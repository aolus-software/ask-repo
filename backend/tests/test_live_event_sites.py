"""Every state write the frontend shows stages exactly one live event.

This is the test the rule "every status write stages" leans on: a new write site added
without staging is caught in review, and the ones that exist are pinned here.
"""

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.audit import AuditRecorder
from app.core.notifications import NotificationType
from app.core.permissions import EDITOR_NAME
from app.db.session import get_sessionmaker
from app.live.bus import InMemoryLiveEventBus
from app.live.events import (
    checklist_module_event,
    mock_data_event,
    notification_event,
    project_event,
)
from app.models.checklist import ChangeSetOrigin, ChangeSetStatus, ChecklistModuleStatus
from app.models.mock_data import MockDataChangeSet, MockDataDataset, MockDataDatasetStatus
from app.models.notification import NotificationEvent
from app.models.project import ProjectStatus
from app.models.user import User
from app.queue.protocol import InMemoryIngestionQueue
from app.repositories.checklist_module import LEASE_SECONDS as CHECKLIST_LEASE_SECONDS
from app.repositories.checklist_module import ChecklistModuleRepository
from app.repositories.mock_data_change_set import MockDataChangeSetRepository
from app.repositories.mock_data_dataset import MockDataDatasetRepository
from app.repositories.project import ProjectRepository
from app.schemas.checklist import ChangeSetApplyRequest
from app.schemas.mock_data import MockDataChangeSetApplyRequest, MockDataGenerationRequest
from app.services.checklist_change_set import ChecklistChangeSetService
from app.services.mock_data_change_set import MockDataChangeSetService
from app.services.mock_data_dataset import MockDataDatasetService
from app.services.notification_fanout import NotificationFanout
from tests.conftest import GrantMembership
from tests.factories import (
    create_checklist_change_set,
    create_checklist_module,
    create_project,
    create_user,
)
from tests.helpers import authenticated, checklist_module_service


def _add_checklist_operation(operation_id: uuid.UUID) -> dict[str, object]:
    return {
        "op": "add",
        "id": str(operation_id),
        "feature": "Login",
        "testName": "Rejects a wrong password",
        "expectedResult": "401 INVALID_CREDENTIALS",
        "citations": None,
        "rationale": "The handler raises on a bcrypt mismatch.",
    }


def _add_mock_data_operation(operation_id: uuid.UUID) -> dict[str, object]:
    return {
        "op": "add",
        "id": str(operation_id),
        "recordId": None,
        "fields": {"name": "Acme"},
        "changes": None,
        "rationale": "r",
    }


# --- app/repositories/project.py -------------------------------------------------


async def test_project_set_status_stages_a_project_event(
    db_session: AsyncSession, live_bus: InMemoryLiveEventBus
) -> None:
    project = await create_project(db_session, grant_owner=False)
    await db_session.commit()
    live_bus.published.clear()

    await ProjectRepository(db_session).set_status(
        project_id=project.id, status=ProjectStatus.INDEXING
    )
    await db_session.commit()

    assert live_bus.published == [project_event(project.id)]


async def test_a_refused_claim_stages_nothing(
    db_session: AsyncSession, live_bus: InMemoryLiveEventBus
) -> None:
    await create_project(db_session, grant_owner=False, status=ProjectStatus.FAILED)
    await db_session.commit()
    live_bus.published.clear()

    claimed = await ProjectRepository(db_session).claim(
        project_id=uuid.uuid4(), job_id=uuid.uuid4(), worker_id="w", lease_seconds=60
    )
    await db_session.commit()

    assert claimed is False
    assert live_bus.published == []


async def test_project_claim_stages_a_project_event(
    db_session: AsyncSession, live_bus: InMemoryLiveEventBus
) -> None:
    project = await create_project(db_session, grant_owner=False)
    await db_session.commit()
    live_bus.published.clear()

    claimed = await ProjectRepository(db_session).claim(
        project_id=project.id, job_id=uuid.uuid4(), worker_id="w", lease_seconds=60
    )
    await db_session.commit()

    assert claimed is True
    assert live_bus.published == [project_event(project.id)]


async def test_project_release_stages_a_project_event(
    db_session: AsyncSession, live_bus: InMemoryLiveEventBus
) -> None:
    project = await create_project(db_session, grant_owner=False)
    await db_session.commit()
    job_id = uuid.uuid4()
    await ProjectRepository(db_session).claim(
        project_id=project.id, job_id=job_id, worker_id="w", lease_seconds=60
    )
    await db_session.commit()
    live_bus.published.clear()

    released = await ProjectRepository(db_session).release(
        project_id=project.id, job_id=job_id, worker_id="w", status=ProjectStatus.READY
    )
    await db_session.commit()

    assert released is True
    assert live_bus.published == [project_event(project.id)]


async def test_project_abandon_stages_a_project_event(
    db_session: AsyncSession, live_bus: InMemoryLiveEventBus
) -> None:
    project = await create_project(db_session, grant_owner=False)
    await db_session.commit()
    job_id = uuid.uuid4()
    await ProjectRepository(db_session).claim(
        project_id=project.id, job_id=job_id, worker_id="w", lease_seconds=60
    )
    await db_session.commit()
    live_bus.published.clear()

    abandoned = await ProjectRepository(db_session).abandon(project_id=project.id, worker_id="w")
    await db_session.commit()

    assert abandoned is True
    assert live_bus.published == [project_event(project.id)]


# --- app/services/project.py -------------------------------------------------------


async def test_project_create_stages_a_project_event(
    authed_client: AsyncClient, live_bus: InMemoryLiveEventBus
) -> None:
    response = await authed_client.post(
        "/projects", json={"repoUrl": "https://github.com/acme/repo.git"}
    )
    assert response.status_code == 201
    project_id = uuid.UUID(response.json()["id"])

    assert project_event(project_id) in live_bus.published


async def test_project_reindex_stages_a_project_event(
    db_session: AsyncSession,
    authed_client: AsyncClient,
    live_bus: InMemoryLiveEventBus,
    authed_user: User,
) -> None:
    project = await create_project(
        db_session, created_by=authed_user.id, status=ProjectStatus.READY
    )
    await db_session.commit()
    live_bus.published.clear()

    response = await authed_client.post(f"/projects/{project.id}/reindex")

    assert response.status_code == 202
    assert response.json()["enqueued"] is True
    assert project_event(project.id) in live_bus.published


async def test_project_delete_stages_a_project_event(
    authed_client: AsyncClient, live_bus: InMemoryLiveEventBus
) -> None:
    created = await authed_client.post(
        "/projects", json={"repoUrl": "https://github.com/acme/repo.git"}
    )
    project_id = uuid.UUID(created.json()["id"])
    live_bus.published.clear()

    response = await authed_client.delete(f"/projects/{project_id}")

    assert response.status_code == 204
    assert project_event(project_id) in live_bus.published


# --- app/repositories/checklist_module.py ------------------------------------------


async def test_checklist_module_claim_stages_a_checklist_module_event(
    db_session: AsyncSession, live_bus: InMemoryLiveEventBus
) -> None:
    module = await create_checklist_module(db_session)
    await db_session.commit()
    live_bus.published.clear()

    claimed = await ChecklistModuleRepository(db_session).claim(
        module_id=module.id,
        job_id=uuid.uuid4(),
        worker_id="w",
        lease_seconds=CHECKLIST_LEASE_SECONDS,
    )
    await db_session.commit()

    assert claimed is True
    assert live_bus.published == [checklist_module_event(module.id, module.project_id)]


async def test_checklist_module_release_stages_a_checklist_module_event(
    db_session: AsyncSession, live_bus: InMemoryLiveEventBus
) -> None:
    module = await create_checklist_module(db_session)
    await db_session.commit()
    job_id = uuid.uuid4()
    repository = ChecklistModuleRepository(db_session)
    await repository.claim(
        module_id=module.id, job_id=job_id, worker_id="w", lease_seconds=CHECKLIST_LEASE_SECONDS
    )
    await db_session.commit()
    live_bus.published.clear()

    released = await repository.release(
        module_id=module.id,
        job_id=job_id,
        worker_id="w",
        status=ChecklistModuleStatus.REVIEW,
    )
    await db_session.commit()

    assert released is True
    assert live_bus.published == [checklist_module_event(module.id, module.project_id)]


async def test_checklist_module_mark_in_review_stages_a_checklist_module_event(
    db_session: AsyncSession, live_bus: InMemoryLiveEventBus
) -> None:
    module = await create_checklist_module(db_session)
    await db_session.commit()
    live_bus.published.clear()

    await ChecklistModuleRepository(db_session).mark_in_review(module.id)
    await db_session.commit()

    assert live_bus.published == [checklist_module_event(module.id, module.project_id)]


async def test_checklist_module_defer_stages_a_checklist_module_event(
    db_session: AsyncSession, live_bus: InMemoryLiveEventBus
) -> None:
    module = await create_checklist_module(db_session, status=ChecklistModuleStatus.GENERATING)
    repository = ChecklistModuleRepository(db_session)
    await repository.claim(
        module_id=module.id,
        job_id=uuid.uuid4(),
        worker_id="w",
        lease_seconds=CHECKLIST_LEASE_SECONDS,
    )
    await db_session.commit()
    live_bus.published.clear()

    deferred = await repository.defer(module_id=module.id, worker_id="w", hold_seconds=60)
    await db_session.commit()

    assert deferred is True
    assert live_bus.published == [checklist_module_event(module.id, module.project_id)]


async def test_checklist_module_claim_stranded_stages_a_checklist_module_event(
    db_session: AsyncSession, live_bus: InMemoryLiveEventBus
) -> None:
    module = await create_checklist_module(db_session, status=ChecklistModuleStatus.GENERATING)
    module.lease_expires_at = datetime.now(UTC) - timedelta(seconds=10)
    module.updated_at = datetime.now(UTC) - timedelta(seconds=600)
    await db_session.commit()
    live_bus.published.clear()

    stranded = await ChecklistModuleRepository(db_session).claim_stranded(
        generating_older_than_seconds=120
    )
    await db_session.commit()

    assert stranded == [module.id]
    assert live_bus.published == [checklist_module_event(module.id, module.project_id)]


# --- app/services/checklist_module.py: the generate request ------------------------


async def test_checklist_module_generation_request_stages_a_checklist_module_event(
    db_session: AsyncSession, live_bus: InMemoryLiveEventBus, grant_membership: GrantMembership
) -> None:
    project = await create_project(db_session, status=ProjectStatus.READY)
    project.embedding_collection = "col"
    module = await create_checklist_module(
        db_session, project_id=project.id, source_path="backend/app/api/routes"
    )
    actor = await create_user(db_session)
    await grant_membership(actor.id, project.id, EDITOR_NAME)
    await db_session.commit()
    live_bus.published.clear()

    service = checklist_module_service(db_session)
    await service.request_generation(
        module.id, actor=await authenticated(db_session, actor), queue=InMemoryIngestionQueue()
    )

    assert checklist_module_event(module.id, project.id) in live_bus.published


# --- app/services/checklist_change_set.py: apply ------------------------------------


async def test_checklist_change_set_apply_stages_a_checklist_module_event(
    db_session: AsyncSession, live_bus: InMemoryLiveEventBus, grant_membership: GrantMembership
) -> None:
    module = await create_checklist_module(db_session)
    operation_id = uuid.uuid4()
    change_set = await create_checklist_change_set(
        db_session, module_id=module.id, operations=[_add_checklist_operation(operation_id)]
    )
    reviewer = await create_user(db_session)
    await grant_membership(reviewer.id, module.project_id, EDITOR_NAME)
    await db_session.commit()
    live_bus.published.clear()

    service = ChecklistChangeSetService(
        db_session, Settings(), recorder=AuditRecorder(get_sessionmaker())
    )
    await service.apply(
        change_set.id, ChangeSetApplyRequest(), actor=await authenticated(db_session, reviewer)
    )

    assert checklist_module_event(module.id, module.project_id) in live_bus.published


# --- app/repositories/mock_data_dataset.py ------------------------------------------


async def test_mock_data_dataset_claim_stages_a_mock_data_event(
    db_session: AsyncSession, live_bus: InMemoryLiveEventBus
) -> None:
    module = await create_checklist_module(db_session)
    repository = MockDataDatasetRepository(db_session)
    dataset = await repository.get_or_create_for_module(module.id)
    await db_session.commit()
    live_bus.published.clear()

    claimed = await repository.claim(
        dataset_id=dataset.id, job_id=uuid.uuid4(), worker_id="w", lease_seconds=300
    )
    await db_session.commit()

    assert claimed is True
    assert live_bus.published == [mock_data_event(module.id, module.project_id)]


async def test_mock_data_dataset_release_stages_a_mock_data_event(
    db_session: AsyncSession, live_bus: InMemoryLiveEventBus
) -> None:
    module = await create_checklist_module(db_session)
    repository = MockDataDatasetRepository(db_session)
    dataset = await repository.get_or_create_for_module(module.id)
    await db_session.commit()
    job_id = uuid.uuid4()
    await repository.claim(dataset_id=dataset.id, job_id=job_id, worker_id="w", lease_seconds=300)
    await db_session.commit()
    live_bus.published.clear()

    released = await repository.release(
        dataset_id=dataset.id, job_id=job_id, worker_id="w", status=MockDataDatasetStatus.READY
    )
    await db_session.commit()

    assert released is True
    assert live_bus.published == [mock_data_event(module.id, module.project_id)]


async def test_mock_data_dataset_mark_in_review_stages_a_mock_data_event(
    db_session: AsyncSession, live_bus: InMemoryLiveEventBus
) -> None:
    module = await create_checklist_module(db_session)
    repository = MockDataDatasetRepository(db_session)
    dataset = await repository.get_or_create_for_module(module.id)
    await db_session.commit()
    live_bus.published.clear()

    await repository.mark_in_review(dataset.id)
    await db_session.commit()

    assert live_bus.published == [mock_data_event(module.id, module.project_id)]


async def test_mock_data_dataset_defer_stages_a_mock_data_event(
    db_session: AsyncSession, live_bus: InMemoryLiveEventBus
) -> None:
    module = await create_checklist_module(db_session)
    repository = MockDataDatasetRepository(db_session)
    dataset = await repository.get_or_create_for_module(module.id)
    await repository.claim(
        dataset_id=dataset.id, job_id=uuid.uuid4(), worker_id="w", lease_seconds=300
    )
    await db_session.commit()
    live_bus.published.clear()

    deferred = await repository.defer(dataset_id=dataset.id, worker_id="w", hold_seconds=60)
    await db_session.commit()

    assert deferred is True
    assert live_bus.published == [mock_data_event(module.id, module.project_id)]


async def test_mock_data_dataset_claim_stranded_stages_a_mock_data_event(
    db_session: AsyncSession, live_bus: InMemoryLiveEventBus
) -> None:
    module = await create_checklist_module(db_session)
    repository = MockDataDatasetRepository(db_session)
    dataset = await repository.get_or_create_for_module(module.id)
    dataset.status = MockDataDatasetStatus.GENERATING.value
    dataset.updated_at = datetime.now(UTC) - timedelta(seconds=999)
    await db_session.commit()
    live_bus.published.clear()

    stranded = await repository.claim_stranded(generating_older_than_seconds=120)
    await db_session.commit()

    assert stranded == [dataset.id]
    assert live_bus.published == [mock_data_event(module.id, module.project_id)]


# --- app/services/mock_data_dataset.py: the generate request ------------------------


async def test_mock_data_generation_request_stages_a_mock_data_event(
    db_session: AsyncSession, live_bus: InMemoryLiveEventBus, grant_membership: GrantMembership
) -> None:
    project = await create_project(db_session, status=ProjectStatus.READY)
    project.embedding_collection = "col"
    module = await create_checklist_module(db_session, project_id=project.id)
    actor = await create_user(db_session)
    await grant_membership(actor.id, project.id, EDITOR_NAME)
    await db_session.commit()
    live_bus.published.clear()

    service = MockDataDatasetService(
        db_session, Settings(), recorder=AuditRecorder(get_sessionmaker())
    )
    await service.request_generation(
        module.id,
        MockDataGenerationRequest(),
        actor=await authenticated(db_session, actor),
        queue=InMemoryIngestionQueue(),
    )

    assert mock_data_event(module.id, project.id) in live_bus.published


# --- app/services/mock_data_change_set.py: apply ------------------------------------


async def test_mock_data_change_set_apply_stages_a_mock_data_event(
    db_session: AsyncSession, live_bus: InMemoryLiveEventBus, grant_membership: GrantMembership
) -> None:
    project = await create_project(db_session, status=ProjectStatus.READY)
    project.embedding_collection = "col"
    module = await create_checklist_module(db_session, project_id=project.id)
    dataset = MockDataDataset(id=uuid.uuid4(), checklist_module_id=module.id, status="review")
    db_session.add(dataset)
    operation_id = uuid.uuid4()
    change_set = await MockDataChangeSetRepository(db_session).add(
        MockDataChangeSet(
            id=uuid.uuid4(),
            checklist_module_id=module.id,
            origin=ChangeSetOrigin.GENERATION.value,
            summary="1 record",
            operations=[_add_mock_data_operation(operation_id)],
            status=ChangeSetStatus.PENDING.value,
            created_by=module.created_by,
        )
    )
    actor = await create_user(db_session)
    await grant_membership(actor.id, project.id, EDITOR_NAME)
    await db_session.commit()
    live_bus.published.clear()

    service = MockDataChangeSetService(
        db_session, Settings(), recorder=AuditRecorder(get_sessionmaker())
    )
    await service.apply(
        change_set.id,
        MockDataChangeSetApplyRequest(),
        actor=await authenticated(db_session, actor),
    )

    assert mock_data_event(module.id, project.id) in live_bus.published


# --- app/services/notification_fanout.py --------------------------------------------


async def test_raise_event_with_recipients_stages_a_notification_event(
    db_session: AsyncSession, live_bus: InMemoryLiveEventBus, grant_membership: GrantMembership
) -> None:
    project = await create_project(db_session, grant_owner=False)
    owner = await create_user(db_session)
    await grant_membership(owner.id, project.id, "owner")
    await db_session.commit()
    live_bus.published.clear()

    await NotificationFanout(db_session).raise_event(
        event_type=NotificationType.PROJECT_READY,
        project_id=project.id,
        actor_user_id=None,
        target_id=project.id,
        details={"projectName": "api", "fileCount": 3, "chunkCount": 9},
    )
    await db_session.commit()

    event_id = (
        await db_session.execute(
            select(NotificationEvent.id).where(NotificationEvent.project_id == project.id)
        )
    ).scalar_one()
    assert live_bus.published == [notification_event(event_id, project.id, [owner.id])]


async def test_raise_event_with_no_recipients_stages_nothing(
    db_session: AsyncSession, live_bus: InMemoryLiveEventBus
) -> None:
    project = await create_project(db_session, grant_owner=False)
    await db_session.commit()
    live_bus.published.clear()

    await NotificationFanout(db_session).raise_event(
        event_type=NotificationType.PROJECT_READY,
        project_id=project.id,
        actor_user_id=None,
        target_id=project.id,
        details={"projectName": "api", "fileCount": 3, "chunkCount": 9},
    )
    await db_session.commit()

    assert live_bus.published == []

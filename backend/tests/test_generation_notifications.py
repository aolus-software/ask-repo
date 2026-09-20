"""A finished generation tells the people who can review it.

This is the case `docs/PRD.md` §2.1 calls the whole point: the reviewer who has to act
is routinely not the person who started the generation, so `CHANGESET_APPLY` -- not
project membership alone -- is the audience.

Reuses the harnesses `tests/test_checklist_generator.py` and
`tests/test_mockdata_generator.py` already built (`tests.factories` and
`tests.fakes`), rather than a third one.
"""

import uuid
from typing import cast

from langchain_core.language_models import BaseChatModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.checklist.generator import ChecklistGenerator
from app.checklist.model_output import (
    FileObservations,
    ObservedBehaviour,
    ProposedChangeSet,
    ProposedOperation,
)
from app.config import Settings
from app.core.notifications import NotificationType
from app.core.permissions import EDITOR_NAME, VIEWER_NAME
from app.ingestion.chunker import Chunk
from app.ingestion.vector_store import InMemoryVectorStore
from app.mockdata.generator import MockDataGenerator
from app.mockdata.model_output import ProposedMockDataOperation, ProposedMockDataSet
from app.models.notification import Notification, NotificationEvent
from app.models.user import User
from app.repositories.checklist_module import ChecklistModuleRepository
from app.repositories.mock_data_dataset import MockDataDatasetRepository
from tests.conftest import GrantMembership
from tests.factories import create_checklist_module, create_project
from tests.fakes import StructuredScriptedChatModel


async def _index(store: InMemoryVectorStore, *, project_id: uuid.UUID, path: str) -> None:
    await store.upsert(
        project_id=project_id,
        generation=1,
        chunks=[
            Chunk(
                file_path=path,
                start_line=1,
                end_line=40,
                language="python",
                symbol=None,
                chunk_index=0,
                text="def login(user):\n    raise Unauthorized()\n",
            )
        ],
        vectors=[[0.1] * 8],
        commit_sha="abc123",
    )


async def _recipients(db_session: AsyncSession, event_type: NotificationType) -> set[uuid.UUID]:
    rows = await db_session.execute(
        select(Notification.user_id)
        .join(NotificationEvent, NotificationEvent.id == Notification.event_id)
        .where(NotificationEvent.event_type == event_type.value)
    )
    return set(rows.scalars().all())


async def test_checklist_generation_notifies_reviewers_not_viewers(
    db_session: AsyncSession,
    grant_membership: GrantMembership,
    user_a: User,
    user_b: User,
) -> None:
    project = await create_project(db_session, grant_owner=False)
    project.active_generation = 1
    project.embedding_collection = "in-memory"
    module = await create_checklist_module(
        db_session, project_id=project.id, source_path="app/auth"
    )
    await grant_membership(user_a.id, project.id, EDITOR_NAME)
    await grant_membership(user_b.id, project.id, VIEWER_NAME)

    store = InMemoryVectorStore(dimensions=8)
    await _index(store, project_id=project.id, path="app/auth/login.py")

    chat = StructuredScriptedChatModel(
        {
            FileObservations: [
                FileObservations(
                    behaviours=[
                        ObservedBehaviour(
                            description="raises Unauthorized", start_line=2, end_line=2
                        )
                    ]
                )
            ],
            ProposedChangeSet: [
                ProposedChangeSet(
                    summary="1 added",
                    operations=[
                        ProposedOperation(
                            kind="positive",
                            op="add",
                            feature="Login",
                            test_name="Rejects an unknown user",
                            expected_result="401 Unauthorized",
                            rationale="The handler raises Unauthorized.",
                            citation_paths=["app/auth/login.py"],
                        )
                    ],
                )
            ],
        }
    )
    generator = ChecklistGenerator(
        db_session, Settings(), store_factory=lambda _: store, chat_model=cast(BaseChatModel, chat)
    )
    job_id = uuid.uuid4()
    await ChecklistModuleRepository(db_session).claim(
        module_id=module.id, job_id=job_id, worker_id="w1", lease_seconds=300
    )

    await generator.run(module_id=module.id, job_id=job_id, worker_id="w1")

    recipients = await _recipients(db_session, NotificationType.CHECKLIST_CHANGE_SET_PENDING)
    assert user_a.id in recipients
    assert user_b.id not in recipients


async def test_mock_data_generation_notifies_reviewers_not_viewers(
    db_session: AsyncSession,
    grant_membership: GrantMembership,
    user_a: User,
    user_b: User,
) -> None:
    project = await create_project(db_session, grant_owner=False)
    project.active_generation = 1
    project.embedding_collection = "in-memory"
    module = await create_checklist_module(
        db_session, project_id=project.id, source_path="app/features/project"
    )
    await grant_membership(user_a.id, project.id, EDITOR_NAME)
    await grant_membership(user_b.id, project.id, VIEWER_NAME)

    store = InMemoryVectorStore(dimensions=8)
    await _index(store, project_id=project.id, path="app/features/project/models.py")

    chat = StructuredScriptedChatModel(
        {
            ProposedMockDataSet: [
                ProposedMockDataSet(
                    schema_found=True,
                    field_keys=["name", "start", "end"],
                    summary="1 record added",
                    operations=[
                        ProposedMockDataOperation(
                            op="add",
                            fields={"name": "Acme", "start": "2026-01-01", "end": "2026-06-01"},
                            rationale="matches the Project model",
                        )
                    ],
                )
            ]
        }
    )
    generator = MockDataGenerator(
        db_session,
        Settings(),
        store_factory=lambda _: store,
        chat_model=cast(BaseChatModel, chat),
    )
    job_id = uuid.uuid4()
    datasets = MockDataDatasetRepository(db_session)
    dataset = await datasets.get_or_create_for_module(module.id)
    await db_session.commit()
    await datasets.claim(dataset_id=dataset.id, job_id=job_id, worker_id="w1", lease_seconds=300)
    await db_session.commit()

    await generator.run(dataset_id=dataset.id, job_id=job_id, worker_id="w1", count=1)

    recipients = await _recipients(db_session, NotificationType.MOCK_DATA_CHANGE_SET_PENDING)
    assert user_a.id in recipients
    assert user_b.id not in recipients

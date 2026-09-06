"""Dataset reads, generation trigger, and the refinement chat."""

import uuid

import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.errors import AppError, ErrorCode
from app.models.checklist import ChangeSetOrigin, ChangeSetStatus
from app.models.mock_data import MockDataChangeSet, MockDataDatasetStatus
from app.queue.protocol import InMemoryIngestionQueue
from app.repositories.mock_data_change_set import MockDataChangeSetRepository
from app.schemas.mock_data import MockDataGenerationRequest
from app.services.mock_data_dataset import MockDataDatasetService
from tests.factories import create_checklist_module, create_project, create_user
from tests.helpers import authenticated


async def test_get_returns_empty_summary_before_any_generation(
    db_session: AsyncSession,
) -> None:
    """Before the first generation, no dataset row exists and that is not a 404."""
    project = await create_project(db_session)
    project.embedding_collection = "col"
    module = await create_checklist_module(db_session, project_id=project.id)
    service = MockDataDatasetService(db_session, Settings())

    detail = await service.get(module.id, actor=authenticated(await create_user(db_session)))

    assert detail.status == MockDataDatasetStatus.EMPTY
    assert detail.record_count == 0
    assert detail.records == []


async def test_request_generation_refuses_when_already_generating(
    db_session: AsyncSession,
) -> None:
    """Cannot request generation while one is in progress."""
    project = await create_project(db_session)
    project.embedding_collection = "col"
    module = await create_checklist_module(db_session, project_id=project.id)
    service = MockDataDatasetService(db_session, Settings())
    queue = InMemoryIngestionQueue()
    user = await create_user(db_session)
    await service.request_generation(
        module.id, MockDataGenerationRequest(), actor=authenticated(user), queue=queue
    )

    with pytest.raises(AppError) as excinfo:
        await service.request_generation(
            module.id, MockDataGenerationRequest(), actor=authenticated(user), queue=queue
        )
    assert excinfo.value.status_code == status.HTTP_409_CONFLICT
    assert excinfo.value.code == ErrorCode.MOCK_DATA_GENERATION_IN_PROGRESS


async def test_request_generation_refuses_a_pending_change_set(
    db_session: AsyncSession,
) -> None:
    """Cannot request generation while changes are pending."""
    project = await create_project(db_session)
    project.embedding_collection = "col"
    module = await create_checklist_module(db_session, project_id=project.id)
    service = MockDataDatasetService(db_session, Settings())
    user = await create_user(db_session)
    await service.datasets.get_or_create_for_module(module.id)
    await db_session.commit()
    await MockDataChangeSetRepository(db_session).add(
        MockDataChangeSet(
            id=uuid.uuid4(),
            checklist_module_id=module.id,
            origin=ChangeSetOrigin.GENERATION.value,
            summary="s",
            operations=[],
            status=ChangeSetStatus.PENDING.value,
            created_by=user.id,
        )
    )
    await db_session.commit()

    with pytest.raises(AppError) as excinfo:
        await service.request_generation(
            module.id,
            MockDataGenerationRequest(),
            actor=authenticated(user),
            queue=InMemoryIngestionQueue(),
        )
    assert excinfo.value.code == ErrorCode.MOCK_DATA_CHANGE_SET_PENDING

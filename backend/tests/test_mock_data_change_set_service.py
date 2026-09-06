"""Applying and discarding a mock-data change set."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.errors import AppError, ErrorCode
from app.models.checklist import ChangeSetOrigin, ChangeSetStatus
from app.models.mock_data import MockDataChangeSet, MockDataDataset, MockDataRecord
from app.models.project import ProjectStatus
from app.repositories.mock_data_change_set import MockDataChangeSetRepository
from app.repositories.mock_data_record import MockDataRecordRepository
from app.schemas.mock_data import MockDataChangeSetApplyRequest
from app.services.mock_data_change_set import MockDataChangeSetService
from tests.factories import create_checklist_module, create_project, create_user
from tests.helpers import authenticated


async def test_apply_add_creates_a_record(db_session: AsyncSession) -> None:
    """Adding an operation creates a new record with the proposed fields."""
    project = await create_project(db_session, status=ProjectStatus.READY)
    project.embedding_collection = "col"
    module = await create_checklist_module(db_session, project_id=project.id)

    # Create a mock dataset for the module
    dataset = MockDataDataset(
        id=uuid.uuid4(),
        checklist_module_id=module.id,
        status="review",
    )
    db_session.add(dataset)

    op_id = uuid.uuid4()
    change_set = await MockDataChangeSetRepository(db_session).add(
        MockDataChangeSet(
            id=uuid.uuid4(),
            checklist_module_id=module.id,
            origin=ChangeSetOrigin.GENERATION.value,
            summary="1 record",
            operations=[
                {
                    "op": "add",
                    "id": str(op_id),
                    "recordId": None,
                    "fields": {"name": "Acme"},
                    "changes": None,
                    "rationale": "r",
                }
            ],
            status=ChangeSetStatus.PENDING.value,
            created_by=module.created_by,
        )
    )
    await db_session.commit()

    actor = await create_user(db_session)
    service = MockDataChangeSetService(db_session, Settings())
    result = await service.apply(
        change_set.id, MockDataChangeSetApplyRequest(), actor=authenticated(actor)
    )

    assert len(result.records) == 1
    assert result.records[0].fields == {"name": "Acme"}
    assert result.skipped_operation_ids == []


async def test_apply_update_merges_into_existing_fields(db_session: AsyncSession) -> None:
    """Updating an operation merges changes into the existing fields."""
    project = await create_project(db_session, status=ProjectStatus.READY)
    project.embedding_collection = "col"
    module = await create_checklist_module(db_session, project_id=project.id)
    creator = await create_user(db_session)

    # Create a mock dataset for the module
    dataset = MockDataDataset(
        id=uuid.uuid4(),
        checklist_module_id=module.id,
        status="review",
    )
    db_session.add(dataset)

    record = await MockDataRecordRepository(db_session).add(
        MockDataRecord(
            id=uuid.uuid4(),
            checklist_module_id=module.id,
            fields={"name": "Acme", "start": "2026-01-01"},
            created_by=creator.id,
        )
    )
    await db_session.commit()

    change_set = await MockDataChangeSetRepository(db_session).add(
        MockDataChangeSet(
            id=uuid.uuid4(),
            checklist_module_id=module.id,
            origin=ChangeSetOrigin.CHAT.value,
            summary="update",
            operations=[
                {
                    "op": "update",
                    "id": str(uuid.uuid4()),
                    "recordId": str(record.id),
                    "fields": None,
                    "changes": {"start": "2026-03-01"},
                    "rationale": "r",
                }
            ],
            status=ChangeSetStatus.PENDING.value,
            created_by=creator.id,
        )
    )
    await db_session.commit()

    actor = await create_user(db_session)
    service = MockDataChangeSetService(db_session, Settings())
    result = await service.apply(
        change_set.id, MockDataChangeSetApplyRequest(), actor=authenticated(actor)
    )

    assert result.records[0].fields == {"name": "Acme", "start": "2026-03-01"}


async def test_apply_twice_conflicts(db_session: AsyncSession) -> None:
    """Applying a change set twice raises a conflict error."""
    project = await create_project(db_session, status=ProjectStatus.READY)
    project.embedding_collection = "col"
    module = await create_checklist_module(db_session, project_id=project.id)
    creator = await create_user(db_session)

    # Create a mock dataset for the module
    dataset = MockDataDataset(
        id=uuid.uuid4(),
        checklist_module_id=module.id,
        status="review",
    )
    db_session.add(dataset)

    change_set = await MockDataChangeSetRepository(db_session).add(
        MockDataChangeSet(
            id=uuid.uuid4(),
            checklist_module_id=module.id,
            origin=ChangeSetOrigin.GENERATION.value,
            summary="s",
            operations=[],
            status=ChangeSetStatus.PENDING.value,
            created_by=creator.id,
        )
    )
    await db_session.commit()

    actor = await create_user(db_session)
    service = MockDataChangeSetService(db_session, Settings())
    await service.apply(change_set.id, MockDataChangeSetApplyRequest(), actor=authenticated(actor))

    with pytest.raises(AppError) as excinfo:
        await service.apply(
            change_set.id, MockDataChangeSetApplyRequest(), actor=authenticated(actor)
        )
    assert excinfo.value.code == ErrorCode.MOCK_DATA_CHANGE_SET_ALREADY_RESOLVED

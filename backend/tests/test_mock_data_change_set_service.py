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
from tests.factories import (
    create_checklist_module,
    create_mock_data_record,
    create_project,
    create_user,
)
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


async def test_apply_is_selective_when_operation_ids_are_given(db_session: AsyncSession) -> None:
    """Only selected operations are applied; unselected ones are left untouched."""
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

    keep, drop = uuid.uuid4(), uuid.uuid4()
    change_set = await MockDataChangeSetRepository(db_session).add(
        MockDataChangeSet(
            id=uuid.uuid4(),
            checklist_module_id=module.id,
            origin=ChangeSetOrigin.GENERATION.value,
            summary="2 records",
            operations=[
                {
                    "op": "add",
                    "id": str(keep),
                    "recordId": None,
                    "fields": {"name": "Kept"},
                    "changes": None,
                    "rationale": "Keep this one.",
                },
                {
                    "op": "add",
                    "id": str(drop),
                    "recordId": None,
                    "fields": {"name": "Dropped"},
                    "changes": None,
                    "rationale": "Drop this one.",
                },
            ],
            status=ChangeSetStatus.PENDING.value,
            created_by=module.created_by,
        )
    )
    await db_session.commit()

    actor = await create_user(db_session)
    service = MockDataChangeSetService(db_session, Settings())
    result = await service.apply(
        change_set.id,
        MockDataChangeSetApplyRequest(operation_ids=[keep]),
        actor=authenticated(actor),
    )

    assert len(result.records) == 1
    assert result.records[0].fields == {"name": "Kept"}


async def test_remove_operation_soft_deletes_a_record(db_session: AsyncSession) -> None:
    """A remove operation soft-deletes the target record."""
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

    record = await create_mock_data_record(db_session, module_id=module.id, created_by=creator.id)
    record_id = record.id
    await db_session.commit()

    remove_op_id = uuid.uuid4()
    change_set = await MockDataChangeSetRepository(db_session).add(
        MockDataChangeSet(
            id=uuid.uuid4(),
            checklist_module_id=module.id,
            origin=ChangeSetOrigin.GENERATION.value,
            summary="remove record",
            operations=[
                {
                    "op": "remove",
                    "id": str(remove_op_id),
                    "recordId": str(record_id),
                    "fields": None,
                    "changes": None,
                    "rationale": "Remove this record.",
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

    assert len(result.records) == 1
    assert result.records[0].id == record_id
    # Verify record was actually soft-deleted by checking the list excludes it
    remaining = await MockDataRecordRepository(db_session).list_for_module(module.id)
    assert remaining == []


async def test_cross_module_operation_is_skipped(db_session: AsyncSession) -> None:
    """An operation targeting a record from another module is skipped."""
    project = await create_project(db_session, status=ProjectStatus.READY)
    project.embedding_collection = "col"
    record_module = await create_checklist_module(db_session, project_id=project.id)
    target_module = await create_checklist_module(db_session, project_id=project.id)
    creator = await create_user(db_session)

    # Create mock datasets
    for mod in [record_module, target_module]:
        dataset = MockDataDataset(
            id=uuid.uuid4(),
            checklist_module_id=mod.id,
            status="review",
        )
        db_session.add(dataset)

    record = await create_mock_data_record(
        db_session, module_id=record_module.id, created_by=creator.id
    )
    await db_session.commit()

    cross_module_op = uuid.uuid4()
    good_op = uuid.uuid4()
    change_set = await MockDataChangeSetRepository(db_session).add(
        MockDataChangeSet(
            id=uuid.uuid4(),
            checklist_module_id=target_module.id,
            origin=ChangeSetOrigin.GENERATION.value,
            summary="mixed operations",
            operations=[
                {
                    "op": "update",
                    "id": str(cross_module_op),
                    "recordId": str(record.id),
                    "fields": None,
                    "changes": {"name": "Mutated"},
                    "rationale": "Item belongs to different module.",
                },
                {
                    "op": "add",
                    "id": str(good_op),
                    "recordId": None,
                    "fields": {"name": "Good"},
                    "changes": None,
                    "rationale": "Good operation.",
                },
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

    assert result.skipped_operation_ids == [cross_module_op]
    assert len(result.records) == 1
    assert result.records[0].fields == {"name": "Good"}
    await db_session.refresh(record)
    assert record.fields != {"name": "Mutated"}


async def test_discard_writes_nothing_and_settles_dataset(db_session: AsyncSession) -> None:
    """Discard returns DISCARDED status, writes no records, and settles the dataset."""
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
            summary="should be discarded",
            operations=[
                {
                    "op": "add",
                    "id": str(uuid.uuid4()),
                    "recordId": None,
                    "fields": {"name": "Never written"},
                    "changes": None,
                    "rationale": "This operation is discarded.",
                }
            ],
            status=ChangeSetStatus.PENDING.value,
            created_by=creator.id,
        )
    )
    await db_session.commit()

    actor = await create_user(db_session)
    service = MockDataChangeSetService(db_session, Settings())
    resolved = await service.discard(change_set.id, actor=authenticated(actor))

    assert resolved.status == ChangeSetStatus.DISCARDED
    # Verify no records were written
    records = await MockDataRecordRepository(db_session).list_for_module(module.id)
    assert records == []
    # Verify dataset settled to empty
    await db_session.refresh(dataset)
    assert dataset.status == "empty"


async def test_change_set_not_found_returns_404(db_session: AsyncSession) -> None:
    """A non-existent change set returns 404."""
    actor = await create_user(db_session)
    service = MockDataChangeSetService(db_session, Settings())

    with pytest.raises(AppError) as excinfo:
        await service.apply(
            uuid.uuid4(), MockDataChangeSetApplyRequest(), actor=authenticated(actor)
        )
    assert excinfo.value.code == ErrorCode.MOCK_DATA_CHANGE_SET_NOT_FOUND


async def test_apply_preserves_the_order_the_model_proposed(db_session: AsyncSession) -> None:
    """Applying several `add` operations in one transaction keeps their proposed order.

    `created_at` is `server_default=func.now()`, and Postgres's `now()` is constant for
    an entire transaction -- every record this apply writes shares one timestamp, so a
    sort that fell back to `created_at, id` would collapse onto the random uuid
    tiebreak. Five records make a coincidental match on that random order roughly
    1-in-120, which is why this reproduces the bug reliably rather than flakily.
    """
    project = await create_project(db_session, status=ProjectStatus.READY)
    project.embedding_collection = "col"
    module = await create_checklist_module(db_session, project_id=project.id)
    creator = await create_user(db_session)

    dataset = MockDataDataset(
        id=uuid.uuid4(),
        checklist_module_id=module.id,
        status="review",
    )
    db_session.add(dataset)

    proposed_names = ["alpha", "bravo", "charlie", "delta", "echo"]
    change_set = await MockDataChangeSetRepository(db_session).add(
        MockDataChangeSet(
            id=uuid.uuid4(),
            checklist_module_id=module.id,
            origin=ChangeSetOrigin.GENERATION.value,
            summary=f"{len(proposed_names)} records",
            operations=[
                {
                    "op": "add",
                    "id": str(uuid.uuid4()),
                    "recordId": None,
                    "fields": {"name": name},
                    "changes": None,
                    "rationale": "r",
                }
                for name in proposed_names
            ],
            status=ChangeSetStatus.PENDING.value,
            created_by=creator.id,
        )
    )
    await db_session.commit()

    actor = await create_user(db_session)
    service = MockDataChangeSetService(db_session, Settings())
    await service.apply(change_set.id, MockDataChangeSetApplyRequest(), actor=authenticated(actor))

    records = await MockDataRecordRepository(db_session).list_for_module(module.id)
    assert [record.fields["name"] for record in records] == proposed_names


async def test_apply_keeps_relative_order_of_a_ticked_subset(db_session: AsyncSession) -> None:
    """Ticking only some proposed operations keeps those in their relative order.

    Position must come from the operation's index within the full `operations` list,
    not a counter over only the accepted ones -- ticking the 1st and 3rd of five
    proposals should not collapse them onto positions 0 and 1.
    """
    project = await create_project(db_session, status=ProjectStatus.READY)
    project.embedding_collection = "col"
    module = await create_checklist_module(db_session, project_id=project.id)
    creator = await create_user(db_session)

    dataset = MockDataDataset(
        id=uuid.uuid4(),
        checklist_module_id=module.id,
        status="review",
    )
    db_session.add(dataset)

    op_ids = [uuid.uuid4() for _ in range(3)]
    proposed_names = ["first", "second", "third"]
    change_set = await MockDataChangeSetRepository(db_session).add(
        MockDataChangeSet(
            id=uuid.uuid4(),
            checklist_module_id=module.id,
            origin=ChangeSetOrigin.GENERATION.value,
            summary="3 records",
            operations=[
                {
                    "op": "add",
                    "id": str(op_id),
                    "recordId": None,
                    "fields": {"name": name},
                    "changes": None,
                    "rationale": "r",
                }
                for op_id, name in zip(op_ids, proposed_names, strict=True)
            ],
            status=ChangeSetStatus.PENDING.value,
            created_by=creator.id,
        )
    )
    await db_session.commit()

    actor = await create_user(db_session)
    service = MockDataChangeSetService(db_session, Settings())
    await service.apply(
        change_set.id,
        MockDataChangeSetApplyRequest(operation_ids=[op_ids[0], op_ids[2]]),
        actor=authenticated(actor),
    )

    records = await MockDataRecordRepository(db_session).list_for_module(module.id)
    assert [record.fields["name"] for record in records] == ["first", "third"]

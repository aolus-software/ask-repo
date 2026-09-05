"""Queries over `mock_data_change_sets` -- proposed record operations."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.checklist import ChangeSetOrigin, ChangeSetStatus
from app.models.mock_data import MockDataChangeSet
from app.repositories.mock_data_change_set import MockDataChangeSetRepository
from tests.factories import create_checklist_module, create_project, create_user


async def test_pending_for_module_finds_the_one_pending_set(
    db_session: AsyncSession,
) -> None:
    module = await create_checklist_module(db_session)
    user = await create_user(db_session)
    repo = MockDataChangeSetRepository(db_session)
    await repo.add(
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

    pending = await repo.pending_for_module(module.id)

    assert pending is not None
    assert pending.status == ChangeSetStatus.PENDING.value


async def test_pending_for_module_returns_none_when_all_resolved(
    db_session: AsyncSession,
) -> None:
    module = await create_checklist_module(db_session)
    user = await create_user(db_session)
    repo = MockDataChangeSetRepository(db_session)
    await repo.add(
        MockDataChangeSet(
            id=uuid.uuid4(),
            checklist_module_id=module.id,
            origin=ChangeSetOrigin.GENERATION.value,
            summary="s",
            operations=[],
            status=ChangeSetStatus.APPLIED.value,
            created_by=user.id,
        )
    )
    await db_session.commit()

    assert await repo.pending_for_module(module.id) is None


async def test_pending_for_module_ignores_resolved_sets(
    db_session: AsyncSession,
) -> None:
    """At most one pending set per module; a resolved one must not block it.

    `created_at` is set explicitly to ensure deterministic ordering, since
    Postgres `now()` is transaction-scoped and rows inserted in one transaction
    would share an identical timestamp.
    """
    module = await create_checklist_module(db_session)
    started = datetime.now(UTC)
    applied = MockDataChangeSet(
        id=uuid.uuid4(),
        checklist_module_id=module.id,
        origin=ChangeSetOrigin.GENERATION.value,
        summary="1 added",
        operations=[],
        status=ChangeSetStatus.APPLIED.value,
        created_by=module.created_by,
        created_at=started + timedelta(seconds=1),
    )
    pending = MockDataChangeSet(
        id=uuid.uuid4(),
        checklist_module_id=module.id,
        origin=ChangeSetOrigin.GENERATION.value,
        summary="1 added",
        operations=[],
        status=ChangeSetStatus.PENDING.value,
        created_by=module.created_by,
        created_at=started,
    )
    db_session.add_all([applied, pending])
    await db_session.commit()
    repository = MockDataChangeSetRepository(db_session)

    found = await repository.pending_for_module(module.id)

    assert found is not None
    assert found.id == pending.id


async def test_list_for_module_returns_newest_first(
    db_session: AsyncSession,
) -> None:
    """Change sets are listed newest-first as the audit trail."""
    module = await create_checklist_module(db_session)
    started = datetime.now(UTC)
    first = MockDataChangeSet(
        id=uuid.uuid4(),
        checklist_module_id=module.id,
        origin=ChangeSetOrigin.GENERATION.value,
        summary="1 added",
        operations=[],
        status=ChangeSetStatus.APPLIED.value,
        created_by=module.created_by,
        created_at=started,
    )
    second = MockDataChangeSet(
        id=uuid.uuid4(),
        checklist_module_id=module.id,
        origin=ChangeSetOrigin.GENERATION.value,
        summary="2 added",
        operations=[],
        status=ChangeSetStatus.APPLIED.value,
        created_by=module.created_by,
        created_at=started + timedelta(seconds=1),
    )
    db_session.add_all([first, second])
    await db_session.commit()
    repository = MockDataChangeSetRepository(db_session)

    rows = await repository.list_for_module(module.id, limit=50)

    assert [row.id for row in rows] == [second.id, first.id]
    assert await repository.list_for_module(module.id, limit=0) == []


async def test_soft_delete_for_module_hides_change_sets(
    db_session: AsyncSession,
) -> None:
    """Soft-deleting a module's change sets hides them from queries."""
    module = await create_checklist_module(db_session)
    user = await create_user(db_session)
    repository = MockDataChangeSetRepository(db_session)
    await repository.add(
        MockDataChangeSet(
            id=uuid.uuid4(),
            checklist_module_id=module.id,
            origin=ChangeSetOrigin.GENERATION.value,
            summary="test",
            operations=[],
            status=ChangeSetStatus.PENDING.value,
            created_by=user.id,
        )
    )
    await db_session.commit()

    count = await repository.soft_delete_for_module(module.id)
    await db_session.commit()

    assert count == 1
    assert await repository.list_for_module(module.id, limit=50) == []
    assert await repository.pending_for_module(module.id) is None


async def test_soft_delete_for_project_cascades(
    db_session: AsyncSession,
) -> None:
    """Soft-deleting a project cascades to all its modules' change sets."""
    project = await create_project(db_session)
    module_a = await create_checklist_module(db_session, project_id=project.id)
    module_b = await create_checklist_module(db_session, project_id=project.id)
    user = await create_user(db_session)
    repository = MockDataChangeSetRepository(db_session)

    await repository.add(
        MockDataChangeSet(
            id=uuid.uuid4(),
            checklist_module_id=module_a.id,
            origin=ChangeSetOrigin.GENERATION.value,
            summary="a",
            operations=[],
            status=ChangeSetStatus.PENDING.value,
            created_by=user.id,
        )
    )
    await repository.add(
        MockDataChangeSet(
            id=uuid.uuid4(),
            checklist_module_id=module_b.id,
            origin=ChangeSetOrigin.GENERATION.value,
            summary="b",
            operations=[],
            status=ChangeSetStatus.PENDING.value,
            created_by=user.id,
        )
    )
    await db_session.commit()

    count = await repository.soft_delete_for_project(project.id)
    await db_session.commit()

    assert count == 2
    assert await repository.list_for_module(module_a.id, limit=50) == []
    assert await repository.list_for_module(module_b.id, limit=50) == []

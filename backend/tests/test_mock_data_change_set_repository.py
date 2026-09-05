"""Queries over `mock_data_change_sets` -- proposed record operations."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.checklist import ChangeSetOrigin, ChangeSetStatus
from app.models.mock_data import MockDataChangeSet
from app.repositories.mock_data_change_set import MockDataChangeSetRepository
from tests.factories import create_checklist_module, create_user


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

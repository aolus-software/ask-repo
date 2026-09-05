"""Queries over `mock_data_records` -- samples generated for a module."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mock_data import MockDataRecord
from app.repositories.mock_data_record import MockDataRecordRepository
from tests.factories import create_checklist_module, create_user


async def test_list_for_module_returns_only_that_modules_records(
    db_session: AsyncSession,
) -> None:
    module_a = await create_checklist_module(db_session)
    module_b = await create_checklist_module(db_session)
    user = await create_user(db_session)
    repo = MockDataRecordRepository(db_session)
    await repo.add(
        MockDataRecord(
            id=uuid.uuid4(),
            checklist_module_id=module_a.id,
            fields={"name": "Acme"},
            created_by=user.id,
        )
    )
    await repo.add(
        MockDataRecord(
            id=uuid.uuid4(),
            checklist_module_id=module_b.id,
            fields={"name": "Globex"},
            created_by=user.id,
        )
    )
    await db_session.commit()

    records = await repo.list_for_module(module_a.id)

    assert [record.fields["name"] for record in records] == ["Acme"]


async def test_soft_delete_for_module_hides_records(db_session: AsyncSession) -> None:
    module = await create_checklist_module(db_session)
    user = await create_user(db_session)
    repo = MockDataRecordRepository(db_session)
    await repo.add(
        MockDataRecord(
            id=uuid.uuid4(), checklist_module_id=module.id, fields={}, created_by=user.id
        )
    )
    await db_session.commit()

    count = await repo.soft_delete_for_module(module.id)
    await db_session.commit()

    assert count == 1
    assert await repo.list_for_module(module.id) == []

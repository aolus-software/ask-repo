"""Queries over `mock_data_messages` -- a module's shared mock-data refinement chat."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import MessageRole
from app.models.mock_data import MockDataMessage
from app.repositories.mock_data_message import MockDataMessageRepository
from tests.factories import create_checklist_module, create_project, create_user


async def test_list_for_module_returns_messages_oldest_first(
    db_session: AsyncSession,
) -> None:
    """Messages are returned oldest-first as they appear chronologically.

    `created_at` is set explicitly to ensure deterministic ordering, since
    Postgres `now()` is transaction-scoped and rows inserted in one transaction
    would share an identical timestamp.
    """
    module = await create_checklist_module(db_session)
    started = datetime.now(UTC)
    first = MockDataMessage(
        id=uuid.uuid4(),
        checklist_module_id=module.id,
        role=MessageRole.USER.value,
        content="one",
        created_by=module.created_by,
        created_at=started,
    )
    second = MockDataMessage(
        id=uuid.uuid4(),
        checklist_module_id=module.id,
        role=MessageRole.ASSISTANT.value,
        content="two",
        created_by=module.created_by,
        created_at=started + timedelta(seconds=1),
    )
    db_session.add_all([first, second])
    await db_session.commit()
    repository = MockDataMessageRepository(db_session)

    rows = await repository.list_for_module(module.id, limit=50)

    assert [row.id for row in rows] == [first.id, second.id]


async def test_recent_turns_returns_rows_oldest_first_within_the_cap(
    db_session: AsyncSession,
) -> None:
    """The cap keeps the NEWEST messages, returning them oldest-first.

    `created_at` is set explicitly for the same reason as
    `test_list_for_module_returns_messages_oldest_first` above.
    """
    module = await create_checklist_module(db_session)
    started = datetime.now(UTC)
    for index in range(3):
        db_session.add(
            MockDataMessage(
                id=uuid.uuid4(),
                checklist_module_id=module.id,
                role=MessageRole.USER.value,
                content=f"m{index}",
                created_by=module.created_by,
                created_at=started + timedelta(seconds=index),
            )
        )
    await db_session.commit()
    repository = MockDataMessageRepository(db_session)

    rows = await repository.recent_turns(module.id, limit=2)

    assert [row.content for row in rows] == ["m1", "m2"]
    assert await repository.recent_turns(module.id, limit=0) == []


async def test_soft_delete_for_module_hides_messages(
    db_session: AsyncSession,
) -> None:
    """Soft-deleting a module's messages hides them from queries."""
    module = await create_checklist_module(db_session)
    user = await create_user(db_session)
    repository = MockDataMessageRepository(db_session)

    await repository.add(
        MockDataMessage(
            id=uuid.uuid4(),
            checklist_module_id=module.id,
            role=MessageRole.USER.value,
            content="test message",
            created_by=user.id,
        )
    )
    await db_session.commit()

    count = await repository.soft_delete_for_module(module.id)
    await db_session.commit()

    assert count == 1
    assert await repository.list_for_module(module.id, limit=50) == []


async def test_soft_delete_for_project_cascades(
    db_session: AsyncSession,
) -> None:
    """Soft-deleting a project cascades to all its modules' messages."""
    project = await create_project(db_session)
    module_a = await create_checklist_module(db_session, project_id=project.id)
    module_b = await create_checklist_module(db_session, project_id=project.id)
    user = await create_user(db_session)
    repository = MockDataMessageRepository(db_session)

    await repository.add(
        MockDataMessage(
            id=uuid.uuid4(),
            checklist_module_id=module_a.id,
            role=MessageRole.USER.value,
            content="message a",
            created_by=user.id,
        )
    )
    await repository.add(
        MockDataMessage(
            id=uuid.uuid4(),
            checklist_module_id=module_b.id,
            role=MessageRole.USER.value,
            content="message b",
            created_by=user.id,
        )
    )
    await db_session.commit()

    count = await repository.soft_delete_for_project(project.id)
    await db_session.commit()

    assert count == 2
    assert await repository.list_for_module(module_a.id, limit=50) == []
    assert await repository.list_for_module(module_b.id, limit=50) == []

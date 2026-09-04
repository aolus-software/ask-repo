"""Change-set and chat-history persistence, plus the module-level cascades."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.checklist import (
    ChangeSetOrigin,
    ChangeSetStatus,
    ChecklistChangeSet,
    ChecklistMessage,
)
from app.models.conversation import MessageRole
from app.repositories.checklist_change_set import ChecklistChangeSetRepository
from app.repositories.checklist_message import ChecklistMessageRepository
from tests.factories import (
    create_checklist_change_set,
    create_checklist_message,
    create_checklist_module,
)


async def test_pending_for_module_ignores_resolved_sets(db_session: AsyncSession) -> None:
    """At most one pending set per module is the invariant the generate route
    enforces with `409 CHANGE_SET_PENDING`; a resolved one must not block it.

    `created_at` is set explicitly, with the APPLIED row deterministically newer than
    the PENDING one, rather than going through `create_checklist_change_set` (which does
    not take a timestamp): Postgres `now()` is transaction-scoped, so two rows inserted in
    this one transaction would otherwise share an identical `created_at`, and
    `order_by(created_at.desc()).limit(1)` has no id tiebreaker -- a tie would make which
    row comes back unspecified, and the guard would only catch a dropped status filter by
    luck rather than deterministically.
    """
    module = await create_checklist_module(db_session)
    started = datetime.now(UTC)
    applied = ChecklistChangeSet(
        id=uuid.uuid4(),
        module_id=module.id,
        origin=ChangeSetOrigin.GENERATION.value,
        summary="1 added",
        operations=[],
        status=ChangeSetStatus.APPLIED.value,
        created_by=module.created_by,
        created_at=started + timedelta(seconds=1),
    )
    pending = ChecklistChangeSet(
        id=uuid.uuid4(),
        module_id=module.id,
        origin=ChangeSetOrigin.GENERATION.value,
        summary="1 added",
        operations=[],
        status=ChangeSetStatus.PENDING.value,
        created_by=module.created_by,
        created_at=started,
    )
    db_session.add_all([applied, pending])
    await db_session.commit()
    repository = ChecklistChangeSetRepository(db_session)

    found = await repository.pending_for_module(module.id)

    assert found is not None
    assert found.id == pending.id


async def test_pending_module_ids_maps_only_modules_with_one(
    db_session: AsyncSession,
) -> None:
    """The module list shows a Review-changes badge per row without an N+1.

    `without` holds a RESOLVED change set rather than none: a module with no rows at
    all cannot tell a working status filter from a missing one.
    """
    with_pending = await create_checklist_module(db_session)
    without = await create_checklist_module(db_session)
    change_set = await create_checklist_change_set(
        db_session, module_id=with_pending.id, status=ChangeSetStatus.PENDING
    )
    await create_checklist_change_set(
        db_session, module_id=without.id, status=ChangeSetStatus.APPLIED
    )
    repository = ChecklistChangeSetRepository(db_session)

    mapping = await repository.pending_module_ids([with_pending.id, without.id])

    assert mapping == {with_pending.id: change_set.id}


async def test_messages_come_back_oldest_first(db_session: AsyncSession) -> None:
    """`created_at` is set explicitly rather than left to the column default: Postgres
    `now()` is transaction-scoped, so rows inserted in one transaction (as these are,
    under `db_session`) share one identical timestamp, and the `id` tiebreaker is a
    random uuid4 -- see `test_recent_turns_returns_the_tail_in_chronological_order` in
    `tests/test_conversation_repository.py` for the same fix on `MessageRepository`.
    """
    module = await create_checklist_module(db_session)
    started = datetime.now(UTC)
    first = ChecklistMessage(
        id=uuid.uuid4(),
        module_id=module.id,
        role=MessageRole.USER.value,
        content="one",
        created_by=module.created_by,
        created_at=started,
    )
    second = ChecklistMessage(
        id=uuid.uuid4(),
        module_id=module.id,
        role=MessageRole.ASSISTANT.value,
        content="two",
        created_by=module.created_by,
        created_at=started + timedelta(seconds=1),
    )
    db_session.add_all([first, second])
    await db_session.commit()
    repository = ChecklistMessageRepository(db_session)

    rows = await repository.list_for_module(module.id, limit=50)

    assert [row.id for row in rows] == [first.id, second.id]


async def test_recent_turns_returns_rows_oldest_first_within_the_cap(
    db_session: AsyncSession,
) -> None:
    """Rows, not `Turn`s: mapping to `Turn` means dropping unfinished assistant turns,
    which is a business rule the service owns. The cap keeps the NEWEST messages, so a
    long chat does not render its first N and hide the rest.

    `created_at` is set explicitly for the same reason as
    `test_messages_come_back_oldest_first` above.
    """
    module = await create_checklist_module(db_session)
    started = datetime.now(UTC)
    for index in range(3):
        db_session.add(
            ChecklistMessage(
                id=uuid.uuid4(),
                module_id=module.id,
                role=MessageRole.USER.value,
                content=f"m{index}",
                created_by=module.created_by,
                created_at=started + timedelta(seconds=index),
            )
        )
    await db_session.commit()
    repository = ChecklistMessageRepository(db_session)

    rows = await repository.recent_turns(module.id, limit=2)

    assert [row.content for row in rows] == ["m1", "m2"]
    assert await repository.recent_turns(module.id, limit=0) == []


async def test_module_cascade_removes_change_sets_and_messages(
    db_session: AsyncSession,
) -> None:
    """Deleting a module soft-deletes its items, change sets, and messages (spec 3.7)."""
    module = await create_checklist_module(db_session)
    await create_checklist_change_set(db_session, module_id=module.id)
    await create_checklist_message(db_session, module_id=module.id, created_by=module.created_by)

    assert await ChecklistChangeSetRepository(db_session).soft_delete_for_module(module.id) == 1
    assert await ChecklistMessageRepository(db_session).soft_delete_for_module(module.id) == 1
    assert await ChecklistChangeSetRepository(db_session).pending_for_module(module.id) is None
    assert await ChecklistMessageRepository(db_session).list_for_module(module.id, limit=50) == []

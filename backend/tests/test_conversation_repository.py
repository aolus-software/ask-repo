"""Ownership scoping, history loading, and the project cascade."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import FinishReason, Message, MessageRole
from app.repositories.conversation import ConversationRepository, MessageRepository
from tests.factories import create_conversation, create_project, create_user


async def test_get_for_owner_hides_another_users_conversation(db_session: AsyncSession) -> None:
    """The privacy boundary, at the lowest layer that can enforce it.

    Returning None (rather than the row plus a check upstairs) is what makes the
    404 in the service unconditional — there is no row to accidentally leak.
    """
    owner = await create_user(db_session)
    intruder = await create_user(db_session)
    conversation = await create_conversation(db_session, user_id=owner.id)
    repository = ConversationRepository(db_session)

    assert await repository.get_for_owner(conversation.id, owner.id) is not None
    assert await repository.get_for_owner(conversation.id, intruder.id) is None


async def test_list_page_returns_only_the_owners_conversations(db_session: AsyncSession) -> None:
    owner = await create_user(db_session)
    other = await create_user(db_session)
    await create_conversation(db_session, user_id=owner.id)
    await create_conversation(db_session, user_id=owner.id)
    await create_conversation(db_session, user_id=other.id)
    await db_session.commit()

    rows, total = await ConversationRepository(db_session).list_page(
        owner_id=owner.id, page=1, limit=25, sort="updated_at", descending=True
    )

    assert total == 2
    assert {row.user_id for row in rows} == {owner.id}


async def test_list_page_can_filter_by_project(db_session: AsyncSession) -> None:
    owner = await create_user(db_session)
    wanted = await create_project(db_session, created_by=owner.id)
    other = await create_project(db_session, created_by=owner.id)
    await create_conversation(db_session, user_id=owner.id, project_id=wanted.id)
    await create_conversation(db_session, user_id=owner.id, project_id=other.id)
    await db_session.commit()

    rows, total = await ConversationRepository(db_session).list_page(
        owner_id=owner.id,
        project_id=wanted.id,
        page=1,
        limit=25,
        sort="updated_at",
        descending=True,
    )

    assert total == 1
    assert rows[0].project_id == wanted.id


async def test_an_unknown_sort_field_is_rejected(db_session: AsyncSession) -> None:
    """Passing a query parameter into getattr(Model, ...) unchecked exposes every
    column. The allowlist is the control; this test is what keeps it one."""
    with pytest.raises(ValueError):
        await ConversationRepository(db_session).list_page(
            owner_id=uuid.uuid4(), page=1, limit=25, sort="user_id; DROP TABLE", descending=True
        )


async def test_soft_delete_for_project_sweeps_every_owner(db_session: AsyncSession) -> None:
    """docs/PRD.md §4.2: deleting a project soft-deletes conversations against it.

    Across all users, not just the deleter's — the project was shared, so the
    conversations against it belong to several people.
    """
    project = await create_project(db_session)
    first = await create_user(db_session)
    second = await create_user(db_session)
    await create_conversation(db_session, user_id=first.id, project_id=project.id)
    await create_conversation(db_session, user_id=second.id, project_id=project.id)
    survivor = await create_conversation(db_session, user_id=first.id)
    await db_session.commit()

    repository = ConversationRepository(db_session)
    swept = await repository.soft_delete_for_project(project.id)
    await db_session.commit()

    assert swept == 2
    _, total = await repository.list_page(
        owner_id=first.id, page=1, limit=25, sort="updated_at", descending=True
    )
    assert total == 1
    assert await repository.get_for_owner(survivor.id, first.id) is not None


async def test_soft_delete_for_project_advances_updated_at(db_session: AsyncSession) -> None:
    """TimestampMixin.onupdate is a server-side expression rendered during an ORM
    flush; it does NOT fire on a bulk UPDATE. A repository issuing one sets
    updated_at itself, or rows end up with an updated_at predating their change."""
    project = await create_project(db_session)
    user = await create_user(db_session)
    conversation = await create_conversation(db_session, user_id=user.id, project_id=project.id)
    await db_session.commit()
    before = conversation.updated_at

    await ConversationRepository(db_session).soft_delete_for_project(project.id)
    await db_session.commit()
    await db_session.refresh(conversation)

    assert conversation.updated_at > before


async def test_recent_turns_returns_the_tail_in_chronological_order(
    db_session: AsyncSession,
) -> None:
    """The window is the LAST n messages, but the prompt needs them oldest-first.

    `created_at` is set explicitly rather than left to the column default. Postgres
    `now()` is transaction-scoped, so six rows inserted in one transaction share one
    identical timestamp, and the `id` tiebreaker is a random uuid4 — the tail would
    then come back in an arbitrary order and this test would be asserting nothing.
    Chronology is what is under test here, so the test has to supply it.
    """
    user = await create_user(db_session)
    conversation = await create_conversation(db_session, user_id=user.id)
    started = datetime.now(UTC)
    for index in range(6):
        db_session.add(
            Message(
                id=uuid.uuid4(),
                conversation_id=conversation.id,
                role=MessageRole.USER.value if index % 2 == 0 else MessageRole.ASSISTANT.value,
                content=f"message {index}",
                finish_reason=None if index % 2 == 0 else FinishReason.STOP.value,
                created_at=started + timedelta(seconds=index),
            )
        )
    await db_session.commit()

    turns = await MessageRepository(db_session).recent_turns(conversation.id, limit=3)

    assert [turn.content for turn in turns] == ["message 3", "message 4", "message 5"]


async def test_soft_deleting_a_message_is_refused(db_session: AsyncSession) -> None:
    """`messages` has no deleted_at. Assigning one would land in __dict__, persist
    nothing, and raise nothing — a delete that silently does not happen."""
    user = await create_user(db_session)
    conversation = await create_conversation(db_session, user_id=user.id)
    message = Message(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        role=MessageRole.USER.value,
        content="hello",
    )
    db_session.add(message)
    await db_session.flush()

    with pytest.raises(TypeError):
        await MessageRepository(db_session).soft_delete(message)

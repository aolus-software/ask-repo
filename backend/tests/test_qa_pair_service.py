"""Creating a pair from a message, and the guards that make publishing safe."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.middleware import AuthenticatedUser
from app.models.conversation import FinishReason, Message, MessageRole
from app.schemas.qa_pair import QAPairCreateRequest
from app.services.qa_pair import QAPairService, normalise_tags
from tests.factories import create_conversation, create_project, create_user


def actor_for(user_id: uuid.UUID, *, is_admin: bool = False) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=user_id, email="a@example.com", is_admin=is_admin, must_change_password=False
    )


async def seed_answered_turn(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    finish_reason: FinishReason = FinishReason.STOP,
) -> Message:
    """A question and its answer, in one conversation owned by `owner_id`."""
    project = await create_project(session, created_by=owner_id)
    conversation = await create_conversation(
        session, user_id=owner_id, project_id=project.id
    )
    session.add(
        Message(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            role=MessageRole.USER.value,
            content="How does login work?",
        )
    )
    await session.flush()
    answer = Message(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        role=MessageRole.ASSISTANT.value,
        content="It hashes with bcrypt. [1]",
        citations=[
            {
                "index": 1,
                "file_path": "app/core/passwords.py",
                "start_line": 1,
                "end_line": 9,
                "language": "python",
                "symbol": None,
                "commit_sha": "abc123",
                "score": 0.9,
                "cited": True,
            }
        ],
        model="test-model",
        finish_reason=finish_reason.value,
    )
    session.add(answer)
    await session.commit()
    return answer


async def test_create_copies_the_content_and_seeds_the_expected_result(
    db_session: AsyncSession,
) -> None:
    user = await create_user(db_session)
    answer = await seed_answered_turn(db_session, owner_id=user.id)
    service = QAPairService(db_session, get_settings())

    pair = await service.create(
        QAPairCreateRequest(message_id=answer.id, module="auth", tags=["Auth", " auth "]),
        actor=actor_for(user.id),
    )

    assert pair.question == "How does login work?"
    assert pair.answer == "It hashes with bcrypt. [1]"
    # Seeded, so a re-run three weeks later has something to be compared against
    # without anyone having done extra work at save time (spec §2.3).
    assert pair.reference_answer == pair.answer
    assert pair.model == "test-model"
    assert pair.status == "unreviewed"
    assert pair.source == "manual"
    assert pair.citations is not None
    # Normalised on write so the filter never has to guess at casing.
    assert pair.tags == ["auth"]


async def test_create_refuses_a_message_that_never_finished(
    db_session: AsyncSession,
) -> None:
    user = await create_user(db_session)
    answer = await seed_answered_turn(
        db_session, owner_id=user.id, finish_reason=FinishReason.DISCONNECTED
    )
    service = QAPairService(db_session, get_settings())

    with pytest.raises(AppError) as caught:
        await service.create(
            QAPairCreateRequest(message_id=answer.id), actor=actor_for(user.id)
        )

    assert caught.value.status_code == 409
    assert caught.value.code is ErrorCode.ANSWER_INCOMPLETE


async def test_create_from_someone_elses_conversation_is_404_not_403(
    db_session: AsyncSession,
) -> None:
    """Conversation existence is private. A 403 here would confirm it exists."""
    owner = await create_user(db_session)
    intruder = await create_user(db_session)
    answer = await seed_answered_turn(db_session, owner_id=owner.id)
    service = QAPairService(db_session, get_settings())

    with pytest.raises(AppError) as caught:
        await service.create(
            QAPairCreateRequest(message_id=answer.id), actor=actor_for(intruder.id)
        )

    assert caught.value.status_code == 404
    assert caught.value.code is ErrorCode.MESSAGE_NOT_FOUND


async def test_create_from_an_unknown_message_is_404(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    service = QAPairService(db_session, get_settings())

    with pytest.raises(AppError) as caught:
        await service.create(
            QAPairCreateRequest(message_id=uuid.uuid4()), actor=actor_for(user.id)
        )

    assert caught.value.status_code == 404


def test_normalise_tags_trims_lowercases_deduplicates_and_drops_empties() -> None:
    assert normalise_tags(["  Auth ", "auth", "", "Billing"]) == ["auth", "billing"]

"""Pre-flight policy, and what survives a broken stream."""

import asyncio
import uuid

import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.middleware import AuthenticatedUser
from app.db.session import get_sessionmaker
from app.models.conversation import FinishReason, MessageRole
from app.models.project import Project, ProjectStatus
from app.models.user import User
from app.rag.answerer import Answerer
from app.repositories.conversation import MessageRepository
from app.schemas.conversation import MessageCreateRequest
from app.services.conversation import ConversationService, stream_turn
from tests.factories import create_conversation, create_project, create_user
from tests.fakes import ScriptedChatModel
from tests.test_answerer import RecordingRetriever
from tests.test_retriever import _span


def actor_for(user: User) -> AuthenticatedUser:
    """The frozen identity the middleware would have built for this row."""
    return AuthenticatedUser(
        id=user.id,
        name=user.name,
        email=user.email,
        is_admin=user.is_admin,
        must_change_password=False,
    )


def service_for(session: AsyncSession) -> ConversationService:
    return ConversationService(session, get_settings())


async def ready_project(session: AsyncSession, owner_id: uuid.UUID) -> Project:
    """A project whose index exists, was built by the configured embedder, and is
    serving generation 3."""
    project = await create_project(session, created_by=owner_id, status=ProjectStatus.READY)
    project.embedding_collection = "code_chunks__ollama__nomic_embed_text__768"
    project.embedding_model = get_settings().embedding_model
    project.active_generation = 3
    await session.flush()
    return project


async def test_another_users_conversation_is_404_not_403(db_session: AsyncSession) -> None:
    """Backwards, this leaks existence. docs/PRD.md §4.2 makes conversations the
    one resource where existence itself is private."""
    owner = await create_user(db_session)
    intruder = await create_user(db_session)
    conversation = await create_conversation(db_session, user_id=owner.id)
    await db_session.commit()

    with pytest.raises(AppError) as caught:
        await service_for(db_session).get(conversation.id, actor=actor_for(intruder))

    assert caught.value.status_code == status.HTTP_404_NOT_FOUND
    assert caught.value.code is ErrorCode.CONVERSATION_NOT_FOUND


async def test_an_admin_gets_404_too(db_session: AsyncSession) -> None:
    """is_admin gates destructive operations on shared resources. Conversations
    are not shared, and §4.2 states their privacy without qualification."""
    owner = await create_user(db_session)
    admin = await create_user(db_session, is_admin=True)
    conversation = await create_conversation(db_session, user_id=owner.id)
    await db_session.commit()

    with pytest.raises(AppError) as caught:
        await service_for(db_session).get(conversation.id, actor=actor_for(admin))

    assert caught.value.status_code == status.HTTP_404_NOT_FOUND


async def test_a_project_that_is_not_ready_is_409(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    project = await create_project(db_session, created_by=user.id, status=ProjectStatus.INDEXING)
    conversation = await create_conversation(db_session, user_id=user.id, project_id=project.id)
    await db_session.commit()

    with pytest.raises(AppError) as caught:
        await service_for(db_session).prepare_turn(
            conversation.id, MessageCreateRequest(question="q"), actor=actor_for(user)
        )

    assert caught.value.status_code == status.HTTP_409_CONFLICT
    assert caught.value.code is ErrorCode.PROJECT_NOT_READY


async def test_a_changed_embedding_model_is_409(db_session: AsyncSession) -> None:
    """Two models of the same width: Qdrant accepts the query and returns its
    nearest neighbours in a space the collection was never built in. Nothing
    errors anywhere — answers just quietly get worse."""
    user = await create_user(db_session)
    project = await ready_project(db_session, user.id)
    project.embedding_model = "some-other-model"
    conversation = await create_conversation(db_session, user_id=user.id, project_id=project.id)
    await db_session.commit()

    with pytest.raises(AppError) as caught:
        await service_for(db_session).prepare_turn(
            conversation.id, MessageCreateRequest(question="q"), actor=actor_for(user)
        )

    assert caught.value.status_code == status.HTTP_409_CONFLICT
    assert caught.value.code is ErrorCode.EMBEDDING_MODEL_CHANGED


async def test_prepare_turn_persists_the_question_and_titles_the_thread(
    db_session: AsyncSession,
) -> None:
    """The question survives regardless of what happens next — that is what makes
    the pre-flight failures the only ones leaving nothing behind."""
    user = await create_user(db_session)
    project = await ready_project(db_session, user.id)
    conversation = await create_conversation(db_session, user_id=user.id, project_id=project.id)
    await db_session.commit()

    context = await service_for(db_session).prepare_turn(
        conversation.id,
        MessageCreateRequest(question="How does the lease work?"),
        actor=actor_for(user),
    )

    messages = await MessageRepository(db_session).list_for_conversation(conversation.id)
    await db_session.refresh(conversation)
    assert [m.role for m in messages] == [MessageRole.USER.value]
    assert conversation.title == "How does the lease work?"
    assert context.generation == 3


async def test_the_title_is_not_overwritten_by_the_second_question(
    db_session: AsyncSession,
) -> None:
    user = await create_user(db_session)
    project = await ready_project(db_session, user.id)
    conversation = await create_conversation(db_session, user_id=user.id, project_id=project.id)
    await db_session.commit()
    service = service_for(db_session)

    await service.prepare_turn(
        conversation.id, MessageCreateRequest(question="first"), actor=actor_for(user)
    )
    await service.prepare_turn(
        conversation.id, MessageCreateRequest(question="second"), actor=actor_for(user)
    )
    await db_session.refresh(conversation)

    assert conversation.title == "first"


async def test_history_excludes_turns_that_did_not_finish(db_session: AsyncSession) -> None:
    """Replaying a truncated answer invites the model to continue someone else's
    half-sentence as though it were its own."""
    user = await create_user(db_session)
    project = await ready_project(db_session, user.id)
    conversation = await create_conversation(db_session, user_id=user.id, project_id=project.id)
    await db_session.commit()
    service = service_for(db_session)

    await service.prepare_turn(
        conversation.id, MessageCreateRequest(question="first"), actor=actor_for(user)
    )
    await _store_assistant(db_session, conversation.id, "cut off", FinishReason.ERROR)
    context = await service.prepare_turn(
        conversation.id, MessageCreateRequest(question="second"), actor=actor_for(user)
    )

    assert "cut off" not in [turn.content for turn in context.history]


async def test_a_broken_stream_persists_the_partial_answer(db_session: AsyncSession) -> None:
    """The whole point of finish_reason. A user reopening the conversation sees
    what they got, rather than a question with no reply."""
    user = await create_user(db_session)
    project = await ready_project(db_session, user.id)
    conversation = await create_conversation(db_session, user_id=user.id, project_id=project.id)
    await db_session.commit()
    context = await service_for(db_session).prepare_turn(
        conversation.id, MessageCreateRequest(question="q"), actor=actor_for(user)
    )
    answerer = Answerer(
        retriever=RecordingRetriever(spans=[_span("app/a.py", 0, 1, 10)]),
        chat_model=ScriptedChatModel(tokens=["half ", "an ", "answer"], fail_after=2),
        model_id="test-model",
        semaphore=asyncio.Semaphore(2),
        timeout_seconds=30,
    )

    async for _ in stream_turn(
        context=context,
        answerer=answerer,
        sessionmaker=get_sessionmaker(),
        model_id="test-model",
    ):
        pass

    stored = await MessageRepository(db_session).list_for_conversation(conversation.id)
    assistant = next(m for m in stored if m.role == MessageRole.ASSISTANT.value)
    assert assistant.content == "half an "
    assert assistant.finish_reason == FinishReason.ERROR.value


async def test_a_client_disconnect_persists_the_partial_and_releases_the_permit(
    db_session: AsyncSession,
) -> None:
    """Two failures in one test because they share a cause: on cancellation every
    `await` raises CancelledError immediately, so an unshielded write never runs
    and an unclosed answerer never releases its semaphore permit."""
    user = await create_user(db_session)
    project = await ready_project(db_session, user.id)
    conversation = await create_conversation(db_session, user_id=user.id, project_id=project.id)
    await db_session.commit()
    context = await service_for(db_session).prepare_turn(
        conversation.id, MessageCreateRequest(question="q"), actor=actor_for(user)
    )
    semaphore = asyncio.Semaphore(1)
    answerer = Answerer(
        retriever=RecordingRetriever(spans=[_span("app/a.py", 0, 1, 10)]),
        chat_model=ScriptedChatModel(tokens=["a", "b", "c"], stall_seconds=0.05),
        model_id="test-model",
        semaphore=semaphore,
        timeout_seconds=30,
    )

    stream = stream_turn(
        context=context,
        answerer=answerer,
        sessionmaker=get_sessionmaker(),
        model_id="test-model",
    )
    seen = 0
    async for _ in stream:
        seen += 1
        if seen == 4:  # past citations and into the tokens
            break
    await stream.aclose()

    stored = await MessageRepository(db_session).list_for_conversation(conversation.id)
    assistant = next(m for m in stored if m.role == MessageRole.ASSISTANT.value)
    assert assistant.finish_reason == FinishReason.DISCONNECTED.value
    assert not semaphore.locked()


async def _store_assistant(
    session: AsyncSession, conversation_id: uuid.UUID, content: str, reason: FinishReason
) -> None:
    from app.models.conversation import Message

    session.add(
        Message(
            id=uuid.uuid4(),
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT.value,
            content=content,
            finish_reason=reason.value,
        )
    )
    await session.commit()

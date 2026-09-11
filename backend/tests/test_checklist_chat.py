"""The refinement chat: the pre-flight split, the ordering contract, and the shield."""

import asyncio
from typing import cast

import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.core.errors import AppError, ErrorCode
from app.models.checklist import ChangeSetOrigin, ChangeSetStatus, ChecklistModule
from app.models.conversation import FinishReason, MessageRole
from app.models.project import Project, ProjectStatus
from app.rag.answerer import Answerer
from app.repositories.checklist_change_set import ChecklistChangeSetRepository
from app.repositories.checklist_message import ChecklistMessageRepository
from app.schemas.checklist import ChecklistMessageCreateRequest
from app.services.checklist_module import stream_checklist_turn
from tests.factories import create_checklist_module, create_project, create_user
from tests.fakes import FakeAnswerer  # yields a scripted event sequence
from tests.helpers import authenticated, checklist_module_service


async def _ready_module(session: AsyncSession) -> tuple[Project, ChecklistModule]:
    project = await create_project(session)
    project.embedding_collection = "code_chunks__ollama__nomic_embed_text__768"
    project.embedding_model = Settings().embedding_model
    project.active_generation = 1
    module = await create_checklist_module(session, project_id=project.id)
    return project, module


@pytest.mark.asyncio
async def test_prepare_turn_refuses_a_project_that_is_not_ready(
    db_session: AsyncSession,
) -> None:
    """Once SSE headers are sent the status is fixed at 200, so nothing that needs a
    status code may be deferred into the stream (spec 5.1)."""
    project = await create_project(db_session, status=ProjectStatus.CLONING)
    module = await create_checklist_module(db_session, project_id=project.id)
    service = checklist_module_service(db_session)

    with pytest.raises(AppError) as caught:
        await service.prepare_turn(
            module.id,
            ChecklistMessageCreateRequest(question="Add a test."),
            actor=authenticated(await create_user(db_session)),
        )

    assert caught.value.status_code == status.HTTP_409_CONFLICT
    assert caught.value.code is ErrorCode.PROJECT_NOT_READY


@pytest.mark.asyncio
async def test_prepare_turn_applies_the_embedding_guard(db_session: AsyncSession) -> None:
    """It DOES apply here, unlike generation: chat retrieves, and a query embedded by
    a different model lands in a vector space the collection was never built in."""
    project, module = await _ready_module(db_session)
    project.embedding_model = "some-other-model"
    service = checklist_module_service(db_session)

    with pytest.raises(AppError) as caught:
        await service.prepare_turn(
            module.id,
            ChecklistMessageCreateRequest(question="Add a test."),
            actor=authenticated(await create_user(db_session)),
        )

    assert caught.value.code is ErrorCode.EMBEDDING_MODEL_CHANGED


@pytest.mark.asyncio
async def test_prepare_turn_persists_the_question_and_mints_ids(
    db_session: AsyncSession,
) -> None:
    """The change-set id is minted here because the row is written under the shield in
    `finally`, and the `changeSet` event has to carry it (spec 5.2)."""
    _, module = await _ready_module(db_session)
    service = checklist_module_service(db_session)

    context = await service.prepare_turn(
        module.id,
        ChecklistMessageCreateRequest(question="Add a test for an empty password."),
        actor=authenticated(await create_user(db_session)),
    )

    assert context.change_set_id is not None
    assert context.assistant_message_id != context.user_message_id
    stored = await ChecklistMessageRepository(db_session).list_for_module(module.id, limit=10)
    assert [(row.role, row.content) for row in stored] == [
        (MessageRole.USER.value, "Add a test for an empty password.")
    ]


@pytest.mark.asyncio
async def test_any_user_may_speak_in_the_shared_chat(db_session: AsyncSession) -> None:
    """Shared, inverting docs/PRD.md 4.2 deliberately: the chat is the justification
    record for a shared document (spec 2.4)."""
    _, module = await _ready_module(db_session)
    stranger = await create_user(db_session)
    service = checklist_module_service(db_session)

    context = await service.prepare_turn(
        module.id,
        ChecklistMessageCreateRequest(question="Why does this expect 410?"),
        actor=authenticated(stranger),
    )

    assert context.created_by == stranger.id


@pytest.mark.asyncio
async def test_the_stream_writes_the_message_and_the_change_set(
    db_session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    _, module = await _ready_module(db_session)
    service = checklist_module_service(db_session)
    context = await service.prepare_turn(
        module.id,
        ChecklistMessageCreateRequest(question="Add a test."),
        actor=authenticated(await create_user(db_session)),
    )
    answerer = FakeAnswerer.proposing(
        change_set_id=context.change_set_id, message_id=context.assistant_message_id
    )

    frames = [
        frame
        async for frame in stream_checklist_turn(
            context=context,
            answerer=cast(Answerer, answerer),  # duck-typed stand-in, not an Answerer
            sessionmaker=sessionmaker,
            model_id="test-model",
        )
    ]

    body = b"".join(frames).decode()
    assert body.index("event: citations") < body.index("event: token")
    assert body.count("event: changeSet") == 1
    assert body.index("event: changeSet") > body.rindex("event: token")
    assert body.count("event: done") + body.count("event: error") == 1

    async with sessionmaker() as verify:
        messages = await ChecklistMessageRepository(verify).list_for_module(module.id, limit=10)
        assert [row.role for row in messages] == [
            MessageRole.USER.value,
            MessageRole.ASSISTANT.value,
        ]
        assert messages[1].finish_reason == FinishReason.STOP.value

        change_set = await ChecklistChangeSetRepository(verify).pending_for_module(module.id)
        assert change_set is not None
        assert change_set.id == context.change_set_id
        assert change_set.origin == ChangeSetOrigin.CHAT.value
        assert change_set.status == ChangeSetStatus.PENDING.value
        assert change_set.message_id == context.assistant_message_id


@pytest.mark.asyncio
async def test_a_disconnect_still_persists_what_arrived(
    db_session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """A disconnect arrives as `CancelledError`, and every `await` in a cancelled task
    raises it again immediately -- so an unshielded cleanup runs none of itself and
    loses the partial answer this design exists to keep (spec 5.3)."""
    _, module = await _ready_module(db_session)
    service = checklist_module_service(db_session)
    context = await service.prepare_turn(
        module.id,
        ChecklistMessageCreateRequest(question="Add a test."),
        actor=authenticated(await create_user(db_session)),
    )
    answerer = FakeAnswerer.hanging_after_one_token()

    stream = stream_checklist_turn(
        context=context,
        answerer=cast(Answerer, answerer),  # duck-typed stand-in, not an Answerer
        sessionmaker=sessionmaker,
        model_id="test-model",
    )
    consumer = asyncio.create_task(_drain(stream))
    await asyncio.sleep(0.01)
    consumer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await consumer

    async with sessionmaker() as verify:
        messages = await ChecklistMessageRepository(verify).list_for_module(module.id, limit=10)
        assert messages[1].content == "partial"
        assert messages[1].finish_reason == FinishReason.DISCONNECTED.value
        # No proposal arrived, so no change set was written -- an empty pending set
        # would put a Review-changes badge on a module with nothing to review.
        assert await ChecklistChangeSetRepository(verify).pending_for_module(module.id) is None
    # The permit was released: the answerer was closed before the write.
    assert answerer.closed is True


async def _drain(stream: object) -> None:
    async for _ in stream:  # type: ignore[attr-defined]  # AsyncGenerator, narrowed by the caller
        pass

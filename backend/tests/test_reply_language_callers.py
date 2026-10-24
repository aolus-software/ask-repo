"""Each `Answerer` caller breaks the tie its own way (spec §4.3)."""

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.audit import AuditRecorder
from app.core.language import Language
from app.db.session import get_sessionmaker
from app.models.project import Project, ProjectStatus
from app.models.user import User
from app.schemas.checklist import ChecklistMessageCreateRequest
from app.schemas.conversation import MessageCreateRequest
from app.schemas.mock_data import MockDataMessageCreateRequest
from app.services.conversation import ConversationService
from app.services.mock_data_dataset import MockDataDatasetService
from tests.factories import (
    create_checklist_module,
    create_conversation,
    create_project,
    create_user,
)
from tests.helpers import authenticated, checklist_module_service

pytestmark = pytest.mark.asyncio


class _World:
    """One user, one ready project, one module and one conversation."""

    def __init__(self, session: AsyncSession, user: User, project: Project) -> None:
        self.session = session
        self.user = user
        self.project = project


@pytest.fixture
async def world(db_session: AsyncSession) -> _World:
    user = await create_user(db_session)
    project = await create_project(db_session, created_by=user.id, status=ProjectStatus.READY)
    project.embedding_collection = "code_chunks__ollama__nomic_embed_text__768"
    project.embedding_model = get_settings().embedding_model
    project.active_generation = 1
    await db_session.commit()
    return _World(db_session, user, project)


@pytest.fixture
def set_user_language(world: _World) -> Callable[[str | None], Awaitable[None]]:
    async def _set(value: str | None) -> None:
        world.user.language = value
        await world.session.commit()

    return _set


@pytest.fixture
def set_project_language(world: _World) -> Callable[[str], Awaitable[None]]:
    async def _set(value: str) -> None:
        world.project.content_language = value
        await world.session.commit()

    return _set


@pytest.fixture
def ask_turn(world: _World) -> Callable[..., Awaitable[Any]]:
    async def _turn(*, accept_language: str | None) -> Any:
        conversation = await create_conversation(
            world.session, user_id=world.user.id, project_id=world.project.id
        )
        await world.session.commit()
        service = ConversationService(
            world.session, get_settings(), recorder=AuditRecorder(get_sessionmaker())
        )
        return await service.prepare_turn(
            conversation.id,
            MessageCreateRequest(question="q"),
            actor=await authenticated(world.session, world.user),
            accept_language=accept_language,
        )

    return _turn


@pytest.fixture
def checklist_turn(world: _World) -> Callable[[], Awaitable[Any]]:
    async def _turn() -> Any:
        module = await create_checklist_module(world.session, project_id=world.project.id)
        await world.session.commit()
        return await checklist_module_service(world.session).prepare_turn(
            module.id,
            ChecklistMessageCreateRequest(question="q"),
            actor=await authenticated(world.session, world.user),
        )

    return _turn


@pytest.fixture
def mock_data_turn(world: _World) -> Callable[[], Awaitable[Any]]:
    async def _turn() -> Any:
        module = await create_checklist_module(world.session, project_id=world.project.id)
        await world.session.commit()
        service = MockDataDatasetService(
            world.session, Settings(), recorder=AuditRecorder(get_sessionmaker())
        )
        return await service.prepare_turn(
            module.id,
            MockDataMessageCreateRequest(question="q"),
            actor=await authenticated(world.session, world.user),
        )

    return _turn


async def test_ask_uses_the_users_stored_language(ask_turn: Any, set_user_language: Any) -> None:
    await set_user_language("ko")

    context = await ask_turn(accept_language="id")

    assert context.reply_language is Language.KO


async def test_ask_falls_back_to_accept_language(ask_turn: Any, set_user_language: Any) -> None:
    await set_user_language(None)

    context = await ask_turn(accept_language="id-ID,id;q=0.9")

    assert context.reply_language is Language.ID


async def test_ask_falls_back_to_english(ask_turn: Any, set_user_language: Any) -> None:
    await set_user_language(None)

    context = await ask_turn(accept_language=None)

    assert context.reply_language is Language.EN


async def test_the_checklist_chat_uses_the_projects_language(
    checklist_turn: Any, set_project_language: Any, set_user_language: Any
) -> None:
    """Who pressed Send must not decide a shared document (spec §4.3)."""
    await set_project_language("ja")
    await set_user_language("ko")

    context = await checklist_turn()

    assert context.reply_language is Language.JA


async def test_the_mock_data_chat_uses_the_projects_language(
    mock_data_turn: Any, set_project_language: Any, set_user_language: Any
) -> None:
    await set_project_language("ms")
    await set_user_language("ko")

    context = await mock_data_turn()

    assert context.reply_language is Language.MS

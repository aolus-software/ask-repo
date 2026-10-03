"""Admin feedback reads: admin-only, filtered through the scope, never naming a voter."""

import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.feedback import FeedbackFeature, FeedbackRating, FeedbackTarget
from app.models.checklist import ChangeSetOrigin
from app.models.conversation import Message, MessageRole
from app.observability.trace_ids import trace_url
from app.schemas.feedback import FeedbackAdminRead
from tests.factories import (
    create_checklist_change_set,
    create_checklist_message,
    create_checklist_module,
    create_conversation,
    create_feedback,
    create_message,
    create_mock_data_change_set,
    create_mock_data_message,
    create_project,
    create_user,
)

# No `pytestmark = pytest.mark.asyncio`: this repo runs pytest-asyncio in "auto" mode
# (`asyncio_mode = "auto"` in pyproject.toml), so an `async def test_...` needs no
# marker, and a module-level mark would wrongly apply to the sync test below too.


async def test_non_admins_are_refused(authed_client: AsyncClient) -> None:
    for path in ("/feedback", "/feedback/summary"):
        response = await authed_client.get(path)
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "ADMIN_REQUIRED"


async def test_the_list_shows_notes_and_projects_but_no_voter(
    client_for_admin: AsyncClient, db_session: AsyncSession
) -> None:
    voter = await create_user(db_session, email="voter@example.com", name="Vera Voter")
    project = await create_project(db_session, name="payments")
    await create_feedback(
        db_session, user_id=voter.id, project_id=project.id, note="Wrong file entirely."
    )
    await db_session.commit()

    response = await client_for_admin.get("/feedback")

    assert response.status_code == 200
    body = response.json()
    assert body["totalCount"] == 1
    item = body["items"][0]
    assert item["projectName"] == "payments"
    assert item["note"] == "Wrong file entirely."
    assert item["traceUrl"] is None
    # The vote's day, never its time: a second-precision timestamp plus the audit
    # trail's `conversation.created` row (same actor, same project, seconds apart)
    # would let an admin match a vote to whoever asked the question.
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", item["createdOn"])
    assert "createdAt" not in item
    assert "updatedAt" not in item
    serialized = response.text
    assert str(voter.id) not in serialized
    assert "voter@example.com" not in serialized
    assert "Vera Voter" not in serialized


def test_the_admin_schema_has_no_user_field() -> None:
    fields = set(FeedbackAdminRead.model_fields)
    assert not {f for f in fields if "user" in f or "email" in f or "actor" in f or "name" == f}


def test_the_admin_schema_carries_no_time_of_day() -> None:
    """`created_on` is a bare date; nothing on this schema is finer-grained than a
    day, which is what keeps it useless for matching against the audit trail's
    second-precision `conversation.created` rows."""
    for name, field in FeedbackAdminRead.model_fields.items():
        assert field.annotation not in (datetime, datetime | None), (
            f"{name} carries a time, not just a day"
        )


async def test_filters_narrow_the_list(
    client_for_admin: AsyncClient, db_session: AsyncSession
) -> None:
    voter = await create_user(db_session)
    alpha = await create_project(db_session, name="alpha")
    beta = await create_project(db_session, name="beta")
    await create_feedback(db_session, user_id=voter.id, project_id=alpha.id)
    await create_feedback(
        db_session, user_id=voter.id, project_id=beta.id, rating=FeedbackRating.UP, reason_codes=()
    )
    await db_session.commit()

    by_project = await client_for_admin.get("/feedback", params={"projectId": str(alpha.id)})
    by_rating = await client_for_admin.get("/feedback", params={"rating": "up"})

    assert [i["projectName"] for i in by_project.json()["items"]] == ["alpha"]
    assert [i["projectName"] for i in by_rating.json()["items"]] == ["beta"]


async def test_summary_counts_votes_reasons_and_prompt_versions(
    client_for_admin: AsyncClient, db_session: AsyncSession
) -> None:
    a = await create_user(db_session)
    b = await create_user(db_session)
    project = await create_project(db_session)
    await create_feedback(
        db_session,
        user_id=a.id,
        project_id=project.id,
        reason_codes=("wrong_file_cited",),
        prompt_version="aaaaaaaaaaaa",
    )
    await create_feedback(
        db_session,
        user_id=b.id,
        project_id=project.id,
        rating=FeedbackRating.UP,
        reason_codes=(),
        prompt_version="aaaaaaaaaaaa",
    )
    await db_session.commit()

    response = await client_for_admin.get("/feedback/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["byFeature"] == [{"feature": "answer", "up": 1, "down": 1}]
    assert body["byReason"] == [{"feature": "answer", "reasonCode": "wrong_file_cited", "count": 1}]
    assert body["byPromptVersion"] == [{"promptVersion": "aaaaaaaaaaaa", "up": 1, "down": 1}]


@asynccontextmanager
async def _langfuse(app: FastAPI, *, enabled: bool) -> AsyncIterator[None]:
    settings = get_settings().model_copy(
        update={
            "langfuse_enabled": enabled,
            "langfuse_public_key": "pk",
            "langfuse_secret_key": "sk",
            "langfuse_ui_url": "http://lf.internal",
            "langfuse_project_id": "askrepo",
        }
    )
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_settings, None)


def _link(seed: object) -> str:
    return trace_url(ui_url="http://lf.internal", project_id="askrepo", seed=str(seed))


async def _seed_votes(db_session: AsyncSession) -> dict[str, uuid.UUID]:
    """One vote per kind of target; returns the ids the links are seeded by."""
    voter = await create_user(db_session)
    project = await create_project(db_session)
    module = await create_checklist_module(db_session, project_id=project.id)
    gen = await create_checklist_change_set(db_session, module_id=module.id, created_by=voter.id)
    chat_msg = await create_checklist_message(
        db_session, module_id=module.id, created_by=voter.id, role=MessageRole.ASSISTANT
    )
    chat = await create_checklist_change_set(
        db_session, module_id=module.id, created_by=voter.id, origin=ChangeSetOrigin.CHAT
    )
    chat.message_id = chat_msg.id
    mock_gen = await create_mock_data_change_set(
        db_session, module_id=module.id, created_by=voter.id
    )
    mock_msg = await create_mock_data_message(
        db_session, module_id=module.id, created_by=voter.id, role=MessageRole.ASSISTANT
    )
    ask_msg_id = (await _ask_message(db_session, project.id, voter.id)).id
    votes = [
        (FeedbackTarget.CHECKLIST_CHANGE_SET, gen.id, FeedbackFeature.GENERATE_CHECKLIST),
        (FeedbackTarget.CHECKLIST_CHANGE_SET, chat.id, FeedbackFeature.PROPOSE_CHECKLIST),
        (FeedbackTarget.CHECKLIST_MESSAGE, chat_msg.id, FeedbackFeature.ANSWER),
        (FeedbackTarget.MOCK_DATA_CHANGE_SET, mock_gen.id, FeedbackFeature.GENERATE_MOCK_DATA),
        (FeedbackTarget.MOCK_DATA_MESSAGE, mock_msg.id, FeedbackFeature.ANSWER),
        (FeedbackTarget.MESSAGE, ask_msg_id, FeedbackFeature.ANSWER),
    ]
    for target_type, target_id, feature in votes:
        await create_feedback(
            db_session,
            user_id=voter.id,
            project_id=project.id,
            target_type=target_type,
            target_id=target_id,
            feature=feature,
        )
    await db_session.commit()
    return {
        "gen": gen.id,
        "chat_msg": chat_msg.id,
        "chat": chat.id,
        "mock_gen": mock_gen.id,
        "mock_msg": mock_msg.id,
        "ask": ask_msg_id,
    }


async def _ask_message(
    db_session: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID
) -> Message:
    conversation = await create_conversation(db_session, project_id=project_id, user_id=user_id)
    return await create_message(
        db_session, conversation_id=conversation.id, role=MessageRole.ASSISTANT
    )


async def test_trace_links_follow_each_targets_seed(
    app_with_queue: FastAPI, client_for_admin: AsyncClient, db_session: AsyncSession
) -> None:
    ids = await _seed_votes(db_session)

    async with _langfuse(app_with_queue, enabled=True):
        response = await client_for_admin.get("/feedback")

    links: dict[str, list[str | None]] = {i["targetType"]: [] for i in response.json()["items"]}
    for item in response.json()["items"]:
        links[item["targetType"]].append(item["traceUrl"])
    assert _link(ids["gen"]) in links["checklist_change_set"]
    assert _link(ids["chat_msg"]) in links["checklist_change_set"]  # chat: its message id
    assert _link(ids["chat"]) not in links["checklist_change_set"]
    assert links["checklist_message"] == [_link(ids["chat_msg"])]
    assert links["mock_data_change_set"] == [_link(ids["mock_gen"])]
    assert links["mock_data_message"] == [_link(ids["mock_msg"])]
    assert links["message"] == [None]  # day-only decision: no Ask link


async def test_trace_links_are_null_when_langfuse_is_off(
    app_with_queue: FastAPI, client_for_admin: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed_votes(db_session)

    async with _langfuse(app_with_queue, enabled=False):
        response = await client_for_admin.get("/feedback")

    assert [i["traceUrl"] for i in response.json()["items"]] == [None] * 6

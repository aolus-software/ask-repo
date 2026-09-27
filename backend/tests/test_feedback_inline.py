"""Each list shows the caller's own vote, and nobody else's."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.feedback import FeedbackFeature, FeedbackRating, FeedbackTarget
from app.core.permissions import VIEWER_NAME
from app.models.conversation import MessageRole
from app.models.user import User
from tests.conftest import GrantMembership
from tests.factories import (
    create_checklist_change_set,
    create_checklist_message,
    create_checklist_module,
    create_conversation,
    create_feedback,
    create_message,
    create_mock_data_change_set,
    create_mock_data_message,
    create_user,
)

pytestmark = pytest.mark.asyncio


async def test_conversation_detail_carries_my_vote(
    authed_client: AsyncClient, authed_user: User, db_session: AsyncSession
) -> None:
    conversation = await create_conversation(db_session, user_id=authed_user.id)
    question = await create_message(
        db_session, conversation_id=conversation.id, role=MessageRole.USER
    )
    answer = await create_message(db_session, conversation_id=conversation.id)
    await create_feedback(
        db_session,
        user_id=authed_user.id,
        project_id=conversation.project_id,
        target_id=answer.id,
        reason_codes=("missed_something",),
    )
    await db_session.commit()

    response = await authed_client.get(f"/conversations/{conversation.id}")

    by_id = {m["id"]: m for m in response.json()["messages"]}
    assert by_id[str(question.id)]["myFeedback"] is None
    assert by_id[str(answer.id)]["myFeedback"] == {
        "rating": "down",
        "reasonCodes": ["missed_something"],
        "note": None,
    }


async def test_a_change_set_shows_only_my_vote(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
) -> None:
    """spec §0.1 decision 7: reviewers do not see each other's votes."""
    colleague = await create_user(db_session)
    module = await create_checklist_module(db_session)
    change_set = await create_checklist_change_set(db_session, module_id=module.id)
    await create_feedback(
        db_session,
        user_id=colleague.id,
        project_id=module.project_id,
        target_type=FeedbackTarget.CHECKLIST_CHANGE_SET,
        target_id=change_set.id,
        feature=FeedbackFeature.GENERATE_CHECKLIST,
        reason_codes=("wrong_scope",),
    )
    await db_session.commit()
    await grant_membership(authed_user.id, module.project_id, VIEWER_NAME)

    response = await authed_client.get(f"/checklist-modules/{module.id}/change-sets")

    assert response.json()[0]["myFeedback"] is None


async def test_checklist_messages_carry_my_vote(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
) -> None:
    module = await create_checklist_module(db_session)
    reply = await create_checklist_message(
        db_session, module_id=module.id, created_by=authed_user.id, role=MessageRole.ASSISTANT
    )
    await create_feedback(
        db_session,
        user_id=authed_user.id,
        project_id=module.project_id,
        target_type=FeedbackTarget.CHECKLIST_MESSAGE,
        target_id=reply.id,
        feature=FeedbackFeature.REFINE_CHECKLIST,
        rating=FeedbackRating.UP,
        reason_codes=(),
    )
    await db_session.commit()
    await grant_membership(authed_user.id, module.project_id, VIEWER_NAME)

    response = await authed_client.get(f"/checklist-modules/{module.id}/messages")

    assert response.json()[0]["myFeedback"]["rating"] == "up"


async def test_mock_data_lists_carry_my_vote(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
) -> None:
    module = await create_checklist_module(db_session)
    reply = await create_mock_data_message(
        db_session, module_id=module.id, created_by=authed_user.id, role=MessageRole.ASSISTANT
    )
    change_set = await create_mock_data_change_set(db_session, module_id=module.id)
    for target_type, target_id, feature in (
        (FeedbackTarget.MOCK_DATA_MESSAGE, reply.id, FeedbackFeature.REFINE_MOCK_DATA),
        (FeedbackTarget.MOCK_DATA_CHANGE_SET, change_set.id, FeedbackFeature.GENERATE_MOCK_DATA),
    ):
        await create_feedback(
            db_session,
            user_id=authed_user.id,
            project_id=module.project_id,
            target_type=target_type,
            target_id=target_id,
            feature=feature,
            rating=FeedbackRating.UP,
            reason_codes=(),
        )
    await db_session.commit()
    await grant_membership(authed_user.id, module.project_id, VIEWER_NAME)

    messages = await authed_client.get(f"/checklist-modules/{module.id}/mock-data-messages")
    change_sets = await authed_client.get(f"/checklist-modules/{module.id}/mock-data-change-sets")

    assert messages.json()[0]["myFeedback"]["rating"] == "up"
    assert change_sets.json()[0]["myFeedback"]["rating"] == "up"

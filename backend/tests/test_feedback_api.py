"""PUT/DELETE /feedback: visibility, validation, upsert, withdraw."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import VIEWER_NAME
from app.models.checklist import ChangeSetOrigin
from app.models.conversation import MessageRole
from app.models.feedback import Feedback
from app.models.user import User
from tests.conftest import GrantMembership
from tests.factories import (
    create_checklist_change_set,
    create_checklist_message,
    create_checklist_module,
    create_conversation,
    create_message,
    create_mock_data_change_set,
    create_user,
)

pytestmark = pytest.mark.asyncio

DOWN = {"rating": "down", "reasonCodes": ["wrong_file_cited"], "note": "Cited the old router."}


async def test_voting_on_my_own_answer_records_it(
    authed_client: AsyncClient, authed_user: User, db_session: AsyncSession
) -> None:
    conversation = await create_conversation(db_session, user_id=authed_user.id)
    message = await create_message(db_session, conversation_id=conversation.id)
    await db_session.commit()

    response = await authed_client.put(f"/feedback/message/{message.id}", json=DOWN)

    assert response.status_code == 200
    body = response.json()
    assert body["targetType"] == "message"
    assert body["rating"] == "down"
    assert body["reasonCodes"] == ["wrong_file_cited"]
    row = (await db_session.execute(select(Feedback))).scalar_one()
    assert row.feature == "answer"
    assert row.project_id == conversation.project_id
    assert len(row.prompt_version) == 12


async def test_a_second_put_changes_the_vote_in_place(
    authed_client: AsyncClient, authed_user: User, db_session: AsyncSession
) -> None:
    conversation = await create_conversation(db_session, user_id=authed_user.id)
    message = await create_message(db_session, conversation_id=conversation.id)
    await db_session.commit()

    await authed_client.put(f"/feedback/message/{message.id}", json=DOWN)
    response = await authed_client.put(
        f"/feedback/message/{message.id}", json={"rating": "up", "reasonCodes": []}
    )

    assert response.status_code == 200
    rows = (await db_session.execute(select(Feedback))).scalars().all()
    assert [(r.rating, r.reason_codes, r.note) for r in rows] == [("up", [], None)]


async def test_an_up_vote_clears_any_reason_codes_sent_with_it(
    authed_client: AsyncClient, authed_user: User, db_session: AsyncSession
) -> None:
    """An up vote is not a place for a down-vote reason to survive by accident."""
    conversation = await create_conversation(db_session, user_id=authed_user.id)
    message = await create_message(db_session, conversation_id=conversation.id)
    await db_session.commit()

    response = await authed_client.put(
        f"/feedback/message/{message.id}",
        json={"rating": "up", "reasonCodes": ["wrong_file_cited"]},
    )

    assert response.status_code == 200
    assert response.json()["reasonCodes"] == []
    row = (await db_session.execute(select(Feedback))).scalar_one()
    assert row.reason_codes == []


async def test_withdrawing_a_vote_removes_it(
    authed_client: AsyncClient, authed_user: User, db_session: AsyncSession
) -> None:
    conversation = await create_conversation(db_session, user_id=authed_user.id)
    message = await create_message(db_session, conversation_id=conversation.id)
    await db_session.commit()
    await authed_client.put(f"/feedback/message/{message.id}", json=DOWN)

    response = await authed_client.delete(f"/feedback/message/{message.id}")
    again = await authed_client.delete(f"/feedback/message/{message.id}")

    assert response.status_code == 204
    assert again.status_code == 204
    assert (await db_session.execute(select(Feedback))).first() is None


async def test_another_users_answer_is_the_same_404_as_a_missing_one(
    client_for_admin: AsyncClient, db_session: AsyncSession
) -> None:
    """No admin bypass under conversations, and no existence oracle."""
    owner = await create_user(db_session)
    conversation = await create_conversation(db_session, user_id=owner.id)
    message = await create_message(db_session, conversation_id=conversation.id)
    await db_session.commit()

    theirs = await client_for_admin.put(f"/feedback/message/{message.id}", json=DOWN)
    missing = await client_for_admin.put(f"/feedback/message/{uuid.uuid4()}", json=DOWN)

    assert theirs.status_code == missing.status_code == 404
    assert theirs.json() == missing.json()
    assert theirs.json()["detail"]["code"] == "FEEDBACK_TARGET_NOT_FOUND"


async def test_a_user_message_cannot_be_judged(
    authed_client: AsyncClient, authed_user: User, db_session: AsyncSession
) -> None:
    conversation = await create_conversation(db_session, user_id=authed_user.id)
    question = await create_message(
        db_session, conversation_id=conversation.id, role=MessageRole.USER
    )
    await db_session.commit()

    response = await authed_client.put(f"/feedback/message/{question.id}", json=DOWN)

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "FEEDBACK_TARGET_NOT_FOUND"


async def test_a_change_set_outside_my_projects_is_404(
    authed_client: AsyncClient, db_session: AsyncSession
) -> None:
    module = await create_checklist_module(db_session)
    change_set = await create_checklist_change_set(db_session, module_id=module.id)
    await db_session.commit()

    response = await authed_client.put(
        f"/feedback/checklist_change_set/{change_set.id}",
        json={"rating": "down", "reasonCodes": ["wrong_scope"]},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "FEEDBACK_TARGET_NOT_FOUND"


async def test_any_member_may_judge_a_change_set(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
) -> None:
    module = await create_checklist_module(db_session)
    change_set = await create_checklist_change_set(
        db_session, module_id=module.id, origin=ChangeSetOrigin.CHAT
    )
    await db_session.commit()
    await grant_membership(authed_user.id, module.project_id, VIEWER_NAME)

    response = await authed_client.put(
        f"/feedback/checklist_change_set/{change_set.id}",
        json={"rating": "down", "reasonCodes": ["duplicate_or_redundant"]},
    )

    assert response.status_code == 200
    row = (await db_session.execute(select(Feedback))).scalar_one()
    assert row.feature == "propose_checklist"


async def test_a_mock_data_change_set_records_its_generation_feature(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
) -> None:
    module = await create_checklist_module(db_session)
    change_set = await create_mock_data_change_set(db_session, module_id=module.id)
    await db_session.commit()
    await grant_membership(authed_user.id, module.project_id, VIEWER_NAME)

    response = await authed_client.put(
        f"/feedback/mock_data_change_set/{change_set.id}", json={"rating": "up"}
    )

    assert response.status_code == 200
    row = (await db_session.execute(select(Feedback))).scalar_one()
    assert row.feature == "generate_mock_data"


async def test_a_refinement_reply_can_be_judged(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
) -> None:
    module = await create_checklist_module(db_session)
    reply = await create_checklist_message(
        db_session, module_id=module.id, created_by=authed_user.id, role=MessageRole.ASSISTANT
    )
    await db_session.commit()
    await grant_membership(authed_user.id, module.project_id, VIEWER_NAME)

    response = await authed_client.put(
        f"/feedback/checklist_message/{reply.id}",
        json={"rating": "down", "reasonCodes": ["invented_something"]},
    )

    assert response.status_code == 200


async def test_a_code_that_does_not_fit_the_target_is_400(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
) -> None:
    module = await create_checklist_module(db_session)
    change_set = await create_checklist_change_set(db_session, module_id=module.id)
    await db_session.commit()
    await grant_membership(authed_user.id, module.project_id, VIEWER_NAME)

    response = await authed_client.put(
        f"/feedback/checklist_change_set/{change_set.id}",
        json={"rating": "down", "reasonCodes": ["wrong_file_cited"]},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "FEEDBACK_REASON_NOT_APPLICABLE"


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"rating": "down", "reasonCodes": []}, "reasonCodes"),
        ({"rating": "down", "reasonCodes": ["not_a_code"]}, "reasonCodes"),
        ({"rating": "up", "note": "x" * 501}, "note"),
        ({"rating": "sideways"}, "rating"),
    ],
)
async def test_invalid_bodies_are_422(
    authed_client: AsyncClient, body: dict[str, object], field: str
) -> None:
    response = await authed_client.put(f"/feedback/message/{uuid.uuid4()}", json=body)

    assert response.status_code == 422
    assert any(key.startswith(field) for key in response.json()["detail"]["fields"])


async def test_an_unknown_target_type_is_422(authed_client: AsyncClient) -> None:
    response = await authed_client.put(f"/feedback/project/{uuid.uuid4()}", json=DOWN)
    assert response.status_code == 422

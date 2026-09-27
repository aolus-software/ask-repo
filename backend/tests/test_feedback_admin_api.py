"""Admin feedback reads: admin-only, filtered through the scope, never naming a voter."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.feedback import FeedbackRating
from app.schemas.feedback import FeedbackAdminRead
from tests.factories import create_feedback, create_project, create_user

pytestmark = pytest.mark.asyncio


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
    serialized = response.text
    assert str(voter.id) not in serialized
    assert "voter@example.com" not in serialized
    assert "Vera Voter" not in serialized


def test_the_admin_schema_has_no_user_field() -> None:
    fields = set(FeedbackAdminRead.model_fields)
    assert not {f for f in fields if "user" in f or "email" in f or "actor" in f or "name" == f}


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

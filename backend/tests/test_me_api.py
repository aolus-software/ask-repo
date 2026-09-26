"""The `/me` surface: the caller's own memberships, sessions and activity.

Every route here is scoped to the caller by construction — none takes a user id — so
the tests that matter are the ones proving one user never reaches another's rows.
Clients sign in through `/auth/login` rather than minting a token, because the session
routes need a real refresh family and the `sid` claim that names it.
"""

import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import User
from tests.conftest import TEST_PASSWORD, GrantMembership
from tests.factories import create_project

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 Safari/605.1.15"


async def _login(client: AsyncClient, email: str) -> tuple[str, str]:
    """Sign in and return (access token, raw refresh cookie)."""
    response = await client.post(
        "/auth/login",
        json={"email": email, "password": TEST_PASSWORD},
        headers={"user-agent": UA},
    )
    assert response.status_code == 200, response.text
    return response.json()["accessToken"], response.cookies[get_settings().refresh_cookie_name]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_memberships_lists_the_callers_grants_with_role_names(
    client: AsyncClient,
    db_session: AsyncSession,
    authed_user: User,
    grant_membership: GrantMembership,
) -> None:
    alpha = await create_project(db_session, grant_owner=False, name="alpha")
    beta = await create_project(db_session, grant_owner=False, name="beta")
    await create_project(db_session, grant_owner=False, name="not-mine")
    await db_session.commit()
    await grant_membership(authed_user.id, beta.id, "viewer")
    await grant_membership(authed_user.id, alpha.id, "editor")
    access, _ = await _login(client, authed_user.email)

    response = await client.get("/me/memberships", headers=_bearer(access))

    assert response.status_code == 200
    assert response.json() == [
        {"projectId": str(alpha.id), "projectName": "alpha", "role": "editor"},
        {"projectId": str(beta.id), "projectName": "beta", "role": "viewer"},
    ]


async def test_memberships_drops_a_deleted_project(
    client: AsyncClient,
    db_session: AsyncSession,
    authed_user: User,
    grant_membership: GrantMembership,
) -> None:
    project = await create_project(db_session, grant_owner=False, name="gone")
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, "owner")
    project.deleted_at = datetime.now(UTC)
    await db_session.commit()
    access, _ = await _login(client, authed_user.email)

    response = await client.get("/me/memberships", headers=_bearer(access))

    assert response.json() == []


async def test_an_admin_sees_only_real_memberships(
    client: AsyncClient, db_session: AsyncSession, admin_user: User
) -> None:
    await create_project(db_session, grant_owner=False)
    await db_session.commit()
    access, _ = await _login(client, admin_user.email)

    response = await client.get("/me/memberships", headers=_bearer(access))

    assert response.json() == []


async def test_me_routes_require_a_token(client: AsyncClient) -> None:
    for path in ("/me/memberships", "/me/sessions", "/me/activity"):
        assert (await client.get(path)).status_code == 401, path
    assert (await client.delete(f"/me/sessions/{uuid.uuid4()}")).status_code == 401


async def test_me_routes_are_behind_the_password_change_gate(
    client: AsyncClient, db_session: AsyncSession, authed_user: User
) -> None:
    """`/me` is not gate-exempt: a user holding a temporary password reaches nothing
    here until they change it."""
    authed_user.must_change_password = True
    await db_session.commit()
    access, _ = await _login(client, authed_user.email)

    for path in ("/me/memberships", "/me/sessions", "/me/activity"):
        response = await client.get(path, headers=_bearer(access))
        assert response.status_code == 403, path
        assert response.json()["detail"]["code"] == "PASSWORD_CHANGE_REQUIRED"
    response = await client.delete(f"/me/sessions/{uuid.uuid4()}", headers=_bearer(access))
    assert response.status_code == 403

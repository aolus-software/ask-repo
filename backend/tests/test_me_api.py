"""The `/me` surface: the caller's own memberships, sessions and activity.

Every route here is scoped to the caller by construction — none takes a user id — so
the tests that matter are the ones proving one user never reaches another's rows.
Clients sign in through `/auth/login` rather than minting a token, because the session
routes need a real refresh family and the `sid` claim that names it.
"""

import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.audit import AuditEventType
from app.core.security import sha256_hex
from app.models import User
from tests.conftest import TEST_PASSWORD, AuditRows, GrantMembership
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


async def test_sessions_lists_each_live_sign_in_and_marks_this_one(
    client: AsyncClient, authed_user: User
) -> None:
    first, _ = await _login(client, authed_user.email)
    await _login(client, authed_user.email)

    response = await client.get("/me/sessions", headers=_bearer(first))

    assert response.status_code == 200
    sessions = response.json()
    assert len(sessions) == 2
    assert [s["current"] for s in sessions].count(True) == 1
    assert all(s["userAgent"] == UA for s in sessions)
    assert set(sessions[0]) == {
        "id",
        "userAgent",
        "ipAddress",
        "startedAt",
        "lastActiveAt",
        "expiresAt",
        "current",
    }


async def test_sessions_omits_a_logged_out_sign_in(client: AsyncClient, authed_user: User) -> None:
    """`logout` revokes only the presented token, leaving used ancestors unrevoked —
    a family is live only while it has an unused, unrevoked, unexpired head."""
    access, _ = await _login(client, authed_user.email)
    _, second_cookie = await _login(client, authed_user.email)
    # The refresh cookie is `Secure`; httpx will not resend it over the plain-http
    # test transport on its own (see `test_audit_write_sites.py`'s logout test), so
    # it is set on the jar explicitly.
    client.cookies.set(get_settings().refresh_cookie_name, second_cookie)
    await client.post("/auth/logout")

    response = await client.get("/me/sessions", headers=_bearer(access))

    assert len(response.json()) == 1


async def test_sessions_never_shows_another_users(
    client: AsyncClient, user_a: User, user_b: User
) -> None:
    access_a, _ = await _login(client, user_a.email)
    await _login(client, user_b.email)

    response = await client.get("/me/sessions", headers=_bearer(access_a))

    assert len(response.json()) == 1


async def test_revoking_a_session_ends_it(
    client: AsyncClient, authed_user: User, audit_rows: AuditRows
) -> None:
    access, _ = await _login(client, authed_user.email)
    _, other_cookie = await _login(client, authed_user.email)
    other = next(
        s
        for s in (await client.get("/me/sessions", headers=_bearer(access))).json()
        if not s["current"]
    )

    response = await client.delete(f"/me/sessions/{other['id']}", headers=_bearer(access))

    assert response.status_code == 204
    client.cookies.set(get_settings().refresh_cookie_name, other_cookie)
    assert (await client.post("/auth/refresh")).status_code == 401
    [row] = await audit_rows(AuditEventType.AUTH_SESSION_REVOKED)
    assert row.actor_user_id == authed_user.id
    assert row.details["familyId"] == other["id"]
    assert row.details["current"] is False
    assert row.details["revokedCount"] >= 1


async def test_revoking_the_current_session_is_allowed(
    client: AsyncClient, authed_user: User, audit_rows: AuditRows
) -> None:
    access, cookie = await _login(client, authed_user.email)
    current = (await client.get("/me/sessions", headers=_bearer(access))).json()[0]

    response = await client.delete(f"/me/sessions/{current['id']}", headers=_bearer(access))

    assert response.status_code == 204
    client.cookies.set(get_settings().refresh_cookie_name, cookie)
    assert (await client.post("/auth/refresh")).status_code == 401
    [row] = await audit_rows(AuditEventType.AUTH_SESSION_REVOKED)
    assert row.details["current"] is True


async def test_another_users_session_is_not_found(
    client: AsyncClient, db_session: AsyncSession, user_a: User, user_b: User
) -> None:
    """`404`, not `403`: the answer must not confirm that someone else's id exists."""
    access_a, _ = await _login(client, user_a.email)
    _, cookie_b = await _login(client, user_b.email)
    row = await db_session.execute(
        text("SELECT family_id FROM refresh_tokens WHERE token_hash = :hash"),
        {"hash": sha256_hex(cookie_b)},
    )
    family_b = row.scalar_one()

    response = await client.delete(f"/me/sessions/{family_b}", headers=_bearer(access_a))

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "SESSION_NOT_FOUND"
    client.cookies.set(get_settings().refresh_cookie_name, cookie_b)
    assert (await client.post("/auth/refresh")).status_code == 200


async def test_an_unknown_session_is_not_found(client: AsyncClient, authed_user: User) -> None:
    access, _ = await _login(client, authed_user.email)

    response = await client.delete(f"/me/sessions/{uuid.uuid4()}", headers=_bearer(access))

    assert response.status_code == 404

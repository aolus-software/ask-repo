"""One behavioural test per event: drive the real route, assert the real row.

`tests/test_audit_coverage.py` proves every mutating route has been *classified*.
This module proves each one actually records, with the payload the spec specifies —
the two are different failures and neither substitutes for the other.

Fixture parameters are annotated with the real ORM types (`User`, `Project`,
`ChecklistModule`, …), so import them from `app.models` as each task adds a test that
needs one. `ruff`'s `ANN` rules require the annotation, and `object` would defeat the
type checking that catches a fixture returning the wrong thing.
"""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.audit import AuditEventType
from app.core.security import sha256_hex
from app.models import User
from tests.conftest import TEST_PASSWORD, AuditRows


async def test_login_records_the_success(
    client: AsyncClient, authed_user: User, audit_rows: AuditRows
) -> None:
    response = await client.post(
        "/auth/login", json={"email": authed_user.email, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200

    rows = await audit_rows(AuditEventType.AUTH_LOGIN_SUCCEEDED)
    assert len(rows) == 1
    assert rows[0].actor_email == authed_user.email
    assert rows[0].outcome == "success"
    assert rows[0].details == {"mustChangePassword": False}


async def test_failed_login_records_the_attempt_against_a_known_account(
    client: AsyncClient, authed_user: User, audit_rows: AuditRows
) -> None:
    response = await client.post(
        "/auth/login", json={"email": authed_user.email, "password": "wrong-password"}
    )
    assert response.status_code == 401

    rows = await audit_rows(AuditEventType.AUTH_LOGIN_FAILED)
    assert len(rows) == 1
    assert rows[0].outcome == "failure"
    assert rows[0].actor_email == authed_user.email
    assert rows[0].details == {"unknownAccount": False}


async def test_failed_login_against_an_unknown_address_stores_no_address(
    client: AsyncClient, audit_rows: AuditRows
) -> None:
    """People paste passwords into the email field.

    This row is built from raw request input, so storing the submitted value blind
    would eventually put a password in the one table an operator is guaranteed to
    read. No match means nothing is stored but the fact and the source host.
    """
    response = await client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "hunter2"}
    )
    assert response.status_code == 401

    rows = await audit_rows(AuditEventType.AUTH_LOGIN_FAILED)
    assert len(rows) == 1
    assert rows[0].actor_user_id is None
    assert rows[0].actor_email is None
    assert rows[0].details == {"unknownAccount": True}


async def test_logout_records_its_scope(
    authed_client: AsyncClient, authed_user: User, audit_rows: AuditRows
) -> None:
    # `authed_client` carries a bearer token but no refresh cookie of its own — logout
    # reads the cookie, not the bearer, so log in first to have one to revoke. The
    # cookie is `Secure`, which httpx will not resend over the plain-http test
    # transport on its own, so it is set on the jar explicitly (see test_auth_api.py).
    login = await authed_client.post(
        "/auth/login", json={"email": authed_user.email, "password": TEST_PASSWORD}
    )
    assert login.status_code == 200
    authed_client.cookies.set(
        get_settings().refresh_cookie_name, login.cookies[get_settings().refresh_cookie_name]
    )

    response = await authed_client.post("/auth/logout")
    assert response.status_code == 204

    rows = await audit_rows(AuditEventType.AUTH_LOGOUT)
    assert len(rows) == 1
    assert rows[0].details == {"scope": "session"}


async def test_logout_all_records_the_wider_scope(
    authed_client: AsyncClient, authed_user: User, audit_rows: AuditRows
) -> None:
    login = await authed_client.post(
        "/auth/login", json={"email": authed_user.email, "password": TEST_PASSWORD}
    )
    assert login.status_code == 200

    response = await authed_client.post("/auth/logout-all")
    assert response.status_code == 204

    rows = await audit_rows(AuditEventType.AUTH_LOGOUT)
    assert rows[0].details == {"scope": "all"}


async def test_password_change_records_no_password(
    authed_client: AsyncClient, audit_rows: AuditRows
) -> None:
    """Both sides of this diff are what the content ban forbids storing.

    The event type is the whole record.
    """
    response = await authed_client.post(
        "/auth/change-password",
        json={"currentPassword": TEST_PASSWORD, "newPassword": "a-much-longer-secret"},
    )
    assert response.status_code == 200

    rows = await audit_rows(AuditEventType.AUTH_PASSWORD_CHANGED)
    assert len(rows) == 1
    assert rows[0].details == {"forced": False}
    assert "changed" not in rows[0].details
    serialised = str(rows[0].details)
    assert "a-much-longer-secret" not in serialised
    assert TEST_PASSWORD not in serialised


async def test_refresh_replay_records_the_family_and_revoked_count(
    client: AsyncClient, authed_user: User, db_session: AsyncSession, audit_rows: AuditRows
) -> None:
    """A genuine reuse, outside the grace window, is a replay and is recorded.

    A reuse *inside* the grace window mints a sibling instead (D12) and must not
    record — that branch is exercised by `tests/test_auth_api.py` and is not repeated
    here, since this module is about the payload of a recorded event, not the whole
    state machine.
    """
    login = await client.post(
        "/auth/login", json={"email": authed_user.email, "password": TEST_PASSWORD}
    )
    assert login.status_code == 200
    cookie_name = get_settings().refresh_cookie_name
    cookie = login.cookies[cookie_name]

    client.cookies.set(cookie_name, cookie)
    await client.post("/auth/refresh")

    # Age the now-consumed token past the grace window so the next presentation of
    # the original cookie is a genuine replay rather than the two-tabs race.
    await db_session.execute(
        text("UPDATE refresh_tokens SET used_at = :stale WHERE token_hash = :hash"),
        {"stale": datetime.now(UTC) - timedelta(hours=1), "hash": sha256_hex(cookie)},
    )
    await db_session.commit()

    client.cookies.set(cookie_name, cookie)
    response = await client.post("/auth/refresh")
    assert response.status_code == 401

    rows = await audit_rows(AuditEventType.AUTH_REFRESH_REPLAYED)
    assert len(rows) == 1
    assert rows[0].outcome == "failure"
    assert rows[0].details["revokedCount"] >= 1
    assert isinstance(rows[0].details["familyId"], str)


async def test_user_create_records_the_new_values_with_a_null_before(
    client_for_admin: AsyncClient, audit_rows: AuditRows
) -> None:
    response = await client_for_admin.post(
        "/users",
        json={
            "name": "New Person",
            "email": "new@example.com",
            "password": "a-long-enough-password",
            "isAdmin": False,
        },
    )
    assert response.status_code == 201

    rows = await audit_rows(AuditEventType.USER_CREATED)
    assert len(rows) == 1
    assert rows[0].target_label == "new@example.com"
    assert rows[0].details["changed"]["email"] == {"before": None, "after": "new@example.com"}
    assert rows[0].details["changed"]["isAdmin"] == {"before": None, "after": False}
    assert rows[0].details["source"] == "api"
    # The password is nowhere in the row, in any form.
    assert "a-long-enough-password" not in str(rows[0].details)


async def test_user_update_records_only_what_changed(
    client_for_admin: AsyncClient, user_b: User, audit_rows: AuditRows
) -> None:
    response = await client_for_admin.patch(f"/users/{user_b.id}", json={"isAdmin": True})
    assert response.status_code == 200

    rows = await audit_rows(AuditEventType.USER_UPDATED)
    assert len(rows) == 1
    # `email` did not change, so it is absent — `changed` is a diff, not a snapshot.
    assert rows[0].details["changed"] == {"isAdmin": {"before": False, "after": True}}


async def test_user_deactivation_records_who_and_whom(
    client_for_admin: AsyncClient, user_b: User, admin_user: User, audit_rows: AuditRows
) -> None:
    response = await client_for_admin.delete(f"/users/{user_b.id}")
    assert response.status_code == 204

    rows = await audit_rows(AuditEventType.USER_DEACTIVATED)
    assert len(rows) == 1
    assert rows[0].actor_user_id == admin_user.id
    assert rows[0].target_id == user_b.id
    assert rows[0].target_label == user_b.email
    assert rows[0].details == {}


async def test_user_password_reset_records_no_password(
    client_for_admin: AsyncClient, user_b: User, audit_rows: AuditRows
) -> None:
    response = await client_for_admin.post(
        f"/users/{user_b.id}/reset-password",
        json={"newPassword": "a-brand-new-temporary-password"},
    )
    assert response.status_code == 200

    rows = await audit_rows(AuditEventType.USER_PASSWORD_RESET)
    assert len(rows) == 1
    assert rows[0].details == {"forced": True}
    serialised = str(rows[0].details)
    assert "a-brand-new-temporary-password" not in serialised

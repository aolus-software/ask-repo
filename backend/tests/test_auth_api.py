"""The /auth surface: login, rotation, the gate, and revocation.

The rotation tests are the ones worth reading twice. Strict rotation would log out any
client that refreshes twice concurrently — two browser tabs is enough — so a 10-second
grace window mints a sibling token instead of treating the second use as a replay
(D12). Anything outside the window still revokes the whole family.
"""

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.security import hash_password, sha256_hex
from app.models import User

PASSWORD = "a-perfectly-fine-passphrase"
NEW_PASSWORD = "another-entirely-fine-passphrase"


async def _make_user(
    session: AsyncSession,
    *,
    email: str = "dev@example.com",
    is_admin: bool = False,
    must_change_password: bool = False,
) -> User:
    user = User(
        id=uuid.uuid4(),
        name="Dev",
        email=email,
        password_hash=hash_password(PASSWORD, cost=4),
        is_admin=is_admin,
        must_change_password=must_change_password,
    )
    session.add(user)
    await session.commit()
    return user


async def _login(client: AsyncClient, email: str = "dev@example.com") -> tuple[str, str]:
    """Log in and return (access token, raw refresh cookie)."""
    response = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    cookie = response.cookies[get_settings().refresh_cookie_name]
    return response.json()["accessToken"], cookie


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_login_returns_an_access_token_and_the_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session)

    response = await client.post(
        "/auth/login", json={"email": "dev@example.com", "password": PASSWORD}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tokenType"] == "bearer"
    assert body["expiresIn"] == get_settings().access_token_ttl_minutes * 60
    assert body["user"]["email"] == "dev@example.com"


async def test_login_sets_an_httponly_refresh_cookie(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """D3: unreadable by any script on the page, unlike localStorage."""
    await _make_user(db_session)

    response = await client.post(
        "/auth/login", json={"email": "dev@example.com", "password": PASSWORD}
    )

    header = response.headers["set-cookie"]
    assert "HttpOnly" in header
    assert "Path=/auth" in header
    assert "SameSite=lax" in header.replace("samesite", "SameSite")


async def test_login_never_returns_the_refresh_token_in_the_body(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session)

    response = await client.post(
        "/auth/login", json={"email": "dev@example.com", "password": PASSWORD}
    )

    assert "refresh" not in response.json()


async def test_login_records_last_login_at(client: AsyncClient, db_session: AsyncSession) -> None:
    user = await _make_user(db_session)

    await client.post("/auth/login", json={"email": "dev@example.com", "password": PASSWORD})
    await db_session.refresh(user)

    assert user.last_login_at is not None


async def test_a_wrong_password_and_an_unknown_email_are_indistinguishable(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """docs/PRD.md:114 — one uniform failure, so login cannot enumerate accounts."""
    await _make_user(db_session)

    wrong = await client.post(
        "/auth/login", json={"email": "dev@example.com", "password": "wrong-but-long-enough"}
    )
    unknown = await client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "wrong-but-long-enough"}
    )

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


async def test_a_soft_deleted_user_cannot_log_in(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session)
    user.deleted_at = datetime.now(UTC)
    await db_session.commit()

    response = await client.post(
        "/auth/login", json={"email": "dev@example.com", "password": PASSWORD}
    )

    assert response.status_code == 401


async def test_the_sixth_login_attempt_in_a_minute_is_429(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session)

    for _ in range(get_settings().login_rate_per_minute_ip):
        await client.post(
            "/auth/login", json={"email": "dev@example.com", "password": "wrong-but-long-enough"}
        )
    response = await client.post(
        "/auth/login", json={"email": "dev@example.com", "password": PASSWORD}
    )

    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "RATE_LIMITED"


async def test_me_returns_the_caller(client: AsyncClient, db_session: AsyncSession) -> None:
    await _make_user(db_session)
    access, _ = await _login(client)

    response = await client.get("/auth/me", headers=_bearer(access))

    assert response.status_code == 200
    assert response.json()["email"] == "dev@example.com"


async def test_refresh_rotates_the_cookie_and_returns_a_new_access_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session)
    _, cookie = await _login(client)
    name = get_settings().refresh_cookie_name

    response = await client.post("/auth/refresh", cookies={name: cookie})

    assert response.status_code == 200
    assert response.cookies[name] != cookie


async def test_refresh_without_a_cookie_is_401(client: AsyncClient) -> None:
    response = await client.post("/auth/refresh")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "INVALID_TOKEN"


async def test_replaying_a_consumed_token_after_the_grace_window_revokes_the_family(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The point of rotation: a leaked token is detected on its second use."""
    await _make_user(db_session)
    _, cookie = await _login(client)
    name = get_settings().refresh_cookie_name
    await client.post("/auth/refresh", cookies={name: cookie})

    # Age the consumed token past the grace window.
    await db_session.execute(
        text("UPDATE refresh_tokens SET used_at = :stale WHERE token_hash = :hash"),
        {"stale": datetime.now(UTC) - timedelta(hours=1), "hash": sha256_hex(cookie)},
    )
    await db_session.commit()

    response = await client.post("/auth/refresh", cookies={name: cookie})

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "REFRESH_TOKEN_REUSED"

    remaining = await db_session.execute(
        text("SELECT count(*) FROM refresh_tokens WHERE revoked_at IS NULL")
    )
    assert remaining.scalar_one() == 0


async def test_two_refreshes_inside_the_grace_window_both_succeed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """D12: two tabs racing a refresh must not log the user out."""
    await _make_user(db_session)
    _, cookie = await _login(client)
    name = get_settings().refresh_cookie_name

    first = await client.post("/auth/refresh", cookies={name: cookie})
    second = await client.post("/auth/refresh", cookies={name: cookie})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.cookies[name] != second.cookies[name]

    revoked = await db_session.execute(
        text("SELECT count(*) FROM refresh_tokens WHERE revoked_at IS NOT NULL")
    )
    assert revoked.scalar_one() == 0

    families = await db_session.execute(text("SELECT DISTINCT family_id FROM refresh_tokens"))
    assert len(families.scalars().all()) == 1

    tokens = await db_session.execute(text("SELECT count(*) FROM refresh_tokens"))
    # The original login token plus the two siblings minted inside the grace window.
    assert tokens.scalar_one() == 3


async def test_an_expired_refresh_token_does_not_revoke_the_family(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Expiry is checked before replay: an honestly-stale token is not an attack."""
    await _make_user(db_session)
    _, cookie = await _login(client)
    name = get_settings().refresh_cookie_name
    await db_session.execute(
        text("UPDATE refresh_tokens SET expires_at = :past WHERE token_hash = :hash"),
        {"past": datetime.now(UTC) - timedelta(days=1), "hash": sha256_hex(cookie)},
    )
    await db_session.commit()

    response = await client.post("/auth/refresh", cookies={name: cookie})

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "TOKEN_EXPIRED"


async def test_refresh_fails_once_the_owner_is_deactivated(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session)
    _, cookie = await _login(client)
    user.deleted_at = datetime.now(UTC)
    await db_session.commit()

    response = await client.post(
        "/auth/refresh", cookies={get_settings().refresh_cookie_name: cookie}
    )

    assert response.status_code == 401


async def test_change_password_clears_the_flag_and_works_with_the_same_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """must_change_password is not a claim, so no new access token is needed."""
    await _make_user(db_session, must_change_password=True)
    access, cookie = await _login(client)

    changed = await client.post(
        "/auth/change-password",
        headers=_bearer(access),
        cookies={get_settings().refresh_cookie_name: cookie},
        json={"currentPassword": PASSWORD, "newPassword": NEW_PASSWORD},
    )
    listing = await client.get("/users", headers=_bearer(access))

    assert changed.status_code == 200
    assert changed.json()["mustChangePassword"] is False
    assert listing.status_code == 200


async def test_the_gate_blocks_users_until_the_password_changes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session, must_change_password=True)
    access, _ = await _login(client)

    response = await client.get("/users", headers=_bearer(access))

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PASSWORD_CHANGE_REQUIRED"


async def test_change_password_rejects_a_wrong_current_password(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session)
    access, cookie = await _login(client)

    response = await client.post(
        "/auth/change-password",
        headers=_bearer(access),
        cookies={get_settings().refresh_cookie_name: cookie},
        json={"currentPassword": "not-the-current-one", "newPassword": NEW_PASSWORD},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "INVALID_CREDENTIALS"


async def test_change_password_rejects_a_weak_new_password(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session)
    access, cookie = await _login(client)

    response = await client.post(
        "/auth/change-password",
        headers=_bearer(access),
        cookies={get_settings().refresh_cookie_name: cookie},
        json={"currentPassword": PASSWORD, "newPassword": "short"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "WEAK_PASSWORD"


async def test_change_password_spares_the_callers_own_session(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """docs/PRD.md:108 — all *other* refresh tokens are revoked."""
    await _make_user(db_session)
    access, cookie = await _login(client)
    name = get_settings().refresh_cookie_name

    await client.post(
        "/auth/change-password",
        headers=_bearer(access),
        cookies={name: cookie},
        json={"currentPassword": PASSWORD, "newPassword": NEW_PASSWORD},
    )
    response = await client.post("/auth/refresh", cookies={name: cookie})

    assert response.status_code == 200


async def test_logout_revokes_the_presented_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session)
    _, cookie = await _login(client)
    name = get_settings().refresh_cookie_name

    logout = await client.post("/auth/logout", cookies={name: cookie})
    reuse = await client.post("/auth/refresh", cookies={name: cookie})

    assert logout.status_code == 204
    assert reuse.status_code == 401


async def test_logout_is_idempotent(client: AsyncClient) -> None:
    """Logging out twice, or with no cookie, is not an error condition."""
    response = await client.post("/auth/logout")

    assert response.status_code == 204


async def test_logout_all_revokes_every_session(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session)
    access, first_cookie = await _login(client)
    _, second_cookie = await _login(client)
    name = get_settings().refresh_cookie_name

    await client.post("/auth/logout-all", headers=_bearer(access))

    for cookie in (first_cookie, second_cookie):
        assert (await client.post("/auth/refresh", cookies={name: cookie})).status_code == 401


async def test_no_auth_response_ever_contains_a_hash(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _make_user(db_session)
    access, _ = await _login(client)

    for response in (
        await client.post("/auth/login", json={"email": "dev@example.com", "password": PASSWORD}),
        await client.get("/auth/me", headers=_bearer(access)),
    ):
        assert "$2b$" not in response.text
        assert "passwordHash" not in response.text


def test_the_cookie_alias_matches_the_configured_name() -> None:
    """FastAPI resolves the Cookie alias at import time, so it cannot read a setting.

    If these ever diverge, refresh silently stops seeing the cookie and every session
    ends after 15 minutes with no error anywhere.
    """
    from app.api.routes.auth import RefreshCookie

    # mypy resolves `RefreshCookie` to its aliased `str | None` in a value position, so
    # it does not see `Annotated.__metadata__`; the attribute exists at runtime.
    alias = RefreshCookie.__metadata__[0].alias  # type: ignore[attr-defined]
    assert alias == get_settings().refresh_cookie_name


def test_the_auth_prefix_is_gate_exempt() -> None:
    """The gate hardcodes its exempt prefixes rather than importing the auth router,
    to avoid inverting the dependency direction between routes and middleware
    (routes depend on middleware through deps.py). That means nothing forces the two
    to stay in sync — this test buys that property back.

    Renaming the auth prefix without updating `GATE_EXEMPT_PREFIXES` would silently
    lock every user out of the one surface they need while `must_change_password` is
    set, turning what should be a red test into a production incident.
    """
    from app.api.routes.auth import router as auth_router
    from app.core.middleware import GATE_EXEMPT_PREFIXES

    assert auth_router.prefix in GATE_EXEMPT_PREFIXES

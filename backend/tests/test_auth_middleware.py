"""Identity establishment and the forced-password-change gate.

Two regressions are pinned here on purpose:

- `/auth` routes must still receive identity. A middleware that skips the whole
  pipeline for exempt paths leaves `request.state.auth` unset, and `GET /auth/me`
  fails with RuntimeError rather than returning the caller.
- The gate's 403 must carry CORS headers, or the browser reports an opaque network
  error and the frontend never sees the code it is meant to branch on.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, CurrentUser
from app.config import get_settings
from app.core.security import create_access_token
from app.models import User


async def _make_user(
    session: AsyncSession,
    *,
    is_admin: bool = False,
    must_change_password: bool = False,
    deleted: bool = False,
) -> User:
    user = User(
        id=uuid.uuid4(),
        name="Dev",
        email=f"{uuid.uuid4().hex}@example.com",
        password_hash="$2b$04$placeholderplaceholderplaceholderplaceholderplaceholderxx",
        is_admin=is_admin,
        must_change_password=must_change_password,
        deleted_at=datetime.now(UTC) if deleted else None,
    )
    session.add(user)
    await session.commit()
    return user


def _token(user: User) -> str:
    settings = get_settings()
    token, _ = create_access_token(
        user.id, secret=settings.secret_key, ttl_minutes=settings.access_token_ttl_minutes
    )
    return token


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(user)}"}


@pytest.fixture
def probe_app(app: FastAPI) -> FastAPI:
    """The real app plus two probe routes, so the real middleware stack is exercised."""

    @app.get("/probe/any")
    async def probe_any(current_user: CurrentUser) -> dict[str, str]:
        return {"email": current_user.email}

    @app.get("/probe/admin")
    async def probe_admin(current_user: AdminUser) -> dict[str, str]:
        return {"email": current_user.email}

    return app


@pytest.fixture
async def probe_client(probe_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=probe_app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


async def test_a_valid_token_reaches_the_route(
    probe_client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session)

    response = await probe_client.get("/probe/any", headers=_auth(user))

    assert response.status_code == 200
    assert response.json()["email"] == user.email


async def test_no_header_is_401(probe_client: AsyncClient) -> None:
    response = await probe_client.get("/probe/any")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "INVALID_TOKEN"


async def test_a_garbage_token_is_401(probe_client: AsyncClient) -> None:
    response = await probe_client.get("/probe/any", headers={"Authorization": "Bearer not.a.jwt"})

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "INVALID_TOKEN"


async def test_an_expired_token_reports_expiry_distinctly(probe_client: AsyncClient) -> None:
    """The frontend refreshes on TOKEN_EXPIRED and hard-logs-out on INVALID_TOKEN."""
    settings = get_settings()
    token, _ = create_access_token(uuid.uuid4(), secret=settings.secret_key, ttl_minutes=-1)

    response = await probe_client.get("/probe/any", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "TOKEN_EXPIRED"


async def test_a_soft_deleted_users_live_token_stops_working(
    probe_client: AsyncClient, db_session: AsyncSession
) -> None:
    """docs/PRD.md:101 — deactivation ends sessions immediately, not in 15 minutes.

    This is the reason the middleware loads the user row on every request instead of
    trusting the token's claims.
    """
    user = await _make_user(db_session)
    headers = _auth(user)
    user.deleted_at = datetime.now(UTC)
    await db_session.commit()

    response = await probe_client.get("/probe/any", headers=headers)

    assert response.status_code == 401


async def test_a_non_admin_is_403_on_an_admin_route(
    probe_client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, is_admin=False)

    response = await probe_client.get("/probe/admin", headers=_auth(user))

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ADMIN_REQUIRED"


async def test_an_admin_passes_the_admin_route(
    probe_client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, is_admin=True)

    response = await probe_client.get("/probe/admin", headers=_auth(user))

    assert response.status_code == 200


async def test_the_gate_blocks_a_route_outside_auth(
    probe_client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, must_change_password=True)

    response = await probe_client.get("/probe/any", headers=_auth(user))

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PASSWORD_CHANGE_REQUIRED"


async def test_the_gates_403_carries_cors_headers(
    probe_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Without this the browser sees an opaque failure, not the code it must branch on.

    Asserts the property rather than the middleware ordering, so it survives a change
    in Starlette's internals.
    """
    user = await _make_user(db_session, must_change_password=True)
    headers = {**_auth(user), "Origin": "http://localhost:3000"}

    response = await probe_client.get("/probe/any", headers=headers)

    assert response.status_code == 403
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


async def test_health_is_reachable_while_the_gate_is_active(
    probe_client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, must_change_password=True)

    response = await probe_client.get("/health/live", headers=_auth(user))

    assert response.status_code == 200


async def test_identity_is_established_even_on_exempt_paths(
    probe_app: FastAPI, db_session: AsyncSession
) -> None:
    """Trap 1: an early return for /auth would leave request.state.auth unset.

    Uses a probe mounted under the exempt prefix, since /auth/me does not exist yet.
    """

    @probe_app.get("/auth/probe-me")
    async def probe_me(current_user: CurrentUser) -> dict[str, bool]:
        return {"mustChange": current_user.must_change_password}

    user = await _make_user(db_session, must_change_password=True)
    transport = ASGITransport(app=probe_app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/auth/probe-me", headers=_auth(user))

    assert response.status_code == 200
    assert response.json()["mustChange"] is True

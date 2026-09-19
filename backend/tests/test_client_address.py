"""Who the backend thinks is calling, once the request has crossed the BFF.

Every request reaches this app from the Next server, never from a browser, so the
caller's address only exists in `X-Forwarded-For`. Issue #40 is what happens when it
does not arrive: the per-caller login limit collapses into one instance-wide bucket of
five attempts a minute, and every audit row records the proxy.

These tests are the half a backend-only suite could not catch before, because the
backend's own logic was never wrong -- `client_ip` has always counted from the right.
What was missing was the header, so every case here sends one.
"""

import uuid

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.security import hash_password
from app.models import User
from tests.conftest import AuditRows

PASSWORD = "a-perfectly-fine-passphrase"
BEHIND_ONE_PROXY = {"trusted_proxy_hops": 1}


@pytest.fixture
def behind_a_proxy(app: FastAPI) -> FastAPI:
    """The production topology: one Caddy, with Next relaying its header.

    `TRUSTED_PROXY_HOPS=1` is the production default (`docs/deployment.md` §4); the
    development default of `0` is the one that ignores the header, so a test that left
    it there would assert nothing about the forwarded address.

    One hop, not two, even though Next is also in the path: Caddy appends the browser's
    address and Next relays that header unchanged, so the chain carries one entry. Every
    header below is written the way it arrives here in production.
    """
    base: Settings = get_settings()
    app.dependency_overrides[get_settings] = lambda: base.model_copy(update=BEHIND_ONE_PROXY)
    return app


async def _make_user(session: AsyncSession, *, email: str = "dev@example.com") -> User:
    user = User(
        id=uuid.uuid4(),
        name="Dev",
        email=email,
        password_hash=hash_password(PASSWORD, cost=4),
        is_admin=False,
        must_change_password=False,
    )
    session.add(user)
    await session.commit()
    return user


async def _spend_the_budget(client: AsyncClient, *, address: str) -> None:
    """Use every login attempt one address is allowed in the current window."""
    for _ in range(get_settings().login_rate_per_minute_ip):
        await client.post(
            "/auth/login",
            json={"email": "dev@example.com", "password": "wrong-but-long-enough"},
            headers={"x-forwarded-for": address},
        )


async def test_two_callers_get_two_budgets(
    behind_a_proxy: FastAPI, client: AsyncClient, db_session: AsyncSession
) -> None:
    """The bug itself: one colleague's attempts must not spend another's allowance."""
    await _make_user(db_session)

    await _spend_the_budget(client, address="203.0.113.7")
    response = await client.post(
        "/auth/login",
        json={"email": "dev@example.com", "password": PASSWORD},
        headers={"x-forwarded-for": "203.0.113.8"},
    )

    assert response.status_code == 200


async def test_one_caller_still_runs_out(
    behind_a_proxy: FastAPI, client: AsyncClient, db_session: AsyncSession
) -> None:
    """The control the separation must not cost: the same caller is still bounded."""
    await _make_user(db_session)

    await _spend_the_budget(client, address="203.0.113.7")
    response = await client.post(
        "/auth/login",
        json={"email": "dev@example.com", "password": PASSWORD},
        headers={"x-forwarded-for": "203.0.113.7"},
    )

    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "RATE_LIMITED"


async def test_a_forged_entry_does_not_buy_a_fresh_budget(
    behind_a_proxy: FastAPI, client: AsyncClient, db_session: AsyncSession
) -> None:
    """Relaying a browser-settable header is only safe because of this.

    The BFF passes `X-Forwarded-For` through, so a client can prepend whatever it
    likes. Counting from the right discards it: the entry the proxy appended is the
    one that decides the bucket.
    """
    await _make_user(db_session)

    await _spend_the_budget(client, address="203.0.113.7")
    response = await client.post(
        "/auth/login",
        json={"email": "dev@example.com", "password": PASSWORD},
        headers={"x-forwarded-for": "1.2.3.4, 203.0.113.7"},
    )

    assert response.status_code == 429


async def test_the_audit_row_records_the_caller_not_the_proxy(
    behind_a_proxy: FastAPI,
    client: AsyncClient,
    db_session: AsyncSession,
    audit_rows: AuditRows,
) -> None:
    """The second half of #40: both readers resolve the address the same way.

    `docs/PRD.md` §3.4 leans on this. A failed login against an address that matches no
    account deliberately stores no email, so the source host is the only thing left that
    shows an enumeration attempt as a pattern from one place -- and it showed the Next
    server for everyone.
    """
    await _make_user(db_session)

    await client.post(
        "/auth/login",
        json={"email": "dev@example.com", "password": PASSWORD},
        headers={"x-forwarded-for": "203.0.113.7"},
    )

    rows = await audit_rows("auth.login.succeeded")
    assert [row.ip_address for row in rows] == ["203.0.113.7"]


async def test_no_forwarded_header_falls_back_to_the_socket(
    behind_a_proxy: FastAPI,
    client: AsyncClient,
    db_session: AsyncSession,
    audit_rows: AuditRows,
) -> None:
    """A request that arrives with no chain is recorded from its peer, not dropped."""
    await _make_user(db_session)

    await client.post("/auth/login", json={"email": "dev@example.com", "password": PASSWORD})

    rows = await audit_rows("auth.login.succeeded")
    assert rows[0].ip_address is not None

"""The reset routes on the wire: identical answers, one email, and the limits."""

import uuid
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.security import hash_password
from app.mail.recording import RecordingMailSender
from app.mail.sender import get_mail_sender
from app.models import User

NEW_PASSWORD = "another-entirely-fine-passphrase"


@pytest.fixture
def mail(app: FastAPI) -> Iterator[RecordingMailSender]:
    """Mail on, with a recording sender in place of the relay."""
    sender = RecordingMailSender()
    settings = get_settings().model_copy(
        update={
            "mail_enabled": True,
            "smtp_host": "relay.internal",
            "smtp_from": "askrepo@example.com",
            "app_base_url": "https://askrepo.internal",
        }
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_mail_sender] = lambda: sender
    yield sender
    app.dependency_overrides.clear()


async def _user(session: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        name="Dev",
        email="dev@example.com",
        password_hash=hash_password("a-perfectly-fine-passphrase", cost=4),
    )
    session.add(user)
    await session.commit()
    return user


def _token_from(sender: RecordingMailSender) -> str:
    [email] = sender.sent
    return email.body.split("#token=", 1)[1].split()[0]


async def test_availability_reports_the_switch(client: AsyncClient) -> None:
    response = await client.get("/auth/password-reset/availability")
    assert response.status_code == 200
    assert response.json() == {"enabled": False}


async def test_availability_reports_on_when_mail_is_on(
    client: AsyncClient, mail: RecordingMailSender
) -> None:
    assert (await client.get("/auth/password-reset/availability")).json() == {"enabled": True}


async def test_request_with_mail_off_is_409(client: AsyncClient) -> None:
    response = await client.post("/auth/password-reset/request", json={"email": "dev@example.com"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "PASSWORD_RESET_UNAVAILABLE"


async def test_known_and_unknown_addresses_get_identical_answers(
    client: AsyncClient, db_session: AsyncSession, mail: RecordingMailSender
) -> None:
    await _user(db_session)
    known = await client.post("/auth/password-reset/request", json={"email": "dev@example.com"})
    unknown = await client.post("/auth/password-reset/request", json={"email": "no@example.com"})

    assert known.status_code == unknown.status_code == 202
    assert known.content == unknown.content == b""
    assert len(mail.sent) == 1
    assert mail.sent[0].to == "dev@example.com"


async def test_the_full_flow_resets_and_the_link_then_dies(
    client: AsyncClient, db_session: AsyncSession, mail: RecordingMailSender
) -> None:
    await _user(db_session)
    await client.post("/auth/password-reset/request", json={"email": "dev@example.com"})
    token = _token_from(mail)

    body = {"token": token, "newPassword": NEW_PASSWORD}
    assert (await client.post("/auth/password-reset/confirm", json=body)).status_code == 204
    login = await client.post(
        "/auth/login", json={"email": "dev@example.com", "password": NEW_PASSWORD}
    )
    assert login.status_code == 200

    again = await client.post("/auth/password-reset/confirm", json=body)
    assert again.status_code == 400
    assert again.json()["detail"]["code"] == "PASSWORD_RESET_TOKEN_INVALID"


async def test_an_unknown_token_is_the_same_400(client: AsyncClient) -> None:
    response = await client.post(
        "/auth/password-reset/confirm", json={"token": "x" * 43, "newPassword": NEW_PASSWORD}
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "PASSWORD_RESET_TOKEN_INVALID"


async def test_the_per_email_limit_applies_to_unknown_addresses_too(
    client: AsyncClient, mail: RecordingMailSender
) -> None:
    limit = get_settings().password_reset_rate_per_hour_email
    for _ in range(limit):
        response = await client.post(
            "/auth/password-reset/request", json={"email": "no@example.com"}
        )
        assert response.status_code == 202
    over = await client.post("/auth/password-reset/request", json={"email": "no@example.com"})
    assert over.status_code == 429
    assert over.json()["detail"]["code"] == "RATE_LIMITED"


async def test_the_per_ip_limit_counts_every_address(
    client: AsyncClient, mail: RecordingMailSender
) -> None:
    limit = get_settings().password_reset_rate_per_hour_ip
    for index in range(limit):
        await client.post("/auth/password-reset/request", json={"email": f"a{index}@example.com"})
    over = await client.post("/auth/password-reset/request", json={"email": "z@example.com"})
    assert over.status_code == 429


async def test_the_forced_change_gate_does_not_block_reset(client: AsyncClient) -> None:
    """/auth is gate-exempt; unauthenticated callers reach these routes."""
    response = await client.get("/auth/password-reset/availability")
    assert response.status_code == 200

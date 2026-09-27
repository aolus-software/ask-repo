"""`GET /events` pre-flight: every status that is not 200 is decided before the first byte."""

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.live.bus import InMemoryLiveEventBus
from app.models import User


async def test_events_requires_a_token(client: AsyncClient) -> None:
    assert (await client.get("/events")).status_code == 401


async def test_events_is_behind_the_password_change_gate(
    authed_client: AsyncClient, authed_user: User, db_session: AsyncSession
) -> None:
    authed_user.must_change_password = True
    await db_session.commit()

    response = await authed_client.get("/events")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PASSWORD_CHANGE_REQUIRED"


async def test_events_is_unavailable_when_the_hub_is_down(
    authed_client: AsyncClient, live_bus: InMemoryLiveEventBus
) -> None:
    live_bus.available = False

    response = await authed_client.get("/events")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "LIVE_EVENTS_UNAVAILABLE"


async def test_events_is_unavailable_when_disabled(
    app_with_queue: FastAPI, authed_client: AsyncClient
) -> None:
    base: Settings = get_settings()
    app_with_queue.dependency_overrides[get_settings] = lambda: base.model_copy(
        update={"live_events_enabled": False}
    )

    response = await authed_client.get("/events")

    assert response.status_code == 503

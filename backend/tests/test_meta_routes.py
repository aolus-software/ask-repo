"""Index and health routes."""

from httpx import AsyncClient


async def test_index_reports_app_and_time(client: AsyncClient) -> None:
    response = await client.get("/")

    assert response.status_code == 200
    body = response.json()
    assert body["app"] == "AskRepo API"
    assert body["version"]
    assert body["date"]


async def test_health_reports_env(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["env"]
    assert body["timestamp"]


async def test_liveness_is_ok(client: AsyncClient) -> None:
    response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readiness_reports_empty_checks_until_datastores_are_wired(
    client: AsyncClient,
) -> None:
    """`checks` gains Postgres/Qdrant/Redis probes at M0/M1 without a shape change."""
    response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {}}

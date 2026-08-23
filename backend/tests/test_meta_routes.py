"""Index and health routes."""

from fastapi.testclient import TestClient


def test_index_reports_app_and_time(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    body = response.json()
    assert body["app"] == "AskRepo API"
    assert body["version"]
    assert body["date"]


def test_health_reports_env(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["env"]
    assert body["timestamp"]


def test_liveness_is_ok(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_empty_checks_until_datastores_are_wired(
    client: TestClient,
) -> None:
    """`checks` gains Postgres/Qdrant/Redis probes at M0/M1 without a shape change."""
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {}}

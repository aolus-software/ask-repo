"""The project routes end to end, against an in-memory queue."""

from httpx import AsyncClient

from app.models.project import ProjectStatus


async def test_create_returns_201_and_camel_case(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/projects", json={"repoUrl": "https://github.com/acme/repo.git", "branch": "main"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["repoUrl"] == "https://github.com/acme/repo.git"
    assert body["status"] == ProjectStatus.PENDING
    # snake_case on the wire is the defect tests/test_api_model.py exists to catch.
    assert "repo_url" not in body
    assert "lastIndexedCommit" in body


async def test_create_never_echoes_the_pat(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/projects", json={"repoUrl": "https://github.com/acme/repo.git", "pat": "ghp_secret"}
    )
    assert response.status_code == 201
    assert "ghp_secret" not in response.text
    assert "pat" not in response.json()


async def test_create_rejects_a_bad_url_with_400(authed_client: AsyncClient) -> None:
    response = await authed_client.post(
        "/projects", json={"repoUrl": "http://github.com/acme/repo.git"}
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "INVALID_REPO_URL"


async def test_list_is_paginated_not_a_bare_array(authed_client: AsyncClient) -> None:
    await authed_client.post("/projects", json={"repoUrl": "https://github.com/acme/one.git"})
    response = await authed_client.get("/projects")

    assert response.status_code == 200
    assert set(response.json()) >= {"items", "page", "limit", "totalCount", "totalPages"}


async def test_list_rejects_an_unknown_sort_field(authed_client: AsyncClient) -> None:
    response = await authed_client.get("/projects", params={"sort": "encryptedPat"})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "INVALID_SORT_FIELD"


async def test_reindex_returns_202_when_a_run_is_in_flight(authed_client: AsyncClient) -> None:
    created = await authed_client.post(
        "/projects", json={"repoUrl": "https://github.com/acme/repo.git"}
    )
    project_id = created.json()["id"]

    # The project is `pending`, so a run is already in flight.
    response = await authed_client.post(f"/projects/{project_id}/reindex")
    assert response.status_code == 202
    assert response.json()["enqueued"] is False
    assert response.json()["project"]["id"] == project_id


async def test_delete_returns_204(authed_client: AsyncClient) -> None:
    created = await authed_client.post(
        "/projects", json={"repoUrl": "https://github.com/acme/repo.git"}
    )
    project_id = created.json()["id"]

    assert (await authed_client.delete(f"/projects/{project_id}")).status_code == 204
    assert (await authed_client.get(f"/projects/{project_id}")).status_code == 404


async def test_unauthenticated_requests_are_rejected(client: AsyncClient) -> None:
    assert (await client.get("/projects")).status_code == 401

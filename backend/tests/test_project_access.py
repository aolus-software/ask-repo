"""Spec §5's status table, row by row.

The distinction this file protects: a non-member must not be able to tell a project
that exists from one that does not, while a member whose role is too low must not be
told a project they can see does not exist.
"""

import uuid
from typing import Any

import httpx


async def _create_project(client: httpx.AsyncClient) -> str:
    response = await client.post(
        "/projects", json={"repoUrl": "https://github.com/o/r.git", "branch": "main"}
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_the_creator_gets_an_owner_membership(client_for_user_a: Any) -> None:
    project_id = await _create_project(client_for_user_a)

    response = await client_for_user_a.get(f"/projects/{project_id}")

    assert response.status_code == 200
    assert response.json()["role"] == "owner"


async def test_a_non_member_cannot_read_the_project(
    client_for_user_a: Any, client_for_user_b: Any
) -> None:
    project_id = await _create_project(client_for_user_a)

    response = await client_for_user_b.get(f"/projects/{project_id}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "PROJECT_NOT_FOUND"


async def test_a_non_member_cannot_tell_it_apart_from_a_missing_project(
    client_for_user_a: Any, client_for_user_b: Any
) -> None:
    """The whole point of `404`. Identical status and identical code."""
    project_id = await _create_project(client_for_user_a)

    existing = await client_for_user_b.get(f"/projects/{project_id}")
    missing = await client_for_user_b.get(f"/projects/{uuid.uuid4()}")

    assert existing.status_code == missing.status_code == 404
    assert existing.json()["detail"]["code"] == missing.json()["detail"]["code"]


async def test_a_non_member_deleting_gets_404_not_403(
    client_for_user_a: Any, client_for_user_b: Any
) -> None:
    """A 403 here would confirm the project exists."""
    project_id = await _create_project(client_for_user_a)

    response = await client_for_user_b.delete(f"/projects/{project_id}")

    assert response.status_code == 404


async def test_a_non_member_sees_no_rows_in_the_list(
    client_for_user_a: Any, client_for_user_b: Any
) -> None:
    await _create_project(client_for_user_a)

    response = await client_for_user_b.get("/projects")

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["totalCount"] == 0


async def test_a_viewer_can_read_but_not_delete(
    client_for_user_a: Any, client_for_user_b: Any, grant_membership: Any
) -> None:
    """The one case that stays `403`: they can see it in their own list, so `404`
    would contradict what the UI just rendered.

    `client_for_user_b`'s own user id comes from `GET /auth/me` — the fixtures yield a
    client, not the row, and the grant has to name the user the client authenticates
    as, not some other account.
    """
    project_id = await _create_project(client_for_user_a)
    viewer_id = (await client_for_user_b.get("/auth/me")).json()["id"]
    await grant_membership(uuid.UUID(viewer_id), uuid.UUID(project_id), role="viewer")

    read = await client_for_user_b.get(f"/projects/{project_id}")
    deleted = await client_for_user_b.delete(f"/projects/{project_id}")

    assert read.status_code == 200
    assert deleted.status_code == 403
    assert deleted.json()["detail"]["code"] == "INSUFFICIENT_ROLE"


async def test_an_admin_reads_and_deletes_any_project(
    client_for_user_a: Any, client_for_admin: Any
) -> None:
    project_id = await _create_project(client_for_user_a)

    assert (await client_for_admin.get(f"/projects/{project_id}")).status_code == 200
    assert (await client_for_admin.delete(f"/projects/{project_id}")).status_code == 204


async def test_the_response_carries_the_callers_permissions(client_for_user_a: Any) -> None:
    project_id = await _create_project(client_for_user_a)

    body = (await client_for_user_a.get(f"/projects/{project_id}")).json()

    assert "project.delete" in body["permissions"]
    assert "question.ask" in body["permissions"]

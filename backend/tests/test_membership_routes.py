"""Grant, change and revoke. The last-owner guard is the interesting one."""

from httpx import AsyncClient

from app.models.user import User


async def _create_project(client: AsyncClient) -> str:
    response = await client.post(
        "/projects", json={"repoUrl": "https://github.com/o/r.git", "branch": "main"}
    )
    return str(response.json()["id"])


async def test_the_creator_is_listed_as_the_only_member(client_for_user_a: AsyncClient) -> None:
    project_id = await _create_project(client_for_user_a)

    body = (await client_for_user_a.get(f"/projects/{project_id}/members")).json()

    assert len(body) == 1
    assert body[0]["role"] == "owner"


async def test_granting_lets_the_other_user_read_the_project(
    client_for_user_a: AsyncClient, client_for_user_b: AsyncClient, authed_user: User
) -> None:
    project_id = await _create_project(client_for_user_a)

    granted = await client_for_user_a.post(
        f"/projects/{project_id}/members",
        json={"userId": str(authed_user.id), "role": "viewer"},
    )

    assert granted.status_code == 201
    assert granted.json()["role"] == "viewer"


async def test_a_non_member_cannot_list_members(
    client_for_user_a: AsyncClient, client_for_user_b: AsyncClient
) -> None:
    """`404`, not `403` — the members list must not confirm the project exists."""
    project_id = await _create_project(client_for_user_a)

    response = await client_for_user_b.get(f"/projects/{project_id}/members")

    assert response.status_code == 404


async def test_granting_twice_is_a_conflict(
    client_for_user_a: AsyncClient, authed_user: User
) -> None:
    project_id = await _create_project(client_for_user_a)
    payload = {"userId": str(authed_user.id), "role": "viewer"}
    await client_for_user_a.post(f"/projects/{project_id}/members", json=payload)

    again = await client_for_user_a.post(f"/projects/{project_id}/members", json=payload)

    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "MEMBERSHIP_EXISTS"


async def test_revoking_the_last_owner_is_refused(client_for_user_a: AsyncClient) -> None:
    """The invariant: every live project has at least one live owner."""
    project_id = await _create_project(client_for_user_a)
    members = (await client_for_user_a.get(f"/projects/{project_id}/members")).json()
    owner_id = members[0]["userId"]

    response = await client_for_user_a.delete(f"/projects/{project_id}/members/{owner_id}")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "LAST_OWNER"


async def test_revoking_an_owner_is_allowed_when_another_remains(
    client_for_user_a: AsyncClient, authed_user: User
) -> None:
    project_id = await _create_project(client_for_user_a)
    await client_for_user_a.post(
        f"/projects/{project_id}/members",
        json={"userId": str(authed_user.id), "role": "owner"},
    )
    members = (await client_for_user_a.get(f"/projects/{project_id}/members")).json()
    first_owner = members[0]["userId"]

    response = await client_for_user_a.delete(f"/projects/{project_id}/members/{first_owner}")

    assert response.status_code == 204


async def test_demoting_the_last_owner_is_refused(client_for_user_a: AsyncClient) -> None:
    """Changing a role away from owner strands the project exactly as revoking does."""
    project_id = await _create_project(client_for_user_a)
    members = (await client_for_user_a.get(f"/projects/{project_id}/members")).json()
    owner_id = members[0]["userId"]

    response = await client_for_user_a.patch(
        f"/projects/{project_id}/members/{owner_id}", json={"role": "viewer"}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "LAST_OWNER"


async def test_an_unknown_role_is_rejected(
    client_for_user_a: AsyncClient, authed_user: User
) -> None:
    project_id = await _create_project(client_for_user_a)

    response = await client_for_user_a.post(
        f"/projects/{project_id}/members",
        json={"userId": str(authed_user.id), "role": "wizard"},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "ROLE_NOT_FOUND"

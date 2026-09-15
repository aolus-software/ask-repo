"""Role management. System-role immutability is the property that matters."""

from httpx import AsyncClient

from app.models.user import User


async def test_the_catalogue_lists_every_permission_once(client_for_admin: AsyncClient) -> None:
    body = (await client_for_admin.get("/permissions")).json()

    flat = [p for group in body["groups"] for p in group["permissions"]]
    assert len(flat) == len(set(flat))
    assert "project.delete" in flat


async def test_the_three_system_roles_are_listed_first(client_for_admin: AsyncClient) -> None:
    body = (await client_for_admin.get("/roles")).json()

    assert [row["name"] for row in body[:3]] == ["editor", "owner", "viewer"]
    assert all(row["isSystem"] for row in body[:3])


async def test_a_non_admin_cannot_list_roles(authed_client: AsyncClient) -> None:
    response = await authed_client.get("/roles")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ADMIN_REQUIRED"


async def test_a_system_role_cannot_be_edited(client_for_admin: AsyncClient) -> None:
    """Unchecking `membership.grant` on owner would leave nobody able to grant
    membership on any project, including to undo it."""
    roles = (await client_for_admin.get("/roles")).json()
    owner = next(row for row in roles if row["name"] == "owner")

    response = await client_for_admin.patch(
        f"/roles/{owner['id']}", json={"permissions": ["project.read"]}
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "SYSTEM_ROLE_IMMUTABLE"


async def test_a_system_role_cannot_be_deleted(client_for_admin: AsyncClient) -> None:
    roles = (await client_for_admin.get("/roles")).json()
    viewer = next(row for row in roles if row["name"] == "viewer")

    response = await client_for_admin.delete(f"/roles/{viewer['id']}")

    assert response.status_code == 403


async def test_a_custom_role_can_be_created_and_permissioned(client_for_admin: AsyncClient) -> None:
    created = await client_for_admin.post(
        "/roles", json={"name": "QA Lead", "description": "Runs the test plan."}
    )
    assert created.status_code == 201
    role_id = created.json()["id"]

    updated = await client_for_admin.patch(
        f"/roles/{role_id}",
        json={"permissions": ["project.read", "question.ask", "result.record"]},
    )

    assert updated.status_code == 200
    assert sorted(updated.json()["permissions"]) == [
        "project.read",
        "question.ask",
        "result.record",
    ]


async def test_an_unknown_permission_is_rejected(client_for_admin: AsyncClient) -> None:
    created = await client_for_admin.post("/roles", json={"name": "Bad"})
    role_id = created.json()["id"]

    response = await client_for_admin.patch(
        f"/roles/{role_id}", json={"permissions": ["project.explode"]}
    )

    assert response.status_code == 422


async def test_a_duplicate_role_name_is_a_conflict(client_for_admin: AsyncClient) -> None:
    await client_for_admin.post("/roles", json={"name": "QA Lead"})

    again = await client_for_admin.post("/roles", json={"name": "QA Lead"})

    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "ROLE_NAME_EXISTS"


async def test_a_role_in_use_cannot_be_deleted(
    client_for_admin: AsyncClient, client_for_user_a: AsyncClient, authed_user: User
) -> None:
    """Silently revoking a dozen people's access as a side effect of tidying a role
    list is not something an admin should be able to do without seeing it first."""
    created = await client_for_admin.post("/roles", json={"name": "QA Lead"})
    role_id = created.json()["id"]
    project = await client_for_user_a.post(
        "/projects", json={"repoUrl": "https://github.com/o/r.git", "branch": "main"}
    )
    project_id = project.json()["id"]
    await client_for_user_a.post(
        f"/projects/{project_id}/members",
        json={"userId": str(authed_user.id), "role": "QA Lead"},
    )

    response = await client_for_admin.delete(f"/roles/{role_id}")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ROLE_IN_USE"

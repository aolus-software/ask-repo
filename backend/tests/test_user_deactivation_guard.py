"""Offboarding cannot strand a project.

`docs/PRD.md` §8 asked what happens to a departed user's projects. This is the answer:
deactivation is blocked until a human names the successor, because the alternatives
either auto-grant an arbitrary admin (writing a grant nobody made) or leave a project
whose only owner cannot log in.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.membership import ProjectMembership
from app.models.user import User


async def _create_project(client: AsyncClient) -> str:
    response = await client.post(
        "/projects", json={"repoUrl": "https://github.com/o/r.git", "branch": "main"}
    )
    return str(response.json()["id"])


async def test_deactivating_a_sole_owner_is_refused(
    client_for_admin: AsyncClient, authed_client: AsyncClient, authed_user: User
) -> None:
    await _create_project(authed_client)

    response = await client_for_admin.delete(f"/users/{authed_user.id}")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "LAST_OWNER"


async def test_the_refusal_names_the_blocking_projects(
    client_for_admin: AsyncClient, authed_client: AsyncClient, authed_user: User
) -> None:
    """ "No" is not actionable; "no, because these projects would have no owner" is."""
    project_id = await _create_project(authed_client)

    detail = (await client_for_admin.delete(f"/users/{authed_user.id}")).json()["detail"]

    assert [entry["id"] for entry in detail["projects"]] == [project_id]


async def test_deactivating_a_co_owner_is_allowed(
    client_for_admin: AsyncClient,
    client_for_user_a: AsyncClient,
    authed_user: User,
    grant_membership: Any,
) -> None:
    """`client_for_user_a`'s user already owns the project (they created it), so
    granting `authed_user` owner too makes them a co-owner. Deactivating a co-owner
    strands nothing, so it must succeed."""
    project_id = await _create_project(client_for_user_a)
    await grant_membership(authed_user.id, uuid.UUID(project_id), role="owner")
    members = (await client_for_user_a.get(f"/projects/{project_id}/members")).json()
    assert len(members) == 2

    response = await client_for_admin.delete(f"/users/{authed_user.id}")

    assert response.status_code == 204


async def test_deactivating_a_user_with_no_owned_projects_succeeds(
    client_for_admin: AsyncClient, authed_user: User
) -> None:
    response = await client_for_admin.delete(f"/users/{authed_user.id}")

    assert response.status_code == 204


async def test_a_deactivated_users_memberships_are_left_intact(
    client_for_admin: AsyncClient,
    client_for_user_a: AsyncClient,
    authed_user: User,
    grant_membership: Any,
    db_session: AsyncSession,
) -> None:
    """Reactivating an account must restore exactly the access it had, so
    deactivation does not soft-delete memberships. `count_live_owners` reads through
    to the user row instead."""
    project_id = await _create_project(client_for_user_a)
    await grant_membership(authed_user.id, uuid.UUID(project_id), role="viewer")

    assert (await client_for_admin.delete(f"/users/{authed_user.id}")).status_code == 204

    # Verify the membership row still exists and is not soft-deleted
    membership = (
        await db_session.execute(
            select(ProjectMembership).where(
                ProjectMembership.project_id == uuid.UUID(project_id),
                ProjectMembership.user_id == authed_user.id,
            )
        )
    ).scalar_one_or_none()
    assert membership is not None
    assert membership.deleted_at is None


async def test_ownerless_lists_projects_whose_only_owner_is_deactivated(
    client_for_admin: AsyncClient,
    client_for_user_a: AsyncClient,
    authed_user: User,
    grant_membership: Any,
    db_session: AsyncSession,
) -> None:
    """The migration cannot block a deactivation that already happened, so it leaves
    those projects visible instead of pretending they are fine."""
    project_id = await _create_project(client_for_user_a)
    await grant_membership(authed_user.id, uuid.UUID(project_id), role="owner")

    # Deactivate every owner directly, as a pre-Phase-2.1 deactivation would have.
    owners = (
        (
            await db_session.execute(
                select(ProjectMembership).where(
                    ProjectMembership.project_id == uuid.UUID(project_id)
                )
            )
        )
        .scalars()
        .all()
    )
    for membership in owners:
        user = await db_session.get(User, membership.user_id)
        assert user is not None
        user.deleted_at = datetime.now(UTC)
    await db_session.commit()

    body = (await client_for_admin.get("/projects?ownerless=true")).json()

    assert project_id in [row["id"] for row in body["items"]]


async def test_ownerless_still_finds_a_project_that_kept_a_live_viewer(
    client_for_admin: AsyncClient,
    client_for_user_a: AsyncClient,
    user_b: User,
    grant_membership: Any,
    db_session: AsyncSession,
) -> None:
    """A live member who is not an owner is not evidence of an owner.

    The owner-role and live-user conditions have to hold on the same membership row.
    Counted separately, this viewer makes the project look owned and it drops out of
    the cleanup list — the one case the list exists to surface.
    """
    project_id = await _create_project(client_for_user_a)
    await grant_membership(user_b.id, uuid.UUID(project_id), role="viewer")

    for membership in (
        (
            await db_session.execute(
                select(ProjectMembership).where(
                    ProjectMembership.project_id == uuid.UUID(project_id),
                    ProjectMembership.user_id != user_b.id,
                )
            )
        )
        .scalars()
        .all()
    ):
        owner = await db_session.get(User, membership.user_id)
        assert owner is not None
        owner.deleted_at = datetime.now(UTC)
    await db_session.commit()

    body = (await client_for_admin.get("/projects?ownerless=true")).json()

    assert project_id in [row["id"] for row in body["items"]]


async def test_ownerless_is_admin_only(authed_client: AsyncClient) -> None:
    response = await authed_client.get("/projects?ownerless=true")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ADMIN_REQUIRED"


async def test_ownerless_defaults_to_false(
    client_for_admin: AsyncClient, client_for_user_a: AsyncClient
) -> None:
    """A healthy project must not appear in the cleanup list."""
    project_id = await _create_project(client_for_user_a)

    body = (await client_for_admin.get("/projects?ownerless=true")).json()

    assert project_id not in [row["id"] for row in body["items"]]

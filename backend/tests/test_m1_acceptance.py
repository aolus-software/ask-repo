"""docs/PRD.md §7's M1 success criteria, asserted over HTTP.

These must never be quietly deleted: they encode the access model and the destructive
gate, both of which look like bugs to someone who has not read §4.1.

**Phase 2.1 inverted the first of them.** M1 shipped with every project shared with
every user on the instance, and `test_sharing_works_as_intended` asserted exactly
that. Per-project RBAC removed it deliberately: a user with no membership can no
longer list, read or query a project. The test below is that criterion rewritten, not
dropped -- the sentence it defends changed, so the assertion changed with it.
"""

import pathlib
import re

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import VIEWER_NAME
from app.models.user import User
from tests.conftest import GrantMembership
from tests.factories import create_project


async def test_a_project_is_invisible_to_a_non_member(
    client_for_user_b: AsyncClient, db_session: AsyncSession
) -> None:
    """User B can neither list nor read a project they hold no role on, and the read
    is `404` rather than `403`.

    A `403` would confirm that a project with that id exists, and the inventory of
    repositories an organization has indexed is exactly what per-project access
    control is for.
    """
    project = await create_project(db_session)
    await db_session.commit()

    listed = await client_for_user_b.get("/projects")
    assert str(project.id) not in [item["id"] for item in listed.json()["items"]]

    read = await client_for_user_b.get(f"/projects/{project.id}")
    assert read.status_code == 404
    assert read.json()["detail"]["code"] == "PROJECT_NOT_FOUND"


async def test_a_member_can_list_and_read_the_project_they_were_granted(
    client_for_user_b: AsyncClient,
    user_b: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
) -> None:
    """The other half: access is a grant, and the lowest role there is carries it.

    `created_by` plays no part -- user B did not add this project and never will."""
    project = await create_project(db_session)
    await db_session.commit()
    await grant_membership(user_b.id, project.id, VIEWER_NAME)

    listed = await client_for_user_b.get("/projects")
    assert str(project.id) in [item["id"] for item in listed.json()["items"]]

    assert (await client_for_user_b.get(f"/projects/{project.id}")).status_code == 200


async def test_destructive_gating_holds(
    client_for_user_b: AsyncClient,
    user_b: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
) -> None:
    """The two refusals, and why they differ.

    A **non-member** gets `404` on delete and reindex: they must not learn the project
    exists. A **member** whose role does not carry `project.delete` gets `403`: the
    project is in the list they just rendered, so `404` would contradict it.
    """
    hidden = await create_project(db_session)
    visible = await create_project(db_session)
    await db_session.commit()
    await grant_membership(user_b.id, visible.id, VIEWER_NAME)

    assert (await client_for_user_b.delete(f"/projects/{hidden.id}")).status_code == 404
    assert (await client_for_user_b.post(f"/projects/{hidden.id}/reindex")).status_code == 404

    delete_response = await client_for_user_b.delete(f"/projects/{visible.id}")
    assert delete_response.status_code == 403
    assert delete_response.json()["detail"]["code"] == "INSUFFICIENT_ROLE"

    assert (await client_for_user_b.post(f"/projects/{visible.id}/reindex")).status_code == 403


async def test_an_admin_overrides_the_gate(
    client_for_user_a: AsyncClient, client_for_admin: AsyncClient
) -> None:
    created = await client_for_user_a.post(
        "/projects", json={"repoUrl": "https://github.com/acme/admin.git"}
    )
    project_id = created.json()["id"]

    assert (await client_for_admin.delete(f"/projects/{project_id}")).status_code == 204


def test_read_scoping_lives_in_exactly_one_function() -> None:
    """docs/PRD.md §7's phase-2 readiness criterion, 'confirmed by grep'.

    Only two things may compare `created_by` to a **caller**: the access resolver,
    and a service's destructive gate. Anything else is read scoping in the wrong
    place, which is what phase 2 would have to hunt down.
    """
    app_root = pathlib.Path(__file__).resolve().parent.parent / "app"
    allowed = {
        "core/access.py",
        "services/project.py",  # destructive gate
    }
    offenders: list[str] = []

    for path in sorted(app_root.rglob("*.py")):
        relative = path.relative_to(app_root).as_posix()
        if relative in allowed:
            continue
        if re.search(r"created_by\s*==", path.read_text()):
            offenders.append(relative)

    assert offenders == [], f"read scoping outside the resolver: {offenders}"

"""docs/PRD.md §7's M1 success criteria, asserted over HTTP.

These must never be quietly deleted: they encode the phase-1 sharing model and the
destructive gate, both of which look like bugs to someone who has not read §4.1.
"""

import pathlib
import re

from httpx import AsyncClient


async def test_sharing_works_as_intended(
    client_for_user_a: AsyncClient, client_for_user_b: AsyncClient
) -> None:
    """User B can list and read a project user A created, with no grant step."""
    created = await client_for_user_a.post(
        "/projects", json={"repoUrl": "https://github.com/acme/shared.git"}
    )
    project_id = created.json()["id"]

    listed = await client_for_user_b.get("/projects")
    assert project_id in [item["id"] for item in listed.json()["items"]]

    assert (await client_for_user_b.get(f"/projects/{project_id}")).status_code == 200


async def test_destructive_gating_holds(
    client_for_user_a: AsyncClient, client_for_user_b: AsyncClient
) -> None:
    """User B gets 403 on someone else's project — not 404, and not success."""
    created = await client_for_user_a.post(
        "/projects", json={"repoUrl": "https://github.com/acme/gated.git"}
    )
    project_id = created.json()["id"]

    delete_response = await client_for_user_b.delete(f"/projects/{project_id}")
    assert delete_response.status_code == 403
    assert delete_response.json()["detail"]["code"] == "NOT_PROJECT_OWNER"

    assert (await client_for_user_b.post(f"/projects/{project_id}/reindex")).status_code == 403


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

    `repositories/qa_pair.py` is the one entry that is not a caller comparison. It
    matches `created_by` against a **query parameter** — `?createdBy=` — which
    `docs/PRD.md` §4.3 specifies as a list filter alongside project, tag, source and
    status. It runs after `resolve_project_scope` has already scoped the statement,
    so it narrows within the scope rather than standing in for it. The regex cannot
    tell the two apart; this docstring is where the difference is recorded.
    """
    app_root = pathlib.Path(__file__).resolve().parent.parent / "app"
    allowed = {
        "core/access.py",
        "services/project.py",  # destructive gate
        "services/qa_pair.py",  # destructive gate
        "repositories/qa_pair.py",  # `?createdBy=` list filter, applied inside the scope
    }
    offenders: list[str] = []

    for path in sorted(app_root.rglob("*.py")):
        relative = path.relative_to(app_root).as_posix()
        if relative in allowed:
            continue
        if re.search(r"created_by\s*==", path.read_text()):
            offenders.append(relative)

    assert offenders == [], f"read scoping outside the resolver: {offenders}"

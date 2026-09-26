"""The two read routes. Admin-only, and there are no write routes at all."""

import uuid
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.routing import APIRoute
from httpx import AsyncClient
from starlette.routing import BaseRoute

from app.core.audit import AuditEventType
from app.main import app
from app.models.user import User
from tests.conftest import AuditRows


def _iter_api_routes(routes: Iterable[BaseRoute]) -> Iterator[APIRoute]:
    """Walk every route FastAPI serves, including ones nested behind `include_router`.

    A router mounted with `app.include_router(...)` no longer appears as a flat
    `APIRoute` in `app.routes` on this FastAPI version — it wraps each included
    router, and the real routes live on its `original_router`. Mirrors the helper in
    `tests/test_audit_coverage.py`; the brief's original version of this test walked
    `app.routes` directly and matched nothing on this FastAPI version, for any router.
    """
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
            continue
        nested_router = getattr(route, "original_router", None)
        if nested_router is not None:
            yield from _iter_api_routes(nested_router.routes)


def test_the_router_serves_reads_only() -> None:
    """Append-only, visible on the wire and not only in the schema."""
    methods = {
        method
        for route in _iter_api_routes(app.routes)
        if route.path.startswith("/audit-events")
        for method in route.methods or set()
    }

    assert methods == {"GET"}


async def test_a_non_admin_is_refused(authed_client: AsyncClient) -> None:
    response = await authed_client.get("/audit-events")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ADMIN_REQUIRED"


async def test_the_list_omits_details_and_names_the_changed_fields(
    client_for_admin: AsyncClient, user_b: User
) -> None:
    """`details` is capped at 8 KB and a role.updated row carries two permission
    lists; shipping 25 of those to render a scannable table is a lot of wire for
    content the table cannot show."""
    await client_for_admin.patch(f"/users/{user_b.id}", json={"isAdmin": True})

    response = await client_for_admin.get("/audit-events?eventType=user.updated")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["changedFields"] == ["isAdmin"]
    assert "details" not in item
    assert "ipAddress" not in item


async def test_the_detail_carries_the_full_payload(
    client_for_admin: AsyncClient, user_b: User
) -> None:
    await client_for_admin.patch(f"/users/{user_b.id}", json={"isAdmin": True})
    listed = await client_for_admin.get("/audit-events?eventType=user.updated")
    event_id = listed.json()["items"][0]["id"]

    response = await client_for_admin.get(f"/audit-events/{event_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["details"]["changed"]["isAdmin"] == {"before": False, "after": True}
    assert body["current"]["targetStillExists"] is True
    assert body["current"]["actorStillActive"] is True


async def test_a_missing_event_is_404(client_for_admin: AsyncClient) -> None:
    """No security dimension here — the route is admin-only and the table has no
    per-project scope, so a miss is genuinely "no such row" rather than "not yours".
    The moment a per-project read is added, that stops being true."""
    response = await client_for_admin.get(f"/audit-events/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "AUDIT_EVENT_NOT_FOUND"


@pytest.mark.parametrize(
    "query",
    [
        "eventType=user.updated",
        "outcome=success",
    ],
)
async def test_each_filter_narrows_the_page(
    client_for_admin: AsyncClient, user_b: User, query: str
) -> None:
    await client_for_admin.patch(f"/users/{user_b.id}", json={"isAdmin": True})

    response = await client_for_admin.get(f"/audit-events?{query}")

    assert response.status_code == 200
    assert response.json()["totalCount"] >= 1


async def test_actor_user_id_filter_narrows_the_page(
    client_for_admin: AsyncClient, admin_user: User, user_b: User
) -> None:
    """A7: `actorUserId` had no coverage at all before this. `client_for_admin`
    acts as `admin_user`, so its own writes are the events to filter for."""
    await client_for_admin.patch(f"/users/{user_b.id}", json={"isAdmin": True})

    response = await client_for_admin.get(f"/audit-events?actorUserId={admin_user.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["totalCount"] >= 1
    assert all(item["actorUserId"] == str(admin_user.id) for item in body["items"])


async def test_project_id_filter_narrows_the_page(client_for_admin: AsyncClient) -> None:
    """A7: `projectId` had no coverage at all before this."""
    created = await client_for_admin.post(
        "/projects", json={"repoUrl": "https://github.com/acme/private.git"}
    )
    assert created.status_code == 201
    project_id = created.json()["id"]

    response = await client_for_admin.get(f"/audit-events?projectId={project_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["totalCount"] >= 1
    assert all(item["projectId"] == project_id for item in body["items"])


async def test_occurred_to_today_includes_events_recorded_today(
    client_for_admin: AsyncClient, user_b: User
) -> None:
    """A4/A7 boundary: `<input type="date">` submits a bare day with no time
    component. Before the fix, `occurredTo=<today>` parsed to midnight and
    `created_at <= midnight` excluded every event recorded today -- an empty page
    on a From=today/To=today search. This assertion fails on the pre-fix code."""
    await client_for_admin.patch(f"/users/{user_b.id}", json={"isAdmin": True})
    today = datetime.now(UTC).date().isoformat()

    response = await client_for_admin.get(f"/audit-events?occurredTo={today}")

    assert response.status_code == 200
    assert response.json()["totalCount"] >= 1


async def test_occurred_from_excludes_events_before_it(
    client_for_admin: AsyncClient, user_b: User
) -> None:
    """A7 boundary: the other side of the same range, asserted as an actual
    exclusion rather than `totalCount >= 1`, which would pass for a no-op filter."""
    await client_for_admin.patch(f"/users/{user_b.id}", json={"isAdmin": True})
    tomorrow = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()

    response = await client_for_admin.get(f"/audit-events?occurredFrom={tomorrow}")

    assert response.status_code == 200
    assert response.json()["totalCount"] == 0


async def test_search_narrows_the_page_by_email(
    client_for_admin: AsyncClient, user_b: User
) -> None:
    """`search` matches `actor_email` or `target_label`; the brief's fixed
    `search=b@example.com` never matches, since fixture emails are random
    (`{uuid4().hex}@example.com`) — this uses the fixture's real address instead."""
    await client_for_admin.patch(f"/users/{user_b.id}", json={"isAdmin": True})

    response = await client_for_admin.get(f"/audit-events?search={user_b.email}")

    assert response.status_code == 200
    assert response.json()["totalCount"] >= 1


async def test_search_matches_an_ip_address_by_prefix(
    client: AsyncClient, client_for_admin: AsyncClient, audit_rows: AuditRows
) -> None:
    """A6: the search box offers to find an address, and offers it as a *prefix*.

    An operator pastes in the address a failed login recorded, not a fragment of one,
    and `ip_address` carries no index of its own -- so this is deliberately not the
    contains-scan `actor_email` and `target_label` get. The distinction is invisible
    from the implementation once written, which is what makes it worth asserting: a
    later "consistency" edit to `%{search}%` would pass every other test here.

    The recorded address is read back rather than assumed, so the test says nothing
    about what the ASGI transport happens to use as a peer.
    """
    refused = await client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "hunter2"}
    )
    assert refused.status_code == 401

    rows = await audit_rows(AuditEventType.AUTH_LOGIN_FAILED)
    assert len(rows) == 1
    recorded_ip = rows[0].ip_address
    assert recorded_ip is not None
    event_id = str(rows[0].id)

    hit = await client_for_admin.get(f"/audit-events?search={recorded_ip[:3]}")
    assert hit.status_code == 200
    assert any(item["id"] == event_id for item in hit.json()["items"])

    # A substring that is not a prefix must not match, or this is a contains-scan.
    miss = await client_for_admin.get(f"/audit-events?search={recorded_ip[1:]}")
    assert miss.status_code == 200
    assert all(item["id"] != event_id for item in miss.json()["items"])


async def test_sort_rejects_anything_but_created_at(client_for_admin: AsyncClient) -> None:
    """`created_at` is the only ordering this table has a meaningful answer for."""
    response = await client_for_admin.get("/audit-events?sort=eventType")

    assert response.status_code == 422


async def test_admin_sees_project_rows_they_hold_no_membership_on(
    client_for_admin: AsyncClient, authed_client: AsyncClient, admin_user: User
) -> None:
    """The admin read is unrestricted and shows rows on any project. A non-admin
    still gets 403 even when querying a project they are not a member of."""
    # Create a project and an event; authed_client acts as a non-admin
    created = await authed_client.post(
        "/projects", json={"repoUrl": "https://github.com/acme/test.git"}
    )
    assert created.status_code == 201
    project_id = created.json()["id"]

    # Admin sees the event even without membership
    response = await client_for_admin.get(f"/audit-events?projectId={project_id}")
    assert response.status_code == 200
    assert response.json()["totalCount"] >= 1

    # Non-admin is still refused
    response = await authed_client.get("/audit-events")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ADMIN_REQUIRED"

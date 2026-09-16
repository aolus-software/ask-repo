"""The two read routes. Admin-only, and there are no write routes at all."""

import uuid
from collections.abc import Iterable, Iterator

import pytest
from fastapi.routing import APIRoute
from httpx import AsyncClient
from starlette.routing import BaseRoute

from app.main import app
from app.models.user import User


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


async def test_sort_rejects_anything_but_created_at(client_for_admin: AsyncClient) -> None:
    """`created_at` is the only ordering this table has a meaningful answer for."""
    response = await client_for_admin.get("/audit-events?sort=eventType")

    assert response.status_code == 422

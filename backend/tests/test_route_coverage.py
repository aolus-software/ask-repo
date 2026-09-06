"""The route-coverage walk (spec §12 case 17).

This does not enforce the forced-password-change gate — `AuthContextMiddleware`
(`app/core/middleware.py`) does that regardless of what a route depends on, and no
test here can substitute for it. What this pins down instead: the list of
gate-exempt prefixes still matches what is actually mounted. Without it, a route
group added later under a brand-new prefix — with no `CurrentUser`/`AdminUser`
dependency and never added to `GATE_EXEMPT_PREFIXES` — would sail through with no
identity check and no gate coverage either, and nothing would say so until someone
noticed in production.

`fastapi.routing.iter_route_contexts` is the same flattening helper
`FastAPI.openapi()` itself calls to build `/openapi.json` — this FastAPI version
(0.141) resolves included routers lazily, so `app.routes` alone yields
`_IncludedRouter` wrappers rather than concrete `APIRoute` objects. Using the same
helper the app already relies on to serve its schema keeps this test tied to
public-ish, actively-exercised behaviour rather than a private code path nobody
else touches.
"""

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, routing
from fastapi.routing import APIRoute

from app.api.deps import get_current_user, require_admin
from app.core.middleware import GATE_EXEMPT_PREFIXES, _is_gate_exempt


def _dependency_calls(dependant: Any) -> set[Callable[..., Any]]:
    """Every callable in a route's dependency tree, including nested dependencies.

    `require_admin` itself depends on `get_current_user`, so a route declaring only
    `AdminUser` still shows both in its tree — which is correct, both mean "identity
    is required".
    """
    calls: set[Callable[..., Any]] = set()
    if dependant.call is not None:
        calls.add(dependant.call)
    for sub_dependant in dependant.dependencies:
        calls |= _dependency_calls(sub_dependant)
    return calls


def test_every_mounted_route_is_open_by_declaration_or_requires_identity(
    app: FastAPI,
) -> None:
    """Every mounted path is either gate-exempt, or its dependency tree includes
    `get_current_user`/`require_admin`.

    A failure here names the exact path and method, and the fix is a choice, not a
    mechanical patch: either the route is missing `CurrentUser`/`AdminUser`, or the
    prefix genuinely belongs in `GATE_EXEMPT_PREFIXES` (`.claude/rules/router.md` —
    the default answer for a new prefix is no).
    """
    uncovered: list[str] = []
    for route_context in routing.iter_route_contexts(app.routes):
        route = route_context.original_route
        if not isinstance(route, APIRoute):
            # Auto-mounted docs/openapi/redoc routes aren't APIRoute and carry no
            # auth dependency by design — they must render without a token. Their
            # paths are explicitly listed in GATE_EXEMPT_PREFIXES.
            continue
        if _is_gate_exempt(route.path):
            continue
        calls = _dependency_calls(route.dependant)
        if get_current_user not in calls and require_admin not in calls:
            uncovered.append(f"{sorted(route.methods or [])} {route.path}")

    assert not uncovered, (
        "Route(s) mounted with no CurrentUser/AdminUser dependency and not covered "
        f"by GATE_EXEMPT_PREFIXES {GATE_EXEMPT_PREFIXES}: {uncovered}. Either add an "
        "auth dependency to the route, or add its prefix to GATE_EXEMPT_PREFIXES if "
        "it is genuinely meant to be reachable with no identity check."
    )


def _checklist_routes(app: FastAPI) -> list[APIRoute]:
    """Every mounted route belonging to the three checklist routers.

    Excludes `/checklist-modules/{module_id}/mock-data*`: those paths share the
    `/checklist-modules` prefix (the mock-data dataset is reached through its
    module) but are mounted by the three mock-data routers M5 added, not by the
    checklist's own three -- a blanket `/checklist-` prefix match would otherwise
    sweep them into this test's route count.
    """
    return [
        route_context.original_route
        for route_context in routing.iter_route_contexts(app.routes)
        if isinstance(route_context.original_route, APIRoute)
        and route_context.original_route.path.startswith("/checklist-")
        and "mock-data" not in route_context.original_route.path
    ]


def test_the_checklist_surface_is_the_eighteen_routes_the_spec_names(app: FastAPI) -> None:
    """A count, so a route silently dropped during a refactor is a failure here.

    Seventeen was `docs/superpowers/specs/2026-09-01-m4-qa-checklist-design.md` §6's
    table; `POST /checklist-items/clear-results` is the eighteenth. Changing this
    number means changing that table, and `backend/README.md`, in the same commit.
    """
    mounted = {
        (method, route.path)
        for route in _checklist_routes(app)
        for method in sorted(route.methods or [])
    }

    assert mounted == {
        ("GET", "/checklist-modules"),
        ("POST", "/checklist-modules"),
        ("GET", "/checklist-modules/{module_id}"),
        ("PATCH", "/checklist-modules/{module_id}"),
        ("DELETE", "/checklist-modules/{module_id}"),
        ("POST", "/checklist-modules/{module_id}/generate"),
        ("GET", "/checklist-modules/{module_id}/messages"),
        ("POST", "/checklist-modules/{module_id}/messages"),
        ("GET", "/checklist-modules/{module_id}/change-sets"),
        ("GET", "/checklist-items"),
        ("POST", "/checklist-items"),
        ("GET", "/checklist-items/export"),
        ("POST", "/checklist-items/clear-results"),
        ("PATCH", "/checklist-items/{item_id}"),
        ("PUT", "/checklist-items/{item_id}/result"),
        ("DELETE", "/checklist-items/{item_id}"),
        ("POST", "/checklist-change-sets/{change_set_id}/apply"),
        ("POST", "/checklist-change-sets/{change_set_id}/discard"),
    }


def test_every_checklist_route_documents_itself(app: FastAPI) -> None:
    """A summary and its own error list, per `.claude/rules/response-api.md`.

    OpenAPI is the contract the in-repo frontend and every generated client read. A
    route with no `responses` block documents none of the statuses it can return, and
    a route with no summary shows up in `/docs` as its function name.
    """
    undocumented = [
        f"{sorted(route.methods or [])} {route.path}"
        for route in _checklist_routes(app)
        if not route.summary or not route.responses
    ]

    assert not undocumented, (
        f"Checklist route(s) missing a summary or a responses block: {undocumented}. "
        "Trace the statuses from the route's own service method -- do not copy the "
        "block from the route beside it."
    )


def test_the_export_route_is_declared_before_the_item_id_route(app: FastAPI) -> None:
    """FastAPI matches in declaration order, so `/export` must come first.

    Declared after `/{item_id}`, the literal path is swallowed as an id and every
    export request fails with a `422` naming `item_id` -- a failure that looks like a
    client bug and is invisible in the route table.
    """
    paths = [route.path for route in _checklist_routes(app)]

    assert paths.index("/checklist-items/export") < paths.index("/checklist-items/{item_id}")

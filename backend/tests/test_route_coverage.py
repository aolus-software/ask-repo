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

"""The rule, as a test.

`.claude/rules/audit-trail.md` says every write and every export records an audit
event. A list of write sites cannot enforce that — it goes stale the moment someone
adds a route, and the failure is silent: the route works, the tests pass, and the
trail has a hole nobody finds until the day it is needed.

So this module asserts three things no per-event test can:

1. **Every mutating route in the app is classified** — either it maps to an event, or
   it is one of the four exemptions. A new route fails here until someone decides.
2. **Every catalogue name is claimed by a route** (or by the CLI), so a name cannot
   exist unwritten.
3. **Every exemption is one of the four the spec names**, so the escape hatch cannot
   quietly widen.
"""

from collections.abc import Iterable, Iterator

from fastapi.routing import APIRoute
from starlette.routing import BaseRoute

from app.core.audit import AuditEventType
from app.main import app

MUTATING_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})

# Export routes are GETs, and they audit: an export is the one action that takes a
# private repository's derived content out of the instance (`docs/PRD.md` §9).
EXPORT_ROUTES = frozenset(
    {
        ("GET", "/checklist-items/export"),
        ("GET", "/checklist-modules/{module_id}/mock-data/export.json"),
        ("GET", "/checklist-modules/{module_id}/mock-data/export.xlsx"),
    }
)

# The four exemptions from spec §1.3. Each value is the reason, so a reader finds a
# decision rather than what looks like an oversight.
READS = "ordinary read — the trail records what changed"
PROPOSAL = "refinement-chat turn — a proposal is not a row; the apply is audited"
CALL_LOG = "the ask route — PRD §2.5 keeps per-call records out of this table by name"
NO_ACTOR = "ingestion outcome — no actor; projects.status holds the result"

VALID_EXEMPTIONS = frozenset({READS, PROPOSAL, CALL_LOG, NO_ACTOR})

# (method, path) -> the event it records, or the reason it does not.
# Every task from 4 to 11 moves entries from a reason to an AuditEventType.
ROUTE_EVENTS: dict[tuple[str, str], AuditEventType | str] = {
    # --- Task 4: auth ---
    ("POST", "/auth/login"): AuditEventType.AUTH_LOGIN_SUCCEEDED,
    ("POST", "/auth/logout"): AuditEventType.AUTH_LOGOUT,
    ("POST", "/auth/logout-all"): AuditEventType.AUTH_LOGOUT,
    ("POST", "/auth/refresh"): AuditEventType.AUTH_REFRESH_REPLAYED,
    ("POST", "/auth/change-password"): AuditEventType.AUTH_PASSWORD_CHANGED,
    # --- Task 5: users ---
    ("POST", "/users"): AuditEventType.USER_CREATED,
    ("PATCH", "/users/{user_id}"): AuditEventType.USER_UPDATED,
    ("DELETE", "/users/{user_id}"): AuditEventType.USER_DEACTIVATED,
    ("POST", "/users/{user_id}/reset-password"): AuditEventType.USER_PASSWORD_RESET,
    # --- Task 6: projects ---
    ("POST", "/projects"): AuditEventType.PROJECT_CREATED,
    ("POST", "/projects/{project_id}/reindex"): AuditEventType.PROJECT_REINDEX_REQUESTED,
    ("DELETE", "/projects/{project_id}"): AuditEventType.PROJECT_DELETED,
    # --- Task 7: RBAC ---
    ("POST", "/projects/{project_id}/members"): AuditEventType.MEMBERSHIP_GRANTED,
    (
        "PATCH",
        "/projects/{project_id}/members/{user_id}",
    ): AuditEventType.MEMBERSHIP_ROLE_CHANGED,
    ("DELETE", "/projects/{project_id}/members/{user_id}"): AuditEventType.MEMBERSHIP_REVOKED,
    ("POST", "/roles"): AuditEventType.ROLE_CREATED,
    ("PATCH", "/roles/{role_id}"): AuditEventType.ROLE_UPDATED,
    ("DELETE", "/roles/{role_id}"): AuditEventType.ROLE_DELETED,
    # --- Task 8: checklist modules and items ---
    ("POST", "/checklist-modules"): AuditEventType.CHECKLIST_MODULE_CREATED,
    ("PATCH", "/checklist-modules/{module_id}"): AuditEventType.CHECKLIST_MODULE_UPDATED,
    ("DELETE", "/checklist-modules/{module_id}"): AuditEventType.CHECKLIST_MODULE_DELETED,
    (
        "POST",
        "/checklist-modules/{module_id}/generate",
    ): AuditEventType.CHECKLIST_MODULE_GENERATION_REQUESTED,
    ("POST", "/checklist-items"): AuditEventType.CHECKLIST_ITEM_CREATED,
    ("PATCH", "/checklist-items/{item_id}"): AuditEventType.CHECKLIST_ITEM_UPDATED,
    ("PUT", "/checklist-items/{item_id}/result"): AuditEventType.CHECKLIST_ITEM_RESULT_RECORDED,
    ("DELETE", "/checklist-items/{item_id}"): AuditEventType.CHECKLIST_ITEM_DELETED,
    ("POST", "/checklist-items/clear-results"): AuditEventType.CHECKLIST_ITEM_RESULTS_CLEARED,
    # --- Task 9: checklist change sets and export ---
    (
        "POST",
        "/checklist-change-sets/{change_set_id}/apply",
    ): AuditEventType.CHECKLIST_CHANGE_SET_APPLIED,
    (
        "POST",
        "/checklist-change-sets/{change_set_id}/discard",
    ): AuditEventType.CHECKLIST_CHANGE_SET_DISCARDED,
    ("GET", "/checklist-items/export"): AuditEventType.CHECKLIST_EXPORTED,
    # --- Task 10: mock data ---
    (
        "POST",
        "/checklist-modules/{module_id}/mock-data-generations",
    ): AuditEventType.MOCK_DATA_GENERATION_REQUESTED,
    (
        "POST",
        "/mock-data-change-sets/{change_set_id}/apply",
    ): AuditEventType.MOCK_DATA_CHANGE_SET_APPLIED,
    (
        "POST",
        "/mock-data-change-sets/{change_set_id}/discard",
    ): AuditEventType.MOCK_DATA_CHANGE_SET_DISCARDED,
    ("DELETE", "/mock-data-records/{record_id}"): AuditEventType.MOCK_DATA_RECORD_DELETED,
    (
        "GET",
        "/checklist-modules/{module_id}/mock-data/export.json",
    ): AuditEventType.MOCK_DATA_EXPORTED,
    (
        "GET",
        "/checklist-modules/{module_id}/mock-data/export.xlsx",
    ): AuditEventType.MOCK_DATA_EXPORTED,
    # --- Task 11: conversations, metadata only ---
    ("POST", "/conversations"): AuditEventType.CONVERSATION_CREATED,
    ("DELETE", "/conversations/{conversation_id}"): AuditEventType.CONVERSATION_DELETED,
    # --- exempt ---
    ("POST", "/conversations/{conversation_id}/messages"): CALL_LOG,
    ("POST", "/checklist-modules/{module_id}/messages"): PROPOSAL,
    ("POST", "/checklist-modules/{module_id}/mock-data-messages"): PROPOSAL,
}


def _iter_api_routes(routes: Iterable[BaseRoute]) -> Iterator[APIRoute]:
    """Walk every route FastAPI serves, including ones nested behind `include_router`.

    A router mounted with `app.include_router(...)` no longer appears as a flat
    `APIRoute` in `app.routes` on this FastAPI version — it wraps each included
    router, and the real routes live on its `original_router`. Recursing through
    that attribute rather than importing the wrapper type keeps this from depending
    on a name FastAPI does not document as public.
    """
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
            continue
        nested_router = getattr(route, "original_router", None)
        if nested_router is not None:
            yield from _iter_api_routes(nested_router.routes)


def _app_routes() -> set[tuple[str, str]]:
    """Every (method, path) the app serves, mutating methods and exports only."""
    found: set[tuple[str, str]] = set()
    for route in _iter_api_routes(app.routes):
        for method in route.methods or set():
            pair = (method, route.path)
            if method in MUTATING_METHODS or pair in EXPORT_ROUTES:
                found.add(pair)
    return found


def test_every_mutating_route_is_classified() -> None:
    """A new mutating route fails here until somebody decides what it records.

    This is the failure `.claude/rules/audit-trail.md` exists to cause. If you are
    reading it because your new route broke this test: add it to `ROUTE_EVENTS` with
    an event, or with one of the four exemption reasons and a line in the rule.
    """
    unclassified = _app_routes() - set(ROUTE_EVENTS)

    assert not unclassified, (
        "These routes change data and record nothing. Classify each in ROUTE_EVENTS: "
        f"{sorted(unclassified)}"
    )


def test_the_classification_table_has_no_stale_entries() -> None:
    """A renamed or deleted route leaves an entry claiming coverage it no longer has."""
    stale = set(ROUTE_EVENTS) - _app_routes()

    assert not stale, f"ROUTE_EVENTS names routes the app does not serve: {sorted(stale)}"


def test_every_exemption_is_one_of_the_four() -> None:
    """The escape hatch cannot widen without editing the spec and the rule.

    `AuditEventType` is a `StrEnum`, so its members are themselves `str` instances --
    `isinstance(value, str)` alone would also match every classified event. The
    reasons are exactly the values that are *not* one of the catalogue's own names.
    """
    reasons = {value for value in ROUTE_EVENTS.values() if not isinstance(value, AuditEventType)}

    assert reasons <= VALID_EXEMPTIONS, (
        f"Undocumented exemption reason: {reasons - VALID_EXEMPTIONS}"
    )


def test_every_catalogue_name_declares_its_payload() -> None:
    """Walk the catalogue rather than the events, so a new name cannot ship undeclared.

    An event with no entry in either allowlist can still be recorded — it just may
    carry nothing. That is fine for `user.deactivated`, whose whole meaning is its
    name, and wrong for anything that meant to record a field. This asserts the
    declaration is deliberate: every name appears in at least one allowlist, or in
    the explicit set of events that are meaningful on their own.
    """
    from app.core.audit import CHANGED_FIELDS, CONTEXT_KEYS

    meaningful_alone = {
        AuditEventType.USER_DEACTIVATED,
        AuditEventType.CONVERSATION_CREATED,
    }
    declared = set(CHANGED_FIELDS) | set(CONTEXT_KEYS) | meaningful_alone

    assert set(AuditEventType) <= declared, (
        "These events declare no payload and are not in the meaningful-alone set: "
        f"{sorted(name.value for name in set(AuditEventType) - declared)}"
    )


def test_every_catalogue_name_has_a_write_site() -> None:
    """A name cannot exist unwritten.

    `user.created` is also written by the seed-admins CLI, and `auth.login.failed` by
    the failure branch of the login route rather than by a route of its own — both are
    covered by `tests/test_audit_write_sites.py`, so they are listed here explicitly
    rather than left looking uncovered.
    """
    written_by_route = {
        value for value in ROUTE_EVENTS.values() if isinstance(value, AuditEventType)
    }
    written_elsewhere = {
        # The failure branch of POST /auth/login.
        AuditEventType.AUTH_LOGIN_FAILED,
    }

    missing = set(AuditEventType) - written_by_route - written_elsewhere

    assert not missing, (
        f"Catalogue names with no write site: {sorted(name.value for name in missing)}"
    )

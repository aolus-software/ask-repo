"""One behavioural test per event: drive the real route, assert the real row.

`tests/test_audit_coverage.py` proves every mutating route has been *classified*.
This module proves each one actually records, with the payload the spec specifies —
the two are different failures and neither substitutes for the other.

Fixture parameters are annotated with the real ORM types (`User`, `Project`,
`ChecklistModule`, …), so import them from `app.models` as each task adds a test that
needs one. `ruff`'s `ANN` rules require the annotation, and `object` would defeat the
type checking that catches a fixture returning the wrong thing.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
import redis.asyncio as aioredis
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.audit import AuditEventType, AuditRecorder
from app.core.permissions import EDITOR_NAME
from app.core.rate_limit import LoginAttemptLimiter, RateLimiter
from app.core.security import sha256_hex
from app.db.session import get_sessionmaker
from app.ingestion.vector_store import InMemoryVectorStore
from app.models import User
from app.models.checklist import ChecklistItemStatus
from app.models.project import Project, ProjectStatus
from app.services.auth import AuthService
from tests.conftest import TEST_PASSWORD, AuditRows, GrantMembership
from tests.factories import (
    create_checklist_change_set,
    create_checklist_item,
    create_checklist_module,
    create_mock_data_change_set,
    create_mock_data_record,
    create_project,
)
from tests.helpers import changed_field, seed_indexed_paths


def _add_operation(
    operation_id: uuid.UUID, *, test_name: str = "Rejects a wrong password"
) -> dict[str, object]:
    """One `add` operation, shaped like a real change set's stored payload."""
    return {
        "op": "add",
        "id": str(operation_id),
        "feature": "Login",
        "testName": test_name,
        "expectedResult": "401 INVALID_CREDENTIALS",
        "citations": None,
        "rationale": "The handler raises on a bcrypt mismatch.",
    }


async def test_login_records_the_success(
    client: AsyncClient, authed_user: User, audit_rows: AuditRows
) -> None:
    response = await client.post(
        "/auth/login", json={"email": authed_user.email, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200

    rows = await audit_rows(AuditEventType.AUTH_LOGIN_SUCCEEDED)
    assert len(rows) == 1
    assert rows[0].actor_email == authed_user.email
    assert rows[0].outcome == "success"
    assert rows[0].details == {"mustChangePassword": False}


async def test_failed_login_records_the_attempt_against_a_known_account(
    client: AsyncClient, authed_user: User, audit_rows: AuditRows
) -> None:
    response = await client.post(
        "/auth/login", json={"email": authed_user.email, "password": "wrong-password"}
    )
    assert response.status_code == 401

    rows = await audit_rows(AuditEventType.AUTH_LOGIN_FAILED)
    assert len(rows) == 1
    assert rows[0].outcome == "failure"
    assert rows[0].actor_email == authed_user.email
    assert rows[0].details == {"unknownAccount": False}


async def test_failed_login_against_an_unknown_address_stores_no_address(
    client: AsyncClient, audit_rows: AuditRows
) -> None:
    """People paste passwords into the email field.

    This row is built from raw request input, so storing the submitted value blind
    would eventually put a password in the one table an operator is guaranteed to
    read. No match means nothing is stored but the fact and the source host.
    """
    response = await client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "hunter2"}
    )
    assert response.status_code == 401

    rows = await audit_rows(AuditEventType.AUTH_LOGIN_FAILED)
    assert len(rows) == 1
    assert rows[0].actor_user_id is None
    assert rows[0].actor_email is None
    assert rows[0].details == {"unknownAccount": True}


async def test_logout_records_its_scope(
    authed_client: AsyncClient, authed_user: User, audit_rows: AuditRows
) -> None:
    # `authed_client` carries a bearer token but no refresh cookie of its own — logout
    # reads the cookie, not the bearer, so log in first to have one to revoke. The
    # cookie is `Secure`, which httpx will not resend over the plain-http test
    # transport on its own, so it is set on the jar explicitly (see test_auth_api.py).
    login = await authed_client.post(
        "/auth/login", json={"email": authed_user.email, "password": TEST_PASSWORD}
    )
    assert login.status_code == 200
    authed_client.cookies.set(
        get_settings().refresh_cookie_name, login.cookies[get_settings().refresh_cookie_name]
    )

    response = await authed_client.post("/auth/logout")
    assert response.status_code == 204

    rows = await audit_rows(AuditEventType.AUTH_LOGOUT)
    assert len(rows) == 1
    assert rows[0].details == {"scope": "session"}


async def test_logout_all_records_the_wider_scope(
    authed_client: AsyncClient, authed_user: User, audit_rows: AuditRows
) -> None:
    login = await authed_client.post(
        "/auth/login", json={"email": authed_user.email, "password": TEST_PASSWORD}
    )
    assert login.status_code == 200

    response = await authed_client.post("/auth/logout-all")
    assert response.status_code == 204

    rows = await audit_rows(AuditEventType.AUTH_LOGOUT)
    assert rows[0].details == {"scope": "all"}


async def test_password_change_records_no_password(
    authed_client: AsyncClient, audit_rows: AuditRows
) -> None:
    """Both sides of this diff are what the content ban forbids storing.

    The event type is the whole record.
    """
    response = await authed_client.post(
        "/auth/change-password",
        json={"currentPassword": TEST_PASSWORD, "newPassword": "a-much-longer-secret"},
    )
    assert response.status_code == 200

    rows = await audit_rows(AuditEventType.AUTH_PASSWORD_CHANGED)
    assert len(rows) == 1
    assert rows[0].details == {"forced": False}
    assert "changed" not in rows[0].details
    serialised = str(rows[0].details)
    assert "a-much-longer-secret" not in serialised
    assert TEST_PASSWORD not in serialised


async def test_refresh_replay_records_the_family_and_revoked_count(
    client: AsyncClient, authed_user: User, db_session: AsyncSession, audit_rows: AuditRows
) -> None:
    """A genuine reuse, outside the grace window, is a replay and is recorded.

    A reuse *inside* the grace window mints a sibling instead (D12) and must not
    record — that branch is exercised by `tests/test_auth_api.py` and is not repeated
    here, since this module is about the payload of a recorded event, not the whole
    state machine.
    """
    login = await client.post(
        "/auth/login", json={"email": authed_user.email, "password": TEST_PASSWORD}
    )
    assert login.status_code == 200
    cookie_name = get_settings().refresh_cookie_name
    cookie = login.cookies[cookie_name]

    client.cookies.set(cookie_name, cookie)
    await client.post("/auth/refresh")

    # Age the now-consumed token past the grace window so the next presentation of
    # the original cookie is a genuine replay rather than the two-tabs race.
    await db_session.execute(
        text("UPDATE refresh_tokens SET used_at = :stale WHERE token_hash = :hash"),
        {"stale": datetime.now(UTC) - timedelta(hours=1), "hash": sha256_hex(cookie)},
    )
    await db_session.commit()

    client.cookies.set(cookie_name, cookie)
    response = await client.post("/auth/refresh")
    assert response.status_code == 401

    rows = await audit_rows(AuditEventType.AUTH_REFRESH_REPLAYED)
    assert len(rows) == 1
    assert rows[0].outcome == "failure"
    # A replayed refresh token is a security signal, and whose account it happened
    # on is the first thing a responder needs -- it is not left to `context`.
    assert rows[0].actor_user_id == authed_user.id
    assert rows[0].actor_email == authed_user.email
    revoked_count = rows[0].details["revokedCount"]
    assert isinstance(revoked_count, int)
    assert revoked_count >= 1
    assert isinstance(rows[0].details["familyId"], str)


async def test_failed_login_records_even_when_the_session_is_already_poisoned(
    db_session: AsyncSession,
    authed_user: User,
    redis_client: aioredis.Redis,
    audit_rows: AuditRows,
) -> None:
    """`_record_failed_login` used to run its own lookup on the request-scoped
    session, from inside the `except Exception:` branch in `login`. If the
    credential check itself failed for a database reason, that session is already in
    a failed transaction, and the lookup would raise `PendingRollbackError` -- an
    audit-path error *replacing* the caller's real exception, at the one call site
    the design names as why recording lives in the service rather than the route.

    The lookup is now wrapped so this cannot happen: the fallback ("no address
    stored") is exactly the behaviour an unresolvable lookup should have anyway.
    """
    settings = get_settings()
    limiter = LoginAttemptLimiter(RateLimiter(redis_client), settings)
    service = AuthService(
        db_session,
        settings,
        limiter,
        recorder=AuditRecorder(get_sessionmaker()),
        client_ip="203.0.113.1",
    )

    # Poison the session with a failing statement, and deliberately leave it
    # un-rolled-back -- exactly the state a mid-transaction database error leaves
    # `login`'s own session in.
    with pytest.raises(DBAPIError):
        await db_session.execute(text("SELECT * FROM no_such_table_at_all"))

    with pytest.raises(Exception):  # noqa: B017 -- the poisoned session's own error
        await service.login(authed_user.email, "irrelevant-password")

    # The session is unusable until it is rolled back; do that before reading the
    # row back, exactly as a real request's session teardown would.
    await db_session.rollback()

    rows = await audit_rows(AuditEventType.AUTH_LOGIN_FAILED)
    assert len(rows) == 1
    assert rows[0].outcome == "failure"
    # The lookup itself failed against the poisoned session, so the conservative
    # "unknown account" branch is what gets recorded -- never a raised exception
    # from the audit path, and never the caller's real address either.
    assert rows[0].actor_user_id is None
    assert rows[0].actor_email is None
    assert rows[0].details == {"unknownAccount": True}


async def test_user_create_records_the_new_values_with_a_null_before(
    client_for_admin: AsyncClient, audit_rows: AuditRows
) -> None:
    response = await client_for_admin.post(
        "/users",
        json={
            "name": "New Person",
            "email": "new@example.com",
            "password": "a-long-enough-password",
            "isAdmin": False,
        },
    )
    assert response.status_code == 201

    rows = await audit_rows(AuditEventType.USER_CREATED)
    assert len(rows) == 1
    assert rows[0].target_label == "new@example.com"
    assert changed_field(rows[0].details, "email") == {"before": None, "after": "new@example.com"}
    assert changed_field(rows[0].details, "isAdmin") == {"before": None, "after": False}
    assert rows[0].details["source"] == "api"
    # The password is nowhere in the row, in any form.
    assert "a-long-enough-password" not in str(rows[0].details)


async def test_user_update_records_only_what_changed(
    client_for_admin: AsyncClient, user_b: User, audit_rows: AuditRows
) -> None:
    response = await client_for_admin.patch(f"/users/{user_b.id}", json={"isAdmin": True})
    assert response.status_code == 200

    rows = await audit_rows(AuditEventType.USER_UPDATED)
    assert len(rows) == 1
    # `changed` is a diff, not a snapshot, so an unchanged field is absent. `email`
    # is absent for a second reason since A9: `UserUpdateRequest` never carried it,
    # so it is not writable through this route at all and was dropped from the
    # allowlist rather than left as an untested case.
    assert rows[0].details["changed"] == {"isAdmin": {"before": False, "after": True}}


async def test_user_deactivation_records_who_and_whom(
    client_for_admin: AsyncClient, user_b: User, admin_user: User, audit_rows: AuditRows
) -> None:
    response = await client_for_admin.delete(f"/users/{user_b.id}")
    assert response.status_code == 204

    rows = await audit_rows(AuditEventType.USER_DEACTIVATED)
    assert len(rows) == 1
    assert rows[0].actor_user_id == admin_user.id
    assert rows[0].target_id == user_b.id
    assert rows[0].target_label == user_b.email
    assert rows[0].details == {}


async def test_user_password_reset_records_no_password(
    client_for_admin: AsyncClient, user_b: User, audit_rows: AuditRows
) -> None:
    response = await client_for_admin.post(
        f"/users/{user_b.id}/reset-password",
        json={"newPassword": "a-brand-new-temporary-password"},
    )
    assert response.status_code == 200

    rows = await audit_rows(AuditEventType.USER_PASSWORD_RESET)
    assert len(rows) == 1
    assert rows[0].details == {"forced": True}
    serialised = str(rows[0].details)
    assert "a-brand-new-temporary-password" not in serialised


async def test_user_rename_records_a_name_only_change(
    client_for_admin: AsyncClient, user_b: User, audit_rows: AuditRows
) -> None:
    before_name = user_b.name
    response = await client_for_admin.patch(f"/users/{user_b.id}", json={"name": "Renamed Person"})
    assert response.status_code == 200

    rows = await audit_rows(AuditEventType.USER_UPDATED)
    assert len(rows) == 1
    # `isAdmin` did not change, so it is absent — a name-only edit must not be dropped
    # just because it doesn't touch the fields the allowlist used to permit.
    assert rows[0].details["changed"] == {
        "name": {"before": before_name, "after": "Renamed Person"}
    }
    assert "isAdmin" not in rows[0].details["changed"]


async def test_project_delete_records_the_blast_radius(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    authed_user: User,
    audit_rows: AuditRows,
) -> None:
    """The name is the point: a deleted project takes its created_by with it.

    The counts are the rest of it — PRD §4.2 sweeps every member's conversations with
    the project, so "a shared index disappeared on Tuesday" wants the blast radius,
    and it is only knowable at delete time.
    """
    project: Project = await create_project(
        db_session, created_by=authed_user.id, status=ProjectStatus.READY
    )
    await db_session.commit()

    response = await authed_client.delete(f"/projects/{project.id}")
    assert response.status_code == 204

    rows = await audit_rows(AuditEventType.PROJECT_DELETED)
    assert len(rows) == 1
    assert rows[0].target_label == project.name
    assert rows[0].project_id == project.id
    assert rows[0].actor_user_id == authed_user.id
    assert changed_field(rows[0].details, "name") == {"before": project.name, "after": None}
    assert "conversationsDeleted" in rows[0].details
    assert "checklistModulesDeleted" in rows[0].details


async def test_reindex_records_the_generation_it_supersedes(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    authed_user: User,
    audit_rows: AuditRows,
) -> None:
    """The new generation does not exist yet — the worker increments it.

    Recording the one being superseded is the only number available at request time,
    and it is the one that identifies what was replaced.
    """
    project: Project = await create_project(
        db_session, created_by=authed_user.id, status=ProjectStatus.READY
    )
    await db_session.commit()

    response = await authed_client.post(f"/projects/{project.id}/reindex")
    assert response.status_code == 202

    rows = await audit_rows(AuditEventType.PROJECT_REINDEX_REQUESTED)
    assert len(rows) == 1
    assert rows[0].details == {"supersededGeneration": project.active_generation}


async def test_membership_grant_targets_the_grantee_not_the_row(
    client_for_user_a: AsyncClient, user_b: User, audit_rows: AuditRows
) -> None:
    """The row reads as "X granted b@example.com viewer on <project>".

    Targeting the membership id instead would need a join through a row a later
    revocation has soft-deleted. `client_for_user_a` is the project's creator, so it
    is granted `owner` automatically and needs no separate setup.
    """
    created = await client_for_user_a.post(
        "/projects", json={"repoUrl": "https://github.com/o/r.git", "branch": "main"}
    )
    assert created.status_code == 201
    project_id = created.json()["id"]

    response = await client_for_user_a.post(
        f"/projects/{project_id}/members",
        json={"userId": str(user_b.id), "role": "viewer"},
    )
    assert response.status_code == 201

    rows = await audit_rows(AuditEventType.MEMBERSHIP_GRANTED)
    assert len(rows) == 1
    assert rows[0].target_type == "user"
    assert rows[0].target_id == user_b.id
    assert rows[0].target_label == user_b.email
    assert str(rows[0].project_id) == project_id
    assert changed_field(rows[0].details, "roleName") == {"before": None, "after": "viewer"}


async def test_membership_role_change_records_old_and_new_role_names(
    client_for_user_a: AsyncClient, user_b: User, audit_rows: AuditRows
) -> None:
    created = await client_for_user_a.post(
        "/projects", json={"repoUrl": "https://github.com/o/r2.git", "branch": "main"}
    )
    project_id = created.json()["id"]
    await client_for_user_a.post(
        f"/projects/{project_id}/members",
        json={"userId": str(user_b.id), "role": "viewer"},
    )

    response = await client_for_user_a.patch(
        f"/projects/{project_id}/members/{user_b.id}", json={"role": "editor"}
    )
    assert response.status_code == 200

    rows = await audit_rows(AuditEventType.MEMBERSHIP_ROLE_CHANGED)
    assert len(rows) == 1
    assert rows[0].target_type == "user"
    assert rows[0].target_id == user_b.id
    assert changed_field(rows[0].details, "roleName") == {"before": "viewer", "after": "editor"}


async def test_membership_revoke_records_the_role_it_removed(
    client_for_user_a: AsyncClient, user_b: User, audit_rows: AuditRows
) -> None:
    created = await client_for_user_a.post(
        "/projects", json={"repoUrl": "https://github.com/o/r3.git", "branch": "main"}
    )
    project_id = created.json()["id"]
    await client_for_user_a.post(
        f"/projects/{project_id}/members",
        json={"userId": str(user_b.id), "role": "viewer"},
    )

    response = await client_for_user_a.delete(f"/projects/{project_id}/members/{user_b.id}")
    assert response.status_code == 204

    rows = await audit_rows(AuditEventType.MEMBERSHIP_REVOKED)
    assert len(rows) == 1
    assert rows[0].target_id == user_b.id
    assert changed_field(rows[0].details, "roleName") == {"before": "viewer", "after": None}


async def test_role_create_records_a_null_before(
    client_for_admin: AsyncClient, audit_rows: AuditRows
) -> None:
    response = await client_for_admin.post(
        "/roles", json={"name": "QA Lead", "description": "Runs the test plan."}
    )
    assert response.status_code == 201

    rows = await audit_rows(AuditEventType.ROLE_CREATED)
    assert len(rows) == 1
    assert rows[0].project_id is None
    assert changed_field(rows[0].details, "name") == {"before": None, "after": "QA Lead"}
    assert changed_field(rows[0].details, "permissions") == {"before": None, "after": []}


async def test_role_update_records_the_permission_set_before_and_after(
    client_for_admin: AsyncClient, audit_rows: AuditRows
) -> None:
    """The most valuable diff in the table.

    This is the one write in the app that can widen what every holder of a role may
    do, across every project, and nothing else records it.
    """
    created = await client_for_admin.post("/roles", json={"name": "QA Lead 2"})
    role_id = created.json()["id"]

    response = await client_for_admin.patch(
        f"/roles/{role_id}", json={"permissions": ["project.read", "project.delete"]}
    )
    assert response.status_code == 200

    rows = await audit_rows(AuditEventType.ROLE_UPDATED)
    assert len(rows) == 1
    change = changed_field(rows[0].details, "permissions")
    after, before = change["after"], change["before"]
    assert isinstance(after, list)
    assert isinstance(before, list)
    assert "project.delete" in after
    assert "project.delete" not in before
    # A role is instance-wide; the assignment carries the project.
    assert rows[0].project_id is None


async def test_role_delete_records_the_permissions_it_held(
    client_for_admin: AsyncClient, audit_rows: AuditRows
) -> None:
    created = await client_for_admin.post("/roles", json={"name": "Temp Role"})
    role_id = created.json()["id"]
    await client_for_admin.patch(f"/roles/{role_id}", json={"permissions": ["project.read"]})

    response = await client_for_admin.delete(f"/roles/{role_id}")
    assert response.status_code == 204

    rows = await audit_rows(AuditEventType.ROLE_DELETED)
    assert len(rows) == 1
    assert changed_field(rows[0].details, "name") == {"before": "Temp Role", "after": None}
    assert changed_field(rows[0].details, "permissions") == {
        "before": ["project.read"],
        "after": None,
    }


async def _ready_project(db_session: AsyncSession) -> Project:
    """An indexed project: the pre-condition for creating a module or generating."""
    project = await create_project(db_session, status=ProjectStatus.READY)
    project.embedding_collection = "code_chunks__ollama__nomic_embed_text__768"
    project.embedding_model = get_settings().embedding_model
    project.active_generation = 1
    await db_session.flush()
    return project


async def test_checklist_module_create_records_name_and_source_path(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    vector_store: InMemoryVectorStore,
    audit_rows: AuditRows,
) -> None:
    project = await _ready_project(db_session)
    seed_indexed_paths(vector_store, project.id, "app/auth/routes.py")
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, EDITOR_NAME)

    response = await authed_client.post(
        "/checklist-modules",
        json={"projectId": str(project.id), "name": "Auth", "sourcePath": "app/auth"},
    )
    assert response.status_code == 201

    rows = await audit_rows(AuditEventType.CHECKLIST_MODULE_CREATED)
    assert len(rows) == 1
    assert rows[0].project_id == project.id
    assert rows[0].target_label == "Auth"
    assert changed_field(rows[0].details, "name") == {"before": None, "after": "Auth"}
    assert changed_field(rows[0].details, "sourcePath") == {"before": None, "after": "app/auth"}


async def test_checklist_module_rename_records_only_the_name(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    audit_rows: AuditRows,
) -> None:
    """A partial update diffs against what actually moved -- `sourcePath` did not
    change, so it must be absent rather than repeated as a before-equals-after pair."""
    module = await create_checklist_module(db_session, name="Old Name")
    await db_session.commit()
    await grant_membership(authed_user.id, module.project_id, EDITOR_NAME)

    response = await authed_client.patch(
        f"/checklist-modules/{module.id}", json={"name": "New Name"}
    )
    assert response.status_code == 200

    rows = await audit_rows(AuditEventType.CHECKLIST_MODULE_UPDATED)
    assert len(rows) == 1
    assert rows[0].details["changed"] == {"name": {"before": "Old Name", "after": "New Name"}}
    assert "sourcePath" not in rows[0].details["changed"]


async def test_checklist_module_delete_records_the_item_count(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    audit_rows: AuditRows,
) -> None:
    module = await create_checklist_module(db_session, name="Auth", source_path="app/auth")
    await create_checklist_item(db_session, module_id=module.id, test_name="first")
    await create_checklist_item(db_session, module_id=module.id, test_name="second")
    await db_session.commit()
    await grant_membership(authed_user.id, module.project_id, EDITOR_NAME)

    response = await authed_client.delete(f"/checklist-modules/{module.id}")
    assert response.status_code == 204

    rows = await audit_rows(AuditEventType.CHECKLIST_MODULE_DELETED)
    assert len(rows) == 1
    assert changed_field(rows[0].details, "name") == {"before": "Auth", "after": None}
    assert changed_field(rows[0].details, "sourcePath") == {"before": "app/auth", "after": None}
    # Read before the sweep ran -- the count that matters is what was actually lost.
    assert rows[0].details["itemCount"] == 2


async def test_checklist_module_generation_requested_records_the_indexed_generation(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    audit_rows: AuditRows,
) -> None:
    project = await _ready_project(db_session)
    module = await create_checklist_module(db_session, project_id=project.id)
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, EDITOR_NAME)

    response = await authed_client.post(f"/checklist-modules/{module.id}/generate")
    assert response.status_code == 202

    rows = await audit_rows(AuditEventType.CHECKLIST_MODULE_GENERATION_REQUESTED)
    assert len(rows) == 1
    assert rows[0].details == {"indexedGeneration": 1}


async def test_checklist_item_create_records_manual_origin(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    audit_rows: AuditRows,
) -> None:
    module = await create_checklist_module(db_session)
    await db_session.commit()
    await grant_membership(authed_user.id, module.project_id, EDITOR_NAME)

    response = await authed_client.post(
        "/checklist-items",
        json={
            "moduleId": str(module.id),
            "feature": "Login",
            "testName": "Rejects a bad password",
            "expectedResult": "401",
        },
    )
    assert response.status_code == 201

    rows = await audit_rows(AuditEventType.CHECKLIST_ITEM_CREATED)
    assert len(rows) == 1
    assert rows[0].details["origin"] == "manual"
    assert changed_field(rows[0].details, "feature") == {"before": None, "after": "Login"}
    assert changed_field(rows[0].details, "testName") == {
        "before": None,
        "after": "Rejects a bad password",
    }
    # The body a human wrote is nowhere in the row.
    assert "401" not in str(rows[0].details)


async def test_checklist_item_update_records_only_the_changed_fields(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    audit_rows: AuditRows,
) -> None:
    module = await create_checklist_module(db_session)
    item = await create_checklist_item(db_session, module_id=module.id, feature="Login")
    await db_session.commit()
    await grant_membership(authed_user.id, module.project_id, EDITOR_NAME)

    response = await authed_client.patch(
        f"/checklist-items/{item.id}", json={"feature": "Authentication"}
    )
    assert response.status_code == 200

    rows = await audit_rows(AuditEventType.CHECKLIST_ITEM_UPDATED)
    assert len(rows) == 1
    assert rows[0].details["changed"] == {"feature": {"before": "Login", "after": "Authentication"}}
    assert "testName" not in rows[0].details["changed"]
    assert "expectedResult" not in rows[0].details["changed"]


async def test_checklist_item_update_never_stores_the_expected_result_text(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    audit_rows: AuditRows,
) -> None:
    """`expectedResult` is model-authored prose derived from a private repository, and
    `audit_events` has no project-deletion sweep -- so a copy of it would outlive the
    project it described. Only a boolean flag may cross into the row."""
    module = await create_checklist_module(db_session)
    item = await create_checklist_item(
        db_session, module_id=module.id, expected_result="Returns 401 Unauthorized"
    )
    await db_session.commit()
    await grant_membership(authed_user.id, module.project_id, EDITOR_NAME)

    response = await authed_client.patch(
        f"/checklist-items/{item.id}",
        json={"expectedResult": "Returns 403 Forbidden with a WWW-Authenticate header"},
    )
    assert response.status_code == 200

    rows = await audit_rows(AuditEventType.CHECKLIST_ITEM_UPDATED)
    assert len(rows) == 1
    assert changed_field(rows[0].details, "expectedResultChanged") == {
        "before": False,
        "after": True,
    }
    assert "expectedResult" not in cast(dict[str, object], rows[0].details["changed"])
    # Neither the old nor the new expectation text is anywhere in the row.
    assert "401 Unauthorized" not in str(rows[0].details)
    assert "403 Forbidden" not in str(rows[0].details)


async def test_recording_a_result_is_its_own_event(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    audit_rows: AuditRows,
) -> None:
    """Separate from checklist_item.updated even though both are a PATCH-shaped write.

    `status` and `current_result` are the two columns the change-set apply path is
    forbidden to write, because they claim a human observation. Keeping the event that
    legitimately writes them distinct is what makes "who recorded this pass?"
    answerable without reading the payload of every update.

    `currentResult` itself never reaches the row: it is a tester's free-text
    observation about generated test content, which the content ban forbids storing,
    and `audit_events` has no project-deletion sweep to age it out.
    """
    module = await create_checklist_module(db_session)
    item = await create_checklist_item(db_session, module_id=module.id)
    await db_session.commit()
    await grant_membership(authed_user.id, module.project_id, EDITOR_NAME)

    response = await authed_client.put(
        f"/checklist-items/{item.id}/result",
        json={"status": "pass", "currentResult": "works as described"},
    )
    assert response.status_code == 200

    recorded = await audit_rows(AuditEventType.CHECKLIST_ITEM_RESULT_RECORDED)
    edited = await audit_rows(AuditEventType.CHECKLIST_ITEM_UPDATED)
    assert len(recorded) == 1
    assert not edited
    assert changed_field(recorded[0].details, "status") == {"before": "untested", "after": "pass"}
    assert changed_field(recorded[0].details, "currentResultChanged") == {
        "before": False,
        "after": True,
    }
    assert "currentResult" not in cast(dict[str, object], recorded[0].details["changed"])
    assert "works as described" not in str(recorded[0].details)


async def test_checklist_item_delete_records_a_recorded_result_as_lost(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    audit_rows: AuditRows,
) -> None:
    module = await create_checklist_module(db_session)
    item = await create_checklist_item(
        db_session,
        module_id=module.id,
        status=ChecklistItemStatus.PASS,
        current_result="Returned 200",
    )
    await db_session.commit()
    await grant_membership(authed_user.id, module.project_id, EDITOR_NAME)

    response = await authed_client.delete(f"/checklist-items/{item.id}")
    assert response.status_code == 204

    rows = await audit_rows(AuditEventType.CHECKLIST_ITEM_DELETED)
    assert len(rows) == 1
    assert rows[0].details["hadRecordedResult"] is True
    assert changed_field(rows[0].details, "feature")["after"] is None
    assert changed_field(rows[0].details, "testName")["after"] is None


async def test_checklist_item_delete_of_an_untested_item_records_no_loss(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    audit_rows: AuditRows,
) -> None:
    module = await create_checklist_module(db_session)
    item = await create_checklist_item(db_session, module_id=module.id)
    await db_session.commit()
    await grant_membership(authed_user.id, module.project_id, EDITOR_NAME)

    response = await authed_client.delete(f"/checklist-items/{item.id}")
    assert response.status_code == 204

    rows = await audit_rows(AuditEventType.CHECKLIST_ITEM_DELETED)
    assert len(rows) == 1
    assert rows[0].details["hadRecordedResult"] is False


async def test_apply_records_what_was_proposed_and_what_was_taken(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    audit_rows: AuditRows,
) -> None:
    """The gap between the two numbers is the record that a human reviewed.

    Neither carries the operations themselves: those are model-authored content
    naming files and test cases.
    """
    module = await create_checklist_module(db_session)
    first_operation = uuid.uuid4()
    second_operation = uuid.uuid4()
    change_set = await create_checklist_change_set(
        db_session,
        module_id=module.id,
        operations=[
            _add_operation(first_operation, test_name="first"),
            _add_operation(second_operation, test_name="second"),
        ],
    )
    await db_session.commit()
    await grant_membership(authed_user.id, module.project_id, EDITOR_NAME)

    response = await authed_client.post(
        f"/checklist-change-sets/{change_set.id}/apply",
        json={"operationIds": [str(first_operation)]},
    )
    assert response.status_code == 200

    rows = await audit_rows(AuditEventType.CHECKLIST_CHANGE_SET_APPLIED)
    assert len(rows) == 1
    assert rows[0].details["operationsProposed"] == len(change_set.operations)
    assert rows[0].details["operationsApplied"] == 1
    assert rows[0].target_label == module.name
    assert "operations" not in rows[0].details


async def test_discard_records_what_was_proposed(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    audit_rows: AuditRows,
) -> None:
    """A discard is also a review decision: it records the count of what was
    thrown away, never the operations themselves."""
    module = await create_checklist_module(db_session)
    change_set = await create_checklist_change_set(
        db_session,
        module_id=module.id,
        operations=[_add_operation(uuid.uuid4())],
    )
    await db_session.commit()
    await grant_membership(authed_user.id, module.project_id, EDITOR_NAME)

    response = await authed_client.post(f"/checklist-change-sets/{change_set.id}/discard")
    assert response.status_code == 200

    rows = await audit_rows(AuditEventType.CHECKLIST_CHANGE_SET_DISCARDED)
    assert len(rows) == 1
    assert rows[0].details["operationsProposed"] == 1
    assert rows[0].details["origin"] == change_set.origin
    assert "operations" not in rows[0].details


async def test_export_records_that_content_left_the_instance(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    audit_rows: AuditRows,
) -> None:
    """An export changes nothing and is audited anyway.

    It is the one action that takes a private repository's derived content out of the
    instance, and PRD §9 treats egress as a category of its own. The row says how much
    left, never what.
    """
    module = await create_checklist_module(db_session)
    await create_checklist_item(db_session, module_id=module.id, test_name="first")
    await create_checklist_item(db_session, module_id=module.id, test_name="second")
    await db_session.commit()
    await grant_membership(authed_user.id, module.project_id, EDITOR_NAME)

    response = await authed_client.get(f"/checklist-items/export?moduleId={module.id}")
    assert response.status_code == 200

    rows = await audit_rows(AuditEventType.CHECKLIST_EXPORTED)
    assert len(rows) == 1
    assert rows[0].details["format"] == "xlsx"
    assert rows[0].details["rowCount"] == 2
    assert rows[0].details["filter"] == {"moduleId": str(module.id)}
    # The query narrowed to exactly one module, so the row names it rather than
    # showing a bare `checklist_item` with nothing to point at.
    assert rows[0].target_label == module.name
    assert rows[0].details["projectCount"] == 1
    assert "first" not in str(rows[0].details)
    assert "second" not in str(rows[0].details)


async def test_export_spanning_multiple_projects_records_no_single_project(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    audit_rows: AuditRows,
) -> None:
    """An unfiltered export can span every project the caller can reach.

    Stamping whichever row happens to sort first would misattribute the export to
    one project out of many, so an export that matches more than one project records
    no `project_id` at all -- `projectCount` says how many it actually spanned.
    """
    module_a = await create_checklist_module(db_session)
    module_b = await create_checklist_module(db_session)
    await create_checklist_item(db_session, module_id=module_a.id, test_name="first")
    await create_checklist_item(db_session, module_id=module_b.id, test_name="second")
    await db_session.commit()
    await grant_membership(authed_user.id, module_a.project_id, EDITOR_NAME)
    await grant_membership(authed_user.id, module_b.project_id, EDITOR_NAME)

    response = await authed_client.get("/checklist-items/export")
    assert response.status_code == 200

    rows = await audit_rows(AuditEventType.CHECKLIST_EXPORTED)
    assert len(rows) == 1
    assert rows[0].project_id is None
    assert rows[0].details["projectCount"] == 2
    assert rows[0].target_type is None
    assert rows[0].target_label is None


async def test_a_feature_filter_is_recorded_as_a_flag_not_the_feature_name(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    audit_rows: AuditRows,
) -> None:
    """A14: a feature name is generated content, and both bulk routes drop it.

    `feature` is picked off a model's output in the UI, so storing the caller's value
    would put generated test content in the trail exactly as `expectedResult` would.
    `featureFilterApplied` records that a feature narrowed the operation without
    naming which one, so the filter stays legible and the content ban holds. `search`
    is the caller's own words and deliberately stays -- the two are treated
    differently on purpose, and nothing else asserts the difference.
    """
    feature = "Password reset flow"
    module = await create_checklist_module(db_session)
    await create_checklist_item(
        db_session,
        module_id=module.id,
        feature=feature,
        test_name="first",
        status=ChecklistItemStatus.PASS,
        current_result="It happened",
    )
    await db_session.commit()
    await grant_membership(authed_user.id, module.project_id, EDITOR_NAME)

    exported = await authed_client.get(
        "/checklist-items/export",
        params={"moduleId": str(module.id), "feature": feature},
    )
    assert exported.status_code == 200

    cleared = await authed_client.post(
        "/checklist-items/clear-results",
        json={"moduleId": str(module.id), "feature": feature},
    )
    assert cleared.status_code == 200
    assert cleared.json()["clearedCount"] == 1

    export_rows = await audit_rows(AuditEventType.CHECKLIST_EXPORTED)
    clear_rows = await audit_rows(AuditEventType.CHECKLIST_ITEM_RESULTS_CLEARED)
    assert len(export_rows) == 1
    assert len(clear_rows) == 1
    for row in (export_rows[0], clear_rows[0]):
        recorded_filter = cast(dict[str, str], row.details["filter"])
        assert recorded_filter["featureFilterApplied"] == "true"
        assert "feature" not in recorded_filter
        assert feature not in str(row.details)


def _mock_data_add_operation(
    operation_id: uuid.UUID, *, name: str = "Ada Lovelace"
) -> dict[str, object]:
    """One `add` operation, shaped like a real mock-data change set's stored payload."""
    return {
        "op": "add",
        "id": str(operation_id),
        "fields": {"name": name},
        "rationale": "A plausible user record.",
    }


async def test_mock_data_generation_requested_records_the_indexed_generation(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    audit_rows: AuditRows,
) -> None:
    project = await _ready_project(db_session)
    module = await create_checklist_module(db_session, project_id=project.id)
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, EDITOR_NAME)

    response = await authed_client.post(f"/checklist-modules/{module.id}/mock-data-generations")
    assert response.status_code == 202

    rows = await audit_rows(AuditEventType.MOCK_DATA_GENERATION_REQUESTED)
    assert len(rows) == 1
    assert rows[0].project_id == project.id
    assert rows[0].target_label == module.name
    assert rows[0].details == {"indexedGeneration": 1}


@pytest.mark.parametrize(
    ("path_suffix", "expected_format"),
    [("export.json", "json"), ("export.xlsx", "xlsx")],
)
async def test_both_mock_data_exports_record_their_format(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    audit_rows: AuditRows,
    path_suffix: str,
    expected_format: str,
) -> None:
    """Two routes, one event, distinguished by a context key rather than by name.

    Splitting them would put the same question -- did this dataset leave the instance?
    -- behind two names an admin has to know to search for.
    """
    module = await create_checklist_module(db_session)
    await create_mock_data_record(db_session, module_id=module.id)
    await create_mock_data_record(db_session, module_id=module.id)
    await db_session.commit()
    await grant_membership(authed_user.id, module.project_id, EDITOR_NAME)

    response = await authed_client.get(f"/checklist-modules/{module.id}/mock-data/{path_suffix}")
    assert response.status_code == 200

    rows = await audit_rows(AuditEventType.MOCK_DATA_EXPORTED)
    assert len(rows) == 1
    assert rows[0].details["format"] == expected_format
    assert rows[0].details["rowCount"] == 2
    assert rows[0].project_id == module.project_id
    assert rows[0].target_label == module.name


async def test_mock_data_record_delete_records_its_position(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    audit_rows: AuditRows,
) -> None:
    """The record's field values are generated content and stay out of the row."""
    module = await create_checklist_module(db_session)
    record = await create_mock_data_record(
        db_session, module_id=module.id, fields={"name": "Ada Lovelace"}
    )
    await db_session.commit()
    await grant_membership(authed_user.id, module.project_id, EDITOR_NAME)

    response = await authed_client.delete(f"/mock-data-records/{record.id}")
    assert response.status_code == 204

    rows = await audit_rows(AuditEventType.MOCK_DATA_RECORD_DELETED)
    assert len(rows) == 1
    assert rows[0].target_label == module.name
    assert rows[0].details == {"position": record.position}
    assert "Ada Lovelace" not in str(rows[0].details)


async def test_mock_data_apply_records_what_was_proposed_and_what_was_taken(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    audit_rows: AuditRows,
) -> None:
    module = await create_checklist_module(db_session)
    first_operation = uuid.uuid4()
    second_operation = uuid.uuid4()
    change_set = await create_mock_data_change_set(
        db_session,
        module_id=module.id,
        operations=[
            _mock_data_add_operation(first_operation, name="first"),
            _mock_data_add_operation(second_operation, name="second"),
        ],
    )
    await db_session.commit()
    await grant_membership(authed_user.id, module.project_id, EDITOR_NAME)

    response = await authed_client.post(
        f"/mock-data-change-sets/{change_set.id}/apply",
        json={"operationIds": [str(first_operation)]},
    )
    assert response.status_code == 200

    rows = await audit_rows(AuditEventType.MOCK_DATA_CHANGE_SET_APPLIED)
    assert len(rows) == 1
    assert rows[0].details["operationsProposed"] == len(change_set.operations)
    assert rows[0].details["operationsApplied"] == 1
    assert rows[0].target_label == module.name
    assert "operations" not in rows[0].details


async def test_mock_data_discard_records_what_was_proposed(
    authed_client: AsyncClient,
    authed_user: User,
    grant_membership: GrantMembership,
    db_session: AsyncSession,
    audit_rows: AuditRows,
) -> None:
    module = await create_checklist_module(db_session)
    change_set = await create_mock_data_change_set(
        db_session,
        module_id=module.id,
        operations=[_mock_data_add_operation(uuid.uuid4())],
    )
    await db_session.commit()
    await grant_membership(authed_user.id, module.project_id, EDITOR_NAME)

    response = await authed_client.post(f"/mock-data-change-sets/{change_set.id}/discard")
    assert response.status_code == 200

    rows = await audit_rows(AuditEventType.MOCK_DATA_CHANGE_SET_DISCARDED)
    assert len(rows) == 1
    assert rows[0].details["operationsProposed"] == 1
    assert rows[0].details["origin"] == change_set.origin
    assert rows[0].target_label == module.name
    assert "operations" not in rows[0].details

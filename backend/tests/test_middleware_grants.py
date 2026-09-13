"""The grant snapshot the middleware attaches to every authenticated request.

Populated here, read by `app.core.access` in Task 5. Nothing reads it yet, so these
tests are the only thing holding the load honest — a `_load_grants` that returned an
empty mapping unconditionally would break no other test in the suite.

The end-to-end test therefore mounts a throwaway probe route that reports what the
middleware actually put on `request.state.auth`. No shipped route exposes the
snapshot yet, and asserting a `200` from one that ignores it would assert nothing.
"""

import uuid

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.middleware import AuthenticatedUser, ProjectGrant, _load_grants
from app.core.permissions import EDITOR_NAME, SYSTEM_ROLES, VIEWER_NAME, Permission
from app.core.security import create_access_token
from app.models.membership import ProjectMembership, Role
from app.models.user import User
from tests.factories import create_project, create_user


async def _role(session: AsyncSession, name: str) -> Role:
    """One of the three system roles `_clean_tables` re-seeds between tests."""
    return (await session.execute(select(Role).where(Role.name == name))).scalar_one()


async def _grant(
    session: AsyncSession, *, user_id: uuid.UUID, project_id: uuid.UUID, role: str
) -> None:
    session.add(
        ProjectMembership(
            id=uuid.uuid4(),
            user_id=user_id,
            project_id=project_id,
            role_id=(await _role(session, role)).id,
        )
    )


def test_authenticated_user_defaults_to_no_grants() -> None:
    """A user constructed without grants has none — never 'all'. Every test fixture
    and every code path that builds one by hand relies on this default being empty."""
    user = AuthenticatedUser(
        id=uuid.uuid4(),
        name="Dev",
        email="dev@example.com",
        is_admin=False,
        must_change_password=False,
    )

    assert user.grants == {}


def test_a_grant_carries_the_role_name_and_permissions() -> None:
    project_id = uuid.uuid4()
    grant = ProjectGrant(
        project_id=project_id,
        role=VIEWER_NAME,
        permissions=frozenset({Permission.PROJECT_READ.value}),
    )

    assert grant.project_id == project_id
    assert grant.role == VIEWER_NAME
    assert Permission.PROJECT_READ.value in grant.permissions


async def test_load_grants_builds_a_grant_per_membership(db_session: AsyncSession) -> None:
    """The snapshot is keyed by project id and carries the role's expanded permissions."""
    user = await create_user(db_session)
    viewed = await create_project(db_session, created_by=user.id)
    edited = await create_project(db_session, created_by=user.id)
    await _grant(db_session, user_id=user.id, project_id=viewed.id, role=VIEWER_NAME)
    await _grant(db_session, user_id=user.id, project_id=edited.id, role=EDITOR_NAME)
    await db_session.commit()

    grants = await _load_grants(db_session, user.id)

    assert set(grants) == {viewed.id, edited.id}
    assert grants[viewed.id] == ProjectGrant(
        project_id=viewed.id,
        role=VIEWER_NAME,
        permissions=frozenset(str(permission) for permission in SYSTEM_ROLES[VIEWER_NAME]),
    )
    assert grants[edited.id].role == EDITOR_NAME
    assert Permission.MODULE_EDIT.value in grants[edited.id].permissions
    assert Permission.PROJECT_DELETE.value not in grants[edited.id].permissions


async def test_load_grants_is_empty_for_a_user_with_no_membership(
    db_session: AsyncSession,
) -> None:
    """No membership means no access — the default the whole design rests on."""
    user = await create_user(db_session)
    await create_project(db_session)
    await db_session.commit()

    assert await _load_grants(db_session, user.id) == {}


async def test_the_snapshot_cannot_be_mutated_by_its_holder(db_session: AsyncSession) -> None:
    """A `MappingProxyType`, so a handler cannot widen the access it was handed."""
    user = await create_user(db_session)
    project = await create_project(db_session, created_by=user.id)
    await _grant(db_session, user_id=user.id, project_id=project.id, role=VIEWER_NAME)
    await db_session.commit()

    grants = await _load_grants(db_session, user.id)

    with pytest.raises(TypeError):
        grants[uuid.uuid4()] = ProjectGrant(  # type: ignore[index]  # the point of the test
            project_id=uuid.uuid4(), role="owner", permissions=frozenset()
        )


async def test_the_middleware_loads_grants_onto_the_request(
    app: FastAPI, db_session: AsyncSession
) -> None:
    """End to end: a membership in the database appears on `request.state.auth`.

    Read through a probe route mounted on the app under test, because no shipped
    route surfaces the snapshot until Task 5 gives it a reader.
    """
    user = await create_user(db_session)
    project = await create_project(db_session, created_by=user.id)
    await _grant(db_session, user_id=user.id, project_id=project.id, role=EDITOR_NAME)
    await db_session.commit()

    async with _probe_client(app, user) as client:
        response = await client.get("/_probe/grants")

    assert response.status_code == 200
    assert response.json() == [
        {
            "projectId": str(project.id),
            "role": EDITOR_NAME,
            "permissions": sorted(str(p) for p in SYSTEM_ROLES[EDITOR_NAME]),
        }
    ]


def _probe_client(app: FastAPI, user: User) -> AsyncClient:
    """A client for `app` with a `/_probe/grants` route that reports the snapshot."""

    @app.get("/_probe/grants")
    async def read_grants(request: Request) -> list[dict[str, object]]:
        auth = request.state.auth
        assert auth.user is not None
        return [
            {
                "projectId": str(grant.project_id),
                "role": grant.role,
                "permissions": sorted(grant.permissions),
            }
            for grant in auth.user.grants.values()
        ]

    settings = get_settings()
    token, _ = create_access_token(
        user.id, secret=settings.secret_key, ttl_minutes=settings.access_token_ttl_minutes
    )
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )

"""The seed and backfill the RBAC migration performs.

The suite migrates a fresh database per session (`conftest._migrated_database`), so
these assert against what the migration actually produced rather than re-running it.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import SYSTEM_ROLES, Permission
from app.core.security import hash_password
from app.models.membership import ProjectMembership, Role, RolePermission
from app.models.project import Project, ProjectStatus
from app.models.user import User


async def test_the_three_system_roles_are_seeded(db_session: AsyncSession) -> None:
    rows = (await db_session.execute(select(Role).where(Role.is_system.is_(True)))).scalars().all()

    assert {row.name for row in rows} == {"viewer", "editor", "owner"}


async def test_owner_is_seeded_with_every_permission(db_session: AsyncSession) -> None:
    owner = (await db_session.execute(select(Role).where(Role.name == "owner"))).scalar_one()
    permissions = (
        (
            await db_session.execute(
                select(RolePermission.permission).where(RolePermission.role_id == owner.id)
            )
        )
        .scalars()
        .all()
    )

    assert set(permissions) == {p.value for p in SYSTEM_ROLES["owner"]}
    assert set(permissions) == {p.value for p in Permission}


async def test_viewer_is_seeded_with_result_record(db_session: AsyncSession) -> None:
    """docs/PRD.md §4.3:511 — recording a result is not gated."""
    viewer = (await db_session.execute(select(Role).where(Role.name == "viewer"))).scalar_one()
    permissions = (
        (
            await db_session.execute(
                select(RolePermission.permission).where(RolePermission.role_id == viewer.id)
            )
        )
        .scalars()
        .all()
    )

    assert Permission.RESULT_RECORD.value in permissions
    assert Permission.ITEM_EDIT.value not in permissions


async def test_a_regrant_after_a_revoke_does_not_collide(db_session: AsyncSession) -> None:
    """The partial unique index. Without `WHERE deleted_at IS NULL` this raises
    IntegrityError on a row the admin cannot see."""
    from datetime import UTC, datetime

    user = User(
        id=uuid.uuid4(),
        name="Dev",
        email=f"{uuid.uuid4().hex}@example.com",
        password_hash=hash_password("a-perfectly-fine-passphrase", cost=4),
        is_admin=False,
        must_change_password=False,
    )
    project = Project(
        id=uuid.uuid4(),
        created_by=user.id,
        name="repo",
        repo_url="https://example.com/o/r.git",
        branch="main",
        status=ProjectStatus.READY.value,
    )
    viewer = (await db_session.execute(select(Role).where(Role.name == "viewer"))).scalar_one()
    # `projects.created_by` is a foreign key and there is no ORM relationship between
    # the two mappers, so the unit of work will not order these for us.
    db_session.add(user)
    await db_session.flush()
    db_session.add(project)
    await db_session.commit()

    first = ProjectMembership(
        id=uuid.uuid4(), user_id=user.id, project_id=project.id, role_id=viewer.id
    )
    db_session.add(first)
    await db_session.commit()

    first.deleted_at = datetime.now(UTC)
    await db_session.commit()

    db_session.add(
        ProjectMembership(
            id=uuid.uuid4(), user_id=user.id, project_id=project.id, role_id=viewer.id
        )
    )
    await db_session.commit()  # must not raise

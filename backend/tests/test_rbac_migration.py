"""The seed and backfill the RBAC migration performs.

**These do not read the live test database.** `conftest._clean_tables` truncates every
table between tests and then restores the system roles with
`app.core.role_seed.ensure_system_roles`, because they are reference data rather than
test data. Asserting against those rows would therefore test the runtime seeder, not
the migration -- a seed that ran but landed `is_system = false` would stay green, and
the immutability guard that keeps an admin from re-permissioning `owner` would be
protecting rows that are not marked as system roles at all.

So `migration_seed` runs the migrations once into a scratch database and snapshots
what they produced. A scratch database rather than a snapshot taken early on the shared
one: `alembic upgrade head` is a no-op against a database already at head, so on the
second run of the suite the "migration output" would silently be the previous run's
runtime seeding.
"""

import os
import subprocess
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

import asyncpg
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.permissions import SYSTEM_ROLES, Permission
from app.core.security import hash_password
from app.models.membership import ProjectMembership, Role
from app.models.project import Project, ProjectStatus
from app.models.user import User
from tests.conftest import BACKEND_ROOT, _swap_database

SEED_DB_NAME = "askrepo_seed_check"


@dataclass(frozen=True, slots=True)
class SeededRole:
    """One role exactly as the migration left it, detached from any session."""

    name: str
    is_system: bool
    description: str | None
    permissions: frozenset[str]


@pytest.fixture(scope="session")
async def migration_seed() -> AsyncIterator[dict[str, SeededRole]]:
    """Every live role the migrations create, read from a freshly migrated database.

    Session-scoped and built once. The scratch database is dropped afterwards, so
    nothing here can influence the suite's own database.
    """
    settings = get_settings()
    admin_url = _swap_database(settings.database_url, "postgres").replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    connection = await asyncpg.connect(admin_url)
    try:
        await connection.execute(f'DROP DATABASE IF EXISTS "{SEED_DB_NAME}"')
        await connection.execute(f'CREATE DATABASE "{SEED_DB_NAME}"')
    finally:
        await connection.close()

    try:
        subprocess.run(
            ["uv", "run", "alembic", "upgrade", "head"],
            cwd=BACKEND_ROOT,
            check=True,
            env={
                **os.environ,
                "DATABASE_URL": _swap_database(settings.database_url, SEED_DB_NAME),
            },
        )
        yield await _read_roles(_swap_database(admin_url, SEED_DB_NAME))
    finally:
        connection = await asyncpg.connect(admin_url)
        try:
            await connection.execute(f'DROP DATABASE IF EXISTS "{SEED_DB_NAME}" WITH (FORCE)')
        finally:
            await connection.close()


async def _read_roles(url: str) -> dict[str, SeededRole]:
    """Snapshot `roles` + `role_permissions` as plain data, keyed by role name."""
    connection = await asyncpg.connect(url)
    try:
        rows = await connection.fetch(
            """
            SELECT r.name, r.is_system, r.description, rp.permission
            FROM roles r
            LEFT JOIN role_permissions rp
                   ON rp.role_id = r.id AND rp.deleted_at IS NULL
            WHERE r.deleted_at IS NULL
            """
        )
    finally:
        await connection.close()

    held: dict[str, set[str]] = {}
    for row in rows:
        held.setdefault(row["name"], set())
        if row["permission"] is not None:
            held[row["name"]].add(row["permission"])

    return {
        row["name"]: SeededRole(
            name=row["name"],
            is_system=row["is_system"],
            description=row["description"],
            permissions=frozenset(held[row["name"]]),
        )
        for row in rows
    }


async def test_the_three_system_roles_are_seeded(migration_seed: dict[str, SeededRole]) -> None:
    assert set(migration_seed) == {"viewer", "editor", "owner"}


async def test_the_seeded_roles_are_marked_as_system(
    migration_seed: dict[str, SeededRole],
) -> None:
    """`is_system` is what Task 10's immutability guard reads. A seed that landed it
    `false` leaves viewer/editor/owner editable, and an admin unchecking
    `membership.grant` on `owner` leaves nobody able to grant membership at all."""
    assert [role.name for role in migration_seed.values() if not role.is_system] == []


async def test_owner_is_seeded_with_every_permission(
    migration_seed: dict[str, SeededRole],
) -> None:
    permissions = migration_seed["owner"].permissions

    assert permissions == {p.value for p in SYSTEM_ROLES["owner"]}
    assert permissions == {p.value for p in Permission}


async def test_viewer_is_seeded_with_result_record(
    migration_seed: dict[str, SeededRole],
) -> None:
    """docs/PRD.md §4.3:511 — recording a result is not gated."""
    permissions = migration_seed["viewer"].permissions

    assert Permission.RESULT_RECORD.value in permissions
    assert Permission.ITEM_EDIT.value not in permissions


async def test_a_regrant_after_a_revoke_does_not_collide(db_session: AsyncSession) -> None:
    """The partial unique index. Without `WHERE deleted_at IS NULL` this raises
    IntegrityError on a row the admin cannot see.

    This one reads the live database on purpose: TRUNCATE does not drop indexes, so
    the DDL under test here is the migration's own.
    """
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

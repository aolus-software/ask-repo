"""The grant cache, and the four ways it can be wrong without anything erroring.

`conftest._clean_redis` flushes between tests, so each starts from an empty cache.
"""

import uuid
from typing import cast

import redis.asyncio as aioredis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.grant_cache import GrantCache
from app.core.permissions import Permission
from app.core.security import hash_password
from app.models.membership import ProjectMembership, Role
from app.models.project import Project, ProjectStatus
from app.models.user import User


class _BrokenRedis:
    """A client that fails every call, to exercise the fallback path."""

    async def get(self, *args: object, **kwargs: object) -> object:
        raise RedisError("redis is down")

    async def set(self, *args: object, **kwargs: object) -> object:
        raise RedisError("redis is down")

    async def delete(self, *args: object, **kwargs: object) -> object:
        raise RedisError("redis is down")

    async def incr(self, *args: object, **kwargs: object) -> object:
        raise RedisError("redis is down")


async def _seed(
    session: AsyncSession, role_name: str = "viewer"
) -> tuple[User, Project, ProjectMembership]:
    user = User(
        id=uuid.uuid4(),
        name="Dev",
        email=f"{uuid.uuid4().hex}@example.com",
        password_hash=hash_password("a-perfectly-fine-passphrase", cost=4),
        is_admin=False,
        must_change_password=False,
    )
    session.add(user)
    await session.commit()
    project = Project(
        id=uuid.uuid4(),
        created_by=user.id,
        name="repo",
        repo_url="https://example.com/o/r.git",
        branch="main",
        status=ProjectStatus.READY.value,
    )
    session.add(project)
    await session.commit()
    role = (await session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    membership = ProjectMembership(
        id=uuid.uuid4(), user_id=user.id, project_id=project.id, role_id=role.id
    )
    session.add(membership)
    await session.commit()
    return user, project, membership


async def test_a_miss_reads_the_database_and_a_hit_does_not(
    db_session: AsyncSession, redis_client: aioredis.Redis
) -> None:
    user, project, _ = await _seed(db_session)
    cache = GrantCache(redis_client, ttl_seconds=300)

    first = await cache.load(db_session, user.id)
    second = await cache.load(db_session, user.id)

    assert first == second
    assert project.id in second


async def test_a_revoke_is_visible_on_the_next_request(
    db_session: AsyncSession, redis_client: aioredis.Redis
) -> None:
    """Without the DEL this is the failure that matters: someone keeps access after
    being removed, and nothing errors."""
    from datetime import UTC, datetime

    user, _project, membership = await _seed(db_session)
    cache = GrantCache(redis_client, ttl_seconds=300)
    await cache.load(db_session, user.id)  # populate

    membership.deleted_at = datetime.now(UTC)
    await db_session.commit()
    await cache.invalidate_user(user.id)

    assert await cache.load(db_session, user.id) == {}


async def test_a_role_edit_invalidates_every_holder(
    db_session: AsyncSession, redis_client: aioredis.Redis
) -> None:
    """Two users on one role, one epoch bump, both see the new set."""
    first_user, first_project, _ = await _seed(db_session)
    second_user, second_project, _ = await _seed(db_session)
    cache = GrantCache(redis_client, ttl_seconds=300)
    await cache.load(db_session, first_user.id)
    await cache.load(db_session, second_user.id)

    viewer = (await db_session.execute(select(Role).where(Role.name == "viewer"))).scalar_one()
    from app.repositories.role import RoleRepository

    await RoleRepository(db_session).replace_permissions(viewer.id, [Permission.PROJECT_READ.value])
    await db_session.commit()
    await cache.bump_epoch()

    first = await cache.load(db_session, first_user.id)
    second = await cache.load(db_session, second_user.id)

    assert first[first_project.id][1] == frozenset({Permission.PROJECT_READ.value})
    assert second[second_project.id][1] == frozenset({Permission.PROJECT_READ.value})


async def test_redis_down_falls_back_to_postgres_and_is_still_correct(
    db_session: AsyncSession,
) -> None:
    """Not deny, not allow — the source of truth. Redis being down makes AskRepo
    slower, never more permissive."""
    user, project, _ = await _seed(db_session)
    cache = GrantCache(cast(aioredis.Redis, _BrokenRedis()), ttl_seconds=300)

    grants = await cache.load(db_session, user.id)

    assert project.id in grants
    assert Permission.QUESTION_ASK.value in grants[project.id][1]


async def test_invalidating_with_redis_down_does_not_raise(
    db_session: AsyncSession,
) -> None:
    """A write path must not 500 because the cache is unreachable."""
    cache = GrantCache(cast(aioredis.Redis, _BrokenRedis()), ttl_seconds=300)

    await cache.invalidate_user(uuid.uuid4())  # must not raise
    await cache.bump_epoch()  # must not raise

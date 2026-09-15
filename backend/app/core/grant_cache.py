"""Redis read-through cache for the per-request grant snapshot.

This is the **second** reader of Redis. The first is `app/core/rate_limit.py`, and the
two have deliberately different failure behaviour — the difference is named here
because a future reader will otherwise get them backwards:

| Client            | On a Redis error         | Why                                       |
| ----------------- | ------------------------ | ----------------------------------------- |
| `rate_limit.py`   | skip the check           | Redis holds the only copy. Failing closed |
|                   |                          | would deny every login.                   |
| this module       | query Postgres instead   | Redis holds a copy, not the truth.        |

Neither fails closed by denying, and only one degrades by skipping a control. A
permission cache must never do that, and never has to: the authoritative answer is one
join away.

**Only grants are cached.** The user row is not — `docs/PRD.md:101` requires
deactivation to end sessions immediately, and the middleware reads that row on every
request to deliver it.

**Invalidation is two mechanisms, because the blast radii differ.** A membership change
affects one user: `DEL` their key. A role's permission set changing affects every
holder, which is not knowable from the write without a reverse lookup — so the epoch in
the key is bumped, making every existing key unreachable at once. That is atomic, has
no partial-failure mode, and cannot miss a user. Orphaned keys expire on their TTL.
"""

import json
import logging
import uuid
from functools import lru_cache

import redis.asyncio as aioredis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.repositories.membership import MembershipRepository

logger = logging.getLogger(__name__)

# Bumped when `ProjectGrant`'s serialized shape changes, so a rolling restart can
# never parse an old value into a new struct.
_SCHEMA = "v1"
_EPOCH_KEY = "askrepo:perm:epoch"


class GrantCache:
    """Read-through cache over `MembershipRepository.load_grants`."""

    def __init__(self, client: aioredis.Redis, *, ttl_seconds: int) -> None:
        self._client = client
        self._ttl = ttl_seconds

    async def load(
        self, session: AsyncSession, user_id: uuid.UUID
    ) -> dict[uuid.UUID, tuple[str, frozenset[str]]]:
        """This user's grants, from the cache if possible and Postgres otherwise."""
        key = await self._key_for(user_id)
        if key is not None:
            cached = await self._read(key)
            if cached is not None:
                return cached

        grants = await MembershipRepository(session).load_grants(user_id)
        if key is not None:
            await self._write(key, grants)
        return grants

    async def invalidate_user(self, user_id: uuid.UUID) -> None:
        """Drop one user's snapshot. Call **after** the transaction commits.

        Evicting before the commit can repopulate the cache with the pre-write value
        and leave it there for the whole TTL. Evicting after a rollback merely
        repopulates from unchanged state, which is harmless.
        """
        key = await self._key_for(user_id)
        if key is None:
            return
        try:
            await self._client.delete(key)
        except RedisError:
            logger.warning("grant cache eviction failed", extra={"user_id": str(user_id)})

    async def bump_epoch(self) -> None:
        """Invalidate every snapshot at once, for a role-definition change."""
        try:
            await self._client.incr(_EPOCH_KEY)
        except RedisError:
            logger.warning("grant cache epoch bump failed")

    async def _key_for(self, user_id: uuid.UUID) -> str | None:
        """`askrepo:perm:v1:{epoch}:user:{id}`, or None when Redis is unreachable."""
        try:
            epoch = await self._client.get(_EPOCH_KEY) or "0"
        except RedisError:
            logger.warning("grant cache unreachable; falling back to postgres")
            return None
        return f"askrepo:perm:{_SCHEMA}:{epoch}:user:{user_id}"

    async def _read(self, key: str) -> dict[uuid.UUID, tuple[str, frozenset[str]]] | None:
        try:
            raw = await self._client.get(key)
        except RedisError:
            return None
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("discarding unparseable grant cache entry", extra={"key": key})
            return None
        return {
            uuid.UUID(project_id): (entry["role"], frozenset(entry["permissions"]))
            for project_id, entry in payload.items()
        }

    async def _write(self, key: str, grants: dict[uuid.UUID, tuple[str, frozenset[str]]]) -> None:
        payload = {
            str(project_id): {"role": role, "permissions": sorted(permissions)}
            for project_id, (role, permissions) in grants.items()
        }
        try:
            await self._client.set(key, json.dumps(payload), ex=self._ttl)
        except RedisError:
            logger.warning("grant cache write failed", extra={"key": key})


@lru_cache
def get_grant_cache() -> GrantCache:
    """The process-wide cache, built once from settings.

    Reuses `rate_limit.get_redis()` rather than opening a second connection pool to
    the same server.
    """
    from app.core.rate_limit import get_redis

    return GrantCache(get_redis(), ttl_seconds=get_settings().grant_cache_ttl_seconds)

"""Redis fixed-window rate limiting for the credential-checking routes.

Applied per route by an explicit dependency, not as global middleware (D7):
`docs/PRD.md:115` specifies only a login limit, and `SECURITY.md:42` puts
authenticated-user resource exhaustion outside the threat model, so a blanket limiter
would guard against something the project has deliberately declined to defend.

Fails open when Redis is unreachable (D18). A Redis outage on a single-VPS deployment
is one the operator is already fixing; refusing every login in the meantime turns a
degraded control into an outage.
"""

import logging
import time
from functools import lru_cache
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import Depends, Request, status
from redis.exceptions import RedisError

from app.config import Settings, get_settings
from app.core.errors import AppError, ErrorCode

logger = logging.getLogger(__name__)


def _redact_email_from_key(key: str) -> str:
    """Return a diagnostic key with the email segment redacted."""
    if ":email:" not in key:
        return key
    parts = key.split(":")
    if len(parts) >= 4 and parts[2] == "email":
        if len(parts) > 4:
            return f"{parts[0]}:{parts[1]}:{parts[2]}:***:{parts[4]}"
        return f"{parts[0]}:{parts[1]}:{parts[2]}:***"
    return key


def client_ip(request: Request, *, trusted_proxy_hops: int) -> str:
    """The caller's address, accounting for reverse proxies.

    Counts from the **right** of `X-Forwarded-For`, discarding one entry per trusted
    hop. The header is client-controlled, so counting from the left would let anyone
    evade a per-IP limit by prepending a fake entry.

    `trusted_proxy_hops=0` ignores the header entirely and trusts the socket address.
    """
    peer = request.client.host if request.client else "unknown"
    if trusted_proxy_hops <= 0:
        return peer

    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return peer

    entries = [entry.strip() for entry in forwarded.split(",") if entry.strip()]
    index = len(entries) - trusted_proxy_hops
    if index < 0:
        # Fewer entries than configured hops: the chain is not what we were told to
        # expect, so trust the socket rather than a value we cannot place.
        logger.warning(
            "X-Forwarded-For has %d entries but %d proxy hops are configured",
            len(entries),
            trusted_proxy_hops,
        )
        return peer
    return entries[index]


class RateLimiter:
    """Fixed-window counters. One Redis key per (subject, window)."""

    def __init__(self, redis: aioredis.Redis) -> None:
        self.redis = redis

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> None:
        """Count one attempt against `key`; raise `AppError(429)` once over `limit`."""
        window = int(time.time()) // window_seconds
        windowed_key = f"{key}:{window}"
        try:
            async with self.redis.pipeline(transaction=True) as pipeline:
                pipeline.incr(windowed_key)
                pipeline.expire(windowed_key, window_seconds)
                count, _ = await pipeline.execute()
        except RedisError:
            logger.exception("Rate limiter unavailable; allowing %s", _redact_email_from_key(key))
            return

        if int(count) > limit:
            raise AppError(
                status.HTTP_429_TOO_MANY_REQUESTS,
                ErrorCode.RATE_LIMITED,
                "Too many attempts. Try again shortly.",
            )

    async def get_count(self, key: str, *, window_seconds: int) -> int:
        """Return the current count for a key and window, or 0 if unavailable."""
        window = int(time.time()) // window_seconds
        windowed_key = f"{key}:{window}"
        try:
            count = await self.redis.get(windowed_key)
        except RedisError:
            logger.exception(
                "Rate limiter unavailable; returning 0 for %s", _redact_email_from_key(key)
            )
            return 0
        return int(count) if count is not None else 0

    async def reset(self, key: str, *, window_seconds: int) -> None:
        """Drop the current window's counter for `key`."""
        window = int(time.time()) // window_seconds
        try:
            await self.redis.delete(f"{key}:{window}")
        except RedisError:
            logger.exception(
                "Rate limiter unavailable; could not reset %s", _redact_email_from_key(key)
            )


@lru_cache
def get_redis() -> aioredis.Redis:
    """The process-wide Redis client, built once from settings."""
    return aioredis.from_url(get_settings().redis_url, decode_responses=True)


def get_rate_limiter() -> RateLimiter:
    """FastAPI dependency providing the limiter."""
    return RateLimiter(get_redis())


RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


async def enforce_login_ip_limit(
    request: Request, limiter: RateLimiterDep, settings: SettingsDep
) -> None:
    """Per-IP limit on a credential-checking route.

    Counted before the credential check, so it also bounds attempts against addresses
    that do not exist — which is what makes it the enumeration-resistant half of the
    pair.
    """
    address = client_ip(request, trusted_proxy_hops=settings.trusted_proxy_hops)
    await limiter.hit(
        f"rl:login:ip:{address}", limit=settings.login_rate_per_minute_ip, window_seconds=60
    )


class LoginAttemptLimiter:
    """The per-email half of the login limit, counting failures only.

    A raw per-email counter is a lockout weapon: anyone who knows a colleague's address
    could spend ten bad guesses an hour to keep them out. Counting only failures — and
    clearing on success — does not remove that, but it stops legitimate logins from
    consuming the budget.
    """

    def __init__(self, limiter: RateLimiter, settings: Settings) -> None:
        self.limiter = limiter
        self.settings = settings

    def _key(self, email: str) -> str:
        return f"rl:login:email:{email.strip().lower()}"

    async def check_email(self, email: str) -> None:
        """Raise `429` if this address has already failed too many times this hour."""
        key = self._key(email)
        count = await self.limiter.get_count(key, window_seconds=3600)
        if count >= self.settings.login_rate_per_hour_email:
            raise AppError(
                status.HTTP_429_TOO_MANY_REQUESTS,
                ErrorCode.RATE_LIMITED,
                "Too many failed attempts for this account. Try again later.",
            )

    async def record_failure(self, email: str) -> None:
        """Count a failed attempt. Never raises — the caller is already returning 401."""
        try:
            await self.limiter.hit(
                self._key(email), limit=self.settings.login_rate_per_hour_email, window_seconds=3600
            )
        except AppError:
            # The limit is enforced by `check_email` on the next attempt; raising here
            # would turn a wrong password into a 429 and leak that the count is at its
            # ceiling for this address.
            return

    async def clear(self, email: str) -> None:
        """Reset the failure budget after a successful login."""
        await self.limiter.reset(self._key(email), window_seconds=3600)


def get_login_attempt_limiter(
    limiter: RateLimiterDep, settings: SettingsDep
) -> LoginAttemptLimiter:
    """FastAPI dependency providing the per-email limiter."""
    return LoginAttemptLimiter(limiter, settings)


LoginAttemptLimiterDep = Annotated[LoginAttemptLimiter, Depends(get_login_attempt_limiter)]

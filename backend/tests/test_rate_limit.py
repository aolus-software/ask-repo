"""Fixed-window rate limiting, and the two decisions that are easy to get wrong.

`client_ip` matters because Caddy sits in front of the API (docs/PRD.md:304): read
naively, every request looks like it came from the proxy and "5 per minute per IP"
silently becomes "5 per minute for the whole instance" — two colleagues mistyping a
password would lock everyone out.

Failing open when Redis is unreachable is deliberate (D18): a Redis outage should
degrade brute-force protection, not lock the team out of their own tool.
"""

import pytest
import redis.asyncio as aioredis
from fastapi import Request
from starlette.datastructures import Headers

from app.config import Settings
from app.core.errors import AppError
from app.core.rate_limit import LoginAttemptLimiter, RateLimiter, client_ip


def _request(*, peer: str, forwarded_for: str | None = None) -> Request:
    headers = {"x-forwarded-for": forwarded_for} if forwarded_for else {}
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "client": (peer, 12345),
        "headers": Headers(headers).raw,
    }
    return Request(scope)


def test_zero_hops_ignores_the_forwarded_header() -> None:
    """Trusting the header with no proxy in front lets a client forge its own IP."""
    request = _request(peer="10.0.0.5", forwarded_for="1.2.3.4")

    assert client_ip(request, trusted_proxy_hops=0) == "10.0.0.5"


def test_one_hop_takes_the_entry_left_of_the_proxy() -> None:
    request = _request(peer="10.0.0.5", forwarded_for="203.0.113.9")

    assert client_ip(request, trusted_proxy_hops=1) == "203.0.113.9"


def test_a_client_cannot_spoof_past_the_limit_by_prepending_entries() -> None:
    """Counting from the right is what makes the value untrustworthy-input-safe."""
    request = _request(peer="10.0.0.5", forwarded_for="9.9.9.9, 203.0.113.9")

    assert client_ip(request, trusted_proxy_hops=1) == "203.0.113.9"


def test_a_missing_header_falls_back_to_the_socket() -> None:
    request = _request(peer="10.0.0.5")

    assert client_ip(request, trusted_proxy_hops=1) == "10.0.0.5"


async def test_hits_under_the_limit_pass(redis_client: aioredis.Redis) -> None:
    limiter = RateLimiter(redis_client)

    for _ in range(3):
        await limiter.hit("test:key", limit=3, window_seconds=60)


async def test_the_hit_over_the_limit_is_429(redis_client: aioredis.Redis) -> None:
    limiter = RateLimiter(redis_client)
    for _ in range(3):
        await limiter.hit("test:key", limit=3, window_seconds=60)

    with pytest.raises(AppError) as caught:
        await limiter.hit("test:key", limit=3, window_seconds=60)

    assert caught.value.status_code == 429
    assert caught.value.code == "RATE_LIMITED"


async def test_separate_keys_have_separate_budgets(redis_client: aioredis.Redis) -> None:
    limiter = RateLimiter(redis_client)
    for _ in range(3):
        await limiter.hit("test:a", limit=3, window_seconds=60)

    await limiter.hit("test:b", limit=3, window_seconds=60)


async def test_the_counter_expires(redis_client: aioredis.Redis) -> None:
    """Without a TTL the first window would bound the key forever."""
    import time

    limiter = RateLimiter(redis_client)
    await limiter.hit("test:ttl", limit=3, window_seconds=60)

    window = int(time.time()) // 60
    assert await redis_client.ttl(f"test:ttl:{window}") > 0


async def test_reset_clears_the_budget(redis_client: aioredis.Redis) -> None:
    """A successful login clears the per-email failure counter."""
    limiter = RateLimiter(redis_client)
    for _ in range(3):
        await limiter.hit("test:reset", limit=3, window_seconds=60)

    await limiter.reset("test:reset", window_seconds=60)

    await limiter.hit("test:reset", limit=3, window_seconds=60)


async def test_an_unreachable_redis_fails_open() -> None:
    """D18: degrade the control rather than deny every login."""
    unreachable = aioredis.from_url("redis://127.0.0.1:6390/0", socket_connect_timeout=0.05)
    limiter = RateLimiter(unreachable)

    for _ in range(50):
        await limiter.hit("test:open", limit=1, window_seconds=60)

    await unreachable.aclose()


async def test_an_unreachable_redis_makes_reset_a_no_op() -> None:
    unreachable = aioredis.from_url("redis://127.0.0.1:6390/0", socket_connect_timeout=0.05)
    limiter = RateLimiter(unreachable)

    await limiter.reset("test:open", window_seconds=60)

    await unreachable.aclose()


async def test_login_attempt_limiter_check_email_passes_while_under_limit(
    redis_client: aioredis.Redis,
) -> None:
    """check_email does not raise when the count is below the limit."""
    settings = Settings(
        redis_url="redis://localhost:6379/15",
        login_rate_per_minute_ip=5,
        login_rate_per_hour_email=10,
        trusted_proxy_hops=0,
    )
    limiter = RateLimiter(redis_client)
    eal = LoginAttemptLimiter(limiter, settings)

    await eal.check_email("user@example.com")


async def test_login_attempt_limiter_record_failure_enforces_limit(
    redis_client: aioredis.Redis,
) -> None:
    """After recording enough failures, check_email raises 429."""
    settings = Settings(
        redis_url="redis://localhost:6379/15",
        login_rate_per_minute_ip=5,
        login_rate_per_hour_email=3,
        trusted_proxy_hops=0,
    )
    limiter = RateLimiter(redis_client)
    eal = LoginAttemptLimiter(limiter, settings)

    for _ in range(3):
        await eal.record_failure("user@example.com")

    with pytest.raises(AppError) as caught:
        await eal.check_email("user@example.com")

    assert caught.value.status_code == 429
    assert caught.value.code == "RATE_LIMITED"


async def test_login_attempt_limiter_clear_resets_counter(
    redis_client: aioredis.Redis,
) -> None:
    """clear() resets the failure counter so check_email passes again."""
    settings = Settings(
        redis_url="redis://localhost:6379/15",
        login_rate_per_minute_ip=5,
        login_rate_per_hour_email=3,
        trusted_proxy_hops=0,
    )
    limiter = RateLimiter(redis_client)
    eal = LoginAttemptLimiter(limiter, settings)

    for _ in range(3):
        await eal.record_failure("user@example.com")

    await eal.clear("user@example.com")

    await eal.check_email("user@example.com")


async def test_login_attempt_limiter_failures_per_email_isolated(
    redis_client: aioredis.Redis,
) -> None:
    """Failures for one email do not affect another email."""
    settings = Settings(
        redis_url="redis://localhost:6379/15",
        login_rate_per_minute_ip=5,
        login_rate_per_hour_email=2,
        trusted_proxy_hops=0,
    )
    limiter = RateLimiter(redis_client)
    eal = LoginAttemptLimiter(limiter, settings)

    for _ in range(2):
        await eal.record_failure("user1@example.com")

    await eal.check_email("user2@example.com")

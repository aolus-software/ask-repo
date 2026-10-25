"""What a failed job does to its row and to the retry ladder, once.

The checklist, mock-data and eval consumers each ended a failed run the same three ways: hand
the row back until a retry is due (`defer_for_retry`), record a terminal failure
(`record_failure`), and publish the next attempt (`route_failure`). Only what differs is a
parameter here -- the row's repository calls, the ladder's `*_next_destination`, the message
that is re-published, and whether a recorded failure announces itself. Each consumer keeps
thin `_defer` / `_fail` / `_route_failure` wrappers that name those choices, so the
differences stay visible at the call site (`.claude/rules/ingestion.md`).

Which failure calls which of these -- a terminal error fails and dead-letters, a retryable one
with the ladder spent fails and dead-letters, a retryable one with rungs left only defers and
re-routes, and a retried failure writes no status and announces nothing -- is decided by each
handler, not here.
"""

import time
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.queue.protocol import TopicProducer
from app.queue.topics import JobMessage

NextDestination = Callable[..., tuple[str, int]]


async def defer_for_retry(
    *,
    session: AsyncSession,
    defer: Callable[[int], Awaitable[bool]],
    next_destination: NextDestination,
    attempt: int,
    max_attempts: int,
) -> None:
    """Shorten the row's lease to the delay of the rung this failure routes to.

    The delay is read from the same `next_destination` that picks the topic in
    `route_failure`, so the lease cannot expire at a different moment from the one the retry
    arrives at. The rollback comes first: whatever the failed run left in this session is not
    wanted, and only the lease write survives. `defer` returns whether we still held the lease.
    """
    _, delay_seconds = next_destination(attempt=attempt, max_attempts=max_attempts)
    await session.rollback()
    if await defer(delay_seconds):
        await session.commit()
    else:
        await session.rollback()


async def record_failure(
    *,
    session: AsyncSession,
    release: Callable[[], Awaitable[bool]],
    announce: Callable[[], Awaitable[None]] | None = None,
    rollback_first: bool = False,
) -> None:
    """Record a terminal failure by releasing the row `failed`, then commit.

    `release` returns whether we still held the lease; `False` means another worker owns the
    row and this run has no right to record itself, so nothing is committed. `announce`, when
    given, runs inside the same transaction and only for a failure that was recorded.
    `rollback_first` drops what the failed run left in the session before the release.
    """
    if rollback_first:
        await session.rollback()
    if await release():
        if announce is not None:
            # Before the commit, like every fan-out: the `failed` status and the
            # notification of it are one transaction.
            await announce()
        await session.commit()
    else:
        await session.rollback()


async def route_failure(
    *,
    producer: TopicProducer,
    attempt: int,
    max_attempts: int,
    next_destination: NextDestination,
    build_message: Callable[[uuid.UUID, int, int], JobMessage],
) -> None:
    """Publish the next attempt: a delay rung, or the dead-letter topic.

    A fresh `job_id` on every attempt, because each repository's `claim` refuses a job id it
    has already recorded -- reusing it would make the retry a no-op that looks like a success.
    `build_message(job_id, attempt, not_before_ms)` returns the kind's own message.
    """
    topic, delay_seconds = next_destination(attempt=attempt, max_attempts=max_attempts)
    await producer.produce_to(
        topic,
        build_message(uuid.uuid4(), attempt + 1, int(time.time() * 1000) + delay_seconds * 1000),
    )

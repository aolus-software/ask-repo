"""The lease heartbeat every long job runs beside its work.

A job runs for minutes and its lease for five, so a background task renews the lease
every sixty seconds (`app/repositories/lease.py`). The ingestion pipeline and the four
generation/eval runners each carried their own copy of the loop and of the "cancel it
and collect it" teardown; both live here once.

Each tick uses its own short-lived session, never the one the job is running on: an
`AsyncSession` is not safe for concurrent use, and two coroutines interleaving on one
connection fail with an `InterfaceError` or, worse, a mis-scoped transaction.
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_sessionmaker

logger = logging.getLogger(__name__)


async def renew_until_lost(
    renew: Callable[[AsyncSession], Awaitable[bool]],
    *,
    interval_seconds: float,
    subject: str,
) -> None:
    """Renew the lease every `interval_seconds` until a renewal reports it was lost.

    `renew` is handed a fresh session each tick and returns whether we still hold the
    lease. Returning (rather than raising) on a loss is the signal: the task finishes,
    and the job's own checks (`task.done()`) notice and stop spending work it cannot
    record. `subject` names the row for the log, e.g. `"project <id>"`.
    """
    while True:
        await asyncio.sleep(interval_seconds)
        async with get_sessionmaker()() as session:
            held = await renew(session)
            await session.commit()
        if not held:
            logger.warning("lost the lease on %s mid-run", subject)
            return


async def stop_heartbeat(task: asyncio.Task[None], *, subject: str) -> None:
    """Cancel the heartbeat and collect it, so nothing fails silently.

    A bare `.cancel()` with no `await` leaves any non-`CancelledError` failure --
    including one from the heartbeat's own session teardown -- unretrieved, and it
    surfaces later as an unrelated "Task exception was never retrieved" warning instead
    of here, where it is attributable to this run. The job's outcome is already decided
    by now, so a failed renewal is logged and cannot change it.
    """
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        try:
            await task
        except Exception:
            logger.warning("lease renewal for %s failed", subject, exc_info=True)


@asynccontextmanager
async def lease_heartbeat(
    renewal: Coroutine[Any, Any, None], *, subject: str
) -> AsyncIterator[asyncio.Task[None]]:
    """Run `renewal` as a background task for the length of the block, then stop it.

    Yields the task so the job can check `task.done()` -- the heartbeat only finishes
    early when the lease was lost.
    """
    task = asyncio.create_task(renewal)
    try:
        yield task
    finally:
        await stop_heartbeat(task, subject=subject)

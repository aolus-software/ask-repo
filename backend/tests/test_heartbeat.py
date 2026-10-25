"""The shared lease heartbeat: it stops on a lost lease and is always collected."""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.queue.heartbeat import lease_heartbeat, renew_until_lost


async def test_the_heartbeat_finishes_when_a_renewal_reports_the_lease_lost(
    db_session: AsyncSession,
) -> None:
    ticks: list[int] = []

    async def renew(session: AsyncSession) -> bool:
        ticks.append(1)
        return len(ticks) < 3

    await asyncio.wait_for(
        renew_until_lost(renew, interval_seconds=0.01, subject="row x"), timeout=5
    )

    assert len(ticks) == 3


async def test_the_context_manager_cancels_and_collects_a_running_heartbeat() -> None:
    async def forever() -> None:
        await asyncio.sleep(60)

    async with lease_heartbeat(forever(), subject="row x") as task:
        assert not task.done()

    assert task.cancelled()


async def test_a_failing_heartbeat_is_logged_not_raised() -> None:
    async def boom() -> None:
        raise RuntimeError("renewal broke")

    async with lease_heartbeat(boom(), subject="row x") as task:
        await asyncio.sleep(0.01)
        assert task.done()

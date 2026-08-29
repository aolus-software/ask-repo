"""Shared test doubles for the Kafka consumer loops.

`IngestionConsumer` and `RetryConsumer` are the same shape — poll, pause everything,
do the slow thing, commit one partition, resume — so they need the same stand-in. One
copy, because the pause/commit rules encoded here are the subtle part: a second copy
is a second thing to get wrong, and a divergence between them would be invisible.
"""

import asyncio
from collections.abc import Awaitable, Callable
from types import SimpleNamespace

from aiokafka import ConsumerRebalanceListener, TopicPartition
from aiokafka.errors import IllegalStateError

from app.queue.topics import IngestionMessage


class FakeConsumer:
    """An `AIOKafkaConsumer` stand-in with aiokafka 0.14's real pause/commit rules.

    The rules that matter, all confirmed against the installed client during the Task
    17 review: `resume` and `commit` raise `IllegalStateError` for a partition that is
    no longer assigned, and a rebalance rebuilds per-partition state **un-paused**, so
    a pause does not survive one.
    """

    def __init__(
        self,
        assigned: set[TopicPartition],
        *,
        on_poll: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._assigned = set(assigned)
        self._paused: set[TopicPartition] = set()
        self.listener: ConsumerRebalanceListener | None = None
        self.committed: list[dict[TopicPartition, int]] = []
        self.keep_alive_polls = 0
        self.delivered_during_job: list[TopicPartition] = []
        # Lets a test act in the middle of a hold — a rebalance, say — at the one
        # moment a real broker could interrupt: while the loop is parked in a poll.
        self._on_poll = on_poll

    def subscribe(self, *, topics: list[str], listener: ConsumerRebalanceListener) -> None:
        self.listener = listener

    def assignment(self) -> set[TopicPartition]:
        return set(self._assigned)

    def pause(self, *partitions: TopicPartition) -> None:
        for partition in partitions:
            if partition not in self._assigned:
                raise IllegalStateError(f"No current assignment for partition {partition}")
            self._paused.add(partition)

    def resume(self, *partitions: TopicPartition) -> None:
        for partition in partitions:
            if partition not in self._assigned:
                raise IllegalStateError(f"No current assignment for partition {partition}")
            self._paused.discard(partition)

    async def rebalance_to(self, assigned: set[TopicPartition]) -> None:
        """What the broker does mid-job: new assignment, all of it un-paused.

        The listener callback is awaited as part of the rebalance, before any fetch
        can happen — which is the whole reason it is the right place to re-pause.
        """
        self._assigned = set(assigned)
        self._paused = set()
        if self.listener is not None:
            await self.listener.on_partitions_assigned(sorted(self._assigned))

    async def getmany(
        self, *, timeout_ms: int, max_records: int | None = None
    ) -> dict[TopicPartition, list[object]]:
        """Records arrive only from partitions that are assigned and not paused.

        Yields to the event loop the way a real poll does — without that the
        keep-alive loop spins and the job task is never scheduled.
        """
        await asyncio.sleep(0)
        self.keep_alive_polls += 1
        if self._on_poll is not None:
            await self._on_poll()
        live = self._assigned - self._paused
        self.delivered_during_job.extend(live)
        return {}

    async def commit(self, offsets: dict[TopicPartition, int]) -> None:
        for partition in offsets:
            if partition not in self._assigned:
                raise IllegalStateError(f"Partition {partition} is not assigned")
        self.committed.append(offsets)


def record_for(message: IngestionMessage, *, offset: int = 7) -> SimpleNamespace:
    """A `ConsumerRecord` stand-in carrying a serialised message."""
    return SimpleNamespace(value=message.to_bytes(), offset=offset)

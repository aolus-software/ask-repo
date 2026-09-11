"""Consuming checklist generation jobs.

Structurally identical to `app/queue/consumer.py`'s ingestion half, and deliberately so:
the same lease-is-the-boundary rule, the same failure classification, the same
pause-and-keep-poll loop inherited from `PausingConsumer`. What differs is the row that
is claimed and the ladder a failure is routed onto.
"""

import logging
import time
import uuid
from collections.abc import Callable
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Re-exported explicitly (`as` names): `strict = true` in pyproject.toml's `[tool.mypy]`
# turns on `no_implicit_reexport`, and both names are imported here only to be used by
# this module's own callers and by tests, exactly the way `app/queue/consumer.py`
# itself is a leaf module for `JobOutcome`.
from app.config import Settings
from app.core.crypto import scrub as scrub
from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError
from app.models.checklist import ChecklistModuleStatus
from app.queue.consumer import JobOutcome as JobOutcome
from app.queue.consumer import PausingConsumer
from app.queue.producer import ensure_topics
from app.queue.protocol import TopicProducer
from app.queue.topics import (
    ALL_CHECKLIST_TOPICS,
    ChecklistJobMessage,
    checklist_next_destination,
    checklist_retries_exhausted,
)
from app.rag.errors import RetryableChatError, TerminalChatError
from app.repositories.checklist_module import LEASE_SECONDS, ChecklistModuleRepository

logger = logging.getLogger(__name__)


class GenerationRunner(Protocol):
    """The unit of work a checklist message triggers.

    A `Protocol` rather than the concrete `ChecklistGenerator`, matching
    `app/queue/consumer.py`'s `Pipeline` -- so `handle_checklist_message` is testable
    with a plain stub instead of a real generator wired to a chat model and a vector
    store.
    """

    async def run(self, *, module_id: uuid.UUID, job_id: uuid.UUID, worker_id: str) -> None:
        """Generate one module's proposed change set."""
        ...


GeneratorFactory = Callable[[AsyncSession], GenerationRunner]


async def handle_checklist_message(
    message: ChecklistJobMessage,
    *,
    generator: GenerationRunner,
    repository: ChecklistModuleRepository,
    producer: TopicProducer,
    worker_id: str,
    max_attempts: int,
    session: AsyncSession,
) -> JobOutcome:
    """Run one generation. Every returned value means "commit the offset".

    The claim -- not the offset -- is what stops two workers generating the same
    module. A refused claim is the *expected* cost of a duplicate delivery, so it
    returns `SKIPPED` rather than raising.
    """
    if not await repository.claim(
        module_id=message.module_id,
        job_id=message.job_id,
        worker_id=worker_id,
        lease_seconds=LEASE_SECONDS,
    ):
        await session.commit()
        logger.info("checklist module %s is already claimed; skipping", message.module_id)
        return JobOutcome.SKIPPED
    await session.commit()

    try:
        await generator.run(module_id=message.module_id, job_id=message.job_id, worker_id=worker_id)
    except (TerminalIngestionError, TerminalChatError) as error:
        # `module.error` is read back by every authenticated user on this shared
        # instance (`app/schemas/checklist.py`'s `ChecklistModuleResponse.error`), and
        # a `TerminalIngestionError`'s text can originate from anywhere downstream,
        # including a project row whose clone URL carries a PAT. This layer holds no
        # PAT and so cannot scrub one out of an arbitrary message -- per
        # `.claude/rules/ingestion.md`'s rule for exactly this position ("the
        # consumer, for instance"), only the exception's class name is recorded on
        # the row; the full text goes to the log only. `scrub` is still run over the
        # class name -- a no-op today -- so the shape of a scrub point on this path
        # survives for a later change that starts passing a real secret through it.
        logger.warning(
            "checklist generation for module %s failed terminally: %s",
            message.module_id,
            error,
        )
        await _fail(
            message,
            repository=repository,
            worker_id=worker_id,
            reason=scrub(f"generation failed: {type(error).__name__}."),
            session=session,
        )
        await _route_failure(message, producer=producer, max_attempts=0)
        return JobOutcome.DEAD_LETTERED
    except (RetryableIngestionError, RetryableChatError) as error:
        if checklist_retries_exhausted(attempt=message.attempt, max_attempts=max_attempts):
            # The ladder is spent, so this job is *not* coming back and `_defer` would
            # be a lie. It leaves the module `generating` with no lease, which is
            # exactly the shape `ChecklistModuleRepository.claim_stranded` reads as an
            # abandoned run -- so the 60-second sweep re-publishes it with a fresh
            # `job_id` the claim is designed not to refuse, and a job that has already
            # exhausted its retries costs a whole generation again on every tick,
            # forever. `app/queue/consumer.py` records the ingestion outcome at the
            # same point, for the same reason.
            logger.warning(
                "checklist generation for module %s exhausted its retries: %s",
                message.module_id,
                type(error).__name__,
            )
            await _fail(
                message,
                repository=repository,
                worker_id=worker_id,
                reason=scrub(
                    f"generation failed after {message.attempt + 1} attempts: "
                    f"{type(error).__name__}."
                ),
                session=session,
            )
            await _route_failure(message, producer=producer, max_attempts=max_attempts)
            return JobOutcome.DEAD_LETTERED
        # No status write: the job is coming back, and `failed` would lie about it.
        # The lease still goes, though -- see `_defer`.
        await _defer(
            message,
            repository=repository,
            worker_id=worker_id,
            session=session,
            max_attempts=max_attempts,
        )
        logger.warning(
            "checklist generation for module %s failed retryably: %s",
            message.module_id,
            type(error).__name__,
        )
        await _route_failure(message, producer=producer, max_attempts=max_attempts)
        return JobOutcome.RETRY_SCHEDULED
    except Exception as error:
        # Unclassified: retried exactly once, then dead-lettered, so a bug neither
        # silently eats jobs nor loops forever. Reaching this means a failure mode
        # nobody classified, and the fix is to classify it rather than widen the net.
        logger.exception("unclassified failure generating module %s", message.module_id)
        if message.attempt >= 1:
            await _fail(
                message,
                repository=repository,
                worker_id=worker_id,
                reason=f"generation failed with an unexpected {type(error).__name__}.",
                session=session,
            )
            await _route_failure(message, producer=producer, max_attempts=0)
            return JobOutcome.DEAD_LETTERED
        await _defer(
            message,
            repository=repository,
            worker_id=worker_id,
            session=session,
            max_attempts=max_attempts,
        )
        await _route_failure(message, producer=producer, max_attempts=max_attempts)
        return JobOutcome.RETRY_SCHEDULED

    return JobOutcome.COMPLETED


async def _defer(
    message: ChecklistJobMessage,
    *,
    repository: ChecklistModuleRepository,
    worker_id: str,
    session: AsyncSession,
    max_attempts: int,
) -> None:
    """Hand back a run that ended but is coming back, until its retry is due.

    The lease is shortened to the delay of the rung this failure routes to, rather than
    dropped: a `generating` module with no lease is what the stranded sweep reads as
    abandoned, and it waits two minutes while the second rung waits ten. See
    `ChecklistModuleRepository.defer`.

    The delay is read from `checklist_next_destination` -- the same function that picks
    the topic in `_route_failure` -- so the lease cannot expire at a different moment
    from the one the retry actually arrives at.

    The rollback still happens first: whatever the failed run left in this session is
    not wanted, and only the lease write should survive.
    """
    _, delay_seconds = checklist_next_destination(
        attempt=message.attempt, max_attempts=max_attempts
    )
    await session.rollback()
    if await repository.defer(
        module_id=message.module_id, worker_id=worker_id, hold_seconds=delay_seconds
    ):
        await session.commit()
    else:
        await session.rollback()


async def _fail(
    message: ChecklistJobMessage,
    *,
    repository: ChecklistModuleRepository,
    worker_id: str,
    reason: str,
    session: AsyncSession,
) -> None:
    """Record a terminal failure on the module, scrubbed, and drop the lease.

    `release` returns whether we still held the lease; a `False` means another worker
    owns the module and this run has no right to record itself.
    """
    if await repository.release(
        module_id=message.module_id,
        job_id=message.job_id,
        worker_id=worker_id,
        status=ChecklistModuleStatus.FAILED,
        error=reason,
    ):
        await session.commit()
    else:
        await session.rollback()


async def _route_failure(
    message: ChecklistJobMessage, *, producer: TopicProducer, max_attempts: int
) -> None:
    """Send the job onward: a delay rung, or the checklist dead-letter topic.

    A fresh `job_id` on every attempt, because `ChecklistModuleRepository.claim`
    refuses a job id it has already recorded -- reusing it would make the retry a
    no-op that looks like a success.
    """
    topic, delay_seconds = checklist_next_destination(
        attempt=message.attempt, max_attempts=max_attempts
    )
    await producer.produce_to(
        topic,
        ChecklistJobMessage(
            module_id=message.module_id,
            job_id=uuid.uuid4(),
            attempt=message.attempt + 1,
            not_before_ms=int(time.time() * 1000) + delay_seconds * 1000,
            original_topic=message.original_topic,
        ),
    )


class ChecklistConsumer(PausingConsumer[ChecklistJobMessage]):
    """The generation polling loop for one worker.

    A generation over a large module can outlast `max.poll.interval.ms` for exactly the
    reason an index can, so it inherits the pause-and-keep-polling loop rather than
    raising the interval -- which is the substitute `.claude/rules/ingestion.md` rejects.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        sessionmaker: async_sessionmaker[AsyncSession],
        producer: TopicProducer,
        build_generator: GeneratorFactory,
        worker_id: str,
    ) -> None:
        self.settings = settings
        self.sessionmaker = sessionmaker
        self.producer = producer
        self.build_generator = build_generator
        self.worker_id = worker_id
        self.topic = settings.kafka_checklist_topic
        # Its own group: sharing ingestion's would drag both into one rebalance and
        # give a generation's pause the power to stall an index.
        self.group_id = f"{settings.kafka_consumer_group}-checklist"
        self._job_in_flight = False

    def _decode(self, raw: bytes) -> ChecklistJobMessage:
        return ChecklistJobMessage.from_bytes(raw)

    async def _ensure_topics(self) -> None:
        """Idempotent, which is what makes calling it here and in the API correct."""
        await ensure_topics(
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            partitions=self.settings.kafka_checklist_partitions,
            topics=ALL_CHECKLIST_TOPICS,
        )

    async def _run_job(self, message: ChecklistJobMessage) -> JobOutcome:
        """One generation, in its own session."""
        async with self.sessionmaker() as session:
            return await handle_checklist_message(
                message,
                generator=self.build_generator(session),
                repository=ChecklistModuleRepository(session),
                producer=self.producer,
                worker_id=self.worker_id,
                max_attempts=self.settings.kafka_max_attempts,
                session=session,
            )

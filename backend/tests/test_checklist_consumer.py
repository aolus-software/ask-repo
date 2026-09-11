"""One generation message, end to end, with no broker."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError
from app.models.checklist import ChecklistModuleStatus
from app.queue.checklist import JobOutcome, handle_checklist_message
from app.queue.protocol import InMemoryIngestionQueue
from app.queue.topics import CHECKLIST_DLQ_TOPIC, CHECKLIST_TOPIC, ChecklistJobMessage
from app.rag.errors import RetryableChatError, TerminalChatError
from app.repositories.checklist_module import ChecklistModuleRepository
from tests.factories import create_checklist_item, create_checklist_module


class _Generator:
    """A generator that records its calls and optionally raises."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[uuid.UUID] = []

    async def run(self, *, module_id: uuid.UUID, job_id: uuid.UUID, worker_id: str) -> None:
        self.calls.append(module_id)
        if self.error is not None:
            raise self.error


def _message(module_id: uuid.UUID, *, attempt: int = 0) -> ChecklistJobMessage:
    return ChecklistJobMessage(
        module_id=module_id,
        job_id=uuid.uuid4(),
        attempt=attempt,
        not_before_ms=0,
        original_topic=CHECKLIST_TOPIC,
    )


async def test_a_claimed_message_runs_the_generator(db_session: AsyncSession) -> None:
    module = await create_checklist_module(db_session)
    generator = _Generator()

    outcome = await handle_checklist_message(
        _message(module.id),
        generator=generator,
        repository=ChecklistModuleRepository(db_session),
        producer=InMemoryIngestionQueue(),
        worker_id="w1",
        max_attempts=3,
        session=db_session,
    )

    assert outcome is JobOutcome.COMPLETED
    assert generator.calls == [module.id]


async def test_a_duplicate_delivery_costs_one_refused_claim(
    db_session: AsyncSession,
) -> None:
    """Kafka is at-least-once, so a duplicate must be cheap -- one refused claim, not
    a second generation (spec 4.5)."""
    module = await create_checklist_module(db_session)
    message = _message(module.id)
    generator = _Generator()
    repository = ChecklistModuleRepository(db_session)

    for _ in range(2):
        await handle_checklist_message(
            message,
            generator=generator,
            repository=repository,
            producer=InMemoryIngestionQueue(),
            worker_id="w1",
            max_attempts=3,
            session=db_session,
        )

    assert generator.calls == [module.id]


async def test_a_retryable_failure_goes_to_the_ladder_and_leaves_status_alone(
    db_session: AsyncSession,
) -> None:
    """The job is coming back, so a `failed` status would lie about it
    (`.claude/rules/ingestion.md`). Asserting equality against `GENERATING`, not just
    `!= FAILED`: the claim set `GENERATING`, and "left alone" means the retryable
    failure rolled back without touching it -- a `!=` check would also pass if the
    status were corrupted to anything else that isn't `FAILED`, including the factory
    default `EMPTY`."""
    module = await create_checklist_module(db_session)
    queue = InMemoryIngestionQueue()

    await handle_checklist_message(
        _message(module.id),
        generator=_Generator(RetryableIngestionError("embedder blipped")),
        repository=ChecklistModuleRepository(db_session),
        producer=queue,
        worker_id="w1",
        max_attempts=3,
        session=db_session,
    )

    assert queue.produced[0][0].startswith("askrepo.checklist.retry")
    await db_session.refresh(module)
    assert module.status == ChecklistModuleStatus.GENERATING.value


async def test_a_retryable_failure_on_the_last_attempt_records_the_module_failed(
    db_session: AsyncSession,
) -> None:
    """The regression that made a stuck generation look merely slow.

    The test above covers a retryable failure with rungs left, where leaving `status`
    at `generating` is correct. On the *last* attempt the job goes to the dead-letter
    topic instead, and deferring there leaves the module `generating` with no lease --
    exactly what `claim_stranded` reads as an abandoned run. The 60-second sweep then
    re-publishes it with a fresh `job_id` the claim cannot refuse, so a job that has
    already spent its retries costs a whole generation again every tick, forever.

    Asserting `FAILED` *and* the dead-letter topic together: recording the status while
    still routing to a retry rung would retry a module already marked failed, and
    routing to the DLQ without recording it is the original bug.
    """
    module = await create_checklist_module(db_session)
    queue = InMemoryIngestionQueue()

    outcome = await handle_checklist_message(
        # attempt 2 of max_attempts=3 is the last one: the ladder is spent.
        _message(module.id, attempt=2),
        generator=_Generator(RetryableChatError("provider timed out")),
        repository=ChecklistModuleRepository(db_session),
        producer=queue,
        worker_id="w1",
        max_attempts=3,
        session=db_session,
    )

    assert outcome is JobOutcome.DEAD_LETTERED
    assert queue.produced[0][0] == CHECKLIST_DLQ_TOPIC
    await db_session.refresh(module)
    assert module.status == ChecklistModuleStatus.FAILED.value
    # The reason names the class and the attempt count, and no exception text: the
    # column is read back by every user on the instance.
    assert module.error is not None
    assert "RetryableChatError" in module.error
    assert "provider timed out" not in module.error
    # No lease left behind, or the module is untouchable until it lapses.
    assert module.lease_expires_at is None


async def test_a_module_that_dead_letters_stops_matching_the_stranded_sweep(
    db_session: AsyncSession,
) -> None:
    """The property the fix actually buys, asserted through the sweep's own query.

    `claim_stranded` is what the 60-second reconcile tick calls. A module left
    `generating` with no lease matches it and gets re-published; one recorded `failed`
    does not. Testing through the repository rather than the status column proves the
    loop is closed rather than that a string changed.
    """
    module = await create_checklist_module(db_session)
    repository = ChecklistModuleRepository(db_session)

    await handle_checklist_message(
        _message(module.id, attempt=2),
        generator=_Generator(RetryableChatError("provider timed out")),
        repository=repository,
        producer=InMemoryIngestionQueue(),
        worker_id="w1",
        max_attempts=3,
        session=db_session,
    )

    stranded = await repository.claim_stranded(generating_older_than_seconds=0)
    assert module.id not in stranded


async def test_a_terminal_failure_records_only_the_exception_class(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """`module.error` is read by every authenticated user via `ChecklistModuleResponse`,
    so it must never carry an exception message: a `TerminalIngestionError` raised
    downstream can quote a clone URL with a PAT in it.
    `.claude/rules/ingestion.md` requires this layer to record the exception's CLASS NAME
    and let the text go only to the log, because a consumer holds no PAT and so cannot
    scrub one out of an arbitrary message.

    Asserting equality, not `"ghp_secret" not in ...`: the substring check passes for any
    string that happens to lack that literal, including one built from a different secret.
    """
    module = await create_checklist_module(db_session)
    queue = InMemoryIngestionQueue()
    secret_url = "https://x:ghp_secret@github.com/acme/repo.git"

    with caplog.at_level(logging.WARNING):
        await handle_checklist_message(
            _message(module.id),
            generator=_Generator(TerminalIngestionError(f"clone failed for {secret_url}")),
            repository=ChecklistModuleRepository(db_session),
            producer=queue,
            worker_id="w1",
            max_attempts=3,
            session=db_session,
        )

    await db_session.refresh(module)
    assert module.status == ChecklistModuleStatus.FAILED.value
    # Equality, so any leak of the message -- not just this one secret -- fails.
    assert module.error == "generation failed: TerminalIngestionError."
    assert queue.produced[0][0] == CHECKLIST_DLQ_TOPIC
    # The other half of the rule's trade: the full text still reaches an operator,
    # just not the row every authenticated user can read.
    assert secret_url in caplog.text


async def test_a_failed_generation_leaves_existing_items_untouched(
    db_session: AsyncSession,
) -> None:
    """Generation only ever proposes; a run that dies before writing its change set
    has changed nothing (spec 4.7)."""
    module = await create_checklist_module(db_session)
    item = await create_checklist_item(
        db_session,
        module_id=module.id,
        project_id=module.project_id,
        created_by=module.created_by,
        current_result="Observed 401",
    )

    await handle_checklist_message(
        _message(module.id),
        generator=_Generator(TerminalIngestionError("boom")),
        repository=ChecklistModuleRepository(db_session),
        producer=InMemoryIngestionQueue(),
        worker_id="w1",
        max_attempts=3,
        session=db_session,
    )

    await db_session.refresh(item)
    assert item.current_result == "Observed 401"
    assert item.deleted_at is None


async def test_a_retryable_failure_releases_the_lease_for_its_own_retry(
    db_session: AsyncSession,
) -> None:
    """The lease is shortened to the retry's due moment -- not held, and not dropped.

    Both neighbouring answers are wrong, and each caused a real defect.

    Holding the full five minutes means the retry that lands a minute later is refused
    by its own dead predecessor. Dropping the lease to `NULL` means the module sits
    `generating` with nobody on it, which is precisely what `claim_stranded` reads as
    abandoned -- so across the ten-minute rung the two-minute sweep publishes a second
    job for one already scheduled, and the same module generates twice at once.
    """
    module = await create_checklist_module(db_session)
    repository = ChecklistModuleRepository(db_session)

    await handle_checklist_message(
        _message(module.id),
        generator=_Generator(RetryableIngestionError("embedder blipped")),
        repository=repository,
        producer=InMemoryIngestionQueue(),
        worker_id="w1",
        max_attempts=3,
        session=db_session,
    )

    await db_session.refresh(module)
    assert module.status == ChecklistModuleStatus.GENERATING.value
    # Held to the first rung's 60 seconds, so well short of the 5-minute claim lease.
    assert module.lease_expires_at is not None
    held_for = (module.lease_expires_at - datetime.now(UTC)).total_seconds()
    assert 0 < held_for <= 60
    # And therefore invisible to the sweep, which is the failure that was biting.
    assert module.id not in await repository.claim_stranded(generating_older_than_seconds=0)

    # Once the retry is actually due, nothing blocks it from claiming.
    module.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.flush()
    assert await repository.claim(
        module_id=module.id, job_id=uuid.uuid4(), worker_id="w1", lease_seconds=300
    )


async def test_an_unclassified_first_failure_releases_the_lease_too(
    db_session: AsyncSession,
) -> None:
    """Same reasoning as the retryable path: attempt 0 is coming back, so it defers
    rather than failing, and a deferred run holds its lease only until the retry is
    due -- long enough that the stranded sweep leaves it alone in the meantime."""
    module = await create_checklist_module(db_session)
    repository = ChecklistModuleRepository(db_session)

    outcome = await handle_checklist_message(
        _message(module.id, attempt=0),
        generator=_Generator(RuntimeError("ollama fell over")),
        repository=repository,
        producer=InMemoryIngestionQueue(),
        worker_id="w1",
        max_attempts=3,
        session=db_session,
    )

    assert outcome is JobOutcome.RETRY_SCHEDULED
    await db_session.refresh(module)
    assert module.status == ChecklistModuleStatus.GENERATING.value
    assert module.lease_expires_at is not None
    assert (module.lease_expires_at - datetime.now(UTC)).total_seconds() <= 60
    assert module.id not in await repository.claim_stranded(generating_older_than_seconds=0)


async def test_a_retryable_chat_failure_goes_to_the_ladder_too(
    db_session: AsyncSession,
) -> None:
    """`RetryableChatError` must be routed exactly like `RetryableIngestionError` --
    the taxonomy is separate (M4.5 spec 2.1) but the dispatch is shared."""
    module = await create_checklist_module(db_session)
    queue = InMemoryIngestionQueue()

    await handle_checklist_message(
        _message(module.id),
        generator=_Generator(RetryableChatError("rate limited")),
        repository=ChecklistModuleRepository(db_session),
        producer=queue,
        worker_id="w1",
        max_attempts=3,
        session=db_session,
    )

    assert queue.produced[0][0].startswith("askrepo.checklist.retry")
    await db_session.refresh(module)
    assert module.status == ChecklistModuleStatus.GENERATING.value


async def test_a_terminal_chat_failure_dead_letters_too(
    db_session: AsyncSession,
) -> None:
    """`TerminalChatError` must be routed exactly like `TerminalIngestionError`."""
    module = await create_checklist_module(db_session)
    queue = InMemoryIngestionQueue()

    await handle_checklist_message(
        _message(module.id),
        generator=_Generator(TerminalChatError("unknown model")),
        repository=ChecklistModuleRepository(db_session),
        producer=queue,
        worker_id="w1",
        max_attempts=3,
        session=db_session,
    )

    await db_session.refresh(module)
    assert module.status == ChecklistModuleStatus.FAILED.value
    assert module.error == "generation failed: TerminalChatError."
    assert queue.produced[0][0] == CHECKLIST_DLQ_TOPIC

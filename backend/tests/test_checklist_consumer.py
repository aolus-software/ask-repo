"""One generation message, end to end, with no broker."""

import logging
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError
from app.models.checklist import ChecklistModuleStatus
from app.queue.checklist import JobOutcome, handle_checklist_message
from app.queue.protocol import InMemoryIngestionQueue
from app.queue.topics import CHECKLIST_DLQ_TOPIC, CHECKLIST_TOPIC, ChecklistJobMessage
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

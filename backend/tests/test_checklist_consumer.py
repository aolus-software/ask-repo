"""One generation message, end to end, with no broker."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError
from app.models.checklist import ChecklistModuleStatus
from app.queue import checklist as checklist_module
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
    (`.claude/rules/ingestion.md`)."""
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
    assert module.status != ChecklistModuleStatus.FAILED.value


async def test_a_terminal_failure_records_a_scrubbed_error(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A PAT can reach an exception message through the clone URL on the project row,
    and `module.error` is read back by every authenticated user on this shared
    instance -- so a `TerminalIngestionError`'s raw text must never reach it. This
    layer holds no PAT and so cannot scrub a secret out of an arbitrary message; per
    `.claude/rules/ingestion.md` it records the exception's class name instead, routed
    through `scrub` for the shape (spec 4.7)."""
    module = await create_checklist_module(db_session)
    queue = InMemoryIngestionQueue()
    seen: list[str] = []
    real_scrub = checklist_module.scrub

    def _spying_scrub(text: str, *secrets: str | None) -> str:
        seen.append(text)
        return real_scrub(text, *secrets)

    monkeypatch.setattr(checklist_module, "scrub", _spying_scrub)
    error_text = "no indexed file matches 'https://x:ghp_secret@h/r'"

    await handle_checklist_message(
        _message(module.id),
        generator=_Generator(TerminalIngestionError(error_text)),
        repository=ChecklistModuleRepository(db_session),
        producer=queue,
        worker_id="w1",
        max_attempts=3,
        session=db_session,
    )

    assert seen, "the failure path must route its recorded text through scrub"
    await db_session.refresh(module)
    assert module.status == ChecklistModuleStatus.FAILED.value
    assert module.error is not None
    assert "ghp_secret" not in module.error
    assert queue.produced[0][0] == CHECKLIST_DLQ_TOPIC


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

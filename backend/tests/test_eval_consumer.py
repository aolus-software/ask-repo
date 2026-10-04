"""One eval job message, end to end, with no broker."""

import logging
import uuid
from typing import Literal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.errors import TerminalIngestionError
from app.models.eval import EvalRun, EvalRunStatus, EvalSet, EvalSetStatus
from app.queue.consumer import JobOutcome
from app.queue.eval import EvalRunners, handle_eval_message
from app.queue.protocol import InMemoryIngestionQueue
from app.queue.topics import EVAL_DLQ_TOPIC, EvalJobMessage
from app.rag.errors import RetryableChatError, TerminalChatError
from tests.factories import create_project, create_user

MARKER = "SECRET-MARKER-sk-12345 def leaked_function()"


class _Stub:
    def __init__(self, *, raises: Exception | None = None) -> None:
        self.raises = raises
        self.calls: list[tuple[uuid.UUID, uuid.UUID, str, int]] = []

    async def run(
        self, *, target_id: uuid.UUID, job_id: uuid.UUID, worker_id: str, attempt: int = 0
    ) -> None:
        self.calls.append((target_id, job_id, worker_id, attempt))
        if self.raises is not None:
            raise self.raises


def _runners(generator: _Stub, runner: _Stub) -> EvalRunners:
    return EvalRunners(build_generator=lambda _: generator, build_runner=lambda _: runner)


async def _set(db: AsyncSession) -> EvalSet:
    user = await create_user(db)
    project = await create_project(db, created_by=user.id)
    row = EvalSet(
        id=uuid.uuid4(),
        project_id=project.id,
        name="s",
        requested_count=10,
        mix="balanced",
        status=EvalSetStatus.GENERATING.value,
        pair_count=0,
        created_by=user.id,
    )
    db.add(row)
    await db.commit()
    return row


async def _run(db: AsyncSession) -> EvalRun:
    eval_set = await _set(db)
    row = EvalRun(
        id=uuid.uuid4(),
        set_id=eval_set.id,
        project_id=eval_set.project_id,
        status=EvalRunStatus.RUNNING.value,
        created_by=eval_set.created_by,
    )
    db.add(row)
    await db.commit()
    return row


def _message(
    kind: Literal["generate", "run"], target_id: uuid.UUID, attempt: int = 0
) -> EvalJobMessage:
    return EvalJobMessage(
        kind=kind,
        target_id=target_id,
        job_id=uuid.uuid4(),
        attempt=attempt,
        not_before_ms=0,
        original_topic="askrepo.eval.jobs",
    )


async def _handle(
    db: AsyncSession,
    message: EvalJobMessage,
    *,
    generator: _Stub | None = None,
    runner: _Stub | None = None,
    producer: InMemoryIngestionQueue | None = None,
    max_attempts: int = 3,
) -> JobOutcome:
    return await handle_eval_message(
        message,
        runners=_runners(generator or _Stub(), runner or _Stub()),
        session=db,
        producer=producer or InMemoryIngestionQueue(),
        worker_id="me",
        max_attempts=max_attempts,
    )


async def test_a_generate_job_claims_the_set_and_runs_the_generator(
    db_session: AsyncSession,
) -> None:
    row = await _set(db_session)
    generator, runner = _Stub(), _Stub()

    outcome = await _handle(
        db_session, _message("generate", row.id, attempt=2), generator=generator, runner=runner
    )

    assert outcome is JobOutcome.COMPLETED
    assert [(c[0], c[2], c[3]) for c in generator.calls] == [(row.id, "me", 2)]
    assert runner.calls == []
    await db_session.refresh(row)
    assert row.lease_owner == "me"


async def test_a_run_job_claims_the_run_and_runs_the_runner(db_session: AsyncSession) -> None:
    row = await _run(db_session)
    generator, runner = _Stub(), _Stub()

    outcome = await _handle(db_session, _message("run", row.id), generator=generator, runner=runner)

    assert outcome is JobOutcome.COMPLETED
    assert [c[0] for c in runner.calls] == [row.id]
    assert generator.calls == []
    await db_session.refresh(row)
    assert row.lease_owner == "me"


async def test_an_already_claimed_target_is_skipped(db_session: AsyncSession) -> None:
    row = await _run(db_session)
    first, second = _Stub(), _Stub()
    await _handle(db_session, _message("run", row.id), runner=first)

    outcome = await _handle(db_session, _message("run", row.id), runner=second)

    assert outcome is JobOutcome.SKIPPED
    assert second.calls == []


async def test_a_terminal_error_fails_the_target_and_dead_letters(
    db_session: AsyncSession,
) -> None:
    eval_set = await _set(db_session)
    run = await _run(db_session)
    producer = InMemoryIngestionQueue()

    set_outcome = await _handle(
        db_session,
        _message("generate", eval_set.id),
        generator=_Stub(raises=TerminalIngestionError("nothing to sample")),
        producer=producer,
    )
    run_outcome = await _handle(
        db_session,
        _message("run", run.id),
        runner=_Stub(raises=TerminalChatError("bad schema")),
        producer=producer,
    )

    assert (set_outcome, run_outcome) == (JobOutcome.DEAD_LETTERED, JobOutcome.DEAD_LETTERED)
    await db_session.refresh(eval_set)
    await db_session.refresh(run)
    assert eval_set.status == EvalSetStatus.FAILED.value
    assert run.status == EvalRunStatus.FAILED.value
    assert [t for t, _ in producer.produced] == [EVAL_DLQ_TOPIC, EVAL_DLQ_TOPIC]
    kinds = [m.kind for _, m in producer.produced if isinstance(m, EvalJobMessage)]
    assert kinds == ["generate", "run"]


async def test_a_retryable_error_defers_and_schedules_a_retry(db_session: AsyncSession) -> None:
    row = await _run(db_session)
    producer = InMemoryIngestionQueue()

    outcome = await _handle(
        db_session,
        _message("run", row.id),
        runner=_Stub(raises=RetryableChatError("blip")),
        producer=producer,
    )

    assert outcome is JobOutcome.RETRY_SCHEDULED
    await db_session.refresh(row)
    assert row.status == EvalRunStatus.RUNNING.value
    assert row.lease_expires_at is not None
    topic, message = producer.produced[0]
    assert topic != EVAL_DLQ_TOPIC
    assert isinstance(message, EvalJobMessage)
    assert (message.kind, message.target_id, message.attempt) == ("run", row.id, 1)


async def test_a_spent_ladder_fails_rather_than_defers(db_session: AsyncSession) -> None:
    row = await _set(db_session)
    producer = InMemoryIngestionQueue()

    outcome = await _handle(
        db_session,
        _message("generate", row.id, attempt=2),
        generator=_Stub(raises=RetryableChatError("blip")),
        producer=producer,
        max_attempts=3,
    )

    assert outcome is JobOutcome.DEAD_LETTERED
    await db_session.refresh(row)
    assert row.status == EvalSetStatus.FAILED.value
    assert row.lease_owner is None
    assert producer.produced[0][0] == EVAL_DLQ_TOPIC


@pytest.mark.parametrize(
    "error",
    [
        TerminalChatError(MARKER),
        TerminalIngestionError(MARKER),
        RetryableChatError(MARKER),
        ValueError(MARKER),
    ],
)
async def test_failure_text_never_carries_the_exception_message(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture, error: Exception
) -> None:
    """Exceptions from the generator and runner wrap provider and Qdrant text, which
    can echo a prompt, an excerpt or a secret. Only the class name may be stored or
    logged -- the stored `error` column and every log line, traceback included."""
    eval_set = await _set(db_session)
    run = await _run(db_session)
    caplog.set_level(logging.DEBUG)

    for kind, row_id in (("generate", eval_set.id), ("run", run.id)):
        await _handle(
            db_session,
            _message(kind, row_id, attempt=2),  # type: ignore[arg-type]  # parametrised literal
            generator=_Stub(raises=error),
            runner=_Stub(raises=error),
        )

    await db_session.refresh(eval_set)
    await db_session.refresh(run)
    assert eval_set.error and run.error
    assert type(error).__name__ in eval_set.error
    assert MARKER not in eval_set.error
    assert MARKER not in run.error
    assert MARKER not in caplog.text
    assert "SECRET-MARKER" not in "".join(str(r.exc_info) for r in caplog.records if r.exc_info)

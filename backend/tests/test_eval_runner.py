"""Running a set: answer each pair through the real graph, judge it, record both signals."""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from langchain_core.language_models import BaseChatModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.eval import runner as runner_module
from app.eval.model_output import JudgeVerdict
from app.eval.runner import EvalRunner, retrieval_hit
from app.ingestion.chunker import Chunk
from app.ingestion.embedder import FakeEmbedder
from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError
from app.ingestion.vector_store import InMemoryVectorStore
from app.models.conversation import Conversation, Message
from app.models.eval import (
    EvalPair,
    EvalResult,
    EvalRun,
    EvalRunStatus,
    EvalSet,
    EvalSetStatus,
    EvalVerdict,
)
from app.rag.graph.state import Classification, EvidenceVerdict
from app.rag.prompt_version import PROMPT_VERSION
from app.rag.prompts import READER_PREFERENCES_PREAMBLE
from app.repositories.eval_result import EvalResultRepository
from app.repositories.eval_run import EvalRunRepository
from app.schemas.conversation import CitationPayload
from tests.factories import create_project, create_user
from tests.fakes import ScriptedChatModel

SOURCE = "app/core/repo_url.py"


def _citation(path: str) -> CitationPayload:
    return CitationPayload(
        index=1,
        file_path=path,
        start_line=1,
        end_line=2,
        language="python",
        symbol=None,
        commit_sha="x",
        score=0.5,
    )


def test_a_hit_is_the_source_file_among_the_citations() -> None:
    assert retrieval_hit([_citation("app/a.py"), _citation("app/b.py")], "app/b.py")
    assert not retrieval_hit([_citation("app/a.py")], "app/b.py")
    assert not retrieval_hit([], "app/b.py")


def _per_pair(*verdicts: str) -> list[Any]:
    """Classify, grade, judge -- in the order one pair consumes them."""
    script: list[Any] = []
    for verdict in verdicts:
        script += [
            Classification(intent="codebase_question", search_query="how is the url checked"),
            EvidenceVerdict(sufficient=True),
            JudgeVerdict(verdict=cast(Any, verdict), reason="because"),
        ]
    return script


def _chat(*verdicts: str, **kwargs: Any) -> ScriptedChatModel:
    return ScriptedChatModel(
        tokens=["It validates the URL [1]."], structured_results=_per_pair(*verdicts), **kwargs
    )


class _Setup:
    """Plain ids and strings: ORM rows expire at the first commit."""

    def __init__(
        self, run_id: uuid.UUID, pairs: list[tuple[uuid.UUID, str]], store: InMemoryVectorStore
    ) -> None:
        self.run_id = run_id
        self.pairs = pairs
        self.store = store
        self.job = uuid.uuid4()


async def _setup(
    session: AsyncSession, *, pairs: int = 2, excluded: int = 0, answer_style: bool = False
) -> _Setup:
    user = await create_user(session)
    if answer_style:
        user.answer_detail = "brief"
        user.answer_familiarity = "new"
        user.answer_format = "bullets"
    project = await create_project(session, created_by=user.id)
    project.active_generation = 0
    project.embedding_collection = "in-memory"
    project.embedding_model = "fake"
    eval_set = EvalSet(
        id=uuid.uuid4(),
        project_id=project.id,
        name="s",
        requested_count=pairs,
        mix="balanced",
        status=EvalSetStatus.READY.value,
        pair_count=pairs,
        created_by=user.id,
    )
    session.add(eval_set)
    await session.flush()
    rows = [
        EvalPair(
            id=uuid.uuid4(),
            set_id=eval_set.id,
            position=index,
            question_type="explain",
            question=f"What does question number {index} cover?",
            reference_answer="It validates the URL.",
            source_file=SOURCE,
            start_line=40,
            end_line=96,
        )
        for index in range(pairs + excluded)
    ]
    for row in rows[pairs:]:
        row.excluded_at = datetime.now(UTC)
    session.add_all(rows)
    run_id = uuid.uuid4()
    run = EvalRun(
        id=run_id,
        set_id=eval_set.id,
        project_id=project.id,
        status=EvalRunStatus.RUNNING.value,
        created_by=user.id,
    )
    session.add(run)
    await session.commit()
    job = uuid.uuid4()
    await EvalRunRepository(session).claim(
        run_id=run_id, job_id=job, worker_id="w", lease_seconds=300
    )
    await session.commit()

    store = InMemoryVectorStore(dimensions=8)
    chunk = Chunk(
        file_path=SOURCE,
        start_line=40,
        end_line=96,
        language="python",
        symbol="validate_repo_url",
        chunk_index=0,
        text="def validate_repo_url(url):\n    ...",
    )
    await store.upsert(
        project_id=project.id,
        generation=0,
        chunks=[chunk],
        vectors=await FakeEmbedder(dimensions=8).embed_documents([chunk.text]),
        commit_sha="9d12711",
    )
    setup = _Setup(run_id, [(r.id, r.question) for r in rows], store)
    setup.job = job
    return setup


def _runner(
    session: AsyncSession, setup: _Setup, chat: object, *, embedder: FakeEmbedder | None = None
) -> EvalRunner:
    return EvalRunner(
        session,
        Settings(eval_answer_concurrency=1, rag_min_score=0.0),
        store_factory=lambda _: setup.store,
        embedder=embedder or FakeEmbedder(dimensions=8),
        chat_model=cast(BaseChatModel, chat),
    )


async def _run(runner: EvalRunner, setup: _Setup) -> None:
    await runner.run(target_id=setup.run_id, job_id=setup.job, worker_id="w")


async def _reload(session: AsyncSession, run_id: uuid.UUID) -> EvalRun:
    session.expire_all()
    row = await EvalRunRepository(session).get(run_id)
    assert row is not None
    return row


async def _results(session: AsyncSession, run_id: uuid.UUID) -> list[EvalResult]:
    session.expire_all()
    return await EvalResultRepository(session).list_for_run(run_id)


async def test_a_run_records_a_result_per_included_pair_and_the_summary(
    db_session: AsyncSession,
) -> None:
    setup = await _setup(db_session, pairs=2, excluded=1)
    chat = _chat("correct", "wrong")

    await _run(_runner(db_session, setup, chat), setup)

    rows = await _results(db_session, setup.run_id)
    assert len(rows) == 2
    hit_count = sum(r.retrieval_hit for r in rows)
    reasons_ok = all(r.answer and r.judge_reason == "because" for r in rows)
    run = await _reload(db_session, setup.run_id)
    assert run.status == EvalRunStatus.DONE.value
    assert run.finished_at is not None
    assert run.pairs_answered == 2
    assert run.hits == hit_count == 2
    assert (run.correct, run.partial, run.wrong, run.errors) == (1, 0, 1, 0)
    assert run.prompt_version == PROMPT_VERSION
    assert run.judge_model == run.chat_model == Settings().chat_model
    assert run.chat_provider == Settings().chat_provider
    assert run.embedding_model == "fake"
    assert run.project_generation == 0
    assert reasons_ok


async def test_an_error_event_records_error_and_skips_the_judge(db_session: AsyncSession) -> None:
    setup = await _setup(db_session, pairs=1)
    chat = _chat("correct", fail_after=0)

    await _run(_runner(db_session, setup, chat), setup)

    rows = await _results(db_session, setup.run_id)
    assert [r.verdict for r in rows] == [EvalVerdict.ERROR.value]
    # Classify and grade only; the judge's entry is never drawn.
    assert len(chat.captured_messages) == 2
    run = await _reload(db_session, setup.run_id)
    assert run.status == EvalRunStatus.DONE.value
    assert run.errors == 1


async def test_a_judge_failure_records_error_and_keeps_the_answer(
    db_session: AsyncSession,
) -> None:
    setup = await _setup(db_session, pairs=1)
    chat = _chat("correct")
    chat.structured_results = chat.structured_results[:2]  # the judge call runs dry

    await _run(_runner(db_session, setup, chat), setup)

    (row,) = await _results(db_session, setup.run_id)
    assert row.verdict == EvalVerdict.ERROR.value
    assert row.answer == "It validates the URL [1]."
    assert row.judge_reason is None


async def test_a_redelivered_run_skips_answered_pairs(db_session: AsyncSession) -> None:
    setup = await _setup(db_session, pairs=2)
    db_session.add(
        EvalResult(
            id=uuid.uuid4(),
            run_id=setup.run_id,
            pair_id=setup.pairs[0][0],
            retrieval_hit=True,
            verdict=EvalVerdict.CORRECT.value,
            answer="earlier",
            grounding_warnings=[],
            retrieval_attempts=1,
        )
    )
    await db_session.commit()
    chat = _chat("wrong")

    await _run(_runner(db_session, setup, chat), setup)

    rows = await _results(db_session, setup.run_id)
    assert len(rows) == 2
    assert len(chat.captured_messages) == 3
    assert setup.pairs[1][1] in str(chat.captured_messages[0])
    assert setup.pairs[0][1] not in str(chat.captured_messages[0])
    run = await _reload(db_session, setup.run_id)
    assert (run.pairs_answered, run.correct, run.wrong) == (2, 1, 1)


async def test_the_runner_never_sends_an_answer_style(db_session: AsyncSession) -> None:
    setup = await _setup(db_session, pairs=1, answer_style=True)
    chat = _chat("correct")

    await _run(_runner(db_session, setup, chat), setup)

    assert chat.captured_stream_messages
    for messages in chat.captured_stream_messages:
        assert all(READER_PREFERENCES_PREAMBLE not in str(m.content) for m in messages)


async def test_a_run_writes_no_conversation_or_message(db_session: AsyncSession) -> None:
    setup = await _setup(db_session, pairs=1)

    async def counts() -> tuple[int, int]:
        conversations = await db_session.scalar(select(func.count()).select_from(Conversation))
        messages = await db_session.scalar(select(func.count()).select_from(Message))
        return int(conversations or 0), int(messages or 0)

    before = await counts()
    await _run(_runner(db_session, setup, _chat("correct")), setup)
    assert await counts() == before


async def test_a_run_whose_every_pair_errored_is_still_done(db_session: AsyncSession) -> None:
    setup = await _setup(db_session, pairs=2)
    chat = _chat("correct", "correct", fail_after=0)
    # A failed answer never reaches the judge, so its entry is never drawn.
    chat.structured_results = [
        r for r in chat.structured_results if not isinstance(r, JudgeVerdict)
    ]

    await _run(_runner(db_session, setup, chat), setup)

    run = await _reload(db_session, setup.run_id)
    assert run.status == EvalRunStatus.DONE.value
    assert (run.pairs_answered, run.errors) == (2, 2)


class _Boom(Exception):
    pass


class _BrokenStore(InMemoryVectorStore):
    async def search(self, **kwargs: Any) -> Any:
        raise _Boom("qdrant unreachable")


async def test_an_unreachable_store_propagates_as_retryable_and_leaves_the_run_open(
    db_session: AsyncSession,
) -> None:
    setup = await _setup(db_session, pairs=1)
    broken = _BrokenStore(dimensions=8)
    setup.store = broken

    with pytest.raises(RetryableIngestionError):
        await _run(_runner(db_session, setup, _chat("correct")), setup)

    run = await _reload(db_session, setup.run_id)
    assert run.status == EvalRunStatus.RUNNING.value
    assert await _results(db_session, setup.run_id) == []


async def test_a_changed_embedding_model_is_terminal(db_session: AsyncSession) -> None:
    setup = await _setup(db_session, pairs=1)

    with pytest.raises(TerminalIngestionError):
        await _run(
            _runner(db_session, setup, _chat("correct"), embedder=FakeEmbedder(model_id="other")),
            setup,
        )


async def test_a_missing_run_is_terminal(db_session: AsyncSession) -> None:
    setup = await _setup(db_session, pairs=1)
    with pytest.raises(TerminalIngestionError):
        await _runner(db_session, setup, _chat("correct")).run(
            target_id=uuid.uuid4(), job_id=setup.job, worker_id="w"
        )


async def test_the_lease_heartbeat_renews_during_the_run_and_stops_after(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner_module, "LEASE_RENEWAL_SECONDS", 0.01)
    calls: list[str] = []
    original = EvalRunRepository.renew_lease

    async def counting(self: EvalRunRepository, **kwargs: Any) -> bool:
        calls.append(kwargs["worker_id"])
        return await original(self, **kwargs)

    monkeypatch.setattr(EvalRunRepository, "renew_lease", counting)
    setup = await _setup(db_session, pairs=1)

    await _run(_runner(db_session, setup, _chat("correct", stall_seconds=0.15)), setup)

    assert len(calls) >= 2
    settled = len(calls)
    await asyncio.sleep(0.05)
    assert len(calls) == settled


async def test_a_lost_lease_propagates_and_commits_no_results(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner_module, "LEASE_RENEWAL_SECONDS", 0.01)

    async def lost(self: EvalRunRepository, **kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(EvalRunRepository, "renew_lease", lost)
    setup = await _setup(db_session, pairs=1)

    with pytest.raises(RetryableIngestionError):
        await _run(_runner(db_session, setup, _chat("correct", stall_seconds=0.15)), setup)

    assert await _results(db_session, setup.run_id) == []
    run = await _reload(db_session, setup.run_id)
    assert run.status == EvalRunStatus.RUNNING.value

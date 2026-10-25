"""Running a set: answer each pair through the real graph, judge it, record both signals."""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from langchain_core.language_models import BaseChatModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.language import Language
from app.core.notifications import NotificationType
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
from app.models.notification import Notification, NotificationEvent
from app.rag.answerer import Answerer
from app.rag.graph.state import Classification, EvidenceVerdict
from app.rag.prompt_version import ANSWER_PROMPT_VERSION, JUDGE_PROMPT_VERSION
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
    session: AsyncSession,
    *,
    pairs: int = 2,
    excluded: int = 0,
    answer_style: bool = False,
    language: str = "en",
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
        language=language,
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
    assert run.prompt_version == ANSWER_PROMPT_VERSION
    assert run.judge_prompt_version == JUDGE_PROMPT_VERSION
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


async def test_a_finished_run_notifies_eval_readers_and_links_its_set(
    db_session: AsyncSession,
) -> None:
    setup = await _setup(db_session, pairs=2)
    chat = _chat("correct", "wrong")

    await _run(_runner(db_session, setup, chat), setup)

    db_session.expire_all()
    run = await _reload(db_session, setup.run_id)
    (event,) = (
        (
            await db_session.execute(
                select(NotificationEvent).where(
                    NotificationEvent.event_type == NotificationType.EVAL_RUN_FINISHED.value
                )
            )
        )
        .scalars()
        .all()
    )
    recipients = (
        (
            await db_session.execute(
                select(Notification.user_id).where(Notification.event_id == event.id)
            )
        )
        .scalars()
        .all()
    )
    assert recipients == [run.created_by]
    # The set, not the run: a run's results live on its set's screen.
    assert (event.target_type, event.target_id) == ("eval_set", run.set_id)
    assert event.details == {
        "projectName": "repo",
        "setName": "s",
        "pairsAnswered": 2,
        "correct": 1,
    }


async def test_the_runner_passes_the_sets_language_as_the_reply_language(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The set's language, never the requester's (spec §4.3)."""
    setup = await _setup(db_session, pairs=1, language="id")
    seen: list[Language] = []
    original = Answerer.answer

    def recording(self: Answerer, **kwargs: Any) -> Any:
        seen.append(kwargs["reply_language"])
        return original(self, **kwargs)

    monkeypatch.setattr(Answerer, "answer", recording)

    await _run(_runner(db_session, setup, _chat("correct")), setup)

    assert seen == [Language.ID]


async def test_a_run_soft_deleted_mid_loop_commits_no_further_results(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner_module, "RESULT_BATCH", 1)
    setup = await _setup(db_session, pairs=3)
    original = EvalRunner._answer_and_judge
    calls = 0

    async def deleting(self: EvalRunner, *args: Any, **kwargs: Any) -> EvalResult:
        nonlocal calls
        calls += 1
        if calls == 2:
            # The first batch has committed; now the run is deleted under the worker.
            await db_session.execute(
                update(EvalRun).where(EvalRun.id == setup.run_id).values(deleted_at=func.now())
            )
            await db_session.commit()
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(EvalRunner, "_answer_and_judge", deleting)

    with pytest.raises(RetryableIngestionError):
        await _run(_runner(db_session, setup, _chat("correct", "correct", "correct")), setup)

    assert calls == 2
    db_session.expire_all()
    committed = (
        await db_session.scalars(select(EvalResult).where(EvalResult.run_id == setup.run_id))
    ).all()
    assert len(committed) == 1


async def test_a_resume_with_an_identical_stamp_proceeds_and_keeps_started_at(
    db_session: AsyncSession,
) -> None:
    setup = await _setup(db_session, pairs=2)
    await _run(_runner(db_session, setup, _chat("correct")), setup)
    first = await _reload(db_session, setup.run_id)
    stamped_at, stamp = first.started_at, first.prompt_version
    assert stamped_at is not None
    # Re-open the run, as a sweep re-publish after a lapsed lease would.
    first.status = EvalRunStatus.RUNNING.value
    first.lease_owner = None
    first.lease_expires_at = None
    first.last_job_id = None
    await db_session.commit()
    again = uuid.uuid4()
    assert await EvalRunRepository(db_session).claim(
        run_id=setup.run_id, job_id=again, worker_id="w", lease_seconds=300
    )
    await db_session.commit()
    setup.job = again

    await _run(_runner(db_session, setup, _chat()), setup)

    run = await _reload(db_session, setup.run_id)
    assert run.status == EvalRunStatus.DONE.value
    assert run.started_at == stamped_at
    assert run.prompt_version == stamp


async def test_a_resume_on_a_different_chat_model_fails_and_keeps_the_stamp(
    db_session: AsyncSession,
) -> None:
    setup = await _setup(db_session, pairs=1)
    run = await _reload(db_session, setup.run_id)
    run.prompt_version = ANSWER_PROMPT_VERSION
    run.judge_prompt_version = JUDGE_PROMPT_VERSION
    run.chat_provider = Settings().chat_provider
    run.chat_model = "some-other-model"
    run.judge_model = "some-other-model"
    run.embedding_model = "fake"
    run.project_generation = 0
    await db_session.commit()

    with pytest.raises(TerminalIngestionError, match="chat_model"):
        await _run(_runner(db_session, setup, _chat("correct")), setup)

    after = await _reload(db_session, setup.run_id)
    assert after.chat_model == "some-other-model"
    assert await _results(db_session, setup.run_id) == []

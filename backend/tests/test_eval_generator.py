"""Generating a set: scroll, sample, one structured call per pair, validate, write."""

import asyncio
import uuid
from typing import Any, cast

import pytest
from langchain_core.language_models import BaseChatModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.eval import generator as generator_module
from app.eval.generator import NO_PAIRS_ERROR, EvalSetGenerator
from app.eval.model_output import GeneratedPair
from app.ingestion.chunker import Chunk
from app.ingestion.vector_store import InMemoryVectorStore
from app.models.eval import EvalSet, EvalSetStatus
from app.rag.errors import RetryableChatError, TerminalChatError
from app.repositories.eval_pair import EvalPairRepository
from app.repositories.eval_set import EvalSetRepository
from tests.factories import create_project, create_user
from tests.fakes import StructuredScriptedChatModel


class RateLimitError(Exception):
    """Named so `classify_chat_error` maps it to retryable."""


class AuthenticationError(Exception):
    """Named so `classify_chat_error` maps it to terminal, as a provider's would be."""


class _SequencedModel:
    """Structured-output model replaying a list: an exception is raised, a value returned."""

    def __init__(self, steps: list[object], *, delay: float = 0.0) -> None:
        self._steps = list(steps)
        self._delay = delay

    def with_structured_output(self, schema: type) -> "_SequencedModel":
        return self

    async def ainvoke(self, messages: object, config: object = None) -> object:
        if self._delay:
            await asyncio.sleep(self._delay)
        step = self._steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def _pair(n: int) -> GeneratedPair:
    return GeneratedPair(
        question=f"What does the thing number {n} do?", reference_answer="It works."
    )


async def _index(store: InMemoryVectorStore, project_id: uuid.UUID, paths: list[str]) -> None:
    for index, path in enumerate(paths):
        await store.upsert(
            project_id=project_id,
            generation=0,
            chunks=[
                Chunk(
                    file_path=path,
                    start_line=1,
                    end_line=5,
                    language="python",
                    symbol=f"fn{index}",
                    chunk_index=0,
                    text=f"def fn{index}():\n    return {index}\n",
                )
            ],
            vectors=[[0.1] * 8],
            commit_sha="abc",
        )


async def _setup(
    session: AsyncSession,
    paths: list[str],
    *,
    count: int,
    source_path: str | None = None,
    job_id: uuid.UUID | None = None,
) -> tuple[EvalSet, InMemoryVectorStore, uuid.UUID]:
    user = await create_user(session)
    project = await create_project(session, created_by=user.id)
    project.active_generation = 0
    project.embedding_collection = "in-memory"
    eval_set = EvalSet(
        id=uuid.uuid4(),
        project_id=project.id,
        name="s",
        source_path=source_path,
        requested_count=count,
        mix="balanced",
        status=EvalSetStatus.GENERATING.value,
        pair_count=0,
        created_by=user.id,
    )
    session.add(eval_set)
    await session.commit()
    job = job_id or uuid.uuid4()
    await EvalSetRepository(session).claim(
        set_id=eval_set.id, job_id=job, worker_id="w", lease_seconds=300
    )
    await session.commit()
    store = InMemoryVectorStore(dimensions=8)
    await _index(store, project.id, paths)
    return eval_set, store, job


def _generator(session: AsyncSession, store: InMemoryVectorStore, chat: object) -> EvalSetGenerator:
    return EvalSetGenerator(
        session,
        Settings(),
        store_factory=lambda _: store,
        chat_model=cast(BaseChatModel, chat),
    )


async def _run(generator: EvalSetGenerator, eval_set: EvalSet, job: uuid.UUID) -> None:
    await generator.run(target_id=eval_set.id, job_id=job, worker_id="w")


async def _reload(session: AsyncSession, set_id: uuid.UUID) -> EvalSet:
    session.expire_all()
    row = await EvalSetRepository(session).get(set_id)
    assert row is not None
    return row


async def test_a_set_gets_one_pair_per_sampled_chunk(db_session: AsyncSession) -> None:
    eval_set, store, job = await _setup(db_session, ["a/x.py", "b/y.py", "c/z.py"], count=3)
    chat = StructuredScriptedChatModel({GeneratedPair: [_pair(1), _pair(2), _pair(3)]})

    await _run(_generator(db_session, store, chat), eval_set, job)

    row = await _reload(db_session, eval_set.id)
    assert row.status == EvalSetStatus.READY.value
    assert row.pair_count == 3
    assert row.indexed_generation == 0
    pairs = await EvalPairRepository(db_session).list_for_set(eval_set.id, include_excluded=True)
    assert sorted(p.position for p in pairs) == [0, 1, 2]
    assert len({p.source_file for p in pairs}) == 3


async def test_a_pair_naming_its_own_file_is_dropped(db_session: AsyncSession) -> None:
    eval_set, store, job = await _setup(db_session, ["app/a.py"], count=1)
    chat = StructuredScriptedChatModel(
        {GeneratedPair: [GeneratedPair(question="What does a.py do?", reference_answer="x")]}
    )

    await _run(_generator(db_session, store, chat), eval_set, job)

    row = await _reload(db_session, eval_set.id)
    assert row.pair_count == 0
    assert row.status == EvalSetStatus.FAILED.value
    pairs = await EvalPairRepository(db_session).list_for_set(eval_set.id, include_excluded=True)
    assert pairs == []


async def test_a_malformed_response_drops_one_pair_not_the_job(db_session: AsyncSession) -> None:
    eval_set, store, job = await _setup(db_session, ["a/x.py", "b/y.py", "c/z.py"], count=3)
    chat = _SequencedModel([ValueError("bad json"), _pair(1), _pair(2)])

    await _run(_generator(db_session, store, chat), eval_set, job)

    row = await _reload(db_session, eval_set.id)
    assert row.status == EvalSetStatus.READY.value
    assert row.pair_count == 2


async def test_zero_usable_pairs_fails_the_set(db_session: AsyncSession) -> None:
    eval_set, store, job = await _setup(db_session, ["a/x.py", "b/y.py"], count=2)
    chat = StructuredScriptedChatModel(
        {GeneratedPair: [GeneratedPair(question="", reference_answer="")]}
    )

    await _run(_generator(db_session, store, chat), eval_set, job)

    row = await _reload(db_session, eval_set.id)
    assert row.status == EvalSetStatus.FAILED.value
    assert row.error == NO_PAIRS_ERROR


async def test_only_chunks_under_the_source_path_are_sampled(db_session: AsyncSession) -> None:
    eval_set, store, job = await _setup(
        db_session, ["app/a.py", "lib/b.py"], count=5, source_path="app/"
    )
    chat = StructuredScriptedChatModel({GeneratedPair: [_pair(1)]})

    await _run(_generator(db_session, store, chat), eval_set, job)

    pairs = await EvalPairRepository(db_session).list_for_set(eval_set.id, include_excluded=True)
    assert pairs
    assert all(p.source_file.startswith("app/") for p in pairs)


async def test_a_terminal_chat_error_propagates(db_session: AsyncSession) -> None:
    eval_set, store, job = await _setup(db_session, ["a/x.py"], count=1)
    chat = _SequencedModel([AuthenticationError("bad key")])

    with pytest.raises(TerminalChatError):
        await _run(_generator(db_session, store, chat), eval_set, job)


async def test_the_lease_heartbeat_renews_during_the_run_and_stops_after(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_renew` ticks on its own session while the model is slow, and is cancelled on exit."""
    monkeypatch.setattr(generator_module, "LEASE_RENEWAL_SECONDS", 0.01)
    calls: list[str] = []
    original = EvalSetRepository.renew_lease

    async def counting(self: EvalSetRepository, **kwargs: Any) -> bool:
        calls.append(kwargs["worker_id"])
        return await original(self, **kwargs)

    monkeypatch.setattr(EvalSetRepository, "renew_lease", counting)
    eval_set, store, job = await _setup(db_session, ["a/x.py"], count=1)
    chat = _SequencedModel([_pair(1)], delay=0.15)

    await _run(_generator(db_session, store, chat), eval_set, job)

    assert len(calls) >= 2
    settled = len(calls)
    await asyncio.sleep(0.05)
    assert len(calls) == settled


async def test_a_retryable_chat_error_propagates_and_writes_nothing(
    db_session: AsyncSession,
) -> None:
    """A later pair's retryable failure must not release the set or keep earlier pairs."""
    eval_set, store, job = await _setup(db_session, ["a/x.py", "b/y.py"], count=2)
    chat = _SequencedModel([_pair(1), RateLimitError("slow down")])

    with pytest.raises(RetryableChatError):
        await _run(_generator(db_session, store, chat), eval_set, job)

    row = await _reload(db_session, eval_set.id)
    assert row.status == EvalSetStatus.GENERATING.value
    pairs = await EvalPairRepository(db_session).list_for_set(eval_set.id, include_excluded=True)
    assert pairs == []

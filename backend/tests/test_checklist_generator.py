"""Generation end to end, with no Qdrant, no broker, and no served model."""

import asyncio
import uuid
from contextlib import suppress
from typing import cast

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.checklist import generator as generator_module
from app.checklist.generator import ChecklistGenerator
from app.checklist.model_output import (
    FileObservations,
    ObservedBehaviour,
    ProposedChangeSet,
    ProposedOperation,
)
from app.config import Settings
from app.db.session import get_sessionmaker
from app.ingestion.chunker import Chunk
from app.ingestion.errors import TerminalIngestionError
from app.ingestion.vector_store import InMemoryVectorStore
from app.models.checklist import ChangeSetOrigin, ChangeSetStatus, ChecklistModuleStatus
from app.repositories.checklist_change_set import ChecklistChangeSetRepository
from app.repositories.checklist_item import ChecklistItemRepository
from app.repositories.checklist_module import ChecklistModuleRepository
from tests.factories import create_checklist_item, create_checklist_module, create_project
from tests.fakes import StructuredScriptedChatModel


async def _index(store: InMemoryVectorStore, *, project_id: uuid.UUID, path: str) -> None:
    await store.upsert(
        project_id=project_id,
        generation=1,
        chunks=[
            Chunk(
                file_path=path,
                start_line=1,
                end_line=40,
                language="python",
                symbol=None,
                chunk_index=0,
                text="def login(user):\n    raise Unauthorized()\n",
            )
        ],
        vectors=[[0.1] * 8],
        commit_sha="abc123",
    )


class _RaisingChatModel:
    """`with_structured_output(FileObservations).ainvoke(...)` always raises.

    Exercises the map step's failure path directly: a real served model never raises
    a domain `IngestionError`, but a Qdrant hiccup surfacing through `_observe` would,
    and that is exactly the kind of failure `asyncio.TaskGroup` must not smuggle
    through an `ExceptionGroup`.
    """

    def with_structured_output(self, schema: type) -> "_RaisingBound":
        return _RaisingBound(schema)


class _RaisingBound:
    """What `_RaisingChatModel.with_structured_output` returns."""

    def __init__(self, schema: type) -> None:
        self._schema = schema

    async def ainvoke(self, messages: list[object]) -> object:
        if self._schema is FileObservations:
            raise TerminalIngestionError("the map step failed")
        raise AssertionError("the reduce step should never be reached")


async def test_generation_writes_a_pending_change_set_and_no_items(
    db_session: AsyncSession,
) -> None:
    """Nothing generated enters the checklist unreviewed. Generation only ever
    proposes (spec 2.1)."""
    project = await create_project(db_session)
    project.active_generation = 1
    project.embedding_collection = "in-memory"
    module = await create_checklist_module(
        db_session, project_id=project.id, source_path="app/auth"
    )
    store = InMemoryVectorStore(dimensions=8)
    await _index(store, project_id=project.id, path="app/auth/login.py")

    chat = StructuredScriptedChatModel(
        {
            FileObservations: [
                FileObservations(
                    behaviours=[
                        ObservedBehaviour(
                            description="raises Unauthorized", start_line=2, end_line=2
                        )
                    ]
                )
            ],
            ProposedChangeSet: [
                ProposedChangeSet(
                    summary="1 added",
                    operations=[
                        ProposedOperation(
                            op="add",
                            feature="Login",
                            test_name="Rejects an unknown user",
                            expected_result="401 Unauthorized",
                            rationale="The handler raises Unauthorized.",
                            citation_paths=["app/auth/login.py"],
                        )
                    ],
                )
            ],
        }
    )
    generator = ChecklistGenerator(
        db_session, Settings(), store_factory=lambda _: store, chat_model=cast(BaseChatModel, chat)
    )
    job_id = uuid.uuid4()
    await ChecklistModuleRepository(db_session).claim(
        module_id=module.id, job_id=job_id, worker_id="w1", lease_seconds=300
    )

    await generator.run(module_id=module.id, job_id=job_id, worker_id="w1")

    await db_session.refresh(module)
    assert module.status == ChecklistModuleStatus.REVIEW.value
    assert module.indexed_generation == 1
    assert module.last_generated_at is not None

    change_set = await ChecklistChangeSetRepository(db_session).pending_for_module(module.id)
    assert change_set is not None
    assert change_set.origin == ChangeSetOrigin.GENERATION.value
    assert change_set.status == ChangeSetStatus.PENDING.value
    assert change_set.operations[0]["op"] == "add"
    # Spec 2.3: the generator never writes an observation.
    assert "currentResult" not in change_set.operations[0]
    # Spec 2.1: nothing generated enters the checklist unreviewed -- the change set
    # is the only thing generation writes.
    assert await ChecklistItemRepository(db_session).list_for_module(module.id) == []


async def test_operations_carry_a_citation_resolved_from_the_index(
    db_session: AsyncSession,
) -> None:
    """The model names a path; the generator supplies the line range, because a model
    asked for line numbers invents plausible ones."""
    project = await create_project(db_session)
    project.active_generation = 1
    project.embedding_collection = "in-memory"
    module = await create_checklist_module(
        db_session, project_id=project.id, source_path="app/auth"
    )
    store = InMemoryVectorStore(dimensions=8)
    await _index(store, project_id=project.id, path="app/auth/login.py")
    chat = StructuredScriptedChatModel(
        {
            FileObservations: [FileObservations(behaviours=[])],
            ProposedChangeSet: [
                ProposedChangeSet(
                    summary="1 added",
                    operations=[
                        ProposedOperation(
                            op="add",
                            feature="Login",
                            test_name="t",
                            expected_result="e",
                            citation_paths=["app/auth/login.py", "app/auth/nonexistent.py"],
                        )
                    ],
                )
            ],
        }
    )
    generator = ChecklistGenerator(
        db_session, Settings(), store_factory=lambda _: store, chat_model=cast(BaseChatModel, chat)
    )
    job_id = uuid.uuid4()
    await ChecklistModuleRepository(db_session).claim(
        module_id=module.id, job_id=job_id, worker_id="w1", lease_seconds=300
    )

    await generator.run(module_id=module.id, job_id=job_id, worker_id="w1")

    change_set = await ChecklistChangeSetRepository(db_session).pending_for_module(module.id)
    assert change_set is not None
    citations = cast(list[dict[str, object]], change_set.operations[0]["citations"])
    # The invented path is dropped rather than carried with a fabricated range.
    assert [citation["file_path"] for citation in citations] == ["app/auth/login.py"]
    assert citations[0]["start_line"] == 1


async def test_existing_items_are_shown_to_the_reduce_step(
    db_session: AsyncSession,
) -> None:
    """Passing the existing items is what makes regeneration a diff rather than a
    fresh list that has to be matched afterwards (spec 2.1)."""
    project = await create_project(db_session)
    project.active_generation = 1
    project.embedding_collection = "in-memory"
    module = await create_checklist_module(
        db_session, project_id=project.id, source_path="app/auth"
    )
    item = await create_checklist_item(
        db_session,
        module_id=module.id,
        project_id=project.id,
        created_by=module.created_by,
        test_name="Rejects a wrong password",
    )
    store = InMemoryVectorStore(dimensions=8)
    await _index(store, project_id=project.id, path="app/auth/login.py")
    chat = StructuredScriptedChatModel(
        {
            FileObservations: [FileObservations(behaviours=[])],
            ProposedChangeSet: [ProposedChangeSet(summary="no change", operations=[])],
        }
    )
    generator = ChecklistGenerator(
        db_session, Settings(), store_factory=lambda _: store, chat_model=cast(BaseChatModel, chat)
    )
    job_id = uuid.uuid4()
    await ChecklistModuleRepository(db_session).claim(
        module_id=module.id, job_id=job_id, worker_id="w1", lease_seconds=300
    )

    await generator.run(module_id=module.id, job_id=job_id, worker_id="w1")

    reduce_prompt = str(chat.prompts_for(ProposedChangeSet)[0][-1].content)
    assert str(item.id) in reduce_prompt
    assert "Rejects a wrong password" in reduce_prompt


async def test_a_path_that_matches_no_indexed_file_is_terminal(
    db_session: AsyncSession,
) -> None:
    """Retrying re-scrolls the same empty prefix forever. Terminal, so the operator is
    told rather than watching the job circle the ladder (`.claude/rules/ingestion.md`)."""
    project = await create_project(db_session)
    project.active_generation = 1
    project.embedding_collection = "in-memory"
    module = await create_checklist_module(
        db_session, project_id=project.id, source_path="frontend/nothing"
    )
    generator = ChecklistGenerator(
        db_session,
        Settings(),
        store_factory=lambda _: InMemoryVectorStore(dimensions=8),
        chat_model=cast(BaseChatModel, StructuredScriptedChatModel({})),
    )
    job_id = uuid.uuid4()
    await ChecklistModuleRepository(db_session).claim(
        module_id=module.id, job_id=job_id, worker_id="w1", lease_seconds=300
    )

    with pytest.raises(TerminalIngestionError):
        await generator.run(module_id=module.id, job_id=job_id, worker_id="w1")


async def test_a_partial_file_is_named_in_the_summary(db_session: AsyncSession) -> None:
    """Coverage is bounded by the chunker, and the bound is surfaced rather than
    buried. There is no "100% covered" badge (spec 4.6)."""
    project = await create_project(db_session)
    project.active_generation = 1
    project.embedding_collection = "in-memory"
    module = await create_checklist_module(
        db_session, project_id=project.id, source_path="app/auth"
    )
    store = InMemoryVectorStore(dimensions=8)
    # chunk_index 1 with no 0: a hole.
    await store.upsert(
        project_id=project.id,
        generation=1,
        chunks=[
            Chunk(
                file_path="app/auth/login.py",
                start_line=20,
                end_line=40,
                language="python",
                symbol=None,
                chunk_index=1,
                text="...",
            )
        ],
        vectors=[[0.1] * 8],
        commit_sha="abc",
    )
    chat = StructuredScriptedChatModel(
        {
            FileObservations: [FileObservations(behaviours=[])],
            ProposedChangeSet: [ProposedChangeSet(summary="1 added", operations=[])],
        }
    )
    generator = ChecklistGenerator(
        db_session, Settings(), store_factory=lambda _: store, chat_model=cast(BaseChatModel, chat)
    )
    job_id = uuid.uuid4()
    await ChecklistModuleRepository(db_session).claim(
        module_id=module.id, job_id=job_id, worker_id="w1", lease_seconds=300
    )

    await generator.run(module_id=module.id, job_id=job_id, worker_id="w1")

    change_set = await ChecklistChangeSetRepository(db_session).pending_for_module(module.id)
    assert change_set is not None
    assert "partial" in change_set.summary.lower()
    assert "app/auth/login.py" in change_set.summary


async def test_a_lost_lease_leaves_the_module_alone(db_session: AsyncSession) -> None:
    """A run that started is not entitled to finish. Another worker owns the module
    now, and this one must not write its outcome over the winner's."""
    project = await create_project(db_session)
    project.active_generation = 1
    project.embedding_collection = "in-memory"
    module = await create_checklist_module(
        db_session, project_id=project.id, source_path="app/auth"
    )
    store = InMemoryVectorStore(dimensions=8)
    await _index(store, project_id=project.id, path="app/auth/login.py")
    chat = StructuredScriptedChatModel(
        {
            FileObservations: [FileObservations(behaviours=[])],
            ProposedChangeSet: [ProposedChangeSet(summary="1 added", operations=[])],
        }
    )
    generator = ChecklistGenerator(
        db_session, Settings(), store_factory=lambda _: store, chat_model=cast(BaseChatModel, chat)
    )
    job_id = uuid.uuid4()
    repository = ChecklistModuleRepository(db_session)
    await repository.claim(module_id=module.id, job_id=job_id, worker_id="w1", lease_seconds=0)
    await repository.claim(
        module_id=module.id, job_id=uuid.uuid4(), worker_id="w2", lease_seconds=300
    )
    # Mirrors `app/queue/consumer.py`'s `handle_message`, which commits the claim
    # before the pipeline ever runs: without this, nothing before `generator.run`
    # was ever committed, so the rollback below (correctly discarding the lost run's
    # own writes) would also undo this test's own fixture setup.
    await db_session.commit()

    await generator.run(module_id=module.id, job_id=job_id, worker_id="w1")

    await db_session.refresh(module)
    assert module.lease_owner == "w2"
    assert module.status == ChecklistModuleStatus.GENERATING.value
    assert await ChecklistChangeSetRepository(db_session).pending_for_module(module.id) is None


async def test_lease_renewal_uses_its_own_session(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_renew` must not share the generation's session.

    An `AsyncSession` is not safe for concurrent use, and the renewal heartbeat runs
    while `run` is scrolling and calling the model on the same session. Mirrors
    `test_pipeline.py::test_the_lease_heartbeat_runs_on_a_session_of_its_own`: holding
    `db_session` busy with a real query for the whole window in which the heartbeat
    ticks is exactly the interleaving an `AsyncSession` cannot survive. A `_renew` that
    shares `self.session` either raises inside its own task -- dying unnoticed and
    renewing nothing -- or corrupts the busy query, so this asserts a renewal was
    actually observed *during* that busy window, not merely that one eventually
    landed. A version of this test that only checks `lease_expires_at is not None`
    after the fact passes just as readily against the shared-session bug (the initial
    claim already set that column), which is why the assertion below compares against
    the pre-renewal baseline instead.
    """
    monkeypatch.setattr(generator_module, "LEASE_RENEWAL_SECONDS", 0.01)
    project = await create_project(db_session)
    module = await create_checklist_module(db_session, project_id=project.id)
    job_id = uuid.uuid4()
    await ChecklistModuleRepository(db_session).claim(
        module_id=module.id, job_id=job_id, worker_id="w1", lease_seconds=300
    )
    await db_session.commit()
    await db_session.refresh(module)
    claimed_until = module.lease_expires_at
    assert claimed_until is not None

    generator = ChecklistGenerator(
        db_session,
        Settings(),
        store_factory=lambda _: InMemoryVectorStore(dimensions=8),
        chat_model=cast(BaseChatModel, StructuredScriptedChatModel({})),
    )
    renewal = asyncio.create_task(generator._renew(module_id=module.id, worker_id="w1"))
    try:
        # Hold `db_session` busy with a real query across several renewal ticks --
        # the same interleaving `IngestionPipeline`'s sibling test uses to force the
        # concurrent-use hazard rather than merely hoping timing exposes it.
        for _ in range(5):
            await db_session.execute(text("SELECT pg_sleep(0.02)"))
    finally:
        renewal.cancel()
        with suppress(asyncio.CancelledError):
            await renewal

    async with get_sessionmaker()() as verify:
        refreshed = await ChecklistModuleRepository(verify).get(module.id)
        assert refreshed is not None
        assert refreshed.lease_expires_at is not None
        # A renewal actually landed while `db_session` was busy: the shared-session
        # bug either never reaches this line (the task dies on its first tick) or
        # leaves the lease at its original claim-time expiry.
        assert refreshed.lease_expires_at > claimed_until


class _OrphanDetectingChatModel:
    """Distinguishes files by the path embedded in `build_map_prompt`'s content.

    One file fails immediately; the other sleeps and records whether it finished
    normally -- proving it kept running orphaned after its sibling's failure had
    already propagated -- or was cancelled -- proving `_propose` cancelled it. This is
    the actual property Finding 2 is about: whether the surviving map tasks are still
    running, spending semaphore permits and model calls, after `run` has unwound.
    """

    def __init__(self, *, slow_path: str, outcomes: list[str]) -> None:
        self._slow_path = slow_path
        self._outcomes = outcomes

    def with_structured_output(self, schema: type) -> "_OrphanDetectingBound":
        return _OrphanDetectingBound(schema, slow_path=self._slow_path, outcomes=self._outcomes)


class _OrphanDetectingBound:
    """What `_OrphanDetectingChatModel.with_structured_output` returns."""

    def __init__(self, schema: type, *, slow_path: str, outcomes: list[str]) -> None:
        self._schema = schema
        self._slow_path = slow_path
        self._outcomes = outcomes

    async def ainvoke(self, messages: list[BaseMessage]) -> object:
        if self._schema is not FileObservations:
            raise AssertionError("the reduce step should never be reached")
        content = str(messages[-1].content)
        if self._slow_path not in content:
            raise TerminalIngestionError("the fast file fails immediately")
        try:
            await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            self._outcomes.append("cancelled")
            raise
        self._outcomes.append("completed")
        return FileObservations(behaviours=[])


async def test_a_terminal_failure_from_one_file_is_not_wrapped_in_an_exception_group(
    db_session: AsyncSession,
) -> None:
    """A `TerminalIngestionError` from one map task must reach `run` as itself.

    `asyncio.TaskGroup` wraps every failure in an `ExceptionGroup`. Neither
    `_read_source` nor the consumer's failure routing classifies on that --
    an unclassified exception falls through to the unclassified path and
    dead-letters with a misleading reason (`.claude/rules/ingestion.md`), so
    `_propose` must unwrap it back to the original `TerminalIngestionError`.
    """
    project = await create_project(db_session)
    project.active_generation = 1
    project.embedding_collection = "in-memory"
    module = await create_checklist_module(
        db_session, project_id=project.id, source_path="app/auth"
    )
    store = InMemoryVectorStore(dimensions=8)
    await _index(store, project_id=project.id, path="app/auth/login.py")
    await _index(store, project_id=project.id, path="app/auth/logout.py")

    generator = ChecklistGenerator(
        db_session,
        Settings(),
        store_factory=lambda _: store,
        chat_model=cast(BaseChatModel, _RaisingChatModel()),
    )
    job_id = uuid.uuid4()
    await ChecklistModuleRepository(db_session).claim(
        module_id=module.id, job_id=job_id, worker_id="w1", lease_seconds=300
    )

    with pytest.raises(TerminalIngestionError):
        await generator.run(module_id=module.id, job_id=job_id, worker_id="w1")


async def test_a_sibling_map_task_is_cancelled_on_failure(db_session: AsyncSession) -> None:
    """The other in-flight `_observe` calls must not keep running after one fails.

    `asyncio.gather`'s default `return_exceptions=False` propagates the first failure
    but leaves sibling tasks running -- still holding semaphore permits and still
    calling the model -- after `run` has already unwound into the consumer's failure
    path (Finding 2). This is the actual discriminator: the ExceptionGroup-unwrapping
    test above passes against plain `asyncio.gather` too, because `gather` never
    raises an `ExceptionGroup` in the first place -- it only guards the unwrap logic
    inside the `TaskGroup` implementation, not the orphaned-task behaviour Finding 2
    is about.
    """
    project = await create_project(db_session)
    project.active_generation = 1
    project.embedding_collection = "in-memory"
    module = await create_checklist_module(
        db_session, project_id=project.id, source_path="app/auth"
    )
    store = InMemoryVectorStore(dimensions=8)
    await _index(store, project_id=project.id, path="app/auth/fast.py")
    await _index(store, project_id=project.id, path="app/auth/slow.py")

    outcomes: list[str] = []
    generator = ChecklistGenerator(
        db_session,
        Settings(),
        store_factory=lambda _: store,
        chat_model=cast(
            BaseChatModel,
            _OrphanDetectingChatModel(slow_path="app/auth/slow.py", outcomes=outcomes),
        ),
    )
    job_id = uuid.uuid4()
    await ChecklistModuleRepository(db_session).claim(
        module_id=module.id, job_id=job_id, worker_id="w1", lease_seconds=300
    )

    with pytest.raises(TerminalIngestionError):
        await generator.run(module_id=module.id, job_id=job_id, worker_id="w1")

    # Give an orphaned sibling task time to finish its sleep, if one is still running.
    await asyncio.sleep(0.3)
    assert outcomes == ["cancelled"]

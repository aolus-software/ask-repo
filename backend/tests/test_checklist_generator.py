"""Generation end to end, with no Qdrant, no broker, and no served model."""

import uuid
from typing import cast

import pytest
from langchain_core.language_models import BaseChatModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.checklist.generator import ChecklistGenerator
from app.checklist.model_output import (
    FileObservations,
    ObservedBehaviour,
    ProposedChangeSet,
    ProposedOperation,
)
from app.config import Settings
from app.ingestion.chunker import Chunk
from app.ingestion.errors import TerminalIngestionError
from app.ingestion.vector_store import InMemoryVectorStore
from app.models.checklist import ChangeSetOrigin, ChangeSetStatus, ChecklistModuleStatus
from app.repositories.checklist_change_set import ChecklistChangeSetRepository
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

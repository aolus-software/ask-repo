"""Mirrors `test_checklist_generator.py`'s shape for the single-call mock-data
generator, adapted to the fixtures that suite actually uses (`tests.factories` and
`tests.fakes`, not the `make_*`/`fake_store_factory` names sketched in the plan)."""

import uuid
from typing import cast

import pytest
from langchain_core.language_models import BaseChatModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.checklist.model_output import ProposedChangeSet
from app.config import Settings
from app.ingestion.chunker import Chunk
from app.ingestion.errors import TerminalIngestionError
from app.ingestion.vector_store import InMemoryVectorStore
from app.mockdata.generator import MockDataGenerator, NoSchemaFoundError
from app.mockdata.model_output import ProposedMockDataOperation, ProposedMockDataSet
from app.models.mock_data import MockDataDatasetStatus
from app.rag.errors import RetryableChatError, TerminalChatError
from app.repositories.mock_data_change_set import MockDataChangeSetRepository
from app.repositories.mock_data_dataset import MockDataDatasetRepository
from app.repositories.mock_data_record import MockDataRecordRepository
from tests.factories import create_checklist_module, create_project
from tests.fakes import StructuredScriptedChatModel

# No `pytestmark = pytest.mark.anyio`: this repo runs pytest-asyncio in "auto" mode
# (`asyncio_mode = "auto"` in pyproject.toml), so an `async def test_...` needs no
# marker -- matching `test_checklist_generator.py`'s own style.


async def _index(store: InMemoryVectorStore, *, project_id: uuid.UUID, path: str) -> None:
    """One chunk, indexed under generation 1 -- enough for `_read_source` to rebuild
    a file out of."""
    await store.upsert(
        project_id=project_id,
        generation=1,
        chunks=[
            Chunk(
                file_path=path,
                start_line=1,
                end_line=10,
                language="python",
                symbol=None,
                chunk_index=0,
                text="class Project(BaseModel):\n    name: str\n    start: str\n    end: str\n",
            )
        ],
        vectors=[[0.1] * 8],
        commit_sha="abc123",
    )


async def _claimed_dataset(
    session: AsyncSession, *, module_id: uuid.UUID, job_id: uuid.UUID, worker_id: str = "w1"
) -> uuid.UUID:
    """A dataset row for `module_id`, claimed by `worker_id` under `job_id` -- the
    state the consumer hands the generator in production."""
    datasets = MockDataDatasetRepository(session)
    dataset = await datasets.get_or_create_for_module(module_id)
    await session.commit()
    await datasets.claim(
        dataset_id=dataset.id, job_id=job_id, worker_id=worker_id, lease_seconds=300
    )
    await session.commit()
    return dataset.id


async def test_run_writes_a_pending_change_set_on_success(db_session: AsyncSession) -> None:
    """Nothing generated enters `mock_data_records` unreviewed -- generation only
    ever proposes."""
    project = await create_project(db_session)
    project.active_generation = 1
    project.embedding_collection = "in-memory"
    module = await create_checklist_module(
        db_session, project_id=project.id, source_path="app/features/project"
    )
    store = InMemoryVectorStore(dimensions=8)
    await _index(store, project_id=project.id, path="app/features/project/models.py")

    chat = StructuredScriptedChatModel(
        {
            ProposedMockDataSet: [
                ProposedMockDataSet(
                    schema_found=True,
                    field_keys=["name", "start", "end"],
                    summary="1 record added",
                    operations=[
                        ProposedMockDataOperation(
                            op="add",
                            fields={"name": "Acme", "start": "2026-01-01", "end": "2026-06-01"},
                            rationale="matches the Project model",
                        )
                    ],
                )
            ]
        }
    )
    generator = MockDataGenerator(
        db_session,
        Settings(),
        store_factory=lambda _: store,
        chat_model=cast(BaseChatModel, chat),
    )
    job_id = uuid.uuid4()
    dataset_id = await _claimed_dataset(db_session, module_id=module.id, job_id=job_id)

    await generator.run(dataset_id=dataset_id, job_id=job_id, worker_id="w1", count=1)

    refreshed = await MockDataDatasetRepository(db_session).get_by_module(module.id)
    assert refreshed is not None
    assert refreshed.status == MockDataDatasetStatus.REVIEW.value
    assert refreshed.indexed_generation == 1
    assert refreshed.last_generated_at is not None

    change_set = await MockDataChangeSetRepository(db_session).pending_for_module(module.id)
    assert change_set is not None
    assert change_set.operations[0]["op"] == "add"
    assert change_set.operations[0]["fields"] == {
        "name": "Acme",
        "start": "2026-01-01",
        "end": "2026-06-01",
    }
    # The generator never writes a record directly -- the change set is the only
    # thing generation writes.
    assert await MockDataRecordRepository(db_session).list_for_module(module.id) == []


async def test_run_raises_no_schema_found_when_model_reports_none(
    db_session: AsyncSession,
) -> None:
    """`schema_found: false` is a grounding gate, not an empty success -- the caller
    must fail generation rather than accept an empty or invented `operations` list."""
    project = await create_project(db_session)
    project.active_generation = 1
    project.embedding_collection = "in-memory"
    module = await create_checklist_module(
        db_session, project_id=project.id, source_path="app/misc"
    )
    store = InMemoryVectorStore(dimensions=8)
    await _index(store, project_id=project.id, path="app/misc/util.py")

    chat = StructuredScriptedChatModel(
        {ProposedMockDataSet: [ProposedMockDataSet(schema_found=False)]}
    )
    generator = MockDataGenerator(
        db_session,
        Settings(),
        store_factory=lambda _: store,
        chat_model=cast(BaseChatModel, chat),
    )
    job_id = uuid.uuid4()
    dataset_id = await _claimed_dataset(db_session, module_id=module.id, job_id=job_id)

    with pytest.raises(NoSchemaFoundError):
        await generator.run(dataset_id=dataset_id, job_id=job_id, worker_id="w1", count=3)


async def test_a_path_that_matches_no_indexed_file_is_terminal(db_session: AsyncSession) -> None:
    """Retrying re-scrolls the same empty prefix forever -- terminal, so the
    operator is told rather than watching the job circle the ladder."""
    project = await create_project(db_session)
    project.active_generation = 1
    project.embedding_collection = "in-memory"
    module = await create_checklist_module(
        db_session, project_id=project.id, source_path="frontend/nothing"
    )
    generator = MockDataGenerator(
        db_session,
        Settings(),
        store_factory=lambda _: InMemoryVectorStore(dimensions=8),
        chat_model=cast(BaseChatModel, StructuredScriptedChatModel({})),
    )
    job_id = uuid.uuid4()
    dataset_id = await _claimed_dataset(db_session, module_id=module.id, job_id=job_id)

    with pytest.raises(TerminalIngestionError):
        await generator.run(dataset_id=dataset_id, job_id=job_id, worker_id="w1", count=3)


async def test_a_lost_lease_leaves_the_dataset_alone(db_session: AsyncSession) -> None:
    """A run that started is not entitled to finish -- another worker owns the
    dataset now, and this one must not write its outcome over the winner's."""
    project = await create_project(db_session)
    project.active_generation = 1
    project.embedding_collection = "in-memory"
    module = await create_checklist_module(
        db_session, project_id=project.id, source_path="app/features/project"
    )
    module_id = module.id
    store = InMemoryVectorStore(dimensions=8)
    await _index(store, project_id=project.id, path="app/features/project/models.py")
    chat = StructuredScriptedChatModel(
        {
            ProposedMockDataSet: [
                ProposedMockDataSet(schema_found=True, field_keys=[], operations=[])
            ]
        }
    )
    generator = MockDataGenerator(
        db_session,
        Settings(),
        store_factory=lambda _: store,
        chat_model=cast(BaseChatModel, chat),
    )
    datasets = MockDataDatasetRepository(db_session)
    dataset = await datasets.get_or_create_for_module(module_id)
    dataset_id = dataset.id
    await db_session.commit()
    job_id = uuid.uuid4()
    await datasets.claim(dataset_id=dataset_id, job_id=job_id, worker_id="w1", lease_seconds=0)
    await datasets.claim(
        dataset_id=dataset_id, job_id=uuid.uuid4(), worker_id="w2", lease_seconds=300
    )
    # Mirrors `app/queue/checklist.py`'s handler, which commits the claim before the
    # generator ever runs: without this, the rollback below (correctly discarding
    # the lost run's own writes) would also undo this test's own fixture setup.
    await db_session.commit()

    await generator.run(dataset_id=dataset_id, job_id=job_id, worker_id="w1", count=1)

    refreshed = await MockDataDatasetRepository(db_session).get_by_module(module_id)
    assert refreshed is not None
    assert refreshed.lease_owner == "w2"
    assert refreshed.status == MockDataDatasetStatus.GENERATING.value
    assert await MockDataChangeSetRepository(db_session).pending_for_module(module_id) is None


async def test_a_classifiable_model_failure_is_reraised_as_its_classified_type(
    db_session: AsyncSession,
) -> None:
    """The single model call's failure must reach `run` as a `RetryableChatError`,
    not the raw SDK-shaped exception -- otherwise the consumer's unclassified-failure
    safety net handles a failure mode `classify_chat_error` already knows about."""
    project = await create_project(db_session)
    project.active_generation = 1
    project.embedding_collection = "in-memory"
    module = await create_checklist_module(
        db_session, project_id=project.id, source_path="app/features/project"
    )
    store = InMemoryVectorStore(dimensions=8)
    await _index(store, project_id=project.id, path="app/features/project/models.py")

    class _NamedFailureBound:
        async def ainvoke(self, messages: list[object]) -> object:
            raise type("RateLimitError", (Exception,), {})("provider said no")

    class _NamedFailureChatModel:
        def with_structured_output(self, schema: type) -> "_NamedFailureBound":
            return _NamedFailureBound()

    generator = MockDataGenerator(
        db_session,
        Settings(),
        store_factory=lambda _: store,
        chat_model=cast(BaseChatModel, _NamedFailureChatModel()),
    )
    job_id = uuid.uuid4()
    dataset_id = await _claimed_dataset(db_session, module_id=module.id, job_id=job_id)

    with pytest.raises(RetryableChatError):
        await generator.run(dataset_id=dataset_id, job_id=job_id, worker_id="w1", count=1)


async def test_the_model_returning_an_unusable_shape_is_terminal(
    db_session: AsyncSession,
) -> None:
    """A model that cannot produce the requested shape will not produce it on a
    retry either -- this is a bug in the model's structured-output support, not a
    transient failure."""
    project = await create_project(db_session)
    project.active_generation = 1
    project.embedding_collection = "in-memory"
    module = await create_checklist_module(
        db_session, project_id=project.id, source_path="app/features/project"
    )
    store = InMemoryVectorStore(dimensions=8)
    await _index(store, project_id=project.id, path="app/features/project/models.py")
    chat = StructuredScriptedChatModel(
        # Wrong shape for `ProposedMockDataSet`: the propose step must reject it.
        {ProposedMockDataSet: [ProposedChangeSet(summary="wrong shape", operations=[])]}
    )
    generator = MockDataGenerator(
        db_session,
        Settings(),
        store_factory=lambda _: store,
        chat_model=cast(BaseChatModel, chat),
    )
    job_id = uuid.uuid4()
    dataset_id = await _claimed_dataset(db_session, module_id=module.id, job_id=job_id)

    with pytest.raises(TerminalChatError):
        await generator.run(dataset_id=dataset_id, job_id=job_id, worker_id="w1", count=1)


async def test_operations_with_a_mismatched_field_key_set_are_dropped(
    db_session: AsyncSession,
) -> None:
    """`field_keys` is the batch's canonical key set -- an `add` whose `fields` uses
    a different key set is dropped rather than stored, and the run still succeeds
    because there is nothing else the model proposed."""
    project = await create_project(db_session)
    project.active_generation = 1
    project.embedding_collection = "in-memory"
    module = await create_checklist_module(
        db_session, project_id=project.id, source_path="app/features/project"
    )
    store = InMemoryVectorStore(dimensions=8)
    await _index(store, project_id=project.id, path="app/features/project/models.py")
    chat = StructuredScriptedChatModel(
        {
            ProposedMockDataSet: [
                ProposedMockDataSet(
                    schema_found=True,
                    field_keys=["name", "start", "end"],
                    summary="1 record added",
                    operations=[
                        ProposedMockDataOperation(
                            op="add",
                            fields={"wrong_key": "value"},
                            rationale="does not match the schema",
                        )
                    ],
                )
            ]
        }
    )
    generator = MockDataGenerator(
        db_session,
        Settings(),
        store_factory=lambda _: store,
        chat_model=cast(BaseChatModel, chat),
    )
    job_id = uuid.uuid4()
    dataset_id = await _claimed_dataset(db_session, module_id=module.id, job_id=job_id)

    await generator.run(dataset_id=dataset_id, job_id=job_id, worker_id="w1", count=1)

    change_set = await MockDataChangeSetRepository(db_session).pending_for_module(module.id)
    assert change_set is not None
    assert change_set.operations == []

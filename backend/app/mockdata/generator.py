"""Turning a module's indexed code into a proposed mock dataset.

One call, not map-reduce: unlike the checklist's exhaustive-coverage goal, a mock-data
generation only needs to find schema-shaped code somewhere under the module's path and
invent records against it, so the module's (capped) source is given to the model whole
rather than observed file-by-file and reduced.

The output is always a pending change set, never a row -- nothing generated enters
`mock_data_records` unreviewed, the same non-negotiable `app/checklist/generator.py`
states for the checklist.
"""

import asyncio
import logging
import uuid
from dataclasses import replace
from datetime import UTC, datetime

from langchain_core.language_models import BaseChatModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.checklist.source import ModuleSource, rebuild_files
from app.config import Settings
from app.db.session import get_sessionmaker
from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError
from app.ingestion.vector_store import VectorStoreFactory
from app.mockdata.model_output import ProposedMockDataSet
from app.mockdata.operations import stored_mock_data_operation
from app.models.checklist import ChangeSetOrigin, ChangeSetStatus
from app.models.mock_data import MockDataChangeSet, MockDataDatasetStatus
from app.rag.errors import TerminalChatError, classify_chat_error
from app.rag.prompts import ExistingRecord, build_mock_data_generate_prompt
from app.repositories.checklist_module import ChecklistModuleRepository
from app.repositories.mock_data_change_set import MockDataChangeSetRepository
from app.repositories.mock_data_dataset import (
    LEASE_RENEWAL_SECONDS,
    LEASE_SECONDS,
    MockDataDatasetRepository,
)
from app.repositories.mock_data_record import MockDataRecordRepository
from app.repositories.project import ProjectRepository

logger = logging.getLogger(__name__)


class NoSchemaFoundError(TerminalIngestionError):
    """The model found nothing schema-shaped under the module's source path.

    A dedicated subclass, not a bare `TerminalIngestionError`, so its class name
    survives the consumer's scrub-to-classname reduction (`.claude/rules/ingestion.md`)
    and a reviewer reading `dataset.error` can tell this apart from every other
    generation failure.
    """


def _apply_file_cap(source: ModuleSource, *, max_files: int) -> ModuleSource:
    """`source`, unless it exceeds `max_files` -- the excess moves to `skipped_paths`."""
    if len(source.files) <= max_files:
        return source
    kept, excess = source.files[:max_files], source.files[max_files:]
    return replace(
        source,
        files=kept,
        skipped_paths=[*source.skipped_paths, *(file.path for file in excess)],
    )


class MockDataGenerator:
    """One generation run, bound to one session."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        store_factory: VectorStoreFactory,
        chat_model: BaseChatModel,
    ) -> None:
        """Bind this run to `session`.

        `_renew` deliberately does not use `session` -- it opens its own short-lived
        session per tick, because an `AsyncSession` is not safe for concurrent use and
        the heartbeat runs while the rest of this class is still using this one.
        """
        self.session = session
        self.settings = settings
        self.store_factory = store_factory
        self.chat_model = chat_model
        self.datasets = MockDataDatasetRepository(session)
        self.records = MockDataRecordRepository(session)
        self.change_sets = MockDataChangeSetRepository(session)
        self.modules = ChecklistModuleRepository(session)
        self.projects = ProjectRepository(session)

    async def run(
        self, *, dataset_id: uuid.UUID, job_id: uuid.UUID, worker_id: str, count: int
    ) -> None:
        """Generate one dataset's change set, renewing the lease throughout.

        The caller has already claimed the dataset. Failures propagate as
        `TerminalIngestionError`/`RetryableIngestionError`/`TerminalChatError` so the
        consumer routes them onto the ladder; the dataset's `failed` status and
        scrubbed `error` are written by the consumer's failure path, not here.
        """
        dataset = await self.datasets.get(dataset_id)
        if dataset is None:
            raise TerminalIngestionError(f"mock data dataset {dataset_id} is gone")
        module = await self.modules.get(dataset.checklist_module_id)
        if module is None:
            raise TerminalIngestionError(f"checklist module {dataset.checklist_module_id} is gone")
        project = await self.projects.get(module.project_id)
        if project is None or not project.embedding_collection:
            raise TerminalIngestionError(f"project {module.project_id} has no index to enumerate")

        renewal = asyncio.create_task(self._renew(dataset_id=dataset_id, worker_id=worker_id))
        try:
            source = await self._read_source(
                # Verbatim from the row, never recomputed from current settings: the
                # width is probed at worker startup, and a project indexed before a
                # provider switch legitimately lives in a different collection.
                collection=project.embedding_collection,
                project_id=project.id,
                generation=project.active_generation,
                path_prefix=module.source_path,
            )
            source = _apply_file_cap(source, max_files=self.settings.mock_data_max_files_per_job)
            existing = [
                ExistingRecord(id=str(record.id), fields=record.fields)
                for record in await self.records.list_for_module(module.id)
            ]
            proposal = await self._propose(
                module_name=module.name, source=source, existing=existing, count=count
            )
        finally:
            await self._stop_renewal(renewal, dataset_id=dataset_id)

        if not proposal.schema_found:
            raise NoSchemaFoundError(
                f"no data schema found under {module.source_path!r} in this project"
            )

        operations = [
            stored
            for operation in proposal.operations
            if (
                stored := stored_mock_data_operation(
                    operation, field_keys=proposal.field_keys or None
                )
            )
            is not None
        ]
        summary = proposal.summary or f"{len(operations)} proposed record(s)"

        change_set = MockDataChangeSet(
            id=uuid.uuid4(),
            checklist_module_id=module.id,
            origin=ChangeSetOrigin.GENERATION.value,
            summary=summary,
            operations=operations,
            status=ChangeSetStatus.PENDING.value,
            created_by=module.created_by,
        )

        # Staged before the release, and committed only if the release matched -- a
        # worker that lost its lease must leave both the dataset and the change set
        # alone, matching `ChecklistGenerator.run`'s own ordering.
        await self.change_sets.add(change_set)
        released = await self.datasets.release(
            dataset_id=dataset_id,
            job_id=job_id,
            worker_id=worker_id,
            status=MockDataDatasetStatus.REVIEW,
            indexed_generation=project.active_generation,
            last_generated_at=datetime.now(UTC),
        )
        if not released:
            await self.session.rollback()
            logger.warning(
                "mock-data generation for dataset %s lost its lease; discarding the proposal",
                dataset_id,
            )
            return
        await self.session.commit()

    async def _renew(self, *, dataset_id: uuid.UUID, worker_id: str) -> None:
        """Hold the lease for the length of the run. Mirrors `ChecklistGenerator._renew`.

        Each tick uses its own short-lived session, never the one the generation is
        running on: an `AsyncSession` is not safe for concurrent use, and two
        coroutines interleaving on one connection fail with an `InterfaceError` or,
        worse, a mis-scoped transaction.
        """
        while True:
            await asyncio.sleep(LEASE_RENEWAL_SECONDS)
            async with get_sessionmaker()() as session:
                held = await MockDataDatasetRepository(session).renew_lease(
                    dataset_id=dataset_id, worker_id=worker_id, lease_seconds=LEASE_SECONDS
                )
                await session.commit()
            if not held:
                logger.warning("lost the lease on mock data dataset %s mid-run", dataset_id)
                return

    async def _stop_renewal(self, renewal: asyncio.Task[None], *, dataset_id: uuid.UUID) -> None:
        """Cancel the heartbeat and collect it. Mirrors `ChecklistGenerator._stop_renewal`."""
        renewal.cancel()
        try:
            await renewal
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.warning(
                "lease renewal for mock data dataset %s failed", dataset_id, exc_info=True
            )

    async def _read_source(
        self,
        *,
        collection: str,
        project_id: uuid.UUID,
        generation: int,
        path_prefix: str,
    ) -> ModuleSource:
        """Scroll the module's chunks and rebuild them into files. Mirrors
        `ChecklistGenerator._read_source` exactly, including its error classification."""
        store = self.store_factory(collection)
        payloads: list[dict[str, object]] = []
        try:
            async for page in store.scroll(
                project_id=project_id,
                generation=generation,
                path_prefix=path_prefix,
                page_size=self.settings.mock_data_scroll_page_size,
            ):
                payloads.extend(page)
        except TerminalIngestionError:
            raise
        except Exception as error:
            raise RetryableIngestionError(f"scrolling the module failed: {error}") from error

        if not payloads:
            raise TerminalIngestionError(f"no indexed file matches {path_prefix!r} in this project")
        return rebuild_files(payloads, chunk_overlap=self.settings.chunk_overlap)

    async def _propose(
        self,
        *,
        module_name: str,
        source: ModuleSource,
        existing: list[ExistingRecord],
        count: int,
    ) -> ProposedMockDataSet:
        """One model call over the module's whole (capped) source text."""
        source_text = "\n\n".join(
            f"# {file.path} (lines {file.start_line}-{file.end_line})\n{file.text}"
            for file in source.files
        )
        model = self.chat_model.with_structured_output(ProposedMockDataSet)
        try:
            result = await model.ainvoke(
                build_mock_data_generate_prompt(
                    module_name=module_name,
                    source_text=source_text,
                    count=count,
                    existing=existing,
                    partial_paths=source.partial_paths,
                    skipped_paths=source.skipped_paths,
                )
            )
        except Exception as error:
            # Same pattern as `ChecklistGenerator._observe`: classify by exception
            # name and fall through to the unclassified-failure safety net
            # (`.claude/rules/ingestion.md`) when `classify_chat_error` returns `None`.
            raise classify_chat_error(error) or error from error
        if not isinstance(result, ProposedMockDataSet):
            raise TerminalChatError("the generation step returned an unusable shape")
        return result

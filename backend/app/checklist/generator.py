"""Turning a module's indexed code into a proposed checklist.

Scroll, map, reduce, propose. The output is always a *pending change set* and never an
item: nothing generated enters the checklist unreviewed (spec 2.1). A run that dies
before writing its change set has therefore changed nothing -- the same property that
makes a failed reindex leave the previous index serving.
"""

import asyncio
import logging
import uuid
from dataclasses import replace
from datetime import UTC, datetime

from langchain_core.language_models import BaseChatModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.checklist.model_output import FileObservations, ProposedChangeSet
from app.checklist.operations import stored_operation
from app.checklist.source import ModuleFile, ModuleSource, rebuild_files
from app.config import Settings
from app.db.session import get_sessionmaker
from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError
from app.ingestion.vector_store import VectorStoreFactory
from app.models.checklist import (
    ChangeSetOrigin,
    ChangeSetStatus,
    ChecklistChangeSet,
    ChecklistModuleStatus,
)
from app.rag.errors import TerminalChatError, classify_chat_error
from app.rag.prompts import (
    ExistingItem,
    build_map_prompt,
    build_reduce_prompt,
)
from app.repositories.checklist_change_set import ChecklistChangeSetRepository
from app.repositories.checklist_item import ChecklistItemRepository
from app.repositories.checklist_module import (
    LEASE_RENEWAL_SECONDS,
    LEASE_SECONDS,
    ChecklistModuleRepository,
)
from app.repositories.project import ProjectRepository

logger = logging.getLogger(__name__)


def _apply_file_cap(source: ModuleSource, *, max_files: int) -> ModuleSource:
    """`source`, unless it exceeds `max_files` -- the excess moves to `skipped_paths`.

    `rebuild_files` already sorts `files` by path, so the cut is deterministic and
    reviewable rather than arbitrary (M4.5 spec 4.1).
    """
    if len(source.files) <= max_files:
        return source
    kept, excess = source.files[:max_files], source.files[max_files:]
    return replace(
        source,
        files=kept,
        skipped_paths=[*source.skipped_paths, *(file.path for file in excess)],
    )


class ChecklistGenerator:
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
        self.modules = ChecklistModuleRepository(session)
        self.items = ChecklistItemRepository(session)
        self.change_sets = ChecklistChangeSetRepository(session)
        self.projects = ProjectRepository(session)

    async def run(self, *, module_id: uuid.UUID, job_id: uuid.UUID, worker_id: str) -> None:
        """Generate one module's change set, renewing the lease throughout.

        The caller has already claimed the module. Failures propagate as
        `TerminalIngestionError` / `RetryableIngestionError` so the consumer can route
        them onto the ladder; the module's `failed` status and scrubbed `error` are
        written by the consumer's failure path, not here, so a retryable failure does
        not leave the row claiming the module is broken (`.claude/rules/ingestion.md`).
        """
        module = await self.modules.get(module_id)
        if module is None:
            raise TerminalIngestionError(f"checklist module {module_id} is gone")
        project = await self.projects.get(module.project_id)
        if project is None or not project.embedding_collection:
            raise TerminalIngestionError(f"project {module.project_id} has no index to enumerate")

        renewal = asyncio.create_task(self._renew(module_id=module_id, worker_id=worker_id))
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
            source = _apply_file_cap(source, max_files=self.settings.checklist_max_files_per_job)
            existing = [
                ExistingItem(
                    id=str(item.id),
                    feature=item.feature,
                    test_name=item.test_name,
                    expected_result=item.expected_result,
                    kind=item.kind,
                )
                for item in await self.items.list_for_module(module_id)
            ]
            proposal = await self._propose(
                module_name=module.name, source=source, existing=existing
            )
            operations = self._to_operations(proposal, source=source)
        finally:
            await self._stop_renewal(renewal, module_id=module_id)

        summary = self._summarise(
            operations, source=source, max_files=self.settings.checklist_max_files_per_job
        )
        change_set = ChecklistChangeSet(
            id=uuid.uuid4(),
            module_id=module_id,
            origin=ChangeSetOrigin.GENERATION.value,
            summary=summary,
            operations=operations,
            status=ChangeSetStatus.PENDING.value,
            created_by=module.created_by,
        )

        # Staged before the release, and committed only if the release matched: a
        # worker that lost its lease must leave both the module and the change set
        # alone, or the surviving row names a proposal nobody asked for.
        await self.change_sets.add(change_set)
        released = await self.modules.release(
            module_id=module_id,
            job_id=job_id,
            worker_id=worker_id,
            status=ChecklistModuleStatus.REVIEW,
            indexed_generation=project.active_generation,
            last_generated_at=datetime.now(UTC),
        )
        if not released:
            await self.session.rollback()
            logger.warning(
                "checklist generation for module %s lost its lease; discarding the proposal",
                module_id,
            )
            return
        await self.session.commit()

    async def _renew(self, *, module_id: uuid.UUID, worker_id: str) -> None:
        """Hold the lease for the length of the run.

        A generation over a large module runs for minutes and the lease is five, so
        this is what makes the two numbers compatible -- the same arrangement
        `IngestionPipeline._renew_lease` uses.

        Each tick uses its own short-lived session, never the one the generation is
        running on: an `AsyncSession` is not safe for concurrent use, and two
        coroutines interleaving on one connection fail with an `InterfaceError` or,
        worse, a mis-scoped transaction.
        """
        while True:
            await asyncio.sleep(LEASE_RENEWAL_SECONDS)
            async with get_sessionmaker()() as session:
                held = await ChecklistModuleRepository(session).renew_lease(
                    module_id=module_id, worker_id=worker_id, lease_seconds=LEASE_SECONDS
                )
                await session.commit()
            if not held:
                logger.warning("lost the lease on checklist module %s mid-run", module_id)
                return

    async def _stop_renewal(self, renewal: asyncio.Task[None], *, module_id: uuid.UUID) -> None:
        """Cancel the heartbeat and collect it, so nothing fails silently.

        Matches `IngestionPipeline._stop`: a bare `.cancel()` with no `await` leaves
        any non-`CancelledError` failure -- including one from the heartbeat's own
        `get_sessionmaker()` teardown -- unretrieved, and it surfaces later as an
        unrelated "Task exception was never retrieved" warning instead of here, where
        it is at least attributable to this module's run.
        """
        renewal.cancel()
        try:
            await renewal
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.warning("lease renewal for checklist module %s failed", module_id, exc_info=True)

    async def _read_source(
        self,
        *,
        collection: str,
        project_id: uuid.UUID,
        generation: int,
        path_prefix: str,
    ) -> ModuleSource:
        """Scroll the module's chunks and rebuild them into files.

        Enumeration, not search: top-k returns k things and cannot report what it left
        out, which is the wrong shape for "list every feature in this module" (spec 2.2).
        """
        store = self.store_factory(collection)
        payloads: list[dict[str, object]] = []
        try:
            async for page in store.scroll(
                project_id=project_id,
                generation=generation,
                path_prefix=path_prefix,
                page_size=self.settings.checklist_scroll_page_size,
            ):
                payloads.extend(page)
        except TerminalIngestionError:
            raise
        except Exception as error:
            raise RetryableIngestionError(f"scrolling the module failed: {error}") from error

        if not payloads:
            # No `scrub` here, deliberately: this generator holds no PAT and never
            # decrypts one -- it reads the module out of the vector index rather than
            # re-cloning (spec 2.2), so there is no secret in scope. `scrub` only
            # redacts secrets it is handed, so calling it with none would be a no-op
            # that merely looks like a control.
            #
            # Retrying re-scrolls the same empty prefix forever. The operator has to
            # fix the path, so tell them rather than circling the ladder.
            raise TerminalIngestionError(f"no indexed file matches {path_prefix!r} in this project")
        return rebuild_files(payloads, chunk_overlap=self.settings.chunk_overlap)

    async def _observe(self, file: ModuleFile) -> list[tuple[str, str, int, int]]:
        """One call for one file: what it exposes, raises, returns, and validates."""
        model = self.chat_model.with_structured_output(FileObservations)
        try:
            result = await model.ainvoke(build_map_prompt(file))
        except Exception as error:
            raise classify_chat_error(error) or error from error
        if not isinstance(result, FileObservations):
            return []
        return [
            (file.path, behaviour.description, behaviour.start_line, behaviour.end_line)
            for behaviour in result.behaviours
        ]

    async def _propose(
        self, *, module_name: str, source: ModuleSource, existing: list[ExistingItem]
    ) -> ProposedChangeSet:
        """Map over the files, then reduce once against the existing checklist."""
        semaphore = asyncio.Semaphore(self.settings.checklist_map_concurrency)

        async def observe(file: ModuleFile) -> list[tuple[str, str, int, int]]:
            async with semaphore:
                return await self._observe(file)

        # A `TaskGroup` rather than `asyncio.gather`: gather with the default
        # `return_exceptions=False` propagates the first failure but leaves its
        # siblings running -- still holding semaphore permits and still calling the
        # model -- after `run` has already unwound into the consumer's failure path.
        # A TaskGroup cancels them.
        try:
            async with asyncio.TaskGroup() as group:
                tasks = [group.create_task(observe(file)) for file in source.files]
        except* Exception as failures:
            # Re-raise the first cause unwrapped: `_read_source` and the consumer
            # classify on `TerminalIngestionError`/`RetryableIngestionError`, and an
            # `ExceptionGroup` matches neither -- it would fall through to the
            # unclassified path and dead-letter with a misleading reason.
            raise failures.exceptions[0] from None
        observations = [entry for task in tasks for entry in task.result()]

        model = self.chat_model.with_structured_output(ProposedChangeSet)
        try:
            result = await model.ainvoke(
                build_reduce_prompt(
                    module_name=module_name,
                    observations=observations,
                    existing=existing,
                    partial_paths=source.partial_paths,
                    skipped_paths=source.skipped_paths,
                )
            )
        except Exception as error:
            raise classify_chat_error(error) or error from error
        if not isinstance(result, ProposedChangeSet):
            raise TerminalChatError("the reduce step returned an unusable shape")
        return result

    def _to_operations(
        self, proposal: ProposedChangeSet, *, source: ModuleSource
    ) -> list[dict[str, object]]:
        """The model's proposal as stored JSON, with citations resolved here.

        The model names file paths; this supplies the line ranges, because a model
        asked for line numbers invents plausible ones. A path the model named that is
        not in the module is dropped rather than carried with a fabricated range -- a
        citation nobody can follow is worse than no citation.
        """
        ranges = {
            file.path: (file.start_line, file.end_line, file.language) for file in source.files
        }
        operations: list[dict[str, object]] = []
        for operation in proposal.operations:
            citations: list[dict[str, object]] = [
                {
                    "index": position + 1,
                    "file_path": path,
                    "start_line": ranges[path][0],
                    "end_line": ranges[path][1],
                    "language": ranges[path][2],
                    "symbol": None,
                    "commit_sha": "",
                    "score": 0.0,
                    "cited": True,
                }
                for position, path in enumerate(
                    [path for path in operation.citation_paths if path in ranges]
                )
            ]
            stored = stored_operation(operation, citations=citations)
            if stored is not None:
                operations.append(stored)
        return operations

    @staticmethod
    def _summarise(
        operations: list[dict[str, object]], *, source: ModuleSource, max_files: int
    ) -> str:
        """One line, naming the coverage bound rather than hiding it (spec 4.6).

        Counts the **stored** operations, not the model's proposal. `_to_operations`
        can drop one -- an `update` naming a row that does not exist -- and a summary
        counting the proposal would then describe a change set the reader cannot see.
        That divergence is not cosmetic: it once read "8 added" above an empty panel,
        which looks like a broken screen rather than a dropped operation.
        """
        counts = {"add": 0, "update": 0, "remove": 0}
        for operation in operations:
            counts[str(operation["op"])] += 1
        parts = [
            f"{counts['add']} added",
            f"{counts['update']} updated",
            f"{counts['remove']} removed",
            f"from {len(source.files)} files",
        ]
        if source.partial_paths:
            parts.append(f"partial: {', '.join(source.partial_paths)}")
        if source.skipped_paths:
            parts.append(
                f"skipped: {len(source.skipped_paths)} files over the {max_files}-file cap"
            )
        return "; ".join(parts)

"""One indexing run: clone, walk, chunk, embed, upsert, swap.

The generation swap is the part to read carefully. New points are written under
`active_generation + 1`, the project's pointer flips, and only then is the old
generation deleted. Two consequences, both intended: a project stays queryable
throughout a reindex, and a reindex that fails part-way leaves the working index
completely intact. Deleting first — the obvious implementation — destroys a working
index whenever embedding fails (spec §6.5).
"""

import asyncio
import logging
import shutil
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.crypto import SecretBox, scrub
from app.core.repo_url import ValidatedRepoUrl, validate_repo_url
from app.db.session import get_sessionmaker
from app.ingestion.chunker import Chunk, Chunker, embedding_text
from app.ingestion.cloner import CloneResult, clone
from app.ingestion.embedder import Embedder
from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError
from app.ingestion.vector_store import VectorStore
from app.ingestion.walker import walk
from app.models.project import ProjectStatus
from app.repositories.project import ProjectRepository

logger = logging.getLogger(__name__)

LEASE_SECONDS = 300
LEASE_RENEWAL_SECONDS = 60
# `Project.error` is String(4096); leave room rather than sitting on the boundary.
MAX_RECORDED_ERROR_CHARS = 4000

CloneFn = Callable[..., Awaitable[CloneResult]]


class IngestionPipeline:
    """Runs one job for one project."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        embedder: Embedder,
        store: VectorStore,
        chunker: Chunker,
        clone_fn: CloneFn = clone,
    ) -> None:
        self.session = session
        self.settings = settings
        self.embedder = embedder
        self.store = store
        self.chunker = chunker
        self.clone_fn = clone_fn
        self.repository = ProjectRepository(session)

    async def run(self, *, project_id: uuid.UUID, job_id: uuid.UUID, worker_id: str) -> None:
        """Index a project the caller has already claimed.

        Raises the ingestion error it failed with, so the consumer can decide between
        the retry chain and the dead-letter queue. A terminal failure is recorded on
        the project first; a retryable one is not, because the job is coming back.
        """
        project = await self.repository.get(project_id)
        if project is None:
            logger.warning("project %s vanished before indexing", project_id)
            return

        pat = None
        if project.encrypted_pat:
            pat = SecretBox(self.settings.pat_encryption_key).decrypt(project.encrypted_pat)

        # Where the clone is asked to land. The cloner is the authority on where it
        # actually landed, so the cleanup path is corrected once it returns.
        cleanup_path = self.settings.repo_scratch_dir / str(project_id)
        heartbeat = asyncio.create_task(self._renew_lease(project_id, worker_id))

        try:
            result = await self._clone(project.repo_url, project.branch, cleanup_path, pat)
            cleanup_path = result.path
            await self._advance_status(project_id, project.status)

            # Read before the release below writes the new value: `release` is an
            # ORM-enabled bulk UPDATE, so it synchronises this attribute in place and
            # reading it afterwards would name the generation we just wrote.
            superseded_generation = project.active_generation
            generation = superseded_generation + 1
            file_count, chunk_count = await self._index(
                project_id=project_id,
                generation=generation,
                root=result.path,
                commit_sha=result.commit_sha,
            )

            # Flip the pointer, then drop the superseded points.
            await self.repository.release(
                project_id=project_id,
                job_id=job_id,
                status=ProjectStatus.READY,
                error=None,
                last_indexed_commit=result.commit_sha,
                file_count=file_count,
                chunk_count=chunk_count,
                active_generation=generation,
                embedding_collection=self.store.collection,
                embedding_model=self.embedder.model_id,
            )
            await self.session.commit()

            if superseded_generation:
                await self.store.delete_generation(
                    project_id=project_id, generation=superseded_generation
                )

        except TerminalIngestionError as error:
            await self.repository.release(
                project_id=project_id,
                job_id=job_id,
                status=ProjectStatus.FAILED,
                error=scrub(str(error), pat)[:MAX_RECORDED_ERROR_CHARS],
            )
            await self.session.commit()
            raise
        except RetryableIngestionError:
            # Drop the lease but leave the status alone — the job is coming back, and
            # marking it `failed` would lie to anyone reading the list.
            await self.repository.renew_lease(
                project_id=project_id, worker_id=worker_id, lease_seconds=-1
            )
            await self.session.commit()
            raise
        finally:
            await self._stop(heartbeat, project_id)
            # docs/PRD.md §4.1: the working copy goes whether we succeeded or failed
            # terminally. /data/repos is scratch space.
            shutil.rmtree(cleanup_path, ignore_errors=True)

    async def _clone(
        self, repo_url: str, branch: str, destination: Path, pat: str | None
    ) -> CloneResult:
        """Validate and clone, pinning git to the address that was validated."""
        validated: ValidatedRepoUrl = await validate_repo_url(
            repo_url, allowlist=self.settings.repo_host_allowlist
        )
        return await self.clone_fn(
            validated,
            branch=branch,
            destination=destination,
            pat=pat,
            timeout_seconds=self.settings.clone_timeout_seconds,
            max_bytes=self.settings.repo_max_size_mb * 1024 * 1024,
        )

    async def _index(
        self, *, project_id: uuid.UUID, generation: int, root: Path, commit_sha: str
    ) -> tuple[int, int]:
        """Walk, chunk, embed, and upsert. Returns (file_count, chunk_count)."""
        await self.store.ensure_collection()

        batch_size = self.settings.embedding_batch_size
        file_count = 0
        chunk_count = 0
        batch: list[Chunk] = []

        for source_file in walk(root, max_file_bytes=self.settings.max_indexed_file_bytes):
            try:
                source = source_file.path.read_text(errors="replace")
            except OSError:
                logger.warning("skipping unreadable file %s", source_file.relative_path)
                continue

            file_count += 1
            batch.extend(self.chunker.split(source_file, source))
            while len(batch) >= batch_size:
                head, batch = batch[:batch_size], batch[batch_size:]
                await self._flush(project_id, generation, head, commit_sha)
                chunk_count += len(head)

        if batch:
            await self._flush(project_id, generation, batch, commit_sha)
            chunk_count += len(batch)

        return file_count, chunk_count

    async def _flush(
        self, project_id: uuid.UUID, generation: int, chunks: list[Chunk], commit_sha: str
    ) -> None:
        """Embed one batch and write it."""
        vectors = await self.embedder.embed_documents([embedding_text(chunk) for chunk in chunks])
        await self.store.upsert(
            project_id=project_id,
            generation=generation,
            chunks=chunks,
            vectors=vectors,
            commit_sha=commit_sha,
        )

    async def _advance_status(self, project_id: uuid.UUID, current_status: str) -> None:
        """Move a first index on to `indexing` once the clone is in.

        A reindex is skipped deliberately: it stays `ready` so the project remains
        queryable, and `reindex_in_progress` carries the fact that a run is active
        (spec §6.5).
        """
        if current_status == ProjectStatus.READY.value:
            return
        await self.repository.set_status(project_id=project_id, status=ProjectStatus.INDEXING)
        await self.session.commit()

    async def _renew_lease(self, project_id: uuid.UUID, worker_id: str) -> None:
        """Extend the lease while the job runs.

        This is what lets the expiry be five minutes rather than thirty: a slow but
        healthy index keeps extending, while a crashed worker releases its project for
        reclaim quickly (spec §4.2).

        Each tick uses its own short-lived session, never the one the job is running
        on: an `AsyncSession` is not safe for concurrent use, and two coroutines
        interleaving on one connection fail with an `InterfaceError` or, worse, a
        mis-scoped transaction.
        """
        while True:
            await asyncio.sleep(LEASE_RENEWAL_SECONDS)
            async with get_sessionmaker()() as session:
                held = await ProjectRepository(session).renew_lease(
                    project_id=project_id, worker_id=worker_id, lease_seconds=LEASE_SECONDS
                )
                await session.commit()
            if not held:
                logger.warning("lost the lease on project %s; stopping renewal", project_id)
                return

    async def _stop(self, heartbeat: asyncio.Task[None], project_id: uuid.UUID) -> None:
        """Cancel the heartbeat and collect it, so nothing fails silently."""
        heartbeat.cancel()
        try:
            await heartbeat
        except asyncio.CancelledError:
            pass
        except Exception:
            # The job's outcome is already decided; a failed renewal cannot change it,
            # but it must not disappear either.
            logger.warning("lease renewal for project %s failed", project_id, exc_info=True)

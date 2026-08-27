"""One indexing run, end to end, with the network stubbed out."""

import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.crypto import REDACTION, SecretBox
from app.core.repo_url import ValidatedRepoUrl
from app.db.session import get_sessionmaker
from app.ingestion import pipeline as pipeline_module
from app.ingestion.chunker import LanguageAwareChunker
from app.ingestion.cloner import CloneResult
from app.ingestion.embedder import FakeEmbedder
from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError
from app.ingestion.pipeline import IngestionPipeline
from app.ingestion.vector_store import InMemoryVectorStore
from app.models.project import ProjectStatus
from app.repositories.project import ProjectRepository
from tests.factories import create_project

COMMIT = "a" * 40


def make_repo(tmp_path: Path) -> Path:
    """A tiny real repository the fake cloner hands back."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "main.py").write_text("def main() -> None:\n    print('hi')\n")
    (root / "util.py").write_text("def helper() -> int:\n    return 42\n")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    return root


def pipeline_for(
    session: AsyncSession,
    store: InMemoryVectorStore,
    repo: Path,
    *,
    fail_with: Exception | None = None,
) -> IngestionPipeline:
    """A pipeline whose clone is a stub, so no test touches the network."""

    async def fake_clone(validated: ValidatedRepoUrl, **kwargs: object) -> CloneResult:
        if fail_with is not None:
            raise fail_with
        return CloneResult(path=repo, commit_sha=COMMIT)

    return IngestionPipeline(
        session,
        get_settings(),
        embedder=FakeEmbedder(dimensions=4),
        store=store,
        chunker=LanguageAwareChunker(chunk_size=1200, chunk_overlap=150),
        clone_fn=fake_clone,
    )


async def claim_for(session: AsyncSession, project_id: uuid.UUID) -> uuid.UUID:
    """Claim a project the way the consumer will, and return the job id."""
    job_id = uuid.uuid4()
    await ProjectRepository(session).claim(
        project_id=project_id, job_id=job_id, worker_id="w0", lease_seconds=300
    )
    await session.commit()
    return job_id


async def test_a_successful_run_reaches_ready(db_session: AsyncSession, tmp_path: Path) -> None:
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()
    store = InMemoryVectorStore(dimensions=4)
    job_id = await claim_for(db_session, project.id)

    await pipeline_for(db_session, store, make_repo(tmp_path)).run(
        project_id=project.id, job_id=job_id, worker_id="w0"
    )

    await db_session.refresh(project)
    assert project.status == ProjectStatus.READY
    assert project.last_indexed_commit == COMMIT
    assert project.file_count == 2
    assert project.chunk_count == len(store.points)
    assert project.lease_owner is None
    assert project.active_generation == 1
    assert project.embedding_collection == store.collection
    assert project.embedding_model == "fake"
    assert store.points


async def test_the_working_copy_is_deleted_after_indexing(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """docs/PRD.md §4.1: /data/repos is scratch, not a persistent volume.

    The cleanup has to target the directory the clone actually produced, not the one
    the pipeline would have asked for — see R10's sibling ruling R9.
    """
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()
    repo = make_repo(tmp_path)
    job_id = await claim_for(db_session, project.id)

    await pipeline_for(db_session, InMemoryVectorStore(dimensions=4), repo).run(
        project_id=project.id, job_id=job_id, worker_id="w0"
    )

    assert not repo.exists()


async def test_a_reindex_swaps_generations_without_losing_the_old_index(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """The old generation survives until the new one is fully written."""
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()
    store = InMemoryVectorStore(dimensions=4)

    for _ in range(2):
        job_id = await claim_for(db_session, project.id)
        await pipeline_for(db_session, store, make_repo(tmp_path)).run(
            project_id=project.id, job_id=job_id, worker_id="w0"
        )

    await db_session.refresh(project)
    assert project.active_generation == 2
    assert project.reindex_in_progress is False
    # Only the current generation survives the swap, and it survives in full.
    assert {point["payload"]["generation"] for point in store.points} == {2}
    assert len(store.points) == project.chunk_count


async def test_a_terminal_failure_marks_the_project_failed(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()
    job_id = await claim_for(db_session, project.id)

    pipeline = pipeline_for(
        db_session,
        InMemoryVectorStore(dimensions=4),
        tmp_path / "unused",
        fail_with=TerminalIngestionError("Remote branch nope not found in upstream origin"),
    )

    with pytest.raises(TerminalIngestionError):
        await pipeline.run(project_id=project.id, job_id=job_id, worker_id="w0")

    await db_session.refresh(project)
    assert project.status == ProjectStatus.FAILED
    assert project.error is not None
    assert project.lease_owner is None


async def test_a_pat_never_reaches_the_recorded_error(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """docs/PRD.md §9: a token must not survive into anything an operator can read."""
    pat = "ghp_averysecrettoken"
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    project.encrypted_pat = SecretBox(get_settings().pat_encryption_key).encrypt(pat)
    await db_session.commit()
    job_id = await claim_for(db_session, project.id)

    pipeline = pipeline_for(
        db_session,
        InMemoryVectorStore(dimensions=4),
        tmp_path / "unused",
        fail_with=TerminalIngestionError(f"fatal: could not read https://{pat}@github.com/a/b"),
    )

    with pytest.raises(TerminalIngestionError):
        await pipeline.run(project_id=project.id, job_id=job_id, worker_id="w0")

    await db_session.refresh(project)
    assert project.error is not None
    assert pat not in project.error
    assert REDACTION in project.error


async def test_a_retryable_failure_leaves_the_project_claimable(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """The consumer will re-enqueue it, so the pipeline must not mark it failed.

    Claimability, not a cleared `lease_owner`, is the guarantee: spec §4.2 clears the
    owner on *terminal* completion, and `ProjectRepository.claim` gates on the lease
    having expired rather than on who last held it.
    """
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()
    job_id = await claim_for(db_session, project.id)

    pipeline = pipeline_for(
        db_session,
        InMemoryVectorStore(dimensions=4),
        tmp_path / "unused",
        fail_with=RetryableIngestionError("connection reset"),
    )

    with pytest.raises(RetryableIngestionError):
        await pipeline.run(project_id=project.id, job_id=job_id, worker_id="w0")

    await db_session.refresh(project)
    assert project.status != ProjectStatus.FAILED
    assert project.lease_expires_at is not None
    assert project.lease_expires_at < datetime.now(UTC)
    assert await ProjectRepository(db_session).claim(
        project_id=project.id, job_id=uuid.uuid4(), worker_id="w1", lease_seconds=300
    )


async def test_the_lease_heartbeat_runs_on_a_session_of_its_own(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R10: the heartbeat must not share the `AsyncSession` the job is using.

    The stub clone keeps the pipeline's own session busy with a real query for the
    whole window in which the heartbeat ticks, which is exactly the interleaving an
    `AsyncSession` cannot survive. A heartbeat sharing that session raises inside its
    task, dies unnoticed, and renews nothing — so this asserts a renewal was actually
    observed mid-run, not merely that the run finished.
    """
    monkeypatch.setattr(pipeline_module, "LEASE_RENEWAL_SECONDS", 0.05)
    monkeypatch.setattr(pipeline_module, "LEASE_SECONDS", 900)

    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()
    repo = make_repo(tmp_path)
    job_id = await claim_for(db_session, project.id)
    await db_session.refresh(project)
    claimed_until = project.lease_expires_at
    assert claimed_until is not None

    observed: list[datetime] = []

    async def busy_clone(validated: ValidatedRepoUrl, **kwargs: object) -> CloneResult:
        """Hold the job's session mid-query, then look at the lease from outside it."""
        for _ in range(4):
            await db_session.execute(text("SELECT pg_sleep(0.1)"))
            async with get_sessionmaker()() as watcher:
                row = await ProjectRepository(watcher).get(project.id)
                if row is not None and row.lease_expires_at is not None:
                    observed.append(row.lease_expires_at)
        return CloneResult(path=repo, commit_sha=COMMIT)

    pipeline = IngestionPipeline(
        db_session,
        get_settings(),
        embedder=FakeEmbedder(dimensions=4),
        store=InMemoryVectorStore(dimensions=4),
        chunker=LanguageAwareChunker(chunk_size=1200, chunk_overlap=150),
        clone_fn=busy_clone,
    )
    await pipeline.run(project_id=project.id, job_id=job_id, worker_id="w0")

    await db_session.refresh(project)
    assert project.status == ProjectStatus.READY
    assert any(seen > claimed_until for seen in observed), (
        f"the lease was never renewed while the job ran: {observed}"
    )

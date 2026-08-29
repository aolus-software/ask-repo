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


async def claim_for(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    worker_id: str = "w0",
    lease_seconds: int = 300,
) -> uuid.UUID:
    """Claim a project the way the consumer will, and return the job id."""
    job_id = uuid.uuid4()
    await ProjectRepository(session).claim(
        project_id=project_id,
        job_id=job_id,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
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


async def test_a_rejected_repo_url_is_terminal(db_session: AsyncSession, tmp_path: Path) -> None:
    """Spec §4.4 lists a rejected URL as its first terminal example.

    `RepoUrlRejected` is a plain `Exception`, so unclassified it escapes `run()` past
    both handlers: the row keeps its lease, keeps `error` NULL, and reports `cloning`
    forever while the reconcile sweep re-enqueues it every 60 seconds — each iteration
    re-cloning and re-embedding the whole repository.
    """
    project = await create_project(
        db_session, status=ProjectStatus.PENDING, repo_url="http://github.com/acme/repo.git"
    )
    await db_session.commit()
    job_id = await claim_for(db_session, project.id)

    pipeline = pipeline_for(db_session, InMemoryVectorStore(dimensions=4), make_repo(tmp_path))
    with pytest.raises(TerminalIngestionError):
        await pipeline.run(project_id=project.id, job_id=job_id, worker_id="w0")

    await db_session.refresh(project)
    assert project.status == ProjectStatus.FAILED
    assert project.error is not None
    assert "https" in project.error
    assert project.lease_owner is None
    assert project.reindex_in_progress is False


async def test_a_project_deleted_mid_run_keeps_none_of_its_chunks(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """docs/PRD.md §5.1: deleting a project takes its vectors with it, always.

    The delete reads `embedding_collection` — written only by `release`, so still NULL
    while a first index is running — and correctly skips Qdrant. That leaves the
    in-flight run as the only thing that can clean up after itself, and it only knows
    to because `release` refuses the soft-deleted row.
    """
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()
    project_id = project.id
    store = InMemoryVectorStore(dimensions=4)
    repo = make_repo(tmp_path)
    job_id = await claim_for(db_session, project_id)

    async def delete_then_clone(validated: ValidatedRepoUrl, **kwargs: object) -> CloneResult:
        """Someone deletes the project while the clone is in flight."""
        async with get_sessionmaker()() as other:
            repository = ProjectRepository(other)
            row = await repository.get(project_id)
            assert row is not None
            assert row.embedding_collection is None
            await repository.soft_delete(row)
            await other.commit()
        return CloneResult(path=repo, commit_sha=COMMIT)

    pipeline = IngestionPipeline(
        db_session,
        get_settings(),
        embedder=FakeEmbedder(dimensions=4),
        store=store,
        chunker=LanguageAwareChunker(chunk_size=1200, chunk_overlap=150),
        clone_fn=delete_then_clone,
    )
    await pipeline.run(project_id=project_id, job_id=job_id, worker_id="w0")

    assert store.points == []
    # A session of its own: `db_session`'s identity map still holds the pre-delete
    # attributes, so reading through it would assert against a stale copy.
    async with get_sessionmaker()() as reader:
        row = await ProjectRepository(reader).get_including_deleted(project_id)
        assert row is not None
        assert row.deleted_at is not None
        assert row.embedding_collection is None
        assert row.status != ProjectStatus.READY


async def test_a_worker_that_lost_its_lease_records_no_outcome(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """Two workers on one project: the loser must not overwrite the winner's row.

    Its points are left alone rather than deleted — the new owner derives the same
    generation number from the same pointer, so dropping that generation could
    destroy what the winning run wrote.
    """
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()
    project_id = project.id
    store = InMemoryVectorStore(dimensions=4)
    repo = make_repo(tmp_path)
    # An already-expired lease, so a second worker can take the project mid-run.
    job_id = await claim_for(db_session, project_id, lease_seconds=-1)

    async def steal_then_clone(validated: ValidatedRepoUrl, **kwargs: object) -> CloneResult:
        async with get_sessionmaker()() as other:
            assert await ProjectRepository(other).claim(
                project_id=project_id,
                job_id=uuid.uuid4(),
                worker_id="w1",
                lease_seconds=300,
            )
            await other.commit()
        return CloneResult(path=repo, commit_sha=COMMIT)

    pipeline = IngestionPipeline(
        db_session,
        get_settings(),
        embedder=FakeEmbedder(dimensions=4),
        store=store,
        chunker=LanguageAwareChunker(chunk_size=1200, chunk_overlap=150),
        clone_fn=steal_then_clone,
    )
    await pipeline.run(project_id=project_id, job_id=job_id, worker_id="w0")

    await db_session.refresh(project)
    assert project.lease_owner == "w1"
    assert project.status != ProjectStatus.READY
    assert project.active_generation == 0
    assert project.embedding_collection is None
    assert store.points, "the loser's points belong to the new owner's generation"


async def test_an_unexpected_error_does_not_strand_the_reindex_flag(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """R17: `claim` sets `reindex_in_progress` and only `release` clears it.

    A run that ends through neither leaves the flag True forever, and
    `ProjectService.reindex` then answers `enqueued: false` with no route, flag, or
    admin action able to clear it — the project is stuck on its old index.
    """
    project = await create_project(db_session, status=ProjectStatus.READY)
    await db_session.commit()
    job_id = await claim_for(db_session, project.id)
    await db_session.refresh(project)
    assert project.reindex_in_progress is True

    pipeline = pipeline_for(
        db_session,
        InMemoryVectorStore(dimensions=4),
        tmp_path / "unused",
        fail_with=RuntimeError("a bug nobody classified"),
    )
    with pytest.raises(RuntimeError):
        await pipeline.run(project_id=project.id, job_id=job_id, worker_id="w0")

    await db_session.refresh(project)
    assert project.reindex_in_progress is False
    # The outcome stays the consumer's call: retry once, then dead-letter (spec §4.4).
    assert project.status == ProjectStatus.READY
    assert await ProjectRepository(db_session).claim(
        project_id=project.id, job_id=uuid.uuid4(), worker_id="w1", lease_seconds=300
    )


async def test_an_undecryptable_pat_does_not_strand_the_project(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """The decrypt sits on the path into the run, so it must be inside the handlers.

    A rotated `PAT_ENCRYPTION_KEY` makes `SecretBox.decrypt` raise before the clone
    is even attempted — outside the `try` that would be a stranded lease and a
    permanently raised reindex flag.
    """
    project = await create_project(db_session, status=ProjectStatus.READY)
    project.encrypted_pat = b"not-a-token-this-key-can-read"
    await db_session.commit()
    job_id = await claim_for(db_session, project.id)

    pipeline = pipeline_for(db_session, InMemoryVectorStore(dimensions=4), make_repo(tmp_path))
    with pytest.raises(ValueError, match="could not be decrypted"):
        await pipeline.run(project_id=project.id, job_id=job_id, worker_id="w0")

    await db_session.refresh(project)
    assert project.reindex_in_progress is False
    assert project.lease_owner is None


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

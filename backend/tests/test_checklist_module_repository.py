"""Module persistence, and the lease that makes generation safe under redelivery."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import ProjectScope
from app.models.checklist import ChecklistModuleStatus
from app.repositories.checklist_module import LEASE_SECONDS, ChecklistModuleRepository
from tests.factories import create_checklist_module, create_project, create_user


async def test_list_page_is_scoped_and_never_filters_on_creator(
    db_session: AsyncSession,
) -> None:
    """Phase 1 shares everything. A module someone else created is still listed --
    `created_by` gates destruction, never reads (docs/PRD.md 4.1)."""
    mine = await create_checklist_module(db_session, name="Auth")
    theirs = await create_checklist_module(db_session, name="Billing")
    repository = ChecklistModuleRepository(db_session)

    rows, total = await repository.list_page(
        scope=ProjectScope.all(), page=1, limit=25, sort="created_at", descending=True
    )

    assert total == 2
    assert {row.id for row in rows} == {mine.id, theirs.id}


async def test_list_page_with_an_empty_scope_returns_nothing(
    db_session: AsyncSession,
) -> None:
    """An empty scope means no access, never all of it -- the fail-open trap
    `ProjectScope` exists to close."""
    await create_checklist_module(db_session)
    repository = ChecklistModuleRepository(db_session)

    rows, total = await repository.list_page(
        scope=ProjectScope.of([]), page=1, limit=25, sort="created_at", descending=True
    )

    assert (rows, total) == ([], 0)


async def test_unknown_sort_field_raises(db_session: AsyncSession) -> None:
    """`sort` arrives from a query parameter; an unchecked column name would expose
    every column on the table."""
    repository = ChecklistModuleRepository(db_session)
    with pytest.raises(ValueError, match="error"):
        await repository.list_page(
            scope=ProjectScope.all(), page=1, limit=25, sort="error", descending=True
        )


async def test_claim_succeeds_once_and_refuses_the_redelivery(
    db_session: AsyncSession,
) -> None:
    """Kafka is at-least-once. The lease -- not the offset -- is what stops two
    workers generating the same module (spec 4.5)."""
    module = await create_checklist_module(db_session)
    repository = ChecklistModuleRepository(db_session)
    job_id = uuid.uuid4()

    assert await repository.claim(
        module_id=module.id, job_id=job_id, worker_id="worker-a", lease_seconds=LEASE_SECONDS
    )
    assert not await repository.claim(
        module_id=module.id, job_id=job_id, worker_id="worker-b", lease_seconds=LEASE_SECONDS
    )

    await db_session.refresh(module)
    assert module.status == ChecklistModuleStatus.GENERATING.value
    assert module.lease_owner == "worker-a"
    assert module.last_job_id == job_id


async def test_claim_refuses_a_replay_of_a_finished_job(db_session: AsyncSession) -> None:
    """A finished job cleared its lease; without the `last_job_id` gate, a redelivered
    message would start an unwanted second generation."""
    module = await create_checklist_module(db_session)
    repository = ChecklistModuleRepository(db_session)
    job_id = uuid.uuid4()

    await repository.claim(
        module_id=module.id, job_id=job_id, worker_id="worker-a", lease_seconds=LEASE_SECONDS
    )
    await repository.release(
        module_id=module.id,
        job_id=job_id,
        worker_id="worker-a",
        status=ChecklistModuleStatus.REVIEW,
    )

    assert not await repository.claim(
        module_id=module.id, job_id=job_id, worker_id="worker-a", lease_seconds=LEASE_SECONDS
    )


async def test_release_is_refused_once_the_lease_moved_on(db_session: AsyncSession) -> None:
    """A write that starts is not entitled to finish. A worker whose lease expired
    and was reclaimed must not overwrite the winner's outcome
    (.claude/rules/persistence.md)."""
    module = await create_checklist_module(db_session)
    repository = ChecklistModuleRepository(db_session)
    first, second = uuid.uuid4(), uuid.uuid4()

    await repository.claim(module_id=module.id, job_id=first, worker_id="worker-a", lease_seconds=0)
    await repository.claim(
        module_id=module.id, job_id=second, worker_id="worker-b", lease_seconds=LEASE_SECONDS
    )

    assert not await repository.release(
        module_id=module.id,
        job_id=first,
        worker_id="worker-a",
        status=ChecklistModuleStatus.FAILED,
        error="whatever",
    )
    await db_session.refresh(module)
    assert module.error is None


async def test_release_is_refused_on_a_soft_deleted_module(
    db_session: AsyncSession,
) -> None:
    """A module deleted mid-generation must not be written back to life."""
    module = await create_checklist_module(db_session)
    repository = ChecklistModuleRepository(db_session)
    job_id = uuid.uuid4()
    await repository.claim(
        module_id=module.id, job_id=job_id, worker_id="worker-a", lease_seconds=LEASE_SECONDS
    )
    await repository.soft_delete(module)

    assert not await repository.release(
        module_id=module.id,
        job_id=job_id,
        worker_id="worker-a",
        status=ChecklistModuleStatus.REVIEW,
    )


async def test_find_stranded_returns_a_module_whose_lease_expired(
    db_session: AsyncSession,
) -> None:
    """A worker that died holding a lease is recovered by the reconcile sweep."""
    module = await create_checklist_module(db_session, status=ChecklistModuleStatus.GENERATING)
    module.lease_expires_at = datetime.now(UTC) - timedelta(seconds=10)
    module.updated_at = datetime.now(UTC) - timedelta(seconds=600)
    await db_session.flush()
    repository = ChecklistModuleRepository(db_session)

    stranded = await repository.claim_stranded(generating_older_than_seconds=120)

    assert stranded == [module.id]


async def test_soft_delete_for_project_takes_every_creators_modules(
    db_session: AsyncSession,
) -> None:
    """The project was shared, so its modules belong to several people and all go."""
    project = await create_project(db_session)
    other = await create_user(db_session)
    await create_checklist_module(db_session, project_id=project.id)
    await create_checklist_module(db_session, project_id=project.id, created_by=other.id)
    repository = ChecklistModuleRepository(db_session)

    assert await repository.soft_delete_for_project(project.id) == 2
    rows, _ = await repository.list_page(
        scope=ProjectScope.all(), page=1, limit=25, sort="created_at", descending=True
    )
    assert rows == []


async def test_claim_stranded_stamps_the_rows_it_returns(db_session: AsyncSession) -> None:
    """A swept module must not be swept again on the next tick.

    The sweep publishes with a fresh `job_id` precisely so the claim cannot refuse
    it, which means a duplicate costs a whole generation rather than one skipped
    poll. Stamping `updated_at` is what stops the 60-second tick re-publishing the
    same module until something else changes it.
    """
    module = await create_checklist_module(db_session, status=ChecklistModuleStatus.GENERATING)
    module.lease_expires_at = datetime.now(UTC) - timedelta(seconds=10)
    module.updated_at = datetime.now(UTC) - timedelta(seconds=600)
    await db_session.flush()
    repository = ChecklistModuleRepository(db_session)

    first = await repository.claim_stranded(generating_older_than_seconds=120)
    second = await repository.claim_stranded(generating_older_than_seconds=120)

    assert first == [module.id]
    assert second == []


async def test_defer_drops_the_lease_and_stays_generating(db_session: AsyncSession) -> None:
    """A run that ended but is coming back releases its lease.

    The claim commits before generation starts, so a failure that only rolls back
    leaves a 300-second lease held by a run that is over -- and the retry scheduled
    one minute later is refused by its own dead predecessor. Status stays
    `generating` because the job really is coming back; `failed` would lie.
    """
    module = await create_checklist_module(db_session, status=ChecklistModuleStatus.GENERATING)
    repository = ChecklistModuleRepository(db_session)
    job_id = uuid.uuid4()
    assert await repository.claim(
        module_id=module.id, job_id=job_id, worker_id="worker-a", lease_seconds=LEASE_SECONDS
    )

    assert await repository.defer(module_id=module.id, worker_id="worker-a") is True

    await db_session.refresh(module)
    assert module.lease_owner is None
    assert module.lease_expires_at is None
    assert module.status == ChecklistModuleStatus.GENERATING.value
    # The successor can now take it, which is the whole point.
    assert await repository.claim(
        module_id=module.id,
        job_id=uuid.uuid4(),
        worker_id="worker-b",
        lease_seconds=LEASE_SECONDS,
    )


async def test_defer_refuses_when_another_worker_owns_the_lease(
    db_session: AsyncSession,
) -> None:
    """Same guard as `release`: a run that lost its lease cannot write to the row."""
    module = await create_checklist_module(db_session, status=ChecklistModuleStatus.GENERATING)
    repository = ChecklistModuleRepository(db_session)
    assert await repository.claim(
        module_id=module.id,
        job_id=uuid.uuid4(),
        worker_id="worker-a",
        lease_seconds=LEASE_SECONDS,
    )

    assert await repository.defer(module_id=module.id, worker_id="worker-b") is False

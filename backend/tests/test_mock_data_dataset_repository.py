"""Dataset persistence, and the lease that makes generation safe under redelivery."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mock_data import MockDataDatasetStatus
from app.repositories.mock_data_dataset import MockDataDatasetRepository
from tests.factories import create_checklist_module


async def test_get_or_create_for_module_creates_once(db_session: AsyncSession) -> None:
    """A module can carry a checklist, a mock dataset, both, or neither -- so there is
    no dataset row until the first generation is requested against this module."""
    module = await create_checklist_module(db_session)
    repo = MockDataDatasetRepository(db_session)

    first = await repo.get_or_create_for_module(module.id)
    await db_session.commit()
    second = await repo.get_or_create_for_module(module.id)

    assert first.id == second.id
    assert first.status == MockDataDatasetStatus.EMPTY.value


async def test_claim_refuses_a_live_lease(db_session: AsyncSession) -> None:
    """Kafka is at-least-once. The lease -- not the offset -- is what stops two
    workers generating the same dataset."""
    module = await create_checklist_module(db_session)
    repo = MockDataDatasetRepository(db_session)
    dataset = await repo.get_or_create_for_module(module.id)
    await db_session.commit()

    job_id = uuid.uuid4()
    assert await repo.claim(dataset_id=dataset.id, job_id=job_id, worker_id="w1", lease_seconds=300)
    await db_session.commit()

    assert not await repo.claim(
        dataset_id=dataset.id, job_id=uuid.uuid4(), worker_id="w2", lease_seconds=300
    )


async def test_release_requires_the_holding_worker(db_session: AsyncSession) -> None:
    """A release must be guarded on lease_owner, so a worker whose lease expired
    cannot overwrite the winner's outcome."""
    module = await create_checklist_module(db_session)
    repo = MockDataDatasetRepository(db_session)
    dataset = await repo.get_or_create_for_module(module.id)
    await db_session.commit()
    job_id = uuid.uuid4()
    await repo.claim(dataset_id=dataset.id, job_id=job_id, worker_id="w1", lease_seconds=300)
    await db_session.commit()

    assert not await repo.release(
        dataset_id=dataset.id,
        job_id=job_id,
        worker_id="someone-else",
        status=MockDataDatasetStatus.READY,
    )
    assert await repo.release(
        dataset_id=dataset.id, job_id=job_id, worker_id="w1", status=MockDataDatasetStatus.READY
    )


async def test_claim_stranded_stamps_updated_at(db_session: AsyncSession) -> None:
    """The sweep re-publishes with a fresh job_id so the claim cannot refuse it --
    which means a duplicate costs a whole generation. Stamping updated_at is what
    stops the sweep re-publishing the same dataset forever."""
    module = await create_checklist_module(db_session)
    repo = MockDataDatasetRepository(db_session)
    dataset = await repo.get_or_create_for_module(module.id)
    dataset.status = MockDataDatasetStatus.GENERATING.value
    dataset.updated_at = datetime.now(UTC) - timedelta(seconds=999)
    await db_session.commit()

    stranded = await repo.claim_stranded(generating_older_than_seconds=120)
    await db_session.commit()

    assert dataset.id in stranded
    # A second call finds nothing: the first call's stamp moved it outside the window.
    assert dataset.id not in await repo.claim_stranded(generating_older_than_seconds=120)


async def test_claim_refuses_a_replay_of_a_finished_job(db_session: AsyncSession) -> None:
    """A finished job cleared its lease; without the `last_job_id` gate, a redelivered
    message would start an unwanted second generation."""
    module = await create_checklist_module(db_session)
    repo = MockDataDatasetRepository(db_session)
    job_id = uuid.uuid4()

    await repo.claim(
        dataset_id=(dataset := await repo.get_or_create_for_module(module.id)).id,
        job_id=job_id,
        worker_id="w1",
        lease_seconds=300,
    )
    await repo.release(
        dataset_id=dataset.id,
        job_id=job_id,
        worker_id="w1",
        status=MockDataDatasetStatus.READY,
    )

    assert not await repo.claim(
        dataset_id=dataset.id, job_id=job_id, worker_id="w1", lease_seconds=300
    )


async def test_release_is_refused_once_the_lease_moved_on(db_session: AsyncSession) -> None:
    """A write that starts is not entitled to finish. A worker whose lease expired
    and was reclaimed must not overwrite the winner's outcome."""
    module = await create_checklist_module(db_session)
    repo = MockDataDatasetRepository(db_session)
    dataset = await repo.get_or_create_for_module(module.id)
    first, second = uuid.uuid4(), uuid.uuid4()

    await repo.claim(dataset_id=dataset.id, job_id=first, worker_id="w1", lease_seconds=0)
    await repo.claim(dataset_id=dataset.id, job_id=second, worker_id="w2", lease_seconds=300)

    assert not await repo.release(
        dataset_id=dataset.id,
        job_id=first,
        worker_id="w1",
        status=MockDataDatasetStatus.FAILED,
        error="whatever",
    )
    await db_session.refresh(dataset)
    assert dataset.error is None


async def test_release_is_refused_on_a_soft_deleted_dataset(
    db_session: AsyncSession,
) -> None:
    """A dataset deleted mid-generation must not be written back to life."""
    module = await create_checklist_module(db_session)
    repo = MockDataDatasetRepository(db_session)
    dataset = await repo.get_or_create_for_module(module.id)
    job_id = uuid.uuid4()
    await repo.claim(dataset_id=dataset.id, job_id=job_id, worker_id="w1", lease_seconds=300)
    await repo.soft_delete(dataset)

    assert not await repo.release(
        dataset_id=dataset.id,
        job_id=job_id,
        worker_id="w1",
        status=MockDataDatasetStatus.READY,
    )


async def test_renew_lease_succeeds_while_held(db_session: AsyncSession) -> None:
    """Extend our own lease. False means we lost it and must abandon the job."""
    module = await create_checklist_module(db_session)
    repo = MockDataDatasetRepository(db_session)
    dataset = await repo.get_or_create_for_module(module.id)
    job_id = uuid.uuid4()
    await repo.claim(dataset_id=dataset.id, job_id=job_id, worker_id="w1", lease_seconds=300)
    await db_session.commit()

    assert await repo.renew_lease(dataset_id=dataset.id, worker_id="w1", lease_seconds=300)


async def test_renew_lease_refuses_when_another_worker_owns_the_lease(
    db_session: AsyncSession,
) -> None:
    """A worker that does not hold the lease cannot renew it."""
    module = await create_checklist_module(db_session)
    repo = MockDataDatasetRepository(db_session)
    dataset = await repo.get_or_create_for_module(module.id)
    await repo.claim(dataset_id=dataset.id, job_id=uuid.uuid4(), worker_id="w1", lease_seconds=300)
    await db_session.commit()

    assert not await repo.renew_lease(dataset_id=dataset.id, worker_id="w2", lease_seconds=300)


async def test_mark_in_review_moves_status_to_review(db_session: AsyncSession) -> None:
    """Move a dataset to `review` because a proposal is now pending."""
    module = await create_checklist_module(db_session)
    repo = MockDataDatasetRepository(db_session)
    dataset = await repo.get_or_create_for_module(module.id)
    await db_session.commit()

    await repo.mark_in_review(dataset.id)
    await db_session.commit()

    await db_session.refresh(dataset)
    assert dataset.status == MockDataDatasetStatus.REVIEW.value


async def test_mark_in_review_does_not_clobber_a_generating_dataset(
    db_session: AsyncSession,
) -> None:
    """Defence in depth for the service-level guard in `prepare_turn`.

    A `generating` dataset is one a worker's lease still (or again) holds. Writing
    `review` over it would blind the reconcile sweep -- `status == "generating"` is the
    only thing that tells it a run is still alive -- and would leave a second pending
    change set behind if the worker finishes normally instead. The predicate makes the
    clobber impossible even if the service-level check is ever bypassed or removed.
    """
    module = await create_checklist_module(db_session)
    repo = MockDataDatasetRepository(db_session)
    dataset = await repo.get_or_create_for_module(module.id)
    await db_session.commit()
    claimed = await repo.claim(
        dataset_id=dataset.id, job_id=uuid.uuid4(), worker_id="worker-1", lease_seconds=300
    )
    await db_session.commit()
    assert claimed

    await repo.mark_in_review(dataset.id)
    await db_session.commit()

    await db_session.refresh(dataset)
    assert dataset.status == MockDataDatasetStatus.GENERATING.value


async def test_defer_drops_the_lease_and_stays_generating(db_session: AsyncSession) -> None:
    """A run that ended but is coming back releases its lease.

    The claim commits before generation starts, so a failure that only rolls back
    leaves a 300-second lease held by a run that is over -- and the retry scheduled
    one minute later is refused by its own dead predecessor. Status stays
    `generating` because the job really is coming back; `failed` would lie.
    """
    module = await create_checklist_module(db_session)
    repo = MockDataDatasetRepository(db_session)
    dataset = await repo.get_or_create_for_module(module.id)
    job_id = uuid.uuid4()
    assert await repo.claim(dataset_id=dataset.id, job_id=job_id, worker_id="w1", lease_seconds=300)

    assert await repo.defer(dataset_id=dataset.id, worker_id="w1") is True

    await db_session.refresh(dataset)
    assert dataset.lease_owner is None
    assert dataset.lease_expires_at is None
    assert dataset.status == MockDataDatasetStatus.GENERATING.value
    # The successor can now take it, which is the whole point.
    assert await repo.claim(
        dataset_id=dataset.id,
        job_id=uuid.uuid4(),
        worker_id="w2",
        lease_seconds=300,
    )


async def test_defer_refuses_when_another_worker_owns_the_lease(
    db_session: AsyncSession,
) -> None:
    """Same guard as `release`: a run that lost its lease cannot write to the row."""
    module = await create_checklist_module(db_session)
    repo = MockDataDatasetRepository(db_session)
    dataset = await repo.get_or_create_for_module(module.id)
    assert await repo.claim(
        dataset_id=dataset.id,
        job_id=uuid.uuid4(),
        worker_id="w1",
        lease_seconds=300,
    )

    assert await repo.defer(dataset_id=dataset.id, worker_id="w2") is False


async def test_soft_delete_for_module_soft_deletes_dataset(
    db_session: AsyncSession,
) -> None:
    """Soft-delete a module's dataset row."""
    module = await create_checklist_module(db_session)
    repo = MockDataDatasetRepository(db_session)
    dataset = await repo.get_or_create_for_module(module.id)
    await db_session.commit()

    count = await repo.soft_delete_for_module(module.id)

    assert count == 1
    await db_session.refresh(dataset)
    assert dataset.deleted_at is not None


async def test_soft_delete_for_project_soft_deletes_all_datasets(
    db_session: AsyncSession,
) -> None:
    """Soft-delete every dataset row of every module of a project."""
    from tests.factories import create_project

    project = await create_project(db_session)
    module1 = await create_checklist_module(db_session, project_id=project.id)
    module2 = await create_checklist_module(db_session, project_id=project.id)
    repo = MockDataDatasetRepository(db_session)
    dataset1 = await repo.get_or_create_for_module(module1.id)
    dataset2 = await repo.get_or_create_for_module(module2.id)
    await db_session.commit()

    count = await repo.soft_delete_for_project(project.id)

    assert count == 2
    await db_session.refresh(dataset1)
    await db_session.refresh(dataset2)
    assert dataset1.deleted_at is not None
    assert dataset2.deleted_at is not None

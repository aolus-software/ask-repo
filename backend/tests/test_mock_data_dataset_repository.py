"""Dataset persistence, and the lease that makes generation safe under redelivery."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mock_data import MockDataDataset, MockDataDatasetStatus
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
    assert await repo.claim(
        dataset_id=dataset.id, job_id=job_id, worker_id="w1", lease_seconds=300
    )
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

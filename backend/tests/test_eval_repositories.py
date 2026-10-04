"""Leases on eval sets and runs: the deduplication boundary for at-least-once jobs."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.eval import EvalRun, EvalRunStatus, EvalSet, EvalSetStatus
from app.repositories.eval_pair import EvalPairRepository
from app.repositories.eval_result import EvalResultRepository
from app.repositories.eval_run import EvalRunRepository
from app.repositories.eval_set import EvalSetRepository
from tests.factories import create_project, create_user


async def _generating_set(db_session: AsyncSession) -> EvalSet:
    user = await create_user(db_session)
    project = await create_project(db_session, created_by=user.id)
    row = EvalSet(
        id=uuid.uuid4(),
        project_id=project.id,
        name="s",
        requested_count=10,
        mix="balanced",
        status=EvalSetStatus.GENERATING.value,
        pair_count=0,
        created_by=user.id,
    )
    db_session.add(row)
    await db_session.commit()
    return row


async def _running_run(db_session: AsyncSession) -> EvalRun:
    eval_set = await _generating_set(db_session)
    row = EvalRun(
        id=uuid.uuid4(),
        set_id=eval_set.id,
        project_id=eval_set.project_id,
        status=EvalRunStatus.RUNNING.value,
        created_by=eval_set.created_by,
    )
    db_session.add(row)
    await db_session.commit()
    return row


async def test_a_set_is_claimed_once(db_session: AsyncSession) -> None:
    row = await _generating_set(db_session)
    repo = EvalSetRepository(db_session)

    first = await repo.claim(set_id=row.id, job_id=uuid.uuid4(), worker_id="a", lease_seconds=300)
    second = await repo.claim(set_id=row.id, job_id=uuid.uuid4(), worker_id="b", lease_seconds=300)

    assert (first, second) == (True, False)


async def test_a_redelivered_finished_set_job_is_refused(db_session: AsyncSession) -> None:
    row = await _generating_set(db_session)
    repo = EvalSetRepository(db_session)
    job = uuid.uuid4()
    await repo.claim(set_id=row.id, job_id=job, worker_id="a", lease_seconds=300)
    await repo.release(set_id=row.id, job_id=job, worker_id="a", status=EvalSetStatus.READY)

    assert not await repo.claim(set_id=row.id, job_id=job, worker_id="a", lease_seconds=300)


async def test_set_claim_stranded_takes_a_set_once_and_stamps_it(db_session: AsyncSession) -> None:
    row = await _generating_set(db_session)
    row.updated_at = datetime.now(UTC) - timedelta(minutes=10)
    await db_session.commit()
    repo = EvalSetRepository(db_session)

    first = await repo.claim_stranded(older_than_seconds=120)
    second = await repo.claim_stranded(older_than_seconds=120)

    assert list(first) == [row.id]
    assert list(second) == []


async def test_set_defer_keeps_it_generating_with_a_short_lease(db_session: AsyncSession) -> None:
    row = await _generating_set(db_session)
    repo = EvalSetRepository(db_session)
    await repo.claim(set_id=row.id, job_id=uuid.uuid4(), worker_id="a", lease_seconds=300)

    assert await repo.defer(set_id=row.id, worker_id="a", hold_seconds=60)
    await db_session.refresh(row)
    assert row.status == EvalSetStatus.GENERATING.value
    assert row.lease_expires_at is not None


async def test_a_run_is_claimed_once_and_stamped_started(db_session: AsyncSession) -> None:
    row = await _running_run(db_session)
    repo = EvalRunRepository(db_session)

    first = await repo.claim(run_id=row.id, job_id=uuid.uuid4(), worker_id="a", lease_seconds=300)
    second = await repo.claim(run_id=row.id, job_id=uuid.uuid4(), worker_id="b", lease_seconds=300)

    assert (first, second) == (True, False)
    await db_session.refresh(row)
    assert row.started_at is not None


async def test_a_redelivered_finished_run_job_is_refused(db_session: AsyncSession) -> None:
    row = await _running_run(db_session)
    repo = EvalRunRepository(db_session)
    job = uuid.uuid4()
    await repo.claim(run_id=row.id, job_id=job, worker_id="a", lease_seconds=300)
    await repo.release(run_id=row.id, job_id=job, worker_id="a", status=EvalRunStatus.DONE)

    assert not await repo.claim(run_id=row.id, job_id=job, worker_id="a", lease_seconds=300)


async def test_run_claim_stranded_takes_a_run_once_and_stamps_it(db_session: AsyncSession) -> None:
    row = await _running_run(db_session)
    row.updated_at = datetime.now(UTC) - timedelta(minutes=10)
    await db_session.commit()
    repo = EvalRunRepository(db_session)

    first = await repo.claim_stranded(older_than_seconds=120)
    second = await repo.claim_stranded(older_than_seconds=120)

    assert list(first) == [row.id]
    assert list(second) == []


async def test_run_defer_keeps_it_running_with_a_short_lease(db_session: AsyncSession) -> None:
    row = await _running_run(db_session)
    repo = EvalRunRepository(db_session)
    await repo.claim(run_id=row.id, job_id=uuid.uuid4(), worker_id="a", lease_seconds=300)

    assert await repo.defer(run_id=row.id, worker_id="a", hold_seconds=60)
    await db_session.refresh(row)
    assert row.status == EvalRunStatus.RUNNING.value
    assert row.lease_expires_at is not None


async def test_active_for_set_finds_only_a_running_run(db_session: AsyncSession) -> None:
    row = await _running_run(db_session)
    repo = EvalRunRepository(db_session)

    found = await repo.active_for_set(row.set_id)
    assert found is not None and found.id == row.id

    row.status = EvalRunStatus.DONE.value
    await db_session.commit()
    assert await repo.active_for_set(row.set_id) is None


async def test_soft_deleting_a_project_reaches_every_eval_table(db_session: AsyncSession) -> None:
    row = await _running_run(db_session)

    assert await EvalRunRepository(db_session).soft_delete_for_project(row.project_id) == 1
    assert await EvalSetRepository(db_session).soft_delete_for_project(row.project_id) == 1
    assert await EvalPairRepository(db_session).soft_delete_for_project(row.project_id) == 0
    assert await EvalResultRepository(db_session).soft_delete_for_project(row.project_id) == 0
    assert await EvalSetRepository(db_session).list_for_project(
        row.project_id, limit=10, offset=0
    ) == ([], 0)


async def test_set_lock_selects_for_update(db_session: AsyncSession) -> None:
    from sqlalchemy import event

    eval_set = await _generating_set(db_session)
    seen: list[str] = []
    engine = db_session.get_bind().engine

    def capture(conn: object, cursor: object, statement: str, *args: object) -> None:
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        found = await EvalSetRepository(db_session).lock(eval_set.id)
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert found is not None
    assert any("FOR UPDATE" in statement for statement in seen)


async def test_results_list_in_pair_position_order(db_session: AsyncSession) -> None:
    from app.models.eval import EvalPair, EvalResult

    run = await _running_run(db_session)
    pairs = []
    for position in (2, 0, 1):
        pair = EvalPair(
            id=uuid.uuid4(),
            set_id=run.set_id,
            position=position,
            question_type="explain",
            question="q",
            reference_answer="a",
            source_file="f.py",
            start_line=1,
            end_line=2,
        )
        db_session.add(pair)
        pairs.append(pair)
    await db_session.flush()
    for pair in pairs:  # inserted in 2, 0, 1 order
        db_session.add(
            EvalResult(
                id=uuid.uuid4(),
                run_id=run.id,
                pair_id=pair.id,
                retrieval_hit=True,
                verdict="correct",
                answer="x",
            )
        )
    await db_session.commit()

    rows = await EvalResultRepository(db_session).list_for_run(run.id)

    by_pair = {pair.id: pair.position for pair in pairs}
    assert [by_pair[row.pair_id] for row in rows] == [0, 1, 2]


async def test_a_stale_job_cannot_reclaim_a_finished_set(db_session: AsyncSession) -> None:
    repo = EvalSetRepository(db_session)
    for finished in (EvalSetStatus.READY, EvalSetStatus.FAILED):
        row = await _generating_set(db_session)
        row.status = finished.value
        row.pair_count = 7
        await db_session.commit()

        claimed = await repo.claim(
            set_id=row.id, job_id=uuid.uuid4(), worker_id="late", lease_seconds=300
        )

        assert claimed is False
        await db_session.refresh(row)
        assert (row.status, row.pair_count, row.lease_owner) == (finished.value, 7, None)


async def test_a_stale_job_cannot_reclaim_a_finished_run(db_session: AsyncSession) -> None:
    repo = EvalRunRepository(db_session)
    for finished in (EvalRunStatus.DONE, EvalRunStatus.FAILED):
        row = await _running_run(db_session)
        row.status = finished.value
        row.error = "kept"
        await db_session.commit()

        claimed = await repo.claim(
            run_id=row.id, job_id=uuid.uuid4(), worker_id="late", lease_seconds=300
        )

        assert claimed is False
        await db_session.refresh(row)
        assert (row.status, row.error, row.lease_owner) == (finished.value, "kept", None)


async def test_a_heartbeat_on_a_deleted_row_returns_false(db_session: AsyncSession) -> None:
    run = await _running_run(db_session)
    runs, sets = EvalRunRepository(db_session), EvalSetRepository(db_session)
    set_row = await _generating_set(db_session)
    await runs.claim(run_id=run.id, job_id=uuid.uuid4(), worker_id="a", lease_seconds=300)
    await sets.claim(set_id=set_row.id, job_id=uuid.uuid4(), worker_id="a", lease_seconds=300)
    assert await runs.renew_lease(run_id=run.id, worker_id="a", lease_seconds=300)
    assert await sets.renew_lease(set_id=set_row.id, worker_id="a", lease_seconds=300)

    run.deleted_at = datetime.now(UTC)
    set_row.deleted_at = datetime.now(UTC)
    await db_session.commit()

    assert not await runs.renew_lease(run_id=run.id, worker_id="a", lease_seconds=300)
    assert not await sets.renew_lease(set_id=set_row.id, worker_id="a", lease_seconds=300)


async def test_active_for_project_finds_only_live_running_runs(db_session: AsyncSession) -> None:
    row = await _running_run(db_session)
    repo = EvalRunRepository(db_session)
    assert await repo.active_for_project(row.project_id) is not None

    row.status = EvalRunStatus.FAILED.value
    await db_session.commit()
    assert await repo.active_for_project(row.project_id) is None

    row.status = EvalRunStatus.RUNNING.value
    row.deleted_at = datetime.now(UTC)
    await db_session.commit()
    assert await repo.active_for_project(row.project_id) is None

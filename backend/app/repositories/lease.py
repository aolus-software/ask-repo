"""The lease statements every job-bearing table shares.

A lease is how one worker claims a job so another cannot run it at the same time
(`.claude/rules/ingestion.md`: the database lease is the deduplication boundary). Five
tables carry one -- `projects`, `checklist_modules`, `mock_data_datasets`, `eval_sets`
and `eval_runs` -- and each used to hold its own copy of the same five UPDATEs. They
live here once, parameterised by the model, so a fix to the protocol lands in one
place.

**This module owns the SQL, never the live event.** Each repository keeps a thin method
per operation that calls the helper and then stages its own `LiveEvent`
(`.claude/rules/live-events.md` rule 3, pinned by `tests/test_live_event_sites.py`):
what a screen is told, and which id it is told it under, differs per table, and a
helper that guessed would be a second place deciding it.

**What is deliberately not here**, because the tables disagree and unifying would change
behaviour: each table's extra `claim` predicates and values (an eval row's claim also
gates on its working status, a project's claim rewrites `status` and the reindex flag),
`release`'s extra outcome columns (passed as `fields`), the project's `abandon` and
three-branch `find_stranded`, the checklist `defer` rationale (documented on the
repository method), and the eval run's `hold_for_commit` `FOR UPDATE` re-check.

The model parameters are typed `Any` on purpose: the five models share column names, not
a base class, and a Protocol over SQLAlchemy's instrumented attributes would say less than
this docstring does.
"""

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import Row, or_, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

# How long a claim is good for. Declared once so the consumer (which claims) and the
# runners (which renew) cannot drift apart on it: five minutes is safe only because
# renewal runs every sixty seconds.
LEASE_SECONDS = 300
LEASE_RENEWAL_SECONDS = 60

type LeasedModel = type[Any]


async def claim_lease(
    session: AsyncSession,
    model: LeasedModel,
    *,
    row_id: uuid.UUID,
    job_id: uuid.UUID,
    worker_id: str,
    lease_seconds: int,
    returning: Sequence[Any],
    extra_where: Sequence[Any] = (),
    extra_values: Mapping[str, Any] | None = None,
) -> Row[Any] | None:
    """Take a row's lease if it is free and this job has not already finished on it.

    Gates on a live row, no live lease, and `last_job_id` differing from this job (what
    separates a redelivery of a finished job from a fresh request). `extra_where` adds a
    table's own gates; `extra_values` its own columns -- `status` and `error` included,
    since the tables disagree on both. `None` means the claim was refused.
    """
    now = datetime.now(UTC)
    result = await session.execute(
        update(model)
        .where(
            model.id == row_id,
            model.deleted_at.is_(None),
            *extra_where,
            model.last_job_id.is_distinct_from(job_id),
            or_(model.lease_expires_at.is_(None), model.lease_expires_at < now),
        )
        .values(
            lease_owner=worker_id,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
            last_job_id=job_id,
            # Bulk UPDATE: `onupdate` does not fire on this path
            # (`.claude/rules/persistence.md`).
            updated_at=now,
            **(extra_values or {}),
        )
        .returning(*returning)
    )
    return result.one_or_none()


async def renew_lease(
    session: AsyncSession,
    model: LeasedModel,
    *,
    row_id: uuid.UUID,
    worker_id: str,
    lease_seconds: int,
    skip_deleted: bool,
) -> bool:
    """Extend our own lease. False means we lost it and must abandon the job.

    `skip_deleted` is a parameter rather than a constant because the tables differ:
    eval sets and runs refuse to renew a soft-deleted row, the project, checklist and
    mock-data heartbeats never did. Each caller keeps what it had.
    """
    now = datetime.now(UTC)
    conditions = [model.id == row_id, model.lease_owner == worker_id]
    if skip_deleted:
        conditions.append(model.deleted_at.is_(None))
    result = await session.execute(
        update(model)
        .where(*conditions)
        .values(lease_expires_at=now + timedelta(seconds=lease_seconds), updated_at=now)
    )
    return cast(CursorResult[Any], result).rowcount == 1


async def release_lease(
    session: AsyncSession,
    model: LeasedModel,
    *,
    row_id: uuid.UUID,
    job_id: uuid.UUID,
    worker_id: str,
    status: str,
    error: str | None,
    fields: Mapping[str, object],
    returning: Sequence[Any],
) -> Row[Any] | None:
    """Finish a run: write the outcome and drop the lease. `None` if we no longer held it.

    Guarded on the conditions the claim was granted under: without `deleted_at IS NULL`
    a row deleted mid-run is written back to life, and without `lease_owner` a worker
    whose lease expired overwrites the winner's outcome. The caller must treat `None`
    as "this run lost the right to record itself".
    """
    result = await session.execute(
        update(model)
        .where(
            model.id == row_id,
            model.deleted_at.is_(None),
            model.lease_owner == worker_id,
        )
        .values(
            status=status,
            error=error,
            lease_owner=None,
            lease_expires_at=None,
            last_job_id=job_id,
            updated_at=datetime.now(UTC),
            **fields,
        )
        .returning(*returning)
    )
    return result.one_or_none()


async def defer_lease(
    session: AsyncSession,
    model: LeasedModel,
    *,
    row_id: uuid.UUID,
    worker_id: str,
    hold_seconds: int,
    returning: Sequence[Any],
) -> Row[Any] | None:
    """Shorten our lease to the moment a scheduled retry is due, leaving status alone.

    The lease expires at the retry's due time rather than being dropped, so the claim
    admits the retry the instant it arrives while the sweep still reads the row as held
    until then (the reasoning is `ChecklistModuleRepository.defer`'s). Guarded on
    `lease_owner`: a run that lost its lease has no right to write to the row.
    """
    now = datetime.now(UTC)
    result = await session.execute(
        update(model)
        .where(
            model.id == row_id,
            model.deleted_at.is_(None),
            model.lease_owner == worker_id,
        )
        .values(lease_expires_at=now + timedelta(seconds=hold_seconds), updated_at=now)
        .returning(*returning)
    )
    return result.one_or_none()


async def claim_stranded_rows(
    session: AsyncSession,
    model: LeasedModel,
    *,
    working_status: str,
    older_than_seconds: int,
    returning: Sequence[Any],
) -> Sequence[Row[Any]]:
    """Take the rows whose job was lost, and stamp them so they stay taken.

    A row in its working status says nothing about whether a worker holds it -- it was
    already `generating` or `running` before its claim -- and the sweep re-publishes
    with a fresh `job_id` the claim cannot refuse. Stamping `updated_at` is what stops
    the next tick taking the same row again, and what makes a concurrent sweep match
    nothing (`.claude/rules/ingestion.md`). The caller's transaction must commit on its
    own for the stamp to hold.
    """
    now = datetime.now(UTC)
    cutoff = now - timedelta(seconds=older_than_seconds)
    result = await session.execute(
        update(model)
        .where(
            model.deleted_at.is_(None),
            model.status == working_status,
            model.updated_at < cutoff,
            or_(model.lease_expires_at.is_(None), model.lease_expires_at < now),
        )
        .values(updated_at=now)
        .returning(*returning)
    )
    return result.all()

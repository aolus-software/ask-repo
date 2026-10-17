"""Announcing an eval set's or run's outcome to the project's `eval.read` holders.

One helper for the three call sites that end an eval job: the generator (a set that
became `ready`, or `failed` with no usable pairs), the runner (a run that is `done`),
and the consumer's terminal-failure path (either kind, `failed`). Each calls it after
the release that made the outcome true and **before** that release commits, so the
status and the notification of it are one transaction (`.claude/rules/notifications.md`
rule 2). A retryable failure that is coming back calls nothing.

The names are read with a column query rather than off ORM rows the caller holds: the
runner commits mid-run, which expires every attribute, and an expired attribute read
outside an `await` is an IO attempt the async session refuses.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.notifications import NotificationType
from app.models.eval import EvalRun, EvalSet
from app.models.project import Project
from app.services.notification_fanout import NotificationFanout


async def announce_set(
    session: AsyncSession,
    *,
    set_id: uuid.UUID,
    event_type: NotificationType,
    mail_enabled: bool,
    pair_count: int | None = None,
) -> None:
    """Raise `eval_set.ready` or `eval_set.failed` for this set. Flushes, never commits."""
    row = (
        await session.execute(
            select(EvalSet.project_id, EvalSet.name, Project.name)
            .join(Project, Project.id == EvalSet.project_id)
            .where(EvalSet.id == set_id)
        )
    ).one_or_none()
    if row is None:
        return
    project_id, set_name, project_name = row
    details: dict[str, object] = {"projectName": project_name, "setName": set_name}
    if pair_count is not None:
        details["pairCount"] = pair_count
    await _raise(session, event_type, project_id, set_id, details, mail_enabled=mail_enabled)


async def announce_run(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    event_type: NotificationType,
    mail_enabled: bool,
    pairs_answered: int | None = None,
    correct: int | None = None,
) -> None:
    """Raise `eval_run.finished` or `eval_run.failed` for this run. Flushes, never commits.

    The target is the run's *set*: `/projects/{id}/eval/{setId}` is the screen a run's
    results live on, and a run's own id names nothing a recipient can navigate to.
    """
    row = (
        await session.execute(
            select(EvalRun.project_id, EvalRun.set_id, EvalSet.name, Project.name)
            .join(EvalSet, EvalSet.id == EvalRun.set_id)
            .join(Project, Project.id == EvalRun.project_id)
            .where(EvalRun.id == run_id)
        )
    ).one_or_none()
    if row is None:
        return
    project_id, set_id, set_name, project_name = row
    details: dict[str, object] = {"projectName": project_name, "setName": set_name}
    if pairs_answered is not None:
        details["pairsAnswered"] = pairs_answered
    if correct is not None:
        details["correct"] = correct
    await _raise(session, event_type, project_id, set_id, details, mail_enabled=mail_enabled)


async def _raise(
    session: AsyncSession,
    event_type: NotificationType,
    project_id: uuid.UUID,
    set_id: uuid.UUID,
    details: dict[str, object],
    *,
    mail_enabled: bool,
) -> None:
    await NotificationFanout(session, mail_enabled=mail_enabled).raise_event(
        event_type=event_type,
        project_id=project_id,
        # No actor: a worker raised this -- nobody did it, a job did. The requester is
        # still a recipient, because none of these four is in `ACTOR_EXCLUDED`.
        actor_user_id=None,
        target_id=set_id,
        details=details,
    )

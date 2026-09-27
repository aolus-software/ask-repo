"""Reads and writes for `feedback`.

Scoping is the service's job: a caller that reaches `upsert` has already proved the
target exists and is visible to it. The admin reads take `project_ids` from
`resolve_project_scope`, never from a filter of their own.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any, TypedDict, cast

from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult

from app.core.feedback import FeedbackTarget
from app.models.conversation import Message
from app.models.feedback import Feedback
from app.models.project import Project
from app.repositories.base import BaseRepository


class FeedbackFilters(TypedDict, total=False):
    """The admin filters, shared by the page, its count, and every aggregate."""

    project_ids: frozenset[uuid.UUID] | None
    feature: str | None
    rating: str | None
    reason_code: str | None
    prompt_version: str | None
    created_from: datetime | None
    created_to: datetime | None


def _apply(statement: Select[Any], filters: FeedbackFilters) -> Select[Any]:
    """The shared WHERE, so the page, its count and the aggregates cannot disagree."""
    statement = statement.where(Feedback.deleted_at.is_(None))
    project_ids = filters.get("project_ids")
    if project_ids is not None:
        statement = statement.where(Feedback.project_id.in_(project_ids))
    if feature := filters.get("feature"):
        statement = statement.where(Feedback.feature == feature)
    if rating := filters.get("rating"):
        statement = statement.where(Feedback.rating == rating)
    if reason_code := filters.get("reason_code"):
        statement = statement.where(Feedback.reason_codes.any(reason_code))
    if prompt_version := filters.get("prompt_version"):
        statement = statement.where(Feedback.prompt_version == prompt_version)
    if created_from := filters.get("created_from"):
        statement = statement.where(Feedback.created_at >= created_from)
    if created_to := filters.get("created_to"):
        statement = statement.where(Feedback.created_at <= created_to)
    return statement


class FeedbackRepository(BaseRepository[Feedback]):
    """Reads and writes for `feedback`. See module docstring."""

    model = Feedback

    async def upsert(
        self,
        *,
        user_id: uuid.UUID,
        project_id: uuid.UUID,
        target_type: str,
        target_id: uuid.UUID,
        feature: str,
        rating: str,
        reason_codes: list[str],
        note: str | None,
        prompt_version: str,
    ) -> Feedback:
        """Insert the caller's vote, or replace it in place.

        `ON CONFLICT` on the partial unique index rather than read-then-write, so two
        tabs voting at once cannot both insert.
        """
        values = {
            "user_id": user_id,
            "project_id": project_id,
            "target_type": target_type,
            "target_id": target_id,
            "feature": feature,
            "rating": rating,
            "reason_codes": reason_codes,
            "note": note,
            "prompt_version": prompt_version,
        }
        statement = (
            insert(Feedback)
            .values(id=uuid.uuid4(), **values)
            .on_conflict_do_update(
                index_elements=["user_id", "target_type", "target_id"],
                index_where=Feedback.deleted_at.is_(None),
                set_={
                    "rating": rating,
                    "reason_codes": reason_codes,
                    "note": note,
                    "prompt_version": prompt_version,
                    "updated_at": func.now(),
                },
            )
            .returning(Feedback)
        )
        result = await self.session.execute(
            statement, execution_options={"populate_existing": True}
        )
        return result.scalar_one()

    async def delete_mine(
        self, *, user_id: uuid.UUID, target_type: str, target_id: uuid.UUID
    ) -> int:
        """Withdraw a vote. A hard delete: an unrecorded opinion needs no tombstone."""
        result = await self.session.execute(
            delete(Feedback).where(
                Feedback.user_id == user_id,
                Feedback.target_type == target_type,
                Feedback.target_id == target_id,
                Feedback.deleted_at.is_(None),
            )
        )
        return cast(CursorResult[Any], result).rowcount

    async def mine_for_targets(
        self, *, user_id: uuid.UUID, target_type: str, target_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, Feedback]:
        """The caller's own votes on these targets, keyed by target id. One query."""
        if not target_ids:
            return {}
        result = await self.session.execute(
            self.active_select().where(
                Feedback.user_id == user_id,
                Feedback.target_type == target_type,
                Feedback.target_id.in_(list(target_ids)),
            )
        )
        return {row.target_id: row for row in result.scalars().all()}

    async def clear_notes_for_conversation(self, conversation_id: uuid.UUID) -> int:
        """Null the notes on a conversation's Ask feedback; keep the counts.

        The note is the user's own words about a private turn and goes when the turn
        goes. The rating and reason codes survive, so the aggregate still adds up.
        """
        messages = select(Message.id).where(Message.conversation_id == conversation_id)
        result = await self.session.execute(
            update(Feedback)
            .where(
                Feedback.target_type == FeedbackTarget.MESSAGE.value,
                Feedback.target_id.in_(messages),
                Feedback.note.is_not(None),
            )
            .values(note=None, updated_at=func.now())
        )
        return cast(CursorResult[Any], result).rowcount

    async def soft_delete_for_project(self, project_id: uuid.UUID) -> int:
        """Soft-delete a project's feedback, alongside every other project-owned row."""
        result = await self.session.execute(
            update(Feedback)
            .where(Feedback.project_id == project_id, Feedback.deleted_at.is_(None))
            .values(deleted_at=func.now(), updated_at=func.now())
        )
        return cast(CursorResult[Any], result).rowcount

    async def delete_older_than(self, cutoff: datetime) -> int:
        """Hard-delete every row created before `cutoff` — `FEEDBACK_RETENTION_DAYS`."""
        result = await self.session.execute(delete(Feedback).where(Feedback.created_at < cutoff))
        return cast(CursorResult[Any], result).rowcount

    async def page(
        self, *, limit: int, offset: int, filters: FeedbackFilters
    ) -> tuple[list[tuple[Feedback, str]], int]:
        """One page, newest first, each row with its project's name, plus the total."""
        statement = _apply(
            select(Feedback, Project.name).join(Project, Project.id == Feedback.project_id),
            filters,
        )
        rows = await self.session.execute(
            statement.order_by(Feedback.created_at.desc(), Feedback.id.desc())
            .limit(limit)
            .offset(offset)
        )
        count = await self.session.execute(_apply(select(func.count(Feedback.id)), filters))
        return [(row, name) for row, name in rows.all()], count.scalar_one()

    async def counts_by_feature(self, filters: FeedbackFilters) -> list[tuple[str, str, int]]:
        """(feature, rating, count)."""
        statement = _apply(
            select(Feedback.feature, Feedback.rating, func.count(Feedback.id)), filters
        ).group_by(Feedback.feature, Feedback.rating)
        return [(f, r, c) for f, r, c in (await self.session.execute(statement)).all()]

    async def counts_by_reason(self, filters: FeedbackFilters) -> list[tuple[str, str, int]]:
        """(feature, reason_code, count) over down-votes. A vote with two codes counts twice."""
        reason = func.unnest(Feedback.reason_codes).label("reason")
        inner = _apply(
            select(Feedback.feature.label("feature"), reason).where(Feedback.rating == "down"),
            filters,
        ).subquery()
        statement = select(inner.c.feature, inner.c.reason, func.count()).group_by(
            inner.c.feature, inner.c.reason
        )
        return [(f, r, c) for f, r, c in (await self.session.execute(statement)).all()]

    async def counts_by_prompt_version(
        self, filters: FeedbackFilters
    ) -> list[tuple[str, str, int]]:
        """(prompt_version, rating, count)."""
        statement = _apply(
            select(Feedback.prompt_version, Feedback.rating, func.count(Feedback.id)), filters
        ).group_by(Feedback.prompt_version, Feedback.rating)
        return [(v, r, c) for v, r, c in (await self.session.execute(statement)).all()]

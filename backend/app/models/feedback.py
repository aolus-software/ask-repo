"""One user's judgement of one model-authored output.

**`target_id` is not a foreign key**, because the target lives in one of five tables
(`app/core/feedback.py`'s `FeedbackTarget`). The service proves the target exists and
is visible before writing; nothing here can.

**It points at what it judges and never copies it.** No prompt, no answer text, no
change-set body — only the reason codes and the user's own optional note. Copying the
subject would put a private repository's derived content outside the lifecycle
`docs/PRD.md` §5.1's delete rule governs.

`deleted_at` is used by project deletion only; withdrawing a vote hard-deletes it.
"""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.feedback import NOTE_MAX_LENGTH
from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class Feedback(Base, TimestampMixin, SoftDeleteMixin):
    """One user's thumbs-up/down on one piece of model output, with optional reasons."""

    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    feature: Mapped[str] = mapped_column(String(32), nullable=False)
    rating: Mapped[str] = mapped_column(String(8), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), nullable=False, server_default=text("'{}'")
    )
    note: Mapped[str | None] = mapped_column(String(NOTE_MAX_LENGTH), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (
        CheckConstraint("rating IN ('up', 'down')", name="rating"),
        CheckConstraint("rating = 'up' OR cardinality(reason_codes) > 0", name="down_has_reason"),
        # One live vote per user per subject; a vote change is an update in place.
        Index(
            "uq_feedback_user_target",
            "user_id",
            "target_type",
            "target_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_feedback_project_id_created_at", "project_id", "created_at"),
        Index("ix_feedback_feature_created_at", "feature", "created_at"),
        Index("ix_feedback_target", "target_type", "target_id"),
    )

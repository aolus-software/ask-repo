"""A self-service password-reset token, stored only as its hash.

Follows `refresh_tokens`: no `TimestampMixin`, no `SoftDeleteMixin`. A dead token is not
a record anybody needs, and `deleted_at` would only keep hashes around longer — rows are
hard-deleted by the worker's tick (`PasswordResetTokenRepository.delete_dead`).

There are no claim, attempt or state columns: the raw token exists only in the request's
memory, so only the request's own background task can ever send it, exactly once
(spec §6.2).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set when the single send succeeds. NULL means it failed or never ran; the user
    # requests another (spec §6.2).
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

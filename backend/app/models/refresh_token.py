"""The `refresh_tokens` table.

Deliberately carries no `deleted_at`, unlike every other table: its lifecycle is
`revoked_at` / `expires_at`, and a third overlapping state column that nothing sets
would be worse than the documented exception (D14, `docs/PRD.md` §5.1).

Only the SHA-256 of a token is stored. The raw value exists in the response cookie
and nowhere else.
"""

import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

RevokedReason = Literal[
    "rotated",
    "replay",
    "logout",
    "logout_all",
    "password_change",
    "admin_reset",
    "user_deactivated",
]


class RefreshToken(Base):
    """One issued refresh token. Rotation inserts a successor sharing `family_id`."""

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        # No cascade: users are soft-deleted, never removed.
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="NO ACTION"),
        nullable=False,
        index=True,
    )
    # The rotation chain. Replay detection revokes exactly one device's family.
    family_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # SHA-256 hex is always exactly 64 characters.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)

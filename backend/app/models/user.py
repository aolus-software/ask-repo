"""The `users` table — see `docs/PRD.md` §3 for the schema of record."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class User(Base, TimestampMixin, SoftDeleteMixin):
    """An account. Provisioned by an admin; there is no self-service signup."""

    __tablename__ = "users"
    __table_args__ = (
        # Partial: a soft-deleted account frees its address for reuse (D20), and every
        # lookup filters `deleted_at IS NULL` anyway. Doubles as the login lookup index.
        Index(
            "uq_users_email_active",
            "email",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    # bcrypt output is always 60 chars; 255 leaves room for a future argon2id move.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

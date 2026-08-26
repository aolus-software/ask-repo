"""The `projects` table.

`created_by` is attribution and a destructive-operation gate. It does **not** scope
reads — that is `resolve_project_scope`'s job and nowhere else
(`docs/PRD.md` §5.1, `.claude/rules/router.md`).
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class ProjectStatus(StrEnum):
    """Lifecycle of an indexing run. Stored as text, not a Postgres enum:
    adding a value to a native enum needs a migration and a table lock."""

    PENDING = "pending"
    CLONING = "cloning"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"


class Project(Base, TimestampMixin, SoftDeleteMixin):
    """A repository that has been, or is being, indexed."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    repo_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    branch: Mapped[str] = mapped_column(String(255), nullable=False, default="main")

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ProjectStatus.PENDING.value, index=True
    )
    error: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    last_indexed_commit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    file_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Never serialized, in any response, not even masked (docs/PRD.md §4.1).
    encrypted_pat: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    # Delivery is at-least-once, so the lease — not the message — decides who runs
    # a job. See the spec's §4.2.
    lease_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Distinguishes "a new reindex was requested" from "an old message arrived
    # twice". The lease alone cannot tell those apart.
    last_job_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    # A reindex leaves `status` at `ready` so the project stays queryable, which
    # means status cannot express "a run is in progress". This flag does.
    reindex_in_progress: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Which Qdrant generation serves queries. New points are written under
    # generation+1 and the pointer flips only once they are all in.
    active_generation: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    # Which collection holds this project's points — needed in order to delete
    # them after the embedding provider has been switched.
    embedding_collection: Mapped[str | None] = mapped_column(String(255), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(255), nullable=True)

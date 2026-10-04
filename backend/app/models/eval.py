"""The eval harness tables.

See `docs/superpowers/specs/2026-10-03-phase-2.6-eval-harness-design.md` §1.

A set is generated once and frozen; runs answer it repeatedly. Every table soft-deletes,
and deleting a set or a project soft-deletes the rows beneath it in the same
transaction. No Qdrant point belongs to any of them.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class EvalSetStatus(StrEnum):
    """A set is written `generating` by the request and finished by the worker."""

    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"


class EvalRunStatus(StrEnum):
    """A run is written `running` by the request and finished by the worker."""

    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class EvalMix(StrEnum):
    """Which question types a set asks for."""

    BALANCED = "balanced"
    EXPLAIN = "explain"
    LOCATE = "locate"


class EvalQuestionType(StrEnum):
    """`impact` is deliberately absent until Phase 3's graph can answer it (spec §0.1)."""

    EXPLAIN = "explain"
    LOCATE = "locate"


class EvalVerdict(StrEnum):
    """The judge's call. `error` is kept out of the split."""

    CORRECT = "correct"
    PARTIAL = "partial"
    WRONG = "wrong"
    ERROR = "error"


class EvalSet(Base, TimestampMixin, SoftDeleteMixin):
    """A frozen set of generated Q&A pairs over a project, or one indexed path of it."""

    __tablename__ = "eval_sets"
    __table_args__ = (Index("ix_eval_sets_project_id", "project_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    source_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    requested_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    mix: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    pair_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    indexed_generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_job_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )


class EvalPair(Base, TimestampMixin, SoftDeleteMixin):
    """One question grounded in one chunk. Never edited; only excluded."""

    __tablename__ = "eval_pairs"
    __table_args__ = (Index("ix_eval_pairs_set_id", "set_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    set_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("eval_sets.id"), nullable=False
    )
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    question_type: Mapped[str] = mapped_column(String(16), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    reference_answer: Mapped[str] = mapped_column(Text, nullable=False)
    source_file: Mapped[str] = mapped_column(String(1024), nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    excluded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EvalRun(Base, TimestampMixin, SoftDeleteMixin):
    """One pass over a set, stamped with everything that could differ between passes."""

    __tablename__ = "eval_runs"
    __table_args__ = (
        Index("ix_eval_runs_set_id", "set_id"),
        Index("ix_eval_runs_project_id", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    set_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("eval_sets.id"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(12), nullable=True)
    chat_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chat_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    judge_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    project_generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pairs_answered: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    hits: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    correct: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    partial: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    wrong: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    errors: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_job_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )


class EvalResult(Base, TimestampMixin, SoftDeleteMixin):
    """One pair's outcome in one run. Its id seeds the pair's trace."""

    __tablename__ = "eval_results"
    __table_args__ = (
        Index("ix_eval_results_run_id", "run_id"),
        Index(
            "uq_eval_results_run_pair",
            "run_id",
            "pair_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("eval_runs.id"), nullable=False
    )
    pair_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("eval_pairs.id"), nullable=False
    )
    retrieval_hit: Mapped[bool] = mapped_column(Boolean, nullable=False)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    judge_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    grounding_warnings: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    retrieval_attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

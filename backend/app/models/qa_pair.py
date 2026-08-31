"""The `qa_pairs` table — the team's shared knowledge base and regression set.

One table, carrying M5's columns from the start. `docs/PRD.md` §4.3 settled this:
the QA List and the Mock Data Generator share one schema discriminated by `source`,
because two tables would have to be merged the moment generated pairs need to appear
in the same list view as manual ones.

Access inverts `conversations` and matches `projects`: every authenticated user may
read every pair, and `created_by` gates editing and deleting rather than reading.
Setting `status` is the one write that is deliberately open to everyone — see
`.claude/rules/router.md` and `docs/PRD.md:338`.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin

MAX_MODULE_CHARS = 120


class QAStatus(StrEnum):
    """Does the stored answer match the expected one?

    One column, three states, written by whoever looked most recently — a human
    through `PUT /qa-pairs/{id}/status`, or M5's judge beside the `eval_score` it
    computes. `reviewed_by` is what distinguishes them: a human verdict names a
    user, a machine verdict does not.

    This replaces the `verified: bool` the PRD originally specified. A boolean has
    no way to record "a human looked and it was wrong", which is the state a
    regression set most needs to surface after a refactor. Spec §2.1.
    """

    UNREVIEWED = "unreviewed"
    PASS = "pass"
    FAIL = "fail"


class QASource(StrEnum):
    """Who produced the pair. `GENERATED` is written by M5 and never by a route."""

    MANUAL = "manual"
    GENERATED = "generated"


class QAPair(Base, TimestampMixin, SoftDeleteMixin):
    """One published question and the answer it was published with."""

    __tablename__ = "qa_pairs"
    __table_args__ = (
        # The default list, filtered by project, newest first.
        Index("ix_qa_pairs_project_id_created_at", "project_id", "created_at"),
        # Containment (`tags @> ARRAY[:tag]`) for the tag filter. A btree index
        # cannot serve that operator at all, so this one is load-bearing rather
        # than an optimisation.
        Index("ix_qa_pairs_tags", "tags", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    # Attribution and the destructive-operation gate. Never read scope
    # (`docs/PRD.md` §5.1).
    created_by: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )

    module: Mapped[str | None] = mapped_column(String(MAX_MODULE_CHARS), nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    # Null until answered: M5 generates a question before it has an answer.
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The expected result. Seeded from `answer` when a pair is saved from a
    # conversation, and editable afterwards — spec §2.3 widens the PRD's
    # "generated pairs only".
    reference_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The FULL retrieved set in prompt order, matching `Message.citations`, not the
    # cited subset: `docs/PRD.md:298-300` needs retrieval scoreable independently of
    # generation, which the discarded chunks are half of.
    citations: Mapped[list[dict[str, object]] | None] = mapped_column(JSONB, nullable=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, server_default="{}")
    # String rather than a native Postgres enum, matching `Message.role` and
    # `Project.status`: adding a value to a native enum needs a migration and a
    # table lock, and M5 is likely to want more states.
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # M5 writes it. M4 only creates the column, so the eval milestone is a code
    # change rather than a migration against a table with rows in it.
    eval_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- The pending re-run slot (spec §2.5) ---
    #
    # A re-run streams to the browser but writes its result here, server-side, and
    # `accept` promotes it. The browser sends an instruction, never content: a QA
    # pair is published to every user on the instance, so its text must come from a
    # model through the server. `pending_finish_reason` is what `accept` refuses on,
    # so a truncated run can be read but never published.
    pending_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    pending_citations: Mapped[list[dict[str, object]] | None] = mapped_column(JSONB, nullable=True)
    pending_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pending_finish_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pending_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

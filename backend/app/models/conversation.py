"""The `conversations` and `messages` tables.

Conversations invert the access rule that governs projects. A project is readable
by every user on the instance (`docs/PRD.md` §4.1); a conversation is readable only
by the user who had it (§4.2), and a request for someone else's returns `404` rather
than `403` — here existence itself is private.

`messages` carries no `deleted_at`, and that is deliberate rather than an oversight.
A message is created by one turn of one conversation and is reachable only through
that conversation, so its deletion is fully expressed by the parent's `deleted_at`.
A column here would be a second state that nothing ever sets — exactly the argument
`docs/PRD.md` §5.1 already makes for `refresh_tokens`.
"""

import uuid
from enum import StrEnum

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin

# Titles are derived from the first question, which is unbounded user input.
MAX_TITLE_CHARS = 200


class MessageRole(StrEnum):
    """Who produced a message."""

    USER = "user"
    ASSISTANT = "assistant"


class FinishReason(StrEnum):
    """How an assistant message ended.

    Without this, a truncated answer is indistinguishable from a short one, with
    two consequences: the sliding window would replay a half-sentence as though it
    were a complete turn, and M4's "save to the QA List" would publish a cut-off
    answer to the whole team.
    """

    STOP = "stop"
    ERROR = "error"
    TIMEOUT = "timeout"
    DISCONNECTED = "disconnected"


class Intent(StrEnum):
    """What kind of question a turn is, and therefore which path the answer
    graph takes for it.

    `StrEnum` so it serialises as its value in `DoneEvent`, matching
    `FinishReason`. Defined here, alongside `FinishReason`, rather than in
    `app.rag.graph.state` where the rest of the graph's data lives: this module
    is already a dependency of the schema layer, and `Intent` needs to reach
    `app/schemas/conversation.py` without making the schema layer depend on RAG.
    """

    CODEBASE_QUESTION = "codebase_question"
    CONVERSATIONAL = "conversational"
    OUT_OF_SCOPE = "out_of_scope"


class Conversation(Base, TimestampMixin, SoftDeleteMixin):
    """One private thread of questions against one project."""

    __tablename__ = "conversations"
    __table_args__ = (
        # The list query, exactly: the caller's conversations, most recent first.
        Index("ix_conversations_user_id_updated_at", "user_id", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # The privacy boundary. Never widened by `is_admin` (docs/PRD.md §4.2).
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, index=True
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Message(Base, TimestampMixin):
    """One turn. Immutable once written — see the module docstring on deletion."""

    __tablename__ = "messages"
    __table_args__ = (
        # The history load and the detail route both read in this order.
        Index("ix_messages_conversation_id_created_at", "conversation_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False
    )
    # String rather than a native enum, matching ProjectStatus: adding a value to a
    # Postgres enum needs a migration and a table lock. `Literal` guards it in Python.
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # The FULL retrieved set in prompt order, not only the cited subset: M5 has to
    # evaluate retrieval independently of generation, which is impossible if the
    # chunks the model ignored were thrown away.
    citations: Mapped[list[dict[str, object]] | None] = mapped_column(JSONB, nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Null on user messages; one of FinishReason on assistant messages.
    finish_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)

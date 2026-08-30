"""Conversation and message persistence.

Every read here is scoped by `owner_id`. That is not defence in depth bolted onto a
service check — it is the only scoping there is, and it lives at the layer that
builds the query so no caller can forget it.
"""

import uuid
from typing import Any, cast

from sqlalchemy import CursorResult, Select, func, select, update

from app.models.conversation import Conversation, Message
from app.repositories.base import BaseRepository


class ConversationRepository(BaseRepository[Conversation]):
    """Reads and writes conversations, always scoped to one owner."""

    model = Conversation

    # Allowlisted, never interpolated: passing a query parameter into
    # getattr(Model, ...) unchecked exposes every column on the table.
    SORTABLE_FIELDS = frozenset({"created_at", "updated_at", "title"})

    async def get_for_owner(
        self, conversation_id: uuid.UUID, owner_id: uuid.UUID
    ) -> Conversation | None:
        """One conversation, if this owner has it. `None` otherwise — never a row
        plus a permission flag, so the caller's `404` cannot be forgotten."""
        result = await self.session.execute(
            self.active_select().where(
                Conversation.id == conversation_id, Conversation.user_id == owner_id
            )
        )
        return result.scalar_one_or_none()

    def _owned(
        self,
        owner_id: uuid.UUID,
        project_id: uuid.UUID | None,
        search: str | None = None,
    ) -> Select[tuple[Conversation]]:
        """The base query both the page and its count are built from."""
        statement = self.active_select().where(Conversation.user_id == owner_id)
        if project_id is not None:
            statement = statement.where(Conversation.project_id == project_id)
        if search:
            # The title is the only text a conversation carries — messages are not
            # searched, because a conversation's body is the model's prose rather
            # than something the operator wrote and would recognise.
            #
            # `title` is NULL until the backend derives one from the first question,
            # and `ilike` on NULL is NULL rather than false. An untitled conversation
            # is therefore excluded from every search, which is the wanted behaviour:
            # it has no text to have matched.
            statement = statement.where(Conversation.title.ilike(f"%{search.strip()}%"))
        return statement

    async def list_page(
        self,
        *,
        owner_id: uuid.UUID,
        page: int,
        limit: int,
        sort: str,
        descending: bool,
        project_id: uuid.UUID | None = None,
        search: str | None = None,
    ) -> tuple[list[Conversation], int]:
        """One page of this owner's conversations, plus the unpaginated total."""
        if sort not in self.SORTABLE_FIELDS:
            raise ValueError(f"cannot sort conversations by {sort!r}")

        column = getattr(Conversation, sort)
        statement = self._owned(owner_id, project_id, search).order_by(
            column.desc() if descending else column.asc()
        )
        rows = await self.session.execute(statement.offset((page - 1) * limit).limit(limit))
        # The count applies the SAME filters as the rows, so the last page is never
        # empty and the pager never promises a page that does not exist.
        total = await self.session.execute(
            select(func.count()).select_from(self._owned(owner_id, project_id, search).subquery())
        )
        return list(rows.scalars().all()), total.scalar_one()

    async def soft_delete_for_project(self, project_id: uuid.UUID) -> int:
        """Soft-delete every conversation against a project, for every owner.

        `updated_at` is set explicitly: `TimestampMixin.onupdate` renders during an
        ORM flush and does not fire on a bulk `UPDATE`
        (`.claude/rules/persistence.md`).

        It is set from `func.now()` — the **database** clock — rather than from
        Python's, because `created_at` and `updated_at` are populated by
        `server_default=func.now()` everywhere else. Mixing clocks in one column is
        not theoretical here: the Postgres container runs milliseconds ahead of the
        host, so a Python timestamp can land *before* the `created_at` of the row it
        is updating, and any "changed since" ordering over the column silently stops
        holding.

        Not scoped by owner, deliberately — the project was shared, so the
        conversations against it belong to several people and all of them go.
        """
        result = await self.session.execute(
            update(Conversation)
            .where(Conversation.project_id == project_id, Conversation.deleted_at.is_(None))
            .values(deleted_at=func.now(), updated_at=func.now())
        )
        # `execute` is typed as returning `Result`, which declares no `rowcount`; a
        # bulk UPDATE really returns a `CursorResult`. Same cast as
        # `ProjectRepository.release` and its siblings.
        return cast(CursorResult[Any], result).rowcount


class MessageRepository(BaseRepository[Message]):
    """Reads and writes messages. Scoping is the conversation's job — a caller that
    reaches here has already proved it owns the conversation."""

    model = Message

    async def list_for_conversation(self, conversation_id: uuid.UUID) -> list[Message]:
        """Every message in a conversation, oldest first."""
        result = await self.session.execute(
            self.active_select()
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc(), Message.id.asc())
        )
        return list(result.scalars().all())

    async def recent_turns(self, conversation_id: uuid.UUID, *, limit: int) -> list[Message]:
        """The last `limit` messages, returned oldest-first.

        Selected newest-first so the database does the limiting, then reversed —
        the prompt needs chronological order, and loading the whole thread to take
        its tail would grow with the conversation.

        **Ordering rests on `created_at` being distinct per message.** It is, because
        a turn's two messages are committed in separate transactions — the question
        in `prepare_turn`, the answer in `_finalise` — and Postgres `now()` advances
        between them. The `id` tiebreaker below does not save us if that ever stops
        being true: ids are `uuid4`, so equal timestamps sort randomly rather than by
        insertion. Anything that writes two messages of one conversation inside a
        single transaction needs an explicit `created_at` or a real sequence column.
        """
        if limit <= 0:
            return []
        result = await self.session.execute(
            self.active_select()
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
        return list(reversed(result.scalars().all()))

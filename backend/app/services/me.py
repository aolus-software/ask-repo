"""The caller's own account surface: memberships, sessions, activity and answer style.

Every method takes the caller and nothing that names another user. Membership comes
from `app/core/access.py`, never a query of its own
(`tests/test_scoping_is_single_point.py`).
"""

import uuid
from enum import StrEnum

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import memberships_for, resolve_project_scope
from app.core.audit import AuditEntry, AuditEventType, AuditRecorder, ChangedValue
from app.core.errors import AppError, ErrorCode
from app.core.middleware import AuthenticatedUser
from app.models.user import User
from app.rag.answer_style import AnswerStyle
from app.repositories.audit_event import AuditEventRepository
from app.repositories.project import ProjectRepository
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.user import UserRepository
from app.schemas.me import (
    ActivityEntry,
    AnswerStyleRead,
    AnswerStyleUpdate,
    MembershipSummary,
    SessionResponse,
)
from app.schemas.pagination import ListQuery, PaginatedResponse


class MeService:
    """Backs the routes under `/me`."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        recorder: AuditRecorder,
        client_ip: str | None = None,
    ) -> None:
        self.session = session
        self.projects = ProjectRepository(session)
        self.tokens = RefreshTokenRepository(session)
        self.audit = AuditEventRepository(session)
        self.users = UserRepository(session)
        self._recorder = recorder
        self._client_ip = client_ip

    async def memberships(self, user: AuthenticatedUser) -> list[MembershipSummary]:
        """The caller's memberships, named, soft-deleted projects dropped, by name."""
        grants = memberships_for(user)
        names = await self.projects.names_and_generations([g.project_id for g in grants])
        summaries = [
            MembershipSummary(
                project_id=grant.project_id,
                project_name=names[grant.project_id].name,
                role=grant.role,
            )
            for grant in grants
            if grant.project_id in names
        ]
        return sorted(summaries, key=lambda summary: summary.project_name.lower())

    async def sessions(self, user: AuthenticatedUser) -> list[SessionResponse]:
        """The caller's live sessions, the one making this request marked `current`."""
        rows = await self.tokens.live_families_for(user.id)
        return [
            SessionResponse(
                id=row.family_id,
                user_agent=row.user_agent,
                ip_address=row.ip_address,
                started_at=row.started_at,
                last_active_at=row.last_active_at,
                expires_at=row.expires_at,
                current=row.family_id == user.session_id,
            )
            for row in rows
        ]

    async def revoke_session(self, user: AuthenticatedUser, session_id: uuid.UUID) -> None:
        """End one of the caller's sessions.

        `404` for a family that is not theirs as well as one that does not exist — the
        same answer, so this cannot confirm another user's session id. The access token
        of a revoked session keeps working until it expires; that window is the same one
        Log out everywhere has, and the frontend says so.
        """
        if not await self.tokens.family_belongs_to(session_id, user.id):
            raise AppError(
                status.HTTP_404_NOT_FOUND, ErrorCode.SESSION_NOT_FOUND, "Session not found."
            )
        revoked_count = await self.tokens.revoke_family(session_id, reason="user_revoked")
        await self.session.commit()
        await self._recorder.record(
            AuditEntry(
                event_type=AuditEventType.AUTH_SESSION_REVOKED,
                actor_user_id=user.id,
                actor_email=user.email,
                ip_address=self._client_ip,
                context={
                    "familyId": str(session_id),
                    "current": session_id == user.session_id,
                    "revokedCount": revoked_count,
                },
            )
        )

    async def activity(
        self, user: AuthenticatedUser, query: ListQuery
    ) -> PaginatedResponse[ActivityEntry]:
        """The caller's own audit rows, newest first.

        Project-scoped rows are narrowed through `resolve_project_scope`, so a member
        removed from a project stops seeing its name here. An administrator's scope is
        unrestricted, so nothing is narrowed.
        """
        scope = resolve_project_scope(user)
        rows, total = await self.audit.page(
            limit=query.limit,
            offset=(query.page - 1) * query.limit,
            actor_user_id=user.id,
            visible_project_ids=None if scope.unrestricted else scope.ids,
        )
        items = [
            ActivityEntry(
                id=row.id,
                created_at=row.created_at,
                event_type=row.event_type,
                outcome=row.outcome,
                target_label=row.target_label,
                project_id=row.project_id,
                ip_address=row.ip_address,
            )
            for row in rows
        ]
        return PaginatedResponse.build(items, page=query.page, limit=query.limit, total_count=total)

    async def answer_style(self, user: AuthenticatedUser) -> AnswerStyleRead:
        """The caller's three dials, `None` where they have no preference."""
        row = await self._own_row(user)
        style = AnswerStyle.from_columns(
            row.answer_detail, row.answer_familiarity, row.answer_format
        )
        return AnswerStyleRead(
            detail=style.detail, familiarity=style.familiarity, format=style.format
        )

    async def update_answer_style(
        self, user: AuthenticatedUser, payload: AnswerStyleUpdate
    ) -> AnswerStyleRead:
        """Replace the caller's dials, and audit what moved after the commit.

        A `PUT` that changes nothing writes no audit row: `changed` holds only fields
        that actually changed (`.claude/rules/audit-trail.md`), and an event with an
        empty `changed` would record an intention, not a change.
        """
        row = await self._own_row(user)
        before: dict[str, str | None] = {
            "answerDetail": row.answer_detail,
            "answerFamiliarity": row.answer_familiarity,
            "answerFormat": row.answer_format,
        }
        after: dict[str, str | None] = {
            "answerDetail": _stored(payload.detail),
            "answerFamiliarity": _stored(payload.familiarity),
            "answerFormat": _stored(payload.format),
        }
        row.answer_detail = after["answerDetail"]
        row.answer_familiarity = after["answerFamiliarity"]
        row.answer_format = after["answerFormat"]
        await self.session.commit()

        changed: dict[str, tuple[ChangedValue, ChangedValue]] = {
            key: (before[key], after[key]) for key in before if before[key] != after[key]
        }
        if changed:
            await self._recorder.record(
                AuditEntry(
                    event_type=AuditEventType.USER_ANSWER_STYLE_UPDATED,
                    actor_user_id=user.id,
                    actor_email=user.email,
                    target_type="user",
                    target_id=user.id,
                    target_label=user.email,
                    ip_address=self._client_ip,
                    changed=changed,
                )
            )
        return AnswerStyleRead(
            detail=payload.detail, familiarity=payload.familiarity, format=payload.format
        )

    async def _own_row(self, user: AuthenticatedUser) -> User:
        """The caller's row. Missing only if deactivated mid-request."""
        row = await self.users.get(user.id)
        if row is None:
            raise AppError(status.HTTP_404_NOT_FOUND, ErrorCode.USER_NOT_FOUND, "User not found.")
        return row


def _stored(value: StrEnum | None) -> str | None:
    """A dial's stored form: its string value, or `NULL` for no preference."""
    return value.value if value is not None else None

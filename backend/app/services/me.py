"""The caller's own account surface: memberships, sessions and activity.

Every method takes the caller and nothing that names another user. Membership comes
from `app/core/access.py`, never a query of its own
(`tests/test_scoping_is_single_point.py`).
"""

import uuid

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import memberships_for
from app.core.audit import AuditEntry, AuditEventType, AuditRecorder
from app.core.errors import AppError, ErrorCode
from app.core.middleware import AuthenticatedUser
from app.repositories.project import ProjectRepository
from app.repositories.refresh_token import RefreshTokenRepository
from app.schemas.me import MembershipSummary, SessionResponse


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

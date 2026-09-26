"""The caller's own account surface: memberships, sessions and activity.

Every method takes the caller and nothing that names another user. Membership comes
from `app/core/access.py`, never a query of its own
(`tests/test_scoping_is_single_point.py`).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import memberships_for
from app.core.middleware import AuthenticatedUser
from app.repositories.project import ProjectRepository
from app.schemas.me import MembershipSummary


class MeService:
    """Backs the routes under `/me`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.projects = ProjectRepository(session)

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

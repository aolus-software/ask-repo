"""The caller's own account surface.

Deliberately **not** under `/auth`: that prefix is exempt from the forced-password-change
gate, and nothing here should be readable before a temporary password is replaced. No
route takes a user id — there is no `/me/{id}`, and an administrator's view of other
people stays on `/users`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentUser, SessionDep
from app.schemas.errors import ERROR_RESPONSES
from app.schemas.me import MembershipSummary
from app.services.me import MeService

router = APIRouter(prefix="/me", tags=["Me"])


def get_me_service(session: SessionDep) -> MeService:
    """Provide the service with a request-scoped session."""
    return MeService(session)


MeServiceDep = Annotated[MeService, Depends(get_me_service)]


@router.get(
    "/memberships",
    response_model=list[MembershipSummary],
    status_code=status.HTTP_200_OK,
    summary="The projects you are a member of",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403)},
)
async def list_memberships(
    current_user: CurrentUser, service: MeServiceDep
) -> list[MembershipSummary]:
    return await service.memberships(current_user)

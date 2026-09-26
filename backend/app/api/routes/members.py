"""`/projects/{project_id}/members` — who may reach a project, and as what.

Access scoping is entirely `MembershipService`'s, which resolves through
`access.require_permission`. No route here filters anything itself.
"""

import uuid
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import AuditRecorderDep, CurrentUser, SessionDep, SettingsDep
from app.schemas.membership import MemberCreateRequest, MemberResponse, MemberUpdateRequest
from app.services.membership import MembershipService

router = APIRouter(prefix="/projects", tags=["members"])


def _service(
    session: SessionDep, settings: SettingsDep, recorder: AuditRecorderDep
) -> MembershipService:
    return MembershipService(session, settings, recorder=recorder)


ServiceDep = Annotated[MembershipService, Depends(_service)]


@router.get("/{project_id}/members", response_model=list[MemberResponse])
async def list_members(
    project_id: uuid.UUID, current_user: CurrentUser, service: ServiceDep
) -> Sequence[MemberResponse]:
    """Everyone with a role on this project."""
    return await service.list_members(project_id, actor=current_user)


@router.post(
    "/{project_id}/members",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_member(
    project_id: uuid.UUID,
    payload: MemberCreateRequest,
    current_user: CurrentUser,
    service: ServiceDep,
) -> MemberResponse:
    """Grant a user a role on this project."""
    return await service.grant(project_id, payload, actor=current_user)


@router.patch("/{project_id}/members/{user_id}", response_model=MemberResponse)
async def change_member_role(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: MemberUpdateRequest,
    current_user: CurrentUser,
    service: ServiceDep,
) -> MemberResponse:
    """Change an existing member's role."""
    return await service.change_role(project_id, user_id, payload, actor=current_user)


@router.delete("/{project_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: CurrentUser,
    service: ServiceDep,
) -> None:
    """Revoke a user's access to this project."""
    await service.revoke(project_id, user_id, actor=current_user)

"""Checklist change sets: proposals to apply or discard.

Applying or discarding a change set is open to every authenticated user, because reviewing
a shared document is not a destructive operation on someone else's data (spec 5.4).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentUser, SessionDep
from app.config import Settings, get_settings
from app.schemas.checklist import (
    ChangeSetApplyRequest,
    ChangeSetApplyResponse,
    ChecklistChangeSetResponse,
)
from app.schemas.errors import ERROR_RESPONSES
from app.services.checklist_change_set import ChecklistChangeSetService

router = APIRouter(prefix="/checklist-change-sets", tags=["Checklist Change Sets"])

# The body of an apply that names no operations. A module-level constant rather than
# `ChangeSetApplyRequest()` written in the signature, which ruff's B008 flags as a call
# evaluated once at import -- which is exactly what is wanted here, and a suppression is
# not the way to say so. Never mutated: the service only reads `operation_ids`.
APPLY_EVERY_OPERATION = ChangeSetApplyRequest()


def get_checklist_change_set_service(
    session: SessionDep, settings: Annotated[Settings, Depends(get_settings)]
) -> ChecklistChangeSetService:
    """Provide the service with a request-scoped session."""
    return ChecklistChangeSetService(session, settings)


ChecklistChangeSetServiceDep = Annotated[
    ChecklistChangeSetService, Depends(get_checklist_change_set_service)
]


@router.post(
    "/{change_set_id}/apply",
    response_model=ChangeSetApplyResponse,
    status_code=status.HTTP_200_OK,
    summary="Apply a proposed change set",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 409, 422)},
)
async def apply_change_set(
    change_set_id: uuid.UUID,
    current_user: CurrentUser,
    service: ChecklistChangeSetServiceDep,
    payload: ChangeSetApplyRequest = APPLY_EVERY_OPERATION,
) -> ChangeSetApplyResponse:
    """Apply the named operations, or all of them. Open to any authenticated user.

    Applying every operation is the common case, so a caller who sends no body at all
    gets that rather than a `422`.
    """
    return await service.apply(change_set_id, payload, actor=current_user)


@router.post(
    "/{change_set_id}/discard",
    response_model=ChecklistChangeSetResponse,
    status_code=status.HTTP_200_OK,
    summary="Discard a proposed change set",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 409, 422)},
)
async def discard_change_set(
    change_set_id: uuid.UUID,
    current_user: CurrentUser,
    service: ChecklistChangeSetServiceDep,
) -> ChecklistChangeSetResponse:
    """Throw the proposal away. Nothing is written to the checklist."""
    return await service.discard(change_set_id, actor=current_user)

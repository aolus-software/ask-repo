"""Mock-data change sets: proposals to apply or discard.

Applying or discarding is open to every authenticated user, matching
`checklist_change_sets.py`: reviewing a shared document is not a destructive operation
on someone else's data.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentUser, SessionDep
from app.config import Settings, get_settings
from app.schemas.errors import ERROR_RESPONSES
from app.schemas.mock_data import (
    MockDataChangeSetApplyRequest,
    MockDataChangeSetApplyResponse,
    MockDataChangeSetResponse,
)
from app.services.mock_data_change_set import MockDataChangeSetService

router = APIRouter(prefix="/mock-data-change-sets", tags=["Mock Data Change Sets"])

# Same B008-avoidance pattern as `checklist_change_sets.py`'s `APPLY_EVERY_OPERATION`.
APPLY_EVERY_OPERATION = MockDataChangeSetApplyRequest()


def get_mock_data_change_set_service(
    session: SessionDep, settings: Annotated[Settings, Depends(get_settings)]
) -> MockDataChangeSetService:
    """Provide the service with a request-scoped session."""
    return MockDataChangeSetService(session, settings)


MockDataChangeSetServiceDep = Annotated[
    MockDataChangeSetService, Depends(get_mock_data_change_set_service)
]


@router.post(
    "/{change_set_id}/apply",
    response_model=MockDataChangeSetApplyResponse,
    status_code=status.HTTP_200_OK,
    summary="Apply a proposed mock-data change set",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 409, 422)},
)
async def apply_mock_data_change_set(
    change_set_id: uuid.UUID,
    current_user: CurrentUser,
    service: MockDataChangeSetServiceDep,
    payload: MockDataChangeSetApplyRequest = APPLY_EVERY_OPERATION,
) -> MockDataChangeSetApplyResponse:
    """Apply the named operations, or all of them. Open to any authenticated user."""
    return await service.apply(change_set_id, payload, actor=current_user)


@router.post(
    "/{change_set_id}/discard",
    response_model=MockDataChangeSetResponse,
    status_code=status.HTTP_200_OK,
    summary="Discard a proposed mock-data change set",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 409, 422)},
)
async def discard_mock_data_change_set(
    change_set_id: uuid.UUID, current_user: CurrentUser, service: MockDataChangeSetServiceDep
) -> MockDataChangeSetResponse:
    """Throw the proposal away. Nothing is written to the dataset."""
    return await service.discard(change_set_id, actor=current_user)

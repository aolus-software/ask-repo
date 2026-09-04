"""Checklist test cases: each one carries an expected result and a recorded result.

Access matches projects and inverts conversations: every authenticated user reads every
item and can record what they observed (spec 2.5). Editing what a test expects is gated
on `created_by`/`is_admin` — a tester who did not author the checklist must be able to
record results without being able to quietly rewrite what was supposed to pass.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import CurrentUser, SessionDep
from app.config import Settings, get_settings
from app.schemas.checklist import (
    ChecklistItemCreateRequest,
    ChecklistItemListQuery,
    ChecklistItemResponse,
    ChecklistItemResultRequest,
    ChecklistItemUpdateRequest,
    ChecklistResultsClearRequest,
    ChecklistResultsClearResponse,
)
from app.schemas.errors import ERROR_RESPONSES
from app.schemas.pagination import PaginatedResponse
from app.services.checklist_item import ChecklistItemService

router = APIRouter(prefix="/checklist-items", tags=["Checklist Items"])

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def get_checklist_item_service(
    session: SessionDep, settings: Annotated[Settings, Depends(get_settings)]
) -> ChecklistItemService:
    """Provide the service with a request-scoped session."""
    return ChecklistItemService(session, settings)


ChecklistItemServiceDep = Annotated[ChecklistItemService, Depends(get_checklist_item_service)]


@router.get(
    "",
    response_model=PaginatedResponse[ChecklistItemResponse],
    status_code=status.HTTP_200_OK,
    summary="List checklist test cases",
    responses={code: ERROR_RESPONSES[code] for code in (400, 401, 403, 422)},
)
async def list_checklist_items(
    current_user: CurrentUser,
    service: ChecklistItemServiceDep,
    query: Annotated[ChecklistItemListQuery, Query()],
) -> PaginatedResponse[ChecklistItemResponse]:
    """A page of items the caller may read, with their current status."""
    return await service.list(query, actor=current_user)


# Declared BEFORE `/{item_id}`. FastAPI matches in declaration order, so a literal path
# declared after a parameterised one is swallowed as an id and 422s every request.
@router.get(
    "/export",
    response_class=Response,
    status_code=status.HTTP_200_OK,
    summary="Export the filtered checklist as a spreadsheet",
    responses={code: ERROR_RESPONSES[code] for code in (400, 401, 403, 409, 422)},
)
async def export_checklist(
    current_user: CurrentUser,
    service: ChecklistItemServiceDep,
    query: Annotated[ChecklistItemListQuery, Query()],
) -> Response:
    """Export all matching rows, regardless of pagination limit."""
    content = await service.export(query, actor=current_user)
    return Response(
        content=content,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="qa-checklist.xlsx"'},
    )


@router.post(
    "/clear-results",
    response_model=ChecklistResultsClearResponse,
    status_code=status.HTTP_200_OK,
    summary="Clear the recorded results the filter selects",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 422)},
)
async def clear_checklist_results(
    payload: ChecklistResultsClearRequest,
    current_user: CurrentUser,
    service: ChecklistItemServiceDep,
) -> ChecklistResultsClearResponse:
    """Reset the result on every row the filter selects, in one module.

    Ungated like the result write it undoes (spec 2.5), and `200` rather than `204`
    because the count is the answer -- a filter that matched nothing is worth seeing.

    Declared before the parameterised item routes: FastAPI matches in declaration
    order, so a literal segment after a parameterised one is swallowed as an id.
    """
    return await service.clear_results(payload, actor=current_user)


@router.post(
    "",
    response_model=ChecklistItemResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a test case by hand",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 422)},
)
async def create_checklist_item(
    payload: ChecklistItemCreateRequest,
    current_user: CurrentUser,
    service: ChecklistItemServiceDep,
) -> ChecklistItemResponse:
    """Name a test, set what it expects, and add it to a module."""
    return await service.create(payload, actor=current_user)


@router.patch(
    "/{item_id}",
    response_model=ChecklistItemResponse,
    status_code=status.HTTP_200_OK,
    summary="Edit what a test expects",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 422)},
)
async def update_checklist_item(
    item_id: uuid.UUID,
    payload: ChecklistItemUpdateRequest,
    current_user: CurrentUser,
    service: ChecklistItemServiceDep,
) -> ChecklistItemResponse:
    """Change the test's name, feature, expected result, or notes."""
    return await service.update(item_id, payload, actor=current_user)


@router.put(
    "/{item_id}/result",
    response_model=ChecklistItemResponse,
    status_code=status.HTTP_200_OK,
    summary="Record a test result",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 422)},
)
async def set_checklist_item_result(
    item_id: uuid.UUID,
    payload: ChecklistItemResultRequest,
    current_user: CurrentUser,
    service: ChecklistItemServiceDep,
) -> ChecklistItemResponse:
    """Set both fields together. Open to every authenticated user (spec 2.5)."""
    return await service.set_result(item_id, payload, actor=current_user)


@router.delete(
    "/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a test case",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 422)},
)
async def delete_checklist_item(
    item_id: uuid.UUID,
    current_user: CurrentUser,
    service: ChecklistItemServiceDep,
) -> Response:
    """Soft-delete the item and its result record."""
    await service.delete(item_id, actor=current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

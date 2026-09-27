"""Votes on model output, and the administrator's view of them.

The two writes record no audit event — the seventh exemption in
`.claude/rules/audit-trail.md`. The two reads are admin-only and never name a voter.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import AdminUser, CurrentUser, SessionDep
from app.core.feedback import FeedbackTarget
from app.schemas.errors import ERROR_RESPONSES
from app.schemas.feedback import (
    FeedbackAdminRead,
    FeedbackListQuery,
    FeedbackRead,
    FeedbackSummary,
    FeedbackSummaryQuery,
    FeedbackWrite,
)
from app.schemas.pagination import PaginatedResponse
from app.services.feedback import FeedbackService

router = APIRouter(prefix="/feedback", tags=["Feedback"])


def get_feedback_service(session: SessionDep) -> FeedbackService:
    """Provide the service with a request-scoped session."""
    return FeedbackService(session)


FeedbackServiceDep = Annotated[FeedbackService, Depends(get_feedback_service)]


@router.get(
    "",
    response_model=PaginatedResponse[FeedbackAdminRead],
    status_code=status.HTTP_200_OK,
    summary="List votes on model output (administrators)",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 422)},
)
async def list_feedback(
    current_user: AdminUser,
    service: FeedbackServiceDep,
    query: Annotated[FeedbackListQuery, Query()],
) -> PaginatedResponse[FeedbackAdminRead]:
    return await service.list_for_admin(query, actor=current_user)


@router.get(
    "/summary",
    response_model=FeedbackSummary,
    status_code=status.HTTP_200_OK,
    summary="Aggregate votes on model output (administrators)",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 422)},
)
async def feedback_summary(
    current_user: AdminUser,
    service: FeedbackServiceDep,
    query: Annotated[FeedbackSummaryQuery, Query()],
) -> FeedbackSummary:
    return await service.summary(query, actor=current_user)


@router.put(
    "/{target_type}/{target_id}",
    response_model=FeedbackRead,
    status_code=status.HTTP_200_OK,
    summary="Record or change my vote on a model output",
    responses={code: ERROR_RESPONSES[code] for code in (400, 401, 404, 422)},
)
async def put_feedback(
    target_type: FeedbackTarget,
    target_id: uuid.UUID,
    payload: FeedbackWrite,
    current_user: CurrentUser,
    service: FeedbackServiceDep,
) -> FeedbackRead:
    return await service.put(target_type, target_id, payload, actor=current_user)


@router.delete(
    "/{target_type}/{target_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Withdraw my vote on a model output",
    responses={code: ERROR_RESPONSES[code] for code in (401, 422)},
)
async def delete_feedback(
    target_type: FeedbackTarget,
    target_id: uuid.UUID,
    current_user: CurrentUser,
    service: FeedbackServiceDep,
) -> Response:
    await service.withdraw(target_type, target_id, actor=current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

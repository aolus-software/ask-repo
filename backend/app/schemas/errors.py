"""Error response models, declared so `responses` blocks reference a real schema.

These are never constructed by application code — `AppError` builds the payload. They
exist so `/docs` shows the actual error shape instead of FastAPI's default guess.
"""

import uuid

from app.core.errors import ErrorCode
from app.schemas.base import ApiModel


class ErrorBody(ApiModel):
    code: ErrorCode
    message: str


class ErrorResponse(ApiModel):
    detail: ErrorBody


class ValidationErrorBody(ErrorBody):
    fields: dict[str, str]


class ValidationErrorResponse(ApiModel):
    detail: ValidationErrorBody


class StrandedProject(ApiModel):
    """A project named in a `LAST_OWNER` refusal, so the caller can go fix it."""

    id: uuid.UUID
    name: str


class LastOwnerErrorBody(ErrorBody):
    projects: list[StrandedProject]


class LastOwnerErrorResponse(ApiModel):
    """`409 LAST_OWNER` on `DELETE /users/{id}`, which carries the blocking projects.

    A widened body needs its own declared model, the same way `422` has
    `ValidationErrorBody`. `AppError`'s `extra` can put any key in `detail`; a route
    that uses it and leaves `ERROR_RESPONSES[409]` in place ships a documented shape
    that is not the shape it returns.
    """

    detail: LastOwnerErrorBody


# Reusable fragments. A route spreads in only the statuses it can actually return —
# `.claude/rules/response-api.md` forbids copying a sibling route's block wholesale.
ERROR_RESPONSES: dict[int, dict[str, object]] = {
    400: {"model": ErrorResponse, "description": "Semantically invalid input"},
    401: {"model": ErrorResponse, "description": "Missing, expired, or malformed access token"},
    403: {"model": ErrorResponse, "description": "Authenticated but not permitted"},
    404: {"model": ErrorResponse, "description": "Not found, or not visible to the caller"},
    409: {"model": ErrorResponse, "description": "Valid request, wrong state"},
    422: {"model": ValidationErrorResponse, "description": "Request validation failed"},
    429: {"model": ErrorResponse, "description": "Rate limited"},
    503: {"model": ErrorResponse, "description": "A dependency is unreachable"},
}

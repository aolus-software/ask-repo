"""Error response models, declared so `responses` blocks reference a real schema.

These are never constructed by application code — `AppError` builds the payload. They
exist so `/docs` shows the actual error shape instead of FastAPI's default guess.
"""

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

"""The API-wide error contract.

Every error this application raises serialises as:

    {"detail": {"code": "SOME_CODE", "message": "Human readable."}}

`code` is stable and machine-readable; `message` is for a person. Validation failures
carry an additional `fields` map so a form can render an error per field.

Deciding this once, here, is what `.claude/rules/router.md` means by "an API-wide
decision": a router that invented its own shape would leave clients parsing two.
"""

import logging
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class ErrorCode(StrEnum):
    """Stable machine-readable error identifiers. Values are part of the API."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    INVALID_TOKEN = "INVALID_TOKEN"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    REFRESH_TOKEN_REUSED = "REFRESH_TOKEN_REUSED"
    PASSWORD_CHANGE_REQUIRED = "PASSWORD_CHANGE_REQUIRED"
    ADMIN_REQUIRED = "ADMIN_REQUIRED"
    WEAK_PASSWORD = "WEAK_PASSWORD"
    USER_NOT_FOUND = "USER_NOT_FOUND"
    EMAIL_ALREADY_EXISTS = "EMAIL_ALREADY_EXISTS"
    LAST_ADMIN = "LAST_ADMIN"
    INVALID_SORT_FIELD = "INVALID_SORT_FIELD"
    RATE_LIMITED = "RATE_LIMITED"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    INVALID_REPO_URL = "INVALID_REPO_URL"
    VECTOR_STORE_UNAVAILABLE = "VECTOR_STORE_UNAVAILABLE"
    CONVERSATION_NOT_FOUND = "CONVERSATION_NOT_FOUND"
    PROJECT_NOT_READY = "PROJECT_NOT_READY"
    EMBEDDING_MODEL_CHANGED = "EMBEDDING_MODEL_CHANGED"
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
    MESSAGE_NOT_FOUND = "MESSAGE_NOT_FOUND"
    EXPORT_TOO_LARGE = "EXPORT_TOO_LARGE"
    CHECKLIST_MODULE_NOT_FOUND = "CHECKLIST_MODULE_NOT_FOUND"
    CHECKLIST_ITEM_NOT_FOUND = "CHECKLIST_ITEM_NOT_FOUND"
    CHANGE_SET_NOT_FOUND = "CHANGE_SET_NOT_FOUND"
    CHANGE_SET_PENDING = "CHANGE_SET_PENDING"
    CHANGE_SET_ALREADY_RESOLVED = "CHANGE_SET_ALREADY_RESOLVED"
    GENERATION_IN_PROGRESS = "GENERATION_IN_PROGRESS"
    MODULE_PATH_NOT_INDEXED = "MODULE_PATH_NOT_INDEXED"
    MOCK_DATA_CHANGE_SET_NOT_FOUND = "MOCK_DATA_CHANGE_SET_NOT_FOUND"
    MOCK_DATA_CHANGE_SET_PENDING = "MOCK_DATA_CHANGE_SET_PENDING"
    MOCK_DATA_CHANGE_SET_ALREADY_RESOLVED = "MOCK_DATA_CHANGE_SET_ALREADY_RESOLVED"
    MOCK_DATA_GENERATION_IN_PROGRESS = "MOCK_DATA_GENERATION_IN_PROGRESS"
    MOCK_DATA_RECORD_NOT_FOUND = "MOCK_DATA_RECORD_NOT_FOUND"
    INSUFFICIENT_ROLE = "INSUFFICIENT_ROLE"
    SYSTEM_ROLE_IMMUTABLE = "SYSTEM_ROLE_IMMUTABLE"
    ROLE_NOT_FOUND = "ROLE_NOT_FOUND"
    ROLE_IN_USE = "ROLE_IN_USE"
    ROLE_NAME_EXISTS = "ROLE_NAME_EXISTS"
    LAST_OWNER = "LAST_OWNER"
    MEMBERSHIP_NOT_FOUND = "MEMBERSHIP_NOT_FOUND"
    MEMBERSHIP_EXISTS = "MEMBERSHIP_EXISTS"


def error_detail(code: ErrorCode, message: str) -> dict[str, object]:
    """Build the `detail` object. One construction site, so the shape cannot drift.

    `object`-valued rather than `str`-valued: `AppError`'s `extra` widens this past
    `code`/`message` with non-string values, e.g. `409 LAST_OWNER`'s `projects` array.
    """
    return {"code": code.value, "message": message}


class AppError(HTTPException):
    """The only exception application code raises for a client-visible error.

    Subclasses `HTTPException` so FastAPI's own handling still applies, while forcing
    the structured detail.
    """

    def __init__(
        self,
        status_code: int,
        code: ErrorCode,
        message: str,
        *,
        headers: dict[str, str] | None = None,
        extra: dict[str, object] | None = None,
    ) -> None:
        """`headers` is for the rare case a route needs to attach one to the error
        response itself — e.g. clearing a cookie on a replay — because FastAPI's
        default `HTTPException` handler builds its own response once an exception
        propagates, ignoring anything mutated on the route's injected `Response`.

        `extra` merges additional fields into the detail object alongside `code` and
        `message` — used for a `409 LAST_OWNER` that names the stranded projects.

        It widens the wire contract, so it comes with an obligation: a route that can
        raise one **must** declare a model for that status instead of the generic
        `ERROR_RESPONSES[...]` entry, the way `422` declares `ValidationErrorBody` and
        `DELETE /users/{id}` declares `LastOwnerErrorResponse`. Otherwise `/docs` and
        every generated client describe a body the route does not return. Use it when
        the extra field is what makes the error actionable, never to pass detail a
        message could carry.
        """
        detail = error_detail(code, message)
        if extra:
            detail.update(extra)
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code
        self.message = message


def _field_name(location: tuple[Any, ...]) -> str:
    """The field a validation error refers to, as the client spelled it.

    Pydantic reports `("body", "newPassword")`; the client wants `newPassword`, not the
    tuple. Non-body errors (query, path) keep their last element for the same reason.
    """
    parts = [str(part) for part in location if part not in {"body", "query", "path", "header"}]
    return ".".join(parts) if parts else "request"


async def _handle_validation_error(request: Request, error: Exception) -> JSONResponse:
    """Reshape FastAPI's `loc`-array payload into the API's one error envelope."""
    if not isinstance(error, RequestValidationError):
        raise error
    fields = {_field_name(item["loc"]): item["msg"] for item in error.errors()}
    detail = error_detail(ErrorCode.VALIDATION_ERROR, "Request validation failed.")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": {**detail, "fields": fields}},
    )


async def _handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
    """Log the real cause with a traceback; tell the client nothing about it."""
    logger.error("Unhandled exception on %s %s", request.method, request.url.path, exc_info=error)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": error_detail(ErrorCode.INTERNAL_ERROR, "Internal server error.")},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Wire the handlers. Called once, from `create_app`."""
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)

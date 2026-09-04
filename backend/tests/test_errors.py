"""One error shape for the whole API.

`docs/PRD.md:107` requires a machine-readable reason so the frontend can force a
password change. router.md forbids inventing that shape in a single router, so it is
decided here and applied everywhere (D4). These tests are what stop a second shape
appearing later.
"""

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.errors import AppError, ErrorCode, register_exception_handlers
from app.schemas.base import ApiModel


class _Body(ApiModel):
    new_password: str


def _build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise AppError(403, ErrorCode.PASSWORD_CHANGE_REQUIRED, "Change your password first.")

    @app.post("/validated")
    def validated(body: _Body) -> dict[str, str]:
        return {"ok": "yes"}

    @app.get("/crash")
    def crash() -> None:
        raise RuntimeError("something the client must never see")

    return app


async def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


async def test_app_error_carries_a_code_and_a_message() -> None:
    async with await _client(_build_app()) as client:
        response = await client.get("/boom")

    assert response.status_code == 403
    assert response.json() == {
        "detail": {
            "code": "PASSWORD_CHANGE_REQUIRED",
            "message": "Change your password first.",
        }
    }


async def test_validation_errors_use_the_same_envelope() -> None:
    """Otherwise the frontend needs two parsers for one API."""
    async with await _client(_build_app()) as client:
        response = await client.post("/validated", json={})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "VALIDATION_ERROR"
    assert isinstance(detail["message"], str)


async def test_validation_field_keys_are_camel_case() -> None:
    """docs/design.md renders a FieldError per field; it should not map loc arrays."""
    async with await _client(_build_app()) as client:
        response = await client.post("/validated", json={})

    assert "newPassword" in response.json()["detail"]["fields"]


async def test_an_unhandled_exception_leaks_nothing() -> None:
    async with await _client(_build_app()) as client:
        response = await client.get("/crash")

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail["code"] == "INTERNAL_ERROR"
    assert "something the client must never see" not in response.text


async def test_every_error_code_is_screaming_snake_case() -> None:
    """The value is a wire contract; a renamed member breaks a frontend branch."""
    for code in ErrorCode:
        assert code.value == code.value.upper()
        assert " " not in code.value


def test_checklist_error_codes_exist() -> None:
    """Each is raised by a route in this milestone; a client branches on the value."""
    for name in (
        "CHECKLIST_MODULE_NOT_FOUND",
        "CHECKLIST_ITEM_NOT_FOUND",
        "NOT_CHECKLIST_OWNER",
        "CHANGE_SET_NOT_FOUND",
        "CHANGE_SET_PENDING",
        "CHANGE_SET_ALREADY_RESOLVED",
        "GENERATION_IN_PROGRESS",
        "MODULE_PATH_NOT_INDEXED",
    ):
        assert ErrorCode[name].value == name


def test_qa_error_codes_are_retired() -> None:
    """Removing an `ErrorCode` member is a deliberate act, permitted here only
    because the sole producer of each is deleted in the same change and the sole
    consumer is the in-repo frontend replaced alongside it (spec 6.3)."""
    for name in ("QA_PAIR_NOT_FOUND", "NOT_QA_PAIR_OWNER", "NO_PENDING_RUN", "ANSWER_INCOMPLETE"):
        assert name not in ErrorCode.__members__


def test_message_not_found_survives() -> None:
    """Still raised by the conversations surface, which this milestone does not touch."""
    assert ErrorCode.MESSAGE_NOT_FOUND.value == "MESSAGE_NOT_FOUND"

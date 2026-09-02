"""The checklist wire contract: camelCase out, filters on the query model."""

import uuid

from app.schemas import SSE_EVENT_MODELS
from app.schemas.checklist import (
    ChangeOperationPayload,
    ChangeSetEvent,
    ChecklistItemListQuery,
    ChecklistItemResultRequest,
    ChecklistModuleCreateRequest,
)
from app.schemas.pagination import ListQuery


def test_module_create_accepts_camel_case_and_stores_snake() -> None:
    payload = ChecklistModuleCreateRequest.model_validate(
        {
            "projectId": str(uuid.uuid4()),
            "name": "Authentication",
            "sourcePath": "backend/app/api/routes",
        }
    )
    assert payload.source_path == "backend/app/api/routes"


def test_item_filters_live_on_the_query_model_not_beside_it() -> None:
    """FastAPI flattens a Pydantic model into query params only while it is the
    route's SOLE query parameter. A scalar beside it makes every request fail with
    `{"request": "Field required"}` (.claude/rules/rag.md)."""
    assert issubclass(ChecklistItemListQuery, ListQuery)
    for field in ("project_id", "module_id", "feature", "status", "source"):
        assert field in ChecklistItemListQuery.model_fields


def test_result_request_carries_both_fields_together() -> None:
    """`PUT`, not `PATCH`: the route replaces the whole result rather than partially
    updating an item (spec 2.5)."""
    request = ChecklistItemResultRequest.model_validate(
        {"currentResult": "Returned 500", "status": "fail"}
    )
    assert request.current_result == "Returned 500"
    assert set(ChecklistItemResultRequest.model_fields) == {"current_result", "status"}


def test_change_set_event_serialises_camel_case() -> None:
    event = ChangeSetEvent(
        change_set_id=uuid.uuid4(),
        summary="3 added, 1 expectation corrected",
        operations=[
            ChangeOperationPayload(
                op="add",
                id=uuid.uuid4(),
                feature="Login",
                test_name="Rejects a wrong password",
                expected_result="401 INVALID_CREDENTIALS",
                rationale="The handler raises on a bcrypt mismatch.",
            )
        ],
    )
    dumped = event.model_dump(by_alias=True)
    assert "changeSetId" in dumped
    assert dumped["operations"][0]["testName"] == "Rejects a wrong password"
    assert event.event_name == "changeSet"


def test_change_set_event_is_registered_for_checking() -> None:
    """SSE payloads never pass through a `response_model`, so this tuple is the only
    enforcement they get. An event added to the stream but not here ships unchecked."""
    assert ChangeSetEvent in SSE_EVENT_MODELS

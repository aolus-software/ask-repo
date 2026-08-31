"""The QA wire shapes: camelCase out, and the filters that must live on the model."""

import uuid

from app.schemas.qa_pair import QAPairCreateRequest, QAPairListQuery, QAPairResponse


def test_create_request_accepts_camel_case() -> None:
    request = QAPairCreateRequest.model_validate({"messageId": str(uuid.uuid4())})
    assert request.module is None
    assert request.tags == []


def test_list_query_carries_every_filter_as_a_field() -> None:
    """Filters are fields on the model, never scalars beside it.

    FastAPI flattens `Annotated[Model, Query()]` into individual query parameters
    only while the model is the route's SOLE query parameter. A scalar beside it
    stops the flattening, and every request then fails with
    `{"request": "Field required"}` — naming nothing in the signature.
    """
    fields = set(QAPairListQuery.model_fields)
    assert {"project_id", "module", "tag", "source", "status", "created_by"} <= fields


def test_response_serialises_snake_case_attributes_as_camel_case() -> None:
    response = QAPairResponse(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        module="auth",
        question="q",
        answer="a",
        reference_answer="a",
        tags=[],
        source="manual",
        status="unreviewed",
        reviewed_by=None,
        reviewed_at=None,
        model=None,
        eval_score=None,
        last_run_at=None,
        has_pending_run=False,
        created_at="2026-08-31T00:00:00Z",
        updated_at="2026-08-31T00:00:00Z",
    )
    dumped = response.model_dump(by_alias=True)
    assert "projectId" in dumped
    assert "referenceAnswer" in dumped
    assert "hasPendingRun" in dumped
    assert "project_id" not in dumped

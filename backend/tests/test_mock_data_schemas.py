"""camelCase-on-the-wire checks, mirroring test_checklist_schemas.py."""

import uuid
from datetime import UTC, datetime

from app.models.mock_data import MockDataDatasetStatus
from app.schemas.mock_data import (
    MockDataChangeOperationPayload,
    MockDataChangeSetEvent,
    MockDataDatasetResponse,
    MockDataGenerationRequest,
    MockDataRecordResponse,
)


def test_record_response_serialises_camel_case() -> None:
    payload = MockDataRecordResponse(
        id=uuid.uuid4(),
        checklist_module_id=uuid.uuid4(),
        fields={"name": "Acme"},
        created_by=uuid.uuid4(),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    dumped = payload.model_dump(by_alias=True)
    assert "checklistModuleId" in dumped
    assert "createdAt" in dumped


def test_dataset_response_serialises_camel_case() -> None:
    payload = MockDataDatasetResponse(
        id=uuid.uuid4(),
        checklist_module_id=uuid.uuid4(),
        status=MockDataDatasetStatus.EMPTY,
        error=None,
        indexed_generation=None,
        last_generated_at=None,
        stale=False,
        record_count=0,
        pending_change_set_id=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    dumped = payload.model_dump(by_alias=True)
    assert dumped["pendingChangeSetId"] is None
    assert dumped["recordCount"] == 0


def test_generation_request_bounds_count() -> None:
    default = MockDataGenerationRequest()
    assert default.count == 10
    assert MockDataGenerationRequest(count=50).count == 50


def test_change_set_event_has_event_name() -> None:
    event = MockDataChangeSetEvent(
        change_set_id=uuid.uuid4(),
        summary="2 records proposed",
        operations=[
            MockDataChangeOperationPayload(
                op="add",
                id=uuid.uuid4(),
                rationale="matches the Project schema",
                fields={"name": "Acme"},
            )
        ],
    )
    assert event.event_name == "mockDataChangeSet"
    assert event.model_dump(by_alias=True)["operations"][0]["op"] == "add"

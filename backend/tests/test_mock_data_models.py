"""Table shape checks for the mock data models, mirroring test_checklist_models.py."""

import uuid

from app.models.checklist import ChangeSetOrigin, ChangeSetStatus
from app.models.mock_data import (
    MockDataChangeSet,
    MockDataDataset,
    MockDataDatasetStatus,
    MockDataMessage,
    MockDataRecord,
)


def test_mock_data_dataset_status_values() -> None:
    assert {member.value for member in MockDataDatasetStatus} == {
        "empty",
        "generating",
        "review",
        "ready",
        "failed",
    }


def test_mock_data_dataset_has_lease_columns() -> None:
    columns = {column.name for column in MockDataDataset.__table__.columns}
    assert {
        "id",
        "checklist_module_id",
        "status",
        "error",
        "indexed_generation",
        "last_generated_at",
        "lease_owner",
        "lease_expires_at",
        "last_job_id",
        "deleted_at",
    } <= columns


def test_mock_data_record_has_fields_column() -> None:
    columns = {column.name for column in MockDataRecord.__table__.columns}
    assert {"id", "checklist_module_id", "fields", "created_by", "deleted_at"} <= columns


def test_mock_data_change_set_reuses_checklist_enums() -> None:
    row = MockDataChangeSet(
        id=uuid.uuid4(),
        checklist_module_id=uuid.uuid4(),
        origin=ChangeSetOrigin.GENERATION.value,
        summary="",
        operations=[],
        status=ChangeSetStatus.PENDING.value,
        created_by=uuid.uuid4(),
    )
    assert row.origin == ChangeSetOrigin.GENERATION.value


def test_mock_data_message_table_name() -> None:
    assert MockDataMessage.__tablename__ == "mock_data_messages"

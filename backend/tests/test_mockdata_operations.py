"""Mirrors test_checklist_operations.py for the mock-data narrowing function."""

from app.mockdata.model_output import ProposedMockDataOperation
from app.mockdata.operations import stored_mock_data_operation


def test_add_operation_is_never_dropped_for_its_record_id() -> None:
    # An `add` has no target, so a model filling `record_id` in anyway (schemas ask for
    # it) must not cause the operation to be dropped -- same lesson `stored_operation`
    # already teaches for checklist items.
    operation = ProposedMockDataOperation(
        op="add", record_id="new", fields={"name": "Acme"}, rationale="from Project model"
    )
    stored = stored_mock_data_operation(operation)
    assert stored is not None
    assert stored["op"] == "add"
    assert stored["recordId"] is None
    assert stored["fields"] == {"name": "Acme"}


def test_update_with_hallucinated_record_id_is_dropped() -> None:
    operation = ProposedMockDataOperation(
        op="update", record_id="the second one", changes={"name": "Globex"}, rationale="r"
    )
    assert stored_mock_data_operation(operation) is None


def test_update_with_real_record_id_is_kept() -> None:
    import uuid

    real_id = str(uuid.uuid4())
    operation = ProposedMockDataOperation(
        op="update", record_id=real_id, changes={"name": "Globex"}, rationale="r"
    )
    stored = stored_mock_data_operation(operation)
    assert stored is not None
    assert stored["recordId"] == real_id


def test_add_with_mismatched_field_keys_is_dropped() -> None:
    operation = ProposedMockDataOperation(
        op="add", fields={"name": "Acme", "extra": "x"}, rationale="r"
    )
    assert stored_mock_data_operation(operation, field_keys=["name", "start"]) is None


def test_add_with_matching_field_keys_is_kept() -> None:
    operation = ProposedMockDataOperation(op="add", fields={"name": "Acme"}, rationale="r")
    stored = stored_mock_data_operation(operation, field_keys=["name"])
    assert stored is not None
    assert stored["fields"] == {"name": "Acme"}

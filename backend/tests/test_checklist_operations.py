"""`stored_operation` is the one place a proposed operation is narrowed into stored
JSON -- see `app/checklist/operations.py` for the seam this closes.
"""

import uuid
from typing import Literal

import pytest

from app.checklist.model_output import ProposedOperation
from app.checklist.operations import stored_operation
from app.schemas.checklist import ChangeOperationPayload


def test_a_valid_update_round_trips() -> None:
    item_id = str(uuid.uuid4())
    operation = ProposedOperation(
        kind="positive",
        op="update",
        item_id=item_id,
        feature="Login",
        test_name="Locks after 5 attempts",
        expected_result="Account locks",
        rationale="Matches observed behaviour.",
    )

    result = stored_operation(operation)

    assert result is not None
    payload = ChangeOperationPayload.model_validate(result)
    assert payload.item_id == uuid.UUID(item_id)


def test_an_add_operation_has_no_target_and_is_not_dropped() -> None:
    operation = ProposedOperation(
        kind="positive",
        op="add",
        item_id="",
        feature="Auth",
        test_name="New test",
        expected_result="Should pass",
        rationale="Coverage gap.",
    )

    result = stored_operation(operation)

    assert result is not None
    assert result["itemId"] is None
    payload = ChangeOperationPayload.model_validate(result)
    assert payload.item_id is None


@pytest.mark.parametrize("op", ["update", "remove"])
def test_a_non_uuid_item_id_is_dropped_regardless_of_op(op: Literal["update", "remove"]) -> None:
    operation = ProposedOperation(
        kind="positive",
        op=op,
        item_id="item-3",
        feature="Login",
        test_name="Some test",
        expected_result="Something",
        rationale="Hallucinated id.",
    )

    result = stored_operation(operation)

    assert result is None


def test_dropping_a_bad_operation_logs_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    operation = ProposedOperation(
        kind="positive",
        op="update",
        item_id="the login one",
        feature="Login",
        test_name="Some test",
        expected_result="Something",
        rationale="Hallucinated id.",
    )

    with caplog.at_level("WARNING"):
        result = stored_operation(operation)

    assert result is None
    assert any("update" in record.message for record in caplog.records)


def test_every_surviving_dict_validates_as_change_operation_payload() -> None:
    operations = [
        ProposedOperation(kind="positive", op="add", item_id="", rationale="new"),
        ProposedOperation(
            kind="positive", op="update", item_id=str(uuid.uuid4()), rationale="edit"
        ),
        ProposedOperation(
            kind="positive", op="remove", item_id=str(uuid.uuid4()), rationale="stale"
        ),
        ProposedOperation(kind="positive", op="update", item_id="not-a-uuid", rationale="dropped"),
    ]

    results = [stored_operation(operation) for operation in operations]

    survivors = [result for result in results if result is not None]
    assert len(survivors) == 3
    for result in survivors:
        ChangeOperationPayload.model_validate(result)


def test_each_call_mints_a_distinct_id() -> None:
    operation = ProposedOperation(kind="positive", op="add", item_id="", rationale="new")

    first = stored_operation(operation)
    second = stored_operation(operation)

    assert first is not None
    assert second is not None
    assert first["id"] != second["id"]


@pytest.mark.parametrize("item_id", ["new", "auth-1", "null", "N/A", "item-3"])
def test_an_add_survives_whatever_the_model_put_in_item_id(item_id: str) -> None:
    """An `add` has no target, so its `item_id` is noise -- never a reason to drop it.

    The field exists in the schema the model is handed, and a model handed a field
    fills it in: `"new"`, `"auth-1"`, the feature name. Validating that noise as a
    `uuid.UUID` dropped every generated addition, so a generation that proposed eight
    test cases stored a change set of zero -- with a summary still claiming eight,
    because the summary counts the model's list and not the stored one. The screen
    then offers nothing to tick while Generate and the chat sit disabled behind the
    pending set, and the only way out is Discard.
    """
    operation = ProposedOperation(
        kind="positive",
        op="add",
        item_id=item_id,
        feature="Login",
        test_name="rejects an empty password",
        expected_result="422",
        rationale="r",
    )

    stored = stored_operation(operation)

    assert stored is not None
    assert stored["itemId"] is None
    ChangeOperationPayload.model_validate(stored)


@pytest.mark.parametrize("op", ["update", "remove"])
def test_a_hallucinated_item_id_still_drops_an_update_or_remove(
    op: Literal["update", "remove"],
) -> None:
    """The opposite case, and it must stay a drop: these name a row to change, so an
    id that parses as nothing targets nothing."""
    proposed = ProposedOperation(kind="positive", op=op, item_id="the login one", rationale="r")

    assert stored_operation(proposed) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("negative", "negative"),
        ("Negative", "negative"),
        ("edge case", "negative"),
        ("edge-case", "negative"),
        ("error_path", "negative"),
        ("sad path", "negative"),
        ("positive", "positive"),
        ("happy path", "positive"),
        ("", "positive"),
        ("nonsense", "positive"),
    ],
)
def test_kind_is_narrowed_and_never_drops_the_operation(raw: str, expected: str) -> None:
    """The model writes prose where an enum was asked for, so the value is narrowed.

    Word-wise and punctuation-blind, because "edge case", "edge-case" and "negative
    test" are all answers a model gives to the same question. Anything unrecognised
    falls back to positive rather than dropping the operation -- the same lesson
    `item_id` taught. Positive specifically: a mislabelled happy path is cosmetic,
    while a mislabelled failure case inflates the negative coverage the field exists
    to measure.
    """
    operation = ProposedOperation(
        op="add", kind=raw, feature="Login", test_name="t", expected_result="e", rationale="r"
    )

    stored = stored_operation(operation)

    assert stored is not None
    assert stored["kind"] == expected


def test_kind_is_absent_on_an_update_or_remove() -> None:
    """Only an `add` carries a kind directly; an update moves it through `changes`,
    where the allowlist checks it against the enum."""
    stored = stored_operation(
        ProposedOperation(kind="positive", op="remove", item_id=str(uuid.uuid4()))
    )

    assert stored is not None
    assert stored["kind"] is None

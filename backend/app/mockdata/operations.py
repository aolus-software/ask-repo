"""The one place a proposed mock-data operation is narrowed into stored JSON.

Mirrors `app/checklist/operations.py`'s `stored_operation` exactly: `record_id` is a
`str` in the model's own output and a `uuid.UUID | None` in
`MockDataChangeOperationPayload`, and this function is where that gap is closed. An
operation that cannot be represented is dropped rather than stored, so a bad id costs
one operation rather than the whole change set.
"""

import logging
import uuid

from pydantic import ValidationError

from app.mockdata.model_output import ProposedMockDataOperation
from app.schemas.mock_data import MockDataChangeOperationPayload

logger = logging.getLogger(__name__)


def stored_mock_data_operation(
    operation: ProposedMockDataOperation,
    *,
    field_keys: list[str] | None = None,
) -> dict[str, object] | None:
    """One operation, keyed camelCase because it is read back as a wire payload.

    **An `add` is never dropped for its `record_id`.** An addition has no target, so
    whatever a model fills into that field regardless is noise -- the same lesson
    `stored_operation`'s own docstring records for checklist items.

    `field_keys`, when given, is the batch's canonical key set
    (`ProposedMockDataSet.field_keys`): an `add` whose `fields` uses a different key
    set is dropped rather than stored, because a table with one row of different
    columns is not a fillable table. `None` skips the check -- the chat's `update`
    operations legitimately touch a subset of keys through `changes`, not the full set,
    so this check only ever applies to `add`.
    """
    if (
        operation.op == "add"
        and field_keys is not None
        and set(operation.fields) != set(field_keys)
    ):
        logger.warning(
            "dropping proposed add operation whose fields %r do not match the batch's"
            " key set %r",
            sorted(operation.fields),
            sorted(field_keys),
        )
        return None
    payload: dict[str, object] = {
        "op": operation.op,
        "id": str(uuid.uuid4()),
        "recordId": None if operation.op == "add" else (operation.record_id or None),
        "fields": operation.fields or None,
        "changes": operation.changes or None,
        "rationale": operation.rationale or "No rationale given.",
    }
    try:
        MockDataChangeOperationPayload.model_validate(payload)
    except ValidationError:
        logger.warning(
            "dropping proposed %s mock-data operation with unrepresentable record_id %r",
            operation.op,
            operation.record_id,
        )
        return None
    return payload

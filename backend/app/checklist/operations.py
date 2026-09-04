"""The one place a proposed operation is narrowed into stored JSON.

`ProposedOperation.item_id` is a `str` (`app/checklist/model_output.py`) because the
model echoes back an id it was shown, and a hallucinated one must not fail the whole
generation. `ChangeOperationPayload.item_id` is a `uuid.UUID | None`
(`app/schemas/checklist.py`), because the apply path and the diff UI should not each
re-parse a string. `ChecklistChangeSet.operations` is stored JSON sitting between
those two types, written as `str` and read back as `UUID`.

`stored_operation` is where that gap is closed: every dict it returns validates as a
`ChangeOperationPayload`, and an operation that cannot is dropped rather than stored.
A stored operation that cannot be read fails every reader at once -- including the
list route that shows the user the change set they would use to fix it -- so the
guarantee belongs here, at the one place data enters, not at each place it leaves.
"""

import logging
import uuid

from pydantic import ValidationError

from app.checklist.model_output import ProposedOperation
from app.schemas.checklist import ChangeOperationPayload

logger = logging.getLogger(__name__)


def stored_operation(
    operation: ProposedOperation,
    *,
    citations: list[dict[str, object]] | None = None,
) -> dict[str, object] | None:
    """One operation, keyed camelCase because it is read back as a wire payload.

    Stored in the shape `ChangeOperationPayload` parses, so the apply path and the
    diff UI read one thing rather than translating between two. Returns `None` when
    the model's `item_id` is not representable as a `uuid.UUID | None` -- a
    hallucinated id on an `update` or `remove` (`"item-3"`, `"the login one"`) names
    no row, so the operation is dropped rather than stored.

    **An `add` is never dropped for its `item_id`.** An addition has no target, so
    whatever sits in that field is noise -- and a model handed a schema with an
    `item_id` field fills it in regardless: `"new"`, `"auth-1"`, the feature name.
    Validating that noise as a `uuid.UUID` dropped every generated addition, so a
    generation that proposed eight test cases stored zero operations while its summary
    still claimed eight (the summary counts the model's list, not the stored one). The
    review screen then had nothing to tick, with Generate and the chat both disabled
    behind the pending change set.
    """
    payload: dict[str, object] = {
        "op": operation.op,
        # Minted here, not by the model: each operation needs its own id so apply
        # can be selective, and an id the model chose could collide or repeat.
        "id": str(uuid.uuid4()),
        "itemId": None if operation.op == "add" else (operation.item_id or None),
        "feature": operation.feature or None,
        "testName": operation.test_name or None,
        "expectedResult": operation.expected_result or None,
        "changes": operation.changes or None,
        "citations": citations or None,
        "rationale": operation.rationale or "No rationale given.",
    }
    try:
        ChangeOperationPayload.model_validate(payload)
    except ValidationError:
        logger.warning(
            "dropping proposed %s operation with unrepresentable item_id %r",
            operation.op,
            operation.item_id,
        )
        return None
    return payload

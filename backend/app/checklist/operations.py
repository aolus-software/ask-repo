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
import re
import uuid

from pydantic import ValidationError

from app.checklist.model_output import ProposedOperation
from app.models.checklist import ChecklistItemKind
from app.schemas.checklist import ChangeOperationPayload

logger = logging.getLogger(__name__)

# What a model actually writes when asked for a positive/negative kind. Anything
# unrecognised falls back to `positive` rather than dropping the operation -- the
# lesson `item_id` taught: a field the model fills in freely must never be able to
# delete a test case it also proposed.
_NEGATIVE_WORDS = frozenset({"negative", "negatif", "failure", "error", "edge", "invalid", "sad"})
# Recognised so that a label can win over the words that follow it. Without a
# positive vocabulary there is nothing for "positive" to match, so the scan below has
# no label to stop on and the explanation decides the kind.
_POSITIVE_WORDS = frozenset({"positive", "positif", "happy", "success", "valid", "nominal"})


def _narrow_kind(raw: str) -> ChecklistItemKind:
    """The model's `kind` as the enum: the first word that names one wins.

    Defaulting to *positive* specifically: a mislabelled happy path is a cosmetic
    error, while a mislabelled failure case inflates the negative coverage the field
    exists to measure.

    Reading the **first** recognised word rather than searching for any negative one
    is what keeps that default honest. Asked for a single word, a model writes the
    word and then justifies it -- and a positive case is justified by naming what it
    is not: "positive: valid credentials, not an error case", "positive (no invalid
    input)". Scanning for any negative word anywhere resolved the justification
    instead of the label, so those came back `negative`, and a module whose
    observations are mostly validation came back with no positive rows at all.
    """
    # Word-wise and punctuation-blind: models answer "edge case", "edge-case",
    # "negative test", "error path" as readily as the bare word.
    for word in re.split(r"[^a-z]+", raw.lower()):
        if word in _NEGATIVE_WORDS:
            return ChecklistItemKind.NEGATIVE
        if word in _POSITIVE_WORDS:
            return ChecklistItemKind.POSITIVE
    return ChecklistItemKind.POSITIVE


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
        "kind": _narrow_kind(operation.kind).value if operation.op == "add" else None,
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

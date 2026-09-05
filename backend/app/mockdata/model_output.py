"""What the mock-data generation and refinement models are asked to return.

Plain `BaseModel`, not `ApiModel`: this is the model's output contract, not a wire
contract. The service converts it into `MockDataChangeOperationPayload` on the way out,
via `stored_mock_data_operation`.
"""

from typing import Literal

from pydantic import BaseModel, Field


class ProposedMockDataOperation(BaseModel):
    """One operation the model proposes against a module's existing mock data records.

    `record_id` is a `str`, not a `UUID`, for the same reason
    `ProposedOperation.item_id` is in the checklist's own model output: the model
    echoes back an id it was shown, and a hallucinated one must fail *at apply time*
    (skipped and reported) rather than fail parsing and destroy the whole batch.
    """

    op: Literal["add", "update", "remove"] = Field(
        description="add a missing record, update an existing one, or remove a bad one"
    )
    record_id: str = Field(
        default="", description="the id of the existing record, for update and remove only"
    )
    # The full field map, required for `add`. Every operation in one batch must use the
    # same key set -- enforced by the generator/graph node reading `field_keys`
    # (`ProposedMockDataSet`), not by this model.
    fields: dict[str, str] = Field(default_factory=dict)
    # Field name to new value, for `update`.
    changes: dict[str, str] = Field(default_factory=dict)
    rationale: str = ""


class ProposedMockDataSet(BaseModel):
    """What the generator and the chat's propose node both return.

    `schema_found` is the grounding gate: `False` means the source given to the model
    contained nothing schema-shaped, and the caller must fail generation rather than
    accept an empty or invented `operations` list.
    """

    schema_found: bool = Field(
        default=False,
        description=(
            "true only if the given source contains an actual data model, ORM class, "
            "migration, or form/DTO definition for this feature"
        ),
    )
    field_keys: list[str] = Field(
        default_factory=list,
        description="the canonical field names every proposed record shares",
    )
    summary: str = ""
    operations: list[ProposedMockDataOperation] = Field(default_factory=list)

"""What the generation and refinement models are asked to return.

Plain `BaseModel`, not `ApiModel`: these are the model's output contract, not a wire
contract. Nothing here is serialised to a client -- the service converts them into
`ChangeOperationPayload` on the way out.

Every field that a well-behaved response would always fill still has a default. A model
that omits `rationale` on one operation should cost that operation its explanation, not
crash a job three minutes into a generation.
"""

from typing import Literal

from pydantic import BaseModel, Field


class ObservedBehaviour(BaseModel):
    """One thing a file does, with the lines it does it on."""

    description: str = ""
    start_line: int = 0
    end_line: int = 0


class FileObservations(BaseModel):
    """What the map step returns for one file."""

    behaviours: list[ObservedBehaviour] = Field(default_factory=list)


class ProposedOperation(BaseModel):
    """One operation the model proposes against the module's existing items.

    `item_id` is a `str` rather than a `UUID` deliberately: the model echoes back an id
    it was shown, and a hallucinated one must fail *validation at apply time* -- where
    it is skipped and reported (spec 3.3) -- rather than fail parsing and destroy the
    whole change set.
    """

    op: Literal["add", "update", "remove"]
    item_id: str = ""
    feature: str = ""
    test_name: str = ""
    expected_result: str = ""
    changes: dict[str, str] = Field(default_factory=dict)
    rationale: str = ""
    # File paths the expectation came from. Resolved to full citations by the
    # generator, which knows the line ranges; the model is not asked for those,
    # because a model asked for line numbers invents plausible ones.
    citation_paths: list[str] = Field(default_factory=list)


class ProposedChangeSet(BaseModel):
    """What the reduce step and the chat's propose node both return.

    A structured schema, not free text: a model asked for prose and then parsed
    produces a change set that fails to parse on the turn it matters (spec 4.4).
    """

    summary: str = ""
    operations: list[ProposedOperation] = Field(default_factory=list)

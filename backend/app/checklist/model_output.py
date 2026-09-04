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

    op: Literal["add", "update", "remove"] = Field(
        description="add a missing test, update an existing one, or remove a dead one"
    )
    item_id: str = Field(
        default="", description="the id of the existing item, for update and remove only"
    )
    # A `str`, not the enum, for the same reason `item_id` is: a model that answers
    # "edge case" or "Negative" must not fail parsing and destroy the whole change
    # set. It is narrowed to the enum in `stored_operation`, which defaults rather
    # than drops.
    # Required, not defaulted, and that is the whole point: a field with a default is
    # optional in the JSON schema the model is handed, and it simply omits it -- every
    # operation came back with an empty kind, which `_narrow_kind` then read as
    # positive. Still a `str` rather than the enum, so a junk value costs one
    # mislabelled test rather than the whole change set.
    kind: str = Field(
        description=(
            "'positive' if the test proves the feature works with valid input, "
            "'negative' if it proves the feature refuses what it should refuse"
        ),
    )
    feature: str = Field(default="", description="the feature this test belongs to, e.g. 'Login'")
    # Described, not just named. These two are the fields a model most readily
    # collapses into one: asked for a test it writes a single sentence, and with no
    # description to separate them it lands entirely in `expected_result`, leaving
    # every row in the grid with a blank name.
    test_name: str = Field(
        default="",
        description=(
            "SHORT label for the test, a few words naming what is being tested, "
            "e.g. 'Rejects a wrong password'. Never a full sentence, and never the "
            "expected outcome."
        ),
    )
    expected_result: str = Field(
        default="",
        description=(
            "what a CORRECT implementation should do, specifically -- the status "
            "code, message or state, e.g. '401 with code INVALID_CREDENTIALS'"
        ),
    )
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

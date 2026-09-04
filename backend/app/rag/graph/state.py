"""The graph's data: what flows between nodes, and what the model returns.

`Classification` and `EvidenceVerdict` are plain `BaseModel` rather than `ApiModel`
on purpose. They are the model's output contract, not a wire contract — nothing here
is serialised to a client. Only `Intent` reaches the browser, and it travels inside
`DoneEvent`, which is an `ApiModel` already.

`Intent` itself is defined in `app.models.conversation`, beside `FinishReason`, and
re-exported here so the graph's data still reads as one module. See that module's
docstring for why it lives there rather than here.
"""

import uuid
from typing import Literal, TypedDict

from pydantic import BaseModel, Field

from app.models.conversation import FinishReason, Intent
from app.rag.prompts import ExistingItem, Turn
from app.rag.retriever import RetrievedChunk

__all__ = [
    "Classification",
    "EvidenceVerdict",
    "Intent",
    "TurnState",
]


class Classification(BaseModel):
    """What `classify` returns: the route, and the query to retrieve on.

    Fused into one call because a model deciding "is this about the codebase?" has
    already done the work of restating the question standalone.
    """

    intent: Literal["codebase_question", "conversational", "out_of_scope"]
    search_query: str


class EvidenceVerdict(BaseModel):
    """What `grade` returns: whether the excerpts answer the question, and if not,
    what is missing and what to search for instead.

    `gap` and `better_query` default to empty so a grader that omits them when
    `sufficient` is true is valid rather than a crash partway through a turn.
    """

    sufficient: bool
    gap: str = Field(default="")
    better_query: str = Field(default="")


class TurnState(TypedDict):
    """Everything one turn carries between nodes.

    `question` and `search_query` are separate for the reason they are separate
    today: the model answers what the user asked, retrieval embeds the rewritten
    form. `message_id` and `model_id` are deliberately absent — they belong to the
    terminator, which the adapter builds, and keeping them out is part of what makes
    "exactly one terminator" structural rather than a rule six nodes must remember.
    """

    question: str
    history: list[Turn]
    project_id: uuid.UUID
    generation: int
    intent: Intent
    search_query: str
    spans: list[RetrievedChunk]
    attempts: int
    gap: str | None
    evidence_ok: bool
    answer: str
    failure: FinishReason | None
    # --- The checklist refinement path (M4) ---
    #
    # Present on every turn and empty on the Ask screen's, rather than a second state
    # (LangGraph binds one schema per compiled graph, and two would mean two graphs,
    # two adapters, and two places the terminator gets built).
    #
    # `change_set_id` is minted by the service before the stream opens, because the
    # row is written under the shield in `finally` -- so the id cannot come from the
    # insert, and the `changeSet` event has to carry it anyway (spec 5.2).
    module_name: str
    existing_items: list[ExistingItem]
    change_set_id: uuid.UUID | None
    operations: list[dict[str, object]]
    change_summary: str

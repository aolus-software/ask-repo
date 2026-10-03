"""Which feature made a model call, and the scope it ran in.

Every chat-model call passes `config=call_config(CallFeature.X)`. The graph and the
generators pass the trace seed, project id and retry attempt once, and LangChain's
inherited metadata carries them to every call beneath. Metadata, not a context
variable: a chat turn's events are pulled through an async generator whose `anext`
may run in a fresh task, so a context variable set there could not be reset safely.
"""

import uuid
from enum import StrEnum

from langchain_core.runnables import RunnableConfig

FEATURE_KEY = "askrepo_feature"
TRACE_SEED_KEY = "askrepo_trace_seed"
PROJECT_KEY = "askrepo_project_id"
ATTEMPT_KEY = "askrepo_attempt"


class CallFeature(StrEnum):
    """The feature a model call belongs to."""

    CLASSIFY = "classify"
    GRADE = "grade"
    ANSWER = "answer"
    HISTORY_ANSWER = "history_answer"
    PROPOSE_CHECKLIST = "propose_checklist"
    PROPOSE_MOCK_DATA = "propose_mock_data"
    MAP = "map"
    REDUCE = "reduce"
    GENERATE_MOCK_DATA = "generate_mock_data"
    CAPABILITY_PROBE = "capability_probe"
    UNTAGGED = "untagged"


def _scope(
    *, trace_seed: str | None, project_id: uuid.UUID | None, attempt: int | None
) -> dict[str, object]:
    metadata: dict[str, object] = {}
    if trace_seed is not None:
        metadata[TRACE_SEED_KEY] = trace_seed
    if project_id is not None:
        metadata[PROJECT_KEY] = str(project_id)
    if attempt is not None:
        metadata[ATTEMPT_KEY] = attempt
    return metadata


def scope_config(
    *, trace_seed: str | None, project_id: uuid.UUID | None, attempt: int | None = None
) -> RunnableConfig:
    """The scope a whole graph run or generation job shares, as inherited metadata."""
    return {"metadata": _scope(trace_seed=trace_seed, project_id=project_id, attempt=attempt)}


def call_config(
    feature: CallFeature,
    *,
    trace_seed: str | None = None,
    project_id: uuid.UUID | None = None,
    attempt: int | None = None,
) -> RunnableConfig:
    """One call's config: its feature, plus scope for a call that has no parent run."""
    metadata: dict[str, object] = {FEATURE_KEY: feature.value}
    metadata.update(_scope(trace_seed=trace_seed, project_id=project_id, attempt=attempt))
    return {"metadata": metadata}

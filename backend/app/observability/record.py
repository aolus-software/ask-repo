"""The one thing the call log ever sees about a model call.

**No field can hold content.** No prompt, no completion, no question, no message, no
user id — a new field here is a change to `.claude/rules/call-log.md` first, and
`tests/test_call_recorder.py` pins the field sets.

A call is announced twice: `CallStart` when it begins, `CallRecord` when it ends. The
sink needs the start so a trace can show a call as in flight with its real start time.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol


@dataclass(frozen=True, slots=True)
class CallStart:
    """The content-free announcement of a call beginning; a subset of `CallRecord`'s fields."""

    feature: str
    provider: str
    model: str
    started_at: datetime
    trace_seed: str | None
    project_id: uuid.UUID | None
    attempt: int | None
    prompt_version: str


@dataclass(frozen=True, slots=True)
class CallRecord:
    """What one finished model call cost and how it ended."""

    feature: str
    provider: str
    model: str
    started_at: datetime
    ended_at: datetime
    duration_ms: int
    outcome: Literal["success", "error"]
    # The exception's class name only. Provider error text can echo the request.
    error_class: str | None
    input_tokens: int | None
    output_tokens: int | None
    trace_seed: str | None
    project_id: uuid.UUID | None
    attempt: int | None
    prompt_version: str


class CallSink(Protocol):
    """Where call records go. `run_id` pairs a `started` with its `record`."""

    def started(self, run_id: uuid.UUID, call: CallStart) -> None: ...

    def record(self, run_id: uuid.UUID, call: CallRecord) -> None: ...

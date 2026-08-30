"""The wire contract: internal `snake_case`, external `camelCase`.

`.claude/rules/response-api.md` makes `ApiModel` mandatory for anything crossing the
HTTP boundary. FastAPI enforces it for ordinary routes by validating against the declared
`response_model` — but the **SSE event payloads** have no `response_model` to validate
against, because the body is `text/event-stream`. The `SSE_EVENT_MODELS` walk below is the
only thing holding those to the rule; an event added to the stream but not to the tuple
ships unchecked.
"""

import uuid

import pytest

from app.models.conversation import FinishReason, Intent
from app.schemas.base import ApiModel
from app.schemas.conversation import (
    SSE_EVENT_MODELS,
    DoneEvent,
    ErrorEvent,
    TokenEvent,
    encode_event,
)


class _Sample(ApiModel):
    last_indexed_commit: str
    file_count: int
    status: str


def test_serializes_multi_word_fields_as_camel_case() -> None:
    dumped = _Sample(last_indexed_commit="abc123", file_count=7, status="ready").model_dump(
        by_alias=True
    )

    assert dumped == {"lastIndexedCommit": "abc123", "fileCount": 7, "status": "ready"}


def test_accepts_snake_case_when_constructed_internally() -> None:
    """Services build models with Python names; `populate_by_name` must allow it."""
    model = _Sample(last_indexed_commit="abc123", file_count=7, status="ready")

    assert model.last_indexed_commit == "abc123"


def test_accepts_camel_case_from_a_request_body() -> None:
    model = _Sample.model_validate(
        {"lastIndexedCommit": "abc123", "fileCount": 7, "status": "ready"}
    )

    assert model.last_indexed_commit == "abc123"
    assert model.file_count == 7


def test_single_word_fields_are_unchanged() -> None:
    """Guards against an alias generator that mangles already-correct names."""
    dumped = _Sample(last_indexed_commit="x", file_count=0, status="ready").model_dump(
        by_alias=True
    )

    assert "status" in dumped


@pytest.mark.parametrize("model", SSE_EVENT_MODELS)
def test_every_sse_event_model_is_an_api_model(model: type[ApiModel]) -> None:
    """These payloads never pass through a `response_model`, so the route-schema
    walk cannot see them. A hand-built json.dumps here would ship `file_path` and
    `start_line` on the wire and no other test in the repository would notice."""
    assert issubclass(model, ApiModel)


def test_encode_event_frames_exactly_one_sse_message() -> None:
    assert encode_event(TokenEvent(text="hi")) == b'event: token\ndata: {"text":"hi"}\n\n'


def test_encoded_events_carry_camel_case_keys() -> None:
    payload = encode_event(
        DoneEvent(
            message_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            model="qwen2.5-coder:14b",
            finish_reason=FinishReason.STOP,
            cited_indexes=[1, 3],
            intent=Intent.CODEBASE_QUESTION,
        )
    )

    assert b'"messageId"' in payload
    assert b'"citedIndexes"' in payload
    assert b'"message_id"' not in payload


def test_every_terminator_carries_a_finish_reason() -> None:
    """The service reads `finishReason` off whichever terminator it saw to decide
    what to persist. An error event without one would leave a partial answer stored
    with no way to tell it apart from a complete short one."""
    assert "finish_reason" in DoneEvent.model_fields
    assert "finish_reason" in ErrorEvent.model_fields

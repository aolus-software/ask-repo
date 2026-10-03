"""The Langfuse sink sends each record's metadata and nothing else."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.config import Settings
from app.observability.langfuse_sink import LangfuseSink, build_call_log
from app.observability.record import CallRecord, CallStart
from app.observability.trace_ids import trace_id_for

CONTENT_KEYS = {"input", "output", "prompt", "completion", "messages", "user_id", "session_id"}


class FakeObservation:
    def __init__(self) -> None:
        self.updated: list[dict[str, Any]] = []
        self.ended: list[dict[str, Any]] = []

    def update(self, **kwargs: Any) -> None:
        self.updated.append(kwargs)

    def end(self, **kwargs: Any) -> None:
        self.ended.append(kwargs)


class FakeClient:
    def __init__(self) -> None:
        self.started: list[dict[str, Any]] = []
        self.observations: list[FakeObservation] = []
        self.shut = False

    def start_observation(self, **kwargs: Any) -> FakeObservation:
        self.started.append(kwargs)
        observation = FakeObservation()
        self.observations.append(observation)
        return observation

    def shutdown(self) -> None:
        self.shut = True


def _fields(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "feature": "reduce",
        "provider": "openai",
        "model": "gpt-test",
        "started_at": datetime.now(UTC),
        "trace_seed": "cs-1",
        "project_id": uuid.uuid4(),
        "attempt": 1,
        "prompt_version": "abcdefabcdef",
    }
    values.update(overrides)
    return values


def _start(**overrides: Any) -> CallStart:
    return CallStart(**_fields(**overrides))


def _record(**overrides: Any) -> CallRecord:
    values = _fields(
        ended_at=datetime.now(UTC),
        duration_ms=42,
        outcome="success",
        error_class=None,
        input_tokens=100,
        output_tokens=20,
    )
    values.update(overrides)
    return CallRecord(**values)


def _all_keys(client: FakeClient) -> set[str]:
    keys: set[str] = set()
    calls = client.started + [kw for o in client.observations for kw in o.updated + o.ended]
    for kwargs in calls:
        keys |= set(kwargs) | set(kwargs.get("metadata", {}))
    return keys


def test_a_call_becomes_one_generation_in_its_trace() -> None:
    client = FakeClient()
    sink = LangfuseSink(client)
    run_id = uuid.uuid4()
    sink.started(run_id, _start())
    sink.record(run_id, _record())

    [started] = client.started
    assert started["as_type"] == "generation"
    assert started["name"] == "reduce"
    assert started["model"] == "gpt-test"
    assert started["trace_context"] == {"trace_id": trace_id_for("cs-1")}
    [observation] = client.observations
    [update] = observation.updated
    assert update["usage_details"] == {"input": 100, "output": 20}
    assert update["metadata"]["duration_ms"] == 42
    assert update["metadata"]["outcome"] == "success"
    assert len(observation.ended) == 1


def test_no_trace_context_without_a_seed() -> None:
    client = FakeClient()
    LangfuseSink(client).started(uuid.uuid4(), _start(trace_seed=None))
    assert "trace_context" not in client.started[0]


def test_nothing_that_could_carry_content_is_sent() -> None:
    client = FakeClient()
    sink = LangfuseSink(client)
    run_id = uuid.uuid4()
    sink.started(run_id, _start())
    sink.record(run_id, _record())
    assert not CONTENT_KEYS & _all_keys(client)


def test_an_error_is_its_class_at_error_level() -> None:
    client = FakeClient()
    sink = LangfuseSink(client)
    run_id = uuid.uuid4()
    sink.started(run_id, _start())
    sink.record(
        run_id,
        _record(
            outcome="error", error_class="RateLimitError", input_tokens=None, output_tokens=None
        ),
    )
    [update] = client.observations[0].updated
    assert update["level"] == "ERROR"
    assert update["status_message"] == "RateLimitError"
    assert "usage_details" not in update
    assert not CONTENT_KEYS & _all_keys(client)


def test_a_record_without_a_start_still_yields_one_ended_observation() -> None:
    client = FakeClient()
    LangfuseSink(client).record(uuid.uuid4(), _record())
    assert len(client.started) == 1
    [observation] = client.observations
    assert len(observation.updated) == 1
    assert len(observation.ended) == 1


def test_disabled_builds_nothing_and_imports_nothing() -> None:
    import sys

    sys.modules.pop("langfuse", None)
    call_log = build_call_log(Settings(langfuse_enabled=False))
    assert call_log.callbacks == []
    call_log.shutdown()
    assert "langfuse" not in sys.modules


def test_enabling_without_both_keys_is_refused() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="LANGFUSE_PUBLIC_KEY"):
        Settings(langfuse_enabled=True, langfuse_public_key="pk")
    assert Settings(
        langfuse_enabled=True, langfuse_public_key="pk", langfuse_secret_key="sk"
    ).langfuse_enabled

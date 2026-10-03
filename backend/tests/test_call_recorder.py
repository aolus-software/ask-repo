"""The recorder turns the callback lifecycle into content-free records."""

import dataclasses
import uuid

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from app.observability.features import CallFeature, call_config, scope_config
from app.observability.record import CallRecord, CallStart
from app.observability.recorder import CallRecorder

SECRET_PROMPT = "the private repository's code: def launch_codes(): ..."
SECRET_ANSWER = "the model's answer about launch_codes"


class ListSink:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.starts: list[tuple[uuid.UUID, CallStart]] = []
        self.records: list[tuple[uuid.UUID, CallRecord]] = []

    @property
    def calls(self) -> list[CallRecord]:
        return [call for _, call in self.records]

    def started(self, run_id: uuid.UUID, call: CallStart) -> None:
        self.events.append("started")
        self.starts.append((run_id, call))

    def record(self, run_id: uuid.UUID, call: CallRecord) -> None:
        self.events.append("record")
        self.records.append((run_id, call))


class BrokenSink:
    def started(self, run_id: uuid.UUID, call: CallStart) -> None:
        raise RuntimeError("langfuse is down")

    def record(self, run_id: uuid.UUID, call: CallRecord) -> None:
        raise RuntimeError("langfuse is down")


def _model(sink: ListSink | BrokenSink, *, usage: bool = True) -> GenericFakeChatModel:
    message = AIMessage(
        content=SECRET_ANSWER,
        usage_metadata={"input_tokens": 12, "output_tokens": 5, "total_tokens": 17}
        if usage
        else None,
    )
    recorder = CallRecorder(sink, provider="openai", model="gpt-test")
    return GenericFakeChatModel(messages=iter([message]), callbacks=[recorder])


async def test_a_call_is_recorded_with_usage_and_feature() -> None:
    sink = ListSink()
    project = uuid.uuid4()

    await _model(sink).ainvoke(
        SECRET_PROMPT,
        config=call_config(CallFeature.REDUCE, trace_seed="cs-1", project_id=project, attempt=2),
    )

    [call] = sink.calls
    assert call.feature == "reduce"
    assert call.provider == "openai" and call.model == "gpt-test"
    assert call.outcome == "success" and call.error_class is None
    assert (call.input_tokens, call.output_tokens) == (12, 5)
    assert call.trace_seed == "cs-1" and call.project_id == project and call.attempt == 2
    assert call.duration_ms >= 0
    assert len(call.prompt_version) == 12


async def test_one_start_precedes_one_record_sharing_a_run_id() -> None:
    sink = ListSink()
    project = uuid.uuid4()

    await _model(sink).ainvoke(
        SECRET_PROMPT,
        config=call_config(CallFeature.REDUCE, trace_seed="cs-1", project_id=project, attempt=2),
    )

    assert sink.events == ["started", "record"]
    [(start_id, start)] = sink.starts
    [(record_id, record)] = sink.records
    assert start_id == record_id
    assert start.feature == "reduce" and start.trace_seed == "cs-1"
    assert start.project_id == project and start.attempt == 2
    assert start.started_at == record.started_at


async def test_no_field_of_a_record_can_hold_content() -> None:
    sink = ListSink()
    await _model(sink).ainvoke(SECRET_PROMPT, config=call_config(CallFeature.ANSWER))
    assert "launch_codes" not in repr(dataclasses.asdict(sink.calls[0]))
    assert "launch_codes" not in repr(sink.starts[0][1])
    assert {f.name for f in dataclasses.fields(CallRecord)} == {
        "feature",
        "provider",
        "model",
        "started_at",
        "ended_at",
        "duration_ms",
        "outcome",
        "error_class",
        "input_tokens",
        "output_tokens",
        "trace_seed",
        "project_id",
        "attempt",
        "prompt_version",
    }
    assert {f.name for f in dataclasses.fields(CallStart)} == {
        "feature",
        "provider",
        "model",
        "started_at",
        "trace_seed",
        "project_id",
        "attempt",
        "prompt_version",
    }


async def test_missing_usage_is_none_not_zero() -> None:
    sink = ListSink()
    await _model(sink, usage=False).ainvoke("q", config=call_config(CallFeature.ANSWER))
    assert (sink.calls[0].input_tokens, sink.calls[0].output_tokens) == (None, None)


async def test_an_untagged_call_is_recorded_as_untagged() -> None:
    sink = ListSink()
    await _model(sink).ainvoke("q")
    assert sink.calls[0].feature == "untagged"


async def test_an_error_records_its_class_and_never_its_message() -> None:
    sink = ListSink()
    recorder = CallRecorder(sink, provider="openai", model="gpt-test")
    model = GenericFakeChatModel(messages=iter([]), callbacks=[recorder])

    with pytest.raises(Exception):  # noqa: B017  # any failure of the exhausted fake model will do
        await model.ainvoke(SECRET_PROMPT, config=call_config(CallFeature.GRADE))

    [call] = sink.calls
    assert call.outcome == "error"
    assert call.error_class is not None and "launch_codes" not in call.error_class


async def test_a_broken_sink_never_fails_the_call() -> None:
    result = await _model(BrokenSink()).ainvoke("q", config=call_config(CallFeature.ANSWER))
    assert result.content == SECRET_ANSWER


async def test_graph_scope_reaches_a_node_call_and_merges_with_its_feature() -> None:
    """The Answerer passes scope once to the graph; each node passes only its feature."""
    sink = ListSink()
    model = _model(sink)
    project = uuid.uuid4()

    class State(TypedDict):
        out: str

    async def node(state: State) -> State:
        reply = await model.ainvoke("q", config=call_config(CallFeature.CLASSIFY))
        return {"out": str(reply.content)}

    builder = StateGraph(State)
    builder.add_node("n", node)
    builder.add_edge(START, "n")
    builder.add_edge("n", END)
    graph = builder.compile()

    async for _ in graph.astream(
        {"out": ""}, config=scope_config(trace_seed="msg-1", project_id=project)
    ):
        pass

    [call] = sink.calls
    assert call.feature == "classify"
    assert call.trace_seed == "msg-1" and call.project_id == project

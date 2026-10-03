"""A LangChain callback that records what a model call cost, never what it said.

Attached once, in `build_chat_model`'s `callbacks=`, so every call is recorded by
construction. It reads timing, usage and the error's class from the callback lifecycle
and ignores the `messages` argument entirely: content never enters this module.
Recording can never fail a call — every sink error is logged and swallowed.
"""

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import ChatGeneration, LLMResult

from app.observability.features import (
    ATTEMPT_KEY,
    FEATURE_KEY,
    PROJECT_KEY,
    TRACE_SEED_KEY,
    CallFeature,
)
from app.observability.record import CallRecord, CallSink, CallStart
from app.rag.prompt_version import PROMPT_VERSION

logger = logging.getLogger(__name__)

# A run whose end never arrives (a cancelled stream LangChain did not report) must not
# grow the table forever.
_MAX_OPEN = 1024


@dataclass(frozen=True, slots=True)
class _Open:
    started_at: datetime
    started_mono: float
    feature: str
    trace_seed: str | None
    project_id: uuid.UUID | None
    attempt: int | None


def _uuid_or_none(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value is not None else None
    except ValueError:
        return None


def _usage(response: LLMResult) -> tuple[int | None, int | None]:
    for generations in response.generations:
        for generation in generations:
            if isinstance(generation, ChatGeneration):
                usage = getattr(generation.message, "usage_metadata", None)
                if usage:
                    return usage.get("input_tokens"), usage.get("output_tokens")
    token_usage = (response.llm_output or {}).get("token_usage") or {}
    return token_usage.get("prompt_tokens"), token_usage.get("completion_tokens")


class CallRecorder(AsyncCallbackHandler):
    """Turns the callback lifecycle into `CallStart` and `CallRecord` for a sink."""

    raise_error = False

    def __init__(self, sink: CallSink, *, provider: str, model: str) -> None:
        self._sink = sink
        self._provider = provider
        self._model = model
        self._open: dict[uuid.UUID, _Open] = {}

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: uuid.UUID,
        metadata: dict[str, Any] | None = None,
        **kwargs: object,
    ) -> None:
        if len(self._open) >= _MAX_OPEN:
            self._open.clear()
        meta = metadata or {}
        attempt = meta.get(ATTEMPT_KEY)
        opened = _Open(
            started_at=datetime.now(UTC),
            started_mono=time.monotonic(),
            feature=str(meta.get(FEATURE_KEY, CallFeature.UNTAGGED.value)),
            trace_seed=str(meta[TRACE_SEED_KEY]) if meta.get(TRACE_SEED_KEY) else None,
            project_id=_uuid_or_none(meta.get(PROJECT_KEY)),
            attempt=int(attempt) if isinstance(attempt, int) else None,
        )
        self._open[run_id] = opened
        self._deliver(
            opened.feature,
            lambda: self._sink.started(
                run_id,
                CallStart(
                    feature=opened.feature,
                    provider=self._provider,
                    model=self._model,
                    started_at=opened.started_at,
                    trace_seed=opened.trace_seed,
                    project_id=opened.project_id,
                    attempt=opened.attempt,
                    prompt_version=PROMPT_VERSION,
                ),
            ),
        )

    async def on_llm_end(self, response: LLMResult, *, run_id: uuid.UUID, **kwargs: object) -> None:
        opened = self._open.pop(run_id, None)
        if opened is None:
            return
        input_tokens, output_tokens = _usage(response)
        self._emit(
            run_id,
            opened,
            outcome="success",
            error_class=None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    async def on_llm_error(
        self, error: BaseException, *, run_id: uuid.UUID, **kwargs: object
    ) -> None:
        opened = self._open.pop(run_id, None)
        if opened is None:
            return
        self._emit(
            run_id,
            opened,
            outcome="error",
            error_class=type(error).__name__,
            input_tokens=None,
            output_tokens=None,
        )

    def _emit(
        self,
        run_id: uuid.UUID,
        opened: _Open,
        *,
        outcome: str,
        error_class: str | None,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> None:
        self._deliver(
            opened.feature,
            lambda: self._sink.record(
                run_id,
                CallRecord(
                    feature=opened.feature,
                    provider=self._provider,
                    model=self._model,
                    started_at=opened.started_at,
                    ended_at=datetime.now(UTC),
                    duration_ms=int((time.monotonic() - opened.started_mono) * 1000),
                    outcome="error" if outcome == "error" else "success",
                    error_class=error_class,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    trace_seed=opened.trace_seed,
                    project_id=opened.project_id,
                    attempt=opened.attempt,
                    prompt_version=PROMPT_VERSION,
                ),
            ),
        )

    @staticmethod
    def _deliver(feature: str, send: Callable[[], None]) -> None:
        """Run one sink call; a failing sink is logged and never reaches the model call."""
        try:
            send()
        except Exception:
            logger.warning("the call log could not record a %s call", feature, exc_info=True)

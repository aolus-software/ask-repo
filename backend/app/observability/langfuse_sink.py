"""Sends call records to a self-hosted Langfuse — metadata only, never content.

`langfuse` is imported only inside `build_call_log` when the call log is enabled, like
the provider imports in `app/rag/chat.py`: an instance with it off never loads it.

A call is two-phase because the SDK cannot backdate: `start_observation` has no start
time and `end()` takes none worth using, so the observation is opened when the call
starts and ended when it finishes, and its timing is the real timing.
"""

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from app.config import Settings
from app.observability.record import CallRecord, CallStart
from app.observability.recorder import CallRecorder
from app.observability.trace_ids import trace_id_for

logger = logging.getLogger(__name__)

# Same bound as the recorder's open-run map: a call whose end never arrives must not
# leave observations here forever.
_MAX_OPEN = 1024


def _start_kwargs(call: CallStart | CallRecord) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "name": call.feature,
        "as_type": "generation",
        "model": call.model,
        "metadata": {
            "provider": call.provider,
            "feature": call.feature,
            "project_id": str(call.project_id) if call.project_id else None,
            "attempt": call.attempt,
            "prompt_version": call.prompt_version,
        },
    }
    if call.trace_seed:
        kwargs["trace_context"] = {"trace_id": trace_id_for(call.trace_seed)}
    return kwargs


class LangfuseSink:
    """One Langfuse generation observation per call: opened at start, ended at record."""

    def __init__(self, client: Any) -> None:  # noqa: ANN401  # lazily imported SDK type

        self._client = client
        self._open: dict[uuid.UUID, Any] = {}

    def started(self, run_id: uuid.UUID, call: CallStart) -> None:
        if len(self._open) >= _MAX_OPEN:
            self._open.clear()
        self._open[run_id] = self._client.start_observation(**_start_kwargs(call))

    def record(self, run_id: uuid.UUID, call: CallRecord) -> None:
        # Evicted or never started: open one now so the call is still recorded.
        observation = self._open.pop(run_id, None) or self._client.start_observation(
            **_start_kwargs(call)
        )
        update: dict[str, Any] = {
            "metadata": {
                **_start_kwargs(call)["metadata"],
                "duration_ms": call.duration_ms,
                "outcome": call.outcome,
            }
        }
        usage = {
            key: value
            for key, value in (("input", call.input_tokens), ("output", call.output_tokens))
            if value is not None
        }
        if usage:
            update["usage_details"] = usage
        if call.outcome == "error":
            update["level"] = "ERROR"
            update["status_message"] = call.error_class
        observation.update(**update)
        observation.end()


@dataclass
class CallLog:
    """The process's call log: callbacks to attach, and a shutdown that flushes."""

    callbacks: list[BaseCallbackHandler] = field(default_factory=list)
    _client: Any = None

    def shutdown(self) -> None:
        """Flush pending records; never raises."""
        if self._client is None:
            return
        try:
            self._client.shutdown()
        except Exception:
            logger.warning("the call log failed to flush on shutdown", exc_info=True)


def build_call_log(settings: Settings) -> CallLog:
    """A recorder wired to Langfuse when enabled; an empty call log otherwise."""
    if not settings.langfuse_enabled:
        return CallLog()
    from langfuse import Langfuse

    client = Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        base_url=settings.langfuse_base_url,
        environment=settings.app_env,
    )
    recorder = CallRecorder(
        LangfuseSink(client), provider=settings.chat_provider, model=settings.chat_model
    )
    return CallLog(callbacks=[recorder], _client=client)

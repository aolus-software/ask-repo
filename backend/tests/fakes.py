"""Shared test doubles for the Kafka consumer loops.

`IngestionConsumer` and `RetryConsumer` are the same shape — poll, pause everything,
do the slow thing, commit one partition, resume — so they need the same stand-in. One
copy, because the pause/commit rules encoded here are the subtle part: a second copy
is a second thing to get wrong, and a divergence between them would be invisible.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from types import SimpleNamespace

from aiokafka import ConsumerRebalanceListener, TopicPartition
from aiokafka.errors import IllegalStateError
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel, Field, PrivateAttr

from app.queue.topics import IngestionMessage


class FakeConsumer:
    """An `AIOKafkaConsumer` stand-in with aiokafka 0.14's real pause/commit rules.

    The rules that matter, all confirmed against the installed client during the Task
    17 review: `resume` and `commit` raise `IllegalStateError` for a partition that is
    no longer assigned, and a rebalance rebuilds per-partition state **un-paused**, so
    a pause does not survive one.
    """

    def __init__(
        self,
        assigned: set[TopicPartition],
        *,
        on_poll: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._assigned = set(assigned)
        self._paused: set[TopicPartition] = set()
        self.listener: ConsumerRebalanceListener | None = None
        self.committed: list[dict[TopicPartition, int]] = []
        self.keep_alive_polls = 0
        self.delivered_during_job: list[TopicPartition] = []
        # Lets a test act in the middle of a hold — a rebalance, say — at the one
        # moment a real broker could interrupt: while the loop is parked in a poll.
        self._on_poll = on_poll

    def subscribe(self, *, topics: list[str], listener: ConsumerRebalanceListener) -> None:
        self.listener = listener

    def assignment(self) -> set[TopicPartition]:
        return set(self._assigned)

    def pause(self, *partitions: TopicPartition) -> None:
        for partition in partitions:
            if partition not in self._assigned:
                raise IllegalStateError(f"No current assignment for partition {partition}")
            self._paused.add(partition)

    def resume(self, *partitions: TopicPartition) -> None:
        for partition in partitions:
            if partition not in self._assigned:
                raise IllegalStateError(f"No current assignment for partition {partition}")
            self._paused.discard(partition)

    async def rebalance_to(self, assigned: set[TopicPartition]) -> None:
        """What the broker does mid-job: new assignment, all of it un-paused.

        The listener callback is awaited as part of the rebalance, before any fetch
        can happen — which is the whole reason it is the right place to re-pause.
        """
        self._assigned = set(assigned)
        self._paused = set()
        if self.listener is not None:
            await self.listener.on_partitions_assigned(sorted(self._assigned))

    async def getmany(
        self, *, timeout_ms: int, max_records: int | None = None
    ) -> dict[TopicPartition, list[object]]:
        """Records arrive only from partitions that are assigned and not paused.

        Yields to the event loop the way a real poll does — without that the
        keep-alive loop spins and the job task is never scheduled.
        """
        await asyncio.sleep(0)
        self.keep_alive_polls += 1
        if self._on_poll is not None:
            await self._on_poll()
        live = self._assigned - self._paused
        self.delivered_during_job.extend(live)
        return {}

    async def commit(self, offsets: dict[TopicPartition, int]) -> None:
        for partition in offsets:
            if partition not in self._assigned:
                raise IllegalStateError(f"Partition {partition} is not assigned")
        self.committed.append(offsets)


def record_for(message: IngestionMessage, *, offset: int = 7) -> SimpleNamespace:
    """A `ConsumerRecord` stand-in carrying a serialised message."""
    return SimpleNamespace(value=message.to_bytes(), offset=offset)


class ScriptedChatModel(BaseChatModel):
    """A `BaseChatModel` whose stream is written in advance.

    LangChain's own `FakeListChatModel` streams, but cannot fail partway through or
    stall — and those are the two cases M2's termination handling exists for. This
    adds them:

    - `tokens` are streamed one event at a time by `astream`.
    - `fail_after=n` raises after `n` tokens, so a test can assert that the tokens
      already delivered were kept.
    - `stall_seconds` sleeps before each token, so a test can trip the timeout
      without waiting for a real one.
    - `invoke_result` is what `ainvoke` returns, which is the query rewrite. It is
      separate from `tokens` so a test can script the rewrite and the answer
      independently.
    """

    # `default_factory`, not `[]`: pydantic would deep-copy a bare mutable default
    # per instance and be safe, but RUF012 cannot see that and a suppression here
    # would read as "we know better" rather than "pydantic handles it".
    tokens: list[str] = Field(default_factory=list)
    invoke_result: str = ""
    fail_after: int | None = None
    stall_seconds: float = 0.0
    # Handed out in order by `with_structured_output`. A turn makes at most two
    # structured calls -- classify, then grade -- and they return different types, so
    # a queue is the honest shape and a single value would hide an ordering bug.
    structured_results: list[BaseModel] = Field(default_factory=list)

    # Instance-level cursor into `structured_results`, consumed across every
    # `with_structured_output` call on this instance -- not rebuilt per call, which
    # would hand every caller the same first element, and not a class attribute,
    # which would leak one instance's script into another's.
    _structured_cursor: int = PrivateAttr(default=0)

    # Every input handed to the runnable returned by `with_structured_output`, in
    # call order. Lets a test prove what a node actually sent the model -- not just
    # what the model handed back -- which matters for a prompt-injection regression
    # guard. Instance-level for the same reason as the cursor above: a class
    # attribute would leak one test's captured calls into another's model.
    _captured_messages: list[object] = PrivateAttr(default_factory=list)

    @property
    def captured_messages(self) -> list[object]:
        """Every input passed to `with_structured_output`'s runnable, in call order."""
        return list(self._captured_messages)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: object | None = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        for index, token in enumerate(self.tokens):
            if self.fail_after is not None and index == self.fail_after:
                raise RuntimeError("scripted model failure")
            if self.stall_seconds:
                await asyncio.sleep(self.stall_seconds)
            yield ChatGenerationChunk(message=AIMessageChunk(content=token))

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: object | None = None,
        **kwargs: object,
    ) -> ChatResult:
        """Backs `ainvoke`, which is how the query rewrite calls the model."""
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=self.invoke_result))]
        )

    def with_structured_output(
        self, schema: object, **kwargs: object
    ) -> Runnable[object, BaseModel]:
        """Serve the next scripted result instead of calling a real provider.

        LangChain's default implementation binds a tool call and parses the model's
        reply, which a scripted fake cannot satisfy. The cursor lives on the instance
        so `classify` and `grade` -- two separate calls to this method on one model,
        expecting two different types -- draw from the same queue in order, rather
        than each getting a fresh copy of the whole list.
        """

        def _next(messages: object) -> BaseModel:
            self._captured_messages.append(messages)
            assert self._structured_cursor < len(self.structured_results), (
                "the scripted model ran out of structured results"
            )
            result = self.structured_results[self._structured_cursor]
            self._structured_cursor += 1
            return result

        return RunnableLambda(_next)


class FailingChatModel(ScriptedChatModel):
    """Raises on `ainvoke` and on any structured call — the degradation paths.

    Both classify and grade must survive a model that raises, and each degrades to a
    different safe default, so one fake covering both keeps them honest.
    """

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: object | None = None,
        **kwargs: object,
    ) -> ChatResult:
        raise RuntimeError("scripted model failure")

    def with_structured_output(
        self, schema: object, **kwargs: object
    ) -> Runnable[object, BaseModel]:
        def _raise(_: object) -> BaseModel:
            raise RuntimeError("scripted structured-output failure")

        return RunnableLambda(_raise)

"""The graph's nodes: every model call and every retrieval this turn makes.

Each node is built by a factory taking its dependencies, so the graph wiring in
`build.py` holds no business logic and a node can be constructed against a fake
without touching a provider.

Every node degrades rather than failing the turn. `app/rag/answerer.py` set that
precedent for the query rewrite -- trading a worse answer for no answer is the wrong
trade for an optimisation -- and the grader inherits it with an asymmetry that
matters: a broken grader is treated as satisfied, because a helper that can block
answers entirely is worse than the behaviour it was added to improve.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from langchain_core.language_models import BaseChatModel
from langgraph.config import get_stream_writer

from app.rag.graph.state import Classification, Intent, TurnState
from app.rag.prompts import CLASSIFY_PROMPT, to_langchain_history
from app.schemas.conversation import StatusEvent, StreamEvent

logger = logging.getLogger(__name__)

# One short call, not a full answer. Its own budget, well under the whole-turn one,
# so a hung helper cannot consume the time the answer needs.
UTILITY_TIMEOUT_SECONDS = 20.0
# Past this the model has returned a preamble or an explanation, not a query.
MAX_QUERY_CHARS = 512

Node = Callable[[TurnState], Awaitable[dict[str, object]]]


def emit(event: StreamEvent) -> None:
    """Write one event to the turn's stream.

    The one place LangGraph's streaming API is named, so a later change of mechanism
    touches this function rather than six nodes. It resolves the writer from the
    runnable context and raises outside one -- see `run_node` in `tests/test_graph.py`
    for how a node is exercised in a test.
    """
    get_stream_writer()(event)


def build_classify(chat_model: BaseChatModel, *, enabled: bool) -> Node:
    """Route the question and rewrite it for retrieval, in one structured call.

    Fused because a model deciding "is this about the codebase?" has already done the
    work of restating the question standalone; splitting them would buy a separable
    node and cost a serialised round trip on every turn.
    """

    async def classify(state: TurnState) -> dict[str, object]:
        question = state["question"]
        fallback: dict[str, object] = {
            "intent": Intent.CODEBASE_QUESTION,
            "search_query": question,
            "attempts": 0,
        }
        if not enabled:
            return fallback

        emit(StatusEvent(phase="classifying"))
        try:
            async with asyncio.timeout(UTILITY_TIMEOUT_SECONDS):
                result = await chat_model.with_structured_output(Classification).ainvoke(
                    CLASSIFY_PROMPT.format_messages(
                        history=to_langchain_history(state["history"]), question=question
                    )
                )
        except Exception:
            logger.warning("Classification failed; retrieving on the raw question", exc_info=True)
            return fallback

        classification = Classification.model_validate(result)
        query = classification.search_query.strip()
        if not query or len(query) > MAX_QUERY_CHARS:
            logger.warning(
                "Classification returned a %d-character query; retrieving on the raw "
                "question instead of trusting the rest of the response",
                len(query),
            )
            return fallback

        intent = Intent(classification.intent)
        logger.info("Routed the question as %s", intent.value)
        return {"intent": intent, "search_query": query, "attempts": 0}

    return classify

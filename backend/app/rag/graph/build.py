"""Wiring: which node follows which, and on what condition.

Deliberately free of business logic. Every decision a node makes lives in
`nodes.py`; the two routing functions here read state a node already set, so a
change of policy is a change to one node rather than to the graph's shape.
"""

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.config import Settings
from app.rag.graph.nodes import (
    build_answer_from_history,
    build_classify,
    build_generate,
    build_grade,
    build_refuse,
    build_retrieve,
)
from app.rag.graph.state import Intent, TurnState
from app.rag.retriever import Retriever


def route_intent(state: TurnState) -> str:
    """Which path this question takes, decided by `classify`."""
    if state["intent"] is Intent.CONVERSATIONAL:
        return "answer_from_history"
    if state["intent"] is Intent.OUT_OF_SCOPE:
        return "refuse"
    return "retrieve"


def route_after_retrieval(state: TurnState) -> str:
    """Grade what was retrieved, or stop.

    Nothing retrieved means no generation at all -- with no evidence, one prompt
    sentence is the only thing between the user and a confident fabrication, and the
    refusal is the adapter's job rather than a node's. There is also nothing to
    grade, so the grader is not called on an empty span list.

    Every non-empty retrieval is graded, including the last one the budget allows.
    Skipping that grade would save a model call and leave `evidence_ok` and `gap`
    describing excerpts that were then replaced: a re-retrieval that found the right
    code would still be reported `weak_evidence`, and `generate` would be told what
    was missing from spans it no longer has. The budget bounds how many times the
    graph *searches*, which is `route_after_grading`'s job -- not whether the
    excerpts an answer is built from were ever judged.
    """
    if not state["spans"]:
        return END
    return "grade"


def route_after_grading(state: TurnState, max_attempts: int) -> str:
    """Back around for another search, or on to the answer."""
    if state["evidence_ok"] or state["attempts"] >= max_attempts:
        return "generate"
    return "retrieve"


def build_answer_graph(
    *, retriever: Retriever, chat_model: BaseChatModel, settings: Settings
) -> CompiledStateGraph[TurnState, None, TurnState, TurnState]:
    """The compiled answer graph for one instance's configuration."""
    max_attempts = settings.rag_max_retrieval_attempts

    # Each node is wrapped in `RunnableLambda`: a bare async callable structurally
    # satisfies LangGraph's `_Node` protocol at runtime, but `add_node`'s overloads
    # are a union of protocols and a concrete `Runnable`, and mypy does not attempt
    # structural matching of a plain function against a protocol union -- only the
    # `Runnable` variant resolves under strict mode. Purely a typing accommodation;
    # `RunnableLambda` changes nothing about how or when a node runs.
    graph = StateGraph(TurnState)
    graph.add_node(
        "classify",
        RunnableLambda(build_classify(chat_model, enabled=settings.rag_classify_intent)),
    )
    graph.add_node("retrieve", RunnableLambda(build_retrieve(retriever)))
    graph.add_node(
        "grade", RunnableLambda(build_grade(chat_model, enabled=settings.rag_grade_evidence))
    )
    graph.add_node(
        "generate",
        RunnableLambda(build_generate(chat_model, timeout_seconds=settings.chat_timeout_seconds)),
    )
    graph.add_node(
        "answer_from_history",
        RunnableLambda(
            build_answer_from_history(chat_model, timeout_seconds=settings.chat_timeout_seconds)
        ),
    )
    graph.add_node("refuse", RunnableLambda(build_refuse()))

    graph.add_edge(START, "classify")
    graph.add_conditional_edges(
        "classify",
        route_intent,
        {
            "retrieve": "retrieve",
            "answer_from_history": "answer_from_history",
            "refuse": "refuse",
        },
    )
    graph.add_conditional_edges(
        "retrieve",
        route_after_retrieval,
        {"grade": "grade", END: END},
    )
    graph.add_conditional_edges(
        "grade",
        lambda state: route_after_grading(state, max_attempts),
        {"retrieve": "retrieve", "generate": "generate"},
    )
    graph.add_edge("generate", END)
    graph.add_edge("answer_from_history", END)
    graph.add_edge("refuse", END)

    return graph.compile()

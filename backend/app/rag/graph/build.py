"""Wiring: which node follows which, and on what condition.

Deliberately free of business logic. Every decision a node makes lives in
`nodes.py`; the two routing functions here read state a node already set, so a
change of policy is a change to one node rather than to the graph's shape.
"""

from typing import Literal

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
    build_propose_changes,
    build_propose_mock_data_changes,
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
    *,
    retriever: Retriever,
    chat_model: BaseChatModel,
    settings: Settings,
    propose_target: Literal["checklist", "mock_data"] | None = None,
) -> CompiledStateGraph[TurnState, None, TurnState, TurnState]:
    """The compiled answer graph for one instance's configuration.

    `propose_target` adds a trailing node that proposes changes against one content
    type. `None` (the Ask screen's case) adds no trailing node at all. One graph shape
    with an optional, selectable tail rather than three graphs, because a second graph
    would need a second adapter -- and the adapter is where the single terminator is
    built.
    """
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
    graph.add_edge("refuse", END)
    if propose_target == "checklist":
        graph.add_node(
            "propose_changes",
            RunnableLambda(build_propose_changes(chat_model, enabled=settings.rag_propose_changes)),
        )
        # Both answering routes feed the proposer. A refinement instruction may
        # classify either way -- "add a test for an empty password" is a codebase
        # question, "make the third one clearer" is conversational -- and wiring only
        # `generate` would silently drop every proposal on the second kind.
        #
        # `refuse` does not: an out-of-scope turn produced no answer to propose from.
        graph.add_edge("generate", "propose_changes")
        graph.add_edge("answer_from_history", "propose_changes")
        graph.add_edge("propose_changes", END)
    elif propose_target == "mock_data":
        # Same wiring as the checklist tail above, and for the same reasons: both
        # answering routes feed it, `refuse` does not.
        graph.add_node(
            "propose_mock_data_changes",
            RunnableLambda(
                build_propose_mock_data_changes(chat_model, enabled=settings.rag_propose_changes)
            ),
        )
        graph.add_edge("generate", "propose_mock_data_changes")
        graph.add_edge("answer_from_history", "propose_mock_data_changes")
        graph.add_edge("propose_mock_data_changes", END)
    else:
        graph.add_edge("generate", END)
        graph.add_edge("answer_from_history", END)

    return graph.compile()

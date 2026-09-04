"""What the prompts do against a real model, rather than a scripted fake.

Every other test in this suite drives `ScriptedChatModel`, which returns whatever the
test scripted. That proves the graph's wiring and proves nothing at all about the
prompts: a classifier prompt that routes every out-of-scope question to
`conversational` passes the entire unit suite, because no unit test ever asks a model
anything.

Two such failures shipped in M3 and were found by hand at the merge gate -- four of
six out-of-scope questions misrouted, and one answer in five carrying a citation
label. This file is those measurements made repeatable, so the next prompt edit is
checked rather than hoped about.

Opt-in, and excluded from `make check`:

    uv run pytest -m model
    CHAT_MODEL=qwen2.5-coder:7b uv run pytest -m model

These are measurements of a probabilistic system, so the thresholds are the floors a
regression would break through, not the scores observed. At the time of writing a
qwen2.5-coder:7b scored 6/6, 4/4, 3/3 and 5/5 respectively.
"""

import re

import httpx
import pytest

from app.checklist.model_output import ProposedChangeSet
from app.checklist.operations import _narrow_kind
from app.config import Settings
from app.models.checklist import ChecklistItemKind
from app.rag.chat import build_chat_model
from app.rag.graph.state import Classification
from app.rag.prompts import (
    ANSWER_PROMPT,
    CLASSIFY_PROMPT,
    ExistingItem,
    build_reduce_prompt,
    format_spans,
)
from app.rag.retriever import RetrievedChunk

pytestmark = pytest.mark.model

CITATION_LABEL = re.compile(r"\[(\d+)\]")

OUT_OF_SCOPE = [
    "who is the president of Brazil",
    "explain the CAP theorem",
    "what does the yield keyword do in JavaScript",
    "translate good morning into Japanese",
    "recommend a good restaurant in Lisbon",
    "what year did the Berlin wall fall",
]

CODEBASE = [
    "why does the worker pause its partitions",
    "which table stores refresh tokens",
    "how are qdrant collections named",
    "what happens to vectors when a project is deleted",
]

CONVERSATIONAL = [
    "can you repeat the last part",
    "what did you just say about the lease",
    "thanks, that helps",
]

HISTORY = [
    ("human", "How does the ingestion worker avoid indexing a project twice?"),
    ("ai", "A database lease on the project row -- ProjectRepository.claim."),
]


@pytest.fixture(scope="module")
def settings() -> Settings:
    """Settings pointed at whatever chat model the operator has served.

    Skips rather than fails when nothing answers: `-m model` on a machine with no
    model running should say so, not produce a connection traceback.
    """
    resolved = Settings()
    try:
        httpx.get(resolved.chat_base_url, timeout=3.0)
    except httpx.HTTPError as err:
        pytest.skip(f"no chat model at {resolved.chat_base_url}: {err}")
    return resolved


def _span(path: str, symbol: str, content: str) -> RetrievedChunk:
    return RetrievedChunk(
        file_path=path,
        start_line=10,
        end_line=18,
        language="python",
        symbol=symbol,
        commit_sha="abc1234",
        content=content,
        score=0.8,
        chunk_indexes=(0,),
    )


SPANS = [
    _span(
        "app/core/access.py",
        "resolve_project_scope",
        "def resolve_project_scope(user: User) -> ProjectScope:\n    return ProjectScope.all()",
    ),
    _span(
        "app/ingestion/vector_store.py",
        "collection_name",
        "def collection_name(provider: str, model: str, dimensions: int) -> str:\n"
        '    return f"code_chunks__{provider}__{model}__{dimensions}"',
    ),
    _span(
        "app/queue/retry.py",
        "RetryConsumer._wait_until_due",
        "async def _wait_until_due(self, message: Job) -> None:\n"
        "    # Kafka has no delay primitive, so hold the partition head.\n"
        "    while not self._is_due(message):\n"
        "        await self._poll_keepalive()",
    ),
]

ANSWERABLE = [
    "Which function decides what projects a user can query?",
    "How is the Qdrant collection name built?",
    "How does the retry consumer wait until a job is due?",
    "What does resolve_project_scope return in phase 1?",
    "Why does the retry consumer hold the partition head instead of sleeping?",
]


async def _route(settings: Settings, question: str, history: list[tuple[str, str]]) -> str:
    model = build_chat_model(settings)
    result = await model.with_structured_output(Classification).ainvoke(
        CLASSIFY_PROMPT.format_messages(history=history, question=question)
    )
    return Classification.model_validate(result).intent


async def test_a_code_question_is_never_routed_away_from_retrieval(settings: Settings) -> None:
    """The asymmetry the classify prompt is built around: a code question answered
    from conversation history is confident, uncited, and evidence-free. This is the
    direction that must not regress, so its floor is every question."""
    routed = [await _route(settings, question, []) for question in CODEBASE]

    assert routed == ["codebase_question"] * len(CODEBASE)


async def test_out_of_scope_questions_do_not_collapse_into_conversational(
    settings: Settings,
) -> None:
    """The M3 regression: `conversational` was acting as the "not a code question"
    bucket, so general knowledge reached `answer_from_history`, which answered it --
    a poem, a Python tutorial, the capital of France. Four of six failed this before
    the prompt became an ordered cascade."""
    routed = [await _route(settings, question, []) for question in OUT_OF_SCOPE]
    correct = routed.count("out_of_scope")

    assert correct >= 5, f"only {correct}/{len(OUT_OF_SCOPE)} routed out_of_scope: {routed}"


async def test_conversational_follow_ups_still_route_to_history(settings: Settings) -> None:
    """The counterweight: a prompt pushed hard toward `out_of_scope` could start
    refusing "thanks". One miss is tolerated because it falls the safe way -- a wasted
    retrieval ending at the existing no-context refusal."""
    routed = [await _route(settings, question, HISTORY) for question in CONVERSATIONAL]
    correct = routed.count("conversational")

    assert correct >= 2, f"only {correct}/{len(CONVERSATIONAL)} routed conversational: {routed}"


async def test_the_answer_carries_citation_labels(settings: Settings) -> None:
    """Every question here is answerable from the excerpts, so a missing label is the
    model ignoring the instruction rather than having nothing to cite.

    An uncited answer is not merely untidy: the sources panel is keyed by label, so
    the reader cannot check the claim, and `uncited_answer` fires on every one.
    """
    model = build_chat_model(settings)
    context = format_spans(SPANS)
    cited = 0

    for question in ANSWERABLE:
        message = await model.ainvoke(
            ANSWER_PROMPT.format_messages(
                context=context, history=[], question=question, evidence_note=""
            )
        )
        answer = str(message.content)
        labels = set(CITATION_LABEL.findall(answer))
        assert not labels - {"1", "2", "3"}, f"cited an excerpt that does not exist: {answer}"
        cited += bool(labels)

    assert cited >= 4, f"only {cited}/{len(ANSWERABLE)} answers carried a citation label"


async def test_reduce_never_fills_in_a_current_result(settings: Settings) -> None:
    """The one property no scripted test can check: a real model, asked for a test
    plan, must not write what actually happens (spec 2.3)."""
    model = build_chat_model(settings).with_structured_output(ProposedChangeSet)
    result = await model.ainvoke(
        build_reduce_prompt(
            module_name="Authentication",
            observations=[
                ("app/auth/login.py", "raises 401 when bcrypt.checkpw fails", 30, 44),
                ("app/auth/login.py", "returns an access token on success", 45, 52),
            ],
            existing=[],
        )
    )
    assert isinstance(result, ProposedChangeSet)
    assert result.operations
    for operation in result.operations:
        assert operation.op == "add"
        assert operation.expected_result
        # No field exists for an observation, and none may be smuggled into another.
        assert "current result" not in operation.expected_result.lower()


async def test_reduce_proposes_an_update_rather_than_a_duplicate_add(settings: Settings) -> None:
    """Regeneration is a diff. A model handed an existing item whose expectation is
    now wrong must name its id, not add a second row beside it (spec 2.1)."""
    model = build_chat_model(settings).with_structured_output(ProposedChangeSet)
    existing = [
        ExistingItem(
            id="11111111-1111-1111-1111-111111111111",
            feature="Login",
            test_name="Rejects a wrong password",
            expected_result="Returns 400",
        )
    ]
    result = await model.ainvoke(
        build_reduce_prompt(
            module_name="Authentication",
            observations=[
                ("app/auth/login.py", "raises 401 INVALID_CREDENTIALS on a wrong password", 30, 44)
            ],
            existing=existing,
        )
    )
    assert isinstance(result, ProposedChangeSet)
    updates = [operation for operation in result.operations if operation.op == "update"]
    assert updates
    assert updates[0].item_id == "11111111-1111-1111-1111-111111111111"


async def test_reduce_proposes_negative_cases_not_only_happy_paths(
    settings: Settings,
) -> None:
    """The property the `kind` field exists to make measurable.

    A generator left to itself proposes happy paths: they are what the code most
    obviously does. Given observations that name a refusal and a success, the plan
    must cover both -- a checklist of only positives says nothing about what happens
    when the feature is misused, which is where defects live.

    Only a real model can check this. `ScriptedChatModel` returns whatever the test
    scripted, so the entire unit suite passes against a prompt that never asks for a
    negative case at all.
    """
    model = build_chat_model(settings).with_structured_output(ProposedChangeSet)
    result = await model.ainvoke(
        build_reduce_prompt(
            module_name="Authentication",
            observations=[
                ("app/auth/login.py", "returns an access token on a correct password", 45, 52),
                ("app/auth/login.py", "raises 401 INVALID_CREDENTIALS on a wrong password", 30, 44),
                ("app/auth/login.py", "raises 422 when the email field is missing", 20, 29),
                ("app/auth/login.py", "raises 429 after five attempts in a minute", 53, 61),
            ],
            existing=[],
        )
    )

    assert isinstance(result, ProposedChangeSet)
    # Every row needs a name. Asked for a test, a model writes one sentence and puts
    # it entirely in `expected_result` unless the two fields are described as
    # different things -- which left every row in the grid blank.
    for operation in result.operations:
        assert operation.test_name.strip(), f"unnamed test: {operation!r}"
        assert operation.expected_result.strip(), f"no expectation: {operation!r}"
    kinds = [_narrow_kind(operation.kind) for operation in result.operations]
    # Only the negative is asserted. It is the property the field exists for and the
    # one that regressed twice while this was being written: first when `kind` was
    # optional in the schema and the model omitted it, then when the prompt described
    # it away from the other per-test fields. That a happy path is also proposed is
    # not worth pinning -- the model sometimes returns only the refusals for these
    # observations, and a flaky assertion on the easy half would cost the hard one.
    assert ChecklistItemKind.NEGATIVE in kinds, (
        f"no negative test proposed for three refusal observations; kinds were {kinds}"
    )

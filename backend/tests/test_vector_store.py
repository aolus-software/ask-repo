"""Collection naming, point identity, payload contents, and failure classification."""

import uuid
from types import SimpleNamespace

import httpx
import pytest
from qdrant_client import models
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from app.ingestion.chunker import Chunk
from app.ingestion.errors import (
    IngestionError,
    RetryableIngestionError,
    TerminalIngestionError,
)
from app.ingestion.vector_store import (
    InMemoryVectorStore,
    QdrantVectorStore,
    VectorStore,
    collection_name,
    point_id,
)

# Constructing AsyncQdrantClient performs a synchronous version probe, which cannot
# reach a server in these tests. Filtered by exact message so nothing else is hidden.
pytestmark = pytest.mark.filterwarnings("ignore:Failed to obtain server version")


def chunk(index: int = 0, path: str = "app/main.py") -> Chunk:
    return Chunk(
        file_path=path,
        start_line=1,
        end_line=5,
        language="python",
        symbol="main",
        chunk_index=index,
        text="def main() -> None:\n    pass\n",
    )


def _chunk(path: str, index: int, start: int, end: int) -> Chunk:
    """A chunk whose text is its own line numbers, so merges are readable."""
    return Chunk(
        file_path=path,
        start_line=start,
        end_line=end,
        language="python",
        symbol=None,
        chunk_index=index,
        text="\n".join(f"line {number}" for number in range(start, end + 1)),
    )


def test_collection_name_encodes_provider_model_and_dimensions() -> None:
    """A collection's vector size is fixed at creation, so switching provider must
    target a different collection rather than corrupt the existing one."""
    assert (
        collection_name(provider="ollama", model="nomic-embed-text", dimensions=768)
        == "code_chunks__ollama__nomic_embed_text__768"
    )
    assert (
        collection_name(provider="openai", model="text-embedding-3-small", dimensions=1536)
        == "code_chunks__openai__text_embedding_3_small__1536"
    )


def test_point_ids_are_deterministic() -> None:
    """A rewrite of the same chunk in the same generation overwrites rather than
    duplicating, and the same chunk in a different generation gets a different id
    so re-indexing cannot silently clobber the generation still serving queries."""
    project = uuid.uuid4()
    assert point_id(project, "app/main.py", 0, 1) == point_id(project, "app/main.py", 0, 1)
    assert point_id(project, "app/main.py", 0, 1) != point_id(project, "app/main.py", 1, 1)
    assert point_id(project, "app/main.py", 0, 1) != point_id(uuid.uuid4(), "app/main.py", 0, 1)
    assert point_id(project, "app/main.py", 0, 1) != point_id(project, "app/main.py", 0, 2)


async def test_upsert_stores_the_chunk_text_in_the_payload() -> None:
    """The working copy is deleted after indexing (docs/PRD.md §4.1), so Qdrant is
    the system of record for code content. Without the text, M2 has nothing to
    inject into a prompt."""
    store = InMemoryVectorStore(dimensions=4)
    project = uuid.uuid4()

    await store.upsert(
        project_id=project,
        generation=1,
        chunks=[chunk()],
        vectors=[[0.1, 0.2, 0.3, 0.4]],
        commit_sha="a" * 40,
    )

    payload = store.points[0]["payload"]
    assert payload["content"] == "def main() -> None:\n    pass\n"
    assert payload["project_id"] == str(project)
    assert payload["generation"] == 1
    assert payload["file_path"] == "app/main.py"
    assert payload["start_line"] == 1
    assert payload["end_line"] == 5
    assert payload["commit_sha"] == "a" * 40


async def test_delete_generation_leaves_other_generations_alone() -> None:
    """The generation swap depends on this: the old set survives until the new one
    is fully written. Two upserts of the *same* chunk under different generations
    must land as two distinct points now that generation is folded into the id —
    if it were not, the second upsert would silently overwrite the first and this
    test would trivially pass with only one point ever existing."""
    store = InMemoryVectorStore(dimensions=4)
    project = uuid.uuid4()

    await store.upsert(
        project_id=project,
        generation=1,
        chunks=[chunk(0)],
        vectors=[[0.1] * 4],
        commit_sha="a" * 40,
    )
    await store.upsert(
        project_id=project,
        generation=2,
        chunks=[chunk(0)],
        vectors=[[0.2] * 4],
        commit_sha="b" * 40,
    )

    assert len(store.points) == 2

    await store.delete_generation(project_id=project, generation=1)

    assert [point["payload"]["generation"] for point in store.points] == [2]


async def test_delete_project_removes_every_generation() -> None:
    """docs/PRD.md §5.1: the Postgres row soft-deletes, the points hard-delete."""
    store = InMemoryVectorStore(dimensions=4)
    project = uuid.uuid4()
    other = uuid.uuid4()

    await store.upsert(
        project_id=project,
        generation=1,
        chunks=[chunk(0)],
        vectors=[[0.1] * 4],
        commit_sha="a" * 40,
    )
    await store.upsert(
        project_id=project,
        generation=2,
        chunks=[chunk(0)],
        vectors=[[0.2] * 4],
        commit_sha="b" * 40,
    )
    await store.upsert(
        project_id=other, generation=1, chunks=[chunk(0)], vectors=[[0.3] * 4], commit_sha="c" * 40
    )

    await store.delete_project(project)

    assert [point["payload"]["project_id"] for point in store.points] == [str(other)]


async def test_upsert_same_generation_overwrites_by_id_alone() -> None:
    """Qdrant dedups on id alone, not on (id, generation) — a fake that only
    matches when both agree would pass while the real store silently loses data.
    A retried batch for the same chunk in the same generation must still replace
    the existing point rather than appending a second one."""
    store = InMemoryVectorStore(dimensions=4)
    project = uuid.uuid4()

    await store.upsert(
        project_id=project,
        generation=1,
        chunks=[chunk(0)],
        vectors=[[0.1] * 4],
        commit_sha="a" * 40,
    )
    await store.upsert(
        project_id=project,
        generation=1,
        chunks=[chunk(0)],
        vectors=[[0.2] * 4],
        commit_sha="a" * 40,
    )

    assert len(store.points) == 1
    assert store.points[0]["vector"] == [0.2] * 4


def collection_of(store: VectorStore) -> str:
    """Mirrors Task 15's `embedding_collection=self.store.collection`.

    Typed against the protocol rather than a concrete class on purpose: the pipeline
    records which collection a project's points went into, and if `VectorStore` stops
    declaring `collection`, `uv run mypy .` fails here instead of in Task 15.
    """
    return store.collection


def test_both_stores_expose_collection_through_the_protocol() -> None:
    """Runtime half of the guard above -- the typecheck half is `collection_of`."""
    real: VectorStore = QdrantVectorStore(
        url="http://qdrant.invalid:6333", collection="code_chunks__x__y__4", dimensions=4
    )
    fake: VectorStore = InMemoryVectorStore(dimensions=4)

    assert collection_of(real) == "code_chunks__x__y__4"
    assert collection_of(fake) == "in-memory"


class FailingClient:
    """Stands in for `AsyncQdrantClient`: every call raises the error it was given.

    The real store is otherwise covered by no test at all, so its `except` blocks --
    the only place failure classification happens -- would go unexercised.
    """

    def __init__(self, error: Exception) -> None:
        self.error = error

    async def collection_exists(self, *args: object, **kwargs: object) -> bool:
        raise self.error

    async def upsert(self, *args: object, **kwargs: object) -> None:
        raise self.error

    async def delete(self, *args: object, **kwargs: object) -> None:
        raise self.error


def store_failing_with(error: Exception) -> QdrantVectorStore:
    """A real store whose client always fails. No connection is ever opened."""
    store = QdrantVectorStore(url="http://qdrant.invalid:6333", collection="c", dimensions=4)
    # Test seam: the real client would need a live server to fail in these ways.
    store._client = FailingClient(error)  # type: ignore[assignment]
    return store


# The verbatim body a live Qdrant v1.15.1 returned for a 2-float vector sent to a
# 4-dimension collection, captured during the Task 14 review.
DIMENSION_ERROR_BODY = (
    b'{"status":{"error":"Wrong input: Vector dimension error: expected dim: 4, got 2"}}'
)


def unexpected_response(status: int) -> UnexpectedResponse:
    """What the Qdrant client raises for a non-2xx, with a real dimension error body."""
    return UnexpectedResponse(
        status_code=status,
        reason_phrase="Bad Request",
        content=DIMENSION_ERROR_BODY,
        headers=httpx.Headers(),
    )


# A 4xx means the request itself is wrong and will be wrong every time; 429 and the
# 5xxs are worth another attempt. Every attempt re-clones and re-embeds the whole
# repository, which is why misclassifying costs eleven minutes and three embedding
# bills before the job reaches the dead-letter queue.
CLASSIFICATION = [
    (400, TerminalIngestionError),
    (401, TerminalIngestionError),
    (403, TerminalIngestionError),
    (404, TerminalIngestionError),
    (409, TerminalIngestionError),
    (429, RetryableIngestionError),
    (500, RetryableIngestionError),
    (503, RetryableIngestionError),
]


@pytest.mark.parametrize(("status", "expected"), CLASSIFICATION)
@pytest.mark.parametrize("operation", ["ensure_collection", "upsert", "delete_generation"])
async def test_qdrant_failures_are_classified_consistently(
    status: int, expected: type[Exception], operation: str
) -> None:
    """A permanent failure must not ride the retry ladder, and a transient one must.

    Parametrised across operations as well as statuses because the classification
    lives in three separate `except` blocks -- one hardcoded exception type in any of
    them would otherwise pass on the strength of the other two.
    """
    store = store_failing_with(unexpected_response(status))
    project = uuid.uuid4()

    with pytest.raises(expected):
        if operation == "ensure_collection":
            await store.ensure_collection()
        elif operation == "upsert":
            await store.upsert(
                project_id=project,
                generation=1,
                chunks=[chunk(0)],
                vectors=[[0.1] * 4],
                commit_sha="a" * 40,
            )
        else:
            await store.delete_generation(project_id=project, generation=1)


async def test_a_connection_failure_is_retryable() -> None:
    """Qdrant being unreachable says nothing about the request -- it may work later."""
    store = store_failing_with(ResponseHandlingException(OSError("connection refused")))

    with pytest.raises(RetryableIngestionError):
        await store.ensure_collection()


async def test_an_unrecognised_failure_is_retryable() -> None:
    """An error with no status code is not evidence the request was malformed, so it
    keeps the benefit of the doubt rather than failing the project outright."""
    store = store_failing_with(RuntimeError("something the client did not wrap"))

    with pytest.raises(RetryableIngestionError):
        await store.ensure_collection()


async def test_the_terminal_message_names_what_qdrant_rejected() -> None:
    """The operator sees this string in `Project.error`. "Qdrant upsert failed" alone
    would point them at an outage that is not happening; the dimension error names the
    actual misconfiguration."""
    store = store_failing_with(unexpected_response(400))

    with pytest.raises(TerminalIngestionError) as raised:
        await store.upsert(
            project_id=uuid.uuid4(),
            generation=1,
            chunks=[chunk(0)],
            vectors=[[0.1] * 4],
            commit_sha="a" * 40,
        )

    assert "Vector dimension error" in str(raised.value)


async def test_a_store_built_without_a_width_refuses_to_create_a_collection() -> None:
    """The delete path builds a store for a recorded collection with no probed width.

    That store must never invent one: a collection created at the wrong size makes
    every subsequent write fail. The refusal is a plain error rather than an ingestion
    error on purpose -- it is a wiring bug, and classifying it as retryable would
    spend the whole retry ladder re-cloning to reach the same mistake.
    """
    store = QdrantVectorStore(url="http://qdrant.invalid:6333", collection="c")

    assert store.dimensions is None
    with pytest.raises(RuntimeError) as raised:
        await store.ensure_collection()

    assert not isinstance(raised.value, IngestionError)
    assert "dimension" in str(raised.value)


class WidthReportingClient:
    """A client whose collection already exists, created at `existing_width`."""

    def __init__(self, existing_width: int) -> None:
        self.existing_width = existing_width
        self.created_indexes: list[str] = []

    async def collection_exists(self, *args: object, **kwargs: object) -> bool:
        return True

    async def get_collection(self, *args: object, **kwargs: object) -> object:
        """Only the path `_verify_width` reads. Building a full `CollectionInfo`
        would couple this test to every unrelated field qdrant-client requires."""
        return SimpleNamespace(
            config=SimpleNamespace(
                params=SimpleNamespace(
                    vectors=models.VectorParams(
                        size=self.existing_width, distance=models.Distance.COSINE
                    )
                )
            )
        )

    async def create_payload_index(self, *args: object, **kwargs: object) -> None:
        self.created_indexes.append(str(kwargs.get("field_name")))


def store_with_existing_width(existing: int, *, asking_for: int) -> QdrantVectorStore:
    store = QdrantVectorStore(
        url="http://qdrant.invalid:6333", collection="c", dimensions=asking_for
    )
    # Test seam: reproducing this needs a collection built at another width.
    store._client = WidthReportingClient(existing)  # type: ignore[assignment]
    return store


async def test_a_width_mismatch_on_an_existing_collection_is_terminal() -> None:
    """A collection's vector size is fixed at creation, so no retry changes the
    answer. Left unchecked this surfaced only as a 400 on every later upsert, naming
    no cause -- the collection name normally encodes the width, but a provider that
    re-tags a model id keeps the name and changes the number."""
    store = store_with_existing_width(768, asking_for=1536)

    with pytest.raises(TerminalIngestionError) as raised:
        await store.ensure_collection()

    assert "768" in str(raised.value)
    assert "1536" in str(raised.value)


async def test_a_matching_width_is_accepted_and_indexes_both_filtered_fields() -> None:
    """The width check must not reject the normal case, and both fields that get
    filtered need an index -- `generation` is filtered by the swap's delete."""
    store = store_with_existing_width(768, asking_for=768)

    await store.ensure_collection()

    client = store._client
    assert isinstance(client, WidthReportingClient)
    assert client.created_indexes == ["project_id", "generation"]


async def test_search_filters_by_project_and_generation() -> None:
    """Both filters, always.

    Mid-reindex, generations N and N+1 coexist in the collection by design. An
    unfiltered search returns a mix of two index generations of the same repo:
    every chunk is real, so nothing errors, but the line ranges in the citations
    come from two different commits and roughly half point at the wrong lines.
    """
    store = InMemoryVectorStore(dimensions=3)
    wanted = uuid.uuid4()
    other = uuid.uuid4()

    await store.upsert(
        project_id=wanted,
        generation=2,
        chunks=[_chunk("app/a.py", 0, 1, 5)],
        vectors=[[1.0, 0.0, 0.0]],
        commit_sha="aaa",
    )
    await store.upsert(
        project_id=wanted,
        generation=1,
        chunks=[_chunk("app/old.py", 0, 1, 5)],
        vectors=[[1.0, 0.0, 0.0]],
        commit_sha="bbb",
    )
    await store.upsert(
        project_id=other,
        generation=2,
        chunks=[_chunk("app/elsewhere.py", 0, 1, 5)],
        vectors=[[1.0, 0.0, 0.0]],
        commit_sha="ccc",
    )

    hits = await store.search(project_id=wanted, generation=2, vector=[1.0, 0.0, 0.0], limit=10)

    assert [hit.payload["file_path"] for hit in hits] == ["app/a.py"]


async def test_search_returns_the_closest_first_and_honours_the_limit() -> None:
    store = InMemoryVectorStore(dimensions=3)
    project = uuid.uuid4()
    await store.upsert(
        project_id=project,
        generation=0,
        chunks=[_chunk("far.py", 0, 1, 5), _chunk("near.py", 0, 1, 5)],
        vectors=[[0.0, 1.0, 0.0], [1.0, 0.0, 0.0]],
        commit_sha="aaa",
    )

    hits = await store.search(project_id=project, generation=0, vector=[1.0, 0.0, 0.0], limit=1)

    assert len(hits) == 1
    assert hits[0].payload["file_path"] == "near.py"
    assert hits[0].score > 0.9

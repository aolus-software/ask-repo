"""Merging, the overlap trim, and the context budget.

The overlap trim is the case a naive implementation passes visually and fails
exactly, so the assertions here are on exact text, not on lengths.
"""

import uuid

from app.ingestion.embedder import FakeEmbedder
from app.ingestion.vector_store import InMemoryVectorStore
from app.rag.retriever import CodeRetriever, RetrievedChunk, apply_budget, merge_adjacent, TRUNCATION_MARKER
from app.ingestion.chunker import Chunk


def _lines(start: int, end: int) -> str:
    return "\n".join(f"line {number}" for number in range(start, end + 1))


def _span(
    path: str, index: int, start: int, end: int, score: float = 0.5
) -> RetrievedChunk:
    return RetrievedChunk(
        file_path=path,
        start_line=start,
        end_line=end,
        language="python",
        symbol=None,
        commit_sha="abc1234",
        content=_lines(start, end),
        score=score,
        chunk_indexes=(index,),
    )

def _chunk_for_store(path: str, index: int, start: int, end: int) -> Chunk:
    return Chunk(
        file_path=path,
        start_line=start,
        end_line=end,
        language="python",
        symbol=None,
        chunk_index=index,
        text=_lines(start, end),
    )


def test_adjacent_chunks_merge_without_repeating_the_overlap() -> None:
    """chunk_overlap is 150 characters, so adjacent chunks SHARE text by
    construction. Concatenating them repeats ~150 characters at every seam, and
    the model reads that as code containing a duplicated fragment — which it will
    then explain, or work around, or cite.

    Chunk A covers lines 1-10 and chunk B covers 9-18, so B's first two lines are
    already present in A and must be dropped.
    """
    merged = merge_adjacent([_span("a.py", 0, 1, 10, 0.9), _span("a.py", 1, 9, 18, 0.7)])

    assert len(merged) == 1
    assert merged[0].content == _lines(1, 18)
    assert (merged[0].start_line, merged[0].end_line) == (1, 18)
    assert merged[0].score == 0.9
    assert merged[0].chunk_indexes == (0, 1)


def test_non_adjacent_chunks_in_the_same_file_stay_separate() -> None:
    """Chunk 0 and chunk 5 are different parts of the file. Merging them would
    invent a line range spanning code that was never retrieved."""
    merged = merge_adjacent([_span("a.py", 0, 1, 10), _span("a.py", 5, 90, 100)])

    assert len(merged) == 2


def test_chunks_from_different_files_never_merge() -> None:
    merged = merge_adjacent([_span("a.py", 0, 1, 10), _span("b.py", 1, 11, 20)])

    assert len(merged) == 2


def test_a_fully_contained_chunk_adds_no_text() -> None:
    """A chunk whose lines are all already present contributes nothing but its
    index. Slicing past the end of a list is silent in Python, so without this the
    bug shows up as a merged span that is quietly short."""
    merged = merge_adjacent([_span("a.py", 0, 1, 20, 0.9), _span("a.py", 1, 15, 20, 0.4)])

    assert len(merged) == 1
    assert merged[0].content == _lines(1, 20)
    assert merged[0].end_line == 20


def test_merged_spans_come_back_best_first() -> None:
    merged = merge_adjacent([_span("a.py", 0, 1, 5, 0.2), _span("b.py", 0, 1, 5, 0.8)])

    assert [span.file_path for span in merged] == ["b.py", "a.py"]


def test_the_budget_drops_the_worst_span_not_the_last() -> None:
    """Truncating a concatenated context cuts whichever span happens to be last,
    which is as likely to be the best hit as the worst."""
    kept = apply_budget(
        [_span("best.py", 0, 1, 10, 0.9), _span("worst.py", 0, 1, 10, 0.1)],
        max_chars=len(_lines(1, 10)) + 5,
    )

    assert [span.file_path for span in kept] == ["best.py"]


def test_a_single_oversized_span_is_truncated_rather_than_dropped() -> None:
    """Dropping it would return nothing at all and the model would answer from
    memory, which reads exactly like a real answer."""
    kept = apply_budget([_span("big.py", 0, 1, 400, 0.9)], max_chars=200)

    assert len(kept) == 1
    assert len(kept[0].content) <= 200 + len(TRUNCATION_MARKER)
    assert kept[0].content.endswith(TRUNCATION_MARKER)


async def test_retrieve_embeds_the_query_and_returns_typed_spans() -> None:
    store = InMemoryVectorStore(dimensions=8)
    embedder = FakeEmbedder(dimensions=8)
    project = uuid.uuid4()
    chunk_vectors = await embedder.embed_documents(["def validate(url): ..."])
    await store.upsert(
        project_id=project,
        generation=3,
        chunks=[_chunk_for_store("app/core/repo_url.py", 0, 40, 96)],
        vectors=chunk_vectors,
        commit_sha="9d12711",
    )

    retriever = CodeRetriever(store=store, embedder=embedder, top_k=12, max_chars=24_000)
    spans = await retriever.retrieve("how is the url validated", project_id=project, generation=3)

    assert len(spans) == 1
    assert spans[0].file_path == "app/core/repo_url.py"
    assert spans[0].commit_sha == "9d12711"
    assert (spans[0].start_line, spans[0].end_line) == (40, 96)

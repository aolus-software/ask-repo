"""Finding the code that answers a question.

Three things here are load-bearing:

1. **Both filters, always.** A search filtered only by `project_id` returns a mix of
   index generations during a reindex — every chunk real, nothing erroring, and
   roughly half the citations pointing at line ranges from the wrong commit.
2. **Adjacent chunks are merged, and the overlap is trimmed by line number.**
   `chunk_overlap` means neighbouring chunks share text by construction, so naive
   concatenation repeats ~150 characters at every seam and the model explains a
   duplication that is not in the file.
3. **The budget drops the worst span, never the last one.** Truncating a
   concatenated context cuts whichever span happens to be at the end, which is as
   likely to be the best hit as the worst.
"""

import uuid
from dataclasses import dataclass
from itertools import groupby

from app.ingestion.embedder import Embedder
from app.ingestion.vector_store import SearchHit, VectorStore

TRUNCATION_MARKER = "\n... (truncated)"


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """One contiguous span of code retrieved for a question.

    Our type rather than LangChain's `Document`, deliberately. A `Document` is
    `page_content` plus an untyped `metadata: dict`, which would dissolve every
    field below into dictionary keys at exactly the point where citations are built
    — and `ANN` lint cannot see inside a dict. Conversion to LangChain messages
    happens once, in `prompts.py`.
    """

    file_path: str
    start_line: int
    end_line: int
    language: str
    symbol: str | None
    commit_sha: str
    content: str
    score: float
    chunk_indexes: tuple[int, ...]


def chunk_from_hit(hit: SearchHit) -> RetrievedChunk:
    """Turn one raw Qdrant payload into a typed span. The only place that reads
    payload keys, so a renamed key breaks here and nowhere else."""
    payload = hit.payload
    return RetrievedChunk(
        file_path=str(payload["file_path"]),
        start_line=int(payload["start_line"]),
        end_line=int(payload["end_line"]),
        language=str(payload.get("language") or "text"),
        symbol=payload.get("symbol") if payload.get("symbol") is None else str(payload["symbol"]),
        commit_sha=str(payload.get("commit_sha") or ""),
        content=str(payload["content"]),
        score=hit.score,
        chunk_indexes=(int(payload["chunk_index"]),),
    )


def _join(first: RetrievedChunk, second: RetrievedChunk) -> RetrievedChunk:
    """Append `second` to `first`, dropping the lines they already share.

    `second`'s text spans lines `second.start_line..second.end_line`, so the lines
    already present in `first` are the leading
    `first.end_line - second.start_line + 1` of them. A negative result means there
    is no overlap and nothing is dropped; a result past the end means `second` is
    entirely contained and contributes only its index.
    """
    overlap = first.end_line - second.start_line + 1
    lines = second.content.split("\n")
    tail = lines[overlap:] if overlap > 0 else lines
    content = first.content if not tail else f"{first.content}\n" + "\n".join(tail)
    return RetrievedChunk(
        file_path=first.file_path,
        start_line=first.start_line,
        end_line=max(first.end_line, second.end_line),
        language=first.language,
        symbol=first.symbol or second.symbol,
        commit_sha=first.commit_sha,
        content=content,
        score=max(first.score, second.score),
        chunk_indexes=first.chunk_indexes + second.chunk_indexes,
    )


def merge_adjacent(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Fold runs of consecutive chunks of the same file into single spans.

    Returned best-first, because that is the order the prompt labels them in and
    therefore the order `[n]` citations refer to.
    """
    merged: list[RetrievedChunk] = []
    ordered = sorted(chunks, key=lambda chunk: (chunk.file_path, chunk.chunk_indexes[0]))
    for _, group in groupby(ordered, key=lambda chunk: chunk.file_path):
        run: RetrievedChunk | None = None
        for chunk in group:
            if run is not None and chunk.chunk_indexes[0] == run.chunk_indexes[-1] + 1:
                run = _join(run, chunk)
                continue
            if run is not None:
                merged.append(run)
            run = chunk
        if run is not None:
            merged.append(run)
    merged.sort(key=lambda chunk: chunk.score, reverse=True)
    return merged


def apply_budget(chunks: list[RetrievedChunk], *, max_chars: int) -> list[RetrievedChunk]:
    """Keep the best spans that fit. Nothing kept yet means truncate rather than drop."""
    kept: list[RetrievedChunk] = []
    remaining = max_chars
    for chunk in chunks:
        if len(chunk.content) <= remaining:
            kept.append(chunk)
            remaining -= len(chunk.content)
            continue
        if not kept:
            truncated = chunk.content[:remaining] + TRUNCATION_MARKER
            kept.append(
                RetrievedChunk(
                    file_path=chunk.file_path,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    language=chunk.language,
                    symbol=chunk.symbol,
                    commit_sha=chunk.commit_sha,
                    content=truncated,
                    score=chunk.score,
                    chunk_indexes=chunk.chunk_indexes,
                )
            )
        break
    return kept


class CodeRetriever:
    """Question in, contiguous code spans out."""

    def __init__(
        self, *, store: VectorStore, embedder: Embedder, top_k: int, max_chars: int
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.top_k = top_k
        self.max_chars = max_chars

    async def retrieve(
        self, query: str, *, project_id: uuid.UUID, generation: int
    ) -> list[RetrievedChunk]:
        """The spans this question should be answered from.

        `top_k` applies before merging; merging typically collapses 12 hits to 5-8
        spans, so the budget is applied to what actually reaches the prompt.
        """
        vector = await self.embedder.embed_query(query)
        hits = await self.store.search(
            project_id=project_id, generation=generation, vector=vector, limit=self.top_k
        )
        merged = merge_adjacent([chunk_from_hit(hit) for hit in hits])
        return apply_budget(merged, max_chars=self.max_chars)

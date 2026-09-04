"""Writing chunks to Qdrant.

Four things here are load-bearing and easy to get wrong:

1. **The collection name carries the model.** A collection's vector size is fixed at
   creation — nomic-embed-text is 768, text-embedding-3-small is 1536 — so a single
   fixed collection would make existing points unqueryable the moment someone flips
   EMBEDDING_PROVIDER, and Qdrant would reject the writes outright. Naming the
   collection for its contents makes a provider switch target a *different*
   collection instead.
2. **The point id carries the generation.** Reindex writes generation N+1 while
   generation N still serves queries, then flips the pointer and deletes the old set.
   An id without the generation in it would upsert the new batch *over* the old
   points, so the "stays answerable throughout" and "a failed reindex leaves the
   working index intact" guarantees would both be false. The same chunk in the same
   generation still maps to the same id, so a retried batch overwrites rather than
   duplicating.
3. **The payload holds the chunk text.** `docs/PRD.md` §4.1 deletes the working copy
   after indexing, so there is no file to re-read at query time. Qdrant is the system
   of record for code content, not merely an index over it.
4. **A 4xx is terminal, not retryable.** Every attempt on the retry ladder re-clones
   and re-embeds the whole repository, so retrying a request Qdrant will always
   reject burns eleven minutes and three embedding bills to reach the dead-letter
   queue with a misleading reason. See `_as_ingestion_error`.
"""

import math
import re
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse

from app.config import Settings
from app.ingestion.chunker import Chunk
from app.ingestion.errors import (
    IngestionError,
    RetryableIngestionError,
    TerminalIngestionError,
)

COLLECTION_PREFIX = "code_chunks"
# Qdrant collection names allow a narrow character set; model ids do not respect it.
_UNSAFE = re.compile(r"[^a-z0-9]+")
# 429 means slow down, not stop, so it stays on the retry ladder with the 5xxs.
_RETRYABLE_CLIENT_STATUS = frozenset({429})


def collection_name(*, provider: str, model: str, dimensions: int) -> str:
    """The collection holding vectors from this exact provider, model, and width."""
    safe_provider = _UNSAFE.sub("_", provider.lower()).strip("_")
    safe_model = _UNSAFE.sub("_", model.lower()).strip("_")
    return f"{COLLECTION_PREFIX}__{safe_provider}__{safe_model}__{dimensions}"


def point_id(project_id: uuid.UUID, file_path: str, chunk_index: int, generation: int) -> str:
    """A stable id for one chunk within one index generation.

    Deterministic, so re-writing the same chunk of the same generation overwrites its
    point rather than accumulating a duplicate beside it. Distinct across generations,
    so writing a new generation cannot clobber the one still answering queries.

    `chunk_index` and `generation` are integers, so no `file_path` can produce a
    colliding name however many colons it contains.
    """
    return str(uuid.uuid5(project_id, f"{file_path}:{chunk_index}:{generation}"))


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One raw Qdrant match: the payload M1 wrote, plus its similarity score.

    Deliberately dumb. Turning payload dictionaries into the typed `RetrievedChunk`
    is the retriever's job, and keeping that conversion in one place is what stops
    payload keys leaking separately into the prompt builder and the citation builder.
    """

    payload: dict[str, Any]
    score: float


def _as_ingestion_error(error: Exception, action: str) -> IngestionError:
    """Whether `action` failing this way is worth another attempt.

    A 4xx from Qdrant is our own malformed request against a schema we control — the
    wrong vector width, an unknown collection — so it will fail identically forever.
    Retrying it is not cheap: every attempt re-clones the repository and re-embeds it
    to arrive at the same 4xx, which costs real money on a hosted provider.

    Deliberately stricter than the embedder adapter, which retries every status but
    401/403. There a 400 may reflect one awkward input among thousands; here it
    reflects a misconfiguration, and the operator needs to be told that rather than
    watching the job circle the retry ladder for eleven minutes.
    """
    status = error.status_code if isinstance(error, UnexpectedResponse) else None
    if status is not None and 400 <= status < 500 and status not in _RETRYABLE_CLIENT_STATUS:
        return TerminalIngestionError(f"{action}: {error}")
    return RetryableIngestionError(f"{action}: {error}")


def _payload(
    *, project_id: uuid.UUID, generation: int, chunk: Chunk, commit_sha: str
) -> dict[str, Any]:
    """Everything M2 needs to build a citation and a prompt, with no file on disk."""
    return {
        "project_id": str(project_id),
        "generation": generation,
        "file_path": chunk.file_path,
        "start_line": chunk.start_line,
        "end_line": chunk.end_line,
        "language": chunk.language,
        "symbol": chunk.symbol,
        "chunk_index": chunk.chunk_index,
        "commit_sha": commit_sha,
        "content": chunk.text,
    }


def _cosine(left: list[float], right: list[float]) -> float:
    """Cosine similarity, with a zero vector scoring 0 rather than dividing by it."""
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


class VectorStore(Protocol):
    """Where embedded chunks live."""

    collection: str
    """Which collection this store writes to.

    Declared on the protocol, not merely on the implementations, because the pipeline
    records it on the project row (`Project.embedding_collection`) — that is how a
    later delete finds the points again once the active collection has moved on.
    """

    async def ensure_collection(self) -> None:
        """Create the collection and its payload index if absent."""
        ...

    async def search(
        self,
        *,
        project_id: uuid.UUID,
        generation: int,
        vector: list[float],
        limit: int,
    ) -> list[SearchHit]:
        """The `limit` closest chunks in one project's active generation."""
        ...

    def scroll(
        self,
        *,
        project_id: uuid.UUID,
        generation: int,
        path_prefix: str,
        page_size: int,
    ) -> AsyncIterator[list[dict[str, Any]]]:
        """Every chunk under `path_prefix`, paged, with no query vector.

        The enumeration counterpart to `search`. `CodeRetriever` returns the top-k
        chunks most similar to a query, which is the right tool for "where is X
        handled" and the wrong one for "list every feature in this module" -- top-k
        has no notion of *all of them* and cannot report what it left out (spec 2.2).

        Declared as a plain method returning an `AsyncIterator` rather than as an
        `async def`, because an async generator's declared return type is the iterator
        itself; an implementation is free to be either.
        """
        ...

    async def upsert(
        self,
        *,
        project_id: uuid.UUID,
        generation: int,
        chunks: list[Chunk],
        vectors: list[list[float]],
        commit_sha: str,
    ) -> None:
        """Write one batch of chunks under `generation`."""
        ...

    async def delete_generation(self, *, project_id: uuid.UUID, generation: int) -> None:
        """Drop one generation's points for a project."""
        ...

    async def delete_project(self, project_id: uuid.UUID) -> None:
        """Drop every point for a project, across all generations."""
        ...


class QdrantVectorStore:
    """The real store.

    `dimensions` is required only to *create* a collection, so it is optional here.
    The delete path builds a store for whichever collection a project recorded
    (`Project.embedding_collection`) and has no probed width to offer — the probe runs
    once at worker startup (spec §6.3), nowhere near a `DELETE /projects/{id}`. A
    placeholder would be worse than `None`: it names a real Qdrant property, so a
    fabricated number reads as fact and would name the wrong collection.
    """

    def __init__(self, *, url: str, collection: str, dimensions: int | None = None) -> None:
        self.collection = collection
        self.dimensions = dimensions
        self._client = AsyncQdrantClient(url=url)

    async def ensure_collection(self) -> None:
        """Create the collection and its payload indexes if absent, and check its width.

        The payload indexes are not optional: filtering without one degrades to a scan
        as the collection grows. `project_id` is filtered by every M2 query and by both
        deletes; `generation` is filtered by the swap's delete; `file_path` is filtered
        by M4's module scroll.

        An existing collection is verified rather than trusted. The name encodes the
        width, so the two normally agree — but a provider that re-tags a model id with
        a different dimension count keeps the name and changes the number, and then
        every upsert would fail with a 400 that names no cause.
        """
        dimensions = self.dimensions
        if dimensions is None:
            # Raised outside the try below on purpose: this is a wiring mistake, not a
            # Qdrant failure, and classifying it as retryable would spend three
            # attempts and two clones on a bug no attempt can fix.
            raise RuntimeError(
                "this QdrantVectorStore was built without a vector width, so it can "
                "only read and delete; creating a collection needs the probed "
                "dimension count"
            )
        try:
            if await self._client.collection_exists(self.collection):
                await self._verify_width(dimensions)
            else:
                await self._client.create_collection(
                    collection_name=self.collection,
                    vectors_config=models.VectorParams(
                        size=dimensions, distance=models.Distance.COSINE
                    ),
                )
            # Every filter this collection serves has an index. Without one the filter
            # degrades to a scan as the collection grows: `project_id` and `generation`
            # are filtered by every M2 query and by both deletes, and `file_path` by
            # M4's module scroll (spec 4.2).
            schemas: dict[str, models.PayloadSchemaType] = {
                "project_id": models.PayloadSchemaType.KEYWORD,
                "generation": models.PayloadSchemaType.INTEGER,
                "file_path": models.PayloadSchemaType.TEXT,
            }
            for field, schema in schemas.items():
                await self._client.create_payload_index(
                    collection_name=self.collection, field_name=field, field_schema=schema
                )
        except IngestionError:
            raise
        except Exception as error:
            raise _as_ingestion_error(error, "Preparing the Qdrant collection failed") from error

    async def search(
        self,
        *,
        project_id: uuid.UUID,
        generation: int,
        vector: list[float],
        limit: int,
    ) -> list[SearchHit]:
        """The `limit` closest chunks in one project's active generation.

        Both filters are mandatory and both have payload indexes created by
        `ensure_collection` — without the index this degrades to a scan as the
        collection grows, and without the generation filter a query during a reindex
        mixes two generations of the same repository.
        """
        try:
            response = await self._client.query_points(
                collection_name=self.collection,
                query=vector,
                query_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="project_id", match=models.MatchValue(value=str(project_id))
                        ),
                        models.FieldCondition(
                            key="generation", match=models.MatchValue(value=generation)
                        ),
                    ]
                ),
                limit=limit,
                with_payload=True,
            )
        except Exception as error:
            raise _as_ingestion_error(error, "Qdrant search failed") from error
        return [
            SearchHit(payload=dict(point.payload or {}), score=point.score)
            for point in response.points
        ]

    async def scroll(
        self,
        *,
        project_id: uuid.UUID,
        generation: int,
        path_prefix: str,
        page_size: int,
    ) -> AsyncIterator[list[dict[str, Any]]]:
        """Page through every chunk under `path_prefix` in one generation.

        `with_vectors=False`: the generator reads text, and shipping a 768-float vector
        per chunk over a whole module is bandwidth spent on nothing.

        The prefix filter needs the `file_path` payload index `ensure_collection`
        creates. Without it this degrades to a scan of the whole collection, which is
        the same failure the `project_id` and `generation` indexes exist to prevent.
        """
        offset: Any = None
        while True:
            try:
                points, offset = await self._client.scroll(
                    collection_name=self.collection,
                    scroll_filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="project_id", match=models.MatchValue(value=str(project_id))
                            ),
                            models.FieldCondition(
                                key="generation", match=models.MatchValue(value=generation)
                            ),
                            models.FieldCondition(
                                key="file_path", match=models.MatchText(text=path_prefix)
                            ),
                        ]
                    ),
                    limit=page_size,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
            except Exception as error:
                raise _as_ingestion_error(error, "Qdrant scroll failed") from error

            if not points:
                return
            # `MatchText` is a full-text match over word tokens, not a prefix
            # match: `app/auth` tokenizes to {app, auth} and matches any path
            # containing both as whole words -- `vendor/app/auth/nested.py` does,
            # and is not in this module. (`vendor/app/authz.py` does NOT: the
            # tokenizer does not split `authz` into `auth`.) Narrowed to a real
            # prefix here rather than dropping the server-side condition, which is
            # what keeps the payload index in play.
            page = [
                dict(point.payload or {})
                for point in points
                if str((point.payload or {}).get("file_path", "")).startswith(path_prefix)
            ]
            if page:
                yield page
            if offset is None:
                return

    async def _verify_width(self, dimensions: int) -> None:
        """Refuse to write into a collection created at a different vector width.

        Terminal, not retryable: the collection's size is fixed at creation, so no
        number of attempts changes the answer. Either the collection is dropped and
        rebuilt, or the provider goes back to the model this collection was built for.
        """
        info = await self._client.get_collection(self.collection)
        params = info.config.params.vectors
        existing = params.size if isinstance(params, models.VectorParams) else None
        if existing is not None and existing != dimensions:
            raise TerminalIngestionError(
                f"collection {self.collection} was created with vectors of width "
                f"{existing}, but this worker embeds at {dimensions}; the collection "
                f"must be dropped and rebuilt, or the embedding model changed back"
            )

    async def upsert(
        self,
        *,
        project_id: uuid.UUID,
        generation: int,
        chunks: list[Chunk],
        vectors: list[list[float]],
        commit_sha: str,
    ) -> None:
        """Write one batch of chunks under `generation`."""
        points = [
            models.PointStruct(
                id=point_id(project_id, chunk.file_path, chunk.chunk_index, generation),
                vector=vector,
                payload=_payload(
                    project_id=project_id,
                    generation=generation,
                    chunk=chunk,
                    commit_sha=commit_sha,
                ),
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        try:
            await self._client.upsert(collection_name=self.collection, points=points, wait=True)
        except Exception as error:
            raise _as_ingestion_error(error, "Qdrant upsert failed") from error

    async def _delete_where(self, conditions: list[models.FieldCondition]) -> None:
        """Delete every point matching all conditions."""
        try:
            await self._client.delete(
                collection_name=self.collection,
                points_selector=models.FilterSelector(filter=models.Filter(must=list(conditions))),
                wait=True,
            )
        except Exception as error:
            raise _as_ingestion_error(error, "Qdrant delete failed") from error

    async def delete_generation(self, *, project_id: uuid.UUID, generation: int) -> None:
        """Drop the superseded generation once the new one is fully written."""
        await self._delete_where(
            [
                models.FieldCondition(
                    key="project_id", match=models.MatchValue(value=str(project_id))
                ),
                models.FieldCondition(key="generation", match=models.MatchValue(value=generation)),
            ]
        )

    async def delete_project(self, project_id: uuid.UUID) -> None:
        """Hard-delete every point for a project (`docs/PRD.md` §5.1)."""
        await self._delete_where(
            [
                models.FieldCondition(
                    key="project_id", match=models.MatchValue(value=str(project_id))
                )
            ]
        )


class InMemoryVectorStore:
    """Test double. `points` is a list of `{"id": ..., "vector": ..., "payload": ...}`.

    Dedup is on the point id alone, because that is what Qdrant does. A fake keyed on
    `(id, generation)` would hide the data loss that an id without the generation in it
    causes in the real store.
    """

    def __init__(self, *, dimensions: int = 8) -> None:
        self.dimensions = dimensions
        self.collection = "in-memory"
        self.points: list[dict[str, Any]] = []
        self.ensured = False

    async def ensure_collection(self) -> None:
        """Record that the caller asked."""
        self.ensured = True

    async def search(
        self,
        *,
        project_id: uuid.UUID,
        generation: int,
        vector: list[float],
        limit: int,
    ) -> list[SearchHit]:
        """Cosine similarity over the stored points, same filters as the real store.

        Cosine specifically, because that is the distance the real collection is
        created with (`models.Distance.COSINE`). A fake ranking by dot product would
        order differently for vectors of differing magnitude, and retrieval tests
        would then pass here and fail against Qdrant.
        """
        matches = [
            point
            for point in self.points
            if point["payload"]["project_id"] == str(project_id)
            and point["payload"]["generation"] == generation
        ]
        scored = [
            SearchHit(payload=dict(point["payload"]), score=_cosine(vector, point["vector"]))
            for point in matches
        ]
        scored.sort(key=lambda hit: hit.score, reverse=True)
        return scored[:limit]

    async def scroll(
        self,
        *,
        project_id: uuid.UUID,
        generation: int,
        path_prefix: str,
        page_size: int,
    ) -> AsyncIterator[list[dict[str, Any]]]:
        """Same filters as the real store, paged the same way.

        Sorted by `(file_path, chunk_index)` so a test's page boundaries are stable.
        Qdrant's own scroll order is by point id and is not sorted this way -- the
        generator re-groups and re-sorts regardless (spec 4.3), so nothing depends on
        the order matching.
        """
        matches = sorted(
            (
                dict(point["payload"])
                for point in self.points
                if point["payload"]["project_id"] == str(project_id)
                and point["payload"]["generation"] == generation
                and str(point["payload"]["file_path"]).startswith(path_prefix)
            ),
            key=lambda payload: (payload["file_path"], payload["chunk_index"]),
        )
        for start in range(0, len(matches), page_size):
            yield matches[start : start + page_size]

    async def upsert(
        self,
        *,
        project_id: uuid.UUID,
        generation: int,
        chunks: list[Chunk],
        vectors: list[list[float]],
        commit_sha: str,
    ) -> None:
        """Append points, replacing any with the same id."""
        for chunk, vector in zip(chunks, vectors, strict=True):
            identifier = point_id(project_id, chunk.file_path, chunk.chunk_index, generation)
            payload = _payload(
                project_id=project_id, generation=generation, chunk=chunk, commit_sha=commit_sha
            )
            self.points = [point for point in self.points if point["id"] != identifier]
            self.points.append({"id": identifier, "vector": vector, "payload": payload})

    async def delete_generation(self, *, project_id: uuid.UUID, generation: int) -> None:
        """Drop one generation for one project."""
        self.points = [
            point
            for point in self.points
            if not (
                point["payload"]["project_id"] == str(project_id)
                and point["payload"]["generation"] == generation
            )
        ]

    async def delete_project(self, project_id: uuid.UUID) -> None:
        """Drop every generation for one project."""
        self.points = [
            point for point in self.points if point["payload"]["project_id"] != str(project_id)
        ]


VectorStoreFactory = Callable[[str], VectorStore]
"""Collection name in, a store for that collection out.

A factory rather than one pre-built store, because the only honest source of a
collection's vector width is the startup probe, and a request handler has none to
offer. Both the delete path and the query path target the collection the project
itself recorded, which is not known until its row is loaded.
"""


def build_store_factory(settings: Settings) -> VectorStoreFactory:
    """Reach whichever collection a project recorded its points in.

    No store is constructed here, deliberately: an unindexed project costs no Qdrant
    client at all, and a project indexed before a provider switch legitimately lives
    in a collection that current settings would not name.
    """

    def store_for(collection: str) -> VectorStore:
        return QdrantVectorStore(url=settings.qdrant_url, collection=collection)

    return store_for

"""Collection naming, point identity, and payload contents."""

import uuid

from app.ingestion.chunker import Chunk
from app.ingestion.vector_store import InMemoryVectorStore, collection_name, point_id


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

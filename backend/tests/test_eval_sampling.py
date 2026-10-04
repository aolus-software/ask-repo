"""Deterministic sampling: the same set id always yields the same pairs."""

import uuid

from app.eval.sampling import assign_types, names_its_file, sample_chunks
from app.models.eval import EvalMix, EvalQuestionType


def _payload(
    path: str, index: int, *, symbol: str | None = None, size: int = 10
) -> dict[str, object]:
    return {
        "file_path": path,
        "start_line": index * 10 + 1,
        "end_line": index * 10 + 9,
        "symbol": symbol,
        "chunk_index": index,
        "content": "x" * size,
    }


PAYLOADS = [
    _payload("a.py", 0),
    _payload("a.py", 1, symbol="login", size=5),
    _payload("b.py", 0, size=50),
    _payload("b.py", 1, size=20),
    _payload("c.py", 0),
]


def test_the_same_seed_samples_the_same_chunks() -> None:
    seed = uuid.uuid4()
    assert sample_chunks(PAYLOADS, count=3, seed=seed) == sample_chunks(
        PAYLOADS, count=3, seed=seed
    )


def test_one_chunk_per_file_before_any_file_repeats() -> None:
    chunks = sample_chunks(PAYLOADS, count=3, seed=uuid.uuid4())
    assert sorted(c.file_path for c in chunks) == ["a.py", "b.py", "c.py"]


def test_a_symbol_is_preferred_then_the_longest_chunk() -> None:
    by_file = {c.file_path: c for c in sample_chunks(PAYLOADS, count=3, seed=uuid.uuid4())}
    assert by_file["a.py"].symbol == "login"
    assert by_file["b.py"].start_line == 1  # the 50-char chunk


def test_fewer_files_than_count_wraps_to_a_second_chunk() -> None:
    chunks = sample_chunks(PAYLOADS, count=5, seed=uuid.uuid4())
    assert len(chunks) == 5
    assert len({(c.file_path, c.start_line) for c in chunks}) == 5


def test_count_is_capped_by_distinct_chunks() -> None:
    assert len(sample_chunks(PAYLOADS, count=50, seed=uuid.uuid4())) == len(PAYLOADS)


def test_balanced_alternates_starting_with_explain() -> None:
    assert assign_types(4, EvalMix.BALANCED) == [
        EvalQuestionType.EXPLAIN,
        EvalQuestionType.LOCATE,
        EvalQuestionType.EXPLAIN,
        EvalQuestionType.LOCATE,
    ]
    assert set(assign_types(3, EvalMix.LOCATE)) == {EvalQuestionType.LOCATE}


def test_a_question_naming_its_file_is_detected() -> None:
    assert names_its_file("Where is login handled in app/auth/login.py?", "app/auth/login.py")
    assert names_its_file("What does login.py do?", "app/auth/login.py")
    assert not names_its_file("Where is a wrong password refused?", "app/auth/login.py")

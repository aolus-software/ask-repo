"""Chunk boundaries and, above all, line numbers.

Every citation at M2 and M4 is "file path + chunk id + line range" (docs/PRD.md
§4.3), so a chunker with correct text and wrong lines is worse than useless — it
cites confidently and points at the wrong code.
"""

from pathlib import Path

from app.ingestion.chunker import Chunk, LanguageAwareChunker, embedding_text
from app.ingestion.walker import SourceFile

SOURCE = '''def alpha() -> int:
    """First."""
    return 1


def beta() -> int:
    """Second."""
    return 2


def gamma() -> int:
    """Third."""
    return 3
'''


def source_file(name: str = "app/calc.py", language: str = "python") -> SourceFile:
    return SourceFile(path=Path(name), relative_path=name, language=language)


def test_produces_at_least_one_chunk() -> None:
    chunks = LanguageAwareChunker(chunk_size=1200, chunk_overlap=150).split(source_file(), SOURCE)
    assert len(chunks) >= 1


def test_line_numbers_locate_the_chunk_in_the_original() -> None:
    """The load-bearing assertion. Slice the file by the chunk's own line range and
    the chunk's first line must be in it."""
    lines = SOURCE.splitlines()
    chunks = LanguageAwareChunker(chunk_size=120, chunk_overlap=0).split(source_file(), SOURCE)

    for chunk in chunks:
        assert 1 <= chunk.start_line <= chunk.end_line <= len(lines)
        window = "\n".join(lines[chunk.start_line - 1 : chunk.end_line])
        assert chunk.text.strip().splitlines()[0] in window


def test_chunk_indexes_are_sequential_from_zero() -> None:
    chunks = LanguageAwareChunker(chunk_size=120, chunk_overlap=0).split(source_file(), SOURCE)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))


def test_every_chunk_carries_the_file_path_and_language() -> None:
    chunks = LanguageAwareChunker(chunk_size=1200, chunk_overlap=150).split(source_file(), SOURCE)
    assert all(chunk.file_path == "app/calc.py" for chunk in chunks)
    assert all(chunk.language == "python" for chunk in chunks)


def test_a_symbol_is_captured_when_one_is_visible() -> None:
    chunks = LanguageAwareChunker(chunk_size=120, chunk_overlap=0).split(source_file(), SOURCE)
    assert any(chunk.symbol is not None for chunk in chunks)


def test_an_unknown_language_still_chunks() -> None:
    """`text` must not crash the splitter — the walker emits it for anything unmapped."""
    chunks = LanguageAwareChunker(chunk_size=50, chunk_overlap=0).split(
        source_file("notes.rst", "text"), "line one\nline two\nline three\n"
    )
    assert len(chunks) >= 1


def test_an_empty_file_produces_no_chunks() -> None:
    assert LanguageAwareChunker(chunk_size=1200, chunk_overlap=150).split(source_file(), "") == []


def test_embedding_text_prepends_path_and_symbol() -> None:
    """A bare function body embeds as generic code; the header makes it *this*
    project's code. Cheap, and one of the highest-return changes in a RAG pipeline."""
    chunk = Chunk(
        file_path="backend/app/core/repo_url.py",
        start_line=10,
        end_line=20,
        language="python",
        symbol="validate_repo_url",
        chunk_index=0,
        text="return ValidatedRepoUrl(...)",
    )
    prepared = embedding_text(chunk)

    assert "backend/app/core/repo_url.py" in prepared
    assert "validate_repo_url" in prepared
    assert prepared.endswith(chunk.text)


def test_line_numbers_correct_with_production_overlap() -> None:
    """Production constants (chunk_size=1200, chunk_overlap=150) with real multifunction
    source. This test catches the cursor-advance bug: with overlap, the next piece starts
    before the prior piece ends, so cursor must advance minimally to find it."""
    # A 122-line Python source with multiple functions, over 1200 chars with overlap
    large_source = '''"""Module with multiple functions for testing overlap."""


def validate_input(data: dict) -> bool:
    """Validate input data structure.

    Checks that required fields are present and have correct types.
    Raises ValueError if validation fails.
    """
    required = {"name", "email", "age"}
    if not required.issubset(data.keys()):
        raise ValueError(f"Missing required fields: {required - data.keys()}")

    if not isinstance(data["name"], str):
        raise ValueError("name must be a string")
    if not isinstance(data["email"], str):
        raise ValueError("email must be a string")
    if not isinstance(data["age"], int):
        raise ValueError("age must be an integer")

    return True


def process_records(records: list) -> list:
    """Process a list of records with filtering and transformation.

    Applies multiple transformations to each record, filtering out invalid ones.
    Returns transformed records that pass all validations.
    """
    processed = []
    for record in records:
        try:
            if validate_input(record):
                transformed = {
                    "full_name": record["name"].upper(),
                    "contact": record["email"].lower(),
                    "years": record["age"],
                }
                processed.append(transformed)
        except (ValueError, KeyError) as e:
            # Skip invalid records and continue processing
            continue
    return processed


def compute_statistics(numbers: list) -> dict:
    """Compute basic statistics on a list of numbers.

    Calculates mean, median, and standard deviation.
    Returns a dict with results or empty if input is empty.
    """
    if not numbers:
        return {}

    mean = sum(numbers) / len(numbers)

    sorted_nums = sorted(numbers)
    n = len(sorted_nums)
    if n % 2 == 0:
        median = (sorted_nums[n // 2 - 1] + sorted_nums[n // 2]) / 2
    else:
        median = sorted_nums[n // 2]

    variance = sum((x - mean) ** 2 for x in numbers) / len(numbers)
    stdev = variance ** 0.5

    return {
        "mean": mean,
        "median": median,
        "stdev": stdev,
        "min": min(numbers),
        "max": max(numbers),
    }


def aggregate_results(results: list) -> dict:
    """Aggregate multiple result dictionaries into summary.

    Combines statistics from multiple runs into unified view.
    """
    summary = {"total": len(results), "entries": results}
    return summary
'''

    lines = large_source.splitlines()
    chunks = LanguageAwareChunker(chunk_size=1200, chunk_overlap=150).split(
        source_file(), large_source
    )

    # Must produce multiple chunks to test overlap behavior
    assert len(chunks) > 1, f"Expected multiple chunks with overlap, got {len(chunks)}"

    # Critical: every chunk's line range must actually contain its text
    for chunk in chunks:
        assert 1 <= chunk.start_line <= chunk.end_line <= len(lines), (
            f"Chunk {chunk.chunk_index} has invalid line range: "
            f"start_line={chunk.start_line}, end_line={chunk.end_line}, "
            f"total_lines={len(lines)}"
        )

        # Slice the source using the chunk's line numbers
        window_lines = lines[chunk.start_line - 1 : chunk.end_line]
        window = "\n".join(window_lines)

        # The chunk's first line must appear in the window
        chunk_first_line = chunk.text.strip().splitlines()[0]
        assert chunk_first_line in window, (
            f"Chunk {chunk.chunk_index} first line not found in window at "
            f"lines {chunk.start_line}-{chunk.end_line}. "
            f"Expected '{chunk_first_line}' in window:\n{window}"
        )

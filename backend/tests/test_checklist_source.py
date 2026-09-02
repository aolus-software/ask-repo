"""Turning scrolled chunks back into files the generator can read."""

from typing import Any

from app.checklist.source import rebuild_files, trim_overlap


def _payload(
    *,
    file_path: str,
    chunk_index: int,
    text: str,
    start_line: int = 1,
    end_line: int = 10,
) -> dict[str, Any]:
    return {
        "project_id": "p",
        "generation": 1,
        "file_path": file_path,
        "start_line": start_line,
        "end_line": end_line,
        "language": "python",
        "symbol": None,
        "chunk_index": chunk_index,
        "commit_sha": "abc",
        "content": text,
    }


def test_chunks_are_grouped_by_file_and_ordered_by_index() -> None:
    source = rebuild_files(
        [
            _payload(file_path="b.py", chunk_index=0, text="B0"),
            _payload(file_path="a.py", chunk_index=1, text="A1"),
            _payload(file_path="a.py", chunk_index=0, text="A0"),
        ],
        chunk_overlap=0,
    )

    assert [file.path for file in source.files] == ["a.py", "b.py"]
    assert source.files[0].text == "A0A1"


def test_the_overlap_seam_is_trimmed_once() -> None:
    """Chunks overlap by `chunk_overlap` characters. Naive concatenation duplicates
    the seam, and duplicated lines read to the model as a genuine duplication in the
    source -- which has produced test cases about it (spec 4.3)."""
    first = "def login(user):\n    check(user)\n"
    second = "    check(user)\n    return token(user)\n"

    source = rebuild_files(
        [
            _payload(file_path="a.py", chunk_index=0, text=first),
            _payload(file_path="a.py", chunk_index=1, text=second),
        ],
        chunk_overlap=64,
    )

    assert source.files[0].text.count("check(user)") == 1
    assert source.files[0].text.endswith("return token(user)\n")


def test_trim_overlap_leaves_unrelated_chunks_alone() -> None:
    assert trim_overlap("alpha", "beta", chunk_overlap=64) == "beta"


def test_a_missing_chunk_is_reported_not_stitched() -> None:
    """A file with a hole in it, where nothing says so, is the failure mode spec 4.6
    is about. The summary names which files were partial."""
    source = rebuild_files(
        [
            _payload(file_path="a.py", chunk_index=0, text="A0"),
            _payload(file_path="a.py", chunk_index=2, text="A2"),
        ],
        chunk_overlap=0,
    )

    assert source.partial_paths == ["a.py"]
    assert source.files[0].partial is True
    # The content that arrived is still used: a partial file is better evidence than
    # no file, as long as the partiality is reported.
    assert source.files[0].text == "A0A2"


def test_line_range_spans_the_whole_file() -> None:
    source = rebuild_files(
        [
            _payload(file_path="a.py", chunk_index=0, text="A0", start_line=1, end_line=20),
            _payload(file_path="a.py", chunk_index=1, text="A1", start_line=18, end_line=40),
        ],
        chunk_overlap=0,
    )

    assert (source.files[0].start_line, source.files[0].end_line) == (1, 40)

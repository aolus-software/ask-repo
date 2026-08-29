"""What gets indexed and what does not.

A fresh clone has already applied .gitignore — ignored files were never committed.
The filter that matters is about binaries, size, and committed-but-worthless paths.
"""

from pathlib import Path
from unittest.mock import patch

from app.ingestion.walker import detect_language, walk


def write(root: Path, relative: str, content: bytes | str) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        target.write_bytes(content)
    else:
        target.write_text(content)


def test_finds_source_files(tmp_path: Path) -> None:
    write(tmp_path, "app/main.py", "print('x')\n")
    write(tmp_path, "web/index.ts", "export const x = 1;\n")

    found = {file.relative_path for file in walk(tmp_path, max_file_bytes=1_000_000)}
    assert found == {"app/main.py", "web/index.ts"}


def test_skips_binaries_by_content_not_extension(tmp_path: Path) -> None:
    """A null byte in the first few KB is the signal; extensions lie."""
    write(tmp_path, "logo.png", b"\x89PNG\r\n\x1a\n\x00\x00binary")
    write(tmp_path, "weird.py", b"\x00\x01\x02 not really python")
    write(tmp_path, "real.py", "x = 1\n")

    found = {file.relative_path for file in walk(tmp_path, max_file_bytes=1_000_000)}
    assert found == {"real.py"}


def test_skips_the_git_directory(tmp_path: Path) -> None:
    write(tmp_path, ".git/config", "[core]\n")
    write(tmp_path, "main.py", "x = 1\n")

    found = {file.relative_path for file in walk(tmp_path, max_file_bytes=1_000_000)}
    assert found == {"main.py"}


def test_skips_denylisted_paths(tmp_path: Path) -> None:
    """Committed, textual, and worthless to index."""
    write(tmp_path, "package-lock.json", '{"lockfileVersion": 3}\n')
    write(tmp_path, "static/app.min.js", "var a=1;\n")
    write(tmp_path, "node_modules/left-pad/index.js", "module.exports = 1;\n")
    write(tmp_path, "vendor/thing/lib.go", "package thing\n")
    write(tmp_path, "src/app.js", "const a = 1;\n")

    found = {file.relative_path for file in walk(tmp_path, max_file_bytes=1_000_000)}
    assert found == {"src/app.js"}


def test_skips_files_over_the_cap(tmp_path: Path) -> None:
    """One generated schema must not consume the whole indexing budget."""
    write(tmp_path, "huge.py", "x = 1\n" * 200_000)
    write(tmp_path, "small.py", "x = 1\n")

    found = {file.relative_path for file in walk(tmp_path, max_file_bytes=1_000)}
    assert found == {"small.py"}


def test_respects_a_gitignore_for_committed_files(tmp_path: Path) -> None:
    """The edge case: committed before the rule was added."""
    write(tmp_path, ".gitignore", "generated/\n")
    write(tmp_path, "generated/schema.py", "x = 1\n")
    write(tmp_path, "app.py", "x = 1\n")

    found = {file.relative_path for file in walk(tmp_path, max_file_bytes=1_000_000)}
    assert found == {"app.py", ".gitignore"}


def test_detects_language_from_extension() -> None:
    assert detect_language(Path("a/b.py")) == "python"
    assert detect_language(Path("a/b.ts")) == "typescript"
    assert detect_language(Path("a/b.unknownext")) == "text"


def test_handles_non_utf8_gitignore(tmp_path: Path) -> None:
    """A .gitignore that is not valid UTF-8 does not abort the walk.

    Regression test for: _load_gitignore raised UnicodeDecodeError when .gitignore
    was not UTF-8, aborting the entire project's indexing.
    """
    # Write a .gitignore with latin-1 encoding (not UTF-8)
    gitignore_path = tmp_path / ".gitignore"
    gitignore_path.write_bytes(b"generated/\n\xf1\n")  # \xf1 is invalid UTF-8

    write(tmp_path, "app.py", "x = 1\n")
    write(tmp_path, "generated/schema.py", "y = 2\n")

    # Should not raise; should yield at least app.py
    found = {file.relative_path for file in walk(tmp_path, max_file_bytes=1_000_000)}
    assert "app.py" in found


def test_skips_files_removed_mid_walk(tmp_path: Path) -> None:
    """A file removed between is_file() check and stat() does not abort the walk.

    Regression test for: walk() raised FileNotFoundError when a file was deleted
    mid-walk (between is_file() check and path.stat() call), aborting indexing.
    """
    write(tmp_path, "app.py", "x = 1\n")
    write(tmp_path, "removable.py", "y = 2\n")
    write(tmp_path, "kept.py", "z = 3\n")

    removable_path = tmp_path / "removable.py"
    stat_calls: dict[str, int] = {}

    # Patch Path.stat to raise FileNotFoundError on the size-check stat() call
    # Path.stat calls: is_file() [1], is_symlink()->lstat() [2], size check [3]
    original_stat = Path.stat

    def patched_stat(self: Path, *, follow_symlinks: bool = True) -> object:
        path_key = str(self)
        call_count = stat_calls.get(path_key, 0) + 1
        stat_calls[path_key] = call_count

        if self == removable_path and call_count > 2:
            raise FileNotFoundError(f"File disappeared: {self}")
        return original_stat(self, follow_symlinks=follow_symlinks)

    with patch.object(Path, "stat", patched_stat):
        # Should not raise; should yield app.py and kept.py (removable.py skipped)
        found = {file.relative_path for file in walk(tmp_path, max_file_bytes=1_000_000)}
        assert "app.py" in found
        assert "kept.py" in found
        assert "removable.py" not in found

"""What gets indexed and what does not.

A fresh clone has already applied .gitignore — ignored files were never committed.
The filter that matters is about binaries, size, and committed-but-worthless paths.
"""

from pathlib import Path

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

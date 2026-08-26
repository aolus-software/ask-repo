"""Deciding which files in a clone are worth indexing.

`docs/PRD.md` §4.1 says "walk → .gitignore-aware filter". Worth being precise: a
fresh clone has *already* applied .gitignore, because ignored files were never
committed. `.gitignore` is still read here, but only for the genuine edge case of
files committed before a rule was added. The filtering that does the real work is
binary detection, a size cap, and a denylist of committed-but-worthless paths.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pathspec

# Directories never worth walking into at all.
SKIP_DIRECTORIES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "vendor",
        "__pycache__",
        ".venv",
        "venv",
        "dist",
        "build",
    }
)

# Committed, textual, and worthless to a code question.
DENY_SUFFIXES = (".min.js", ".min.css", ".lock", ".map")
DENY_NAMES = frozenset(
    {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "uv.lock", "Cargo.lock"}
)

EXTENSION_LANGUAGES = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".swift": "swift",
    ".scala": "scala",
    ".sh": "bash",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".md": "markdown",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".toml": "toml",
}

BINARY_SNIFF_BYTES = 8192


@dataclass(frozen=True, slots=True)
class SourceFile:
    """A file cleared for chunking."""

    path: Path
    relative_path: str
    language: str


def detect_language(path: Path) -> str:
    """The chunker's language hint, from the extension. `text` when unknown."""
    return EXTENSION_LANGUAGES.get(path.suffix.lower(), "text")


def _is_binary(path: Path) -> bool:
    """Whether a file looks binary.

    Null-byte sniff rather than extension matching: an extension is a claim, and a
    `.py` full of null bytes would otherwise be fed to the embedder as text.
    """
    try:
        return b"\x00" in path.open("rb").read(BINARY_SNIFF_BYTES)
    except OSError:
        return True


def _load_gitignore(root: Path) -> pathspec.PathSpec | None:  # type: ignore[type-arg]  # pathspec stubs declare PathSpec as generic without parameters
    """The repository's own ignore rules, if it has any."""
    gitignore = root / ".gitignore"
    if not gitignore.is_file():
        return None
    return pathspec.PathSpec.from_lines("gitignore", gitignore.read_text().splitlines())


def walk(root: Path, *, max_file_bytes: int) -> Iterator[SourceFile]:
    """Yield every file in `root` worth indexing."""
    spec = _load_gitignore(root)

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue

        relative = path.relative_to(root).as_posix()

        if any(part in SKIP_DIRECTORIES for part in path.relative_to(root).parts[:-1]):
            continue
        if path.name in DENY_NAMES or relative.endswith(DENY_SUFFIXES):
            continue
        if spec is not None and spec.match_file(relative):
            continue
        if path.stat().st_size > max_file_bytes:
            continue
        if _is_binary(path):
            continue

        yield SourceFile(path=path, relative_path=relative, language=detect_language(path))

"""Shaping a flat list of indexed file paths into something browsable.

Pure functions over a sorted tuple of repository-relative file paths, with no session,
no settings and no Qdrant client. That is deliberate: the path picker's behaviour on the
awkward cases -- a path that is a prefix of another but not a directory prefix of it, a
directory whose only content is nested deeper -- is exactly what a test should be able to
state directly, without a store to stand up first.

The design is `docs/superpowers/specs/2026-09-08-phase-1.1-module-path-picker-design.md`.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

SEPARATOR = "/"


@dataclass(frozen=True, slots=True)
class PathEntry:
    """One row in the picker: a directory to open, or a file to choose.

    `file_count` is the number of indexed files in a directory's whole subtree, not
    just its immediate children -- a directory holding one deeply nested file is worth
    opening, and a count of `0` beside it would say the opposite. It is `None` on a
    file, where the number would mean nothing.
    """

    name: str
    path: str
    is_directory: bool
    file_count: int | None


def covers(paths: Iterable[str], candidate: str) -> bool:
    """Whether `candidate` names an indexed file or a directory containing one.

    The prefix has to end at a separator. Without that, `backend/app/auth` would claim
    `backend/app/authz.py` and a module pointed at a path that does not exist would be
    accepted -- which is the whole failure phase 1.1 exists to close. `QdrantVectorStore.scroll`
    narrows its server-side `MatchText` condition for the same reason.

    An empty candidate is the repository root, and covers anything at all.
    """
    if not candidate:
        return any(True for _ in paths)
    prefix = candidate + SEPARATOR
    return any(path == candidate or path.startswith(prefix) for path in paths)


def _subtree_file_counts(paths: Sequence[str]) -> dict[str, int]:
    """How many indexed files sit under each directory, at any depth."""
    counts: dict[str, int] = {}
    for path in paths:
        segments = path.split(SEPARATOR)[:-1]
        walked = ""
        for segment in segments:
            walked = f"{walked}{SEPARATOR}{segment}" if walked else segment
            counts[walked] = counts.get(walked, 0) + 1
    return counts


def _ordered(entries: Iterable[PathEntry]) -> list[PathEntry]:
    """Directories before files, each alphabetically -- the order a file tree reads in."""
    return sorted(entries, key=lambda entry: (not entry.is_directory, entry.path))


def children_of(paths: Sequence[str], directory: str) -> list[PathEntry]:
    """The immediate children of one directory. `""` is the repository root.

    One level only, which is what makes the endpoint's per-directory shape honest: the
    client asks for what it is about to draw and nothing deeper.
    """
    prefix = f"{directory}{SEPARATOR}" if directory else ""
    counts = _subtree_file_counts(paths)
    directories: set[str] = set()
    files: list[PathEntry] = []
    for path in paths:
        if prefix and not path.startswith(prefix):
            continue
        remainder = path[len(prefix) :]
        if not remainder:
            continue
        head, separator, _ = remainder.partition(SEPARATOR)
        child = f"{prefix}{head}"
        if separator:
            directories.add(child)
        else:
            files.append(PathEntry(name=head, path=child, is_directory=False, file_count=None))
    return _ordered(
        [
            *(
                PathEntry(
                    name=child.rsplit(SEPARATOR, 1)[-1],
                    path=child,
                    is_directory=True,
                    file_count=counts.get(child, 0),
                )
                for child in directories
            ),
            *files,
        ]
    )


def matching(paths: Sequence[str], term: str, *, limit: int) -> tuple[list[PathEntry], bool]:
    """Every directory and file whose path contains `term`, capped at `limit`.

    Returns the entries and whether the cap cut anything off, because a picker that
    silently shows the first hundred of four hundred matches teaches the user that the
    thing they are looking for is not indexed.

    Case-insensitive substring matching over the whole path, not the name alone: a
    search for `routes/auth` should find `backend/app/api/routes/auth.py`, and typing a
    fragment of a path is how someone who half-remembers the tree looks for it.
    """
    needle = term.strip().lower()
    if not needle:
        return [], False
    counts = _subtree_file_counts(paths)
    hits = [
        *(
            PathEntry(
                name=directory.rsplit(SEPARATOR, 1)[-1],
                path=directory,
                is_directory=True,
                file_count=count,
            )
            for directory, count in counts.items()
            if needle in directory.lower()
        ),
        *(
            PathEntry(
                name=path.rsplit(SEPARATOR, 1)[-1], path=path, is_directory=False, file_count=None
            )
            for path in paths
            if needle in path.lower()
        ),
    ]
    ordered = _ordered(hits)
    return ordered[:limit], len(ordered) > limit

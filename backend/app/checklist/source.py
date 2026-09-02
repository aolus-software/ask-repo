"""Reconstructing a module's files out of the vector index.

`docs/PRD.md` 4.1 deletes the working copy after indexing, so there is no file on disk
to read. The payload holds the chunk text, which makes the index a reconstructable copy
of the source -- and that is what lets generation run with no re-clone, and therefore no
second PAT decrypt, no second URL-validation surface, and no second `scrub` obligation
(spec 2.2).
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ModuleFile:
    """One file, rebuilt from its chunks."""

    path: str
    language: str
    text: str
    start_line: int
    end_line: int
    # True when the chunk indexes were not contiguous. Reported to the model and to
    # the generation summary rather than silently stitched (spec 4.3).
    partial: bool


@dataclass(frozen=True, slots=True)
class ModuleSource:
    """Everything the generator has to read, plus what it could not read whole."""

    files: list[ModuleFile]
    partial_paths: list[str]


def trim_overlap(previous: str, current: str, *, chunk_overlap: int) -> str:
    """`current` with its leading duplicate of `previous`'s tail removed.

    The chunker overlaps adjacent chunks by `chunk_overlap` characters so a symbol
    spanning a boundary is embedded whole. Concatenating them back naively duplicates
    the seam, and a duplicated block reads to the model as real duplication in the
    source.

    The longest match is taken, and bounded by `chunk_overlap` so an ordinary repeated
    line elsewhere in the file cannot be mistaken for a seam.
    """
    limit = min(chunk_overlap, len(previous), len(current))
    for size in range(limit, 0, -1):
        if previous.endswith(current[:size]):
            return current[size:]
    return current


def _join(chunks: list[dict[str, Any]], *, chunk_overlap: int) -> str:
    """Concatenate one file's chunks, trimming each seam exactly once."""
    parts: list[str] = []
    for chunk in chunks:
        text = str(chunk.get("content", ""))
        parts.append(trim_overlap(parts[-1], text, chunk_overlap=chunk_overlap) if parts else text)
    return "".join(parts)


def _is_contiguous(indexes: Iterable[int]) -> bool:
    """Whether the chunk indexes run 0, 1, 2, ... with nothing missing."""
    ordered = sorted(indexes)
    return ordered == list(range(len(ordered)))


def rebuild_files(payloads: list[dict[str, Any]], *, chunk_overlap: int) -> ModuleSource:
    """Group scrolled payloads by file, order them, and rejoin their text.

    A file whose chunks are non-contiguous is marked `partial` and named in
    `partial_paths`. The content that did arrive is still used: partial evidence beats
    none, as long as the partiality is reported rather than hidden (spec 4.3, 4.6).
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for payload in payloads:
        grouped.setdefault(str(payload["file_path"]), []).append(payload)

    files: list[ModuleFile] = []
    partial_paths: list[str] = []
    for path in sorted(grouped):
        chunks = sorted(grouped[path], key=lambda chunk: int(chunk["chunk_index"]))
        partial = not _is_contiguous(int(chunk["chunk_index"]) for chunk in chunks)
        if partial:
            partial_paths.append(path)
            logger.warning("checklist source for %s is missing chunks; reporting it partial", path)
        files.append(
            ModuleFile(
                path=path,
                language=str(chunks[0].get("language") or "text"),
                text=_join(chunks, chunk_overlap=chunk_overlap),
                start_line=min(int(chunk["start_line"]) for chunk in chunks),
                end_line=max(int(chunk["end_line"]) for chunk in chunks),
                partial=partial,
            )
        )
    return ModuleSource(files=files, partial_paths=partial_paths)

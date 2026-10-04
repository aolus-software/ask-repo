"""Choosing which chunks a set's pairs are built from, deterministically.

Seeded by the set id, so regenerating nothing and re-reading the code gives the same
answer to "why this chunk". Pure: no I/O, so it is tested without a store.
"""

import random
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from app.models.eval import EvalMix, EvalQuestionType


@dataclass(frozen=True, slots=True)
class SampledChunk:
    """One chunk a pair will be generated from."""

    file_path: str
    start_line: int
    end_line: int
    symbol: str | None
    content: str


def _rank(payload: dict[str, Any]) -> tuple[int, int]:
    """Prefer a chunk with a symbol, then the longest."""
    return (0 if payload.get("symbol") else 1, -len(str(payload.get("content", ""))))


def sample_chunks(
    payloads: list[dict[str, Any]], *, count: int, seed: uuid.UUID
) -> list[SampledChunk]:
    """Up to `count` chunks: one per file in a seeded order, then a second round, and so on."""
    by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for payload in payloads:
        by_file[str(payload["file_path"])].append(payload)
    files = sorted(by_file)
    random.Random(seed.int).shuffle(files)
    queues = {path: sorted(by_file[path], key=_rank) for path in files}

    chosen: list[SampledChunk] = []
    while len(chosen) < count and any(queues.values()):
        for path in files:
            if len(chosen) == count:
                break
            if queues[path]:
                payload = queues[path].pop(0)
                chosen.append(
                    SampledChunk(
                        file_path=path,
                        start_line=int(payload["start_line"]),
                        end_line=int(payload["end_line"]),
                        symbol=payload.get("symbol") or None,
                        content=str(payload.get("content", "")),
                    )
                )
    return chosen


def assign_types(count: int, mix: EvalMix) -> list[EvalQuestionType]:
    """One type per pair. `balanced` alternates, starting with `explain`."""
    if mix is EvalMix.EXPLAIN:
        return [EvalQuestionType.EXPLAIN] * count
    if mix is EvalMix.LOCATE:
        return [EvalQuestionType.LOCATE] * count
    cycle = (EvalQuestionType.EXPLAIN, EvalQuestionType.LOCATE)
    return [cycle[index % 2] for index in range(count)]


def names_its_file(question: str, source_file: str) -> bool:
    """Whether a question gives away its own answer by naming the file."""
    lowered = question.lower()
    return source_file.lower() in lowered or PurePosixPath(source_file).name.lower() in lowered

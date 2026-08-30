"""Cheap checks on whether an answer stayed inside what was retrieved.

None of this makes the model honest. What it does is make dishonesty **visible**:
a claim about a file that was never retrieved, or an answer that cites nothing at
all, is recorded on the message and reported in the `done` event rather than
shipped silently as though it were grounded. A check whose result nothing can see
is not a check.

Deliberately limited to file paths. Symbols would need a lexicon of every
identifier in the repository to distinguish `validate_repo_url` from ordinary
prose, and a checker with false positives is a checker people learn to ignore.
"""

import re

from app.rag.retriever import RetrievedChunk

NO_CONTEXT = "no_context"
"""Nothing was retrieved above the relevance floor, so no answer was generated."""

UNCITED_ANSWER = "uncited_answer"
"""Excerpts were supplied and the model referenced none of their labels."""

UNKNOWN_PATHS = "unknown_paths"
"""The answer named a file that appears in no retrieved excerpt."""

WEAK_EVIDENCE = "weak_evidence"
"""Retrieval was graded insufficient and the attempt budget was spent.

Distinct from `NO_CONTEXT`, which means retrieval returned nothing above the
relevance floor and no answer was generated at all. This one means an answer *was*
generated, from excerpts a grader judged incomplete.
"""

NO_CONTEXT_ANSWER = (
    "I could not find code in this project that answers that question. Nothing in "
    "the index matched closely enough to answer from, and I will not guess. Try "
    "naming a file, a function, or a feature by the words used in the code, or "
    "check that the project finished indexing."
)
"""What the user sees when there is nothing to ground on.

Streamed as ordinary tokens rather than a distinct event type, so a client renders
a refusal exactly as it renders an answer. The machine-readable distinction is
`NO_CONTEXT` in `groundingWarnings`.
"""

OUT_OF_SCOPE_ANSWER = (
    "I only answer questions about the code in this project. Ask me about a file, a "
    "function, or how something in this repository works, and I will answer from the "
    "indexed code."
)
"""What the user sees for a question that is not about this repository.

Streamed as ordinary tokens rather than a distinct event type, following
`NO_CONTEXT_ANSWER`: a client renders a refusal exactly as it renders an answer, and
the machine-readable distinction rides in the `done` event's `intent`.
"""

# A path-shaped token: at least one directory separator, and a dotted extension.
# Both conditions are needed — without the separator this matches every sentence
# ending in a filename-like word, and without the extension it matches "3/4".
_PATH_PATTERN = re.compile(r"\b(?:[\w.-]+/)+[\w-]+\.[A-Za-z0-9]+\b")

# Removed before scanning. A URL is path-shaped by construction — a dotted host
# followed by slash-separated segments — so `https://github.com/acme/repo.git`
# matches `_PATH_PATTERN` as `github.com/acme/repo.git` and gets reported as a file
# that was never retrieved. Linking the repository or an issue is an ordinary thing
# for an answer to do, and this check is worth only as much as it is believed.
_URL_PATTERN = re.compile(r"\bhttps?://\S+", re.IGNORECASE)


def _same_file(candidate: str, retrieved: str) -> bool:
    """Whether two paths name the same file, allowing for a differing prefix.

    Chunks are stored repo-relative, but a model that has read the repository name
    in a path may write `backend/app/main.py` for what was retrieved as
    `app/main.py`. Flagging that as an invention would train the reader to ignore
    the warnings, which costs more than the miss.
    """
    return (
        candidate == retrieved
        or candidate.endswith(f"/{retrieved}")
        or retrieved.endswith(f"/{candidate}")
    )


def unknown_paths(answer: str, spans: list[RetrievedChunk]) -> list[str]:
    """File paths the answer names that appear in no retrieved excerpt.

    URLs are stripped first — see `_URL_PATTERN`. A scheme-less host
    (`github.com/acme/repo`) still matches and is still reported; that is the
    accepted limit, because a bare dotted-slash token is genuinely ambiguous
    between a host and a path.
    """
    retrieved = {span.file_path for span in spans}
    scannable = _URL_PATTERN.sub(" ", answer)
    return sorted(
        candidate
        for candidate in set(_PATH_PATTERN.findall(scannable))
        if not any(_same_file(candidate, path) for path in retrieved)
    )


def grounding_warnings(*, answer: str, spans: list[RetrievedChunk], cited_count: int) -> list[str]:
    """Machine-readable signals that this answer may not be grounded.

    An empty list is the normal case. `NO_CONTEXT` is returned alone: with nothing
    retrieved there is no point also reporting that nothing was cited — one cause,
    one warning.
    """
    if not spans:
        return [NO_CONTEXT]

    warnings: list[str] = []
    if answer.strip() and cited_count == 0:
        warnings.append(UNCITED_ANSWER)
    if unknown_paths(answer, spans):
        warnings.append(UNKNOWN_PATHS)
    return warnings

"""Post-hoc checks on whether an answer stayed inside what was retrieved."""

from app.rag.grounding import (
    NO_CONTEXT,
    UNCITED_ANSWER,
    UNKNOWN_PATHS,
    grounding_warnings,
    unknown_paths,
)
from tests.test_retriever import _span


def test_a_path_that_was_never_retrieved_is_reported() -> None:
    """The exact failure this product must not have. The model names
    `app/services/billing.py`, the reader opens it, and it does not exist — or
    worse, it exists and says something else entirely."""
    spans = [_span("app/core/repo_url.py", 0, 1, 10)]

    assert unknown_paths("See app/services/billing.py for details.", spans) == [
        "app/services/billing.py"
    ]


def test_a_retrieved_path_is_not_reported() -> None:
    spans = [_span("app/core/repo_url.py", 0, 1, 10)]

    assert unknown_paths("Validation lives in app/core/repo_url.py.", spans) == []


def test_a_path_written_with_a_longer_prefix_still_matches() -> None:
    """Chunks are stored repo-relative, but a model reading the repo name in a
    path may write `backend/app/main.py` for what was retrieved as
    `app/main.py`. Flagging that would train the reader to ignore the warnings."""
    spans = [_span("app/main.py", 0, 1, 10)]

    assert unknown_paths("It is wired in backend/app/main.py.", spans) == []


def test_prose_is_not_mistaken_for_a_path() -> None:
    """A checker with false positives is a checker people switch off."""
    spans = [_span("app/main.py", 0, 1, 10)]

    assert unknown_paths("The ratio is 3/4 and the rate is 10/s.", spans) == []


def test_no_spans_is_the_only_warning_reported() -> None:
    """With nothing retrieved there is no point also reporting that nothing was
    cited — one cause, one warning."""
    assert grounding_warnings(answer="anything", spans=[], cited_count=0) == [NO_CONTEXT]


def test_an_answer_that_cites_nothing_is_flagged() -> None:
    """Spans were supplied and the model used none of their labels. Either it
    ignored the evidence or it answered from memory; both are worth recording."""
    spans = [_span("app/main.py", 0, 1, 10)]

    assert UNCITED_ANSWER in grounding_warnings(
        answer="It works by magic.", spans=spans, cited_count=0
    )


def test_a_cited_answer_naming_only_retrieved_paths_is_clean() -> None:
    spans = [_span("app/main.py", 0, 1, 10)]

    assert grounding_warnings(answer="See [1] in app/main.py.", spans=spans, cited_count=1) == []


def test_an_invented_path_is_flagged_even_when_the_answer_cites() -> None:
    """Citing `[1]` correctly and then naming a second, invented file is the most
    plausible-looking failure of all."""
    spans = [_span("app/main.py", 0, 1, 10)]

    assert UNKNOWN_PATHS in grounding_warnings(
        answer="See [1] in app/main.py, which calls app/nope/gone.py.",
        spans=spans,
        cited_count=1,
    )


def test_a_linked_url_is_not_reported_as_an_invented_file() -> None:
    """A URL is path-shaped by construction — a dotted host, then slash-separated
    segments — so `https://github.com/acme/repo.git` would otherwise be reported as
    a file that was never retrieved. Linking the repository or an issue is an
    ordinary thing for an answer to do, and a check that fires on ordinary answers
    stops being read."""
    spans = [_span("app/main.py", 0, 1, 10)]

    assert unknown_paths("Cloned from https://github.com/acme/repo.git by [1].", spans) == []


def test_a_url_does_not_mask_a_real_invention_beside_it() -> None:
    """Stripping URLs must not swallow the rest of the sentence."""
    spans = [_span("app/main.py", 0, 1, 10)]

    assert unknown_paths(
        "See https://example.com/docs and also app/services/billing.py.", spans
    ) == ["app/services/billing.py"]


def test_weak_evidence_is_a_distinct_warning_from_no_context() -> None:
    """They mean different things: `no_context` is "retrieval found nothing above the
    floor", `weak_evidence` is "it found something and the grader judged it short"."""
    from app.rag.grounding import NO_CONTEXT, WEAK_EVIDENCE

    assert WEAK_EVIDENCE == "weak_evidence"
    assert WEAK_EVIDENCE != NO_CONTEXT


def test_the_out_of_scope_refusal_says_what_to_ask_instead() -> None:
    """A refusal that does not redirect reads as a failure rather than a boundary."""
    from app.rag.grounding import OUT_OF_SCOPE_ANSWER

    assert OUT_OF_SCOPE_ANSWER.strip()
    assert "project" in OUT_OF_SCOPE_ANSWER.lower()

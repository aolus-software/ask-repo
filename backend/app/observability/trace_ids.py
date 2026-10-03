"""Deterministic Langfuse trace ids, derived from our own ids.

A chat turn's trace is seeded with its assistant message id and a generation run's with
its change set id, so a feedback row can link to its trace without storing a trace id
anywhere. The derivation must equal the SDK's `create_trace_id(seed=...)`, and
`tests/test_trace_ids.py` pins that.
"""

import hashlib


def trace_id_for(seed: str) -> str:
    """The Langfuse trace id for `seed`: 32 lowercase hex characters."""
    return hashlib.sha256(seed.encode("utf-8")).digest()[:16].hex()


def trace_url(*, ui_url: str, project_id: str, seed: str) -> str:
    """A browser link to the trace seeded by `seed`."""
    return f"{ui_url.rstrip('/')}/project/{project_id}/traces/{trace_id_for(seed)}"

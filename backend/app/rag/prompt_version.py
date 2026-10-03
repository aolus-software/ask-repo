"""A version stamp for the prompts, derived rather than maintained.

Every prompt in the application lives in `app/rag/prompts.py`. Hashing its
upper-case string constants means any edit changes the version and nobody has to
remember to bump it — which is what lets feedback (and Phase 2.6's eval harness)
compare "before this prompt change" against "after".

This module imports nothing from feedback, and must not: nothing feedback-authored
reaches a model (`.claude/rules/feedback.md`).
"""

import hashlib
from types import ModuleType

from app.rag import prompts


def compute_prompt_version(module: ModuleType) -> str:
    """The first 12 hex characters of a SHA-256 over `module`'s prompt constants."""
    parts = [
        f"{name}={value}"
        for name, value in sorted(vars(module).items())
        if name.isupper() and not name.startswith("_") and isinstance(value, str)
    ]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:12]


PROMPT_VERSION = compute_prompt_version(prompts)

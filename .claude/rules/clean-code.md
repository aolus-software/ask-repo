---
paths:
  - "backend/app/**/*.py"
  - "backend/tests/**/*.py"
---

# Clean Code Rules (Python)

The installed `clean-code` skill covers the general principles — naming, function size, single
responsibility, duplication. **This rule covers only what is Python- and AskRepo-specific.**
Where they overlap, the skill is the deeper reference; this file is the enforceable local
convention.

## Type hints

- **Every function and method has annotated parameters and an explicit return type**,
  including `-> None`. `ruff`'s `ANN` rules are the enforcement point.
- No bare `Any` on a public boundary — a route signature, a service method, or anything in
  `app/schemas/`. Inside a function body, inference is fine.
- Prefer modern syntax: `str | None`, `list[str]`, `dict[str, int]` — not `Optional[str]`,
  `List[str]`, `Dict[str, int]`.
- Use `Literal` for closed sets of strings (statuses, roles) rather than bare `str`. The
  `Status` alias in `app/api/routes/health.py` is the pattern.

## Docstrings and comments

- **Every public function, class, and module has a docstring** stating what it does — not how.
  One docstring per unit; do not annotate individual statements.
- Private helpers (`_leading_underscore`) need a docstring only when the logic is non-obvious.
- **No line-by-line commentary.** If a block needs explaining, a single comment above it is
  correct. If it needs a comment per line, extract a named function instead.
- Comments explain **why**, not what. `# add 1 to i` is noise; `# Qdrant rejects batches over
  256 points` is the reason a magic number exists.
- Do not leave commented-out code. Delete it — git remembers.

## Logging

- **Never `print()`.** Use the standard library `logging` module via a module-level
  `logger = logging.getLogger(__name__)`.
- Log at the right level: `debug` for tracing, `info` for lifecycle events, `warning` for
  recoverable oddities, `error` for failures with a stack trace via `exc_info=True`.
- **Never log a secret.** Passwords, tokens, PATs, and full `DATABASE_URL`s are excluded — see
  `docs/PRD.md` §9. This includes interpolating a whole request body or settings object into a
  log line.

## Errors

- Raise `HTTPException` (or a domain exception mapped by a handler) — never return an error
  dict from a route. See `response-api.md`.
- Never `except:` or `except Exception:` without re-raising or logging with `exc_info=True`. A
  swallowed exception is a bug that will be reported as "it just does nothing".
- No `try`/`except` wrapper around a whole route body for the sake of catching everything —
  FastAPI exception handlers do that once, globally. See `response-api.md`.

## General

- **No emojis or icons in code, comments, docstrings, or generated files.** They are fine in
  Markdown docs where they carry meaning, such as the severity tags in `audit-findings.md`.
- Module-level constants are `UPPER_SNAKE_CASE`; everything else is `snake_case`. Classes are
  `PascalCase`.
- No mutable default arguments (`def f(x: list = [])`). Use `None` and build inside.
- Keep files focused. A module doing two jobs is two modules; a file you cannot hold in your
  head is a file that will be edited wrongly.
- Imports at the top, grouped stdlib / third-party / first-party. `ruff`'s `I` rules enforce
  the ordering — fix at the lint step, never by suppressing the rule.

## Suppressions

`# noqa` and `# type: ignore` require a reason on the same line and are a last resort:

```python
value = legacy_api()  # type: ignore[no-any-return]  # upstream stub is untyped
```

A bare suppression with no explanation is treated as an unfixed lint failure.

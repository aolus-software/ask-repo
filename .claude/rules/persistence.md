---
paths:
  - "backend/app/models/**/*.py"
  - "backend/app/repositories/**/*.py"
  - "backend/app/db/**/*.py"
  - "backend/alembic/**/*.py"
---

# Persistence Rules

Three layers: route → service → repository. `router.md` owns the top; this file owns the bottom
two.

## Only repositories touch SQLAlchemy

`select`, `insert`, `update`, and `delete` are imported in `app/repositories/**` and nowhere
else. A service that builds a statement has moved a query somewhere nobody will look for it, and
puts it outside the reach of the soft-delete guarantee below.

Services own **business rules, transactions, and orchestration across repositories**. They call
repository methods and commit.

## The soft-delete filter is structural, not remembered

`docs/PRD.md:323` requires every read to exclude soft-deleted rows. `BaseRepository.active_select()`
applies `deleted_at IS NULL` for any model carrying `SoftDeleteMixin`. **Every read starts
there.**

A query that genuinely needs deleted rows uses a method whose name says so —
`get_including_deleted` — so the intent is visible at the call site and greppable. A
hand-written `select(Model)` inside a repository read is a defect even when its output is
currently correct.

`refresh_tokens` is the documented exception: it has no `deleted_at`, and its lifecycle is
`revoked_at` / `expires_at` (`docs/PRD.md` §5.1).

## Bulk updates must set `updated_at` themselves

`TimestampMixin.updated_at` uses SQLAlchemy's `onupdate`, which is a **Python-side** default: it
fires on an ORM flush and **not** on a bulk `UPDATE`. Any repository method issuing a bulk
update sets `updated_at` in the `values()` explicitly. Forgetting leaves rows whose
`updated_at` predates their last change, which is the kind of bug found months later while
debugging something else.

## `sort` is allowlisted, never interpolated

A list repository exposes `SORTABLE_FIELDS: frozenset[str]` and raises `ValueError` for anything
outside it. The route maps that to `400 INVALID_SORT_FIELD`. Passing a query parameter into
`getattr(Model, ...)` unchecked exposes every column, `password_hash` included.

## The engine is built lazily

`app/db/session.py` constructs the engine on first use from `get_settings()`, not at import
time. `AuthContextMiddleware` builds sessions from the sessionmaker directly rather than through
`Depends`, so an import-time engine would ignore a test's settings override and talk to the
development database. `reset_engine()` exists for tests and nothing else.

## Migrations, not `create_all`

Schema changes are Alembic revisions. `Base.metadata.create_all` is not used anywhere, including
in tests — the migrations are what runs in production, so they are what the suite exercises.

- `MetaData(naming_convention=...)` in `app/models/base.py` keeps constraint names deterministic;
  without it autogenerate churns and a migration cannot reliably drop a constraint it did not name.
- Write the revision by hand when autogenerate cannot express the intent. The partial unique index
  on `users.email` is the standing example.
- Every revision has a working `downgrade()`. A migration that cannot be reversed cannot be
  iterated on.

## Timestamps and IDs

`timestamptz`, timezone-aware, UTC (`docs/PRD.md:321`). Primary keys are application-generated
`uuid4` (`docs/PRD.md:322`) — never a database sequence, so an id in a URL reveals nothing about
volume or ordering.

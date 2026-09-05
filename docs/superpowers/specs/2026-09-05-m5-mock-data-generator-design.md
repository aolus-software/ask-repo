# M5 — QA Mock Data Generator: Design

**Status:** Approved design, not yet implemented.
**Date:** 2026-09-05

## 0. Why this document exists, and what it replaces

`docs/PRD.md` §4.4 originally specified M5 as a synthetic Q&A eval harness: generate
`(question, reference_answer, source_file)` triples from a codebase, run them back through
Dev Knowledge, and score the answers — a way to measure RAG quality when chunking, prompting,
or the chat model changes.

That feature is **deferred to phase 2**, not built. §4.4 and the M5 milestone entry now
describe a different feature: a QA **mock data** generator that produces sample data records
for a QA Checklist module's actual fields, so a reviewer has realistic values to fill that
feature's forms or seed it manually. `docs/PRD.md` §2.1's new "Synthetic Q&A eval harness"
bullet carries the original spec forward as a phase-2 item. See that section, and §4.4, for
the canonical product spec — this document is the *implementation* design for the feature that
now carries the M5 name.

## 1. Relationship to QA Checklist (M4)

The Mock Data Generator attaches to the **existing** `ChecklistModule` row — no rename, no
restructuring of M4's shipped tables, routes, services, or frontend. A module is scoped by
`name` + `source_path` (a repository-relative path), exactly as M4 defined it. Mock data is a
second, independent capability on that same scope:

- A module may have a checklist, a mock dataset, both, or neither.
- Generating, refining, applying, or exporting one has no effect on the other.
- Both reuse the "scroll the index, don't search it" grounding principle from M4, because the
  same reason applies: top-k retrieval cannot report what it left out, so both generators walk
  every chunk under `source_path` rather than searching for a handful of nearest neighbors.

This mirrors M4's shape closely enough that most of the new code is "the same pattern, applied
to a different content type" rather than new architecture:

| M4 (QA Checklist) | M5 (Mock Data Generator) |
| --- | --- |
| `checklist_items` | `mock_data_records` |
| `checklist_change_sets` | `mock_data_change_sets` |
| `app/checklist/` (generator, contracts, file rebuild) | `app/mockdata/` (generator, contracts) |
| `app/queue/checklist.py` | `app/queue/mock_data.py` |
| `app/services/checklist_module.py`, `checklist_item.py`, `checklist_change_set.py`, `checklist_export.py` | `app/services/mock_data_record.py`, `mock_data_change_set.py`, `mock_data_export.py` |
| Checklist chat, scoped to a module | Mock data chat, scoped to a module — same `Answerer`, different content |
| `POST /checklist-change-sets/{id}/apply` | `POST /mock-data-change-sets/{id}/apply` |
| `.xlsx` export | `.json` and `.xlsx` export |

## 2. Data model

**Correction found while drafting the implementation plan:** `ChecklistModule.status`
(`empty`/`generating`/`review`/`ready`/`failed`) plus its lease columns
(`lease_owner`/`lease_expires_at`/`last_job_id`) already carry the checklist capability's own
generation state machine. A module can independently have a checklist, a mock dataset, both,
or neither (§1), so mock data cannot write those same columns without corrupting whichever
capability didn't just run. It needs its **own** status/lease row — a third table, not two.

### `mock_data_datasets`

One row per module, created lazily on the first generation request. Mirrors
`ChecklistModule`'s own status/lease shape exactly (same lease semantics, same reasoning —
see `ChecklistModuleRepository`'s docstring on why that lease logic is a near-copy of
`ProjectRepository.claim` rather than a shared helper: different status vocabularies,
different outcome columns).

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `checklist_module_id` | UUID FK, **unique** | One dataset per module |
| `status` | enum: `empty`/`generating`/`review`/`ready`/`failed` | Independent of the module's own checklist status |
| `error` | text, nullable | Scrubbed, same as `ChecklistModule.error` |
| `indexed_generation` | int, nullable | The project generation the last run read, for the same staleness check §4.3 does for the checklist |
| `last_generated_at` | timestamptz, nullable | |
| `lease_owner` / `lease_expires_at` / `last_job_id` | same shapes as `ChecklistModule` | The dedup boundary for this dataset's generation, independent of the checklist's own lease |
| `created_at`, `updated_at` | timestamptz | |

### `mock_data_records`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `checklist_module_id` | UUID FK → `checklist_modules.id` | Scope; not a new "module" concept. Kept as a direct FK to the module (like `checklist_items.module_id`) rather than to `mock_data_datasets.id`, so a record survives even if the dataset row's lifecycle is ever reworked |
| `fields` | JSONB | Dynamic key → value map. Keys vary per module (whatever the schema in code defines); every record produced by one generation batch shares the same key set |
| `created_by` | UUID FK → users | Attribution only, per the repo-wide `created_by` rule — never a read filter |
| `created_at`, `updated_at` | timestamptz | |
| `deleted_at` | timestamptz, nullable | Soft delete, per repo convention. No Qdrant counterpart exists for this row — it never had one — so this is an ordinary soft delete, not the dual-store case ingestion has |

No `status` or `current_result` column. Unlike a checklist item, a mock data record is not a
claim about an observation — it is a sample value, full stop. That is also why the apply path
does not need to defend a column that would let generated content "claim" a human result: the
allowlist is simply `fields`.

### `mock_data_change_sets`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | Minted in `prepare_turn`, before generation runs or a byte streams — same reason M4's change-set id is minted early: the `changeSet` SSE event has to name a row that does not exist yet at emission time |
| `checklist_module_id` | UUID FK | |
| `status` | enum: `pending` / `applied` / `discarded` | |
| `changes` | JSONB | List of `{op: "add" \| "update" \| "remove", record_id?: UUID, fields?: {...}, rationale: str}` |
| `created_by` | UUID FK → users | |
| `applied_by` | UUID FK → users, nullable | |
| `created_at`, `applied_at` | timestamptz | |

**One pending change set per `(checklist_module_id)` for mock data**, independent of whatever
checklist change set may also be pending for the same module — they are different resources
with different uniqueness scopes. Concurrent refinement is out of scope for v1, matching M4.

## 3. Generation flow

1. `POST /checklist-modules/{id}/mock-data-generations` enqueues a job (Kafka, same queue
   infrastructure as M1/M4 — no new broker, no Redis-as-queue). Returns `202` with the pending
   change set's id (minted synchronously, before the job runs) so the client can open the SSE
   connection or poll immediately.
2. The worker claims the job through the same lease/claim discipline M4's checklist sweep
   uses: a fresh `job_id` on re-publish, `updated_at` stamped on claim, so a stranded run is
   recoverable without a duplicate mid-flight generation silently succeeding twice.
3. **Scroll**, not search: pull every chunk under the module's `source_path`, filtered by
   `project_id` and `active_generation` — the same filter discipline `rag.md` requires for
   every retrieval in this codebase.
4. Look for schema-shaped code: a Pydantic model, an ORM class, a migration, a form/DTO
   definition. If nothing schema-shaped is found under the path, generation fails with a
   specific reason (`NO_SCHEMA_FOUND`) — this is a hard failure, not a fallback to invented
   fields. Grounding is not optional here any more than it is for the checklist.
5. If a schema is found, the chat model is prompted to infer field names, types, and
   constraints from the excerpts, and to produce N sample records (N = the configured count:
   5/10/25/50) that all share the same field-key set. Structured output is validated the same
   way M4 validates its output contract: reject and retry (bounded, same retry/error taxonomy
   `app/rag/errors.py` already provides) rather than accept a batch with inconsistent keys.
6. A field inferred as a file/attachment type gets a plausible **filename** as its generated
   value (e.g. `"requirements-v2.pdf"`) — never generated binary content. This is a hard
   product boundary (see PRD §4.4's "out of scope"), not a v1-can't-get-to-it gap.
7. The result is written as a **pending change set** — one `add` operation per proposed
   record, each carrying a rationale — never directly into `mock_data_records`. This is the
   same non-negotiable M4 draws: generation writes a proposal, `apply` is the only path that
   writes rows.
8. Same instance-wide concurrency cap pattern as checklist generation (a new setting, e.g.
   `MOCK_DATA_MAX_CONCURRENT_GENERATIONS`, documented in `docs/configuration.md` and
   `backend/.env.example` alongside the existing checklist cap in the same change that adds
   it).

## 4. Refinement chat

`POST /checklist-modules/{id}/mock-data-messages` is a **third** caller of the same graph and
`Answerer` that already serves `/conversations/{id}/messages` and the checklist's
`/checklist-modules/{id}/messages` — not a new stream implementation. But the graph's existing
proposal mechanism (`TurnState`'s `existing_items`/`operations`/`change_summary`,
`build_propose_changes` in `app/rag/graph/nodes.py`, and `build_propose_prompt` in
`app/rag/prompts.py`) is hard-typed to checklist items — `ExistingItem` carries
`feature`/`test_name`/`expected_result`/`kind`, and the prompt text says "Existing checklist:".
Reusing it verbatim for a dynamic field-map record would be wrong on both the input and output
side.

**Resolution: additive, not generalized.** `TurnState` gains a second, parallel block —
`existing_records: list[ExistingRecord]`, `record_operations: list[dict[str, object]]`,
`record_change_summary: str` — beside the checklist block already there (that block was itself
an addition on top of the base conversational graph for M4; this follows the same precedent).
`build_answer_graph`'s `propose: bool` parameter becomes `propose_target:
Literal["checklist", "mock_data"] | None = None`, selecting which trailing proposal node is
attached — `build_propose_changes` (unchanged) or the new `build_propose_mock_data_changes`.
The retrieval/grading/generation portion of the graph is shared unmodified; only the trailing
proposal node differs. **Zero lines in the conversation or checklist-chat path move** — this is
purely additive to `state.py`, `nodes.py`, and `prompts.py`. The generalization (one proposal
shape for both) is explicitly rejected: it would rewrite the already-shipped M4 propose node,
its prompt, and its state fields for a cleanliness win the spec never asked for, at real
regression risk to live checklist chat.

The ordering contract in `.claude/rules/rag.md` applies unchanged to this third caller:

- `citations` exactly once, before the first `token`.
- Exactly one terminator (`done` or `error`), carrying `finishReason`.
- `changeSet` at most once, after the last token, absent when the turn proposed nothing.
- The termination write happens under `asyncio.shield` in `finally`, on the stream's own
  session — same reasons as every other caller of this graph.

A reviewer can ask for a specific shape before accepting a batch — "make every `start` date
fall in 2026", "drop the third record, duplicate of the second" — and the chat proposes a new
`mock_data_change_sets` row with `update`/`remove`/`add` operations against the current pending
set (or against applied records, if there is no pending set and the reviewer wants to revise
what already exists). Like the checklist chat, this never writes `mock_data_records` directly.

## 5. Apply

`POST /mock-data-change-sets/{id}/apply` takes the operation ids the reviewer accepted (or
`discard`). It applies each operation through an **explicit column allowlist** — only `fields`
may be written — mirroring the checklist apply path's defense against a `changes` payload
(model-authored content) claiming more than it should. There is less to defend here than in
M4 (no `status`/`current_result` to protect), but the allowlist pattern is kept for the same
reason: `changes` originates in a model's output, and an unchecked key is a latent
privilege the JSON shape would otherwise grant it.

Regeneration is **non-destructive**, matching M4: a new generation run proposes `add` /
`update` / `remove` operations against the records that already exist. A record accepted last
week survives a regeneration unless a `remove` operation targeting it is explicitly applied.

## 6. Export

Two endpoints, both scoped to a module's applied (non-deleted) records:

- `GET /checklist-modules/{id}/mock-data/export.json` — a JSON array of `fields` maps.
- `GET /checklist-modules/{id}/mock-data/export.xlsx` — one row per record, one column per
  field key. If records from different generation batches carry different key sets (a module
  regenerated after its schema changed), the column set is the union across all records, with
  blank cells where a given record has no value for that key.

## 7. API surface

| Method & path | Purpose |
| --- | --- |
| `POST /checklist-modules/{id}/mock-data-generations` | Trigger generation (background job) |
| `POST /checklist-modules/{id}/mock-data-messages` | Refinement chat (SSE) |
| `GET /checklist-modules/{id}/mock-data-records` | List applied records |
| `DELETE /mock-data-records/{id}` | Delete one record — `created_by`/`is_admin` gated, per the repo's destructive-operation rule |
| `GET /mock-data-change-sets/{id}` | Read a pending change set for review |
| `POST /mock-data-change-sets/{id}/apply` | Apply or discard |
| `GET /checklist-modules/{id}/mock-data/export.json` | Export as JSON |
| `GET /checklist-modules/{id}/mock-data/export.xlsx` | Export as spreadsheet |

All follow `response-api.md` and `router.md`: one service call per route except where the
pre-flight/stream split applies to the chat route (same exception `rag.md` already documents
for `ask_question`), the wire boundary's `camelCase`/`snake_case` translation via `ApiModel`,
and `403`-vs-`404` per the existing destructive-operation convention (module and project
existence stay visible; deleting someone else's record does not).

## 8. Frontend

A new **"Mock Data"** tab on the existing `/checklist/[moduleId]` page, beside "Test Plan":

- A table of applied records — columns are the dynamic field keys, rows are records.
- A "Generate" control with the count picker (5/10/25/50).
- A chat panel identical in shape to the checklist's refinement chat, plus Apply/Discard
  controls that appear when a change set is pending. Generate and the composer are disabled
  while a change set is pending, matching the checklist's existing single-flight rule.
- Two export buttons (JSON, xlsx).

No new top-level nav entry — this lives inside the module page M4 already shipped.

## 9. Out of scope for v1

Carried from PRD §4.4: binary/file content generation, auto-filling a *running target
application's* UI (the output is data to paste or feed a seed script, not browser automation
against another app), per-module RBAC, and the synthetic Q&A eval harness (deferred to phase
2, PRD §2.1).

## 10. Open items for the implementation plan

- Exact Alembic migration shape for the two new tables and their indexes (at minimum,
  `checklist_module_id` on both, and `status` on `mock_data_change_sets` for the "one pending
  per module" check).
- `NO_SCHEMA_FOUND` is a background-job failure reason, not a synchronous route error, so it
  is not an `ErrorCode` member — it never passes through `AppError`. It surfaces as a
  dedicated exception class name inside the scrubbed `dataset.error` text, the same
  class-name-survives-scrubbing convention every other generation failure reason already uses
  (`.claude/rules/ingestion.md`). New *synchronous* route failures (an unresolved change set,
  a generation already running) do get real `ErrorCode` members, same as the checklist's own.
- The exact structured-output contract (Pydantic models in `app/mockdata/contracts.py` or
  similar) for the generator's LLM call, and its retry/error classification wiring into the
  existing `app/rag/errors.py` taxonomy.
- Settings additions mirror the checklist's own surface exactly, since M4 has no dedicated
  "max concurrent generations" setting either — a generation's cost is already bounded by
  `chat_max_concurrency` (the shared chat-model semaphore) and by there being one consumer
  loop per worker process: `kafka_mock_data_topic`, `kafka_mock_data_partitions`,
  `mock_data_scroll_page_size`, `mock_data_max_files_per_job`. Documented in
  `docs/configuration.md` and `backend/.env.example` in the same change.

# M4 — QA Checklist: Design

**Status:** implemented, 2026-09-03.
**Implemented by:** `docs/superpowers/plans/2026-09-02-m4-qa-checklist.md`.
**Supersedes:** `docs/superpowers/specs/2026-08-31-m4-qa-list-design.md`.
**Requires PRD changes:** §4.3 rewritten, §4.4 storage clause amended, §6's M4 line, §7's
success criteria. Those land in the same change as the code
(`.claude/rules/documentation.md`).

---

## 0. Why this replaces a shipped milestone

The M4 that shipped is a **regression set for AskRepo itself**. A developer asks Dev Knowledge
a question, saves the answer, and `status: pass | fail` records whether *the assistant* got it
right. The subject under test is the retrieval pipeline.

This design replaces it with a **test plan for the indexed application**. A user points at a
module, AskRepo reads the code and derives the features in it and the test cases those features
need, and `status` records whether *the application under test* behaves correctly. The subject
moves from AskRepo's RAG to the customer's codebase.

Those are different products that happened to share the word "QA". The user chose to replace
rather than run both, so `qa_pairs` and everything built on it comes out (§9). This is recorded
here because `.claude/rules/contradiction-halt.md` requires the conflict be named rather than
worked around: the shipped feature was not wrong, it was answering a different question.

---

## 1. What this milestone delivers

- **Modules.** A user names a module ("Authentication") and points it at a path in the indexed
  repository. Modules are the unit of generation and the unit of review.
- **Generation.** A background job enumerates the module's files out of the vector index,
  reads what each one exposes, raises, and returns, and proposes a set of features and test
  cases with expected results grounded in the code.
- **Review.** Nothing generated enters the checklist unreviewed. Generation produces a
  *change set* a human applies or discards.
- **Chat refinement.** A shared conversation scoped to the module. The assistant answers in
  prose and proposes further change sets; the human applies them.
- **Test execution recording.** A tester fills in `currentResult` and `status` per row. AskRepo
  never fills these in — it has not run the application and will not claim to have.
- **Export.** The filtered grid as `.xlsx`, which is the artifact handed to whoever runs the
  tests.

Out of scope for M4: automated execution of the tests, integration with a test runner or
CI, per-module RBAC, and versioned checklist snapshots.

---

## 2. Decisions that go beyond the PRD

### 2.1 Every write to the checklist is a reviewed change set

Generation and chat are two producers of one thing: a `checklist_change_sets` row holding
proposed operations. Neither writes `checklist_items` directly. A human applies the change set,
and only the apply path mutates items.

The obvious alternative — generation writes rows, chat edits rows, humans edit rows — is
simpler on day one and wrong by the second generation. Consider the sequence that this feature
exists to survive:

1. A user generates the Authentication checklist. 40 test cases land.
2. A tester spends a day filling in `currentResult` and `status` on all 40.
3. Someone refactors auth and adds two-factor.
4. The user regenerates.

With direct writes, step 4 either destroys the tester's day of work or needs fuzzy matching to
avoid it — matching a freshly generated list against the stored one by string similarity on
test names, which is exactly the kind of heuristic that silently mismatches a renamed row and
duplicates it. With change sets, step 4 is a diff: the generator is given the module's existing
items and emits operations *against them* (`add`, `update` naming an `item_id`, `remove` naming
an `item_id`). Rows nobody touched are not in the change set at all, so their human-entered
results survive because nothing rewrote them.

One apply path, one audit trail, one review surface, two producers.

### 2.2 The generator enumerates; it does not search

`CodeRetriever` returns the top-k chunks most similar to a query. That is the correct tool for
"where is X handled" and the wrong one for "list every feature in this module", because top-k
has no notion of *all of them* — it returns k things and cannot report what it left out.

Deriving "Authentication has login, register, verify, forgot-password, reset-password" is an
enumeration problem. The generator therefore **scrolls** the collection by filter rather than
searching it by vector (§4.2).

This is possible only because of a decision M1 already made. `app/ingestion/vector_store.py:18`:
*"The payload holds the chunk text. `docs/PRD.md` §4.1 deletes the working copy."* Each point
carries `file_path`, `start_line`, `end_line`, `language`, `symbol`, `chunk_index`, and `text`.
The index is a reconstructable copy of the source, so enumeration needs no re-clone — and
therefore no second PAT decrypt, no second URL-validation surface, and no second `scrub`
obligation under `docs/PRD.md` §9.

The rejected alternative was re-cloning per generation. It reads files the chunker skipped
(§4.6), but it duplicates the entire ingestion trust boundary for that gain and introduces a
second source of truth that can disagree with the index the answers come from. If §4.6's
coverage ceiling turns out to bite in practice, re-clone returns as an opt-in "deep scan" —
not as the default path.

### 2.3 `currentResult` is a human's observation, never the model's

The generator fills `feature`, `test_name`, and `expected_result`. It leaves `current_result`
null and `status` at `untested`, always.

AskRepo reads code; it does not run the application. A model asked to predict "what actually
happens" from a handler body produces a fluent sentence indistinguishable from an observation,
and a tester reading a pre-filled `currentResult` will rubber-stamp it. The checklist's entire
value is that a person looked. A field that lets the model pretend to have looked destroys
that, and destroys it invisibly — nothing errors, the spreadsheet just quietly becomes
fiction.

This is the same reasoning as `.claude/rules/rag.md`'s grounding warnings: the guardrail does
not make the model honest, it removes the opportunity to be dishonest.

### 2.4 The chat is shared, inverting §4.2

`conversations` are private per user, `404`-on-miss, with no admin bypass, because
`docs/PRD.md` §4.2 states their privacy without qualification. Checklist chat does the
opposite: `checklist_messages` are scoped to the module and readable by every authenticated
user.

The reason is that the chat is the **justification record for a shared document**. A tester
reading "expected result: 410 GONE" needs to be able to find out why it says 410 — and under
private conversations that reasoning would be visible only to whoever happened to run the
refinement. A shared artifact whose change history is private is a shared artifact nobody can
audit.

This is a deliberate departure from §4.2, not an oversight, and the PRD rewrite must say so in
those words. It follows the access shape of `projects` and the old `qa_pairs`, not of
`conversations`: everyone reads, `created_by` gates destruction.

### 2.5 Editing a test is gated; recording a result is not

Two different writes to `checklist_items`, with two different rules:

- `PATCH /checklist-items/{id}` — changing `test_name`, `expected_result`, `feature`, `notes`.
  Requires `created_by` or `is_admin`. Returns `403`, because module existence is not a secret
  (`.claude/rules/response-api.md`).
- `PUT /checklist-items/{id}/result` — setting `current_result` and `status`. Open to **every**
  authenticated user.

The split is the point. A tester who did not author the checklist must be able to record what
they observed without being able to quietly rewrite what was expected — otherwise the cheapest
way to make a failing test pass is to edit the expectation. This mirrors `PUT
/qa-pairs/{id}/status` being ungated in the shipped M4 (`docs/PRD.md:338`), and it is the one
piece of that design that survives unchanged.

`PUT` rather than `PATCH` here is deliberate and matches the existing precedent: the route
replaces the whole result — both fields, together — rather than partially updating an item.
`.claude/rules/router.md`'s "`PATCH`, not `PUT`" governs the CRUD update route, which is
`PATCH` as required.

### 2.6 A module is an entity; a feature is a string

`checklist_modules` is a table because a module has state of its own: which path it covers,
whether a generation is running, when it last ran, which `active_generation` it was built from,
and what went wrong if it failed.

`feature` is a `String` column on `checklist_items`. A features table would add a join and an
orphan-cleanup problem in exchange for nothing — a feature has no attributes beyond its name,
and the grid sorts on `(module, feature, position)` perfectly well as a column. If features
later acquire attributes (an owner, a priority, a release), promote it then; the migration is
mechanical and doing it now is speculative.

### 2.7 The model's proposals reach Postgres from the server, never from the browser

`.claude/rules/rag.md` establishes this for QA re-runs: the streamed answer is written into a
server-held pending slot, and the client sends only an instruction (`accept`) — never content.
The reason is that a QA pair is published to every user on the instance, so its stored content
must come from a model through the server rather than from whoever's tab happened to be open.

A checklist is published the same way, so the same rule applies. The chat stream persists its
change set server-side (§5.3), and `POST /checklist-change-sets/{id}/apply` takes a list of
operation **ids** — selective apply is still an instruction, not content.

---

## 3. Storage

Four new tables. All carry `deleted_at` per `docs/PRD.md` §5.1.

### 3.1 `checklist_modules`

```python
class ChecklistModule(Base, TimestampMixin, SoftDeleteMixin):
    id: UUID
    project_id: UUID                    # FK projects.id
    created_by: UUID                    # attribution + destructive gate; never scopes reads
    name: str                           # "Authentication"
    source_path: str                    # repo-relative dir or file the module covers
    status: ChecklistModuleStatus       # empty | generating | review | ready | failed
    error: str | None                   # scrubbed; see §4.7
    indexed_generation: int | None      # the project generation the last run read
    last_generated_at: datetime | None
    lease_expires_at: datetime | None   # §4.5
```

`ChecklistModuleStatus` is a `StrEnum` (`.claude/rules/clean-code.md` requires `Literal` or an
enum for a closed set of strings):

| Value | Meaning |
| --- | --- |
| `empty` | Created, never generated |
| `generating` | A worker holds the lease and is running |
| `review` | A change set is pending a human decision |
| `ready` | Items exist, nothing pending |
| `failed` | The last generation failed; `error` says why |

`indexed_generation` is what makes "this checklist is stale" answerable: if it is behind
`project.active_generation`, the repository has been reindexed since the checklist was built.
The UI surfaces that as a prompt to regenerate; nothing enforces it.

### 3.2 `checklist_items`

```python
class ChecklistItem(Base, TimestampMixin, SoftDeleteMixin):
    id: UUID
    module_id: UUID                     # FK checklist_modules.id
    project_id: UUID                    # denormalised; the grid and export filter on it
    feature: str                        # "Login"
    test_name: str                      # "Rejects a wrong password"
    expected_result: str                # "401 with code INVALID_CREDENTIALS"
    current_result: str | None          # human only (§2.3)
    status: ChecklistItemStatus         # untested | pass | fail | blocked
    notes: str | None
    citations: list[Citation] | None    # file path + line range the expectation came from
    source: ChecklistItemSource         # generated | manual
    position: int                       # stable ordering within (module, feature)
    created_by: UUID
    reviewed_by: UUID | None
    reviewed_at: datetime | None
```

`blocked` is a real state, distinct from `fail`: "could not run this because login is broken"
is not the same finding as "this behaved wrongly", and without the value testers will record
it as `fail` and corrupt the pass rate.

`project_id` is denormalised off `module_id` deliberately. The grid and the export both filter
by project across modules, and carrying it here avoids a join on every list query. The
invariant — an item's `project_id` equals its module's — is set at insert and never updated,
because a module cannot move between projects.

`citations` reuses the existing `Citation` shape from `app/schemas/conversation.py`, so the UI
that renders sources on an answer renders them on a test case with no new component.

### 3.3 `checklist_change_sets`

```python
class ChecklistChangeSet(Base, TimestampMixin, SoftDeleteMixin):
    id: UUID
    module_id: UUID
    origin: ChangeSetOrigin             # generation | chat
    message_id: UUID | None             # the chat turn that produced it; null for generation
    summary: str                        # one line: "3 added, 1 expectation corrected"
    operations: list[ChangeOperation]   # JSONB
    status: ChangeSetStatus             # pending | applied | discarded
    resolved_by: UUID | None
    resolved_at: datetime | None
    created_by: UUID
```

An operation is one of three shapes, discriminated by `op`:

```python
{"op": "add",    "id": "<op-uuid>", "feature": ..., "testName": ..., "expectedResult": ...,
                 "citations": [...], "rationale": "..."}
{"op": "update", "id": "<op-uuid>", "itemId": "<uuid>", "changes": {...}, "rationale": "..."}
{"op": "remove", "id": "<op-uuid>", "itemId": "<uuid>", "rationale": "..."}
```

Each operation carries its own `id` so apply can be selective, and a `rationale` so the diff
UI can say why without the user having to read back through the chat.

**At most one `pending` change set per module.** A second generation while one is pending is
refused with `409` rather than queued — two overlapping diffs against the same items would
have to be rebased against each other, and there is no sensible automatic answer to that. The
user discards or applies the first.

An `update` or `remove` naming an `item_id` that no longer exists at apply time is **skipped,
not failed**, and reported in the apply response. The item was deleted between proposal and
apply; failing the whole change set for that would make a stale row block three good ones.

### 3.4 `checklist_messages`

```python
class ChecklistMessage(Base, TimestampMixin, SoftDeleteMixin):
    id: UUID
    module_id: UUID
    role: MessageRole                   # user | assistant
    content: str
    citations: list[Citation] | None
    model: str | None
    finish_reason: str | None
    created_by: UUID                    # who spoke; every user can read (§2.4)
```

Unlike `messages`, this table **does** carry `deleted_at`, because §5.1's exception for
`messages` was justified by conversations being private and deleted wholesale with their
parent. A shared, auditable record does not get that exception.

### 3.5 Indexes

| Index | Why |
| --- | --- |
| `(project_id, created_at)` on `checklist_modules` | The module list, newest first |
| `(module_id, feature, position)` on `checklist_items` | The grid's default ordering |
| `(project_id, status)` on `checklist_items` | The status filter across modules, and the export |
| `(module_id, status)` on `checklist_change_sets` | Finding the pending change set — the hot path on every module read |
| `(module_id, created_at)` on `checklist_messages` | Chat history |

No GIN index: `tags` is not carried forward. Filtering is by module, feature, and status, all
of which are btree-friendly. If tags return later they bring their own index, as `qa_pairs`
did.

### 3.6 Migration

One Alembic revision:

1. Create the four tables and their indexes.
2. `DROP TABLE qa_pairs`.

The drop is not reversible with data — the downgrade recreates the table empty. That is stated
in the revision's docstring rather than pretended otherwise. There is no data migration from
`qa_pairs` to `checklist_items`: a saved question-and-answer is not a test case, and
mechanically reshaping one into the other would produce rows whose `expected_result` is a
paragraph of prose about the codebase.

### 3.7 Soft delete and cascade

- Deleting a **project** soft-deletes its modules, items, change sets, and messages, matching
  what §4.3 required of `qa_pairs`.
- Deleting a **module** soft-deletes its items, change sets, and messages.
- Nothing here reaches Qdrant. The checklist owns no vector points — it *reads* the project's,
  and the project's own delete path already hard-deletes them (`CLAUDE.md`, "Soft delete does
  not reach Qdrant").

---

## 4. Generation

### 4.1 The job

`POST /checklist-modules/{id}/generate` validates, publishes a Kafka message, and returns
`202` with the module in `generating`. It does not wait. This is the shape `POST /projects`
already uses, and `docs/PRD.md` §4.4 already established that generation is background work
with an instance-wide concurrency cap rather than an inline request.

A new topic (`askrepo.checklist.generate`) and a consumer registered in `app/worker.py`
alongside `IngestionConsumer`. It inherits the existing retry ladder and the
pause-and-keep-polling behaviour from `.claude/rules/ingestion.md` unchanged — a generation over
a large module can exceed `max.poll.interval.ms` for exactly the same reason an index can, and
the fix is the same one.

Pre-flight checks happen in the route's service call, before publishing, so they can return a
status code:

| Condition | Response |
| --- | --- |
| Module not found | `404 CHECKLIST_MODULE_NOT_FOUND` |
| Project not `ready` | `409 PROJECT_NOT_READY` |
| A generation already running | `409 GENERATION_IN_PROGRESS` |
| A change set already pending | `409 CHANGE_SET_PENDING` |
| `source_path` matches no indexed file | `409 MODULE_PATH_NOT_INDEXED` |

The embedding-model guard (`409 EMBEDDING_MODEL_CHANGED`, `.claude/rules/rag.md`) **does not
apply**. That guard exists because a query embedded by a different model lands in a vector
space the collection was never built in. Generation embeds nothing — it filters and scrolls —
so there is no space to mismatch.

### 4.2 Scroll, not search

A new method on `VectorStore`:

```python
async def scroll(
    self,
    *,
    collection: str,
    project_id: uuid.UUID,
    generation: int,
    path_prefix: str,
    page_size: int,
) -> AsyncIterator[list[dict[str, Any]]]:
```

Qdrant's `scroll` returns points matching a filter with no query vector, paginated by an offset
token. The filter is `project_id` AND `generation` AND `file_path` matching the prefix — the
first two for exactly the reason `.claude/rules/rag.md` gives for retrieval (a reindex means
both generations are in the collection by design, and an unfiltered read mixes them), the third
to scope to the module.

`ensure_collection` gains a payload index on `file_path`. Without it the prefix filter degrades
to a scan of the whole collection, which is the same failure the existing `project_id` and
`generation` indexes exist to prevent.

`InMemoryVectorStore` implements `scroll` too, so generation tests need no Qdrant — the same
arrangement that lets route and consumer tests run with no broker.

### 4.3 Rebuilding a file

Group the scrolled points by `file_path`, sort each group by `chunk_index`, concatenate `text`.

Chunks overlap by `chunk_overlap` characters, so naive concatenation duplicates the seam. The
rebuild trims each chunk's leading overlap against the previous chunk's tail before joining.
Duplicated lines would otherwise reach the model as repeated code, which reads as a genuine
duplication in the source and has produced test cases about it.

A file whose chunks are non-contiguous — one is missing, because it exceeded a limit or the
scroll page was lost — is **reported, not silently stitched**. The generation's summary names
which files were partial. A checklist built from code with a hole in it, where nothing says so,
is the failure mode §4.6 is about.

### 4.4 Map, then reduce

**Map**, one call per file: given the file's reconstructed text, what does this file expose,
what does it raise, what does it return, what does it validate. Output is a structured list of
observed behaviours with line ranges. Files are processed concurrently up to a configured cap.

**Reduce**, one call: given every file's observations **and the module's existing items**,
produce the change-set operations. Passing the existing items is what makes regeneration a diff
rather than a fresh list needing to be matched afterwards (§2.1) — the model is asked to change
a checklist, not to write one.

Both prompts live in `app/rag/prompts.py` alongside the existing ones, and both are covered by
the `model` marker suite. `.claude/rules/rag.md`'s note applies directly: no ordinary test can
catch a prompt that enumerates or cites wrongly, because everything else drives
`ScriptedChatModel`. `uv run pytest -m model` after editing either prompt.

The reduce output is a structured schema, not free text. A model asked for prose and then
parsed produces a change set that fails to parse on the turn it matters.

**The excerpts are untrusted input**, exactly as in `.claude/rules/rag.md`: they come from a
cloned repository anyone with commit access wrote. Both prompts wrap file content in
`<excerpts>` delimiters and state that everything inside is data being reported on. As there,
this is mitigation and not a boundary — what bounds the damage is that the generator has no
tools, no write access beyond a change set a human must approve, and no network reach.

### 4.5 The lease is the deduplication boundary

Kafka is at-least-once. A rebalance, a redelivered uncommitted offset, or a reconcile sweep
racing a retry can deliver the same generation twice. What prevents two workers generating the
same module is a **database lease on the module row**, exactly as `ProjectRepository.claim`
does for ingestion (`.claude/rules/ingestion.md`).

The service-level "is one already running?" check in §4.1 is a fast path for a nicer API
response. It is not the guard. Removing the lease because the service already checks is the
defect that rule names explicitly.

A worker that dies holding a lease is recovered when it expires, by the same reconcile sweep in
`app/worker.py` that recovers ingestion jobs — extended to sweep modules as well as projects.

### 4.6 The coverage ceiling, stated as a limitation

**The checklist can only see what the chunker ingested.** `app/ingestion/walker.py` skips
`SKIP_DIRECTORIES`, binaries, and files over `max_file_bytes`, and maps a fixed extension set.
A feature living entirely in a skipped file is invisible to the generator, and — this is the
part that matters — the generator has no way to know it is missing.

This is a real bound on a deliverable whose value is completeness, so it is surfaced rather
than buried:

- The generation summary reports how many files were read and lists any that were partial
  (§4.3).
- The UI states which path was enumerated, so a user can see that `frontend/` was never in
  scope.
- The spec records that re-clone (§2.2's rejected alternative) is the escape hatch if this
  turns out to bite.

What it does **not** do is claim coverage it cannot verify. There is no "100% covered" badge.

### 4.7 Failure

A failed generation sets `status = failed` and writes a scrubbed message to `error`. Everything
on that path goes through `scrub` before being written or logged — the module's `source_path`
is user-supplied, the project's clone URL carries a PAT, and `docs/PRD.md` §9 requires that no
token survive into anything an operator can read.

A failure leaves existing items untouched. Generation only ever proposes; a run that dies
before writing its change set has changed nothing, which is the same property that makes a
failed reindex leave the previous index serving.

---

## 5. The chat stream

### 5.1 The pre-flight/stream split

Identical in structure to `POST /conversations/{id}/messages`. Once SSE headers are sent the
status is fixed at `200`, so everything that can legitimately return something else — module
exists, project is `ready`, the embedding guard (which **does** apply here, because chat
retrieves) — happens in a `prepare_turn` before the `StreamingResponse` is constructed.

`POST /checklist-modules/{id}/messages` is therefore the second route in the codebase that
makes two service calls, for the same reason `ask_question` is the first
(`.claude/rules/router.md`). All the policy stays in the service; the route chooses the
transport.

### 5.2 The stream adds one event

Event order on a chat turn:

1. `citations` — exactly once, before the first `token`, on every route. Empty if the turn
   retrieved nothing.
2. `token` — many.
3. `changeSet` — at most once, after the last token, carrying the proposed operations and the
   change set's id. Absent when the turn proposed no changes (a question like "why does this
   test expect 410?" is a legitimate turn that changes nothing).
4. Exactly one terminator, `done` or `error`, carrying a `finishReason`.

`ChangeSetEvent` inherits `ApiModel` and **is added to `SSE_EVENT_MODELS`**. This is the single
easiest thing in this design to ship broken: SSE payloads never pass through a `response_model`,
so FastAPI validates nothing about them, and the tuple walked by `tests/test_api_model.py` is
the only enforcement they get. An event added to the stream but not to the tuple ships
`snake_case` keys to a browser expecting `camelCase`, and no test fails.

The terminator is built only by the answerer adapter, never by a node
(`.claude/rules/rag.md`), which is what keeps "exactly one terminator" structural.

### 5.3 The change set is written under a shield

`stream_turn`'s cleanup runs in a `finally` under `asyncio.shield`, using its own session from
the sessionmaker rather than the request-scoped one, and cancelling the in-flight `anext`
before closing the answerer. All three parts are load-bearing and all three are explained in
`.claude/rules/rag.md`; they are repeated here only because the thing being persisted is now a
change set as well as a message.

A client that disconnects mid-turn still gets its proposal saved. That is the case the pattern
exists for — a slow generation over a large module is precisely when a browser tab gets closed.

### 5.4 Apply and discard

`POST /checklist-change-sets/{id}/apply` takes `{"operationIds": [...]}` — ids only. Omitting
the field applies all of them. The server reads the stored operations, applies the named ones
inside one transaction, marks the change set `applied`, and returns the resulting items plus a
list of operations that were skipped because their target item no longer exists (§3.3).

`POST /checklist-change-sets/{id}/discard` marks it `discarded` and writes nothing.

Either on an already-resolved change set is `409 CHANGE_SET_ALREADY_RESOLVED`. Both are open to
any authenticated user: applying a change set is reviewing a shared document, and gating it on
`created_by` would mean only the person who ran the generation could act on it.

---

## 6. API surface

Three resources, therefore three routers, one per module, per
`.claude/rules/router.md`'s one-router-per-resource rule:

| File | `prefix` | `tags` |
| --- | --- | --- |
| `app/api/routes/checklist_modules.py` | `/checklist-modules` | `Checklist Modules` |
| `app/api/routes/checklist_items.py` | `/checklist-items` | `Checklist Items` |
| `app/api/routes/checklist_change_sets.py` | `/checklist-change-sets` | `Checklist Change Sets` |

One tag per router, each naming its own resource, as the rule requires — not one shared
`QA Checklist` tag across three routers. They are registered consecutively in `app/main.py` so
they still read as one feature in `/docs`.

| Method | Path | Status | Notes |
| --- | --- | --- | --- |
| `GET` | `/checklist-modules` | 200 | `ChecklistModuleListQuery` |
| `POST` | `/checklist-modules` | 201 | |
| `GET` | `/checklist-modules/{id}` | 200 | |
| `PATCH` | `/checklist-modules/{id}` | 200 | `403` unless creator/admin |
| `DELETE` | `/checklist-modules/{id}` | 204 | `403` unless creator/admin |
| `POST` | `/checklist-modules/{id}/generate` | 202 | §4.1 |
| `GET` | `/checklist-modules/{id}/messages` | 200 | |
| `POST` | `/checklist-modules/{id}/messages` | 200 | SSE, §5 |
| `GET` | `/checklist-modules/{id}/change-sets` | 200 | |
| `GET` | `/checklist-items` | 200 | `ChecklistItemListQuery` |
| `POST` | `/checklist-items` | 201 | `source = manual` |
| `PATCH` | `/checklist-items/{id}` | 200 | `403` unless creator/admin (§2.5) |
| `PUT` | `/checklist-items/{id}/result` | 200 | **Ungated** (§2.5) |
| `DELETE` | `/checklist-items/{id}` | 204 | `403` unless creator/admin |
| `POST` | `/checklist-change-sets/{id}/apply` | 200 | §5.4 |
| `POST` | `/checklist-change-sets/{id}/discard` | 200 | §5.4 |
| `GET` | `/checklist-items/export` | 200 | `.xlsx`, §7 |

Every route declares a `summary` and a `responses` block traced from its own service method —
not copied from the route beside it.

### 6.1 Read scoping

`GET /checklist-modules` and `GET /checklist-items` scope through
`access.resolve_project_scope(current_user)`. Neither filters on `created_by`, neither builds
its own project filter, and neither consults `is_admin` for reads.

This is `docs/PRD.md` §7's testable criterion — read scoping happens in exactly one function,
confirmed by grep — and it is the whole reason phase 2 is a change to one function body rather
than a sweep. A route that filters on its own is a defect even when its output is currently
identical.

### 6.2 Filters go on `ListQuery` subclasses

```python
class ChecklistItemListQuery(ListQuery):
    project_id: uuid.UUID | None = None
    module_id: uuid.UUID | None = None
    feature: str | None = None
    status: ChecklistItemStatus | None = None
    source: ChecklistItemSource | None = None
```

Never as sibling `Query(...)` parameters. FastAPI flattens a Pydantic model into individual
query params only while it is the route's sole query parameter; add a scalar beside it and
every request fails with `{"request": "Field required"}`, naming nothing in the signature.
`.claude/rules/rag.md` documents this failure in full.

### 6.3 New `ErrorCode` members

Added: `CHECKLIST_MODULE_NOT_FOUND`, `CHECKLIST_ITEM_NOT_FOUND`, `NOT_CHECKLIST_OWNER`,
`CHANGE_SET_NOT_FOUND`, `CHANGE_SET_PENDING`, `CHANGE_SET_ALREADY_RESOLVED`,
`GENERATION_IN_PROGRESS`, `MODULE_PATH_NOT_INDEXED`.

Retired with their routes: `QA_PAIR_NOT_FOUND`, `NOT_QA_PAIR_OWNER`, `NO_PENDING_RUN`,
`ANSWER_INCOMPLETE`. `ErrorCode` values are a wire contract and
`.claude/rules/response-api.md` says add members, never rename them — removing one is a
deliberate act, permitted here only because the sole producer of each is being deleted and the
sole consumer is the in-repo frontend being replaced in the same change.

Kept and reused: `PROJECT_NOT_FOUND`, `PROJECT_NOT_READY`, `EMBEDDING_MODEL_CHANGED`,
`INVALID_SORT_FIELD`, `EXPORT_TOO_LARGE`, `VECTOR_STORE_UNAVAILABLE`, `LLM_UNAVAILABLE`.

---

## 7. Export

`app/services/qa_export.py` is **carried over rather than rewritten from scratch**: it is
renamed to `app/services/checklist_export.py`, keeping its structure — openpyxl, a
`(header, width)` tuple table, wrapped prose columns, the row cap — and changing only the
column set and the row projection. Its docstring's argument for `.xlsx` over CSV (the long
columns are multi-paragraph prose that CSV renders as one unwrapped line that runs off the
screen) applies unchanged and stays.

Columns:

| Module | Feature | Test name | Expected result | Current result | Status | Notes | Source | Reviewed by | Reviewed at | Citations | Project |

Sorted by `(module, feature, position)` so the sheet reads in the order a tester works.

The export takes the same filters as `GET /checklist-items` and applies **no pagination** — the
point is to get the whole filtered set into one file. It keeps the existing row cap and its
`EXPORT_TOO_LARGE` response rather than streaming an unbounded workbook into memory.

The Next proxy already survives a binary body from the shipped export; that handling carries
over unchanged.

---

## 8. Frontend

Replaces `/qa`, at `/checklist`:

- **`/checklist`** — modules for a project: name, path, status, item count, pass/fail/untested
  counts, and a staleness badge when `indexed_generation` is behind the project's.
- **`/checklist/[moduleId]`** — the grid, grouped by feature. Inline editing of
  `currentResult` and `status` (the ungated write, so every user gets the control) with the
  definition columns read-only unless the user is the creator or an admin. A **Generate**
  action, a **Review changes** banner when a change set is pending, and the chat panel.
- **The change-set diff** — added / changed / removed, each row with its rationale and a
  checkbox, with **Apply selected** and **Discard**.
- **Export** — same filters as the grid, downloads the `.xlsx`.

Design-system constraints from `.claude/rules/design-system.md` apply without exception: no
`dark:` colour utility anywhere, no palette utility (`bg-zinc-50`, `text-slate-600`), semantic
tokens only, and composition via `render={<Component />}` rather than `asChild`, which does not
exist on the Base UI base and fails silently.

The SSE parser, the single-flight refresh, and the proxy's refresh-and-retry are reused
unchanged; the answer stream's ordering contract test gains a case for `changeSet`.

`components/qa/save-to-qa-dialog.tsx` and its Ask-screen entry point are **removed with no
replacement**. Publishing a Dev Knowledge answer to the team is a capability this milestone
deliberately drops (decided during design); a checklist row is a test case, not a saved answer,
and routing one into the other would produce items whose `expected_result` is prose.

---

## 9. What comes out

**Backend:** `app/models/qa_pair.py`, `app/schemas/qa_pair.py`, `app/services/qa_pair.py` (682
lines), `app/repositories/qa_pair.py`, `app/api/routes/qa_pairs.py` (11 routes), their tests,
and the router registration in `app/main.py`. `app/services/qa_export.py` is renamed rather
than deleted (§7).

**Frontend:** `app/(app)/qa/`, `components/qa/`, `lib/qa/`, and the nav entry.

**Migration:** drops `qa_pairs` (§3.6).

---

## 10. Documentation landing in the same change

`.claude/rules/documentation.md` makes these part of this change, not a follow-up:

| Doc | Change |
| --- | --- |
| `docs/PRD.md` §4.3 | Rewritten: QA List → QA Checklist. New user stories, acceptance criteria, and the four schemas |
| `docs/PRD.md` §4.4 | Kept as a planned milestone. Its storage clause — "output writes into the shared `qa_pairs` table (§4.3)" — becomes "its own storage, defined when M5 is designed", because that table no longer exists |
| `docs/PRD.md` §4.2 | Note the deliberate inversion: checklist chat is shared where conversations are private (§2.4) |
| `docs/PRD.md` §6 | M4's line rewritten. M5 unchanged in scope |
| `docs/PRD.md` §7 | "QA List has 20+ saved pairs… usable as a shared regression set" replaced by a criterion about checklist generation. The M5 eval criterion stays, pointed at M5's own storage |
| `CLAUDE.md` | The M4 paragraph, the route counts, the frontend route list, and the rule table if `rag.md` is renamed |
| `.claude/rules/rag.md` | The "ordering contract holds on `POST /qa-pairs/{id}/rerun` too" section becomes the checklist chat section; the pending-slot reasoning is preserved because it now justifies the change set |
| `backend/README.md` | Route table — 11 routes out, 17 in |
| `docs/configuration.md` + `backend/.env.example` | Every new `Settings` field: the generation topic, the map concurrency cap, the instance-wide generation cap, the scroll page size |
| `infra/docker-compose.yml` | Nothing — no new service |

---

## 11. Known limitations

1. **Coverage is bounded by the chunker** (§4.6). Surfaced in the UI and the generation
   summary; never claimed as complete.
2. **`currentResult` is only ever as fresh as the last manual test run.** Nothing detects that
   the code changed under a passing row — `indexed_generation` flags a stale *checklist*, not a
   stale *result*.
3. **No test execution.** AskRepo generates the plan; a human runs it. Automating execution
   would need a running instance of the application under test, which is a different product.
4. **One pending change set per module** (§3.3). Two people cannot refine concurrently; the
   second gets `409`.
5. **Expected results are model-derived and can be wrong.** The review gate is the only defence,
   which is why §2.1 makes it unskippable. M5, if it later grades generated expectations against
   the code, is the automated backstop.

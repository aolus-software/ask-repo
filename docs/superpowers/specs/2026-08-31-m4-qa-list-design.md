# M4 — QA List: Design

Status: designed, not implemented.
Date: 2026-08-31.
Covers: the shared `qa_pairs` store, its route group, a second Server-Sent Events surface for
re-running a saved question, spreadsheet export, and the `/qa` screens — against a backend
where M0, M1, M2 and M3 are shipped and the frontend is current through M3.

Ground truth, in precedence order: `docs/PRD.md`, then `.claude/rules/`
(`contradiction-halt.md`, `documentation.md`, `router.md`, `response-api.md`, `rag.md`,
`persistence.md`, `clean-code.md`, `design-system.md`, `forms.md`, `navigation.md`), then the
prior milestone specs. This document departs from the PRD in five named places; §2 states each
one, and §11 amends the PRD in the same change rather than leaving the contradiction standing.

---

## 1. What this milestone delivers

Today an answer exists only inside the conversation that produced it. Conversations are private
(`docs/PRD.md` §4.2), so a good answer about the authentication flow is invisible to everyone
except the person who happened to ask, and it decays silently as the code moves underneath it.

After this milestone:

- An answer can be **published** to the instance with one action from the Ask screen, becoming a
  QA pair that every user can read.
- The QA List is a **grid**: module, expected result, result, status. It filters by project,
  module, tag, source, status and creator, and it paginates like every other list route.
- A pair can be **re-run** against the current index. The new answer streams beside the stored
  one, is held server-side until a human accepts it, and survives a page reload.
- A pair carries a **status** — `unreviewed` / `pass` / `fail` — which any user may set. It is
  the single column that answers "does the result match the expected result?", written by a
  human in M4 and by M5's judge later.
- The list **exports to `.xlsx`**, honouring whatever filters are on screen.

What this does **not** deliver: no generated pairs (M5 owns `source="generated"`), no
LLM-graded scoring (M5 writes `eval_score`), no run history beyond the single pending slot, no
change to the answer graph, the access model, or the conversation routes. §13 is the full list.

The streaming contract in `.claude/rules/rag.md` is preserved exactly on the new route, and
that preservation shapes §5.

---

## 2. Decisions that go beyond the PRD

Each was raised and settled during design. They are recorded because a reader who finds the code
disagreeing with `docs/PRD.md` needs to know which one is stale and why.

### 2.1 `status` replaces `verified`, and it means "does the result match the expected result?"

**This changes the PRD's schema.** `docs/PRD.md:356-357` gives `verified: bool = False` and
`verified_by: UUID | None`, and §4.3's user story reads "I can mark a Q&A pair as 'verified
correct' so it becomes a trusted reference / eval case for the team."

This design replaces both with `status: Literal["unreviewed", "pass", "fail"]`, `reviewed_by`
and `reviewed_at`.

The reason is M5. `docs/PRD.md` §4.4 already specifies that the generator's eval mode will
"compare answer vs `reference_answer` … and store the result in `eval_score`" — a pass/fail
judgement about whether the produced answer matches the expected one. That is the *same
question* a human answers when they tick "verified correct". Keeping both a boolean and a score
means the grid has two columns that disagree the first time a human and the judge reach
different conclusions, and no rule anywhere says which wins.

One column, three states, written by whoever looked most recently — a human through
`PUT /qa-pairs/{id}/status`, or M5's judge alongside the `eval_score` it computes. `reviewed_by`
being nullable is what distinguishes them: a human verdict names a user, a machine verdict does
not.

`verified` is not merely renamed. A boolean has no way to record "a human looked and it was
wrong", which is the state a regression set most needs to surface after a refactor.

### 2.2 A pair carries `module`, which overlaps `tags` on purpose

**The PRD has no `module` field.** `docs/PRD.md:353` gives `tags: list[str]` with the examples
"auth", "billing" — which is the same information a module column would hold.

Both exist because they play different roles in the grid. `module` is one value, is the first
column, and sorts; `tags` are many, are filter facets, and are what §4.3 specifies for the
filtered list view. Collapsing them would mean either sorting a table by an array, or dropping
the filter the PRD asks for.

This is the weakest decision in this document and it should be reviewed after the list has real
content in it. If in practice the grid only ever filters by `module` and nobody tags anything,
`tags` is the field to drop — not the reverse, because the column is the thing the milestone was
asked for.

### 2.3 `reference_answer` is writable on manual pairs

**The PRD scopes it narrowly.** `docs/PRD.md:350` annotates `reference_answer: str | None` with
"generated pairs only".

The grid needs an "expected result" column on every row, or the status verdict in §2.1 has
nothing to be a verdict *about*. So a human may write `reference_answer` on a manual pair
through `PATCH /qa-pairs/{id}`.

It is also **seeded automatically**: saving an answer from the Ask screen writes the same text
into both `answer` and `reference_answer`. The person saving is publishing an answer they judged
good, so that answer is the expected result until someone says otherwise — and a re-run three
weeks later then has something concrete to be compared against, without anyone having done extra
work at save time.

### 2.4 Export ships in M4

**The PRD lists it as out of scope.** `docs/PRD.md:364`: "**Out of scope for v1:** exporting,
collaborative editing of a single pair, versioned diffing UI."

Overridden by the owner during design. The QA List is described in §4.3 as the team's regression
set, and a regression set that cannot leave the tool cannot be reviewed in a meeting, attached
to a ticket, or diffed against last month's. `.xlsx` was chosen over CSV deliberately (§6).

The other two out-of-scope items stand and are not affected.

### 2.5 A re-run result is held server-side, and the client never posts an answer

**The PRD is silent on the mechanism.** `docs/PRD.md:339` says only that "the re-run does not
overwrite the stored answer unless the user saves it."

The obvious implementation — stream the new answer to the browser, let the browser post it back
on Save — is rejected. It would make the API accept assistant-authored text from a client, which
is precisely the hole §4.2 of this document closes for creation: a QA pair is published to every
user on the instance, so the text in it must come from a model through the server, never from a
request body.

So the re-run writes its result into a **pending slot** on the pair
(`pending_answer`, `pending_citations`, `pending_model`, `pending_finish_reason`,
`pending_run_at`) and `POST /qa-pairs/{id}/rerun/accept` promotes it. The client sends an
instruction, never content.

Two things fall out of this that are worth having on purpose. A re-run survives a reload, a
closed laptop, or a different browser — the work is not lost because a tab was closed forty
seconds in. And `pending_finish_reason` gives `accept` something to refuse on, so a truncated
run can be read but never published (§2.6).

Five nullable columns is the point at which a separate `qa_runs` table starts to look better,
and that table is also where M5's eval runs would naturally live. It is not built now: M4 needs
exactly one pending run per pair, nothing reads history, and promoting the slot to a table later
is an additive migration. Whoever specifies M5 should revisit this before adding a sixth
`pending_*` column.

### 2.6 A pair can only be created from a message the server can read, and only a finished one

`POST /qa-pairs` takes `{messageId, module?, tags?}`. The server resolves the message through
its conversation via `resolve_conversation_owner`, and copies `question`, `answer`, `citations`,
`model` and `project_id` out of the rows.

This is what makes `docs/PRD.md` §4.2's stated rationale for `finish_reason` true rather than
aspirational — "§4.3's 'save to the QA List' would publish a cut-off answer to the whole team".
That guard needs an enforcement point, and there is only one: the server reading the row. A
request body carrying `{question, answer, citations}` has no way to be checked, because a
truncated answer and a short answer are the same string.

Consequences, both intended:

- Saving from **another user's** conversation returns `404`, not `403` — conversation existence
  is private and this route must not become the place that leaks it.
- Saving a message whose `finish_reason` is anything but `stop` returns
  `409 ANSWER_INCOMPLETE`.
- M5's generator does **not** use this route. It writes rows through `QAPairService` directly,
  because generated pairs have no message and no conversation.

### 2.7 The re-run reuses the answer graph and the existing SSE event models unchanged

`Answerer.answer` is called with `history=[]` and the pair's question. No new node, no new
prompt, no new event type, and therefore no new entry in `SSE_EVENT_MODELS`.

Empty history is correct rather than convenient: a saved question is standalone by construction,
so there is no conversation for the classify node to condense. And the classify node still runs
— if a saved question now routes to `out_of_scope`, that is a real fact about the pair and the
`done` event reports it. Suppressing the router for re-runs would make a re-run take a path the
original answer never took, which defeats the point of running it again.

One wire change is unavoidable and is specified in §8.1: the terminator events' `messageId`
becomes optional, because a re-run has no message.

---

## 3. Storage

### 3.1 One table

`backend/app/models/qa_pair.py`, one table, created whole — M5's columns included. This is
`docs/PRD.md` §4.3's decision, not a new one: "QA List and Mock Data Generator **share one
storage schema** from the start, discriminated by a `source` field. Two tables would have to be
merged the moment generated pairs need to appear in the same list view as manual ones."

```python
class QAStatus(StrEnum):
    UNREVIEWED = "unreviewed"
    PASS = "pass"
    FAIL = "fail"


class QASource(StrEnum):
    MANUAL = "manual"
    GENERATED = "generated"


class QAPair(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "qa_pairs"

    id: Mapped[uuid.UUID]                       # PgUUID, pk, default uuid4
    project_id: Mapped[uuid.UUID]               # FK projects.id, not null
    created_by: Mapped[uuid.UUID]               # FK users.id, not null

    module: Mapped[str | None]                  # String(120)
    question: Mapped[str]                       # Text
    answer: Mapped[str | None]                  # Text — null until answered (M5)
    reference_answer: Mapped[str | None]        # Text — the expected result
    citations: Mapped[list[dict] | None]        # JSONB, full retrieved set in prompt order
    tags: Mapped[list[str]]                     # ARRAY(String), server_default '{}'
    source: Mapped[str]                         # String(16), QASource
    status: Mapped[str]                         # String(16), QAStatus
    reviewed_by: Mapped[uuid.UUID | None]       # FK users.id
    reviewed_at: Mapped[datetime | None]
    model: Mapped[str | None]                   # String(255) — produced `answer`
    eval_score: Mapped[float | None]            # M5 writes it; M4 only creates it
    last_run_at: Mapped[datetime | None]

    # --- the pending re-run slot (§2.5) ---
    pending_answer: Mapped[str | None]
    pending_citations: Mapped[list[dict] | None]
    pending_model: Mapped[str | None]
    pending_finish_reason: Mapped[str | None]   # String(32), FinishReason
    pending_run_at: Mapped[datetime | None]
```

`status` and `source` are `String(16)`, not native Postgres enums, matching `Message.role` and
`Project.status`: adding a value to a native enum needs a migration and a table lock, and M5 is
likely to want more states. `StrEnum` guards them in Python and `Literal` guards them at the wire
(`.claude/rules/persistence.md`).

`citations` reuses the shape already written by `stream_turn` — the **full** retrieved set in
prompt order, not the cited subset. `docs/PRD.md:298-300` requires this so M5 can score retrieval
independently of generation, and a pair that dropped the ignored chunks would be useless for that.

### 3.2 Indexes

| Index | Serves |
| --- | --- |
| `(project_id, created_at)` | the default list, filtered by project, newest first |
| GIN on `tags` | `tags @> ARRAY[:tag]` containment for the tag filter |
| `created_by` | the creator filter |
| `status` | the status filter, and the grid's most common narrowing |

A partial index on `deleted_at IS NULL` is not added: every table in this codebase filters that
way and none of them carry one, so adding it here alone would be an inconsistency without a
measurement behind it.

### 3.3 Migration

One new Alembic revision, `down_revision = "3a0b796e2274"` (the conversations revision, currently
head). Creates the table, the four indexes, and both foreign keys. `downgrade` drops the table.

### 3.4 Soft delete and cascade

`qa_pairs` carries `deleted_at` through `SoftDeleteMixin` and every query filters it, per
`docs/PRD.md` §5.1.

**Deleting a project soft-deletes its pairs in the same operation** (`docs/PRD.md:340`). This
happens in `ProjectService.delete`, beside the existing Qdrant hard-delete, not in a database
cascade — the existing code already coordinates two stores there and a database-level rule would
be invisible to the reader of that method.

There is **no Qdrant work** for a QA pair. Its `citations` are copies of payload data; it owns no
vector points. The soft-delete-versus-Qdrant rule in `docs/PRD.md` §5.1 is about resources that
own points, and this one does not.

A soft-deleted user's pairs survive, per `docs/PRD.md` §3 — they are instance assets, and
`created_by` continues to point at the deactivated row.

---

## 4. API surface

`backend/app/api/routes/qa_pairs.py`, prefix `/qa-pairs`, with
`backend/app/services/qa_pair.py` and `backend/app/repositories/qa_pair.py` behind it. The
layering follows `.claude/rules/router.md`: one service call per route, no query in a route body,
no policy in the router.

| Route | Gate | Behaviour |
| --- | --- | --- |
| `GET /qa-pairs` | any authenticated | Paginated list. §4.1 |
| `GET /qa-pairs/tags` | any authenticated | Distinct tags across the caller's project scope, for the filter combobox |
| `GET /qa-pairs/export` | any authenticated | `.xlsx`. §6 |
| `GET /qa-pairs/{id}` | any authenticated | Detail |
| `POST /qa-pairs` | any authenticated | Create from a message. §4.2 |
| `PATCH /qa-pairs/{id}` | `created_by` or admin → `403` | `{module?, tags?, question?, referenceAnswer?}` |
| `PUT /qa-pairs/{id}/status` | **any authenticated** | `{status}`. §4.3 |
| `POST /qa-pairs/{id}/rerun` | `created_by` or admin → `403` | SSE. §5 |
| `POST /qa-pairs/{id}/rerun/accept` | `created_by` or admin → `403` | Promote the pending slot. §5.4 |
| `DELETE /qa-pairs/{id}/rerun` | `created_by` or admin → `403` | Discard the pending slot |
| `DELETE /qa-pairs/{id}` | `created_by` or admin → `403` | Soft delete |

**`/tags` and `/export` are declared before `/{id}`.** FastAPI matches in declaration order, so
either one declared after the parameterised route is swallowed as an id and fails with a
malformed-UUID `422` that names nothing useful.

**`403`, not `404`, on the destructive routes.** A QA pair is a shared instance asset, exactly
like a project: `docs/PRD.md:338` gates editing and deleting on `created_by` or admin "same rule
as projects, returning `403`". Existence is deliberately not secret
(`.claude/rules/response-api.md`).

### 4.1 The list route and read scoping

```python
class QAPairListQuery(ListQuery):
    project_id: uuid.UUID | None = None
    module: str | None = None
    tag: str | None = None
    source: QASource | None = None
    status: QAStatus | None = None
    created_by: uuid.UUID | None = None
```

**A subclass of `ListQuery`, never scalars declared beside it.** `.claude/rules/rag.md` records
why, and it is not a style preference: FastAPI flattens a Pydantic model used as
`Annotated[Model, Query()]` into individual query parameters *only while it is the sole query
parameter of the route*. Add one scalar beside it and the flattening stops, the model starts
demanding a literal `?query=`, and every request fails with `{"request": "Field required"}` —
naming a field that appears nowhere in the signature. `ConversationListQuery` is the precedent.

**Read scoping goes through `resolve_project_scope`**, in the repository's query builder, and
nowhere else. `docs/PRD.md` §7's phase-2 readiness criterion is verifiable by grep — "read
scoping happens in exactly one function, confirmed by grep — no route filters projects on its
own" — and a QA list that filtered on `created_by` or on a path parameter would break it even
though phase 1's output would be identical.

`project_id` in the query is a **filter within** the scope, not the scope itself: the repository
intersects it with what the resolver returned, so a phase-2 caller passing a project they cannot
see gets an empty page rather than rows.

Sorting is restricted to a fixed field allowlist (`created_at`, `updated_at`, `last_run_at`,
`module`, `status`), rejecting anything else with `400 INVALID_SORT_FIELD` — the existing code
and error member for this already exist.

### 4.2 Create

```python
class QAPairCreateRequest(ApiModel):
    message_id: uuid.UUID
    module: str | None = None
    tags: list[str] = []
```

The service:

1. Loads the message and its conversation, scoped through `resolve_conversation_owner`. Missing,
   soft-deleted, or someone else's → `404 MESSAGE_NOT_FOUND`. Never `403` (§2.6).
2. Rejects a non-assistant message → `409 ANSWER_INCOMPLETE`.
3. Rejects `finish_reason != "stop"` → `409 ANSWER_INCOMPLETE`.
4. Reads the preceding **user** message in the same conversation as `question`; if there is none,
   `409 ANSWER_INCOMPLETE`.
5. Writes the pair: `project_id` and `citations` and `model` and `answer` from the rows,
   `reference_answer = answer` (§2.3), `source = "manual"`, `status = "unreviewed"`,
   `created_by = actor.id`, `last_run_at = message.created_at`.

Tags are normalised on write — trimmed, lowercased, deduplicated, empties dropped — in the
service, so the filter never has to guess at casing. Same normalisation on `PATCH`.

Duplicate saves of the same message are **allowed**. Refusing would need a unique constraint on
a column that generated pairs never populate, and re-saving an answer with different tags is a
reasonable thing to do.

### 4.3 Status is deliberately ungated

`PUT /qa-pairs/{id}/status` takes `{status}` and is available to **every** authenticated user,
unlike every other write on the resource.

`docs/PRD.md:338` is explicit: "Any user may create and verify a pair. Editing or deleting a pair
requires `created_by` or admin". Verification is a shared judgement about a shared asset — the
point of a team regression set is that a colleague can mark a stale answer as failing without
finding whoever saved it eighteen months ago.

This asymmetry looks like an oversight and will be "fixed" into a `403` by someone eventually.
§10 pins it with a test that asserts a non-owner **succeeds**.

Setting a status writes `reviewed_by = actor.id` and `reviewed_at = now()`. Setting it back to
`unreviewed` clears both.

### 4.4 Error codes

Appended to `ErrorCode` in `backend/app/core/errors.py`. Members are a wire contract — added,
never renamed (`CLAUDE.md`).

| Code | Status | Raised when |
| --- | --- | --- |
| `QA_PAIR_NOT_FOUND` | 404 | No such pair, or soft-deleted |
| `NOT_QA_PAIR_OWNER` | 403 | Caller is neither `created_by` nor admin |
| `MESSAGE_NOT_FOUND` | 404 | No such message, or it belongs to another user's conversation |
| `ANSWER_INCOMPLETE` | 409 | The referenced message is not a finished assistant answer, or the pending run never finished |
| `NO_PENDING_RUN` | 409 | `accept` or `DELETE .../rerun` with an empty slot |
| `EXPORT_TOO_LARGE` | 409 | The filtered set exceeds the export row cap |

`PROJECT_NOT_FOUND`, `PROJECT_NOT_READY`, `EMBEDDING_MODEL_CHANGED`, `INVALID_SORT_FIELD` and
`LLM_UNAVAILABLE` are reused as-is.

---

## 5. The re-run stream

`POST /qa-pairs/{id}/rerun` is the second `text/event-stream` route in the codebase. It is built
by copying the shape of `ask_question` rather than inventing a second one, because
`.claude/rules/rag.md`'s ordering contract is far easier to preserve by mirroring the working
implementation than by re-deriving it.

### 5.1 The pre-flight/stream split

`.claude/rules/rag.md`: once SSE headers are sent the status code is fixed at `200`, so
everything that can legitimately return something else happens first.

`QAPairService.prepare_rerun(pair_id, *, actor) -> RerunContext` performs, in order:

1. Pair exists and is not soft-deleted → else `404 QA_PAIR_NOT_FOUND`.
2. Caller is `created_by` or admin → else `403 NOT_QA_PAIR_OWNER`. Re-running mutates the pending
   slot, so it is a write and is gated like one.
3. Project is readable through `resolve_project_scope` → else `404 PROJECT_NOT_FOUND`.
4. Project is `ready` and has an `embedding_collection` → else `409 PROJECT_NOT_READY`.
5. `project.embedding_model == settings.embedding_model` → else `409 EMBEDDING_MODEL_CHANGED`.

Step 5 is the one that would otherwise fail silently. `.claude/rules/rag.md` states the failure
in full: swap one 768-wide model for another and Qdrant accepts the query, returns its nearest
neighbours in a space the collection was never built in, and the model writes a fluent, cited
answer about noise with no error anywhere. A regression set whose re-runs quietly degrade is
worse than no regression set.

The route then returns a `StreamingResponse` and does nothing else. Like `ask_question`, it is a
route that does two things, and for the same unavoidable reason — all the policy is still in the
service.

### 5.2 The collection comes from the project row

`RerunContext` carries `project.embedding_collection` **verbatim**, and the answerer factory is
called with it. Never recomputed from current settings: the width is probed at worker startup and
is not available in the API process, and a project indexed before a provider switch legitimately
lives in a different collection from the one current settings would name
(`.claude/rules/rag.md`).

### 5.3 The generator

`stream_rerun` lives in `backend/app/services/qa_pair.py` and mirrors `stream_turn`:

- **Its own session**, from the sessionmaker rather than from `Depends`. FastAPI closes `yield`
  dependencies through the request's `AsyncExitStack`, and a persistence guarantee must not rest
  on when that runs relative to a streaming body — least of all on the cancellation path, where
  the request scope is already unwinding.
- **Cleanup in `finally` under `asyncio.shield`.** A client disconnect arrives as
  `asyncio.CancelledError`, and any `await` in a cancelled task raises it again immediately, so
  an unshielded write records nothing at all — losing the partial answer in exactly the case the
  behaviour exists for.
- **The in-flight `anext` is cancelled and awaited *before* the answerer is closed.** Closing a
  generator that is still running raises `RuntimeError`, and that close is what releases the
  concurrency permit. Skipping it leaves later answers queued behind a slot nobody holds.
- **The pending slot is written once, at termination**, not per token. A per-token `UPDATE` is
  thousands of writes for a row nobody reads until it is finished.
- The default `finish_reason` is `disconnected`, set before the loop: reaching the end of the
  generator without a terminator means the client went away.

**Re-runs take the same `get_answer_semaphore` as the Ask screen.** It is an instance-wide bound
on concurrent generation, and a burst of re-runs that could starve someone asking a live question
would be a self-inflicted denial of service on the feature people actually use.

### 5.4 Accept and discard

`POST /qa-pairs/{id}/rerun/accept`:

1. `409 NO_PENDING_RUN` if `pending_run_at` is null.
2. `409 ANSWER_INCOMPLETE` if `pending_finish_reason != "stop"`. A partial run may be read; it
   may never be published (§2.5, and `docs/PRD.md` §4.2's rationale for `finish_reason`).
3. Copies `pending_answer`/`pending_citations`/`pending_model` into `answer`/`citations`/`model`,
   sets `last_run_at = pending_run_at`, clears all five `pending_*` columns.
4. **Resets `status = "unreviewed"`, `reviewed_by = NULL`, `reviewed_at = NULL`.**
5. Returns the updated pair.

Step 4 is a decision, not bookkeeping. A human who marked a pair `pass` vouched for *that text*.
If the text is replaced and the verdict survives, `status` stops meaning "a person read this and
it was right" — which is the only thing it is for, and a stale green badge on a shared regression
set is worse than no badge, because it is trusted.

`DELETE /qa-pairs/{id}/rerun` clears the five columns. `409 NO_PENDING_RUN` on an empty slot.

### 5.5 The ordering contract, on this route too

Unchanged from `.claude/rules/rag.md`, and tested here as well as on the conversation route:

- `citations` is emitted exactly once, and always **before** the first `token` — on every route
  the graph can take, empty on the two that never retrieve.
- Exactly one terminator per stream, `done` or `error`, and every terminator carries a
  `finishReason`.
- Only `Answerer._terminate` constructs a terminator. This route adds no exception to that, which
  is what keeps "exactly one terminator" structural rather than a rule two call sites each have
  to remember.

---

## 6. Export

`GET /qa-pairs/export` returns a real `.xlsx`, built with **`openpyxl`** — a new backend
dependency in `backend/pyproject.toml`.

`.xlsx` over CSV was chosen deliberately by the owner. The three long columns (question, expected
result, result) are multi-paragraph prose; CSV renders them as a single unwrapped line that runs
off the screen, and the point of exporting a regression set is that a person reads it.

### 6.1 Same filters, no pagination

The route takes the **same** `QAPairListQuery`, ignoring `page` and `limit`. You export what you
are looking at. A second filter implementation would drift from the first, and the divergence
would show up as an export that silently disagrees with the screen it was taken from.

Read scoping is the same `resolve_project_scope` call — the export is not a back door around it.

### 6.2 The row cap

A new setting, `qa_export_max_rows`, default `5000`.

`openpyxl` builds the workbook in memory even in write-only mode, so nothing else bounds the
allocation. Over the cap the route returns `409 EXPORT_TOO_LARGE` with the actual count in the
message, so the caller knows how much to narrow by rather than guessing.

Per `CLAUDE.md` this lands in `backend/app/config.py`, `backend/.env.example` (in its group,
default only, no prose) and `docs/configuration.md` (where its meaning lives) in the same change.

### 6.3 The sheet

One sheet, `QA Pairs`. Columns in the grid's order:

Module · Question · Expected result · Result · Status · Tags · Source · Project · Created by ·
Reviewed by · Last run · Created at · Citations

`Tags` joins with `, `. `Citations` joins `path:startLine-endLine` with newlines — the file
references are the most useful thing in the export and a sheet without them cannot be audited
against the repository.

Frozen header row, bold header, explicit widths, and `wrap_text` on the three prose columns.
That formatting is the entire reason `.xlsx` was chosen over CSV, so it is part of the
deliverable rather than a nicety.

`Created by` and `Reviewed by` render names, not UUIDs — the repository joins `users` for the
export query. A spreadsheet of UUIDs is not readable by the person the export is for.

Returned as a `StreamingResponse` over a `BytesIO`, with
`Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` and
`Content-Disposition: attachment; filename="qa-pairs-<date>.xlsx"`.

### 6.4 The proxy has to survive a binary body

`frontend/app/api/[...path]/route.ts` already relays bodies untouched, but nothing currently
exercises it with a non-JSON response. §10 adds a test that `content-type` and
`content-disposition` both survive the hop, because a proxy that quietly re-encodes the body
produces a corrupt file rather than an error, and the failure surfaces as Excel refusing to open
it.

### 6.5 One operator note

Export is a new egress path. The contents are code excerpts from private repositories, and a
spreadsheet on a laptop is outside the network boundary the instance relies on
(`docs/PRD.md` §5, Networking).

This is **not** a threat-model change — `SECURITY.md` already places malicious authenticated
users out of scope, and every user could already read the same content through the UI. But
`.claude/rules/documentation.md` requires `SECURITY.md` to be updated when a new operator
responsibility appears, and "exported spreadsheets leave the instance" is one. One sentence,
under operator responsibilities.

---

## 7. Frontend

Two routes, following the existing `page.tsx` (server, data + metadata) plus `*-screen.tsx`
(client, interaction) split used by every other screen.

### 7.1 `/qa` — the grid

`frontend/app/(app)/qa/page.tsx` + `qa-screen.tsx`.

`PageHeader`, then `ListToolbar` carrying search plus five filters — project, module, tag,
source, status, creator — then the table, then `PaginationFooter`. All three layout components
already exist.

Columns: **Module · Question · Expected result · Result · Status · Tags · Project · Last run ·
actions.** The three prose columns truncate to a single line with the full text in a tooltip;
the row links to the detail page, which is where prose is meant to be read.

The export control is an anchor pointing at `/api/qa-pairs/export?<current filters>`. Same-origin,
so the session cookies ride along and the browser handles the download — no blob assembly, no
object URLs.

### 7.2 `/qa/[id]` — the pair

`frontend/app/(app)/qa/[id]/page.tsx` + `qa-pair-screen.tsx`.

Header: module, status badge, and the actions menu (Edit, Re-run, Delete — the last two hidden
for a caller who is neither `created_by` nor admin, matching `lib/can.ts`'s existing pattern).
Then the question. Then **Expected result** and **Result** side by side: `reference_answer`
inline-editable for the owner, `answer` read-only with the sources panel from
`components/ask/sources.tsx` reused verbatim.

The status control — Pass / Fail / Unreviewed — sits beneath, with `reviewed_by` and
`reviewed_at`, and is enabled for **every** user. It is the one control on the page that is not
ownership-gated, and it should not be tucked into the owner-only actions menu where it would
read as one.

### 7.3 The re-run surface

Pressing Re-run swaps the Result column into a two-up **Stored** versus **New run**, streaming
into the right side through the existing `lib/ask/sse.ts` parser and rendering with
`components/ask/answer.tsx`, `sources.tsx` and `grounding-notice.tsx`.

On `done`, **Save** and **Discard** appear.

**If the page loads with a pending run already stored, it renders immediately with those same two
buttons.** This is the visible payoff for §2.5: a re-run survives a reload, a closed laptop, and
a different browser.

Save is disabled, with the reason shown, when `pendingFinishReason !== "stop"` — mirroring the
server's `409` rather than letting the user discover it by clicking. Save opens a `ConfirmDialog`
stating that the status will reset to unreviewed (§5.4), because a silent reset of a badge
someone deliberately set is the kind of thing that erodes trust in the badge.

Navigating away mid-stream is safe by construction: the server-side write is shielded, so the
partial run is in the pending slot when the user comes back.

### 7.4 Save from the Ask screen

`components/ask/answer.tsx` gains a **Save to QA List** action on assistant messages, enabled
only when `finishReason === "stop"` and disabled with an explanatory tooltip otherwise — the same
condition the server enforces, surfaced before the request rather than after.

It opens a `FormDialog` (the existing shell, which already routes field errors from the `422`
`fields` map) for module and tags, posts `{messageId, module, tags}`, and toasts with a link to
the new `/qa/[id]`.

A dialog rather than a page, per `.claude/rules/forms.md`: two optional fields, no navigation
away from a conversation in progress.

### 7.5 Four things this touches outside the new routes

- **`lib/nav.ts`.** Add `{ title: "QA List", href: "/qa", icon: ClipboardCheck }` to `navItems`
  and delete the comment explaining why `/qa` is deliberately absent — it is the file's own
  record of this milestone not existing yet. Breadcrumbs need no change; `resolveBreadcrumbs`
  reads the same array.
- **`StatusBadge`** is currently typed to `ProjectStatus` and reads project-specific helpers from
  `lib/status.ts`. It becomes a generic `{tone, label}` badge with a thin `ProjectStatusBadge`
  wrapper over it, so QA status reuses the tone classes instead of cloning the file. `pass` →
  `success` (which `docs/design.md:25` already earmarks for "project `ready`, verified QA pair"),
  `fail` → `danger`, `unreviewed` → muted.
- **`ListToolbar`** is search-only today. It gains an optional filter slot. It is already a
  3/4-column responsive grid, so the filters drop into the remaining cells with no layout work.
- **Components to install** by CLI into `components/ui/`, per `docs/design.md:114`'s M4 row:
  `command`, `popover`, `pagination`. `checkbox` and `combobox` are already present.

Both refactors are in files this milestone is already editing, and neither changes behaviour for
existing callers.

### 7.6 Design-system constraints

No `dark:` colour utility anywhere — the token already knows what dark means. No palette utility
(`bg-zinc-50`, `text-slate-600`) — those name a colour rather than a role and do not follow the
theme. `globals.css` is the only file permitted a raw hex value, and this milestone should not
need to add one. Composition is `render={<Component />}`, never `asChild`, which does not exist
on the Base UI base and fails silently.

---

## 8. What the API contract gains

New request/response schemas in `backend/app/schemas/qa_pair.py`, **every one inheriting
`ApiModel`** so `snake_case` attributes ship as `camelCase` keys. A schema on plain `BaseModel`
silently ships `snake_case` and `tests/test_api_model.py` exists to catch it.

- `QAPairListQuery(ListQuery)` — §4.1
- `QAPairCreateRequest`, `QAPairUpdateRequest`, `QAPairStatusRequest`
- `QAPairResponse`, `QAPairDetailResponse` (adds `referenceAnswer`, `citations`, and the
  `pending*` fields), `PendingRunPayload`

### 8.1 The one wire change to the existing models

`DoneEvent.message_id` and `ErrorEvent.message_id` are both `uuid.UUID` and both required today.
Both become `uuid.UUID | None`, emitted as `null` on the re-run route. It is both, not just
`DoneEvent`: a re-run that fails terminates through `ErrorEvent`, which carries the same field
for the same reason, and changing only one would leave the failure path unable to terminate at
all.

A re-run has no message. The alternatives were weighed:

- **Add a nullable `qaPairId` beside it, exactly one always set.** More self-documenting, but
  nothing validates the "exactly one" part, so it is a convention two call sites must remember —
  the shape this codebase avoids elsewhere.
- **Give the re-run its own terminator event type.** Duplicates `Answerer._terminate`, which is
  the single construction point that makes "exactly one terminator per stream" structural.
- **Reuse `messageId` for the pair id.** A lie in a field name, and clients would key on it.

Nullable is the smallest honest change, and no client needs it: the re-run client already knows
the pair id — it is in the URL it posted to. The cost is that the Ask client loses a
non-null guarantee it currently has, on a field it reads on a path where the value is still
always present.

`SSE_EVENT_MODELS` is unchanged. No event is added, so nothing can ship unchecked through the
gap that tuple exists to close.

---

## 9. Configuration

One new setting.

| Setting | Default | Meaning |
| --- | --- | --- |
| `qa_export_max_rows` | `5000` | Rows above which `GET /qa-pairs/export` returns `409` instead of building a workbook in memory |

Lands in `backend/app/config.py`, `backend/.env.example` and `docs/configuration.md` in the same
change (`CLAUDE.md`). Nothing else reads `os.environ`; the setting is injected with `Depends`
like every other.

---

## 10. Testing

Only invariants that fail *silently* earn a test here; the rest is covered by lint and by
FastAPI's own validation.

### 10.1 Backend

**`tests/test_qa_pairs_api.py`**

- The CRUD surface end to end, and the `camelCase` wire shape.
- User B gets `403 NOT_QA_PAIR_OWNER` on `PATCH`, `DELETE`, and `POST .../rerun` against user A's
  pair; an admin succeeds.
- **User B succeeds at `PUT /qa-pairs/{id}/status` on user A's pair.** Asserted explicitly and
  with a comment pointing at `docs/PRD.md:338`, because this asymmetry looks like an oversight
  and will otherwise be "fixed" into a `403`.
- `409 ANSWER_INCOMPLETE` when saving a message whose `finish_reason` is `error`, `timeout`, or
  `disconnected`.
- **`404 MESSAGE_NOT_FOUND` when saving from a message in another user's conversation.** This is
  the one genuinely new security surface in the milestone — a shared resource created from a
  private one — and `404` rather than `403` is the assertion, since a `403` would confirm the
  conversation exists.
- `reference_answer` is seeded from `answer` on create (§2.3).
- Tag normalisation: casing and whitespace collapse, duplicates dropped.
- Sort allowlist: an unlisted field returns `400 INVALID_SORT_FIELD`.
- Deleting a project soft-deletes its pairs, and they disappear from the list.

**`tests/test_qa_rerun.py`**

- Each pre-flight status code, asserted **before** any bytes are sent — including the embedding
  guard, which is the one that fails silently in production.
- The ordering contract: `citations` exactly once and before the first `token`; exactly one
  terminator; the terminator carries a `finishReason`.
- The pending slot is written on `stop`, and on a disconnect mid-stream with
  `pending_finish_reason = "disconnected"`.
- `accept` promotes, clears the slot, and resets `status`/`reviewed_by`/`reviewed_at`.
- `accept` on a non-`stop` pending run returns `409 ANSWER_INCOMPLETE`.
- `accept` and `DELETE .../rerun` on an empty slot return `409 NO_PENDING_RUN`.
- A re-run acquires the same semaphore as `ask_question`.

**`tests/test_qa_export.py`**

- Filters are honoured and match what the list route returns for the same query.
- The row cap returns `409 EXPORT_TOO_LARGE` naming the count.
- The response headers are correct, and the workbook parses back with the expected header row and
  a citations column.

**`tests/test_api_model.py`** needs no edit, but will fail if any new schema forgets `ApiModel`.

**No new `-m model` test.** `.claude/rules/rag.md` requires one when `app/rag/prompts.py`
changes; this milestone does not touch it. Stated here so the next reader does not assume it was
skipped.

### 10.2 Frontend (vitest)

Same principle — the pieces that fail quietly:

- `lib/nav.test.ts` extended for `/qa`, including that it appears for a non-admin.
- `app/api/[...path]/route.test.ts` gains a binary-response case asserting `content-type` and
  `content-disposition` survive the proxy (§6.4).
- The re-run screen's stream reducer against the ordering contract, mirroring the existing
  answer-stream test.
- The save dialog's error routing through the form shell.

---

## 11. Documentation amendments — part of this change, not a follow-up

`.claude/rules/documentation.md` makes these part of the same commit. `docs/PRD.md` takes the
most, because §2 departs from it in five places.

**`docs/PRD.md` §4.3**

- Schema block: `verified: bool` and `verified_by` replaced by `status`, `reviewed_by`,
  `reviewed_at`; `module`, `last_run_at` and the five `pending_*` fields added; the "generated
  pairs only" annotation on `reference_answer` dropped (§2.1, §2.2, §2.3, §2.5).
- User story: "mark a Q&A pair as 'verified correct'" becomes "mark a pair pass or fail against
  its expected result".
- Acceptance criteria: "Any user may create and verify a pair" becomes "…and set its status";
  export added; the create-from-a-message rule and its `409` stated (§2.6).
- Out of scope: **"exporting" removed** (§2.4). Collaborative editing and versioned diffing stay.

**`docs/PRD.md` §4.4** — a line recording that M5's judge writes `status` alongside `eval_score`,
so the column has one meaning whether a human or a model filled it. Without it, M5 re-opens §2.1
from scratch.

**`docs/PRD.md` §6** — the M4 line restated to name the status verdict and the export.

**`docs/PRD.md` §5.1** — nothing to change. `qa_pairs` soft-deletes normally and owns no vector
points, so it is not a third exception.

Then:

- `backend/README.md` — the route table is required to be exhaustive; all eleven routes.
- `docs/configuration.md` and `backend/.env.example` — `qa_export_max_rows` (§9).
- `README.md` — the M4 roadmap checkbox, and the status banner.
- `CLAUDE.md` — the status paragraph (M4 shipped), the module list, the frontend route list, and
  the `/qa` entry in the shipped screens.
- `SECURITY.md` — one sentence on exports leaving the instance (§6.5).
- `.claude/rules/rag.md` — a short section stating that the ordering contract holds on
  `/qa-pairs/{id}/rerun` too, and that the pending slot exists so a client never posts an answer
  back.

**No new rule file.** The one new pattern is the second SSE surface, and `rag.md` already owns
the streaming contract. A thirteenth rule file would also make `CLAUDE.md`'s "Twelve rule files"
stale for no gain.

---

## 12. Known limitations

- **`module` and `tags` overlap** (§2.2). Two ways to categorise the same thing, kept apart only
  by their role in the UI. Revisit once the list has real content.
- **Five `pending_*` columns** (§2.5). One pending run per pair, no history. M5's eval runs are
  the thing most likely to want a `qa_runs` table; that migration is additive.
- **A re-run's diff is visual, not computed.** The screen shows stored and new side by side and a
  human decides. There is no textual diff and no similarity score — scoring is M5's, and a
  character diff of two LLM answers is noise, because generation is nondeterministic and the two
  will differ in wording on every run even when the index has not changed.
- **Nothing detects a stale pair automatically.** A pair whose cited files have since moved looks
  identical to a fresh one until someone re-runs it. Retrieval *is* deterministic, so a
  citation-set comparison would be a reliable drift signal — a "sources moved" badge computed at
  re-run time is the obvious follow-up, and it needs no schema change beyond what §3.1 already
  stores.
- **The export builds in memory.** `qa_export_max_rows` bounds it; a genuinely large instance
  would want a streaming writer or a background job.
- **Duplicate pairs are allowed** (§4.2). Saving the same message twice makes two rows.

---

## 13. Out of scope for M4

- Generated pairs (`source="generated"`) and `eval_score` — M5.
- LLM-graded pass/fail. `status` is human-written in this milestone.
- Run history beyond the single pending slot.
- Any change to the answer graph, its nodes, or its prompts.
- Any change to the access model. `resolve_project_scope` and `resolve_conversation_owner` are
  called, never modified.
- Collaborative editing of a pair, and a versioned diffing UI — still out of scope per
  `docs/PRD.md` §4.3.
- Re-running many pairs at once. Single-pair only; a batch run is M5's eval mode.
- Import. Export is one-way.

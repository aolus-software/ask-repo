# Changelog

All notable changes to AskRepo are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

What each version means for an operator: the **wire contract** — route paths, JSON field names,
and `ErrorCode` values — is what versioning covers. A `MAJOR` bump means one of those changed
incompatibly. Configuration defaults and internal module layout may change in a `MINOR`.

## [Unreleased]

### Added

- **A path picker for QA Checklist modules** (`docs/PRD.md` §2.1, phase 1.1). `GET
  /projects/{id}/indexed-paths` browses the project's indexed file tree one directory at a time
  (`?path=`) or searches all of it (`?search=`), so a `source_path` is picked rather than typed
  from memory. The create-module and edit-module dialogs now render it instead of a bare text
  field, and the field is still typeable for anyone who knows the path already. The read
  enumerates the `file_path` payloads in the project's active generation — no vector search and
  no model call — cached per `(project, activeGeneration)`, so a reindex cannot serve a stale
  tree. It answers `409 PROJECT_NOT_READY` when the project has no index, and `503
  VECTOR_STORE_UNAVAILABLE` when Qdrant is unreachable.
- **`GENERATION_TIMEOUT_SECONDS`** (600), the per-request timeout on the worker's chat
  client. Generation is not interactive and needs a different bound from a question:
  a checklist reduce folds every file's findings into a single structured call and
  legitimately runs for minutes, so the 180-second `CHAT_TIMEOUT_SECONDS` cut it off
  mid-call. That surfaced as `RetryableChatError` with **no HTTP response logged** — the
  request never completed — and the retry ladder then spent its whole budget re-running a
  call that was always going to need longer than it was given, ending at `failed`.
  `CHAT_TIMEOUT_SECONDS` keeps its meaning for the API process, so questions are
  unaffected.
- Four settings bounding that read: `INDEXED_PATH_SCROLL_PAGE_SIZE` (1024),
  `INDEXED_PATH_CACHE_TTL_SECONDS` (300), `INDEXED_PATH_CACHE_MAX_PROJECTS` (32) and
  `INDEXED_PATH_SEARCH_LIMIT` (200).
- **`CHAT_REASONING` and `CHAT_EXTRA_MODEL_KWARGS`**, so an operator can turn off a reasoning
  model's hidden chain-of-thought (issue #26). `CHAT_REASONING=off` reaches all three providers
  `build_chat_model` supports, in each one's own vocabulary; `CHAT_EXTRA_MODEL_KWARGS` is a
  narrower escape hatch, forwarded as `extra_body` on the `openai` branch only, for self-hosted
  OpenAI-compatible servers whose thinking toggle isn't `reasoning_effort`. Both default to
  today's behavior — this is a pure opt-in.

### Fixed

- **`CHAT_TIMEOUT_SECONDS` now bounds every model call, not just the answer stream.** It was
  applied only to the graph's answer nodes, so checklist generation, mock-data generation, and
  the classify and grade nodes fell through to the provider client's own default — ten minutes
  per request for the OpenAI client, times its three built-in attempts. A checklist generation
  whose reduce step stalled therefore sat there for up to half an hour per attempt and looked
  slow rather than broken. The provider client's own retries are now disabled as well
  (`PROVIDER_RETRIES = 0`): the Kafka ladder already owns retrying, and stacking the two
  multiplied the wait and bypassed the failure classifier.
- **A generation that exhausts its retry ladder is now recorded `failed` instead of looping
  forever.** A retryable failure on the *last* attempt went to the dead-letter topic but left the
  module or dataset `generating` with no lease — which is precisely what the reconcile sweep
  reads as an abandoned run. It then re-published the job with a fresh `job_id` the claim cannot
  refuse, so a dead-lettered generation cost a full generation again on every 60-second tick,
  indefinitely. Affected `checklist-modules` and mock-data datasets; project ingestion already
  handled this correctly.
- **A pending retry no longer gets a duplicate job published alongside it.** While a generation
  waited on a retry rung, `defer` dropped its lease entirely — and a `generating` row with no
  lease is exactly what the reconcile sweep reads as abandoned. The sweep waits two minutes and
  the second rung waits ten, so it published a second job, with a fresh `job_id` the claim is
  designed not to refuse: the same module generated twice at once. `defer` now shortens the lease
  to the moment the retry is due instead, which both keeps the sweep away and still lets the retry
  claim the row the instant it arrives. Project ingestion already did this via `renew_lease`.
- **Chat failures are classified again.** `classify_chat_error` matched on the exception's own
  class name, but LangChain wraps every provider failure in a subclass of its own
  (`openai.APITimeoutError` arrives as `OpenAITimeoutError`), so it matched **nothing** from
  either provider and every chat failure fell through to the unclassified path — one retry
  instead of three for a rate limit, and a pointless retry for a rejected key. It now matches any
  name in the exception's MRO, and knows LangChain's provider-agnostic `Model*Error` bases.

### Changed

- **`POST /checklist-modules` now refuses a `source_path` that matches nothing in the project's
  index, with `400 MODULE_PATH_NOT_INDEXED`** — as does `PATCH /checklist-modules/{id}` when it
  changes the path. Previously a typo'd path was accepted with `201` and failed later and
  silently, when the background generation could not match anything under it. Renaming a module
  is unaffected and still needs no index. No new `ErrorCode`: the generate-time check reports
  the same condition under the same name, and it stays, because a reindex can drop the files a
  module was pointed at after it was created.

---

## [1.0.0] — 2026-09-06

First release. AskRepo clones a repository, indexes it into a vector store, and answers
natural-language questions about it with citations — self-hosted, single-tenant, on your own
network.

This version completes **phase 1** as specified in [`docs/PRD.md`](docs/PRD.md) §6: every
milestone from M0 to M5 is built, and the three defects the PRD listed as release blockers are
fixed.

### Added

#### Accounts and access

- Admin-provisioned accounts — no public registration, no email verification, and therefore no
  mail provider anywhere in the stack.
- Login with a stateless 15-minute JWT plus an opaque refresh token, stored hashed so it can be
  revoked, rotating on every use with replay detection by token family.
- Forced password change on first login, enforced by middleware rather than per-route, so a
  route added later is covered without opting in.
- Password policy with a vendored common-password list.
- Login rate limiting backed by Redis, failing open on a Redis outage by design.
- Idempotent bootstrap-admin seeding, run by the container entrypoint on every start.
- A single access resolver (`resolve_project_scope`) through which all read scoping passes —
  the seam that makes per-project RBAC a change to one function body rather than a rewrite.

#### Repository ingestion

- `POST /projects` accepts a repository URL, returns immediately, and indexes in the background.
- Kafka-driven worker: clone → walk → language-aware chunk → embed → Qdrant, across three
  independent retry ladders with dead-letter topics.
- Pluggable embedding providers: Ollama, OpenAI, Voyage. Vector width is **probed at startup**,
  never declared, and becomes part of the Qdrant collection name so a provider switch targets a
  different collection instead of corrupting the current one.
- Race-safe database leases as the deduplication boundary, since Kafka delivers at least once.
- A reconcile sweep that recovers jobs the broker never received and jobs whose worker died.
- Reindex as a **generation swap**: new vectors are written under an incremented generation
  while the old one still serves, the pointer flips only on success, and a reindex that fails
  part-way leaves the previous index intact and still answering.
- Personal access token support, encrypted at rest.
- The cloned working copy is deleted after indexing — `/data/repos` is scratch space.

#### Dev Knowledge (question answering)

- Cited answers over an indexed project, streamed token by token over Server-Sent Events.
- Conversations private to the user who had them, with no admin bypass.
- A LangGraph state machine rather than a chain: intent routing (codebase question /
  conversational / out of scope) before retrieval, then a corrective loop where a grader judges
  the retrieved excerpts and re-searches with a better query when they fall short.
- The critique grades **retrieval, not the finished answer**, so streaming is unaffected.
- Grounding checks surfaced to the user: a file the answer named that no excerpt contained, and
  an answer that cited nothing.
- No evidence, no generation — if nothing clears the relevance floor the model is not called at
  all and a fixed refusal is streamed instead.
- Every helper node degrades rather than failing the turn; the grader can never be the reason a
  question goes unanswered.

#### QA Checklist

- Name a module over an indexed repository and generate test cases with expected results
  grounded in the code. The generator **scrolls the index rather than searching it**, so it can
  report which files it covered and which it skipped.
- Nothing generated enters the checklist unreviewed: generation and the refinement chat both
  write a *pending change set*, and apply is the only path that writes rows.
- A shared per-module refinement chat that proposes further change sets, on the same answer
  graph and the same streaming contract as Dev Knowledge.
- Human-recorded pass / fail / blocked results, open to every authenticated user — a tester must
  be able to record what they observed without being able to rewrite what was expected.
- `status` and `current_result` are outside what a generated operation may write, enforced by an
  explicit column allowlist.
- Staleness flagging when the project has been re-indexed since the checklist was generated.
- `.xlsx` export.

#### Mock Data Generator

- For a QA Checklist module, a grounded sample dataset built from that feature's actual schema —
  it fails rather than inventing fields when no schema-shaped code is found.
- Its own tables, status and lease, independent of the checklist's, so one failing does not mark
  the other failed.
- Refined through the same chat → change set → apply discipline.
- JSON and `.xlsx` export.

#### Model providers

- Three chat providers: Ollama, Anthropic (native), and any OpenAI-compatible endpoint —
  OpenRouter, DeepSeek, Kimi, Groq, Together, or self-hosted vLLM — by configuration alone.
- A boot-time structured-output capability probe in both processes. An instance configured with
  a model that cannot do structured output **fails to start**, naming that as the cause, rather
  than failing on its first generation.
- A chat-error taxonomy separating terminal failures (rejected key, unknown model,
  context-length rejection) from retryable ones (rate limit, outage, connection blip), so a
  provider that has already said no does not burn the retry ladder.
- `CHECKLIST_MAX_FILES_PER_JOB` as a per-run spend bound, degrading to the first N files sorted
  by path and reporting the rest as skipped.
- Switching the answering model is configuration, not a migration: no re-index, no change to
  stored citations.

#### Web interface

- Sign-in, forced password change, dashboard, projects (list, detail, create, re-index, delete),
  Dev Knowledge with streamed answers and a live sources panel, admin user management, the QA
  Checklist module list and grid with chat and review panels, and the Mock Data tab.
- Next.js acts as a **backend-for-frontend**: the session lives in httpOnly cookies it owns, and
  no token is ever readable by a script on the page.
- The answer stream is piped through the proxy unbuffered, preserving `text/event-stream`.
- Light and dark themes through semantic tokens.

#### Operations

- Docker Compose for development and a standalone production compose file — never an overlay,
  because Compose merges volumes by target path and would keep development bind-mounts over
  `/app`.
- Multi-stage production images for backend and frontend.
- `make` targets for setup, infra, dev, checks, and the production deploy path.
- 71 documented settings, each with what it does and what to change before production.

### Security

- Repository URLs are validated as a control, not input hygiene: https-only, host allowlist, and
  private-address rejection at connect time — because URLs are fetched from **inside** a private
  network where internal names resolve.
- Everything derived from clone output is scrubbed before it reaches a stored error or a log
  line, since a personal access token is embedded in the clone URL.
- Retrieved code is treated as untrusted input and delimited in the prompt. This is mitigation,
  not a boundary — what bounds the damage is that the model has no tools, no write access and no
  network reach.
- Soft-deleted rows keep `deleted_at`; the matching Qdrant points are **hard-deleted in the same
  operation**, because vector points have no such column and a query-time filter would be one
  forgotten call away from serving deleted content.
- `403` and `404` are chosen deliberately: `403` where the caller may see the resource but not
  act on it, `404` where they should not learn it exists.
- No secret appears in any log, traceback, or API response.

### Fixed

Three defects [`docs/PRD.md`](docs/PRD.md) §7 listed as release blockers, all fixed before this
tag:

- **Re-index appeared to do nothing.** The route enqueued the job but never raised
  `reindex_in_progress`, so the response and every later poll described an idle project.
- **A regenerated checklist module still reported `stale`.** This turned out to be the same
  defect: because nothing showed a re-index was running, a generation started during one
  recorded the generation that run was about to supersede and delete. Both generation paths now
  refuse with `409` while a re-index is in flight; questions and refinement chats deliberately
  still work, since they record nothing.
- **A checklist chat reply disappeared after navigating away and back.** The backend had
  persisted the turn correctly; the panel served a stale cached list on remount.

### Known limitations

None of these is a defect. Each is a documented, deliberate scope decision:

- **Every authenticated user can read and query every project.** This is intended — see
  [`docs/PRD.md`](docs/PRD.md) §4.1 and [`SECURITY.md`](SECURITY.md). Per-project RBAC is
  phase 2, and the access resolver exists so it lands as one function body.
- **Conversations are private; checklists and mock data are shared.** Sharing a conversation is
  out of scope for this version.
- **No self-service password reset and no notifications.** Both need a mail provider, which
  would be this instance's first outbound network path — a decision deferred to phase 2.
- **Not internet-facing.** AskRepo assumes a private network and trusted, authenticated users.
  [`SECURITY.md`](SECURITY.md) puts malicious authenticated users outside the threat model.
- **A hosted answering model sends retrieved source code to a third party** on every question.
  That is an operator's trade to make per instance, not a default.

---

[Unreleased]: https://github.com/aolus-software/ask-repo/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/aolus-software/ask-repo/releases/tag/v1.0.0

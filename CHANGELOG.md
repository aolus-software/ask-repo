# Changelog

All notable changes to AskRepo are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

What each version means for an operator: the **wire contract** — route paths, JSON field names,
and `ErrorCode` values — is what versioning covers. A `MAJOR` bump means one of those changed
incompatibly. Configuration defaults and internal module layout may change in a `MINOR`.

## [Unreleased]

Nothing yet.

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

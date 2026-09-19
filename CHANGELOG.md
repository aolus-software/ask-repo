# Changelog

All notable changes to AskRepo are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

What each version means for an operator: the **wire contract** — route paths, JSON field names,
and `ErrorCode` values — is what versioning covers. A `MAJOR` bump means one of those changed
incompatibly. Configuration defaults and internal module layout may change in a `MINOR`.

## [Unreleased]

## [2.1.0] — 2026-09-19

Append-only audit trail (`docs/PRD.md` §2.1, phase 2.2): who did what, never the secret involved
and never the content. Alongside it, two fixes to controls that were quietly not doing their job
— the per-caller login limit, which had become one bucket for the whole instance, and light
mode, which had been rendering without elevation. **Nothing here breaks the wire contract**: one
`ErrorCode` was added and none renamed or removed, no route path changed, and no JSON field was
dropped.

### Added

- **Two read routes, both admin-only.** `GET /audit-events` returns a page of events newest
  first, filterable by `eventType`, `actorUserId`, `projectId`, `outcome`, `occurredFrom` and
  `occurredTo`; `GET /audit-events/{id}` returns one with its full `details` payload, its
  `ipAddress`, and a `current` block saying whether the actor is still active and the target
  still exists. There is deliberately **no route that writes one** — that is how append-only
  shows up on the wire rather than only in the schema. New `ErrorCode`: `AUDIT_EVENT_NOT_FOUND`.
- **One Postgres table, `audit_events`** (migration `9d97a74a24fa`). It is the only table in the
  app carrying neither the timestamp mixin nor the soft-delete mixin, and both omissions are the
  mechanism: with no `deleted_at` there is no soft-delete path to reach these rows through, and
  `updated_at` has no business on a row that is never updated. Every write and every export in
  the app now records one of **37 event types** — auth, accounts, projects, memberships and
  roles, checklist modules and items (including the destructive bulk result-clear), change-set
  applies and discards, mock data, and the two exports. The `details` payload is an allowlist per
  event type rather than a diff of changed columns, so a new column is invisible to the trail
  until somebody names it.
- **Conversation creation and deletion are audited as metadata — a user-visible change to what an
  administrator can see.** `conversation.created` and `conversation.deleted` record the actor,
  the project and the time. An administrator can therefore see that a colleague opened or deleted
  a conversation against a given project, and when. **They still cannot see its title or any
  message:** `targetLabel` is `NULL` for a conversation, the ask route is not audited at all, and
  no administrator bypass was added anywhere under `/conversations` — every miss there is still
  `404`. This is a deliberate, narrow amendment to the previously unqualified privacy statement
  in `docs/PRD.md` §4.2, made and recorded in the same change.
- **`AUDIT_RETENTION_DAYS`** (default `0`, meaning keep forever). A positive value is a window the
  worker's existing 60-second reconcile tick enforces by hard-deleting rows older than it. The
  single delete path takes a cutoff and nothing else — no actor filter, no event-type filter — so
  an operator sets a window and nobody erases a row.
- **Two admin screens**, `/settings/audit` (the filterable event list) and
  `/settings/audit/[eventId]` (one event, its before/after change list and its live `current`
  block).

- **Read an audit event without leaving the list.** Each row on `/settings/audit` gains a **View**
  action that opens the event in a dialog, keeping the filters and the scroll position.
  `/settings/audit/[eventId]` remains, and remains the linkable one — a dialog has no URL to put in
  a ticket.

### Fixed

- **Light mode has elevation again.** `--muted` and `--accent` were `#f1f5f9` in light — the same
  value as `--background` — so every surface drawn with `bg-muted` or `bg-accent` painted the page
  colour over the page colour and simply did not appear, while dark mode rendered the identical
  markup as panels. Both now sit one step down the ramp at `#e2e8f0`, mirroring dark, where
  `muted` and `border` are likewise one value. What comes back in light: the question panel and
  avatar on the Ask screen, fenced and inline code in an answer, the highlight on a cited source,
  the selected conversation and row hovers in the conversation rail, loading skeletons, ghost and
  outline button hovers, progress tracks, selected and hovered table rows, and the keyboard-focus
  highlight in menus and comboboxes. `--sidebar-accent` moved with them so the nav's hover is not
  the one weak highlight left in the UI. No component changed — every call site was already using
  the right token.

- **Secondary text in light mode now meets WCAG AA.** `--muted-foreground` was `#62748e`, which
  read 4.35:1 on the page and 4.76:1 on a card — both under the 4.5:1 threshold for normal text,
  and 3.86:1 on the darker `muted` surface above. It is now `#45556c`: 6.15–7.58 across page,
  card and muted, the band dark mode was already in at 5.56–7.67. This darkens every timestamp,
  helper line, placeholder and secondary paragraph in light mode — 112 call sites — which is the
  visible half of the change.

- **The per-caller login limit bounds a caller again, and the audit trail records one.** Every
  backend request leaves from the Next server, and the backend-for-frontend forwarded no
  `X-Forwarded-For`, so the per-address limit held one key for the whole instance: five logins a
  minute for everyone, counted on successes too, so the sixth colleague signing in within a
  minute got `RATE_LIMITED` having done nothing wrong — and onboarding a batch of accounts drove
  the same collapse on `POST /auth/change-password`. The security half was the mirror image: one
  attacker had the whole instance's allowance to themselves. The BFF now relays the header its
  own reverse proxy set, on every path that reaches the API. It appends nothing of its own, so
  `TRUSTED_PROXY_HOPS` still counts only the proxies that append an entry — one Caddy is still
  `1`, unchanged. Alongside it, `audit_events.ip_address` stopped being the proxy for every user:
  the audit path took the direct peer while the limiter was `X-Forwarded-For`-aware, and both now
  resolve the caller through the one implementation in `app/core/rate_limit.py`. That address is
  what `docs/PRD.md` §3.4 leans on to keep an enumeration attempt visible as a pattern from one
  host, given a failed login against an unknown address deliberately stores no email.

- **A To date of today now finds today's events.** `<input type="date">` submits a bare calendar
  day, which parsed to midnight, so `occurredTo=<today>` excluded everything actually recorded that
  day — the obvious From=today/To=today search returned an empty page. A value with no time
  component is now treated as the whole day. The remaining UTC-versus-local-day edge is documented
  rather than papered over: fixing it needs the operator's timezone, which the endpoint is not
  given.
- **A bulk-operation filter no longer renders as `[object Object]`** on the event detail screen —
  which is precisely the row an operator opens after a bulk result-clear erased recorded
  observations.
- **The audit filter row is usable.** All four controls and both date pickers were rendering
  clipped to a few characters ("All e", "dd/"), because the filter row declared a grid of its own
  inside a single cell of the toolbar's grid. Each control now gets its own cell, and the two
  selects became searchable comboboxes — 37 event types is past the point where a menu that does
  not narrow is usable.
- **Applying a proposed removal to a QA checklist no longer fails with a server error.** The apply
  had already committed, so the item really was deleted while the response reported failure.
- **Four surfaces no longer report a failed request as "there is nothing here":** a project's
  Members tab, the Ask conversation rail and its project filter, and the Mock Data tab. Each now
  distinguishes loading, empty and failed, with a retry.
- **Generating a checklist from the module list's row menu reports what happened.** It previously
  succeeded or failed in silence, and was not gated on the generate permission — so a user without
  it saw an enabled action whose refusal went nowhere.

### Changed

- **Success toasts use one voice.** Eleven that interpolated a name (`"askrepo deleted"`,
  `"Password reset for ada@example.com"`) now read as bare phrases (`"Project deleted"`,
  `"Password reset"`), matching the other nineteen.
- **The audit table's columns follow the documented list order** — identity, status, then
  timestamps — so it reads the same way as `/settings/users` and `/settings/roles`.

## [2.0.0] — 2026-09-16

Per-project role-based access control (`docs/PRD.md` §2.1, phase 2.1). Projects are no longer
shared with every account on the instance: each one has members, each member holds one role, and
each role carries a set of named permissions. **This changes the wire contract in ways a client
can observe** — see Changed and Removed below before upgrading.

### Added

- **Project membership routes.** `GET /projects/{id}/members` lists everyone with a role on a
  project (needs `membership.read`, which `viewer` holds). `POST /projects/{id}/members` grants a
  role (`201`; `membership.grant`), `PATCH /projects/{id}/members/{userId}` changes one
  (`membership.grant`), and `DELETE /projects/{id}/members/{userId}` revokes it (`204`;
  `membership.revoke`). New `ErrorCode` values on this surface: `MEMBERSHIP_NOT_FOUND`,
  `MEMBERSHIP_EXISTS`, `INSUFFICIENT_ROLE` and `LAST_OWNER`.
- **Role management routes**, all admin-only. `GET /permissions` returns the permission
  catalogue grouped for the matrix editor; `GET /roles` lists every role with its permissions and
  `memberCount`; `POST /roles` creates a custom one (`201`); `PATCH /roles/{id}` renames it
  and/or replaces its permission set; `DELETE /roles/{id}` soft-deletes one nobody holds (`204`).
  New `ErrorCode` values: `ROLE_NOT_FOUND`, `ROLE_NAME_EXISTS`, `ROLE_IN_USE` and
  `SYSTEM_ROLE_IMMUTABLE`. `viewer`, `editor` and `owner` are system roles and refuse renaming,
  deletion and re-permissioning — without that, unchecking `membership.grant` on `owner` would
  leave nobody on the instance able to grant membership, including to undo it.
- **`role` and `permissions` on `ProjectResponse`** — the caller's own role name on that project
  (`null` for an admin with no membership) and their effective permission values, so a client can
  hide controls it would be refused. The hiding is cosmetic; the server-side check is the control.
- **`GET /projects?ownerless=true`**, admin-only (`403 ADMIN_REQUIRED` otherwise), narrowing the
  list to projects with no live owner. The RBAC migration backfills one `owner` membership per
  project from `created_by` and deliberately does not fabricate one where that account was
  already deactivated, so this filter is how an admin finds those and grants someone `owner`. It
  narrows the access resolver's scope rather than replacing it, so it can only ever show less
  than the caller could already read.
- **`409 LAST_OWNER` on `DELETE /users/{id}`.** Deactivating an account that is the only live
  owner of one or more projects is refused, and the error body is widened with a `projects` array
  of `{id, name}` naming the blockers — "no" alone tells an admin nothing about what to fix. This
  is the only route in the API whose error body carries more than `{code, message}`, and it is
  declared as its own response model so `/docs` and generated clients describe it accurately.
- **`python -m app.cli restore-system-roles`**, a new CLI command. It reconciles `viewer`,
  `editor` and `owner` back to their built-in permission sets and bumps the grant-cache epoch.
  For an instance whose seed was damaged by direct SQL or a partial restore; it is not part of
  the container entrypoint.
- **`GRANT_CACHE_TTL_SECONDS`** (default `300`). Each user's project grants are read through a
  Redis cache, since the middleware needs them on every authenticated request. The TTL is a
  **backstop, not the invalidation mechanism**: a membership change evicts that user's key and a
  role-permission change bumps an epoch that invalidates every snapshot at once. A Redis outage
  is not a lockout — the cache falls back to querying Postgres.
- **Three Postgres tables** — `roles`, `role_permissions`, `project_memberships` — added by
  migration `58f7e042f75a`, which also seeds the three system roles and runs the `created_by`
  backfill described above.
- **UI:** a **Members** tab on `/projects/[id]` (grant, change role, revoke) and admin role
  management at `/settings/roles` with a permission-matrix editor at `/settings/roles/[id]`.
  Project, checklist and mock-data controls are now hidden from the server-sent permission set
  rather than from a client-side ownership rule.

### Changed

- **BREAKING — a non-member now gets `404 PROJECT_NOT_FOUND` on every project route.**
  Previously every authenticated user could read every project, and the destructive routes
  (`DELETE /projects/{id}`, `POST /projects/{id}/reindex`) refused a non-creator with `403
  NOT_PROJECT_OWNER` because project existence was deliberately public. It is not public any
  more: once projects are reachable only through membership, "you may not see this" and "this
  does not exist" are the same answer, and a `403` would confirm a private repository exists to
  anyone who can guess an id. A caller who **is** a member but whose role is too low gets `403
  INSUFFICIENT_ROLE` instead — they can already see the project in their own list, so a `404`
  there would contradict what the UI just rendered. Administrators pass every project permission.
- **BREAKING — `GET /projects` and every list scoped by project now return fewer rows.** Lists of
  projects, checklist modules, checklist items, mock data and conversations are scoped to the
  caller's memberships. An existing instance is unaffected in practice on the first upgrade,
  because the migration grants each project's creator `owner` — but any account that was relying
  on instance-wide visibility loses it.
- **Destructive and role-sensitive operations gate on a permission, not on `created_by`.**
  `created_by` is now purely attribution: the migration read it once to seed memberships, and no
  check consults it afterwards. Reindex needs `project.reindex`, delete needs `project.delete`,
  module create needs `module.create`, module edit/delete need `module.edit` / `module.delete`,
  triggering checklist or mock-data generation needs `generate.run`, applying or discarding a
  change set needs `changeset.apply`, checklist item edits need `item.edit`, recording a result
  needs `result.record` (held by every system role, `viewer` included), and mock-data record
  editing needs `mockdata.edit`.
- **`AuthContextMiddleware` now loads project grants alongside the user row** on every
  authenticated request. The user row is deliberately still read from Postgres uncached, because
  deactivating an account must end its sessions immediately.
- Conversations are unchanged: still private to one user, still `404` on every miss, still with
  no administrator bypass. The permission catalogue contains no `conversation.*` member on
  purpose, which is what makes the admin bypass elsewhere safe.

### Removed

- **BREAKING — `NOT_PROJECT_OWNER`, `NOT_CHECKLIST_OWNER` and `NOT_MOCK_DATA_RECORD_OWNER` are
  gone from `ErrorCode`.** These named a `created_by`-based refusal that no longer exists; a
  client switching on them should read `INSUFFICIENT_ROLE` (a member whose role is too low) or
  `PROJECT_NOT_FOUND` (a non-member) instead. `ErrorCode` values are a wire contract, so this is
  a breaking removal rather than a rename.

## [1.1.0] — 2026-09-13

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
- **The account menu crashed on every open with an uncaught Base UI error** (`Menu.GroupLabel`
  requires a `<Menu.Group>` ancestor, which `DropdownMenuLabel` never provided). Fixed by
  dropping the profile header from the menu — it is now sign-out actions only
  (`Log out` / `Log out everywhere`); the profile display and self-service change-password entry
  return once there is a settings page for them to live on. The forced first-login
  `/change-password` route is unaffected.
- **A batch of frontend consistency fixes from a full-app UI audit** (`docs/ui-audit-findings.md`,
  `/audit-ui`). The user-visible ones: a failed list or detail request (backend down, a dropped
  connection) no longer renders as "nothing here" or "not found" — both now show a retry, and a
  private conversation is never told it does not exist over a network blip. The checklist and
  mock-data refinement chats now show the same grounding warnings and "what the model is doing"
  phase indicator the Ask screen always has, so an uncited or invented proposal on the shared
  checklist no longer arrives with no warning at all. Deleting a mock-data record now confirms
  first, like every other destructive action. Error banners (`Alert`'s `destructive` variant)
  reliably colour their message text instead of leaving it grey inside a red border. A dozen
  smaller inconsistencies also closed: duplicated page headers and empty states consolidated
  into shared components, one status→colour mapping for checklist modules and user roles, the
  auth flow's two screens no longer double in width between them, and `docs/design.md`'s radius
  and component-inventory sections corrected to match the code.
- **The Ask screen's conversation list was unusable on a phone.** It stacked inline above the
  page content with a fixed-height scroll area sized for a full sidebar, so a two-conversation
  account showed most of a screen of empty space before the actual composer, with no way to get
  past it faster than scrolling. The list is now a collapsed-by-default drawer on mobile, opened
  by a "Conversations" button, with the fixed height removed entirely. The desktop sticky
  sidebar is now collapsible too — a toggle shrinks it to a slim strip and back, remembered per
  browser.
- **Login had no placeholder text on either field.** `you@example.com` and a password hint are
  now shown.
- **The QA Checklist's test-case grid was the one table in the app with no `Card` behind it**,
  so it showed the page background through it instead of `bg-card` — visibly different from
  every other table. `.claude/rules/design-system.md` §11 now states this as a rule: every
  `<Table>` sits inside a `Card`, with no carve-out for a grid on a detail-page tab.

### Changed

- **The conversation view — Ask, and both refinement chats — no longer looks flat.** Neither
  Claude.ai nor ChatGPT bubbles the assistant's reply; both anchor each turn with a small role
  icon instead. The assistant's turn now gets the same treatment here, live while it streams and
  once it is stored, and a user's own question can be collapsed to one line with a click — useful
  for a long question or a pasted block of code without losing your place in the conversation.

- **Every backend process now logs with a UTC timestamp and a service tag.** The API, the worker,
  the CLI and Alembic each configured logging on their own and none emitted a timestamp, so a
  line in `make dev` — which interleaves the API and the worker into one terminal — carried
  neither a time nor any indication of which process wrote it, and reconstructing the order of a
  Kafka redelivery meant querying Postgres and Kafka directly. One `configure_logging` in
  `app/core/logging.py` now serves all four: `2026-09-13T02:33:36.949Z INFO     api
  uvicorn.error: Started server process`. UTC because Kafka records epoch milliseconds and every
  Postgres column is `timestamptz` in UTC, so the three line up without arithmetic. Uvicorn's own
  startup and access lines are included — they carry private handlers with `propagate = False`
  and were otherwise the only untimestamped lines left. **The access log moves from stdout to
  stderr** as a result, which is where every other line in these processes already went; an
  operator splitting the two streams is the one case that needs attention. No new configuration.

  Uvicorn is now started with `--log-config logging.json` everywhere it is started — the
  `Makefile`, both backend Dockerfiles, and the documented manual command. Under `--reload`
  uvicorn runs a reloader parent that never imports the app, so nothing in application code can
  reach it and its startup lines were the last ones without a timestamp. The file names
  `app.core.logging.build_formatter` as its formatter factory rather than restating the format,
  so the two paths cannot drift. **A uvicorn started without the flag still timestamps
  everything except those reloader lines.**

- **The QA Checklist module screen keeps its refinement chat and its pending proposal in side
  drawers**, opened from `Refine` and `Review N changes` in the action row, on both the Test Plan
  and Mock Data tabs. They used to render on the page, the proposal above the grid and the chat
  that produced it below — so accepting a proposal meant scrolling back past the whole checklist,
  and the composer disabled itself for a reason (one pending change set per module) that was off
  screen and therefore read as the UI being broken. The grid now keeps the full width. Each
  drawer's left edge drags to resize, by pointer or with the arrow keys when the handle is
  focused, and the width is remembered per drawer in `localStorage` — closing a drawer while an
  answer is streaming still stops that answer, and the partial reply is persisted and labelled
  as interrupted, unchanged from before.

- **The frontend's `middleware.ts` is now `proxy.ts`**, following Next 16's rename of the file
  convention — the exported function is `proxy` rather than `middleware`. No behavioural change:
  the same session gate runs on the same `matcher`, and navigations still refresh there while
  browser fetches refresh in the API proxy at `app/api/[...path]`. Operators are unaffected; this
  is noted only because "the proxy" now names two different files, and the docs distinguish them
  as `proxy.ts` (Next's request gate) and the API proxy (the forwarding route).

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

[Unreleased]: https://github.com/aolus-software/ask-repo/compare/v2.1.0...HEAD
[2.1.0]: https://github.com/aolus-software/ask-repo/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/aolus-software/ask-repo/compare/v1.1.0...v2.0.0
[1.1.0]: https://github.com/aolus-software/ask-repo/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/aolus-software/ask-repo/releases/tag/v1.0.0

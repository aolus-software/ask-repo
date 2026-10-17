# Audit findings

The standing record of **open** backend and architecture findings, written by `/audit-flow`,
plus each sweep's verified-correct notes so the next sweep can tell "clean" from "not audited".
A finding that has been fixed moves, verbatim, to
[`audit-finding-solved-logs.md`](audit-finding-solved-logs.md). A number cited below that is not
in this file (§1.1, §9.1 and so on) is there.

**Sweeps:** 2026-09-19 (at `f902f4c`, phase 2.2 branch), 2026-09-27 (at `5b43564`, `main`) and
2026-10-04 (at `df7594e`, `main`). All three were read-only. The first two were each followed by a
separate, explicitly requested fix pass; the third has had none.

**Re-verified 2026-10-17**, still at `df7594e` (no application code had changed). Every open
finding was re-checked against the code. None was refuted. §8.5 and §8.6 were promoted from
SUSPECT to CONFIRMED, and §9.31 stays SUSPECT. §2.2 was corrected and retitled: its original count
and one citation were wrong. Line citations were updated wherever code had been misquoted.
Overstatements were narrowed in §1.3 (which tests are loose), §3.2 (messages have no soft delete
of their own), §5.1 (the leak is bounded to about a minute), §7.1 (what the rule actually
requires), §8.1 (the timeout has to be added, not moved) and §8.2 (the repeat stops once a worker
claims the row).

**Ground truth:** [`PRD.md`](PRD.md), which outranks everything else, then `CLAUDE.md`, then
`.claude/rules/*.md`, then [`SECURITY.md`](../SECURITY.md). The rules outrank the code.

**Severity:** 🔴 bug (wrong behaviour reachable today) · 🟠 inconsistency / latent risk ·
🟡 hygiene · 📄 doc.

**Evidence:** every finding is CONFIRMED (the path was traced end to end and the trigger can be
named) or SUSPECT (the shape looks wrong but something is unverified — what, and what would
settle it, is stated).

## Open findings

Every finding from the 2026-09-19 and 2026-09-27 sweeps has been fixed and is in
[`audit-finding-solved-logs.md`](audit-finding-solved-logs.md). Everything below was raised on
2026-10-04 and is still open; what was fixed on 2026-10-17 is in the log.

| # | Finding | Severity | Raised |
| --- | --- | --- | --- |
| §2.2 | Two services flatten the project scope into a raw id list, and the single-point grep cannot see it | 🟡 | 2026-10-04 |
| §5.1 | Deleting a project mid-run can leave live eval results under a deleted run | 🟡 | 2026-10-04 |
| §7.1 | Four eval routes do not declare `422` | 🟡 | 2026-10-04 |
| §7.2 | Eval, feedback and activity lists accept `sort`/`search` and ignore them | 🟡 | 2026-10-04 |
| §7.3 | An eval set can be created with a whitespace-only name | 🟡 | 2026-10-04 |
| §8.3 | A failed eval run reports zero tallies and no finish time | 🟡 | 2026-10-04 |
| §8.4 | The eval set generator never checks that it still holds its lease | 🟡 | 2026-10-04 |
| §8.5 | A resumed eval run overwrites its own provenance stamp | 🟡 | 2026-10-04 |
| §8.6 | Eval requests audit after the publish, unlike reindex | 🟡 | 2026-10-04 |
| §9.17 | `HOST` and `PORT` are settings nothing reads | 🟡 | 2026-10-04 |
| §9.19 | The "project is indexed" guard exists in three copies | 🟡 | 2026-10-04 |
| §9.20 | The lease and heartbeat mechanism is copied across five repositories | 🟡 | 2026-10-04 |
| §9.21 | Four dead `STRANDED_AFTER_SECONDS` constants | 🟡 | 2026-10-04 |
| §9.22 | Eval does not normalise `sourcePath` the way checklist modules do | 🟡 | 2026-10-04 |
| §9.18 | `APP_VERSION` defaults to `0.1.0` on a 2.2.0 release | 📄 | 2026-10-04 |
| §9.23 | `docs/README.md` and `docs/architecture.md` carry stale counts | 📄 | 2026-10-04 |
| §9.24 | `docs/codebase.md`'s tree misses modules | 📄 | 2026-10-04 |
| §9.25 | `backend/README.md`'s layout and worker description are stale | 📄 | 2026-10-04 |
| §9.26 | `docs/PRD.md` §6 does not record Phase 2.6 as shipped | 📄 | 2026-10-04 |
| §9.27 | `docs/notifications.md` carries an "in progress" banner | 📄 | 2026-10-04 |
| §9.28 | The eval harness is missing from `docs/langfuse.md` and the timeout docs | 📄 | 2026-10-04 |
| §9.29 | `CHANGELOG.md` `[Unreleased]` has duplicate headings and misfiled entries | 📄 | 2026-10-04 |
| §9.30 | Stale comments in the feedback schema and the audit coverage test | 📄 | 2026-10-04 |
| §9.31 | `PROMPT_VERSION` changes when a non-answer prompt changes (SUSPECT) | 📄 | 2026-10-04 |

## Top priorities (2026-10-17)

Both 🔴 bugs and all three 🟠 findings from 2026-10-04 were fixed on 2026-10-17, along with §3.3,
and are in the log. Everything still open is hygiene or documentation.

1. **One owner decision is waiting: §9.31.** One prompt version is stamped on every vote, every
   model call and every eval run. Hashing only the answer prompts (the option first chosen) would
   stop checklist, mock-data and judge prompt edits from moving the version on the records that
   depend on them. Recommended instead: a version per feature.
2. **The eval job edge cases** (§5.1, §8.3–§8.6): about a minute of orphan results after a
   mid-run project delete, a failed run's empty tallies, a generator that never checks its lease,
   a resumed run's overwritten stamp, and audit-after-publish ordering.
3. **The response-contract gaps** (§7.1–§7.3), the duplication (§9.19–§9.22), and the scope
   plumbing in two services (§2.2).
4. **The documentation** (§9.18, §9.23–§9.30), in particular §9.26: the PRD still does not record
   Phase 2.6 as shipped, and must before a release is cut.

---

# Sweep 2026-09-19

## §1 Access control — verified correct (its two findings, §1.1 and §1.2, are resolved)

**What was checked.** `backend/app/core/access.py` in full; every mutating method in
`project.py`, `checklist_module.py`, `checklist_item.py`, `mock_data_dataset.py`,
`mock_data_change_set.py` and `membership.py`; the route signatures in `users.py` and
`audit_events.py`; and the forced-password-change gate in `backend/app/core/middleware.py`.

**What holds.**

- Every destructive and role-sensitive operation gates on a named `Permission` value through
  `require_permission`. A grep for `created_by` used as a comparison — in both directions, and
  under variable names other than `actor` — returns nothing in `backend/app`.
- The three error codes retired in phase 2.1 (`NOT_PROJECT_OWNER`, `NOT_CHECKLIST_OWNER`,
  `NOT_MOCK_DATA_RECORD_OWNER`) are absent from `ErrorCode`, and
  `backend/tests/test_errors.py::test_created_by_ownership_error_codes_are_retired` asserts they
  stay absent. Not reintroduced.
- `POST /users`, `PATCH /users/{id}`, `DELETE /users/{id}`, `POST /users/{id}/reset-password` and
  both audit routes take `AdminUser` in the route signature — verified at the parameter level
  rather than assumed from a router-level dependency.
- The `must_change_password` gate is middleware, so a route added later is covered without opting
  in. No route group in this branch introduces a new top-level prefix that should have been added
  to `GATE_EXEMPT_PREFIXES`.

---

## §2 Read scoping — verified correct (its note, §2.1, is resolved)

**What was checked.** `resolve_project_scope` and its 20 call sites; `ProjectRepository.list_page`;
the `?ownerless=true` filter; and `backend/tests/test_scoping_is_single_point.py`'s own grep
patterns.

**What holds.**

- `ProjectRepository.list_page` applies the scope exactly as the resolver returns it —
  `unrestricted` means no clause, otherwise `Project.id.in_(scope.ids)`, which fails closed on an
  empty set.
- `?ownerless=true` is applied with `scope.narrowed_to(ownerless_ids)`, layered on top of the
  resolver's answer rather than replacing it, and is itself gated on `is_admin`. This is the shape
  `.claude/rules/contradiction-halt.md`'s worked example calls for.
- `ProjectScope` is never nullable. `unrestricted: bool` plus `ids: frozenset` is the only state,
  and no `Optional[ProjectScope]` or `None` sentinel exists anywhere it is used.

---

## §3 Conversation privacy — verified correct

**What was checked.** All four routes under `/conversations`; `ConversationService._require_own`;
`resolve_conversation_owner`; the permission catalogue; and the two audit events conversations
now record.

**What holds.**

- `_require_own` is the single ownership check and always raises `404 CONVERSATION_NOT_FOUND`.
  `GET /{id}` and `DELETE /{id}` declare no `403` in their `responses` blocks at all, which is the
  wire-level expression of the same rule.
- `is_admin` appears nowhere in the conversation stack except in docstrings explaining that it
  must not. There is no `conversation.*` permission in `backend/app/core/permissions.py`, and its
  absence is what keeps privacy true for administrators too.
- The phase-2.2 amendment holds to its stated bound: `conversation.created` and
  `conversation.deleted` set `target_label` to `None` explicitly, the delete event's context
  carries only `messageCount`, and the ask route records nothing. No title and no message content
  reaches any operator surface.

---

## §4 Ingestion and server-side request forgery — verified correct

Server-side request forgery (SSRF) means making the server fetch a URL an attacker chose. It is
the sharpest risk in this application, because `repo_url` is user-supplied and fetched from inside
a private network where `10.0.x.x` and internal service names resolve.

**What was checked.** `backend/app/core/repo_url.py`, `backend/app/ingestion/cloner.py`, and the
clone path in `backend/app/ingestion/pipeline.py`.

**What holds, and each is the hard version rather than the easy one.**

- **Every resolved address is checked**, not just the first, closing the bypass where a hostname
  publishes one public and one private address record.
- **The clone is pinned to the validated address** via git's `http.curloptResolve`. This is a
  connect-time control, not a parse-time one, so DNS rebinding — re-pointing the hostname between
  the check and the fetch — does not apply. Redirects are disabled
  (`http.followRedirects=false`), so a redirect to a private host after a passing check cannot be
  followed, and `GIT_CONFIG_NOSYSTEM=1` blocks a system-level `url.insteadOf` rewrite that could
  otherwise re-target a validated URL.
- **`.hostname` is used rather than `.netloc`**, so `https://github.com@10.0.0.1/` reads as host
  `10.0.0.1` and is rejected rather than smuggled past the allowlist. Credentials in the URL are
  rejected outright rather than stripped.
- **The size cap is enforced twice** — a watchdog kills the process mid-clone, and a second check
  runs on the success path for clones that finish before the watchdog's first poll. The clone
  timeout is enforced with `asyncio.wait_for`.
- **The PAT is passed by environment and a credential helper, never on the command line**, so it
  cannot appear in a process listing.
- **Validation runs again inside the pipeline immediately before every clone**, not only at
  project creation, so a host that later re-resolves is still checked at connect time.

**One thing worth stating precisely**, because it reads like a bypass and is not: a trailing-dot
host (`github.com.`) or a punycode homograph does not match the allowlist by exact string
comparison, and therefore is **rejected**. The failure direction is closed, not open.

---

## §5 Soft delete against the vector store — verified correct

The invariant: Postgres rows soft-delete, and the matching vector points hard-delete, in the same
operation. Vector points carry no `deleted_at`, so a query-time filter would be one forgotten call
away from serving deleted content.

**What holds.**

- `ProjectService.delete` soft-deletes the project and cascades to conversations, checklist and
  mock data, then hard-deletes the points in the project's own recorded `embedding_collection` —
  and commits **only after** the vector delete succeeds. A vector-store failure raises `503` and
  leaves everything uncommitted, so the row stays visible and nothing is orphaned.
- `release`, `abandon` and `renew_lease` all gate on `deleted_at IS NULL` and `lease_owner`, so a
  worker finishing after a mid-run delete cannot resurrect the row's collection or outcome.
- No collection name is hardcoded anywhere outside `collection_name()` and the in-memory test
  double. The vector width is probed once at worker startup.
- Reindex is a genuine generation swap: new points are written under an incremented generation,
  `active_generation` flips only on success, and the superseded generation is deleted only after
  that flip. A failure part-way leaves the previous index intact and still serving.
- Every hand-written `select(...)` across the repositories was reviewed. Each is either an
  aggregate, a narrow projection with `deleted_at.is_(None)` applied explicitly, or a subquery
  deliberately unfiltered because it feeds a cascade that is itself guarded.
  `backend/app/repositories/audit_event.py` building `select(AuditEvent)` directly is the
  documented, deliberate exception — the model carries no soft-delete mixin, so routing through
  `active_select()` would read as though a filter were in force on a table that has no such
  column.

---

## §6 Secret handling — verified correct

**What holds.**

- `scrub` is applied at every site on the path a token can take into operator-readable text: the
  clone stderr, the rev-parse stderr, and the terminal-error string written to `Project.error`.
- The queue consumer's unclassified-exception branch deliberately discards the real message and
  records only the exception class name, because that layer has no token in scope to scrub with.
  That is a traced decision, not an omission.
- No response schema exposes `encrypted_pat`, `password_hash` or any token. The fields are absent
  from response models, not masked and not optional.
- No log statement interpolates a token or a raw `repo_url`. The one refresh-token log line
  records a count.
- Refresh tokens are stored as a SHA-256 hash so they can be revoked, and rotate on use.
- The audit trail's allowlist holds: every allowlisted key across all event types was checked for
  both banned categories, and none carries a secret or model-generated content. `repo_url_host()`
  uses `urlsplit().hostname`, which excludes userinfo by construction, so a token embedded as
  `https://x-access-token:PAT@host/…` cannot survive into `repoUrlHost`.

**Known, already scheduled, and deliberately not re-filed here:** `.claude/rules/audit-trail.md`
states that everything entering `details` passes `scrub`, and no `scrub` call exists on that path.
Nothing leaks — the allowlist above is the real bound — and the decision already taken is to make
the document true rather than the code. This sweep independently confirms the allowlist is a
sufficient bound, which is the evidence that fix needs.

---

## §7 The response contract — verified correct

**What was checked.** 15 routers, 67 routes, and all 13 schema modules.

**What holds.**

- Every schema module defines only `ApiModel` subclasses. Zero plain `BaseModel` schemas exist, so
  nothing silently ships `snake_case` keys.
- **The SSE event set matches exactly.** Every event constructed in `backend/app/rag/graph/nodes.py`
  and `answerer.py` was enumerated and diffed against `SSE_EVENT_MODELS`: `StatusEvent`,
  `CitationsEvent`, `TokenEvent`, `DoneEvent`, `ErrorEvent`, `ChangeSetEvent`,
  `MockDataChangeSetEvent`. Nothing on the wire is missing from the tuple. This matters more than
  any other item in this section: these payloads never pass through a `response_model`, so
  `tests/test_api_model.py` walking that tuple is the only thing checking them at all.
- Exactly one route widens the error body past `{code, message}` — `409 LAST_OWNER` — and it
  declares `LastOwnerErrorResponse` for that status rather than the generic entry, which is the
  obligation `.claude/rules/response-api.md` attaches to widening.
- The `422` field map is keyed camelCase, because `ApiModel` validates by alias and Pydantic's
  `loc` entries are therefore already the alias.
- `ask_question` remains the only route making two service calls, and nothing needing a status
  code is deferred into a stream. The other 14 routers make one call each.
- The FastAPI query-flattening trap does not fire anywhere: `list_indexed_paths` takes two scalar
  `Query()` parameters but never pairs them with a `ListQuery` subclass.

---

## §8 Job and status handling — verified correct

**What holds.**

- `ProjectRepository.claim` is the real deduplication boundary — a database-level conditional
  update on the project row. The service-level "is it already running?" check is documented and
  used only as a fast path for a nicer API response.
- `find_stranded` has all three branches, including the third one that exists for a reindex
  request that never reached a worker: flag raised, no lease, `updated_at` past the cutoff.
- The checklist sweep's exception is implemented as the rule describes. `claim_stranded` stamps
  `updated_at` on the rows it returns, so the 60-second tick cannot re-publish the same module
  forever, and it republishes with a fresh job id because a module that is already `generating`
  before its claim cannot be refused by its own status. `defer` shortens rather than drops the
  lease, so a retry is not refused by its own dead predecessor.
- Every terminal path either writes a terminal status with its error, or hands the lease back
  cleanly for the sweep to recover. No path was found that can strand a project in `cloning` or
  `indexing` forever.
- The consumer pauses **every** assigned partition and keeps polling throughout a long job, and
  re-pauses on rebalance — a keep-alive poll discards what it returns, so an unpaused sibling
  would have its jobs read and thrown away. There is no `max.poll.interval.ms` setting in
  `Settings`, confirming the knob is deliberately not exposed.

---

## §9 Code health — dead code, duplication, and documentation

Every finding this section raised (§9.1–§9.11) is resolved and in the log.

---

## Verified correct, with what was checked

Recorded so the next sweep can tell "clean" from "not audited".

- **Settings, all three places.** All 80 `Settings` fields were extracted programmatically and
  diffed against `backend/.env.example` and `docs/configuration.md` in both directions. Zero gaps
  either way. Every field has at least one real reader outside `config.py` — no dead setting.
  `AUDIT_RETENTION_DAYS`, added on this branch, is present in all three and is read by the worker.
- **Configuration flows one way.** No `os.environ` or `os.getenv` read exists outside `config.py`.
- **No unused imports or dead locals.** `ruff` with `F401`/`F841` returns nothing. The only `ARG`
  hits are FastAPI dependency parameters that exist to force a dependency to resolve, and test
  doubles matching a real interface.
- **The export pair is genuinely parallel, not drifted.** `checklist_export.py` has one workbook
  builder because its column set is fixed by spec; `mock_data_export.py` has a JSON builder, a
  workbook builder and a key-union helper because a record's fields are dynamic per module. Both
  modules cross-reference each other and explain the divergence. Row caps and audit events are
  correctly scoped to each domain's real shape.
- **The change-set pair is parallel apart from §9.1.** The `add` and `update` branches were diffed
  line by line with no divergence beyond domain-appropriate differences.
- **`docs/configuration.md`, `docs/data.md`, `docs/codebase.md`, `docs/architecture.md` and
  `docs/langgraph.md`** each had their stated counts verified exact — settings, tables, routers and
  routes, modules, and the graph's six always-present nodes plus its optional tail.
- **`CLAUDE.md` carries no milestone status**, correctly deferring to `docs/PRD.md` §6, and its
  frontend route list matches the real tree including the `/settings` index redirect.
- **No orphan references.** The two apparent ones are deliberate historical notes: `NEXT_PUBLIC_*`
  appears only in sentences explaining that the rule inverted, and `QA_EXPORT_MAX_ROWS` only in the
  sentence recording its rename.
- **Examples work.** The root README's `curl` examples match live routes and shapes; its port table
  matches the compose file exactly; every Make target named in the docs exists in the `Makefile`;
  and `frontend/package.json`'s scripts match the frontend README's table.
- **Released changelog sections are untouched**, as the rule requires.

---

# Sweep 2026-09-27

**Swept:** 2026-09-27 at `5b43564` (`main`). **Scope:** the whole backend again, weighted toward
what merged since 2026-09-19: notifications and their fan-out, mail and password reset, the
`/me/*` routes behind the profile page, and live updates (`GET /events`, the staging hook, the
Kafka hub and the worker's publisher). **Ground truth:** unchanged. **Read-only.** Every finding it raised
(§9.12–§9.16) was fixed the same day and is in the log. What stays here is what it verified.

**Numbering continues §9** and never reuses a number. It re-checked the four findings
the 2026-09-19 sweep left open (§2.1, §9.2–§9.4) and found them unchanged. All four were fixed
in the same pass.

## Verified correct in this sweep (2026-09-27), with what was checked

- **Access on every new route.** `notifications.py`, `notification_preferences.py`, `me.py` and
  `events.py` each take `CurrentUser`, with no `AdminUser` and no `is_admin`. None of them performs
  a destructive operation on a shared resource. `grep "created_by *[!=]="` across `backend/app`
  returns nothing.
- **`404`, not `403`, for someone else's row.** `NotificationService.mark_read`
  (`services/notification.py:73-86`) puts `user_id` in the `UPDATE` predicate itself, and
  `MeService.revoke_session` (`services/me.py:72-84`) checks `family_belongs_to`. Both answer `404`
  for another user's id.
- **The forced-password-change gate covers the new prefixes.** `GATE_EXEMPT_PREFIXES` in
  `core/middleware.py` is unchanged, so `/events`, `/me`, `/notifications` and
  `/notification-preferences` are gated. `/auth/password-reset/*` sits under `/auth` and takes no
  auth dependency, so a signed-out visitor can reach it, as intended.
- **Read scoping is still single-point.** `/me/activity` narrows through `resolve_project_scope`
  (`services/me.py:100-115`). `MembershipRepository.recipients_for` is called only from
  `core/access.py`. `live_event_visible_to` is the only visibility check in `app/live/stream.py`,
  `routes/events.py`, the hub and the fan-out. `tests/test_scoping_is_single_point.py` was
  extended with allowlists for all three. Only its older `created_by` pattern remains narrow
  (§2.1).
- **Live streams re-check per event.** `stream.py:142-148` reloads the user before each
  project-scoped event. The heartbeat re-check also calls `RefreshTokenRepository.family_is_live`.
  A notification event is forwarded only to ids in its `recipients`, with no admin bypass
  (`access.py:233-234`).
- **Notification recipients.** `resolve_notification_recipients` is the only resolver and has no
  admin branch. `raise_direct` is used only for `membership.granted`. `ACTOR_EXCLUDED`
  (`core/notifications.py:77-84`) holds exactly the four change-set applied/discarded events,
  matching rule 6.
- **Fan-out ordering at all nine sites.** `pipeline.py:140,184`, `checklist/generator.py:181`,
  `mockdata/generator.py:193`, `checklist_change_set.py:200,269`, `mock_data_change_set.py:144,210`
  and `membership.py:116`. The fan-out precedes the commit, and the audit write follows it,
  everywhere.
- **Conversation privacy is unchanged.** Every miss is `404`, there is no `is_admin` check, and
  `target_label` is `None` on both conversation audit events.
- **Password reset.** Only `sha256_hex(raw_token)` is stored (`password_reset.py:87`), and logs
  carry the token row's id, never the token. `get_usable_by_hash` filters `used_at`, `revoked_at`
  and `expires_at` and takes `with_for_update()`. `confirm` stamps `used_at`, sets the password
  and revokes every refresh token in one transaction. `request` answers `202` identically for
  known and unknown addresses. The per-address limiter counts every submitted address before the
  existence check, so a `429` reveals nothing either. The reset link is built from the
  `APP_BASE_URL` setting, never from the request's `Host` header, and carries the token in the URL
  fragment.
- **Mail.** The composer signatures match `mail.md` exactly. The templates contain no `<img`,
  `<script`, `<link` or `url(`. The Jinja environment autoescapes and uses `StrictUndefined`. The
  outbox constants (50 / 15 min / 5 / 24 h) match the rule. A non-`MailSendError` fails the row
  immediately. SMTP error text goes only to the log.
- **Secrets.** No response schema carries `password_hash`, `pat` or `encrypted_pat`. The refresh
  token stays cookie-only.
- **Audit coverage.** There are exactly 42 `.record(` call sites (41 in services plus the CLI),
  matching `CLAUDE.md` and `audit-trail.md`. `auth.password_reset.requested`/`.completed` and
  `auth.session.revoked` are catalogued and recorded after commit. Notification state is mapped to
  exemption 5 in `tests/test_audit_coverage.py`.
- **Response contract.** Every schema inherits `ApiModel`. `SSE_EVENT_MODELS` includes `/events`'
  `ReadyEvent`, `InvalidateEvent` and `ResyncEvent`. `LIVE_EVENTS_UNAVAILABLE` is declared in
  `GET /events`' `responses`. No new route raises a bare `HTTPException`, and no `AppError`
  widening lacks a model.
- **SSRF is unchanged and correct.** `git log a76f550..HEAD -- backend/app/ingestion` touches only
  `pipeline.py` (the fan-out). `repo_url.py` and `cloner.py` still reject non-https URLs, userinfo
  and any non-global resolved address. Git is pinned to the validated address via
  `http.curloptResolve`, and the size cap is enforced both live and after completion.
- **Soft delete.** Project delete still hard-deletes Qdrant points before the commit
  (`services/project.py:353-372`). `recipients_for` filters `deleted_at` on memberships, roles,
  role permissions and users. The new notification, preference, reset-token and refresh-token
  tables deliberately carry no `deleted_at` and are hard-deleted or revoked by design. A deleted
  project's past notifications stay listed, rendered from their `details` snapshot. That is
  by design (`notifications.md` rule 3), and following one lands on the project's ordinary `404`.
- **Live events are staged, never published directly.** No `.submit(` exists outside `app/live/`.
  `staging.py` discards only when the outermost transaction ends (`transaction.parent is None`).
  `tests/test_live_event_sites.py` pins every status-writing method in the three repositories.
  `LiveEvent` carries ids only.
- **The worker publishes.** `worker.py:275-280` installs a `KafkaLivePublisher` unconditionally,
  so index and generation status changes made in the worker do reach browsers. It unhooks the
  publisher before stopping it.
- **Worker task isolation.** `reconcile_loop` and `mail_loop` catch and log each tick. The
  ingestion, checklist, mock-data and retry consumers catch each record (`queue/consumer.py:344`,
  `queue/retry.py:142`), so one bad job cannot stop the worker. Only a failure of a loop itself,
  such as a lost broker connection, ends `asyncio.gather` and the process, which is the correct
  fail-fast behaviour under a restarting container.
- **Settings.** All 97 fields are in `backend/.env.example` and `docs/configuration.md`
  (`COMMON_PASSWORD_LIST_PATH` is there, commented out, at `.env.example:41`), and every field
  has a reader. The only gap is on the Compose side (§9.13).
- **Counts that are right.** 17 rule files and 7 commands (`CLAUDE.md`); 81 routes (`docs/codebase.md`,
  `docs/README.md` and `backend/README.md`'s table); 40 audit event types (`docs/data.md`); nine
  fan-out sites (`notifications.md`). `SECURITY.md` covers `SMTP_PASSWORD`. `README.md`'s Roadmap
  defers to PRD §6 with no checkboxes.

---

# Sweep 2026-10-04

**Swept:** 2026-10-04 at `df7594e` (`main`). **Scope:** the whole backend and infrastructure,
weighted toward what merged since v2.2.0: user feedback on model output and the AI call log
(Phase 2.5, PR #57), the synthetic question-and-answer eval harness and per-user answer style
(Phase 2.6, PR #58). **Ground truth:** unchanged. **Read-only** — nothing below has been fixed.

**Numbering** continues each category (`§1.3`, `§3.1`, `§9.17`…) and never reuses a number.

**Four decisions were put to the owner during this sweep.** The PRD is right about deactivation
and the code should follow it (§3.2). An eval id's existence must not be told apart from a random
id's (§1.3). The two frontend decisions are in [`ui-audit-findings.md`](ui-audit-findings.md).

## §1 Access control

Every finding this sweep raised here (§1.3) was resolved on 2026-10-17 and is in
[`audit-finding-solved-logs.md`](audit-finding-solved-logs.md).

## §2 Read scoping

### §2.2 Two services flatten the project scope into a raw id list, and the single-point grep cannot see it — 🟡 hygiene

> **Corrected 2026-10-17.** This finding was first filed as "three reads of `scope.ids`", citing
> `repositories/feedback.py:41`. That line reads a `project_ids` filter, not `scope.ids`. A recount
> finds five reads outside `access.py`. Three of them are repositories applying a `ProjectScope`
> they were handed, which is the intended pattern. The two that matter are in services. The
> heading and blocks below are the corrected version.

**Evidence:** CONFIRMED (`grep -rn "scope\.ids" backend/app`, re-run 2026-10-17).

**Where:** `backend/app/services/feedback.py:260`, `backend/app/services/me.py:125` (the two service
sites); `backend/app/repositories/project.py:84`, `checklist_module.py:58`, `checklist_item.py:42`
(the three repository sites, which are correct); `backend/tests/test_scoping_is_single_point.py`

**What this is.** `docs/PRD.md` §7 requires that which projects a user may read is decided in one
function, `resolve_project_scope`, and a grep test enforces it. The resolver returns a
`ProjectScope`: either unrestricted (an administrator) or a set of project ids. Repositories
receive that object and apply it in their `WHERE` clause.

**Why this can happen.** `FeedbackService` and `MeService` do not pass the `ProjectScope` down.
Each unpacks it into a plain list (`None if scope.unrestricted else scope.ids`), and the repository
filters on that list. The result is correct today, because both lists come straight from the
resolver. But the repository can no longer tell a resolver-issued list from any other list of ids.
The grep test has no pattern for `scope.ids`, so a later service that builds the list some other
way would also pass.

**What it costs.** Nothing today. It is the shape that lets read scoping leak out of `access.py`
without any test noticing.

**What we should do.** Pass the `ProjectScope` itself into `FeedbackRepository` and the activity
query, the way the project and checklist repositories already do. Then add a grep pattern for
`scope.ids` outside `app/core/access.py` and `app/repositories/`. About an hour.

## §3 Conversation and voter privacy

Every finding this sweep raised here (§3.1–§3.3) was resolved on 2026-10-17 and is in
[`audit-finding-solved-logs.md`](audit-finding-solved-logs.md).

## §5 Soft delete

### §5.1 Deleting a project mid-run can leave live eval results under a deleted run — 🟡 hygiene

**Evidence:** CONFIRMED by reading; the race was not executed.

**Where:** `backend/app/services/project.py:309-387` (the soft-delete block of `delete`);
`backend/app/eval/runner.py:57` (`RESULT_BATCH = 10`), `:148-172` (the result loop), `:231-238`
(`_require_lease`), `:332-346` (`_renew`), `:182-194` (the final release);
`backend/app/repositories/eval_run.py:21-22`, `:112`, `:135`

**What this is.** An eval run answers each question with the real answer graph and stores the
answer and a judge's verdict as result rows, committing every ten. A worker holds a lease on the
run and renews it every 60 seconds.

**Why this can happen.** A project delete soft-deletes the project's eval rows, but takes no lock
on a running run and does not refuse while one is active (unlike reindex and eval set delete,
which refuse with `409 EVAL_RUN_IN_PROGRESS`). Sequence: an owner deletes the project → the run row is
soft-deleted → the worker keeps committing batches of ten results → those rows are live, under a
deleted run, and nothing sweeps them.

The window is bounded. `renew_lease` filters on `deleted_at IS NULL`, so the renewal task's next
tick (at most 60 seconds later) fails, and `_require_lease` stops the loop before the next commit.
The final `release` also refuses a deleted run and rolls back. What leaks is only the batches
committed between the delete and that tick: up to about a minute of results.

**What it costs.** Orphan rows holding model answers about a deleted repository's code. No route
returns them (the run is deleted), so it is invisible rather than exposed.

**What we should do.** Either refuse a project delete with `409 EVAL_RUN_IN_PROGRESS` while a run
is active, or have the runner's batch commit re-check the run (`... WHERE deleted_at IS NULL`).
One to two hours.

## §7 The response contract

### §7.1 Four eval routes do not declare `422` — 🟡 hygiene

**Evidence:** CONFIRMED.

**Where:** `backend/app/api/routes/eval.py:91-102`, `:105-116`, `:136-150`, `:170-181`;
`backend/app/api/routes/projects.py:118`, `:184` (the siblings that declare it)

**What this is.** `.claude/rules/response-api.md` (`:117-120`, `:150`) requires `422` on a route
that takes a body or typed query parameters. The project routes go further and declare it for a
typed UUID path parameter too, so `/docs` and generated clients describe the malformed-id case.

**Why this can happen.** `get_eval_set`, `delete_eval_set`, `start_eval_run` and `get_eval_run`
take a UUID path parameter and omit `422`, while the project routes with the same shape declare
it. Strictly, the rule's wording does not require it for a path-only route, so this is a sibling
inconsistency rather than a rule breach. `start_eval_run` also takes a body, and for that route
the rule does apply.

**What we should do.** Add `422` to the four `responses` blocks. Minutes.

### §7.2 Eval, feedback and activity lists accept `sort`/`search` and ignore them — 🟡 hygiene

**Evidence:** CONFIRMED.

**Where:** `backend/app/api/routes/eval.py:74-89`, `:153-167`; `backend/app/services/eval.py:136-151`,
`:319-332`; `backend/app/api/routes/feedback.py:37-50` (takes `FeedbackListQuery`, a `ListQuery`
subclass); `backend/app/api/routes/me.py:80-93`

**What this is.** `ListQuery` carries `page`, `limit`, `sort`, `sortDirection` and `search`.
`.claude/rules/router.md` says an unknown `sort` answers `400`, and the project, checklist and
conversation lists do.

**Why this can happen.** These routes take `ListQuery` but have a fixed order, so the service
reads only `page` and `limit`. `?sort=bogus` answers `200`, and `?search=x` returns the whole list.

**What it costs.** A client that sends a search gets an unfiltered list and no error, and the
generated docs advertise parameters that do nothing.

**What we should do.** Add a `PageQuery` (page and limit only) for fixed-order lists, or honour
or reject the fields. One to two hours, across the four routes.

### §7.3 An eval set can be created with a whitespace-only name — 🟡 hygiene

**Evidence:** CONFIRMED.

**Where:** `backend/app/schemas/eval.py:22`; `backend/app/services/eval.py:90`

**Why this can happen.** `name` has `min_length=1` but no stripping, and the service strips it
after validation. `{"name": "   "}` passes, stores `""`, and writes an empty audit `target_label`.

**What we should do.** Strip in a validator before the length check. Minutes. The checklist
module name has the same gap; fix both together.

## §8 Job and status handling

### §8.3 A failed eval run reports zero tallies and no finish time — 🟡 hygiene

**Evidence:** CONFIRMED.

**Where:** `backend/app/queue/eval.py:133-143` (`_RunLease.fail`); `backend/app/eval/runner.py:182-194`

**Why this can happen.** Tallies (`hits`, `correct`, `partial`, `wrong`, `errors`,
`pairs_answered`) and `finished_at` are written only when a run finishes `done`. A run that
answers 30 of 50 questions and then fails keeps its 30 committed results but is released `failed`
with tallies of zero and no finish time.

**What it costs.** The runs table shows "hits 0/0 · correct 0" for a run whose detail sheet lists 30
answers, and its duration cannot be computed.

**What we should do.** On failure, write `finished_at` and tallies computed from the committed
results. One hour.

### §8.4 The eval set generator never checks that it still holds its lease — 🟡 hygiene

**Evidence:** CONFIRMED.

**Where:** `backend/app/eval/generator.py:88-119`, `:139-143`; compare `backend/app/eval/runner.py:231-238`

**Why this can happen.** The runner checks its renewal task before each batch; the generator
starts one and never reads it. If the set is deleted while generating (`delete_set` refuses only
while a *run* is active), or its lease lapses and the sweep re-publishes it, the generator carries
on through up to 50 model calls and only learns at the end, when its release matches no row and it
discards everything.

**What it costs.** Wasted model calls; no stuck or corrupt rows.

**What we should do.** Check the renewal task in the per-question loop, as the runner does, and
consider refusing to delete a set that is still generating. One hour.

### §8.5 A resumed eval run overwrites its own provenance stamp — 🟡 hygiene

**Evidence:** CONFIRMED 2026-10-17 (was SUSPECT). The overwrite is in
`backend/app/eval/runner.py:132-138` and `backend/app/repositories/eval_run.py:88-96` (`started_at`
reset at `:93`). The trigger is reachable: a resume happens only after a lease lapses, which means
a worker restart or a redeploy, and that is exactly when `PROMPT_VERSION` or the `CHAT_*` settings
can change (§8.1 makes the settings drift more likely). The embedding model and index generation
cannot change mid-run, because reindex refuses with `409` (`backend/app/services/project.py:271-279`).
How often it happens in practice cannot be measured from the code.

**What this is.** Each run records which prompt version, chat model, judge model, embedding model
and index generation it used, so two runs can be compared honestly. `docs/PRD.md` (`:343`, `:354`)
says a score is comparable only against a fixed prompt; the list of stamped fields comes from
`app/models/eval.py`.

**Why this can happen.** Every attempt overwrites the stamp and resets `started_at`. A run that
answers 20 questions, is retried after a restart, and resumes on a different model is stamped only
with the second.

**What we should do.** Stamp only when empty; on resume, compare and fail the run if the stamp
would change. Set `started_at` only once. One hour.

### §8.6 Eval requests audit after the publish, unlike reindex — 🟡 hygiene

**Evidence:** CONFIRMED 2026-10-17 (was SUSPECT). The ordering is certain: commit `:105`, publish
`:107`, audit `:117-133` in `create_set`; commit `:291`, publish `:295`, audit `:305` in
`start_run`. `producer.produce_to` raises on a Kafka failure. How often a produce fails after the
commit cannot be measured from the code.

**Where:** `backend/app/services/eval.py:105-134`, `:291-316`; compare
`backend/app/services/project.py:293-306`

**Why this can happen.** `create_set` and `start_run` commit, then publish to Kafka, then record
the audit event. If the publish raises, the user sees a `500`, the row survives (the sweep later
publishes it), and `eval_set.generation.requested` / `eval_run.requested` is never written.
Reindex and checklist generation record before the publish. Mock data has the same order as eval.

**What we should do.** Record the audit event before the publish (still after the commit, as
`.claude/rules/audit-trail.md` requires), in eval and mock data. Half an hour.

## §9 Code health — dead code, duplication, and documentation

### §9.17 `HOST` and `PORT` are settings nothing reads — 🟡 hygiene

**Where:** `backend/app/config.py:28-29`; `backend/.env.example:12-13`; `docs/configuration.md:82-83`

The bind address comes from the uvicorn command (`Makefile:207`,
`infra/backend.prod.Dockerfile:68`). `grep -rnw "settings\.\(host\|port\)" backend/app` returns
nothing, so an operator who sets `PORT=9000` changes nothing. **Fix:** delete the two fields and
their example and doc rows, or pass them to uvicorn. Every other of the 108 settings is read.

### §9.18 `APP_VERSION` defaults to `0.1.0` on a 2.2.0 release — 📄 doc

**Where:** `backend/app/config.py:23`, `backend/.env.example:7`, `docs/configuration.md:74`;
`backend/pyproject.toml:3`, `frontend/package.json:3`

`/` and `/health` report `0.1.0`; both package files say `2.2.0`. **Fix:** decide whether
`APP_VERSION` tracks the release; if it does, read it from the package metadata rather than a
default someone must remember to bump.

### §9.19 The "project is indexed" guard exists in three copies — 🟡 hygiene

**Where:** `backend/app/services/index_guards.py:16-26`, `backend/app/core/access.py:155-181`
(`require_answerable`), `backend/app/services/indexed_path.py:200-212`; a fourth variant at
`backend/app/eval/runner.py:116-119` (it raises `TerminalIngestionError` with its own message)

Same condition, same message, three bodies (`require_answerable` adds the `EMBEDDING_MODEL_CHANGED`
check on top of the shared condition) — although `index_guards.py`'s own docstring says it
exists "so a fourth caller cannot drift" (commit `8f42a28`, a partial fix of §9.4). **Fix:** move
`require_indexed` to a leaf module (importing it from `index_guards` would cycle through
`IndexedPathReader`) and call it from all three. One hour.

### §9.20 The lease and heartbeat mechanism is copied across five repositories — 🟡 hygiene

**Where:** `claim`/`renew_lease`/`release`/`claim_stranded`/`defer` in
`backend/app/repositories/checklist_module.py`, `mock_data_dataset.py`, `eval_set.py`, `eval_run.py`
(and the project's `claim`/`renew_lease`/`release`/`find_stranded`); `LEASE_SECONDS`/`LEASE_RENEWAL_SECONDS`
repeated in all five; a renewal heartbeat in five runners — `_renew`/`_stop_renewal` in
`checklist/generator.py:212,235`, `mockdata/generator.py:227,246`, `eval/generator.py:146,159` and
`eval/runner.py:332,349`, and a differently named `_renew_lease` in `ingestion/pipeline.py:334`; `_defer`/`_fail`/`_route_failure` in three queue handlers

A lease is how one worker claims a job so another cannot run it at the same time. `eval_set.py:3-4`
calls itself "a near-copy" of the mock-data repository. Parameter names already diverge
(`generating_older_than_seconds` / `older_than_seconds` / `pending_older_than_seconds`). A fix to the
lease protocol — §8.2 is one — has to land in five places. **Fix:** a lease helper parameterised
by table, and one heartbeat context manager. A day; do it before a sixth job kind.

### §9.21 Four dead `STRANDED_AFTER_SECONDS` constants — 🟡 hygiene

**Where:** `backend/app/repositories/checklist_module.py:33`, `mock_data_dataset.py:28`,
`eval_set.py:23`, `eval_run.py:23`

Nothing imports them; the live value is `backend/app/worker.py:73`. **Fix:** delete them.

### §9.22 Eval does not normalise `sourcePath` the way checklist modules do — 🟡 hygiene

**Where:** `backend/app/services/eval.py:83-91`, `backend/app/eval/generator.py:95`; compare
`backend/app/services/checklist_module.py:163`; `backend/app/services/path_tree.py:34-47`;
`backend/app/schemas/eval.py:12`, `:23`; `backend/app/models/checklist.py:25-26`

A checklist module strips whitespace and slashes from its path, so `src/` and `/src` work. Eval
passes it raw, so the same input answers `400 MODULE_PATH_NOT_INDEXED`. Eval also caps the path at
1024 characters where checklist uses 512, and repeats the 120-character name limit as its own
constant. **Fix:** one shared normaliser and the shared length constants. One hour.

### §9.23 `docs/README.md` and `docs/architecture.md` carry stale counts — 📄 doc

| Claim | Where | Actual | How counted |
| --- | --- | --- | --- |
| "81 routes" | `docs/README.md:83` | 95 | `grep -rhE "^@[a-z_]+\.(get\|post\|put\|patch\|delete)\(" backend/app/api/routes \| wc -l` (`docs/codebase.md:148` says 95) |
| "20 tables" | `docs/README.md:27` | 26 | `grep -rh __tablename__ backend/app/models \| wc -l` (`docs/data.md:14` says 26) |
| "All 104 backend settings" | `docs/README.md:40` | 108 | `len(Settings.model_fields)` |
| "All 80 settings" | `docs/architecture.md:393` | 108 | same |

The same class as §9.7 and §9.15. **Fix:** correct the numbers, or drop the two settings counts and
link to `docs/configuration.md`.

### §9.24 `docs/codebase.md`'s tree misses modules — 📄 doc

**Where:** `docs/codebase.md:160` (`ingestion/`), `:163` (`rag/`), `:157` (`services/`), `:168`
(`live/`)

`ingestion/` lacks `errors.py`; `rag/` lacks `answer_style.py` and `prompt_version.py`; the
service count says 22 where there are 21 services plus `path_tree.py` and `index_guards.py`, and
`index_guards.py` is not mentioned; `mail/` is absent; the `live/` line omits `stream.py`. The
route, model and repository counts are right. **Fix:** update the tree.

### §9.25 `backend/README.md`'s layout and worker description are stale — 📄 doc

**Where:** `backend/README.md:59-75`, `:460-560`; `backend/app/worker.py:383`, `:397`, `:411`,
`:435` (the four consumers), `:508-512` (the mail loop)

The worker section still says "the API only enqueues indexing and checklist-generation jobs" and
lists two consumers; there are four, plus their retry consumers, the mail loop and the sweeps. The
layout block has no `observability/`, `live/` or `mail/`, lists six of 18 schema files, and describes `services/` as
three services. **Fix:** update both, linking to `docs/codebase.md` for the tree.

### §9.26 `docs/PRD.md` §6 does not record Phase 2.6 as shipped — 📄 doc

**Where:** `docs/PRD.md:1047`; compare `:1046` (Phase 2.5, "Shipped in two stages…")

PR #58 merged the eval harness and answer style, and #61 polished the eval screen. §6 is the only
place progress is recorded (`.claude/rules/documentation.md`). **Fix:** add a "Shipped" sentence
naming #58 and #61, in Phase 2.5's style.

### §9.27 `docs/notifications.md` carries an "in progress" banner — 📄 doc

**Where:** `docs/notifications.md:96` ("Amendment (2026-09-27, in progress)"); `docs/PRD.md:1027`

Progress belongs in the PRD only, which records live updates as shipped. **Fix:** drop "in
progress".

### §9.28 The eval harness is missing from `docs/langfuse.md` and the timeout docs — 📄 doc

**Where:** `docs/langfuse.md:41`, `:152-160` (the traces table), `:167-178`, `:426`; `docs/configuration.md:270`,
`docs/llm.md:235`

`docs/langfuse.md` never mentions eval: its feature table lacks `eval_generate` and `eval_judge`,
and it does not say an eval answer is one trace seeded from its result id (which `docs/llm.md`
does). `GENERATION_TIMEOUT_SECONDS` is documented as covering checklist and mock-data generation
only; it also bounds eval generation, answers and the judge. **Fix:** add eval to each.

### §9.29 `CHANGELOG.md` `[Unreleased]` has duplicate headings and misfiled entries — 📄 doc

**Where:** `CHANGELOG.md:16`, `:25`, `:34`, `:99`, `:118`; `:101-110`; `:22`

The section reads Changed, Fixed, Added, Changed, Fixed. The `traceUrl` and `createdOn` entries
are filed as Changed, but feedback has never been released, so they describe the feature as it
ships and belong in its Added entry. Line 22 says the reindex refusal "reuses the existing error
code", which is itself new in this release. **Fix:** merge the headings and move the two entries
before the release is cut.

### §9.30 Stale comments in the feedback schema and the audit coverage test — 📄 doc

**Where:** `backend/app/schemas/feedback.py:95` ("Stage 2 (Langfuse) fills this; until then…
null" — Stage 2 shipped, `backend/app/services/feedback.py:165-166`);
`backend/tests/test_audit_coverage.py:11`, `:14`, `:50`, `:221`, `:238-241` ("six", "five"
exemptions — there are seven: the comment at `:38` says so, and `VALID_EXEMPTIONS` at `:60-62`
has seven);
`backend/tests/test_auth_middleware.py:219` ("`/auth/me` does not exist yet" — it does,
`backend/app/api/routes/auth.py:327`)

**Fix:** reword to "the named exemptions" and rename `test_every_exemption_is_one_of_the_five`.

### §9.31 `PROMPT_VERSION` changes when a non-answer prompt changes — 📄 doc

**Evidence:** SUSPECT — whether this is intended is a design question. Re-checked 2026-10-17 and
still unsettled. The module docstring (`prompt_version.py:3-6`) and `prompts.py:189` say "any edit
changes the version" deliberately, and nothing records a decision either way about scoping it to
the answer path. The owner settles it.

**Decision pending (2026-10-17).** The owner first chose "hash only the answer-path prompts". That
was not implemented, because the same version is also stamped on checklist and mock-data
change-set feedback, on every call record, and on eval runs, whose scores depend on the judge prompt.
Answer-path-only would leave those stamps unchanged when the prompts behind them change, which is
the comparison they exist for. The alternative put back to the owner: a version per feature, with
eval runs stamping an answer version and a judge version.

**Where:** `backend/app/rag/prompt_version.py:18-25`; stamped at `backend/app/services/feedback.py:116`,
`backend/app/observability/recorder.py:110`, `:172`, `backend/app/eval/runner.py:132`

`PROMPT_VERSION` hashes every upper-case constant in `app/rag/prompts.py`, including the
checklist, mock-data and eval judge prompts. Editing the judge prompt therefore changes the version
stamped on Ask answers and feedback, though the answer prompt did not change — which weakens the
PRD's "an eval score is comparable only against a fixed prompt". **Fix:** document it, or hash
only the answer-path prompts.

## Verified correct in this sweep (2026-10-04), with what was checked

- **Access on every new route.** `backend/app/api/routes/eval.py` (8 routes), `feedback.py` and
  `me.py`. Eval gates on `eval.read` / `eval.run` through `require_permission`. A member without
  the permission gets `403 INSUFFICIENT_ROLE`, a non-member `404`, and an admin passes. The feedback
  reads take `AdminUser`, the writes `CurrentUser`. `/me/answer-style` has no id parameter.
  No `created_by` or inline `is_admin` gate exists. The new prefixes (`/eval-sets`, `/eval-runs`,
  `/eval-pairs`, `/feedback`, `/me`) are covered by the forced-password-change gate, which is an
  allowlist.
- **Conversation privacy and the feedback write side.** There is no `is_admin` under
  `/conversations`. Every feedback write miss is the single `404 FEEDBACK_TARGET_NOT_FOUND`, through
  `get_for_owner` or `ChecklistModuleRepository.get_in_scope`. `FeedbackAdminRead` has no user
  field and no `updatedAt`. `traceUrl` is never seeded for an Ask vote.
- **Server-side request forgery** (making the server fetch an address an attacker chose).
  `git diff v2.2.0..HEAD -- backend/app/ingestion` is empty. `repo_url.py`, the connect-time
  re-validation in `pipeline.py:233`, and the cloner's pinned resolve, disabled redirects, timeout
  and size cap are unchanged.
- **Soft delete reaches eval and feedback.** A project delete soft-deletes results, runs, pairs,
  sets and feedback in one transaction, children first, and hard-deletes the Qdrant points before
  committing. Every eval repository read filters `deleted_at`. Eval tables hold no vectors.
- **Secrets and content.** No response schema carries `encrypted_pat`. The Langfuse keys are read
  only in `config.py`, `main.py` and `langfuse_sink.py`, and the frontend never sees them.
  `CallRecord` and `CallStart` have no content or user field. The recorder sets
  `raise_error = False`, reads only usage from `on_llm_end`, and stores `type(error).__name__`.
  `langfuse` is imported only after the enabled check. The eval audit allowlists carry no
  question, reference, answer or judge reason, and eval log lines carry ids and exception class
  names only. Answer style is three enums mapped to fixed sentences.
  Observation, not filed: `LANGFUSE_SECRET_KEY`, `CHAT_API_KEY` and `EMBEDDING_API_KEY` are plain
  `str` where `SMTP_PASSWORD` is `SecretStr`. No leak path was found.
- **Response contract.** Every raise in `backend/app/services/eval.py` was traced to its route's
  `responses`; apart from §7.1, nothing is under- or over-declared. Every eval, feedback and me
  schema inherits `ApiModel`. `AppError(extra=…)` is used only for `LAST_OWNER`.
  `SSE_EVENT_MODELS` covers the live event payloads, whose `kind` includes `eval_set` and
  `eval_run`.
- **Eval jobs cannot stick.** `claim`, `release`, `defer`, `renew_lease` and `claim_stranded` gate
  on `deleted_at` and the lease owner. `claim_stranded` stamps `updated_at`, as the checklist sweep
  does (but see §8.2). Every failure path writes a terminal status with a class-name-only error.
  `EvalConsumer` inherits the pausing consumer. Reindex and run start serialise on the project row.
  The eval status writes stage live events (`tests/test_live_event_sites.py`).
- **Counts that hold.**
  - 47 `AuditRecorder` call sites (46 in services plus the CLI) and 45 audit event types, matching
    `CLAUDE.md`, `.claude/rules/audit-trail.md` and `docs/data.md`.
  - 19 rule files, 7 commands, 6 live kinds, 9 notification fan-out sites, 16 job topics plus 1 live
    topic, 4 worker consumers, and 20 permissions.
  - All 108 settings are in `backend/.env.example` and `docs/configuration.md`.
  - Every `.ainvoke`/`.astream` call site is listed in `tests/test_call_sites_tagged.py`, including
    `eval_generate` and `eval_judge`.
- **No regressions** of §1.1, §1.2, §2.1, §9.2, §9.3, §9.6, §9.8, §9.13, §9.14 or §9.16. §9.4 is
  partly fixed; the remainder is §9.19.

---

## See also

- [`audit-finding-solved-logs.md`](audit-finding-solved-logs.md) — the findings that have been fixed, verbatim
- [`ui-audit-findings.md`](ui-audit-findings.md) — the frontend sweep (`§U1`–`§U12`)
- [`PRD.md`](PRD.md) — the source of truth these findings are measured against
- [`../.claude/commands/audit-flow.md`](../.claude/commands/audit-flow.md) — how this sweep is run
- [`../.claude/rules/audit-findings.md`](../.claude/rules/audit-findings.md) — how a finding is written

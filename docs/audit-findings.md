# Audit findings

The standing record of **open** backend and architecture findings, written by `/audit-flow`,
plus each sweep's verified-correct notes so the next sweep can tell "clean" from "not audited".
A finding that has been fixed moves, verbatim, to
[`audit-finding-solved-logs.md`](audit-finding-solved-logs.md). A number cited below that is not
in this file (§1.1, §9.1 and so on) is there.

**Sweeps:** 2026-09-19 (at `f902f4c`, phase 2.2 branch), 2026-09-27 (at `5b43564`, `main`),
2026-10-04 (at `df7594e`, `main`) and 2026-10-24 (at `ac3a52c`, `main`). All four were read-only.
The first two were each followed by a separate, explicitly requested fix pass; the last two have
had none. The 2026-10-24 sweep re-checked every open finding: all fifteen are still open, with
their current locations listed under [Sweep 2026-10-24](#sweep-2026-10-24).

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
2026-10-04 or 2026-10-24 and is still open; what was fixed on 2026-10-17 is in the log.

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
| §9.30 | Stale comments in the feedback schema and the audit coverage test | 📄 | 2026-10-04 |
| §4.1 | A timed-out or cancelled clone leaves its `git` process behind | 🟡 | 2026-10-24 |
| §4.2 | The connect-time address pin uses only the first record, and may not accept IPv6 (SUSPECT) | 🟡 | 2026-10-24 |
| §6.2 | A refused reset email may log the recipient's address (SUSPECT) | 🟡 | 2026-10-24 |
| §7.4 | The four membership routes declare no `summary` and no error responses | 🟡 | 2026-10-24 |
| §7.5 | The source-path check's errors are undeclared on three routes | 🟡 | 2026-10-24 |
| §7.6 | The `409` on `DELETE /users/{id}` is declared with a shape `LAST_ADMIN` does not have | 🟡 | 2026-10-24 |
| §7.7 | The three download routes document no body | 🟡 | 2026-10-24 |
| §7.8 | The eval-set create body marks every field optional | 🟡 | 2026-10-24 |
| §7.9 | An eval set with a retired language would fail every list it appears in (SUSPECT) | 🟡 | 2026-10-24 |
| §8.7 | Translating an eval set whose source is deleted mid-job fails with the wrong reason | 🟡 | 2026-10-24 |
| §9.32 | Five English-only constants survive the translated tables | 🟡 | 2026-10-24 |
| §9.33 | "An unset or unshipped language reads as English" is written out eight times | 🟡 | 2026-10-24 |
| §9.34 | The single- and multi-module checklist exports duplicate their filter and cap logic | 🟡 | 2026-10-24 |
| §9.36 | `docs/architecture.md` counts nine notification fan-out sites; there are thirteen | 📄 | 2026-10-24 |
| §9.38 | A project-list docstring still describes phase 1 | 📄 | 2026-10-24 |

## Top priorities (2026-10-24)

The 2026-10-24 sweep found no security finding, no 🔴 bug and no 🟠 risk in the backend. Access,
read scoping, conversation privacy, the clone's address checks and soft delete all held across
Phase 2.7. Everything open is hygiene or documentation.

1. **Error text and logs that say more than they should** (§6.1, §6.2): a provider outage can put an
   internal URL on the project screen, and a refused reset email may log the address. Neither leaks
   a secret.
2. **The eval job edge cases** (§5.1, §8.3–§8.7): orphan results after a mid-run delete, a failed
   run's empty tallies, a generator that never checks its lease, a resumed run's overwritten stamp,
   audit-after-publish ordering, and a translation that fails for the wrong reason.
3. **The response-contract gaps** (§7.1–§7.9), led by the membership routes (§7.4) and the
   undeclared path error on module create (§7.5).
4. **The duplication and dead code** (§9.17, §9.19–§9.22, §9.32–§9.34), the clone process clean-up
   (§4.1), the scope plumbing in two services (§2.2), and the IPv6 pin question (§4.2).
5. **The documentation** (§9.30, §9.36, §9.38): stale test and schema comments, the architecture
   page's notification-site count, and a phase-1 docstring. §9.35 and §9.37 were fixed with the
   v2.4.0 release cut and are in the log.

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

### §9.30 Stale comments in the feedback schema and the audit coverage test — 📄 doc

**Where:** `backend/app/schemas/feedback.py:95` ("Stage 2 (Langfuse) fills this; until then…
null" — Stage 2 shipped, `backend/app/services/feedback.py:165-166`);
`backend/tests/test_audit_coverage.py:11`, `:14`, `:50`, `:221`, `:238-241` ("six", "five"
exemptions — there are seven: the comment at `:38` says so, and `VALID_EXEMPTIONS` at `:60-62`
has seven);
`backend/tests/test_auth_middleware.py:219` ("`/auth/me` does not exist yet" — it does,
`backend/app/api/routes/auth.py:327`)

**Fix:** reword to "the named exemptions" and rename `test_every_exemption_is_one_of_the_five`.

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

# Sweep 2026-10-24

**Swept:** 2026-10-24 at `ac3a52c` (`main`). **Scope:** the whole backend and infrastructure,
weighted toward the 111 commits since `df7594e`: eval notifications (#66), the multi-module
checklist export (#67), and Phase 2.7 — the interface language (#68), eval languages and
translation (#69), and a project's content language (#70) — plus the Dependabot bumps (#71).
**Ground truth:** unchanged. **Read-only** — nothing below has been fixed.

**Numbering** continues each category and never reuses a number. §4 and §6 had never had a
finding; theirs start at §4.1 and §6.1.

**Evidence:** every finding below was traced in the code. Where the trace stops short of the
trigger, the finding says SUSPECT and names what would settle it. Nothing was executed — no tests,
no server, no clone.

## Open findings re-checked

All fifteen findings open before this sweep are **still open**; none was fixed and none refuted.
Their line numbers have moved; the current locations are:

| # | Still open at |
| --- | --- |
| §2.2 | `backend/app/services/feedback.py:290`, `backend/app/services/me.py:127` → `backend/app/repositories/feedback.py:27,45-46`, `backend/app/repositories/audit_event.py:35,53,63-70,124-136` |
| §5.1 | `backend/app/services/project.py:349-452` (no `active_for_project` check; reindex has one at `:312`); runner commits every 10 results, `backend/app/eval/runner.py:61,181-184` |
| §7.1 | `backend/app/api/routes/eval.py:98`, `:111`, `:143`, `:177` |
| §7.2 | `backend/app/api/routes/eval.py:85`, `:164`, `backend/app/api/routes/me.py:91`; the feedback list's `FeedbackListQuery` likewise |
| §7.3 | `backend/app/schemas/eval.py:35` (no strip); `backend/app/services/eval.py:148` strips afterwards |
| §8.3 | `backend/app/queue/eval.py:148-158`; tallies and `finished_at` only on the done path, `backend/app/eval/runner.py:195-205` |
| §8.4 | `backend/app/eval/generator.py:104` (renewal task created), `:120` (only cancelled) |
| §8.5 | `backend/app/eval/runner.py:143-150`; `started_at` reset at `backend/app/repositories/eval_run.py:93` |
| §8.6 | `backend/app/services/eval.py:101/103/116` (`create_set`), `:376/380/390` (`start_run`) |
| §9.17 | `backend/app/config.py:47-48` |
| §9.19 | `backend/app/services/index_guards.py:21`, `backend/app/core/access.py` (`require_answerable`), `backend/app/services/indexed_path.py:207`, plus bare `embedding_collection` checks in `backend/app/eval/runner.py:121`, `backend/app/checklist/generator.py:115`, `backend/app/mockdata/generator.py:127` |
| §9.20 | `renew_lease` in five repositories; `claim_stranded` in four |
| §9.21 | `backend/app/repositories/checklist_module.py:33`, `mock_data_dataset.py:28`, `eval_run.py:23`, `eval_set.py:23`; the live one is `backend/app/worker.py:73` |
| §9.22 | `backend/app/services/eval.py:142-149` vs `backend/app/services/checklist_module.py:163` |
| §9.30 | `backend/app/schemas/feedback.py:97`; `backend/tests/test_audit_coverage.py:11,14,51,227,244`; `backend/tests/test_auth_middleware.py:219` |

## §4 Ingestion and server-side request forgery

### §4.1 A timed-out or cancelled clone leaves its `git` process behind — 🟡 hygiene

**Evidence:** CONFIRMED by reading the code; not reproduced.

**Where:** `backend/app/ingestion/cloner.py:218-230`; the scratch directory is removed by
`backend/app/ingestion/pipeline.py` (`shutil.rmtree`)

**What this is.** Indexing a project starts by running `git clone` as a child process. The cloner
waits for it with a 120-second timeout (`docs/PRD.md` §9) and a size watcher, so a hung or huge
clone cannot hold its job forever.

**Why this can happen.** On timeout the code calls `process.kill()` and raises at once — it never
awaits `process.wait()`, so the dead process is not reaped until the event loop gets round to it.
If the worker is cancelled mid-clone (a shutdown, a redeploy), the `finally` block stops only the
size watcher: `git` is neither killed nor awaited, and keeps writing into `/data/repos` while the
pipeline's `rmtree` removes the same directory.

**What it costs.** No user sees anything. An operator may find stray `git` processes after a
redeploy, or leftover scratch directories that the next run has to step around.

**What we should do.** In the `finally`, kill the process if it is still running and await
`process.wait()` (under `asyncio.shield`, since the task may be cancelled). Half an hour.

### §4.2 The connect-time address pin uses only the first record, and may not accept IPv6 — 🟡 hygiene

**Evidence:** SUSPECT. Unverified: whether the deployed `git`/`curl` accepts an unbracketed IPv6
literal in `http.curloptResolve`. Running `git -c http.curloptResolve=github.com:443:<ipv6> ls-remote
https://github.com/…` in the production image settles it.

**Where:** `backend/app/core/repo_url.py:124-130`; `backend/app/ingestion/cloner.py:44`

**What this is.** To stop a repository URL from being re-resolved to a private address between the
check and the clone, the validator checks every address the host resolves to, then pins the clone
to one of them with curl's resolve override.

**Why this can happen.** It pins `addresses[0]`. If that is an IPv6 address and curl wants it
bracketed, the clone fails; if that one address is unreachable, the clone fails rather than trying
the next. Either way the failure is a retryable "clone failed", never a request to an unchecked
address — the security control holds.

**What we should do.** Settle the IPv6 question first. If it bites, prefer an IPv4 record or
bracket IPv6 literals. One hour, including a test.

## §6 Secret handling

### §6.2 A refused reset email may log the recipient's address — 🟡 hygiene

**Evidence:** SUSPECT. Unverified: whether `aiosmtplib`'s `SMTPRecipientsRefused` text includes the
address. Reading its `__str__` settles it.

**Where:** `backend/app/services/password_reset.py:173-180`; `backend/app/mail/sender.py:60-70`

**What this is.** When a reset email cannot be sent, the service logs a `WARNING` with the token
row's id — deliberately never the token (`.claude/rules/mail.md`).

**Why this can happen.** The same line also logs the `MailSendError`, which is built from the SMTP
library's own message. A relay that refuses the recipient produces a message that may quote the
address.

**What it costs.** A user's email address in operator logs. Not a secret, and not the audit trail,
but more than the line needs.

**What we should do.** Log `type(error.__cause__).__name__` and `error.retryable` instead of the
message. Fifteen minutes.

## §7 The response contract

### §7.4 The four membership routes declare no `summary` and no error responses — 🟡 hygiene

**Evidence:** CONFIRMED.

**Where:** `backend/app/api/routes/members.py:29`, `:37-40`, `:52`, `:64`; the raises are in
`backend/app/services/membership.py:84`, `:87`, `:89`, `:168`, `:181`, `:216`, `:249`

**What this is.** `.claude/rules/response-api.md` requires every route to declare a `summary`, a
`status_code`, and a `responses` block listing what its service raises, so `/docs` and every
generated client describe the real errors.

**Why this can happen.** The members router never had its contract pass. Its four routes (list,
add, change role, remove) declare none of it, and two have no `status_code`. The service raises
`404` (`ROLE_NOT_FOUND`, `USER_NOT_FOUND`, `MEMBERSHIP_NOT_FOUND`), `409` (`MEMBERSHIP_EXISTS`,
`LAST_OWNER`) and `403 INSUFFICIENT_ROLE`.

**What it costs.** `/docs` shows these routes with only their success status, titled by function
name. A generated client has no typed error for "this would leave the project with no owner".

**What we should do.** Add `summary`, `status_code` and `responses` (401/403/404/422 on all four,
409 on add, change and remove). Half an hour. No other router has this gap.

### §7.5 The source-path check's errors are undeclared on three routes — 🟡 hygiene

**Evidence:** CONFIRMED.

**Where:** `backend/app/api/routes/checklist_modules.py:140-146` (`POST`), `:170-176` (`PATCH`);
`backend/app/api/routes/eval.py:58-70` (`POST /projects/{id}/eval-sets`); the raises are in
`backend/app/services/index_guards.py:15-27`, `:74-87` and `backend/app/services/indexed_path.py:143-148`

**What this is.** A checklist module or an eval set can be pointed at a path in the repository.
`require_path_indexed` refuses a path the index does not contain with
`400 MODULE_PATH_NOT_INDEXED`, and answers `503 VECTOR_STORE_UNAVAILABLE` if the vector store cannot
be read.

**Why this can happen.** Neither module route declares `400` or `503`, the module `PATCH` also
omits the `409 PROJECT_NOT_READY` that `require_indexed` raises, and the eval-set route omits `503`.

**What it costs.** The most common error on module create — a mistyped path — is absent from
`/docs` and from every generated client, and a vector-store outage arrives as an undocumented
status.

**What we should do.** Declare `400` and `503` on all three, and `409` on the module `PATCH`.
Fifteen minutes.

### §7.6 The `409` on `DELETE /users/{id}` is declared with a shape `LAST_ADMIN` does not have — 🟡 hygiene

**Evidence:** CONFIRMED.

**Where:** `backend/app/api/routes/users.py:96-117`; `backend/app/schemas/errors.py:40-41`;
`backend/app/services/user.py:87-88` (`LAST_ADMIN`), `:236` (`LAST_OWNER` with `extra`)

**What this is.** Deactivating a user can be refused two ways: `LAST_OWNER` (it would leave projects
ownerless), whose body lists those projects, and `LAST_ADMIN` (it would remove the last
administrator), whose body is the plain `{code, message}`.

**Why this can happen.** The route declares `LastOwnerErrorResponse` for every `409`, and that model
makes `projects` a required list.

**What it costs.** A client generated from `/docs` that deserialises the `409` strictly fails on a
`LAST_ADMIN` refusal — the one case where an admin most needs to read the message.

**What we should do.** Make `projects` optional, or declare the two shapes as a union. Fifteen
minutes.

### §7.7 The three download routes document no body — 🟡 hygiene

**Evidence:** CONFIRMED.

**Where:** `backend/app/api/routes/projects.py:~166-190` (`.xlsx`/`.zip`, chosen at runtime);
`backend/app/api/routes/checklist_items.py:73` (`.xlsx`); `backend/app/api/routes/mock_data_datasets.py:203-240`
(`.json`/`.xlsx`)

**What this is.** The export routes return a file with `response_class=Response`.
`.claude/rules/response-api.md` treats an undeclared success body as a defect unless a reason is
documented.

**Why this can happen.** None declares a `200` content type or the `Content-Disposition` header, and
none documents why.

**What it costs.** `/docs` shows a `200` with no body; a generated client returns an untyped blob.

**What we should do.** Add `responses={200: {"content": {<media type>: {}}, …}}` to each. Fifteen
minutes.

### §7.8 The eval-set create body marks every field optional — 🟡 hygiene

**Evidence:** CONFIRMED.

**Where:** `backend/app/schemas/eval.py:22-57`

**What this is.** `POST /projects/{id}/eval-sets` takes one of two bodies: generate (`name`,
`count`, `mix`, optional `sourcePath`) or translate (`sourceSetId`, `language`). A
`model_validator` enforces "exactly one shape".

**Why this can happen.** Both shapes live in one model, so every field is optional in the schema.
The shape rule exists only in the validator and a docstring. The reason is stated — a union would
prefix the field keys in `422` bodies — but the route's description does not say so.

**What it costs.** A generated client accepts a body that always answers `422`.

**What we should do.** Describe the two shapes in the route's `description` (and note that shape
errors key as `fields["request"]`). Fifteen minutes.

### §7.9 An eval set with a retired language would fail every list it appears in — 🟡 hygiene

**Evidence:** SUSPECT. Unverified: whether a shipped language can ever be removed —
`backend/app/core/language.py` says members are added, never renamed. A test that loads an eval set
row with language `xx` settles the behaviour.

**Where:** `backend/app/schemas/eval.py` (`EvalSetSummary.language: Language`);
`backend/app/services/eval.py:479`; compare `backend/app/schemas/project.py:64-70`

**Why this can happen.** A project's stored language that is no longer shipped reads as English
(`_unshipped_language_reads_as_english`). An eval set's does not: the strict enum would raise during
serialisation and answer `500` for the whole list.

**What we should do.** Reuse the project schema's tolerant validator. Fifteen minutes. See §9.33,
which would put that fallback in one place.

## §8 Job and status handling

### §8.7 Translating an eval set whose source is deleted mid-job fails with the wrong reason — 🟡 hygiene

**Evidence:** CONFIRMED.

**Where:** `backend/app/eval/generator.py:107-109`, `:197-235`;
`backend/app/repositories/eval_pair.py:18-24` (`list_for_set` uses `active_select`);
`backend/app/services/eval.py:251-262` (`delete_set` refuses only on an active run)

**What this is.** Since #69 an English eval set can be translated into another language; the worker
reads the source set's pairs and translates each one.

**Why this can happen.** User A requests a translation of set S → the worker starts → user B
deletes S, which is allowed because no *run* is active → the worker's read of S's pairs filters
out the soft-deleted rows and finds none → the translation is released as `failed` with "No
question could be translated with its code kept intact", and an `eval_set.failed` notification
goes out.

**What it costs.** The project's members are told the translation failed for a reason that is not
true. No row is stuck.

**What we should do.** Refuse to delete a set while a translation of it is generating — the same
guard §8.4 proposes for a set that is itself generating. One hour, both together.

## §9 Code health — dead code, duplication, and documentation

### §9.32 Five English-only constants survive the translated tables — 🟡 hygiene

**Evidence:** CONFIRMED (`grep -rnw` finds each defined once in `backend/app`).

**Where:** `backend/app/rag/grounding.py:87` (`NO_CONTEXT_ANSWER`), `:132` (`OUT_OF_SCOPE_ANSWER`);
`backend/app/mail/compose.py:315` (`RESET_MESSAGE`); `backend/app/services/checklist_export.py:21`
(`SHEET_TITLE`); `backend/app/services/mock_data_export.py:23` (`NO_DATA_LABEL`)

Each is `TABLE[Language.EN]`, left behind when the table it came from was translated. Nothing in the
application reads them; three are read only by tests (`tests/test_grounding.py`, `test_graph.py`,
`test_checklist_export.py`, `test_project_export.py`), which therefore test the English constant
rather than the language-picked path production takes. **Fix:** delete all five and point the
tests at the tables. Half an hour.

### §9.33 "An unset or unshipped language reads as English" is written out eight times — 🟡 hygiene

**Evidence:** CONFIRMED (`grep -rn "parse_language(.*) or Language.EN" backend/app` → 8).

**Where:** `backend/app/mockdata/generator.py:136`; `backend/app/checklist/generator.py:125`;
`backend/app/services/mock_data_dataset.py:249`, `:373`; `backend/app/services/checklist_module.py:421`;
`backend/app/services/project_export.py:102`; `backend/app/schemas/project.py:69`;
`backend/app/repositories/notification.py:211`

The eight copies agree today. If the fallback ever changes — the obvious next step is "the viewer's
language" — the change has to land in eight places and any one missed makes a shared document's
language depend on which code path produced it. `shared_language` in `app/core/language.py:113`
hides a ninth. The `"en"` server defaults in `backend/app/models/project.py:107` and
`backend/app/models/eval.py:110` are fine (a migration cannot import the enum) but deserve a comment
naming `Language.EN`. **Fix:** one `language_or_default()` in `app/core/language.py`. One hour.

### §9.34 The single- and multi-module checklist exports duplicate their filter and cap logic — 🟡 hygiene

**Evidence:** CONFIRMED.

**Where:** `backend/app/services/checklist_item.py:296-372` (`ChecklistItemService.export`);
`backend/app/services/project_export.py:140-200` (`ProjectExportService._checklist`), and its
mock-data cap at `:~210`

Both build the same `list_all(...)` arguments, raise the same `409 EXPORT_TOO_LARGE` with different
wording ("rows" vs "test cases"), and build the same audit `filter` details. A comment at
`project_export.py:~183` says "same envelope as the per-module export" — the comment is the only
thing keeping them aligned. **Fix:** extract the filter-to-details mapping and the cap check beside
`build_workbook` in `app/services/checklist_export.py`. One hour.

### §9.36 `docs/architecture.md` counts nine notification fan-out sites; there are thirteen — 📄 doc

**Evidence:** CONFIRMED.

**Where:** `docs/architecture.md:303`; the sites are `backend/app/ingestion/pipeline.py:140,184`,
`backend/app/checklist/generator.py:198`, `backend/app/mockdata/generator.py:218`,
`backend/app/services/checklist_change_set.py:186,255`, `backend/app/services/mock_data_change_set.py:144,210`,
`backend/app/services/membership.py:116`, and the four eval callers of `backend/app/eval/notifications.py`
(`eval/generator.py:147`, `eval/runner.py:213`, `queue/eval.py:120,162`)

`.claude/rules/notifications.md` already says thirteen. The architecture page predates #66 and also
words the generators as "two checklist and two mock-data", which reads as four. **Fix:** "Thirteen",
listing the eval generator, runner and terminal-failure path. `docs/PRD.md` §6 items 7 and 8 also
quote "40 events", "eleven members" and "nine call sites" (now 47, 15 and 13); they read as
snapshots, and adding "at the time" would make that explicit. Ten minutes.

### §9.38 A project-list docstring still describes phase 1 — 📄 doc

**Evidence:** CONFIRMED.

**Where:** `backend/app/services/project.py:192-194`

"In phase 1 it is unrestricted; phase 2 changes the resolver's body" — phase 2.1 shipped per-project
access long ago. **Fix:** "The scope comes from the access resolver and nowhere else." Two minutes.

## Verified correct in this sweep (2026-10-24), with what was checked

- **Access on every new or changed route.** `PATCH /projects/{id}` checks `require_readable_project`
  then `PROJECT_UPDATE` (`backend/app/services/project.py:245-246`). Every `DELETE` gates on a named
  permission after the readable-project check, with no `created_by` or inline `is_admin`.
  `/me/language` touches only the caller's row. No new prefix joined the forced-password-change
  exemptions, so `/me/language`, the export route and the eval routes are all gated.
- **The multi-module export cannot cross projects.** Modules come from the scoped
  `list_in_scope`; an id outside it is `404 CHECKLIST_MODULE_NOT_FOUND`; each part checks
  `CHECKLIST_READ` or `MOCKDATA_READ`; the unscoped record reads receive only ids from the scoped
  list; audit is written after every part is built.
- **Eval notifications resolve recipients through `access.py`.** `MembershipRepository.recipients_for`
  is still called only from `backend/app/core/access.py`. The eval events use
  `RECIPIENT_PERMISSIONS = EVAL_READ`, have no admin branch, and carry only `projectName`,
  `setName` and counts. The fan-out runs inside the transaction before the commit on all four sites;
  `_fail` in `backend/app/queue/eval.py` writes `failed` and notifies together.
- **Conversation privacy.** Every conversation read goes through `resolve_conversation_owner`;
  `prepare_turn` reads only the asker's own language. The new admin `by_prompt_version` feedback rows
  carry no voter.
- **Server-side request forgery** (making the server fetch an address an attacker chose). The
  validator still requires https, an allowlisted host, no credentials in the URL, and a global
  address for every resolved record; the clone re-validates at connect time and pins the result;
  redirects are off; the personal access token travels in the environment, never the command line.
  No new outbound fetch was added since `df7594e`.
- **Secrets and content.** No response model carries `encrypted_pat`. The new audit fields
  (`language`, `contentLanguage`, `moduleCount`, `sourceSetId`) are closed values or ids. The mail
  composers gained only a `Language` enum parameter, and the signatures in `.claude/rules/mail.md`
  match `backend/app/mail/compose.py:426,469` exactly. The call log's new `EVAL_TRANSLATE` feature
  records the error's class only.
- **Soft delete.** A project delete still hard-deletes its Qdrant points before the commit and
  soft-deletes results, runs, pairs, sets and feedback in the same transaction. Every new query
  (`content_languages`, `list_in_scope`, `get_by_modules`, `list_for_modules`, `live_translation`)
  filters `deleted_at`. The new partial unique index on translations excludes deleted rows.
- **Live events.** The eval set and run repositories stage an event on `claim`, `release`, `defer` and
  `claim_stranded`, and the services stage on create, start and soft delete.
- **Response contract.** Every schema inherits `ApiModel`; `SSE_EVENT_MODELS` lists all ten stream
  event classes. Since `df7594e` one `ErrorCode` was added (`EVAL_TRANSLATION_EXISTS`) and none
  renamed or removed. No route puts a scalar query parameter beside a query model.
- **Language resolution is written once.** "Stored language, else `Accept-Language`, else English"
  is `resolve_language` in `backend/app/core/language.py`, called from Ask and password reset only;
  the header is read at two routes. The backend language list is held to the frontend's by a test.
- **Counts that hold.** 19 rule files and 7 commands (`CLAUDE.md`); 50 `AuditRecorder` call sites
  (49 in services plus the CLI); 47 audit event types; 26 tables; 13 notification fan-out sites
  (`.claude/rules/notifications.md`); every `Settings` field in `backend/.env.example` and
  `docs/configuration.md`, and every field read except §9.17's two; the `backend/README.md` route
  table covers all routes.
- **Language docs.** `docs/rag.md`, `docs/langgraph.md` and `.claude/rules/rag.md` agree on the
  reply-language table and the translated refusals.

---

## See also

- [`audit-finding-solved-logs.md`](audit-finding-solved-logs.md) — the findings that have been fixed, verbatim
- [`ui-audit-findings.md`](ui-audit-findings.md) — the frontend sweep (`§U1`–`§U12`)
- [`PRD.md`](PRD.md) — the source of truth these findings are measured against
- [`../.claude/commands/audit-flow.md`](../.claude/commands/audit-flow.md) — how this sweep is run
- [`../.claude/rules/audit-findings.md`](../.claude/rules/audit-findings.md) — how a finding is written

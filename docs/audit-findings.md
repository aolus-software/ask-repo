# Audit findings

The standing record of **open** backend and architecture findings, written by `/audit-flow`,
plus each sweep's verified-correct notes so the next sweep can tell "clean" from "not audited".
A finding that has been fixed moves, verbatim, to
[`audit-finding-solved-logs.md`](audit-finding-solved-logs.md). A number cited below that is not
in this file (§1.1, §9.1 and so on) is there.

**Sweeps:** 2026-09-19 (at `f902f4c`, phase 2.2 branch) and 2026-09-27 (at `5b43564`, `main`).
Both were read-only. The first was followed by a separate, explicitly requested fix pass; the
second has had none.

**Ground truth:** [`PRD.md`](PRD.md), which outranks everything else, then `CLAUDE.md`, then
`.claude/rules/*.md`, then [`SECURITY.md`](../SECURITY.md). The rules outrank the code.

**Severity:** 🔴 bug (wrong behaviour reachable today) · 🟠 inconsistency / latent risk ·
🟡 hygiene · 📄 doc.

**Evidence:** every finding is CONFIRMED (the path was traced end to end and the trigger can be
named) or SUSPECT (the shape looks wrong but something is unverified — what, and what would
settle it, is stated).

## Open findings

**None.** Every finding raised so far has been fixed. The most recent ones were fixed on
`fix/audit-sweep-2026-09-27`, the same day they were found, and each is in
[`audit-finding-solved-logs.md`](audit-finding-solved-logs.md) under the sweep that raised it.
The next sweep adds its findings here.

Nothing either sweep found was security-relevant. Both found access, scoping, conversation
privacy, SSRF, soft delete, secrets, the response contract and job handling clean.

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

## See also

- [`audit-finding-solved-logs.md`](audit-finding-solved-logs.md) — the findings that have been fixed, verbatim
- [`ui-audit-findings.md`](ui-audit-findings.md) — the frontend sweep (`§U1`–`§U12`)
- [`PRD.md`](PRD.md) — the source of truth these findings are measured against
- [`../.claude/commands/audit-flow.md`](../.claude/commands/audit-flow.md) — how this sweep is run
- [`../.claude/rules/audit-findings.md`](../.claude/rules/audit-findings.md) — how a finding is written

# Audit findings

**Swept:** 2026-09-19 · **Scope:** the whole backend and the repository's documentation — access
control, read scoping, conversation privacy, ingestion and SSRF, soft delete against the vector
store, secret handling, the response contract, job and status handling, and code health.

**Branch:** `feat/phase-2.2-audit-trail`, at `f902f4c` — phase 2.1 (per-project RBAC) and phase
2.2 (the append-only audit trail) are both in the tree.

**Ground truth:** [`PRD.md`](PRD.md), which outranks everything else, then `CLAUDE.md`, then
`.claude/rules/*.md`, then [`SECURITY.md`](../SECURITY.md). The rules outrank the code.

**This sweep was read-only** — `/audit-flow` changed no application code, and the only file it
writes is this one. **A separate, explicitly requested fix pass on 2026-09-19 then resolved
§9.1 and §9.5–§9.11.** Each resolved heading carries `— ✅ RESOLVED 2026-09-19` and a note saying
what changed, with the original finding kept below it.

**Still open:** §1.1 and §1.2, tracked as [#40](https://github.com/aolus-software/ask-repo/issues/40)
and deliberately left for their own change; §2.1 (the scoping test's narrow grep); and §9.2–§9.4
(a dead error code and two duplicated guards), which are hygiene and were not in the fix pass's
scope.

**Severity:** 🔴 bug (wrong behaviour reachable today) · 🟠 inconsistency / latent risk ·
🟡 hygiene · 📄 doc.

**Evidence:** every finding is CONFIRMED (the path was traced end to end and the trigger can be
named) or SUSPECT (the shape looks wrong but something is unverified — what, and what would
settle it, is stated).

---

## Top priorities

Ordered security → data integrity → correctness → hygiene and doc. In the plainest language:

1. **Applying a proposed removal to a QA checklist can fail with a server error** (§9.1). The
   mock-data side of the app had this exact bug, fixed it, and wrote a comment explaining the fix.
   The checklist side never got it. No test catches it because both checklist tests for removals
   use an item id that does not exist, so they stop before reaching the broken line.
2. **A contributor is told per-project roles and permissions are not built yet** (§9.9), in the
   file that exists to tell contributors what to work on. The feature shipped in phase 2.1 and is
   the single most detailed section of `CLAUDE.md`.
3. **The whole instance shares five logins per minute** (§1.1), because every request reaches
   the backend from the frontend server rather than from a browser, so the per-address limit has
   one key for everybody. Six colleagues signing in within the same minute means the sixth is
   refused. Found after the sweep proper, from a question about why the audit trail's address
   column was empty (§1.2).
4. **Otherwise clean.** Read scoping, conversation privacy, SSRF defences, soft delete against
   the vector store, secret handling, the response contract and job handling were all swept and
   all came back clean. What was checked in each is recorded under its section, so
   the next sweep can tell "clean" from "not audited".
5. **Seven stale counts across six documents** (§9.5–§9.11) — rule files, routes, settings,
   tables, permission call sites, audit call sites, and the unit-test count. Each is small; the
   pattern is that every count in the repository drifts and none is enforced.

---

## §1 Access control — two findings, and the rest verified correct

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

### §1.1 The login rate limiter is one shared bucket for the whole instance — 🔴 CONFIRMED

> **Tracked as [#40](https://github.com/aolus-software/ask-repo/issues/40).** Deliberately not
> fixed in the pass that followed this sweep: the fix spans the backend-for-frontend, a config
> default and `docs/deployment.md`, which is its own change rather than something folded into
> phase 2.2.

**Where:** `backend/app/core/rate_limit.py:39-68` (`client_ip`), `backend/app/config.py:71`
(`trusted_proxy_hops: int = 0`), `frontend/app/api/auth/login/route.ts:22-24`, and
`frontend/app/api/[...path]/route.ts`.

**What this is.** `docs/PRD.md:115` specifies a login rate limit, and it is applied per route by
an explicit dependency rather than as global middleware. The limiter counts attempts per subject
per fixed window, and the subject includes the caller's address. `client_ip()` is carefully
written: it reads `X-Forwarded-For` counting from the **right**, discarding one entry per trusted
hop, precisely so nobody can evade a per-address limit by prepending a fake entry.

**Why this can happen.** The frontend is a backend-for-frontend. The browser talks only to Next,
and Next calls the API on its behalf — so from the backend's side, every request in the system
arrives from one peer: the Next server. Two things then combine:

1. `trusted_proxy_hops` defaults to `0`, which by design ignores `X-Forwarded-For` entirely and
   trusts the socket address.
2. The BFF forwards no `X-Forwarded-For` header. `frontend/app/api/auth/login/route.ts` sends
   only `content-type`, and the catch-all proxy attaches only the bearer.

So there is no header to trust even if hops were configured, and the socket address is the same
for everyone. The limiter's key contains one constant where it should contain the caller.

**What it costs.** Put the real numbers in: `login_rate_per_minute_ip` is **5**, over a
60-second window, and the per-address limiter `hit`s on **every** attempt — it is a route
dependency, so it counts successful logins too, not just failures.

That means the whole instance shares five logins per minute. Six colleagues arriving at nine on a
Monday and signing in within the same minute means the sixth gets `429 RATE_LIMITED` and is told
to try again later, having done nothing wrong. This is ordinary usage, not an attack.

`enforce_password_change_ip_limit` has the same shape and the same budget on its own key, which
makes it worse in one specific case: `must_change_password` forces a change on first login, so
onboarding a batch of new accounts drives everyone through `POST /auth/change-password` at once —
five per minute, instance-wide.

The mirror image is the security half: an attacker gets the entire instance's allowance to
themselves, and the control `docs/PRD.md` asked for is not doing the job it was specified to do.

**What still works, and it matters for the fix.** The per-email half is unaffected, and it is the
better-designed of the two: `LoginAttemptLimiter` counts **failures only**, clears on success, and
keys on the submitted address — none of which depends on the network path. So credential-stuffing
against one account is still bounded at 10 failures an hour. What is lost is the per-caller bound,
which is the half that stops one client spraying many accounts.

This is not the documented fail-open behaviour. Failing open on a Redis outage is a deliberate,
reasoned decision recorded in the module docstring. This is the limiter working exactly as
written, against a key that no longer identifies anybody.

**Evidence.** CONFIRMED by reading all three sides — the default, the header-handling, and both
BFF handlers — and by the recorded rows: the only `auth.login.succeeded` row on the development
instance carries `127.0.0.1`, which is the Next server rather than any browser.

**What we should do.** Two halves, and both are needed:

- Have the BFF forward the browser's address as `X-Forwarded-For` on the auth routes (Next exposes
  it on the incoming request), and set `trusted_proxy_hops` to match the real deployment topology.
  `docs/deployment.md` already covers the uvicorn `--proxy-headers` side of this for a reverse
  proxy in front of the backend; the BFF hop is the one that is missing.
- Until that lands, consider whether five per minute is the right number for a key that currently
  identifies the whole instance. Raising it is a worse fix than forwarding the address — it weakens
  the control everywhere to work around one hop — so it is a stopgap to take knowingly, if at all.

Half a day including a test that asserts two different browser addresses get two different buckets,
which is the test whose absence let this through. The test needs the BFF in the loop or a request
carrying the header; a backend-only test would have passed throughout, because the backend's own
code is correct — it is the deployment shape around it that changed.

### §1.2 The audit trail's only address column records the frontend, not the caller — 🟠 CONFIRMED

> **Tracked as [#40](https://github.com/aolus-software/ask-repo/issues/40)**, alongside §1.1 —
> they share one cause and the address fix has to land before this one can record anything
> better.

**Where:** `backend/app/api/deps.py:68-76` (`get_client_ip`), against
`backend/app/core/rate_limit.py:39-68` (`client_ip`).

**What this is.** Authentication events record `ip_address`, and `docs/PRD.md` §3.4's reasoning
leans on it: a failed login against an unknown address deliberately stores no email, and the
address is what keeps the enumeration attempt visible as a pattern from one host.

**Why this can happen.** `get_client_ip` returns `request.client.host` — the direct peer — and its
docstring is explicit that behind a reverse proxy this is the proxy, and that nothing parses
`X-Forwarded-For` by hand because a wrong address is worse than none. That reasoning is sound. But
the BFF is itself a hop, so in this architecture the direct peer is always the Next server, and
the column records the same value for every user on the instance.

**What it costs.** The pattern §3.4 relies on cannot be seen: every failed login from every user
shares one address, so "repeated attempts from one host" is true of the instance by construction
and tells an operator nothing. In development this reads as `127.0.0.1` and looks plausible, which
is what makes it easy to miss; under Compose it becomes the Next container's address.

Note the inconsistency this sits on: the audit path takes the raw peer while the rate limiter is
`X-Forwarded-For`-aware. Two resolutions of "who is calling", giving different answers.

**What we should do.** Resolve the caller's address in **one** place and have both readers use it —
the rate limiter's `client_ip` already has the careful implementation, so the audit path should
call it rather than keeping a second, simpler one. That fix depends on §1.1's: without a forwarded
header there is nothing better to record. Two hours once §1.1 lands.


---

## §2 Read scoping — verified correct, with one note

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

### §2.1 The single-point-of-scoping test is narrower than it reads — 🟠 SUSPECT

**Where:** `backend/tests/test_scoping_is_single_point.py`

**What this is.** `docs/PRD.md` §7 makes "read scoping happens in exactly one function" testable,
and this file is the test: it greps the source for the shapes that would indicate a route or
service deciding for itself which projects a caller may see.

**Why this matters.** One of its two patterns is
`created_by\s*[!=]=\s*actor\.id|actor\.id\s*[!=]=\s*\w+\.created_by`, which only matches a
comparison against a variable literally named `actor`. A service that named its parameter
`current_user` or `user` and compared `current_user.id != project.created_by` would pass the
guard untouched.

**What it costs.** Nothing today. A manual broadened search across the whole of `backend/app`
found zero comparisons under any other variable name, so nothing currently evades it. The cost is
future: the guard reads as stronger than it is, and the failure mode is silent — the test passes,
and the scoping rule the PRD makes a success criterion is quietly unenforced at that site.

**What we should do.** Broaden the pattern to match any identifier on the left of the comparison
rather than `actor` specifically, or match on `created_by` appearing in a boolean context at all
and allowlist the known-good sites. Under an hour. Evidence is SUSPECT only in the sense that no
site evades it today — the pattern's narrowness is CONFIRMED by reading it.

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

### §9.1 Applying a proposed removal to a checklist can fail with a server error — 🔴 CONFIRMED — ✅ RESOLVED 2026-09-19

> Fixed on `feat/phase-2.2-audit-trail`. `checklist_change_set.py` now sets
> `item.updated_at` after the soft delete, carrying the twin's comment across, and
> `test_remove_operation_soft_deletes_an_item_and_returns_it` covers the successful
> remove-and-serialise path. The test was confirmed to fail against the unfixed code
> before the fix was restored.
>
> Original finding follows.


**Where:** `backend/app/services/checklist_change_set.py:293-295`, against its working twin at
`backend/app/services/mock_data_change_set.py:228-235`. Coverage gap at
`backend/tests/test_checklist_change_set_service.py:159` and `:202`.

**What this is.** A generated checklist never lands as rows. Both producers write a *pending change
set* — a list of `add` / `update` / `remove` operations — and a human ticks the ones they accept
before `POST /checklist-change-sets/{id}/apply` writes exactly those. The apply path collects every
row it touched and returns them in the response, so the browser can redraw the grid without
refetching.

**Why this can happen.** For a `remove`, the checklist service soft-deletes the item and returns it.
Soft delete sets `updated_at` through `TimestampMixin`'s `onupdate=func.now()` — a *server-side*
expression, rendered into the SQL at flush time. The database has the new value; the Python object
does not, and will not until it is refreshed. `ChecklistItemResponse` requires a non-optional
`updated_at`, so serializing the returned item reaches for an attribute that is not loaded, and
SQLAlchemy's async session raises `MissingGreenlet` on the implicit lazy-load.

The mock-data service hits the identical shape and sets the attribute explicitly, with a comment
naming this exact failure. The checklist service does not.

**What it costs.** A tester ticks a proposed removal, clicks Apply, and gets a `500` on an operation
that **already committed** — the item really is deleted, but the response says the request failed.
The natural reaction is to try again. This is reachable on any apply containing a removal of an item
that still exists, which is the ordinary case for a regeneration against a module that has drifted.

**Why no test catches it.** Both checklist tests that name `"op": "remove"` target an item id that
does not exist, so `_apply_one` returns `None` before reaching the line that returns the item for
serialization. The successful-remove-and-serialize path is never exercised. The mock-data suite has
`test_remove_operation_soft_deletes_a_record`, which does exercise it — which is precisely why that
side got the fix and this side did not.

**What we should do.** Set `item.updated_at` explicitly after the soft delete, mirroring the twin,
and carry its comment across so the next reader knows why the line exists. Then add the missing test
against a real item id, mirroring `test_remove_operation_soft_deletes_a_record`. Under an hour
including the test. The broader lesson belongs in the two services' docstrings: these files are
parallel by construction, and a fix to one is a candidate fix for the other.

### §9.2 `MESSAGE_NOT_FOUND` is raised by nothing, and a test asserts otherwise — 🟡 CONFIRMED

**Where:** `backend/app/core/errors.py:49`; `backend/tests/test_errors.py::test_message_not_found_survives`.

**What this is.** `ErrorCode` values are a wire contract — members may be added but never renamed,
because a client may branch on them.

**Why this can happen.** No code raises `MESSAGE_NOT_FOUND`. A grep across `backend/app` returns
only its own declaration. There is no route that fetches a single message by id; the conversations
router raises only `CONVERSATION_NOT_FOUND` and `PROJECT_NOT_FOUND`. The test that guards it is
documented "Still raised by the conversations surface, which this milestone does not touch" — a
claim that is false today.

**What it costs.** Nothing at runtime. The cost is that a passing test asserts something untrue
about the codebase, which is worse than no test: a reader checking whether the code is reachable
finds a green assertion saying it is.

**What we should do.** Decide which it is. If a per-message route (feedback, a permalink) is coming,
leave the member and fix the test's docstring to say it is reserved. If not, delete the member and
the test together in one change. Fifteen minutes either way.

### §9.3 The project-readable guard is copy-pasted across five services — 🟡 CONFIRMED

**Where:** `backend/app/services/conversation.py:279-289`,
`backend/app/services/mock_data_dataset.py:426-435`, and the same body in
`checklist_module.py`, `indexed_path.py` and `project.py`.

**What this is.** Four lines that resolve the caller's project scope, fetch the project, and raise
`404 PROJECT_NOT_FOUND` if it is absent *or* outside scope — the rule that a project you hold no
membership on must be indistinguishable from one that does not exist.

**Why this matters.** All five bodies are currently identical, so nothing is wrong today. But the
reasoning for the `404` — which is a security decision, not a style choice — is written out at only
one of the five sites, and a sixth service will be written by copying whichever of the five its
author finds first.

**What it costs.** Developer time, and a slow erosion of the "decided in one place" property that
`docs/PRD.md` §7 makes a success criterion.

**What we should do.** Lift it into `backend/app/core/access.py` as
`require_readable_project(projects, project_id, actor) -> Project`, beside the two resolvers it
already calls, and carry the `404`-not-`403` reasoning with it. Two hours including the call-site
edits.

### §9.4 The answerable-index guard is copy-pasted across three services — 🟡 CONFIRMED

**Where:** `backend/app/services/checklist_module.py:425-448`,
`backend/app/services/conversation.py:291-312`, `backend/app/services/mock_data_dataset.py:392-411`.

**What this is.** The check that a project has an index and that the index was built by the
embedding model currently configured — raising `PROJECT_NOT_READY` or `EMBEDDING_MODEL_CHANGED`.
The second is the guard that pays for itself: swap one 768-dimensional model for another and the
vector store accepts the query happily, returning nearest neighbours in a space the collection was
never built in, with no error anywhere.

**Why this matters.** Three identical copies. Unlike §9.3 this one is self-aware —
`mock_data_dataset.py` docstrings "Same guard `ChecklistModuleService._require_answerable`
applies" — which is better than hiding it, but a docstring is not a shared function.

**What it costs.** Developer time. A change to the mismatch condition needs three edits, and the
consequence of missing one is the silent-quality-drop failure the guard exists to prevent.

**What we should do.** Hoist to a shared `require_answerable(project, settings)` and have all three
call it. An hour.

### §9.5 A stale docstring claims a `created_by` gate that no longer exists — 📄 CONFIRMED — ✅ RESOLVED 2026-09-19

> Fixed. The docstring names `item.edit`.
>
> Original finding follows.


**Where:** `backend/app/schemas/checklist.py:143` says "Gated on `created_by`/`is_admin` (spec
2.5)"; the real enforcement is `backend/app/services/checklist_item.py:155`, which calls
`require_permission(actor, item.project_id, Permission.ITEM_EDIT)`.

**What it costs.** The code is correct; the comment describes the design phase 2.1 deliberately
removed. `CLAUDE.md` is explicit that `created_by` is attribution and nothing else, and that the
inline gates were deleted along with their error codes. A maintainer trusting this docstring could
reintroduce one "to match the docs" — which is the failure mode `.claude/rules/contradiction-halt.md`
exists to catch, arriving through a comment instead of a request.

**What we should do.** Change the docstring to name `item.edit`. Two minutes.

### §9.6 The rule-file count is wrong in three documents, three different ways — 📄 CONFIRMED — ✅ RESOLVED 2026-09-19

> Fixed. `docs/README.md`, `docs/codebase.md` and the root `README.md` all say fourteen.
>
> Original finding follows.


**Where:** `docs/README.md:96` and `docs/codebase.md:279` say 13; `README.md:369` says "twelve
enforceable conventions"; `CLAUDE.md:401` says fourteen. `.claude/rules/` contains **14** files.

**What it costs.** `CLAUDE.md` is the load-bearing one and is right. The other three send a reader
looking for fewer conventions than exist, and the two that disagree with each other undermine trust
in every other number in those files.

**What we should do.** Update all three to fourteen. Ten minutes. Worth considering whether a test
should assert this the way `tests/test_audit_coverage.py` asserts the event catalogue — see §9.11.

### §9.7 Three counts in `docs/README.md` are stale, and the accurate figure lives elsewhere in the same repository — 📄 CONFIRMED — ✅ RESOLVED 2026-09-19

> Fixed. `docs/README.md` now says 67 routes, 80 settings and 17 tables; the root
> `README.md` says 17 tables.
>
> Original finding follows.


**Where:** `docs/README.md:96` says 55 routes (actual: **67**, matching `docs/codebase.md:141` and
`backend/README.md`'s own table); `docs/README.md:56` says 71 settings (actual: **80**, matching
`docs/architecture.md:243`); `docs/README.md:20` and `README.md:353` say 13 tables (actual: **17**,
matching `docs/data.md:14` and `docs/codebase.md:147`).

**What it costs.** `docs/README.md` is the index a reader lands on. It undercounts the API surface
by 12 routes, the configuration surface by 9 settings, and the schema by 4 tables — and in each
case a deeper document in the same directory has the right number, so the index is the least
accurate page about facts the pages it links to state correctly.

**What we should do.** Correct all four numbers from the accurate sources named above. Twenty
minutes.

### §9.8 Two rules state call-site counts that have since grown — 📄 CONFIRMED — ✅ RESOLVED 2026-09-19

> Fixed by rewording rather than renumbering: both call-site figures now read as a
> record of what was true when phase 2.1 landed, with today's count beside them. The
> audit figure is stated exactly (39 — 38 services plus the CLI) in `CLAUDE.md` and
> `.claude/rules/audit-trail.md`.
>
> Original finding follows.


**Where:** `.claude/rules/router.md:130` and `docs/codebase.md:105` say `require_permission` has 15
call sites; there are **20**. `CLAUDE.md:239` says "~37" audit recorder call sites and
`.claude/rules/audit-trail.md:131` says 37; there are **38** in services plus one in the
`seed-admins` CLI.

**What it costs.** The `require_permission` figure is used rhetorically — "phase 2.1 touched none of
the 15 call sites" — which is a true historical fact about when RBAC landed but reads in the present
tense, so someone checking "have I covered every call site?" stops five short. The audit figure is
hedged with a `~` and costs little, but a test exists specifically to keep that catalogue exact, so
the prose should track it.

**What we should do.** Reword the `require_permission` claim to name phase 2.1 explicitly as the
moment it counted 15, or update it to 20 if a live figure is intended. For the audit count, state
the exact number and decide whether the CLI seed path is inside or outside it — 38 and 39 are both
defensible and the ambiguity is the only real problem.

### §9.9 `CONTRIBUTING.md` tells contributors that per-project RBAC will not be merged — 🟠 CONFIRMED — ✅ RESOLVED 2026-09-19

> Fixed. The stale scope line is gone and the Conventions section reads in the past
> tense, naming `app/core/access.py` and `require_permission` as what already exists.
>
> Original finding follows.


**Where:** `CONTRIBUTING.md:172` lists "Per-project roles and permissions — that's phase 2, and it
wants a design first" under things that will not be merged; `CONTRIBUTING.md:126` frames it in the
future tense. Against `CLAUDE.md:165-214`, `backend/app/core/access.py`,
`backend/app/core/permissions.py`, the `roles` / `role_permissions` / `project_memberships` tables,
and nine live member and role routes in `backend/README.md`.

**What this is.** `CONTRIBUTING.md`'s "what won't be merged" list exists so a contributor does not
spend a weekend on something out of scope.

**Why this can happen.** The feature shipped in phase 2.1 and the contributing guide was not
updated with it.

**What it costs.** This is the most actively misleading finding in the sweep. A contributor reading
it concludes that proposing anything touching per-project roles is premature — when the feature is
not only built but is the single most consequential design constraint in the repository, with its
own detailed section in `CLAUDE.md` and a test enforcing its single-point-of-scoping property.
Worse, they may conclude there is no access-control convention to follow, and write a route that
filters projects itself.

**What we should do.** Remove the stale scope line, and change the Conventions section's framing
from future to past tense. This is a document drifting behind shipped code, not a disagreement with
the PRD, so no decision is needed — just the edit. Half an hour, including a read for any other
future-tense phase-2 framing in the same file.

### §9.10 `CONTRIBUTING.md`'s test count is roughly half the real one — 📄 CONFIRMED — ✅ RESOLVED 2026-09-19

> Fixed. The number is gone; it says "the whole unit suite", which does not go stale.
>
> Original finding follows.


**Where:** `CONTRIBUTING.md:100` says "passes all 563 unit tests"; the suite currently collects
**1150** (1161 with the two opt-in markers).

**What it costs.** Minor. The point being made — that a scripted-fake suite proves wiring rather
than prompt correctness — survives any number. But a reader gauging how much `make check` actually
exercises is off by about half.

**What we should do.** Update the number, or drop it and say "the unit suite", since it moves every
week.

### §9.11 The `[Unreleased]` changelog is missing two shipped user-visible changes — 📄 CONFIRMED — ✅ RESOLVED 2026-09-19

> Fixed. `[Unreleased]` gains the view-in-dialog entry and a new `### Fixed` section
> covering the end-date filter, the `[object Object]` payload, the filter-row layout,
> the checklist remove-branch 500, the four false-emptiness surfaces and the silent
> Generate — plus a `### Changed` section for the toast voice and the column order.
>
> Original finding follows.


**Where:** `CHANGELOG.md:12-42` — five bullets, all under `### Added`, no `### Fixed` section at
all. Against commits `f902f4c` and `6d084bf` on this branch.

**What this is.** `.claude/rules/documentation.md` requires a user-visible change to land in
`[Unreleased]` in the same change that ships it: a route, a JSON field, an `ErrorCode`, a default,
or a fixed defect.

**Why this can happen.** Two commits landed after the documentation task for this phase was
completed, so neither was covered by it.

**What it costs.** An operator reading the changelog before upgrading does not learn that the audit
screen gained an inline detail view, nor that its filter row was previously rendering every control
clipped to a few characters — which matters if they had already hit it and worked around it, or
reported it.

**What we should do.** Add an `### Added` bullet for reading an event without leaving the list, and
open a `### Fixed` section for the filter-row layout. Note this is **in addition** to the two
already-scheduled entries for the end-date filter and the `[object Object]` payload, which were
identified before this sweep and are not re-filed here.

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

## See also

- [`ui-audit-findings.md`](ui-audit-findings.md) — the frontend sweep (`§U1`–`§U12`)
- [`PRD.md`](PRD.md) — the source of truth these findings are measured against
- [`../.claude/commands/audit-flow.md`](../.claude/commands/audit-flow.md) — how this sweep is run
- [`../.claude/rules/audit-findings.md`](../.claude/rules/audit-findings.md) — how a finding is written

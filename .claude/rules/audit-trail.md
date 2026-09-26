# Audit Trail Rules

Everything under `app/core/audit.py`, plus every service that writes — `auth`, `user`, `project`,
`membership`, `role`, `checklist_module`, `checklist_item`, `checklist_change_set`,
`mock_data_dataset`, `mock_data_change_set`, `mock_data_record`, `conversation`, `password_reset` — and the two
export paths. Read `persistence.md` and `router.md` alongside this — they own the table and the
route; this file owns what must be recorded and what must never be.

Design: `docs/superpowers/specs/2026-09-16-phase-2.2-audit-trail-design.md`.
Intent: `docs/PRD.md` §2.1, Phase 2.2.

## Principle: if it changed data or moved data out, it leaves a record

`created_by` is attribution — it says who made a row, and nothing about who changed or destroyed
it. Before this trail existed, a deleted project took its `created_by` with it and **nothing
anywhere recorded who deleted it**.

So the rule is not "log the interesting things". It is:

> **Every write, and every export, records an audit event. No exceptions beyond the six named
> in this file.**

This is written as a rule rather than a list because a list goes stale the moment someone adds a
route, and the failure is silent: the route works, the tests pass, and the trail simply has a hole
nobody discovers until the day it is needed.

## What must record an event

| Kind of action | Examples | Event shape |
| --- | --- | --- |
| **Create** | a project, a user, a role, a module, a test case by hand, a membership | `<resource>.created` |
| **Update** | edit a user, rename or re-point a module, edit what a test expects, change a role's permissions, change a member's role | `<resource>.updated` |
| **Delete** | a project, a module, a test case, a mock-data record, a membership, a conversation | `<resource>.deleted` / `.revoked` / `.deactivated` |
| **Destructive bulk** | clearing the recorded results a filter selects | `<resource>.results_cleared` |
| **Promote a proposal** | applying or discarding a checklist or mock-data change set | `<resource>.applied` / `.discarded` |
| **Request expensive work** | reindex, checklist generation, mock-data generation | `<resource>.<action>.requested` |
| **Move data out** | the checklist spreadsheet, mock data as JSON or spreadsheet | `<resource>.exported` |
| **Authenticate** | login, **failed** login, logout, password change, admin reset, refresh replay, password reset request, password reset confirm | `auth.*` / `user.password.reset` / `auth.password_reset.requested` / `auth.password_reset.completed` |

**An export is a write for this purpose even though it changes nothing.** It is the one action
that takes a private repository's derived content out of the instance, and `docs/PRD.md` §9 treats
egress as a category of its own. "It's only a GET" is not a reason to skip it.

**A destructive bulk operation is the highest-value row in the table.** `DELETE /checklist-items`
with a filter can erase a week of a tester's recorded observations without deleting a single row,
and it is the only write in the app that destroys human-recorded work that way.

## The six exemptions, and each one's reason

Named here so a later reader finds a **decision** rather than what looks like an oversight. Do not
"fix" these; changing one is a PRD change first.

1. **Ordinary reads.** Listing, getting, browsing indexed paths, asking a question. The trail
   records what changed; a read log on the hot path is a different feature with a different write
   rate, and `docs/PRD.md` §2.5 puts per-call records in their own store for exactly that reason.
2. **Refinement-chat turns.** `POST /checklist-modules/{id}/messages` and its mock-data twin write
   a message and a *pending change set*. `docs/data.md`'s third storage rule is that a proposal is
   not a row — the audited event is the `apply`, where content of record actually changes.
   Auditing the turn too records an intention twice and makes the trail noisier than what it
   describes.
3. **The ask route.** `POST /conversations/{id}/messages` is not audited, and this is the PRD's own
   line: §2.5 rules out folding per-model-call records into this table **by name**, because "one
   table would bury 'an admin deactivated an account' under two hundred map calls". Token, timing
   and outcome per call belong to Phase 2.5's record, not to this one.
4. **Ingestion outcomes.** A finished or failed index has no actor — nobody did it, a job did.
   `projects.status` and `projects.error` already hold the result, and `NULL` actor is reserved for
   the two cases where a *human* acted without an authenticated identity: a failed login, and the
   `seed-admins` CLI.
5. **A user's own notification state.** Marking a notification read, marking all read,
   and changing notification preferences. Three reasons, and all three are needed: the
   row is private to one user; it describes no shared resource and no change to one;
   and its write rate is proportional to **attention** rather than to change. That last
   one is what makes it a flooding risk rather than merely a low-value row — a bell
   clicked forty times a day would bury `user.deactivated` under exactly the noise
   §2.5 refuses for the ask route.
6. **Email delivery attempts.** Sending a reset link or a notification email is a transport of an
   event already recorded elsewhere — the notification event, or the `auth.password_reset.requested`
   row — not a new action. No human performs the send: a FastAPI background task drains it for a
   password reset, and the worker's `mail_loop` drains it for notification email. The audit trail
   records *human actions that change data*; a mail loop pushing bytes through an SMTP service is
   infrastructure, and auditing each send would write one row per recipient per event. Delivery
   success or failure is recorded on the row itself — `notifications.email_state`/`email_sent_at`,
   `password_reset_tokens.sent_at` — and visible to operations through a table query, never
   through the audit trail.

## Adding a mutating route means adding an event, in the same change

A new `POST`, `PATCH`, `PUT`, `DELETE` or export route is not finished until:

1. Its event name is in the catalogue in `app/core/audit.py`.
2. Its allowlisted `changed` fields are declared there too (see below).
3. The service method records it — **after its own commit**, never before.
4. `tests/test_audit_coverage.py` names the operation.
5. `docs/data.md`'s event list and `CHANGELOG.md` mention it.

`tests/test_audit_coverage.py` enforces this **in both directions**: every audited operation must
emit the expected event, and every name in the catalogue must have at least one recording site. A
catalogue entry cannot exist unwritten, and a write site cannot invent a name.

## Never the secret, and never the content

Two separate bans, from `docs/PRD.md` §9 and §2.5. An audit trail is by definition something an
operator reads, so it is subject to the same obligation as a log line or an error message.

**What enforces that here is the allowlist, not `scrub`.** There is deliberately no `scrub` call in
`app/core/audit.py` or in any recording service, and adding one would be defence at the wrong
layer: `scrub` needs the secret in hand to replace it, and the recorder is handed plain scalars a
service chose, never the clone URL or the token. A value can only reach `details` by being named in
`CHANGED_FIELDS` or `CONTEXT_KEYS`, and `AuditEntry.details()` raises `ValueError` on a key that is
not — so an accidental reintroduction fails loudly at the write rather than quietly in the row. The
scrubbing that matters for secrets happens where the secret exists, on the clone path
(`app/ingestion/cloner.py`, `pipeline.py`), before anything derived from it is passed along.

**Never the secret.** No passwords, no tokens, no PATs, no clone URL with credentials embedded. A
`repo_url` is stored **host-only**.

**Never the content.** No prompt, no completion, no message text, no conversation title, no chunk
of source code, no generated test case body. `docs/PRD.md` §2.5's reasoning is the binding one:
that content is a private repository's code and the user's own question, and storing it puts a
second copy outside the lifecycle §5.1's delete rule governs — so deleting a project would leave
its code behind in a table nobody thinks of as holding code.

Three mechanisms hold this, and none of them is "remember to be careful":

- **`changed` is an allowlist per event type**, declared in `app/core/audit.py` — never a diff of
  the model's dirty attributes. A generic differ would start writing `password_hash` and
  `encrypted_pat` the moment someone adds a column to `users` or `projects`. **A new column is
  invisible to the trail until someone names it**, and that is the correct failure direction.
- **`target_label` is `NULL` for a conversation**, because its title derives from the user's first
  question. Every other resource's label is a name a human chose for a shared thing.
- **A failed login stores the submitted address only if it matches a live user row.** People paste
  passwords into the email field, and this row is built from raw request input. No match means
  `actor_user_id` and `actor_email` stay `NULL` and `details` carries `{"unknownAccount": true}`.
  What it gives up is enumeration detail; `ip_address` still shows the pattern.

## Conversations record metadata only

Conversation creation and deletion **are** audited, with `actor_user_id`, `target_id` and
`project_id` set and `target_label` `NULL`. An administrator can therefore see that a colleague
opened and deleted a conversation against a given project, and when — never what it was about, and
never any message in it.

This is a **deliberate amendment** to what `docs/PRD.md` §4.2 and §7 previously stated without
qualification, made with the trade-off on the table. What survives unchanged is the part that
carries the weight: there is still **no administrator bypass on any route under
`/conversations`**, every miss there is still `404`, and no message content reaches any operator
surface. Do not widen this to the ask route or to titles (see exemption 3 and the content ban).

## The record is written after the commit, and the recorder never raises

`AuditRecorder.record` takes the **sessionmaker** and opens its own session, so the write does not
depend on when FastAPI closes the request's `AsyncExitStack`. On any `Exception` it logs the whole
event at `WARNING` and returns.

**It never raises.** That is what makes "an audit failure cannot fail a user's action" structural
rather than a promise each of the 41 call sites keeps (40 in services, plus the `seed-admins`
CLI). A login must not fail because a log write did.

**The accepted consequence, and it is not to be quietly reframed as a guarantee:** an action that
commits and then crashes before its audit write leaves no row, silently. The trail is a strong
record, not a complete one. The `WARNING` is the fallback; the log is not the record.

Two consequences at the call site:

- **Capture `before` scalars into locals before mutating, and `after` before committing.** Hand
  the recorder a plain dict. Nothing in the audit path holds an ORM reference — a recorder that
  cannot touch a `Session` cannot be made to re-read a row that is now soft-deleted, or hold one
  open past the request.
- **Record after the commit that made the change true**, never before. A row describing a write
  that rolled back is worse than no row.

For `project.deleted` the full order is: capture label and counts → hard-delete the Qdrant points
→ commit the soft delete → record. `docs/data.md` requires the vector delete before the commit, so
if Qdrant refuses, nothing commits and nothing is recorded — correct, because no deletion happened.

**A notification is written *before* the commit at the same call sites, and both
orderings are correct.** An audit failure must not fail a user's action, so the audit
write goes after; a lost notification is the feature not working, so the fan-out goes
before and shares the transaction. See `.claude/rules/notifications.md`.

## Append-only is structural, not a convention

`audit_events` carries **neither** `TimestampMixin` **nor** `SoftDeleteMixin`
(`app/models/base.py`), and both omissions are load-bearing:

- **No `deleted_at`** — `BaseRepository.active_select()` filters only when the model carries the
  mixin, so there is no soft-delete path to reach these rows through at all.
- **No `updated_at`** — a column recording a mutation has no business on a row that is never
  mutated. `created_at` is declared explicitly.

There is exactly one delete path: `AuditEventRepository.delete_older_than(cutoff)`, a hard delete
driven by `AUDIT_RETENTION_DAYS` from the worker's 60-second tick. **It takes a cutoff and nothing
else** — no actor filter, no event-type filter — so the one code path that removes these rows
cannot be aimed at anyone's entries. An operator sets a window; nobody erases a row.

Never add an `update` method to the repository. Never add a route that writes: the router is reads
only (`GET /audit-events`, `GET /audit-events/{id}`), which is how append-only shows up on the wire
and not only in the schema.

## The payload shape is one envelope

```json
{
  "changed": { "<field>": { "before": "<scalar|list|null>", "after": "<scalar|list|null>" } },
  "<contextKey>": "<scalar>"
}
```

- `changed` holds **only fields that actually changed** — never a snapshot of the row. A create
  writes `"before": null` throughout; a delete writes `"after": null`. One renderer handles all
  three shapes.
- Flat keys beside it carry immutable context that is not a change: `patSupplied`, `forced`,
  `unknownAccount`, `source`, `format`, counts.
- Keys are `camelCase` **as stored**, so `ApiModel` has nothing to translate on the way out and
  the stored bytes match the wire.
- `details` is capped at 8 KB. Nothing entering it is scrubbed, and nothing needs to be: the
  allowlist above is what bounds it, and a key nobody named cannot be written at all.

An event whose whole meaning is its name carries no `changed` block at all —
`auth.password.changed` and `user.password.reset` are the examples, and they have to be: both
sides of that diff are what the content ban forbids storing.

## Who reads it

Admins, instance-wide, through the existing `AdminUser` dependency. The auth, account and export
events span no project, so a per-project scope does not describe this read — it is a read on a
different axis, not a narrower project scope.

The row still carries `project_id`, so a future per-project read is one permission plus a
`require_permission` call. **If that is ever added it goes through `app/core/access.py` like
everything else** — never a filter beside the resolver (`docs/PRD.md` §7) — and `GET
/audit-events/{id}`'s `404` then acquires the security meaning it does not have today.

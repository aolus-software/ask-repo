# Notifications

Every long-running operation in AskRepo used to finish in silence. A twenty-minute index, a
checklist generation, a mock-data generation — the only way to learn any of them finished was to
reload the screen showing its status column. That was tolerable for the person who pressed the
button and useless for everyone else, which is the wrong way round for a checklist §4.3 publishes
to every member of its project: the reviewer who has to act is routinely not the person who
started the generation.

A notification is a row, and in-app delivery — a bell with a polled unread count, plus a full
`/notifications` page — is one transport against it. Email is a second transport against the same
record, at Phase 2.4; it adds no table and no read state of its own. See
[`PRD.md`](PRD.md) §2.1, Phase 2.3, for the milestone record — this page does not restate it.

---

## The event table

One row per `NotificationType` member, verified against the catalogue in
`app/core/notifications.py` (`RECIPIENT_PERMISSIONS`, `ACTOR_EXCLUDED`, `DIRECT_EVENTS`,
`TARGET_TYPES`).

| Event | Raised when | Who receives it | Links to |
| --- | --- | --- | --- |
| `project.ready` | a first index finishes | members with `project.read` | the project |
| `project.failed` | a first index fails terminally | members with `project.reindex` | the project |
| `project.reindex.finished` | a reindex finishes | members with `project.read` | the project |
| `project.reindex.failed` | a reindex fails terminally | members with `project.reindex` | the project |
| `checklist_change_set.pending` | a checklist generation proposes a change set | members with `changeset.apply` | the module |
| `checklist_change_set.applied` | someone applies a checklist change set | members with `checklist.read`, **not** the actor | the module |
| `checklist_change_set.discarded` | someone discards one | members with `checklist.read`, **not** the actor | the module |
| `mock_data_change_set.pending` | a mock-data generation proposes a change set | members with `changeset.apply` | the module |
| `mock_data_change_set.applied` | someone applies a mock-data change set | members with `mockdata.read`, **not** the actor | the module |
| `mock_data_change_set.discarded` | someone discards one | members with `mockdata.read`, **not** the actor | the module |
| `membership.granted` | someone is added to a project | the new member only | the project |

Both change-set families link to the checklist module rather than to the change set's own id
(`target_type` is `checklist_module` for all six), because the Mock Data tab lives at
`/checklist/[moduleId]` rather than at a route of its own — a change set's own id names nothing a
recipient could navigate to.

---

## Three rules the table does not show

**Actor exclusion is per-event.** You are not told about your own click — applying or discarding
a change set is something you just did, and a notification about it is noise. You *are* told the
reindex you started twenty minutes ago finished — that is something you cannot otherwise know,
and it is the entire feature for the person who pressed the button and walked away. Neither
`pending` event has an actor at all: a worker raised it.

**An administrator with no membership on a project receives nothing about it.** Permission to see
a project is not interest in hearing about it. `require_permission` lets an administrator bypass
every check; the notification resolver does not mirror that, on purpose — an admin is notified
about the projects they hold a membership on, exactly like everyone else. Adding a bypass for
symmetry is the bug, not a missing feature (`.claude/rules/notifications.md`).

**A deactivated account receives nothing**, even though its memberships are left intact rather
than soft-deleted so that reactivating the account restores exactly the access it had. A
notification for someone who cannot currently log in is an unread count nobody will ever clear,
and reactivating them should not hand back a month of stale nudges.

---

## Configuration

| Setting | Default | What it does |
| --- | --- | --- |
| `NOTIFICATION_RETENTION_DAYS` | `90` | How long a notification is kept. `0` keeps forever. The worker's existing 60-second tick prunes past the window, by age and regardless of read state |

**Why this defaults to `90` while `AUDIT_RETENTION_DAYS` defaults to `0`.** The two settings look
parallel and answer different questions. Audit keeps forever by default because a fresh instance
must not silently start discarding the one record whose entire purpose is being the record. A
notification is not a record — it is a nudge with a shelf life, and keep-forever would grow a
table nobody reads past a week. Pruning ignores read state on purpose: an unread badge that can
never reach zero is a badge people stop looking at, so a 90-day-old unread notification is deleted
exactly as a read one is.

Full definition, including the cascade and the prune mechanism: [`configuration.md`](configuration.md).

**Not configurable, deliberately.** The bell's 60-second poll interval is a frontend constant
rather than a setting, and there is no socket or SSE stream for notifications — a per-user
notification stream is a different connection lifecycle than the one answer-stream SSE machinery
was built for, and polling an integer is honest at this scale. See [`PRD.md`](PRD.md) §2.1.

---

## Preferences

Per user, per event type, two switches: `in_app` and `email`. Rows in `notification_preferences`
are sparse and **absence means on** — a user with no row for an event type is treated as
subscribed to it, so a new event type is on for everybody with no migration and no backfill.

The email switch is stored and rendered **disabled**, with a line saying email delivery is not
configured on this instance — Phase 2.4 turns it on by adding a sender, not by touching the
schema.

**The counter-intuitive part, stated outright because it reads as a bug otherwise: muting in-app
does not stop the row being written.** A `notifications` row is written for every resolved
recipient regardless of their preference; muting in-app sets that row's `in_app_visible` to
`false` instead of skipping the row. The row is what Phase 2.4's email is a delivery attempt
against — a user who muted in-app but wants email needs that row to exist, and suppressing it at
write time would leave nothing for email to send against.

---

## Where the code is

- The catalogue, the recipient map, the actor-exclusion set and the per-event `details` allowlist
  — `app/core/notifications.py`.
- Recipient resolution — `resolve_notification_recipients` in `app/core/access.py`, beside
  `resolve_project_scope`.
- The write path — `app/services/notification_fanout.py`.
- The invariants each of the above must hold, and why each fails silently when broken —
  `.claude/rules/notifications.md`.
- The full design — `docs/superpowers/specs/2026-09-20-phase-2.3-notifications-design.md`.

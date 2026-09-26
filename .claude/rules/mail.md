# Mail Rules

Everything under `app/mail/`, `app/services/password_reset.py`, the three `/auth/password-reset/*`
routes, and the email half of `app/services/notification_fanout.py`. Read `audit-trail.md` and
`notifications.md` alongside this — all three cover per-action decisions about who, what, and where;
this file specifies what content may leave the network and how.

Design: `docs/superpowers/specs/2026-09-26-phase-2.4-mail-design.md`.
Intent: `docs/PRD.md` §2.1, Phase 2.4.

Every invariant here fails silently when broken — no exception, no failing request, just an
email that reaches the network with something inside it that should have stayed private. That
is what makes these rules rather than preferences.

## The composer's signature is the enforcement

`app/mail/compose.py` builds every message that leaves the instance, and the rule is not "check
that every message is okay" — it is "accept no parameter that would allow one to leave the
code". `tests/test_mail_compose.py` pins both signatures; adding a parameter means updating that
test, which is what makes a silent addition impossible.

- **`compose_notification(*, event_type, target_type, target_id, project_id, to, settings)`.**
  No `name`, no `path`, no `details` — nothing that could carry a display name, a repository
  name, a module name, or free text out of the app. The subject and body sentence come from a
  fixed table (`MESSAGES`, keyed by `NotificationType`) and the only thing composed per call is
  a link built from ids: `_link` returns `/checklist/{target_id}` for a checklist module target
  and `/projects/{project_id}` otherwise.
- **`compose_password_reset(*, raw_token, to, settings)`.** The reset link is the entire message.
  `raw_token` is handed in as an argument and lives nowhere else — see the token lifecycle below.

## Subjects are fixed strings per event, bodies are plain text

`compose_subject` builds `"{message} | {MAIL_APP_NAME}"`, prefixed with `"[{APP_ENV}] "` in
every environment except `production`, where the tag is omitted. There is no per-call
templating: `MESSAGES` maps each `NotificationType` to one subject and one body sentence, and
the reset email's subject is the same fixed string (`RESET_MESSAGE`) every time.

Bodies are plain text (`EmailMessage.set_content`), never HTML. No styling, no rendering logic
in the mailer — a reset link is a bare URL on its own line, `https://.../reset-password#token=…`.

## The raw reset token exists only in memory and in the email

`PasswordResetService.request` mints 32 random bytes and stores only `sha256_hex(raw_token)` in
`password_reset_tokens.token_hash`. The raw value is carried as a field on `PendingResetEmail`,
handed to `deliver_password_reset` as an argument, and never written anywhere — not a log line,
not the audit trail (`.claude/rules/audit-trail.md` exemption 6), not a second column.

- **Single use is `used_at`.** `PasswordResetTokenRepository.get_usable_by_hash` only returns a
  row with `used_at IS NULL`, `revoked_at IS NULL`, and `expires_at > now()`, and locks the row
  with `with_for_update()` so two concurrent confirms against the same token cannot both read it
  usable. `confirm` stamps `used_at` in the same transaction that changes the password.
- **Sent once, from a `BackgroundTasks` task, after the response.** `request_password_reset`
  answers `202` before the send is attempted, so a live account is not measurably slower to
  respond than an unknown one at the HTTP layer — a live account still costs a few extra
  database writes (revoking prior tokens, minting and storing the new one) before that `202`.
  `deliver_password_reset` runs after the response and **never retries**: on a `MailSendError`
  it logs at `WARNING` with the token row's id — never the token itself — and returns. A user
  whose email did not arrive requests another, which mints a fresh token and revokes the old one.
- **Hard-deleted, not soft-deleted.** `PasswordResetTokenRepository.delete_dead`, run on every
  worker tick, removes rows expired or used more than a day ago. A dead token is not a record
  anyone needs to keep, unlike a refresh token.

## Notification email is claimed before it is sent, and delivery is at-least-once

Mechanism: `app/mail/outbox.py` and `mail_loop` in `app/worker.py`.

- **The claim is a lease, not a flag.** `NotificationRepository.claim_pending_email` selects up
  to `CLAIM_BATCH` (50) rows with `email_state = 'pending'` whose lease has expired or was never
  set, locks them with `SELECT ... FOR UPDATE SKIP LOCKED`, and stamps `email_claimed_until` 15
  minutes out. The lease is 15 minutes, not the 2 an earlier draft specified, because a batch of
  50 rows against the 10-second SMTP timeout can run past 8 minutes in the worst case, and two
  worker replicas draining on the same 60-second tick would otherwise both send a row still
  within a shorter lease.
- **Delivery is at-least-once, and nothing here claims otherwise.** A process that crashes after
  the relay accepts a message and before the row is marked will send it again once the lease
  expires. `mark_email` only writes a row still `email_state = 'pending'`, so a genuine
  double-claim cannot have its outcome overwritten by the race's loser — but the outbox does not
  itself deduplicate a message that reached two SMTP connections; a rare duplicate is the
  accepted cost of a nudge.
- **Failure classification**, in `_deliver`:
  - A retryable `MailSendError` with `attempts < MAX_EMAIL_ATTEMPTS` (5) leaves the row
    `pending` — the lease expiry is what spaces the next attempt.
  - A non-retryable `MailSendError`, or the fifth retryable attempt, marks the row `failed`.
  - **Anything that is not a `MailSendError`** — a bug in `compose_notification`, an
    unrecognised `event_type` — fails that row immediately and lets the rest of the batch
    proceed, rather than sitting leased behind a deterministic crash that would reproduce on
    every future drain.
  - A row whose event is older than `STALE_AFTER` (24 hours), or whose recipient is
    deactivated, is marked `skipped` without a send attempt — turning mail off for a week and
    back on must not deliver a week of stale "Index finished" notices.
- **The SMTP error is logged at `WARNING` and never stored.** `email_state`/`email_attempts`
  record the outcome; the exception text goes to the log, never to a column, and never to the
  audit trail.

## `mail_loop` is never a step inside `reconcile_loop`

`app/worker.py` runs `mail_loop` as its own `asyncio.Task`, on its own 60-second cadence,
**only when `MAIL_ENABLED` is true** — it is not constructed at all when mail is off, and
`reconcile_loop` neither calls into it nor inspects its state. A slow relay must not delay
stranded-job recovery, and a wedged Kafka must not stop mail from draining; keeping the two
ticks as siblings is what makes each failure profile independent of the other.

## The email decision is a snapshot at fan-out, and email adds no recipient path

Mechanism: `app/services/notification_fanout.py`, `.claude/rules/notifications.md` rules 1 and
4. `NotificationFanout._write` writes `email_state` at the same moment it writes
`in_app_visible` — off the same preference read, for the same resolved recipient set. It writes
`'pending'` when mail is enabled and the recipient's email preference is on, and `NULL`
otherwise (mail off, or the preference off) — there is no `'skipped'` value written at fan-out;
`'skipped'` is a terminal outcome the outbox writes later, at send time, for a stale event or a
deactivated recipient. Nothing at fan-out, and nothing in the outbox, resolves a second
recipient list: email reaches exactly the recipients `resolve_notification_recipients` already
computed for the in-app row.

## Email delivery is not audited

Mechanism: `app/core/audit.py`, `.claude/rules/audit-trail.md` exemption 6, `docs/PRD.md` §2.1's
Phase 2.4 entry — not a rule stated in `app/core/audit.py` itself, which carries no mail-specific
code at all.

- **Sending a reset link or a notification email is a transport of an event already recorded
  elsewhere** — the notification event, or `auth.password_reset.requested` — not a new action.
  No human performs the send: a `BackgroundTasks` task drains a reset email, and the worker's
  `mail_loop` drains notification email.
- **The outcome lives on the row itself**, never in the audit trail: `notifications.email_state`
  / `email_attempts` / `email_sent_at` for notification email, `password_reset_tokens.sent_at`
  for a reset email. An operator recovers by querying those tables, not by reading an audit
  event.

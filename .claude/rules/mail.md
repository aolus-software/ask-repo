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

## Nothing derived from an indexed repository leaves the network

`app/mail/composer.py` composes every message that leaves the instance. The rule is **not**
"check that every message is okay" — it is "accept no parameter that would allow one to leave
the code". That is what the signature rules exist for.

- **A notification email carries an event type and a link, never content.** Subject and body
  leave the instance; both are fixed strings per event. `compose_notification` accepts only
  `event_type`, `user_name` (for "Dear <name>"), `project_name`, `module_name`, and `web_url`.
  It takes no message text, no answer text, no answer title, no snippet, no change set
  proposal body. A parameter added here is not a convenience — it is a decision to export
  that thing out of the network, and `docs/PRD.md` §9 owns that decision, not this file.
- **A password reset email carries a link and nothing else.** The link is the entire message;
  the user's email address is never mentioned. `compose_password_reset` accepts only
  `user_name`, `reset_link`, and `instance_name`. Every other detail is generated on the
  reset form itself, in the browser, never on this side of the email.

`tests/test_mail_compose.py` signatures are the enforcement. Adding a parameter requires
updating that test and makes the change visible to review; silent additions are caught by
the signature check rather than left to remember.

## Subjects are fixed strings per event, bodies are plain text

- **No template variables in the subject.** Every event gets one subject line, and it carries
  no context. The recipient reading an inbox has learned to sort notifications by sender;
  subjects all saying "Update on your project" are undifferentiated noise.
- **Bodies are plain text, not HTML.** No styling, no links embedded in `<a>` tags, no
  rendering logic in the mailer. A reset link is `Click here: <URL>` or the `[URL]` form on
  its own line, never an HTML template. This is an intentional simplification: it keeps
  the compose logic thin and is what makes it safe to have none.

## Resetting a password is never retried

A reset token is **single-use and short-lived** — designed so that a lost or intercepted email
cannot be replayed. That single-use property depends on a hard delete in the token table. A
retry path that redrew an expired or used token would defeat that.

- **Resetting a password raises immediately on a failed send.** No retry, no second attempt.
  If the mail service is down or rejects the address, the user is told at request time and
  must try again — which redraws the token automatically.
- **A `password_reset_tokens` row is hard-deleted** by `PasswordResetRepository.delete_dead()`,
  run on every worker tick, for expired tokens and for tokens used more than one day ago. The
  latter covers the case where the email reached the user, the user clicked it once and reset
  their password, then the second click arrives when they try to refresh — the browser backs up
  and hits reset again. The token is gone and they are refused immediately, which is correct:
  the second request is someone else getting the email off the wire or trying brute-force.

## Notification email is claimed before it is sent

Mechanism: `app/mail/outbox.py` and `mail_loop` in `app/worker.py`.

- **A row in the notifications table is claimed with `SELECT ... FOR UPDATE SKIP LOCKED`**
  before any network call. `email_claimed_until` holds the lease expiry; if the lease expires
  or the worker dies, the row's `email_attempts` and `email_claimed_until` are cleared by the
  reconcile sweep and the row is claimable again.
- **The lease is held for the duration of the send.**  On success, `email_state` moves to
  `sent` and `email_sent_at` is stamped. On failure, `email_state` becomes `failed` (if the
  exception is not `MailSendError`) or returns to `pending` for retry (if it is
  `MailSendError`). `email_attempts` counts delivery attempts, not retries — every claim is
  one attempt.
- **The same at-least-once guarantee that covers Kafka covers mail.** Kafka delivers a job
  at least once. If a worker dies mid-send, the row is re-claimed and sent again — if the
  first send succeeded but the worker crashed before `email_state` was updated, the email
  still reaches once, because idempotent sends are the producer's responsibility to define,
  and email providers define it per-provider. The rule is that the outbox handles
  at-least-once semantics correctly: each send must check whether the previous send succeeded
  before trying again, and Kafka re-delivery must be idempotent. The feature must not lie
  about `email_sent_at`.

## `mail_loop` is never a step inside `reconcile_loop`

`app/worker.py` runs two separate 60-second ticks: `reconcile_loop` and `mail_loop`.

- **They do not compose.** `reconcile_loop` does not call into `mail_loop`, and `mail_loop`
  does not use or inspect reconciliation state. Both are sibling ticks — parallel polling
  loops over different tables.
- **Why.** Reconciliation and mail delivery have different failure profiles. Reconciliation
  finds stranded work and re-publishes it; mail finds claimed rows and retries. If mail were
  a step inside reconciliation, a broken mail service could starve the reconcile path, and a
  broken Kafka could starve the mail path. Keeping them separate means a mail provider down
  does not stop stranded-job recovery, and a wedged job queue does not stop email from draining.

## The email decision is a snapshot at fan-out

Mechanism: `app/services/notification_fanout.py`, `.claude/rules/notifications.md` rule 4.

- **`email_state` and `email_attempts` are written at the same moment as `in_app_visible`.**
  Both are read off the preference snapshot at fan-out time and written to the
  `notifications` row. A user who changes their email preference an hour later affects only
  new events, not rows already written.
- **Email adds no recipient path.** A notification either reaches someone in-app or via email,
  or both, based on preferences snapshotted at the time the event occurred — not based on
  any decision the mailer later makes. The mailer reads what was decided, tries to deliver
  what was agreed, and reports the outcome. It does not re-evaluate who should be told.

## Email delivery is not audited

Mechanism: `app/core/audit.py`, exemption 6.

- **Sending an email to a user is not an audited event.** The row on `notifications` records
  that the event occurred and who was told; the audit trail records *human actions that change
  data*. A mail loop pushing bytes through an SMTP service is infrastructure, not an action.
- **A delivery failure is recorded on the row and nothing else.** `email_state` `failed`,
  `email_attempts` incremented — the mechanism is the same as any other retriable work. No
  audit row, no log line naming the address or the reason. If recovery is needed, it is
  manual: an operator queries the table.

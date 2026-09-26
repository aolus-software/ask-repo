# Notifications Rules

Everything under `app/core/notifications.py`, `app/services/notification_fanout.py`,
`app/services/notification.py`, the nine fan-out call sites in `app/ingestion/pipeline.py`,
`app/checklist/generator.py`, `app/mockdata/generator.py`,
`app/services/checklist_change_set.py`, `app/services/mock_data_change_set.py` and
`app/services/membership.py`, the email half of `app/mail/`, and the routes under `app/api/routes/notifications.py` and
`app/api/routes/notification_preferences.py`. Read `audit-trail.md` alongside this — the two
systems share a shape (a catalogue, an allowlist, a per-event decision about who and what) and
diverge on purpose in exactly the places called out below.

Design: `docs/superpowers/specs/2026-09-20-phase-2.3-notifications-design.md`.
Intent: `docs/PRD.md` §2.1, Phase 2.3.

Every invariant here fails **silently** when broken — no exception, no failing request, just a
notification that never reached the person it was for, or one that reached someone it should
not have. That is what makes these rules rather than preferences.

## 1. Recipients resolve through `resolve_notification_recipients`, and nowhere else

`app/core/access.py` already answers "which projects may this user see", through
`resolve_project_scope`, and `require_permission` answers "what may this user do to this one".
Recipient selection is the same question asked backwards — "who is interested in this
project" — and it must resolve through the same file, not through a recipient list invented at
the fan-out call site.

The reason is not tidiness. A second resolver is a second place that can drift from the first,
and here drift does not mean an empty list — it means a notification naming a private
repository to someone who was never given membership on it. `tests/test_scoping_is_single_point.py`
greps for this: `MembershipRepository.recipients_for` may be called from `app/core/access.py`
and from nowhere else. Add a second call site and the grep fails; that is the point.

## 2. Fan-out runs before the commit; `AuditRecorder` runs after — both orderings are load-bearing

```
… mutate …
await fanout.raise_event(...)      # before: a lost notification is the feature failing
await session.commit()
await recorder.record(...)         # after:  a failed audit must not fail the action
```

These look like a contradiction to anyone who has not read why each one is where it is. They
are not the same durability requirement pointed in the same direction — they are two different
requirements that happen to point opposite ways.

`AuditRecorder` runs after the commit, on its own session, and never raises, because an audit
failure must not fail the user's action — a login must not fail because a log write did.
`NotificationFanout` runs *inside* the same transaction as the state change and `flush`es
rather than commits, because the entire feature is reaching someone who is not watching the
screen right now. If the fan-out failed silently after the commit, "the generation finished and
nobody was told" would be unrepresentable as a bug — there would be no record that it should
have happened. Rolling the state change back with a failed fan-out is the correct trade: the
database connection that cannot take a handful of insert rows was not going to take the status
commit either.

## 3. `details` is in-app only — Phase 2.4's email composes from `event_type` and `target_id`

Every in-app recipient is, by construction, a member who can already read the project name and
the module name on the screen behind the bell — that is what makes `details`' display names
(`projectName`, `moduleName`, …) safe to store. They are **not** safe in an email: email is the
instance's first path *out* of a network whose whole posture is that nothing leaves, and
copying a display name into that path is the small, reasonable-looking step that turns into "is
a project name really repository content" argued after a mail host already exists.

So the boundary is drawn now, in code that cannot see an email yet: Phase 2.4's composer reads
`event_type` and `target_id` off the `notification_events`/`notifications` rows and never
touches `details`. Adding a field to `DETAIL_FIELDS` that Phase 2.4 would need to read is a sign
the boundary is being crossed, not a convenience.

## 4. Preferences snapshot onto `notifications.in_app_visible`; they never gate row creation

The obvious implementation — skip writing a row when the recipient has muted the event — is
wrong, and it is wrong for a reason that only shows up once email exists: the `notifications`
row *is* the per-`(user, event)` record, and Phase 2.4 defines email as a delivery attempt
against that row. A user who muted in-app but wants email is the exact combination the
preferences screen exists to offer, and suppressing the row at write time would leave that user
with nothing for Phase 2.4 to send against — forcing a second, parallel recipient path into
existence for email alone.

So a row is written for **every** resolved recipient, muted or not, and the preference is
copied onto it as `in_app_visible` at fan-out time. The unread count and the list both filter on
that column — there is no read-time join to `notification_preferences` on the polled path — and
changing a preference later does not retroactively reveal or hide what already happened, which
is what a person expects from a notification setting.

**The same snapshot applies to email (Phase 2.4), but only at fan-out.** At the moment
`in_app_visible` is written, `email_state` is written too, off a separate preference lookup made
at the same moment (`_muted_for` for in-app, `muted_email` for email): it is
`'pending'` when mail is on and the recipient's email preference for this event is on, and
`NULL` when email was never in play — mail off instance-wide, or the recipient's preference off.
That is the whole snapshot; `email_attempts` is left at its default of `0`. What `email_state`
becomes afterwards — `sent`, `failed`, or the outbox's own `skipped` — is a delivery outcome the
mail loop writes later (`app/mail/outbox.py`), and says nothing about the preference: it is the
same kind of after-the-fact state `in_app_visible` never carries, because the bell has no
equivalent post-fan-out write. A user who changes their preference later affects only new
events; existing rows remember what was decided when they were written.

## 5. An administrator with no membership receives nothing

`require_permission` lets an administrator pass every check, and the temptation is to give
`resolve_notification_recipients` the same bypass for symmetry. **That symmetry is the bug, not
a missing feature.** Permission to see a project is not interest in hearing about it, and an
admin bypass here would turn every project event on the instance into a firehose no
administrator will read — on an instance whose repository names are inventory of private
codebases, arguably worse than a firehose nobody reads.

Administrators are notified about the projects they actually hold a membership on, exactly like
everyone else. If an admin needs to know about a project they do not belong to, that is a
membership to grant, not a resolver to special-case.

## 6. Actor exclusion is per-event: exclude for actions, include for outcomes

`ACTOR_EXCLUDED` in `app/core/notifications.py` is a set, not a global flag, because the two
halves of "was this the actor's own doing" answer differently for a synchronous click and an
asynchronous result.

Applying someone else's change set is something the actor just did — telling them about their
own click is pure noise, so `checklist_change_set.applied`/`discarded` and their mock-data
twins exclude the actor. Finishing a reindex is something the actor **cannot** otherwise know
happened — they pressed the button twenty minutes ago and walked away, so `project.ready`,
`project.failed`, `project.reindex.finished` and `project.reindex.failed` all include the actor.
Collapsing this into one flag either spams the person who just clicked Apply or leaves the
person who started a reindex with no way to learn it finished — a helper that is right half the
time and silently wrong the other half.

## 7. `membership.granted` goes through `raise_direct`, never through the permission map

Every other event's recipients are members holding a permission, resolved at the moment the
event is raised. `membership.granted` cannot work that way: its recipient — the person just
added — by construction was not a member when the event fired. Resolving through the permission
map either misses them (queried before the grant is flushed) or sweeps in every other member
too (queried after), and neither is "notify the new member".

`NotificationFanout` therefore exposes two methods rather than one general one with a branch:
`raise_event(...)` for the permission-resolved events, and `raise_direct(...)` which takes an
explicit recipient and is used by `MembershipService.grant` alone. Adding a branch inside
`raise_event` for this case — "if it's `membership.granted`, use the grantee instead" — is how
a single recipient resolver quietly becomes two, which is exactly what rule 1 exists to prevent.

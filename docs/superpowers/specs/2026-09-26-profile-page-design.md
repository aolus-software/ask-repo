# Profile page — account, sessions, activity, notifications and password: Design

**Date:** 2026-09-26
**Intent:** GitHub issue #50; `docs/PRD.md` §4.0 (amended by this change)
**Depends on:** Phase 2.1 (memberships and roles), Phase 2.2 (the audit trail), Phase 2.3
(notification preferences), Phase 2.4 (self-service password reset)
**Milestone placement:** an unnumbered amendment to M0, in the shape of §6's "Phase 1.1 —
module path picker" paragraph — not a milestone of its own

---

## 0. What this document covers

A signed-in user has no page about themselves. The account menu
(`frontend/components/layout/account-menu.tsx`) holds exactly two items, Log out and Log
out everywhere; its own comment (`account-menu.tsx:24-30`) says the profile display and the
change-password entry were removed pending "a proper account settings page".
`components/users/change-password-dialog.tsx` still exists and nothing imports it, so
**voluntary password change is unreachable from the UI today** — only the forced
first-login flow at `/change-password` can change a password.

Issue #50 describes the menu as still carrying name, email and a Change password dialog.
That is out of date; this design starts from the menu as it is.

This change ships one page, `/profile`, with five sections — account, sessions, activity,
notifications, password — and the four `/me` routes behind it.

What is deliberately **not** in scope: a user editing their own name or email (it changes
the admin-provisioned account model, §4.0); any `/profile/{id}` or admin view of another
user's sessions or activity; filters on the activity list; polling or push on any of the new
queries (issue #48 owns push).

### 0.1 The decisions, made

1. **Last activity is all three layers.** "Last signed in" from `users.last_login_at`; the
   user's own sessions, from `refresh_tokens`; and the user's own audit events. The second
   and third are PRD amendments (§0.2), not defaults.
2. **Sessions carry device information and can be revoked one at a time.** `user_agent` and
   `ip_address` are captured at login and copied forward on rotation. Revoking a session is
   a new, audited write. Without device information a revoke button is a guess.
3. **The activity feed is the rows where the caller is the actor, every event type,** with
   project-scoped rows narrowed through `resolve_project_scope`. That includes
   `auth.login.failed` rows recorded against the caller's account — someone else's attempt,
   with their IP (`app/services/auth.py:179`). Rows where the caller is only the *target* (an
   admin acting on them) are not included.
4. **Notification preferences move to `/profile`.** `/settings/notifications` becomes a
   redirect to `/profile#notifications`, and the Settings group is admin-only again.
5. **"Email me a reset link" is offered on the profile when mail is on.** It reuses the
   existing public `POST /auth/password-reset/request` with the caller's own email; no new
   route.
6. **The routes live under a new `/me` prefix,** not under `/auth` and not as flags on
   existing routes (§1.1).
7. **The account menu gains a header and a Profile item;** it does not shrink.

### 0.2 Amendments to `docs/PRD.md` and the rules, made in the implementation change

These are the parts `.claude/rules/contradiction-halt.md` requires be written down rather
than worked around. Each lands in the same change as the code.

- **§4.0 Auth & Accounts** gains a *Profile* subsection: the page, the four `/me` routes,
  no `/profile/{id}`, admins view others only through `/settings/users`, and self-edit of
  name or email still out of scope.
- **§4.0's out-of-scope list (`docs/PRD.md:501`)** loses "session-activity history". In its
  place: a user sees and may revoke **their own** sessions, with device and IP captured at
  login; there is still no administrator view of anyone else's sessions.
- **§2.1 Phase 2.2** gains a second, narrow reader of the audit trail: a user reads the rows
  where they are the actor, project-scoped rows narrowed through `resolve_project_scope`.
  Admin-only remains true of every other read. Written as a deliberate amendment, in the
  same register as the conversation-metadata amendment to §4.2.
- **§2.1 Phase 2.3** records that preferences moved from Settings to the profile. The
  polled-count decision is untouched.
- **§6** gains an unnumbered paragraph, "M0 amendment — profile page (not a milestone of its
  own)", pointing at §4.0.
- **§9** records `refresh_tokens.user_agent`/`ip_address` as newly stored personal data, and
  that a user can see the IP of failed sign-in attempts against their own account.
- **`.claude/rules/audit-trail.md`** — "Who reads it" gains the self-read; the catalogue
  gains `auth.session.revoked` under the existing *Authenticate* row.
- **`.claude/rules/navigation.md`** — `/profile` is breadcrumb-only; Settings is admin-only
  again, and the text calling Notifications its first non-admin child is rewritten.

### 0.3 The constraints that are not negotiable

- **Membership is read through `app/core/access.py`, and nowhere else.**
  `tests/test_scoping_is_single_point.py` fails if any file outside its allowlist names
  `ProjectMembership`. `MeService` never does.
- **Every `/me` route is scoped to the caller by construction.** No route takes a user id.
  A session id belonging to someone else is `404`, never `403`.
- **`/me` is behind the forced-password-change gate.** It is not added to
  `GATE_EXEMPT_PREFIXES`.

---

## 1. Backend

### 1.1 Why `/me`, and not `/auth` or flags on existing routes

- **`/auth` is gate-exempt.** Sessions and activity placed there would be readable before a
  forced password change unless someone remembered to carve them out. A new prefix is gated
  by default, which is the correct failure direction.
- **`GET /auth/me` is the hottest read in the app** — it backs `useSession` and the settings
  redirect. It stays exactly as it is; memberships are not joined onto it.
- **`GET /audit-events?mine=true` would make an admin-only route's authorization depend on a
  query flag.** `AdminUser` is a dependency, not a branch, and should stay one.
  `GET /projects?member=true` would force an administrator to page through every project on
  the instance to find their own memberships.

### 1.2 Session identity: the `sid` claim

The BFF proxy strips `cookie` from every forwarded request
(`frontend/app/api/[...path]/route.ts:37`), so an ordinary API call never carries the
refresh cookie and the backend cannot tell which session it came from. The access token
fixes that:

- `create_access_token` (`app/core/security.py:99`) gains a keyword `session_id` and writes
  it as a `sid` claim — the refresh token's `family_id`.
- `AuthService._issue` already holds the family id at login and at every rotation
  (`app/services/auth.py:94`, `:290`, `:301`) and passes it through.
- `decode_access_token` returns the subject and the `sid`; `AuthenticatedUser`
  (`app/core/middleware.py:67`) gains `session_id: uuid.UUID | None`.
- `None` only for a token minted before this change. Those age out within 15 minutes and
  simply show no "This device" marker; nothing refuses them.

### 1.3 Migration: device information on `refresh_tokens`

Two nullable columns, existing rows `NULL`:

| Column | Type | Source |
| --- | --- | --- |
| `user_agent` | `String(255)` | the `User-Agent` header at login, truncated to 255 |
| `ip_address` | same type as `audit_events.ip_address` | `client_ip(request, trusted_proxy_hops=...)` (`app/core/rate_limit.py:40`) |

- Captured at **login**. A rotation copies both from the parent, so a session keeps the
  device it started on.
- The login route hands both to `AuthService.login` the same way it already hands the
  client IP to the recorder. The BFF already relays `X-Forwarded-For`
  (`frontend/lib/auth/forwarded.ts`), so `TRUSTED_PROXY_HOPS` resolves the real caller.

### 1.4 `memberships_for` in `app/core/access.py`

```python
def memberships_for(user: AuthenticatedUser) -> list[Grant]:
    """The projects this caller actually holds a membership on, with the role name."""
```

Reads `user.grants` — the snapshot the middleware already loaded — and returns it. An
administrator gets their **real** memberships, not every project: this function answers
"where am I a member", which is a different question from `resolve_project_scope`'s "what may
I read". No I/O, synchronous, beside `role_for`.

### 1.5 Routes

A new router, `app/api/routes/me.py`, one service call per route (`router.md`), backed by a
new `MeService` in `app/services/me.py`. Every route takes the caller from `CurrentUser` and
from nothing else.

| Route | Returns / does | Status codes |
| --- | --- | --- |
| `GET /me/memberships` | `MembershipSummary[]`: `{projectId, projectName, role}`. Grants from `memberships_for`; names from `ProjectRepository`, soft-deleted projects dropped; ordered by project name | `200`, `401`, `403 PASSWORD_CHANGE_REQUIRED` |
| `GET /me/sessions` | `SessionResponse[]`, one per live family: `{id, userAgent, ipAddress, startedAt, lastActiveAt, expiresAt, current}`. `id` is the `family_id`; `startedAt` the family's first `issued_at`; `lastActiveAt` its newest `issued_at` (tokens rotate on use, so the newest issue is the last refresh); `current` is `id == user.session_id`. Newest `lastActiveAt` first | `200`, `401`, `403` |
| `DELETE /me/sessions/{id}` | Revokes every unrevoked token in the family with `reason="user_revoked"`, after confirming the family belongs to the caller. Records `auth.session.revoked` after the commit | `204`, `401`, `403`, `404 SESSION_NOT_FOUND` |
| `GET /me/activity` | `Page[AuditEventResponse]` — the rows where the caller is the actor, project-scoped rows narrowed (§1.6). Plain `ListQuery` pagination, no filters | `200`, `401`, `403` |

**A "live family"** has at least one token with `revoked_at IS NULL` and
`expires_at > now()`.

**`404 SESSION_NOT_FOUND`** covers both an unknown id and a family owned by another user —
the same answer, so the route cannot confirm that someone else's session id exists. It is a
new `ErrorCode` member.

**Revoking the current session is allowed** and behaves like Log out: the refresh token is
dead, and the access token lives out its remaining minutes. The frontend handles the
redirect (§2.3).

**The 15-minute window is stated, not hidden.** Access tokens are stateless, so a revoked
session keeps working until its access token expires — the same window Log out everywhere
has today. The frontend says so on the confirm dialog.

### 1.6 The activity query

`AuditEventRepository._filtered` (`app/repositories/audit_event.py:42`) gains an optional
`project_scope: ProjectScope | None`:

- `None` — no narrowing. `/audit-events` passes `None` and is unchanged.
- unrestricted (an administrator) — no narrowing.
- restricted — `WHERE project_id IS NULL OR project_id IN scope.ids`.

`MeService.activity` calls `page(actor_user_id=user.id,
project_scope=resolve_project_scope(user))`. This is a narrowing applied on top of the
resolver's answer, never a replacement for it, so it passes the single-point rule the same
way `?ownerless` does.

Consequences, all deliberate:

- A user removed from a project stops seeing their own past rows on it — its name is
  `target_label`, and project existence is private.
- Rows with no project (`auth.*`, account events) always show.
- `auth.login.failed` rows against the caller's account appear, with the attempt's IP.
- Conversation rows appear with `target_label` `NULL`, as they are stored.

### 1.7 Repository and model changes

- `RevokedReason` (`app/models/refresh_token.py:21`) gains `"user_revoked"`. The column is
  `String(32)` with no check constraint, so no migration is needed for the value.
- `RefreshTokenRepository` gains `live_families_for(user_id)` and a way to fetch one
  family's owner. `revoke_family` exists already (`refresh_token.py:71`).
- `RefreshTokenRepository.create` gains `user_agent` and `ip_address`.

### 1.8 Audit: one new event

`auth.session.revoked` joins the catalogue in `app/core/audit.py`:

- No `changed` block — the event's meaning is its name.
- Context keys: `familyId`, `current` (bool), `revokedCount` — the same shape as the
  existing logout event (`auth.py:243`).
- Recorded after the commit, on the caller as actor.
- `tests/test_audit_coverage.py` names it; `docs/data.md`'s event list and `CHANGELOG.md`
  mention it.

The two existing writes the page exposes — password change and preference changes — are
unchanged. Preference changes remain exemption 5.

### 1.9 Response models

`MembershipSummary` and `SessionResponse` are new and inherit `ApiModel`;
`tests/test_api_model.py` covers them. `/me/activity` reuses `AuditEventResponse`. Nothing
here streams, so `SSE_EVENT_MODELS` is untouched.

### 1.10 Flagged for decision: password change revokes the current session too

**SUSPECT, traced but not reproduced.** `AuthService.change_password`
(`app/services/auth.py:305`) spares the caller's own session by hashing the refresh token
"because it arrived in the cookie", and the route reads it with `_read_refresh_cookie`
(`app/api/routes/auth.py:213`). But the frontend calls `/auth/change-password` through the
catch-all proxy (`frontend/hooks/use-change-password.ts`), which strips `cookie`. So
`raw_token` is `None`, `except_token_id` is `None`, and `revoke_all_for_user` revokes
**every** session, the caller's included. The caller's next refresh fails and they are sent
to `/login` within 15 minutes of changing their password — on the forced first-login flow
as well as the new profile form.

Settled by: changing a password in the running app and checking whether the caller's own
`refresh_tokens` row has `revoked_reason = 'password_change'`.

If confirmed, the `sid` claim (§1.2) is the natural fix: `change_password` spares
`user.session_id`'s family instead of looking up a cookie the backend never receives. That
is a behavioural fix to an existing route and **is not part of this design until the owner
decides** — it is listed here because the profile's password section is the second place
that would inherit the defect.

---

## 2. Frontend

### 2.1 Route and navigation

- `app/(app)/profile/page.tsx` renders `ProfileScreen`. One page, no sub-routes, inside the
  app shell and behind `proxy.ts`.
- `/profile` joins `breadcrumbOnlyItems` in `lib/nav.ts`, beside `/notifications`. It is
  reached from the account menu, not the sidebar.
- `settingsNav` drops Notifications. For a non-admin the Settings group then has no
  reachable child, and `visibleNavTree` already hides such a group.
- `/settings/notifications/page.tsx` becomes `redirect("/profile#notifications")`.
- `/settings/page.tsx` needs no change: a non-admin falls through to `redirect("/")` via
  `child?.href ?? "/"`.

### 2.2 The account menu

`account-menu.tsx` gains a header (name and email), then a **Profile** item, then Log out
and Log out everywhere as today. The comment promising a future settings page is replaced.

### 2.3 The page

Sections stack in one column; on wide screens a sticky index of section anchors sits beside
them. Each section is its own component under `components/profile/`.

| Section | Content | Data |
| --- | --- | --- |
| **Account** | Name, email, an Administrator badge (`user-role-badge.tsx`), and a membership table — project name linking to `/projects/{id}`, and role. Empty state: "You aren't a member of any project yet." An administrator also sees one line: "As an administrator you can see every project." | `useSession`, `GET /me/memberships` |
| **Sessions** | "Last signed in" from `lastLoginAt`; then one row per session: a device label parsed from the user agent (raw string on hover), IP, started, last active, and a **This device** badge on the current row. Each row has **Log out**. Log out everywhere sits below the table | `GET` / `DELETE /me/sessions` |
| **Activity** | Paged list of the caller's own audit events: time, a readable event label, project if any, outcome, IP | `GET /me/activity` |
| **Notifications** (`#notifications`) | `PreferencesScreen`, moved as-is, its page header dropped | existing routes |
| **Password** | `ChangePasswordFields` in a page-section form shell (`forms.md` §2 — a swap, not a rewrite). When `/api/auth/password-reset/availability` reports mail on, an **Email me a reset link** button posts the caller's own email to the existing public-forward route and shows the forgot-password page's neutral confirmation | existing routes |

**Revoking a session.**

- The current row: the same hard reload to `/login` the menu uses, so the React Query cache
  is dropped with the session.
- Any other row: a confirm dialog — "It may stay signed in for up to 15 minutes." — then the
  sessions query is invalidated.

**Event labels.** The admin audit screen already maps event types to readable labels. That
mapping moves to a shared `lib/audit-labels.ts` rather than being copied.

**Device labels.** A small pure parser, `lib/user-agent.ts`, maps a user-agent string to
"Browser on OS" for common agents and falls back to the raw string. No new dependency.

### 2.4 Hooks

`hooks/use-profile.ts`: `useMemberships`, `useSessions`, `useRevokeSession`, `useActivity`.
None poll. A revoke invalidates the sessions query; a successful password change invalidates
sessions too, since the backend revokes every other session.

### 2.5 Removed

`components/users/change-password-dialog.tsx` — imported by nothing, superseded by the
Password section.

### 2.6 Design system

Tokens and shadcn/Base UI components only, composed with `render=`. No `dark:` colour
utility and no palette utility (`design-system.md`). A component the page needs that is not
yet installed is installed by the CLI.

---

## 3. Error codes

| Code | Status | When |
| --- | --- | --- |
| `SESSION_NOT_FOUND` | `404` | `DELETE /me/sessions/{id}` for an unknown family, or one owned by another user |

Added, never renamed (`response-api.md`).

---

## 4. Testing

### 4.1 Backend

**`tests/test_me_api.py`** (new):

- Memberships: exactly the caller's grants with role names; soft-deleted projects dropped;
  empty for a user with no grants; an administrator sees only real memberships.
- Sessions: only the caller's live families; `current` from the `sid` claim; revoked and
  expired families excluded.
- Revoke own family: every token in it revoked; a later refresh with that cookie is `401`.
- Revoke **another user's** family: `404 SESSION_NOT_FOUND`, their tokens untouched.
- Revoke unknown id: `404`.
- Activity: only rows where the caller is actor, including their `auth.login.failed` rows.
- Activity after membership revoke: that project's rows gone; project-less rows kept; an
  administrator's feed not narrowed.
- All four routes: `403 PASSWORD_CHANGE_REQUIRED` while `must_change_password` is set;
  `401` with no token.

**Extended:**

- `test_auth_api.py` — login stores the user agent and the resolved IP, honouring
  `TRUSTED_PROXY_HOPS`; rotation copies both and keeps `family_id`; the access token's
  `sid` equals the family id after login and after refresh; a token without `sid` still
  authenticates with `session_id = None`.
- `test_audit_coverage.py` — `auth.session.revoked` named and emitted.
- `test_audit_events_api.py` — `/audit-events` unchanged: admin-only, no narrowing.
- `test_api_model.py` — the new models inherit `ApiModel`.
- Migration — upgrade and downgrade clean, following the existing pattern.

**Unchanged and expected to pass:** `test_scoping_is_single_point.py`, which is what proves
`memberships_for` lives in `access.py` and `MeService` never names `ProjectMembership`.

### 4.2 Frontend (Vitest)

- `lib/nav.test.ts` — a non-admin's tree has no Settings group; an admin's has three
  children; `/profile` resolves a breadcrumb.
- `lib/user-agent.test.ts` — common agents, empty string, unknown agent falls back to raw.
- `lib/audit-labels.test.ts` — every catalogued event type has a label; unknown types fall
  back to the raw name.
- Components — revoking the current session hard-reloads to `/login`, another session
  refetches in place; the reset-link button appears only when availability says mail is on;
  the password section routes field errors as the form-shell tests already require.

### 4.3 Checks

`make check` and `bun run build` pass. No `-m model` run: nothing under `app/rag/` changes.

### 4.4 Manual

With `make dev`: sign in from two browsers and see **This device** on each one's own row;
revoke the other browser and see its next navigation after token expiry land on `/login`;
`/settings/notifications` redirects; a non-admin sees no Settings entry.

---

## 5. Documentation changed in the implementation change

| Doc | Change |
| --- | --- |
| `docs/PRD.md` | §0.2's amendments |
| `.claude/rules/audit-trail.md` | the self-read in "Who reads it"; `auth.session.revoked` |
| `.claude/rules/navigation.md` | `/profile` breadcrumb-only; Settings admin-only again |
| `docs/data.md` | the two columns and migration, `user_revoked`, the new event |
| `docs/notifications.md` | preferences now live on `/profile` |
| `backend/README.md` | the four `/me` routes |
| `frontend/README.md` | the screen and the layout tree |
| `CLAUDE.md` | the frontend route list gains `/profile`; `/settings/notifications` is a redirect |
| `CHANGELOG.md` | under `[Unreleased]`: the page, the routes, `SESSION_NOT_FOUND`, the event, Settings hidden from non-admins |

`docs/configuration.md` is untouched: no setting is added. The PR closes #50.

---

## 6. Out of scope, and where it would go

- **Editing one's own name or email** — a change to §4.0's admin-provisioned model; its own
  PRD decision.
- **An administrator's view of another user's sessions** — a new read on personal data;
  would go through `/settings/users` and a PRD decision.
- **Rows where the caller is the target** — would show users the admins who acted on them;
  a policy decision.
- **Activity filters** — `ListQuery` subclass (`rag.md`, "A query model cannot share a
  route with a scalar query parameter") when someone asks.
- **Pushing session or activity changes live** — issue #48.

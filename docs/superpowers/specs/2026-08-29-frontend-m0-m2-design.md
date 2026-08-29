# Frontend M0–M2: Design

Status: approved, not yet implemented.
Date: 2026-08-29.
Covers: the entire browser-facing surface for milestones M0 (auth & accounts), M1 (project
ingestion) and M2 (Dev Knowledge), against a backend where all three are already shipped.

Ground truth, in precedence order: `docs/PRD.md`, then `.claude/rules/` (`navigation.md`,
`forms.md`, `design-system.md`, `rag.md`, `response-api.md`), then `docs/design.md`. Where this
document departs from any of them, §2 says so explicitly and §13 amends the document in the same
change.

---

## 1. What this milestone delivers

`frontend/` today is scaffolding: a landing page, the design tokens in `app/globals.css`, the two
fonts wired in `app/layout.tsx`, and nothing else. No API client, no auth, no `components/ui/`,
no `lib/`. Every backend route listed in `backend/README.md` is reachable only by `curl`.

After this milestone an operator can, in a browser:

- log in, be forced through the first-login password change, and log out of one device or all of
  them;
- see every project on the instance, add one from a repository URL, watch it clone and index,
  read its stats and its failure reason, re-index it, delete it;
- open a private conversation against a `ready` project, ask a question, watch the answer stream
  in with its sources, and see the grounding warnings when the answer may not be trustworthy;
- provision, edit, reset, and deactivate colleagues' accounts, if they are an admin.

Three things this does **not** deliver: the QA List (`/qa`) is M4 and is not in the navigation
tree; nothing here anticipates the LangGraph rework in M3 beyond tolerating unknown stream
events; and no per-project access UI exists, because phase 1 has no per-project access
(`docs/PRD.md` §4.1).

---

## 2. Decisions that go beyond the PRD

Each of these was raised, argued, and decided during design. They are recorded here because a
reader who finds them in the code and not in a document will reasonably assume they were
accidents.

### 2.1 The frontend is a BFF, not a thin client

`docs/PRD.md` §5 describes the frontend as "Minimal Next.js — not the focus; keep thin". This
design puts a **backend-for-frontend** layer in Next: route handlers that proxy the API, Next's
own session cookies, and a middleware gate. That is more than "thin", and the deviation is
deliberate and approved.

The reason is that the alternative does not exist. A Next middleware gate needs *something* it
can read to decide whether a visitor is authenticated, and today there is nothing:

- The access token is a JWT returned **in a JSON response body** (`AccessTokenResponse` in
  `backend/app/schemas/auth.py`). The server never sees it.
- The refresh token is an httpOnly cookie the backend sets **on its own origin, scoped to
  `/auth`** (`docs/PRD.md` §4.0). Middleware runs on the frontend origin at paths like
  `/projects`, where a `/auth`-scoped cookie is not sent.

So server-side gating implies Next holding a session, and Next holding a session implies the
proxy — because once the browser has no token, the browser cannot call the API directly.

What the cost buys: no authentication flash, no protected markup delivered to a logged-out
visitor, and an access token that no script on the page can read. What it costs: a second
authentication mechanism the PRD does not describe, a proxy hop on the one latency-sensitive
path in the product (the answer stream), and roughly a third more frontend surface. §13 amends
the PRD row rather than leaving it contradicted.

### 2.2 Next's mirror cookies are scoped to `Path=/`

`docs/PRD.md` §4.0 scopes the refresh cookie to `/auth`, and that remains true of the cookie the
**backend** sets on the **backend's** origin. Next mirrors the session into its own cookies on
the frontend origin, and those are `Path=/`, because a cookie scoped to `/api/auth` is not sent
on a navigation to `/projects` and the middleware gate would read nothing.

`httpOnly`, `SameSite=Lax`, and `Secure` (outside development) are all preserved, and neither
cookie is ever readable by script. The change is the path, and the consequence is that both
cookies accompany every same-origin request to the frontend — including requests for static
assets. That is accepted; the mitigation that matters (unreadable by JavaScript) is intact.

### 2.3 Refresh happens in two places, and that is structural

A Server Component **cannot set a cookie** in Next — only middleware, route handlers, and Server
Actions can. A Server Component that noticed a stale access token could refresh it and use the
result for its own fetch, but could not persist it; the next Server Component would refresh
again. Every SSR request would rotate the refresh token, and rotation is exactly what
`docs/PRD.md` §4.0 treats as a replay signal when it happens twice.

So:

- **Navigations** refresh in `middleware.ts`, which sets cookies on the response, so by the time
  any Server Component renders the token in the cookie jar is fresh.
- **Browser fetches and the SSE stream** refresh inside the proxy: a `401` from the backend
  triggers one refresh and one retry.

Both call the same `refreshSession()` (§4.2). There is no third refresh site, and a Server
Component never refreshes.

### 2.4 Wire types are hand-written, not generated

`lib/api/types.ts` mirrors the backend schemas by hand. The whole surface is roughly ten shapes
(`UserResponse`, `ProjectResponse`, `ConversationResponse`, `ConversationDetailResponse`,
`MessageResponse`, `CitationPayload`, `PaginatedResponse<T>`, the five SSE payloads, the error
envelope), and they change when a milestone changes, not weekly.

Generating them from `/openapi.json` would catch drift automatically, but it needs either a
running backend at build time — a build that fails when a datastore is down is worse than a type
that is briefly stale — or a committed `openapi.json`, which is the same staleness problem with
an extra file. Revisit at M4 if the surface grows.

The mitigation for drift is that every type is in one module, and the backend's own
`tests/test_api_model.py` guarantees the casing those types assume.

### 2.5 `form` leaves the component inventory

`docs/design.md`'s M0 inventory row lists `form`. shadcn's `form` component is a wrapper around
**react-hook-form**, which `.claude/rules/forms.md` §4 bans by name, because validation belongs
to the backend's `422` field map and a client-side copy of the password policy cannot be kept
honest.

`field` is in the same row and is what `forms.md` §5 actually composes with. `form` is
vestigial, and installing it would pull in the dependency the rule exists to exclude. §13 removes
it from the inventory.

### 2.6 The dashboard shows no per-status breakdown

`GET /projects` accepts only `page`, `limit`, `search`, `sort`, `sortDirection` (`ListQuery` in
`backend/app/schemas/pagination.py`; the route takes it unmodified at
`backend/app/api/routes/projects.py:73`). There is no status filter and no aggregate route.

A tile reading "3 indexing · 12 ready" could therefore only be computed from one page of
results, and would be quietly wrong the moment an instance holds more than `limit` projects —
a wrong number rendered confidently, which is worse than no number. `PaginatedResponse.total_count`
is authoritative, so the dashboard shows totals and recent lists, and no breakdown.

### 2.7 Sort values are snake_case — reported, not fixed

`ProjectRepository.SORTABLE_FIELDS` (`backend/app/repositories/project.py:34`) is
`{"name", "status", "created_at", "updated_at"}`, and the incoming `sort` string is compared
against it directly. Same in `user.py:20` and `conversation.py:24`.

So a client must send `?sort=updated_at`. Every other field name on the wire is camelCase
(`docs/PRD.md` §5.1), which makes `?sort=updatedAt` the obvious thing to send and a
`422 INVALID_SORT_FIELD` the reward.

**This spec does not change it.** Altering a shipped backend contract as a side effect of a
frontend milestone is out of scope, and per `.claude/rules/contradiction-halt.md` the finding is
reported rather than acted on. `lib/api/endpoints.ts` therefore defines the sort values as
snake_case constants with a comment pointing here, so no screen invents its own.

---

## 3. Topology

Two runtimes inside one Next application, and the boundary between them is the point of the
design: **the BFF holds tokens; the browser never does.**

```
frontend/
├── middleware.ts                  # the gate + the navigation refresh point
├── vitest.config.ts
├── app/
│   ├── layout.tsx                 # fonts, ThemeProvider, QueryProvider, Toaster
│   ├── globals.css                # unchanged — the only file with a raw hex colour
│   ├── (auth)/
│   │   ├── layout.tsx             # centred card, no shell
│   │   ├── login/page.tsx
│   │   └── change-password/page.tsx
│   ├── (app)/
│   │   ├── layout.tsx             # SC: /auth/me → shell; forced-change redirect
│   │   ├── page.tsx               # dashboard
│   │   ├── projects/
│   │   │   ├── page.tsx           # list
│   │   │   └── [id]/page.tsx      # detail
│   │   ├── ask/
│   │   │   ├── layout.tsx         # two-pane: history rail + slot
│   │   │   ├── page.tsx           # composer + project picker
│   │   │   └── [conversationId]/page.tsx
│   │   └── settings/
│   │       ├── page.tsx           # redirect → /settings/users
│   │       └── users/page.tsx
│   └── api/
│       ├── [...path]/route.ts     # the proxy
│       └── auth/
│           ├── login/route.ts
│           ├── refresh/route.ts
│           └── logout/route.ts    # also serves logout-all
├── components/
│   ├── ui/                        # shadcn CLI-managed. Never hand-edited
│   ├── layout/                    # app-shell, navbar, app-sidebar, breadcrumbs,
│   │                              #   account-menu, theme-toggle
│   ├── form/                      # form-dialog, form-page, confirm-dialog
│   ├── feedback/                  # forbidden, not-found, empty-state, status-badge,
│   │                              #   table-skeleton, error-alert
│   ├── projects/                  # project-table, create-project-dialog, project-actions,
│   │                              #   project-stats, project-status
│   ├── ask/                       # conversation-rail, message-list, answer, sources,
│   │                              #   composer, project-picker, grounding-notice
│   └── users/                     # user-table, create-user-dialog, edit-user-dialog,
│                                  #   reset-password-dialog
├── lib/
│   ├── api/
│   │   ├── client.ts              # apiFetch — browser → /api/*
│   │   ├── server.ts              # serverFetch — Server Component → backend
│   │   ├── endpoints.ts           # every path and sort value, in one place
│   │   ├── errors.ts              # ApiError + fieldError()
│   │   └── types.ts               # the wire types (§2.4)
│   ├── auth/
│   │   ├── cookies.ts             # names, options, read/write/clear
│   │   └── session.ts             # refreshSession() + the single-flight guard
│   ├── query/
│   │   ├── keys.ts
│   │   └── provider.ts
│   ├── ask/
│   │   ├── pending.ts             # the first question, across one navigation
│   │   └── sse.ts                 # the event parser
│   ├── nav.ts · nav-child.ts · settings-nav.ts
│   ├── status.ts                  # ProjectStatus → semantic token, once
│   └── utils.ts                   # cn(), from shadcn init
└── hooks/
    ├── use-projects.ts · use-project.ts · use-project-mutations.ts
    ├── use-conversations.ts · use-conversation.ts
    ├── use-ask-stream.ts
    ├── use-users.ts · use-user-mutations.ts
    └── use-session.ts             # the user, from the shell's context
```

---

## 4. The BFF

### 4.1 Cookies

Two, both set by Next, both `httpOnly`, both `Path=/` (§2.2), both `SameSite=Lax`, both `Secure`
when `NODE_ENV === "production"`.

| Name | Holds | `Max-Age` |
| --- | --- | --- |
| `askrepo_session` | the backend's refresh cookie as a verbatim `name=value` pair | 30 days |
| `askrepo_access` | the JWT access token | `expiresIn − 30` seconds |

The access cookie's own lifetime **is** the expiry check. When the browser drops it, the token
is stale; when it is present, the token is assumed live and the backend is the authority if it
is not.

**The frontend never parses the JWT.** No `jose`, no `jwt-decode`, no reading of `exp` or any
claim. A frontend that verified a signature would be performing a security check it cannot
enforce, and one that read claims would grow a second source of truth about the user beside
`GET /auth/me`. The 30-second skew subtraction is what makes the cookie lifetime a safe proxy
for the token lifetime.

`lib/auth/cookies.ts` owns the names and the option object. Nothing else constructs cookie
options; a second copy is how `Secure` ends up set in one place and not the other.

### 4.2 The three auth handlers

These are the only route handlers that write cookies.

**`POST /api/auth/login`** takes `{email, password}`, calls `POST {API_URL}/auth/login`, and on
success receives `{accessToken, tokenType, expiresIn, user}` plus the backend's own refresh
`Set-Cookie`. It stores that cookie's **`name=value` pair verbatim** in `askrepo_session`, sets
`askrepo_access`, and returns **`{user}` and nothing else**. The access token never crosses to
the browser — that is the entire point of the layer.

**The pair is stored verbatim because the backend's cookie name is configurable.**
`Settings.refresh_cookie_name` (`backend/app/config.py:43`) defaults to `askrepo_refresh` but is
an operator override. A frontend that parsed the token out by a hard-coded name would break the
moment `REFRESH_COOKIE_NAME` was set — and break silently, as a login that appears to succeed and
a session that cannot refresh. Capturing `name=value` and replaying it as a `Cookie` header on
refresh means the BFF never needs to know the name at all.

Failures pass through with their status and body intact, because the login form needs to tell
`401 INVALID_CREDENTIALS` from `429 RATE_LIMITED`.

**`POST /api/auth/refresh`** exists for completeness and for tests; in normal operation refresh
is triggered by middleware or the proxy rather than by the browser.

**`POST /api/auth/logout`** calls `POST {API_URL}/auth/logout` (or `/auth/logout-all`, selected
by a body flag) with the mirrored refresh token, then clears both cookies **regardless of the
backend's answer**. A logout that fails server-side but leaves the browser holding a session is
the worst of the available outcomes; clearing locally always is the safe direction.

**`refreshSession()` in `lib/auth/session.ts`** is the shared implementation: read
`askrepo_session`, `POST {API_URL}/auth/refresh` with it as a `Cookie` header, and on success
return the new access token, its lifetime, and the rotated refresh token for the caller to
persist. On failure return `null`, and the caller clears both cookies.

**The refresh stampede.** Two browser requests can `401` at the same instant, and each would
present the same refresh token. The backend treats a second presentation of a consumed token as
replay and revokes the whole family — logging the operator out of everything. Two things prevent
that:

1. A module-level single-flight promise in `session.ts`. Concurrent callers **in the same Node
   process** await one refresh and share its result.
2. The backend's own 10-second grace window (`docs/PRD.md` §4.0), which mints a sibling instead
   of revoking.

Be precise about the limit: the guard is per-process, so with more than one frontend replica two
simultaneous refreshes can still reach the backend, and it is the grace window — not the guard —
that saves the session. Do not describe the guard as complete.

### 4.3 The proxy

`app/api/[...path]/route.ts` exports every method (`GET`, `POST`, `PATCH`, `PUT`, `DELETE`) as
one shared handler:

1. Join `params.path` (awaited — Next 16) onto `API_URL`, carrying the query string through
   verbatim.
2. Read `askrepo_access`. If absent, refresh first; if that fails, clear cookies and return
   `401 {detail:{code:"INVALID_TOKEN"}}`.
3. Call the backend with `Authorization: Bearer …`, forwarding method, body, and `Content-Type`.
   A request with a body sets `duplex: "half"`.
4. On `401`: refresh **once**, retry **once**. On a second `401`, clear cookies and return it.
5. Return the backend's status, body, and headers — **with `set-cookie` removed**.

**Why `set-cookie` is stripped:** the backend sets its own refresh cookie on rotation. Passed
through, the browser would hold a second refresh cookie, on a different path, that nothing reads
and nothing rotates — and which would eventually be presented by some future code path and
trigger the replay revocation. Only §4.2's handlers write cookies.

**Why the retry is safe:** the `401` arrives with the status line, before any response body is
consumed. This is what makes retry possible at all on the SSE route (§9.6) — a half-read stream
cannot be replayed, so a retry sited any later would be a bug for that one endpoint. Written down
because it looks like an arbitrary ordering choice and is not.

The path is joined onto a fixed `API_URL`, so the handler cannot be used to reach an arbitrary
host. It is a token-attaching forwarder, not an open proxy.

### 4.4 The middleware gate

`middleware.ts` runs on everything except `/api/*` (the proxy owns those), `/_next/*`, and static
files.

| `askrepo_session` | `askrepo_access` | Path | Action |
| --- | --- | --- | --- |
| absent | — | `/login` | pass |
| absent | — | anything else | redirect `/login?next=<path>` |
| present | — | `/login` | redirect `/` |
| present | present | any | pass |
| present | absent | any | `refreshSession()` → set cookies → pass; on failure clear → `/login` |

The gate is coarse on purpose: it answers "is there a session at all", nothing more. Two things
it deliberately does **not** do:

- **It does not check `must_change_password`.** That flag is not a token claim
  (`docs/PRD.md` §4.0), so middleware could only learn it with an extra API call on every
  navigation. §6 handles it in the shell layout, which already fetches the user.
- **It does not check `is_admin`.** Route authorization lives in the page body (§7.4), because
  middleware sees a path and not a resource, and because the backend is the authority regardless.

### 4.5 The two clients

**`serverFetch(path, init?)`** — Server Components only. Reads `askrepo_access` via `cookies()`,
calls the backend directly. It never refreshes and never sets a cookie (§2.3): middleware
guarantees a fresh token before the render begins. A `401` here means the token expired between
middleware and render, which `redirect("/login")` handles.

**`apiFetch(path, init?)`** — browser only. Calls `/api/<path>` same-origin with
`credentials: "same-origin"`, parses errors through §4.6, returns typed JSON. It carries no
token and knows nothing about auth.

Both take paths from `lib/api/endpoints.ts`. A string literal path at a call site is how the
`sort` trap in §2.7 gets rediscovered one screen at a time.

### 4.6 One error type

```ts
export class ApiError extends Error {
  readonly status: number;
  readonly code: ErrorCode;          // the backend enum, mirrored
  readonly fieldErrors: Record<string, string>;  // camelCase keys, empty when none
}
```

Parsed from `{"detail":{"code":…,"message":…,"fields"?:…}}` (`docs/PRD.md` §5.1). A response
that is not JSON, or is JSON in another shape — a proxy's HTML error page, a truncated body —
becomes an `ApiError` carrying the real status and `INTERNAL_ERROR`. **No call site ever sees a
raw `fetch` rejection or an unparsed body**, which is what lets every screen handle failure with
one branch.

`fieldError(error, name)` reads `fieldErrors`, and is what `forms.md` §4 requires.

---

## 5. The data layer

**TanStack Query**, with every key in `lib/query/keys.ts`:

```ts
export const keys = {
  me: ["me"] as const,
  projects: {
    all: ["projects"] as const,
    list: (params: ListParams) => ["projects", "list", params] as const,
    detail: (id: string) => ["projects", "detail", id] as const,
  },
  conversations: { /* the same shape */ },
  users: { /* the same shape */ },
};
```

Prefix invalidation (`forms.md` §8) is then `invalidateQueries({ queryKey: keys.projects.all })`,
and cannot be spelled two ways in two components.

**Server prefetch, then hydrate.** This is what the BFF buys, and skipping it would mean paying
for SSR and rendering a spinner anyway. A list `page.tsx`:

1. is a Server Component that awaits `searchParams` (Next 16);
2. builds the same params object the client screen will build;
3. prefetches `keys.<resource>.list(params)` with `serverFetch` into a request-scoped
   `QueryClient`;
4. renders `<Suspense><HydrationBoundary state={dehydrate(qc)}><Screen/></HydrationBoundary></Suspense>`.

The client screen reads `useSearchParams()`, derives the identical params, and calls `useQuery`
with the identical key. `<Suspense>` is not optional — `navigation.md` §6 notes that a route
reading `useSearchParams()` fails `next build` without it.

Detail pages do the same for `.detail(id)`.

**Polling, bounded.** A project sits at `pending → cloning → indexing` for minutes:

- the list query sets `refetchInterval: 3000` **only while some item is non-terminal**;
- the detail query, only while that project is non-terminal or `reindexInProgress`;
- both set `refetchIntervalInBackground: false`.

A backgrounded tab polling every three seconds for an hour is a defect, and refetch-on-focus
already satisfies `forms.md` §10's requirement that the flow survive the operator navigating
away.

Defaults: `staleTime: 30_000`, `retry: 1`, and **no retry on an `ApiError` with a 4xx status** —
retrying a `403` three times produces three identical failures and delays the message.

---

## 6. The shell and navigation

`app/(app)/layout.tsx` is a Server Component and does three things in order:

1. `serverFetch("/auth/me")` → the `UserResponse`.
2. If `mustChangePassword`, `redirect("/change-password")`. That route lives under `(auth)`, so
   it renders shell-less, and it stays reachable because the backend exempts the whole `/auth`
   surface from its own gate (`docs/PRD.md` §4.0).
3. Render `<AppShell user={user}>{children}</AppShell>`, publishing the user through context for
   `use-session.ts`.

**The permission flash is eliminated structurally.** `navigation.md` §4 requires that the sidebar
render placeholder rows rather than a filtered list while the profile is pending. With the user
resolved before the first byte there is no pending state — the rule is satisfied by there being
nothing to get wrong, not by a skeleton. Do not add one back and wonder what it is for.

**Geometry** is fixed by `docs/design.md` and `design-system.md` §9: navbar fixed, `h-16`,
`z-50`, `bg-card` with `border-b`; sidebar `w-64`, `top-16`, `h-[calc(100vh-4rem)]`, `z-40`,
`bg-sidebar` with `border-e`; main content `mt-16 p-4 md:p-8`, `max-w-7xl` for lists and
`max-w-3xl` for forms and prose. Below `md` the sidebar is off-canvas over a
`bg-black/30 backdrop-blur-sm` backdrop at `z-30`.

Navbar contents, left to right: the mobile sidebar toggle, the brand, a spacer, the theme
toggle, the account menu. Breadcrumbs sit at the top of the main content, not in the navbar.

**`lib/nav.ts`** declares the four destinations that exist:

```ts
[
  { title: "Dashboard", href: "/",              icon: LayoutDashboard },
  { title: "Projects",  href: "/projects",      icon: FolderGit2 },
  { title: "Ask",       href: "/ask",           icon: MessagesSquare },
  { title: "Settings",  href: "/settings",      icon: Settings, children: settingsNav },
]
```

`settingsNav` lives in `lib/settings-nav.ts` and holds one child, `/settings/users`, flagged
`adminOnly`. The split is required, not tidy: `nav.ts` imports the child list as a **value**, so
the child module importing a type back from `nav.ts` would close a cycle — hence
`lib/nav-child.ts` holding the shared `NavChild` shape (`navigation.md` §1).

**`/qa` is absent.** `navigation.md` §6 lists it in the target route shape, but it is M4. A nav
item pointing at a route that does not exist is broken UI, and adding it "ready for later" is how
that ships.

`visibleNavTree(user)` is pure — it takes the user and returns the tree with children resolved
and `adminOnly` items removed, and a group whose children are all unreachable removed entirely
(`navigation.md` §2, §3). `components/layout/app-sidebar.tsx` renders it and computes nothing.
The Settings group renders as a `Collapsible` whose trigger is the parent row — not a link — and
opens already expanded when the route is inside it.

Breadcrumbs resolve the trail by longest matching nav item, and emit the separator as a
**sibling** of the item inside a `Fragment` (`navigation.md` §5) — nesting it produces invalid
HTML that passes every render assertion and fails hydration in a real browser.

**Base UI composition is `render`, never `asChild`** (`design-system.md` §7):
`<SidebarMenuButton render={<Link href={item.href} />}>`.

**Theme.** `next-themes` with `attribute="class"`, `defaultTheme="system"`,
`disableTransitionOnChange`. `globals.css` already declares
`@custom-variant dark (&:where(.dark, .dark *))` and `app/layout.tsx` already carries
`suppressHydrationWarning` with a comment naming the provider — the scaffolding was written
expecting this.

**Account menu** (`dropdown-menu` on an `avatar` of the user's initials): name and email, Change
password, Log out, Log out everywhere.

---

## 7. M0 screens

### 7.1 `/login`

Centred `card`, `max-w-sm`, shell-less. Email and password.

Client validation stops at **required** and **contains an `@`** (`forms.md` §4). Nothing else —
the password policy lives in `backend/app/core/passwords.py` and a copy here could not be kept
honest.

`401 INVALID_CREDENTIALS` renders as a form-level `Alert`, **not** a field error. The backend
returns one uniform message for "unknown email" and "wrong password", compared against a dummy
hash so even the timing does not differ (`docs/PRD.md` §4.0); attaching it to the email field
would undo that deliberately. `429 RATE_LIMITED` renders the same way, with the backend's message.

On success: `mustChangePassword` → `/change-password`; otherwise the `next` parameter; otherwise
`/`.

**`next` is validated before use.** It must begin with exactly one `/` and must not begin with
`//`, or it is discarded and `/` is used. An unvalidated `?next=` is an open redirect, and it sits
on the login page — the one place a redirect is most useful to someone phishing an operator.

### 7.2 `/change-password`

The forced route: `FormPage`, shell-less, `max-w-3xl`, current password and new password. It has
no `backHref` — the operator cannot navigate away from it while the flag is set — but it does
carry a **Log out** link, because someone who cannot satisfy the form must still be able to
leave.

`422 WEAK_PASSWORD` arrives with a `fields` map and renders against `newPassword`. The helper text
does not enumerate the policy (`forms.md` §4): it says to choose a strong password not used
elsewhere, and the backend supplies the specifics when they are violated.

On success: invalidate `keys.me`, toast, `router.replace("/")`. The backend revokes every *other*
refresh token, so the current session survives and no re-login is needed. It returns no new
access token, and none is needed — `must_change_password` is not a claim, so the existing token
starts working everywhere the instant the row changes.

The same `ChangePasswordFields` component is mounted inside `FormDialog` from the account menu.
`forms.md` §2 exists for exactly this: moving a form between shells is a swap, not a rewrite.

### 7.3 `/` — dashboard

Two recent lists — five projects by `updated_at`, five of your own conversations — plus the two
primary actions. The stat tiles above them ("N projects", "N conversations") read `totalCount`
off **those same two queries**, which `PaginatedResponse` returns on every page; a separate
`limit=1` count query would be two extra round trips for a number already in hand.

No per-status breakdown (§2.6).

### 7.4 `/settings/users`

`/settings/page.tsx` redirects to `/settings/users` (`navigation.md` §3: a group's index route
only redirects to its first reachable child).

The list follows `docs/design.md` → Lists: name · email · role badge · last login · created ·
actions, with search, pagination, skeleton rows, and an empty state carrying the primary action.

| Action | Surface | Notable failure |
| --- | --- | --- |
| Create | dialog — name, email, password, isAdmin (4 inputs) | `409 EMAIL_ALREADY_EXISTS` → banner |
| Edit | dialog — name, isAdmin | `409 LAST_ADMIN` → banner |
| Reset password | dialog — new password | `422 WEAK_PASSWORD` → field |
| Deactivate | `ConfirmDialog` | `409 LAST_ADMIN` → banner |

`LAST_ADMIN` names no field, so it renders as the dialog's form-level `Alert` and never as a
field error — `forms.md` §4 puts a banner exactly where the backend named nothing.

**The route body is wrapped in an admin gate rendering `<Forbidden />`.** Hiding the nav item is
not gating the route (`navigation.md` §6) — an operator can type the URL. The gate mirrors the
backend's `ADMIN_REQUIRED`; it does not replace it.

---

## 8. M1 screens

### 8.1 `/projects`

The standard list skeleton: page header with "Add project", a debounced search bound to
`?search=`, a `Card` with no padding wrapping the `Table`, pagination inside the same card.

Columns, in `docs/design.md`'s mandated order — identity, status, timestamps, actions: name ·
repository and branch (`font-mono`) · status `Badge` · files / chunks · last indexed commit
(`font-mono`, shortened) · updated (relative, with the ISO value in `title`) · actions.

Loading renders `Skeleton` rows matching the column count, never a spinner, so the layout does
not jump. An empty list renders an empty state carrying "Add project", never a bare "No results".

**Status colour comes from `lib/status.ts` and nowhere else** (`design-system.md` §5):
`pending`/`cloning`/`indexing` → `warning`, `ready` → `success`, `failed` → `danger`. The badge,
the detail header, and the dashboard tile call the same function, so they cannot disagree.

**Create** is a `FormDialog` (3 inputs — `repoUrl`, `branch` defaulting to `main`, optional
`pat`), `size="md"`. `422` with `repoUrl` in `fields`, or `INVALID_REPO_URL`, renders on the
field. The PAT input is **write-only**: helper text says a stored token is left unchanged when
blank, and there is never a masked placeholder that looks like a value (`forms.md` §9) — the API
never returns a PAT, not even masked, so a placeholder would be a lie an operator submits.

**The dialog closes on `201`.** The clone and index then run for minutes, and progress appears on
the project row. Holding the dialog open on the job would violate `forms.md` §10 and would lose
the work the moment the operator navigated away — which they will.

**Row actions** (`dropdown-menu`): Open · Reindex · Delete. Reindex and Delete are shown only when
`user.isAdmin || project.createdBy === user.id`. The client gate **mirrors** the backend's
`created_by`/`is_admin` check; a `403 NOT_PROJECT_OWNER` still surfaces as an error toast, because
the client gate is a courtesy and the backend is the authority.

**Reindex reads the `202` outcome flag.** `ReindexResponse` is `{enqueued, project}`, and
`docs/PRD.md` §5.1 put the flag there so a caller can tell "I started one" from "one was already
running" without an error branch. `enqueued: true` toasts "Reindex started"; `false` toasts
"A reindex is already running". Toasting success for both would waste the flag at the last step.

**Delete has one designed-for failure.** `DELETE /projects/{id}` must reach Qdrant to satisfy
`docs/PRD.md` §5.1's same-operation hard delete, and returns `503 VECTOR_STORE_UNAVAILABLE` when
it cannot — committing nothing, so the project stays in the list. Without a specific message that
looks exactly like a delete that silently did nothing, so the toast says the vector store is
unreachable, the project was not deleted, and the action can be retried.

### 8.2 `/projects/[id]`

Header: name, repository link, branch, status badge, and the same gated actions.

Stat cards: files indexed, chunks, `lastIndexedCommit` (`font-mono`), embedding model. A `danger`
`Alert` carrying `error` when the status is `failed` — that string has already been through the
backend's `scrub`, so it is safe to render, and it is the only place an operator learns why a
clone failed.

While cloning or indexing, an **indeterminate** `Progress` with the phase as its label. The API
reports a phase, never a percentage; rendering a percentage would mean inventing one, and an
invented progress bar that sits at 60% for eight minutes is worse than an honest indeterminate
one. Non-blocking and resumable on reload, per `docs/design.md` → Feedback.

Plus "Ask about this project" → `/ask?projectId=<id>`, enabled only when `ready`.

---

## 9. M2 — `/ask` and the answer stream

### 9.1 Layout

`app/(app)/ask/layout.tsx` renders the conversation rail beside `{children}`, so switching
conversations does not remount the rail.

The rail lists **the caller's own** conversations (`GET /conversations`, paginated, with a project
filter bound to `projectId`), each row showing the derived title and a relative timestamp, with a
row menu offering Delete. There is no "all conversations" view anywhere in the product
(`navigation.md` §7) — conversations are private, `is_admin` does not widen that
(`docs/PRD.md` §4.2), and a UI affordance implying otherwise would be the first step toward
someone adding the route.

Deleting the open conversation `router.replace("/ask")`s.

### 9.2 The project picker

Only `ready` projects can be asked (`409 PROJECT_NOT_READY` otherwise). With no status filter on
`GET /projects` (§2.6), the picker fetches `limit=100` by recency and filters client-side:

- non-`ready` projects appear **disabled, labelled with their status**, not hidden — an operator
  who just added a repository should see it indexing, not conclude it vanished;
- beyond 100 projects the picker is incomplete, so it also drives the server-side `?search=`.

That cap is a known limit, written down here rather than discovered later.

### 9.3 Starting a conversation

Two calls, with a navigation between them:

1. `POST /conversations {projectId}` → `{id}`
2. `router.replace("/ask/{id}")`
3. `POST /conversations/{id}/messages {question}` → the stream

The question survives the navigation through a module-level map in `lib/ask/pending.ts`, written
before the navigation and read exactly once by the conversation screen. `replace`, not `push`, so
Back does not return to a composer that has already fired.

A hard reload inside that window loses the question — correctly, because the backend persists the
user message only when the messages endpoint is called, so nothing was stored either.

### 9.4 `lib/ask/sse.ts`

A parser over `ReadableStream<Uint8Array>`, not an `EventSource`: the endpoint is a `POST` with a
JSON body, which `EventSource` cannot send at all.

Four requirements, each of which fails as a hang or a silently dropped answer rather than an
exception:

- **Frames end at `\n\n`, and a network chunk can split one.** Buffer; emit only complete frames.
- **`: keep-alive` comments arrive every 15 seconds** during any gap (`KEEP_ALIVE` in
  `backend/app/schemas/conversation.py`) and must be skipped, not parsed.
- **`data:` may span multiple lines.** Join with `\n` before `JSON.parse`.
- **An unknown event name is ignored, never fatal.** M3 will add events to this stream; a client
  that throws on one it does not recognise turns a backend feature addition into a frontend
  outage.

### 9.5 `useAskStream` and the ordering contract

From `.claude/rules/rag.md`:

| Event | Handling |
| --- | --- |
| `status` | phase label — `queued` / `rewriting` / `retrieving` / `generating`. May repeat; may never arrive |
| `citations` | **exactly once, before the first token** → the sources block renders while the answer types |
| `token` | appended to a **ref**, flushed to state on an animation frame |
| `done` | terminator: `messageId`, `model`, `finishReason`, `citedIndexes`, `groundingWarnings` |
| `error` | terminator: `messageId`, `code`, `message`, `finishReason` |

Token accumulation goes through a ref because a long answer is thousands of fragments, and a
`setState` per fragment re-renders a markdown tree thousands of times.

**There is a third termination the contract does not name: the stream simply ending.** No `done`,
no `error` — the connection dropped. The backend has already persisted the partial with
`finishReason: "disconnected"` (`docs/PRD.md` §4.2), so the UI marks the answer interrupted.

After **any** of the three, the hook invalidates `keys.conversations.detail(id)`. That refetch is
the reconciliation point: the optimistic message is replaced by the stored one, which is where
the real `messageId` and the resolved `cited` flags come from. It also invalidates
`keys.conversations.all`, so the rail picks up the title the backend derived from the first
question.

`finishReason: "timeout"` offers a Retry button; `"error"` does not.

### 9.6 Citations and grounding

The `citations` event carries `cited: null` — it is emitted before generation and cannot know
what the model will use. `done.citedIndexes` says which were actually used. So: render all
retrieved spans as "Sources (N)" during the stream, mark the cited ones on `done`, and let the
refetch confirm against the stored `cited` flags.

`[n]` markers in the answer become superscript anchors that highlight the matching source row.

**`groundingWarnings` render as a visible `warning`-toned strip under the answer:**

| Warning | Rendered as |
| --- | --- |
| `no_context` | nothing relevant was found in this project; the answer is a fixed refusal. The empty sources block is suppressed |
| `uncited_answer` | the answer cites none of the excerpts it was given |
| `unknown_paths` | the answer names files that were not among the excerpts |

`rag.md` is blunt about why: these checks do not make the model honest, they make dishonesty
visible, and *a check whose result nothing can see is not a check*. A console line or a tooltip
would be the same as not having them.

### 9.7 Markdown, and why raw HTML is refused

`react-markdown` + `remark-gfm`. **No `rehype-raw`. No `dangerouslySetInnerHTML`. Anywhere.**

`docs/PRD.md` §9 and `rag.md` both establish that retrieved excerpts are untrusted input written
by anyone with commit access to an indexed repository, and the answer can quote them verbatim.
Rendering raw HTML would take a comment in someone's repo and turn it into markup in the
operator's browser — converting a prompt-injection attempt, which can only make the model *say*
something wrong, into something that can *do* something in the client. That is precisely the
architectural bound §9 relies on, given away at the last render step.

Code blocks render in `font-mono` inside an `overflow-x-auto` container with a copy button, and
**no syntax highlighter**: `shiki` is a large dependency and a build-time concern for a first
pass, and a plain mono block is honest about what it is.

### 9.8 Pre-flight errors are inline

`.claude/rules/rag.md` makes the split structural: everything that can return a status other than
`200` happens in `ConversationService.prepare_turn`, before the `StreamingResponse`. So `404`,
`409 PROJECT_NOT_READY`, `409 EMBEDDING_MODEL_CHANGED` and `422` all arrive as ordinary HTTP
failures, before any body, and render **in the conversation** where the question was asked —
not as a toast, because they are about that turn.

`EMBEDDING_MODEL_CHANGED` gets a real explanation rather than its code: this project was indexed
with a different embedding model, its stored vectors cannot be searched with the current one, and
it must be re-indexed before it can answer — with a Reindex button when the operator is permitted
one. Left as a bare code it is unactionable, and this is the error most likely to appear on a
working instance after an operator changes `EMBEDDING_MODEL`.

### 9.9 The stream through the proxy

The proxy (§4.3) forwards the request with `duplex: "half"` and returns
`new Response(upstream.body, { status, headers })`, so nothing is buffered. It preserves
`Content-Type: text/event-stream`, `Cache-Control: no-cache`, and `X-Accel-Buffering: no` — the
backend sets the last two precisely so an intermediary does not accumulate the stream and deliver
it in one piece, and the BFF is now an intermediary.

Refresh-and-retry happens **before the body starts**, which §4.3 guarantees by acting on the
status line. A retry moved any later would be correct for every other route and broken for this
one.

**Disconnect** is an `AbortController.abort()` on unmount or navigation. Nothing else is needed:
the backend emits nothing (nobody is listening) and persists what arrived, so reopening the
conversation shows the partial.

---

## 10. Design-system conformance

Not new rules — the specific places this milestone is most likely to break
`.claude/rules/design-system.md`:

- **No `dark:` colour utility in any component.** Tokens already know what dark means. If a
  surface needs something no token provides, the fix is a new token in `globals.css` — the only
  file in the repository permitted to hold a raw hex colour.
- **No palette utility.** `bg-zinc-50`, `text-slate-600`, `border-gray-200` name a colour rather
  than a role and do not follow the theme. `bg-card`, `text-muted-foreground`, `border-border`.
- **Pair every background with its `-foreground`.** `bg-primary` takes `text-primary-foreground`,
  never `text-white` — which is already wrong in dark mode, where `primary-foreground` is
  near-black.
- **Never hand-roll a component shadcn provides.** `components/ui/` is CLI-managed and is never
  edited by hand; keeping it untouched is what makes an upstream diff readable.
- **Spacing from `1, 2, 3, 4, 6, 8, 12` only**, with `docs/design.md` → Spacing as the per-context
  default.
- **`font-semibold` is the heaviest weight in the system.** No `font-bold`.
- **Icons are `lucide-react`**, `size-4` inline and `size-5` standalone, and every icon-only
  control carries an `aria-label`.

Components installed, by stage, from `docs/design.md`'s inventory (minus `form`, §2.5):

| Stage | `npx shadcn@latest add …` |
| --- | --- |
| Foundation | `button input label field card alert sonner sidebar breadcrumb dropdown-menu avatar separator skeleton dialog` |
| M1 | `table badge select tooltip progress` |
| M2 | `textarea scroll-area collapsible tabs` |

**`dialog` moves from the M1 row to M0.** `docs/design.md` currently lists it under M1
(projects), but every M0 form is a dialog by `forms.md` §1's count — create user (4 inputs),
reset password (1), change own password (2) — so the M0 screens cannot be built without it. The
inventory row is wrong rather than the plan; §13 corrects it.

---

## 11. Testing

Vitest + jsdom + Testing Library, wired into `make test`. `fetch` is stubbed directly rather than
through MSW — the surface under test is small, and a mock server is a dependency plus a second
place for the wire contract to be described.

Eight units, chosen because each fails **silently**:

| Unit | Assertions |
| --- | --- |
| `lib/nav.ts` | `adminOnly` hidden from a non-admin; a group with no reachable children hidden entirely; `children` absent (not empty) on leaves; the tree is stable for an admin |
| `lib/api/errors.ts` | the `{detail:{code,message,fields}}` envelope parses; `fields` keys stay camelCase; a non-JSON body becomes `INTERNAL_ERROR` carrying the real status |
| `lib/ask/sse.ts` | a frame split across two chunks; `: keep-alive` skipped; multi-line `data:` joined; an unknown event ignored rather than thrown |
| `lib/auth/session.ts` | two concurrent `refreshSession()` calls produce exactly one backend call and share the result |
| `app/api/[...path]/route.ts` | `401` → refresh → retry once; a second `401` clears cookies and returns `401`; backend `set-cookie` never reaches the caller; the query string survives |
| `app/api/auth/login/route.ts` | the access token is absent from the response body; both cookies are set `httpOnly`; a `429` passes through with its body |
| `useAskStream` | `citations` before the first token; a stream ending with no terminator marks the answer interrupted; `groundingWarnings` reach the rendered output; tokens accumulate in order |
| `form/` shells + `lib/status.ts` | a `422` with `fields` renders per-field errors and **no** banner; an error naming no fields renders the banner; every `ProjectStatus` maps to exactly one token |

Not tested: layout and pixels, shadcn internals, and anything `next build` or `eslint` already
catches. No Playwright — an end-to-end suite needs Postgres, Qdrant, Kafka and Ollama in CI, which
is a larger decision than this milestone.

`make test` becomes `test-backend test-frontend`; `make test-frontend` runs `bun run test`.

---

## 12. Configuration

| Variable | Where read | Notes |
| --- | --- | --- |
| `API_URL` | **server only** — proxy, middleware, `serverFetch` | Under Compose this is `http://backend:8000`, the service name, because the fetch now happens server-side |
| `NEXT_PUBLIC_API_URL` | — | **Removed.** The browser no longer talks to the backend |

This inverts the note currently in `CLAUDE.md`, `frontend/README.md`, and
`frontend/.env.example`, all of which explain that the value must be an address the *browser* can
reach. That was correct for a direct client and is wrong for a BFF. §13 fixes all three.

---

## 13. Documentation amendments — part of this change, not a follow-up

Per `.claude/rules/documentation.md`, these ship in the same change:

| Doc | Change |
| --- | --- |
| `docs/PRD.md` §5 | The "Frontend: Minimal Next.js" row gains the BFF and a pointer to §2.1 here |
| `docs/PRD.md` §4.0 | A note that Next mirrors the session into its own `Path=/` cookies on the frontend origin, and why (§2.2) |
| `docs/design.md` | `form` removed from the M0 inventory row, with a note that `field` is the composition primitive and react-hook-form is banned by `forms.md` §4; `dialog` moved from the M1 row to M0, where every form already needs it (§10) |
| `CLAUDE.md` | Frontend section rewritten: routes that exist, the BFF, `API_URL` replacing `NEXT_PUBLIC_API_URL`, and the removal of "one route so far… no API client and no component library installed yet" |
| `frontend/README.md` | Scripts (`test`), env vars, the app layout, and the BFF explained |
| `frontend/.env.example` | `API_URL` replaces `NEXT_PUBLIC_API_URL`, with the inverted note |
| `infra/docker-compose.yml` | The frontend service's environment; the header URL list re-checked |
| `README.md` | Status banner and roadmap: the M0–M2 frontend ships |
| `Makefile` | `test-frontend`, and `test` depending on it |
| `CONTRIBUTING.md` | `make check` now runs frontend tests too |

Two findings are **reported, not fixed** (`.claude/rules/contradiction-halt.md`): the snake_case
`sort` values (§2.7), and `docs/design.md`'s `form` row, which §2.5 resolves by amending the doc
rather than by installing the component.

---

## 14. Staging

Five stages, to be turned into an implementation plan by `writing-plans`:

1. **Foundation** — dependencies, `shadcn init` + the foundation components, `lib/api/*`,
   `lib/auth/*`, the three auth handlers, the proxy, `middleware.ts`, `lib/query/*`,
   `lib/nav*`, `lib/status.ts`, the shell, theme, form shells, feedback components, Vitest wiring.
2. **M0 screens** — `/login`, `/change-password`, the account menu, `/settings/users`.
3. **M1 screens** — `/projects`, `/projects/[id]`, the create dialog, the gated actions.
4. **M2** — `/ask`, the rail, the picker, the SSE parser, `useAskStream`, the answer renderer.
5. **Dashboard and the doc sweep** — `/`, then §13 in full.

Stage 1 carries nearly all the risk: the refresh paths, the cookie boundary, and the proxy. It is
also the only stage that cannot be demonstrated in a browser on its own, which makes its tests
(§11) the acceptance evidence rather than a screenshot.

---

## 15. Out of scope

- `/qa` and every QA List screen (M4).
- Anything anticipating M3's graph beyond tolerating unknown SSE events.
- Syntax highlighting in answers.
- Playwright or any end-to-end browser suite.
- Optimistic updates; every mutation invalidates and refetches.
- Sharing a conversation with a colleague (`docs/PRD.md` §4.2, out of scope for v1).
- Any per-project access UI — phase 2 (`docs/PRD.md` §2.1).
- Internationalisation, and any offline or service-worker behaviour.

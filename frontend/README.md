# AskRepo Frontend

Next.js UI for AskRepo — the codebase-aware assistant described in
[`docs/PRD.md`](../docs/PRD.md).

**Milestone progress is recorded in [`docs/PRD.md`](../docs/PRD.md) §6 and nowhere else.** The
screens that exist are sign-in, self-service password reset (`/forgot-password`, `/reset-password`,
Phase 2.4), and the forced first-login password change, the dashboard,
projects (list, detail, create, re-index, delete), Dev Knowledge with streamed answers, admin
user management, admin role management (`/settings/roles` and the `/settings/roles/[id]`
permission matrix), the admin audit trail (`/settings/audit` and the
`/settings/audit/[eventId]` detail), and the QA Checklist — the `/checklist` module list and the
`/checklist/[moduleId]` grid with chat and review panel, which also carries a Mock Data tab
(generate, refine by chat, review the pending change set, export JSON/`.xlsx`) beside the
checklist grid, no route of its own. `/checklist/export` exports a project's checklist and mock
data, for every module or a chosen set, as one file or a `.zip`. The project detail page at `/projects/[id]` likewise
carries a **Members** tab — grant, change role, revoke — as a tab, not a route of its own, and an
**Eval** tab listing the project's synthetic Q&A sets with a generate dialog. A set opens at
`/projects/[id]/eval/[setId]`: its pairs (exclude or include each), its runs, a run's per-pair
verdicts and answers, and a comparison of two runs on the pairs both answered.
Notifications add `/notifications` (a paginated list, filterable by project/type/unread) — the
bell itself lives in the app shell's navbar, not a route. `/profile`, opened from the account
menu, carries seven sections — account, answer style (three radio dials shaping your own Ask
answers), language (a radio group that saves with `PUT /me/language` and sets the
`askrepo_locale` cookie), sessions (with a per-session sign-out), activity (the caller's own audit-trail
rows), notifications (per-event in-app and email switches; the email switch is enabled only
when `MAIL_ENABLED` is true on the instance), and password — and
`/settings/notifications` now only redirects to `/profile#notifications`.

Model output carries a vote. `FeedbackControl` (`components/output-feedback/`) puts a thumbs-up
and a thumbs-down under an Ask answer, a refinement-chat reply and each change set; thumbs-down
asks for reasons and an optional note. Administrators read the votes at `/settings/feedback` — a
summary and a filterable table, with no voter and only the day of each vote.

**Controls are hidden from what the server said, never from a client-side rule.** Each project
response carries the caller's own `role` and effective `permissions`, and the UI hides what
they would be refused. That hiding is cosmetic: the backend's `require_permission` is the
control, and a hidden button that was clicked anyway still gets a `403`.

This layer is **not** a thin client. It acts as a backend-for-frontend: it holds the session in
its own httpOnly cookies and calls the [backend](../backend/README.md) on the browser's behalf,
so no token is ever readable by a script on the page. See
[the design spec](../docs/superpowers/specs/2026-08-29-frontend-m0-m2-design.md) §2.1 for why
that departs from the PRD's "keep it thin".

## Stack

Next.js 16 (App Router) · React 19 · TypeScript · Tailwind CSS 4 · next-intl · Bun

## Running locally

```bash
cd frontend
cp .env.example .env.local    # optional
bun install
bun dev
```

Then open <http://localhost:3000>. It expects the API on
<http://localhost:8000> — start that too (see the
[backend README](../backend/README.md)), or bring up the whole stack with
`cd infra && docker compose up --build`.

## Scripts

| Command                   | Does                                                 |
| ------------------------- | ---------------------------------------------------- |
| `bun dev`                 | Dev server with hot reload                           |
| `bun run build`           | Production build — catches type errors dev tolerates |
| `bun start`               | Serve the production build                           |
| `bun lint`                | ESLint                                               |
| `bunx tsc --noEmit`       | Typecheck without building                           |
| `bunx prettier --write .` | Format (Tailwind class sorting included)             |
| `bun run test`            | Vitest, single pass                                  |
| `bun run test:watch`      | Vitest, watching                                     |
| `bun run typecheck`       | `tsc --noEmit`                                       |

Or from the repo root: `make dev-frontend`, `make build`, `make lint-frontend`,
`make format-frontend`, `make typecheck`.

## Design system

[`docs/design.md`](../docs/design.md) is the reference; `app/globals.css` implements it. Palette
values come from the [Fexend](https://github.com/fexend/fexend-html) design system, structured as
one semantic token per role, redefined under `.dark`.

Two rules do most of the work — full set in
[`.claude/rules/design-system.md`](../.claude/rules/design-system.md):

- **Never write a `dark:` colour utility.** `bg-card`, not `bg-white dark:bg-slate-900`. The token
  already knows what dark means, so dark mode is a change to `globals.css` alone.
- **Never use a palette utility.** `bg-zinc-50` names a colour, not a role, and won't follow the
  theme. Use `bg-card`, `text-muted-foreground`, `border-border`.

`app/globals.css` is the only file permitted to contain a raw hex colour.

Components come from shadcn on the Base UI base, installed via
`npx shadcn@latest add <name>` into `components/ui/`. Composition uses
`render={<Component />}`, **never `asChild`** — `asChild` does not exist on this base and fails
silently. `components/ui/` is CLI-managed and never hand-edited; see the component inventory in
`docs/design.md` for what lands at which milestone.

## Layout

```
frontend/
├── proxy.ts               # session gate + the refresh point for navigations
├── i18n/request.ts        # resolves the locale once per request, loads its catalogue
├── messages/              # the catalogues: en/ is the source, one dir per language
├── app/
│   ├── layout.tsx         # fonts, theme, query provider, toaster
│   ├── globals.css        # Tailwind entry + theme tokens (only file with raw hex)
│   ├── manifest.ts        # web app manifest — served at /manifest.webmanifest
│   ├── favicon.ico icon.png apple-icon.png   # copies of ../assets/favicon/
│   ├── (auth)/            # shell-less: /login, /forgot-password, /reset-password,
│   │                      #   /change-password
│   ├── (app)/             # the shell: dashboard, projects (/projects, /projects/[id],
│   │                      #   /projects/[id]/eval/[setId]),
│   │                      #   ask, checklist (/checklist, /checklist/export,
│   │                      #     /checklist/[moduleId]),
│   │                      #   notifications (/notifications), profile (/profile),
│   │                      #   settings (/settings/users, /settings/roles, /settings/roles/[id],
│   │                      #     /settings/audit, /settings/audit/[eventId],
│   │                      #     /settings/feedback,
│   │                      #     /settings/notifications — redirects to /profile#notifications)
│   └── api/
│       ├── [...path]/     # the API forwarding route the browser talks to
│       └── auth/          # login, refresh, logout, locale — the cookie writers —
│                          #   plus the public forwards: password-policy and
│                          #   password-reset/{availability,request,confirm}
├── components/
│   ├── ui/                # shadcn, CLI-managed
│   ├── layout/ form/ feedback/ live/
│   └── auth/ projects/ ask/ checklist/ mock-data/ change-sets/ eval/ roles/ users/ audit/
│       notifications/ output-feedback/ profile/
│       #   auth/ holds the signed-out language selector
│       #   projects/ also holds the Members tab: member-table, add-member-dialog,
│       #     and the content-language section
│       #   change-sets/ holds the operation list the checklist and mock-data panels share
│       #   eval/ holds the set table, generate dialog, set screen, pair and run tables,
│       #     the run sheet and the two-run comparison
│       #   roles/ holds the role table, create dialog, permission matrix, role badge
│       #   audit/ holds the audit table, filters and event detail
│       #   live/ holds the provider for the `GET /events` stream
│       #   notifications/ holds the bell, the popover list, and the deep-link mapper's UI
│       #   output-feedback/ holds the vote control and the admin feedback screen's
│       #     table, summary and filters
│       #   profile/ holds the seven sections: account, answer style, language,
│       #     sessions, activity, notifications (reuses notifications/preferences-screen),
│       #     password
├── hooks/                 # one file per resource
├── lib/
│   ├── api/               # types, endpoints, errors, both fetch clients
│   ├── auth/              # cookie names, single-flight refresh, the locale cookie,
│   │                      #   forwarded headers, the public forward
│   ├── i18n/              # the language list, error text by code, catalogue parity test
│   ├── ask/               # SSE parser, pending-question carrier
│   ├── checklist/         # change-set operations, path helpers, the refinement stream
│   ├── mock-data/         # the mock-data refinement stream
│   ├── live/              # reconnect backoff, event-to-query invalidation
│   ├── query/             # the query client, keys and provider
│   ├── eval-compare.ts    # two runs compared on the pairs both answered
│   └── nav.ts nav-child.ts settings-nav.ts can.ts status.ts dates.ts notifications.ts …
├── public/                # logo.png + the two android-chrome sizes the manifest names
└── .env.example
```

`../assets/` holds the brand source files. The icons under `app/` and `public/` are copies of
them, because Next resolves `favicon.ico` / `icon.png` / `apple-icon.png` by file convention
inside `app/` and the manifest needs stable public URLs — neither can point outside the app.
Re-export from `../assets/` when the mark changes.

## Translations

The interface ships in seven languages — `en`, `id`, `ja`, `ms`, `zh-HK`, `zh-TW`, `ko` — through
`next-intl`, without locale-prefixed routes: the language belongs to the user, not the URL.
`i18n/request.ts` resolves it once per request from the `askrepo_locale` cookie, then
`Accept-Language`, then English. The cookie mirrors the user's stored language
(`GET`/`PUT /me/language`); the profile page and the signed-out selector both change it.

```
messages/
├── en/                    # the source of every key
│   ├── <namespace>.json   # one file per area: ask, auth, checklist, errors, forms, …
│   └── index.ts           # assembles the namespaces into one catalogue
└── id/ ja/ ms/ zh-HK/ zh-TW/ ko/
    ├── <namespace>.json   # exactly en/'s keys
    ├── index.ts
    └── _meta.json         # { "reviewed": false } until a native speaker signs it off
```

- **`messages/en/` is the source.** `next-intl`'s `AppConfig` typing makes a missing or misspelled
  key a type error in `bun run build`. Write English first, then the same key in every other
  language.
- **Parity is a test.** `lib/i18n/messages.test.ts` fails when a language has a key English does
  not, lacks one English has, or drops or renames an ICU placeholder or tag (`{count}`,
  `<path>`). Plurals use ICU `plural`; languages with no plural forms use `other` alone.
- **Lint forbids literals.** `i18next/no-literal-string` (`eslint.config.mjs`) fails on JSX text
  and on `aria-label`, `placeholder`, `title` and `alt` under `app/` and `components/`; tests and
  `components/ui/` are exempt.
- **Errors are translated by code.** `useErrorText()` (`lib/i18n/error-text.ts`) looks up
  `errors.<ErrorCode>` and falls back to the backend's English message; `useFieldErrorText()`
  translates a `422` field error by its `fieldTypes` entry. A backend test,
  `tests/test_frontend_error_catalogue.py`, requires an entry in `messages/en/errors.json` for
  every `ErrorCode`. A few codes whose backend message names the specific fix
  (`ACTIONABLE_MESSAGE_CODES` in `lib/i18n/error-text.ts`) still show the backend's English text.
  A stream's `error` event is turned into an `ApiError` (`apiErrorFromEvent`) so it takes the
  same path.
- **English that lint cannot see remains:** the page metadata descriptions in `app/layout.tsx`
  and `app/manifest.ts`, and the shadcn components' own screen-reader and title strings under
  `components/ui/` ("Close", "Toggle Sidebar", "Sidebar").
- **What stays as written:** repository content (paths, identifiers, code), stored model output,
  admin-entered names, and each language's own name in the switchers (its endonym).
- **`_meta.json` is a fact about the file.** The six non-English catalogues are machine-assisted
  drafts, and each says `reviewed: false` until a native speaker signs it off.

**Adding a language:** a member in `backend/app/core/language.py` and in `lib/i18n/languages.ts`
(`tests/test_language_catalogue.py` fails when the two differ); a `messages/<tag>/` directory with
every namespace, an `index.ts` and a `_meta.json`; and a font fallback in `app/globals.css` if its
script needs one. The parity test picks the new directory up from the language list.

## Configuration

Still only one variable — per-project access added no frontend setting, because roles,
permissions and memberships are all read through the same `API_URL`-proxied backend. See
[`.env.example`](.env.example), and
[`../docs/configuration.md`](../docs/configuration.md#frontend) for the reasoning:

- `API_URL` — base URL of the AskRepo API, read on the **server** only: by the API forwarding
  route, `proxy.ts`, and `serverFetch`. The browser never calls the API directly, so this
  does not need to be reachable from a browser. Under Docker Compose it is the service name
  `http://backend:8000`, **not** the published host port. (This inverts the old
  `NEXT_PUBLIC_API_URL` rule, which was correct while the browser did the fetching.)

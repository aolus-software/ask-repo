# AskRepo Frontend

Next.js UI for AskRepo — the codebase-aware assistant described in
[`docs/PRD.md`](../docs/PRD.md).

**Milestone progress is recorded in [`docs/PRD.md`](../docs/PRD.md) §6 and nowhere else.** The
screens that exist are sign-in and the forced first-login password change, the dashboard,
projects (list, detail, create, re-index, delete), Dev Knowledge with streamed answers, admin
user management, and the QA Checklist — the `/checklist` module list and the
`/checklist/[moduleId]` grid with chat and review panel, which also carries a Mock Data tab
(generate, refine by chat, review the pending change set, export JSON/`.xlsx`) beside the
checklist grid, no route of its own.

This layer is **not** a thin client. It acts as a backend-for-frontend: it holds the session in
its own httpOnly cookies and calls the [backend](../backend/README.md) on the browser's behalf,
so no token is ever readable by a script on the page. See
[the design spec](../docs/superpowers/specs/2026-08-29-frontend-m0-m2-design.md) §2.1 for why
that departs from the PRD's "keep it thin".

## Stack

Next.js 16 (App Router) · React 19 · TypeScript · Tailwind CSS 4 · Bun

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
├── app/
│   ├── layout.tsx         # fonts, theme, query provider, toaster
│   ├── globals.css        # Tailwind entry + theme tokens (only file with raw hex)
│   ├── manifest.ts        # web app manifest — served at /manifest.webmanifest
│   ├── favicon.ico icon.png apple-icon.png   # copies of ../assets/favicon/
│   ├── (auth)/            # shell-less: /login, /change-password
│   ├── (app)/             # the shell: dashboard, projects, ask, checklist (/checklist, /checklist/[moduleId]), settings
│   └── api/
│       ├── [...path]/     # the API forwarding route the browser talks to
│       └── auth/          # login, refresh, logout — the only cookie writers
├── components/
│   ├── ui/                # shadcn, CLI-managed
│   ├── layout/ form/ feedback/
│   └── projects/ ask/ checklist/ mock-data/ users/
├── hooks/                 # one file per resource
├── lib/
│   ├── api/               # types, endpoints, errors, both fetch clients
│   ├── auth/              # cookie names + single-flight refresh
│   ├── ask/               # SSE parser, pending-question carrier
│   └── query/ nav.ts status.ts dates.ts can.ts
├── public/                # logo.png + the two android-chrome sizes the manifest names
└── .env.example
```

`../assets/` holds the brand source files. The icons under `app/` and `public/` are copies of
them, because Next resolves `favicon.ico` / `icon.png` / `apple-icon.png` by file convention
inside `app/` and the manifest needs stable public URLs — neither can point outside the app.
Re-export from `../assets/` when the mark changes.

## Configuration

Only one variable — see [`.env.example`](.env.example), and
[`../docs/configuration.md`](../docs/configuration.md#frontend) for the reasoning:

- `API_URL` — base URL of the AskRepo API, read on the **server** only: by the API forwarding
  route, `proxy.ts`, and `serverFetch`. The browser never calls the API directly, so this
  does not need to be reachable from a browser. Under Docker Compose it is the service name
  `http://backend:8000`, **not** the published host port. (This inverts the old
  `NEXT_PUBLIC_API_URL` rule, which was correct while the browser did the fetching.)

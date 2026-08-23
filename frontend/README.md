# AskRepo Frontend

Next.js UI for AskRepo — the codebase-aware assistant described in
[`docs/PRD.md`](../docs/PRD.md).

Per the PRD this layer stays deliberately thin: the interesting work lives in the
[backend](../backend/README.md). Right now it is the stock Next.js starter page.

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
`render={<Component />}`, **never `asChild`**. Nothing is installed yet — see the component
inventory in `docs/design.md` for what lands at which milestone.

## Layout

```
frontend/
├── app/
│   ├── layout.tsx      # root layout
│   ├── page.tsx        # landing page
│   └── globals.css     # Tailwind entry + theme tokens
├── public/
└── .env.example
```

## Configuration

Only one variable so far — see [`.env.example`](.env.example):

- `NEXT_PUBLIC_API_URL` — base URL of the AskRepo API. `NEXT_PUBLIC_`-prefixed
  vars are inlined into the client bundle at build time, so this must be an
  address the **browser** can reach. Under Docker Compose that means
  `http://localhost:8000` (the published port), not `http://backend:8000`.

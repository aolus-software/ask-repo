# The codebase

Where code lives, why it is layered the way it is, and where to put something new.

Read [`architecture.md`](architecture.md) first for the processes; this page is about the source
tree inside them.

---

## Backend layering

Every feature is the same four files plus a router. Data flows down, and each layer knows only
about the one below it.

```mermaid
flowchart TD
    R["<b>router</b> — app/api/routes/<br/><i>HTTP: status codes, dependencies</i>"]
    S["<b>service</b> — app/services/<br/><i>business rules, authorization, transactions</i>"]
    P["<b>repository</b> — app/repositories/<br/><i>queries. The only place SQL is written</i>"]
    M["<b>model</b> — app/models/<br/><i>SQLAlchemy tables</i>"]
    SC["<b>schema</b> — app/schemas/<br/><i>request/response shapes on the wire</i>"]
    R --> S --> P --> M
    R -.uses.-> SC
    S -.returns.-> SC
```

### A route is thin, on purpose

```python
@router.get("", response_model=PaginatedResponse[ProjectResponse], ...)
async def list_projects(
    current_user: CurrentUser,
    service: ProjectServiceDep,
    query: Annotated[ListQuery, Query()],
) -> PaginatedResponse[ProjectResponse]:
    return await service.list(query, actor=current_user)
```

**One service call per route.** No business logic, no `if user.is_admin`, no query building. The
one exception in the whole codebase is `ask_question`, which must both run a pre-flight check
and return a streaming response — and even there, all the policy is in the service.

Authorization lives in the **service**, not the route, so `reindex` and `delete` cannot drift
apart in what they permit.

### The wire boundary: `snake_case` in, `camelCase` out

Python attributes and Postgres columns are `snake_case`. Every JSON body is `camelCase`. The
translation happens in **exactly one class** — `ApiModel` in `app/schemas/base.py`, which applies
Pydantic's `to_camel` alias generator. Every request and response schema inherits it.

A schema on plain `BaseModel` silently ships `snake_case` keys. That is a defect, and
`tests/test_api_model.py` exists to catch it. It matters most for the **SSE event payloads**,
which never pass through a `response_model` — so FastAPI validates nothing about them, and the
`SSE_EVENT_MODELS` tuple that test walks is the only thing holding them to the rule.

### One error shape

Every error is `{"detail": {"code": ..., "message": ...}}`, built by `AppError`. `ErrorCode`
values are a **wire contract** — add members, never rename them. A `422` adds a `fields` map
keyed by the `camelCase` field name.

### `403` vs `404` is a security decision

- **`403`** when the caller may see the resource but not do this to it — deleting a project
  someone else created. Project existence is deliberately public.
- **`404`** when the caller should not learn it exists — another user's conversation.

Backwards, this either leaks existence or hides something the user can already see in a list.

---

## The access resolver

This is the single most consequential constraint in the repo, and it is one function:

```python
def resolve_project_scope(user: AuthenticatedUser) -> ProjectScope:
    """Which projects this caller may read."""
    return ProjectScope.all()          # phase 2 replaces this body
```

Today every authenticated user can list and query every project. **That is designed behaviour,
not a leak** — [`PRD.md`](PRD.md) §4.1 and `SECURITY.md` both say so. Per-project access control
is phase 2.

To make phase 2 a change rather than a rewrite, **all read scoping goes through this one
function**. A route, service or query that filters projects on its own is a defect *even when its
output is currently correct*, because it puts read scoping in two places.

Its counterpart `resolve_conversation_owner` sits in the same file so the contrast is visible
rather than folklore: projects are shared, conversations are private.

**`created_by` is not ownership.** It is attribution, and it gates destructive operations
(delete, reindex) alongside `is_admin`. It never scopes reads.

---

## Backend tree

```
backend/app/
├── main.py            FastAPI app + lifespan (topics, probes, queue)
├── worker.py          the separate process: 3 consumers + retry ladders + reconcile sweep
├── config.py          Settings — the only place os.environ is read
├── cli.py             seed-admins, run by the container entrypoint
│
├── api/
│   ├── deps.py        shared dependencies (CurrentUser, AdminUser, service factories)
│   └── routes/        12 routers, 55 routes
│
├── core/              cross-cutting: access, crypto, errors, middleware,
│                      passwords, rate_limit, repo_url, security
├── db/session.py      engine + sessionmaker
├── models/            6 modules, 13 tables
├── repositories/      12 repositories — the only place SQL is written
├── schemas/           request/response shapes, all on ApiModel
├── services/          11 services — business rules and authorization
│
├── ingestion/         cloner, walker, chunker, embedder/, vector_store, pipeline
├── queue/             topics, producer, consumer, retry, protocol, checklist, mock_data
├── rag/               retriever, chat, prompts, answerer, grounding, capability, errors
│   └── graph/         build.py, nodes.py, state.py
├── checklist/         generator, model_output, operations, source
└── mockdata/          generator, model_output, operations
```

### Reading order for a newcomer

1. `config.py` — what is configurable
2. `models/project.py` — the richest table, and the lease/generation columns
3. `api/routes/projects.py` → `services/project.py` → `repositories/project.py` — one feature
   through all four layers
4. `ingestion/pipeline.py` — the write path end to end
5. `rag/graph/build.py` — the answer graph in one screen

---

## Frontend layering

Next.js App Router, and **not a thin client**.

```
frontend/
├── app/
│   ├── (auth)/          login, change-password
│   ├── (app)/           dashboard, projects, ask, checklist, settings
│   └── api/
│       ├── [...path]/   the one route the browser talks to — proxies everything
│       └── auth/        login, logout, refresh — the only handlers that write cookies
├── components/
│   ├── ui/              shadcn on the Base UI base (30 components)
│   ├── ask/ checklist/ mock-data/ projects/ users/   feature components
│   ├── form/ feedback/ layout/                       shared shells
├── hooks/               React Query hooks
├── lib/                 api client, query keys, SSE parser, auth/session
└── middleware.ts        route protection + refresh on navigation
```

Each screen is a thin `page.tsx` (a Server Component) plus a `*-screen.tsx` client component.

### Next holds the session

No token is ever readable by a script on the page.

- **Two cookies, both httpOnly, both `Path=/`**: `askrepo_access` (the JWT) and `askrepo_session`
  (the backend's refresh cookie, stored verbatim). `Path=/` differs from the backend's `/auth`
  scope on purpose — middleware runs at `/projects` and is only sent cookies whose path matches.
- **`app/api/[...path]/route.ts` is the only route the browser calls.** It attaches the bearer,
  strips `set-cookie` from every backend response, and relays the body untouched.
- **Refresh happens in two places, and that split is structural.** A Server Component cannot set
  a cookie, so a token refreshed during render could never be persisted. Navigations refresh in
  `middleware.ts`; browser fetches and the answer stream refresh inside the proxy, on the `401`
  status line, *before any body is read* — which is what keeps it safe on the SSE route.
- **`API_URL` is server-only.** There are no `NEXT_PUBLIC_*` variables; re-adding the prefix
  would inline the value into the client bundle.

### Styling

Tailwind CSS 4, CSS-first `@theme` — there is no `tailwind.config.js` for tokens.

- **Never write a `dark:` colour utility.** The token already knows what dark means. `bg-card`,
  not `bg-white dark:bg-slate-900`.
- **Never use a palette utility.** `bg-zinc-50` names a colour, not a role, so it does not follow
  the theme. Use `bg-card`, `text-muted-foreground`, `border-border`.
- `frontend/app/globals.css` is the only file allowed to contain a raw hex colour.
- Composition uses **`render={<Component />}`, never `asChild`** — `asChild` does not exist on
  the Base UI base and fails silently.

Full reference: [`design.md`](design.md).

---

## Where does X go?

| I want to… | Do this |
| --- | --- |
| **Add a route to an existing resource** | Schema in `app/schemas/`, method on the service, thin route. Update `backend/README.md`'s route table |
| **Add a whole new resource** | Run `/scaffold-route` — it generates schema, model, migration, repository, service and router to the repo's conventions |
| **Add a setting** | `app/config.py`, `backend/.env.example`, **and** `docs/configuration.md` — all three in the same change |
| **Change a table** | Model, then `uv run alembic revision --autogenerate`, then **read** what it generated. See [`data.md`](data.md) |
| **Change how retrieval works** | `app/rag/retriever.py`. Both filters are mandatory — see [`rag.md`](rag.md) |
| **Change a prompt** | `app/rag/prompts.py`, then run `uv run pytest -m model`. No ordinary test can catch a bad prompt |
| **Add a graph node** | `app/rag/graph/nodes.py` + wire it in `build.py`. It must degrade, never block. Test it with the `run_node` harness |
| **Add a background job** | A topic trio in `app/queue/topics.py`, a handler, a consumer in `worker.py`, and a lease on the row |
| **Add a screen** | `page.tsx` + `*-screen.tsx`, a hook in `hooks/`, nav entry per [`design.md`](design.md) |
| **Add a UI component** | `npx shadcn@latest add <name>` into `components/ui/`. Do not hand-write one that shadcn ships |

---

## Conventions enforced by lint, not review

`backend/pyproject.toml` selects `ANN` (type-hint coverage), `T20` (bans `print()`), `LOG`/`G`
(logging correctness), `RUF`, plus `E`/`F`/`I`/`UP`/`B`. `# noqa` and `# type: ignore` need a
reason on the same line.

If you add a convention, wire it into the config in the same change — a rule lint can enforce
should be enforced there.

Run everything CI runs with `make check`: ruff, prettier, mypy, pytest, vitest.

---

## The rule files

`.claude/rules/` holds 13 rule files that encode conventions this page only summarises —
`router.md`, `persistence.md`, `response-api.md`, `rag.md`, `ingestion.md`, `design-system.md`,
`forms.md`, `navigation.md`, `frontend-bff.md`, and others. They are written for coding agents
but are the most precise statement of each convention, and worth reading before a change in the
area they cover.

Two apply to everything: `contradiction-halt.md` (if a request contradicts the PRD or a rule,
report it rather than working around it) and `documentation.md` (if your change makes a doc
wrong, fixing it is part of the same change).

---

## See also

- [`architecture.md`](architecture.md) — the processes and their lifecycles
- [`data.md`](data.md) — tables, leases, soft delete
- [`rag.md`](rag.md) · [`llm.md`](llm.md) · [`langgraph.md`](langgraph.md) — the AI path
- [`configuration.md`](configuration.md) — every setting
- [`../backend/README.md`](../backend/README.md) — the exhaustive route table
- [`../frontend/README.md`](../frontend/README.md) — frontend scripts and env

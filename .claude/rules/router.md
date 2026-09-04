---
paths:
  - "backend/app/api/routes/**/*.py"
---

# Router Rules

FastAPI's equivalent of a controller is an `APIRouter`. This rule is the port of the
controller conventions from the team's NestJS backend, adapted where the frameworks differ —
decorator-based Swagger metadata becomes function signatures and `response_model`; guards
become dependencies; `try`/`catch` per method becomes global exception handlers.

Read `response-api.md` alongside this — it owns status codes, `ApiModel`, and OpenAPI
declarations.

## One router per resource

```
app/api/routes/
├── index.py        # GET /
├── health.py       # GET /health, /health/live, /health/ready
├── auth.py         # POST /auth/login, /auth/refresh, …
├── users.py        # admin user provisioning
├── projects.py     # project ingestion + lifecycle
├── conversations.py # /conversations CRUD + the SSE answer endpoint
├── checklist_modules.py # /checklist-modules CRUD + generate + chat
├── checklist_items.py   # /checklist-items CRUD + export
└── checklist_change_sets.py # apply + discard change sets
```

Each module defines exactly one `router` and is mounted in `app/main.py`. A module with two
routers, or a router assembled across files, makes the route map unreadable.

## Router declaration

```python
router = APIRouter(prefix="/projects", tags=["Projects"])
```

- **`prefix`** is the flat, kebab-case plural resource name. No role prefix — access control
  lives in dependencies, never in the URL. `/projects`, not `/admin/projects`.
- **`tags`** is the entity name in Title Case, matching the resource: `Projects`,
  `Checklist Modules`, `Users`, `Auth`. One tag per router. Do not invent per-route tags.
- Register the router in `app/main.py` in the order routes should appear in `/docs`.

## Every route has a summary

```python
@router.get("", response_model=list[ProjectResponse], summary="List all projects")
```

The summary is what appears in `/docs` and in generated clients. Write it for someone reading
the API, not the code: "Re-clone and re-index a project", not "reindex handler".

## Routers are thin

A route handler does four things and nothing else: accept validated input, resolve
dependencies, call **one** service method, return a typed response.

```python
@router.post("", response_model=ProjectResponse, status_code=201, summary="Create a project")
async def create_project(
    payload: ProjectCreateRequest,
    service: Annotated[ProjectService, Depends(get_project_service)],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> ProjectResponse:
    return await service.create(payload, created_by=current_user.id)
```

No conditionals, no data reshaping, no database or Qdrant access, no `os.environ` reads, and
no more than one service call. If a handler needs an `if`, that branch belongs in the service.

Handlers are `async def`. The persistence layer is async (`.claude/rules/persistence.md`); a
sync handler would block the event loop or need a threadpool hop for every query.

## Access control lives in dependencies

Dependencies are this codebase's guards. Never inline an auth check in a handler body.

```python
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]  # any authenticated user
AdminUser   = Annotated[AuthenticatedUser, Depends(require_admin)]     # is_admin, else 403
```

`AuthenticatedUser` is a frozen dataclass, not the ORM `User`. `AuthContextMiddleware` resolves
identity in its own session, which closes before the handler runs — passing the ORM row would
hand every handler a detached instance. A service that needs to mutate the row loads it itself.

- Router-wide: `APIRouter(prefix="/users", tags=["Users"], dependencies=[Depends(require_admin)])`
  when every route shares the requirement.
- Per-route: declare the dependency in the signature when routes differ — reads open to all
  users, destructive operations gated. `/users` does exactly this: reads take `CurrentUser`,
  mutations take `AdminUser`.

### The forced-password-change gate is middleware, not a dependency

`AuthContextMiddleware` (`app/core/middleware.py`) returns `403 PASSWORD_CHANGE_REQUIRED` for a
user with `must_change_password` set, on every path outside `GATE_EXEMPT_PREFIXES`. A new route
is therefore gated without opting in, which is the point — there is no `require_password_changed`
dependency to forget. Adding a route group under a **new** prefix means deciding whether that
prefix belongs in `GATE_EXEMPT_PREFIXES`; the default answer is no.

### Destructive operations are gated, and the gate is not the route's job to invent

`docs/PRD.md` §4.1: delete and reindex require the caller to be `created_by` or an admin,
returning `403` otherwise. That check belongs in the service (or a shared dependency), not
copy-pasted into handlers, so it cannot drift between routes.

### Read scoping goes through the access resolver — never the handler

This is the rule with the longest consequence. Phase 1 shares all projects; phase 2 adds
per-project RBAC. `docs/PRD.md` §2 and §5.1 require that **read scoping happen in exactly one
function**, so phase 2 is a change to that function's body and nothing else.

```python
# WRONG — puts read scoping in a route. Phase 2 now has to find every one of these.
projects = [p for p in service.list_all() if p.created_by == current_user.id]

# CORRECT — the resolver decides; in phase 1 it returns everything
scope = access.resolve_project_scope(current_user)
projects = service.list(scope)
```

The resolver returns a `ProjectScope` — either `unrestricted` (phase 1) or a concrete set of
ids — rather than a nullable list. A `None` meaning "unrestricted" is fail-open: an empty set
must mean *no* access, not all of it.

A handler that filters projects on its own is a defect even when its output is currently
identical.

## The five canonical CRUD routes

A full CRUD router implements exactly these, in this order:

| Method | Path | Handler | Status |
| --- | --- | --- | --- |
| `GET` | `""` | `list_*` | 200 |
| `GET` | `"/{id}"` | `get_*` | 200 |
| `POST` | `""` | `create_*` | 201 |
| `PATCH` | `"/{id}"` | `update_*` | 200 |
| `DELETE` | `"/{id}"` | `delete_*` | 204 |

- `PATCH`, not `PUT` — updates are partial.
- `DELETE` returns `204` with no body. It soft-deletes the row and hard-deletes any Qdrant
  points in the same operation (`docs/PRD.md` §5.1).
- Custom actions (`POST /projects/{id}/reindex`) are named verbs after the resource. They get
  their **own** `responses` block traced from their own service method — never copied from the
  CRUD route beside them.

## List routes take a shared query dependency

Every list route accepts the same pagination and filtering shape through one dependency, so
the contract can't drift between resources:

```python
class ListQuery(ApiModel):
    page: int = 1
    limit: int = 25
    search: str | None = None
    sort: str | None = None
    sort_direction: Literal["asc", "desc"] = "desc"   # arrives as sortDirection
```

- Because it inherits `ApiModel`, query params are `camelCase` on the wire (`sortDirection`)
  while the code reads `sort_direction`.
- An unknown `sort` field raises `400` — a list route therefore always declares `400`.
- List responses return items plus pagination meta (`page`, `limit`, `totalCount`,
  `totalPages`). Never a bare array for a paginated resource.

## No `try`/`except` in a handler

Exception handlers are registered once in `app/main.py`. See `response-api.md`.

## Response messages

There is no i18n layer and no success-envelope in this codebase: routes return the resource
itself, and errors carry their message in the `HTTPException` detail. Do not introduce an
envelope or a translation call in a single router — that is an API-wide decision, and
introducing it in one place produces two response shapes.

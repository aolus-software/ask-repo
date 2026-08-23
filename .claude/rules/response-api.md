---
paths:
  - "backend/app/api/**/*.py"
  - "backend/app/schemas/**/*.py"
---

# Response & API Contract Rules

OpenAPI is a contract. An undeclared status code or an example that doesn't match the real
payload misleads every consumer of this API, including the frontend in this repo.

## Every schema inherits `ApiModel`

`app/schemas/base.py` defines `ApiModel`, which emits `camelCase` on the wire while the code
stays `snake_case`. **Every request and response model inherits it.**

```python
from app.schemas.base import ApiModel

class ProjectResponse(ApiModel):
    id: UUID
    last_indexed_commit: str | None   # serializes as lastIndexedCommit
```

A model on plain `BaseModel` silently ships `snake_case` keys and is a defect, not a style
preference. `backend/tests/test_api_model.py` is what keeps this honest — it exists because no
route shipped so far has a multi-word field, so nothing else would catch a regression.

Never hand-convert casing in a route or service. One translation point, no exceptions.

## Every route declares `response_model` and `status_code`

```python
@router.post("/projects", response_model=ProjectResponse, status_code=201)
def create_project(...) -> ProjectResponse: ...
```

- `201` for resource creation, `200` for everything else, `204` for a delete returning no body.
- `status_code` and the annotated return type must agree with what the function actually
  returns. A route annotated `-> ProjectResponse` that returns a dict is a bug even when the
  keys happen to line up.
- Never `response_model=dict` or an un-annotated return. A route whose shape isn't declared
  isn't documented.

## Exception → status mapping

| Raise | Status | When |
| --- | --- | --- |
| `RequestValidationError` (automatic) | `422` | Any malformed request body or query param. FastAPI raises it — never catch it |
| `HTTPException(400)` | `400` | Semantically invalid input that passed schema validation — an unsupported sort field, a malformed repo URL |
| `HTTPException(401)` | `401` | Missing, expired, or malformed access token |
| `HTTPException(403)` | `403` | Authenticated, may see the resource, **may not do this to it** |
| `HTTPException(404)` | `404` | Does not exist, **or the caller may not know it exists** |
| `HTTPException(409)` | `409` | Valid request, wrong state — querying a project that isn't `ready`, re-registering an existing email |
| `HTTPException(429)` | `429` | Rate or quota limit |
| Unhandled | `500` | A bug. Must be logged with `exc_info=True` and must not leak internals to the client |

### `403` vs `404` is a security decision, not a preference

This is the rule most easily got wrong, and `docs/PRD.md` §5.1 is the authority:

- **`403`** when existence is not a secret. Deleting a project you didn't create returns `403`
  — projects are deliberately shared instance-wide, so hiding the project's existence would
  only confuse.
- **`404`** when the caller should not learn the resource exists. Requesting another user's
  conversation returns `404`, never `403`, because `403` confirms it is there.

Getting this backwards either leaks existence or hides a resource the user can plainly see in
a list. When adding a route, decide which category it is before writing the handler.

## `422` is always possible on a route with a body

Any route taking a Pydantic body or typed query params can raise `RequestValidationError`.
Declare `422` in `responses` and never suppress it.

## `429` becomes universal once rate limiting lands

Login rate limiting arrives at M0 (`docs/PRD.md` §4.0) and the middleware applies broadly.
Once it does, `429` is declarable on every route it covers — a route that opts out must say so
explicitly rather than silently omitting the code.

## Declaring error responses in OpenAPI

Use `responses` on the route decorator, and declare **exactly** what the handler and its
dependencies can raise — traced, not guessed:

```python
@router.delete(
    "/projects/{project_id}",
    status_code=204,
    responses={
        403: {"description": "Not the project creator and not an admin"},
        404: {"description": "No such project"},
        429: {"description": "Rate limited"},
    },
)
```

Checklist when adding a route:

1. Which exceptions can the **service** raise? Map each one.
2. Does it depend on an auth dependency? → `401`, and `403` if the dependency checks a role.
3. Is it a destructive operation gated on `created_by`/`is_admin`? → always `403`.
4. Does it take a body or typed query params? → always `422`.
5. Can it 404 — including on a *parent* resource, not just the one in the path? → declare it.
6. Is it behind rate limiting? → `429`.

Do not copy the `responses` block from a sibling route. A custom action (`reindex`) raises a
different set than the `findOne` next to it.

## Response examples must match the real shape

If you add an example, it must reflect what the code actually returns — traced through
schema → service return type → query projection. A wrong example is worse than none.

- **No placeholder examples.** `{}` or an invented shape is a defect.
- **Examples are `camelCase`,** like the real payload. An example in `snake_case` documents a
  response the API does not produce.
- **List vs detail differ.** A list response shows the list shape plus its pagination meta; a
  detail response shows nested relations. Don't reuse one for the other.
- **A schema change ripples here.** When a response model's fields change, every example
  showing that model is updated in the **same change**.

## No `try`/`except` around a route body

Exception handling is registered once, globally, in `app/main.py`. A route does not catch
broadly to convert exceptions into responses:

```python
# WRONG — hides real errors, duplicates the global handler, returns an untyped body
@router.get("/projects/{project_id}")
def get_project(project_id: UUID):
    try:
        return service.get(project_id)
    except Exception as err:
        return {"error": str(err)}

# CORRECT — raise; the handler and FastAPI do the rest
@router.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(project_id: UUID) -> ProjectResponse:
    return service.get(project_id)
```

Catch narrowly and only to *translate* a specific known failure into the right status code —
never to blanket-convert everything.

## Never return an error body from a route

Raise. Returning `{"error": ...}` with a `200` makes every client check the body instead of
the status, and the error shape ends up undocumented.

## No secret in any response

Passwords, tokens, and PATs are never serialized — not even masked. A response model that
could carry one must not declare the field at all. `docs/PRD.md` §4.1: PATs are "never
returned in any API response — not even masked."

## Routers carry tags and summaries

Every router sets `tags`; every route sets a `summary`. See `router.md`.

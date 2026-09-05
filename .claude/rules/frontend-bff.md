---
paths:
  - "frontend/middleware.ts"
  - "frontend/app/api/**/*.ts"
  - "frontend/lib/auth/**/*.ts"
  - "frontend/lib/api/server.ts"
  - "frontend/lib/api/client.ts"
  - "frontend/lib/ask/sse.ts"
---

# Frontend Backend-for-Frontend Rules

`docs/PRD.md` §5 calls the frontend "minimal", and it has outgrown that deliberately —
`docs/superpowers/specs/2026-08-29-frontend-m0-m2-design.md` §2.1 records why. **Next holds the
session and calls the API on the browser's behalf**, so no access or refresh token is ever
readable by a script running on the page. Every invariant below fails **silently** when broken:
the app still renders, requests still mostly succeed, and the only symptom is a token leaking
somewhere it shouldn't, or a session that drops without an error anyone sees.

## Two cookies, both set by Next, both `httpOnly` and `Path=/`

`askrepo_access` (the JWT) and `askrepo_session` (the backend's own refresh cookie, stored as a
verbatim `name=value` pair because `REFRESH_COOKIE_NAME` is operator-configurable). Neither is
readable from client-side JavaScript.

The `Path=/` is deliberate and differs from the backend's own `/auth` cookie scope: `middleware.ts`
runs at `/projects` and every other app route, and is only sent cookies whose path matches. Scoping
either cookie to `/auth` here would make the middleware unable to read it on any other route —
not an error, just a silent, permanent "not authenticated."

## `app/api/[...path]/route.ts` is the one route the browser talks to

It attaches the bearer token, strips `set-cookie` from every backend response before relaying it,
and passes the body through untouched. **Only the three `/api/auth/*` handlers write cookies.**

A new proxy path, or a handler outside `/api/auth/*` that sets a cookie, creates a second place a
token can be written — which is exactly the surface this design exists to avoid. If a new browser
capability needs to reach the backend, it goes through this one route, not a new one.

## Refresh happens in two places, and that split is structural

A Server Component cannot set a cookie, so a token refreshed during render could never be
persisted — refreshing there would silently discard the new token every time.

- **Navigations** refresh in `middleware.ts`.
- **Browser fetches and the answer stream** refresh inside the proxy (`app/api/[...path]/route.ts`),
  on the `401` status line, **before any body is read**. Reading the body first is what would break
  this on the SSE route: an SSE body is a stream, not a value, and inspecting it before deciding to
  refresh would consume or block on data that never arrives.

Moving refresh logic into a Server Component, or moving the proxy's refresh check to after the
body starts streaming, are both regressions that look correct in every case except the one they
exist for.

## The answer stream is piped through the proxy unbuffered

`text/event-stream`, `Cache-Control: no-cache`, and `X-Accel-Buffering: no` must survive the
proxy hop unchanged. Buffering the response here — even accidentally, via a helper that reads a
`Response` fully before re-emitting it — turns a live token stream into a response that arrives
all at once after the model finishes, which defeats the entire streaming UI with no error and no
failing test outside the ones listed below.

## `API_URL` is server-only

It replaces `NEXT_PUBLIC_API_URL` and is read only by the proxy, `middleware.ts`, and
`serverFetch` — never by browser code. Under Compose it is the service name `http://backend:8000`,
the inverse of the old `NEXT_PUBLIC_*` rule, because the fetch now happens server-side. Reading it
from a Client Component, or re-adding a `NEXT_PUBLIC_*` variable that mirrors it, inlines it into
the client bundle and is a regression back to the thin-client model this design replaced.

## What actually tests these invariants

Vitest (run in `make test` alongside pytest) covers the pieces that fail silently: single-flight
refresh, the proxy's refresh-and-retry, and the answer stream's ordering contract, among others.
A change to any file this rule covers should have a reason to believe those suites still pass —
they are the only thing that would catch a regression here before a user does.

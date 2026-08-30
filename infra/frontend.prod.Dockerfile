# AskRepo frontend — production image (compiled Next.js server).
# Build context is ./frontend; see infra/frontend.Dockerfile for the development one.
#
#   docker build -f infra/frontend.prod.Dockerfile -t askrepo-frontend:prod ./frontend
#
# The development image runs `next dev` and compiles on demand. This one runs
# `next build` once, here, and serves the output with `next start`.
#
# Bun installs, Node builds and serves. That split is not a preference: `bun run
# build` segfaults running Next's compiler on linux/arm64 (Bun 1.3.14, both musl and
# glibc), so the image would build on an x86 CI box and crash on an ARM one. Bun
# still owns dependency resolution, because bun.lock is the lockfile in this repo
# and npm would resolve it afresh.

# ── Dependency stage ──────────────────────────────────────────────────────────
FROM oven/bun:1.3.14-debian AS deps

WORKDIR /app

COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

# Again, without the dev group this time — the runtime stage gets these. `next`,
# `react` and everything the server actually needs are runtime dependencies; the dev
# group is compilers, types, eslint and vitest, none of which `next start` loads.
# Installed separately rather than pruned afterwards, because `bun install` has no
# prune and deleting from a resolved tree by hand is how a runtime import goes
# missing on a Tuesday.
FROM oven/bun:1.3.14-debian AS prod-deps

WORKDIR /app

COPY package.json bun.lock ./
RUN bun install --frozen-lockfile --production

# ── Build stage ───────────────────────────────────────────────────────────────
FROM node:22-bookworm-slim AS build

ENV NEXT_TELEMETRY_DISABLED=1

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# No API_URL is needed here. Everything that talks to the API also reads cookies,
# which opts those routes into dynamic rendering; only /login, /change-password and
# /_not-found are prerendered, and none of them fetches anything. If this step ever
# starts failing on a connection error, a route that reads the session became
# static — fix the route rather than baking a URL in, because API_URL is resolved
# per request at runtime and a build-time value would be the wrong one.
#
# `.next/cache` is ~80 MB of incremental-build state that `next start` never reads.
# Dropped here rather than after the COPY, because deleting it in the runtime stage
# would add a layer without reclaiming the bytes in the one below.
RUN node node_modules/.bin/next build && rm -rf .next/cache

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM node:22-bookworm-slim

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

WORKDIR /app

# `next start` needs the build output, the config it was built with, package.json,
# and a node_modules — the runtime one, not the build one. The app does not set
# `output: "standalone"`, so there is no self-contained bundle to copy instead.
COPY --from=build --chown=node:node /app/.next ./.next
COPY --from=prod-deps --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/public ./public
COPY --from=build --chown=node:node /app/package.json /app/next.config.ts ./

# The base image ships this unprivileged user; nothing here needs root.
USER node

EXPOSE 3000

# /login is one of the prerendered routes, so this answers without the API being up
# — it reports that the Next server itself is serving, nothing more.
HEALTHCHECK --interval=10s --timeout=5s --retries=5 --start-period=15s \
    CMD ["node", "-e", "fetch('http://127.0.0.1:3000/login').then(r => process.exit(r.ok ? 0 : 1), () => process.exit(1))"]

# --hostname 0.0.0.0 so it is reachable from outside the container. Publish it to
# 127.0.0.1 on the host and put Caddy in front (docs/deployment.md §3).
CMD ["node", "node_modules/.bin/next", "start", "--hostname", "0.0.0.0"]

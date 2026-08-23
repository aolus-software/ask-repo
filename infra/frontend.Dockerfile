# AskRepo frontend — development image (Next.js dev server).
# Build context is ./frontend; see infra/docker-compose.yml.
FROM oven/bun:1.3.14-alpine

ENV NEXT_TELEMETRY_DISABLED=1

WORKDIR /app

# Dependencies first, so editing source doesn't invalidate the install layer.
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

COPY . .

EXPOSE 3000

# --hostname 0.0.0.0 so the dev server is reachable from outside the container.
CMD ["bun", "run", "next", "dev", "--hostname", "0.0.0.0"]

# AskRepo backend — development image (hot reload).
# Build context is ./backend; see infra/docker-compose.yml.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    # Keep the venv outside /app so the compose bind-mount can't shadow it.
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# git is a runtime dependency, not a build one: `app/ingestion/cloner.py` shells out
# to `git clone --depth 1` for every indexing run. The uv base is bookworm-slim and
# ships without it, so leaving this out lets the API start and the worker consume
# jobs, and then fails every clone with FileNotFoundError: 'git' — after the job has
# already been claimed.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, so editing source doesn't invalidate the install layer.
# `uv.lock*` is a glob: it is used when present and skipped when it isn't.
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-install-project

COPY . .

EXPOSE 8000

# Migrate, seed the bootstrap admins (idempotent), then serve. Shell form so the
# chain runs in order and a failed migration stops the container rather than
# serving against an empty schema.
CMD ["sh", "-c", "alembic upgrade head && python -m app.cli seed-admins && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"]

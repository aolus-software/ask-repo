# AskRepo backend — production image (API and worker).
# Build context is ./backend; see infra/backend.Dockerfile for the development one.
#
#   docker build -f infra/backend.prod.Dockerfile -t askrepo-backend:prod ./backend
#
# Three differences from the development image, each deliberate:
#   1. No --reload, and the source is baked in rather than bind-mounted.
#   2. No `alembic upgrade head` in CMD. Two replicas restarting together would race
#      on the same migration, and schema changes should not be coupled to serving —
#      run migrations as a deploy step (docs/deployment.md §5).
#   3. Runs as a non-root user. This image also runs the worker, which is the process
#      that clones user-supplied URLs from inside the network.

# ── Build stage ───────────────────────────────────────────────────────────────
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS build

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

# Dependencies only. `--no-dev` drops mypy, pytest and ruff — they are test-time
# tools, and shipping them enlarges the image and its attack surface for nothing.
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-install-project --no-dev

# ── Runtime stage ─────────────────────────────────────────────────────────────
# The same base the uv image is built on, so the venv's interpreter symlinks still
# resolve after the copy below. uv itself is a build tool and does not ship.
FROM python:3.13-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# git is a runtime dependency, not a build one: `app/ingestion/cloner.py` shells out
# to `git clone --depth 1` for every indexing run. Leaving it out lets the API start
# and the worker claim jobs, then fails every clone with FileNotFoundError: 'git' —
# after the job has already been claimed.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /opt/venv /opt/venv

# REPO_SCRATCH_DIR defaults to /data/repos and the worker writes there as this user.
# Created here rather than left to a volume mount, so a missing volume is a clone
# that fails loudly instead of a container that cannot start.
RUN useradd --create-home --uid 10001 askrepo \
    && mkdir -p /data/repos \
    && chown askrepo:askrepo /data/repos

WORKDIR /app
COPY --chown=askrepo:askrepo . .

USER askrepo

EXPOSE 8000

# Mirrors the compose healthcheck, so the image is self-describing when run without
# it. /health/live is process liveness only — it stays ok while a datastore is down.
HEALTHCHECK --interval=10s --timeout=5s --retries=5 --start-period=15s \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3).status == 200 else 1)"]

# The worker overrides this with ["python", "-m", "app.worker"] — same image, same
# settings, different entrypoint.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

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

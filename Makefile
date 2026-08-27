# AskRepo — task runner.
#
#   make help        list every target
#   make setup       install backend + frontend dependencies
#   make infra       start postgres, qdrant, redis and kafka only
#   make dev         run both dev servers (needs `make infra` first)
#   make check       lint + typecheck + test everything, as CI would
#
# Targets are grouped: setup, infra (datastores), dev, quality, docker, clean.

COMPOSE := docker compose -f infra/docker-compose.yml
BACKEND  := backend
FRONTEND := frontend

# Datastore services — the ones you run in Docker while developing the apps locally.
DATASTORES := postgres qdrant redis kafka

.DEFAULT_GOAL := help
.PHONY: help setup setup-backend setup-frontend \
        infra infra-stop infra-down infra-logs infra-status migrate seed \
        docker-start-pg docker-start-redis docker-start-qdrant docker-start-kafka \
        docker-stop-pg docker-stop-redis docker-stop-qdrant docker-stop-kafka \
        psql redis-cli \
        dev dev-backend dev-frontend \
        build build-frontend \
        lint lint-backend lint-frontend \
        format format-check format-backend format-frontend \
        test test-backend test-one test-watch \
        typecheck check \
        up down restart logs ps compose-config rebuild \
        clean clean-backend clean-frontend

## ─── Help ──────────────────────────────────────────────────────────────────

help: ## List available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

## ─── Setup ─────────────────────────────────────────────────────────────────

setup: setup-backend setup-frontend ## Install all dependencies

setup-backend: ## Create the backend venv and install dependencies
	cd $(BACKEND) && uv sync

setup-frontend: ## Install frontend dependencies
	cd $(FRONTEND) && bun install

## ─── Datastores ────────────────────────────────────────────────────────────

infra: ## Start postgres + qdrant + redis + kafka (detached), wait until healthy
	$(COMPOSE) up -d --wait $(DATASTORES)
	@echo "postgres :5432   qdrant :6333   redis :6379   kafka :9092"

infra-stop: ## Stop the datastores, keep their data
	$(COMPOSE) stop $(DATASTORES)

infra-down: ## Stop the datastores and DELETE their volumes
	$(COMPOSE) down -v

infra-status: ## Show datastore health
	$(COMPOSE) ps $(DATASTORES)

infra-logs: ## Tail datastore logs
	$(COMPOSE) logs -f $(DATASTORES)

migrate: ## Apply database migrations
	cd $(BACKEND) && uv run alembic upgrade head

seed: ## Create the bootstrap admin accounts (idempotent)
	cd $(BACKEND) && uv run python -m app.cli seed-admins

docker-start-pg: ## Start postgres only
	$(COMPOSE) up -d --wait postgres

docker-start-redis: ## Start redis only
	$(COMPOSE) up -d --wait redis

docker-start-qdrant: ## Start qdrant only
	$(COMPOSE) up -d --wait qdrant

docker-start-kafka: ## Start kafka only
	$(COMPOSE) up -d --wait kafka

docker-stop-pg: ## Stop postgres
	$(COMPOSE) stop postgres

docker-stop-redis: ## Stop redis
	$(COMPOSE) stop redis

docker-stop-qdrant: ## Stop qdrant
	$(COMPOSE) stop qdrant

docker-stop-kafka: ## Stop kafka
	$(COMPOSE) stop kafka

psql: ## Open a psql shell on the running postgres
	$(COMPOSE) exec postgres psql -U askrepo -d askrepo

redis-cli: ## Open a redis-cli shell on the running redis
	$(COMPOSE) exec redis redis-cli

## ─── Dev servers ───────────────────────────────────────────────────────────

dev: ## Run backend + frontend dev servers together (Ctrl-C stops both)
	@echo "backend :8000 (docs at /docs)   frontend :3000"
	@trap 'kill 0' INT TERM; \
		( cd $(BACKEND) && uv run uvicorn app.main:app --reload --port 8000 ) & \
		( cd $(FRONTEND) && bun dev ) & \
		wait

dev-backend: ## Run the backend dev server only
	cd $(BACKEND) && uv run uvicorn app.main:app --reload --port 8000

dev-frontend: ## Run the frontend dev server only
	cd $(FRONTEND) && bun dev

## ─── Quality ───────────────────────────────────────────────────────────────

check: lint format-check typecheck test ## Everything CI would run

lint: lint-backend lint-frontend ## Lint both apps

lint-backend: ## ruff check
	cd $(BACKEND) && uv run ruff check .

lint-frontend: ## eslint
	cd $(FRONTEND) && bun lint

format: format-backend format-frontend ## Format both apps in place

format-backend: ## ruff format
	cd $(BACKEND) && uv run ruff format .

format-frontend: ## prettier
	cd $(FRONTEND) && bunx prettier --write .

format-check: ## Fail if anything is unformatted
	cd $(BACKEND) && uv run ruff format --check .
	cd $(FRONTEND) && bunx prettier --check .

typecheck: ## Static types, both apps
	cd $(BACKEND) && uv run mypy .
	cd $(FRONTEND) && bunx tsc --noEmit

test: test-backend ## Run the test suites

test-backend: ## pytest
	cd $(BACKEND) && uv run pytest

# Usage: make test-one T=tests/test_api_model.py  |  make test-one T=-k\ camel_case
test-one: ## Run one test file or -k expression (T=...)
	cd $(BACKEND) && uv run pytest $(T)

test-watch: ## Re-run backend tests on change
	cd $(BACKEND) && uv run pytest -f 2>/dev/null || \
		echo "pytest-watch not installed: uv add --dev pytest-watcher, then use 'ptw'"

build: build-frontend ## Production build

build-frontend: ## next build
	cd $(FRONTEND) && bun run build

## ─── Full stack in Docker ──────────────────────────────────────────────────

up: ## Start the whole stack in Docker (apps included)
	$(COMPOSE) up --build

down: ## Stop the whole stack, keep volumes
	$(COMPOSE) down

restart: down up ## Recreate the whole stack

rebuild: ## Rebuild images without cache
	$(COMPOSE) build --no-cache

logs: ## Tail all service logs
	$(COMPOSE) logs -f

ps: ## Show all services
	$(COMPOSE) ps

compose-config: ## Validate docker-compose.yml
	$(COMPOSE) config --quiet && echo "compose config valid"

## ─── Clean ─────────────────────────────────────────────────────────────────

clean: clean-backend clean-frontend ## Remove caches and build output

clean-backend: ## Remove Python caches
	find $(BACKEND) -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf $(BACKEND)/.pytest_cache $(BACKEND)/.ruff_cache

clean-frontend: ## Remove Next.js build output
	rm -rf $(FRONTEND)/.next $(FRONTEND)/out

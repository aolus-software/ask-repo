# AskRepo — task runner.
#
#   make help        list every target
#   make setup       install backend + frontend dependencies
#   make infra       start postgres, qdrant, redis and kafka only
#   make dev         run both dev servers (needs `make infra` first)
#   make check       lint + typecheck + test everything, as CI would
#
# Targets are grouped: setup, infra (datastores), dev, quality, docker, prod, clean.
#
# Bare target names are the development stack. Production targets carry a `-prod`
# suffix, use infra/docker-compose.prod.yml, and are documented in
# docs/deployment.md. Start with `make setup-prod`, which checks a box is ready.

# The ollama profile is on by default: the shipped EMBEDDING_PROVIDER is `ollama`,
# so a stack without it has a default pointing at nothing. An instance on a hosted
# embedding provider can override this to a bare `docker compose`.
COMPOSE := docker compose -f infra/docker-compose.yml --profile ollama

# The production stack is a STANDALONE file, never layered onto the development one:
# Compose merges `volumes` by target path rather than replacing the list, so
# `-f … -f …` would keep the dev bind-mounts of the working copy over /app.
COMPOSE_PROD := docker compose -f infra/docker-compose.prod.yml --profile ollama

BACKEND  := backend
FRONTEND := frontend

# Datastore services — the ones you run in Docker while developing the apps locally.
DATASTORES := postgres qdrant redis kafka ollama

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
        test test-backend test-frontend test-one test-watch \
        typecheck check \
        up down restart logs ps compose-config rebuild \
        setup-prod build-prod rebuild-prod compose-config-prod \
        up-prod down-prod restart-prod logs-prod ps-prod \
        migrate-prod seed-prod psql-prod pull-models-prod backup-prod \
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

infra: ## Start postgres + qdrant + redis + kafka + ollama (detached), wait until healthy
	$(COMPOSE) up -d --wait $(DATASTORES)
	@echo "postgres :5432   qdrant :6333   redis :6379   kafka :9092   ollama :11434"

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

test: test-backend test-frontend ## Run the test suites

test-backend: ## pytest
	cd $(BACKEND) && uv run pytest

test-frontend: ## vitest
	cd $(FRONTEND) && bun run test

# Usage: make test-one T=tests/test_api_model.py  |  make test-one T=-k\ camel_case
test-one: ## Run one test file or -k expression (T=...)
	cd $(BACKEND) && uv run pytest $(T)

test-watch: ## Re-run backend tests on change
	cd $(BACKEND) && uv run pytest -f 2>/dev/null || \
		echo "pytest-watch not installed: uv add --dev pytest-watcher, then use 'ptw'"

test-integration:  ## Run integration tests (needs `make infra`)
	cd backend && uv run pytest -m integration -v

test-model:  ## Run prompt tests against a real chat model (needs one served)
	cd backend && uv run pytest -m model -v

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

## ─── Production ────────────────────────────────────────────────────────────
#
# Full procedure: docs/deployment.md. Order on a fresh box:
#   make setup-prod && make build-prod && make migrate-prod && make seed-prod && make up-prod
#
# There is deliberately no `down -v` equivalent here. Deleting production volumes
# should not be one typo away from a target you run every day.

setup-prod: ## Check this box is ready to deploy (reads infra/.env, changes nothing)
	@ok=1; \
	pass() { printf '  \033[32m✓\033[0m %s\n' "$$1"; }; \
	fail() { printf '  \033[31m✗\033[0m %s\n' "$$1"; ok=0; }; \
	printf '\n  Preflight — production\n\n'; \
	if docker compose version >/dev/null 2>&1; then pass "docker + compose v2 present"; \
	else fail "docker compose v2 not found"; fi; \
	if [ -f infra/.env ]; then pass "infra/.env exists"; \
	else fail "infra/.env missing — cp infra/.env.example infra/.env"; fi; \
	set -a; [ -f infra/.env ] && . ./infra/.env; set +a; \
	if [ -n "$$SECRET_KEY" ] && [ "$$SECRET_KEY" != dev-insecure-change-me ]; then pass "SECRET_KEY set"; \
	else fail "SECRET_KEY unset or placeholder — openssl rand -hex 32"; fi; \
	if [ -n "$$PAT_ENCRYPTION_KEY" ] && [ "$$PAT_ENCRYPTION_KEY" != dev-insecure-change-me ]; then pass "PAT_ENCRYPTION_KEY set"; \
	else fail "PAT_ENCRYPTION_KEY unset or placeholder — python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"; fi; \
	if [ -n "$$POSTGRES_PASSWORD" ] && [ "$$POSTGRES_PASSWORD" != askrepo ]; then pass "POSTGRES_PASSWORD set"; \
	else fail "POSTGRES_PASSWORD unset or still the default 'askrepo'"; fi; \
	if [ -n "$$BOOTSTRAP_ADMIN_PASSWORD" ]; then pass "BOOTSTRAP_ADMIN_PASSWORD set"; \
	else fail "BOOTSTRAP_ADMIN_PASSWORD unset — seeding refuses to run without it"; fi; \
	case "$$PUBLIC_ORIGIN" in \
	  https://*) pass "PUBLIC_ORIGIN is https" ;; \
	  "") fail "PUBLIC_ORIGIN unset — e.g. https://askrepo.internal.example.com" ;; \
	  *) fail "PUBLIC_ORIGIN must be https: the refresh cookie is Secure and will not be sent over http" ;; \
	esac; \
	if [ -n "$$TRUSTED_PROXY_HOPS" ] && [ "$$TRUSTED_PROXY_HOPS" != 0 ]; then pass "TRUSTED_PROXY_HOPS=$$TRUSTED_PROXY_HOPS"; \
	else fail "TRUSTED_PROXY_HOPS is 0 or unset — set it to the number of proxies in front of the API (1 with Caddy)"; fi; \
	printf '\n'; \
	if [ $$ok -eq 1 ]; then printf '  ready — next: make build-prod\n\n'; \
	else printf '  not ready. See docs/deployment.md\n\n'; exit 1; fi

build-prod: ## Build both production images
	$(COMPOSE_PROD) build

rebuild-prod: ## Rebuild the production images without cache
	$(COMPOSE_PROD) build --no-cache

compose-config-prod: ## Validate docker-compose.prod.yml
	$(COMPOSE_PROD) config --quiet && echo "prod compose config valid"

migrate-prod: ## Apply migrations (a deploy step, not a container start command)
	$(COMPOSE_PROD) run --rm backend alembic upgrade head

seed-prod: ## Create the bootstrap admins (idempotent)
	$(COMPOSE_PROD) run --rm backend python -m app.cli seed-admins

up-prod: ## Start the production stack (detached), wait until healthy
	$(COMPOSE_PROD) up -d --wait
	@echo "frontend 127.0.0.1:3000   api 127.0.0.1:8000   — put Caddy in front, see docs/deployment.md"

down-prod: ## Stop the production stack, keep volumes
	$(COMPOSE_PROD) down

restart-prod: down-prod up-prod ## Recreate the production stack

logs-prod: ## Tail production logs
	$(COMPOSE_PROD) logs -f

ps-prod: ## Show production services
	$(COMPOSE_PROD) ps

psql-prod: ## Postgres shell, without publishing 5432
	@set -a; [ -f infra/.env ] && . ./infra/.env; set +a; \
	$(COMPOSE_PROD) exec postgres psql -U $${POSTGRES_USER:-askrepo} -d $${POSTGRES_DB:-askrepo}

pull-models-prod: ## Pre-pull the Ollama models, so the first question doesn't wait on a download
	@set -a; [ -f infra/.env ] && . ./infra/.env; set +a; \
	$(COMPOSE_PROD) exec ollama ollama pull $${EMBEDDING_MODEL:-nomic-embed-text}; \
	$(COMPOSE_PROD) exec ollama ollama pull $${CHAT_MODEL:-qwen2.5-coder:14b}

backup-prod: ## Dump Postgres to backups/askrepo-<timestamp>.sql.gz
	@mkdir -p backups
	@set -a; [ -f infra/.env ] && . ./infra/.env; set +a; \
	f=backups/askrepo-$$(date +%Y%m%d-%H%M%S).sql.gz; \
	$(COMPOSE_PROD) exec -T postgres pg_dump -U $${POSTGRES_USER:-askrepo} $${POSTGRES_DB:-askrepo} | gzip > $$f; \
	echo "wrote $$f"; \
	echo "PAT_ENCRYPTION_KEY is NOT in this file and must be backed up separately — a backup holding both is plaintext storage with extra steps"

## ─── Clean ─────────────────────────────────────────────────────────────────

clean: clean-backend clean-frontend ## Remove caches and build output

clean-backend: ## Remove Python caches
	find $(BACKEND) -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf $(BACKEND)/.pytest_cache $(BACKEND)/.ruff_cache

clean-frontend: ## Remove Next.js build output
	rm -rf $(FRONTEND)/.next $(FRONTEND)/out

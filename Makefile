# AskRepo — task runner.
#
#   make help        list every target
#   make setup       install backend + frontend dependencies
#   make infra       start postgres, qdrant, redis and kafka only
#   make dev         run both dev servers (needs `make infra` and a host `ollama serve`)
#   make check       lint + typecheck + test everything, as CI would
#
# Targets are grouped: setup, infra (datastores), dev, quality, docker, prod, clean.
#
# Bare target names are the development stack. Production targets carry a `-prod`
# suffix, use infra/docker-compose.prod.yml, and are documented in
# docs/deployment.md. Start with `make setup-prod`, which checks a box is ready.

# Ollama runs on the HOST, not in a container, and that is a performance decision
# rather than a preference. Docker Desktop hands a container no GPU on macOS and
# caps it at the VM's memory allowance, so a model inside one runs on CPU inside a
# slice of RAM. The same model under a host `ollama serve` gets Metal and the whole
# machine. `make infra` therefore starts four datastores and leaves the model server
# to you: `ollama serve` (or the menu-bar app), then `make pull-models`.
#
# The containerised ollama is still in the compose file, behind its profile, for a
# box where that is the right answer. Opt back in with any non-empty value:
#   make infra OLLAMA_IN_DOCKER=1
OLLAMA_PROFILE := $(if $(OLLAMA_IN_DOCKER),--profile ollama,)
COMPOSE := docker compose -f infra/docker-compose.yml $(OLLAMA_PROFILE)

# The production stack is a STANDALONE file, never layered onto the development one:
# Compose merges `volumes` by target path rather than replacing the list, so
# `-f … -f …` would keep the dev bind-mounts of the working copy over /app.
COMPOSE_PROD := docker compose -f infra/docker-compose.prod.yml --profile ollama

BACKEND  := backend
FRONTEND := frontend

# Datastore services — the ones you run in Docker while developing the apps locally.
# Ollama is not among them: it runs on the host. See OLLAMA_PROFILE above.
DATASTORES := postgres qdrant redis kafka $(if $(OLLAMA_IN_DOCKER),ollama,)

# Where the host model server is expected to answer. Only the preflight check reads
# this — the apps get their endpoint from EMBEDDING_BASE_URL / CHAT_BASE_URL.
OLLAMA_URL ?= http://localhost:11434

.DEFAULT_GOAL := help
.PHONY: help setup setup-backend setup-frontend \
        infra infra-stop infra-down infra-reset infra-logs infra-status migrate seed \
        docker-start-pg docker-start-redis docker-start-qdrant docker-start-kafka \
        docker-stop-pg docker-stop-redis docker-stop-qdrant docker-stop-kafka \
        psql redis-cli \
        ollama-check pull-models \
        dev dev-backend dev-frontend worker \
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

infra: ## Start postgres + qdrant + redis + kafka (detached), wait until healthy
	$(COMPOSE) up -d --wait $(DATASTORES)
	@echo "postgres :5432   qdrant :6333   redis :6379   kafka :9092"
	@$(MAKE) --no-print-directory ollama-check

infra-stop: ## Stop the datastores, keep their data
	$(COMPOSE) stop $(DATASTORES)

infra-down: ## Stop and remove the datastore containers, keep their data
	$(COMPOSE) down

# Separated from `infra-down` on the same principle the production section states:
# deleting volumes should not be one typo away from a target you run every day. The
# prompt is the guard -- a non-tty `read` returns empty, so a scripted or piped
# invocation aborts rather than wiping a volume nobody was watching.
infra-reset: ## DESTRUCTIVE — delete every volume in the project (asks first)
	@printf '\n  \033[31mThis deletes every volume in the project.\033[0m\n'
	@printf '  Postgres rows, the Qdrant index, Redis and Kafka all go. Coming back\n'
	@printf '  costs `make migrate && make seed` plus a re-index of every project.\n'
	@printf '  Your Ollama models are safe: they live on the host, not in a volume.\n\n'
	@printf '  Type "delete" to confirm: '; read -r reply; \
		[ "$$reply" = delete ] || { printf '  aborted — nothing was deleted\n\n'; exit 1; }; \
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

## ─── Models (on the host, not in Docker) ───────────────────────────────────

# A warning, never a failure. An instance configured for a hosted embedding or chat
# provider has no host Ollama and is entirely correct; failing here would block it.
# The warning exists because the alternative is silent: the worker dies at startup
# probing embedding dimensions, restart-loops, and says so in a log stream that is
# interleaved with two others and scrolling.
ollama-check: ## Warn (don't fail) if the host Ollama is not answering
	@curl -fsS -m 2 $(OLLAMA_URL)/api/version >/dev/null 2>&1 && \
		printf '  ollama  %s  ok\n' '$(OLLAMA_URL)' || { \
		printf '\n  \033[33mNo Ollama answering at %s.\033[0m\n' '$(OLLAMA_URL)'; \
		printf '  It runs on the host now, not in Docker. Start it with `ollama serve`\n'; \
		printf '  (or the menu-bar app), then `make pull-models`. Ignore this if you\n'; \
		printf '  set EMBEDDING_PROVIDER / CHAT_PROVIDER to a hosted API.\n\n'; }

# The host equivalent of pull-models-prod. Reads backend/.env so it pulls the models
# this checkout is actually configured for, not the defaults.
pull-models: ## Pull the configured embedding + chat models into the host Ollama
	@set -a; [ -f $(BACKEND)/.env ] && . ./$(BACKEND)/.env; set +a; \
	ollama pull $${EMBEDDING_MODEL:-nomic-embed-text}; \
	ollama pull $${CHAT_MODEL:-qwen2.5-coder:14b}

## ─── Dev servers ───────────────────────────────────────────────────────────

# The worker runs here too, and it is not option∆al for a working instance: the API only
# *enqueues* indexing and checklist generation. Without it a new project sits at
# `pending` and a generated checklist never arrives, with nothing on screen saying why.
dev: ollama-check ## Run backend + frontend dev servers and the worker together (Ctrl-C stops all)
	@echo "backend :8000 (docs at /docs)   frontend :3000   worker: ingest + checklist"
	@trap 'kill 0' INT TERM; \
		( cd $(BACKEND) && uv run uvicorn app.main:app --reload --port 8000 ) & \
		( cd $(BACKEND) && uv run python -m app.worker ) & \
		( cd $(FRONTEND) && bun dev ) & \
		wait

dev-backend: ## Run the backend dev server only
	cd $(BACKEND) && uv run uvicorn app.main:app --reload --port 8000

dev-frontend: ## Run the frontend dev server only
	cd $(FRONTEND) && bun dev

# No --reload: the worker holds Kafka group memberships and a database lease, and a
# reload mid-job drops both, leaving the row to be recovered by the stranded sweep.
worker: ollama-check ## Run the ingestion + checklist worker only
	cd $(BACKEND) && uv run python -m app.worker

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

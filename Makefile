# ==============================================================================
# PayPilot -- root Makefile
# ==============================================================================
.DEFAULT_GOAL := help
SHELL := /bin/sh

BACKEND  := backend
FRONTEND := frontend
PY       ?= python
COMPOSE  ?= docker compose

# Override when a port is taken:  make backend PORT=8010
PORT     ?= 8000
HOST     ?= 0.0.0.0
WEB_PORT ?= 3000

# Prefer the project venv if one exists (posix and windows layouts).
VENV_PY_POSIX := $(BACKEND)/.venv/bin/python
VENV_PY_WIN   := $(BACKEND)/.venv/Scripts/python.exe
ifneq ("$(wildcard $(VENV_PY_POSIX))","")
  PYBIN := ../$(VENV_PY_POSIX)
else ifneq ("$(wildcard $(VENV_PY_WIN))","")
  PYBIN := ../$(VENV_PY_WIN)
else
  PYBIN := $(PY)
endif

## ------------------------------------------------------------------ help
help: ## Show this help
	@echo ""
	@echo "  PayPilot"
	@echo "  --------"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'
	@echo ""

## ------------------------------------------------------------------ setup
setup: env install db wait-db migrate seed ## One-shot: env -> deps -> database -> migrations -> seed
	@echo ""
	@echo "  Setup complete.  Run 'make dev' and open http://localhost:$(WEB_PORT)"
	@echo "  Demo login: owner@sharmacafe.in / Autopilot@2024"
	@echo ""

env: ## Create the single root .env from the example if it is missing
	@if [ ! -f .env ]; then cp .env.example .env; echo "created .env"; fi
	@echo "environment ready - one .env at the repo root, read by backend and frontend"

install: install-backend install-frontend ## Install backend + frontend dependencies

install-backend: ## Create the venv and install python dependencies
	cd $(BACKEND) && $(PY) -m venv .venv || true
	cd $(BACKEND) && $(PYBIN) -m pip install --upgrade pip
	cd $(BACKEND) && $(PYBIN) -m pip install -r requirements.txt
	-cd $(BACKEND) && $(PYBIN) -m pip install -r requirements-optional.txt

install-frontend: ## Install node dependencies
	cd $(FRONTEND) && npm install

## ------------------------------------------------------------------ run
dev: ## Run backend + frontend together
	$(MAKE) -j2 backend frontend

backend: ## Run the FastAPI backend (override with PORT=8010)
	cd $(BACKEND) && $(PYBIN) -m uvicorn app.main:app --reload --host $(HOST) --port $(PORT)

frontend: ## Run the Next.js frontend (override with WEB_PORT=3001)
	cd $(FRONTEND) && npm run dev -- -p $(WEB_PORT)

## ------------------------------------------------------------------ database
db: ## Start the local Postgres+pgvector container
	$(COMPOSE) up -d postgres

wait-db: ## Block until Postgres accepts connections
	@echo "waiting for postgres..."
	@$(COMPOSE) exec -T postgres sh -c 'for i in $$(seq 1 60); do pg_isready -U autopilot -d autopilot >/dev/null 2>&1 && exit 0; sleep 1; done; exit 1'
	@echo "postgres ready"

db-down: ## Stop the local Postgres container
	$(COMPOSE) stop postgres

db-reset: ## Destroy and recreate the local database volume
	$(COMPOSE) down -v postgres || true
	$(COMPOSE) up -d postgres
	$(MAKE) wait-db

migrate: ## Apply all Alembic migrations
	cd $(BACKEND) && $(PYBIN) -m alembic upgrade head

migration: ## Autogenerate a migration:  make migration MSG="add x"
	cd $(BACKEND) && $(PYBIN) -m alembic revision --autogenerate -m "$(MSG)"

downgrade: ## Roll back one migration
	cd $(BACKEND) && $(PYBIN) -m alembic downgrade -1

## ------------------------------------------------------------------ data
seed: ## Seed the deterministic Sharma Cafe demo dataset (idempotent)
	cd $(BACKEND) && $(PYBIN) -m app.seed.seed

reseed: ## Wipe and re-seed the demo tenant
	cd $(BACKEND) && $(PYBIN) -m app.seed.seed --reset

seed-stats: ## Print current row counts
	cd $(BACKEND) && $(PYBIN) -m app.seed.seed --stats

calibrate: ## Verify the seeded business story without a database
	cd $(BACKEND) && $(PYBIN) -m app.seed.calibrate

demo: db wait-db migrate reseed ## Rebuild a pristine demo environment
	@echo "demo environment ready -> make dev"

## ------------------------------------------------------------------ quality
test: test-backend ## Run all tests

test-backend: ## Run the backend suite (SQLite - no Docker needed)
	cd $(BACKEND) && $(PYBIN) -m pytest

test-frontend: ## Typecheck the frontend
	cd $(FRONTEND) && npm run typecheck

lint: ## Lint backend + frontend
	cd $(BACKEND) && $(PYBIN) -m ruff check app tests
	cd $(FRONTEND) && npm run lint

format: ## Format backend + frontend
	cd $(BACKEND) && $(PYBIN) -m ruff format app tests && $(PYBIN) -m ruff check --fix app tests
	cd $(FRONTEND) && npm run format

typecheck: ## Typecheck backend + frontend
	-cd $(BACKEND) && $(PYBIN) -m mypy app
	cd $(FRONTEND) && npm run typecheck

check: lint test test-frontend ## Everything CI would run

## ------------------------------------------------------------------ docker
docker-up: ## Start the whole stack in docker
	$(COMPOSE) --profile full up -d --build

docker-down: ## Stop the docker stack
	$(COMPOSE) --profile full down

logs: ## Tail docker logs
	$(COMPOSE) logs -f --tail=120

## ------------------------------------------------------------------ n8n
n8n-build: ## Render the n8n workflows from .env into n8n/deploy
	python n8n/build_workflows.py

n8n-import: ## Build, import and activate the workflows in the n8n container
	bash n8n/import.sh

n8n-check: ## Confirm the inventory webhook is live and refusing unsigned events
	@code=$$(curl -s -o /dev/null -w '%{http_code}' -X POST 	  http://localhost:5678/webhook/pga-inventory-event 	  -H 'Content-Type: application/json' -H 'X-Signature: sha256=bad' -d '{}'); 	if [ "$$code" = "401" ]; then 	  echo "n8n inventory webhook is live and rejecting unsigned events"; 	elif [ "$$code" = "404" ]; then 	  echo "webhook is not registered - run 'make n8n-import'"; exit 1; 	else 	  echo "unexpected status $$code - check 'docker logs n8n'"; exit 1; 	fi

## ------------------------------------------------------------------ misc
clean: ## Remove build artifacts and caches
	-rm -rf $(FRONTEND)/.next $(FRONTEND)/out $(FRONTEND)/.turbo
	-find $(BACKEND) -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	-rm -rf $(BACKEND)/.pytest_cache $(BACKEND)/.ruff_cache $(BACKEND)/.mypy_cache
	-rm -rf $(BACKEND)/logs
	@echo "cleaned"

.PHONY: help setup env install install-backend install-frontend dev backend frontend \
        db wait-db db-down db-reset migrate migration downgrade \
        seed reseed seed-stats calibrate demo \
        test test-backend test-frontend lint format typecheck check \
        docker-up docker-down logs clean         n8n-build n8n-import n8n-check

# ==============================================================================
# PayPilot -- root Makefile
#
# Every target delegates to scripts/tasks.py (standard-library Python), so the
# same commands work from GNU Make on macOS/Linux, Git Bash, WSL and Windows -
# and scripts/*.ps1 call exactly the same tasks.
#
#   First time:   make init
#   Then:         make dev
# ==============================================================================
.DEFAULT_GOAL := help

ifeq ($(OS),Windows_NT)
  PY ?= python
else
  PY ?= python3
endif

TASKS    := $(PY) scripts/tasks.py
PORT     ?= 8000
WEB_PORT ?= 3000

## ------------------------------------------------------------------ help
help: ## List every target
	@$(TASKS) help
	@echo "  Make-only extras: calibrate, seed-reset, demo, n8n-build, n8n-import, verify"
	@echo ""

## ------------------------------------------------------------------ setup
init: ## First-time setup: tools, .env, deps, database, migrations, seed
	@$(TASKS) init

setup: ## Install and prepare dependencies (+ database when Docker is running)
	@$(TASKS) env
	@$(TASKS) install

install: ## Install backend + frontend dependencies
	@$(TASKS) install

check: ## Check tools, versions and .env configuration
	@$(TASKS) check

integrations: ## Verify Channel3 + PayPal sandbox credentials against the live APIs
	@$(TASKS) integrations

env: ## Create .env from .env.example (never overwrites an existing .env)
	@$(TASKS) env

## ------------------------------------------------------------------ run
dev: ## Start database + backend (:8000) + frontend (:3000)
	@$(TASKS) dev --port $(PORT) --web-port $(WEB_PORT)

dev-backend: ## Start only the FastAPI backend   (PORT=8010 to override)
	@$(TASKS) dev-backend --port $(PORT)

dev-frontend: ## Start only the Next.js frontend (WEB_PORT=3001 to override)
	@$(TASKS) dev-frontend --web-port $(WEB_PORT)

backend: dev-backend
frontend: dev-frontend

## ------------------------------------------------------------------ docker
docker-up: ## Start Postgres + pgvector (FULL=1 for the whole stack)
	@$(TASKS) docker-up $(if $(FULL),--full,)

docker-down: ## Stop containers without deleting data
	@$(TASKS) docker-down

docker-logs: ## Tail container logs
	@$(TASKS) docker-logs

db: docker-up

## ------------------------------------------------------------------ database
migrate: ## Apply Alembic migrations
	@$(TASKS) migrate

migration: ## Autogenerate a migration:  make migration MSG="add x"
	@$(TASKS) migration --message "$(MSG)"

seed: ## Load the deterministic demo dataset (idempotent)
	@$(TASKS) seed

seed-reset: ## Rebuild the demo tenant's data (keeps the database)
	@$(TASKS) seed --reset

reset-db: ## DESTRUCTIVE: rebuild the local database   (make reset-db CONFIRM=yes)
	@$(TASKS) reset-db

calibrate: ## Print the seeded growth story's numbers without a database
	@cd backend && $(if $(wildcard backend/.venv/Scripts/python.exe),.venv/Scripts/python.exe,.venv/bin/python) -m app.seed.calibrate

demo: docker-up migrate seed-reset ## Rebuild a pristine demo environment

## ------------------------------------------------------------------ quality
test: ## Backend pytest + frontend vitest
	@$(TASKS) test

test-backend: ## Backend tests (SQLite - no Docker needed)
	@$(TASKS) test-backend

test-frontend: ## Frontend unit tests (vitest)
	@$(TASKS) test-frontend

lint: ## ruff + next lint
	@$(TASKS) lint

format: ## ruff format + prettier
	@$(TASKS) format

typecheck: ## tsc --noEmit (+ advisory mypy)
	@$(TASKS) typecheck

build: ## Production builds: backend import check + next build
	@$(TASKS) build

verify: lint typecheck test ## Everything CI runs

clean: ## Remove caches and build artifacts (never .env, deps, data or logs)
	@$(TASKS) clean

## ------------------------------------------------------------------ n8n
n8n-build: ## Render the n8n workflows from .env into n8n/deploy
	@$(PY) n8n/build_workflows.py

n8n-import: ## Build, import and activate the workflows in the n8n container
	bash n8n/import.sh

.PHONY: help init setup install check integrations env dev dev-backend dev-frontend backend frontend \
        docker-up docker-down docker-logs db migrate migration seed seed-reset reset-db \
        calibrate demo test test-backend test-frontend lint format typecheck build verify clean \
        n8n-build n8n-import

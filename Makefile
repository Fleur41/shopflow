# Developer shortcuts. Everything runs inside Docker, so only Docker is required.
.DEFAULT_GOAL := help
COMPOSE := docker compose
BACKEND := $(COMPOSE) run --rm backend
# Schema changes run as the database owner, not the app's restricted role.
BACKEND_OWNER := $(COMPOSE) run --rm backend env DATABASE_URL=postgres://shopflow:shopflow@db:5432/shopflow
FRONTEND := $(COMPOSE) run --rm --no-deps frontend

.PHONY: help up down logs ps migrate makemigrations superuser shell db-roles \
        test test-backend test-frontend lint lint-backend lint-frontend fmt check clean

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

up: ## Build and start the full stack (web on :3000, API on :8000)
	$(COMPOSE) up --build -d
	@echo "Web: http://localhost:3000   API: http://localhost:8000/api/v1/docs/"

down: ## Stop the stack (data volumes are kept)
	$(COMPOSE) down

logs: ## Follow logs from all services
	$(COMPOSE) logs -f

ps: ## Show running services
	$(COMPOSE) ps

migrate: ## Apply database migrations (as the schema owner)
	$(BACKEND_OWNER) python manage.py migrate

makemigrations: ## Create migrations after model changes
	$(BACKEND_OWNER) python manage.py makemigrations

db-roles: ## Create the app's restricted database role on an existing local volume
	$(COMPOSE) exec db sh /docker-entrypoint-initdb.d/01-app-role.sh
	$(BACKEND_OWNER) python manage.py migrate

superuser: ## Create a platform admin user
	$(BACKEND) python manage.py createsuperuser

shell: ## Open a Django shell
	$(BACKEND) python manage.py shell

test: test-backend test-frontend ## Run all tests

test-backend: ## Run backend tests with coverage
	$(BACKEND) pytest --cov -W error

test-frontend: ## Run frontend unit tests
	$(FRONTEND) npm test

lint: lint-backend lint-frontend ## Run all linters and type checks

lint-backend: ## Ruff + mypy + migration drift check
	$(BACKEND) sh -c "ruff format --check . && ruff check . && mypy . && python manage.py makemigrations --check --dry-run"

lint-frontend: ## ESLint + TypeScript
	$(FRONTEND) sh -c "npm run lint && npm run typecheck"

fmt: ## Auto-format backend code
	$(BACKEND) sh -c "ruff format . && ruff check --fix ."

check: lint test ## Everything CI runs locally (except image scans)

clean: ## Stop the stack AND delete local database data
	$(COMPOSE) down -v

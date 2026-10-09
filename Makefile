.PHONY: up down logs initdb resetdb dump-user restore-user seed test test-db test-live lint fmt slice accept-real demo-record demo-replay

PY ?= python
COMPOSE ?= docker compose

# Start db (PostGIS), api, worker, web and mailhog. Creates .env on first run.
up:
	@test -f .env || cp .env.example .env
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=100

# Create PostGIS + all tables from app/models.py (idempotent).
initdb:
	$(COMPOSE) run --rm api python -m app.db

# Drop and recreate derived tables; watchlists are kept. `make resetdb ALL=1` drops user tables too.
resetdb:
	$(COMPOSE) run --rm api python -m app.db --reset $(if $(ALL),--all)

# Save / load watchlists as JSON (data/user_dump.json, gitignored) around a `resetdb ALL=1`.
dump-user:
	$(COMPOSE) run --rm api python -m app.db --dump-user data/user_dump.json

restore-user:
	$(COMPOSE) run --rm api python -m app.db --restore-user data/user_dump.json

seed:
	@echo "seed: implemented in Phase 3 (facility registry)"

# Local tests; DB tests skip without a database. test-db runs them in the api container.
test:
	DATA_MODE=fixture $(PY) -m pytest

test-db:
	$(COMPOSE) run --rm -e DATA_MODE=fixture -w /srv api python -m pytest

# Tests that need real services and credentials (marked `live`).
test-live:
	RUN_LIVE=1 $(PY) -m pytest -m live

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

fmt:
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .

slice:
	@echo "slice: implemented in Phase 5A"

accept-real:
	@echo "accept-real: implemented in Phase 13"

demo-record:
	@echo "demo-record: implemented in Phase 13"

demo-replay:
	@echo "demo-replay: implemented in Phase 13"

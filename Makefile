.PHONY: up down logs initdb resetdb dump-user restore-user seed spike fixtures sources synthetic-fixtures smoke test test-db test-live lint fmt slice accept-real demo-record demo-replay

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

# Phase S, live, needs the Phase 0 credentials in .env. `spike` writes docs/SPIKE_REPORT.md;
# `fixtures` records tests/fixtures/real_singrauli/ (run `spike` first).
spike:
	$(PY) scripts/spike_ee.py $(ARGS)

fixtures:
	$(PY) scripts/make_fixtures.py --unit singrauli --days 120 $(ARGS)   # e.g. ARGS="--end 2026-02-28"

# Offline. `sources` rewrites config/sources.yaml from docs/SPIKE_FACTS.json (run after every spike);
# `synthetic-fixtures` rewrites tests/fixtures/synthetic/.
sources:
	$(PY) scripts/make_sources.py

synthetic-fixtures:
	$(PY) scripts/make_synthetic_fixtures.py

# Live check of the data clients (Phase 2), needs the Phase 0 credentials in .env.
smoke:
	DATA_MODE=live $(PY) -m app.clients.ee_client --smoke
	DATA_MODE=live $(PY) -m app.clients.wind --smoke

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

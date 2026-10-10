# Land Industrial Emissions Monitor

Screens registered industrial sites from space: flags NO₂ and SO₂ that are unusual for a site, attributes them to a site or cluster with a stated margin, estimates emission rates when the data supports them, and shows the people inside the modelled transport footprint. Starts with the Singrauli coal belt (India).

Results are screening indicators from satellite data at about 5 km resolution, not compliance evidence.

> **Status:** early development. The foundation is in place: the API, the database schema, a background worker and a map UI. The detection, attribution and alerting modules are still being built (see [Roadmap](#roadmap)). The build plan is in [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md), the feature behaviour in [docs/FEATURE_GUIDE.md](docs/FEATURE_GUIDE.md) and the log of finished phases in [docs/PROGRESS.md](docs/PROGRESS.md).

## Features

**Available now**

- **FastAPI backend** with `/health` (reports database status) and `/region` (monitored area from config).
- **PostGIS schema** for facilities, watch units, detections, events, emission estimates, baseline predictions, anomalies, footprint population, watchlists, alert deliveries and map-layer caching. All geometries are WGS84 (EPSG:4326). Tables are tagged `derived` (re-creatable) or `user` (watchlists, deliveries).
- **Typed shared schemas** (Pydantic). Every detector returns a list of `Detection` objects with a `natural_key`, so re-running a date never creates duplicates. Tests check that the schemas match the database columns.
- **Background worker** (APScheduler) that runs scheduled jobs in the region's time zone.
- **Map dashboard** (Vite + React + TypeScript + MapLibre GL) that zooms to the configured region.
- **Config in one place**: region, thresholds, schedule and weights live in `config/settings.yaml`; every user-facing claim and disclaimer lives in `config/wording.yaml`.
- **Local metric projection** (`app/geo/projection.py`) instead of a hard-coded UTM zone, and a token-protected admin dependency (`X-Admin-Token`).
- **Offline-first testing**: `DATA_MODE=fixture` means tests and CI never call external APIs.
- **Docker Compose stack** with PostGIS, API, worker, web and MailHog. CI runs on GitHub Actions.

## Tech stack

| Layer    | Tools                                                                |
| -------- | -------------------------------------------------------------------- |
| Backend  | Python 3.11, FastAPI, SQLAlchemy 2, GeoAlchemy2, pydantic-settings   |
| Database | PostgreSQL 16 + PostGIS 3.4                                          |
| Worker   | APScheduler                                                          |
| Frontend | Vite, React 19, TypeScript, MapLibre GL JS                           |
| Tooling  | pytest, ruff, Docker Compose, GitHub Actions                         |

## Getting started

### Prerequisites

- Docker with Docker Compose, plus `make`, **or**
- Python 3.11, Node.js 22 and a PostgreSQL/PostGIS server for a local setup without Docker

### Option A: Docker (recommended)

```bash
make up        # creates .env from .env.example if needed; starts db, api, worker, web, mailhog
make initdb    # enables PostGIS and creates all tables
```

| Service     | URL                          |
| ----------- | ---------------------------- |
| API health  | http://localhost:8000/health |
| API docs    | http://localhost:8000/docs   |
| Map         | http://localhost:5173        |
| MailHog     | http://localhost:8025        |

Other targets: `make down`, `make logs`, `make resetdb` (drops and recreates derived tables; watchlists are kept), `make resetdb ALL=1` (drops everything), `make dump-user` / `make restore-user` (watchlists to and from `data/user_dump.json`).

### Option B: Local without Docker

```bash
cp .env.example .env                 # then set DATABASE_URL to your PostGIS server (host: localhost)

python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

cd backend
python -m app.db                     # create schema
uvicorn app.main:app --reload        # API on :8000
python -m app.jobs.scheduler         # worker (separate terminal)

cd ../web
npm install
npm run dev                          # map on :5173, proxies /api to :8000
```

## Configuration

| File                   | Purpose                                                                                      |
| ---------------------- | -------------------------------------------------------------------------------------------- |
| `.env`                 | Secrets and per-machine values: `DATABASE_URL`, `DATA_MODE` (`live` / `fixture` / `replay`), API keys. Copy from `.env.example`. **Never commit it.** |
| `config/settings.yaml` | Region bounding box, detector thresholds, schedule and weights                               |
| `config/wording.yaml`  | User-facing labels, captions and the disclaimer                                              |
| `config/sources.yaml`  | Earth Engine asset ids, band names and access facts. Generated from the spike by `make sources`; do not edit by hand. |
| `config/regions/`      | Region boundary as GeoJSON                                                                    |
| `secrets/`             | Service-account key files (e.g. Earth Engine). Ignored by git.                               |

The credentials in `.env.example` (`emissions` / `emissions`) are for the local development database only. Use strong values anywhere else.

## Testing and linting

```bash
make test      # pytest locally; PostGIS tests are skipped if DATABASE_URL is unreachable
make test-live # tests marked `live` (real services, needs credentials)
make test-db   # full suite inside the api container, against PostGIS
make lint      # ruff check + ruff format --check
make spike     # live: probe the real data, write docs/SPIKE_REPORT.md (needs credentials)
make fixtures  # live: record tests/fixtures/real_singrauli/ (run `make spike` first)
make sources   # offline: rewrite config/sources.yaml from docs/SPIKE_FACTS.json (after every spike)
make smoke     # live: small requests through the Earth Engine client and the wind chain
make fmt       # auto-fix lint and formatting
```

### Data modes

Every data client (`backend/app/clients/`) works in three modes, set by `DATA_MODE`:

- `fixture` reads `tests/fixtures/`: the recorded Singrauli slice first, then the small synthetic files. Tests and CI always use it, and a test that tries to open a network connection fails.
- `live` reads `data/cache/<source>/` and calls the service on a miss. Data for the last days is fetched again until it has settled (`schedule.rerun_previous_days`).
- `replay` reads the cache only.

CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs lint and the full test suite against a PostGIS service, and builds the web app. Database tests use a separate `<database>_test` database, so they never touch development data.

## Project structure

```
.
├── backend/
│   ├── Dockerfile
│   └── app/
│       ├── main.py          # FastAPI app and routes
│       ├── settings.py      # .env + settings.yaml loading
│       ├── db.py            # engine, sessions, init_db, reset_db (python -m app.db [--reset [--all]])
│       ├── models.py        # the only database schema definition
│       ├── schemas.py       # Pydantic schemas shared by detectors and API
│       ├── wording.py       # t(key): user-facing text from config/wording.yaml
│       ├── geo/             # local_aeqd projection
│       ├── repositories/    # database I/O
│       ├── jobs/            # scheduler (worker entry point)
│       ├── clients/         # Earth Engine, wind chain, CDS, FIRMS, flares, OSM; cache and data modes
│       ├── registry/        # facility registry                (planned)
│       ├── detect/          # gas, flare, thermal, smoke       (planned)
│       ├── attribute/       # source attribution, emissions    (planned)
│       ├── temporal/        # baselines and anomaly alerts     (planned)
│       ├── impact/          # population / sensitive sites     (planned)
│       ├── alerts/          # geofenced email alerts           (planned)
│       ├── reports/         # PDF evidence reports             (planned)
│       ├── api/             # additional API routes            (planned)
│       └── demo/            # demo record / replay             (planned)
├── config/
│   ├── settings.yaml        # all thresholds and schedules
│   ├── wording.yaml         # user-facing wording
│   └── regions/             # region boundaries (GeoJSON)
├── docs/                    # implementation plan, feature guide, progress log
├── data/                    # local caches and raw inputs (gitignored)
├── ml/                      # model training code              (planned)
├── models/                  # trained model weights (gitignored)
├── scripts/                 # spike_ee.py, make_fixtures.py (live); make_sources.py, make_synthetic_fixtures.py (offline)
├── secrets/                 # key files (gitignored)
├── tests/                   # pytest suite and fixtures
├── web/                     # Vite + React + MapLibre dashboard
├── docker-compose.yml
├── Makefile
└── pyproject.toml           # package, pytest and ruff config
```

## Roadmap

Phases from [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md):

- S. ~~Real-data spike and recorded fixtures~~ ✅
- 1. ~~Repo skeleton, Docker, database~~ ✅
- 2. ~~Data access layer, wind providers, fixtures~~ ✅
- 3. Facility registry and watch units
- 4. Gas detectors, flaring, score
- 5A. Attribution, fusion, first end-to-end slice
- 5B. Emission rates with uncertainty
- 6. Thermal anomaly classifier
- 7. Stack plume classifier
- 8. Unit baseline model and anomaly alerts
- 9. Population and sensitive sites in the transport footprint
- 10. Scheduled pipeline and API
- 11. Map dashboard
- 12. Watchlists, geofenced email alerts and PDF reports
- 13. Integration, real-data acceptance and demo mode

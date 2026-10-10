# Land Emissions Monitor — rules for Claude Code

## Workflow
- Read `docs/IMPLEMENTATION_PLAN.md` (sections 0.x + the phase you were asked for) and `docs/FEATURE_GUIDE.md` for the features in that phase. Work only on that phase.
- Before coding, read `docs/PROGRESS.md` and `docs/SPIKE_REPORT.md` (if it exists). If a task conflicts with either, stop and say so.
- Never guess an Earth Engine asset ID, band name, API field or quota. Use the value in `docs/SPIKE_REPORT.md`; if it is not there, say it needs the spike (Phase S) and use a clearly marked TODO.
- Run `make lint test` before saying a task is done. Fix failures; never skip, xfail or delete a test to get green.
- At the end of a phase: tick its "Done when" items, append a short entry to `docs/PROGRESS.md` (what was built, deviations from the plan, open questions), then stop. Do not start the next phase.
- If a decision is not covered by the plan and changes an interface or the schema, ask. Otherwise decide, and record it in `docs/PROGRESS.md`.

## Stack
- Python 3.11, FastAPI, SQLAlchemy 2 + GeoAlchemy2, pydantic-settings. Frontend: Vite + React + TypeScript + MapLibre GL JS (+ Recharts from Phase 11).
- Add a dependency to `pyproject.toml` only in the phase that first imports it (plan §0.5).

## Data, tests and config
- Schema lives only in `backend/app/models.py`. Tables are tagged `info={"kind": "derived"}` or `{"kind": "user"}`. `make resetdb` drops derived tables only; `make resetdb ALL=1` drops everything.
- Never call Earth Engine, CDS, FIRMS, EOG, Overpass or any network API in tests. Use `DATA_MODE=fixture` and `tests/fixtures/`. Tests that need real services are marked `@pytest.mark.live` and are skipped unless `RUN_LIVE=1`.
- Never loop per day or per facility over Earth Engine for history. Use the batched `get_buffer_timeseries` (plan §2), cached to parquet.
- All thresholds, weights and wording live in `config/settings.yaml` and `config/wording.yaml`. No numbers or user-facing claims hard-coded in detectors or templates.
- Every detector returns `list[Detection]` (`schemas.py`). Layer-only products (CH4) return a `LayerProduct`. Do not invent other shapes.
- EOG Nightfire is optional (licence-gated, scripted access is paid). Never require `EOG_*` variables or fail when Nightfire is missing; flaring uses `flaring.source` (default `firms_persistent`).
- Detections are upserted on `natural_key` (plan §0.7), never inserted blindly; re-running a date must not create duplicates.

## Geometry
- DB and API: WGS84 (EPSG:4326). Metric work: the local azimuthal-equidistant projection from `app/geo/projection.py:local_aeqd(lon, lat)`. Never hard-code a UTM zone (Delhi is zone 43, Singrauli zone 44).
- Watch units (an isolated facility or a cluster of facilities) are the unit of detection, attribution and emission rates. Never attribute a cluster detection to a single plant unless the attribution margin allows it.

## Honesty rules (these protect the demo)
- A confidence value is an uncalibrated score, not a probability. Say "score" in code, API and UI until `calibration.json` exists.
- Stub or fallback model output sets `is_stub=true`, and is excluded from fusion, confidence boosts and PDF evidence. A stub must never look like a real result.
- Emission-rate bands must include the wind-uncertainty term; show statistical-only bands only when labelled as such.
- Every user-facing report/alert uses the wording in `config/wording.yaml` ("screening indicator, not compliance evidence").
- Report every evaluation metric on the independent evaluation set, not on the weak-label set.

## Code style
- Keep functions pure where possible: data in, detections out. I/O lives in `clients/` and `repositories/`.
- Wind comes only from `clients/wind.py:get_wind()` (provider chain); record `wind_source` and level in `qa`.
- Admin and write endpoints require `X-Admin-Token` (admin) or a confirmed watchlist token (user).

# Progress log

One entry per finished phase: what was built, deviations from the plan, open questions.

---

## Phase 1 — Repo skeleton, Docker, database (reworked to plan v2) — 2026-10-09

The first Phase 1 commit followed plan v1. This entry covers the rework to v2. Phase 1 was done before Phase S because the repo already existed.

### Built
- `docs/` with the v2 plan and feature guide; `CLAUDE.md` as delivered; `.gitignore` no longer ignores them.
- `config/settings.yaml` replaced by the §0.10 defaults (region bbox is now `[82.0, 23.6, 83.4, 24.8]`); `config/wording.yaml`; `config/regions/delhi_ncr.geojson`.
- `app/models.py`: all tables of §0.7, each tagged `derived` or `user`. New: `watch_units`, `watch_unit_id` columns, `natural_key` (unique), `z_bg`, `z_self`, `score`, `score_parts`, `is_stub`, the event attribution fields and `contested` status, the v2 emission-estimate, baseline, exposure and watchlist columns.
- `app/schemas.py`: `Detection`, `LayerProduct`, `Event`, `EmissionEstimate`, `Exposure`, `Facility`, `WatchUnit`, `ScoreParts`, and `natural_key()`. Datetimes must be timezone-aware.
- `app/db.py`: `init_db()`, `reset_db(all=False)`; `make resetdb`, `make resetdb ALL=1`, `make dump-user`, `make restore-user` (`app/repositories/user_data.py`).
- `app/geo/projection.py:local_aeqd`, `app/wording.py:t`, `app/api/deps.py:require_admin`.
- `ADMIN_TOKEN`, `CDS_*`, `RUN_LIVE`, `WORDING_PATH` in `.env.example`; pytest marker `live` (skipped unless `RUN_LIVE=1`).

### Done when
- [x] `ruff check`, `ruff format --check` and `pytest` pass locally: 45 passed, 3 skipped.
- [ ] `make up && make initdb`, `GET /health` → 200, browser shows the map: **not run**. The build machine has no Docker.
- [ ] `make resetdb` keeps a `watchlists` row and `make resetdb ALL=1` removes it: the test exists (`tests/test_db.py`) but was **skipped** with the two other PostGIS tests, because no database was reachable. They run in CI and with `make test-db`.

### Deviations from the plan
- `pyproj` is a Phase 1 dependency (plan §0.5 lists it under Phase 2 via geopandas), because `local_aeqd` imports it.
- `alert_deliveries.event_id` and `anomaly_id` are plain integers without a foreign key. A user table that references derived tables would block the derived-only reset. `reset_db()` clears `alert_deliveries` on a derived-only reset, because its rows point at rows that no longer exist.
- `schedule.heartbeat_minutes` was added to `settings.yaml` (worker liveness log); it is not in §0.10.
- `WatchUnit` schema has `lon`/`lat` (plan §0.6) while the table has `geom` and `region` (plan §0.7). The `Event` schema has no `created_at`/`updated_at`. The parity test lists these differences.
- `emission_estimates.rate_kg_s` is nullable, so `insufficient_data` rows carry no rate.
- Database tests run on a separate `<database>_test` database so they cannot drop development tables.
- `make` targets `slice` and `accept-real` are placeholders until Phases 5A and 13.

### Fixed along the way
- `python -m app.db` created no tables: the module ran as `__main__`, so the models registered on a different `Base`. The entry point now calls the imported module.

### Open questions
- After a derived-only reset the delivery log is empty, so a re-run of the pipeline would email the same real-world events again. A stable event key in `alert_deliveries` would fix this; decide in Phase 12.
- The Delhi-NCR box in `config/regions/delhi_ncr.geojson` is a placeholder and must be checked before it is used as a region.
- `config/sources.yaml` does not exist yet; Phase 2 generates it from `docs/SPIKE_REPORT.md`.

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

---

## Phase S — Real-data spike and recorded fixtures — 2026-10-10

The spike ran live on 2026-10-10, the real slice is recorded and gate G1 is decided (section 12 of `docs/SPIKE_REPORT.md`).

### Built
- `scripts/spike_ee.py` (`make spike`): probes every collection (resolves, bands, newest image, scale), picks product bands by pattern from the reported band lists, lists wind levels and compares 10 m with 100 m at the largest plants, checks the CDS, downloads NO2 and SO2 grids for a 120 km window, reports valid days per month over a full year, runs rough null-buffer and SO2-window prototypes on the last 120 days and on the last dry season, times small calls against two batched forms, checks FIRMS (access, and night-time detections within `flaring.radius_km` of each plant) and the annual flare-site files on disk. Nightfire is not tested (plan v2.1). Writes `docs/SPIKE_REPORT.md` and `docs/SPIKE_FACTS.json`. A failing section is recorded and the run continues; `--only` re-runs sections.
- `scripts/make_fixtures.py` (`make fixtures`): records `tests/fixtures/real_singrauli/` using only ids and bands from `SPIKE_FACTS.json`, then checks the slice.
- `scripts/flare_sources.py`, `scripts/spike_analysis.py`, `scripts/spike_report.py`, `scripts/ee_common.py`.
- `app/clients/slice_format.py`: the slice format and `check_slice()`.
- `tests/test_fixture_integrity.py`, `tests/test_spike.py`.

### Done when
- [x] Report exists with every table filled (`docs/SPIKE_REPORT.md`, no section errors). Two columns are for people: "QA already applied in L3?" (section 3) and the Nightfire rows (section 10).
- [x] Gate G1 decided on 2026-10-10 and written in section 12 of the report.
- [x] `tests/fixtures/real_singrauli/` recorded (13 MB): NO2 with cloud fraction, SO2, aerosol index, ERA5 100 m wind, FIRMS, flare sites (none in the region), OSM objects, three Sentinel-2 chips.
- [x] Fixture integrity test passes on the real slice.
- [x] `ruff` and `pytest` pass, including the three PostGIS tests against the Docker database.

### What the real data showed
- All 14 collections resolve. Offline NO2 is 9.4 days behind, offline SO2 2.9 days, near-real-time NO2 0.1 days.
- Earth Engine's own ERA5 hourly collection has 100 m winds, 6.4 days behind; the CDS is at most 6 days behind and took 55 s for one small request. GFS in Earth Engine has only 10 m winds and no analysis at 08:00 UTC (run hours only). 100 m wind is 1.3–1.4 times the 10 m wind at the plants.
- Valid days (at least half the window has a value): 84–90 % from November to May, 26 % in October, 63 % in June, 10–20 % from July to September.
- Null-buffer prototype: in the dry season 88 of 102 testable days have `z_bg ≥ 2` (median 6.3). The plants are above the background almost every day, so `z_bg` alone cannot make events; `z_self` is needed, as the plan says.
- SO2 window prototype, dry season: Vindhyachal passes in all four windows (z 2.8–5.5, 22–28 valid days). Sasan and Rihand do not; their upwind boxes contain the neighbouring plants. In the monsoon only one window has 10 valid days.
- One request with `reduceRegions` mapped over 90 days fails with "Too many concurrent aggregations". The same 1800 unit-days as one `reduceRegions` over a 90-band image take 3 s.
- FIRMS: the area API accepts at most 5 days per request. No night-time detection within 2 km of the five largest plants in 90 days. The flare-site file has no site in the region.

### Not verified
- `make_fixtures.py --wind cds` and `--include-nightfire` have not been run.

### Deviations from the plan
- Dependencies added now: `earthengine-api`, `numpy`, `pandas`, `httpx` (plan §0.5, Phase S) and also `xarray`, `netcdf4`, `cdsapi` (listed under Phase 2), because the Phase S scripts import them. `openpyxl` is added to read the annual flare-site Excel files; the plan does not list it, and Phase 3 needs it for the Global Energy Monitor files too.
- **The slice covers 2025-11-01 to 2026-02-28, not the last 120 days.** The last 120 days are the monsoon with 10–20 % valid days, which would leave Phase 4 and 5A almost nothing to accept on. FIRMS in the slice is therefore the standard-processing product (`VIIRS_SNPP_SP`); the near-real-time products start on 2026-07-01.
- The slice wind is Earth Engine ERA5 hourly at 100 m, at the analysis centre and the five plants.
- Point tables in the slice are CSV, not parquet, so `pyarrow` waits for Phase 2.
- The plants for the spike come from OpenStreetMap (`power=plant`, largest first), because the registry is Phase 3. The analysis window is centred on their mean position, not on the bbox centre.
- Whether the Level-3 Sentinel-5P products are already QA-filtered cannot be read from image metadata. The report lists the QA and cloud bands and the masked share, and leaves a column to fill in from the catalog page.
- Nightfire (plan v2.1): the scripts never read `EOG_*` variables and never fail without Nightfire. `make_fixtures.py` records `data/raw/nightfire/*.csv` only with `--include-nightfire`, because the files are licence-gated and the slice is committed.
- The SO2 box (30 km along, ±10 km across) is a constant in `spike_ee.py` taken from the Phase 4 text; it is not in `settings.yaml` yet.

### Gate G1 decisions (config changed)
- `wind.chain` is now `[era5_100m_ee, cds_era5_100m, gfs_ee, era5_land_10m_ee]`. `era5_100m_ee` is a new provider (Earth Engine ERA5 hourly at 100 m) that Phase 2 has to build beside the three in the plan; its `uncertainty_frac` is 0.25, the same as the CDS copy.
- `schedule.rerun_previous_days` is 10 (plan: 5), because offline NO2 arrives after about 9 days.
- SO2 detector stays, per watch unit. `valid_fraction_min`, `flaring.source` and the bbox are unchanged.

### Open questions
- `get_buffer_timeseries` (Phase 2) must use the stacked-bands form; the mapped form hits the concurrency limit.
- Still for people to fill in the report: whether the Level-3 products are already QA-filtered (section 3) and the Nightfire licence status (section 10).
- SO2 should be tested per watch unit (the cluster), not per plant: neighbouring plants sit in each other's upwind boxes.
- `config/sources.yaml` (Phase 2) should be generated from `docs/SPIKE_FACTS.json`.
- Wording for `firms_persistent` detections: without a flame temperature a persistent night-time hotspot near a plant
  may be a furnace, a stockpile or a mine fire. Decide in Phase 4 whether the UI says "flare" or
  "persistent night-time heat source" unless a known flare site or Nightfire confirms it.
- `data/raw/` (CEA reports, Nightfire files) is gitignored. The plan puts Nightfire files in `data/raw/nightfire/`.

### Plan v2.1 applied (2026-10-10)
- Docs and `CLAUDE.md` replaced with v2.1; `settings.yaml` has the `flaring` section in place of `detect.flare_*`
  (Phase 1 commit). The Nightfire access check was removed from the spike and replaced as described above (this commit).

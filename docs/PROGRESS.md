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

---

## Phase 0 — data collected — 2026-10-10

- Credentials in `.env`, `secrets/ee-key.json` and `~/.cdsapirc`; all three were used successfully by the spike.
- Registry files in `data/registry/raw/`: WRI GPPD, GEM coal, steel and cement trackers, Climate TRACE
  (`climate_trace/`), and the World Bank flare-location file (`flares/`).
- `scripts/cea_reports.py` turns the CEA daily reports in `data/raw/cea/` into:
  - `data/known_events.csv`: 44 rows. 43 unit outages at the eight thermal stations of the region, from Sub-Report 10
    (units under maintenance) and Sub-Report 14 (units recommissioned) of eight report days between 2020 and 2026,
    plus the 2020 national lockdown. Extra columns: `unit_no`, `capacity_out_mw`, `outage_kind`, `ongoing_at_report`,
    `duration_days`, `reason`. For an outage still running on the report day, `end` is the report day, so the true end
    is later.
  - `data/covariates/generation.csv`: 144 rows, eight stations on 18 days between 2021 and 2026, with
    `monitored_capacity_mw` and `capacity_under_outage_mw` beside `generation_mwh`.

### Deviations
- `xlrd` is a dependency, to read the `.xls` reports.
- Station names are a fixed list in `cea_reports.py` (stations whose WRI coordinates lie in the region); Phase 3
  should replace it with the registry.

### Still open
- The lockdown row has no source link yet.
- Many outages take out one unit of a multi-unit plant for a few days; Phase 8 should weigh events by
  `capacity_out_mw` and `duration_days` when it reports hit rates.
- Generation covers 18 days, which is too sparse for a daily covariate. More `dgr2` report days are needed before
  Phase 8 can use it.
- Climate TRACE has four assets in the region (Vindhyachal, Sasan, two at Mahan); Rihand, Singrauli, Anpara and Obra
  are not in the download. The two sets of files in `climate_trace/` overlap: the newer ones contain the older.
- The flare-location file has no site in the region.
- Nightfire licence: optional, status not recorded.

---

## Phase 2 — Data access layer, wind providers, fixtures — 2026-10-10

### Built
- `config/sources.yaml`, written by `scripts/make_sources.py` (`make sources`) from `docs/SPIKE_FACTS.json`: collections, products and bands, wind providers, the CDS request, Sentinel-2 bands, FIRMS sources. A band the spike did not list is an error in the generator. A test fails when the file differs from what the generator writes, and when an id or band is not in `docs/SPIKE_REPORT.md`.
- `app/clients/base.py`: data modes, fixture lookup (the recorded slice first, then `tests/fixtures/synthetic/`), the cache `data/cache/<source>/<key>.{nc,parquet,json}`, and `retry` (exponential backoff with jitter; the service's own error text is raised).
- `app/clients/ee_client.py`: `get_no2`, `get_so2`, `get_aerosol_index`, `get_ch4`, `get_s2_chip`, `get_worldcover`, `get_ndvi`, `get_burned_area`, `get_population`, `get_tile_url`, `get_buffer_timeseries`, and `stream_for` (near-real-time or offline collection for a day, gate G1).
- `get_buffer_timeseries` uses the stacked-bands form: one `reduceRegions` per calendar quarter, cached as parquet per quarter.
- `app/clients/wind.py:get_wind` with the four providers of gate G1 (`era5_100m_ee` is the new one) and `app/clients/cds.py` (one download per month, cached NetCDF). The result has `source`, `level`, `uncertainty_frac` and `time_offset_h` per time, and a summary in the attrs.
- `app/clients/firms.py`, `flares.py` (one interface over `annual_sites`, `firms_persistent`, `nightfire`), `nightfire.py` (optional; never raises), `osm.py`.
- `tests/synthetic.py`: `make_correlated_background`, `inject_plume` (Lagrangian puff model), `apply_footprint`, `add_missing`, `add_neighbour_source`; `puff_plume` returns the column with a mass budget.
- `scripts/make_synthetic_fixtures.py` and its output in `tests/fixtures/synthetic/` (CH4, land cover, burned area, population, a 10 m GFS wind for five days after the slice). The values are made up and marked `mode: synthetic`.
- Tests: five new offline test files. A test that opens a network connection to another machine fails (`conftest.py`). Three tests in `tests/live/` are marked `live`.

### Done when
- [x] All client tests pass in fixture mode: `ruff check`, `ruff format --check` and `pytest` pass locally (counts in the commit message). Skipped: the 3 live tests, and the 3 PostGIS tests because no database was reachable in this session.
- [x] `python -m app.clients.wind --smoke` works in live mode (run on 2026-10-10): `era5_100m_ee` answered up to 2026-10-02, `cds_era5_100m` 3–5 October, `gfs_ee` (10 m, 2 h offset) 6–9 October.
- [ ] `python -m app.clients.ee_client --smoke` in live mode: **10 of 11 checks pass.** `get_tile_url` fails with "Permission 'earthengine.maps.create' denied on resource 'projects/land-emission-monitor'". The service account needs that permission (👤); until then the live path of `get_tile_url` is untested.
- [x] `get_buffer_timeseries` returns one quarter for 20 units in one call in live mode: 1820 rows in 2.7 s (181 bands in one `reduceRegions`). The three live tests pass with `RUN_LIVE=1`.

### Found with live data
- **The recorded slice was labelled up to half a pixel off.** The Sentinel-5P Level-3 pixels are 0.01° with edges on multiples of 0.01°. The Phase S recording grid was not aligned with them, so each value was stored under coordinates up to 0.0045° away from its pixel centre. A 5 km buffer mean over the plants came out about 7 % higher from the slice than from Earth Engine. Fixed in two places:
  - `daily_grids` now widens the bbox to whole pixels (`snap_bbox`), for the client and for `make_fixtures.py`.
  - The `lat`/`lon` coordinates of `no2.nc`, `so2.nc` and `aer_ai.nc` in the slice were re-labelled to the pixel centres (values unchanged; noted in `manifest.json`). The re-labelled NO2 and cloud grids equal a live aligned fetch cell for cell on 3 days (12 078 cells). Live and recorded buffer means now agree within 3 %.
- `reduceRegions` runs unweighted (a pixel counts when its centre is in the buffer), so `n_total` and the mean are defined as in fixture mode. The weighted default counted 86 pixels in a 5 km buffer; unweighted counts 69, the grid statistic 70–71.
- The MODIS burned-area band and the NDVI band need a cast to float before they are merged with the masked template (found by the smoke check).

### Deviations from the plan
- `rioxarray` is not a dependency: nothing imports it (no GeoTIFF is written). Added now: `scipy`, `shapely`, `geopandas`, `pyarrow`.
- New settings: `wind.gfs_max_offset_hours`, and the sections `data` (request sizes, Sentinel-2 search window, NDVI and land-cover scale) and `layers` (display range and palette per tile layer). New `Settings` fields for the keys and for the cache, fixture, flare and Nightfire folders.
- `gfs_ee` uses the nearest analysis within `wind.gfs_max_offset_hours` (3) of the requested time, because the spike confirmed analyses at run hours only. `time_offset_h` records the difference (2 h for the 08:00 overpass).
- A time is answered by a provider only when it has wind for every requested point, so one call never mixes levels within a time.
- A provider that raises is skipped, logged and named in `attrs["notes"]`; the next one answers.
- `replay` mode reads the cache only and never calls a service. Phase 13 builds the demo replay on this.
- A cache file whose data ends less than `schedule.rerun_previous_days` before it was written is fetched again. Without this the first, incomplete version of the last days would be kept.
- The cache holds `.nc`, `.parquet` and `.json` (OSM features, population, FIRMS availability); no `.tif`.
- `get_s2_chip` returns `None` when no scene under `data.s2_max_cloud_pct` lies within `data.s2_search_days`. The acquisition time is in `attrs["acquired_at"]`.
- `get_ndvi` in fixture mode is computed from the recorded Sentinel-2 chips, so it covers 1.3 km around Vindhyachal only.
- `get_tile_url` returns `fixture://tiles/...` in fixture mode, which no map can load by mistake.
- Nightfire: the scripted download with `EOG_*` is **not implemented** (marked TODO in `nightfire.py`), because its endpoints were not probed in Phase S. The column names of the nightly files are not verified either; columns are found by pattern and a file without them is skipped.
- `scripts/ee_common.py` and `scripts/flare_sources.py` import `retry`, `grid_spec`, `daily_grids`, the Overpass and FIRMS helpers and `read_flare_sites` from `app/clients/`, where they moved, so there is one copy. The live scripts were not re-run after this change; their offline tests pass.
- The smoke checks and the live tests were run by Claude Code with the keys in `.env`, not by a person.

### Open questions
- 👤 Grant the service account `earthengine.maps.create` (or decide that tiles are rendered another way) before Phases 10 and 11 need `get_tile_url`.
- Re-record the slice with `make fixtures ARGS="--end 2026-02-28"` when convenient. The re-labelled slice is exact; a new recording would also start the window on a pixel edge.
- A GFS forecast step valid at 08:00 UTC (the 06:00 run, step 2) would remove the 2 h offset. The spike confirmed the properties `forecast_hours` and `forecast_time` but not that such images exist; check in the next spike run.
- CH4 uses `CH4_column_volume_mixing_ratio_dry_air`, the first match in the spike. `..._bias_corrected` is also in the band list and may be the better choice for the layer; decide in Phase 4.
- The buffer time-series cache is keyed by the whole set of units, so adding a unit fetches every quarter again (one request per quarter).
- Still for people to fill in: whether the Level-3 products are QA-filtered (report section 3). Until then `valid` means "the product has a value".
- Layer display ranges in `layers` are first values; tune them in Phase 11.

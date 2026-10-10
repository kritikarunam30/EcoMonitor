# Land Industrial Emissions Monitor — Implementation Plan for Claude Code (v2)

Source: *Land Emissions Monitor – Project Plan* (v2, 9 Oct 2026). 17 features, 3 own models, **49.0 person-days (44.5 with trims)** for Phases S–13; Phase 0 (accounts and downloads, 0.5 days) is on top.

This plan is written so Claude Code can build the project **one phase per session**. Each phase lists the goal, inputs, files, tasks, tests that prove it works, a "Done when" gate and a ready-to-paste prompt. Feature numbers (#1, #7, #22 …) match the Word plan. Read `FEATURE_GUIDE.md` for what each feature means for a user and how it must behave.

**v2.1 (10 Oct 2026).** Flaring (#5) no longer depends on EOG Nightfire access. EOG now requires a Nightfire data-use licence (a no-cost one-year academic licence exists, approval takes days) and charges for scripted downloads since 1 June 2026. Flaring therefore runs on a `flaring.source` setting: `annual_sites` (free annual flare-location files) plus `firms_persistent` (nightly, free FIRMS key) by default, with `nightfire` as an optional upgrade. Nothing on the critical path waits for the licence.

**Why v2 exists.** A review of v1 found problems that would have produced a demo that works on fixtures and fails on real data: no contact with real satellite data until the last phase, a hotspot test that detects "a power plant is a power plant", conflicting asset vs. cone attribution in a plant cluster, a thermal model that learned its own labels, a baseline validated on its own training data, and overclaimed confidence, emission-rate and exposure numbers. §0.8 lists every change and where it landed.

---

## 0. How to use this plan with Claude Code

1. Commit this file as `docs/IMPLEMENTATION_PLAN.md` (and `FEATURE_GUIDE.md` beside it). It contains no secrets, and every teammate and every Claude Code session needs it. `CLAUDE.md` sits at the repo root.
2. Run **one phase per session**. Start with the phase prompt at the end of the phase. Claude Code reads `CLAUDE.md` automatically.
3. A phase is done only when every **Done when** item passes (`make lint test` green plus the listed check). Then Claude Code appends an entry to `docs/PROGRESS.md` (built, deviations, open questions). Commit: `git commit -m "Phase N: <name>"`.
4. Steps marked **👤 HUMAN** cannot be done by Claude Code (logins, downloads, GPU training, hand-labelling, running live scripts). Do them before the phase that needs them; each phase says which.
5. **Stop conditions.** If a metric target in a phase is not met after a reasonable attempt, Claude Code must stop, report the achieved numbers and propose options. It must not loosen a test, xfail it or change a config threshold to make it pass.
6. **Decision gates** (§0.9) are points where you review real numbers and may trim scope. They are part of the plan, not optional.

### 0.1 Ground rules that make this buildable by an agent

- **Fixture-first, but real data early.** Every external source sits behind a client with modes `live`, `fixture`, `replay`. CI always uses `fixture`. Fixtures come in two kinds: small hand-made synthetic ones, and **real recorded slices** of the Singrauli cluster made in Phase S. Phase 4 and 5A acceptance run on the real slice.
- **Synthetic plumes with an independent forward model.** The test generator uses a Lagrangian puff model with first-order decay, the TROPOMI pixel footprint blur, spatially correlated noise, missing days and a neighbouring source. The emission-rate fit uses a different (Beirle EMG) model, so a pass is not circular.
- **Models are trained outside, served inside.** Claude Code writes export scripts, notebooks and inference code. You run GPU training and labelling. Until real weights exist, a stub returns fixed output **with `is_stub=true`**, which is excluded from fusion, score boosts and PDFs.
- **One config.** `config/settings.yaml` (thresholds, weights, schedule), `config/wording.yaml` (all user-facing claims and disclaimers), `.env` (keys).
- **One schema definition.** `backend/app/models.py` only. Tables are tagged `derived` (re-creatable) or `user` (watchlists, deliveries). `make resetdb` drops derived tables only.
- **No per-day Earth Engine loops for history.** One batched `reduceRegions` call per quarter returns a table, cached to parquet.
- **Dependencies arrive with the phase that uses them** (§0.5).

### 0.2 Phase map

| Phase | Name | Features | Person-days | Can run in parallel with |
|---|---|---|---|---|
| 0 | 👤 Accounts, downloads, decisions | — | 0.5 (extra) | — |
| S | Real-data spike and recorded fixtures | Arch (new) | 1.0 | — |
| 1 | Repo skeleton, Docker, database | Arch 8 + scaffolding | 1.5 | — |
| 2 | Data access layer, wind providers, fixtures | Arch 7 | 2.5 | — |
| 3 | Facility registry and watch units | #16 | 2.25 | 4 (after 2) |
| 4 | Gas detectors, flaring, confidence | #1, #2, #3, #5, #21 | 8.0 | 3 |
| 5A | Attribution, fusion, first end-to-end slice | #17, Arch 3 | 3.75 | 6, 7 |
| 5B | Emission rates with honest uncertainty | #18 | 3.5 | 6, 7, 8 |
| 6 | Own model 1: thermal anomaly classifier | #7, Arch 6 (half) | 4.0 | 5A, 5B, 7 |
| 7 | Own model 2: stack plume classifier | #8, Arch 6 (half) | 4.0 | 5A, 5B, 6 |
| 8 | Own model 3: facility baseline + anomaly alerts | #22, #23 | 5.0 | 9 |
| 9 | Impact: population and sensitive sites | #28, #29 | 3.0 | 8 |
| 10 | Backend API + scheduler (live watch) | Arch 11 + scaffolding | 1.5 | 11 |
| 11 | Map dashboard | #32 | 2.5 | 10 |
| 12 | Watchlists, geofenced email alerts, PDF reports | #33, #34 | 3.5 | — |
| 13 | Integration, real-data acceptance, demo mode | Cross-cutting | 3.0 | — |
| | **Total S–13** | | **49.0** | |

Critical path: S → 1 → 2 → 3 → 4 → 5A → 8 → 10 → 12 → 13. Phases 5B, 6, 7, 9 and 11 hang off the side and can go to other team members.

### 0.3 Target repo layout

```
land-emissions-monitor/
├── CLAUDE.md
├── README.md                  # setup, usage, features, structure, limitations, ethics/wording
├── Makefile                   # up down initdb resetdb seed test test-live lint spike fixtures slice accept-real demo-record demo-replay
├── pyproject.toml
├── docker-compose.yml         # db (postgis), api, worker, web, mailhog
├── .env.example
├── docs/
│   ├── IMPLEMENTATION_PLAN.md
│   ├── FEATURE_GUIDE.md
│   ├── SPIKE_REPORT.md        # written in Phase S; the single source of truth for EE ids/bands/latency
│   └── PROGRESS.md            # one entry per finished phase
├── config/
│   ├── settings.yaml
│   ├── wording.yaml
│   └── regions/singrauli.geojson, delhi_ncr.geojson
├── backend/
│   ├── Dockerfile
│   └── app/
│       ├── main.py, settings.py, db.py, models.py, schemas.py, wording.py
│       ├── geo/             # projection.py (local_aeqd), cones.py, rotation.py
│       ├── clients/         # ee_client.py, wind.py, firms.py, flares.py, nightfire.py (optional), osm.py, registry_sources.py, cds.py
│       ├── registry/        # build.py, dedupe.py, units.py                       (#16)
│       ├── detect/          # null_buffers.py, no2.py, so2.py, ch4.py, flaring.py, thermal.py, smoke.py, confidence.py
│       ├── attribute/       # upwind_cone.py, fusion.py, emission.py
│       ├── temporal/        # features.py, baseline.py, alerts.py, calibrate.py
│       ├── impact/          # exposure.py, sensitive_sites.py
│       ├── alerts/          # geofence.py, mailer.py, optin.py
│       ├── reports/         # render.py, templates/event_report.html
│       ├── jobs/            # scheduler.py, pipeline.py
│       ├── api/             # routes_facilities.py, routes_events.py, routes_layers.py, routes_watchlists.py, routes_reports.py, routes_admin.py
│       ├── repositories/    # detections.py (upsert), events.py, ...
│       └── demo/            # record.py, replay.py
├── ml/
│   ├── thermal/             # make_dataset.py, make_eval_template.py, train.ipynb
│   ├── smoke/               # export_chips.py, prepare_labels.py, train.ipynb, export_onnx.py
│   └── baseline/            # train.py
├── models/                  # thermal_lgbm.txt, smoke_resnet18.onnx, baseline_lgbm.txt, calibration.json (gitignored except stubs)
├── data/                    # cache/, registry/raw/, known_events.csv, review_labels.csv, covariates/generation.csv, demo/
├── scripts/                 # spike_ee.py, make_fixtures.py
├── web/                     # Vite React app
└── tests/
    ├── fixtures/            # synthetic/ and real_singrauli/ (NetCDF/parquet/CSV/GeoJSON)
    ├── live/                # @pytest.mark.live acceptance tests (need credentials)
    ├── synthetic.py         # puff-model plume generator and noise tools
    └── test_*.py
```

### 0.4 `CLAUDE.md`

`CLAUDE.md` (delivered with this plan) is the rules file. Create it in Phase 1 exactly as delivered. It points Claude Code to `docs/`.

### 0.5 Dependencies by phase

| Phase | Python packages added | System packages (Dockerfile) |
|---|---|---|
| S | earthengine-api, pandas, numpy, httpx (script-only; also needed by Phase 2) | — |
| 1 | fastapi, uvicorn[standard], sqlalchemy, geoalchemy2, psycopg[binary], pydantic-settings, pyyaml, apscheduler; dev: pytest, httpx, ruff | — |
| 2 | xarray, rioxarray (brings rasterio), geopandas (brings pyproj), shapely, scipy, pyarrow, netcdf4, cdsapi | — |
| 3 | rapidfuzz | — |
| 6, 8 | lightgbm, scikit-learn | libgomp1 |
| 7 | onnxruntime (training-only packages such as timm/torch stay in the Colab notebook) | — |
| 11 | web: recharts, terra-draw, terra-draw-maplibre-gl-adapter, openapi-typescript, @playwright/test | — |
| 12 | jinja2, weasyprint, matplotlib | libpango-1.0-0, libpangoft2-1.0-0 |

### 0.6 Interface contracts (shared by all phases — do not change without recording it in `PROGRESS.md`)

**Time.** All datetimes are UTC and timezone-aware. The nominal TROPOMI overpass for India is 08:00 UTC (≈13:30 IST); a daily detection has `observed_at = date + 08:00Z`.

**Grids.** Raster data is an `xarray.Dataset` with dims `(time, lat, lon)`, 1-D regular `lat`/`lon` coordinates in WGS84 (≈0.01° from Earth Engine), and attrs `source`, `ee_id`, `fetched_at`, `mode`. Variable names and units: `no2` (mol/m²), `so2` (mol/m²), `ch4` (ppb), `cloud_fraction` (0–1), `aer_ai` (unitless), `valid` (bool mask where the product's QA passes). Missing data is NaN, never 0.

**Wind.** `clients/wind.py:get_wind(points, times) -> xarray.Dataset` with `u`, `v` (m/s), `speed`, `dir_from_deg`, and attrs `source`, `level` (e.g. `100m`), `uncertainty_frac`. Providers are tried in the order of `wind.chain` in settings; the result records which one answered.

**Buffer time series.** `clients/ee_client.py:get_buffer_timeseries(units, start, end, product, radius_km) -> DataFrame[unit_id, date, mean, n_valid, n_total, cloud_mean]`, chunked by quarter, retrying with exponential backoff, cached as parquet.

**WatchUnit** (`schemas.py`): `id, kind ('facility'|'cluster'), name, lon, lat, member_ids: list[int], capacity_mw`. A unit is an isolated facility, or a cluster of facilities within `registry.cluster_radius_km`. Detection, attribution and emission rates operate on units.

**Detection** (`schemas.py`):

| Field | Meaning |
|---|---|
| `detector` | `no2`, `so2`, `ch4`, `flare`, `thermal`, `smoke` |
| `observed_at` | UTC datetime |
| `watch_unit_id` | nullable (thermal points have none) |
| `facility_id` | nullable, set only when attribution allows |
| `geom`, `footprint` | GeoJSON point / polygon |
| `value`, `unit` | measurement and its unit |
| `z_bg` | z against the null-buffer distribution (see Phase 4) |
| `z_self` | z against the unit's own history, nullable |
| `class_label`, `class_prob` | thermal / smoke class |
| `score`, `score_parts` | uncalibrated score in [0, 1] and `{signal_quality, attribution_certainty, anomaly_strength}` |
| `qa` | json: cloud, valid fraction, wind source/level/speed, aer_ai, `retrieval_degraded`, `window_days`, … |
| `is_stub` | true if produced by a stub or fallback |
| `natural_key` | `sha1(f"{detector}\|{watch_unit_id or '-'}\|{observed_at:%Y-%m-%dT%H}\|{lon:.4f}\|{lat:.4f}")`, UNIQUE |
| `raw_ref` | pointer to the source product |

Repositories upsert on `natural_key`, so re-running the previous five days never creates duplicates (this replaces the v1 key `(detector, facility, observed_at)`, which Postgres does not enforce when `facility_id` is NULL).

**LayerProduct** (`schemas.py`): `{layer, date, data_ref, legend}`; returned by layer-only detectors (CH4).

**Event**: `id, start_at, end_at, geom, watch_unit_id, facility_id (nullable), attribution_level ('facility'|'cluster'|'ambiguous'), attribution_margin, candidates (ranked json), detection_ids, score, score_parts, status ('open'|'contested'|'rejected_crop_burning'|'confirmed'), anomaly_strength, reassigned_from (nullable), summary json`.

**Wording.** Strings such as the report disclaimer, the label "score (uncalibrated)", the exposure caption and the evidence-chip captions come from `config/wording.yaml` via `app/wording.py:t(key)`.

### 0.7 Schema (Phase 1 creates; later phases only add columns they need)

| Table (kind) | Key columns |
|---|---|
| `facilities` (derived) | id, name, operator, type (coal_power, steel, cement, refinery, smelter, other), capacity_mw, geom POINT, footprint POLYGON nullable, watch_unit_id, sources jsonb, source_ids jsonb |
| `watch_units` (derived) | id, kind, name, geom POINT, member_ids int[], capacity_mw, region |
| `detections` (derived) | id, natural_key UNIQUE, detector, observed_at, watch_unit_id nullable, facility_id nullable, geom POINT, footprint POLYGON nullable, value, unit, z_bg, z_self, class_label, class_prob, score, score_parts jsonb, qa jsonb, is_stub bool, raw_ref |
| `events` (derived) | fields in §0.6, plus created_at, updated_at |
| `emission_estimates` (derived) | id, watch_unit_id, species (NO2/NOx, SO2), season (`all`, `DJF`, `MAM`, `SON`), period_start, period_end, status (`ok`, `insufficient_data`, `contaminated`), rate_kg_s, stat_low, stat_high, rate_low, rate_high (total, includes wind term), wind_sigma_frac, lifetime_h, n_days, method, reference_value, reference_source, caveats jsonb |
| `baseline_predictions` (derived) | watch_unit_id, date, observed, expected, residual, residual_z, is_oof bool, model_version |
| `anomalies` (derived) | id, watch_unit_id, date, residual_z, direction (high/low), matched_known_event nullable |
| `exposures` (derived) | event_id, plume_geom, method (`observed`, `wedge`), population_raw, population_weighted, schools, hospitals, villages, site_list jsonb |
| `layer_cache` (derived) | layer, date, ee_map_id, tile_url, expires_at |
| `watchlists` (**user**) | id, email, name, geom POLYGON, species text[], min_score, created_at, confirmed_at nullable, confirm_token, ip_hash |
| `alert_deliveries` (**user**) | id, watchlist_id, event_id nullable, anomaly_id nullable, email, sent_at, status, error; unique per (watchlist, event) and (watchlist, anomaly) |

### 0.8 What v2 changed (review issue → fix → phase)

| # | Issue found in v1 | Fix in v2 | Phase |
|---|---|---|---|
| 1 | Real data first touched in Phase 13 | Spike + recorded real fixtures; Phase 4/5A acceptance on real data; `make slice`; decision gates | S, 4, 5A |
| 2 | Pixel z-score finds "a plant is hotter than countryside"; correlated pixels make z overconfident | Null-buffer z (resampled equal-size buffers), plus `z_self` against the unit's own seasonal history; events need both | 4, 8 |
| 3 | Asset-centric detection and upwind cone could disagree in a cluster | Watch units (clusters); attribution margin; reassignment; `attribution_level` | 3, 5A |
| 4 | 10 m ERA5-Land wind; unknown latency of ERA5 copies | Wind provider chain chosen in the spike; wind uncertainty term; wind source recorded | S, 2, 5B |
| 5 | Circular synthetic test; weekly rates; band understated | Independent puff forward model; seasonal/annual estimates with `min_days`; block bootstrap + wind term; Beirle live acceptance | 2, 5B, 13 |
| 6 | Thermal model learned its own weak labels | Label-blind features, independent evaluation set (MODIS burned area + hand-checked), rules-only baseline, `persistent_other` class | 6 |
| 7 | Binary crop-burning rejection | `contested` status; reject only if facility is not anomalous on its own; aerosol-index flag | 4, 5A |
| 8 | Smoke CNN presented as proof (steam, timing, stub 0.5) | 3 classes (none/steam/smoke), time offset shown, evidence level, stubs excluded | 7, 11, 12 |
| 9 | Baseline validated on training data (COVID 2020 in train) | Known-event windows masked from training; out-of-fold historical predictions; optional generation covariate; calibration | 8 |
| 10 | Noisy-OR inflated scores; one number for three questions | Three-part score, geometric mean, corroboration by independent detector type, uncalibrated until `calibration.json` | 4, 5A, 8 |
| 11 | Exposure wedge too large and worded as "exposed" | Observed footprint preferred; 15° wedge, 30 km max; raw and distance-weighted counts; caption | 9 |
| 12 | UTM 44N hard-coded (Delhi is zone 43); NULL keys duplicate; gitignored plan; CH4 rule conflict; resetdb wiped user data; open admin endpoint; unverified emails; EE quota; legal wording | `local_aeqd`; `natural_key`; plan in `docs/`; `LayerProduct`; derived/user tables; admin token; double opt-in; batched series; `wording.yaml` | 1, 2, 10, 12 |
| 13 | Phase days summed to 41.75 but the plan claimed 39.25 | Phases S–13 sum to exactly 49.0 and match the Word plan | all |
| 14 | (v2.1) Nightfire needs a data-use licence and scripted access is paid; v2 assumed a free scripted download | `flaring.source` with `annual_sites`, `firms_persistent` and optional `nightfire`; Nightfire not required by any phase; no effort change | 0, S, 2, 4 |

### 0.9 Decision gates

| Gate | When | Look at | Decide |
|---|---|---|---|
| G1 | End of Phase S | `SPIKE_REPORT.md`: valid-day fraction per month, wind latency, SO2 window z for the main plants, quota test | Pick the wind chain; if SO2 window z < 2 for the known big plants, show SO2 as a regional layer only and move #2 to the trim list; if valid days in Oct–Mar < 40 %, widen windows (config) |
| G2 | End of Phase 4 | Rate of detections vs. events on 120 real days | Tune thresholds in config only; if more than 1 event per unit per week survives the gate, raise `z_self_min` |
| G3 | End of Phase 5B | Rate recovery table, Beirle comparison | If the total band excludes the catalogue value for most sources, publish rates as "order of magnitude" in the UI |
| G4 | End of Phase 8 | Out-of-fold anomaly validation | If known-event hit rate is below 50 % or false alarms exceed 1 per unit per month, raise thresholds and say so in README |
| G5 | Day −7 before demo | `make accept-real` | Freeze scope; only fixes |

### 0.10 `config/settings.yaml` (created in Phase 1 with these defaults; values are tuned only through the gates)

```yaml
region:
  name: singrauli
  bbox: [82.0, 23.6, 83.4, 24.8]       # lon_min, lat_min, lon_max, lat_max — verify in Phase S
  geojson: config/regions/singrauli.geojson
registry:
  cluster_radius_km: 15
  dedupe_threshold: 0.75
  dedupe_max_km: 3
detect:
  local_radius_km: 5
  null_annulus_km: [20, 50]
  null_mask_km: 15            # exclude null buffers near any registered facility
  n_null: 40
  n_null_min_valid: 20
  z_bg_min: 2.0
  valid_fraction_min: 0.5
  cloud_max: 0.3
  aer_ai_degraded: 1.0
  self_min_days: 20
  self_season_days: 45
  self_trailing_days: 90
  z_self_min: 2.0
  so2_window_days: 28
  so2_min_valid_days: 10
  so2_boot: 200
flaring:
  source: firms_persistent       # annual_sites | firms_persistent | nightfire (nightfire needs a licence)
  radius_km: 2
  min_nights: 3
  window_days: 30
  min_frp_mw: 5                  # firms_persistent only; tune from the spike's real counts
  nightfire_temp_k: 1400         # nightfire only
  annual_site_match_km: 1        # a detection within this distance of an annual flare site is flagged known_flare_site
wind:
  chain: [cds_era5_100m, gfs_ee, era5_land_10m_ee]   # final order set by Phase S
  level: 100m
  uncertainty_frac: {cds_era5_100m: 0.25, gfs_ee: 0.30, era5_land_10m_ee: 0.35}
  min_speed_ms: 1.5
  max_speed_ms: 10
attribute:
  cone_half_angle_deg: 30
  transport_hours: 3
  cone_max_km: 50
  margin_min: 0.25
fusion:
  event_gap_hours: 48
  corroboration_bonus: 0.05
  corroboration_max: 0.10
  score_cap: 0.95
  burn_prob_min: 0.6
  burn_frp_min_mw: 50
  burn_window_hours: 24
score:
  weights: {signal_quality: 1.0, attribution_certainty: 1.0, anomaly_strength: 1.0}
  neutral_anomaly: 0.5
emission:
  wind_min_ms: 2
  wind_max_ms: 8
  min_days: 60
  n_boot: 200
  boot_block_days: 7
  across_km: 20
  nox_no2_ratio: 1.32
  seasons: {DJF: [12, 1, 2], MAM: [3, 4, 5], SON: [10, 11]}   # JJAS monsoon excluded
  reference_match_km: 10
baseline:
  train_end: 2024-12-31
  valid_year: 2025
  rolling_z_days: 60
  alert_z: 3.0
  alert_k: 2
  alert_n: 5
  alert_calendar_days: 14
  known_event_pad_days: 7
impact:
  wedge_half_angle_deg: 15
  wedge_max_km: 30
  decay_km: 15
thermal:
  ship_margin_f1: 0.03
schedule:
  daily_tz: Asia/Kolkata
  daily_time: "15:00"
  rerun_previous_days: 5
  firms_every_hours: 3
  emission_refresh: monthly
alerts:
  max_watchlists_per_email: 5
  max_watchlists_per_ip_per_day: 20
  demo_auto_confirm: false
```

---

## Phase 0 — 👤 Accounts, downloads, decisions (before any coding)

| Task | Detail |
|---|---|
| Earth Engine | Google Cloud project, enable the Earth Engine API, register it for non-commercial use, create a service account with Earth Engine access, download the JSON key → `secrets/ee-key.json`. Note the quota tier shown in the console. |
| CDS (ERA5) | Create a Copernicus Climate Data Store account and API key (`~/.cdsapirc` or `.env`). Needed for 100 m winds of the history. |
| FIRMS | Free MAP_KEY at firms.modaps.eosdis.nasa.gov/api. |
| VIIRS Nightfire (optional, does not block anything) | Create a free EOG account at eogdata.mines.edu and **apply for the VIIRS Nightfire Data Use License** (no-cost one-year academic licence via the Payne Institute licensing page; approval can take days; email eog@mines.edu if you are unsure which tier applies). Since 1 June 2026 *scripted* access needs a paid subscription (`EOG_CLIENT_ID` / `EOG_CLIENT_SECRET`), so leave the EOG variables blank in `.env` unless you buy one. After approval, download a few nightly files by hand in the browser and note which versions and dates work. |
| Flare site files | Download the World Bank GFMR flare-location Excel file (2012–2025) and/or EOG's annual flare files (Excel or KML) into `data/registry/raw/flares/`. Open the file and check whether it has rows near your region; if it does not, `annual_sites` is simply empty and `firms_persistent` carries flaring. |
| SMTP | MailHog locally (Docker). For the demo, a Gmail app password or any SMTP relay. |
| Live-watch region | **Singrauli** (dense coal cluster, clean SO2 signal, little crop burning). **Delhi-NCR** is the "contested / rejected crop-burning" showcase in Oct–Nov; it needs its own region file and is a *second* region config, not a code change. |
| Registry downloads | Place WRI GPPD, Global Energy Monitor trackers (coal plant, steel, cement) and Climate TRACE files in `data/registry/raw/`. |
| Known events | Start `data/known_events.csv` (watch unit or facility, start, end, type `outage|commissioning|lockdown|other`, direction `low|high`, source URL). **Collect at least 15 rows** (plant or unit outages from news and regulator reports, commissioning dates, the 2020 lockdown). Phase 8 reports hit rate and false-alarm rate, and fewer than about 15 rows makes those numbers indicative only. |
| Plant generation (optional, high value) | Look for daily plant-wise generation or load factor (for example CEA or Grid-India daily generation reports) and save `data/covariates/generation.csv` with columns `facility_name, date, generation_mwh`. Emissions follow generation, so this is the strongest covariate for Phase 8. |
| Team split | Owners for parallel tracks in §0.2. |

---

## Phase S — Real-data spike and recorded fixtures (new, 1.0 day)

**Goal:** find out, before building anything on top, what real Earth Engine data looks like for Singrauli, and record a real fixture slice. The result is `docs/SPIKE_REPORT.md`, which every later phase treats as the source of truth for asset IDs, bands, latency and thresholds.

**Inputs:** Phase 0 credentials.

**Files:** `scripts/spike_ee.py`, `scripts/make_fixtures.py`, `docs/SPIKE_REPORT.md` (template written by Claude Code, filled by the script), `tests/fixtures/real_singrauli/`.

**Tasks**
1. Claude Code writes `scripts/spike_ee.py` (runs live, 👤 you execute it with credentials). It must:
   - For every collection used (S5P OFFL and NRTI NO2/SO2/CH4/AER_AI, ERA5-Land hourly, ERA5 hourly, GFS 0.25°, Sentinel-2 SR harmonized, WorldCover, WorldPop) print: whether the asset id resolves, its band names, the most recent available date (= latency), and the native scale.
   - For the S5P collections, state whether QA filtering is already applied in the Level-3 product and which QA/cloud bands exist.
   - For wind: list which wind heights exist in each collection; compare 10 m and the best higher level at the Singrauli plants; record the ratio of mean speeds.
   - Pull 120 days of NO2 and 28-day SO2 for a 60 km window around the Singrauli centroid; report per month the fraction of days with ≥ 50 % valid pixels (this quantifies cloud, haze and monsoon loss).
   - Run a rough prototype of the Phase 4 null-buffer test on those 120 days and report: days with `z_bg ≥ 2`, typical `local − null_median`, and the SO2 window bootstrap z for the biggest plants.
   - Time 100 small `reduceRegions` calls and one quarter-long batched call; report seconds and any quota error text.
   - Check FIRMS (VIIRS SNPP and NOAA-20, last 90 days): count night-time detections within 2 km of each registered facility. Check that the annual flare files are present in `data/registry/raw/flares/` and report how many flare sites fall inside the region. Nightfire is **not** tested by the script (scripted access is paid); 👤 you record in the report which Nightfire versions and dates you could download by hand, or "no licence yet".
2. The script writes the **decisions table** in `docs/SPIKE_REPORT.md`: wind chain order, NRT strategy for "today", history strategy, `valid_fraction_min` suggestion, whether SO2 passes gate G1, and the flaring source (`annual_sites` / `firms_persistent` / `nightfire`) with the number of annual flare sites in the region.
3. `scripts/make_fixtures.py --unit singrauli --days 120` records a real slice (NO2, SO2, cloud, AER_AI, winds from the chosen provider, FIRMS, annual flare sites, OSM objects, S2 chips for 3 dates; Nightfire files only if you have downloaded some) into `tests/fixtures/real_singrauli/` as NetCDF/parquet/CSV/GeoJSON (< 50 MB total; downsample if needed). 👤 You run it once.
4. Claude Code writes `tests/test_fixture_integrity.py` that loads the real slice and checks dims, units, NaN handling and time zones.

**Done when:** the report exists with every table filled; gate G1 decided and written at the bottom of the report; `tests/fixtures/real_singrauli/` committed; fixture integrity test passes.

**Prompt:** *"Read docs/IMPLEMENTATION_PLAN.md Phase S. Write scripts/spike_ee.py, scripts/make_fixtures.py, the SPIKE_REPORT.md template and the fixture integrity test. Do not guess any Earth Engine id or band: the script must discover them. Stop after writing the code; I will run the scripts with credentials and paste the report back."*

---

## Phase 1 — Repo skeleton, Docker, database

**Goal:** `make up` starts PostGIS, API, worker, web and MailHog; `make initdb` creates the schema; `make test` runs; CI passes.

**Tasks**
1. Layout from §0.3, `CLAUDE.md` exactly as delivered, `.env.example` (all keys, including `ADMIN_TOKEN`, `CDS_*`, `DATA_MODE`), `config/settings.yaml` from §0.10, `config/wording.yaml` (disclaimer, score label, exposure caption, evidence captions; short sentences, English), `docs/PROGRESS.md` (empty log), `.gitignore` (secrets, `.env*`, caches, `models/*` except stubs, `data/cache`, `data/demo`; **not** `docs/`).
2. `docker-compose.yml`: `postgis/postgis:16-3.4`, `api` (uvicorn), `worker` (same image, scheduler), `web` (Vite dev server), `mailhog`.
3. Root `pyproject.toml` with the Phase 1 set from §0.5, pytest and ruff config, markers `live` (skipped unless `RUN_LIVE=1`).
4. SQLAlchemy models in `app/models.py` for every table in §0.7, tagged `info={"kind": "derived"|"user"}`; `app/db.py:init_db()` (PostGIS extension + `create_all`), `reset_db(all=False)` that drops derived tables only unless `all=True`. `make resetdb` / `make resetdb ALL=1`. Add `make dump-user` / `make restore-user` (JSON dump of watchlists).
5. `app/schemas.py`: `Detection`, `LayerProduct`, `Event`, `EmissionEstimate`, `Exposure`, `Facility`, `WatchUnit` exactly as in §0.6, including `natural_key()` helper and its unit test.
6. `app/geo/projection.py:local_aeqd(lon, lat)` returning a pyproj transformer pair (WGS84 ↔ local azimuthal equidistant). Test: 10 km east at 24°N and at 28.6°N differ < 0.5 % from true distance.
7. `app/wording.py:t(key)` reading `wording.yaml`; test that every key used in code exists.
8. `/health` and `/region` endpoints; admin dependency `require_admin` (header `X-Admin-Token` equals `ADMIN_TOKEN`, constant-time compare); GitHub Actions running `ruff`, `pytest` (PostGIS service) and the web build.
9. `web/`: Vite React TS app with a full-screen MapLibre map fitted to the region bbox from `GET /region` (OSM raster basemap); error state if the API is down.

**Done when:** `make up && make initdb && make test` succeeds; `GET /health` → 200; browser shows the map; `make resetdb` keeps a test row in `watchlists` and `make resetdb ALL=1` removes it (test).

**Prompt:** *"Read docs/IMPLEMENTATION_PLAN.md §0 and Phase 1. Do Phase 1 completely, create CLAUDE.md as delivered, then update docs/PROGRESS.md. Show me the output of `make lint test`."*

---

## Phase 2 — Data access layer, wind providers, fixtures (Arch 7)

**Goal:** one Python interface for every data source, working in `live`, `fixture` and (Phase 13) `replay` mode, with a cache and without per-day Earth Engine loops.

**Inputs:** `docs/SPIKE_REPORT.md` (asset ids, bands, wind chain), `tests/fixtures/real_singrauli/`.

**Tasks**
1. `clients/ee_client.py` (initialise with the service account) — functions return xarray / DataFrames clipped to an AOI. Asset ids and band names come **only** from the spike report (store them in `config/sources.yaml`, generated from it):

| Function | Returns |
|---|---|
| `get_no2(aoi, start, end)` | `no2`, `cloud_fraction`, `valid` |
| `get_so2(aoi, start, end)` | `so2`, `valid` |
| `get_ch4(aoi, month)` | `ch4` monthly |
| `get_aerosol_index(aoi, start, end)` | `aer_ai` (UV aerosol index; flags smoke/haze days) |
| `get_s2_chip(point, date, size_px=128)` | 6-band chip, SCL cloud mask, **acquisition time** |
| `get_worldcover(aoi)`, `get_ndvi(aoi, date)` | land cover / vegetation |
| `get_burned_area(aoi, start, end)` | MODIS burned-area product (used for thermal evaluation) |
| `get_population(geom)` | WorldPop sum |
| `get_tile_url(layer, date)` | XYZ tile URL |
| `get_buffer_timeseries(units, start, end, product, radius_km)` | **batched** table per §0.6 |

   Use small AOIs (≤ 60 km) and `reduceRegions` for tables. Never loop per day or per facility over EE calls for history. Retry 429/5xx with exponential backoff and jitter; surface the quota error text.
2. `clients/wind.py:get_wind(points, times)` — provider chain from `settings.wind.chain`. Providers: `cds_era5_100m` (history; batched CDS download, cached NetCDF), `gfs_ee` (near-real-time), `era5_land_10m_ee` (fallback). Each returns `u, v, speed, dir_from_deg` and attrs `source`, `level`, `uncertainty_frac`. If the first provider has no data for a time, the next answers and the result says so. Never silently return a wind of a different level without the attrs.
3. `clients/firms.py` (VIIRS SNPP/NOAA-20 NRT, SP for history), `clients/flares.py`, `clients/nightfire.py` (optional), `clients/osm.py` (industrial, power, chimney, schools, hospitals, villages) — with caching and rate-limit handling.
   - `clients/flares.py` exposes one interface over three sources chosen by `flaring.source`: `annual_sites` (loads the GFMR / EOG annual Excel or KML files into a GeoDataFrame of flare sites with annual volume), `firms_persistent` (night-time FIRMS 375 m detections near facilities, via `clients/firms.py`), and `nightfire` (reads nightly Nightfire CSVs from `data/raw/nightfire/` if you placed any there, or downloads them only when `EOG_CLIENT_ID` and `EOG_CLIENT_SECRET` are set; otherwise it reports "unavailable" and the caller falls back).
   - `clients/nightfire.py` must never fail the pipeline when credentials or files are missing.
4. Cache: every live call writes `data/cache/<source>/<key>.{nc,tif,parquet}` and reads it first.
5. `DATA_MODE=fixture` reads `tests/fixtures/` (the real Singrauli slice **and** small synthetic arrays).
6. `tests/synthetic.py`:
   - `make_correlated_background(shape, pixel_km, corr_len_km, sigma)`;
   - `inject_plume(field, src_xy, rate_kg_s, wind_series, lifetime_h, pixel_km, model="puff")` — a Lagrangian puff model (puffs released hourly, advected by the wind series, Gaussian growth, first-order decay), **not** the closed-form fit model;
   - `apply_footprint(field, pixel_km=(5.5, 3.5))` — blur to the TROPOMI footprint;
   - `add_missing(field, frac, coherent=True)` — cloud-like gaps;
   - `add_neighbour_source(...)`.

**Tests:** every client in fixture mode; wind chain falls through to the next provider; caching round-trip; synthetic background has the requested correlation length; puff mass balance (emitted mass ≈ integrated column + decayed mass, within 5 %).

**Done when:** all client tests pass in fixture mode; `python -m app.clients.ee_client --smoke` and `python -m app.clients.wind --smoke` work in live mode (👤 with keys); `get_buffer_timeseries` returns one quarter for 20 units in one call in live mode.

**Prompt:** *"Do Phase 2 of docs/IMPLEMENTATION_PLAN.md using docs/SPIKE_REPORT.md for every asset id. Build the clients, the wind provider chain, batched buffer time series, and the puff-model synthetic helpers with tests. No network calls in tests."*

---

## Phase 3 — Facility registry and watch units (#16)

**Goal:** one de-duplicated table of industrial sites, grouped into watch units.

**Tasks**
1. `clients/registry_sources.py` loaders for GPPD, GEM trackers, Climate TRACE and OSM (files in `data/registry/raw/`); normalise to `(name, operator, type, capacity, lat, lon, source, source_id)`.
2. `registry/dedupe.py`: candidate pairs within `dedupe_max_km`; score = 0.6 × name similarity (rapidfuzz `token_set_ratio`) + 0.4 × distance score; merge above `dedupe_threshold`. Keep all source ids. Prefer coordinates GEM > GPPD > Climate TRACE > OSM.
3. Footprints from OSM industrial polygons; chimney points kept for Phase 7.
4. `registry/units.py`: connected components of facilities within `cluster_radius_km` → `watch_units` (kind `facility` if alone, `cluster` otherwise; centroid = capacity-weighted mean; name from the largest member + "complex"). Write `facilities.watch_unit_id`.
5. `make seed` loads the region; prints counts per source, merges, number of units by kind.
6. API: `GET /facilities?bbox=`, `GET /facilities/{id}`, `GET /watch-units?bbox=`.

**Tests:** two near-duplicates merge; two distinct plants 2 km apart do not; five plants within 15 km form one cluster unit and an isolated plant stays a facility unit; the Singrauli fixture yields one cluster with ≥ 5 members.

**Done when:** tests pass; real seed for Singrauli loads (expect a few dozen sites and 1–3 clusters); 👤 you open the result on the map once and confirm the big plants are present.

**Prompt:** *"Do Phase 3 of docs/IMPLEMENTATION_PLAN.md: registry, de-duplication and watch units, with fixture CSVs in tests and a seed command for real files."*

---

## Phase 4 — Gas detectors, flaring, score (#1, #2, #3, #5, #21)

**Goal:** per-unit observations from TROPOMI and the configured flare source that distinguish *unusual for this unit* from *a power plant is a power plant*, each with a three-part score.

**Inputs:** Phases 2 and 3; real fixture slice.

**Tasks**
1. **Null-buffer test** (`detect/null_buffers.py`). For a unit and day: `local` = mean of valid pixels within `local_radius_km` (for a cluster: the union of member buffers). Draw `n_null` random centres in the annulus `null_annulus_km`, rejecting centres within `null_mask_km` of any registered facility, buffers with too few valid pixels, and (for the per-day test) cloudy pixels. Compute the same-size buffer mean at each centre. `z_bg = (local − median(null)) / (1.4826·MAD(null))`. Require ≥ `n_null_min_valid` valid null buffers. This keeps spatial correlation inside the null distribution, so the z-score is not overconfident. Seed the random draw from `(unit_id, date)` so results are reproducible.
2. **#1 NO2** (`detect/no2.py`): detection if `z_bg ≥ z_bg_min`, valid fraction ≥ `valid_fraction_min`, cloud ≤ `cloud_max`. Footprint = connected pixels above `null_median + 2σ_null` touching the buffer. **Also compute `z_self`:** `d = local − null_median`; history = the unit's `d` values for days within ±`self_season_days` of the same day of year in earlier years if ≥ `self_min_days` exist, else the trailing `self_trailing_days`; `z_self = (d − median(hist)) / (1.4826·MAD(hist))`. If history is too short, `z_self = None` and `qa.gate_degraded = true`. Add `qa.retrieval_degraded` when the mean `aer_ai` within 20 km exceeds `aer_ai_degraded`. A detection with `z_bg ≥ z_bg_min` but `z_self < z_self_min` is stored with `qa.routine = true` (the plume is normal for this unit); only non-routine detections can start events.
3. **#2 SO2** (`detect/so2.py`): SO2 is too noisy daily. For each unit use a rolling `so2_window_days` window: rotate each valid day so the wind points along +x (`geo/rotation.py:rotate_field`, shared with Phase 5B), average, and compute downwind enhancement (mean of the box 0–30 km downwind × ±10 km across) minus the upwind box. Bootstrap the valid days `so2_boot` times. `z = mean/std`; detect if `z ≥ z_bg_min` and the 5th percentile > 0 and valid days ≥ `so2_min_valid_days`. `observed_at` = window end, `qa.window_days`, `qa.kind = "window"`. SO2 detections **corroborate** events; they do not create events (they cannot be dated to one day).
4. **#3 CH4** (`detect/ch4.py`): monthly anomaly = month mean − 12-month regional median; returns a `LayerProduct`. *(Optional trim.)*
5. **#5 Flaring** (`detect/flaring.py`, build it last in this phase) with the source set by `flaring.source`:
   - `firms_persistent` (default): night-time FIRMS 375 m detections with FRP ≥ `min_frp_mw` within `radius_km` of a unit's facility on ≥ `min_nights` of `window_days`. Intensity = FRP (MW). It cannot give a flame temperature (the 375 m channel saturates), so `qa.temperature_known = false`.
   - `nightfire` (optional upgrade, only when files or credentials exist): points ≥ `nightfire_temp_k` within `radius_km`, same persistence rule; intensity = radiant heat. Select it with one config change; the interface is identical.
   - `annual_sites`: loads the annual flare-site files as a static layer and **prior**. A flare detection within `annual_site_match_km` of a known site gets `qa.known_flare_site = true`; a site is never reported as an active flare on its own.
   - Land sites only. These FIRMS pixels are also the raw input of the thermal classifier (Phase 6); fusion must not count a flare detection and a thermal detection of the same pixel as two independent detector types.
6. **#21 Score** (`detect/confidence.py`): `score_parts = {signal_quality, attribution_certainty, anomaly_strength}`, each in [0, 1].
   - *signal_quality*: z margin `clip((z_bg − z_min)/z_min, 0, 1)`, valid fraction, cloud, number of valid overpasses (windows), minus a penalty for `retrieval_degraded`.
   - *attribution_certainty*: wind-speed band (penalise below `wind.min_speed_ms` and above `wind.max_speed_ms`); the cone margin is added in Phase 5A. Until then it is the wind part only.
   - *anomaly_strength*: `clip((z_self − z_self_min)/4, 0, 1)`; if `z_self` is None use `score.neutral_anomaly` and set `qa.gate_degraded`.
   - `score` = weighted geometric mean of the three parts (weights in config). Return the parts so reports can show them. The word "confidence" is not used in code or UI; use `score`.
7. Persist via `repositories/detections.py:upsert_detections` (ON CONFLICT `natural_key`). Re-running a date, or the previous five days, produces no duplicates (test).

**Tests (CI):**
- Injected puff-model plume next to the fixture unit → NO2 fires with `z_bg ≥ 2` and `z_self` high; no plume → no detection.
- **False-positive rate:** 1000 days of spatially correlated noise (correlation length 10 km) with no source → fraction with `z_bg ≥ 2` is between 1 % and 5 %. (This test is what the old pixel-wise z-score would fail.)
- A constant source with a stable plume for two years → `routine = true` and no event-eligible detection.
- Cloudy fixture → no detection; high-aerosol day → `retrieval_degraded`.
- SO2 window: injected constant source detected; pure noise rejected with FP rate < 10 % over 300 windows.
- Flaring persistence rule for each source (3-of-30 nights accepted, 2-of-30 rejected); the `nightfire` source returns "unavailable" cleanly with no files or credentials and the caller falls back; a detection near an annual site sets `known_flare_site`; each score part is monotonic.
- Idempotent upsert; `natural_key` stable.

**Real-data acceptance (👤 + Claude Code, gate G2):** run on the 120-day real Singrauli slice. Report: days observed, days with `z_bg ≥ 2`, days non-routine, fraction of routine detections, SO2 window z for the main units. Save the table in `PROGRESS.md`.

**Done when:** CI tests green; `python -m app.jobs.pipeline --detectors gas --date <fixture date>` writes detections in fixture mode; the real-data table exists and gate G2 is decided.

**Prompt:** *"Do Phase 4 of docs/IMPLEMENTATION_PLAN.md exactly as specified: null-buffer z, z_self, SO2 window bootstrap, flaring, three-part score, idempotent upsert, all thresholds from config. Include the false-positive-rate test. Then run the real-fixture acceptance and report the table."*

---

## Phase 5A — Attribution, fusion, first end-to-end slice (#17, Arch 3)

**Goal:** every non-routine detection points to a unit with a stated certainty; detections merge into events; the first end-to-end slice runs on **real** data.

**Tasks**
1. **#17 Upwind cone** (`attribute/upwind_cone.py`): from the footprint centroid (or unit centroid), take wind from `get_wind` at the overpass time (level and source recorded). Cone half-angle `cone_half_angle_deg`, length `min(speed × transport_hours, cone_max_km)`. Candidates = facilities of **all** units inside the cone or the buffer. Rank by `angle_offset/half_angle + distance/length` (lower is better). `attribution_margin = (r2 − r1)/r2` (1.0 if one candidate). Store the cone polygon and the ranked list.
2. **Attribution level:**
   - top candidate's unit ≠ detecting unit and margin ≥ `margin_min` → **reassign** the event to that unit, set `reassigned_from`, and mark the original detection `qa.contaminated_by`;
   - margin ≥ `margin_min` and the unit is a single facility → `attribution_level = facility`;
   - candidates all inside one cluster with margin < `margin_min` → `cluster` (UI says "Singrauli complex", lists members);
   - candidates from different units with margin < `margin_min` → `ambiguous` and status `contested`.
3. **Fusion** (`attribute/fusion.py`): non-routine NO2 and flare detections of one unit within `event_gap_hours` → one event. SO2-window, smoke and thermal detections attach as corroborators. Event `score`: the maximum detection score plus `corroboration_bonus` for each *additional independent detector type* (NO2, SO2, flare, smoke), capped by `corroboration_max` and `score_cap`; repeated days of the same detector add nothing. Update `attribution_certainty` with the cone margin and recompute the score. Missing `z_self` keeps `gate_degraded`.
4. **Crop-burning logic** (needs Phase 6; implement the rule now, test it with synthetic thermal detections): within the upwind cone and ±`burn_window_hours`, sum the FRP of thermal detections classed `crop_burning` with prob ≥ `burn_prob_min`. If the sum ≥ `burn_frp_min_mw`:
   - facility is *not* unusual on its own (`z_self < z_self_min`) → `rejected_crop_burning`;
   - `z_self ≥ z_self_min` or unknown → `contested` (shown with both signals, never rejected).
   Smoke detections with `evidence_level = same_day` and `is_stub = false` add a corroboration bonus; stubs add nothing.
5. API: `GET /events?bbox=&from=&to=`, `GET /events/{id}`.
6. **`make slice DATE=...`:** on the real Singrauli slice, runs ingest → detect → attribute → fuse and prints a table of events (unit, level, margin, score parts, status) and writes `slice.png` (a static map of units, cone, events). This is the first time real data flows through the whole chain.

**Tests:** cone picks the upwind plant and not the closer downwind one; a detection at unit A caused by an upwind unit B is reassigned to B; a cluster with a small margin yields `cluster`; repeated daily NO2 detections do not push the score above the single-day maximum plus corroboration; crop-burning rule: not-anomalous facility → rejected, anomalous facility → contested; stub smoke adds nothing.

**Done when:** CI green; `make slice` prints a sensible event table for the real slice and the PNG shows cones pointing from the plumes to the right units (👤 you eyeball the image); fixture pipeline produces events with unit, level, cone and score parts.

**Prompt:** *"Do Phase 5A of docs/IMPLEMENTATION_PLAN.md: cone attribution with margins and reassignment, fusion with corroboration instead of noisy-OR, the contested/rejected crop-burning rule, and `make slice` on the real fixture slice."*

---

## Phase 5B — Emission rates with honest uncertainty (#18)

**Goal:** a per-unit emission rate whose band includes the dominant systematic term, produced only when there is enough data.

**Tasks** (`attribute/emission.py`, `geo/rotation.py`)
1. For a unit and a period (rolling 365 days, and each season in `emission.seasons`; the monsoon is excluded): keep valid days with wind between `wind_min_ms` and `wind_max_ms`. If fewer than `min_days` remain → store `status = insufficient_data` and **no rate**.
2. Rotate each day's field around the unit centroid so the wind points along +x; average; integrate across-wind (±`across_km`) to get the line density along wind.
3. Fit an exponentially modified Gaussian with `scipy.optimize.curve_fit` → total mass `A` and e-folding distance `x₀`. Lifetime `τ = x₀ / mean wind`, rate `E = A / τ`. NO2 → NOx with `nox_no2_ratio`. Convert mol/m² to kg. Fit τ separately per season.
4. **Uncertainty:** block bootstrap of the days (blocks of `boot_block_days`, `n_boot` times) → `stat_low`/`stat_high` (5th–95th percentile). Add the wind term: relative wind uncertainty from the wind provider (`wind.uncertainty_frac`) in quadrature → `rate_low`/`rate_high` (**total** band). The API and UI show the total band; statistical-only appears as a labelled secondary value.
5. **Contamination check:** if another unit lies within 2 × `across_km` of the centroid and inside the integration region, set `status = contaminated` and add a caveat (the Beirle method assumes an isolated source). Clusters are treated as one source (the unit centroid).
6. **Validation:** compare with the Beirle NOx catalogue (NO2) and NASA MSAQSO2L4 (SO2) when a catalogue source lies within `reference_match_km`; store `reference_value`, `reference_source`.
7. API: `GET /watch-units/{id}/emissions`.

**Tests (CI):** use the independent puff-model generator with TROPOMI blur, correlated noise, 40 % coherent missing days, wind error of 25 %, a background gradient and, in one scenario, a neighbour source at 15 km.
- Isolated source, 20 random seeds: median bias within ±30 %, **total band** contains the true rate in ≥ 80 % of seeds.
- Fewer than `min_days` valid days → `insufficient_data`, no rate.
- Neighbour source → `contaminated` caveat present.
- Wind bias of +30 % is reflected in the output bias (the test documents it rather than hiding it).

If the targets are not met after reasonable tuning of the algorithm (not of the tests), stop and report the achieved numbers.

**Live acceptance (`tests/live`, 👤 `RUN_LIVE=1`, gate G3):** run on 3–5 Beirle-catalogue sources, plus the Singrauli unit, with real winds; save a comparison table in `PROGRESS.md`.

**Done when:** CI green; fixture pipeline stores an estimate or an honest `insufficient_data`; gate G3 decided.

**Prompt:** *"Do Phase 5B of docs/IMPLEMENTATION_PLAN.md: wind-rotation emission rates with seasonal fits, min_days, block bootstrap plus wind term, contamination check, tests on the puff-model generator. Stop and report if targets are not met."*

---

## Phase 6 — Own model 1: thermal anomaly classifier (#7, Arch 6 first half)

**Goal:** classify each VIIRS hotspot as `industrial`, `crop_burning`, `persistent_other` (mine fires, brick kilns, waste burning) or `other`, so crop-burning NO2 can be flagged, and prove it works on data that does not share the label rules.

**Design (why this differs from v1).** v1 trained on weak labels built from distance to facility, persistence, land cover and month, using those same variables as features, so the model could only relearn the rules. v2 separates the two sets:
- **Label-defining features (set L):** distance to registry facility, distance to OSM industrial polygon, persistence counts (30/365 days), WorldCover at point and at 1 km, month. Used **only** to assign weak labels and as a rules prior.
- **Model features (set M, label-blind):** FRP, `bright_ti4`, `bright_ti5`, `ti4 − ti5`, day/night, scan/track, hour (UTC), cluster size that day, fire density within 5 km that day, regularity of overpass-time detections within 1 km over 30 days (spread of timing and of FRP), NDVI around the point.
- The model learns what each class *looks like*, so it can disagree with the rules where the evidence says so.

**Tasks**
1. `ml/thermal/make_dataset.py`: 2 years of VIIRS 375 m points over the region plus Punjab/Haryana for crop-burning examples; compute L and M; assign weak labels from L (drop ambiguous points); keep a **spatial hold-out** region.
2. **Independent evaluation set** (never used for training or rule tuning):
   - automatic part: points inside MODIS burned-area polygons within ±10 days → `crop_burning` evidence; points inside registered facility footprints with ≥ 100 detections/year → `industrial` evidence;
   - 👤 **hand-checked part:** `ml/thermal/make_eval_template.py` writes a CSV and Sentinel-2 preview chips for **200 stratified points** (70 industrial, 70 crop burning, 30 persistent_other, 30 other). You label them (about 2–3 hours) and save `ml/thermal/eval_labels.csv`.
3. Train LightGBM multiclass on M with the weak labels (`ml/thermal/train.ipynb`, CPU). Report per-class precision/recall and the confusion matrix on (a) the spatial hold-out and (b) the independent set, for three candidates: **rules only (L)**, **model only (M)**, **product of experts** (`p ∝ p_model(c) · prior_rules(c)`, prior weights in config). Save the best by macro-F1 on the independent set to `models/thermal_lgbm.txt` + feature list; if the model does not beat rules only by `thermal.ship_margin_f1` (0.03), ship the rules-only classifier and say so in the README.
4. `detect/thermal.py`: load the chosen classifier (or the rules), classify new FIRMS points, write `thermal` detections with `class_label`, `class_prob`, and `qa.classifier = rules|model|poe`.
5. Notebook note: list which features were excluded because they define the labels, and the independent-set numbers.

**Tests:** feature builder is label-blind (the test asserts no L column is in M); tiny fixture dataset trains and predicts; the October Delhi-NCR fixture day produces crop-burning detections (used by Phase 5A's rule test).

**Done when:** independent-set macro-F1 and confusion matrix reported (**no fixed target is promised in advance**; the number is what it is); the shipped classifier is the best of the three on the independent set; the October fixture day classifies correctly.

**Prompt:** *"Do Phase 6 of docs/IMPLEMENTATION_PLAN.md: label-blind feature set M, rules from set L, independent evaluation set (burned area plus my hand labels once I provide them), three-way comparison and shipping rule, inference module."*

---

## Phase 7 — Own model 2: stack plume classifier (#8, Arch 6 second half)

**Goal:** a Sentinel-2 chip around a registered stack is classified `none` / `steam` / `smoke`, shown as **dated visual context**, never as stand-alone proof.

**Why.** Many visible plumes at power plants are cooling-tower steam (water vapour), not pollution, and Sentinel-2 passes about three hours before TROPOMI and can be days away from the event.

**Tasks**
1. `ml/smoke/export_chips.py`: for every chimney/facility point, 128×128 px chips (10 m → 1.28 km) from Sentinel-2 L2A with cloud cover < 20 %, bands B2, B3, B4, B8, B11, B12 → GeoTIFF + RGB PNG, with the acquisition time in the file name.
2. Public data: `prepare_labels.py` converts the Sentinel-2 industrial plume dataset (Mommert et al., European sites) into the same chip format; its positive class is mapped to `plume` (steam and smoke are not distinguished there).
3. 👤 **Label a few hundred Indian chips** in Label Studio with three classes (`none`, `steam`, `smoke`); Claude Code generates the config and import JSON. Aim for ≥ 300; 100 of them held out as the Indian test split.
4. `ml/smoke/train.ipynb` (👤 Colab/Kaggle GPU): timm `resnet18` pretrained, `in_chans=6` (first conv adapted by repeating RGB weights), flips/90° rotations/brightness augmentation. Pre-train a 2-class head (`none` vs `plume`) on the public set, then fine-tune a 3-class head on the Indian set. Report precision/recall per class on the Indian test split only. Export with `export_onnx.py` → `models/smoke_resnet18.onnx`.
5. `detect/smoke.py`: onnxruntime CPU inference; save a Grad-CAM or plain RGB chip PNG; for each result record `dt_hours = S2 acquisition − event overpass` and `evidence_level`: `same_day` if |dt| ≤ 24 h, `context` otherwise. **Stub:** if weights are missing it returns class `none`, prob 0.0, **`is_stub = true`**, and callers must ignore stubs (fusion, bonuses, PDFs, UI badges).
6. Run on the most recent clear Sentinel-2 pass for each unit with an open event.

**Tests:** inference on fixture chips with the stub (checks `is_stub`) and with a tiny real ONNX file; fusion ignores stubs; evidence level computed correctly around the 24 h boundary.

**Done when:** tests pass; with real weights the Indian-test numbers are in `PROGRESS.md`; the event detail shows the chip with its date, time offset and class (Phase 11).

**Prompt:** *"Do Phase 7 of docs/IMPLEMENTATION_PLAN.md: chip exporter, public-dataset converter, 3-class Label Studio config, Colab notebook, ONNX export, inference with evidence level and a stub that is flagged and ignored. I will run training and labelling."*

---

## Phase 8 — Own model 3: facility baseline + anomaly alerts (#22, #23)

**Goal:** predict the NO2 column you would expect for each unit given season and weather; alert when the observation departs strongly; validate without leakage.

**Tasks**
1. `temporal/features.py`: daily table per watch unit from 2018 → today using `get_buffer_timeseries` (no per-day loops). Target = `local − null_median` buffer anomaly of NO2 (and the 28-day SO2 enhancement). Features: day-of-year sin/cos, weekday, year trend, wind speed and direction (sin/cos, from the wind chain), 2 m temperature, cloud fraction, boundary-layer height if available, regional background mean, unit id (categorical), type, capacity, and **`generation_mwh` if `data/covariates/generation.csv` exists** (the training script runs with and without it and reports both).
2. `ml/baseline/train.py`: one global LightGBM with the unit as a categorical.
   - **Mask known events:** drop rows inside any `known_events.csv` window ± `known_event_pad_days` from training (otherwise the model learns the outage).
   - Time split: train ≤ `train_end`, validate `valid_year`, test the following year.
   - **Out-of-fold history:** blocked cross-validation by year; the historical `expected` values stored in `baseline_predictions` (`is_oof = true`) come from the fold that did *not* see that year. Today's predictions come from the final model (`is_oof = false`).
   - Report MAE and R² per unit; save `models/baseline_lgbm.txt`.
3. `temporal/baseline.py`: write `baseline_predictions` (observed, expected, residual, rolling robust z over `rolling_z_days`).
4. `temporal/alerts.py` (#23): anomaly if `|residual_z| ≥ alert_z` on ≥ `alert_k` of the last `alert_n` valid days inside `alert_calendar_days`. Validate against `data/known_events.csv` using OOF predictions: hit rate and false-alarm rate per unit-month; mark anomalies that match a known event. If there are fewer than 15 known events, the report says "indicative only".
5. **Replace `z_self` with the baseline residual** when a trained model exists (`qa.anomaly_source = "baseline"`), keeping the climatological `z_self` as the fallback.
6. `temporal/calibrate.py`: if ≥ 20 reviewed outcomes exist (`data/review_labels.csv`: event id/date, `real|false`, plus anomalies matched to known events), fit an isotonic map from score to hit rate and write `models/calibration.json`. The API exposes `score_calibrated` and the UI drops the "(uncalibrated)" label **only** when this file exists. Otherwise print "not enough reviewed outcomes to calibrate".
7. API: `GET /watch-units/{id}/timeseries` (observed, expected, band, anomalies; flags OOF vs. final).

**Tests:** synthetic series with seasonality plus an injected step → alert fires on the step and nowhere else; time split has no leakage (test asserts no train row is later than `train_end`); masked event windows are absent from the training frame; OOF predictions for year Y are produced by a model whose training data excludes Y.

**Done when:** validation report printed with OOF hit rate and false-alarm rate (the 2020 lockdown dip appears as a `low` anomaly **because it was masked and predicted out-of-fold**, not because it was memorised); the timeseries endpoint works; gate G4 decided.

**Prompt:** *"Do Phase 8 of docs/IMPLEMENTATION_PLAN.md: batched feature builder, global LightGBM with known-event masking, out-of-fold history, residual alerts validated against data/known_events.csv, optional generation covariate, calibration step."*

---

## Phase 9 — Impact: population and sensitive sites (#28, #29)

**Goal:** report how many people and which sensitive places lie inside the modelled transport footprint, with numbers that cannot be misread as measured exposure.

**Tasks**
1. `impact/exposure.py` (#28): footprint = the observed event footprint (pixels above background) if present, else a downwind wedge (half-angle `wedge_half_angle_deg` = 15°, length `min(wind × 3 h, wedge_max_km)` = 30 km max, about 240 km² at most). Population = WorldPop sum via Earth Engine `reduceRegion`. Store **`population_raw`** and **`population_weighted`** (each cell weighted by `exp(−distance/decay_km)` from the source) with `method` (`observed` | `wedge`).
2. `impact/sensitive_sites.py` (#29): spatial join with cached OSM schools, hospitals/clinics, villages/towns in PostGIS; counts plus the 10 nearest with names and distances. *(Optional trim.)*
3. Hook both into the pipeline after fusion; `GET /events/{id}` returns them together with the caption `t("exposure_caption")` ("People inside the modelled transport footprint, not a measurement of exposure.").

**Tests:** fixture population raster with a known sum; wedge area ≤ 245 km²; weighted ≤ raw; observed footprint preferred over the wedge.

**Done when:** a fixture event shows both population numbers, the method and the site list.

**Prompt:** *"Do Phase 9 of docs/IMPLEMENTATION_PLAN.md: observed-or-wedge footprint, raw and distance-weighted WorldPop counts, sensitive-site join, wording from wording.yaml, tests with fixture rasters."*

---

## Phase 10 — Backend API + scheduler, live watch (Arch 11)

**Tasks**
1. `jobs/pipeline.py:run_for_date(date, region)` in this order: ingest → detect (gas, flare, thermal, smoke) → **attribute → fuse** → baseline/alerts → impact → watchlist dispatch (Phase 12). Quantify (emission rates) is a separate monthly job. Each stage logs counts and duration; one failed detector does not stop the rest; every stage is idempotent (re-running a date changes nothing).
2. `jobs/scheduler.py` (APScheduler in the worker): daily 15:00 IST for "today" using the near-real-time sources chosen in the spike, and the previous `rerun_previous_days` days re-run with the offline products; FIRMS every 3 h; Nightfire daily only if `flaring.source` is `nightfire`; emission rates monthly; baseline retrain monthly.
3. `routes_layers.py`: `GET /layers/{no2|so2|ch4}/{date}` → EE tile URL (cached in `layer_cache`).
4. `POST /admin/run?date=` guarded by `require_admin`; basic rate limit on all write endpoints (in-memory token bucket is enough).
5. OpenAPI types exported to `web/src/api/types.ts` (openapi-typescript).

**Tests:** admin endpoint returns 401 without the token and 200 with it; a failing detector is logged and the pipeline continues; running one date twice yields identical row counts.

**Done when:** `make up` in fixture mode runs one full pipeline cycle on schedule; all endpoints covered by API tests.

**Prompt:** *"Do Phase 10 of docs/IMPLEMENTATION_PLAN.md: pipeline orchestrator in the new stage order, scheduler, layer tile endpoint, token-protected admin trigger with rate limiting, generated TS types."*

---

## Phase 11 — Map dashboard (#32)

**Goal:** the screen the judges see, honest by construction.

**Tasks**
1. Layout: left sidebar (layer toggles, date slider, anomaly list), map centre, right drawer (unit or event detail).
2. Layers: NO2 / SO2 / CH4 tiles, watch units (symbol by kind and type), events (circle sized by score, colour by status), upwind cone + wind arrow for the selected event, plume footprint, flares, thermal points coloured by class.
3. Time slider (last 90 days) driving layer date and event filter.
4. **Event drawer:** attribution badge (`facility`, `cluster` with member list, or `ambiguous` with all candidates and the margin); score with its three parts and the label "score (uncalibrated)"; "routine plume" and "gate degraded" notes; **contested** banner (both signals shown) or rejected-crop-burning banner; Sentinel-2 chip with its date, time offset and class (steam / smoke / none) and the caption for its evidence level; exposure numbers with the caption from wording; "Download evidence PDF".
5. **Unit page:** metadata, emission rate with the **total** band and the secondary statistical band, status `insufficient_data` / `contaminated` shown plainly, reference value, time series (observed vs. expected band, anomalies; out-of-fold history marked), list of events.
6. Geofence drawing (terra-draw) and "Watch this area" form → `POST /watchlists` (Phase 12), including the confirmation notice.
7. Works at 1366×768. Loading, empty and error states for every panel.

**Done when:** with fixture data every demo moment in the storyline is clickable; the Playwright smoke test opens the map, clicks an event and sees the drawer with the attribution badge and the uncalibrated label.

**Prompt:** *"Do Phase 11 of docs/IMPLEMENTATION_PLAN.md against the generated API types, with the attribution badge, contested banner, evidence-chip captions, total uncertainty band and wording from the API. Add a Playwright smoke test."*

---

## Phase 12 — Watchlists, geofenced email alerts, PDF reports (#33, #34)

**Tasks**
1. **#33** `alerts/geofence.py`: for each new event/anomaly, `ST_Intersects` with confirmed watchlists, respecting species and `min_score`; send through `alerts/mailer.py` (SMTP; MailHog in dev); log in `alert_deliveries`; de-duplicate per (watchlist, event). *(Optional trim.)*
2. **Opt-in and abuse limits** (`alerts/optin.py`): `POST /watchlists` stores the row unconfirmed and sends a confirmation email with a one-time token; only confirmed watchlists receive alerts. Limits: `max_watchlists_per_email`, `max_watchlists_per_ip_per_day` (IP stored as a hash). With `demo_auto_confirm: true` (demo only) the confirmation is skipped. Every alert email has an unsubscribe link.
3. **#34** `reports/render.py`: Jinja2 → WeasyPrint PDF per event. Sections: summary line, map snapshot (matplotlib static map of unit, cone, footprint), Sentinel-2 chip with date, offset and class **and the right caption**, wind (source and level), detection table, score with its three parts, emission estimate with total and statistical bands and the reference, time-series chart, exposure with its caption, method notes and data sources with dates, and a footer disclaimer from wording: *"Screening indicator from satellite data at ~5 km resolution; not compliance evidence."* Deterministic, no LLM. Stub outputs never appear.
4. `GET /events/{id}/report.pdf`; the alert email links to it.

**Tests:** unconfirmed watchlists get nothing; limits enforced; confirmation token single-use; PDF contains the unit name, the emission number or "insufficient data", the disclaimer, and no stub content.

**Done when:** creating and confirming a geofence over the fixture event and re-running the pipeline delivers an email visible in MailHog; the PDF renders and the tests above pass.

**Prompt:** *"Do Phase 12 of docs/IMPLEMENTATION_PLAN.md: double opt-in watchlists with limits, geofence dispatch via SMTP/MailHog, and the WeasyPrint evidence report with the disclaimer and honest captions."*

---

## Phase 13 — Integration, real-data acceptance, demo mode (cross-cutting)

**Tasks**
1. **End-to-end test (fixture):** fresh DB → seed → run the pipeline for 3 dates → assert units, events, estimates (or `insufficient_data`), anomalies, exposures, email and PDF all exist; running it twice changes nothing.
2. **Real-data acceptance** (`make accept-real`, `tests/live`, 👤 `RUN_LIVE=1`): on the recorded real slice and the live Singrauli window, assert the behaviours the demo relies on: the cluster is attributed at cluster or facility level with a stated margin; routine plumes do not create events; at least one non-routine event exists in the window or the report explains why not; an emission estimate is stored or flagged honestly; Beirle comparison table produced.
3. **Demo record/replay** (`app/demo/`): `make demo-record DATE=…` runs live and snapshots every client response (including CDS winds) and a DB dump into `data/demo/<date>/`; `make demo-replay` sets `DATA_MODE=replay` and serves exactly that run.
4. **Curate the demo set:** one clear Singrauli event (cluster-level attribution shown honestly) with its chip; one Delhi-NCR contested or rejected crop-burning case; one unit with a visible baseline anomaly; one unit with a catalogue comparison.
5. Performance: pipeline for one region-day < 5 min; dashboard first paint < 3 s with replay data.
6. Deployment: single VM, `docker compose -f docker-compose.prod.yml up`, Caddy for HTTPS, `ADMIN_TOKEN` set, MailHog off, SMTP relay on.
7. **Security and wording checklist:** admin token required, rate limits on, no secrets in the repo (scan), disclaimers present in UI, PDF and email.
8. README: setup, keys, fixture vs. live, how each model was trained and evaluated, **limitations** (TROPOMI 5.5×3.5 km pixels, cloud and monsoon gaps, cluster attribution, wind uncertainty, weak labels, steam vs. smoke, uncalibrated score, flaring from FIRMS persistence unless Nightfire is licensed), and an ethics section on naming facilities.
9. 👤 Demo script, screen recording of the storyline, slides.

**Done when:** a teammate who did not build it runs `make demo-replay` on a clean machine and completes the storyline; `make accept-real` output is saved in `PROGRESS.md`; gate G5 passed.

**Prompt:** *"Do Phase 13 of docs/IMPLEMENTATION_PLAN.md: end-to-end test, real-data acceptance target, demo record/replay, production compose, security and wording checklist, README. Then run the e2e test and report results."*

---

## Demo storyline → what must work

| Moment | Built in phases |
|---|---|
| Hook: today's NO2/SO2 map over Singrauli | 2, 4, 10, 11 |
| Click a hotspot → wind arrow, attribution badge (cluster or facility, with margin), score parts, dated plume chip | 4, 5A, 7, 11 |
| Contested/rejected alert: NO2 rise linked to crop burning (Delhi-NCR) | 5A, 6, 11 |
| Emission rate with total band vs. catalogue, or an honest "insufficient data"; history with the anomaly | 5B, 8, 11 |
| People, schools, hospitals inside the modelled transport footprint | 9, 11 |
| Judge draws a geofence → confirms → email; hand over the PDF | 12, 11 |

## If time runs short

Drop in this order (each also listed in the Word plan): **#3 methane layer (1.0)**, **#29 sensitive sites (1.0)**, **#8 Indian fine-tune — ship the public-set model as context only (1.0)**, **#33 geofenced alerts (1.5; the dashboard anomaly list stands in)**. Saves 4.5 person-days (44.5 remaining). Never drop Phase S, Phase 13's replay mode or `make accept-real`.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Real data is much noisier than synthetic data | Phase S and real-slice acceptance in 4 and 5A; gates G1–G3 |
| Earth Engine quota or latency in the demo | Batched requests, cache everything, replay mode |
| Wind data for "today" is delayed or low-level winds are biased | Provider chain chosen in the spike; wind source recorded; wind term in the rate band |
| A cluster's plume cannot be assigned to one plant | `cluster`/`ambiguous` levels with margins; say so in the UI |
| Most days are cloudy (monsoon, winter haze) | Valid-day fractions measured in the spike; windows widened by config; JJAS excluded from rates |
| Thermal model only relearns the rules | Label-blind features; independent evaluation set; ship rules if the model does not beat them |
| Visible plume is steam, or the chip is days old | 3 classes; dated chip; evidence level; context-only caption |
| Too few known events or reviews to calibrate | Report "indicative only"; leave the score labelled uncalibrated |
| Emission rate far from catalogue | Show both with total bands; explain wind-height and lifetime assumptions; `insufficient_data` is a valid answer |
| Naming a facility from coarse satellite data | Wording from `wording.yaml`; disclaimer everywhere; ethics note in README |
| Build time is underestimated | Estimate rose from 39.25 to 49.0 person-days on purpose; gates and trims defined above |
| Nightfire licence is slow or refused | Flaring runs on `annual_sites` + `firms_persistent`; Nightfire is an optional config switch; flaring is 1.0 of 49 days and rare at coal plants |

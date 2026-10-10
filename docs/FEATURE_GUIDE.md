# Land Industrial Emissions Monitor — Feature Guide (v2)

Companion to `IMPLEMENTATION_PLAN.md`. The plan says *how and when* to build; this guide says *what each feature is, how it must behave, what it must never claim, and how to tell it works*. Feature numbers match the Word plan. Config keys refer to `config/settings.yaml`.

## How the system fits together

Satellites see **columns of gas** at about 5.5 × 3.5 km per pixel, once a day, only when it is not cloudy. The product therefore works with *watch units* (an isolated facility, or a cluster of facilities within 15 km), not with individual chimneys:

1. **Observe** a unit each day: is NO2 higher around it than in comparable places nearby (#1), is SO2 elevated in the 28-day wind-aligned average (#2), is there a flare (#5), is there fire nearby (#7), is there a visible plume (#8)?
2. **Ask whether it is unusual for this unit** (`z_self`, later the baseline residual #22). A power plant is always a bit above the countryside; only departures are news.
3. **Attribute** the plume to a unit using wind (#17), with an honest margin. A cluster may be the finest honest answer.
4. **Fuse** observations into events and score them (#21, Arch 3). Fire evidence makes an event *contested* or *rejected*, never silently deleted.
5. **Quantify** emission rates over seasons (#18) and **track** each unit over time (#22, #23).
6. **Assess impact** (#28, #29) and **deliver** (#32, #33, #34) with wording that says what the data can and cannot support.

### Words that must be used consistently

| Say | Do not say | Why |
|---|---|---|
| score (uncalibrated) | confidence, probability | The score is not calibrated until `models/calibration.json` exists |
| unusual for this unit | polluting | A satellite column is not a compliance measurement |
| modelled transport footprint | exposed population | A column is not ground-level concentration |
| attributed to the Singrauli complex | caused by plant X | Margin decides how fine the attribution may be |
| insufficient data | (a number) | A rate needs enough valid days |
| context | proof | A plume chip may be hours or days from the event |

---

## A. Detection

### #1 NO2 hotspot and plume detection  — Phase 4
- **What the user gets:** a daily yes/no per watch unit that NO2 is higher than expected around it, with a plume outline.
- **Inputs:** Sentinel-5P NO2 (`no2`, `cloud_fraction`, `valid`), `aer_ai`, the unit's history.
- **Method:** compare the mean over the unit's 5 km buffer with the means of 40 random buffers of the same size in the 20–50 km ring (never near other registered facilities). `z_bg = (local − median(null)) / (1.4826·MAD(null))`. This is a *null-buffer* test, so spatially correlated noise stays in the null distribution. Then `z_self` compares the same anomaly with the unit's own seasonal history. A detection with `z_bg ≥ 2` but `z_self < 2` is stored as **routine** and cannot start an event.
- **Outputs:** `Detection(detector="no2", z_bg, z_self, footprint, score_parts, qa)`.
- **Key config:** `detect.local_radius_km`, `null_annulus_km`, `n_null`, `z_bg_min`, `z_self_min`, `cloud_max`, `valid_fraction_min`, `aer_ai_degraded`.
- **Limits:** one pixel is about 19 km²; plumes of small plants are not resolved; cloud and monsoon remove many days; heavy haze degrades the retrieval (flagged `retrieval_degraded`).
- **Works when:** a puff-model plume next to a fixture unit is detected; pure correlated noise gives 1–5 % false positives at `z_bg ≥ 2`; a stable two-year source is routine, not an event.

### #2 SO2 hotspot detection  — Phase 4
- **What the user gets:** a monthly-scale indicator that a unit has a sustained SO2 plume.
- **Method:** rotate each valid day so the wind points along +x, average over 28 days, compare the 0–30 km downwind box with the upwind box, bootstrap the days 200 times. Detect when `z ≥ 2` and the 5th percentile is above 0 and at least 10 valid days exist.
- **Behaviour:** it is a *window* detection dated at the window end. It **corroborates** events; it never creates one.
- **Limits:** if the spike shows SO2 `z < 2` for the main plants, SO2 becomes a regional layer only (gate G1).
- **Works when:** a constant injected source is detected; noise-only windows are rejected (< 10 % FP over 300 windows).

### #3 Methane regional context layer  — Phase 4 *(optional trim)*
- **What the user gets:** a monthly CH4 anomaly map as context. No attribution, no detections.
- **Method:** month mean minus 12-month regional median. Returns a `LayerProduct`.
- **Limits:** TROPOMI CH4 has large retrieval noise at this scale; never present it as a source finder.

### #5 Gas flaring detection and intensity  — Phase 4
- **What the user gets:** persistent flares at refineries, steel plants and similar land sites, with an intensity value. It matters little for coal-only regions such as Singrauli.
- **Sources (set by `flaring.source`):**
  - `firms_persistent` (default, free): night-time FIRMS 375 m detections with FRP ≥ 5 MW within 2 km of a unit's facility on ≥ 3 nights of 30. Intensity is FRP in MW; no flame temperature.
  - `nightfire` (optional upgrade): VIIRS Nightfire points ≥ 1400 K with the same persistence rule and radiant heat as intensity. Needs the EOG Nightfire data-use licence; scripted access is paid, so the plan works with hand-downloaded files or leaves it off.
  - `annual_sites`: annual flare-site files (World Bank GFMR or EOG) as a static layer and prior. A detection near a known site is flagged `known_flare_site`; a site alone is never an active flare.
- **Rules:** the Nightfire source must fail soft ("unavailable", fall back) when files or credentials are missing. A flare and a thermal detection of the same FIRMS pixel are not two independent detector types.
- **Limits:** land sites only; cloud hides flares; the annual files may have no rows in the region (check in the spike).
- **Works when:** the persistence rule accepts 3-of-30 and rejects 2-of-30 for each source, and the Nightfire source falls back cleanly.

### #7 Thermal anomaly classification  — Phase 6 (own model 1)
- **What the user gets:** each VIIRS hotspot labelled `industrial`, `crop_burning`, `persistent_other` (mine fires, brick kilns, waste) or `other`, so that fire-related NO2 is not blamed on a plant, and a plant's NO2 is not hidden by a field fire.
- **Method:** LightGBM on **label-blind** features (FRP, brightness temperatures, scan/track, hour, cluster size, local fire density, timing regularity, NDVI). Weak labels come from different variables (distance to facility, persistence, land cover, month). The result is compared with rules only and with a product of experts on an **independent** evaluation set (MODIS burned area plus 200 hand-checked points). The best of the three ships; if the model does not beat the rules by 0.03 macro-F1, the rules ship.
- **Limits:** the weak-label metric is not a performance number; only the independent-set number is.
- **Works when:** the October Delhi-NCR fixture day yields crop-burning detections; no L-set column appears in the model features (tested).

### #8 Visible smoke and stack plume classification  — Phase 7 (own model 2)
- **What the user gets:** a Sentinel-2 chip around the stack classified `none`, `steam` or `smoke`, shown as **dated context**.
- **Method:** ResNet-18 (6 bands), pre-trained on the public European plume set, fine-tuned on about 300 hand-labelled Indian chips.
- **Rules:** every result carries `dt_hours` (S2 time minus the event overpass) and an `evidence_level` (`same_day` if ≤ 24 h, else `context`). Only `same_day` smoke can add a corroboration bonus. A stub result (`is_stub=true`) is ignored everywhere.
- **Limits:** most visible plumes at coal plants are cooling-tower steam; S2 passes at about 10:30 local, TROPOMI at about 13:30.

---

## B. Attribution and quantification

### #16 Facility registry and watch units  — Phase 3
- **What the user gets:** one de-duplicated list of industrial sites, grouped into watch units.
- **Method:** load GPPD, GEM, Climate TRACE and OSM; match pairs within 3 km with 0.6 × name similarity + 0.4 × distance score; merge above the threshold; keep every source id; prefer GEM > GPPD > Climate TRACE > OSM coordinates. Connected components within 15 km become cluster units.
- **Works when:** near-duplicates merge, plants 2 km apart do not, the Singrauli fixture forms one cluster with at least five members.

### #17 Wind-based back-attribution  — Phase 5A
- **What the user gets:** for every event, which unit it points to, how sure that is, and the runners-up.
- **Method:** a cone pointing upwind from the plume centroid (half-angle 30°, length `min(speed × 3 h, 50 km)`); candidates from **all** units; rank by `angle_offset/half_angle + distance/length`; `margin = (r2 − r1)/r2`.
- **Rules:** top unit differs from the detecting unit and margin ≥ 0.25 → the event is reassigned. Margin ≥ 0.25 and a single facility → `facility`. Small margin inside one cluster → `cluster`. Small margin across units → `ambiguous` and *contested*.
- **Limits:** wind level and source are recorded; a bad wind gives a bad cone.

### #18 Emission rate estimate with uncertainty  — Phase 5B
- **What the user gets:** a rate in kg/s for a unit over a season or a year, with a band, a catalogue comparison, and a plain statement when the data cannot support a rate.
- **Method (Beirle):** keep days with wind 2–8 m/s; rotate to the wind; average; integrate across-wind ±20 km; fit an exponentially modified Gaussian for mass `A` and e-folding distance `x₀`; `τ = x₀/wind`, `E = A/τ`; NO2 → NOx × 1.32; lifetime fitted per season.
- **Uncertainty:** weekly-block bootstrap (statistical band) combined in quadrature with the wind uncertainty (total band). The UI shows the **total** band first.
- **Statuses:** `ok`, `insufficient_data` (< 60 valid days), `contaminated` (another unit inside the integration region).
- **Works when:** on the independent puff generator the median bias is within ±30 % and the total band contains the truth in ≥ 80 % of seeds; live comparison with Beirle sources is reported (gate G3).

### #21 Score per detection and event  — Phase 4 and 5A
- **What the user gets:** a number in [0, 1] with three visible parts: `signal_quality`, `attribution_certainty`, `anomaly_strength`.
- **Method:** weighted geometric mean (all three must be decent). Event score = best detection score plus 0.05 for each additional *independent detector type* (max +0.10), capped at 0.95. Repeating the same detector on more days adds nothing.
- **Honesty:** called "score (uncalibrated)" until `calibration.json` exists (≥ 20 reviewed outcomes).

---

## C. Temporal intelligence

### #22 Per-facility time series with seasonal baseline  — Phase 8 (own model 3)
- **What the user gets:** for each unit, observed vs. expected NO2 with a band.
- **Method:** one global LightGBM on season, weather, trend, regional background, unit, capacity, and plant generation if available. Known-event windows are masked from training; historical expected values are **out-of-fold** (the model never saw that year).
- **Limits:** with heavy cloud, daily series are sparse; the model explains weather and season, not operations unless generation data is supplied.

### #23 Anomaly alerts  — Phase 8
- **What the user gets:** a list of units behaving unusually, with direction (`high`/`low`) and a match to known events.
- **Method:** rolling robust z of the residual; anomaly if `|z| ≥ 3` on ≥ 2 of the last 5 valid days within 14 calendar days. Hit rate and false-alarm rate reported from out-of-fold predictions; fewer than 15 known events means "indicative only".

---

## D. Impact

### #28 Downwind population exposure  — Phase 9
- **What the user gets:** population inside the *modelled transport footprint* of an event.
- **Method:** observed footprint if present, else a 15° half-angle wedge up to 30 km; WorldPop sum plus a distance-weighted sum (decay 15 km).
- **Caption:** "People inside the modelled transport footprint, not a measurement of exposure."

### #29 Sensitive sites inside a plume  — Phase 9 *(optional trim)*
- **What the user gets:** counts of schools, hospitals and villages in the footprint and the 10 nearest with distances.
- **Method:** spatial join with cached OSM objects.
- **Limits:** OSM completeness in rural India varies.

---

## E. Product

### #32 Map dashboard  — Phase 11
- **Must show:** attribution badge and margin; score parts with the "(uncalibrated)" label; routine / gate-degraded notes; contested and rejected banners; dated plume chip with class and caption; total emission band; exposure caption; wording from the API only.
- **Works when:** every demo moment is clickable and the Playwright smoke test passes at 1366×768.

### #33 Watchlists and geofenced alerts  — Phase 12 *(optional trim)*
- **What the user gets:** draw an area, confirm by email, receive alerts for events and anomalies inside it.
- **Rules:** double opt-in; limits per email and per IP; unsubscribe link in every email; de-duplicated per (watchlist, event).

### #34 Auto-generated evidence report  — Phase 12
- **What the user gets:** a deterministic PDF per event: summary, map, dated chip with caption, wind source and level, detections, score parts, emission estimate with bands and reference, time series, exposure with caption, method notes, sources, and the disclaimer "Screening indicator from satellite data at ~5 km resolution; not compliance evidence."
- **Never:** include stub output, call the score a probability, or state a rate when status is not `ok`.

"""Render docs/SPIKE_REPORT.md from the facts collected by spike_ee.py.

`render({})` is the empty template. Every value in the report comes from the facts; nothing is typed in here.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

EMPTY = "—"


def fmt(value: Any, digits: int = 2) -> str:
    if value is None or value == "" or value == []:
        return EMPTY
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        if value != value:  # NaN
            return EMPTY
        return f"{value:.{digits}e}" if 0 < abs(value) < 0.01 else f"{value:.{digits}f}"
    if isinstance(value, list | tuple):
        return ", ".join(str(v) for v in value)
    return str(value).replace("|", "\\|").replace("\n", " ")


def table(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    rows = [list(r) for r in rows] or [[EMPTY] * len(headers)]
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(fmt(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def render(facts: dict[str, Any]) -> str:
    run = facts.get("run", {})
    status = (
        f"Run at {run['started_at']} UTC." if run else "**NOT RUN YET.** Run `make spike` with the Phase 0 credentials."
    )
    out = [
        "# Spike report — real data for the live-watch region",
        "",
        "Written by `scripts/spike_ee.py` (plan Phase S). This file is the single source of truth for",
        "Earth Engine asset ids, band names, latency and data availability. Later phases must not use",
        "an id or band that is not confirmed here. Machine-readable copy: `docs/SPIKE_FACTS.json`.",
        "",
        status,
        "",
        "## 1. Run",
        "",
        table(
            ["Item", "Value"],
            [
                ["Region", run.get("region")],
                ["Bounding box", run.get("bbox")],
                ["Centroid (lon, lat)", run.get("centroid")],
                ["Analysis centre (mean of the largest plants)", run.get("analysis_centre")],
                ["Analysis window", f"{fmt(run.get('window_km'))} km square around the centroid"],
                ["Days analysed", f"{fmt(run.get('start'))} to {fmt(run.get('end'))} ({fmt(run.get('days'))} days)"],
                ["Earth Engine project", run.get("ee_project")],
                ["Earth Engine quota tier (from the Cloud console)", run.get("quota_tier")],
            ],
        ),
        "",
        "## 2. Collections",
        "",
        "Latency is the time between the newest image over the region and the run.",
        "",
        table(
            ["Key", "Asset id", "Resolves", "Newest image (UTC)", "Latency (days)", "Scale (m)", "Bands", "Error"],
            [
                [
                    k,
                    c.get("id"),
                    c.get("ok"),
                    c.get("latest"),
                    c.get("latency_days"),
                    c.get("scale_m"),
                    c.get("bands"),
                    c.get("error"),
                ]
                for k, c in facts.get("collections", {}).items()
            ],
        ),
        "",
        "### Bands chosen per product",
        "",
        table(
            ["Product", "Collection key", "Asset id", "Band", "Cloud band", "Note"],
            [
                [name, p.get("collection_key"), p.get("id"), p.get("band"), p.get("cloud_band"), p.get("note")]
                for name, p in facts.get("products", {}).items()
            ],
        ),
        "",
        "## 3. Sentinel-5P quality filtering",
        "",
        "Whether the Level-3 product is already QA-filtered cannot be read from the image metadata alone:",
        "confirm it on the catalog page of each collection and write the answer in the last column.",
        "",
        table(
            [
                "Collection key",
                "QA / cloud bands found",
                "Masked share of the window on the newest day",
                "QA already applied in L3? (fill in)",
            ],
            [
                [k, q.get("qa_bands"), q.get("masked_share"), q.get("qa_applied")]
                for k, q in facts.get("s5p_qa", {}).items()
            ],
        ),
        "",
        "## 4. Wind",
        "",
        table(
            [
                "Collection key",
                "Heights with u and v bands (m)",
                "Days covered in the window",
                "Image properties",
                "Note",
            ],
            [
                [k, w.get("heights"), w.get("days_covered"), w.get("props"), w.get("note")]
                for k, w in facts.get("wind", {}).get("collections", {}).items()
            ],
        ),
        "",
        "### 10 m against the best higher level, at the largest plants (08:00 UTC)",
        "",
        table(
            [
                "Collection key",
                "Plant",
                "Low level (m)",
                "High level (m)",
                "Mean speed low (m/s)",
                "Mean speed high (m/s)",
                "Ratio high / low",
                "Samples",
            ],
            [
                [
                    r.get("collection_key"),
                    r.get("plant"),
                    r.get("low_m"),
                    r.get("high_m"),
                    r.get("mean_low"),
                    r.get("mean_high"),
                    r.get("ratio"),
                    r.get("n"),
                ]
                for r in facts.get("wind", {}).get("ratios", [])
            ],
        ),
        "",
        "### Copernicus CDS (ERA5 100 m)",
        "",
        table(
            ["Item", "Value"],
            [[k, v] for k, v in facts.get("cds", {}).items()],
        ),
        "",
        "## 5. Plants used (from OpenStreetMap, largest first)",
        "",
        table(
            ["Name", "Lon", "Lat", "Capacity (MW)", "Fuel"],
            [
                [p.get("name"), p.get("lon"), p.get("lat"), p.get("capacity_mw"), p.get("source")]
                for p in facts.get("plants", [])
            ],
        ),
        "",
        "## 6. Valid days per month",
        "",
        "A day counts when at least the stated share of pixels in the window has a value.",
        "",
    ]
    for product, block in facts.get("valid_days", {}).items() or {"no2": {}, "so2": {}}.items():
        out += [
            f"### {product.upper()} (threshold {fmt(block.get('min_fraction'))})",
            "",
            table(
                ["Month", "Days", "Days valid", "Share valid", "Share valid at 0.3"],
                [
                    [r.get("month"), r.get("days"), r.get("days_ok"), r.get("fraction_ok"), r.get("fraction_ok_030")]
                    for r in block.get("months", [])
                ],
            ),
            "",
        ]
    nb = facts.get("null_buffer", {})
    dry = facts.get("dry_season", {})
    g1 = facts.get("gate_g1", {})
    dnb = dry.get("null_buffer", {})
    out += [
        "## 7. Null-buffer prototype (NO2)",
        "",
        "Rough version of the Phase 4 test: the plants' buffers against equal-size buffers drawn in the ring.",
        "",
        table(
            ["Item", "Value"],
            [
                ["Days in the window", nb.get("days")],
                ["Days with a usable local buffer and enough null buffers", nb.get("days_tested")],
                ["Days with z_bg ≥ threshold", nb.get("days_detected")],
                ["z_bg threshold", nb.get("z_bg_min")],
                ["Median of (local − null median), mol/m²", nb.get("median_excess")],
                ["Median null sigma, mol/m²", nb.get("median_sigma")],
                ["Median z_bg", nb.get("median_z")],
            ],
        ),
        "",
        "## 8. SO2 window prototype",
        "",
        "Bootstrap z of the wind-aligned downwind enhancement, per plant and per window.",
        "",
        table(
            ["Plant", "Window end", "Valid days", "Mean enhancement (mol/m²)", "z", "5th percentile", "Wind source"],
            [
                [
                    r.get("plant"),
                    r.get("window_end"),
                    r.get("n_valid_days"),
                    r.get("mean"),
                    r.get("z"),
                    r.get("p5"),
                    r.get("wind_source"),
                ]
                for r in facts.get("so2_window", [])
            ],
        ),
        "",
        f"## 8b. The same prototypes on the last dry season ({fmt(dry.get('start'))} to {fmt(dry.get('end'))})",
        "",
        table(
            ["Item", "Value"],
            [
                ["Days in the window", dnb.get("days")],
                ["Days with a usable local buffer and enough null buffers", dnb.get("days_tested")],
                ["Days with z_bg ≥ threshold", dnb.get("days_detected")],
                ["Median of (local − null median), mol/m²", dnb.get("median_excess")],
                ["Median null sigma, mol/m²", dnb.get("median_sigma")],
                ["Median z_bg", dnb.get("median_z")],
            ],
        ),
        "",
        table(
            ["Plant", "Window end", "Valid days", "Mean enhancement (mol/m²)", "z", "5th percentile", "Wind source"],
            [
                [
                    r.get("plant"),
                    r.get("window_end"),
                    r.get("n_valid_days"),
                    r.get("mean"),
                    r.get("z"),
                    r.get("p5"),
                    r.get("wind_source"),
                ]
                for r in dry.get("so2_window", [])
            ],
        ),
        "",
        "## 9. Earth Engine timing and quota",
        "",
        table(
            ["Test", "Calls", "Rows", "Seconds", "Error text"],
            [
                [t.get("test"), t.get("calls"), t.get("rows"), t.get("seconds"), t.get("error")]
                for t in facts.get("timing", [])
            ],
        ),
        "",
        "## 10. FIRMS and flare sources",
        "",
        table(
            [
                "Source",
                "Access",
                "Rows in the last 90 days",
                "Date range available",
                "Largest day range accepted",
                "Columns",
                "Error",
            ],
            [
                [
                    k,
                    f.get("ok"),
                    f.get("rows_90d"),
                    f.get("available"),
                    f.get("day_range"),
                    f.get("columns"),
                    f.get("error"),
                ]
                for k, f in facts.get("firms", {}).get("sources", {}).items()
            ],
        ),
        "",
        f"FIRMS key status: {fmt(facts.get('firms', {}).get('key_status'))}",
        "",
        "### Night-time FIRMS detections near the largest plants (last 90 days)",
        "",
        table(
            [
                "Source",
                "Plant",
                "Detections",
                "Nights",
                "Most nights in one window",
                "Same, FRP at or above the minimum",
                "Median FRP (MW)",
            ],
            [
                [
                    source,
                    row.get("plant"),
                    row.get("detections"),
                    row.get("nights"),
                    row.get("max_nights_in_window"),
                    row.get("max_nights_in_window_min_frp"),
                    row.get("median_frp_mw"),
                ]
                for source, f in facts.get("firms", {}).get("sources", {}).items()
                for row in f.get("near_plants", [])
            ],
        ),
        "",
        f"### Annual flare-site files in `{fmt(facts.get('flares', {}).get('directory'))}`",
        "",
        table(
            ["File", "Sites", "Sites inside the region", "Error"],
            [
                [f.get("file"), f.get("sites"), f.get("sites_in_region"), f.get("error")]
                for f in facts.get("flares", {}).get("files", [])
            ],
        ),
        "",
        "### Nightfire (optional; not tested by the script, fill in by hand)",
        "",
        table(
            ["Item", "Value"],
            [
                [
                    "Nightly files found in `data/raw/nightfire/`",
                    facts.get("flares", {}).get("nightfire_files_on_disk"),
                ],
                ["Licence status (granted / applied / no licence yet)", ""],
                ["Versions and dates that could be downloaded by hand", ""],
            ],
        ),
        "",
        "## 11. Suggested decisions",
        "",
        "Computed from the numbers above. They are suggestions; the decision is written in section 12.",
        "",
        table(
            ["Decision", "Suggestion", "Based on"],
            [[d.get("decision"), d.get("suggestion"), d.get("basis")] for d in facts.get("decisions", [])],
        ),
        "",
        "## 12. Gate G1 — decided by the team",
        "",
        table(
            ["Question", "Decision"],
            [
                ["Wind chain order (`wind.chain`)", g1.get("wind_chain")],
                ['Source for "today" and for history', g1.get("today_and_history")],
                [
                    "Does SO2 pass (window z ≥ 2 for the main plants)? If not, SO2 becomes a regional layer.",
                    g1.get("so2"),
                ],
                ["Are valid days in Oct–Mar ≥ 40 %? If not, which windows are widened?", g1.get("valid_days")],
                ["`valid_fraction_min`", g1.get("valid_fraction_min")],
                ["Flaring source (`flaring.source`)", g1.get("flaring_source")],
                ["Region bbox confirmed?", g1.get("bbox")],
                ["Decided on", g1.get("decided_on")],
            ],
        ),
        "",
        "## Errors during the run",
        "",
        table(["Section", "Error"], [[k, v] for k, v in facts.get("errors", {}).items()]),
        "",
    ]
    return "\n".join(out)

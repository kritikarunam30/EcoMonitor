"""The CEA report converter, on small sheets shaped like the real reports. No files, no network."""

from datetime import date

import numpy as np
import pandas as pd

import cea_reports

NAN = np.nan
REPORT_DAY = date(2026, 10, 8)


def test_ongoing_outages_are_read_for_region_stations_only():
    sheet = pd.DataFrame(
        [
            [
                "State/System",
                NAN,
                "Power Station",
                "Unit No.",
                "Planned",
                "Major",
                "Minor",
                "Others",
                "Date",
                NAN,
                "Reason",
            ],
            ["Punjab", NAN, "ROPAR TPS", "6", 0, 0, 210, 0, "27/09/2026 11:32", NAN, "FURNACE DRAFT ABNORMAL"],
            ["Uttar Pradesh", NAN, "RIHAND STPS", "3", 500, 0, 0, 0, "31/08/2026 18:25", NAN, "OVERHAULING WORKS"],
            [
                "Uttar Pradesh",
                NAN,
                "OBRA TPS",
                "15",
                0,
                0,
                200,
                0,
                "07/10/2026 13:03",
                "08/10/2026 17:36",
                "ELECTRICAL  FAULT /",
            ],
        ]
    )
    rihand, obra = cea_reports.parse_ongoing_outages(sheet, REPORT_DAY, "src")
    assert rihand == {
        "unit_or_facility": "RIHAND STPS",
        "start": date(2026, 8, 31),
        "end": REPORT_DAY,  # still out on the report day
        "unit_no": 3,
        "capacity_out_mw": 500.0,
        "outage_kind": "planned",
        "ongoing_at_report": True,
        "reason": "OVERHAULING WORKS",
        "source_url": "src",
    }
    assert (obra["end"], obra["ongoing_at_report"], obra["outage_kind"]) == (date(2026, 10, 8), False, "forced_minor")
    assert obra["reason"] == "ELECTRICAL FAULT"


def test_finished_outages_read_numbers_stored_as_text():
    sheet = pd.DataFrame(
        [
            ["Station", "Unit No", "Capacity (MW)", "Date of Maintanance", "Sync Date", "remarks"],
            ["SINGRAULI STPS", "6", "500.00", "14/05/2025 23:55", "16/05/2025 13:32", "TUBE LKG."],
            ["ANTA CCPP", "3", "88.71", "16/05/2025 00:28", "16/05/2025 16:54", "CONSERVATION"],
        ]
    )
    (event,) = cea_reports.parse_finished_outages(sheet, "src")
    assert (event["unit_or_facility"], event["unit_no"], event["capacity_out_mw"]) == ("SINGRAULI STPS", 6, 500.0)
    assert (event["start"], event["end"], event["ongoing_at_report"]) == (date(2025, 5, 14), date(2025, 5, 16), False)


def test_merge_keeps_one_row_per_outage_and_prefers_the_finished_one():
    base = {"unit_or_facility": "RIHAND STPS", "unit_no": 3, "capacity_out_mw": 500.0, "outage_kind": "planned"}
    base |= {"reason": "x", "source_url": "s", "start": date(2026, 8, 31)}
    seen_early = base | {"end": date(2026, 9, 10), "ongoing_at_report": True}
    seen_late = base | {"end": date(2026, 10, 8), "ongoing_at_report": True}
    finished = base | {"end": date(2026, 10, 20), "ongoing_at_report": False}
    no_capacity = base | {"unit_no": 4, "capacity_out_mw": 0.0, "end": date(2026, 9, 1), "ongoing_at_report": True}

    still_running = cea_reports.merge_events([seen_late, seen_early, no_capacity])
    assert len(still_running) == 1
    assert still_running.iloc[0]["end"] == date(2026, 10, 8)

    merged = cea_reports.merge_events([seen_early, finished, seen_late])
    assert len(merged) == 1
    row = merged.iloc[0]
    assert (row["end"], row["ongoing_at_report"], row["duration_days"]) == (date(2026, 10, 20), False, 50)
    assert (row["type"], row["direction"]) == ("outage", "low")
    assert list(merged.columns) == cea_reports.EVENT_COLUMNS
    assert cea_reports.merge_events([]).empty


def test_generation_columns_are_found_from_the_header():
    sheet = pd.DataFrame(
        [
            ["POWER STATION", NAN, "MONITORED\nCAP.\n(MW)", "GENERATION (MU)", NAN, "CAP. UNDER\nOUTAGE\n(MW)"],
            [NAN, NAN, NAN, "TODAY'S\nPROGRAM", "TODAY'S\nACTUAL\n", NAN],
            ["REGION TOTAL", NAN, 78431.22, 1269.54, 1164.39, 12781.75],
            ["RIHAND STPS", NAN, 3000, 67.93, 61.46, 0],
            ["RIHAND HPS", NAN, 300, 1.29, 1.23, 0],
            ["VINDHYACHAL STPS", NAN, 4760, 97.65, 83.87, 500],
        ]
    )
    rows = cea_reports.parse_generation(sheet, date(2025, 5, 18))
    assert [r["facility_name"] for r in rows] == ["RIHAND STPS", "VINDHYACHAL STPS"]  # hydro is not in the list
    assert rows[0] == {
        "facility_name": "RIHAND STPS",
        "date": date(2025, 5, 18),
        "generation_mwh": 61460.0,
        "monitored_capacity_mw": 3000.0,
        "capacity_under_outage_mw": 0.0,
    }
    assert rows[1]["capacity_under_outage_mw"] == 500.0

"""Turn hand-downloaded CEA daily reports into the Phase 0 inputs. Offline.

    python scripts/cea_reports.py

Reads data/raw/cea/ (gitignored) and writes

    data/known_events.csv            unit outages of the region's stations, plus hand-kept rows
    data/covariates/generation.csv   daily generation per station

Reports used, by the file names the National Power Portal gives them:

    dgr10-YYYY-MM-DD.xls             Sub-Report 10: units under maintenance on that day (outage still running)
    dgr14-YYYY-MM-DD.xls             Sub-Report 14: units recommissioned on that day (outage finished)
    generation/dgr2-YYYY-MM-DD.xls   Sub-Report 2: station-wise generation of that day
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pandas as pd

from app.settings import REPO_ROOT

RAW_DIR = REPO_ROOT / "data" / "raw" / "cea"
EVENTS_PATH = REPO_ROOT / "data" / "known_events.csv"
GENERATION_PATH = REPO_ROOT / "data" / "covariates" / "generation.csv"

# CEA names of the thermal stations whose coordinates (WRI Global Power Plant Database) lie inside the
# Singrauli region bbox. Phase 3 replaces this list with the registry.
REGION_STATIONS = (
    "ANPARA C TPS",
    "ANPARA TPS",
    "MAHAN TPP",
    "OBRA TPS",
    "RIHAND STPS",
    "SASAN UMTPP",
    "SINGRAULI STPS",
    "VINDHYACHAL STPS",
)
# Rows that do not come from a CEA report. The source link is still to be added by hand.
MANUAL_EVENTS = [
    {
        "unit_or_facility": "ALL",
        "start": "2020-03-25",
        "end": "2020-05-31",
        "type": "lockdown",
        "direction": "low",
        "source_url": "TODO add a source link: India national COVID-19 lockdown, phases 1-4",
        "ongoing_at_report": False,
        "reason": "national lockdown",
    }
]
EVENT_COLUMNS = [
    "unit_or_facility", "start", "end", "type", "direction", "source_url",
    "unit_no", "capacity_out_mw", "outage_kind", "ongoing_at_report", "duration_days", "reason",
]  # fmt: skip
DATE_TIME = re.compile(r"^\s*(\d{2}/\d{2}/\d{4})(?:\s+\d{2}:\d{2})?\s*$")
NUMBER = re.compile(r"^\s*\d+(\.\d+)?\s*$")
FILE_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")
OUTAGE_KINDS = ("planned", "forced_major", "forced_minor", "others")


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()


def _is_number(value: object) -> bool:
    """Numbers arrive as numbers or as text such as '500.00'."""
    if isinstance(value, str):
        return bool(NUMBER.match(value))
    return isinstance(value, int | float)


def _split(cells: list) -> tuple[list[float], list[str], list[str]]:
    """Cells of a report row as (numbers, date-times, other text), each in row order."""
    numbers = [float(c) for c in cells if _is_number(c)]
    dates = [c for c in cells if isinstance(c, str) and DATE_TIME.match(c)]
    text = [c for c in cells if isinstance(c, str) and not DATE_TIME.match(c) and not _is_number(c)]
    return numbers, dates, text


def _day(text: str) -> date:
    return pd.to_datetime(DATE_TIME.match(text).group(1), format="%d/%m/%Y").date()


def _station_rows(sheet: pd.DataFrame):
    """Yield (station, cells after the station name without empty ones) for the region's stations."""
    for row in sheet.itertuples(index=False):
        cells = [c for c in row if not pd.isna(c)]
        for i, cell in enumerate(cells):
            if _clean(cell) in REGION_STATIONS:
                yield _clean(cell), cells[i + 1 :]
                break


def parse_ongoing_outages(sheet: pd.DataFrame, report_day: date, source: str) -> list[dict]:
    """Sub-Report 10: station, unit, four MW columns, outage start, optional expected return, reason."""
    events = []
    for station, cells in _station_rows(sheet):
        numbers, dates, text = _split(cells)
        if not dates or len(numbers) < 5:
            continue
        megawatts = dict(zip(OUTAGE_KINDS, numbers[1:5], strict=True))
        start = _day(dates[0])
        returned = _day(dates[1]) if len(dates) > 1 and _day(dates[1]) <= report_day else None
        events.append(
            {
                "unit_or_facility": station,
                "start": start,
                "end": returned or report_day,
                "unit_no": int(numbers[0]),
                "capacity_out_mw": sum(megawatts.values()),
                "outage_kind": max(megawatts, key=megawatts.get),
                "ongoing_at_report": returned is None,
                "reason": _clean(text[-1]).strip(" /") if text else "",
                "source_url": source,
            }
        )
    return events


def parse_finished_outages(sheet: pd.DataFrame, source: str) -> list[dict]:
    """Sub-Report 14: station, unit, capacity, outage start, synchronisation date, remarks."""
    events = []
    for station, cells in _station_rows(sheet):
        numbers, dates, text = _split(cells)
        if len(dates) < 2 or len(numbers) < 2:
            continue
        events.append(
            {
                "unit_or_facility": station,
                "start": _day(dates[0]),
                "end": _day(dates[1]),
                "unit_no": int(numbers[0]),
                "capacity_out_mw": numbers[1],
                "outage_kind": "",
                "ongoing_at_report": False,
                "reason": _clean(text[-1]).strip(" /") if text else "",
                "source_url": source,
            }
        )
    return events


def merge_events(events: list[dict]) -> pd.DataFrame:
    """One row per (station, unit, start): a finished outage replaces the same outage seen while running,
    and of several sightings of a running outage the latest is kept."""
    frame = pd.DataFrame(events)
    if frame.empty:
        return pd.DataFrame(columns=EVENT_COLUMNS)
    frame = frame[frame["capacity_out_mw"] > 0]
    frame = frame.sort_values(["ongoing_at_report", "end"], ascending=[False, True])
    frame = frame.drop_duplicates(["unit_or_facility", "unit_no", "start"], keep="last")
    frame["type"], frame["direction"] = "outage", "low"
    frame["duration_days"] = (pd.to_datetime(frame["end"]) - pd.to_datetime(frame["start"])).dt.days
    return frame.sort_values(["start", "unit_or_facility", "unit_no"])[EVENT_COLUMNS]


def parse_generation(sheet: pd.DataFrame, day: date) -> list[dict]:
    """Sub-Report 2: per station the monitored capacity, today's actual generation (MU) and the capacity
    under outage. The columns are found from the header text, because their positions change over the years."""
    header = sheet.head(8).map(lambda c: _clean(c).upper() if isinstance(c, str) else "")

    def column(*words: str) -> int | None:
        hits = [col for col in header.columns if any(all(w in cell for w in words) for cell in header[col])]
        return hits[0] if hits else None

    capacity, actual, outage = column("MONITORED"), column("TODAY", "ACTUAL"), column("CAP", "OUTAGE")
    if actual is None:
        raise ValueError('no "today\'s actual" generation column found')
    rows = []
    for _, row in sheet.iterrows():
        station = next((_clean(c) for c in row if isinstance(c, str) and _clean(c) in REGION_STATIONS), None)
        if station is None or pd.isna(row[actual]):
            continue
        rows.append(
            {
                "facility_name": station,
                "date": day,
                "generation_mwh": round(float(row[actual]) * 1000, 1),  # 1 MU = 1 GWh
                "monitored_capacity_mw": float(row[capacity]) if capacity is not None else None,
                "capacity_under_outage_mw": float(row[outage]) if outage is not None else None,
            }
        )
    return rows


def _file_day(path: Path) -> date:
    return date.fromisoformat(FILE_DATE.search(path.name).group(1))


def main() -> None:
    events: list[dict] = []
    for path in sorted(RAW_DIR.glob("dgr10-*.xls")):
        source = f"CEA Daily Maintenance Report, Sub-Report 10, {_file_day(path)} ({path.name})"
        events += parse_ongoing_outages(pd.read_excel(path, header=None), _file_day(path), source)
    for path in sorted(RAW_DIR.glob("dgr14-*.xls")):
        sheet = pd.read_excel(path, header=None)
        source = f"CEA Recommissioning Report, Sub-Report 14, {_file_day(path)} ({path.name})"
        events += parse_finished_outages(sheet, source)
    outages = merge_events(events)
    manual = pd.DataFrame(MANUAL_EVENTS).reindex(columns=EVENT_COLUMNS)
    pd.concat([manual, outages], ignore_index=True).to_csv(EVENTS_PATH, index=False, lineterminator="\n")
    print(f"{EVENTS_PATH.relative_to(REPO_ROOT)}: {len(manual)} hand-kept rows, {len(outages)} outages")

    generation: list[dict] = []
    for path in sorted((RAW_DIR / "generation").glob("dgr2-*.xls")):
        try:
            generation += parse_generation(pd.read_excel(path, header=None), _file_day(path))
        except ValueError as exc:
            print(f"  skipped {path.name}: {exc}")
    if generation:
        frame = pd.DataFrame(generation).sort_values(["date", "facility_name"])
        GENERATION_PATH.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(GENERATION_PATH, index=False, lineterminator="\n")
        print(f"{GENERATION_PATH.relative_to(REPO_ROOT)}: {len(frame)} rows, {frame['date'].nunique()} days")


if __name__ == "__main__":
    main()

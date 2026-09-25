"""Build the published results tree from the QuantConnect backtest exports.

Run from any directory; paths are resolved from this file.

    python analysis/build_results.py --import-from <folder with the raw exports>
    python analysis/build_results.py
    python analysis/build_results.py --check

The first form copies the exports that belong to this repository into
results/raw (gzip-compressed, SHA-256 of each uncompressed file in
results/raw/MANIFEST.csv), the part of QuantConnect's backtest lists that
covers this repository's projects, each QuantConnect report into its run
folder and this repository's part of code_hashes.json into
results/provenance, then builds. code_hashes.json is not a QuantConnect
export: in the exports whose embedded code carried it, one docstring
paragraph was rewritten to leave out the names of the other 2024 team
members, and the file records, per export and code file, the SHA-256 as run
on QuantConnect and as published. Every later run reads only results/raw and
results/provenance, and stops if a published hash does not match the code in
results/raw. --check verifies the raw files against the manifest, rebuilds
into a temporary directory and compares the result with the files in
results/; it exits 1 and lists every difference, including files under
results/ that the build does not write.

The data check uses rank_space.DailyCaps, the class the algorithm runs, to roll
the logged market caps forward, so the build imports rank_space.py from the
repository root.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import importlib.util
import io
import json
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from pandas.tseries.holiday import (
    AbstractHolidayCalendar,
    GoodFriday,
    Holiday,
    USLaborDay,
    USMartinLutherKingJr,
    USMemorialDay,
    USPresidentsDay,
    USThanksgivingDay,
    nearest_workday,
    sunday_to_monday,
)

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "results"
RAW = RESULTS / "raw"
MANIFEST_NAME = "MANIFEST.csv"
NEW_YORK = ZoneInfo("America/New_York")
EXPORT_DATE = "2026-09-25"
REPORT_NAME = "qc_report.html"
CHARTS_RAW = "charts.json.gz"
SAME_SAMPLE_TOLERANCE_S = 60
TURNOVER_TOLERANCE_S = 36 * 3600
GROSS_EXPOSURE_MARK = 1.9
DAYS_PER_YEAR = 365.25
# SHA-256 of each code file as QuantConnect ran it and as published in results/raw. The source file
# covers the exports of both strategy repositories; results/provenance keeps this repository's keys.
PROVENANCE_SOURCE = "code_hashes.json"
PROVENANCE = "provenance/code_hashes.json"
PROVENANCE_ABOUT = (
    "Not a QuantConnect export. In the exports whose embedded code carried it, one docstring paragraph "
    "was rewritten to leave out the names of the other 2024 team members; every other byte of each export "
    "is as QuantConnect returned it. For each export key and code file: as_run is the SHA-256 of the UTF-8 "
    "text QuantConnect ran, published the SHA-256 of the text in results/raw, and names_removed whether "
    "the two differ."
)


@dataclass(frozen=True)
class Run:
    key: str
    label: str
    folder: str
    kind: str  # "v4", "superseded", "reference", "reproduction" or "margin"
    version: str
    role: str  # "current", "superseded", "check" or "reference"


V4_WINDOWS = (
    ("sa__v4_2011", "2011_2012"),
    ("sa__v4_2013", "2013_2014"),
    ("sa__v4_2015", "2015_2016"),
    ("sa__v4_2017", "2017_2018"),
    ("sa__v4_2018", "2018_2019"),
    ("sa__v4_2020", "2020_2021"),
    ("sa__v4_2022", "2022_2023"),
    ("sa__v4_2024", "2024"),
)


def window_words(window: str) -> str:
    return " to ".join(window.split("_"))


RUNS = (
    *(Run(key, f"v4, {window_words(window)}", f"v4/{window}", "v4", "v4", "current")
      for key, window in V4_WINDOWS),
    Run("sa__v3_2011", "v3, 2011 to 2017 chunk", "superseded/v3_2011_2017", "superseded", "v3", "superseded"),
    Run("sa__v3_2018", "v3, 2018 to 2024 chunk", "superseded/v3_2018_2024", "superseded", "v3", "superseded"),
    Run("sa__v2", "v2, legs renormalised daily", "superseded/v2_2018_2024", "superseded", "v2", "superseded"),
    Run("sa__v1", "v1, dense paper weights on every rank", "superseded/v1_2010_2024", "superseded", "v1",
        "superseded"),
    Run("rerun__sa_v3_2018", "v3 re-run, 2018 to 2024", "checks/reproduction", "reproduction", "v3 re-run",
        "check"),
    Run("control__sa_v3_2018_recorded_code", "v3 control, recorded main.py, 2018 to 2024", "checks/reproduction",
        "reproduction", "v3 control", "check"),
    Run("check__v3_via_params_2018", "v4 code with v3 parameters, 2018 to 2024", "checks/reproduction",
        "reproduction", "v3 via v4 code", "check"),
    Run("rerun__sa_v3_2011", "v3 re-run, 2011 to 2017", "checks/reproduction", "reproduction", "v3 re-run", "check"),
    Run("sa__half_leg_2011", "v3 half legs, 2011 to 2017", "checks/margin/half_leg_2011_2017", "margin",
        "v3 half legs", "check"),
    Run("sa__half_leg_2018", "v3 half legs, 2018 to 2024", "checks/margin/half_leg_2018_2024", "margin",
        "v3 half legs", "check"),
    Run("audit__spy_2015_2019", "Reference, SPY buy and hold 2015 to 2019", "reference/spy_2015_2019", "reference",
        "reference", "reference"),
)
RUN_BY_KEY = {run.key: run for run in RUNS}
FOLDER_KINDS = ("v4", "superseded", "reference")

PROBE_KEYS = ("probe2__2012", "probe2__2019")
CAP_PROBE_KEY = "capprobe2__2019"
ENGINES_KEY = "engines__original_runs"
RAW_ONLY = (*PROBE_KEYS, CAP_PROBE_KEY, ENGINES_KEY)

# QuantConnect's backtests/list, exported with includeStatistics for every project involved in either
# strategy repository; raw/ keeps the projects that hold this repository's backtests.
BACKTEST_LISTS_SOURCE = "backtest_lists.json"
BACKTEST_LISTS_RAW = "backtest_lists.json.gz"
BACKTEST_LISTS_CSV = "checks/backtest_lists.csv"
STRATEGY_PROJECT = "36836415"
BACKTEST_LIST_PROJECTS = (
    (STRATEGY_PROJECT, "the strategy"),
    ("36924052", "the control re-run of the recorded v3 code"),
    ("36922759", "the reference runs"),
    ("36923739", "the `market_cap` probe"),
    ("36924577", "the cap probe"),
)
# Backtests in those projects that are not published here, by backtest id, with the reason.
NOT_PUBLISHED = {
    "d611b8a8fb19c48188e250a4c75a5297": "belongs to the DCF repository, automated-dcf-point-in-time, as its "
                                        "reference run audit__basket_2023",
    "d8437e5465b8ac3e0e57c1793df5a2ca": "discarded probe version (the first probe had no once-per-day guard and "
                                        "counted repeat calls on the same day); re-run as probe2__2012",
    "783c48a6748f1768dc417308cc432b26": "discarded probe version (the first probe had no once-per-day guard and "
                                        "counted repeat calls on the same day); re-run as probe2__2019",
    "3ea271f9598e34f6872c7aa6911fa3c8": "discarded probe version (the first run of the cap probe); replaced 88 "
                                        "seconds later by capprobe2__2019, the run whose log is published; what "
                                        "changed between the two is not recorded",
}
BACKTEST_LIST_COLUMNS = (
    "project_id", "project_name", "backtest_id", "name", "created", "completed", "status", "error",
    "parameters", "net_profit", "sharpe", "drawdown", "published_key", "note",
)

# results/checks/reproduction: (chunk, key, role in the comparison).
REPRODUCTION = (
    ("2018", "sa__v3_2018", "Recorded v3 run"),
    ("2018", "rerun__sa_v3_2018", "Re-run, refactored code"),
    ("2018", "control__sa_v3_2018_recorded_code", "Control, recorded main.py"),
    ("2018", "check__v3_via_params_2018", "v4 code, v3 parameters"),
    ("2011", "sa__v3_2011", "Recorded v3 run"),
    ("2011", "rerun__sa_v3_2011", "Re-run, refactored code"),
)
RECORDED = {"2018": "sa__v3_2018", "2011": "sa__v3_2011"}
RERUN = {"2018": "rerun__sa_v3_2018", "2011": "rerun__sa_v3_2011"}
# The runs of 25 September on the 2018 chunk, expected to agree with each other exactly.
SAME_DAY_2018 = ("rerun__sa_v3_2018", "control__sa_v3_2018_recorded_code", "check__v3_via_params_2018")
CHUNK_WORDS = {"2018": "2018 to 2024", "2011": "2011 to 2017"}
# results/checks/margin: (chunk, re-run at the v3 leg weight, the same code at half the leg weight).
MARGIN_PAIRS = (("2011", "rerun__sa_v3_2011", "sa__half_leg_2011"),
                ("2018", "rerun__sa_v3_2018", "sa__half_leg_2018"))

# LEAN enumerations, as used in the order and trade records of the exports.
ORDER_STATUS = {
    0: "New", 1: "Submitted", 2: "PartiallyFilled", 3: "Filled", 5: "Canceled",
    6: "None", 7: "Invalid", 8: "CancelPending", 9: "UpdateSubmitted",
}
ORDER_TYPE = {
    0: "Market", 1: "Limit", 2: "StopMarket", 3: "StopLimit", 4: "MarketOnOpen",
    5: "MarketOnClose", 6: "OptionExercise", 7: "LimitIfTouched", 8: "ComboMarket",
    9: "ComboLimit", 10: "ComboLegLimit", 11: "TrailingStop",
}
ORDER_DIRECTION = {0: "Buy", 1: "Sell", 2: "Hold"}
TRADE_DIRECTION = {0: "Long", 1: "Short"}

EQUITY_SERIES = (
    ("Benchmark", "Benchmark", "spy_benchmark", 4),
    ("Drawdown", "Equity Drawdown", "drawdown_pct", 4),
    ("Exposure", "Equity - Long Ratio", "exposure_long", 4),
    ("Exposure", "Equity - Short Ratio", "exposure_short", 4),
)
RANK_SERIES = "rank space, paper weights, before costs"
NAME_SERIES = "name space, realised, after costs"
RANK_COLUMN = "rank_space_paper_weights_before_costs_pct"
NAME_COLUMN = "name_space_realised_after_costs_pct"

RUNS_COLUMNS = (
    "key", "version", "role", "label", "folder", "project_id", "backtest_id", "created", "lean_version",
    "configured_start", "configured_end", "first_date_traded", "last_date_traded",
    "order_cap_hit", "parameters", "net_profit", "cagr", "sharpe", "psr",
    "max_drawdown", "beta", "orders", "orders_filled", "orders_invalid",
    "orders_canceled", "orders_open_at_stop", "closed_trades", "win_rate",
    "total_fees", "fees_pct_of_start", "portfolio_turnover", "start_equity",
    "end_equity", "paper_weights_before_costs", "code_sha256_as_run", "code_sha256_published",
    "rank_space_sha256_as_run", "rank_space_sha256_published",
)
SUMMARY_COLUMNS = (
    "window", "key", "backtest_id", "configured_start", "configured_end", "first_fill", "last_fill",
    "months_covered", "net_profit_pct", "cagr_pct", "sharpe", "psr_pct", "max_drawdown_pct", "beta",
    "total_fees", "fees_pct_of_start", "turnover_per_day_pct", "orders", "orders_filled", "orders_canceled",
    "orders_invalid", "orders_open_at_stop", "closed_trades", "last_sample",
    "paper_weights_before_costs_pct", "paper_weights_annualised_pct", "realised_after_costs_pct",
    "order_cap_hit", "order_cap_date",
)
TIMING_COLUMNS = (
    "window", "first_fill", "last_fill", "trading_days", "passes", "passes_midnight", "passes_close",
    "passes_close_pct", "passes_on_closed_days", "passes_repeating_a_close", "opens_with_fills",
    "opens_without_fills",
    "opens_with_two_passes", "orders_filled", "filled_from_close_passes", "filled_from_close_passes_pct",
    "orders", "orders_canceled", "orders_canceled_pct", "canceled_from_close_passes",
    "canceled_replaced_at_next_pass",
)


CALENDAR_YEAR_COLUMNS = (
    "window", "year", "part", "from_date", "to_date", "trading_days", "paper_weights_cumulative_pct",
    "paper_weights_annualised_pct", "table1_pct", "difference_pts",
)
# Li and Papanicolaou, arXiv:2410.06568v1, Table 1, column "rank space, parametric model" (before costs),
# per calendar year, checked against the arXiv HTML of v1 on 25 September 2026.
PAPER_TABLE1 = {
    2011: 40.14, 2012: 41.06, 2013: 27.92, 2014: 43.82, 2015: 41.78, 2016: 61.86,
    2017: 30.58, 2018: 27.78, 2019: 41.42, 2020: 25.06, 2021: 37.60, 2022: 36.79,
}
TRADING_DAYS_PER_YEAR = 252


class NyseCalendar(AbstractHolidayCalendar):
    """NYSE full-day holidays as scheduled from 2009 on (New Year's Day moves to Monday only)."""

    rules = [
        Holiday("New Year's Day", month=1, day=1, observance=sunday_to_monday),
        USMartinLutherKingJr,
        USPresidentsDay,
        GoodFriday,
        USMemorialDay,
        Holiday("Juneteenth", month=6, day=19, start_date="2022-01-01", observance=nearest_workday),
        Holiday("Independence Day", month=7, day=4, observance=nearest_workday),
        USLaborDay,
        USThanksgivingDay,
        Holiday("Christmas Day", month=12, day=25, observance=nearest_workday),
    ]


# Unscheduled full-day closures in the v4 windows: Hurricane Sandy, and the national day of mourning
# for President George H. W. Bush.
NYSE_UNSCHEDULED_CLOSURES = ("2012-10-29", "2012-10-30", "2018-12-05")


# --------------------------------------------------------------------------- helpers
def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def text_sha256(text: str) -> str:
    return sha256(text.encode("utf-8"))


def gzip_bytes(data: bytes) -> bytes:
    """Deterministic gzip: no file name and a zero timestamp in the header."""
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0, compresslevel=9) as handle:
        handle.write(data)
    return buffer.getvalue()


def number(text: object) -> float | None:
    """Parse QuantConnect's statistic strings such as "97.851%", "$1388.79" or "-0.149"."""
    if text is None:
        return None
    cleaned = str(text).replace("$", "").replace("%", "").replace(",", "").strip()
    if cleaned == "":
        return None
    return float(cleaned)


def ny_date_from_seconds(seconds: float) -> str:
    return dt.datetime.fromtimestamp(seconds, NEW_YORK).date().isoformat()


def ny_date_from_iso(text: str | None) -> str:
    if not text:
        return ""
    moment = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    return moment.astimezone(NEW_YORK).date().isoformat()


def ny_time(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(NEW_YORK)


def trading_days(first: str, last: str) -> list[str]:
    """NYSE sessions from first to last inclusive (ISO dates), by NyseCalendar and the unscheduled closures."""
    closed = {day.date().isoformat() for day in NyseCalendar().holidays(first, last)}
    closed.update(NYSE_UNSCHEDULED_CLOSURES)
    return [day.date().isoformat() for day in pd.date_range(first, last, freq="D")
            if day.weekday() < 5 and day.date().isoformat() not in closed]


def days_between(first: str, last: str) -> int:
    return (dt.date.fromisoformat(last) - dt.date.fromisoformat(first)).days


def duration_days(text: str | None) -> float | None:
    """Convert a .NET TimeSpan string ("18.09:01:15.7475094" or "00:30:00") to days."""
    if not text:
        return None
    match = re.fullmatch(r"(?:(\d+)\.)?(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if match is None:
        return None
    days, hours, minutes, seconds = match.groups()
    total = int(days or 0) + int(hours) / 24 + int(minutes) / 1440 + float(seconds) / 86400
    return round(total, 4)


def format_parameters(parameter_set: object) -> str:
    if not parameter_set:
        return "code defaults"
    if isinstance(parameter_set, dict):
        return "; ".join(f"{name}={value}" for name, value in parameter_set.items())
    return json.dumps(parameter_set, separators=(",", ":"))


def snake(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def csv_text(frame: pd.DataFrame) -> str:
    return frame.to_csv(index=False, lineterminator="\n")


def json_text(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def normalise(data: bytes) -> bytes:
    """Line endings as git would store them, so a CRLF checkout still compares equal."""
    return data.replace(b"\r\n", b"\n")


def daily_caps_class():
    """rank_space.DailyCaps, loaded from the repository root without changing sys.path."""
    spec = importlib.util.spec_from_file_location("rank_space", REPO / "rank_space.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.DailyCaps


# --------------------------------------------------------------------------- import
def import_exports(source: Path) -> None:
    """Copy this repository's raw exports and reports out of the export folder."""
    RAW.mkdir(parents=True, exist_ok=True)
    rows = []
    for key in (*(run.key for run in RUNS), *RAW_ONLY):
        path = source / f"{key}.json"
        data = path.read_bytes()
        document = json.loads(data)
        meta = document.get("meta") if isinstance(document, dict) else None
        if isinstance(meta, dict) and meta.get("key", key) != key:
            raise SystemExit(f"{path.name}: meta.key is {meta.get('key')!r}, expected {key!r}")
        (RAW / f"{key}.json.gz").write_bytes(gzip_bytes(data))
        rows.append({
            "file": f"raw/{key}.json.gz", "source": path.name, "source_sha256": sha256(data),
            "sha256": sha256(data), "bytes": len(data),
        })

    charts_path = source / "charts__all.json"
    charts_bytes = charts_path.read_bytes()
    charts = json.loads(charts_bytes)
    subset = {run.key: charts[run.key] for run in RUNS if run.key in charts}
    subset_bytes = (json.dumps(subset, separators=(",", ":")) + "\n").encode("utf-8")
    (RAW / CHARTS_RAW).write_bytes(gzip_bytes(subset_bytes))
    rows.append({
        "file": f"raw/{CHARTS_RAW}", "source": f"{charts_path.name} (keys {', '.join(subset)})",
        "source_sha256": sha256(charts_bytes), "sha256": sha256(subset_bytes), "bytes": len(subset_bytes),
    })

    lists_path = source / BACKTEST_LISTS_SOURCE
    lists_bytes = lists_path.read_bytes()
    lists = json.loads(lists_bytes)
    kept = [project for project, _ in BACKTEST_LIST_PROJECTS]
    lists_subset = {key: value for key, value in lists.items() if key != "projects"}
    # The source file's own "exported" field reads 2026-09-26, a typing slip at export time: the
    # file was written on 2026-09-25 (its timestamp), the same day as the other exports. The
    # slice records the true date and keeps the original value next to it.
    if lists_subset.get("exported") == "2026-09-26":
        lists_subset["exported_as_written"] = lists_subset["exported"]
        lists_subset["exported"] = "2026-09-25"
    lists_subset["projects"] = {project: lists["projects"][project] for project in kept}
    lists_subset_bytes = (json.dumps(lists_subset, indent=1, ensure_ascii=False) + "\n").encode("utf-8")
    (RAW / BACKTEST_LISTS_RAW).write_bytes(gzip_bytes(lists_subset_bytes))
    rows.append({
        "file": f"raw/{BACKTEST_LISTS_RAW}", "source": f"{lists_path.name} (projects {', '.join(kept)})",
        "source_sha256": sha256(lists_bytes), "sha256": sha256(lists_subset_bytes),
        "bytes": len(lists_subset_bytes),
    })

    hashes_path = source / PROVENANCE_SOURCE
    hashes_bytes = hashes_path.read_bytes()
    all_hashes = json.loads(hashes_bytes)
    keys = {*(run.key for run in RUNS), *RAW_ONLY}
    provenance = {"about": PROVENANCE_ABOUT,
                  "hashes": {key: value for key, value in all_hashes.items() if key in keys}}
    provenance_bytes = (json.dumps(provenance, indent=1, ensure_ascii=False) + "\n").encode("utf-8")
    (RESULTS / PROVENANCE).parent.mkdir(parents=True, exist_ok=True)
    (RESULTS / PROVENANCE).write_bytes(provenance_bytes)
    rows.append({
        "file": PROVENANCE,
        "source": f"{hashes_path.name} (keys {', '.join(provenance['hashes'])}; not a QuantConnect export: "
                  "written when one docstring paragraph of the embedded code was rewritten to leave out the "
                  "other team members' names, it gives the SHA-256 of each code file as run and as published)",
        "source_sha256": sha256(hashes_bytes), "sha256": sha256(provenance_bytes), "bytes": len(provenance_bytes),
    })

    for run in RUNS:
        path = source / f"{run.key}__report.html"
        if not path.exists():
            continue
        data = path.read_bytes()
        destination = RESULTS / run.folder / REPORT_NAME
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        rows.append({
            "file": f"{run.folder}/{REPORT_NAME}", "source": path.name, "source_sha256": sha256(data),
            "sha256": sha256(data), "bytes": len(data),
        })

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=["file", "source", "source_sha256", "sha256", "bytes"],
                            lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    (RAW / MANIFEST_NAME).write_bytes(buffer.getvalue().encode("utf-8"))
    print(f"imported {len(rows)} files from {source}")


def manifest_files(results: Path) -> list[str]:
    manifest = results / "raw" / MANIFEST_NAME
    if not manifest.exists():
        return []
    with manifest.open(encoding="utf-8", newline="") as handle:
        return [row["file"] for row in csv.DictReader(handle)]


def verify_manifest(results: Path) -> list[str]:
    """Check every file listed in raw/MANIFEST.csv against its recorded SHA-256."""
    manifest = results / "raw" / MANIFEST_NAME
    if not manifest.exists():
        return [f"missing {manifest.relative_to(results.parent).as_posix()}"]
    problems = []
    with manifest.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            path = results / row["file"]
            if not path.exists():
                problems.append(f"missing results/{row['file']}")
                continue
            data = path.read_bytes()
            if path.suffix == ".gz":
                data = gzip.decompress(data)
            if row["sha256"] not in (sha256(data), sha256(normalise(data))):
                problems.append(f"hash mismatch results/{row['file']}")
    return problems


# --------------------------------------------------------------------------- load
def load_raw(raw: Path) -> tuple[dict[str, dict], dict[str, dict]]:
    exports = {}
    for key in (*(run.key for run in RUNS), *RAW_ONLY):
        path = raw / f"{key}.json.gz"
        if not path.exists():
            raise SystemExit(f"missing {path}; run with --import-from <export folder> first")
        exports[key] = json.loads(gzip.decompress(path.read_bytes()))
    charts = json.loads(gzip.decompress((raw / CHARTS_RAW).read_bytes()))
    return exports, charts


def load_backtest_lists(raw: Path) -> dict:
    path = raw / BACKTEST_LISTS_RAW
    if not path.exists():
        raise SystemExit(f"missing {path}; run with --import-from <export folder> first")
    return json.loads(gzip.decompress(path.read_bytes()))


def load_provenance(raw: Path, exports: dict[str, dict]) -> dict[str, dict]:
    """The hashes of results/provenance/code_hashes.json, checked against the code in the raw exports.

    Every export with code must have an entry for exactly its code files; each "published" hash must
    be the SHA-256 of that file's text in raw/, and "names_removed" must say whether it differs from
    the "as_run" hash. Anything else stops the build.
    """
    path = raw.parent / PROVENANCE
    if not path.exists():
        raise SystemExit(f"missing {path}; run with --import-from <export folder> first")
    hashes = json.loads(path.read_text(encoding="utf-8"))["hashes"]
    with_code = {key for key, export in exports.items() if isinstance(export.get("code"), dict)}
    if set(hashes) != with_code:
        raise SystemExit(f"{PROVENANCE} covers {sorted(hashes)}, the exports with code are {sorted(with_code)}")
    for key in sorted(with_code):
        code = exports[key]["code"]
        if set(hashes[key]) != set(code):
            raise SystemExit(f"{PROVENANCE}: {key} lists {sorted(hashes[key])}, the export has {sorted(code)}")
        for name, text in code.items():
            entry = hashes[key][name]
            if entry["published"] != text_sha256(text):
                raise SystemExit(f"{PROVENANCE}: published hash of {key}/{name} does not match raw/")
            if entry["names_removed"] != (entry["as_run"] != entry["published"]):
                raise SystemExit(f"{PROVENANCE}: names_removed of {key}/{name} disagrees with its hashes")
    return hashes


def as_run_hashes(provenance: dict[str, dict], key: str) -> dict[str, str]:
    """SHA-256 of each code file of an export as QuantConnect ran it."""
    return {name: entry["as_run"] for name, entry in provenance.get(key, {}).items()}


def list_number(value: object) -> float | None:
    return None if value is None else float(value)


def backtest_list_rows(lists: dict, exports: dict[str, dict]) -> list[dict]:
    """One row per backtest QuantConnect lists in the projects of BACKTEST_LIST_PROJECTS.

    Each backtest is either a published run (matched by backtest id to the meta of an export in raw/)
    or has a reason in NOT_PUBLISHED; anything else stops the build. For a published run the listed
    creation time and headline statistics must equal those of its export.
    """
    published = {}
    for key, export in exports.items():
        meta = export.get("meta") if isinstance(export, dict) else None
        if isinstance(meta, dict) and meta.get("backtestId"):
            published[meta["backtestId"]] = key
    rows = []
    for project, _ in BACKTEST_LIST_PROJECTS:
        entry = lists["projects"][project]
        backtests = sorted(entry["backtests"], key=lambda item: (item["created"], item["backtestId"]))
        if entry.get("count") is not None and entry["count"] != len(backtests):
            raise SystemExit(f"project {project}: count {entry['count']} but {len(backtests)} backtests listed")
        for item in backtests:
            backtest_id = item["backtestId"]
            key = published.get(backtest_id, "")
            if key:
                export = exports[key]
                statistics = export.get("statistics") or {}
                expected = {
                    "created": export["meta"].get("created"),
                    "netProfit": number(statistics.get("Net Profit")),
                    "sharpeRatio": number(statistics.get("Sharpe Ratio")),
                    "drawdown": number(statistics.get("Drawdown")),
                }
                for field, value in expected.items():
                    listed = item.get(field)
                    if field != "created":
                        listed = list_number(listed)
                        value = 0.0 if value is None else value
                    if listed != value:
                        raise SystemExit(f"backtest list and export {key} disagree on {field}: {listed} vs {value}")
                if str(item["projectId"]) != str(export["meta"].get("projectId")):
                    raise SystemExit(f"backtest list and export {key} disagree on the project")
                if key in RUN_BY_KEY:
                    note = f"runs.csv; files in {RUN_BY_KEY[key].folder}/"
                else:
                    note = "listed in checks/data/README.md; files in checks/data/"
            elif backtest_id in NOT_PUBLISHED:
                note = "not published: " + NOT_PUBLISHED[backtest_id]
            else:
                raise SystemExit(f"backtest {backtest_id} ({item['name']}) in project {project} is neither "
                                 "published nor explained in NOT_PUBLISHED")
            error = (item.get("error") or "").strip()
            rows.append({
                "project_id": project,
                "project_name": entry["name"],
                "backtest_id": backtest_id,
                "name": item["name"],
                "created": item["created"],
                "completed": "yes" if item.get("completed") else "no",
                "status": item.get("status") or "",
                "error": error.splitlines()[0] if error else "",
                "parameters": format_parameters(item.get("parameterSet")),
                "net_profit": list_number(item.get("netProfit")),
                "sharpe": list_number(item.get("sharpeRatio")),
                "drawdown": list_number(item.get("drawdown")),
                "published_key": key,
                "note": note,
            })
    return rows


def run_chart(key: str, export: dict, charts: dict) -> dict:
    """Chart data of a run: the separate chart export where it has the run, else the export's own."""
    return charts.get(key) or export.get("charts") or {}


def lean_version(export: dict, engines: dict) -> str:
    """LEAN build of a backtest: from its own export, else from the export of the original runs."""
    meta = export.get("meta") or {}
    if meta.get("leanVersion"):
        return meta["leanVersion"]
    server = export.get("serverStatistics") or {}
    if server.get("LEAN Version"):
        return server["LEAN Version"]
    original = engines.get(meta.get("backtestId"), {})
    return (original.get("serverStatistics") or {}).get("LEAN Version", "")


def python_files(export: dict) -> dict[str, str]:
    """The Python files QuantConnect stored with the backtest (research.ipynb does not run)."""
    return {name: text for name, text in (export.get("code") or {}).items() if name.endswith(".py")}


def code_default(export: dict, name: str) -> str:
    """Default of a project parameter in the main.py that ran, e.g. get_parameter("leg_weight", 0.05)."""
    match = re.search(r'get_parameter\("' + re.escape(name) + r'",\s*([^)]+)\)',
                      (export.get("code") or {}).get("main.py", ""))
    return match.group(1).strip().strip("\"'") if match else ""


def effective_parameter(export: dict, name: str) -> str:
    parameters = export.get("parameterSet") or {}
    if isinstance(parameters, dict) and name in parameters:
        return str(parameters[name])
    return code_default(export, name)


# --------------------------------------------------------------------------- frames
def series_frame(points: list, column: str) -> pd.DataFrame:
    """One chart series as (ts, value); for candle series the close is the last element."""
    return pd.DataFrame(
        {"ts": [int(point[0]) for point in points], column: [float(point[-1]) for point in points]}
    )


def attach(frame: pd.DataFrame, part: pd.DataFrame, direction: str, tolerance: int) -> pd.DataFrame:
    """Join a chart series to the equity samples by nearest timestamp within a tolerance."""
    return pd.merge_asof(frame.sort_values("ts"), part.sort_values("ts"), on="ts",
                         direction=direction, tolerance=tolerance)


def has_equity(chart: dict) -> bool:
    return bool(chart.get("Strategy Equity", {}).get("Equity"))


def equity_frame(chart: dict) -> pd.DataFrame:
    frame = series_frame(chart["Strategy Equity"]["Equity"], "equity")
    frame["equity"] = frame["equity"].round(2)
    for chart_name, series_name, column, decimals in EQUITY_SERIES:
        points = chart.get(chart_name, {}).get(series_name)
        if points:
            part = series_frame(points, column)
            part[column] = part[column].round(decimals)
            # The series share the equity samples' timestamps up to a one-second rounding.
            frame = attach(frame, part, "nearest", SAME_SAMPLE_TOLERANCE_S)
    turnover = chart.get("Portfolio Turnover", {}).get("Portfolio Turnover")
    if turnover:
        # QuantConnect stamps each turnover sample one day after the equity sample.
        part = series_frame(turnover, "portfolio_turnover")
        part["portfolio_turnover"] = part["portfolio_turnover"].round(6)
        frame = attach(frame, part, "forward", TURNOVER_TOLERANCE_S)
    frame.insert(0, "date", [ny_date_from_seconds(ts) for ts in frame["ts"]])
    if frame["date"].duplicated().any():
        raise SystemExit("two equity samples fall on the same New York date")
    return frame.drop(columns="ts").reset_index(drop=True)


def rank_frame(chart: dict, decimals: int | None = 4) -> pd.DataFrame | None:
    """The "Rank vs name" chart as a table, rounded to ``decimals`` (None keeps the exported values)."""
    series = chart.get("Rank vs name", {})
    if not series.get(RANK_SERIES):
        return None
    rank = series_frame(series[RANK_SERIES], RANK_COLUMN)
    name = series_frame(series[NAME_SERIES], NAME_COLUMN)
    frame = rank.merge(name, on="ts", how="outer").sort_values("ts")
    frame.insert(0, "date", [ny_date_from_seconds(ts) for ts in frame["ts"]])
    if decimals is not None:
        for column in frame.columns[2:]:
            frame[column] = frame[column].round(decimals)
    return frame.drop(columns="ts").reset_index(drop=True)


def orders_frame(orders: list[dict]) -> pd.DataFrame:
    return pd.DataFrame({
        "id": [order["id"] for order in orders],
        "submitted_utc": [order["time"] for order in orders],
        "filled_utc": [order.get("lastFillTime") or "" for order in orders],
        "symbol": [order["symbol"] for order in orders],
        "type": [ORDER_TYPE.get(order["type"], str(order["type"])) for order in orders],
        "direction": [ORDER_DIRECTION.get(order["direction"], str(order["direction"])) for order in orders],
        "quantity": [order["quantity"] for order in orders],
        "fill_price": [round(float(order["price"]), 6) for order in orders],
        "value": [round(float(order["value"]), 2) for order in orders],
        "fee": [round(float(order["fee"]), 4) for order in orders],
        "status": [ORDER_STATUS.get(order["status"], str(order["status"])) for order in orders],
        "tag": [order.get("tag") or "" for order in orders],
    })


def trades_frame(trades: list[dict]) -> pd.DataFrame:
    return pd.DataFrame({
        "symbol": [trade["symbol"] for trade in trades],
        "direction": [TRADE_DIRECTION.get(trade["direction"], str(trade["direction"])) for trade in trades],
        "quantity": [trade["quantity"] for trade in trades],
        "entry_utc": [trade["entryTime"] for trade in trades],
        "entry_price": [round(float(trade["entryPrice"]), 6) for trade in trades],
        "exit_utc": [trade["exitTime"] for trade in trades],
        "exit_price": [round(float(trade["exitPrice"]), 6) for trade in trades],
        "profit_loss": [round(float(trade["profitLoss"]), 2) for trade in trades],
        "total_fees": [round(float(trade["totalFees"]), 4) for trade in trades],
        "mae": [round(float(trade["mae"]), 2) for trade in trades],
        "mfe": [round(float(trade["mfe"]), 2) for trade in trades],
        "end_trade_drawdown": [round(float(trade.get("endTradeDrawdown", 0.0)), 2) for trade in trades],
        "duration_days": [duration_days(trade.get("duration")) for trade in trades],
        "is_win": [bool(trade["isWin"]) for trade in trades],
        "order_ids": [";".join(str(i) for i in trade.get("orderIds", [])) for trade in trades],
    })


def yearly_frame(equity: pd.DataFrame, ranks: pd.DataFrame | None, start_equity: float) -> pd.DataFrame:
    by_year = equity.assign(year=equity["date"].str[:4].astype(int)).groupby("year").tail(1)
    rows = []
    previous = start_equity
    for record in by_year.itertuples(index=False):
        row = {
            "year": record.year,
            "equity_date": record.date,
            "equity": round(record.equity, 2),
            "year_return_pct": round((record.equity / previous - 1.0) * 100.0, 2),
            "cumulative_return_pct": round((record.equity / start_equity - 1.0) * 100.0, 2),
        }
        previous = record.equity
        if ranks is not None:
            in_year = ranks[ranks["date"].str[:4].astype(int) == record.year]
            if len(in_year):
                last = in_year.iloc[-1]
                row["rank_vs_name_date"] = last["date"]
                row["paper_weights_before_costs_cum_pct"] = round(float(last[RANK_COLUMN]), 2)
                row["name_space_after_costs_cum_pct"] = round(float(last[NAME_COLUMN]), 2)
        rows.append(row)
    return pd.DataFrame(rows)


def gross_exposure(equity: pd.DataFrame) -> pd.Series | None:
    if "exposure_long" in equity and "exposure_short" in equity:
        return equity["exposure_long"] - equity["exposure_short"]
    return None


def exact_gross_exposure(chart: dict) -> pd.Series | None:
    """Long minus short exposure at each equity sample, from the chart values as exported.

    equity.csv rounds the exposures to four decimals; thresholds and medians are taken before
    that rounding, so a sample at 1.899983 does not count as 1.9.
    """
    frame = series_frame(chart["Strategy Equity"]["Equity"], "equity")
    for series_name, column in (("Equity - Long Ratio", "exposure_long"), ("Equity - Short Ratio", "exposure_short")):
        points = chart.get("Exposure", {}).get(series_name)
        if not points:
            return None
        frame = attach(frame, series_frame(points, column), "nearest", SAME_SAMPLE_TOLERANCE_S)
    return gross_exposure(frame)


def public(rows: list[dict]) -> list[dict]:
    """Rows without the unrounded helper keys (those starting with an underscore)."""
    return [{key: value for key, value in row.items() if not key.startswith("_")} for row in rows]


# --------------------------------------------------------------------------- summaries
def order_summary(export: dict) -> dict:
    orders = export.get("orders") or []
    counts: dict[str, int] = {}
    for order in orders:
        name = ORDER_STATUS.get(order["status"], str(order["status"]))
        counts[name] = counts.get(name, 0) + 1
    filled = [order for order in orders if order["status"] == 3]
    cap_hit = ""
    buying_power_errors = None
    for item in export.get("analysis") or []:
        if item["name"] == "ExceededMaximumOrdersOrderResponseErrorAnalysis":
            # The sample reads "2017-02-10 00:00:00 You have exceeded maximum number of orders (10000), ...".
            match = re.match(r"\d{4}-\d{2}-\d{2}", str(item.get("sample", "")))
            if match:
                cap_hit = match.group(0)
            elif orders:
                cap_hit = ny_date_from_iso(orders[-1]["time"])
        if item["name"] == "InsufficientBuyingPowerOrderResponseErrorAnalysis":
            buying_power_errors = item.get("count")
    return {
        "orders_by_status": dict(sorted(counts.items())),
        "first_date_traded": ny_date_from_iso(filled[0].get("lastFillTime") or filled[0]["time"]) if filled else "",
        "last_date_traded": ny_date_from_iso(filled[-1].get("lastFillTime") or filled[-1]["time"]) if filled else "",
        "order_cap_hit": cap_hit,
        "insufficient_buying_power_errors": buying_power_errors,
    }


def calendar_years(window: str, chart: dict, first_fill: str) -> list[dict]:
    """The paper weights' before-cost series of one v4 window, split into calendar years.

    Each year runs from the previous year's last "Rank vs name" sample (from the first fill for the
    window's first year) to its own last sample. The annualised figure follows the paper's
    Algorithm 5: the compounded return raised to 252 / N, minus one, with N the NYSE sessions the
    span covers (the first fill counted, a starting sample not). A year is "part" when its last
    sample is before December.
    """
    ranks = rank_frame(chart, decimals=None).dropna(subset=[RANK_COLUMN])
    rows = []
    start_date, start_level, first = first_fill, 1.0, True
    for year, group in ranks.groupby(ranks["date"].str[:4].astype(int), sort=True):
        last = group.iloc[-1]
        level = 1.0 + float(last[RANK_COLUMN]) / 100.0
        sessions = len(trading_days(start_date, last["date"])) - (0 if first else 1)
        cumulative = level / start_level - 1.0
        annualised = ((1.0 + cumulative) ** (TRADING_DAYS_PER_YEAR / sessions) - 1.0) * 100.0
        paper = PAPER_TABLE1.get(int(year))
        rows.append({
            "window": window,
            "year": int(year),
            "part": "whole" if last["date"][5:7] == "12" else "part",
            "from_date": start_date,
            "to_date": last["date"],
            "trading_days": sessions,
            "paper_weights_cumulative_pct": round(cumulative * 100.0, 2),
            "paper_weights_annualised_pct": round(annualised, 2),
            "table1_pct": paper if paper is not None else "",
            "difference_pts": round(annualised - paper, 2) if paper is not None else "",
        })
        start_date, start_level, first = last["date"], level, False
    return rows


def order_timing(window: str, export: dict) -> dict:
    """When a v4 window acted and when its orders filled: one row of results/v4/timing.csv.

    A decision pass is one submission time in the order list (New York time); the algorithm acts
    once per calendar date, at the first data event QuantConnect delivers for it. A close pass is
    one submitted at 16:00, or 13:00 on an early-close day; a midnight pass one submitted at 00:00.
    Opens are NYSE sessions from the first to the last fill; an open is fed by a pass when one of
    that pass's orders filled on that date.
    """
    orders = export.get("orders") or []
    passes: dict[dt.datetime, list[dict]] = {}
    for order in orders:
        passes.setdefault(ny_time(order["time"]), []).append(order)
    order_of_pass = sorted(passes)
    following = dict(zip(order_of_pass, order_of_pass[1:]))
    close = {moment for moment in passes if (moment.hour, moment.minute) in ((16, 0), (13, 0))}
    midnight = {moment for moment in passes if (moment.hour, moment.minute) == (0, 0)}
    if len(close) + len(midnight) != len(passes):
        raise SystemExit(f"{window}: orders submitted at times other than 00:00, 13:00 and 16:00 New York")
    fed_by: dict[str, set] = {}
    for moment, group in passes.items():
        for order in group:
            if order["status"] == 3:
                fed_by.setdefault(ny_date_from_iso(order["lastFillTime"]), set()).add(moment)
    if any(len(moments) > 2 for moments in fed_by.values()):
        raise SystemExit(f"{window}: an open received the orders of more than two passes")
    first, last = min(fed_by), max(fed_by)
    sessions = trading_days(first, last)
    stray = sorted(set(fed_by) - set(sessions))
    if stray:
        raise SystemExit(f"{window}: fills on dates the calendar has as closed: {', '.join(stray)}")
    open_days = set(sessions)
    filled = [order for order in orders if order["status"] == 3]
    late_filled = sum(1 for order in filled if ny_time(order["time"]) in close)
    canceled = [order for order in orders if order["status"] == 5]
    replaced = 0
    for order in canceled:
        after = following.get(ny_time(order["time"]))
        if after is not None and any(other["symbol"] == order["symbol"] for other in passes[after]):
            replaced += 1
    # The universe selection runs at midnight after each trading day, so between two passes a new close
    # arrives only if a trading day falls on or after the first pass's date and before the second's.
    calendar = set(trading_days(order_of_pass[0].date().isoformat(), order_of_pass[-1].date().isoformat()))
    repeated = 0
    for before, after in following.items():
        day, new_close = before.date(), False
        while day < after.date():
            new_close = new_close or day.isoformat() in calendar
            day += dt.timedelta(days=1)
        repeated += int(not new_close)
    return {
        "window": window,
        "first_fill": first,
        "last_fill": last,
        "trading_days": len(sessions),
        "passes": len(passes),
        "passes_midnight": len(midnight),
        "passes_close": len(close),
        "passes_close_pct": round(len(close) / len(passes) * 100.0, 1),
        "passes_on_closed_days": sum(1 for moment in passes if moment.date().isoformat() not in open_days
                                     and first <= moment.date().isoformat() <= last),
        "passes_repeating_a_close": repeated,
        "opens_with_fills": len(fed_by),
        "opens_without_fills": len(sessions) - len(fed_by),
        "opens_with_two_passes": sum(1 for moments in fed_by.values() if len(moments) >= 2),
        "orders_filled": len(filled),
        "filled_from_close_passes": late_filled,
        "filled_from_close_passes_pct": round(late_filled / len(filled) * 100.0, 1),
        "orders": len(orders),
        "orders_canceled": len(canceled),
        "orders_canceled_pct": round(len(canceled) / len(orders) * 100.0, 1),
        "canceled_from_close_passes": sum(1 for order in canceled if ny_time(order["time"]) in close),
        "canceled_replaced_at_next_pass": replaced,
    }


def code_hashes(export: dict) -> dict[str, str]:
    """SHA-256 of each code file as published in the raw export."""
    return {name: text_sha256(text) for name, text in (export.get("code") or {}).items()}


def statistics_document(run: Run, export: dict, summary: dict, engines: dict, provenance: dict) -> dict:
    document: dict = {"key": run.key, "label": run.label, "version": run.version, "role": run.role,
                      "folder": run.folder, "meta": export["meta"], "parameters": export.get("parameterSet") or {}}
    for section in ("statistics", "runtimeStatistics", "tradeStatistics", "portfolioStatistics"):
        if export.get(section):
            document[section] = export[section]
    if export.get("analysis"):
        # QuantConnect's generic "solutions" text is left in the raw export.
        document["analysis"] = [
            {field: item[field] for field in ("name", "issue", "sample", "count") if field in item}
            for item in export["analysis"]
        ]
    document["derived"] = {**summary, "lean_version": lean_version(export, engines),
                           "code_sha256_as_run": as_run_hashes(provenance, run.key),
                           "code_sha256_published": code_hashes(export)}
    return document


def runs_row(run: Run, export: dict, summary: dict, ranks: pd.DataFrame | None, engines: dict,
             provenance: dict) -> dict:
    meta = export["meta"]
    stats = export["statistics"]
    trade_stats = export.get("tradeStatistics") or {}
    counts = summary["orders_by_status"]
    has_orders = bool(export.get("orders"))
    start_equity = number(stats["Start Equity"])
    total_fees = number(stats["Total Fees"])
    win_rate = trade_stats.get("winRate")
    paper = ""
    if ranks is not None:
        paper = round(float(ranks[RANK_COLUMN].dropna().iloc[-1]), 4)
    hashes = code_hashes(export)
    ran = as_run_hashes(provenance, run.key)
    return {
        "key": run.key,
        "version": run.version,
        "role": run.role,
        "label": run.label,
        "folder": run.folder,
        "project_id": meta["projectId"],
        "backtest_id": meta["backtestId"],
        "created": meta["created"],
        "lean_version": lean_version(export, engines),
        "configured_start": meta["backtestStart"][:10],
        "configured_end": meta["backtestEnd"][:10],
        "first_date_traded": summary["first_date_traded"],
        "last_date_traded": summary["last_date_traded"],
        "order_cap_hit": summary["order_cap_hit"],
        "parameters": format_parameters(export.get("parameterSet")),
        "net_profit": number(stats["Net Profit"]),
        "cagr": number(stats["Compounding Annual Return"]),
        "sharpe": number(stats["Sharpe Ratio"]),
        "psr": number(stats["Probabilistic Sharpe Ratio"]),
        "max_drawdown": number(stats["Drawdown"]),
        "beta": number(stats["Beta"]),
        "orders": int(number(stats["Total Orders"]) or 0),
        "orders_filled": counts.get("Filled", 0) if has_orders else "",
        "orders_invalid": counts.get("Invalid", 0) if has_orders else "",
        "orders_canceled": counts.get("Canceled", 0) if has_orders else "",
        "orders_open_at_stop": counts.get("Submitted", 0) if has_orders else "",
        "closed_trades": trade_stats.get("totalNumberOfTrades", ""),
        "win_rate": round(float(win_rate) * 100.0, 2) if win_rate is not None else "",
        "total_fees": total_fees,
        "fees_pct_of_start": round(total_fees / start_equity * 100.0, 3),
        "portfolio_turnover": number(stats["Portfolio Turnover"]),
        "start_equity": start_equity,
        "end_equity": number(stats["End Equity"]),
        "paper_weights_before_costs": paper,
        "code_sha256_as_run": ran.get("main.py", ""),
        "code_sha256_published": hashes.get("main.py", ""),
        "rank_space_sha256_as_run": ran.get("rank_space.py", ""),
        "rank_space_sha256_published": hashes.get("rank_space.py", ""),
    }


def summary_row(window: str, row: dict, ranks: pd.DataFrame, chart: dict) -> dict:
    """One row of results/v4/summary.csv.

    The keys starting with an underscore hold the same figures unrounded (the chart values as
    exported), so that the README rounds each figure once; they are not written to the CSV.
    """
    last = ranks.dropna(subset=[RANK_COLUMN, NAME_COLUMN]).iloc[-1]
    exact = rank_frame(chart, decimals=None).dropna(subset=[RANK_COLUMN, NAME_COLUMN]).iloc[-1]
    if exact["date"] != last["date"]:
        raise SystemExit(f"{window}: the last Rank vs name sample moved when unrounded")
    paper = float(exact[RANK_COLUMN])
    span = days_between(row["first_date_traded"], last["date"])
    annualised = ((1.0 + paper / 100.0) ** (DAYS_PER_YEAR / span) - 1.0) * 100.0
    months = days_between(row["first_date_traded"], row["last_date_traded"]) / (DAYS_PER_YEAR / 12.0)
    return {
        "_paper": paper,
        "_annualised": annualised,
        "_realised": float(exact[NAME_COLUMN]),
        "_fees_pct": row["total_fees"] / row["start_equity"] * 100.0,
        "window": window,
        "key": row["key"],
        "backtest_id": row["backtest_id"],
        "configured_start": row["configured_start"],
        "configured_end": row["configured_end"],
        "first_fill": row["first_date_traded"],
        "last_fill": row["last_date_traded"],
        "months_covered": round(months, 1),
        "net_profit_pct": row["net_profit"],
        "cagr_pct": row["cagr"],
        "sharpe": row["sharpe"],
        "psr_pct": row["psr"],
        "max_drawdown_pct": row["max_drawdown"],
        "beta": row["beta"],
        "total_fees": row["total_fees"],
        "fees_pct_of_start": row["fees_pct_of_start"],
        "turnover_per_day_pct": row["portfolio_turnover"],
        "orders": row["orders"],
        "orders_filled": row["orders_filled"],
        "orders_canceled": row["orders_canceled"],
        "orders_invalid": row["orders_invalid"],
        "orders_open_at_stop": row["orders_open_at_stop"],
        "closed_trades": row["closed_trades"],
        "last_sample": last["date"],
        "paper_weights_before_costs_pct": round(paper, 4),
        "paper_weights_annualised_pct": round(annualised, 2),
        "realised_after_costs_pct": round(float(last[NAME_COLUMN]), 4),
        "order_cap_hit": "yes" if row["order_cap_hit"] else "no",
        "order_cap_date": row["order_cap_hit"],
    }


def coverage_gaps(summary: list[dict]) -> tuple[list[tuple[str, str]], list[tuple[str, str, str, str]]]:
    """Calendar spans between consecutive v4 windows that no window traded, and overlaps.

    A gap runs from the day after a window's last fill to the day before the next window's
    configured start. An overlap runs from the next window's first fill to this window's last fill.
    """
    ordered = sorted(summary, key=lambda row: row["configured_start"])
    gaps, overlaps = [], []
    for current, following in zip(ordered, ordered[1:]):
        last = dt.date.fromisoformat(current["last_fill"])
        start = dt.date.fromisoformat(following["configured_start"])
        first = dt.date.fromisoformat(following["first_fill"])
        if last + dt.timedelta(days=1) < start:
            gaps.append(((last + dt.timedelta(days=1)).isoformat(), (start - dt.timedelta(days=1)).isoformat()))
        elif last >= first:
            overlaps.append((current["window"], following["window"], first.isoformat(), last.isoformat()))
    return gaps, overlaps


# --------------------------------------------------------------------------- text helpers
def fmt_num(value: object, decimals: int, sign: bool = False, suffix: str = "") -> str:
    """Format a number for the README, with a true minus sign as in the main README."""
    if value in ("", None):
        return ""
    text = f"{float(value):+.{decimals}f}" if sign else f"{float(value):.{decimals}f}"
    return text.replace("-", "−") + suffix


def fmt_money(value: object) -> str:
    return "" if value in ("", None) else f"${float(value):,.0f}"


def fmt_int(value: object) -> str:
    return "" if value in ("", None) else f"{int(value):,}"


def fmt_share(value: float, decimals: int = 1) -> str:
    return f"{value * 100:.{decimals}f}%"


def nice_date(text: str) -> str:
    moment = dt.date.fromisoformat(text)
    return f"{moment.day} {moment:%B %Y}"


def date_span(first: str, last: str) -> str:
    """'14 September to 31 December 2012', with the year or month repeated only when they differ."""
    a, b = dt.date.fromisoformat(first), dt.date.fromisoformat(last)
    if (a.year, a.month) == (b.year, b.month):
        return f"{a.day} to {b.day} {b:%B %Y}"
    if a.year == b.year:
        return f"{a.day} {a:%B} to {b.day} {b:%B %Y}"
    return f"{nice_date(first)} to {nice_date(last)}"


def margin_ratio(export: dict) -> float | None:
    """Initial margin over order value in QuantConnect's sample buying-power error, if present."""
    for item in export.get("analysis") or []:
        if item["name"] == "InsufficientBuyingPowerOrderResponseErrorAnalysis":
            found = re.search(r"Value:\[(-?[\d.]+)\].*?Initial Margin: (-?[\d.]+)", str(item.get("sample", "")))
            if found:
                return abs(float(found.group(2)) / float(found.group(1)))
    return None


MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]


# --------------------------------------------------------------------------- checks: reproduction
def sorted_orders(export: dict) -> list[dict]:
    return sorted(export.get("orders") or [], key=lambda order: order["id"])


def orders_identical(a: dict, b: dict) -> bool:
    """Every exported field of every order equal, in order-id order."""
    return sorted_orders(a) == sorted_orders(b)


def trades_identical(a: dict, b: dict) -> bool:
    """Every exported field of every closed trade equal, in the exported order, except `id`: QuantConnect
    gives each closed trade a random UUID, which differs between any two runs."""
    def strip(export: dict) -> list[dict]:
        return [{field: value for field, value in trade.items() if field != "id"}
                for trade in export.get("closedTrades") or []]
    return strip(a) == strip(b)


DIVERGENCE_FIELDS = ("time", "symbol", "quantity", "price", "status")


def first_divergence(a: dict, b: dict) -> tuple[int, dict, dict] | None:
    """The first order, in order-id order, whose time, symbol, quantity, price or status differ."""
    for index, (left, right) in enumerate(zip(sorted_orders(a), sorted_orders(b))):
        if any(left[field] != right[field] for field in DIVERGENCE_FIELDS):
            return index, left, right
    return None


def fill_price_ratios(recorded: dict, rerun: dict) -> pd.DataFrame:
    """Re-run fill price over recorded fill price, per symbol, for filled orders that match on
    submission time and symbol (paired in order-id order where a symbol has several)."""
    pending: dict[tuple, list] = {}
    for order in sorted_orders(rerun):
        if order["status"] == 3:
            pending.setdefault((order["time"], order["symbol"]), []).append(order)
    ratios: dict[str, list[float]] = {}
    for order in sorted_orders(recorded):
        if order["status"] != 3 or not order["price"]:
            continue
        matches = pending.get((order["time"], order["symbol"]))
        if matches:
            other = matches.pop(0)
            ratios.setdefault(order["symbol"], []).append(other["price"] / order["price"])
    rows = [{"symbol": symbol, "matched_fills": len(values), "ratio_min": round(min(values), 6),
             "ratio_max": round(max(values), 6)} for symbol, values in sorted(ratios.items())]
    return pd.DataFrame(rows, columns=["symbol", "matched_fills", "ratio_min", "ratio_max"])


def same_day_identical(rows: list[dict], stat_names: list[str]) -> bool:
    """True when the same-day 2018 runs agree on every statistic, order and closed trade."""
    by_key = {row["key"]: row for row in rows}
    reference = by_key[RERUN["2018"]]
    return all(by_key[key]["orders_identical_to_rerun"] and by_key[key]["trades_identical_to_rerun"]
               and all(by_key[key][snake(name)] == reference[snake(name)] for name in stat_names)
               for key in SAME_DAY_2018)


def build_reproduction(outputs: dict, exports: dict, engines: dict, provenance: dict) -> bool:
    """results/checks/reproduction; returns whether the same-day 2018 runs are identical."""
    stat_names = list(exports[RECORDED["2018"]]["statistics"])
    rows = []
    for chunk, key, role in REPRODUCTION:
        export = exports[key]
        if list(export["statistics"]) != stat_names:
            raise SystemExit(f"{key}: statistics differ in name or order from {RECORDED['2018']}")
        meta = export["meta"]
        hashes = as_run_hashes(provenance, key)
        recorded, rerun = exports[RECORDED[chunk]], exports[RERUN[chunk]]
        row = {
            "chunk": CHUNK_WORDS[chunk], "key": key, "run": role, "project_id": meta["projectId"],
            "backtest_id": meta["backtestId"], "created": meta["created"],
            "lean_version": lean_version(export, engines),
            "parameters": format_parameters(export.get("parameterSet")),
            "main_py_sha256_as_run": hashes.get("main.py", ""),
            "rank_space_py_sha256_as_run": hashes.get("rank_space.py", ""),
        }
        row.update({snake(name): export["statistics"][name] for name in stat_names})
        row.update({
            "closed_trades": len(export.get("closedTrades") or []),
            "orders": len(export.get("orders") or []),
            "orders_identical_to_recorded": orders_identical(export, recorded),
            "trades_identical_to_recorded": trades_identical(export, recorded),
            "orders_identical_to_rerun": orders_identical(export, rerun),
            "trades_identical_to_rerun": trades_identical(export, rerun),
        })
        rows.append(row)
    outputs["checks/reproduction/comparison.csv"] = csv_text(pd.DataFrame(rows))

    divergence_rows = []
    divergences = {}
    for chunk in ("2018", "2011"):
        found = first_divergence(exports[RECORDED[chunk]], exports[RERUN[chunk]])
        divergences[chunk] = found
        if found is None:
            continue
        index, left, right = found
        row = {"chunk": CHUNK_WORDS[chunk], "order_index": index, "recorded_key": RECORDED[chunk],
               "rerun_key": RERUN[chunk]}
        for side, order in (("recorded", left), ("rerun", right)):
            row.update({
                f"{side}_id": order["id"], f"{side}_submitted_utc": order["time"],
                f"{side}_filled_utc": order.get("lastFillTime") or "", f"{side}_symbol": order["symbol"],
                f"{side}_quantity": order["quantity"], f"{side}_fill_price": round(float(order["price"]), 6),
                f"{side}_status": ORDER_STATUS.get(order["status"], str(order["status"])),
            })
        divergence_rows.append(row)
    outputs["checks/reproduction/first_divergence.csv"] = csv_text(pd.DataFrame(divergence_rows))

    ratio_frames = []
    for chunk in ("2018", "2011"):
        frame = fill_price_ratios(exports[RECORDED[chunk]], exports[RERUN[chunk]])
        frame.insert(0, "chunk", CHUNK_WORDS[chunk])
        ratio_frames.append(frame)
    ratios = pd.concat(ratio_frames, ignore_index=True)
    outputs["checks/reproduction/fill_price_ratios.csv"] = csv_text(ratios)
    outputs["checks/reproduction/README.md"] = reproduction_readme(rows, stat_names, exports, engines,
                                                                   divergences, ratios)
    return same_day_identical(rows, stat_names)


def reproduction_readme(rows: list[dict], stat_names: list[str], exports: dict, engines: dict,
                        divergences: dict, ratios: pd.DataFrame) -> str:
    by_key = {row["key"]: row for row in rows}
    n_stats = len(stat_names)
    lines = [
        "# Reproduction of the v3 runs",
        "",
        "Written by `analysis/build_results.py` from the exports in `results/raw/`; a rebuild overwrites it.",
        "",
        "The two recorded v3 runs (now in `../../superseded/`) ran on 22 September 2026 with a single "
        "`main.py`. The code was then split into `main.py` and `rank_space.py`, and later extended to v4. "
        "Four backtests on 25 September test whether either change altered what v3 does:",
        "",
        "| Chunk | Run | Key | QuantConnect project / backtest | Created (UTC) | LEAN | Parameters | "
        "`main.py`, as run | `rank_space.py`, as run |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['chunk']} | {row['run']} | `{row['key']}` | {row['project_id']} / `{row['backtest_id']}` | "
            f"{row['created']} | {row['lean_version'] or 'not recorded'} | {row['parameters']} | "
            f"`{row['main_py_sha256_as_run'][:8]}...` | "
            + (f"`{row['rank_space_py_sha256_as_run'][:8]}...` |" if row["rank_space_py_sha256_as_run"] else "n/a |")
        )
    check = exports["check__v3_via_params_2018"]
    rerun18 = exports[RERUN["2018"]]
    lines += [
        "",
        "- The re-runs ran the refactored v3 code, before v4, with the v3 parameters as its defaults "
        f"(`leg_weight` default {code_default(rerun18, 'leg_weight')}).",
        "- The control ran the recorded `main.py` (the same SHA-256 as the recorded runs) again, in a "
        "separate QuantConnect project, on the same day and LEAN build as the re-run.",
        "- The check ran the v4 code, the repository's `main.py` and `rank_space.py` of the v4 runs, "
        f"with `cap_source={effective_parameter(check, 'cap_source')}` and "
        f"`leg_weight={effective_parameter(check, 'leg_weight')}`, the settings that give v3's behaviour.",
        "- Hashes are the SHA-256 of each file as QuantConnect ran it, from `../../provenance/code_hashes.json`; "
        "`comparison.csv` has them in full. Where the copy of a file in `../../raw/` has one docstring paragraph "
        "rewritten to leave out the other team members' names, its own hash differs (`runs.csv` gives both).",
        "",
        "## LEAN versions",
        "",
        "The exports of the recorded runs do not carry a LEAN version; it comes from "
        "`raw/engines__original_runs.json.gz`, a separate export of the server statistics of each original "
        "backtest. QuantConnect upgraded LEAN between the recorded runs "
        f"({by_key[RECORDED['2018']]['lean_version']}) and the checks ({by_key[RERUN['2018']]['lean_version']}).",
        "",
        "## Result",
        "",
    ]
    rerun_row = by_key[RERUN["2018"]]
    all_identical = same_day_identical(rows, stat_names)
    names = ", ".join(f"`{key}`" for key in SAME_DAY_2018)
    if all_identical:
        lines.append(
            f"The runs of 25 September on the 2018 to 2024 chunk ({names}) are identical to each other: all "
            f"{n_stats} statistics, all {rerun_row['closed_trades']:,} closed trades and all "
            f"{rerun_row['orders']:,} orders, compared on every exported field. The split into `main.py` and "
            "`rank_space.py` changed nothing, and the v4 code reproduces v3 through its parameters."
        )
    else:
        lines.append(f"The runs of 25 September on the 2018 to 2024 chunk ({names}) are not all identical; "
                     "see `comparison.csv`.")
    lines += [
        "",
        "Against the recorded runs of 22 September, the re-runs differ. The recorded code, re-run in the control, "
        "shows the same difference, so it comes from QuantConnect's side (data and engine), not from the code:",
        "",
        "| Statistic | Recorded, 2018 to 2024 | Re-run, 2018 to 2024 | Recorded, 2011 to 2017 | "
        "Re-run, 2011 to 2017 |",
        "|---|---|---|---|---|",
    ]
    differing = [name for name in stat_names
                 if any(by_key[RECORDED[c]][snake(name)] != by_key[RERUN[c]][snake(name)] for c in ("2018", "2011"))]
    for name in differing:
        column = snake(name)
        lines.append(f"| {name} | {by_key[RECORDED['2018']][column]} | {by_key[RERUN['2018']][column]} | "
                     f"{by_key[RECORDED['2011']][column]} | {by_key[RERUN['2011']][column]} |")
    for label, column in (("Closed trades (exported)", "closed_trades"), ("Orders (exported)", "orders")):
        lines.append(f"| {label} | {by_key[RECORDED['2018']][column]:,} | {by_key[RERUN['2018']][column]:,} | "
                     f"{by_key[RECORDED['2011']][column]:,} | {by_key[RERUN['2011']][column]:,} |")
    lines += [
        "",
        f"Of the {n_stats} statistics, {len(differing)} differ in at least one chunk.",
        "",
        "## Where the runs part",
        "",
        "`first_divergence.csv` gives, for each chunk, the first order (in order-id order) whose time, symbol, "
        "quantity, fill price or status differs between the recorded run and its re-run:",
        "",
    ]
    for chunk in ("2018", "2011"):
        found = divergences[chunk]
        if found is None:
            lines.append(f"- {CHUNK_WORDS[chunk]}: no order differs.")
            continue
        index, left, right = found
        lines.append(
            f"- {CHUNK_WORDS[chunk]}: order {left['id']} (position {index}), submitted "
            f"{left['time'][:10]}, {left['symbol']}: recorded {left['quantity']:,} shares at "
            f"{left['price']:.4f}, re-run {right['quantity']:,} shares at {right['price']:.4f}. "
            f"Every earlier order is the same."
        )
    off = ratios[(ratios["ratio_min"] != 1.0) | (ratios["ratio_max"] != 1.0)]
    counts = [int((ratios["chunk"] == CHUNK_WORDS[c]).sum()) for c in ("2018", "2011")]
    lines += [
        "",
        "`fill_price_ratios.csv` pairs the filled orders of each recorded run and its re-run that share "
        "submission time and symbol, and gives the re-run's fill price over the recorded one per symbol. "
        f"{counts[0]} symbols in the {CHUNK_WORDS['2018']} chunk and {counts[1]} in the {CHUNK_WORDS['2011']} "
        "chunk have such pairs; all but these have a ratio of exactly 1 on every pair:",
        "",
        "| Chunk | Symbol | Matched fills | Ratio, lowest | Ratio, highest |",
        "|---|---|---|---|---|",
    ]
    for record in off.itertuples(index=False):
        lines.append(f"| {record.chunk} | {record.symbol} | {record.matched_fills} | {record.ratio_min:.6f} | "
                     f"{record.ratio_max:.6f} |")
    first_symbol = divergences["2018"][1]["symbol"] if divergences["2018"] else ""
    factor = off[off["symbol"] == first_symbol]["ratio_min"]
    shift = (f"A {(1.0 - float(factor.iloc[0])) * 100:.2f}% lower {first_symbol} price means more shares for "
             f"the same target value, so the first {first_symbol} order already differs, and the book, the "
             "order sequence and the statistics drift apart from there." if len(factor) else "")
    lines += [
        "",
        "One constant factor across years of fills is what a change in a stock's price adjustment produces: "
        "QuantConnect's default for US equities is to trade on split- and dividend-adjusted prices, and a "
        "newly booked dividend rescales the whole earlier history of the stock. The exports show the factor, "
        f"not its cause. {shift}",
        "",
        "## Files",
        "",
        "| File | Content |",
        "|---|---|",
        "| `comparison.csv` | One row per run: chunk, key, role, QuantConnect identifiers, creation time, LEAN "
        "build, parameters, SHA-256 of `main.py` and `rank_space.py` as QuantConnect ran them (blank where the "
        f"run had no `rank_space.py`), QuantConnect's {n_stats} statistics exactly as exported (text, with QuantConnect's "
        "rounding and units), the number of closed trades and orders, and four identity flags |",
        "| `first_divergence.csv` | The first differing order of each chunk, recorded and re-run side by side "
        "(order id, submission and fill time in UTC, symbol, quantity, fill price, status) |",
        "| `fill_price_ratios.csv` | Per chunk and symbol: matched filled orders and the lowest and highest "
        "ratio of re-run to recorded fill price |",
        "",
        "Identity flags: `orders_identical_to_recorded` and `orders_identical_to_rerun` are true when every "
        "exported field of every order (id, type, submission and fill time, symbol, quantity, price, status, "
        "direction, value, tag, fee) equals that of the chunk's recorded run or re-run, in order-id order; "
        "`trades_identical_to_recorded` and `trades_identical_to_rerun` do the same for every field of every "
        "closed trade, in the exported order, except the trade `id`, a random UUID QuantConnect draws anew in "
        "each run.",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- checks: margin
def build_margin(outputs: dict, exports: dict, charts: dict, engines: dict, provenance: dict) -> list[dict]:
    rows = []
    for chunk, full_key, half_key in MARGIN_PAIRS:
        for key in (full_key, half_key):
            export = exports[key]
            summary = order_summary(export)
            counts = summary["orders_by_status"]
            total = len(export.get("orders") or [])
            chart = run_chart(key, export, charts)
            gross = exact_gross_exposure(chart) if has_equity(chart) else None
            stats = export["statistics"]
            rows.append({
                "_gross_median": float(gross.median()) if gross is not None else None,
                "_rejected_share": counts.get("Invalid", 0) / total * 100.0 if total else None,
                "chunk": CHUNK_WORDS[chunk],
                "key": key,
                "leg_weight": float(effective_parameter(export, "leg_weight")),
                "backtest_id": export["meta"]["backtestId"],
                "created": export["meta"]["created"],
                "lean_version": lean_version(export, engines),
                "main_py_sha256_as_run": as_run_hashes(provenance, key).get("main.py", ""),
                "configured_start": export["meta"]["backtestStart"][:10],
                "configured_end": export["meta"]["backtestEnd"][:10],
                "first_fill": summary["first_date_traded"],
                "last_fill": summary["last_date_traded"],
                "order_cap_hit": "yes" if summary["order_cap_hit"] else "no",
                "order_cap_date": summary["order_cap_hit"],
                "net_profit_pct": number(stats["Net Profit"]),
                "sharpe": number(stats["Sharpe Ratio"]),
                "total_fees": number(stats["Total Fees"]),
                "orders": total,
                "orders_filled": counts.get("Filled", 0),
                "orders_canceled": counts.get("Canceled", 0),
                "orders_invalid": counts.get("Invalid", 0),
                "orders_open_at_stop": counts.get("Submitted", 0),
                "rejected_share_pct": round(counts.get("Invalid", 0) / total * 100.0, 2) if total else "",
                "insufficient_buying_power_errors": summary["insufficient_buying_power_errors"],
                "gross_exposure_median": round(float(gross.median()), 3) if gross is not None else "",
                "gross_exposure_share_at_1_9_pct": (round(float((gross >= GROSS_EXPOSURE_MARK).mean()) * 100.0, 1)
                                                    if gross is not None else ""),
            })
        run = RUN_BY_KEY[half_key]
        outputs[f"{run.folder}/statistics.json"] = json_text(
            statistics_document(run, exports[half_key], order_summary(exports[half_key]), engines, provenance))
    outputs["checks/margin/comparison.csv"] = csv_text(pd.DataFrame(public(rows)))
    outputs["checks/margin/README.md"] = margin_readme(rows, exports)
    return rows


def margin_readme(rows: list[dict], exports: dict) -> str:
    by_key = {row["key"]: row for row in rows}
    same_code = all(by_key[full]["main_py_sha256_as_run"] == by_key[half]["main_py_sha256_as_run"]
                    for _, full, half in MARGIN_PAIRS)
    ratio = next((margin_ratio(exports[key]) for key in by_key if margin_ratio(exports[key])), None)
    lines = [
        "# Margin check: v3 at half the leg weight",
        "",
        "Written by `analysis/build_results.py` from the exports in `results/raw/`; a rebuild overwrites it.",
        "",
        "The v3 runs held a fixed leg of 5% of equity per open rank plus an SPY hedge, and QuantConnect "
        "rejected about four orders in ten of them for insufficient buying power. Two backtests on 25 "
        "September ran the same v3 code at half the leg weight, on the same day and LEAN build as the "
        "re-runs at the full weight (`../reproduction/`)"
        + (", with the same `main.py`" if same_code else "")
        + ". Both use the monthly reported market cap, as v3 did. v4 takes 0.025 as its default leg weight.",
        "",
        "| Chunk | Key | Leg weight | Orders | Filled | Rejected | Rejected share | Cancelled | Open at stop | "
        "Order cap | Last fill | Net | Sharpe | Fees | Gross exposure, median | Samples at 1.9x or more |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        cap = f"hit {row['order_cap_date']}" if row["order_cap_hit"] == "yes" else "not reached"
        lines.append(
            f"| {row['chunk']} | `{row['key']}` | {row['leg_weight']:g} | {fmt_int(row['orders'])} | "
            f"{fmt_int(row['orders_filled'])} | {fmt_int(row['orders_invalid'])} | "
            f"{row['_rejected_share']:.2f}% | {fmt_int(row['orders_canceled'])} | "
            f"{fmt_int(row['orders_open_at_stop'])} | {cap} | {row['last_fill']} | "
            f"{fmt_num(row['net_profit_pct'], 3, sign=True, suffix='%')} | {fmt_num(row['sharpe'], 3)} | "
            f"{fmt_money(row['total_fees'])} | {row['_gross_median']:.2f} | "
            f"{row['gross_exposure_share_at_1_9_pct']:.1f}% |"
        )
    halves = [by_key[half] for _, _, half in MARGIN_PAIRS]
    fulls = [by_key[full] for _, full, _ in MARGIN_PAIRS]
    lines += [
        "",
        "At a leg weight of 0.05, QuantConnect rejected "
        + " and ".join(f"{fmt_int(r['orders_invalid'])} of {fmt_int(r['orders'])} orders ({r['_rejected_share']:.1f}%) "
                       f"in {r['chunk']}" for r in fulls)
        + "; the analysis QuantConnect attaches to each run counts the same number of insufficient-buying-power "
        "errors."
        + (f" Its sample error puts the initial margin at {ratio * 100:.0f}% of the order value, so the "
           "account could hold about twice its equity in positions." if ratio else "")
        + " Rejected orders count toward the order cap, which these runs reached on "
        + " and ".join(nice_date(r["order_cap_date"]) for r in fulls if r["order_cap_date"])
        + ". At 0.025 the same code had "
        + " and ".join(f"{fmt_int(r['orders_invalid'])} of {fmt_int(r['orders'])} rejected "
                       f"({r['_rejected_share']:.2f}%)" for r in halves)
        + (", did not reach the order cap and ran to "
           + " and ".join(nice_date(r["configured_end"]) for r in halves) + "."
           if all(r["order_cap_hit"] == "no" for r in halves) else "."),
        "",
        "The gross exposure column is `exposure_long` minus `exposure_short` over the equity samples (the same "
        "definition as in each run folder's `equity.csv`). Halving the legs brought the median from "
        + " and ".join(f"{f['_gross_median']:.2f} to {h['_gross_median']:.2f} ({f['chunk']})"
                       for f, h in zip(fulls, halves))
        + " times equity. Both columns are computed from the exposures as exported, before the rounding to "
        "four decimals in `equity.csv`.",
        "",
        "Net return and Sharpe are not comparable between the rows: the full-weight runs stopped at the "
        "order cap, the half-weight runs cover the whole configured period, and a run with smaller legs "
        "holds less of the signal. The check is about whether the book QuantConnect holds is the book the "
        "signal asks for.",
        "",
        "## Files",
        "",
        "| File | Content |",
        "|---|---|",
        "| `comparison.csv` | The table above with QuantConnect identifiers, creation time, LEAN build, SHA-256 "
        "of `main.py` as QuantConnect ran it, configured window, first fill and the count of insufficient-buying-power errors "
        "QuantConnect's analysis reports |",
        "| `half_leg_2011_2017/statistics.json`, `half_leg_2018_2024/statistics.json` | QuantConnect's "
        "statistics, runtime, trade and portfolio statistics, parameters, backtest metadata and analysis "
        "warnings for each half-weight run, plus a `derived` block as in the run folders |",
        "",
        "The full-weight runs' statistics are in `../reproduction/comparison.csv`; every order of all four runs "
        "is in the raw exports.",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- checks: data
CAP_LINE = re.compile(
    r"(\d{4}-\d{2}-\d{2}) (\S+) px (-?[\d.]+) adj (-?[\d.]+) mcap (-?[\d.]+) "
    r"sh (-?[\d.]+) pxsh (-?[\d.]+)")
CAP_COLUMNS = ["date", "ticker", "price_unadjusted", "price_adjusted", "market_cap_bn",
               "shares_outstanding_bn", "price_x_shares_bn"]


def log_lines(logs) -> list[str]:
    """The export's log field as a list of lines (it may be a list or one string)."""
    if not logs:
        return []
    if isinstance(logs, str):
        return [line for line in logs.splitlines() if line.strip()]
    return [item if isinstance(item, str) else json.dumps(item, ensure_ascii=False) for item in logs]


def parse_cap_log(lines: list[str]) -> pd.DataFrame:
    """The cap probe's log lines (see results/checks/data/code/cap_probe_main.py) as a table.
    Lines that do not match the probe's format are ignored."""
    rows = []
    for line in lines:
        match = CAP_LINE.search(line)
        if match:
            date, ticker, *values = match.groups()
            rows.append([date, ticker, *(float(x) for x in values)])
    return pd.DataFrame(rows, columns=CAP_COLUMNS)


def roll_caps(table: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Add rank_space.DailyCaps' daily cap to the cap probe table, and list each re-anchor.

    At a re-anchor day the reported cap has changed; the estimate there is what the previous
    anchor, rolled forward with the adjusted price, would have given before DailyCaps resets it.
    """
    daily_caps = daily_caps_class()()
    table = table.sort_values(["ticker", "date"], kind="stable").reset_index(drop=True)
    rolled, anchors, events = [], {}, []
    for record in table.itertuples(index=False):
        previous = anchors.get(record.ticker)
        value = daily_caps.update(record.ticker, record.market_cap_bn, record.price_adjusted)
        rolled.append(round(value, 4))
        if previous is None or previous["cap"] != record.market_cap_bn:
            if previous is not None:
                estimate = previous["cap"] * record.price_adjusted / previous["price"]
                unadjusted_ratio = record.price_unadjusted / previous["unadjusted"]
                events.append({
                    "ticker": record.ticker,
                    "anchor_date": previous["date"],
                    "anchor_cap_bn": previous["cap"],
                    "anchor_price_adjusted": previous["price"],
                    "anchor_price_unadjusted": previous["unadjusted"],
                    "reanchor_date": record.date,
                    "price_adjusted": record.price_adjusted,
                    "price_unadjusted": record.price_unadjusted,
                    "rolled_estimate_bn": round(estimate, 4),
                    "new_snapshot_bn": record.market_cap_bn,
                    "error_pct": round((estimate / record.market_cap_bn - 1.0) * 100.0, 4),
                    "adjusted_price_ratio": round(record.price_adjusted / previous["price"], 6),
                    "unadjusted_price_ratio": round(unadjusted_ratio, 6),
                    "implied_share_change_pct": round(
                        (record.market_cap_bn / (previous["cap"] * unadjusted_ratio) - 1.0) * 100.0, 4),
                })
            anchors[record.ticker] = {"date": record.date, "cap": record.market_cap_bn,
                                      "price": record.price_adjusted, "unadjusted": record.price_unadjusted}
    table["rolled_cap_bn"] = rolled
    table = table.sort_values(["date", "ticker"], kind="stable").reset_index(drop=True)
    return table, pd.DataFrame(events)


def probe_month(seconds: int, previous: bool) -> tuple[int, int]:
    """(year, month) of a probe chart point. The monthly Caps and Calls points are plotted
    when the next month starts (the last one at the end of the backtest), so they belong to
    the month before their New York timestamp; the EBITDA growth points are plotted at the
    first data point of their own month."""
    moment = dt.datetime.fromtimestamp(seconds, NEW_YORK)
    year, month = moment.year, moment.month
    if previous:
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return year, month


def probe_rows(export: dict, points: dict[str, list], previous: bool) -> list[dict]:
    """Rows (year, month, one column per series) from probe chart series. Every series must
    share the same timestamps, and every month must fall in the probe's year exactly once."""
    key = export["meta"]["key"]
    times = [[int(p[0]) for p in pts] for pts in points.values()]
    if any(t != times[0] for t in times):
        raise SystemExit(f"{key}: probe series do not share timestamps")
    year = int((export.get("parameterSet") or {}).get("year"))
    rows = []
    for i, t in enumerate(times[0]):
        y, m = probe_month(t, previous)
        row = {"year": y, "month": m}
        row.update({column: float(pts[i][1]) for column, pts in points.items()})
        rows.append(row)
    months = [(r["year"], r["month"]) for r in rows]
    if len(set(months)) != len(months) or any(y != year for y, _ in months):
        raise SystemExit(f"{key}: probe months {months} do not fit the year {year}")
    return rows


def build_data_checks(outputs: dict, exports: dict, engines: dict) -> dict:
    probes = [exports[key] for key in PROBE_KEYS]
    cap = exports[CAP_PROBE_KEY]
    growth, caps = [], []
    for export in probes:
        charts = export["charts"]
        growth += probe_rows(export, {
            "median_one_year": charts["EBITDA growth"]["median one_year"],
            "p90_abs_one_year": charts["EBITDA growth"]["p90 of absolute value"],
        }, previous=False)
        caps += probe_rows(export, {
            "cap_unchanged_share": charts["Caps"]["cap unchanged share"],
            "cap_moved_with_price_share": charts["Caps"]["cap moved with price share"],
            "price_moved_cap_unchanged_share": charts["Caps"]["price moved, cap unchanged share"],
            "calls_per_day": charts["Calls"]["on_data calls per day"],
            "hour_of_first_call": charts["Calls"]["hour of first call"],
        }, previous=True)
    growth_df = pd.DataFrame(growth).sort_values(["year", "month"]).reset_index(drop=True)
    caps_df = pd.DataFrame(caps).sort_values(["year", "month"]).reset_index(drop=True)
    outputs["checks/data/ebitda_growth_monthly.csv"] = csv_text(growth_df)
    outputs["checks/data/market_cap_updates.csv"] = csv_text(caps_df)

    probe_code = {python_files(export)["main.py"] for export in probes}
    if len(probe_code) != 1:
        raise SystemExit("the two probe exports ran different code")
    outputs["checks/data/code/probe_main.py"] = probe_code.pop()
    outputs["checks/data/code/cap_probe_main.py"] = python_files(cap)["main.py"]

    lines = log_lines(cap.get("logs"))
    if not lines:
        raise SystemExit(f"{CAP_PROBE_KEY}: the export holds no log lines")
    cap_table, reanchors = roll_caps(parse_cap_log(lines))
    outputs["checks/data/cap_probe_2019.log"] = "\n".join(lines) + "\n"
    outputs["checks/data/cap_probe_2019.csv"] = csv_text(cap_table)
    outputs["checks/data/cap_probe_reanchor.csv"] = csv_text(reanchors)
    outputs["checks/data/README.md"] = data_readme(probes, cap, engines, growth_df, caps_df, lines, cap_table,
                                                   reanchors)
    return {"caps": caps_df, "reanchors": reanchors}


def dividend_sentence(reanchors: pd.DataFrame) -> str:
    """What the adjusted and unadjusted price ratios say about the re-anchor errors."""
    gap = (reanchors["adjusted_price_ratio"] / reanchors["unadjusted_price_ratio"] - 1.0).abs()
    shares = ", ".join(f"{fmt_num(r.implied_share_change_pct, 2, sign=True, suffix='%')} ({r.ticker})"
                       for r in reanchors.itertuples(index=False))
    if (gap < 5e-4).all():
        return ("Between each anchor and its re-anchor the adjusted and the unadjusted price moved by the same "
                f"ratio to within {gap.max() * 100:.3f}%, inside the rounding of the logged prices, so no "
                "dividend or split fell in between. The share count implied by the snapshots "
                "(`implied_share_change_pct`: the new snapshot over the anchor cap times the unadjusted price "
                f"ratio, minus one) changed by {shares}: that accounts for most of each error, and the rest is "
                "within the rounding of the logged prices.")
    return (f"`implied_share_change_pct` (the new snapshot over the anchor cap times the unadjusted price "
            f"ratio, minus one) is {shares}; where the adjusted and unadjusted price ratios differ, a dividend "
            "or split fell between the two dates.")


def data_readme(probes, cap, engines, growth, caps, lines, cap_table, reanchors) -> str:
    out = [
        "# Data checks",
        "",
        "Written by `analysis/build_results.py` from the exports in `results/raw/`; a rebuild overwrites it.",
        "",
        "Rank-space returns are the day-to-day change in the capitalisation held at each rank, so the strategy "
        "needs a capitalisation that moves every day. Runs v1 to v3 took it from Morningstar's "
        "`Fundamental.market_cap` in QuantConnect. Probe backtests that place no orders tested what that "
        "field does:",
        "",
        "| Backtest | Key | QuantConnect project / backtest | Created (UTC) | LEAN | Period |",
        "|---|---|---|---|---|---|",
    ]
    for export, name in [(probes[0], "Probe"), (probes[1], "Probe"), (cap, "Cap probe")]:
        meta = export["meta"]
        out.append(f"| {name} | `{meta['key']}` | {meta['projectId']} / `{meta['backtestId']}` | "
                   f"{meta['created']} | {lean_version(export, engines)} | "
                   f"{meta['backtestStart'][:10]} to {meta['backtestEnd'][:10]} |")
    out += [
        "",
        "The probe (`code/probe_main.py`, one backtest per year through its `year` parameter) holds the 100 "
        "largest primary shares by `market_cap` with a price above $1, as the strategy's universe does, and "
        "aggregates what it sees to one chart point per month, because a free-tier backtest keeps few chart "
        "points. A first version of the probe had no once-per-day guard and counted repeat calls on the same "
        "day; it was discarded, and `probe2` is the corrected version.",
        "",
        "| File | Content |",
        "|---|---|",
        "| `market_cap_updates.csv` | How often `market_cap` changed from one day to the next, per month |",
        "| `cap_probe_2019.csv` | The cap probe's log, one row per name and day, with the daily cap "
        "`rank_space.DailyCaps` rolls forward from it |",
        "| `cap_probe_reanchor.csv` | Each change of the reported cap in the cap probe, with the rolled-forward "
        "estimate for that day, its error, the adjusted and unadjusted price ratios since the anchor and the "
        "share-count change the snapshots imply |",
        "| `cap_probe_2019.log` | The cap probe's log lines as exported |",
        "| `ebitda_growth_monthly.csv` | Median and 90th percentile of the absolute value of "
        "`operation_ratios.ebitda_growth.one_year` per month (a check for the companion DCF repository, "
        "measured by the same probe) |",
        "| `code/probe_main.py` | The probe's code as QuantConnect stored it (identical in both probe backtests) |",
        "| `code/cap_probe_main.py` | The cap probe's code as QuantConnect stored it |",
        "",
        "## Market cap updates",
        "",
        "`market_cap_updates.csv`: one row per month. At the first data point of each day the probe compares "
        "every name's `market_cap` and price with the values it saw on the previous day.",
        "",
        "| Column | Meaning |",
        "|---|---|",
        "| `year`, `month` | The month the comparisons fall in |",
        "| `cap_unchanged_share` | Share of comparisons in which the cap did not change |",
        "| `cap_moved_with_price_share` | Share in which the cap changed by the same ratio as the price (within "
        "1e-6), as price times shares would |",
        "| `price_moved_cap_unchanged_share` | Share in which the price changed and the cap did not |",
        "| `calls_per_day` | Mean number of `on_data` calls per day |",
        "| `hour_of_first_call` | Mean New York hour of the day's first `on_data` call |",
        "",
        "QuantConnect stores each monthly point when the next month starts (the last one at the end of the "
        "backtest), so the build assigns each point to the month before its timestamp.",
        "",
    ]
    later = caps[caps["month"] > 1]
    january = caps[caps["month"] == 1]
    moved = caps[caps["cap_moved_with_price_share"] > 0]
    if moved.empty:
        moved_text = "The cap never moved in step with the price."
    else:
        where = ", ".join(f"{MONTHS[int(r.month) - 1]} {int(r.year)} ({r.cap_moved_with_price_share * 100:.2f}% "
                          "of comparisons)" for r in moved.itertuples())
        moved_text = (f"The cap moved in step with the price in no comparison in {len(caps) - len(moved)} of the "
                      f"{len(caps)} months; the exception is {where}.")
    if (january["cap_unchanged_share"] == 1.0).all():
        january_text = (f"In January the share unchanged is exactly 1.0 in "
                        f"{'both years' if len(january) == 2 else 'every year'}.")
    else:
        january_text = "In January the share unchanged is " + ", ".join(
            f"{r.cap_unchanged_share:.4f} in {int(r.year)}" for r in january.itertuples()) + "."
    out += [
        f"From February to December, between {fmt_share(later['cap_unchanged_share'].min())} and "
        f"{fmt_share(later['cap_unchanged_share'].max())} of the comparisons in a month found the cap unchanged, "
        f"while in {fmt_share(later['price_moved_cap_unchanged_share'].min())} to "
        f"{fmt_share(later['price_moved_cap_unchanged_share'].max())} the price had moved and the cap had not. "
        f"{moved_text} {january_text} That pattern fits a value that changes once a month: the probe starts on "
        f"1 January, so January's comparisons contain no change, and in later months about one comparison in "
        f"{round(1.0 / (1.0 - later['cap_unchanged_share'].mean()))} finds a change, one per name per month "
        "(a month has about 21 trading days).",
        "",
        f"`on_data` ran {caps['calls_per_day'].min():.2f} to {caps['calls_per_day'].max():.2f} times a day on "
        "average in a month, which is why the probe, like the strategy, acts only at the first call of each day. "
        f"The mean New York hour of that first call was {caps['hour_of_first_call'].min():.1f} to "
        f"{caps['hour_of_first_call'].max():.1f} in a month: on some dates the first call comes at midnight, on "
        "others at the 16:00 close. The strategy's order times show the same mix (`../../v4/timing.csv`). "
        "Where the first call of one date is at 16:00 and that of the next date at midnight, both see the same "
        "closing price, which is why the share of comparisons with both cap and price unchanged is not zero.",
        "",
        "## Cap probe",
        "",
        "The cap probe (`code/cap_probe_main.py`) logs, for AAPL, MSFT and XOM on every day of its run, the "
        "unadjusted price, the adjusted price, `market_cap`, `company_profile.shares_outstanding` and "
        "unadjusted price times shares. The log runs in the universe selection, which QuantConnect calls "
        "before the day's data, so the prices on a line dated D are the previous trading day's close.",
        "",
        f"`cap_probe_2019.log` holds the {len(lines)} exported log lines; `cap_probe_2019.csv` parses the "
        f"{len(cap_table)} that match the probe's format into `date`, `ticker`, `price_unadjusted`, "
        "`price_adjusted`, `market_cap_bn`, `shares_outstanding_bn` and `price_x_shares_bn` (billions, as "
        "logged, rounded to two decimals by the log), and adds `rolled_cap_bn`: the value "
        "`rank_space.DailyCaps.update` returns when fed each day's `market_cap_bn` and `price_adjusted` in "
        "date order, the same call the algorithm makes in its universe selection when `cap_source` is "
        "`rolled`.",
        "",
    ]
    for ticker, group in cap_table.groupby("ticker", sort=True):
        spans = group.groupby((group["market_cap_bn"] != group["market_cap_bn"].shift()).cumsum())
        parts = [f"{span['market_cap_bn'].iloc[0]:,.2f} from {span['date'].iloc[0]} to {span['date'].iloc[-1]}"
                 for _, span in spans]
        out.append(f"- {ticker}: `market_cap_bn` is {and_list(parts)}, while `price_unadjusted` takes "
                   f"{group['price_unadjusted'].nunique()} different values over the {len(group)} logged days.")
    first = cap_table.groupby("ticker", sort=True).head(1)
    out += [
        "",
        "On the first logged day the unadjusted price times the logged shares, over the reported cap, is "
        + ", ".join(f"{r.price_x_shares_bn / r.market_cap_bn:.4f} for {r.ticker}" for r in first.itertuples())
        + ". The reported cap is the previous close times a share count; for AAPL the logged "
        "`shares_outstanding` is four times that count, because the field is restated for splits made after "
        "the date, so price times `shares_outstanding` cannot stand in for the cap of a past date.",
        "",
        "`cap_probe_reanchor.csv`: at each change of the reported cap, the previous anchor rolled forward with "
        "the adjusted price to that day, against the new snapshot:",
        "",
        "| Ticker | Anchor date | Anchor cap, bn | Re-anchor date | Rolled estimate, bn | New snapshot, bn | "
        "Error |",
        "|---|---|---|---|---|---|---|",
    ]
    for record in reanchors.itertuples(index=False):
        out.append(f"| {record.ticker} | {record.anchor_date} | {record.anchor_cap_bn:,.2f} | {record.reanchor_date} | "
                   f"{record.rolled_estimate_bn:,.2f} | {record.new_snapshot_bn:,.2f} | "
                   f"{fmt_num(record.error_pct, 2, sign=True, suffix='%')} |")
    out += [
        "",
        "`error_pct` is the estimate over the new snapshot, minus one, in percent. The estimate misses changes "
        "in the share count during the month (buybacks, issuance) and counts a dividend as return, while the "
        "snapshot, a price times a share count, does not; the logged prices are also rounded to cents. Each "
        "re-anchor steps the daily cap by that error.",
        "",
        dividend_sentence(reanchors),
        "",
        "## Consequence for this repository",
        "",
        "Runs v1 to v3 ranked the universe and computed rank returns on the raw monthly field. On most days "
        "no rank's cap had changed, so most daily rank returns were exactly zero, and on the day the snapshot "
        "changed they carried a month of price movement at once. Those runs are kept in `../../superseded/` "
        "as a record. v4 (`cap_source = \"rolled\"`, the default) rolls each company's reported cap forward "
        "daily with `rank_space.DailyCaps` and forms ranks and rank returns on that value.",
        "",
        "## EBITDA growth",
        "",
        "`ebitda_growth_monthly.csv`: `year`, `month`, `median_one_year`, `p90_abs_one_year`. The stat-arb "
        "strategy does not use this field; the probe measured it for the DCF repository "
        "(automated-dcf-point-in-time). At the first data point of each month the probe takes "
        "`ebitda_growth.one_year` of every name it holds (missing, NaN and zero values left out) and plots the "
        "median and the 90th percentile of the absolute value.",
        "",
    ]
    parts = [f"between {g['median_one_year'].min():.3f} and {g['median_one_year'].max():.3f} in {year}"
             for year, g in growth.groupby("year", sort=True)]
    out += [
        f"The monthly median lies {' and '.join(parts)}; the 90th percentile of the absolute value lies between "
        f"{growth['p90_abs_one_year'].min():.3f} and {growth['p90_abs_one_year'].max():.3f}. The field is a "
        "decimal fraction (0.10 means 10%).",
        "",
    ]
    return "\n".join(out)


# --------------------------------------------------------------------------- results README
NUMBER_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight",
                9: "nine", 10: "ten"}


def count_words(count: int) -> str:
    return NUMBER_WORDS.get(count, str(count))


def and_list(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def keys_on(rows: list[dict], version: str) -> str:
    return ", ".join(f"`{row['key']}`" for row in rows if row["lean_version"] == version)


def backtest_list_section(list_rows: list[dict], exported: str) -> list[str]:
    """The Backtest lists section of results/README.md."""
    strategy = [row for row in list_rows if row["project_id"] == STRATEGY_PROJECT]
    strategy_published = [row for row in strategy if row["published_key"] in RUN_BY_KEY]
    others = [row for row in list_rows if row["project_id"] != STRATEGY_PROJECT]
    others_published = [row for row in others if row["published_key"]]
    discarded = [row for row in list_rows if row["note"].startswith("not published: discarded")]
    elsewhere = [row for row in others if not row["published_key"] and row not in discarded]
    failed = [row for row in list_rows if row["completed"] != "yes" or row["error"]]
    projects = ", ".join(f"{project} ({what})" for project, what in BACKTEST_LIST_PROJECTS)
    roles = [RUN_BY_KEY[row["published_key"]].role for row in strategy_published]
    if len(strategy_published) == len(strategy):
        strategy_text = (f"The strategy's project {STRATEGY_PROJECT} holds {len(strategy)} backtests, and every one "
                         f"of them is a row of `runs.csv`: {count_words(roles.count('current'))} v4 windows, "
                         f"{count_words(roles.count('superseded'))} superseded runs (v1, v2 and the two v3 chunks) "
                         f"and {count_words(roles.count('check'))} checks. No strategy backtest is left out of "
                         "`results/`. The list shows what QuantConnect held on the export date, so a backtest "
                         "deleted before then would not appear in it.")
    else:
        strategy_text = (f"The strategy's project {STRATEGY_PROJECT} holds {len(strategy)} backtests, of which "
                         f"{len(strategy_published)} are rows of `runs.csv`; the `note` column gives the reason "
                         "for each of the others.")
    return [
        "## Backtest lists",
        "",
        f"`{BACKTEST_LISTS_CSV}` lists every backtest QuantConnect holds in the five projects behind this "
        f"repository: {projects}. It comes from QuantConnect's `backtests/list` API with statistics, exported on "
        f"{exported} and kept as `raw/{BACKTEST_LISTS_RAW}`. Columns: project id and name; backtest id, name "
        "and creation time (UTC); `completed` and `status` as QuantConnect reports them; the first line of any "
        "error; the parameters; QuantConnect's net profit, Sharpe ratio and drawdown (percent) as listed; "
        "`published_key`, the run's key in `runs.csv` or, for a data probe, in `checks/data/` (blank when the "
        "backtest is not published); and `note`, where the run's files are or why it is not published.",
        "",
        f"All {len(list_rows)} backtests completed"
        + (" and none records an error. " if not failed else f"; {len(failed)} record an error. ")
        + strategy_text
        + f" Of the {count_words(len(others))} backtests in the other four projects, "
        f"{count_words(len(others_published))} are published "
        f"(the control, the SPY reference and the three data probes). The {count_words(len(discarded))} discarded "
        "ones are the first versions of the two probes, and "
        + and_list([f"\"{row['name']}\"" for row in elsewhere])
        + " in the reference project belongs to the DCF repository. For every published backtest the listed "
        "creation time, net profit, Sharpe ratio and drawdown equal those of its export; `build_results.py` "
        "stops if they differ, or if a listed backtest is neither published nor given a reason.",
        "",
    ]


def readme_text(rows: list[dict], summary: list[dict], timing: list[dict], years: list[dict], data: dict,
                margin_rows: list[dict], reproduction_identical: bool, list_rows: list[dict],
                lists_exported: str) -> str:
    """results/README.md. Every percentage is rounded once, from the unrounded value."""
    by_key = {row["key"]: row for row in rows}
    v4_table = [
        "| Window | Folder | First fill | Last fill | Months | Net | Sharpe | Max drawdown | Fees | Fees, % of start | "
        "Turnover per day | Paper weights, before costs | Annualised | Realised, after costs | Order cap |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for record in summary:
        cap = f"hit {record['order_cap_date']}" if record["order_cap_hit"] == "yes" else "not reached"
        v4_table.append(
            f"| {window_words(record['window'])} | `v4/{record['window']}/` | {record['first_fill']} | "
            f"{record['last_fill']} | {record['months_covered']:.1f} | "
            f"{fmt_num(record['net_profit_pct'], 3, sign=True, suffix='%')} | {fmt_num(record['sharpe'], 3)} | "
            f"{record['max_drawdown_pct']:.1f}% | {fmt_money(record['total_fees'])} | "
            f"{record['_fees_pct']:.2f}% | {record['turnover_per_day_pct']:.2f}% | "
            f"{fmt_num(record['_paper'], 2, sign=True, suffix='%')} | "
            f"{fmt_num(record['_annualised'], 1, sign=True, suffix='%')} | "
            f"{fmt_num(record['_realised'], 2, sign=True, suffix='%')} | {cap} |"
        )
    paper = [r["_paper"] for r in summary]
    realised = [r["_realised"] for r in summary]
    net = [r["net_profit_pct"] for r in summary]
    fees = [r["total_fees"] for r in summary]
    turnover = [r["turnover_per_day_pct"] for r in summary]
    capped = [r for r in summary if r["order_cap_hit"] == "yes"]
    uncapped = [r for r in summary if r["order_cap_hit"] == "no"]
    two_year = [r for r in summary if r["months_covered"] > 15]
    months = [r["months_covered"] for r in two_year]
    gaps, overlaps = coverage_gaps(summary)
    start_equity = by_key[summary[0]["key"]]["start_equity"]

    superseded = [row for row in rows if row["role"] == "superseded"]
    old_table = [
        "| Run | Folder | Configured | Last fill | Order cap hit | Net | Sharpe | Fees | Orders filled / rejected | "
        "Paper weights, before costs |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in superseded:
        orders = f"{fmt_int(row['orders_filled'])} / {fmt_int(row['orders_invalid'])}"
        old_table.append(
            f"| {row['label']} | `{row['folder']}/` | {row['configured_start']} to {row['configured_end']} | "
            f"{row['last_date_traded']} | {row['order_cap_hit'] or 'n/a'} | "
            f"{fmt_num(row['net_profit'], 3, sign=True, suffix='%')} | {fmt_num(row['sharpe'], 3)} | "
            f"{fmt_money(row['total_fees'])} | {orders} | "
            f"{fmt_num(row['paper_weights_before_costs'], 2, sign=True, suffix='%') or 'n/a'} |"
        )
    caps = data["caps"]
    later = caps[caps["month"] > 1]
    reanchors = data["reanchors"]
    errors = reanchors["error_pct"].abs()
    halves = [row for row in margin_rows if row["key"].startswith("sa__half_leg")]
    fulls = [row for row in margin_rows if row["key"].startswith("rerun__")]
    v4_invalid = [int(r["orders_invalid"]) for r in summary]
    checks = [row for row in rows if row["role"] == "check"]
    canceled = [r["orders_canceled"] for r in timing]
    canceled_pct = [r["orders_canceled"] / r["orders"] * 100.0 for r in timing]
    canceled_late = [r["canceled_from_close_passes"] for r in timing]
    replaced = [r["canceled_replaced_at_next_pass"] for r in timing]
    repeats = [r["passes_repeating_a_close"] for r in timing]
    compared = [r["difference_pts"] for r in years if r["difference_pts"] != ""]
    above = [value for value in compared if value > 0]
    below = [value for value in compared if value < 0]
    close_pct = [r["passes_close"] / r["passes"] * 100.0 for r in timing]
    no_fill_pct = [r["opens_without_fills"] / r["trading_days"] * 100.0 for r in timing]
    two_pct = [r["opens_with_two_passes"] / r["trading_days"] * 100.0 for r in timing]
    late_pct = [r["filled_from_close_passes"] / r["orders_filled"] * 100.0 for r in timing]
    v3_hashes = {row["code_sha256_as_run"] for row in superseded if row["version"] == "v3"}

    layout = "\n".join([
        "```",
        "results/",
        "  README.md                      this file (generated)",
        "  runs.csv                       one row per strategy, check and reference backtest",
        "  raw/                           the QuantConnect exports, gzip-compressed, plus MANIFEST.csv",
        "  provenance/code_hashes.json    SHA-256 of each exported code file, as run and as published",
        "  v4/                            the current version",
        "    summary.csv                  one row per window",
        "    timing.csv                   when each window acted and when its orders filled",
        "    calendar_years.csv           the paper weights per calendar year, against the paper's Table 1",
        *(f"    {record['window'] + '/':<29}{record['configured_start'][:4]} window" for record in summary),
        "  superseded/                    v1 to v3, kept as a record",
        "    v3_2011_2017/  v3_2018_2024/  v2_2018_2024/  v1_2010_2024/",
        "  checks/",
        "    reproduction/                recorded v3 against re-runs, a control and the v4 code",
        "    margin/                      v3 at half the leg weight",
        "    data/                        what Fundamental.market_cap does, and the rolled-forward cap",
        "    backtest_lists.csv           every backtest in the projects involved, published or not",
        "  reference/spy_2015_2019/       SPY buy and hold over the window of the 2024 backtest",
        "```",
    ])
    lines = [
        "# Results",
        "",
        "Every QuantConnect backtest behind this repository, as exported (apart from the one docstring paragraph "
        "described under Provenance), plus the tables derived from them; "
        "`checks/backtest_lists.csv` accounts for every backtest in the projects involved, including the three "
        "discarded probe versions that are not published (Backtest lists below). "
        "`analysis/build_results.py` writes everything here except `raw/`, `provenance/` and the "
        "`qc_report.html` files, which it copies in with `--import-from`; "
        "`analysis/make_figures.py` draws `figures/` from the CSV files.",
        "",
        "## Current version: v4",
        "",
        "v4 ranks companies on a daily capitalisation, the monthly Morningstar value rolled forward with each "
        "company's adjusted price (`rank_space.DailyCaps`, `cap_source = \"rolled\"`), and holds a leg of 2.5% "
        f"of equity per open rank. It ran in {count_words(len(summary))} windows, each from 1 January of its "
        "start year, on "
        f"${start_equity:,.0f}. `v4/summary.csv` has one row per window:",
        "",
        *v4_table,
        "",
        "Net, Sharpe, maximum drawdown, fees and turnover are QuantConnect's statistics up to the day each "
        "window stopped. \"Paper weights, before costs\" is the last value of the algorithm's \"Rank vs name\" "
        "chart: the cumulative P&L of the paper's own L1-normalised weights on rank-space returns, before "
        "costs, from the first trading day. \"Annualised\" compounds it over the days from the first fill to "
        "that sample. \"Realised, after costs\" is the traded book's equity change at the same sample. "
        "QuantConnect's Sharpe ratio subtracts the average rate of its risk-free interest-rate model, while "
        "the account earned no interest on its cash, and its probabilistic Sharpe ratio (`psr_pct`) is the "
        "probability that the Sharpe ratio exceeds 1, not 0 (see the main README).",
        "",
        f"Across the windows the paper's weights made {fmt_num(min(paper), 1, sign=True, suffix='%')} to "
        f"{fmt_num(max(paper), 1, sign=True, suffix='%')} before costs, and the traded book "
        f"{fmt_num(min(realised), 1, sign=True, suffix='%')} to {fmt_num(max(realised), 1, sign=True, suffix='%')} "
        f"after costs at the same sample (net {fmt_num(min(net), 1, sign=True, suffix='%')} to "
        f"{fmt_num(max(net), 1, sign=True, suffix='%')} at the stop). The book turned over "
        f"{min(turnover):.1f}% to {max(turnover):.1f}% of its value a day, because ranks change hands between "
        f"companies as prices move, and paid {fmt_money(min(fees))} to {fmt_money(max(fees))} in fees per window "
        "at 2 basis points.",
        "",
        f"{count_words(len(capped)).capitalize()} of the {count_words(len(summary))} windows stopped at "
        "QuantConnect's 10,000-order cap"
        + (f"; the {' and '.join(window_words(r['window']) for r in uncapped)} window"
           f"{'s' if len(uncapped) > 1 else ''} ran to the configured end"
           if uncapped else "")
        + f". The two-year windows covered {min(months):.1f} to {max(months):.1f} months of trading each. "
        + (f"No v4 window traded in these spans: {and_list([date_span(a, b) for a, b in gaps])}. " if gaps else "")
        + " ".join(f"The {window_words(a)} window overlaps the {window_words(b)} window from {date_span(s, e)}."
                   for a, b, s, e in overlaps),
        "",
        "Rejected orders were rare in v4: "
        f"{min(v4_invalid)} to {max(v4_invalid)} per window (`orders_invalid` in `v4/summary.csv`). Cancelled "
        f"orders were not: {min(canceled)} to {max(canceled)} per window, {min(canceled_pct):.1f}% to "
        f"{max(canceled_pct):.1f}% of each window's orders, and they count toward the order cap (Order timing "
        "below).",
        "",
        "## Order timing",
        "",
        "`v4/timing.csv` has one row per window, counted from its `orders.csv` in New York time. A decision "
        "pass is one submission time: the algorithm acts once per calendar date, at the first data event "
        "QuantConnect delivers for that date. "
        f"{min(close_pct):.1f}% to {max(close_pct):.1f}% of each window's passes were submitted at 16:00 (13:00 "
        "on early-close days), the rest at 00:00. Every pass ranks on the latest universe selection, which "
        "QuantConnect runs at midnight after each trading day on that day's close (`checks/data/`), so the "
        "signal of a pass on date D uses the close of the trading day before D. Orders from a midnight pass "
        "fill at the open of D; orders from a 16:00 pass fill at the next trading day's open, one session "
        f"later. As a result {min(no_fill_pct):.1f}% to {max(no_fill_pct):.1f}% of each window's trading days had "
        f"no fill at the open and {min(two_pct):.1f}% to {max(two_pct):.1f}% received the orders of two passes, "
        f"and {min(late_pct):.1f}% to {max(late_pct):.1f}% of filled orders came from a 16:00 pass.",
        "",
        f"Of the {fmt_int(sum(canceled))} cancelled orders, {fmt_int(sum(canceled_late))} were sent by a 16:00 "
        f"pass, and for {fmt_int(sum(replaced))} the next pass sent a new order for the same company before the "
        "first had filled. Passes dated on a day the exchange was closed: "
        + and_list([f"{r['passes_on_closed_days']} in the {window_words(r['window'])} window"
                    for r in timing if r["passes_on_closed_days"]] or ["none"])
        + ". "
        + (f"{count_words(sum(repeats)).capitalize()} passes (`passes_repeating_a_close`) each came after "
           "another pass with no trading day in between, so no new universe selection ran before them: each "
           "ranked on the same capitalisations as the pass before and added a row of zero rank returns to the "
           "252-day window. " if sum(repeats) > 1 else
           "One pass (`passes_repeating_a_close`) came after another with no trading day in between, so no "
           "new universe selection ran before it: it ranked on the same capitalisations as the pass before "
           "and added a row of zero rank returns to the 252-day window. " if sum(repeats) == 1 else
           "Every pass had a trading day between it and the pass before. ")
        + "The order lists show only passes that sent orders. Trading days are "
        "NYSE sessions from the first to the last fill, by the pandas holiday rules in `build_results.py` plus "
        "the closures of 29 and 30 October 2012 and 5 December 2018; every fill falls on one.",
        "",
        "## Calendar years",
        "",
        "`v4/calendar_years.csv` splits each window's paper-weights series into calendar years, the unit of "
        "the paper's Table 1. Each year runs from the first fill, or from the previous year's last sample, to "
        "the year's last sample; the return over it is compounded and annualised as the paper's Algorithm 5 "
        "does, to the power 252 over the NYSE sessions covered. `table1_pct` is the paper's Table 1 figure "
        "for that year (arXiv:2410.06568v1, rank space, parametric model, before costs) and `difference_pts` "
        f"the annualised figure minus it. Of the {len(compared)} window-years with a Table 1 figure, "
        f"{len(above)} are above it, by {fmt_num(min(above), 2)} to {fmt_num(max(above), 2)} points, and "
        f"{len(below)} below, by {fmt_num(-max(below), 2)} to {fmt_num(-min(below), 2)} points:",
        "",
        "| Window | Year | Part | From | To | Sessions | Cumulative | Annualised | Table 1 | Difference |",
        "|---|---|---|---|---|---|---|---|---|---|",
        *(f"| {window_words(r['window'])} | {r['year']} | {r['part']} | {r['from_date']} | {r['to_date']} | "
          f"{r['trading_days']} | {fmt_num(r['paper_weights_cumulative_pct'], 2, sign=True, suffix='%')} | "
          f"{fmt_num(r['paper_weights_annualised_pct'], 2, sign=True, suffix='%')} | "
          + (f"{r['table1_pct']:.2f}% | {fmt_num(r['difference_pts'], 2, sign=True)} |" if r["table1_pct"] != ""
             else "not in the paper | |")
          for r in years),
        "",
        "Each window folder holds `statistics.json`, `equity.csv`, `rank_vs_name.csv`, `orders.csv` and "
        "`trades.csv` (described under Files below). All eight windows ran the same code: `main.py` and "
        "`rank_space.py` with the SHA-256 as run on QuantConnect in `runs.csv` (`code_sha256_as_run`, "
        "`rank_space_sha256_as_run`). The published copies are stored under `code` in each raw export, with "
        "their own hashes in `code_sha256_published` and `rank_space_sha256_published` (Provenance below).",
        "",
        "## Superseded: v1 to v3",
        "",
        "v1 to v3 formed ranks and rank-space returns from `Fundamental.market_cap` as reported. That field is "
        "a month-end snapshot held for the whole following month: in the probe of `checks/data/`, from "
        f"February to December {fmt_share(later['cap_unchanged_share'].min())} to "
        f"{fmt_share(later['cap_unchanged_share'].max())} of the day-to-day comparisons in a month found a "
        "top-100 company's cap unchanged (January, when the probe starts, has no month boundary), and in the "
        "cap probe the "
        "reported value of AAPL, MSFT and XOM changed once, on 1 February 2019, over six weeks. So in v1 to v3 "
        "most daily rank returns were exactly zero and the rest carried a month of movement on one day. The "
        "rank-space signal those runs traded, and the paper-weight P&L they report, are not the daily "
        "rank-space quantities of the paper. The runs are kept as a record of what was run:",
        "",
        *old_table,
        "",
        "v1 held the paper's dense weights on every rank, v2 renormalised the legs daily, and v3 held a fixed "
        "leg of 5% of equity per open rank. v3's legs asked for more gross exposure than QuantConnect's "
        "default margin allows, so about four orders in ten were rejected (`checks/margin/`). The superseded "
        "folders have the same files as the v4 windows plus `code/main.py`, the code QuantConnect ran; the v3 "
        "folders also have `yearly.csv` and `qc_report.html`. "
        + (f"Both v3 chunks ran the same `main.py` (SHA-256 `{next(iter(v3_hashes))[:8]}...` as run on QuantConnect); "
           "its published copy is `code/main.py` in either v3 folder."
           if len(v3_hashes) == 1 else "The two v3 chunks ran different `main.py` files (`runs.csv`)."),
        "",
        "## Checks",
        "",
        "| Run | Key | Folder | Net | What it tests |",
        "|---|---|---|---|---|",
    ]
    purposes = {
        "rerun__sa_v3_2018": "Refactored v3 code against the recorded v3 run",
        "rerun__sa_v3_2011": "Refactored v3 code against the recorded v3 run",
        "control__sa_v3_2018_recorded_code": "Recorded v3 `main.py`, re-run on the re-run's day and LEAN build",
        "check__v3_via_params_2018": "v4 code with `cap_source=reported` and `leg_weight=0.05`",
        "sa__half_leg_2011": "v3 at a leg weight of 0.025, against the re-run at 0.05",
        "sa__half_leg_2018": "v3 at a leg weight of 0.025, against the re-run at 0.05",
    }
    for row in checks:
        lines.append(f"| {row['label']} | `{row['key']}` | `{row['folder']}/` | "
                     f"{fmt_num(row['net_profit'], 3, sign=True, suffix='%')} | {purposes[row['key']]} |")
    lines += [
        "",
        "- `checks/reproduction/`: "
        + ("the re-run, the control and the v4 code with v3 parameters are identical to each other in every "
           "statistic, closed trade and order, so neither the refactor nor v4 changed v3's logic. "
           if reproduction_identical else "see its README for which runs agree. ")
        + "All three differ from the run recorded on 22 September from the first MDT order on: MDT's fill "
        "prices changed by one constant factor between the two dates, and the two dates also ran on different "
        "LEAN builds.",
        "- `checks/margin/`: at 0.05 legs QuantConnect rejected "
        + " and ".join(f"{r['_rejected_share']:.1f}%" for r in fulls)
        + " of the orders; at 0.025, "
        + " and ".join(f"{r['_rejected_share']:.2f}%" for r in halves)
        + ". v4 uses 0.025.",
        f"- `checks/data/`: `market_cap` is a monthly snapshot (above); rolled forward with the adjusted price, "
        f"it landed within {errors.min():.2f}% to {errors.max():.2f}% of the next snapshot in the cap probe.",
        "",
        *backtest_list_section(list_rows, lists_exported),
        "## Layout",
        "",
        layout,
        "",
        "## Files",
        "",
        "| File | Content |",
        "|---|---|",
        "| `statistics.json` | QuantConnect's statistics, runtime, trade and portfolio statistics, the parameters, "
        "the backtest metadata and QuantConnect's analysis warnings, plus a `derived` block (order counts by "
        "status, first and last date traded, date the order cap was hit, LEAN build, SHA-256 of each code file "
        "as run on QuantConnect and as published) |",
        "| `equity.csv` | The equity curve as QuantConnect sampled it (every few calendar days) |",
        "| `rank_vs_name.csv` | v2 to v4: the paper's weights before costs against the realised book after "
        "costs, cumulative, every fifth trading day |",
        "| `orders.csv` | Every order, including rejected ones (none for the SPY reference, whose export has no "
        "order list) |",
        "| `trades.csv` | Every closed round trip (none for the SPY reference) |",
        "| `yearly.csv` | v3 only: equity at the last sample of each year, the year's return and the paper "
        "weights' cumulative P&L at the same point |",
        "| `code/main.py` | Superseded runs and the SPY reference: the code QuantConnect ran, as published in the "
        "raw export (Provenance below) |",
        "| `qc_report.html` | v3 only: QuantConnect's own generated backtest report |",
        "",
        "## Provenance",
        "",
        "The backtests ran on QuantConnect's free tier in Danyil Nepyivoda's account and were exported through "
        f"QuantConnect's web API on {EXPORT_DATE}: one JSON file per backtest (metadata, statistics, orders, "
        "closed trades, analysis, chart data, logs where the backtest wrote any, and the code of the project "
        "snapshot). The chart data of v1 to v3 was exported again in one file, because some of their chart "
        "series are empty in the per-backtest export; the later exports carry complete charts. `raw/` keeps the "
        "per-backtest files and the stat-arb slice of the chart file, gzip-compressed, plus "
        "`engines__original_runs.json.gz`, the server statistics (LEAN build) of the original runs, whose own "
        "exports do not record it, and `backtest_lists.json.gz`, the slice of QuantConnect's backtest lists "
        f"(exported on {lists_exported}) for the five projects of this repository, re-serialised. "
        "The per-backtest files are as QuantConnect returned them except that, in the exports whose embedded "
        "code carried it, one docstring paragraph was rewritten to leave out the other team members' names; "
        "`provenance/code_hashes.json`, which is not a QuantConnect export, records the SHA-256 of each code "
        "file as run on QuantConnect and as published. "
        "`raw/MANIFEST.csv` records the SHA-256 of each uncompressed file and of its "
        "source file, the provenance file included; `build_results.py --check` verifies them, and the build "
        "stops if a published hash differs from the code in `raw/`.",
        "",
        "LEAN builds (`lean_version` in `runs.csv`): "
        + "; ".join(f"{version}: {keys_on(rows, version)}" for version in sorted({row['lean_version'] for row in rows}))
        + ".",
        "",
        "The SPY reference ran in a separate project (`audit_benchmarks_main.py`, copied to "
        "`reference/spy_2015_2019/code/main.py`). It covers 1 January 2015 to 31 December 2019, the window of "
        "the 2024 backtest described in the main README, with $100,000.",
        "",
        "## The order cap",
        "",
        "QuantConnect's free tier stops a backtest at 10,000 orders: the order log ends at order 10,001, and "
        "QuantConnect's analysis records \"You have exceeded maximum number of orders (10000)\" on the date in "
        "`order_cap_hit`. All statistics, including the compounding annual return, cover only the period up to "
        "that stop. Rejected and cancelled orders count toward the cap. The v3 date chunks and the v4 windows "
        "exist because of it.",
        "",
        "## Columns",
        "",
        "`runs.csv` has one row per strategy, check and reference backtest. The three data probes "
        "(`probe2__2012`, `probe2__2019`, `capprobe2__2019`), which place no orders, are listed with their ids "
        "and LEAN build in `checks/data/README.md` instead. Percentages are in percent, money in US dollars:",
        "",
        "| Column | Meaning |",
        "|---|---|",
        "| `key`, `label`, `folder` | Run key used in `raw/`, a readable label, the folder that holds the run's "
        "files |",
        "| `version` | `v1` to `v4`; for checks, what was run (`v3 re-run`, `v3 control`, `v3 via v4 code`, "
        "`v3 half legs`); `reference` for SPY |",
        "| `role` | `current` (v4), `superseded` (v1 to v3), `check` or `reference` |",
        "| `project_id`, `backtest_id`, `created` | QuantConnect identifiers and the backtest's creation time "
        "(UTC) |",
        "| `lean_version` | LEAN build the backtest ran on |",
        "| `configured_start`, `configured_end` | The backtest window set in the code or parameters |",
        "| `first_date_traded`, `last_date_traded` | New York dates of the first and last filled order |",
        "| `order_cap_hit` | Date of QuantConnect's order-limit message; blank when the run did not reach it |",
        "| `parameters` | QuantConnect project parameters for the run; `code defaults` when none were set |",
        "| `net_profit`, `cagr`, `sharpe`, `psr`, `max_drawdown`, `beta` | QuantConnect statistics: net profit, "
        "compounding annual return, Sharpe ratio, probabilistic Sharpe ratio, maximum drawdown, beta to SPY |",
        "| `orders` | QuantConnect's total order count |",
        "| `orders_filled`, `orders_invalid`, `orders_canceled`, `orders_open_at_stop` | Orders by final status: "
        "filled; rejected by QuantConnect before reaching the market; cancelled; still submitted when the run "
        "stopped |",
        "| `closed_trades`, `win_rate` | Closed round trips and the share of them with positive P&L |",
        "| `total_fees`, `fees_pct_of_start` | Fees paid, and fees as a percentage of starting equity |",
        "| `portfolio_turnover` | QuantConnect's average daily portfolio turnover |",
        "| `start_equity`, `end_equity` | Equity at the start and when the run stopped |",
        "| `paper_weights_before_costs` | Last value of the \"Rank vs name\" rank-space series, percent; blank "
        "where the run had no such chart |",
        "| `code_sha256_as_run`, `rank_space_sha256_as_run` | SHA-256 of the UTF-8 text of `main.py` and "
        "`rank_space.py` as QuantConnect ran them, from `provenance/code_hashes.json`; blank where the run had no "
        "`rank_space.py` |",
        "| `code_sha256_published`, `rank_space_sha256_published` | SHA-256 of the same files as published under "
        "`code` in the raw export; they differ from the `_as_run` column where one docstring paragraph was "
        "rewritten to leave out the other team members' names |",
        "",
        "`v4/summary.csv`: `window`, `key`, `backtest_id`; `configured_start` and `configured_end`; `first_fill` "
        "and `last_fill` (New York dates of the first and last filled order); `months_covered` (days from first "
        "to last fill over 30.44); `net_profit_pct`, `cagr_pct`, `sharpe`, `psr_pct`, `max_drawdown_pct`, "
        "`beta`, `total_fees`, `turnover_per_day_pct` (QuantConnect statistics); `fees_pct_of_start`; `orders` "
        "and the counts by status; `closed_trades`; `last_sample` (date of the last \"Rank vs name\" point); "
        "`paper_weights_before_costs_pct` and `realised_after_costs_pct` at that sample; "
        "`paper_weights_annualised_pct` ((1 + p)^(365.25 / days) - 1 over the days from `first_fill` to "
        "`last_sample`); `order_cap_hit` (`yes` or `no`) and `order_cap_date`.",
        "",
        "`v4/timing.csv`: `window`; `first_fill` and `last_fill`; `trading_days` (NYSE sessions from the first "
        "to the last fill); `passes` (distinct order submission times, New York), split into `passes_midnight` "
        "(00:00) and `passes_close` (16:00, or 13:00 on an early-close day), with `passes_close_pct`; "
        "`passes_on_closed_days` (passes dated on a day the exchange was closed); `passes_repeating_a_close` "
        "(passes with no trading day between them and the pass before, so no new universe selection); "
        "`opens_with_fills`, "
        "`opens_without_fills` and `opens_with_two_passes` (trading days on which orders of at least one, of no "
        "and of two passes filled); `orders_filled`, `filled_from_close_passes` and "
        "`filled_from_close_passes_pct`; `orders`, `orders_canceled` and `orders_canceled_pct`; "
        "`canceled_from_close_passes`; `canceled_replaced_at_next_pass` (cancelled orders for whose company the "
        "next pass sent a new order).",
        "",
        "`v4/calendar_years.csv`: `window`, `year`; `part` (`whole` when the year's last sample is in "
        "December, else `part`); `from_date` and `to_date` (the span, see Calendar years); `trading_days` (NYSE "
        "sessions in the span, the first fill counted, a starting sample not); `paper_weights_cumulative_pct` "
        "and `paper_weights_annualised_pct` ((1 + p)^(252 / trading_days) - 1); `table1_pct` (blank for years "
        "outside the paper's 2007 to 2022); `difference_pts` (annualised minus Table 1, percentage points).",
        "",
        "`equity.csv`: `date` (New York date of the sample), `equity` (close of QuantConnect's equity candle), "
        "`spy_benchmark` (QuantConnect's benchmark series: SPY price adjusted for splits and dividends), "
        "`drawdown_pct` (percent below the running peak), `exposure_long` and `exposure_short` (long and short "
        "holdings as a fraction of equity, the short side negative), `portfolio_turnover` (the turnover sample "
        "QuantConnect stamps one day after the equity sample, as a fraction of equity; a point sample, zero on "
        "days without trading). Columns a run's export does not have are left out.",
        "",
        "`rank_vs_name.csv`: `rank_space_paper_weights_before_costs_pct` is the cumulative before-cost P&L of "
        "the paper's L1-normalised weights on rank-space returns, computed inside the algorithm; "
        "`name_space_realised_after_costs_pct` is the book's equity change since the first trading day, after "
        "fees. Both in percent, sampled every fifth trading day.",
        "",
        "`orders.csv`: `submitted_utc`, `filled_utc` (blank if never filled), `type` (all MarketOnOpen), "
        "`fill_price`, `value` (signed, US dollars), `fee`, `status` (Filled, Invalid = rejected, Canceled, "
        "Submitted), `tag` (`closed` marks an exit; a few orders carry `left universe`, v1's `Liquidated` or a "
        "QuantConnect message).",
        "",
        "`trades.csv`: one closed round trip per row with entry and exit times (UTC) and prices, `profit_loss` "
        "before fees, `total_fees`, maximum adverse and favourable excursion (`mae`, `mfe`), `duration_days` "
        "and the ids of the orders involved.",
        "",
        "`yearly.csv`: `equity_date` is the last equity sample of the year (the last year is partial, up to the "
        "stop); `year_return_pct` is measured from the previous row, the first from starting equity; the "
        "paper-weights and name-space columns are the last \"Rank vs name\" values of the same year.",
        "",
        "## Rebuild",
        "",
        "Python 3.11 with the package versions pinned in `requirements-dev.txt`, the versions that built the "
        "committed files (`--check` compares text byte for byte, so another pandas or numpy release could "
        "format a number differently):",
        "",
        "```",
        "python analysis/build_results.py           # rebuild everything here from raw/",
        "python analysis/build_results.py --check   # verify raw/ and compare with a fresh rebuild",
        "python analysis/make_figures.py            # redraw figures/ from the CSV files",
        "```",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- build
def build(raw: Path) -> dict[str, str]:
    """Every derived file, as {path relative to results/: text}."""
    exports, charts = load_raw(raw)
    engines = exports[ENGINES_KEY]
    provenance = load_provenance(raw, exports)
    outputs: dict[str, str] = {}
    rows = []
    summary = []
    timing = []
    years: list[dict] = []
    for run in RUNS:
        export = exports[run.key]
        chart = run_chart(run.key, export, charts)
        order_info = order_summary(export)
        ranks = rank_frame(chart)
        rows.append(runs_row(run, export, order_info, ranks, engines, provenance))
        if run.kind not in FOLDER_KINDS:
            continue
        folder = run.folder
        equity = equity_frame(chart)
        outputs[f"{folder}/statistics.json"] = json_text(statistics_document(run, export, order_info, engines,
                                                                             provenance))
        outputs[f"{folder}/equity.csv"] = csv_text(equity)
        if ranks is not None:
            outputs[f"{folder}/rank_vs_name.csv"] = csv_text(ranks)
        if export.get("orders"):
            outputs[f"{folder}/orders.csv"] = csv_text(orders_frame(export["orders"]))
        if export.get("closedTrades"):
            outputs[f"{folder}/trades.csv"] = csv_text(trades_frame(export["closedTrades"]))
        if run.kind == "superseded" and run.version == "v3":
            start_equity = number(export["statistics"]["Start Equity"])
            outputs[f"{folder}/yearly.csv"] = csv_text(yearly_frame(equity, ranks, start_equity))
        if run.kind in ("superseded", "reference") and python_files(export).get("main.py"):
            outputs[f"{folder}/code/main.py"] = python_files(export)["main.py"]
        if run.kind == "v4":
            window = folder.split("/", 1)[1]
            summary.append(summary_row(window, rows[-1], ranks, chart))
            timing.append(order_timing(window, export))
            years += calendar_years(window, chart, rows[-1]["first_date_traded"])

    outputs["runs.csv"] = csv_text(pd.DataFrame(rows, columns=list(RUNS_COLUMNS)))
    outputs["v4/summary.csv"] = csv_text(pd.DataFrame(summary, columns=list(SUMMARY_COLUMNS)))
    outputs["v4/timing.csv"] = csv_text(pd.DataFrame(timing, columns=list(TIMING_COLUMNS)))
    outputs["v4/calendar_years.csv"] = csv_text(pd.DataFrame(years, columns=list(CALENDAR_YEAR_COLUMNS)))
    reproduction_identical = build_reproduction(outputs, exports, engines, provenance)
    margin_rows = build_margin(outputs, exports, charts, engines, provenance)
    data = build_data_checks(outputs, exports, engines)
    lists = load_backtest_lists(raw)
    list_rows = backtest_list_rows(lists, exports)
    outputs[BACKTEST_LISTS_CSV] = csv_text(pd.DataFrame(list_rows, columns=list(BACKTEST_LIST_COLUMNS)))
    outputs["README.md"] = readme_text(rows, summary, timing, years, data, margin_rows, reproduction_identical,
                                       list_rows, lists.get("exported", ""))
    return outputs


def write_outputs(outputs: dict[str, str], target: Path) -> None:
    for relative, text in outputs.items():
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))


def first_difference(expected: bytes, actual: bytes) -> str:
    expected_lines = expected.split(b"\n")
    actual_lines = actual.split(b"\n")
    for number_line, (left, right) in enumerate(zip(expected_lines, actual_lines), start=1):
        if left != right:
            return f"line {number_line}"
    return f"line count {len(actual_lines)} instead of {len(expected_lines)}"


def check() -> int:
    problems = verify_manifest(RESULTS)
    with tempfile.TemporaryDirectory() as temporary:
        target = Path(temporary)
        outputs = build(RAW)
        write_outputs(outputs, target)
        for relative in sorted(outputs):
            fresh = normalise((target / relative).read_bytes())
            committed_path = RESULTS / relative
            if not committed_path.exists():
                problems.append(f"missing results/{relative}")
                continue
            committed = normalise(committed_path.read_bytes())
            if committed != fresh:
                problems.append(f"differs results/{relative} (first at {first_difference(fresh, committed)})")
    expected = set(outputs) | set(manifest_files(RESULTS)) | {f"raw/{MANIFEST_NAME}"}
    for path in sorted(RESULTS.rglob("*")):
        relative = path.relative_to(RESULTS).as_posix()
        if path.is_file() and relative not in expected:
            problems.append(f"unexpected results/{relative}")
    if problems:
        print(f"{len(problems)} difference(s):")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print(f"results/ matches a fresh rebuild ({len(outputs)} derived files) and raw/MANIFEST.csv")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--import-from", type=Path, help="folder with the QuantConnect exports")
    parser.add_argument("--check", action="store_true", help="compare results/ with a fresh rebuild")
    args = parser.parse_args()
    if args.check:
        return check()
    if args.import_from:
        import_exports(args.import_from)
    problems = verify_manifest(RESULTS)
    if problems:
        print("raw/ does not match its manifest:\n  " + "\n  ".join(problems))
        return 1
    outputs = build(RAW)
    write_outputs(outputs, RESULTS)
    print(f"wrote {len(outputs)} files under {RESULTS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

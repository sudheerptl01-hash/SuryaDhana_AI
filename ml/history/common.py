"""Shared paths, URL builders and calendar helpers for the P4 history stream."""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "ml" / "data_raw" / "hist"
RAW_CM, RAW_MTO, RAW_PR = RAW / "cm", RAW / "mto", RAW / "pr"
MANIFEST = RAW / "manifest.jsonl"
STAGE = REPO / "ml" / "data_hist"
PARTS = STAGE / "parts"
RESULTS = REPO / "ml" / "results" / "improve" / "history"
LOG_PATH = RESULTS / "log.txt"
EXPORT = REPO / "ml" / "results" / "improve" / "cache" / "eod_export_v1.parquet"

ARCHIVE = "https://archives.nseindia.com"
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
          "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

WINDOW_START = date(2016, 10, 3)
WINDOW_END = date(2021, 9, 30)
# Days inside the stored window (equity_eod export) fetched for the overlap check.
OVERLAP_DAYS = [date(2021, 10, 1), date(2021, 10, 4)]

# Sessions on a weekend or a listed holiday that must be present.
SPECIAL_SESSIONS = {
    "2016-10-30": "Sunday Muhurat",
    "2017-10-19": "Muhurat (Diwali holiday)",
    "2018-11-07": "Muhurat (Diwali holiday)",
    "2019-10-27": "Sunday Muhurat",
    "2020-02-01": "Saturday Budget session",
    "2020-11-14": "Saturday Muhurat",
}


def mon(d: date) -> str:
    return MONTHS[d.month - 1]


def cm_name(d: date) -> str:
    return f"cm{d:%d}{mon(d)}{d.year}bhav.csv.zip"


def mto_name(d: date) -> str:
    return f"MTO_{d:%d%m%Y}.DAT"


def pr_name(d: date) -> str:
    return f"PR{d:%d%m%y}.zip"


def cm_url(d: date) -> str:
    return f"{ARCHIVE}/content/historical/EQUITIES/{d.year}/{mon(d)}/{cm_name(d)}"


def mto_url(d: date) -> str:
    return f"{ARCHIVE}/archives/equities/mto/{mto_name(d)}"


def pr_url(d: date) -> str:
    return f"{ARCHIVE}/archives/equities/bhavcopy/pr/{pr_name(d)}"


def local_path(kind: str, d: date) -> Path:
    return {"cm": RAW_CM / cm_name(d), "mto": RAW_MTO / mto_name(d),
            "pr": RAW_PR / pr_name(d)}[kind]


def url_for(kind: str, d: date) -> str:
    return {"cm": cm_url, "mto": mto_url, "pr": pr_url}[kind](d)


def calendar_days(start: date = WINDOW_START, end: date = WINDOW_END) -> list[date]:
    out, d = [], start
    while d <= end:
        out.append(d)
        d += timedelta(days=1)
    return out


def read_manifest() -> dict[tuple[str, str], dict]:
    """Last manifest record per (iso date, kind)."""
    rec: dict[tuple[str, str], dict] = {}
    if MANIFEST.exists():
        with MANIFEST.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rec[(r["date"], r["kind"])] = r
    return rec


def get_logger(name: str) -> logging.Logger:
    RESULTS.mkdir(parents=True, exist_ok=True)
    lg = logging.getLogger(name)
    if not lg.handlers:
        lg.setLevel(logging.INFO)
        fh = logging.FileHandler(LOG_PATH)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s %(name)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
        lg.addHandler(fh)
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
        lg.addHandler(sh)
    return lg

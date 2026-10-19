"""Shared paths, constants, session calendar and logging for ml/extdata."""
from __future__ import annotations

import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "2")

REPO = Path(__file__).resolve().parent.parent.parent
ML = REPO / "ml"
RAW = ML / "data_raw"
RAW_FO = RAW / "fo"
RAW_IDX = RAW / "indices"
RAW_PART = RAW / "participant"
RAW_LISTS = RAW / "lists"
EXT = ML / "data_ext"
OUT = ML / "results" / "improve" / "extdata"
CACHE = ML / "results" / "improve" / "cache"
EOD_EXPORT = CACHE / "eod_export_v1.parquet"
FEAT_EXPORT = CACHE / "features_prices_export_v1.parquet"
V1_DATASET = ML / "data_5y" / "model_dataset.parquet"
LOG_PATH = OUT / "log.txt"

SEED = 108
ARCHIVE = "https://archives.nseindia.com"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "Chrome/121.0.0.0 Safari/537.36")

# main window (P3) and the optional history extension (for P4)
MAIN_START = date(2021, 10, 1)
MAIN_END = date(2026, 10, 16)
HIST_START = date(2016, 10, 3)
HIST_END = date(2021, 9, 30)

# trading sessions missing from nse_market.duckdb that P1 is adding
# (IMPROVEMENT_PLAN.md section 0 item 2)
SPECIAL_SESSIONS = [date(2023, 11, 12), date(2024, 3, 2), date(2024, 5, 18),
                    date(2025, 2, 1), date(2025, 10, 21), date(2026, 2, 1)]

# F&O bhavcopy format switch: legacy fo<DD><MON><YYYY>bhav.csv.zip up to and
# including 2024-07-05, UDiFF BhavCopy_NSE_FO_* from 2024-07-08
FO_LEGACY_LAST = date(2024, 7, 5)
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
          "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

# universe filter (ml/data.py)
MIN_PRICE = 10.0
MIN_MED_TURNOVER = 1e7
FEATURE_START = "2022-10-03"


def ensure_dirs() -> None:
    for p in (RAW_FO, RAW_IDX, RAW_PART, RAW_LISTS, EXT, OUT):
        p.mkdir(parents=True, exist_ok=True)


def get_logger(name: str = "extdata") -> logging.Logger:
    ensure_dirs()
    log = logging.getLogger(name)
    if not log.handlers:
        log.setLevel(logging.INFO)
        fmt = logging.Formatter("%(asctime)s %(levelname)s [%(threadName)s] %(message)s",
                                "%Y-%m-%d %H:%M:%S")
        fh = logging.FileHandler(LOG_PATH)
        fh.setFormatter(fmt)
        log.addHandler(fh)
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        log.addHandler(sh)
        log.propagate = False
    return log


def eod_sessions() -> list[date]:
    """Every distinct date in the EOD export (2021-10-01..2026-10-16)."""
    import pyarrow.parquet as pq
    t = pq.read_table(EOD_EXPORT, columns=["date"])
    vals = sorted(set(t.column("date").to_pylist()))
    return [v if isinstance(v, date) else v.date() for v in vals]


def main_sessions() -> list[date]:
    """EOD-export sessions plus the six special sessions P1 is adding."""
    return sorted(set(eod_sessions()) | set(SPECIAL_SESSIONS))


def hist_candidate_days() -> list[date]:
    """2016-10-03..2021-09-30 candidate days for the history extension: every
    weekday (a 404 marks a holiday) plus known weekend special sessions
    (Muhurat / Budget / special live sessions) of that period."""
    weekend_specials = {date(2016, 10, 30), date(2019, 10, 27), date(2020, 2, 1),
                        date(2020, 11, 14)}
    out, d = [], HIST_START
    while d <= HIST_END:
        if d.weekday() < 5 or d in weekend_specials:
            out.append(d)
        d += timedelta(days=1)
    return out


def fo_url(d: date) -> tuple[str, str, str]:
    """(url, local file name, source_format) of the F&O bhavcopy for date d."""
    if d <= FO_LEGACY_LAST:
        mon = MONTHS[d.month - 1]
        name = f"fo{d.day:02d}{mon}{d.year}bhav.csv.zip"
        return (f"{ARCHIVE}/content/historical/DERIVATIVES/{d.year}/{mon}/{name}",
                name, "legacy")
    name = f"BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
    return f"{ARCHIVE}/content/fo/{name}", name, "udiff"


def idx_url(d: date) -> tuple[str, str]:
    name = f"ind_close_all_{d:%d%m%Y}.csv"
    return f"{ARCHIVE}/content/indices/{name}", name


def part_url(d: date) -> tuple[str, str]:
    name = f"fao_participant_oi_{d:%d%m%Y}.csv"
    return f"{ARCHIVE}/content/nsccl/{name}", name


LIST_FILES = {
    "ind_nifty500list.csv": f"{ARCHIVE}/content/indices/ind_nifty500list.csv",
    "ind_niftymidcap150list.csv": f"{ARCHIVE}/content/indices/ind_niftymidcap150list.csv",
    "ind_niftysmallcap250list.csv": f"{ARCHIVE}/content/indices/ind_niftysmallcap250list.csv",
    "ind_niftymicrocap250_list.csv": f"{ARCHIVE}/content/indices/ind_niftymicrocap250_list.csv",
    "ind_nifty50list.csv": f"{ARCHIVE}/content/indices/ind_nifty50list.csv",
    "EQUITY_L.csv": f"{ARCHIVE}/content/equities/EQUITY_L.csv",
}

#!/usr/bin/env python3
"""Resume-safe download of the daily PR bundles (plus a few named check files).

Queue (in this order, one request in flight, see common.PoliteGetter):
  1. sec_bhavdata_full for the six missing sessions and for 2022-03-04..2022-03-09
     (the 2022-03-08 anomaly), into ml/data_raw/pr/sec/;
  2. the CM bhavcopy zip that nse_historical_ingest.fetch_day uses for ISIN
     enrichment (legacy cm<DDMONYYYY>bhav.csv.zip, UDiFF fallback) for the six
     missing sessions, into ml/data_raw/pr/cm/;
  3. EQUITY_L.csv into ml/data_raw/pr/master/;
  4. PR<ddmmyy>.zip for every session date in the store (from the parquet export)
     plus the six missing sessions, 2021-10-01..2026-10-16, into ml/data_raw/pr/.

A file already on disk (valid zip for .zip names, non-empty otherwise) is skipped.
Every outcome is appended to ml/data_raw/pr/_manifest.csv (name, url, status,
bytes, sha256, fetched_at).

Run (from the repo root):
  OMP_NUM_THREADS=2 python3 -I ml/integrity/download_pr.py [--only-named] [--retry-absent]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import sys
import time
import zipfile
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ml.integrity.common import (EOD_EXPORT, EQUITY_L_URL, MISSING_SESSIONS, PR_URL, RAW,  # noqa: E402
                                 RAW_CM, RAW_MASTER, RAW_SEC, SEC_URL, STORE_END, STORE_START,
                                 PoliteGetter, atomic_write_bytes, log, pr_name, sec_name)

MANIFEST = RAW / "_manifest.csv"
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
LEGACY_CM = "https://archives.nseindia.com/content/historical/EQUITIES/{yyyy}/{mon}/cm{dd}{mon}{yyyy}bhav.csv.zip"
UDIFF_CM = "https://archives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{yyyymmdd}_F_0000.csv.zip"
CHECK_SEC_DATES = ["2022-03-04", "2022-03-07", "2022-03-08", "2022-03-09"]


def _valid(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    if path.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(path) as zf:
                return len(zf.namelist()) > 0
        except zipfile.BadZipFile:
            return False
    return True


def _absent() -> set[str]:
    if not MANIFEST.exists():
        return set()
    with open(MANIFEST) as fh:
        return {r["name"] for r in csv.DictReader(fh) if r["status"] == "404"}


def _record(name: str, url: str, status: int, body: bytes | None) -> None:
    new = not MANIFEST.exists()
    with open(MANIFEST, "a", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["name", "url", "status", "bytes", "sha256", "fetched_at"])
        w.writerow([name, url, status, len(body) if body else 0,
                    hashlib.sha256(body).hexdigest() if body else "",
                    datetime.now().isoformat(timespec="seconds")])


def session_dates() -> list[date]:
    import pandas as pd
    d = pd.read_parquet(EOD_EXPORT, columns=["date"])["date"].drop_duplicates()
    ds = {pd.Timestamp(x).date() for x in d}
    ds |= {date.fromisoformat(x) for x in MISSING_SESSIONS}
    lo, hi = date.fromisoformat(STORE_START), date.fromisoformat(STORE_END)
    return sorted(x for x in ds if lo <= x <= hi)


def fetch_to(g: PoliteGetter, url: str, path: Path, absent: set[str], retry_absent: bool,
             expect_zip: bool) -> str:
    if _valid(path):
        return "skip"
    if path.name in absent and not retry_absent:
        return "absent"
    status, body = g.get(url)
    if status == 200 and body:
        if expect_zip and not body[:2] == b"PK":
            _record(path.name, url, -2, body)
            log(f"{path.name}: body is not a zip ({body[:40]!r}); not saved", "download")
            return "bad"
        if expect_zip:
            try:
                zipfile.ZipFile(io.BytesIO(body)).namelist()
            except zipfile.BadZipFile:
                _record(path.name, url, -3, body)
                log(f"{path.name}: corrupt zip; not saved", "download")
                return "bad"
        atomic_write_bytes(path, body)
        _record(path.name, url, 200, body)
        return "ok"
    _record(path.name, url, status, None)
    return "404" if status == 404 else f"fail{status}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-named", action="store_true", help="named check files only, no PR bundles")
    ap.add_argument("--retry-absent", action="store_true", help="re-request names that 404'd before")
    ap.add_argument("--all-days", action="store_true",
                    help="probe a PR bundle for EVERY calendar day of the window (session calendar audit)")
    a = ap.parse_args(argv)
    if a.all_days:
        return all_days(a.retry_absent)
    for p in (RAW, RAW_SEC, RAW_CM, RAW_MASTER):
        p.mkdir(parents=True, exist_ok=True)
    g = PoliteGetter(tag="download")
    absent = _absent()
    t0 = time.time()

    # 1-3: named files
    named: list[tuple[str, Path, bool]] = []
    for s in MISSING_SESSIONS + CHECK_SEC_DATES:
        d = date.fromisoformat(s)
        named.append((SEC_URL.format(ddmmyyyy=f"{d:%d%m%Y}"), RAW_SEC / sec_name(d), False))
    named.append((EQUITY_L_URL, RAW_MASTER / "EQUITY_L.csv", False))
    res: dict[str, int] = {}
    for url, path, z in named:
        r = fetch_to(g, url, path, absent, a.retry_absent, z)
        res[r] = res.get(r, 0) + 1
        log(f"named {path.relative_to(RAW)} -> {r}", "download")
    # CM bhavcopy for ISIN enrichment, fetch_day's order: legacy first, UDiFF if absent
    for s in MISSING_SESSIONS:
        d = date.fromisoformat(s)
        mon = MONTHS[d.month - 1]
        leg = RAW_CM / f"cm{d:%d}{mon}{d.year}bhav.csv.zip"
        udf = RAW_CM / f"BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
        if _valid(udf):
            r = "skip"
        else:
            r = fetch_to(g, LEGACY_CM.format(yyyy=d.year, mon=mon, dd=f"{d:%d}"), leg, absent,
                         a.retry_absent, True)
            if r not in ("ok", "skip"):
                r = "udiff:" + fetch_to(g, UDIFF_CM.format(yyyymmdd=f"{d:%Y%m%d}"), udf, absent,
                                        a.retry_absent, True)
        res[r] = res.get(r, 0) + 1
        log(f"named cm bhavcopy {d} -> {r}", "download")
    log(f"named files done: {res} ({time.time() - t0:.0f}s)", "download")
    if a.only_named:
        return 0

    # 4: PR bundles (missing sessions first, then chronological)
    days = session_dates()
    first = [date.fromisoformat(s) for s in MISSING_SESSIONS]
    order = first + [d for d in days if d not in set(first)]
    res = {}
    for i, d in enumerate(order, 1):
        r = fetch_to(g, PR_URL.format(ddmmyy=f"{d:%d%m%y}"), RAW / pr_name(d), absent, a.retry_absent, True)
        res[r] = res.get(r, 0) + 1
        if r not in ("skip", "ok") or i % 50 == 0 or i == len(order):
            log(f"PR [{i}/{len(order)}] {d} -> {r}; totals {res}; requests {g.n_requests}, "
                f"back-offs {g.n_backoffs}, {time.time() - t0:.0f}s", "download")
    log(f"PR bundles done: {res}; requests {g.n_requests}, back-offs {g.n_backoffs}, "
        f"{time.time() - t0:.0f}s", "download")
    return 0


def all_days(retry_absent: bool) -> int:
    """Calendar audit: a PR bundle exists for a session and 404s on a closure (no echo)."""
    from datetime import timedelta
    g = PoliteGetter(tag="download-all")
    absent = _absent()
    lo, hi = date.fromisoformat(STORE_START), date.fromisoformat(STORE_END)
    stored = set(session_dates())          # the main pass fetches these
    days, d = [], lo
    while d <= hi:
        if d not in stored:
            days.append(d)
        d += timedelta(days=1)
    t0, res = time.time(), {}
    for i, d in enumerate(days, 1):
        r = fetch_to(g, PR_URL.format(ddmmyy=f"{d:%d%m%y}"), RAW / pr_name(d), absent, retry_absent, True)
        res[r] = res.get(r, 0) + 1
        if r == "ok" and d.weekday() >= 5:
            log(f"PR all-days: weekend bundle exists {d} ({d:%A})", "download-all")
        if i % 100 == 0 or i == len(days):
            log(f"PR all-days [{i}/{len(days)}] {d}; totals {res}; requests {g.n_requests}, "
                f"{time.time() - t0:.0f}s", "download-all")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

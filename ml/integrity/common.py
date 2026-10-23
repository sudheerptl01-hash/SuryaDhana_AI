"""Shared paths, logging and the polite NSE-archive client of the P1 stream.

Download policy (ml/IMPROVEMENT_PLAN.md section 3): browser user agent, a random
1.0-2.0 s gap before every request, a 60 s back-off and a halved request rate on
403/429/5xx, and never more than one request in flight for this stream.  The
last rule holds across processes: every request is made while holding an
exclusive flock on ml/data_raw/pr/.net.lock, and the delay is slept inside the
lock, so two P1 processes interleave instead of doubling the rate.  The current
rate multiplier is persisted next to the lock so a back-off seen by one process
slows the other one too.
"""
from __future__ import annotations

import fcntl
import json
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

ML_DIR = REPO / "ml"
DB_PATH = REPO / "nse_market.duckdb"
CACHE = ML_DIR / "results" / "improve" / "cache"
EOD_EXPORT = CACHE / "eod_export_v1.parquet"
FEAT_EXPORT = CACHE / "features_prices_export_v1.parquet"
LOCK_FILE = ML_DIR / "results" / "improve" / "LOCK_duckdb_write"
OUT = ML_DIR / "results" / "improve" / "integrity"
LOG_FILE = OUT / "log.txt"
DATA_EXT = ML_DIR / "data_ext"
RAW = ML_DIR / "data_raw" / "pr"          # PR bundles (one zip per session)
RAW_SEC = RAW / "sec"                      # sec_bhavdata_full files fetched for checks
RAW_CM = RAW / "cm"                        # legacy / UDiFF CM bhavcopy zips (ISIN enrichment)
RAW_MASTER = RAW / "master"                # EQUITY_L.csv
DATA_V1 = ML_DIR / "data_5y"
DATA_V2 = ML_DIR / "data_5y_v2"
SEED = 108

ARCHIVES = "https://archives.nseindia.com"
PR_URL = ARCHIVES + "/archives/equities/bhavcopy/pr/PR{ddmmyy}.zip"
SEC_URL = ARCHIVES + "/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"
EQUITY_L_URL = ARCHIVES + "/content/equities/EQUITY_L.csv"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "Chrome/121.0.0.0 Safari/537.36")

# The six sessions the lead's continuity probe found missing from the store.
MISSING_SESSIONS = ["2023-11-12", "2024-03-02", "2024-05-18", "2025-02-01", "2025-10-21", "2026-02-01"]
STORE_START, STORE_END = "2021-10-01", "2026-10-16"


def log(msg: str, tag: str = "p1") -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now().isoformat(timespec='seconds')} [{tag}] {msg}"
    with open(LOG_FILE, "a") as fh:
        fh.write(line + "\n")
    print(line, flush=True)


def _jd(o):
    import numpy as np
    import pandas as pd
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, (pd.Timestamp, np.datetime64)):
        return str(pd.Timestamp(o).date())
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, set):
        return sorted(o)
    return str(o)


def wjson(path: Path, obj) -> None:
    """Atomic JSON write (NaN -> null through the default hook where possible)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(_clean(obj), indent=1, default=_jd))
    tmp.replace(path)


def _clean(o):
    import math
    if isinstance(o, float):
        return None if not math.isfinite(o) else o
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


class PoliteGetter:
    """One request in flight across all P1 processes; 1.0-2.0 s gaps; 60 s back-off."""

    LOCK = RAW / ".net.lock"
    STATE = RAW / ".net_state.json"
    BACKOFF_STATUSES = {403, 429}

    def __init__(self, timeout: int = 60, max_attempts: int = 6, tag: str = "net"):
        import requests
        self.timeout, self.max_attempts, self.tag = timeout, max_attempts, tag
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": USER_AGENT,
                               "Accept": "*/*",
                               "Accept-Language": "en-US,en;q=0.9",
                               "Referer": "https://www.nseindia.com/"})
        self.n_requests = 0
        self.n_backoffs = 0
        RAW.mkdir(parents=True, exist_ok=True)

    def _mult(self) -> float:
        try:
            return float(json.loads(self.STATE.read_text()).get("rate_mult", 1.0))
        except Exception:  # noqa: BLE001
            return 1.0

    def _set_mult(self, m: float) -> None:
        self.STATE.write_text(json.dumps({"rate_mult": m, "updated": datetime.now().isoformat()}))

    def get(self, url: str) -> tuple[int, bytes | None]:
        """Return (status, body).  status 404 -> (404, None); exhausted -> (last_status, None)."""
        import requests
        last = -1
        for attempt in range(1, self.max_attempts + 1):
            with open(self.LOCK, "a+") as lk:
                fcntl.flock(lk, fcntl.LOCK_EX)
                try:
                    mult = self._mult()
                    time.sleep(random.uniform(1.0, 2.0) * mult)
                    try:
                        r = self.s.get(url, timeout=self.timeout)
                        last = r.status_code
                        body = r.content
                    except requests.RequestException as exc:
                        last, body = -1, None
                        log(f"request error {url}: {exc!r}", self.tag)
                    self.n_requests += 1
                    if last == 200:
                        return 200, body
                    if last == 404:
                        return 404, None
                    if last in self.BACKOFF_STATUSES or last >= 500 or last == -1:
                        self.n_backoffs += 1
                        new = min(mult * 2.0, 16.0)
                        self._set_mult(new)
                        log(f"HTTP {last} on {url} (attempt {attempt}); backing off 60 s, "
                            f"rate multiplier {mult:g} -> {new:g}", self.tag)
                        time.sleep(60)
                        continue
                    log(f"HTTP {last} on {url}; not retried", self.tag)
                    return last, None
                finally:
                    fcntl.flock(lk, fcntl.LOCK_UN)
        return last, None


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(path)


def pr_name(d) -> str:
    return f"PR{d:%d%m%y}.zip"


def sec_name(d) -> str:
    return f"sec_bhavdata_full_{d:%d%m%Y}.csv"


def member_date(name: str):
    """Date encoded in a PR-bundle member name: Pd050424.csv (ddmmyy) or pd01022026.csv (ddmmyyyy)."""
    import re
    from datetime import datetime as _dt
    m = re.search(r"(\d{8}|\d{6})", Path(name).name)
    if not m:
        return None
    g = m.group(1)
    try:
        return (_dt.strptime(g, "%d%m%Y") if len(g) == 8 else _dt.strptime(g, "%d%m%y")).date()
    except ValueError:
        return None


def bundle_inner_date(zpath: Path):
    """Date of the bundle's pd member (the zip name is not trusted: the archive mis-files some)."""
    import zipfile
    try:
        with zipfile.ZipFile(zpath) as zf:
            for n in zf.namelist():
                if Path(n).name.lower().startswith("pd") and n.lower().endswith(".csv"):
                    return member_date(n)
    except zipfile.BadZipFile:
        return None
    return None


def bundle_ok(zpath: Path) -> bool:
    """True when the bundle's pd member carries the date in the zip's own name."""
    from datetime import datetime as _dt
    try:
        zd = _dt.strptime(zpath.stem[2:], "%d%m%y").date()
    except ValueError:
        return False
    return bundle_inner_date(zpath) == zd

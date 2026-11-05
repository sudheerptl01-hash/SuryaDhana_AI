"""Snapshot data access for alpha_lab: read-only copy of the project DuckDB, vendored panel loader.

Everything the three strategies need, loaded once: adjusted survivorship-free panel (2010→),
NIFTY 50 and INDIAVIX series, results release times, per-symbol futures closes (2019-10→).
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import duckdb
import pandas as pd

LAB = Path(__file__).resolve().parents[1]
ROOT = LAB.parent
sys.path.insert(0, str(LAB))
import lib  # noqa: F401,E402  (aliases `shared` → vendored copies)
from lib.nse_panel import load_panel  # noqa: E402

PANEL_START = "2010-01-01"


def _shared_snapshot() -> Path | None:
    """Ops hook (Bloomberg F2.3/A7): reuse the shared 19:20 evening snapshot read-only
    instead of making a private 4.4GB copy. Env var wins (injected at job spawn by the
    controller, pre-verified fresh); else the pointer file if its snapshot is <24h old.
    Any problem → None → today's private-copy behaviour. Never raises."""
    try:
        import json as _json
        import os as _os
        import time as _time
        p = _os.getenv("SURYA_SNAPSHOT_PATH")
        if p:
            return Path(p) if Path(p).exists() else None
        sp = Path(_json.loads((ROOT / "data" / ".evening_snapshot.json").read_text())["path"])
        if sp.exists() and _time.time() - sp.stat().st_mtime < 24 * 3600:
            return sp
    except Exception:
        pass
    return None


def load(panel_start: str = PANEL_START) -> dict:
    """One self-cleaning snapshot read. Returns dict with panel, nifty, vix, releases, fo."""
    tmp = Path(tempfile.mkdtemp(prefix="alphalab_"))
    db = ROOT / "data" / "market.duckdb"
    shared = _shared_snapshot()
    if shared is not None:
        snap = shared                      # verified evening snapshot — no copy needed
    else:
        snap = tmp / "s.duckdb"
        shutil.copy2(db, snap)
        wal = Path(f"{db}.wal")
        if wal.exists():
            shutil.copy2(wal, f"{snap}.wal")
    con = duckdb.connect(str(snap), read_only=shared is not None)
    try:
        panel = load_panel(con, start=panel_start)
        q = lambda s, *a: con.execute(s, list(a)).df()  # noqa: E731
        nifty = q("SELECT date, close FROM market_index_daily WHERE symbol='NIFTY50' ORDER BY date")
        vix = q("SELECT date, close FROM market_index_daily WHERE symbol='INDIAVIX' ORDER BY date")
        releases = q("SELECT symbol, period_end, released_at FROM nse_results "
                     "WHERE released_at IS NOT NULL AND released_at >= TIMESTAMP '2010-03-01'")
        fo = q("SELECT date, symbol, kind, near_expiry, fut_close, fut_oi FROM nse_fo_daily")
    finally:
        con.close()
        shutil.rmtree(tmp, ignore_errors=True)
    out = {"panel": panel}
    for name, df in (("nifty", nifty), ("vix", vix)):
        out[name] = pd.Series(df["close"].to_numpy(float), index=pd.to_datetime(df["date"])).sort_index()
    releases["released_at"] = pd.to_datetime(releases["released_at"])
    fo["date"] = pd.to_datetime(fo["date"])
    out["releases"], out["fo"] = releases, fo
    return out

"""``index_drivers_daily`` (19:25 IST; retry 20:35; PLAN 1.2 jobs) and the one-off backfill from stored data (no fetch).

Daily: archive the constituent lists (2 conditional GETs), the top-10 file (1 GET, may not be there yet → the weights stay
``rebuilt`` + carried calibration and the 20:35 retry re-runs the day), then for each index: PIT weights (rebuilt, calibrated),
contributions, the fit row, the driver state for the 20- and 60-session windows. Backfill: the same from
``nse_bhavcopy`` / filings / ``index_ohlc_daily`` for every session in the range with the oldest archived list applied before
its date (the page says so). Never a restart; never a Yahoo call.
"""
from __future__ import annotations

import contextlib
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from data_health import db
from index_drivers import compute, ingest, weights
from index_drivers.schema import CASTS, COLUMNS, positions_meta
from shared.logging import get_logger

logger = get_logger(__name__)

JOBS: tuple[str, ...] = ("index_drivers_daily", "index_drivers_backfill")
STATE_LOOKBACK_DAYS = 130                      # calendar days of stored contributions needed for the 60-session window


def _upsert(store: Any, table: str, df: pd.DataFrame) -> int:
    return db.upsert(store, table, df, COLUMNS[table], CASTS[table]) if df is not None and not df.empty else 0


def compute_index(store: Any, index_name: str, days: list[date], *, financials_root: Path, now: datetime,
                  progress: Callable[[int, int], None] | None = None) -> dict[str, Any]:
    """Weights, contributions and fit for ``days`` (ascending) of one index from stored data; then the driver state."""
    if not days:
        return {"index": index_name, "days": 0}
    members_cache: dict[date | None, pd.DataFrame] = {}
    notes: set[str] = set()
    all_members: set[str] = set()
    per_day_members: dict[date, pd.DataFrame] = {}
    for d in days:
        m, list_date, note = weights.members_for(store, index_name, d)
        if m.empty:
            continue
        key = list_date
        members_cache.setdefault(key, m)
        per_day_members[d] = members_cache[key]
        all_members.update(m["symbol"].tolist())
        if "applied before" in note:
            notes.add(note)
    if not per_day_members:
        return {"index": index_name, "days": 0, "status": "no_members", "note": "no constituent list stored (run the daily job once to archive it)"}
    splits = weights.load_splits(store)
    rets = compute.load_returns(store, sorted(all_members), days[0], days[-1], splits)
    levels = compute.index_levels(store, index_name, days[0], days[-1])
    sh = weights.load_shareholding(store, sorted(all_members))
    shares = weights.SharesCache(financials_root, splits)
    lv = levels.set_index("date")["close"].sort_index()
    lv_src = levels.set_index("date")["source"]
    corrections, _ = weights.latest_calibration(store, index_name, days[0] - timedelta(days=1))
    written = {"weights": 0, "contributions": 0, "fit": 0}
    skipped: list[dict[str, Any]] = []
    for i, d in enumerate(days, 1):
        if progress:
            progress(i, len(days))
        m = per_day_members.get(d)
        if m is None or d not in lv.index:
            skipped.append({"date": d.isoformat(), "reason": "no index level" if m is not None else "no members"})
            continue
        prev_idx = lv.index[lv.index < d]
        if len(prev_idx) == 0:
            skipped.append({"date": d.isoformat(), "reason": "no previous index level"})
            continue
        prev_level, level, src = float(lv[prev_idx[-1]]), float(lv[d]), str(lv_src[d])
        day_rets = rets[rets["date"] == d]
        # NSE's prev_close is NOT adjusted on the ex-date while the PIT share count already is: divide by the ratio of a
        # split effective today so ffmc = shares × prev close stays the same capitalisation (the nse_bhavcopy.prev_close trap)
        split_today = {str(r.ticker): float(r.ratio) for r in splits.itertuples(index=False) if db.to_date(r.date) == d and r.ratio > 0}
        prev_close = {s: float(v) / split_today.get(s, 1.0) for s, v in zip(day_rets["symbol"], day_rets["prev_close"], strict=True)
                      if v is not None and v == v}
        rebuilt = weights.rebuild(index_name, d, m, prev_close, shares, sh, now=now)
        if rebuilt.empty:
            skipped.append({"date": d.isoformat(), "reason": "no weights (no filings / prices)"})
            continue
        official = ingest.official_top10(store, d) if index_name == ingest.TOP10_INDEX else {}
        if official:
            cal = weights.calibrate(rebuilt, official, now=now)
            corrections = {str(r.symbol): float(r.iwf_correction) for r in cal.itertuples(index=False) if r.iwf_correction is not None}
            method = "rebuilt_calibrated"
        elif corrections:
            cal = weights.carry_calibration(rebuilt, corrections, now=now)
            method = "rebuilt_calibrated"
        else:
            cal = pd.DataFrame(columns=COLUMNS["index_weights_daily"])
            method = "rebuilt"
        written["weights"] += _upsert(store, "index_weights_daily", pd.concat([rebuilt, cal], ignore_index=True))
        use = cal if not cal.empty else rebuilt
        contrib, fit = compute.contributions(index_name, d, use, day_rets, prev_level, level, src, method, len(m), now=now)
        written["contributions"] += _upsert(store, "index_contribution_daily", contrib)
        written["fit"] += _upsert(store, "index_contribution_fit", pd.DataFrame([fit]))
    states = refresh_driver_state(store, index_name, days[0], days[-1], now=now)
    with contextlib.suppress(Exception):
        store.checkpoint()
    return {"index": index_name, "days": len(days), "written": {**written, "driver_state": states}, "skipped": skipped[:20], "notes": sorted(notes)}


def refresh_driver_state(store: Any, index_name: str, start: date, end: date, *, now: datetime) -> int:
    """Recompute index_driver_state for [start, end] from the stored contributions (needs the trailing window before start)."""
    lo = start - timedelta(days=STATE_LOOKBACK_DAYS)
    contrib = db.query_df(store, """SELECT date, symbol, points, weight_pct, ret_pct FROM index_contribution_daily
                                    WHERE index_name = ? AND date >= ? AND date <= ? AND points IS NOT NULL""", [index_name, lo, end])
    if contrib.empty:
        return 0
    contrib["date"] = contrib["date"].map(db.to_date)
    rets = contrib[["date", "symbol", "ret_pct"]].rename(columns={"ret_pct": "ret"})
    rets["ret"] = rets["ret"] / 100.0
    levels = db.query_df(store, "SELECT date, index_level AS close FROM index_contribution_fit WHERE index_name = ? AND date >= ? AND date <= ?",
                         [index_name, lo, end])
    levels["date"] = levels["date"].map(db.to_date)
    states = compute.driver_states(contrib, rets, levels, None, index_name, now=now)
    if states.empty:
        return 0
    states = states[(states["date"] >= start) & (states["date"] <= end)]
    return _upsert(store, "index_driver_state", states)


def run_daily(store: Any, http: Any, *, day: date | None, indices: tuple[str, ...] = ingest.INDICES, cache_root: Path, financials_root: Path,
              now: datetime | None = None, fetch: bool = True) -> dict[str, Any]:
    now = now or db.utcnow()
    out: dict[str, Any] = {"job": "index_drivers_daily"}
    if day is None:
        v = db.scalar(store, "SELECT MAX(date) FROM nse_bhavcopy") if db.table_exists(store, "nse_bhavcopy") else None
        day = db.to_date(v) or now.date()
    out["date"] = day.isoformat()
    if fetch:
        out["constituents"] = {ix: ingest.ingest_constituents(store, http, ix, day, cache_root, now=now) for ix in indices if ix in ingest.CONSTITUENT_URLS}
        out["top10"] = ingest.ingest_top10(store, http, day, cache_root, now=now)
    out["indices"] = {ix: compute_index(store, ix, [day], financials_root=financials_root, now=now) for ix in indices}
    out["status"] = "ok" if all(v.get("days") for v in out["indices"].values()) else "degraded"
    out["tables"] = positions_meta(store)
    return out


def sessions(store: Any, start: date, end: date) -> list[date]:
    if not db.table_exists(store, "nse_bhavcopy"):
        return []
    df = db.query_df(store, "SELECT DISTINCT date FROM nse_bhavcopy WHERE date >= ? AND date <= ? ORDER BY date", [start, end])
    return [d for d in (db.to_date(v) for v in df["date"]) if d]


def run_backfill(store: Any, *, start: date, end: date, indices: tuple[str, ...] = ingest.INDICES, financials_root: Path, now: datetime | None = None,
                 progress: Callable[[int, int], None] | None = None, resume: bool = True) -> dict[str, Any]:
    now = now or db.utcnow()
    days = sessions(store, start, end)
    out: dict[str, Any] = {"job": "index_drivers_backfill", "from": start.isoformat(), "to": end.isoformat(), "sessions": len(days), "indices": {}}
    for ix in indices:
        todo = days
        if resume:
            have = db.query_df(store, "SELECT DISTINCT date FROM index_contribution_fit WHERE index_name = ? AND date >= ? AND date <= ?", [ix, start, end])
            done = {db.to_date(v) for v in have["date"]}
            todo = [d for d in days if d not in done]
        out["indices"][ix] = compute_index(store, ix, todo, financials_root=financials_root, now=now, progress=progress)
    out["status"] = "ok"
    out["tables"] = positions_meta(store)
    return out


def backfill_plan(store: Any) -> dict[str, Any]:
    first_bhav = db.to_date(db.scalar(store, "SELECT MIN(date) FROM nse_bhavcopy")) if db.table_exists(store, "nse_bhavcopy") else None
    have = positions_meta(store)
    lists = {ix: db.to_date(db.scalar(store, "SELECT MIN(date) FROM index_constituents_daily WHERE index_name = ?", [ix])) for ix in ingest.INDICES}
    return {"steps": [{"step": "index_drivers_backfill", "from": "2019-10-01", "to": "today", "indices": list(ingest.INDICES), "source": "stored data only",
                       "est_minutes": 15, "precondition": "one daily run archived the constituent lists (members as of that date applied before it)",
                       "constituent_lists_since": {k: (v.isoformat() if v else None) for k, v in lists.items()}, "bhavcopy_from": first_bhav.isoformat() if first_bhav else None,
                       "window": "outside 07:45–09:20 and 18:30–21:15 IST, never beside the 02:15 backup"}], "tables": have, "resumable": True}

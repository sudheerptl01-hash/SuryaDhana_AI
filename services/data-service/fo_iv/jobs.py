"""The ``fo_iv`` jobs behind ``POST /jobs/iv-eod`` / ``POST /jobs/iv-intraday`` (PLAN 1.1 jobs; the controller (B2) calls them
with ``?job=<id>``): ``iv_eod`` (the day's file → the three tables + the NSE context files + the event ledger + the NSE delta
cross-check), ``iv_weekly`` (Saturday rank / percentile recompute + catalog check), ``iv_backfill`` (resumable, from the cached
files only — one-off on O-T4), ``vix_backfill`` (the vixhistory API, one-off), ``iv_intraday`` (the pilot tick).

Fetch + compute only; nothing restarts anything; every HTTP request goes through the paced allowlisted client and is logged.
"""
from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from data_health import db, ingest_log

from fo_iv import events, intraday, iv_eod
from fo_iv import files as fo_files
from fo_iv.schema import CASTS, COLUMNS, positions_meta
from shared.logging import get_logger

logger = get_logger(__name__)

JOBS: tuple[str, ...] = ("iv_eod", "iv_weekly", "iv_backfill", "vix_backfill", "iv_intraday")
EOD_FILES: tuple[str, ...] = ("index_ohlc_daily", "nse_fo_volt", "nse_contract_delta", "nse_combined_oi")
DELTA_TOL = 0.05
LEGACY_START = date(2019, 10, 1)


def fo_file_for(fo_root: Path, day: date) -> Path | None:
    hits = fo_files.files(fo_root, day, day)
    return hits[0][1] if hits else None


def fetch_fo_file(store: Any, http: Any, fo_root: Path, day: date, *, now: datetime) -> Path | None:
    """The day's UDiFF file into the cache when the 20:30 pass has not stored it yet (one paced GET, logged)."""
    import nse_positions

    url = nse_positions.fo_urls(day)[0]
    f = ingest_log.fetch_logged(store, http, "nse_fo_bhavcopy", day, url, cache_root=fo_root.parent, cache_name=None, now=now)
    return f.cached_path if f.ok and f.cached_path else None


def delta_crosscheck(store: Any, day: date, *, tol: float = DELTA_TOL) -> dict[str, Any]:
    """|Δ_ours − Δ_nse| per surface strike against NSE's Contract_Delta (R-IV §2 row 8): counts + the worst offenders."""
    if not (db.table_exists(store, "nse_contract_delta") and db.table_exists(store, "iv_surface_daily")):
        return {"compared": 0}
    df = db.query_df(store, """SELECT s.symbol, s.expiry, s.strike, s.opt_type, s.delta AS ours, n.delta_factor AS nse
                               FROM iv_surface_daily s JOIN nse_contract_delta n
                                 ON n.date = s.date AND n.symbol = s.symbol AND n.expiry = s.expiry AND n.strike = s.strike AND n.opt_type = s.opt_type
                               WHERE s.date = ? AND s.delta IS NOT NULL AND n.delta_factor IS NOT NULL""", [day])
    if df.empty:
        return {"compared": 0}
    diff = (df["ours"] - df["nse"]).abs()
    bad = df[diff > tol].assign(diff=diff[diff > tol]).sort_values("diff", ascending=False).head(10)
    out = {"compared": len(df), "beyond_tol": int((diff > tol).sum()), "mean_abs": round(float(diff.mean()), 4), "tol": tol,
           "worst": db.records(bad, ("expiry",))}
    if out["beyond_tol"]:
        logger.info("fo_iv.delta_crosscheck", day=day.isoformat(), **{k: v for k, v in out.items() if k != "worst"})
    return out


def run_eod(store: Any, http: Any, *, day: date | None, fo_root: Path, cache_root: Path, now: datetime | None = None,
            surface_symbols: set[str] | None = None, fetch_files: bool = True, revalidate: bool = False) -> dict[str, Any]:
    import nse_positions

    now = now or db.utcnow()
    out: dict[str, Any] = {"job": "iv_eod"}
    if day is None:
        last = fo_files.files(fo_root)
        day = last[-1][0] if last else now.date()
    out["date"] = day.isoformat()
    iv_eod.seed_rate_curve(store, now=now)
    path = fo_file_for(fo_root, day)
    if path is None and fetch_files:
        path = fetch_fo_file(store, http, fo_root, day, now=now)
    if path is None:
        out["status"] = "not_yet"
        out["reason"] = f"no F&O file for {day} (NSE publishes ≈ 20:10; retry in the 22:45 pass)"
        return out
    if fetch_files:
        out["files"] = nse_positions.ingest_files(store, http, list(EOD_FILES), day, day, cache_root, revalidate=revalidate, now=now)["datasets"]
    out["iv"] = iv_eod.run_day(store, path, day, surface_symbols=surface_symbols, now=now)
    out["events"] = events.build_ledger(store, since=day - timedelta(days=4), until=day, now=now)
    out["delta_check"] = delta_crosscheck(store, day)
    with contextlib.suppress(Exception):
        store.checkpoint()
    out["status"] = "ok"
    out["tables"] = positions_meta(store)
    return out


def load_index_history_csv(store: Any, csv_path: Path, *, now: datetime | None = None) -> int:
    """Closes from data/nse_archive/derived/index_valuation_history.csv into index_ohlc_daily (close only, source
    index_valuation_history) for the days the daily file was never stored — the close-to-close RV and the drivers' index level
    need a close back to 2012. Never overwrites a nse_daily_file row."""
    if not csv_path.exists():
        return 0
    now = now or db.utcnow()
    df = pd.read_csv(csv_path, usecols=["date", "index", "close"]).dropna(subset=["close"])
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df.rename(columns={"index": "symbol"})
    df["symbol"] = df["symbol"].astype(str).str.upper().str.strip()
    have = db.query_df(store, "SELECT symbol, date FROM index_ohlc_daily WHERE source = 'nse_daily_file'")
    had = {(str(r.symbol), db.to_date(r.date)) for r in have.itertuples(index=False)}
    keep = df[[(s, d) not in had for s, d in zip(df["symbol"], df["date"], strict=True)]].copy()
    keep["open"], keep["high"], keep["low"] = None, None, None
    keep["source"], keep["first_seen_at"] = "index_valuation_history", now
    return db.upsert(store, "index_ohlc_daily", keep, COLUMNS["index_ohlc_daily"], CASTS["index_ohlc_daily"])


def run_backfill(store: Any, *, start: date, end: date, fo_root: Path, surface_symbols: set[str] | None = None, now: datetime | None = None,
                 progress: Callable[[int, int], None] | None = None, resume: bool = True, index_history_csv: Path | None = None,
                 max_files: int | None = None) -> dict[str, Any]:
    """Resumable by date from the cached files (never a fetch): days already in iv_summary_daily are skipped when ``resume``."""
    now = now or db.utcnow()
    iv_eod.seed_rate_curve(store, now=now)
    if index_history_csv is not None:
        load_index_history_csv(store, index_history_csv, now=now)
    todo = fo_files.files(fo_root, start, end)
    if resume:
        have = db.query_df(store, "SELECT DISTINCT date FROM iv_summary_daily WHERE date >= ? AND date <= ?", [start, end])
        done = {db.to_date(v) for v in have["date"]}
        todo = [(d, p) for d, p in todo if d not in done]
    if max_files:
        todo = todo[:max_files]
    if not todo:
        return {"job": "iv_backfill", "status": "ok", "days": 0, "note": "nothing to do"}
    symbols = sorted({*iv_eod.INDEX_SYMBOLS})
    rv = iv_eod.RvCache()
    # symbols for the RV cache: every option underlying seen in the first file of the range (new names join on the next run)
    first = fo_files.load(todo[0][1])
    symbols = sorted(set(symbols) | set(first.loc[first["instrument"] == "OPT", "symbol"].unique()))
    rv.load(store, symbols, todo[0][0], todo[-1][0])
    history = iv_eod.IvHistory(store, todo[0][0])
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for i, (d, p) in enumerate(todo, 1):
        try:
            results.append(iv_eod.run_day(store, p, d, surface_symbols=surface_symbols, now=now, history=history, rv=rv))
        except Exception as exc:  # noqa: BLE001 — one bad file never stops the backfill
            errors.append({"date": d.isoformat(), "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
        if progress:
            progress(i, len(todo))
        if i % 50 == 0:
            with contextlib.suppress(Exception):
                store.checkpoint()
    ev = events.build_ledger(store, since=todo[0][0], until=todo[-1][0], now=now)
    with contextlib.suppress(Exception):
        store.checkpoint()
    return {"job": "iv_backfill", "status": "ok" if not errors else "degraded", "days": len(results), "from": todo[0][0].isoformat(),
            "to": todo[-1][0].isoformat(), "seconds": round(sum(r["seconds"] for r in results), 1),
            "rows": {k: sum(int(r[k]) for r in results) for k in ("expiry_rows", "surface_rows", "summary_rows")}, "events": ev,
            "errors": errors[:20], "tables": positions_meta(store)}


def run_weekly(store: Any, *, now: datetime | None = None) -> dict[str, Any]:
    from data_health import catalog

    now = now or db.utcnow()
    n = iv_eod.recompute_ranks(store)
    ev = events.build_ledger(store, since=now.date() - timedelta(days=30), until=now.date(), now=now)
    seeded = catalog.seed(store)
    with contextlib.suppress(Exception):
        store.checkpoint()
    return {"job": "iv_weekly", "status": "ok", "ranks_recomputed": n, "events": ev, "catalog_rows": seeded, "tables": positions_meta(store)}


def run_vix_backfill(store: Any, http: Any, *, start: date, end: date, now: datetime | None = None) -> dict[str, Any]:
    import nse_positions

    res = nse_positions.ingest_vix_history(store, http, start, end, now=now)
    with contextlib.suppress(Exception):
        store.checkpoint()
    return {"job": "vix_backfill", "status": "ok" if not res["errors"] else "degraded", **res}


def run_intraday(store: Any, breeze: Any, budget: Any, *, parquet_root: Path, watchlist: Iterable[str] = (), now: datetime | None = None,
                 force_window: bool = False, is_live: Callable[[], bool] | None = None) -> dict[str, Any]:
    res = intraday.snapshot(store, breeze, budget, now=now, watchlist=watchlist, parquet_root=parquet_root, force_window=force_window, is_live=is_live)
    return {"job": "iv_intraday", **res}


def backfill_plan(fo_root: Path, store: Any | None = None) -> dict[str, Any]:
    """What a backfill would do (the gold ``/db/gold/backfill-plan`` idea): files per era, seconds at the measured 3 s / file."""
    all_files = fo_files.files(fo_root)
    udiff = [(d, p) for d, p in all_files if not fo_files.is_legacy(p)]
    legacy = [(d, p) for d, p in all_files if fo_files.is_legacy(p)]
    done: set[date] = set()
    if store is not None and db.table_exists(store, "iv_summary_daily"):
        done = {d for d in (db.to_date(v) for v in db.query_df(store, "SELECT DISTINCT date FROM iv_summary_daily")["date"]) if d is not None}
    steps = []
    for name, fs, owner in (("udiff", udiff, "O-T4"), ("legacy", legacy, "O-T4")):
        todo = [d for d, _ in fs if d not in done]
        steps.append({"step": name, "files": len(fs), "remaining": len(todo), "from": fs[0][0].isoformat() if fs else None,
                      "to": fs[-1][0].isoformat() if fs else None, "est_minutes": round(len(todo) * 3 / 60, 1), "owner_decision": owner,
                      "window": "outside 07:45–09:20 and 18:30–21:15 IST, never beside the 02:15 backup (a Sunday 10:00 start)"})
    steps.append({"step": "archive_2001_2019", "files": "≈ 4,500", "remaining": "all", "est_minutes": 150 + 210, "owner_decision": "O-T4b",
                  "note": "paced download 1 file / 2 s (3.6 GB) then compute; not started by this service"})
    return {"steps": steps, "resumable": True, "source": "cached files only (no fetch)"}

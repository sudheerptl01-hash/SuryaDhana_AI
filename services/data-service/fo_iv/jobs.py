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

import numpy as np
import pandas as pd
from data_health import db, ingest_log

from fo_iv import events, intraday, iv_eod
from fo_iv import files as fo_files
from fo_iv.schema import CASTS, COLUMNS, positions_meta
from shared.logging import get_logger

logger = get_logger(__name__)

JOBS: tuple[str, ...] = ("iv_eod", "iv_weekly", "iv_backfill", "vix_backfill", "iv_intraday", "iv_repair")
EOD_FILES: tuple[str, ...] = ("index_ohlc_daily", "nse_fo_volt", "nse_contract_delta", "nse_combined_oi")
# fetched by iv_eod itself after EOD_FILES (the controller's pinned NSE_IV_FILES list stays as it is): the MWPL zip (M43: the
# deleq file alone carries no MWPL, so % MWPL and BAN were empty for 224 of 224) and NCL's SPAN risk-parameter file (M44;
# stored under data/nse_archive/span/ for POST /api/options/margin's file tier). Both are published before 19:30 IST.
EOD_EXTRA_FILES: tuple[str, ...] = ("nse_combined_oi_zip", "nse_span_zip")
# Round 2 (checker deploy note): the SPAN zip is ≈ 10 MB, heavier than the "light" class allowed inside the 07:45–09:20 IST
# freeze window (ICICI login + pre-open jobs), where the 08:35 morning sweep can re-run iv_eod. It is deferred there; the
# margin route then reads the newest stored SPAN file (it names its date). The MWPL zip (≈ 22 KB) stays.
HEAVY_EXTRA_FILES: frozenset[str] = frozenset({"nse_span_zip"})
MORNING_FREEZE_IST: tuple[tuple[int, int], tuple[int, int]] = ((7, 45), (9, 20))


def extra_files_for(now_utc: datetime) -> tuple[list[str], list[str]]:
    """(the extra files iv_eod fetches at ``now_utc``, the ones it defers): the heavy ones wait outside the morning freeze."""
    ist = now_utc + timedelta(hours=5, minutes=30)
    (h0, m0), (h1, m1) = MORNING_FREEZE_IST
    in_freeze = (h0, m0) <= (ist.hour, ist.minute) < (h1, m1)
    fetch = [f for f in EOD_EXTRA_FILES if not (in_freeze and f in HEAVY_EXTRA_FILES)]
    return fetch, [f for f in EOD_EXTRA_FILES if f not in fetch]
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
        extra, deferred = extra_files_for(now)
        out["files_extra"] = nse_positions.ingest_files(store, http, extra, day, day, cache_root, revalidate=revalidate,
                                                        now=now)["datasets"]
        if deferred:
            out["files_deferred"] = {"datasets": deferred, "reason": "heavy file inside the 07:45–09:20 IST freeze window"}
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


REPAIR_COLS = ("rv20_cc", "rv20_parkinson", "rv20_yz", "iv_minus_rv20", "iv30_cm", "expected_move_1d_pct", "quality_flags", "first_seen_at")


def _flags_without(flags: Any, drop: set[str]) -> list[str]:
    if not isinstance(flags, str) or not flags:
        return []
    return [f for f in flags.split(",") if f and f not in drop]


def run_repair(store: Any, *, start: date | None = None, end: date | None = None, symbols: list[str] | None = None,
               now: datetime | None = None) -> dict[str, Any]:
    """``iv_repair`` (M06 / M43 / m052; POST /jobs/iv-eod?job=iv_repair[&backfill_from=YYYY-MM-DD], the PM runs it once after
    the deploy, outside the freeze windows; ≈ 1–3 min, cached data only, no fetch). Over the stored ``iv_summary_daily`` rows
    in [start, end] (default: all):

    * RV20 close-to-close / Parkinson / Yang-Zhang recomputed from ``index_ohlc_daily`` (indices; OHLC stored 2019-10 →) and
      ``nse_bhavcopy`` (stocks) with the range-outlier rule — the 5 Nov backfill had RV for 107 of 224 names (the cache was
      seeded from the 2019 file) and index YZ / Parkinson on 1 of 1,761 rows (it ran before the index OHLC history);
    * IV30 filled flat from the one expiry nearest 30 d inside 10–60 d where no pair brackets 30 d (flag ``cm30_flat``);
    * IV − RV20 (close-to-close) recomputed on the result with enrich's base (IV30, else the ~1-month ATM IV), and the 1-day
      expected move with summarise's base (IV30, else the NEAR ATM IV) — one rule for repaired history and fresh EOD rows
      (round 2: the repair used the ~1-month IV here and blanked 10,558 near-only rows that iv_eod fills);
    * rank / percentile recomputed over the whole history (``recompute_ranks``), so the 4 Nov rows get theirs.

    Rows are updated in place (the derived-table rule, PLAN §0.3 as amended 5 Nov): ``first_seen_at`` = this run."""
    now = now or db.utcnow()
    where: list[str] = ["1 = 1"]
    params: list[Any] = []
    if start:
        where.append("date >= ?")
        params.append(start)
    if end:
        where.append("date <= ?")
        params.append(end)
    if symbols:
        where.append("list_contains(?, symbol)")
        params.append([s.upper() for s in symbols])
    w = " AND ".join(where)
    summ = db.query_df(store, f"""SELECT date, symbol, iv30_cm, monthly_atm_iv, near_atm_iv, quality_flags FROM iv_summary_daily
                                 WHERE {w} ORDER BY symbol, date""", params)
    if summ.empty:
        return {"job": "iv_repair", "status": "ok", "rows": 0, "note": "no stored summary rows in range"}
    summ["date"] = summ["date"].map(db.to_date)
    lo, hi = min(summ["date"]), max(summ["date"])
    exp = db.query_df(store, f"""SELECT date, symbol, dte, atm_iv FROM iv_expiry_daily
                                WHERE {w} AND atm_iv IS NOT NULL AND dte BETWEEN ? AND ?""", [*params, *iv_eod.CM30_FLAT_DTE])
    flat: dict[tuple[str, date], float] = {}
    if not exp.empty:
        exp["date"] = exp["date"].map(db.to_date)
        exp["gap"] = (exp["dte"] - 30).abs()
        exp = exp.sort_values(["symbol", "date", "gap", "dte"], ascending=[True, True, True, False]).drop_duplicates(["symbol", "date"])
        flat = {(str(r.symbol), r.date): round(float(r.atm_iv), 4) for r in exp.itertuples(index=False)}
    rv = iv_eod.RvCache()
    syms = sorted(summ["symbol"].astype(str).unique())
    rv.load(store, syms, lo, hi)
    frames = []
    for sym in syms:
        rv.get(sym, lo)                                   # loads a late F&O entrant on first use
        f = rv.rows.get(sym)
        if f is not None and not f.empty:
            frames.append(f.assign(symbol=sym))
    rv_all = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["symbol", "date", "rv20_cc", "rv20_parkinson",
                                                                                       "rv20_yz", "range_outlier"])
    rv_all = rv_all.drop_duplicates(["symbol", "date"], keep="last")
    m = summ.merge(rv_all, on=["symbol", "date"], how="left")
    out_rows: list[dict[str, Any]] = []
    counts = {"rv_filled": 0, "yz_filled": 0, "iv30_flat": 0, "range_outlier_rows": 0}
    drop = {"no_cm30", "cm30_flat", "rv_range_outlier", "rv_input_missing"}

    def _v(x: Any) -> float | None:
        return None if x is None or pd.isna(x) else round(float(x), 4)

    for r in m.itertuples(index=False):
        sym, d = str(r.symbol), r.date
        flags = _flags_without(r.quality_flags, drop)
        was_flat = "cm30_flat" in str(r.quality_flags or "").split(",")
        iv30 = None if was_flat else _v(r.iv30_cm)
        if iv30 is None:
            iv30 = flat.get((sym, d))
            flags.append("cm30_flat" if iv30 is not None else "no_cm30")
            counts["iv30_flat"] += int(iv30 is not None)
        if isinstance(r.range_outlier, (bool, np.bool_)) and bool(r.range_outlier):
            flags.append("rv_range_outlier")
            counts["range_outlier_rows"] += 1
        cc, park, yz = _v(r.rv20_cc), _v(r.rv20_parkinson), _v(r.rv20_yz)
        base = iv30 if iv30 is not None else _v(r.monthly_atm_iv)          # enrich's IV − RV base
        em_base = iv30 if iv30 is not None else _v(r.near_atm_iv)          # summarise's expected-move base
        counts["rv_filled"] += int(cc is not None)
        counts["yz_filled"] += int(yz is not None)
        out_rows.append({"symbol": sym, "date": d, "rv20_cc": cc, "rv20_parkinson": park, "rv20_yz": yz,
                         "iv_minus_rv20": round(base - cc, 4) if (base is not None and cc is not None) else None, "iv30_cm": iv30,
                         "expected_move_1d_pct": round(em_base / (252.0 ** 0.5), 4) if em_base is not None else None,
                         "quality_flags": ",".join(dict.fromkeys(flags)) or None, "first_seen_at": now})
    up = pd.DataFrame(out_rows)
    sets = ", ".join(f"{c} = u.{c}" for c in REPAIR_COLS)
    for i in range(0, len(up), db.BATCH_ROWS):
        chunk = up.iloc[i:i + db.BATCH_ROWS]
        store.write(f"""UPDATE iv_summary_daily SET {sets} FROM _b1_repair u
                        WHERE iv_summary_daily.symbol = u.symbol AND iv_summary_daily.date = u.date::DATE""", frames={"_b1_repair": chunk})
    ranks = iv_eod.recompute_ranks(store, symbols=[s.upper() for s in symbols] if symbols else None)
    with contextlib.suppress(Exception):
        store.checkpoint()
    return {"job": "iv_repair", "status": "ok", "rows": len(up), "from": lo.isoformat(), "to": hi.isoformat(), **counts,
            "ranks_recomputed": ranks, "note": "RV (cc / Parkinson / YZ, range outliers out), IV30 flat fill, IV − RV20 (cc), ranks"}


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

"""Build the inputs of the Terminal v2 studies in a SCRATCH DuckDB with the production code (PLAN §0.3 amendment: a
past vintage is recomputed from the archived source files).

    --fo       one pass over the cached NSE F&O bhavcopies (`data/nse_archive/fo/<year>/`, read-only) for NIFTY and
               BANKNIFTY: production's `fo_iv.files.load` + `fo_iv.iv_eod.compute_day` → `iv_summary_daily`,
               `iv_expiry_daily`, `iv_surface_daily` (production table names and columns), the 252-session rank and
               percentile by `fo_iv.iv_eod.rank_and_percentile`; plus the study-only tables `study_fo_contracts` (every
               NIFTY / BANKNIFTY contract row with open / high / low / close / settle / volume / OI) and
               `study_index_close` (NSE's index closes from `index_valuation_history.csv`, then the UDiFF `UndrlygPric`).
    --drivers  a READ-ONLY extract of an evening snapshot (`nse_bhavcopy` for today's NIFTY 50 members, `splits`,
               `nse_shareholding`) + NSE's NIFTY 50 closes (`index_ohlc_daily`, source `valuation_history`) + the 4 Nov
               2026 constituent list, then production's `index_drivers.jobs.run_backfill` (NIFTY 50).

Resumable (dates already present are skipped); never writes under `data/` (refuses an --out there); no network.
Run with `nice` beside the live stack. Exit 0 on success, 3 when a source is missing.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from terminal_studies import common as C

C.ensure_data_service_path()

SYMBOLS: tuple[str, ...] = ("NIFTY", "BANKNIFTY")
R_CONST = 0.065                                   # production's seeded constant (O-T5 default)

STUDY_DDL = """
CREATE TABLE IF NOT EXISTS study_fo_contracts (date DATE NOT NULL, symbol VARCHAR NOT NULL, instrument VARCHAR NOT NULL, expiry DATE NOT NULL,
  strike DOUBLE, opt_type VARCHAR, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, settle DOUBLE, volume DOUBLE, oi DOUBLE,
  underlying DOUBLE, source_file VARCHAR);
CREATE TABLE IF NOT EXISTS study_index_close (symbol VARCHAR NOT NULL, date DATE NOT NULL, close DOUBLE NOT NULL, source VARCHAR NOT NULL,
  PRIMARY KEY (symbol, date));
CREATE TABLE IF NOT EXISTS study_build_log (step VARCHAR, day DATE, seconds DOUBLE, note VARCHAR, at TIMESTAMP);
"""


def _refuse_data_dir(out: Path) -> None:
    data_dir = (C.ROOT / "data").resolve()
    try:
        out.expanduser().resolve().relative_to(data_dir)
    except ValueError:
        return
    raise SystemExit(f"refusing to write under {data_dir}: pass a scratch path (default {C.DEFAULT_INPUTS})")


def open_store(out: Path) -> Any:
    from storage.duckdb_store import DuckDBStore

    out.parent.mkdir(parents=True, exist_ok=True)
    store = DuckDBStore(str(out))
    with store.writer() as con:
        for stmt in STUDY_DDL.split(";"):
            if stmt.strip():
                con.execute(stmt)
    return store


# ── F&O files ─────────────────────────────────────────────────────────────────────────────────────────────────────

_UDIFF_HL = {"TckrSymb": "symbol", "FinInstrmTp": "tp", "XpryDt": "expiry", "StrkPric": "strike", "OptnTp": "opt_type",
             "OpnPric": "open", "HghPric": "high", "LwPric": "low"}
_LEGACY_HL = {"SYMBOL": "symbol", "INSTRUMENT": "tp", "EXPIRY_DT": "expiry", "STRIKE_PR": "strike", "OPTION_TYP": "opt_type",
              "OPEN": "open", "HIGH": "high", "LOW": "low"}


def ohlc_frame(blob: bytes, legacy: bool, symbols: tuple[str, ...] = SYMBOLS) -> pd.DataFrame:
    """open / high / low of every contract of `symbols` from the raw file (the production loader keeps close only)."""
    from fo_iv import files as fo_files

    cols = _LEGACY_HL if legacy else _UDIFF_HL
    raw = pd.read_csv(io.BytesIO(fo_files._unzip_first(blob)), dtype=str, usecols=lambda c: c.strip() in cols)
    raw.columns = [c.strip() for c in raw.columns]
    raw = raw.rename(columns=cols)
    raw["symbol"] = raw["symbol"].str.strip()
    raw = raw[raw["symbol"].isin(symbols)].copy()
    tp = raw["tp"].str.strip()
    raw["instrument"] = np.where(tp.isin(["IDF", "STF", "FUTIDX", "FUTSTK"]), "FUT", "OPT")
    fmt = "%d-%b-%Y" if legacy else None
    raw["expiry"] = pd.to_datetime(raw["expiry"].str.strip(), format=fmt, errors="coerce").dt.date
    for c in ("strike", "open", "high", "low"):
        raw[c] = fo_files._num(raw[c])
    raw["opt_type"] = raw["opt_type"].str.strip().where(raw["instrument"] == "OPT")
    raw.loc[raw["instrument"] == "FUT", "strike"] = np.nan
    return raw[["symbol", "instrument", "expiry", "strike", "opt_type", "open", "high", "low"]]


def contracts_with_ohlc(contracts: pd.DataFrame, hl: pd.DataFrame) -> pd.DataFrame:
    c = contracts.copy()
    c.loc[c["instrument"] == "FUT", "strike"] = np.nan
    key = ["symbol", "instrument", "expiry", "strike", "opt_type"]
    hl = hl.drop_duplicates(key)
    c["_k"] = c["strike"].fillna(-1.0)
    hl = hl.assign(_k=hl["strike"].fillna(-1.0)).drop(columns=["strike"])
    out = c.merge(hl, on=["symbol", "instrument", "expiry", "_k", "opt_type"], how="left").drop(columns=["_k"])
    return out


def _days_present(store: Any, table: str) -> set[date]:
    df = store.read(f"SELECT DISTINCT date FROM {table}")
    return {pd.Timestamp(d).date() for d in df["date"]} if not df.empty else set()


def build_fo(store: Any, *, start: date | None, end: date | None, limit: int | None, log_every: int = 50) -> dict[str, Any]:
    from data_health import db
    from fo_iv import files as fo_files
    from fo_iv import iv_eod
    from fo_iv.legacy_parser import parse_legacy
    from fo_iv.schema import CASTS, COLUMNS

    if not C.FO_ROOT.is_dir():
        print(C.status_line("build_inputs", "data not yet ingested", f"cached F&O files under {C.FO_ROOT}"))
        sys.exit(C.EXIT_NOT_INGESTED)
    todo = fo_files.files(C.FO_ROOT, start, end)
    have = _days_present(store, "study_fo_contracts")
    todo = [(d, p) for d, p in todo if d not in have]
    if limit:
        todo = todo[:limit]
    now = db.utcnow()
    t0 = time.time()
    n_done = 0
    keep_cols = ["date", "symbol", "instrument", "expiry", "strike", "opt_type", "open", "high", "low", "close", "settle", "volume", "oi",
                 "underlying", "source_file"]
    for day, path in todo:
        ts = time.time()
        blob = path.read_bytes()
        legacy = fo_files.is_legacy(path)
        contracts = parse_legacy(blob, path.name) if legacy else fo_files.parse_udiff(blob, path.name)
        sub = contracts[contracts["symbol"].isin(SYMBOLS)].reset_index(drop=True)
        if sub.empty:
            continue
        res = iv_eod.compute_day(sub, day, R_CONST, surface_symbols=set(SYMBOLS), symbols=set(SYMBOLS), now=now,
                                 source_file=path.name, legacy=legacy)
        for table, frame in (("iv_expiry_daily", res.expiry), ("iv_surface_daily", res.surface), ("iv_summary_daily", res.summary)):
            if frame is not None and not frame.empty:
                db.upsert(store, table, frame, COLUMNS[table], CASTS[table])
        rows = contracts_with_ohlc(sub, ohlc_frame(blob, legacy))
        rows.insert(0, "date", day)
        store.write("INSERT INTO study_fo_contracts BY NAME SELECT * FROM f", frames={"f": rows[keep_cols]})
        store.write("INSERT INTO study_build_log VALUES ('fo', ?, ?, ?, ?)", [day, round(time.time() - ts, 3), path.name, now])
        n_done += 1
        if n_done % log_every == 0:
            el = time.time() - t0
            print(f"[fo] {n_done}/{len(todo)} {day} {el:.0f}s elapsed, ~{el / n_done * (len(todo) - n_done) / 60:.1f} min left", flush=True)
    ranks = fill_rank_percentile(store)
    closes = build_index_close(store)
    return {"fo_days_added": n_done, "fo_seconds": round(time.time() - t0, 1), "rank_rows": ranks, "index_close_rows": closes}


def fill_rank_percentile(store: Any) -> int:
    """`iv_rank_252` / `iv_pctile_252` per symbol in date order, production's rule (iv30_cm, else monthly_atm_iv)."""
    from fo_iv import iv_eod

    df = store.read("SELECT date, symbol, iv30_cm, monthly_atm_iv FROM iv_summary_daily ORDER BY symbol, date")
    if df.empty:
        return 0
    out = []
    for sym, g in df.groupby("symbol", sort=True):
        hist: list[float] = []
        for r in g.itertuples(index=False):
            base = r.iv30_cm if r.iv30_cm is not None and not pd.isna(r.iv30_cm) else r.monthly_atm_iv
            base = None if base is None or pd.isna(base) else float(base)
            rank, pct = iv_eod.rank_and_percentile(hist[-iv_eod.RANK_WINDOW:], base)
            out.append({"date": r.date, "symbol": sym, "iv_rank_252": rank, "iv_pctile_252": pct})
            if base is not None:
                hist.append(base)
    f = pd.DataFrame(out)
    store.write("""UPDATE iv_summary_daily SET iv_rank_252 = f.iv_rank_252, iv_pctile_252 = f.iv_pctile_252
                   FROM f WHERE iv_summary_daily.date = f.date AND iv_summary_daily.symbol = f.symbol""", frames={"f": f})
    return len(f)


def build_index_close(store: Any) -> int:
    """NSE index closes: the valuation-history CSV (ind_close_all closes), then the UDiFF `UndrlygPric` after its end."""
    rows = []
    if C.INDEX_CLOSE_CSV.exists():
        v = pd.read_csv(C.INDEX_CLOSE_CSV, usecols=["date", "index", "close"])
        for sym, name in C.INDEX_NAME.items():
            s = v[v["index"] == name].dropna(subset=["close"])
            rows.append(pd.DataFrame({"symbol": sym, "date": pd.to_datetime(s["date"]).dt.date, "close": s["close"].astype(float),
                                      "source": "nse_ind_close_all_csv"}))
    base = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["symbol", "date", "close", "source"])
    und = store.read("""SELECT symbol, date, median(underlying) AS close FROM study_fo_contracts
                        WHERE instrument = 'OPT' AND underlying > 0 GROUP BY 1, 2""")
    if not und.empty:
        und["date"] = pd.to_datetime(und["date"]).dt.date
        und["source"] = "udiff_underlying"
        have = set(zip(base["symbol"], base["date"], strict=True))
        und = und[[(s, d) not in have for s, d in zip(und["symbol"], und["date"], strict=True)]]
        base = pd.concat([base, und[["symbol", "date", "close", "source"]]], ignore_index=True)
    if base.empty:
        return 0
    store.write("INSERT OR REPLACE INTO study_index_close BY NAME SELECT * FROM f", frames={"f": base})
    return len(base)


# ── drivers ───────────────────────────────────────────────────────────────────────────────────────────────────────

def nifty50_members() -> pd.DataFrame:
    m = pd.read_csv(C.NIFTY50_LIST)
    m.columns = [c.strip() for c in m.columns]
    m = m[m["Series"].astype(str).str.strip() == "EQ"]
    return pd.DataFrame({"symbol": m["Symbol"].astype(str).str.strip(), "industry": m["Industry"].astype(str).str.strip(),
                         "isin": m["ISIN Code"].astype(str).str.strip(), "company": m["Company Name"].astype(str).str.strip()})


def _copy_by_name(store: Any, table: str, df: pd.DataFrame) -> int:
    cols = store.read(f"SELECT * FROM {table} LIMIT 0").columns
    keep = [c for c in df.columns if c in set(cols)]
    if df.empty or not keep:
        return 0
    store.write(f"INSERT OR REPLACE INTO {table} BY NAME SELECT {', '.join(keep)} FROM f", frames={"f": df[keep]})
    return len(df)


def build_drivers(store: Any, snapshot: Path, *, start: date, end: date | None) -> dict[str, Any]:
    import duckdb
    from data_health import db
    from index_drivers import jobs as drv_jobs

    if not snapshot.exists():
        print(C.status_line("build_inputs", "data not yet ingested", f"evening snapshot {snapshot}"))
        sys.exit(C.EXIT_NOT_INGESTED)
    if C.is_live_db(snapshot):
        raise SystemExit("refusing the live data/market.duckdb: pass an evening snapshot (a read-only copy)")
    members = nifty50_members()
    syms = members["symbol"].tolist()
    now = db.utcnow()
    src = duckdb.connect(str(snapshot), read_only=True)
    try:
        lo = start - timedelta(days=40)
        bhav = src.execute("SELECT * FROM nse_bhavcopy WHERE date >= ? AND list_contains(?, symbol)", [lo, syms]).df()
        splits = src.execute("SELECT * FROM splits").df()
        sh = src.execute("SELECT * FROM nse_shareholding WHERE list_contains(?, symbol)", [syms]).df()
        row = src.execute("SELECT MAX(date) FROM nse_bhavcopy").fetchone()
        snap_end = row[0] if row else None
    finally:
        src.close()
    out: dict[str, Any] = {"snapshot": str(snapshot), "members": len(syms), "bhav_rows": _copy_by_name(store, "nse_bhavcopy", bhav),
                           "split_rows": _copy_by_name(store, "splits", splits), "shareholding_rows": _copy_by_name(store, "nse_shareholding", sh)}
    v = pd.read_csv(C.INDEX_CLOSE_CSV, usecols=["date", "index", "close"])
    v = v[v["index"] == "NIFTY 50"].dropna(subset=["close"])
    lv = pd.DataFrame({"symbol": "NIFTY 50", "date": pd.to_datetime(v["date"]).dt.date, "open": np.nan, "high": np.nan, "low": np.nan,
                       "close": v["close"].astype(float), "source": "valuation_history", "first_seen_at": now})
    out["index_level_rows"] = _copy_by_name(store, "index_ohlc_daily", lv)
    cons = members.assign(index_name="NIFTY 50", date=date(2026, 11, 4), source="niftyindices_list_2026-11-04", first_seen_at=now)
    out["constituent_rows"] = _copy_by_name(store, "index_constituents_daily", cons)
    if end is None and snap_end is None:
        raise SystemExit(f"{snapshot}: nse_bhavcopy is empty")
    stop = end or pd.Timestamp(snap_end).date()
    t0 = time.time()

    def progress(i: int, n: int) -> None:
        if i % 100 == 0 or i == n:
            print(f"[drivers] {i}/{n} {time.time() - t0:.0f}s", flush=True)

    res = drv_jobs.run_backfill(store, start=start, end=stop, indices=("NIFTY 50",), financials_root=C.FINANCIALS_ROOT, now=now,
                                progress=progress, resume=True)
    out["backfill"] = {k: v for k, v in res.items() if k != "tables"}
    out["drivers_seconds"] = round(time.time() - t0, 1)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=C.DEFAULT_INPUTS)
    ap.add_argument("--fo", action="store_true", help="recompute the IV tables + study inputs from the cached F&O files")
    ap.add_argument("--drivers", action="store_true", help="rebuild the drivers tables from a read-only snapshot extract")
    ap.add_argument("--snapshot", type=Path, default=C.ROOT / "data" / "snapshots" / "evening" / "evening-20261030-1920.duckdb")
    ap.add_argument("--start", type=date.fromisoformat, default=None)
    ap.add_argument("--end", type=date.fromisoformat, default=None)
    ap.add_argument("--limit", type=int, default=None, help="at most N new F&O files (smoke runs)")
    a = ap.parse_args(argv)
    if not (a.fo or a.drivers):
        ap.error("pass --fo and/or --drivers")
    _refuse_data_dir(a.out)
    store = open_store(a.out)
    summary: dict[str, Any] = {"out": str(a.out), "started": datetime.now().isoformat(timespec="seconds")}  # noqa: DTZ005
    try:
        if a.fo:
            summary["fo"] = build_fo(store, start=a.start, end=a.end, limit=a.limit)
        if a.drivers:
            summary["drivers"] = build_drivers(store, a.snapshot, start=a.start or date(2019, 10, 1), end=a.end)
        store.write("CHECKPOINT")
    finally:
        store.close()
    print(json.dumps(C._clean(summary), default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

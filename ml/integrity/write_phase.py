#!/usr/bin/env python3
"""The single read-write window of P1 on nse_market.duckdb (ml/IMPROVEMENT_PLAN.md section 3).

--dry-run  no DuckDB file is opened: an in-memory DuckDB gets the EQ/BE rows of the
           parquet export with the P1 session fixes applied, and build_features runs on
           it with the corporate-actions feed.  Times the step and writes
           ml/data_ext/staging/equity_features_dryrun.parquet for the post-write check.
--write    1. create ml/results/improve/LOCK_duckdb_write (start time, purpose);
           2. copy the store to the scratch backup path given by --backup (rollback);
           3. open read-write; delete the mis-dated session dates, upsert the verified
              sessions with DuckDBStore.upsert (the run_ingest duplicate-day guard is
              bypassed only for these rows, each verified by its own DATE1 column);
           4. CREATE OR REPLACE corporate_actions, etf_list, equity_master, special_sessions;
           5. build_features(con, ca_csv=ml/data_ext/corporate_actions_feed.csv);
           6. verify row counts, (date, ticker) uniqueness, NESTLEIND continuity, the
              continuity scan (I1) and the dry-run equality; CHECKPOINT; close;
           7. remove the lock; record the duration in write_phase.json.

Run: OMP_NUM_THREADS=2 python3 -I ml/integrity/write_phase.py --dry-run
     OMP_NUM_THREADS=2 python3 -I ml/integrity/write_phase.py --write --backup <path>
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import date, datetime
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "2")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import duckdb  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import nse_historical_ingest as nhi  # noqa: E402
from ml.integrity.common import DATA_EXT, DB_PATH, LOCK_FILE, OUT, log, wjson  # noqa: E402
from ml.integrity.sessions import STAGING, apply_fixes_to_export, load_eod  # noqa: E402

FEED = DATA_EXT / "corporate_actions_feed.csv"
DRY = STAGING / "equity_features_dryrun.parquet"
SPECIAL_KIND = {
    "2016-10-30": "muhurat", "2017-10-19": "muhurat", "2018-11-07": "muhurat", "2019-10-27": "muhurat",
    "2020-02-01": "budget", "2020-11-14": "muhurat", "2021-11-04": "muhurat", "2022-10-24": "muhurat",
    "2023-11-12": "muhurat", "2024-01-20": "special_full_session", "2024-03-02": "special_live_session",
    "2024-05-18": "special_live_session", "2024-11-01": "muhurat", "2025-02-01": "budget",
    "2025-10-21": "muhurat", "2026-02-01": "budget"}
FEAT_CHECK_COLS = ["open", "high", "low", "close", "open_unadj", "close_unadj", "adj_factor", "ret_1d",
                   "dist_sma_20", "mom_20", "vol_20", "rsi_14", "atr_pct", "deliv_pct_sma_20",
                   "dist_52w_high", "fwd_ret_5d"]


def staging() -> tuple[pd.DataFrame, list[str]]:
    up = pd.read_parquet(STAGING / "sessions_upsert.parquet")
    dele = json.loads((STAGING / "sessions_delete.json").read_text())["delete_dates"]
    return up, dele


def special_sessions_table(stored: set) -> pd.DataFrame:
    rows = []
    for s in sorted(nhi.SPECIAL_SESSIONS):
        d = date.fromisoformat(s)
        rows.append({"date": d, "weekday": d.strftime("%A"), "kind": SPECIAL_KIND.get(s, "special"),
                     "in_store": d in stored,
                     "source": "nse_historical_ingest.SPECIAL_SESSIONS; 2021-10 onward confirmed by the "
                               "archive file's DATE1 column and the PR bundle"})
    return pd.DataFrame(rows)


def dry_run() -> dict:
    t0 = time.time()
    eod = load_eod()
    up, dele = staging()
    fixed = apply_fixes_to_export(eod, up, dele)
    con = duckdb.connect(":memory:")
    con.execute("SET threads TO 2")
    con.register("x", fixed[["date", "ticker", "series", "open", "high", "low", "close", "volume",
                             "turnover", "deliv_pct"]])
    con.execute("CREATE TABLE equity_eod AS SELECT * FROM x")
    con.unregister("x")
    t1 = time.time()
    n = nhi.build_features(con, ca_csv=str(FEED))
    t_bf = time.time() - t1
    ef = con.execute("SELECT * FROM equity_features").df()
    con.close()
    STAGING.mkdir(parents=True, exist_ok=True)
    ef.to_parquet(DRY, index=False)
    res = {"rows_eq_be": int(len(fixed)), "equity_features_rows": int(n), "build_features_seconds": round(t_bf, 1),
           "seconds": round(time.time() - t0, 1), "nestleind": nestle_check(ef)}
    wjson(OUT / "write_phase_dryrun.json", res)
    log(f"dry-run: build_features {n:,} rows in {t_bf:.0f}s; NESTLEIND {res['nestleind']}", "write")
    return res


def nestle_check(ef: pd.DataFrame) -> dict:
    x = ef[ef["ticker"] == "NESTLEIND"].sort_values("date")
    r = x["close"] / x["close"].shift(1)
    ru = x["close_unadj"] / x["close_unadj"].shift(1)
    w = x[(pd.to_datetime(x["date"]) >= "2023-12-20") & (pd.to_datetime(x["date"]) <= "2024-01-20")]
    return {"rows": int(len(x)), "max_abs_log_ret_adjusted": float(np.nanmax(np.abs(np.log(r)))),
            "max_abs_log_ret_unadjusted": float(np.nanmax(np.abs(np.log(ru)))),
            "adj_close_2024-01-04": float(w.loc[pd.to_datetime(w["date"]) == "2024-01-04", "close"].iloc[0]),
            "adj_close_2024-01-05": float(w.loc[pd.to_datetime(w["date"]) == "2024-01-05", "close"].iloc[0]),
            "no_10x_break": bool(np.nanmax(np.abs(np.log(r))) < np.log(1.5))}


def write(backup: str, db_path: Path = DB_PATH, rehearsal: bool = False) -> dict:
    """The write procedure.  rehearsal=True runs it on a scratch COPY of the store
    (db_path), without the shared lock and without a backup, to time and test it."""
    t0 = time.time()
    if not rehearsal and LOCK_FILE.exists():
        raise SystemExit(f"lock exists: {LOCK_FILE.read_text()}")
    if Path(str(db_path) + ".wal").exists():
        raise SystemExit("a .wal file exists next to the store: another writer may be active")
    up, dele = staging()
    feed = pd.read_csv(FEED)
    ca_all = pd.read_csv(DATA_EXT / "corporate_actions_all.csv")
    etf = pd.read_csv(DATA_EXT / "etf_list.csv")
    em = pd.read_csv(DATA_EXT / "equity_master.csv")
    tag = "rehearsal" if rehearsal else "write"
    res: dict = {"db": str(db_path), "rehearsal": rehearsal}
    if not rehearsal:
        # backup BEFORE the lock (P1 is the only writer; the copy takes > 1 min on this disk),
        # then verify nothing touched the store while copying
        st0 = os.stat(db_path)
        tb = time.time()
        shutil.copy2(db_path, backup)
        st1 = os.stat(db_path)
        if (st0.st_size, st0.st_mtime_ns) != (st1.st_size, st1.st_mtime_ns) or os.path.getsize(backup) != st1.st_size:
            raise SystemExit("the store changed while it was being backed up; aborting before the lock")
        res["backup"] = {"path": backup, "bytes": os.path.getsize(backup), "seconds": round(time.time() - tb, 1),
                         "store_mtime": datetime.fromtimestamp(st1.st_mtime).isoformat(timespec="seconds"),
                         "taken": "before the lock; store size and mtime verified unchanged"}
        log(f"backup copied to {backup} ({res['backup']['seconds']}s)", tag)
        t0 = time.time()                      # the lock window starts here
        LOCK_FILE.write_text(json.dumps({
            "owner": "P1 data-integrity stream", "started": datetime.now().isoformat(timespec="seconds"),
            "doing": f"delete {dele}; upsert {len(up):,} verified rows on {up['date'].dt.date.nunique()} dates; "
                     f"tables corporate_actions/etf_list/equity_master/special_sessions; "
                     f"build_features with {len(feed)} corporate-action events",
            "pid": os.getpid()}, indent=1))
        log(f"LOCK created {LOCK_FILE}", tag)
    res["started"] = datetime.now().isoformat(timespec="seconds")
    try:
        if not rehearsal and os.stat(db_path).st_mtime_ns != st1.st_mtime_ns:
            raise SystemExit("the store changed after the backup")
        store = nhi.DuckDBStore(str(db_path))
        con = store.con
        con.execute("SET threads TO 2")
        q = lambda sql, *p: con.execute(sql, list(p)).fetchall()  # noqa: E731
        res["before"] = {"equity_eod_rows": q("SELECT count(*) FROM equity_eod")[0][0],
                         "equity_eod_dates": q("SELECT count(DISTINCT date) FROM equity_eod")[0][0],
                         "equity_features_rows": q("SELECT count(*) FROM equity_features")[0][0],
                         "rows_on_delete_dates": {d: q("SELECT count(*) FROM equity_eod WHERE date = ?", d)[0][0]
                                                  for d in dele}}
        keys = up[["date", "ticker", "series"]].assign(date=lambda x: x["date"].dt.date)
        con.register("k_df", keys)
        res["overwrites_existing_keys"] = q("SELECT count(*) FROM equity_eod e JOIN k_df k ON e.date = k.date "
                                            "AND e.ticker = k.ticker AND e.series = k.series")[0][0]
        con.unregister("k_df")
        tw = time.time()
        con.execute("BEGIN TRANSACTION")
        for d in dele:
            con.execute("DELETE FROM equity_eod WHERE date = ?", [d])
        n_up = store.upsert(up)
        con.execute("COMMIT")
        res["upsert"] = {"rows": int(n_up), "deleted_dates": dele, "seconds": round(time.time() - tw, 1),
                         "by_date": {str(k.date()): int(v) for k, v in up.groupby("date").size().items()}}
        log(f"upserted {n_up:,} rows, deleted dates {dele}", tag)
        stored = {r[0] for r in q("SELECT DISTINCT date FROM equity_eod")}
        tables = {"corporate_actions": ca_all, "etf_list": etf, "equity_master": em,
                  "special_sessions": special_sessions_table(stored)}
        for name, df in tables.items():
            con.register("t_df", df)
            con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM t_df")
            con.unregister("t_df")
        res["tables"] = {k: int(len(v)) for k, v in tables.items()}
        tf = time.time()
        n_feat = nhi.build_features(con, ca_csv=str(FEED))
        res["build_features"] = {"rows": int(n_feat), "seconds": round(time.time() - tf, 1)}
        log(f"build_features: {n_feat:,} rows ({res['build_features']['seconds']}s)", tag)
        # ---- verification ----
        after = {"equity_eod_rows": q("SELECT count(*) FROM equity_eod")[0][0],
                 "equity_eod_dates": q("SELECT count(DISTINCT date) FROM equity_eod")[0][0],
                 "eq_be_rows": q("SELECT count(*) FROM equity_eod WHERE series IN ('EQ','BE')")[0][0],
                 "eq_be_dup_date_ticker": q("SELECT count(*) FROM (SELECT date, ticker FROM equity_eod WHERE "
                                            "series IN ('EQ','BE') GROUP BY 1,2 HAVING count(*) > 1)")[0][0],
                 "equity_features_rows": q("SELECT count(*) FROM equity_features")[0][0],
                 "rows_on_delete_dates": {d: q("SELECT count(*) FROM equity_eod WHERE date = ?", d)[0][0] for d in dele},
                 "rows_on_upsert_dates": {str(k.date()): q("SELECT count(*) FROM equity_eod WHERE date = ?",
                                                           k.date())[0][0] for k in sorted(up["date"].unique())},
                 "adj_factor_ne_1_rows": q("SELECT count(*) FROM equity_features WHERE adj_factor <> 1")[0][0]}
        after["expected_equity_eod_rows"] = (res["before"]["equity_eod_rows"]
                                             - sum(res["before"]["rows_on_delete_dates"].values()) + int(n_up)
                                             - int(res["overwrites_existing_keys"]))
        after["row_count_as_expected"] = after["equity_eod_rows"] == after["expected_equity_eod_rows"]
        res["after"] = after
        ef = con.execute("SELECT * FROM equity_features").df()
        res["nestleind"] = nestle_check(ef)
        scan = nhi.check_sessions(con)
        res["continuity_after"] = {"max_share": float(scan["share"].max()),
                                   "flagged": [str(pd.Timestamp(d).date()) for d in scan.loc[scan["flagged"], "date"]],
                                   "top5": scan.sort_values("share", ascending=False).head(5).assign(
                                       date=lambda x: pd.to_datetime(x["date"]).dt.strftime("%Y-%m-%d"))
                                   .to_dict("records")}
        scan.to_csv(OUT / "continuity_after_store.csv", index=False)
        ex = con.execute(
            """
            WITH x AS (
                SELECT date, ticker, prev_close,
                       lag(close) OVER (PARTITION BY ticker ORDER BY date) AS stored_prev
                FROM equity_eod WHERE series IN ('EQ','BE')),
            m AS (SELECT * FROM x WHERE stored_prev IS NOT NULL AND prev_close IS NOT NULL
                  AND abs(prev_close - stored_prev) > 0.005),
            c AS (SELECT DISTINCT ticker, CAST(ex_date AS DATE) AS d FROM corporate_actions WHERE ex_date IS NOT NULL)
            SELECT count(*) AS mismatches,
                   count(*) FILTER (WHERE c.ticker IS NOT NULL) AS on_a_parsed_ex_date
            FROM m LEFT JOIN c ON m.ticker = c.ticker AND m.date = c.d
            """).fetchall()[0]
        res["continuity_after"]["mismatch_rows_total"] = int(ex[0])
        res["continuity_after"]["mismatch_rows_on_a_parsed_ex_date"] = int(ex[1])
        if DRY.exists():
            res["dry_run_equality"] = compare_dry(ef)
        con.execute("CHECKPOINT")
        store.close()
    finally:
        if not rehearsal:
            LOCK_FILE.unlink(missing_ok=True)
            log("LOCK removed", tag)
    res["finished"] = datetime.now().isoformat(timespec="seconds")
    res["duration_seconds"] = round(time.time() - t0, 1)
    wjson(OUT / ("write_phase_rehearsal.json" if rehearsal else "write_phase.json"), res)
    log(f"{tag} done in {res['duration_seconds']}s", tag)
    return res


def compare_dry(ef: pd.DataFrame) -> dict:
    dry = pd.read_parquet(DRY)
    a = ef.sort_values(["ticker", "date"]).reset_index(drop=True)
    b = dry.sort_values(["ticker", "date"]).reset_index(drop=True)
    out = {"rows_store": int(len(a)), "rows_dry": int(len(b))}
    if len(a) != len(b) or not (a["ticker"].to_numpy() == b["ticker"].to_numpy()).all():
        out["aligned"] = False
        return out
    out["aligned"] = True
    worst = {}
    for c in FEAT_CHECK_COLS:
        x, y = a[c].to_numpy(float), b[c].to_numpy(float)
        fin = np.isfinite(x) & np.isfinite(y)
        worst[c] = {"max_abs_diff": float(np.max(np.abs(x[fin] - y[fin]))) if fin.any() else 0.0,
                    "nan_mismatch": int((np.isfinite(x) != np.isfinite(y)).sum())}
    out["columns"] = worst
    out["identical"] = all(v["max_abs_diff"] < 1e-9 and v["nan_mismatch"] == 0 for v in worst.values())
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--backup", default="")
    ap.add_argument("--rehearse", default="", help="path of a scratch COPY of the store to rehearse on")
    a = ap.parse_args(argv)
    if a.dry_run:
        dry_run()
    if a.rehearse:
        write("", db_path=Path(a.rehearse), rehearsal=True)
    if a.write:
        if not a.backup:
            raise SystemExit("--write needs --backup <path outside the repo>")
        write(a.backup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

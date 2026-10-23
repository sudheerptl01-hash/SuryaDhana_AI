#!/usr/bin/env python3
"""The read-write window of P1 on nse_market.duckdb (ml/IMPROVEMENT_PLAN.md section 3).

--dry-run    no DuckDB file is opened: an in-memory DuckDB gets the EQ/BE rows of the
             parquet export with the P1 session fixes applied and build_features runs on
             it with the corporate-actions feed (ml/data_ext/staging/equity_features_dryrun.parquet).
--rehearse P the same write procedure on a scratch COPY P of the store (no lock, no backup).
--write      the real write:
             1. copy the store to --backup (before the lock; the store's size and mtime are
                verified unchanged, P1 being the only writer), then create
                ml/results/improve/LOCK_duckdb_write (start time, purpose, pid);
             2. one transaction: delete the mis-dated session dates of sessions_delete.json
                (each must be an exchange closure whose true session is in the staging), upsert
                the verified P1 rows plus any --extra-staging parquet (equity_eod schema) with
                DuckDBStore.upsert on the (date, ticker, series) key; the transaction is rolled
                back if any EQ/BE (date, ticker) pair would appear twice;
             3. CREATE OR REPLACE corporate_actions, etf_list, equity_master, special_sessions;
             4. build_features(con, ca_csv=--ca-csv) (default ml/data_ext/corporate_actions_feed.csv);
             5. verify: row counts, EQ/BE (date, ticker) uniqueness, the four known events'
                adjusted series, the continuity re-scan (I1), equality with the dry run;
                CHECKPOINT; remove the lock; write <--out-name>.json (default write_phase_real).

Idempotent: a second run (e.g. with --extra-staging ml/data_hist/<rows>.parquet and a merged
--ca-csv for the 10-year dataset) re-applies the same keyed upserts (overwrites, never adds a
duplicate key), finds the deleted closure dates already empty, replaces the four tables and
rebuilds equity_features from scratch.  A killed process may leave the lock file behind:
remove it by hand after checking no writer is alive.

Run: OMP_NUM_THREADS=2 python3 -I ml/integrity/write_phase.py --dry-run
     OMP_NUM_THREADS=2 python3 -I ml/integrity/write_phase.py --rehearse <scratch copy>
     OMP_NUM_THREADS=2 python3 -I ml/integrity/write_phase.py --write --backup <scratch path>
         [--extra-staging a.parquet b.parquet] [--ca-csv feed.csv] [--out-name write_phase_hist]
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


KNOWN_EVENTS = [("NESTLEIND", "2024-01-05"), ("NESTLEIND", "2025-08-08"), ("IRCTC", "2021-10-28"),
                ("TATASTEEL", "2022-07-28"), ("RELIANCE", "2024-10-28")]


def known_events_check(ef: pd.DataFrame, feed: pd.DataFrame, events: list | None = None) -> dict:
    """Adjusted vs raw close-to-close move on each known ex-date, and the largest adjusted
    move over the ticker's whole series (a 2x to 10x step would remain if the feed missed it)."""
    events = events or KNOWN_EVENTS
    out = {}
    for tkr in sorted({t for t, _ in events}):
        x = ef[ef["ticker"] == tkr].sort_values("date").reset_index(drop=True)
        x["date"] = pd.to_datetime(x["date"])
        la = np.log(x["close"] / x["close"].shift(1))
        lu = np.log(x["close_unadj"] / x["close_unadj"].shift(1))
        rec = {"rows": int(len(x)), "max_abs_log_ret_adjusted": float(np.nanmax(np.abs(la))),
               "max_abs_log_ret_raw": float(np.nanmax(np.abs(lu))),
               "feed_events": feed.loc[feed["ticker"] == tkr, ["ex_date", "ratio"]].astype(str).to_dict("records"),
               "ex_dates": {}}
        for t2, d in events:
            if t2 != tkr:
                continue
            i = x.index[x["date"] >= pd.Timestamp(d)]
            if len(i) == 0 or i[0] == 0:
                rec["ex_dates"][d] = None
                continue
            j = i[0]
            rec["ex_dates"][d] = {"session": str(x.loc[j, "date"].date()),
                                  "raw_close_prev": float(x.loc[j - 1, "close_unadj"]),
                                  "raw_close_ex": float(x.loc[j, "close_unadj"]),
                                  "adj_close_prev": float(x.loc[j - 1, "close"]),
                                  "adj_close_ex": float(x.loc[j, "close"]),
                                  "adj_ret_ex": float(x.loc[j, "close"] / x.loc[j - 1, "close"] - 1),
                                  "raw_ret_ex": float(x.loc[j, "close_unadj"] / x.loc[j - 1, "close_unadj"] - 1)}
        k = int(np.nanargmax(np.abs(la.to_numpy()))) if la.notna().any() else None
        rec["largest_adjusted_move"] = ({"date": str(x.loc[k, "date"].date()), "log_ret": float(la.iloc[k])}
                                        if k is not None else None)
        # continuity is judged on the ex-dates themselves: a real >50% day elsewhere is not a break
        rec["continuous"] = bool(all(v is not None and abs(v["adj_ret_ex"]) < 0.15
                                     for v in rec["ex_dates"].values()))
        out[tkr] = rec
    out["all_continuous"] = all(v["continuous"] for k, v in out.items() if isinstance(v, dict))
    return out


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


SERIES_KEPT = ["EQ", "BE", "BZ", "SM", "ST"]   # the ingest's convention (parse_sec_delivery)
EXTRA_STATS: dict = {}


def load_extra_staging(paths: list[str], before: str | None = None) -> pd.DataFrame:
    """Additional equity_eod rows (e.g. the history stream's 2016-2021 staging), reduced to the
    store's series convention; with `before`, every row must be dated before it."""
    frames = []
    for p_ in paths:
        x = pd.read_parquet(p_)
        miss = [c for c in nhi.EOD_COLUMNS if c not in x.columns]
        if miss:
            raise SystemExit(f"{p_}: missing equity_eod columns {miss}")
        x = x[nhi.EOD_COLUMNS].copy()
        x["date"] = pd.to_datetime(x["date"]).astype("datetime64[ns]")
        keep = x["series"].astype(str).isin(SERIES_KEPT)
        EXTRA_STATS[str(p_)] = {"rows_in_file": int(len(x)), "rows_other_series_dropped": int((~keep).sum()),
                                "series_dropped": int(x.loc[~keep, "series"].nunique()),
                                "date_min": str(x["date"].min().date()), "date_max": str(x["date"].max().date())}
        x = x[keep]
        if before is not None and (x["date"] >= pd.Timestamp(before)).any():
            raise SystemExit(f"{p_}: {int((x['date'] >= pd.Timestamp(before)).sum())} rows dated on/after {before}")
        frames.append(x)
    if not frames:
        return pd.DataFrame(columns=nhi.EOD_COLUMNS)
    out = pd.concat(frames, ignore_index=True)
    if out.duplicated(["date", "ticker", "series"]).any():
        raise SystemExit("extra staging has duplicate (date, ticker, series) keys")
    eqbe = out[out["series"].isin(["EQ", "BE"])]
    if eqbe.duplicated(["date", "ticker"]).any():
        raise SystemExit("extra staging has a ticker in both EQ and BE on one date")
    return out


def guarded_deletes(dele: list[str], up: pd.DataFrame) -> list[str]:
    """Only exchange closures whose true session is being written may be deleted."""
    ok = []
    staged = {pd.Timestamp(x).date() for x in up["date"].unique()}
    for d in dele:
        dd = date.fromisoformat(d)
        closure = d in nhi.NSE_TRADING_HOLIDAYS and dd not in set(nhi.trading_days(dd, dd))
        replaced = any(0 < (dd - x).days <= 4 for x in staged)
        if not (closure and replaced):
            raise SystemExit(f"refusing to delete {d}: closure={closure}, true session staged={replaced}")
        ok.append(d)
    return ok


def write(backup: str, db_path: Path = DB_PATH, rehearsal: bool = False, extra: list[str] | None = None,
          ca_csv: Path = FEED, ca_all_csv: Path | None = None, out_name: str = "write_phase_real",
          etf_csv: Path | None = None, extra_before: str | None = None, known: list[tuple[str, str]] | None = None,
          hist_pr_dir: Path | None = None) -> dict:
    """The write procedure.  rehearsal=True runs it on a scratch COPY of the store
    (db_path), without the shared lock and without a backup, to time and test it."""
    t0 = time.time()
    if not rehearsal and LOCK_FILE.exists():
        raise SystemExit(f"lock exists: {LOCK_FILE.read_text()}")
    if Path(str(db_path) + ".wal").exists():
        raise SystemExit("a .wal file exists next to the store: another writer may be active")
    up, dele = staging()
    xs = load_extra_staging(extra or [], before=extra_before)
    n_p1 = int(len(up))
    if len(xs):
        up = pd.concat([up[nhi.EOD_COLUMNS], xs], ignore_index=True)
        if up.duplicated(["date", "ticker", "series"]).any():
            raise SystemExit("extra staging overlaps the P1 staging keys")
    dele = guarded_deletes(dele, up)
    feed = pd.read_csv(ca_csv)
    ca_all = pd.read_csv(ca_all_csv or (DATA_EXT / "corporate_actions_all.csv"))
    etf = pd.read_csv(etf_csv or (DATA_EXT / "etf_list.csv"))
    em = pd.read_csv(DATA_EXT / "equity_master.csv")
    tag = "rehearsal" if rehearsal else "write"
    res: dict = {"db": str(db_path), "rehearsal": rehearsal, "ca_csv": str(ca_csv),
                 "staging": {"p1_rows": n_p1, "extra_rows": int(len(xs)), "extra_files": list(extra or []),
                             "extra_file_stats": dict(EXTRA_STATS), "extra_before": extra_before,
                             "delete_dates": dele},
                 "etf_list": str(etf_csv or (DATA_EXT / "etf_list.csv"))}
    if not rehearsal:
        free = shutil.disk_usage(Path(backup).parent).free
        if free < 2 * os.path.getsize(db_path):
            raise SystemExit(f"not enough free space for the backup and the store's growth ({free / 1e9:.1f} GB)")
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
        con.execute("SET memory_limit = '4GB'")      # leave room for build_features' pandas frame
        q = lambda sql, *p: con.execute(sql, list(p)).fetchall()  # noqa: E731
        res["before"] = {"equity_eod_rows": q("SELECT count(*) FROM equity_eod")[0][0],
                         "equity_eod_dates": q("SELECT count(DISTINCT date) FROM equity_eod")[0][0],
                         "equity_features_rows": q("SELECT count(*) FROM equity_features")[0][0],
                         "rows_on_delete_dates": {d: q("SELECT count(*) FROM equity_eod WHERE date = ?", d)[0][0]
                                                  for d in dele}}
        fp_sql = ("SELECT count(*), round(sum(close), 4), sum(volume), round(sum(turnover), 2), "
                  "round(sum(prev_close), 4), count(DISTINCT date), count(DISTINCT ticker) FROM equity_eod "
                  "WHERE date >= ?")
        boundary = extra_before or "2021-10-01"
        fp_before = [float(v) if v is not None else None for v in q(fp_sql, boundary)[0]]
        keys = up[["date", "ticker", "series"]].assign(date=lambda x: x["date"].dt.date)
        con.register("k_df", keys)
        res["overwrites_existing_keys"] = q("SELECT count(*) FROM equity_eod e JOIN k_df k ON e.date = k.date "
                                            "AND e.ticker = k.ticker AND e.series = k.series")[0][0]
        con.unregister("k_df")
        tw = time.time()
        con.execute("BEGIN TRANSACTION")
        deleted = {}
        for d in dele:
            deleted[d] = q("SELECT count(*) FROM equity_eod WHERE date = ?", d)[0][0]
            con.execute("DELETE FROM equity_eod WHERE date = ?", [d])
        n_up = store.upsert(up)
        dups = q("SELECT count(*) FROM (SELECT date, ticker FROM equity_eod WHERE series IN ('EQ','BE') "
                 "GROUP BY 1,2 HAVING count(*) > 1)")[0][0]
        if dups:
            con.execute("ROLLBACK")
            raise SystemExit(f"rolled back: {dups} EQ/BE (date, ticker) pairs would appear twice")
        con.execute("COMMIT")
        by_date = up.groupby("date").size()
        res["upsert"] = {"rows": int(n_up), "deleted_dates": dele, "rows_deleted": deleted,
                         "seconds": round(time.time() - tw, 1),
                         "dates": int(len(by_date)),
                         "by_date": ({str(k.date()): int(v) for k, v in by_date.items()} if len(by_date) <= 120
                                     else f"{len(by_date)} dates (see the staging files)")}
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
        n_feat = nhi.build_features(con, ca_csv=str(ca_csv))
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
                 "rows_on_upsert_dates": ({str(pd.Timestamp(k).date()): q(
                     "SELECT count(*) FROM equity_eod WHERE date = ?", pd.Timestamp(k).date())[0][0]
                     for k in sorted(up["date"].unique())} if up["date"].nunique() <= 120 else "many"),
                 "dates_in_feature_table": q("SELECT count(DISTINCT date) FROM equity_features")[0][0],
                 "adj_factor_ne_1_rows": q("SELECT count(*) FROM equity_features WHERE adj_factor <> 1")[0][0]}
        after["expected_equity_eod_rows"] = (res["before"]["equity_eod_rows"]
                                             - sum(res["before"]["rows_on_delete_dates"].values()) + int(n_up)
                                             - int(res["overwrites_existing_keys"]))
        after["row_count_as_expected"] = after["equity_eod_rows"] == after["expected_equity_eod_rows"]
        fp_after = [float(v) if v is not None else None for v in q(fp_sql, boundary)[0]]
        after["rows_from_boundary_unchanged"] = {"boundary": boundary, "before": fp_before, "after": fp_after,
                                                 "identical": fp_before == fp_after}
        if hist_pr_dir is not None:
            after["history_calendar"] = history_calendar(con, Path(hist_pr_dir), boundary)
        res["after"] = after
        import gc
        gc.collect()
        events = KNOWN_EVENTS + list(known or [])
        tick = sorted({t for t, _ in events} | {"NESTLEIND"})
        ef = con.execute("SELECT date, ticker, close, close_unadj FROM equity_features WHERE ticker IN ("
                         + ",".join("?" * len(tick)) + ") ORDER BY ticker, date", tick).df()
        res["nestleind"] = nestle_check(ef)
        res["known_events"] = known_events_check(ef, feed, events)
        del ef
        if len(xs):
            res["features_from_boundary_vs_v2_export"] = compare_to_v2_export_sql(con, boundary)
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
        if DRY.exists() and not len(xs):
            res["dry_run_equality"] = compare_dry_sql(con)
        con.execute("CHECKPOINT")
        store.close()
    finally:
        if not rehearsal:
            LOCK_FILE.unlink(missing_ok=True)
            log("LOCK removed", tag)
    res["finished"] = datetime.now().isoformat(timespec="seconds")
    res["duration_seconds"] = round(time.time() - t0, 1)
    if rehearsal:
        name = "write_phase_rehearsal" if out_name == "write_phase_real" else f"{out_name}_rehearsal"
    else:
        name = out_name
    wjson(OUT / f"{name}.json", res)
    log(f"{tag} done in {res['duration_seconds']}s", tag)
    return res


def history_calendar(con, pr_dir: Path, boundary: str) -> dict:
    """Stored sessions before the boundary vs the history PR calendar (bundle present, member
    names carrying its date) and the special sessions of that window."""
    from ml.integrity.common import bundle_inner_date, bundle_ok
    pr, misfiled = set(), {}
    for z in pr_dir.glob("PR*.zip"):
        zd = pd.to_datetime(z.stem[2:], format="%d%m%y").date()
        if bundle_ok(z):
            pr.add(zd)
        else:
            misfiled[zd] = str(bundle_inner_date(z))
    stored = {r[0] for r in con.execute("SELECT DISTINCT date FROM equity_eod WHERE date < ?", [boundary]).fetchall()}
    lo = min(stored) if stored else None
    bd = date.fromisoformat(boundary)
    pr = {d for d in pr if (lo is None or d >= lo) and d < bd}
    misfiled = {k: v for k, v in misfiled.items() if k < bd}
    years = sorted({d.year for d in stored | pr})
    by_year = {str(y): {"stored": sum(1 for d in stored if d.year == y), "pr_calendar": sum(1 for d in pr if d.year == y)}
               for y in years}
    spc = {s_: (date.fromisoformat(s_) in stored) for s_ in sorted(nhi.SPECIAL_SESSIONS)
           if lo is not None and lo <= date.fromisoformat(s_) < date.fromisoformat(boundary)}
    unknown = set(misfiled)                 # a mis-filed bundle says nothing about its own date
    return {"sessions_by_year": by_year,
            "stored_not_in_pr_calendar": sorted(str(d) for d in stored - pr - unknown),
            "pr_calendar_not_stored": sorted(str(d) for d in pr - stored),
            "misfiled_bundles": {str(k): {"holds": v, "stored": k in stored} for k, v in sorted(misfiled.items())},
            "identical": (stored - unknown) == (pr - unknown) and not (pr - stored),
            "special_sessions_stored": spc}


def compare_to_v2_export(ef: pd.DataFrame, boundary: str) -> dict:
    """From the boundary on, raw prices must equal the v2 export and adjusted prices may differ
    only through the adjustment factor (i.e. not at all if the feed is unchanged there)."""
    from ml.integrity.common import CACHE
    v2 = pd.read_parquet(CACHE / "features_prices_export_v2.parquet")
    v2["date"] = pd.to_datetime(v2["date"]).astype("datetime64[ns]")
    a = ef[pd.to_datetime(ef["date"]) >= pd.Timestamp(boundary)][list(v2.columns)].copy()
    a["date"] = pd.to_datetime(a["date"]).astype("datetime64[ns]")
    j = a.merge(v2, on=["date", "ticker"], how="outer", suffixes=("_new", "_v2"), indicator=True)
    out = {"rows_new": int(len(a)), "rows_v2": int(len(v2)),
           "rows_only_in_one": int((j["_merge"] != "both").sum())}
    jb = j[j["_merge"] == "both"]
    cols = {}
    for c in ("open_unadj", "close_unadj", "volume", "turnover", "deliv_pct", "open", "high", "low", "close"):
        x, y = jb[c + "_new"].to_numpy(float), jb[c + "_v2"].to_numpy(float)
        fin = np.isfinite(x) & np.isfinite(y)
        d = np.abs(x[fin] - y[fin])
        cols[c] = {"max_abs_diff": float(d.max()) if fin.any() else 0.0, "rows_differing": int((d > 1e-9).sum()),
                   "nan_mismatch": int((np.isfinite(x) != np.isfinite(y)).sum())}
    fac_new = jb["close_new"] / jb["close_unadj_new"]
    fac_v2 = jb["close_v2"] / jb["close_unadj_v2"]
    diff = (fac_new - fac_v2).abs() > 1e-12
    out["columns"] = cols
    out["raw_columns_identical"] = all(cols[c]["rows_differing"] == 0 and cols[c]["nan_mismatch"] == 0
                                       for c in ("open_unadj", "close_unadj", "volume", "turnover", "deliv_pct"))
    out["adjustment_factor_differs_rows"] = int(diff.sum())
    out["adjustment_factor_differs_tickers"] = sorted(jb.loc[diff, "ticker"].unique().tolist())[:50]
    return out


def _sql_diff(con, left_sql: str, right_sql: str, cols: list[str], params: list) -> dict:
    """Full outer join on (date, ticker) of two row sets, per-column differences, in DuckDB."""
    parts = []
    for c in cols:
        parts.append(f"max(abs(n.{c} - v.{c})) AS {c}_max, "
                     f"count(*) FILTER (WHERE abs(n.{c} - v.{c}) > 1e-9) AS {c}_n, "
                     f"count(*) FILTER (WHERE n.ticker IS NOT NULL AND v.ticker IS NOT NULL "
                     f"AND ((n.{c} IS NULL OR isnan(n.{c})) <> (v.{c} IS NULL OR isnan(v.{c})))) AS {c}_nan")
    q = (f"WITH n AS ({left_sql}), v AS ({right_sql}) SELECT count(*) AS rows_joined, "
         "count(*) FILTER (WHERE n.ticker IS NULL OR v.ticker IS NULL) AS only_one, "
         "count(n.ticker) AS rows_left, count(v.ticker) AS rows_right, " + ", ".join(parts) +
         " FROM n FULL OUTER JOIN v ON n.date = v.date AND n.ticker = v.ticker")
    r = con.execute(q, params).df().iloc[0]
    out = {"rows_left": int(r["rows_left"]), "rows_right": int(r["rows_right"]), "rows_only_in_one": int(r["only_one"]),
           "columns": {c: {"max_abs_diff": float(r[f"{c}_max"]) if pd.notna(r[f"{c}_max"]) else 0.0,
                           "rows_differing": int(r[f"{c}_n"]), "nan_mismatch": int(r[f"{c}_nan"])} for c in cols}}
    return out


def compare_to_v2_export_sql(con, boundary: str) -> dict:
    """From the boundary on, raw prices must equal the v2 export and adjusted prices may differ
    only through the adjustment factor (i.e. not at all if the feed is unchanged there)."""
    from ml.integrity.common import CACHE
    v2p = str(CACHE / "features_prices_export_v2.parquet")
    cols = ["open_unadj", "close_unadj", "volume", "turnover", "deliv_pct", "open", "high", "low", "close"]
    sel = "date, ticker, " + ", ".join(cols)
    out = _sql_diff(con, f"SELECT {sel} FROM equity_features WHERE date >= CAST(? AS TIMESTAMP)",
                    f"SELECT {sel} FROM read_parquet(?)", cols, [boundary, v2p])
    out["raw_columns_identical"] = all(out["columns"][c]["rows_differing"] == 0 and out["columns"][c]["nan_mismatch"] == 0
                                       for c in ("open_unadj", "close_unadj", "volume", "turnover", "deliv_pct"))
    fac = con.execute(
        "WITH n AS (SELECT date, ticker, close / close_unadj AS f FROM equity_features WHERE date >= CAST(? AS TIMESTAMP)), "
        "v AS (SELECT date, ticker, close / close_unadj AS f FROM read_parquet(?)) "
        "SELECT count(*), list(DISTINCT n.ticker) FROM n JOIN v ON n.date = v.date AND n.ticker = v.ticker "
        "WHERE abs(n.f - v.f) > 1e-12", [boundary, v2p]).fetchall()[0]
    out["adjustment_factor_differs_rows"] = int(fac[0])
    out["adjustment_factor_differs_tickers"] = sorted(fac[1] or [])[:50]
    out["rows_new"], out["rows_v2"] = out.pop("rows_left"), out.pop("rows_right")
    return out


def compare_dry_sql(con) -> dict:
    cols = [c for c in FEAT_CHECK_COLS]
    sel = "date, ticker, " + ", ".join(cols)
    out = _sql_diff(con, f"SELECT {sel} FROM equity_features", f"SELECT {sel} FROM read_parquet(?)", cols, [str(DRY)])
    out["rows_store"], out["rows_dry"] = out.pop("rows_left"), out.pop("rows_right")
    out["aligned"] = out["rows_only_in_one"] == 0
    out["identical"] = out["aligned"] and all(v["max_abs_diff"] < 1e-9 and v["nan_mismatch"] == 0
                                              for v in out["columns"].values())
    return out


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
    ap.add_argument("--extra-staging", nargs="*", default=[], help="parquet files with the equity_eod columns")
    ap.add_argument("--ca-csv", default=str(FEED), help="corporate-actions feed for build_features")
    ap.add_argument("--ca-all", default="", help="all-records CSV for the corporate_actions table")
    ap.add_argument("--out-name", default="write_phase_real", help="JSON name of a real run")
    ap.add_argument("--etf-list", default="", help="CSV for the etf_list table (default ml/data_ext/etf_list.csv)")
    ap.add_argument("--extra-before", default=None, help="every extra-staging row must be dated before this")
    ap.add_argument("--known", default="", help="extra known events TICKER:YYYY-MM-DD,... to check")
    ap.add_argument("--hist-pr-dir", default="", help="PR-bundle folder of the history window (calendar check)")
    a = ap.parse_args(argv)
    known = [tuple(x.split(":")) for x in a.known.split(",") if x]
    kw = dict(extra=a.extra_staging, ca_csv=Path(a.ca_csv), ca_all_csv=Path(a.ca_all) if a.ca_all else None,
              etf_csv=Path(a.etf_list) if a.etf_list else None, extra_before=a.extra_before, known=known,
              hist_pr_dir=Path(a.hist_pr_dir) if a.hist_pr_dir else None)
    if a.dry_run:
        dry_run()
    if a.rehearse:
        write("", db_path=Path(a.rehearse), rehearsal=True, out_name=a.out_name, **kw)
    if a.write:
        if not a.backup:
            raise SystemExit("--write needs --backup <path outside the repo>")
        write(a.backup, out_name=a.out_name, **kw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

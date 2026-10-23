#!/usr/bin/env python3
"""The v2 five-year dataset (ml/data_5y_v2/) and the v1-vs-v2 comparison (P1).

1. ml.data.build_dataset on the corrected store (opened READ-ONLY, after the write
   lock is gone): dataset_start 2022-10-03, the 43 monthly FOLDS of ml/build_5y.py,
   holdout_start 2026-08-01, rebuild_features=False (equity_features was rebuilt in
   the write phase on split/bonus-adjusted prices), exclude_tickers = every symbol
   of the PR bundles' etf files (dropped before the universe filter and before every
   cross-sectional median and rank); the universe price floor (close >= 10) is tested
   on the RAW close (close_unadj): on adjusted prices a future split would push past
   rows below the floor (look-ahead in universe membership).
2. Adds, with ml/scale5y_nested.py prep's code path (suff_per_ticker + cs_z_log):
   deliv_value_share_20 = 20d sum(deliv_qty x close) / 20d sum(turnover), raw same-day
     prints (deliv_qty is a raw share count, so the close must be raw too);
   amihud_20 = per-date z over the v2 universe of log(20d mean |ret_1d| / turnover in
     crore, |ret_1d| > 22% masked, >= 15 obs), with ret_1d from the adjusted close of
     equity_features (v2's price basis; the raw-close variant is reported for reference);
   exit_date = the ticker's own equity_features row t+21 (label exit, for the purge).
3. Writes model_dataset.parquet (52 features), manifest.json, splits.json, and
   ml/results/improve/integrity/v1_vs_v2.json.

Run: OMP_NUM_THREADS=2 python3 -I ml/integrity/build_v2.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "2")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import duckdb  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from ml.build_5y import FOLDS  # noqa: E402
from ml.data import ID_COLS, LABEL_COLS, build_dataset  # noqa: E402
from ml.integrity.common import CACHE, DATA_EXT, DATA_V1, DATA_V2, DB_PATH, LOCK_FILE, OUT, log, wjson  # noqa: E402
from ml.scale5y_nested import cs_z_log, suff_per_ticker  # noqa: E402

SUFF = ["deliv_value_share_20", "amihud_20"]
H = 20
PER_TICKER = None  # filled in main(): features that do not depend on other tickers
CROSS_SECTIONAL = {"cs_rank_mom_20", "cs_rank_ret_126", "cs_rank_vol_20", "cs_rank_turnover",
                   "cs_rank_deliv_z", "cs_rank_ret_126_isnan", "cs_rank_deliv_z_isnan", "amihud_20"}


def extra_columns(ds: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    cal = con.execute("SELECT date, ticker, close FROM equity_features ORDER BY ticker, date").df()
    eod = con.execute("SELECT date, ticker, close, turnover, deliv_qty FROM equity_eod "
                      "WHERE series IN ('EQ','BE') ORDER BY ticker, date").df()
    con.close()
    for f in (cal, eod):
        f["date"] = pd.to_datetime(f["date"]).astype("datetime64[ns]")
    assert not eod.duplicated(["date", "ticker"]).any()
    cal["exit_date"] = cal.groupby("ticker", sort=False)["date"].shift(-(H + 1))
    raw = suff_per_ticker(eod)                                   # deliv value share + raw-close amihud
    adj_in = eod.drop(columns="close").merge(cal[["date", "ticker", "close"]], on=["date", "ticker"],
                                             how="left", validate="one_to_one")
    adj = suff_per_ticker(adj_in)                                 # adjusted-close returns for amihud
    key = ds[["date", "ticker"]]
    m = key.merge(cal[["date", "ticker", "exit_date"]], on=["date", "ticker"], how="left", validate="one_to_one")
    m = m.merge(raw.rename(columns={"_amihud_raw_20": "_ami_rawclose"}), on=["date", "ticker"], how="left",
                validate="one_to_one")
    m = m.merge(adj[["date", "ticker", "_amihud_raw_20"]].rename(columns={"_amihud_raw_20": "_ami_adjclose"}),
                on=["date", "ticker"], how="left", validate="one_to_one")
    assert len(m) == len(ds)
    out = pd.DataFrame({"exit_date": m["exit_date"].to_numpy(),
                        "deliv_value_share_20": m["deliv_value_share_20"].to_numpy(float),
                        "amihud_20": cs_z_log(m["_ami_adjclose"].to_numpy(float), ds["date"])})
    ami_raw = cs_z_log(m["_ami_rawclose"].to_numpy(float), ds["date"])
    a, b = out["amihud_20"].to_numpy(float), ami_raw
    fin = np.isfinite(a) & np.isfinite(b)
    lab = ds["label_beat_mkt_20d"].notna().to_numpy()
    info = {"exit_date_missing_on_labeled_rows": int(out["exit_date"].isna().to_numpy()[lab].sum()),
            "suff_nan_pct": {f: round(100 * float(out[f].isna().mean()), 2) for f in SUFF},
            "amihud_adjusted_vs_rawclose": {
                "rows_differing_gt_1e-9": int((np.abs(a[fin] - b[fin]) > 1e-9).sum()),
                "share_differing": float(np.mean(np.abs(a[fin] - b[fin]) > 1e-9)) if fin.any() else 0.0,
                "max_abs_diff": float(np.max(np.abs(a[fin] - b[fin]))) if fin.any() else 0.0,
                "nan_mismatch": int((np.isfinite(a) != np.isfinite(b)).sum())}}
    return out, info


def compare(v1: pd.DataFrame, v2: pd.DataFrame, feats: list[str], feed: pd.DataFrame,
            etfs: set[str], first_added: pd.Timestamp) -> dict:
    def stats(d: pd.DataFrame) -> dict:
        return {"rows": int(len(d)), "tickers": int(d["ticker"].nunique()), "sessions": int(d["date"].nunique()),
                "label_beat_mkt_20d_mean": float(d["label_beat_mkt_20d"].mean()),
                "label_up_5d_mean": float(pd.to_numeric(d["label_up_5d"]).mean()),
                "y_clean_20d_share": float(d["y_clean_20d"].astype(bool).mean()),
                "labeled_rows": int(d["label_beat_mkt_20d"].notna().sum()),
                "labeled_clean_rows": int((d["label_beat_mkt_20d"].notna() & d["y_clean_20d"].astype(bool)).sum()),
                "flag_split_20d_rate": float(d["flag_split_20d"].mean()),
                "etf_tickers_by_list": int(d.loc[d["ticker"].isin(etfs), "ticker"].nunique()),
                "etf_rows_by_list": int(d["ticker"].isin(etfs).sum())}
    res = {"v1": stats(v1), "v2": stats(v2)}
    res["etf_rows_removed_from_v1"] = res["v1"]["etf_rows_by_list"]
    k1 = set(zip(v1["date"], v1["ticker"]))
    k2 = set(zip(v2["date"], v2["ticker"]))
    res["rows_only_v1"] = len(k1 - k2)
    res["rows_only_v2"] = len(k2 - k1)
    res["rows_only_v1_that_are_etf"] = int(sum(t in etfs for _, t in (k1 - k2)))
    j = v1.merge(v2, on=["date", "ticker"], suffixes=("_v1", "_v2"))
    res["common_rows"] = int(len(j))
    ca_t = set(feed["ticker"])
    grp = np.where(j["ticker"].isin(ca_t), "A_ticker_with_adjusted_ca",
                   np.where(j["date"] < first_added, "B_other_before_first_added_session",
                            "C_other_from_first_added_session"))
    res["common_rows_by_group"] = {g: int((grp == g).sum()) for g in sorted(set(grp))}
    per = {}
    for c in feats + ["y_raw_20d", "y_excess_20d", "label_beat_mkt_20d", "fwd_ret_5d"]:
        if c + "_v1" not in j.columns:
            continue
        x, y = j[c + "_v1"].to_numpy(float), j[c + "_v2"].to_numpy(float)
        fin = np.isfinite(x) & np.isfinite(y)
        diff = np.zeros(len(j), bool)
        diff[fin] = np.abs(x[fin] - y[fin]) > 1e-9
        diff |= np.isfinite(x) != np.isfinite(y)
        rec = {"max_abs_diff": float(np.max(np.abs(x[fin] - y[fin]))) if fin.any() else 0.0,
               "share_rows_differing": float(diff.mean()),
               "cross_sectional": c in CROSS_SECTIONAL or c.startswith("y_") or c.startswith("label_")}
        rec["share_differing_by_group"] = {g: float(diff[grp == g].mean()) for g in sorted(set(grp))}
        per[c] = rec
    res["per_feature"] = per
    pt = [c for c, v in per.items() if not v["cross_sectional"] and c in feats]
    res["per_ticker_features_identical_in_group_B"] = sorted(
        c for c in pt if per[c]["share_differing_by_group"].get("B_other_before_first_added_session", 0) == 0)
    res["per_ticker_features_differing_in_group_B"] = {
        c: per[c]["share_differing_by_group"]["B_other_before_first_added_session"] for c in pt
        if per[c]["share_differing_by_group"].get("B_other_before_first_added_session", 0) > 0}
    return res


def export_v2() -> dict:
    """Parquet exports of the corrected store with the v1 export schemas (ml/data_ext/)."""
    t0 = time.time()
    con = duckdb.connect(str(DB_PATH), read_only=True)
    def table(sql: str):
        r = con.execute(sql).arrow()
        return r.read_all() if hasattr(r, "read_all") else r     # duckdb >= 1.4 returns a reader:
                                                                   # read it before the next query
    eod = table("SELECT date, ticker, series, prev_close, open, high, low, last, close, vwap, volume, "
                "turnover, trades, deliv_qty, deliv_pct FROM equity_eod WHERE series IN ('EQ','BE') "
                "ORDER BY ticker, date")
    fp = table("SELECT date, ticker, open, high, low, close, volume, turnover, deliv_pct, open_unadj, "
               "close_unadj FROM equity_features ORDER BY ticker, date")
    con.close()
    import pyarrow.parquet as pq
    if eod.num_rows == 0 or fp.num_rows == 0:
        raise SystemExit("empty export")
    CACHE.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, tab in (("eod_export_v2.parquet", eod), ("features_prices_export_v2.parquet", fp)):
        v1 = pq.read_schema(CACHE / name.replace("_v2", "_v1"))
        if tab.schema.names != v1.names:
            raise SystemExit(f"{name}: columns {tab.schema.names} differ from v1 {v1.names}")
        if tab.schema != v1:                      # same columns; align types to the v1 export
            tab = tab.cast(v1)
        tmp = CACHE / (name + ".tmp")
        pq.write_table(tab, tmp)
        tmp.replace(CACHE / name)
        out[name] = {"rows": tab.num_rows, "columns": tab.schema.names, "path": str(CACHE / name)}
    out["seconds"] = round(time.time() - t0, 1)
    return out


def main(argv=None) -> int:
    t0 = time.time()
    if LOCK_FILE.exists():
        raise SystemExit("the DuckDB write lock exists; v2 is built after the write phase")
    exports = export_v2()
    log(f"v2 exports: {exports}", "v2")
    etf = pd.read_csv(DATA_EXT / "etf_list.csv")
    etfs = set(etf["symbol"].astype(str))
    feed = pd.read_csv(DATA_EXT / "corporate_actions_feed.csv")
    manifest = build_dataset(db_path=str(DB_PATH), rebuild_features=False, dataset_start="2022-10-03",
                             fold_months=FOLDS, holdout_start="2026-08-01", out_dir=DATA_V2,
                             exclude_tickers=etfs, read_only=True, universe_price_col="close_unadj")
    t_build = time.time() - t0
    ds = pd.read_parquet(DATA_V2 / "model_dataset.parquet")
    ds["date"] = pd.to_datetime(ds["date"]).astype("datetime64[ns]")
    extra, info = extra_columns(ds)
    for c in SUFF:
        ds[c] = extra[c].to_numpy(float)
    ds["exit_date"] = pd.to_datetime(extra["exit_date"]).to_numpy()
    feats = list(manifest["features"]) + SUFF
    v1m = json.loads((DATA_V1 / "manifest.json").read_text())
    feats_match = feats == v1m["features"] + SUFF
    ds = ds[ID_COLS + feats + LABEL_COLS + ["exit_date"]]
    ds.to_parquet(DATA_V2 / "model_dataset.parquet", index=False)
    splits2 = json.loads((DATA_V2 / "splits.json").read_text())
    splits1 = json.loads((DATA_V1 / "splits.json").read_text())
    fold_diff = []
    for a, b in zip(splits1["folds"], splits2["folds"]):
        d = {k: (a[k], b[k]) for k in ("train_end", "test_start", "test_end") if a[k] != b[k]}
        if d or a["name"] != b["name"]:
            fold_diff.append({"name": a["name"], **{k: {"v1": v[0], "v2": v[1]} for k, v in d.items()}})
    hd = {k: {"v1": splits1["holdout"][k], "v2": splits2["holdout"][k]} for k in ("train_end", "test_start", "test_end")
          if splits1["holdout"][k] != splits2["holdout"][k]}
    v1 = pd.read_parquet(DATA_V1 / "model_dataset.parquet")
    v1["date"] = pd.to_datetime(v1["date"]).astype("datetime64[ns]")
    # the v1 suff features, from the v1 prep cache, for the per-feature comparison
    ex1 = DATA_V1.parent / "results" / "scale5y" / "cache" / "extra_5y.parquet"
    if ex1.exists():
        e1 = pd.read_parquet(ex1)
        assert (e1["ticker"].to_numpy() == v1["ticker"].to_numpy()).all()
        for c in SUFF:
            v1[c] = e1[c].to_numpy(float)
    sessions = json.loads((OUT / "sessions.json").read_text())
    added = sorted(sessions["sessions_to_add"]) + sorted(sessions.get("redated_sessions", {}))
    first_added = pd.Timestamp(min(sessions["sessions_to_add"]))
    cmp_ = compare(v1, ds, feats, feed, etfs, first_added)
    # I3 / I4
    i3 = {"flag_split_20d_v1": cmp_["v1"]["flag_split_20d_rate"], "flag_split_20d_v2": cmp_["v2"]["flag_split_20d_rate"],
          "y_clean_20d_v1": cmp_["v1"]["y_clean_20d_share"], "y_clean_20d_v2": cmp_["v2"]["y_clean_20d_share"]}
    i3["pass"] = bool(i3["flag_split_20d_v2"] < i3["flag_split_20d_v1"] and i3["y_clean_20d_v2"] > i3["y_clean_20d_v1"])
    pit = _pit_etf_rows(ds)
    i4 = {"v2_tickers_in_etf_union": cmp_["v2"]["etf_tickers_by_list"],
          "v2_rows_whose_ticker_is_in_that_dates_etf_file": pit, "pass": bool(cmp_["v2"]["etf_tickers_by_list"] == 0
                                                                            and pit == 0)}
    manifest.update({
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "rows": int(len(ds)), "tickers": int(ds["ticker"].nunique()), "sessions": int(ds["date"].nunique()),
        "features": feats,
        "extra_columns": ["exit_date"],
        "version": "v2 (P1 data integrity): corrected sessions, split/bonus-adjusted equity_features, ETFs excluded",
        "label_balance": {"beat_mkt_20d": float(ds["label_beat_mkt_20d"].mean()),
                          "up_5d": float(pd.to_numeric(ds["label_up_5d"]).mean()),
                          "y_clean_20d_pct": float(ds["y_clean_20d"].astype(bool).mean())},
        "flag_split_20d_rate": float(ds["flag_split_20d"].mean()),
        "corporate_actions": {"feed": "ml/data_ext/corporate_actions_feed.csv", "events": int(len(feed)),
                              "price_break_flags": "ml/data_ext/price_break_flags.csv (not applied as masks)"},
        "etf_exclusion": {"source": "ml/data_ext/etf_list.csv (union of the PR bundles' etf files)",
                          "symbols": int(len(etfs)), **manifest.get("excluded_tickers", {})},
        "sessions_fixed": {"added": sorted(sessions["sessions_to_add"]),
                           "redated": sessions.get("redated_sessions", {}),
                           "rebuilt_rows_2022-03-07": sessions["march_2022"]["rows_rebuilt_2022-03-07"]},
        "suff_features": {"deliv_value_share_20": "20d sum(deliv_qty*close)/sum(turnover), raw same-day prints, "
                                                  ">= 15 obs (ml/scale5y_nested.py suff_per_ticker)",
                          "amihud_20": "per-date z over v2 universe rows of log(20d mean |ret_1d|/(turnover/1e7)), "
                                       "|ret_1d|>22% masked, >= 15 obs; ret_1d on adjusted closes "
                                       "(equity_features.close)",
                          **info},
        "features_equal_v1_plus_suff": bool(feats_match),
        "fold_boundaries_vs_v1": {"folds_changed": fold_diff, "holdout_changed": hd},
        "known_gaps": "dividends, rights, demergers, schemes and capital reductions are not adjusted "
                      "(price_break_flags.csv lists their ex-dates); y_clean_20d still masks |ret_1d|>22%",
        "build_seconds": round(time.time() - t0, 1)})
    manifest.pop("excluded_tickers", None)
    (DATA_V2 / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str))
    out = {"dataset": {k: manifest[k] for k in ("rows", "tickers", "sessions", "date_min", "date_max",
                                                "last_labeled_date_20d")},
           "n_features": len(feats), "features_equal_v1_plus_suff": bool(feats_match),
           "comparison": cmp_, "fold_boundaries_vs_v1": manifest["fold_boundaries_vs_v1"],
           "suff": info, "I3": i3, "I4": i4, "added_or_redated_sessions": added, "exports": exports,
           "seconds": {"build_dataset": round(t_build, 1), "total": round(time.time() - t0, 1)}}
    wjson(OUT / "v1_vs_v2.json", out)
    log(f"v2: {manifest['rows']:,} rows, {manifest['tickers']} tickers, {len(feats)} features; I3 {i3['pass']}, "
        f"I4 {i4['pass']}; folds changed {len(fold_diff)} ({time.time() - t0:.0f}s)", "v2")
    return 0


def _pit_etf_rows(ds: pd.DataFrame) -> int:
    """Rows of v2 whose ticker appears in that same date's etf file (point-in-time I4 check)."""
    from ml.integrity.corporate_actions import read_members
    etf, _ = read_members("etf")
    pit = set(zip(pd.to_datetime(etf["file_date"]).astype("datetime64[ns]"), etf["SYMBOL"]))
    return int(sum((d, t) in pit for d, t in zip(ds["date"], ds["ticker"])))


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""The ten-year dataset (ml/data_10y/) with the v2 machinery, and the v2-vs-10y comparison.

1. ml.data.build_dataset on the store after the 10-year write phase (read-only):
   dataset_start 2017-10-02, one fold per calendar month 2018-01 .. 2026-07 (103 folds,
   22-session embargo), holdout_start 2026-08-01, rebuild_features=False, exclude_tickers =
   ml/data_ext/etf_list_10y.csv, universe_price_col close_unadj, and the NaN indicators
   pinned to v2's list so manifest.json["features"] carries the same 52 names.
2. deliv_value_share_20, amihud_20 and exit_date exactly as for v2 (build_v2.extra_columns).
3. ml/results/improve/integrity/v2_vs_10y.json: dataset stats, the first fold's training
   rows, and per-feature differences on the rows common to v2 and 10y (date >= 2022-10-03),
   split into rows before / from 2023-10-02 (one year into v2, two years into the store) and
   with the NaN pattern changes (v2 NaN filled in 10y = long windows that now have history).

Run: OMP_NUM_THREADS=2 python3 -I ml/integrity/build_10y.py
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

from ml.data import ID_COLS, LABEL_COLS, build_dataset  # noqa: E402
from ml.integrity.build_v2 import SUFF, extra_columns  # noqa: E402
from ml.integrity.common import CACHE, DATA_EXT, DATA_V2, DB_PATH, LOCK_FILE, ML_DIR, OUT, log, wjson  # noqa: E402

DATA_10Y = ML_DIR / "data_10y"
DATASET_START = "2017-10-02"
FOLDS_10Y = [(y, m) for y in range(2018, 2026) for m in range(1, 13)] + [(2026, m) for m in range(1, 8)]
COMMON_FROM = "2022-10-03"
SETTLED_FROM = "2023-10-02"
HIST_PR = ML_DIR / "data_raw" / "hist" / "pr"


def export_10y() -> dict:
    """eod_export_10y / features_prices_export_10y with the v2 export columns and types."""
    t0 = time.time()
    con = duckdb.connect(str(DB_PATH), read_only=True)

    def table(sql: str):
        r = con.execute(sql).arrow()
        return r.read_all() if hasattr(r, "read_all") else r

    eod = table("SELECT date, ticker, series, prev_close, open, high, low, last, close, vwap, volume, turnover, "
                "trades, deliv_qty, deliv_pct FROM equity_eod WHERE series IN ('EQ','BE') ORDER BY ticker, date")
    fp = table("SELECT date, ticker, open, high, low, close, volume, turnover, deliv_pct, open_unadj, close_unadj "
               "FROM equity_features ORDER BY ticker, date")
    con.close()
    import pyarrow.parquet as pq
    out = {}
    for name, tab in (("eod_export_10y.parquet", eod), ("features_prices_export_10y.parquet", fp)):
        ref = pq.read_schema(CACHE / name.replace("_10y", "_v2"))
        if tab.schema.names != ref.names:
            raise SystemExit(f"{name}: columns differ from the v2 export")
        if tab.schema != ref:
            tab = tab.cast(ref)
        tmp = CACHE / (name + ".tmp")
        pq.write_table(tab, tmp)
        tmp.replace(CACHE / name)
        out[name] = {"rows": tab.num_rows, "path": str(CACHE / name)}
    out["seconds"] = round(time.time() - t0, 1)
    return out


def stats(d: pd.DataFrame) -> dict:
    return {"rows": int(len(d)), "tickers": int(d["ticker"].nunique()), "sessions": int(d["date"].nunique()),
            "date_min": str(d["date"].min().date()), "date_max": str(d["date"].max().date()),
            "label_beat_mkt_20d_mean": float(d["label_beat_mkt_20d"].mean()),
            "label_up_5d_mean": float(pd.to_numeric(d["label_up_5d"]).mean()),
            "y_clean_20d_share": float(d["y_clean_20d"].astype(bool).mean()),
            "labeled_rows": int(d["label_beat_mkt_20d"].notna().sum()),
            "labeled_clean_rows": int((d["label_beat_mkt_20d"].notna() & d["y_clean_20d"].astype(bool)).sum()),
            "flag_split_20d_rate": float(d["flag_split_20d"].mean())}


def compare_v2_10y(v2: pd.DataFrame, t: pd.DataFrame, feats: list[str]) -> dict:
    a = v2[v2["date"] >= COMMON_FROM]
    b = t[t["date"] >= COMMON_FROM]
    ka, kb = set(zip(a["date"], a["ticker"])), set(zip(b["date"], b["ticker"]))
    j = a.merge(b, on=["date", "ticker"], suffixes=("_v2", "_10y"))
    settled = (j["date"] >= SETTLED_FROM).to_numpy()
    res = {"rows_v2_from_2022_10_03": int(len(a)), "rows_10y_from_2022_10_03": int(len(b)),
           "rows_only_v2": len(ka - kb), "rows_only_10y": len(kb - ka), "common_rows": int(len(j)),
           "common_rows_before_2023_10_02": int((~settled).sum()), "common_rows_from_2023_10_02": int(settled.sum())}
    per = {}
    for c in feats + ["y_raw_20d", "y_excess_20d", "y_rank_20d", "label_beat_mkt_20d", "fwd_ret_5d", "y_clean_20d"]:
        x = j[c + "_v2"].to_numpy(float)
        y = j[c + "_10y"].to_numpy(float)
        fin = np.isfinite(x) & np.isfinite(y)
        d = np.zeros(len(j), bool)
        d[fin] = np.abs(x[fin] - y[fin]) > 1e-9
        filled = ~np.isfinite(x) & np.isfinite(y)
        lost = np.isfinite(x) & ~np.isfinite(y)
        d |= filled | lost
        per[c] = {"max_abs_diff": float(np.max(np.abs(x[fin] - y[fin]))) if fin.any() else 0.0,
                  "share_differing": float(d.mean()),
                  "share_differing_before_2023_10_02": float(d[~settled].mean()) if (~settled).any() else 0.0,
                  "share_differing_from_2023_10_02": float(d[settled].mean()) if settled.any() else 0.0,
                  "max_abs_diff_from_2023_10_02": float(np.max(np.abs(x[fin & settled] - y[fin & settled])))
                  if (fin & settled).any() else 0.0,
                  "v2_nan_filled_in_10y": int(filled.sum()), "v2_value_nan_in_10y": int(lost.sum())}
    res["per_feature"] = per
    res["identical_features"] = sorted(c for c, v in per.items() if v["share_differing"] == 0)
    res["features_with_v2_nans_filled"] = {c: v["v2_nan_filled_in_10y"] for c, v in per.items()
                                           if v["v2_nan_filled_in_10y"] > 0}
    res["features_differing_after_settling"] = {c: {"share": v["share_differing_from_2023_10_02"],
                                                    "max_abs_diff": v["max_abs_diff_from_2023_10_02"]}
                                                for c, v in per.items() if v["share_differing_from_2023_10_02"] > 0}
    return res


def pit_etf_rows(ds: pd.DataFrame) -> int:
    from ml.integrity import corporate_actions as ca
    dirs = [ca.RAW, HIST_PR]
    etf, _ = ca.read_members("etf", dirs=dirs)
    pit = set(zip(pd.to_datetime(etf["file_date"]).astype("datetime64[ns]"), etf["SYMBOL"]))
    return int(sum((d, t) in pit for d, t in zip(ds["date"], ds["ticker"])))


def main(argv=None) -> int:
    t0 = time.time()
    if LOCK_FILE.exists():
        raise SystemExit("the DuckDB write lock exists; the 10-year dataset is built after the write phase")
    exports = export_10y()
    log(f"10y exports: {exports}", "10y")
    etfs = set(pd.read_csv(DATA_EXT / "etf_list_10y.csv")["symbol"].astype(str))
    v2m = json.loads((DATA_V2 / "manifest.json").read_text())
    isnan = [f for f in v2m["features"] if f.endswith("_isnan")]
    assert len(FOLDS_10Y) == 103
    manifest = build_dataset(db_path=str(DB_PATH), rebuild_features=False, dataset_start=DATASET_START,
                             fold_months=FOLDS_10Y, holdout_start="2026-08-01", out_dir=DATA_10Y,
                             exclude_tickers=etfs, read_only=True, universe_price_col="close_unadj",
                             isnan_features=isnan)
    t_build = time.time() - t0
    ds = pd.read_parquet(DATA_10Y / "model_dataset.parquet")
    ds["date"] = pd.to_datetime(ds["date"]).astype("datetime64[ns]")
    extra, info = extra_columns(ds)
    for c in SUFF:
        ds[c] = extra[c].to_numpy(float)
    ds["exit_date"] = pd.to_datetime(extra["exit_date"]).to_numpy()
    feats = list(manifest["features"]) + SUFF
    same = feats == v2m["features"]
    ds = ds[ID_COLS + feats + LABEL_COLS + ["exit_date"]]
    ds.to_parquet(DATA_10Y / "model_dataset.parquet", index=False)
    splits = json.loads((DATA_10Y / "splits.json").read_text())
    s2 = json.loads((DATA_V2 / "splits.json").read_text())
    f0 = splits["folds"][0]
    tr = ds[ds["date"] <= f0["train_end"]]
    first_fold = {"fold": f0, "train_rows": int(len(tr)), "train_labeled_rows": int(tr["label_beat_mkt_20d"].notna().sum()),
                  "train_labeled_clean_rows": int((tr["label_beat_mkt_20d"].notna() & tr["y_clean_20d"].astype(bool)).sum()),
                  "train_sessions": int(tr["date"].nunique()),
                  "note": "rows dated <= train_end; the walk-forward harness also purges by exit_date"}
    # the v2 folds inside the 10y list should coincide
    v2f = {f["name"]: f for f in s2["folds"]}
    fold_match = {f["name"]: (f == v2f[f["name"]]) for f in splits["folds"] if f["name"] in v2f}
    v2 = pd.read_parquet(DATA_V2 / "model_dataset.parquet")
    v2["date"] = pd.to_datetime(v2["date"]).astype("datetime64[ns]")
    cmp_ = compare_v2_10y(v2, ds, feats)
    pit = pit_etf_rows(ds)
    st = stats(ds)
    manifest.update({
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "rows": st["rows"], "tickers": st["tickers"], "sessions": st["sessions"], "features": feats,
        "extra_columns": ["exit_date"],
        "version": "10y (P1 + P4): 2016-10..2026-10 store, split/bonus-adjusted with the merged feed, ETFs excluded",
        "label_balance": {"beat_mkt_20d": st["label_beat_mkt_20d_mean"], "up_5d": st["label_up_5d_mean"],
                          "y_clean_20d_pct": st["y_clean_20d_share"]},
        "flag_split_20d_rate": st["flag_split_20d_rate"],
        "corporate_actions": {"feed": "ml/data_ext/corporate_actions_feed_10y.csv",
                              "events": int(len(pd.read_csv(DATA_EXT / "corporate_actions_feed_10y.csv"))),
                              "price_break_flags": "ml/data_ext/price_break_flags_10y.csv (not applied as masks)"},
        "etf_exclusion": {"source": "ml/data_ext/etf_list_10y.csv", "symbols": int(len(etfs)),
                          **manifest.get("excluded_tickers", {})},
        "isnan_features_pinned_to": "ml/data_5y_v2/manifest.json",
        "suff_features": {"deliv_value_share_20": v2m["suff_features"]["deliv_value_share_20"],
                          "amihud_20": v2m["suff_features"]["amihud_20"], **info},
        "features_equal_v2": bool(same),
        "first_fold": first_fold,
        "known_gaps": v2m.get("known_gaps"),
        "build_seconds": round(time.time() - t0, 1)})
    manifest.pop("excluded_tickers", None)
    (DATA_10Y / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str))
    out = {"dataset": st, "n_features": len(feats), "features_equal_v2": bool(same),
           "folds": len(splits["folds"]), "holdout": splits["holdout"], "embargo_sessions": splits["embargo_sessions"],
           "first_fold": first_fold, "v2_folds_identical_inside_10y": {
               "compared": len(fold_match), "identical": int(sum(fold_match.values())),
               "differing": [k for k, v in fold_match.items() if not v]},
           "holdout_equal_v2": splits["holdout"] == s2["holdout"],
           "etf": {"rows_whose_ticker_is_in_the_etf_union": int(ds["ticker"].isin(etfs).sum()),
                   "rows_whose_ticker_is_in_that_dates_etf_file": pit},
           "suff": info, "comparison_v2_vs_10y": cmp_, "exports": exports,
           "seconds": {"build_dataset": round(t_build, 1), "total": round(time.time() - t0, 1)}}
    wjson(OUT / "v2_vs_10y.json", out)
    log(f"10y: {st['rows']:,} rows, {st['tickers']} tickers, {st['sessions']} sessions, {len(feats)} features "
        f"(equal to v2: {same}); first fold train rows {first_fold['train_rows']:,} ({time.time() - t0:.0f}s)", "10y")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Scoring frame of the paper book: the ten-year dataset's code path on the live store.

ml.data.build_dataset (rebuild_features=False, read_only=True, dataset_start 2017-10-02, the 103 monthly folds,
holdout 2026-08-01, exclude_tickers = ml/data_ext/etf_list_live.csv, universe_price_col close_unadj, NaN
indicators pinned to ml/data_5y_v2/manifest.json) followed by ml.integrity.build_v2.extra_columns
(deliv_value_share_20, amihud_20, exit_date): exactly ml/integrity/build_10y.py minus its exports and reports.
Output: ml/paper/state/frame/{model_dataset.parquet, manifest.json, splits.json} (gitignored), readable with
ml.improve.ab.load_frame.

Consistency proof (written to ml/results/improve2/paper/consistency.json): the frame's rows for the research
end (2026-10-16) against ml/data_10y's on all 52 features, and the same over every common row.
"""
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

from ml.paper.common import log, sha256_file, wjson
from ml.paper.config import (DATA_10Y, DATA_V2, DATASET_START, DB_PATH, ETF_LIVE, FOLDS_10Y, HOLDOUT_START,
                             LOCK_FILE, RESEARCH_END, RESULTS_DIR, STATE_DIR)

FRAME_DIR = STATE_DIR / "frame"
FRAME = FRAME_DIR / "model_dataset.parquet"
FRAME_META = FRAME_DIR / "frame_meta.json"
CONSISTENCY_JSON = RESULTS_DIR / "consistency.json"


def store_key() -> dict:
    """What the frame depends on: the store's rows and the two lists that shape the universe and prices."""
    import duckdb
    from ml.paper.config import CA_FEED_LIVE
    con = duckdb.connect(str(DB_PATH), read_only=True)
    # exact, order-independent: integer sums and an XOR of row hashes (a parallel float sum is not reproducible)
    r = con.execute("SELECT count(*), max(date), sum(volume), bit_xor(hash(date, ticker, series, open, close)) "
                    "FROM equity_eod").fetchall()[0]
    f = con.execute("SELECT count(*), max(date), bit_xor(hash(date, ticker, open, close)) FROM equity_features").fetchall()[0]
    con.close()
    return {"equity_eod": [int(r[0]), str(r[1]), int(r[2]), str(r[3])], "equity_features": [int(f[0]), str(f[1]), str(f[2])],
            "etf_live_sha256": sha256_file(ETF_LIVE) if ETF_LIVE.exists() else None,
            "ca_feed_live_sha256": sha256_file(CA_FEED_LIVE) if CA_FEED_LIVE.exists() else None}


def frame_current() -> bool:
    if not (FRAME.exists() and FRAME_META.exists()):
        return False
    return json.loads(FRAME_META.read_text()).get("store_key") == store_key()


def build_frame(force: bool = False) -> dict:
    from ml.data import ID_COLS, LABEL_COLS, build_dataset
    from ml.integrity.build_v2 import SUFF, extra_columns
    if LOCK_FILE.exists():
        raise SystemExit("the DuckDB write lock exists; the frame is built after the write")
    key = store_key()
    if not force and frame_current():
        return {"rebuilt": False, **json.loads(FRAME_META.read_text())}
    t0 = time.time()
    etfs = set(pd.read_csv(ETF_LIVE, dtype=str, keep_default_na=False)["symbol"].astype(str))
    v2m = json.loads((DATA_V2 / "manifest.json").read_text())
    isnan = [f for f in v2m["features"] if f.endswith("_isnan")]
    FRAME_DIR.mkdir(parents=True, exist_ok=True)
    manifest = build_dataset(db_path=str(DB_PATH), rebuild_features=False, dataset_start=DATASET_START,
                             fold_months=FOLDS_10Y, holdout_start=HOLDOUT_START, out_dir=FRAME_DIR,
                             exclude_tickers=etfs, read_only=True, universe_price_col="close_unadj",
                             isnan_features=isnan)
    t_build = time.time() - t0
    ds = pd.read_parquet(FRAME)
    ds["date"] = pd.to_datetime(ds["date"]).astype("datetime64[ns]")
    extra, info = extra_columns(ds)
    for c in SUFF:
        ds[c] = extra[c].to_numpy(float)
    ds["exit_date"] = pd.to_datetime(extra["exit_date"]).to_numpy()
    feats = list(manifest["features"]) + SUFF
    m10 = json.loads((DATA_10Y / "manifest.json").read_text())
    if feats != m10["features"]:
        raise SystemExit(f"frame features differ from ml/data_10y: {set(feats) ^ set(m10['features'])}")
    ds = ds[ID_COLS + feats + LABEL_COLS + ["exit_date"]]
    tmp = FRAME.with_name(FRAME.name + ".tmp")
    ds.to_parquet(tmp, index=False)
    tmp.replace(FRAME)
    meta = {"store_key": key, "rows": int(len(ds)), "tickers": int(ds["ticker"].nunique()),
            "sessions": int(ds["date"].nunique()), "date_min": str(ds["date"].min().date()),
            "date_max": str(ds["date"].max().date()), "n_features": len(feats), "features_equal_10y": True,
            "excluded_tickers": manifest.get("excluded_tickers"), "suff": info,
            "seconds": {"build_dataset": round(t_build, 1), "total": round(time.time() - t0, 1)}}
    FRAME_META.write_text(json.dumps(meta, indent=1, default=str))
    log(f"frame: {meta['rows']:,} rows, {meta['sessions']} sessions, last {meta['date_max']} ({meta['seconds']['total']} s)",
        "frame")
    return {"rebuilt": True, **meta}


CROSS_SECTIONAL = {"cs_rank_mom_20", "cs_rank_ret_126", "cs_rank_vol_20", "cs_rank_turnover", "cs_rank_deliv_z",
                   "cs_rank_ret_126_isnan", "cs_rank_deliv_z_isnan", "amihud_20"}


def _cmp(x: pd.DataFrame, y: pd.DataFrame, feats: list[str], ca_tickers: set[str]) -> dict:
    """Cell-by-cell comparison.  A differing cell is explained when it belongs to a ticker with a corporate action
    added after the research end (its pre-ex prices were rescaled), or is a cross-sectional feature on a date where
    such a ticker is in the universe (the rescaled ticker enters that date's ranks or z-scores)."""
    j = x.merge(y, on=["date", "ticker"], suffixes=("_f", "_t"), how="outer", indicator=True)
    both = j[j["_merge"] == "both"]
    is_ca = both["ticker"].isin(ca_tickers).to_numpy()
    ca_dates = set(both.loc[is_ca, "date"])
    on_ca_date = both["date"].isin(ca_dates).to_numpy()
    per, bad_rows, unexplained = {}, np.zeros(len(both), bool), 0
    for c in feats:
        u, v = both[c + "_f"].to_numpy(float), both[c + "_t"].to_numpy(float)
        same = (u == v) | (np.isnan(u) & np.isnan(v))
        fin = np.isfinite(u) & np.isfinite(v)
        d = np.abs(u[fin] - v[fin])
        expl = is_ca | (on_ca_date if c in CROSS_SECTIONAL else np.zeros(len(both), bool))
        per[c] = {"max_abs_diff": float(d.max()) if d.size else 0.0, "rows_differing": int((~same).sum()),
                  "nan_mismatch": int((np.isfinite(u) != np.isfinite(v)).sum()),
                  "rows_differing_unexplained": int((~same & ~expl).sum())}
        unexplained += per[c]["rows_differing_unexplained"]
        bad_rows |= ~same
    return {"rows_frame": int(len(x)), "rows_10y": int(len(y)), "rows_common": int(len(both)),
            "rows_only_frame": int((j["_merge"] == "left_only").sum()),
            "rows_only_10y": int((j["_merge"] == "right_only").sum()), "per": per, "unexplained": unexplained,
            "tickers": set(both.loc[bad_rows, "ticker"]), "dates": set(both.loc[bad_rows, "date"])}


def _summ(parts: list[dict], feats: list[str]) -> dict:
    per = {c: {"max_abs_diff": max(p["per"][c]["max_abs_diff"] for p in parts),
               "rows_differing": sum(p["per"][c]["rows_differing"] for p in parts),
               "nan_mismatch": sum(p["per"][c]["nan_mismatch"] for p in parts)} for c in feats}
    tick = set().union(*[p["tickers"] for p in parts])
    dts = set().union(*[p["dates"] for p in parts])
    out = {k: sum(p[k] for p in parts) for k in ("rows_frame", "rows_10y", "rows_common", "rows_only_frame",
                                                    "rows_only_10y")}
    out.update({"max_abs_diff_all_features": max(v["max_abs_diff"] for v in per.values()),
                "cells_differing": sum(v["rows_differing"] for v in per.values()),
                "nan_mismatch_cells": sum(v["nan_mismatch"] for v in per.values()),
                "per_feature_differing": {c: v for c, v in per.items() if v["rows_differing"] or v["nan_mismatch"]},
                "tickers_with_differences": sorted(tick)[:60], "n_tickers_with_differences": len(tick),
                "n_dates_with_differences": len(dts),
                "dates_with_differences_last": [str(pd.Timestamp(d).date()) for d in sorted(dts)[-5:]]})
    out["identical"] = bool(out["cells_differing"] == 0 and out["rows_only_frame"] == 0 and out["rows_only_10y"] == 0)
    out["cells_differing_unexplained"] = sum(p["unexplained"] for p in parts)
    out["equal_except_new_corporate_action_rounding"] = bool(out["cells_differing_unexplained"] == 0
                                                             and out["nan_mismatch_cells"] == 0
                                                             and out["rows_only_frame"] == 0 and out["rows_only_10y"] == 0)
    return out


def consistency_proof() -> dict:
    """Frame vs ml/data_10y on the 52 features: the research end's rows, then every common row (year by year)."""
    from ml.paper.config import CA_FEED_10Y, CA_FEED_LIVE
    m10 = json.loads((DATA_10Y / "manifest.json").read_text())
    feats = m10["features"]
    cols = ["date", "ticker"] + feats
    live, f10 = pd.read_csv(CA_FEED_LIVE), pd.read_csv(CA_FEED_10Y)
    new_ev = live.merge(f10[["ticker", "ex_date"]], on=["ticker", "ex_date"], how="left", indicator=True)
    new_ev = new_ev[new_ev["_merge"] == "left_only"]
    ca_t = set(new_ev["ticker"])
    out = {"features": len(feats), "research_end": RESEARCH_END,
           "rule": "exact equality per cell (NaN equals NaN); max_abs_diff over finite pairs",
           "corporate_actions_added_after_research_end": new_ev[["ticker", "ex_date", "ratio"]].to_dict("records"),
           "explained_difference_rule": "a cell of a ticker whose pre-ex prices the new event rescales, or a "
                                        "cross-sectional feature (ranks, amihud_20 z-score) on a date where that ticker "
                                        "is in the universe"}

    def read(path, lo, hi):
        d = pd.read_parquet(path, columns=cols, filters=[("date", ">=", pd.Timestamp(lo)), ("date", "<=", pd.Timestamp(hi))])
        d["date"] = pd.to_datetime(d["date"]).astype("datetime64[ns]")
        return d

    out["research_end_rows"] = _summ([_cmp(read(FRAME, RESEARCH_END, RESEARCH_END),
                                           read(DATA_10Y / "model_dataset.parquet", RESEARCH_END, RESEARCH_END), feats,
                                           ca_t)], feats)
    parts = []
    for y in range(2017, int(RESEARCH_END[:4]) + 1):
        lo, hi = f"{y}-01-01", min(f"{y}-12-31", RESEARCH_END)
        parts.append(_cmp(read(FRAME, lo, hi), read(DATA_10Y / "model_dataset.parquet", lo, hi), feats, ca_t))
    out["all_dates_through_research_end"] = _summ(parts, feats)
    tail = pd.read_parquet(FRAME, columns=["date"], filters=[("date", ">", pd.Timestamp(RESEARCH_END))])
    out["frame_dates_after_research_end"] = sorted(str(pd.Timestamp(x).date()) for x in tail["date"].unique())
    wjson(CONSISTENCY_JSON, out)
    r = out["research_end_rows"]
    log(f"consistency {RESEARCH_END}: {r['rows_common']} common rows, only frame {r['rows_only_frame']}, only 10y "
        f"{r['rows_only_10y']}, max |diff| {r['max_abs_diff_all_features']:.3g}, identical {r['identical']}, "
        f"unexplained cells {r['cells_differing_unexplained']}", "frame")
    return out

#!/usr/bin/env python3
"""LAST STEP ONLY. Descriptive per-date rank IC of family E against y_excess_20d (EVENTS.md section 7.7).

Descriptive, not a pass mark (the Q6 pass mark is the primary A/B mark, run by the lead):
  ear_3d       among rows with a results release in the last 60 sessions (sess_since_results <= 59) and a finite
               ear_3d, per date with >= 50 names
  every column over all rows with a finite value, per date with >= 50 names
Per-date Spearman correlation (ml.scale5y_report.per_date_ic), mean, Newey-West t with lag 20 (nw_t), by calendar
year.  Rows: labelled (finite y_excess_20d) and clean (y_clean_20d), dates before the holdout's first test date
(the holdout stays untouched).

Usage: python3 -m ml.events.ic
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from ml.events import features as F
from ml.scale5y_report import NW_LAG, nw_t, per_date_ic

ML = Path(__file__).resolve().parents[1]
OUT = ML / "results" / "improve2" / "events" / "ic.json"
MIN_NAMES = 50


def summarise(codes: np.ndarray, s: np.ndarray, y: np.ndarray, dates: np.ndarray) -> dict:
    ic = per_date_ic(codes, s, y, len(dates))
    ok = np.isfinite(ic)
    yr = pd.DatetimeIndex(dates).year.to_numpy()
    by_year = {}
    for yy in np.unique(yr):
        m = ok & (yr == yy)
        if m.sum() >= 2:
            by_year[int(yy)] = {"mean": float(ic[m].mean()), "nw_t": nw_t(ic[m]), "dates": int(m.sum()),
                                "share_positive": float((ic[m] > 0).mean())}
    return {"mean": float(ic[ok].mean()) if ok.any() else None, "nw_t": nw_t(ic[ok]) if ok.sum() > NW_LAG else None,
            "dates": int(ok.sum()), "share_positive": float((ic[ok] > 0).mean()) if ok.any() else None,
            "rows_used": int(np.isfinite(s).sum()), "by_year": by_year}


def run() -> dict:
    t0 = time.time()
    splits = json.loads((ML / "data_10y" / "splits.json").read_text())
    hold = pd.Timestamp(splits["holdout"]["test_start"])
    ds = pd.read_parquet(F.DATASET, columns=["date", "ticker", "y_excess_20d", "y_clean_20d"])
    ds["date"] = pd.to_datetime(ds["date"])
    f = pd.read_parquet(F.OUT)
    f["date"] = pd.to_datetime(f["date"])
    assert (f["ticker"].to_numpy() == ds["ticker"].to_numpy()).all()
    m = np.isfinite(ds["y_excess_20d"].to_numpy(float)) & ds["y_clean_20d"].fillna(False).to_numpy(bool) \
        & (ds["date"] < hold).to_numpy()
    f, ds = f[m].reset_index(drop=True), ds[m].reset_index(drop=True)
    dates = np.unique(ds["date"].to_numpy(dtype="datetime64[ns]"))
    codes = np.searchsorted(dates, ds["date"].to_numpy(dtype="datetime64[ns]"))
    y = ds["y_excess_20d"].to_numpy(float)
    res = {"label": "DESCRIPTIVE - not a pass mark; the Q6 pass mark is the primary A/B mark of ml/IMPROVEMENT_PLAN_2.md",
           "target": "y_excess_20d (20-session next-open excess return vs the universe median)",
           "rows": "labelled and clean rows dated before the holdout's first test date " + str(hold.date()),
           "min_names_per_date": MIN_NAMES, "nw_lag": NW_LAG, "dates_available": int(len(dates))}
    ear = f["ear_3d"].to_numpy(float)
    in60 = f["sess_since_results"].to_numpy(float) <= 59
    res["ear_3d_recent_release"] = summarise(codes, np.where(in60, ear, np.nan), y, dates)
    res["ear_3d_recent_release"]["subset"] = "rows with sess_since_results <= 59 and a finite ear_3d"
    res["columns_all_rows"] = {c: summarise(codes, f[c].to_numpy(float), y, dates) for c in F.FEATURES}
    res["seconds"] = round(time.time() - t0, 1)
    OUT.write_text(json.dumps(res, indent=1))
    print(f"[events.ic] ear_3d (recent release) mean IC {res['ear_3d_recent_release']['mean']:+.4f}, "
          f"NW t {res['ear_3d_recent_release']['nw_t']:.2f}; ic.json written", flush=True)
    return res


if __name__ == "__main__":
    run()

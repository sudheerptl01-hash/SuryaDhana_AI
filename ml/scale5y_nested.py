#!/usr/bin/env python3
"""Honest nested feature selection on the 5-year walk-forward (agent: lead-scale5y).

The audit (ml/results/audit/AUDIT.md, T11) showed the pilot champion's 10
features were chosen on its own CV test months.  This module re-runs the
pilot's selection method (ml/feature_selection.py through audit T11's code
path) INSIDE each training history, once per calendar year of folds, and then
scores the 43 monthly folds + holdout with the champion LightGBM config and an
L2 logistic on those per-year sets.

Stages (each writes to disk as it completes; re-runs skip finished units)
  prep    ml/results/scale5y/cache/extra_5y.parquet -- per dataset row: the
          label EXIT DATE (the ticker's own row t+21 in equity_features, the
          exact label definition of ml/data.py) and the two feature-sufficiency
          survivors deliv_value_share_20 / amihud_20 (ml/feature_sufficiency.py
          definitions), all rebuilt from nse_market.duckdb opened READ-ONLY.
          cache/pre_rows.parquet -- dataset rows for 2022-01-03 .. 2022-09-30
          rebuilt with ml/data.py's definitions from the same DuckDB table and
          checked identical to the 5-year dataset on its first two months: the
          5-year dataset starts 2022-10-03, i.e. only 43 labeled sessions before
          the 2023-01 fold's train_end -- too few for T11's inner protocol
          (validation blocks of 21 sessions behind a 22-session embargo).  The
          extension is used ONLY by the 2023 selection; every model trains on
          the 5-year dataset rows exactly like ml/scale5y.py.
  select  for Y in 2023..2026, window = labeled rows dated <= train_end of fold
          Y-01 (embargo-adjusted, splits_5y.json):
            univariate AUC (fs.univariate_aucs) over the last <=12 21-session
              blocks of the window that lie in the 5-year dataset;
            LightGBM gain + permutation importance (fs.model_importances) of one
              champion-config model trained on the 504 sessions before the last
              block (22-session embargo, exit-date purge), permuted on that block;
            redundancy clusters |rho|>0.9 (fs.find_redundancy_clusters);
            combined rank (fs.combined_ranking) -> selection order;
            k in {5,8,10,15} by mean AUC over the last 3 blocks (each block has
              its own rolling-504 / embargo / purge inner model); rule = smallest
              k within 0.002 of the best (the pilot's CV_TOL rule, audit T11).
          -> cache/select_<Y>.json and ml/results/scale5y/nested_selection.json
  run     nested_lgbm (champion LightGBM, raw) and nested_lr_l2 (C=0.01,
          scaled) over 43 folds + holdout, rolling 504-session window exactly as
          ml/scale5y.py's _fold_job, plus EXIT-DATE PURGE: train rows whose label
          exit date is >= the fold's test_start are dropped (audit T3).
          --ensemble adds nested_lambdarank + nested_catboost (fixed 600 trees)
          and nested_ensemble_rank = per-date mean percentile rank of
          nested_lgbm, nested_lambdarank, nested_catboost (nothing fitted).
          -> ml/results/scale5y/<model>__beat_mkt_20d.json + preds/<model>__beat_mkt_20d.parquet

Run:  cd /home/user/SuryaDhana_AI && python3 -m ml.scale5y_nested [--stages prep,select,run] [--ensemble]
Seed 108; OMP_NUM_THREADS=2, OMP_WAIT_POLICY=PASSIVE; never more than 2 worker processes.
"""
from __future__ import annotations

import os

os.environ["OMP_NUM_THREADS"] = "2"
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
os.environ["OMP_WAIT_POLICY"] = "PASSIVE"

import argparse
import json
import multiprocessing as mp
import time
from pathlib import Path

import numpy as np
import pandas as pd

import ml.evaluation as ev
import ml.feature_selection as fs
import ml.scale5y as s5
from ml.evaluation import TASKS, Preprocessor, compute_metrics

ML_DIR = ev.ML_DIR
REPO = ML_DIR.parent
DB_PATH = REPO / "nse_market.duckdb"
DATA_5Y = ML_DIR / "data_5y"
OUT = ML_DIR / "results" / "scale5y"
CACHE = OUT / "cache"
PREDS = OUT / "preds"
SEED = 108
TASK = "beat_mkt_20d"
LABEL, FWD, CLEAN = TASKS[TASK]
H = 20                     # label = open[t+1] -> open[t+21] (ticker's own rows)
EMBARGO = 22
TRAIN_SESSIONS = 504
INNER_LEN = 21
N_UNI_BLOCKS = 12
N_K_BLOCKS = 3
K_GRID = (5, 8, 10, 15)
CV_TOL = 0.002
SUFF = ["deliv_value_share_20", "amihud_20"]
PILOT10 = list(s5.CHAMPION10)
EXT_START = "2022-01-03"
DATASET_START = "2022-10-03"
YEARS = (2023, 2024, 2025, 2026)
N_JOBS = 2
N_THREADS = 2
CB_PARAMS = dict(depth=6, learning_rate=0.05, iterations=600, l2_leaf_reg=5,
                 random_seed=SEED, thread_count=N_THREADS, verbose=0)
AGENT = "lead-scale5y"

T0 = time.time()
_DF: pd.DataFrame | None = None        # set before forking
_DATES: pd.DatetimeIndex | None = None
_DD: np.ndarray | None = None
_SELF: pd.DataFrame | None = None      # selection universe (pre rows + dataset rows), date-sorted
_SD: np.ndarray | None = None
_FEATS: list[str] | None = None


def log(msg: str) -> None:
    print(f"[nested +{time.time() - T0:6.0f}s] {msg}", flush=True)


def _jd(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp, np.datetime64)):
        return str(pd.Timestamp(o).date())
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def wjson(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, default=_jd))
    tmp.replace(path)


# =========================================================================== #
# prep
# =========================================================================== #
def _groll(df: pd.DataFrame, col: str, w: int, minp: int, how: str) -> pd.Series:
    """ml/feature_sufficiency.py's per-ticker trailing rolling statistic."""
    r = df.groupby("ticker", sort=False)[col].rolling(w, min_periods=minp)
    return getattr(r, how)().reset_index(level=0, drop=True).reindex(df.index)


def suff_per_ticker(eod: pd.DataFrame) -> pd.DataFrame:
    """deliv_value_share_20 and the raw 20d Amihud ratio, ml/feature_sufficiency.py
    per_ticker_features() definitions (EQ+BE rows, ticker-own rolling windows)."""
    df = eod.sort_values(["ticker", "date"]).reset_index(drop=True).copy()
    g = df.groupby("ticker", sort=False)
    df["_ret_1d"] = g["close"].pct_change()
    dq = df["deliv_qty"].astype(float)
    okd = dq.notna() & (df["turnover"] > 0)
    df["_dval"] = (dq * df["close"]).where(okd)
    df["_dturn"] = df["turnover"].where(okd)
    sv = _groll(df, "_dval", 20, 15, "sum")
    st = _groll(df, "_dturn", 20, 15, "sum")
    df["deliv_value_share_20"] = sv / st.where(st > 0)
    absr = df["_ret_1d"].abs()
    absr = absr.where(absr <= 0.22)
    df["_illiq"] = absr / (df["turnover"].where(df["turnover"] > 0) / 1e7)
    df["_amihud_raw_20"] = _groll(df, "_illiq", 20, 15, "mean")
    return df[["date", "ticker", "deliv_value_share_20", "_amihud_raw_20"]]


def cs_z_log(raw: np.ndarray, dates: pd.Series) -> np.ndarray:
    """amihud_20 = per-date z (over the dataset universe rows) of log(raw)."""
    s = pd.Series(np.log(np.where(raw > 0, raw, np.nan)), index=dates.index)
    gs = s.groupby(dates.to_numpy())
    return ((s - gs.transform("mean")) / gs.transform("std")).to_numpy(dtype=float)


def replicate_dataset_rows(ef: pd.DataFrame, start: str, isnan_cols: list[str]) -> pd.DataFrame:
    """ml/data.py build_dataset() transformations on equity_features rows
    (features, 20d next-open labels, PIT universe, cross-sectional pieces)."""
    from ml.data import (FWD_SESSIONS, MIN_MED_TURNOVER, MIN_PRICE,
                         SPLIT_MOVE_THRESHOLD, _fwd_window_max, _rsi)
    df = ef.copy()
    df["date"] = pd.to_datetime(df["date"])
    g = df.groupby("ticker", group_keys=False)
    df["macd_norm"] = df["macd"] / df["close"]
    df["rsi_2"] = g["close"].transform(lambda s: _rsi(s, 2))
    for w in (63, 126, 252):
        df[f"ret_{w}d"] = g["close"].transform(lambda s, w=w: s / s.shift(w) - 1)
    df["mom_12_1"] = g["close"].transform(lambda s: s.shift(21) / s.shift(252) - 1)
    sma200 = g["close"].transform(lambda s: s.rolling(200, min_periods=120).mean())
    df["dist_200dma"] = df["close"] / sma200 - 1
    df["flag_below_200dma"] = (df["dist_200dma"] < 0).astype("float32")
    df["flag_near_52w_low"] = (df["dist_52w_low"] < 0.05).astype("float32")
    absret = df["ret_1d"].abs()
    df["flag_split_20d"] = (absret.groupby(df["ticker"]).transform(
        lambda s: s.rolling(20, min_periods=1).max()) > SPLIT_MOVE_THRESHOLD).astype("float32")
    df["log_turnover"] = np.log1p(df["turnover"])
    entry_open = g["open"].shift(-1)
    exit_open = g["open"].shift(-(FWD_SESSIONS + 1))
    df["y_raw_20d"] = exit_open / entry_open - 1
    entry_date = g["date"].shift(-1)
    exit_date = g["date"].shift(-(FWD_SESSIONS + 1))
    span_days = (exit_date - entry_date).dt.days
    fwd_absmax = absret.groupby(df["ticker"]).transform(lambda s: _fwd_window_max(s, FWD_SESSIONS + 1))
    df["y_clean_20d"] = (df["y_raw_20d"].notna() & (entry_open > 0) & (exit_open > 0)
                         & (span_days <= 45) & (fwd_absmax <= SPLIT_MOVE_THRESHOLD))
    med_turn = g["turnover"].transform(lambda s: s.rolling(20, min_periods=10).median())
    universe = (df["close"] >= MIN_PRICE) & (med_turn >= MIN_MED_TURNOVER)
    df = df[universe & (df["date"] >= start)].copy()
    mkt = df.groupby("date")["y_raw_20d"].transform("median")
    df["y_excess_20d"] = df["y_raw_20d"] - mkt
    df["y_rank_20d"] = df.groupby("date")["y_excess_20d"].rank(pct=True)
    df["label_beat_mkt_20d"] = np.where(df["y_excess_20d"].notna(),
                                        (df["y_excess_20d"] > 0).astype(float), np.nan)
    for src, dst in [("mom_20", "cs_rank_mom_20"), ("ret_126d", "cs_rank_ret_126"),
                     ("vol_20", "cs_rank_vol_20"), ("turnover", "cs_rank_turnover"),
                     ("deliv_pct_z_20", "cs_rank_deliv_z")]:
        df[dst] = df.groupby("date")[src].rank(pct=True)
    for c in isnan_cols:
        df[c] = df[c[: -len("_isnan")]].isna().astype("float32")
    return df.sort_values(["date", "ticker"]).reset_index(drop=True)


EF_COLS = ("date, ticker, open, high, low, close, volume, turnover, ret_1d, log_ret_1d, gap_pct, "
           "range_pct, close_pos_in_range, dist_sma_5, dist_sma_10, dist_sma_20, dist_sma_50, macd, "
           "mom_5, mom_10, mom_20, vol_5, vol_10, vol_20, rsi_14, atr_pct, vol_ratio_20, vol_z_20, "
           "deliv_pct, deliv_pct_sma_20, deliv_pct_z_20, dist_52w_high, dist_52w_low")


def prep(force: bool = False) -> dict:
    p_extra, p_pre, p_info = CACHE / "extra_5y.parquet", CACHE / "pre_rows.parquet", CACHE / "prep_info.json"
    if p_extra.exists() and p_pre.exists() and p_info.exists() and not force:
        log("prep: cached")
        return json.loads(p_info.read_text())
    import duckdb
    CACHE.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    manifest = json.loads((DATA_5Y / "manifest.json").read_text())
    feats = manifest["features"]
    isnan_cols = [f for f in feats if f.endswith("_isnan")]
    ds = pd.read_parquet(DATA_5Y / "model_dataset.parquet")
    ds["date"] = pd.to_datetime(ds["date"])
    con = duckdb.connect(str(DB_PATH), read_only=True)
    cal = con.execute("SELECT date, ticker FROM equity_features ORDER BY ticker, date").df()
    eod = con.execute("SELECT date, ticker, close, turnover, deliv_qty FROM equity_eod "
                      "WHERE series IN ('EQ','BE') ORDER BY ticker, date").df()
    ef = con.execute(f"SELECT {EF_COLS} FROM equity_features WHERE date <= TIMESTAMP '2023-03-31' "
                     "ORDER BY ticker, date").df()
    con.close()
    log(f"prep: duckdb (read-only) equity_features {len(cal):,} rows, equity_eod EQ+BE {len(eod):,}, "
        f"slice<=2023-03-31 {len(ef):,} ({time.time() - t0:.0f}s)")
    # (1) label exit date = the ticker's own row t+21 (ml/data.py label window)
    cal["date"] = pd.to_datetime(cal["date"])
    cal["exit_date"] = cal.groupby("ticker", sort=False)["date"].shift(-(H + 1))
    eod["date"] = pd.to_datetime(eod["date"])
    assert not eod.duplicated(["date", "ticker"]).any()
    # (2) sufficiency survivors, per ticker on EQ+BE rows
    pt = suff_per_ticker(eod)
    key = ds[["date", "ticker"]]
    m = key.merge(cal, on=["date", "ticker"], how="left", validate="one_to_one")
    m = m.merge(pt, on=["date", "ticker"], how="left", validate="one_to_one")
    assert len(m) == len(ds)
    extra = pd.DataFrame({"date": ds["date"], "ticker": ds["ticker"],
                          "exit_date": m["exit_date"].to_numpy(),
                          "deliv_value_share_20": m["deliv_value_share_20"].to_numpy(float),
                          "amihud_20": cs_z_log(m["_amihud_raw_20"].to_numpy(float), ds["date"])})
    lab = ds[LABEL].notna().to_numpy()
    info = {"exit_date_missing_on_labeled_rows": int(extra["exit_date"].isna().to_numpy()[lab].sum()),
            "suff_nan_pct": {f: round(100 * float(extra[f].isna().mean()), 2) for f in SUFF}}
    # check against the pilot's sufficiency dataset where they overlap
    try:
        ps = pd.read_parquet(ML_DIR / "data" / "model_dataset_suff.parquet", columns=["date", "ticker"] + SUFF)
        ps["date"] = pd.to_datetime(ps["date"])
        j = ps.merge(extra[["date", "ticker"] + SUFF], on=["date", "ticker"], suffixes=("_pilot", "_5y"))
        chk = {"rows_overlap": int(len(j))}
        for f in SUFF:
            a, b = j[f + "_pilot"].to_numpy(float), j[f + "_5y"].to_numpy(float)
            both = np.isfinite(a) & np.isfinite(b)
            chk[f] = {"max_abs_diff": float(np.max(np.abs(a[both] - b[both]))) if both.any() else None,
                      "share_abs_diff_lt_1e-9": float(np.mean(np.abs(a[both] - b[both]) < 1e-9)),
                      "nan_pattern_equal": float(np.mean(np.isfinite(a) == np.isfinite(b)))}
        info["check_vs_pilot_suff_dataset"] = chk
    except Exception as e:  # pragma: no cover
        info["check_vs_pilot_suff_dataset"] = f"skipped: {e}"
    extra.to_parquet(p_extra, index=False)
    log(f"prep: extra columns written ({time.time() - t0:.0f}s): {info}")
    # (3) pre-dataset rows for the 2023 selection window (ml/data.py definitions)
    rep = replicate_dataset_rows(ef, EXT_START, isnan_cols)
    ov = rep[(rep["date"] >= DATASET_START) & (rep["date"] <= "2022-12-01")]
    dso = ds[(ds["date"] >= DATASET_START) & (ds["date"] <= "2022-12-01")]
    j = dso.merge(ov, on=["date", "ticker"], how="outer", suffixes=("_ds", "_re"), indicator=True)
    rc = {"rows_5y": int(len(dso)), "rows_rebuilt": int(len(ov)),
          "rows_only_in_one": int((j["_merge"] != "both").sum())}
    jb = j[j["_merge"] == "both"]
    worst = {}
    for c in feats + [LABEL, FWD, "y_raw_20d", "y_rank_20d"]:
        a, b = jb[c + "_ds"].to_numpy(float), jb[c + "_re"].to_numpy(float)
        fin = np.isfinite(a) & np.isfinite(b)
        worst[c] = {"max_abs_diff": float(np.max(np.abs(a[fin] - b[fin]))) if fin.any() else 0.0,
                    "nan_mismatch": int((np.isfinite(a) != np.isfinite(b)).sum())}
    rc["clean_mask_mismatch"] = int((jb[CLEAN + "_ds"].astype(bool) != jb[CLEAN + "_re"].astype(bool)).sum())
    rc["max_abs_diff_any_column"] = max(v["max_abs_diff"] for v in worst.values())
    rc["nan_mismatch_any_column"] = sum(v["nan_mismatch"] for v in worst.values())
    rc["identical"] = bool(rc["rows_only_in_one"] == 0 and rc["max_abs_diff_any_column"] < 1e-9
                           and rc["nan_mismatch_any_column"] == 0 and rc["clean_mask_mismatch"] == 0)
    info["rebuild_check_2022-10-03_to_2022-12-01"] = rc
    pre = rep[rep["date"] < DATASET_START].copy()
    pc = pre[["date", "ticker"]].merge(cal, on=["date", "ticker"], how="left", validate="one_to_one")
    pre["exit_date"] = pc["exit_date"].to_numpy()
    pp = pre[["date", "ticker"]].merge(pt, on=["date", "ticker"], how="left", validate="one_to_one")
    pre["deliv_value_share_20"] = pp["deliv_value_share_20"].to_numpy(float)
    pre["amihud_20"] = cs_z_log(pp["_amihud_raw_20"].to_numpy(float), pre["date"])
    keep = ["date", "ticker"] + feats + SUFF + [LABEL, FWD, CLEAN, "y_raw_20d", "y_rank_20d", "exit_date"]
    pre[keep].to_parquet(p_pre, index=False)
    info["pre_rows"] = {"rows": int(len(pre)), "dates": int(pre["date"].nunique()),
                        "date_min": str(pre["date"].min().date()), "date_max": str(pre["date"].max().date()),
                        "labeled_clean": int((pre[LABEL].notna() & pre[CLEAN].astype(bool)).sum())}
    info["seconds"] = round(time.time() - t0, 1)
    wjson(p_info, info)
    log(f"prep: rebuild check {rc}; pre rows {info['pre_rows']}")
    return info


# =========================================================================== #
# shared frame
# =========================================================================== #
def load_frame() -> tuple[pd.DataFrame, list[str], dict]:
    manifest = json.loads((DATA_5Y / "manifest.json").read_text())
    splits = json.loads((DATA_5Y / "splits.json").read_text())
    feats = manifest["features"]
    cols = ["date", "ticker"] + feats + [LABEL, FWD, CLEAN, "y_raw_20d", "y_rank_20d"]
    df = pd.read_parquet(DATA_5Y / "model_dataset.parquet", columns=cols)
    df["date"] = pd.to_datetime(df["date"])
    ex = pd.read_parquet(CACHE / "extra_5y.parquet")
    assert (ex["ticker"].to_numpy() == df["ticker"].to_numpy()).all()
    assert (pd.to_datetime(ex["date"]).to_numpy() == df["date"].to_numpy()).all()
    for c in SUFF:
        df[c] = ex[c].to_numpy(float)
    df["exit_date"] = pd.to_datetime(ex["exit_date"]).to_numpy()
    return df, feats, splits


def window_rows(frame: pd.DataFrame, darr: np.ndarray, dates: pd.DatetimeIndex, spec: dict,
                train_sessions: int = TRAIN_SESSIONS) -> tuple[pd.DataFrame, pd.DataFrame, int, int]:
    """ml/scale5y.py _fold_job rows on a DATE-SORTED frame (sliced, not masked):
    train = labeled clean rows with first <= date <= train_end, first = the
    session train_sessions before train_end on `dates`; test = labeled clean
    rows in [test_start, test_end].  Then the audit-T3 purge: drop train rows
    whose label exit date (ticker row t+21) is >= test_start."""
    te_ = pd.Timestamp(spec["train_end"])
    first = dates[max(dates.get_loc(te_) - train_sessions, 0)] if train_sessions else dates[0]
    i0 = int(np.searchsorted(darr, first.to_datetime64(), "left"))
    i1 = int(np.searchsorted(darr, te_.to_datetime64(), "right"))
    tr = frame.iloc[i0:i1]
    lab = tr[LABEL].notna().to_numpy() & tr[CLEAN].to_numpy().astype(bool)
    ex = tr["exit_date"].to_numpy(dtype="datetime64[ns]")
    bad = lab & ~np.isnat(ex) & (ex >= pd.Timestamp(spec["test_start"]).to_datetime64())
    n_before = int(lab.sum())
    tr = tr[lab & ~bad]
    j0 = int(np.searchsorted(darr, pd.Timestamp(spec["test_start"]).to_datetime64(), "left"))
    j1 = int(np.searchsorted(darr, pd.Timestamp(spec["test_end"]).to_datetime64(), "right"))
    te = frame.iloc[j0:j1]
    te = te[te[LABEL].notna().to_numpy() & te[CLEAN].to_numpy().astype(bool)]
    return tr, te, n_before, int(bad.sum())


def lgbm(n_threads: int = N_THREADS):
    return s5.make_model("all51", n_threads)          # the champion LightGBM config


# =========================================================================== #
# selection
# =========================================================================== #
def make_blocks(cal: pd.DatetimeIndex, n_blocks: int, min_date=None) -> list[dict]:
    """T11 inner splits generalised to n blocks: 21-session validation blocks
    ending at the last window date, each behind a 22-session embargo."""
    n = len(cal)
    out = []
    for back in range(n_blocks - 1, -1, -1):
        v_end = n - 1 - back * INNER_LEN
        v_start = v_end - INNER_LEN + 1
        it_end = v_start - EMBARGO
        if it_end < 0 or v_start < 0:
            continue
        if min_date is not None and cal[v_start] < pd.Timestamp(min_date):
            continue
        out.append({"name": f"blk{back:02d}", "train_end": str(cal[it_end].date()),
                    "test_start": str(cal[v_start].date()), "test_end": str(cal[v_end].date())})
    return out


DUMMY = {"name": "holdout", "train_end": "2000-01-01", "test_start": "2100-01-01", "test_end": "2000-01-01"}


def _year_frame(year: int) -> tuple[pd.DataFrame, pd.DatetimeIndex, dict]:
    splits = json.loads((DATA_5Y / "splits.json").read_text())
    spec = next(f for f in splits["folds"] if f["name"] == f"{year}-01")
    te = pd.Timestamp(spec["train_end"])
    pos = int(np.searchsorted(_SD, te.to_datetime64(), "right"))
    d = _SELF.iloc[:pos]
    cal = pd.DatetimeIndex(np.unique(_SD[:pos]))
    return d, cal, spec


def _sel_rank_job(year: int) -> dict:
    """Univariate + importance + clusters + combined rank for one selection year."""
    p = CACHE / f"select_{year}_rank.json"
    if p.exists():
        return json.loads(p.read_text())
    t0 = time.time()
    feats = _FEATS
    d, cal, spec = _year_frame(year)
    tm = d[LABEL].notna() & d[CLEAN].astype(bool)
    ublocks = make_blocks(cal, N_UNI_BLOCKS, min_date=DATASET_START)
    uni = fs.univariate_aucs(d, feats, {"folds": ublocks, "holdout": DUMMY})
    imp = make_blocks(cal, 1)[0]
    imp = {**imp, "name": "imp"}
    tr, te, n_before, n_purged = window_rows(d, _SD[:len(d)], cal, imp)
    dfi = pd.concat([tr, te], ignore_index=True)
    fs.IMPORTANCE_FOLD = "imp"
    gain, perm, nperm = fs.model_importances(dfi, feats, {"folds": [imp], "holdout": DUMMY})
    clusters, pairs = fs.find_redundancy_clusters(d, feats)
    entries, order, cinfo = fs.combined_ranking(feats, uni, gain, perm, clusters)
    out = {"year": year, "window_train_end": spec["train_end"], "window_first_date": str(cal[0].date()),
           "window_sessions": int(len(cal)), "window_labeled_rows": int(tm.sum()),
           "univariate_blocks": ublocks, "importance_block": imp,
           "importance_train_rows": int(len(tr)), "importance_train_rows_purged": n_purged,
           "importance_test_rows": int(nperm), "univariate": uni, "lgbm_gain": gain, "permutation": perm,
           "redundancy_clusters": cinfo, "combined_rank": entries, "selection_order": order,
           "seconds": round(time.time() - t0, 1)}
    wjson(p, out)
    log(f"select {year}: ranked ({out['seconds']}s); top-10 {order[:10]}")
    return out


def _sel_k_job(args) -> dict:
    year, k, blk, feats_k = args
    p = CACHE / f"select_{year}_k{k:02d}_{blk['name']}.json"
    if p.exists():
        return json.loads(p.read_text())
    t0 = time.time()
    d, cal, _ = _year_frame(year)
    tr, te, n_before, n_purged = window_rows(d, _SD[:len(d)], cal, blk)
    prep_ = Preprocessor("raw").fit(tr[feats_k])
    est = lgbm()
    est.fit(prep_.transform(tr[feats_k]), tr[LABEL].to_numpy(np.float32))
    sc = est.predict_proba(prep_.transform(te[feats_k]))[:, 1]
    met = compute_metrics(te[LABEL].to_numpy(np.float32), sc, te[FWD].to_numpy(np.float32))
    out = {"year": year, "k": k, "block": blk, "auc": met["auc"], "n_train": int(len(tr)),
           "n_purged": n_purged, "n_test": int(len(te)), "seconds": round(time.time() - t0, 1)}
    wjson(p, out)
    log(f"select {year}: k={k} {blk['name']} auc={met['auc']:.4f} ({out['seconds']}s)")
    return out


def select(df: pd.DataFrame, feats: list[str]) -> dict:
    global _SELF, _FEATS, _SD
    pre = pd.read_parquet(CACHE / "pre_rows.parquet")
    pre["date"] = pd.to_datetime(pre["date"])
    pre["exit_date"] = pd.to_datetime(pre["exit_date"])
    cols = ["date", "ticker"] + feats + SUFF + [LABEL, FWD, CLEAN, "exit_date"]
    _SELF = pd.concat([pre[cols], df.loc[df["date"] <= "2025-12-31", cols]], ignore_index=True)
    _SELF = _SELF.sort_values(["date", "ticker"]).reset_index(drop=True)
    _SD = _SELF["date"].to_numpy(dtype="datetime64[ns]")
    _FEATS = feats + SUFF
    ctx = mp.get_context("fork")
    with ctx.Pool(N_JOBS) as pool:
        yrs_heavy = sorted(YEARS, reverse=True)
        ranks = dict(zip(yrs_heavy, pool.map(_sel_rank_job, yrs_heavy, chunksize=1)))
    jobs = []
    for y in YEARS:
        _, cal, _ = _year_frame(y)
        for blk in make_blocks(cal, N_K_BLOCKS):
            for k in K_GRID:
                jobs.append((y, k, blk, ranks[y]["selection_order"][:k]))
    jobs.sort(key=lambda j: (-j[0], -j[1]))           # heavy first
    with ctx.Pool(N_JOBS) as pool:
        kres = pool.map(_sel_k_job, jobs, chunksize=1)
    sel = {}
    for y in YEARS:
        rk = ranks[y]
        order = rk["selection_order"]
        kc = {}
        for k in K_GRID:
            a = [r["auc"] for r in kres if r["year"] == y and r["k"] == k]
            kc[k] = float(np.mean(a))
        best = max(kc.values())
        k_sel = min(k for k, v in kc.items() if v >= best - CV_TOL)
        chosen = order[:k_sel]
        sel[str(y)] = {
            "window": {"train_end": rk["window_train_end"], "first_date": rk["window_first_date"],
                       "sessions": rk["window_sessions"], "labeled_rows": rk["window_labeled_rows"]},
            "k_curve_mean_inner_auc": {str(k): v for k, v in kc.items()},
            "k_curve_blocks": {str(k): [r["auc"] for r in kres if r["year"] == y and r["k"] == k]
                               for k in K_GRID},
            "k_selected": k_sel, "selected": chosen, "top10": order[:10], "selection_order": order,
            "overlap_selected_with_pilot10": sorted(set(chosen) & set(PILOT10)),
            "n_overlap_selected_with_pilot10": len(set(chosen) & set(PILOT10)),
            "n_overlap_top10_with_pilot10": len(set(order[:10]) & set(PILOT10)),
            "suff_features_selected": [f for f in SUFF if f in chosen],
            "suff_rank_in_order": {f: (order.index(f) + 1 if f in order else None) for f in SUFF},
            "redundancy_clusters": rk["redundancy_clusters"],
            "univariate_top10": sorted(rk["univariate"], key=lambda f: -rk["univariate"][f]["auc"])[:10],
            "univariate_blocks": [b["test_start"] + ".." + b["test_end"] for b in rk["univariate_blocks"]],
            "importance_block": rk["importance_block"],
            "importance_train_rows_purged": rk["importance_train_rows_purged"],
        }
    yrs = [str(y) for y in YEARS]
    stab = {}
    for a, b in zip(yrs[:-1], yrs[1:]):
        stab[f"{a}->{b}"] = {"top10_overlap": len(set(sel[a]["top10"]) & set(sel[b]["top10"])),
                             "selected_overlap": len(set(sel[a]["selected"]) & set(sel[b]["selected"])),
                             "selected_sizes": [len(sel[a]["selected"]), len(sel[b]["selected"])]}
    allsel = [set(sel[y]["selected"]) for y in yrs]
    payload = {
        "generated_at": pd.Timestamp.now().isoformat(timespec="seconds"),
        "generated_by": "ml/scale5y_nested.py (seed 108)",
        "method": {
            "candidates": f"{len(feats)} 5-year base features (ml/data_5y manifest; dist_sma_50_isnan absent "
                          f"at 5y because it is <2% missing) + {SUFF} (ml/feature_sufficiency.py definitions, "
                          "rebuilt from nse_market.duckdb read-only)",
            "window": "labeled clean rows dated <= train_end of fold <year>-01 (embargo-adjusted); 2023 window "
                      f"extended back to {EXT_START} with rows rebuilt from DuckDB under ml/data.py definitions "
                      "(the 5-year dataset has only 43 labeled sessions before 2022-12-01)",
            "univariate": f"fs.univariate_aucs over the last <= {N_UNI_BLOCKS} 21-session blocks of the window "
                          "inside the 5-year dataset (2023: 2 blocks)",
            "importance": "fs.model_importances: champion-config LightGBM on the 504 sessions before the last "
                          "21-session block (22-session embargo, exit-date purge); gain + permutation (AUC drop, "
                          "3 repeats, seed 108) on that block",
            "redundancy": "fs.find_redundancy_clusters, |spearman rho| > 0.9, 100k-row sample of the window",
            "rank": "fs.combined_ranking (mean of the three ranks; one representative per cluster)",
            "k_rule": f"k in {list(K_GRID)} by mean AUC over the last {N_K_BLOCKS} 21-session blocks, each with its "
                      "own rolling-504 / 22-session-embargo / exit-purged inner model; smallest k within "
                      f"{CV_TOL} of the best (pilot CV_TOL rule, audit T11 KCURVE)",
            "outer_test_data_used": "none: every number above uses rows dated <= the year's first train_end",
        },
        "pilot10": PILOT10,
        "per_year": sel,
        "stability": stab,
        "features_selected_every_year": sorted(set.intersection(*allsel)),
        "features_selected_any_year": sorted(set.union(*allsel)),
    }
    wjson(OUT / "nested_selection.json", payload)
    log("nested_selection.json written: " + "; ".join(
        f"{y}: k={sel[y]['k_selected']} {sel[y]['selected']}" for y in yrs))
    return payload


# =========================================================================== #
# outer runs
# =========================================================================== #
MODELS = {
    "nested_lgbm":       dict(kind="lgbm",       preprocess="raw",    family="trees"),
    "nested_lr_l2":      dict(kind="lr",         preprocess="scaled", family="linear"),
    "nested_lambdarank": dict(kind="lambdarank", preprocess="raw",    family="ranking"),
    "nested_catboost":   dict(kind="catboost",   preprocess="raw",    family="trees"),
}


def _outer_job(args):
    name, spec, feats = args
    ck = CACHE / "folds" / name / f"{spec['name']}.json"
    pk = ck.with_suffix(".parquet")
    if ck.exists() and pk.exists():
        return json.loads(ck.read_text())
    t0 = time.time()
    tr, te, n_before, n_purged = window_rows(_DF, _DD, _DATES, spec)
    kind = MODELS[name]["kind"]
    prep_ = Preprocessor(MODELS[name]["preprocess"]).fit(tr[feats])
    Xtr, Xte = prep_.transform(tr[feats]), prep_.transform(te[feats])
    ytr, yte = tr[LABEL].to_numpy(np.float32), te[LABEL].to_numpy(np.float32)
    if kind == "lgbm":
        est = lgbm()
        est.fit(Xtr, ytr)
        score = est.predict_proba(Xte)[:, 1]
    elif kind == "lr":
        est = s5.make_model("lr_l2", N_THREADS)
        est.fit(Xtr, ytr)
        score = est.predict_proba(Xte)[:, 1]
    elif kind == "lambdarank":
        from lightgbm import LGBMRanker
        d = tr["date"].to_numpy()
        assert (d[1:] >= d[:-1]).all(), "train rows must be date-sorted"
        grade = np.clip(np.floor(tr["y_rank_20d"].to_numpy(float) * 10), 0, 9).astype(int)
        group = tr.groupby("date", sort=True).size().to_numpy()
        p = s5.make_model("all51", N_THREADS).get_params()
        keep = {k: p[k] for k in ("num_leaves", "learning_rate", "n_estimators", "random_state")}
        est = LGBMRanker(objective="lambdarank", feature_fraction=0.8, bagging_fraction=0.8,
                         bagging_freq=1, min_data_in_leaf=200, num_threads=N_THREADS, verbosity=-1, **keep)
        est.fit(Xtr, grade, group=group)
        score = 1.0 / (1.0 + np.exp(-est.predict(Xte)))     # monotone map (AUC/ranks unchanged)
    elif kind == "catboost":
        from catboost import CatBoostClassifier
        est = CatBoostClassifier(**CB_PARAMS)
        est.fit(Xtr, ytr)
        score = est.predict_proba(Xte)[:, 1]
    else:
        raise ValueError(kind)
    met = compute_metrics(yte, score, te[FWD].to_numpy(np.float32))
    met.update(fold=spec["name"], n_train=int(len(tr)), n_train_before_purge=n_before,
               n_train_purged_exit_ge_test_start=n_purged, n_features=len(feats),
               train_seconds=round(time.time() - t0, 1))
    preds = te[["date", "ticker"]].copy()
    preds["score"], preds["y"], preds["fwd"], preds["fold"] = score, yte, te[FWD].to_numpy(), spec["name"]
    ck.parent.mkdir(parents=True, exist_ok=True)
    preds.to_parquet(pk, index=False)
    wjson(ck, met)
    log(f"{name} {spec['name']}: auc={met['auc']:.4f} n_train={len(tr):,} purged={n_purged} "
        f"k={len(feats)} ({met['train_seconds']}s)")
    return met


def year_of(spec: dict) -> str:
    return "2026" if spec["name"] == "holdout" else spec["name"][:4]


def write_model(name: str, specs: list[dict], fmap: dict, family: str, preprocess: str,
                params: dict, notes: str, folds_meta: list[dict] | None = None,
                preds: pd.DataFrame | None = None) -> dict:
    if folds_meta is None:
        folds_meta = [json.loads((CACHE / "folds" / name / f"{s['name']}.json").read_text()) for s in specs]
        preds = pd.concat([pd.read_parquet(CACHE / "folds" / name / f"{s['name']}.parquet") for s in specs],
                          ignore_index=True)
    folds = [m for m in folds_meta if m["fold"] != "holdout"]
    holdout = next((m for m in folds_meta if m["fold"] == "holdout"), None)
    aucs = np.array([f["auc"] for f in folds])
    purge_total = int(sum(m.get("n_train_purged_exit_ge_test_start", 0) for m in folds_meta))
    payload = {
        "model": name, "family": family, "agent": AGENT, "task": TASK,
        "params": params, "preprocess": preprocess,
        "n_features": None, "feature_subset": None, "nested_feature_sets": fmap,
        "folds": folds, "cv_auc_mean": float(aucs.mean()), "cv_auc_std": float(aucs.std()),
        "min_fold_auc": float(aucs.min()), "pct_folds_ge_050": float(np.mean(aucs >= 0.5)),
        "holdout": holdout,
        "train_seconds": round(float(sum(m.get("train_seconds", 0) for m in folds_meta)), 1),
        "exit_date_purge": {"rows_removed_total": purge_total,
                            "rows_removed_by_fold": {m["fold"]: m.get("n_train_purged_exit_ge_test_start", 0)
                                                     for m in folds_meta},
                            "train_rows_before_purge_total": int(sum(m.get("n_train_before_purge", 0)
                                                                     for m in folds_meta))},
        "notes": notes,
    }
    wjson(OUT / f"{name}__{TASK}.json", payload)
    PREDS.mkdir(parents=True, exist_ok=True)
    preds.to_parquet(PREDS / f"{name}__{TASK}.parquet", index=False)
    log(f"[{name}] folds={len(folds)} cv_auc={payload['cv_auc_mean']:.4f}±{payload['cv_auc_std']:.4f} "
        f"min={payload['min_fold_auc']:.4f} ge50={payload['pct_folds_ge_050']:.0%} "
        f"holdout={holdout['auc'] if holdout else float('nan'):.4f} purged={purge_total}")
    return payload


def run_models(df: pd.DataFrame, splits: dict, names: list[str]) -> None:
    global _DF, _DATES, _DD
    sel = json.loads((OUT / "nested_selection.json").read_text())["per_year"]
    fmap = {y: sel[y]["selected"] for y in sel}
    specs = splits["folds"] + [splits["holdout"]]
    _DATES = pd.DatetimeIndex(np.sort(df["date"].unique()))      # all sessions (scale5y's `dates`)
    _DF = df.sort_values(["date", "ticker"], kind="stable").reset_index(drop=True)
    _DD = _DF["date"].to_numpy(dtype="datetime64[ns]")
    ctx = mp.get_context("fork")
    for name in names:
        jobs = [(name, s, fmap[year_of(s)]) for s in specs]
        jobs.sort(key=lambda j: j[1]["name"], reverse=True)          # big windows first
        with ctx.Pool(N_JOBS) as pool:
            pool.map(_outer_job, jobs, chunksize=1)
        spec = MODELS[name]
        params = {"train_sessions": TRAIN_SESSIONS, "n_jobs": N_JOBS, "exit_date_purge": True,
                  "selection": "per calendar year of folds, nested (nested_selection.json)"}
        if spec["kind"] == "lgbm":
            params["lgbm"] = s5.make_model("all51", N_THREADS).get_params()
        elif spec["kind"] == "lr":
            params["lr"] = {"C": 0.01, "max_iter": 1000}
        elif spec["kind"] == "catboost":
            params["catboost"] = {k: v for k, v in CB_PARAMS.items() if k != "verbose"}
        elif spec["kind"] == "lambdarank":
            params["lambdarank"] = "champion tree params, relevance = floor(10*y_rank_20d) clipped 0..9, query = date"
        notes = (f"5-year walk-forward, 43 monthly folds + holdout, rolling {TRAIN_SESSIONS}-session window "
                 "(ml/scale5y.py protocol) on per-year NESTED feature sets chosen with data <= the year's first "
                 "train_end only; train rows whose label exit date >= test_start purged (audit T3)")
        write_model(name, specs, fmap, spec["family"], spec["preprocess"], params, notes)


def ensemble(splits: dict) -> None:
    members = ["nested_lgbm", "nested_lambdarank", "nested_catboost"]
    sel = json.loads((OUT / "nested_selection.json").read_text())["per_year"]
    fmap = {y: sel[y]["selected"] for y in sel}
    base = None
    for j, m in enumerate(members):
        p = pd.read_parquet(PREDS / f"{m}__{TASK}.parquet")
        p["date"] = pd.to_datetime(p["date"])
        p = p.rename(columns={"score": f"s{j}"})
        if base is None:
            base = p
        else:
            n0 = len(base)
            q = p[["date", "ticker", "fold", f"s{j}", "y"]].rename(columns={"y": f"y{j}"})
            base = base.merge(q, on=["date", "ticker", "fold"], how="inner", validate="1:1")
            assert len(base) == n0 and (base[f"y{j}"] == base["y"]).all()
    g = base.groupby("date")
    base["score"] = np.mean(np.column_stack([g[f"s{j}"].rank(pct=True).to_numpy()
                                             for j in range(len(members))]), axis=1)
    specs = splits["folds"] + [splits["holdout"]]
    metas = []
    for s in specs:
        f = base[base["fold"] == s["name"]]
        met = compute_metrics(f["y"].to_numpy(np.float32), f["score"].to_numpy(float),
                              f["fwd"].to_numpy(np.float32))
        met.update(fold=s["name"], n_train=0, train_seconds=0.0)
        metas.append(met)
    corr = {}
    for a in range(len(members)):
        for b in range(a + 1, len(members)):
            r = base.groupby("date").apply(lambda x: x[f"s{a}"].rank().corr(x[f"s{b}"].rank()))
            corr[f"{members[a]}~{members[b]}"] = round(float(r.mean()), 3)
    params = {"members": members, "combiner": "per-date percentile rank of each member, equal-weight mean; "
              "no weights fitted", "member_rank_corr_mean_per_date": corr}
    notes = ("SOTA-registered challenger (ml/results/sota/SOTA_MODELS.md) on the nested per-year sets: rank "
             "average of the champion LightGBM, LGBMRanker lambdarank and CatBoost (fixed 600 trees)")
    write_model("nested_ensemble_rank", specs, fmap, "ensemble", "rank_blend", params, notes,
                folds_meta=metas, preds=base[["date", "ticker", "score", "y", "fwd", "fold"]])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stages", default="prep,select,run")
    ap.add_argument("--models", nargs="+", default=["nested_lgbm", "nested_lr_l2"])
    ap.add_argument("--ensemble", action="store_true", help="also run lambdarank + catboost and the rank blend")
    ap.add_argument("--force-prep", action="store_true")
    ap.add_argument("--n-jobs", type=int, default=N_JOBS, help="worker processes (<= 2 on the shared box)")
    a = ap.parse_args()
    global N_JOBS
    N_JOBS = max(1, min(2, a.n_jobs))
    stages = a.stages.split(",")
    OUT.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    if "prep" in stages:
        prep(a.force_prep)
    df, feats, splits = load_frame()
    log(f"frame: {len(df):,} rows, {len(feats)} base features + {SUFF}")
    if "select" in stages:
        if (OUT / "nested_selection.json").exists():
            log("select: nested_selection.json exists (delete it to recompute)")
        else:
            select(df, feats)
    if "run" in stages:
        names = list(a.models)
        if a.ensemble:
            names += [m for m in ("nested_lambdarank", "nested_catboost") if m not in names]
        run_models(df, splits, names)
        if a.ensemble:
            ensemble(splits)
    log("done")


if __name__ == "__main__":
    main()

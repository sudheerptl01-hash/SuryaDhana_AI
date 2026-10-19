#!/usr/bin/env python3
"""Red-team audit of the SuryaDhana pilot (agent: red-team / testing lead).

Purpose: try to BREAK the pilot's headline claim -- champion
``lgbm_fs_selected`` (LightGBM, 10 selected features) with CV AUC 0.5307
(frozen) / 0.5314 (clean), "only model above chance at 95%", ">= 0.50 in all
5 OOS windows" -- by looking for leakage, overfitting, selection bias and
construction bugs, and by quantifying what chance alone produces.

Tests (seed 108, OMP_NUM_THREADS=2; each prints PASS / FAIL / INFO + number)
  T0  reproduce the clean champion run through the harness (sanity of setup)
  T1  label-permutation null: labels permuted WITHIN EACH DATE, 10 seeds
  T2  leak-detector sensitivity: champion features shifted -1 (also -5, -21)
  T3  embargo verification: calendar + per-row ACTUAL label exit dates
  T4  label construction recompute from the raw EOD snapshot
  T5  point-in-time checks: universe mask, market-state, cs_rank, champion
      features recomputed from truncated (date <= t) history
  T6  selection-bias: 30 N(0,1) noise features through the feature-selection
      scoring + harness; plus 30 PERSISTENT AR(1) noise features vs all 51
  T7  multiple-testing accounting (best-of-N order statistics)
  T8  duplicates & integrity (dataset, preds, coverage, phantom-day scan)
  T9  holdout-once check (code grep + selection paths)
  T10 preds sanity (recompute AUCs from parquet; base rates)
  extra (red-team additions)
  T11 HONEST NESTED SELECTION: re-run the feature-selection pipeline per
      outer fold using ONLY that fold's train window (inner folds), then
      score the outer test -- the selection-bias-free estimate of the
      pipeline's CV AUC
  T12 random 10-feature subsets through the harness (how special is the 10?)
  T13 y_clean mask sensitivity (test rows dropped using FUTURE prices)

Outputs (nothing else is written):
  ml/results/audit/audit.json, ml/results/audit/cache/*.json,
  ml/results/audit/<run>__beat_mkt_20d.json (harness runs),
  ml/results/preds/audit/*.parquet
Run:  cd /home/user/SuryaDhana_AI && python3 -m ml.audit [--only T1,T2] [--fresh]
"""
from __future__ import annotations

import os

os.environ["OMP_NUM_THREADS"] = "2"  # must precede numpy/sklearn/lightgbm
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")

import argparse
import json
import math
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb
from scipy import stats
from scipy.signal import lfilter
from sklearn.metrics import roc_auc_score

import ml.evaluation as ev

# The league aggregator globs ml/results/*.json -- the audit writes only to its
# own folders. save_results/save_preds read these module globals at call time.
ev.RESULTS_DIR = ev.ML_DIR / "results" / "audit"
ev.PREDS_DIR = ev.ML_DIR / "results" / "preds" / "audit"

ML_DIR = ev.ML_DIR
RES = ML_DIR / "results"
AUDIT_DIR = ev.RESULTS_DIR
CACHE_DIR = AUDIT_DIR / "cache"
DATA_DIR = ev.DATA_DIR
SEED = 108
PRIMARY = "beat_mkt_20d"
LABEL, FWD, CLEAN = ev.TASKS[PRIMARY]
FWD_SESSIONS = 20          # label = open[t+1] -> open[t+21]
EMBARGO = 22
SPLIT_MOVE = 0.22
MIN_PRICE, MIN_MED_TURN, DATASET_START = 10.0, 1e7, "2025-06-01"
N_PERM = 10
K_GRID = (5, 10, 15, 20, 30)
INNER_LEN = 21             # sessions per inner validation block (T11)

LGBM_PARAMS = dict(num_leaves=63, learning_rate=0.05, n_estimators=300,
                   feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1,
                   min_data_in_leaf=200, num_threads=2, random_state=SEED,
                   verbose=-1)

CHAMP_CLEAN_JSON = RES / "lgbm_fs_selected_clean__beat_mkt_20d.json"
CHAMP_FROZEN_JSON = RES / "lgbm_fs_selected__beat_mkt_20d.json"
PHANTOM_DAYS = json.loads((RES / "holiday_duplicates.json").read_text())["phantom_days"]
AUX_FILES = {"data_profile.json", "feature_selection.json", "holiday_duplicates.json",
             "lr_coefficients.json", "tree_importances.json", "model_selection.json"}

T_START = time.time()


# =========================================================================== #
# helpers
# =========================================================================== #
def log(msg: str) -> None:
    print(f"[audit +{time.time() - T_START:6.0f}s] {msg}", flush=True)


def _json_default(o):
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


def cached(key: str, fn, fresh: bool = False):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = CACHE_DIR / f"{key}.json"
    if p.exists() and not fresh:
        return json.loads(p.read_text())
    out = fn()
    p.write_text(json.dumps(out, indent=1, default=_json_default))
    return json.loads(p.read_text())


def verdict(tid: str, name: str, status: str, msg: str, **numbers) -> dict:
    print(f"[{tid}] {status:4s} | {name} | {msg}", flush=True)
    return {"id": tid, "name": name, "status": status, "summary": msg, **numbers}


def make_lgbm(task=None):
    return lgb.LGBMClassifier(**LGBM_PARAMS)


def slim(df: pd.DataFrame, feats, extra=()) -> pd.DataFrame:
    cols = list(dict.fromkeys(["date", "ticker", *feats, LABEL, FWD, CLEAN, *extra]))
    return df[cols].copy()


def summarize(p: dict) -> dict:
    return {"cv_auc_mean": p["cv_auc_mean"], "cv_auc_std": p["cv_auc_std"],
            "fold_aucs": {f["fold"]: f["auc"] for f in p["folds"]},
            "fold_n": {f["fold"]: f["n"] for f in p["folds"]},
            "fold_base_rate": {f["fold"]: f["base_rate"] for f in p["folds"]},
            "holdout_auc": p["holdout"]["auc"] if p["holdout"] else None,
            "holdout_n": p["holdout"]["n"] if p["holdout"] else None,
            "holdout_decile_spread": (p["holdout"] or {}).get("decile_spread"),
            "cv_decile_spreads": {f["fold"]: f.get("decile_spread") for f in p["folds"]},
            "seconds": p["train_seconds"]}


def harness(ctx, name: str, df: pd.DataFrame, feats, notes: str) -> dict:
    res = ev.run_standard_eval(
        model_name=name, family="audit", agent="red-team", make_model=make_lgbm,
        tasks=(PRIMARY,), preprocess="raw", feature_subset=list(feats),
        params=dict(LGBM_PARAMS), notes=notes, df=df, features=list(feats),
        splits=ctx.splits)
    return summarize(res[PRIMARY])


def task_mask(df: pd.DataFrame) -> np.ndarray:
    return (df[LABEL].notna() & df[CLEAN].astype(bool)).to_numpy()


def e_max_std_normal(n: int) -> float:
    """E[max of n iid N(0,1)] by numerical integration of n*x*phi*Phi^(n-1)."""
    if n <= 1:
        return 0.0
    x = np.linspace(-8, 8, 160001)
    f = n * x * stats.norm.pdf(x) * stats.norm.cdf(x) ** (n - 1)
    return float(np.trapezoid(f, x) if hasattr(np, "trapezoid") else np.trapz(f, x))


def fwd_max(x: pd.Series, a: int, b: int) -> pd.Series:
    """max(x[t+a .. t+b]) positional within one series (a>=1)."""
    w = b - a + 1
    rev = x.iloc[::-1].rolling(w, min_periods=1).max().iloc[::-1]
    return rev.shift(-a)


# =========================================================================== #
# context
# =========================================================================== #
class Ctx:
    def __init__(self):
        log("loading clean dataset via ml.evaluation.load_dataset()")
        self.df, self.features, self.splits = ev.load_dataset()
        d = self.df["date"].to_numpy()
        assert (d[1:] >= d[:-1]).all(), "dataset not date-sorted"
        self.cal = pd.DatetimeIndex(np.sort(self.df["date"].unique()))
        fsj = json.loads((RES / "feature_selection.json").read_text())
        self.champ = list(fsj["selected"]["features"])
        self.champ_json = json.loads(CHAMP_CLEAN_JSON.read_text())
        assert self.champ_json["feature_subset"] == self.champ
        self.real_cv = float(self.champ_json["cv_auc_mean"])
        self.real_ho = float(self.champ_json["holdout"]["auc"])
        self.real_folds = {f["fold"]: f["auc"] for f in self.champ_json["folds"]}
        self._snap = None
        self._snapm = None
        log(f"{len(self.df):,} rows, {len(self.features)} features, "
            f"champion={self.champ}, real clean CV={self.real_cv:.6f}")

    # raw snapshot, EQ/BE only, per-ticker derived columns ------------------
    @property
    def snap(self) -> pd.DataFrame:
        if self._snap is None:
            log("loading raw EOD snapshot (EQ/BE) + per-ticker recomputation")
            s = pd.read_parquet(DATA_DIR / "equity_eod_snapshot.parquet",
                                columns=["date", "ticker", "series", "prev_close", "open",
                                         "high", "low", "close", "volume", "turnover",
                                         "deliv_pct"])
            s = s[s["series"].isin(["EQ", "BE"])].copy()
            s["date"] = pd.to_datetime(s["date"]).astype(self.df["date"].dtype)
            s = s.sort_values(["ticker", "date"]).reset_index(drop=True)
            g = s.groupby("ticker", sort=False)
            s["entry_open"] = g["open"].shift(-1)
            s["exit_open"] = g["open"].shift(-(FWD_SESSIONS + 1))
            s["entry_date"] = g["date"].shift(-1)
            s["exit_date"] = g["date"].shift(-(FWD_SESSIONS + 1))
            s["y_raw_re"] = s["exit_open"] / s["entry_open"] - 1
            s["span_days"] = (s["exit_date"] - s["entry_date"]).dt.days
            s["ret_1d_re"] = g["close"].pct_change()
            absret = s["ret_1d_re"].abs()
            s["fwd_absmax_re"] = absret.groupby(s["ticker"], sort=False).transform(
                lambda x: fwd_max(x, 1, FWD_SESSIONS + 1))
            s["y_clean_re"] = (s["y_raw_re"].notna() & (s["entry_open"] > 0)
                               & (s["exit_open"] > 0) & (s["span_days"] <= 45)
                               & (s["fwd_absmax_re"] <= SPLIT_MOVE))
            s["med_turn_re"] = g["turnover"].transform(
                lambda x: x.rolling(20, min_periods=10).median())
            self._snap = s
        return self._snap

    @property
    def snapm(self) -> pd.DataFrame:
        """Snapshot-derived columns aligned row-for-row to the dataset."""
        if self._snapm is None:
            s = self.snap
            cols = ["date", "ticker", "entry_open", "exit_open", "entry_date", "exit_date",
                    "y_raw_re", "span_days", "fwd_absmax_re", "y_clean_re", "med_turn_re",
                    "close", "turnover"]
            m = self.df[["date", "ticker"]].merge(s[cols], on=["date", "ticker"],
                                                  how="left", validate="one_to_one")
            assert len(m) == len(self.df)
            self._snapm = m
        return self._snapm


# =========================================================================== #
# T0  reproduction
# =========================================================================== #
def t0(ctx, fresh):
    r = cached("T0_repro", lambda: harness(
        ctx, "audit_champion_repro", slim(ctx.df, ctx.champ), ctx.champ,
        "T0: reproduction of lgbm_fs_selected_clean (champion config, clean data)"), fresh)
    d_cv = r["cv_auc_mean"] - ctx.real_cv
    d_ho = r["holdout_auc"] - ctx.real_ho
    st = "PASS" if abs(d_cv) < 1e-6 and abs(d_ho) < 1e-6 else ("INFO" if abs(d_cv) < 2e-3 else "FAIL")
    return verdict("T0", "champion reproduction", st,
                   f"repro CV {r['cv_auc_mean']:.6f} vs JSON {ctx.real_cv:.6f} (d={d_cv:+.2e}); "
                   f"holdout {r['holdout_auc']:.6f} vs {ctx.real_ho:.6f} (d={d_ho:+.2e})",
                   repro=r, json_cv=ctx.real_cv, json_holdout=ctx.real_ho,
                   delta_cv=d_cv, delta_holdout=d_ho)


# =========================================================================== #
# T1  label-permutation null (within date)
# =========================================================================== #
def permute_within_date(d: pd.DataFrame, seed: int) -> pd.DataFrame:
    """Shuffle (label, fwd) jointly among the task-frame rows of each date:
    per-date base rate and the row set are preserved, feature-label link gone."""
    rng = np.random.default_rng(seed)
    idx = np.flatnonzero(task_mask(d))
    dts = d["date"].to_numpy()[idx]
    assert (dts[1:] >= dts[:-1]).all()
    order = np.lexsort((rng.random(len(idx)), dts))
    src = idx[order]
    assert (d["date"].to_numpy()[src] == dts).all()
    out = d.copy()
    for c in (LABEL, FWD):
        v = d[c].to_numpy().copy()
        v[idx] = d[c].to_numpy()[src]
        out[c] = v
    br0 = d.iloc[idx].groupby("date")[LABEL].mean()
    br1 = out.iloc[idx].groupby("date")[LABEL].mean()
    assert np.allclose(br0.to_numpy(), br1.to_numpy())
    return out


def t1(ctx, fresh):
    base = slim(ctx.df, ctx.champ)
    perms = []
    for i in range(N_PERM):
        seed = SEED + i
        perms.append(cached(f"T1_perm{i:02d}", lambda seed=seed, i=i: {
            "seed": seed, **harness(ctx, f"audit_perm{i:02d}", permute_within_date(base, seed),
                                    ctx.champ, f"T1 within-date label permutation, seed {seed}")},
            fresh))
        log(f"T1 perm {i}: cv={perms[-1]['cv_auc_mean']:.4f} ho={perms[-1]['holdout_auc']:.4f}")
    cv = np.array([p["cv_auc_mean"] for p in perms])
    ho = np.array([p["holdout_auc"] for p in perms])
    folds = np.array([[p["fold_aucs"][k] for k in sorted(p["fold_aucs"])] for p in perms])
    m, sd, mx = float(cv.mean()), float(cv.std(ddof=1)), float(cv.max())
    hm, hsd, hmx = float(ho.mean()), float(ho.std(ddof=1)), float(ho.max())
    z = (ctx.real_cv - m) / sd
    zh = (ctx.real_ho - hm) / hsd
    # analytic iid AUC sd under H0 per fold: sqrt((n1+n0+1)/(12 n1 n0))
    an = []
    for k, n in perms[0]["fold_n"].items():
        p_ = perms[0]["fold_base_rate"][k]
        n1, n0 = n * p_, n * (1 - p_)
        an.append((n1 + n0 + 1) / (12 * n1 * n0))
    an_cv_sd = float(math.sqrt(sum(an)) / len(an))
    passed = ctx.real_cv > mx and ctx.real_cv > m + 3 * sd
    return verdict(
        "T1", "label-permutation null (within-date, 10 perms)", "PASS" if passed else "FAIL",
        f"null CV mean {m:.4f} sd {sd:.4f} max {mx:.4f}; champion {ctx.real_cv:.4f} -> z={z:.1f}; "
        f"null holdout mean {hm:.4f} sd {hsd:.4f} max {hmx:.4f}; champion holdout {ctx.real_ho:.4f} -> z={zh:.1f}",
        null_cv={"mean": m, "sd": sd, "max": mx, "min": float(cv.min()), "values": cv.tolist()},
        null_holdout={"mean": hm, "sd": hsd, "max": hmx, "values": ho.tolist()},
        null_fold_auc_sd=float(folds.std(ddof=1)),
        analytic_iid_cv_mean_sd=an_cv_sd,
        champion_cv=ctx.real_cv, champion_holdout=ctx.real_ho, z_cv=z, z_holdout=zh,
        caveat=("within-date permutation also destroys the cross-sectional factor structure and "
                "the 20-day overlap persistence of labels, so its sd is close to the iid floor; it "
                "rules out 'AUC produced by fitting noise', NOT regime luck or selection bias"),
        perms=perms)


# =========================================================================== #
# T2  leak-detector sensitivity
# =========================================================================== #
def t2(ctx, fresh):
    out = {}
    for k in (1, 5, 21):
        def run(k=k):
            d = slim(ctx.df, ctx.champ)
            d[ctx.champ] = d.groupby("ticker", sort=False)[ctx.champ].shift(-k)
            return harness(ctx, f"audit_leak_shift_m{k}", d, ctx.champ,
                           f"T2 deliberate leak: champion features shifted -{k} rows within ticker")
        out[f"shift_-{k}"] = cached(f"T2_shift_m{k}", run, fresh)
    r1 = out["shift_-1"]
    st = "INFO"
    msg = (f"features(t+1): CV {r1['cv_auc_mean']:.4f} (holdout {r1['holdout_auc']:.4f}) vs real "
           f"{ctx.real_cv:.4f}; t+5: CV {out['shift_-5']['cv_auc_mean']:.4f}; t+21: CV "
           f"{out['shift_-21']['cv_auc_mean']:.4f} -> harness "
           + ("DETECTS a 1-session leak (>0.55)" if r1["cv_auc_mean"] > 0.55
              else "rises with leak size (1-session leak alone stays <0.55)"))
    return verdict("T2", "leak-detector sensitivity", st, msg, runs=out, real_cv=ctx.real_cv)


# =========================================================================== #
# T3  embargo verification
# =========================================================================== #
def t3(ctx, fresh):
    df, sm, cal = ctx.df, ctx.snapm, ctx.cal
    tm = task_mask(df)
    dates = df["date"].to_numpy()
    exit_d = sm["exit_date"].to_numpy(dtype="datetime64[ns]")
    rows, total_viol, total_overlap = [], 0, 0
    specs = ctx.splits["folds"] + [ctx.splits["holdout"]]
    for spec in specs:
        tr_end, te_start = pd.Timestamp(spec["train_end"]), pd.Timestamp(spec["test_start"])
        p_tr, p_te = cal.get_loc(tr_end), cal.get_loc(te_start)
        cal_exit = cal[p_tr + FWD_SESSIONS + 1]
        m = tm & (dates <= np.datetime64(tr_end))
        ex = exit_d[m]
        nat = int(np.isnat(ex).sum())
        viol = int((ex >= np.datetime64(te_start)).sum())
        overlap = int((ex > np.datetime64(te_start)).sum())
        total_viol += viol
        total_overlap += overlap
        bad = df.loc[m].assign(exit_date=ex)
        bad = bad[bad["exit_date"] >= te_start]
        rows.append({
            "fold": spec["name"], "train_end": spec["train_end"], "test_start": spec["test_start"],
            "embargo_sessions_in_calendar": int(p_te - p_tr),
            "last_train_calendar_exit": str(cal_exit.date()),
            "calendar_ok": bool(cal_exit < te_start),
            "n_train_rows": int(m.sum()), "n_missing_exit": nat,
            "max_actual_exit_date": str(pd.Timestamp(ex[~np.isnat(ex)].max()).date()),
            "n_rows_exit_on_or_after_test_start": viol,
            "n_rows_exit_after_test_start": overlap,
            "violating_tickers": sorted(bad["ticker"].unique().tolist())[:20],
        })
    # label horizon measured on the MARKET calendar: rows whose ticker-session
    # window (21 own rows) spans more than 21 market sessions (illiquid names)
    cpos = pd.Series(np.arange(len(cal)), index=cal)
    have = (~np.isnat(exit_d)) & tm
    p_t = cpos.reindex(pd.DatetimeIndex(dates[have])).to_numpy()
    p_x = cpos.reindex(pd.DatetimeIndex(exit_d[have])).to_numpy()
    horizon = p_x - p_t
    n_long = int((horizon > FWD_SESSIONS + 1).sum())
    long_info = {"task_rows_with_exit": int(have.sum()),
                 "rows_horizon_gt_21_market_sessions": n_long,
                 "share": n_long / max(int(have.sum()), 1),
                 "max_horizon_market_sessions": int(np.nanmax(horizon))}
    # disjoint test windows + holdout
    wins = sorted((pd.Timestamp(s["test_start"]), pd.Timestamp(s["test_end"]), s["name"]) for s in specs)
    disjoint = all(wins[i][1] < wins[i + 1][0] for i in range(len(wins) - 1))
    last_lab = pd.Timestamp(df.loc[df[LABEL].notna(), "date"].max())
    ends_ok = all(pd.Timestamp(s["test_end"]) <= last_lab for s in specs)
    cal_ok = all(r["calendar_ok"] for r in rows)
    ntr = sum(r["n_train_rows"] for r in rows)
    st = "PASS" if (cal_ok and total_viol == 0 and disjoint and ends_ok) else "FAIL"
    msg = (f"calendar embargo ok in {sum(r['calendar_ok'] for r in rows)}/{len(rows)} windows "
           f"(gap {[r['embargo_sessions_in_calendar'] for r in rows]} sessions); per-row actual "
           f"exit >= test_start: {total_viol} of {ntr:,} train rows ({total_overlap} strictly after); "
           f"test windows disjoint={disjoint}")
    msg += (f"; labels spanning >21 market sessions (ticker-row horizon, illiquid names): "
            f"{n_long:,} rows ({100 * long_info['share']:.2f}%), max {long_info['max_horizon_market_sessions']}")
    return verdict("T3", "embargo verification", st, msg, folds=rows, label_horizon=long_info,
                   violating_rows=total_viol, violating_rows_strict=total_overlap,
                   test_windows_disjoint=disjoint, test_end_le_last_labeled=ends_ok)


# =========================================================================== #
# T4  label construction recompute
# =========================================================================== #
def t4(ctx, fresh):
    df, sm, s = ctx.df, ctx.snapm, ctx.snap
    have = df["y_raw_20d"].notna().to_numpy()
    rng = np.random.default_rng(SEED)
    idx = rng.choice(np.flatnonzero(have), 300, replace=False)
    # independent row-wise recompute for the 300 sample
    by_t = {t: g for t, g in s.groupby("ticker", sort=False)[["date", "open"]]}
    y300 = []
    for i in idx:
        tk, dt = df.at[i, "ticker"], df.at[i, "date"]
        g = by_t[tk]
        dv = g["date"].to_numpy()
        pos = int(np.searchsorted(dv, np.datetime64(dt)))
        assert dv[pos] == np.datetime64(dt)
        op = g["open"].to_numpy()
        y300.append(op[pos + 21] / op[pos + 1] - 1 if pos + 21 < len(op) else np.nan)
    y300 = np.array(y300)
    d300 = np.abs(y300 - df["y_raw_20d"].to_numpy()[idx])
    max300 = float(np.nanmax(d300))
    nan300 = int(np.isnan(d300).sum())
    # full vectorized recompute
    yr = sm["y_raw_re"].to_numpy()
    yd = df["y_raw_20d"].to_numpy()
    both = np.isfinite(yr) & np.isfinite(yd)
    full_max = float(np.max(np.abs(yr[both] - yd[both])))
    nan_mis = int((np.isfinite(yr) != np.isfinite(yd)).sum())
    # excess / label
    med = pd.Series(yr).groupby(df["date"].to_numpy()).transform("median").to_numpy()
    yex = yr - med
    lab = np.where(np.isfinite(yex), (yex > 0).astype(float), np.nan)
    ex_d = df["y_excess_20d"].to_numpy()
    ok = np.isfinite(yex) & np.isfinite(ex_d)
    ex_max = float(np.max(np.abs(yex[ok] - ex_d[ok])))
    lab_d = df[LABEL].to_numpy()
    okl = np.isfinite(lab) & np.isfinite(lab_d)
    lab_mis = int((lab[okl] != lab_d[okl]).sum()) + int((np.isfinite(lab) != np.isfinite(lab_d)).sum())
    lab_mis300 = int(np.nansum(lab[idx] != lab_d[idx]))
    ex_max300 = float(np.nanmax(np.abs(yex[idx] - ex_d[idx])))
    # y_clean recompute
    yc = sm["y_clean_re"].fillna(False).to_numpy().astype(bool)
    yc_mis = int((yc != df[CLEAN].to_numpy().astype(bool)).sum())
    passed = max300 < 1e-9 and nan300 == 0 and lab_mis300 == 0 and lab_mis == 0 and full_max < 1e-9
    return verdict(
        "T4", "label construction recompute", "PASS" if passed else "FAIL",
        f"300-row y_raw max|diff|={max300:.2e} (NaN mismatches {nan300}); full {both.sum():,} rows "
        f"max|diff|={full_max:.2e}, NaN mismatches {nan_mis}; y_excess max|diff|={ex_max:.2e}; "
        f"label mismatches 300-row={lab_mis300}, full={lab_mis}; y_clean mismatches={yc_mis}",
        sample_n=300, sample_max_abs_diff=max300, sample_nan_mismatch=nan300,
        sample_label_mismatch=lab_mis300, sample_excess_max_abs_diff=ex_max300,
        full_rows_compared=int(both.sum()), full_max_abs_diff=full_max, full_nan_mismatch=nan_mis,
        full_excess_max_abs_diff=ex_max, full_label_mismatch=lab_mis, y_clean_mismatch=yc_mis)


# =========================================================================== #
# T5  point-in-time checks
# =========================================================================== #
def _trunc_feats(h: pd.DataFrame) -> dict:
    """Champion per-ticker features at the LAST row of a truncated history h
    (rows date <= t, EQ/BE, sorted) -- same formulas as build_features/data.py."""
    c, hi, lo = h["close"], h["high"], h["low"]
    pc = c.shift(1)
    tr = pd.concat([hi - lo, (hi - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    hi252 = hi.rolling(252, min_periods=20).max()
    ret = c.pct_change()
    return {
        "atr_pct": (atr / c).iloc[-1],
        "deliv_pct": h["deliv_pct"].iloc[-1],
        "deliv_pct_sma_20": h["deliv_pct"].rolling(20).mean().iloc[-1],
        "dist_52w_high": (c / hi252 - 1).iloc[-1],
        "ret_63d": (c / c.shift(63) - 1).iloc[-1],
        "ret_126d": (c / c.shift(126) - 1).iloc[-1],
        "mom_12_1": (c.shift(21) / c.shift(252) - 1).iloc[-1],
        "mom_20": (c / c.shift(20) - 1).iloc[-1],
        "vol_20": ret.rolling(20).std().iloc[-1],
    }


def t5(ctx, fresh):
    df, sm, s = ctx.df, ctx.snapm, ctx.snap
    rng = np.random.default_rng(SEED)
    out = {}
    # (a) universe mask --------------------------------------------------
    src = Path(ML_DIR / "data.py").read_text()
    static_ok = ("rolling(20, min_periods=10).median()" in src
                 and re.search(r"med_turn\s*=.*shift\(-", src) is None)
    uni = s[(s["close"] >= MIN_PRICE) & (s["med_turn_re"] >= MIN_MED_TURN)
            & (s["date"] >= pd.Timestamp(DATASET_START))]
    re_set = pd.MultiIndex.from_frame(uni[["date", "ticker"]])
    ds_set = pd.MultiIndex.from_frame(df[["date", "ticker"]])
    n_ds_not_re = int((~ds_set.isin(re_set)).sum())
    n_re_not_ds = int((~re_set.isin(ds_set)).sum())
    by_t = {t: g for t, g in s.groupby("ticker", sort=False)}
    idx = rng.choice(len(df), 100, replace=False)
    a_bad = 0
    a_cases = []
    for i in idx:
        tk, dt = df.at[i, "ticker"], df.at[i, "date"]
        h = by_t[tk]
        h = h[h["date"] <= dt]
        med = h["turnover"].iloc[-20:].median() if len(h) >= 10 else np.nan
        close = h["close"].iloc[-1]
        ok = bool(np.isfinite(med) and med >= MIN_MED_TURN and close >= MIN_PRICE
                  and np.isclose(med, sm.at[i, "med_turn_re"], rtol=1e-12))
        a_bad += (not ok)
        if len(a_cases) < 5:
            a_cases.append({"ticker": tk, "date": str(dt.date()), "trailing_med_turnover": float(med),
                            "close": float(close), "ok": ok})
    out["a_universe"] = {"static_code_check_trailing_only": static_ok,
                         "dataset_rows_not_in_recomputed_universe": n_ds_not_re,
                         "recomputed_universe_rows_not_in_dataset": n_re_not_ds,
                         "sample100_truncated_recompute_failures": a_bad, "examples": a_cases}
    # (b) market-state features from rows with date <= t --------------------
    fe = pd.read_parquet(DATA_DIR / "model_dataset_fe.parquet",
                         columns=["date", "ticker", "mkt_ret_20", "mkt_breadth_200", "mkt_vol_20"])
    fe["date"] = pd.to_datetime(fe["date"])
    dates50 = np.sort(rng.choice(ctx.cal.to_numpy(), 50, replace=False))
    b_max = {"mkt_ret_20": 0.0, "mkt_breadth_200": 0.0, "mkt_vol_20": 0.0}
    b_nan_mis = 0
    for t in dates50:
        t = pd.Timestamp(t)
        tick = df.loc[df["date"] == t, "ticker"]
        sub = s[(s["date"] <= t) & s["ticker"].isin(set(tick))]
        sub = sub.groupby("ticker", sort=False).tail(260)
        g = sub.groupby("ticker", sort=False)
        c = sub["close"]
        mom20 = c / g["close"].shift(20) - 1
        ret = g["close"].pct_change()
        vol20 = ret.groupby(sub["ticker"], sort=False).transform(lambda x: x.rolling(20).std())
        sma = g["close"].transform(lambda x: x.rolling(200, min_periods=120).mean())
        dist = c / sma - 1
        last = (sub["date"] == t).to_numpy()
        dl = dist[last]
        rec = {"mkt_ret_20": float(np.nanmedian(mom20[last])),
               "mkt_breadth_200": float((dl[dl.notna()] > 0).mean()),
               "mkt_vol_20": float(np.nanmedian(vol20[last]))}
        stored = fe.loc[fe["date"] == t, list(rec)].iloc[0]
        assert fe.loc[fe["date"] == t, "mkt_ret_20"].nunique() <= 1
        for k, v in rec.items():
            sv = float(stored[k])
            if np.isfinite(v) != np.isfinite(sv):
                b_nan_mis += 1
            elif np.isfinite(v):
                b_max[k] = max(b_max[k], abs(v - sv))
    out["b_market_state"] = {"n_dates": 50, "max_abs_diff": b_max, "nan_mismatch": b_nan_mis}
    # (c) cs_rank_* same-date only ----------------------------------------
    cs_src = {"cs_rank_mom_20": "mom_20", "cs_rank_ret_126": "ret_126d",
              "cs_rank_vol_20": "vol_20", "cs_rank_turnover": "log_turnover",
              "cs_rank_deliv_z": "deliv_pct_z_20"}
    c_max = {}
    for dst, srcc in cs_src.items():
        # data.py ranks raw turnover (not in dataset); log1p is monotone -> same ranks
        r = df.groupby("date")[srcc].rank(pct=True).to_numpy()
        v = df[dst].to_numpy()
        okk = np.isfinite(r) & np.isfinite(v)
        c_max[dst] = float(np.max(np.abs(r[okk] - v[okk]))) if okk.any() else None
        c_max[dst + "_nan_mismatch"] = int((np.isfinite(r) != np.isfinite(v)).sum())
    # truncation demo: ranks recomputed on df[date <= t] for 10 dates
    trunc_bad = 0
    for t in np.sort(rng.choice(ctx.cal.to_numpy(), 10, replace=False)):
        part = df[df["date"] <= pd.Timestamp(t)]
        r = part[part["date"] == pd.Timestamp(t)]["mom_20"].rank(pct=True)
        v = part[part["date"] == pd.Timestamp(t)]["cs_rank_mom_20"]
        trunc_bad += int((~np.isclose(r, v, equal_nan=True)).sum())
    out["c_cs_rank"] = {"max_abs_diff": c_max, "truncated_recompute_mismatch_10dates": trunc_bad}
    # (d) champion features from truncated history (date <= t), 50 rows ----
    idx50 = rng.choice(len(df), 50, replace=False)
    d_bad, d_n, d_maxrel = 0, 0, 0.0
    d_cases = []
    for i in idx50:
        tk, dt = df.at[i, "ticker"], df.at[i, "date"]
        h = by_t[tk]
        h = h[h["date"] <= dt]
        rec = _trunc_feats(h)
        for f, v in rec.items():
            sv = df.at[i, f]
            d_n += 1
            same = bool(np.isclose(v, sv, rtol=1e-9, atol=1e-12, equal_nan=True))
            if not same:
                d_bad += 1
                if len(d_cases) < 8:
                    d_cases.append({"ticker": tk, "date": str(dt.date()), "feature": f,
                                    "stored": float(sv), "recomputed_leq_t": float(v)})
            elif np.isfinite(v) and abs(sv) > 0:
                d_maxrel = max(d_maxrel, abs(v - sv) / abs(sv))
    out["d_champion_features_truncated"] = {"n_rows": 50, "n_values": d_n, "mismatches": d_bad,
                                            "max_rel_diff": d_maxrel, "examples": d_cases}
    passed = (static_ok and n_ds_not_re == 0 and n_re_not_ds == 0 and a_bad == 0
              and max(b_max.values()) < 1e-9 and b_nan_mis == 0
              and all((v or 0) < 1e-9 for k, v in c_max.items() if not k.endswith("mismatch"))
              and all(v == 0 for k, v in c_max.items() if k.endswith("mismatch"))
              and trunc_bad == 0 and d_bad == 0)
    msg = (f"(a) universe recompute: {n_ds_not_re} dataset rows fail / {n_re_not_ds} missing, "
           f"100-row trailing recompute failures {a_bad}; (b) market-state max|diff| "
           f"{max(b_max.values()):.1e} over 50 dates; (c) cs_rank max|diff| "
           f"{max(v for k, v in c_max.items() if not k.endswith('mismatch')):.1e}; "
           f"(d) champion features from date<=t history: {d_bad}/{d_n} mismatches")
    return verdict("T5", "point-in-time checks", "PASS" if passed else "FAIL", msg, **out)


# =========================================================================== #
# T6  selection bias / random features
# =========================================================================== #
def _ar1_noise(df: pd.DataFrame, k: int, phi: float, seed: int) -> np.ndarray:
    """k independent per-ticker AR(1) series (stationary, unit variance) in
    each ticker's date order -- persistent like real characteristics."""
    rng = np.random.default_rng(seed)
    order = np.lexsort((df["date"].to_numpy(), df["ticker"].to_numpy()))
    tk = df["ticker"].to_numpy()[order]
    starts = np.flatnonzero(np.r_[True, tk[1:] != tk[:-1]])
    ends = np.r_[starts[1:], len(df)]
    e = rng.standard_normal((len(df), k))
    z = np.empty_like(e)
    c = math.sqrt(1 - phi ** 2)
    for a, b in zip(starts, ends):
        seg = e[a:b]
        z[a] = seg[0]
        if b - a > 1:
            z[a + 1:b] = lfilter([c], [1, -phi], seg[1:], axis=0, zi=phi * seg[0:1])[0]
    out = np.empty_like(z)
    out[order] = z
    return out


def _fs_score(d, feats, splits):
    import ml.feature_selection as fs
    fs.IMPORTANCE_FOLD = "2026-06"
    uni = fs.univariate_aucs(d, feats, splits)
    gain, perm, nperm = fs.model_importances(d, feats, splits)
    clusters, _ = fs.find_redundancy_clusters(d, feats)
    entries, order, _ = fs.combined_ranking(feats, uni, gain, perm, clusters)
    return uni, gain, perm, entries, order


def t6(ctx, fresh):
    df = ctx.df
    noise_names = [f"noise_{i:02d}" for i in range(30)]

    def part_a():  # champion 10 + 30 iid N(0,1)
        rng = np.random.default_rng(SEED)
        d = slim(df, ctx.champ)
        d[noise_names] = rng.standard_normal((len(d), 30))
        feats = ctx.champ + noise_names
        uni, gain, perm, entries, order = _fs_score(d, feats, ctx.splits)
        top10 = order[:10]
        nrank = [i + 1 for i, f in enumerate(order) if f.startswith("noise_")]
        h = harness(ctx, "audit_champ_plus_noise30", d, feats,
                    "T6: champion 10 + 30 iid N(0,1) noise features")
        return {"top10": top10, "n_noise_in_top10": sum(f.startswith("noise_") for f in top10),
                "best_noise_rank": min(nrank), "noise_ranks": nrank,
                "max_noise_univariate_auc": max(uni[f]["auc"] for f in noise_names),
                "min_champion_univariate_auc": min(uni[f]["auc"] for f in ctx.champ),
                "max_noise_perm": max(perm[f]["mean"] for f in noise_names),
                "noise_gain_pct_total": sum(gain[f]["gain_pct"] for f in noise_names),
                "order": order, "harness": h}

    def part_b():  # all 51 + 30 persistent AR(1) noise (phi=0.99)
        d = slim(df, ctx.features)
        pn = [f"pnoise_{i:02d}" for i in range(30)]
        d[pn] = _ar1_noise(d, 30, 0.99, SEED)
        feats = ctx.features + pn
        uni, gain, perm, entries, order = _fs_score(d, feats, ctx.splits)
        top10 = order[:10]
        real_order = [f for f in order if not f.startswith("pnoise_")]
        nrank = [i + 1 for i, f in enumerate(order) if f.startswith("pnoise_")]
        u_noise = sorted((uni[f]["auc"] for f in pn), reverse=True)
        u_champ = {f: uni[f]["auc"] for f in ctx.champ}
        n_beat_weakest_champ = sum(u > min(u_champ.values()) for u in u_noise)
        return {"top10": top10, "n_noise_in_top10": sum(f.startswith("pnoise_") for f in top10),
                "n_noise_in_top20": sum(f.startswith("pnoise_") for f in order[:20]),
                "best_noise_rank": min(nrank), "noise_ranks": nrank,
                "noise_univariate_auc": {"max": u_noise[0], "median": float(np.median(u_noise)),
                                         "values": u_noise},
                "champion_univariate_auc": u_champ,
                "n_noise_univariate_above_weakest_champion": n_beat_weakest_champ,
                "clean_data_top10_real_only": real_order[:10],
                "overlap_clean_top10_vs_champion": len(set(real_order[:10]) & set(ctx.champ)),
                "order": order}

    a = cached("T6a_iid_noise", part_a, fresh)
    b = cached("T6b_persistent_noise", part_b, fresh)
    delta = a["harness"]["cv_auc_mean"] - ctx.real_cv
    st = "PASS" if (a["n_noise_in_top10"] == 0 and delta <= 0.002) else "FAIL"
    msg = (f"iid noise: {a['n_noise_in_top10']}/30 in combined top-10 (best noise rank "
           f"{a['best_noise_rank']}); champion+30 noise CV {a['harness']['cv_auc_mean']:.4f} "
           f"(delta {delta:+.4f}). Persistent AR(1) noise vs all 51: {b['n_noise_in_top10']} in "
           f"top-10, {b['n_noise_in_top20']} in top-20, best rank {b['best_noise_rank']}; "
           f"{b['n_noise_univariate_above_weakest_champion']}/30 noise univariate AUCs exceed the "
           f"weakest champion feature; clean-data re-selection keeps "
           f"{b['overlap_clean_top10_vs_champion']}/10 champion features")
    return verdict("T6", "selection-bias / random-feature test", st, msg,
                   iid_noise=a, persistent_noise=b, harness_delta_cv=delta)


# =========================================================================== #
# T7  multiple-testing accounting
# =========================================================================== #
def t7(ctx, fresh, t1res=None):
    if t1res is None:
        t1res = json.loads((CACHE_DIR / "T1.json").read_text())
    mu0, sd0 = t1res["null_cv"]["mean"], t1res["null_cv"]["sd"]
    # enumerate evaluated configurations on the primary task
    full, other_task, extra_screens = [], [], {}
    for p in sorted(RES.rglob("*.json")):
        rel = p.relative_to(RES)
        if rel.parts[0] in ("audit", "preds") or p.name in AUX_FILES:
            continue
        try:
            d = json.loads(p.read_text())
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        if d.get("cv_auc_mean") is not None:
            (full if d.get("task") == PRIMARY else other_task).append(
                ("results/" + str(rel), d["cv_auc_mean"]))
        elif rel.parts[0] == "feature_sufficiency" and isinstance(d.get("new_features"), list):
            extra_screens["feature_sufficiency IC screen (new features)"] = len(d["new_features"])
    names = [n for n, _ in full]
    reruns = [n for n in names if n.endswith("_clean__beat_mkt_20d.json") or "champion_ref" in n]
    dups = [n for n in names if "lgbm_fs_top10__" in n]   # identical to lgbm_fs_selected
    n_full = len(full)
    n_distinct = n_full - len(reruns) - len(dups)
    screens = {"decision_tree grid (trees.py)": 8, "xgboost grid (trees.py)": 4,
               "lightgbm grid (trees.py)": 4, "random_forest grid (trees.py)": 6,
               "lr_l2 C grid (logistic.py)": 6, "lr_l1 C grid (logistic.py)": 4,
               "lr_elastic C screen (logistic.py, <=3)": 3, "mlp hidden x dropout (deep.py)": 4}
    n_screen = sum(screens.values())
    n_univ = len(ctx.features) + sum(extra_screens.values())
    Ns = {"distinct_full_protocol_primary": n_distinct,
          "plus_2fold_hparam_screens": n_distinct + n_screen,
          "plus_univariate_feature_screens": n_distinct + n_screen + n_univ}
    if other_task:
        Ns["plus_other_label_tasks"] = Ns["plus_univariate_feature_screens"] + len(other_task)
    target = ctx.real_cv
    # alternative null sds (beyond the permutation null) for context
    fa = np.array(list(ctx.real_folds.values()))
    league = [v for n, v in full if "lgbm_fs_selected" not in n and "lgbm_fs_top10" not in n
              and n not in reruns]
    sig = {"T1_within_date_permutation": sd0,
           "fold_to_fold_regime (champion fold sd/sqrt(4))": float(fa.std(ddof=1) / 2),
           "date_block_bootstrap (eval_aggregate clean CI/3.92)": (0.5399 - 0.5226) / 3.92,
           "cross_config_dispersion (sd of other primary CV AUCs)": float(np.std(league, ddof=1))}
    table = []
    for sname, s_ in sig.items():
        m0 = mu0 if sname.startswith("T1") else 0.5
        for nname, N in Ns.items():
            em = e_max_std_normal(N)
            z = (target - m0) / s_
            p1 = float(stats.norm.sf(z))
            p_any = float(-np.expm1(N * np.log1p(-p1))) if p1 > 0 else 0.0
            table.append({"null_sd_source": sname, "null_mean": m0, "null_sd": s_, "N_label": nname,
                          "N": N, "E_max_std_normal": em, "expected_best_of_N_null": m0 + s_ * em,
                          "z_champion": z, "p_single": p1, "p_at_least_one_reaches_champion": p_any})
    t1rows = [r for r in table if r["null_sd_source"].startswith("T1")]
    worst = max(t1rows, key=lambda r: r["p_at_least_one_reaches_champion"])
    distinguishable = worst["p_at_least_one_reaches_champion"] < 0.01
    league_sorted = sorted(league, reverse=True)
    msg = (f"N = {Ns}; T1 null (mu {mu0:.4f}, sd {sd0:.4f}): expected best-of-N "
           f"{worst['expected_best_of_N_null']:.4f} at N={worst['N']}, P(any >= {target:.4f}) "
           f"= {worst['p_at_least_one_reaches_champion']:.1e} -> "
           + ("distinguishable from best-of-N pure-noise" if distinguishable else "NOT distinguishable")
           + f"; but vs realistic regime/selection sd the margin shrinks (see table); "
             f"runner-up primary CV among other configs = {league_sorted[0]:.4f}")
    return verdict("T7", "multiple-testing accounting", "INFO", msg,
                   formula=("E[max_N] = mu0 + sd0 * E[max of N iid N(0,1)], E computed as "
                            "integral of N x phi(x) Phi(x)^(N-1) dx; P(at least one of N null trials "
                            ">= a) = 1 - Phi((a-mu0)/sd0)^N (independence assumed -> conservative "
                            "upper bound for positively correlated trials)"),
                   evaluated_primary_jsons=names, other_task_jsons=[n for n, _ in other_task],
                   n_reruns_not_counted=len(reruns), n_duplicates_not_counted=len(dups),
                   hparam_screens=screens, univariate_screens=n_univ, extra_screens=extra_screens, N=Ns, null_sd_alternatives=sig, table=table,
                   distinguishable_from_T1_best_of_N=distinguishable,
                   other_configs_primary_cv_sorted=league_sorted)


# =========================================================================== #
# T8  duplicates & integrity
# =========================================================================== #
def _harness_test_rows(ctx) -> pd.DataFrame:
    tdf = ctx.df[task_mask(ctx.df)]
    parts = []
    for spec in ctx.splits["folds"] + [ctx.splits["holdout"]]:
        te = tdf[(tdf["date"] >= spec["test_start"]) & (tdf["date"] <= spec["test_end"])]
        parts.append(te[["date", "ticker", LABEL]].assign(fold=spec["name"]))
    return pd.concat(parts, ignore_index=True)


def t8(ctx, fresh):
    df, s = ctx.df, ctx.snap
    ds_dup = int(df.duplicated(["date", "ticker"]).sum())
    snap_dup = int(s.duplicated(["date", "ticker"]).sum())
    # phantom / echo-day scan on the raw snapshot: share of tickers whose
    # OHLC+volume equal their previous row
    g = s.groupby("ticker", sort=False)
    same = np.ones(len(s), dtype=bool)
    for c in ("open", "high", "low", "close", "volume"):
        same &= (s[c].to_numpy() == g[c].shift(1).to_numpy())
    echo = pd.Series(same).groupby(s["date"].to_numpy()).mean()
    max_echo_date, max_echo = str(pd.Timestamp(echo.idxmax()).date()), float(echo.max())
    phantom_in_data = [d for d in PHANTOM_DAYS if pd.Timestamp(d) in set(ctx.cal)]
    ref = _harness_test_rows(ctx)
    ref_key = pd.MultiIndex.from_frame(ref[["date", "ticker", "fold"]])
    preds = []
    files = sorted((RES / "preds").glob("*.parquet")) + sorted((RES / "preds" / "feature_study").glob("*.parquet"))
    for p in files:
        pr = pd.read_parquet(p)
        pr["date"] = pd.to_datetime(pr["date"]).astype(df["date"].dtype)
        dup = int(pr.duplicated(["date", "ticker"]).sum())
        multi_fold = int(pr.groupby(["date", "ticker"])["fold"].nunique().gt(1).sum())
        ph = int(pr["date"].isin(pd.to_datetime(PHANTOM_DAYS)).sum())
        rec = {"file": str(p.relative_to(RES)), "rows": len(pr), "dup_date_ticker": dup,
               "rows_in_two_folds": multi_fold, "rows_on_phantom_days": ph,
               "era": "pre-fix (frozen)" if ph > 0 else "clean"}
        if "__beat_mkt_20d" in p.name and ph == 0:
            k = pd.MultiIndex.from_frame(pr[["date", "ticker", "fold"]])
            rec["missing_vs_harness"] = int((~ref_key.isin(k)).sum())
            rec["extra_vs_harness"] = int((~k.isin(ref_key)).sum())
            mg = pr.merge(ref, on=["date", "ticker", "fold"], how="inner")
            rec["y_mismatch_vs_dataset"] = int((mg["y"].to_numpy() != mg[LABEL].to_numpy()).sum())
            rec["covers_exactly"] = (rec["missing_vs_harness"] == 0 and rec["extra_vs_harness"] == 0
                                     and rec["y_mismatch_vs_dataset"] == 0)
        preds.append(rec)
    clean_primary = [r for r in preds if "covers_exactly" in r]
    ok = (ds_dup == 0 and snap_dup == 0 and all(r["dup_date_ticker"] == 0 for r in preds)
          and all(r["rows_in_two_folds"] == 0 for r in preds)
          and all(r["covers_exactly"] for r in clean_primary) and not phantom_in_data
          and max_echo < 0.5)
    msg = (f"dataset dup (date,ticker)={ds_dup}; snapshot dup={snap_dup}; preds files with dups="
           f"{sum(r['dup_date_ticker'] > 0 for r in preds)}/{len(preds)}, rows in 2 folds="
           f"{sum(r['rows_in_two_folds'] for r in preds)}; clean primary preds covering harness rows "
           f"exactly: {sum(r['covers_exactly'] for r in clean_primary)}/{len(clean_primary)}; "
           f"phantom days in clean data={len(phantom_in_data)}; max echo share {max_echo:.3f} "
           f"({max_echo_date}); pre-fix preds still contain phantom-day rows: "
           f"{sum(r['rows_on_phantom_days'] > 0 for r in preds)} files")
    return verdict("T8", "duplicates & integrity", "PASS" if ok else "FAIL", msg,
                   dataset_dup=ds_dup, snapshot_dup=snap_dup, preds=preds,
                   phantom_days_in_clean_calendar=phantom_in_data,
                   max_echo_share=max_echo, max_echo_date=max_echo_date,
                   n_harness_test_rows=len(ref))


# =========================================================================== #
# T9  holdout-once check
# =========================================================================== #
def t9(ctx, fresh):
    files = sorted((ML_DIR / "models").glob("*.py")) + [ML_DIR / "feature_selection.py",
                                                        ML_DIR / "feature_ab.py"]
    hits = []
    for p in files:
        for ln, line in enumerate(p.read_text().splitlines(), 1):
            if "holdout" in line.lower():
                hits.append({"file": str(p.relative_to(ML_DIR.parent)), "line": ln,
                             "text": line.strip()[:160]})
    # classified findings (manual review of every hit + the selection paths)
    findings = [
        {"where": "models/trees.py screen(), models/logistic.py screen_C(), models/deep.py screen_mlp()",
         "use": "hyper-parameter choice on CV folds 2026-04/05 only; logistic asserts no holdout fold",
         "holdout_in_selection": False},
        {"where": "models/trees.py write_gain_importances(), models/logistic.py coefficient dump",
         "use": "refit on the holdout fold's TRAIN window (date <= 2026-07-02) for reporting only; "
                "no holdout test labels", "holdout_in_selection": False},
        {"where": "feature_selection.py",
         "use": "univariate screen skips holdout; k chosen on cv_auc_mean only. BUT every selection "
                "signal (univariate AUC on the 4 CV TEST folds, permutation importance on fold "
                "2026-06 TEST rows, k by CV AUC) uses the same CV test rows that later report the "
                "champion's CV AUC -> the CV number is in-sample for feature selection",
         "holdout_in_selection": False, "cv_test_in_selection": True},
        {"where": "feature_ab.py TOP8_NEW (lgbm_fe_top18)",
         "use": "the 8 'new' features = top-8 by |quick_ic| from features_ext._quick_ic, computed over "
                "ALL labelled dates incl. the holdout window Aug-Sep 2026 (and the CV test months)",
         "holdout_in_selection": True},
        {"where": "ml/MODEL_SELECTION.md / eval_aggregate adjudication",
         "use": "after seeing that 12/13 models scored higher on the holdout, the memo chose to "
                "discount the holdout as a 'friendly window' and adjudicate on CV -- a human selection "
                "decision taken with holdout results in view (the holdout favoured other models)",
         "holdout_in_selection": True},
    ]
    n_code = sum(f["holdout_in_selection"] for f in findings[:4])
    st = "FAIL" if n_code else "PASS"
    msg = (f"{len(hits)} 'holdout' lines grepped in models/*.py, feature_selection.py, feature_ab.py; "
           f"model tuning paths are clean (CV folds 1-2 only); holdout labels entered a selection in "
           f"{n_code} code path (feature_ab TOP8 via all-dates quick_ic) + 1 memo-level adjudication; "
           f"champion feature selection used CV TEST folds (CV AUC is in-sample for selection)")
    return verdict("T9", "holdout-once check", st, msg, grep_hits=hits, findings=findings)


# =========================================================================== #
# T10 preds sanity
# =========================================================================== #
def t10(ctx, fresh):
    out = {}
    worst = 0.0
    for tag, jp, pp in (("clean", CHAMP_CLEAN_JSON, RES / "preds" / "lgbm_fs_selected_clean__beat_mkt_20d.parquet"),
                        ("frozen", CHAMP_FROZEN_JSON, RES / "preds" / "lgbm_fs_selected__beat_mkt_20d.parquet")):
        j = json.loads(jp.read_text())
        pr = pd.read_parquet(pp)
        jf = {f["fold"]: f for f in j["folds"]}
        jf["holdout"] = j["holdout"]
        rows = {}
        for fold, g in pr.groupby("fold"):
            auc = float(roc_auc_score(g["y"], g["score"]))
            m = ev.compute_metrics(g["y"].to_numpy(), g["score"].to_numpy(), g["fwd"].to_numpy())
            d = abs(auc - jf[fold]["auc"])
            worst = max(worst, d)
            rows[fold] = {"auc_from_parquet": auc, "auc_json": jf[fold]["auc"], "abs_diff": d,
                          "base_rate": float(g["y"].mean()), "n": len(g),
                          "decile_spread_parquet": m.get("decile_spread"),
                          "decile_spread_json": jf[fold].get("decile_spread")}
        out[tag] = rows
    br = [r["base_rate"] for t in out.values() for r in t.values()]
    ok = worst < 1e-6 and all(abs(b - 0.5) < 0.01 for b in br)
    ho = out["clean"]["holdout"]
    msg = (f"clean champion holdout AUC from parquet {ho['auc_from_parquet']:.6f} vs JSON "
           f"{ho['auc_json']:.6f} (max |diff| over all folds, both runs = {worst:.1e}); "
           f"per-fold base rates {min(br):.4f}-{max(br):.4f}")
    return verdict("T10", "preds sanity", "PASS" if ok else "FAIL", msg, runs=out,
                   max_abs_diff=worst, base_rate_range=[min(br), max(br)])


# =========================================================================== #
# T11 honest nested feature selection
# =========================================================================== #
def _fit_score(d, feats, spec_splits):
    out = []
    for fold in ev.iter_folds(d, feats, spec_splits, PRIMARY, "raw", list(feats)):
        est = make_lgbm()
        est.fit(fold.X_train, fold.y_train)
        sc = est.predict_proba(fold.X_test)[:, 1]
        m = ev.compute_metrics(fold.y_test, sc, fold.fwd_test)
        out.append((fold.name, m))
    return out


def t11(ctx, fresh):
    import ml.feature_selection as fs
    df, feats, cal = ctx.df, ctx.features, ctx.cal
    specs = ctx.splits["folds"] + [ctx.splits["holdout"]]
    per = []
    for spec in specs:
        def run(spec=spec):
            t0 = time.time()
            tr_end = pd.Timestamp(spec["train_end"])
            dtr = df[df["date"] <= tr_end]
            tc = cal[cal <= tr_end]
            n = len(tc)
            inner = []
            for j, back in enumerate((1, 0)):
                v_end = n - 1 - back * INNER_LEN
                v_start = v_end - INNER_LEN + 1
                it_end = v_start - EMBARGO
                inner.append({"name": f"inner{j}", "train_end": str(tc[it_end].date()),
                              "test_start": str(tc[v_start].date()), "test_end": str(tc[v_end].date())})
            dummy = {"name": "holdout", "train_end": inner[0]["train_end"],
                     "test_start": "2100-01-01", "test_end": "2000-01-01"}
            isp = {"folds": inner, "holdout": dummy}
            uni = fs.univariate_aucs(dtr, feats, isp)
            fs.IMPORTANCE_FOLD = "inner1"
            gain, perm, _ = fs.model_importances(dtr, feats, isp)
            clusters, _ = fs.find_redundancy_clusters(dtr, feats)
            _, order, _ = fs.combined_ranking(feats, uni, gain, perm, clusters)
            kc = {}
            for k in K_GRID:
                res = _fit_score(slim(dtr, order[:k]), order[:k], isp)
                kc[k] = float(np.mean([m["auc"] for _, m in res]))
            best = max(kc.values())
            k_sel = min(k for k, v in kc.items() if v >= best - 0.002)
            one = ({"folds": [], "holdout": spec} if spec["name"] == "holdout"
                   else {"folds": [spec], "holdout": {**dummy, "train_end": spec["train_end"]}})
            outer = {}
            for k in sorted({10, k_sel}):
                (name, m), = _fit_score(slim(df, order[:k]), order[:k], one)
                outer[str(k)] = {"auc": m["auc"], "decile_spread": m.get("decile_spread"),
                                 "features": order[:k]}
            log(f"T11 {spec['name']}: inner k-curve {kc} -> k={k_sel}; outer AUC k=10 "
                f"{outer['10']['auc']:.4f}, k_sel {outer[str(k_sel)]['auc']:.4f} ({time.time()-t0:.0f}s)")
            return {"fold": spec["name"], "inner_splits": inner, "selection_order": order,
                    "inner_k_curve": kc, "k_selected": k_sel, "outer": outer,
                    "overlap_top10_with_champion": len(set(order[:10]) & set(ctx.champ)),
                    "seconds": time.time() - t0}
        per.append(cached(f"T11_{spec['name']}", run, fresh))
    cvf = [p for p in per if p["fold"] != "holdout"]
    hof = next(p for p in per if p["fold"] == "holdout")
    cv10 = float(np.mean([p["outer"]["10"]["auc"] for p in cvf]))
    cvk = float(np.mean([p["outer"][str(p["k_selected"])]["auc"] for p in cvf]))
    ho10 = hof["outer"]["10"]["auc"]
    hok = hof["outer"][str(hof["k_selected"])]["auc"]
    fold10 = {p["fold"]: p["outer"]["10"]["auc"] for p in per}
    foldk = {p["fold"]: p["outer"][str(p["k_selected"])]["auc"] for p in per}
    gap = ctx.real_cv - cvk
    st = "INFO"
    msg = (f"selection re-done per fold on pre-fold data only: CV AUC {cvk:.4f} (inner-chosen k) / "
           f"{cv10:.4f} (k fixed at 10) vs claimed {ctx.real_cv:.4f} -> selection optimism "
           f"{gap:+.4f}; holdout {hok:.4f} / {ho10:.4f}; folds<0.50 (inner k): "
           f"{sum(v < 0.5 for v in foldk.values())}/5; champion-feature overlap per fold "
           f"{[p['overlap_top10_with_champion'] for p in per]}")
    return verdict("T11", "honest nested feature selection", st, msg, per_fold=per,
                   cv_auc_inner_k=cvk, cv_auc_k10=cv10, holdout_auc_inner_k=hok,
                   holdout_auc_k10=ho10, fold_aucs_inner_k=foldk, fold_aucs_k10=fold10,
                   selection_optimism_cv=gap, claimed_cv=ctx.real_cv)


# =========================================================================== #
# T12 random 10-feature subsets
# =========================================================================== #
def t12(ctx, fresh, n_sub=8):
    pool = [f for f in ctx.features if not f.endswith("_isnan")]
    rng = np.random.default_rng(SEED)
    subs = [sorted(rng.choice(pool, 10, replace=False).tolist()) for _ in range(n_sub)]
    runs = []
    for i, sub in enumerate(subs):
        runs.append(cached(f"T12_sub{i:02d}", lambda sub=sub, i=i: {
            "features": sub, **harness(ctx, f"audit_rand10_{i:02d}", slim(ctx.df, sub), sub,
                                       "T12 random 10-feature subset of the 40 value features")},
            fresh))
        log(f"T12 subset {i}: cv={runs[-1]['cv_auc_mean']:.4f} ho={runs[-1]['holdout_auc']:.4f}")
    cv = np.array([r["cv_auc_mean"] for r in runs])
    ho = np.array([r["holdout_auc"] for r in runs])
    msg = (f"{n_sub} random 10-feature subsets: CV mean {cv.mean():.4f} sd {cv.std(ddof=1):.4f} "
           f"max {cv.max():.4f} (champion {ctx.real_cv:.4f}, {int((cv >= ctx.real_cv).sum())} "
           f">= champion); holdout mean {ho.mean():.4f} max {ho.max():.4f} (champion "
           f"{ctx.real_ho:.4f}, {int((ho >= ctx.real_ho).sum())}/{n_sub} >= champion)")
    return verdict("T12", "random 10-feature subsets", "INFO", msg, runs=runs,
                   cv={"mean": float(cv.mean()), "sd": float(cv.std(ddof=1)), "max": float(cv.max())},
                   holdout={"mean": float(ho.mean()), "sd": float(ho.std(ddof=1)), "max": float(ho.max())},
                   n_cv_ge_champion=int((cv >= ctx.real_cv).sum()),
                   n_holdout_ge_champion=int((ho >= ctx.real_ho).sum()))


# =========================================================================== #
# T13 y_clean look-ahead mask sensitivity
# =========================================================================== #
def t13(ctx, fresh):
    def run():
        df, sm = ctx.df, ctx.snapm
        lab = df[LABEL].notna().to_numpy()
        clean = df[CLEAN].to_numpy().astype(bool)
        pos_ok = ((sm["entry_open"] > 0) & (sm["exit_open"] > 0)).to_numpy()
        span_ok = (sm["span_days"] <= 45).to_numpy()
        extreme = (sm["fwd_absmax_re"] > SPLIT_MOVE).to_numpy()
        no_label_tail = (~lab) & sm["y_raw_re"].isna().to_numpy()
        variants = {"clean (harness)": lab & clean,
                    "+ suspensions (span>45d)": lab & ((clean) | (pos_ok & ~span_ok & ~extreme)),
                    "all labelled rows (no y_clean mask)": lab & pos_ok}
        dates = df["date"]
        tm = lab & clean
        counts, res = [], {k: {} for k in variants}
        for spec in ctx.splits["folds"] + [ctx.splits["holdout"]]:
            win = ((dates >= spec["test_start"]) & (dates <= spec["test_end"])).to_numpy()
            counts.append({"fold": spec["name"], "test_rows_in_window": int(win.sum()),
                           "clean": int((win & tm).sum()),
                           "masked_extreme_move": int((win & lab & extreme).sum()),
                           "masked_suspension_only": int((win & lab & ~span_ok & ~extreme).sum()),
                           "no_label_ticker_stopped": int((win & no_label_tail).sum())})
            tr = (dates <= spec["train_end"]).to_numpy() & tm
            prep = ev.Preprocessor("raw").fit(df.loc[tr, ctx.champ])
            est = make_lgbm()
            est.fit(prep.transform(df.loc[tr, ctx.champ]), df.loc[tr, LABEL].to_numpy(dtype=np.float32))
            for vname, vm in variants.items():
                te = win & vm
                sc = est.predict_proba(prep.transform(df.loc[te, ctx.champ]))[:, 1]
                m = ev.compute_metrics(df.loc[te, LABEL].to_numpy(dtype=np.float32), sc,
                                       df.loc[te, FWD].to_numpy(dtype=np.float32))
                res[vname][spec["name"]] = {"auc": m["auc"], "n": m["n"],
                                            "decile_spread": m.get("decile_spread"),
                                            "top_decile_mean_fwd": m.get("top_decile_mean_fwd")}
        summ = {}
        for vname, r in res.items():
            cvs = [v["auc"] for k, v in r.items() if k != "holdout"]
            summ[vname] = {"cv_auc_mean": float(np.mean(cvs)), "holdout_auc": r["holdout"]["auc"],
                           "min_window_auc": float(min(v["auc"] for v in r.values()))}
        return {"counts": counts, "by_variant": res, "summary": summ}
    r = cached("T13_mask", run, fresh)
    s0, s2 = r["summary"]["clean (harness)"], r["summary"]["all labelled rows (no y_clean mask)"]
    tot = {k: sum(c[k] for c in r["counts"]) for k in r["counts"][0] if k != "fold"}
    msg = (f"test windows: {tot['clean']:,} clean rows; masked by FUTURE extreme move "
           f"{tot['masked_extreme_move']:,}, by suspension {tot['masked_suspension_only']:,}, "
           f"no label (ticker stopped) {tot['no_label_ticker_stopped']:,}; champion CV AUC clean "
           f"{s0['cv_auc_mean']:.4f} -> no-mask {s2['cv_auc_mean']:.4f}, holdout "
           f"{s0['holdout_auc']:.4f} -> {s2['holdout_auc']:.4f}")
    return verdict("T13", "y_clean look-ahead mask sensitivity", "INFO", msg, totals=tot, **r)


# =========================================================================== #
# T14 dependence-aware uncertainty on saved preds (moving-block bootstrap)
# =========================================================================== #
def _block_counts(m: int, L: int, B: int, rng) -> np.ndarray:
    """Circular moving-block bootstrap date counts, shape (B, m)."""
    k = int(math.ceil(m / L))
    starts = rng.integers(0, m, size=(B, k))
    pos = (starts[:, :, None] + np.arange(L)[None, None, :]).reshape(B, -1)[:, :m] % m
    cnt = np.zeros((B, m))
    for b in range(B):
        cnt[b] = np.bincount(pos[b], minlength=m)
    return cnt


def t14(ctx, fresh):
    from ml.eval_aggregate import WeightedAUC
    models = {"champion_clean": "lgbm_fs_selected_clean", "lr_l2_clean": "lr_l2_clean",
              "baseline_mom_clean": "baseline_mom_clean"}
    B = 1000
    preds = {k: pd.read_parquet(RES / "preds" / f"{v}__{PRIMARY}.parquet") for k, v in models.items()}
    folds = ["2026-04", "2026-05", "2026-06", "2026-07", "holdout"]
    cdates = {f: np.unique(preds["champion_clean"].loc[lambda d: d["fold"] == f, "date"].to_numpy())
              for f in folds}
    for k, pr in preds.items():
        for f in folds:
            assert np.array_equal(np.unique(pr.loc[pr["fold"] == f, "date"].to_numpy()), cdates[f]), k
    eng = {k: {} for k in models}
    for k, pr in preds.items():
        for f in folds:
            g = pr[pr["fold"] == f]
            eng[k][f] = (WeightedAUC(g["score"].to_numpy(), g["y"].to_numpy()),
                         np.searchsorted(cdates[f], g["date"].to_numpy()))
    res = {}
    for L in (1, 5, 10):
        rng = np.random.default_rng(SEED)
        cnts = {f: _block_counts(len(cdates[f]), L, B, rng) for f in folds}
        draws = {}
        for k in models:
            fd = {f: np.array([eng[k][f][0].auc(cnts[f][b][eng[k][f][1]]) for b in range(B)])
                  for f in folds}
            draws[k] = {"cv_mean": np.mean([fd[f] for f in folds[:4]], axis=0), "holdout": fd["holdout"]}
        r = {}
        for k in models:
            for key in ("cv_mean", "holdout"):
                dd = draws[k][key]
                r[f"{k}_{key}"] = {"ci95": [float(np.percentile(dd, 2.5)), float(np.percentile(dd, 97.5))],
                                   "sd": float(dd.std(ddof=1)), "p_gt_0.5": float((dd > 0.5).mean())}
        for other in ("lr_l2_clean", "baseline_mom_clean"):
            for key in ("cv_mean", "holdout"):
                dd = draws["champion_clean"][key] - draws[other][key]
                r[f"champion_minus_{other}_{key}"] = {
                    "ci95": [float(np.percentile(dd, 2.5)), float(np.percentile(dd, 97.5))],
                    "p_gt_0": float((dd > 0).mean())}
        res[f"block_{L}"] = r
    # window-level (month-level) inference: the honest unit of independence
    w = np.array([ctx.real_folds[f] for f in folds[:4]] + [ctx.real_ho])
    t5, p5 = stats.ttest_1samp(w, 0.5, alternative="greater")
    t4_, p4 = stats.ttest_1samp(w[:4], 0.5, alternative="greater")
    window = {"window_aucs": w.tolist(), "mean_5": float(w.mean()), "sd_5": float(w.std(ddof=1)),
              "t_5windows": float(t5), "p_one_sided_5windows": float(p5),
              "t_4cv_folds": float(t4_), "p_one_sided_4cv": float(p4),
              "sign_test_p_all5_above_0.5": 0.5 ** 5,
              "holdout_only_selection_free_auc": ctx.real_ho}
    r1, r10 = res["block_1"], res["block_10"]
    msg = (f"champion CV-mean 95% CI: date bootstrap (L=1) {np.round(r1['champion_clean_cv_mean']['ci95'], 4).tolist()} "
           f"-> 10-session blocks {np.round(r10['champion_clean_cv_mean']['ci95'], 4).tolist()} "
           f"(sd x{r10['champion_clean_cv_mean']['sd'] / r1['champion_clean_cv_mean']['sd']:.1f}); "
           f"P(CV>0.5)={r10['champion_clean_cv_mean']['p_gt_0.5']:.3f}; holdout champion minus "
           f"baseline_mom: CI {np.round(r10['champion_minus_baseline_mom_clean_holdout']['ci95'], 4).tolist()}, "
           f"P(champ>base)={r10['champion_minus_baseline_mom_clean_holdout']['p_gt_0']:.3f}; month-level t-test on 5 "
           f"windows t={t5:.2f} (p={p5:.3f}), on 4 CV folds t={t4_:.2f} (p={p4:.3f})")
    return verdict("T14", "dependence-aware uncertainty (block bootstrap, month-level)", "INFO", msg,
                   B=B, bootstrap=res, window_level=window)


# =========================================================================== #
TESTS = {"T0": t0, "T1": t1, "T2": t2, "T3": t3, "T4": t4, "T5": t5, "T6": t6, "T7": t7,
         "T8": t8, "T9": t9, "T10": t10, "T11": t11, "T12": t12, "T13": t13, "T14": t14}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma list, e.g. T1,T2")
    ap.add_argument("--fresh", action="store_true", help="ignore caches")
    args = ap.parse_args()
    sel = [t.strip() for t in args.only.split(",") if t.strip()] or list(TESTS)
    ctx = Ctx()
    results = {}
    for tid in sel:
        log(f"=== {tid} ===")
        p = CACHE_DIR / f"{tid}.json"
        if tid in ("T3", "T4", "T5", "T7", "T8", "T9", "T10") or args.fresh or not p.exists():
            r = TESTS[tid](ctx, args.fresh)
            p.write_text(json.dumps(r, indent=1, default=_json_default))
        else:
            r = json.loads(p.read_text())
            print(f"[{tid}] {r['status']:4s} | {r['name']} | {r['summary']}  (cached)", flush=True)
        results[tid] = json.loads(p.read_text())
    if not args.only:
        tests = [results[t] for t in TESTS]
        payload = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "generated_by": "ml/audit.py (red-team, seed 108, OMP_NUM_THREADS=2)",
            "claim_audited": {"champion": "lgbm_fs_selected", "features": ctx.champ,
                              "cv_auc_frozen": 0.5307, "cv_auc_clean": ctx.real_cv,
                              "holdout_auc_clean": ctx.real_ho, "fold_aucs_clean": ctx.real_folds},
                "table": [{"id": t["id"], "name": t["name"], "status": t["status"],
                       "summary": t["summary"]} for t in tests],
            "tests": tests,
            "runtime_seconds": round(time.time() - T_START, 1),
        }
        out = AUDIT_DIR / "audit.json"
        out.write_text(json.dumps(payload, indent=1, default=_json_default))
        log(f"wrote {out}")
        for t in tests:
            print(f"  {t['id']:4s} {t['status']:4s} {t['name']}")


if __name__ == "__main__":
    main()

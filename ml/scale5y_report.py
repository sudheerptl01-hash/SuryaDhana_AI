#!/usr/bin/env python3
"""5-year scale-up report (agent: lead-scale5y).

Reads the 5-year walk-forward results in ml/results/scale5y/ (core duel from
ml/scale5y.py: champion10, all51, lr_l2, baseline_mom; nested runs from
ml/scale5y_nested.py: nested_lgbm, nested_lr_l2, nested_ensemble_rank and its
members) and writes ml/results/scale5y/scale5y_summary.json + tables.md:

1. league over the 43 monthly folds (mean, sd, % folds >= 0.50, worst fold,
   per-year means, pooled CV AUC, holdout);
2. 20-session moving-block bootstrap on the POOLED 43-fold test-date sequence
   (B=1000, seed 108, identical draws for every model => paired deltas):
   ceil(M/20) blocks of 20 consecutive CV test sessions per replicate (circular
   over the whole sequence), so dates within months AND months against each
   other are re-weighted; CV-mean replicate = fold AUCs weighted by how often
   each fold's dates were drawn; pooled replicate = weighted AUC over all CV
   rows; holdout = 20-session circular blocks inside the holdout ->
   bootstrap_5y.json;
3. per-date rank-IC of score vs y_excess_20d: mean, Newey-West t (20 lags),
   month-level t, block-bootstrap CI;
4. regimes, PRE-SPECIFIED from market data only (never from AUCs): per test
   month, direction = sign of the equal-weight universe's mean forward 20-day
   return over the month's signal dates; volatility = annualised std of the EW
   universe's daily close-to-close return over the month's sessions (|ret_1d| >
   22% split days excluded), high = above the median of the 43 CV months; plus
   calendar year and the two called-out windows (2025-09..2026-02 run, the
   2026-03 AUC crash -- a sharp EW rebound month); fold AUC and top-decile 20d excess vs the EW universe per regime;
   count of months that look like 2026-04 (most features' IC inverted) ->
   regimes_5y.json + regimes_5y.md;
5. portfolio on the 5-year OOS signal dates through ml/strategy_backtest.py's
   engine (imported, defaults untouched; prices = equity_features open/turnover
   from nse_market.duckdb opened read-only): top decile and liquid-tercile top
   decile long-only, top-minus-bottom decile long-short and the liquid-tercile
   top decile (STRATEGY.md's pre-registered paper book), 10/20/40 bps per side;
   annualised return, excess vs EW, Sharpe with month-block CI, max DD,
   turnover, monthly hit vs EW, PSR/DSR with N fixed in TRIALS below before any
   portfolio number is computed -> portfolio_5y.json;
6. SCALE_UP.md gates 1-5 for nested_lgbm, all51 and nested_ensemble_rank
   (the ensemble = per-date rank average of nested_lgbm, nested_lambdarank and
   nested_catboost, all on the per-year NESTED feature sets).

Run: cd /home/user/SuryaDhana_AI && python3 -m ml.scale5y_report [--skip-portfolio] [--B 1000]
"""
from __future__ import annotations

import os

os.environ["OMP_NUM_THREADS"] = "2"
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
os.environ["OMP_WAIT_POLICY"] = "PASSIVE"

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.metrics import roc_auc_score

import ml.strategy_backtest as sb
from ml.eval_aggregate import WeightedAUC

ML_DIR = Path(__file__).resolve().parent
REPO = ML_DIR.parent
DATA_5Y = ML_DIR / "data_5y"
OUT = ML_DIR / "results" / "scale5y"
PREDS = OUT / "preds"
CACHE = OUT / "cache"
TASK = "beat_mkt_20d"
SEED = 108
BLOCK = 20
NW_LAG = 20
CORE = ["champion10", "all51", "lr_l2", "baseline_mom"]
NESTED = ["nested_lgbm", "nested_lr_l2", "nested_ensemble_rank"]
MEMBERS = ["nested_lambdarank", "nested_catboost"]
HEUR = "heuristic_mom20"
CHAMP = "nested_lgbm"
ENS = "nested_ensemble_rank"
BOOT_MODELS = ["nested_lgbm", "all51", "champion10", "lr_l2", "baseline_mom", "nested_lr_l2", ENS, HEUR]
PAIRS = [("nested_lgbm", "all51"), ("nested_lgbm", "champion10"), ("nested_lgbm", "lr_l2"),
         ("nested_lgbm", "baseline_mom"), ("nested_lgbm", "nested_lr_l2"), (ENS, "nested_lgbm"),
         (ENS, "all51"), ("all51", "lr_l2"), (ENS, "lr_l2"), ("all51", "champion10"), ("nested_lgbm", HEUR)]
GATE_MODELS = ["nested_lgbm", "all51", ENS]
PORT_SCORERS = ["nested_lgbm", "all51", ENS, "champion10", "lr_l2", "nested_lr_l2", "baseline_mom", HEUR]
BASKETS = ("top_decile", "ls_decile", "liq_top_decile")
COST_KEY = "20bps"
PAPER_BASKET = "liq_top_decile"               # STRATEGY.md: champion liquid-tercile top decile, long-only
# --------------------------------------------------------------------------------------------------------
# DSR trial count N -- WRITTEN DOWN BEFORE ANY PORTFOLIO NUMBER IS COMPUTED (SCALE_UP.md gate 5).
# Every model/variant evaluated on these folds in this program:
#   5-year folds: champion10, all51, lr_l2, baseline_mom (core duel), nested_lgbm, nested_lr_l2,
#     nested_lambdarank, nested_catboost, nested_ensemble_rank, heuristic_mom20            = 10 model configs
#     portfolio grid of this report: 8 scorers x 3 baskets (cost levels not counted)        = 24 books
#   pilot (its 4 CV months + holdout are 2026-04..2026-09, i.e. inside these folds):
#     audit T7 ledger 77 = 38 full-protocol configs + 39 two-fold hyper-parameter screens,
#     STRATEGY.md grid 66 = 60 scorer x basket cells + 6 diagnostics
#   headline N = 10 + 24 + 77 + 66 = 177; conservative N = 10 + 24 + 151 + 66 = 251 (adds the
#   audit's 74 univariate feature screens); 5-year-only N = 34.
#   The nested selection's 48 inner k-curve fits (4 years x 4 k x 3 blocks) were scored on
#   training-period blocks, never on a test fold, and are not counted.
TRIALS = {"5y_model_configs": 10, "5y_portfolio_books": 24, "pilot_configs_audit_T7_77": 77,
          "pilot_portfolio_cells_STRATEGY_md": 66}
N_HEADLINE = 177
N_SENSITIVITY = {"5y_only": 34, "headline": 177, "conservative_incl_univariate_screens": 251}
SUFF = ["deliv_value_share_20", "amihud_20"]
MONTH_LIKE = "2026-04"

T0 = time.time()


def log(msg: str) -> None:
    print(f"[report +{time.time() - T0:6.0f}s] {msg}", flush=True)


def clean(o):
    return sb.clean_json(o)


def wjson(path: Path, obj) -> None:
    path.write_text(json.dumps(clean(obj), indent=1, allow_nan=False))


# =========================================================================== #
# data
# =========================================================================== #
def load_base(splits: dict, feats: list[str]) -> pd.DataFrame:
    vfeats = [f for f in feats if not f.endswith("_isnan")]
    cols = list(dict.fromkeys(["date", "ticker", "y_raw_20d", "y_excess_20d", "label_beat_mkt_20d",
                               "y_clean_20d", "cs_rank_turnover", "cs_rank_mom_20", "log_turnover"] + vfeats))
    d = pd.read_parquet(DATA_5Y / "model_dataset.parquet", columns=cols)
    d["date"] = pd.to_datetime(d["date"])
    ex = pd.read_parquet(CACHE / "extra_5y.parquet", columns=SUFF)
    for c in SUFF:
        d[c] = ex[c].to_numpy(float)
    fold = pd.Series(pd.NA, index=d.index, dtype="object")
    for s in splits["folds"] + [splits["holdout"]]:
        fold[(d["date"] >= s["test_start"]) & (d["date"] <= s["test_end"])] = s["name"]
    d["fold"] = fold
    m = d["fold"].notna() & d["label_beat_mkt_20d"].notna() & d["y_clean_20d"].astype(bool)
    base = d[m].sort_values(["date", "ticker"]).reset_index(drop=True)
    base["segment"] = np.where(base["fold"] == "holdout", "holdout", "cv")
    base["mkt_med"] = base["y_raw_20d"] - base["y_excess_20d"]
    base["month"] = base["date"].dt.strftime("%Y-%m")
    return base


def load_scores(base: pd.DataFrame) -> tuple[dict, dict]:
    key = base[["date", "ticker"]]
    scores, meta = {}, {}
    y = base["label_beat_mkt_20d"].to_numpy(float)
    for m in CORE + NESTED + MEMBERS:
        p = PREDS / f"{m}__{TASK}.parquet"
        j = OUT / f"{m}__{TASK}.json"
        if not (p.exists() and j.exists()):
            continue
        pr = pd.read_parquet(p, columns=["date", "ticker", "score", "y"])
        pr["date"] = pd.to_datetime(pr["date"])
        mm = key.merge(pr, on=["date", "ticker"], how="left", validate="one_to_one")
        sc = mm["score"].to_numpy(float)
        ok = np.isfinite(sc)
        assert np.array_equal(mm["y"].to_numpy(float)[ok], y[ok]), f"{m}: label mismatch"
        scores[m] = sc
        meta[m] = {"json": json.loads(j.read_text()), "coverage": float(ok.mean()), "n_pred_rows": int(len(pr))}
    h = base["cs_rank_mom_20"].to_numpy(float)
    meta[HEUR] = {"json": None, "coverage": float(np.isfinite(h).mean()),
                  "note": "score = cs_rank_mom_20 (parameter-free momentum rank); undefined for names with < 20 "
                          "sessions of history -> neutral 0.5 so every scorer covers identical rows"}
    scores[HEUR] = np.where(np.isfinite(h), h, 0.5)
    for m, v in scores.items():
        assert np.isfinite(v).all(), f"{m}: non-finite scores on {int((~np.isfinite(v)).sum())} rows"
    return scores, meta


# =========================================================================== #
# league
# =========================================================================== #
def fold_aucs(base: pd.DataFrame, score: np.ndarray, fold_names: list[str]) -> dict:
    out = {}
    y = base["label_beat_mkt_20d"].to_numpy(float)
    fo = base["fold"].to_numpy()
    for f in fold_names:
        m = (fo == f) & np.isfinite(score)
        if m.sum() > 0:
            s = score[m]
            out[f] = float(roc_auc_score(y[m], np.where(np.isfinite(s), s, 0.5)))
    return out


def league(base, scores, meta, splits) -> dict:
    cvf = [f["name"] for f in splits["folds"]]
    y = base["label_beat_mkt_20d"].to_numpy(float)
    cvm = (base["segment"] == "cv").to_numpy()
    rows = {}
    for m, sc in scores.items():
        fa = fold_aucs(base, sc, cvf + ["holdout"])
        cv = np.array([fa[f] for f in cvf if f in fa])
        if len(cv) < len(cvf):
            log(f"league: {m} has {len(cv)}/{len(cvf)} folds -- skipped")
            continue
        worst = min(cvf, key=lambda f: fa[f])
        per_year = {yr: float(np.mean([fa[f] for f in cvf if f.startswith(yr)])) for yr in ("2023", "2024", "2025", "2026")}
        ok = cvm & np.isfinite(sc)
        r = {"cv_auc_mean": float(cv.mean()), "cv_auc_sd": float(cv.std()), "cv_auc_sd_ddof1": float(cv.std(ddof=1)),
             "pct_folds_ge_050": float(np.mean(cv >= 0.5)), "n_folds_lt_050": int(np.sum(cv < 0.5)),
             "worst_fold": worst, "worst_fold_auc": fa[worst],
             "per_year_mean": per_year, "pooled_cv_auc": float(roc_auc_score(y[ok], sc[ok])),
             "holdout_auc": fa.get("holdout"), "fold_aucs": fa,
             "month_level_t_vs_050": float((cv.mean() - 0.5) / (cv.std(ddof=1) / math.sqrt(len(cv))))}
        f39 = [f for f in cvf if f <= "2026-03"]
        fpost = [f for f in cvf if f >= "2024-10"]
        a39, apost = np.array([fa[f] for f in f39]), np.array([fa[f] for f in fpost])
        r["cv_auc_mean_39_folds_2023_01_to_2026_03"] = float(a39.mean())
        r["pct_ge_050_39_folds"] = float(np.mean(a39 >= 0.5))
        r["month_level_t_39_folds"] = float((a39.mean() - 0.5) / (a39.std(ddof=1) / math.sqrt(len(a39))))
        r["posthoc_cv_auc_mean_folds_2024_10_on"] = float(apost.mean())
        r["posthoc_pct_ge_050_folds_2024_10_on"] = float(np.mean(apost >= 0.5))
        r["posthoc_n_folds_2024_10_on"] = len(fpost)
        js = meta[m]["json"]
        if js is not None:
            ntr = {f["fold"]: f.get("n_train") for f in js["folds"]}
            if js.get("holdout"):
                ntr["holdout"] = js["holdout"].get("n_train")
            r["n_train_by_fold"] = ntr
            r["mean_n_train_by_year"] = {yr: float(np.mean([ntr[f] for f in cvf if f.startswith(yr) and ntr.get(f)]))
                                         for yr in ("2023", "2024", "2025", "2026")
                                         if any(ntr.get(f) for f in cvf if f.startswith(yr))}
            r["json_cv_auc_mean"] = js["cv_auc_mean"]
            r["json_matches_preds"] = bool(abs(js["cv_auc_mean"] - r["cv_auc_mean"]) < 1e-9)
            r["holdout_decile_spread"] = (js.get("holdout") or {}).get("decile_spread")
            r["mean_fold_decile_spread"] = float(np.nanmean([f.get("decile_spread", np.nan) for f in js["folds"]]))
            if "exit_date_purge" in js:
                r["exit_date_purge_rows_removed"] = js["exit_date_purge"]["rows_removed_total"]
        rows[m] = r
    return rows


# =========================================================================== #
# block bootstrap
# =========================================================================== #
def _block_counts_within(m: int, L: int, Bn: int, rng) -> np.ndarray:
    """audit T14 circular moving-block counts for one window, shape (B, m)."""
    k = int(math.ceil(m / L))
    starts = rng.integers(0, m, size=(Bn, k))
    pos = (starts[:, :, None] + np.arange(L)[None, None, :]).reshape(Bn, -1)[:, :m] % m
    cnt = np.zeros((Bn, m))
    for b in range(Bn):
        cnt[b] = np.bincount(pos[b], minlength=m)
    return cnt


def bootstrap(base, scores, splits, models, Bn: int) -> dict:
    cvf = [f["name"] for f in splits["folds"]]
    y = base["label_beat_mkt_20d"].to_numpy(float)
    dts = base["date"].to_numpy(dtype="datetime64[ns]")
    fo = base["fold"].to_numpy()
    cdates = {f: np.unique(dts[fo == f]) for f in cvf}
    msz = np.array([len(cdates[f]) for f in cvf])
    off = np.r_[0, np.cumsum(msz)[:-1]]
    allcv = np.concatenate([cdates[f] for f in cvf])
    M = int(len(allcv))
    assert (np.diff(allcv.astype("int64")) > 0).all(), "CV dates must be chronological and disjoint"
    # pooled moving blocks: T14 circular block counts over the whole 43-fold date sequence
    cnt = _block_counts_within(M, BLOCK, Bn, np.random.default_rng(SEED))
    W = np.column_stack([cnt[:, off[i]:off[i] + msz[i]].sum(1) for i in range(len(cvf))])   # (B, folds)
    mult = W / msz[None, :]
    hd = np.unique(dts[fo == "holdout"])
    hcnt = _block_counts_within(len(hd), BLOCK, Bn, np.random.default_rng(SEED + 1))
    cvrows = np.flatnonzero(base["segment"].to_numpy() == "cv")
    code_cv = np.searchsorted(allcv, dts[cvrows])
    hrows = np.flatnonzero(fo == "holdout")
    hcode = np.searchsorted(hd, dts[hrows])
    frows = {f: np.flatnonzero(fo[cvrows] == f) for f in cvf}
    global _BT
    _BT = dict(scores=scores, y=y, cvf=cvf, cvrows=cvrows, frows=frows, hrows=hrows, code_cv=code_cv,
               hcode=hcode, cnt=cnt, hcnt=hcnt, W=W, mult=mult, Bn=Bn)
    todo = [m for m in models if m in scores and np.isfinite(scores[m][cvrows]).all()]
    import multiprocessing as mp
    with mp.get_context("fork").Pool(min(2, len(todo))) as pool:
        res = pool.map(_boot_one, todo, chunksize=1)
    draws = dict(zip(todo, res))
    return {"draws": draws, "design": {
        "B": Bn, "seed": SEED, "block_sessions": BLOCK, "n_cv_dates": M, "n_cv_folds": len(cvf),
        "blocks_per_replicate": int(math.ceil(M / BLOCK)), "n_holdout_dates": int(len(hd)),
        "cv": "moving blocks of 20 consecutive sessions over the pooled, chronological sequence of the 43 folds' "
              "test dates (circular at the ends; audit T14 _block_counts with L=20 on the pooled sequence); "
              "identical draws for every model (paired). cv_mean replicate = sum_f mult_f * AUC_f(w) / sum_f "
              "mult_f with mult_f = (draw weight of fold f's dates)/(fold f's dates); pooled_cv replicate = "
              "weighted AUC over all CV rows (scores of 43 fold models pooled, as ml/eval_aggregate.py does)",
        "holdout": "20-session circular blocks inside the 32-date holdout (seed 109): ~2 blocks per replicate, so "
                   "the holdout CI is indicative only"}}


_BT: dict = {}


def _boot_one(m: str) -> dict:
    t1 = time.time()
    g = _BT
    sc, y, cvf, cvrows, frows = g["scores"][m], g["y"], g["cvf"], g["cvrows"], g["frows"]
    scv, ycv = sc[cvrows], y[cvrows]
    eng_f = {f: WeightedAUC(scv[frows[f]], ycv[frows[f]]) for f in cvf}
    eng_p = WeightedAUC(scv, ycv)
    eng_h = WeightedAUC(sc[g["hrows"]], y[g["hrows"]])
    Bn, W, mult = g["Bn"], g["W"], g["mult"]
    A = np.full((Bn, len(cvf)), np.nan)
    pooled = np.empty(Bn)
    ho = np.empty(Bn)
    for b in range(Bn):
        w = g["cnt"][b][g["code_cv"]]
        for i, f in enumerate(cvf):
            if W[b, i] > 0:
                A[b, i] = eng_f[f].auc(w[frows[f]])
        pooled[b] = eng_p.auc(w)
        ho[b] = eng_h.auc(g["hcnt"][b][g["hcode"]])
    cv_mean = np.nansum(np.nan_to_num(A) * mult, 1) / np.where(W > 0, mult, 0).sum(1)
    log(f"bootstrap {m}: {time.time() - t1:.0f}s")
    return {"cv_mean": cv_mean, "pooled_cv": pooled, "holdout": ho}


def ci(x) -> list:
    x = np.asarray(x)
    x = x[np.isfinite(x)]
    return [float(np.percentile(x, 2.5)), float(np.percentile(x, 97.5))]


def boot_summary(bt: dict, lg: dict) -> dict:
    out = {"design": bt["design"], "models": {}, "pairs": {}}
    D = bt["draws"]
    for m, d in D.items():
        out["models"][m] = {
            "cv_auc_mean": lg[m]["cv_auc_mean"], "cv_mean_ci95": ci(d["cv_mean"]),
            "cv_mean_sd": float(np.std(d["cv_mean"], ddof=1)), "p_cv_mean_gt_050": float(np.mean(d["cv_mean"] > 0.5)),
            "pooled_cv_auc": lg[m]["pooled_cv_auc"], "pooled_cv_ci95": ci(d["pooled_cv"]),
            "p_pooled_gt_050": float(np.mean(d["pooled_cv"] > 0.5)),
            "holdout_auc": lg[m]["holdout_auc"], "holdout_ci95": ci(d["holdout"]),
            "p_holdout_gt_050": float(np.mean(d["holdout"] > 0.5)),
            "cv_mean_ci_excludes_050": bool(ci(d["cv_mean"])[0] > 0.5),
        }
    for a, b in PAIRS:
        if a not in D or b not in D:
            continue
        r = {}
        for key, pt in (("cv_mean", "cv_auc_mean"), ("pooled_cv", "pooled_cv_auc"), ("holdout", "holdout_auc")):
            dd = D[a][key] - D[b][key]
            r[key] = {"delta": lg[a][pt] - lg[b][pt], "ci95": ci(dd), "p_gt_0": float(np.mean(dd > 0)),
                      "ci_excludes_0": bool(ci(dd)[0] > 0 or ci(dd)[1] < 0)}
        fa, fb = lg[a]["fold_aucs"], lg[b]["fold_aucs"]
        diffs = np.array([fa[f] - fb[f] for f in fa if f != "holdout"])
        r["folds_won"] = f"{int((diffs > 0).sum())}/{len(diffs)}"
        r["month_level_paired_t"] = float(diffs.mean() / (diffs.std(ddof=1) / math.sqrt(len(diffs))))
        out["pairs"][f"{a} - {b}"] = r
    return out


# =========================================================================== #
# rank IC
# =========================================================================== #
def per_date_ic(codes: np.ndarray, s: np.ndarray, y: np.ndarray, n_dates: int) -> np.ndarray:
    ok = np.isfinite(s) & np.isfinite(y)
    df = pd.DataFrame({"d": codes[ok], "s": s[ok], "y": y[ok]})
    rs = df.groupby("d")["s"].rank().to_numpy()
    ry = df.groupby("d")["y"].rank().to_numpy()
    d = df["d"].to_numpy()
    n = np.bincount(d, minlength=n_dates).astype(float)
    sx, sy = np.bincount(d, rs, n_dates), np.bincount(d, ry, n_dates)
    sxx, syy, sxy = np.bincount(d, rs * rs, n_dates), np.bincount(d, ry * ry, n_dates), np.bincount(d, rs * ry, n_dates)
    with np.errstate(invalid="ignore", divide="ignore"):
        cov = sxy / n - sx * sy / n ** 2
        vx, vy = sxx / n - (sx / n) ** 2, syy / n - (sy / n) ** 2
        ic = cov / np.sqrt(vx * vy)
    ic[n < 50] = np.nan
    return ic


def nw_t(x: np.ndarray, L: int = NW_LAG) -> float:
    x = x[np.isfinite(x)]
    T = len(x)
    e = x - x.mean()
    s = e @ e / T
    for l in range(1, L + 1):
        s += 2 * (1 - l / (L + 1)) * (e[l:] @ e[:-l]) / T
    return float(x.mean() / math.sqrt(s / T))


def ic_block(base, scores, splits) -> tuple[dict, dict]:
    dates = np.unique(base["date"].to_numpy(dtype="datetime64[ns]"))
    codes = np.searchsorted(dates, base["date"].to_numpy(dtype="datetime64[ns]"))
    yx = base["y_excess_20d"].to_numpy(float)
    dmon = pd.DatetimeIndex(dates).strftime("%Y-%m").to_numpy()
    seg_d = base.groupby(codes)["segment"].first().reindex(np.arange(len(dates))).to_numpy()
    rng = np.random.default_rng(SEED)
    cvd = np.flatnonzero(seg_d == "cv")
    nb = int(math.ceil(len(cvd) / BLOCK))
    st = rng.integers(0, len(cvd), size=(1000, nb))
    bidx = ((st[..., None] + np.arange(BLOCK)) % len(cvd)).reshape(1000, -1)
    out, series = {}, {}
    for m, sc in scores.items():
        ic = per_date_ic(codes, sc, yx, len(dates))
        series[m] = ic
        cv = ic[cvd]
        mon = pd.Series(cv).groupby(dmon[cvd]).mean()
        bmeans = np.nanmean(cv[bidx], axis=1)
        out[m] = {"cv_mean_ic": float(np.nanmean(cv)), "cv_nw_t_lag20": nw_t(cv),
                  "cv_naive_t": float(np.nanmean(cv) / (np.nanstd(cv, ddof=1) / math.sqrt(np.isfinite(cv).sum()))),
                  "cv_month_level_t": float(mon.mean() / (mon.std(ddof=1) / math.sqrt(len(mon)))),
                  "cv_months_ic_positive": f"{int((mon > 0).sum())}/{len(mon)}",
                  "cv_block_bootstrap_ci95": ci(bmeans),
                  "holdout_mean_ic": float(np.nanmean(ic[seg_d == "holdout"])),
                  "monthly_mean_ic": {k: float(v) for k, v in pd.Series(ic).groupby(dmon).mean().items()}}
    return out, {"dates": dates, "codes": codes, "months": dmon, "series": series, "seg": seg_d}


EXPO_FEATS = ["atr_pct", "vol_20", "dist_52w_high", "log_turnover", "amihud_20", "mom_20", "ret_126d",
              "deliv_pct_sma_20", "deliv_value_share_20"]


def exposures(base, scores, icd) -> dict:
    """Mean per-date Spearman correlation of each model's score with stock characteristics (CV dates; also
    split by the month's direction). Explains what the extremes of each ranking are made of."""
    codes, nd = icd["codes"], len(icd["dates"])
    cvd = icd["seg"] == "cv"
    yr = base["y_raw_20d"].to_numpy(float)
    ew_d = np.bincount(codes, yr, nd) / np.bincount(codes, minlength=nd)
    dmon = icd["months"]
    mdir = {mo: (ew_d[dmon == mo].mean() > 0) for mo in set(dmon)}
    up_d = np.array([mdir[mo] for mo in dmon])
    out = {}
    for m in ["nested_lgbm", "all51", ENS, "nested_lambdarank", "nested_catboost", "champion10", "lr_l2",
              "nested_lr_l2", "baseline_mom", HEUR]:
        if m not in scores:
            continue
        e = {}
        for f in EXPO_FEATS:
            c = per_date_ic(codes, scores[m], base[f].to_numpy(float), nd)
            e[f] = {"cv_mean": float(np.nanmean(c[cvd])), "up_months": float(np.nanmean(c[cvd & up_d])),
                    "down_months": float(np.nanmean(c[cvd & ~up_d])), "holdout": float(np.nanmean(c[icd["seg"] == "holdout"]))}
        out[m] = e
    return out


# =========================================================================== #
# regimes
# =========================================================================== #
REGIME_DEF = {
    "direction": "sign of the equal-weight universe's forward 20-day return (mean over the month's signal dates of "
                 "the EW mean y_raw_20d of clean-labeled universe rows) -- what a passive 20-day tranche earned",
    "volatility": "annualised std of the EW universe's daily close-to-close return (mean ret_1d over the date's "
                  "universe rows, |ret_1d| > 22% split/CA days excluded) over the month's sessions; high = above "
                  "the median of the 43 CV months (the same threshold classifies the holdout months)",
    "called_out": {"2025-09..2026-02 run": ["2025-09", "2025-10", "2025-11", "2025-12", "2026-01", "2026-02"],
                   "2026-03 AUC crash (EW rebound month)": ["2026-03"]},
    "fixed_before_looking_at_auc": True,
}
REGIME_MODELS = ["nested_lgbm", "all51", ENS, "champion10", "lr_l2", "nested_lr_l2", "baseline_mom", HEUR,
                 "nested_lambdarank", "nested_catboost"]


def regimes(base, scores, icd, feats, lg) -> dict:
    vfeats = [f for f in feats if not f.endswith("_isnan")] + SUFF
    codes, dmon, nd = icd["codes"], icd["months"], len(icd["dates"])
    yx = base["y_excess_20d"].to_numpy(float)
    yr = base["y_raw_20d"].to_numpy(float)
    nrow = np.bincount(codes, minlength=nd)
    ew_d = np.bincount(codes, yr, nd) / nrow                         # EW forward 20d return per signal date
    r1 = base["ret_1d"].to_numpy(float)
    ok1 = np.isfinite(r1) & (np.abs(r1) <= 0.22)
    ew1 = np.bincount(codes[ok1], r1[ok1], nd) / np.maximum(np.bincount(codes[ok1], minlength=nd), 1)
    months = sorted(set(dmon))
    mseg = {mo: ("holdout" if mo >= "2026-08" else "cv") for mo in months}
    ew20 = {mo: float(ew_d[dmon == mo].mean()) for mo in months}
    vol = {mo: float(np.std(ew1[dmon == mo], ddof=1) * math.sqrt(252)) for mo in months}
    vthr = float(np.median([vol[mo] for mo in months if mseg[mo] == "cv"]))
    direction = {mo: ("up" if ew20[mo] > 0 else "down") for mo in months}
    vstate = {mo: ("high-vol" if vol[mo] > vthr else "low-vol") for mo in months}
    # feature ICs per month, orientation = sign of the feature's mean daily IC over all CV dates (descriptive)
    cvd = icd["seg"] == "cv"
    fic = {f: per_date_ic(codes, base[f].to_numpy(float), yx, nd) for f in vfeats}
    orient = {f: float(np.sign(np.nanmean(fic[f][cvd]))) for f in vfeats}
    inv_share = {}
    for mo in months:
        mm = dmon == mo
        neg = [orient[f] * np.nanmean(fic[f][mm]) < 0 for f in vfeats if orient[f] != 0]
        inv_share[mo] = float(np.mean(neg))
    # per-model monthly AUC, IC and top-decile 20d excess vs the EW universe
    y = base["label_beat_mkt_20d"].to_numpy(float)
    bm = base["month"].to_numpy()
    rows = {}
    for m in REGIME_MODELS:
        if m not in scores or m not in lg:
            continue
        sc = scores[m]
        r = pd.Series(sc).groupby(codes).rank(pct=True, method="first").to_numpy()
        top = r > 0.9
        topm = np.bincount(codes[top], yr[top], nd) / np.maximum(np.bincount(codes[top], minlength=nd), 1)
        ex_d = topm - ew_d
        rows[m] = {mo: {"auc": float(roc_auc_score(y[bm == mo], sc[bm == mo])),
                        "top_decile_excess_vs_ew_20d": float(np.mean(ex_d[dmon == mo])),
                        "mean_ic": float(np.nanmean(icd["series"][m][dmon == mo]))} for mo in months}

    ntr_of = {m: lg[m].get("n_train_by_fold", {}) for m in rows}

    def agg(m, sel):
        v = [rows[m][mo] for mo in sel]
        if not v:
            return {"n_months": 0}
        fk = [mo if mseg[mo] == "cv" else "holdout" for mo in sel]
        nt = [ntr_of[m].get(k) for k in fk if ntr_of[m].get(k)]
        return {"n_months": len(sel), "mean_auc": float(np.mean([x["auc"] for x in v])),
                "mean_n_train": float(np.mean(nt)) if nt else None,
                "share_auc_ge_050": float(np.mean([x["auc"] >= 0.5 for x in v])),
                "top_decile_excess_vs_ew_20d": float(np.mean([x["top_decile_excess_vs_ew_20d"] for x in v])),
                "share_months_excess_gt_0": float(np.mean([x["top_decile_excess_vs_ew_20d"] > 0 for x in v])),
                "mean_ic": float(np.mean([x["mean_ic"] for x in v]))}
    cvm = [mo for mo in months if mseg[mo] == "cv"]
    sels = {
        "all 43 CV months": cvm,
        "up (EW 20d > 0)": [mo for mo in cvm if direction[mo] == "up"],
        "down (EW 20d <= 0)": [mo for mo in cvm if direction[mo] == "down"],
        "low-vol": [mo for mo in cvm if vstate[mo] == "low-vol"],
        "high-vol": [mo for mo in cvm if vstate[mo] == "high-vol"],
        "up / low-vol": [mo for mo in cvm if direction[mo] == "up" and vstate[mo] == "low-vol"],
        "up / high-vol": [mo for mo in cvm if direction[mo] == "up" and vstate[mo] == "high-vol"],
        "down / low-vol": [mo for mo in cvm if direction[mo] == "down" and vstate[mo] == "low-vol"],
        "down / high-vol": [mo for mo in cvm if direction[mo] == "down" and vstate[mo] == "high-vol"],
        "2023": [mo for mo in cvm if mo.startswith("2023")],
        "2024": [mo for mo in cvm if mo.startswith("2024")],
        "2025": [mo for mo in cvm if mo.startswith("2025")],
        "2026 Jan-Jul": [mo for mo in cvm if mo.startswith("2026")],
        "39 folds 2023-01..2026-03 (config fixed on 2026-04..07)": [mo for mo in cvm if mo <= "2026-03"],
        "POST-HOC: folds 2024-10..2026-07 (full 504-session window)": [mo for mo in cvm if mo >= "2024-10"],
        "2025-09..2026-02 run": REGIME_DEF["called_out"]["2025-09..2026-02 run"],
        "2026-03 AUC crash (EW rebound month)": REGIME_DEF["called_out"]["2026-03 AUC crash (EW rebound month)"],
        "43 CV months ex 2025-09..2026-03": [mo for mo in cvm if not ("2025-09" <= mo <= "2026-03")],
        "majority-inverted months (>50% of features' IC against their usual sign)":
            [mo for mo in cvm if inv_share[mo] > 0.5],
        "holdout months (2026-08, 2026-09)": [mo for mo in months if mseg[mo] == "holdout"],
    }
    groups = {lab: {"months": sel, **{m: agg(m, sel) for m in rows}} for lab, sel in sels.items()}
    like = [mo for mo in cvm if inv_share[mo] > 0.5]
    like_april = [mo for mo in cvm if inv_share[mo] >= inv_share.get(MONTH_LIKE, 1.0)]
    per_month = {mo: {"segment": mseg[mo], "ew_fwd_20d": ew20[mo], "ew_daily_vol_ann": vol[mo],
                      "direction": direction[mo], "vol_state": vstate[mo], "inverted_feature_share": inv_share[mo],
                      "n_train_nested_lgbm": ntr_of.get(CHAMP, {}).get(mo if mseg[mo] == "cv" else "holdout"),
                      "n_train_all51": ntr_of.get("all51", {}).get(mo if mseg[mo] == "cv" else "holdout"),
                      **{m: rows[m][mo] for m in rows}} for mo in months}
    return {
        "definition": {**REGIME_DEF, "vol_threshold_ann": vthr,
                       "top_decile_excess_vs_ew_20d": "per date: mean y_raw_20d of the top 10% by score minus the EW "
                                                      "universe, gross of costs; averaged over the month's dates",
                       "inverted_share": f"share of the {len(vfeats)} value features (40 base + 2 sufficiency, *_isnan "
                                         "excluded) whose monthly mean rank-IC vs y_excess_20d has the opposite sign "
                                         "to the feature's 43-month mean (descriptive orientation, not PIT)"},
        "groups": groups, "per_month": per_month, "feature_orientation": orient,
        "n_cv_months_majority_inverted": len(like), "majority_inverted_months": like,
        "april_2026_inverted_share": inv_share.get(MONTH_LIKE),
        "n_cv_months_at_least_as_inverted_as_2026_04": len(like_april),
        "months_at_least_as_inverted_as_2026_04": like_april,
        "counts": {"up": sum(direction[mo] == "up" for mo in cvm), "down": sum(direction[mo] == "down" for mo in cvm),
                   "high-vol": sum(vstate[mo] == "high-vol" for mo in cvm),
                   "low-vol": sum(vstate[mo] == "low-vol" for mo in cvm)},
    }


def regimes_md(rg: dict) -> str:
    ms = [m for m in REGIME_MODELS if m in rg["groups"]["all 43 CV months"]]
    md = ["# 5-year regimes: fold AUC by market regime and year\n",
          f"Generated by `python3 -m ml.scale5y_report` (seed 108). Regimes are defined from market data only, "
          f"before any AUC was split by them: direction = sign of the equal-weight universe's forward 20-day "
          f"return over the month's signal dates; volatility = annualised std of the EW universe's daily return "
          f"in the month, high if above the 43-month median ({100 * rg['definition']['vol_threshold_ann']:.1f}%). "
          f"Top-decile excess = gross 20-day return of the model's top 10% minus the EW universe.\n",
          "**Small training sets in 2023.** The 5-year dataset starts 2022-10-03, so the rolling 504-session window "
          "is truncated until about 2024-10: nested_lgbm trains on 41,733 rows for 2023-01 and reaches the full "
          "window (~580k rows) only around 2024-10. The 2023 AUCs are small-training-set results; the n_train "
          "columns carry the training size. All 43 folds stay in the headline (pre-registered); the 2024-10+ row is "
          "a post-hoc sensitivity.\n",
          "| regime / window | months | mean n_train (nested_lgbm) | " + " | ".join(ms) + " | nested_lgbm % months ≥ 0.50 | nested_lgbm top-decile excess vs EW (20d) | nested_lgbm mean IC |",
          "|---|---:|---:|" + "---:|" * len(ms) + "---:|---:|---:|"]
    for lab, g in rg["groups"].items():
        c = g.get(CHAMP, {})
        if not c.get("n_months"):
            continue
        ntxt = f"{c['mean_n_train']:,.0f}" if c.get("mean_n_train") else "n/a"
        md.append(f"| {lab} | {c['n_months']} | {ntxt} | " + " | ".join(
            (f"{g[m]['mean_auc']:.4f}" if g.get(m, {}).get("n_months") else "n/a") for m in ms)
            + f" | {100 * c['share_auc_ge_050']:.0f}% | {100 * c['top_decile_excess_vs_ew_20d']:+.2f}% | {c['mean_ic']:+.4f} |")
    md.append(f"\nMonths in which most features' IC ran against its usual sign: {rg['n_cv_months_majority_inverted']} of 43 "
              f"({', '.join(rg['majority_inverted_months']) or 'none'}). 2026-04's inverted share was "
              f"{rg['april_2026_inverted_share']:.2f}; {rg['n_cv_months_at_least_as_inverted_as_2026_04']} CV months were at "
              f"least as inverted ({', '.join(rg['months_at_least_as_inverted_as_2026_04'])}).\n")
    md.append("\n## Per month\n")
    md.append("| month | n_train nested_lgbm | n_train all51 | EW fwd 20d | EW vol (ann.) | regime | inverted share | "
              + " | ".join(ms[:4]) + " |")
    md.append("|---|---:|---:|---:|---:|---|---:|" + "---:|" * len(ms[:4]))
    for mo, r in rg["per_month"].items():
        n1, n2 = r.get("n_train_nested_lgbm") or 0, r.get("n_train_all51") or 0
        md.append(f"| {mo} | {n1:,} | {n2:,} | {100 * r['ew_fwd_20d']:+.2f}% | {100 * r['ew_daily_vol_ann']:.1f}% | {r['direction']} / "
                  f"{r['vol_state']} | {r['inverted_feature_share']:.2f} | " + " | ".join(
                      f"{r[m]['auc']:.4f}" if m in r else "n/a" for m in ms[:4]) + " |")
    return "\n".join(md) + "\n"


# =========================================================================== #
# portfolio (strategy_backtest engine on 5-year OOS dates)
# =========================================================================== #
def load_prices(base: pd.DataFrame):
    import duckdb
    con = duckdb.connect(str(REPO / "nse_market.duckdb"), read_only=True)
    s = con.execute("SELECT date, ticker, open, turnover FROM equity_features "
                    "WHERE date >= TIMESTAMP '2022-10-03' ORDER BY date, ticker").df()
    con.close()
    s["date"] = pd.to_datetime(s["date"])
    assert not s.duplicated(["date", "ticker"]).any()
    sessions = pd.DatetimeIndex(sorted(s["date"].unique()))
    tick = np.array(sorted(base["ticker"].unique()))
    s = s[s["ticker"].isin(tick)]
    O = s.pivot(index="date", columns="ticker", values="open").reindex(index=sessions, columns=tick)
    T = s.pivot(index="date", columns="ticker", values="turnover").reindex(index=sessions, columns=tick)
    adv20 = T.rolling(20, min_periods=10).median()
    return sessions, tick, O, adv20


def portfolio(base, scores, only: list[str] | None = None) -> dict:
    t1 = time.time()
    sessions, tick, O, adv20 = load_prices(base)
    blocks, check = sb.build_blocks(base, sessions, tick, O, adv20)
    log(f"portfolio: {len(blocks)} signal dates, exit-mark/label match {check['exit_mark_matches_label_frac']:.5f} "
        f"({time.time() - t1:.0f}s)")
    H = sb.HORIZON
    eng = sb.Engine(blocks, sessions, len(tick), H)
    cal = eng.cal
    EX = cal.expo["combined"]
    month_of = np.array([b.month for b in blocks])
    ew_R = eng.bench["ew_universe"]["R"]
    direction = {mo: ("up" if ew_R[month_of == mo].mean() > 0 else "down") for mo in sorted(set(month_of))}
    up_mask = np.array([direction[mo] == "up" for mo in month_of])
    bench = {}
    for name, bd in eng.bench.items():
        bench[name] = {"turnover_per_rebalance": bd["turnover"], "names_mean": float(bd["size"].mean())}
        for seg in sb.SEGMENTS:
            mk = cal.masks[seg]
            x = cal.seg_series(bd["D"], seg)
            bench[name][seg] = {"tranche": sb.tranche_stats(bd["R"][mk], bd["R"][mk], eng.med[mk], H=H),
                                "daily": sb.series_stats(x, cal.expo[seg], cal.month_codes[seg], cal.draws[seg],
                                                         rf=sb.RF_ANNUAL)}
    c20 = int(COST_KEY.replace("bps", "")) / 1e4
    books, skill, raw = {}, {}, {}
    scorers = [s_ for s_ in (only or PORT_SCORERS) if s_ in scores and np.isfinite(scores[s_]).all()]
    for sc in scorers:
        for bk in BASKETS:
            r = eng.run(scores[sc], bk)
            is_ls = bk.endswith("ls_decile")
            res = r["results"]
            segs = {}
            for seg in sb.SEGMENTS:
                e = {}
                for ck in ("gross", "10bps", "20bps", "40bps", "20bps_no_netting"):
                    t, dl = res[ck][seg]["tranche"], res[ck][seg]["daily"]
                    row = {"ann_return_252_20": t["ann_return_252_h"], "sharpe": dl["sharpe"],
                           "sharpe_ci95": dl["sharpe_ci95"], "p_sharpe_gt0": dl["p_sharpe_gt0"],
                           "ann_vol": dl["ann_vol"], "max_dd": dl["max_dd"]}
                    if is_ls:
                        row["hit_net_positive_tranches"] = t["hit_rate_net_positive"]
                    else:
                        da = res[ck][seg]["daily_active"]
                        ba = res[ck][seg]["beta_alpha_vs_benchmark"]
                        row.update({"excess_ann_vs_ew_252_20": t["active_ann_252_h"],
                                    "excess_ann_vs_ew_daily": da["ann_mean_daily"], "ir": da["sharpe"],
                                    "ir_ci95": da["sharpe_ci95"], "excess_max_dd": da["max_dd"],
                                    "hit_vs_ew_tranches": t["hit_rate_vs_ew"],
                                    "beta_vs_bench": ba["beta_vs_benchmark"], "alpha_ann_vs_bench": ba["alpha_ann"]})
                    e[ck] = row
                segs[seg] = e
            R = r["_tranche"][COST_KEY]["R"]
            val = R if is_ls else R - eng.bench[eng.bench_for(bk)]["R"]
            mon = pd.Series(val).groupby(month_of).mean()
            cvmon = mon[[mo for mo in mon.index if mo < "2026-08"]]
            ent = {"benchmark": None if is_ls else eng.bench_for(bk), "basket_size_mean": r["basket_size_mean"],
                   "turnover_per_rebalance": r["turnover_per_rebalance"],
                   "turnover_per_rebalance_short": r.get("turnover_per_rebalance_short"),
                   "capacity": r["capacity"], "segments": segs,
                   "monthly_metric": "net (20 bps) long-short 20d return" if is_ls else
                                     "net (20 bps) 20d return minus the EW benchmark's",
                   "monthly_20bps": {k: float(v) for k, v in mon.items()},
                   "months_positive": int((mon > 0).sum()), "n_months": int(len(mon)),
                   "share_months_positive": float((mon > 0).mean()),
                   "cv_months_positive": int((cvmon > 0).sum()), "n_cv_months": int(len(cvmon)),
                   "share_cv_months_positive": float((cvmon > 0).mean()),
                   "by_direction_20d": {"up": float(val[up_mask].mean()), "down": float(val[~up_mask].mean())},
                   "by_year_20d": {yy: float(val[np.char.startswith(month_of.astype(str), yy)].mean())
                                   for yy in ("2023", "2024", "2025", "2026")}}
            Lp, Wl, _ = sb.leg(blocks, [x[0] for x in r["_mem"]], len(tick), H)
            tl = sb.trade_fracs(Wl, H)
            if is_ls:
                Sp, Ws, _ = sb.leg(blocks, [x[1] for x in r["_mem"]], len(tick), H)
                rr, _ = sb.ls_net(Lp, Sp, tl, sb.trade_fracs(Ws, H), c20)
                skill[(sc, bk)] = cal.seg_series(cal.to_days(rr), "combined")
            else:
                rr, _ = sb.long_net(Lp, tl["buy"], tl["sell"], c20)
                x = cal.seg_series(cal.to_days(rr), "combined")
                xb = cal.seg_series(eng.bench[eng.bench_for(bk)]["D"], "combined")
                skill[(sc, bk)] = x - xb
                raw[(sc, bk)] = x - sb.RF_ANNUAL / sb.PPY
            books[f"{sc}|{bk}"] = ent
            c = segs["combined"]["20bps"]
            log(f"portfolio {sc}|{bk}: ann {c['ann_return_252_20']:+.3f} "
                + (f"LS Sharpe {c['sharpe']:+.2f}" if is_ls else
                   f"excess {c['excess_ann_vs_ew_252_20']:+.3f} IR {c['ir']:+.2f}")
                + f" months+ {ent['months_positive']}/{ent['n_months']}")
            del r
    # ---- PSR / DSR (N fixed in TRIALS / N_HEADLINE at the top of this file)
    keys = list(skill)
    if only is None:
        assert len(keys) == TRIALS["5y_portfolio_books"], f"grid has {len(keys)} books, TRIALS says {TRIALS['5y_portfolio_books']}"
    sr = {k: sb.wmoments(skill[k], EX)[0] / sb.wmoments(skill[k], EX)[1] for k in keys}
    srr = {k: sb.wmoments(raw[k], EX)[0] / sb.wmoments(raw[k], EX)[1] for k in raw}
    var_sr = float(np.var(list(sr.values()), ddof=1))
    var_srr = float(np.var(list(srr.values()), ddof=1))
    dsr = {"method": "Bailey & Lopez de Prado via ml/strategy_backtest.py dsr_block on the daily net (20 bps) series of "
                     "the combined 5-year OOS program (signal dates 2023-01-02..2026-09-16), exposure-weighted moments, "
                     "T = Kish n_eff; skill = net excess vs the EW benchmark (long-only) or net L-S return (long-short); "
                     f"V[SR] across this report's {len(keys)} books",
           "trials": TRIALS, "N_headline": N_HEADLINE, "N_sensitivity": N_SENSITIVITY,
           "var_sr_skill_daily": var_sr, "var_sr_absolute_daily": var_srr, "books": {}}
    for k in keys:
        lab = f"{k[0]}|{k[1]}"
        e = {"skill": {str(N): sb.dsr_block(skill[k], EX, var_sr, N, lab + " skill", sb.PPY)
                       for N in N_SENSITIVITY.values()}}
        if k in raw:
            e["absolute_net_minus_rf"] = {str(N): sb.dsr_block(raw[k], EX, var_srr, N, lab + " abs", sb.PPY)
                                          for N in N_SENSITIVITY.values()}
        dsr["books"][lab] = e
    ew_raw = cal.seg_series(eng.bench["ew_universe"]["D"], "combined") - sb.RF_ANNUAL / sb.PPY
    dsr["ew_universe_absolute_reference"] = sb.dsr_block(ew_raw, EX, var_srr, N_HEADLINE, "ew_universe abs", sb.PPY)
    return {"engine": "ml/strategy_backtest.py (imported; defaults untouched): 20 overlapping tranches, entry at the "
                      "open of t+1, exit at the open of t+21, exact daily open-to-open marks (equity_features open, "
                      "nse_market.duckdb read-only), exit pinned to 1 + y_raw_20d, netted costs per side, exposure-"
                      "weighted daily stats, month-block bootstrap CIs (B=1000, seed 108)",
            "n_signal_dates": len(blocks), "path_check": check, "direction_by_month": direction,
            "benchmarks": bench, "books": books, "dsr": dsr, "scorers": scorers, "baskets": list(BASKETS),
            "costs_bps_per_side": [10, 20, 40], "headline_cost": COST_KEY, "seconds": round(time.time() - t1, 1)}


# =========================================================================== #
# gates
# =========================================================================== #
def gates(lg, bs, sel, port) -> dict:
    yrs = sorted(sel["per_year"])
    ov = [sel["stability"][f"{a}->{b}"]["top10_overlap"] for a, b in zip(yrs[:-1], yrs[1:])]
    ovs = [sel["stability"][f"{a}->{b}"]["selected_overlap"] for a, b in zip(yrs[:-1], yrs[1:])]
    ks = [sel["per_year"][y]["k_selected"] for y in yrs]
    out = {}
    for m in GATE_MODELS:
        if m not in lg:
            continue
        g = {}
        pr = bs["pairs"].get(f"{m} - lr_l2")
        if pr:
            d = pr["cv_mean"]
            g["1"] = {"name": "beats lr_l2 on CV mean, bootstrap CI excluding zero",
                      "number": f"{d['delta']:+.4f} [{d['ci95'][0]:+.4f}, {d['ci95'][1]:+.4f}]",
                      "pass": bool(d["delta"] > 0 and d["ci95"][0] > 0)}
        c = lg[m]
        g["2"] = {"name": "fold AUC >= 0.50 in >= 90% of months",
                  "number": f"{100 * c['pct_folds_ge_050']:.0f}% ({43 - c['n_folds_lt_050']}/43; worst {c['worst_fold']} "
                            f"{c['worst_fold_auc']:.4f})", "pass": bool(c["pct_folds_ge_050"] >= 0.90)}
        if port and f"{m}|top_decile" in port["books"]:
            b = port["books"][f"{m}|top_decile"]
            g["3"] = {"name": "top decile beats EW universe in >= 75% of months, net 20 bps",
                      "number": f"{b['months_positive']}/{b['n_months']} signal months = {100 * b['share_months_positive']:.0f}% "
                                f"(43 CV months: {b['cv_months_positive']}/{b['n_cv_months']})",
                      "pass": bool(b["share_months_positive"] >= 0.75)}
        note = "" if m != "all51" else (" (all51 selects nothing, so read literally the test is vacuous; scored on the "
                                        "same yearly re-selection because the gate asks for a stable signal)")
        g["4"] = {"name": "selected-feature overlap >= 7/10 across yearly re-selections",
                  "number": f"consecutive-year top-10 overlap {ov} (min {min(ov)}/10); chosen sets k={ks}, overlap {ovs}" + note,
                  "pass": bool(min(ov) >= 7)}
        if port and f"{m}|{PAPER_BASKET}" in port["dsr"]["books"]:
            N = str(N_HEADLINE)
            e = port["dsr"]["books"][f"{m}|{PAPER_BASKET}"]["skill"][N]
            et = port["dsr"]["books"][f"{m}|top_decile"]["skill"][N]
            el = port["dsr"]["books"][f"{m}|ls_decile"]["skill"][N]
            g["5"] = {"name": "Deflated Sharpe >= 0.95 (paper book: liquid-tercile top decile, long-only, net 20 bps, "
                              f"excess vs EW-liquid), N={N_HEADLINE}",
                      "number": f"DSR {e['dsr']:.3f} (SR {e['sr_annualised']:+.2f}/yr, PSR {e['psr_vs_0']:.3f}); "
                                f"top decile DSR {et['dsr']:.3f}, long-short DSR {el['dsr']:.3f}",
                      "pass": bool(e["dsr"] >= 0.95)}
        g["n_pass"] = sum(v["pass"] for k, v in g.items() if isinstance(v, dict))
        out[m] = g
    return out


def posthoc_stability(lg) -> dict:
    """POST-HOC (not a gate): stability-aware comparison, added after seeing the data."""
    out = {"label": "POST-HOC, not pre-registered: the pre-registered gate verdicts stand as scored"}
    for m in ("nested_lgbm", "all51", ENS, "lr_l2", "nested_lr_l2", "champion10", "baseline_mom", HEUR):
        if m in lg:
            r = lg[m]
            out[m] = {"cv_auc_mean": r["cv_auc_mean"], "cv_auc_sd": r["cv_auc_sd"], "worst_fold": r["worst_fold"],
                      "worst_fold_auc": r["worst_fold_auc"], "n_folds_lt_050": r["n_folds_lt_050"],
                      "holdout_auc": r["holdout_auc"], "holdout_decile_spread": r.get("holdout_decile_spread"),
                      "mean_fold_decile_spread": r.get("mean_fold_decile_spread")}
    return out


# =========================================================================== #
# tables
# =========================================================================== #
def f4(x):
    return "n/a" if x is None or not np.isfinite(x) else f"{x:.4f}"


def pct(x, d=1):
    return "n/a" if x is None or not np.isfinite(x) else f"{100 * x:+.{d}f}%"


def write_tables(S: dict) -> None:
    md = [f"# 5-year scale-up: generated tables\n\nGenerated {S['generated_at']} by `python3 -m ml.scale5y_report` "
          "(seed 108). Narrative and verdict: SCALE5Y.md.\n"]
    lg, bsm = S["league"], S["bootstrap"]["models"]
    order = [m for m in ["nested_lgbm", ENS, "nested_lambdarank", "nested_catboost", "nested_lr_l2", "all51",
                         "champion10", "lr_l2", "baseline_mom", HEUR] if m in lg]
    md.append("\n## League over 43 monthly folds (2023-01 .. 2026-07) + holdout (2026-08-03 .. 2026-09-16)\n")
    md.append("2023 folds train on truncated windows (mean n_train per year in the second table): small-training-set "
              "results. The LightGBM config (and lr_l2's C) were fixed in the pilot on 2026-04..07, so those 4 folds and "
              "the holdout are not fully out-of-sample for the configuration: the 39-fold column (2023-01..2026-03) is "
              "the clean one. The 2024-10+ column is a post-hoc sensitivity (full 504-session windows).\n")
    md.append("| model | CV AUC ± sd (43) | 39-fold mean | POST-HOC 2024-10+ (22) | % folds ≥ 0.50 | worst fold | 2023 | 2024 | 2025 | 2026 Jan–Jul | CV mean 95% CI (20-session blocks) | pooled CV [CI] | holdout [CI] | holdout decile spread | rank-IC (NW t) |")
    md.append("|---|---|---:|---:|---:|---|---:|---:|---:|---:|---|---|---|---:|---|")
    for m in order:
        r = lg[m]
        b = bsm.get(m)
        ic = S["rank_ic"].get(m, {})
        cim = f"[{b['cv_mean_ci95'][0]:.4f}, {b['cv_mean_ci95'][1]:.4f}]" if b else "n/a"
        cip = f" [{b['pooled_cv_ci95'][0]:.4f}, {b['pooled_cv_ci95'][1]:.4f}]" if b else ""
        cih = f" [{b['holdout_ci95'][0]:.4f}, {b['holdout_ci95'][1]:.4f}]" if b else ""
        hs = r.get("holdout_decile_spread")
        md.append(f"| {m} | {r['cv_auc_mean']:.4f} ± {r['cv_auc_sd']:.4f} | {r['cv_auc_mean_39_folds_2023_01_to_2026_03']:.4f} | "
                  f"{r['posthoc_cv_auc_mean_folds_2024_10_on']:.4f} | {100 * r['pct_folds_ge_050']:.0f}% | "
                  f"{r['worst_fold']} {r['worst_fold_auc']:.4f} | "
                  + " | ".join(f4(r['per_year_mean'][y]) for y in ("2023", "2024", "2025", "2026"))
                  + f" | {cim} | {r['pooled_cv_auc']:.4f}{cip} | {f4(r['holdout_auc'])}{cih} | "
                  + (pct(hs, 2) if hs is not None else "n/a")
                  + f" | {ic.get('cv_mean_ic', float('nan')):+.4f} ({ic.get('cv_nw_t_lag20', float('nan')):.2f}) |")
    md.append("\n### Mean training rows per fold, by year\n")
    md.append("| model | 2023 | 2024 | 2025 | 2026 | holdout |")
    md.append("|---|---:|---:|---:|---:|---:|")
    for m in order:
        r = lg[m]
        if r.get("mean_n_train_by_year"):
            ny = r["mean_n_train_by_year"]
            md.append(f"| {m} | " + " | ".join(f"{ny[y]:,.0f}" if y in ny else "n/a" for y in ("2023", "2024", "2025", "2026"))
                      + f" | {r['n_train_by_fold'].get('holdout') or 0:,} |")
    md.append("\n## Paired deltas A − B (20-session moving blocks on the pooled 43-fold test dates, identical draws)\n")
    md.append("| A − B | Δ CV mean [95% CI] | P(Δ>0) | Δ pooled CV [95% CI] | Δ holdout [95% CI] | folds won | month-level paired t |")
    md.append("|---|---|---:|---|---|---:|---:|")
    for k, r in S["bootstrap"]["pairs"].items():
        md.append(f"| {k} | {r['cv_mean']['delta']:+.4f} [{r['cv_mean']['ci95'][0]:+.4f}, {r['cv_mean']['ci95'][1]:+.4f}] | "
                  f"{r['cv_mean']['p_gt_0']:.3f} | {r['pooled_cv']['delta']:+.4f} [{r['pooled_cv']['ci95'][0]:+.4f}, "
                  f"{r['pooled_cv']['ci95'][1]:+.4f}] | {r['holdout']['delta']:+.4f} [{r['holdout']['ci95'][0]:+.4f}, "
                  f"{r['holdout']['ci95'][1]:+.4f}] | {r['folds_won']} | {r['month_level_paired_t']:+.2f} |")
    sel = S["nested_selection"]
    md.append("\n## Nested selection per year\n")
    md.append("| year | window | k (mean inner AUC per k) | selected | ∩ pilot 10 |")
    md.append("|---|---|---|---|---:|")
    for y, r in sel["per_year"].items():
        kc = ", ".join(f"{k}: {v:.4f}" for k, v in r["k_curve_mean_inner_auc"].items())
        md.append(f"| {y} | {r['window']['first_date']} .. {r['window']['train_end']} ({r['window']['sessions']} sessions) | "
                  f"{r['k_selected']} ({kc}) | {', '.join(r['selected'])} | {r['n_overlap_selected_with_pilot10']}/{len(r['selected'])} |")
    P = S.get("portfolio")
    if P:
        N = str(N_HEADLINE)
        for seg in ("combined", "cv", "holdout"):
            md.append(f"\n## Portfolio, {seg} OOS, net 20 bps/side (DSR at N={N}; combined = signal dates 2023-01-02 .. 2026-09-16)\n")
            md.append("| book | ann. return | excess vs EW (ann.) | Sharpe [95% CI] | IR [95% CI] | max DD | turnover | months > 0 | ann. @10 / 40 bps | PSR | DSR |")
            md.append("|---|---:|---:|---|---|---:|---:|---:|---|---:|---:|")
            for k, b in P["books"].items():
                c = b["segments"][seg]["20bps"]
                d = P["dsr"]["books"][k]["skill"][N]
                ls = k.endswith("|ls_decile")
                exc = "(L–S)" if ls else pct(c["excess_ann_vs_ew_252_20"])
                ir = "—" if ls else f"{c['ir']:+.2f} [{c['ir_ci95'][0]:+.2f}, {c['ir_ci95'][1]:+.2f}]"
                key10 = "ann_return_252_20" if ls else "excess_ann_vs_ew_252_20"
                c10, c40 = b["segments"][seg]["10bps"][key10], b["segments"][seg]["40bps"][key10]
                md.append(f"| {k} | {pct(c['ann_return_252_20'])} | {exc} | {c['sharpe']:+.2f} [{c['sharpe_ci95'][0]:+.2f}, "
                          f"{c['sharpe_ci95'][1]:+.2f}] | {ir} | {pct(c['max_dd'])} | {100 * b['turnover_per_rebalance']:.0f}% | "
                          + (f"{b['months_positive']}/{b['n_months']}" if seg == "combined" else "") + f" | {pct(c10)} / {pct(c40)} | "
                          + (f"{d['psr_vs_0']:.3f} | {d['dsr']:.3f} |" if seg == "combined" else "— | — |"))
            for nm in ("ew_universe", "ew_liquid"):
                c = P["benchmarks"][nm][seg]
                md.append(f"| *{nm} (passive)* | {pct(c['tranche']['ann_return_252_h'])} | — | {c['daily']['sharpe']:+.2f} "
                          f"[{c['daily']['sharpe_ci95'][0]:+.2f}, {c['daily']['sharpe_ci95'][1]:+.2f}] | — | {pct(c['daily']['max_dd'])} | "
                          f"{100 * P['benchmarks'][nm]['turnover_per_rebalance']:.0f}% | | | | |")
    ex = S.get("score_exposures_mean_per_date_spearman", {})
    if ex:
        md.append("\n## What the rankings are made of: mean per-date Spearman of score with characteristics (43 CV months; up / down months)\n")
        md.append("| model | " + " | ".join(EXPO_FEATS) + " |")
        md.append("|---|" + "---|" * len(EXPO_FEATS))
        for m, e in ex.items():
            md.append(f"| {m} | " + " | ".join(f"{e[f]['cv_mean']:+.2f} ({e[f]['up_months']:+.2f} / {e[f]['down_months']:+.2f})"
                                               for f in EXPO_FEATS) + " |")
    md.append("\n## Gates (SCALE_UP.md, pre-registered)\n")
    md.append("| gate | " + " | ".join(S["gates"]) + " |")
    md.append("|---|" + "---|" * len(S["gates"]))
    for gk in ("1", "2", "3", "4", "5"):
        cells = []
        name = None
        for m, g in S["gates"].items():
            if gk in g:
                name = g[gk]["name"]
                cells.append(f"{g[gk]['number']} **{'PASS' if g[gk]['pass'] else 'FAIL'}**")
            else:
                cells.append("n/a")
        md.append(f"| {gk}. {name} | " + " | ".join(cells) + " |")
    md.append("| passes | " + " | ".join(f"{g['n_pass']}/5" for g in S["gates"].values()) + " |")
    ph = S.get("posthoc_stability_comparison", {})
    md.append("\n### POST-HOC (not pre-registered) stability comparison — the gate verdicts above stand\n")
    md.append("| model | CV mean | sd | worst fold | folds < 0.50 | holdout AUC | holdout decile spread | mean fold decile spread |")
    md.append("|---|---:|---:|---|---:|---:|---:|---:|")
    for m, r in ph.items():
        if m == "label":
            continue
        md.append(f"| {m} | {r['cv_auc_mean']:.4f} | {r['cv_auc_sd']:.4f} | {r['worst_fold']} {r['worst_fold_auc']:.4f} | "
                  f"{r['n_folds_lt_050']} | {f4(r['holdout_auc'])} | "
                  + (pct(r['holdout_decile_spread'], 2) if r.get('holdout_decile_spread') is not None else "n/a") + " | "
                  + (pct(r['mean_fold_decile_spread'], 2) if r.get('mean_fold_decile_spread') is not None else "n/a") + " |")
    (OUT / "tables.md").write_text("\n".join(md) + "\n")


# =========================================================================== #
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-portfolio", action="store_true")
    ap.add_argument("--B", type=int, default=1000)
    ap.add_argument("--port-scorers", nargs="+", default=None, help="TEST ONLY: subset of scorers (relaxes the N check)")
    a = ap.parse_args()
    splits = json.loads((DATA_5Y / "splits.json").read_text())
    feats = json.loads((DATA_5Y / "manifest.json").read_text())["features"]
    base = load_base(splits, feats)
    log(f"base: {len(base):,} test rows, {base['date'].nunique()} signal dates")
    scores, meta = load_scores(base)
    log(f"models with preds: {[m for m in scores]}")
    lg = league(base, scores, meta, splits)
    for m, r in lg.items():
        log(f"{m:22s} cv {r['cv_auc_mean']:.4f}±{r['cv_auc_sd']:.4f} ge50 {r['pct_folds_ge_050']:.0%} worst "
            f"{r['worst_fold']} {r['worst_fold_auc']:.4f} pooled {r['pooled_cv_auc']:.4f} ho {r['holdout_auc']:.4f}")
    bt = bootstrap(base, scores, splits, [m for m in BOOT_MODELS if m in lg], a.B)
    bs = boot_summary(bt, lg)
    wjson(OUT / "bootstrap_5y.json", {"generated_at": pd.Timestamp.now().isoformat(timespec="seconds"),
                                      "generated_by": "ml/scale5y_report.py (seed 108)", **bs})
    log("bootstrap_5y.json written")
    ric, icd = ic_block(base, {m: s_ for m, s_ in scores.items() if m in lg}, splits)
    log("rank-IC done")
    expo = exposures(base, {m: s_ for m, s_ in scores.items() if m in lg}, icd)
    log("exposures done")
    rg = regimes(base, scores, icd, feats, lg)
    wjson(OUT / "regimes_5y.json", {"generated_at": pd.Timestamp.now().isoformat(timespec="seconds"),
                                    "generated_by": "ml/scale5y_report.py (seed 108)", **rg})
    (OUT / "regimes_5y.md").write_text(regimes_md(clean(rg)))
    log(f"regimes_5y.json/.md written: {rg['n_cv_months_majority_inverted']} majority-inverted CV months")
    sel = json.loads((OUT / "nested_selection.json").read_text())
    port = None
    if not a.skip_portfolio:
        port = portfolio(base, scores, a.port_scorers)
        if a.port_scorers:
            port["TEST_SUBSET_ONLY"] = True
        wjson(OUT / "portfolio_5y.json", {"generated_at": pd.Timestamp.now().isoformat(timespec="seconds"),
                                          "generated_by": "ml/scale5y_report.py (seed 108)", **port})
        log("portfolio_5y.json written")
    G = gates(lg, bs, sel, port)
    S = {"generated_at": pd.Timestamp.now().isoformat(timespec="seconds"),
         "generated_by": "ml/scale5y_report.py (seed 108)",
         "files": {"bootstrap": "bootstrap_5y.json", "regimes": "regimes_5y.json / regimes_5y.md",
                   "portfolio": "portfolio_5y.json", "selection": "nested_selection.json", "tables": "tables.md"},
         "dataset": {k: v for k, v in json.loads((DATA_5Y / "manifest.json").read_text()).items() if k != "features"},
         "n_test_rows": int(len(base)), "n_signal_dates": int(base["date"].nunique()),
         "models_present": list(lg), "league": lg,
         "bootstrap": bs, "rank_ic": ric, "score_exposures_mean_per_date_spearman": expo,
         "regimes": {"definition": rg["definition"], "groups": rg["groups"], "counts": rg["counts"],
                     "n_cv_months_majority_inverted": rg["n_cv_months_majority_inverted"],
                     "majority_inverted_months": rg["majority_inverted_months"],
                     "april_2026_inverted_share": rg["april_2026_inverted_share"],
                     "months_at_least_as_inverted_as_2026_04": rg["months_at_least_as_inverted_as_2026_04"]},
         "nested_selection": {"per_year": {y: {k: v for k, v in r.items() if k in (
             "window", "k_curve_mean_inner_auc", "k_selected", "selected", "top10", "overlap_selected_with_pilot10",
             "n_overlap_selected_with_pilot10", "n_overlap_top10_with_pilot10", "suff_features_selected",
             "suff_rank_in_order")} for y, r in sel["per_year"].items()},
             "stability": sel["stability"], "every_year": sel["features_selected_every_year"],
             "any_year": sel["features_selected_any_year"]},
         "exit_date_purge": {m: meta[m]["json"].get("exit_date_purge") for m in lg
                             if meta[m]["json"] and meta[m]["json"].get("exit_date_purge")},
         "portfolio_headline": None if port is None else {
             k: {"ann_return_20bps": b["segments"]["combined"]["20bps"]["ann_return_252_20"],
                 "excess_vs_ew_20bps": b["segments"]["combined"]["20bps"].get("excess_ann_vs_ew_252_20"),
                 "sharpe": b["segments"]["combined"]["20bps"]["sharpe"],
                 "max_dd": b["segments"]["combined"]["20bps"]["max_dd"],
                 "turnover": b["turnover_per_rebalance"], "months_positive": f"{b['months_positive']}/{b['n_months']}",
                 "psr": port["dsr"]["books"][k]["skill"][str(N_HEADLINE)]["psr_vs_0"],
                 "dsr": port["dsr"]["books"][k]["skill"][str(N_HEADLINE)]["dsr"]} for k, b in port["books"].items()},
         "dsr_trials": {"TRIALS": TRIALS, "N_headline": N_HEADLINE, "N_sensitivity": N_SENSITIVITY},
         "gates": G, "posthoc_stability_comparison": posthoc_stability(lg)}
    wjson(OUT / "scale5y_summary.json", S)
    write_tables(clean({**S, "portfolio": port}))
    for m, g in G.items():
        log(f"GATES {m}: " + "; ".join(f"{k}={'PASS' if v['pass'] else 'FAIL'}" for k, v in g.items() if isinstance(v, dict)))
    log("wrote scale5y_summary.json + tables.md")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""5-year scale-up report (agent: lead-scale5y).

Reads the 5-year walk-forward results in ml/results/scale5y/ (core duel from
ml/scale5y.py: champion10, all51, lr_l2, baseline_mom; nested runs from
ml/scale5y_nested.py: nested_lgbm, nested_lr_l2, nested_ensemble_rank and its
members) and writes ml/results/scale5y/scale5y_summary.json + tables.md:

1. league over the 43 monthly folds (mean, sd, % folds >= 0.50, worst fold,
   per-year means, pooled CV AUC, holdout);
2. 20-session block bootstrap (B=1000, seed 108, identical draws for every
   model => paired deltas).  Blocks of 20 consecutive test sessions are drawn
   WITHIN folds (a block never spans two fold models; circular inside the fold)
   and ceil(M/20) blocks are drawn per replicate across the M CV test dates, so
   each replicate re-weights both dates within a month and months against each
   other (a block ~ a month).  The literal per-fold-only variant (each fold
   resampled on its own ~21 dates with 20-session blocks) is near-degenerate --
   it cannot move a fold's AUC -- and is reported only as a sensitivity row;
3. per-date rank-IC of score vs y_excess_20d: mean, Newey-West t (20 lags),
   month-level t, block-bootstrap CI;
4. regime table (sign of the universe-median 20d forward return per test month,
   and calendar year): AUC and top-decile 20d excess vs the EQUAL-WEIGHT
   universe; count of months that look like 2026-04 (most features' IC inverted);
5. portfolio on the 5-year OOS signal dates through ml/strategy_backtest.py's
   engine (imported, defaults untouched; prices = equity_features open/turnover
   from nse_market.duckdb opened read-only): top decile and liquid-tercile top
   decile, long-only, 20 bps/side; Sharpe with month-block CI, max DD, active vs
   EW, turnover, monthly hit vs EW, PSR/DSR with N = audit ledger + this run's
   trials;
6. SCALE_UP.md gates 1-5.

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
BOOT_MODELS = ["nested_lgbm", "all51", "champion10", "lr_l2", "baseline_mom", "nested_lr_l2",
               "nested_ensemble_rank"]
PORT_SCORERS = ["nested_lgbm", "all51", "champion10", "baseline_mom", HEUR, "nested_ensemble_rank"]
BASKETS = ("top_decile", "liq_top_decile")
COST_KEY = "20bps"
# Trial ledger from the audit (ml/results/audit/audit.json T7); this run's trials are added below.
LEDGER = {"38 distinct full-protocol configs": 38, "77 = + 2-fold hyper-parameter screens": 77,
          "151 = + univariate feature screens": 151}
HEADLINE_LEDGER = "77 = + 2-fold hyper-parameter screens"
PAPER_BOOK = (CHAMP, "liq_top_decile")       # STRATEGY.md: champion liquid-tercile top decile, long-only
SUFF = ["deliv_value_share_20", "amihud_20"]
MONTH_LIKE = "2026-04"

T0 = time.time()


def log(msg: str) -> None:
    print(f"[report +{time.time() - T0:6.0f}s] {msg}", flush=True)


def clean(o):
    return sb.clean_json(o)


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
    scores[HEUR] = base["cs_rank_mom_20"].to_numpy(float)
    meta[HEUR] = {"json": None, "coverage": float(np.isfinite(scores[HEUR]).mean())}
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
        js = meta[m]["json"]
        if js is not None:
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
    M = int(msz.sum())
    allcv = np.concatenate([cdates[f] for f in cvf])
    assert (np.diff(allcv.astype("int64")) > 0).all()
    fold_of = np.repeat(np.arange(len(cvf)), msz)
    loc = np.arange(M) - off[fold_of]
    rng = np.random.default_rng(SEED)
    nb = int(math.ceil(M / BLOCK))
    starts = rng.integers(0, M, size=(Bn, nb))
    fs_, ls_ = fold_of[starts], loc[starts]
    idx = off[fs_][..., None] + (ls_[..., None] + np.arange(BLOCK)) % msz[fs_][..., None]
    cnt = np.zeros((Bn, M))
    for b in range(Bn):
        cnt[b] = np.bincount(idx[b].ravel(), minlength=M)
    W = np.column_stack([cnt[:, off[i]:off[i] + msz[i]].sum(1) for i in range(len(cvf))])   # (B, folds)
    mult = W / msz[None, :]
    # literal variant: each fold resampled on its own dates (20-session circular blocks)
    rng2 = np.random.default_rng(SEED + 1)
    within = {f: _block_counts_within(len(cdates[f]), BLOCK, Bn, rng2) for f in cvf}
    hd = np.unique(dts[fo == "holdout"])
    rng3 = np.random.default_rng(SEED + 2)
    hcnt = _block_counts_within(len(hd), BLOCK, Bn, rng3)
    cvrows = np.flatnonzero(base["segment"].to_numpy() == "cv")
    code_cv = np.searchsorted(allcv, dts[cvrows])
    hrows = np.flatnonzero(fo == "holdout")
    hcode = np.searchsorted(hd, dts[hrows])
    frows = {f: np.flatnonzero(fo[cvrows] == f) for f in cvf}
    fcode = {f: np.searchsorted(cdates[f], dts[cvrows][frows[f]]) for f in cvf}
    draws = {}
    for m in models:
        if m not in scores:
            continue
        sc = scores[m]
        if not np.isfinite(sc[cvrows]).all():
            log(f"bootstrap: {m} has missing CV scores -- skipped")
            continue
        t1 = time.time()
        eng_f = {f: WeightedAUC(sc[cvrows][frows[f]], y[cvrows][frows[f]]) for f in cvf}
        eng_p = WeightedAUC(sc[cvrows], y[cvrows])
        eng_h = WeightedAUC(sc[hrows], y[hrows])
        A = np.full((Bn, len(cvf)), np.nan)
        Aw = np.full((Bn, len(cvf)), np.nan)
        pooled = np.empty(Bn)
        ho = np.empty(Bn)
        for b in range(Bn):
            w = cnt[b][code_cv]
            for i, f in enumerate(cvf):
                if W[b, i] > 0:
                    A[b, i] = eng_f[f].auc(w[frows[f]])
                Aw[b, i] = eng_f[f].auc(within[f][b][fcode[f]])
            pooled[b] = eng_p.auc(w)
            ho[b] = eng_h.auc(hcnt[b][hcode])
        cv_mean = np.nansum(np.nan_to_num(A) * mult, 1) / np.where(W > 0, mult, 0).sum(1)
        draws[m] = {"cv_mean": cv_mean, "pooled_cv": pooled, "holdout": ho,
                    "cv_mean_within_fold_only": Aw.mean(1)}
        log(f"bootstrap {m}: {time.time() - t1:.0f}s")
    return {"draws": draws, "design": {
        "B": Bn, "block_sessions": BLOCK, "n_cv_dates": M, "blocks_per_replicate": nb,
        "n_holdout_dates": int(len(hd)),
        "cv": "20-session circular blocks confined to one fold (a fold = one model's test month); block starts "
              "uniform over all CV test dates; ceil(M/20) blocks per replicate => months re-weighted against each "
              "other as well as dates within months. cv_mean replicate = sum_f mult_f AUC_f(w) / sum_f mult_f, "
              "mult_f = (fold weight)/(fold dates); pooled_cv = weighted AUC over all CV rows",
        "holdout": "20-session circular blocks within the holdout window (audit T14 _block_counts)",
        "within_fold_only": "sensitivity: every fold resampled on its own dates with 20-session blocks (T14 style); "
                            "fold weights fixed => understates month-to-month uncertainty",
        "seeds": [SEED, SEED + 1, SEED + 2]}}


def ci(x) -> list:
    x = np.asarray(x)
    x = x[np.isfinite(x)]
    return [float(np.percentile(x, 2.5)), float(np.percentile(x, 97.5))]


def boot_summary(bt: dict, lg: dict) -> dict:
    out = {"design": bt["design"], "models": {}, "paired_vs_" + CHAMP: {}}
    D = bt["draws"]
    for m, d in D.items():
        out["models"][m] = {
            "cv_auc_mean": lg[m]["cv_auc_mean"], "cv_mean_ci95": ci(d["cv_mean"]), "cv_mean_sd": float(np.std(d["cv_mean"], ddof=1)),
            "p_cv_mean_gt_050": float(np.mean(d["cv_mean"] > 0.5)),
            "pooled_cv_auc": lg[m]["pooled_cv_auc"], "pooled_cv_ci95": ci(d["pooled_cv"]),
            "p_pooled_gt_050": float(np.mean(d["pooled_cv"] > 0.5)),
            "holdout_auc": lg[m]["holdout_auc"], "holdout_ci95": ci(d["holdout"]),
            "cv_mean_ci95_within_fold_only": ci(d["cv_mean_within_fold_only"]),
            "cv_mean_sd_within_fold_only": float(np.std(d["cv_mean_within_fold_only"], ddof=1)),
        }
    if CHAMP in D:
        for m, d in D.items():
            if m == CHAMP:
                continue
            r = {}
            for key, pt in (("cv_mean", "cv_auc_mean"), ("pooled_cv", "pooled_cv_auc"), ("holdout", "holdout_auc")):
                dd = D[CHAMP][key] - d[key]
                r[key] = {"delta": lg[CHAMP][pt] - lg[m][pt], "ci95": ci(dd), "p_gt_0": float(np.mean(dd > 0))}
            dd = D[CHAMP]["cv_mean_within_fold_only"] - d["cv_mean_within_fold_only"]
            r["cv_mean_within_fold_only"] = {"ci95": ci(dd), "p_gt_0": float(np.mean(dd > 0))}
            fa, fb = lg[CHAMP]["fold_aucs"], lg[m]["fold_aucs"]
            diffs = np.array([fa[f] - fb[f] for f in fa if f != "holdout"])
            r["folds_won"] = int((diffs > 0).sum())
            r["month_level_paired_t"] = float(diffs.mean() / (diffs.std(ddof=1) / math.sqrt(len(diffs))))
            out["paired_vs_" + CHAMP][m] = r
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


# =========================================================================== #
# regimes
# =========================================================================== #
def regimes(base, scores, icd, feats, lg) -> dict:
    vfeats = [f for f in feats if not f.endswith("_isnan")] + SUFF
    codes, dmon, nd = icd["codes"], icd["months"], len(icd["dates"])
    yx = base["y_excess_20d"].to_numpy(float)
    yr = base["y_raw_20d"].to_numpy(float)
    # month state = sign of mean (over signal dates) universe-median y_raw_20d
    med_d = base.groupby(codes)["mkt_med"].first().to_numpy()
    ew_d = np.bincount(codes, yr, nd) / np.bincount(codes, minlength=nd)
    months = sorted(set(dmon))
    mstate = {mo: ("up" if med_d[dmon == mo].mean() > 0 else "down") for mo in months}
    mseg = {mo: ("holdout" if mo >= "2026-08" else "cv") for mo in months}
    # feature ICs per month, orientation = sign of the feature's mean daily IC over all CV dates (descriptive)
    cvd = icd["seg"] == "cv"
    fic = {}
    for f in vfeats:
        ic = per_date_ic(codes, base[f].to_numpy(float), yx, nd)
        fic[f] = ic
    orient = {f: float(np.sign(np.nanmean(fic[f][cvd]))) for f in vfeats}
    inv_share = {}
    for mo in months:
        mm = dmon == mo
        neg = [orient[f] * np.nanmean(fic[f][mm]) < 0 for f in vfeats if orient[f] != 0]
        inv_share[mo] = float(np.mean(neg))
    # per-model monthly AUC and top-decile 20d excess vs EW universe
    y = base["label_beat_mkt_20d"].to_numpy(float)
    bm = base["month"].to_numpy()
    rows = {}
    for m in [CHAMP, "all51", "champion10", "lr_l2", "nested_lr_l2", "baseline_mom", "nested_ensemble_rank", HEUR]:
        if m not in scores or m not in lg:
            continue
        sc = scores[m]
        r = pd.Series(sc).groupby(codes).rank(pct=True, method="first").to_numpy()
        n_d = np.bincount(codes, minlength=nd)
        top = r > 0.9
        topm = np.bincount(codes[top], yr[top], nd) / np.maximum(np.bincount(codes[top], minlength=nd), 1)
        ex_d = topm - ew_d
        mon = {}
        for mo in months:
            mm = bm == mo
            mon[mo] = {"auc": float(roc_auc_score(y[mm], sc[mm])), "top_decile_excess_vs_ew_20d": float(np.mean(ex_d[dmon == mo])),
                       "mean_ic": float(np.nanmean(icd["series"][m][dmon == mo]))}
        rows[m] = mon
    def agg(m, sel):
        v = [rows[m][mo] for mo in sel]
        return {"n_months": len(sel), "mean_auc": float(np.mean([x["auc"] for x in v])) if v else None,
                "share_auc_ge_050": float(np.mean([x["auc"] >= 0.5 for x in v])) if v else None,
                "top_decile_excess_vs_ew_20d": float(np.mean([x["top_decile_excess_vs_ew_20d"] for x in v])) if v else None,
                "share_months_excess_gt_0": float(np.mean([x["top_decile_excess_vs_ew_20d"] > 0 for x in v])) if v else None,
                "mean_ic": float(np.mean([x["mean_ic"] for x in v])) if v else None}
    groups = {}
    for lab, sel in {
        "up months (CV)": [mo for mo in months if mstate[mo] == "up" and mseg[mo] == "cv"],
        "down months (CV)": [mo for mo in months if mstate[mo] == "down" and mseg[mo] == "cv"],
        "2023": [mo for mo in months if mo.startswith("2023")],
        "2024": [mo for mo in months if mo.startswith("2024")],
        "2025": [mo for mo in months if mo.startswith("2025")],
        "2026 CV (Jan-Jul)": [mo for mo in months if mo.startswith("2026") and mseg[mo] == "cv"],
        "holdout (Aug-Sep 2026)": [mo for mo in months if mseg[mo] == "holdout"],
        "inverted-feature months (CV, >50% of features' IC against their usual sign)":
            [mo for mo in months if inv_share[mo] > 0.5 and mseg[mo] == "cv"],
        "other CV months": [mo for mo in months if inv_share[mo] <= 0.5 and mseg[mo] == "cv"],
    }.items():
        groups[lab] = {m: agg(m, sel) for m in rows}
        groups[lab]["_months"] = sel
    cv_months = [mo for mo in months if mseg[mo] == "cv"]
    like = [mo for mo in cv_months if inv_share[mo] > 0.5]
    like_april = [mo for mo in cv_months if inv_share[mo] >= inv_share.get(MONTH_LIKE, 1.0)]
    return {
        "definition": {"state": "sign of the mean over the month's signal dates of the universe-median y_raw_20d",
                       "ew_universe": "equal-weight mean y_raw_20d of all clean-labeled universe rows of the date",
                       "top_decile_excess_vs_ew_20d": "per date: mean y_raw_20d of the top 10% by score minus the EW "
                                                      "universe; gross of costs; averaged over the month's dates",
                       "inverted_share": f"share of the {len(vfeats)} value features (40 base + 2 sufficiency, *_isnan "
                                         "excluded) whose monthly mean rank-IC vs y_excess_20d has the opposite sign "
                                         "to the feature's 43-month mean (descriptive orientation)"},
        "month_state": mstate, "month_segment": mseg,
        "universe_median_20d_by_month": {mo: float(med_d[dmon == mo].mean()) for mo in months},
        "ew_universe_20d_by_month": {mo: float(ew_d[dmon == mo].mean()) for mo in months},
        "inverted_feature_share_by_month": inv_share,
        "feature_orientation": orient,
        "n_cv_months_majority_inverted": len(like), "majority_inverted_months": like,
        "april_2026_inverted_share": inv_share.get(MONTH_LIKE),
        "n_cv_months_at_least_as_inverted_as_2026_04": len(like_april), "months_at_least_as_inverted_as_2026_04": like_april,
        "groups": groups, "by_month": rows,
        "n_up_cv_months": sum(mstate[mo] == "up" for mo in cv_months),
        "n_down_cv_months": sum(mstate[mo] == "down" for mo in cv_months),
    }


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


def portfolio(base, scores, n_trials_models: int) -> dict:
    t1 = time.time()
    sessions, tick, O, adv20 = load_prices(base)
    blocks, check = sb.build_blocks(base, sessions, tick, O, adv20)
    log(f"portfolio: {len(blocks)} signal dates, exit-mark/label match {check['exit_mark_matches_label_frac']:.5f} "
        f"({time.time() - t1:.0f}s)")
    H = sb.HORIZON
    eng = sb.Engine(blocks, sessions, len(tick), H)
    cal = eng.cal
    month_of = np.array([b.month for b in blocks])
    months = sorted(set(month_of))
    state = {}
    for mo in months:
        mm = month_of == mo
        state[mo] = "up" if eng.med[mm].mean() > 0 else "down"
    bench = {}
    for name, bd in eng.bench.items():
        bench[name] = {}
        for seg in sb.SEGMENTS:
            mk = cal.masks[seg]
            x = cal.seg_series(bd["D"], seg)
            bench[name][seg] = {"tranche": sb.tranche_stats(bd["R"][mk], bd["R"][mk], eng.med[mk], H=H),
                                "daily": sb.series_stats(x, cal.expo[seg], cal.month_codes[seg], cal.draws[seg],
                                                         rf=sb.RF_ANNUAL)}
    books, skill, raw = {}, {}, {}
    scorers = [s for s in PORT_SCORERS if s in scores and np.isfinite(scores[s]).all()]
    EX = cal.expo["combined"]
    c = int(COST_KEY.replace("bps", "")) / 1e4
    for sc in scorers:
        for bk in BASKETS:
            r = eng.run(scores[sc], bk)
            bname = eng.bench_for(bk)
            R = r["_tranche"][COST_KEY]["R"]
            act = R - eng.bench[bname]["R"]
            mon_act = pd.Series(act).groupby(month_of).mean()
            res = r["results"]
            ent = {"benchmark": bname, "basket_size_mean": r["basket_size_mean"],
                   "turnover_per_rebalance": r["turnover_per_rebalance"], "capacity": r["capacity"],
                   "segments": {seg: {"ann_return_252_20": res[COST_KEY][seg]["tranche"]["ann_return_252_h"],
                                      "ann_return_gross": res["gross"][seg]["tranche"]["ann_return_252_h"],
                                      "sharpe": res[COST_KEY][seg]["daily"]["sharpe"],
                                      "sharpe_ci95": res[COST_KEY][seg]["daily"]["sharpe_ci95"],
                                      "ann_vol": res[COST_KEY][seg]["daily"]["ann_vol"],
                                      "max_dd": res[COST_KEY][seg]["daily"]["max_dd"],
                                      "active_ann_vs_ew_252_20": res[COST_KEY][seg]["tranche"]["active_ann_252_h"],
                                      "active_ann_daily": res[COST_KEY][seg]["daily_active"]["ann_mean_daily"],
                                      "ir": res[COST_KEY][seg]["daily_active"]["sharpe"],
                                      "ir_ci95": res[COST_KEY][seg]["daily_active"]["sharpe_ci95"],
                                      "active_max_dd": res[COST_KEY][seg]["daily_active"]["max_dd"],
                                      "hit_vs_ew_tranches": res[COST_KEY][seg]["tranche"]["hit_rate_vs_ew"],
                                      "beta_vs_bench": res[COST_KEY][seg]["beta_alpha_vs_benchmark"]["beta_vs_benchmark"],
                                      "alpha_ann_vs_bench": res[COST_KEY][seg]["beta_alpha_vs_benchmark"]["alpha_ann"],
                                      "active_ann_40bps": res["40bps"][seg]["tranche"]["active_ann_252_h"],
                                      "active_ann_no_netting": res["20bps_no_netting"][seg]["tranche"]["active_ann_252_h"]}
                                for seg in sb.SEGMENTS},
                   "monthly_net_active_vs_ew_20d": {k: float(v) for k, v in mon_act.items()},
                   "months_beating_ew": int((mon_act > 0).sum()), "n_months": int(len(mon_act)),
                   "share_months_beating_ew": float((mon_act > 0).mean()),
                   "share_cv_months_beating_ew": float((mon_act[[mo for mo in mon_act.index if mo < "2026-08"]] > 0).mean()),
                   "net_active_20d_by_state": {st: float(np.mean(act[np.array([state[mo] == st for mo in month_of])]))
                                               for st in ("up", "down")},
                   "net_active_20d_by_year": {yy: float(np.mean(act[np.char.startswith(month_of.astype(str), yy)]))
                                              for yy in ("2023", "2024", "2025", "2026")}}
            # daily skill (net active vs EW) and absolute (net - rf) series, combined program
            Lp, Wl, _ = sb.leg(blocks, [x[0] for x in r["_mem"]], len(tick), H)
            tl = sb.trade_fracs(Wl, H)
            rr, _ = sb.long_net(Lp, tl["buy"], tl["sell"], c)
            x = cal.seg_series(cal.to_days(rr), "combined")
            xb = cal.seg_series(eng.bench[bname]["D"], "combined")
            skill[(sc, bk)] = x - xb
            raw[(sc, bk)] = x - sb.RF_ANNUAL / sb.PPY
            books[f"{sc}|{bk}"] = ent
            log(f"portfolio {sc}|{bk}: ann {ent['segments']['combined']['ann_return_252_20']:+.3f} active "
                f"{ent['segments']['combined']['active_ann_vs_ew_252_20']:+.3f} IR {ent['segments']['combined']['ir']:+.2f} "
                f"months>EW {ent['months_beating_ew']}/{ent['n_months']}")
    # ---- PSR / DSR
    keys = list(skill)
    n_books = len(keys)
    n_mine = n_trials_models + n_books
    sr = {k: sb.wmoments(skill[k], EX)[0] / sb.wmoments(skill[k], EX)[1] for k in keys}
    srr = {k: sb.wmoments(raw[k], EX)[0] / sb.wmoments(raw[k], EX)[1] for k in keys}
    var_sr = float(np.var(list(sr.values()), ddof=1))
    var_srr = float(np.var(list(srr.values()), ddof=1))
    dsr = {"method": "Bailey & Lopez de Prado via ml/strategy_backtest.py dsr_block: daily net (20 bps) series of the "
                     "combined 5-year OOS program, exposure-weighted moments, T = Kish n_eff; SR0 from the variance of "
                     f"daily SRs across this run's {n_books} books",
           "n_trials": {"this_run_model_configs": n_trials_models, "this_run_portfolio_books": n_books,
                        "this_run_total": n_mine,
                        **{f"N_ledger_{k}": v + n_mine for k, v in LEDGER.items()}},
           "headline_N": LEDGER[HEADLINE_LEDGER] + n_mine,
           "var_sr_skill": var_sr, "var_sr_absolute": var_srr, "books": {}}
    for k in keys:
        lab = f"{k[0]}|{k[1]}"
        e = {"skill_active_vs_ew": {}, "absolute_net_minus_rf": {}}
        for nm, N0 in LEDGER.items():
            N = N0 + n_mine
            e["skill_active_vs_ew"][str(N)] = sb.dsr_block(skill[k], EX, var_sr, N, lab + " active", sb.PPY)
            e["absolute_net_minus_rf"][str(N)] = sb.dsr_block(raw[k], EX, var_srr, N, lab + " abs", sb.PPY)
        dsr["books"][lab] = e
    ew_raw = cal.seg_series(eng.bench["ew_universe"]["D"], "combined") - sb.RF_ANNUAL / sb.PPY
    dsr["ew_universe_absolute_reference"] = sb.dsr_block(ew_raw, EX, var_srr, dsr["headline_N"], "ew_universe abs", sb.PPY)
    return {"n_signal_dates": len(blocks), "path_check": check, "month_state": state, "benchmarks": bench,
            "books": books, "dsr": dsr, "scorers": scorers, "baskets": list(BASKETS),
            "seconds": round(time.time() - t1, 1)}


# =========================================================================== #
# gates
# =========================================================================== #
def gates(lg, bs, sel, port) -> dict:
    g = {}
    pv = bs.get("paired_vs_" + CHAMP, {})
    if "lr_l2" in pv:
        d = pv["lr_l2"]["cv_mean"]
        g["1_champion_beats_lr_l2_cv_mean_ci_excludes_0"] = {
            "number": f"nested_lgbm - lr_l2 CV mean {d['delta']:+.4f}, 95% CI [{d['ci95'][0]:+.4f}, {d['ci95'][1]:+.4f}]",
            "pass": bool(d["delta"] > 0 and d["ci95"][0] > 0)}
    c = lg[CHAMP]
    g["2_fold_auc_ge_050_in_90pct_of_months"] = {
        "number": f"{100 * c['pct_folds_ge_050']:.0f}% of 43 folds >= 0.50 ({c['n_folds_lt_050']} below; worst "
                  f"{c['worst_fold']} {c['worst_fold_auc']:.4f})", "pass": bool(c["pct_folds_ge_050"] >= 0.90)}
    if port:
        b = port["books"].get(f"{CHAMP}|top_decile")
        bl = port["books"].get(f"{CHAMP}|liq_top_decile")
        if b:
            g["3_top_decile_beats_ew_in_75pct_of_months_net_20bps"] = {
                "number": f"top decile beat EW in {b['months_beating_ew']}/{b['n_months']} signal months "
                          f"({100 * b['share_months_beating_ew']:.0f}%); liquid-tercile book "
                          f"{bl['months_beating_ew']}/{bl['n_months']} ({100 * bl['share_months_beating_ew']:.0f}%)",
                "pass": bool(b["share_months_beating_ew"] >= 0.75)}
    yrs = sorted(sel["per_year"])
    ov = [sel["stability"][f"{a}->{b}"]["top10_overlap"] for a, b in zip(yrs[:-1], yrs[1:])]
    ovs = [sel["stability"][f"{a}->{b}"]["selected_overlap"] for a, b in zip(yrs[:-1], yrs[1:])]
    g["4_selected_feature_overlap_ge_7_of_10_across_yearly_reselections"] = {
        "number": f"consecutive-year top-10 overlap {ov} (min {min(ov)}/10); selected-set overlap {ovs} with k = "
                  f"{[sel['per_year'][y]['k_selected'] for y in yrs]}",
        "pass": bool(min(ov) >= 7)}
    if port:
        lab = f"{PAPER_BOOK[0]}|{PAPER_BOOK[1]}"
        N = str(port["dsr"]["headline_N"])
        e = port["dsr"]["books"][lab]["skill_active_vs_ew"][N]
        a = port["dsr"]["books"][lab]["absolute_net_minus_rf"][N]
        best = max(port["dsr"]["books"], key=lambda k: port["dsr"]["books"][k]["skill_active_vs_ew"][N]["dsr"])
        bd = port["dsr"]["books"][best]["skill_active_vs_ew"][N]["dsr"]
        g["5_dsr_ge_095_paper_portfolio"] = {
            "number": f"{lab} active vs EW-liquid: SR {e['sr_annualised']:+.2f}/yr, PSR {e['psr_vs_0']:.3f}, DSR "
                      f"{e['dsr']:.3f} at N={N} (absolute net-rf DSR {a['dsr']:.3f}); best book {best} DSR {bd:.3f}",
            "pass": bool(e["dsr"] >= 0.95)}
    return g


def gates_for(model: str, lg, bs_full, port) -> dict:
    """Gate 1-3 numbers for another model (no promotion claim): same tests."""
    out = {}
    D = bs_full["draws"]
    if model in D and "lr_l2" in D and model != "lr_l2":
        dd = D[model]["cv_mean"] - D["lr_l2"]["cv_mean"]
        out["1"] = {"delta_cv_mean_vs_lr_l2": lg[model]["cv_auc_mean"] - lg["lr_l2"]["cv_auc_mean"], "ci95": ci(dd),
                    "pass": bool(lg[model]["cv_auc_mean"] > lg["lr_l2"]["cv_auc_mean"] and ci(dd)[0] > 0)}
    out["2"] = {"pct_folds_ge_050": lg[model]["pct_folds_ge_050"], "pass": bool(lg[model]["pct_folds_ge_050"] >= 0.9)}
    if port and f"{model}|top_decile" in port["books"]:
        b = port["books"][f"{model}|top_decile"]
        out["3"] = {"share_months_beating_ew": b["share_months_beating_ew"], "pass": bool(b["share_months_beating_ew"] >= 0.75)}
        N = str(port["dsr"]["headline_N"])
        out["5"] = {"dsr_liq_top_decile_active": port["dsr"]["books"][f"{model}|liq_top_decile"]["skill_active_vs_ew"][N]["dsr"],
                    "dsr_top_decile_active": port["dsr"]["books"][f"{model}|top_decile"]["skill_active_vs_ew"][N]["dsr"]}
        out["5"]["pass"] = bool(out["5"]["dsr_liq_top_decile_active"] >= 0.95)
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
          "(seed 108). Narrative: SCALE5Y.md.\n"]
    lg, bs = S["league"], S["bootstrap"]["models"]
    order = [m for m in ["nested_lgbm", "nested_ensemble_rank", "nested_lr_l2", "champion10", "all51", "lr_l2",
                         "baseline_mom", HEUR, "nested_lambdarank", "nested_catboost"] if m in lg]
    md.append("\n## League over 43 monthly folds (2023-01 .. 2026-07) + holdout\n")
    md.append("| model | CV AUC ± sd | % folds ≥ 0.50 | worst fold | 2023 | 2024 | 2025 | 2026 (Jan–Jul) | pooled CV [95% block CI] | CV mean 95% block CI | holdout [CI] | rank-IC (NW t) |")
    md.append("|---|---|---:|---|---:|---:|---:|---:|---|---|---|---|")
    for m in order:
        r = lg[m]
        b = bs.get(m)
        ic = S["rank_ic"].get(m, {})
        md.append(f"| {m} | {r['cv_auc_mean']:.4f} ± {r['cv_auc_sd']:.4f} | {100 * r['pct_folds_ge_050']:.0f}% | "
                  f"{r['worst_fold']} {r['worst_fold_auc']:.4f} | " + " | ".join(f4(r['per_year_mean'][y]) for y in ("2023", "2024", "2025", "2026"))
                  + f" | {r['pooled_cv_auc']:.4f} " + (f"[{b['pooled_cv_ci95'][0]:.4f}, {b['pooled_cv_ci95'][1]:.4f}]" if b else "")
                  + " | " + (f"[{b['cv_mean_ci95'][0]:.4f}, {b['cv_mean_ci95'][1]:.4f}]" if b else "n/a")
                  + f" | {f4(r['holdout_auc'])} " + (f"[{b['holdout_ci95'][0]:.4f}, {b['holdout_ci95'][1]:.4f}]" if b else "")
                  + f" | {ic.get('cv_mean_ic', float('nan')):+.4f} ({ic.get('cv_nw_t_lag20', float('nan')):.2f}) |")
    pv = S["bootstrap"].get("paired_vs_" + CHAMP, {})
    if pv:
        md.append(f"\n## Paired deltas: {CHAMP} minus X (20-session block bootstrap, identical draws)\n")
        md.append("| X | Δ CV mean [95% CI] | P(Δ>0) | Δ pooled CV [95% CI] | Δ holdout [95% CI] | folds won | month-level paired t |")
        md.append("|---|---|---:|---|---|---:|---:|")
        for m, r in pv.items():
            md.append(f"| {m} | {r['cv_mean']['delta']:+.4f} [{r['cv_mean']['ci95'][0]:+.4f}, {r['cv_mean']['ci95'][1]:+.4f}] | "
                      f"{r['cv_mean']['p_gt_0']:.3f} | {r['pooled_cv']['delta']:+.4f} [{r['pooled_cv']['ci95'][0]:+.4f}, "
                      f"{r['pooled_cv']['ci95'][1]:+.4f}] | {r['holdout']['delta']:+.4f} [{r['holdout']['ci95'][0]:+.4f}, "
                      f"{r['holdout']['ci95'][1]:+.4f}] | {r['folds_won']}/43 | {r['month_level_paired_t']:+.2f} |")
    sel = S["nested_selection"]
    md.append("\n## Nested selection per year\n")
    md.append("| year | window | k (inner curve) | selected | ∩ pilot 10 |")
    md.append("|---|---|---|---|---:|")
    for y, r in sel["per_year"].items():
        kc = ", ".join(f"{k}:{v:.4f}" for k, v in r["k_curve_mean_inner_auc"].items())
        md.append(f"| {y} | {r['window']['first_date']} .. {r['window']['train_end']} ({r['window']['sessions']} sessions) | "
                  f"{r['k_selected']} ({kc}) | {', '.join(r['selected'])} | {r['n_overlap_selected_with_pilot10']}/{len(r['selected'])} |")
    rg = S["regimes"]
    md.append("\n## Regimes (nested_lgbm unless stated; 20d excess vs EQUAL-WEIGHT universe, gross)\n")
    md.append("| group | months | nested_lgbm AUC | % months AUC ≥ 0.50 | top-decile excess vs EW (20d) | % months > 0 | mean IC | all51 AUC | champion10 AUC | momentum heuristic AUC |")
    md.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for lab, gr in rg["groups"].items():
        c = gr.get(CHAMP)
        if not c or not c["n_months"]:
            continue
        md.append(f"| {lab} | {c['n_months']} | {c['mean_auc']:.4f} | {100 * c['share_auc_ge_050']:.0f}% | "
                  f"{pct(c['top_decile_excess_vs_ew_20d'], 2)} | {100 * c['share_months_excess_gt_0']:.0f}% | {c['mean_ic']:+.4f} | "
                  + " | ".join(f4(gr[m]["mean_auc"]) if m in gr else "n/a" for m in ("all51", "champion10", HEUR)) + " |")
    md.append(f"\nMonths with a majority of features inverted (CV): {rg['n_cv_months_majority_inverted']} of 43 "
              f"({', '.join(rg['majority_inverted_months'])}); 2026-04 inverted share {rg['april_2026_inverted_share']:.2f}; "
              f"months at least as inverted as 2026-04: {rg['n_cv_months_at_least_as_inverted_as_2026_04']}.\n")
    P = S.get("portfolio")
    if P:
        md.append("\n## Portfolio, combined 5-year OOS (signal dates 2023-01-02 .. 2026-09-16), 20 bps/side, long-only\n")
        N = str(P["dsr"]["headline_N"])
        md.append(f"| book | ann. return (net) | Sharpe rf 5.5% [CI] | max DD | active vs EW (ann.) | IR [CI] | turnover | months > EW | DSR active (N={N}) | PSR active | DSR abs |")
        md.append("|---|---:|---|---:|---:|---|---:|---:|---:|---:|---:|")
        for k, b in P["books"].items():
            c = b["segments"]["combined"]
            d = P["dsr"]["books"][k]
            md.append(f"| {k} | {pct(c['ann_return_252_20'])} | {c['sharpe']:+.2f} [{c['sharpe_ci95'][0]:+.2f}, {c['sharpe_ci95'][1]:+.2f}] | "
                      f"{pct(c['max_dd'])} | {pct(c['active_ann_vs_ew_252_20'])} | {c['ir']:+.2f} [{c['ir_ci95'][0]:+.2f}, {c['ir_ci95'][1]:+.2f}] | "
                      f"{100 * b['turnover_per_rebalance']:.0f}% | {b['months_beating_ew']}/{b['n_months']} | "
                      f"{d['skill_active_vs_ew'][N]['dsr']:.3f} | {d['skill_active_vs_ew'][N]['psr_vs_0']:.3f} | "
                      f"{d['absolute_net_minus_rf'][N]['dsr']:.3f} |")
        for nm in ("ew_universe", "ew_liquid"):
            c = P["benchmarks"][nm]["combined"]
            md.append(f"| *{nm} (passive)* | {pct(c['tranche']['ann_return_252_h'])} | {c['daily']['sharpe']:+.2f} | "
                      f"{pct(c['daily']['max_dd'])} | — | — | — | — | — | — | — |")
    md.append("\n## Gates (SCALE_UP.md, pre-registered)\n")
    for k, v in S["gates"].items():
        md.append(f"- **{k}**: {v['number']} — **{'PASS' if v['pass'] else 'FAIL'}**")
    (OUT / "tables.md").write_text("\n".join(md) + "\n")


# =========================================================================== #
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-portfolio", action="store_true")
    ap.add_argument("--B", type=int, default=1000)
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
    ric, icd = ic_block(base, {m: s for m, s in scores.items() if m in lg}, splits)
    log("rank-IC done")
    rg = regimes(base, scores, icd, feats, lg)
    log(f"regimes done: {rg['n_cv_months_majority_inverted']} majority-inverted CV months")
    sel = json.loads((OUT / "nested_selection.json").read_text())
    n_models = len([m for m in CORE + NESTED + MEMBERS if m in lg])
    port = None
    if not a.skip_portfolio:
        port = portfolio(base, scores, n_models)
    S = {"generated_at": pd.Timestamp.now().isoformat(timespec="seconds"),
         "generated_by": "ml/scale5y_report.py (seed 108)",
         "dataset": json.loads((DATA_5Y / "manifest.json").read_text()) | {"features": None},
         "n_test_rows": int(len(base)), "n_signal_dates": int(base["date"].nunique()),
         "models_present": list(lg), "league": lg, "bootstrap": bs, "rank_ic": ric, "regimes": rg,
         "nested_selection": {"per_year": {y: {k: v for k, v in r.items() if k in (
             "window", "k_curve_mean_inner_auc", "k_selected", "selected", "top10", "overlap_selected_with_pilot10",
             "n_overlap_selected_with_pilot10", "n_overlap_top10_with_pilot10", "suff_features_selected",
             "suff_rank_in_order")} for y, r in sel["per_year"].items()},
             "stability": sel["stability"], "every_year": sel["features_selected_every_year"],
             "any_year": sel["features_selected_any_year"]},
         "exit_date_purge": {m: meta[m]["json"].get("exit_date_purge") for m in lg
                             if meta[m]["json"] and meta[m]["json"].get("exit_date_purge")},
         "portfolio": port}
    S["gates"] = gates(lg, bs, sel, port)
    S["gates_other_models"] = {m: gates_for(m, lg, bt, port) for m in ("nested_ensemble_rank", "champion10", "all51", "nested_lr_l2")
                               if m in lg}
    (OUT / "scale5y_summary.json").write_text(json.dumps(clean(S), indent=1, allow_nan=False))
    write_tables(clean(S))
    for k, v in S["gates"].items():
        log(f"GATE {k}: {v['number']} -> {'PASS' if v['pass'] else 'FAIL'}")
    log("wrote scale5y_summary.json + tables.md")


if __name__ == "__main__":
    main()

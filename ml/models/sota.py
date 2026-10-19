#!/usr/bin/env python3
"""State-of-the-art challengers vs the pilot champion (agent: quant-sota).

Champion: lgbm_fs_selected (LightGBM num_leaves=63, lr=0.05, 300 trees,
feature/bagging fraction 0.8, min_data_in_leaf=200, 10 FS-selected features);
clean-data CV AUC 0.5314. Pass mark for a challenger, fixed BEFORE any run in
this module: CV AUC >= 0.5364 (champion + 0.005) AND every CV fold >= 0.50.
The holdout is reported but never used to tune, select or early-stop.

Models (primary task beat_mkt_20d only; seed 108; 2 CPU threads):
  champion_ref         same-box re-run of the champion config: timing, rank-IC,
                       and a reproducibility check vs lgbm_fs_selected_clean
  lgbm_lambdarank      LGBMRanker(lambdarank), query group = date, relevance =
                       y_rank_20d binned to grades 0..9; 10 features
  lgbm_lambdarank_f51  the same on all 51 features
  lgbm_huber           LGBMRegressor(huber, alpha=0.9) on y_excess_20d clipped
                       to +/-0.30; 10 features
  catboost             CatBoostClassifier(depth 6, lr 0.05, <=600 it, l2 5);
                       10 features
  catboost_f51         the same on all 51 features
  patchtst_lite        patch transformer over per-stock 60-session x 14-channel
                       windows (6 patch tokens)
  cs_transformer       self-attention ACROSS the stocks of one date (set model)
  ensemble_rank        per-date rank average of the OOS scores of the champion,
                       lgbm_lambdarank and catboost (no weights fitted)
  dlinear              DLinear (Zeng et al. 2022) on the same 60x14 windows

Inner validation (early stopping only -- never test rows, never the holdout):
the time-ordered tail of each fold's train set (last 15% of train ROWS for
CatBoost, last 15% of train DATES for the networks). The 20 sessions before
the inner-val start are purged from the inner-fit set so that no inner-fit
20-session label window overlaps the inner-val period (the harness embargo
does the same between train and test).

Outputs: ml/results/sota/<model>__beat_mkt_20d.json (harness schema plus
rank_ic / vs_champion extras), ml/results/preds/sota/<model>__beat_mkt_20d
.parquet, ml/results/sota/train_log.txt (per-epoch inner-val AUC),
ml/results/sota/league_summary.json.

Run: cd /home/user/SuryaDhana_AI && python3 -m ml.models.sota [--parts a,b]
"""
from __future__ import annotations

import os

os.environ["OMP_NUM_THREADS"] = "2"  # before numpy / torch imports

import argparse
import json
import random
import time

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F

torch.set_num_threads(2)
try:
    torch.set_num_interop_threads(1)
except RuntimeError:
    pass

from sklearn.metrics import roc_auc_score

import ml.evaluation as ev
from ml.evaluation import (SEED, TASKS, compute_metrics, iter_folds,
                           load_dataset, save_preds, save_results)

# eval_aggregate treats every JSON directly in ml/results/ as a pilot league
# entry, so this study writes to its own folders (save_* read these at call time).
ev.RESULTS_DIR = ev.ML_DIR / "results" / "sota"
ev.PREDS_DIR = ev.ML_DIR / "results" / "preds" / "sota"
SOTA_DIR = ev.RESULTS_DIR
TRAIN_LOG = SOTA_DIR / "train_log.txt"
# Post-fix champion preds: align row-for-row with the current dataset. The
# frozen lgbm_fs_selected preds carry 11,728 rows from the 12 phantom
# holiday-echo days that no longer exist in model_dataset.parquet.
CHAMP_PREDS = ev.ML_DIR / "results" / "preds" / "lgbm_fs_selected_clean__beat_mkt_20d.parquet"

TASK = "beat_mkt_20d"
LABEL, FWD, CLEAN = TASKS[TASK]
FAMILY = "sota"
AGENT = "quant-sota"
CHAMP_CV = 0.5314
PASS_MARK = 0.5364
INNER_VAL_FRAC = 0.15
INNER_PURGE = 20          # sessions = label horizon

CHAMP_PARAMS = dict(num_leaves=63, learning_rate=0.05, n_estimators=300,
                    feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1,
                    min_data_in_leaf=200, num_threads=2, random_state=SEED,
                    verbose=-1)
CB_PARAMS = dict(depth=6, learning_rate=0.05, iterations=600, l2_leaf_reg=5,
                 random_seed=SEED, thread_count=2, verbose=0)
CB_OD_WAIT = 50

SEQ_LEN = 60
PATCH = 10
SEQ_EXTRA = ["ret_1d", "gap_pct", "vol_z_20", "rsi_2"]
SEQ_CAP = 120_000
SEQ_BATCH = 512
SEQ_MAX_EPOCHS = 12
SEQ_PATIENCE = 3
D_MODEL = 64
N_HEADS = 4
N_LAYERS = 2
DROPOUT = 0.2
CS_MAX_EPOCHS = 30
CS_PATIENCE = 5
CS_LR = 5e-4
EPOCH_SECONDS_LIMIT = 90.0
DLINEAR_KERNEL = 25
GRAD_CLIP = 1.0


def log(msg: str, to_file: bool = False) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    if to_file:
        SOTA_DIR.mkdir(parents=True, exist_ok=True)
        with open(TRAIN_LOG, "a") as fh:
            fh.write(line + "\n")


def seed_everything(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def champion_features() -> list[str]:
    fs = json.loads((ev.ML_DIR / "results" / "feature_selection.json").read_text())
    sel = list(fs["selected"]["features"])
    assert len(sel) == 10
    return sel


# ---------------------------------------------------------------------------
# metrics extras: per-date rank IC
# ---------------------------------------------------------------------------
def per_date_rank_ic(dates, score, fwd) -> pd.Series:
    """Spearman(score, y_excess_20d) within each test date."""
    d = pd.DataFrame({"date": dates, "s": np.asarray(score, float),
                      "f": np.asarray(fwd, float)})
    d = d[np.isfinite(d["s"]) & np.isfinite(d["f"])]
    g = d.groupby("date")
    d["rs"] = g["s"].rank()
    d["rf"] = g["f"].rank()
    d["rs"] -= d.groupby("date")["rs"].transform("mean")
    d["rf"] -= d.groupby("date")["rf"].transform("mean")
    num = (d["rs"] * d["rf"]).groupby(d["date"]).sum()
    den = np.sqrt((d["rs"] ** 2).groupby(d["date"]).sum()
                  * (d["rf"] ** 2).groupby(d["date"]).sum())
    return (num / den.replace(0, np.nan)).dropna().sort_index()


def t_naive(x) -> float:
    x = np.asarray(x, float)
    if len(x) < 3 or x.std(ddof=1) == 0:
        return float("nan")
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x))))


def t_newey_west(x, lags: int = 19) -> float:
    """HAC t-stat (Bartlett). Daily ICs of 20-session forward returns overlap
    for 19 sessions, so the naive t overstates significance."""
    x = np.asarray(x, float)
    n = len(x)
    if n < 3:
        return float("nan")
    lags = min(lags, n - 1)
    e = x - x.mean()
    s = e @ e / n
    for lag in range(1, lags + 1):
        s += 2.0 * (1.0 - lag / (lags + 1.0)) * (e[lag:] @ e[:-lag]) / n
    return float(x.mean() / np.sqrt(s / n)) if s > 0 else float("nan")


def ic_block(ic: pd.Series) -> dict:
    return {"mean": float(ic.mean()), "std": float(ic.std(ddof=1)),
            "t_naive": t_naive(ic), "t_nw19": t_newey_west(ic),
            "hit_rate": float((ic > 0).mean()), "n_dates": int(len(ic))}


def summarize(model: str, params: dict, feats: list[str], fold_out: list[dict],
              notes: str, preprocess: str, family: str = FAMILY,
              score_kind: str = "probability", save: bool = True) -> dict:
    """Harness-schema payload (+ extras) -> save_results / save_preds."""
    fold_rows, frames, holdout = [], [], None
    ics_cv, ic_ho = [], None
    for fo in fold_out:
        m = compute_metrics(fo["y"], fo["score"], fo["fwd"])
        ic = per_date_rank_ic(fo["dates"], fo["score"], fo["fwd"])
        m["fold"] = fo["name"]
        m["n_train"] = int(fo["n_train"])
        m["train_seconds"] = round(float(fo["train_s"]), 1)
        m["rank_ic_mean"] = float(ic.mean())
        m["rank_ic_t_naive"] = t_naive(ic)
        m["n_dates"] = int(len(ic))
        if fo["name"] == "holdout":
            holdout, ic_ho = m, ic
        else:
            fold_rows.append(m)
            ics_cv.append(ic)
        frames.append(pd.DataFrame({
            "date": fo["dates"], "ticker": fo["tickers"], "score": fo["score"],
            "y": fo["y"], "fwd": fo["fwd"], "fold": fo["name"]}))
    aucs = [r["auc"] for r in fold_rows]
    cv_mean = float(np.mean(aucs))
    worst = float(np.min(aucs))
    ic_cv = pd.concat(ics_cv).sort_index()
    secs = [fo["train_s"] for fo in fold_out]
    payload = {
        "model": model, "family": family, "agent": AGENT, "task": TASK,
        "params": params, "preprocess": preprocess,
        "n_features": len(feats), "feature_subset": feats,
        "folds": fold_rows,
        "cv_auc_mean": cv_mean,
        "cv_auc_std": float(np.std(aucs)),
        "holdout": holdout,
        "train_seconds": round(float(np.sum(secs)), 1),
        "notes": notes,
        # ---- extras (schema superset) ----
        "score_kind": score_kind,
        "train_seconds_per_fold_mean": round(float(np.mean(secs)), 1),
        "cv_worst_fold_auc": worst,
        "rank_ic": {
            "definition": "per-date Spearman(score, y_excess_20d) over clean "
                          "test rows; t_naive = mean/(sd/sqrt(n_dates)); "
                          "t_nw19 = Newey-West(19 lags) because consecutive "
                          "20-session forward windows overlap",
            "cv": ic_block(ic_cv),
            "holdout": ic_block(ic_ho) if ic_ho is not None else None,
        },
        "vs_champion": {
            "champion": "lgbm_fs_selected (clean)", "champion_cv_auc": CHAMP_CV,
            "pass_mark_cv_auc": PASS_MARK, "delta_cv_auc": cv_mean - CHAMP_CV,
            "all_folds_ge_050": bool(worst >= 0.50),
            "passes": bool(cv_mean >= PASS_MARK and worst >= 0.50),
        },
    }
    if save:
        save_results(payload)
        save_preds(model, TASK, frames)
    ho = holdout or {}
    log(f"[{model}] cv_auc={cv_mean:.4f} (+/-{payload['cv_auc_std']:.4f}) "
        f"worst={worst:.4f} holdout={ho.get('auc', float('nan')):.4f} "
        f"ho_spread={ho.get('decile_spread', float('nan')):+.4f} "
        f"ic_cv={payload['rank_ic']['cv']['mean']:+.4f} "
        f"(t={payload['rank_ic']['cv']['t_naive']:.2f}, "
        f"nw={payload['rank_ic']['cv']['t_nw19']:.2f}) "
        f"s/fold={payload['train_seconds_per_fold_mean']} "
        f"passes={payload['vs_champion']['passes']}", to_file=True)
    return payload


def fold_record(fold, score, train_s, extra=None) -> dict:
    rec = {"name": fold.name, "y": fold.y_test, "score": np.asarray(score, float),
           "fwd": fold.fwd_test, "dates": fold.meta_test["date"].to_numpy(),
           "tickers": fold.meta_test["ticker"].to_numpy(),
           "n_train": len(fold.y_train), "train_s": train_s}
    rec.update(extra or {})
    return rec


# ---------------------------------------------------------------------------
# inner validation splits (time-ordered tail, purged)
# ---------------------------------------------------------------------------
def inner_split_rows(dates: np.ndarray, frac=INNER_VAL_FRAC, purge=INNER_PURGE):
    """val = rows from the date of the row at the (1-frac) quantile of ROWS;
    fit = rows dated before the `purge` sessions preceding val start."""
    assert (dates[1:] >= dates[:-1]).all(), "train rows not date-ordered"
    val_start = dates[int(round(len(dates) * (1 - frac)))]
    ud = np.unique(dates)
    k = int(np.searchsorted(ud, val_start))
    purge_start = ud[max(0, k - purge)]
    return dates < purge_start, dates >= val_start, val_start, purge_start


def inner_split_dates(dates: np.ndarray, frac=INNER_VAL_FRAC, purge=INNER_PURGE):
    """val = last `frac` of distinct train DATES; purge before it."""
    ud = np.unique(dates)
    k = min(max(1, int(round(len(ud) * (1 - frac)))), len(ud) - 1)
    val_start, purge_start = ud[k], ud[max(0, k - purge)]
    return dates < purge_start, dates >= val_start, val_start, purge_start


# ---------------------------------------------------------------------------
# train-fitted scaling (same recipe as harness Preprocessor("scaled"))
# ---------------------------------------------------------------------------
def fit_scaler(X: np.ndarray) -> dict:
    # a channel that is entirely NaN in the train window (mom_12_1 before
    # ~Mar-2026) carries no learnable signal: it is zeroed at transform time
    # for train AND test, so untrained weights never see raw test values.
    dead = np.isnan(X).all(axis=0)
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            med = np.nanmedian(X, axis=0)
            lo = np.nanquantile(X, 0.01, axis=0)
            hi = np.nanquantile(X, 0.99, axis=0)
    med = np.where(np.isfinite(med), med, 0.0)
    lo = np.where(np.isfinite(lo), lo, -np.inf)
    hi = np.where(np.isfinite(hi), hi, np.inf)
    Xc = np.clip(np.where(np.isnan(X), med, X), lo, hi)
    mean = Xc.mean(axis=0)
    std = Xc.std(axis=0)
    std = np.where((std == 0) | ~np.isfinite(std), 1.0, std)
    return {"med": med, "lo": lo, "hi": hi, "mean": mean, "std": std, "dead": dead}


def apply_scaler(X: np.ndarray, sc: dict) -> np.ndarray:
    Xc = np.clip(np.where(np.isnan(X), sc["med"], X), sc["lo"], sc["hi"])
    Z = np.nan_to_num((Xc - sc["mean"]) / sc["std"]).astype(np.float32)
    Z[:, sc["dead"]] = 0.0
    return Z


def cap_per_date(dates: np.ndarray, cap: int, seed: int = SEED) -> np.ndarray:
    """Random per-date subsample to ~cap rows total (dates sorted)."""
    n = len(dates)
    if n <= cap:
        return np.arange(n)
    frac = cap / n
    rng = np.random.default_rng(seed)
    _, starts = np.unique(dates, return_index=True)
    bounds = np.append(np.sort(starts), n)
    keep = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        k = max(1, int(round((b - a) * frac)))
        keep.append(a + rng.permutation(b - a)[:k])
    return np.sort(np.concatenate(keep))


# ---------------------------------------------------------------------------
# 0-3) tree models through the harness folds
# ---------------------------------------------------------------------------
def run_trees(kind: str, model_name: str, feats: list[str], df, features, splits,
              notes: str, params: dict, score_kind="probability") -> dict:
    from catboost import CatBoostClassifier
    from lightgbm import LGBMClassifier, LGBMRanker, LGBMRegressor

    fold_out, detail = [], {}
    for fold in iter_folds(df, features, splits, TASK, preprocess="raw",
                           feature_subset=feats):
        tr = fold.train_df
        dates = tr["date"].to_numpy()
        info = {}
        t0 = time.time()
        if kind == "champion":
            est = LGBMClassifier(**CHAMP_PARAMS).fit(fold.X_train, fold.y_train)
            score = est.predict_proba(fold.X_test)[:, 1]
        elif kind == "lambdarank":
            assert (dates[1:] >= dates[:-1]).all(), "rows must be date-sorted"
            grade = np.clip(np.floor(tr["y_rank_20d"].to_numpy(float) * 10),
                            0, 9).astype(int)
            group = tr.groupby("date", sort=True).size().to_numpy()
            assert group.sum() == len(grade)
            est = LGBMRanker(objective="lambdarank", **CHAMP_PARAMS)
            est.fit(fold.X_train, grade, group=group)
            score = est.predict(fold.X_test)
            info = {"n_queries": int(len(group)),
                    "mean_query_size": round(float(group.mean()), 1)}
        elif kind == "huber":
            yt = np.clip(tr["y_excess_20d"].to_numpy(float), -0.30, 0.30)
            est = LGBMRegressor(objective="huber", alpha=0.9, **CHAMP_PARAMS)
            est.fit(fold.X_train, yt)
            score = est.predict(fold.X_test)
            info = {"share_target_clipped": round(float(
                (np.abs(tr["y_excess_20d"].to_numpy(float)) > 0.30).mean()), 4)}
        elif kind == "catboost":
            fit_m, val_m, vs, ps = inner_split_rows(dates)
            es = CatBoostClassifier(**CB_PARAMS, od_type="Iter", od_wait=CB_OD_WAIT,
                                    use_best_model=True, eval_metric="AUC")
            es.fit(fold.X_train[fit_m], fold.y_train[fit_m],
                   eval_set=(fold.X_train[val_m], fold.y_train[val_m]))
            best_it = int(es.get_best_iteration())
            va_auc = roc_auc_score(fold.y_train[val_m],
                                   es.predict_proba(fold.X_train[val_m])[:, 1])
            # refit on ALL train rows with the early-stopped tree count, so the
            # most recent 15% of train (closest to test) is not thrown away --
            # the champion also trains on every train row.
            n_iter = max(best_it + 1, 10)
            final = CatBoostClassifier(**{**CB_PARAMS, "iterations": n_iter})
            final.fit(fold.X_train, fold.y_train)
            score = final.predict_proba(fold.X_test)[:, 1]
            info = {"best_iteration": best_it, "refit_iterations": n_iter,
                    "inner_val_auc_at_best": round(float(va_auc), 4),
                    "inner_fit_rows": int(fit_m.sum()),
                    "inner_val_rows": int(val_m.sum()),
                    "inner_val_start": str(pd.Timestamp(vs).date()),
                    "inner_purge_start": str(pd.Timestamp(ps).date())}
            log(f"[{model_name}] fold={fold.name} best_it={best_it} "
                f"inner_val_auc={va_auc:.4f}", to_file=True)
        elif kind == "catboost_fixed":
            # diagnostic: champion-style protocol -- no early stopping, the
            # spec's full 600 iterations on ALL train rows
            est = CatBoostClassifier(**CB_PARAMS).fit(fold.X_train, fold.y_train)
            score = est.predict_proba(fold.X_test)[:, 1]
            info = {"iterations": CB_PARAMS["iterations"]}
        else:
            raise ValueError(kind)
        train_s = time.time() - t0
        info["train_seconds"] = round(train_s, 1)
        detail[fold.name] = info
        auc = roc_auc_score(fold.y_test, score)
        log(f"[{model_name}] fold={fold.name} auc={auc:.4f} n_test={len(score)} "
            f"({train_s:.1f}s)")
        fold_out.append(fold_record(fold, score, train_s))
    params = {**params, "fold_detail": detail}
    return summarize(model_name, params, feats, fold_out, notes, "raw",
                     score_kind=score_kind)


# ---------------------------------------------------------------------------
# neural building blocks
# ---------------------------------------------------------------------------
class Block(nn.Module):
    """Pre-LN transformer encoder block on the fused SDPA kernel.

    Attention-probability dropout is omitted (it would force the unfused,
    materialised N x N path: 6x slower for the 1,500-stock set model);
    dropout acts on the attention output, the FFN and the residual branches.
    """

    def __init__(self, d: int, heads: int, dropout: float, ff_mult: int = 2):
        super().__init__()
        self.h = heads
        self.n1 = nn.LayerNorm(d)
        self.qkv = nn.Linear(d, 3 * d)
        self.proj = nn.Linear(d, d)
        self.n2 = nn.LayerNorm(d)
        self.ff = nn.Sequential(nn.Linear(d, ff_mult * d), nn.GELU(),
                                nn.Dropout(dropout), nn.Linear(ff_mult * d, d))
        self.drop = nn.Dropout(dropout)

    def forward(self, x):
        B, N, D = x.shape
        q, k, v = (self.qkv(self.n1(x)).view(B, N, 3, self.h, D // self.h)
                   .permute(2, 0, 3, 1, 4))
        a = F.scaled_dot_product_attention(q, k, v)
        a = a.transpose(1, 2).reshape(B, N, D)
        x = x + self.drop(self.proj(a))
        return x + self.drop(self.ff(self.n2(x)))


class PatchTSTLite(nn.Module):
    """60 sessions x C channels -> 6 non-overlapping 10-session patches
    (channel-mixing patch embedding, i.e. one token per patch, as specified)
    + learned positional embedding -> 2 pre-LN encoder layers -> mean-pool ->
    linear logit. No RevIN: per-window instance normalisation would erase the
    level information (e.g. the stock's current ret_126d) that carries the
    cross-sectional signal."""

    def __init__(self, n_chan: int, d: int = D_MODEL, seq_len: int = SEQ_LEN,
                 patch: int = PATCH, layers: int = N_LAYERS, heads: int = N_HEADS,
                 dropout: float = DROPOUT):
        super().__init__()
        self.n_tok, self.patch = seq_len // patch, patch
        self.embed = nn.Linear(patch * n_chan, d)
        self.pos = nn.Parameter(torch.randn(1, self.n_tok, d) * 0.02)
        self.drop = nn.Dropout(dropout)
        self.blocks = nn.ModuleList([Block(d, heads, dropout) for _ in range(layers)])
        self.norm = nn.LayerNorm(d)
        self.head = nn.Linear(d, 1)

    def forward(self, x):                                  # (B, L, C)
        B, L, C = x.shape
        z = self.drop(self.embed(x.reshape(B, self.n_tok, self.patch * C)) + self.pos)
        for blk in self.blocks:
            z = blk(z)
        return self.head(self.norm(z).mean(dim=1)).squeeze(-1)


class DLinear(nn.Module):
    """Zeng et al. (2022): moving-average trend + remainder, each mapped by a
    per-channel linear layer over the 60-step window, then a linear read-out
    across channels -> logit. Linear end to end (2 linear layers)."""

    def __init__(self, n_chan: int, seq_len: int = SEQ_LEN, kernel: int = DLINEAR_KERNEL):
        super().__init__()
        self.k = kernel
        self.w_season = nn.Parameter(torch.full((n_chan, seq_len), 1.0 / seq_len))
        self.w_trend = nn.Parameter(torch.full((n_chan, seq_len), 1.0 / seq_len))
        self.b = nn.Parameter(torch.zeros(n_chan))
        self.out = nn.Linear(n_chan, 1)

    def forward(self, x):                                  # (B, L, C)
        xt = x.transpose(1, 2)                             # (B, C, L)
        pad = (self.k - 1) // 2
        front = xt[:, :, :1].expand(-1, -1, pad)
        back = xt[:, :, -1:].expand(-1, -1, self.k - 1 - pad)
        trend = F.avg_pool1d(torch.cat([front, xt, back], dim=2), self.k, stride=1)
        season = xt - trend
        z = (season * self.w_season).sum(-1) + (trend * self.w_trend).sum(-1) + self.b
        return self.out(z).squeeze(-1)


class CSTransformer(nn.Module):
    """One date's universe as a SET: linear embed -> 2 self-attention layers
    across stocks (no positional encoding: permutation-equivariant) ->
    per-stock logit. Each score can depend on the whole cross-section."""

    def __init__(self, n_feat: int, d: int = D_MODEL, layers: int = N_LAYERS,
                 heads: int = N_HEADS, dropout: float = DROPOUT):
        super().__init__()
        self.embed = nn.Linear(n_feat, d)
        self.drop = nn.Dropout(dropout)
        self.blocks = nn.ModuleList([Block(d, heads, dropout) for _ in range(layers)])
        self.norm = nn.LayerNorm(d)
        self.head = nn.Linear(d, 1)

    def forward(self, x):                                  # (1, N, F)
        z = self.drop(self.embed(x))
        for blk in self.blocks:
            z = blk(z)
        return self.head(self.norm(z)).squeeze(-1)         # (1, N)


# ---------------------------------------------------------------------------
# 4/7) per-stock sequence models (PatchTST-lite, DLinear)
# ---------------------------------------------------------------------------
def build_seq_context(df: pd.DataFrame, channels: list[str]):
    """(ticker,date)-sorted raw channel matrix over ALL parquet rows (features
    are backward-looking, so a test row's lookback may reach before
    test_start; label status of the lookback rows is irrelevant)."""
    assert isinstance(df.index, pd.RangeIndex) and df.index.start == 0
    s = df.sort_values(["ticker", "date"], kind="mergesort")
    pos_of_orig = np.empty(len(df), dtype=np.int64)
    pos_of_orig[s.index.to_numpy()] = np.arange(len(df))
    M = s[channels].to_numpy(dtype=np.float32)
    wt = s.groupby("ticker").cumcount().to_numpy().astype(np.int64)
    return M, pos_of_orig, wt, s["date"].to_numpy()


OFFS = torch.arange(-(SEQ_LEN - 1), 1)


def gather_windows(Mt_t, wt_t, pos, pad_idx):
    """(B,) sorted positions -> (B, 60, C); sessions before the ticker's first
    parquet row point at an all-zero pad row (= train mean after scaling)."""
    idx = pos.unsqueeze(1) + OFFS
    invalid = OFFS.unsqueeze(0) < -wt_t[pos].unsqueeze(1)
    return Mt_t[idx.masked_fill(invalid, pad_idx)]


@torch.no_grad()
def seq_logits(net, Mt_t, wt_t, pos_t, pad_idx, batch=4096) -> np.ndarray:
    net.eval()
    out = [net(gather_windows(Mt_t, wt_t, pos_t[i:i + batch], pad_idx))
           for i in range(0, len(pos_t), batch)]
    return torch.cat(out).numpy() if out else np.zeros(0, np.float32)


def bench_seq_epoch(make_net, n_chan, n_fit) -> float:
    seed_everything()
    net = make_net()
    opt = torch.optim.AdamW(net.parameters(), lr=1e-3, weight_decay=1e-4)
    x = torch.randn(SEQ_BATCH, SEQ_LEN, n_chan)
    y = (torch.rand(SEQ_BATCH) > 0.5).float()
    lossf = nn.BCEWithLogitsLoss()
    for i in range(10):
        if i == 3:
            t0 = time.time()
        opt.zero_grad()
        lossf(net(x), y).backward()
        opt.step()
    return (time.time() - t0) / 7 * np.ceil(n_fit / SEQ_BATCH) * 1.3  # +gather


def train_seq_net(tag, net, Mt_t, wt_t, pad_idx, fit_pos, y_fit, va_pos, y_va,
                  lr=1e-3, wd=1e-4, max_epochs=SEQ_MAX_EPOCHS, patience=SEQ_PATIENCE):
    opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=wd)
    lossf = nn.BCEWithLogitsLoss()
    g = torch.Generator().manual_seed(SEED)
    fit_pos_t, y_fit_t = torch.from_numpy(fit_pos), torch.from_numpy(y_fit)
    va_pos_t = torch.from_numpy(va_pos)
    best_auc, best_state, bad, best_ep, ep_secs = -1.0, None, 0, 0, []
    epoch = 0
    for epoch in range(1, max_epochs + 1):
        t0 = time.time()
        net.train()
        perm = torch.randperm(len(fit_pos_t), generator=g)
        tot, nb = 0.0, 0
        for i in range(0, len(perm), SEQ_BATCH):
            idx = perm[i:i + SEQ_BATCH]
            opt.zero_grad(set_to_none=True)
            loss = lossf(net(gather_windows(Mt_t, wt_t, fit_pos_t[idx], pad_idx)),
                         y_fit_t[idx])
            loss.backward()
            nn.utils.clip_grad_norm_(net.parameters(), GRAD_CLIP)
            opt.step()
            tot, nb = tot + loss.item(), nb + 1
        auc = roc_auc_score(y_va, seq_logits(net, Mt_t, wt_t, va_pos_t, pad_idx))
        ep_secs.append(time.time() - t0)
        log(f"{tag} epoch {epoch:2d} train_loss={tot / nb:.5f} "
            f"val_auc={auc:.4f} ({ep_secs[-1]:.1f}s)", to_file=True)
        if auc > best_auc + 1e-5:
            best_auc, bad, best_ep = auc, 0, epoch
            best_state = {k: v.detach().clone() for k, v in net.state_dict().items()}
        else:
            bad += 1
            if bad >= patience:
                break
    net.load_state_dict(best_state)
    return net, {"epochs_run": epoch, "best_epoch": best_ep,
                 "best_inner_val_auc": round(float(best_auc), 4),
                 "epoch_seconds_mean": round(float(np.mean(ep_secs)), 1)}


def run_seq_model(model_name: str, arch: str, df, features, splits, channels,
                  ctx, smoke: bool = False, cap0: int = SEQ_CAP) -> dict | None:
    M, pos_of_orig, wt, dates_sorted = ctx
    pad_idx = len(M)
    wt_t = torch.from_numpy(wt)
    cap, d_model = cap0, D_MODEL
    n_chan = len(channels)

    def make_net():
        if arch == "patchtst":
            return PatchTSTLite(n_chan, d=d_model)
        return DLinear(n_chan)

    if not smoke:
        proj = bench_seq_epoch(make_net, n_chan, cap * (1 - INNER_VAL_FRAC))
        if proj > EPOCH_SECONDS_LIMIT:
            cap //= 2
            d_model //= 2 if arch == "patchtst" else 1
            log(f"[{model_name}] projected {proj:.0f}s/epoch > {EPOCH_SECONDS_LIMIT}s "
                f"-> cap={cap}, d_model={d_model}", to_file=True)
        else:
            log(f"[{model_name}] projected ~{proj:.0f}s/epoch at cap={cap} "
                f"d_model={d_model}", to_file=True)
    else:
        cap = 6000

    fold_out, detail = [], {}
    for fold in iter_folds(df, features, splits, TASK, preprocess="raw",
                           feature_subset=channels):
        tr, te = fold.train_df, fold.test_df
        t0 = time.time()
        cutoff = np.datetime64(tr["date"].max())
        sc = fit_scaler(M[dates_sorted <= cutoff])
        Mt_t = torch.from_numpy(np.vstack([apply_scaler(M, sc),
                                           np.zeros((1, n_chan), np.float32)]))
        tr_pos = pos_of_orig[tr.index.to_numpy()]
        tr_dates = tr["date"].to_numpy()
        y_tr = tr[LABEL].to_numpy(dtype=np.float32)
        n_precap = len(tr_pos)
        sub = cap_per_date(tr_dates, cap)
        tr_pos, tr_dates, y_tr = tr_pos[sub], tr_dates[sub], y_tr[sub]
        fit_m, val_m, vs, ps = inner_split_dates(tr_dates)
        seed_everything()
        net = make_net()
        tag = f"[{model_name}] fold={fold.name}"
        log(f"{tag} train_seq={len(tr_pos)} (pre-cap {n_precap}) "
            f"fit={int(fit_m.sum())} val={int(val_m.sum())} "
            f"val_start={pd.Timestamp(vs).date()} test={len(te)} "
            f"short_hist_test={(wt[pos_of_orig[te.index.to_numpy()]] < SEQ_LEN - 1).mean():.3f}",
            to_file=True)
        net, info = train_seq_net(
            tag, net, Mt_t, wt_t, pad_idx, tr_pos[fit_m], y_tr[fit_m],
            tr_pos[val_m], y_tr[val_m],
            max_epochs=1 if smoke else SEQ_MAX_EPOCHS)
        train_s = time.time() - t0
        te_pos = torch.from_numpy(pos_of_orig[te.index.to_numpy()])
        score = 1.0 / (1.0 + np.exp(-seq_logits(net, Mt_t, wt_t, te_pos, pad_idx)))
        info.update({"n_train_precap": int(n_precap), "n_train_capped": int(len(tr_pos)),
                     "n_inner_fit": int(fit_m.sum()), "n_inner_val": int(val_m.sum()),
                     "inner_val_start": str(pd.Timestamp(vs).date()),
                     "inner_purge_start": str(pd.Timestamp(ps).date()),
                     "train_seconds": round(train_s, 1)})
        detail[fold.name] = info
        log(f"{tag} test_auc={roc_auc_score(fold.y_test, score):.4f} "
            f"best_ep={info['best_epoch']}/{info['epochs_run']} ({train_s:.0f}s)",
            to_file=True)
        fold_out.append(fold_record(fold, score, train_s, {"n_train": int(len(tr_pos))}))
        del Mt_t, net
        if smoke:
            return None

    n_params = sum(p.numel() for p in make_net().parameters())
    common = {
        "seq_len": SEQ_LEN, "channels": channels,
        "optimizer": "AdamW", "lr": 1e-3, "weight_decay": 1e-4,
        "batch_size": SEQ_BATCH, "max_epochs": SEQ_MAX_EPOCHS,
        "early_stopping_patience": SEQ_PATIENCE, "grad_clip_norm": GRAD_CLIP,
        "inner_val": "last 15% of capped train dates; 20 sessions before it "
                     "purged from inner-fit",
        "train_seq_cap_per_fold": cap, "n_params": int(n_params),
        "channel_scaling": "median impute -> clip to train q01/q99 -> z-score, "
                           "fit on all parquet rows dated <= train_end",
        "short_history": "sessions before a ticker's first parquet row = zero "
                         "pad (train mean); ALL test rows scored",
        "seed": SEED, "torch_threads": 2, "fold_detail": detail,
    }
    if arch == "patchtst":
        params = {"arch": "PatchTST-lite (channel-mixing patch embedding)",
                  "patch_len": PATCH, "stride": PATCH, "n_tokens": SEQ_LEN // PATCH,
                  "d_model": d_model, "n_layers": N_LAYERS, "n_heads": N_HEADS,
                  "ff_dim": 2 * d_model, "dropout": DROPOUT, "pool": "mean",
                  "norm": "pre-LN, no RevIN", **common}
        notes = ("PatchTST-lite over per-stock windows of the last 60 sessions x "
                 f"{n_chan} channels (champion 10 + {SEQ_EXTRA}), built from the "
                 "parquet sorted (ticker,date); 10-session patches, stride 10 -> 6 "
                 f"tokens, d_model {d_model}, 2 pre-LN layers, 4 heads, dropout 0.2 "
                 "(attention-probability dropout omitted for the fused SDPA "
                 "kernel), mean-pool -> logit; BCE on label_beat_mkt_20d. Train "
                 f"sequences capped at {cap // 1000}k/fold by per-date random subsampling "
                 "(seed 108); all test rows kept. Early stopping on inner-val AUC "
                 "(last 15% of train dates, purged 20 sessions)." + (
                     f" HALVING RULE APPLIED (spec 120k / d_model 64): the pre-run "
                     f"benchmark projected >{EPOCH_SECONDS_LIMIT:.0f} s/epoch under box "
                     "contention (load ~10-18 on 4 cores), so cap and d_model were "
                     "halved; epochs unchanged." if cap < SEQ_CAP else ""))
    else:
        params = {"arch": "DLinear (individual per-channel linear on trend and "
                          "remainder) -> Linear(C->1)",
                  "moving_avg_kernel": DLINEAR_KERNEL, **common}
        notes = ("DLinear (Zeng et al. 2022) baseline on the identical 60x14 "
                 "windows, cap, scaling, inner validation and optimiser as "
                 "patchtst_lite (incl. its halved 60k train-sequence cap, for a "
                 "like-for-like test of what attention adds): moving-average(25) "
                 "trend + remainder, each "
                 "weighted per channel over the 60 sessions, then a linear "
                 "read-out across channels -> logit (a 2-layer linear model).")
    return summarize(model_name, params, channels, fold_out, notes, "seq_scaled")


# ---------------------------------------------------------------------------
# 5) cross-sectional set transformer
# ---------------------------------------------------------------------------
def run_cs_transformer(df, features, splits, feats, smoke: bool = False,
                       halve: bool = False) -> dict | None:
    assert isinstance(df.index, pd.RangeIndex) and df.index.start == 0
    model_name = "cs_transformer"
    X_all = df[feats].to_numpy(dtype=np.float32)
    d_all = df["date"].to_numpy()
    ok_all = (df[LABEL].notna() & df[CLEAN].astype(bool)).to_numpy()
    y_all = np.where(ok_all, df[LABEL].to_numpy(dtype=np.float32), 0.0).astype(np.float32)
    ud, starts = np.unique(d_all, return_index=True)
    ends = np.append(starts[1:], len(d_all))
    sizes = ends - starts
    d_model = D_MODEL
    set_frac = 1.0
    if halve:
        # lead's rule: > ~90 s/epoch -> halve the sequence cap and d_model.
        # For a set model the 'sequence' is the date's stock set: each
        # training step sees a fresh random 50% of that date's universe
        # (val/test always use the FULL set).
        d_model, set_frac = D_MODEL // 2, 0.5
        log(f"[cs_transformer] HALVED (measured epoch time > {EPOCH_SECONDS_LIMIT}s "
            f"under box contention): d_model={d_model}, train set fraction={set_frac}",
            to_file=True)

    # projected epoch time at the largest fold (holdout train ~ 260 dates)
    seed_everything()
    net = CSTransformer(len(feats), d=d_model)
    opt = torch.optim.AdamW(net.parameters(), lr=CS_LR)
    x = torch.randn(1, int(sizes.max()), len(feats))
    yy = (torch.rand(1, int(sizes.max())) > 0.5).float()
    for i in range(6):
        if i == 2:
            t0 = time.time()
        opt.zero_grad()
        F.binary_cross_entropy_with_logits(net(x), yy).backward()
        opt.step()
    per_date = (time.time() - t0) / 4
    max_fit_days = int((ud <= np.datetime64(splits["holdout"]["train_end"])).sum()
                       * (1 - INNER_VAL_FRAC))
    proj = per_date * max_fit_days * 1.15
    if proj > EPOCH_SECONDS_LIMIT and not smoke and not halve:
        d_model //= 2
        log(f"[{model_name}] projected {proj:.0f}s/epoch > {EPOCH_SECONDS_LIMIT}s "
            f"-> d_model={d_model}", to_file=True)
    else:
        log(f"[{model_name}] projected ~{proj:.0f}s/epoch (worst fold) at "
            f"d_model={d_model}", to_file=True)

    fold_out, detail = [], {}
    for fold in iter_folds(df, features, splits, TASK, preprocess="raw",
                           feature_subset=feats):
        tr, te = fold.train_df, fold.test_df
        t0 = time.time()
        cutoff = np.datetime64(tr["date"].max())
        t_lo = np.datetime64(te["date"].min())
        t_hi = np.datetime64(te["date"].max())
        Z = torch.from_numpy(apply_scaler(X_all, fit_scaler(X_all[d_all <= cutoff])))
        Y = torch.from_numpy(y_all)
        OK = torch.from_numpy(ok_all.copy())
        train_days = [i for i in range(len(ud))
                      if ud[i] <= cutoff and ok_all[starts[i]:ends[i]].any()]
        k = min(max(1, int(round(len(train_days) * (1 - INNER_VAL_FRAC)))),
                len(train_days) - 1)
        val_days = train_days[k:]
        fit_days = train_days[:max(1, k - INNER_PURGE)]
        test_days = [i for i in range(len(ud)) if t_lo <= ud[i] <= t_hi]
        if smoke:
            fit_days = fit_days[-12:]
        tag = f"[{model_name}] fold={fold.name}"
        log(f"{tag} fit_days={len(fit_days)} val_days={len(val_days)} "
            f"(val_start={pd.Timestamp(ud[val_days[0]]).date()}) "
            f"test_days={len(test_days)} mean_set={sizes[fit_days].mean():.0f}",
            to_file=True)

        seed_everything()
        net = CSTransformer(len(feats), d=d_model)
        opt = torch.optim.AdamW(net.parameters(), lr=CS_LR, weight_decay=1e-4)
        rng = np.random.default_rng(SEED)

        @torch.no_grad()
        def day_scores(days):
            net.eval()
            return [net(Z[starts[i]:ends[i]].unsqueeze(0)).squeeze(0) for i in days]

        def val_auc():
            outs = day_scores(val_days)
            s = torch.cat([o[OK[starts[i]:ends[i]]] for o, i in zip(outs, val_days)])
            yv = torch.cat([Y[starts[i]:ends[i]][OK[starts[i]:ends[i]]] for i in val_days])
            return roc_auc_score(yv.numpy(), s.numpy())

        best_auc, best_state, bad, best_ep, ep_secs = -1.0, None, 0, 0, []
        epoch = 0
        max_ep = 1 if smoke else CS_MAX_EPOCHS
        for epoch in range(1, max_ep + 1):
            te0 = time.time()
            net.train()
            tot = 0.0
            for i in rng.permutation(fit_days):
                a, b = starts[i], ends[i]
                if set_frac < 1.0:
                    sel = torch.from_numpy(np.sort(rng.choice(
                        b - a, size=int((b - a) * set_frac), replace=False)) + a)
                else:
                    sel = torch.arange(a, b)
                m = OK[sel]
                opt.zero_grad(set_to_none=True)
                logit = net(Z[sel].unsqueeze(0)).squeeze(0)
                loss = F.binary_cross_entropy_with_logits(logit[m], Y[sel][m])
                loss.backward()
                nn.utils.clip_grad_norm_(net.parameters(), GRAD_CLIP)
                opt.step()
                tot += loss.item()
            auc = val_auc()
            ep_secs.append(time.time() - te0)
            log(f"{tag} epoch {epoch:2d} train_loss={tot / len(fit_days):.5f} "
                f"val_auc={auc:.4f} ({ep_secs[-1]:.1f}s)", to_file=True)
            if auc > best_auc + 1e-5:
                best_auc, bad, best_ep = auc, 0, epoch
                best_state = {kk: v.detach().clone() for kk, v in net.state_dict().items()}
            else:
                bad += 1
                if bad >= CS_PATIENCE:
                    break
        net.load_state_dict(best_state)
        train_s = time.time() - t0
        full = np.full(len(df), np.nan)
        for o, i in zip(day_scores(test_days), test_days):
            full[starts[i]:ends[i]] = 1.0 / (1.0 + np.exp(-o.numpy()))
        score = full[te.index.to_numpy()]
        assert np.isfinite(score).all()
        detail[fold.name] = {
            "epochs_run": epoch, "best_epoch": best_ep,
            "best_inner_val_auc": round(float(best_auc), 4),
            "epoch_seconds_mean": round(float(np.mean(ep_secs)), 1),
            "n_fit_dates": len(fit_days), "n_val_dates": len(val_days),
            "inner_val_start": str(pd.Timestamp(ud[val_days[0]]).date()),
            "train_seconds": round(train_s, 1)}
        log(f"{tag} test_auc={roc_auc_score(fold.y_test, score):.4f} "
            f"best_ep={best_ep}/{epoch} ({train_s:.0f}s)", to_file=True)
        fold_out.append(fold_record(fold, score, train_s,
                                    {"n_train": int(ok_all[d_all <= cutoff].sum())}))
        if smoke:
            return None

    params = {
        "arch": "set transformer: Linear(10->d) -> 2 pre-LN self-attention "
                "layers across the date's stocks (4 heads, FFN 2d, GELU) -> "
                "LayerNorm -> Linear(d->1); no positional encoding",
        "d_model": d_model, "n_layers": N_LAYERS, "n_heads": N_HEADS,
        "train_set_fraction_per_step": set_frac,
        "halving_rule_applied": bool(halve),
        "dropout": DROPOUT, "optimizer": "AdamW", "lr": CS_LR,
        "weight_decay": 1e-4, "batch": "one date = one batch (full universe set)",
        "max_epochs": CS_MAX_EPOCHS, "early_stopping_patience": CS_PATIENCE,
        "grad_clip_norm": GRAD_CLIP,
        "inner_val": "last 15% of train dates; 20 sessions before it purged",
        "context_set": "ALL universe rows of the date (point-in-time); loss only "
                       "on labeled+clean rows (selecting the set by y_clean "
                       "would leak future split events)",
        "scaling": "median impute -> clip q01/q99 -> z-score, fit on rows "
                   "dated <= train_end",
        "n_params": int(sum(p.numel() for p in net.parameters())),
        "seed": SEED, "torch_threads": 2, "fold_detail": detail,
    }
    notes = ("Cross-sectional set transformer on the 10 champion features: each "
             "date's whole universe (~1,500 stocks) is one attention set, so a "
             "stock's score is conditioned on the full cross-section (the "
             "mechanism behind the cs_rank_* features, learned). BCE on "
             "label_beat_mkt_20d, one date per optimiser step, AdamW 5e-4, max "
             "30 epochs, patience 5 on inner-val AUC (last 15% of train dates, "
             "purged 20 sessions)." + (
                 " HALVING RULE APPLIED: the first full-spec epoch took 67 s on the "
                 "smallest fold (136 dates) with box load ~8.5 on 4 cores, projecting "
                 ">90 s/epoch for the larger folds, so d_model 64->32 and each "
                 "training step uses a random 50% of the date's stocks (val/test "
                 "use the full set)." if halve else ""))
    return summarize(model_name, params, feats, fold_out, notes, "cs_scaled")


# ---------------------------------------------------------------------------
# 6) rank-average ensemble of existing OOS scores
# ---------------------------------------------------------------------------
def run_ensemble(feats: list[str]) -> dict:
    members = {
        "lgbm_fs_selected (champion, clean)": CHAMP_PREDS,
        "lgbm_lambdarank": ev.PREDS_DIR / f"lgbm_lambdarank__{TASK}.parquet",
        "catboost": ev.PREDS_DIR / f"catboost__{TASK}.parquet",
    }
    base = None
    cols = []
    for j, (name, path) in enumerate(members.items()):
        p = pd.read_parquet(path)
        p["date"] = pd.to_datetime(p["date"])
        c = f"s{j}"
        cols.append(c)
        if base is None:
            base = p.rename(columns={"score": c})
        else:
            q = p[["date", "ticker", "fold", "score", "y"]].rename(
                columns={"score": c, "y": f"y{j}"})
            n0 = len(base)
            base = base.merge(q, on=["date", "ticker", "fold"], how="inner",
                              validate="1:1")
            assert len(base) == n0, f"{name} preds do not align with the champion's"
            assert (base[f"y{j}"] == base["y"]).all()
    g = base.groupby("date")
    for c in cols:
        base["r" + c] = g[c].rank(pct=True)
    base["score"] = base[["r" + c for c in cols]].mean(axis=1)
    # mean per-date Spearman between members (diversity diagnostic)
    corr = {}
    names = list(members)
    for a in range(len(cols)):
        for b in range(a + 1, len(cols)):
            ic = per_date_rank_ic(base["date"].to_numpy(), base[cols[a]].to_numpy(),
                                  base[cols[b]].to_numpy())
            corr[f"{names[a]} ~ {names[b]}"] = round(float(ic.mean()), 3)
    fold_out = []
    order = ["2026-04", "2026-05", "2026-06", "2026-07", "holdout"]
    for fname in order:
        f = base[base["fold"] == fname].sort_values(["date", "ticker"])
        fold_out.append({"name": fname, "y": f["y"].to_numpy(np.float32),
                         "score": f["score"].to_numpy(float),
                         "fwd": f["fwd"].to_numpy(np.float32),
                         "dates": f["date"].to_numpy(), "tickers": f["ticker"].to_numpy(),
                         "n_train": 0, "train_s": 0.0})
    log(f"[ensemble_rank] member per-date rank correlations: {corr}", to_file=True)
    params = {"members": {k: str(v.relative_to(ev.ML_DIR.parent)) for k, v in members.items()},
              "combiner": "per-date percentile rank of each member's OOS score, "
                          "equal-weight mean; NO weights fitted, no refit",
              "member_rank_corr_mean_per_date": corr}
    notes = ("Equal-weight per-date rank average of three already-OOS score "
             "sets (champion clean preds, lgbm_lambdarank, catboost); nothing is "
             "fitted, so the blend cannot overfit the folds. Score is an average "
             "percentile rank: AUC/decile/IC are meaningful, Brier/acc@0.5 are "
             "not calibrated probabilities. train_seconds = 0 (cost = sum of "
             "the members).")
    return summarize("ensemble_rank", params, feats, fold_out, notes, "rank_blend",
                     family="ensemble", score_kind="rank_average")


# ---------------------------------------------------------------------------
# league summary (+ champion reference rank-IC from its clean preds)
# ---------------------------------------------------------------------------
def run_league() -> list[dict]:
    rows = []
    for p in sorted(SOTA_DIR.glob(f"*__{TASK}.json")):
        d = json.loads(p.read_text())
        ho = d["holdout"]
        rows.append({
            "model": d["model"], "family": d["family"], "n_features": d["n_features"],
            "cv_auc_mean": round(d["cv_auc_mean"], 4), "cv_auc_std": round(d["cv_auc_std"], 4),
            "worst_fold": round(d["cv_worst_fold_auc"], 4),
            "fold_aucs": {f["fold"]: round(f["auc"], 4) for f in d["folds"]},
            "holdout_auc": round(ho["auc"], 4),
            "holdout_decile_spread": round(ho.get("decile_spread", float("nan")), 4),
            "holdout_top_decile_fwd": round(ho.get("top_decile_mean_fwd", float("nan")), 4),
            "cv_decile_spread_mean": round(float(np.mean(
                [f.get("decile_spread", np.nan) for f in d["folds"]])), 4),
            "rank_ic_cv_mean": round(d["rank_ic"]["cv"]["mean"], 4),
            "rank_ic_cv_t_naive": round(d["rank_ic"]["cv"]["t_naive"], 2),
            "rank_ic_cv_t_nw19": round(d["rank_ic"]["cv"]["t_nw19"], 2),
            "rank_ic_holdout_mean": round(d["rank_ic"]["holdout"]["mean"], 4),
            "rank_ic_holdout_t_naive": round(d["rank_ic"]["holdout"]["t_naive"], 2),
            "train_s_per_fold": d["train_seconds_per_fold_mean"],
            "delta_cv_vs_champion": round(d["vs_champion"]["delta_cv_auc"], 4),
            "passes": d["vs_champion"]["passes"],
        })
    rows.sort(key=lambda r: -r["cv_auc_mean"])
    out = {"task": TASK, "champion_cv_auc": CHAMP_CV, "pass_mark": PASS_MARK,
           "rule": "challenger passes iff CV AUC >= 0.5364 AND every CV fold >= 0.50 "
                   "(fixed before any run; holdout never used to choose)",
           "rows": rows}
    (SOTA_DIR / "league_summary.json").write_text(json.dumps(out, indent=1))
    print("| model | #feat | CV AUC ± std | worst fold | holdout AUC | holdout spread "
          "| rank-IC CV (t / NW-t) | holdout IC | s/fold | passes |")
    print("|---|---:|---|---:|---:|---:|---|---:|---:|---|")
    for r in rows:
        print(f"| {r['model']} | {r['n_features']} | {r['cv_auc_mean']:.4f} ± "
              f"{r['cv_auc_std']:.4f} | {r['worst_fold']:.4f} | {r['holdout_auc']:.4f} | "
              f"{r['holdout_decile_spread'] * 100:+.2f}% | {r['rank_ic_cv_mean']:+.4f} "
              f"({r['rank_ic_cv_t_naive']:.2f} / {r['rank_ic_cv_t_nw19']:.2f}) | "
              f"{r['rank_ic_holdout_mean']:+.4f} | {r['train_s_per_fold']} | "
              f"{'yes' if r['passes'] else 'no'} |")
    return rows


# ---------------------------------------------------------------------------
# post-hoc interpretation (written after the runs; appended to each JSON)
# ---------------------------------------------------------------------------
INTERPRETATION: dict[str, str] = {
    "champion_ref": (
        "Reference only. Reproduces lgbm_fs_selected_clean exactly (max score diff 0); "
        "its per-date rank-IC (+0.057, Newey-West t 3.3) and ~5 s/fold are the bar the "
        "challengers are read against. Score is roughly volatility-neutral (per-date "
        "Spearman with atr_pct +0.03) and tilted to stocks near their 52-week high (+0.25)."),
    "lgbm_lambdarank": (
        "Does not beat the champion: CV 0.5293 (-0.002) and July 0.4967 < 0.50. The "
        "2^g-1 gains on 10 return grades make the ranker chase the top decile of 20-day "
        "returns, which is dominated by volatile names: its score has per-date Spearman "
        "+0.66 with atr_pct (champion +0.03), so its fold pattern follows the sign of the "
        "volatility factor (IC +0.095 Apr, -0.059 Jul, +0.10 holdout) rather than "
        "stock-specific skill; the 0.566 holdout / +6.0% spread is that vol-friendly "
        "window, not evidence. It is the most diverse partner for the champion (per-date "
        "rank corr 0.26), which is what the ensemble exploits."),
    "lgbm_lambdarank_f51": (
        "Does not beat the champion: CV 0.5160, July 0.4943. Adding the other 41 features "
        "lowers the ranker's CV mean exactly as it lowered the classifier's (pilot "
        "lightgbm-51 0.504): more capacity to fit the train window's regime structure. "
        "Holdout 0.564 is the same vol-friendly window as the 10-feature ranker."),
    "lgbm_huber": (
        "Does not beat the champion on the mean (CV 0.5223, -0.009) but is the most "
        "stable model in the study: CV std 0.007, worst fold 0.513, all five windows "
        ">= 0.51. With alpha=0.9 above the +/-0.30 clip it is least squares on the "
        "clipped excess return, so it weights stocks by return magnitude rather than by "
        "the median crossing; its rank-IC t (NW 3.27) equals the champion's (3.26) while "
        "its AUC is lower -- it is a return forecaster, not a better classifier."),
    "catboost_es_logloss": (
        "Superseded diagnostic: Logloss early stopping on the inner tail selected "
        "43/0/0/1/0 trees, i.e. a 10-44 tree model on most folds; CV 0.5154."),
    "catboost": (
        "Does not beat the champion: CV 0.5260, April 0.4938. Early stopping on the "
        "time-ordered inner tail chose 43/79/0/186/5 trees: on folds whose inner-val "
        "window sits on the March-2026 break (val AUC never above 0.48/0.44) the "
        "protocol shuts the model down, while where it allowed 186 trees (July) CatBoost "
        "scored 0.545 vs the champion's 0.543. The shortfall is the early-stopping "
        "protocol under a regime break as much as the algorithm -- see catboost_fixed600."),
    "catboost_f51": (
        "Does not beat the champion: CV 0.5193, worst fold 0.4888; early stopping again "
        "picked few trees. 51 features add noise for CatBoost as for LightGBM; holdout "
        "0.550 is the friendly window."),
    "catboost_fixed600": (
        "Diagnostic, not eligible for promotion: with the champion's protocol (no early "
        "stopping, fixed 600 trees) CatBoost is level with LightGBM -- CV 0.5299 vs "
        "0.5314, a better floor (0.5115 vs 0.5069) and lower dispersion (0.012 vs 0.014), "
        "rank-IC NW t 3.51 -- but still below the pass mark. The early-stopped 'catboost' "
        "shortfall is therefore the protocol (early stopping on a regime-break tail), "
        "not the algorithm; at this sample size the two GBM implementations are "
        "interchangeable."),
    "patchtst_lite": (
        "Fails clearly: CV 0.5143 +/- 0.044 (the most dispersed model in the study), worst "
        "fold 0.4516 (April), holdout 0.4480 with a -1.9% decile spread, rank-IC NW t 0.6. "
        "The 60-session view lets it fit whatever pattern dominated the inner tail (inner-val "
        "AUC ~0.60 on the pre-break Jan-Feb tail) and that pattern inverted in April; when "
        "the pattern persisted (July 0.575) it won big. That is a regime bet, not stock "
        "selection. Run at the halved setting (60k sequences, d_model 32) because of box "
        "contention; the verdict matches the pilot's GRU/LSTM (0.489/0.502). Its score is "
        "effectively a low-vol / near-52w-high factor (per-date Spearman atr_pct -0.53, "
        "dist_52w_high +0.59): the mirror image of LambdaRank's high-vol tilt."),
    "dlinear": (
        "The trivial-sequence control fails too: CV 0.5103 +/- 0.039, worst fold 0.4568, "
        "holdout 0.4605, rank-IC NW t 0.4. Its fold pattern almost duplicates "
        "patchtst_lite's (0.457/0.518/0.500/0.567 vs 0.452/0.524/0.506/0.575) on the same "
        "windows, cap, scaling and early stopping, so attention adds ~0.004 CV AUC over a "
        "2-layer linear model -- nothing beyond noise. What fails is the sequence view "
        "itself: it re-expresses trailing-return information the point-in-time features "
        "already summarise, and early stopping on the inner tail locks in the last regime. "
        "Score = low-vol / near-52w-high factor (atr_pct -0.52, dist_52w_high +0.64)."),
    "cs_transformer": (
        "Fails: CV 0.5197 +/- 0.035 with April and May below 0.50 (0.493/0.493) and a big "
        "July (0.578) -- the regime-bet profile of the sequence models, not stable "
        "selection. The label is already cross-sectional (beat the median) and the "
        "cs_rank_* features already normalise across stocks, so attention over ~1,450 "
        "names has little left to add, while 140-210 training dates (one optimiser step "
        "each) give it far more capacity than data; early stopping on the "
        "break-straddling tail (fold 2026-06 inner-val AUC <= 0.44) is the same trap. Run "
        "at the halved setting (d_model 32, 50% of each date's stocks per training step). "
        "Holdout 0.501, rank-IC NW t 0.70 (not significant); its score is a low-vol / "
        "near-52w-high factor (atr_pct -0.59, dist_52w_high +0.56)."),
    "ensemble_rank": (
        "Misses the pre-registered bar by 0.0007 (CV 0.5357 vs 0.5364), so it does NOT "
        "pass -- but it is the strongest result here: worst fold 0.5236 (champion "
        "0.5069), CV std 0.008 (0.014), better than the champion in 3/4 folds, holdout "
        "0.548 (0.518), rank-IC NW t 3.64 (3.26). The gain is diversification, not a new "
        "signal: the LambdaRank member's high-vol tilt (rank corr 0.26 with the champion) "
        "offsets the champion's defensive/near-52w-high tilt in the April and Aug-Sep "
        "rallies. No weights were fitted, so it cannot have overfit the folds."),
}


def run_annotate() -> None:
    for model, text in INTERPRETATION.items():
        p = SOTA_DIR / f"{model}__{TASK}.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text())
        base = d["notes"].split(" INTERPRETATION: ")[0]
        d["notes"] = f"{base} INTERPRETATION: {text}"
        p.write_text(json.dumps(d, indent=1, default=str))
        log(f"annotated {p.name}")


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parts", default="all",
                    help="all | comma list of champ,lambdarank,lambdarank51,huber,"
                         "catboost,catboost51,ensemble,patchtst,cstf,dlinear,"
                         "league,annotate")
    ap.add_argument("--tree-threads", type=int, default=2,
                    help="threads for LightGBM/CatBoost (not a model hyper-parameter)")
    ap.add_argument("--seq-cap", type=int, default=SEQ_CAP,
                    help="train-sequence cap for dlinear (pilot: 60000, matching the "
                         "halved patchtst_lite)")
    ap.add_argument("--cs-halve", action="store_true",
                    help="apply the >90 s/epoch halving rule to cs_transformer")
    ap.add_argument("--smoke", action="store_true",
                    help="one fold, one epoch, tiny caps, nothing written")
    args = ap.parse_args()
    t_start = time.time()
    CHAMP_PARAMS["num_threads"] = args.tree_threads
    CB_PARAMS["thread_count"] = args.tree_threads
    SOTA_DIR.mkdir(parents=True, exist_ok=True)
    ev.PREDS_DIR.mkdir(parents=True, exist_ok=True)
    order = ["champ", "lambdarank", "lambdarank51", "huber", "catboost",
             "catboost51", "ensemble", "patchtst", "cstf", "dlinear",
             "catboost_fixed", "league", "annotate"]
    parts = order if args.parts == "all" else [p.strip() for p in args.parts.split(",")]
    unknown = set(parts) - set(order)
    assert not unknown, f"unknown parts {unknown}"

    feats10 = champion_features()
    if set(parts) - {"league", "annotate", "ensemble"}:
        seed_everything()
        df, features, splits = load_dataset()
        d = df["date"].to_numpy()
        assert (d[1:] >= d[:-1]).all(), "dataset not date-sorted"
        assert isinstance(df.index, pd.RangeIndex)
        log(f"dataset {len(df)} rows, {len(features)} features; parts={parts}; "
            f"torch {torch.__version__} threads=2 seed={SEED}", to_file=True)
    channels = feats10 + [c for c in SEQ_EXTRA if c not in feats10]

    if args.smoke:
        ctx = build_seq_context(df, channels)
        run_seq_model("patchtst_lite", "patchtst", df, features, splits, channels, ctx, smoke=True)
        run_seq_model("dlinear", "dlinear", df, features, splits, channels, ctx, smoke=True)
        run_cs_transformer(df, features, splits, feats10, smoke=True)
        log(f"smoke done in {time.time() - t_start:.0f}s")
        return

    lgb_params = {k: v for k, v in CHAMP_PARAMS.items()}
    ctx = None
    for part in parts:
        log(f"=== {part} (elapsed {(time.time() - t_start) / 60:.1f} min) ===", to_file=True)
        if part == "champ":
            pay = run_trees("champion", "champion_ref", feats10, df, features, splits,
                            "REFERENCE, not a challenger: same-box re-run of the champion "
                            "config (lgbm_fs_selected) on the clean dataset, for timing "
                            "and rank-IC on identical footing.",
                            {**lgb_params, "objective": "binary"})
            ref = pd.read_parquet(CHAMP_PREDS)
            mine = pd.read_parquet(ev.PREDS_DIR / f"champion_ref__{TASK}.parquet")
            ref["date"] = pd.to_datetime(ref["date"])
            mm = mine.merge(ref, on=["date", "ticker", "fold"], suffixes=("", "_ref"))
            diff = float(np.abs(mm["score"] - mm["score_ref"]).max())
            log(f"[champion_ref] rows matched {len(mm)}/{len(ref)}; max |score - "
                f"clean preds| = {diff:.2e}", to_file=True)
            p = SOTA_DIR / f"champion_ref__{TASK}.json"
            dd = json.loads(p.read_text())
            dd["family"] = "reference"
            dd["params"]["reproducibility"] = {"rows_matched": int(len(mm)),
                                               "max_abs_score_diff_vs_clean_preds": diff}
            p.write_text(json.dumps(dd, indent=1, default=str))
        elif part == "lambdarank":
            run_trees("lambdarank", "lgbm_lambdarank", feats10, df, features, splits,
                      "LGBMRanker(objective=lambdarank) with the champion's tree "
                      "hyper-parameters; query group = one date (rows date-sorted); "
                      "relevance = floor(10*y_rank_20d) clipped to 0..9. LightGBM ranking "
                      "defaults kept (label_gain 2^g-1, lambdarank_truncation_level=30, "
                      "so the gradient concentrates on the top ~30 names per date). Score "
                      "= raw ranker output: AUC, decile spread and rank-IC are valid; "
                      "Brier and acc@0.5 are NOT meaningful for a non-probability score.",
                      {**lgb_params, "objective": "lambdarank",
                       "relevance": "floor(10*y_rank_20d) clipped 0..9",
                       "query": "date"}, score_kind="ranker_raw")
        elif part == "lambdarank51":
            run_trees("lambdarank", "lgbm_lambdarank_f51", features, df, features, splits,
                      "As lgbm_lambdarank but on all 51 features (harness 'raw' "
                      "preprocessing = train-median impute, as the champion). Brier/acc "
                      "not meaningful (ranker score).",
                      {**lgb_params, "objective": "lambdarank",
                       "relevance": "floor(10*y_rank_20d) clipped 0..9",
                       "query": "date"}, score_kind="ranker_raw")
        elif part == "huber":
            run_trees("huber", "lgbm_huber", feats10, df, features, splits,
                      "LGBMRegressor(objective=huber, alpha=0.9) with the champion's "
                      "tree hyper-parameters on y_excess_20d clipped to +/-0.30; score = "
                      "predicted excess return. In LightGBM alpha is the Huber delta: "
                      "with |target| <= 0.30 every residual is far inside 0.9, so this is "
                      "effectively least squares on the clipped target. Brier/acc not "
                      "meaningful (score is a return forecast, not a probability).",
                      {**lgb_params, "objective": "huber", "alpha": 0.9,
                       "target": "clip(y_excess_20d, -0.30, 0.30)"},
                      score_kind="regression")
        elif part in ("catboost", "catboost51"):
            fs = feats10 if part == "catboost" else features
            name = "catboost" if part == "catboost" else "catboost_f51"
            run_trees("catboost", name, fs, df, features, splits,
                      f"CatBoostClassifier(depth 6, lr 0.05, <=600 iterations, l2 5, "
                      f"seed 108, 2 threads) on {len(fs)} features (harness 'raw' "
                      "preprocessing). Tree count chosen by early stopping (inner-val AUC, "
                      f"od_wait {CB_OD_WAIT}) on the last 15% of train ROWS (time-ordered; "
                      "20 sessions before it purged from the inner-fit set), then refit "
                      "on ALL train rows with that tree count. (A first run that early-"
                      "stopped on Logloss collapsed to 0-1 trees on 4/5 folds because the "
                      "inner-val tails straddle the March-2026 regime break; it is kept "
                      "as catboost_es_logloss.)",
                      {**CB_PARAMS, "od_type": "Iter", "od_wait": CB_OD_WAIT,
                       "eval_metric_for_stopping": "AUC",
                       "inner_val": "last 15% of train rows (date-aligned), 20-session purge",
                       "final_fit": "all train rows, iterations = best_iteration + 1"})
        elif part == "catboost_fixed":
            run_trees("catboost_fixed", "catboost_fixed600", feats10, df, features, splits,
                      "DIAGNOSTIC (not in the original spec): CatBoost with the same "
                      "hyper-parameters as 'catboost' but the champion's protocol -- no "
                      "early stopping, the spec's full 600 iterations on all train rows. "
                      "Added because early stopping on the time-ordered inner tail chose "
                      "0-186 trees (the tails straddle the March-2026 regime break), which "
                      "confounds 'CatBoost the algorithm' with 'early stopping on a "
                      "regime-break tail'. Defined before seeing its test results; not "
                      "eligible to be promoted on this pilot.",
                      {**CB_PARAMS, "early_stopping": "none (fixed 600 iterations)"})
        elif part == "ensemble":
            run_ensemble(feats10)
        elif part in ("patchtst", "dlinear"):
            if ctx is None:
                ctx = build_seq_context(df, channels)
            if part == "patchtst":
                run_seq_model("patchtst_lite", "patchtst", df, features, splits, channels, ctx)
            else:
                run_seq_model("dlinear", "dlinear", df, features, splits, channels, ctx,
                              cap0=args.seq_cap)
        elif part == "cstf":
            run_cs_transformer(df, features, splits, feats10, halve=args.cs_halve)
        elif part == "league":
            run_league()
        elif part == "annotate":
            run_annotate()
    log(f"ALL DONE ({parts}) in {(time.time() - t_start) / 60:.1f} min", to_file=True)


if __name__ == "__main__":
    main()

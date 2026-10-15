#!/usr/bin/env python3
"""Shared walk-forward evaluation harness.

Every modeling agent reports through ``run_standard_eval`` (sklearn-style
models) or the lower-level ``iter_folds`` + ``save_results`` (custom
PyTorch/RL models). The protocol is fixed so numbers are comparable:

* purged, embargoed walk-forward folds from ml/data/splits.json
  (train = labeled rows dated <= train_end; test = [test_start, test_end]);
* primary task ``beat_mkt_20d`` (clean-masked), secondary ``up_5d``;
* metrics: ROC AUC (headline), PR AUC, Brier, accuracy@0.5, and the
  economic view -- decile spread + top-decile mean forward return;
* standardized JSON into ml/results/, per-row scores into
  ml/results/preds/ for the evaluator/report agents (both gitignored
  except the JSONs).

Preprocessing is owned by the harness (median impute -> winsorize ->
standardize, all fit on train only) so no agent can leak test statistics.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (average_precision_score, brier_score_loss,
                             roc_auc_score)

ML_DIR = Path(__file__).resolve().parent
DATA_DIR = ML_DIR / "data"
RESULTS_DIR = ML_DIR / "results"
PREDS_DIR = RESULTS_DIR / "preds"
SEED = 108

TASKS = {
    # task -> (binary label col, forward-return col for economics, clean mask col)
    "beat_mkt_20d": ("label_beat_mkt_20d", "y_excess_20d", "y_clean_20d"),
    "up_5d": ("label_up_5d", "fwd_ret_5d", None),
}


def load_dataset():
    df = pd.read_parquet(DATA_DIR / "model_dataset.parquet")
    df["date"] = pd.to_datetime(df["date"])
    manifest = json.loads((DATA_DIR / "manifest.json").read_text())
    splits = json.loads((DATA_DIR / "splits.json").read_text())
    return df, manifest["features"], splits


@dataclass
class Fold:
    name: str
    is_holdout: bool
    X_train: np.ndarray
    y_train: np.ndarray
    X_test: np.ndarray
    y_test: np.ndarray
    fwd_test: np.ndarray          # forward return for economic metrics
    meta_test: pd.DataFrame       # date, ticker of test rows
    train_df: pd.DataFrame        # raw train rows (for sequence/RL models)
    test_df: pd.DataFrame


class Preprocessor:
    """Median impute -> winsorize(1,99) -> standardize; fit on train only."""

    def __init__(self, mode: str = "scaled"):
        assert mode in ("scaled", "raw")
        self.mode = mode

    def fit(self, X: pd.DataFrame):
        # A feature can be entirely NaN in an early train window (e.g.
        # ret_252d before a year of history exists); its *_isnan indicator
        # carries the signal, the value column falls back to 0.
        self.median_ = X.median()
        if self.mode == "scaled":
            lo = X.quantile(0.01)
            hi = X.quantile(0.99)
            self.lo_, self.hi_ = lo, hi
            Xc = X.fillna(self.median_).clip(lo, hi, axis=1)
            self.mean_ = Xc.mean().fillna(0.0)
            self.std_ = Xc.std().replace(0, 1.0).fillna(1.0)
        return self

    def transform(self, X: pd.DataFrame) -> np.ndarray:
        X = X.fillna(self.median_)
        if self.mode == "scaled":
            X = X.clip(self.lo_, self.hi_, axis=1)
            X = (X - self.mean_) / self.std_
        return X.fillna(0.0).to_numpy(dtype=np.float32)


def _task_frame(df: pd.DataFrame, task: str) -> pd.DataFrame:
    label, fwd, clean = TASKS[task]
    m = df[label].notna()
    if clean:
        m &= df[clean].astype(bool)
    return df[m]


def iter_folds(df: pd.DataFrame, features: list[str], splits: dict, task: str,
               preprocess: str = "scaled", feature_subset: list[str] | None = None):
    """Yield Fold objects per walk-forward fold, then the holdout."""
    label, fwd, _ = TASKS[task]
    feats = feature_subset or features
    tdf = _task_frame(df, task)
    for spec in splits["folds"] + [splits["holdout"]]:
        tr = tdf[tdf["date"] <= spec["train_end"]]
        te = tdf[(tdf["date"] >= spec["test_start"]) & (tdf["date"] <= spec["test_end"])]
        if tr.empty or te.empty:
            continue
        prep = Preprocessor(preprocess).fit(tr[feats])
        yield Fold(
            name=spec["name"], is_holdout=(spec["name"] == "holdout"),
            X_train=prep.transform(tr[feats]), y_train=tr[label].to_numpy(dtype=np.float32),
            X_test=prep.transform(te[feats]), y_test=te[label].to_numpy(dtype=np.float32),
            fwd_test=te[fwd].to_numpy(dtype=np.float32),
            meta_test=te[["date", "ticker"]].reset_index(drop=True),
            train_df=tr, test_df=te,
        )


def compute_metrics(y: np.ndarray, score: np.ndarray, fwd: np.ndarray) -> dict:
    out = {
        "auc": float(roc_auc_score(y, score)),
        "pr_auc": float(average_precision_score(y, score)),
        "brier": float(brier_score_loss(y, np.clip(score, 0, 1))),
        "acc": float(((score > 0.5).astype(float) == y).mean()),
        "n": int(len(y)),
        "base_rate": float(y.mean()),
    }
    ok = ~np.isnan(fwd)
    if ok.sum() > 100:
        s, f = score[ok], fwd[ok]
        deciles = pd.qcut(pd.Series(s).rank(method="first"), 10, labels=False)
        by_dec = pd.Series(f).groupby(deciles).mean()
        out["decile_spread"] = float(by_dec.iloc[-1] - by_dec.iloc[0])
        out["top_decile_mean_fwd"] = float(by_dec.iloc[-1])
        out["decile_means"] = [float(x) for x in by_dec.tolist()]
    return out


def save_results(payload: dict) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{payload['model']}__{payload['task']}.json"
    path.write_text(json.dumps(payload, indent=1, default=str))
    return path


def save_preds(model: str, task: str, frames: list[pd.DataFrame]) -> Path:
    PREDS_DIR.mkdir(parents=True, exist_ok=True)
    path = PREDS_DIR / f"{model}__{task}.parquet"
    pd.concat(frames, ignore_index=True).to_parquet(path, index=False)
    return path


def run_standard_eval(model_name: str, family: str, agent: str, make_model,
                      tasks=("beat_mkt_20d", "up_5d"), preprocess: str = "scaled",
                      feature_subset: list[str] | None = None, params: dict | None = None,
                      notes: str = "", df=None, features=None, splits=None) -> dict:
    """Full protocol for any sklearn-style classifier factory.

    ``make_model(task) -> estimator`` with fit(X, y) / predict_proba(X).
    Writes results JSON + preds parquet per task; returns {task: payload}.
    """
    if df is None:
        df, features, splits = load_dataset()
    summaries = {}
    for task in tasks:
        fold_rows, pred_frames = [], []
        holdout = None
        t0 = time.time()
        for fold in iter_folds(df, features, splits, task, preprocess, feature_subset):
            est = make_model(task)
            est.fit(fold.X_train, fold.y_train)
            score = est.predict_proba(fold.X_test)[:, 1]
            m = compute_metrics(fold.y_test, score, fold.fwd_test)
            m["fold"] = fold.name
            m["n_train"] = int(len(fold.y_train))
            if fold.is_holdout:
                holdout = m
            else:
                fold_rows.append(m)
            pf = fold.meta_test.copy()
            pf["score"], pf["y"], pf["fwd"] = score, fold.y_test, fold.fwd_test
            pf["fold"] = fold.name
            pred_frames.append(pf)
        aucs = [r["auc"] for r in fold_rows]
        payload = {
            "model": model_name, "family": family, "agent": agent, "task": task,
            "params": params or {}, "preprocess": preprocess,
            "n_features": len(feature_subset or features),
            "feature_subset": feature_subset,
            "folds": fold_rows,
            "cv_auc_mean": float(np.mean(aucs)) if aucs else None,
            "cv_auc_std": float(np.std(aucs)) if aucs else None,
            "holdout": holdout,
            "train_seconds": round(time.time() - t0, 1),
            "notes": notes,
        }
        save_results(payload)
        save_preds(model_name, task, pred_frames)
        summaries[task] = payload
        print(f"[{model_name} | {task}] cv_auc={payload['cv_auc_mean']:.4f} "
              f"(+/-{payload['cv_auc_std']:.4f}) holdout_auc={holdout['auc']:.4f} "
              f"({payload['train_seconds']}s)" if holdout else f"[{model_name}|{task}] no holdout")
    return summaries

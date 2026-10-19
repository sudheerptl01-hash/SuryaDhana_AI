#!/usr/bin/env python3
"""5-year walk-forward runner: the pilot protocol over ~43 monthly folds.

Same metrics and result schema as ml.evaluation.run_standard_eval, with two
changes that the scale demands:

* a ROLLING training window (default: the latest 504 sessions ≈ 2 years of
  labeled rows before each fold's embargo) instead of an ever-expanding one,
  so a fold trained in 2026 does not cost 5× a fold trained in 2023 and the
  model adapts to the regime it is scored in;
* folds run in parallel worker processes forked after the frame is loaded,
  so nothing is pickled per fold.

Results go to ml/results/scale5y/ (JSON per model, preds parquet per model).

    python3 -m ml.scale5y --data ml/data_5y --models champion10 all51 lr_l2 baseline_mom
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import time
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "2")

import numpy as np
import pandas as pd

from ml.evaluation import TASKS, Preprocessor, compute_metrics

ML_DIR = Path(__file__).resolve().parent
SEED = 108
CHAMPION10 = ["atr_pct", "deliv_pct_sma_20", "dist_52w_high", "ret_126d", "mom_12_1",
              "cs_rank_mom_20", "cs_rank_ret_126", "cs_rank_vol_20", "deliv_pct", "ret_63d"]

_DF: pd.DataFrame | None = None          # set before the pool is forked
_DATES: pd.DatetimeIndex | None = None


def make_model(name: str, n_threads: int):
    from lightgbm import LGBMClassifier
    from sklearn.linear_model import LogisticRegression
    if name in ("champion10", "all51", "lgbm10", "lgbm_all"):
        return LGBMClassifier(num_leaves=63, learning_rate=0.05, n_estimators=300,
                              feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1,
                              min_data_in_leaf=200, num_threads=n_threads, verbosity=-1,
                              random_state=SEED)
    if name == "lgbm_lambdarank":
        from lightgbm import LGBMRanker
        return LGBMRanker(objective="lambdarank", num_leaves=63, learning_rate=0.05,
                          n_estimators=300, feature_fraction=0.8, bagging_fraction=0.8,
                          bagging_freq=1, min_data_in_leaf=200, num_threads=n_threads,
                          verbosity=-1, random_state=SEED)
    if name in ("lr_l2", "baseline_mom"):
        return LogisticRegression(C=0.01 if name == "lr_l2" else 1.0, max_iter=1000)
    raise ValueError(name)


MODEL_SPECS = {
    "champion10":     dict(feats=CHAMPION10, preprocess="raw",    family="trees"),
    "all51":          dict(feats=None,       preprocess="raw",    family="trees"),
    "lgbm_lambdarank": dict(feats=CHAMPION10, preprocess="raw",   family="ranking"),
    "lr_l2":          dict(feats=None,       preprocess="scaled", family="linear"),
    "baseline_mom":   dict(feats=["cs_rank_mom_20"], preprocess="scaled", family="baseline"),
}


def _fold_job(args):
    name, task, spec, feats, train_sessions, n_threads = args
    df, dates = _DF, _DATES
    label, fwd, clean = TASKS[task]
    m = df[label].notna()
    if clean:
        m &= df[clean].astype(bool)
    tdf = df[m]
    tr = tdf[tdf["date"] <= spec["train_end"]]
    if train_sessions:
        first = dates[max(dates.get_loc(pd.Timestamp(spec["train_end"])) - train_sessions, 0)]
        tr = tr[tr["date"] >= first]
    te = tdf[(tdf["date"] >= spec["test_start"]) & (tdf["date"] <= spec["test_end"])]
    if tr.empty or te.empty:
        return None
    prep = Preprocessor(MODEL_SPECS[name]["preprocess"]).fit(tr[feats])
    Xtr, Xte = prep.transform(tr[feats]), prep.transform(te[feats])
    ytr, yte = tr[label].to_numpy(np.float32), te[label].to_numpy(np.float32)
    t0 = time.time()
    est = make_model(name, n_threads)
    if name == "lgbm_lambdarank":
        grades = tr.groupby("date")[fwd].rank(pct=True).fillna(0.5)
        rel = np.minimum((grades * 10).astype(int), 9).to_numpy()
        order = np.argsort(tr["date"].to_numpy(), kind="stable")
        groups = tr["date"].iloc[order].value_counts(sort=False).reindex(
            tr["date"].iloc[order].unique()).to_numpy()
        est.fit(Xtr[order], rel[order], group=groups)
        score = est.predict(Xte)
        score = 1 / (1 + np.exp(-score))            # monotone map for the metric suite
    else:
        est.fit(Xtr, ytr)
        score = est.predict_proba(Xte)[:, 1]
    met = compute_metrics(yte, score, te[fwd].to_numpy(np.float32))
    met.update(fold=spec["name"], n_train=int(len(tr)), train_seconds=round(time.time() - t0, 1))
    preds = te[["date", "ticker"]].copy()
    preds["score"], preds["y"], preds["fwd"], preds["fold"] = score, yte, te[fwd].to_numpy(), spec["name"]
    return met, preds


def run(data_dir: Path, out_dir: Path, models: list[str], task: str, train_sessions: int,
        n_jobs: int, n_threads: int) -> None:
    global _DF, _DATES
    _DF = pd.read_parquet(data_dir / "model_dataset.parquet")
    _DF["date"] = pd.to_datetime(_DF["date"])
    _DATES = pd.DatetimeIndex(sorted(_DF["date"].unique()))
    manifest = json.loads((data_dir / "manifest.json").read_text())
    splits = json.loads((data_dir / "splits.json").read_text())
    specs = splits["folds"] + [splits["holdout"]]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "preds").mkdir(exist_ok=True)
    ctx = mp.get_context("fork")
    for name in models:
        feats = MODEL_SPECS[name]["feats"] or manifest["features"]
        t0 = time.time()
        jobs = [(name, task, s, feats, train_sessions, n_threads) for s in specs]
        with ctx.Pool(n_jobs) as pool:
            results = [r for r in pool.map(_fold_job, jobs) if r is not None]
        folds = [m for m, _ in results if m["fold"] != "holdout"]
        holdout = next((m for m, _ in results if m["fold"] == "holdout"), None)
        aucs = [f["auc"] for f in folds]
        payload = {
            "model": name, "family": MODEL_SPECS[name]["family"], "agent": "lead-scale5y",
            "task": task, "params": {"train_sessions": train_sessions, "n_jobs": n_jobs},
            "preprocess": MODEL_SPECS[name]["preprocess"], "n_features": len(feats),
            "feature_subset": feats if len(feats) <= 12 else None,
            "folds": folds, "cv_auc_mean": float(np.mean(aucs)), "cv_auc_std": float(np.std(aucs)),
            "min_fold_auc": float(np.min(aucs)), "pct_folds_ge_050": float(np.mean(np.array(aucs) >= 0.5)),
            "holdout": holdout, "train_seconds": round(time.time() - t0, 1),
            "notes": f"5-year walk-forward, {len(folds)} monthly folds, rolling {train_sessions}-session train window",
        }
        (out_dir / f"{name}__{task}.json").write_text(json.dumps(payload, indent=1, default=str))
        pd.concat([p for _, p in results], ignore_index=True).to_parquet(
            out_dir / "preds" / f"{name}__{task}.parquet", index=False)
        print(f"[{name} | {task}] folds={len(folds)} cv_auc={payload['cv_auc_mean']:.4f}"
              f"±{payload['cv_auc_std']:.4f} min={payload['min_fold_auc']:.4f} "
              f"ge50={payload['pct_folds_ge_050']:.0%} holdout={holdout['auc'] if holdout else float('nan'):.4f} "
              f"({payload['train_seconds']}s)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ML_DIR / "data_5y"))
    ap.add_argument("--out", default=str(ML_DIR / "results" / "scale5y"))
    ap.add_argument("--models", nargs="+", default=["champion10", "all51", "lr_l2", "baseline_mom"])
    ap.add_argument("--task", default="beat_mkt_20d")
    ap.add_argument("--train-sessions", type=int, default=504)
    ap.add_argument("--n-jobs", type=int, default=2)
    ap.add_argument("--n-threads", type=int, default=2)
    a = ap.parse_args()
    run(Path(a.data), Path(a.out), a.models, a.task, a.train_sessions, a.n_jobs, a.n_threads)

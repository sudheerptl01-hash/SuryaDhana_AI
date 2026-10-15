#!/usr/bin/env python3
"""Tree-family models for the SuryaDhana ML evaluation (agent: quant-trees).

Models: decision_tree, random_forest, xgboost, lightgbm.

Protocol (fixed, see ml/README.md + ml/evaluation.py):
* preprocess="raw" (median impute only -- trees need no scaling), seed 108,
  n_jobs/num_threads = 2 everywhere (shared 4-core box).
* TUNING DISCIPLINE: configs are screened ONLY on the first two CV folds
  (2026-04, 2026-05) via ml.evaluation.iter_folds + compute_metrics on the
  PRIMARY task (beat_mkt_20d); the config with the best mean screen AUC then
  runs the full protocol (run_standard_eval, both tasks) exactly once.
  The holdout is never touched for tuning -- only run_standard_eval sees it.
* GBM early stopping: the estimator wrapper carves an inner TIME-ORDERED
  validation set = the last 15% of the rows of the train matrix passed to
  fit(). ASSUMPTION (stated per protocol): the harness preserves the
  dataset's (date, ticker) sort, so the final 15% of train rows are the
  latest train dates -- never random rows, never test rows. This is
  asserted at runtime in main().

Run: cd <repo root> && python3 -m ml.models.trees
"""
from __future__ import annotations

import os

os.environ["OMP_NUM_THREADS"] = "2"  # before numpy/sklearn/xgb/lgbm imports

import json
import time

import numpy as np

from ml.evaluation import (RESULTS_DIR, SEED, compute_metrics, iter_folds,
                           load_dataset, run_standard_eval)

FAMILY = "trees"
AGENT = "quant-trees"
PRIMARY = "beat_mkt_20d"
SCREEN_FOLD_NAMES = ("2026-04", "2026-05")
INNER_VAL_FRAC = 0.15
RF_SCREEN_TREES = 100  # ranking proxy for the 300-tree final (runtime budget)

INNER_VAL_NOTE = (
    "GBM fit() carves an inner time-ordered validation = last 15% of the "
    "train-matrix ROWS for early stopping (never random rows, never test "
    "rows). Assumption: the harness preserves the dataset's (date,ticker) "
    "sort, so the row tail ~= the latest train dates; dataset date order is "
    "asserted at runtime."
)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Early-stopping wrapper (xgboost / lightgbm)
# ---------------------------------------------------------------------------
class GBMEarlyStop:
    """sklearn-style wrapper: fit(X, y) internally splits off the last
    `val_frac` of rows (time-ordered tail, see INNER_VAL_NOTE) as the
    early-stopping eval set; predict_proba uses the best iteration."""

    def __init__(self, kind: str, params: dict, val_frac: float = INNER_VAL_FRAC):
        assert kind in ("xgb", "lgbm")
        self.kind = kind
        self.params = params
        self.val_frac = val_frac

    def fit(self, X, y):
        n = len(y)
        cut = max(1, int(round(n * (1.0 - self.val_frac))))
        X_tr, y_tr = X[:cut], y[:cut]
        X_va, y_va = X[cut:], y[cut:]
        if self.kind == "xgb":
            from xgboost import XGBClassifier

            self.model_ = XGBClassifier(**self.params)
            self.model_.fit(X_tr, y_tr, eval_set=[(X_va, y_va)], verbose=False)
            self.best_iteration_ = int(self.model_.best_iteration)
        else:
            import lightgbm as lgb

            self.model_ = lgb.LGBMClassifier(**self.params)
            self.model_.fit(
                X_tr, y_tr, eval_X=X_va, eval_y=y_va,
                callbacks=[lgb.early_stopping(50, verbose=False)],
            )
            bi = self.model_.best_iteration_
            self.best_iteration_ = int(bi) if bi else int(self.params["n_estimators"])
        return self

    def predict_proba(self, X):
        return self.model_.predict_proba(X)


# ---------------------------------------------------------------------------
# Estimator factories
# ---------------------------------------------------------------------------
def make_dt(cfg: dict):
    from sklearn.tree import DecisionTreeClassifier

    return DecisionTreeClassifier(
        max_depth=cfg["max_depth"], min_samples_leaf=cfg["min_samples_leaf"],
        random_state=SEED,
    )


def make_rf(cfg: dict, n_estimators: int = 300):
    from sklearn.ensemble import RandomForestClassifier

    return RandomForestClassifier(
        n_estimators=n_estimators, max_depth=cfg["max_depth"],
        min_samples_leaf=cfg["min_samples_leaf"], max_features="sqrt",
        n_jobs=2, random_state=SEED,
    )


def xgb_params(cfg: dict) -> dict:
    return dict(
        n_estimators=600, learning_rate=0.05, max_depth=cfg["max_depth"],
        min_child_weight=cfg["min_child_weight"], subsample=0.8,
        colsample_bytree=0.8, tree_method="hist", n_jobs=2,
        eval_metric="auc", early_stopping_rounds=50, random_state=SEED,
    )


def lgbm_params(cfg: dict) -> dict:
    # native lgbm names (feature_fraction/bagging_*/min_data_in_leaf) pass
    # through the sklearn wrapper into booster params and take precedence.
    return dict(
        n_estimators=800, learning_rate=0.05, num_leaves=cfg["num_leaves"],
        min_data_in_leaf=cfg["min_data_in_leaf"], feature_fraction=0.8,
        bagging_fraction=0.8, bagging_freq=1, metric="auc",
        num_threads=2, verbosity=-1, random_state=SEED,
    )


def make_xgb(cfg: dict):
    return GBMEarlyStop("xgb", xgb_params(cfg))


def make_lgbm(cfg: dict):
    return GBMEarlyStop("lgbm", lgbm_params(cfg))


# ---------------------------------------------------------------------------
# Screening (first two CV folds ONLY, primary task, mean AUC)
# ---------------------------------------------------------------------------
def get_screen_folds(df, features, splits):
    folds = []
    for f in iter_folds(df, features, splits, PRIMARY, preprocess="raw"):
        if f.name in SCREEN_FOLD_NAMES:
            folds.append(f)
        if len(folds) == len(SCREEN_FOLD_NAMES):
            break
    assert [f.name for f in folds] == list(SCREEN_FOLD_NAMES)
    return folds


def screen(label: str, grid: list[dict], make_est, folds,
           keep_after_fold1: int | None = None):
    """Evaluate grid on the screen folds; optionally prune to the top-k
    configs after fold 1 (runtime budget -- drop clearly losing families).
    Returns (best_cfg, per-config fold AUC lists)."""
    aucs: dict[int, list[float]] = {i: [] for i in range(len(grid))}
    survivors = list(range(len(grid)))
    for fi, fold in enumerate(folds):
        if fi == 1 and keep_after_fold1 and keep_after_fold1 < len(survivors):
            survivors = sorted(
                sorted(survivors, key=lambda i: -aucs[i][0])[:keep_after_fold1])
            log(f"[screen {label}] pruned to top-{keep_after_fold1} after "
                f"fold 1: {[grid[i] for i in survivors]}")
        for i in survivors:
            t0 = time.time()
            est = make_est(grid[i])
            est.fit(fold.X_train, fold.y_train)
            score = est.predict_proba(fold.X_test)[:, 1]
            m = compute_metrics(fold.y_test, score, fold.fwd_test)
            aucs[i].append(m["auc"])
            bi = getattr(est, "best_iteration_", None)
            extra = f" best_iter={bi}" if bi is not None else ""
            log(f"[screen {label}] fold={fold.name} cfg={grid[i]} "
                f"auc={m['auc']:.4f} ({time.time() - t0:.0f}s{extra})")
    best_i = max(survivors, key=lambda i: float(np.mean(aucs[i])))
    log(f"[screen {label}] CHOSEN {grid[best_i]} "
        f"mean_auc={np.mean(aucs[best_i]):.4f} folds={aucs[best_i]}")
    return grid[best_i], aucs


# ---------------------------------------------------------------------------
# Gain importances from the best GBM, refit on the holdout train window
# ---------------------------------------------------------------------------
def write_gain_importances(best_name: str, best_cfg: dict, params_json: dict,
                           df, features, splits):
    hold = None
    for f in iter_folds(df, features, splits, PRIMARY, preprocess="raw"):
        if f.is_holdout:
            hold = f
    assert hold is not None
    est = make_xgb(best_cfg) if best_name == "xgboost" else make_lgbm(best_cfg)
    t0 = time.time()
    est.fit(hold.X_train, hold.y_train)
    if best_name == "xgboost":
        score = est.model_.get_booster().get_score(importance_type="gain")
        gains = {features[int(k[1:])]: float(v) for k, v in score.items()}
    else:
        arr = est.model_.booster_.feature_importance(importance_type="gain")
        gains = {features[i]: float(arr[i]) for i in range(len(features))
                 if arr[i] > 0}
    top30 = dict(sorted(gains.items(), key=lambda kv: -kv[1])[:30])
    payload = {
        "model": best_name,
        "params": params_json,
        "task": PRIMARY,
        "window": f"holdout-fold train (date <= {splits['holdout']['train_end']})",
        "importance_type": "gain",
        "best_iteration": est.best_iteration_,
        "n_train": int(len(hold.y_train)),
        "importances": top30,
    }
    path = RESULTS_DIR / "tree_importances.json"
    path.write_text(json.dumps(payload, indent=1))
    log(f"wrote {path} from {best_name} "
        f"(best_iter={est.best_iteration_}, {time.time() - t0:.0f}s)")


# ---------------------------------------------------------------------------
def main():
    t_start = time.time()
    df, features, splits = load_dataset()
    # runtime check backing the row-order assumption for the inner time split
    d = df["date"].to_numpy()
    assert (d[1:] >= d[:-1]).all(), "dataset not date-sorted; inner split invalid"
    log(f"dataset ok: {len(df)} rows, {len(features)} features, date-sorted")

    screen_folds = get_screen_folds(df, features, splits)
    log(f"screen folds: {[(f.name, len(f.y_train), len(f.y_test)) for f in screen_folds]}")

    # ---- screens (primary task, first two folds only) ----
    dt_grid = [{"max_depth": d_, "min_samples_leaf": l}
               for d_ in (3, 4, 5, 6) for l in (500, 2000)]
    dt_best, dt_aucs = screen("decision_tree", dt_grid, make_dt, screen_folds)

    xgb_grid = [{"max_depth": d_, "min_child_weight": w}
                for d_ in (4, 6) for w in (50, 200)]
    xgb_best, xgb_aucs = screen("xgboost", xgb_grid, make_xgb, screen_folds)

    lgbm_grid = [{"num_leaves": nl, "min_data_in_leaf": md}
                 for nl in (31, 63) for md in (200, 500)]
    lgbm_best, lgbm_aucs = screen("lightgbm", lgbm_grid, make_lgbm, screen_folds)

    rf_grid = [{"max_depth": d_, "min_samples_leaf": l}
               for d_ in (8, 12, None) for l in (200, 500)]
    rf_best, rf_aucs = screen(
        "random_forest", rf_grid,
        lambda cfg: make_rf(cfg, n_estimators=RF_SCREEN_TREES),
        screen_folds, keep_after_fold1=2)

    del screen_folds  # free memory before the full runs

    def mean_auc(aucs, grid, cfg):
        return float(np.mean(aucs[grid.index(cfg)]))

    base_note = ("Tuned ONLY on CV folds 2026-04 + 2026-05 (mean primary-task "
                 "AUC); holdout untouched for tuning. preprocess=raw (median "
                 "impute; trees need no scaling); seed 108.")

    # ---- full protocol runs (both tasks, run_standard_eval) ----
    log("=== final run: decision_tree ===")
    dt_params = {**dt_best, "criterion": "gini",
                 "screen_cv_auc_2folds": mean_auc(dt_aucs, dt_grid, dt_best)}
    run_standard_eval(
        "decision_tree", FAMILY, AGENT, lambda task: make_dt(dt_best),
        preprocess="raw", params=dt_params,
        notes=f"Interpretability baseline. {base_note} Grid 4x2 "
              "(max_depth x min_samples_leaf) screened in full.",
        df=df, features=features, splits=splits)

    log("=== final run: xgboost ===")
    xgb_params_json = {k: v for k, v in xgb_params(xgb_best).items()
                       if k not in ("n_jobs",)}
    xgb_params_json["inner_val"] = "last 15% of train rows (time-ordered tail)"
    xgb_params_json["screen_cv_auc_2folds"] = mean_auc(xgb_aucs, xgb_grid, xgb_best)
    xgb_summary = run_standard_eval(
        "xgboost", FAMILY, AGENT, lambda task: make_xgb(xgb_best),
        preprocess="raw", params=xgb_params_json,
        notes=f"{base_note} {INNER_VAL_NOTE}",
        df=df, features=features, splits=splits)

    log("=== final run: lightgbm ===")
    lgbm_params_json = {k: v for k, v in lgbm_params(lgbm_best).items()
                        if k not in ("num_threads", "verbosity")}
    lgbm_params_json["early_stopping_rounds"] = 50
    lgbm_params_json["inner_val"] = "last 15% of train rows (time-ordered tail)"
    lgbm_params_json["screen_cv_auc_2folds"] = mean_auc(lgbm_aucs, lgbm_grid, lgbm_best)
    lgbm_summary = run_standard_eval(
        "lightgbm", FAMILY, AGENT, lambda task: make_lgbm(lgbm_best),
        preprocess="raw", params=lgbm_params_json,
        notes=f"{base_note} {INNER_VAL_NOTE}",
        df=df, features=features, splits=splits)

    # ---- gain importances from the better GBM (primary cv_auc_mean) ----
    xgb_cv = xgb_summary[PRIMARY]["cv_auc_mean"]
    lgbm_cv = lgbm_summary[PRIMARY]["cv_auc_mean"]
    log(f"gbm cv_auc_mean ({PRIMARY}): xgboost={xgb_cv:.4f} lightgbm={lgbm_cv:.4f}")
    if xgb_cv >= lgbm_cv:
        write_gain_importances("xgboost", xgb_best, xgb_params_json,
                               df, features, splits)
    else:
        write_gain_importances("lightgbm", lgbm_best, lgbm_params_json,
                               df, features, splits)

    log("=== final run: random_forest (300 trees -- slow) ===")
    rf_params_json = {**rf_best, "n_estimators": 300, "max_features": "sqrt",
                      "screen_cv_auc_2folds": mean_auc(rf_aucs, rf_grid, rf_best),
                      "screen_n_estimators": RF_SCREEN_TREES}
    run_standard_eval(
        "random_forest", FAMILY, AGENT,
        lambda task: make_rf(rf_best, n_estimators=300),
        preprocess="raw", params=rf_params_json,
        notes=f"{base_note} Screened with n_estimators={RF_SCREEN_TREES} as a "
              "ranking proxy for the 300-tree final (runtime budget); grid "
              "pruned to top-2 configs after fold 2026-04.",
        df=df, features=features, splits=splits)

    log(f"ALL DONE in {(time.time() - t_start) / 60:.1f} min")


if __name__ == "__main__":
    main()

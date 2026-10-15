#!/usr/bin/env python3
"""Linear family (QUANT-LINEAR agent): logistic-regression models.

Models produced through the shared harness (ml.evaluation.run_standard_eval):

* ``baseline_mom`` -- logistic regression on the single feature
  ``cs_rank_mom_20``: the floor every fancier model must beat.
* ``lr_l2``       -- lbfgs L2, C tuned over {0.003,0.01,0.03,0.1,0.3,1.0}.
* ``lr_l1``       -- saga L1 (max_iter=300, tol=1e-3), C tuned over
  {0.003,0.01,0.03,0.1}; zeroed-coefficient counts recorded.
* ``lr_elastic``  -- optional (time permitting): saga elasticnet,
  l1_ratio=0.5, C screened in the best-C region.

Tuning discipline: C is chosen by mean PRIMARY-task AUC on the FIRST TWO CV
folds only (2026-04, 2026-05). The holdout is produced by the harness and is
never used for any choice. The saga screens run on a 150k-row train
subsample for speed; all final full-protocol fits use every train row.

Also writes ``ml/results/lr_coefficients.json``: the best full-feature
linear model refit on the holdout's train window (date <= holdout
train_end), standardized coefficients sorted by |coef|, chosen C per
family, and the L1 model's zeroed-coefficient count.

Run: ``cd /home/user/SuryaDhana_AI && python3 -m ml.models.logistic``
"""
from __future__ import annotations

import os

# Shared 4-core box: cap BLAS/OpenMP threads BEFORE importing numpy/sklearn.
os.environ["OMP_NUM_THREADS"] = "2"
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")

import gc
import itertools
import json
import time
import warnings

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression

from ml.evaluation import (RESULTS_DIR, SEED, compute_metrics, iter_folds,
                           load_dataset, run_standard_eval)

AGENT = "quant-linear"
FAMILY = "linear"
PRIMARY = "beat_mkt_20d"
TUNE_FOLD_NAMES = ["2026-04", "2026-05"]   # cheap screen -- never the holdout
L2_GRID = [0.003, 0.01, 0.03, 0.1, 0.3, 1.0]
L1_GRID = [0.003, 0.01, 0.03, 0.1]
L1_SCREEN_SUBSAMPLE = 150_000              # saga screens on a train subsample
ELASTIC_START_BUDGET_S = 12.5 * 60         # start optional elastic only if under

T0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - T0:6.1f}s] {msg}", flush=True)


# ---------------------------------------------------------------- builders
def build_baseline(C: float = 1.0) -> LogisticRegression:
    return LogisticRegression(penalty="l2", solver="lbfgs", max_iter=1000,
                              C=C, random_state=SEED)


def build_l2(C: float) -> LogisticRegression:
    return LogisticRegression(penalty="l2", solver="lbfgs", max_iter=1000,
                              C=C, random_state=SEED)


def build_l1(C: float) -> LogisticRegression:
    return LogisticRegression(penalty="l1", solver="saga", max_iter=300,
                              tol=1e-3, C=C, random_state=SEED)


def build_elastic(C: float) -> LogisticRegression:
    return LogisticRegression(penalty="elasticnet", solver="saga",
                              l1_ratio=0.5, max_iter=300, tol=1e-3,
                              C=C, random_state=SEED)


# ---------------------------------------------------------------- tuning
def screen_C(tune_folds, grid, build, subsample: int | None = None, tag: str = ""):
    """Mean PRIMARY-task AUC over the two tuning folds for each C.

    This is the cheap screen: folds 2026-04 and 2026-05 only. For saga a
    deterministic (seed 108) train subsample keeps it inside the budget.
    """
    table = []
    for C in grid:
        aucs, zeros, secs = [], [], []
        for f in tune_folds:
            X, y = f.X_train, f.y_train
            if subsample is not None and len(y) > subsample:
                rng = np.random.default_rng(SEED)
                idx = rng.choice(len(y), size=subsample, replace=False)
                X, y = X[idx], y[idx]
            t = time.time()
            est = build(C)
            est.fit(X, y)
            secs.append(round(time.time() - t, 1))
            m = compute_metrics(f.y_test, est.predict_proba(f.X_test)[:, 1],
                                f.fwd_test)
            aucs.append(m["auc"])
            zeros.append(int(np.sum(est.coef_[0] == 0.0)))
        row = {"C": C, "mean_auc": float(np.mean(aucs)),
               "fold_aucs": [round(a, 5) for a in aucs],
               "zero_coefs": zeros, "fit_seconds": secs}
        table.append(row)
        log(f"  screen {tag:10s} C={C:<6g} mean_auc={row['mean_auc']:.5f} "
            f"folds={row['fold_aucs']} zeros={zeros} secs={secs}")
    best = max(table, key=lambda r: r["mean_auc"])
    log(f"  -> {tag}: best C={best['C']} (mean tuning AUC {best['mean_auc']:.5f})")
    return best["C"], table


def main() -> None:
    log(f"QUANT-LINEAR start | seed={SEED} | OMP_NUM_THREADS="
        f"{os.environ['OMP_NUM_THREADS']}")
    df, features, splits = load_dataset()
    log(f"dataset: {len(df):,} rows x {len(features)} features")

    conv_counts: dict[str, int] = {}
    other_msgs: set[str] = set()

    with warnings.catch_warnings(record=True) as wlist:
        warnings.simplefilter("always")

        def mark(stage: str, i0: int) -> int:
            new = wlist[i0:]
            n_conv = sum(1 for w in new
                         if issubclass(w.category, ConvergenceWarning))
            if n_conv:
                conv_counts[stage] = conv_counts.get(stage, 0) + n_conv
                log(f"  ! {n_conv} ConvergenceWarning(s) during {stage}")
            for w in new:
                if not issubclass(w.category, ConvergenceWarning):
                    msg = f"{w.category.__name__}: {w.message}"
                    if msg not in other_msgs:
                        other_msgs.add(msg)
                        log(f"  ! warning during {stage}: {msg}")
            return len(wlist)

        # ---- materialize the two tuning folds (primary task, full features)
        i0 = len(wlist)
        tune_folds = list(itertools.islice(
            iter_folds(df, features, splits, PRIMARY, "scaled"),
            len(TUNE_FOLD_NAMES)))
        names = [f.name for f in tune_folds]
        assert names == TUNE_FOLD_NAMES, f"unexpected tuning folds: {names}"
        assert not any(f.is_holdout for f in tune_folds)
        for f in tune_folds:            # screens only need the arrays
            f.train_df = None
            f.test_df = None
        log("tuning folds: " + ", ".join(
            f"{f.name} (train {len(f.y_train):,} / test {len(f.y_test):,})"
            for f in tune_folds))
        i0 = mark("tuning-fold prep", i0)

        # ---- screens (folds 1-2 only, primary task only)
        log("screening lr_l2 (lbfgs, full train rows)")
        c_l2, l2_table = screen_C(tune_folds, L2_GRID, build_l2, tag="lr_l2")
        i0 = mark("lr_l2 screen", i0)

        log(f"screening lr_l1 (saga, {L1_SCREEN_SUBSAMPLE:,}-row train subsample)")
        c_l1, l1_table = screen_C(tune_folds, L1_GRID, build_l1,
                                  subsample=L1_SCREEN_SUBSAMPLE, tag="lr_l1")
        i0 = mark("lr_l1 screen", i0)

        del tune_folds
        gc.collect()

        # ---- full protocol runs (both tasks, all folds + holdout, full rows)
        results: dict[str, dict] = {}
        chosen_C: dict[str, float] = {}

        log("full protocol: baseline_mom (single feature cs_rank_mom_20)")
        results["baseline_mom"] = run_standard_eval(
            model_name="baseline_mom", family=FAMILY, agent=AGENT,
            make_model=lambda task: build_baseline(1.0),
            preprocess="scaled", feature_subset=["cs_rank_mom_20"],
            params={"C": 1.0, "penalty": "l2", "solver": "lbfgs",
                    "max_iter": 1000, "features": ["cs_rank_mom_20"]},
            notes="single-feature momentum floor; fixed C=1.0 (no tuning)",
            df=df, features=features, splits=splits)
        i0 = mark("baseline_mom full run", i0)

        log(f"full protocol: lr_l2 (C={c_l2})")
        chosen_C["lr_l2"] = c_l2
        results["lr_l2"] = run_standard_eval(
            model_name="lr_l2", family=FAMILY, agent=AGENT,
            make_model=lambda task: build_l2(c_l2),
            preprocess="scaled",
            params={"C": c_l2, "penalty": "l2", "solver": "lbfgs",
                    "max_iter": 1000},
            notes="tuned C on folds 1-2 only",
            df=df, features=features, splits=splits)
        i0 = mark("lr_l2 full run", i0)

        log(f"full protocol: lr_l1 (C={c_l1}, saga, full train rows)")
        chosen_C["lr_l1"] = c_l1
        results["lr_l1"] = run_standard_eval(
            model_name="lr_l1", family=FAMILY, agent=AGENT,
            make_model=lambda task: build_l1(c_l1),
            preprocess="scaled",
            params={"C": c_l1, "penalty": "l1", "solver": "saga",
                    "max_iter": 300, "tol": 1e-3},
            notes="tuned C on folds 1-2 only",
            df=df, features=features, splits=splits)
        i0 = mark("lr_l1 full run", i0)

        # ---- optional elastic net, only if comfortably inside the budget
        en_table = None
        if time.time() - T0 < ELASTIC_START_BUDGET_S:
            ext = [0.003, 0.01, 0.03, 0.1, 0.3]
            j = ext.index(c_l1)
            en_grid = ext[max(0, j - 1): j + 2]
            log(f"time permits: screening lr_elastic over best-C region {en_grid}")
            tune_folds = list(itertools.islice(
                iter_folds(df, features, splits, PRIMARY, "scaled"),
                len(TUNE_FOLD_NAMES)))
            for f in tune_folds:
                f.train_df = None
                f.test_df = None
            c_en, en_table = screen_C(tune_folds, en_grid, build_elastic,
                                      subsample=L1_SCREEN_SUBSAMPLE,
                                      tag="lr_elastic")
            del tune_folds
            gc.collect()
            i0 = mark("lr_elastic screen", i0)

            log(f"full protocol: lr_elastic (C={c_en}, l1_ratio=0.5)")
            chosen_C["lr_elastic"] = c_en
            results["lr_elastic"] = run_standard_eval(
                model_name="lr_elastic", family=FAMILY, agent=AGENT,
                make_model=lambda task: build_elastic(c_en),
                preprocess="scaled",
                params={"C": c_en, "penalty": "elasticnet", "l1_ratio": 0.5,
                        "solver": "saga", "max_iter": 300, "tol": 1e-3},
                notes="tuned C on folds 1-2 only",
                df=df, features=features, splits=splits)
            i0 = mark("lr_elastic full run", i0)
        else:
            log("skipping optional lr_elastic (outside time budget)")

        # ---- coefficient dump: best full-feature model, holdout train window
        full_models = [m for m in ("lr_l2", "lr_l1", "lr_elastic")
                       if m in results]
        best_name = max(full_models,
                        key=lambda m: results[m][PRIMARY]["cv_auc_mean"])
        log(f"best full-feature linear model by primary cv_auc_mean: "
            f"{best_name} (C={chosen_C[best_name]})")

        hold = None
        for f in iter_folds(df, features, splits, PRIMARY, "scaled"):
            hold = f                   # last yielded fold IS the holdout
        assert hold is not None and hold.is_holdout
        log(f"holdout train window (date <= {splits['holdout']['train_end']}): "
            f"{len(hold.y_train):,} rows")

        builders = {"lr_l2": build_l2, "lr_l1": build_l1,
                    "lr_elastic": build_elastic}
        best_est = builders[best_name](chosen_C[best_name])
        best_est.fit(hold.X_train, hold.y_train)

        if best_name == "lr_l1":
            l1_est = best_est
        else:
            l1_est = build_l1(chosen_C["lr_l1"])
            l1_est.fit(hold.X_train, hold.y_train)
        l1_coef = l1_est.coef_[0]
        l1_zeroed = [f for f, c in zip(features, l1_coef) if c == 0.0]
        i0 = mark("coefficient refits", i0)

        coefs = sorted(zip(features, best_est.coef_[0].astype(float)),
                       key=lambda kv: -abs(kv[1]))
        payload = {
            "model": best_name,
            "task": PRIMARY,
            "refit_train_end": splits["holdout"]["train_end"],
            "n_train": int(len(hold.y_train)),
            "preprocess": "scaled (median impute -> winsorize 1/99 -> "
                          "standardize, fit on train only; coefficients "
                          "are per-1-sd and comparable across features)",
            "seed": SEED,
            "chosen_C": chosen_C,
            "intercept": float(best_est.intercept_[0]),
            "coefficients": {f: round(c, 6) for f, c in coefs},
            "l1": {
                "C": chosen_C["lr_l1"],
                "n_features": len(features),
                "n_zero_coefs": int(len(l1_zeroed)),
                "n_nonzero_coefs": int(len(features) - len(l1_zeroed)),
                "zeroed_features": l1_zeroed,
            },
            "tuning": {
                "protocol": "C chosen by mean primary-task AUC on CV folds "
                            "2026-04 and 2026-05 only; holdout never used",
                "l1_screen_subsample_rows": L1_SCREEN_SUBSAMPLE,
                "l2_screen": l2_table,
                "l1_screen": l1_table,
                **({"elastic_screen": en_table} if en_table else {}),
            },
        }
        out = RESULTS_DIR / "lr_coefficients.json"
        out.write_text(json.dumps(payload, indent=1))
        log(f"wrote {out}")
        log("top coefficients (|coef| desc): " + ", ".join(
            f"{f}={c:+.4f}" for f, c in coefs[:12]))

    # ---- verify + summarize ------------------------------------------------
    log("verifying result files")
    problems = []
    for model in results:
        for task in ("beat_mkt_20d", "up_5d"):
            p = RESULTS_DIR / f"{model}__{task}.json"
            if not p.exists():
                problems.append(f"missing {p}")
                continue
            d = json.loads(p.read_text())
            if d.get("cv_auc_mean") is None or d.get("holdout") is None:
                problems.append(f"{p.name}: null cv_auc_mean or holdout")
                continue
            h = d["holdout"]
            log(f"  OK {p.name:34s} cv_auc={d['cv_auc_mean']:.4f}"
                f"+/-{d['cv_auc_std']:.4f} holdout_auc={h['auc']:.4f} "
                f"holdout_spread={h.get('decile_spread', float('nan')):.4f}")
    if problems:
        for pr in problems:
            log(f"  PROBLEM: {pr}")
        raise SystemExit("verification failed: " + "; ".join(problems))

    if conv_counts:
        log(f"convergence warnings by stage: {conv_counts}")
    else:
        log("no convergence warnings")
    log(f"done in {time.time() - T0:.1f}s")


if __name__ == "__main__":
    main()

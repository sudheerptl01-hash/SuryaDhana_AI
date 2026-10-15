#!/usr/bin/env python3
"""Feature-rebuild A/B: engineered feature set vs the pilot champion, same harness.

Pre-registered decision rule (set before results were seen): a feature
rebuild for the 5-year run is warranted only if a variant beats the clean
control (lgbm_fs_selected_clean, CV AUC 0.5314) by >= +0.005 CV AUC on the
primary task while keeping every fold at AUC >= 0.50. Holdout is reported
by the harness but never used to choose.

Variants (champion LGBM config everywhere; primary task only):
  lgbm_fe_all      every base feature + all 23 engineered
  lgbm_fe_top18    pilot top-10 + top-8 new by build-time quick IC
  lgbm_fe_newaxes  pilot top-10 + the genuinely-new axes (low redundancy)
  lgbm_fe_regime   pilot top-10 + market-state conditioners
  lr_rank_fe       L2 logistic on the pure cross-sectional rank layer
"""
from __future__ import annotations

import os

os.environ.setdefault("OMP_NUM_THREADS", "3")

import json
from pathlib import Path

import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.linear_model import LogisticRegression

import ml.evaluation as ev
from ml.evaluation import DATA_DIR, run_standard_eval

# eval_aggregate treats every JSON in ml/results/ as a pilot league entry, so the
# A/B writes to its own folders. save_results/save_preds read these at call time.
ev.RESULTS_DIR = ev.ML_DIR / "results" / "feature_study"
ev.PREDS_DIR = ev.ML_DIR / "results" / "preds" / "feature_study"

SEED = 108
CONTROL_CLEAN_CV = 0.5314
REBUILD_BAR = CONTROL_CLEAN_CV + 0.005

PILOT_TOP10 = ["atr_pct", "deliv_pct_sma_20", "dist_52w_high", "ret_126d",
               "mom_12_1", "cs_rank_mom_20", "cs_rank_ret_126",
               "cs_rank_vol_20", "deliv_pct", "ret_63d"]
TOP8_NEW = ["cs_rank_deliv_sma", "cs_rank_52wh", "sharpe_mom_126",
            "cs_rank_mom121", "upday_frac_63", "cs_rank_atr",
            "ix_deliv_mom", "accum_20"]
NEW_AXES = ["upday_frac_63", "mom_consistency", "accum_20", "deliv_surge",
            "sessions_since_52w_high", "deliv_z_chg_5"]
REGIME = ["mkt_ret_20", "mkt_breadth_200", "mkt_vol_20", "corr_mkt_60"]
RANK_LAYER = ["cs_rank_deliv_sma", "cs_rank_52wh", "cs_rank_rsi14",
              "cs_rank_ret63", "cs_rank_mom121", "cs_rank_atr",
              "cs_rank_mom_20", "cs_rank_ret_126", "cs_rank_vol_20",
              "cs_rank_turnover", "cs_rank_deliv_z"]


def champion_lgbm(task):
    return LGBMClassifier(num_leaves=63, learning_rate=0.05, n_estimators=300,
                          feature_fraction=0.8, bagging_fraction=0.8,
                          bagging_freq=1, min_data_in_leaf=200,
                          num_threads=3, verbosity=-1, random_state=SEED)


def main() -> None:
    df = pd.read_parquet(DATA_DIR / "model_dataset_fe.parquet")
    df["date"] = pd.to_datetime(df["date"])
    base = json.loads((DATA_DIR / "manifest.json").read_text())["features"]
    new = json.loads((DATA_DIR / "manifest_fe.json").read_text())["new_features"]
    splits = json.loads((DATA_DIR / "splits.json").read_text())
    feats_all = base + new

    runs = [
        ("lgbm_fe_all", champion_lgbm, "raw", feats_all,
         "all base + 23 engineered; model self-selects"),
        ("lgbm_fe_top18", champion_lgbm, "raw", PILOT_TOP10 + TOP8_NEW,
         "pilot top-10 + top-8 new by build-time quick IC (selection caveat noted)"),
        ("lgbm_fe_newaxes", champion_lgbm, "raw", PILOT_TOP10 + NEW_AXES,
         "pilot top-10 + low-redundancy new axes only"),
        ("lgbm_fe_regime", champion_lgbm, "raw", PILOT_TOP10 + REGIME,
         "pilot top-10 + market-state conditioners"),
        ("lr_rank_fe",
         lambda task: LogisticRegression(penalty="l2", C=0.01, solver="lbfgs", max_iter=1000),
         "scaled", RANK_LAYER,
         "L2 logistic on the pure cross-sectional rank layer"),
    ]

    summary = {}
    for name, make, prep, subset, note in runs:
        res = run_standard_eval(
            name, "feature_ab", "lead", make_model=make, tasks=("beat_mkt_20d",),
            preprocess=prep, feature_subset=subset,
            params={"config": "pilot champion LGBM" if "lgbm" in name else "lr_l2 C=0.01"},
            notes=f"feature A/B on model_dataset_fe (clean data): {note}",
            df=df, features=feats_all, splits=splits)
        p = res["beat_mkt_20d"]
        summary[name] = {
            "cv": p["cv_auc_mean"], "cv_std": p["cv_auc_std"],
            "min_fold": min(f["auc"] for f in p["folds"]),
            "holdout": p["holdout"]["auc"],
            "spread": p["holdout"].get("decile_spread"),
            "n_features": p["n_features"],
        }

    best = max(summary, key=lambda k: summary[k]["cv"])
    verdict = {
        "control_clean_cv": CONTROL_CLEAN_CV,
        "rebuild_bar_cv": REBUILD_BAR,
        "variants": summary,
        "best_variant": best,
        "rebuild_warranted": bool(
            summary[best]["cv"] >= REBUILD_BAR and summary[best]["min_fold"] >= 0.50),
        "rule": "pre-registered: CV >= control+0.005 AND every fold >= 0.50",
    }
    out = ev.RESULTS_DIR / "feature_ab_verdict.json"
    out.write_text(json.dumps(verdict, indent=1))
    print(json.dumps(verdict, indent=1))


if __name__ == "__main__":
    main()

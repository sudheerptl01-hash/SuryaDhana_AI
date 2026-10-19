"""Stage 4: walk-forward meta-models.  Usage: python3 s4_wf.py ALL | R1 L7 R3 L3 ...

ALL   -> L.walk_forward on every U bar (label-every-bar model), date_step=2, n_jobs=2.
<set> -> 'setup-gated' meta-model trained ONLY on rows where the setup fires.
         Uses a verbatim copy of L.walk_forward's fold logic (expanding yearly folds 2023-2026,
         embargo h+2, train_start 2021-09-01) with two documented changes required by the small
         setup samples: min train rows 20000 -> 1500 (min test 1000 -> 100) and model capacity
         num_leaves 31->15, min_child_samples 400->100, n_estimators 400->300; date_step=1
         (setup rows are already sparse).  Target in both cases: y = 1{barrier label == +1}.
Features: L.FEATURES minus sec_rel_mom20 (2026 sector-snapshot leak, E_auditor issue #1).
"""
import json
import sys

import numpy as np
import pandas as pd

from common import L, OUT, H, FEATS_META, load_base, save, T

SETMAP = {"R1": "S1_bd20", "R3": "S3_rslag", "L7": "L7_oversold_up", "L3": "L3_pullback",
          "L6": "L6_rslead", "L1": "L1_bo20", "L8b": "L8b_mktlead"}


def wf_small(target, mask, P, F, h, features, test_years=(2023, 2024, 2025, 2026), params=None,
             train_start="2021-09-01", min_train=1500, min_test=100, n_jobs=2):
    import lightgbm as lgb
    from sklearn.metrics import roc_auc_score
    y = np.asarray(target, dtype="float64")
    m = np.asarray(mask, bool) & ~np.isnan(y)
    dates = P["date"].values.astype("datetime64[D]")
    cal = np.unique(dates)
    X = F[features].values.astype(np.float32)
    base = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=100,
                subsample=0.7, subsample_freq=1, colsample_bytree=0.7, reg_lambda=5.0, n_jobs=n_jobs, verbose=-1)
    if params:
        base.update(params)
    score = np.full(len(y), np.nan)
    folds = []
    for Y in test_years:
        ts, te = np.datetime64(f"{Y}-01-01"), np.datetime64(f"{Y + 1}-01-01")
        ti = np.searchsorted(cal, ts)
        cutoff = cal[max(0, ti - h - 2)]
        tr = m & (dates < cutoff) & (dates >= np.datetime64(train_start))
        tm = m & (dates >= ts) & (dates < te)
        if tr.sum() < min_train or tm.sum() < min_test:
            print("skip", Y, int(tr.sum()), int(tm.sum()))
            continue
        mdl = lgb.LGBMClassifier(**base)
        mdl.fit(X[tr], y[tr].astype(int))
        p = mdl.predict_proba(X[tm])[:, 1]
        score[tm] = p
        yb = y[tm].astype(int)
        fm = {"year": Y, "n_train": int(tr.sum()), "n_test": int(tm.sum()), "train_base_rate": float(y[tr].mean())}
        if 0 < yb.mean() < 1:
            fm["auc_up"] = float(roc_auc_score(yb, p))
        fm["base_rate"] = float(yb.mean())
        q = pd.Series(p).rank(pct=True).values  # pooled within test year (setup rows are sparse per date)
        fm["top_decile_rate"] = float(yb[q > 0.9].mean())
        fm["bottom_decile_rate"] = float(yb[q <= 0.1].mean())
        imp = pd.Series(mdl.booster_.feature_importance("gain"), index=features)
        fm["top_features"] = (imp / imp.sum()).sort_values(ascending=False).head(8).round(4).to_dict()
        folds.append(fm)
        print(json.dumps({k: v for k, v in fm.items() if k != "top_features"}), flush=True)
    met = {"folds": folds}
    for k in ("auc_up", "top_decile_rate", "base_rate", "bottom_decile_rate"):
        vals = [f[k] for f in folds if k in f]
        if vals:
            met[f"mean_{k}"] = float(np.mean(vals))
    return score, met


if __name__ == "__main__":
    t = T()
    B = load_base()
    names = list(B["setup_names"])
    P = L.load_panel(["date"])
    F = L.load_features(FEATS_META)
    lab = B["lab_L"].astype("float64")
    y = np.where(np.isnan(lab), np.nan, (lab == 1).astype(float))
    t("loaded")
    for tag in sys.argv[1:]:
        if tag == "ALL":
            mask = B["U"] & ~np.isnan(y)
            score, met = L.walk_forward(y, mask, P, F, H, kind="binary", features=FEATS_META, date_step=2, n_jobs=2)
        else:
            sm = B["setups"][:, names.index(SETMAP[tag])]
            mask = B["U"] & sm & ~np.isnan(y)
            score, met = wf_small(y, mask, P, F, H, FEATS_META)
        met["n_rows_mask"] = int(mask.sum())
        np.savez_compressed(f"{OUT}/wf_{tag}.npz", score=score.astype(np.float32))
        save(f"s4_wf_{tag}", met)
        t(f"done {tag} " + json.dumps({k: v for k, v in met.items() if k != 'folds'}))

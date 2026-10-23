#!/usr/bin/env python3
"""Evaluator aggregation for the SuryaDhana pilot bake-off.

Builds ml/results/model_selection.json (league table, date-block-bootstrap
significance, stability, decile economics, recommendation) from SAVED
artifacts only -- the frozen result JSONs in ml/results/ and the per-row
score dumps in ml/results/preds/. Nothing is retrained.

Statistical method
------------------
Per-date cross-sectional correlation makes row-level resampling invalid
(~1,500 tickers share each date's regime), so significance uses a
DATE-BLOCK BOOTSTRAP: test DATES are resampled with replacement within
each fold (and within the holdout), the fold AUC is recomputed on the
resampled rows, B=1000, seed 108. All models in a cohort are evaluated on
IDENTICAL date draws, so pairwise P(A > B) is paired. Models re-validated
on the cleaned (phantom-holiday-purged) dataset form a second cohort with
their own draws (their test calendars differ from the frozen runs).

Reported per model: pooled-CV AUC (four CV folds' out-of-sample scores
concatenated; each fold keeps its own per-fold-trained model), the
mean-of-fold-AUCs (the league headline, cv_auc_mean), and the holdout AUC
-- each with a 95% percentile CI and P(AUC > 0.5).

Run:  cd /home/user/SuryaDhana_AI && python3 -m ml.eval_aggregate
"""
from __future__ import annotations

import os

os.environ.setdefault("OMP_NUM_THREADS", "2")

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

ML_DIR = Path(__file__).resolve().parent
RESULTS_DIR = ML_DIR / "results"
PREDS_DIR = RESULTS_DIR / "preds"
OUT_JSON = RESULTS_DIR / "model_selection.json"

SEED = 108
B = 1000
TASKS = ["beat_mkt_20d", "up_5d"]
CV_FOLDS = ["2026-04", "2026-05", "2026-06", "2026-07"]
HOLDOUT = "holdout"

# Result JSONs that are not league entries.
AUX_FILES = {"data_profile.json", "feature_selection.json", "holiday_duplicates.json",
             "lr_coefficients.json", "tree_importances.json", "model_selection.json"}

# Selection candidates (one per configuration actually competing). The
# lgbm_fs_top{5,15,20,30} runs are the feature-count ablation around the
# champion (top10 == lgbm_fs_selected) -- league rows, not bootstrap rows.
CANDIDATES = ["lgbm_fs_selected", "random_forest", "lightgbm", "xgboost", "decision_tree",
              "lr_l2", "lr_l1", "lr_elastic", "mlp", "gru", "lstm", "rl_reinforce",
              "baseline_mom"]
CLEAN_MODELS = ["lgbm_fs_selected_clean", "lr_l2_clean", "baseline_mom_clean"]
ABLATIONS = ["lgbm_fs_top5", "lgbm_fs_top10", "lgbm_fs_top15", "lgbm_fs_top20", "lgbm_fs_top30"]

CHAMPION = "lgbm_fs_selected"
# Champion vs the best-CV model of every other family, plus the two
# full-feature GBMs (same algorithm ablation + the holdout leader) and the
# free baseline; lr_l2 vs baseline closes the loop on the linear anchor.
PAIRS_PRIMARY = [(CHAMPION, "lr_l2"), (CHAMPION, "random_forest"), (CHAMPION, "xgboost"),
                 (CHAMPION, "lightgbm"), (CHAMPION, "mlp"), (CHAMPION, "rl_reinforce"),
                 (CHAMPION, "baseline_mom"), ("lr_l2", "baseline_mom")]
PAIRS_PRIMARY_CLEAN = [("lgbm_fs_selected_clean", "lr_l2_clean"),
                       ("lgbm_fs_selected_clean", "baseline_mom_clean"),
                       ("lr_l2_clean", "baseline_mom_clean")]
PAIRS_SECONDARY = [(CHAMPION, "lr_l2"), (CHAMPION, "lightgbm"), (CHAMPION, "baseline_mom")]

FAMILY_FIX = {"baseline_mom": "baseline"}  # ran under quant-linear; it is the 1-feature floor

ECON_SHORTLIST = CANDIDATES + CLEAN_MODELS  # per-date decile economics


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _f(x, nd=6):
    return None if x is None else round(float(x), nd)


def load_league():
    """League entries straight from the frozen result JSONs."""
    league = {t: [] for t in TASKS}
    raw = {}
    for p in sorted(RESULTS_DIR.glob("*.json")):
        if p.name in AUX_FILES:
            continue
        d = json.loads(p.read_text())
        model, task = d["model"], d["task"]
        raw[(model, task)] = d
        folds = d.get("folds", [])
        spreads = [f.get("decile_spread") for f in folds]
        tops = [f.get("top_decile_mean_fwd") for f in folds]
        ho = d.get("holdout") or {}
        league[task].append({
            "model": model,
            "family": FAMILY_FIX.get(model, d.get("family")),
            "n_features": d.get("n_features"),
            "cv_auc_mean": _f(d.get("cv_auc_mean")),
            "cv_auc_std": _f(d.get("cv_auc_std")),  # np.std over the 4 fold AUCs (ddof=0)
            "min_fold_auc": _f(min(f["auc"] for f in folds)) if folds else None,
            "fold_aucs": {f["fold"]: _f(f["auc"]) for f in folds},
            "holdout_auc": _f(ho.get("auc")),
            "holdout_decile_spread": _f(ho.get("decile_spread")),
            "holdout_top_decile_mean_fwd": _f(ho.get("top_decile_mean_fwd")),
            "cv_decile_spreads": {f["fold"]: _f(f.get("decile_spread")) for f in folds},
            "cv_top_decile_mean_fwd": {f["fold"]: _f(f.get("top_decile_mean_fwd")) for f in folds},
            "n_folds_spread_positive": int(sum(1 for s in spreads if s is not None and s > 0)),
            "top_decile_fwd_positive_all_folds": bool(tops and all(t is not None and t > 0 for t in tops)),
            "is_clean_revalidation": model.endswith("_clean"),
            "is_ablation": model in ABLATIONS,
            "train_seconds": d.get("train_seconds"),
        })
    for t in TASKS:
        league[t].sort(key=lambda e: (e["cv_auc_mean"] is None, -(e["cv_auc_mean"] or 0)))
    return league, raw


class WeightedAUC:
    """ROC AUC with per-row weights, presorted once so each bootstrap
    replicate is O(n). Ties get the standard mid-rank 0.5 credit."""

    def __init__(self, score, y):
        score = np.asarray(score, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        self.order = np.argsort(score, kind="mergesort")
        s = score[self.order]
        self.y_sorted = y[self.order]
        self.starts = np.flatnonzero(np.r_[True, s[1:] != s[:-1]])

    def auc(self, w):
        ws = np.asarray(w, dtype=np.float64)[self.order]
        pw = ws * self.y_sorted
        nw = ws - pw
        pg = np.add.reduceat(pw, self.starts)
        ng = np.add.reduceat(nw, self.starts)
        cn = np.cumsum(ng)
        wp, wn = pg.sum(), cn[-1]
        if wp == 0 or wn == 0:
            return np.nan
        return float((pg * (cn - ng + 0.5 * ng)).sum() / (wp * wn))


def load_preds(model, task):
    p = PREDS_DIR / f"{model}__{task}.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[ns]")
    return df


def fold_dates(df, fold):
    """Sorted unique test dates of a fold as a plain datetime64[ns] ndarray."""
    return np.unique(df.loc[df["fold"] == fold, "date"].to_numpy(dtype="datetime64[ns]"))


def cohort_draws(canonical_dates, rng):
    """One (B, n_dates) index-draw matrix per fold + its bincounts.
    Shared by every model in the cohort => paired comparisons."""
    draws = {}
    for fold, dates in canonical_dates.items():
        nd = len(dates)
        idx = rng.integers(0, nd, size=(B, nd))
        counts = np.zeros((B, nd), dtype=np.float64)
        for b in range(B):
            counts[b] = np.bincount(idx[b], minlength=nd)
        draws[fold] = counts
    return draws


def bootstrap_model(df, canonical_dates, counts):
    """Bootstrap AUC draws for one model: per-fold, cv-mean, pooled-CV, holdout."""
    engines, date_codes = {}, {}
    for fold, dates in canonical_dates.items():
        g = df[df["fold"] == fold]
        gd = g["date"].to_numpy(dtype="datetime64[ns]")
        assert np.isin(gd, dates).all(), f"unexpected dates in fold {fold}"
        engines[fold] = WeightedAUC(g["score"].to_numpy(), g["y"].to_numpy())
        date_codes[fold] = np.searchsorted(dates, gd)
    cv_rows = pd.concat([df[df["fold"] == f] for f in CV_FOLDS], ignore_index=True)
    pooled_engine = WeightedAUC(cv_rows["score"].to_numpy(), cv_rows["y"].to_numpy())

    fold_draws = {f: np.empty(B) for f in canonical_dates}
    pooled_draws = np.empty(B)
    for b in range(B):
        w_parts = []
        for f in CV_FOLDS:
            w = counts[f][b][date_codes[f]]
            fold_draws[f][b] = engines[f].auc(w)
            w_parts.append(w)
        pooled_draws[b] = pooled_engine.auc(np.concatenate(w_parts))
        fold_draws[HOLDOUT][b] = engines[HOLDOUT].auc(counts[HOLDOUT][b][date_codes[HOLDOUT]])
    cv_mean_draws = np.mean(np.column_stack([fold_draws[f] for f in CV_FOLDS]), axis=1)

    # point estimates recomputed from the saved preds (unweighted)
    ones = {f: np.ones(len(date_codes[f])) for f in canonical_dates}
    point = {
        "fold_auc": {f: engines[f].auc(ones[f]) for f in canonical_dates},
        "pooled_cv_auc": pooled_engine.auc(np.ones(len(cv_rows))),
    }
    point["cv_auc_mean"] = float(np.mean([point["fold_auc"][f] for f in CV_FOLDS]))
    point["holdout_auc"] = point["fold_auc"][HOLDOUT]
    return {"cv_mean": cv_mean_draws, "pooled_cv": pooled_draws,
            "holdout": fold_draws[HOLDOUT], "point": point}


def ci(draws):
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return [_f(lo, 4), _f(hi, 4)]


def summarize_boot(res):
    p = res["point"]
    return {
        "pooled_cv_auc": _f(p["pooled_cv_auc"], 4), "pooled_cv_auc_ci95": ci(res["pooled_cv"]),
        "cv_auc_mean": _f(p["cv_auc_mean"], 4), "cv_auc_mean_ci95": ci(res["cv_mean"]),
        "holdout_auc": _f(p["holdout_auc"], 4), "holdout_auc_ci95": ci(res["holdout"]),
        "p_pooled_cv_gt_chance": _f((res["pooled_cv"] > 0.5).mean(), 3),
        "p_cv_mean_gt_chance": _f((res["cv_mean"] > 0.5).mean(), 3),
        "p_holdout_gt_chance": _f((res["holdout"] > 0.5).mean(), 3),
    }


def pair_stats(ra, rb):
    out = {}
    for key, label in [("cv_mean", "cv_mean"), ("pooled_cv", "pooled_cv"), ("holdout", "holdout")]:
        d = ra[key] - rb[key]
        out[f"delta_{label}"] = _f(ra["point"]["cv_auc_mean" if key == "cv_mean" else
                                   ("pooled_cv_auc" if key == "pooled_cv" else "holdout_auc")] -
                                   rb["point"]["cv_auc_mean" if key == "cv_mean" else
                                   ("pooled_cv_auc" if key == "pooled_cv" else "holdout_auc")], 4)
        out[f"delta_{label}_ci95"] = ci(d)
        out[f"p_a_gt_b_{label}"] = _f((d > 0).mean(), 3)
    return out


def harness_decile(score, fwd):
    """Replicates ml/evaluation.compute_metrics' fold-level decile economics."""
    ok = ~np.isnan(fwd)
    s = pd.Series(score[ok])
    f = pd.Series(fwd[ok].astype(np.float64))
    dec = pd.qcut(s.rank(method="first"), 10, labels=False)
    by = f.groupby(dec).mean()
    return float(by.iloc[-1] - by.iloc[0]), float(by.iloc[-1])


def per_date_spread(g):
    """Mean over test dates of the within-date top-minus-bottom decile fwd."""
    vals = []
    for _, day in g.groupby("date"):
        if len(day) < 50 or day["fwd"].isna().all():
            continue
        dec = pd.qcut(day["score"].rank(method="first"), 10, labels=False)
        by = day["fwd"].astype("float64").groupby(dec).mean()
        vals.append(by.iloc[-1] - by.iloc[0])
    return float(np.mean(vals)), float(np.mean([v > 0 for v in vals]))


def decile_econ(df):
    out = {}
    for fold in CV_FOLDS + [HOLDOUT]:
        g = df[df["fold"] == fold]
        spread, top = harness_decile(g["score"].to_numpy(), g["fwd"].to_numpy())
        pd_spread, pd_sign = per_date_spread(g)
        out[fold] = {"decile_spread": _f(spread), "top_decile_mean_fwd": _f(top),
                     "per_date_spread_mean": _f(pd_spread),
                     "pct_dates_spread_positive": _f(pd_sign, 3)}
    cv = [out[f] for f in CV_FOLDS]
    out["summary"] = {
        "spread_positive_folds": f"{sum(1 for c in cv if c['decile_spread'] > 0)}/4",
        "top_decile_fwd_positive_all_cv_folds": bool(all(c["top_decile_mean_fwd"] > 0 for c in cv)),
        "top_decile_fwd_positive_all_windows": bool(all(out[f]["top_decile_mean_fwd"] > 0
                                                        for f in CV_FOLDS + [HOLDOUT])),
    }
    return out


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main():
    t0 = time.time()
    league, raw = load_league()
    holidays = json.loads((RESULTS_DIR / "holiday_duplicates.json").read_text())

    # ---- cohorts and canonical date lists --------------------------------
    preds, cohort_of = {}, {}
    for task in TASKS:
        for m in CANDIDATES + CLEAN_MODELS:
            df = load_preds(m, task)
            if df is not None:
                preds[(m, task)] = df
                cohort_of[(m, task)] = "clean" if m.endswith("_clean") else "frozen"

    boot, significance = {}, {t: {} for t in TASKS}
    for task in TASKS:
        for cohort in ["frozen", "clean"]:
            members = [m for m in CANDIDATES + CLEAN_MODELS
                       if (m, task) in preds and cohort_of[(m, task)] == cohort]
            if not members:
                continue
            ref = preds[(members[0], task)]
            canon = {f: fold_dates(ref, f) for f in CV_FOLDS + [HOLDOUT]}
            for m in members:  # all cohort members must share the test calendar
                d = preds[(m, task)]
                for f in CV_FOLDS + [HOLDOUT]:
                    assert np.array_equal(fold_dates(d, f), canon[f]), \
                        f"{m}/{task}/{f}: date set differs from cohort"
            rng = np.random.default_rng(np.random.SeedSequence(
                [SEED, TASKS.index(task), 0 if cohort == "frozen" else 1]))
            counts = cohort_draws(canon, rng)
            for m in members:
                res = bootstrap_model(preds[(m, task)], canon, counts)
                boot[(m, task)] = res
                # sanity: recomputed point AUCs vs the frozen JSONs
                # (float32 score storage allows ~1e-4 rank-tie slack)
                jm = raw[(m, task)]
                for fr in jm["folds"]:
                    assert abs(res["point"]["fold_auc"][fr["fold"]] - fr["auc"]) < 5e-4, \
                        f"{m}/{task}/{fr['fold']}: preds do not reproduce frozen AUC"
                assert abs(res["point"]["holdout_auc"] - jm["holdout"]["auc"]) < 5e-4
                print(f"  boot {task:12s} {m:26s} done ({time.time()-t0:5.1f}s)")

        significance[task]["per_model"] = {
            m: summarize_boot(boot[(m, task)])
            for m in CANDIDATES + CLEAN_MODELS if (m, task) in boot}

    pair_lists = {"beat_mkt_20d": PAIRS_PRIMARY + PAIRS_PRIMARY_CLEAN, "up_5d": PAIRS_SECONDARY}
    for task in TASKS:
        rows = []
        for a, b in pair_lists[task]:
            if (a, task) in boot and (b, task) in boot:
                rows.append({"a": a, "b": b, **pair_stats(boot[(a, task)], boot[(b, task)])})
        significance[task]["pairwise"] = rows

    # ---- stability -------------------------------------------------------
    stability = {}
    for task in TASKS:
        stability[task] = {}
        for e in league[task]:
            m = e["model"]
            folds = list(e["fold_aucs"].values())
            all_windows = folds + ([e["holdout_auc"]] if e["holdout_auc"] is not None else [])
            worst = min(e["fold_aucs"], key=e["fold_aucs"].get)
            stability[task][m] = {
                "cv_auc_std": e["cv_auc_std"],
                "min_fold_auc": e["min_fold_auc"],
                "worst_fold": worst,
                "n_cv_folds_below_050": int(sum(1 for a in folds if a < 0.5)),
                "n_windows_below_050_incl_holdout": int(sum(1 for a in all_windows if a < 0.5)),
                "never_below_050_any_window": bool(all(a >= 0.5 for a in all_windows)),
                "holdout_minus_cv_mean": _f((e["holdout_auc"] or np.nan) - (e["cv_auc_mean"] or np.nan), 4),
                "decile_spread_positive_folds": e["n_folds_spread_positive"],
                "top_decile_fwd_positive_all_folds": e["top_decile_fwd_positive_all_folds"],
            }

    # ---- CV vs holdout tension ------------------------------------------
    prim = [e for e in league["beat_mkt_20d"]
            if e["model"] in CANDIDATES and not e["is_ablation"]]
    cvs = pd.Series({e["model"]: e["cv_auc_mean"] for e in prim})
    hos = pd.Series({e["model"]: e["holdout_auc"] for e in prim})
    spearman = float(cvs.rank().corr(hos.rank()))
    tension = {
        "spearman_rank_corr_cv_vs_holdout_primary": _f(spearman, 3),
        "mean_holdout_minus_cv_primary": _f(float((hos - cvs).mean()), 4),
        "models_holdout_above_cv": f"{int((hos > cvs).sum())}/{len(prim)}",
        "note": ("Every candidate but the champion scored higher on the single Aug-1->mid-Sep "
                 "holdout than on 4-fold CV, and holdout vs CV rank models in near-opposite "
                 "order among trees (RF best CV 0.5167; XGB/LGBM best holdout ~0.56). The "
                 "holdout is ONE friendly 6-week window used once; the 4 CV folds span 4 "
                 "months including the adversarial 2026-04. Adjudication: algorithm choice is "
                 "decided on CV mean + fold minimum (regime robustness); the holdout serves "
                 "only as a no-catastrophe check. lgbm_fs_selected is the only candidate whose "
                 "holdout ~= CV (-0.009), i.e. least window-dependent."),
    }

    # ---- decile economics ------------------------------------------------
    econ = {t: {} for t in TASKS}
    for task in TASKS:
        for m in ECON_SHORTLIST:
            if (m, task) in preds:
                econ[task][m] = decile_econ(preds[(m, task)])

    # ---- up_5d caveat (April fold inflation) ------------------------------
    up = [e for e in league["up_5d"] if e["model"] in CANDIDATES]
    n_apr_best = sum(1 for e in up if max(e["fold_aucs"], key=e["fold_aucs"].get) == "2026-04")
    ex_apr = {e["model"]: _f(np.mean([v for k, v in e["fold_aucs"].items() if k != "2026-04"]), 4)
              for e in up}
    secondary_caveat = {
        "monthly_base_rate_range": "0.37-0.72 (regime-exposed by construction)",
        "n_models_with_best_fold_2026_04": f"{n_apr_best}/{len(up)}",
        "cv_mean_excluding_2026_04": ex_apr,
        "label_defect": ("label_up_5d hard-codes 0 where fwd_ret_5d is NaN (~1.6% of rows; "
                         "fixed in the cleaned rebuild)"),
        "verdict": ("up_5d CV means are inflated by the one-sided 2026-04 fold (base rate "
                    "0.72) across all families; used as a sanity check only, never for "
                    "selection."),
    }

    # ---- significance verdicts (auto-quantified) --------------------------
    sp = significance["beat_mkt_20d"]["per_model"]
    pw = {(r["a"], r["b"]): r for r in significance["beat_mkt_20d"]["pairwise"]}
    ch = sp[CHAMPION]
    v_lr = pw[(CHAMPION, "lr_l2")]
    v_bl = pw[(CHAMPION, "baseline_mom")]
    v_xgb = pw[(CHAMPION, "xgboost")]
    above = sorted(m for m, s in sp.items() if s["p_pooled_cv_gt_chance"] >= 0.975)
    below = sorted(m for m, s in sp.items() if s["p_pooled_cv_gt_chance"] <= 0.025)
    mid = sorted(m for m, s in sp.items() if 0.025 < s["p_pooled_cv_gt_chance"] < 0.975)
    lr_sig = v_lr["delta_cv_mean_ci95"][0] > 0
    verdicts = [
        f"Chance (pooled CV, date-block bootstrap): clearly above 0.5 only for "
        f"{', '.join(above)}; significantly BELOW 0.5 for {', '.join(below)} (1-feature "
        f"momentum ranked mildly contrarian in this sample); everything else "
        f"({', '.join(mid)}) is NOT distinguishable from coin-flipping on CV. On the holdout "
        f"every model clears 0.5 with P=1.000 -- the friendly-window effect, which is exactly "
        f"why the holdout alone is not trusted.",
        f"Champion vs chance: {CHAMPION} pooled-CV AUC {ch['pooled_cv_auc']} (95% CI "
        f"{ch['pooled_cv_auc_ci95']}, P(>0.5)={ch['p_pooled_cv_gt_chance']}); holdout "
        f"{ch['holdout_auc']} (CI {ch['holdout_auc_ci95']}). A real but thin edge of ~2-3 "
        f"AUC points.",
        f"Champion vs lr_l2: paired CV-mean delta {v_lr['delta_cv_mean']:+.4f} (95% CI "
        f"{v_lr['delta_cv_mean_ci95']}, P={v_lr['p_a_gt_b_cv_mean']}) -- "
        f"{'significant under date-block resampling' if lr_sig else 'NOT significant'} -- but "
        f"a dead heat on the holdout (delta {v_lr['delta_holdout']:+.4f}, "
        f"P={v_lr['p_a_gt_b_holdout']}). CAVEAT: with only 4 CV regime-months the date-block "
        f"bootstrap conditions on those months and cannot capture fold/regime-level "
        f"uncertainty, which this sample shows is the dominant risk. The CV gap is treated as "
        f"suggestive, not settled; the recommendation therefore also rests on stability, "
        f"cost, interpretability and scale-up headroom.",
        f"Champion vs the free floor: paired CV-mean delta {v_bl['delta_cv_mean']:+.4f} (CI "
        f"{v_bl['delta_cv_mean_ci95']}, P={v_bl['p_a_gt_b_cv_mean']}) -- the champion does "
        f"beat the 1-feature momentum baseline on CV; on the holdout even that gap closes "
        f"(delta {v_bl['delta_holdout']:+.4f}, P={v_bl['p_a_gt_b_holdout']}).",
        f"CV-vs-holdout contradiction (the heart of the adjudication): on CV mean the "
        f"champion beats xgboost by {v_xgb['delta_cv_mean']:+.4f} (CI "
        f"{v_xgb['delta_cv_mean_ci95']}); on the single holdout xgboost leads by "
        f"{-v_xgb['delta_holdout']:.4f} (P(xgb better)={1 - v_xgb['p_a_gt_b_holdout']:.3f}). "
        f"Both directions are 'significant' under date resampling -- so the disagreement is "
        f"regime-window dependence, not sampling noise. Four monthly windows outvote one "
        f"6-week window; the 5-year run adjudicates for good.",
        "Scale of resolvable differences: individual 95% CIs are roughly +/-0.009-0.012 "
        "wide, so unpaired differences of ~0.01-0.02 (the entire mid-table: lr anchors, "
        "decision_tree, rl, mlp, lstm, full-feature GBMs on CV) are inside the noise, and "
        "paired sub-0.01 differences (champion vs lr_l2 on holdout; l1/l2/elastic among "
        "themselves) are too. The mid-table ordering should not be oversold.",
    ]

    # ---- recommendation ---------------------------------------------------
    st = stability["beat_mkt_20d"]
    e_ch = econ["beat_mkt_20d"][CHAMPION]
    recommendation = {
        "decision": "Carry LightGBM on the selected 10-feature subset to the 5-year run; "
                    "keep L2 logistic regression as the interpretable benchmark/sanity layer.",
        "carry_to_5y": [
            {"algorithm": "LightGBM classifier on the 10-feature selected subset "
                          "(long momentum + delivery block + atr_pct + dist_52w_high + "
                          "inverted cs_rank_mom_20)",
             "model_id": CHAMPION,
             "evidence": [
                 f"Best primary CV among candidates: {sp[CHAMPION]['cv_auc_mean']} "
                 f"(CI {sp[CHAMPION]['cv_auc_mean_ci95']}); re-validated on cleaned data at "
                 f"0.5314 with fold std tightening 0.018->0.014.",
                 f"Only candidate never below 0.50 in any of the 5 OOS windows "
                 f"(min fold {st[CHAMPION]['min_fold_auc']}; clean rerun min "
                 f"{st['lgbm_fs_selected_clean']['min_fold_auc']}); every other model dips "
                 f"below chance in at least one window.",
                 f"Smallest CV<->holdout gap ({st[CHAMPION]['holdout_minus_cv_mean']:+.4f} vs "
                 f"+0.01..+0.06 for the rest): least regime-window sensitivity -- the property "
                 f"that matters for scale-up.",
                 f"Top-decile mean 20d excess positive in all 5 windows "
                 f"({', '.join(f'{e_ch[f]['top_decile_mean_fwd']*100:+.2f}%' for f in CV_FOLDS + [HOLDOUT])}).",
                 "Native missing-value handling for the structurally-NaN long-lookback "
                 "features early in the 5y history (ret_252d/mom_12_1 are 58% NaN here); "
                 "~32s per full protocol run -- cheap at 5y scale.",
             ]},
            {"algorithm": "L2 logistic regression (C=0.01, all features, harness scaling)",
             "model_id": "lr_l2",
             "role": "interpretable benchmark + sanity layer, not a production scorer",
             "evidence": [
                 f"Cheapest credible anchor: a dead heat with the champion on the holdout "
                 f"(delta {v_lr['delta_holdout']:+.4f}, P={v_lr['p_a_gt_b_holdout']}); the "
                 f"champion's paired CV edge over it ({v_lr['delta_cv_mean']:+.4f}) is real "
                 f"under date resampling but conditions on only 4 regime-months. Per-1-sd "
                 f"coefficients give a drift monitor the GBM cannot.",
                 "Improved on cleaned data (0.513->0.517) and tracks the champion on holdout "
                 "AUC (0.523), but its holdout decile spread is negative (-0.023: extremes "
                 "invert economically) and it sat below 0.50 in 2 of 4 folds -- benchmark only.",
             ]},
        ],
        "drop": [
            {"model": "rl_reinforce (RL)",
             "why": "Does not earn its complexity: CV 0.5085, REINFORCE failed to beat its own "
                    "init on 2/4 folds, and its own portfolio sim loses to the free mom20 "
                    "heuristic out-of-sample (net +1.76% vs +2.71%/20d CV-agg; +4.67% vs "
                    "+5.15% holdout)."},
            {"model": "gru / lstm (RNNs)",
             "why": "At or below chance on CV (0.489 / 0.502): a 20-session temporal view adds "
                    "nothing at this scale, and the MLP (0.5025, ~3 AUC pts under LGBM) shows "
                    "the deep stack itself isn't paying either."},
            {"model": "decision_tree",
             "why": "Strictly dominated by the boosted/bagged trees it underlies."},
            {"model": "lr_l1 / lr_elastic",
             "why": "Numerically identical to lr_l2 to ~3 decimals; keep one linear anchor."},
        ],
        "revisit_at_5y_if": [
            "Full-feature XGBoost/LightGBM (holdout 0.5646/0.5627, spreads +3.5/+2.9pts, but "
            "bottom-tier CV ~0.502-0.504) beat the 10-feature subset on the multi-year "
            "walk-forward MEAN, not a single window -- then prefer the full-feature GBM.",
            "The re-run feature selection at 5y (long-lookback features fully populated) "
            "changes the subset materially -- re-fit and re-adjudicate.",
            "The champion's mildly negative clean-holdout decile spread (-0.004) persists "
            "across multiple years -- then the ranking edge is not monetizable as a long-short.",
        ],
        "purpose_note": "The pilot's question was WHICH ALGORITHM, not whether the edge is "
                        "tradable: gradient-boosted trees on a compact selected subset is the "
                        "decisive answer. The SIZE of the edge (pooled-CV AUC ~0.53, and a "
                        "gap to the linear anchor that vanished on the holdout window) is a "
                        "5-year question.",
    }

    retest_at_5y = [
        "Feature selection: re-run the full ranking/elimination at 5y -- ret_252d, mom_12_1, "
        "dist_200dma are 58/58/21% NaN in the pilot and 'switch on' through 2026; the top-10 "
        "subset may change.",
        "Full-feature GBM vs 10-feature subset: the single friendly holdout favored "
        "full-feature XGB/LGBM; adjudicate on ~60 monthly folds where 0.01-0.02 AUC deltas "
        "become resolvable.",
        "Significance: re-run the date-block bootstrap (B=1000, seed 108) -- with thousands of "
        "test dates the champion-vs-linear gap will be in or out of the noise definitively.",
        "Regime coverage: the pilot had one adversarial month (2026-04); verify the >=0.50 "
        "fold floor and decile-spread sign consistency across full bull/bear cycles.",
        "Economics: decile spreads net of costs/turnover on y_excess_20d; confirm top-decile "
        "excess positivity by regime, not just by fold.",
        "Secondary task: re-evaluate up_5d with the NaN-label fix and per-regime base-rate "
        "stratification before trusting any up_5d number.",
        "Data hygiene: extend the holiday-echo duplicate scan and corporate-action handling "
        "to the full 5y ingest (unadjusted prices: y_clean_20d masking must be re-audited).",
        "Optional: one MLP re-check at 5y data volume before finalizing the no-deep verdict.",
    ]

    data_quality_event = {
        "what": "12 phantom holiday-echo days (2.9% of ingested sessions): the archive mirror "
                "served the previous session's bhavcopy on 2026 NSE holidays instead of 404ing; "
                "every ticker duplicated the prior session's OHLC+volume.",
        "fix": "Ingest patched (2026 holiday calendar + duplicate-day guard), phantom days "
               "purged, dataset rebuilt; label_up_5d NaN-encoding fixed in the same rebuild.",
        "revalidation": "Champion and anchors re-run on cleaned data: lgbm_fs_selected CV "
                        "0.5307->0.5314 (std 0.018->0.014), lr_l2 0.513->0.517, baseline_mom "
                        "0.493->0.491 -- ranking robust. League numbers remain the FROZEN "
                        "pre-fix runs; the *_clean rows are the robustness check (their test "
                        "calendars differ, so they are bootstrapped as a separate cohort).",
        "phantom_days": holidays["phantom_days"],
    }

    out = {
        "generated_at": pd.Timestamp.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "generated_by": f"ml/eval_aggregate.py (seed {SEED}, B={B} date-block bootstrap)",
        "protocol": {
            "primary_task": "beat_mkt_20d (balanced ~0.500 by construction, regime-robust)",
            "secondary_task": "up_5d (regime-exposed; see secondary_task_caveat)",
            "cv_folds": CV_FOLDS, "holdout": "2026-08-03 -> 2026-09-11/15 (frozen), used once",
            "n_cv_test_dates": 88, "n_holdout_test_dates": 32,
            "bootstrap": "test dates resampled with replacement within each fold/holdout; "
                         "identical draws across cohort models (paired); B=1000, seed 108",
        },
        "league": league,
        "cv_holdout_tension": tension,
        "significance": {"method": "date-block bootstrap on saved preds", **significance,
                         "verdicts": verdicts},
        "stability": stability,
        "decile_economics": econ,
        "secondary_task_caveat": secondary_caveat,
        "data_quality_event": data_quality_event,
        "recommendation": recommendation,
        "retest_at_5y": retest_at_5y,
        "runtime_seconds": round(time.time() - t0, 1),
    }
    OUT_JSON.write_text(json.dumps(out, indent=1))
    print(f"\nwrote {OUT_JSON} ({OUT_JSON.stat().st_size/1024:.0f} KB) "
          f"in {time.time()-t0:.1f}s")

    # ---- memo numbers ------------------------------------------------------
    print("\n=== PRIMARY LEAGUE (beat_mkt_20d) ===")
    hdr = f"{'model':26s} {'fam':9s} {'nf':>3s} {'cv_mean':>8s} {'std':>6s} {'minfold':>8s} {'holdout':>8s} {'ho_sprd':>8s}"
    print(hdr)
    for e in league["beat_mkt_20d"]:
        print(f"{e['model']:26s} {str(e['family'])[:9]:9s} {e['n_features']:3d} "
              f"{e['cv_auc_mean']:.4f}   {e['cv_auc_std']:.4f} {e['min_fold_auc']:8.4f} "
              f"{e['holdout_auc']:8.4f} {e['holdout_decile_spread']:+8.4f}"
              + ("  [clean]" if e["is_clean_revalidation"] else "")
              + ("  [ablation]" if e["is_ablation"] else ""))
    print("\n=== SIGNIFICANCE (primary) ===")
    for m, s in significance["beat_mkt_20d"]["per_model"].items():
        print(f"{m:26s} pooledCV {s['pooled_cv_auc']:.4f} CI{s['pooled_cv_auc_ci95']} "
              f"P>.5={s['p_pooled_cv_gt_chance']:.3f} | cv_mean CI{s['cv_auc_mean_ci95']} | "
              f"holdout {s['holdout_auc']:.4f} CI{s['holdout_auc_ci95']} "
              f"P>.5={s['p_holdout_gt_chance']:.3f}")
    print("\n=== PAIRWISE (primary) ===")
    for r in significance["beat_mkt_20d"]["pairwise"]:
        print(f"{r['a']} vs {r['b']}: d_cv_mean {r['delta_cv_mean']:+.4f} "
              f"CI{r['delta_cv_mean_ci95']} P={r['p_a_gt_b_cv_mean']:.3f} | "
              f"d_pooled {r['delta_pooled_cv']:+.4f} P={r['p_a_gt_b_pooled_cv']:.3f} | "
              f"d_holdout {r['delta_holdout']:+.4f} P={r['p_a_gt_b_holdout']:.3f}")
    print("\n=== TENSION ===", json.dumps(tension, indent=1)[:600])
    print("\n=== VERDICTS ===")
    for v in verdicts:
        print("-", v)
    print("\n=== CHAMPION ECON (primary) ===")
    for f in CV_FOLDS + [HOLDOUT]:
        e = econ["beat_mkt_20d"][CHAMPION][f]
        print(f"{f}: spread {e['decile_spread']:+.4f} top {e['top_decile_mean_fwd']:+.4f} "
              f"per-date {e['per_date_spread_mean']:+.4f} "
              f"({e['pct_dates_spread_positive']:.0%} dates +)")
    print("\n=== UP_5D CAVEAT ===", json.dumps(secondary_caveat["cv_mean_excluding_2026_04"]))
    return out


if __name__ == "__main__":
    main()

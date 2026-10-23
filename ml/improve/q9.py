#!/usr/bin/env python3
"""Phase-2 amendment A1 (ml/IMPROVEMENT_PLAN_2.md section 4): the control with an expanding training window.

Reads ml/results/improve/ab/10y_p2/compare.json (primary AUC mark, pair 'q9_expanding - control') and
ml/results/improve/ab/10y_p2/books.json (books of both configurations, same base, same benchmark), and applies the
Q3 book mark to the control's construction: the liquid-tercile neutral top decile's IR >= 0.5 with its month-block CI
excluding zero, and its paired monthly excess over the control's liquid neutral book with a bootstrap CI excluding
zero (iid months binding; 3-month blocks reported).  Bootstrap and readings reuse ml/improve/liquid.py.

    python3 -m ml.improve.q9
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ml.improve import liquid as L

ML = Path(__file__).resolve().parents[1]
TAG = ML / "results" / "improve" / "ab" / "10y_p2"
OUT = ML / "results" / "improve2" / "expanding"
N = 264
VAR_SR = 0.00387


def main() -> None:
    cmp_ = json.loads((TAG / "compare.json").read_text())
    books = json.loads((TAG / "books.json").read_text())["books"]
    pair = cmp_["pairs"]["q9_expanding - control"]
    res = {"plan": "ml/IMPROVEMENT_PLAN_2.md section 4, amendment A1", "n_trials": N,
           "primary": {k: pair[k] for k in ("delta_cv_mean", "ci95", "folds_won", "rank_ic_delta_mean",
                                            "rank_ic_delta_nw_t", "holdout_auc_delta", "pass_primary")},
           "models": {n: {k: cmp_["models"][n][k] for k in ("cv_auc_mean", "cv_mean_ci95", "pct_folds_ge_050",
                                                            "min_fold_auc", "holdout_auc", "rank_ic_cv_mean",
                                                            "rank_ic_nw_t")} for n in ("control", "q9_expanding")},
           "books": {}}
    for k in ("none|top_decile", "vol+size|top_decile", "none|liq_top_decile", "vol+size|liq_top_decile"):
        for n in ("control", "q9_expanding"):
            res["books"][f"{n}|{k}"] = L.book_reading(books[f"{n}|{k}"], N, VAR_SR)
    for k in ("vol+size|liq_top_decile", "vol+size|top_decile"):
        p = L.paired(books[f"q9_expanding|{k}"], books[f"control|{k}"], None, allow_partial=False)
        p.pop("_d")
        res[f"paired_{k}"] = p
    liq = res["books"]["q9_expanding|vol+size|liq_top_decile"]
    pl = res["paired_vol+size|liq_top_decile"]
    part1 = bool(liq["ir_20bps"] >= 0.5 and liq["ir_ci95"][0] > 0)
    part2 = bool(pl["iid_months"]["ci_above_0"])
    res["book_mark"] = {"part1_ir_ge_0.5_ci_above_0": part1, "part2_paired_iid_ci_above_0": part2,
                        "part2_block3_ci_above_0": bool(pl["block_3_months"]["ci_above_0"]),
                        "PASS": bool(part1 and part2)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "expanding.json").write_text(json.dumps(res, indent=1, default=float))
    b = res["books"]
    def row(key, lab):
        x = b[key]
        return (f"| {lab} | {100 * x['excess_ann_vs_ew_20bps']:+.1f}% | {x['ir_20bps']:+.2f} [{x['ir_ci95'][0]:+.2f}, "
                f"{x['ir_ci95'][1]:+.2f}] | {x['months_positive']}/{x['n_months']} | {100 * x['turnover_per_rebalance']:.0f}% | "
                f"{100 * x['excess_ann_vs_ew_name_level']:+.1f}% | {x[f'dsr_{N}']['dsr']:.3f} |")
    m = res["models"]
    md = ["# Q9 (amendment A1): the control with an expanding training window", "",
          "Plan: `ml/IMPROVEMENT_PLAN_2.md` section 4, A1 (motivated by the CPCV reading; a pass is evidence for a forward "
          "test, not a promotion). Every number is quoted from `expanding.json`.", "",
          "| Model, 103 folds | CV AUC | 95% CI | Months >= 0.50 | Worst | Holdout | Rank IC (NW t) |", "|---|---:|---|---:|---:|---:|---|"]
    for n, lab in (("control", "rolling 504 sessions (control)"), ("q9_expanding", "expanding window")):
        x = m[n]
        md.append(f"| {lab} | {x['cv_auc_mean']:.4f} | [{x['cv_mean_ci95'][0]:.4f}, {x['cv_mean_ci95'][1]:.4f}] | "
                  f"{100 * x['pct_folds_ge_050']:.0f}% | {x['min_fold_auc']:.3f} | {x['holdout_auc']:.4f} | "
                  f"{x['rank_ic_cv_mean']:+.4f} ({x['rank_ic_nw_t']:.1f}) |")
    pr = res["primary"]
    md += ["", f"Primary mark: Δ CV-mean AUC {pr['delta_cv_mean']:+.4f} [{pr['ci95'][0]:+.4f}, {pr['ci95'][1]:+.4f}], "
           f"folds won {pr['folds_won']}, Δ rank IC {pr['rank_ic_delta_mean']:+.4f} (NW t {pr['rank_ic_delta_nw_t']:.1f}): "
           f"**{'PASS' if pr['pass_primary'] else 'FAIL'}**.", "",
           "| Book (net 20 bps vs EW) | Excess/yr | IR [95% CI] | Months ahead | Turnover | Name-level excess | DSR (N = 264) |",
           "|---|---:|---|---:|---:|---:|---:|",
           row("control|vol+size|top_decile", "control, neutral top decile"),
           row("q9_expanding|vol+size|top_decile", "expanding, neutral top decile"),
           row("control|vol+size|liq_top_decile", "control, neutral liquid top decile"),
           row("q9_expanding|vol+size|liq_top_decile", "expanding, neutral liquid top decile"),
           row("control|none|liq_top_decile", "control, plain liquid top decile"),
           row("q9_expanding|none|liq_top_decile", "expanding, plain liquid top decile"), ""]
    for k in ("vol+size|liq_top_decile", "vol+size|top_decile"):
        p = res[f"paired_{k}"]
        md.append(f"Paired monthly excess, expanding minus control, {k}: {100 * p['mean_annualised_x12_6']:+.2f} pp/yr; "
                  f"iid-month CI [{100 * p['iid_months']['ci95'][0] * 12.6:+.2f}, {100 * p['iid_months']['ci95'][1] * 12.6:+.2f}] pp/yr; "
                  f"3-month-block CI [{100 * p['block_3_months']['ci95'][0] * 12.6:+.2f}, {100 * p['block_3_months']['ci95'][1] * 12.6:+.2f}] pp/yr; "
                  f"expanding ahead in {p['months_set_beats_control']}/{p['n_months']} months.")
    bm = res["book_mark"]
    md += ["", f"Book mark (Q3 rule on the liquid neutral book): IR >= 0.5 with CI above 0: {bm['part1_ir_ge_0.5_ci_above_0']}; "
           f"paired iid CI above 0: {bm['part2_paired_iid_ci_above_0']} (3-month blocks: {bm['part2_block3_ci_above_0']}). "
           f"**{'PASS' if bm['PASS'] else 'FAIL'}**."]
    (OUT / "EXPANDING.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()

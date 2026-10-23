#!/usr/bin/env python3
"""Phase-2 amendment A2 (ml/IMPROVEMENT_PLAN_2.md section 4): seed calibration of the book marks (Q10).

Inputs: ml/results/improve/ab/10y_p2/books.json and compare.json with the seed replicates control (108), control_s109,
control_s110, control_s111, q9_expanding (108), q9_expanding_s109, q9_expanding_s110.  Readings exactly as registered:
the seed spread per configuration; the seed-averaged paired monthly comparison Q9 minus control (iid months and 3-month
blocks, ml/improve/liquid.boot_ci); the min/max seed rule; the seed-averaged fold-AUC delta with a 3-fold moving-block
bootstrap.

    python3 -m ml.improve.q10
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from ml.improve import liquid as L

ML = Path(__file__).resolve().parents[1]
TAG = ML / "results" / "improve" / "ab" / "10y_p2"
OUT = ML / "results" / "improve2" / "seeds"
CTRL = ["control", "control_s109", "control_s110", "control_s111"]
Q9 = ["q9_expanding", "q9_expanding_s109", "q9_expanding_s110"]
SEEDS = {"control": 108, "control_s109": 109, "control_s110": 110, "control_s111": 111,
         "q9_expanding": 108, "q9_expanding_s109": 109, "q9_expanding_s110": 110}
BOOKS = ["vol+size|liq_top_decile", "vol+size|top_decile", "none|liq_top_decile", "none|top_decile"]
PER20 = 252 / 20


def fold_block_ci(d: np.ndarray, block: int = 3, B: int = 1000, seed: int = 108) -> list[float]:
    rng = np.random.default_rng(seed)
    M = d.size
    nb = math.ceil(M / block)
    st = rng.integers(0, M - block + 1, size=(B, nb))
    idx = (st[:, :, None] + np.arange(block)[None, None, :]).reshape(B, -1)[:, :M]
    m = d[idx].mean(1)
    return [float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]


def main() -> None:
    books = json.loads((TAG / "books.json").read_text())["books"]
    cmp_ = json.loads((TAG / "compare.json").read_text())["models"]
    res = {"plan": "ml/IMPROVEMENT_PLAN_2.md section 4, amendment A2 (Q10)", "seeds": SEEDS, "spread": {}, "seed_averaged": {}}
    for bk in BOOKS:
        res["spread"][bk] = {}
        for n in CTRL + Q9:
            c = books[f"{n}|{bk}"]["segments"]["combined"]["20bps"]
            res["spread"][bk][n] = {"excess_ann": c["excess_ann_vs_ew"], "ir": c["ir"], "ir_ci95": c["ir_ci95"],
                                    "months_positive": books[f"{n}|{bk}"]["months_positive"]}
        months = sorted(books[f"control|{bk}"]["monthly_net_20bps"])
        for n in CTRL + Q9:
            assert sorted(books[f"{n}|{bk}"]["monthly_net_20bps"]) == months, f"{n}|{bk}: month coverage differs"
        mc = np.array([[books[f"{n}|{bk}"]["monthly_net_20bps"][m] for m in months] for n in CTRL]).mean(0)
        mq = np.array([[books[f"{n}|{bk}"]["monthly_net_20bps"][m] for m in months] for n in Q9]).mean(0)
        d = mq - mc
        iid, blk = L.boot_ci(d, 1), L.boot_ci(d, 3)
        ex_c = [res["spread"][bk][n]["excess_ann"] for n in CTRL]
        ex_q = [res["spread"][bk][n]["excess_ann"] for n in Q9]
        res["seed_averaged"][bk] = {
            "n_months": len(months), "control_mean_excess_ann": float(np.mean(ex_c)), "q9_mean_excess_ann": float(np.mean(ex_q)),
            "control_seed_range": [float(min(ex_c)), float(max(ex_c))], "q9_seed_range": [float(min(ex_q)), float(max(ex_q))],
            "control_seed_sd": float(np.std(ex_c, ddof=1)), "q9_seed_sd": float(np.std(ex_q, ddof=1)),
            "paired_mean_ann": float(d.mean() * PER20),
            "paired_iid_ci_ann": [x * PER20 for x in iid["ci95"]], "paired_block3_ci_ann": [x * PER20 for x in blk["ci95"]],
            "months_q9_ahead": int((d > 0).sum()),
            "both_cis_above_0": bool(iid["ci_above_0"] and blk["ci_above_0"]),
            "min_q9_seed_gt_max_control_seed": bool(min(ex_q) > max(ex_c)),
        }
        res["seed_averaged"][bk]["REAL"] = bool(res["seed_averaged"][bk]["both_cis_above_0"]
                                                and res["seed_averaged"][bk]["min_q9_seed_gt_max_control_seed"])
    folds = sorted(f for f in cmp_["control"]["fold_aucs"] if f != "holdout")
    A = {n: np.array([cmp_[n]["fold_aucs"][f] for f in folds]) for n in CTRL + Q9}
    auc_c, auc_q = np.mean([A[n] for n in CTRL], 0), np.mean([A[n] for n in Q9], 0)
    d = auc_q - auc_c
    res["auc"] = {"per_seed_cv_mean": {n: float(A[n].mean()) for n in CTRL + Q9},
                  "control_seed_sd": float(np.std([A[n].mean() for n in CTRL], ddof=1)),
                  "q9_seed_sd": float(np.std([A[n].mean() for n in Q9], ddof=1)),
                  "seed_averaged_delta": float(d.mean()), "fold_block3_ci": fold_block_ci(d),
                  "folds_q9_ahead": f"{int((d > 0).sum())}/{d.size}",
                  "per_seed_pairs_vs_control_seed108": {n: float((A[n] - A["control"]).mean()) for n in CTRL[1:] + Q9}}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "seeds.json").write_text(json.dumps(res, indent=1, default=float))
    md = ["# Q10 (amendment A2): seed calibration of the book marks", "",
          "Plan: `ml/IMPROVEMENT_PLAN_2.md` section 4, A2. Every number is quoted from `seeds.json`. Net 20 bps per side, "
          "excess over the equal-weight benchmark of the book (universe or liquid tercile).", "",
          "## Seed spread", "", "| Book | Configuration | Seed | Excess/yr | IR [95% CI] | Months ahead |", "|---|---|---:|---:|---|---:|"]
    for bk in BOOKS:
        for n in CTRL + Q9:
            x = res["spread"][bk][n]
            md.append(f"| {bk} | {'control' if n in CTRL else 'expanding'} | {SEEDS[n]} | {100 * x['excess_ann']:+.1f}% | "
                      f"{x['ir']:+.2f} [{x['ir_ci95'][0]:+.2f}, {x['ir_ci95'][1]:+.2f}] | {x['months_positive']}/105 |")
    md += ["", "## Seed-averaged comparison (expanding minus control)", "",
           "| Book | Control mean (range) | Expanding mean (range) | Paired, pp/yr | iid CI | 3-month-block CI | Min expanding seed > max control seed | Reading |",
           "|---|---|---|---:|---|---|---|---|"]
    for bk in BOOKS:
        x = res["seed_averaged"][bk]
        md.append(f"| {bk} | {100 * x['control_mean_excess_ann']:+.1f}% ({100 * x['control_seed_range'][0]:+.1f}..{100 * x['control_seed_range'][1]:+.1f}) | "
                  f"{100 * x['q9_mean_excess_ann']:+.1f}% ({100 * x['q9_seed_range'][0]:+.1f}..{100 * x['q9_seed_range'][1]:+.1f}) | "
                  f"{100 * x['paired_mean_ann']:+.2f} | [{100 * x['paired_iid_ci_ann'][0]:+.2f}, {100 * x['paired_iid_ci_ann'][1]:+.2f}] | "
                  f"[{100 * x['paired_block3_ci_ann'][0]:+.2f}, {100 * x['paired_block3_ci_ann'][1]:+.2f}] | {x['min_q9_seed_gt_max_control_seed']} | "
                  f"{'**REAL**' if x['REAL'] else '**not shown**'} |")
    a = res["auc"]
    md += ["", f"AUC: control seeds {', '.join(f'{v:.4f}' for k, v in a['per_seed_cv_mean'].items() if k in CTRL)} "
           f"(sd {a['control_seed_sd']:.4f}); expanding seeds {', '.join(f'{v:.4f}' for k, v in a['per_seed_cv_mean'].items() if k in Q9)} "
           f"(sd {a['q9_seed_sd']:.4f}). Seed-averaged delta {a['seed_averaged_delta']:+.4f}, 3-fold-block CI "
           f"[{a['fold_block3_ci'][0]:+.4f}, {a['fold_block3_ci'][1]:+.4f}], expanding ahead in {a['folds_q9_ahead']} folds.", "",
           "Registered reading (neutral liquid book decides): "
           f"**{'Q9 book gain REAL' if res['seed_averaged']['vol+size|liq_top_decile']['REAL'] else 'Q9 book gain NOT SHOWN'}**."]
    (OUT / "SEEDS.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()

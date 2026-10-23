#!/usr/bin/env python3
"""The five pre-registered gates (ml/SCALE_UP.md) for every configuration of an A/B tag, at the phase's trial
count.  Inputs: ml/results/improve/ab/<tag>/compare.json (fold AUCs, paired bootstraps vs the control and vs
the linear benchmark) and ml/results/improve/ab/<tag>/books.json (the P2 construction applied to each
configuration).  Gate 4 (yearly re-selection stability) does not apply to configurations that select nothing;
it is reported as not applicable and not counted, as the five-year report did for the all-features model.

    python3 -m ml.improve.gates --tag v2 [--n-trials 241]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ML_DIR = Path(__file__).resolve().parents[1]
OUT_ROOT = ML_DIR / "results" / "improve" / "ab"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="v2")
    ap.add_argument("--n-trials", type=int, default=241)
    a = ap.parse_args()
    out = OUT_ROOT / a.tag
    cmp_ = json.loads((out / "compare.json").read_text())
    books = json.loads((out / "books.json").read_text())["books"]
    N = str(a.n_trials)
    rows, res = [], {}
    for n, m in cmp_["models"].items():
        if n in ("lr_l2", "baseline_mom", "all51"):
            continue
        g = {}
        p1 = cmp_.get("pairs_vs_lr_l2", {}).get(f"{n} - lr_l2")
        g["1"] = {"name": "beats the L2 logistic on CV mean, paired block-bootstrap CI excluding zero",
                  "number": (f"{p1['delta_cv_mean']:+.4f} [{p1['ci95'][0]:+.4f}, {p1['ci95'][1]:+.4f}]" if p1 else "n/a"),
                  "pass": bool(p1 and p1["gate1_pass"])}
        g["2"] = {"name": "fold AUC >= 0.50 in >= 90% of months",
                  "number": f"{100 * m['pct_folds_ge_050']:.0f}% (worst {m['min_fold_auc']:.3f})",
                  "pass": bool(m["pct_folds_ge_050"] >= 0.90)}
        for lab, nt in (("plain", "none"), ("vol+size-neutral", "vol+size")):
            b = books.get(f"{n}|{nt}|top_decile")
            if b:
                g[f"3 ({lab})"] = {"name": "top decile beats the EW universe in >= 75% of months, net 20 bps",
                                   "number": f"{b['months_positive']}/{b['n_months']} = {100 * b['share_months_positive']:.0f}%",
                                   "pass": bool(b["share_months_positive"] >= 0.75)}
        g["4"] = {"name": "selected-feature overlap >= 7/10 across yearly re-selections",
                  "number": "not applicable: the configuration selects nothing (all features, no yearly re-selection)",
                  "pass": None}
        for lab, nt in (("plain", "none"), ("vol+size-neutral", "vol+size")):
            b = books.get(f"{n}|{nt}|liq_top_decile")
            if b:
                d = b["dsr"][N]
                g[f"5 ({lab})"] = {"name": f"Deflated Sharpe >= 0.95 on the liquid-tercile top decile, N = {N}",
                                   "number": f"DSR {d['dsr']:.3f} (SR {d['sr_annualised']:+.2f}/yr, PSR {d['psr_vs_0']:.3f})",
                                   "pass": bool(d["dsr"] >= 0.95)}
        scored = [v for k, v in g.items() if v["pass"] is not None]
        g["n_pass"] = f"{sum(v['pass'] for v in scored)} of {len(scored)} scored (gate 4 not applicable)"
        res[n] = g
        rows.append(n)
    (out / "gates.json").write_text(json.dumps({"tag": a.tag, "n_trials": a.n_trials, "gates": res}, indent=1))
    L = [f"# Pre-registered gates ({a.tag}, N = {a.n_trials})", "",
         "| Configuration | " + " | ".join(k for k in res[rows[0]] if k != "n_pass") + " | Passed |",
         "|---|" + "---|" * (len(res[rows[0]]) - 1) + "---|"]
    for n in rows:
        g = res[n]
        cells = []
        for k, v in g.items():
            if k == "n_pass":
                continue
            mark = "n/a" if v["pass"] is None else ("PASS" if v["pass"] else "FAIL")
            cells.append(f"{v['number']} **{mark}**")
        L.append(f"| {n} | " + " | ".join(cells) + f" | {g['n_pass']} |")
    (out / "GATES.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()

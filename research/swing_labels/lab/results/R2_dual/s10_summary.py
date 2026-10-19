"""Stage 10: structured summary (verdicts + headline numbers) into results.json."""
import json
from common import OUT, save

R = json.load(open(f"{OUT}/results.json"))
m = {(r["name"], r["win"], r["cost"]): r for r in R["s5_main"]}
av = {(r["name"], r["mask"], r["win"], r["cost"]): r for r in R["s5_avoid"]}
ph = R["s9_phase"]["summary"]
pha = R["s9b_phase_avoid"]["summary"]


def book(nm):
    d, d8, h = m[(nm, "dev", 50.0)], m[(nm, "dev", 80.0)], m[(nm, "hold", 50.0)]
    return {"dev_cagr_50": d["cagr"], "dev_cagr_80": d8["cagr"], "dev_excess_nw_t": d["excess_nw_t"], "dev_maxdd": d["max_dd"],
            "dev_random_cagr_50": d["rand_cagr"], "holdout_cagr_50": h["cagr"], "holdout_excess_nw_t": h["excess_nw_t"],
            "holdout_random_cagr_50": h["rand_cagr"], "phase_mean_dev_cagr": ph["dev"].get(nm, {}).get("cagr_mean"),
            "phase_mean_hold_cagr": ph["hold"].get(nm, {}).get("cagr_mean")}


def avd(nm):
    d, d8, h = av[(nm, "U", "dev", 50.0)], av[(nm, "U", "dev", 80.0)], av[(nm, "U", "hold", 50.0)]
    return {"dev_cagr_50": d["cagr"], "dev_cagr_80": d8["cagr"], "dev_excess_nw_t": d["excess_nw_t"], "dev_maxdd": d["max_dd"],
            "dev_random_cagr_50": d["rand_cagr"], "holdout_cagr_50": h["cagr"], "holdout_excess_nw_t": h["excess_nw_t"],
            "holdout_random_cagr_50": h["rand_cagr"], "vs_universe_dev": pha["dev"][nm]["vs_univ_mean"],
            "vs_universe_hold": pha["hold"][nm]["vs_univ_mean"]}


out = {"verdict": "Label-side AND (DUAL) = same-loss pure relative (RUP) within noise; no fewer drawdowns; "
                  "absolute leg adds market timing a cross-sectional book cannot use. Use pure relative (binary top-30 "
                  "or blend with XR_neu regression); avoid = low P(rel top-30).",
       "books": {k: book(k) for k in ("REL", "RUP", "DUAL", "DUALP", "DUALt300", "ABS", "BAR", "SUM_REL_ABS",
                                      "PROD_RUP_ABS", "AND_REL_ABS50", "SUM_REL_RUP", "SUM_REL_DUAL") if (k, "dev", 50.0) in m},
       "avoid": {k: avd(k) for k in ("AVOID_RUPup", "AVOID_DUALup", "AVOID_DDN", "AVOID_RDN", "AVOID_REL", "AVOID_ABS")},
       "phase_pairs": {w: ph[w]["pairs"] for w in ("dev", "hold")},
       "variants": {"walk_forward_models": len([k for k in R if k.startswith("s3_wf_")]),
                    "dev_book_configs": R["s7_paired"]["n_dev_strategy_configs"], "label_variants_event_screen": 56,
                    "phase_robustness_runs": "5 phases x 7 books + 6 avoid overlays (robustness, not selection)"}}
save("summary", out)
print(json.dumps(out["books"]["DUAL"], indent=0)[:400])

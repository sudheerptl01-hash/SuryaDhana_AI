"""Stage 5 (devil): deflated Sharpe ratio / multiple-testing haircut with the programme-wide trial count.

Inputs: the self-built book's daily excess-vs-random series (phase-0 and phase-averaged), the variant
counts declared by every round-1 and round-2 agent, and the empirical cross-trial dispersion of DEV
excess t-stats from the refiners' saved results (R2_rel, R2_alpha, R2_dual).
DSR (Bailey & Lopez de Prado 2014): Phi[(SR - SR0) sqrt(T_eff-1) / sqrt(1 - g3 SR + (g4-1)/4 SR^2)],
SR0 = sqrt(V) * ((1-gamma) z(1-1/N) + gamma z(1-1/(N e))). Autocorrelation is handled with
T_eff = (t_NW / SR_daily)^2, so SR*sqrt(T_eff) equals the Newey-West t.
"""
import json

import numpy as np
import pandas as pd
from scipy import stats

from common import OUT, L, PER, log, save, load_sim, compare

LABR = f"{L.LAB}/results"
EG = 0.5772156649


def emax(N):
    N = max(float(N), 1.0001)
    return (1 - EG) * stats.norm.ppf(1 - 1 / N) + EG * stats.norm.ppf(1 - 1 / (N * np.e))


# ---------------------------------------------------------------- variant counts
r1 = json.load(open(f"{LABR}/_lead/round1_results.json"))
r1_counts = {x["agent_id"]: int(x.get("variants_tried") or 0) for x in r1}
rel = json.load(open(f"{LABR}/R2_rel/results.json"))["s10_variant_count"]
alpha = json.load(open(f"{LABR}/R2_alpha/results.json"))["s11_variants"]
dual = json.load(open(f"{LABR}/R2_dual/results.json"))["summary"]["variants"]
regime = json.load(open(f"{LABR}/R2_regime/results.json"))["variant_count"]
event = json.load(open(f"{LABR}/R2_event/results.json"))["final_summary"]
r2_counts = {"R2_rel_distinct_dev_specs": rel["distinct_specs_dev_50bp"],
             "R2_dual_dev_book_configs": dual["dev_book_configs"],
             "R2_alpha_distinct_dev_specs": alpha["distinct_dev_strategy_specs_50bps"],
             "R2_regime_book_level_dev_specs": regime["book_level_dev_specs"],
             "R2_event_variants_total": event["variants_total"]}
n_r1 = sum(r1_counts.values())
n_r2 = sum(r2_counts.values())
n_all_runs = n_r1 + rel["total_portfolio_tests_dev"] + dual["dev_book_configs"] + dual["label_variants_event_screen"] \
    + alpha["distinct_dev_strategy_specs_50bps"] + regime["book_level_dev_specs"] + regime["total_timing_variants"] \
    + event["variants_total"]
counts = {"round1_by_agent": r1_counts, "round1_total": n_r1, "round1_brief_approx": 600, "round2_by_agent": r2_counts,
          "round2_total": n_r2, "programme_total_distinct": n_r1 + n_r2,
          "programme_total_with_brief_r1": 600 + n_r2, "programme_upper_all_runs": n_all_runs}
log("counts", counts)

# ---------------------------------------------------------------- cross-trial dispersion of DEV t
def collect_rel():
    d = json.load(open(f"{LABR}/R2_rel/results.json"))
    ts = []
    for k, v in d.items():
        if not k.startswith("s5_") or not isinstance(v, list):
            continue
        for rec in v:
            if not isinstance(rec, dict):
                continue
            cfg = rec.get("cfg", {})
            if rec.get("period") == "dev" and cfg.get("cost_bps") == 50 and rec.get("excess_daily_nw_t") is not None:
                ts.append(rec["excess_daily_nw_t"])
    return np.array(ts, float)


t_rel = collect_rel()
disp = {"R2_rel_dev50_records": int(len(t_rel)), "mean": float(t_rel.mean()), "sd": float(t_rel.std(ddof=1)),
        "p50": float(np.median(t_rel)), "p90": float(np.percentile(t_rel, 90)), "max": float(t_rel.max()),
        "share_gt3": float((t_rel > 3).mean()), "share_gt4": float((t_rel > 4).mean())}
log("dispersion", disp)

# ---------------------------------------------------------------- the selected book's excess series
P, F, fw, S, E = load_sim()
sc = np.load(f"{OUT}/wf_main.npz")["score"].astype("float64")
z = np.load(f"{OUT}/pa_series_main.npz")
series = {}
for per, (a, b) in PER.items():
    res, sd, rbd, dts = compare(S, sc, E, "liq2", 20, dict(top_k=20, step=5, cost_bps=50, start=a, end_exit=b))
    n = min(len(sd), len(rbd))
    series[f"phase0_{per}"] = sd[:n] - rbd[:n]
    series[f"phaseavg_{per}"] = z[f"{per}_strat"] - z[f"{per}_rand"]


def sr_stats(x, lag=20):
    x = np.asarray(x, float)
    sr = x.mean() / x.std(ddof=1)
    t_nw = L.nw_t(x, lag)
    t_naive = sr * np.sqrt(len(x))
    t_eff = (t_nw / sr) ** 2
    return {"T": int(len(x)), "ann_mean": float(x.mean() * 252), "ann_te": float(x.std(ddof=1) * np.sqrt(252)),
            "IR_ann": float(sr * np.sqrt(252)), "SR_daily": float(sr), "skew": float(stats.skew(x)),
            "kurt": float(stats.kurtosis(x, fisher=False)), "t_naive": float(t_naive), "t_nw": float(t_nw),
            "T_eff": float(t_eff)}


def dsr(st, N, sd_t):
    """sd_t = cross-trial sd of the t-statistic (1.0 = pure null)."""
    sr, te = st["SR_daily"], st["T_eff"]
    V = sd_t ** 2 / te
    sr0 = np.sqrt(V) * emax(N)
    den = np.sqrt(max(1 - st["skew"] * sr + (st["kurt"] - 1) / 4 * sr ** 2, 1e-9))
    return float(stats.norm.cdf((sr - sr0) * np.sqrt(te - 1) / den)), float(sr0 * np.sqrt(te))


out = {"variant_counts": counts, "cross_trial_t_dispersion": disp, "series_stats": {}, "dsr": {}}
Ns = {"R2_rel_only": 477, "M_eff_LiJi_R2rel": 71, "M_eff_Nyholt_R2rel": 210, "round2_total": n_r2,
      "programme_total": n_r1 + n_r2, "programme_brief_r1_600": 600 + n_r2, "upper_all_runs": n_all_runs}
for nm, x in series.items():
    st = sr_stats(x)
    out["series_stats"][nm] = st
    if not nm.endswith("dev"):
        continue
    tab = {}
    for nn, N in Ns.items():
        for sdt in (1.0, 1.10, 1.19):
            p, t0 = dsr(st, N, sdt)
            tab[f"{nn}_N{N}_sd{sdt}"] = {"DSR": p, "t_hurdle_expected_max": t0,
                                          "bonferroni_t_5pct_onesided": float(sdt * stats.norm.ppf(1 - 0.05 / N))}
    out["dsr"][nm] = tab
    log(nm, {k: round(v, 3) if isinstance(v, float) else v for k, v in st.items()})
    for k_, v_ in tab.items():
        if k_.endswith("sd1.1") or k_.endswith("sd1.0"):
            log("  ", k_, {a: round(b, 3) for a, b in v_.items()})

# HLZ-style haircut of the DEV excess (Bonferroni), phase-averaged t
st = out["series_stats"]["phaseavg_dev"]
hc = {}
for nn, N in Ns.items():
    p1 = 1 - stats.norm.cdf(st["t_nw"])
    padj = min(1.0, p1 * N)
    tadj = stats.norm.ppf(1 - padj) if padj < 1 else 0.0
    hc[nn] = {"N": N, "p_onesided": float(p1), "p_bonf": float(padj), "t_adj": float(max(tadj, 0)),
              "haircut_share": float(1 - max(tadj, 0) / st["t_nw"]),
              "haircut_excess_ann": float(st["ann_mean"] * max(tadj, 0) / st["t_nw"])}
out["hlz_bonferroni_haircut_phaseavg_dev"] = hc
log("haircut", {k: (round(v["haircut_excess_ann"], 4), round(v["p_bonf"], 3)) for k, v in hc.items()})

# precision-weighted forward estimate: DEV (raw and haircut) combined with the untouched 2026 holdout
sd_dev = st["ann_mean"] / st["t_nw"]
sh = out["series_stats"]["phaseavg_hold"]
sd_hold = abs(sh["ann_mean"] / sh["t_nw"]) if sh["t_nw"] else np.nan
comb = {}
for nm_, dev_est in (("raw_dev", st["ann_mean"]), ("bonf_haircut_programme", hc["programme_total"]["haircut_excess_ann"]),
                     ("half_dev", st["ann_mean"] / 2)):
    w1, w2 = 1 / sd_dev ** 2, 1 / sd_hold ** 2
    m = (dev_est * w1 + sh["ann_mean"] * w2) / (w1 + w2)
    comb[nm_] = {"dev_input": float(dev_est), "combined": float(m), "combined_se": float(np.sqrt(1 / (w1 + w2)))}
out["forward_estimate_precision_weighted"] = {"se_dev_ann": float(sd_dev), "se_hold_ann": float(sd_hold),
                                               "hold_ann": sh["ann_mean"], "z_hold_vs_dev": float((sh["ann_mean"] - st["ann_mean"]) / np.sqrt(sd_dev ** 2 + sd_hold ** 2)),
                                               **comb}
log("forward", out["forward_estimate_precision_weighted"])
save("s5_dsr", out)

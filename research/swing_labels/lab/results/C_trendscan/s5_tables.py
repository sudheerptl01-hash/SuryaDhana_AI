#!/usr/bin/env python3
"""Stage 5: render every measured number in results.json into markdown tables (tables_autogen.md)."""
import json

from common import OUT

R = json.load(open(f"{OUT}/results.json"))
E = R["s2_event_rates"]
md = []


def f(x, nd=3, pct=False, bps=False, sign=False):
    if x is None:
        return "–"
    if pct:
        return f"{x * 100:+.1f}%" if sign else f"{x * 100:.1f}%"
    if bps:
        return f"{x:+.0f}"
    return f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}"


def table(head, rows):
    md.append("| " + " | ".join(head) + " |")
    md.append("|" + "|".join(["---"] * len(head)) + "|")
    for r in rows:
        md.append("| " + " | ".join(str(x) for x in r) + " |")
    md.append("")


DEFS = {
    "TSA_T{T}": "trend-scan on log(close[t+k]/open[t+1]), L*=argmax|t| over L=5..20, sign if |t*|>=T",
    "TSX_T{T}": "same on market-excess log path (stock minus Nifty 500 over same rows)",
    "RA10": "z=r10/(vol_20*sqrt10), +1 if z>=0.5 (and r>=50bp), -1 mirror",
    "RA20": "z=r20/(vol_20*sqrt20), +-0.5 dead zone",
    "MQ_vol{a}": "MFE/MAE over 20 bars: +1 if MFE>=a*vol_20*sqrt20 and MFE>=2|MAE|; -1 mirror",
    "MQ_atr{a}": "same with a*atr_pct*sqrt20",
    "FP20": "first passage of +-vol_20*sqrt20 within 20 bars (gap/same-bar aware)",
    "FP10": "first passage of +-vol_20*sqrt10 within 20 bars",
    "FX10_pm50": "control: r10 > +50bp / < -50bp (fixed horizon)",
    "FX20_pm50": "control: r20 > +50bp / < -50bp (fixed horizon)",
}

# ------------------------------------------------------------------ A. null vs real
md.append("### A. Trend-scan statistic: real NSE paths vs driftless random-walk null\n")
s1 = R["s1_build"]
null = R["s2_null"]
LS = R["s2_Lstar"]
rows = []
for nm, lab in (("TSA", "real NSE, absolute path (eq universe)"), ("TSX", "real NSE, market-excess path")):
    sh = {T: 1 - E[f"{nm}_T{T}"]["overall"]["0.0"] for T in (2, 3, 5, 8, 10)}
    q = s1["tsA_abs_t_quantiles_eq"] if nm == "TSA" else {}
    rows.append([lab, f(q.get("0.1"), 2) if q else "–", f(q.get("0.5"), 2) if q else "–", f(q.get("0.9"), 2) if q else "–",
                 *[f(sh[T], pct=True) for T in (2, 3, 5, 8, 10)],
                 f(LS[nm]["hist_all"]["5"], pct=True), f(LS[nm]["hist_all"]["20"], pct=True)])
for nm, lab in (("gauss_iid", "null: Gaussian iid random walk"), ("student_t4_iid", "null: Student-t(4) iid"),
                ("gauss_iid_first_bar_half_var", "null: Gaussian, first bar half variance")):
    d = null[nm]
    rows.append([lab, f(d["abs_t_quantiles"]["0.1"], 2), f(d["abs_t_quantiles"]["0.5"], 2), f(d["abs_t_quantiles"]["0.9"], 2),
                 *[f(d["share_abs_t_ge"][str(T)], pct=True) for T in (2, 3, 5, 8, 10)],
                 f(d["Lstar_hist"]["5"], pct=True), f(d["Lstar_hist"]["20"], pct=True)])
table(["series", "abs t* p10", "median", "p90", "P(|t*|>=2)", ">=3", ">=5", ">=8", ">=10", "P(L*=5)", "P(L*=20)"], rows)

# L* histogram
md.append("### A2. L* distribution (share of rows), real vs null\n")
bins = [("5", [5]), ("6-8", [6, 7, 8]), ("9-12", [9, 10, 11, 12]), ("13-16", [13, 14, 15, 16]), ("17-19", [17, 18, 19]), ("20", [20])]
rows = []
for lab, hist in (("TSA real", LS["TSA"]["hist_all"]), ("TSX real", LS["TSX"]["hist_all"]),
                  ("TSA real, T=5 up", LS["TSA"]["hist_T5_up"]), ("TSA real, T=5 down", LS["TSA"]["hist_T5_down"]),
                  ("null Gaussian", null["gauss_iid"]["Lstar_hist"])):
    rows.append([lab] + [f(sum(hist.get(str(k), 0) for k in ks), pct=True) for _, ks in bins])
table(["", *[b for b, _ in bins]], rows)

# ------------------------------------------------------------------ B. event-rate master table
md.append("### B. Event rates on the equity universe (elig_base minus ETFs), all variants screened\n")
rows = []
for nm, e in E.items():
    rows.append([nm, f"{e['n']:,}", f(e["overall"].get("-1.0"), pct=True), f(e["overall"].get("0.0"), pct=True),
                 f(e["overall"].get("1.0"), pct=True), f(e["monthly_pos"]["mean"], pct=True), f(e["monthly_pos"]["std"], pct=True),
                 f(e["monthly_pos"]["min"], pct=True), f(e["monthly_pos"]["max"], pct=True),
                 f(e.get("corr_monthly_pos_vs_mkt_ret"), 2, sign=True), f(e.get("corr_pos_mkt_dev"), 2, sign=True),
                 f(e.get("corr_pos_mkt_2026"), 2, sign=True), f(e.get("corr_neg_mkt_dev"), 2, sign=True),
                 f(e["fno_overall"]["1"], pct=True), f(e["fno_overall"]["-1"], pct=True)])
table(["label", "n", "P(-1)", "P(0)", "P(+1)", "mo P(+1) mean", "mo std", "mo min", "mo max", "corr all", "corr dev",
       "corr 2026", "corr P(-1) dev", "F&O P(+1)", "F&O P(-1)"], rows)

KEY = ["TSA_T5", "TSX_T5", "TSA_T8", "RA10", "RA20", "MQ_vol1.0", "FP20", "FX10_pm50", "FX20_pm50"]
md.append("### C. By year: P(+1) / P(-1) (2026 = holdout, Jan-Sep)\n")
rows = []
for nm in KEY:
    by = E[nm]["by_year"]
    rows.append([nm] + [f"{by[y]['1.0'] * 100:.1f} / {by[y]['-1.0'] * 100:.1f}" for y in sorted(by)])
table(["label", *sorted(E["TSA_T5"]["by_year"])], rows)

md.append("### D. By market regime (Nifty 500 vs its 200d SMA x 20d momentum): P(+1) / P(-1)\n")
regs = ["bull_up20", "bull_dn20", "bear_up20", "bear_dn20"]
rows = []
for nm in KEY:
    br = E[nm]["by_regime"]
    rows.append([nm] + [f"{br[r]['1.0'] * 100:.1f} / {br[r]['-1.0'] * 100:.1f}" for r in regs])
rows.append(["n rows (TSA_T5)"] + [f"{E['TSA_T5']['by_regime'][r]['n']:,}" for r in regs])
table(["label", *regs], rows)

md.append("### E. By liquidity tercile (20d turnover, within month; 0 = least liquid): P(+1) / P(-1)\n")
rows = []
for nm in KEY:
    bl = E[nm]["by_liquidity_tercile"]
    rows.append([nm] + [f"{bl[t]['1.0'] * 100:.1f} / {bl[t]['-1.0'] * 100:.1f}" for t in sorted(bl)])
table(["label", "T0 (illiquid)", "T1", "T2 (liquid)"], rows)

md.append("### F. Label/P&L coherence: mean NET return (50 bp) of each class under different exits\n")
rows = []
for nm in KEY:
    for cl in ("1", "0", "-1"):
        c = E[nm]["coherence"].get(cl)
        if not c:
            continue
        rows.append([nm, cl, f(c["share"], pct=True), f(c["natural_exit_net50"], pct=True, sign=True),
                     f(c["fixed10_net50"], pct=True, sign=True), f(c["fixed20_net50"], pct=True, sign=True),
                     f(c["fixed10_excess_mkt"], pct=True, sign=True), f(c["p_fixed10_net_pos"], pct=True),
                     f(c["p_fixed20_net_pos"], pct=True)])
table(["label", "class", "share", "natural exit net", "fixed 10d net", "fixed 20d net", "10d excess vs N500",
       "P(10d net>0)", "P(20d net>0)"], rows)

md.append("### G. Label-execution mismatch: TSA_T5 labels by L* bucket (mean GROSS returns)\n")
rows = []
for side in ("up", "down"):
    b = LS["TSA"][f"bucket_T5_{side}"]
    for k, v in b.items():
        rows.append([side, k, f(v["share"], pct=True), f(v["rL"], pct=True, sign=True), f(v["r5"], pct=True, sign=True),
                     f(v["r10"], pct=True, sign=True), f(v["r20"], pct=True, sign=True)])
table(["side", "L* bucket", "share of side", "return at L* (oracle exit)", "fixed 5d", "fixed 10d", "fixed 20d"], rows)

md.append("### H. Overlap: pooled within-entity autocorrelation of the label\n")
ac = R["s2_autocorr"]
table(["label", "lag 1", "lag 5", "lag 10"], [[k, f(v["lag1"], 2), f(v["lag5"], 2), f(v["lag10"], 2)] for k, v in ac.items()])

md.append("### I. Label agreement (Cohen's kappa; share of identical class in brackets)\n")
ag = R["s2b_agreement"]
table(["pair", "kappa", "agree"], [[k.replace("|", " vs "), f(v, 2), f(ag["agree_same_class"][k], pct=True)]
                                   for k, v in ag["kappa"].items()])

# ------------------------------------------------------------------ learnability
models = [k[6:] for k in R if k.startswith("s3_wf_")]
order = [m for m in ("TSA_T5", "TSX_T5", "MQ_vol1.0", "RA10", "FX10_pm50", "FX20_pm50") if m in models]
md.append("### J. Learnability (walk-forward OOS, LightGBM multiclass, 52 PIT features w/o sec_rel_mom20)\n")
md.append("Pooled AUC (lablib definition, mixes market timing) and mean DAILY cross-sectional AUC (stock selection only).\n")
rows = []
for m in order:
    w = R[f"s3_wf_{m}"]
    s4 = R.get(f"s4_{m}", {}).get("learn", {})
    for fo in w["folds"]:
        y = fo["year"]
        rows.append([m, y, f(fo.get("auc_up")), f(fo.get("auc_down_inverted")),
                     f(s4.get("xs_auc_up_by_year", {}).get(str(y))), f(s4.get("xs_auc_down_by_year", {}).get(str(y))),
                     f(fo["base_rate"], pct=True), f(fo["top_decile_rate"], pct=True), f(fo["bottom_decile_rate"], pct=True),
                     f(fo.get("down_base_rate"), pct=True), f(fo.get("down_rate_in_bottom_decile"), pct=True)])
table(["model", "year", "pooled AUC up", "pooled AUC down", "XS-AUC up", "XS-AUC down", "P(+1) base", "P(+1) top dec",
       "P(+1) bottom dec", "P(-1) base", "P(-1) bottom dec"], rows)

md.append("### K. Common yardstick: daily rank IC of each model's score vs executable forward returns\n")
rows = []
for m in order:
    s4 = R.get(f"s4_{m}", {}).get("learn")
    if not s4:
        continue
    for h in (5, 10, 20):
        by = s4[f"ic_r{h}_by_year"]
        rows.append([m, f"r{h}", *[f(by.get(str(y)), 3, sign=True) for y in (2023, 2024, 2025)],
                     f(s4[f"ic_r{h}_dev"], 3, sign=True), f(s4[f"ic_r{h}_t_dev"], 1), f(s4[f"ic_r{h}_2026"], 3, sign=True),
                     f(s4[f"ic_r{h}_t_2026"], 1)])
table(["model", "target", "IC 2023", "IC 2024", "IC 2025", "IC dev mean", "t dev (non-overlap)", "IC 2026", "t 2026"], rows)

md.append("### L. Top / bottom decile excess return vs date mean (bps, gross), per year\n")
rows = []
for m in order:
    s4 = R.get(f"s4_{m}", {}).get("learn")
    if not s4:
        continue
    for h in (10, 20):
        t = s4[f"top_dec_ex_r{h}_bps_by_year"]
        b = s4[f"bot_dec_ex_r{h}_bps_by_year"]
        rows.append([m, f"r{h}", *[f"{t[str(y)]:+.0f} / {b[str(y)]:+.0f}" for y in (2023, 2024, 2025, 2026)],
                     f"{s4[f'top_dec_ex_r{h}_bps_dev']:+.0f} / {s4[f'bot_dec_ex_r{h}_bps_dev']:+.0f}"])
    t = s4["fno_top_dec_ex_r10_bps_by_year"]
    b = s4["fno_bot_dec_ex_r10_bps_by_year"]
    rows.append([m, "r10 F&O only", *[f"{t[str(y)]:+.0f} / {b[str(y)]:+.0f}" for y in (2023, 2024, 2025, 2026)], "–"])
table(["model", "target", "2023 top/bot", "2024", "2025", "2026 (holdout)", "dev mean"], rows)

# ------------------------------------------------------------------ investability
RD = R.get("s4_RANDOM", {})
md.append("### M. Investability: long top-20 every 5 days, eq universe, next-open entry\n")
md.append("Sim-Sharpe as lablib computes it; 'adj' = Sharpe / sqrt(1+2*rho1) (auditor fix for overlapping sleeves).\n")


def inv_rows(src, label, keys):
    rows = []
    for k in keys:
        for wn in ("dev", "hold2026", "full"):
            v = src.get(f"{k}_{wn}")
            if not v:
                continue
            by = v.get("by_year", {})
            rows.append([label, k, wn, f(v["cagr"], pct=True, sign=True), f(v["sharpe"], 2), f(v["sharpe_rho_adj"], 2),
                         f(v["max_dd"], pct=True), f(v.get("hit_rate"), pct=True),
                         f(v.get("mean_trade_net", 0) * 1e4, bps=True),
                         " ".join(f"{y}:{by[y] * 100:+.0f}%" for y in sorted(by)) if wn == "full" else ""])
    return rows


keys = ["fixed10_c50", "fixed10_c80", "fixed20_c50", "fixed20_c80"]
rows = []
for m in order:
    if f"s4_{m}" in R:
        rows += inv_rows(R[f"s4_{m}"]["long"], m, keys)
if RD:
    rows += inv_rows(RD["avg"], "RANDOM (5 seeds)", keys)
table(["model", "exit/cost", "window", "CAGR", "Sharpe", "adj", "maxDD", "hit", "mean trade bp", "by year"], rows)
if RD:
    bm = RD["nifty500"]
    table(["Nifty 500 (price index)", "CAGR", "Sharpe(daily)", "maxDD", "by year"],
          [[wn, f(bm[wn]["cagr"], pct=True, sign=True), f(bm[wn]["sharpe"], 2), f(bm[wn]["max_dd"], pct=True),
            " ".join(f"{y}:{v * 100:+.0f}%" for y, v in bm[wn]["by_year"].items())] for wn in ("dev", "hold2026", "full")])

md.append("### N. Exit-rule comparison on the SAME picks (long top-20, 50 bp; S=4 sleeves for 20-bar-max exits)\n")
rows = []
srcs = [(m, R[f"s4_{m}"]["long"]) for m in order if f"s4_{m}" in R]
if RD:
    srcs.append(("RANDOM", RD["avg"]))
for m, src in srcs:
    for k in ("fixed10_c50", "fixed20_c50", "atr2_c50", "atr3_c50", "tsexit_c50"):
        d, h = src.get(f"{k}_dev"), src.get(f"{k}_hold2026")
        if not d:
            continue
        rows.append([m, k.replace("_c50", ""), f(d["cagr"], pct=True, sign=True), f(d["sharpe_rho_adj"], 2), f(d["max_dd"], pct=True),
                     f(d.get("avg_bars_held"), 1), f(d.get("net_per_bar_bps"), 2, sign=True), f(d.get("hit_rate"), pct=True),
                     f(h["cagr"], pct=True, sign=True), f(h["sharpe_rho_adj"], 2), f(h.get("net_per_bar_bps"), 2, sign=True)])
table(["model", "exit", "dev CAGR", "dev adj Sharpe", "dev maxDD", "bars held", "dev net/bar bp", "dev hit",
       "2026 CAGR", "2026 adj Sharpe", "2026 net/bar bp"], rows)

md.append("### O. Short side (bottom-20 by score among fno_proxy names, fixed 10d)\n")
rows = []
for m in order:
    if f"s4_{m}" in R:
        rows += inv_rows(R[f"s4_{m}"]["short_fno"], m, ["fixed10_c50", "fixed10_c80"])
if RD:
    rows += inv_rows({k[6:]: v for k, v in RD["avg"].items() if k.startswith("short_")}, "RANDOM short F&O", ["fixed10_c50", "fixed10_c80"])
table(["model", "exit/cost", "window", "CAGR", "Sharpe", "adj", "maxDD", "hit", "mean trade bp", "by year"], rows)

md.append("### O2. Long top-20 restricted to fno_proxy names (fixed 10d)\n")
rows = []
for m in order:
    if f"s4_{m}" in R:
        rows += inv_rows(R[f"s4_{m}"]["long_fno"], m, ["fixed10_c50"])
table(["model", "exit/cost", "window", "CAGR", "Sharpe", "adj", "maxDD", "hit", "mean trade bp", "by year"], rows)

md.append("### P. Long-only overlays (pre-registered): avoid30 = drop bottom-30% scores then 20 random; "
          "top30rand = 20 random from top-30% (5 seeds)\n")
rows = []
B = R.get("s4b_random", {})


def ov_rows(lab, blk):
    out = []
    for k, v in blk.items():
        for kk in (f"fixed{k[-2:]}_c50", f"fixed{k[-2:]}_c80"):
            d, h, fu = v[f"{kk}_dev"], v[f"{kk}_hold2026"], v[f"{kk}_full"]
            out.append([lab, k, kk.split("_")[1], f(d["cagr"], pct=True, sign=True), f(d["cagr_sd_seeds"], pct=True),
                        f(d["sharpe_rho_adj"], 2), f(h["cagr"], pct=True, sign=True), f(h["sharpe_rho_adj"], 2),
                        f(fu["cagr"], pct=True, sign=True), " ".join(f"{y}:{x * 100:+.0f}%" for y, x in fu["by_year"].items())])
    return out


rows += ov_rows("RANDOM", B)
for m in order:
    if f"s4b_{m}" in R:
        rows += ov_rows(m, R[f"s4b_{m}"])
table(["model", "overlay", "cost", "dev CAGR", "seed sd", "dev adj Sharpe", "2026 CAGR", "2026 adj Sharpe", "full CAGR", "by year"], rows)


# ------------------------------------------------------------------ Q. score similarity & IC differences
if "s6_compare" in R:
    C = R["s6_compare"]
    md.append("### Q1. Mean daily Spearman correlation between model scores (dev 2023-2025)\n")
    table(["pair", "corr"], [[k.replace("|", " vs "), f(v, 2)] for k, v in C["score_corr_dev"].items()])
    md.append("### Q2. Paired daily rank-IC difference vs fixed-horizon controls (non-overlapping t)\n")
    rows = []
    for k, v in C["ic_diff"].items():
        tgt, pair = k.split("|")
        a, b = pair.split("-", 1) if pair.count("-") == 1 else (pair.rsplit("-", 1)[0], pair.rsplit("-", 1)[1])
        rows.append([tgt, a, b, f(v["dev"]["mean_diff"], 4, sign=True), f(v["dev"]["t_nonoverlap"], 2),
                     " ".join(f"{y}:{x:+.3f}" for y, x in v["by_year"].items()),
                     f(v["2026"]["mean_diff"], 4, sign=True), f(v["2026"]["t_nonoverlap"], 2)])
    table(["target", "model", "minus control", "dev diff", "dev t", "by year", "2026 diff", "2026 t"], rows)

# ------------------------------------------------------------------ R. oracle capture
if "s7_oracle" in R:
    O = R["s7_oracle"]
    md.append("### R. Perfect-foresight capture: mean NET (50 bp) per trade if the label were known, by executable exit\n")
    md.append("(eq universe, <=60k sampled rows per cell; 'natural' = the label's own unknowable exit, e.g. close at L*)\n")
    rows = []
    for k, d in O.items():
        nm, cl, wn = k.split("|")
        rows.append([nm, cl, wn, f"{d['n_pool']:,}", f(d.get("natural_net"), pct=True, sign=True) if "natural_net" in d else "–",
                     *[f"{d[r]['net'] * 100:+.2f}% ({d[r]['bars']:.1f}b)" for r in ("fixed10", "fixed20", "atr2", "atr3", "tsexit")]])
    table(["label", "class", "window", "pool n", "natural exit", "fixed 10d", "fixed 20d", "ATR trail 2x", "ATR trail 3x", "TS-exit"], rows)

# ------------------------------------------------------------------ S. pick profile
if "s8_profile" in R:
    S8 = R["s8_profile"]
    md.append("### S. What each model buys: median features of long top-20 picks vs universe (2023-2026)\n")
    cols = ["vol_20", "atr_pct", "mom_20", "mom_60", "dist_sma200", "hi52_dist", "log_turn20", "beta_60", "volz_20"]
    rows = []
    for n, pr in S8["profile_long"].items():
        rows.append([n, *[f(pr[c], 3) for c in cols], f(pr["fno_share"], pct=True), f"{pr['raw_close_median']:.0f}", pr["unique_entities"]])
    u = S8["profile_universe"]
    rows.append(["UNIVERSE", *[f(u[c], 3) for c in cols], f(u["fno_share"], pct=True), f"{u['raw_close_median']:.0f}", "–"])
    table(["model", *cols, "F&O share", "price Rs", "unique names"], rows)
    md.append("Mean daily Jaccard overlap of top-20 lists: " + ", ".join(f"{k.replace('|', '/')} {v:.2f}" for k, v in S8["jaccard_top20"].items()) + "\n")

# ------------------------------------------------------------------ T. cost ladder / liquidity
if "s9_stress" in R:
    S9 = R["s9_stress"]
    md.append("### T. Cost ladder and liquidity robustness (long top-20, CAGR; break-even = mean gross trade in bp)\n")
    rows = []
    for n, res in S9.items():
        for k, v in res.items():
            bc = v["by_cost"]
            rows.append([n, k, *[f(bc[str(c)]["cagr"], pct=True, sign=True) for c in (50, 80, 100, 130)],
                         f"{v['breakeven_cost_bps_trade']:.0f}"])
    table(["model", "universe_hold_window", "50 bp", "80 bp", "100 bp", "130 bp", "break-even bp/trade"], rows)

open(f"{OUT}/tables_autogen.md", "w").write("\n".join(md))
print("wrote", len(md), "lines")

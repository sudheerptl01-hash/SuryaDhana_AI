"""Stage 9: render markdown tables (tables_autogen.md) from results.json + a small dead-zone
sensitivity computation for the market-excess label. Every number in REPORT.md comes from here."""
import json

import numpy as np
import pandas as pd

from common import OUT, L, save

R = json.load(open(f"{OUT}/results.json"))
md = []


def f(x, d=3, pct=False):
    if x is None or (isinstance(x, float) and x != x):
        return "–"
    return f"{x * 100:.{d}f}%" if pct else f"{x:.{d}f}"


def table(head, rows):
    md.append("| " + " | ".join(head) + " |")
    md.append("|" + "|".join(["---"] * len(head)) + "|")
    for r in rows:
        md.append("| " + " | ".join(str(c) for c in r) + " |")
    md.append("")


# ---------- dead-zone sensitivity (MX) ----------
P = L.load_panel(["date"])
dates = pd.DatetimeIndex(P["date"].values)
U = np.load(f"{OUT}/meta.npz")["U"]
dz = {}
for h in (5, 10, 20):
    Z = np.load(f"{OUT}/labels_h{h}.npz")
    for nm in ("r", "ex"):
        x = Z[nm].astype("float64")
        mk = U & np.isfinite(x)
        xs = x[mk]
        mon = pd.Series(xs).groupby(dates[mk].to_period("M"))
        for tau in (0, 25, 50, 100, 200):
            t = tau / 1e4
            pos = float((xs > t).mean())
            neg = float((xs < -t).mean())
            mpos = mon.apply(lambda s: (s > t).mean())
            dz[f"h{h}_{nm}_{tau}"] = {"pos": pos, "neg": neg, "flat": 1 - pos - neg, "mstd": float(mpos.std()),
                                     "mmin": float(mpos.min()), "mmax": float(mpos.max())}
save("s9_deadzone", dz)

LBL = ["ABS_dz", "MX_dz", "BR_dz", "SR_dz", "XR_raw_30", "XR_br_30", "XR_vn_30", "XR_vnx_30", "XR_neu_30", "XR_br50_30",
       "XR_raw_10", "XR_vn_10", "XR_neu_10"]


def get(h, nm):
    s = R[f"s2_events_h{h}"].get(nm)
    if s is None:
        s = R[f"s7_events_h{h}_extra"].get(nm)
    return s


for h in (5, 10, 20):
    md.append(f"### Event rates on U (elig_base & equity ISIN), h={h}")
    rows = []
    for nm in LBL:
        s = get(h, nm)
        if s is None:
            continue
        o = s["overall"]
        mp = s["monthly_pos"]
        rows.append([nm, f(o.get("1.0"), 1, True), f(o.get("0.0"), 1, True), f(o.get("-1.0"), 1, True),
                     f(mp["std"], 3), f(mp["min"], 3), f(mp["max"], 3), f(s["corr_monthly_pos_vs_mkt_ret"], 2),
                     f(s["eta2_date_pos"], 4), f(s["lag1_autocorr_pos"], 2), f(s["tilt"]["corr_beta_tilt_vs_mkt_window_ret"], 2),
                     f(s["tilt"]["corr_vol_tilt_vs_mkt_window_ret"], 2)])
    table(["label", "P(+1)", "P(0)", "P(-1)", "monthly P(+1) std", "min", "max", "corr(mon P+1, Nifty mon ret)",
           "eta2 date (+1)", "lag-1 AC (+1)", "corr(beta tilt, mkt win ret)", "corr(vol tilt, mkt win ret)"], rows)
    md.append(f"#### P(+1) by year, h={h}")
    yrs = ["2021", "2022", "2023", "2024", "2025", "2026"]
    table(["label"] + yrs + ["range"], [[nm] + [f(get(h, nm)["by_year_pos"].get(y), 3) for y in yrs] +
                                         [f(max(get(h, nm)["by_year_pos"].values()) - min(get(h, nm)["by_year_pos"].values()), 3)]
                                         for nm in LBL if get(h, nm)])
    md.append(f"#### P(+1) by regime (Nifty500 vs 200dma x 20d momentum) and liquidity tercile, h={h}")
    regs = ["bull_up20", "bull_dn20", "bear_up20", "bear_dn20"]
    table(["label"] + regs + ["liq T0 (low)", "liq T1", "liq T2 (high)"],
          [[nm] + [f(get(h, nm)["by_regime_pos"].get(g), 3) for g in regs] + [f(get(h, nm)["by_liq_pos"].get(t), 3) for t in ("0", "1", "2")]
           for nm in LBL if get(h, nm)])
    md.append(f"#### Key risk: absolute P&L of the +1 class (gross r = open[t+1] -> close[t+h]), h={h}")
    rows = []
    for nm in ["MX_dz", "BR_dz", "SR_dz", "XR_raw_30", "XR_vn_30", "XR_neu_30", "XR_raw_10", "XR_neu_10"]:
        s = get(h, nm)
        if s is None:
            continue
        c = s["coherence"]["1.0"]
        rr = [nm, f(c["all"]["p_abs_loss_gross"], 1, True), f(c["all"]["p_abs_loss_net50"], 1, True), f(c["all"]["mean_r_bps"], 0)]
        rr += [f(c["by_regime"][g]["p_abs_loss_gross"], 1, True) if g in c["by_regime"] else "–" for g in regs]
        rr += [f(c["by_year"][y]["p_abs_loss_gross"], 1, True) if y in c["by_year"] else "–" for y in yrs]
        cn = s["coherence"]["-1.0"]["all"]
        rr += [f(cn["p_abs_loss_gross"], 1, True), f(s["coherence"]["1.0"]["fno_only"]["p_abs_loss_gross"], 1, True)]
        rows.append(rr)
    table(["label", "P(r<=0 given +1)", "P(r<50bp given +1)", "mean r | +1 (bps)"] + [f"P(r<=0|+1) {g}" for g in regs] +
          [f"P(r<=0|+1) {y}" for y in yrs] + ["P(r>=0 given -1) (short loses)", "P(r<=0|+1) fno only"], rows)

md.append("### Composition tilt screen (dev 2021-2025 dates): corr over dates of (mean X of +1 minus -1) with Nifty window return")
rows = []
for h in (5, 10, 20):
    for nm, v in R["s3_tilt_screen"][f"h{h}"].items():
        d = v["dev"]
        rows.append([h, nm, f(d["corr_beta_tilt"], 2), f(d["beta_tilt_up"], 3), f(d["beta_tilt_dn"], 3), f(d["corr_vol_tilt"], 2),
                     f(d["vol_tilt_up_pct"], 2), f(d["vol_tilt_dn_pct"], 2), f(d["corr_size_tilt"], 2), f(v["spearman_vs_raw"], 2)])
table(["h", "construction", "corr beta-tilt", "beta tilt (mkt up)", "beta tilt (mkt down)", "corr vol-tilt",
       "vol tilt up (pp)", "vol tilt down (pp)", "corr size-tilt", "rank corr with raw"], rows)

md.append("### Dead-zone sensitivity (share of rows; monthly P(+1) std) for absolute r and market-excess ex")
rows = []
for h in (5, 10, 20):
    for nm in ("r", "ex"):
        for tau in (0, 25, 50, 100, 200):
            d = dz[f"h{h}_{nm}_{tau}"]
            rows.append([h, "absolute r" if nm == "r" else "excess r-r_mkt", tau, f(d["pos"], 1, True), f(d["flat"], 1, True),
                         f(d["neg"], 1, True), f(d["mstd"], 3), f(d["mmin"], 3), f(d["mmax"], 3)])
table(["h", "label", "tau bps", "P(+1)", "P(0)", "P(-1)", "monthly P(+1) std", "min", "max"], rows)

# ---------- learnability ----------
md.append("### Learnability (walk-forward OOS, mean daily cross-sectional metrics); t = non-overlapping (every h-th date)")
evs = {"h10": R["s5_eval_h10_R10_raw_R10_vn_R10_neu_ABS10_E_B10_mx"], "h5": R["s5_eval_h5_R5_neu"], "h20": R["s5_eval_h20_R20_neu"]}
rows = []
for hk, ev in evs.items():
    for nm, v in ev.items():
        for y in ("2023", "2024", "2025", "2026"):
            r = v["by_year"][y]
            rows.append([nm, y, f(r["ic_raw"], 3), f(r["ic_raw_t"], 1), f(r["ic_neu"], 3), f(r["ic_neu_t"], 1), f(r["ic_raw_fno"], 3),
                         f(r["xsauc_XR_raw_30_pos"], 3), f(r["xsauc_XR_raw_30_neg_inv"], 3), f(r["xsauc_XR_neu_30_pos"], 3),
                         f(r["xsauc_XR_neu_30_neg_inv"], 3), f(r["top_dec_rate_XR_neu_30"], 3), f(r["bot_dec_rate_XR_neu_30_neg"], 3),
                         f(r["xsauc_MX_dz_pos"], 3), f(r["pooled_auc_ABS_pos"], 3), f(r["top_minus_bottom_r_bps"], 0),
                         f(r["top_ex_bps"], 0), f(r["bottom_ex_bps"], 0)])
table(["model", "year", "IC vs raw/excess rank", "t", "IC vs neutral rank", "t", "IC raw (fno only)", "XS-AUC +1 raw30", "XS-AUC -1 raw30 (inv)",
       "XS-AUC +1 neu30", "XS-AUC -1 neu30 (inv)", "top-dec P(+1 neu30) (base .30)", "bot-dec P(-1 neu30) (base .30)",
       "XS-AUC MX_dz +1", "pooled AUC ABS +1", "top-bot decile r (bps)", "top dec excess (bps)", "bot dec excess (bps)"], rows)
md.append("#### Decile mean forward return r (bps, date-balanced) of OOS score")
rows = []
for hk, ev in evs.items():
    for nm, v in ev.items():
        for y in ("2023", "2024", "2025", "2026"):
            d = v["by_year"][y]["decile_mean_r_bps"]
            rows.append([nm, y] + [f(d[str(i)], 0) for i in range(10)])
table(["model", "year"] + [f"D{i}" for i in range(10)], rows)

# ---------- investability ----------
md.append("### Investability (lablib.portfolio_sim replica, verified exact). CAGR / sim-Sharpe / sharpe_adj / maxDD; dev = signals 2023-01-01..(2025-12-31 - h); hold = 2026-01-01..2026-09-10 (annualised)")
INV = [("s6_invest_h10_s5_k20_R10_raw_R10_vn_R10_neu_ABS10_E_B10_mx", "h10 s5 K20"), ("s6_invest_h10_s5_k50_R10_neu", "h10 s5 K50"),
       ("s6_invest_h5_s5_k20_R5_neu", "h5 s5 K20"), ("s6_invest_h20_s5_k20_R20_neu", "h20 s5 K20"),
       ("s6_invest_h20_s10_k20_R20_neu", "h20 s10 K20")]
rows = []
for key, cfg in INV:
    S = R[key]
    for w in ("full", "dev", "hold"):
        b = S["nifty500"][w]
        rows.append([cfg, "Nifty 500 (price)", w, f(b["cagr"], 1, True), f(b["sharpe"], 2), "–", f(b["max_dd"], 1, True), "–", "–"])
    for c in ("50", "80"):
        bb = S["baselines"][f"LO_random_{c}"]
        for w in ("full", "dev", "hold"):
            x = bb[w]
            rows.append([cfg, f"random LO {c}bps (10 seeds)", w, f(x["cagr"], 1, True) + f" (sd {x['cagr_sd'] * 100:.1f})", f(x["sharpe"], 2),
                         f(x["sharpe_adj"], 2), f(x["max_dd"], 1, True), f(x["hit_rate"], 3), f(x["mean_trade_net"] * 1e4, 0)])
    for nm in [k for k in S if k not in ("params", "verify_vs_lablib", "nifty500", "baselines")]:
        for strat in ("LO_50", "LO_80", "LO_reg_50", "LO_fno_50"):
            for w in ("full", "dev", "hold"):
                x = S[nm][strat][w]
                rows.append([cfg, f"{nm} {strat}", w, f(x["cagr"], 1, True), f(x["sharpe"], 2), f(x.get("sharpe_adj"), 2), f(x["max_dd"], 1, True),
                             f(x.get("hit_rate"), 3), f(x.get("mean_trade_net", np.nan) * 1e4, 0)])
table(["config", "strategy", "window", "CAGR", "Sharpe(sim)", "Sharpe adj", "maxDD", "hit", "mean trade net (bps)"], rows)

md.append("#### By-year returns (calendar year of signal; 2026 = Jan-Sep, not annualised), 50 bps")
rows = []
for key, cfg in INV:
    S = R[key]
    rows.append([cfg, "Nifty 500"] + [f(S["nifty500"]["full"]["by_year"].get(y), 1, True) for y in ("2023", "2024", "2025", "2026")])
    rows.append([cfg, "random LO"] + [f(S["baselines"]["LO_random_50"]["full"]["by_year"].get(y), 1, True) for y in ("2023", "2024", "2025", "2026")])
    for nm in [k for k in S if k not in ("params", "verify_vs_lablib", "nifty500", "baselines")]:
        for strat in ("LO_50", "LO_80", "LS_fno_50", "AVOID30_random_50"):
            if "by_year" in S[nm][strat]["full"]:
                rows.append([cfg, f"{nm} {strat}"] + [f(S[nm][strat]["full"]["by_year"].get(y), 1, True) for y in ("2023", "2024", "2025", "2026")])
table(["config", "strategy", "2023", "2024", "2025", "2026 YTD"], rows)

md.append("#### Long-short on fno_proxy (50/50 long top-K / short bottom-K, cost per leg), 'down'-side and avoid usage")
rows = []
for key, cfg in INV:
    S = R[key]
    for nm in [k for k in S if k not in ("params", "verify_vs_lablib", "nifty500", "baselines")]:
        for strat in ("LS_fno_0", "LS_fno_20", "LS_fno_50", "LS_fno_80", "SO_fno_50", "AVOID30_random_50"):
            x = S[nm][strat]
            rows.append([cfg, nm, strat] + [f(x[w]["cagr"], 1, True) + (f" ({x[w]['mean_cohort_spread_bps']:.0f}bp)" if "mean_cohort_spread_bps" in x[w] else "")
                                            for w in ("full", "dev", "hold")])
    for c in ("50", "80"):
        x = S["baselines"][f"LS_fno_random_{c}"]
        rows.append([cfg, "random", f"LS_fno_{c}"] + [f(x[w]["cagr"], 1, True) for w in ("full", "dev", "hold")])
        x = S["baselines"][f"LO_random_{c}"]
        rows.append([cfg, "random", f"LO_{c} (compare AVOID)"] + [f(x[w]["cagr"], 1, True) for w in ("full", "dev", "hold")])
table(["config", "score", "strategy", "full CAGR (mean cohort net bp)", "dev", "hold"], rows)

md.append("### Excess over random (same mask/dates, 10 seeds): mean per-cohort excess (bps), Newey-West t (all cohorts) and non-overlapping t")
rows = []
for nm, v in R["s8_final"].items():
    e = v["excess_vs_random_50"]
    rows.append([nm, f"h{v['h']} s{v['step']} K{v['K']}", f(e["dev"]["mean_excess_bps_per_cohort"], 0), f(e["dev"]["t_newey_west_all"], 2),
                 f(e["dev"]["t_nonoverlap"], 2), f(e["dev"]["share_cohorts_positive"], 2), f(e["hold"]["mean_excess_bps_per_cohort"], 0),
                 f(e["hold"]["t_newey_west_all"], 2), f(e["hold"]["share_cohorts_positive"], 2)] +
                [f(e["by_year_mean_excess_bps"].get(y), 0) for y in ("2023", "2024", "2025", "2026")])
table(["score", "config", "dev excess bp/cohort", "dev NW t", "dev non-overlap t", "dev share>0", "hold excess", "hold NW t", "hold share>0",
       "2023", "2024", "2025", "2026"], rows)
md.append("### Index-hedged long book (long top-K, short Nifty 500 same window, +10 bps hedge cost) vs same hedge on random picks; liq5 robustness")
rows = []
for nm, v in R["s8_final"].items():
    for c in ("50", "80"):
        hh = v[f"index_hedged_{c}"]
        rh = v[f"index_hedged_random_cagr_{c}"]
        rows.append([nm, c, *[f"{hh[w]['cagr'] * 100:.1f}% (rand {rh[w] * 100:.1f}%)" for w in ("full", "dev", "hold")],
                     f(hh["full"]["sharpe"], 2), f(hh["full"]["max_dd"], 1, True)])
table(["score", "cost", "hedged full CAGR", "dev", "hold", "Sharpe(sim) full", "maxDD full"], rows)
rows = []
for nm, v in R["s8_final"].items():
    for c in ("50", "80"):
        if f"liq5_LO_{c}" in v:
            l5 = v[f"liq5_LO_{c}"]
            rows.append([nm, c] + [f"{l5[w]['cagr'] * 100:.1f}% (rand {l5[w]['random_cagr'] * 100:.1f}%)" for w in ("full", "dev", "hold")])
table(["score (liq5 universe: 20d turnover >= Rs5cr)", "cost", "full", "dev", "hold"], rows)
rows = [[nm, f(v["pick_profile"]["median_turnover20_cr"], 1), f(v["pick_profile"]["p25_turnover20_cr"], 1), f(v["pick_profile"]["fno_share"], 2),
         f(v["pick_profile"]["liq5_share"], 2), f(v["pick_profile"]["universe_median_turnover20_cr"], 1)] for nm, v in R["s8_final"].items()]
table(["score", "pick median 20d turnover (Rs cr)", "p25", "fno share", "liq5 share", "universe median (Rs cr)"], rows)
open(f"{OUT}/tables_autogen.md", "w").write("\n".join(md))
print("written", len(md), "lines")

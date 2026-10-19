"""Markdown table builders for the R2_rel report (all numbers read from results.json)."""
import json
import os

import numpy as np

from common import OUT, RES

D = json.load(open(RES))


def pct(x, d=1, sign=False):
    if x is None or (isinstance(x, float) and x != x):
        return "n/a"
    return f"{x * 100:+.{d}f}%" if sign else f"{x * 100:.{d}f}%"


def num(x, d=2, sign=False):
    if x is None or (isinstance(x, float) and x != x):
        return "n/a"
    return f"{x:+.{d}f}" if sign else f"{x:.{d}f}"


def table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def sim_rec(sec, univ="liq2", K=20, step=5, cost=50, per="dev", q=None):
    for r in D.get(sec, []):
        c = r["cfg"]
        if c["univ"] == univ and c["step"] == step and c["cost_bps"] == cost and r["period"] == per:
            if q is None and c.get("top_k") == K and "select_quantile" not in c:
                return r
            if q is not None and c.get("select_quantile") is not None and abs(c["select_quantile"][0] - q[0]) < 1e-9 \
                    and abs(c["select_quantile"][1] - q[1]) < 1e-9:
                return r
    return None


def find_sim(tag, **kw):
    for g in ("full", "core", "avoid", "avoidc", "avoidcut", "quant"):
        r = sim_rec(f"s5_{g}_{tag}", **kw)
        if r is not None:
            return r
    return None


def t_construction():
    s = D["s1_label_build"]
    rows = []
    for h in (10, 15, 20):
        x = s[f"h{h}"]
        rows.append([h, f"{x['valid_rows']:,}", pct(x["valid_share_of_elig"]), int(x["median_names_per_date"]),
                     num(s[f"h{h}_neu_mean_xs_R2"], 3), num(s[f"h{h}_neumom_mean_xs_R2"], 3),
                     num(s[f"h{h}_size_mean_xs_R2"], 3), num(x["spearman_pct_neu_vs_none"], 3),
                     num(x["spearman_pct_neu_vs_size"], 3), num(x["spearman_pct_neu_vs_neumom"], 3)])
    return table(["h", "labelled elig rows", "share of elig_base", "median names/date", "xs R2 neu",
                  "xs R2 neu+mom", "xs R2 size", "rank corr neu vs none", "neu vs size", "neu vs neu+mom"], rows)


def t_events_c30():
    E = D["s2_events"]
    rows = []
    for h in (10, 15, 20):
        for nt in ("neu", "neumom", "size", "none"):
            o = E[f"h{h}_{nt}_C30"]
            lt = o["by_liq_tercile"]
            yrs = [v["1.0"] for v in o["by_year"].values()]
            rows.append([h, nt, pct(o["overall"]["1.0"]), f"{min(yrs) * 100:.1f}-{max(yrs) * 100:.1f}%",
                         num(o["monthly_pos"]["std"], 4),
                         f"{lt['0']['1.0'] * 100:.1f}/{lt['1']['1.0'] * 100:.1f}/{lt['2']['1.0'] * 100:.1f}",
                         f"{o['fno_subset']['1.0'] * 100:.1f}/{o['fno_subset']['-1.0'] * 100:.1f}",
                         f"{o['liq5_subset']['1.0'] * 100:.1f}/{o['liq5_subset']['-1.0'] * 100:.1f}",
                         num(o["corr_monthly_pos_vs_mkt_ret"], 2),
                         num(o.get("class_disagreement_vs_neu"), 3) if nt != "neu" else "-"])
    return table(["h", "neutraliser", "+1 share", "+1 share by year (min-max)", "monthly +1 std",
                  "+1 share by liquidity tercile (low/mid/high)", "fno_proxy +1/-1", "liq5 +1/-1",
                  "corr(monthly +1, Nifty month)", "class disagreement vs neu"], rows)


def t_coherence():
    E = D["s2_events"]
    rows = []
    for h in (10, 15, 20):
        for nt in ("neu", "neumom", "size", "none"):
            o = E[f"h{h}_{nt}_C30"]
            c = o["coherence"]
            by = c["1.0"]["p_net_pos_by_year"]
            mp = o["monthly_p_net_pos_given_pos"]
            rows.append([h, nt, f"{c['1.0']['mean_net_bps']:.0f} / {c['0.0']['mean_net_bps']:.0f} / "
                                f"{c['-1.0']['mean_net_bps']:.0f}",
                         f"{c['1.0']['mean_excess_vs_ew_bps']:.0f} / {c['-1.0']['mean_excess_vs_ew_bps']:.0f}",
                         pct(c["1.0"]["p_net_pos"]), f"{min(by.values()) * 100:.1f}-{max(by.values()) * 100:.1f}%",
                         f"{mp['min'] * 100:.1f}%", num(mp["corr_vs_mkt_ret"], 2), pct(c["-1.0"]["p_net_pos"]),
                         f"{o['xs_spread_pos_minus_neg_bps']['mean']:.0f}"])
    return table(["h", "neutraliser", "mean net bps +1 / 0 / -1 (50 bps cost)", "excess vs same-day EW bps +1 / -1",
                  "P(net>0 | +1)", "P(net>0|+1) by year (min-max)", "worst month P(net>0|+1)",
                  "corr(monthly P(net>0|+1), Nifty month)", "P(net>0 | -1)", "per-date +1 minus -1 spread bps"], rows)


def t_tilt():
    E = D["s2_events"]
    rows = []
    for h in (10, 20):
        for nt in ("neu", "neumom", "size", "none"):
            o = E[f"h{h}_{nt}_C30"]
            tl = o["composition_tilt"]
            p = o["persistence"]
            rows.append([h, nt] + [f"{tl[c]['mean_z']:+.3f} (up {tl[c]['mean_z_up_mkt']:+.2f} / dn "
                                   f"{tl[c]['mean_z_dn_mkt']:+.2f}; corr {tl[c]['corr_with_mkt_window_ret_dev']:+.2f})"
                                   for c in ("beta_60", "vol_20", "log_turn20", "mom_12_1")] +
                        [num(p["autocorr_lag1"], 3), num(p[[k for k in p if k.startswith("persistence")][0]], 3)])
    return table(["h", "neutraliser", "beta tilt z (+1 minus -1)", "vol_20 tilt", "log_turn20 tilt", "mom_12_1 tilt",
                  "label autocorr lag1", "corr(pct_t, pct_t+h)"], rows)


def t_rankcut():
    E = D["s2_events"]
    rows = []
    for h in (10, 20):
        for f in ("C20", "C30", "C33", "T30", "B30"):
            o = E[f"h{h}_neu_{f}"]
            c = o["coherence"]
            ks = sorted(c.keys(), key=float, reverse=True)
            rows.append([h, f, " / ".join(pct(o["overall"][k]) for k in ks),
                         " / ".join(f"{c[k]['mean_net_bps']:.0f}" for k in ks),
                         " / ".join(pct(c[k]["p_net_pos"]) for k in ks),
                         f"{o['xs_spread_pos_minus_neg_bps']['mean']:.0f}"])
    return table(["h", "form (neu)", "class shares (high->low class)", "mean net bps per class",
                  "P(net>0) per class", "spread top-class minus bottom-class bps"], rows)


def t_regime():
    o = D["s2_events"]["h20_neu_C30"]
    c = o["coherence"]
    rows = []
    for rg in sorted(o["by_regime"]):
        rows.append([rg, pct(o["by_regime"][rg]["1.0"]), pct(o["by_regime"][rg]["-1.0"]),
                     pct(c["1.0"]["p_net_pos_by_regime"][rg]), pct(c["0.0"]["p_net_pos_by_regime"][rg]),
                     pct(c["-1.0"]["p_net_pos_by_regime"][rg])])
    yr = []
    for y in sorted(o["by_year"]):
        yr.append([y, pct(o["by_year"][y]["1.0"]), pct(o["by_year"][y]["-1.0"]),
                   pct(c["1.0"]["p_net_pos_by_year"][y]), f"{c['1.0']['mean_net_bps_by_year'][y]:.0f}",
                   f"{c['-1.0']['mean_net_bps_by_year'][y]:.0f}"])
    return table(["regime at t (N500 vs 200dma, 20d mom)", "+1 share", "-1 share", "P(net>0 | +1)", "P(net>0 | 0)",
                  "P(net>0 | -1)"], rows), table(["year", "+1 share", "-1 share", "P(net>0 | +1)",
                                                  "mean net bps +1", "mean net bps -1"], yr)


MODELS = ["h10_neu_RANK", "h15_neu_RANK", "h20_neu_RANK", "h20_neumom_RANK", "h20_size_RANK", "h20_none_RANK",
          "h20_neu_C30", "h20_neu_C20", "h20_neu_C33", "h20_neu_T30", "h20_neu_T20", "h20_neu_T10", "h20_neu_T50",
          "h20_neumom_T30", "h20_neumom_C20", "h20_neu_B30", "h10_neu_T30", "h15_neu_T30", "h10_neu_B30", "h15_neu_B30",
          "h10_neu_C30", "h10_neumom_RANK", "h10_none_RANK"]


def avail(prefix):
    return [m for m in MODELS if f"{prefix}{m}" in D]


def t_xs():
    rows = []
    for m in avail("s4_xs_"):
        x = D[f"s4_xs_{m}"]
        by = x["by_year"]
        rows.append([m, f"{num(x['dev_ic_own_mean'], 3)} ({num(x.get('dev_ic_own_t'), 1)})",
                     f"{num(x['dev_ic_neu20_mean'], 3)} ({num(x.get('dev_ic_neu20_t'), 1)})",
                     f"{num(x['dev_ic_raw_mean'], 3)} ({num(x.get('dev_ic_raw_t'), 1)})",
                     f"{num(x['dev_auc_top30_mean'], 3)} ({num(x.get('dev_auc_top30_t'), 1)})",
                     f"{num(x['dev_auc_bot30_mean'], 3)} ({num(x.get('dev_auc_bot30_t'), 1)})",
                     f"{num(x['holdout_ic_own_mean'], 3)} ({num(x.get('holdout_ic_own_t'), 1)})",
                     f"{num(x['holdout_ic_neu20_mean'], 3)}", f"{num(x['holdout_ic_raw_mean'], 3)}",
                     f"{num(x['holdout_auc_top30_mean'], 3)}", f"{num(x['holdout_auc_bot30_mean'], 3)}",
                     " / ".join(num(by[y]["ic_own"], 3) for y in ("2023", "2024", "2025", "2026") if y in by)])
    return table(["model", "dev IC own (t)", "dev IC vs XR_neu20 (t)", "dev IC vs raw r_h (t)", "dev AUC top30 (t)",
                  "dev AUC bottom30 (t)", "2026 IC own (t)", "2026 IC XR_neu20", "2026 IC raw", "2026 AUC top30",
                  "2026 AUC bottom30", "IC own by year 23/24/25/26"], rows)


def phase(m, cfg, per):
    p = D.get(f"s7_phase_{m}", {}).get(f"{cfg}_{per}")
    return p


def t_invest_headline():
    rows = []
    for m in avail("s3_wf_"):
        h = int(m.split("_")[0][1:])
        r = [find_sim(m, K=20, step=5, cost=50, per=p) for p in ("dev", "hold")]
        r80 = [find_sim(m, K=20, step=5, cost=80, per=p) for p in ("dev", "hold")]
        ph = [phase(m, "K20_s5", p) for p in ("dev", "hold")]
        if r[0] is None:
            continue
        rows.append([m, pct(r[0]["cagr"]), pct(r[0]["random"]["cagr_mean"]), pct(r[0]["excess_cagr_vs_random"], sign=True),
                     num(r[0]["excess_daily_nw_t"]),
                     (f"{pct(ph[0]['phaseavg_excess_ann'], sign=True)} ({num(ph[0]['phaseavg_nw_t'])})" if ph[0] else "n/a"),
                     pct(r[0]["max_dd"]), pct(r80[0]["cagr"]) if r80[0] else "n/a",
                     pct(r[1]["cagr"]), pct(r[1]["random"]["cagr_mean"]), pct(r[1]["excess_cagr_vs_random"], sign=True),
                     num(r[1]["excess_daily_nw_t"]),
                     (f"{pct(ph[1]['phaseavg_excess_ann'], sign=True)} ({num(ph[1]['phaseavg_nw_t'])})" if ph[1] else "n/a"),
                     pct(r80[1]["cagr"]) if r80[1] else "n/a"])
    return table(["model (K20, step 5, liq2)", "dev CAGR 50bp", "dev random", "dev excess", "dev NW t",
                  "dev phase-avg excess/yr (t)", "dev maxDD", "dev CAGR 80bp", "2026 CAGR 50bp", "2026 random",
                  "2026 excess", "2026 NW t", "2026 phase-avg excess/yr (t)", "2026 CAGR 80bp"], rows)


def t_horizon_cost():
    rows = []
    for m in ("h10_neu_RANK", "h15_neu_RANK", "h20_neu_RANK"):
        for cost in (50, 80, 130):
            for step in (5, 10):
                r = [sim_rec(f"s5_full_{m}", K=20, step=step, cost=cost, per=p) for p in ("dev", "hold")]
                if r[0] is None:
                    continue
                rows.append([m, cost, step, pct(r[0]["cagr"]), pct(r[0]["random"]["cagr_mean"]),
                             pct(r[0]["excess_cagr_vs_random"], sign=True), num(r[0]["excess_daily_nw_t"]),
                             pct(r[0]["mean_trade_net"], 2), pct(r[1]["cagr"]), pct(r[1]["random"]["cagr_mean"]),
                             pct(r[1]["excess_cagr_vs_random"], sign=True), num(r[1]["excess_daily_nw_t"])])
    return table(["model", "cost bps", "step", "dev CAGR", "dev random", "dev excess", "dev t", "dev mean trade net",
                  "2026 CAGR", "2026 random", "2026 excess", "2026 t"], rows)


def t_k_step(m, univ="liq2"):
    rows = []
    for K in (10, 20, 30, 50):
        for step in (5, 10):
            r = [sim_rec(f"s5_full_{m}", univ=univ, K=K, step=step, cost=50, per=p) for p in ("dev", "hold")]
            r80 = sim_rec(f"s5_full_{m}", univ=univ, K=K, step=step, cost=80, per="dev")
            if r[0] is None:
                continue
            rows.append([K, step, pct(r[0]["cagr"]), pct(r[0]["excess_cagr_vs_random"], sign=True),
                         num(r[0]["excess_daily_nw_t"]), pct(r[0]["max_dd"]), pct(r[0]["hit_rate"]),
                         pct(r80["cagr"]) if r80 else "n/a",
                         pct(r[1]["cagr"]), pct(r[1]["excess_cagr_vs_random"], sign=True),
                         num(r[1]["excess_daily_nw_t"])])
    return table(["K", "step", "dev CAGR", "dev excess", "dev t", "dev maxDD", "dev hit", "dev CAGR 80bp",
                  "2026 CAGR", "2026 excess", "2026 t"], rows)


def t_liq():
    rows = []
    for m in avail("s3_wf_"):
        r2 = [find_sim(m, univ="liq2", K=20, step=5, cost=50, per=p) for p in ("dev", "hold")]
        r5 = [find_sim(m, univ="liq5", K=20, step=5, cost=50, per=p) for p in ("dev", "hold")]
        if r2[0] is None or r5[0] is None:
            continue
        rows.append([m, pct(r2[0]["excess_cagr_vs_random"], sign=True), num(r2[0]["excess_daily_nw_t"]),
                     pct(r5[0]["cagr"]), pct(r5[0]["random"]["cagr_mean"]), pct(r5[0]["excess_cagr_vs_random"], sign=True),
                     num(r5[0]["excess_daily_nw_t"]), pct(r2[1]["excess_cagr_vs_random"], sign=True),
                     pct(r5[1]["excess_cagr_vs_random"], sign=True), num(r5[1]["excess_daily_nw_t"])])
    return table(["model (K20 s5 50bp)", "liq2 dev excess", "liq2 dev t", "liq5 dev CAGR", "liq5 dev random",
                  "liq5 dev excess", "liq5 dev t", "liq2 2026 excess", "liq5 2026 excess", "liq5 2026 t"], rows)


def t_avoid():
    rows = []
    for m in avail("s3_wf_"):
        r = [find_sim(m, K=None, step=5, cost=50, per=p, q=(0.3, 1.0)) for p in ("dev", "hold")]
        ph = [phase(m, "avoid30_s5", p) for p in ("dev", "hold")]
        if r[0] is None:
            continue
        rows.append([m, pct(r[0]["cagr"]), pct(r[0]["random"]["cagr_mean"]), pct(r[0]["ew"]["cagr"]),
                     pct(r[0]["excess_cagr_vs_random"], sign=True), num(r[0]["excess_daily_nw_t"]),
                     num(r[0]["excess_vs_ew_nw_t"]),
                     (f"{pct(ph[0]['phaseavg_excess_ann'], sign=True)} ({num(ph[0]['phaseavg_nw_t'])})" if ph[0] else "n/a"),
                     pct(r[0]["max_dd"]), pct(r[0]["ew"]["max_dd"]),
                     pct(r[1]["cagr"]), pct(r[1]["ew"]["cagr"]), pct(r[1]["excess_cagr_vs_random"], sign=True),
                     num(r[1]["excess_daily_nw_t"]),
                     (f"{pct(ph[1]['phaseavg_excess_ann'], sign=True)} ({num(ph[1]['phaseavg_nw_t'])})" if ph[1] else "n/a")])
    return table(["model: EW all minus model bottom 30% (step 5, 50bp)", "dev CAGR", "dev random-70%", "dev universe EW",
                  "dev excess vs random", "t vs random", "t vs EW", "dev phase-avg (t)", "dev maxDD", "EW maxDD",
                  "2026 CAGR", "2026 EW", "2026 excess", "2026 t", "2026 phase-avg (t)"], rows)


def t_avoid_cost():
    rows = []
    for m in ("h10_neu_RANK", "h15_neu_RANK", "h20_neu_RANK", "h20_neumom_RANK", "h20_neu_T30"):
        for univ in ("liq2", "liq5"):
            for cost in (50, 80, 130):
                r = [sim_rec(f"s5_avoid_{m}", univ=univ, step=5, cost=cost, per=p, q=(0.3, 1.0)) for p in ("dev", "hold")]
                if r[0] is None:
                    continue
                rows.append([m, univ, cost, pct(r[0]["cagr"]), pct(r[0]["ew"]["cagr"]),
                             pct(r[0]["excess_cagr_vs_random"], sign=True), num(r[0]["excess_daily_nw_t"]),
                             pct(r[1]["cagr"]), pct(r[1]["ew"]["cagr"]), pct(r[1]["excess_cagr_vs_random"], sign=True),
                             num(r[1]["excess_daily_nw_t"])])
    return table(["model", "universe", "cost", "dev CAGR", "dev EW", "dev excess", "dev t", "2026 CAGR", "2026 EW",
                  "2026 excess", "2026 t"], rows)


def t_avoidcut():
    rows = []
    for m in avail("s5_avoidcut_"):
        for q in (0.1, 0.2, 0.3, 0.5):
            r = [sim_rec(f"s5_avoidcut_{m}", step=5, cost=50, per=p, q=(q, 1.0)) for p in ("dev", "hold")]
            if r[0] is None:
                continue
            rows.append([m, f"drop bottom {int(q * 100)}%", pct(r[0]["excess_cagr_vs_random"], sign=True),
                         num(r[0]["excess_daily_nw_t"]), num(r[0]["excess_vs_ew_nw_t"]),
                         pct(r[1]["excess_cagr_vs_random"], sign=True), num(r[1]["excess_daily_nw_t"])])
    return table(["model", "avoid cut", "dev excess vs random", "dev t", "dev t vs EW", "2026 excess", "2026 t"], rows)


def t_quant():
    rows = []
    for m in avail("s5_quant_"):
        for q in ((0.9, 1.0), (0.8, 1.0), (0.7, 1.0)):
            r = [sim_rec(f"s5_quant_{m}", step=5, cost=50, per=p, q=q) for p in ("dev", "hold")]
            if r[0] is None:
                continue
            rows.append([m, f"top {int(round((1 - q[0]) * 100))}% EW", pct(r[0]["cagr"]),
                         pct(r[0]["excess_cagr_vs_random"], sign=True), num(r[0]["excess_daily_nw_t"]),
                         pct(r[0]["max_dd"]), pct(r[1]["cagr"]), pct(r[1]["excess_cagr_vs_random"], sign=True),
                         num(r[1]["excess_daily_nw_t"])])
    return table(["model", "book", "dev CAGR", "dev excess vs random", "dev t", "dev maxDD", "2026 CAGR",
                  "2026 excess", "2026 t"], rows)


def t_xh():
    x = D["s6_cross_horizon"]
    rows = []
    for tr in (10, 15, 20):
        row = [f"trained h={tr}"]
        for hh in (10, 15, 20):
            a = x[f"train{tr}_hold{hh}_s5_dev"]
            b = x[f"train{tr}_hold{hh}_s5_hold"]
            row.append(f"{pct(a['cagr'])} / {pct(a['excess_cagr'], sign=True)} (t {a['nw_t']:.2f}) | 2026 "
                       f"{pct(b['excess_cagr'], sign=True)} (t {b['nw_t']:.2f})")
        rows.append(row)
    return table(["score \\ held for", "h=10: dev CAGR / excess (t) / 2026 excess", "h=15", "h=20"], rows)


def t_phase():
    rows = []
    for m in avail("s7_phase_"):
        for cfg in ("K20_s5", "K20_s10", "K50_s10", "avoid30_s5"):
            a = phase(m, cfg, "dev")
            b = phase(m, cfg, "hold")
            if a is None:
                continue
            rows.append([m, cfg, a["n_phases"],
                         f"{pct(a['phase_excess_min'], sign=True)} .. {pct(a['phase_excess_max'], sign=True)}",
                         f"{pct(a['phaseavg_excess_ann'], sign=True)} ({num(a['phaseavg_nw_t'])})",
                         f"{pct(b['phase_excess_min'], sign=True)} .. {pct(b['phase_excess_max'], sign=True)}",
                         pct(b["share_phases_positive"], 0),
                         f"{pct(b['phaseavg_excess_ann'], sign=True)} ({num(b['phaseavg_nw_t'])})",
                         pct(b["phaseavg_cagr"]), pct(b["phaseavg_random_cagr"])])
    return table(["model", "book", "phases", "dev excess range over phases", "dev phase-avg excess/yr (t)",
                  "2026 excess range", "2026 share phases > 0", "2026 phase-avg excess/yr (t)", "2026 phase-avg CAGR",
                  "2026 phase-avg random"], rows)


def t_luck():
    L_ = D["s6_luck"]
    rows = []
    for k in ("h10_dev", "h10_hold", "h15_dev", "h15_hold", "h20_dev", "h20_hold"):
        x = L_[k]
        rows.append([k, pct(x["random5_cagr_mean"]), pct(x["iid40_cagr_sd"]), pct(x["iid40_cagr_p95"]),
                     pct(x["persistent40_excess_sd"]), pct(x["persistent40_excess_p95"], sign=True),
                     pct(x["persistent40_excess_max"], sign=True), num(x["persistent40_nwt_sd"]),
                     num(x["persistent40_nwt_p95"]), num(x["persistent40_nwt_max"])])
    out = table(["h / period", "random CAGR (5 seeds)", "iid random sd (40)", "iid p95", "constant-tilt excess sd",
                 "constant-tilt excess p95", "max", "constant-tilt NW t sd", "NW t p95", "NW t max"], rows)
    rows2 = []
    for k, x in D.items():
        if not k.startswith("s6b_matched_null_"):
            continue
        for per in ("dev", "hold"):
            y = x[per]
            rows2.append([k.replace("s6b_matched_null_", ""), per, f"w={x['w']:.2f}, rho={x['rho_daily']:.3f}",
                          pct(y["model_excess"], sign=True), num(y["model_nw_t"]), pct(y["null_excess_sd"]),
                          pct(y["null_excess_p95"], sign=True), pct(y["null_excess_max"], sign=True),
                          num(y["null_t_sd"]), num(y["null_t_p95"]), pct(y["model_excess_pctile_in_null"], 0),
                          num(y["model_excess_z_vs_null"], 1)])
    out2 = table(["model / book", "period", "null persistence (fitted)", "model excess", "model NW t", "null excess sd",
                  "null p95", "null max", "null NW t sd", "null t p95", "model percentile in null", "model z vs null"],
                 rows2)
    return out, out2


def t_attrib():
    A = D["s9_attrib"]
    rows = []
    keep_avoid = ("h20_neu_RANK_", "h20_neumom_RANK_", "h20_neu_T30_", "h20_neumom_T30_", "h20_neumom_C20_",
                  "h20_neu_B30_")
    for k, v in A.items():
        if k.startswith("factor_"):
            continue
        if "avoid" in k and not k.startswith(keep_avoid):
            continue
        rows.append([k, pct(v["excess_ann"], sign=True), pct(v["alpha_ann"], sign=True), num(v["alpha_nw_t"]),
                     num(v["r2"]), ", ".join(f"{c} {v['betas'][c]:+.2f} ({v['beta_t'][c]:+.1f})"
                                             for c in v["betas"])])
    f = []
    for per in ("dev", "hold"):
        x = A[f"factor_ls_ann_{per}"]
        f.append([per] + [pct(x[c], sign=True) for c in x])
    return table(["book", "excess vs random /yr", "alpha /yr", "alpha NW t", "R2", "factor betas (t)"], rows), \
        table(["period"] + list(A["factor_ls_ann_dev"].keys()), f)


def t_ref():
    R = D["s6_ref_sorts_h20"]
    names = sorted({k.rsplit("_", 3)[0] for k in R})
    rows = []
    for n in names:
        row = [n]
        for mode in ("long_s5", "long_s10", "avoid_s5"):
            a, b = R.get(f"{n}_{mode}_dev"), R.get(f"{n}_{mode}_hold")
            row.append(f"{pct(a['excess_cagr'], sign=True)} ({a['nw_t']:.2f}) / {pct(b['excess_cagr'], sign=True)} "
                       f"({b['nw_t']:.2f})" if a else "n/a")
        rows.append(row)
    return table(["characteristic sort (h=20, 50bp)", "long top-20 step 5: dev (t) / 2026 (t)", "long top-20 step 10",
                  "avoid: drop the 30% with the LOWEST score (e.g. high_vol20 drops low-vol names), step 5"], rows)


def t_loadings():
    Lo = D["s8_loadings"]
    rows = []
    for m, v in Lo.items():
        if m == "pairwise_score_spearman":
            continue
        s = v["spearman"]
        tp = v["top20_profile"]
        rows.append([m] + [num(s[c]["dev"], 2) for c in ("vol_20", "beta_60", "log_turn20", "mom_12_1", "mom_5",
                                                          "idio_vol_60", "dist_sma200", "deliv_pct")] +
                    [f"{tp['dev']['vol_20']:.2f} / {tp['dev']['log_turn20']:.2f} / {tp['dev']['mom_12_1']:.2f}",
                     f"{tp['dev']['fno_share'] * 100:.0f}% / {tp['dev']['liq5_share'] * 100:.0f}%"])
    return table(["model", "rho vol_20", "beta_60", "log_turn20", "mom_12_1", "mom_5", "idio_vol_60", "dist_sma200",
                  "deliv_pct", "top-20 pick pctile vol/turnover/mom12-1 (dev)", "top-20 fno / liq5 share (dev)"], rows)


def t_precision(models=("h20_neumom_RANK", "h20_neumom_C20", "h20_neumom_T30", "h20_neu_RANK", "h20_neu_T30",
                         "h20_neu_B30", "h20_none_RANK", "h10_neu_RANK")):
    Pz = D.get("s11_precision", {})
    rows = []
    for m in models:
        if m not in Pz:
            continue
        v = Pz[m]
        for y in sorted(v):
            x = v[y]
            rows.append([m, y, pct(x["top20_p_plus"]), pct(x["top20_p_minus"]), pct(x["top20_hit"]),
                         pct(x["all_hit"]), f"{x['top20_mean_net_bps']:.0f}", f"{x['all_mean_net_bps']:.0f}",
                         pct(x["bot30_p_minus"]), f"{x['bot30_mean_net_bps']:.0f}"])
    return table(["model", "year", "top-20 in +1 (base 30%)", "top-20 in -1 (base 30%)", "top-20 hit (net>0)",
                  "all-names hit", "top-20 mean net bps", "all mean net bps", "bottom-30% in -1 (base 30%)",
                  "bottom-30% mean net bps"], rows)


def t_by_year():
    rows = []
    for m in avail("s3_wf_"):
        r = [find_sim(m, K=20, step=5, cost=50, per=p) for p in ("dev", "hold")]
        if r[0] is None:
            continue
        by, rb = r[0]["by_year"], r[0]["random"]["by_year_mean"]
        cells = []
        for y in ("2023", "2024", "2025"):
            cells.append(f"{pct(by[y])} vs {pct(rb[y])} ({pct(by[y] - rb[y], sign=True)})")
        b2, r2 = r[1]["by_year"], r[1]["random"]["by_year_mean"]
        cells.append(f"{pct(b2['2026'])} vs {pct(r2['2026'])} ({pct(b2['2026'] - r2['2026'], sign=True)})")
        rows.append([m] + cells)
    return table(["model (K20 s5 50bp)", "2023 strat vs random (diff)", "2024", "2025", "2026 YTD (holdout)"], rows)


def dev_metrics(m):
    """Dev-only selection metrics (no 2026 data used)."""
    out = {}
    r = find_sim(m, K=20, step=5, cost=50, per="dev")
    out["t_K20s5"] = r["excess_daily_nw_t"] if r else np.nan
    ph = phase(m, "K20_s5", "dev")
    out["t_phase_K20s5"] = ph["phaseavg_nw_t"] if ph else np.nan
    ph = phase(m, "K20_s10", "dev")
    out["t_phase_K20s10"] = ph["phaseavg_nw_t"] if ph else np.nan
    ts = [x["excess_daily_nw_t"] for x in D.get(f"s5_full_{m}", []) if x["period"] == "dev"
          and x["cfg"]["univ"] == "liq2" and x["cfg"]["cost_bps"] == 50]
    out["t_grid_mean"] = float(np.mean(ts)) if ts else np.nan
    a = D.get("s9_attrib", {}).get(f"{m}_K20_s5_dev")
    out["alpha_t"] = a["alpha_nw_t"] if a else np.nan
    ph = phase(m, "avoid30_s5", "dev")
    out["t_phase_avoid"] = ph["phaseavg_nw_t"] if ph else np.nan
    x = D.get(f"s4_xs_{m}")
    out["ic_neu20_t"] = x.get("dev_ic_neu20_t", np.nan) if x else np.nan
    r80 = find_sim(m, K=20, step=5, cost=80, per="dev")
    out["cagr80"] = r80["cagr"] if r80 else np.nan
    yrs = r["by_year"] if r else {}
    ry = r["random"]["by_year_mean"] if r else {}
    out["min_year_excess"] = float(min(yrs[y] - ry[y] for y in ("2023", "2024", "2025"))) if r else np.nan
    return out


SEL_KEYS = ["t_K20s5", "t_phase_K20s5", "t_phase_K20s10", "t_grid_mean", "alpha_t", "t_phase_avoid", "ic_neu20_t"]


def t_selection(models):
    import pandas as pd
    M = pd.DataFrame({m: dev_metrics(m) for m in models}).T
    R = M[SEL_KEYS].rank(ascending=False)
    M["mean_rank"] = R.mean(1)
    M = M.sort_values("mean_rank")
    rows = []
    for m, x in M.iterrows():
        rows.append([m] + [num(x[k]) for k in SEL_KEYS] + [pct(x["cagr80"]), pct(x["min_year_excess"], sign=True),
                                                         num(x["mean_rank"], 1)])
    return table(["model (h=20)", "S.compare t K20 s5", "phase-avg t K20 s5", "phase-avg t K20 s10",
                  "mean t over K x step grid", "factor-alpha t", "avoid30 phase-avg t", "IC t vs XR_neu20",
                  "dev CAGR 80bp", "worst dev-year excess", "mean rank (lower=better)"], rows), M


def t_holdout_exam(models):
    rows = []
    for m in models:
        out = [m]
        for per in ("dev", "hold"):
            r = find_sim(m, K=20, step=5, cost=50, per=per)
            r80 = find_sim(m, K=20, step=5, cost=80, per=per)
            p = phase(m, "K20_s5", per)
            a = phase(m, "avoid30_s5", per)
            out += [pct(r["cagr"]), pct(r80["cagr"]) if r80 else "n/a",
                    f"{pct(p['phaseavg_cagr'])} vs {pct(p['phaseavg_random_cagr'])}",
                    f"{pct(p['phaseavg_excess_ann'], sign=True)} ({num(p['phaseavg_nw_t'])})",
                    f"{pct(a['phaseavg_excess_ann'], sign=True)} ({num(a['phaseavg_nw_t'])})"]
        at = D.get("s9_attrib", {}).get(f"{m}_K20_s5_hold")
        out.append(f"{pct(at['alpha_ann'], sign=True)} ({num(at['alpha_nw_t'])})" if at else "n/a")
        rows.append(out)
    return table(["model", "dev CAGR 50bp", "dev CAGR 80bp", "dev phase-avg CAGR vs random", "dev phase-avg excess (t)",
                  "dev avoid30 phase-avg (t)", "2026 CAGR 50bp", "2026 CAGR 80bp", "2026 phase-avg CAGR vs random",
                  "2026 phase-avg excess (t)", "2026 avoid30 phase-avg (t)", "2026 factor alpha (t)"], rows)

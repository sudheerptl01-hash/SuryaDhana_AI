#!/usr/bin/env python3
"""Stage 11: compact tables for REPORT.md (report_tables.md) straight from results.json."""
import json

from common import OUT

R = json.load(open(f"{OUT}/results.json"))
E = R["s2_event_rates"]
M = ["TSA_T5", "TSX_T5", "MQ_vol1.0", "RA10", "FX10_pm50", "FX20_pm50"]
md = []


def p(x, sign=True, nd=1):
    if x is None:
        return "–"
    return f"{x * 100:+.{nd}f}%" if sign else f"{x * 100:.{nd}f}%"


def n(x, nd=3, sign=False):
    if x is None:
        return "–"
    return f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}"


def table(head, rows):
    md.append("| " + " | ".join(head) + " |")
    md.append("|" + "|".join(["---"] * len(head)) + "|")
    for r in rows:
        md.append("| " + " | ".join(str(x) for x in r) + " |")
    md.append("")


md.append("## CT2 event rates\n")
rows = []
for k, e in E.items():
    if k.endswith("_nofloor"):
        continue
    rows.append([k, p(e["overall"].get("-1.0"), False), p(e["overall"].get("0.0"), False), p(e["overall"].get("1.0"), False),
                 p(e["monthly_pos"]["std"], False), f"{e['monthly_pos']['min'] * 100:.0f}–{e['monthly_pos']['max'] * 100:.0f}%",
                 n(e.get("corr_pos_mkt_dev"), 2, True), n(e.get("corr_pos_mkt_2026"), 2, True),
                 f"{e['fno_overall']['1'] * 100:.1f} / {e['fno_overall']['-1'] * 100:.1f}"])
table(["label", "P(-1)", "P(0)", "P(+1)", "monthly P(+1) sd", "monthly P(+1) range", "corr(mo P(+1), N500 ret) dev",
       "same, 2026", "F&O P(+1)/P(-1) %"], rows)

md.append("## CT7 learnability summary\n")
rows = []
for m in M:
    L = R[f"s4_{m}"]["learn"]
    W = R[f"s3_wf_{m}"]
    rows.append([m, f"{W['mean_auc_up']:.3f} / {W['mean_auc_down_inverted']:.3f}",
                 f"{L['xs_auc_up_dev']:.3f} (t {L['xs_auc_up_t_dev']:.1f})", f"{L['xs_auc_up_by_year']['2026']:.3f}",
                 f"{L['xs_auc_down_dev']:.3f}", f"{L['xs_auc_down_by_year']['2026']:.3f}",
                 f"{L['ic_r10_dev']:+.3f} (t {L['ic_r10_t_dev']:.1f})", f"{L['ic_r10_2026']:+.3f} (t {L['ic_r10_t_2026']:.1f})",
                 f"{L['ic_r20_dev']:+.3f} (t {L['ic_r20_t_dev']:.1f})", f"{L['ic_r20_2026']:+.3f}",
                 f"{L['top_dec_ex_r10_bps_dev']:+.0f} / {L['bot_dec_ex_r10_bps_dev']:+.0f}",
                 f"{L['top_dec_ex_r10_bps_by_year']['2026']:+.0f} / {L['bot_dec_ex_r10_bps_by_year']['2026']:+.0f}"])
table(["model (label)", "pooled AUC up/down (4 folds)", "XS-AUC up dev", "XS-AUC up 2026", "XS-AUC down dev",
       "XS-AUC down 2026", "IC r10 dev", "IC r10 2026", "IC r20 dev", "IC r20 2026", "top/bot decile r10 bp dev",
       "top/bot decile r10 bp 2026"], rows)

md.append("## CT8 IC by year + paired difference vs FX20 control\n")
rows = []
C = R["s6_compare"]["ic_diff"]
for m in M:
    L = R[f"s4_{m}"]["learn"]
    by = L["ic_r10_by_year"]
    d = C.get(f"r10|{m}-FX20_pm50")
    d20 = C.get(f"r20|{m}-FX20_pm50")
    rows.append([m, *[f"{by[y]:+.3f}" for y in ("2023", "2024", "2025", "2026")],
                 f"{d['dev']['mean_diff']:+.4f} (t {d['dev']['t_nonoverlap']:.1f})" if d else "control",
                 f"{d['2026']['mean_diff']:+.4f} (t {d['2026']['t_nonoverlap']:.1f})" if d else "–",
                 f"{d20['dev']['mean_diff']:+.4f} (t {d20['dev']['t_nonoverlap']:.1f})" if d20 else "control",
                 f"{R['s6_compare']['score_corr_dev'].get(f'FX20_pm50|{m}', R['s6_compare']['score_corr_dev'].get(f'{m}|FX20_pm50', 1.0)):.2f}"])
table(["model", "IC r10 2023", "2024", "2025", "2026", "ΔIC r10 vs FX20 dev", "ΔIC r10 vs FX20 2026", "ΔIC r20 vs FX20 dev",
       "score corr with FX20 model"], rows)

md.append("## CT9 investability compact (long top-20 / 5 days, eq universe)\n")
RD = R["s4_RANDOM"]["avg"]
rows = []
for m in M + ["RANDOM"]:
    src = RD if m == "RANDOM" else R[f"s4_{m}"]["long"]
    f = lambda k: src[k]  # noqa: E731
    by = f("fixed10_c50_full")["by_year"]
    rows.append([m + (" (5 seeds)" if m == "RANDOM" else ""),
                 p(f("fixed10_c50_dev")["cagr"]), p(f("fixed10_c50_hold2026")["cagr"]), p(f("fixed10_c50_full")["cagr"]),
                 f"{f('fixed10_c50_full')['sharpe']:.2f} / {f('fixed10_c50_full')['sharpe_rho_adj']:.2f}",
                 p(f("fixed10_c50_full")["max_dd"]), p(f("fixed10_c50_full")["hit_rate"], False),
                 f"{f('fixed10_c50_full')['mean_trade_net'] * 1e4:+.0f}",
                 p(f("fixed10_c80_dev")["cagr"]), p(f("fixed10_c80_hold2026")["cagr"]),
                 p(f("fixed20_c50_dev")["cagr"]), p(f("fixed20_c50_hold2026")["cagr"]), p(f("fixed20_c50_full")["cagr"]),
                 p(f("fixed20_c80_dev")["cagr"]), p(f("fixed20_c80_hold2026")["cagr"]),
                 " ".join(f"{y[2:]}:{v * 100:+.0f}" for y, v in by.items())])
bm = R["s4_RANDOM"]["nifty500"]
rows.append(["Nifty 500 (price idx)", p(bm["dev"]["cagr"]), p(bm["hold2026"]["cagr"]), p(bm["full"]["cagr"]),
             f"{bm['full']['sharpe']:.2f} (daily)", p(bm["full"]["max_dd"]), "–", "–", "–", "–", "–", "–", "–", "–", "–",
             " ".join(f"{y[2:]}:{v * 100:+.0f}" for y, v in bm["full"]["by_year"].items())])
table(["model", "10d/50bp dev", "10d/50bp 2026", "10d/50bp full", "Sharpe sim/adj (full)", "maxDD (full)", "hit", "mean trade bp",
       "10d/80bp dev", "10d/80bp 2026", "20d/50bp dev", "20d/50bp 2026", "20d/50bp full", "20d/80bp dev", "20d/80bp 2026",
       "10d/50bp by year %"], rows)

md.append("## CT11 short side compact (bottom-20 among fno_proxy, 10d)\n")
rows = []
for m in M + ["RANDOM"]:
    src = {k[6:]: v for k, v in RD.items() if k.startswith("short_")} if m == "RANDOM" else R[f"s4_{m}"]["short_fno"]
    rows.append([m, p(src["fixed10_c50_dev"]["cagr"]), p(src["fixed10_c50_hold2026"]["cagr"]), p(src["fixed10_c50_full"]["cagr"]),
                 p(src["fixed10_c50_full"]["max_dd"]), f"{src['fixed10_c50_full']['mean_trade_net'] * 1e4:+.0f}",
                 p(src["fixed10_c80_full"]["cagr"])])
table(["model", "50bp dev", "50bp 2026", "50bp full", "maxDD", "mean trade bp", "80bp full"], rows)

md.append("## CT12 overlays compact (5 seeds, 50 bp)\n")
B = R["s4b_random"]
rows = [["RANDOM", p(B["random_h20"]["fixed20_c50_dev"]["cagr"]), p(B["random_h20"]["fixed20_c50_hold2026"]["cagr"]),
         "–", "–", p(B["random_h10"]["fixed10_c50_dev"]["cagr"]), p(B["random_h10"]["fixed10_c50_hold2026"]["cagr"]),
         p(B["random_h20"]["fixed20_c80_dev"]["cagr"]), p(B["random_h20"]["fixed20_c80_hold2026"]["cagr"])]]
for m in M:
    o = R[f"s4b_{m}"]
    rows.append([m, p(o["avoid30_h20"]["fixed20_c50_dev"]["cagr"]), p(o["avoid30_h20"]["fixed20_c50_hold2026"]["cagr"]),
                 p(o["top30rand_h20"]["fixed20_c50_dev"]["cagr"]), p(o["top30rand_h20"]["fixed20_c50_hold2026"]["cagr"]),
                 p(o["avoid30_h10"]["fixed10_c50_dev"]["cagr"]), p(o["avoid30_h10"]["fixed10_c50_hold2026"]["cagr"]),
                 p(o["avoid30_h20"]["fixed20_c80_dev"]["cagr"]), p(o["avoid30_h20"]["fixed20_c80_hold2026"]["cagr"])])
table(["model", "avoid30 20d dev", "avoid30 20d 2026", "top30rand 20d dev", "top30rand 20d 2026", "avoid30 10d dev",
       "avoid30 10d 2026", "avoid30 20d/80bp dev", "avoid30 20d/80bp 2026"], rows)

md.append("## CT13 cost ladder & liquidity compact (long top-20, 20d hold)\n")
S9 = R["s9_stress"]
rows = []
for m in M + ["RANDOM"]:
    s = S9[m]
    rows.append([m, *[p(s["eq_h20_dev"]["by_cost"][c]["cagr"]) for c in ("50", "80", "130")],
                 *[p(s["eq_h20_2026"]["by_cost"][c]["cagr"]) for c in ("50", "80")],
                 f"{s['eq_h20_dev']['breakeven_cost_bps_trade']:.0f}",
                 p(s["liq5_h20_dev"]["by_cost"]["50"]["cagr"]), p(s["liq5_h20_2026"]["by_cost"]["50"]["cagr"]),
                 p(s["liq5_h10_2026"]["by_cost"]["50"]["cagr"])])
table(["model", "dev 50bp", "dev 80bp", "dev 130bp", "2026 50bp", "2026 80bp", "dev break-even bp/trade",
       "liq5 dev 50bp", "liq5 2026 50bp", "liq5 10d 2026 50bp"], rows)

md.append("## CT6 oracle capture compact (dev 2023-25; +1 = long, -1 = short)\n")
O = R["s7_oracle"]
rows = []
for k, d in O.items():
    nm, cl, wn = k.split("|")
    if wn != "dev":
        continue
    nat = d.get("natural_net")
    f20 = d["fixed20"]["net"]
    rows.append([nm, cl, p(nat) if nat is not None else "–", p(d["fixed10"]["net"], nd=2), p(f20, nd=2), p(d["atr2"]["net"], nd=2),
                 p(d["atr3"]["net"], nd=2), p(d["tsexit"]["net"], nd=2) + f" ({d['tsexit']['bars']:.1f} bars)",
                 f"{f20 / nat * 100:.0f}%" if nat else "–", p(O[f"{nm}|{cl}|2026"]["fixed20"]["net"], nd=2)])
table(["label", "class", "natural (unknowable) exit", "fixed 10d", "fixed 20d", "ATR trail 2x", "ATR trail 3x", "TS-exit",
       "fixed20 / natural", "fixed 20d 2026"], rows)
open(f"{OUT}/report_tables.md", "w").write("\n".join(md))
print("ok")

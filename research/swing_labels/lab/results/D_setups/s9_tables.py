"""Stage 9: markdown tables for REPORT.md (tables_autogen.md) + official L.portfolio_sim confirmation
of the headline configurations (lablib's own signal grid and equal-weight sizing)."""
import numpy as np
import pandas as pd

from common import L, OUT, H, DEV_END, HOLD_END, load_base, load_res, save, T

t = T()
R = load_res()
md = []


def tbl(df, floatfmt=2):
    df = df.copy()
    for c in df.columns:
        if df[c].dtype.kind == "f":
            df[c] = df[c].round(floatfmt)
    cols = list(df.columns)
    lines = ["| " + " | ".join(str(c) for c in cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join("" if (isinstance(v, float) and np.isnan(v)) else str(v) for v in r.values) + " |")
    return "\n".join(lines)


E = R["s2_events"]
# 1. base label
b = E["base_long"]
rows = []
for k in ("all", "dev_2023_2025", "hold_2026"):
    x = b[k]
    rows.append({"period": k, "n": x["n"], "P(+1)": x["P+1"], "P(0)": x["P0"], "P(-1)": x["P-1"], "touch_pt": x["touch_pt"],
                 "touch_sl": x["touch_sl"], "touch_time": x["touch_time"], "mean_bars": x["mean_k"],
                 "gross_bps": x["gross_bps"], "net50_bps": x["net50_bps"], "net80_bps": x["net80_bps"]})
md += ["## T1 Base label (every eligible bar, long barrier h=10)", tbl(pd.DataFrame(rows), 3)]
rows = [{"year": y, "n": v["n"], "P(+1)": v["P+1"], "P(-1)": v["P-1"], "net50_bps": v["net50_bps"]} for y, v in b["by_year"].items()]
md += ["### T1b base by year", tbl(pd.DataFrame(rows), 3)]
rows = [{"regime": k, "n": v["n"], "P(+1)": v["P+1"], "net50_bps": v["net50_bps"]} for k, v in b["by_regime"].items()]
md += ["### T1c base by regime", tbl(pd.DataFrame(rows), 3), f"monthly P(+1): {b['monthly_pos']}"]

# 2. setup table (dev) for all setups
S = pd.DataFrame(E["summary"])
for side in ("long", "long_avoid", "short", "short_fno"):
    s = S[S.side == side]
    cols = ["setup", "variant", "share_U", "ev_per_day", "dev_n", "dev_P+1", "dev_base_P+1", "dev_lift", "dev_net50",
            "dev_base_net50", "dev_xs_bps", "dev_xs_t", "xs_2023", "xs_2024", "xs_2025", "hold_n", "hold_net50",
            "hold_xs_bps", "mon_std", "mon_corr_mkt", "bull_share_events"]
    md += [f"## T2 setups side={side} (dev = 2023-01-01..{DEV_END}; hold = 2026)", tbl(s[cols], 3)]

# 2b. class shares + touch mix (dev) per setup
rows = []
for key, v in E.items():
    if "|" not in key or not key.endswith("|all"):
        continue
    sd, st_, _ = key.split("|")
    d = v["dev_2023_2025"]
    if d.get("n", 0) == 0:
        continue
    rows.append({"side": sd, "setup": st_, "n_dev": d["n"], "P(+1)": d["P+1"], "P(0)": d["P0"], "P(-1)": d["P-1"],
                 "lift+1": d["lift_P+1"], "lift-1": d["lift_P-1"], "pt": d["touch_pt"], "sl": d["touch_sl"], "time": d["touch_time"],
                 "mean_bars": d["mean_k"], "median_net50": d["median_net50_bps"], "hit_net50": d["hit_net50"],
                 "xsP+1": d["xs_excess_P+1"], "nan_share": v.get("nan_share_of_setup_rows")})
md += ["## T3 class shares / touch mix (dev)", tbl(pd.DataFrame(rows), 3)]

# 3. by year (P+1 / net50 / xs) for long setups
rows = []
for key, v in E.items():
    if not (key.startswith("long|") or key.startswith("long_avoid|")) or not key.endswith("|all"):
        continue
    r = {"setup": key.split("|")[1] + (" (as long)" if key.startswith("long_avoid") else "")}
    for y, yv in v["by_year"].items():
        r[f"P+1_{y}"] = yv.get("P+1")
        r[f"xs_{y}"] = yv.get("xs_excess_ret_bps")
    rows.append(r)
md += ["## T4 by year: P(+1) and date-matched excess (bps)", tbl(pd.DataFrame(rows), 3)]

# 4. by regime for key setups
rows = []
for key in ("long|L1_bo20|all", "long|L3_pullback|all", "long|L6_rslead|all", "long|L7_oversold_up|all",
            "long|L8b_mktlead|all", "long_avoid|S1_bd20|all", "long_avoid|S3_rslag|all"):
    for rg, v in E[key]["by_regime"].items():
        rows.append({"setup": key.split("|")[1], "regime": rg, "n": v.get("n"), "share_of_events": v.get("share_of_events"),
                     "share_of_base": v.get("share_of_base"), "P(+1)": v.get("P+1"), "base_P(+1)": v.get("base_P+1"),
                     "net50": v.get("net50_bps"), "xs_bps": v.get("xs_excess_ret_bps")})
md += ["## T5 by regime (all years)", tbl(pd.DataFrame(rows), 3)]
# liquidity
rows = []
for key in ("long|L1_bo20|all", "long|L3_pullback|all", "long|L6_rslead|all", "long|L7_oversold_up|all",
            "long_avoid|S1_bd20|all"):
    for lt, v in E[key]["by_liq_tercile"].items():
        rows.append({"setup": key.split("|")[1], "liq_tercile(0=low)": lt, "n": v.get("n"), "P(+1)": v.get("P+1"),
                     "net50": v.get("net50_bps"), "xs_bps": v.get("xs_excess_ret_bps")})
md += ["## T5b by liquidity tercile (all years)", tbl(pd.DataFrame(rows), 3)]

# 5. Jaccard
J = E["jaccard"]
jn = J["names"]
jd = pd.DataFrame(np.array(J["J"]), index=jn, columns=jn)
md += ["## T6 Jaccard overlap (U rows)", tbl(jd.reset_index().rename(columns={"index": "setup"}), 3)]

# 6. conjunctions
C = R["s3_conj"]
md += [f"## T7 conjunctions: {C['n_configs_evaluated']} configs, {C['n_configs_ge300_dev_events']} with >=300 dev events; "
       f"Bonferroni |t| hurdle {C['bonferroni_t_hurdle']:.2f}",
       tbl(pd.DataFrame(C["top30_by_dev_t"]).head(20), 2), "### worst 10", tbl(pd.DataFrame(C["bottom10_by_dev_t"]), 2),
       "### trade-off: best 3 per dev-event-count bucket", tbl(pd.DataFrame(C["tradeoff_best3_per_bucket"]), 2)]
leak = pd.DataFrame(C["sector_leak_demo"]).T.reset_index().rename(columns={"index": "subset"})
md += ["## T8 sector-snapshot leak demo", tbl(leak[["subset", "n_dev", "dev_xs_bps", "dev_xs_t", "xs_2023", "xs_2024",
                                                    "xs_2025", "hold_xs_bps"]], 2)]

# 7. meta-label eval
ME = pd.DataFrame(R["s5_eval"]["summary"])
md += ["## T9 meta-labeling on setup rows (OOS)", tbl(ME[["setup", "scorer", "period", "n_events", "auc_pooled", "ic_date_neutral",
                                                          "all_P+1", "all_net50_bps", "all_xs_bps", "pit_pass_n", "pit_pass_P+1",
                                                          "pit_pass_net50_bps", "pit_pass_xs_bps", "top_tercile_P+1",
                                                          "top_tercile_net50_bps", "top_tercile_xs_bps", "bottom_tercile_xs_bps"]], 3)]
MY = pd.DataFrame(R["s5_eval"]["per_year"])
md += ["### T9b per year", tbl(MY[["setup", "scorer", "year", "n_events", "auc_pooled", "ic_date_neutral", "all_xs_bps",
                                   "pit_pass_share", "pit_pass_P+1", "pit_pass_xs_bps", "top_tercile_xs_bps", "bottom_tercile_xs_bps"]], 3)]
wf = []
for k in ("ALL", "R1", "L7", "R3", "L3"):
    for f in R[f"s4_wf_{k}"]["folds"]:
        wf.append({"model": k, "year": f["year"], "n_train": f["n_train"], "n_test": f["n_test"], "auc_pooled": f.get("auc_up"),
                   "base": f["base_rate"], "top_decile": f["top_decile_rate"], "bottom_decile": f["bottom_decile_rate"]})
md += ["### T9c walk-forward folds", tbl(pd.DataFrame(wf), 3)]
xs = pd.DataFrame(R["s5_eval"]["allbar_xs"]).T.reset_index().rename(columns={"index": "year"})
md += ["### T9d every-bar model: daily cross-sectional AUC / IC", tbl(xs, 4)]

# 8. investability
A = pd.read_csv(f"{OUT}/s6_invest_agg.csv")
key = ["U_random", "U_allbar_top20", "D1_U_random_top5", "D1_U_allbar_top5", "R1_events_random", "R1_gate_allbar_top5",
       "R1_meta_PIT_top20", "R1dn_events_random", "R1dn_gate_allbar_top5", "R1dn_meta_top5", "R1dn_meta_PIT_top20",
       "D1_R1_events_random_top5", "D1_R1_meta_PIT_top5", "D1_R1dn_events_random_top5", "D1_R1dn_gate_allbar_top5",
       "D1_R1dn_meta_PIT_top5", "D1_R1dn_meta_top5", "L7_events_random", "L7_gate_allbar_top5", "L7_meta_PIT_top20",
       "R3_events_random", "R3_gate_allbar_top5", "R3_meta_PIT_top20", "L3_events_random", "L3_meta_top20",
       "L1_events_random", "L6_events_random", "L6_gate_allbar_top20",
       "SHORT_fno_random", "SHORT_S1_bd20_fno_events_random", "SHORT_S5_gapfail_fno_events_random"]
for w in ("full", "dev", "hold"):
    q = A[(A.config.isin(key)) & (A.window == w) & (A.sizing == "slot") & (A.exit == "time")]
    q50 = q[q.cost == 50].set_index("config")
    q80 = q[q.cost == 80].set_index("config")
    o = q50[["top_k", "step", "trades", "avg_exposure_slot", "hit_rate", "mean_trade_net_bps", "cagr", "sharpe", "max_dd",
             "y2023", "y2024", "y2025", "y2026"]].copy()
    o["cagr_80"] = q80["cagr"]
    o["sharpe_80"] = q80["sharpe"]
    o = o.reindex([k for k in key if k in o.index]).reset_index()
    md += [f"## T10 investability window={w} (time exit, slot sizing, 50 bps; cagr_80/sharpe_80 = 80 bps)", tbl(o, 3)]
bm = R["s6_invest"]["benchmark_nifty500"]
md += ["Nifty 500 benchmark: " + "; ".join(f"{w}: CAGR {v['cagr']:.3f} Sharpe(daily) {v['sharpe']:.2f} maxDD {v['max_dd']:.3f}"
                                         for w, v in bm.items())]

# 9. R1 robustness
D = R["s7_diag"]
md += ["## T11 breadth dependence of R1 / R1dn", tbl(pd.DataFrame(D["breadth"]), 2)]
sens = pd.DataFrame(D["sensitivity"])
md += ["## T12 R1 parameter sensitivity", tbl(sens[["lookback", "volz_gt", "regime", "share_of_U_rows", "events_per_day", "dev_n",
                                                    "dev_P+1", "dev_net50_bps", "dev_xs_bps", "xs_2023", "xs_2024", "xs_2025",
                                                    "hold_n", "hold_net50_bps", "hold_xs_bps"]], 2)]
md += ["## T13 label robustness (time-exit h=5/10/20, Nifty excess)", tbl(pd.DataFrame(D["label_robustness"]), 3)]
ep = D["episodes"]
md += ["## T14 episode concentration", str({k: {kk: vv for kk, vv in v.items() if kk != "monthly"} for k, v in ep.items()})]
md += ["### R1dn monthly", tbl(pd.DataFrame(ep["R1dn"]["monthly"]), 1)]
C8 = R["s8_checks"]
for nm in ("R1", "R1dn"):
    for per in ("dev", "hold"):
        dd = pd.DataFrame({k: v for k, v in C8[nm][per].items() if isinstance(v, dict)}).T.reset_index().rename(columns={"index": "subset"})
        md += [f"## T15 {nm} checks {per}", tbl(dd, 2)]
md += [f"capitulation episodes (>=30 R1 events/day, merged within 5 days): {C8['n_episodes']} {C8['n_episodes_by_year']}"]

# 10. official L.portfolio_sim confirmation
B = load_base()
names = list(B["setup_names"])
P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["sector", "atr_pct"])
fw = L.Fwd(P)
U = B["U"]
R1dn = B["setups"][:, names.index("S1_bd20")] & U & (B["mkt_mom20"] < 0)
sc_all = np.load(f"{OUT}/wf_ALL.npz")["score"].astype("float64")
sc_r1 = np.load(f"{OUT}/wf_R1.npz")["score"].astype("float64")
off = []
for nm, sc, m, k, seeds in (("U_random", None, U, 20, (1, 2, 3)), ("U_allbar_top20", sc_all, U, 20, (None,)),
                            ("R1dn_random", None, R1dn, 5, (1, 2, 3)), ("R1dn_allbar_top5", sc_all, R1dn, 5, (None,)),
                            ("R1dn_metaR1_top5", sc_r1, R1dn, 5, (None,))):
    for cost in (50, 80):
        for (lo, hi, w) in (("2023-01-01", HOLD_END, "full"), ("2023-01-01", DEV_END, "dev"), ("2026-01-01", HOLD_END, "hold")):
            rs = [L.portfolio_sim(sc if sc is not None else np.zeros(len(P)), m, P, F, fw, H, step=5, top_k=k, cost_bps=cost,
                                  start=lo, end=hi, random_seed=s) for s in seeds]
            off.append({"config": nm, "cost": cost, "window": w, "trades": np.mean([r["trades"] for r in rs]),
                        "hit": np.mean([r["hit_rate"] for r in rs]),
                        "mean_trade_net_bps": 1e4 * np.mean([r["mean_trade_net"] for r in rs]),
                        "cagr": np.mean([r["cagr"] for r in rs]), "sharpe": np.mean([r["sharpe"] for r in rs]),
                        "max_dd": np.mean([r["max_dd"] for r in rs])})
off = pd.DataFrame(off)
print(off.round(3).to_string())
md += ["## T16 official L.portfolio_sim (lablib grid = every 5th date with events, equal weight among picks, time exit)",
       tbl(off, 3)]
save("s9_official_sim", off.to_dict(orient="records"))
open(f"{OUT}/tables_autogen.md", "w").write("\n\n".join(md))
t("done")

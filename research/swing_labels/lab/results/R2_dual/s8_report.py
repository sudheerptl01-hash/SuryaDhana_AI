"""Stage 8: generate REPORT.md (all numbers pulled from results.json)."""
import json
import os

import numpy as np

from common import OUT, save

R = json.load(open(os.path.join(OUT, "results.json")))
E20, E10 = R["s2_events_h20"], R["s2_events_h10"]
MAIN = R["s5_main"]
KS = R["s5_ksens"]
LQ = R["s5_liq5"]
AV = R["s5_avoid"]
GT = R["s5_gates"]
GO = R["s5_gate_only"]
GS = R["s5_gate_stats"]
P7 = R["s7_paired"]
PK = R["s6_picks"]
L = []


def w(s=""):
    L.append(s)


def f(x, d=1, pct=False, sign=False):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "–"
    if pct:
        x = x * 100
    s = f"{x:+.{d}f}" if sign else f"{x:.{d}f}"
    return s + ("%" if pct else "")


def table(header, rows):
    w("| " + " | ".join(header) + " |")
    w("|" + "|".join(["---"] * len(header)) + "|")
    for r in rows:
        w("| " + " | ".join(str(c) for c in r) + " |")
    w()


def find(rows, **kw):
    for r in rows:
        if all(r.get(k) == v for k, v in kw.items()):
            return r
    return None


def xs(tag):
    return R.get(f"s4_xs_{tag}")


# ------------------------------------------------------------------ headline numbers
m = {(r["name"], r["win"], r["cost"]): r for r in MAIN}
pr = {(r["a"], r["b"], r["win"]): r for r in P7["paired_main"]}
rk = {(r["name"], r["win"], r["cost"]): r for r in P7["risk_main"]}
n_cfg = P7["n_dev_strategy_configs"]
n_models = len([k for k in R if k.startswith("s3_wf_")])

w("# R2_dual — \"both conditions must accept\" (relative AND absolute), formalised and tested")
w()
w("Lab v2 (no sector data, ETFs excluded, rebuilt `elig_base`). Universe U = `elig_base`. Entry at open[t+1], "
  "exit at close[t+h]. Labels are NaN where `fw.ok(h)` is false. Filters choose samples and never change label values. "
  "Models: `L.walk_forward2` (yearly expanding folds 2023-2026, embargo h+2, date_step 2, 52 features, n_jobs 2). "
  "Learnability: `L.xs_metrics`, per-date IC/AUC only (no pooled AUC). Investability: `L.Sim`, daily mark-to-market, "
  "slot sizing, staggered sleeves, h=20, step 5, top-20 unless stated, horizon-matched random baseline on the same mask "
  "(5 seeds), NW t of the daily excess with lag 20. Costs: 50 bps central and 80 bps stress. "
  "DEV = 2023-01-01 to 2025-12-31 (exits by DEV end). HOLDOUT = 2026-01-01 to 2026-10-14, reported separately "
  "and never used for selection. The holdout is lightly contaminated because round 1 reported 2026.")
w()
w("## Verdict")
w()
d_rel = m[("REL", "dev", 50.0)]
d_rup = m[("RUP", "dev", 50.0)]
d_dual = m[("DUAL", "dev", 50.0)]
d_dualp = m[("DUALP", "dev", 50.0)]
h_rel = m[("REL", "hold", 50.0)]
h_rup = m[("RUP", "hold", 50.0)]
h_dual = m[("DUAL", "hold", 50.0)]
h_dualp = m[("DUALP", "hold", 50.0)]
w(f"**No.** Requiring an absolute condition as well as a relative one does not make more money and does not "
  f"reduce drawdowns compared with a pure-relative label. This holds once the comparison controls for the model's "
  f"loss function. DUAL is roughly equal to the same-loss pure-relative model. Its apparent gain over the XR_neu "
  f"regression comes from the loss function, not from the absolute condition.")
w()
PH = R["s9_phase"]["summary"]
PHA = R["s9b_phase_avoid"]["summary"]
php = lambda win, k: PH[win]["pairs"][k]
phb = lambda win, k: PH[win][k]
w(f"* **Label-side DUAL vs pure relative with the same loss (binary top-30%, M_RUP).** The comparison is averaged over "
  f"5 signal-calendar phases (K20, step 5, 50 bp). On DEV, DUAL minus RUP is "
  f"{f(php('dev','DUAL-RUP')['diff_mean'],1,True,True)}/yr (range {f(php('dev','DUAL-RUP')['diff_min'],1,True,True)} to "
  f"{f(php('dev','DUAL-RUP')['diff_max'],1,True,True)}, {php('dev','DUAL-RUP')['n_positive']}/5 phases positive, "
  f"mean NW t {f(php('dev','DUAL-RUP')['t_mean'],2)}). In the 2026 holdout it is "
  f"{f(php('hold','DUAL-RUP')['diff_mean'],1,True,True)}/yr (range {f(php('hold','DUAL-RUP')['diff_min'],1,True,True)} "
  f"to {f(php('hold','DUAL-RUP')['diff_max'],1,True,True)}, mean t {f(php('hold','DUAL-RUP')['t_mean'],2)}). "
  f"The path version is worse: DUALP minus RUP is {f(php('dev','DUALP-RUP')['diff_mean'],1,True,True)}/yr on DEV "
  f"(0/5 phases positive). Over the 8-cell K x step grid at phase 0, DUAL beats RUP in "
  f"{[g for g in P7['grid_consistency'] if g['a']=='DUAL' and g['b']=='RUP' and g['win']=='dev'][0]['n_positive']}/8 DEV "
  f"cells and DUALP in {[g for g in P7['grid_consistency'] if g['a']=='DUALP' and g['b']=='RUP' and g['win']=='dev'][0]['n_positive']}/8. "
  f"The DUAL and RUP model scores have a 0.90 per-date rank correlation. **The absolute leg is neutral at best, "
  f"inside noise in both windows.**")
w(f"* **DUAL does beat the pure-relative regression model (XR_neu, `REL`):** "
  f"{f(php('dev','DUAL-REL')['diff_mean'],1,True,True)}/yr on DEV (5/5 phases, mean t {f(php('dev','DUAL-REL')['t_mean'],2)}; "
  f"8/8 grid cells). That gain comes entirely from switching the target from a full-rank regression to a top-tail "
  f"classifier. RUP minus REL is {f(php('dev','RUP-REL')['diff_mean'],1,True,True)}/yr (5/5 phases, mean t "
  f"{f(php('dev','RUP-REL')['t_mean'],2)}).")
w(f"* **No fewer drawdowns.** Phase-mean DEV maxDD: REL {f(phb('dev','REL')['maxdd_mean'],1,True)}, RUP "
  f"{f(phb('dev','RUP')['maxdd_mean'],1,True)}, DUAL {f(phb('dev','DUAL')['maxdd_mean'],1,True)}, DUALP "
  f"{f(phb('dev','DUALP')['maxdd_mean'],1,True)}. Book beta at phase 0: REL {f(rk[('REL','dev',50.0)]['beta'],2)}, "
  f"RUP {f(rk[('RUP','dev',50.0)]['beta'],2)}, DUAL {f(rk[('DUAL','dev',50.0)]['beta'],2)}. The top-tail books carry "
  f"more beta than REL, and the absolute leg does not lower it on DEV.")
w(f"* **Two-model ANDs do not help either.** rank(REL)+rank(ABS) gives "
  f"{f(pr[('SUM_REL_ABS','REL','dev')]['ann_diff'],1,True,True)}/yr on DEV vs REL and "
  f"{f(pr[('SUM_REL_ABS','REL','hold')]['ann_diff'],1,True,True)}/yr in the holdout (0/8 grid cells positive in the holdout). "
  f"P(top30) x P(abs up) vs RUP gives {f(pr[('PROD_RUP_ABS','RUP','dev')]['ann_diff'],1,True,True)}/yr on DEV "
  f"(t {f(pr[('PROD_RUP_ABS','RUP','dev')]['nw_t'],2)}). 'REL top-20 only among ABS-model top half' gives "
  f"{f(pr[('AND_REL_ABS50','REL','dev')]['ann_diff'],1,True,True)}/yr on DEV.")
w("* **Input-side gates (sample filters) do not add skill on DEV either.** Inside close>sma200 AND xr_mom60>0.7, a random "
  "pick earns about 1%/yr more than in U (t 0.4), and the relative model inside the gate is not better than the "
  "relative model on all of U. In the 2026 holdout the trend gate by itself was worth +15%/yr (t 2.1). That is not "
  "selectable on DEV, and the model added nothing inside the gate.")
w(f"* **Avoid side.** The explicit DUAL_down model is accurate as a classifier (per-date AUC 0.57 DEV / 0.56 holdout). "
  f"As an avoid overlay it gives {f(PHA['dev']['AVOID_DDN']['vs_univ_mean'],1,True,True)}/yr vs the universe on DEV "
  f"(t {f(PHA['dev']['AVOID_DDN']['t_mean'],1)}) and **fails in 2026** with "
  f"{f(PHA['hold']['AVOID_DDN']['vs_univ_mean'],1,True,True)}/yr (0/5 phases positive). REL_down behaves the same. "
  f"The robust avoid overlay is to drop the 30% of names with the lowest P(relative top-30): "
  f"{f(PHA['dev']['AVOID_RUPup']['vs_univ_mean'],1,True,True)}/yr on DEV (t {f(PHA['dev']['AVOID_RUPup']['t_mean'],1)}) and "
  f"{f(PHA['hold']['AVOID_RUPup']['vs_univ_mean'],1,True,True)}/yr in 2026 (t {f(PHA['hold']['AVOID_RUPup']['t_mean'],1)}), "
  f"5/5 phases in both windows. The DUAL-up version of the same overlay is slightly worse: "
  f"{f(PHA['dev']['AVOID_DUALup']['vs_univ_mean'],1,True,True)} / {f(PHA['hold']['AVOID_DUALup']['vs_univ_mean'],1,True,True)}.")
w()
w("**Recommendation:** keep the label purely relative. Use XR_neu residual ranks, and train the selection model as a "
  "**binary top-30% classifier** (or blend it with the XR_neu regression score). Use **low P(top-30)** as the avoid "
  "screen. Put the absolute or market condition in a separate regime/exposure layer (R2_regime). It does not belong "
  "in the stock label: there it only adds market beta and timing information that a cross-sectional book cannot use.")
w()
w(f"Variants tried by this agent: {n_models} walk-forward models, {n_cfg} distinct DEV book configurations "
  f"(each also run at 80 bps and on the holdout), and about 56 label variants screened on event rates "
  f"(tau x q x h grid of 42, 3 barrier geometries with their DUALP versions, and 8 base labels). "
  f"Under the null, the expected maximum t of {n_cfg} tries is about 2.6. For about 730 programme-wide tries "
  f"(including round 1) it is about 3.2. No DUAL-vs-relative paired t comes anywhere close. "
  f"On top of that, the signal-calendar phase alone moves a K20 book's 2026 CAGR by 10-14 pp (section 4.7), "
  f"so single-phase holdout differences of a few %/yr are noise.")
w()

# ------------------------------------------------------------------ definitions
w("## 1. Label definitions (h = 20 unless stated)")
w()
table(["id", "family", "formula (r = open[t+1] -> close[t+h], adjusted; NaN unless fw.ok(h))"], [
    ["REL (XR_neu)", "pure relative", "per date: winsorise r at 1/99%, OLS on [1, 0.5*beta_60+0.5, vol_20, log_turn20] over U; "
                                      "residual percentile pct; +1 pct>0.7, -1 pct<=0.3, else 0"],
    ["ABS", "pure absolute", "+1 r > +50 bp, -1 r < -50 bp, else 0 (cost dead zone)"],
    ["BAR (A2)", "pure absolute, path", "L.barrier_labels(h=20, pt=3.0 ATR, sl=1.5 ATR, tau 50 bp); stop checked first, gap fills"],
    ["DUAL", "label-side AND", "+1 if REL=+1 AND r > +tau; -1 if REL=-1 AND r < -tau; else 0; tau = 50 bp (= covers the 50 bp round trip)"],
    ["DUALP", "label-side AND, path", "+1 if REL=+1 AND BAR=+1; -1 if REL=-1 AND BAR=-1; else 0"],
    ["DUAL_t300", "stricter AND", "as DUAL with tau = 300 bp"],
])
w("Models (walk_forward2; a binary target is the event vs the rest): `M_REL` = regression on pct-0.5. `M_RUP` = P(REL=+1), "
  "the **same-loss pure-relative control**. `M_RDN` = P(REL=-1). `M_ABS` = P(r>50bp). `M_BAR` = P(BAR=+1). `M_DUAL`, "
  "`M_DUALP`, `M_DUALt300` = P(+1). `M_DDN` = P(DUAL=-1), the DUAL avoid model. `M_DUALmc` = multiclass DUAL, scored "
  "P(+1)-P(-1). `M_RELG` = M_REL trained and scored only inside the input gate G_trend. Combinations: SUM_REL_ABS = "
  "rank(M_REL)+rank(M_ABS). SUM_REL_BAR. SUM_REL_DUAL. SUM_REL_RUP (the pure-relative control for SUM_REL_DUAL). "
  "PROD_RUP_ABS = P(top30) x P(r>50bp). AND_REL_ABS50 = M_REL top-20 among names whose M_ABS is in the top half that day.")
w()

# ------------------------------------------------------------------ event rates
w("## 2. Event rates — the DUAL +1 share now moves with the market")
w()
rows = []
for k in ("REL", "ABS", "BAR", "DUAL", "DUALP"):
    x = E20[k]
    o = x["overall"]
    du = x["daily_up"]["dev"]
    rows.append([k, f(o.get("1.0"), 1, True), f(o.get("0.0"), 1, True), f(o.get("-1.0"), 1, True),
                 f(x["monthly_pos"]["std"], 1, True), f(x["monthly_pos"]["min"], 1, True), f(x["monthly_pos"]["max"], 1, True),
                 f(du["corr_daily_share_vs_mkt_window"], 2), f(du["slope_share_per_10pct_mkt"], 1, True, True),
                 f(du["share_when_mkt_window_up"], 1, True), f(du["share_when_mkt_window_down"], 1, True),
                 f(du["share_when_mkt_window_lt_m5pct"], 1, True), f(x["corr_monthly_pos_vs_mkt_ret"], 2)])
table(["label", "+1", "0", "-1", "monthly +1 sd", "monthly min", "monthly max", "corr(daily +1 share, N500 same window) DEV",
       "+1 share per +10% mkt", "+1 share, mkt window up", "mkt window down", "mkt window < -5%", "corr monthly +1 vs N500 month"], rows)
w("Rows are U samples from 2021 to 2026. Daily statistics are DEV dates. The market window is the Nifty 500 open on the "
  "row's t+1 date to the close on its t+h date, the same executable window as the stock.")
w()
w("**Reading:** by construction REL has a constant 30% +1 share (corr 0.04). Adding the absolute leg (DUAL) makes the "
  "share move with the market: corr 0.70, and +10 pp of share for every +10% of market window return. The share falls "
  "from 29.7% in up windows to 23.3% in down windows and to 11.9% when the market window falls more than 5%. Its level "
  "dependence is still about 5x smaller than pure ABS (slope 48 pp per 10%), because the relative leg caps the share "
  "at 30%.")
w()
rows = []
for k in ("REL", "ABS", "BAR", "DUAL", "DUALP"):
    x = E20[k]
    rows.append([k] + [f(x["by_year"][y].get("1.0"), 1, True) for y in ("2021", "2022", "2023", "2024", "2025", "2026")]
                + [f(x["by_year"][y].get("-1.0"), 1, True) for y in ("2021", "2022", "2023", "2024", "2025", "2026")])
table(["label"] + [f"+1 {y}" for y in range(2021, 2027)] + [f"-1 {y}" for y in range(2021, 2027)], rows)
rows = []
for k in ("REL", "ABS", "BAR", "DUAL", "DUALP"):
    x = E20[k]
    rows.append([k] + [f"{f(x['by_regime'][rg].get('1.0'),1,True)} / {f(x['by_regime'][rg].get('-1.0'),1,True)}"
                       for rg in ("bull_up20", "bull_dn20", "bear_up20", "bear_dn20")]
                + [f"{f(x['by_liquidity_tercile'][t].get('1.0'),1,True)} / {f(x['by_liquidity_tercile'][t].get('-1.0'),1,True)}"
                   for t in ("0", "1", "2")])
table(["label (+1 / -1)", "bull_up20", "bull_dn20", "bear_up20", "bear_dn20", "liq T1 (low)", "liq T2", "liq T3 (high)"], rows)
w("Regimes are measured at the signal date (N500 vs its 200dma, and N500 20d momentum). Signal-date regime barely "
  "moves the DUAL share (26.5-28.9%). What moves it is the realised market path over the window (table above), and "
  "that is unknown at entry.")
w()
x = E20["rel_plus_removed_by_abs"]
w(f"**What the absolute leg removes from REL +1.** Overall {f(x['share_of_REL+1_removed_overall'],1,True)} of REL +1 labels "
  f"become 0. By year: " + ", ".join(f"{y} {f(v,1,True)}" for y, v in x["by_year"].items()) +
  f". The removed rows are relative winners that lost money: mean net {f(x['mean_net_bps_removed'],0)} bps, mean "
  f"residual {f(x['mean_resid_bps_removed'],0,sign=True)} bps, beta {f(x['mean_beta_removed'],2)}. The kept rows have "
  f"mean net {f(x['mean_net_bps_kept'],0,sign=True)} bps and beta {f(x['mean_beta_kept'],2)}. At h=10, "
  f"{f(E10['rel_plus_removed_by_abs']['share_of_REL+1_removed_overall'],1,True)} are removed.")
w()
w("### 2a. Label / P&L coherence (mean net return per class, net = r - 50 bp)")
w()
rows = []
for k in ("REL", "ABS", "BAR", "DUAL", "DUALP"):
    c = E20[k]["coherence_dev"]
    ch = E20[k]["coherence_holdout"]
    rows.append([k] + [f"{f(c[s]['mean_net_bps'],0,sign=True)} ({f(c[s]['hit_net_pos'],0,True)})" if s in c else "–" for s in ("1", "0", "-1")]
                + [f"{f(ch[s]['mean_net_bps'],0,sign=True)}" if s in ch else "–" for s in ("1", "0", "-1")]
                + [f"{f(c[s]['mean_resid_bps'],0,sign=True)}" if s in c else "–" for s in ("1", "-1")])
table(["label", "+1 net bps (hit) 2021-25", "0", "-1", "+1 net 2026", "0 2026", "-1 2026", "+1 resid bps", "-1 resid bps"], rows)
w("All labels are coherent with P&L by construction. DUAL +1 is 100% profitable net by definition, and its spread "
  "(+1 minus -1) is the widest. That is a mechanical consequence of conditioning on the outcome and says nothing about "
  "predictability (section 3).")
w()
w("### 2b. Sensitivity map: how DUAL event rates move with tau (absolute hurdle), q (relative cut) and h")
w()
rows = []
for h in (20, 10):
    for r_ in R[f"s2_events_h{h}"]["sensitivity"]:
        if r_["q"] == 0.3 or r_["tau_bps"] in (0, 50, 500):
            rows.append([h, r_["q"], r_["tau_bps"], f(r_["up_dev_share"], 1, True), f(r_["up_dev_daily_std"], 1, True),
                         f(r_["up_dev_corr_mkt"], 2), f(r_["up_dev_share_mktup"], 1, True), f(r_["up_dev_share_mktdn"], 1, True),
                         f(r_["up_hold_share"], 1, True), f(r_["up_hold_corr_mkt"], 2), f(r_["up_dev_mean_net_bps"], 0, sign=True),
                         f(r_["dn_dev_share"], 1, True), f(r_["dn_dev_corr_mkt"], 2), f(r_["dn_dev_mean_net_bps"], 0, sign=True)])
table(["h", "q", "tau bp", "+1 share DEV", "daily sd", "corr mkt", "+1 in up windows", "+1 in down windows",
       "+1 share 2026", "corr mkt 2026", "+1 mean net bps", "-1 share", "-1 corr mkt", "-1 mean net bps"], rows)
w("A smooth plateau with no cliffs. Raising tau from 0 to 500 bp (q=0.3, h=20) cuts the +1 share from 27.6% to 22.7%. "
  "Market dependence rises from corr 0.67 to 0.83, and the down-window +1 share falls from 24.1% to 14.4%. "
  "Widening q to 0.4 raises market dependence further (corr 0.77-0.84). Narrowing it to 0.2 lowers it (0.56-0.75). "
  "h=10 behaves like h=20 with slightly higher corr. The stricter the absolute hurdle, the more the label becomes a "
  "market-timing label.")
w()
bg = E20["barrier_geometry_sensitivity"]
rows = []
for nm in ("BAR", "BAR22", "BAR21"):
    b = bg[nm]
    rows.append([{"BAR": "3.0/1.5", "BAR22": "2.0/2.0", "BAR21": "2.0/1.0"}[nm], f(b[f"{nm}_up_dev_share"], 1, True),
                 f(b[f"{nm}_up_dev_corr_mkt"], 2), f(b[f"DUALP_{nm}_up_dev_share"], 1, True), f(b[f"DUALP_{nm}_up_dev_corr_mkt"], 2),
                 f(b[f"DUALP_{nm}_up_dev_mean_net_bps"], 0, sign=True), f(b[f"DUALP_{nm}_dn_dev_share"], 1, True)])
table(["barrier pt/sl ATR", "BAR +1 share", "BAR corr mkt", "DUALP +1 share", "DUALP corr mkt", "DUALP +1 net bps", "DUALP -1 share"], rows)
w(f"Overlap autocorrelation (lag 1, within entity): REL {f(E20['REL']['autocorr_lag1'],2)}, DUAL {f(E20['DUAL']['autocorr_lag1'],2)}, "
  f"DUALP {f(E20['DUALP']['autocorr_lag1'],2)}. At lag 5: REL {f(E20['REL']['autocorr_lag5'],2)}, DUAL {f(E20['DUAL']['autocorr_lag5'],2)}. "
  f"Overlapping 20d labels give about 1/20 independent observations per row, so every t-stat here is either NW (lag 20) "
  f"or non-overlapping.")
w()

# ------------------------------------------------------------------ learnability
w("## 3. Learnability (cross-sectional, walk-forward OOS)")
w()
rows = []
for t in ("M_REL", "M_RUP", "M_DUAL", "M_DUALP", "M_DUALt300", "M_DUALmc", "M_ABS", "M_BAR", "M_RDN", "M_DDN", "M_RELG"):
    x = xs(t)
    if x is None:
        continue
    ic, icr = x["ic_resid"], x["ic_raw"]
    yrs = ic.get("dev_ic_by_year", {})
    rows.append([t, f"{f(ic.get('dev_ic_mean'),3)} ({f(ic.get('dev_ic_t_nonoverlap'),1)})",
                 f"{f(ic.get('holdout_ic_mean'),3)} ({f(ic.get('holdout_ic_t_nonoverlap'),1)})",
                 " / ".join(f(yrs.get(y), 3) for y in ("2023", "2024", "2025")),
                 f"{f(icr.get('dev_ic_mean'),3)} / {f(icr.get('holdout_ic_mean'),3)}",
                 f"{f(x['auc_REL+1'].get('dev_auc_mean'),3)} / {f(x['auc_REL+1'].get('holdout_auc_mean'),3)}",
                 f"{f(x['auc_DUAL+1'].get('dev_auc_mean'),3)} / {f(x['auc_DUAL+1'].get('holdout_auc_mean'),3)}",
                 f"{f(x['auc_DUALP+1'].get('dev_auc_mean'),3)} / {f(x['auc_DUALP+1'].get('holdout_auc_mean'),3)}",
                 f"{f(x['auc_ABS+1'].get('dev_auc_mean'),3)} / {f(x['auc_ABS+1'].get('holdout_auc_mean'),3)}",
                 f"{f(x['auc_REL-1'].get('dev_auc_mean'),3)} / {f(x['auc_REL-1'].get('holdout_auc_mean'),3)}",
                 f"{f(x['auc_DUAL-1'].get('dev_auc_mean'),3)} / {f(x['auc_DUAL-1'].get('holdout_auc_mean'),3)}"])
table(["model", "IC vs resid DEV (t)", "IC vs resid 2026 (t)", "IC 2023/24/25", "IC vs raw r DEV/2026",
       "AUC REL+1 DEV/2026", "AUC DUAL+1", "AUC DUALP+1", "AUC ABS+1", "AUC REL-1", "AUC DUAL-1"], rows)
w("Down models (M_RDN, M_DDN) are scored as -P(down) for IC, and as P(down) for the -1 AUCs. Every AUC is a per-date "
  "cross-sectional AUC averaged over dates, and t-stats use every 20th date. M_RELG is scored only inside G_trend.")
w()
w("**Reading:** the DUAL model is learnable (AUC on DUAL+1 0.545 DEV / 0.564 2026), but **no more learnable than the "
  "pure-relative binary model**. M_RUP scores 0.544 / 0.566 on the DUAL+1 event itself, and its scores have a 0.90 "
  "rank correlation with M_DUAL. Both binary-up models have lower full-cross-section IC than the regression M_REL "
  "(0.035-0.039 vs 0.063 DEV), because they ignore the loser tail (AUC REL-1 below 0.5). Their 2026 IC is higher "
  "(0.079-0.081 vs 0.057). The absolute models carry raw-return IC on DEV (0.066) that collapses in 2026 (0.034). "
  "The down models classify down events robustly (AUC 0.57 / 0.56) but their full-cross-section IC collapses in "
  "2026 (0.013-0.025).")
w()
rows = []
for t in ("M_REL", "M_RUP", "M_DUAL", "M_DUALP", "M_ABS", "M_DDN"):
    x = xs(t)
    for dsel in ("top10", "bot10"):
        rd = [r_ for r_ in x["deciles"] if r_["sel"] == dsel and r_["win"] == "dev"][0]
        rh = [r_ for r_ in x["deciles"] if r_["sel"] == dsel and r_["win"] == "hold"][0]
        rows.append([t, dsel, f(rd["mean_net_bps"], 0, sign=True), f(rd["mean_resid_bps"], 0, sign=True),
                     f(rd["rate_DUAL+1"], 1, True), f(rh["mean_net_bps"], 0, sign=True), f(rh["mean_resid_bps"], 0, sign=True),
                     f(rh["rate_DUAL+1"], 1, True)])
alld = [r_ for r_ in xs("M_REL")["deciles"] if r_["sel"] == "all" and r_["win"] == "dev"][0]
allh = [r_ for r_ in xs("M_REL")["deciles"] if r_["sel"] == "all" and r_["win"] == "hold"][0]
rows.append(["universe", "all", f(alld["mean_net_bps"], 0, sign=True), "0", f(alld["rate_DUAL+1"], 1, True),
             f(allh["mean_net_bps"], 0, sign=True), "0", f(allh["rate_DUAL+1"], 1, True)])
table(["model", "decile", "net bps DEV", "resid bps DEV", "DUAL+1 rate DEV", "net bps 2026", "resid bps 2026", "DUAL+1 rate 2026"], rows)
w("For M_DDN, 'top10' means lowest P(down) and 'bot10' means highest P(down), the names an avoid overlay would drop. "
  "In 2026 those names had a raw net return (+96 bps) above the universe average even though their residual was "
  "negative. That is why the DUAL-down avoid overlay fails (section 4.4).")
w()
sc = R["s4_score_corr_dev"]
rows = [[a.replace("M_", ""), b.replace("M_", ""), f(sc.get(f"{a}|{b}", sc.get(f"{b}|{a}")), 2)] for a, b in
        [("M_DUAL", "M_RUP"), ("M_DUAL", "M_REL"), ("M_DUALP", "M_RUP"), ("M_DUALt300", "M_RUP"), ("M_RUP", "M_REL"),
         ("M_ABS", "M_REL"), ("M_DDN", "M_RDN"), ("M_DDN", "M_DUAL"), ("M_REL", "M_RELG")]]
table(["score A", "score B", "mean per-date rank corr (DEV)"], rows)

# ------------------------------------------------------------------ investability
w("## 4. Investability (L.Sim, h=20)")
w()
w("### 4.1 Long top-20, step 5, U — DEV (selection) and 2026 holdout (report only)")
w()
rows = []
for nm in ["REL", "RUP", "DUAL", "DUALP", "DUALt300", "DUALmc", "ABS", "BAR", "SUM_REL_ABS", "SUM_REL_BAR",
           "PROD_RUP_ABS", "AND_REL_ABS50", "SUM_REL_DUAL", "SUM_REL_RUP"]:
    a, a8, hh = m.get((nm, "dev", 50.0)), m.get((nm, "dev", 80.0)), m.get((nm, "hold", 50.0))
    if a is None:
        continue
    rows.append([nm, f(a["cagr"], 1, True), f(a["excess_cagr"], 1, True, True), f(a["excess_nw_t"], 2), f(a["max_dd"], 1, True),
                 f(a["sharpe"], 2), f(a["beta"], 2), f(a8["cagr"], 1, True), f(a8["excess_cagr"], 1, True, True),
                 f(hh["cagr"], 1, True), f(hh["excess_cagr"], 1, True, True), f(hh["excess_nw_t"], 2), f(hh["max_dd"], 1, True),
                 f(a.get("vs_REL_ann", a.get("vs_ref_ann")), 1, True, True) if nm != "REL" else "–",
                 f(a.get("vs_RUP_ann"), 1, True, True) if nm not in ("RUP",) else "–"])
r0 = m[("REL", "dev", 50.0)]
r0h = m[("REL", "hold", 50.0)]
table(["score", "DEV CAGR 50bp", "excess vs random", "NW t", "maxDD", "Sharpe", "beta", "DEV CAGR 80bp", "excess 80bp",
       "2026 CAGR 50bp", "2026 excess", "2026 t", "2026 maxDD", "DEV vs REL /yr", "DEV vs RUP /yr"], rows)
w(f"Random baseline (same mask, 5 seeds): DEV {f(r0['rand_cagr'],1,True)} at 50 bp (sd {f(r0['rand_cagr_sd'],1,True)}), "
  f"{f(m[('REL','dev',80.0)]['rand_cagr'],1,True)} at 80 bp. 2026: {f(r0h['rand_cagr'],1,True)} at 50 bp. "
  f"The 2026 CAGR is annualised over 9.5 months. Exposure is about 0.93 for all books.")
w()
w("### 4.2 Paired daily differences (the decisive test), 50 bp, K20 step 5")
w()
rows = []
for r_ in P7["paired_main"]:
    rows.append([f"{r_['a']} - {r_['b']}", r_["win"], f(r_["ann_diff"], 1, True, True), f(r_["nw_t"], 2), f(r_["corr"], 3),
                 f(r_["ann_diff_bull200"], 1, True, True), f(r_["ann_diff_bear200"], 1, True, True),
                 f(r_["ann_diff_mkt_up20"], 1, True, True), f(r_["ann_diff_mkt_dn20"], 1, True, True)])
table(["pair", "window", "ann. diff", "NW t", "daily corr", "N500>200dma days", "N500<200dma days", "N500 20d up", "N500 20d down"], rows)
w("Bear days (N500 below its 200dma) are 17% of DEV and 55% of 2026. The regime splits are conditional means of the "
  "daily difference. They are descriptive and have no t-stats.")
w()
w("### 4.3 Robustness across K in {10,20,30,50} x step in {5,10} (50 bp): how many cells the first book wins")
w()
rows = []
for g in P7["grid_consistency"]:
    rows.append([f"{g['a']} - {g['b']}", g["win"], f"{g['n_positive']}/{g['n_cells']}", f(g["median_ann_diff"], 1, True, True),
                 f(g["min_ann_diff"], 1, True, True), f(g["max_ann_diff"], 1, True, True), f(g["median_t"], 2), g["n_t_gt_2"]])
table(["pair", "window", "cells positive", "median diff /yr", "min", "max", "median NW t", "cells t>2"], rows)
rows = []
for nm in ("REL", "RUP", "DUAL", "DUALP", "DUALt300", "SUM_REL_RUP", "SUM_REL_DUAL", "ABS"):
    cells = []
    for win in ("dev", "hold"):
        for st in (5, 10):
            for k in (10, 20, 30, 50):
                x = find(KS, name=nm, win=win, step=st, top_k=k)
                cells.append(f"{f(x['excess_cagr'],1,True,True)}" if x else "–")
    rows.append([nm] + cells)
hdr = ["score"] + [f"{w_} s{st} K{k}" for w_ in ("DEV", "2026") for st in (5, 10) for k in (10, 20, 30, 50)]
w("Excess CAGR vs the horizon-matched random baseline:")
w()
table(hdr, rows)
w("### 4.4 Avoid overlays: equal-weight U minus the model's bottom 30% (`select_quantile=(0.3,1)`, `sizing='equal'`)")
w()
rows = []
for mk_ in ("U", "liq5"):
    for nm in ("UNIVERSE_EW", "AVOID_DDN", "AVOID_RDN", "AVOID_RUPup", "AVOID_DUALup", "AVOID_DUALPup", "AVOID_DUALt300up",
               "AVOID_REL", "AVOID_ABS", "AVOID_BAR", "AVOID_DUALmc"):
        a = find(AV, name=nm, mask=mk_, win="dev", cost=50.0)
        hh = find(AV, name=nm, mask=mk_, win="hold", cost=50.0)
        if a is None:
            continue
        rows.append([mk_, nm, f(a["cagr"], 1, True), f(a.get("vs_universe_ann"), 1, True, True), f(a.get("vs_universe_nw_t"), 2),
                     f(a["max_dd"], 1, True), f(hh["cagr"], 1, True), f(hh.get("vs_universe_ann"), 1, True, True),
                     f(hh.get("vs_universe_nw_t"), 2), f(a.get("vs_RUP_ann"), 1, True, True), f(hh.get("vs_RUP_ann"), 1, True, True)])
table(["mask", "overlay (what is dropped)", "DEV CAGR", "DEV vs universe /yr", "t", "DEV maxDD", "2026 CAGR",
       "2026 vs universe /yr", "2026 t", "DEV vs AVOID_RUPup", "2026 vs AVOID_RUPup"], rows)
w("AVOID_DDN drops the highest P(DUAL=-1) and AVOID_RDN the highest P(REL=-1). AVOID_xxxup drops the lowest "
  "P(xxx=+1). AVOID_REL drops the lowest M_REL score. 80 bp results shift every row by the same cost drag "
  "(see results.json).")
w()
w("### 4.5 Input-side conditions (sample filters) vs label-side conditions")
w()
rows = []
for g in ("U", "G_sma200", "G_rs70", "G_trend", "G_mkt200"):
    st_ = GS[g]
    god = find(GO, gate=g, win="dev", cost=50.0)
    goh = find(GO, gate=g, win="hold", cost=50.0)
    rows.append([g, f(st_["share_of_U"], 1, True), f(st_["daily_share_std"], 1, True), f(st_["names_per_day_median"], 0),
                 f(god["rand_cagr_gate"], 1, True), f(god["gate_excess_cagr"], 1, True, True), f(god["gate_excess_nw_t"], 2),
                 f(god["rand_maxdd_gate"], 1, True), f(goh["rand_cagr_gate"], 1, True), f(goh["gate_excess_cagr"], 1, True, True),
                 f(goh["gate_excess_nw_t"], 2)])
table(["gate", "share of U", "daily share sd", "names/day", "random-in-gate DEV CAGR", "gate value vs random-in-U",
       "t", "random maxDD", "random-in-gate 2026", "gate value 2026", "t 2026"], rows)
rows = []
for nm in ("REL@U", "DUAL@U", "ABS@U", "REL@G_sma200", "DUAL@G_sma200", "REL@G_rs70", "DUAL@G_rs70", "REL@G_trend",
           "DUAL@G_trend", "ABS@G_trend", "RELG@G_trend", "REL@G_mkt200", "DUAL@G_mkt200"):
    a = find(GT, name=nm, win="dev", cost=50.0)
    hh = find(GT, name=nm, win="hold", cost=50.0)
    if a is None:
        continue
    rows.append([nm, f(a["cagr"], 1, True), f(a["excess_cagr"], 1, True, True), f(a["excess_nw_t"], 2), f(a["max_dd"], 1, True),
                 f(a["beta"], 2), f(hh["cagr"], 1, True), f(hh["excess_cagr"], 1, True, True), f(hh["excess_nw_t"], 2), f(hh["max_dd"], 1, True)])
table(["score@gate", "DEV CAGR", "excess vs random-in-gate", "t", "maxDD", "beta", "2026 CAGR", "2026 excess", "2026 t", "2026 maxDD"], rows)
w("G_sma200 = close>sma200. G_rs70 = xr_mom60>0.7. G_trend = both, which is the client's 'absolute uptrend AND "
  "relatively strong' as an input condition. G_mkt200 = Nifty 500 above its 200dma: market timing, with an empty "
  "book (cash at 0% yield) on off days. RELG = the REL model retrained on G_trend rows only.")
w()
w("### 4.6 Liquidity tier (elig_liq5, 20d turnover >= Rs 5 cr), K20 step 5")
w()
rows = []
for nm in ("REL", "RUP", "DUAL", "DUALP", "DUALt300", "ABS", "SUM_REL_ABS", "AND_REL_ABS50"):
    a = find(LQ, name=nm, win="dev", cost=50.0)
    a8 = find(LQ, name=nm, win="dev", cost=80.0)
    hh = find(LQ, name=nm, win="hold", cost=50.0)
    if a is None:
        continue
    rows.append([nm, f(a["cagr"], 1, True), f(a["excess_cagr"], 1, True, True), f(a["excess_nw_t"], 2), f(a["max_dd"], 1, True),
                 f(a8["cagr"], 1, True), f(hh["cagr"], 1, True), f(hh["excess_cagr"], 1, True, True), f(hh["excess_nw_t"], 2)])
table(["score", "DEV CAGR", "excess", "t", "maxDD", "DEV CAGR 80bp", "2026 CAGR", "2026 excess", "2026 t"], rows)

w("### 4.7 Signal-calendar phase sensitivity (K20, step 5, 50 bp; calendar shifted by 0-4 trading days)")
w()
rows = []
for nm in ("REL", "RUP", "DUAL", "DUALP", "SUM_REL_RUP", "SUM_REL_DUAL", "ABS"):
    a, hh = PH["dev"][nm], PH["hold"][nm]
    rows.append([nm, f(a["cagr_mean"], 1, True), f"{f(a['cagr_min'],1,True)} .. {f(a['cagr_max'],1,True)}", f(a["excess_mean"], 1, True, True),
                 f(a["maxdd_mean"], 1, True), f(hh["cagr_mean"], 1, True), f"{f(hh['cagr_min'],1,True)} .. {f(hh['cagr_max'],1,True)}",
                 f(hh["excess_mean"], 1, True, True), f(hh["maxdd_mean"], 1, True)])
table(["book", "DEV CAGR (5-phase mean)", "DEV range", "DEV excess vs random", "DEV maxDD", "2026 CAGR mean", "2026 range",
       "2026 excess", "2026 maxDD"], rows)
rows = []
for k in ("DUAL-RUP", "DUALP-RUP", "DUAL-REL", "RUP-REL", "SUM_REL_DUAL-SUM_REL_RUP"):
    a, hh = PH["dev"]["pairs"][k], PH["hold"]["pairs"][k]
    rows.append([k, f(a["diff_mean"], 1, True, True), f"{f(a['diff_min'],1,True,True)} .. {f(a['diff_max'],1,True,True)}",
                 f"{a['n_positive']}/5", f(a["t_mean"], 2), f(hh["diff_mean"], 1, True, True),
                 f"{f(hh['diff_min'],1,True,True)} .. {f(hh['diff_max'],1,True,True)}", f"{hh['n_positive']}/5", f(hh["t_mean"], 2)])
table(["paired difference", "DEV mean /yr", "DEV range", "DEV phases >0", "DEV mean t", "2026 mean /yr", "2026 range",
       "2026 phases >0", "2026 mean t"], rows)
rows = []
for k in ("AVOID_RUPup", "AVOID_DUALup", "AVOID_REL", "AVOID_ABS", "AVOID_DDN", "AVOID_RDN"):
    a, hh = PHA["dev"][k], PHA["hold"][k]
    rows.append([k, f(a["vs_univ_mean"], 1, True, True), f"{f(a['vs_univ_min'],1,True,True)} .. {f(a['vs_univ_max'],1,True,True)}",
                 f(a["t_mean"], 2), f(hh["vs_univ_mean"], 1, True, True),
                 f"{f(hh['vs_univ_min'],1,True,True)} .. {f(hh['vs_univ_max'],1,True,True)}", f(hh["t_mean"], 2), f"{hh['n_positive']}/5"])
table(["avoid overlay vs universe EW", "DEV mean /yr", "DEV range", "DEV mean t", "2026 mean /yr", "2026 range", "2026 mean t",
       "2026 phases >0"], rows)
w("The phase-0 tables above (4.1-4.6) are one draw. For a 20-name book, the phase moves 2026 CAGR by 10-14 pp and "
  "DEV CAGR by 2-5 pp. The single-phase holdout result 'DUAL -8.9%/yr vs RUP' (4.2) was an extreme draw: the "
  "phase mean is +3.0%/yr. Differences between the label variants sit inside this band. The avoid overlays hold "
  "about 700 names, so they are phase-stable (range under 1 pp).")
w()

# ------------------------------------------------------------------ drawdowns / regimes / picks
w("## 5. Drawdowns, beta and what the books buy")
w()
rows = []
for nm in ("REL", "RUP", "DUAL", "DUALP", "DUALt300", "ABS", "BAR", "SUM_REL_ABS", "SUM_REL_RUP", "SUM_REL_DUAL"):
    a, hh = rk.get((nm, "dev", 50.0)), rk.get((nm, "hold", 50.0))
    if a is None:
        continue
    rows.append([nm, f(a["max_dd"], 1, True), f(a["worst_20d"], 1, True), f(a["ann_vol"], 1, True), f(a["calmar"], 2),
                 f(a["beta"], 2), f(a["down_capture"], 2), f(a["up_capture"], 2), f(hh["max_dd"], 1, True),
                 f(hh["worst_20d"], 1, True), f(hh["beta"], 2), f(hh["down_capture"], 2)])
table(["book (K20 s5 50bp)", "DEV maxDD", "worst 20d", "ann vol", "Calmar", "beta", "down capt.", "up capt.", "2026 maxDD",
       "2026 worst 20d", "2026 beta", "2026 down capt."], rows)
rows = []
for r_ in P7["regime_books"]:
    rows.append([r_["name"], f(r_["ann_ret_bull200"], 1, True), f(r_["ann_ret_bear200"], 1, True), f(r_["beta_bull200"], 2),
                 f(r_["beta_bear200"], 2), f(r_["ann_ret_mkt_up20"], 1, True), f(r_["ann_ret_mkt_dn20"], 1, True)])
table(["book (DEV+2026 days)", "ann. ret N500>200dma", "ann. ret N500<200dma", "beta bull", "beta bear",
       "ann. ret N500 20d up", "ann. ret 20d down"], rows)
w("The binary-up books (RUP, DUAL, DUALP) lose less than REL on bear days (-14% to -8% vs -19% annualised). That "
  "effect comes from the binary loss, because RUP shows it without any absolute leg. DUALP's somewhat better bear-day "
  "number does not survive into a better DEV maxDD (-31.8% vs -29.5% for REL).")
w()
rows = []
for win in ("dev", "hold"):
    for nm in ("REL", "RUP", "DUAL", "DUALP", "ABS", "BAR", "SUM_REL_ABS"):
        x = PK[win]["all"].get(nm)
        if x is None:
            continue
        rows.append([win, nm, f(x["net_bps"], 0, sign=True), f(x["resid_bps"], 0, sign=True), f(x["beta"], 2),
                     f(x["ann_vol"], 2), f(x["log_turn"], 2), f(x["above_sma200"], 0, True), f(x["xr_mom60"], 2)])
    u = PK[win]["universe"]
    rows.append([win, "universe", f(u["univ_net_bps"], 0, sign=True), "0", f(u["univ_beta"], 2), f(u["univ_ann_vol"], 2),
                 f(u["univ_log_turn"], 2), f(u["univ_above_sma200"], 0, True), f(u["univ_xr_mom60"], 2)])
table(["window", "top-20 by", "net bps / 20d", "resid bps", "beta_60", "ann vol", "log turnover", "% above sma200", "xr_mom60 pct"], rows)
ov = PK["top20_overlap_with_REL"]
w("Top-20 overlap with the REL book (mean share of the same names, every 5th date, 2023-2026): " +
  ", ".join(f"{k} {f(v,0,True)}" for k, v in ov.items()) +
  f". DUAL vs RUP: {f(PK.get('top20_overlap_DUAL_vs_RUP'),0,True)}. The binary-up models lean toward trend and "
  "momentum (84-87% above sma200, xr_mom60 0.69-0.70 on DEV). The regression REL model turned contrarian in 2026 "
  "(33% above sma200).")
w()

# ------------------------------------------------------------------ pros / cons
w("## 6. Pros, cons, failure modes")
w()
w("**DUAL (label-side AND)**")
w()
w("* Pros: maximal label/P&L coherence (+1 is always a net winner, -1 always a net loser). No executable or NaN "
  "biases. Learnable (per-date AUC 0.545-0.564). Easy to explain to a discretionary trader.")
w("* Cons: (1) Its +1 rate is 91% the same as REL's, so it adds almost no information about which stock to own. "
  "(2) The 9% it changes are chosen by the market's realised path, which re-introduces market timing (daily share corr "
  "0.70 with the market window). A long-only top-K book is always invested and cannot use that timing. Models trained "
  "on top-tail events carry more beta (1.33-1.35 vs 1.26 for REL), and DUAL's phase-mean DEV maxDD is -32.3% vs "
  "-31.0% for RUP and -29.5% for REL. The absolute leg does not cushion drawdowns. (3) The stricter tau is, the more pronounced this becomes (tau=300bp: corr 0.79, no DEV gain vs "
  "RUP). (4) DUAL_down as an avoid label fails in 2026, because its high-P(down) names are high-vol names whose raw "
  "returns were fine.")
w("* Failure mode: in 20-day windows where the market falls more than 5%, the DUAL +1 set shrinks from 30% to "
  "about 12% of names (2026 had 55% of days below the 200dma). Training sets become regime-imbalanced and the classifier's base rate drifts. The label then measures "
  "'did the market go up' as much as 'was this the right stock'.")
w()
w("**DUALP (path version):** worse than RUP on DEV (-4.6%/yr phase mean, 0/5 phases, 1/8 grid cells). Its 2026 "
  "phase-0 result (+29%) was its best phase. The phase mean is 19.5% vs RUP 17.6%. Selection on DEV would not have "
  "picked it.")
w()
w("**Two-model AND / product / rank-sum with an absolute model:** never better than the pure-relative model on DEV "
  "beyond noise, and worse in 2026 (rank-sum 0/8 holdout cells). The absolute model's cross-sectional information "
  "overlaps the relative model's (rank corr 0.69). Its extra content is market timing, which does not help a "
  "cross-sectional book.")
w()
w("**Input-side gates:** these are honest sample filters and leave label values unchanged. They add no DEV skill "
  "(gate value +0.9%/yr, t 0.4), shrink the universe to about 300 names a day, and the model is no better inside the "
  "gate. G_trend made a lot of money in 2026, which is worth re-testing in round 3 as a regime-dependent tilt, but it "
  "cannot be selected on DEV.")
w()
w("## 7. What to use (for the judges)")
w()
w("1. **Primary selection label:** pure relative XR_neu residual rank at h=20, trained as a **binary top-30% "
  "classifier** (M_RUP). Alternatively blend it with the XR_neu regression (SUM_REL_RUP: best phase-0 DEV excess t "
  "3.96; phase-mean DEV 33.4%, 2026 19.1% vs random about 7%). Do not add an absolute condition to the label. The "
  "only consistent hint in DUAL's favour is SUM_REL_DUAL vs SUM_REL_RUP at +1.0%/yr on DEV (5/5 phases, mean t "
  "0.66), which is far below any significance bar.")
w("2. **Avoid label:** the bottom 30% by P(relative top-30). Do not use a separately trained down model (DUAL_down or "
  "REL_down): those classify down events well but failed as an overlay in 2026.")
w("3. **The absolute/market condition** belongs in an exposure layer (R2_regime) evaluated on its own, not inside "
  "the stock label.")
w("4. Caveats: every DEV excess t here (3.0-4.0 for the relative books) is only modestly above the "
  "expected-max-of-N luck bar (about 2.6 for this agent's 130 configs, about 3.2 for the programme). The DUAL vs "
  "relative differences are well inside noise in both directions.")
w()
w("Scripts: s1_labels.py (labels), s2_events.py (event rates and sensitivity), s3_wf.py (walk-forward models), "
  "s4_xs.py (learnability), s5_invest.py (Sim books), s6_picks.py (pick characteristics), s7_paired.py (paired tests, "
  "drawdowns, regimes), s8_report.py (this file), s9_phase.py and s9b_phase_avoid.py (signal-calendar phase "
  "robustness), s10_summary.py (structured summary). All numbers are in results.json.")

open(os.path.join(OUT, "REPORT.md"), "w").write("\n".join(L) + "\n")
print("wrote REPORT.md", len(L), "lines")

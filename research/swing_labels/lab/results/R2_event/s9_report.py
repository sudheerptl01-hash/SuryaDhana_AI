"""Stage 9: generate REPORT.md (all tables pulled from results.json / saved grids) + final_summary."""
import json

import numpy as np
import pandas as pd
from scipy.stats import norm

from common import OUT, save, eq_stats

R = json.load(open(f"{OUT}/results.json"))
g2 = pd.read_csv(f"{OUT}/s2_grid.csv")
s3 = pd.read_pickle(f"{OUT}/s3_sim.pkl")
s4 = pd.read_pickle(f"{OUT}/s4_sim.pkl")
ser = np.load(f"{OUT}/s5_series.npz")
L_ = []


def w(s=""):
    L_.append(s)


def pct(x, d=1):
    return "n/a" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{100 * x:.{d}f}%"


def bps(x, d=0):
    return "n/a" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:+.{d}f}"


def num(x, d=2):
    return "n/a" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.{d}f}"


def table(header, rows):
    w("| " + " | ".join(header) + " |")
    w("|" + "|".join(["---"] * len(header)) + "|")
    for r in rows:
        w("| " + " | ".join(str(c) for c in r) + " |")
    w()


def g2row(d, h):
    r = g2[(g2["def"] == d) & (g2.h == h)]
    return r.iloc[0] if len(r) else None


s2 = R["s2_eventstudy"]
det = R["s2_detail"]
iso = R["s6_isolated"]
N_tests, z_b = iso["N_tests"], iso["bonferroni_z"]
ANCH, SEL = "R1|L20|v1|mom20dn", "R1|L10|v0|mom20dn_brd5"
rob = R["s6_sleeve_robust"]
chk = R["s7_checks"]
s5 = R["s5_combo"]
stack = R["s6_stack"]
learn = R["s4_learn"]
xsi = R["s6_xs_indicator"]
ov = R["s6_core_overlap"]
locks = R["s8_locks"]
bench = R["s3_sim"]["benchmark"]

# ---------------------------------------------------------------- variant count
n_cells = iso["N_cells"]
dev50 = s3[(s3.win == "dev") & (s3.cost == 50)]
n_s3 = len(dev50)
n_s4 = len(s4[(s4.win == "dev") & (s4.cost == 50) & (s4.score != "ALL_EVENTS")])
n_s5 = 6 * 2 * 3
n_extra = 2 + 2 + 4          # stack variants, OS sleeves, lag-1 sleeves
n_port = n_s3 + n_s4 + n_s5 + n_extra
n_wf = 2
z_port = float(norm.ppf(1 - 0.05 / n_port))
variants_total = n_cells + n_port + n_wf

# ================================================================ REPORT
w("# R2_event: capitulation-reversal event sleeve (lab v2)")
w()
w("Agent R2_event, round 2. Lab v2 only: no sector data, ETFs excluded, `elig_base` as rebuilt. Entry at open[t+1] "
  "and time exit at close[t+h]. Labels are NaN unless `fw.ok(h)`, and event gates choose sample rows without changing "
  "label values. Models use `L.walk_forward2`, investability uses `L.Sim` (bit-identical copy `SimX` that also returns "
  "the daily invested fraction), and learnability uses `L.xs_metrics` plus month-cluster t. Costs are 50 bps (80 and "
  "130 bps stress). Selection is on DEV only: signals 2023-01-01 to the last date whose exit is on or before "
  "2025-12-31. The 2026 holdout (to 2026-10-14) is reported separately and never used to choose. PRE (2021-22) "
  "is shown for information only.")
w()
w("## 1. Headline")
w()
a10 = g2row(ANCH, 10)
s10 = g2row(SEL, 10)
w(f"* **The capitulation reversal is real on lab v2, but it is a market-breadth effect, not a stock effect.** The "
  f"round-1 gate R1dn is close < prior 20-day low, volz_20 > 1, Nifty-500 20d momentum < 0. At h=10 it has DEV excess "
  f"of {bps(a10.dev_xs_bps)} bps per event versus the same-date universe mean (month-cluster t {num(a10.dev_xs_t_month)}). "
  f"That passes Bonferroni over all {N_tests} event tests in this study (|z| > {num(z_b)}). Weighting each event *day* "
  f"equally, the excess is only {bps(a10.dev_xs_dw_bps)} bps (t {num(a10.dev_xs_dw_t_month)}). The edge lives on "
  f"mass-breakdown days. On days when fewer than 2% of the universe make new 20-day lows, R1dn events earn "
  f"{bps(det[ANCH]['10']['brd_buckets_dev']['0.00-0.02']['xs_bps'])} bps (DEV) and "
  f"{bps(det[ANCH]['10']['brd_buckets_hold']['0.00-0.02']['xs_bps'])} bps (2026). On days when 20% or more do, they "
  f"earn {bps(det[ANCH]['10']['brd_buckets_dev']['0.20-1.01']['xs_bps'])} / "
  f"{bps(det[ANCH]['10']['brd_buckets_hold']['0.20-1.01']['xs_bps'])} bps.")
w(f"* **Adding a breadth gate turns it into a tradable event label.** The gate requires at least 5% of eligible names "
  f"at new 20-day lows in a falling market. The selected gate A1 (`{SEL}`) was chosen by a pre-declared DEV rule: "
  f"maximise the date-weighted t. At h=10 it has DEV excess {bps(s10.dev_xs_bps)} bps (t {num(s10.dev_xs_t_month)}), "
  f"date-weighted {bps(s10.dev_xs_dw_bps)} bps (t {num(s10.dev_xs_dw_t_month)}); both pass Bonferroni. The 2026 "
  f"holdout is {bps(s10.hold_xs_bps)} bps (t {num(s10.hold_xs_t_month)}). It fires on "
  f"{pct(s10.dev_share_days_with_event, 0)} of DEV days with about "
  f"{s10.dev_events_per_event_day:.0f} names per event day. There were 56 washout episodes in 2021-26.")
rm5 = rob["h5|50|dev"]
rm5h = rob["h5|50|hold"]
rm10 = rob["h10|50|dev"]
rm10h = rob["h10|50|hold"]
w(f"* **As a sleeve (L.Sim, daily signal calendar, 20 slots per daily sleeve, idle cash at 0%) the edge is small in "
  f"absolute terms because capital is idle about 85% of the time.** A1, all events, h=10: DEV CAGR "
  f"{pct(rm10['all_cagr'])} at 50 bps against {pct(rm10['matched_cagr'])} for a count-matched random-stock sleeve "
  f"on the same days. Ranking the events with a walk-forward meta-model (relative target) and buying the top 20 gives "
  f"DEV CAGR {pct(rm5['meta_cagr'])} (h=5), Sharpe {num(rm5['meta_sharpe'])}, maxDD {pct(rm5['meta_max_dd'])}, at "
  f"{pct(rm5['meta_exposure'], 0)} exposure. That is {pct(rm5['meta_vs_all_ann'])}/yr over all events (NW t "
  f"{num(rm5['meta_vs_all_nw_t'])}) and {pct(rm5['meta_vs_matched_ann'])}/yr over matched random (t "
  f"{num(rm5['meta_vs_matched_nw_t'])}).")
w(f"* **2026 holdout (not used for selection):** the edge over baselines survives but absolute returns depend on the "
  f"horizon. The DEV-selected h=5 meta sleeve made {pct(rm5h['meta_cagr'])} against {pct(rm5h['matched_cagr'])} for "
  f"matched random (excess t {num(rm5h['meta_vs_matched_nw_t'])}). The h=10 version made {pct(rm10h['meta_cagr'])} "
  f"against {pct(rm10h['matched_cagr'])} (t {num(rm10h['meta_vs_matched_nw_t'])}). Nifty 500 returned "
  f"{pct(bench['hold']['cagr'])} annualised over the same window. 2026 washouts kept falling for weeks before "
  f"rebounding, so 5-day holds sold too early.")
c50 = s5["50|dev"]
c50h = s5["50|hold"]
w(f"* **It does not improve the relative core book.** The core is R2_rel's h20_neumom_RANK, top-20: DEV CAGR "
  f"{pct(c50['core']['cagr'])}, 2026 {pct(c50h['core']['cagr'])}. Parking the sleeve's idle capital in the core "
  f"(overlay, 20%) gives DEV {pct(c50['sleeves']['S5_META']['combos']['OVL20']['cagr'])} and 2026 "
  f"{pct(c50h['sleeves']['S5_META']['combos']['OVL20']['cagr'])}, both below the core. A tilt of the core toward "
  f"gate events also loses ({pct(stack['CORE_TILT_A1_0.3|50|dev']['d_vs_core_ann'])}/yr DEV). The core already holds "
  f"{pct(ov['share_core_top20_that_are_events'], 0)} gate events on gate days, against a "
  f"{pct(ov['base_share_events_in_U'], 0)} base rate. When the sleeve is active, its daily correlation with the core "
  f"is {num(c50['sleeves']['S5_META']['corr']['daily_when_sleeve_active'])}, because both are long a falling market.")
qcr10 = [r for r in iso["rows"] if r["def"] == "Q_CR|k3" and r["h"] == 10][0]
w(f"* **Other overreaction events (Bonferroni over {N_tests} tests):** none gives an investable long edge. Large "
  f"down days and recovered gap-downs *continue* when the market is quiet: quiet-day crash (Q_CR k3) has DEV excess "
  f"{bps(qcr10['dev_xs_bps'])} bps at h=10 (t {num(qcr10['dev_xs_t_month'])}), and all-day crashes have day-weighted "
  f"excess of -90 to -136 bps (t -4.1 to -5.5). The continuation faded in 2026 (Q_CR k3 {bps(qcr10['hold_xs_bps'])} bps, "
  f"t {num(qcr10['hold_xs_t_month'])}), and an avoid filter built on it did not help the core in DEV. Oversold names "
  f"(RSI < 20) in a falling market pass Bonferroni at h=5 as events but lose as a sleeve in 2026. 5-day cross-sectional "
  f"losers and 52-week lows on volume show no edge.")
w(f"* **Verdict.** The breadth-gated capitulation label is **promising** as an *event sleeve for capital that is not "
  f"already in the core book*, for example the cash buffer of a client who runs below 100% gross. It is **not** "
  f"promising as an add-on to a fully invested relative book. Use it as a descriptive regime fact: buy washouts, not "
  f"isolated breakdowns. Variants tried: {variants_total} ({n_cells} event-study cells x 2 statistics = {N_tests} "
  f"tests; {n_port} distinct DEV portfolio specs; {n_wf} new walk-forward models plus 2 reused from R2_rel).")
w()

# ---------------------------------------------------------------- definitions
w("## 2. Definitions")
w()
w("```")
w("U        = elig_base (lab v2)                                    r_h = open[t+1] -> close[t+h], NaN unless fw.ok(h)")
w("x_h      = r_h - mean_U,same date(r_h)   (date-matched excess; removes market timing)")
w("brd_t    = share of U rows with close[t] < min(low[t-20..t-1])  (new-20d-low breadth, PIT at close t)")
w("R1(L,v,M)= U & close[t] < min(low[t-L..t-1]) & volz_20 > v & market filter M")
w("           M in {none, mkt_mom20<0 (mom20dn), mkt_dist_sma200<0 (sma200dn), brd>=5%, brd>=10%, mom20dn & brd>=5%}")
w(f"ANCHOR   = R1(20, 1, mom20dn)        (round-1 R1dn)")
w(f"A1 (SEL) = R1(10, 0, mom20dn & brd>=5%)   (DEV-selected: max date-weighted DEV t at h=10 among cells with >=500 events)")
w("Event label: on event rows, +1 if r_h > 50 bps (net positive) else -1 (absolute); relative view +1 if x_h > 0.")
w("Sleeve   = L.Sim step=1 (h daily sleeves, each 1/h of capital), top_k=20 slots/sleeve (slot = 1/(20h)), idle cash 0%;")
w("           'all events' = random tie-break among the day's events (5 seeds) = S.compare's same-mask random arm;")
w("           'matched'    = count-matched universe random: each day as many random U names as the sleeve holds events.")
w("```")
w()
w("Baselines. `S.compare` draws its random arm from the *same mask*, so on an event mask it measures only the ranking "
  "*within* events. The event effect itself is measured against the **count-matched universe random** sleeve: same "
  "days, same number of names, same exposure, random stocks. Both are reported, with NW t at lag h and month-cluster t.")
w()

# ---------------------------------------------------------------- re-validation
w("## 3. Re-validation of R1dn on lab v2 (event study, no model)")
w()
w("Table 3.1: ANCHOR R1dn and selected A1 by horizon. 'ew' weights each event equally; 'dw' weights each event day "
  "equally (closer to a slot-sized sleeve). t uses month clusters.")
rows = []
for d in (ANCH, SEL):
    for h in (5, 10, 20):
        r = g2row(d, h)
        for wn in ("dev", "hold", "pre"):
            rows.append([("ANCHOR" if d == ANCH else "A1") if wn == "dev" else "", h if wn == "dev" else "", wn,
                         int(r[f"{wn}_n"]), f"{100 * r[f'{wn}_share_days_with_event']:.0f}%",
                         f"{r[f'{wn}_events_per_event_day']:.0f}", num(r[f"{wn}_p_net_pos"], 3),
                         bps(r[f"{wn}_net_bps"]), f"{bps(r[f'{wn}_xs_bps'])} ({num(r[f'{wn}_xs_t_month'])})",
                         f"{bps(r[f'{wn}_xs_dw_bps'])} ({num(r[f'{wn}_xs_dw_t_month'])})",
                         num(r[f"{wn}_xs_t_quarter"])])
table(["gate", "h", "window", "events", "% days", "events/event-day", "P(net50>0)", "net50 bps", "xs ew bps (t)",
       "xs dw bps (t)", "xs t (qtr clusters)"], rows)
w("Table 3.2: by calendar year, h=10 (2021-22 = PRE, 2023-25 = DEV, 2026 = holdout).")
rows = []
for d, nm in ((ANCH, "ANCHOR"), (SEL, "A1")):
    by = det[d]["10"]["stats"]["by_year"]
    for y in sorted(by):
        o = by[y]
        rows.append([nm, y, o["n"], o["event_days"], num(o["p_net_pos"], 3), bps(o["net_bps"]), bps(o["xs_bps"])])
table(["gate", "year", "events", "event days", "P(net50>0)", "net50 bps", "xs bps"], rows)
w("Table 3.3: mass-day dependence for ANCHOR (h=10). Buckets are by the number of R1dn events that day, and by brd "
  "(share of U at new 20d lows).")
rows = []
for kind in ("count", "brd"):
    for wn in ("dev", "hold"):
        bk = det[ANCH]["10"][f"{kind}_buckets_{wn}"]
        for k, o in bk.items():
            rows.append([kind, wn, k, o["n"], o["days"], num(o["p_net_pos"], 3) if o["p_net_pos"] is not None else "n/a",
                         bps(o["net_bps"]), bps(o["xs_bps"])])
table(["bucket by", "window", "bucket", "events", "days", "P(net50>0)", "net50 bps", "xs bps"], rows)
w("Isolated breakdowns continue down. The reversal is a *market* washout phenomenon. Excess rises with breadth "
  "from the lowest to the highest bucket: DEV -20 to +82 bps, 2026 -112 to +97/+145 bps. It is not strictly "
  "monotone in the middle buckets. This is why the breadth gate, not the volume or lookback threshold, is the "
  "parameter that matters.")
w()
w("Table 3.4: month concentration of the excess (h=10).")
rows = []
for d, nm in ((ANCH, "ANCHOR"), (SEL, "A1")):
    for wn in ("dev", "hold"):
        c = det[d]["10"][f"conc_{wn}"]
        rows.append([nm, wn, c["months_with_events"], num(c["share_months_xs_pos"], 2), num(c["top1_share_xs"], 2),
                     num(c["top3_share_xs"], 2), num(c["top5_share_xs"], 2), num(c["top5_share_net"], 2),
                     num(c["top5_share_events"], 2), bps(c["xs_excl_top1_bps"]), bps(c["xs_excl_top3_bps"]),
                     bps(c["xs_excl_top5_bps"]), bps(c["lomo_min_xs_bps"]), num(c["eff_n_months_pos_xs"], 1)])
table(["gate", "window", "months w/ events", "share months xs>0", "top1 share xs", "top3", "top5", "top5 share net",
       "top5 share events", "xs excl top1", "excl top3", "excl top5", "leave-one-month-out min", "eff. # months"], rows)
tm = det[ANCH]["10"]["conc_dev"]["top_months"]
w("ANCHOR's top DEV months: " + ", ".join(f"{m['month']} ({m['n']} events, {bps(m['xs_bps'])} bps, "
                                          f"{100 * m['share_xs']:.0f}% of xs)" for m in tm[:5]) + ".")
w(f"In 2026, ANCHOR's excess is one month (top1 share {num(det[ANCH]['10']['conc_hold']['top1_share_xs'])}; "
  f"excluding it {bps(det[ANCH]['10']['conc_hold']['xs_excl_top1_bps'])} bps). A1 is less concentrated "
  f"(top1 {num(det[SEL]['10']['conc_hold']['top1_share_xs'])}; excluding it "
  f"{bps(det[SEL]['10']['conc_hold']['xs_excl_top1_bps'])} bps). Washout episodes (runs of days with brd >= 10%): "
  f"{len(s2['episodes_brd10'])} in 2021-26, by start year {s2['episodes_by_start_year']}.")
w()

# ---------------------------------------------------------------- sensitivity
w("## 4. Parameter sensitivity: how event rates and the edge move (h=10 unless noted)")
w()


def sens_rows(defs, label_fn):
    rows = []
    for d in defs:
        r = g2row(d, 10)
        if r is None:
            continue
        rows.append([label_fn(d), int(r.dev_n), f"{r.dev_n / 3:.0f}", f"{100 * r.dev_share_days_with_event:.0f}%",
                     f"{r.dev_events_per_event_day:.0f}", num(r.dev_p_net_pos, 3), bps(r.dev_net_bps),
                     f"{bps(r.dev_xs_bps)} ({num(r.dev_xs_t_month)})", f"{bps(r.dev_xs_dw_bps)} ({num(r.dev_xs_dw_t_month)})",
                     f"{bps(r.hold_xs_bps)} ({num(r.hold_xs_t_month)})", int(r.hold_n)])
    return rows


H = ["variant", "DEV events", "events/yr", "% DEV days", "events/event-day", "P(net50>0)", "net50 bps", "xs ew (t)",
     "xs dw (t)", "2026 xs (t)", "2026 events"]
w("Table 4.1: volume threshold (L=20, M=mom20dn).")
table(H, sens_rows([f"R1|L20|{v}|mom20dn" for v in ("vnone", "v0", "v0.5", "v1", "v2")], lambda d: d.split("|")[2]))
w("Table 4.2: lookback (v=1, M=mom20dn).")
table(H, sens_rows([f"R1|L{l}|v1|mom20dn" for l in (10, 20, 40)], lambda d: d.split("|")[1]))
w("Table 4.3: market filter (L=20, v=1).")
table(H, sens_rows([f"R1|L20|v1|{m}" for m in ("none", "mom20dn", "sma200dn", "brd5", "brd10", "mom20dn_brd5")],
                   lambda d: d.split("|")[3]))
w("Table 4.4: market filter (L=10, v=0; the selected cell is mom20dn_brd5).")
table(H, sens_rows([f"R1|L10|v0|{m}" for m in ("none", "mom20dn", "sma200dn", "brd5", "brd10", "mom20dn_brd5")],
                   lambda d: d.split("|")[3]))
w("Table 4.5: plateau map. DEV date-weighted xs t at h=10 for every lookback x volume cell under three market "
  "filters (2026 date-weighted xs bps in brackets).")
rows = []
for m in ("mom20dn", "mom20dn_brd5", "brd10"):
    for l in (10, 20, 40):
        rr = [m if l == 10 else "", f"L{l}"]
        for v in ("vnone", "v0", "v0.5", "v1", "v2"):
            r = g2row(f"R1|L{l}|{v}|{m}", 10)
            rr.append(f"{num(r.dev_xs_dw_t_month)} [{bps(r.hold_xs_dw_bps)}]")
        rows.append(rr)
table(["filter", "lookback", "v none", "v>0", "v>0.5", "v>1", "v>2"], rows)
r1 = g2[(g2.family == "R1") & (g2.h == 10)]


def dwr(m):
    sub = r1[r1["def"].str.split("|").str[3] == m].dev_xs_dw_t_month
    return f"{sub.min():.1f} to {sub.max():.1f} (median {sub.median():.1f})"
w(f"Reading the sensitivity. (i) Event rates scale with the filters as expected. Volume > 2 cuts events about "
  f"{g2row('R1|L20|vnone|mom20dn', 10).dev_n / g2row('R1|L20|v2|mom20dn', 10).dev_n:.0f}x relative to no volume "
  f"filter. L=40 fires about {g2row('R1|L20|v1|mom20dn', 10).dev_n / g2row('R1|L40|v1|mom20dn', 10).dev_n:.1f}x less "
  f"than L=20. The breadth gate cuts the share of event days from about 35% to 13-16% but *raises* events per event "
  f"day to more than 100. (ii) Event-weighted excess is positive in "
  f"{int((r1.dev_xs_bps > 0).sum())}/{len(r1)} R1 cells and in 2026 in {int((r1.hold_xs_bps > 0).sum())}/{len(r1)}. "
  f"It is a broad plateau and not a lucky cell. (iii) The day-weighted excess depends on the market filter. Its DEV t "
  f"ranges by filter: none {dwr('none')}, mom20dn {dwr('mom20dn')}, sma200dn {dwr('sma200dn')}, brd5 {dwr('brd5')}, "
  f"brd10 {dwr('brd10')}, mom20dn_brd5 {dwr('mom20dn_brd5')}. With no market filter it is negative in every cell, "
  f"because isolated breakdowns continue. Filters that select washout conditions (breadth, bear market) create it. "
  f"Within a filter, lookback matters little. High volume thresholds (v>2) weaken it because they leave too few names "
  f"per washout day.")
w()
w("Table 4.6: horizon for A1 (event study).")
rows = []
for h in (5, 10, 20):
    r = g2row(SEL, h)
    rows.append([h, int(r.dev_n), num(r.dev_p_net_pos, 3), bps(r.dev_net_bps), f"{bps(r.dev_xs_bps)} ({num(r.dev_xs_t_month)})",
                 f"{bps(r.dev_xs_dw_bps)} ({num(r.dev_xs_dw_t_month)})", f"{bps(r.hold_xs_bps)} ({num(r.hold_xs_t_month)})",
                 bps(r.hold_net_bps)])
table(["h", "DEV events", "P(net50>0)", "net50 bps", "xs ew (t)", "xs dw (t)", "2026 xs (t)", "2026 net50 bps"], rows)

# ---------------------------------------------------------------- event-rate scorecard
w("## 5. Event-rate scorecard (h=10)")
w()
for d, nm in ((SEL, "A1 (selected)"), (ANCH, "ANCHOR R1dn")):
    rl = det[d]["10"]["regime_liq"]
    mc = det[d]["10"]["monthly_corr"]
    w(f"**{nm}.** Monthly P(net50>0) on months with events: mean {num(mc['monthly_pnet_mean'])}, std "
      f"{num(mc['monthly_pnet_std'])}, min {num(mc['monthly_pnet_min'])}, max {num(mc['monthly_pnet_max'])}. Corr with "
      f"the Nifty-500 monthly return: {num(mc['corr_monthly_pnet_vs_mkt'])} for P(net>0), "
      f"{num(mc['corr_monthly_xs_vs_mkt'])} for the excess, and {num(mc['corr_monthly_count_vs_mkt'])} for the monthly "
      f"event count. Events fire in {mc['months_with_events']}/{mc['months_total']} months.")
    w()
    rows = []
    for wn in ("dev", "hold"):
        for k, o in rl[wn]["by_regime"].items():
            rows.append([wn, k, o["n"], f"{100 * o['share_events']:.0f}%", f"{100 * o['share_U_rows']:.0f}%",
                         num(o["p_net_pos"], 3) if o["p_net_pos"] is not None else "n/a", bps(o["net_bps"]), bps(o["xs_bps"])])
    table(["window", "regime (N500 vs SMA200 x 20d mom)", "events", "share of events", "share of U rows", "P(net50>0)",
           "net50 bps", "xs bps"], rows)
    rows = []
    for wn in ("dev", "hold"):
        for k, o in rl[wn]["by_liq"].items():
            rows.append([wn, f"liq tercile {k} (universe terciles)", o["n"], f"{100 * o['share_events']:.0f}%",
                         num(o["p_net_pos"], 3), bps(o["net_bps"]), bps(o["xs_bps"])])
        for k in ("fno", "liq5"):
            for f_, o in rl[wn][k].items():
                rows.append([wn, f"{k}={f_}", o["n"], "", "", bps(o["net_bps"]), bps(o["xs_bps"])])
    table(["window", "group", "events", "share of events", "P(net50>0)", "net50 bps", "xs bps"], rows)
w("By construction the label is regime-conditional: it fires only in falling markets. The *class shares* of the "
  "absolute event label move with the market (monthly P(net>0) corr about 0.45-0.49; P(net>0) ranges from below 0.1 "
  "to 0.99 across months). The *excess* is nearly market-neutral (corr about -0.2). Large caps (F&O proxy, top "
  "liquidity tercile) show weaker or negative 2026 excess, so the effect is mid/small-cap.")
w()
w("Table 5.1: scorecard learnability of the event indicator (score = 1 for event rows, 0 for other U rows; "
  "`L.xs_metrics` per-date IC vs x_h, non-overlap t). Also shown is the per-date AUC of event vs non-event rows "
  "(common-language effect size: P(a random event beats a random same-day non-event)), event-weighted and day-weighted, "
  "with month-cluster t.")
rows = []
for gname in ("A1", "A0", "Q_CR|k3", "Q_BO|k3"):
    for h in ("5", "10", "20"):
        o = xsi[gname][h]
        xm = o["xs_metrics"]
        rows.append([{"A0": "ANCHOR"}.get(gname, gname), h, f"{num(xm.get('dev_ic_mean'), 4)} ({num(xm.get('dev_ic_t_nonoverlap'))})",
                     f"{num(xm.get('holdout_ic_mean'), 4)} ({num(xm.get('holdout_ic_t_nonoverlap'))})",
                     num(o["auc_event_vs_rest_dev_ew"], 3), f"{num(o['auc_event_vs_rest_dev_dw'], 3)} ({num(o['auc_dw_dev_t_month'])})",
                     num(o["auc_event_vs_rest_hold_ew"], 3), f"{num(o['auc_event_vs_rest_hold_dw'], 3)} ({num(o['auc_dw_hold_t_month'])})",
                     json.dumps({k: round(v, 3) for k, v in xm.get("dev_ic_by_year", {}).items()})])
table(["event", "h", "xs IC DEV (t)", "xs IC 2026 (t)", "AUC ev-vs-rest DEV ew", "AUC DEV dw (t)", "AUC 2026 ew",
       "AUC 2026 dw (t)", "xs IC by DEV year"], rows)
w("The indicator IC is tiny (about 0.01-0.03) because events are 1-3% of rows. Its pooled xs-AUC is about 0.50 for "
  "the same reason. The event-vs-rest AUC (about 0.53) is the meaningful learnability number for a sparse gate.")
w()

# ---------------------------------------------------------------- sleeve investability
w("## 6. Investability of the sleeve (L.Sim)")
w()
w(f"Nifty 500 price index over the same windows: DEV CAGR {pct(bench['dev']['cagr'])} (maxDD "
  f"{pct(bench['dev']['max_dd'])}), 2026 {pct(bench['hold']['cagr'])} annualised (maxDD {pct(bench['hold']['max_dd'])}). "
  "Universe random top-20 (fully invested, same h/step) is in the `urand` column.")
w()
w("Table 6.1: all-events sleeves, K=20, step=1, 50 bps (80 bps CAGR in brackets). 'exc' is the strategy minus the "
  "count-matched random sleeve, with NW t at lag h.")
rows = []
for m in s3["mask"].unique():
    for h in (5, 10, 20):
        def g(win, cost):
            return s3[(s3["mask"] == m) & (s3.K == 20) & (s3.h == h) & (s3.win == win) & (s3.cost == cost)].iloc[0]
        d50, d80, h50, h80 = g("dev", 50), g("dev", 80), g("hold", 50), g("hold", 80)
        rows.append([m if h == 5 else "", h, f"{pct(d50.ev_cagr)} [{pct(d80.ev_cagr)}]", num(d50.ev_sharpe), pct(d50.ev_max_dd),
                     pct(d50.ev_exposure, 0), f"{1e4 * d50.ev_mean_trade_net:.0f}", pct(d50.match_cagr),
                     f"{pct(d50.exc_vs_match_cagr)} ({num(d50.exc_vs_match_nw_t)})", pct(d50.urand_cagr),
                     f"{pct(h50.ev_cagr)} [{pct(h80.ev_cagr)}]", pct(h50.match_cagr),
                     f"{pct(h50.exc_vs_match_cagr)} ({num(h50.exc_vs_match_nw_t)})", pct(h50.urand_cagr)])
table(["mask", "h", "DEV CAGR50 [80]", "Sharpe", "maxDD", "exposure", "mean trade bps", "matched CAGR",
       "exc vs matched (t)", "urand CAGR", "2026 CAGR50 [80]", "2026 matched", "2026 exc (t)", "2026 urand"], rows)
w("Table 6.2: slots per daily sleeve K (h=10, 50 bps). With step=1 each day can deploy at most 1/h of capital, so K "
  "changes diversification and how much light-event days count, not peak exposure.")
rows = []
for m in ("A0_R1dn_L20v1_mom20dn", "A1_L10v0_mom20dn_brd5", "N2_L20v1_brd10"):
    for K in (5, 10, 20):
        def g(win):
            return s3[(s3["mask"] == m) & (s3.K == K) & (s3.h == 10) & (s3.win == win) & (s3.cost == 50)].iloc[0]
        d, hh = g("dev"), g("hold")
        rows.append([m if K == 5 else "", K, pct(d.ev_cagr), num(d.ev_sharpe), pct(d.ev_exposure, 0),
                     f"{1e4 * d.ev_mean_trade_net:.0f}", f"{pct(d.exc_vs_match_cagr)} ({num(d.exc_vs_match_nw_t)})",
                     pct(hh.ev_cagr), f"{pct(hh.exc_vs_match_cagr)} ({num(hh.exc_vs_match_nw_t)})"])
table(["mask", "K", "DEV CAGR", "Sharpe", "exposure", "mean trade bps", "exc vs matched (t)", "2026 CAGR", "2026 exc (t)"], rows)
bg = s3[(s3.K == 20) & (s3.cost == 50) & (s3["mask"] != "A0_R1dn_L20v1_mom20dn")]
bgd, bgh = bg[bg.win == "dev"], bg[bg.win == "hold"]
a0k = s3[(s3["mask"] == "A0_R1dn_L20v1_mom20dn") & (s3.K < 20) & (s3.cost == 50) & (s3.win == "dev")]
w(f"Reading. The all-events sleeve beats count-matched random in every breadth-gated configuration at K=20: DEV "
  f"excess t {bgd.exc_vs_match_nw_t.min():.2f} to {bgd.exc_vs_match_nw_t.max():.2f}, 2026 t "
  f"{bgh.exc_vs_match_nw_t.min():.2f} to {bgh.exc_vs_match_nw_t.max():.2f}, all {len(bgd)} + {len(bgh)} positive. "
  f"Without the breadth gate (ANCHOR) the K=5/10 sleeves have DEV CAGR {pct(a0k.ev_cagr.min())} to "
  f"{pct(a0k.ev_cagr.max())}, because light-event days dominate. K=20 gives the best excess t in most cells because "
  f"it gives mass days more names. No all-events sleeve clears the portfolio-level Bonferroni hurdle "
  f"(best t {bgd.exc_vs_match_nw_t.max():.2f}).")
w()

# ---------------------------------------------------------------- meta
w("## 7. Meta-labeling inside the gate")
w()
w("Models (`L.walk_forward2`, training mask = U & close < prior 10-day low, 106,859 rows; date_step=1, min_train=2000, "
  "min_test=100, num_leaves 15, min_child_samples 100, 300 trees; features = 52 lab features + brd, bdd10, bdd20). "
  "**WF_R10** is a regression on R2_rel's relative label at h=10 (per-date neumom residual rank - 0.5). **WF_A10** is "
  "binary, 1{r_10 > 50 bps} (absolute meta-label, round-1 style). Free comparators are R2_rel's every-bar OOS models "
  "**EB_XR10** / **EB_XR20** (neumom RANK, h=10/20). **DEPTH** ranks deeper breakdowns first. **LIQ** ranks more "
  "liquid names first.")
w()
w("Table 7.1: learnability inside A1. Within-event IC per day, on days with >= 10 events, averaged over days, with "
  "month-cluster t. `xs_metrics` IC needs >= 30 events per day and uses non-overlap t.")
rows = []
for sn in ("WF_R10", "WF_A10", "EB_XR10", "EB_XR20", "DEPTH", "LIQ"):
    for h in ("5", "10", "20"):
        o = learn[f"A1|{sn}"][h]
        xm = o["xs"]
        rows.append([sn if h == "5" else "", h, f"{num(o['ic10_dev_mean'], 3)} ({num(o['ic10_dev_t_month'])})",
                     f"{num(o['ic10_hold_mean'], 3)} ({num(o['ic10_hold_t_month'])})",
                     f"{num(xm.get('dev_ic_mean'), 3)} ({num(xm.get('dev_ic_t_nonoverlap'))})",
                     num(xm.get("dev_auc_mean"), 3), num(xm.get("holdout_auc_mean"), 3) if xm.get("holdout_auc_mean") else "n/a",
                     (f"{bps(o['thr_dev']['xs_pass_bps'])} / {bps(o['thr_dev']['xs_fail_bps'])} ({100 * o['thr_dev']['pass_share']:.0f}%)"
                      if "thr_dev" in o else ""),
                     (f"{bps(o['thr_hold']['xs_pass_bps'])} / {bps(o['thr_hold']['xs_fail_bps'])} ({100 * o['thr_hold']['pass_share']:.0f}%)"
                      if "thr_hold" in o else "")])
table(["score", "h", "within-event IC DEV (t)", "IC 2026 (t)", "xs_metrics IC DEV (t non-ovl)", "xs AUC DEV",
       "xs AUC 2026", "PIT threshold DEV: xs pass / fail bps (pass %)", "2026 pass / fail (pass %)"], rows)
w("Table 7.2: investability. A1 gate, K=20, step=1. 'vs all' is against random events from the same gate (= "
  "`S.compare`). 'vs matched' is against count-matched universe random. 'thr' buys every event whose score passes the "
  "PIT threshold (prob > 0.5 / rank > 0) instead of the top 20.")
rows = []
for sn in ("ALL_EVENTS", "WF_R10", "WF_A10", "EB_XR10", "EB_XR20", "DEPTH", "LIQ"):
    for var in (("random",) if sn == "ALL_EVENTS" else ("topK", "thr")):
        for h in (5, 10, 20):
            sub = s4[(s4.gate == "A1") & (s4.score == sn) & (s4.variant == var) & (s4.h == h)]
            if not len(sub):
                continue
            def g(win, cost):
                return sub[(sub.win == win) & (sub.cost == cost)].iloc[0]
            d50, d80, h50 = g("dev", 50), g("dev", 80), g("hold", 50)
            rows.append([f"{sn} {var}" if h == 5 else "", h, f"{pct(d50.cagr)} [{pct(d80.cagr)}]", num(d50.sharpe),
                         pct(d50.max_dd), pct(d50.exposure, 0), f"{1e4 * d50.mean_trade_net:.0f}",
                         f"{pct(d50.exc_vs_rnd_cagr)} ({num(d50.exc_vs_rnd_nw_t)})",
                         f"{pct(d50.exc_vs_match_cagr)} ({num(d50.exc_vs_match_nw_t)})",
                         pct(h50.cagr), f"{pct(h50.exc_vs_rnd_cagr)} ({num(h50.exc_vs_rnd_nw_t)})",
                         f"{pct(h50.exc_vs_match_cagr)} ({num(h50.exc_vs_match_nw_t)})"])
table(["score / variant", "h", "DEV CAGR50 [80]", "Sharpe", "maxDD", "exposure", "mean trade bps", "DEV exc vs all (t)",
       "DEV exc vs matched (t)", "2026 CAGR50", "2026 exc vs all (t)", "2026 exc vs matched (t)"], rows)
w("Reading. (i) Ranking inside the gate works. Every model score has a positive within-event IC in every window: "
  "DEV 0.05-0.10 (t 3.2-6.8); 2026 0.03-0.055 at h=5/10 but only 0.00-0.03 at h=20. Simple rules do not: DEPTH has "
  "IC of -0.01 to 0.02 in DEV, and LIQ flips sign in 2026 at h=10/20. (ii) The general every-bar relative model "
  "(EB_XR10/20) ranks events about as well as the event-specific "
  "models, so no special model is needed. This confirms round 1. (iii) Top-20 by score is the right use. PIT "
  "thresholds cut exposure and lose most of the gain. (iv) In 2026 the score's lift over all-events stays positive at "
  "h=5/10 (+2 to +5%/yr) but is not significant (t 0.8-1.8). At h=20 it is about zero.")
w()
w("**DEV selection** (rule: highest DEV t of 'vs all' at 50 bps, among model scores x h): WF_R10 at h=5 "
  f"(t {num(rob['h5|50|dev']['meta_vs_all_nw_t'])}). h=10 is the cost-robust near-tie on DEV: Sharpe at 130 bps "
  f"{num(rob['h10|130|dev']['meta_sharpe'])} vs {num(rob['h5|130|dev']['meta_sharpe'])} for h=5, 2x the net per trade, "
  "half the turnover. The h=5 vs h=10 choice is not resolved by DEV at central costs.")
w()

# ---------------------------------------------------------------- robustness
w("## 8. Robustness of the meta sleeve (A1 + WF_R10 top-20)")
w()
rows = []
for h in (5, 10, 20):
    for cost in (50, 80, 130):
        for wn in ("dev", "hold"):
            o = rob[f"h{h}|{cost}|{wn}"]
            rows.append([h, cost, wn, pct(o["meta_cagr"]), num(o["meta_sharpe"]), pct(o["meta_max_dd"]), pct(o["meta_exposure"], 0),
                         f"{1e4 * o['meta_mean_trade_net']:.0f}", pct(o["all_cagr"]), pct(o["matched_cagr"]),
                         f"{pct(o['meta_vs_matched_ann'])} ({num(o['meta_vs_matched_nw_t'])} / {num(o['meta_vs_matched_month_t'])})",
                         f"{pct(o['meta_vs_matched_ann_excl_best_month'])} ({num(o['meta_vs_matched_nw_t_excl_best_month'])})",
                         f"{pct(o['meta_vs_all_ann'])} ({num(o['meta_vs_all_nw_t'])} / {num(o['meta_vs_all_month_t'])})",
                         f"{pct(o['all_vs_matched_ann'])} ({num(o['all_vs_matched_nw_t'])})"])
table(["h", "cost", "window", "meta CAGR", "Sharpe", "maxDD", "exposure", "mean trade bps", "all-events CAGR",
       "matched CAGR", "meta - matched /yr (NW t / month t)", "excl. best month (t)", "meta - all /yr (NW t / month t)",
       "all - matched /yr (t)"], rows)
w("Table 8.2: perturbations (50 bps). LAG1 means the signal is acted on one day late, with entry at open t+2. The "
  "entity halves are a random 50% split of entities (seed 7), with the matched baseline drawn from the same half.")
rows = []
for k, o in chk.items():
    if k in ("quarters", "capacity") or k.startswith("OS"):
        continue
    name, h, cost, wn = k.split("|")
    rows.append([name, h, wn, pct(o["cagr"]), num(o["sharpe"]), pct(o["matched_cagr"]),
                 f"{pct(o['exc_ann'])} ({num(o['exc_nw_t'])} / {num(o['exc_month_t'])})"])
table(["variant", "h", "window", "CAGR", "Sharpe", "matched CAGR", "exc vs matched /yr (NW t / month t)"], rows)
q = chk["quarters"]
w("Table 8.3: quarterly sum of daily excess (meta minus matched), 50 bps.")
rows = []
for k in ("h5|dev", "h5|hold", "h10|dev", "h10|hold"):
    rows.append([k] + [f"{kk}: {100 * vv:+.1f}%" for kk, vv in q[k].items()])
mx = max(len(r) for r in rows)
rows = [r + [""] * (mx - len(r)) for r in rows]
table(["sleeve|window"] + [f"q{i}" for i in range(1, mx)], rows)
cap = chk["capacity"]["h5"]
w(f"**Capacity** (meta sleeve trades 2023-01..2026-10, n={cap['trades']}). Median 20d ADV of bought names is "
  f"Rs {cap['adv_median_cr']:.1f} cr (p25 {cap['adv_p25_cr']:.1f}, p10 {cap['adv_p10_cr']:.1f}). "
  f"{100 * cap['liq5_share']:.0f}% are >= Rs 5 cr ADV and {100 * cap['fno_share']:.0f}% are F&O proxy names. "
  f"Position as % of ADV, median / p90: Rs 5 lakh {cap['pos_5L_pct_adv_median']:.2f}% / {cap['pos_5L_pct_adv_p90']:.1f}%; "
  f"Rs 25 lakh {cap['pos_25L_pct_adv_median']:.1f}% / {cap['pos_25L_pct_adv_p90']:.1f}% "
  f"({100 * cap['pos_25L_share_trades_gt5pct_adv']:.0f}% of trades > 5% ADV); Rs 1 crore "
  f"{cap['pos_1Cr_pct_adv_median']:.1f}% / {cap['pos_1Cr_pct_adv_p90']:.0f}% "
  f"({100 * cap['pos_1Cr_share_trades_gt5pct_adv']:.0f}% > 5% ADV). Up to 20 names per event day, each "
  f"1/(20h) of sleeve capital, so a Rs 1-5 cr sleeve is comfortable and Rs 20 cr+ is not, given panic-day spreads.")
w(f"**Fills.** The t+1 entry bar is locked (high == low) for {100 * locks['A1']['t1_locked_share']:.2f}% of A1 events "
  f"({100 * locks['A1']['t1_locked_up_share']:.2f}% locked limit-up). {100 * locks['A1']['t1_gap_up_gt5pct_share']:.1f}% "
  f"gap up > 5%. The mean t+1 gap is {locks['A1']['t1_gap_mean_bps']:.0f} bps, the same as the universe "
  f"({locks['U']['t1_gap_mean_bps']:.0f}). The open[t+1] fill assumption is not flattering the sleeve.")
w()

# ---------------------------------------------------------------- other events
w("## 9. Other overreaction / reversal events (scan) under Bonferroni")
w()
w(f"Families (each x market filter none / mom20dn x h 5/10/20): **CR** crash day r1 <= -k*vol20[t-1] (k=3,4) & "
  f"volz>1; **GR** gap-down reclaimed gap_open <= -m*ATR[t-1] (m=1,2) & close>open; **SL** 5-day xs loser "
  f"rank(mom_5) <= 1%/3%; **OS** oversold rsi_14 < 20/25; **LV** within 0.5% of the 52w low & volz > 1/2; **BO** "
  f"upside blow-off r1 >= +k*vol20[t-1] & volz>1 (avoid side). Added after s2 (flagged as data-driven): **Q_** = the "
  f"same events on *quiet* days (brd < 2%), to test continuation. Bonferroni: {n_cells} cells x 2 statistics (event- "
  f"and day-weighted month-cluster t) = {N_tests} tests, two-sided 5% means |z| > {num(z_b)}.")
w()
rows = []
for fam in ("CR", "GR", "SL", "OS", "LV", "BO"):
    sub = g2[(g2.family == fam)]
    for _, r in sub.iterrows():
        if r.h != 10 and not (fam == "OS" and r.h == 5):
            continue
        rows.append([r["def"], r.h, int(r.dev_n), f"{100 * r.dev_share_days_with_event:.0f}%", num(r.dev_p_net_pos, 3),
                     f"{bps(r.dev_xs_bps)} ({num(r.dev_xs_t_month)})", f"{bps(r.dev_xs_dw_bps)} ({num(r.dev_xs_dw_t_month)})",
                     f"{bps(r.hold_xs_bps)} ({num(r.hold_xs_t_month)})", f"{bps(r.pre_xs_bps)}",
                     "yes" if (abs(r.dev_xs_t_month) > z_b or abs(r.dev_xs_dw_t_month) > z_b) else ""])
for r in iso["rows"]:
    if r["h"] not in (5, 10):
        continue
    rows.append([r["def"], r["h"], int(r["dev_n"]), "", num(r["dev_p_net_pos"], 3),
                 f"{bps(r['dev_xs_bps'])} ({num(r['dev_xs_t_month'])})", f"{bps(r['dev_xs_dw_bps'])} ({num(r['dev_xs_dw_t_month'])})",
                 f"{bps(r['hold_xs_bps'])} ({num(r['hold_xs_t_month'])})", bps(r["pre_xs_bps"]),
                 "yes" if (abs(r["dev_xs_t_month"]) > z_b or abs(r["dev_xs_dw_t_month"]) > z_b) else ""])
table(["event", "h", "DEV events", "% DEV days", "P(net50>0)", "DEV xs ew (t)", "DEV xs dw (t)", "2026 xs (t)",
       "PRE xs", "Bonferroni"], rows)
pas = pd.DataFrame(iso["passing"])
fam = pas["def"].str.split("|").str[0]
w(f"Bonferroni passes ({len(pas)} cells): R1 family {int((fam == 'R1').sum())}, and also "
  + ", ".join(f"{d} h={h} (ew t {num(a)}, dw t {num(b)})" for d, h, a, b in
              pas[fam != "R1"][["def", "h", "dev_xs_t_month", "dev_xs_dw_t_month"]].itertuples(index=False))
  + ".")
w()
os_ = {k: v for k, v in chk.items() if k.startswith("OS")}
w("OS as a sleeve (rsi_14<20 & mom20dn, K=20, step=1): " + "; ".join(
    f"{k.replace('OS|', '')}: CAGR {pct(v['cagr'])}, exc vs matched {pct(v['exc_ann'])}/yr (t {num(v['exc_nw_t'])})"
    for k, v in os_.items() if "|50|" in k) + ".")
w()
w("Reading. Only the *washout* version of overreaction reverses. Crash days and recovered gap-downs on quiet days "
  "continue: Q_CR / Q_GR DEV excess -130 to -250 bps (t -2.5 to -6.0), and PRE is even stronger at -205 to -460 bps. "
  "In 2026 that continuation was weak or reversed (Q_CR k3 -28 bps, t -0.3), so it is not a dependable avoid flag. "
  "52-week lows on volume are negative but not significant. Removing quiet-day crash and "
  "blow-off names from the core book changed it by "
  f"{pct(stack['CORE_AVOID_QCR3_QBO3|50|dev']['d_vs_core_ann'])}/yr in DEV (t "
  f"{num(stack['CORE_AVOID_QCR3_QBO3|50|dev']['nw_t_vs_core'])}). Not selected; 2026 shows "
  f"{pct(stack['CORE_AVOID_QCR3_QBO3|50|hold']['d_vs_core_ann'])} (t {num(stack['CORE_AVOID_QCR3_QBO3|50|hold']['nw_t_vs_core'])}). "
  "Upside blow-offs (BO) underperform by 10-50 bps (avoid side) but miss Bonferroni in DEV. Short-term (5-day) "
  "losers have no reversal edge on NSE at 5-20 days.")
w()

# ---------------------------------------------------------------- combination
w("## 10. Combination with the relative core book")
w()
w("CORE = R2_rel `h20_neumom_RANK` walk_forward2 OOS score (reused, not retrained), U, top-20, step 5, h=20, reproduced "
  "exactly (DEV CAGR 30.88%). Sleeves use step=1, K=20. MIX w = (1-w) core + w sleeve, with sleeve idle cash at 0%. "
  "OVL w = idle sleeve capital parked in the core, r = r_core + w (r_sleeve - x_t r_core) - w |dx_t| cost/2. 'vs "
  "matched' compares the same combo with the sleeve replaced by its count-matched random twin.")
w()
rows = []
for key in ("50|dev", "50|hold", "80|dev", "80|hold"):
    res = s5[key]
    co = res["core"]
    rows.append([key, "CORE", pct(co["cagr"]), num(co["sharpe"]), pct(co["max_dd"]), "", "", "", "", ""])
    rc = ser.get(f"core|50|{key.split('|')[1]}") if key.startswith("50") else None
    if rc is not None:
        e = eq_stats(0.8 * rc)
        rows.append([key, "80% core + 20% cash", pct(e["cagr"]), num(e["sharpe"]), pct(e["max_dd"]), "", "", "", "", ""])
    for sn in ("S5_META", "S10_META", "S10_CORE", "S10_ALL", "S10_R1DN", "S20_META"):
        o = res["sleeves"][sn]
        for cn in ("MIX20", "OVL20"):
            c = o["combos"][cn]
            rows.append([key, f"{sn} {cn}", pct(c["cagr"]), num(c["sharpe"]), pct(c["max_dd"]),
                         f"{pct(o['sleeve']['cagr'])} / {num(o['sleeve']['sharpe'])}",
                         f"{num(o['corr']['daily'])} / {num(o['corr']['daily_when_sleeve_active'])} / {num(o['corr']['monthly'])}",
                         num(o["corr"]["daily_excess"]), num(c["nw_t_vs_core"]), num(c["nw_t_vs_matched_combo"])])
table(["cost|window", "book", "CAGR", "Sharpe", "maxDD", "sleeve alone CAGR / Sharpe",
       "corr daily / active days / monthly", "corr of excess", "t vs core", "t vs matched combo"], rows)
t5 = s5["50|dev"]["sleeves"]["S5_META"]["tail"]
w(f"Tail behaviour (DEV, S5_META). On the core's worst 5% of days, the core averages "
  f"{t5['core_worst5pct_days_mean_core_bps']:.0f} bps and the sleeve {t5['core_worst5pct_days_mean_sleeve_bps']:.0f} "
  f"bps (it is mostly in cash). In the core's three worst months the sleeve made: "
  + ", ".join(f"{k[:7]} core {pct(v['core'])} / sleeve {pct(v['sleeve'])}" for k, v in t5["core_worst3_months"].items()) + ".")
w()
w("Table 10.2: one-model stack variants (core rebalances unchanged, 50 bps).")
rows = []
for vn in ("CORE", "CORE_TILT_A1_0.3", "CORE_AVOID_QCR3_QBO3"):
    for wn in ("dev", "hold"):
        o = stack[f"{vn}|50|{wn}"]
        rows.append([vn, wn, pct(o["cagr"]), num(o["sharpe"]), pct(o["max_dd"]),
                     f"{pct(o['exc_vs_random_cagr'])} ({num(o['exc_vs_random_nw_t'])})",
                     f"{pct(o.get('d_vs_core_ann'))} ({num(o.get('nw_t_vs_core'))})" if vn != "CORE" else ""])
table(["variant", "window", "CAGR", "Sharpe", "maxDD", "exc vs random (t)", "vs core /yr (t)"], rows)
w(f"Core overlap on gate days ({ov['gate_days']} days, about {ov['mean_events_per_gate_day']:.0f} events each): "
  f"{pct(ov['share_core_top20_that_are_events'], 0)} of the core's top-20 are A1 events, against a "
  f"{pct(ov['base_share_events_in_U'], 0)} base share. The core's mean percentile of A1 events is "
  f"{num(ov['mean_core_pct_of_events'])}. The relative model already leans into washout names, which is why a "
  f"separate sleeve adds little to it.")
w()
def crange(win, key):
    v = [s5[f"50|{win}"]["sleeves"][sn]["corr"][key] for sn in s5[f"50|{win}"]["sleeves"]]
    return f"{min(v):.2f}-{max(v):.2f}"


def ovl_t(win):
    v = [s5[f"50|{win}"]["sleeves"][sn]["combos"]["OVL20"]["nw_t_vs_core"] for sn in s5[f"50|{win}"]["sleeves"]]
    return f"{min(v):.2f} to {max(v):.2f}"


def mix_vs_cash(win):
    base = eq_stats(0.8 * ser[f"core|50|{win}"])["cagr"]
    v = [s5[f"50|{win}"]["sleeves"][sn]["combos"]["MIX20"]["cagr"] - base for sn in ("S5_META", "S10_META", "S20_META")]
    return f"{100 * min(v):+.1f} to {100 * max(v):+.1f}%"


w(f"Reading. The sleeve's daily correlation with the core is {crange('dev', 'daily')} (DEV) and "
  f"{crange('hold', 'daily')} (2026) over all days, and {crange('dev', 'daily_when_sleeve_active')} on the days it is "
  f"active. The correlation of the two excess streams is low: {crange('dev', 'daily_excess')} DEV, "
  f"{crange('hold', 'daily_excess')} 2026. The sleeve's *selection* alpha is fairly independent of the core's, but "
  f"its capital is long the same falling market at the same time. Every OVL20 combination is below the core (t vs "
  f"core {ovl_t('dev')} DEV, {ovl_t('hold')} 2026), even though the same combos beat their matched-random twins (t "
  f"2.6-4.3 DEV). MIX20 (meta sleeves h=5/10/20) versus 80% core + 20% cash changes CAGR by {mix_vs_cash('dev')} in "
  f"DEV and {mix_vs_cash('hold')} in 2026. That is just 20% x the sleeve's own CAGR.")
w()

# ---------------------------------------------------------------- scorecards & verdicts
w("## 11. Candidate scorecards (summary)")
w()


def s3get(mask, h, win, cost, K=20):
    return s3[(s3["mask"] == mask) & (s3.K == K) & (s3.h == h) & (s3.win == win) & (s3.cost == cost)].iloc[0]


A0d, A0d8, A0h = s3get("A0_R1dn_L20v1_mom20dn", 10, "dev", 50), s3get("A0_R1dn_L20v1_mom20dn", 10, "dev", 80), s3get("A0_R1dn_L20v1_mom20dn", 10, "hold", 50)
A1d, A1d8, A1h = s3get("A1_L10v0_mom20dn_brd5", 10, "dev", 50), s3get("A1_L10v0_mom20dn_brd5", 10, "dev", 80), s3get("A1_L10v0_mom20dn_brd5", 10, "hold", 50)
m5d, m5d8, m5h = rob["h5|50|dev"], rob["h5|80|dev"], rob["h5|50|hold"]
s4m5 = s4[(s4.gate == "A1") & (s4.score == "WF_R10") & (s4.variant == "topK") & (s4.h == 5)]
s4m5d = s4m5[(s4m5.win == "dev") & (s4m5.cost == 50)].iloc[0]
s4m5h = s4m5[(s4m5.win == "hold") & (s4m5.cost == 50)].iloc[0]
qcr = [r for r in iso["rows"] if r["def"] == "Q_CR|k3" and r["h"] == 10][0]
os5 = g2row("OS|r20|-|mom20dn", 5)
cands = [
    {"candidate_id": "E1_R1DN_ANCHOR", "family": "event gate (capitulation reversal), round-1 definition",
     "definition": "U & close[t] < min(low[t-20..t-1]) & volz_20 > 1 & Nifty-500 mkt_mom20 < 0; label on event rows = r_10 (open[t+1]->close[t+10]) / x_10 vs same-date U mean; sleeve L.Sim step=1 K=20 all events (random tie-break)",
     "horizon": "10d (5/20 also tested)",
     "event_rates": f"DEV {int(a10.dev_n)} events, {100 * a10.dev_share_days_with_event:.0f}% of days, {a10.dev_events_per_event_day:.0f}/event-day; P(net50>0) {a10.dev_p_net_pos:.3f}; 57% bull_dn20 / 43% bear_dn20; liq terciles 39/29/32%; monthly P(net>0) std 0.22, corr with market 0.45; monthly count corr -0.70",
     "dev_cagr_50": float(A0d.ev_cagr), "dev_cagr_80": float(A0d8.ev_cagr), "dev_excess_nw_t": float(A0d.exc_vs_match_nw_t),
     "dev_maxdd": float(A0d.ev_max_dd), "dev_random_cagr_50": float(A0d.match_cagr), "holdout_cagr_50": float(A0h.ev_cagr),
     "holdout_excess_nw_t": float(A0h.exc_vs_match_nw_t), "holdout_random_cagr_50": float(A0h.match_cagr),
     "xs_ic_dev": xsi["A0"]["10"]["xs_metrics"].get("dev_ic_mean"), "xs_ic_holdout": xsi["A0"]["10"]["xs_metrics"].get("holdout_ic_mean"),
     "verdict": "weak"},
    {"candidate_id": "E2_CAPIT_BREADTH_A1", "family": "event gate (capitulation reversal) + market-breadth washout gate",
     "definition": "U & close[t] < min(low[t-10..t-1]) & volz_20 > 0 & mkt_mom20 < 0 & brd_t >= 5% (share of U at new 20d lows); label r_h / x_h on event rows; sleeve L.Sim step=1 K=20 all events",
     "horizon": "10d (5d similar on DEV; 20d best in 2026)",
     "event_rates": f"DEV {int(s10.dev_n)} events on {100 * s10.dev_share_days_with_event:.0f}% of days ({s10.dev_events_per_event_day:.0f}/event-day), 2.0% of U rows; P(net50>0) {s10.dev_p_net_pos:.3f}; by year 1219/5740/3172/5463/7392/7002 (2021-26); 57% bull_dn20 / 43% bear_dn20; liq terciles 38/31/31%; monthly P(net>0) std 0.21, corr with market 0.47 (excess corr -0.18)",
     "dev_cagr_50": float(A1d.ev_cagr), "dev_cagr_80": float(A1d8.ev_cagr), "dev_excess_nw_t": float(A1d.exc_vs_match_nw_t),
     "dev_maxdd": float(A1d.ev_max_dd), "dev_random_cagr_50": float(A1d.match_cagr), "holdout_cagr_50": float(A1h.ev_cagr),
     "holdout_excess_nw_t": float(A1h.exc_vs_match_nw_t), "holdout_random_cagr_50": float(A1h.match_cagr),
     "xs_ic_dev": xsi["A1"]["10"]["xs_metrics"].get("dev_ic_mean"), "xs_ic_holdout": xsi["A1"]["10"]["xs_metrics"].get("holdout_ic_mean"),
     "verdict": "promising"},
    {"candidate_id": "E3_CAPIT_META_A1_WFR10", "family": "event gate A1 + walk_forward2 relative meta-label ranking (top-20 per day)",
     "definition": "A1 gate; score = L.walk_forward2 regression on R2_rel neumom residual rank at h=10 (-0.5), trained on U & close<prior-10d-low rows, features 52 + brd/bdd10/bdd20; buy top-20 events per day (step=1, K=20, slot sizing), time exit h",
     "horizon": "5d DEV-selected; 10d cost-robust near-tie",
     "event_rates": "same gate as E2; meta-label base rate inside gate: P(x_10>0) 0.485 DEV; top-20 per event day (about 15% of the day's events)",
     "dev_cagr_50": float(m5d["meta_cagr"]), "dev_cagr_80": float(m5d8["meta_cagr"]), "dev_excess_nw_t": float(s4m5d.exc_vs_rnd_nw_t),
     "dev_maxdd": float(m5d["meta_max_dd"]), "dev_random_cagr_50": float(m5d["all_cagr"]), "holdout_cagr_50": float(m5h["meta_cagr"]),
     "holdout_excess_nw_t": float(s4m5h.exc_vs_rnd_nw_t), "holdout_random_cagr_50": float(m5h["all_cagr"]),
     "xs_ic_dev": learn["A1|WF_R10"]["5"]["ic10_dev_mean"], "xs_ic_holdout": learn["A1|WF_R10"]["5"]["ic10_hold_mean"],
     "verdict": "promising"},
    {"candidate_id": "E4_QUIET_CRASH_AVOID", "family": "isolated overreaction (continuation) avoid flag",
     "definition": "U & r1 <= -3*vol_20[t-1] & volz_20 > 1 & brd_t < 2% (quiet market); expected underperformance; used as exclusion from the core book",
     "horizon": "5-20d",
     "event_rates": f"DEV {int(qcr['dev_n'])} events on {int(qcr['dev_event_days'])} days (about 0.8/day); P(net50>0) {qcr['dev_p_net_pos']:.3f}",
     "dev_cagr_50": stack["CORE_AVOID_QCR3_QBO3|50|dev"]["cagr"], "dev_cagr_80": stack["CORE_AVOID_QCR3_QBO3|80|dev"]["cagr"],
     "dev_excess_nw_t": stack["CORE_AVOID_QCR3_QBO3|50|dev"]["nw_t_vs_core"], "dev_maxdd": stack["CORE_AVOID_QCR3_QBO3|50|dev"]["max_dd"],
     "dev_random_cagr_50": stack["CORE|50|dev"]["cagr"], "holdout_cagr_50": stack["CORE_AVOID_QCR3_QBO3|50|hold"]["cagr"],
     "holdout_excess_nw_t": stack["CORE_AVOID_QCR3_QBO3|50|hold"]["nw_t_vs_core"], "holdout_random_cagr_50": stack["CORE|50|hold"]["cagr"],
     "xs_ic_dev": xsi["Q_CR|k3"]["10"]["xs_metrics"].get("dev_ic_mean"), "xs_ic_holdout": xsi["Q_CR|k3"]["10"]["xs_metrics"].get("holdout_ic_mean"),
     "verdict": "weak"},
    {"candidate_id": "E5_OVERSOLD_DOWNMKT", "family": "oversold reversal event",
     "definition": "U & rsi_14 < 20 & mkt_mom20 < 0; sleeve step=1 K=20 all events h=5",
     "horizon": "5d",
     "event_rates": f"DEV {int(os5.dev_n)} events on {100 * os5.dev_share_days_with_event:.0f}% of days; P(net50>0) {os5.dev_p_net_pos:.3f}",
     "dev_cagr_50": chk["OS|h5|50|dev"]["cagr"], "dev_cagr_80": chk["OS|h5|80|dev"]["cagr"], "dev_excess_nw_t": chk["OS|h5|50|dev"]["exc_nw_t"],
     "dev_maxdd": chk["OS|h5|50|dev"]["max_dd"], "dev_random_cagr_50": chk["OS|h5|50|dev"]["matched_cagr"],
     "holdout_cagr_50": chk["OS|h5|50|hold"]["cagr"], "holdout_excess_nw_t": chk["OS|h5|50|hold"]["exc_nw_t"],
     "holdout_random_cagr_50": chk["OS|h5|50|hold"]["matched_cagr"],
     "xs_ic_dev": None, "xs_ic_holdout": None, "verdict": "reject"},
]
rows = []
for c in cands:
    rows.append([c["candidate_id"], c["horizon"], pct(c["dev_cagr_50"]), pct(c["dev_cagr_80"]), num(c["dev_excess_nw_t"]),
                 pct(c["dev_maxdd"]), pct(c["dev_random_cagr_50"]), pct(c["holdout_cagr_50"]), num(c["holdout_excess_nw_t"]),
                 pct(c["holdout_random_cagr_50"]), num(c["xs_ic_dev"], 3), num(c["xs_ic_holdout"], 3), c["verdict"]])
table(["candidate", "h", "DEV CAGR 50", "DEV CAGR 80", "DEV excess t", "DEV maxDD", "DEV baseline CAGR", "2026 CAGR 50",
       "2026 excess t", "2026 baseline CAGR", "IC DEV", "IC 2026", "verdict"], rows)
w("Baselines: E1/E2 use count-matched universe random (same days, same counts). E3 uses all events from the same gate "
  "(`S.compare` semantics); against matched random E3's DEV t is "
  f"{num(m5d['meta_vs_matched_nw_t'])} and 2026 t is {num(m5h['meta_vs_matched_nw_t'])}. E4 uses the core book "
  "itself (t of core-with-exclusion minus core). E5 uses matched random. IC: E1/E2/E4 use the event-indicator "
  "`xs_metrics` IC vs x_10. E3 uses the within-event day-weighted IC vs x_5.")
w()
w("## 12. Pros, cons, failure modes and how to use it")
w()
r1all = g2[g2.family == "R1"]
hb = s3[(s3.K == 20) & (s3.cost == 50) & (s3.win == "hold") & (s3.h >= 10) & (s3["mask"] != "A0_R1dn_L20v1_mom20dn")]
w(f"**Pros.** (1) The cleanest reversal fact in the lab. Buying washouts beats random stocks bought the same day in "
  f"every year 2021-2026. Event-weighted excess is positive in {int((r1all.dev_xs_bps > 0).sum())}/{len(r1all)} R1 "
  f"cells in DEV and {int((r1all.hold_xs_bps > 0).sum())}/{len(r1all)} in 2026, and it rises with breadth "
  f"(lowest to highest bucket). It survives a 1-day signal lag, random entity halves, the best-month drop and 130 bps costs "
  f"(h=10). (2) In the 2026 bear market (Nifty 500 {pct(bench['hold']['cagr'])} annualised), every breadth-gated "
  f"sleeve at h=10/20 was positive at 50 bps (CAGR {pct(hb.ev_cagr.min())} to {pct(hb.ev_cagr.max())}), with maxDD "
  f"{pct(hb.ev_max_dd.max())} to {pct(hb.ev_max_dd.min())}. (3) The event label is regime-conditional by design, "
  f"but its excess is "
  "market-neutral (corr about -0.2). (4) The general relative model ranks the events, so no separate model is needed. "
  "(5) No execution artefact: t+1 entry bars are almost never locked.")
w()
w("**Cons / failure modes.** (1) It is episodic. There are 56 washout episodes in 5.75 years, the top 5 DEV months "
  "supply 58-60% of the excess, and the 2026 excess is mostly January and March (March alone is 69-92%). (2) Low exposure (13-22%) means low absolute "
  "CAGR (about 3-10%). The sleeve is a cash-deployment rule, not a book. (3) Horizon depends on the regime: 5-day "
  "holds win in bull-market corrections (2023-25) and lose in drawn-out bear markets (2026). (4) It adds nothing to "
  "the relative core book, because the core already leans into the same names and is long the same market. (5) "
  "Weak in large caps: 2026 excess for F&O-proxy names is negative, and capacity is about Rs 5-25 lakh per name. "
  "(6) Absolute class shares swing with the market. The monthly P(net>0) ranges from about 0.1 to 0.99. Read the "
  "label's +1 as 'beats same-day stocks', not 'goes up'.")
w()
w("**How to invest with it (if at all).** Each evening, compute brd (the share of eligible stocks closing below "
  "their prior 20-day low). If brd >= 5% and Nifty-500 20-day momentum < 0, take the stocks that closed below their "
  "prior 10-day low on above-average volume. Rank them with the relative model and buy the top 20 at the next open, "
  "each at 1/(20h) of the sleeve's capital. Hold h days (h=10 is recommended on DEV cost-robustness; h=5 was best at "
  "50/80 bps) and exit at the close with a time exit, no stops. Fund it from capital that is not in the core "
  "relative book (a cash buffer or a separate sleeve). Expect 0-2 active weeks in most months and none in calm bull "
  "phases.")
w()
w("## 13. Statistics and variants tried")
w()
w(f"* Event-study cells: {n_cells} (R1 family 3 lookbacks x 5 volume x 6 market filters x 3 h = 270; 6 other "
  f"families x 2 params x 2 filters x 3 h = 72; 6 quiet-day events x 3 h = 18). Each is tested with event-weighted and "
  f"day-weighted t, giving {N_tests} tests and a Bonferroni |z| of {num(z_b)}.")
w(f"* Portfolio specs at DEV / 50 bps (cost/window/seed/perturbation repeats not counted): s3 {n_s3} (8 masks x 3 K x "
  f"3 h), s4 {n_s4} (2 gates x 3 h x 6 scores topK + 4 thresholds), s5 {n_s5} (6 sleeves x MIX/OVL x 3 weights), "
  f"{n_extra} others. Total {n_port}, giving a one-sided Bonferroni z of {num(z_port)}. The DEV-selected meta sleeve "
  f"(t {num(rob['h5|50|dev']['meta_vs_all_nw_t'])} vs all events, {num(rob['h5|50|dev']['meta_vs_matched_nw_t'])} vs "
  f"matched) clears it. No all-events sleeve does (best t about 2.9).")
w(f"* Walk-forward models: 2 new (WF_R10, WF_A10), within the budget of 6. R2_rel's EB_XR10/EB_XR20 OOS scores were "
  f"reused. Total variants: about {variants_total}. Round 1 tried about 600 more.")
w("* Holdout discipline. 2026 columns are printed next to DEV in every table (lab convention). Every *selection* "
  "used DEV columns only. The gate rule (max DEV day-weighted t at h=10, >= 500 events) was coded into s2 before it "
  "ran. The meta-sleeve rule (max DEV t vs all events) was applied mechanically. The recommendation of h=10 over the "
  "DEV-best h=5 is a judgment call made after 2026 was visible. It rests on DEV cost-robustness (Sharpe at 130 bps), "
  "but the reader should discount it accordingly. Round 1 had already reported 2026 for R1dn, so the holdout is "
  "lightly contaminated for the R1 family.")
w(f"* NW t and month-cluster t for the sleeve excess agree within about 0.6 (Table 8.1). Effective sample: about "
  f"30 DEV washout episodes, so treat sleeve-level t as an upper bound.")
w()
w("## 14. Lab notes")
w()
w("* `S.compare`'s random arm draws from the same mask. On a sparse event mask it tests only the ranking within "
  "events and cannot measure the event effect. A count-matched universe baseline (`matched_mask` here) is needed. "
  "Suggest a `baseline_mask` / count-matching option in `Sim.compare`.")
w("* `Sim.run` ends its window at the last signal plus one period, so daily series from different (h, step) "
  "configurations have different lengths (741 vs 743 days). Combining books needs date alignment.")
w("* With step=1 and slot sizing, a sleeve can deploy at most 1/h of capital per day. Mass-capitulation days cannot "
  "be sized up beyond that. This is a structural cap on event sleeves in the v2 Sim.")
w("* `xs_metrics` needs >= 30 rows per date, so event masks count only mass days. Its 'non-overlap' subsample takes "
  "every h-th *available* date, which is not calendar non-overlap for clustered event dates, so its t-stats are "
  "erratic. Use month-cluster t for event masks.")
w("* `walk_forward2` default LightGBM params (num_leaves 31, min_child_samples 400) are too coarse for event-row "
  "training sets of 20-60k rows. Pass smaller params.")
open(f"{OUT}/REPORT.md", "w").write("\n".join(L_))
save("final_summary", {"candidates": cands, "variants_total": variants_total, "n_event_cells": n_cells,
                       "n_event_tests": N_tests, "bonferroni_z_event": z_b, "n_portfolio_specs": n_port,
                       "bonferroni_z_portfolio_one_sided": z_port, "n_new_wf": n_wf})
print("REPORT lines", len(L_), "variants", variants_total, "n_port", n_port, "z_port", z_port)

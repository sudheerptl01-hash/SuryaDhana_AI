#!/usr/bin/env python3
"""R3_scen stage 4: client-facing html_tables and charts (numbers as fractions) from results.json."""
import sys

import numpy as np

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
sys.path.insert(0, LAB)
import r3common as C  # noqa: E402

C.set_agent("R3_scen")
OUT = C.OUT
R = C.load_res()
Z, D, FI, SC, PS = R["zoo"], R["old_label_defects"], R["filters_h20"], R["scenarios_h20"], R["prod_by_scenario_h20"]
HE, OI, TX = R["horizon_random_books"], R["overnight_intraday_split"], R["overnight_tax_by_h"]

NAMES = {"old": "Old repo label (raw close→close > 0, missing→0)",
         "cs": "Clean sign (next-open→close > 0)",
         "three": "Cost-aware 3-class (±50 bps)",
         "b22": "Triple barrier 2.0/2.0 ATR",
         "b315": "Triple barrier 3.0/1.5 ATR",
         "pct_neu": "Relative XR_neu 30/40/30",
         "pct_neumom": "Relative XR_neumom 30/40/30 (frozen label)",
         "dual": "DUAL: relative AND cost-aware agree"}
SHORT = {"old": "Old repo", "cs": "Clean sign", "three": "3-class ±50bp", "b22": "Barrier 2/2", "b315": "Barrier 3/1.5",
         "pct_neu": "XR_neu", "pct_neumom": "XR_neumom", "dual": "DUAL"}
DEFS = {"old": "close[t]→close[t+h] on unadjusted prices > 0; undefined future → 0",
        "cs": "open[t+1]→close[t+h] > 0 (adjusted); undefined → blank",
        "three": "+1 if return > +0.5%, −1 if < −0.5%, else 0",
        "b22": "up/down barrier at 2.0×ATR×√(h/20), first touch wins; time exit ±0.5% dead zone",
        "b315": "target 3.0×ATR, stop 1.5×ATR (×√(h/20)); time exit ±0.5% dead zone",
        "pct_neu": "rank of risk-adjusted return vs same-day peers (beta, volatility, size neutral): top 30% / middle / bottom 30%",
        "pct_neumom": "as XR_neu but also momentum-neutral (12-1 month); the team's frozen label",
        "dual": "+1 only if top-30% relative AND return > +0.5%; −1 only if bottom-30% AND < −0.5%"}
LABS = list(NAMES)


def lo_cls(st):
    return str(min(int(x) for x in st["shares_all"]))


def g(d, *ks):
    for k in ks:
        if d is None:
            return None
        d = d.get(k) if isinstance(d, dict) else None
    return d


T = []
INDEP = int(Z["cs_h20"]["daily_pos"]["n_days"] // 20)
C.save("derived", {"n_label_days_h20": Z["cs_h20"]["daily_pos"]["n_days"], "n_independent_20d_periods": INDEP})
# ---------------------------------------------------------------- T1 label verdict at h=20
rows = []
for k in LABS:
    s = Z[f"{k}_h20"]
    c = s["coherence_all"]
    lo = lo_cls(s)
    rows.append([NAMES[k], DEFS[k], s["shares_all"].get("1"), s["shares_all"].get("0"), s["shares_all"].get("-1"),
                 s["shares_dev"].get("1"), s["shares_hold"].get("1"), s["daily_pos"]["sd"], s["daily_pos"]["p5"],
                 s["daily_pos"]["p95"], s["corr_daily_pos_vs_mkt_same_window"], g(c, "1", "mean_net"), g(c, lo, "mean_net"),
                 g(c, "1", "p_net_pos")])
T.append(C.table(
    "1. Are the labels right? Eight label definitions side by side (20-day horizon, tradable universe, 2021-2026)",
    ["Label", "Definition", "Up (+1) share", "Flat (0) share", "Down (−1) share", "Up share 2023-25 (DEV)",
     "Up share 2026", "Day-to-day swing of up share (sd)", "Up share on a weak day (5th percentile of days)", "Up share on a strong day (95th percentile of days)",
     "Correlation of daily up share with the market's own 20-day return", "Average net return when labelled up",
     "Average net return when labelled down (−1, or 0 for two-class labels)", "Chance an 'up' row actually made money"],
    rows,
    "Tradable universe = elig_base (EQ series, price ≥ ₹20, ≥ ₹2 cr daily turnover, seasoned, not circuit-locked). Net return = "
    "buy at next day's open, sell at the close 20 trading days later, minus 0.5% round-trip cost. A label whose up share swings "
    "from ~13% to ~83% of stocks and moves 0.7-0.9 with the market is mostly describing the market, not the stock. The relative "
    "labels hold exactly 30% up every day by construction. Absolute labels' 'up' P&L is high by construction (the class is defined "
    "by the outcome); what matters is what can be predicted in advance (table 7)."))

# ---------------------------------------------------------------- T2 old label defects
rows = []
for h in (5, 10, 15, 20):
    d = D[f"h{h}"]
    rows.append([h, d["share_nan_to_0"], d["share_old_label_0_due_to_nan_among_old_0"],
                 d["share_labelled_but_clean_window_undefined"], d["share_sign_flip_raw_vs_adjusted_close"],
                 d["n_fake_crash_raw_lt_m30_adj_gt_m10"], d["share_old_vs_clean_sign_disagree"],
                 d["mean_close_entry_ret"], d["mean_exec_ret"], d["mean_close_entry_ret"] - d["mean_exec_ret"],
                 d["median_exec_ret"]])
T.append(C.table(
    "2. What is wrong with the old repo label, measured (tradable universe, 2021-2026)",
    ["Holding period (trading days)", "Rows labelled 'not up' only because the future price is missing",
     "Share of the old label's 'not up' class that is really 'unknown'", "Rows labelled although the clean window is invalid (suspension/corporate-action break)",
     "Rows where unadjusted prices flip the sign vs adjusted prices", "Fake crashes from splits/bonuses (raw < −30%, adjusted > −10%), count",
     "Rows where the old label disagrees with the clean sign label", "Average return if you could buy at the signal close (not possible)",
     "Average return buying at the next open (what you can actually do)", "Phantom return per trade (close entry minus open entry)",
     "Median executable return (a typical stock loses money before costs)"],
    rows,
    "The old label is close to the clean sign label on most rows (3-6% disagree) but it is biased: missing futures are counted as "
    "'not up', raw prices create fake split crashes, and the close entry adds ~26 bps per trade that no one can trade. The old "
    "label is evaluated on every row (valid future or not), exactly as the repo did; within-entity windows make this a kinder "
    "version than the repo's ticker-keyed shift."))

# ---------------------------------------------------------------- T3 event rates by horizon
rows = []
for k in LABS:
    for h in (5, 10, 15, 20):
        s = Z[f"{k}_h{h}"]
        c = s["coherence_all"]
        lo = lo_cls(s)
        rows.append([SHORT[k], h, s["shares_all"].get("1"), s["shares_all"].get("0"), s["shares_all"].get("-1"),
                     s["daily_pos"]["sd"], s["corr_daily_pos_vs_mkt_same_window"], s["corr_monthly_pos_vs_mkt_month"],
                     g(c, "1", "mean_net"), g(c, lo, "mean_net"), c.get("spread_top_minus_bottom")])
T.append(C.table(
    "3. Event rates by holding period (tradable universe, 2021-2026)",
    ["Label", "Holding period (days)", "Up share", "Flat share", "Down share", "Day-to-day swing of up share (sd)",
     "Corr. with market return over the same window", "Corr. with market (monthly, old atlas method)",
     "Average net when up", "Average net when down", "Up minus down (class separation)"],
    rows,
    "Longer horizons do not make absolute labels less market-driven: the same-window correlation stays 0.85-0.88 for the sign "
    "labels at every horizon. The monthly method used in earlier rounds understates it at 20 days (0.47) because a 20-day window "
    "straddles two calendar months. Relative labels stay at 30% up and ≈0 market correlation at every horizon. The 3-class flat "
    "share shrinks from 9% (5 days) to 4% (20 days) because 20-day moves rarely stay inside ±0.5%."))

# ---------------------------------------------------------------- T4 / T5 filters
FN = {"none": "No filter (every stock with a valid 20-day future)", "elig": "Tradable universe (elig_base, ≥ ₹2 cr/day)",
      "liq5": "Liquid (≥ ₹5 cr/day)", "fno": "F&O proxy (top-200 by turnover; shortable)",
      "trend": "Trend gate: above 200-day average AND 60-day momentum in top 30%",
      "washout": "Washout gate: new 10-day low on volume in a falling, broad sell-off (R2 A1)",
      "deliv": "High delivery: top third of delivery % that day"}
rows = []
for fk, fr in FI.items():
    f_ = fr["_filter"]
    rows.append([FN[fk], f_["rows_valid"], f_["rows_per_active_day"], f_["share_days_active"],
                 fr["cs"]["share_of_elig_rows"], f_["mean_net_all_rows"], f_["mean_net_all_rows_dev"], f_["mean_net_all_rows_hold"],
                 f_["p_net_pos_all_rows"], fr["old"]["shares_all"].get("1"), fr["cs"]["shares_all"].get("1"),
                 fr["three"]["shares_all"].get("1"), fr["b315"]["shares_all"].get("1"),
                 fr["pct_neumom"]["shares_all"].get("1"), fr["pct_neumom"]["shares_all"].get("-1"), fr["dual"]["shares_all"].get("1")])
T.append(C.table(
    "4. Conditions (filters) × labels at 20 days: how many stocks survive and how the up/down rates change",
    ["Filter (used only to choose which stocks are considered)", "Stock-days with a valid 20-day future", "Stocks per active day",
     "Share of trading days the filter fires", "Size relative to the tradable universe", "Average net return of all filtered stocks",
     "… in 2023-25 (DEV)", "… in 2026", "Chance a filtered stock makes money", "Old repo label up share", "Clean sign up share",
     "3-class up share", "Barrier 3/1.5 up share", "XR_neumom up share", "XR_neumom down share", "DUAL up share"],
    rows,
    "Filters never change a label's value; they only choose rows. Relative labels keep their rank among the tradable universe, so an "
    "up share above 30% means the filter tends to select relative winners (trend +3.3 pp, washout +1.7 pp). For 'No filter' the "
    "relative labels are re-ranked among all stocks (they are undefined otherwise). The washout gate fires on ~16% of days only."))
rows = []
for fk, fr in FI.items():
    cs, xr, du = fr["cs"]["coherence_all"], fr["pct_neumom"]["coherence_all"], fr["dual"]["coherence_all"]
    rows.append([FN[fk], g(cs, "1", "mean_net"), g(cs, "0", "mean_net"), g(xr, "1", "mean_net"), g(xr, "-1", "mean_net"),
                 g(xr, "1", "p_net_pos"), g(du, "1", "mean_net"), g(du, "-1", "mean_net"),
                 fr["pct_neumom"]["shares_dev"].get("1"), fr["pct_neumom"]["shares_hold"].get("1"),
                 fr["cs"]["shares_dev"].get("1"), fr["cs"]["shares_hold"].get("1")])
T.append(C.table(
    "5. Conditions × labels: does 'up' still mean money inside each filter? (20 days, net of 0.5% cost)",
    ["Filter", "Clean sign: average net when up", "Clean sign: average net when not up", "XR_neumom: average net when +1",
     "XR_neumom: average net when −1", "XR_neumom: chance a +1 stock made money", "DUAL: average net when +1",
     "DUAL: average net when −1", "XR_neumom up share 2023-25", "XR_neumom up share 2026", "Clean sign up share 2023-25",
     "Clean sign up share 2026"],
    rows,
    "Class separation (up vs down P&L) survives every filter. Liquid and F&O names have smaller spreads (they move less); the "
    "unfiltered universe has the widest spread but includes untradable rows (BE series, < ₹20, illiquid, circuit-locked)."))

# ---------------------------------------------------------------- T6 scenarios x labels
rows = []
for sn, dd in SC.items():
    a = dd["all"]
    rows.append([sn, a["_state"]["share_of_days"], a["_state"]["mean_net_all"],
                 g(a, "cs", "pos_share"), g(a, "cs", "p_net_pos_given_pos"), g(a, "three", "pos_share"),
                 g(a, "b315", "pos_share"), g(a, "pct_neumom", "pos_share"), g(a, "pct_neumom", "mean_net_given_pos"),
                 g(a, "pct_neumom", "p_net_pos_given_pos"), g(a, "pct_neumom", "mean_net_given_down"),
                 g(a, "dual", "pos_share"), g(a, "dual", "mean_net_given_pos")])
T.append(C.table(
    "6. Scenarios × labels at 20 days (tradable universe, 2021-2026): how the market backdrop changes the event rates",
    ["Scenario (first 9 rows known on the signal day; last 4 known only afterwards)", "Share of trading days",
     "Average net return of all stocks", "Clean sign: up share", "Clean sign: chance an 'up' row made money",
     "3-class: up share", "Barrier 3/1.5: up share", "XR_neumom: up share", "XR_neumom: average net when +1",
     "XR_neumom: chance a +1 stock made money", "XR_neumom: average net when −1", "DUAL: up share", "DUAL: average net when +1"],
    rows,
    "Ex-ante states (200-day average, 20-day momentum, breadth, VIX tercile vs its own past year) move the absolute up share only "
    "between 0.44 and 0.58; the realised market move (ex-post rows) moves it from 0.14 to 0.78. The relative label stays at 30% "
    "in every scenario, but its absolute payoff does not: when the market falls more than 5% over the next 20 days, the top-30% "
    "stocks average only about +0.8% net and fewer than half make money. Overlapping 20-day windows: there are only "
    f"{INDEP} independent 20-day periods in 2021-2026 (labelled days / 20), so scenario differences are descriptive, not tradable rules."))

# ---------------------------------------------------------------- T7 PROD by scenario
rows = []
for sn, dd in PS.items():
    dv, ho = dd["dev"], dd["hold"]
    rows.append([sn, dv.get("n_days"), dv.get("top20_mean_net"), dv.get("universe_mean_net"), dv.get("excess_vs_universe"),
                 dv.get("excess_nw_t"), dv.get("avoid_tail_excess"), dv.get("ic_vs_label"),
                 ho.get("n_days"), ho.get("top20_mean_net"), ho.get("universe_mean_net"), ho.get("excess_vs_universe"),
                 ho.get("excess_nw_t"), ho.get("avoid_tail_excess"), ho.get("ic_vs_label")])
T.append(C.table(
    "7. The tradable version: frozen PROD score by scenario (top-20 picks vs the whole universe, 20-day hold)",
    ["Scenario", "DEV signal days", "DEV: top-20 average net", "DEV: universe average net", "DEV: top-20 minus universe",
     "DEV: t-stat (Newey-West, 20 lags)", "DEV: avoid tail (bottom 30%) minus universe", "DEV: rank IC with the label",
     "2026 signal days", "2026: top-20 average net", "2026: universe average net", "2026: top-20 minus universe",
     "2026: t-stat", "2026: avoid tail minus universe", "2026: rank IC"],
    rows,
    "Each signal day: top-20 by PROD (walk-forward, never trained on the day it scores), bought next open, sold 20 days later, "
    "minus 0.5%. Universe = all tradable stocks equally weighted (also minus 0.5%). This is a per-day signal study (overlapping "
    "trades), not the staggered book; R3_book has the book numbers. In 2023-25 the top-20 beat the universe in every ex-ante "
    "state; in 2026 the edge is about zero in most states although the rank IC (0.06) is intact - the long book does not "
    "monetise the IC. 2026 is reported, never used to choose."))

# ---------------------------------------------------------------- T8 horizon economics
rows = []
for h in (5, 10, 15, 20):
    rows.append([h, HE[f"random_h{h}_c0_dev"]["cagr"], HE[f"random_h{h}_c50_dev"]["cagr"], HE[f"random_h{h}_c80_dev"]["cagr"],
                 HE[f"random_h{h}_c0_hold"]["cagr"], HE[f"random_h{h}_c50_hold"]["cagr"], HE[f"random_h{h}_c80_hold"]["cagr"],
                 HE[f"ew_h{h}_c50_dev"]["cagr"], HE[f"ew_h{h}_c50_hold"]["cagr"], 0.005 * 252 / h,
                 HE[f"random_h{h}_c50_dev"]["maxdd"]])
rows.append(["Nifty 500 price index (no dividends)", None, HE["nifty500_price_dev"]["cagr"], None, None,
             HE["nifty500_price_hold"]["cagr"], None, None, None, None, HE["nifty500_price_dev"]["max_dd"]])
T.append(C.table(
    "8. Why 20 days: a random 20-stock book by holding period and trading cost (phase-averaged, 5 random seeds)",
    ["Holding period (days)", "2023-25 CAGR, no cost", "2023-25 CAGR, 0.5% cost", "2023-25 CAGR, 0.8% cost",
     "2026 annualised, no cost", "2026 annualised, 0.5% cost", "2026 annualised, 0.8% cost",
     "Equal-weight universe 2023-25, 0.5% cost", "Equal-weight universe 2026, 0.5% cost",
     "Cost drag per year at 0.5% (0.5% × 252 / h)", "Max drawdown 2023-25, random at 0.5%"],
    rows,
    "No skill at all, only the holding period changes: at 5 days a random book loses ~17%/yr to costs, at 20 days it makes ~12%/yr "
    "(2023-25). Every number is averaged over the 5 possible weekly start days. Stocks are total-return adjusted; Nifty 500 is a "
    "price index (≈1.2%/yr dividends missing). 2026 = Jan to mid-Oct, annualised."))

# ---------------------------------------------------------------- T9 overnight vs intraday
rows = []
GN = {"all": "All tradable stocks", "liq_low": "Least liquid third", "liq_mid": "Middle third", "liq_high": "Most liquid third"}
for grp in ("all", "liq_low", "liq_mid", "liq_high"):
    for per, pn in (("dev", "2023-25"), ("hold", "2026")):
        on, it, cc = OI[f"{grp}_overnight_{per}"], OI[f"{grp}_intraday_{per}"], OI[f"{grp}_close_to_close_{per}"]
        rows.append([GN[grp], pn, on["ann_compounded"], it["ann_compounded"], cc["ann_compounded"],
                     on["mean_daily_bps"] / 1e4, it["mean_daily_bps"] / 1e4, on["share_days_pos"], it["share_days_pos"]])
T.append(C.table(
    "9. Where Indian stock returns happen: overnight gap vs trading session (equal-weight tradable universe)",
    ["Group (liquidity on the previous day)", "Period", "Overnight (close → next open), annualised",
     "Trading session (open → close), annualised", "Close → close, annualised", "Average overnight return per day",
     "Average session return per day", "Share of days the overnight gap is positive", "Share of days the session is positive"],
    rows,
    "Equal-weight averages, re-balanced daily, before costs: not a tradable strategy (a daily round trip costs ~0.5%, more than "
    "the ~0.2-0.3% average gap). The pattern holds in every liquidity third, so it is not only an illiquid-stock artefact; part of "
    "it may be how NSE's open (auction / first trade) and close (last-30-minute average) prints are formed. Its practical meaning: "
    "a signal computed at the close can only be bought at the next open, after the gap has already been paid."))

# ---------------------------------------------------------------- T10 overnight tax
rows = []
for h in (5, 10, 15, 20):
    for per, pn in (("dev", "2023-25"), ("hold", "2026")):
        x = TX[f"h{h}_{per}"]
        rows.append([h, pn, x["mean_close_entry_ret"], x["mean_next_open_entry_ret"], x["mean_overnight_gap_forfeited"],
                     x["fraction_of_close_entry_return_forfeited"], x["annual_overnight_drag_if_rolled_every_h_days"],
                     x["annual_cost_drag_50bps_if_rolled_every_h_days"]])
T.append(C.table(
    "10. The 'overnight tax': what an executable next-open entry gives up vs the (untradable) close-entry label",
    ["Holding period (days)", "Period", "Average h-day return from the signal close (not tradable)",
     "Average h-day return from the next open (tradable)", "Overnight gap given up per trade",
     "Share of the close-entry return given up", "Yearly gap given up if you re-enter every h days",
     "Yearly cost drag at 0.5% per round trip, same turnover"],
    rows,
    "Date-weighted averages over the tradable universe, before costs. The per-trade gap is the same at every horizon (~0.27% in "
    "2023-25), so short holds pay it far more often: a 5-day trader gives up ~60% of the close-entry return, a 20-day trader ~15%."))
IDS = ["t1_label_verdict_h20", "t2_old_label_defects", "t3_event_rates_by_horizon", "t4_filters_event_rates", "t5_filters_coherence", "t6_scenarios_x_labels", "t7_prod_by_scenario", "t8_random_book_by_horizon", "t9_overnight_vs_session", "t10_overnight_tax"]
for i_, t_ in enumerate(T):
    t_["id"] = IDS[i_]
C.save("html_tables", T)

# ---------------------------------------------------------------- charts
S2 = np.load(f"{OUT}/series_s2.npz", allow_pickle=True)
mon = [str(m) for m in S2["mon_codes"]]
keep = [i for i, m in enumerate(mon) if np.isfinite(S2["monthly_pos_cs"][i])]


def cl(a):
    return [None if not np.isfinite(v) else float(v) for v in a]


charts = {
    "monthly_up_share_h20": {
        "type": "line", "x": [mon[i] for i in keep],
        "series": {"Clean sign (absolute) – share of stocks labelled up": cl(S2["monthly_pos_cs"][keep]),
                   "XR_neumom (relative, frozen) – share labelled +1": cl(S2["monthly_pos_pct_neumom"][keep]),
                   "DUAL – share labelled +1": cl(S2["monthly_pos_dual"][keep]),
                   "Nifty 500 return in the same calendar month": cl(S2["mret_m"][keep])},
        "note": "20-day labels on the tradable universe, by month of the signal. The absolute label's up share swings with the "
                "market (12%-77% of stocks); the relative label is 30% every month by construction; DUAL re-imports the market."},
    "event_rate_by_horizon": {
        "type": "bar", "x": [SHORT[k] for k in LABS],
        "series": {f"h = {h} days": [Z[f"{k}_h{h}"]["shares_all"].get("1") for k in LABS] for h in (5, 10, 15, 20)},
        "note": "Share of stock-days labelled up (+1), tradable universe 2021-2026."},
    "market_dependence_by_horizon": {
        "type": "bar", "x": [SHORT[k] for k in LABS],
        "series": {f"h = {h} days": [Z[f"{k}_h{h}"]["corr_daily_pos_vs_mkt_same_window"] for k in LABS] for h in (5, 10, 15, 20)},
        "note": "Correlation between the daily up share and the Nifty 500 return over the same window. Near 1 = the label is the "
                "market; near 0 = the label is about the stock."},
    "scenario_up_share_heatmap": {
        "type": "bar", "x": list(SC.keys()),
        "series": {SHORT[k]: [g(SC[s]["all"], k, "pos_share") for s in SC] for k in LABS},
        "note": "Heatmap data (rows = scenarios, columns = labels): up share at 20 days, 2021-2026. First 9 scenarios known in "
                "advance, last 4 only afterwards."},
    "scenario_mean_net_up_heatmap": {
        "type": "bar", "x": list(SC.keys()),
        "series": {SHORT[k]: [g(SC[s]["all"], k, "mean_net_given_pos") for s in SC] for k in LABS},
        "note": "Heatmap data: average net 20-day return of rows labelled up, by scenario (after 0.5% cost)."},
    "prod_excess_by_scenario": {
        "type": "bar", "x": list(PS.keys()),
        "series": {"Top-20 minus universe, 2023-25": [PS[s]["dev"].get("excess_vs_universe") for s in PS],
                   "Top-20 minus universe, 2026": [PS[s]["hold"].get("excess_vs_universe") for s in PS],
                   "Avoid tail minus universe, 2023-25": [PS[s]["dev"].get("avoid_tail_excess") for s in PS],
                   "Avoid tail minus universe, 2026": [PS[s]["hold"].get("avoid_tail_excess") for s in PS]},
        "note": "Frozen PROD score, per signal day, 20-day hold, net of 0.5%; average over days in each scenario."},
    "filters_up_share": {
        "type": "bar", "x": [FN[f] for f in FI],
        "series": {SHORT[k]: [FI[f][k]["shares_all"].get("1") for f in FI] for k in LABS},
        "note": "Up share at 20 days inside each filter (filters choose rows; label values unchanged)."},
    "random_book_cagr_by_horizon": {
        "type": "bar", "x": ["5 days", "10 days", "15 days", "20 days"],
        "series": {"No cost, 2023-25": [HE[f"random_h{h}_c0_dev"]["cagr"] for h in (5, 10, 15, 20)],
                   "0.5% cost, 2023-25": [HE[f"random_h{h}_c50_dev"]["cagr"] for h in (5, 10, 15, 20)],
                   "0.8% cost, 2023-25": [HE[f"random_h{h}_c80_dev"]["cagr"] for h in (5, 10, 15, 20)],
                   "0.5% cost, 2026": [HE[f"random_h{h}_c50_hold"]["cagr"] for h in (5, 10, 15, 20)]},
        "note": "Random 20-stock books (no skill), phase-averaged over 5 start days and 5 seeds."},
}
S3 = np.load(f"{OUT}/series_s3.npz", allow_pickle=True)
charts["overnight_vs_session_growth"] = {
    "type": "line", "x": [str(m) for m in S3["months"]],
    "series": {"Growth of ₹1 earning only overnight gaps": cl(S3["overnight"]),
               "Growth of ₹1 earning only the trading session": cl(S3["intraday"]),
               "Growth of ₹1 close-to-close": cl(S3["cc"])},
    "note": "Equal-weight tradable universe from 2023-01, daily, before costs; month-end values. Illustrative, not tradable."}
C.save("charts", charts)
C.log("tables", len(T), "charts", len(charts))

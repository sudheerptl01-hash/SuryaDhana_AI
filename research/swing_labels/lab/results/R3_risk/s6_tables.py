"""R3_risk: client-ready html_tables + charts (numbers as fractions) built only from saved results/series,
plus two small derived checks: Sharpe in excess of cash for exposure policies; quarterly excess of the book."""
import sys

import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
sys.path.insert(0, LAB)
import r3common as C  # noqa: E402

OUT = C.set_agent("R3_risk")
R = C.load_res()
z = np.load(f"{OUT}/pa_series.npz")
xz = np.load(f"{OUT}/expo_series.npz")
icz = np.load(f"{OUT}/ic_series.npz")
cash = C.market_daily("Nifty 1D Rate Index")


def S_(npz, key):
    return pd.Series(npz[key], index=pd.DatetimeIndex(npz[key + "_dates"]))


# ---------- derived 1: Sharpe in excess of cash (Nifty 1D Rate) for exposure policies (50 bps)
sh_cash = {}
for k in xz.files:
    if k.endswith("_dates"):
        continue
    s = S_(xz, k)
    c = cash.reindex(s.index).fillna(0.0)
    ex = s - c
    sh_cash[k] = float(ex.mean() / s.std() * np.sqrt(252))
C.save("item2_sharpe_vs_cash", sh_cash)

# ---------- derived 2: quarterly excess (sum of daily book - random) on the contiguous book
b, r, e = S_(z, "contig_c50_book"), S_(z, "contig_c50_rand"), S_(z, "contig_c50_ew")
q = pd.DataFrame({"ex_rand": b - r, "ex_ew": b - e}).groupby((b.index.to_period("Q"))).sum()
qtr = {str(k): {"excess_vs_random": float(v.ex_rand), "excess_vs_ew": float(v.ex_ew)} for k, v in q.iterrows()}
C.save("item1_quarterly_excess", {"quarters": qtr, "n_quarters_positive_vs_random": int((q.ex_rand > 0).sum()),
                                  "n_quarters": int(len(q))})

# ---------- derived 3: where did the breadth governor's DEV gain/loss come from? (top-1 drawdown window vs rest)
dd = R["item1_drawdowns"]
w0, w1 = dd["top5"][0]["peak"], dd["top5"][0]["trough"]
g50, x100 = S_(xz, "PROD_dev_c50_G50"), S_(xz, "PROD_dev_c50_X100")
dfx = (g50 - x100)
inw = (dfx.index >= w0) & (dfx.index <= w1)
eqg = (1 + g50).cumprod()
gov_attr = {"window": [w0, w1], "diff_sum_in_top1_dd_window": float(dfx[inw].sum()),
            "diff_sum_rest_of_dev": float(dfx[~inw].sum()), "diff_sum_total_dev": float(dfx.sum()),
            "g50_maxdd_dev": float((eqg / eqg.cummax() - 1).min()),
            "g50_maxdd_date": str((eqg / eqg.cummax() - 1).idxmin().date()),
            "x100_fall_in_window": float((1 + x100[inw]).prod() - 1), "g50_fall_in_window": float((1 + g50[inw]).prod() - 1)}
C.log("governor attribution", C.short(gov_attr))
C.save("item2_governor_attribution", gov_attr)
# ---------- derived 4: slippage budget from the cost model (statutory ~22.3 bps round trip, TEAM_BRIEF)
STAT = 22.3
slip = {"statutory_round_trip_bps": STAT, "central_all_in_bps": 50, "stress_all_in_bps": 80,
        "slippage_budget_bps_per_side_central": (50 - STAT) / 2, "slippage_budget_bps_per_side_stress": (80 - STAT) / 2,
        "cagr_drag_50_to_80_dev": R["item1_phase_avg"]["dev_c50"]["pa_cagr"] - R["item1_phase_avg"]["dev_c80"]["pa_cagr"],
        "cagr_drag_50_to_80_contig": R["item1_phase_avg"]["contig_c50"]["pa_cagr"] - R["item1_phase_avg"]["contig_c80"]["pa_cagr"]}
C.save("item4_slippage_budget", slip)

T = []
# ---------- T1 drawdowns
rows = []
for i, ep in enumerate(dd["top5"], 1):
    rows.append([i, ep["peak"], ep["trough"], ep["recovery"] or "not yet (open)", ep["depth"], ep["days_peak_to_trough"],
                 ep["days_peak_to_recovery"], ep["nifty500_peak_to_trough"], ep["ew_peak_to_trough"],
                 ep["random_peak_to_trough"], ep["excess_vs_random_peak_to_trough"]])
T.append(C.table("The five worst falls of the strategy (Jan-2023 to Oct-2026) and what the market did over the same days",
                 ["Rank", "Peak date", "Bottom date", "Back to peak on", "Fall (peak to bottom)", "Trading days falling",
                  "Trading days to recover", "Nifty 500 same days", "All-stock equal-weight same days",
                  "Random 20-stock picks same days", "Strategy minus random"],
                 rows, "Strategy = frozen PROD book (top-20, weekly, 20-day holds, 50 bps costs), averaged over the 5 weekday "
                       "entry phases. The worst fall (Dec-2024 to Mar-2025) was a broad small/mid-cap sell-off: random picks "
                       "and the equal-weight universe fell as much; the model did not cause it and could not avoid it. "
                       "Nifty 500 is a price index (no dividends)."))
# ---------- T2 monthly distribution
md = dd["monthly_dist"]
stats = [("Average month", "mean"), ("Median month", "median"), ("Typical swing (std dev)", "sd"), ("Worst month", "min"),
         ("1-in-20 bad month (5th pct)", "p5"), ("1-in-20 good month (95th pct)", "p95"), ("Best month", "max"),
         ("Share of months up", "pct_positive")]
T.append(C.table(f"Monthly returns, {dd['monthly_first_month_used']} to {dd['monthly_last_month_used']} ({md['book']['n_months']} months)",
                 ["Statistic", "Strategy", "Random 20-stock picks", "All-stock equal-weight", "Nifty 500 (price)"],
                 [[lab, md["book"][k], md["random"][k], md["ew"][k], md["nifty500"][k]] for lab, k in stats],
                 "Monthly compounded returns of the daily book. The strategy swings as much as the small/mid-cap universe "
                 "(about 6% a month), roughly 1.5x the Nifty 500."))
mb = dd["monthly_beat"]
T.append(C.table("How often the strategy beat the alternatives, month by month",
                 ["Period", "Months", "Beat random picks", "Beat equal-weight universe", "Beat Nifty 500",
                  "Average monthly edge vs random", "Worst monthly edge vs random", "Longest losing streak vs random (months)"],
                 [[p, mb[k]["n_months"], mb[k]["pct_months_beat_random"], mb[k]["pct_months_beat_ew"],
                   mb[k]["pct_months_beat_nifty500"], mb[k]["mean_monthly_excess_vs_random"],
                   mb[k]["worst_monthly_excess_vs_random"], mb[k]["longest_run_months_below_random"]]
                  for p, k in (("All", "all"), ("Development 2023-2025", "dev"), ("2026 (holdout, reported only)", "hold_2026"))],
                 "Even in the strong development years the strategy lost to random picks in about 3 months out of 10; "
                 "in 2026 it beat random in fewer than half of the months."))
cd = dd["monthly_conditional_on_market"]
T.append(C.table("Months when the market fell, was flat, or rose",
                 ["Nifty 500 month", "Months", "Strategy avg", "Random avg", "Equal-weight avg", "Nifty 500 avg",
                  "Share beating random"],
                 [[lab, cd[k]["n_months"], cd[k]["book_mean"], cd[k]["random_mean"], cd[k]["ew_mean"], cd[k]["nifty500_mean"],
                   cd[k]["pct_beat_random"]] for lab, k in (("Fell more than 3%", "n500_down_gt3"),
                                                            ("Within +/-3%", "n500_flat"), ("Rose more than 3%", "n500_up_gt3"))],
                 "The strategy is a fully invested long book of mostly mid/small caps: in falling months it falls more than "
                 "the Nifty 500. Its edge shows up mainly in flat and rising months."))
# ---------- T4/T5 exposure
ex = R["item2_exposure"]["results"]
pol_lab = {"X100": "100% invested (frozen baseline)", "X80": "80% invested, 20% cash", "X60": "60% invested, 40% cash",
           "G50": "Breadth governor (50% when breadth < 0.5)"}
per_lab = {"dev": "Development 2023-2025", "hold": "2026 holdout", "pre": "Sep-2021 to Dec-2022 (pre-period)"}
for book, pers, title, note in (
        ("PROD", ("dev", "hold"), "Exposure choices for the strategy book (50 bps costs)",
         "Cash earns the Nifty 1D Rate. Gain vs 100% = annualised daily difference with a Newey-West t (lag 20). "
         "No policy passes the pre-registered adoption rule (needs t >= 2): the breadth governor cut the worst fall by "
         f"about 10 points in 2023-2025 but gave up return overall; it gained {gov_attr['diff_sum_in_top1_dd_window']:.1%} "
         f"during the single Dec-2024 to Mar-2025 sell-off and lost {gov_attr['diff_sum_rest_of_dev']:.1%} the rest of the time. "
         "'Sharpe vs cash' subtracts the cash rate; plain Sharpe (rf = 0) flatters cash-heavy choices."),
        ("EW", ("pre", "dev", "hold"), "Exposure choices tested on the all-stock equal-weight book, including 2021-22",
         "No model scores exist before 2023 (walk-forward), so the 2021-22 test uses the equal-weight universe book. "
         "In the choppy 2022 market the breadth governor switched ~10 times a year and did worse than staying invested.")):
    rows = []
    for p in pers:
        for pol in ("X100", "X80", "X60", "G50"):
            st = ex[f"{book}_{p}_c50_{pol}"]
            pv = st.get("paired_vs_X100", {})
            rows.append([per_lab[p], pol_lab[pol], st["cagr"], st["vol"], st["sharpe"],
                         sh_cash.get(f"{book}_{p}_c50_{pol}"), st["maxdd"], st["calmar"], st["avg_exposure"],
                         pv.get("diff_ann", 0.0), pv.get("nw_t"), st.get("maxdd_change_vs_X100", 0.0)])
    T.append(C.table(title, ["Period", "Policy", "Annual return", "Volatility", "Sharpe (rf=0)", "Sharpe vs cash", "Worst fall",
                             "Return / worst fall", "Average invested", "Return change vs 100%", "t-stat", "Worst-fall change"],
                     rows, note))
# ---------- T6/T7/T8 expectations
xp = R["item3_expectations"]
rows = []
for lab, key in (("Planned edge +5%/yr", "dev_b40_t5"), ("Dead strategy 0%/yr", "dev_b40_t0")):
    for hz, k in (("6 months", "excess_6m"), ("12 months", "excess_12m"), ("24 months", "excess_24m")):
        v = xp[key][k]
        rows.append([lab, hz, v["p5"], v["p25"], v["p50"], v["p75"], v["p95"], v["p_neg"]])
T.append(C.table("What to expect: the strategy's lead over random picks after 6, 12 and 24 months",
                 ["Assumed true edge", "After", "Bad case (5th pct)", "25th pct", "Middle", "75th pct", "Good case (95th pct)",
                  "Chance of being behind"], rows,
                 "Block bootstrap (40-day blocks, 10,000 paths) of the 2023-2025 daily excess, re-centred on the planning "
                 "edge (+5%/yr) or on zero. Even with a real +5% edge, about 1 year in 4 ends behind random picks; a dead "
                 "strategy looks like a +5% one about 1 year in 4."))
rows = []
for lab, key in (("Independent days (reference only, NOT used)", "dev_b1"), ("20-day blocks", "dev_b20"),
                 ("40-day blocks (primary)", "dev_b40"), ("60-day blocks", "dev_b60"), ("40-day blocks, 2023-Oct 2026 data", "contig_b40")):
    a, d0 = xp[f"{key}_t5"], xp[f"{key}_t0"]
    rows.append([lab, a["excess_12m"]["sd"], a["p_negative_excess_year"], a["excess_12m"]["p_below_minus5"],
                 a["p_at_least_one_negative_year_in_2"], d0["excess_12m"]["p_above_plus5"]])
T.append(C.table("Sensitivity of the expectations to how the history is resampled",
                 ["Resampling", "12-month spread (std dev)", "P(behind random in a year | +5% edge)",
                  "P(12-month lead < -5% | +5% edge)", "P(at least one losing year in two | +5% edge)",
                  "P(dead strategy shows > +5% in a year)"], rows,
                 "Longer blocks keep more of the day-to-day persistence and widen the ranges; treating days as independent "
                 "understates the risk of a bad year. Primary = 40-day blocks."))
rows = []
for lab, key in (("Planned edge +5%/yr", "dev_b40_t5"), ("Dead strategy 0%/yr", "dev_b40_t0")):
    v = xp[key]
    rows.append([lab, v["absolute_12m"]["p5"], v["absolute_12m"]["p50"], v["absolute_12m"]["p95"], v["absolute_12m"]["p_neg"],
                 v["absolute_24m_annualised"]["p5"], v["absolute_24m_annualised"]["p50"], v["absolute_24m_annualised"]["p95"],
                 v["maxdd_24m"]["p50"], v["maxdd_24m"]["p_worse_than_minus20"], v["maxdd_24m"]["p_worse_than_minus30"]])
v = xp["dev_b40_t5"]["ew_alone_12m"]
rows.append(["Equal-weight universe alone", v["p5"], v["p50"], v["p95"], v["p_neg"], None, None, None, None, None, None])
T.append(C.table("What to expect in rupees: total return ranges (market + strategy edge)",
                 ["Case", "12m bad (5th pct)", "12m middle", "12m good (95th pct)", "Chance 12m is negative",
                  "24m per-year bad", "24m per-year middle", "24m per-year good", "Typical worst fall in 2 years",
                  "P(worst fall beyond -20%)", "P(worst fall beyond -30%)"], rows,
                 f"Total return = equal-weight universe daily return + the re-centred edge, resampled together in 40-day "
                 f"blocks. The market part keeps its 2023-2025 average (equal-weight book {xp['ew_dev_cagr']:.1%}/yr after "
                 f"costs), which may be optimistic. Market risk dominates: the edge changes the middle, not the width."))
# ---------- T9/T10 kill rules
kb, kn, kh = R["item4_kill_bootstrap"], R["item4_kill_null_books"], R["item4_kill_historical"]
rl = {"K1": "Review: 6-month lead over random < -5%", "K2": "Review: 3-month average signal quality (IC) < 0.02",
      "K3": "12-month lead over random < 0", "C1_review": "Any of the three (review trigger)",
      "C2_kill": "KILL: 12-month lead < 0 AND 3-month IC < 0.02", "C3_kill_fast": "Fast kill: 6-month lead < -5% AND 3-month IC < 0.02"}
rows = []
for k, lab in rl.items():
    rows.append([lab, kb["b40_H1a"][k]["p_fire_24m"], min(kb[f"b{b}_H1a"][k]["p_fire_24m"] for b in (20, 40, 60)),
                 max(kb[f"b{b}_H1a"][k]["p_fire_24m"] for b in (20, 40, 60)), kb["b40_H1b"][k]["p_fire_24m"],
                 kb["b40_H0"][k]["p_fire_12m"], kb["b40_H0"][k]["p_fire_24m"], kb["b40_H0"][k]["median_first_fire_days"],
                 kn["H1a"][k]["p_fire_24m"], kn["H0"][k]["p_fire_24m"]])
T.append(C.table("Kill and review rules: false alarms vs detection over the first 24 months of live trading",
                 ["Rule (checked weekly)", "False alarm, good strategy (+5%, IC intact)", "False alarm, low (20-60 day blocks)",
                  "False alarm, high (20-60 day blocks)", "False alarm if IC only 0.022", "Detects dead strategy within 12m",
                  "Detects dead strategy within 24m", "Median days to detect (trading days)",
                  "Null-book check: false alarm", "Null-book check: detection 24m"], rows,
                 "Joint 40-day block bootstrap of the daily (lead over random, IC) history 2023-2025, re-centred: good = +5%/yr "
                 f"with IC {kb['ic_target_H1a']:.3f} (as observed), pessimistic good = +5%/yr with IC {kb['ic_target_H1b']:.3f} "
                 "(IC scaled down with the edge), dead = 0%/yr and IC 0. IC of a signal date is known 20 trading days later. "
                 "Null books = 100 random scores with the same day-to-day persistence as the model (rolling 24-month windows). "
                 "Recommended: C2 as the kill rule; K1 and K2 as review triggers."))
rows = []
for k, lab in rl.items():
    h = kh[k]
    rows.append([lab, h["dev_share_checks_on"], h["hold_share_checks_on"], h["first_fire"] or "never",
                 "yes" if h["on_at_last_check"] else "no"])
T.append(C.table(f"How the rules would have behaved on our own backtest (weekly checks to {kh['last_check']['date']})",
                 ["Rule", "Share of weekly checks firing, 2023-2025", "Share firing, 2026", "First time it fired",
                  "Firing at the last check"], rows,
                 f"Only the 6-month review rule fired (Jan-2024), a false alarm: the 12-month lead never fell below "
                 f"{kh['min_values']['ex12m_min']:.1%} over the whole backtest. At the "
                 f"last check the 6-month lead was {kh['last_check']['ex6m']:.1%}, the 12-month lead "
                 f"{kh['last_check']['ex12m']:.1%} and the 3-month IC {kh['last_check']['ic3m']:.3f}: no rule active."))
# ---------- T11 dashboard
mm = R["item4_monitor_metrics"]
dv, hd = mm["dev"], mm["hold_2026"]
cost_drag = R["item1_phase_avg"]["dev_c50"]["pa_cagr"] - R["item1_phase_avg"]["dev_c80"]["pa_cagr"]
rows = [
    ["Signal quality (rank IC of the score vs realised 20-day relative return)", "20 trading days after each signal",
     dv["ic"]["daily"]["mean"], dv["ic"]["weekly"]["p10"], dv["ic"]["weekly"]["p90"], dv["ic"]["rolling13w"]["p10"],
     hd["ic"]["daily"]["mean"], "Review if the 13-week average < 0.02 (K2); kill only with C2"],
    ["Top-20 relative hit rate (share of picks beating the median stock after neutralisation)", "20 trading days later",
     dv["rel_hit"]["daily"]["mean"], dv["rel_hit"]["weekly"]["p10"], dv["rel_hit"]["weekly"]["p90"],
     dv["rel_hit"]["rolling13w"]["p10"], hd["rel_hit"]["daily"]["mean"], "Watch if the 13-week average < 0.50"],
    ["Top-20 absolute hit rate (share of picks with net 20-day return > 0)", "20 trading days later",
     dv["abs_hit"]["daily"]["mean"], dv["abs_hit"]["weekly"]["p10"], dv["abs_hit"]["weekly"]["p90"],
     dv["abs_hit"]["rolling13w"]["p10"], hd["abs_hit"]["daily"]["mean"], "Market-driven: context only, no action"],
    ["Top-20 return minus universe average (20-day, before costs)", "20 trading days later",
     dv["top_ex"]["daily"]["mean"], dv["top_ex"]["weekly"]["p10"], dv["top_ex"]["weekly"]["p90"],
     dv["top_ex"]["rolling13w"]["p10"], hd["top_ex"]["daily"]["mean"], "Feeds the money rules K1/K3"],
    ["Avoid list (bottom 30%) return minus universe average (20-day)", "20 trading days later",
     dv["avoid_ex"]["daily"]["mean"], dv["avoid_ex"]["weekly"]["p10"], dv["avoid_ex"]["weekly"]["p90"],
     dv["avoid_ex"]["rolling13w"]["p10"], hd["avoid_ex"]["daily"]["mean"], "Review if the 13-week average turns positive"],
    ["Turnover: share of this week's top-20 also picked 4 weeks ago (same sleeve)", "same day",
     dv["ovl20"]["daily"]["mean"], dv["ovl20"]["weekly"]["p10"], dv["ovl20"]["weekly"]["p90"],
     dv["ovl20"]["rolling13w"]["p10"], hd["ovl20"]["daily"]["mean"],
     "By construction each weekly rebalance sells the expiring 20 and buys 20 new; if the overlap stays above 0.30 "
     "(2023-25 weekly 90th pct was " + f"{dv['ovl20']['weekly']['p90']:.2f}) check that the score file is updating"],
    ["Slippage vs the official open (bps per side)", "same day (from broker fills)", None, None, None, None, None,
     f"Budget {slip['slippage_budget_bps_per_side_central']:.1f} bps/side beyond statutory (~{STAT} bps round trip) inside "
     f"the 50 bps all-in cost; review above it, stop adding money above {slip['slippage_budget_bps_per_side_stress']:.1f} "
     f"(= 80 bps stress, which cost {cost_drag:.1%}/yr of return in 2023-2025)"],
]
T.append(C.table("Weekly monitoring dashboard: what normal looked like in 2023-2025 and what 2026 showed",
                 ["Measure", "Known", "2023-25 average", "Weekly low (10th pct)", "Weekly high (90th pct)",
                  "13-week average low (10th pct)", "2026 average", "Alert"], rows,
                 "All values are fractions (0.067 = 6.7%). 2026 values are reported, never used to set thresholds. "
                 "In 2026 the signal quality and relative hit rate stayed normal while the top-20's raw return lead "
                 "nearly vanished: the information survived but did not turn into money. A likely (not verified here) "
                 "cause is the book's factor tilts; round 2 found it leans away from momentum, which led in 2026."))
# ---------- charts
ch = {}
eqs = {k: (1 + s).cumprod() for k, s in (("Strategy", b), ("Random 20-stock picks", r), ("All-stock equal-weight", e))}
n500 = pd.Series(z["n500"], index=pd.DatetimeIndex(z["contig_dates"]))
eqs["Nifty 500 (price)"] = (1 + n500).cumprod()
W = pd.DataFrame(eqs)
Wd = (W / W.cummax() - 1).resample("W-FRI").last()
ch["drawdown_weekly"] = {"type": "line", "x": [str(x.date()) for x in Wd.index],
                         "series": {c: [float(v) for v in Wd[c].values] for c in Wd.columns},
                         "note": "How far each portfolio was below its previous high, weekly (0 = at a new high). The strategy's "
                                 "worst fall (-27%, early 2025) matched random picks; it recovered to its peak in Jul-2026."}
Wm = W.resample("ME").last()
ch["equity_monthly"] = {"type": "line", "x": [str(x.date()) for x in Wm.index],
                        "series": {c: [float(v) for v in Wm[c].values] for c in Wm.columns},
                        "note": "Growth of 1 rupee, Jan-2023 to Oct-2026, 50 bps costs, averaged over the 5 weekday entry phases."}
hist = dd["monthly_hist"]
ch["monthly_return_histogram"] = {"type": "bar", "x": [f"{x:.1%} to {x + 0.025:.1%}" for x in hist["bin_left"]],
                                  "series": {"Strategy": hist["book"], "All-stock equal-weight": hist["ew"],
                                             "Nifty 500": hist["nifty500"]},
                                  "note": "Number of months in each monthly-return bucket (end buckets include the tails)."}
ch["exposure_policies"] = {"type": "bar", "x": [pol_lab[p] for p in ("X100", "X80", "X60", "G50")],
                           "series": {"Annual return 2023-25": [ex[f"PROD_dev_c50_{p}"]["cagr"] for p in ("X100", "X80", "X60", "G50")],
                                      "Worst fall 2023-25": [ex[f"PROD_dev_c50_{p}"]["maxdd"] for p in ("X100", "X80", "X60", "G50")],
                                      "Annual return 2026": [ex[f"PROD_hold_c50_{p}"]["cagr"] for p in ("X100", "X80", "X60", "G50")],
                                      "Worst fall 2026": [ex[f"PROD_hold_c50_{p}"]["maxdd"] for p in ("X100", "X80", "X60", "G50")]},
                           "note": "Holding cash lowers both the return and the worst fall almost one-for-one; none of these is a free lunch."}
pk = ["p5", "p25", "p50", "p75", "p95"]
ch["expected_12m_lead"] = {"type": "bar", "x": ["Bad case (5%)", "25%", "Middle", "75%", "Good case (95%)"],
                           "series": {"Real +5%/yr edge": [xp["dev_b40_t5"]["excess_12m"][k] for k in pk],
                                      "Dead strategy (0%)": [xp["dev_b40_t0"]["excess_12m"][k] for k in pk]},
                           "note": "Range of the 12-month lead over random picks. The two ranges overlap heavily: one year of "
                                   "results cannot tell a good strategy from a dead one."}
ch["kill_rule_tradeoff"] = {"type": "bar", "x": [rl[k] for k in rl],
                            "series": {"False alarm on a good strategy (24m)": [kb["b40_H1a"][k]["p_fire_24m"] for k in rl],
                                       "Detection of a dead strategy (24m)": [kb["b40_H0"][k]["p_fire_24m"] for k in rl]},
                            "note": "A good rule has a short first bar and a tall second bar. Money-only rules fire too often on a "
                                    "good strategy; combining money with signal quality (C2) keeps detection and cuts false alarms."}
sw = kh["series_weekly"]
ch["rules_history_lead"] = {"type": "line", "x": sw["dates"],
                            "series": {"6-month lead over random": sw["ex6m"], "12-month lead over random": sw["ex12m"],
                                       "Review line (-5%)": [-0.05] * len(sw["dates"]), "Kill line (0%)": [0.0] * len(sw["dates"])},
                            "note": "Rolling lead of the strategy over random picks on our own backtest (weekly)."}
ch["rules_history_ic"] = {"type": "line", "x": sw["dates"],
                          "series": {"3-month average IC (known 20 days later)": sw["ic3m"],
                                     "Review line (0.02)": [0.02] * len(sw["dates"])},
                          "note": "Signal quality never fell below the review line, including 2026."}
C.save("html_tables", T)
C.save("charts", ch)
C.log("tables", len(T), "charts", list(ch))

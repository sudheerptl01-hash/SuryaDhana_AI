"""R3_book item 5 + house-rule outputs: charts data and client-readable html_tables, built ONLY from numbers already
in results.json and the saved phase-averaged daily series (no new strategy runs)."""
import numpy as np
import pandas as pd

import sys
LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
sys.path.insert(0, LAB)
import r3common as C  # noqa: E402

C.set_agent("R3_book")
R = C.load_res()
I1, I2, I2b, I3, I4 = (R["item1_repro"], R["item2_exits"], R["item2b_x3_decomposition"], R["item3_capacity"],
                       R["item4_ops_tax"])
z1 = np.load(f"{C.OUT}/pa_series_item1.npz")
zc = np.load(f"{C.OUT}/pa_series_contig_books.npz")


def s4(key):
    idx = pd.DatetimeIndex(z1[f"{key}__dates"])
    return {j: pd.Series(z1[f"{key}__{j}"], index=idx) for j in ("s", "r", "e", "n")}


charts, tables = {}, []
LAB_N = {"s": "PROD book (frozen)", "r": "Random top-20 (5 seeds)", "e": "Equal-weight universe", "n": "Nifty 500 (price index)"}


def monthly_curve(d, extra=None):
    df = pd.DataFrame({LAB_N[k]: v for k, v in d.items()})
    if extra is not None:
        for k, v in extra.items():
            df[k] = v.reindex(df.index)
    eq = (1 + df.fillna(0.0)).cumprod()
    m = eq.groupby(eq.index.to_period("M")).last()
    x = [str(p) for p in m.index]
    return x, {c: [float(v) for v in m[c].values] for c in m.columns}


x, sr = monthly_curve(s4("PROD_dev_c50"))
charts["equity_dev_monthly"] = {"type": "line", "x": x, "series": sr, "title": "Growth of 1 rupee, development period 2023-2025",
                                "y_label": "value of 1 rupee invested",
                                "note": "Phase-averaged PROD book (top-20 weekly, 20-day holds, 50 bps costs) vs a random top-20 book, "
                                        "the equal-weight eligible universe and the Nifty 500 PRICE index (no dividends, ~1.2%/yr missing; "
                                        "lab stock prices include dividends). Month-end values."}
x, sr = monthly_curve(s4("PROD_hold_c50"))
charts["equity_2026_monthly"] = {"type": "line", "x": x, "series": sr, "title": "Growth of 1 rupee, 2026 holdout (Jan-Oct)",
                                 "y_label": "value of 1 rupee invested",
                                 "note": "Same books on the 2026 holdout, which was never used to choose anything. The PROD book roughly "
                                         "matches the random book in 2026."}
cont = s4("PROD_contig_c50")
x3 = pd.Series(zc["X3__s"], index=pd.DatetimeIndex(zc["X3__dates"]))
e0c = pd.Series(zc["E0__s"], index=pd.DatetimeIndex(zc["E0__dates"]))
chk = float(np.abs(e0c.reindex(cont["s"].index).values - cont["s"].values).max())
x, sr = monthly_curve(cont, extra={"PROD book + executable carry (X3)": x3})
charts["equity_contiguous_monthly"] = {"type": "line", "x": x, "series": sr,
                                       "title": "Growth of 1 rupee, Jan 2023 - Oct 2026 (one continuous book)",
                                       "y_label": "value of 1 rupee invested",
                                       "note": "One contiguous phase-averaged book. X3 = same picks, but positions due to exit at a rebalance "
                                               "close are held to the next open and names still in the new top-20 are kept; most of its extra "
                                               "return is the overnight premium, which random picks also earn with that timing."}
# quarterly excess bars (contiguous)
q = I1["PROD"]["contig_c50"]["by_quarter"]
qs = sorted(q)
charts["quarterly_excess"] = {"type": "bar", "x": qs,
                              "series": {"PROD book minus random top-20": [q[k]["ex_vs_random"] for k in qs],
                                         "PROD book minus equal-weight universe": [q[k]["ex_vs_ew"] for k in qs]},
                              "title": "Quarterly excess return of the PROD book",
                              "y_label": "quarterly return difference",
                              "note": "Compounded quarterly return of the PROD book minus the random top-20 book and minus the "
                                      "equal-weight universe (contiguous 2023-01 to 2026-10, 50 bps). 2026 quarters are holdout."}
# weekly drawdowns
df = pd.DataFrame({LAB_N[k]: v for k, v in cont.items()})
eq = (1 + df).cumprod()
dd = eq / eq.cummax() - 1
wk = dd.iloc[::5]
charts["drawdown_weekly"] = {"type": "line", "x": [str(i)[:10] for i in wk.index],
                             "series": {c: [float(v) for v in wk[c].values] for c in wk.columns},
                             "title": "Drawdown from previous peak (weekly samples)", "y_label": "drawdown",
                             "note": "Fall from the running peak of each book, sampled every 5 trading days, contiguous 2023-01 to 2026-10."}
# capacity curve (DEV and 2026, Y = 1.0)
A = ["1cr", "5cr", "20cr", "50cr", "100cr"]
P_ = I3["policies"]
PN = {"a_liq2": "liq2 universe, no cap", "b_liq2_cap5": "liq2, max 5% of ADV", "c_liq5": "liq5 universe, no cap",
      "d_liq5_cap5": "liq5, max 5% of ADV"}
for per, lab in (("dev", "2023-2025"), ("hold", "2026")):
    sr = {PN[p]: [P_[p][f"Y1.0_{a}_{per}"]["pa_cagr"] for a in A] for p in PN}
    sr["Equal-weight universe (no impact)"] = [I3["refs"][per]["ew_cagr"]] * len(A)
    sr["Nifty 500 price index"] = [I3["refs"][per]["nifty500_cagr"]] * len(A)
    charts[f"capacity_cagr_{per}"] = {"type": "line", "x": ["Rs 1 cr", "Rs 5 cr", "Rs 20 cr", "Rs 50 cr", "Rs 100 cr"],
                                      "series": sr, "title": f"Annual return vs fund size ({lab}), impact coefficient Y = 1",
                                      "y_label": "CAGR after costs and market impact",
                                      "note": "Each name gets AUM/80; square-root market impact (1.0 x daily vol x sqrt(position/ADV20)) "
                                              "per side on top of 50 bps; idle cash earns the Nifty 1D Rate."}
# add-on gains
V = ["X1", "E1", "X3", "E2w", "E2d", "E3", "S1"]
VN = {"X1": "Idle cash earns 1D rate", "E1": "E1 carry (as specified)", "X3": "X3 carry, executable timing",
      "E2w": "E2w weekly early exit", "E2d": "E2d daily early exit", "E3": "E3 -25% stop", "S1": "S1 inverse-vol sizing"}
charts["addon_gain_vs_baseline"] = {"type": "bar", "x": [VN[v] for v in V],
                                    "series": {"2023-2025 gain vs frozen book (per yr)": [I2[v]["dev_c50"]["paired_vs_E0"]["diff_ann"] for v in V],
                                               "2026 gain vs frozen book (per yr)": [I2[v]["hold_c50"]["paired_vs_E0"]["diff_ann"] for v in V]},
                                    "title": "What each add-on changes vs the frozen book", "y_label": "annualised return difference",
                                    "note": "Paired daily difference vs the frozen baseline E0 (50 bps), annualised. Adoption needs DEV t >= 2 "
                                            "and no >3pp worse max drawdown."}

# ---------------------------------------------------------------- tables
rows = []
for nm, lab in (("PROD", "PROD book (frozen production score)"), ("single", "Single model (devil)"),
                ("ens3", "3-seed ensemble (devil)")):
    for per, plab in (("dev", "2023-2025"), ("hold", "2026 Jan-Oct")):
        for cost in (50, 80):
            p = I1[nm][f"{per}_c{cost}"]
            rows.append([lab, plab, cost / 1e4, p["pa_cagr"], p["pa_random_cagr"], p["pa_ew_cagr"], p["nifty500_stats"]["cagr"],
                         p["pa_excess_ann"], p["pa_nw_t"], p["pa_excess_vs_ew_ann"], p["pa_vs_ew_nw_t"], p["pa_maxdd"],
                         p["pa_sharpe"], p["pa_vol"], p["phase_excess_min"], p["phase_excess_max"]])
tables.append(C.table("1. Does the stock-picking book beat simple alternatives? (frozen PROD vs single model vs 3-seed ensemble)",
                      ["Score", "Period", "Round-trip cost", "Book CAGR", "Random top-20 CAGR", "Equal-weight universe CAGR",
                       "Nifty 500 price CAGR", "Excess vs random (per yr)", "t-stat vs random", "Excess vs equal-weight (per yr)",
                       "t-stat vs equal-weight", "Max drawdown", "Sharpe", "Volatility", "Worst entry-day phase excess",
                       "Best entry-day phase excess"], rows,
                      "Phase-averaged (weekly book started on each of the 5 weekdays, averaged). Excess = annualised mean daily "
                      "difference; t-stats are Newey-West (lag 20). 2026 is a holdout never used for selection. The Nifty 500 is a "
                      "price index (dividends ~1.2%/yr missing) while lab stock prices include dividends, so the random/equal-weight "
                      "books are the fair yardsticks. PROD stays the production score regardless (pre-registered)."))
yr = I1["PROD"]["contig_c50"]["by_year"]
tables.append(C.table("2. Calendar-year returns of the frozen PROD book (one continuous book, 50 bps)",
                      ["Year", "PROD book", "Random top-20", "Equal-weight universe", "Nifty 500 price", "Book minus random",
                       "Book minus equal-weight"],
                      [[y, yr[y]["strat"], yr[y]["random"], yr[y]["ew"], yr[y]["nifty500"], yr[y]["ex_vs_random"], yr[y]["ex_vs_ew"]]
                       for y in sorted(yr)],
                      "2023 starts in the first week of January; 2026 runs to mid-October (holdout). Differences are compounded "
                      "returns minus compounded returns. The separate fresh-start 2026 holdout book (table 1) starts its four sleeves "
                      "one week apart in January, so its absolute 2026 return differs from this continuous book; the excess vs random "
                      "is near zero in both."))
qq = I1["PROD"]["contig_c50"]["by_quarter"]
tables.append(C.table("2b. Quarter-by-quarter returns of the frozen PROD book (one continuous book, 50 bps)",
                      ["Quarter", "PROD book", "Random top-20", "Equal-weight universe", "Nifty 500 price", "Book minus random",
                       "Book minus equal-weight"],
                      [[k, qq[k]["strat"], qq[k]["random"], qq[k]["ew"], qq[k]["nifty500"], qq[k]["ex_vs_random"], qq[k]["ex_vs_ew"]]
                       for k in sorted(qq)],
                      "Quarters in 2026 are holdout. Compounded quarterly returns; differences are return minus return."))
AD = I2["adoption_rule_dev_c50"]
VERD = {"E0": "frozen baseline", "X1": "control only (adds cash yield; not a strategy)",
        "E1": ("passes the rule but NOT executable as specified (decides at the close with that close's signal); superseded by X3"
               if AD["E1"] else "rejected"),
        "X3": "ADOPTED (passes the rule; gain is mostly the overnight premium, see table 4)" if AD["X3"] else "rejected",
        "E2w": "adopted" if AD["E2w"] else "rejected", "E2d": "adopted" if AD["E2d"] else "rejected",
        "E3": "adopted" if AD["E3"] else "rejected", "S1": "adopted" if AD["S1"] else "rejected"}
rows = []
for v in ["E0", "X1", "E1", "X3", "E2w", "E2d", "E3", "S1"]:
    d_, h_ = I2[v]["dev_c50"], I2[v]["hold_c50"]
    pd_ = d_.get("paired_vs_E0", {})
    ph_ = h_.get("paired_vs_E0", {})
    rows.append([VN.get(v, "E0 frozen baseline (20-day time exit)"), d_["pa_cagr"], pd_.get("diff_ann"), pd_.get("nw_t"),
                 d_.get("paired_vs_X1", {}).get("nw_t"), d_["pa_maxdd"], d_.get("delta_maxdd_vs_E0"),
                 h_["pa_cagr"], ph_.get("diff_ann"), ph_.get("nw_t"), d_["turnover"]["traded_x_book_per_yr"],
                 d_["turnover"]["round_trips_per_yr"], d_["turnover"]["cost_drag_per_yr"], d_["early_exit_share"],
                 d_["carried_share"], VERD[v]])
tables.append(C.table("3. Exit, hold and sizing add-ons vs the frozen book (pre-declared list + disclosed extras)",
                      ["Variant", "2023-25 CAGR", "2023-25 gain vs frozen (per yr)", "Paired t vs frozen", "Paired t vs X1 (cash-yield control)",
                       "2023-25 max drawdown", "Change in max drawdown", "2026 CAGR", "2026 gain vs frozen (per yr)", "2026 paired t",
                       "Book traded per yr (x book, buys+sells)", "Round trips per yr", "Cost drag per yr", "Share of positions exited early",
                       "Share of positions carried", "Adopted under the rule?"], rows,
                      "50 bps round trip. Adoption rule (pre-registered): DEV paired Newey-West t >= 2 vs the frozen book and max "
                      "drawdown not worse by > 3 pp (early-exit rules must also beat X1, which only adds the cash yield). E1 as "
                      "specified decides at the rebalance close using that close's signal (not executable); X3 is the executable "
                      "version (disclosed post-hoc). X3's gain is mostly the overnight premium, see table 4."))
rows = []
for per, plab in (("dev", "2023-2025"), ("hold", "2026")):
    d_ = I2b[f"{per}_c50"]
    rows.append([plab, d_["random_E0timing_cagr"], d_["random_X3timing_cagr"], d_["random_timing_gain"]["diff_ann"],
                 d_["random_timing_gain"]["nw_t"], d_["X3_minus_E1"]["diff_ann"], d_["E1_minus_E0"]["diff_ann"],
                 d_["E0_excess_vs_random"]["diff_ann"], d_["X3_excess_vs_timing_matched_random"]["diff_ann"],
                 d_["X3_excess_vs_timing_matched_random"]["nw_t"]])
tables.append(C.table("4. Where the carry gain comes from: mostly the overnight premium, not stock-picking skill",
                      ["Period", "Random book, frozen timing", "Random book, X3 timing", "Timing gain for random picks (per yr)",
                       "t", "X3 minus E1: exit at next open instead of close (per yr)", "E1 minus frozen: cost saving + carried gap (per yr)",
                       "Frozen book skill: excess vs random", "X3 skill: excess vs timing-matched random", "t"], rows,
                      "Holding positions through the rebalance night and trading at the next open earns the close-to-open move, "
                      "which was strongly positive for Indian stocks in 2023-2026. Random picks gain almost as much from the same "
                      "timing, so the model's skill (excess vs a random book with the same timing) is essentially unchanged."))
G = R["item2c_overnight_gap_check"]
rows = []
for per, plab in (("dev", "2023-2025"), ("hold", "2026")):
    for who, wl in (("model_exits", "Names the PROD book sells at a rebalance"), ("random_exits", "Random names")):
        g_ = G[per][who]
        rows.append([plab, wl, g_["n"], g_["mean_gap"], g_["median_gap"], g_["share_positive"], g_["trimmed_mean_1_99"],
                     g_["mean_gap_liq5"], g_["mean_gap_liq2_only"]])
tables.append(C.table("4b. The overnight move (close to next open) of the names being sold",
                      ["Period", "Names", "Number of exits", "Mean overnight move", "Median overnight move", "Share positive",
                       "Mean after trimming 1% tails", "Mean, more liquid names (liq5)", "Mean, less liquid names (liq2 only)"], rows,
                      "Exits of names picked 20 trading days earlier (every trading day used as a signal date). The overnight move is "
                      "broad (not a few outliers) and present in the more liquid names too, but it shrank from 2023-24 to 2026. "
                      "Selling at the open captures it; selling at the close (the frozen book) forgoes it."))
rows = []
for p in PN:
    for Y in (0.5, 1.0):
        for a in A:
            dv, hv = P_[p][f"Y{Y}_{a}_dev"], P_[p][f"Y{Y}_{a}_hold"]
            rows.append([PN[p], Y, a.replace("cr", " cr"), dv["pa_cagr"], dv["pa_random_cagr"], dv["pa_excess_ann"], dv["pa_nw_t"],
                         dv["pa_maxdd"], hv["pa_cagr"], hv["pa_excess_ann"]])
tables.append(C.table("5. Capacity: returns after market impact by fund size (frozen book)",
                      ["Policy", "Impact coefficient Y", "Fund size (Rs)", "2023-25 CAGR", "2023-25 random CAGR (same impact)",
                       "2023-25 excess vs random", "t", "2023-25 max drawdown", "2026 CAGR", "2026 excess vs random"], rows,
                      f"Each name gets AUM/80. Impact per side = Y x daily vol x sqrt(position / 20-day median traded value), capped "
                      f"at 10%, plus 50 bps base cost. Capped policies hold at most 5% of a name's ADV and leave the rest in cash. "
                      f"Idle cash earns the Nifty 1D Rate. References: equal-weight universe CAGR {I3['refs']['dev']['ew_cagr']:.4f} "
                      f"(2023-25) / {I3['refs']['hold']['ew_cagr']:.4f} (2026); Nifty 500 price {I3['refs']['dev']['nifty500_cagr']:.4f} / "
                      f"{I3['refs']['hold']['nifty500_cagr']:.4f}."))
cr = I3["crossings_aum_cr"]
rows = [[PN[p], Y, cr[f"{p}_Y{Y}_dev"]["aum_cr_cagr_eq_EW"], cr[f"{p}_Y{Y}_dev"]["aum_cr_cagr_eq_Nifty500"],
         cr[f"{p}_Y{Y}_hold"]["aum_cr_cagr_eq_EW"], cr[f"{p}_Y{Y}_hold"]["aum_cr_cagr_eq_Nifty500"]] for p in PN for Y in (0.5, 1.0)]
tables.append(C.table("6. Fund size (Rs crore) at which the book stops beating the passive alternatives",
                      ["Policy", "Impact coefficient Y", "2023-25: AUM where CAGR = equal-weight universe",
                       "2023-25: AUM where CAGR = Nifty 500", "2026: AUM where CAGR = equal-weight universe",
                       "2026: AUM where CAGR = Nifty 500"], rows,
                      "Log-linear interpolation between the tested fund sizes (Rs 1, 5, 20, 50, 100 crore). 'below_1cr' means the "
                      "book already trails at Rs 1 crore; 'above_100cr' means it still leads at Rs 100 crore."))
pt = I3["participation"]
rows = []
for per, plab in (("dev", "2023-2025"), ("hold", "2026")):
    for a in A:
        q_ = pt[per][a]
        rows.append([plab, a.replace("cr", " cr"), q_["position_lakh"], pt[per]["model_adv_cr_median"], q_["median_participation"],
                     q_["p90_participation"], q_["share_gt10pct"], q_["fill_under_5pct_cap_mean"], q_["impact_bps_side_Y1_mean"] / 1e4])
tables.append(C.table("7. Operations: how big are our trades relative to what trades in each stock?",
                      ["Period", "Fund size (Rs)", "Position per name (Rs lakh)", "Median ADV20 of picks (Rs crore)",
                       "Median participation (position / ADV20)", "90th percentile participation", "Share of picks above 10% of ADV",
                       "Average fill under a 5% ADV cap", "Average impact per side (Y=1)"], rows,
                      f"Frozen book: about {I2['E0']['dev_c50']['turnover']['orders_per_week']:.0f} orders per week "
                      f"(buys + sells), about {I2['E0']['dev_c50']['avg_names_held']:.0f} names held on a typical day (80 slots), "
                      f"{I2['E0']['dev_c50']['turnover']['round_trips_per_yr']:.0f} round trips per year; executable carry (X3) cuts "
                      f"orders to about {I2['X3']['dev_c50']['turnover']['orders_per_week']:.0f} per week."))
rows = []
for nm, lab in (("E0", "PROD book (frozen)"), ("X3", "PROD book + executable carry")):
    t_ = I4[nm]
    rows.append([lab, "Short-term capital gains (15% -> 20% from 23-Jul-2024)", t_["tax_stcg"]["pre_tax_cagr"],
                 t_["tax_stcg"]["post_tax_cagr"], t_["tax_stcg"]["tax_drag_cagr"]])
    rows.append([lab, "Business income (31.2%, STT deductible)", t_["tax_business_income"]["pre_tax_cagr"],
                 t_["tax_business_income"]["post_tax_cagr"], t_["tax_business_income"]["tax_drag_cagr"]])
bh = I4["nifty500_buy_hold"]
for cap in ("Rs50L", "Rs5cr"):
    rows.append([f"Buy-and-hold Nifty 500 (price index), capital {cap.replace('Rs', 'Rs ')}", "Long-term gain 12.5% above Rs 1.25 lakh, paid at sale",
                 bh["pre_tax_cagr"], bh[cap]["post_tax_cagr"], bh[cap]["tax_drag_cagr"]])
tables.append(C.table("8. Tax illustration for an Indian individual (Jan 2023 - Oct 2026)",
                      ["Strategy", "Tax treatment", "Pre-tax CAGR", "Post-tax CAGR", "Tax drag (per yr)"], rows,
                      "Simplified calendar-year model: tax paid each year-end from the book; short-term losses carried forward; STT "
                      "(0.1% buy + 0.1% sell) is not deductible from capital gains, so taxable gain = net P&L + STT. Frequent "
                      "trading may be assessed as business income instead (slab rate; STT then deductible). Nifty 500 is a price index "
                      "(dividends excluded, which would add ~1.2%/yr before dividend tax). Not tax advice."))
C.save("charts", charts)
C.save("html_tables", tables)
C.save("charts_check", {"E0_contig_booksim_vs_item1_max_abs_diff": chk})
C.log("charts", list(charts), "tables", len(tables), "check", chk)

"""Stage 6: extra tests and diagnostics.

(a) ISOLATED-event continuation (hypothesis formed from s2: crash / breakdown names on QUIET market days
    keep falling).  quiet = brd < 2% (below-median breadth).  6 events x h{5,10,20} = 18 more tests.
(b) Scorecard xs metrics: L.xs_metrics with the event INDICATOR (1 event / 0 other elig rows) as the score
    over elig_base (per-date IC, AUC vs 1{x_h>0}), plus per-date event-vs-rest AUC (common-language effect).
(c) Core-overlap: on gate days, how many of the core book's top-20 are gate events (redundancy check).
(d) One-model stack: core score + tilt toward gate events  (score = per-date pct(core) + 0.3*1{A1});
    core with an AVOID exclusion of quiet-day crash/blow-off names.  (2 variants, DEV-judged.)
(e) Sleeve robustness: 130 bps stress; month-cluster t and episode-drop of sleeve-vs-matched excess.
"""
import numpy as np
import pandas as pd
from scipy.stats import norm

from common import (OUT, L, T, EventStudy, SimX, load_base, matched_mask, counts_by_g, save, cluster_t,
                    eq_stats, summarize_runs, excess_stats)

t = T()
B = load_base()
ES = EventStudy(B)
U = B["U"]
didx = ES.didx
ncal = len(ES.cal)
brd_day = np.load(f"{OUT}/brd_day.npy")
brd = brd_day[didx]
mm20 = B["mkt_mom20"]
vz = B["volz_20"]
quiet = brd < 0.02
with np.errstate(invalid="ignore"):
    ISO = {"Q_R1|L20v1": U & (B["bdd20"] < 0) & (vz > 1) & quiet,
           "Q_CR|k3": U & (B["r1"] <= -3 * B["vol20_lag"]) & (vz > 1) & quiet,
           "Q_CR|k4": U & (B["r1"] <= -4 * B["vol20_lag"]) & (vz > 1) & quiet,
           "Q_GR|m2": U & (B["gap_open"] <= -2 * B["atr_lag"]) & (B["intraday"] > 0) & quiet,
           "Q_BO|k3": U & (B["r1"] >= 3 * B["vol20_lag"]) & (vz > 1) & quiet,
           "Q_BO|k4": U & (B["r1"] >= 4 * B["vol20_lag"]) & (vz > 1) & quiet}
    A1 = U & (B["bdd10"] < 0) & (vz > 0) & (mm20 < 0) & (brd >= 0.05)
    A0 = U & (B["bdd20"] < 0) & (vz > 1) & (mm20 < 0)
rows = []
for name, m in ISO.items():
    for h in (5, 10, 20):
        st = ES.stats(m, h, detail=True)
        r = {"def": name, "h": h}
        for wn in ("dev", "hold", "pre"):
            for k in ("n", "event_days", "p_net_pos", "net_bps", "xs_bps", "xs_t_month", "xs_dw_bps", "xs_dw_t_month", "p_xs_pos"):
                r[f"{wn}_{k}"] = st.get(wn, {}).get(k, np.nan)
        r["by_year_xs"] = {y: v["xs_bps"] for y, v in st["by_year"].items()}
        rows.append(r)
iso = pd.DataFrame(rows)
t("isolated tests")

# total Bonferroni bookkeeping: s2 grid (342) + 18 isolated, x2 statistics (event- and date-weighted)
g2 = pd.read_csv(f"{OUT}/s2_grid.csv")
N_cells = len(g2) + len(iso)
N_tests = 2 * N_cells
z_b = float(norm.ppf(1 - 0.025 / N_tests))
allt = pd.concat([g2[["def", "h", "dev_xs_t_month", "dev_xs_dw_t_month", "dev_xs_bps", "dev_xs_dw_bps", "dev_n",
                      "hold_xs_bps", "hold_xs_t_month"]],
                  iso[["def", "h", "dev_xs_t_month", "dev_xs_dw_t_month", "dev_xs_bps", "dev_xs_dw_bps", "dev_n",
                       "hold_xs_bps", "hold_xs_t_month"]]])
passing = allt[(allt.dev_xs_t_month.abs() > z_b) | (allt.dev_xs_dw_t_month.abs() > z_b)]
save("s6_isolated", {"rows": iso.to_dict("records"), "N_cells": N_cells, "N_tests": N_tests,
                     "bonferroni_z": z_b, "passing": passing.to_dict("records")})
print("Bonferroni z", round(z_b, 3), "cells", N_cells, "tests", N_tests)
pd.set_option("display.width", 250)
print(iso.drop(columns=["by_year_xs"]).round(2).to_string())
print(passing.round(2).to_string())

# ---------------- (b) xs metrics with the event indicator ----------------
P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
xsm = {}
for gname, g in (("A0", A0), ("A1", A1), ("Q_CR|k3", ISO["Q_CR|k3"]), ("Q_BO|k3", ISO["Q_BO|k3"])):
    ind = np.where(U, g.astype(float), np.nan)
    o = {}
    for h in (5, 10, 20):
        x = B[f"x{h}"].astype("float64")
        xm = L.xs_metrics(ind, x, U, P, h, binary_target=np.where(np.isfinite(x), (x > 0).astype(float), np.nan))
        # per-date AUC of event vs rest on x_h (dates with >=1 event and >=5 events for stability)
        v = U & np.isfinite(x)
        df = pd.DataFrame({"d": didx[v], "e": g[v], "x": x[v]})
        df["rk"] = df.groupby("d").x.rank()
        agg = df.groupby("d").agg(n=("e", "size"), n1=("e", "sum"))
        s1 = df[df.e].groupby("d").rk.sum()
        agg = agg.join(s1.rename("s1")).dropna()
        agg = agg[agg.n1 >= 1]
        agg["auc"] = (agg.s1 - agg.n1 * (agg.n1 + 1) / 2) / (agg.n1 * (agg.n - agg.n1))
        dd = ES.cal[agg.index.values]
        dev = (dd >= np.datetime64("2023-01-01")) & (dd <= ES.dev_end[h])
        hold = dd >= np.datetime64("2026-01-01")
        mon = dd.astype("datetime64[M]").astype(np.int64)
        o[h] = {"xs_metrics": xm,
                "auc_event_vs_rest_dev_ew": float(np.average(agg.auc[dev], weights=agg.n1[dev])) if dev.any() else None,
                "auc_event_vs_rest_dev_dw": float(agg.auc[dev].mean()) if dev.any() else None,
                "auc_dw_dev_t_month": cluster_t(agg.auc[dev].values - 0.5, mon[dev])[0] if dev.sum() > 5 else None,
                "auc_event_vs_rest_hold_ew": float(np.average(agg.auc[hold], weights=agg.n1[hold])) if hold.any() else None,
                "auc_event_vs_rest_hold_dw": float(agg.auc[hold].mean()) if hold.any() else None,
                "auc_dw_hold_t_month": cluster_t(agg.auc[hold].values - 0.5, mon[hold])[0] if hold.sum() > 5 else None}
    xsm[gname] = o
save("s6_xs_indicator", xsm)
t("xs indicator")

# ---------------- (c) core overlap on gate days ----------------
sc_core = np.load(f"{L.LAB}/results/R2_rel/wf_h20_neumom_RANK.npz")["score"].astype("float64")
v = U & np.isfinite(sc_core)
df = pd.DataFrame({"d": didx[v], "s": sc_core[v], "a1": A1[v], "a0": A0[v]})
df["rk_desc"] = df.groupby("d").s.rank(ascending=False, method="first")
df["pct"] = df.groupby("d").s.rank(pct=True)
gd = df.groupby("d").agg(n=("s", "size"), na1=("a1", "sum"), na0=("a0", "sum"))
top = df[df.rk_desc <= 20].groupby("d").agg(t_a1=("a1", "sum"), t_a0=("a0", "sum"))
gd = gd.join(top)
days_a1 = gd[gd.na1 > 0]
ov = {"gate_days": int(len(days_a1)),
      "mean_events_per_gate_day": float(days_a1.na1.mean()),
      "base_share_events_in_U": float((days_a1.na1 / days_a1.n).mean()),
      "share_core_top20_that_are_events": float((days_a1.t_a1 / 20).mean()),
      "mean_core_pct_of_events": float(df[df.a1].pct.mean()),
      "core_top20_overlap_A0_days": float((gd[gd.na0 > 0].t_a0 / 20).mean()),
      "A0_base_share": float((gd[gd.na0 > 0].na0 / gd[gd.na0 > 0].n).mean()),
      "mean_core_pct_of_A0_events": float(df[df.a0].pct.mean())}
save("s6_core_overlap", ov)
print("overlap", ov)

# ---------------- (d) one-model stack variants ----------------
F = L.load_features(["atr_pct"])
fw = L.Fwd(P)
S = SimX(P, F, fw)
pct_core = np.full(len(U), np.nan)
pct_core[np.flatnonzero(v)] = df.sort_index().pct.values if False else np.nan
pc = pd.Series(np.where(v, sc_core, np.nan)).groupby(didx).rank(pct=True).values
avoid = ISO["Q_CR|k3"] | ISO["Q_BO|k3"]
VAR = {"CORE": (pc, v), "CORE_TILT_A1_0.3": (pc + 0.3 * A1, v), "CORE_AVOID_QCR3_QBO3": (pc, v & ~avoid)}
WIN = {"dev": dict(start=L.DEV[0], end_exit=L.DEV[1]), "hold": dict(start="2026-01-01", end_exit=None)}
stack = {}
for cost in (50, 80):
    for wn, w in WIN.items():
        base_r = None
        rr = {}
        rnd = summarize_runs([S.run(None, U, 20, step=5, top_k=20, cost_bps=cost, random_seed=s, **w) for s in (1, 2, 3, 4, 5)])
        for vn, (sc, msk) in VAR.items():
            r = S.run(sc, msk, 20, step=5, top_k=20, cost_bps=cost, **w)
            rr[vn] = r
            o = {"cagr": r["cagr"], "sharpe": r["sharpe"], "max_dd": r["max_dd"], "exposure": r["exposure"],
                 "mean_trade_net": r["mean_trade_net"], "by_year": r["by_year"],
                 "exc_vs_random_cagr": r["cagr"] - rnd["cagr"], "exc_vs_random_nw_t": L.nw_t(r["_daily_ret"] - rnd["_daily_ret"], 20)}
            if vn != "CORE":
                o["d_vs_core_ann"] = float((r["_daily_ret"] - rr["CORE"]["_daily_ret"]).mean() * 252)
                o["nw_t_vs_core"] = L.nw_t(r["_daily_ret"] - rr["CORE"]["_daily_ret"], 20)
            stack[f"{vn}|{cost}|{wn}"] = o
        stack[f"RANDOM|{cost}|{wn}"] = {"cagr": rnd["cagr"], "sharpe": rnd["sharpe"], "max_dd": rnd["max_dd"]}
save("s6_stack", stack)
for k, o in stack.items():
    print(k, {kk: (round(vv, 4) if isinstance(vv, float) else vv) for kk, vv in o.items() if kk != "by_year"})
t("stack")

# ---------------- (e) sleeve robustness ----------------
sc_meta = np.load(f"{OUT}/s4_scores.npz")["WF_R10"].astype("float64")
rob = {}
gm = A1 & np.isfinite(sc_meta)
cnt = counts_by_g(gm, sc_meta, didx, ncal, 20)
mms = [matched_mask(cnt, U, didx, s) for s in (1, 2, 3, 4, 5)]
cnt_all = counts_by_g(A1, None, didx, ncal, 20)
mms_all = [matched_mask(cnt_all, U, didx, s) for s in (1, 2, 3, 4, 5)]
ep_brd10 = brd_day >= 0.10
for h in (5, 10, 20):
    for cost in (50, 80, 130):
        for wn, w in WIN.items():
            kw = dict(step=1, top_k=20, cost_bps=cost, **w)
            st = S.run(sc_meta, gm, h, **kw)
            ma = summarize_runs([S.run(None, mm, h, random_seed=s, **kw) for s, mm in zip((1, 2, 3, 4, 5), mms)])
            al = summarize_runs([S.run(None, A1, h, random_seed=s, **kw) for s in (1, 2, 3, 4, 5)])
            alm = summarize_runs([S.run(None, mm, h, random_seed=s, **kw) for s, mm in zip((1, 2, 3, 4, 5), mms_all)])
            dts = st["_dates"]
            mon = dts.astype("datetime64[M]").astype(np.int64)
            d1 = st["_daily_ret"] - ma["_daily_ret"]
            d2 = st["_daily_ret"] - al["_daily_ret"]
            d3 = al["_daily_ret"] - alm["_daily_ret"]
            # drop the single best calendar month of excess (concentration check)
            ms = pd.Series(d1).groupby(mon).sum()
            best = ms.idxmax()
            keep = mon != best
            rob[f"h{h}|{cost}|{wn}"] = {
                "meta_cagr": st["cagr"], "meta_sharpe": st["sharpe"], "meta_max_dd": st["max_dd"], "meta_exposure": st["exposure"],
                "meta_mean_trade_net": st["mean_trade_net"], "meta_by_year": st["by_year"],
                "all_cagr": al["cagr"], "all_sharpe": al["sharpe"], "matched_cagr": ma["cagr"], "all_matched_cagr": alm["cagr"],
                "meta_vs_matched_ann": float(d1.mean() * 252), "meta_vs_matched_nw_t": L.nw_t(d1, h),
                "meta_vs_matched_month_t": cluster_t(d1, mon)[0],
                "meta_vs_matched_ann_excl_best_month": float(d1[keep].mean() * 252),
                "meta_vs_matched_nw_t_excl_best_month": L.nw_t(d1[keep], h),
                "best_month": str(np.datetime64(int(best), "M")),
                "meta_vs_all_ann": float(d2.mean() * 252), "meta_vs_all_nw_t": L.nw_t(d2, h), "meta_vs_all_month_t": cluster_t(d2, mon)[0],
                "all_vs_matched_ann": float(d3.mean() * 252), "all_vs_matched_nw_t": L.nw_t(d3, h),
                "all_vs_matched_month_t": cluster_t(d3, mon)[0]}
save("s6_sleeve_robust", rob)
for k, o in rob.items():
    print(k, {kk: (round(vv, 4) if isinstance(vv, float) else vv) for kk, vv in o.items() if kk not in ("meta_by_year",)})
t("done")

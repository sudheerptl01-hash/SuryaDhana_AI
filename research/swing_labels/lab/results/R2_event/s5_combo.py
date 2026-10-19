"""Stage 5: combine the capitulation sleeve with the relative core book.

CORE  = R2_rel selected label h20_neumom_RANK (walk_forward2 OOS score, reused from R2_rel), elig_base,
        long top-20, step 5, h=20, slot sizing (reproduces R2_rel: DEV CAGR 30.9%).
SLEEVES (step=1, K=20 slots per daily sleeve; gate A1 = close<10d-low & volz>0 & Nifty-500 mom20<0 &
        >=5% of elig at new 20d lows):
   S5_META   A1, top-20 by WF_R10 (event meta-model), h=5   <- DEV-selected sleeve (s4: best DEV t)
   S10_META  A1, top-20 by WF_R10, h=10
   S10_CORE  A1, top-20 by the CORE model's own score (EB_XR20), h=10   <- one-model stack
   S10_ALL   A1, all events (random tie-break, 5 seeds), h=10
   S10_R1DN  A0 (round-1 R1dn) all events, h=10
   + count-matched universe-random twins of each (same days, same counts) to isolate selection value.
Combos (daily returns; DEV and HOLD separately):
   MIX w   : (1-w) core + w sleeve (sleeve idle cash at 0%), constant weights (daily rebalanced approx.)
   OVL w   : sleeve idle cash parked IN the core book: r = r_core + w (r_sleeve - x_t r_core)
             - w |dx_t| * cost/2 (switching cost on capital moved between core and sleeve)
Diagnostics: daily / weekly / monthly correlations (also of excess-vs-baseline returns), sleeve return
on the core's worst days/months, NW t (lag 20) of combo minus core and of combo minus combo-with-matched-sleeve.
"""
import numpy as np
import pandas as pd

from common import (OUT, L, T, SimX, load_base, matched_mask, counts_by_g, save, eq_stats)

t = T()
P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["atr_pct"])
fw = L.Fwd(P)
S = SimX(P, F, fw)
B = load_base()
U = B["U"]
didx = S.didx
ncal = len(S.cal)
brd = np.load(f"{OUT}/brd_day.npy")[didx]
mm20 = B["mkt_mom20"]
A1 = U & (B["bdd10"] < 0) & (B["volz_20"] > 0) & (mm20 < 0) & (brd >= 0.05)
A0 = U & (B["bdd20"] < 0) & (B["volz_20"] > 1) & (mm20 < 0)
sc_core = np.load(f"{L.LAB}/results/R2_rel/wf_h20_neumom_RANK.npz")["score"].astype("float64")
sc_meta = np.load(f"{OUT}/s4_scores.npz")["WF_R10"].astype("float64")
WIN = {"dev": dict(start=L.DEV[0], end_exit=L.DEV[1]), "hold": dict(start="2026-01-01", end_exit=None)}
SEEDS = (1, 2, 3, 4, 5)
K = 20
t("init")


def avg_runs(runs):
    return {"r": np.vstack([x["_daily_ret"] for x in runs]).mean(0),
            "x": np.vstack([x["_invested"] for x in runs]).mean(0), "d": runs[0]["_dates"],
            "exposure": float(np.mean([x["exposure"] for x in runs])), "cagr": float(np.mean([x["cagr"] for x in runs]))}


def one(run):
    return {"r": run["_daily_ret"], "x": run["_invested"], "d": run["_dates"], "exposure": run["exposure"], "cagr": run["cagr"]}


SLEEVES = {"S5_META": (A1, sc_meta, 5), "S10_META": (A1, sc_meta, 10), "S10_CORE": (A1, sc_core, 10),
           "S10_ALL": (A1, None, 10), "S10_R1DN": (A0, None, 10), "S20_META": (A1, sc_meta, 20)}
out = {}
series = {}
for cost in (50, 80):
    for wn, w in WIN.items():
        core = S.run(sc_core, U & np.isfinite(sc_core), 20, step=5, top_k=20, cost_bps=cost, **w)
        rc = core["_daily_ret"]
        dates = core["_dates"]
        crand = avg_runs([S.run(None, U, 20, step=5, top_k=20, cost_bps=cost, random_seed=s, **w) for s in SEEDS])
        res = {"core": {**eq_stats(rc, dates), "exposure": core["exposure"]},
               "core_random": eq_stats(crand["r"], dates), "sleeves": {}}
        series[f"core|{cost}|{wn}"] = rc
        for sn, (g, sc, h) in SLEEVES.items():
            kw = dict(step=1, top_k=K, cost_bps=cost, **w)
            if sc is None:
                sl = avg_runs([S.run(None, g, h, random_seed=s, **kw) for s in SEEDS])
                cnt = counts_by_g(g, None, didx, ncal, K)
            else:
                gm = g & np.isfinite(sc)
                sl = one(S.run(sc, gm, h, **kw))
                cnt = counts_by_g(gm, sc, didx, ncal, K)
            ma = avg_runs([S.run(None, matched_mask(cnt, U, didx, s), h, random_seed=s, **kw) for s in SEEDS])
            # align sleeve series onto the core's calendar (windows start on the same day; the Sim ends at
            # the last signal + one period, which differs by (h, step)); days outside a sleeve window = cash.
            def al(v, dd):
                s_ = pd.Series(v, index=pd.DatetimeIndex(dd)).reindex(pd.DatetimeIndex(dates))
                return s_.fillna(0.0).values
            rs, xs = al(sl["r"], sl["d"]), al(sl["x"], sl["d"])
            rm, xm = al(ma["r"], ma["d"]), al(ma["x"], ma["d"])
            d = pd.DatetimeIndex(dates)
            o = {"sleeve": {**eq_stats(rs, dates), "exposure": sl["exposure"]},
                 "matched": {**eq_stats(rm, dates), "exposure": ma["exposure"]}}
            # correlations
            dfc = pd.DataFrame({"c": rc, "s": rs, "cx": rc - crand["r"], "sx": rs - rm}, index=d)
            wk = (1 + dfc[["c", "s"]]).resample("W").prod() - 1
            mo = (1 + dfc[["c", "s"]]).resample("ME").prod() - 1
            act = xs > 0.02
            o["corr"] = {"daily": float(dfc.c.corr(dfc.s)), "daily_when_sleeve_active": float(dfc.c[act].corr(dfc.s[act])),
                         "weekly": float(wk.c.corr(wk.s)), "monthly": float(mo.c.corr(mo.s)),
                         "daily_excess": float(dfc.cx.corr(dfc.sx)),
                         "share_days_active": float(act.mean())}
            worst = dfc.c <= dfc.c.quantile(0.05)
            o["tail"] = {"core_worst5pct_days_mean_core_bps": 1e4 * float(dfc.c[worst].mean()),
                         "core_worst5pct_days_mean_sleeve_bps": 1e4 * float(dfc.s[worst].mean()),
                         "core_worst3_months": {str(k.date()): {"core": float(v), "sleeve": float(mo.s.loc[k])}
                                                for k, v in mo.c.nsmallest(3).items()}}
            o["combos"] = {}
            for wgt in (0.1, 0.2, 0.3):
                mix = (1 - wgt) * rc + wgt * rs
                mixm = (1 - wgt) * rc + wgt * rm
                dx = np.abs(np.diff(np.r_[0.0, xs]))
                dxm = np.abs(np.diff(np.r_[0.0, xm]))
                ovl = rc + wgt * (rs - xs * rc) - wgt * dx * (cost / 1e4 / 2)
                ovlm = rc + wgt * (rm - xm * rc) - wgt * dxm * (cost / 1e4 / 2)
                for nm, a, b in (("MIX", mix, mixm), ("OVL", ovl, ovlm)):
                    o["combos"][f"{nm}{int(wgt * 100)}"] = {
                        **eq_stats(a, dates),
                        "d_cagr_vs_core": eq_stats(a, dates)["cagr"] - res["core"]["cagr"],
                        "d_sharpe_vs_core": eq_stats(a, dates)["sharpe"] - res["core"]["sharpe"],
                        "d_maxdd_vs_core": eq_stats(a, dates)["max_dd"] - res["core"]["max_dd"],
                        "nw_t_vs_core": L.nw_t(a - rc, 20),
                        "with_matched_sleeve": eq_stats(b, dates),
                        "nw_t_vs_matched_combo": L.nw_t(a - b, 20)}
                    if cost == 50 and wgt == 0.2:
                        series[f"{nm}20|{sn}|{wn}"] = a
            if cost == 50:
                series[f"sleeve|{sn}|{wn}"] = rs
                series[f"sleevex|{sn}|{wn}"] = xs
                series[f"matched|{sn}|{wn}"] = rm
            res["sleeves"][sn] = o
        out[f"{cost}|{wn}"] = res
        t(f"cost {cost} {wn}")
np.savez_compressed(f"{OUT}/s5_series.npz", **series)
save("s5_combo", out)
for key, res in out.items():
    print("=====", key, "core", {k: round(v, 4) for k, v in res["core"].items() if k != "by_year"}, "by_year", {k: round(v, 3) for k, v in res["core"]["by_year"].items()})
    for sn, o in res["sleeves"].items():
        c = o["combos"]
        print(f"  {sn:9s} sleeve cagr {o['sleeve']['cagr']:.4f} sh {o['sleeve']['sharpe']:.2f} dd {o['sleeve']['max_dd']:.3f} exp {o['sleeve']['exposure']:.3f} | "
              f"corr d {o['corr']['daily']:.2f} w {o['corr']['weekly']:.2f} m {o['corr']['monthly']:.2f} ex {o['corr']['daily_excess']:.2f} | "
              f"MIX20 cagr {c['MIX20']['cagr']:.4f} sh {c['MIX20']['sharpe']:.2f} dd {c['MIX20']['max_dd']:.3f} | "
              f"OVL20 cagr {c['OVL20']['cagr']:.4f} sh {c['OVL20']['sharpe']:.2f} dd {c['OVL20']['max_dd']:.3f} t_core {c['OVL20']['nw_t_vs_core']:.2f} t_match {c['OVL20']['nw_t_vs_matched_combo']:.2f}")
t("done")

"""R3_book item 1: reproduce PROD (10-model rank average, frozen) vs the devil's single model (wf_main)
vs the devil's 3-seed ensemble (main, seed1, seed2 rank-averaged exactly as R3_devil/s8_extra.py).
Phase-averaged (5 weekly entry phases) DEV and 2026, 50 and 80 bps, vs 5-seed random and EW universe.
Also the contiguous 2023-01-01 -> 2026-10-14 book (charts / tax). Saves section item1_repro ASAP."""
import os
import sys

import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
sys.path.insert(0, LAB)
import r3common as C  # noqa: E402

OUT = C.set_agent("R3_book")
L = C.L
P, F, fw, S, E = C.load_sim()
Z = C.load_prod()
d = P["date"].values
DV = f"{LAB}/results/R3_devil"
sc_main = np.load(f"{DV}/wf_main.npz")["score"].astype("float64")
sc1 = np.load(f"{DV}/wf_seed1.npz")["score"].astype("float64")
sc2 = np.load(f"{DV}/wf_seed2.npz")["score"].astype("float64")
rk = [pd.Series(np.where(E, s, np.nan)).groupby(d).rank(pct=True).values for s in (sc_main, sc1, sc2)]
ens3 = np.nanmean(np.vstack(rk), 0)
ens3 = np.where(E & np.isfinite(sc_main), ens3, np.nan)
del rk, sc1, sc2
SCORES = {"PROD": Z["prod"].astype("float64"), "single": sc_main, "ens3": ens3}
C.log("scores ready", {k: int(np.isfinite(v).sum()) for k, v in SCORES.items()})

n5 = L.market_series("Nifty 500")["close"].astype("float64")
n5.index = pd.DatetimeIndex(n5.index)


def idx_on(common):
    lv = n5.reindex(n5.index.union(common)).ffill().reindex(common)
    return lv.pct_change().fillna(0.0)


def sstats(r):
    r = np.asarray(r)
    eq = np.cumprod(1 + r)
    yrs = len(r) / 252
    return {"cagr": float(eq[-1] ** (1 / yrs) - 1), "vol": float(r.std() * np.sqrt(252)),
            "sharpe": float(r.mean() / r.std() * np.sqrt(252)), "maxdd": float((eq / np.maximum.accumulate(eq) - 1).min())}


def breakdown(sm, rm, em, nm, freq):
    df = pd.DataFrame({"s": sm.values, "r": rm.values, "e": em.values, "n": nm.values}, index=sm.index)
    key = df.index.year if freq == "Y" else df.index.to_period("Q").astype(str)
    out = {}
    for k, g in df.groupby(key):
        out[str(k)] = {"strat": float(np.prod(1 + g.s) - 1), "random": float(np.prod(1 + g.r) - 1),
                       "ew": float(np.prod(1 + g.e) - 1), "nifty500": float(np.prod(1 + g.n) - 1),
                       "ex_vs_random": float(np.prod(1 + g.s) - np.prod(1 + g.r)),
                       "ex_vs_ew": float(np.prod(1 + g.s) - np.prod(1 + g.e)),
                       "ex_vs_random_ann": float((g.s - g.r).mean() * 252),
                       "ex_vs_ew_ann": float((g.s - g.e).mean() * 252), "days": int(len(g))}
    return out


def trade_stats(score, period, cost):
    a, b = C.PER[period] if isinstance(period, str) else period
    g0 = int(np.searchsorted(S.cal, np.datetime64(a)))
    keys = ("trades", "hit_rate", "mean_trade_net", "median_trade_net", "exposure", "avg_bars", "forced_exits")
    acc = {k: [] for k in keys}
    for k in range(5):
        st = S.run(score, E, 20, top_k=20, step=5, cost_bps=cost, start=str(S.cal[g0 + k]), end_exit=b)
        for kk in keys:
            acc[kk].append(st[kk])
    return {k: float(np.mean(v)) for k, v in acc.items()}


res = {}
series = {}
PERIODS = {"dev": "dev", "hold": "hold", "contig": ("2023-01-01", None)}
for name, sc in SCORES.items():
    res[name] = {}
    for pname, per in PERIODS.items():
        for cost in (50, 80):
            if pname == "contig" and name != "PROD" and cost == 80:
                continue
            kw = dict(C.BASE_KW, cost_bps=cost)
            pa, sm, rm, em = C.phase_avg(S, sc, E, "liq2", 20, kw, per, with_ew=True)
            nm = idx_on(sm.index)
            pa["random_stats"] = sstats(rm.values)
            pa["ew_stats"] = sstats(em.values)
            pa["nifty500_stats"] = sstats(nm.values)
            pa["strat_stats"] = sstats(sm.values)
            pa["start"] = str(sm.index[0])[:10]
            pa["end"] = str(sm.index[-1])[:10]
            pa["by_year"] = breakdown(sm, rm, em, nm, "Y")
            pa["by_quarter"] = breakdown(sm, rm, em, nm, "Q")
            if pname != "contig":
                pa["trade_stats_phase_mean"] = trade_stats(sc, per, cost)
            res[name][f"{pname}_c{cost}"] = pa
            series[f"{name}_{pname}_c{cost}"] = (sm, rm, em, nm)
            C.log(name, pname, cost, C.short({k: pa[k] for k in ("pa_cagr", "pa_random_cagr", "pa_ew_cagr", "pa_excess_ann",
                                                                 "pa_nw_t", "pa_excess_vs_ew_ann", "pa_vs_ew_nw_t",
                                                                 "pa_maxdd", "phase_excess_min", "phase_excess_max")}))
    # save after each score so the lead can read partial results
    C.save("item1_repro", res)

# pairwise: PROD vs single / ens3 (paired daily diff, NW t) on the same phase-averaged calendars
pairs = {}
for pname in ("dev", "hold"):
    for cost in (50, 80):
        a = series[f"PROD_{pname}_c{cost}"][0]
        for other in ("single", "ens3"):
            pairs[f"PROD_minus_{other}_{pname}_c{cost}"] = C.paired(a, series[f"{other}_{pname}_c{cost}"][0])
res["paired_vs_PROD"] = pairs
# top-20 overlap of PROD with the single model on signal dates (weekly calendar, dev and hold)
ov = {}
for pname in ("dev", "hold"):
    a, b = C.PER[pname]
    g0 = int(np.searchsorted(S.cal, np.datetime64(a)))
    g1 = int(np.searchsorted(S.cal, np.datetime64(b or "2026-10-14"), side="right")) - 22
    vals = {"single": [], "ens3": []}
    for g in range(g0, g1, 5):
        cand = S.rows_on(g)
        cand = cand[E[cand]]
        def top(s):
            c2 = cand[np.isfinite(s[cand])]
            return set(c2[np.argsort(-s[c2], kind="stable")[:20]])
        tp = top(SCORES["PROD"])
        for o in vals:
            vals[o].append(len(tp & top(SCORES[o])) / 20)
    ov[pname] = {o: float(np.mean(v)) for o, v in vals.items()}
res["top20_overlap_PROD_with"] = ov
C.log("pairs", C.short(pairs), "overlap", ov)
C.save("item1_repro", res)
np.savez_compressed(f"{OUT}/pa_series_item1.npz",
                    **{f"{k}__{j}": v[i].values for k, v in series.items() for i, j in enumerate(("s", "r", "e", "n"))},
                    **{f"{k}__dates": v[0].index.values.astype("datetime64[D]").astype(str) for k, v in series.items()})
C.log("done")

"""Shared setup for R3_book scripts: sim, PROD, PROD per-date percentile, vol_20, Nifty 1D Rate level, BookSim,
plus phase-averaging helpers for BookSim books against the frozen cached random/EW baselines."""
import sys

import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
sys.path.insert(0, LAB)
sys.path.insert(0, LAB + "/results/R3_book")
import r3common as C  # noqa: E402
from booksim import BookSim, turnover_summary  # noqa: E402

L = C.L


def setup(extra_feat=("vol_20",)):
    C.set_agent("R3_book")
    P, F, fw, S, E = C.load_sim(extra_feat=extra_feat)
    Z = C.load_prod()
    prod = Z["prod"].astype("float64")
    d = P["date"].values
    prank = pd.Series(np.where(E, prod, np.nan)).groupby(d).rank(pct=True).values
    vol20 = F["vol_20"].values.astype("float64") if "vol_20" in F else None
    lv = L.market_series("Nifty 1D Rate Index")["close"].astype("float64")
    lv.index = pd.DatetimeIndex(lv.index)
    cal = pd.DatetimeIndex(S.cal)
    cash_level = lv.reindex(lv.index.union(cal)).ffill().bfill().reindex(cal).values
    BS = BookSim(S, fw, prank=prank, vol20=vol20, cash_level=cash_level)
    return dict(P=P, F=F, fw=fw, S=S, E=E, Z=Z, prod=prod, prank=prank, BS=BS, cash_level=cash_level)


def phase_runs(BS, score, mask, period, run_kw, step=5, seeds=None):
    """Run a BookSim variant on the 5 entry phases; returns list of runs (and random runs if seeds)."""
    a, b = C.PER[period] if isinstance(period, str) else period
    g0 = int(np.searchsorted(BS.S.cal, np.datetime64(a)))
    runs, rruns = [], []
    for k in range(step):
        st = str(BS.S.cal[g0 + k])
        runs.append(BS.run(score, mask, start=st, end_exit=b, **run_kw))
        if seeds:
            rruns.append([BS.run(None, mask, start=st, end_exit=b, random_seed=s_, **run_kw) for s_ in seeds])
    return runs, rruns


def avg_series(runs):
    sds = [pd.Series(r["_daily"], index=pd.DatetimeIndex(r["_dates"])) for r in runs]
    common = sds[0].index
    for x in sds:
        common = common.intersection(x.index)
    return pd.Series(np.mean([x.reindex(common).values for x in sds], 0), index=common)


def frozen_baselines(S, E, period, cost, mask_tag="liq2", step=5):
    """Phase-averaged frozen random (5 seeds) and EW universe daily series from the shared cache."""
    a, b = C.PER[period] if isinstance(period, str) else period
    g0 = int(np.searchsorted(S.cal, np.datetime64(a)))
    rds, eds = [], []
    for k in range(step):
        kw = dict(C.BASE_KW, cost_bps=cost, start=str(S.cal[g0 + k]), end_exit=b)
        _, rbd, rdates = C.random_band(S, E, mask_tag, 20, kw)
        _, ewd, edates = C.ew_band(S, E, mask_tag, 20, kw)
        rds.append(pd.Series(rbd, index=pd.DatetimeIndex(rdates)))
        eds.append(pd.Series(ewd, index=pd.DatetimeIndex(edates)))
    return rds, eds


def pa_stats(sm, rm=None, em=None, h=20):
    """Stats of a phase-averaged series sm, aligned with rm/em on common dates."""
    common = sm.index
    for x in (rm, em):
        if x is not None:
            common = common.intersection(x.index)
    s = sm.reindex(common).values
    yrs = len(common) / 252
    eq = np.cumprod(1 + s)
    out = {"pa_cagr": float(eq[-1] ** (1 / yrs) - 1), "pa_vol": float(s.std() * np.sqrt(252)),
           "pa_sharpe": float(s.mean() / s.std() * np.sqrt(252)),
           "pa_maxdd": float((eq / np.maximum.accumulate(eq) - 1).min()), "n_days": int(len(common))}
    if rm is not None:
        r = rm.reindex(common).values
        out["pa_random_cagr"] = float(np.prod(1 + r) ** (1 / yrs) - 1)
        out["pa_excess_ann"] = float((s - r).mean() * 252)
        out["pa_nw_t"] = L.nw_t(s - r, lag=h)
    if em is not None:
        e = em.reindex(common).values
        out["pa_ew_cagr"] = float(np.prod(1 + e) ** (1 / yrs) - 1)
        out["pa_excess_vs_ew_ann"] = float((s - e).mean() * 252)
        out["pa_vs_ew_nw_t"] = L.nw_t(s - e, lag=h)
    return out


def align_avg(series_list, common):
    return pd.Series(np.mean([x.reindex(common).values for x in series_list], 0), index=common)

"""Shared fast-sim core copied verbatim from s6_invest.py (validated there against L.portfolio_sim)."""
import numpy as np
import pandas as pd

from common import H, HOLD_END

STEP = 5
dates = None  # set by caller: simcore.dates = <datetime64[D] row array>


def picks_run(score, mask, tr, top_k, side="long", start="2023-01-01", end=HOLD_END, seed=None,
              step=STEP, grid=None):
    """grid=None -> lablib behaviour (signal dates = every step-th date ON WHICH THE MASK HAS ROWS);
    grid=<bool row mask> -> signal dates = every step-th trading date of that universe (sparse setups:
    a grid date without events is a cash cohort)."""
    s = np.asarray(score, dtype="float64")
    m = np.asarray(mask, bool) & (~np.isnan(s) if seed is None else True)
    cal = np.unique(dates[m if grid is None else grid])
    cal = cal[(cal >= np.datetime64(start)) & (cal <= np.datetime64(end))]
    sig = cal[::step]
    rng = np.random.default_rng(seed if seed is not None else 0)
    okt = m & np.isfinite(tr)
    ii = np.flatnonzero(okt)
    by = pd.Series(ii).groupby(dates[okt]).apply(np.array)
    coh = []
    for d in sig:
        cand = by.get(d)
        if cand is None or len(cand) == 0:
            coh.append((d, np.array([], int)))
            continue
        if seed is not None:
            pick = rng.choice(cand, size=min(top_k, len(cand)), replace=False)
        else:
            sc = s[cand]
            order = np.argsort(-sc if side == "long" else sc, kind="stable")
            pick = cand[order][:top_k]
        coh.append((d, pick))
    return coh


def metrics(coh, tr, cost_bps, top_k, sizing="ew", lo=None, hi=None, step=STEP):
    cs = [(d, p) for d, p in coh if (lo is None or d >= np.datetime64(lo)) and (hi is None or d <= np.datetime64(hi))]
    if not cs:
        return {}
    S = int(np.ceil(H / step))
    cr = []
    for d, p in cs:
        if len(p) == 0:
            cr.append(0.0)
            continue
        net = tr[p] - cost_bps / 1e4
        cr.append(float(net.mean()) if sizing == "ew" else float(net.sum() / top_k))
    cr = np.array(cr)
    sleeves = np.ones(S)
    eq = []
    for c, r in enumerate(cr):
        sleeves[c % S] *= (1 + r)
        eq.append(sleeves.mean())
    eq = np.array(eq)
    stepret = np.r_[eq[0] - 1, eq[1:] / eq[:-1] - 1]
    cd = np.array([d for d, _ in cs])
    years = max((cd[-1] - cd[0]).astype(int) / 365.25, 1e-9) + H / 252
    allp = np.concatenate([p for _, p in cs if len(p)]) if any(len(p) for _, p in cs) else np.array([], int)
    tnet = tr[allp] - cost_bps / 1e4
    dd = eq / np.maximum.accumulate(eq) - 1
    yr = pd.Series(stepret, index=pd.DatetimeIndex(cd))
    by_year = yr.groupby(yr.index.year).apply(lambda s_: float(np.prod(1 + s_) - 1)).to_dict()
    npk = np.array([len(p) for _, p in cs])
    return {"trades": int(len(allp)), "hit_rate": float((tnet > 0).mean()) if len(tnet) else None,
            "mean_trade_net_bps": 1e4 * float(tnet.mean()) if len(tnet) else None,
            "cagr": float(eq[-1] ** (1 / years) - 1), "total_return": float(eq[-1] - 1),
            "sharpe": float(stepret.mean() / stepret.std() * np.sqrt(252 / step)) if stepret.std() > 0 else None,
            "max_dd": float(dd.min()), "by_year": {int(k): v for k, v in by_year.items()},
            "avg_picks": float(npk.mean()), "share_cohorts_empty": float((npk == 0).mean()),
            "avg_exposure_slot": float(np.minimum(npk, top_k).mean() / top_k)}



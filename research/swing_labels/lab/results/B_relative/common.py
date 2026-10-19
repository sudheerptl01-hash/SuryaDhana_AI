"""Shared helpers for B_relative (relative / cross-sectional labels)."""
import json
import os
import sys

import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
OUT = os.path.join(LAB, "results", "B_relative")
sys.path.insert(0, LAB)
import lablib as L  # noqa: E402

RES = os.path.join(OUT, "results.json")
HS = (5, 10, 20)
DEV_END = "2025-12-31"
HOLD_START, HOLD_END = "2026-01-01", "2026-09-10"
# auditor (E) HIGH issue: sec_rel_mom20 is built on a 2026 sector snapshot -> excluded from features
FEATS = [f for f in L.FEATURES if f != "sec_rel_mom20"]


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        f = float(o)
        return None if f != f else f
    if isinstance(o, float) and o != o:
        return None
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.ndarray):
        return _clean(o.tolist())
    if hasattr(o, "isoformat"):
        return str(o)[:10]
    return o


def save(section, obj):
    d = {}
    if os.path.exists(RES):
        with open(RES) as fh:
            d = json.load(fh)
    d[section] = _clean(obj)
    with open(RES, "w") as fh:
        json.dump(d, fh, indent=1, default=str)
    print(f"[saved] {section}", flush=True)


def load_res():
    if os.path.exists(RES):
        with open(RES) as fh:
            return json.load(fh)
    return {}


def universe(P, F):
    """elig_base restricted to equity ISINs (INE...) -- auditor issue #2 removes ETFs/MF units."""
    return F["elig_base"].values.astype(bool) & P["isin"].str.startswith("INE").values


def xs_rank(x, dates, mask):
    """Per-date percentile rank (0..1] of x among rows in mask with finite x; NaN elsewhere."""
    v = np.where(mask & np.isfinite(x), x, np.nan)
    s = pd.Series(v)
    return s.groupby(dates).rank(pct=True, method="average").values


def tercile_label(pct, q):
    """+1 if pct > 1-q, -1 if pct <= q, 0 middle, NaN where pct NaN."""
    out = np.where(pct > 1 - q, 1.0, np.where(pct <= q, -1.0, 0.0))
    out[np.isnan(pct)] = np.nan
    return out


def dz_label(x, tau=0.005):
    out = np.where(x > tau, 1.0, np.where(x < -tau, -1.0, 0.0))
    out[np.isnan(x)] = np.nan
    return out


class Sim:
    """Fast replica of lablib.portfolio_sim(exit_rule='time') (same selection, RNG, sleeves, stats)
    that also returns cohort returns so long and short legs can be combined. Verified vs lablib."""

    def __init__(self, P, fw, h):
        self.h = h
        self.dates = P["date"].values.astype("datetime64[D]")
        e = fw.at(P["open"].values, 1)
        x = fw.at(P["close"].values, h)
        tr = x / e - 1
        if np.isnan(tr).any():
            last = np.full(len(P), np.nan)
            for k in range(1, h + 1):
                xk = fw.at(P["close"].values, k)
                last = np.where(np.isnan(xk), last, xk)
            fb = last / e - 1
            tr = np.where(np.isnan(tr) & np.isfinite(e), fb, tr)
        self.tr_long = tr
        self._cache = {}

    def groups(self, key, m):
        if key in self._cache:
            return self._cache[key]
        ok = m & np.isfinite(self.tr_long)
        idx = np.flatnonzero(ok)
        d = self.dates[idx]
        order = np.argsort(d, kind="stable")
        idx_s, d_s = idx[order], d[order]
        b = np.flatnonzero(np.r_[True, d_s[1:] != d_s[:-1]])
        e_ = np.r_[b[1:], len(idx_s)]
        g = {d_s[s]: idx_s[s:t] for s, t in zip(b, e_)}
        self._cache[key] = g
        return g

    def cohorts(self, score, mask, key, step=5, top_k=20, side="long", cost_bps=50.0,
                start="2023-01-01", end=HOLD_END, random_seed=None):
        """Return (cohort_dates, cohort_net_returns, picks list). Mirrors lablib.portfolio_sim."""
        sgn = 1.0 if side == "long" else -1.0
        tr = sgn * self.tr_long
        m = np.asarray(mask, bool)
        g = self.groups(key, m)
        if random_seed is None:
            s = np.asarray(score, dtype="float64")
            mm = m & ~np.isnan(s)
        else:
            s, mm = None, m
        cal = np.unique(self.dates[mm])
        cal = cal[cal >= np.datetime64(start)]
        if end is not None:
            cal = cal[cal <= np.datetime64(end)]
        sig = cal[::step]
        rng = np.random.default_rng(random_seed if random_seed is not None else 0)
        cd, cr, picks = [], [], []
        for d in sig:
            cand = g.get(d)
            if cand is not None and random_seed is None:
                cand = cand[~np.isnan(s[cand])]
            if cand is None or len(cand) == 0:
                cd.append(d); cr.append(0.0); picks.append(np.array([], int))
                continue
            if random_seed is not None:
                pick = rng.choice(cand, size=min(top_k, len(cand)), replace=False)
            else:
                sc = s[cand]
                order = np.argsort(-sc if side == "long" else sc)
                pick = cand[order][:top_k]
            cd.append(d)
            cr.append(float(np.mean(tr[pick] - cost_bps / 1e4)))
            picks.append(pick)
        return np.array(cd), np.array(cr), picks


def stats_from_cohorts(cd, cr, h, step, picks=None, tr=None, cost_bps=None):
    """lablib.portfolio_sim statistics from cohort returns (staggered ceil(h/step) sleeves)."""
    S = int(np.ceil(h / step))
    sleeves = np.ones(S)
    eq = []
    for c, r in enumerate(cr):
        sleeves[c % S] *= (1 + r)
        eq.append(sleeves.mean())
    eq = np.array(eq)
    stepret = np.r_[eq[0] - 1, eq[1:] / eq[:-1] - 1]
    years = max((cd[-1] - cd[0]).astype(int) / 365.25, 1e-9) + h / 252
    dd = eq / np.maximum.accumulate(eq) - 1
    yr = pd.Series(stepret, index=pd.DatetimeIndex(cd))
    by_year = yr.groupby(yr.index.year).apply(lambda s_: float(np.prod(1 + s_) - 1)).to_dict()
    sh = float(stepret.mean() / stepret.std() * np.sqrt(252 / step)) if stepret.std() > 0 else np.nan
    rho = float(pd.Series(stepret).autocorr(1)) if len(stepret) > 3 else np.nan
    out = {"cagr": float(eq[-1] ** (1 / years) - 1), "total_return": float(eq[-1] - 1), "sharpe": sh,
           "sharpe_adj": sh / np.sqrt(max(1 + 2 * rho, 1e-6)) if rho == rho else sh, "rho1": rho,
           "max_dd": float(dd.min()), "by_year": {int(k): float(v) for k, v in by_year.items()},
           "n_cohorts": int(len(cr))}
    if picks is not None and tr is not None:
        allp = np.concatenate([p for p in picks if len(p)]) if any(len(p) for p in picks) else np.array([], int)
        tnet = tr[allp] - cost_bps / 1e4
        out.update({"trades": int(len(allp)), "hit_rate": float((tnet > 0).mean()) if len(tnet) else np.nan,
                    "mean_trade_net": float(tnet.mean()) if len(tnet) else np.nan})
    return out

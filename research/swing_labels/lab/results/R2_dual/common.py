"""R2_dual shared helpers: paths, results.json persistence, per-date ranking/residualisation."""
import json
import os
import sys
import fcntl

import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
OUT = os.path.join(LAB, "results", "R2_dual")
sys.path.insert(0, LAB)
import lablib as L  # noqa: E402

RES = os.path.join(OUT, "results.json")
COST = 50.0          # central round-trip cost, bps
STRESS = 80.0        # stress cost, bps


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
    """Merge one section into results.json (file-locked, so parallel stages are safe)."""
    lock = open(RES + ".lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        d = {}
        if os.path.exists(RES):
            with open(RES) as fh:
                d = json.load(fh)
        d[section] = _clean(obj)
        tmp = RES + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(d, fh, indent=1, default=str)
        os.replace(tmp, RES)
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
    print(f"[saved] {section}", flush=True)


def load_res():
    if os.path.exists(RES):
        with open(RES) as fh:
            return json.load(fh)
    return {}


def date_groups(dates, idx):
    """Split row indices idx (any order) into per-date blocks. Returns list of arrays."""
    order = np.argsort(dates[idx], kind="stable")
    ii = idx[order]
    d = dates[ii]
    b = np.flatnonzero(np.r_[True, d[1:] != d[:-1]])
    e = np.r_[b[1:], len(ii)]
    return [ii[s:t] for s, t in zip(b, e)]


def xs_pct(x, dates, mask):
    """Per-date percentile rank (0,1] among mask rows with finite x; NaN elsewhere."""
    v = np.where(mask & np.isfinite(x), x, np.nan)
    return pd.Series(v).groupby(dates).rank(pct=True, method="average").values


def neutral_resid(r, dates, mask, regs, wins=(1, 99), min_n=30):
    """Per-date: winsorise r at 1/99 pct among valid rows, OLS on [1, regs...], return residual.
    NaN where r/regs undefined or date has < min_n names."""
    ok = mask & np.isfinite(r)
    for z in regs:
        ok &= np.isfinite(z)
    out = np.full(len(r), np.nan)
    for ii in date_groups(dates, np.flatnonzero(ok)):
        if len(ii) < min_n:
            continue
        y = r[ii]
        lo, hi = np.percentile(y, wins)
        y = np.clip(y, lo, hi)
        X = np.column_stack([np.ones(len(ii))] + [z[ii] for z in regs])
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        out[ii] = y - X @ coef
    return out


def cls3(pct, q):
    """+1 if pct > 1-q, -1 if pct <= q, else 0; NaN where pct NaN."""
    out = np.where(pct > 1 - q, 1.0, np.where(pct <= q, -1.0, 0.0))
    out[~np.isfinite(pct)] = np.nan
    return out


def regime(F_mds200, F_mm20):
    reg = np.where(F_mds200 > 0, "bull", "bear").astype(object)
    reg = reg + np.where(F_mm20 > 0, "_up20", "_dn20")
    reg[~(np.isfinite(F_mds200) & np.isfinite(F_mm20))] = "na"
    return reg

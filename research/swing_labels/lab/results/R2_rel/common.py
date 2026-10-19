"""R2_rel shared helpers: relative (selection) label architecture on lab v2."""
import fcntl
import json
import os
import sys

import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
OUT = os.path.join(LAB, "results", "R2_rel")
sys.path.insert(0, LAB)
import lablib as L  # noqa: E402

RES = os.path.join(OUT, "results.json")
HS = (10, 15, 20)
NEUTS = ("neu", "neumom", "size", "none")
# label forms derived from the per-date residual percentile `pct`
FORMS = ("C30", "C20", "C33", "T30", "B30", "RANK")
DEV = L.DEV
HOLD = ("2026-01-01", None)


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
    """Merge one section into results.json (file-locked; safe across concurrent scripts)."""
    lock = RES + ".lock"
    with open(lock, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        d = {}
        if os.path.exists(RES):
            with open(RES) as fh:
                d = json.load(fh)
        d[section] = _clean(obj)
        tmp = RES + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(d, fh, indent=1, default=str)
        os.replace(tmp, RES)
        fcntl.flock(lk, fcntl.LOCK_UN)
    print(f"[saved] {section}", flush=True)


def load_res():
    if os.path.exists(RES):
        with open(RES) as fh:
            return json.load(fh)
    return {}


def form_label(pct, form):
    """Map per-date residual percentile (0,1] to a label. NaN stays NaN."""
    pct = np.asarray(pct, dtype="float64")
    nan = np.isnan(pct)
    if form == "RANK":
        out = pct - 0.5
    elif form in ("C30", "C20", "C33"):
        q = {"C30": 0.3, "C20": 0.2, "C33": 1 / 3}[form]
        out = np.where(pct > 1 - q, 1.0, np.where(pct <= q, -1.0, 0.0))
    elif form[0] == "T" and form[1:].isdigit():          # binary top-q% vs rest (T30, T20, T10, T50)
        out = (pct > 1 - int(form[1:]) / 100).astype(float)
    elif form[0] == "B" and form[1:].isdigit():          # binary bottom-q% vs rest (AVOID model)
        out = (pct <= int(form[1:]) / 100).astype(float)
    else:
        raise ValueError(form)
    out = np.asarray(out, dtype="float64")
    out[nan] = np.nan
    return out


def date_groups(dates, idx):
    """Sort idx by date; return (idx_sorted, starts, ends)."""
    order = np.argsort(dates[idx], kind="stable")
    idx = idx[order]
    d = dates[idx]
    b = np.flatnonzero(np.r_[True, d[1:] != d[:-1]])
    e = np.r_[b[1:], len(idx)]
    return idx, b, e


def xs_rank(x, dates, mask):
    v = np.where(mask & np.isfinite(x), x, np.nan)
    return pd.Series(v).groupby(dates).rank(pct=True, method="average").values

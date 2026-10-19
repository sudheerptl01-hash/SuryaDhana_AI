"""Shared helpers for A_barrier (vectorized triple barrier on eligible rows).

Semantics are identical to lablib.barrier_labels (validated in s1_grid.py):
entry = open[t+1]; bars t+1..t+h scanned; stop checked before target on the same
bar; gaps through a barrier fill at that bar's open; time exit at close[t+h]
with a +/- tau dead zone. Label NaN when fw.ok(h) is false.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
OUT = os.path.join(LAB, "results", "A_barrier")
sys.path.insert(0, LAB)
import lablib as L  # noqa: E402

HMAX = 20


def load_base(pcols=None, fcols=None):
    pc = ["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"] + (pcols or [])
    fc = ["atr_pct", "elig_base", "fno_proxy", "mkt_dist_sma200", "mkt_mom20", "log_turn20"] + (fcols or [])
    P = L.load_panel(pc)
    F = L.load_features(list(dict.fromkeys(fc)))
    fw = L.Fwd(P)
    return P, F, fw


class FwdMats:
    """Forward OHLC matrices (rows = selected row indices, cols = k=1..HMAX)."""

    def __init__(self, P, fw, rows, hmax=HMAX):
        self.rows = rows
        n = len(rows)
        self.O = np.empty((n, hmax))
        self.H = np.empty((n, hmax))
        self.Lo = np.empty((n, hmax))
        self.C = np.empty((n, hmax))
        o, h, lo, c = (P[k].values for k in ("open", "high", "low", "close"))
        for k in range(1, hmax + 1):
            self.O[:, k - 1] = fw.at(o, k)[rows]
            self.H[:, k - 1] = fw.at(h, k)[rows]
            self.Lo[:, k - 1] = fw.at(lo, k)[rows]
            self.C[:, k - 1] = fw.at(c, k)[rows]
        self.entry = self.O[:, 0]
        self.ok = {hh: fw.ok(hh)[rows] for hh in (5, 10, 15, 20)}


def barrier(M: FwdMats, up_d, dn_d, h, side="long"):
    """Returns dict(label0, ret, k, touch[0=time,1=pt,-1=sl], valid) on M.rows."""
    e = M.entry
    O, H, Lo, C = M.O[:, :h], M.H[:, :h], M.Lo[:, :h], M.C[:, :h]
    if side == "long":
        tgt, stp = e * (1 + up_d), e * (1 - dn_d)
        gs = O <= stp[:, None]
        hs = ~gs & (Lo <= stp[:, None])
        sa = gs | hs
        gt = ~sa & (O >= tgt[:, None])
        ht = ~sa & ~gt & (H >= tgt[:, None])
        sgn = 1.0
    else:
        tgt, stp = e * (1 - up_d), e * (1 + dn_d)
        gs = O >= stp[:, None]
        hs = ~gs & (H >= stp[:, None])
        sa = gs | hs
        gt = ~sa & (O <= tgt[:, None])
        ht = ~sa & ~gt & (Lo <= tgt[:, None])
        sgn = -1.0
    ev = sa | gt | ht
    has = ev.any(axis=1)
    first = ev.argmax(axis=1)
    r = np.arange(len(e))
    px = np.where(gs[r, first], O[r, first],
                  np.where(hs[r, first], stp,
                           np.where(gt[r, first], O[r, first], tgt)))
    touch = np.where(has, np.where(sa[r, first], -1, 1), 0).astype(np.int8)
    ret = np.where(has, sgn * (px / e - 1), sgn * (C[:, h - 1] / e - 1))
    k = np.where(has, first + 1, h).astype(np.int8)
    valid = M.ok[h] & np.isfinite(e) & (e > 0) & np.isfinite(tgt) & np.isfinite(stp)
    ret = np.where(valid, ret, np.nan)
    lab0 = np.where(touch != 0, touch, np.sign(ret)).astype(float)
    lab0[~valid] = np.nan
    return {"label0": lab0, "ret": ret, "k": k, "touch": touch, "valid": valid}


def tau_label(b, tau_bps):
    tau = tau_bps / 1e4
    r = b["ret"]
    lab = np.where(b["touch"] != 0, b["touch"],
                   np.where(r > tau, 1, np.where(r < -tau, -1, 0))).astype(float)
    lab[~b["valid"]] = np.nan
    return lab


def geom(kind, a, b, h):
    """Multiples of atr_pct for target/stop."""
    if kind == "fix":
        return a, b
    s = np.sqrt(h)
    return a * s, b * s


def save_json(path, obj):
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=1, default=lambda x: float(x) if isinstance(x, (np.floating, np.integer)) else str(x))


def update_results(key, val):
    p = os.path.join(OUT, "results.json")
    d = {}
    if os.path.exists(p):
        with open(p) as fh:
            d = json.load(fh)
    d[key] = val
    save_json(p, d)

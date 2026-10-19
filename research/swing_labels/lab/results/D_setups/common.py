"""Shared helpers for D_setups (setup / event-gated labels + meta-labeling).

Primary label (common to all setups, per round1_roles.md D_setups):
  triple barrier, h=10, entry = open[t+1],
  pt = 1.5 * atr_pct * sqrt(10), sl = 1.0 * atr_pct * sqrt(10)  (long; short mirrored)
  computed with L.barrier_labels(..., tau_bps=50):
     +1 = target touched OR time exit with gross ret > +50 bps
     -1 = stop touched   OR time exit with gross ret < -50 bps
      0 = time exit within +/-50 bps
  NaN where fw.ok(10) is false / no entry.  ret = gross barrier-trade return.
  Meta-label (binary) = 1{label == +1}  == 1{barrier trade beats ~50 bps cost}.

Universe U = elig_base AND ISIN starts with 'INE' (equity shares; ETFs/MF units removed per
E_auditor issue #2).  Sector map is a 2026 snapshot (E_auditor issue #1): sec_rel_mom20 and
F.sector are NOT used as model features; the 'sector leader' setup is measured only to expose
the leak.
"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
OUT = os.path.join(LAB, "results", "D_setups")
sys.path.insert(0, LAB)
import lablib as L  # noqa: E402

RES = os.path.join(OUT, "results.json")
H = 10
PT = 1.5 * np.sqrt(10)
SL = 1.0 * np.sqrt(10)
COST = 50.0
STRESS = 80.0
DEV_END = "2025-12-16"     # last signal date whose t+10 exit is <= 2025-12-31 (computed in s1)
HOLD_START, HOLD_END = "2026-01-01", "2026-09-10"
FEATS_META = [f for f in L.FEATURES if f != "sec_rel_mom20"]  # drop leaky sector feature

LONG_SETUPS = {
    "L1_bo20": "20d breakout: hi20_dist>0 & volz_20>1",
    "L2_bo52": "52w-high breakout: hi52_dist>-0.01 & volz_20>0.5",
    "L3_pullback": "pullback in uptrend: dist_sma200>0 & mom_60>0 & -0.03<dist_sma20<0.01 & rsi_14<50",
    "L4_vcp": "vol-contraction breakout: vol_ratio<0.75 & hi20_dist>0",
    "L5_deliv": "delivery accumulation: deliv_z20>1.5 & intraday>0 & mom_20>0",
    "L6_rslead": "RS leader: xr_mom60>0.9 & xr_mom20>0.7",
    "L7_oversold_up": "oversold in uptrend: rsi_14<30 & dist_sma200>0",
    "L8_seclead_LEAKY": "sector leader: sec_rel_mom20 top decile (per date) & mkt_dist_sma200>0 [uses 2026 sector snapshot]",
    "L8b_mktlead": "index-relative leader (leak-free L8 analogue): rel_mom20 top decile (per date) & mkt_dist_sma200>0",
    "L9_gaphold": "gap-up hold: gap_open>0.02 & range_pos>0.7 & volz_20>1",
}
SHORT_SETUPS = {
    "S1_bd20": "20d breakdown: close < min(low[t-20..t-1]) & volz_20>1",
    "S2_failrally": "failed rally in downtrend: dist_sma200<0 & rsi_14>60 & mom_5<0",
    "S3_rslag": "RS laggard: xr_mom60<0.1 & xr_mom20<0.3",
    "S4_bd52": "52w-low breakdown: lo52_dist<0.01 & volz_20>0.5",
    "S5_gapfail": "gap-down fail: gap_open<-0.02 & range_pos<0.3 & volz_20>1",
}


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
    tmp = RES + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(d, fh, indent=1)
    os.replace(tmp, RES)


def load_res():
    if os.path.exists(RES):
        with open(RES) as fh:
            return json.load(fh)
    return {}


def load_base():
    """Arrays built by s1_build.py (row-aligned with panel)."""
    z = np.load(os.path.join(OUT, "base.npz"), allow_pickle=False)
    return {k: z[k] for k in z.files}


class T:
    def __init__(self):
        self.t0 = time.time()

    def __call__(self, msg):
        print(f"[{time.time() - self.t0:6.1f}s] {msg}", flush=True)

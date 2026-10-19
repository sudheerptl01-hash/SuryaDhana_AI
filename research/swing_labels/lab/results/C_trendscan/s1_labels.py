#!/usr/bin/env python3
"""Stage 1: compute all C_trendscan labels (vectorised, no row loops) and persist to labels.npz.

Entry = open[t+1] (fw.at(open,1)); everything is NaN where the needed window is not valid
(fw.ok(h) false: segment break / span cap / label_block inside window / missing entry).

Families
  TS  trend-scanning (Lopez de Prado): y_0 = 0 (=log open[t+1]-log entry), y_k = log(close[t+k]/entry),
      k=1..L; OLS slope t-value for L=5..20; L* = argmax |t|.  Absolute (TSA) and market-excess (TSX,
      y_k minus Nifty-500 log return over the same rows/dates).
  RA  risk-adjusted fwd return z_h = r_h / (vol_20*sqrt(h)), h=10,20 (r_h = close[t+h]/open[t+1]-1).
  MQ  MFE / MAE over 20 bars after entry (high/low based), plus bars at which they occur.
  FP  first passage of +/- sigma*sqrt(h) barriers within 20 bars (sigma = vol_20), h_width=20 and 10.
  FX  fixed-horizon controls r_5, r_10, r_20.
"""
import time

import numpy as np
import pandas as pd

from common import OUT, L, save, eq_universe

t0 = time.time()
P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["elig_base", "vol_20", "atr_pct"])
fw = L.Fwd(P)
n = len(P)
print("loaded", round(time.time() - t0, 1), n, flush=True)

ent = P["entity"].astype(str).values
pref = pd.Series(ent).str[:3].value_counts().to_dict()
elig = F["elig_base"].values
pref_elig = pd.Series(ent[elig]).str[:3].value_counts().to_dict()
eq = eq_universe(P, F)

o = P["open"].values.astype("float64")
hi = P["high"].values.astype("float64")
lo = P["low"].values.astype("float64")
c = P["close"].values.astype("float64")
entry = fw.at(o, 1)
good_entry = np.isfinite(entry) & (entry > 0)
ok = {h: fw.ok(h) & good_entry for h in (5, 10, 20)}

# market close / open mapped to each row's date
mk = L.market_series("Nifty 500")
cal = pd.DatetimeIndex(np.sort(np.unique(P["date"].values)))
mk = mk.reindex(cal).ffill()
di = pd.DatetimeIndex(P["date"].values)
m_close = mk["close"].reindex(di).values.astype("float64")
m_open = mk["open"].reindex(di).values.astype("float64")
m_entry = fw.at(m_open, 1)

LMAX = 20
LMIN = 5
S2_FLOOR = 1e-6  # residual variance floor (0.1% residual sd) -> caps |t| on locked/linear paths


def trend_scan(get_y):
    """Running OLS sums over k=0..L, vectorised across rows. Returns best t, L*, and t at each L."""
    Sy = np.zeros(n)
    Sxy = np.zeros(n)
    Syy = np.zeros(n)
    best_abs = np.full(n, -1.0)
    best_t = np.full(n, np.nan)
    best_L = np.full(n, np.nan)
    t_at = {}
    for k in range(1, LMAX + 1):
        y = get_y(k)
        Sy += y
        Sxy += k * y
        Syy += y * y
        if k < LMIN:
            continue
        N = k + 1
        Sx = k * (k + 1) / 2.0
        Sxx = k * (k + 1) * (2 * k + 1) / 6.0
        sxx = Sxx - Sx * Sx / N
        sxy = Sxy - Sx * Sy / N
        syy = Syy - Sy * Sy / N
        b = sxy / sxx
        ss = np.maximum(syy - b * sxy, 0.0)
        s2 = np.maximum(ss / (N - 2), S2_FLOOR)
        t = b / np.sqrt(s2 / sxx)
        at = np.abs(t)
        upd = np.isfinite(at) & (at > best_abs)
        best_abs = np.where(upd, at, best_abs)
        best_t = np.where(upd, t, best_t)
        best_L = np.where(upd, k, best_L)
        if k in (5, 10, 20):
            t_at[k] = t
    return best_t, best_L, t_at


closes = {}
for k in range(1, LMAX + 1):
    closes[k] = fw.at(c, k)
mclose_k = {k: fw.at(m_close, k) for k in range(1, LMAX + 1)}

v20 = ok[20]
tsA_t, tsA_L, tsA_tat = trend_scan(lambda k: np.log(closes[k] / entry))
tsX_t, tsX_L, tsX_tat = trend_scan(lambda k: np.log(closes[k] / entry) - np.log(mclose_k[k] / m_entry))
for a in (tsA_t, tsA_L, tsX_t, tsX_L):
    a[~v20] = np.nan
for d in (tsA_tat, tsX_tat):
    for k in d:
        d[k][~v20] = np.nan
# realised return at L* (oracle exit)
idxL = np.where(np.isfinite(tsA_L), tsA_L, 1).astype(int)
cl_stack = np.vstack([closes[k] for k in range(1, LMAX + 1)])
tsA_r = cl_stack[idxL - 1, np.arange(n)] / entry - 1
tsA_r[~v20] = np.nan
idxX = np.where(np.isfinite(tsX_L), tsX_L, 1).astype(int)
tsX_r = cl_stack[idxX - 1, np.arange(n)] / entry - 1
tsX_r[~v20] = np.nan
mret_L = np.vstack([mclose_k[k] for k in range(1, LMAX + 1)])
tsX_rx = tsX_r - (mret_L[idxX - 1, np.arange(n)] / m_entry - 1)
tsX_rx[~v20] = np.nan
del cl_stack, mret_L
print("trend scan done", round(time.time() - t0, 1), flush=True)

# fixed horizon returns (executable)
r = {}
mr = {}
for h in (5, 10, 20):
    rr = closes[h] / entry - 1
    rr[~ok[h]] = np.nan
    r[h] = rr
    mm = mclose_k[h] / m_entry - 1
    mm[~ok[h]] = np.nan
    mr[h] = mm

# MFE / MAE over 20 bars (high/low after entry; bar t+1 range is at/after the open)
mfe = np.full(n, -np.inf)
mae = np.full(n, np.inf)
kmfe = np.zeros(n)
kmae = np.zeros(n)
for k in range(1, LMAX + 1):
    hk = fw.at(hi, k) / entry - 1
    lk = fw.at(lo, k) / entry - 1
    u = hk > mfe
    mfe = np.where(u, hk, mfe)
    kmfe = np.where(u, k, kmfe)
    u = lk < mae
    mae = np.where(u, lk, mae)
    kmae = np.where(u, k, kmae)
for a in (mfe, mae, kmfe, kmae):
    a[~v20] = np.nan
print("mfe/mae done", round(time.time() - t0, 1), flush=True)

# first passage of +/- sigma*sqrt(hw) within 20 bars, sigma = vol_20 (PIT at t)
sig = F["vol_20"].values.astype("float64")
fp = {}
for hw in (20, 10):
    w = sig * np.sqrt(hw)
    U = entry * (1 + w)
    D = entry * (1 - w)
    lab = np.full(n, np.nan)
    kk = np.full(n, np.nan)
    ret = np.full(n, np.nan)
    both = np.zeros(n, bool)
    open_ = v20 & np.isfinite(w) & (w > 0)
    for k in range(1, LMAX + 1):
        ok_, hk, lk, ck = fw.at(o, k), fw.at(hi, k), fw.at(lo, k), closes[k]
        gu = open_ & (ok_ >= U)
        gd = open_ & ~gu & (ok_ <= D)
        rest = open_ & ~gu & ~gd
        hu = rest & (hk >= U)
        hd = rest & (lk <= D)
        amb = hu & hd
        hu1 = hu & ~amb
        hd1 = hd & ~amb
        for m_, px, lb in ((gu, ok_, 1.0), (gd, ok_, -1.0), (hu1, U, 1.0), (hd1, D, -1.0), (amb, ck, 0.0)):
            if m_.any():
                lab[m_] = lb
                kk[m_] = k
                ret[m_] = px[m_] / entry[m_] - 1
        both |= amb
        open_ = open_ & ~(gu | gd | hu | hd)
        if k == LMAX and open_.any():
            lab[open_] = 0.0
            kk[open_] = LMAX
            ret[open_] = ck[open_] / entry[open_] - 1
    lab[~v20] = np.nan
    fp[hw] = (lab, kk, ret, both)
print("first passage done", round(time.time() - t0, 1), flush=True)

f32 = lambda a: np.asarray(a, dtype="float32")  # noqa: E731
np.savez_compressed(
    f"{OUT}/labels.npz",
    eq=eq, v5=ok[5], v10=ok[10], v20=ok[20],
    tsA_t=f32(tsA_t), tsA_L=f32(tsA_L), tsA_r=f32(tsA_r),
    tsA_t5=f32(tsA_tat[5]), tsA_t10=f32(tsA_tat[10]), tsA_t20=f32(tsA_tat[20]),
    tsX_t=f32(tsX_t), tsX_L=f32(tsX_L), tsX_r=f32(tsX_r), tsX_rx=f32(tsX_rx),
    r5=f32(r[5]), r10=f32(r[10]), r20=f32(r[20]), mr5=f32(mr[5]), mr10=f32(mr[10]), mr20=f32(mr[20]),
    mfe=f32(mfe), mae=f32(mae), kmfe=f32(kmfe), kmae=f32(kmae),
    fp20_lab=f32(fp[20][0]), fp20_k=f32(fp[20][1]), fp20_ret=f32(fp[20][2]), fp20_both=fp[20][3],
    fp10_lab=f32(fp[10][0]), fp10_k=f32(fp[10][1]), fp10_ret=f32(fp[10][2]), fp10_both=fp[10][3],
)
m = eq & v20
save("s1_build", {
    "rows": n, "isin_prefix_all": pref, "isin_prefix_elig_base": pref_elig,
    "elig_base_rows": int(elig.sum()), "elig_eq_rows": int(eq.sum()),
    "valid_share_on_eq": {h: float(ok[h][eq].mean()) for h in (5, 10, 20)},
    "tsA_abs_t_quantiles_eq": {q: float(np.nanquantile(np.abs(tsA_t[m]), q)) for q in (.1, .25, .5, .75, .9, .99)},
    "tsA_t_inf_or_floor_hits": int(np.sum(np.abs(tsA_t[m]) > 100)),
    "fp20_ambiguous_share": float(fp[20][3][m].mean()), "fp10_ambiguous_share": float(fp[10][3][m].mean()),
    "seconds": time.time() - t0,
})
print("done", round(time.time() - t0, 1))

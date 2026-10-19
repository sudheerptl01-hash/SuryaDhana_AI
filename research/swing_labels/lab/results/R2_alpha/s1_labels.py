"""Stage 1: the three alpha-source targets on lab v2 (h = 20), NaN where undefined.

U     = elig_base (lab v2: EQ, >=Rs20, >=Rs2cr 20d turnover, seasoned, unlocked, ATR band, INE ISIN)
r20   = open[t+1] -> close[t+20] (adjusted), NaN unless fw.ok(20)                       [L.fwd_return]
XR    = XR_neu: per date over V = U & finite(r20): winsorise r20 at the 1st/99th pct, OLS on
        [1, 0.5*clip(beta_60,0,3)+0.5, vol_20, log_turn20]; residual -> per-date pct rank (0,1].
        Regression target = pct - 0.5. (Identical construction to R2_rel 'neu'; cross-checked.)
BAR   = A2 triple barrier: L.barrier_labels(h=20, pt=3.0*ATR, sl=1.5*ATR, tau=50bp), entry open[t+1],
        stop checked first, gap fills at the open. Binary target 1{BAR=+1}, NaN where invalid.
TSX   = market-excess trend scan (round-1 TSX_T5): y_0 = 0, y_k = log(close[t+k]/open[t+1])
        - log(N500 close[date t+k] / N500 open[date t+1]), k=1..L; OLS slope t-value for L = 5..20
        (residual variance floor 1e-6); L* = argmax |t_L|; label = sign(t*) if |t*| >= 5 else 0.
        NaN unless fw.ok(20) and a valid entry. Multiclass target {-1,0,+1}.
"""
import time

import numpy as np
import pandas as pd

from common import OUT, L, save, date_blocks

t0 = time.time()
P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["elig_base", "elig_liq5", "fno_proxy", "atr_pct", "beta_60", "vol_20", "log_turn20",
                     "mkt_dist_sma200", "mkt_mom20"])
fw = L.Fwd(P)
n = len(P)
U = F["elig_base"].values.astype(bool)
dates = P["date"].values.astype("datetime64[D]")
cal = np.unique(dates)
print("loaded", round(time.time() - t0, 1), flush=True)

# ---------------------------------------------------------------- r20 and market leg
H = 20
r = L.fwd_return(P, fw, H)
V = U & np.isfinite(r)
mk = L.market_series("Nifty 500").reindex(pd.DatetimeIndex(cal)).ffill()
mo, mc = mk["open"].values.astype("float64"), mk["close"].values.astype("float64")
pos = np.searchsorted(cal, dates).astype(float)
p1, ph = fw.at(pos, 1), fw.at(pos, H)
okm = np.isfinite(p1) & np.isfinite(ph) & np.isfinite(r)
m20 = np.full(n, np.nan)
m20[okm] = mc[ph[okm].astype(int)] / mo[p1[okm].astype(int)] - 1

# ---------------------------------------------------------------- XR_neu
beta_s = 0.5 * np.clip(F["beta_60"].values.astype("float64"), 0.0, 3.0) + 0.5
vol = F["vol_20"].values.astype("float64")
lt = F["log_turn20"].values.astype("float64")
okx = V & np.isfinite(beta_s) & np.isfinite(vol) & np.isfinite(lt)
idx, b, e = date_blocks(dates, np.flatnonzero(okx))
res = np.full(n, np.nan)
ew = np.full(n, np.nan)
r2s = []
for s_, t_ in zip(b, e):
    ii = idx[s_:t_]
    if len(ii) < 30:
        continue
    y = r[ii]
    lo, hi = np.percentile(y, [1, 99])
    yw = np.clip(y, lo, hi)
    ew[ii] = y.mean()
    X = np.column_stack([np.ones(len(ii)), beta_s[ii], vol[ii], lt[ii]])
    coef, *_ = np.linalg.lstsq(X, yw, rcond=None)
    rr = yw - X @ coef
    res[ii] = rr
    r2s.append(1 - rr.var() / yw.var() if yw.var() > 0 else np.nan)
pct = pd.Series(res).groupby(dates).rank(pct=True, method="average").values
print("XR_neu done", round(time.time() - t0, 1), "mean xs R2", round(float(np.nanmean(r2s)), 4), flush=True)

# ---------------------------------------------------------------- A2 barrier
bl = L.barrier_labels(P, F, fw, h=H, pt=3.0, sl=1.5, tau_bps=50)
bar = bl["label"]
bar_ret = bl["ret"]
bar_k = bl["k"]
touch = bl["touch"]
bar_touch = np.where(touch == "pt", 1.0, np.where(touch == "sl", -1.0, np.where(touch == "time", 0.0, np.nan)))
bar_touch[~bl["valid"]] = np.nan
del bl, touch
print("barrier done", round(time.time() - t0, 1), flush=True)

# ---------------------------------------------------------------- TSX trend scan (vectorised)
o = P["open"].values.astype("float64")
c = P["close"].values.astype("float64")
entry = fw.at(o, 1)
good = np.isfinite(entry) & (entry > 0)
di = pd.DatetimeIndex(P["date"].values)
m_close = mk["close"].reindex(di).values.astype("float64")
m_open = mk["open"].reindex(di).values.astype("float64")
m_entry = fw.at(m_open, 1)
LMIN, LMAX, FLOOR = 5, 20, 1e-6
Sy, Sxy, Syy = np.zeros(n), np.zeros(n), np.zeros(n)
best_abs = np.full(n, -1.0)
best_t = np.full(n, np.nan)
best_L = np.full(n, np.nan)
with np.errstate(divide="ignore", invalid="ignore"):
    for k in range(1, LMAX + 1):
        y = np.log(fw.at(c, k) / entry) - np.log(fw.at(m_close, k) / m_entry)
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
        bb = sxy / sxx
        ss = np.maximum(syy - bb * sxy, 0.0)
        s2 = np.maximum(ss / (N - 2), FLOOR)
        t = bb / np.sqrt(s2 / sxx)
        at = np.abs(t)
        upd = np.isfinite(at) & (at > best_abs)
        best_abs = np.where(upd, at, best_abs)
        best_t = np.where(upd, t, best_t)
        best_L = np.where(upd, k, best_L)
v20 = fw.ok(H) & good
best_t[~v20] = np.nan
best_L[~v20] = np.nan
tsx = np.where(best_t >= 5, 1.0, np.where(best_t <= -5, -1.0, 0.0))
tsx[~np.isfinite(best_t)] = np.nan
print("trend scan done", round(time.time() - t0, 1), flush=True)

f32 = lambda a: np.asarray(a, dtype="float32")  # noqa: E731
np.savez_compressed(f"{OUT}/labels.npz", U=U, V=V, liq5=F["elig_liq5"].values.astype(bool),
                    fno=F["fno_proxy"].values.astype(bool),
                    r20=f32(r), m20=f32(m20), ew20=f32(ew), res=f32(res), pct=f32(pct),
                    bar=f32(bar), bar_ret=f32(bar_ret), bar_k=f32(bar_k), bar_touch=f32(bar_touch),
                    tsx_t=f32(best_t), tsx_L=f32(best_L), tsx=f32(tsx))

# ---------------------------------------------------------------- cross-checks vs other R2 agents
diag = {"U_rows": int(U.sum()), "V_rows": int(V.sum()), "V_share_of_U": float(V.sum() / U.sum()),
        "xr_mean_xs_R2": float(np.nanmean(r2s)), "xr_defined_on_V": float(np.isfinite(pct[V]).mean())}
try:
    z = np.load(f"{L.LAB}/results/R2_rel/labels_h20.npz")
    o_pct = z["pct_neu"].astype("float64")
    mm = np.isfinite(o_pct) & np.isfinite(pct)
    diag["xcheck_R2_rel_pct_neu"] = {"both_defined": int(mm.sum()),
                                     "only_mine": int((np.isfinite(pct) & ~np.isfinite(o_pct)).sum()),
                                     "only_theirs": int((~np.isfinite(pct) & np.isfinite(o_pct)).sum()),
                                     "max_abs_diff": float(np.abs(o_pct[mm] - pct[mm]).max()),
                                     "corr": float(np.corrcoef(o_pct[mm], pct[mm])[0, 1])}
except Exception as ex:  # noqa: BLE001
    diag["xcheck_R2_rel_pct_neu"] = str(ex)
try:
    z = np.load(f"{L.LAB}/results/R2_dual/labels_h20.npz")
    ob = z["BAR"].astype("float64")
    mm = np.isfinite(ob) & np.isfinite(bar)
    diag["xcheck_R2_dual_BAR"] = {"both_defined": int(mm.sum()),
                                  "nan_pattern_mismatch": int((np.isfinite(ob) != np.isfinite(bar)).sum()),
                                  "agreement": float((ob[mm] == bar[mm]).mean())}
except Exception as ex:  # noqa: BLE001
    diag["xcheck_R2_dual_BAR"] = str(ex)
for nm, y in (("BAR", bar), ("TSX", tsx)):
    x = y[U]
    x = x[np.isfinite(x)]
    diag[f"{nm}_shares_on_U"] = {"n": int(len(x)), "+1": float((x == 1).mean()), "0": float((x == 0).mean()),
                                 "-1": float((x == -1).mean())}
x = bar_touch[U]
x = x[np.isfinite(x)]
diag["BAR_exit_mix_on_U"] = {"target": float((x == 1).mean()), "stop": float((x == -1).mean()),
                             "time": float((x == 0).mean())}
diag["TSX_Lstar_hist_on_U"] = {int(k): float(v) for k, v in
                               pd.Series(best_L[U & np.isfinite(best_L)]).value_counts(normalize=True)
                               .sort_index().items()}
print(diag, flush=True)
save("s1_labels", diag)
print("total", round(time.time() - t0, 1))

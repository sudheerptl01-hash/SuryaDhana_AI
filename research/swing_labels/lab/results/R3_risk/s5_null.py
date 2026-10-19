"""R3_risk item 4 cross-check: persistence-matched null books.
Null score = sqrt(w)*entity constant + sqrt(1-w)*AR(1)(rho) within segment, (w, rho) fitted to PROD's own
within-entity rank autocorrelation at lags 5 and 250 (devil s10 method, refitted on PROD). Each draw ->
phase-averaged contiguous book (2023-01 -> 2026-10, 50 bps) excess vs the same 5-seed random, and its
per-date rank IC vs the realised label. Rules evaluated in rolling 24-month windows (starts every 21 days):
H0 = the null as is (persistent-tilt luck included); H1a/H1b = null + planning drift (+5%/yr) and IC shift."""
import sys

import numpy as np
import pandas as pd
from scipy.signal import lfilter

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
sys.path.insert(0, LAB)
import r3common as C  # noqa: E402

OUT = C.set_agent("R3_risk")
P, F, fw, S, E = C.load_sim()
Z = C.load_prod()
prod, pct = Z["prod"], Z["pct"]
del Z
H = 20
CONTIG = ("2023-01-01", "2026-10-14")
NDRAW = 100
kb = C.load_res()["item4_kill_bootstrap"]
IC_H1A, IC_H1B = kb["ic_target_H1a"], kb["ic_target_H1b"]

# ---- PROD rank autocorrelation (within entity segment)
ac = {}
for k in (1, 5, 20, 60, 250):
    lagged = fw.at(prod, -k)
    ok = np.isfinite(prod) & np.isfinite(lagged)
    ac[k] = float(np.corrcoef(prod[ok], lagged[ok])[0, 1])
w = max(min(ac[250], 0.9), 0.0)
rho = ((ac[5] - w) / (1 - w)) ** (1 / 5)
C.log("PROD rank autocorr", C.short(ac), "w", round(w, 4), "rho", round(rho, 4))

# ---- IC machinery on the same row set as the real IC (elig_base, finite PROD, finite label)
d = P["date"].values.astype("datetime64[D]")
cal = np.unique(d)
didx = np.searchsorted(cal, d)
m = E & np.isfinite(prod) & np.isfinite(pct)
gi = didx[m]
NG = len(cal)
cnt = np.bincount(gi, minlength=NG).astype(float)


def per_date_rank(v):
    o = np.lexsort((v, gi))
    first = np.r_[0, np.cumsum(cnt.astype(int))[:-1]]
    rk = np.empty(len(v))
    rk[o] = np.arange(len(v)) - first[gi[o]] + 1
    return rk


ry = per_date_rank(pct[m])
sy = np.bincount(gi, ry, NG)
syy = np.bincount(gi, ry * ry, NG)


def ic_of(score_m):
    rx = per_date_rank(score_m)
    sx = np.bincount(gi, rx, NG)
    sxx = np.bincount(gi, rx * rx, NG)
    sxy = np.bincount(gi, rx * ry, NG)
    with np.errstate(invalid="ignore", divide="ignore"):
        cov = sxy - sx * sy / cnt
        ic = cov / np.sqrt((sxx - sx ** 2 / cnt) * (syy - sy ** 2 / cnt))
    ic[cnt < 30] = np.nan
    return ic


ic_real = ic_of(prod[m])
icz = np.load(f"{OUT}/ic_series.npz")
chk = pd.Series(icz["ic"], index=pd.DatetimeIndex(icz["dates"]))
cr = pd.Series(ic_real, index=pd.DatetimeIndex(cal)).reindex(chk.index)
C.log("IC machinery check vs s3 (max abs diff)", float(np.nanmax(np.abs(cr.values - chk.values))))

# ---- null draws
n = S.n
start = fw.start
pos = np.arange(n) - start
ent_codes = pd.factorize(P["entity"].values)[0]
del P
draws_ex, draws_ic, summ = [], [], []
ex_dates = None
for k in range(NDRAW):
    rng = np.random.default_rng(5000 + k)
    e = rng.standard_normal(n)
    y = lfilter([1.0], [1.0, -rho], e)
    prev = np.where(start > 0, y[np.maximum(start - 1, 0)], 0.0)
    ar = (y - rho ** (pos + 1) * prev) * np.sqrt(1 - rho ** 2)
    const = rng.standard_normal(ent_codes.max() + 1)[ent_codes]
    zs = np.where(E, np.sqrt(w) * const + np.sqrt(1 - w) * ar, np.nan)
    pa, sm, rm, _ = C.phase_avg(S, zs, E, "liq2", H, C.BASE_KW, CONTIG)
    exs = (sm - rm)
    ex_dates = exs.index if ex_dates is None else ex_dates
    draws_ex.append(exs.reindex(ex_dates).values)
    icn = pd.Series(ic_of(zs[m]), index=pd.DatetimeIndex(cal)).reindex(ex_dates).values
    draws_ic.append(icn)
    summ.append((pa["pa_excess_ann"], pa["pa_nw_t"], float(np.nanmean(icn))))
    if k % 20 == 19:
        C.log("draw", k + 1, "last", C.short(summ[-1]))
DX = np.vstack(draws_ex)
DI = np.vstack(draws_ic)
np.savez(f"{OUT}/null_books.npz", ex=DX, ic=DI, dates=ex_dates.values.astype("datetime64[D]").astype(str))
# ---- rules on rolling 24-month windows
L_ = 504
CHK = np.arange(5, L_ + 1, 5)


def rule_matrix(x, icp):
    nn = x.shape[0]
    cs = np.c_[np.zeros(nn), np.cumsum(x, 1)]
    ci = np.c_[np.zeros(nn), np.cumsum(np.nan_to_num(icp, nan=0.0), 1)]
    cc = np.c_[np.zeros(nn), np.cumsum(np.isfinite(icp), 1)]
    T = CHK
    k1 = np.where(T >= 126, (cs[:, T] - cs[:, np.maximum(T - 126, 0)]) < -0.05, False)
    k3 = np.where(T >= 252, (cs[:, T] - cs[:, np.maximum(T - 252, 0)]) < 0.0, False)
    te = T - 20
    num = ci[:, np.maximum(te, 0)] - ci[:, np.maximum(te - 63, 0)]
    den = cc[:, np.maximum(te, 0)] - cc[:, np.maximum(te - 63, 0)]
    with np.errstate(invalid="ignore", divide="ignore"):
        k2 = np.where((te >= 63) & (den >= 50), num / den < 0.02, False)
    return {"K1": k1, "K2": k2, "K3": k3, "C1_review": k1 | k2 | k3, "C2_kill": k3 & k2, "C3_kill_fast": k1 & k2}


starts = np.arange(0, DX.shape[1] - L_ + 1, 21)
WX = np.concatenate([DX[:, s:s + L_] for s in starts], 0)
WI = np.concatenate([DI[:, s:s + L_] for s in starts], 0)
out = {"autocorr_prod_rank": ac, "w": w, "rho": rho, "n_draws": NDRAW, "n_windows_per_draw": int(len(starts)),
       "null_excess_ann_mean": float(np.mean([s[0] for s in summ])), "null_excess_ann_sd": float(np.std([s[0] for s in summ], ddof=1)),
       "null_excess_ann_p95": float(np.percentile([s[0] for s in summ], 95)),
       "null_nw_t_mean": float(np.mean([s[1] for s in summ])), "null_nw_t_sd": float(np.std([s[1] for s in summ], ddof=1)),
       "null_ic_mean": float(np.mean([s[2] for s in summ])), "null_ic_sd_of_draw_means": float(np.std([s[2] for s in summ], ddof=1)),
       "null_tracking_error_daily_ann": float(np.nanmean(np.nanstd(DX, 1)) * np.sqrt(252)),
       "null_ic_daily_sd": float(np.nanmean(np.nanstd(DI, 1)))}
zz = np.load(f"{OUT}/pa_series.npz")
mod_ex = zz["contig_c50_book"] - zz["contig_c50_rand"]
out["model_tracking_error_contig"] = float(mod_ex.std() * np.sqrt(252))
out["model_ic_daily_sd_contig"] = float(np.nanstd(icz["ic"]))
for hname, (te_, ti_) in {"H0": (0.0, 0.0), "H1a": (0.05, IC_H1A), "H1b": (0.05, IC_H1B)}.items():
    R = rule_matrix(WX + te_ / 252, WI + ti_)
    res = {}
    for k, M in R.items():
        anyf = M.any(1)
        ff = np.where(anyf, CHK[np.argmax(M, 1)], np.inf)
        fired = np.isfinite(ff)
        res[k] = {"p_fire_12m": float((ff <= 252).mean()), "p_fire_24m": float((ff <= 504).mean()),
                  "median_first_fire_days": float(np.median(ff[fired])) if fired.any() else None}
    out[hname] = res
    C.log("null", hname, {k: (round(v["p_fire_24m"], 3), v["median_first_fire_days"]) for k, v in res.items()})
C.log("null summary", C.short({k: v for k, v in out.items() if not isinstance(v, dict)}))
C.save("item4_kill_null_books", out)
C.log("done")

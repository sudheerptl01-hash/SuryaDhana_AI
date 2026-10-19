"""R3_verify_R3_risk v1: independent re-computation of the book series and the exposure policies.
- base phase-averaged PROD book / random / EW via the shared tool C.phase_avg (validated, cached baselines)
- my OWN sleeve simulator (forward-fill on a day grid, written from scratch, not a copy of expo_sim/L.Sim)
  validated against C.phase_avg, then X80 / X60 / G50 on PROD (dev, hold) and X100 / G50 on the EW book (PRE)
- per-phase (single-phase, live-like) excess series for the dispersion check
Saves everything to v1_series.npz + v1_out.json in this folder."""
import json
import sys
import time

import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
OUT = LAB + "/results/R3_verify_R3_risk"
sys.path.insert(0, LAB)
import r3common as C  # noqa: E402
import lablib as L  # noqa: E402

T0 = time.time()


def log(*a):
    print(f"[{time.time() - T0:6.1f}s]", *a, flush=True)


P, F, fw, S, E = C.load_sim(extra_feat=("breadth50",))
prod = C.load_prod()["prod"]
cal = S.cal
NC = len(cal)
didx = S.didx
# per-date breadth (median over rows, a different reduction than R3_risk's .first())
b50 = pd.Series(F["breadth50"].values.astype("float64")).groupby(didx).median().reindex(range(NC)).values
b50_first = pd.Series(F["breadth50"].values.astype("float64")).groupby(didx).first().reindex(range(NC)).values
log("breadth50 median==first on all dates:", bool(np.allclose(np.nan_to_num(b50, nan=-1), np.nan_to_num(b50_first, nan=-1))))
cash_lvl = L.market_series("Nifty 1D Rate Index")["close"].astype("float64")
log("cash index first date", str(cash_lvl.index[0])[:10], "n", len(cash_lvl))
cash_lvl_cal = cash_lvl.reindex(pd.DatetimeIndex(cal)).ffill().bfill().values

# rows by date in original row order
order = np.argsort(didx, kind="stable")
bnd = np.searchsorted(didx[order], np.arange(NC + 1))
o_, c_ = S.o, S.c
end_ = fw.end
lbc = fw.lb_cs
N = S.n


def mysim(score, start, end_exit, xg=None, cash=None, cost_bps=50.0, equal=False, top_k=20, h=20, step=5):
    g0 = int(np.searchsorted(cal, np.datetime64(start)))
    g_end = NC - 1 if end_exit is None else int(np.searchsorted(cal, np.datetime64(end_exit), side="right")) - 1
    sigs = np.arange(g0, g_end - h - 1 + 1, step)
    NS, per = 4, 20
    D0, D1 = g0, min(g_end, int(sigs[-1]) + per)
    nd = D1 - D0 + 1
    eq = np.ones((NS, nd))
    last = np.zeros(NS, dtype=int)
    cst = cost_bps / 1e4
    xs = []
    for j, g in enumerate(sigs):
        g = int(g)
        s = j % NS
        gn = min(g + per, D1)
        E0 = eq[s, g - D0]
        x = 1.0 if xg is None else float(xg(g))
        xs.append(x)
        nday = gn - g
        grow = np.ones(nday) if cash is None else cash[g + 1:gn + 1] / cash[g]
        rows = order[bnd[g]:bnd[g + 1]]
        rows = rows[E[rows] & np.isfinite(score[rows])]
        if equal:
            pick = rows
        else:
            pick = rows[np.argsort(-score[rows], kind="stable")[:top_k]]
        if len(pick) == 0 or nday == 0:
            eq[s, g - D0 + 1:gn - D0 + 1] = E0 * grow
            last[s] = gn - D0
            continue
        kk = np.arange(1, h + 1)
        R = pick[:, None] + kk[None, :]
        Rc = np.minimum(R, N - 1)
        val = (R <= end_[pick][:, None]) & (lbc[Rc] == lbc[pick][:, None]) & (didx[Rc] <= gn)
        val = np.logical_and.accumulate(val, axis=1)
        ent = o_[Rc[:, 0]]
        ok = val[:, 0] & np.isfinite(ent) & (ent > 0)
        pick, R, Rc, val, ent = pick[ok], R[ok], Rc[ok], val[ok], ent[ok]
        npk = len(pick)
        if npk == 0:
            eq[s, g - D0 + 1:gn - D0 + 1] = E0 * grow
            last[s] = gn - D0
            continue
        # value grid: column = day offset (day g+1 -> col 0); place close/entry on each valid bar's day, ffill
        M = np.full((npk, nday), np.nan)
        pp, kq = np.nonzero(val)
        col = didx[Rc[pp, kq]] - (g + 1)
        M[pp, col] = c_[Rc[pp, kq]] / ent[pp]
        # forward fill along days
        has = np.isfinite(M)
        idxf = np.where(has, np.arange(nday)[None, :], -1)
        idxf = np.maximum.accumulate(idxf, axis=1)
        Mf = np.where(idxf >= 0, np.take_along_axis(np.nan_to_num(M, nan=0.0), np.maximum(idxf, 0), axis=1), np.nan)
        nb = val.sum(1)
        exit_col = didx[Rc[np.arange(npk), nb - 1]] - (g + 1)
        valm = np.where(np.isfinite(Mf), Mf * (1 - cst / 2), 1.0)
        valm = np.where(np.arange(nday)[None, :] >= exit_col[:, None], valm * (1 - cst / 2), valm)
        w = (1.0 / npk if equal else 1.0 / top_k) * x
        cf = max(0.0, 1 - w * npk)
        eq[s, g - D0 + 1:gn - D0 + 1] = E0 * (cf * grow + w * valm.sum(0))
        last[s] = gn - D0
    for s in range(NS):
        if 0 < last[s] < nd - 1:
            eq[s, last[s] + 1:] = eq[s, last[s]]
    e = eq.mean(0)
    r = np.r_[0.0, e[1:] / e[:-1] - 1]
    return pd.Series(r, index=pd.DatetimeIndex(cal[D0:D1 + 1])), np.array(xs)


def pavg(score, period, **kw):
    a, b = period
    g0 = int(np.searchsorted(cal, np.datetime64(a)))
    ss, xs0 = [], None
    for k in range(5):
        sr, xs = mysim(score, str(cal[g0 + k]), b, **kw)
        ss.append(sr)
        if k == 0:
            xs0 = xs
    com = ss[0].index
    for s_ in ss[1:]:
        com = com.intersection(s_.index)
    return pd.Series(np.mean([s_.reindex(com).values for s_ in ss], 0), index=com), xs0


def stats(r):
    eqv = np.cumprod(1 + r.values)
    yrs = len(r) / 252
    return {"cagr": float(eqv[-1] ** (1 / yrs) - 1), "vol": float(r.std() * np.sqrt(252)),
            "sharpe": float(r.mean() / r.std() * np.sqrt(252)), "maxdd": float((eqv / np.maximum.accumulate(eqv) - 1).min())}


def nwt(d, lag=20):
    d = np.asarray(d, float)
    n = len(d)
    u = d - d.mean()
    v = u @ u / n
    for k in range(1, lag + 1):
        v += 2 * (1 - k / (lag + 1)) * (u[k:] @ u[:-k]) / n
    return float(d.mean() / np.sqrt(v / n))


def paired(a, b):
    c = a.index.intersection(b.index)
    d = a.reindex(c).values - b.reindex(c).values
    return {"diff_ann": float(d.mean() * 252), "nw_t": nwt(d)}


out = {}
ser = {}
PER = {"dev": ("2023-01-01", "2025-12-31"), "hold": ("2026-01-01", None), "contig": ("2023-01-01", "2026-10-14")}
# ---- shared-tool base series (cached random / EW)
for name, per in PER.items():
    pa, sm, rm, em = C.phase_avg(S, prod, E, "liq2", 20, C.BASE_KW, per if name != "dev" else "dev", with_ew=True)
    out[f"pa_{name}"] = {k: v for k, v in pa.items() if not isinstance(v, list)}
    ser[f"{name}_book"], ser[f"{name}_rand"], ser[f"{name}_ew"] = sm, rm, em
    log(name, C.short(out[f"pa_{name}"]))

# ---- per-phase (single-phase, live-like) excess series, dev and contig
g0d = int(np.searchsorted(cal, np.datetime64("2023-01-01")))
for name, per in (("dev", PER["dev"]), ("contig", PER["contig"])):
    for k in range(5):
        kw = dict(C.BASE_KW, start=str(cal[g0d + k]), end_exit=per[1])
        res, sd, rbd, dts = C.compare(S, prod, E, "liq2", 20, kw)
        ser[f"{name}_phase{k}_ex"] = pd.Series(sd - rbd[:len(sd)], index=pd.DatetimeIndex(dts))
        ser[f"{name}_phase{k}_book"] = pd.Series(sd, index=pd.DatetimeIndex(dts))
log("per-phase series done")

# ---- my own simulator: validate X100 (idle cash 0%) against C.phase_avg book
for name in ("dev", "hold"):
    mine, _ = pavg(prod, PER[name])
    ref = ser[f"{name}_book"]
    dif = np.abs(mine.reindex(ref.index).values - ref.values)
    out[f"mysim_validation_{name}"] = {"max_abs_daily_diff": float(np.nanmax(dif)), "n_common": int(len(ref)),
                                       "n_mine": int(len(mine)), "cagr_mine": stats(mine)["cagr"],
                                       "cagr_ref": stats(ref)["cagr"]}
    log("validation", name, out[f"mysim_validation_{name}"])


def gov(g):
    return 0.5 if (np.isfinite(b50[g]) and b50[g] < 0.5) else 1.0


POL = {"X100": dict(), "X80": dict(xg=lambda g: 0.8, cash=cash_lvl_cal), "X60": dict(xg=lambda g: 0.6, cash=cash_lvl_cal),
       "G50": dict(xg=gov, cash=cash_lvl_cal)}
expo = {}
for name in ("dev", "hold"):
    base = None
    for pol, kw in POL.items():
        sm, xs0 = pavg(prod, PER[name], **kw)
        st = stats(sm)
        if pol == "X100":
            base = sm
        else:
            st["paired_vs_X100"] = paired(sm, base)
            st["maxdd_change"] = st["maxdd"] - stats(base)["maxdd"]
        if pol == "G50":
            st["share_risk_off_phase0"] = float(np.mean(xs0 < 1))
            st["switches_per_year_phase0"] = float(np.sum(np.diff(xs0) != 0) / (len(sm) / 252))
        cs = pd.Series(cash_lvl_cal, index=pd.DatetimeIndex(cal)).pct_change().reindex(sm.index).fillna(0.0)
        st["sharpe_vs_cash"] = float((sm - cs).mean() / (sm - cs).std() * np.sqrt(252))
        expo[f"PROD_{name}_{pol}"] = st
        ser[f"PROD_{name}_{pol}"] = sm
        log("PROD", name, pol, C.short(st))
# EW book PRE (2021-09..2022-12): X100 vs G50
ones = np.ones(N)
pre = ("2021-09-01", "2022-12-31")
bx, _ = pavg(ones, pre, equal=True)
bg, xs0 = pavg(ones, pre, equal=True, xg=gov, cash=cash_lvl_cal)
expo["EW_pre_X100"] = stats(bx)
expo["EW_pre_G50"] = {**stats(bg), "paired_vs_X100": paired(bg, bx),
                      "switches_per_year_phase0": float(np.sum(np.diff(xs0) != 0) / (len(bg) / 252)),
                      "share_risk_off_phase0": float(np.mean(xs0 < 1))}
log("EW pre", C.short(expo["EW_pre_X100"]), C.short(expo["EW_pre_G50"]))
out["expo"] = expo
# governor attribution inside the book's worst-DD window
g50, x100 = ser["PROD_dev_G50"], ser["PROD_dev_X100"]
dfx = g50 - x100.reindex(g50.index)
inw = (dfx.index >= "2024-12-16") & (dfx.index <= "2025-03-03")
out["gov_attr"] = {"in_window": float(dfx[inw].sum()), "rest": float(dfx[~inw].sum()), "total": float(dfx.sum())}
log("gov attr", out["gov_attr"])

np.savez(f"{OUT}/v1_series.npz", **{k: v.values for k, v in ser.items()},
         **{k + "_dates": v.index.values.astype("datetime64[D]").astype(str) for k, v in ser.items()})
with open(f"{OUT}/v1_out.json", "w") as fh:
    json.dump(C._clean(out), fh, indent=1)
log("done")

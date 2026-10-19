"""Verifier checks 2 (own code): capacity (own ADV20 + sqrt impact), crossings vs Nifty 500 / EW; overnight gap of
exits; rejected add-ons E2w/E2d/E3/S1 vs E0 (and E2/E3 vs X1); tax illustration on the contiguous book."""
import json
import sys
import time

import numpy as np
import pandas as pd

VD = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab/results/R3_verify_R3_book"
sys.path.insert(0, VD)
from vsim import (LAB, L, Data, phase_series, seeds_mean, pavg, common_of, cagr, maxdd, my_nw_t)  # noqa: E402

T0 = time.time()


def log(*a):
    print(f"[{time.time() - T0:7.1f}s]", *a, flush=True)


D = Data(extra_panel=("turnover",), extra_feat=("vol_20", "elig_liq5"))
E = D.E
prod = np.load(f"{LAB}/results/_lead/prod_h20.npz")["prod"].astype(float)
cal = pd.DatetimeIndex(D.cal)
lv1 = L.market_series("Nifty 1D Rate Index")["close"].astype(float)
lv1.index = pd.DatetimeIndex(lv1.index)
cash_lv = lv1.reindex(lv1.index.union(cal)).ffill().bfill().reindex(cal).values
n5 = L.market_series("Nifty 500")["close"].astype(float)
n5.index = pd.DatetimeIndex(n5.index)
PERS = {"dev": ("2023-01-01", "2025-12-31"), "hold": ("2026-01-01", None)}
own1 = {p: np.load(f"{VD}/own_series_{p}.npz") for p in PERS}


def own(per, key):
    z = own1[per]
    return pd.Series(z[key], index=pd.DatetimeIndex(z["dates"]))


def pdiff(a, b):
    c = a.index.intersection(b.index)
    d = a.reindex(c).values - b.reindex(c).values
    return {"diff_ann": float(d.mean() * 252), "nw_t": my_nw_t(d, 20), "n": int(len(c))}


def n500_cagr(common):
    lv = n5.reindex(n5.index.union(common)).ffill().reindex(common)
    return cagr(lv.pct_change().fillna(0.0).values)


out = {}
# ------------------------------------------------------------------ 1. capacity
turn = D.P["turnover"].values.astype(float)
adv = pd.Series(turn).groupby(D.segid).rolling(20, min_periods=1).median().reset_index(level=0, drop=True) \
    .sort_index().values
vol = D.F["vol_20"].values.astype(float)
log("ADV ready: median over elig rows (cr)", float(np.nanmedian(adv[E]) / 1e7), "max (cr)", float(np.nanmax(adv[E]) / 1e7))
AUM = {"1cr": 1e7, "5cr": 5e7, "20cr": 2e8, "50cr": 5e8, "100cr": 1e9}
cap = {"refs": {}, "a_liq2_Y1": {}, "b_liq2_cap5_Y1": {}}
for per, (a, b) in PERS.items():
    cm = own(per, "E0").index
    cap["refs"][per] = {"ew_cagr_own": cagr(own(per, "EW").values), "nifty500_cagr_own": n500_cagr(cm)}
    for an, A in AUM.items():
        Q = A / 80.0
        imp = np.minimum(1.0 * vol * np.sqrt(Q / adv), 0.10)
        imp = np.where(np.isfinite(imp), imp, 0.10)
        sl, _ = phase_series(D, a, b, score=prod, cost_rt=0.005 + 2 * imp, cash_lv=cash_lv)
        s = pavg(sl)
        cap["a_liq2_Y1"][f"{an}_{per}"] = {"cagr": cagr(s.values), "maxdd": maxdd(s.values)}
        if an in ("20cr", "50cr", "100cr"):
            fill = np.minimum(1.0, 0.05 * adv / Q)
            fill = np.where(np.isfinite(fill), fill, 0.0)
            imp2 = np.minimum(1.0 * vol * np.sqrt(Q * fill / adv), 0.10)
            imp2 = np.where(np.isfinite(imp2), imp2, 0.10)
            sl2, _ = phase_series(D, a, b, score=prod, cost_rt=0.005 + 2 * imp2, cash_lv=cash_lv, fill=fill)
            cap["b_liq2_cap5_Y1"][f"{an}_{per}"] = {"cagr": cagr(pavg(sl2).values)}
        if an == "20cr" and per == "dev":
            rl = seeds_mean(D, a, b, cost_rt=0.005 + 2 * imp, cash_lv=cash_lv)
            cap["a_liq2_Y1"]["20cr_dev"]["random_cagr"] = cagr(pavg(rl).values)
        log("capacity", per, an, cap["a_liq2_Y1"][f"{an}_{per}"], cap["b_liq2_cap5_Y1"].get(f"{an}_{per}"))


def crossing(tbl, per, target, tiers=("1cr", "5cr", "20cr", "50cr", "100cr")):
    xs = np.log10([AUM[t] / 1e7 for t in tiers])
    ys = np.array([tbl[f"{t}_{per}"]["cagr"] for t in tiers])
    if ys[0] <= target:
        return "below_first"
    for i in range(len(ys) - 1):
        if ys[i] > target >= ys[i + 1]:
            f = (ys[i] - target) / (ys[i] - ys[i + 1])
            return float(10 ** (xs[i] + f * (xs[i + 1] - xs[i])))
    return "above_last"


cap["crossings"] = {}
for per in PERS:
    rf = cap["refs"][per]
    cap["crossings"][per] = {"a_liq2_Y1_EW": crossing(cap["a_liq2_Y1"], per, rf["ew_cagr_own"]),
                             "a_liq2_Y1_N500": crossing(cap["a_liq2_Y1"], per, rf["nifty500_cagr_own"]),
                             "b_cap5_Y1_N500": crossing(cap["b_liq2_cap5_Y1"], per, rf["nifty500_cagr_own"],
                                                        tiers=("20cr", "50cr", "100cr"))}
# participation at Rs 20 cr (every trading day signal, model top-20)
part = {}
for per, (a, b) in PERS.items():
    g0 = D.gidx(a)
    g1 = D.g_last(b or "2026-10-14") - 21
    rows = []
    for g in range(g0, g1):
        cand = D.rows_on(g)
        cand = cand[E[cand] & np.isfinite(prod[cand])]
        rows.append(cand[np.argsort(-prod[cand], kind="stable")[:20]])
    rows = np.concatenate(rows)
    pr = 2.5e6 / adv[rows]
    part[per] = {"median_adv_cr": float(np.median(adv[rows]) / 1e7), "median_part_20cr": float(np.median(pr)),
                 "share_gt10pct_20cr": float((pr > 0.10).mean()),
                 "impact_bps_side_Y1_20cr": float(np.minimum(vol[rows] * np.sqrt(pr), 0.10).mean() * 1e4),
                 "n": int(len(rows))}
cap["participation"] = part
out["capacity"] = cap
log("capacity done", json.dumps(cap["crossings"]), json.dumps(part))

# ------------------------------------------------------------------ 2. overnight gap of exits (model top-20)
gapres = {}
for per, (a, b) in PERS.items():
    g0 = D.gidx(a)
    g1 = D.g_last(b or "2026-10-14") - 21
    rows = []
    for g in range(g0, g1):
        cand = D.rows_on(g)
        cand = cand[E[cand] & np.isfinite(prod[cand])]
        rows.append(cand[np.argsort(-prod[cand], kind="stable")[:20]])
    p = np.concatenate(rows)
    span = (D.cal[D.di[np.minimum(p + 20, D.n - 1)]] - D.cal[D.di[p]]).astype(int)
    ok = (p + 21 <= D.seg_end[p]) & (D.lbc[np.minimum(p + 21, D.n - 1)] == D.lbc[p]) & (span <= 36)
    p = p[ok]
    gap = D.o[p + 21] / D.c[p + 20] - 1
    yrs = D.cal[D.di[p + 20]].astype("datetime64[Y]").astype(int) + 1970
    gapres[per] = {"n": int(len(gap)), "mean": float(gap.mean()), "median": float(np.median(gap)),
                   "share_pos": float((gap > 0).mean()),
                   "by_year_mean": {int(y): float(gap[yrs == y].mean()) for y in np.unique(yrs)}}
out["overnight_gap_model_exits"] = gapres
log("gap", json.dumps(gapres))

# ------------------------------------------------------------------ 3. rejected add-ons
prank = pd.Series(np.where(E, prod, np.nan)).groupby(D.P["date"].values).rank(pct=True).values
vol20 = vol


def invvol(pick):
    npk = len(pick)
    T = npk / 20.0
    iv = 1.0 / np.maximum(vol20[pick], 1e-4)
    capw = 2.0 / 20
    w = T * iv / iv.sum()
    fixed = np.zeros(npk, bool)
    for _ in range(60):
        over = (w > capw + 1e-15) & ~fixed
        if not over.any():
            break
        fixed |= over
        w[fixed] = capw
        w[~fixed] = (T - capw * fixed.sum()) * iv[~fixed] / iv[~fixed].sum()
    return w


addons = {}
for per, (a, b) in PERS.items():
    e0 = own(per, "E0")
    x1l, _ = phase_series(D, a, b, score=prod, cash_lv=cash_lv)
    x1 = pavg(x1l).reindex(e0.index)
    res = {"X1_vs_E0": pdiff(x1, e0)}
    for nm, kw in (("E2w", dict(early=("e2w", prank, 0.30), cash_lv=cash_lv)),
                   ("E2d", dict(early=("e2d", prank, 0.30), cash_lv=cash_lv)),
                   ("E3", dict(early=("e3", 0.75), cash_lv=cash_lv)),
                   ("S1", dict(wfun=invvol))):
        sl, sts = phase_series(D, a, b, score=prod, **kw)
        s = pavg(sl).reindex(e0.index)
        res[nm] = {"cagr": cagr(s.values), "gain_vs_E0": pdiff(s, e0), "maxdd": maxdd(s.values),
                   "dmaxdd_vs_E0": maxdd(s.values) - maxdd(e0.values),
                   "early_share": float(np.mean([x["n_early"] / x["n_pos"] for x in sts]))}
        if nm != "S1":
            res[nm]["gain_vs_X1"] = pdiff(s, x1)
        log(per, nm, json.dumps(res[nm]))
    addons[per] = res
out["addons"] = addons

# ------------------------------------------------------------------ 4. tax illustration (contiguous 2023-01-01 -> end)
CUT = pd.Timestamp("2024-07-23")


def tax_path(sm, trade_mult, mode):
    V, cf, rows = 1.0, 0.0, {}
    for y in sorted(set(sm.index.year)):
        r = sm[sm.index.year == y]
        gf = np.cumprod(1 + r.values)
        g_tot = gf[-1] - 1
        stt = 0.001 * trade_mult[int(y)] * V * gf.mean()
        if mode == "stcg":
            pre = r.index < CUT
            g_a = gf[pre][-1] - 1 if pre.any() else 0.0
            fa = pre.mean()
            parts = [[0.15, V * g_a + stt * fa], [0.20, V * (g_tot - g_a) + stt * (1 - fa)]]
            if y < 2024:
                parts = [[0.15, parts[0][1] + parts[1][1]], [0.20, 0.0]]
            elif y > 2024:
                parts = [[0.15, 0.0], [0.20, parts[0][1] + parts[1][1]]]
            tot = parts[0][1] + parts[1][1]
            if tot <= 0:
                cf += -tot
                tax = 0.0
            else:
                # intra-year netting: a negative part reduces the other part
                if parts[0][1] < 0:
                    parts[1][1] += parts[0][1]
                    parts[0][1] = 0.0
                if parts[1][1] < 0:
                    parts[0][1] += parts[1][1]
                    parts[1][1] = 0.0
                for pp in (parts[1], parts[0]):          # set off brought-forward losses (higher rate first)
                    u = min(cf, pp[1])
                    pp[1] -= u
                    cf -= u
                tax = parts[0][0] * parts[0][1] + parts[1][0] * parts[1][1]
        else:
            tg = V * g_tot
            if tg <= 0:
                cf += -tg
                tax = 0.0
            else:
                u = min(cf, tg)
                cf -= u
                tax = 0.312 * (tg - u)
        rows[int(y)] = {"pre": float(g_tot), "stt_frac": float(stt / V), "tax_frac": float(tax / V)}
        V = V * (1 + g_tot) - tax
    yrs = len(sm) / 252.0
    return {"pre_cagr": cagr(sm.values), "post_cagr": float(V ** (1 / yrs) - 1), "by_year": rows}


taxres = {}
for nm, kw in (("E0", {}), ("X3", dict(mode="X3"))):
    g0 = D.gidx("2023-01-01")
    seriesl, mults = [], []
    from vsim import run_book  # noqa: E402
    for k in range(5):
        rr = run_book(D, g0 + k, None, score=prod, **kw)
        s = pd.Series(rr["r"], index=pd.DatetimeIndex(rr["dates"]))
        eq = pd.Series(rr["eq"], index=s.index)
        seriesl.append(s)
        mults.append({int(y): rr["stats"]["by_year_trade"].get(int(y), 0.0) / float(eq[eq.index.year == y].mean())
                      for y in sorted(set(s.index.year))})
    sm = pavg(seriesl)
    tm = {y: float(np.mean([m[y] for m in mults])) for y in mults[0]}
    taxres[nm] = {"trade_mult_by_year": tm, "stcg": tax_path(sm, tm, "stcg"), "business": tax_path(sm, tm, "bus"),
                  "window": [str(sm.index[0])[:10], str(sm.index[-1])[:10]], "n_days": len(sm)}
    log("tax", nm, json.dumps({k: v for k, v in taxres[nm].items()}, default=float)[:1500])
cm = pavg([pd.Series(0.0, index=x.index) for x in seriesl]).index
lvn = n5.reindex(n5.index.union(cm)).ffill().reindex(cm)
gN = float(lvn.iloc[-1] / lvn.iloc[0] - 1)
yrsN = len(cm) / 252.0
post = (5e6 * (1 + gN) - 0.125 * max(0.0, 5e6 * gN - 1.25e5)) / 5e6
taxres["nifty500_bh_50L"] = {"pre_cagr": float((1 + gN) ** (1 / yrsN) - 1), "post_cagr": float(post ** (1 / yrsN) - 1)}
out["tax"] = taxres
with open(f"{VD}/v2_checks.json", "w") as fh:
    json.dump(out, fh, indent=1, default=float)
log("done")

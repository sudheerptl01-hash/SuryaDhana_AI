"""Verifier checks 3 (own code): single model / 3-seed ensemble vs own random; phase-range definition; by-year paired
add-on diffs; tax with the 4% cess; html_tables values vs results.json values."""
import json
import sys
import time

import numpy as np
import pandas as pd

VD = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab/results/R3_verify_R3_book"
sys.path.insert(0, VD)
from vsim import (LAB, L, Data, run_book, phase_series, pavg, cagr, maxdd, my_nw_t)  # noqa: E402

T0 = time.time()


def log(*a):
    print(f"[{time.time() - T0:7.1f}s]", *a, flush=True)


D = Data()
E = D.E
prod = np.load(f"{LAB}/results/_lead/prod_h20.npz")["prod"].astype(float)
PERS = {"dev": ("2023-01-01", "2025-12-31"), "hold": ("2026-01-01", None)}
out = {}
own1 = {p: np.load(f"{VD}/own_series_{p}.npz") for p in PERS}


def own(per, key):
    z = own1[per]
    return pd.Series(z[key], index=pd.DatetimeIndex(z["dates"]))


def pdiff(a, b):
    c = a.index.intersection(b.index)
    d = a.reindex(c).values - b.reindex(c).values
    return {"diff_ann": float(d.mean() * 252), "nw_t": my_nw_t(d, 20)}


# ---- 1. single model and 3-seed ensemble
DV = f"{LAB}/results/R3_devil"
sm_ = np.load(f"{DV}/wf_main.npz")["score"].astype(float)
s1_ = np.load(f"{DV}/wf_seed1.npz")["score"].astype(float)
s2_ = np.load(f"{DV}/wf_seed2.npz")["score"].astype(float)
dd = D.P["date"].values
rks = [pd.Series(np.where(E, s, np.nan)).groupby(dd).rank(pct=True).values for s in (sm_, s1_, s2_)]
with np.errstate(all="ignore"):
    ens3 = np.nanmean(np.vstack(rks), 0)
ens3 = np.where(E & np.isfinite(sm_), ens3, np.nan)
res1 = {}
for nm, sc in (("single", sm_), ("ens3", ens3)):
    for per, (a, b) in PERS.items():
        sl, _ = phase_series(D, a, b, score=sc)
        s = pavg(sl).reindex(own(per, "R0").index)
        res1[f"{nm}_{per}"] = {"cagr": cagr(s.values), "excess_vs_random": pdiff(s, own(per, "R0")),
                               "PROD_minus": pdiff(own(per, "E0"), s)}
out["single_ens3"] = res1
log("single/ens3", json.dumps(res1))

# ---- 2. phase range with lablib's definition (calendar-day CAGR, random = mean of per-seed CAGRs)
pr = {}
for per, (a, b) in PERS.items():
    g0 = D.gidx(a)
    vals = []
    for k in range(5):
        rr = run_book(D, g0 + k, b, score=prod)
        yrs = (rr["dates"][-1] - rr["dates"][0]).astype(int) / 365.25
        c_s = rr["eq"][-1] ** (1 / yrs) - 1
        c_r = np.mean([run_book(D, g0 + k, b, seed=sd)["eq"][-1] ** (1 / yrs) - 1 for sd in (1, 2, 3, 4, 5)])
        vals.append(float(c_s - c_r))
    pr[per] = {"phase_excess_lablib_def": vals, "min": min(vals), "max": max(vals)}
out["phase_range"] = pr
log("phase range", json.dumps(pr))

# ---- 3. tax with 4% health & education cess on STCG / LTCG (R3_book used 15%/20% and 12.5% without cess)
v2 = json.load(open(f"{VD}/v2_checks.json"))
CUT = pd.Timestamp("2024-07-23")


def tax_path(sm, trade_mult, ra, rb):
    V, cf = 1.0, 0.0
    for y in sorted(set(sm.index.year)):
        r = sm[sm.index.year == y]
        gf = np.cumprod(1 + r.values)
        g_tot = gf[-1] - 1
        stt = 0.001 * trade_mult[str(y)] * V * gf.mean()
        pre = r.index < CUT
        g_a = gf[pre][-1] - 1 if pre.any() else 0.0
        fa = pre.mean()
        parts = [[ra, V * g_a + stt * fa], [rb, V * (g_tot - g_a) + stt * (1 - fa)]]
        if y < 2024:
            parts = [[ra, parts[0][1] + parts[1][1]], [rb, 0.0]]
        elif y > 2024:
            parts = [[ra, 0.0], [rb, parts[0][1] + parts[1][1]]]
        tot = parts[0][1] + parts[1][1]
        if tot <= 0:
            cf += -tot
            tax = 0.0
        else:
            if parts[0][1] < 0:
                parts[1][1] += parts[0][1]
                parts[0][1] = 0.0
            if parts[1][1] < 0:
                parts[0][1] += parts[1][1]
                parts[1][1] = 0.0
            for pp in (parts[1], parts[0]):
                u = min(cf, pp[1])
                pp[1] -= u
                cf -= u
            tax = parts[0][0] * parts[0][1] + parts[1][0] * parts[1][1]
        V = V * (1 + g_tot) - tax
    return float(V ** (252.0 / len(sm)) - 1)


taxc = {}
for nm, kw in (("E0", {}), ("X3", dict(mode="X3"))):
    g0 = D.gidx("2023-01-01")
    sl = [pd.Series(run_book(D, g0 + k, None, score=prod, **kw)["r"],
                    index=pd.DatetimeIndex(run_book(D, g0 + k, None, score=prod, **kw)["dates"])) for k in range(5)]
    sm = pavg(sl)
    tm = v2["tax"][nm]["trade_mult_by_year"]
    taxc[nm] = {"pre": cagr(sm.values), "post_no_cess": tax_path(sm, tm, 0.15, 0.20),
                "post_with_cess": tax_path(sm, tm, 0.156, 0.208)}
    taxc[nm]["drag_no_cess"] = taxc[nm]["pre"] - taxc[nm]["post_no_cess"]
    taxc[nm]["drag_with_cess"] = taxc[nm]["pre"] - taxc[nm]["post_with_cess"]
n5 = L.market_series("Nifty 500")["close"].astype(float)
n5.index = pd.DatetimeIndex(n5.index)
cm = sm.index
lvn = n5.reindex(n5.index.union(cm)).ffill().reindex(cm)
gN = float(lvn.iloc[-1] / lvn.iloc[0] - 1)
yN = len(cm) / 252.0
for rate, lab in ((0.125, "no_cess"), (0.13, "with_cess")):
    post = (5e6 * (1 + gN) - rate * max(0.0, 5e6 * gN - 1.25e5)) / 5e6
    taxc[f"N500_bh_50L_{lab}"] = float(post ** (1 / yN) - 1)
out["tax_cess"] = taxc
log("tax cess", json.dumps(taxc))

# ---- 4. html_tables numeric values vs computed sections of results.json
R = json.load(open(f"{LAB}/results/R3_book/results.json"))
pool = []


def walk(o):
    if isinstance(o, dict):
        for v in o.values():
            walk(v)
    elif isinstance(o, list):
        for v in o:
            walk(v)
    elif isinstance(o, (int, float)) and not isinstance(o, bool):
        pool.append(float(o))


for k, v in R.items():
    if k not in ("html_tables", "charts", "summary"):
        walk(v)
pool = np.array(sorted(set(pool)))
miss = []
nchk = 0
for ti, t in enumerate(R["html_tables"]):
    for row in t["rows"]:
        for ci, x in enumerate(row):
            if isinstance(x, float):
                nchk += 1
                j = np.searchsorted(pool, x)
                near = min(abs(pool[max(j - 1, 0)] - x), abs(pool[min(j, len(pool) - 1)] - x))
                if near > 1e-9:
                    miss.append((ti, t["columns"][ci], row[0], row[1] if len(row) > 1 else None, x))
out["html_tables_check"] = {"n_numbers_checked": nchk, "n_not_found_verbatim": len(miss), "not_found": miss}
log("html check", nchk, len(miss))
for m_ in miss:
    print("   ", m_)
with open(f"{VD}/v3_misc.json", "w") as fh:
    json.dump(out, fh, indent=1, default=float)
log("done")

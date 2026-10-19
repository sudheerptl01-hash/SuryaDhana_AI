"""Verifier v3 (own engine vbook.py): BASE, D4 (F&O short-only), random F&O short, D3 (BASE + 50% F&O short overlay),
D2 K20 cash / K10 fut, and the index hedges D1a/D1b (own overlay, own ex-ante beta), phase-averaged, DEV and 2026, 50 bps.
Sensitivity: (i) futures carry from the entry day instead of the signal close; (ii) strictly ex-ante planned exposure
for the hedge vs the t+1-close exposure R3_twoway used."""
import json
import sys
import time
import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
OUT = LAB + "/results/R3_verify_R3_twoway"
sys.path.insert(0, LAB)
sys.path.insert(0, OUT)
import lablib as L  # noqa: E402
from vbook import VBook, hedge  # noqa: E402

T0 = time.time()
P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["atr_pct", "elig_base", "fno_proxy"])
fw = L.Fwd(P)
E = F["elig_base"].values.astype(bool)
fnoE = E & F["fno_proxy"].values.astype(bool)
prod = np.load(f"{LAB}/results/_lead/prod_h20.npz", allow_pickle=True)["prod"].astype("float64")
d = P["date"].values.astype("datetime64[D]")
cal = np.unique(d)
didx = np.searchsorted(cal, d)
calI = pd.DatetimeIndex(cal)


def lvl(nm):
    return L.market_series(nm)["close"].astype(float).reindex(calI).ffill()


cl = lvl("Nifty 1D Rate Index").values
fut50 = lvl("Nifty 50 Futures Index").values
n500 = lvl("Nifty 500")
VB = VBook(P["open"].values.astype(float), P["close"].values.astype(float), didx, fw.end, fw.lb_cs, cal, cl)

# ---------------- engine validation vs raw L.Sim.run (long BASE, and price-only F&O short)
S = L.Sim(P, F, fw)
val = {}
for nm, legs, kw in (("long_base_dev", [dict(score=prod, mask=E, k=20, side="long", mode="cash", a=1.0, c=0.005)],
                      dict(score=prod, mask=E, top_k=20, cost_bps=50)),
                     ("short_fno_dev", [dict(score=prod, mask=fnoE, k=20, side="short", mode="cash", a=1.0, c=0.0025)],
                      dict(score=prod, mask=fnoE, top_k=20, cost_bps=25, side="short"))):
    mine = VB.run("2023-01-02", "2025-12-31", legs, zero_cash=True)
    if nm.startswith("short"):
        # a cash-mode short leg in vbook is long-valued; emulate L.Sim short: collateral 1 at 0%, value (2-rel)
        legs2 = [dict(legs[0], mode="fut")]
        mine = VB.run("2023-01-02", "2025-12-31", legs2, zero_cash=True, carry_from="none")
    ref = S.run(kw.pop("score"), kw.pop("mask"), 20, step=5, start="2023-01-02", end_exit="2025-12-31", **kw)
    val[nm] = float(np.abs(mine["r"] - ref["_daily_ret"]).max())
print("validation max abs daily diff vs L.Sim:", val, round(time.time() - T0, 1), flush=True)
del S


def my_nw_t(x, lag=20):
    x = np.asarray(x, float)
    n = len(x)
    u = x - x.mean()
    s = u @ u / n
    for k in range(1, lag + 1):
        s += 2 * (1 - k / (lag + 1)) * (u[k:] @ u[:-k]) / n
    return x.mean() / np.sqrt(s / n)


def stats(r):
    r = r.dropna()
    eq = np.cumprod(1 + r.values)
    m = (1 + r).groupby(r.index.to_period("M")).prod() - 1
    return {"cagr": float(eq[-1] ** (252 / len(r)) - 1), "vol": float(r.std() * np.sqrt(252)),
            "sharpe": float(r.mean() / r.std() * np.sqrt(252)), "maxdd": float((eq / np.maximum.accumulate(eq) - 1).min()),
            "worst_month": float(m.min()), "n": int(len(r))}


def paired(a, b):
    c = a.index.intersection(b.index)
    x = a.reindex(c).values - b.reindex(c).values
    return {"diff_ann": float(x.mean() * 252), "nw_t": float(my_nw_t(x))}


def pavg(lst):
    common = lst[0].index
    for x in lst[1:]:
        common = common.intersection(x.index)
    return pd.Series(np.mean([x.reindex(common).values for x in lst], 0), index=common)


S_CASH = 1 / 1.125
S_D3 = 1 / (1 + 0.125 * 0.5)
STRATS = {
    "BASE": [dict(score=prod, mask=E, k=20, side="long", mode="cash", a=1.0, c=0.005)],
    "D4": [dict(score=prod, mask=fnoE, k=20, side="short", mode="fut", a=1.0, c=0.0025)],
    "D3": [dict(score=prod, mask=E, k=20, side="long", mode="cash", a=S_D3, c=0.005),
           dict(score=prod, mask=fnoE, k=20, side="short", mode="fut", a=0.5 * S_D3, c=0.0025)],
    "D2_K20_cash": [dict(score=prod, mask=fnoE, k=20, side="long", mode="cash", a=S_CASH, c=0.005),
                    dict(score=prod, mask=fnoE, k=20, side="short", mode="fut", a=S_CASH, c=0.0025)],
    "D2_K10_fut": [dict(score=prod, mask=fnoE, k=10, side="long", mode="fut", a=1.0, c=0.0025),
                   dict(score=prod, mask=fnoE, k=10, side="short", mode="fut", a=1.0, c=0.0025)],
}
PER = {"dev": ("2023-01-01", "2025-12-31"), "2026": ("2026-01-01", None), "contig": ("2023-01-01", None)}
SER, BOOKS = {}, {}
for per, (a, b) in PER.items():
    g0 = int(np.searchsorted(cal, np.datetime64(a)))
    for nm, legs in STRATS.items():
        if per == "contig" and nm != "BASE":
            continue
        for cf in (("signal", "entry") if nm in ("D4", "D3") and per != "contig" else ("signal",)):
            runs = []
            for k in range(5):
                rr = VB.run(str(cal[g0 + k]), b, legs, carry_from=cf, record=(nm == "BASE"))
                runs.append(pd.Series(rr["r"], index=pd.DatetimeIndex(rr["dates"])))
                if nm == "BASE":
                    BOOKS[(per, k)] = rr
            SER[f"{nm}|{per}|{cf}"] = pavg(runs)
    if per != "contig":
        for cf in ("signal", "entry"):
            runs = []
            for k in range(5):
                seeds = []
                for sd in range(5):
                    legs = [dict(STRATS["D4"][0], seed=7000 + 13 * sd + k)]
                    rr = VB.run(str(cal[g0 + k]), b, legs, carry_from=cf)
                    seeds.append(pd.Series(rr["r"], index=pd.DatetimeIndex(rr["dates"])))
                runs.append(pavg(seeds))
            SER[f"R_D4|{per}|{cf}"] = pavg(runs)
    print(per, "books done", round(time.time() - T0, 1), flush=True)

# ---------------- ex-ante beta (own): contiguous phase-averaged BASE on Nifty 50 futures, 60d window ending t-1
base_c = SER["BASE|contig|signal"]
fr = pd.Series(fut50, index=calI).pct_change().reindex(base_c.index)
y = base_c.copy()
y.iloc[:20] = np.nan
ys, xs = y.shift(1), fr.shift(1)
beta = (ys.rolling(60, min_periods=40).cov(xs) / xs.rolling(60, min_periods=40).var()).clip(0, 2).fillna(1.0)
month_end = pd.Series(calI.to_period("M"), index=calI)
month_end = (month_end != month_end.shift(-1)).values
for per in ("dev", "2026"):
    for hn, bm in (("D1a", "one"), ("D1b", "beta")):
        for fm in ("theirs_t+1", "ex_ante_plan"):
            runs, hns = [], []
            for k in range(5):
                rr = BOOKS[(per, k)]
                gi = rr["g_idx"]
                dts = pd.DatetimeIndex(rr["dates"])
                reset = np.zeros(len(gi), bool)
                reset[::5] = True
                if fm == "theirs_t+1":
                    f = np.r_[rr["expL"][1:], rr["expL"][-1]]
                else:
                    f = rr["plan"]
                bt = np.ones(len(gi)) if bm == "one" else beta.reindex(dts).fillna(1.0).values
                hr, hnot = hedge(rr["r"], f, fut50[gi], cl[gi], bt, reset, month_end[gi])
                runs.append(pd.Series(hr, index=dts))
                hns.append(pd.Series(hnot, index=dts))
            SER[f"{hn}|{per}|{fm}"] = pavg(runs)
            SER[f"{hn}_notional|{per}|{fm}"] = pavg(hns)
print("hedges done", round(time.time() - T0, 1), flush=True)

out = {"validation_vs_LSim": val, "beta_mean_dev": float(beta.loc["2023-03-01":"2025-12-31"].mean()),
       "beta_mean_2026": float(beta.loc["2026-01-01":].mean())}
for per in ("dev", "2026"):
    base = SER[f"BASE|{per}|signal"]
    for k, s in SER.items():
        if f"|{per}|" not in k or "_notional" in k:
            continue
        st = stats(s)
        if not k.startswith("BASE"):
            st["vs_base"] = paired(s, base)
        out[k] = st
    out[f"D4_vs_R_D4|{per}|signal"] = paired(SER[f"D4|{per}|signal"], SER[f"R_D4|{per}|signal"])
    out[f"D4_vs_R_D4|{per}|entry"] = paired(SER[f"D4|{per}|entry"], SER[f"R_D4|{per}|entry"])
    for hn in ("D1a", "D1b"):
        for fm in ("theirs_t+1", "ex_ante_plan"):
            out[f"{hn}_notional_mean|{per}|{fm}"] = float(SER[f"{hn}_notional|{per}|{fm}"].mean())
for k, v in out.items():
    print(k, json.dumps(v if not isinstance(v, dict) else {a: (round(b, 4) if isinstance(b, float) else b) for a, b in v.items()}))
json.dump(out, open(OUT + "/v3_books.json", "w"), indent=1)
np.savez(OUT + "/v3_series.npz", keys=np.array(list(SER)), **{f"v{i}": s.values for i, s in enumerate(SER.values())},
         **{f"d{i}": s.index.values.astype("datetime64[D]").astype(str) for i, s in enumerate(SER.values())})
print("done", round(time.time() - T0, 1))

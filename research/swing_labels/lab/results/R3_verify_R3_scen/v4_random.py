#!/usr/bin/env python3
"""R3_verify_R3_scen v4: random-book horizon economics.

A. Cache integrity: rebuild every random/EW baseline R3_scen read from results/_lead/rb_cache with
   UNCACHED lablib.Sim (same seeds 1-5, 5 phases) and compare phase-averaged CAGRs.
B. Own simulator (written from the frozen-book spec, not from Sim's code): random 20-stock books,
   S = ceil(h/5) staggered sleeves, slot sizing 1/20, next-open entry, h-day time exit or forced exit at
   the last valid close, cost half at entry and half at exit, daily mark-to-market; 20 seeds x 5 phases
   (seeds 101-120: different draws from R3_scen's), phase/seed-averaged daily returns -> CAGR."""
import json
import sys
import time

import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
OUT = f"{LAB}/results/R3_verify_R3_scen"
sys.path.insert(0, LAB)
import lablib as L  # noqa: E402

T0 = time.time()


def log(*a):
    print(f"[{time.time() - T0:6.1f}s]", *a, flush=True)


P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["atr_pct", "elig_base"])
fw = L.Fwd(P)
S = L.Sim(P, F, fw)
E = F["elig_base"].values.astype(bool)
cal = S.cal
ncal = len(cal)
PER = {"dev": ("2023-01-01", "2025-12-31"), "hold": ("2026-01-01", None)}
theirs = json.load(open(f"{LAB}/results/R3_scen/results.json"))["horizon_random_books"]


def pa(series_list):
    common = series_list[0].index
    for x in series_list[1:]:
        common = common.intersection(x.index)
    m = np.mean([x.reindex(common).values for x in series_list], 0)
    return float(np.prod(1 + m) ** (252 / len(m)) - 1), len(m)


# ---------------------------------------------------------------- A. uncached lablib.Sim
A = {}
for h in (5, 10, 15, 20):
    for cost in (0, 50, 80):
        for per, (a, b) in PER.items():
            g0 = int(np.searchsorted(cal, np.datetime64(a)))
            ser = []
            ser_ew = []
            for k in range(5):
                kw = dict(top_k=20, step=5, cost_bps=cost, start=str(cal[g0 + k]), end_exit=b)
                rb = S.random_band(E, h, seeds=(1, 2, 3, 4, 5), **kw)
                ser.append(pd.Series(rb["_daily_ret_mean"], index=pd.DatetimeIndex(rb["_dates"])))
                if cost == 50:
                    kw2 = dict(step=5, cost_bps=cost, start=str(cal[g0 + k]), end_exit=b, select_quantile=(0.0, 1.0),
                               sizing="equal")
                    st = S.run(np.ones(S.n), E, h, **kw2)
                    ser_ew.append(pd.Series(st["_daily_ret"], index=pd.DatetimeIndex(st["_dates"])))
            cg, nd = pa(ser)
            A[f"random_h{h}_c{cost}_{per}"] = {"mine_uncached": cg, "theirs": theirs[f"random_h{h}_c{cost}_{per}"]["cagr"],
                                              "n_days": nd}
            if cost == 50:
                ce, _ = pa(ser_ew)
                A[f"ew_h{h}_c50_{per}"] = {"mine_uncached": ce, "theirs": theirs[f"ew_h{h}_c50_{per}"]["cagr"]}
    log("A h", h, {k: (round(v["mine_uncached"], 4), round(v["theirs"], 4)) for k, v in A.items() if f"_h{h}_" in k})
maxdiff = max(abs(v["mine_uncached"] - v["theirs"]) for v in A.values())
log("A max |uncached - theirs| =", maxdiff)

# ---------------------------------------------------------------- B. own simulator
n = S.n
dates = P["date"].values.astype("datetime64[D]")
o = P["open"].values.astype("float64")
c = P["close"].values.astype("float64")
lbcum = np.cumsum(P["label_block"].values.astype(bool))
ent = P["entity"].values
newseg = np.r_[True, ent[1:] != ent[:-1]] | P["seg_break"].values.astype(bool)
segid = np.cumsum(newseg) - 1
firsts = np.flatnonzero(newseg)
seg_end = np.r_[firsts[1:] - 1, n - 1][segid]
didx = np.searchsorted(cal, dates)
del P, ent
order = np.argsort(didx, kind="stable")
bnd = np.searchsorted(didx[order], np.arange(ncal + 1))
elig_rows = [None] * ncal
for g in range(ncal):
    rr = order[bnd[g]:bnd[g + 1]]
    elig_rows[g] = rr[E[rr]]


def pick_paths(rows, h, g, g_next):
    """For picked rows: entry price, per-bar (day index, close) for valid bars, exit bar count."""
    k = np.arange(1, h + 1)
    j = rows[:, None] + k[None, :]
    jc = np.minimum(j, n - 1)
    ok = (j <= seg_end[rows][:, None]) & ((lbcum[jc] - lbcum[rows][:, None]) == 0) & (didx[jc] <= g_next)
    ok = np.cumprod(ok, axis=1).astype(bool)
    return jc, ok


def run_book(h, cost, start_g, last_exit_g, rng, ew=False):
    nsl = int(np.ceil(h / 5))
    period = nsl * 5
    sigs = list(range(start_g, last_exit_g - h - 1 + 1, 5))
    D0 = start_g
    D1 = min(last_exit_g, sigs[-1] + period)
    nd = D1 - D0 + 1
    val = np.ones((nsl, nd))
    eq_s = np.ones(nsl)
    last_end = np.zeros(nsl, int)
    for jx, g in enumerate(sigs):
        s = jx % nsl
        g_next = min(g + period, D1)
        cand = elig_rows[g]
        if ew:
            pick = cand
            w = None
        else:
            pick = rng.choice(cand, size=min(20, len(cand)), replace=False)
        jc, ok = pick_paths(pick, h, g, g_next)
        good = ok[:, 0] & np.isfinite(o[jc[:, 0]]) & (o[jc[:, 0]] > 0)
        pick, jc, ok = pick[good], jc[good], ok[good]
        days = np.arange(g + 1, g_next + 1)               # calendar indices marked in this window
        if len(pick) == 0:
            val[s, g - D0 + 1:g_next - D0 + 1] = eq_s[s]
            last_end[s] = g_next - D0
            continue
        w = 1.0 / len(pick) if ew else 1.0 / 20
        entry = o[jc[:, 0]]
        K = ok.sum(1)                                      # bars held (>=1)
        bar_day = np.where(ok, didx[jc], 10 ** 9)
        exit_day = didx[jc[np.arange(len(pick)), K - 1]]
        # latest valid bar with day <= d
        cnt = (bar_day[:, None, :] <= days[None, :, None]).sum(2)
        price = np.where(cnt > 0, c[jc[np.arange(len(pick))[:, None], np.maximum(cnt - 1, 0)]], np.nan)
        slot = np.where(cnt == 0, 1.0, price / entry[:, None] * (1 - cost / 2e4))
        slot = np.where(days[None, :] >= exit_day[:, None], slot * (1 - cost / 2e4), slot)
        cash = 1.0 - w * len(pick)
        path = cash + w * slot.sum(0)
        val[s, g - D0 + 1:g_next - D0 + 1] = eq_s[s] * path
        eq_s[s] = eq_s[s] * path[-1]
        last_end[s] = g_next - D0
    for s in range(nsl):
        if 0 < last_end[s] < nd - 1:
            val[s, last_end[s] + 1:] = val[s, last_end[s]]
    book = val.mean(0)
    r = np.r_[0.0, book[1:] / book[:-1] - 1]
    return pd.Series(r, index=pd.DatetimeIndex(cal[D0:D1 + 1]))


B = {}
for h in (5, 20):
    for per, (a, b) in PER.items():
        g0 = int(np.searchsorted(cal, np.datetime64(a)))
        gl = ncal - 1 if b is None else int(np.searchsorted(cal, np.datetime64(b), side="right")) - 1
        ser = []
        single = []
        for k in range(5):
            for sd in range(101, 121):
                x = run_book(h, 50, g0 + k, gl, np.random.default_rng(sd))
                ser.append(x)
                single.append(float(np.prod(1 + x.values) ** (252 / len(x)) - 1))
        cg, nd = pa(ser)
        ew_ser = [run_book(h, 50, g0 + k, gl, None, ew=True) for k in range(5)]
        ce, _ = pa(ew_ser)
        B[f"h{h}_c50_{per}"] = {"own_random_20seeds_x5phases": cg, "own_ew": ce,
                                "single_run_cagr_sd": float(np.std(single)), "single_run_cagr_mean": float(np.mean(single)),
                                "theirs_random": theirs[f"random_h{h}_c50_{per}"]["cagr"],
                                "theirs_ew": theirs[f"ew_h{h}_c50_{per}"]["cagr"], "n_days": nd}
        log("B", h, per, {k: (round(v, 4) if isinstance(v, float) else v) for k, v in B[f"h{h}_c50_{per}"].items()})
json.dump({"A_uncached_sim": A, "A_maxdiff": maxdiff, "B_own_sim": B}, open(f"{OUT}/v4_results.json", "w"), indent=1)
log("done")

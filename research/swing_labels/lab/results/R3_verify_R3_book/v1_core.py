"""Verifier core: independent re-computation of R3_book headline numbers with vsim (own code).
(1) PROD frozen book DEV/2026 phase-averaged vs own 5-seed random and own EW universe;
(2) cache check: own random/EW per-phase daily series vs the shared rb_cache files used by R3_book ("liq2" tag);
(3) X3 executable carry vs E0 (paired NW t), random top-20 with X3 timing (timing gain), X3 vs timing-matched random;
(4) element-wise comparison with R3_book's saved phase-averaged series."""
import json
import os
import sys
import time

import numpy as np
import pandas as pd

VD = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab/results/R3_verify_R3_book"
sys.path.insert(0, VD)
from vsim import (LAB, Data, phase_series, seeds_mean, pavg, common_of, cagr, maxdd, sharpe, my_nw_t)  # noqa: E402

sys.path.insert(0, LAB)
import r3common as C  # noqa: E402  (only key_of / RB path to locate the shared cache files)

T0 = time.time()


def log(*a):
    print(f"[{time.time() - T0:7.1f}s]", *a, flush=True)


D = Data()
prod = np.load(f"{LAB}/results/_lead/prod_h20.npz")["prod"].astype(float)
log("data ready", D.n, "rows; PROD finite", int(np.isfinite(prod).sum()))
PERS = {"dev": ("2023-01-01", "2025-12-31"), "hold": ("2026-01-01", None)}
BK = f"{LAB}/results/R3_book"
z1 = np.load(f"{BK}/pa_series_item1.npz")
z2 = np.load(f"{BK}/pa_series_item2.npz")


def theirs(z, key):
    return pd.Series(z[f"{key}"], index=pd.DatetimeIndex(z[f"{key}__dates"] if f"{key}__dates" in z.files else None))


def pdiff(a, b):
    c = a.index.intersection(b.index)
    d = a.reindex(c).values - b.reindex(c).values
    return {"diff_ann": float(d.mean() * 252), "nw_t": my_nw_t(d, 20), "n": int(len(c))}


out = {}
for per, (a, b) in PERS.items():
    res = {}
    g0 = D.gidx(a)
    s_e0, st_e0 = phase_series(D, a, b, score=prod)
    r_e0 = seeds_mean(D, a, b)
    ew_l, _ = phase_series(D, a, b, ew=True)
    log(per, "E0/random/EW done")
    # ---- cache check (per phase)
    cc = {}
    for k in range(5):
        kw = dict(C.BASE_KW, cost_bps=50, start=str(D.cal[g0 + k]), end_exit=b)
        fr = os.path.join(C.RB, C.key_of("liq2", 20, kw) + ".npz")
        kw2 = dict(kw)
        kw2["select_quantile"] = (0.0, 1.0)
        kw2["sizing"] = "equal"
        kw2.pop("top_k", None)
        fe = os.path.join(C.RB, "EW_" + C.key_of("liq2", 20, kw2) + ".npz")
        zr, ze = np.load(fr, allow_pickle=True), np.load(fe, allow_pickle=True)
        cr_ = pd.Series(zr["daily"], index=pd.DatetimeIndex(zr["dates"]))
        ce_ = pd.Series(ze["daily"], index=pd.DatetimeIndex(ze["dates"]))
        cc[f"phase{k}"] = {"random_maxabs": float(np.abs(cr_.reindex(r_e0[k].index).values - r_e0[k].values).max()),
                           "ew_maxabs": float(np.abs(ce_.reindex(ew_l[k].index).values - ew_l[k].values).max()),
                           "same_dates": bool(cr_.index.equals(r_e0[k].index) and ce_.index.equals(ew_l[k].index))}
    res["cache_check_vs_own"] = cc
    log(per, "cache check", cc)
    # ---- X3 strategy + X3-timed random
    s_x3, st_x3 = phase_series(D, a, b, score=prod, mode="X3")
    r_x3 = seeds_mean(D, a, b, mode="X3")
    log(per, "X3 done")
    s80, _ = phase_series(D, a, b, score=prod, flat=0.008)
    r80 = seeds_mean(D, a, b, flat=0.008)
    cm = common_of(s_e0, r_e0, ew_l, s_x3, r_x3)
    S0, R0, EW, S3, R3 = (pavg(x, cm) for x in (s_e0, r_e0, ew_l, s_x3, r_x3))
    cm80 = common_of(s80, r80)
    S80, R80 = pavg(s80, cm80), pavg(r80, cm80)
    res["E0"] = {"cagr": cagr(S0), "random_cagr": cagr(R0), "ew_cagr": cagr(EW), "maxdd": maxdd(S0),
                 "sharpe": sharpe(S0), "vol": float(S0.std() * np.sqrt(252)), "n_days": len(cm),
                 "start": str(cm[0])[:10], "end": str(cm[-1])[:10],
                 "excess_vs_random": pdiff(S0, R0), "excess_vs_ew": pdiff(S0, EW),
                 "c80": {"cagr": cagr(S80), "random_cagr": cagr(R80), "excess_vs_random": pdiff(S80, R80)}}
    # phase-level excess (phase CAGR minus 5-seed random CAGR), like phase_excess
    res["E0"]["phase_excess"] = [cagr(s_e0[k].values) - cagr(r_e0[k].values) for k in range(5)]
    res["X3"] = {"cagr": cagr(S3), "maxdd": maxdd(S3), "gain_vs_E0": pdiff(S3, S0),
                 "random_X3timing_cagr": cagr(R3), "random_timing_gain": pdiff(R3, R0),
                 "X3_vs_timing_matched_random": pdiff(S3, R3),
                 "carried_share": float(np.mean([s["n_carried"] / s["n_pos"] for s in st_x3])),
                 "legacy_open_per_phase": float(np.mean([s["n_legacy_open"] for s in st_x3]))}
    yrs = sorted(set(cm.year))
    res["X3"]["gain_by_year"] = {int(y): float((S3 - S0)[cm.year == y].mean() * 252) for y in yrs}
    res["X3"]["random_gain_by_year"] = {int(y): float((R3 - R0)[cm.year == y].mean() * 252) for y in yrs}
    # turnover stats (book units) from own accounting, phase mean
    def turn(sts, ser):
        yrs_ = len(ser) / 252.0
        return {"round_trips_per_yr": float(np.mean([s["rt"] for s in sts])) / yrs_,
                "traded_x_book_approx": float(np.mean([(s["buys"] + s["sells"]) for s in sts])) / yrs_,
                "cost_paid_per_yr_approx": float(np.mean([s["cost"] for s in sts])) / yrs_}
    res["E0"]["turnover_approx"] = turn(st_e0, S0)
    res["X3"]["turnover_approx"] = turn(st_x3, S3)
    # ---- compare with R3_book saved series
    try:
        tk = f"PROD_{per}_c50"
        tS = pd.Series(z1[f"{tk}__s"], index=pd.DatetimeIndex(z1[f"{tk}__dates"]))
        tR = pd.Series(z1[f"{tk}__r"], index=pd.DatetimeIndex(z1[f"{tk}__dates"]))
        tE = pd.Series(z1[f"{tk}__e"], index=pd.DatetimeIndex(z1[f"{tk}__dates"]))
        t3 = pd.Series(z2[f"X3__{per}_c50"], index=pd.DatetimeIndex(z2[f"X3__{per}_c50__dates"]))
        res["vs_R3_book_series_maxabs"] = {
            "E0": float(np.abs(tS.reindex(cm).values - S0.values).max()),
            "random": float(np.abs(tR.reindex(cm).values - R0.values).max()),
            "EW": float(np.abs(tE.reindex(cm).values - EW.values).max()),
            "X3": float(np.abs(t3.reindex(cm).values - S3.values).max()),
            "same_calendar": bool(tS.index.equals(cm) and t3.index.equals(cm))}
    except Exception as ex:  # noqa: BLE001
        res["vs_R3_book_series_maxabs"] = {"error": repr(ex)}
    out[per] = res
    log(per, json.dumps({k: v for k, v in res.items() if k != "cache_check_vs_own"}, default=float)[:3000])
    np.savez_compressed(f"{VD}/own_series_{per}.npz", dates=cm.values.astype("datetime64[D]").astype(str),
                        E0=S0.values, R0=R0.values, EW=EW.values, X3=S3.values, R3=R3.values)

with open(f"{VD}/v1_core.json", "w") as fh:
    json.dump(out, fh, indent=1, default=float)
log("done")

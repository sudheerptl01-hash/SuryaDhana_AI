"""Stage 8 (devil): extra checks.
 * seed ensemble: mean of the per-date ranks of the main/seed1/seed2 scores (variance reduction, no selection)
 * event-time profile: average excess path of the top-20 picks vs the same-date elig universe, days 1..20
 * rolling 126-day excess of the phase-averaged book, and monthly 2026 excess
"""
import numpy as np
import pandas as pd

from common import OUT, L, PER, log, save, load_sim, phase_avg, short

P, F, fw, S, E = load_sim()
H = 20
d = P["date"].values.astype("datetime64[D]")
out = {}
sc = {j: np.load(f"{OUT}/wf_{j}.npz")["score"].astype("float64") for j in ("main", "seed1", "seed2")}
rk = {j: pd.Series(np.where(E, s, np.nan)).groupby(d).rank(pct=True).values for j, s in sc.items()}
ens = np.nanmean(np.vstack(list(rk.values())), 0)
ens = np.where(E & np.isfinite(sc["main"]), ens, np.nan)
for per in PER:
    r, *_ = phase_avg(S, ens, E, "liq2", H, dict(top_k=20, step=5, cost_bps=50), per)
    out[f"seed_ensemble_{per}"] = {k: r[k] for k in ("pa_cagr", "pa_random_cagr", "pa_excess_ann", "pa_nw_t",
                                                     "phase_excess_min", "phase_excess_max", "pa_maxdd")}
    log("ensemble", per, short(out[f"seed_ensemble_{per}"]))

# event-time excess path of the picks (vs same-date EW universe), DEV and hold
o = P["open"].values.astype("float64")
c = P["close"].values.astype("float64")
e1 = fw.at(o, 1)
paths = {}
for k in range(1, H + 1):
    ck = fw.at(c, k)
    paths[k] = ck / e1 - 1
for per, (a, b) in PER.items():
    st = S.run(sc["main"], E, H, top_k=20, step=5, cost_bps=50, start=a, end_exit=b, keep_trades=True)
    rows = np.array([t[1] for t in st["_trades"]])
    prof = []
    for k in range(1, H + 1):
        pk = paths[k]
        ok = E & np.isfinite(pk)
        mu = pd.Series(np.where(ok, pk, np.nan)).groupby(d).transform("mean").values
        x = pk[rows] - mu[rows]
        prof.append(float(np.nanmean(x)))
    out[f"event_time_excess_{per}"] = {str(k + 1): v for k, v in enumerate(prof)}
    log("event-time", per, [round(v * 1e4) for v in prof])

# rolling excess
z = np.load(f"{OUT}/pa_series_main.npz")
for per in PER:
    idx = pd.DatetimeIndex(z[f"{per}_strat__dates"])
    ex = pd.Series(z[f"{per}_strat"] - z[f"{per}_rand"], index=idx)
    mo = ex.groupby(ex.index.to_period("M")).sum()
    out[f"monthly_excess_{per}"] = {str(k): float(v) for k, v in mo.items()}
    if per == "dev":
        roll = ex.rolling(126).sum().dropna()
        out["rolling126_dev"] = {"min": float(roll.min()), "min_end": str(roll.idxmin().date()),
                                 "share_negative": float((roll < 0).mean()), "max": float(roll.max())}
        log("rolling126 dev", short(out["rolling126_dev"]))
    log("monthly", per, short(out[f"monthly_excess_{per}"], 3))
save("s8_extra", out)

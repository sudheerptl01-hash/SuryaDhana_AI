#!/usr/bin/env python3
"""Stage 6: audit of portfolio_sim statistics.
portfolio_sim books each cohort's whole h-day return on its SIGNAL date and computes Sharpe from
per-step equity changes annualised with sqrt(252/step). With h=10, step=5 the two sleeves'
cohorts overlap by 5 days, so consecutive step returns are autocorrelated -> Sharpe overstated,
and intra-trade drawdowns are invisible -> maxDD understated. Here we rebuild a DAILY
mark-to-market equity curve for the same picks and compare."""
import numpy as np
import pandas as pd

from common import OUT, L, save
from fastsim import Sim

H, STEP, K = 10, 5, 20
P = L.load_panel(["date", "entity", "open", "close", "seg_break", "label_block"])
F = L.load_features(["elig_base"])
fw = L.Fwd(P)
sim = Sim(P, fw, H)
eb = F.elig_base.values
cal = np.unique(P.date.values.astype("datetime64[D]"))
pos_of = {d: i for i, d in enumerate(cal)}
e1 = fw.at(P.open.values, 1)
closes = np.vstack([fw.at(P.close.values, k) for k in range(1, H + 1)])  # H x n
# carry last available close forward (forced exit convention of portfolio_sim)
for k in range(1, H):
    closes[k] = np.where(np.isnan(closes[k]), closes[k - 1], closes[k])
rel = closes / e1  # H x n : value multiple at close of t+k


def mtm(res, cost_bps=50.0, start="2023-01-01"):
    cd = res["cohort_dates"]
    picks = res["picks"]
    cr = res["cohort_rets"]
    S = int(np.ceil(H / STEP))
    # rebuild per-cohort pick lists in order (cohorts with zero picks have cr==0 and no entry)
    # fastsim appends picks only for cohorts with picks; all cohorts here have picks (large universe)
    assert len(picks) == len(cd) * K
    pk = picks.reshape(len(cd), K)
    T0 = pos_of[cd[0]]
    T1 = pos_of[cd[-1]] + H + 1
    ndays = T1 - T0 + 1
    sleeve_val = np.ones((S, ndays))
    cur = np.ones(S)
    last_t = np.full(S, 0)
    for c, d in enumerate(cd):
        s = c % S
        t = pos_of[d] - T0
        # sleeve s idle from last_t to t (flat)
        sleeve_val[s, last_t[s]:t + 1] = cur[s]
        path = np.nanmean(rel[:, pk[c]], axis=1)  # H
        for k in range(1, H + 1):
            if t + k < ndays:
                v = cur[s] * path[k - 1]
                if k == H:
                    v = cur[s] * (1 + cr[c])   # exact net return booked by portfolio_sim at exit
                sleeve_val[s, t + k] = v
        cur[s] = cur[s] * (1 + cr[c])
        last_t[s] = t + H
    for s in range(S):
        sleeve_val[s, last_t[s]:] = cur[s]
    eq = sleeve_val.mean(0)
    dr = eq[1:] / eq[:-1] - 1
    dd = eq / np.maximum.accumulate(eq) - 1
    return {"daily_sharpe": float(dr.mean() / dr.std() * np.sqrt(252)), "daily_maxdd": float(dd.min()),
            "final": float(eq[-1])}


rows = []
for seed in range(10):
    r = sim.run(None, eb, "eb", step=STEP, top_k=K, random_seed=seed, start="2023-01-01", end="2025-12-31",
                return_cohorts=True)
    st = np.r_[np.nan, np.array(r["cohort_rets"])]
    # step returns as in portfolio_sim
    m = mtm(r)
    S = 2
    sleeves = np.ones(S)
    eq = []
    for c, x in enumerate(r["cohort_rets"]):
        sleeves[c % S] *= (1 + x)
        eq.append(sleeves.mean())
    eq = np.array(eq)
    sr = np.r_[eq[0] - 1, eq[1:] / eq[:-1] - 1]
    ac1 = float(pd.Series(sr).autocorr(1))
    rows.append({"seed": seed, "sim_sharpe": r["sharpe"], "sim_maxdd": r["max_dd"], "mtm_sharpe": m["daily_sharpe"],
                 "mtm_maxdd": m["daily_maxdd"], "steprets_lag1_autocorr": ac1,
                 "sim_final": float(eq[-1]), "mtm_final": m["final"]})
    print(rows[-1], flush=True)
T = pd.DataFrame(rows)
R = {"random_dev_10seeds": rows, "mean": T.mean().to_dict(),
     "sharpe_ratio_sim_over_mtm_median": float((T.sim_sharpe / T.mtm_sharpe).median())}
# model score (baseline WF) top-20
try:
    sc = np.load(f"{OUT}/wf_base.npz")["score"].astype(float)
    for win in (("2023-01-01", "2025-12-31"), ("2026-01-01", "2026-09-10")):
        r = sim.run(sc, eb, "eb", step=STEP, top_k=K, start=win[0], end=win[1], return_cohorts=True)
        m = mtm(r)
        R[f"base_model_{win[0][:4]}"] = {"sim_sharpe": r["sharpe"], "sim_maxdd": r["max_dd"], "sim_cagr": r["cagr"],
                                        "mtm_sharpe": m["daily_sharpe"], "mtm_maxdd": m["daily_maxdd"]}
        print(R[f"base_model_{win[0][:4]}"], flush=True)
except FileNotFoundError:
    pass
# Nifty 500 Sharpe for the same window computed the same daily way
R["nifty500_dev_daily_sharpe"] = L.benchmark(P, start="2023-01-01", end="2025-12-31")["sharpe"]
save("s6_sim_audit", R)

"""Stage 10 (devil): persistence-matched null for the NW t of the top-20 book (independent of R2_rel's).
Random scores = sqrt(w)*entity constant + sqrt(1-w)*AR(1)(rho) within segment, with (w, rho) fitted to the
model score's own within-entity rank autocorrelation at lags 5 and 250. 40 draws, phase-averaged K20 s5
50 bps DEV and 2026 books vs the same 5-seed random baseline. Output: null mean/sd of the excess and of the
NW t (the sd is the null dispersion to use in the deflated Sharpe), and the model's z."""
import numpy as np
import pandas as pd
from scipy.signal import lfilter

from common import OUT, L, PER, log, save, load_sim, phase_avg, short

P, F, fw, S, E = load_sim()
H = 20
d = P["date"].values.astype("datetime64[D]")
sc = np.load(f"{OUT}/wf_main.npz")["score"].astype("float64")
rk = pd.Series(np.where(E, sc, np.nan)).groupby(d).rank(pct=True).values
ac = {}
for k in (1, 5, 20, 60, 250):
    lagged = fw.at(rk, -k)
    ok = np.isfinite(rk) & np.isfinite(lagged)
    ac[k] = float(np.corrcoef(rk[ok], lagged[ok])[0, 1])
w = max(min(ac[250], 0.9), 0.0)
rho = ((ac[5] - w) / (1 - w)) ** (1 / 5)
log("score rank autocorr", short(ac), "fitted w", round(w, 3), "rho", round(rho, 4))
seg = fw.seg
n = len(sc)
start = fw.start
pos = np.arange(n) - start                      # position inside segment
ent_codes = pd.factorize(P["entity"].values)[0]
res = {"autocorr": ac, "w": w, "rho": rho, "draws": []}
for draw in range(40):
    rng = np.random.default_rng(1000 + draw)
    e = rng.standard_normal(n)
    y = lfilter([1.0], [1.0, -rho], e)
    prev = np.where(start > 0, y[np.maximum(start - 1, 0)], 0.0)
    ar = (y - rho ** (pos + 1) * prev) * np.sqrt(1 - rho ** 2)   # reset at each segment start
    const = rng.standard_normal(ent_codes.max() + 1)[ent_codes]
    z = np.sqrt(w) * const + np.sqrt(1 - w) * ar
    z = np.where(E, z, np.nan)
    rec = {}
    for per in PER:
        r, *_ = phase_avg(S, z, E, "liq2", H, dict(top_k=20, step=5, cost_bps=50), per)
        rec[per] = (r["pa_excess_ann"], r["pa_nw_t"])
    res["draws"].append(rec)
    if draw % 10 == 9:
        log("draw", draw + 1)
for per in PER:
    ex = np.array([x[per][0] for x in res["draws"]])
    tt = np.array([x[per][1] for x in res["draws"]])
    res[f"null_{per}"] = {"excess_mean": float(ex.mean()), "excess_sd": float(ex.std(ddof=1)),
                          "excess_p95": float(np.percentile(ex, 95)), "excess_max": float(ex.max()),
                          "t_mean": float(tt.mean()), "t_sd": float(tt.std(ddof=1)), "t_p95": float(np.percentile(tt, 95)),
                          "t_max": float(tt.max())}
model = {"dev": (0.1576, 4.106), "hold": (0.039, 0.599)}
for per in PER:
    nl = res[f"null_{per}"]
    res[f"model_z_{per}"] = {"excess_z": (model[per][0] - nl["excess_mean"]) / nl["excess_sd"],
                             "t_z": (model[per][1] - nl["t_mean"]) / nl["t_sd"],
                             "pct_of_null_excess_below_model": float(np.mean([x[per][0] < model[per][0] for x in res["draws"]]))}
    log(per, short(nl), short(res[f"model_z_{per}"]))
res["draws"] = [{p: list(v) for p, v in x.items()} for x in res["draws"]]
save("s10_persistence_null", res)

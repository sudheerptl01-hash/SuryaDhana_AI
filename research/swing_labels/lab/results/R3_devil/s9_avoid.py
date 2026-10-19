"""Stage 9 (devil): the avoid label (bottom 30% of the same score) as an overlay, re-derived with the
self-built model and perturbed: seeds, seed ensemble, cut 10/30%, entity halves, 1-day lag.
Overlay = equal-weight elig_base minus the score's bottom q (select_quantile=(q,1), sizing equal, step 5,
50 bps, phase-averaged) vs the equal-weight universe (0,1) on the same calendar."""
import numpy as np
import pandas as pd

from common import OUT, L, PER, log, save, load_sim, phase_avg, entity_half, short

P, F, fw, S, E = load_sim()
H = 20
d = P["date"].values.astype("datetime64[D]")
sc = {j: np.load(f"{OUT}/wf_{j}.npz")["score"].astype("float64") for j in ("main", "seed1", "seed2")}
rk = {j: pd.Series(np.where(E, s, np.nan)).groupby(d).rank(pct=True).values for j, s in sc.items()}
ens = np.where(E & np.isfinite(sc["main"]), np.nanmean(np.vstack(list(rk.values())), 0), np.nan)
half = entity_half(P["entity"].values)
out = {}
KEYS = ("pa_cagr", "pa_ew_cagr", "pa_excess_vs_ew_ann", "pa_vs_ew_nw_t", "phase_excess_min", "phase_excess_max")


def ov(score, q, per, mask=E, tag="liq2"):
    r, *_ = phase_avg(S, score, mask, tag, H, dict(step=5, cost_bps=50, select_quantile=(q, 1.0), sizing="equal"),
                      per, with_ew=True)
    return {k: r[k] for k in KEYS}


for per in PER:
    for nm, s_ in (("main", sc["main"]), ("seed1", sc["seed1"]), ("seed2", sc["seed2"]), ("ensemble", ens)):
        out[f"{nm}_q0.3_{per}"] = ov(s_, 0.3, per)
        log(nm, per, short(out[f"{nm}_q0.3_{per}"]))
    out[f"main_q0.1_{per}"] = ov(sc["main"], 0.1, per)
    out[f"main_lag1_q0.3_{per}"] = ov(fw.at(sc["main"], -1), 0.3, per, mask=E & np.isfinite(fw.at(sc["main"], -1)),
                                      tag="lag1")
    for hn, hv in (("A", 0), ("B", 1)):
        out[f"main_half{hn}_q0.3_{per}"] = ov(sc["main"], 0.3, per, mask=E & (half == hv), tag=f"half{hn}")
    log("cut/lag/halves", per, short({k: out[k]["pa_excess_vs_ew_ann"] for k in out if k.endswith(per)}))
save("s9_avoid", out)

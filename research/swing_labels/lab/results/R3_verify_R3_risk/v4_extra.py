"""R3_verify_R3_risk v4: (a) single-phase expectation summary, (b) G50 vs exposure-matched X80,
(c) probability that K3 fires by early/mid 2027 given the realised path to 2026-10-14,
(d) html_tables / summary consistency spot checks against results.json."""
import json
import sys

import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
OUT = LAB + "/results/R3_verify_R3_risk"
z = np.load(f"{OUT}/v1_series.npz")
v2 = json.load(open(f"{OUT}/v2_out.json"))
R = json.load(open(f"{LAB}/results/R3_risk/results.json"))


def S_(k):
    return pd.Series(z[k], index=pd.DatetimeIndex(z[k + "_dates"]))


def nwt(d, lag=20):
    d = np.asarray(d, float)
    n = len(d)
    u = d - d.mean()
    v = u @ u / n
    for k in range(1, lag + 1):
        v += 2 * (1 - k / (lag + 1)) * (u[k:] @ u[:-k]) / n
    return float(d.mean() / np.sqrt(v / n))


out = {}
# (a) single-phase expectations
sp = v2["boot_cbb40_single_phase"]
out["single_phase_p_neg_year_plus5"] = [x["t5"]["p_neg_12m"] for x in sp]
out["single_phase_sd_12m"] = [x["t5"]["sd_12m"] for x in sp]
out["single_phase_p_dead_above5"] = [x["t0"]["p_above5_12m"] for x in sp]
out["single_phase_mean"] = {"p_neg_year_plus5": float(np.mean(out["single_phase_p_neg_year_plus5"])),
                            "sd_12m": float(np.mean(out["single_phase_sd_12m"])),
                            "p_dead_above5": float(np.mean(out["single_phase_p_dead_above5"]))}
# (b) G50 vs X80 (exposure-matched static) on DEV and 2026
for per in ("dev", "hold"):
    g, x8 = S_(f"PROD_{per}_G50"), S_(f"PROD_{per}_X80")
    c = g.index.intersection(x8.index)
    d = g.reindex(c).values - x8.reindex(c).values
    out[f"G50_minus_X80_{per}"] = {"diff_ann": float(d.mean() * 252), "nw_t": nwt(d)}
ex = R["item2_exposure"]["results"]
out["EW_pre_G50_minus_X80_cagr"] = ex["EW_pre_c50_G50"]["cagr"] - ex["EW_pre_c50_X80"]["cagr"]
out["avg_exposure"] = {k: ex[f"PROD_dev_c50_{k}"]["avg_exposure"] for k in ("X80", "G50")}
# (c) K3 in early 2027: realised contiguous excess + bootstrapped future excess
b, r = S_("contig_book"), S_("contig_rand")
ex_c = (b - r).values
ex_dev = (S_("dev_book") - S_("dev_rand")).values
v = ex_dev - ex_dev.mean()
rng = np.random.default_rng(4242)
NP, FUT, BL = 20000, 180, 40
nb = -(-FUT // BL)
st = rng.integers(0, len(v), (NP, nb))
I = ((st[:, :, None] + np.arange(BL)[None, None, :]) % len(v)).reshape(NP, -1)[:, :FUT]
last_date = b.index[-1]
fut_dates = pd.bdate_range(last_date + pd.Timedelta(days=1), periods=FUT)   # approx. trading calendar
res = {}
for tgt in (0.05, 0.0):
    x = v[I] + tgt / 252
    path = np.concatenate([np.repeat(ex_c[None, :], NP, 0), x], 1)
    cs = np.concatenate([np.zeros((NP, 1)), path.cumsum(1)], 1)
    n0 = len(ex_c)
    fire_by = {}
    for lab, dl in (("2027-03-31", "2027-03-31"), ("2027-06-30", "2027-06-30")):
        kmax = int((fut_dates <= dl).sum())
        fired = np.zeros(NP, bool)
        for k in range(5, kmax + 1, 5):      # weekly checks after the last realised day
            t = n0 + k
            fired |= (cs[:, t] - cs[:, t - 252]) < 0
        fire_by[lab] = float(fired.mean())
    res[f"plan_{int(tgt * 100)}pct"] = fire_by
out["K3_fire_prob_given_realised_path"] = res
out["contig_last_date"] = str(last_date.date())
# (d) html_tables spot checks
T = R["html_tables"]
kb = R["item4_kill_bootstrap"]
t9 = [t for t in T if t["title"].startswith("Kill and review rules")][0]
c2row = [rw for rw in t9["rows"] if rw[0].startswith("KILL")][0]
out["table9_C2_row"] = c2row
out["table9_C2_matches"] = bool(abs(c2row[1] - kb["b40_H1a"]["C2_kill"]["p_fire_24m"]) < 1e-12
                               and abs(c2row[6] - kb["b40_H0"]["C2_kill"]["p_fire_24m"]) < 1e-12)
t4 = [t for t in T if t["title"].startswith("Exposure choices for the strategy book")][0]
g50row = [rw for rw in t4["rows"] if rw[0].startswith("Development") and rw[1].startswith("Breadth")][0]
out["table4_G50_dev_row"] = g50row
t1 = T[0]
out["table1_row1"] = t1["rows"][0]
print(json.dumps(out, indent=1, default=float))
with open(f"{OUT}/v4_out.json", "w") as fh:
    json.dump(out, fh, indent=1, default=float)

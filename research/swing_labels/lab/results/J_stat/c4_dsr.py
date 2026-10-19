"""J_stat check 4: deflated-Sharpe style hurdle for the selected spec.
(1) cross-trial distribution of DEV excess t over R2_rel's DEV 50bp specs;
(2) effective number of independent trials from the eigenvalues of the correlation matrix of the DEV
    excess-vs-random daily series of R2_rel's long books (phase 0, liq2/liq5 x K x step x 23 models);
(3) expected max t under the null and a DSR-like probability for several N."""
import glob
import json
import os
import sys
import numpy as np
from scipy.stats import norm

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
R = f"{LAB}/results/R2_rel"
d = json.load(open(f"{R}/results.json"))
ts = []
for k, v in d.items():
    if k.startswith(("s5_full_", "s5_core_", "s5_avoid_", "s5_avoidc_", "s5_avoidcut_", "s5_quant_")) and isinstance(v, list):
        for rec in v:
            cfg = rec.get("cfg", {})
            if rec.get("period") == "dev" and cfg.get("cost_bps", 50) == 50 and rec.get("excess_daily_nw_t") is not None:
                ts.append(rec["excess_daily_nw_t"])
ts = np.array(ts)
print(f"R2_rel DEV 50bp spec records: {len(ts)}  t mean {ts.mean():.2f} sd {ts.std():.2f} max {ts.max():.2f} "
      f"share>2 {np.mean(ts>2):.2f} share>3 {np.mean(ts>3):.2f}")

# random bands (phase 0) from cache, keyed by desc
rb = {}
for f in glob.glob(f"{R}/rb_cache/*.npz"):
    z = np.load(f, allow_pickle=True)
    desc = json.loads(str(z["desc"]))
    rb[(desc.get("u"), desc.get("h"), desc.get("top_k"), desc.get("step"), desc.get("cost_bps"), desc.get("start"))] = z["daily"]
X, names = [], []
for f in sorted(glob.glob(f"{R}/daily_full_*.npz")):
    tag = os.path.basename(f)[len("daily_full_"):-4]
    h = int(tag.split("_")[0][1:])
    z = np.load(f)
    for k in z.files:
        if k.endswith("__dates") or not k.endswith("_c50_dev"):
            continue
        u, K, s = k.split("_")[0], int(k.split("_")[1][1:]), int(k.split("_")[2][1:])
        key = (u, h, K, s, 50, "2023-01-01")
        if key not in rb:
            continue
        x = z[k].astype(float)
        r = rb[key]
        n = min(len(x), len(r))
        X.append(x[:n] - r[:n])
        names.append(f"{tag}|{k}")
n = min(len(x) for x in X)
X = np.vstack([x[:n] for x in X])
C = np.corrcoef(X)
ev = np.clip(np.linalg.eigvalsh(C), 0, None)
m_eff_lj = float(np.sum((ev >= 1).astype(float) + (ev - np.floor(ev))))
m_eff_nyholt = float(1 + (len(ev) - 1) * (1 - np.var(ev, ddof=1) / len(ev)))
print(f"excess series used: {X.shape[0]} (of models x configs), days {n}")
print(f"mean pairwise corr {C[np.triu_indices_from(C,1)].mean():.3f}; M_eff Li-Ji {m_eff_lj:.1f}; Nyholt {m_eff_nyholt:.1f}; "
      f"ratio M_eff/N = {m_eff_lj/X.shape[0]:.3f}")

g = 0.5772156649


def emax(N):
    """Expected max of N iid standard normals (Bailey-Lopez de Prado approximation)."""
    return (1 - g) * norm.ppf(1 - 1 / N) + g * norm.ppf(1 - 1 / (N * np.e))


t_obs = {"PA NW20": 4.106, "PA NW120": 3.686, "phase-mean": 3.78}
print("\nN_eff | E[max Z] | hurdle sd1.0 | hurdle sd1.10 | hurdle sd1.37 | DSR(t=4.11, sd 1.10) | DSR(t=3.69, sd 1.10)")
for N in (10, 25, 50, 100, 150, 300, 477, 1000, 1630):
    em = emax(N)
    p1 = norm.cdf((4.106 - 1.10 * em) / 1.10)
    p2 = norm.cdf((3.686 - 1.10 * em) / 1.10)
    print(f"{N:5d} | {em:.2f} | {em:.2f} | {1.10*em:.2f} | {1.37*em:.2f} | {p1:.3f} | {p2:.3f}")
# empirical-variance DSR (Bailey & Lopez de Prado use the cross-trial variance of the estimated SR)
sd_emp = ts.std()
for N in (50, 150, 477, 1630):
    sr0 = sd_emp * emax(N)
    print(f"empirical cross-trial sd {sd_emp:.2f}: N={N} -> SR0 (t units) {sr0:.2f}, DSR(4.11) {norm.cdf((4.106-sr0)/1.10):.3f}")
# family-level evidence: how unlikely is it that MANY correlated relative specs show t>3 if all nulls?
fam = [k for k in d if k.startswith("s7_phase_h20_")]
print("\nphase-averaged DEV t of h=20 R2_rel models:")
for k in fam:
    v = d[k].get("K20_s5_dev", {})
    print(f"  {k[len('s7_phase_'):]:20s} PA t {v.get('phaseavg_nw_t', float('nan')):.2f}  excess {v.get('phaseavg_excess_ann', float('nan'))*100:.1f}%  "
          f"| 2026 PA t {d[k].get('K20_s5_hold', {}).get('phaseavg_nw_t', float('nan')):.2f} excess {d[k].get('K20_s5_hold', {}).get('phaseavg_excess_ann', float('nan'))*100:.1f}%")

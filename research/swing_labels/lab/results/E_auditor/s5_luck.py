#!/usr/bin/env python3
"""Stage 5: luck band and selection-shrinkage.
  A. verify fastsim == lablib.portfolio_sim
  B. iid random-pick baseline, 20 seeds (h=10, top_k=20, step=5, 50/80 bps), 2023-2025 + 2026 holdout + full
  C. same, but mask restricted to rows with a DEFINED label (what a model's OOS score implicitly does)
  D. persistent random tilt: one fixed random score per entity (concentrated, autocorrelated picks)
  E. 'factor zoo': each of the 53 lab features, both signs, as a ranking score (106 strategies);
     select best on 2023-2025, check 2026 (selection shrinkage)
  F. deflated-Sharpe hurdle table."""
import time

import numpy as np
import pandas as pd
from scipy.stats import norm, spearmanr

from common import L, save
from fastsim import Sim

t0 = time.time()
H, STEP, K = 10, 5, 20
P = L.load_panel(["date", "entity", "open", "close", "seg_break", "label_block"])
F = L.load_features(list(L.FEATURES) + ["elig_base", "fno_proxy"])
fw = L.Fwd(P)
sim = Sim(P, fw, H)
eb = F.elig_base.values
okh = fw.ok(H) & np.isfinite(fw.at(P.open.values, 1))
print("loaded", time.time() - t0, flush=True)
W = {"dev": ("2023-01-01", "2025-12-31"), "hold": ("2026-01-01", "2026-09-10"), "full": ("2023-01-01", "2026-09-10")}
R = {}

# ---- A. verification
a1 = L.portfolio_sim(None, eb, P, F, fw, H, step=STEP, top_k=K, random_seed=0, start=W["dev"][0], end=W["dev"][1])
b1 = sim.run(None, eb, "eb", step=STEP, top_k=K, random_seed=0, start=W["dev"][0], end=W["dev"][1])
sc = F.mom_20.values.astype(float)
a2 = L.portfolio_sim(sc, eb, P, F, fw, H, step=STEP, top_k=K, start=W["dev"][0], end=W["dev"][1])
b2 = sim.run(sc, eb, "eb", step=STEP, top_k=K, start=W["dev"][0], end=W["dev"][1])
R["verify"] = {"lablib_random0": {k: a1[k] for k in ("cagr", "sharpe", "trades")},
               "fast_random0": {k: b1[k] for k in ("cagr", "sharpe", "trades")},
               "lablib_mom20": {k: a2[k] for k in ("cagr", "sharpe", "trades")},
               "fast_mom20": {k: b2[k] for k in ("cagr", "sharpe", "trades")}}
print(R["verify"], flush=True)
assert abs(a1["cagr"] - b1["cagr"]) < 1e-12 and abs(a2["cagr"] - b2["cagr"]) < 1e-12


def summ(lst, key):
    x = np.array([r[key] for r in lst])
    return {"mean": float(x.mean()), "sd": float(x.std(ddof=1)), "p5": float(np.quantile(x, .05)),
            "p50": float(np.median(x)), "p95": float(np.quantile(x, .95)), "min": float(x.min()), "max": float(x.max())}


def band(mask, key, seeds=range(20), cost=50.0, win="dev", score_fn=None):
    out = []
    for sd in seeds:
        if score_fn is None:
            r = sim.run(None, mask, key, step=STEP, top_k=K, random_seed=sd, cost_bps=cost, start=W[win][0], end=W[win][1])
        else:
            r = sim.run(score_fn(sd), mask, key, step=STEP, top_k=K, cost_bps=cost, start=W[win][0], end=W[win][1])
        out.append(r)
    res = {k: summ(out, k) for k in ("cagr", "sharpe", "max_dd", "hit_rate", "mean_trade_net")}
    yrs = sorted({y for r in out for y in r["by_year"]})
    res["by_year_mean"] = {y: float(np.mean([r["by_year"].get(y, np.nan) for r in out])) for y in yrs}
    res["by_year_sd"] = {y: float(np.std([r["by_year"].get(y, np.nan) for r in out], ddof=1)) for y in yrs}
    # 3-seed-average spread (what the brief's baseline is)
    c = np.array([r["cagr"] for r in out])
    if len(c) >= 18:
        avg3 = c[:18].reshape(6, 3).mean(1)
        res["cagr_3seed_avg_values"] = avg3.tolist()
    res["n"] = len(out)
    return res, out


# ---- B. iid random
for win in ("dev", "hold", "full"):
    for cost in (50.0, 80.0):
        res, _ = band(eb, "eb", cost=cost, win=win)
        R[f"random_iid_{win}_{int(cost)}bps"] = res
        print(win, cost, res["cagr"], res["sharpe"], flush=True)
save("s5_luck_partial", R)

# ---- C. label-defined restriction (asymmetry that NaN OOS scores create)
for win in ("dev", "full"):
    res, _ = band(eb & okh, "eb_ok", win=win)
    R[f"random_iid_labelvalid_only_{win}_50bps"] = res
    print("labelvalid", win, res["cagr"], flush=True)
# picks that random baseline makes into rows whose label is undefined
bm = sim.run(None, eb, "eb", step=STEP, top_k=K, random_seed=0, start=W["full"][0], end=W["full"][1], return_cohorts=True)
pk = bm["picks"]
R["random_picks_label_undefined_share"] = float((~okh[pk]).mean())
R["random_picks_label_undefined_mean_ret"] = float(np.nanmean(sim.tr_ret_long[pk[~okh[pk]]])) if (~okh[pk]).any() else None

# ---- D. persistent entity-level random score
ent_codes = pd.factorize(P.entity.values)[0]


def ent_score(seed):
    u = np.random.default_rng(1000 + seed).random(ent_codes.max() + 1)
    return u[ent_codes]


for win in ("dev", "hold"):
    res, _ = band(eb, "eb", win=win, score_fn=ent_score)
    R[f"random_persistent_entity_{win}_50bps"] = res
    print("persistent", win, res["cagr"], res["sharpe"], flush=True)
save("s5_luck_partial", R)

# ---- E. factor zoo
zoo = []
for f in L.FEATURES:
    x = F[f].values.astype("float64")
    for sgn in (1, -1):
        rec = {"feature": f, "sign": sgn}
        for win in ("dev", "hold"):
            r = sim.run(sgn * x, eb, "eb", step=STEP, top_k=K, cost_bps=50.0, start=W[win][0], end=W[win][1])
            rec[f"{win}_cagr"] = r["cagr"]
            rec[f"{win}_sharpe"] = r["sharpe"]
            rec[f"{win}_maxdd"] = r["max_dd"]
            if win == "dev":
                rec.update({f"dev_{y}": v for y, v in r["by_year"].items()})
        zoo.append(rec)
Z = pd.DataFrame(zoo).sort_values("dev_sharpe", ascending=False)
Z.to_csv("factor_zoo.csv", index=False)
rho, pv = spearmanr(Z.dev_sharpe, Z.hold_sharpe)
best = Z.iloc[0]
top5 = Z.head(5)
R["factor_zoo"] = {"n_strategies": int(len(Z)),
                   "dev_cagr_quantiles": Z.dev_cagr.quantile([.05, .5, .9, .95, 1]).to_dict(),
                   "dev_sharpe_quantiles": Z.dev_sharpe.quantile([.05, .5, .9, .95, 1]).to_dict(),
                   "best_on_dev": best.to_dict(),
                   "top5_on_dev": top5[["feature", "sign", "dev_cagr", "dev_sharpe", "hold_cagr", "hold_sharpe"]].to_dict("records"),
                   "top5_dev_sharpe_mean": float(top5.dev_sharpe.mean()), "top5_hold_sharpe_mean": float(top5.hold_sharpe.mean()),
                   "spearman_dev_vs_hold_sharpe": float(rho), "spearman_p": float(pv),
                   "hold_rank_of_dev_best": int((Z.hold_sharpe > best.hold_sharpe).sum() + 1),
                   "hold_cagr_quantiles": Z.hold_cagr.quantile([.05, .5, .95]).to_dict()}
print(R["factor_zoo"]["top5_on_dev"], rho, flush=True)

# ---- F. deflated-Sharpe hurdle
sd_iid = R["random_iid_dev_50bps"]["sharpe"]["sd"]
mu_iid = R["random_iid_dev_50bps"]["sharpe"]["mean"]
sd_per = R["random_persistent_entity_dev_50bps"]["sharpe"]["sd"]
g = 0.5772156649
tab = {}
for N in (1, 5, 10, 20, 50, 100, 300):
    if N == 1:
        z = norm.ppf(0.95)
    else:
        z = (1 - g) * norm.ppf(1 - 1 / N) + g * norm.ppf(1 - 1 / (N * np.e))
    tab[N] = {"expected_max_excess_sharpe_iid_null": float(sd_iid * z), "hurdle_sharpe_iid": float(mu_iid + sd_iid * z),
              "expected_max_excess_sharpe_persistent_null": float(sd_per * z),
              "hurdle_sharpe_persistent": float(R["random_persistent_entity_dev_50bps"]["sharpe"]["mean"] + sd_per * z)}
R["deflated_sharpe_hurdles_dev_2023_2025"] = tab
R["benchmark_dev"] = L.benchmark(P, start=W["dev"][0], end=W["dev"][1])
R["benchmark_hold"] = L.benchmark(P, start=W["hold"][0], end=W["hold"][1])
R["benchmark_full"] = L.benchmark(P, start=W["full"][0], end=W["full"][1])
save("s5_luck", R)
print("done", time.time() - t0, flush=True)

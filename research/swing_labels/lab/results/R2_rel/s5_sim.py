"""Stage 5: investability with L.Sim (daily MTM, staggered sleeves, next-open entry, half cost in/out,
slot sizing, fixed calendar) vs the horizon-matched random baseline on the same mask (5 seeds) —
identical maths to L.Sim.compare, but random bands are cached on disk (they do not depend on the score).

Usage: python3 s5_sim.py <grid> tag1 [tag2 ...]
grids
  full  : long top-K, K {10,20,30,50} x step {5,10} x cost {50,80,130} x {dev,hold} x {liq2,liq5}
  core  : long top-K, K {20,50} x step {5,10} x cost {50,80} x {dev,hold} x {liq2}  (+ liq5 K20 s5 50)
  avoid : equal-weight all names except the model's bottom 30% (select_quantile=(0.3,1), sizing equal)
          vs random-70% (baseline) and vs universe EW (0,1); step {5,10} x cost {50,80,130} x {dev,hold}
          x {liq2,liq5}
  avoidc: avoid with step 5 x cost {50,80} x {dev,hold} x liq2
  quant : equal-weight top-decile (0.9,1) / top-quintile (0.8,1) / top-30% (0.7,1); step 5; 50/80; dev/hold
"""
import hashlib
import json
import os
import sys
import time

import numpy as np

from common import OUT, L, save

grid, tags = sys.argv[1], sys.argv[2:]
t0 = time.time()
P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["atr_pct"])
fw = L.Fwd(P)
S = L.Sim(P, F, fw)
del F
meta = np.load(f"{OUT}/meta.npz")
MASKS = {"liq2": meta["E"], "liq5": meta["E"] & meta["liq5"]}
PERIODS = {"dev": dict(start=L.DEV[0], end_exit=L.DEV[1]), "hold": dict(start="2026-01-01", end_exit=None)}
RBDIR = os.path.join(OUT, "rb_cache")
os.makedirs(RBDIR, exist_ok=True)
SEEDS = (1, 2, 3, 4, 5)
print("sim ready", round(time.time() - t0, 1), flush=True)


def _key(univ, h, kw):
    s = json.dumps({"u": univ, "h": h, **{k: (list(v) if isinstance(v, tuple) else v) for k, v in sorted(kw.items())}},
                   sort_keys=True)
    return hashlib.md5(s.encode()).hexdigest()[:16], s


def random_band(univ, h, kw):
    k, desc = _key(univ, h, kw)
    fn = os.path.join(RBDIR, f"{k}.npz")
    if os.path.exists(fn):
        z = np.load(fn, allow_pickle=True)
        return json.loads(str(z["summary"])), z["daily"]
    rb = S.random_band(MASKS[univ], h, seeds=SEEDS, **kw)
    summ = {kk: v for kk, v in rb.items() if not kk.startswith("_")}
    summ["by_year_mean"] = {str(a): b for a, b in summ["by_year_mean"].items()}
    tmp = fn + ".tmp.npz"
    np.savez(tmp, summary=json.dumps(summ), daily=rb["_daily_ret_mean"], desc=desc)
    os.replace(tmp, fn)
    return summ, rb["_daily_ret_mean"]


def ew_ref(univ, h, kw):
    """universe equal-weight book (all names), cached the same way."""
    kw2 = dict(kw)
    kw2["select_quantile"] = (0.0, 1.0)
    k, desc = _key(univ + "_EW", h, kw2)
    fn = os.path.join(RBDIR, f"{k}.npz")
    if os.path.exists(fn):
        z = np.load(fn, allow_pickle=True)
        return json.loads(str(z["summary"])), z["daily"]
    ones = np.ones(S.n)
    st = S.run(ones, MASKS[univ], h, **kw2)
    summ = {kk: v for kk, v in st.items() if not kk.startswith("_") and kk != "params"}
    summ["by_year"] = {str(a): b for a, b in summ["by_year"].items()}
    tmp = fn + ".tmp.npz"
    np.savez(tmp, summary=json.dumps(summ), daily=st["_daily_ret"], desc=desc)
    os.replace(tmp, fn)
    return summ, st["_daily_ret"]


def compare(score, univ, h, kw, with_ew=False):
    st = S.run(score, MASKS[univ], h, **kw)
    rb, rbd = random_band(univ, h, kw)
    diff = st["_daily_ret"] - rbd
    res = {k: v for k, v in st.items() if not k.startswith("_") and k != "params"}
    res["cfg"] = {"univ": univ, "h": h, **{k: v for k, v in kw.items()}}
    res["random"] = rb
    res["excess_cagr_vs_random"] = st["cagr"] - rb["cagr_mean"]
    res["excess_daily_nw_t"] = L.nw_t(diff, lag=h)
    res["excess_ann_return"] = float(diff.mean() * 252)
    if with_ew:
        ew, ewd = ew_ref(univ, h, kw)
        d2 = st["_daily_ret"] - ewd
        res["ew"] = {"cagr": ew["cagr"], "sharpe": ew["sharpe"], "max_dd": ew["max_dd"], "by_year": ew["by_year"]}
        res["excess_cagr_vs_ew"] = st["cagr"] - ew["cagr"]
        res["excess_vs_ew_nw_t"] = L.nw_t(d2, lag=h)
    return res, st["_daily_ret"], st["_dates"]


def configs(h):
    steps = (5, 10)
    out = []
    if grid == "full":
        for univ in ("liq2", "liq5"):
            for K in (10, 20, 30, 50):
                for step in steps:
                    for cost in (50, 80, 130):
                        for per in ("dev", "hold"):
                            out.append((univ, dict(top_k=K, step=step, cost_bps=cost, **PERIODS[per]), per, False))
    elif grid == "core":
        for K in (20, 50):
            for step in steps:
                for cost in (50, 80):
                    for per in ("dev", "hold"):
                        out.append(("liq2", dict(top_k=K, step=step, cost_bps=cost, **PERIODS[per]), per, False))
        for per in ("dev", "hold"):
            out.append(("liq5", dict(top_k=20, step=5, cost_bps=50, **PERIODS[per]), per, False))
    elif grid in ("avoid", "avoidc"):
        univs = ("liq2", "liq5") if grid == "avoid" else ("liq2",)
        stp = steps if grid == "avoid" else (5,)
        costs = (50, 80, 130) if grid == "avoid" else (50, 80)
        for univ in univs:
            for step in stp:
                for cost in costs:
                    for per in ("dev", "hold"):
                        out.append((univ, dict(step=step, cost_bps=cost, select_quantile=(0.3, 1.0), sizing="equal",
                                               **PERIODS[per]), per, True))
    elif grid == "avoidcut":
        for q in ((0.1, 1.0), (0.2, 1.0), (0.3, 1.0), (0.5, 1.0)):
            for cost in (50,):
                for per in ("dev", "hold"):
                    out.append(("liq2", dict(step=5, cost_bps=cost, select_quantile=q, sizing="equal",
                                             **PERIODS[per]), per, True))
    elif grid == "quant":
        for q in ((0.9, 1.0), (0.8, 1.0), (0.7, 1.0)):
            for cost in (50, 80):
                for per in ("dev", "hold"):
                    out.append(("liq2", dict(step=5, cost_bps=cost, select_quantile=q, sizing="equal",
                                             **PERIODS[per]), per, True))
    return out


for tag in tags:
    h = int(tag.split("_")[0][1:])
    sc = np.load(f"{OUT}/wf_{tag}.npz")["score"].astype("float64")
    recs = []
    keep = {}
    for univ, kw, per, with_ew in configs(h):
        r_, daily, dts = compare(sc, univ, h, kw, with_ew)
        r_["period"] = per
        recs.append(r_)
        tagc = f"{univ}_K{kw.get('top_k', 'q')}_s{kw['step']}_c{kw['cost_bps']}_{per}" + \
            (f"_q{kw['select_quantile'][0]}" if "select_quantile" in kw else "")
        if kw["cost_bps"] == 50:
            keep[tagc] = daily.astype(np.float32)
            keep[tagc + "__dates"] = dts.astype("datetime64[D]").astype(str)
        print(tag, tagc, f"cagr {r_['cagr']:.3f} rnd {r_['random']['cagr_mean']:.3f} "
              f"ex {r_['excess_cagr_vs_random']:+.3f} t {r_['excess_daily_nw_t']:.2f}",
              (f"ew {r_['ew']['cagr']:.3f} t_ew {r_['excess_vs_ew_nw_t']:.2f}" if with_ew else ""),
              round(time.time() - t0, 1), flush=True)
    save(f"s5_{grid}_{tag}", recs)
    np.savez_compressed(f"{OUT}/daily_{grid}_{tag}.npz", **keep)
print("all done", round(time.time() - t0, 1), flush=True)

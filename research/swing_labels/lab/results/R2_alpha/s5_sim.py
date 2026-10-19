"""Stage 5: investability with L.Sim (daily MTM, staggered sleeves, next-open entry, half cost in/out,
slot sizing, fixed trading-day calendar), h = 20, mask U = elig_base.

Every book is compared with the horizon-matched 5-seed random baseline on the same mask and params
(identical maths to L.Sim.compare; bands cached on disk because they do not depend on the score).
Phase averaging: the signal calendar is shifted by p = 0..step-1 trading days; the phase-averaged book
is the mean of the p daily return series (= a daily-staggered book). Phase 0 reproduces S.compare.
Primary statistic: phase-averaged excess over random, annualised (mean daily diff x 252) with
Newey-West t (lag 20). Phase-0 CAGR/excess/NW t are also reported (S.compare convention).

Usage: python3 s5_sim.py <grid> tag1 [tag2 ...]
  main  : long top-20 step 5 at 50/80 bps + AVOID overlay (EW all names except the model's bottom 30%,
          select_quantile=(0.3,1), sizing equal) vs random-70% and vs universe EW; dev & hold.
  grid  : long top-K, K in {10,20,30,50} x step in {5,10}, 50 bps (+80 bps for K20 s10, K50 s10).
  liq5  : main long book on U & liq5 (score trained on U).
Daily phase-averaged series are stored in daily_<grid>_<tag>.npz for paired tests / attribution.
"""
import hashlib
import json
import os
import sys
import time

import numpy as np
import pandas as pd

from common import OUT, L, H, save

grid, tags = sys.argv[1], sys.argv[2:]
t0 = time.time()
P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["atr_pct"])
fw = L.Fwd(P)
S = L.Sim(P, F, fw)
del F
Z = np.load(f"{OUT}/labels.npz")
MASKS = {"U": Z["U"], "U5": Z["U"] & Z["liq5"]}
PER = {"dev": (L.DEV[0], L.DEV[1]), "hold": ("2026-01-01", None)}
RBDIR = os.path.join(OUT, "rb_cache")
os.makedirs(RBDIR, exist_ok=True)
SEEDS = (1, 2, 3, 4, 5)
print("sim ready", round(time.time() - t0, 1), flush=True)


def start_of(per, phase):
    g0 = int(np.searchsorted(S.cal, np.datetime64(PER[per][0])))
    return str(S.cal[g0 + phase])


def _key(*parts):
    s = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.md5(s.encode()).hexdigest()[:16], s


def random_band(univ, per, phase, kw):
    k, desc = _key("rb", univ, per, phase, H, sorted(kw.items()))
    fn = os.path.join(RBDIR, f"{k}.npz")
    if os.path.exists(fn):
        z = np.load(fn, allow_pickle=True)
        return json.loads(str(z["summary"])), pd.Series(z["daily"], index=pd.DatetimeIndex(z["dates"]))
    rb = S.random_band(MASKS[univ], H, seeds=SEEDS, start=start_of(per, phase), end_exit=PER[per][1], **kw)
    summ = {kk: v for kk, v in rb.items() if not kk.startswith("_")}
    summ["by_year_mean"] = {str(a): b for a, b in summ["by_year_mean"].items()}
    tmp = fn + ".tmp.npz"
    np.savez(tmp, summary=json.dumps(summ), daily=rb["_daily_ret_mean"], dates=rb["_dates"], desc=desc)
    os.replace(tmp, fn)
    return summ, pd.Series(rb["_daily_ret_mean"], index=pd.DatetimeIndex(rb["_dates"]))


def ew_book(univ, per, phase, kw):
    kw2 = dict(kw)
    kw2["select_quantile"] = (0.0, 1.0)
    kw2["sizing"] = "equal"
    k, desc = _key("ew", univ, per, phase, H, sorted(kw2.items()))
    fn = os.path.join(RBDIR, f"{k}.npz")
    if os.path.exists(fn):
        z = np.load(fn, allow_pickle=True)
        return json.loads(str(z["summary"])), pd.Series(z["daily"], index=pd.DatetimeIndex(z["dates"]))
    st = S.run(np.ones(S.n), MASKS[univ], H, start=start_of(per, phase), end_exit=PER[per][1], **kw2)
    summ = {kk: v for kk, v in st.items() if not kk.startswith("_") and kk != "params"}
    summ["by_year"] = {str(a): b for a, b in summ["by_year"].items()}
    tmp = fn + ".tmp.npz"
    np.savez(tmp, summary=json.dumps(summ), daily=st["_daily_ret"], dates=st["_dates"], desc=desc)
    os.replace(tmp, fn)
    return summ, pd.Series(st["_daily_ret"], index=pd.DatetimeIndex(st["_dates"]))


def cagr_of(daily):
    eq = np.cumprod(1 + daily.values)
    yrs = max((daily.index[-1] - daily.index[0]).days / 365.25, 1e-9)
    return float(eq[-1] ** (1 / yrs) - 1)


def maxdd_of(daily):
    eq = np.cumprod(1 + daily.values)
    return float((eq / np.maximum.accumulate(eq) - 1).min())


def by_year(daily):
    return {int(y): float(np.prod(1 + g.values) - 1) for y, g in daily.groupby(daily.index.year)}


def evaluate(score, univ, per, kw, with_ew=False):
    """phase-0 S.compare-equivalent stats + phase-averaged excess."""
    step = kw.get("step", 5)
    strat, rand, ew = [], [], []
    rec = {}
    phase_ex = []
    for ph in range(step):
        st = S.run(score, MASKS[univ], H, start=start_of(per, ph), end_exit=PER[per][1], **kw)
        sd = pd.Series(st["_daily_ret"], index=pd.DatetimeIndex(st["_dates"]))
        rb, rbd = random_band(univ, per, ph, kw)
        strat.append(sd)
        rand.append(rbd)
        phase_ex.append(st["cagr"] - rb["cagr_mean"])
        if with_ew:
            ews, ewd = ew_book(univ, per, ph, kw)
            ew.append(ewd)
        if ph == 0:
            diff = st["_daily_ret"] - rbd.values
            rec.update({k: v for k, v in st.items() if not k.startswith("_") and k != "params"})
            rec["by_year"] = {str(a): b for a, b in st["by_year"].items()}
            rec["random"] = rb
            rec["excess_cagr_vs_random"] = st["cagr"] - rb["cagr_mean"]
            rec["excess_daily_nw_t"] = L.nw_t(diff, lag=H)
            rec["excess_ann_return"] = float(diff.mean() * 252)
            if with_ew:
                d2 = st["_daily_ret"] - ewd.values
                rec["ew"] = {"cagr": ews["cagr"], "sharpe": ews["sharpe"], "max_dd": ews["max_dd"],
                             "by_year": ews["by_year"]}
                rec["excess_cagr_vs_ew"] = st["cagr"] - ews["cagr"]
                rec["excess_vs_ew_nw_t"] = L.nw_t(d2, lag=H)
    sa = pd.concat(strat, axis=1, join="inner").mean(axis=1)
    ra = pd.concat(rand, axis=1, join="inner").mean(axis=1)
    j = pd.concat([sa, ra], axis=1, join="inner")
    d = j.iloc[:, 0] - j.iloc[:, 1]
    rec["pa"] = {"n_phases": step, "cagr": cagr_of(j.iloc[:, 0]), "random_cagr": cagr_of(j.iloc[:, 1]),
                 "excess_ann": float(d.mean() * 252), "excess_nw_t": L.nw_t(d.values, lag=H),
                 "max_dd": maxdd_of(j.iloc[:, 0]), "sharpe": float(j.iloc[:, 0].mean() / j.iloc[:, 0].std() * np.sqrt(252)),
                 "by_year": by_year(j.iloc[:, 0]), "random_by_year": by_year(j.iloc[:, 1]),
                 "phase_excess_cagr_min": float(np.min(phase_ex)), "phase_excess_cagr_max": float(np.max(phase_ex)),
                 "phase_excess_pos_share": float(np.mean(np.array(phase_ex) > 0))}
    out_series = {"strat": j.iloc[:, 0], "rand": j.iloc[:, 1]}
    if with_ew:
        ea = pd.concat(ew, axis=1, join="inner").mean(axis=1)
        j2 = pd.concat([sa, ea], axis=1, join="inner")
        d2 = j2.iloc[:, 0] - j2.iloc[:, 1]
        rec["pa"]["ew_cagr"] = cagr_of(j2.iloc[:, 1])
        rec["pa"]["excess_vs_ew_ann"] = float(d2.mean() * 252)
        rec["pa"]["excess_vs_ew_nw_t"] = L.nw_t(d2.values, lag=H)
        out_series["ew"] = j2.iloc[:, 1]
    return rec, out_series


def configs():
    out = []
    if grid == "main":
        for cost in (50, 80):
            for per in ("dev", "hold"):
                out.append((f"K20_s5_c{cost}_{per}", "U", per, dict(top_k=20, step=5, cost_bps=cost), False))
                out.append((f"avoid30_s5_c{cost}_{per}", "U", per,
                            dict(step=5, cost_bps=cost, select_quantile=(0.3, 1.0), sizing="equal"), True))
    elif grid == "grid":
        for K in (10, 20, 30, 50):
            for step in (5, 10):
                for per in ("dev", "hold"):
                    costs = (50, 80) if (step == 10 and K in (20, 50)) else (50,)
                    for cost in costs:
                        if K == 20 and step == 5:
                            continue      # already in main
                        out.append((f"K{K}_s{step}_c{cost}_{per}", "U", per,
                                    dict(top_k=K, step=step, cost_bps=cost), False))
    elif grid == "liq5":
        for per in ("dev", "hold"):
            out.append((f"liq5_K20_s5_c50_{per}", "U5", per, dict(top_k=20, step=5, cost_bps=50), False))
            out.append((f"liq5_avoid30_s5_c50_{per}", "U5", per,
                        dict(step=5, cost_bps=50, select_quantile=(0.3, 1.0), sizing="equal"), True))
    return out


for tag in tags:
    sc = np.load(f"{OUT}/wf_{tag}.npz")["score"].astype("float64")
    recs, daily = {}, {}
    for name, univ, per, kw, with_ew in configs():
        rec, ser = evaluate(sc, univ, per, kw, with_ew)
        rec["cfg"] = {"univ": univ, "per": per, **{k: (list(v) if isinstance(v, tuple) else v) for k, v in kw.items()}}
        recs[name] = rec
        for k, v in ser.items():
            daily[f"{name}|{k}"] = v
        pa = rec["pa"]
        print(f"{tag} {name}: p0 cagr {rec['cagr']:.3f} ex {rec['excess_cagr_vs_random']:+.3f} t {rec['excess_daily_nw_t']:.2f}"
              f" | PA cagr {pa['cagr']:.3f} rnd {pa['random_cagr']:.3f} ex/yr {pa['excess_ann']:+.3f} t {pa['excess_nw_t']:.2f}"
              f" ph[{pa['phase_excess_cagr_min']:+.3f},{pa['phase_excess_cagr_max']:+.3f}]"
              + (f" vsEW {pa['excess_vs_ew_ann']:+.3f} t {pa['excess_vs_ew_nw_t']:.2f}" if with_ew else ""),
              flush=True)
    save(f"s5_{grid}_{tag}", recs)
    np.savez_compressed(f"{OUT}/daily_{grid}_{tag}.npz",
                        **{k.replace("|", "__"): v.values for k, v in daily.items()},
                        **{k.replace("|", "__") + "__dates": v.index.values.astype("datetime64[D]").astype(str)
                           for k, v in daily.items()})
    print("done", tag, round(time.time() - t0, 1), flush=True)
print("total", round(time.time() - t0, 1))

"""Stage 4 (devil): perturbations of the selected book (self-built model 'main').
Usage: python3 s4_perturb.py <part> [<part> ...]
  halves  : entity halves A/B (md5 hash of entity), evaluated with the full model, K=20 and K=10
  cross   : models trained on one entity half only (s2 trainA/trainB), scored on the OTHER half
  lag     : extra signal lag of 1/2/3/5/10 trading days (score of t-L traded at open t+1)
  quarters: quarter-by-quarter excess of the phase-averaged book (vs random and vs EW)
  grid    : top_k x step grid, phase-averaged, 50 bps (+ cost sweep for K20 s5)
  univ    : sub-universes liq5 and fno_proxy (re-ranked inside the sub-universe)
  seeds   : LightGBM seed perturbation (s2 seed1/seed2) vs main
All phase-averaged over `step` entry phases unless stated; random baseline = 5-seed horizon-matched on
the same mask.
"""
import sys

import numpy as np
import pandas as pd

from common import OUT, L, PER, log, save, load_sim, compare, phase_avg, entity_half, short

parts = sys.argv[1:]
P, F, fw, S, E = load_sim()
H = 20
sc = np.load(f"{OUT}/wf_main.npz")["score"].astype("float64")
KEYS = ("pa_cagr", "pa_random_cagr", "pa_excess_ann", "pa_nw_t", "phase_excess_min", "phase_excess_max", "pa_maxdd")


def pa(score, mask, tag, kw, per, with_ew=False):
    r, sm, rm, em = phase_avg(S, score, mask, tag, H, kw, per, with_ew=with_ew)
    return r, sm, rm, em


if "halves" in parts or "cross" in parts:
    half = entity_half(P["entity"].values)
    MA, MB = E & (half == 0), E & (half == 1)

if "halves" in parts:
    out = {"share_A_elig_rows": float(MA.sum() / E.sum())}
    for nm, m in (("A", MA), ("B", MB), ("full", E)):
        for K in (10, 20):
            for per in PER:
                r, *_ = pa(sc, m, f"half{nm}" if nm != "full" else "liq2", dict(top_k=K, step=5, cost_bps=50), per)
                out[f"{nm}_K{K}_{per}"] = {k: r[k] for k in KEYS}
                log("halves", nm, K, per, short(out[f"{nm}_K{K}_{per}"]))
    save("s4_halves_eval", out)

if "cross" in parts:
    out = {}
    sA = np.load(f"{OUT}/wf_trainA.npz")["score"].astype("float64")   # trained on A only
    sB = np.load(f"{OUT}/wf_trainB.npz")["score"].astype("float64")   # trained on B only
    for nm, m, s_out, s_in in (("B_scored_by_trainA", MB, sA, sB), ("A_scored_by_trainB", MA, sB, sA)):
        for K in (10, 20):
            for per in PER:
                tag = "halfB" if nm.startswith("B") else "halfA"
                r_out, *_ = pa(s_out, m, tag, dict(top_k=K, step=5, cost_bps=50), per)
                r_in, *_ = pa(s_in, m, tag, dict(top_k=K, step=5, cost_bps=50), per)
                r_full, *_ = pa(sc, m, tag, dict(top_k=K, step=5, cost_bps=50), per)
                out[f"{nm}_K{K}_{per}"] = {"out_of_entity": {k: r_out[k] for k in KEYS},
                                           "in_entity_half_model": {k: r_in[k] for k in KEYS},
                                           "full_model": {k: r_full[k] for k in KEYS}}
                log("cross", nm, K, per, "out", short(r_out["pa_excess_ann"]), short(r_out["pa_nw_t"]),
                    "in", short(r_in["pa_excess_ann"]), "full", short(r_full["pa_excess_ann"]))
    # IC of out-of-entity scores vs label
    pct = np.load(f"{OUT}/label_h20_neumom.npz")["pct"]
    for nm, m, s_out in (("B_by_trainA", MB, sA), ("A_by_trainB", MA, sB)):
        xm = L.xs_metrics(s_out, pct, m, P, H)
        out[f"ic_{nm}"] = {k: v for k, v in xm.items() if "ic" in k}
        xm2 = L.xs_metrics(sc, pct, m, P, H)
        out[f"ic_{nm}_fullmodel_same_rows"] = {k: v for k, v in xm2.items() if "ic" in k}
        log("ic", nm, short(out[f"ic_{nm}"]), "full", short(out[f"ic_{nm}_fullmodel_same_rows"]))
    save("s4_cross_entity", out)

if "lag" in parts:
    out = {}
    for lag in (0, 1, 2, 3, 5, 10):
        s_l = sc if lag == 0 else fw.at(sc, -lag)
        m = E & np.isfinite(s_l)
        for per in PER:
            r, *_ = pa(s_l, m, f"lag{lag}", dict(top_k=20, step=5, cost_bps=50), per)
            out[f"lag{lag}_{per}"] = {k: r[k] for k in KEYS}
            log("lag", lag, per, short(out[f"lag{lag}_{per}"]))
    save("s4_signal_lag", out)

if "quarters" in parts:
    z = np.load(f"{OUT}/pa_series_main.npz")
    out = {}
    for per in PER:
        idx = pd.DatetimeIndex(z[f"{per}_strat__dates"])
        s_, r_, e_ = (pd.Series(z[f"{per}_{k}"], index=idx) for k in ("strat", "rand", "ew"))
        q = pd.DataFrame({"ex_r": s_ - r_, "ex_e": s_ - e_, "s": s_, "r": r_, "e": e_})
        g = q.groupby(q.index.to_period("Q"))
        tab = pd.DataFrame({"days": g.size(), "excess_vs_random_sum": g.ex_r.sum(), "excess_vs_ew_sum": g.ex_e.sum(),
                            "strat_ret": g.s.apply(lambda x: np.prod(1 + x) - 1),
                            "random_ret": g.r.apply(lambda x: np.prod(1 + x) - 1),
                            "ew_ret": g.e.apply(lambda x: np.prod(1 + x) - 1)})
        tab.index = tab.index.astype(str)
        tot = tab.excess_vs_random_sum.sum()
        srt = tab.excess_vs_random_sum.sort_values(ascending=False)
        out[per] = {"table": tab.round(4).to_dict(orient="index"),
                    "n_quarters": int(len(tab)), "pos_vs_random": int((tab.excess_vs_random_sum > 0).sum()),
                    "pos_vs_ew": int((tab.excess_vs_ew_sum > 0).sum()),
                    "share_of_total_from_best_quarter": float(srt.iloc[0] / tot) if tot else None,
                    "share_of_total_from_best_2": float(srt.iloc[:2].sum() / tot) if tot else None,
                    "excess_ann_ex_best_quarter": float((q.ex_r.sum() - srt.iloc[0]) / (len(q) - tab.loc[srt.index[0], 'days']) * 252),
                    "median_quarter_excess": float(tab.excess_vs_random_sum.median()),
                    "worst_quarter": [str(tab.excess_vs_random_sum.idxmin()), float(tab.excess_vs_random_sum.min())]}
        log("quarters", per, short({k: v for k, v in out[per].items() if k != "table"}))
        log(tab.round(4).to_string())
    # monthly hit rate of excess
    for per in PER:
        idx = pd.DatetimeIndex(z[f"{per}_strat__dates"])
        ex = pd.Series(z[f"{per}_strat"] - z[f"{per}_rand"], index=idx)
        mo = ex.groupby(ex.index.to_period("M")).sum()
        out[per]["months_pos_share"] = float((mo > 0).mean())
        out[per]["n_months"] = int(len(mo))
        out[per]["monthly_excess_mean"] = float(mo.mean())
        out[per]["monthly_t"] = float(mo.mean() / (mo.std() / np.sqrt(len(mo))))
    save("s4_quarters", out)

if "grid" in parts:
    out = {}
    for K in (5, 10, 20, 30, 50, 100, 200):
        for step in (1, 5, 10, 20):
            for per in PER:
                r, *_ = pa(sc, E, "liq2", dict(top_k=K, step=step, cost_bps=50), per)
                out[f"K{K}_s{step}_{per}"] = {k: r[k] for k in KEYS}
                log("grid", K, step, per, short(out[f"K{K}_s{step}_{per}"]))
    for cost in (30, 50, 80, 130, 200):
        for per in PER:
            r, *_ = pa(sc, E, "liq2", dict(top_k=20, step=5, cost_bps=cost), per)
            out[f"cost{cost}_K20_s5_{per}"] = {k: r[k] for k in KEYS}
            log("cost", cost, per, short(out[f"cost{cost}_K20_s5_{per}"]))
    save("s4_grid", out)

if "univ" in parts:
    F2 = L.load_features(["elig_liq5", "fno_proxy"])
    out = {}
    for nm, m in (("liq5", E & F2["elig_liq5"].values.astype(bool)), ("fno", E & F2["fno_proxy"].values.astype(bool))):
        for K in (10, 20):
            for per in PER:
                r, *_ = pa(sc, m, nm, dict(top_k=K, step=5, cost_bps=50), per, with_ew=True)
                out[f"{nm}_K{K}_{per}"] = {k: r[k] for k in KEYS + ("pa_ew_cagr", "pa_excess_vs_ew_ann", "pa_vs_ew_nw_t")}
                log("univ", nm, K, per, short(out[f"{nm}_K{K}_{per}"]))
    save("s4_universes", out)

if "seeds" in parts:
    out = {}
    pct = np.load(f"{OUT}/label_h20_neumom.npz")["pct"]
    for job in ("main", "seed1", "seed2"):
        s_ = np.load(f"{OUT}/wf_{job}.npz")["score"].astype("float64")
        for per in PER:
            r, *_ = pa(s_, E, "liq2", dict(top_k=20, step=5, cost_bps=50), per)
            out[f"{job}_{per}"] = {k: r[k] for k in KEYS}
            log("seed", job, per, short(out[f"{job}_{per}"]))
        if job != "main":
            b = np.isfinite(s_) & np.isfinite(sc)
            out[f"{job}_score_corr_with_main"] = float(np.corrcoef(s_[b], sc[b])[0, 1])
            # top-20 overlap per date (DEV)
            d = P["date"].values.astype("datetime64[D]")
            ii = np.flatnonzero(E & b & (d >= np.datetime64("2023-01-01")))
            df = pd.DataFrame({"d": d[ii], "a": sc[ii], "b": s_[ii]})
            df["ra"] = df.groupby("d").a.rank(ascending=False)
            df["rb"] = df.groupby("d").b.rank(ascending=False)
            ov = df.groupby("d").apply(lambda g: ((g.ra <= 20) & (g.rb <= 20)).sum() / 20.0, include_groups=False)
            out[f"{job}_top20_overlap_mean"] = float(ov.mean())
    save("s4_seeds", out)
log("done", parts)

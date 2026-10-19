"""Stage 6 (devil): boring-explanation test. Can a simple factor tilt from the same universe reproduce
the selected book's edge?
  (a) top-20 factor tilts (K=20, step 5, 50 bps, phase-averaged, same Sim and random baseline):
      low-vol, low idio-vol, short-term reversal (5d, 20d), small size, large size, 12-1 momentum,
      low beta, high delivery %, near 52w high, and an equal-weight rank composite of the four asked for
      (low-vol + reversal + small + momentum);
  (b) the model's own linear factor projection (per-date OLS of the score on 9 characteristic ranks) and
      its residual, each used as a score;
  (c) regression of the model's daily excess on quintile long-short factor returns (EW, h=20, step 5,
      phase-averaged, gross) -> alpha and NW t;
  (d) single-feature scan: every one of the 52 model features as a top-20 score, both signs;
  (e) characteristic profile of the model's picks (mean same-date percentile).
Usage: python3 s6_boring.py [a b c d e]
"""
import sys

import numpy as np
import pandas as pd

from common import OUT, L, PER, log, save, load_sim, phase_avg, short

parts = sys.argv[1:] or ["a", "b", "c", "d", "e"]
P, F, fw, S, E = load_sim()
H = 20
FC = ["vol_20", "idio_vol_60", "mom_5", "mom_20", "log_turn20", "mom_12_1", "beta_60", "deliv_pct", "hi52_dist"]
X = L.load_features(sorted(set(L.FEATURES + FC)))
d = P["date"].values.astype("datetime64[D]")
sc = np.load(f"{OUT}/wf_main.npz")["score"].astype("float64")
KW = dict(top_k=20, step=5, cost_bps=50)
KEYS = ("pa_cagr", "pa_random_cagr", "pa_excess_ann", "pa_nw_t", "pa_maxdd")


def xs_rank(v, mask):
    s = pd.Series(np.where(mask & np.isfinite(v), v, np.nan))
    return s.groupby(d).rank(pct=True).values


R = {c: xs_rank(X[c].values.astype("float64"), E) for c in FC}
TILTS = {"low_vol": 1 - R["vol_20"], "low_idio_vol": 1 - R["idio_vol_60"], "reversal_5d": 1 - R["mom_5"],
         "reversal_20d": 1 - R["mom_20"], "small_size": 1 - R["log_turn20"], "large_size": R["log_turn20"],
         "momentum_12_1": R["mom_12_1"], "low_beta": 1 - R["beta_60"], "high_delivery": R["deliv_pct"],
         "near_52w_high": R["hi52_dist"]}
comp = np.nanmean(np.vstack([TILTS["low_vol"], TILTS["reversal_5d"], TILTS["small_size"],
                             np.where(np.isnan(TILTS["momentum_12_1"]), 0.5, TILTS["momentum_12_1"])]), 0)
TILTS["composite_lowvol_rev_small_mom"] = np.where(E, comp, np.nan)
out = {}
pa_series = {}


def run_pa(score, tag, per, kw=KW, mask=E, mtag="liq2"):
    r, sm, rm, _ = phase_avg(S, score, mask, mtag, H, kw, per)
    pa_series[(tag, per)] = (sm, rm)
    return {k: r[k] for k in KEYS}


if "a" in parts:
    res = {}
    for per in PER:
        res[f"MODEL_{per}"] = run_pa(sc, "MODEL", per)
    for nm, s_ in TILTS.items():
        for per in PER:
            res[f"{nm}_{per}"] = run_pa(s_, nm, per)
        log("tilt", nm, short(res[f"{nm}_dev"]), "| hold", short(res[f"{nm}_hold"]))
    # daily-excess correlation of each tilt with the model
    cor = {}
    for per in PER:
        ms, mr = pa_series[("MODEL", per)]
        mx = ms - mr
        for nm in TILTS:
            ts_, tr_ = pa_series[(nm, per)]
            tx = (ts_ - tr_).reindex(mx.index)
            cor[f"{nm}_{per}"] = float(np.corrcoef(mx.values, tx.values)[0, 1])
    res["corr_daily_excess_with_model"] = cor
    # time-series regression of model excess on the top-20 tilt excesses (DEV)
    for per in PER:
        ms, mr = pa_series[("MODEL", per)]
        y = (ms - mr).values
        Z = np.column_stack([(pa_series[(nm, per)][0] - pa_series[(nm, per)][1]).reindex(ms.index).values
                             for nm in ("low_vol", "reversal_5d", "small_size", "momentum_12_1")])
        Zc = np.column_stack([np.ones(len(y)), Z])
        b, *_ = np.linalg.lstsq(Zc, y, rcond=None)
        e = y - Zc @ b
        res[f"regress_on_top20_tilts_{per}"] = {"alpha_ann": float(b[0] * 252), "alpha_nw_t": L.nw_t(e + b[0], 20),
                                                 "betas": [float(x) for x in b[1:]],
                                                 "R2": float(1 - e.var() / y.var())}
        log("regress top20 tilts", per, short(res[f"regress_on_top20_tilts_{per}"]))
    out["a_top20_tilts"] = res
    save("s6_boring_a", out["a_top20_tilts"])

if "b" in parts:
    res = {}
    # per-date OLS of the model score on the 9 characteristic ranks (NaN rank -> 0.5)
    m = E & np.isfinite(sc)
    idx = np.flatnonzero(m)
    idx = idx[np.argsort(d[idx], kind="stable")]
    dd = d[idx]
    st = np.flatnonzero(np.r_[True, dd[1:] != dd[:-1]])
    en = np.r_[st[1:], len(idx)]
    Z = np.column_stack([np.ones(len(idx))] + [np.where(np.isnan(R[c][idx]), 0.5, R[c][idx]) for c in FC])
    y = sc[idx]
    fit = np.full(len(sc), np.nan)
    resid = np.full(len(sc), np.nan)
    r2 = []
    for a, b in zip(st, en):
        bb, *_ = np.linalg.lstsq(Z[a:b], y[a:b], rcond=None)
        f_ = Z[a:b] @ bb
        fit[idx[a:b]] = f_
        resid[idx[a:b]] = y[a:b] - f_
        r2.append(1 - np.var(y[a:b] - f_) / np.var(y[a:b]))
    r2 = np.array(r2)
    res["xs_R2_score_on_9_char_ranks"] = {"mean": float(r2.mean()), "p10": float(np.percentile(r2, 10)),
                                          "p90": float(np.percentile(r2, 90))}
    for nm, s_ in (("linear_factor_projection", fit), ("factor_residual", resid)):
        for per in PER:
            res[f"{nm}_{per}"] = run_pa(s_, nm, per)
        log(nm, short(res[f"{nm}_dev"]), "| hold", short(res[f"{nm}_hold"]))
    log("xs R2 of score on chars", short(res["xs_R2_score_on_9_char_ranks"]))
    out["b_projection"] = res
    save("s6_boring_b", res)

if "c" in parts:
    res = {}
    kwq = dict(step=5, cost_bps=0, sizing="equal")
    LS = {}
    for nm in ("low_vol", "reversal_5d", "small_size", "momentum_12_1", "low_beta", "reversal_20d"):
        for per in PER:
            r1, s_hi, _, _ = phase_avg(S, TILTS[nm], E, "liq2", H, dict(kwq, select_quantile=(0.8, 1.0)), per)
            r0, s_lo, _, _ = phase_avg(S, TILTS[nm], E, "liq2", H, dict(kwq, select_quantile=(0.0, 0.2)), per)
            ls = (s_hi - s_lo.reindex(s_hi.index))
            LS[(nm, per)] = ls
            res[f"LS_{nm}_{per}"] = {"ann_mean": float(ls.mean() * 252), "nw_t": L.nw_t(ls.values, 20)}
        log("LS factor", nm, short(res[f"LS_{nm}_dev"]), short(res[f"LS_{nm}_hold"]))
    for per in PER:
        ms, mr = pa_series.get(("MODEL", per)) or phase_avg(S, sc, E, "liq2", H, KW, per)[1:3]
        y = (ms - mr)
        names = ["low_vol", "reversal_5d", "small_size", "momentum_12_1", "low_beta", "reversal_20d"]
        Zf = np.column_stack([LS[(nm, per)].reindex(y.index).values for nm in names])
        ok = np.isfinite(Zf).all(1) & np.isfinite(y.values)
        Zc = np.column_stack([np.ones(ok.sum()), Zf[ok]])
        b, *_ = np.linalg.lstsq(Zc, y.values[ok], rcond=None)
        e = y.values[ok] - Zc @ b
        res[f"regress_model_excess_on_LS_{per}"] = {"alpha_ann": float(b[0] * 252), "alpha_nw_t": L.nw_t(e + b[0], 20),
                                                     "raw_excess_ann": float(y.values[ok].mean() * 252),
                                                     "betas": dict(zip(names, [float(x) for x in b[1:]])),
                                                     "R2": float(1 - e.var() / y.values[ok].var())}
        log("regress on LS", per, short(res[f"regress_model_excess_on_LS_{per}"]))
    out["c_ls_regression"] = res
    save("s6_boring_c", res)

if "d" in parts:
    res = {}
    for f in L.FEATURES:
        v = X[f].values.astype("float64")
        rk = xs_rank(v, E)
        if np.isfinite(rk).sum() == 0 or np.nanstd(rk) == 0:
            continue
        for sgn, nm in ((1, "hi"), (-1, "lo")):
            s_ = rk if sgn == 1 else 1 - rk
            r_dev = run_pa(s_, f"{f}_{nm}", "dev")
            res[f"{f}_{nm}"] = {"dev_ex": r_dev["pa_excess_ann"], "dev_t": r_dev["pa_nw_t"]}
            pa_series.pop((f"{f}_{nm}", "dev"), None)
    ranked = sorted(res.items(), key=lambda kv: -kv[1]["dev_t"])
    top = ranked[:8]
    for k_, v_ in top:   # holdout only for the reporting of the DEV-best single features
        f, nm = k_.rsplit("_", 1)
        rk = xs_rank(X[f].values.astype("float64"), E)
        r_h = run_pa(rk if nm == "hi" else 1 - rk, k_, "hold")
        v_["hold_ex"], v_["hold_t"] = r_h["pa_excess_ann"], r_h["pa_nw_t"]
    out["d_single_feature_scan"] = {"n_scores": len(res), "top8_by_dev_t": dict(top),
                                     "share_dev_t_gt2": float(np.mean([v["dev_t"] > 2 for v in res.values()])),
                                     "max_dev_ex": float(max(v["dev_ex"] for v in res.values())),
                                     "all": res}
    log("single-feature top8", short(dict(top)))
    save("s6_boring_d", out["d_single_feature_scan"])

if "e" in parts:
    res = {}
    for per, (a, b) in PER.items():
        st = S.run(sc, E, H, top_k=20, step=5, cost_bps=50, start=a, end_exit=b, keep_trades=True)
        rows = np.array([t[1] for t in st["_trades"]])
        prof = {}
        for c in FC + ["xr_mom20", "xr_vol20", "xr_deliv_z", "dist_sma20", "rsi_14", "max_ret_20", "range_pos"]:
            rk = R.get(c)
            if rk is None:
                rk = xs_rank(X[c].values.astype("float64"), E)
            prof[c] = float(np.nanmean(rk[rows]))
        res[per] = prof
        # trade-level distribution vs random picks (seed 1..5)
        tn = np.array([t[2] for t in st["_trades"]])
        rnd = []
        for s_ in (1, 2, 3, 4, 5):
            rr = S.run(None, E, H, top_k=20, step=5, cost_bps=50, start=a, end_exit=b, keep_trades=True, random_seed=s_)
            rnd.append(np.array([t[2] for t in rr["_trades"]]))
        rn = np.concatenate(rnd)
        q = [1, 5, 10, 25, 50, 75, 90, 95, 99]
        res[f"{per}_trades"] = {"model_mean": float(tn.mean()), "random_mean": float(rn.mean()),
                                "model_median": float(np.median(tn)), "random_median": float(np.median(rn)),
                                "model_q": dict(zip(map(str, q), np.percentile(tn, q).round(4).tolist())),
                                "random_q": dict(zip(map(str, q), np.percentile(rn, q).round(4).tolist())),
                                "model_share_lt_-20pct": float((tn < -0.2).mean()),
                                "random_share_lt_-20pct": float((rn < -0.2).mean()),
                                "model_share_gt_+30pct": float((tn > 0.3).mean()),
                                "random_share_gt_+30pct": float((rn > 0.3).mean()),
                                "model_trimmed5_mean": float(pd.Series(tn).clip(*np.percentile(tn, [5, 95])).mean()),
                                "random_trimmed5_mean": float(pd.Series(rn).clip(*np.percentile(rn, [5, 95])).mean())}
        log("profile", per, short(prof, 3))
        log("trades", per, short(res[f"{per}_trades"]))
    out["e_profile"] = res
    save("s6_boring_e", res)
log("done", parts)

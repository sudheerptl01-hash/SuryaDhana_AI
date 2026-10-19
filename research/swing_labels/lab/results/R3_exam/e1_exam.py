"""R3_exam stage 1: final exam of the frozen process (E0 book) on 2026 vs DEV, PROD vs single model vs 3-seed
ensemble, phase-averaged, with 5-seed random (pre-registered), 25-seed random (SC1), EW universe and Nifty 500.
Also SC2 (D0 avoid veto), SC3 (Sharpe vs cash), SC4 (NW lag / non-overlap t), SC5 (single-phase tracking error),
SC6 (Nifty 500 TR proxy) and the precision-weighted forward estimate. Own phase loop (C.compare maths) so that the
per-phase series are kept; checked against C.phase_avg."""
import os
import sys
import time

import numpy as np
import pandas as pd
from scipy import stats

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
sys.path.insert(0, LAB)
import r3common as C  # noqa: E402

OUT = C.set_agent("R3_exam")
L = C.L
P, F, fw, S, E = C.load_sim()
d = P["date"].values
Z = C.load_prod()
prod = Z["prod"].astype("float64")
del Z
DV = f"{LAB}/results/R3_devil"
sc_main = np.load(f"{DV}/wf_main.npz")["score"].astype("float64")
sc1 = np.load(f"{DV}/wf_seed1.npz")["score"].astype("float64")
sc2 = np.load(f"{DV}/wf_seed2.npz")["score"].astype("float64")
rk = [pd.Series(np.where(E, s, np.nan)).groupby(d).rank(pct=True).values for s in (sc_main, sc1, sc2)]
with np.errstate(all="ignore"):
    import warnings
    warnings.simplefilter("ignore")
    ens3 = np.nanmean(np.vstack(rk), 0)
ens3 = np.where(E & np.isfinite(sc_main), ens3, np.nan)
del rk, sc1, sc2
SCORES = {"PROD": prod, "single": sc_main, "ens3": ens3}
C.log("scores", {k: int(np.isfinite(v).sum()) for k, v in SCORES.items()})

n5 = L.market_series("Nifty 500")["close"].astype("float64")
n5.index = pd.DatetimeIndex(n5.index)
cash = L.market_series("Nifty 1D Rate Index")["close"].astype("float64")
cash.index = pd.DatetimeIndex(cash.index)


def idx_ret(lv_series, common):
    lv = lv_series.reindex(lv_series.index.union(common)).ffill().reindex(common)
    return lv.pct_change().fillna(0.0)


def nw_se_ann(x, lag=20):
    x = np.asarray(x, dtype="float64")
    n = len(x)
    xc = x - x.mean()
    s = (xc @ xc) / n
    for k in range(1, min(lag, n - 1) + 1):
        s += 2 * (1 - k / (lag + 1)) * (xc[k:] @ xc[:-k]) / n
    return float(np.sqrt(max(s, 1e-30) / n) * 252)


def sstats(r):
    r = np.asarray(r, dtype="float64")
    eq = np.cumprod(1 + r)
    yrs = len(r) / 252
    return {"cagr": float(eq[-1] ** (1 / yrs) - 1), "total_return": float(eq[-1] - 1),
            "vol": float(r.std() * np.sqrt(252)), "sharpe": float(r.mean() / r.std() * np.sqrt(252)),
            "maxdd": float((eq / np.maximum.accumulate(eq) - 1).min()), "n_days": int(len(r))}


def phase_loop(score, kw, period):
    a, b = C.PER[period]
    g0 = int(np.searchsorted(S.cal, np.datetime64(a)))
    recs = []
    for k in range(5):
        kk = dict(kw, start=str(S.cal[g0 + k]), end_exit=b)
        res, sd, rbd, dts = C.compare(S, score, E, "liq2", 20, kk)
        _, ewd, _ = C.ew_band(S, E, "liq2", 20, kk)
        ix = pd.DatetimeIndex(dts)
        recs.append({"kk": kk, "res": res, "s": pd.Series(sd, ix), "r5": pd.Series(rbd[:len(dts)], ix),
                     "ew": pd.Series(ewd[:len(dts)], ix)})
    return recs


def extra_random(kw, period, seeds):
    """Per-phase random top-20 books for extra seeds (diagnostic SC1). Returns per-phase list of (daily matrix, cagrs)."""
    a, b = C.PER[period]
    g0 = int(np.searchsorted(S.cal, np.datetime64(a)))
    out = []
    for k in range(5):
        kk = dict(kw, start=str(S.cal[g0 + k]), end_exit=b)
        mats, cg, dts = [], [], None
        for sd_ in seeds:
            st = S.run(None, E, 20, random_seed=sd_, **kk)
            mats.append(st["_daily_ret"])
            cg.append(st["cagr"])
            dts = st["_dates"]
        out.append({"daily": np.vstack(mats), "cagr": cg, "dates": pd.DatetimeIndex(dts.astype("datetime64[D]").astype(str))})
    return out


def common_index(recs):
    c = recs[0]["s"].index
    for r in recs:
        for key in ("s", "r5", "ew"):
            c = c.intersection(r[key].index)
    return c


KW50 = dict(top_k=20, step=5, cost_bps=50)
KW80 = dict(top_k=20, step=5, cost_bps=80)
res = {}
series = {}
T1 = time.time()
# ------------------------------------------------------------------ SC1 extra random seeds (50 bps)
XR = {}
for per in ("dev", "hold"):
    t0 = time.time()
    XR[per] = extra_random(KW50, per, range(6, 26))
    C.log(f"extra random {per} done in {time.time() - t0:.0f}s")

for per in ("dev", "hold"):
    for cname, kw in (("c50", KW50), ("c80", KW80)):
        recs_by = {}
        for nm, sc in SCORES.items():
            t0 = time.time()
            recs_by[nm] = phase_loop(sc, kw, per)
            C.log(f"{nm} {per} {cname} phase loop {time.time() - t0:.0f}s")
        common = common_index(recs_by["PROD"])
        for nm in SCORES:
            common = common.intersection(common_index(recs_by[nm]))
        r5 = np.mean([r["r5"].reindex(common).values for r in recs_by["PROD"]], 0)
        ew = np.mean([r["ew"].reindex(common).values for r in recs_by["PROD"]], 0)
        nret = idx_ret(n5, common).values
        cret = idx_ret(cash, common).values
        block = {"window": [str(common[0])[:10], str(common[-1])[:10]], "n_days": int(len(common)),
                 "random5": sstats(r5), "ew": sstats(ew), "nifty500_price": sstats(nret), "cash_1d_rate": sstats(cret)}
        block["nifty500_tr_proxy_cagr"] = float((1 + block["nifty500_price"]["cagr"]) * 1.012 - 1)
        if cname == "c50":
            # 25-seed random = cached seeds 1..5 + extra 6..25 on the strategy calendar
            r25p = []
            for k in range(5):
                xr = XR[per][k]
                s5 = recs_by["PROD"][k]["r5"]
                mat = pd.DataFrame(xr["daily"].T, index=xr["dates"]).reindex(s5.index).values
                r25p.append(pd.Series((5 * s5.values + mat.sum(1)) / 25, index=s5.index))
            r25 = np.mean([x.reindex(common).values for x in r25p], 0)
            block["random25"] = sstats(r25)
            allc = []
            for k in range(5):
                cg5 = recs_by["PROD"][k]["res"]["random"]["cagr_mean"]
                allc.append({"phase": k, "seeds1_5_cagr_mean": cg5, "seeds6_25_cagr_mean": float(np.mean(XR[per][k]["cagr"])),
                             "seeds6_25_cagr_sd": float(np.std(XR[per][k]["cagr"]))})
            block["random_seed_noise_by_phase"] = allc
            block["random5_minus_random25_ann"] = float((r5 - r25).mean() * 252)
            series[f"{per}_random25"] = r25
        series[f"{per}_{cname}_dates"] = np.array([str(x)[:10] for x in common])
        series[f"{per}_{cname}_random5"] = r5
        series[f"{per}_{cname}_ew"] = ew
        series[f"{per}_{cname}_n500"] = nret
        series[f"{per}_{cname}_cash"] = cret
        for nm in SCORES:
            recs = recs_by[nm]
            sm = np.mean([r["s"].reindex(common).values for r in recs], 0)
            series[f"{per}_{cname}_{nm}"] = sm
            st = sstats(sm)
            ex = sm - r5
            exe = sm - ew
            st.update({"excess_vs_random5_ann": float(ex.mean() * 252), "nw_t_vs_random5": L.nw_t(ex, 20),
                       "se_vs_random5_ann": nw_se_ann(ex, 20),
                       "excess_vs_ew_ann": float(exe.mean() * 252), "nw_t_vs_ew": L.nw_t(exe, 20),
                       "se_vs_ew_ann": nw_se_ann(exe, 20),
                       "cagr_gap_vs_random5": st["cagr"] - block["random5"]["cagr"],
                       "cagr_gap_vs_ew": st["cagr"] - block["ew"]["cagr"],
                       "sharpe_vs_cash": float((sm - cret).mean() / (sm - cret).std() * np.sqrt(252)),
                       "phase_excess_cagr_vs_random": [float(r["res"]["excess_cagr_vs_random"]) for r in recs],
                       "phase_excess_ann_vs_random": [float((r["s"].reindex(common).values - r["r5"].reindex(common).values).mean() * 252) for r in recs],
                       "phase_t": [float(r["res"]["excess_daily_nw_t"]) for r in recs],
                       "trades_phase_mean": float(np.mean([r["res"]["trades"] for r in recs])),
                       "hit_rate_phase_mean": float(np.mean([r["res"]["hit_rate"] for r in recs])),
                       "mean_trade_net_phase_mean": float(np.mean([r["res"]["mean_trade_net"] for r in recs])),
                       "median_trade_net_phase_mean": float(np.mean([r["res"]["median_trade_net"] for r in recs])),
                       "exposure_phase_mean": float(np.mean([r["res"]["exposure"] for r in recs]))})
            if cname == "c50":
                ex25 = sm - series[f"{per}_random25"]
                st.update({"excess_vs_random25_ann": float(ex25.mean() * 252), "nw_t_vs_random25": L.nw_t(ex25, 20),
                           "se_vs_random25_ann": nw_se_ann(ex25, 20)})
                # SC4: NW lag sensitivity and non-overlapping 20-day blocks
                nb = len(ex) // 20
                bs = ex[:nb * 20].reshape(nb, 20).sum(1)
                st["SC4_t_lag"] = {"lag20": L.nw_t(ex, 20), "lag40": L.nw_t(ex, 40), "lag60": L.nw_t(ex, 60),
                                   "nonoverlap_20d_blocks_t": float(bs.mean() / bs.std(ddof=1) * np.sqrt(nb)),
                                   "n_blocks": int(nb)}
                # SC5: single-phase vs phase-averaged tracking error vs random5
                te_ph = [float((r["s"].reindex(common).values - r["r5"].reindex(common).values).std() * np.sqrt(252)) for r in recs]
                st["SC5_tracking_error"] = {"phase_avg": float(ex.std() * np.sqrt(252)), "single_phase": te_ph,
                                            "single_phase_mean": float(np.mean(te_ph))}
                # monthly breakdown
                df = pd.DataFrame({"s": sm, "r5": r5, "r25": series[f"{per}_random25"], "ew": ew, "n5": nret},
                                  index=common)
                mo = (1 + df).groupby(df.index.to_period("M")).prod() - 1
                st["monthly"] = {str(k): {c: float(v) for c, v in row.items()} for k, row in mo.iterrows()}
                st["months_beating_random5"] = float((mo["s"] > mo["r5"]).mean())
                st["months_beating_ew"] = float((mo["s"] > mo["ew"]).mean())
            block[nm] = st
        # paired diffs
        for a_, b_ in (("PROD", "single"), ("PROD", "ens3"), ("single", "ens3")):
            sa = pd.Series(series[f"{per}_{cname}_{a_}"], index=common)
            sb = pd.Series(series[f"{per}_{cname}_{b_}"], index=common)
            block[f"paired_{a_}_minus_{b_}"] = C.paired(sa, sb)
        # check vs C.phase_avg for PROD
        if cname == "c50":
            pa, smx, rmx, emx = C.phase_avg(S, prod, E, "liq2", 20, kw, per, with_ew=True)
            block["check_vs_C_phase_avg"] = {"max_abs_diff_strategy": float(np.max(np.abs(smx.reindex(common).values - series[f"{per}_{cname}_PROD"]))),
                                             "C_pa_excess_ann": pa["pa_excess_ann"], "C_pa_nw_t": pa["pa_nw_t"],
                                             "C_pa_cagr": pa["pa_cagr"], "C_pa_ew_cagr": pa["pa_ew_cagr"]}
        res[f"{per}_{cname}"] = block
        C.log(per, cname, {nm: (round(block[nm]["cagr"], 4), round(block[nm]["excess_vs_random5_ann"], 4),
                                round(block[nm]["nw_t_vs_random5"], 2)) for nm in SCORES},
              "r5", round(block["random5"]["cagr"], 4), "ew", round(block["ew"]["cagr"], 4))
        C.save("exam", res)

# ------------------------------------------------------------------ forward estimate (precision weighted)
dv = C.load_res("R3_devil")
N_prog = dv["s5_dsr"]["hlz_bonferroni_haircut_phaseavg_dev"]["programme_total"]["N"]
N_upper = dv["s5_dsr"]["hlz_bonferroni_haircut_phaseavg_dev"]["upper_all_runs"]["N"]


def haircut(ex, t, N):
    p1 = 1 - stats.norm.cdf(t)
    padj = min(1.0, p1 * N)
    tadj = max(stats.norm.ppf(1 - padj), 0.0) if padj < 1 else 0.0
    return {"N": int(N), "p_onesided": float(p1), "p_bonf": float(padj), "t_adj": float(tadj),
            "haircut_share": float(1 - tadj / t), "haircut_excess_ann": float(ex * tadj / t)}


def combine(dev_in, se_dev, hold, se_hold):
    w1, w2 = 1 / se_dev ** 2, 1 / se_hold ** 2
    return {"dev_input": float(dev_in), "combined": float((dev_in * w1 + hold * w2) / (w1 + w2)),
            "combined_se": float(np.sqrt(1 / (w1 + w2))), "weight_dev": float(w1 / (w1 + w2)),
            "weight_hold": float(w2 / (w1 + w2))}


fwd = {}
for nm in SCORES:
    fwd[nm] = {}
    for base, kx, kt, ks in (("random5", "excess_vs_random5_ann", "nw_t_vs_random5", "se_vs_random5_ann"),
                             ("ew", "excess_vs_ew_ann", "nw_t_vs_ew", "se_vs_ew_ann"),
                             ("random25", "excess_vs_random25_ann", "nw_t_vs_random25", "se_vs_random25_ann")):
        dvb, hdb = res["dev_c50"][nm], res["hold_c50"][nm]
        ex_d, t_d, se_d = dvb[kx], dvb[kt], dvb[ks]
        ex_h, se_h = hdb[kx], hdb[ks]
        hc = haircut(ex_d, t_d, N_prog)
        hcu = haircut(ex_d, t_d, N_upper)
        fwd[nm][base] = {"dev_excess": ex_d, "dev_t": t_d, "dev_se": se_d, "hold_excess": ex_h, "hold_t": hdb[kt],
                         "hold_se": se_h, "z_hold_vs_dev_raw": float((ex_h - ex_d) / np.sqrt(se_d ** 2 + se_h ** 2)),
                         "z_hold_vs_dev_haircut": float((ex_h - hc["haircut_excess_ann"]) / np.sqrt(se_d ** 2 + se_h ** 2)),
                         "haircut_programme": hc, "haircut_upper": hcu,
                         "bonf_haircut_programme": combine(hc["haircut_excess_ann"], se_d, ex_h, se_h),
                         "bonf_haircut_upper": combine(hcu["haircut_excess_ann"], se_d, ex_h, se_h),
                         "raw_dev": combine(ex_d, se_d, ex_h, se_h),
                         "half_dev": combine(ex_d / 2, se_d, ex_h, se_h)}
        fwd[nm][base]["p_combined_gt0_primary"] = float(stats.norm.cdf(fwd[nm][base]["bonf_haircut_programme"]["combined"] / fwd[nm][base]["bonf_haircut_programme"]["combined_se"]))
C.save("forward_estimate", fwd)
C.log("forward PROD random5", {k: round(v["combined"], 4) for k, v in fwd["PROD"]["random5"].items() if isinstance(v, dict) and "combined" in v})

# ------------------------------------------------------------------ SC2: D0 avoid veto (EW minus PROD bottom 30%)
KWD0 = dict(top_k=20, step=5, cost_bps=50, select_quantile=(0.3, 1.0), sizing="equal")
sc2r = {}
for per in ("dev", "hold"):
    t0 = time.time()
    pa, smd, rmd, emd = C.phase_avg(S, prod, E, "liq2", 20, KWD0, per, with_ew=True)
    base = pd.Series(series[f"{per}_c50_PROD"], index=pd.DatetimeIndex(series[f"{per}_c50_dates"]))
    eqd = np.cumprod(1 + emd.values)
    sc2r[per] = {"D0_cagr": pa["pa_cagr"], "ew_cagr": pa["pa_ew_cagr"], "D0_vs_ew_ann": pa["pa_excess_vs_ew_ann"],
                 "D0_vs_ew_t": pa["pa_vs_ew_nw_t"], "D0_maxdd": pa["pa_maxdd"], "ew_maxdd": pa["pa_ew_maxdd"],
                 "D0_vs_random70_ann": pa["pa_excess_ann"], "D0_vs_random70_t": pa["pa_nw_t"],
                 "D0_minus_frozen_book": C.paired(smd, base)}
    C.log("SC2", per, f"{time.time() - t0:.0f}s", C.short(sc2r[per]))
C.save("SC2_D0_avoid_veto", sc2r)

# ------------------------------------------------------------------ SC3: Sharpe vs cash for hedges (from R3_twoway series)
sc3 = {"frozen_book_my_series": {p: {"sharpe_raw": res[f"{p}_c50"]["PROD"]["sharpe"],
                                     "sharpe_vs_cash": res[f"{p}_c50"]["PROD"]["sharpe_vs_cash"]} for p in ("dev", "hold")}}
try:
    zt = np.load(f"{LAB}/results/R3_twoway/series_s3.npz", allow_pickle=True)
    keys = list(zt.files)
    sc3["twoway_series_keys_sample"] = keys[:12]
    dates_key = [k for k in keys if "date" in k.lower()]
    sc3["twoway_dates_keys"] = dates_key[:10]
    for strat in ("BASE", "D1a", "D1b", "D3"):
        kk = [k for k in keys if k.startswith(strat) and "dev" in k and "c50" in k]
        sc3[f"{strat}_candidate_keys"] = kk[:6]
except Exception as e:  # noqa: BLE001
    sc3["twoway_series_error"] = repr(e)
C.save("SC3_sharpe_vs_cash", sc3)

np.savez_compressed(os.path.join(OUT, "exam_series.npz"), **series)
C.log("done", f"{time.time() - T1:.0f}s")

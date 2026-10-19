"""Stage 6: factor attribution — is the edge just low-vol / reversal / size?

(A) Long-short factor returns from the SAME universe U with the SAME Sim mechanics as the books
    (h=20, step 5, EW top-30% minus EW bottom-30% by characteristic, 50 bps on both legs, phase-averaged
    over the 5 signal phases):
      SIZE    small minus big            (-log_turn20)
      MOM     12-1 winners minus losers  (mom_12_1)
      REV     5d losers minus winners    (-mom_5)
      LOWVOL  low minus high vol_20      (-vol_20)
      LOWBETA low minus high beta_60     (-beta_60)
      (ext)   LOWIDIO (-idio_vol_60), TREND (dist_sma200), and MKT = universe EW book return.
(B) Regress each book's phase-averaged daily excess-vs-random on the factors (OLS, Newey-West lag 20):
    spec 'brief' = SIZE MOM REV LOWVOL LOWBETA MKT ; spec 'ext' = brief + LOWIDIO TREND.
    Alpha (annualised) and its NW t after factors, R2, betas. DEV and HOLD separately.
(C) Score decomposition (writes new score files, evaluated by s5_sim.py main):
      <tag>_FN : per-date residual of the score's pct rank on the pct ranks of the 7 characteristics
                 (factor-neutral score: what the model knows beyond the factor tilts)
      <tag>_FC : static factor composite = sum_k w_k * rank_k with w = DEV-average of the per-date
                 projection coefficients (a 'boring' linear factor tilt calibrated on DEV only)
Usage: python3 s6_attrib.py factors            (build factor series)
       python3 s6_attrib.py decompose tag ...  (write _FN/_FC score files)
       python3 s6_attrib.py regress tag ...    (needs daily_main_<tag>.npz from s5_sim.py main)
"""
import os
import sys
import time

import numpy as np
import pandas as pd

from common import OUT, L, H, save, nw_reg, date_blocks

mode, tags = sys.argv[1], sys.argv[2:]
t0 = time.time()
CH = {"SIZE": ("log_turn20", -1), "MOM": ("mom_12_1", 1), "REV": ("mom_5", -1), "LOWVOL": ("vol_20", -1),
      "LOWBETA": ("beta_60", -1), "LOWIDIO": ("idio_vol_60", -1), "TREND": ("dist_sma200", 1)}
BRIEF = ["SIZE", "MOM", "REV", "LOWVOL", "LOWBETA", "MKT"]
EXT = BRIEF + ["LOWIDIO", "TREND"]
PER = {"dev": (L.DEV[0], L.DEV[1]), "hold": ("2026-01-01", None)}
FACT_FN = f"{OUT}/factors_daily.npz"

if mode == "factors":
    P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
    F = L.load_features(["atr_pct"] + [c for c, _ in CH.values()])
    fw = L.Fwd(P)
    S = L.Sim(P, F, fw)
    U = np.load(f"{OUT}/labels.npz")["U"]
    out, ser = {}, {}
    for per, (a, b) in PER.items():
        g0 = int(np.searchsorted(S.cal, np.datetime64(a)))
        for nm, (col, sgn) in list(CH.items()) + [("MKT", (None, 1))]:
            legs = []
            for ph in range(5):
                st = str(S.cal[g0 + ph])
                kw = dict(step=5, cost_bps=50, sizing="equal", start=st, end_exit=b)
                if nm == "MKT":
                    r_ = S.run(np.ones(S.n), U, H, select_quantile=(0.0, 1.0), **kw)
                    legs.append(pd.Series(r_["_daily_ret"], index=pd.DatetimeIndex(r_["_dates"])))
                    continue
                x = sgn * F[col].values.astype("float64")
                hi = S.run(x, U, H, select_quantile=(0.7, 1.0), **kw)
                lo = S.run(-x, U, H, select_quantile=(0.7, 1.0), **kw)
                legs.append(pd.Series(hi["_daily_ret"] - lo["_daily_ret"], index=pd.DatetimeIndex(hi["_dates"])))
            s = pd.concat(legs, axis=1, join="inner").mean(axis=1)
            ser[f"{per}__{nm}"] = s
            out[f"{per}_{nm}_ann"] = float(s.mean() * 252)
            out[f"{per}_{nm}_nw_t"] = L.nw_t(s.values, lag=H)
            print(per, nm, round(s.mean() * 252, 4), round(out[f"{per}_{nm}_nw_t"], 2), round(time.time() - t0, 1),
                  flush=True)
        names = BRIEF[:-1] + ["LOWIDIO", "TREND", "MKT"]
        M = pd.concat([ser[f"{per}__{n}"] for n in names], axis=1, join="inner")
        M.columns = names
        out[f"{per}_corr"] = M.corr().round(3).to_dict()
    np.savez_compressed(FACT_FN, **{k: v.values for k, v in ser.items()},
                        **{k + "__dates": v.index.values.astype("datetime64[D]").astype(str) for k, v in ser.items()})
    save("s6_factors", out)

elif mode == "decompose":
    from scipy.stats import rankdata
    P = L.load_panel(["date"])
    dates = P["date"].values.astype("datetime64[D]")
    F = L.load_features([c for c, _ in CH.values()])
    U = np.load(f"{OUT}/labels.npz")["U"]
    cols = [c for c, _ in CH.values()]
    Xc = np.column_stack([F[c].values.astype("float64") for c in cols])
    del F
    dev_end = np.datetime64(L.DEV[1])
    for tag in tags:
        sc = np.load(f"{OUT}/wf_{tag}.npz")["score"].astype("float64")
        m = U & np.isfinite(sc)
        idx, b0, e0 = date_blocks(dates, np.flatnonzero(m))
        resid = np.full(len(sc), np.nan)
        R = np.full((len(sc), len(cols)), np.nan)
        coefs, cdates, r2 = [], [], []
        for s_, t_ in zip(b0, e0):
            ii = idx[s_:t_]
            if len(ii) < 30:
                continue
            ys = rankdata(sc[ii]) / len(ii)
            Xr = np.empty((len(ii), len(cols)))
            for k in range(len(cols)):
                v = Xc[ii, k]
                ok = np.isfinite(v)
                rr = np.full(len(ii), 0.5)
                if ok.sum() > 1:
                    rr[ok] = rankdata(v[ok]) / ok.sum()
                Xr[:, k] = rr
            X = np.column_stack([np.ones(len(ii)), Xr])
            cf, *_ = np.linalg.lstsq(X, ys, rcond=None)
            e = ys - X @ cf
            resid[ii] = e
            R[ii] = Xr
            coefs.append(cf)
            cdates.append(dates[ii[0]])
            r2.append(1 - e.var() / ys.var())
        coefs = np.array(coefs)
        cdates = np.array(cdates)
        dev_m = cdates <= dev_end
        w = coefs[dev_m].mean(0)                 # static DEV-average weights (intercept irrelevant)
        comp = np.where(np.isfinite(R).all(1), R @ w[1:], np.nan)
        comp[~m] = np.nan
        np.savez_compressed(f"{OUT}/wf_{tag}_FN.npz", score=resid.astype(np.float32))
        np.savez_compressed(f"{OUT}/wf_{tag}_FC.npz", score=comp.astype(np.float32))
        r2 = np.array(r2)
        info = {"chars": cols, "dev_mean_coef": dict(zip(["const"] + cols, w.tolist())),
                "dev_coef_t": dict(zip(["const"] + cols, (coefs[dev_m].mean(0) / (coefs[dev_m].std(0) /
                                                                                     np.sqrt(dev_m.sum() / H))).tolist())),
                "hold_mean_coef": dict(zip(["const"] + cols, coefs[~dev_m].mean(0).tolist())) if (~dev_m).any() else None,
                "mean_xs_R2_dev": float(r2[dev_m].mean()), "mean_xs_R2_hold": float(r2[~dev_m].mean()) if (~dev_m).any() else None}
        save(f"s6_decompose_{tag}", info)
        print(tag, info, round(time.time() - t0, 1), flush=True)

elif mode == "regress":
    fz = np.load(FACT_FN, allow_pickle=True)
    fac = {k: pd.Series(fz[k], index=pd.DatetimeIndex(fz[k + "__dates"])) for k in fz.files if not k.endswith("__dates")}
    out = {}
    for tag in tags:
        dz = np.load(f"{OUT}/daily_main_{tag}.npz", allow_pickle=True)
        for book in ("K20_s5_c50", "avoid30_s5_c50"):
            for per in ("dev", "hold"):
                k = f"{book}_{per}"
                st = pd.Series(dz[f"{k}__strat"], index=pd.DatetimeIndex(dz[f"{k}__strat__dates"]))
                rd = pd.Series(dz[f"{k}__rand"], index=pd.DatetimeIndex(dz[f"{k}__rand__dates"]))
                y = (st - rd).dropna()
                for spec, names in (("brief", BRIEF), ("ext", EXT)):
                    M = pd.concat([y] + [fac[f"{per}__{n}"] for n in names], axis=1, join="inner").dropna()
                    yy, XX = M.iloc[:, 0].values, M.iloc[:, 1:].values
                    b, t, r2 = nw_reg(yy, XX, H)
                    rec = {"n_days": int(len(yy)), "excess_ann": float(yy.mean() * 252),
                           "excess_nw_t": L.nw_t(yy, lag=H), "alpha_ann": float(b[0] * 252),
                           "alpha_nw_t": float(t[0]), "r2": float(r2),
                           "betas": dict(zip(names, b[1:].tolist())), "beta_t": dict(zip(names, t[1:].tolist())),
                           "factor_contrib_ann": {n: float(b[i + 1] * M.iloc[:, i + 1].mean() * 252)
                                                  for i, n in enumerate(names)}}
                    out[f"{tag}|{k}|{spec}"] = rec
                    print(tag, k, spec, "excess", round(rec["excess_ann"], 4), "alpha", round(rec["alpha_ann"], 4),
                          "t", round(rec["alpha_nw_t"], 2), "R2", round(r2, 3),
                          {n: round(v, 2) for n, v in rec["beta_t"].items()}, flush=True)
    save("s6_regress_" + "_".join(tags), out)
print("total", round(time.time() - t0, 1))

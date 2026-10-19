"""Stage 6: null distributions and reference sorts for the long top-K book (liq2, 50 bps).

(a) iid-random luck band: 40 seeds of the random picker (same as the compare baseline) -> sd/p95 of CAGR.
(b) persistent-tilt luck band: score = U(0,1) drawn once per entity (constant through time) -> a
    skill-less but persistent tilt (same names picked repeatedly), 40 seeds; excess vs the 5-seed
    iid baseline + NW t -> p95 / max of the null.
(c) cross-horizon matrix: model trained at h_train scored and held at h_hold (K20 s5 50 bps).
(d) reference single-characteristic sorts (not candidates): low vol_20, mom_12_1, 5d reversal,
    low beta_60, high log_turn20, low idio_vol_60, high xr_mom60.
Usage: python3 s6_nulls.py <part: luck|xh|ref> [h]
"""
import sys
import time

import numpy as np

from common import OUT, L, save

part = sys.argv[1]
t0 = time.time()
P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["atr_pct", "vol_20", "mom_12_1", "mom_5", "beta_60", "log_turn20", "idio_vol_60", "xr_mom60",
                     "dist_sma200"])
fw = L.Fwd(P)
S = L.Sim(P, F, fw)
meta = np.load(f"{OUT}/meta.npz")
E = meta["E"]
PER = {"dev": dict(start=L.DEV[0], end_exit=L.DEV[1]), "hold": dict(start="2026-01-01", end_exit=None)}
ent_code = np.unique(P["entity"].values, return_inverse=True)[1]
print("ready", round(time.time() - t0, 1), flush=True)


def summ(st):
    return {k: st[k] for k in ("cagr", "sharpe", "max_dd", "exposure", "mean_trade_net", "hit_rate")}


if part == "luck":
    out = {}
    for h in (10, 15, 20):
        for per, kw in PER.items():
            base = dict(top_k=20, step=5, cost_bps=50, **kw)
            rb = S.random_band(E, h, seeds=(1, 2, 3, 4, 5), **base)
            iid = [S.run(None, E, h, random_seed=100 + s, **base)["cagr"] for s in range(40)]
            pers = []
            for s in range(40):
                u = np.random.default_rng(1000 + s).random(ent_code.max() + 1)
                st = S.run(u[ent_code], E, h, **base)
                pers.append((st["cagr"] - rb["cagr_mean"], L.nw_t(st["_daily_ret"] - rb["_daily_ret_mean"], lag=h)))
            pe = np.array(pers)
            out[f"h{h}_{per}"] = {
                "random5_cagr_mean": rb["cagr_mean"],
                "iid40_cagr_mean": float(np.mean(iid)), "iid40_cagr_sd": float(np.std(iid)),
                "iid40_cagr_p95": float(np.percentile(iid, 95)),
                "persistent40_excess_mean": float(pe[:, 0].mean()), "persistent40_excess_sd": float(pe[:, 0].std()),
                "persistent40_excess_p95": float(np.percentile(pe[:, 0], 95)),
                "persistent40_excess_max": float(pe[:, 0].max()),
                "persistent40_nwt_p95": float(np.percentile(pe[:, 1], 95)),
                "persistent40_nwt_max": float(pe[:, 1].max()),
                "persistent40_nwt_sd": float(pe[:, 1].std())}
            print(h, per, out[f"h{h}_{per}"], round(time.time() - t0, 1), flush=True)
    save("s6_luck", out)

elif part == "xh":
    out = {}
    rbs = {}
    for htr in (10, 15, 20):
        sc = np.load(f"{OUT}/wf_h{htr}_neu_RANK.npz")["score"].astype("float64")
        for hh in (10, 15, 20):
            for per, kw in PER.items():
                for step in (5, 10):
                    base = dict(top_k=20, step=step, cost_bps=50, **kw)
                    key = (hh, per, step)
                    if key not in rbs:
                        rbs[key] = S.random_band(E, hh, **base)
                    rb = rbs[key]
                    st = S.run(sc, E, hh, **base)
                    out[f"train{htr}_hold{hh}_s{step}_{per}"] = {
                        **summ(st), "random_cagr": rb["cagr_mean"], "excess_cagr": st["cagr"] - rb["cagr_mean"],
                        "nw_t": L.nw_t(st["_daily_ret"] - rb["_daily_ret_mean"], lag=hh)}
                    print(htr, hh, step, per, round(out[f"train{htr}_hold{hh}_s{step}_{per}"]["excess_cagr"], 4),
                          round(out[f"train{htr}_hold{hh}_s{step}_{per}"]["nw_t"], 2), flush=True)
    save("s6_cross_horizon", out)

elif part == "ref":
    h = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    refs = {"low_vol20": -F["vol_20"].values, "mom_12_1": F["mom_12_1"].values, "rev_5d": -F["mom_5"].values,
            "low_beta60": -F["beta_60"].values, "liquid_turn20": F["log_turn20"].values,
            "low_idio60": -F["idio_vol_60"].values, "xr_mom60": F["xr_mom60"].values,
            "high_vol20": F["vol_20"].values, "high_idio60": F["idio_vol_60"].values,
            "dist_sma200": F["dist_sma200"].values}
    out = {}
    for per, kw in PER.items():
        for step, mode in ((5, "long"), (10, "long"), (5, "avoid")):
            if mode == "long":
                base = dict(top_k=20, step=step, cost_bps=50, **kw)
            else:
                base = dict(step=step, cost_bps=50, select_quantile=(0.3, 1.0), sizing="equal", **kw)
            rb = S.random_band(E, h, **base)
            for nm, sc in refs.items():
                sc = np.asarray(sc, dtype="float64")
                st = S.run(sc, E, h, **base)
                kk = f"{nm}_{mode}_s{step}_{per}"
                out[kk] = {**summ(st), "random_cagr": rb["cagr_mean"], "excess_cagr": st["cagr"] - rb["cagr_mean"],
                           "nw_t": L.nw_t(st["_daily_ret"] - rb["_daily_ret_mean"], lag=h)}
                print(kk, round(out[kk]["excess_cagr"], 4), round(out[kk]["nw_t"], 2), flush=True)
    save(f"s6_ref_sorts_h{h}", out)
print("done", round(time.time() - t0, 1))

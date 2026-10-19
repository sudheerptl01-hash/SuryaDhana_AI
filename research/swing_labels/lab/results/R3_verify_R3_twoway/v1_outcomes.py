"""Verifier v1 (own code): PROD decile spreads (all eligible and inside F&O), realised -1 class mean, F&O short view.
Independent of R3_twoway scripts; uses only lablib loaders, the frozen label file and the frozen PROD score."""
import json
import sys
import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
OUT = LAB + "/results/R3_verify_R3_twoway"
sys.path.insert(0, LAB)
import lablib as L  # noqa: E402

P = L.load_panel(["date"])
F = L.load_features(["elig_base", "fno_proxy"])
d = P["date"].values.astype("datetime64[D]")
E = F["elig_base"].values.astype(bool)
fno = F["fno_proxy"].values.astype(bool)
z = np.load(f"{LAB}/results/R3_devil/label_h20_neumom.npz")
pct, r = z["pct"].astype("float64"), z["r"].astype("float64")
prod = np.load(f"{LAB}/results/_lead/prod_h20.npz", allow_pickle=True)["prod"].astype("float64")
yr = d.astype("datetime64[Y]").astype(int) + 1970
cal = np.unique(d)
gi = np.searchsorted(cal, d)
cl = L.market_series("Nifty 1D Rate Index")["close"].reindex(pd.DatetimeIndex(cal)).ffill().values


def my_nw_t(x, lag):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    n = len(x)
    u = x - x.mean()
    s = u @ u / n
    for k in range(1, lag + 1):
        s += 2 * (1 - k / (lag + 1)) * (u[k:] @ u[:-k]) / n
    return x.mean() / np.sqrt(s / n)


def decile_table(univ, per_mask, x):
    # decile by per-date percentile rank of PROD among univ rows with finite PROD
    m = univ & np.isfinite(prod)
    df = pd.DataFrame({"d": d[m], "p": prod[m], "x": x[m], "pm": per_mask[m]})
    df["rk"] = df.groupby("d")["p"].rank(method="average") / df.groupby("d")["p"].transform("count")
    df["dec"] = np.clip(np.ceil(df["rk"] * 10), 1, 10)
    df = df[df.pm & np.isfinite(df.x)]
    dm = df.groupby("dec").x.mean()
    per_date = df.groupby(["d", "dec"]).x.mean().unstack()
    sp = (per_date[10.0] - per_date[1.0]).dropna()
    # non-overlapping t for every one of the 20 offsets
    ts = []
    for off in range(20):
        v = sp.values[off::20]
        ts.append(v.mean() / (v.std(ddof=1) / np.sqrt(len(v))))
    rho = pd.Series(dm.values).corr(pd.Series(dm.index.values), method="spearman")
    return {"decile_means": {int(k): float(v) for k, v in dm.items()}, "spread_mean": float(sp.mean()),
            "nonoverlap_t_offset0": float(ts[0]), "nonoverlap_t_median_of_20_offsets": float(np.median(ts)),
            "nonoverlap_t_range": [float(min(ts)), float(max(ts))], "nw_t_lag20": float(my_nw_t(sp.values, 20)),
            "spearman": float(rho), "n_dates": int(len(sp)), "universe_mean": float(df.x.mean())}


net = r - 0.005
j20 = np.minimum(gi + 20, len(cal) - 1)
short_net_sig = -r + (cl[j20] / cl[gi] - 1) - 0.0025          # carry from signal date (their convention)
out = {}
for nm, pm in (("dev", (yr >= 2023) & (yr <= 2025)), ("2026", yr == 2026)):
    out[f"all|{nm}"] = decile_table(E, pm, net)
    out[f"fno|{nm}"] = decile_table(E & fno, pm, net)
    out[f"fno_short|{nm}"] = decile_table(E & fno, pm, short_net_sig)
    cls_m1 = pm & E & np.isfinite(r) & np.isfinite(pct) & (pct <= 0.3)
    cls_p1 = pm & E & np.isfinite(r) & np.isfinite(pct) & (pct > 0.7)
    out[f"class|{nm}"] = {"m1_mean": float(net[cls_m1].mean()), "m1_p_pos": float((net[cls_m1] > 0).mean()),
                          "m1_p_lt_m5": float((net[cls_m1] < -0.05).mean()), "p1_mean": float(net[cls_p1].mean()),
                          "n_m1": int(cls_m1.sum())}
    # random F&O short (all F&O rows) mean per trade
    mf = pm & E & fno & np.isfinite(r) & np.isfinite(prod)
    out[f"fno_univ_short|{nm}"] = float(short_net_sig[mf].mean())
for k, v in out.items():
    if isinstance(v, dict) and "spread_mean" in v:
        print(k, "spread", round(v["spread_mean"], 5), "t0", round(v["nonoverlap_t_offset0"], 2), "t_med", round(v["nonoverlap_t_median_of_20_offsets"], 2),
              "t_rng", [round(x, 2) for x in v["nonoverlap_t_range"]], "nw", round(v["nw_t_lag20"], 2), "rho", round(v["spearman"], 3),
              "d1", round(v["decile_means"][1], 5), "d10", round(v["decile_means"][10], 5), "univ", round(v["universe_mean"], 5))
    else:
        print(k, v)
json.dump(out, open(OUT + "/v1_outcomes.json", "w"), indent=1)

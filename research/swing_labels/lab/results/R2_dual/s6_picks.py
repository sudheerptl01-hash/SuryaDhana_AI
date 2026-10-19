"""Stage 6: what do the different scores actually buy? Top-20 picks on every 5th date (dev/holdout):
characteristics (beta, vol, size, trend), realised net/resid, by market regime, and top-20 overlap
between scores (how different is a DUAL book from a pure-relative book?)."""
import os
import time

import numpy as np
import pandas as pd

from common import OUT, L, save, xs_pct, regime

t0 = time.time()
P = L.load_panel(["date"])
F = L.load_features(["beta_60", "vol_20", "log_turn20", "dist_sma200", "xr_mom60", "mom_5", "mkt_dist_sma200",
                     "mkt_mom20"])
U = np.load(f"{OUT}/meta.npz")["U"]
dates = P["date"].values.astype("datetime64[D]")
Z = np.load(f"{OUT}/labels_h20.npz")
r = Z["r"].astype("float64")
resid = Z["resid"].astype("float64")
m = Z["m"].astype("float64")
reg = regime(F["mkt_dist_sma200"].values, F["mkt_mom20"].values)


def ld(t):
    fn = f"{OUT}/wf_{t}.npz"
    return np.load(fn)["score"].astype("float64") if os.path.exists(fn) else None


SC = {k: ld(f"M_{k}") for k in ("REL", "RUP", "DUAL", "DUALP", "ABS", "BAR", "DUALmc")}
SC = {k: v for k, v in SC.items() if v is not None}
pc = {k: xs_pct(v, dates, U) for k, v in SC.items()}
if "ABS" in pc:
    SC["SUM_REL_ABS"] = pc["REL"] + pc["ABS"]
    SC["AND_REL_ABS50"] = np.where(pc["ABS"] >= 0.5, SC["REL"], np.nan)
cal = np.unique(dates[U & (dates >= np.datetime64("2023-01-01"))])[::5]
rows_on = pd.Series(np.flatnonzero(U)).groupby(dates[U]).apply(np.array)
feat = {"beta": F["beta_60"].values.astype(float), "ann_vol": F["vol_20"].values.astype(float) * np.sqrt(252),
        "log_turn": F["log_turn20"].values.astype(float),
        "above_sma200": (F["dist_sma200"].values > 0).astype(float), "xr_mom60": F["xr_mom60"].values.astype(float),
        "mom_5": F["mom_5"].values.astype(float)}
recs = []
picks = {k: {} for k in SC}
for d in cal:
    cand = rows_on.get(d)
    if cand is None:
        continue
    for k, s in SC.items():
        c = cand[np.isfinite(s[cand])]
        if len(c) == 0:
            continue
        p = c[np.argsort(-s[c], kind="stable")[:20]]
        picks[k][d] = set(p.tolist())
        rec = {"d": d, "score": k, "reg": reg[p[0]], "mkt_win": float(np.nanmedian(m[cand])),
               "net_bps": float(np.nanmean(r[p] - 0.005) * 1e4), "resid_bps": float(np.nanmean(resid[p]) * 1e4),
               "univ_net_bps": float(np.nanmean(r[cand] - 0.005) * 1e4)}
        for fk, fv in feat.items():
            rec[fk] = float(np.nanmean(fv[p]))
            rec[f"univ_{fk}"] = float(np.nanmean(fv[cand]))
        recs.append(rec)
df = pd.DataFrame(recs)
df["win"] = np.where(df.d < np.datetime64("2026-01-01"), "dev", "hold")
df["mkt_dir"] = np.where(df.mkt_win > 0, "mktUp", "mktDn")
cols = ["net_bps", "resid_bps", "beta", "ann_vol", "log_turn", "above_sma200", "xr_mom60", "mom_5"]
out = {}
for w in ("dev", "hold"):
    g = df[df.win == w]
    out[w] = {"all": g.groupby("score")[cols].mean().round(4).to_dict(orient="index"),
              "by_regime": {f"{a}|{b}": v for (a, b), v in
                            g.groupby(["score", "reg"])[cols].mean().round(4).to_dict(orient="index").items()},
              "by_mkt_dir": {f"{a}|{b}": v for (a, b), v in
                             g.groupby(["score", "mkt_dir"])[cols].mean().round(4).to_dict(orient="index").items()},
              "universe": g[g.score == "REL"][[f"univ_{c}" for c in ("beta", "ann_vol", "log_turn", "above_sma200",
                                                                    "xr_mom60", "mom_5")] + ["univ_net_bps"]].mean().round(4).to_dict()}
# overlap of top-20 sets vs REL
ov = {}
for k in SC:
    if k == "REL":
        continue
    j = [len(picks[k][d] & picks["REL"][d]) / 20 for d in picks["REL"] if d in picks[k]]
    ov[k] = float(np.mean(j))
out["top20_overlap_with_REL"] = ov
if "RUP" in picks:
    out["top20_overlap_DUAL_vs_RUP"] = float(np.mean([len(picks["DUAL"][d] & picks["RUP"][d]) / 20
                                                     for d in picks["RUP"] if d in picks.get("DUAL", {})]))
save("s6_picks", out)
print(pd.DataFrame(out["dev"]["all"]).T.round(3).to_string())
print(pd.DataFrame(out["hold"]["all"]).T.round(3).to_string())
print(ov)
print("done", round(time.time() - t0, 1))

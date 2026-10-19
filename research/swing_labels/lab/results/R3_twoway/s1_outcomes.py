"""Stage 1: outcome tables. Absolute 20d net returns (open t+1 -> close t+20, minus 50 bps) for the realised
XR_neumom h=20 classes (ex-post, coherence) and for PROD score deciles (ex-ante, tradable), by year and by
ex-ante market state; top-minus-bottom spread + monotonicity; same within F&O proxy (re-ranked) with the
futures-short view (short net = -r + 1D-rate carry over the window - 25 bps)."""
import sys
import numpy as np
import pandas as pd
sys.path.insert(0, "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab")
import r3common as C
L = C.L
C.set_agent("R3_twoway")
LAB = C.LAB
P = L.load_panel(["date"])
F = L.load_features(["elig_base", "fno_proxy", "mkt_dist_sma200", "mkt_mom20"])
d = P["date"].values.astype("datetime64[D]")
E = F["elig_base"].values.astype(bool)
fno = F["fno_proxy"].values.astype(bool)
z = np.load(f"{LAB}/results/R3_devil/label_h20_neumom.npz")
pct, r = z["pct"].astype("float64"), z["r"].astype("float64")
prod = np.load(f"{LAB}/results/_lead/prod_h20.npz", allow_pickle=True)["prod"].astype("float64")
net = r - 0.005
cal = np.unique(d)
gi = np.searchsorted(cal, d)
cl1d = L.market_series("Nifty 1D Rate Index")["close"].reindex(pd.DatetimeIndex(cal)).ffill().values
j20 = np.minimum(gi + 20, len(cal) - 1)
carry20 = cl1d[j20] / cl1d[gi] - 1
short_net = -r + carry20 - 0.0025
yr = pd.DatetimeIndex(d).year.values
above = F["mkt_dist_sma200"].values > 0
mup = F["mkt_mom20"].values > 0
C.log("loaded")

cls = np.where(pct > 0.7, 1, np.where(pct <= 0.3, -1, 0)).astype(float)
cls[~np.isfinite(pct)] = np.nan
base = E & np.isfinite(r) & np.isfinite(pct)


def stats(m, x=net):
    v = x[m]
    v = v[np.isfinite(v)]
    if len(v) == 0:
        return None
    return {"n": int(len(v)), "mean": float(v.mean()), "median": float(np.median(v)),
            "p_pos": float((v > 0).mean()), "p_lt_m5": float((v < -0.05).mean())}


PERIODS = {"dev": (yr >= 2023) & (yr <= 2025), "2026": yr == 2026}
for y in range(2021, 2027):
    PERIODS[str(y)] = yr == y
STATES = {"all": np.ones(len(d), bool), "above200": above, "below200": ~above, "mom20_up": mup, "mom20_down": ~mup}
out = {"label_classes": {}, "label_classes_short_view_fno": {}}
for pn, pm in PERIODS.items():
    for sn, sm in STATES.items():
        if sn != "all" and pn not in ("dev", "2026"):
            continue
        key = f"{pn}|{sn}"
        mm = base & pm & sm
        out["label_classes"][key] = {"universe": stats(mm), **{str(int(c)): stats(mm & (cls == c)) for c in (1, 0, -1)},
                                     "share_rows": float(mm.sum())}
        mf = mm & fno
        out["label_classes_short_view_fno"][key] = {
            "minus1_short_net": stats(mf & (cls == -1), short_net), "plus1_net": stats(mf & (cls == 1)),
            "all_fno_short_net": stats(mf, short_net)}
C.log("classes done")


def deciles(mask_rank):
    s = pd.Series(np.where(mask_rank & np.isfinite(prod), prod, np.nan))
    rk = s.groupby(d).rank(pct=True).values
    dec = np.ceil(rk * 10).clip(1, 10)
    dec[~np.isfinite(rk)] = np.nan
    return dec


def spread_stats(dec, m, x=net):
    df = pd.DataFrame({"d": d[m], "dec": dec[m], "x": x[m]})
    g = df.groupby(["d", "dec"]).x.mean().unstack()
    if 10 not in g.columns or 1 not in g.columns:
        return None
    sp = (g[10] - g[1]).dropna()
    nov = sp.iloc[::20]
    dm = df.groupby("dec").x.mean()
    inv = int((np.diff(dm.values) < 0).sum())
    rho = float(pd.Series(dm.index.values).corr(pd.Series(dm.values), method="spearman"))
    return {"top_minus_bottom_mean": float(sp.mean()), "n_dates": int(len(sp)),
            "nonoverlap_t": float(nov.mean() / (nov.std() / np.sqrt(len(nov)))) if len(nov) > 3 else None,
            "nw_t_lag20": L.nw_t(sp.values, 20), "share_dates_positive": float((sp > 0).mean()),
            "decile_means": {str(int(k)): float(v) for k, v in dm.items()}, "spearman_decile_vs_mean": rho,
            "adjacent_inversions_of_9": inv}


dec_all = deciles(E)
dec_fno = deciles(E & fno)
okp = E & np.isfinite(r) & np.isfinite(prod)
for nm, dec, extra in (("prod_deciles_all", dec_all, None), ("prod_deciles_fno", dec_fno, fno)):
    res = {}
    for pn, pm in PERIODS.items():
        if int(pn) if pn.isdigit() else 0:
            if int(pn) < 2023:
                continue
        for sn, sm in STATES.items():
            if sn != "all" and pn not in ("dev", "2026"):
                continue
            mm = okp & pm & sm & np.isfinite(dec)
            if extra is not None:
                mm &= extra
            if mm.sum() == 0:
                continue
            row = {"universe": stats(mm)}
            for k in range(1, 11):
                row[f"d{k}"] = stats(mm & (dec == k))
            row["spread"] = spread_stats(dec, mm)
            if extra is not None:
                row["d1_short_net"] = stats(mm & (dec == 1), short_net)
                row["d10_long_fut_net"] = stats(mm & (dec == 10), r - carry20 - 0.0025)
                row["universe_short_net"] = stats(mm, short_net)
                row["short_spread"] = spread_stats(dec, mm, short_net)
            res[f"{pn}|{sn}"] = row
    out[nm] = res
    C.log(nm, "done")
# share of time in each state (signal dates)
st = {}
for pn in ("dev", "2026"):
    m = PERIODS[pn] & E
    dd = pd.DataFrame({"d": d[m], "a": above[m], "u": mup[m]}).groupby("d").first()
    st[pn] = {"share_dates_above200": float(dd.a.mean()), "share_dates_mom20_up": float(dd.u.mean()), "n_dates": int(len(dd))}
out["state_shares"] = st
out["notes"] = ["net = open[t+1]->close[t+20] - 0.005 (CA-adjusted, incl. dividends); rows = elig_base with valid 20d window",
                "label classes are realised (ex-post); PROD deciles are ex-ante (per-date rank among elig_base rows with finite PROD)",
                "F&O deciles re-ranked within fno_proxy & elig_base; short_net = -r + Nifty 1D Rate carry over the window - 25 bps",
                "overlapping 20d windows: rows are not independent; spread t-stats use every 20th date (non-overlap) and NW lag 20"]
C.save("s1_outcomes", out)
# compact console view
for nm in ("prod_deciles_all", "prod_deciles_fno"):
    for k in ("dev|all", "2026|all"):
        rw = out[nm][k]
        print(nm, k, "univ", round(rw["universe"]["mean"], 4), "d1", round(rw["d1"]["mean"], 4), "d10", round(rw["d10"]["mean"], 4),
              "spread", round(rw["spread"]["top_minus_bottom_mean"], 4), "t", round(rw["spread"]["nonoverlap_t"], 2),
              "rho", round(rw["spread"]["spearman_decile_vs_mean"], 3), "inv", rw["spread"]["adjacent_inversions_of_9"])
        if nm.endswith("fno"):
            print("   d1 short net", C.short(rw["d1_short_net"]), " univ short", C.short(rw["universe_short_net"]))
for k in ("dev|all", "2026|all", "dev|above200", "dev|below200", "2026|above200", "2026|below200", "dev|mom20_down", "2026|mom20_down"):
    rw = out["label_classes"][k]
    print("classes", k, {c: (round(rw[c]["mean"], 4), round(rw[c]["p_pos"], 3)) for c in ("1", "0", "-1") if rw[c]})
print(st)

"""Stage 4d: is the relative (selection) edge regime-dependent?

Per signal date g (all 5 phases => every trading day), cohort mean net trade return (20d hold,
next-open entry, 50/80 bps) for XR20 picks, the 5-seed random top-20 mean and the EW universe.
excess_g = XR20_g - RND_g (selection skill); mkt_g = EW_g (what timing must predict).
For each regime signal: mean excess when risk-on vs risk-off, NW t (lag 20, overlapping holds);
plus the slope of excess on mkt (does selection skill depend on market direction?).
Also the event rate of the timing targets by regime (bull/bear x up20/dn20) for the scorecard.
"""
import pickle
import time

import numpy as np
import pandas as pd

from common import OUT, save, nw_mean_diff_t, hac_slope, nw_t

t0 = time.time()
with open(f"{OUT}/paths_cache.pkl", "rb") as fh:
    cache = pickle.load(fh)
S = pd.read_parquet(f"{OUT}/timing_signals.parquet")
D = pd.read_parquet(f"{OUT}/dateset.parquet")
cal = D.index.values.astype("datetime64[D]")
RULES = ["R200", "RBR", "RVIX", "RM60", "VOTE"]
MODELS = [f"{m}_{t}" for m in ("LOG4", "LOG10", "LGB10") for t in ("N0", "N1", "E0")]


def per_g(book, wname, cost):
    out = {}
    for ph in range(5):
        for (g, mnet, hit, npk) in cache[(book, wname, cost, ph)]["tstats"]:
            out[g] = mnet
    return pd.Series(out).sort_index()


res = {}
for wname in ("DEV", "HOLD"):
    for cost in (50, 80):
        xr = per_g("XR20", wname, cost)
        rnd = pd.concat([per_g(f"RND20_s{s}", wname, cost) for s in range(1, 6)], axis=1).mean(1)
        ew = per_g("EW", wname, cost)
        df = pd.DataFrame({"xr": xr, "rnd": rnd, "ew": ew}).dropna()
        df["ex"] = df.xr - df.rnd
        g = df.index.values.astype(int)
        rec = {"n_dates": int(len(df)), "xr_mean": float(df.xr.mean()), "rnd_mean": float(df.rnd.mean()),
               "ew_mean": float(df.ew.mean()), "excess_mean": float(df.ex.mean()), "excess_nw_t": nw_t(df.ex.values, 20)}
        b, t = hac_slope(df.ex.values, df.ew.values, 20)
        rec["excess_on_mkt_slope"], rec["excess_on_mkt_t"] = b, t
        rec["corr_excess_mkt"] = float(np.corrcoef(df.ex, df.ew)[0, 1])
        bx, tx = hac_slope(df.xr.values, df.ew.values, 20)
        rec["xr_beta_to_ew"], rec["xr_beta_t"] = bx, tx
        # up vs down market cohorts
        up = df.ew > 0
        rec["excess_when_mkt_up"] = float(df.ex[up].mean())
        rec["excess_when_mkt_down"] = float(df.ex[~up].mean())
        rec["share_mkt_up"] = float(up.mean())
        cond = {}
        for sn in RULES + MODELS:
            st = S[sn].values[g]
            ok = np.isfinite(st)
            if ok.sum() < 30 or np.nanstd(st[ok]) == 0:
                continue
            on = st[ok] >= 0.5
            d_ex, t_ex = nw_mean_diff_t(df.ex.values[ok], on.astype(float), 20)
            d_ew, t_ew = nw_mean_diff_t(df.ew.values[ok], on.astype(float), 20)
            cond[sn] = {"on_share": float(on.mean()),
                        "excess_on": float(df.ex.values[ok][on].mean()) if on.any() else None,
                        "excess_off": float(df.ex.values[ok][~on].mean()) if (~on).any() else None,
                        "excess_on_minus_off": d_ex, "t": t_ex,
                        "ew_on": float(df.ew.values[ok][on].mean()) if on.any() else None,
                        "ew_off": float(df.ew.values[ok][~on].mean()) if (~on).any() else None,
                        "ew_on_minus_off": d_ew, "t_ew": t_ew}
        rec["by_signal"] = cond
        res[f"{wname}_{cost}"] = rec
        print(wname, cost, {k: (round(v, 4) if isinstance(v, float) else v) for k, v in rec.items() if k != "by_signal"}, flush=True)
        if cost == 50:
            for sn, c in cond.items():
                print(f"   {sn:9s} on {c['on_share']:.2f} excess on {c['excess_on']*100 if c['excess_on'] is not None else np.nan:+.2f}% "
                      f"off {c['excess_off']*100 if c['excess_off'] is not None else np.nan:+.2f}% (diff t {c['t']:+.2f}) | "
                      f"EW on {c['ew_on']*100 if c['ew_on'] is not None else np.nan:+.2f}% off "
                      f"{c['ew_off']*100 if c['ew_off'] is not None else np.nan:+.2f}% (t {c['t_ew']:+.2f})", flush=True)
save("s4d_conditional_selection_edge", res)

# ------------------------------------------------------------------ event rates of timing targets by regime
reg = np.where(D.mkt_dist_sma200 > 0, "bull", "bear")
reg = np.char.add(reg.astype(str), np.where(D.mkt_mom20 > 0, "_up20", "_dn20"))
reg = np.where(np.isfinite(D.mkt_dist_sma200) & np.isfinite(D.mkt_mom20), reg, "na")
ev = {}
for nm, (a, b) in (("DEV", ("2023-01-01", "2025-12-31")), ("HOLD", ("2026-01-01", "2026-12-31")),
                   ("PRE", ("2021-09-01", "2022-12-31"))):
    m = (D.index >= a) & (D.index <= b)
    out = {}
    for r in ("bull_up20", "bull_dn20", "bear_up20", "bear_dn20"):
        mm = m & (reg == r)
        sub = D[mm]
        out[r] = {"dates": int(mm.sum()),
                  "N0": float((sub.n500_f20.dropna() > 0).mean()) if mm.sum() else None,
                  "N1": float((sub.n500_f20.dropna() > 0.01).mean()) if mm.sum() else None,
                  "E0": float((sub.ew_f20.dropna() > 0).mean()) if mm.sum() else None,
                  "n500_f20_mean": float(sub.n500_f20.mean()) if mm.sum() else None,
                  "ew_f20_mean": float(sub.ew_f20.mean()) if mm.sum() else None}
    ev[nm] = out
# monthly stability of N0/E0 event rates
mon = D[(D.index >= "2023-01-01") & (D.index <= "2025-12-31")].copy()
mon["m"] = mon.index.to_period("M")
mm_ = mon.groupby("m").agg(N0=("n500_f20", lambda s: (s > 0).mean()), E0=("ew_f20", lambda s: (s > 0).mean()))
ev["DEV_monthly"] = {k: {"mean": float(mm_[k].mean()), "std": float(mm_[k].std()), "min": float(mm_[k].min()),
                         "max": float(mm_[k].max()), "share_months_all_or_nothing": float(((mm_[k] == 0) | (mm_[k] == 1)).mean())}
                     for k in ("N0", "E0")}
save("s4d_target_event_rates_by_regime", ev)
for k, v in ev.items():
    print(k, v)
print("total", round(time.time() - t0, 1))

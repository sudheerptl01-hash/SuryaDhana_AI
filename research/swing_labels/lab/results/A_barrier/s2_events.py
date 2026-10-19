"""Stage 2: full scorecard event reports for shortlisted configs (chosen from the
2023-2025 grid stats in s1) + save label arrays for walk-forward.
"""
import time

import numpy as np
import pandas as pd

from abar import L, OUT, FwdMats, barrier, tau_label, geom, save_json, update_results, load_base

SHORT = {
    # id: (h, kind, a, b)
    "B20_f2.0_2.0": (20, "fix", 2.0, 2.0),
    "B20_f3.0_1.5": (20, "fix", 3.0, 1.5),
    "B10_f2.0_1.5": (10, "fix", 2.0, 1.5),
    "B15_f2.0_2.0": (15, "fix", 2.0, 2.0),
    "B10_s0.75_0.75": (10, "sqrt", 0.75, 0.75),
    "B10_s1.5_1.0": (10, "sqrt", 1.5, 1.0),   # D_setups common label (for reference)
}

t0 = time.time()
P, F, fw = load_base()
n = len(P)
elig = F["elig_base"].values.astype(bool)
fno = F["fno_proxy"].values.astype(bool)
rows = np.flatnonzero(elig)
M = FwdMats(P, fw, rows)
atr = F["atr_pct"].values.astype("float64")[rows]
dates = P["date"].values.astype("datetime64[D]")
year = pd.DatetimeIndex(P["date"].values).year.values
print("loaded", round(time.time() - t0, 1), flush=True)


def full(arr_rows, fill=np.nan, dtype="float64"):
    out = np.full(n, fill, dtype=dtype)
    out[rows] = arr_rows
    return out


def autocorr_lags(lab_full, mask, h, sample=300000, seed=0):
    v = np.where(mask, lab_full, np.nan)
    out = {}
    rng = np.random.default_rng(seed)
    for k in sorted(set([1, 2, 5, h // 2, h, h + 5])):
        vl = fw.at(v, -k)
        ok = ~np.isnan(v) & ~np.isnan(vl)
        idx = np.flatnonzero(ok)
        if len(idx) > sample:
            idx = rng.choice(idx, sample, replace=False)
        out[k] = float(np.corrcoef(v[idx], vl[idx])[0, 1])
    # all lags 1..h for N_eff
    rs = []
    for k in range(1, h + 1):
        vl = fw.at(v, -k)
        ok = ~np.isnan(v) & ~np.isnan(vl)
        idx = np.flatnonzero(ok)
        if len(idx) > sample:
            idx = rng.choice(idx, sample, replace=False)
        rs.append(float(np.corrcoef(v[idx], vl[idx])[0, 1]))
    infl = 1 + 2 * sum(max(r, 0) for r in rs)
    return out, infl


res = {}
saved = {}
for cid, (h, kind, a, b) in SHORT.items():
    pm, sm = geom(kind, a, b, h)
    out = {"h": h, "kind": kind, "a": a, "b": b, "pt_mult_atr": pm, "sl_mult_atr": sm}
    for side in ("long", "short"):
        bb = barrier(M, pm * atr, sm * atr, h, side)
        v = bb["valid"]
        lab50 = tau_label(bb, 50)
        labT = np.where(v, bb["touch"].astype(float), np.nan)  # touch-only (tau=inf)
        Lf = full(lab50)
        mask = elig & ~np.isnan(Lf)
        rep = L.event_report(Lf, mask, P, F, positive=1)
        rep.pop("monthly_pos", None) if False else None
        rep["monthly_pos"].pop("series", None)
        # fno subset
        repf = L.event_report(Lf, mask & fno, P, None, positive=1)
        repf["monthly_pos"].pop("series", None)
        # touch-only label
        repT = L.event_report(full(labT), mask, P, None, positive=1)
        repT["monthly_pos"].pop("series", None)
        # date-level regime dependence: daily P(+1) vs Nifty500 fwd return same window
        mf = L.market_fwd(P, h)
        df = pd.DataFrame({"d": dates[mask], "pos": (Lf[mask] == 1).astype(float), "mf": mf[mask],
                           "y": year[mask]})
        g = df.groupby("d").agg(pos=("pos", "mean"), mf=("mf", "first"), y=("y", "first"))
        gs = g[(g.y >= 2023) & (g.y <= 2025)].dropna()
        reg = {"corr_daily_pos_vs_mktfwd_all": float(g.dropna().pos.corr(g.dropna().mf)),
               "corr_daily_pos_vs_mktfwd_2023_25": float(gs.pos.corr(gs.mf)),
               "daily_pos_p05_p95": [float(g.pos.quantile(0.05)), float(g.pos.quantile(0.95))],
               "daily_pos_std": float(g.pos.std())}
        ac, infl = autocorr_lags(Lf, mask, h)
        # net-by-class at 50 and 80 bps, by period
        net = bb["ret"]
        cls = {}
        for c in (1, -1, 0):
            mm = v & (lab50 == c)
            cls[str(c)] = {"share": float(mm.sum() / v.sum()),
                           "mean_gross": float(net[mm].mean()) if mm.any() else None,
                           "mean_net50": float(net[mm].mean() - 0.005) if mm.any() else None,
                           "share_net80_pos": float((net[mm] - 0.008 > 0).mean()) if mm.any() else None,
                           "median_k": float(np.median(bb["k"][mm])) if mm.any() else None}
        yr = year[rows]
        per = {}
        for pname, pm_ in (("2021_22", (yr <= 2022)), ("2023_25", (yr >= 2023) & (yr <= 2025)), ("2026", yr == 2026)):
            mm = v & pm_
            per[pname] = {"n": int(mm.sum()), "p_pt": float((bb["touch"][mm] == 1).mean()),
                          "p_sl": float((bb["touch"][mm] == -1).mean()), "p_time": float((bb["touch"][mm] == 0).mean()),
                          "p1": float((lab50[mm] == 1).mean()), "m1": float((lab50[mm] == -1).mean()),
                          "z": float((lab50[mm] == 0).mean()),
                          "uncond_net50": float(np.nanmean(net[mm]) - 0.005),
                          "mean_k": float(bb["k"][mm].mean())}
        out[side] = {"event_report_tau50": rep, "fno_event_report_tau50": repf, "touch_only_report": repT,
                     "regime_daily": reg, "autocorr": ac, "variance_inflation_1p2sum_rho": infl,
                     "class_pnl": cls, "by_period": per}
        saved[f"{cid}_{side}_lab"] = Lf.astype(np.float32)
        saved[f"{cid}_{side}_ret"] = full(bb["ret"]).astype(np.float32)
        saved[f"{cid}_{side}_k"] = full(bb["k"].astype(float)).astype(np.float32)
        print(cid, side, "p1", round(rep["overall"].get("1.0", np.nan), 3), "acf1", round(ac[1], 3),
              "infl", round(infl, 2), reg["corr_daily_pos_vs_mktfwd_2023_25"], round(time.time() - t0, 1), flush=True)
    res[cid] = out
    save_json(f"{OUT}/events_shortlist.json", res)

np.savez_compressed(f"{OUT}/labels_shortlist.npz", **saved)
update_results("shortlist_ids", list(SHORT.keys()))
print("total", round(time.time() - t0, 1))

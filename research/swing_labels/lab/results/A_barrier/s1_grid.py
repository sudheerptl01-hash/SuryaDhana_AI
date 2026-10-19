"""Stage 1: validate vectorized barrier vs lablib, then full event-rate grid.
Grid: h in {5,10,15,20} x side {long,short} x geometry
  fix : pt,sl in {1.5,2,3} x atr_pct
  sqrt: pt=a*atr*sqrt(h), sl=b*atr*sqrt(h), a,b in {0.75,1,1.5}
Tau dead zone {0,50,100} bps applied to time exits.
All stats on elig_base & valid rows.
"""
import time

import numpy as np
import pandas as pd

from abar import L, OUT, FwdMats, barrier, tau_label, geom, save_json, update_results, load_base

t0 = time.time()
P, F, fw = load_base()
elig = F["elig_base"].values.astype(bool)
rows = np.flatnonzero(elig)
print("loaded", len(P), len(rows), round(time.time() - t0, 1), flush=True)
M = FwdMats(P, fw, rows)
atr = F["atr_pct"].values.astype("float64")[rows]
print("mats", round(time.time() - t0, 1), flush=True)

# ---------------- validation vs lablib ----------------
val = {}
for (h, pt, sl, side) in ((10, 2.0, 1.5, "long"), (20, np.sqrt(20) * 1.0, np.sqrt(20) * 0.75, "short")):
    ref = L.barrier_labels(P, F, fw, h=h, pt=pt, sl=sl, side=side)
    mine = barrier(M, pt * atr, sl * atr, h, side)
    rl, rr = ref["label"][rows], ref["ret"][rows]
    both = ~np.isnan(rl) | ~np.isnan(mine["label0"])
    val[f"h{h}_{side}"] = {
        "n_cmp": int(both.sum()),
        "label_mismatch": int(np.sum((rl != mine["label0"]) & both)),
        "ret_max_abs_diff": float(np.nanmax(np.abs(rr - mine["ret"]))),
        "nan_mismatch": int(np.sum(np.isnan(rl) != np.isnan(mine["label0"]))),
    }
    del ref
print("validation", val, flush=True)
update_results("validation_vs_lablib", val)

# ---------------- date / regime helpers ----------------
d = pd.DatetimeIndex(P["date"].values[rows])
year = d.year.values
mon = d.to_period("M").astype(str).values
mon_codes, mon_uni = pd.factorize(mon, sort=True)
mk = L.market_series("Nifty 500")["close"]
mret = mk.resample("ME").last().pct_change()
mret.index = mret.index.to_period("M").astype(str)
mret_al = mret.reindex(mon_uni).values
fm = F.iloc[rows]
reg = np.where(fm["mkt_dist_sma200"].values > 0, "bull", "bear")
reg = np.char.add(reg.astype(str), np.where(fm["mkt_mom20"].values > 0, "_up20", "_dn20"))
reg_codes, reg_uni = pd.factorize(reg, sort=True)
sel = (year >= 2023) & (year <= 2025)
hold = year == 2026
years = sorted(np.unique(year))


def share(mask_cls, v):
    n = v.sum()
    return float(mask_cls[v].sum() / n) if n else np.nan


def monthly(pos, v, mask=None):
    mm = v if mask is None else (v & mask)
    num = np.bincount(mon_codes[mm], weights=pos[mm].astype(float), minlength=len(mon_uni))
    den = np.bincount(mon_codes[mm], minlength=len(mon_uni))
    ok = den > 500
    s = num[ok] / den[ok]
    mr = mret_al[ok]
    j = np.isfinite(mr)
    return {"mean": float(s.mean()), "std": float(s.std(ddof=1)), "min": float(s.min()), "max": float(s.max()),
            "corr_mkt": float(np.corrcoef(s[j], mr[j])[0, 1])}


rec = []
NET = 0.005
for h in (5, 10, 15, 20):
    for side in ("long", "short"):
        for kind, grid in (("fix", (1.5, 2.0, 3.0)), ("sqrt", (0.75, 1.0, 1.5))):
            for a in grid:
                for b in grid:
                    pm, sm = geom(kind, a, b, h)
                    bb = barrier(M, pm * atr, sm * atr, h, side)
                    v = bb["valid"]
                    net = bb["ret"] - NET
                    r = {"h": h, "side": side, "kind": kind, "a": a, "b": b, "pt_mult": pm, "sl_mult": sm,
                         "n": int(v.sum()),
                         "med_pt_pct": float(np.median(pm * atr[v])), "med_sl_pct": float(np.median(sm * atr[v])),
                         "sh_pt": share(bb["touch"] == 1, v), "sh_sl": share(bb["touch"] == -1, v),
                         "sh_time": share(bb["touch"] == 0, v),
                         "medk_pt": float(np.median(bb["k"][v & (bb["touch"] == 1)])) if (v & (bb["touch"] == 1)).any() else np.nan,
                         "medk_sl": float(np.median(bb["k"][v & (bb["touch"] == -1)])) if (v & (bb["touch"] == -1)).any() else np.nan,
                         "meank_all": float(bb["k"][v].mean()),
                         "net_all": float(np.nanmean(net[v])),
                         "net_all_sel": float(np.nanmean(net[v & sel])), "net_all_2026": float(np.nanmean(net[v & hold])),
                         "net_time": float(np.nanmean(net[v & (bb["touch"] == 0)])) if (v & (bb["touch"] == 0)).any() else np.nan}
                    for tau in (0, 50, 100):
                        lab = tau_label(bb, tau)
                        for c, nm in ((1, "p1"), (-1, "m1"), (0, "z")):
                            r[f"{nm}_t{tau}"] = share(lab == c, v)
                        for c, nm in ((1, "p1"), (-1, "m1"), (0, "z")):
                            mm = v & (lab == c)
                            r[f"net_{nm}_t{tau}"] = float(net[mm].mean()) if mm.any() else np.nan
                        r[f"coh_p1_t{tau}"] = float((net[v & (lab == 1)] > 0).mean())
                        r[f"coh_m1_t{tau}"] = float((net[v & (lab == -1)] < 0).mean())
                        if tau in (0, 50):
                            pos = lab == 1
                            for yy in years:
                                r[f"p1_t{tau}_{yy}"] = share(pos, v & (year == yy))
                            r[f"p1_t{tau}_sel"] = share(pos, v & sel)
                            r[f"m1_t{tau}_sel"] = share(lab == -1, v & sel)
                            r[f"p1_t{tau}_2026"] = share(pos, v & hold)
                            r[f"m1_t{tau}_2026"] = share(lab == -1, v & hold)
                            mo = monthly(pos, v)
                            for kk_, vv_ in mo.items():
                                r[f"mon_{kk_}_t{tau}"] = vv_
                            mo = monthly(pos, v, sel)
                            r[f"mon_std_sel_t{tau}"] = mo["std"]
                            r[f"mon_corr_sel_t{tau}"] = mo["corr_mkt"]
                            for ri, rn in enumerate(reg_uni):
                                r[f"p1_t{tau}_{rn}"] = share(pos, v & (reg_codes == ri))
                    # selection-period net by class (tau=50)
                    lab50 = tau_label(bb, 50)
                    for c, nm in ((1, "p1"), (-1, "m1"), (0, "z")):
                        mm = v & (lab50 == c) & sel
                        r[f"net_{nm}_t50_sel"] = float(net[mm].mean()) if mm.any() else np.nan
                        mm = v & (lab50 == c) & hold
                        r[f"net_{nm}_t50_2026"] = float(net[mm].mean()) if mm.any() else np.nan
                    rec.append(r)
                    del bb, net
        print("done h", h, side, round(time.time() - t0, 1), flush=True)

G = pd.DataFrame(rec)
G.to_csv(f"{OUT}/grid.csv", index=False)
update_results("grid_n_configs", len(G))
print("total", round(time.time() - t0, 1))

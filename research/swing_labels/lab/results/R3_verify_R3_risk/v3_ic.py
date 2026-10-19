"""R3_verify_R3_risk v3: own per-date rank IC of PROD vs the frozen label pct (scipy rankdata loop),
plus top-20 relative hit and top-20 raw lead over the universe. Saves v3_ic.npz / v3_out.json."""
import json
import sys

import numpy as np
import pandas as pd
from scipy.stats import rankdata

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
OUT = LAB + "/results/R3_verify_R3_risk"
sys.path.insert(0, LAB)
import lablib as L  # noqa: E402

P = L.load_panel(["date"])
F = L.load_features(["elig_base"])
E = F["elig_base"].values.astype(bool)
del F
z = np.load(f"{LAB}/results/_lead/prod_h20.npz", allow_pickle=True)
prod, pct = z["prod"].astype(float), z["pct"].astype(float)
lab = np.load(f"{LAB}/results/R3_devil/label_h20_neumom.npz")
r = lab["r"].astype(float)
d = P["date"].values.astype("datetime64[D]")
del P
cal = np.unique(d)
gi = np.searchsorted(cal, d)
m = E & np.isfinite(prod) & np.isfinite(pct)
rows = np.flatnonzero(m)
o = np.argsort(gi[rows], kind="stable")
rows = rows[o]
bounds = np.searchsorted(gi[rows], np.arange(len(cal) + 1))
IC = np.full(len(cal), np.nan)
REL = np.full(len(cal), np.nan)
TOPX = np.full(len(cal), np.nan)
for g in range(len(cal)):
    rr = rows[bounds[g]:bounds[g + 1]]
    if len(rr) < 30:
        continue
    a, b = rankdata(prod[rr]), rankdata(pct[rr])
    IC[g] = np.corrcoef(a, b)[0, 1]
# top-20 metrics use all elig rows with finite PROD (label may be NaN -> skipped)
ms = E & np.isfinite(prod)
rows2 = np.flatnonzero(ms)
rows2 = rows2[np.argsort(gi[rows2], kind="stable")]
b2 = np.searchsorted(gi[rows2], np.arange(len(cal) + 1))
for g in range(len(cal)):
    rr = rows2[b2[g]:b2[g + 1]]
    if len(rr) == 0:
        continue
    top = rr[np.argsort(-prod[rr], kind="stable")[:20]]
    tp = pct[top]
    if np.isfinite(tp).any():
        REL[g] = np.nanmean(np.where(np.isfinite(tp), (tp > 0.5).astype(float), np.nan))
    if np.isfinite(r[rr]).any() and np.isfinite(r[top]).any():
        TOPX[g] = np.nanmean(r[top]) - np.nanmean(r[rr])
s = pd.DataFrame({"ic": IC, "rel": REL, "topx": TOPX}, index=pd.DatetimeIndex(cal))
s = s[s.index >= "2023-01-01"]
g_dev_end = int(np.searchsorted(cal, np.datetime64("2025-12-31"), side="right")) - 1
dev_last = pd.Timestamp(cal[g_dev_end - 20])
dev = s[s.index <= dev_last]
hold = s[s.index >= "2026-01-01"]
wk = dev.ic.dropna().groupby(dev.ic.dropna().index.to_period("W-FRI")).mean()
r13 = wk.rolling(13).mean().dropna()
wk26 = hold.ic.dropna().groupby(hold.ic.dropna().index.to_period("W-FRI")).mean()
out = {"dev_last_signal": str(dev_last.date()), "ic_dev_mean": float(dev.ic.mean()), "ic_2026_mean": float(hold.ic.mean()),
       "ic_dev_n": int(dev.ic.notna().sum()), "ic_2026_n": int(hold.ic.notna().sum()),
       "ic_2026_last_date": str(hold.ic.dropna().index[-1].date()),
       "rel_hit_dev": float(dev.rel.mean()), "rel_hit_2026": float(hold.rel.mean()),
       "top_lead_dev": float(dev.topx.mean()), "top_lead_2026": float(hold.topx.mean()),
       "ic_autocorr_lag1_dev": float(dev.ic.dropna().autocorr(1)), "ic_autocorr_lag20_dev": float(dev.ic.dropna().autocorr(20)),
       "ic13w_dev_p10": float(r13.quantile(0.10)), "ic13w_dev_min": float(r13.min()),
       "ic13w_2026_min": float(wk26.rolling(13).mean().dropna().min()),
       "ic_daily_sd_dev": float(dev.ic.std())}
print(json.dumps(out, indent=1))
np.savez(f"{OUT}/v3_ic.npz", dates=s.index.values.astype("datetime64[D]").astype(str), ic=s.ic.values, rel=s.rel.values,
         topx=s.topx.values)
with open(f"{OUT}/v3_out.json", "w") as fh:
    json.dump(out, fh, indent=1)

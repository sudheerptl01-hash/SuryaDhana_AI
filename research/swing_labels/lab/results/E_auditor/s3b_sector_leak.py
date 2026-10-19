#!/usr/bin/env python3
"""Stage 3b: is the sector map (downloaded in 2026 from current NSE index constituent lists)
a look-ahead / survivorship leak?  'sector known' == 'in today's Nifty Total Market list'.
Test: does sector-known (and sec_rel_mom20 NaN-ness) predict forward returns historically,
controlling for liquidity, and is the effect stronger in early years (more look-ahead)?"""
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from common import L, save

P = L.load_panel(["date", "entity", "open", "close", "seg_break", "label_block"])
F = L.load_features(["elig_base", "sector", "sec_rel_mom20", "log_turn20", "fno_proxy"])
fw = L.Fwd(P)
h = 10
r = L.fwd_return(P, fw, h)
mf = L.market_fwd(P, h)
eb = F.elig_base.values & np.isfinite(r)
dates = P.date.values.astype("datetime64[D]")
yr = pd.DatetimeIndex(dates).year.values
known = (F.sector.values != "NA")
y = (r > 0.005).astype(int)
R = {"h": h}
R["known_share_elig_by_year"] = pd.Series(known[eb]).groupby(yr[eb]).mean().to_dict()
rows = []
for Y in range(2021, 2027):
    m = eb & (yr == Y)
    d = pd.DataFrame({"d": dates[m], "k": known[m], "y": y[m], "r": r[m], "x": (r - mf)[m],
                      "lt": F.log_turn20.values[m]})
    # liquidity terciles within date
    d["t"] = d.groupby("d").lt.transform(lambda s: pd.qcut(s.rank(method="first"), 3, labels=False))
    rec = {"year": Y, "n": int(m.sum()), "known_share": float(d.k.mean()),
           "auc_known_vs_label": float(roc_auc_score(d.y, d.k)),
           "mean_ret_known_bps": float(d[d.k].r.mean() * 1e4), "mean_ret_unknown_bps": float(d[~d.k].r.mean() * 1e4),
           "mean_excess_known_bps": float(d[d.k].x.mean() * 1e4), "mean_excess_unknown_bps": float(d[~d.k].x.mean() * 1e4)}
    for t in (0, 1, 2):
        s = d[d.t == t]
        rec[f"terc{t}_diff_known_minus_unknown_bps"] = float((s[s.k].r.mean() - s[~s.k].r.mean()) * 1e4)
        rec[f"terc{t}_known_share"] = float(s.k.mean())
    # date-demeaned difference (cross-sectional, removes timing)
    d["rd"] = d.r - d.groupby("d").r.transform("mean")
    rec["xs_demeaned_diff_bps"] = float((d[d.k].rd.mean() - d[~d.k].rd.mean()) * 1e4)
    rows.append(rec)
    print(rec, flush=True)
R["by_year"] = rows
# t-stat of xs demeaned difference using non-overlapping dates (every h-th date)
d = pd.DataFrame({"d": dates[eb], "k": known[eb], "r": r[eb]})
d["rd"] = d.r - d.groupby("d").r.transform("mean")
dm = d.groupby(["d", "k"]).rd.mean().unstack()
diff = (dm[True] - dm[False]).dropna()
sub = diff.iloc[::h]
R["xs_diff_mean_bps_all"] = float(diff.mean() * 1e4)
R["xs_diff_t_nonoverlap"] = float(sub.mean() / (sub.std() / np.sqrt(len(sub))))
sy = pd.Series(diff.values, index=pd.DatetimeIndex(diff.index))
R["xs_diff_by_year_bps"] = (sy.groupby(sy.index.year).mean() * 1e4).to_dict()
save("s3b_sector_leak", R)
print(R["xs_diff_mean_bps_all"], R["xs_diff_t_nonoverlap"], R["xs_diff_by_year_bps"])

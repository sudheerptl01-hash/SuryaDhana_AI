"""Monthly P(+1) series for the primary label (B20 2/2 long, tau=50) vs Nifty 500 monthly return; extremes."""
import numpy as np, pandas as pd, json
from abar import L, OUT, update_results
P = L.load_panel(["date"]); F = L.load_features(["elig_base"])
lab = np.load(f"{OUT}/labels_shortlist.npz")["B20_f2.0_2.0_long_lab"].astype("float64")
m = F["elig_base"].values & ~np.isnan(lab)
d = pd.DatetimeIndex(P["date"].values[m])
s = pd.Series((lab[m] == 1).astype(float)).groupby(d.to_period("M").astype(str)).mean()
mk = L.market_series("Nifty 500")["close"]; mr = mk.resample("ME").last().pct_change(); mr.index = mr.index.to_period("M").astype(str)
nx = mr.shift(-1)
j = pd.DataFrame({"p1": s, "mkt_same_month": mr.reindex(s.index), "mkt_next_month": nx.reindex(s.index)})
out = {"lowest": j.nsmallest(5, "p1").round(4).reset_index().to_dict("records"),
       "highest": j.nlargest(5, "p1").round(4).reset_index().to_dict("records"),
       "corr_same": float(j.p1.corr(j.mkt_same_month)), "corr_same_plus_next_avg": float(j.p1.corr((j.mkt_same_month + j.mkt_next_month) / 2))}
print(json.dumps(out, indent=0))
update_results("monthly_extremes_B20sym", out)

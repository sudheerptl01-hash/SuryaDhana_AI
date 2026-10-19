"""Stage 11: headline event-rate scorecard for the recommended gated label R1dn (and R1, base):
class shares by year / regime / liquidity, monthly P(+1) stability and market correlation,
overlap autocorrelation and fresh-event counts; plus the label's 'avoid' twin (L1 breakout)."""
import numpy as np
import pandas as pd

from common import L, OUT, load_base, save, T

t = T()
B = load_base()
names = list(B["setup_names"])
U = B["U"]
P = L.load_panel(["date", "entity", "seg_break", "label_block"])
dates = P["date"].values.astype("datetime64[D]")
lab = B["lab_L"].astype("float64")
ret = B["ret_L"].astype("float64")
okL = U & ~np.isnan(lab)
dser = pd.Series(dates)
x_ret = ret - pd.Series(np.where(okL, ret, np.nan)).groupby(dser).transform("mean").values
R1 = B["setups"][:, names.index("S1_bd20")] & U
R1dn = R1 & (B["mkt_mom20"] < 0)
L1 = B["setups"][:, names.index("L1_bo20")] & U
Fm = pd.DataFrame({"mkt_dist_sma200": B["mkt_dist_sma200"], "mkt_mom20": B["mkt_mom20"], "log_turn20": B["log_turn20"]})
Pm = pd.DataFrame({"date": P["date"].values})
out = {}
year = pd.DatetimeIndex(dates).year.values
for nm, m in (("base_U", U), ("R1", R1), ("R1dn", R1dn), ("L1_bo20", L1)):
    rep = L.event_report(lab, m & okL, Pm, Fm, positive=1)
    mon = rep["monthly_pos"]
    yr = {}
    for y in range(2021, 2027):
        mm = m & okL & (year == y)
        yr[y] = {"n": int(mm.sum()), "P+1": float((lab[mm] == 1).mean()) if mm.sum() else None,
                 "P0": float((lab[mm] == 0).mean()) if mm.sum() else None,
                 "P-1": float((lab[mm] == -1).mean()) if mm.sum() else None,
                 "net50_bps": 1e4 * (ret[mm].mean() - 0.005) if mm.sum() else None,
                 "xs_bps": 1e4 * x_ret[mm].mean() if mm.sum() else None}
    ac = L.overlap_autocorr(np.where(m & okL, lab, np.nan), P, lag_=1)
    out[nm] = {"n": rep["n"], "overall": rep["overall"], "by_year": yr, "by_regime": rep.get("by_regime"),
               "by_liquidity_tercile_within_events": rep.get("by_liquidity_tercile"),
               "monthly_pos": {k: v for k, v in mon.items() if k != "series"},
               "corr_monthly_pos_vs_mkt_ret": rep.get("corr_monthly_pos_vs_mkt_ret"),
               "lag1_autocorr_label_within_entity": ac}
    print(nm, {k: v for k, v in out[nm].items() if k not in ("by_year", "by_regime", "by_liquidity_tercile_within_events")})
    print(pd.DataFrame(yr).T.round(3).to_string())
save("s11_headline", out)
t("done")

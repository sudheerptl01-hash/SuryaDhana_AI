"""Stage 7: diagnostics + robustness of the winning setup R1 (20d breakdown on volume, bought).

(a) breadth dependence: split R1 / R1dn events by how many R1 events fired that day
    -> is the edge stock-specific or 'mass-capitulation' market timing?
(b) episode concentration: monthly table of R1dn events (net50, date-matched excess), share of
    total excess from the top-5 months.
(c) parameter sensitivity of the setup definition (lookback 10/20/55, volz threshold 0/0.5/1/2,
    regime filter none / mkt_mom20<0 / mkt_dist_sma200<0) -> event rate, dev excess, holdout excess.
(d) label robustness: same events scored with executable time-exit returns h=5/10/20 and with the
    Nifty-500 excess return (L.fwd_return, L.market_fwd), not only the h=10 barrier.
Everything selection-relevant is reported on dev (2023-01-01..DEV_END); 2026 shown separately.
"""
import numpy as np
import pandas as pd

from common import L, OUT, DEV_END, load_base, save, T

t = T()
B = load_base()
names = list(B["setup_names"])
U = B["U"]
P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["volz_20", "mkt_mom20", "mkt_dist_sma200"])
fw = L.Fwd(P)
dates = P["date"].values.astype("datetime64[D]")
n = len(P)
lab = B["lab_L"].astype("float64")
ret = B["ret_L"].astype("float64")
okL = U & ~np.isnan(lab)
dser = pd.Series(dates)


def date_demean(v, m):
    s = pd.Series(np.where(m, v, np.nan))
    return v - s.groupby(dser).transform("mean").values


x_ret = date_demean(ret, okL)
fr = {h: L.fwd_return(P, fw, h) for h in (5, 10, 20)}
mk = {h: L.market_fwd(P, h) for h in (5, 10, 20)}
xr = {}
for h in (5, 10, 20):
    okh = U & np.isfinite(fr[h])
    xr[h] = (date_demean(fr[h], okh), okh)
t("returns")
dev = (dates >= np.datetime64("2023-01-01")) & (dates <= np.datetime64(DEV_END))
hold = dates >= np.datetime64("2026-01-01")
R1 = B["setups"][:, names.index("S1_bd20")] & U
mm20 = F["mkt_mom20"].values
R1dn = R1 & (mm20 < 0)
res = {}

# (a) breadth dependence
cnt = pd.Series(R1.astype(int)).groupby(dser).transform("sum").values
buckets = [(1, 2), (3, 9), (10, 29), (30, 99), (100, 10000)]
rows = []
for nm, m0 in (("R1", R1), ("R1dn", R1dn)):
    for per, pm in (("dev", dev), ("hold", hold)):
        for lo, hi in buckets:
            m = m0 & pm & okL & (cnt >= lo) & (cnt <= hi)
            if m.sum() == 0:
                continue
            dm = pd.DataFrame({"d": dates[m], "r": ret[m]}).groupby("d").r.mean()
            rows.append({"set": nm, "period": per, "events_that_day": f"{lo}-{hi}", "n_events": int(m.sum()),
                         "n_days": int(len(dm)), "net50_event_wtd_bps": 1e4 * (ret[m].mean() - 0.005),
                         "net50_day_wtd_bps": 1e4 * (dm.mean() - 0.005), "xs_bps": 1e4 * x_ret[m].mean(),
                         "P+1": float((lab[m] == 1).mean())})
br = pd.DataFrame(rows)
res["breadth"] = br.to_dict(orient="records")
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 30)
print(br.round(2).to_string(index=False))

# (b) episode concentration (R1dn and R1)
ep = {}
for nm, m0 in (("R1dn", R1dn), ("R1", R1)):
    m = m0 & okL
    df = pd.DataFrame({"m": pd.DatetimeIndex(dates[m]).to_period("M").astype(str), "r": ret[m], "x": x_ret[m]})
    g = df.groupby("m").agg(n=("r", "size"), net50_bps=("r", lambda s: 1e4 * (s.mean() - 0.005)),
                            xs_bps=("x", lambda s: 1e4 * s.mean()), xs_sum=("x", "sum"), r_sum=("r", "sum"))
    tot_x, tot_r = g.xs_sum.sum(), (g.r_sum - 0.005 * g.n).sum()
    top5x = g.xs_sum.sort_values(ascending=False).head(5)
    top5r = (g.r_sum - 0.005 * g.n).sort_values(ascending=False).head(5)
    ep[nm] = {"months_with_events": int(len(g)), "months_xs_pos_share": float((g.xs_bps > 0).mean()),
              "months_net_pos_share": float((g.net50_bps > 0).mean()),
              "top5_months_share_of_total_xs": float(top5x.sum() / tot_x) if tot_x > 0 else None,
              "top5_months_xs": top5x.index.tolist(),
              "top5_months_share_of_total_net": float(top5r.sum() / tot_r) if tot_r > 0 else None,
              "top5_months_net": top5r.index.tolist(),
              "monthly": g[["n", "net50_bps", "xs_bps"]].round(1).reset_index().to_dict(orient="records")}
    print(nm, {k: v for k, v in ep[nm].items() if k != "monthly"})
res["episodes"] = ep
t("episodes")

# (c) parameter sensitivity
lo_prev = L.lag(P["low"].values, 1, fw.start)
seg = pd.Series(fw.seg)
volz = F["volz_20"].values.astype("float64")
mdist = F["mkt_dist_sma200"].values
sens = []
for lb in (10, 20, 55):
    lowN = (pd.Series(lo_prev).groupby(seg).rolling(lb, min_periods=int(lb * 0.75)).min()
            .reset_index(level=0, drop=True).sort_index().values)
    brk = P["close"].values < lowN
    for vz in (None, 0.0, 0.5, 1.0, 2.0):
        base_m = U & brk & (np.ones(n, bool) if vz is None else (volz > vz))
        for fn, fm in (("none", np.ones(n, bool)), ("mkt_mom20<0", mm20 < 0), ("mkt_below_sma200", mdist < 0)):
            m = base_m & fm & okL
            r = {"lookback": lb, "volz_gt": "any" if vz is None else vz, "regime": fn,
                 "share_of_U_rows": float((base_m & fm).sum() / U.sum()),
                 "events_per_day": float((m & (dev | hold)).sum() / len(np.unique(dates[U & (dev | hold)])))}
            for per, pm in (("dev", dev), ("hold", hold)):
                mm = m & pm
                r[f"{per}_n"] = int(mm.sum())
                r[f"{per}_P+1"] = float((lab[mm] == 1).mean()) if mm.sum() else None
                r[f"{per}_net50_bps"] = 1e4 * (ret[mm].mean() - 0.005) if mm.sum() else None
                r[f"{per}_xs_bps"] = 1e4 * x_ret[mm].mean() if mm.sum() else None
            for y in (2023, 2024, 2025):
                my = m & (dates >= np.datetime64(f"{y}-01-01")) & (dates < np.datetime64(f"{y + 1}-01-01")) & dev
                r[f"xs_{y}"] = 1e4 * x_ret[my].mean() if my.sum() else None
            sens.append(r)
sens = pd.DataFrame(sens)
res["sensitivity"] = sens.to_dict(orient="records")
print(sens[["lookback", "volz_gt", "regime", "share_of_U_rows", "events_per_day", "dev_n", "dev_P+1", "dev_net50_bps",
            "dev_xs_bps", "xs_2023", "xs_2024", "xs_2025", "hold_n", "hold_net50_bps", "hold_xs_bps"]].round(3).to_string(index=False))
t("sensitivity")

# (d) label robustness on R1 / R1dn / reference sets
lr = []
refs = {"R1": R1, "R1dn": R1dn, "L1_bo20": B["setups"][:, names.index("L1_bo20")] & U,
        "L8b_mktlead": B["setups"][:, names.index("L8b_mktlead")] & U}
for nm, m0 in refs.items():
    for h in (5, 10, 20):
        xh, okh = xr[h]
        exc = fr[h] - mk[h]
        for per, pm in (("dev", dev), ("hold", hold)):
            m = m0 & okh & pm
            lr.append({"set": nm, "h": h, "period": per, "n": int(m.sum()),
                       "net50_bps": 1e4 * (np.nanmean(fr[h][m]) - 0.005),
                       "excess_vs_nifty500_bps": 1e4 * np.nanmean(exc[m]),
                       "xs_date_matched_bps": 1e4 * np.nanmean(xh[m]),
                       "P(ret>50bps)": float(np.nanmean(fr[h][m] > 0.005)),
                       "P(ret>50bps)_base": float(np.nanmean(fr[h][okh & pm] > 0.005))})
lr = pd.DataFrame(lr)
res["label_robustness"] = lr.to_dict(orient="records")
print(lr.round(3).to_string(index=False))
save("s7_diag", res)
t("done")

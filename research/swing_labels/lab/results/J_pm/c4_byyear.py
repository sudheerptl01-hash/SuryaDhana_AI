"""J_pm check 4: calendar-year excess vs the seed-free EW-universe book (phase-averaged), plus tiered-cost
CAGR (fno 30 / mid 50 / small 95 bps) from trade-level P&L for the selected book."""
import sys, json, numpy as np, pandas as pd
LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
sys.path.insert(0, LAB); import lablib as L
R = LAB + "/results"
P = L.load_panel(["date", "entity", "seg_break", "label_block", "open", "high", "low", "close"])
F = L.load_features(["elig_base", "elig_liq5", "fno_proxy"])
mask = F.elig_base.values.astype(bool)
fw = L.Fwd(P); S = L.Sim(P, None, fw); cal = S.cal
def ld(p): return np.load(p)["score"].astype("float64")
sc = {"neumom_RANK": ld(R + "/R2_rel/wf_h20_neumom_RANK.npz"), "neumom_C20": ld(R + "/R2_rel/wf_h20_neumom_C20.npz"),
      "neumom_T30": ld(R + "/R2_rel/wf_h20_neumom_T30.npz")}
out = {}
for win, kw in {"dev": dict(start=L.DEV[0], end_exit=L.DEV[1]), "hold": dict(start="2026-01-01", end_exit=None)}.items():
    ser = {k: [] for k in list(sc) + ["EW"]}
    for ph in range(5):
        st = str(cal[int(np.searchsorted(cal, np.datetime64(kw["start"]))) + ph])
        ew = S.run(sc["neumom_RANK"], mask, 20, step=5, cost_bps=50.0, start=st, end_exit=kw["end_exit"], sizing="equal", select_quantile=(0.0, 1.0))
        ser["EW"].append(pd.Series(ew["_daily_ret"], index=pd.DatetimeIndex(ew["_dates"])))
        for k, s in sc.items():
            r = S.run(s, mask, 20, step=5, top_k=20, cost_bps=50.0, start=st, end_exit=kw["end_exit"])
            ser[k].append(pd.Series(r["_daily_ret"], index=pd.DatetimeIndex(r["_dates"])))
    idx = ser["EW"][4].index
    for v in ser.values():
        for s in v: idx = idx.intersection(s.index)
    M = {k: pd.Series(np.mean([s.loc[idx].values for s in v], 0), index=idx) for k, v in ser.items()}
    res = {}
    for y, gidx in pd.Series(idx, index=idx).groupby(idx.year):
        row = {"EW": float((1 + M["EW"].loc[gidx.index]).prod() - 1)}
        for k in sc:
            row[k] = float((1 + M[k].loc[gidx.index]).prod() - 1)
            row[k + "_minus_EW"] = row[k] - row["EW"]
        res[int(y)] = {kk: round(vv, 4) for kk, vv in row.items()}
    out[win] = res
    print(win, json.dumps(res), flush=True)
# tiered cost: trade-level P&L of the phase-0 DEV book; replace flat 50 bps with tier cost per name
fno = F.fno_proxy.values.astype(bool); liq5 = F.elig_liq5.values.astype(bool)
tier = np.where(fno, 30.0, np.where(liq5, 50.0, 95.0))
for win, kw in {"dev": dict(start=L.DEV[0], end_exit=L.DEV[1]), "hold": dict(start="2026-01-01", end_exit=None)}.items():
    r = S.run(sc["neumom_RANK"], mask, 20, step=5, top_k=20, cost_bps=50.0, keep_trades=True, **kw)
    rows = np.array([t[1] for t in r["_trades"]]); net = np.array([t[2] for t in r["_trades"]])
    extra = (tier[rows] - 50.0) / 1e4
    # random baseline's average tier cost (universe composition on the same signal dates)
    sig_rows = np.concatenate([S.rows_on(int(np.searchsorted(cal, np.datetime64(d)))) for d in sorted(set(t[0] for t in r["_trades"]))])
    sig_rows = sig_rows[mask[sig_rows]]
    out[win + "_tiered_cost"] = dict(mean_tier_cost_picks_bps=float(tier[rows].mean()), mean_tier_cost_universe_bps=float(tier[sig_rows].mean()),
                                     mean_trade_net_flat50=float(net.mean()), mean_trade_net_tiered=float((net - extra).mean()),
                                     approx_cagr_drag_vs_flat50_pct=float(-extra.mean() * 12.6 * 100))
    print(win, out[win + "_tiered_cost"], flush=True)
json.dump(out, open(R + "/J_pm/c4_byyear.json", "w"), indent=1)

"""Stage 7: perturbation, capacity and secondary-event checks (step=1, K=20 throughout).

(a) OS: rsi_14<20 & Nifty-500 mom20<0 (passed Bonferroni at h=5 in s2) -> sleeve vs matched random.
(b) 1-day signal lag: the stock had a gate event YESTERDAY -> signal today -> entry open t+2.
(c) Random entity halves (seed 7): sleeve + matched baseline restricted to each half.
(d) Quarter-by-quarter excess of the meta sleeve vs matched (DEV + HOLD).
(e) Capacity: 20d average daily turnover (ADV) of the names the meta sleeve buys; position size at
    Rs 5 lakh / 25 lakh / 1 crore per name as % of ADV.
"""
import numpy as np
import pandas as pd

from common import (OUT, L, T, SimX, load_base, matched_mask, counts_by_g, save, cluster_t, summarize_runs)

t = T()
P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["atr_pct"])
fw = L.Fwd(P)
S = SimX(P, F, fw)
B = load_base()
U = B["U"]
didx = S.didx
ncal = len(S.cal)
brd = np.load(f"{OUT}/brd_day.npy")[didx]
mm20 = B["mkt_mom20"]
A1 = U & (B["bdd10"] < 0) & (B["volz_20"] > 0) & (mm20 < 0) & (brd >= 0.05)
OS = U & (B["rsi_14"] < 20) & (mm20 < 0)
sc_meta = np.load(f"{OUT}/s4_scores.npz")["WF_R10"].astype("float64")
WIN = {"dev": dict(start=L.DEV[0], end_exit=L.DEV[1]), "hold": dict(start="2026-01-01", end_exit=None)}
SEEDS = (1, 2, 3, 4, 5)


def sleeve(mask, score, h, cost, w, base_mask=None):
    """strategy (score top-20, or random events if score None) vs count-matched random from base_mask."""
    bm = U if base_mask is None else base_mask
    kw = dict(step=1, top_k=20, cost_bps=cost, **w)
    if score is None:
        st = summarize_runs([S.run(None, mask, h, random_seed=s, **kw) for s in SEEDS])
        cnt = counts_by_g(mask, None, didx, ncal, 20)
    else:
        m = mask & np.isfinite(score)
        r = S.run(score, m, h, **kw)
        st = {"cagr": r["cagr"], "sharpe": r["sharpe"], "max_dd": r["max_dd"], "exposure": r["exposure"],
              "mean_trade_net": r["mean_trade_net"], "trades": r["trades"], "_daily_ret": r["_daily_ret"], "_dates": r["_dates"]}
        cnt = counts_by_g(m, score, didx, ncal, 20)
    ma = summarize_runs([S.run(None, matched_mask(cnt, bm, didx, s), h, random_seed=s, **kw) for s in SEEDS])
    d = st["_daily_ret"] - ma["_daily_ret"]
    mon = st["_dates"].astype("datetime64[M]").astype(np.int64)
    return {"cagr": st["cagr"], "sharpe": st["sharpe"], "max_dd": st["max_dd"], "exposure": st["exposure"],
            "mean_trade_net": st["mean_trade_net"], "trades": st["trades"], "matched_cagr": ma["cagr"],
            "exc_ann": float(d.mean() * 252), "exc_nw_t": L.nw_t(d, h), "exc_month_t": cluster_t(d, mon)[0]}, d, st["_dates"]


out = {}
# (a) oversold-in-down-market sleeve
for h in (5, 10):
    for cost in (50, 80):
        for wn, w in WIN.items():
            out[f"OS|h{h}|{cost}|{wn}"] = sleeve(OS, None, h, cost, w)[0]
t("OS")
# (b) 1-day lag
fwd = L.Fwd(P)
A1_lag = (fwd.at(A1.astype(float), -1) == 1) & U
sc_lag = fwd.at(sc_meta, -1)
for h in (5, 10):
    for wn, w in WIN.items():
        out[f"LAG1_ALL|h{h}|50|{wn}"] = sleeve(A1_lag, None, h, 50, w)[0]
        out[f"LAG1_META|h{h}|50|{wn}"] = sleeve(A1_lag, sc_lag, h, 50, w)[0]
        out[f"LAG0_ALL|h{h}|50|{wn}"] = sleeve(A1, None, h, 50, w)[0]
        out[f"LAG0_META|h{h}|50|{wn}"] = sleeve(A1, sc_meta, h, 50, w)[0]
t("lag")
# (c) entity halves
ent = P["entity"].values
ue = np.unique(ent)
rng = np.random.default_rng(7)
half_set = set(rng.choice(ue, size=len(ue) // 2, replace=False))
inA = np.fromiter((e in half_set for e in ent), bool, len(ent))
for hn, hm in (("halfA", inA), ("halfB", ~inA)):
    for h in (5, 10):
        for wn, w in WIN.items():
            out[f"{hn}_ALL|h{h}|50|{wn}"] = sleeve(A1 & hm, None, h, 50, w, base_mask=U & hm)[0]
            out[f"{hn}_META|h{h}|50|{wn}"] = sleeve(A1 & hm, sc_meta, h, 50, w, base_mask=U & hm)[0]
t("halves")
# (d) quarter-by-quarter
quarters = {}
for h in (5, 10):
    for wn, w in WIN.items():
        _, d, dts = sleeve(A1, sc_meta, h, 50, w)
        q = pd.Series(d, index=pd.DatetimeIndex(dts)).groupby(pd.DatetimeIndex(dts).to_period("Q")).sum()
        quarters[f"h{h}|{wn}"] = {str(k): float(v) for k, v in q.items()}
out["quarters"] = quarters
t("quarters")
# (e) capacity
lt = B["log_turn20"].astype("float64")
cap = {}
for h in (5, 10):
    r = S.run(sc_meta, A1 & np.isfinite(sc_meta), h, step=1, top_k=20, cost_bps=50, keep_trades=True,
              start=L.DEV[0], end_exit=None)
    rows = np.array([tr[1] for tr in r["_trades"]], dtype=int)
    adv = np.expm1(lt[rows])
    o = {"trades": int(len(rows)), "adv_median_cr": float(np.median(adv) / 1e7), "adv_p10_cr": float(np.percentile(adv, 10) / 1e7),
         "adv_p25_cr": float(np.percentile(adv, 25) / 1e7), "fno_share": float(B["fno"][rows].mean()),
         "liq5_share": float(B["liq5"][rows].mean()),
         "liq_tercile_share": {int(k): float(v) for k, v in pd.Series(B["liq"][rows]).value_counts(normalize=True).items()}}
    for nm, pos in (("5L", 5e5), ("25L", 2.5e6), ("1Cr", 1e7)):
        pct = pos / adv
        o[f"pos_{nm}_pct_adv_median"] = float(np.median(pct) * 100)
        o[f"pos_{nm}_pct_adv_p90"] = float(np.percentile(pct, 90) * 100)
        o[f"pos_{nm}_share_trades_gt5pct_adv"] = float((pct > 0.05).mean())
    # names per event day and max simultaneous names
    cap[f"h{h}"] = o
out["capacity"] = cap
save("s7_checks", out)
for k, v in out.items():
    if k in ("quarters", "capacity"):
        print(k, v)
    else:
        print(k, {kk: (round(vv, 4) if isinstance(vv, float) else vv) for kk, vv in v.items()})
t("done")

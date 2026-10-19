"""Stage 3: investability of the capitulation sleeve with L.Sim (daily mark-to-market, slot sizing,
fixed trading-day calendar, next-open entry, half cost in / half out).

Sleeve design: step=1 (every trading day is a signal date -> S=h sleeves, each 1/h of capital, each
rebalanced every h days), top_k=K slots per sleeve (each slot 1/(h*K) of capital, unfilled = cash at 0%).
"All events" strategy = random tie-break among the day's events (5 seeds) == S.compare's random arm.

Baselines (same h, K, step, cost, window):
  MATCH  count-matched universe random: on every day, as many random elig_base names as the sleeve
         holds events (min(K, n_events)), 5 seeds -> isolates the EVENT effect at equal exposure/timing.
  URAND  universe random top-K every day (fully invested) -> absolute context (S.random_band on U).
NW t of daily (strategy - baseline) with lag h.  DEV = 2023-01-01..2025-12-31 exits; HOLD = 2026.
"""
import numpy as np
import pandas as pd

from common import (OUT, L, T, load_base, matched_mask, counts_by_g, save, summarize_runs, excess_stats, strip)

t = T()
P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["atr_pct"])
fw = L.Fwd(P)
S = L.Sim(P, F, fw)
B = load_base()
U = B["U"]
didx = S.didx
ncal = len(S.cal)
brd = np.load(f"{OUT}/brd_day.npy")[didx]
mm20 = B["mkt_mom20"]
t("init")


def r1(Lb, v, gate):
    m = U & (B[f"bdd{Lb}"] < 0)
    if v is not None:
        m &= B["volz_20"] > v
    if gate == "mom20dn":
        m &= mm20 < 0
    elif gate == "mom20dn_brd5":
        m &= (mm20 < 0) & (brd >= 0.05)
    elif gate == "brd5":
        m &= brd >= 0.05
    elif gate == "brd10":
        m &= brd >= 0.10
    return m


MASKS = {
    "A0_R1dn_L20v1_mom20dn": r1(20, 1.0, "mom20dn"),          # round-1 anchor
    "A1_L10v0_mom20dn_brd5": r1(10, 0.0, "mom20dn_brd5"),     # DEV-selected (pre-declared rule, s2)
    "N1_L20v1_mom20dn_brd5": r1(20, 1.0, "mom20dn_brd5"),
    "N2_L20v1_brd10": r1(20, 1.0, "brd10"),
    "N3_L10v0.5_brd10": r1(10, 0.5, "brd10"),
    "N4_L20v0.5_mom20dn_brd5": r1(20, 0.5, "mom20dn_brd5"),
    "N5_L40v1_mom20dn_brd5": r1(40, 1.0, "mom20dn_brd5"),
    "N6_L20v1_brd5": r1(20, 1.0, "brd5"),
}
WIN = {"dev": dict(start=L.DEV[0], end_exit=L.DEV[1]), "hold": dict(start="2026-01-01", end_exit=None)}
SEEDS = (1, 2, 3, 4, 5)
rows = []
daily = {}
bench = {}
for wn, w in WIN.items():
    mk = L.market_series("Nifty 500")["close"]
    mk = mk[(mk.index >= pd.Timestamp(w["start"])) & ((mk.index <= pd.Timestamp(w["end_exit"])) if w["end_exit"] else True)]
    yrs = (mk.index[-1] - mk.index[0]).days / 365.25
    bench[wn] = {"cagr": float((mk.iloc[-1] / mk.iloc[0]) ** (1 / yrs) - 1),
                 "max_dd": float((mk / mk.cummax() - 1).min())}
urand_cache = {}
for K in (5, 10, 20):
    for h in (5, 10, 20):
        for cost in (50, 80):
            for wn, w in WIN.items():
                kw = dict(step=1, top_k=K, cost_bps=cost, sizing="slot", **w)
                ur = summarize_runs([S.run(None, U, h, random_seed=s, **kw) for s in SEEDS])
                urand_cache[(K, h, cost, wn)] = ur
                if cost == 50 and K == 10:
                    daily[f"URAND|h{h}|K{K}|{wn}"] = ur["_daily_ret"]
    t(f"urand K={K}")
for mname, m in MASKS.items():
    for K in (5, 10, 20):
        cnt = counts_by_g(m, None, didx, ncal, K)
        mmasks = [matched_mask(cnt, U, didx, s) for s in SEEDS]
        for h in (5, 10, 20):
            for cost in (50, 80):
                for wn, w in WIN.items():
                    kw = dict(step=1, top_k=K, cost_bps=cost, sizing="slot", **w)
                    ev = summarize_runs([S.run(None, m, h, random_seed=s, **kw) for s in SEEDS])
                    ma = summarize_runs([S.run(None, mm, h, random_seed=s, **kw) for s, mm in zip(SEEDS, mmasks)])
                    ur = urand_cache[(K, h, cost, wn)]
                    ex_m = excess_stats(ev["_daily_ret"], ma["_daily_ret"], h)
                    ex_u = excess_stats(ev["_daily_ret"], ur["_daily_ret"], h)
                    row = {"mask": mname, "K": K, "h": h, "cost": cost, "win": wn,
                           **{f"ev_{k}": v for k, v in ev.items() if not k.startswith("_") and k != "by_year"},
                           "ev_by_year": ev["by_year"],
                           **{f"match_{k}": v for k, v in ma.items() if not k.startswith("_") and k != "by_year"},
                           "match_by_year": ma["by_year"],
                           "urand_cagr": ur["cagr"], "urand_sharpe": ur["sharpe"], "urand_max_dd": ur["max_dd"],
                           "urand_exposure": ur["exposure"],
                           "exc_vs_match_cagr": ev["cagr"] - ma["cagr"], "exc_vs_match_ann": ex_m["excess_ann_return"],
                           "exc_vs_match_nw_t": ex_m["excess_nw_t"],
                           "exc_vs_urand_cagr": ev["cagr"] - ur["cagr"], "exc_vs_urand_nw_t": ex_u["excess_nw_t"],
                           "bench_cagr": bench[wn]["cagr"]}
                    rows.append(row)
                    if cost == 50:
                        daily[f"EV|{mname}|h{h}|K{K}|{wn}"] = ev["_daily_ret"]
                        daily[f"MA|{mname}|h{h}|K{K}|{wn}"] = ma["_daily_ret"]
        t(f"{mname} K={K}")
df = pd.DataFrame(rows)
df.to_pickle(f"{OUT}/s3_sim.pkl")
np.savez_compressed(f"{OUT}/s3_daily.npz", **{k: np.asarray(v, dtype=np.float64) for k, v in daily.items()},
                    dates_dev=S.run(None, U, 10, step=1, top_k=5, random_seed=1, **WIN["dev"])["_dates"].astype("datetime64[D]").astype(str),
                    dates_hold=S.run(None, U, 10, step=1, top_k=5, random_seed=1, **WIN["hold"])["_dates"].astype("datetime64[D]").astype(str))
save("s3_sim", {"benchmark": bench, "rows": df.to_dict("records"),
                "n_configs": int(len(df[(df.cost == 50) & (df.win == "dev")]))})
pd.set_option("display.width", 260)
cols = ["mask", "K", "h", "ev_cagr", "ev_sharpe", "ev_max_dd", "ev_exposure", "ev_trades", "ev_mean_trade_net",
        "match_cagr", "exc_vs_match_cagr", "exc_vs_match_nw_t", "urand_cagr", "exc_vs_urand_nw_t"]
for wn in ("dev", "hold"):
    print("=====", wn, "cost 50")
    print(df[(df.win == wn) & (df.cost == 50)][cols].round(4).to_string())
t("done")

"""Stage 10: capacity / sizing of the R1dn capitulation gate.

The s6/s9 sims cap picks at 5-20 per signal date, which under-weights mass-capitulation days (where
s7 shows the edge lives).  Here: take (up to) ALL events of the signal date ('top_k' large) with
equal weight (ew) or fixed slots (slot: each position 1/top_k of a sleeve, rest cash).
Signal grid = every step-th trading date of the eligible universe; time exit at close[t+10].
"""
import numpy as np
import pandas as pd

import simcore as sc
from common import L, OUT, DEV_END, HOLD_START, load_base, save, T

t = T()
B = load_base()
names = list(B["setup_names"])
U = B["U"]
P = L.load_panel(["date", "entity", "open", "close", "seg_break", "label_block"])
fw = L.Fwd(P)
sc.dates = P["date"].values.astype("datetime64[D]")
n = len(P)
e = fw.at(P["open"].values, 1)
x = fw.at(P["close"].values, 10)
tr = x / e - 1
last = np.full(n, np.nan)
for k in range(1, 11):
    xk = fw.at(P["close"].values, k)
    last = np.where(np.isnan(xk), last, xk)
tr = np.where(np.isnan(tr) & np.isfinite(e), last / e - 1, tr)
R1 = B["setups"][:, names.index("S1_bd20")] & U
R1dn = R1 & (B["mkt_mom20"] < 0)
sc_all = np.load(f"{OUT}/wf_ALL.npz")["score"].astype("float64")
windows = {"full": (None, None), "dev": (None, DEV_END), "hold": (HOLD_START, None)}
rows = []
for nm, m in (("R1dn", R1dn), ("R1", R1)):
    for step in (5, 1):
        for k in (20, 50, 300):
            for scorer in ("all_events", "allbar_rank"):
                if scorer == "all_events":
                    coh = sc.picks_run(np.zeros(n), m, tr, k, seed=1, step=step, grid=U)
                else:
                    coh = sc.picks_run(sc_all, m, tr, k, step=step, grid=U)
                for cost in (50, 80):
                    for sizing in ("ew", "slot"):
                        for w, (lo, hi) in windows.items():
                            mt = sc.metrics(coh, tr, cost, k, sizing, lo, hi, step=step)
                            r = {"set": nm, "step": step, "top_k": k, "scorer": scorer, "cost": cost, "sizing": sizing,
                                 "window": w}
                            r.update({kk: v for kk, v in mt.items() if kk != "by_year"})
                            for yy, v in mt.get("by_year", {}).items():
                                r[f"y{yy}"] = v
                            rows.append(r)
        t(f"{nm} step{step}")
df = pd.DataFrame(rows)
df.to_csv(f"{OUT}/s10_allevents.csv", index=False)
save("s10_allevents", df.to_dict(orient="records"))
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 30)
q = df[(df.cost == 50) & (df.scorer == "all_events")]
for w in ("full", "dev", "hold"):
    print("==", w)
    print(q[q.window == w][["set", "step", "top_k", "sizing", "trades", "avg_picks", "avg_exposure_slot", "mean_trade_net_bps",
                            "cagr", "sharpe", "max_dd", "y2023", "y2024", "y2025", "y2026"]].round(3).to_string(index=False))
q = df[(df.cost == 50) & (df.scorer == "allbar_rank") & (df.top_k == 20)]
print(q[["set", "step", "sizing", "window", "trades", "mean_trade_net_bps", "cagr", "sharpe", "max_dd", "y2023", "y2024",
         "y2025", "y2026"]].round(3).to_string(index=False))
t("done")

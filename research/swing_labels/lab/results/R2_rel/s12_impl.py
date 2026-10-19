"""Stage 12: implementation facts for the long top-20 book (h=20, step 5 -> each sleeve rebalances every
20 trading days): (a) name retention between a sleeve's consecutive rebalances (the Sim charges a full
round trip even for re-picked names, so realised cost ~ (1-retention) x cost); (b) liquidity of the picks:
median / p10 20-day average daily turnover (Rs crore) and the position size at which a pick would be
10% of its ADV for a Rs 1 crore / 5 crore / 25 crore book (K=20 -> 5% of book per name per sleeve...
here: book/K/S per name since 4 sleeves overlap -> per-name ticket = book/(K*S)).
Usage: python3 s12_impl.py tag1 tag2 ...
"""
import sys

import numpy as np
import pandas as pd

from common import OUT, L, save, load_res

tags = sys.argv[1:]
P = L.load_panel(["date"])
F = L.load_features(["log_turn20"])
E = np.load(f"{OUT}/meta.npz")["E"]
dates = P["date"].values.astype("datetime64[D]")
cal = np.unique(dates)
turn = np.expm1(F["log_turn20"].values.astype("float64")) / 1e7     # Rs crore / day
res = load_res().get("s12_impl", {})
for tag in tags:
    sc = np.load(f"{OUT}/wf_{tag}.npz")["score"].astype("float64")
    m = E & np.isfinite(sc) & (dates >= np.datetime64("2023-01-01"))
    df = pd.DataFrame({"d": dates[m], "s": sc[m], "row": np.flatnonzero(m), "t": turn[m]})
    df["rk"] = df.groupby("d").s.rank(ascending=False, method="first")
    top = df[df.rk <= 20]
    g = top.groupby("d")
    picks = {d: set(x.row.values) for d, x in g}
    ents = {d: set(x) for d, x in picks.items()}
    # entity identity for retention: rows differ by date, so map row->entity
    ent = L.load_panel(["entity"])["entity"].values
    eset = {d: set(ent[list(r)]) for d, r in picks.items()}
    ds = sorted(eset)
    pos = {d: i for i, d in enumerate(cal)}
    ret = []
    for d in ds:
        j = pos[d] + 20
        if j < len(cal) and cal[j] in eset:
            ret.append(len(eset[d] & eset[cal[j]]) / 20)
    o = {"retention_20d_mean": float(np.mean(ret)), "median_pick_turnover_cr": float(top.t.median()),
         "p10_pick_turnover_cr": float(top.t.quantile(0.1)), "median_universe_turnover_cr": float(df.t.median())}
    for book in (1, 5, 25):
        ticket = book / (20 * 4)          # crore per name per sleeve (4 sleeves)
        o[f"share_picks_ticket_gt_10pct_ADV_book{book}cr"] = float((ticket > 0.1 * top.t).mean())
    res[tag] = o
    print(tag, o, flush=True)
save("s12_impl", res)

#!/usr/bin/env python3
"""Stage 2: point-in-time recomputation of features for 30 random rows, using ONLY data
up to and including date t AND corporate-action factors known by date t (re-adjusting raw
prices with truncated CA history). Independent pandas implementation, compared with
features.parquet. Half the rows are chosen from entities with a split/bonus AFTER t
(stress test for future-CA leakage through back-adjustment)."""
import numpy as np
import pandas as pd

from common import L, save

FEATS = ["mom_20", "dist_sma50", "vol_20", "rsi_14", "volz_20", "deliv_z20", "hi52_dist", "beta_60",
         "mom_60", "atr_pct", "max_ret_20", "gap_open"]
P = L.load_panel(["date", "entity", "symbol", "open", "high", "low", "close", "volume", "deliv_pct",
                  "adj_factor", "ca_ratio", "seg_break"])
F = L.load_features(FEATS + ["elig_base"])
n = len(P)
ent = P.entity.values
seg = L.segment_codes(P)
start, end = L._start_end(seg)
rng = np.random.default_rng(7)
eb = np.flatnonzero(F.elig_base.values)
# rows whose entity has a split/bonus (ratio<0.8) AFTER the row, within the same segment
split_rows = np.flatnonzero(P.ca_ratio.values < 0.8)
has_future_split = np.zeros(n, bool)
for r in split_rows:
    s0 = start[r]
    has_future_split[s0:r] = True
cand_future = np.intersect1d(eb, np.flatnonzero(has_future_split))
pick = np.r_[rng.choice(eb, 15, replace=False), rng.choice(cand_future, 15, replace=False)]
mk = L.market_series("Nifty 500")["close"]


def features_from_truncated(i):
    s0 = start[i]
    sl = slice(s0, i + 1)
    af = P.adj_factor.values[sl]
    # raw prices
    raw = {k: P[k].values[sl] / af for k in ("open", "high", "low", "close")}
    # truncated CA factors: only ratios on rows <= i are known at t
    lr = np.log(P.ca_ratio.values[sl])
    tf = np.exp(lr.sum() - np.cumsum(lr))
    adj = {k: raw[k] * tf for k in raw}
    vol_adj = P.volume.values[sl] / tf
    d = pd.DataFrame({"date": P.date.values[sl], **adj, "v": vol_adj, "dp": P.deliv_pct.values[sl]})
    c = d.close
    out = {}
    out["mom_20"] = c.iloc[-1] / c.iloc[-21] - 1 if len(c) > 20 else np.nan
    out["mom_60"] = c.iloc[-1] / c.iloc[-61] - 1 if len(c) > 60 else np.nan
    w = c.iloc[-50:]
    out["dist_sma50"] = c.iloc[-1] / w.mean() - 1 if len(w) >= 40 else np.nan
    lr1 = np.log(c / c.shift(1))
    x = lr1.iloc[-20:].dropna()
    out["vol_20"] = x.std(ddof=1) if len(x) >= 15 else np.nan
    ch = c.diff()
    g = ch.clip(lower=0).iloc[-14:]
    lo_ = (-ch).clip(lower=0).iloc[-14:]
    if g.notna().sum() >= 14:
        ag, al = g.mean(), lo_.mean()
        out["rsi_14"] = 100.0 if (al == 0 and ag > 0) else (50.0 if (al == 0 and ag == 0) else 100 - 100 / (1 + ag / al))
    else:
        out["rsi_14"] = np.nan
    lv = np.log1p(d.v)
    past = lv.iloc[-21:-1].dropna()
    out["volz_20"] = (lv.iloc[-1] - past.mean()) / past.std(ddof=1) if len(past) >= 15 else np.nan
    dp = d.dp.clip(0, 100)
    pdp = dp.iloc[-21:-1].dropna()
    out["deliv_z20"] = (dp.iloc[-1] - pdp.mean()) / pdp.std(ddof=1) if len(pdp) >= 15 else np.nan
    hh = d.high.iloc[-250:]
    out["hi52_dist"] = c.iloc[-1] / hh.max() - 1 if len(hh) >= 120 else np.nan
    # ATR(14) simple mean of true range
    c1 = c.shift(1)
    tr = pd.concat([d.high - d.low, (d.high - c1).abs(), (d.low - c1).abs()], axis=1).max(axis=1)
    tr.iloc[0] = d.high.iloc[0] - d.low.iloc[0]
    trw = tr.iloc[-14:]
    out["atr_pct"] = trw.mean() / c.iloc[-1] if len(trw) >= 14 else np.nan
    r1 = c / c1 - 1
    rw = r1.iloc[-20:].dropna()
    out["max_ret_20"] = rw.max() if len(rw) >= 15 else np.nan
    out["gap_open"] = d.open.iloc[-1] / c.iloc[-2] - 1 if len(c) > 1 else np.nan
    # beta_60 vs Nifty 500 log returns on the same dates
    mlr = np.log(mk / mk.shift(1)).reindex(pd.DatetimeIndex(d.date)).values
    xs = lr1.values[-60:]
    ys = mlr[-60:]
    ok = ~np.isnan(xs) & ~np.isnan(ys)
    if ok.sum() >= 45:
        xx, yy = xs[ok], ys[ok]
        out["beta_60"] = np.mean(xx * yy) - xx.mean() * yy.mean()
        out["beta_60"] /= (np.mean(yy * yy) - yy.mean() ** 2)
    else:
        out["beta_60"] = np.nan
    return out


rows = []
for i in pick:
    rec = features_from_truncated(i)
    for f in FEATS:
        a = float(F[f].values[i])
        b = float(rec[f])
        rows.append({"row": int(i), "symbol": P.symbol.values[i], "date": str(P.date.values[i])[:10],
                     "future_split": bool(has_future_split[i]), "feature": f, "lab": a, "recomputed": b,
                     "abs_diff": abs(a - b) if np.isfinite(a) and np.isfinite(b) else (0.0 if (np.isnan(a) and np.isnan(b)) else np.inf)})
T = pd.DataFrame(rows)
T["rel_diff"] = T.abs_diff / np.maximum(T.recomputed.abs(), 1e-3)
T["match"] = (T.abs_diff < 1e-4) | (T.rel_diff < 1e-4)
summ = T.groupby("feature").agg(n=("match", "size"), matched=("match", "sum"), max_abs_diff=("abs_diff", "max"),
                                max_rel_diff=("rel_diff", "max"))
print(summ)
print(T[~T.match].head(30).to_string())
save("s2_pit", {"rows_checked": int(len(pick)), "rows_with_future_split": int(has_future_split[pick].sum()),
                "summary": summ.reset_index().to_dict("records"),
                "mismatches": T[~T.match].to_dict("records"),
                "sample_rows": T.groupby("row").first().reset_index()[["row", "symbol", "date", "future_split"]].to_dict("records")})

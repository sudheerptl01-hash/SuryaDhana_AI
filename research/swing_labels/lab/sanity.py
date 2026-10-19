#!/usr/bin/env python3
"""Quick sanity checks on the built lab before the team starts."""
import json
import os
import sys

import numpy as np
import pandas as pd

LAB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LAB)
import lablib as L  # noqa: E402

P = L.load_panel()
F = L.load_features(["elig_base", "atr_pct", "mom_20", "fno_proxy", "mkt_dist_sma200"])
fw = L.Fwd(P)
out = {}
out["rows"] = len(P)
out["entities"] = int(P.entity.nunique())
out["elig_base_rows"] = int(F.elig_base.sum())
out["elig_base_per_day_median"] = float(F.groupby(P.date).elig_base.sum().median())
r = P.loc[P.ca_event, "ca_ratio"]
out["ca_rows"] = int(P.ca_event.sum())
out["ca_ratio_quantiles"] = r.quantile([0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99]).round(4).to_dict()
out["ca_rows_per_year"] = P.loc[P.ca_event].groupby(P.date.dt.year).size().to_dict()
out["label_block_rows"] = int(P.label_block.sum())
# known splits/bonuses: adjusted close must be continuous across the ex-date
known = [("TATASTEEL", "2022-07-28"), ("IRCTC", "2021-10-28"), ("BAJFINANCE", "2025-06-16")]
kk = {}
for sym, d in known:
    s = P[(P.symbol == sym)].reset_index()
    j = s.index[s.date == pd.Timestamp(d)]
    if len(j):
        j = j[0]
        kk[sym] = {"raw_jump": float(s.raw_close[j] / s.raw_close[j - 1] - 1),
                   "adj_jump": float(s.close[j] / s.close[j - 1] - 1),
                   "ca_ratio": float(s.ca_ratio[j]), "label_block": bool(s.label_block[j])}
out["known_splits"] = kk
big = P.index[P.ca_event & (P.ca_ratio < 0.8)]
raw_jump, adj_jump = [], []
for i in big:
    if i == 0 or P.entity.iat[i - 1] != P.entity.iat[i]:
        continue
    raw_jump.append(P.raw_close.iat[i] / P.raw_close.iat[i - 1] - 1)
    adj_jump.append(P.close.iat[i] / P.close.iat[i - 1] - 1)
out["split_bonus_events_checked"] = len(raw_jump)
out["split_raw_jump_median"] = float(np.median(raw_jump)) if raw_jump else None
out["split_adj_jump_median"] = float(np.median(adj_jump)) if adj_jump else None
out["split_adj_abs_jump_p90"] = float(np.quantile(np.abs(adj_jump), 0.9)) if adj_jump else None
lr = np.log(P.close / P.groupby("entity").close.shift())
out["adj_abs_daily_move_gt_30pct_rows"] = int((lr.abs() > np.log(1.3)).sum())

# entity bridging examples (multiple symbols)
ms = P.groupby("entity").symbol.agg(lambda s: list(dict.fromkeys(s)))
multi = ms[ms.map(len) > 1]
out["renamed_entities"] = int(len(multi))
out["rename_examples"] = {k: v for k, v in list(multi.items())[:12]}

# forward validity and executable returns
for h in (5, 10, 20):
    ok = fw.ok(h) & F.elig_base.values
    r_ex = L.fwd_return(P, fw, h)
    m = ok & np.isfinite(r_ex)
    out[f"h{h}_valid_share_of_elig"] = float(m.sum() / F.elig_base.sum())
    out[f"h{h}_exec_ret_mean_bps"] = float(np.nanmean(r_ex[m]) * 1e4)
    out[f"h{h}_exec_ret_median_bps"] = float(np.nanmedian(r_ex[m]) * 1e4)
    out[f"h{h}_p_up"] = float((r_ex[m] > 0).mean())
mk = L.market_series("Nifty 500")
out["nifty500_rows"] = len(mk)
out["nifty500_first_last"] = [str(mk.index.min().date()), str(mk.index.max().date()),
                              float(mk.close.iloc[0]), float(mk.close.iloc[-1])]
out["sectors"] = "removed (2026 snapshot = look-ahead)"
out["fno_proxy_share_of_elig"] = float(F.loc[F.elig_base, "fno_proxy"].mean())
print(json.dumps(out, indent=1, default=str))
with open(os.path.join(LAB, "sanity.json"), "w") as fh:
    json.dump(out, fh, indent=1, default=str)

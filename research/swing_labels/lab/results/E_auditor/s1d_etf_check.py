#!/usr/bin/env python3
"""Stage 1d: are non-equity instruments (ETFs / MF units: ISIN 'INF...') inside elig_base?"""
import numpy as np
import pandas as pd
from common import L, save
P = L.load_panel(["date", "entity", "symbol", "isin", "open", "close", "seg_break", "label_block"])
F = L.load_features(["elig_base", "fno_proxy", "atr_pct"])
eb = F.elig_base.values
isin = P["isin"].values
etf = pd.Series(isin).str.startswith("INF").values
fw = L.Fwd(P)
r = L.fwd_return(P, fw, 10)
d = pd.DatetimeIndex(P.date.values)
R = {"etf_rows_total": int(etf.sum()), "etf_entities": int(pd.Series(P.entity.values[etf]).nunique()),
     "etf_rows_in_elig_base": int((etf & eb).sum()), "etf_share_of_elig_base": float((etf & eb).sum() / eb.sum()),
     "etf_entities_in_elig_base": int(pd.Series(P.entity.values[etf & eb]).nunique()),
     "etf_rows_in_fno_proxy_elig": int((etf & eb & F.fno_proxy.values).sum()),
     "etf_elig_per_day_median": float(pd.Series((etf & eb)).groupby(d).sum().median()),
     "etf_elig_by_year": pd.Series((etf & eb)).groupby(d.year).sum().to_dict(),
     "top_etf_symbols_in_elig": pd.Series(P.symbol.values[etf & eb]).value_counts().head(25).to_dict(),
     "etf_elig_atr_pct_median": float(np.nanmedian(F.atr_pct.values[etf & eb])),
     "stock_elig_atr_pct_median": float(np.nanmedian(F.atr_pct.values[~etf & eb])),
     "etf_elig_h10_ret_mean_bps": float(np.nanmean(r[etf & eb]) * 1e4),
     "etf_elig_h10_abs_ret_mean_bps": float(np.nanmean(np.abs(r[etf & eb])) * 1e4),
     "stock_elig_h10_abs_ret_mean_bps": float(np.nanmean(np.abs(r[~etf & eb])) * 1e4)}
print(R)
save("s1d_etf_check", R)

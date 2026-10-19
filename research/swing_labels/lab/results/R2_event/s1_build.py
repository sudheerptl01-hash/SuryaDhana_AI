"""Stage 1: base arrays (row-aligned with panel) -> base.npz.

r_h  = open[t+1] -> close[t+h] (L.fwd_return, NaN unless fw.ok(h)), h in {5,10,20}
mu_h = per-date mean of r_h over U (finite), med_h = per-date median; x_h = r_h - mu_h
lo_prev_L = min(low[t-L..t-1]) within segment (min_periods = 0.75 L)  -> breakdown flags
r1   = close[t]/close[t-1]-1 (in segment); vol20_lag = vol_20[t-1]; atr_lag = atr_pct[t-1]
liq  = per-date tercile of log_turn20 over U (universe terciles, not event-internal)
reg  = 0 bull_up20 / 1 bull_dn20 / 2 bear_up20 / 3 bear_dn20 (Nifty 500 vs SMA200, 20d momentum)
"""
import numpy as np
import pandas as pd

from common import L, OUT, HS, T, save

t = T()
P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
FC = ["elig_base", "elig_liq5", "fno_proxy", "volz_20", "vol_20", "atr_pct", "gap_open", "intraday", "range_pos",
      "rsi_14", "mom_5", "mom_20", "lo52_dist", "log_turn20", "mkt_mom20", "mkt_mom5", "mkt_dist_sma200",
      "dist_sma200", "deliv_z20", "breadth50", "vix"]
F = L.load_features(FC)
t("loaded")
fw = L.Fwd(P)
n = len(P)
dates = P["date"].values.astype("datetime64[D]")
cal = np.unique(dates)
didx = np.searchsorted(cal, dates)
U = F["elig_base"].values.astype(bool)
start = fw.start
out = {}
for h in HS:
    r = L.fwd_return(P, fw, h)
    ok = U & np.isfinite(r)
    s = pd.Series(np.where(ok, r, np.nan))
    g = s.groupby(didx)
    mu = g.transform("mean").values
    med = g.transform("median").values
    out[f"r{h}"] = r.astype(np.float32)
    out[f"x{h}"] = (r - mu).astype(np.float32)
    out[f"med{h}"] = med.astype(np.float32)
    out[f"mu{h}"] = mu.astype(np.float32)
    t(f"fwd h={h}: valid U share {ok.sum() / U.sum():.4f}")

c = P["close"].values
lo = P["low"].values
lo_prev = L.lag(lo, 1, start)
seg = pd.Series(fw.seg)
for Lb in (10, 20, 40):
    mp = int(np.ceil(0.75 * Lb))
    lo_L = (pd.Series(lo_prev).groupby(seg).rolling(Lb, min_periods=mp).min()
            .reset_index(level=0, drop=True).sort_index().values)
    out[f"bdd{Lb}"] = (c / lo_L - 1).astype(np.float32)          # <0 => close below prior L-bar low
    t(f"lookback {Lb}")
c1 = L.lag(c, 1, start)
out["r1"] = (c / c1 - 1).astype(np.float32)
out["vol20_lag"] = L.lag(F["vol_20"].values, 1, start).astype(np.float32)
out["atr_lag"] = L.lag(F["atr_pct"].values, 1, start).astype(np.float32)

lt = F["log_turn20"].values.astype("float64")
lr = pd.Series(np.where(U & np.isfinite(lt), lt, np.nan)).groupby(didx).rank(pct=True).values
liq = np.where(np.isnan(lr), -1, np.minimum((lr * 3).astype(int), 2)).astype(np.int8)
m200 = F["mkt_dist_sma200"].values
m20 = F["mkt_mom20"].values
reg = np.where(m200 > 0, np.where(m20 > 0, 0, 1), np.where(m20 > 0, 2, 3)).astype(np.int8)
reg[np.isnan(m200) | np.isnan(m20)] = -1
# per-date xs rank of mom_5 over U (short-term loser event)
m5 = F["mom_5"].values.astype("float64")
out["xr_mom5"] = pd.Series(np.where(U & np.isfinite(m5), m5, np.nan)).groupby(didx).rank(pct=True).values.astype(np.float32)

for k in ("volz_20", "vol_20", "atr_pct", "gap_open", "intraday", "range_pos", "rsi_14", "mom_5", "mom_20",
          "lo52_dist", "log_turn20", "mkt_mom20", "mkt_mom5", "mkt_dist_sma200", "dist_sma200", "deliv_z20",
          "breadth50", "vix"):
    out[k] = F[k].values.astype(np.float32)
np.savez_compressed(f"{OUT}/base.npz", **out, U=U, liq5=F["elig_liq5"].values.astype(bool),
                    fno=F["fno_proxy"].values.astype(bool), day=dates.astype("int64").astype(np.int32),
                    seg=fw.seg.astype(np.int32), liq=liq, reg=reg)
pos = np.searchsorted(cal, np.datetime64("2025-12-31"), side="right") - 1
info = {"rows": n, "U_rows": int(U.sum()), "trading_days": len(cal),
        "dev_end_signal": {h: str(cal[pos - h]) for h in HS},
        "valid_share_of_U": {h: float((U & np.isfinite(out[f"r{h}"])).sum() / U.sum()) for h in HS},
        "U_per_day_median": float(pd.Series(U).groupby(didx).sum().median())}
save("s1_build", info)
print(info)
t("done")

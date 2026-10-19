"""Stage 1: primary barrier labels (long + short), setup masks, regime/liquidity tags -> base.npz."""
import numpy as np
import pandas as pd

from common import L, OUT, H, PT, SL, LONG_SETUPS, SHORT_SETUPS, save, T

t = T()
P = L.load_panel(["date", "entity", "isin", "open", "high", "low", "close", "seg_break", "label_block"])
FC = ["hi20_dist", "volz_20", "hi52_dist", "lo52_dist", "dist_sma200", "mom_60", "dist_sma20", "rsi_14",
      "vol_ratio", "deliv_z20", "intraday", "mom_20", "mom_5", "xr_mom60", "xr_mom20", "sec_rel_mom20",
      "rel_mom20", "mkt_dist_sma200", "mkt_mom20", "gap_open", "range_pos", "atr_pct", "log_turn20",
      "elig_base", "fno_proxy"]
F = L.load_features(FC)
t("loaded")
fw = L.Fwd(P)
n = len(P)
dates = P["date"].values.astype("datetime64[D]")
cal = np.unique(dates)
U = F["elig_base"].values.astype(bool) & P["isin"].str.startswith("INE").values
etf_removed = int((F["elig_base"].values & ~U).sum())

# ---------------- primary labels ----------------
out = {}
for side in ("long", "short"):
    b = L.barrier_labels(P, F, fw, h=H, pt=PT, sl=SL, side=side, tau_bps=50.0)
    tc = np.zeros(n, np.int8)
    tc[b["touch"] == "pt"] = 1
    tc[b["touch"] == "sl"] = -1
    tc[~b["valid"]] = -9
    s = side[0].upper()
    out[f"lab_{s}"] = b["label"].astype(np.float32)
    out[f"ret_{s}"] = b["ret"].astype(np.float32)
    out[f"k_{s}"] = b["k"].astype(np.float32)
    out[f"touch_{s}"] = tc
    out[f"mfe_{s}"] = b["mfe"].astype(np.float32)
    out[f"mae_{s}"] = b["mae"].astype(np.float32)
    del b
    t(f"barrier {side}")
fwd10 = L.fwd_return(P, fw, H)
mkt10 = L.market_fwd(P, H)
t("fwd")

# ---------------- extra PIT feature: prior 20-bar low ----------------
start = fw.start
lo_prev = L.lag(P["low"].values, 1, start)
seg = pd.Series(fw.seg)
lo20 = (pd.Series(lo_prev).groupby(seg).rolling(20, min_periods=15).min()
        .reset_index(level=0, drop=True).sort_index().values)
lo20_dist = P["close"].values / lo20 - 1

g = {c: F[c].values.astype("float64") for c in FC if not c.startswith("elig") and c != "fno_proxy"}
dkey = pd.Series(dates)


def xs_rank(x, m):
    s = pd.Series(np.where(m & np.isfinite(x), x, np.nan))
    return s.groupby(dkey).rank(pct=True).values


sec_rank = xs_rank(g["sec_rel_mom20"], U)
rel_rank = xs_rank(g["rel_mom20"], U)
liq_rank = xs_rank(g["log_turn20"], U)
liq_terc = np.where(np.isnan(liq_rank), -1, np.minimum((liq_rank * 3).astype(int), 2)).astype(np.int8)
bull = g["mkt_dist_sma200"] > 0

with np.errstate(invalid="ignore"):
    S = {
        "L1_bo20": (g["hi20_dist"] > 0) & (g["volz_20"] > 1),
        "L2_bo52": (g["hi52_dist"] > -0.01) & (g["volz_20"] > 0.5),
        "L3_pullback": (g["dist_sma200"] > 0) & (g["mom_60"] > 0) & (g["dist_sma20"] > -0.03)
                       & (g["dist_sma20"] < 0.01) & (g["rsi_14"] < 50),
        "L4_vcp": (g["vol_ratio"] < 0.75) & (g["hi20_dist"] > 0),
        "L5_deliv": (g["deliv_z20"] > 1.5) & (g["intraday"] > 0) & (g["mom_20"] > 0),
        "L6_rslead": (g["xr_mom60"] > 0.9) & (g["xr_mom20"] > 0.7),
        "L7_oversold_up": (g["rsi_14"] < 30) & (g["dist_sma200"] > 0),
        "L8_seclead_LEAKY": (sec_rank > 0.9) & bull,
        "L8b_mktlead": (rel_rank > 0.9) & bull,
        "L9_gaphold": (g["gap_open"] > 0.02) & (g["range_pos"] > 0.7) & (g["volz_20"] > 1),
        "S1_bd20": (lo20_dist < 0) & (g["volz_20"] > 1),
        "S2_failrally": (g["dist_sma200"] < 0) & (g["rsi_14"] > 60) & (g["mom_5"] < 0),
        "S3_rslag": (g["xr_mom60"] < 0.1) & (g["xr_mom20"] < 0.3),
        "S4_bd52": (g["lo52_dist"] < 0.01) & (g["volz_20"] > 0.5),
        "S5_gapfail": (g["gap_open"] < -0.02) & (g["range_pos"] < 0.3) & (g["volz_20"] > 1),
    }
assert set(S) == set(LONG_SETUPS) | set(SHORT_SETUPS)
names = list(S)
SM = np.zeros((n, len(names)), dtype=bool)
for j, k in enumerate(names):
    SM[:, j] = S[k] & U
t("setups")

# regime code: 0 bull_up20, 1 bull_dn20, 2 bear_up20, 3 bear_dn20, -1 nan
mm20 = g["mkt_mom20"]
reg = np.where(bull, np.where(mm20 > 0, 0, 1), np.where(mm20 > 0, 2, 3)).astype(np.int8)
reg[np.isnan(g["mkt_dist_sma200"]) | np.isnan(mm20)] = -1

# dev end: last signal date whose t+H trading date <= 2025-12-31
pos = np.searchsorted(cal, np.datetime64("2025-12-31"), side="right") - 1
dev_end = str(cal[pos - H])
ent_codes = pd.factorize(P["entity"].values)[0].astype(np.int32)

np.savez_compressed(
    f"{OUT}/base.npz", **out, fwd10=fwd10.astype(np.float32), mkt10=mkt10.astype(np.float32),
    U=U, fno=F["fno_proxy"].values.astype(bool), day=dates.astype("int64").astype(np.int32),
    ent=ent_codes, seg=fw.seg.astype(np.int32), reg=reg, liq=liq_terc, setups=SM,
    setup_names=np.array(names), mkt_dist_sma200=g["mkt_dist_sma200"].astype(np.float32),
    mkt_mom20=mm20.astype(np.float32), log_turn20=g["log_turn20"].astype(np.float32),
    atr_pct=g["atr_pct"].astype(np.float32))
info = {"rows": n, "U_rows": int(U.sum()), "etf_rows_removed_from_elig_base": etf_removed,
        "U_valid_long": int((U & ~np.isnan(out["lab_L"])).sum()),
        "dev_end_signal_date": dev_end,
        "setup_rows_on_U": {k: int(SM[:, j].sum()) for j, k in enumerate(names)},
        "pt_mult_atr": float(PT), "sl_mult_atr": float(SL)}
save("s1_build", info)
print(info)
t("done")

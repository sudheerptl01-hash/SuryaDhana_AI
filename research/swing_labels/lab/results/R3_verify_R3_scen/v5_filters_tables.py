#!/usr/bin/env python3
"""R3_verify_R3_scen v5: (a) filters x frozen label at h=20 with my own washout-gate inputs
(bdd10, brd recomputed from the panel, point-in-time); (b) html_tables / key_numbers vs results.json;
(c) Nifty 500 CAGR with the proper base close."""
import json
import time

import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
OUT = f"{LAB}/results/R3_verify_R3_scen"
T0 = time.time()


def log(*a):
    print(f"[{time.time() - T0:6.1f}s]", *a, flush=True)


P = pd.read_parquet(f"{LAB}/panel.parquet", columns=["date", "entity", "open", "low", "close", "seg_break", "label_block"])
F = pd.read_parquet(f"{LAB}/features.parquet", columns=["elig_base", "elig_liq5", "fno_proxy", "dist_sma200", "xr_mom60",
                                                         "deliv_pct", "volz_20", "mkt_mom20"])
n = len(P)
E = F["elig_base"].values.astype(bool)
dates = P["date"].values.astype("datetime64[D]")
ent = P["entity"].values
o = P["open"].values.astype("float64")
lo = P["low"].values.astype("float64")
c = P["close"].values.astype("float64")
lb = P["label_block"].values.astype(bool)
newseg = np.r_[True, ent[1:] != ent[:-1]] | P["seg_break"].values.astype(bool)
del P, ent
segid = np.cumsum(newseg) - 1
firsts = np.flatnonzero(newseg)
seg_start = firsts[segid]
seg_end = np.r_[firsts[1:] - 1, n - 1][segid]
lbcum = np.cumsum(lb)
ii = np.arange(n)
cal = np.unique(dates)
ncal = len(cal)
didx = np.searchsorted(cal, dates)
H = 20
j = np.minimum(ii + H, n - 1)
valid = ((ii + H) <= seg_end) & ((dates[j] - dates).astype("int64") <= 36) & ((lbcum[j] - lbcum) == 0)
e1 = np.where(ii + 1 <= seg_end, o[np.minimum(ii + 1, n - 1)], np.nan)
r20 = np.where(valid, c[j] / e1 - 1, np.nan)
pct = np.load(f"{LAB}/results/R3_devil/label_h20_neumom.npz")["pct"].astype("float64")

# own point-in-time breakdown depth: close[t] / min(low[t-L..t-1]) - 1 within segment, min_periods ceil(.75L)
lo_prev = np.where(ii - 1 >= seg_start, lo[np.maximum(ii - 1, 0)], np.nan)


def bdd(Lb):
    s = pd.Series(lo_prev)
    m = s.groupby(segid).rolling(Lb, min_periods=int(np.ceil(0.75 * Lb))).min().reset_index(level=0, drop=True).sort_index().values
    return c / m - 1


bdd10 = bdd(10)
bdd20 = bdd(20)
nE = np.bincount(didx[E], minlength=ncal)
brd_day = np.bincount(didx[E & (bdd20 < 0)], minlength=ncal) / np.maximum(nE, 1)
brd = brd_day[didx]
zb = np.load(f"{LAB}/results/R2_event/base.npz")
b10_their = zb["bdd10"].astype("float64")
okb = np.isfinite(b10_their) & np.isfinite(bdd10)
chk = {"bdd10_sign_agree": float(((b10_their[okb] < 0) == (bdd10[okb] < 0)).mean()),
       "bdd10_finite_mismatch": int((np.isfinite(b10_their) != np.isfinite(bdd10)).sum()),
       "brd_day_maxdiff": float(np.nanmax(np.abs(np.load(f"{LAB}/results/R2_event/brd_day.npy") - brd_day)))}
log("washout input check", chk)
dp = F["deliv_pct"].values.astype("float64")
dpr = pd.Series(np.where(E & np.isfinite(dp), dp, np.nan)).groupby(didx).rank(pct=True).values
FILT = {
    "elig": E,
    "liq5": E & F["elig_liq5"].values.astype(bool),
    "fno": E & F["fno_proxy"].values.astype(bool),
    "trend": E & (F["dist_sma200"].values > 0) & (F["xr_mom60"].values > 0.7),
    "washout": E & (bdd10 < 0) & (F["volz_20"].values > 0) & (F["mkt_mom20"].values < 0) & (brd >= 0.05),
    "deliv": E & (dpr > 2 / 3),
}
g_dev0 = int(np.searchsorted(cal, np.datetime64("2023-01-01")))
g_dev_last = int(np.searchsorted(cal, np.datetime64("2025-12-31"), side="right")) - 1
g_hold0 = int(np.searchsorted(cal, np.datetime64("2026-01-01")))
DEV = (didx >= g_dev0) & (didx + H <= g_dev_last)
HOLD = didx >= g_hold0
res = {"washout_input_check": chk, "filters": {}}
for k, m in FILT.items():
    v = m & np.isfinite(r20)
    vl = v & np.isfinite(pct)
    net = r20 - 0.005
    res["filters"][k] = {"rows_valid": int(v.sum()), "xr_up_share": float((pct[vl] > 0.7).mean()),
                         "xr_down_share": float((pct[vl] <= 0.3).mean()),
                         "mean_net_all": float(net[v].mean()), "mean_net_dev": float(net[v & DEV].mean()),
                         "mean_net_2026": float(net[v & HOLD].mean()),
                         "share_days_active": float((np.bincount(didx[v], minlength=ncal) > 0).mean()),
                         "xr_up_mean_net": float(net[vl & (pct > 0.7)].mean()),
                         "xr_down_mean_net": float(net[vl & (pct <= 0.3)].mean())}
    log(f"{k:8s}", {a: (round(b, 4) if isinstance(b, float) else b) for a, b in res["filters"][k].items()})

# ---------------------------------------------------------------- (b) html_tables & key_numbers vs results.json
R = json.load(open(f"{LAB}/results/R3_scen/results.json"))
T = {t["id"]: t for t in R["html_tables"]}
Z, D, PS, HE, OI, TX, SC, FI = (R["zoo"], R["old_label_defects"], R["prod_by_scenario_h20"], R["horizon_random_books"],
                                R["overnight_intraday_split"], R["overnight_tax_by_h"], R["scenarios_h20"], R["filters_h20"])
bad = []


def eq(a, b, where):
    if a is None and b is None:
        return
    if a is None or b is None or abs(float(a) - float(b)) > 1e-12:
        bad.append((where, a, b))


labs = ["old", "cs", "three", "b22", "b315", "pct_neu", "pct_neumom", "dual"]
for i, k in enumerate(labs):
    row = T["t1_label_verdict_h20"]["rows"][i]
    s = Z[f"{k}_h20"]
    eq(row[2], s["shares_all"].get("1"), f"t1 {k} up")
    eq(row[5], s["shares_dev"].get("1"), f"t1 {k} dev")
    eq(row[6], s["shares_hold"].get("1"), f"t1 {k} hold")
    eq(row[7], s["daily_pos"]["sd"], f"t1 {k} sd")
    eq(row[10], s["corr_daily_pos_vs_mkt_same_window"], f"t1 {k} corr")
for i, h in enumerate((5, 10, 15, 20)):
    row = T["t2_old_label_defects"]["rows"][i]
    d = D[f"h{h}"]
    eq(row[1], d["share_nan_to_0"], f"t2 h{h} nan")
    eq(row[6], d["share_old_vs_clean_sign_disagree"], f"t2 h{h} disagree")
    eq(row[9], d["mean_close_entry_ret"] - d["mean_exec_ret"], f"t2 h{h} phantom")
for row in T["t7_prod_by_scenario"]["rows"]:
    p = PS[row[0]]
    eq(row[4], p["dev"].get("excess_vs_universe"), f"t7 {row[0]} dev ex")
    eq(row[5], p["dev"].get("excess_nw_t"), f"t7 {row[0]} dev t")
    eq(row[11], p["hold"].get("excess_vs_universe"), f"t7 {row[0]} hold ex")
    eq(row[14], p["hold"].get("ic_vs_label"), f"t7 {row[0]} hold ic")
for i, h in enumerate((5, 10, 15, 20)):
    row = T["t8_random_book_by_horizon"]["rows"][i]
    eq(row[2], HE[f"random_h{h}_c50_dev"]["cagr"], f"t8 h{h} dev")
    eq(row[5], HE[f"random_h{h}_c50_hold"]["cagr"], f"t8 h{h} hold")
    eq(row[7], HE[f"ew_h{h}_c50_dev"]["cagr"], f"t8 h{h} ew")
for row in T["t10_overnight_tax"]["rows"]:
    x = TX[f"h{row[0]}_{'dev' if row[1] == '2023-25' else 'hold'}"]
    eq(row[5], x["fraction_of_close_entry_return_forfeited"], f"t10 h{row[0]} {row[1]}")
kn = R["key_numbers"]
pairs = [("clean_sign_h20_up_share", Z["cs_h20"]["shares_all"]["1"]), ("dual_h20_corr_same_window", Z["dual_h20"]["corr_daily_pos_vs_mkt_same_window"]),
         ("prod_dev_top20_excess", PS["All days"]["dev"]["excess_vs_universe"]), ("prod_2026_ic", PS["All days"]["hold"]["ic_vs_label"]),
         ("random_h20_c50_hold", HE["random_h20_c50_hold"]["cagr"]), ("tax_h5_dev_fraction", TX["h5_dev"]["fraction_of_close_entry_return_forfeited"]),
         ("washout_gate_xr_up_share", FI["washout"]["pct_neumom"]["shares_all"]["1"]), ("trend_gate_xr_up_share", FI["trend"]["pct_neumom"]["shares_all"]["1"]),
         ("overnight_ann_dev", OI["all_overnight_dev"]["ann_compounded"]), ("scen_crash_xr_p_net_pos_up", SC["Ex-post mkt next 20d < -5%"]["all"]["pct_neumom"]["p_net_pos_given_pos"])]
for k, v in pairs:
    eq(kn[k], v, f"key {k}")
res["table_mismatches"] = bad
log("html/key mismatches:", bad)
ch = R["charts"]["monthly_up_share_h20"]["series"]
cs_m = [x for x in ch["Clean sign (absolute) – share of stocks labelled up"] if x is not None]
res["chart_monthly_cs_min_max"] = [min(cs_m), max(cs_m)]
log("chart monthly clean-sign up share min/max", res["chart_monthly_cs_min_max"])

# ---------------------------------------------------------------- (c) Nifty 500 CAGR with proper base close
idx = pd.read_parquet(f"{LAB}/index.parquet")
mk = idx[idx["index"] == "Nifty 500"].drop_duplicates("date").set_index("date").sort_index()["close"]
b0 = mk[mk.index <= "2022-12-31"].iloc[-1]
b1 = mk[mk.index <= "2025-12-31"].iloc[-1]
yrs = (mk[mk.index <= "2025-12-31"].index[-1] - mk[mk.index <= "2022-12-31"].index[-1]).days / 365.25
h0 = b1
h1 = mk.iloc[-1]
yrs_h = (mk.index[-1] - mk[mk.index <= "2025-12-31"].index[-1]).days / 365.25
res["nifty500"] = {"dev_cagr_proper_base": float((b1 / b0) ** (1 / yrs) - 1), "hold_ann_proper_base": float((h1 / h0) ** (1 / yrs_h) - 1),
                   "hold_ytd_return": float(h1 / h0 - 1)}
log("nifty500", res["nifty500"])
json.dump(res, open(f"{OUT}/v5_results.json", "w"), indent=1)
log("done")

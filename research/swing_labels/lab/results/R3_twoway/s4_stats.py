"""Stage 4: statistics for every strategy/baseline series: CAGR, vol, Sharpe, maxDD, worst month, % positive months,
correlation & beta with Nifty 500, months when Nifty 500 fell > 3%, paired diff vs BASE (NW t) and the PREREG
adoption rule, short-leg selection value vs random shorts, calendar-year returns, and the characteristics
(tilts) of the F&O short picks vs random F&O names (boring-explanation check)."""
import sys
import numpy as np
import pandas as pd
LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
sys.path.insert(0, LAB)
import r3common as C
L = C.L
C.set_agent("R3_twoway")
z = np.load(f"{LAB}/results/R3_twoway/series_s3.npz", allow_pickle=True)
keys = list(z["keys"])
SER = {k: pd.Series(z[f"v{i}"], index=pd.DatetimeIndex(z[f"d{i}"])) for i, k in enumerate(keys)}
N500 = SER["N500"]
STRATS = ["BASE", "D0", "D1a", "D1b", "D1c", "D2_K10_cash", "D2_K10_fut", "D2_K20_cash", "D2_K20_fut",
          "X1_D2_K20_cash_beta", "D3", "D4"]
BASELINES = ["RAND", "EW", "R_D0_rand70", "R_D4_randshort", "R_D2_K20_cash_rand", "R_D3_randshort", "R_BASE_fnolong_rand"]


def full_stats(r, base=None):
    r = r.dropna()
    st = C.stats_from_daily(r)
    m = N500.reindex(r.index).fillna(0.0)
    st["corr_n500_daily"] = float(np.corrcoef(r.values, m.values)[0, 1])
    st["beta_n500_daily"] = float(np.cov(r.values, m.values)[0, 1] / np.var(m.values, ddof=1))
    mr = (1 + r).groupby(r.index.to_period("M")).prod() - 1
    mm = (1 + m).groupby(m.index.to_period("M")).prod() - 1
    st["corr_n500_monthly"] = float(np.corrcoef(mr.values, mm.values)[0, 1]) if len(mr) > 3 else None
    down = mm < -0.03
    st["n500_down_months_n"] = int(down.sum())
    st["down_months_mean_ret"] = float(mr[down].mean()) if down.any() else None
    st["down_months_n500_mean"] = float(mm[down].mean()) if down.any() else None
    st["down_months_hit_vs_n500"] = float((mr[down] > mm[down]).mean()) if down.any() else None
    st["down_months_list"] = {str(k): [float(mr[k]), float(mm[k])] for k in mr[down].index}
    yrs = r.groupby(r.index.year)
    st["by_year"] = {int(y): float(np.prod(1 + g.values) - 1) for y, g in yrs}
    if base is not None:
        st["vs_base"] = C.paired(r, base)
        st["maxdd_change_vs_base"] = float(st["maxdd"] - C.stats_from_daily(base.reindex(r.index).dropna())["maxdd"])
    return st


out = {}
for cost in ("c50", "c80"):
    for per in ("dev", "hold", "contig"):
        base = SER[f"BASE|{per}|{cost}"]
        res = {}
        for nm in STRATS + BASELINES:
            k = f"{nm}|{per}|{cost}"
            if k not in SER:
                continue
            res[nm] = full_stats(SER[k], None if nm == "BASE" else base)
        # adoption rule (PREREG) — evaluated on DEV only, reported for every add-on
        for nm in ("D1a", "D1b", "D1c", "D2_K10_cash", "D2_K10_fut", "D2_K20_cash", "D2_K20_fut", "X1_D2_K20_cash_beta", "D3", "D4"):
            vb = res[nm]["vs_base"]
            res[nm]["adopt_rule_pass"] = bool(vb["nw_t"] >= 2 and res[nm]["maxdd_change_vs_base"] >= -0.03)
        # D0 is judged vs the EW universe (round-2 definition)
        ew = SER[f"EW|{per}|{cost}"]
        res["D0"]["vs_ew"] = C.paired(SER[f"D0|{per}|{cost}"], ew)
        res["D0"]["maxdd_change_vs_ew"] = float(res["D0"]["maxdd"] - C.stats_from_daily(ew.reindex(SER[f"D0|{per}|{cost}"].index).dropna())["maxdd"])
        res["D0"]["adopt_rule_pass_vs_ew"] = bool(res["D0"]["vs_ew"]["nw_t"] >= 2 and res["D0"]["maxdd_change_vs_ew"] >= -0.03)
        res["BASE"]["vs_random"] = C.paired(base, SER[f"RAND|{per}|{cost}"])
        res["BASE"]["vs_ew"] = C.paired(base, ew)
        # short-side selection value: strategy vs the same construction with random shorts
        res["selection"] = {
            "D4_vs_random_short": C.paired(SER[f"D4|{per}|{cost}"], SER[f"R_D4_randshort|{per}|{cost}"]),
            "D2_K20_cash_vs_random_LS": C.paired(SER[f"D2_K20_cash|{per}|{cost}"], SER[f"R_D2_K20_cash_rand|{per}|{cost}"]),
            "D3_vs_D3_random_short": C.paired(SER[f"D3|{per}|{cost}"], SER[f"R_D3_randshort|{per}|{cost}"]),
            "random_short_vs_cash": C.paired(SER[f"R_D4_randshort|{per}|{cost}"], SER["CASH1D"]),
            "D4_vs_cash": C.paired(SER[f"D4|{per}|{cost}"], SER["CASH1D"]),
        }
        out[f"{per}|{cost}"] = res
        C.log(per, cost, {nm: (round(res[nm]["cagr"], 4), round(res[nm]["sharpe"] or 0, 2), round(res[nm]["maxdd"], 3))
                          for nm in STRATS})
# hedge instrument and cash reference stats
ref = {}
for nm in ("N500", "N50FUT", "MSFUT", "CASH1D"):
    for per, (a, b) in (("dev", ("2023-01-06", "2025-12-23")), ("hold", ("2026-01-01", "2026-10-14")),
                        ("contig", ("2023-01-06", "2026-10-14"))):
        s = SER[nm].loc[a:b].dropna()
        ref[f"{nm}|{per}"] = C.stats_from_daily(s)
out["reference_series"] = ref
C.save("s4_stats", out)

# ------------------------------------------------ characteristics of the F&O picks (tilts): phase-0 signal dates
P = L.load_panel(["date"])
F = L.load_features(["elig_base", "fno_proxy", "mom_12_1", "mom_20", "vol_20", "beta_60", "log_turn20", "dist_sma200"])
d = P["date"].values.astype("datetime64[D]")
E = F["elig_base"].values.astype(bool)
fnoE = E & F["fno_proxy"].values.astype(bool)
prod = C.load_prod()["prod"].astype("float64")
m = fnoE & np.isfinite(prod)
df = pd.DataFrame({"d": d[m], "prod": prod[m], **{c: F[c].values[m].astype("float64") for c in
                                                  ("mom_12_1", "mom_20", "vol_20", "beta_60", "log_turn20", "dist_sma200")}})
for c in ("mom_12_1", "mom_20", "vol_20", "beta_60", "log_turn20", "dist_sma200"):
    df["xr_" + c] = df.groupby("d")[c].rank(pct=True)
df["rk"] = df.groupby("d")["prod"].rank(method="first")
df["n"] = df.groupby("d")["prod"].transform("size")
cal = np.unique(d)
tilts = {}
for per, (a, b) in (("dev", ("2023-01-01", "2025-12-31")), ("hold", ("2026-01-01", "2026-12-31"))):
    sig = cal[(cal >= np.datetime64(a)) & (cal <= np.datetime64(b))][::5]
    sub = df[df.d.isin(sig)]
    bot = sub[sub.rk <= 20]
    top = sub[sub.rk > sub.n - 20]
    row = {}
    for c in ("mom_12_1", "mom_20", "vol_20", "beta_60", "log_turn20", "dist_sma200"):
        row[c] = {"bottom20_mean_xs_pct": float(bot["xr_" + c].mean()), "top20_mean_xs_pct": float(top["xr_" + c].mean()),
                  "bottom20_mean_raw": float(bot[c].mean()), "top20_mean_raw": float(top[c].mean()),
                  "all_fno_mean_raw": float(sub[c].mean())}
    row["n_signal_dates"] = int(len(sig))
    tilts[per] = row
C.save("s4_fno_pick_tilts", tilts)
for per, row in tilts.items():
    C.log("tilts", per, {c: (round(v["bottom20_mean_xs_pct"], 3), round(v["top20_mean_xs_pct"], 3)) for c, v in row.items() if isinstance(v, dict)})

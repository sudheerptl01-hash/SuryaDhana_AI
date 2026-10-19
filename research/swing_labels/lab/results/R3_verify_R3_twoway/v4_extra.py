"""Verifier v4 (own code):
(a) Is the D0 avoid veto a multi-factor tilt? Joint OLS of daily (D0 - EW) on five factor vetoes' excess vs EW
    (top-30% vol_20, beta_60, mom_12_1, mom_20 removed; bottom-30% log_turn20 removed), DEV in-sample and the DEV
    slopes applied out of sample to 2026. Also the tilt of PROD's bottom 30% across all eligible names.
(b) Sharpe on returns in excess of cash (Nifty 1D Rate) for BASE, D1a, D1b, D3, D4 from my v3 series.
(c) Down-month (Nifty 500 < -3%) average returns from my v3 series."""
import json
import sys
import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
OUT = LAB + "/results/R3_verify_R3_twoway"
sys.path.insert(0, LAB)
import lablib as L  # noqa: E402


def my_nw_t(x, lag=20):
    x = np.asarray(x, float)
    n = len(x)
    u = x - x.mean()
    s = u @ u / n
    for k in range(1, lag + 1):
        s += 2 * (1 - k / (lag + 1)) * (u[k:] @ u[:-k]) / n
    return x.mean() / np.sqrt(s / n)


out = {}
# ---------------- (b) and (c) from v3 series
z = np.load(OUT + "/v3_series.npz", allow_pickle=True)
SER = {k: pd.Series(z[f"v{i}"], index=pd.DatetimeIndex(z[f"d{i}"])) for i, k in enumerate(z["keys"])}
calI = None
cl = L.market_series("Nifty 1D Rate Index")["close"].astype(float)
n5 = L.market_series("Nifty 500")["close"].astype(float)
for per in ("dev", "2026"):
    names = {"BASE": f"BASE|{per}|signal", "D1a": f"D1a|{per}|theirs_t+1", "D1b": f"D1b|{per}|theirs_t+1",
             "D3": f"D3|{per}|signal", "D4": f"D4|{per}|signal", "R_D4": f"R_D4|{per}|signal"}
    idx = SER[names["BASE"]].index
    rc = cl.reindex(idx).ffill().pct_change().fillna(0.0)      # cash return on the book calendar
    rm = n5.reindex(idx).ffill().pct_change().fillna(0.0)
    mm = (1 + rm).groupby(idx.to_period("M")).prod() - 1
    down = mm[mm < -0.03].index
    res = {"n_down_months": int(len(down)), "n500_down_mean": float(mm[down].mean())}
    for nm, k in names.items():
        r = SER[k].reindex(idx)
        x = r - rc
        mr = (1 + r).groupby(idx.to_period("M")).prod() - 1
        res[nm] = {"raw_sharpe": float(r.mean() / r.std() * np.sqrt(252)),
                   "excess_of_cash_sharpe": float(x.mean() / x.std() * np.sqrt(252)),
                   "down_month_mean": float(mr[down].mean())}
    out[f"sharpe_downmonths|{per}"] = res
    print(per, json.dumps(res), flush=True)

# ---------------- (a) multi-factor veto regression
P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["atr_pct", "elig_base", "vol_20", "beta_60", "mom_12_1", "mom_20", "log_turn20"])
fw = L.Fwd(P)
S = L.Sim(P, F, fw)
E = F["elig_base"].values.astype(bool)
d = P["date"].values.astype("datetime64[D]")
del P
prod = np.load(f"{LAB}/results/_lead/prod_h20.npz", allow_pickle=True)["prod"].astype("float64")


def filled(col):
    v = pd.Series(F[col].values.astype("float64"))
    med = v.where(E).groupby(d).transform("median")
    return v.fillna(med).fillna(0.0).values


SC = {"vol": -filled("vol_20"), "beta": -filled("beta_60"), "mom121": -filled("mom_12_1"), "mom20": -filled("mom_20"),
      "size": filled("log_turn20")}
# tilt of PROD bottom-30% names across all eligible (DEV signal dates)
m = E & np.isfinite(prod) & (d >= np.datetime64("2023-01-01")) & (d <= np.datetime64("2025-12-31"))
df = pd.DataFrame({"d": d[m], "p": prod[m], **{k: -v[m] if k != "size" else v[m] for k, v in SC.items()}})
df["prk"] = df.groupby("d")["p"].rank(pct=True)
tilt = {}
for k in SC:
    df["x"] = df.groupby("d")[k].rank(pct=True)
    tilt[k] = {"bottom30_mean_pct": float(df.loc[df.prk <= 0.3, "x"].mean()), "top70_mean_pct": float(df.loc[df.prk > 0.3, "x"].mean())}
out["tilt_bottom30_all_elig_dev"] = tilt
print("tilt (raw factor pct; size = log_turn20)", json.dumps(tilt), flush=True)
del df


def phased(score, sq, per):
    a, b = per
    g0 = int(np.searchsorted(S.cal, np.datetime64(a)))
    ser = []
    for k in range(5):
        st = S.run(score, E, 20, step=5, cost_bps=50, start=str(S.cal[g0 + k]), end_exit=b, select_quantile=sq, sizing="equal")
        ser.append(pd.Series(st["_daily_ret"], index=pd.DatetimeIndex(st["_dates"])))
    common = ser[0].index
    for x in ser[1:]:
        common = common.intersection(x.index)
    return pd.Series(np.mean([x.reindex(common).values for x in ser], 0), index=common)


coef_dev = None
for pn, per in (("dev", ("2023-01-01", "2025-12-31")), ("2026", ("2026-01-01", None))):
    d0 = phased(prod, (0.3, 1.0), per)
    ew = phased(np.ones(len(E)), (0.0, 1.0), per)
    fx = {k: phased(v, (0.3, 1.0), per) for k, v in SC.items()}
    c = d0.index
    y = (d0 - ew).reindex(c).values
    X = np.c_[np.ones(len(c)), np.column_stack([(fx[k] - ew).reindex(c).values for k in SC])]
    coef = np.linalg.lstsq(X, y, rcond=None)[0]
    resid = y - X[:, 1:] @ coef[1:]
    res = {"d0_vs_ew_ann": float(y.mean() * 252), "factor_veto_vs_ew_ann": {k: float((fx[k] - ew).mean() * 252) for k in SC},
           "slopes": {k: float(b) for k, b in zip(SC, coef[1:])}, "r2": float(1 - np.var(y - X @ coef) / np.var(y)),
           "resid_alpha_ann_insample": float(resid.mean() * 252), "resid_alpha_t_insample": float(my_nw_t(resid))}
    if pn == "dev":
        coef_dev = coef
    else:
        r2 = y - X[:, 1:] @ coef_dev[1:]
        res["resid_alpha_ann_dev_slopes"] = float(r2.mean() * 252)
        res["resid_alpha_t_dev_slopes"] = float(my_nw_t(r2))
    out[f"multifactor|{pn}"] = res
    print(pn, json.dumps(res), flush=True)
json.dump(out, open(OUT + "/v4_extra.json", "w"), indent=1)

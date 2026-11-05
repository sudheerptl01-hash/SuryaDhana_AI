"""
G-STUDY (macro drivers of gold) — pre-registered before any number was computed (see REPORT.md §2).

H1  Real yields: gold's monthly log return is negatively related to the change in the 10y TIPS real yield
    (DFII10), with |t| >= 2 in 2010-2021; the level fit (ln gold on DFII10) has R^2 >= 0.6 in 2010-2021 and the
    same fit breaks down (R^2 < 0.3 or sign flip) in 2022-2026.
H2  Dollar: gold's monthly log return is negatively related to the DXY log change with |t| >= 2 in every regime
    (beta around -1: gold moves roughly one-for-one against the dollar).
H3  Seasonality: the month-of-year effect is NOT reliable at the monthly horizon (no month clears t >= 2 in both
    halves of the sample); expect "Autumn effect" (Sep) and Jan to look best in-sample.
H4  Geopolitical risk (GPR, monthly): the contemporaneous relation is positive but weak (R^2 < 0.05); GPR does
    not predict next month's gold return (|t| < 2).
H5  Mispricing gauge: the residual of the 2010-2021 real-yield fit is a context number, not a signal (its sign
    does not predict the next 3-month return with |t| >= 2 out of sample, 2022-2026).

Everything else (KGX decomposition, ratios, GVZ expected move, gold in currencies, gold/M2) is descriptive.
Inputs: ./data/*.csv written by verify_sources.py. Output: study.json, tables/*.csv.
OLS via numpy; t-stats are plain OLS for non-overlapping (weekly/monthly) returns, Newey-West (HAC) where noted.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
TAB = HERE / "tables"
TAB.mkdir(exist_ok=True)
OUT: dict = {}


# ── helpers ──────────────────────────────────────────────────────────────────
def ols(y: np.ndarray, X: np.ndarray, hac_lags: int = 0) -> dict:
    """OLS with intercept; returns betas, t-stats (OLS or Newey-West), R^2, n."""
    X1 = np.column_stack([np.ones(len(y)), X])
    beta, *_ = np.linalg.lstsq(X1, y, rcond=None)
    resid = y - X1 @ beta
    n, k = X1.shape
    xtx_inv = np.linalg.inv(X1.T @ X1)
    if hac_lags > 0:
        S = np.zeros((k, k))
        u = X1 * resid[:, None]
        S += u.T @ u
        for L in range(1, hac_lags + 1):
            w = 1 - L / (hac_lags + 1)
            G = u[L:].T @ u[:-L]
            S += w * (G + G.T)
        cov = xtx_inv @ S @ xtx_inv
    else:
        s2 = (resid @ resid) / (n - k)
        cov = s2 * xtx_inv
    se = np.sqrt(np.diag(cov))
    tss = ((y - y.mean()) ** 2).sum()
    r2 = 1 - (resid @ resid) / tss if tss > 0 else float("nan")
    return {"beta": beta.tolist(), "t": (beta / se).tolist(), "r2": float(r2), "n": int(n), "resid_last": float(resid[-1]),
            "resid_sd": float(resid.std(ddof=k))}


def load_fred(sid: str) -> pd.Series:
    df = pd.read_csv(DATA / f"fred_{sid}.csv", parse_dates=["date"])
    return df.set_index("date")[sid].astype(float).sort_index()


def load_yahoo(sym: str) -> pd.DataFrame:
    p = DATA / f"yahoo_{sym.replace('=', '_').replace('^', '_').replace('.', '_')}.csv"
    df = pd.read_csv(p, parse_dates=["date"]).set_index("date").sort_index()
    return df[~df.index.duplicated(keep="last")]


def gold_series() -> tuple[pd.Series, str]:
    """Daily gold in USD: LBMA PM fix (1968→) when verified, else COMEX GC=F close (2000→)."""
    p = DATA / "lbma_gold_pm.csv"
    if p.exists():
        df = pd.read_csv(p, parse_dates=["date"]).set_index("date").sort_index()
        s = df["v0"].astype(float)
        s = s[s > 0]
        return s, "LBMA gold PM (USD/oz)"
    g = load_yahoo("GC=F")["close"].astype(float)
    return g[g > 0], "COMEX GC=F front close (USD/oz)"


def periods() -> list[tuple[str, str, str]]:
    return [("2003-2009", "2003-01-01", "2009-12-31"), ("2010-2021", "2010-01-01", "2021-12-31"),
            ("2022-2026", "2022-01-01", "2026-12-31"), ("2010-2026", "2010-01-01", "2026-12-31")]


# ── 1. gold vs real yields and DXY: levels and changes ───────────────────────
def study_regressions() -> None:
    gold, gold_src = gold_series()
    dfii = load_fred("DFII10")
    dxy = load_yahoo("DX-Y.NYB")["close"].astype(float)
    dgs10 = load_fred("DGS10")
    bei = load_fred("T10YIE")
    vix = load_fred("VIXCLS")
    daily = pd.concat({"gold": gold, "dfii10": dfii, "dxy": dxy, "dgs10": dgs10, "bei": bei, "vix": vix}, axis=1).sort_index()
    daily = daily[daily.index >= "2003-01-02"]
    daily = daily.ffill(limit=3).dropna(subset=["gold", "dfii10", "dxy"])
    daily["lg"] = np.log(daily["gold"])
    daily["ldxy"] = np.log(daily["dxy"])
    OUT["data"] = {"gold_source": gold_src, "daily_rows": int(len(daily)), "first": str(daily.index[0].date()),
                   "last": str(daily.index[-1].date())}

    levels = []
    for name, a, b in periods():
        d = daily.loc[a:b]
        if len(d) < 200:
            continue
        r = ols(d["lg"].values, d[["dfii10"]].values, hac_lags=60)
        r2 = ols(d["lg"].values, d[["ldxy"]].values, hac_lags=60)
        r3 = ols(d["lg"].values, d[["dfii10", "ldxy"]].values, hac_lags=60)
        levels.append({"period": name, "n": r["n"],
                       "ry_beta_pct_per_100bp": round(100 * r["beta"][1], 1), "ry_t_hac": round(r["t"][1], 2), "ry_r2": round(r["r2"], 3),
                       "dxy_beta_elasticity": round(r2["beta"][1], 2), "dxy_t_hac": round(r2["t"][1], 2), "dxy_r2": round(r2["r2"], 3),
                       "both_r2": round(r3["r2"], 3), "both_ry_beta": round(100 * r3["beta"][1], 1), "both_dxy_beta": round(r3["beta"][2], 2)})
    pd.DataFrame(levels).to_csv(TAB / "levels_by_period.csv", index=False)
    OUT["levels"] = levels

    # change regressions at weekly (Fri) and monthly (month-end) horizons: non-overlapping -> plain OLS t
    changes = []
    for freq, lab in (("W-FRI", "weekly"), ("ME", "monthly")):
        res = daily[["lg", "dfii10", "ldxy", "dgs10", "bei", "vix"]].resample(freq).last().dropna(subset=["lg", "dfii10", "ldxy"])
        ch = res.diff().dropna(subset=["lg", "dfii10", "ldxy"])
        for name, a, b in periods():
            c = ch.loc[a:b]
            if len(c) < 30:
                continue
            r = ols(c["lg"].values, c[["dfii10"]].values)
            r2 = ols(c["lg"].values, c[["ldxy"]].values)
            both = ols(c["lg"].values, c[["dfii10", "ldxy"]].values)
            cc = c.dropna(subset=["dgs10", "bei"])
            dec = ols(cc["lg"].values, cc[["dgs10", "bei"]].values)        # nominal vs breakeven split
            changes.append({"horizon": lab, "period": name, "n": r["n"],
                            "ry_beta_pct_per_100bp": round(100 * r["beta"][1], 1), "ry_t": round(r["t"][1], 2), "ry_r2": round(r["r2"], 3),
                            "ry_corr": round(float(np.corrcoef(c["lg"], c["dfii10"])[0, 1]), 3),
                            "dxy_beta": round(r2["beta"][1], 2), "dxy_t": round(r2["t"][1], 2), "dxy_r2": round(r2["r2"], 3),
                            "dxy_corr": round(float(np.corrcoef(c["lg"], c["ldxy"])[0, 1]), 3),
                            "both_r2": round(both["r2"], 3), "both_ry_beta": round(100 * both["beta"][1], 1), "both_ry_t": round(both["t"][1], 2),
                            "both_dxy_beta": round(both["beta"][2], 2), "both_dxy_t": round(both["t"][2], 2),
                            "nominal10y_beta": round(100 * dec["beta"][1], 1), "nominal10y_t": round(dec["t"][1], 2),
                            "breakeven_beta": round(100 * dec["beta"][2], 1), "breakeven_t": round(dec["t"][2], 2), "nom_bei_r2": round(dec["r2"], 3)})
    pd.DataFrame(changes).to_csv(TAB / "changes_by_period.csv", index=False)
    OUT["changes"] = changes

    # rolling 1-year correlation of daily changes (for the chart/story)
    dch = daily[["lg", "dfii10", "ldxy"]].diff().dropna()
    roll = pd.DataFrame({"corr_gold_realyield": dch["lg"].rolling(252).corr(dch["dfii10"]),
                         "corr_gold_dxy": dch["lg"].rolling(252).corr(dch["ldxy"])}).dropna()
    yearly = roll.resample("YE").last().round(3)
    yearly.index = yearly.index.year
    yearly.to_csv(TAB / "rolling_corr_yearend.csv")
    OUT["rolling_corr_yearend"] = {str(k): v for k, v in yearly.to_dict("index").items()}

    # mispricing gauge: fit 2010-2021 levels on DFII10 + lnDXY, apply to today
    fit = daily.loc["2010-01-01":"2021-12-31"]
    r = ols(fit["lg"].values, fit[["dfii10", "ldxy"]].values, hac_lags=60)
    b = np.array(r["beta"])
    daily["fv_2010_21"] = np.exp(b[0] + b[1] * daily["dfii10"] + b[2] * daily["ldxy"])
    daily["resid_pct"] = 100 * (daily["gold"] / daily["fv_2010_21"] - 1)
    today = daily.iloc[-1]
    OUT["mispricing_gauge"] = {
        "fit_window": "2010-2021", "model": "ln(gold) = a + b1*DFII10 + b2*ln(DXY)", "a": round(b[0], 4),
        "b1_pct_per_100bp": round(100 * b[1], 1), "b2_dxy_elasticity": round(b[2], 2), "r2_in_window": round(r["r2"], 3),
        "as_of": str(daily.index[-1].date()), "gold": round(float(today["gold"]), 1), "dfii10": float(today["dfii10"]),
        "dxy": round(float(today["dxy"]), 2), "fair_value_2010_21_model": round(float(today["fv_2010_21"]), 0),
        "residual_pct": round(float(today["resid_pct"]), 1),
        "residual_pct_at_year_end": {str(k.year): round(float(v), 1) for k, v in daily["resid_pct"].resample("YE").last().items()},
    }
    # regime-aware gauge: the same model re-fitted on the trailing 3 years (756 sessions), residual today in SDs
    tail = daily.iloc[-756:]
    rt = ols(tail["lg"].values, tail[["dfii10", "ldxy"]].values, hac_lags=60)
    bt = np.array(rt["beta"])
    fv_t = float(np.exp(bt[0] + bt[1] * today["dfii10"] + bt[2] * today["ldxy"]))
    OUT["mispricing_gauge_trailing_3y"] = {
        "fit_window": f"{tail.index[0].date()}..{tail.index[-1].date()}", "b1_pct_per_100bp": round(100 * bt[1], 1),
        "b1_t_hac": round(rt["t"][1], 2), "b2_dxy_elasticity": round(bt[2], 2), "b2_t_hac": round(rt["t"][2], 2), "r2": round(rt["r2"], 3),
        "fair_value": round(fv_t, 0), "residual_pct": round(100 * (float(today["gold"]) / fv_t - 1), 1),
        "residual_in_sd": round(rt["resid_last"] / rt["resid_sd"], 2), "resid_sd_pct": round(100 * rt["resid_sd"], 1)}
    # 2022-2026 level fit on its own (how the relation looks inside the new regime)
    new = daily.loc["2022-01-01":]
    rn = ols(new["lg"].values, new[["dfii10", "ldxy"]].values, hac_lags=60)
    OUT["levels_2022_2026_both"] = {"n": rn["n"], "b1_pct_per_100bp": round(100 * rn["beta"][1], 1), "b1_t_hac": round(rn["t"][1], 2),
                                    "b2_dxy": round(rn["beta"][2], 2), "b2_t_hac": round(rn["t"][2], 2), "r2": round(rn["r2"], 3)}
    # H5: does the residual sign predict the next 63-session return out of sample (2022-2026)?
    oos = daily.loc["2022-01-01":].copy()
    oos["fwd63"] = oos["lg"].shift(-63) - oos["lg"]
    m = oos.resample("ME").last().dropna(subset=["fwd63", "resid_pct"])
    if len(m) > 12:
        h5 = ols(m["fwd63"].values * 100, m[["resid_pct"]].values, hac_lags=3)
        OUT["H5_residual_predicts_fwd3m_oos"] = {"n_months": h5["n"], "beta_pct_fwd_per_1pct_resid": round(h5["beta"][1], 3),
                                                 "t_hac": round(h5["t"][1], 2), "r2": round(h5["r2"], 3)}
    daily[["gold", "dfii10", "dxy", "fv_2010_21", "resid_pct"]].resample("ME").last().round(2).to_csv(TAB / "mispricing_monthly.csv")


# ── 2. seasonality ───────────────────────────────────────────────────────────
def long_monthly_gold() -> tuple[pd.Series, str]:
    """Monthly gold back to 1971 (post Bretton Woods): World Bank CMO monthly averages (1960→2024, as served today)
    spliced with COMEX GC=F month-end closes from 2025 on. Averages vs month-ends differ slightly; both are
    'a price per month' and the splice is only used for month-of-year statistics."""
    wb = pd.read_csv(DATA / "worldbank_cmo_monthly.csv", parse_dates=["date"]).set_index("date")["gold"].astype(float)
    wb = wb.loc["1971-01-01":]
    gc = load_yahoo("GC=F")["close"].astype(float).resample("ME").last()
    gc = gc[gc.index > wb.index[-1]]
    return pd.concat([wb, gc]), f"World Bank CMO monthly avg 1971→{wb.index[-1].date()} + GC=F month-end after"


def study_seasonality() -> None:
    gold, src = long_monthly_gold()
    m = gold
    ret = 100 * np.log(m).diff().dropna()
    df = pd.DataFrame({"ret": ret})
    df["month"] = df.index.month
    df["year"] = df.index.year
    rows = []
    for mo in range(1, 13):
        x = df[df["month"] == mo]["ret"]
        halves = []
        for a, b in ((1971, 2000), (2001, 2026)):
            h = df[(df["month"] == mo) & (df["year"] >= a) & (df["year"] <= b)]["ret"]
            halves.append({"years": f"{a}-{b}", "mean": round(h.mean(), 2), "t": round(h.mean() / (h.std(ddof=1) / math.sqrt(len(h))), 2) if len(h) > 2 else None,
                           "hit": round(100 * (h > 0).mean(), 0), "n": int(len(h))})
        rows.append({"month": mo, "mean_pct": round(x.mean(), 2), "median_pct": round(x.median(), 2), "hit_rate_pct": round(100 * (x > 0).mean(), 0),
                     "t": round(x.mean() / (x.std(ddof=1) / math.sqrt(len(x))), 2), "n": int(len(x)),
                     "h1": halves[0], "h2": halves[1]})
    pd.json_normalize(rows).to_csv(TAB / "seasonality_month_of_year.csv", index=False)
    # Festival windows in calendar terms (approximate, the dates move): Diwali season = 1 Sep -> Diwali (Oct/Nov);
    # Chinese New Year run-up = 1 Dec -> 31 Jan; Western year-end = Dec.
    OUT["seasonality"] = {"source": src, "first_year": int(df["year"].min()), "last_year": int(df["year"].max()), "months": rows,
                          "note": "monthly log returns, all available years; halves 1971-2000 / 2001-2026; no month is declared PASS unless t>=2 in both halves"}
    # cross-check on month-end COMEX closes only (2001-2026), which have no averaging artefact
    gc = 100 * np.log(load_yahoo("GC=F")["close"].astype(float).resample("ME").last()).diff().dropna()
    gcd = pd.DataFrame({"ret": gc}); gcd["month"] = gcd.index.month
    OUT["seasonality_gcf_2001_2026"] = [{"month": mo, "mean_pct": round(float(gcd[gcd.month == mo]["ret"].mean()), 2),
                                         "hit_rate_pct": round(100 * float((gcd[gcd.month == mo]["ret"] > 0).mean()), 0),
                                         "t": round(float(gcd[gcd.month == mo]["ret"].mean() / (gcd[gcd.month == mo]["ret"].std(ddof=1) / math.sqrt(len(gcd[gcd.month == mo])))), 2),
                                         "n": int(len(gcd[gcd.month == mo]))} for mo in range(1, 13)]
    both = [r["month"] for r in rows if r["h1"]["t"] is not None and r["h2"]["t"] is not None and r["h1"]["t"] >= 2 and r["h2"]["t"] >= 2]
    OUT["H3_months_passing_both_halves"] = both


# ── 3. GPR ───────────────────────────────────────────────────────────────────
def study_gpr() -> None:
    p = DATA / "gpr_monthly.csv"
    if not p.exists():
        OUT["gpr"] = {"status": "GPR file not verified"}
        return
    g = pd.read_csv(p)
    dcol = next((c for c in g.columns if str(c).lower() in ("month", "date")), g.columns[0])
    g[dcol] = pd.to_datetime(g[dcol], errors="coerce")
    col = "GPR" if "GPR" in g.columns else next(c for c in g.columns if str(c).upper().startswith("GPR"))
    gpr = g.set_index(dcol)[col].astype(float).dropna()
    gpr.index = gpr.index + pd.offsets.MonthEnd(0)
    m, _ = long_monthly_gold()
    ret = 100 * np.log(m).diff()
    df = pd.concat({"ret": ret, "gpr": gpr, "dlgpr": np.log(gpr).diff()}, axis=1).dropna()
    df = df.loc["1985-01-01":]
    df["fwd"] = df["ret"].shift(-1)
    contemp = ols(df["ret"].values, df[["dlgpr"]].values)
    pred = df.dropna(subset=["fwd"])
    predictive = ols(pred["fwd"].values, pred[["dlgpr"]].values)
    lvl = ols(pred["fwd"].values, np.log(pred[["gpr"]].values))
    hi = df[df["gpr"] >= df["gpr"].quantile(0.9)]
    OUT["gpr"] = {"gpr_column": col, "n_months": int(len(df)), "first": str(df.index[0].date()), "last": str(df.index[-1].date()),
                  "latest_gpr": round(float(gpr.iloc[-1]), 1), "latest_gpr_percentile_since_1985": round(100 * float((gpr.loc['1985':] <= gpr.iloc[-1]).mean()), 0),
                  "contemporaneous": {"beta_pct_per_100pct_gpr_change": round(contemp["beta"][1], 2), "t": round(contemp["t"][1], 2), "r2": round(contemp["r2"], 3)},
                  "predictive_next_month": {"beta": round(predictive["beta"][1], 2), "t": round(predictive["t"][1], 2), "r2": round(predictive["r2"], 3)},
                  "level_predicts_next_month": {"beta_per_log_gpr": round(lvl["beta"][1], 2), "t": round(lvl["t"][1], 2)},
                  "mean_ret_when_gpr_top_decile": round(float(hi["ret"].mean()), 2), "mean_ret_all": round(float(df["ret"].mean()), 2),
                  "mean_next_month_ret_after_top_decile": round(float(hi["fwd"].mean()), 2)}


# ── 4. descriptive: KGX decomposition, gold in currencies, ratios, GVZ, gold/M2 ──
def study_descriptive() -> None:
    gc = load_yahoo("GC=F")["close"].astype(float)
    fx = {}
    for sym, inv in (("EURUSD=X", False), ("JPY=X", True), ("GBPUSD=X", False), ("CAD=X", True), ("SEK=X", True), ("CHF=X", True),
                     ("INR=X", True), ("CNY=X", True)):
        s = load_yahoo(sym)["close"].astype(float)
        fx[sym] = (1 / s) if inv else s            # all as USD per 1 unit of foreign currency
    panel = pd.concat({"gold": gc, **fx}, axis=1).ffill(limit=3).dropna()
    # DXY weights: EUR 57.6, JPY 13.6, GBP 11.9, CAD 9.1, SEK 4.2, CHF 3.6 (ICE)
    w = {"EURUSD=X": 0.576, "JPY=X": 0.136, "GBPUSD=X": 0.119, "CAD=X": 0.091, "SEK=X": 0.042, "CHF=X": 0.036}
    lr = np.log(panel).diff()
    basket_usd_move = -sum(w[k] * lr[k] for k in w)          # + = USD strengthened vs the basket (geometric, DXY-weighted)
    gold_usd = lr["gold"]
    pure_gold = gold_usd + basket_usd_move                   # gold measured in the basket currency
    kgx = pd.DataFrame({"gold_usd_pct": 100 * gold_usd, "usd_vs_basket_pct": 100 * basket_usd_move,
                        "usd_effect_on_gold_pct": -100 * basket_usd_move, "pure_gold_pct": 100 * pure_gold}).dropna()
    kgx.tail(10).round(2).to_csv(TAB / "kgx_decomposition_last10.csv")
    OUT["kgx_last_sessions"] = {str(k.date()): {c: round(v, 2) for c, v in r.items()} for k, r in kgx.tail(5).iterrows()}
    # YTD / 1y gold in currencies
    cur = {}
    for sym, name in (("EURUSD=X", "EUR"), ("JPY=X", "JPY"), ("GBPUSD=X", "GBP"), ("CNY=X", "CNY"), ("INR=X", "INR")):
        gl = panel["gold"] / panel[sym]
        y0 = gl[gl.index < pd.Timestamp("2026-01-01")].iloc[-1]
        y1 = gl[gl.index <= gl.index[-1] - pd.Timedelta(days=365)].iloc[-1]
        cur[name] = {"level": round(float(gl.iloc[-1]), 1), "ytd_pct": round(100 * (gl.iloc[-1] / y0 - 1), 1), "1y_pct": round(100 * (gl.iloc[-1] / y1 - 1), 1)}
    g = panel["gold"]
    cur["USD"] = {"level": round(float(g.iloc[-1]), 1), "ytd_pct": round(100 * (g.iloc[-1] / g[g.index < pd.Timestamp('2026-01-01')].iloc[-1] - 1), 1),
                  "1y_pct": round(100 * (g.iloc[-1] / g[g.index <= g.index[-1] - pd.Timedelta(days=365)].iloc[-1] - 1), 1)}
    OUT["gold_in_currencies"] = {"as_of": str(panel.index[-1].date()), **cur, "inr_per_10g_landed_no_duty": round(float(g.iloc[-1] / panel["INR=X"].iloc[-1] * 10 / 31.1034768), 0)}
    # ratios
    si = load_yahoo("SI=F")["close"].astype(float)
    pl = load_yahoo("PL=F")["close"].astype(float)
    r = pd.concat({"gs": gc / si, "gp": gc / pl}, axis=1).dropna()
    OUT["ratios"] = {"as_of": str(r.index[-1].date()),
                     "gold_silver": {"now": round(float(r["gs"].iloc[-1]), 1), "median_since_2000": round(float(r["gs"].median()), 1),
                                     "percentile": round(100 * float((r["gs"] <= r["gs"].iloc[-1]).mean()), 0), "min": round(float(r["gs"].min()), 1), "max": round(float(r["gs"].max()), 1)},
                     "gold_platinum": {"now": round(float(r["gp"].iloc[-1]), 2), "median_since_2000": round(float(r["gp"].median()), 2),
                                       "percentile": round(100 * float((r["gp"] <= r["gp"].iloc[-1]).mean()), 0)}}
    # GVZ expected move
    try:
        gvz = load_fred("GVZCLS").dropna()
        g_now = float(gc.iloc[-1])
        inr = float(load_yahoo("INR=X")["close"].iloc[-1])
        daily_sd_pct = float(gvz.iloc[-1]) / math.sqrt(252)
        mcx_approx = g_now * inr * 10 / 31.1034768
        OUT["gvz"] = {"as_of": str(gvz.index[-1].date()), "gvz": float(gvz.iloc[-1]), "percentile_since_2008": round(100 * float((gvz <= gvz.iloc[-1]).mean()), 0),
                      "implied_1day_1sd_pct": round(daily_sd_pct, 2), "implied_1day_1sd_usd": round(g_now * daily_sd_pct / 100, 1),
                      "implied_1day_1sd_inr_per_10g_landed": round(mcx_approx * daily_sd_pct / 100, 0),
                      "implied_1day_1sd_rupees_per_1kg_lot": round(mcx_approx * daily_sd_pct / 100 * 100, 0),
                      "realised_20d_vol_pct": round(float(100 * np.log(gc).diff().tail(20).std() * math.sqrt(252)), 1)}
    except Exception as exc:  # noqa: BLE001
        OUT["gvz"] = {"status": f"unavailable: {exc}"}
    # gold / M2
    try:
        m2 = load_fred("M2SL")
        gm = gold_series()[0].resample("ME").last()
        ratio = (gm / (m2.resample("ME").last().ffill())).dropna()
        ratio = ratio.loc["1975":]
        OUT["gold_m2"] = {"as_of": str(ratio.index[-1].date()), "gold_per_bn_m2": round(float(ratio.iloc[-1]), 4),
                          "percentile_since_1975": round(100 * float((ratio <= ratio.iloc[-1]).mean()), 0),
                          "m2_latest": str(m2.index[-1].date()), "note": "gold($/oz) / M2($bn); a popular 'monetary debasement' chart; context only"}
    except Exception as exc:  # noqa: BLE001
        OUT["gold_m2"] = {"status": f"unavailable: {exc}"}
    # fed funds futures implied rate
    try:
        zq = load_yahoo("ZQ=F")["close"].astype(float)
        dff = load_fred("DFF")
        OUT["fed_funds_futures"] = {"as_of": str(zq.index[-1].date()), "zq_front_price": round(float(zq.iloc[-1]), 3),
                                    "implied_rate_pct": round(100 - float(zq.iloc[-1]), 3), "effr_latest": float(dff.iloc[-1]), "effr_date": str(dff.index[-1].date())}
    except Exception as exc:  # noqa: BLE001
        OUT["fed_funds_futures"] = {"status": f"unavailable: {exc}"}
    # intraday real-yield proxy check: corr of daily changes DGS10 - T10YIE vs DFII10
    try:
        d = pd.concat({"dfii": load_fred("DFII10"), "dgs": load_fred("DGS10"), "bei": load_fred("T10YIE")}, axis=1).dropna().loc["2010":]
        proxy = (d["dgs"] - d["bei"])
        dd = pd.DataFrame({"a": d["dfii"].diff(), "b": proxy.diff()}).dropna()
        OUT["real_yield_proxy"] = {"corr_daily_change_dfii10_vs_dgs10_minus_t10yie": round(float(dd["a"].corr(dd["b"])), 3),
                                   "mean_abs_gap_bp": round(float(100 * (d["dfii"] - proxy).abs().mean()), 1),
                                   "note": "intraday: ^TNX (live) minus the last T10YIE approximates the real yield when breakevens are quiet"}
    except Exception as exc:  # noqa: BLE001
        OUT["real_yield_proxy"] = {"status": f"unavailable: {exc}"}


if __name__ == "__main__":
    for fn in (study_regressions, study_seasonality, study_gpr, study_descriptive):
        try:
            fn()
            print("ok", fn.__name__)
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            OUT[fn.__name__] = {"error": str(exc)}
    (HERE / "study.json").write_text(json.dumps(OUT, indent=1, default=str), encoding="utf-8")
    print(json.dumps(OUT, indent=1, default=str)[:6000])

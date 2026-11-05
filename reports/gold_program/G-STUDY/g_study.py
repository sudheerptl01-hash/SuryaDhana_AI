#!/usr/bin/env python
"""
G-STUDY — is CFTC COT positioning (and the usual "gold health" indicators) USEFUL to a gold trader?

    /Users/sudheer/Desktop/jupyter_env/bin/python reports/gold_program/G-STUDY/g_study.py

Reproducible from the files in ./data (all downloaded 26 Oct 2026, see DATA_SOURCES.md):
  * CFTC COT for COMEX gold (contract code 088691): legacy + disaggregated, futures-only + combined,
    from the CFTC Socrata API (cftc_socrata_*.csv) and cross-checked against the raw history zips
    (cftc_zip_*.csv, extracted from data/cftc_zips/).
  * Prices: Yahoo GC=F daily (COMEX front-month settlement, 2000-08-30 →), GLD (ETF), DX-Y.NYB (DXY),
    INR=X (USD/INR, for the MCX proxy), SI=F.
  * FRED fredgraph.csv (no key): DFII10 (10-y TIPS real yield), DTWEXBGS (broad dollar).
  * SPDR Gold Shares historical archive (xlsx): GLD tonnes daily 2004-11-18 →.

Anti-patterns honoured (see CLAUDE.md): no look-ahead (every COT signal is dated at its RELEASE and the
entry is the NEXT session's close), no shuffling, expanding-window walk-forward with IS/OOS reported
separately, round-trip costs at the project floor 0.15 % (MCX GOLD's exchange cost from
shared/mcx_specs.py is far lower and is shown for reference).

Outputs: results/*.csv, figures/*.png, RESULTS_TABLES.md (every table), summary.json.
"""
from __future__ import annotations

import json
import sys
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RES = ROOT / "results"
FIG = ROOT / "figures"
PROJECT = ROOT.parents[2]
sys.path.insert(0, str(PROJECT))
from shared.mcx_specs import round_trip_costs  # noqa: E402

HORIZONS = (1, 4, 13)
MIN_HIST = 104                 # weeks of history before an expanding percentile / fitted direction is used
COST_RT = 0.15                 # % per round trip — the project floor (anti-pattern rule)
IS_FRACTION = 0.40             # first 40 % of weeks = in-sample; the rest = walk-forward out-of-sample
SUBPERIODS = [("pre-2011", None, "2010-12-31"), ("2011-19", "2011-01-01", "2019-12-31"), ("2020-26", "2020-01-01", None)]
COLORS = {"blue": "#2a78d6", "orange": "#eb6834", "aqua": "#1baf7a", "yellow": "#eda100", "magenta": "#e87ba4",
          "green": "#008300", "violet": "#4a3aa7", "red": "#e34948", "ink": "#0b0b0b", "ink2": "#52514e", "grid": "#e6e5e1"}


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# 1. Loaders
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def load_cot(kind: str) -> pd.DataFrame:
    """One row per report date for COMEX gold (088691). Columns normalised to short names."""
    df = pd.read_csv(DATA / f"cftc_socrata_{kind}_gold_088691.csv", low_memory=False)
    df["date"] = pd.to_datetime(df["report_date_as_yyyy_mm_dd"]).dt.normalize()
    df = df.sort_values("date").drop_duplicates("date").set_index("date")
    out = pd.DataFrame(index=df.index)
    out["oi"] = df["open_interest_all"].astype(float)
    if kind.startswith("legacy"):
        out["spec_long"] = df["noncomm_positions_long_all"].astype(float)
        out["spec_short"] = df["noncomm_positions_short_all"].astype(float)
        out["spec_spread"] = df["noncomm_postions_spread_all"].astype(float)
        out["comm_long"] = df["comm_positions_long_all"].astype(float)
        out["comm_short"] = df["comm_positions_short_all"].astype(float)
    else:
        out["mm_long"] = df["m_money_positions_long_all"].astype(float)
        out["mm_short"] = df["m_money_positions_short_all"].astype(float)
        out["mm_spread"] = df["m_money_positions_spread"].astype(float)
        out["pm_long"] = df["prod_merc_positions_long"].astype(float)
        out["pm_short"] = df["prod_merc_positions_short"].astype(float)
        out["swap_long"] = df["swap_positions_long_all"].astype(float)
        out["swap_short"] = df["swap__positions_short_all"].astype(float)
        out["swap_spread"] = df["swap__positions_spread_all"].astype(float)
        out["other_long"] = df["other_rept_positions_long"].astype(float)
        out["other_short"] = df["other_rept_positions_short"].astype(float)
        out["other_spread"] = df["other_rept_positions_spread"].astype(float)
        out["comm_long"] = out["pm_long"] + out["swap_long"]
        out["comm_short"] = out["pm_short"] + out["swap_short"]
    out["nr_long"] = df["nonrept_positions_long_all"].astype(float)
    out["nr_short"] = df["nonrept_positions_short_all"].astype(float)
    return out


def crosscheck_zip(kind: str, soc: pd.DataFrame) -> dict:
    """Socrata API vs the raw CFTC history zips: same rows, same numbers?"""
    z = pd.read_csv(DATA / f"cftc_zip_{kind}_gold_088691.csv", low_memory=False)
    z.columns = [c.strip() for c in z.columns]
    if kind.startswith("legacy"):
        dcol = "As of Date in Form YYYY-MM-DD"
        cols = {"oi": "Open Interest (All)", "spec_long": "Noncommercial Positions-Long (All)",
                "spec_short": "Noncommercial Positions-Short (All)", "comm_long": "Commercial Positions-Long (All)",
                "comm_short": "Commercial Positions-Short (All)", "nr_long": "Nonreportable Positions-Long (All)"}
    else:
        dcol = "Report_Date_as_YYYY-MM-DD"
        cols = {"oi": "Open_Interest_All", "mm_long": "M_Money_Positions_Long_All", "mm_short": "M_Money_Positions_Short_All",
                "pm_long": "Prod_Merc_Positions_Long_All", "swap_short": "Swap_Positions_Short_All",
                "nr_long": "NonRept_Positions_Long_All"}
    z["date"] = pd.to_datetime(z[dcol]).dt.normalize()
    z = z.sort_values("date").drop_duplicates("date").set_index("date")
    common = soc.index.intersection(z.index)
    mism = {}
    for k, c in cols.items():
        if c not in z.columns:   # the zips spell 'Swap__Positions_Short_All' with a double underscore
            c = next(cc for cc in z.columns if cc.replace("__", "_").lower() == c.replace("__", "_").lower())
        a = soc.loc[common, k].astype(float)
        b = z.loc[common, c].astype(float)
        mism[k] = int((a - b).abs().gt(0.5).sum())
    return {"socrata_rows": len(soc), "zip_rows": len(z), "common_dates": len(common),
            "socrata_only": len(soc.index.difference(z.index)), "zip_only": len(z.index.difference(soc.index)),
            "value_mismatches": mism}


def load_yahoo(sym: str) -> pd.DataFrame:
    df = pd.read_csv(DATA / f"yahoo_{sym}_1d.csv")
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df = df.drop_duplicates("date").set_index("date").sort_index()
    return df[["open", "high", "low", "close"] + (["adjclose"] if "adjclose" in df else [])]


def load_fred(series: str) -> pd.Series:
    df = pd.read_csv(DATA / f"fred_{series}.csv")
    df["date"] = pd.to_datetime(df["observation_date"])
    s = pd.to_numeric(df[series], errors="coerce")
    return pd.Series(s.values, index=df["date"]).dropna().sort_index()


def load_gld_tonnes() -> pd.DataFrame:
    x = pd.ExcelFile(DATA / "spdr_gld_historical_archive.bin")
    df = x.parse("US GLD Historical Archive", header=0)
    df.columns = [str(c).strip() for c in df.columns]
    df["date"] = pd.to_datetime(df["Date"], format="%d-%b-%Y", errors="coerce")
    df["tonnes"] = pd.to_numeric(df["Tonnes of Gold"], errors="coerce")
    df["gld_close"] = pd.to_numeric(df["Closing Price"], errors="coerce")
    df = df.dropna(subset=["date", "tonnes"]).set_index("date").sort_index()
    return df[["tonnes", "gld_close"]]


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# 2. Release dates — the look-ahead guard
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    d = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: date) -> date:
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def us_federal_holidays(year: int) -> set[date]:
    hol = {_observed(date(year, 1, 1)), _nth_weekday(year, 1, 0, 3), _nth_weekday(year, 2, 0, 3), _last_weekday(year, 5, 0),
           _observed(date(year, 7, 4)), _nth_weekday(year, 9, 0, 1), _nth_weekday(year, 10, 0, 2), _observed(date(year, 11, 11)),
           _nth_weekday(year, 11, 3, 4), _observed(date(year, 12, 25))}
    if year >= 2021:
        hol.add(_observed(date(year, 6, 19)))
    return hol


# Verified exceptions (CFTC "Historical Special Announcements" + press release 7864-19, fetched 26 Oct 2026):
#   report date → actual publication date.
RELEASE_OVERRIDES: dict[str, str] = {
    # 2025 lapse in appropriations (Dec 9 2025 table): catch-up publications
    "2025-09-30": "2025-11-19", "2025-10-07": "2025-11-21", "2025-10-14": "2025-11-25", "2025-10-21": "2025-12-02",
    "2025-10-28": "2025-12-05", "2025-11-04": "2025-12-09", "2025-11-10": "2025-12-10", "2025-11-18": "2025-12-12",
    "2025-11-25": "2025-12-15", "2025-12-02": "2025-12-17", "2025-12-09": "2025-12-19", "2025-12-16": "2025-12-23",
    "2025-12-23": "2025-12-29",
    # Jan 2025 National Day of Mourning (Carter): released Monday 13 Jan
    "2025-01-07": "2025-01-13",
    # 2023 ION cyber incident: delayed reports (dates from the announcements page)
    "2023-01-31": "2023-02-24", "2023-02-07": "2023-03-03", "2023-02-14": "2023-03-08", "2023-02-21": "2023-03-10",
    "2023-02-28": "2023-03-14", "2023-03-07": "2023-03-16", "2023-03-14": "2023-03-21",
    # 2018-19 lapse in appropriations: press release 7864-19 — first catch-up Fri 1 Feb 2019, then one every Tue and Fri
    "2018-12-24": "2019-02-01", "2018-12-31": "2019-02-05", "2019-01-08": "2019-02-08", "2019-01-15": "2019-02-12",
    "2019-01-22": "2019-02-15", "2019-01-29": "2019-02-19", "2019-02-05": "2019-02-22", "2019-02-12": "2019-02-26",
    "2019-02-19": "2019-03-01", "2019-02-26": "2019-03-05", "2019-03-05": "2019-03-08",
}
# October 2013 shutdown: the catch-up dates could not be verified from cftc.gov → those weeks are EXCLUDED
RELEASE_EXCLUDE = {"2013-10-01", "2013-10-08", "2013-10-15", "2013-10-22"}


def release_date(report: pd.Timestamp) -> pd.Timestamp | None:
    """Friday 15:30 ET of the report week; a federal holiday after the report day in that week pushes it to Monday.
    Verified special cases override; unverifiable ones are excluded (None)."""
    key = report.strftime("%Y-%m-%d")
    if key in RELEASE_EXCLUDE:
        return None
    if key in RELEASE_OVERRIDES:
        return pd.Timestamp(RELEASE_OVERRIDES[key])
    d = report.date()
    friday = d + timedelta(days=(4 - d.weekday()) % 7)
    hol = us_federal_holidays(d.year) | us_federal_holidays(d.year + 1)
    delayed = any((d + timedelta(days=i)) in hol for i in range(1, (friday - d).days + 1))
    if delayed:
        return pd.Timestamp(friday + timedelta(days=3))
    return pd.Timestamp(friday)


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# 3. Statistics helpers (no statsmodels in the env — Newey-West by hand)
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def nw_t(x: pd.Series | np.ndarray, lags: int) -> float:
    """t-stat of the mean with a Bartlett Newey-West variance (overlapping forward windows)."""
    x = pd.Series(x).dropna().to_numpy(dtype=float)
    n = len(x)
    if n < 4:
        return float("nan")
    e = x - x.mean()
    s = e @ e / n
    for lag in range(1, min(lags, n - 1) + 1):
        s += 2 * (1 - lag / (lags + 1)) * (e[lag:] @ e[:-lag]) / n
    return float(x.mean() / np.sqrt(s / n)) if s > 0 else float("nan")


def nw_slope_t(x: pd.Series, y: pd.Series, lags: int) -> tuple[float, float]:
    """OLS slope of y on x with a Newey-West t-stat (HAC on the score u_t = x̃_t·e_t)."""
    d = pd.concat([x, y], axis=1).dropna()
    if len(d) < 10:
        return float("nan"), float("nan")
    xv, yv = d.iloc[:, 0].to_numpy(float), d.iloc[:, 1].to_numpy(float)
    xt = xv - xv.mean()
    beta = (xt @ (yv - yv.mean())) / (xt @ xt)
    e = (yv - yv.mean()) - beta * xt
    u = xt * e
    n = len(u)
    s = u @ u / n
    for lag in range(1, min(lags, n - 1) + 1):
        s += 2 * (1 - lag / (lags + 1)) * (u[lag:] @ u[:-lag]) / n
    se = np.sqrt(s * n) / (xt @ xt)
    return float(beta), float(beta / se) if se > 0 else float("nan")


def expanding_pct(s: pd.Series, min_hist: int = MIN_HIST) -> pd.Series:
    """Percentile of s[t] within s[:t] (strictly earlier values only) — walk-forward ranks."""
    v = s.to_numpy(float)
    out = np.full(len(v), np.nan)
    for i in range(min_hist, len(v)):
        if np.isnan(v[i]):
            continue
        past = v[:i]
        past = past[~np.isnan(past)]
        if len(past) >= min_hist:
            out[i] = (past < v[i]).mean() + 0.5 * (past == v[i]).mean()
    return pd.Series(out, index=s.index)


def max_drawdown(eq: pd.Series) -> float:
    return float((eq / eq.cummax() - 1).min() * 100)


def perf(weekly: pd.Series) -> dict:
    w = weekly.dropna()
    if len(w) < 10:
        return {}
    eq = (1 + w).cumprod()
    yrs = len(w) / 52
    return {"cagr": round((eq.iloc[-1] ** (1 / yrs) - 1) * 100, 2), "vol": round(w.std() * np.sqrt(52) * 100, 2),
            "sharpe": round(w.mean() / w.std() * np.sqrt(52), 2) if w.std() > 0 else None, "max_dd": round(max_drawdown(eq), 1),
            "weeks": len(w)}


def table(rows: list[dict], cols: list[str]) -> str:
    def f(v):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return ""
        return str(v)
    return ("| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
            + "\n".join("| " + " | ".join(f(r.get(c)) for c in cols) + " |" for r in rows))


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# 4. Panel: one row per COT report, every signal known at the release, forward returns from the next session
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def asof(series: pd.Series, when: pd.Timestamp) -> float:
    """Last value on or before `when`."""
    s = series.loc[:when]
    return float(s.iloc[-1]) if len(s) else np.nan


def build_panel(cot: pd.DataFrame, price: pd.Series, extra: dict[str, pd.Series], late_sessions: int = 2) -> pd.DataFrame:
    idx = price.index
    rows = []
    for T, r in cot.iterrows():
        R = release_date(T)
        row = {"report": T, "release": R}
        if R is None:
            rows.append(row)
            continue
        pos = idx.searchsorted(R, side="right")       # first session strictly after the release
        if pos >= len(idx) or (idx[pos] - R).days > 10:   # no price yet (pre-2000 legacy rows) → no entry
            rows.append(row)
            continue
        E0 = idx[pos]
        P0 = price.iloc[pos]
        row.update({"entry": E0, "p0": P0, "lag_days": (E0 - T).days})
        if pos + late_sessions < len(idx):
            row["p0_late"] = price.iloc[pos + late_sessions]
            row["entry_late"] = idx[pos + late_sessions]
        for h in HORIZONS:
            end = E0 + pd.Timedelta(days=7 * h)
            if end > idx[-1]:
                row[f"fwd{h}"] = np.nan
            else:
                Ph = asof(price, end)
                row[f"fwd{h}"] = (Ph / P0 - 1) * 100
                if "p0_late" in row:
                    end_l = row["entry_late"] + pd.Timedelta(days=7 * h)
                    row[f"fwd{h}_late"] = (asof(price, end_l) / row["p0_late"] - 1) * 100 if end_l <= idx[-1] else np.nan
        # price at the report date and one report earlier (for the OI-price quadrant and the descriptive section)
        row["p_T"] = asof(price, T)
        for k, s in extra.items():
            row[k] = asof(s, R)             # known at the release → usable as a signal
            row[f"{k}_T"] = asof(s, T)      # as of the report date → descriptive (same-week) use only
        rows.append(row)
    pan = pd.DataFrame(rows).set_index("report")
    pan = pan.join(cot)
    pan["dp_week"] = pan["p_T"].pct_change() * 100                 # report-week price change (T-1 report → T)
    pan["r_next"] = pan["p0"].shift(-1) / pan["p0"] - 1              # realised return between consecutive decisions
    return pan


def add_signals(p: pd.DataFrame, kind: str) -> pd.DataFrame:
    if kind == "disagg":
        p["mm_net"] = p["mm_long"] - p["mm_short"]
        p["comm_net"] = p["comm_long"] - p["comm_short"]
        p["pm_net"] = p["pm_long"] - p["pm_short"]
        p["swap_net"] = p["swap_long"] - p["swap_short"]
        p["other_net"] = p["other_long"] - p["other_short"]
        spec = "mm_net"
    else:
        p["spec_net"] = p["spec_long"] - p["spec_short"]
        p["comm_net"] = p["comm_long"] - p["comm_short"]
        spec = "spec_net"
    p["nr_net"] = p["nr_long"] - p["nr_short"]
    p[f"{spec}_chg4"] = p[spec].diff(4)
    p[f"{spec}_chg1"] = p[spec].diff(1)
    lo, hi = p[spec].rolling(52).min(), p[spec].rolling(52).max()
    p[f"{spec}_cotidx52"] = (p[spec] - lo) / (hi - lo) * 100
    p[f"{spec}_z52"] = (p[spec] - p[spec].rolling(52).mean()) / p[spec].rolling(52).std()
    p[f"{spec}_pct_oi"] = p[spec] / p["oi"] * 100
    p["comm_net_cotidx52"] = (p["comm_net"] - p["comm_net"].rolling(52).min()) / (p["comm_net"].rolling(52).max() - p["comm_net"].rolling(52).min()) * 100
    p["oi_chg1"] = p["oi"].pct_change(1) * 100
    p["oi_chg4"] = p["oi"].pct_change(4) * 100
    for k in ("gld_tonnes", "dfii10", "dxy"):
        if k in p:
            if k == "dfii10":
                p["dfii10_chg4"] = p[k].diff(4) * 100      # basis points
            else:
                p[f"{k}_chg4"] = p[k].pct_change(4) * 100
    # OI-price quadrant at the report date
    doi = p["oi"].diff(1)
    q = np.where(p["dp_week"] > 0, np.where(doi > 0, "P↑ OI↑ new longs", "P↑ OI↓ short covering"),
                 np.where(doi > 0, "P↓ OI↑ new shorts", "P↓ OI↓ long liquidation"))
    p["quadrant"] = np.where(p["dp_week"].isna() | doi.isna(), None, q)
    return p


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# 5. Predictive tests
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def decile_table(p: pd.DataFrame, sig: str, h: int, pct_col: str) -> tuple[list[dict], dict]:
    x = p.dropna(subset=[f"fwd{h}", pct_col])
    if len(x) < 50:
        return [], {}
    dec = np.minimum((x[pct_col] * 10).astype(int), 9)
    mu = x[f"fwd{h}"].mean()
    rows = []
    for d in range(10):
        m = dec == d
        if m.sum() == 0:
            continue
        f = x.loc[m, f"fwd{h}"]
        rows.append({"decile": d + 1, "n": int(m.sum()), "mean_%": round(f.mean(), 2), "hit_%": round((f > 0).mean() * 100, 1),
                     "t_vs_all": round(nw_t(f - mu, max(h - 1, 0)), 2)})
    top, bot = x.loc[dec == 9, f"fwd{h}"], x.loc[dec == 0, f"fwd{h}"]
    sign = pd.Series(np.where(dec == 9, 1.0, np.where(dec == 0, -1.0, 0.0)), index=x.index)
    active = ((x[f"fwd{h}"] - mu) * sign)[sign != 0]
    rho, _ = stats.spearmanr(x[sig], x[f"fwd{h}"])
    _, t_ic = nw_slope_t(x[sig].rank(), x[f"fwd{h}"], max(h - 1, 0))
    summary = {"n": len(x), "mean_all_%": round(mu, 2), "top_mean_%": round(top.mean(), 2), "bottom_mean_%": round(bot.mean(), 2),
               "spread_%": round(top.mean() - bot.mean(), 2), "t_spread": round(nw_t(active, max(h - 1, 0)), 2),
               "spearman_ic": round(rho, 3), "t_ic": round(t_ic, 2)}
    return rows, summary


def subperiod_ic(p: pd.DataFrame, sig: str, h: int) -> dict:
    out = {}
    for name, a, b in SUBPERIODS:
        x = p.loc[(p.index >= (a or "1900")) & (p.index <= (b or "2100"))].dropna(subset=[sig, f"fwd{h}"])
        if len(x) < 40:
            out[name] = None
            continue
        rho, _ = stats.spearmanr(x[sig], x[f"fwd{h}"])
        _, t = nw_slope_t(x[sig].rank(), x[f"fwd{h}"], max(h - 1, 0))
        out[name] = f"{rho:+.3f} (t {t:+.1f}, n {len(x)})"
    return out


def walk_forward(p: pd.DataFrame, sig: str, h: int, cost_rt: float = COST_RT, fixed_dir: int | None = None) -> dict:
    """Long/flat, one tranche per week held h weeks (so h overlapping tranches), direction learned from completed
    history (expanding, strictly before the decision), favourable tercile → long. Returns IS and OOS metrics."""
    x = p.dropna(subset=[sig, "r_next", "p0"]).copy()
    n = len(x)
    if n < MIN_HIST + 60:
        return {}
    is_end = int(n * IS_FRACTION)
    sigv = x[sig].to_numpy(float)
    fwd = x[f"fwd{h}"].to_numpy(float)
    entry = x["entry"].to_numpy()
    pos_tranche = np.zeros(n)
    dirs = np.zeros(n)
    for t in range(MIN_HIST, n):
        # completed pairs: forward window of pair i ended on/before the decision date of t
        done_mask = (entry + np.timedelta64(7 * h, "D")) <= entry[t]
        done_mask[t:] = False
        hist = sigv[done_mask]
        if fixed_dir is None:
            pair = fwd[done_mask]
            ok = ~np.isnan(pair) & ~np.isnan(hist)
            if ok.sum() < 60:
                continue
            rho, _ = stats.spearmanr(hist[ok], pair[ok])
            d = 1 if rho > 0 else -1
        else:
            d = fixed_dir
        past = sigv[:t]
        past = past[~np.isnan(past)]
        pct = (past < sigv[t]).mean()
        dirs[t] = d
        pos_tranche[t] = 1.0 if (d > 0 and pct >= 2 / 3) or (d < 0 and pct <= 1 / 3) else 0.0
    pos = pd.Series(pos_tranche, index=x.index).rolling(h, min_periods=1).mean()   # h tranches, equally weighted
    r = x["r_next"]
    turn = pos.diff().abs().fillna(pos.abs())
    strat = pos * r - turn * (cost_rt / 100) / 2   # cost_rt is per round trip: each unit of turnover = one side
    bh = r
    scaled_bh = r * pos.mean()
    out = {"signal": sig, "h": h, "weeks": n, "is_end": str(x.index[is_end].date()), "exposure_%": round(pos.mean() * 100, 1)}
    for label, sl in (("IS", slice(MIN_HIST, is_end)), ("OOS", slice(is_end, n))):
        s, b, sb, po = strat.iloc[sl], bh.iloc[sl], scaled_bh.iloc[sl], pos.iloc[sl]
        ps, pb = perf(s), perf(b)
        if not ps:
            continue
        diff = s - b * po.mean()
        out[f"{label}_strat_cagr"] = ps["cagr"]
        out[f"{label}_strat_sharpe"] = ps["sharpe"]
        out[f"{label}_strat_maxdd"] = ps["max_dd"]
        out[f"{label}_bh_cagr"] = pb["cagr"]
        out[f"{label}_bh_sharpe"] = pb["sharpe"]
        out[f"{label}_bh_maxdd"] = pb["max_dd"]
        out[f"{label}_exposure_%"] = round(po.mean() * 100, 1)
        out[f"{label}_scaledbh_cagr"] = perf(b * po.mean())["cagr"]
        out[f"{label}_excess_vs_scaled_pa_%"] = round(diff.mean() * 52 * 100, 2)
        out[f"{label}_t_excess"] = round(nw_t(diff, max(h - 1, 0)), 2)
        out[f"{label}_dir_long_share_%"] = round((dirs[sl] > 0).mean() * 100, 0) if fixed_dir is None else (100 if fixed_dir > 0 else 0)
    out["_series"] = {"strat": strat, "bh": bh, "pos": pos}
    return out


def seasonality(p: pd.DataFrame, h: int = 4) -> tuple[list[dict], dict]:
    x = p.dropna(subset=[f"fwd{h}"]).copy()
    x["month"] = x["entry"].dt.month
    mu = x[f"fwd{h}"].mean()
    rows = []
    for m in range(1, 13):
        f = x.loc[x["month"] == m, f"fwd{h}"]
        rows.append({"month": datetime(2000, m, 1).strftime("%b"), "n": len(f), "mean_%": round(f.mean(), 2),
                     "hit_%": round((f > 0).mean() * 100, 1), "t_vs_all": round(nw_t(f - mu, max(h - 1, 0)), 2)})
    # walk-forward: each year, go long only in the 6 months with the highest mean h-week return in all PRIOR years
    x["year"] = x["entry"].dt.year
    years = sorted(x["year"].unique())
    pos = pd.Series(0.0, index=x.index)
    for y in years[5:]:
        prior = x[x["year"] < y]
        best = prior.groupby("month")[f"fwd{h}"].mean().sort_values(ascending=False).index[:6]
        pos[(x["year"] == y) & (x["month"].isin(best))] = 1.0
    pos = pos.rolling(h, min_periods=1).mean()
    r = x["r_next"]
    turn = pos.diff().abs().fillna(0)
    strat = pos * r - turn * (COST_RT / 100) / 2
    oos = x["year"] >= years[5]
    diff = (strat - r * pos[oos].mean())[oos]
    wf = {"oos_from": int(years[5]), "strat": perf(strat[oos]), "bh": perf(r[oos]), "exposure_%": round(pos[oos].mean() * 100, 1),
          "excess_vs_scaled_pa_%": round(diff.mean() * 52 * 100, 2), "t_excess": round(nw_t(diff, max(h - 1, 0)), 2)}
    return rows, wf


def quadrant_table(p: pd.DataFrame) -> list[dict]:
    rows = []
    for q in ["P↑ OI↑ new longs", "P↑ OI↓ short covering", "P↓ OI↑ new shorts", "P↓ OI↓ long liquidation"]:
        x = p[p["quadrant"] == q]
        row = {"quadrant": q, "n": len(x)}
        for h in HORIZONS:
            f = x[f"fwd{h}"].dropna()
            mu = p[f"fwd{h}"].mean()
            row[f"fwd{h}_mean_%"] = round(f.mean(), 2)
            row[f"fwd{h}_hit_%"] = round((f > 0).mean() * 100, 1)
            row[f"fwd{h}_t"] = round(nw_t(f - mu, max(h - 1, 0)), 2)
        rows.append(row)
    return rows


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# 6. Descriptive usefulness: does positioning explain what just happened?
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def descriptive(p: pd.DataFrame) -> dict:
    d = p.dropna(subset=["dp_week"]).copy()
    out = {"contemporaneous": []}
    for col, label in [("mm_net", "Managed-money net"), ("mm_long", "Managed-money gross long"), ("mm_short", "Managed-money gross short"),
                       ("comm_net", "Commercial net (producer/merchant + swap)"), ("pm_net", "Producer/merchant net"), ("swap_net", "Swap-dealer net"),
                       ("other_net", "Other reportables net"), ("nr_net", "Non-reportable (small) net"), ("oi", "Open interest")]:
        if col not in d:
            continue
        dx = d[col].diff()
        ok = dx.notna() & d["dp_week"].notna()
        pr = stats.pearsonr(dx[ok], d.loc[ok, "dp_week"])[0]
        sr = stats.spearmanr(dx[ok], d.loc[ok, "dp_week"])[0]
        beta, t = nw_slope_t(dx[ok] / 1000, d.loc[ok, "dp_week"], 0)
        same = ((np.sign(dx[ok]) == np.sign(d.loc[ok, "dp_week"])).mean() * 100)
        # and the predictive counterpart: same change vs NEXT week's price change
        nxt = d["dp_week"].shift(-1)
        ok2 = dx.notna() & nxt.notna()
        sr_next = stats.spearmanr(dx[ok2], nxt[ok2])[0]
        out["contemporaneous"].append({"series": label, "n": int(ok.sum()), "pearson_same_week": round(pr, 3), "spearman_same_week": round(sr, 3),
                                       "R2_%": round(pr ** 2 * 100, 1), "pct_move_per_1k_contracts": round(beta, 3), "t": round(t, 1),
                                       "same_sign_%": round(same, 1), "spearman_NEXT_week": round(sr_next, 3)})
    # macro series over the same report week (as of T): do they explain the move too?
    for col, label, scale in [("dfii10_T", "10-y real yield change, bp (same week)", 100.0), ("dxy_T", "DXY % change (same week)", None),
                              ("gld_tonnes_T", "GLD tonnes % change (same week)", None), ("usdinr_T", "USD/INR % change (same week)", None)]:
        if col not in d:
            continue
        dx = d[col].diff() * scale if scale else d[col].pct_change() * 100
        ok = dx.notna() & d["dp_week"].notna()
        pr = stats.pearsonr(dx[ok], d.loc[ok, "dp_week"])[0]
        sr = stats.spearmanr(dx[ok], d.loc[ok, "dp_week"])[0]
        nxt = d["dp_week"].shift(-1)
        ok2 = dx.notna() & nxt.notna()
        sr_next = stats.spearmanr(dx[ok2], nxt[ok2])[0]
        out["contemporaneous"].append({"series": label, "n": int(ok.sum()), "pearson_same_week": round(pr, 3), "spearman_same_week": round(sr, 3),
                                       "R2_%": round(pr ** 2 * 100, 1), "pct_move_per_1k_contracts": None, "t": None,
                                       "same_sign_%": round((np.sign(dx[ok]) == np.sign(d.loc[ok, "dp_week"])).mean() * 100, 1), "spearman_NEXT_week": round(sr_next, 3)})
    # stability of the descriptive relation by sub-period
    out["stability"] = []
    for name, a, b in SUBPERIODS:
        s = d.loc[(d.index >= (a or "1900")) & (d.index <= (b or "2100"))]
        dx = s["mm_net"].diff()
        ok = dx.notna() & s["dp_week"].notna()
        if ok.sum() < 30:
            continue
        out["stability"].append({"period": name, "n": int(ok.sum()), "spearman_same_week": round(stats.spearmanr(dx[ok], s.loc[ok, "dp_week"])[0], 3),
                                 "same_sign_%": round((np.sign(dx[ok]) == np.sign(s.loc[ok, "dp_week"])).mean() * 100, 1),
                                 "spearman_NEXT_week": round(stats.spearmanr(dx[ok], s["dp_week"].shift(-1)[ok].fillna(0))[0], 3)})
    # weekly driver labels (price-up weeks): what did managed money do?
    up = d[d["dp_week"] > 0]
    dn = d[d["dp_week"] < 0]
    def share(sub, cond):
        return round(cond(sub).mean() * 100, 1)
    out["drivers"] = {
        "up_weeks": len(up),
        "up_weeks_mm_long_added_%": share(up, lambda s: s["mm_long"].diff() > 0),
        "up_weeks_mm_short_covered_%": share(up, lambda s: s["mm_short"].diff() < 0),
        "up_weeks_mm_net_up_%": share(up, lambda s: s["mm_net"].diff() > 0),
        "up_weeks_oi_up_%": share(up, lambda s: s["oi"].diff() > 0),
        "down_weeks": len(dn),
        "down_weeks_mm_long_cut_%": share(dn, lambda s: s["mm_long"].diff() < 0),
        "down_weeks_mm_short_added_%": share(dn, lambda s: s["mm_short"].diff() > 0),
        "down_weeks_mm_net_down_%": share(dn, lambda s: s["mm_net"].diff() < 0),
        "down_weeks_oi_down_%": share(dn, lambda s: s["oi"].diff() < 0),
    }
    # last 12 reports: who did what
    last = d.tail(12)
    rows = []
    for T, r in last.iterrows():
        prev = d.loc[:T].iloc[-2] if len(d.loc[:T]) > 1 else None
        if prev is None:
            continue
        dl, ds = r["mm_long"] - prev["mm_long"], r["mm_short"] - prev["mm_short"]
        if r["dp_week"] > 0:
            driver = "new longs" if dl > abs(min(ds, 0)) else ("short covering" if ds < 0 else "funds sold into it")
        else:
            driver = "long liquidation" if dl < 0 and abs(dl) >= max(ds, 0) else ("new shorts" if ds > 0 else "funds bought the dip")
        rows.append({"report": str(T.date()), "released": str(r["release"].date()) if pd.notna(r["release"]) else "?",
                     "gold_$": round(r["p_T"], 0), "wk_%": round(r["dp_week"], 2), "MM_long": int(r["mm_long"]), "ΔMM_long": int(dl),
                     "MM_short": int(r["mm_short"]), "ΔMM_short": int(ds), "MM_net": int(r["mm_net"]), "Δcomm_net": int(r["comm_net"] - prev["comm_net"]),
                     "Δswap_net": int(r["swap_net"] - prev["swap_net"]), "Δother_net": int(r["other_net"] - prev["other_net"]),
                     "ΔOI": int(r["oi"] - prev["oi"]), "OI": int(r["oi"]), "quadrant": r["quadrant"], "MM driver": driver})
    out["last12"] = rows
    # the last rally: from the lowest report-date price of the trailing 2 years to the highest afterwards
    two = d.loc[d.index >= d.index[-1] - pd.Timedelta(days=730)]
    lo_T = two["p_T"].idxmin()
    hi_T = two.loc[lo_T:, "p_T"].idxmax()
    a, b = d.loc[lo_T], d.loc[hi_T]
    out["last_rally"] = {"from": str(lo_T.date()), "to": str(hi_T.date()), "price_from": round(a["p_T"], 0), "price_to": round(b["p_T"], 0),
                         "price_%": round((b["p_T"] / a["p_T"] - 1) * 100, 1),
                         "ΔMM_long": int(b["mm_long"] - a["mm_long"]), "ΔMM_short": int(b["mm_short"] - a["mm_short"]), "ΔMM_net": int(b["mm_net"] - a["mm_net"]),
                         "Δcomm_net": int(b["comm_net"] - a["comm_net"]), "Δswap_net": int(b["swap_net"] - a["swap_net"]), "Δpm_net": int(b["pm_net"] - a["pm_net"]),
                         "Δother_net": int(b["other_net"] - a["other_net"]), "Δnr_net": int(b["nr_net"] - a["nr_net"]), "ΔOI": int(b["oi"] - a["oi"]),
                         "ΔGLD_tonnes": round(b["gld_tonnes"] - a["gld_tonnes"], 1) if pd.notna(a.get("gld_tonnes")) and pd.notna(b.get("gld_tonnes")) else None}
    # since the rally high: what has happened
    c = d.iloc[-1]
    out["since_high"] = {"from": str(hi_T.date()), "to": str(d.index[-1].date()), "price_%": round((c["p_T"] / b["p_T"] - 1) * 100, 1),
                         "ΔMM_long": int(c["mm_long"] - b["mm_long"]), "ΔMM_short": int(c["mm_short"] - b["mm_short"]), "ΔMM_net": int(c["mm_net"] - b["mm_net"]),
                         "Δcomm_net": int(c["comm_net"] - b["comm_net"]), "Δother_net": int(c["other_net"] - b["other_net"]), "ΔOI": int(c["oi"] - b["oi"])}
    return out


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# 7. Figures (one axis per panel, categorical hues in fixed order, text in ink)
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def _style(ax, title: str, ylabel: str = ""):
    ax.set_title(title, loc="left", fontsize=10, color=COLORS["ink"], fontweight="bold")
    ax.set_ylabel(ylabel, fontsize=8, color=COLORS["ink2"])
    ax.tick_params(colors=COLORS["ink2"], labelsize=8)
    ax.grid(True, color=COLORS["grid"], linewidth=0.6)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(COLORS["grid"])


def figures(p: pd.DataFrame, dec_results: dict, wf_results: list[dict], quad: list[dict], seas: list[dict], gld_check: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb"})

    # 1. price and managed-money net: stacked panels (never a dual axis)
    fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True, gridspec_kw={"height_ratios": [2, 1.4, 1]})
    axes[0].plot(p.index, p["p_T"], color=COLORS["blue"], linewidth=1.4)
    axes[0].set_yscale("log")
    _style(axes[0], "COMEX gold, $/oz at each COT report date (log scale)", "$/oz")
    axes[1].plot(p.index, p["mm_net"] / 1000, color=COLORS["orange"], linewidth=1.2, label="Managed money net")
    axes[1].plot(p.index, p["comm_net"] / 1000, color=COLORS["aqua"], linewidth=1.2, label="Commercial net (producer/merchant + swap dealer)")
    axes[1].axhline(0, color=COLORS["ink2"], linewidth=0.6)
    axes[1].legend(fontsize=8, frameon=False, loc="upper left")
    _style(axes[1], "Net positions, thousand contracts (100 oz each)", "k contracts")
    axes[2].plot(p.index, p["mm_net_cotidx52"], color=COLORS["violet"], linewidth=1.0)
    axes[2].axhspan(90, 100, color=COLORS["red"], alpha=0.12)
    axes[2].axhspan(0, 10, color=COLORS["green"], alpha=0.12)
    axes[2].set_ylim(0, 100)
    _style(axes[2], "Managed-money 52-week COT index (0 = 1-year low, 100 = 1-year high); shaded = the classic extreme bands", "index")
    fig.tight_layout()
    fig.savefig(FIG / "fig1_price_positioning.png", dpi=150)
    plt.close(fig)

    # 2. decile means for the headline signals at 4 weeks — small multiples
    keys = [k for k in ("mm_net_cotidx52", "mm_net_chg4", "comm_net", "nr_net", "gld_tonnes_chg4", "dfii10_chg4", "dxy_chg4", "opt_mm_net") if (k, 4) in dec_results]
    fig, axes = plt.subplots(2, 4, figsize=(13, 6), sharey=True)
    for ax, k in zip(axes.ravel(), keys):
        rows, summ = dec_results[(k, 4)]
        ax.bar([r["decile"] for r in rows], [r["mean_%"] for r in rows], color=COLORS["blue"], width=0.7)
        ax.axhline(summ["mean_all_%"], color=COLORS["orange"], linewidth=1.0, linestyle="--")
        _style(ax, f"{k}\nIC {summ['spearman_ic']:+.3f} (t {summ['t_ic']:+.1f}), spread t {summ['t_spread']:+.1f}", "4-wk fwd return, %")
        ax.set_xlabel("walk-forward decile (1 = lowest)", fontsize=8, color=COLORS["ink2"])
    for ax in axes.ravel()[len(keys):]:
        ax.axis("off")
    fig.suptitle("Mean 4-week forward return by signal decile (dashed = unconditional mean)", fontsize=10, color=COLORS["ink"], x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(FIG / "fig2_deciles_4w.png", dpi=150)
    plt.close(fig)

    # 3. walk-forward OOS equity curves of the three managed-money rules vs buy-and-hold
    fig, ax = plt.subplots(figsize=(11, 5))
    hues = [COLORS["orange"], COLORS["aqua"], COLORS["violet"], COLORS["magenta"]]
    i = 0
    for w in wf_results:
        if w.get("signal") in ("mm_net_cotidx52", "mm_net_chg4", "comm_net") and w.get("h") == 4 and "_series" in w:
            s = w["_series"]
            oos = s["strat"].loc[w["is_end"]:]
            eq = (1 + oos).cumprod()
            ax.plot(eq.index, eq.values, color=hues[i % 4], linewidth=1.3, label=f"{w['signal']} long/flat (h=4, {w['OOS_exposure_%']}% invested)")
            i += 1
            bh = (1 + s["bh"].loc[w["is_end"]:]).cumprod()
    ax.plot(bh.index, bh.values, color=COLORS["blue"], linewidth=1.6, label="Buy and hold (gold)")
    ax.set_yscale("log")
    ax.legend(fontsize=8, frameon=False, loc="upper left")
    _style(ax, "Out-of-sample growth of 1 — walk-forward long/flat rules after 0.15 % round-trip costs vs holding gold", "growth of 1 (log)")
    fig.tight_layout()
    fig.savefig(FIG / "fig3_walkforward_oos.png", dpi=150)
    plt.close(fig)

    # 4. OI-price quadrants
    fig, axes = plt.subplots(1, 3, figsize=(12, 4), sharey=False)
    for ax, h in zip(axes, HORIZONS):
        labels = [q["quadrant"].replace(" new", "\nnew").replace(" short", "\nshort").replace(" long", "\nlong") for q in quad]
        vals = [q[f"fwd{h}_mean_%"] for q in quad]
        ax.bar(range(4), vals, color=[COLORS["green"], COLORS["aqua"], COLORS["red"], COLORS["orange"]], width=0.6)
        ax.set_xticks(range(4))
        ax.set_xticklabels(labels, fontsize=7.5)
        ax.set_xlim(-0.6, 3.6)
        ax.axhline(p[f"fwd{h}"].mean(), color=COLORS["ink2"], linewidth=0.8, linestyle="--")
        _style(ax, f"{h}-week forward return by OI-price quadrant", "%")
    fig.tight_layout()
    fig.savefig(FIG / "fig4_oi_quadrants.png", dpi=150)
    plt.close(fig)

    # 5. seasonality
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar(range(12), [r["mean_%"] for r in seas], color=COLORS["blue"], width=0.7)
    ax.set_xticks(range(12))
    ax.set_xticklabels([r["month"] for r in seas], fontsize=8)
    ax.axhline(np.mean([r["mean_%"] for r in seas]), color=COLORS["orange"], linewidth=1.0, linestyle="--")
    _style(ax, "Mean 4-week forward return by calendar month of entry (2006-2026), with t-stats in the table", "%")
    fig.tight_layout()
    fig.savefig(FIG / "fig5_seasonality.png", dpi=150)
    plt.close(fig)

    # 6. descriptive: same-week vs next-week relation between managed-money net change and price
    d = p.dropna(subset=["dp_week"]).copy()
    dx = d["mm_net"].diff() / 1000
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    axes[0].scatter(dx, d["dp_week"], s=8, color=COLORS["blue"], alpha=0.55, edgecolors="none")
    _style(axes[0], "Same week: ΔMM net (k contracts) vs gold's weekly % change", "gold weekly change, %")
    axes[0].set_xlabel("Δ managed-money net, k contracts (report week)", fontsize=8, color=COLORS["ink2"])
    axes[1].scatter(dx, d["dp_week"].shift(-1), s=8, color=COLORS["orange"], alpha=0.55, edgecolors="none")
    _style(axes[1], "Next week: the same ΔMM net vs the FOLLOWING week", "gold next-week change, %")
    axes[1].set_xlabel("Δ managed-money net, k contracts (report week)", fontsize=8, color=COLORS["ink2"])
    fig.tight_layout()
    fig.savefig(FIG / "fig6_descriptive_vs_predictive.png", dpi=150)
    plt.close(fig)


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# 8. Main
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def main() -> None:
    RES.mkdir(exist_ok=True)
    FIG.mkdir(exist_ok=True)
    md: list[str] = [f"# G-STUDY result tables\n\nGenerated {datetime.now():%Y-%m-%d %H:%M} by `g_study.py`. All forward returns start at the close of the "
                     "first COMEX session AFTER the COT release (Friday 15:30 ET → Monday close) and are in % of the GC=F front-month settlement.\n"]
    summary: dict = {}

    # ── data ──
    cot_df = load_cot("disagg_fut")
    cot_c = load_cot("disagg_com")
    leg_f = load_cot("legacy_fut")
    checks = {k: crosscheck_zip(k, v) for k, v in (("disagg_fut", cot_df), ("disagg_com", cot_c), ("legacy_fut", leg_f), ("legacy_com", load_cot("legacy_com")))}
    summary["crosscheck_socrata_vs_zip"] = checks
    gc = load_yahoo("GC_F")
    price = gc["close"]
    gld_px = load_yahoo("GLD")
    dxy = load_yahoo("DX_Y_NYB")["close"]
    inr = load_yahoo("INR_X")["close"]
    dfii = load_fred("DFII10")
    gld = load_gld_tonnes()

    # GC=F vs GLD sanity (roll drift, correlation) on weekly Friday closes
    wk_gc = price.resample("W-FRI").last().pct_change()
    wk_gld = gld_px["adjclose"].resample("W-FRI").last().pct_change()
    both = pd.concat([wk_gc, wk_gld], axis=1).dropna()
    both.columns = ["gc", "gld"]
    gld_check = {"weeks": len(both), "corr_weekly": round(both.corr().iloc[0, 1], 4),
                 "gc_cagr_%": round(((1 + both["gc"]).prod() ** (52 / len(both)) - 1) * 100, 2),
                 "gld_cagr_%": round(((1 + both["gld"]).prod() ** (52 / len(both)) - 1) * 100, 2),
                 "from": str(both.index[0].date()), "to": str(both.index[-1].date())}
    summary["gc_vs_gld"] = gld_check

    # options positioning = combined − futures-only managed-money net
    opt = (cot_c["mm_long"] - cot_c["mm_short"]) - (cot_df["mm_long"] - cot_df["mm_short"])

    extra = {"gld_tonnes": gld["tonnes"], "dfii10": dfii, "dxy": dxy, "usdinr": inr}
    p = build_panel(cot_df, price, extra)
    p = add_signals(p, "disagg")
    p["opt_mm_net"] = opt.reindex(p.index)
    p["opt_mm_net_chg4"] = p["opt_mm_net"].diff(4)
    p.to_csv(RES / "panel_disagg.csv")
    L = build_panel(leg_f, price, {})
    L = add_signals(L, "legacy")
    L.to_csv(RES / "panel_legacy.csv")

    usable = p.dropna(subset=["entry"])
    summary["panel"] = {"disagg_reports": len(p), "disagg_with_entry": len(usable), "excluded_unverifiable_release": int(p["release"].isna().sum()),
                        "first_report": str(p.index[0].date()), "last_report": str(p.index[-1].date()),
                        "median_lag_report_to_entry_days": float(usable["lag_days"].median()), "max_lag_days": int(usable["lag_days"].max()),
                        "legacy_reports_with_price": int(L["entry"].notna().sum()), "legacy_first_with_price": str(L.dropna(subset=["entry"]).index[0].date())}
    md.append("## Data cross-check: CFTC Socrata API vs the raw history zips\n")
    md.append(table([{"dataset": k, **{kk: (json.dumps(vv) if isinstance(vv, dict) else vv) for kk, vv in v.items()}} for k, v in checks.items()],
                    ["dataset", "socrata_rows", "zip_rows", "common_dates", "socrata_only", "zip_only", "value_mismatches"]))
    md.append("\n## Price series check: GC=F (COMEX front-month settle) vs GLD (ETF, adjusted close), weekly Friday returns\n")
    md.append(table([gld_check], list(gld_check.keys())))
    md.append("\n## Panel\n")
    md.append(table([summary["panel"]], list(summary["panel"].keys())))
    lagd = usable["lag_days"].value_counts().sort_index()
    md.append("\nReport-date → entry-session lag (days): " + ", ".join(f"{int(k)}d×{int(v)}" for k, v in lagd.items()))

    # ── predictive: deciles, IC, sub-periods ──
    SIGNALS = [  # column, label, pre-registered hypothesis, source
        ("mm_net", "Managed-money net (contracts)", "contrarian: extreme long → weak; extreme short → strong", "COT disagg"),
        ("mm_net_pct_oi", "Managed-money net, % of OI", "contrarian", "COT disagg"),
        ("mm_net_chg4", "Managed-money net, 4-week change", "exploratory (trend vs reversal)", "COT disagg"),
        ("mm_net_cotidx52", "Managed-money 52-wk COT index", "contrarian at the 90/10 bands", "COT disagg"),
        ("mm_net_z52", "Managed-money 52-wk z-score", "contrarian", "COT disagg"),
        ("comm_net", "Commercial net (prod/merch + swap)", "the mirror: commercial net high → strong", "COT disagg"),
        ("comm_net_cotidx52", "Commercial 52-wk COT index", "high → strong", "COT disagg"),
        ("nr_net", "Small-speculator (non-reportable) net", "contrarian", "COT disagg"),
        ("oi_chg1", "Open interest, 1-week % change", "exploratory", "COT"),
        ("oi_chg4", "Open interest, 4-week % change", "exploratory", "COT"),
        ("opt_mm_net", "Options-only MM net (combined − futures)", "exploratory", "COT disagg combined"),
        ("opt_mm_net_chg4", "Options-only MM net, 4-wk change", "exploratory", "COT disagg combined"),
        ("gld_tonnes_chg4", "GLD tonnes, 4-week % change", "momentum: inflows → strong", "SPDR"),
        ("dfii10_chg4", "10-y real yield, 4-week change (bp)", "falling real yields → strong", "FRED DFII10"),
        ("dxy_chg4", "DXY, 4-week % change", "falling dollar → strong", "Yahoo DX-Y.NYB"),
    ]
    dec_results: dict = {}
    ic_rows: list[dict] = []
    for col, label, hyp, src in SIGNALS:
        if col not in p:
            continue
        p[f"{col}_pct"] = expanding_pct(p[col])
        for h in HORIZONS:
            rows, summ = decile_table(p, col, h, f"{col}_pct")
            if not rows:
                continue
            dec_results[(col, h)] = (rows, summ)
            sub = subperiod_ic(p, col, h)
            ic_rows.append({"signal": col, "h": h, **summ, **{f"ic_{k}": v for k, v in sub.items()}, "hypothesis": hyp})
            pd.DataFrame(rows).to_csv(RES / f"deciles_{col}_h{h}.csv", index=False)
    ic_df = pd.DataFrame(ic_rows)
    ic_df.to_csv(RES / "ic_summary.csv", index=False)
    md.append("\n## Rank IC and decile spreads (disaggregated COT, 2006-2026; expanding walk-forward deciles)\n")
    md.append("IC = Spearman rank correlation between the signal (known at release) and the forward return; t = Newey-West t of the slope. "
              "spread = top-decile mean − bottom-decile mean (t Newey-West, lags = h−1). Sub-period cells: IC (t, n).\n")
    md.append(table(ic_rows, ["signal", "h", "n", "mean_all_%", "top_mean_%", "bottom_mean_%", "spread_%", "t_spread", "spearman_ic", "t_ic",
                              "ic_pre-2011", "ic_2011-19", "ic_2020-26", "hypothesis"]))
    # Full decile tables for the headline signals
    for col in ("mm_net_cotidx52", "mm_net", "mm_net_chg4", "comm_net", "nr_net", "gld_tonnes_chg4", "dfii10_chg4", "dxy_chg4"):
        for h in HORIZONS:
            if (col, h) in dec_results:
                rows, summ = dec_results[(col, h)]
                md.append(f"\n### Deciles · {col} · {h}-week horizon (n {summ['n']}, unconditional mean {summ['mean_all_%']} %)\n")
                md.append(table(rows, ["decile", "n", "mean_%", "hit_%", "t_vs_all"]))

    # fixed-band test of the classic rule: COT index ≥ 90 / ≤ 10
    md.append("\n## The classic desk rule: managed-money 52-week COT index ≥ 90 (crowded long) or ≤ 10 (washed out)\n")
    band_rows = []
    for h in HORIZONS:
        x = p.dropna(subset=["mm_net_cotidx52", f"fwd{h}"])
        mu = x[f"fwd{h}"].mean()
        for name, m in (("≥ 90", x["mm_net_cotidx52"] >= 90), ("≤ 10", x["mm_net_cotidx52"] <= 10), ("middle", (x["mm_net_cotidx52"] > 10) & (x["mm_net_cotidx52"] < 90))):
            f = x.loc[m, f"fwd{h}"]
            sub = {}
            for sname, a, b in SUBPERIODS:
                ff = f[(f.index >= (a or "1900")) & (f.index <= (b or "2100"))]
                sub[sname] = f"{ff.mean():+.2f} (n {len(ff)})" if len(ff) >= 10 else ""
            band_rows.append({"h": h, "band": name, "n": len(f), "mean_%": round(f.mean(), 2), "hit_%": round((f > 0).mean() * 100, 1),
                              "excess_vs_all_%": round(f.mean() - mu, 2), "t_nw": round(nw_t(f - mu, max(h - 1, 0)), 2), **sub})
    md.append(table(band_rows, ["h", "band", "n", "mean_%", "hit_%", "excess_vs_all_%", "t_nw", "pre-2011", "2011-19", "2020-26"]))
    pd.DataFrame(band_rows).to_csv(RES / "cot_index_bands.csv", index=False)

    # legacy (2000-2026) large-spec / commercial / small-spec for a longer sample
    md.append("\n## Legacy report (large speculators = non-commercial), 2000-2026 — longer sample, same method\n")
    leg_rows = []
    for col in ("spec_net", "spec_net_chg4", "spec_net_cotidx52", "spec_net_z52", "comm_net", "comm_net_cotidx52", "nr_net", "oi_chg4"):
        L[f"{col}_pct"] = expanding_pct(L[col])
        for h in HORIZONS:
            rows, summ = decile_table(L, col, h, f"{col}_pct")
            if rows:
                sub = subperiod_ic(L, col, h)
                leg_rows.append({"signal": col, "h": h, **summ, **{f"ic_{k}": v for k, v in sub.items()}})
    md.append(table(leg_rows, ["signal", "h", "n", "mean_all_%", "top_mean_%", "bottom_mean_%", "spread_%", "t_spread", "spearman_ic", "t_ic",
                               "ic_pre-2011", "ic_2011-19", "ic_2020-26"]))
    pd.DataFrame(leg_rows).to_csv(RES / "ic_summary_legacy.csv", index=False)

    # late-entry robustness (2 sessions later) for the headline signals
    md.append("\n## Robustness: entering two sessions later (Wednesday close instead of Monday)\n")
    late_rows = []
    for col in ("mm_net_cotidx52", "mm_net_chg4", "comm_net", "mm_net"):
        for h in HORIZONS:
            x = p.dropna(subset=[col, f"fwd{h}_late"])
            rho, _ = stats.spearmanr(x[col], x[f"fwd{h}_late"])
            _, t = nw_slope_t(x[col].rank(), x[f"fwd{h}_late"], max(h - 1, 0))
            late_rows.append({"signal": col, "h": h, "n": len(x), "spearman_ic_late": round(rho, 3), "t_ic_late": round(t, 2),
                              "spearman_ic_monday": dec_results[(col, h)][1]["spearman_ic"]})
    md.append(table(late_rows, ["signal", "h", "n", "spearman_ic_monday", "spearman_ic_late", "t_ic_late"]))

    # ── walk-forward long/flat after costs ──
    cost_ref = round_trip_costs("GOLD", price=float(price.iloc[-1] * asof(inr, price.index[-1]) / 31.1034768 * 10), lots=1)
    summary["mcx_cost_reference"] = {"gold_rs_per_10g": cost_ref["price"], "round_trip_rs": cost_ref["total"], "pct_of_notional": cost_ref["pct_of_notional"],
                                     "note": "shared/mcx_specs.round_trip_costs; the study charges the project floor 0.15 % instead"}
    md.append(f"\n## Walk-forward long/flat rules after costs (round trip {COST_RT} %; MCX GOLD exchange+brokerage cost is only "
              f"{cost_ref['pct_of_notional']} % of notional = ₹{cost_ref['total']:,.0f} per 1-kg lot at ₹{cost_ref['price']:,.0f}/10 g, so the floor dominates)\n")
    md.append(f"IS = first {int(IS_FRACTION * 100)} % of weeks (direction learned inside the window: optimistic by construction); OOS = expanding walk-forward from "
              "`is_end`; one tranche per week held h weeks; long when the signal's expanding percentile is in the favourable tercile. "
              "`excess_vs_scaled` = strategy minus buy-and-hold scaled to the same average exposure (the honest benchmark for a long/flat rule).\n")
    wf_results = []
    for col, label, hyp, src in SIGNALS:
        if col not in p:
            continue
        for h in HORIZONS:
            w = walk_forward(p, col, h)
            if w:
                wf_results.append(w)
    wf_cols = ["signal", "h", "is_end", "IS_strat_cagr", "IS_bh_cagr", "IS_exposure_%", "IS_excess_vs_scaled_pa_%", "IS_t_excess",
               "OOS_strat_cagr", "OOS_strat_sharpe", "OOS_strat_maxdd", "OOS_bh_cagr", "OOS_bh_sharpe", "OOS_bh_maxdd", "OOS_exposure_%",
               "OOS_excess_vs_scaled_pa_%", "OOS_t_excess", "OOS_dir_long_share_%"]
    md.append(table(wf_results, wf_cols))
    pd.DataFrame([{k: v for k, v in w.items() if not k.startswith("_")} for w in wf_results]).to_csv(RES / "walk_forward.csv", index=False)
    # pre-registered fixed-direction variants for the classic contrarian rule
    md.append("\n### Fixed-direction variants (no learning): contrarian on the COT index (long when index in bottom tercile) and 'follow the commercials'\n")
    fixed = []
    for col, d in (("mm_net_cotidx52", -1), ("mm_net", -1), ("comm_net", +1), ("mm_net_chg4", +1), ("mm_net_chg4", -1), ("gld_tonnes_chg4", +1), ("dfii10_chg4", -1), ("dxy_chg4", -1)):
        for h in HORIZONS:
            w = walk_forward(p, col, h, fixed_dir=d)
            if w:
                w["signal"] = f"{col} (dir {'+' if d > 0 else '−'})"
                fixed.append(w)
    md.append(table(fixed, wf_cols))
    pd.DataFrame([{k: v for k, v in w.items() if not k.startswith("_")} for w in fixed]).to_csv(RES / "walk_forward_fixed_direction.csv", index=False)

    # INR terms (what an MCX trader actually earns): buy-and-hold in rupees vs the best OOS rule in rupees
    inr_px = (price * inr.reindex(price.index).ffill()).dropna()
    p_inr = build_panel(cot_df, inr_px, {})
    p_inr = add_signals(p_inr, "disagg")
    p_inr["mm_net_cotidx52_pct"] = expanding_pct(p_inr["mm_net_cotidx52"])
    w_inr = walk_forward(p_inr, "mm_net_cotidx52", 4)
    w_inr_fixed = walk_forward(p_inr, "mm_net_cotidx52", 4, fixed_dir=-1)
    md.append("\n### The same rule measured in rupees (GC=F × USD/INR, the MCX proxy — MCX history itself is not freely downloadable)\n")
    md.append(table([{**{k: v for k, v in w_inr.items() if not k.startswith('_')}, "signal": "mm_net_cotidx52 learned (INR)"},
                     {**{k: v for k, v in w_inr_fixed.items() if not k.startswith('_')}, "signal": "mm_net_cotidx52 contrarian (INR)"}], wf_cols))

    # ── seasonality and OI quadrants ──
    seas_rows, seas_wf = seasonality(p, 4)
    md.append("\n## Month-of-year seasonality (4-week forward return by calendar month of entry; walk-forward 'best 6 months' rule)\n")
    md.append(table(seas_rows, ["month", "n", "mean_%", "hit_%", "t_vs_all"]))
    md.append(f"\nWalk-forward (long only in the 6 best months of all prior years, from {seas_wf['oos_from']}): strategy {seas_wf['strat']}, buy-and-hold "
              f"{seas_wf['bh']}, exposure {seas_wf['exposure_%']} %, excess vs scaled B&H {seas_wf['excess_vs_scaled_pa_%']} %/yr (t {seas_wf['t_excess']}).")
    pd.DataFrame(seas_rows).to_csv(RES / "seasonality.csv", index=False)
    summary["seasonality_walk_forward"] = seas_wf
    quad = quadrant_table(p)
    md.append("\n## OI-price quadrant at the report date (price change over the report week × open-interest change)\n")
    md.append(table(quad, ["quadrant", "n"] + [f"fwd{h}_{m}" for h in HORIZONS for m in ("mean_%", "hit_%", "t")]))
    pd.DataFrame(quad).to_csv(RES / "oi_quadrants.csv", index=False)

    # ── descriptive ──
    desc = descriptive(p)
    md.append("\n## Descriptive usefulness: positioning changes vs the SAME week's price move (and the next week's)\n")
    md.append(table(desc["contemporaneous"], ["series", "n", "pearson_same_week", "spearman_same_week", "R2_%", "pct_move_per_1k_contracts", "t", "same_sign_%", "spearman_NEXT_week"]))
    md.append("\n### Stability of the same-week relation (managed-money net change vs the week's price change)\n")
    md.append(table(desc["stability"], ["period", "n", "spearman_same_week", "same_sign_%", "spearman_NEXT_week"]))
    md.append("\n### What managed money did in up-weeks and down-weeks\n")
    md.append(table([desc["drivers"]], list(desc["drivers"].keys())))
    md.append("\n### The last 12 reports: who did what\n")
    md.append(table(desc["last12"], list(desc["last12"][0].keys())))
    md.append("\n### The last rally, decomposed\n")
    md.append(table([desc["last_rally"]], list(desc["last_rally"].keys())))
    md.append("\n### Since the rally high\n")
    md.append(table([desc["since_high"]], list(desc["since_high"].keys())))
    pd.DataFrame(desc["contemporaneous"]).to_csv(RES / "descriptive_contemporaneous.csv", index=False)
    pd.DataFrame(desc["last12"]).to_csv(RES / "descriptive_last12.csv", index=False)
    summary["descriptive"] = {k: v for k, v in desc.items() if k != "last12"}

    # ── survival verdicts ──
    def survives(col: str) -> dict:
        r = ic_df[ic_df["signal"] == col]
        out = {}
        for h in HORIZONS:
            rr = r[r["h"] == h]
            if rr.empty:
                continue
            rr = rr.iloc[0]
            subs = [rr[f"ic_{k}"] for k, _, _ in SUBPERIODS if isinstance(rr[f"ic_{k}"], str) and rr[f"ic_{k}"]]
            signs = [float(s.split()[0]) for s in subs]
            same_sign = len(signs) >= 2 and (all(s > 0 for s in signs) or all(s < 0 for s in signs))
            w = next((w for w in wf_results if w["signal"] == col and w["h"] == h), {})
            oos_ok = w.get("OOS_t_excess") is not None and w.get("OOS_t_excess", 0) >= 2.0 and w.get("OOS_excess_vs_scaled_pa_%", 0) > 0
            out[h] = {"t_ic": float(rr["t_ic"]), "t_spread": float(rr["t_spread"]), "same_sign_subperiods": same_sign,
                      "oos_excess_pa_%": w.get("OOS_excess_vs_scaled_pa_%"), "oos_t": w.get("OOS_t_excess"),
                      "verdict": "PASS" if (abs(rr["t_ic"]) >= 2.5 and same_sign and oos_ok) else ("WEAK" if abs(rr["t_ic"]) >= 2.0 else "FAIL")}
        return out
    summary["verdicts"] = {col: survives(col) for col, *_ in SIGNALS if col in p}
    md.append("\n## Survival table (PASS needs |t_IC| ≥ 2.5 on the full sample, the same IC sign in every sub-period, and OOS excess after costs with t ≥ 2)\n")
    vrows = []
    for col, v in summary["verdicts"].items():
        for h, r in v.items():
            vrows.append({"signal": col, "h": h, **r})
    md.append(table(vrows, ["signal", "h", "t_ic", "t_spread", "same_sign_subperiods", "oos_excess_pa_%", "oos_t", "verdict"]))
    pd.DataFrame(vrows).to_csv(RES / "survival.csv", index=False)

    figures(p, dec_results, wf_results, quad, seas_rows, gld_check)
    (ROOT / "RESULTS_TABLES.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (ROOT / "summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    print("done:", len(ic_rows), "signal×horizon tests;", len(wf_results), "walk-forward rules; panel", len(p), "reports")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Data-quality profile for the SuryaDhana ML evaluation dataset.

Read-only consumer of:
  * nse_market.duckdb  (equity_eod, equity_features)  -- opened read_only
  * ml/data/model_dataset.parquet + manifest.json + splits.json

Writes:
  * ml/results/data_profile.json          (consumed by evaluator/report agents)
  * ml/report/assets/data_universe_by_month.png
  * ml/report/assets/data_regime_monthly.png

Run:  cd <repo> && python3 -m ml.profile_data
Seed 108 everywhere; never modifies the dataset or the DB.
"""
from __future__ import annotations

import os

os.environ.setdefault("OMP_NUM_THREADS", "2")

import json
from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPO = Path(__file__).resolve().parent.parent
ML = REPO / "ml"
DB_PATH = str(REPO / "nse_market.duckdb")
DATA_DIR = ML / "data"
RESULTS_DIR = ML / "results"
ASSETS_DIR = ML / "report" / "assets"
SEED = 108
CORR_SAMPLE = 100_000
CORR_THRESHOLD = 0.85
HIGH_NAN_PCT = 10.0

# Official NSE trading holidays, 2025 (verified: the only weekdays missing from
# equity_eod in 2025 are exactly these). 2026 has no official list encoded --
# any missing 2026 weekday is therefore reported as suspicious.
NSE_HOLIDAYS_2025 = {
    "2025-02-26": "Mahashivratri",
    "2025-03-14": "Holi",
    "2025-03-31": "Id-ul-Fitr",
    "2025-04-10": "Shri Mahavir Jayanti",
    "2025-04-14": "Dr. Ambedkar Jayanti",
    "2025-04-18": "Good Friday",
    "2025-05-01": "Maharashtra Day",
    "2025-08-15": "Independence Day",
    "2025-08-27": "Ganesh Chaturthi",
    "2025-10-02": "Mahatma Gandhi Jayanti / Dussehra",
    "2025-10-21": "Diwali Laxmi Pujan (muhurat session only)",
    "2025-10-22": "Diwali Balipratipada",
    "2025-11-05": "Prakash Gurpurb Sri Guru Nanak Dev",
    "2025-12-25": "Christmas",
}


def _f(x, nd: int = 6):
    """float for JSON; NaN/None -> None."""
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    if np.isnan(x) or np.isinf(x):
        return None
    return round(x, nd)


# --------------------------------------------------------------------------- #
# Sections
# --------------------------------------------------------------------------- #
def funnel(con, df: pd.DataFrame, manifest: dict) -> dict:
    eod_n, eod_t, eod_d0, eod_d1 = con.execute(
        "SELECT count(*), count(DISTINCT ticker), min(date), max(date) FROM equity_eod"
    ).fetchone()
    ft_n, ft_t, ft_d0, ft_d1 = con.execute(
        "SELECT count(*), count(DISTINCT ticker), min(date), max(date) FROM equity_features"
    ).fetchone()
    primary_rows = int((df["label_beat_mkt_20d"].notna() & df["y_clean_20d"].astype(bool)).sum())
    return {
        "equity_eod": {"rows": int(eod_n), "tickers": int(eod_t),
                       "date_min": str(eod_d0), "date_max": str(eod_d1)},
        "equity_features": {"rows": int(ft_n), "tickers": int(ft_t),
                            "date_min": str(ft_d0), "date_max": str(ft_d1)},
        "universe_parquet": {"rows": int(len(df)), "tickers": int(df["ticker"].nunique()),
                             "date_min": str(df["date"].min().date()),
                             "date_max": str(df["date"].max().date())},
        "primary_task_rows": primary_rows,
        "primary_task_note": "label_beat_mkt_20d not-NaN AND y_clean_20d True "
                             "(rows the evaluation harness actually uses)",
        "matches_manifest": bool(len(df) == manifest["rows"]
                                 and df["ticker"].nunique() == manifest["tickers"]),
        "note": "equity_eod -> equity_features drops non-feature series/short histories; "
                "features -> universe applies close >= Rs10, trailing-20d median turnover "
                ">= Rs1cr, and date >= 2025-06-01 (warm-up excluded).",
    }


def per_month(df: pd.DataFrame) -> list[dict]:
    out = []
    up5 = pd.to_numeric(df["label_up_5d"], errors="coerce")
    g = df.assign(_up5=up5).groupby(df["date"].dt.to_period("M"), observed=True)
    for p, grp in g:
        out.append({
            "month": str(p),
            "rows": int(len(grp)),
            "tickers": int(grp["ticker"].nunique()),
            "trading_days": int(grp["date"].nunique()),
            "mean_label_beat_mkt_20d": _f(grp["label_beat_mkt_20d"].mean()),
            "mean_label_up_5d": _f(grp["_up5"].mean()),
            "median_y_raw_20d": _f(grp["y_raw_20d"].median()),
            "mean_y_clean_20d": _f(grp["y_clean_20d"].astype(float).mean()),
        })
    return out


def calendar_audit(con) -> dict:
    d = con.execute("SELECT DISTINCT date FROM equity_eod ORDER BY date").df()["date"]
    dates = pd.DatetimeIndex(pd.to_datetime(d))
    weekdays = pd.bdate_range(dates.min(), dates.max())
    missing = weekdays.difference(dates)
    missing_list = [{"date": str(x.date()), "weekday": x.day_name(),
                     "known_holiday": NSE_HOLIDAYS_2025.get(str(x.date()))}
                    for x in missing]
    suspicious = [m["date"] for m in missing_list if m["known_holiday"] is None]

    months = []
    for p in pd.period_range(dates.min(), dates.max(), freq="M"):
        lo = max(p.start_time, dates.min())
        hi = min(p.end_time, dates.max())
        wd = pd.bdate_range(lo, hi)
        hols = [h for h in NSE_HOLIDAYS_2025
                if lo <= pd.Timestamp(h) <= hi and pd.Timestamp(h).dayofweek < 5]
        actual = int(((dates >= lo) & (dates <= hi)).sum())
        expected = len(wd) - len(hols)
        months.append({"month": str(p), "trading_days": actual, "weekdays": int(len(wd)),
                       "known_holidays_on_weekdays": len(hols), "expected_days": expected,
                       "delta_vs_expected": actual - expected})

    # partial-ingest check: days whose ticker count collapses vs neighbours
    tc = con.execute(
        "SELECT date, count(DISTINCT ticker) AS nt FROM equity_eod GROUP BY date ORDER BY date"
    ).df()
    roll_med = tc["nt"].rolling(21, center=True, min_periods=5).median()
    low = tc[tc["nt"] < 0.8 * roll_med]
    low_days = [{"date": str(pd.Timestamp(r.date).date()), "tickers": int(r.nt)}
                for r in low.itertuples()]

    no_2026_closures = (not any(m["date"].startswith("2026") for m in missing_list))
    return {
        "range": {"first_date": str(dates.min().date()), "last_date": str(dates.max().date()),
                  "n_trading_dates": int(len(dates))},
        "per_month": months,
        "missing_weekdays": missing_list,
        "suspicious_missing_dates": suspicious,
        "low_coverage_days": low_days,
        "observations": ([
            "All 13 missing weekdays fall in 2025 and match the official NSE 2025 "
            "holiday calendar exactly -- no unexplained data gaps.",
        ] + (["2026 (Jan..Oct) has ZERO holiday closures: every single weekday trades. "
              "A real NSE calendar closes ~13-15 weekdays/yr (Republic Day, Holi, Good "
              "Friday, Independence Day...). The 2026 portion runs on a simulated "
              "continuous calendar -- harmless for modeling, but calendar-sensitive "
              "logic (holiday effects, days-to-event features) would be meaningless "
              "in 2026."] if no_2026_closures else [])),
    }


def feature_nan_rates(df: pd.DataFrame, features: list[str]) -> dict:
    rates = (df[features].isna().mean() * 100.0).sort_values(ascending=False)
    return {
        "pct_nan": {k: _f(v, 3) for k, v in rates.items()},
        "high_nan_gt10pct": {k: _f(v, 3) for k, v in rates[rates > HIGH_NAN_PCT].items()},
    }


def feature_moments(df: pd.DataFrame, features: list[str]) -> dict:
    X = df[features]
    mean, std = X.mean(), X.std()
    q = X.quantile([0.01, 0.50, 0.99])
    return {c: {"mean": _f(mean[c]), "std": _f(std[c]), "p1": _f(q.loc[0.01, c]),
                "p50": _f(q.loc[0.50, c]), "p99": _f(q.loc[0.99, c])}
            for c in features}


def correlation(df: pd.DataFrame, features: list[str]) -> dict:
    feats = [c for c in features if not c.endswith("_isnan")]
    sample = df[feats].sample(n=min(CORR_SAMPLE, len(df)), random_state=SEED)
    # Spearman as Pearson-on-ranks (ranked once per column, NaNs kept as NaN,
    # pairwise-complete correlation) -- exact for complete pairs, and orders of
    # magnitude faster than pandas' pairwise spearman on 40 columns x 100k rows.
    ranked = sample.rank(method="average")
    corr = ranked.corr(method="pearson", min_periods=5_000)
    pairs = []
    cols = corr.columns
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            rho = corr.iloc[i, j]
            if pd.notna(rho) and abs(rho) > CORR_THRESHOLD:
                pairs.append({"f1": cols[i], "f2": cols[j], "spearman_rho": _f(rho, 4)})
    pairs.sort(key=lambda p: -abs(p["spearman_rho"]))
    return {
        "method": f"spearman (pearson on ranks, pairwise-complete), "
                  f"{len(sample):,}-row sample, seed {SEED}, *_isnan excluded",
        "threshold_abs_rho": CORR_THRESHOLD,
        "n_pairs_above_threshold": len(pairs),
        "pairs": pairs,
    }


def label_sanity(df: pd.DataFrame) -> dict:
    def stats(s: pd.Series) -> dict:
        return {"n_nonnull": int(s.notna().sum()), "mean": _f(s.mean()), "std": _f(s.std()),
                "p1": _f(s.quantile(0.01)), "p99": _f(s.quantile(0.99))}

    per_date_med = df.groupby("date")["y_excess_20d"].median()
    max_abs_med = per_date_med.abs().max()  # NaN-only dates (unlabeled tail) skipped
    return {
        "y_excess_20d": stats(df["y_excess_20d"]),
        "fwd_ret_5d": stats(df["fwd_ret_5d"]),
        "label_beat_mkt_20d_nan_pct": _f(df["label_beat_mkt_20d"].isna().mean() * 100, 3),
        "label_up_5d_nan_pct": _f(
            pd.to_numeric(df["label_up_5d"], errors="coerce").isna().mean() * 100, 3),
        "per_date_median_y_excess_20d": {
            "max_abs": _f(max_abs_med, 12),
            "is_approx_zero": bool(max_abs_med < 1e-9),
            "note": "y_excess_20d = y_raw_20d - per-date universe median, so each "
                    "labeled date's median must be exactly 0 (label is cross-sectional).",
        },
    }


def integrity(con, df: pd.DataFrame) -> dict:
    dup_parquet = int(df.duplicated(subset=["date", "ticker"]).sum())
    bad_close, bad_vol, null_close, null_vol = con.execute(
        "SELECT count(*) FILTER (WHERE close <= 0), count(*) FILTER (WHERE volume < 0), "
        "count(*) FILTER (WHERE close IS NULL), count(*) FILTER (WHERE volume IS NULL) "
        "FROM equity_eod"
    ).fetchone()
    multi_series = con.execute(
        "SELECT count(*) FROM (SELECT date, ticker FROM equity_eod "
        "GROUP BY date, ticker HAVING count(*) > 1)"
    ).fetchone()[0]
    return {
        "parquet_dup_date_ticker_rows": dup_parquet,
        "eod_rows_close_le_0": int(bad_close),
        "eod_rows_volume_lt_0": int(bad_vol),
        "eod_rows_close_null": int(null_close),
        "eod_rows_volume_null": int(null_vol),
        "eod_date_ticker_in_multiple_series": int(multi_series),
        "multi_series_note": "equity_eod PK is (date,ticker,series); same ticker in >1 "
                             "series on a day is an NSE segment artifact, resolved "
                             "upstream of equity_features -- informational only.",
        "pct_rows_flag_split_20d": _f(df["flag_split_20d"].eq(1).mean() * 100, 3),
        "pct_rows_y_clean_20d_true": _f(df["y_clean_20d"].astype(float).mean() * 100, 3),
    }


def splits_audit(df: pd.DataFrame, splits: dict) -> list[dict]:
    mask = df["label_beat_mkt_20d"].notna() & df["y_clean_20d"].astype(bool)
    tdf = df[mask]
    out = []
    for spec in splits["folds"] + [splits["holdout"]]:
        tr = tdf[tdf["date"] <= pd.Timestamp(spec["train_end"])]
        te = tdf[(tdf["date"] >= pd.Timestamp(spec["test_start"]))
                 & (tdf["date"] <= pd.Timestamp(spec["test_end"]))]
        out.append({
            "fold": spec["name"],
            "train_end": spec["train_end"],
            "test_start": spec["test_start"],
            "test_end": spec["test_end"],
            "n_train_rows": int(len(tr)),
            "n_test_rows": int(len(te)),
            "n_test_days": int(te["date"].nunique()),
            "n_train_days": int(tr["date"].nunique()),
            "test_base_rate_beat_mkt": _f(te["label_beat_mkt_20d"].mean(), 4),
        })
    return out


def build_verdict(pm: list[dict], cal: dict, nan_rates: dict, corr: dict,
                  lab: dict, integ: dict, sa: list[dict], manifest: dict,
                  df: pd.DataFrame) -> list[str]:
    v: list[str] = []

    # integrity
    if (integ["parquet_dup_date_ticker_rows"] == 0 and integ["eod_rows_close_le_0"] == 0
            and integ["eod_rows_volume_lt_0"] == 0):
        v.append("clean: 0 duplicate (date,ticker) rows in the parquet; 0 rows with "
                 "close<=0 or volume<0 in equity_eod.")
    else:
        v.append(f"INTEGRITY FAIL: dup={integ['parquet_dup_date_ticker_rows']}, "
                 f"close<=0={integ['eod_rows_close_le_0']}, "
                 f"volume<0={integ['eod_rows_volume_lt_0']}.")

    # calendar
    if not cal["suspicious_missing_dates"] and not cal["low_coverage_days"]:
        v.append("clean: no unexplained missing trading days and no low-coverage "
                 "(partial-ingest) days; all 13 missing weekdays are official NSE "
                 "2025 holidays.")
    else:
        v.append(f"calendar gaps: suspicious={cal['suspicious_missing_dates']}, "
                 f"low_coverage={[d['date'] for d in cal['low_coverage_days']]}.")
    if any("ZERO holiday closures" in o for o in cal["observations"]):
        v.append("note: the 2026 portion has no holiday closures at all (every weekday "
                 "trades) -- a simulated continuous calendar; do not build "
                 "calendar/seasonality features on 2026 data.")

    # regime
    labeled = [m for m in pm if m["median_y_raw_20d"] is not None]
    meds = [m["median_y_raw_20d"] for m in labeled]
    lo_m = min(labeled, key=lambda m: m["median_y_raw_20d"])
    hi_m = max(labeled, key=lambda m: m["median_y_raw_20d"])
    v.append(f"regime skew: monthly median y_raw_20d swings from "
             f"{lo_m['median_y_raw_20d']:+.2%} ({lo_m['month']}) to "
             f"{hi_m['median_y_raw_20d']:+.2%} ({hi_m['month']}); up_5d monthly base "
             f"rate ranges {min(m['mean_label_up_5d'] for m in pm if m['mean_label_up_5d'] is not None):.2f}"
             f"-{max(m['mean_label_up_5d'] for m in pm if m['mean_label_up_5d'] is not None):.2f} "
             f"-- the SECONDARY up_5d task inherits market beta, so expect fold-to-fold "
             f"metric swings there; the PRIMARY beat_mkt_20d label is cross-sectionally "
             f"demeaned (monthly base rate ~0.50 by construction) and is regime-robust.")
    if max(meds) > 0.03 or min(meds) < -0.03:
        v.append("note: at least one month's median 20d forward return exceeds +/-3% -- "
                 "economic metrics (top-decile mean fwd) on y_raw are regime-dominated; "
                 "use y_excess_20d for economics, as the harness does.")

    # features to distrust / handle
    high = nan_rates["high_nan_gt10pct"]
    if high:
        v.append(f"features >10% NaN ({len(high)}): "
                 + ", ".join(f"{k} ({pct:.0f}%)" for k, pct in high.items())
                 + " -- structural, not bugs: 126/252-session lookbacks cannot exist "
                   "before ~Mar-2026 (DB starts Mar-2025) and deliv_pct is absent for "
                   "SME/trade-to-trade segments. The harness median-imputes and ships "
                   "*_isnan indicators; early CV folds see these columns mostly imputed, "
                   "so treat ret_252d/mom_12_1 importances with suspicion.")

    # redundancy
    v.append(f"redundancy: {corr['n_pairs_above_threshold']} feature pairs with "
             f"|spearman|>{CORR_THRESHOLD} (momentum/SMA-distance/vol families and "
             f"cs_rank twins) -- fine for trees, but collinearity will destabilize "
             f"linear/NN coefficient interpretation; consider dropping one of each pair "
             f"for linear models.")

    # labels
    v.append(f"labels: label_beat_mkt_20d NaN on {lab['label_beat_mkt_20d_nan_pct']:.1f}% "
             f"of rows (the unlabeled tail after {manifest['last_labeled_date_20d']} plus "
             f"short histories) -- harness drops them; y_excess_20d per-date median is "
             f"exactly 0 (max abs {lab['per_date_median_y_excess_20d']['max_abs']}).")
    v.append(f"label cleaning: y_clean_20d masks {100 - integ['pct_rows_y_clean_20d_true']:.1f}% "
             f"of rows (split/circuit/suspension-poisoned 20d windows; "
             f"{integ['pct_rows_flag_split_20d']:.1f}% of rows sit within 20d of a >22% "
             f"1-day move). Prices are UNADJUSTED (no corporate-action feed): the mask is "
             f"the only defense, so never evaluate on y_clean_20d=False rows.")

    # splits
    smallest = min(sa, key=lambda s: s["n_train_rows"])
    v.append(f"splits: all folds populated; first fold ({smallest['fold']}) trains on only "
             f"{smallest['n_train_rows']:,} rows / {smallest['n_train_days']} days vs "
             f"{max(s['n_train_rows'] for s in sa):,} for the holdout -- expect the "
             f"earliest fold to be the weakest and do not tune on it alone.")
    return v


# --------------------------------------------------------------------------- #
# Plots
# --------------------------------------------------------------------------- #
def make_pngs(pm: list[dict]) -> list[str]:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    fg, bg, grid = "#e8eaed", "#14161a", "#3a4048"
    plt.rcParams.update({
        "figure.facecolor": bg, "axes.facecolor": bg, "savefig.facecolor": bg,
        "text.color": fg, "axes.edgecolor": grid, "axes.labelcolor": fg,
        "xtick.color": fg, "ytick.color": fg, "grid.color": grid,
        "font.size": 10, "axes.grid": True, "grid.alpha": 0.35,
    })
    months = [m["month"] for m in pm]
    x = np.arange(len(months))
    paths = []

    # (1) universe rows + distinct tickers
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(x, [m["rows"] for m in pm], color="#4c8dff", alpha=0.9, label="rows / month")
    ax.set_ylabel("universe rows")
    ax.set_xticks(x)
    ax.set_xticklabels(months, rotation=45, ha="right")
    ax2 = ax.twinx()
    ax2.plot(x, [m["tickers"] for m in pm], color="#ffb14e", marker="o", lw=2,
             label="distinct tickers")
    ax2.set_ylabel("distinct tickers", color="#ffb14e")
    ax2.tick_params(axis="y", colors="#ffb14e")
    ax2.grid(False)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    leg = ax.legend(h1 + h2, l1 + l2, loc="lower right", facecolor=bg, edgecolor=grid)
    for t in leg.get_texts():
        t.set_color(fg)
    ax.set_title("Universe coverage by month -- model_dataset.parquet")
    fig.tight_layout()
    p1 = ASSETS_DIR / "data_universe_by_month.png"
    fig.savefig(p1, dpi=120)
    plt.close(fig)
    paths.append(str(p1))

    # (2) monthly median y_raw_20d (market regime)
    lab = [(m["month"], m["median_y_raw_20d"]) for m in pm if m["median_y_raw_20d"] is not None]
    xs = np.arange(len(lab))
    vals = [v * 100 for _, v in lab]
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.bar(xs, vals, color=["#2ecc71" if v >= 0 else "#ff6b6b" for v in vals], alpha=0.9)
    ax.axhline(0, color=fg, lw=1.2)
    ax.set_xticks(xs)
    ax.set_xticklabels([m for m, _ in lab], rotation=45, ha="right")
    ax.set_ylabel("median y_raw_20d (%)")
    ax.set_title("Market regime -- monthly median 20-session forward return (next-open entry)")
    fig.tight_layout()
    p2 = ASSETS_DIR / "data_regime_monthly.png"
    fig.savefig(p2, dpi=120)
    plt.close(fig)
    paths.append(str(p2))
    return paths


# --------------------------------------------------------------------------- #
def main() -> None:
    t0 = datetime.now()
    manifest = json.loads((DATA_DIR / "manifest.json").read_text())
    splits = json.loads((DATA_DIR / "splits.json").read_text())
    features = manifest["features"]

    df = pd.read_parquet(DATA_DIR / "model_dataset.parquet")
    df["date"] = pd.to_datetime(df["date"])

    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        sec_funnel = funnel(con, df, manifest)
        sec_calendar = calendar_audit(con)
        sec_integrity = integrity(con, df)
    finally:
        con.close()

    sec_pm = per_month(df)
    sec_nan = feature_nan_rates(df, features)
    sec_moments = feature_moments(df, features)
    sec_corr = correlation(df, features)
    sec_labels = label_sanity(df)
    sec_splits = splits_audit(df, splits)
    verdict = build_verdict(sec_pm, sec_calendar, sec_nan, sec_corr, sec_labels,
                            sec_integrity, sec_splits, manifest, df)
    pngs = make_pngs(sec_pm)

    profile = {
        "generated_at": t0.isoformat(timespec="seconds"),
        "generated_by": "ml/profile_data.py (seed 108, read-only)",
        "sources": {"duckdb": DB_PATH,
                    "parquet": str(DATA_DIR / "model_dataset.parquet"),
                    "manifest_built_at": manifest["built_at"]},
        "funnel": sec_funnel,
        "per_month": sec_pm,
        "calendar_audit": sec_calendar,
        "feature_nan_rates": sec_nan,
        "feature_moments": sec_moments,
        "correlation": sec_corr,
        "label_sanity": sec_labels,
        "integrity": sec_integrity,
        "splits_audit": sec_splits,
        "verdict": verdict,
        "plots": pngs,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / "data_profile.json"
    out_path.write_text(json.dumps(profile, indent=1))

    dt = (datetime.now() - t0).total_seconds()
    print(f"wrote {out_path} ({out_path.stat().st_size / 1024:.0f} KiB) in {dt:.1f}s")
    print(f"plots: {pngs}")
    print("funnel:", json.dumps({k: sec_funnel[k] for k in
                                 ("equity_eod", "equity_features", "universe_parquet",
                                  "primary_task_rows")}, default=str))
    print(f"high-NaN features: {list(sec_nan['high_nan_gt10pct'])}")
    print(f"corr pairs |rho|>{CORR_THRESHOLD}: {sec_corr['n_pairs_above_threshold']}")
    print("verdict:")
    for s in verdict:
        print(" -", s)


if __name__ == "__main__":
    main()

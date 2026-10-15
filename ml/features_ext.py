#!/usr/bin/env python3
"""Extended leak-safe feature set for the SuryaDhana A/B (quant-fe agent).

Builds ``ml/data/model_dataset_fe.parquet`` = every column of
``ml/data/model_dataset.parquet`` unchanged (same 507,163 rows, same
(date, ticker) order) PLUS 23 new engineered features, and
``ml/data/manifest_fe.json`` describing them. The lead A/Bs the new set
through the frozen harness; nothing here touches ml/data.py, the original
parquet, or any result file.

Conventions mirrored from ml/data.py / nse_historical_ingest.build_features
---------------------------------------------------------------------------
* per-ticker time series are computed on DuckDB ``equity_eod`` rows with
  ``series IN ('EQ','BE')`` -- exactly the rows ``equity_features`` was built
  from (EQ-only would orphan 10,284 dataset rows of series migrators and 4
  BE-only tickers) -- sorted (ticker, date), prices unadjusted (the repo's
  ca_csv=None convention), then joined back on (date, ticker);
* cross-sectional pieces are computed per date over the dataset's universe
  rows only (same convention as the existing cs_rank_* columns);
* seed 108 everywhere; DuckDB is opened read-only.

LEAK-SAFETY (hard rules, enforced in code)
------------------------------------------
* every feature at date t uses only data of date <= t: shift(+k)/rolling on
  past values; same-day EOD prints (OHLC/volume/delivery) are allowed, the
  same convention as every existing feature (labels enter at the NEXT open);
* no ``fwd_*`` / ``y_*`` / ``label_*`` column can enter feature math: all
  cross-sectional construction runs on a frame from which the label columns
  have been dropped (asserted), per-ticker construction sees equity_eod only;
* market-state features are same-date aggregates of backward-looking
  per-name values over the date-t universe -- same value for all names;
* automated truncation check: for 5 random tickers (seed 108), 3 per-ticker
  features are recomputed at an interior date from ONLY data <= that date
  and asserted equal to the stored values;
* CALENDAR GUARD: no calendar/seasonality features are built -- the 2026
  archive calendar is simulated (documented limitation).

The ``quick_ic`` block in the manifest DOES read y_excess_20d / y_clean_20d.
That is reporting only (per-date mean Spearman IC, computed after the
features are fully built) -- labels never feed any feature, and quick_ic is
not used for selection; the lead runs the real harness A/B.

Run: ``cd /home/user/SuryaDhana_AI && python3 -m ml.features_ext``
"""
from __future__ import annotations

import json
import os
import time

os.environ.setdefault("OMP_NUM_THREADS", "2")

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
DATA_DIR = Path(__file__).resolve().parent / "data"
DB_PATH = REPO / "nse_market.duckdb"
SEED = 108
EXPECTED_ROWS = 507_163

ID_COLS = ["date", "ticker"]
LABEL_COLS = [
    "fwd_ret_5d", "label_up_5d",
    "y_raw_20d", "y_excess_20d", "y_rank_20d", "label_beat_mkt_20d",
    "y_clean_20d",
]
FORBIDDEN_PREFIXES = ("fwd_", "y_", "label_")

GROUPS = {
    "A_rank_layer": [
        "cs_rank_atr", "cs_rank_deliv_sma", "cs_rank_52wh",
        "cs_rank_rsi14", "cs_rank_ret63", "cs_rank_mom121",
    ],
    "B_momentum_quality": ["sharpe_mom_126", "upday_frac_63", "mom_consistency"],
    "C_delivery_dynamics": ["deliv_z_chg_5", "deliv_surge", "deliv_value_z"],
    "D_interactions": ["ix_deliv_mom", "ix_vol_mom", "ix_52wh_mom"],
    "E_residual_reversal": ["rev_resid_20"],
    "F_market_state": ["mkt_ret_20", "mkt_breadth_200", "mkt_vol_20", "corr_mkt_60"],
    "G_structure": ["sessions_since_52w_high", "accum_20", "days_listed"],
}
NEW_FEATURES = [f for feats in GROUPS.values() for f in feats]

# per-date percentile ranks over the universe: source -> new column
RANK_LAYER = [
    ("atr_pct", "cs_rank_atr"),
    ("deliv_pct_sma_20", "cs_rank_deliv_sma"),
    ("dist_52w_high", "cs_rank_52wh"),
    ("rsi_14", "cs_rank_rsi14"),
    ("ret_63d", "cs_rank_ret63"),
    ("mom_12_1", "cs_rank_mom121"),
    # log_turnover -> cs_rank_turnover already exists in the dataset: skipped
]

PER_TICKER_FEATURES = [
    "upday_frac_63", "mom_consistency", "deliv_z_chg_5",
    "sessions_since_52w_high", "accum_20", "days_listed",
]
LEAK_CHECK_FEATURES = ["upday_frac_63", "sessions_since_52w_high", "deliv_z_chg_5"]


# ========================================================================= #
# per-ticker time-series features (strictly backward-looking)
# ========================================================================= #

def _sessions_since_high(h: np.ndarray, window: int = 252,
                         min_sessions: int = 60) -> np.ndarray:
    """Sessions since the most recent occurrence of the trailing-``window``
    max high (0 = today printed the max). Capped at ``window``-1 by
    construction; NaN until ``min_sessions`` sessions of history exist."""
    n = h.size
    if n == 0:
        return np.full(0, np.nan)
    hv = np.where(np.isfinite(h), h, -np.inf)
    padded = np.concatenate([np.full(window - 1, -np.inf), hv])
    sw = np.lib.stride_tricks.sliding_window_view(padded, window)  # ends at i
    since = sw[:, ::-1].argmax(axis=1).astype(float)  # last occurrence of max
    since[~np.isfinite(sw).any(axis=1)] = np.nan
    since[np.arange(n) + 1 < min_sessions] = np.nan
    return since


def _per_ticker_features(eod: pd.DataFrame) -> pd.DataFrame:
    """All per-ticker rolling/shift features on equity_eod EQ+BE rows.

    Works on any subset of tickers/dates (used both for the full build and
    for the truncated-history leak check). Only shift(+k)/rolling on PAST
    values plus same-day EOD prints -- nothing forward-looking.
    """
    df = eod.sort_values(["ticker", "date"]).reset_index(drop=True).copy()
    gb = df.groupby("ticker", group_keys=False)

    # daily return (mirrors build_features' ret_1d)
    df["_ret_1d"] = gb["close"].pct_change()

    # --- B: fraction of up days over the last 63 sessions ------------------
    df["_up"] = pd.Series(
        np.where(df["_ret_1d"].notna(), (df["_ret_1d"] > 0).astype(float), np.nan),
        index=df.index)
    df["upday_frac_63"] = df.groupby("ticker", group_keys=False)["_up"].transform(
        lambda s: s.rolling(63, min_periods=40).mean())

    # --- B: momentum consistency over 6 non-overlapping trailing 21d blocks
    # fraction of block returns whose sign matches the 126d total's sign
    gclose = df.groupby("ticker", group_keys=False)["close"]
    sh = {k: gclose.shift(21 * k) for k in range(7)}
    total = sh[0] / sh[6] - 1.0
    total_up = (total > 0)
    bad = total.isna().to_numpy().copy()
    agree = np.zeros(len(df))
    for k in range(6):
        rk = sh[k] / sh[k + 1] - 1.0
        bad |= rk.isna().to_numpy()
        agree += ((rk > 0) == total_up).to_numpy().astype(float)
    mc = agree / 6.0
    mc[bad] = np.nan
    df["mom_consistency"] = mc

    # --- C: delivery z (exact build_features formula) and 5-session change -
    dsma = gb["deliv_pct"].transform(lambda s: s.rolling(20).mean())
    dstd = gb["deliv_pct"].transform(lambda s: s.rolling(20).std())
    df["_deliv_z"] = (df["deliv_pct"] - dsma) / dstd
    df["deliv_z_chg_5"] = (
        df["_deliv_z"] - df.groupby("ticker", group_keys=False)["_deliv_z"].shift(5))

    # --- G: structure -------------------------------------------------------
    df["sessions_since_52w_high"] = df.groupby("ticker", group_keys=False)[
        "high"].transform(lambda s: _sessions_since_high(s.to_numpy(dtype=float)))
    df["_cpr"] = (df["close"] - df["low"]) / (df["high"] - df["low"]).replace(0, np.nan)
    df["accum_20"] = df.groupby("ticker", group_keys=False)["_cpr"].transform(
        lambda s: s.rolling(20, min_periods=15).mean())
    df["days_listed"] = np.log1p(df.groupby("ticker").cumcount() + 1)

    # same-day ingredient for the cross-sectional deliv_value_z
    df["_deliv_value_raw"] = np.log1p(df["deliv_qty"].astype("float64") * df["close"])

    return df[ID_COLS + PER_TICKER_FEATURES
              + ["_ret_1d", "_deliv_z", "_deliv_value_raw"]]


def _load_eod() -> pd.DataFrame:
    import duckdb
    con = duckdb.connect(str(DB_PATH), read_only=True)
    eod = con.execute(
        """
        SELECT date, ticker, open, high, low, close, volume, turnover,
               deliv_qty, deliv_pct
        FROM equity_eod
        WHERE series IN ('EQ','BE')
        ORDER BY ticker, date
        """
    ).df()
    con.close()
    eod["date"] = pd.to_datetime(eod["date"])
    assert not eod.duplicated(ID_COLS).any(), "duplicate (date,ticker) in EQ/BE pull"
    return eod


# ========================================================================= #
# cross-sectional / market-state pieces (per date t, universe rows only)
# ========================================================================= #

def _rev_resid_20(base: pd.DataFrame, min_names: int = 100) -> np.ndarray:
    """Per-date OLS residual of mom_20 on [1, mom_12_1, ret_126d.fillna(1)].

    Rows need mom_20 and mom_12_1 present; dates with < min_names such rows
    stay NaN. The residual is the pure short-term reversal component."""
    y = base["mom_20"].to_numpy(dtype=float)
    x1 = base["mom_12_1"].to_numpy(dtype=float)
    x2raw = base["ret_126d"].to_numpy(dtype=float)
    x2 = np.where(np.isnan(x2raw), 1.0, x2raw)  # "(1-filled)" per spec
    res = np.full(len(base), np.nan)
    for _, idx in base.groupby("date").indices.items():
        yi, x1i, x2i = y[idx], x1[idx], x2[idx]
        m = np.isfinite(yi) & np.isfinite(x1i)
        n = int(m.sum())
        if n < min_names:
            continue
        X = np.column_stack([np.ones(n), x1i[m], x2i[m]])
        beta, *_ = np.linalg.lstsq(X, yi[m], rcond=None)
        res[idx[m]] = yi[m] - X @ beta
    return res


def _corr_mkt_60(base: pd.DataFrame, pt: pd.DataFrame, mi: pd.MultiIndex,
                 window: int = 60, min_periods: int = 40) -> np.ndarray:
    """Rolling 60-session correlation of each ticker's ret_1d with the
    per-date universe median ret_1d (beta proxy). The market series is the
    median over the dataset's universe rows per date; the ticker series is
    its equity_eod daily return on dataset dates. Pairwise-NaN deletion,
    min 40 common sessions. Everything at date t uses dates <= t only."""
    mkt = base.groupby("date")["ret_1d"].median()  # one value per dataset date
    dates = mkt.index
    tickers = pd.Index(np.sort(base["ticker"].unique()))
    r = pt[pt["date"].isin(set(dates)) & pt["ticker"].isin(set(tickers))]
    wide = (r.pivot(index="date", columns="ticker", values="_ret_1d")
             .reindex(index=dates, columns=tickers))
    mcol = pd.DataFrame(
        np.broadcast_to(mkt.to_numpy()[:, None], wide.shape),
        index=dates, columns=tickers).where(wide.notna())

    def roll(d: pd.DataFrame) -> pd.DataFrame:
        return d.rolling(window, min_periods=min_periods).mean()

    mx, mm = roll(wide), roll(mcol)
    cov = roll(wide * mcol) - mx * mm
    vx = roll(wide * wide) - mx ** 2
    vm = roll(mcol * mcol) - mm ** 2
    corr = (cov / np.sqrt(vx * vm)).where((vx > 1e-18) & (vm > 1e-18))
    corr = corr.clip(-1.0, 1.0)
    ser = corr.stack()
    ser.index.names = ["date", "ticker"]
    return ser.reindex(mi).to_numpy(dtype=float)


# ========================================================================= #
# checks & reporting
# ========================================================================= #

def _leak_check(out: pd.DataFrame, eod: pd.DataFrame) -> dict:
    """For 5 random tickers (seed 108) recompute 3 per-ticker features at an
    interior date from ONLY data <= that date; assert equality with stored."""
    rng = np.random.default_rng(SEED)
    cnt = out.groupby("ticker")["date"].transform("size")
    posf = out.groupby("ticker").cumcount() / cnt
    okall = out[LEAK_CHECK_FEATURES].notna().all(axis=1)
    interior = okall & (posf >= 0.6) & (posf <= 0.95) & (cnt >= 120)
    elig = np.sort(out.loc[interior, "ticker"].unique())
    assert len(elig) >= 5, "not enough eligible tickers for the leak check"
    picks = rng.choice(elig, size=5, replace=False)

    cases = []
    for tk in picks:
        cand = out[(out["ticker"] == tk) & interior]
        row = cand.iloc[0]
        t = row["date"]
        stored = row[LEAK_CHECK_FEATURES].to_numpy(dtype=float)
        trunc = eod[(eod["ticker"] == tk) & (eod["date"] <= t)]
        re_pt = _per_ticker_features(trunc)
        rerow = re_pt[re_pt["date"] == t]
        assert len(rerow) == 1, f"no unique eod row for {tk} @ {t}"
        recomputed = rerow.iloc[0][LEAK_CHECK_FEATURES].to_numpy(dtype=float)
        match = bool(np.allclose(stored, recomputed, rtol=1e-9, atol=1e-10,
                                 equal_nan=True))
        cases.append({
            "ticker": str(tk), "date": str(pd.Timestamp(t).date()),
            "stored": {f: float(stored[j]) for j, f in enumerate(LEAK_CHECK_FEATURES)},
            "recomputed_leq_date": {f: float(recomputed[j])
                                    for j, f in enumerate(LEAK_CHECK_FEATURES)},
            "match": match,
        })
        assert match, (f"LEAK CHECK FAILED {tk} @ {t}: "
                       f"stored={stored} recomputed={recomputed}")
    return {"passed": True, "seed": SEED, "n_tickers": 5,
            "features_checked": LEAK_CHECK_FEATURES, "cases": cases}


def _closest_existing(out: pd.DataFrame, existing: list[str],
                      sample_n: int = 100_000) -> tuple[dict, list]:
    """Spearman of each new feature against every existing (non-isnan)
    feature on a 100k-row sample (seed 108); report the closest and flag
    |rho| > 0.95 as redundant (kept, but noted)."""
    samp = out.sample(n=min(sample_n, len(out)), random_state=SEED)
    closest, flags = {}, []
    for f in NEW_FEATURES:
        xs = samp[f]
        best_rho, best_name = np.nan, None
        if xs.notna().sum() >= 100 and xs.nunique() > 1:
            for e in existing:
                rho = xs.corr(samp[e], method="spearman")
                if pd.notna(rho) and (pd.isna(best_rho) or abs(rho) > abs(best_rho)):
                    best_rho, best_name = float(rho), e
        closest[f] = {"closest_existing": best_name,
                      "spearman": None if pd.isna(best_rho) else round(best_rho, 4)}
        if pd.notna(best_rho) and abs(best_rho) > 0.95:
            flags.append({"feature": f, "existing": best_name,
                          "spearman": round(best_rho, 4)})
    return closest, flags


def _quick_ic(out: pd.DataFrame) -> dict:
    """REPORTING ONLY (reads the label): per-date Spearman IC of each new
    feature vs y_excess_20d on rows where y_clean_20d, mean over dates with
    >= 50 valid pairs. Market-state features are constant within a date, so
    their cross-sectional IC is undefined (null)."""
    from scipy.stats import spearmanr
    mask = (out["y_clean_20d"].to_numpy().astype(bool)
            & out["y_excess_20d"].notna().to_numpy())
    sub = out.loc[mask, ["date", "y_excess_20d"] + NEW_FEATURES].reset_index(drop=True)
    y = sub["y_excess_20d"].to_numpy(dtype=float)
    idxmap = sub.groupby("date").indices
    ics = {}
    for f in NEW_FEATURES:
        x = sub[f].to_numpy(dtype=float)
        vals = []
        for _, idx in idxmap.items():
            xi, yi = x[idx], y[idx]
            m = np.isfinite(xi) & np.isfinite(yi)
            if int(m.sum()) < 50 or np.unique(xi[m]).size < 2:
                continue
            res = spearmanr(xi[m], yi[m])
            rho = float(getattr(res, "statistic", getattr(res, "correlation", np.nan)))
            if np.isfinite(rho):
                vals.append(rho)
        ics[f] = {"mean_ic": round(float(np.mean(vals)), 5) if vals else None,
                  "n_dates": len(vals)}
    return ics


# ========================================================================= #
# build
# ========================================================================= #

def build_extended() -> dict:
    t0 = time.perf_counter()
    for f in NEW_FEATURES:
        assert not f.startswith(FORBIDDEN_PREFIXES)

    ds = pd.read_parquet(DATA_DIR / "model_dataset.parquet")
    assert len(ds) == EXPECTED_ROWS, f"unexpected dataset rows: {len(ds)}"
    assert not set(NEW_FEATURES) & set(ds.columns), "new-feature name collision"

    # label guard: construction only ever sees `base` (labels dropped) + eod
    base = ds.drop(columns=LABEL_COLS).copy()
    for c in base.columns:
        assert not c.startswith(FORBIDDEN_PREFIXES), f"label column leaked: {c}"
    print(f"dataset: {len(ds):,} rows x {ds.shape[1]} cols; "
          f"construction inputs carry no fwd_*/y_*/label_* columns")

    eod = _load_eod()
    print(f"equity_eod EQ+BE: {len(eod):,} rows, {eod['ticker'].nunique():,} tickers "
          f"({eod['date'].min().date()} - {eod['date'].max().date()})")

    pt = _per_ticker_features(eod)
    pts = pt.set_index(ID_COLS)
    assert pts.index.is_unique
    mi = pd.MultiIndex.from_arrays([base["date"], base["ticker"]])
    joined = {c: pts[c].reindex(mi).to_numpy(dtype=float) for c in pts.columns}

    # consistency guard: the recomputed per-ticker series must reproduce the
    # stored dataset columns (proves identical raw series + conventions)
    r_re, r_ds = joined["_ret_1d"], base["ret_1d"].to_numpy(dtype=float)
    mboth = np.isfinite(r_re) & np.isfinite(r_ds)
    max_d_ret = float(np.max(np.abs(r_re[mboth] - r_ds[mboth])))
    z_re, z_ds = joined["_deliv_z"], base["deliv_pct_z_20"].to_numpy(dtype=float)
    mz = np.isfinite(z_re) & np.isfinite(z_ds)
    max_d_z = float(np.max(np.abs(z_re[mz] - z_ds[mz])))
    print(f"consistency vs stored dataset: max|d ret_1d|={max_d_ret:.2e} "
          f"(n={int(mboth.sum()):,}), max|d deliv_pct_z_20|={max_d_z:.2e} "
          f"(n={int(mz.sum()):,})")
    assert max_d_ret < 1e-8 and max_d_z < 1e-8, "equity_eod/dataset mismatch"

    new: dict[str, np.ndarray | pd.Series] = {}
    gdate = base.groupby("date")

    # --- A: rank layer ------------------------------------------------------
    for src, dst in RANK_LAYER:
        new[dst] = gdate[src].rank(pct=True)

    # --- B: momentum quality ------------------------------------------------
    sharpe = base["ret_126d"] / (base["vol_20"] * np.sqrt(126.0))
    new["sharpe_mom_126"] = sharpe.replace([np.inf, -np.inf], np.nan)
    new["upday_frac_63"] = joined["upday_frac_63"]
    new["mom_consistency"] = joined["mom_consistency"]

    # --- C: delivery dynamics ----------------------------------------------
    new["deliv_z_chg_5"] = joined["deliv_z_chg_5"]
    new["deliv_surge"] = base["deliv_pct_z_20"] * base["vol_z_20"]
    dv = pd.Series(joined["_deliv_value_raw"], index=base.index)
    new["deliv_value_z"] = ((dv - dv.groupby(base["date"]).transform("mean"))
                            / dv.groupby(base["date"]).transform("std"))

    # --- D: interactions ----------------------------------------------------
    new["ix_deliv_mom"] = new["cs_rank_deliv_sma"] * new["cs_rank_mom121"]
    new["ix_vol_mom"] = (1.0 - base["cs_rank_vol_20"]) * new["cs_rank_mom121"]
    new["ix_52wh_mom"] = new["cs_rank_52wh"] * new["cs_rank_mom121"]

    # --- E: residual reversal ----------------------------------------------
    new["rev_resid_20"] = _rev_resid_20(base)

    # --- F: market state (same value for all names that date) ---------------
    new["mkt_ret_20"] = gdate["mom_20"].transform("median")
    above = pd.Series(
        np.where(base["dist_200dma"].notna(),
                 (base["dist_200dma"] > 0).astype(float), np.nan),
        index=base.index)
    new["mkt_breadth_200"] = above.groupby(base["date"]).transform("mean")
    new["mkt_vol_20"] = gdate["vol_20"].transform("median")
    new["corr_mkt_60"] = _corr_mkt_60(base, pt, mi)

    # --- G: structure -------------------------------------------------------
    new["sessions_since_52w_high"] = joined["sessions_since_52w_high"]
    new["accum_20"] = joined["accum_20"]
    new["days_listed"] = joined["days_listed"]

    # --- assemble: existing columns unchanged + new features appended -------
    out = ds.copy()
    for f in NEW_FEATURES:
        v = new[f]
        out[f] = np.asarray(v, dtype=float) if not isinstance(v, pd.Series) \
            else v.to_numpy(dtype=float)

    assert len(out) == EXPECTED_ROWS
    for c in ds.columns:
        assert out[c].equals(ds[c]), f"existing column changed: {c}"
    print(f"assembled: {len(out):,} rows x {out.shape[1]} cols "
          f"(existing {ds.shape[1]} all byte-identical; +{len(NEW_FEATURES)} new)")

    # --- automated leak-safety check ----------------------------------------
    leak = _leak_check(out, eod)
    print("leak check (truncate history at t, recompute, compare): PASSED "
          f"for {leak['n_tickers']} tickers x {leak['features_checked']}")

    # --- NaN audit -----------------------------------------------------------
    nan_pct = {f: round(float(out[f].isna().mean()) * 100, 2) for f in NEW_FEATURES}
    all_nan = [f for f, v in nan_pct.items() if v >= 100.0]
    assert not all_nan, f"NaN-only new feature(s): {all_nan}"
    high_nan = [f for f, v in nan_pct.items() if v > 40.0]
    print("\nNaN %% per new feature (flag >40%):")
    for f in NEW_FEATURES:
        flag = "  <-- FLAG >40%" if f in high_nan else ""
        print(f"  {f:<24s} {nan_pct[f]:6.2f}%{flag}")

    # --- redundancy vs existing features ------------------------------------
    man = json.loads((DATA_DIR / "manifest.json").read_text())
    existing = [c for c in man["features"] if not c.endswith("_isnan")]
    closest, red_flags = _closest_existing(out, existing)
    print("\nclosest existing feature (pooled Spearman, 100k sample, seed 108):")
    for f in NEW_FEATURES:
        c = closest[f]
        rho = c["spearman"]
        flag = "  <-- REDUNDANT |rho|>0.95 (kept, noted)" \
            if any(r["feature"] == f for r in red_flags) else ""
        print(f"  {f:<24s} vs {str(c['closest_existing']):<20s} "
              f"rho={rho if rho is not None else 'n/a'}{flag}")

    # --- quick univariate IC (REPORTING ONLY -- reads the label) -------------
    ics = _quick_ic(out)
    ranked = sorted((f for f in NEW_FEATURES if ics[f]["mean_ic"] is not None),
                    key=lambda f: -abs(ics[f]["mean_ic"]))
    print("\nquick_ic (per-date mean Spearman vs y_excess_20d on y_clean rows; "
          "reporting only, not selection):")
    for f in ranked:
        print(f"  {f:<24s} IC={ics[f]['mean_ic']:+.5f}  (n_dates={ics[f]['n_dates']})")
    const_feats = [f for f in NEW_FEATURES if ics[f]["mean_ic"] is None]
    if const_feats:
        print(f"  (no cross-sectional IC -- constant within date: {const_feats})")

    # --- write outputs -------------------------------------------------------
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out.to_parquet(DATA_DIR / "model_dataset_fe.parquet", index=False)

    manifest = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "builder": "ml/features_ext.py (quant-fe)",
        "source_dataset": "ml/data/model_dataset.parquet",
        "rows": int(len(out)),
        "tickers": int(out["ticker"].nunique()),
        "date_min": str(out["date"].min().date()),
        "date_max": str(out["date"].max().date()),
        "seed": SEED,
        "n_new_features": len(NEW_FEATURES),
        "new_features": NEW_FEATURES,
        "groups": GROUPS,
        "leak_safety_note": (
            "Every new feature at date t is strictly backward-looking: per-ticker "
            "features use only shift(+k)/rolling windows over PAST values of "
            "equity_eod EQ+BE rows (the exact rows equity_features was built from, "
            "unadjusted prices, sorted ticker/date; same-day EOD prints allowed, "
            "matching every existing feature -- labels enter at the NEXT open); "
            "cross-sectional pieces (ranks, per-date z, per-date OLS residual) are "
            "computed within date t over the dataset's universe rows only; "
            "market-state features are same-date aggregates of backward-looking "
            "per-name values (one value for all names that date); corr_mkt_60 uses "
            "a trailing 60-session window of past daily returns vs past universe "
            "median returns. No fwd_*/y_*/label_* column enters any computation -- "
            "label columns are dropped from the construction frame and asserted "
            "absent; the quick_ic block reads y_excess_20d/y_clean_20d for "
            "REPORTING ONLY, after the features are built. Automated truncation "
            "check passed: for 5 seed-108 tickers, upday_frac_63 / "
            "sessions_since_52w_high / deliv_z_chg_5 recomputed from only data <= "
            "an interior date equal the stored values. Calendar/seasonality "
            "features deliberately NOT built (2026 archive calendar is simulated "
            "-- documented limitation)."
        ),
        "leak_check": leak,
        "consistency_check": {
            "max_abs_diff_ret_1d_vs_dataset": max_d_ret,
            "max_abs_diff_deliv_pct_z_20_vs_dataset": max_d_z,
        },
        "nan_pct": nan_pct,
        "high_nan_flags_gt40pct": high_nan,
        "closest_existing_spearman": closest,
        "redundancy_flags_gt095": red_flags,
        "quick_ic": ics,
        "quick_ic_note": (
            "per-date mean Spearman IC vs y_excess_20d on rows where y_clean_20d, "
            "dates with >=50 valid pairs; READS THE LABEL -- reporting only, never "
            "used for construction or selection; the lead runs the real harness "
            "A/B. Market-state features are constant within a date (null IC)."
        ),
        "conventions": {
            "eod_source": ("equity_eod series IN ('EQ','BE'), read-only -- mirrors "
                           "nse_historical_ingest.build_features (EQ-only would "
                           "orphan 10,284 dataset rows); prices unadjusted "
                           "(ca_csv=None convention)"),
            "join": "per-ticker frame reindexed onto the dataset's (date,ticker); "
                    "row set and order identical to model_dataset.parquet",
            "min_periods": {"upday_frac_63": 40, "sessions_since_52w_high": 60,
                            "accum_20": 15, "corr_mkt_60": 40,
                            "rev_resid_20_min_names_per_date": 100},
            "mom_consistency": ("fraction of the 6 non-overlapping trailing 21d "
                                "block returns whose sign matches the sign of the "
                                "126d total return (0..1)"),
            "rev_resid_20": ("per-date OLS mom_20 ~ 1 + mom_12_1 + "
                             "ret_126d.fillna(1.0); residual for rows with mom_20 "
                             "and mom_12_1 present; NaN when <100 names that date"),
            "sharpe_mom_126": "ret_126d / (vol_20 * sqrt(126)); +-inf -> NaN",
            "deliv_value_z": "per-date cross-sectional z of log1p(deliv_qty*close)",
            "mkt_breadth_200": ("fraction of universe names with dist_200dma > 0, "
                                "among names with non-NaN dist_200dma"),
            "days_listed": "log1p(cumulative session count of the ticker in "
                           "equity_eod EQ/BE)",
            "sessions_since_52w_high": ("sessions since the most recent occurrence "
                                        "of the trailing-252-session max high; "
                                        "0 = today; capped at 251 by construction"),
            "nan_indicator_columns": ("none added for new features -- the champion "
                                      "(LightGBM) handles NaN natively; the "
                                      "existing *_isnan columns are untouched"),
        },
    }
    (DATA_DIR / "manifest_fe.json").write_text(json.dumps(manifest, indent=1))
    # ml/data/ is gitignored; the feature-study report reads this committed copy.
    study_dir = REPO / "ml" / "results" / "feature_study"
    study_dir.mkdir(parents=True, exist_ok=True)
    (study_dir / "manifest_fe.json").write_text(json.dumps(manifest, indent=1))

    print(f"\nwrote {DATA_DIR / 'model_dataset_fe.parquet'} "
          f"({len(out):,} rows x {out.shape[1]} cols)")
    print(f"wrote {DATA_DIR / 'manifest_fe.json'}")
    print(f"total {time.perf_counter() - t0:.1f}s")
    return manifest


if __name__ == "__main__":
    build_extended()

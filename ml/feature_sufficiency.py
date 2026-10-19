#!/usr/bin/env python3
"""Feature-sufficiency study for the SuryaDhana pilot (feature-sufficiency DS).

Management asked: "Is there scope for feature enhancement? Are the current
features sufficient? Do we need extra features?"  This module answers with
evidence, in five steps:

A. INFORMATION INVENTORY -- ten microstructure features from bhavcopy fields
   the pilot never reads (trades, vwap, last, CA-adjusted prev_close,
   delivery VALUE) or reads only in another form;
B. STRUCTURAL / RELATIVE -- 60-session rolling OLS of ret_1d on the universe-
   median return -> residual momentum (Blitz, Huij & Martens 2011),
   idiosyncratic vol and beta; a return-correlation SECTOR PROXY (KMeans,
   k=12) with cluster-relative momentum / delivery and cluster momentum
   (Moskowitz & Grinblatt 1999); cs_rank versions of the residual pair;
C. UNIQUE-INFORMATION TEST -- per-date Spearman IC vs y_excess_20d and the
   RESIDUAL IC after per-date OLS orthogonalization on the champion's 10
   features; monthly t-stats; Benjamini-Hochberg across the new features;
D. HARNESS A/B -- champion LightGBM config through ml.evaluation, primary
   task only, results under ml/results/feature_sufficiency/;
E/F. external-data gap list and verdict (FEATURE_SUFFICIENCY.md).

PRE-REGISTERED RULES (fixed in this docstring before any result existed)
-----------------------------------------------------------------------
* "carries new information": residual-IC Benjamini-Hochberg q <= 0.10 on the
  full labeled sample (monthly t-stat, two-sided);
* "worth adding": an A/B variant reaches CV AUC >= 0.5364 (= clean control
  lgbm_fs_selected_clean 0.5314 + 0.005, the ml/feature_ab.py pass mark)
  with every CV fold >= 0.50; holdout reported, never used to choose;
* "sufficient for this sample": no variant clears the A/B bar;
* variant (i) top-5 = best |residual monthly t| on labeled dates <= the
  holdout's train_end, so the selection never sees holdout labels.  It DOES
  see the CV test months' labels, which biases variant (i) UPWARD -- the
  conservative direction for a null verdict; reported, not hidden.

LEAK-SAFETY
-----------
* source = ml/data/equity_eod_snapshot.parquet, series EQ+BE (nse_market.duckdb
  is never opened).  Asserted: recomputed ret_1d equals the dataset's exactly
  and the replicated point-in-time universe equals the dataset's row set;
* per-ticker features use only shift(+k)/rolling over PAST rows plus same-day
  EOD prints (labels enter at the NEXT open).  Automated truncation check:
  5 seed-108 tickers x 5 features recomputed after truncating the WHOLE market
  at an interior date t (the market series is re-derived from data <= t) must
  equal the stored values;
* cross-sectional pieces are same-date operations over the date-t universe;
  the label columns are dropped from the construction frame (asserted);
* CLUSTERS are fit ONCE on the 120 sessions ending 2026-01-30 (last session
  <= 2026-01-31): point-in-time for every CV test fold (first test date
  2026-04-01) and the holdout.  For TRAINING rows dated before 2026-01-31 the
  grouping uses later co-movement (Aug-2025..Jan-2026): look-ahead in WHICH
  names are grouped, never in any test label.  Cluster-feature IC is also
  reported on the PIT-strict window (dates >= 2026-02-01).

Run: cd /home/user/SuryaDhana_AI && python3 -m ml.feature_sufficiency
     [--skip-build] [--skip-ab] [--report-only]
"""
from __future__ import annotations

import os

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")

import argparse
import json
import time
from datetime import datetime

import numpy as np
import pandas as pd

import ml.evaluation as ev
from ml.evaluation import run_standard_eval

ML_DIR = ev.ML_DIR
DATA_DIR = ev.DATA_DIR
OUT_DIR = ML_DIR / "results" / "feature_sufficiency"
PREDS_OUT = ML_DIR / "results" / "preds" / "feature_sufficiency"
# eval_aggregate globs ml/results/*.json as league entries -> own folders.
ev.RESULTS_DIR = OUT_DIR
ev.PREDS_DIR = PREDS_OUT

SNAPSHOT = DATA_DIR / "equity_eod_snapshot.parquet"
OUT_PARQUET = DATA_DIR / "model_dataset_suff.parquet"
EVIDENCE_JSON = OUT_DIR / "feature_sufficiency.json"
MANIFEST_JSON = OUT_DIR / "manifest_suff.json"
REPORT_MD = OUT_DIR / "FEATURE_SUFFICIENCY.md"

SEED = 108
EXPECTED_ROWS = 507_163
ID = ["date", "ticker"]
LABEL_COLS = ["fwd_ret_5d", "label_up_5d", "y_raw_20d", "y_excess_20d",
              "y_rank_20d", "label_beat_mkt_20d", "y_clean_20d"]
FORBIDDEN = ("fwd_", "y_", "label_")

# conventions mirrored from ml/data.py
MIN_PRICE, MIN_MED_TURNOVER = 10.0, 1e7
SPLIT_MOVE = 0.22             # |1d move| above this = CA / circuit artefact

GAP_MIN = 0.0025              # gap_fill only defined for |gap| >= 0.25%
GAP_FILL_CLIP = 3.0
REG_WIN, REG_MINP = 60, 40    # rolling market regression
RESID_SUM_WIN, RESID_SUM_MINP = 63, 45

CLUSTER_CUTOFF = pd.Timestamp("2026-01-31")
CLUSTER_WINDOW = 120
CLUSTER_MIN_OBS = 100
N_CLUSTERS = 12
CLUSTER_MIN_NAMES = 5
PIT_CLUSTER_START = "2026-02-01"

MIN_NAMES_IC = 100
BH_Q = 0.10
BOOT_B = 1000

CHAMPION = ["atr_pct", "deliv_pct_sma_20", "dist_52w_high", "ret_126d",
            "mom_12_1", "cs_rank_mom_20", "cs_rank_ret_126", "cs_rank_vol_20",
            "deliv_pct", "ret_63d"]
CONTROL_CLEAN_CV = 0.5314
PASS_MARK = 0.5364
FOLD_FLOOR = 0.50

MICRO = ["avg_trade_size_z", "ats_chg_20", "trades_z_20", "close_vs_vwap",
         "close_vs_vwap_5", "last_vs_close", "deliv_value_share_20",
         "gap_fill_10", "range_position_20", "amihud_20"]
RESID = ["resid_mom_63", "idio_vol_60", "beta_60",
         "cs_rank_resid_mom_63", "cs_rank_idio_vol_60"]
CLUSTER = ["cr_mom_20", "cr_ret_63", "cr_ret_126", "cr_mom_12_1",
           "cr_deliv_sma_20", "cr_deliv_pct", "cluster_mom_20", "cluster_ret_126"]
GROUPS = {"A_microstructure": MICRO, "B_residual_market_model": RESID,
          "B_cluster_sector_proxy": CLUSTER}
NEW_FEATURES = MICRO + RESID + CLUSTER
# per-date monotone transforms of each other -> identical Spearman statistics
RANK_EQUIV = {"cs_rank_resid_mom_63": "resid_mom_63",
              "cs_rank_idio_vol_60": "idio_vol_60"}
CLUSTER_REL = [("mom_20", "cr_mom_20"), ("ret_63d", "cr_ret_63"),
               ("ret_126d", "cr_ret_126"), ("mom_12_1", "cr_mom_12_1"),
               ("deliv_pct_sma_20", "cr_deliv_sma_20"), ("deliv_pct", "cr_deliv_pct")]
LEAK_CHECK_FEATURES = ["resid_mom_63", "idio_vol_60", "trades_z_20",
                       "gap_fill_10", "range_position_20"]

PILOT_OVERLAP = {
    "avg_trade_size_z": "none: `trades` is never read; nearest is size/liquidity (log_turnover)",
    "ats_chg_20": "none",
    "trades_z_20": "yes, in form: vol_z_20 is the same z-score on shares",
    "close_vs_vwap": "none: `vwap` is never read (close_pos_in_range uses the H-L range)",
    "close_vs_vwap_5": "none (5d mean of close_vs_vwap)",
    "last_vs_close": "none: `last` is never read",
    "deliv_value_share_20": "yes, in form: deliv_pct_sma_20 (quantity share); deliv_value_z (engineered)",
    "gap_fill_10": "partial: gap_pct is the 1-day gap size, never the retrace",
    "range_position_20": "yes, in form: close_pos_in_range (1d), accum_20 (engineered), dist_sma_20",
    "amihud_20": "partial: log_turnover / cs_rank_turnover with vol_20 (Amihud ~ vol/turnover)",
    "resid_mom_63": "partial: ret_63d is total, not idiosyncratic; rev_resid_20 (engineered) differs",
    "idio_vol_60": "partial: vol_20 / cs_rank_vol_20 / atr_pct are total vol",
    "beta_60": "partial: corr_mkt_60 (engineered) is correlation, not beta",
    "cs_rank_resid_mom_63": "rank-equivalent of resid_mom_63",
    "cs_rank_idio_vol_60": "rank-equivalent of idio_vol_60",
    "cr_mom_20": "none: the pilot has no sector information",
    "cr_ret_63": "none", "cr_ret_126": "none", "cr_mom_12_1": "none",
    "cr_deliv_sma_20": "none", "cr_deliv_pct": "none",
    "cluster_mom_20": "none (mkt_ret_20 is the whole-market analogue)",
    "cluster_ret_126": "none (added: 6-month industry momentum, Moskowitz-Grinblatt)",
}

EXTERNAL_DATA = [
    {"data": "Index and F&O membership (Nifty 50/100/500, F&O list, MWPL ban list)",
     "adds": "inclusion/exclusion demand shocks; F&O eligibility = short-sale feasibility",
     "mechanism": "index-demand price pressure (Shleifer 1986; Harris & Gurel 1986); overpricing persists where shorting is hard (Miller 1977): non-F&O NSE names cannot be shorted overnight except through SLB",
     "source": "NSE archives fo_mktlots.csv and the F&O UDiFF bhavcopy (membership), fo_secban.csv (ban list); niftyindices.com constituent CSVs plus NSE Indices rebalancing press releases (history)"},
    {"data": "Sector / industry classification",
     "adds": "true industry momentum, sector-neutral ranking, lead-lag across linked industries",
     "mechanism": "industry momentum (Moskowitz & Grinblatt 1999); slow diffusion across linked firms (Hou 2007; Cohen & Frazzini 2008). The return-correlation clusters here are only a statistical stand-in",
     "source": "NSE 4-level industry classification (macro sector / sector / industry / basic industry) in the NSE equity master and the niftyindices.com constituent files; AMFI half-yearly market-cap categorisation"},
    {"data": "Fundamentals (quarterly results, balance sheet)",
     "adds": "value, profitability/quality, accruals, earnings surprise",
     "mechanism": "value and profitability premia (Fama & French 2015; Novy-Marx 2013), accrual anomaly (Sloan 1996), post-earnings-announcement drift (Bernard & Thomas 1989)",
     "source": "Reg-33 LODR XBRL results filed on NSE/BSE (free, needs parsing); vendors CMIE Prowess, ACE Equity, Capitaline, LSEG, Bloomberg"},
    {"data": "Corporate announcements and corporate actions",
     "adds": "event timing (results, buybacks, pledges, insider trades) and price adjustment factors",
     "mechanism": "event drift and PEAD (Bernard & Thomas 1989), buyback drift (Ikenberry, Lakonishok & Vermaelen 1995), insider-trade signals (Seyhun 1986). CA factors would also remove split artefacts from every rolling feature and from the y_clean mask (which drops 0.6% of labelled rows)",
     "source": "NSE corporate filings (announcements, corporate actions, board meetings), BSE announcements API, SEBI PIT/SAST disclosures carried by both exchanges"},
    {"data": "Options-implied volatility and derivatives positioning",
     "adds": "IV skew, call-put IV spread, implied-minus-realised vol, futures OI/basis (the README's out-of-scope 'carry')",
     "mechanism": "IV skew predicts returns (Xing, Zhang & Zhao 2010); call-put IV spread (Cremers & Weinbaum 2010); volatility risk premium (Bali & Hovakimian 2009); India VIX as the regime conditioner the March-2026 break called for",
     "source": "NSE F&O bhavcopy (daily option settlement prices, OI, volume per strike: IV via Black-76), India VIX history (NSE), NSE participant-wise OI"},
    {"data": "Institutional flows (FII/FPI, DII)",
     "adds": "flow-induced price pressure; per-stock ownership change",
     "mechanism": "foreign flows predict EM returns (Froot, O'Connell & Seasholes 2001); flow-driven fire sales/purchases (Coval & Stafford 2007)",
     "source": "NSE/BSE daily FII/DII cash-market figures (aggregate only), NSDL FPI Monitor (aggregate, fortnightly by sector); per stock: quarterly shareholding patterns (NSE/BSE), daily bulk/block deal files (NSE archives), AMC monthly portfolio disclosures"},
    {"data": "News and sentiment",
     "adds": "news tone, attention shocks, news-vs-no-news momentum",
     "mechanism": "media pessimism predicts reversals (Tetlock 2007); drift after news vs reversal without news (Chan 2003); attention-driven buying (Barber & Odean 2008)",
     "source": "licensed feeds (LSEG MarketPsych, Bloomberg, Dow Jones/Factiva); exchange announcements as structured events; GDELT (free, coarse)"},
    {"data": "India-specific: surveillance, price bands, SLB, promoter pledges",
     "adds": "ASM/GSM stage changes and price-band moves (mechanical liquidity limits); SLB borrow as short interest; pledge overhang",
     "mechanism": "trading restrictions shift liquidity and returns; short interest predicts returns (Desai et al. 2002; Boehmer, Jones & Zhang 2008); forced-sale risk from pledged promoter holdings",
     "source": "NSE daily ASM/GSM lists and sec_list.csv price bands; NSE SLB bhavcopy; SEBI SAST pledge disclosures (NSE 'pledged data')"},
]


# ========================================================================= #
# raw data, universe, market series
# ========================================================================= #

def load_eod() -> pd.DataFrame:
    cols = ["date", "ticker", "series", "prev_close", "open", "high", "low",
            "last", "close", "vwap", "volume", "turnover", "trades",
            "deliv_qty", "deliv_pct"]
    e = pd.read_parquet(SNAPSHOT, columns=cols)
    e = e[e["series"].isin(["EQ", "BE"])].drop(columns="series")
    e["date"] = pd.to_datetime(e["date"])
    e = e.sort_values(ID[::-1]).reset_index(drop=True)          # ticker, date
    assert not e.duplicated(ID).any(), "duplicate (date,ticker) in EQ/BE rows"
    return e


def _groll(df: pd.DataFrame, col: str, w: int, minp: int, how: str) -> pd.Series:
    """Per-ticker trailing rolling statistic over the ticker's own rows."""
    r = df.groupby("ticker", sort=False)[col].rolling(w, min_periods=minp)
    return getattr(r, how)().reset_index(level=0, drop=True).reindex(df.index)


def universe_frame(e: pd.DataFrame) -> pd.DataFrame:
    """ret_1d + the ml/data.py point-in-time universe flag on EQ+BE rows."""
    g = e.groupby("ticker", sort=False)
    u = e[ID].copy()
    u["_ret_1d"] = g["close"].pct_change()
    med = _groll(e, "turnover", 20, 10, "median")
    u["univ"] = (e["close"] >= MIN_PRICE) & (med >= MIN_MED_TURNOVER)
    return u


def market_series(u: pd.DataFrame) -> pd.Series:
    """Per-date universe-median ret_1d (uses only date-t rows)."""
    m = u[u["univ"]]
    return m.groupby("date")["_ret_1d"].median()


# ========================================================================= #
# per-ticker features (strictly backward-looking)
# ========================================================================= #

PT_OUT = ["trades_z_20", "close_vs_vwap", "close_vs_vwap_5", "last_vs_close",
          "deliv_value_share_20", "gap_fill_10", "range_position_20",
          "resid_mom_63", "idio_vol_60", "beta_60",
          "_log_ats", "_ats_chg_20", "_amihud_raw_20", "_ret_1d"]


def per_ticker_features(eod: pd.DataFrame, mkt: pd.Series) -> pd.DataFrame:
    """All per-ticker features on EQ+BE rows; works on any ticker/date subset
    (full build and the truncated-history leak check use the same code)."""
    df = eod.sort_values(["ticker", "date"]).reset_index(drop=True).copy()
    g = df.groupby("ticker", sort=False)
    df["_ret_1d"] = g["close"].pct_change()

    # (1) average trade size: log(turnover / trades) -- institutional footprint
    ok = (df["turnover"] > 0) & (df["trades"] > 0)
    df["_log_ats"] = np.log((df["turnover"] / df["trades"]).where(ok))
    df["_ats5"] = _groll(df, "_log_ats", 5, 3, "mean")
    df["_ats_chg_20"] = df["_ats5"] - df.groupby("ticker", sort=False)["_ats5"].shift(20)

    # (2) trade-count z-score (vol_z_20 convention: 20-row window incl. today)
    tm = _groll(df, "trades", 20, 20, "mean")
    ts = _groll(df, "trades", 20, 20, "std")
    df["trades_z_20"] = (df["trades"] - tm) / ts.where(ts > 0)

    # (3) closing strength vs VWAP (NSE close = last-30-min weighted average)
    df["close_vs_vwap"] = df["close"] / df["vwap"].where(df["vwap"] > 0) - 1.0
    df["close_vs_vwap_5"] = _groll(df, "close_vs_vwap", 5, 3, "mean")

    # (4) closing-session pressure: last traded price vs official close
    df["last_vs_close"] = df["last"] / df["close"].where(df["close"] > 0) - 1.0

    # (5) delivery VALUE share of traded value, 20 sessions
    dq = df["deliv_qty"].astype(float)
    okd = dq.notna() & (df["turnover"] > 0)
    df["_dval"] = (dq * df["close"]).where(okd)
    df["_dturn"] = df["turnover"].where(okd)
    sv = _groll(df, "_dval", 20, 15, "sum")
    st = _groll(df, "_dturn", 20, 15, "sum")
    df["deliv_value_share_20"] = sv / st.where(st > 0)

    # (6) gap fill: share of the opening gap retraced by the close (sign-aware;
    #     1 = closed back at the CA-adjusted previous close), 10-session mean
    pc = df["prev_close"].where(df["prev_close"] > 0)
    gap = df["open"] - pc
    big = (gap.abs() / pc) >= GAP_MIN
    df["_gap_fill"] = ((df["open"] - df["close"]) / gap.where(big)).clip(
        -GAP_FILL_CLIP, GAP_FILL_CLIP)
    df["gap_fill_10"] = _groll(df, "_gap_fill", 10, 3, "mean")

    # (7) position in the 20-session high-low range
    hi = _groll(df, "high", 20, 15, "max")
    lo = _groll(df, "low", 20, 15, "min")
    rng = hi - lo
    df["range_position_20"] = (df["close"] - lo) / rng.where(rng > 0)

    # (8) Amihud illiquidity: mean |ret| per Rs crore traded (split days out)
    absr = df["_ret_1d"].abs()
    absr = absr.where(absr <= SPLIT_MOVE)
    df["_illiq"] = absr / (df["turnover"].where(df["turnover"] > 0) / 1e7)
    df["_amihud_raw_20"] = _groll(df, "_illiq", 20, 15, "mean")

    # (9)/(10) 60-session rolling OLS  ret_1d ~ a + b * universe-median ret_1d
    m = df["date"].map(mkt)
    r = df["_ret_1d"].where(df["_ret_1d"].abs() <= SPLIT_MOVE)
    valid = r.notna() & m.notna()
    df["_x"] = m.where(valid)
    df["_y"] = r.where(valid)
    df["_v"] = valid.astype(float)
    df["_xx"] = df["_x"] * df["_x"]
    df["_xy"] = df["_x"] * df["_y"]
    df["_yy"] = df["_y"] * df["_y"]
    n = _groll(df, "_v", REG_WIN, 1, "sum")
    s = {c: _groll(df, c, REG_WIN, 1, "sum") for c in ("_x", "_y", "_xx", "_xy", "_yy")}
    enough = n >= REG_MINP
    mx, my = s["_x"] / n, s["_y"] / n
    vx = s["_xx"] / n - mx * mx
    cxy = s["_xy"] / n - mx * my
    beta = (cxy / vx.where(vx > 1e-12)).where(enough)
    alpha = my - beta * mx
    df["_resid"] = df["_y"] - alpha - beta * df["_x"]   # residual at t, coefs from <= t
    vres = (s["_yy"] / n - my * my) - beta * cxy
    df["idio_vol_60"] = np.sqrt((vres.clip(lower=0) * n / (n - 2)).where(enough))
    df["beta_60"] = beta
    df["resid_mom_63"] = _groll(df, "_resid", RESID_SUM_WIN, RESID_SUM_MINP, "sum")
    return df[ID + PT_OUT]


# ========================================================================= #
# sector proxy: return-correlation clusters, fit once on data <= cutoff
# ========================================================================= #

def build_clusters(u: pd.DataFrame, mkt: pd.Series, e: pd.DataFrame) -> tuple[pd.Series, dict]:
    from sklearn.cluster import KMeans
    dts = np.sort(u["date"].unique())
    dts = dts[dts <= np.datetime64(CLUSTER_CUTOFF)]
    win = pd.DatetimeIndex(dts[-CLUSTER_WINDOW:])
    sub = u[u["date"].isin(win)]
    in_univ = set(sub.loc[sub["univ"], "ticker"])
    R = sub.pivot(index="date", columns="ticker", values="_ret_1d").reindex(win)
    R = R[sorted(t for t in in_univ if t in R.columns)]
    R = R.where(R.abs() <= SPLIT_MOVE)
    R = R.loc[:, R.notna().sum() >= CLUSTER_MIN_OBS]
    Rv = R.to_numpy(dtype=float)
    M = np.broadcast_to(mkt.reindex(win).to_numpy(dtype=float)[:, None], Rv.shape)
    V = np.isfinite(Rv) & np.isfinite(M)
    nn = V.sum(0)
    x, y = np.where(V, M, 0.0), np.where(V, Rv, 0.0)
    mx, my = x.sum(0) / nn, y.sum(0) / nn
    b = ((x * y).sum(0) / nn - mx * my) / ((x * x).sum(0) / nn - mx * mx)
    a = my - b * mx
    E = np.where(V, Rv - a - b * M, np.nan)          # market-residual returns
    Z = (E - np.nanmean(E, 0)) / np.nanstd(E, 0)
    Z = np.nan_to_num(Z, nan=0.0).T                   # tickers x sessions
    km = KMeans(n_clusters=N_CLUSTERS, n_init=20, random_state=SEED).fit(Z)
    raw = pd.Series(km.labels_, index=R.columns)
    order = raw.value_counts().index                  # relabel: 0 = largest
    labels = raw.map({c: i for i, c in enumerate(order)}).astype(int)

    # diagnostics: residual-correlation structure + recognisable members
    G = (Z @ Z.T) / Z.shape[1]
    lab = labels.to_numpy()
    same = lab[:, None] == lab[None, :]
    off = ~np.eye(len(lab), dtype=bool)
    within = float(G[same & off].mean())
    between = float(G[~same].mean())
    medturn = (e[e["date"].isin(win)].groupby("ticker")["turnover"].median()
               .reindex(labels.index))
    members = {}
    for c in range(N_CLUSTERS):
        tk = labels.index[lab == c]
        members[str(c)] = {
            "size": int(len(tk)),
            "mean_within_resid_corr": round(float(G[np.ix_(lab == c, lab == c)][
                ~np.eye(int((lab == c).sum()), dtype=bool)].mean()), 4)
            if (lab == c).sum() > 1 else None,
            "top_by_turnover": [str(t) for t in
                                medturn.loc[tk].sort_values(ascending=False).index[:8]],
        }
    diag = {"window": [str(win[0].date()), str(win[-1].date())],
            "n_sessions": int(len(win)), "n_tickers": int(len(labels)),
            "method": ("KMeans(k=12, n_init=20, seed 108) on per-ticker standardized "
                       "market-residual daily returns (OLS on the universe-median "
                       "return over the window; |ret|>22% split/circuit days dropped); "
                       "tickers = in the PIT universe on >=1 window session with "
                       ">=100 valid returns"),
            "mean_within_cluster_resid_corr": round(within, 4),
            "mean_between_cluster_resid_corr": round(between, 4),
            "clusters": members}
    return labels, diag


# ========================================================================= #
# build: features joined onto the dataset rows
# ========================================================================= #

def build() -> tuple[pd.DataFrame, dict]:
    t0 = time.perf_counter()
    ds = pd.read_parquet(DATA_DIR / "model_dataset.parquet")
    ds["date"] = pd.to_datetime(ds["date"])
    assert len(ds) == EXPECTED_ROWS, f"unexpected dataset rows: {len(ds)}"
    assert not set(NEW_FEATURES) & set(ds.columns)
    base = ds.drop(columns=LABEL_COLS)
    for c in base.columns:
        assert not c.startswith(FORBIDDEN), f"label column in construction frame: {c}"

    e = load_eod()
    u = universe_frame(e)
    mkt = market_series(u)
    print(f"[build] EQ+BE rows {len(e):,}, tickers {e['ticker'].nunique():,}, "
          f"{e['date'].min().date()}..{e['date'].max().date()}")

    # consistency guards: identical raw series + identical universe
    mi = pd.MultiIndex.from_frame(base[ID])
    us = u.set_index(ID)
    r_re = us["_ret_1d"].reindex(mi).to_numpy(dtype=float)
    r_ds = base["ret_1d"].to_numpy(dtype=float)
    both = np.isfinite(r_re) & np.isfinite(r_ds)
    max_d_ret = float(np.max(np.abs(r_re[both] - r_ds[both])))
    assert max_d_ret < 1e-12 and (np.isfinite(r_re) == np.isfinite(r_ds)).all()
    rep = u[u["univ"] & (u["date"] >= base["date"].min())]
    rep_keys = pd.MultiIndex.from_frame(rep[ID])
    univ_equal = bool(len(rep_keys) == len(mi) and rep_keys.isin(mi).all())
    assert univ_equal, "replicated universe != dataset row set"
    mkt_ds = base.groupby("date")["ret_1d"].median()
    max_d_mkt = float((mkt.reindex(mkt_ds.index) - mkt_ds).abs().max())
    assert max_d_mkt < 1e-12
    print(f"[build] consistency: max|d ret_1d|={max_d_ret:.1e}, universe identical "
          f"({len(mi):,} rows), max|d mkt median|={max_d_mkt:.1e}")

    tickers = set(base["ticker"].unique())
    pt = per_ticker_features(e[e["ticker"].isin(tickers)], mkt)
    pts = pt.set_index(ID)
    J = {c: pts[c].reindex(mi).to_numpy(dtype=float) for c in PT_OUT}
    print(f"[build] per-ticker features done ({time.perf_counter() - t0:.0f}s)")

    date = base["date"]

    def cs_z(v: np.ndarray) -> np.ndarray:
        s = pd.Series(v, index=base.index)
        gs = s.groupby(date)
        return ((s - gs.transform("mean")) / gs.transform("std")).to_numpy(dtype=float)

    new: dict[str, np.ndarray] = {}
    new["avg_trade_size_z"] = cs_z(J["_log_ats"])
    new["ats_chg_20"] = cs_z(J["_ats_chg_20"])
    for c in ("trades_z_20", "close_vs_vwap", "close_vs_vwap_5", "last_vs_close",
              "deliv_value_share_20", "gap_fill_10", "range_position_20",
              "resid_mom_63", "idio_vol_60", "beta_60"):
        new[c] = J[c]
    am = J["_amihud_raw_20"]
    new["amihud_20"] = cs_z(np.log(np.where(am > 0, am, np.nan)))
    for src, dst in (("resid_mom_63", "cs_rank_resid_mom_63"),
                     ("idio_vol_60", "cs_rank_idio_vol_60")):
        new[dst] = pd.Series(new[src], index=base.index).groupby(date).rank(
            pct=True).to_numpy(dtype=float)

    labels, cdiag = build_clusters(u, mkt, e)
    cl = base["ticker"].map(labels)
    keys = [date, cl]
    for src, dst in CLUSTER_REL:
        s = base[src]
        gk = s.groupby(keys, dropna=True)
        med = gk.transform("median")
        cnt = gk.transform("count")
        new[dst] = (s - med).where(cnt >= CLUSTER_MIN_NAMES).to_numpy(dtype=float)
        if src == "mom_20":
            new["cluster_mom_20"] = med.where(cnt >= CLUSTER_MIN_NAMES).to_numpy(dtype=float)
        if src == "ret_126d":
            new["cluster_ret_126"] = med.where(cnt >= CLUSTER_MIN_NAMES).to_numpy(dtype=float)
    cov = cl.notna().groupby(date.dt.strftime("%Y-%m")).mean()
    cdiag["row_coverage_by_month"] = {k: round(float(v), 3) for k, v in cov.items()}
    cdiag["row_coverage_overall"] = round(float(cl.notna().mean()), 3)
    print(f"[build] clusters: {cdiag['n_tickers']} tickers, within/between resid corr "
          f"{cdiag['mean_within_cluster_resid_corr']}/{cdiag['mean_between_cluster_resid_corr']}, "
          f"row coverage {cdiag['row_coverage_overall']}")

    out = ds.copy()
    for f in NEW_FEATURES:
        out[f] = np.asarray(new[f], dtype=float)
    out["cluster_id"] = cl.to_numpy(dtype=float)
    for c in ds.columns:
        assert out[c].equals(ds[c]), f"existing column changed: {c}"

    leak = truncation_check(out, e)
    cluster_pit = cluster_pit_check(e, labels)
    print(f"[build] truncation check PASSED ({leak['n_tickers']} tickers x "
          f"{len(LEAK_CHECK_FEATURES)} features); cluster PIT check "
          f"{'PASSED' if cluster_pit['identical'] else 'FAILED'}")

    nan_pct = {f: round(float(out[f].isna().mean()) * 100, 2) for f in NEW_FEATURES}
    assert not [f for f, v in nan_pct.items() if v >= 100.0]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT_PARQUET, index=False)
    manifest = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "builder": "ml/feature_sufficiency.py (feature-sufficiency DS)",
        "rows": int(len(out)), "seed": SEED,
        "source": "ml/data/equity_eod_snapshot.parquet series EQ+BE (DuckDB never opened)",
        "new_features": NEW_FEATURES, "groups": GROUPS, "extra_columns": ["cluster_id"],
        "pilot_overlap": PILOT_OVERLAP,
        "consistency": {"max_abs_diff_ret_1d": max_d_ret, "universe_identical": univ_equal,
                        "max_abs_diff_universe_median_ret": max_d_mkt},
        "leak_check": leak, "cluster_pit_check": cluster_pit, "clusters": cdiag,
        "nan_pct": nan_pct,
        "definitions": {
            "avg_trade_size_z": "per-date z (universe) of log(turnover/trades)",
            "ats_chg_20": "per-date z of [5d-mean log(turnover/trades) minus its value 20 sessions earlier]",
            "trades_z_20": "(trades - 20d mean)/20d std, window incl. today (vol_z_20 convention)",
            "close_vs_vwap": "close/vwap - 1", "close_vs_vwap_5": "5-session mean (min 3)",
            "last_vs_close": "last/close - 1",
            "deliv_value_share_20": "20d sum(deliv_qty*close) / 20d sum(turnover) on rows with delivery data (min 15)",
            "gap_fill_10": "10-session mean (min 3 gap days) of (open-close)/(open-prev_close) on days with |gap|>=0.25%, clipped to +-3; prev_close = bhavcopy PREV_CLOSE (CA-adjusted)",
            "range_position_20": "(close - 20d min low)/(20d max high - 20d min low), min 15 rows",
            "amihud_20": "per-date z of log(20d mean |ret_1d| / turnover in Rs crore), |ret|>22% days excluded",
            "resid_mom_63": "63-session sum (min 45) of e_t = r_t - a_t - b_t m_t, (a_t,b_t) = 60-session OLS (min 40) ending at t; m = universe-median ret_1d; |r|>22% excluded",
            "idio_vol_60": "residual std of that regression (n-2 dof)", "beta_60": "slope of that regression",
            "cs_rank_*": "per-date percentile rank over the universe",
            "cr_<x>": "x minus its cluster's per-date universe median (>=5 names)",
            "cluster_mom_20 / cluster_ret_126": "cluster's per-date median mom_20 / ret_126d (>=5 names)",
        },
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_JSON.write_text(json.dumps(manifest, indent=1, default=str))
    print(f"[build] wrote {OUT_PARQUET} ({len(out):,} x {out.shape[1]}) in "
          f"{time.perf_counter() - t0:.0f}s")
    return out, manifest


def truncation_check(out: pd.DataFrame, e: pd.DataFrame) -> dict:
    """Truncate the WHOLE market at an interior date t, re-derive the market
    series and the ticker's features from data <= t, compare with stored."""
    rng = np.random.default_rng(SEED)
    cnt = out.groupby("ticker")["date"].transform("size")
    posf = out.groupby("ticker").cumcount() / cnt
    okall = out[LEAK_CHECK_FEATURES].notna().all(axis=1)
    interior = okall & (posf >= 0.6) & (posf <= 0.95) & (cnt >= 150)
    elig = np.sort(out.loc[interior, "ticker"].unique())
    picks = rng.choice(elig, size=5, replace=False)
    cases = []
    for tk in picks:
        row = out[(out["ticker"] == tk) & interior].iloc[0]
        t = row["date"]
        trunc = e[e["date"] <= t]
        mkt_t = market_series(universe_frame(trunc))
        re_pt = per_ticker_features(trunc[trunc["ticker"] == tk], mkt_t)
        rr = re_pt[re_pt["date"] == t]
        assert len(rr) == 1
        stored = row[LEAK_CHECK_FEATURES].to_numpy(dtype=float)
        recomputed = rr.iloc[0][LEAK_CHECK_FEATURES].to_numpy(dtype=float)
        match = bool(np.allclose(stored, recomputed, rtol=1e-9, atol=1e-12, equal_nan=True))
        cases.append({"ticker": str(tk), "date": str(t.date()),
                      "stored": dict(zip(LEAK_CHECK_FEATURES, map(float, stored))),
                      "recomputed_from_data_leq_t": dict(zip(LEAK_CHECK_FEATURES,
                                                             map(float, recomputed))),
                      "match": match})
        assert match, f"TRUNCATION CHECK FAILED {tk} @ {t}: {stored} vs {recomputed}"
    return {"passed": True, "seed": SEED, "n_tickers": 5,
            "features_checked": LEAK_CHECK_FEATURES, "cases": cases}


def cluster_pit_check(e: pd.DataFrame, labels: pd.Series) -> dict:
    """Re-fit the clusters on the snapshot truncated at the cutoff: the labels
    must be identical, i.e. nothing after 2026-01-31 enters the grouping."""
    trunc = e[e["date"] <= CLUSTER_CUTOFF]
    u = universe_frame(trunc)
    lab2, _ = build_clusters(u, market_series(u), trunc)
    same = bool(lab2.index.equals(labels.index) and (lab2 == labels).all())
    assert same, "cluster labels depend on data after the cutoff"
    return {"identical": same, "refit_on_data_leq": str(CLUSTER_CUTOFF.date())}


# ========================================================================= #
# C. unique-information test
# ========================================================================= #

def _corr(a: np.ndarray, b: np.ndarray) -> float:
    a = a - a.mean()
    b = b - b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d > 0 else np.nan


def _basis(X: np.ndarray) -> np.ndarray:
    U, s, _ = np.linalg.svd(X, full_matrices=False)
    return U[:, s > s[0] * 1e-10]


def ic_study(lab: pd.DataFrame, feats: list[str], controls: list[str] | None = None,
             quad: bool = True) -> dict:
    """Per-date raw Spearman IC and residual IC (feature rank orthogonalized
    on the controls' per-date ranks [+ NaN indicators]; default controls =
    the champion's 10; 'quad' also removes squared ranks) vs y_excess_20d.
    A residual with < 1e-10 of the feature's rank variance is treated as
    'no unique information' (IC 0) instead of ranking float noise."""
    from scipy.stats import rankdata
    controls = controls or CHAMPION
    y_all = lab["y_excess_20d"].to_numpy(dtype=float)
    F = {f: lab[f].to_numpy(dtype=float) for f in feats}
    C_all = lab[controls].to_numpy(dtype=float)
    res = {f: {"raw": {}, "resid": {}, "resid_quad": {}, "resid_share": {}} for f in feats}
    for d, idx in lab.groupby("date").indices.items():
        n = len(idx)
        if n < MIN_NAMES_IC:
            continue
        yd = y_all[idx]
        C = C_all[idx]
        lin, quad_cols = [np.ones(n)], []
        for j in range(C.shape[1]):
            v = C[:, j]
            ok = np.isfinite(v)
            k = int(ok.sum())
            if k < 2:
                continue
            r = np.zeros(n)
            r[ok] = rankdata(v[ok]) / k - 0.5
            lin.append(r)
            quad_cols.append(r * r)
            if k < n:
                lin.append((~ok).astype(float))
        Xl = np.column_stack(lin)
        Xq = np.column_stack(lin + quad_cols) if quad else Xl
        cache: dict[bytes, tuple[np.ndarray, np.ndarray]] = {}
        for f in feats:
            x = F[f][idx]
            m = np.isfinite(x)
            if int(m.sum()) < MIN_NAMES_IC or np.ptp(x[m]) == 0:
                continue
            key = np.packbits(m).tobytes()
            if key not in cache:
                cache[key] = (_basis(Xl[m]), _basis(Xq[m]) if quad else None)
            Ul, Uq = cache[key]
            rx = rankdata(x[m])
            ry = rankdata(yd[m])
            res[f]["raw"][d] = _corr(rx, ry)
            rc = rx - rx.mean()
            el = rc - Ul @ (Ul.T @ rc)
            share = float((el * el).sum() / (rc * rc).sum())
            res[f]["resid_share"][d] = share
            res[f]["resid"][d] = _corr(rankdata(el), ry) if share > 1e-10 else 0.0
            if quad:
                eq = rc - Uq @ (Uq.T @ rc)
                sq = float((eq * eq).sum() / (rc * rc).sum())
                res[f]["resid_quad"][d] = _corr(rankdata(eq), ry) if sq > 1e-10 else 0.0
    return res


def mstats(daily: dict, lo: str | None = None, hi: str | None = None) -> dict:
    from scipy.stats import t as student_t
    s = pd.Series(daily, dtype=float)
    if s.empty:
        return {"n_months": 0, "mean_ic": None, "t": None, "p": None}
    s.index = pd.to_datetime(s.index)
    if lo:
        s = s[s.index >= pd.Timestamp(lo)]
    if hi:
        s = s[s.index <= pd.Timestamp(hi)]
    if s.empty:
        return {"n_months": 0, "mean_ic": None, "t": None, "p": None}
    mth = s.groupby(s.index.strftime("%Y-%m")).mean()
    n = len(mth)
    mean = float(mth.mean())
    sd = float(mth.std(ddof=1)) if n > 1 else float("nan")
    t = mean / (sd / np.sqrt(n)) if n > 1 and sd > 0 else float("nan")
    p = float(2 * student_t.sf(abs(t), n - 1)) if np.isfinite(t) else float("nan")
    sgn = 1.0 if mean >= 0 else -1.0
    return {"mean_ic": mean, "ic_std": sd, "t": t if np.isfinite(t) else None,
            "p": p if np.isfinite(p) else None, "n_months": n, "n_dates": int(len(s)),
            "sign_consistency": float((np.sign(mth) == sgn).mean()),
            "monthly": {k: round(float(v), 5) for k, v in mth.items()}}


def bh(p: list[float]) -> list[float]:
    p = np.asarray(p, dtype=float)
    n = len(p)
    order = np.argsort(p)
    q = p[order] * n / np.arange(1, n + 1)
    q = np.minimum.accumulate(q[::-1])[::-1].clip(0, 1)
    out = np.empty(n)
    out[order] = q
    return out.tolist()


def summarize_ic(res: dict, feats: list[str], splits: dict) -> dict:
    sel_end = splits["holdout"]["train_end"]
    precv_end = splits["folds"][0]["train_end"]
    cv_lo, cv_hi = splits["folds"][0]["test_start"], splits["folds"][-1]["test_end"]
    ho_lo, ho_hi = splits["holdout"]["test_start"], splits["holdout"]["test_end"]
    out = {}
    for f in feats:
        r = res[f]
        out[f] = {
            "raw_full": mstats(r["raw"]), "resid_full": mstats(r["resid"]),
            "resid_quad_full": mstats(r["resid_quad"]),
            "resid_sel": mstats(r["resid"], hi=sel_end),
            "resid_precv": mstats(r["resid"], hi=precv_end),
            "resid_cvtest": mstats(r["resid"], lo=cv_lo, hi=cv_hi),
            "resid_holdout": mstats(r["resid"], lo=ho_lo, hi=ho_hi),
            "raw_pit_cluster": mstats(r["raw"], lo=PIT_CLUSTER_START),
            "resid_pit_cluster": mstats(r["resid"], lo=PIT_CLUSTER_START),
        }
    ok = [f for f in feats if out[f]["resid_full"].get("p") is not None]
    for key in ("resid_full", "raw_full"):
        qs = bh([out[f][key]["p"] for f in ok])
        for f, q in zip(ok, qs):
            out[f][key]["q_bh"] = q
    return out


def _abs_t(s: dict) -> float:
    return abs(s["t"]) if s.get("t") is not None else -1.0


def select_top(summary: dict, key: str, k: int = 5) -> list[str]:
    """Top-k by |residual t| in window `key`, rank-equivalent pairs collapsed
    (the cs_rank member is kept: identical IC, stationary across dates)."""
    ranked = sorted(NEW_FEATURES, key=lambda f: -_abs_t(summary[f][key]))
    picked: list[str] = []
    for f in ranked:
        rep = {v: kk for kk, v in RANK_EQUIV.items()}.get(f, f)   # raw -> cs_rank
        if rep not in picked:
            picked.append(rep)
        if len(picked) == k:
            break
    return picked


# ========================================================================= #
# D. harness A/B + paired date-block bootstrap
# ========================================================================= #

def champion_lgbm(task):
    from lightgbm import LGBMClassifier
    return LGBMClassifier(num_leaves=63, learning_rate=0.05, n_estimators=300,
                          feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1,
                          min_data_in_leaf=200, num_threads=2, verbosity=-1,
                          random_state=SEED)


def variants(top5: list[str]) -> dict[str, tuple[list[str], str]]:
    swap = {"cs_rank_mom_20": "resid_mom_63", "cs_rank_vol_20": "idio_vol_60"}
    swap_rank = {"cs_rank_mom_20": "cs_rank_resid_mom_63",
                 "cs_rank_vol_20": "cs_rank_idio_vol_60"}
    return {
        "control": (list(CHAMPION), "same-session replica of lgbm_fs_selected_clean"),
        "top5": (CHAMPION + top5, "(i) champion 10 + top-5 new by |residual t| "
                 "(selection window <= holdout train_end; sees CV-month labels)"),
        "cluster": (CHAMPION + CLUSTER, "(ii) champion 10 + cluster-relative set"),
        "micro": (CHAMPION + MICRO, "(iii) champion 10 + microstructure set (A)"),
        "swap_resid": ([swap.get(f, f) for f in CHAMPION],
                       "(iv) cs_rank_mom_20/cs_rank_vol_20 -> resid_mom_63/idio_vol_60"),
        "swap_resid_rank": ([swap_rank.get(f, f) for f in CHAMPION],
                            "(iv-b) same swap with the cs_rank versions"),
    }


def run_ab(df: pd.DataFrame, feats_all: list[str], splits: dict,
           top5: list[str]) -> dict:
    out = {}
    for name, (subset, note) in variants(top5).items():
        res = run_standard_eval(
            f"lgbm_suff_{name}", "feature_sufficiency", "feature-sufficiency",
            make_model=champion_lgbm, tasks=("beat_mkt_20d",), preprocess="raw",
            feature_subset=subset,
            params={"config": "pilot champion LGBM", "num_leaves": 63,
                    "learning_rate": 0.05, "n_estimators": 300, "feature_fraction": 0.8,
                    "bagging_fraction": 0.8, "bagging_freq": 1, "min_data_in_leaf": 200,
                    "num_threads": 2, "random_state": SEED},
            notes=f"feature-sufficiency A/B on model_dataset_suff: {note}",
            df=df, features=feats_all, splits=splits)
        p = res["beat_mkt_20d"]
        folds = {f["fold"]: f["auc"] for f in p["folds"]}
        out[name] = {
            "model": f"lgbm_suff_{name}", "note": note, "features": subset,
            "n_features": len(subset), "cv": p["cv_auc_mean"], "cv_std": p["cv_auc_std"],
            "folds": folds, "min_fold": min(folds.values()),
            "holdout": p["holdout"]["auc"],
            "holdout_spread": p["holdout"].get("decile_spread"),
            "cv_mean_spread": float(np.mean([f.get("decile_spread", np.nan)
                                             for f in p["folds"]])),
            "passes": bool(p["cv_auc_mean"] >= PASS_MARK
                           and min(folds.values()) >= FOLD_FLOOR),
        }
    return out


def _auc_prep(score: np.ndarray, y: np.ndarray):
    order = np.argsort(score, kind="mergesort")
    s = score[order]
    gid = np.cumsum(np.r_[True, s[1:] != s[:-1]]) - 1
    return order, (y[order] == 1), gid, int(gid[-1] + 1)


def _wauc(w: np.ndarray, prep) -> float:
    order, pos, gid, ng = prep
    ws = w[order]
    gp = np.bincount(gid, weights=ws * pos, minlength=ng)
    gn = np.bincount(gid, weights=ws * ~pos, minlength=ng)
    below = np.cumsum(gn) - gn
    den = gp.sum() * gn.sum()
    return float((gp * (below + 0.5 * gn)).sum() / den) if den > 0 else np.nan


def paired_bootstrap(names: list[str], splits: dict, B: int = BOOT_B) -> dict:
    """Resample test DATES with replacement within each fold (same draw for
    every model = paired); statistic = mean of the 4 CV-fold AUCs."""
    P = {n: pd.read_parquet(PREDS_OUT / f"lgbm_suff_{n}__beat_mkt_20d.parquet")
         for n in names}
    ref = P["control"]
    for n in names:
        assert (P[n]["ticker"].to_numpy() == ref["ticker"].to_numpy()).all()
        assert (P[n]["date"].to_numpy() == ref["date"].to_numpy()).all()
    cv_names = [f["name"] for f in splits["folds"]]
    fold_names = cv_names + ["holdout"]
    rng = np.random.default_rng(SEED)
    prep, codes, nd = {}, {}, {}
    for fo in fold_names:
        msk = (ref["fold"] == fo).to_numpy()
        c, uniq = pd.factorize(ref.loc[msk, "date"])
        codes[fo], nd[fo] = c, len(uniq)
        for n in names:
            prep[(n, fo)] = _auc_prep(P[n].loc[msk, "score"].to_numpy(dtype=float),
                                      P[n].loc[msk, "y"].to_numpy(dtype=float))
    draws = {n: {fo: np.empty(B) for fo in fold_names} for n in names}
    point = {n: {fo: _wauc(np.ones(len(codes[fo])), prep[(n, fo)]) for fo in fold_names}
             for n in names}
    for b in range(B):
        for fo in fold_names:
            wd = rng.multinomial(nd[fo], np.full(nd[fo], 1.0 / nd[fo])).astype(float)
            w = wd[codes[fo]]
            for n in names:
                draws[n][fo][b] = _wauc(w, prep[(n, fo)])
    out = {}
    ctl_cv = np.mean([draws["control"][fo] for fo in cv_names], axis=0)
    for n in names:
        cv = np.mean([draws[n][fo] for fo in cv_names], axis=0)
        d = cv - ctl_cv
        dh = draws[n]["holdout"] - draws["control"]["holdout"]
        out[n] = {
            "cv_point": float(np.mean([point[n][fo] for fo in cv_names])),
            "cv_ci95": [float(np.percentile(cv, 2.5)), float(np.percentile(cv, 97.5))],
            "p_cv_ge_pass_mark": float((cv >= PASS_MARK).mean()),
            "delta_cv_vs_control": float(np.mean([point[n][fo] - point["control"][fo]
                                                  for fo in cv_names])),
            "delta_cv_ci95": [float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))],
            "p_delta_cv_gt0": float((d > 0).mean()),
            "delta_holdout": float(point[n]["holdout"] - point["control"]["holdout"]),
            "delta_holdout_ci95": [float(np.percentile(dh, 2.5)),
                                   float(np.percentile(dh, 97.5))],
        }
    return {"B": B, "seed": SEED, "method": "date-block bootstrap within folds, paired "
            "across models (identical weights per draw); statistic = mean of 4 CV fold AUCs",
            "results": out}


# ========================================================================= #
# redundancy vs existing features (context for 'already in the pilot?')
# ========================================================================= #

def redundancy(out: pd.DataFrame, existing: list[str], n: int = 100_000) -> dict:
    from scipy.stats import rankdata
    samp = out.sample(n=min(n, len(out)), random_state=SEED)
    R = {}
    for c in set(NEW_FEATURES) | set(existing):
        v = samp[c].to_numpy(dtype=float)
        r = np.full(v.shape, np.nan)
        ok = np.isfinite(v)
        r[ok] = rankdata(v[ok])
        R[c] = r
    res = {}
    for f in NEW_FEATURES:
        best, name = 0.0, None
        for c in existing:
            m = np.isfinite(R[f]) & np.isfinite(R[c])
            if m.sum() < 1000:
                continue
            rho = _corr(R[f][m], R[c][m])
            if np.isfinite(rho) and abs(rho) > abs(best):
                best, name = rho, c
        res[f] = {"closest_existing": name, "rank_corr": round(float(best), 4)}
    return res


# ========================================================================= #
# report
# ========================================================================= #

def _f(x, nd=4, sign=False):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "n/a"
    return f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}"


def write_report(ev_: dict) -> None:
    S = ev_["ic_summary"]
    ab = ev_.get("ab", {})
    boot = ev_.get("bootstrap", {}).get("results", {})
    ref = ev_.get("ic_reference_engineered", {})
    cdiag = ev_["manifest"]["clusters"]
    ranked = sorted(NEW_FEATURES, key=lambda f: -_abs_t(S[f]["resid_full"]))
    n_q = [f for f in NEW_FEATURES if (S[f]["resid_full"].get("q_bh") or 1) <= BH_Q]
    n_q_raw = [f for f in NEW_FEATURES if (S[f]["raw_full"].get("q_bh") or 1) <= BH_Q]
    passers = [k for k, v in ab.items() if k != "control" and v["passes"]]
    best = max((k for k in ab if k != "control"), key=lambda k: ab[k]["cv"]) if ab else None
    sufficient = not passers
    ctl = ab.get("control", {})

    L = []
    L.append("# Feature sufficiency: does the bhavcopy hold information the champion lacks?\n")
    L.append(f"*Generated {ev_['generated_at']} by `python3 -m ml.feature_sufficiency` "
             f"(seed 108). Evidence: `feature_sufficiency.json`; feature definitions and "
             f"leak checks: `manifest_suff.json`.*\n")
    L.append("## Verdict\n")
    if not ab:
        L.append("**A/B not yet run** (`--skip-ab`); verdict pending.\n")
    elif sufficient:
        L.append(
            f"**The champion's feature set is sufficient for what this sample can resolve. "
            f"Do not add any of the {len(NEW_FEATURES)} new features.** No A/B variant reached "
            f"the fixed pass mark of {PASS_MARK} CV AUC with every fold at or above 0.50. The best variant, "
            f"`lgbm_suff_{best}`, scored {_f(ab[best]['cv'])} against {_f(ctl.get('cv'))} for "
            f"the same-session control. Our recommendation is to keep the 10-feature set "
            f"and spend the effort on the external data listed below.\n")
    else:
        L.append(
            f"**The champion's feature set is not sufficient.** {len(passers)} variant(s) cleared the "
            f"fixed pass mark of {PASS_MARK} with every fold at or above 0.50: "
            + ", ".join(f"`lgbm_suff_{k}` ({_f(ab[k]['cv'])})" for k in passers) + ".\n")
    L.append(
        f"On the information test, {len(n_q)} of {len(NEW_FEATURES)} new features carry "
        f"residual information at BH q ≤ {BH_Q}, meaning information the champion's 10 features "
        f"do not span linearly: "
        + (", ".join(f"`{f}`" for f in n_q) if n_q else "none") + ". "
        f"{len(n_q_raw)} pass on raw IC alone. ")
    L.append("Some features carry new information on paper, but the model gained nothing "
             "from them out of sample. Either the trees already extract the information, or "
             "a 4-month CV is too small to see a gain of that size.\n" if (n_q and sufficient)
             else "\n")

    L.append("## Residual-IC evidence (top 10 by |residual monthly t|, all 23 in the JSON)\n")
    L.append("Each IC is the per-date Spearman correlation with `y_excess_20d` on clean labelled rows, averaged "
             "within months, over 16 months (2025-06 to 2026-09). "
             "To get the residual IC, each feature's per-date rank is first OLS-orthogonalized on the "
             "champion's 10 ranks (plus NaN indicators); the residual is then correlated with the label. "
             "The \"quad\" column also removes squared ranks, a crude proxy for what the trees can do non-linearly. "
             "The q column is the BH q-value across all 23 new features. CV and holdout columns are mean residual IC.\n")
    L.append("| # | feature | raw IC | raw t | resid IC | resid t | q (BH) | resid IC quad | resid IC vs all 40 pilot (t) | CV months | holdout months | in pilot already? |")
    L.append("|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for i, f in enumerate(ranked[:10], 1):
        s = S[f]
        a40 = s.get("resid_allbase_full", {})
        L.append(f"| {i} | `{f}` | {_f(s['raw_full']['mean_ic'], 4, True)} | "
                 f"{_f(s['raw_full']['t'], 2, True)} | {_f(s['resid_full']['mean_ic'], 4, True)} | "
                 f"{_f(s['resid_full']['t'], 2, True)} | {_f(s['resid_full'].get('q_bh'), 3)} | "
                 f"{_f(s['resid_quad_full']['mean_ic'], 4, True)} | "
                 f"{_f(a40.get('mean_ic'), 4, True)} ({_f(a40.get('t'), 2, True)}) | "
                 f"{_f(s['resid_cvtest']['mean_ic'], 4, True)} | "
                 f"{_f(s['resid_holdout']['mean_ic'], 4, True)} | {PILOT_OVERLAP[f]} |")
    L.append("")
    rb_ = ev_.get("ic_reference_pilot_nonchampion", {})
    if rb_:
        top_b = sorted((k for k in rb_ if rb_[k]["resid_full"].get("t") is not None),
                       key=lambda k: -_abs_t(rb_[k]["resid_full"]))[:4]
        L.append("**Information the pilot already holds.** The stricter column re-runs the residual "
                 "against all 40 pilot base features, not just the champion's 10. The non-champion pilot "
                 "features with the largest residual IC against the champion are "
                 + ", ".join(f"`{k}` {_f(rb_[k]['resid_full']['mean_ic'], 4, True)} "
                             f"(t {_f(rb_[k]['resid_full']['t'], 2, True)})" for k in top_b)
                 + ". Where a new feature's residual IC shrinks in the all-40 column, the 40-feature set "
                 "already holds that information and the champion's selection dropped it. The fix for "
                 "that is feature re-selection, not new data.\n")
    if ref:
        rt = sorted((k for k in ref if ref[k]["resid_full"].get("t") is not None),
                    key=lambda k: -_abs_t(ref[k]["resid_full"]))[:3]
        L.append("**Calibration.** The 23 engineered features from the earlier feature study, run "
                 "through the same test, have residual |t| up to "
                 + ", ".join(f"`{k}` {_f(ref[k]['resid_full']['t'], 2, True)}" for k in rt)
                 + ". All of them failed the harness A/B (best 0.5268). A residual t of this size "
                 "has not been enough to move AUC in this sample.\n")

    L.append("## Harness A/B (beat_mkt_20d, champion LightGBM config, pass mark 0.5364, every fold ≥ 0.50)\n")
    L.append("| variant | #feat | CV AUC ± std | folds Apr / May / Jun / Jul | min fold | Δ CV vs control [95% CI] | P(CV ≥ 0.5364) | holdout AUC | holdout spread | pass |")
    L.append("|---|---:|---|---|---:|---|---:|---:|---:|:-:|")
    for k, v in ab.items():
        b = boot.get(k, {})
        fo = " / ".join(_f(x, 4) for x in v["folds"].values())
        dci = (f"{_f(b.get('delta_cv_vs_control'), 4, True)} "
               f"[{_f(b['delta_cv_ci95'][0], 4, True)}, {_f(b['delta_cv_ci95'][1], 4, True)}]"
               if b and k != "control" else "--")
        L.append(f"| `lgbm_suff_{k}` | {v['n_features']} | {_f(v['cv'])} ± {_f(v['cv_std'], 3)} | "
                 f"{fo} | {_f(v['min_fold'])} | {dci} | {_f(b.get('p_cv_ge_pass_mark'), 3)} | "
                 f"{_f(v['holdout'])} | {_f(v['holdout_spread'], 4, True)} | "
                 f"{'**yes**' if v['passes'] else 'no'} |")
    L.append("")
    if ab:
        L.append(f"Variant (i) contains {', '.join('`' + f + '`' for f in ev_['top5'])}. The selection "
                 f"window was all labelled dates up to {ev_['splits']['holdout']['train_end']}, so the CV months "
                 f"helped pick it and its CV score is biased upward. The top-5 by the pre-CV window alone "
                 f"overlap in {ev_['top5_overlap_precv']}/5 features. The control reproduces "
                 f"the stored `lgbm_fs_selected_clean` ({_f(ctl.get('cv'))} vs {CONTROL_CLEAN_CV}).\n")

    L.append("## Three strongest cases\n")
    L.append(ev_.get("strongest_cases_md", "_to be written_") + "\n")

    L.append("## What the bhavcopy already gives the pilot\n")
    L.append("Seven of the ten microstructure features read fields the pilot never touches: `trades`, "
             "`vwap`, `last`, the CA-adjusted `prev_close` and delivery value. Three are re-expressions "
             "of pilot features: `trades_z_20` of `vol_z_20`, `deliv_value_share_20` of "
             "`deliv_pct_sma_20`, and `range_position_20` of `close_pos_in_range`/`accum_20`. "
             f"The sector proxy has {cdiag['n_tickers']} tickers in 12 clusters. Its mean within-cluster "
             f"residual correlation is {cdiag['mean_within_cluster_resid_corr']}, against "
             f"{cdiag['mean_between_cluster_resid_corr']} between clusters, and it covers "
             f"{cdiag['row_coverage_overall']:.0%} of rows. It was fit once on "
             f"{cdiag['window'][0]} to {cdiag['window'][1]}, so it is point-in-time for every test fold. "
             "For training rows before Feb-2026, the grouping looks ahead; cluster ICs are also reported "
             "from Feb-2026 in the JSON.\n")

    L.append("## External-data gap list (what this repo cannot build)\n")
    L.append("| data | what it would add | mechanism | NSE source |")
    L.append("|---|---|---|---|")
    for d in EXTERNAL_DATA:
        L.append(f"| {d['data']} | {d['adds']} | {d['mechanism']} | {d['source']} |")
    L.append("")

    L.append("## What a 6-month sample can and cannot decide\n")
    L.append(ev_.get("limits_md", "_to be written_") + "\n")
    REPORT_MD.write_text("\n".join(L))
    print(f"[report] wrote {REPORT_MD}")


def strongest_cases_md(ev_: dict) -> str:
    S, ab = ev_["ic_summary"], ev_.get("ab", {})
    ranked = sorted(NEW_FEATURES, key=lambda f: -_abs_t(S[f]["resid_full"]))
    picked, seen = [], set()
    for f in ranked:
        canon = RANK_EQUIV.get(f, f)          # cs_rank twin -> raw name
        if canon in seen:
            continue
        seen.add(canon)
        picked.append(f)
        if len(picked) == 3:
            break
    lines = []
    for f in picked:
        s = S[f]
        in_v = [k for k, v in ab.items() if k != "control" and
                (f in v["features"] or RANK_EQUIV.get(f) in v["features"]
                 or {vv: kk for kk, vv in RANK_EQUIV.items()}.get(f) in v["features"])]
        ab_txt = "; ".join(f"`lgbm_suff_{k}` {_f(ab[k]['cv'])} ({'pass' if ab[k]['passes'] else 'fail'})"
                           for k in in_v) or "not in any variant"
        q = s["resid_full"].get("q_bh")
        clears = (q is not None and q <= BH_Q) and any(ab[k]["passes"] for k in in_v)
        a40 = s.get("resid_allbase_full", {})
        lines.append(
            f"- `{f}`: residual IC {_f(s['resid_full']['mean_ic'], 4, True)}, "
            f"t {_f(s['resid_full']['t'], 2, True)}, q {_f(q, 3)}; against all 40 pilot "
            f"features {_f(a40.get('mean_ic'), 4, True)} (t {_f(a40.get('t'), 2, True)}); sign held in "
            f"{s['resid_full']['sign_consistency']:.0%} of {s['resid_full']['n_months']} months; "
            f"after the quadratic control {_f(s['resid_quad_full']['mean_ic'], 4, True)}; "
            f"CV months {_f(s['resid_cvtest']['mean_ic'], 4, True)}. A/B: {ab_txt}. "
            f"**{'Clears the bar.' if clears else 'Does not clear the bar.'}**")
    return "\n".join(lines)


def limits_md(ev_: dict) -> str:
    S = ev_["ic_summary"]
    sds = [S[f]["resid_full"]["ic_std"] for f in NEW_FEATURES
           if S[f]["resid_full"].get("ic_std") is not None and np.isfinite(S[f]["resid_full"]["ic_std"])]
    n_m = max(S[f]["resid_full"]["n_months"] for f in NEW_FEATURES)
    mde = 2.13 * float(np.median(sds)) / np.sqrt(n_m) if sds else float("nan")
    ab = ev_.get("ab", {})
    stds = [v["cv_std"] for v in ab.values()]
    se_cv = float(np.median(stds)) / np.sqrt(4) if stds else float("nan")
    return (
        f"- **Can decide:** whether a feature carries a large, steady signal the champion lacks. "
        f"With {n_m} monthly ICs and a median monthly residual-IC std of {np.median(sds):.3f}, "
        f"the smallest residual IC detectable at 5% is about {mde:.3f}. Anything weaker is "
        f"indistinguishable from zero here. The test also catches gross failures: no variant "
        f"may sit below 0.50 in any fold.\n"
        f"- **Cannot decide:** gains of about +0.005 AUC. Four CV folds give a standard error on mean "
        f"CV AUC of about {se_cv:.3f}, so the pass mark sits within about one standard error of the control. "
        f"A pass would still need confirmation and a fail does not prove the gain is zero. The sample "
        f"also cannot decide anything that needs a cycle. It holds one regime break (March 2026) and "
        f"only 7 observable months of `mom_12_1`. Signals that pay only in some regimes, such as "
        f"cluster rotation, are out of reach, as is seasonality, because the archive calendar is simulated.\n"
        f"- **Adjacent ICs overlap.** Labels span 20 sessions, so adjacent daily ICs share most of their window "
        f"and monthly t-stats run slightly optimistic. Monthly means are used for that reason. The "
        f"5-year walk-forward (~60 monthly folds) is where a +0.005 effect becomes decidable. Re-run "
        f"this module on that dataset before closing the question.")


# ========================================================================= #
# main
# ========================================================================= #

def _jsonable(o):
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else round(float(o), 6)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-build", action="store_true")
    ap.add_argument("--skip-ab", action="store_true")
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args()
    t0 = time.perf_counter()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    splits = json.loads((DATA_DIR / "splits.json").read_text())

    if args.report_only:
        evd = json.loads(EVIDENCE_JSON.read_text())
        evd["external_data_gaps"] = EXTERNAL_DATA
        evd["pilot_overlap"] = PILOT_OVERLAP
        evd["strongest_cases_md"] = strongest_cases_md(evd)
        evd["limits_md"] = limits_md(evd)
        EVIDENCE_JSON.write_text(json.dumps(evd, indent=1))
        write_report(evd)
        return

    if args.skip_build and OUT_PARQUET.exists():
        out = pd.read_parquet(OUT_PARQUET)
        out["date"] = pd.to_datetime(out["date"])
        manifest = json.loads(MANIFEST_JSON.read_text())
    else:
        out, manifest = build()

    base_feats = json.loads((DATA_DIR / "manifest.json").read_text())["features"]
    fe_feats = json.loads((DATA_DIR / "manifest_fe.json").read_text())["new_features"]
    fe = pd.read_parquet(DATA_DIR / "model_dataset_fe.parquet", columns=ID + fe_feats)
    fe["date"] = pd.to_datetime(fe["date"])
    assert (fe["ticker"].to_numpy() == out["ticker"].to_numpy()).all()
    assert (fe["date"].to_numpy() == out["date"].to_numpy()).all()

    # ---- C. unique-information test (reads the label: evidence only) -------
    mask = out["label_beat_mkt_20d"].notna() & out["y_clean_20d"].astype(bool)
    base40 = [c for c in base_feats if not c.endswith("_isnan")]
    lab = out.loc[mask, ID + ["y_excess_20d"] + base40 + NEW_FEATURES].reset_index(drop=True)
    labfe = pd.concat([lab[ID + ["y_excess_20d"] + CHAMPION],
                       fe.loc[mask.to_numpy(), fe_feats].reset_index(drop=True)], axis=1)
    t1 = time.perf_counter()
    res = ic_study(lab, NEW_FEATURES + ["deliv_pct_sma_20"])
    summary = summarize_ic(res, NEW_FEATURES, splits)
    sanity = mstats(res["deliv_pct_sma_20"]["resid"])
    sanity_share = float(np.max(list(res["deliv_pct_sma_20"]["resid_share"].values())))
    print(f"[ic] new features done ({time.perf_counter() - t1:.0f}s); sanity: champion "
          f"feature deliv_pct_sma_20 max residual variance share {sanity_share:.1e}, "
          f"residual IC {sanity['mean_ic']:+.1e} (must be ~0)")
    assert sanity_share < 1e-10 and abs(sanity["mean_ic"]) < 1e-12, "orthogonalization sanity failed"
    res_all = ic_study(lab, NEW_FEATURES, controls=base40, quad=False)
    for f in NEW_FEATURES:
        summary[f]["resid_allbase_full"] = mstats(res_all[f]["resid"])
        summary[f]["resid_share_median"] = float(np.median(list(res[f]["resid_share"].values())))
    print(f"[ic] residual vs all 40 pilot base features done ({time.perf_counter() - t1:.0f}s)")
    nonchamp = [c for c in base40 if c not in CHAMPION]
    res_b = ic_study(lab, nonchamp, quad=False)
    ref_base = {f: {"raw_full": mstats(res_b[f]["raw"]), "resid_full": mstats(res_b[f]["resid"])}
                for f in nonchamp}
    print(f"[ic] non-champion pilot-feature reference done ({time.perf_counter() - t1:.0f}s)")
    fe_keep = [f for f in fe_feats if not f.startswith("mkt_")]   # mkt_* constant per date
    res_fe = ic_study(labfe, fe_keep)
    ref = {f: {"raw_full": mstats(res_fe[f]["raw"]), "resid_full": mstats(res_fe[f]["resid"]),
               "resid_quad_full": mstats(res_fe[f]["resid_quad"])} for f in fe_keep}
    print(f"[ic] engineered-reference done ({time.perf_counter() - t1:.0f}s)")

    ranked = sorted(NEW_FEATURES, key=lambda f: -_abs_t(summary[f]["resid_full"]))
    print("\n residual-IC table (full sample, ranked by |resid t|):")
    print(f" {'feature':<22s} {'rawIC':>8s} {'raw_t':>6s} {'resIC':>8s} {'res_t':>6s} "
          f"{'q':>6s} {'resQ':>8s} {'cvIC':>8s} {'hoIC':>8s} {'pitIC':>8s} {'all40':>8s} {'t40':>6s}")
    for f in ranked:
        s = summary[f]
        print(f" {f:<22s} {_f(s['raw_full']['mean_ic'], 4, True):>8s} "
              f"{_f(s['raw_full']['t'], 2, True):>6s} {_f(s['resid_full']['mean_ic'], 4, True):>8s} "
              f"{_f(s['resid_full']['t'], 2, True):>6s} {_f(s['resid_full'].get('q_bh'), 3):>6s} "
              f"{_f(s['resid_quad_full']['mean_ic'], 4, True):>8s} "
              f"{_f(s['resid_cvtest']['mean_ic'], 4, True):>8s} "
              f"{_f(s['resid_holdout']['mean_ic'], 4, True):>8s} "
              f"{_f(s['resid_pit_cluster']['mean_ic'], 4, True):>8s} "
              f"{_f(s['resid_allbase_full']['mean_ic'], 4, True):>8s} "
              f"{_f(s['resid_allbase_full']['t'], 2, True):>6s}")
    rb = sorted(ref_base, key=lambda f: -_abs_t(ref_base[f]["resid_full"]))[:8]
    print(" non-champion pilot features, residual vs champion (top 8): " + ", ".join(
        f"{f} {_f(ref_base[f]['resid_full']['mean_ic'], 4, True)} (t {_f(ref_base[f]['resid_full']['t'], 2, True)})"
        for f in rb))

    top5 = select_top(summary, "resid_sel")
    top5_full = select_top(summary, "resid_full")
    top5_precv = select_top(summary, "resid_precv")
    print(f"\n top-5 (selection window): {top5}\n top-5 (full): {top5_full}\n "
          f"top-5 (pre-CV only): {top5_precv}")

    existing = [c for c in base_feats if not c.endswith("_isnan")] + fe_feats
    red = redundancy(out.join(fe[fe_feats]), existing)

    evd = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "generated_by": "ml/feature_sufficiency.py (seed 108)",
        "splits": splits, "champion": CHAMPION, "new_features": NEW_FEATURES,
        "groups": GROUPS, "pilot_overlap": PILOT_OVERLAP,
        "rules": {"bh_q": BH_Q, "pass_mark": PASS_MARK, "fold_floor": FOLD_FLOOR,
                  "control_clean_cv": CONTROL_CLEAN_CV},
        "ic_method": ("per-date Spearman vs y_excess_20d on label notna & y_clean rows, "
                      ">=100 names/date, averaged within calendar month; t = mean/(std/sqrt(n_months)); "
                      "residual IC = Spearman(y, residual of the feature's per-date rank after OLS on "
                      "[1, champion per-date centered ranks (NaN->0), NaN indicators]); 'quad' adds "
                      "squared ranks; BH across the 23 new features (rank-equivalent pairs included, "
                      "conservative)"),
        "orthogonalization_sanity": {"feature": "deliv_pct_sma_20 (a champion feature)",
                                     "max_residual_variance_share": sanity_share,
                                     "resid_mean_ic": sanity["mean_ic"]},
        "ic_summary": summary, "ic_reference_engineered": ref,
        "ic_reference_pilot_nonchampion": ref_base,
        "top5": top5, "top5_full_window": top5_full, "top5_precv_window": top5_precv,
        "top5_overlap_precv": len(set(top5) & set(top5_precv)),
        "top5_overlap_full": len(set(top5) & set(top5_full)),
        "redundancy_vs_existing": red, "manifest": manifest,
        "external_data_gaps": EXTERNAL_DATA,
    }

    if not args.skip_ab:
        feats_all = base_feats + NEW_FEATURES
        t2 = time.perf_counter()
        evd["ab"] = run_ab(out, feats_all, splits, top5)
        print(f"[ab] done ({time.perf_counter() - t2:.0f}s)")
        evd["bootstrap"] = paired_bootstrap(list(evd["ab"].keys()), splits)
        print(f"[boot] done ({time.perf_counter() - t2:.0f}s)")
        for k, v in evd["ab"].items():
            b = evd["bootstrap"]["results"][k]
            print(f"  {k:<16s} cv={v['cv']:.4f} min_fold={v['min_fold']:.4f} "
                  f"holdout={v['holdout']:.4f} dCV={b['delta_cv_vs_control']:+.4f} "
                  f"[{b['delta_cv_ci95'][0]:+.4f},{b['delta_cv_ci95'][1]:+.4f}] "
                  f"pass={v['passes']}")
        evd["verdict"] = {
            "sufficient_for_this_sample": not any(v["passes"] for k, v in evd["ab"].items()
                                                  if k != "control"),
            "passing_variants": [k for k, v in evd["ab"].items() if k != "control" and v["passes"]],
            "features_new_information_bh": [f for f in NEW_FEATURES
                                            if (summary[f]["resid_full"].get("q_bh") or 1) <= BH_Q],
        }
    elif EVIDENCE_JSON.exists():
        old = json.loads(EVIDENCE_JSON.read_text())
        for k in ("ab", "bootstrap", "verdict"):
            if k in old:
                evd[k] = old[k]

    evd = _jsonable(evd)
    evd["strongest_cases_md"] = strongest_cases_md(evd)
    evd["limits_md"] = limits_md(evd)
    EVIDENCE_JSON.write_text(json.dumps(evd, indent=1))
    write_report(evd)
    print(f"[done] {time.perf_counter() - t0:.0f}s")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Label-design study: which forward-return label do the features predict,
which does the model predict, and which survives trading costs?

Management's question: "How good are the features with respect to the labels?
Do the features have predicting power with respect to each type of label we
created? Which label should we model?"

Pipeline (seed 108, OMP_NUM_THREADS=2; read-only on ml/data/)
-------------------------------------------------------------
1. LABEL VARIANTS rebuilt from the raw EOD snapshot (series EQ/BE, UNADJUSTED
   prices) and joined to the modeling rows by (date, ticker):
     horizon h in {1,2,3,5,10,20,40} sessions
     x entry   cc: close[t+h]/close[t]-1   |   no: open[t+1+h]/open[t+1]-1
     x target  raw | ex = raw - per-date universe median (clean rows)
               | rank = per-date pct rank of ex | vs = ex / (max(vol_20,0.5%)*sqrt(h))
     + binaries raw>0 and ex>0.
   Each (h, entry) has its own clean mask, the y_clean_20d idea applied per
   window: positive entry/exit prices; EVERY bar of the forward window present
   on the market calendar; calendar span <= max(2.2*h, h+4) days (the h+4 floor
   stops 2.2*h from rejecting ordinary weekends at h<=3); no |1d move| > 22%
   inside the window (split/bonus/circuit poisoning on unadjusted prices).
   Market-wide holiday clusters (window span equal to the market calendar's
   span) are exempt from the span cap -- the all-bars check is the real
   suspension guard.
   vs is additionally masked where vol_20 is NaN or flag_split_20d == 1
   (trailing vol contaminated by an unadjusted split).
2. FEATURE x LABEL IC GRID: 40 base features x 28 distinct continuous labels.
   Per-date Spearman IC (>=100 names), averaged by calendar month (>=5 IC
   dates), monthly t-test, sign consistency, Newey-West t (overlap), and a
   Benjamini-Hochberg q over the whole grid. Per-date Spearman is invariant
   to per-date monotone transforms, so raw == ex == rank exactly (verified
   numerically below) -- the 56 nominal continuous variants are 28 distinct
   labels (14 ex-family + 14 vs) and 40 x 28 = 1,120 hypotheses.
   Binary variants: pooled AUC (as the harness measures a model) and mean
   per-date (cross-sectional) AUC with its own monthly t-test / BH family.
   A month-sign-flip null (same random sign per calendar month for every
   test, preserving the cross-test dependence) gives the number of BH
   discoveries chance alone produces on this grid.
3. PER-LABEL SUMMARY: # features at q<0.05 / q<0.10, top-5, and the honest
   composite: features with q<0.10 selected on the first 8 months only
   (BH over the whole grid restricted to those months), sign-aligned per-date
   cs-ranks averaged, IC reported in-sample and out-of-sample (OOS dates start
   h(+1) sessions after the last selection date). Top-5-by-|t| composite as a
   fallback when the FDR filter selects nothing.
4. MODEL LEVEL: the pilot champion LightGBM config on all 51 manifest features
   through the shared harness (purged walk-forward, 22-session embargo) for
   ex>0 next-open at h in {2,3,5,10,20}, raw>0 close-to-close at 5d and 20d,
   and a control on the existing beat_mkt_20d label. h=40 is skipped at model
   level: its label looks 41 sessions ahead, the embargo is 22, so train
   labels would overlap the test window (leak).
5. TRADABILITY: per-date top-minus-bottom decile spread, annualized x 252/h,
   minus 20 bps per side per rebalance (long-short = 4 sides; long-only top
   decile vs median = 2 sides), at assumed 100% turnover and at measured
   decile turnover.

Outputs: ml/results/label_study/ (JSON/CSV/TABLES.md; LABEL_STUDY.md is the
hand-written verdict) and ml/results/preds/label_study/ (harness preds +
label_variants.parquet). Never a bare JSON in ml/results/ (league glob).

Run:  cd /home/user/SuryaDhana_AI && python3 -m ml.label_study
"""
from __future__ import annotations

import os

os.environ.setdefault("OMP_NUM_THREADS", "2")

import argparse
import hashlib
import json
import math
import time
from datetime import datetime

import numpy as np
import pandas as pd
from scipy import stats

import ml.evaluation as ev
from ml.evaluation import DATA_DIR, ML_DIR

SEED = 108
HORIZONS = (1, 2, 3, 5, 10, 20, 40)
ENTRIES = ("cc", "no")
MODEL_HORIZONS = (2, 3, 5, 10, 20)
SPLIT_MOVE = 0.22
SPAN_FACTOR = 2.2
VOL_FLOOR = 0.005
MIN_NAMES = 100
MIN_DATES_PER_MONTH = 5
MIN_CLASS = 10                 # per-date AUC needs >= 10 of each class
SEL_LAST_MONTH = "2026-01"     # selection window = first 8 months, 2025-06 .. 2026-01
COST_PER_SIDE = 0.0020         # 20 bps per side per rebalance
SESSIONS_PER_YEAR = 252
N_SIGNFLIP = 1000

OUT_DIR = ML_DIR / "results" / "label_study"
PRED_DIR = ML_DIR / "results" / "preds" / "label_study"

# ETF-like tickers (sensitivity only; no ISIN in the snapshot). Name pattern
# plus hand-checked operating companies that happen to match it.
ETF_PATTERN = r"(?:BEES|ETF|LIQUID|LIQID|GILT|BETF|SENSEX|NIFTY|GOLD|SILV|CASE$|360$|BND$|BETA$|ADD$)"
ETF_NAME_EXCEPTIONS = {"BETA", "SKYGOLD", "SILVERTUC", "SHANTIGOLD", "GOLDIAM",
                       "PNBGILTS", "DECNGOLD"}

LGBM_PARAMS = dict(num_leaves=63, learning_rate=0.05, n_estimators=300,
                   feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1,
                   min_data_in_leaf=200, num_threads=2, random_state=SEED)


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def span_cap(h: int) -> float:
    return max(SPAN_FACTOR * h, h + 4.0)


def steps_of(h: int, entry: str) -> int:
    """Bars after t touched by the label (entry next-open adds one)."""
    return h if entry == "cc" else h + 1


def vname(h: int, entry: str) -> str:
    return f"{entry}_{h}d"


def _f(x, nd=6):
    if x is None:
        return None
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return x
    if not math.isfinite(xf):
        return None
    return round(xf, nd)


# --------------------------------------------------------------------------- #
# 1. labels
# --------------------------------------------------------------------------- #
def build_price_labels() -> pd.DataFrame:
    """Forward labels on the full EQ/BE price panel (before the universe filter,
    like data.py), one row per (ticker, date)."""
    px = pd.read_parquet(DATA_DIR / "equity_eod_snapshot.parquet",
                         columns=["date", "ticker", "series", "open", "close"])
    px = px[px["series"].isin(["EQ", "BE"])].drop(columns="series")
    px["date"] = pd.to_datetime(px["date"])
    px = px.sort_values(["ticker", "date"]).reset_index(drop=True)
    if px.duplicated(["ticker", "date"]).any():
        raise RuntimeError("duplicate (ticker, date) rows in EQ/BE snapshot")
    cal = pd.DatetimeIndex(np.sort(px["date"].unique()))
    px["si"] = cal.get_indexer(px["date"]).astype(np.int64)
    g = px.groupby("ticker", sort=False)
    absret = g["close"].pct_change().abs()
    rev = absret.iloc[::-1]

    def fwd_absmax(w: int) -> pd.Series:
        # max |ret_1d| over bars t+1 .. t+w (same construction as data.py)
        return rev.rolling(w, min_periods=1).max().iloc[::-1].shift(-1)

    out = {"date": px["date"], "ticker": px["ticker"]}
    cal_days = cal.to_numpy()
    n_cal = len(cal_days)
    si = px["si"].to_numpy()
    for h in HORIZONS:
        cap = span_cap(h)
        for e in ENTRIES:
            k = steps_of(h, e)
            if e == "cc":
                p_in, d_in = px["close"], px["date"]
                p_out, d_out = g["close"].shift(-h), g["date"].shift(-h)
            else:
                p_in, d_in = g["open"].shift(-1), g["date"].shift(-1)
                p_out, d_out = g["open"].shift(-(h + 1)), g["date"].shift(-(h + 1))
            raw = p_out / p_in - 1.0
            exists = raw.notna() & (p_in > 0) & (p_out > 0)
            allbars = (g["si"].shift(-k) - px["si"]) == k
            # calendar span of the SAME window on the market calendar: a market-wide
            # holiday cluster (e.g. 26-Mar/31-Mar/03-Apr-2026: 5 sessions = 12 days)
            # is not a suspension, so it is exempt from the 2.2*h cap.
            i_in = si + (0 if e == "cc" else 1)
            i_out = si + k
            okc = i_out < n_cal
            mkt_span = np.full(len(px), np.nan)
            mkt_span[okc] = ((cal_days[i_out[okc]] - cal_days[i_in[okc]])
                             / np.timedelta64(1, "D"))
            span = (d_out - d_in).dt.days
            span_ok = (span <= cap) | (span <= pd.Series(mkt_span, index=px.index))
            nosplit = fwd_absmax(k) <= SPLIT_MOVE
            clean = exists & allbars & span_ok & nosplit
            # guard code: 0 no forward bar, 1 missing bars, 2 span, 3 split move, 4 clean
            code = np.full(len(px), 4, dtype=np.int8)
            code[~nosplit.to_numpy()] = 3
            code[~span_ok.to_numpy()] = 2
            code[~allbars.to_numpy()] = 1
            code[~exists.to_numpy()] = 0
            v = vname(h, e)
            out[f"raw_{v}"] = raw.where(clean).astype("float32")
            out[f"guard_{v}"] = pd.Series(code, index=px.index)
    return pd.DataFrame(out)


def attach_labels(md: pd.DataFrame, lab: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    keys = md[["date", "ticker"]].copy()
    keys["ticker"] = keys["ticker"].astype(str)
    lab = lab.copy()
    lab["ticker"] = lab["ticker"].astype(str)
    m = keys.merge(lab, on=["date", "ticker"], how="left", validate="one_to_one")
    if len(m) != len(md):
        raise RuntimeError("label merge changed row count")
    matched = float(m["guard_cc_1d"].notna().mean())
    lab_cols = [c for c in m.columns if c not in ("date", "ticker")]
    md = pd.concat([md.reset_index(drop=True), m[lab_cols].reset_index(drop=True)], axis=1)
    return md, {"model_rows_matched_in_snapshot": matched}


def add_cross_sectional(md: pd.DataFrame) -> pd.DataFrame:
    new = {}
    vol = md["vol_20"].astype("float64")
    vs_ok = vol.notna() & (md["flag_split_20d"] < 0.5)
    for h in HORIZONS:
        for e in ENTRIES:
            v = vname(h, e)
            raw = md[f"raw_{v}"].astype("float64")
            med = raw.groupby(md["date"]).transform("median")
            ex = raw - med
            new[f"clean_{v}"] = raw.notna()
            new[f"ex_{v}"] = ex.astype("float32")
            new[f"rank_{v}"] = ex.groupby(md["date"]).rank(pct=True).astype("float32")
            new[f"vs_{v}"] = (ex / (np.maximum(vol, VOL_FLOOR) * math.sqrt(h))
                              ).where(vs_ok & raw.notna()).astype("float32")
            new[f"bin_raw_{v}"] = (raw > 0).astype("float32").where(raw.notna())
            new[f"bin_ex_{v}"] = (ex > 0).astype("float32").where(ex.notna())
    return pd.concat([md, pd.DataFrame(new, index=md.index)], axis=1)


def validate_against_dataset(md: pd.DataFrame) -> dict:
    """Rebuilt labels vs the ones data.py wrote (same raw prices => must match)."""
    out = {}
    a = md["raw_cc_5d"].astype("float64")
    b = pd.to_numeric(md["fwd_ret_5d"], errors="coerce")
    both = a.notna() & b.notna()
    out["cc_5d_raw_vs_fwd_ret_5d"] = {
        "rows_compared": int(both.sum()),
        "max_abs_diff": _f((a[both] - b[both]).abs().max(), 9),
        "rows_dataset_has_but_masked_here": int((b.notna() & a.isna()).sum())}
    a = md["raw_no_20d"].astype("float64")
    b = md["y_raw_20d"].astype("float64")
    both = a.notna() & b.notna()
    out["no_20d_raw_vs_y_raw_20d"] = {
        "rows_compared": int(both.sum()),
        "max_abs_diff": _f((a[both] - b[both]).abs().max(), 9)}
    mine = md["clean_no_20d"].astype(bool)
    theirs = md["y_clean_20d"].astype(bool)
    out["no_20d_clean_vs_y_clean_20d"] = {
        "agree": _f((mine == theirs).mean()),
        "theirs_clean_mine_not": int((theirs & ~mine).sum()),
        "mine_clean_theirs_not": int((mine & ~theirs).sum())}
    both = md["ex_no_20d"].notna() & md["y_excess_20d"].notna() & theirs
    out["no_20d_ex_vs_y_excess_20d"] = {
        "pearson": _f(np.corrcoef(md.loc[both, "ex_no_20d"], md.loc[both, "y_excess_20d"])[0, 1], 8),
        "mean_abs_diff": _f((md.loc[both, "ex_no_20d"] - md.loc[both, "y_excess_20d"]).abs().mean(), 8),
        "note": "excess median here is over CLEAN universe rows; data.py used all non-null raw rows"}
    both = md["bin_ex_no_20d"].notna() & md["label_beat_mkt_20d"].notna() & theirs
    out["no_20d_binex_vs_label_beat_mkt_20d"] = {
        "agree": _f((md.loc[both, "bin_ex_no_20d"] == md.loc[both, "label_beat_mkt_20d"]).mean())}
    return out


def variant_stats(md: pd.DataFrame) -> dict:
    month = md["date"].dt.to_period("M").astype(str)
    out = {}
    n_all = len(md)
    guard_names = {0: "no_forward_bar", 1: "missing_bars", 2: "span_too_long",
                   3: "split_move_gt_22pct", 4: "clean"}
    for h in HORIZONS:
        for e in ENTRIES:
            v = vname(h, e)
            raw = md[f"raw_{v}"]
            ok = raw.notna()
            last = md.loc[ok, "date"].max()
            labelable = md["date"] <= last
            gc = md.loc[labelable, f"guard_{v}"].value_counts(normalize=True)
            rec = {"h": h, "entry": e,
                   "last_labeled_date": str(last.date()),
                   "coverage_all_rows": _f(ok.mean()),
                   "coverage_labelable_dates": _f(ok[labelable].mean()),
                   "n_valid": int(ok.sum()),
                   "mask_breakdown_labelable": {guard_names[int(k)]: _f(val) for k, val in gc.items()},
                   "targets": {}}
            for tgt in ("raw", "ex", "rank", "vs"):
                s = md[f"{tgt}_{v}"].astype("float64")
                okt = s.notna()
                per_date_mean = s.groupby(md["date"]).mean().dropna()
                per_date_std = s.groupby(md["date"]).std().dropna()
                t = {"n_valid": int(okt.sum()),
                     "coverage_all_rows": _f(okt.mean()),
                     "xs_std_mean": _f(per_date_std.mean()),
                     "xs_std_min": _f(per_date_std.min()),
                     "xs_std_max": _f(per_date_std.max()),
                     "per_date_mean_lag1_autocorr": (
                         None if tgt == "rank" else _f(per_date_mean.autocorr(1), 4)),
                     "mean": _f(s.mean()), "median": _f(s.median())}
                if tgt in ("raw", "ex"):
                    pos = (s > 0).astype(float).where(okt)
                    br = pos.groupby(month).mean().dropna()
                    br = br[s.groupby(month).count().reindex(br.index) >= 1000]
                    t["base_rate_overall"] = _f(pos.mean())
                    t["base_rate_month_min"] = _f(br.min())
                    t["base_rate_month_max"] = _f(br.max())
                    t["base_rate_month_argmin"] = br.idxmin()
                    t["base_rate_month_argmax"] = br.idxmax()
                    t["base_rate_by_month"] = {k: _f(x, 4) for k, x in br.items()}
                    # binary series of per-date base rate (overlap persistence)
                    t["per_date_base_rate_lag1_autocorr"] = _f(
                        pos.groupby(md["date"]).mean().dropna().autocorr(1), 4)
                rec["targets"][tgt] = t
            out[v] = rec
    return out


# --------------------------------------------------------------------------- #
# 2. IC machinery (rows sorted by date; per-date grouped sums via reduceat)
# --------------------------------------------------------------------------- #
def _starts(codes: np.ndarray) -> np.ndarray:
    return np.r_[0, np.flatnonzero(np.diff(codes)) + 1]


def grouped_rank(codes: np.ndarray, X: np.ndarray) -> np.ndarray:
    """Per-date average ranks, NaN kept as NaN (ranked among non-NaN only)."""
    if X.ndim == 1:
        return pd.Series(X).groupby(codes).rank(method="average").to_numpy(np.float64)
    return pd.DataFrame(X).groupby(codes).rank(method="average").to_numpy(np.float64)


class SortedRanker:
    """Sort a column once by (date, value); afterwards the exact per-date
    average rank among ANY row subset costs O(n) (no re-sort). Ties are
    averaged within the subset, exactly as pandas rank(method='average')."""

    def __init__(self, codes: np.ndarray, x: np.ndarray):
        self.n = len(x)
        iv = np.flatnonzero(~np.isnan(x))
        o = iv[np.lexsort((x[iv], codes[iv]))]
        cs, xs = codes[o], x[o]
        gflag = np.r_[True, cs[1:] != cs[:-1]] if len(o) else np.zeros(0, bool)
        rflag = gflag | np.r_[True, xs[1:] != xs[:-1]] if len(o) else np.zeros(0, bool)
        self.o = o
        self.run_starts = np.flatnonzero(rflag)
        self.run_len = np.diff(np.r_[self.run_starts, len(o)])
        g_of_run = (np.cumsum(gflag) - 1)[self.run_starts]
        self.gstart_run = np.r_[True, g_of_run[1:] != g_of_run[:-1]] if len(o) else np.zeros(0, bool)

    def rank(self, mask: np.ndarray) -> np.ndarray:
        out = np.full(self.n, np.nan)
        if len(self.o) == 0:
            return out
        sm = mask[self.o]
        c_run = np.add.reduceat(sm.astype(np.int64), self.run_starts)
        before_all = np.cumsum(c_run) - c_run
        base = np.maximum.accumulate(np.where(self.gstart_run, before_all, 0))
        avg = (before_all - base) + (c_run + 1) / 2.0
        r_sorted = np.repeat(avg, self.run_len)
        out[self.o[sm]] = r_sorted[sm]
        return out


def grouped_corr(codes: np.ndarray, RX: np.ndarray, RY: np.ndarray, min_n: int):
    st = _starts(codes)
    valid = ~(np.isnan(RX) | np.isnan(RY))
    X = np.where(valid, RX, 0.0)
    Y = np.where(valid, RY, 0.0)
    n = np.add.reduceat(valid.astype(np.float64), st, axis=0)
    sx = np.add.reduceat(X, st, axis=0)
    sy = np.add.reduceat(Y, st, axis=0)
    sxx = np.add.reduceat(X * X, st, axis=0)
    syy = np.add.reduceat(Y * Y, st, axis=0)
    sxy = np.add.reduceat(X * Y, st, axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        cov = sxy - sx * sy / n
        vx = sxx - sx * sx / n
        vy = syy - sy * sy / n
        r = cov / np.sqrt(vx * vy)
    r[(n < min_n) | (vx <= 1e-9) | (vy <= 1e-9)] = np.nan
    return codes[st], r


def per_date_spearman(codes: np.ndarray, X: np.ndarray, y: np.ndarray,
                      min_n: int = MIN_NAMES, RX: np.ndarray | None = None):
    """Exact per-date Spearman of every column of X with y (rows already
    restricted to y-valid). y is re-ranked on the joint non-NaN set of each
    feature (cached by NaN pattern)."""
    if RX is None:
        RX = grouped_rank(codes, X)
    ry_full = grouped_rank(codes, y)
    nanmask = np.isnan(X)
    RY = np.empty_like(RX)
    cache: dict[str, np.ndarray] = {}
    for j in range(X.shape[1]):
        col = nanmask[:, j]
        if not col.any():
            RY[:, j] = ry_full
            continue
        key = hashlib.md5(np.packbits(col).tobytes()).hexdigest()
        if key not in cache:
            cache[key] = grouped_rank(codes, np.where(col, np.nan, y))
        RY[:, j] = cache[key]
    return grouped_corr(codes, RX, RY, min_n)


def per_date_auc(codes: np.ndarray, RX: np.ndarray, b: np.ndarray,
                 min_n: int = MIN_NAMES, min_class: int = MIN_CLASS):
    """Mean-rank AUC per date; RX = per-date ranks among non-NaN feature rows."""
    st = _starts(codes)
    valid = ~np.isnan(RX)
    bb = b[:, None].astype(np.float64)
    n = np.add.reduceat(valid.astype(np.float64), st, axis=0)
    n1 = np.add.reduceat(valid * bb, st, axis=0)
    S = np.add.reduceat(np.where(valid, RX, 0.0) * bb, st, axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        auc = (S - n1 * (n1 + 1) / 2.0) / (n1 * (n - n1))
    auc[(n < min_n) | (n1 < min_class) | ((n - n1) < min_class)] = np.nan
    return codes[st], auc


def pooled_auc(X: np.ndarray, bins: list[np.ndarray]) -> list[np.ndarray]:
    """AUC over all rows (the harness's view: mixes cross-section and timing)."""
    k = X.shape[1]
    outs = [np.full(k, np.nan) for _ in bins]
    for j in range(k):
        v = ~np.isnan(X[:, j])
        if v.sum() < 1000:
            continue
        r = stats.rankdata(X[v, j])
        for i, b in enumerate(bins):
            bb = b[v]
            n1 = bb.sum()
            n0 = len(bb) - n1
            if n1 > 0 and n0 > 0:
                outs[i][j] = (r[bb == 1].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0)
    return outs


def monthly_matrix(dates: pd.DatetimeIndex, D: np.ndarray) -> pd.DataFrame:
    df = pd.DataFrame(D, index=pd.DatetimeIndex(dates))
    per = df.index.to_period("M")
    mean = df.groupby(per).mean()
    cnt = df.groupby(per).count()
    return mean.where(cnt >= MIN_DATES_PER_MONTH)


def nw_tstat(x: np.ndarray, lag: int) -> float:
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 3:
        return float("nan")
    m = x.mean()
    d = x - m
    var = (d @ d) / n
    for L in range(1, min(lag, n - 1) + 1):
        w = 1.0 - L / (lag + 1.0)
        var += 2.0 * w * (d[L:] @ d[:-L]) / n
    if var <= 0:
        return float("nan")
    return float(m / math.sqrt(var / n))


def column_tests(M: np.ndarray, center: float = 0.0, nw_lag: int = 0) -> dict:
    """Monthly t-tests per column of M (months x k, NaN allowed)."""
    import warnings
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    X = M - center
    n = np.sum(~np.isnan(X), axis=0).astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.nanmean(X, axis=0)
        sd = np.nanstd(X, axis=0, ddof=1)
        t = mean / (sd / np.sqrt(n))
        p = 2.0 * stats.t.sf(np.abs(t), np.maximum(n - 1, 1))
        sgn = np.sign(mean)
        cons = np.nansum((np.sign(X) == sgn[None, :]) & ~np.isnan(X), axis=0) / n
    t[n < 3] = np.nan
    p[n < 3] = np.nan
    t_nw = np.array([nw_tstat(X[:, j], nw_lag) if nw_lag > 0 else t[j]
                     for j in range(X.shape[1])])
    with np.errstate(invalid="ignore"):
        p_nw = 2.0 * stats.t.sf(np.abs(t_nw), np.maximum(n - 1, 1))
    return {"mean": mean, "sd": sd, "t": t, "p": p, "t_nw": t_nw, "p_nw": p_nw,
            "sign_cons": cons, "n_months": n}


def bh_q(p: np.ndarray) -> np.ndarray:
    p = np.asarray(p, dtype=float)
    q = np.full(p.shape, np.nan)
    ok = ~np.isnan(p)
    pv = p[ok]
    m = pv.size
    if m == 0:
        return q
    order = np.argsort(pv)
    ranked = pv[order] * m / np.arange(1, m + 1)
    qs = np.minimum.accumulate(ranked[::-1])[::-1]
    tmp = np.empty(m)
    tmp[order] = np.minimum(qs, 1.0)
    q[ok] = tmp
    return q


def nw_lag_for(h: int) -> int:
    """Months of overlap carried by monthly ICs of an h-session label."""
    return 0 if h <= 5 else (1 if h <= 20 else 2)


# --------------------------------------------------------------------------- #
# 2b. the grid
# --------------------------------------------------------------------------- #
def ic_grid(md: pd.DataFrame, feats: list[str], row_filter: np.ndarray | None = None,
            with_auc: bool = True, targets=("ex", "vs"), rankers: dict | None = None) -> dict:
    """Daily IC (and per-date / pooled AUC) for every (h, entry, target).
    All matrices are indexed by the full model calendar (dates_all)."""
    codes_all = pd.factorize(md["date"], sort=True)[0]
    if np.any(np.diff(codes_all) < 0):
        raise RuntimeError("model rows must be sorted by date")
    dates_all = np.sort(md["date"].unique())
    Fall = md[feats].to_numpy(np.float64)
    xvalid = ~np.isnan(Fall)
    k = len(feats)
    if rankers is None:
        rankers = {}
    if "date" not in rankers:
        rankers["date"] = [SortedRanker(codes_all, Fall[:, j]) for j in range(k)]
    if with_auc and "pooled" not in rankers:
        zero = np.zeros(len(md), dtype=np.int64)
        rankers["pooled"] = [SortedRanker(zero, Fall[:, j]) for j in range(k)]
    res = {"ic": {}, "auc_xs": {}, "auc_pooled": {}, "dates": dates_all}

    def spearman(mask, ycol):
        RX = np.column_stack([r.rank(mask) for r in rankers["date"]])
        yr = SortedRanker(codes_all, np.where(mask, ycol, np.nan))
        RY = np.empty_like(RX)
        cache = {}
        for j in range(k):
            mj = mask & xvalid[:, j]
            key = hashlib.md5(np.packbits(mj).tobytes()).hexdigest()
            if key not in cache:
                cache[key] = yr.rank(mj)
            RY[:, j] = cache[key]
        _, r = grouped_corr(codes_all, RX, RY, MIN_NAMES)
        return RX, r

    for h in HORIZONS:
        for e in ENTRIES:
            v = vname(h, e)
            base = md[f"raw_{v}"].notna().to_numpy()
            if row_filter is not None:
                base &= row_filter
            RX = None
            if "ex" in targets:
                RX, r = spearman(base, md[f"ex_{v}"].to_numpy(np.float64))
                res["ic"][f"ex_{v}"] = (dates_all, r)
            if with_auc:
                if RX is None:
                    RX = np.column_stack([rr.rank(base) for rr in rankers["date"]])
                for bn in ("raw", "ex"):
                    b = np.nan_to_num(md[f"bin_{bn}_{v}"].to_numpy(np.float64), nan=0.0)
                    _, a = per_date_auc(codes_all, RX, b)
                    res["auc_xs"][f"bin_{bn}_{v}"] = (dates_all, a)
                    pa = np.full(k, np.nan)
                    for j in range(k):
                        rg = rankers["pooled"][j].rank(base)
                        ok = ~np.isnan(rg)
                        bb = b[ok]
                        n1 = bb.sum()
                        n0 = ok.sum() - n1
                        if n1 > 0 and n0 > 0:
                            pa[j] = (rg[ok][bb == 1].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0)
                    res["auc_pooled"][f"bin_{bn}_{v}"] = pa
            if "vs" in targets:
                yv = md[f"vs_{v}"].to_numpy(np.float64)
                _, r = spearman(base & ~np.isnan(yv), yv)
                res["ic"][f"vs_{v}"] = (dates_all, r)
            log(f"  grid {v}: {int(base.sum()):,} rows")
    res["rankers"] = rankers
    return res


def summarize_grid(res: dict, feats: list[str], sel_last: str = SEL_LAST_MONTH) -> dict:
    """Monthly stats + BH over the whole grid (full sample and selection window)."""
    labels = list(res["ic"].keys())
    full, sel, monthly = {}, {}, {}
    for lab in labels:
        dates, D = res["ic"][lab]
        h = int(lab.split("_")[-1][:-1])
        M = monthly_matrix(pd.DatetimeIndex(dates), D)
        monthly[lab] = M
        full[lab] = column_tests(M.to_numpy(), 0.0, nw_lag_for(h))
        Ms = M[M.index <= pd.Period(sel_last, "M")]
        sel[lab] = column_tests(Ms.to_numpy(), 0.0, 0)
    # BH over the whole grid
    for store in (full, sel):
        pv = np.concatenate([store[lab]["p"] for lab in labels])
        q = bh_q(pv)
        pv_nw = np.concatenate([store[lab]["p_nw"] for lab in labels])
        q_nw = bh_q(pv_nw)
        k = len(feats)
        for i, lab in enumerate(labels):
            store[lab]["q"] = q[i * k:(i + 1) * k]
            store[lab]["q_nw"] = q_nw[i * k:(i + 1) * k]
    return {"labels": labels, "full": full, "sel": sel, "monthly": monthly,
            "m_hypotheses": int(sum(np.sum(~np.isnan(full[lab]["p"])) for lab in labels))}


def signflip_null(summary: dict, feats: list[str], n_draws: int = N_SIGNFLIP) -> dict:
    """Month-sign-flip null preserving cross-test dependence: one random sign
    per calendar month, applied to every feature x label monthly IC."""
    labels = summary["labels"]
    months = sorted(set().union(*[set(summary["monthly"][lab].index) for lab in labels]))
    cols = []
    for lab in labels:
        M = summary["monthly"][lab].reindex(months)
        cols.append(M.to_numpy())
    A = np.concatenate(cols, axis=1)                      # months x (labels*feats)
    keep = np.sum(~np.isnan(A), axis=0) >= 3
    A = A[:, keep]
    rng = np.random.default_rng(SEED)

    def discoveries(B):
        n = np.sum(~np.isnan(B), axis=0)
        with np.errstate(invalid="ignore", divide="ignore"):
            t = np.nanmean(B, 0) / (np.nanstd(B, 0, ddof=1) / np.sqrt(n))
        p = 2.0 * stats.t.sf(np.abs(t), n - 1)
        q = bh_q(p)
        return int(np.sum(p < 0.05)), int(np.sum(q < 0.05)), int(np.sum(q < 0.10))

    obs = discoveries(A)
    draws = np.array([discoveries(A * rng.choice([-1.0, 1.0], size=len(months))[:, None])
                      for _ in range(n_draws)])
    return {
        "n_tests": int(A.shape[1]), "n_months": len(months), "n_draws": n_draws,
        "observed": {"p_lt_0.05": obs[0], "q_lt_0.05": obs[1], "q_lt_0.10": obs[2]},
        "null_mean": {"p_lt_0.05": _f(draws[:, 0].mean(), 2), "q_lt_0.05": _f(draws[:, 1].mean(), 2),
                      "q_lt_0.10": _f(draws[:, 2].mean(), 2)},
        "null_p95": {"p_lt_0.05": _f(np.percentile(draws[:, 0], 95), 1),
                     "q_lt_0.05": _f(np.percentile(draws[:, 1], 95), 1),
                     "q_lt_0.10": _f(np.percentile(draws[:, 2], 95), 1)},
        "null_p99": {"p_lt_0.05": _f(np.percentile(draws[:, 0], 99), 1),
                     "q_lt_0.05": _f(np.percentile(draws[:, 1], 99), 1),
                     "q_lt_0.10": _f(np.percentile(draws[:, 2], 99), 1)},
        "frac_null_draws_with_any_q05_discovery": _f(np.mean(draws[:, 1] > 0), 3),
        "p_value_obs_q05": _f((1 + np.sum(draws[:, 1] >= obs[1])) / (1 + n_draws), 4),
        "note": "same random sign per calendar month for all tests (keeps the cross-test "
                "dependence: correlated features, nested horizons, duplicate rank features)",
    }


# --------------------------------------------------------------------------- #
# 3. composite (select on first 8 months, evaluate OOS after an h-embargo)
# --------------------------------------------------------------------------- #
def composite_eval(md: pd.DataFrame, feats: list[str], summary: dict,
                   ranks_all: np.ndarray, codes_all: np.ndarray, dates_all: np.ndarray) -> dict:
    out = {}
    sel_end = pd.Period(SEL_LAST_MONTH, "M").end_time.normalize()
    cal = pd.DatetimeIndex(dates_all)
    last_sel_pos = int(np.searchsorted(cal, sel_end, side="right") - 1)
    for lab in summary["labels"]:
        tgt, e, hd = lab.split("_")
        h = int(hd[:-1])
        st = summary["sel"][lab]
        oos_first = cal[min(last_sel_pos + steps_of(h, e) + 1, len(cal) - 1)]
        variants = {}
        q = st["q"]
        sel_q = [j for j in range(len(feats)) if np.isfinite(q[j]) and q[j] < 0.10]
        tt = np.where(np.isfinite(st["t"]), np.abs(st["t"]), -1)
        sel_top5 = [int(j) for j in np.argsort(-tt)[:5] if tt[j] > 0]
        for name, sel_idx in (("fdr_q10", sel_q), ("top5_abs_t", sel_top5)):
            if not sel_idx:
                variants[name] = {"n_selected": 0, "features": [], "is_ic": None, "oos_ic": None}
                continue
            signs = np.sign(st["mean"][sel_idx])
            R = ranks_all[:, sel_idx].astype(np.float64)
            R = np.where(signs[None, :] > 0, R, 1.0 - R)
            with np.errstate(invalid="ignore"):
                comp = np.nanmean(R, axis=1)
            y = md[lab].to_numpy(np.float64)
            ok = ~np.isnan(y) & ~np.isnan(comp)
            idx = np.flatnonzero(ok)
            gc, r = per_date_spearman(codes_all[idx], comp[idx][:, None], y[idx])
            d = pd.DatetimeIndex(dates_all[gc])
            daily = pd.Series(r[:, 0], index=d)
            is_d = daily[d <= sel_end]
            oos_d = daily[d >= oos_first]
            Mis = monthly_matrix(is_d.index, is_d.to_numpy()[:, None])
            Moos = monthly_matrix(oos_d.index, oos_d.to_numpy()[:, None])
            tis = column_tests(Mis.to_numpy())
            toos = column_tests(Moos.to_numpy(), 0.0, nw_lag_for(h))
            variants[name] = {
                "n_selected": len(sel_idx),
                "features": [{"feature": feats[j], "sign": int(np.sign(st["mean"][j])),
                              "is_mean_ic": _f(st["mean"][j], 5), "is_t": _f(st["t"][j], 2),
                              "is_q": _f(st["q"][j], 4)} for j in sel_idx],
                "is_ic": _f(tis["mean"][0], 5), "is_t": _f(tis["t"][0], 2),
                "is_months": int(tis["n_months"][0]),
                "oos_ic": _f(toos["mean"][0], 5), "oos_t": _f(toos["t"][0], 2),
                "oos_t_nw": _f(toos["t_nw"][0], 2),
                "oos_months": int(toos["n_months"][0]),
                "oos_sign_consistency": _f(toos["sign_cons"][0], 3),
                "oos_monthly_ic": {str(k): _f(x, 4) for k, x in Moos.iloc[:, 0].dropna().items()},
                "oos_first_date": str(oos_first.date()),
            }
            variants[name]["_score"] = comp  # dropped before JSON
        out[lab] = variants
    return out


# --------------------------------------------------------------------------- #
# 4/5. per-date economics of any score
# --------------------------------------------------------------------------- #
def per_date_econ(df: pd.DataFrame, score: str, ret: str, h: int,
                  y: str | None = None) -> dict:
    """Per-date rank-IC, decile spreads, decile turnover and cost-adjusted
    annualization for a score vs an h-session forward return column."""
    d = df[["date", "ticker", score, ret] + ([y] if y else [])].dropna(subset=[score, ret])
    d = d.sort_values(["date", "ticker"]).reset_index(drop=True)
    codes = pd.factorize(d["date"], sort=True)[0]
    dates = np.sort(d["date"].unique())
    gc, ic = per_date_spearman(codes, d[[score]].to_numpy(np.float64), d[ret].to_numpy(np.float64))
    ic_s = pd.Series(ic[:, 0], index=pd.DatetimeIndex(dates[gc])).dropna()
    rk = d.groupby("date")[score].rank(pct=True, method="first")
    top = rk > 0.9
    bot = rk <= 0.1
    g = d.groupby("date")
    top_m = d[ret].where(top).groupby(d["date"]).mean()
    bot_m = d[ret].where(bot).groupby(d["date"]).mean()
    med = g[ret].median()
    spread = (top_m - bot_m).dropna()
    top_ex = (top_m - med).dropna()
    out = {"n_dates": int(len(ic_s)),
           "rank_ic_mean": _f(ic_s.mean(), 5),
           "rank_ic_t_daily_naive": _f(ic_s.mean() / (ic_s.std(ddof=1) / math.sqrt(len(ic_s))), 2),
           "rank_ic_t_nw": _f(nw_tstat(ic_s.to_numpy(), max(h - 1, 0)) if h > 1 else
                              ic_s.mean() / (ic_s.std(ddof=1) / math.sqrt(len(ic_s))), 2),
           "rank_ic_pos_frac": _f((ic_s > 0).mean(), 3)}
    Mm = monthly_matrix(ic_s.index, ic_s.to_numpy()[:, None])
    tm = column_tests(Mm.to_numpy())
    out["rank_ic_monthly"] = {str(k): _f(x, 4) for k, x in Mm.iloc[:, 0].dropna().items()}
    out["rank_ic_t_monthly"] = _f(tm["t"][0], 2)
    if y:
        b = d[y].to_numpy(np.float64)
        RX = grouped_rank(codes, d[[score]].to_numpy(np.float64))
        gc2, a = per_date_auc(codes, RX, b)
        a_s = pd.Series(a[:, 0], index=pd.DatetimeIndex(dates[gc2])).dropna()
        out["xs_auc_mean"] = _f(a_s.mean(), 5)
    # spreads (mean over all dates = expected per-period spread; overlapping windows)
    S = float(spread.mean())
    T = float(top_ex.mean())
    out["decile_spread_per_period"] = _f(S, 5)
    out["decile_spread_t_nw"] = _f(nw_tstat(spread.to_numpy(), max(h - 1, 0)) if h > 1 else
                                   S / (spread.std(ddof=1) / math.sqrt(len(spread))), 2)
    out["top_decile_excess_per_period"] = _f(T, 5)
    # measured turnover on a non-overlapping rebalance grid (every h sessions)
    reb = dates[::h] if h > 1 else dates
    members_top, members_bot = {}, {}
    dsub = d[d["date"].isin(reb)]
    rks = rk[d["date"].isin(reb)]
    for dt, grp in dsub.groupby("date"):
        r = rks.loc[grp.index]
        members_top[dt] = set(grp.loc[r > 0.9, "ticker"])
        members_bot[dt] = set(grp.loc[r <= 0.1, "ticker"])
    tos_t, tos_b = [], []
    for a_, b_ in zip(reb[:-1], reb[1:]):
        if a_ in members_top and b_ in members_top and members_top[a_] and members_top[b_]:
            tos_t.append(1 - len(members_top[a_] & members_top[b_]) / len(members_top[b_]))
            tos_b.append(1 - len(members_bot[a_] & members_bot[b_]) / len(members_bot[b_]))
    tau_t = float(np.mean(tos_t)) if tos_t else float("nan")
    tau_b = float(np.mean(tos_b)) if tos_b else float("nan")
    tau_ls = (tau_t + tau_b) / 2.0
    ppy = SESSIONS_PER_YEAR / h
    out["periods_per_year"] = _f(ppy, 2)
    out["turnover_top_measured"] = _f(tau_t, 3)
    out["turnover_bottom_measured"] = _f(tau_b, 3)
    out["ls_gross_annual"] = _f(S * ppy, 4)
    out["ls_cost_annual_full_turnover"] = _f(4 * COST_PER_SIDE * ppy, 4)
    out["ls_net_annual_full_turnover"] = _f((S - 4 * COST_PER_SIDE) * ppy, 4)
    out["ls_net_annual_measured_turnover"] = _f((S - 4 * COST_PER_SIDE * tau_ls) * ppy, 4)
    out["long_gross_annual"] = _f(T * ppy, 4)
    out["long_net_annual_full_turnover"] = _f((T - 2 * COST_PER_SIDE) * ppy, 4)
    out["long_net_annual_measured_turnover"] = _f((T - 2 * COST_PER_SIDE * tau_t) * ppy, 4)
    out["breakeven_cost_per_side_bps_full_turnover"] = _f(S / 4 * 1e4, 2)
    return out


# --------------------------------------------------------------------------- #
# 4. model level through the harness
# --------------------------------------------------------------------------- #
def model_runs(md: pd.DataFrame, features: list[str], splits: dict) -> dict:
    from lightgbm import LGBMClassifier

    ev.RESULTS_DIR = OUT_DIR
    ev.PREDS_DIR = PRED_DIR

    def make(task):
        return LGBMClassifier(verbosity=-1, **LGBM_PARAMS)

    specs = [(f"bin_ex_no_{h}d", f"ex_no_{h}d", f"clean_no_{h}d", h, "no")
             for h in MODEL_HORIZONS]
    specs += [(f"bin_raw_cc_{h}d", f"raw_cc_{h}d", f"clean_cc_{h}d", h, "cc") for h in (5, 20)]
    specs += [("beat_mkt_20d", "y_excess_20d", "y_clean_20d", 20, "no")]   # control
    out = {}
    for task, fwd, clean, h, e in specs:
        if task != "beat_mkt_20d":
            ev.TASKS[task] = (task, fwd, clean)
        label = ev.TASKS[task][0]
        name = f"lgbm_lbl_{task}" if task != "beat_mkt_20d" else "lgbm_lbl_ctrl_beat_mkt_20d"
        cols = ["date", "ticker"] + features + sorted({label, fwd, clean})
        slim = md[cols]
        log(f"harness run {name} ...")
        res = ev.run_standard_eval(
            model_name=name, family="label_study", agent="quant-labels",
            make_model=make, tasks=(task,), preprocess="raw",
            params={k: v for k, v in LGBM_PARAMS.items()},
            notes=(f"label study: pilot champion LGBM config, all 51 manifest features, "
                   f"label={label} fwd={fwd} clean={clean}"),
            df=slim, features=features, splits=splits)[task]
        folds = res["folds"]
        out[name] = {
            "task": task, "label": label, "fwd": fwd, "clean": clean, "h": h, "entry": e,
            "cv_auc_mean": _f(res["cv_auc_mean"], 5), "cv_auc_std": _f(res["cv_auc_std"], 5),
            "fold_aucs": {f["fold"]: _f(f["auc"], 5) for f in folds},
            "worst_fold_auc": _f(min(f["auc"] for f in folds), 5),
            "holdout_auc": _f(res["holdout"]["auc"], 5),
            "holdout_decile_spread_pooled": _f(res["holdout"].get("decile_spread"), 5),
            "holdout_base_rate": _f(res["holdout"]["base_rate"], 4),
            "fold_base_rates": {f["fold"]: _f(f["base_rate"], 4) for f in folds},
            "train_seconds": res["train_seconds"],
        }
    return out


def model_econ(md: pd.DataFrame, runs: dict) -> dict:
    out = {}
    for name, r in runs.items():
        p = pd.read_parquet(PRED_DIR / f"{name}__{r['task']}.parquet")
        p["date"] = pd.to_datetime(p["date"])
        h, e = r["h"], r["entry"]
        same_ex = f"ex_{e}_{h}d" if r["task"] != "beat_mkt_20d" else "y_excess_20d"
        cols = sorted({same_ex, f"ex_no_{h}d"})
        p = p.merge(md[["date", "ticker"] + cols], on=["date", "ticker"], how="left")
        rec = {}
        for split_name, sub in (("oos_all", p), ("cv", p[p["fold"] != "holdout"]),
                                ("holdout", p[p["fold"] == "holdout"])):
            rec[split_name] = {"label_return": per_date_econ(sub, "score", same_ex, h, y="y")}
            if e == "cc":
                rec[split_name]["next_open_return"] = per_date_econ(sub, "score", f"ex_no_{h}d", h)
        out[name] = rec
    return out


# --------------------------------------------------------------------------- #
# reporting helpers
# --------------------------------------------------------------------------- #
def grid_records(summary: dict, feats: list[str], res: dict) -> tuple[dict, pd.DataFrame]:
    nested, rows = {}, []
    for lab in summary["labels"]:
        tgt, e, hd = lab.split("_")
        h = int(hd[:-1])
        F, S = summary["full"][lab], summary["sel"][lab]
        M = summary["monthly"][lab]
        nested[lab] = {}
        for j, f in enumerate(feats):
            rec = {"mean_ic": _f(F["mean"][j], 5), "t": _f(F["t"][j], 3), "p": _f(F["p"][j], 6),
                   "q": _f(F["q"][j], 6), "t_nw": _f(F["t_nw"][j], 3), "q_nw": _f(F["q_nw"][j], 6),
                   "sign_consistency": _f(F["sign_cons"][j], 3), "n_months": int(F["n_months"][j]),
                   "sel_window_mean_ic": _f(S["mean"][j], 5), "sel_window_t": _f(S["t"][j], 3),
                   "sel_window_q": _f(S["q"][j], 6),
                   "monthly_ic": {str(k): _f(x, 4) for k, x in M.iloc[:, j].dropna().items()}}
            nested[lab][f] = rec
            rows.append({"label": lab, "target": tgt, "entry": e, "h": h, "feature": f,
                         "mean_ic": rec["mean_ic"], "t": rec["t"], "t_nw": rec["t_nw"],
                         "p": rec["p"], "q": rec["q"], "q_nw": rec["q_nw"],
                         "sign_consistency": rec["sign_consistency"], "n_months": rec["n_months"],
                         "sel_window_t": rec["sel_window_t"], "sel_window_q": rec["sel_window_q"]})
    return nested, pd.DataFrame(rows)


def auc_records(res: dict, feats: list[str]) -> tuple[dict, pd.DataFrame, dict]:
    labels = list(res["auc_xs"].keys())
    tests = {}
    for lab in labels:
        dates, A = res["auc_xs"][lab]
        h = int(lab.split("_")[-1][:-1])
        M = monthly_matrix(pd.DatetimeIndex(dates), A)
        tests[lab] = column_tests(M.to_numpy(), 0.5, nw_lag_for(h))
    pv = np.concatenate([tests[lab]["p"] for lab in labels])
    q = bh_q(pv)
    k = len(feats)
    nested, rows = {}, []
    for i, lab in enumerate(labels):
        _, kind, e, hd = lab.split("_")
        h = int(hd[:-1])
        T = tests[lab]
        nested[lab] = {}
        for j, f in enumerate(feats):
            pa = res["auc_pooled"][lab][j]
            xs = T["mean"][j] + 0.5 if np.isfinite(T["mean"][j]) else np.nan
            rec = {"auc_pooled": _f(pa, 5),
                   "auc_pooled_abs": _f(max(pa, 1 - pa), 5) if np.isfinite(pa) else None,
                   "auc_pooled_sign": int(np.sign(pa - 0.5)) if np.isfinite(pa) else None,
                   "auc_xs_mean": _f(xs, 5),
                   "auc_xs_abs": _f(max(xs, 1 - xs), 5) if np.isfinite(xs) else None,
                   "auc_xs_sign": int(np.sign(xs - 0.5)) if np.isfinite(xs) else None,
                   "auc_xs_t": _f(T["t"][j], 3), "auc_xs_q": _f(q[i * k + j], 6),
                   "auc_xs_sign_consistency": _f(T["sign_cons"][j], 3)}
            nested[lab][f] = rec
            rows.append({"label": lab, "kind": kind, "entry": e, "h": h, "feature": f, **{
                kk: vv for kk, vv in rec.items()}})
    meta = {"m_hypotheses": int(np.sum(~np.isnan(pv)))}
    return nested, pd.DataFrame(rows), meta


def md_table(headers: list[str], rows: list[list]) -> str:
    def fmt(x):
        if x is None:
            return "–"
        if isinstance(x, float):
            return f"{x:.4g}" if abs(x) >= 1e-3 or x == 0 else f"{x:.2e}"
        return str(x)
    s = "| " + " | ".join(headers) + " |\n|" + "|".join("---" for _ in headers) + "|\n"
    for r in rows:
        s += "| " + " | ".join(fmt(x) for x in r) + " |\n"
    return s


# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-models", action="store_true")
    ap.add_argument("--null-draws", type=int, default=N_SIGNFLIP)
    args = ap.parse_args()
    t0 = time.time()
    np.random.seed(SEED)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PRED_DIR.mkdir(parents=True, exist_ok=True)

    md = pd.read_parquet(DATA_DIR / "model_dataset.parquet")
    md["date"] = pd.to_datetime(md["date"])
    md = md.sort_values(["date", "ticker"]).reset_index(drop=True)
    manifest = json.loads((DATA_DIR / "manifest.json").read_text())
    splits = json.loads((DATA_DIR / "splits.json").read_text())
    features = manifest["features"]
    base_feats = [f for f in features if not f.endswith("_isnan")]
    assert len(base_feats) == 40, len(base_feats)
    log(f"model rows {len(md):,}; features {len(features)} (base {len(base_feats)})")

    # ---- 1. labels -----------------------------------------------------------
    lab = build_price_labels()
    md, match = attach_labels(md, lab)
    del lab
    md = add_cross_sectional(md)
    log("labels built")
    validation = validate_against_dataset(md)
    validation.update(match)
    vstats = variant_stats(md)
    keep = (["date", "ticker"] + [c for c in md.columns if c.split("_")[0] in
                                  ("raw", "ex", "rank", "vs", "bin", "clean")
                                  and c.endswith("d") and c[-2:-1].isdigit()])
    md[keep].to_parquet(PRED_DIR / "label_variants.parquet", index=False)
    log("label stats done")

    # ---- 2. IC / AUC grid ------------------------------------------------------
    res = ic_grid(md, base_feats)
    # exactness check: raw / rank give identical per-date Spearman to ex
    codes_all = pd.factorize(md["date"], sort=True)[0]
    dates_all = np.sort(md["date"].unique())
    ident = {}
    for v in ("cc_1d", "no_20d"):
        idx = np.flatnonzero(md[f"raw_{v}"].notna().to_numpy())
        X = md[base_feats].to_numpy(np.float64)[idx]
        diffs = []
        for tgt in ("raw", "rank"):
            gc, r = per_date_spearman(codes_all[idx], X, md[f"{tgt}_{v}"].to_numpy(np.float64)[idx])
            diffs.append(float(np.nanmax(np.abs(r - res["ic"][f"ex_{v}"][1][gc]))))
        ident[v] = {"max_abs_daily_ic_diff_raw_vs_ex": diffs[0],
                    "max_abs_daily_ic_diff_rank_vs_ex": diffs[1]}
    summary = summarize_grid(res, base_feats)
    nested_ic, ic_df = grid_records(summary, base_feats, res)
    nested_auc, auc_df, auc_meta = auc_records(res, base_feats)
    null = signflip_null(summary, base_feats, args.null_draws)
    log(f"IC grid summarized: {summary['m_hypotheses']} hypotheses")

    # ex-ETF sensitivity (ex-family labels only)
    etf = (md["ticker"].astype(str).str.contains(ETF_PATTERN, regex=True)
           & ~md["ticker"].astype(str).isin(ETF_NAME_EXCEPTIONS)).to_numpy()
    res["rankers"].pop("pooled", None)
    res_ne = ic_grid(md, base_feats, row_filter=~etf, with_auc=False, targets=("ex",),
                     rankers=res["rankers"])
    summ_ne = summarize_grid(res_ne, base_feats)
    log("ex-ETF sensitivity done")

    # ---- 3. composites ---------------------------------------------------------
    ranks_all = md.groupby("date")[base_feats].rank(pct=True).to_numpy(np.float32)
    comp = composite_eval(md, base_feats, summary, ranks_all, codes_all, dates_all)
    # composite economics (OOS dates only) for every ex label -> tradability at all h
    comp_econ = {}
    for labname, variants in comp.items():
        if not labname.startswith("ex_"):
            continue
        _, e, hd = labname.split("_")
        h = int(hd[:-1])
        for vn in ("fdr_q10", "top5_abs_t"):
            if variants[vn]["n_selected"] == 0:
                continue
            tmp = md[["date", "ticker", labname, f"ex_no_{h}d"]].copy()
            tmp["score"] = variants[vn]["_score"]
            tmp = tmp[tmp["date"] >= pd.Timestamp(variants[vn]["oos_first_date"])]
            rec = {"label_return": per_date_econ(tmp, "score", labname, h)}
            if e == "cc":
                rec["next_open_return"] = per_date_econ(tmp, "score", f"ex_no_{h}d", h)
            comp_econ.setdefault(labname, {})[vn] = rec
    for variants in comp.values():
        for vv in variants.values():
            vv.pop("_score", None)
    del ranks_all
    log("composites done")

    # ---- 4. model level ----------------------------------------------------------
    runs, econ = {}, {}
    if not args.skip_models:
        runs = model_runs(md, features, splits)
        econ = model_econ(md, runs)
        log("model runs done")

    # ---- per-label summary ------------------------------------------------------
    label_summary = {}
    for labname in summary["labels"]:
        F = summary["full"][labname]
        q = F["q"]
        order = np.argsort(-np.where(np.isfinite(F["t"]), np.abs(F["t"]), -1))
        label_summary[labname] = {
            "n_q_lt_0.05": int(np.nansum(q < 0.05)), "n_q_lt_0.10": int(np.nansum(q < 0.10)),
            "n_q_nw_lt_0.05": int(np.nansum(F["q_nw"] < 0.05)),
            "n_p_lt_0.05": int(np.nansum(F["p"] < 0.05)),
            "top5": [{"feature": base_feats[j], "mean_ic": _f(F["mean"][j], 4), "t": _f(F["t"][j], 2),
                      "t_nw": _f(F["t_nw"][j], 2), "q": _f(F["q"][j], 4),
                      "sign_consistency": _f(F["sign_cons"][j], 2)} for j in order[:5]],
            "mean_abs_ic_all_feats": _f(np.nanmean(np.abs(F["mean"])), 5),
            "composite": comp[labname],
        }
        if labname in summ_ne["full"]:
            Fn = summ_ne["full"][labname]
            label_summary[labname]["ex_etf"] = {
                "n_q_lt_0.05": int(np.nansum(Fn["q"] < 0.05)),
                "n_q_lt_0.10": int(np.nansum(Fn["q"] < 0.10)),
                "top5": [{"feature": base_feats[j], "mean_ic": _f(Fn["mean"][j], 4), "t": _f(Fn["t"][j], 2)}
                         for j in np.argsort(-np.where(np.isfinite(Fn["t"]), np.abs(Fn["t"]), -1))[:5]]}
    # ex-ETF per-feature deltas for the headline label families
    etf_delta = {}
    for labname in summ_ne["labels"]:
        F, Fn = summary["full"][labname], summ_ne["full"][labname]
        etf_delta[labname] = {f: {"ic_all": _f(F["mean"][j], 4), "ic_ex_etf": _f(Fn["mean"][j], 4),
                                  "t_all": _f(F["t"][j], 2), "t_ex_etf": _f(Fn["t"][j], 2)}
                              for j, f in enumerate(base_feats)}

    # ---- write -----------------------------------------------------------------
    meta = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "generated_by": "ml/label_study.py (python3 -m ml.label_study), seed 108, OMP_NUM_THREADS=2",
        "runtime_seconds": round(time.time() - t0, 1),
        "rows": int(len(md)), "dates": int(md["date"].nunique()),
        "base_features": base_feats,
        "horizons": list(HORIZONS), "entries": {"cc": "close[t+h]/close[t]-1",
                                                "no": "open[t+1+h]/open[t+1]-1"},
        "targets": {"raw": "raw forward return", "ex": "raw - per-date median of clean universe rows",
                    "rank": "per-date pct rank of ex", "vs": "ex / (max(vol_20, 0.005) * sqrt(h)); "
                    "masked where vol_20 NaN or flag_split_20d==1",
                    "bin_raw": "raw > 0", "bin_ex": "ex > 0"},
        "clean_mask": {"prices": "entry and exit > 0", "all_bars": "every session of the forward "
                       "window present for the ticker (market calendar)",
                       "span_days_max": {str(h): span_cap(h) for h in HORIZONS},
                       "span_exemption": "a window whose calendar span equals the market "
                                         "calendar's span for the same sessions (holiday "
                                         "cluster) is not rejected; only h=5 is affected "
                                         "(the 26-Mar/31-Mar/03-Apr-2026 cluster)",
                       "split_guard": "no |ret_1d| > 22% on bars t+1..t+steps (steps = h cc, h+1 no)"},
        "ic": {"method": "per-date Spearman, >=100 names/date, mean within calendar month "
                         "(>=5 IC dates), monthly t-test (df = months-1), NW t with lag 0/1/2 "
                         "months for h<=5 / 10-20 / 40",
               "identical_targets_check": ident,
               "m_hypotheses_continuous": summary["m_hypotheses"],
               "m_hypotheses_binary_xs_auc": auc_meta["m_hypotheses"],
               "exact_duplicate_feature_pairs": [["ret_1d", "log_ret_1d"], ["mom_20", "cs_rank_mom_20"],
                                                 ["ret_126d", "cs_rank_ret_126"], ["vol_20", "cs_rank_vol_20"],
                                                 ["log_turnover", "cs_rank_turnover"],
                                                 ["deliv_pct_z_20", "cs_rank_deliv_z"]],
               "selection_window": f"2025-06 .. {SEL_LAST_MONTH} (8 months)"},
        "etf_sensitivity": {"pattern": ETF_PATTERN, "exceptions": sorted(ETF_NAME_EXCEPTIONS),
                            "etf_row_share": _f(etf.mean(), 4),
                            "etf_tickers": int(md.loc[etf, "ticker"].nunique())},
        "costs": {"per_side": COST_PER_SIDE, "long_short_sides_per_rebalance": 4,
                  "long_only_sides_per_rebalance": 2, "sessions_per_year": SESSIONS_PER_YEAR},
        "lgbm_params": LGBM_PARAMS,
        "model_h40_skipped": "next-open 40d label spans 41 sessions > 22-session embargo: "
                             "train labels would overlap the test window",
    }
    (OUT_DIR / "label_variants.json").write_text(json.dumps(
        {"meta": meta, "validation_vs_dataset": validation, "variants": vstats}, indent=1))
    (OUT_DIR / "ic_matrix.json").write_text(json.dumps(
        {"meta": meta["ic"], "aliases": {f"{a}_{vname(h, e)}": f"ex_{vname(h, e)}"
                                         for a in ("raw", "rank") for h in HORIZONS for e in ENTRIES},
         "matrix": nested_ic}, indent=1))
    ic_df.to_csv(OUT_DIR / "ic_matrix.csv", index=False)
    ic_df.pivot(index="feature", columns="label", values="t").reindex(base_feats).round(2).to_csv(
        OUT_DIR / "ic_matrix_t_wide.csv")
    ic_df.pivot(index="feature", columns="label", values="mean_ic").reindex(base_feats).round(4).to_csv(
        OUT_DIR / "ic_matrix_mean_wide.csv")
    (OUT_DIR / "auc_matrix.json").write_text(json.dumps(
        {"meta": {"m_hypotheses": auc_meta["m_hypotheses"],
                  "auc_pooled": "AUC over all clean rows (harness view; mixes timing for raw>0)",
                  "auc_xs": "mean of per-date AUCs (cross-sectional only), monthly t vs 0.5, "
                            "BH over the binary family"},
         "matrix": nested_auc}, indent=1))
    auc_df.to_csv(OUT_DIR / "auc_matrix.csv", index=False)
    (OUT_DIR / "label_summary.json").write_text(json.dumps(
        {"meta": {"bh_family_size": summary["m_hypotheses"],
                  "expected_p_lt_0.05_under_global_null": round(0.05 * summary["m_hypotheses"], 1),
                  "signflip_null": null},
         "labels": label_summary, "ex_etf_feature_deltas": etf_delta}, indent=1))
    (OUT_DIR / "composite_econ.json").write_text(json.dumps(comp_econ, indent=1))
    if runs:
        (OUT_DIR / "model_level.json").write_text(json.dumps(
            {"runs": runs, "econ": econ}, indent=1))
    write_tables(meta, vstats, label_summary, null, runs, econ, comp_econ, validation)
    log(f"done in {time.time() - t0:.0f}s")


def write_tables(meta, vstats, label_summary, null, runs, econ, comp_econ, validation) -> None:
    L = [f"# Label study — generated tables\n\nGenerated {meta['generated_at']} by "
         f"`python3 -m ml.label_study` (seed 108). Hand-written verdict: LABEL_STUDY.md.\n"]
    rows = []
    for h in HORIZONS:
        for e in ENTRIES:
            v = vname(h, e)
            s = vstats[v]
            ls_ex, ls_vs = label_summary[f"ex_{v}"], label_summary[f"vs_{v}"]
            c = ls_ex["composite"]
            rows.append([v, s["coverage_labelable_dates"],
                         f"{s['targets']['raw']['base_rate_month_min']:.2f}–{s['targets']['raw']['base_rate_month_max']:.2f}",
                         f"{s['targets']['ex']['base_rate_month_min']:.2f}–{s['targets']['ex']['base_rate_month_max']:.2f}",
                         s["targets"]["ex"]["xs_std_mean"],
                         s["targets"]["raw"]["per_date_mean_lag1_autocorr"],
                         ls_ex["n_q_lt_0.05"], ls_ex["n_q_lt_0.10"], ls_ex["n_q_nw_lt_0.05"],
                         ls_vs["n_q_lt_0.05"],
                         c["fdr_q10"]["n_selected"], c["fdr_q10"]["is_ic"], c["fdr_q10"]["oos_ic"],
                         c["top5_abs_t"]["is_ic"], c["top5_abs_t"]["oos_ic"], c["top5_abs_t"]["oos_t"]])
    L.append("## Label variants and feature-level predictability (ex = excess family; raw/rank identical ICs)\n")
    L.append(md_table(["label", "coverage", "raw>0 month range", "ex>0 month range", "xs std(ex)",
                       "lag1 ac mkt", "#q<.05 ex", "#q<.10 ex", "#q_nw<.05 ex", "#q<.05 vs",
                       "#sel(8m)", "comp IS IC", "comp OOS IC", "top5 IS IC", "top5 OOS IC",
                       "top5 OOS t"], rows))
    L.append(f"\nBH family: {meta['ic']['m_hypotheses_continuous']} hypotheses. Month-sign-flip null "
             f"({null['n_draws']} draws): observed q<0.05 = {null['observed']['q_lt_0.05']}, null mean "
             f"{null['null_mean']['q_lt_0.05']}, null 95th pct {null['null_p95']['q_lt_0.05']}; "
             f"observed p<0.05 = {null['observed']['p_lt_0.05']} vs null mean {null['null_mean']['p_lt_0.05']}.\n")
    if runs:
        rows = []
        for name, r in runs.items():
            ec = econ[name]["oos_all"]
            lr = ec["label_return"]
            no = ec.get("next_open_return", lr)
            rows.append([name, f"{r['cv_auc_mean']:.4f} ± {r['cv_auc_std']:.4f}", r["worst_fold_auc"],
                         r["holdout_auc"], r["holdout_decile_spread_pooled"], lr.get("xs_auc_mean"),
                         lr["rank_ic_mean"], lr["rank_ic_t_nw"], lr["rank_ic_t_monthly"],
                         lr["decile_spread_per_period"], lr["ls_net_annual_full_turnover"],
                         no["rank_ic_mean"], no["ls_net_annual_full_turnover"],
                         no["ls_net_annual_measured_turnover"], no["long_net_annual_measured_turnover"]])
        L.append("\n## Model level (champion LGBM, 51 features, harness folds + holdout; OOS = 4 CV months + holdout)\n")
        L.append(md_table(["model", "CV AUC", "worst fold", "holdout AUC", "holdout spread (pooled)",
                           "xs AUC", "rank-IC", "t (NW)", "t (monthly)", "spread/period",
                           "L/S net ann. (100% TO)", "rank-IC next-open", "L/S net ann. next-open (100% TO)",
                           "L/S net ann. next-open (meas. TO)", "long-only net ann. (meas. TO)"], rows))
    rows = []
    for labname in sorted(comp_econ, key=lambda s: (s.split("_")[1], int(s.split("_")[2][:-1]))):
        for vn, rec in comp_econ[labname].items():
            lr = rec["label_return"]
            no = rec.get("next_open_return", lr)
            rows.append([labname, vn, lr["rank_ic_mean"], lr["decile_spread_per_period"],
                         lr["ls_gross_annual"], lr["ls_net_annual_full_turnover"],
                         no["decile_spread_per_period"], no["ls_net_annual_full_turnover"],
                         no["turnover_top_measured"], no["ls_net_annual_measured_turnover"],
                         no["long_net_annual_measured_turnover"]])
    L.append("\n## Feature-composite tradability (OOS months only, after h-session embargo)\n")
    L.append(md_table(["label", "composite", "rank-IC", "spread/period", "L/S gross ann.",
                       "L/S net ann. (100% TO)", "next-open spread/period", "next-open L/S net (100% TO)",
                       "top-decile TO", "next-open L/S net (meas. TO)", "next-open long-only net (meas. TO)"],
                      rows))
    L.append("\n## Validation vs model_dataset labels\n\n```\n" + json.dumps(validation, indent=1) + "\n```\n")
    (OUT_DIR / "TABLES.md").write_text("\n".join(L))


if __name__ == "__main__":
    main()

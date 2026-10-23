#!/usr/bin/env python3
"""Average label uniqueness (Lopez de Prado, Advances in Financial Machine Learning, ch. 4) for one
training window: the 2025-01 fold of the five-year walk-forward (ml/IMPROVEMENT_PLAN.md P5).

Training window exactly as ml/scale5y.py / ml/scale5y_nested.py window_rows: labeled rows with
y_clean_20d True and first <= date <= train_end, where first is the session 504 sessions before
train_end on the dataset's date axis, then the audit-T3 purge (label exit date >= test_start
dropped).  Label span of row (ticker, t) = sessions [t+1, exit], exit = the ticker's own row t+21
(ml/results/scale5y/cache/extra_5y.parquet exit_date), measured on the market session calendar.

Concurrency c(k, s) = number of ticker k's training rows whose span contains session s.
Average uniqueness of a row = mean over its span of 1 / c.  With fixed 21-session spans and one
label per session, an interior row has c = 21 at every session of its span and uniqueness 1/21.

Pre-stated reading (written before the computation; the plan fixes the consequence but not the
threshold): uniqueness is "near-constant" if at least 95% of training rows lie within +-10% of
1/21.  If so, uniqueness weights are a constant multiple of equal weights for almost every row and
cannot change the fit; the item closes with that evidence.  If not, the rows that deviate are
located (window edges, ticker gaps) and the size of the possible effect is measured without a
model fit: weighted vs unweighted label base rate and univariate AUC of the 50 features on the
same training rows (no test data is touched).

Sensitivity (not the reading): concurrency counted over every labeled row of the ticker in the
dataset, not only the training rows, which removes the window-boundary effect.

Run:  PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 python3 -m ml.hygiene.uniqueness
"""
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

from ml.hygiene.common import CACHE5Y, DATA_5Y, OUT, input_record, log, wjson

FOLD = "2025-01"
TRAIN_SESSIONS = 504
H = 21                       # label span in sessions: t+1 .. t+21
LABEL, CLEAN = "label_beat_mkt_20d", "y_clean_20d"
NEAR_CONSTANT_SHARE = 0.95   # pre-stated threshold
TOL = 0.10                   # +-10% of 1/21


def concurrency_uniqueness(codes: np.ndarray, si: np.ndarray, ei: np.ndarray, n_codes: int, D: int,
                           q_codes: np.ndarray | None = None, q_si: np.ndarray | None = None,
                           q_ei: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Concurrency from the spans (si+1 .. ei) of rows (codes, si, ei); average uniqueness of the
    query rows (defaults to the same rows).  Returns (uniqueness, concurrency matrix)."""
    diff = np.zeros((n_codes, D + 2), np.int32)
    np.add.at(diff, (codes, si + 1), 1)
    np.add.at(diff, (codes, ei + 1), -1)
    c = np.cumsum(diff, axis=1)[:, :D + 1]
    inv = np.where(c > 0, 1.0 / np.maximum(c, 1), 0.0)
    P = np.concatenate([np.zeros((n_codes, 1)), np.cumsum(inv, axis=1)], axis=1)
    if q_codes is None:
        q_codes, q_si, q_ei = codes, si, ei
    span = (q_ei - q_si).astype(float)
    u = (P[q_codes, q_ei + 1] - P[q_codes, q_si + 1]) / span
    return u, c


def distribution(u: np.ndarray) -> dict:
    q = np.percentile(u, [0, 1, 5, 25, 50, 75, 95, 99, 100])
    target = 1.0 / H
    return {"n_rows": int(len(u)), "mean": float(u.mean()), "sd": float(u.std(ddof=1)),
            "cv": float(u.std(ddof=1) / u.mean()), "min": float(q[0]), "p01": float(q[1]), "p05": float(q[2]),
            "p25": float(q[3]), "median": float(q[4]), "p75": float(q[5]), "p95": float(q[6]),
            "p99": float(q[7]), "max": float(q[8]),
            "share_within_10pct_of_1_over_21": float((np.abs(u - target) <= TOL * target + 1e-15).mean()),
            "share_exactly_1_over_21": float((np.abs(u - target) < 1e-12).mean()),
            "share_above_1.5_over_21": float((u > 1.5 * target).mean()),
            "kish_weight_efficiency": float(u.sum() ** 2 / (len(u) * (u ** 2).sum())),
            "effective_labels_sum_u": float(u.sum())}


def wauc(s: np.ndarray, y: np.ndarray, w: np.ndarray) -> float:
    """Weighted ROC AUC with ties counted one half (w = 1 gives the ordinary AUC)."""
    o = np.argsort(s, kind="mergesort")
    s, y, w = s[o], y[o], w[o]
    starts = np.flatnonzero(np.r_[True, s[1:] != s[:-1]])
    wn, wp = w * (y == 0), w * (y == 1)
    gn, gp = np.add.reduceat(wn, starts), np.add.reduceat(wp, starts)
    below = np.cumsum(gn) - gn
    return float((gp * (below + 0.5 * gn)).sum() / (wp.sum() * wn.sum()))


def main() -> None:
    t0 = time.time()
    log(f"uniqueness: start; fold {FOLD}; pre-stated reading: near-constant iff >= {NEAR_CONSTANT_SHARE:.0%} of "
        f"training rows within +-{TOL:.0%} of 1/{H}", "uniqueness")
    splits = json.loads((DATA_5Y / "splits.json").read_text())
    spec = next(f for f in splits["folds"] if f["name"] == FOLD)
    feats = json.loads((DATA_5Y / "manifest.json").read_text())["features"]
    df = pd.read_parquet(DATA_5Y / "model_dataset.parquet", columns=["date", "ticker", LABEL, CLEAN] + feats)
    ex = pd.read_parquet(CACHE5Y / "extra_5y.parquet", columns=["date", "ticker", "exit_date"])
    df["date"] = pd.to_datetime(df["date"])
    ex["date"] = pd.to_datetime(ex["date"])
    df = df.merge(ex, on=["date", "ticker"], how="left", validate="one_to_one")
    dates = pd.DatetimeIndex(sorted(df["date"].unique()))            # ml/scale5y.py _DATES
    D = len(dates)
    te = pd.Timestamp(spec["train_end"])
    ts = pd.Timestamp(spec["test_start"])
    loc = dates.get_loc(te)
    first = dates[max(loc - TRAIN_SESSIONS, 0)]
    win = df[(df["date"] >= first) & (df["date"] <= te)]
    lab = win[LABEL].notna() & win[CLEAN].astype(bool)
    purge = lab & win["exit_date"].notna() & (win["exit_date"] >= ts)
    tr = win[lab & ~purge].copy()
    log(f"uniqueness: window {first.date()}..{te.date()} ({loc - dates.get_loc(first) + 1} sessions), rows in window "
        f"{len(win):,}, labeled clean {int(lab.sum()):,}, purged {int(purge.sum())}, training rows {len(tr):,}, "
        f"tickers {tr['ticker'].nunique():,}", "uniqueness")
    # session indices of entry and exit
    si = dates.get_indexer(tr["date"])
    ei = dates.searchsorted(tr["exit_date"].to_numpy())
    exact = (ei < D) & (dates[np.minimum(ei, D - 1)] == tr["exit_date"].to_numpy())
    assert (si >= 0).all() and exact.all(), "every exit date must be a session on the dataset calendar"
    span = ei - si
    tick = pd.Index(sorted(df["ticker"].unique()))
    codes = tick.get_indexer(tr["ticker"])
    # (A) the reading: concurrency among the training rows
    u, conc = concurrency_uniqueness(codes, si, ei, len(tick), D)
    distA = distribution(u)
    # where deviations sit
    i_first = dates.get_loc(first)
    pos = np.where(si < i_first + (H - 1), "window_start_20_sessions",
                   np.where(si > loc - (H - 1), "window_end_20_sessions", "interior"))
    target = 1.0 / H
    within = np.abs(u - target) <= TOL * target + 1e-15
    by_pos = {}
    for p in ("window_start_20_sessions", "interior", "window_end_20_sessions"):
        m = pos == p
        by_pos[p] = {"share_of_rows": float(m.mean()), "mean_u": float(u[m].mean()),
                     "share_within_10pct": float(within[m].mean()), "p99_u": float(np.percentile(u[m], 99))}
    # interior rows that deviate: ticker-level reasons
    span_dist = {str(k): int(v) for k, v in zip(*np.unique(span, return_counts=True))}
    dev_int = (pos == "interior") & ~within
    # (B) sensitivity: concurrency over every labeled row of the ticker in the dataset
    alll = df[df[LABEL].notna() & df["exit_date"].notna()]
    a_si = dates.get_indexer(alll["date"])
    a_ei = dates.searchsorted(alll["exit_date"].to_numpy())
    ok = (a_ei < D)
    a_codes = tick.get_indexer(alll["ticker"])
    uB, _ = concurrency_uniqueness(a_codes[ok], a_si[ok], a_ei[ok], len(tick), D, codes, si, ei)
    distB = distribution(uB)
    # possible effect without a model fit: weighted vs unweighted base rate and univariate AUC
    y = tr[LABEL].to_numpy(float)
    w = u / u.mean()
    base = {"unweighted": float(y.mean()), "uniqueness_weighted": float((w * y).sum() / w.sum())}
    aucs = []
    for f in feats:
        x = tr[f].to_numpy(float)
        m = np.isfinite(x)
        if m.sum() < 1000 or np.unique(x[m]).size < 2:
            continue
        a0 = wauc(x[m], y[m], np.ones(int(m.sum())))
        a1 = wauc(x[m], y[m], w[m])
        aucs.append({"feature": f, "auc_unweighted": a0, "auc_weighted": a1, "delta": a1 - a0})
    d = np.array([r["delta"] for r in aucs])
    edge0 = np.array([abs(r["auc_unweighted"] - 0.5) for r in aucs])
    edge1 = np.array([abs(r["auc_weighted"] - 0.5) for r in aucs])
    from scipy.stats import spearmanr
    proxy = {"label_base_rate": base,
             "univariate_auc": {"n_features": len(aucs), "max_abs_delta": float(np.abs(d).max()),
                                "mean_abs_delta": float(np.abs(d).mean()),
                                "mean_abs_auc_minus_half_unweighted": float(edge0.mean()),
                                "spearman_feature_order_weighted_vs_unweighted": float(spearmanr(edge0, edge1)[0]),
                                "largest_deltas": sorted(aucs, key=lambda r: -abs(r["delta"]))[:5]},
             "note": "computed on the 2025-01 training rows only, weights = uniqueness / mean uniqueness; "
                     "no model is fitted and no test month is used, so this is not a trial"}
    # brute-force check of the concurrency algebra on 25 random tickers (seed 108)
    rng = np.random.default_rng(108)
    max_err = 0.0
    for k in rng.choice(np.unique(codes), size=25, replace=False):
        m = np.flatnonzero(codes == k)
        cnt = np.zeros(D + 1)
        for a_, b_ in zip(si[m], ei[m]):
            cnt[a_ + 1:b_ + 1] += 1
        for j in m:
            ub = np.mean(1.0 / cnt[si[j] + 1:ei[j] + 1])
            max_err = max(max_err, abs(ub - u[j]))
    log(f"uniqueness: brute-force check on 25 tickers, max |error| {max_err:.2e}", "uniqueness")
    assert max_err < 1e-9
    # who would be up-weighted: liquidity of deviating vs exact rows (cs_rank_turnover < 0.5 = illiquid half)
    liq = tr["cs_rank_turnover"].to_numpy(float)
    dev = ~within
    liquidity_of_deviating = {
        "share_illiquid_half_among_deviating_rows": float((liq[dev] < 0.5).mean()),
        "share_illiquid_half_among_other_rows": float((liq[~dev] < 0.5).mean()),
        "share_illiquid_half_among_interior_deviating_rows": float((liq[dev_int] < 0.5).mean()) if dev_int.any() else None,
        "mean_weight_multiplier_window_edges": float(u[pos != "interior"].mean() / target),
        "mean_weight_multiplier_deviating_rows": float(u[dev].mean() / target)}
    near_constant = bool(distA["share_within_10pct_of_1_over_21"] >= NEAR_CONSTANT_SHARE)
    reading = {
        "criterion": f"near-constant iff share of training rows within +-10% of 1/21 >= {NEAR_CONSTANT_SHARE}",
        "share_within_10pct": distA["share_within_10pct_of_1_over_21"],
        "near_constant": near_constant,
        "item_closes": near_constant,
    }
    payload = {
        "generated_by": "ml/hygiene/uniqueness.py",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "method": {"fold": FOLD, "train_end": spec["train_end"], "test_start": spec["test_start"],
                   "window_first_session": str(first.date()), "train_sessions_back": TRAIN_SESSIONS,
                   "window_sessions_inclusive": int(loc - i_first + 1),
                   "rows": "labeled (label_beat_mkt_20d present), y_clean_20d True, first <= date <= train_end, "
                           "exit-date purge (exit >= test_start dropped); all tickers (cheap)",
                   "span": "sessions t+1 .. exit (exit = ticker's own row t+21) on the dataset's session calendar",
                   "concurrency": "per ticker, number of that ticker's training rows whose span contains the session",
                   "uniqueness": "mean over the row's span of 1 / concurrency",
                   "pre_stated_reading": reading["criterion"]},
        "inputs": [input_record(DATA_5Y / "model_dataset.parquet", full_hash=False),
                   input_record(CACHE5Y / "extra_5y.parquet"), input_record(DATA_5Y / "splits.json")],
        "window": {"rows_in_window": int(len(win)), "labeled_clean": int(lab.sum()), "purged_exit_ge_test_start":
                   int(purge.sum()), "training_rows": int(len(tr)), "tickers": int(tr["ticker"].nunique()),
                   "span_length_sessions_counts": span_dist,
                   "share_span_21": float((span == H).mean())},
        "distribution_training_rows": distA,
        "by_position_in_window": by_pos,
        "interior_rows_deviating": {"rows": int(dev_int.sum()), "share_of_all_rows": float(dev_int.mean()),
                                    "share_with_span_not_21": float((span[dev_int] != H).mean()) if dev_int.any() else None,
                                    "note": "interior deviations come from the ticker's own gaps: universe entry or "
                                            "exit, masked (unclean) labels, listing, or spans longer than 21 sessions"},
        "who_is_up_weighted": liquidity_of_deviating,
        "brute_force_check_max_abs_error_25_tickers": max_err,
        "sensitivity_concurrency_all_labeled_rows": distB,
        "possible_effect_without_fit": proxy,
        "reading": reading,
        "seconds": round(time.time() - t0, 1),
    }
    wjson(OUT / "uniqueness.json", payload)
    log(f"uniqueness: A mean {distA['mean']:.5f} sd {distA['sd']:.5f} p01 {distA['p01']:.5f} p99 {distA['p99']:.5f} "
        f"within10% {distA['share_within_10pct_of_1_over_21']:.4f}; B within10% "
        f"{distB['share_within_10pct_of_1_over_21']:.4f}; AUC max |delta| {proxy['univariate_auc']['max_abs_delta']:.5f}; "
        f"near_constant={near_constant}", "uniqueness")
    log(f"uniqueness: wrote {OUT / 'uniqueness.json'} ({payload['seconds']} s)", "uniqueness")


if __name__ == "__main__":
    main()

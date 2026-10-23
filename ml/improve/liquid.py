#!/usr/bin/env python3
"""Stream Q3 of ml/IMPROVEMENT_PLAN_2.md: a model for the liquid universe.

    python3 -m ml.improve.liquid md          # (re)write LIQUID.md from whatever JSON exists (definitions first)
    python3 -m ml.improve.liquid build       # L1 / L2 datasets + build checks -> ml/results/improve2/liquid/build.json
    python3 -m ml.improve.liquid selftest    # pass-mark code path on the control's own books (difference == 0)
    python3 -m ml.improve.liquid compare     # pass mark after the full runs -> liquid.json + LIQUID.md

Datasets (filters of ml/data_10y/model_dataset.parquet, which is only read):
  L1  ml/data_10y_liq/   rows with cs_rank_turnover >= 0.67 on that date (full-universe rank, as stored)
  L2  ml/data_10y_liq2/  rows with cs_rank_turnover >= 0.33
Same columns, the 52-feature manifest, splits.json copied byte for byte, exit_date kept. Only the three
universe-relative labels are recomputed inside the restricted universe, exactly as ml/data.py does it (lines
198-202): y_excess_20d = y_raw_20d - per-date median of y_raw_20d over the universe's rows (pandas skips NaN, so the
median runs over every universe row with a non-missing y_raw_20d, clean or not), y_rank_20d = per-date percentile
rank of y_excess_20d, label_beat_mkt_20d = 1(y_excess_20d > 0) where y_excess_20d is not NaN. Features, including
the cs_rank_* columns ranked on the full universe, are unchanged.

Pass mark (fixed in the plan): for L1 or L2, the neutral liquid book's IR >= 0.5 with its month-block 95% CI
excluding zero AND its paired monthly excess over the control's neutral liquid book has a bootstrap 95% CI excluding
zero (months resampled with replacement, B = 1000, seed 108; a 3-month moving-block version is reported beside it).

Seed 108; single process; reads parquet only (never the DuckDB).
"""
from __future__ import annotations

import os

os.environ["OMP_NUM_THREADS"] = "2"
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")

import argparse
import json
import math
import shutil
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import ml.strategy_backtest as sb
from ml.books import data as D
from ml.improve.ab import OUT_ROOT

ML_DIR = Path(__file__).resolve().parents[1]
REPO = ML_DIR.parent
SRC = ML_DIR / "data_10y"
OUT = ML_DIR / "results" / "improve2" / "liquid"
BOOKS_JSON = ML_DIR / "results" / "improve" / "books" / "books.json"
CONTROL_BOOKS = OUT_ROOT / "10y" / "books.json"
PRICES = ML_DIR / "results" / "improve" / "cache" / "features_prices_export_10y.parquet"
PRICE_START = "2017-10-02"
SEED = 108
B_BOOT = 1000
BLOCK_MONTHS = 3
PASS_IR = 0.5
N_TRIALS = 261
EXPECTED_MONTHS = 105
N_HAND_DATES = 5
LABELS = ("y_excess_20d", "y_rank_20d", "label_beat_mkt_20d")
CTRL_NEUTRAL, CTRL_PLAIN = "control|vol+size|liq_top_decile", "control|none|liq_top_decile"
SETS = {
    "L1": {"dir": ML_DIR / "data_10y_liq", "cut": 0.67, "tag": "10y_liq",
           "neutral": "control|vol+size|top_decile", "plain": "control|none|top_decile",
           "universe": "liquid tercile (cs_rank_turnover >= 0.67)"},
    "L2": {"dir": ML_DIR / "data_10y_liq2", "cut": 0.33, "tag": "10y_liq2",
           "neutral": "control|vol+size|liq_top_decile", "plain": "control|none|liq_top_decile",
           "universe": "top two terciles (cs_rank_turnover >= 0.33)"},
}
T0 = time.time()


def log(msg: str) -> None:
    print(f"[liquid +{time.time() - T0:6.0f}s] {msg}", flush=True)


def rel(p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(REPO))
    except ValueError:
        return str(p)


def wjson(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(sb.clean_json(obj), indent=1, allow_nan=False) + "\n")
    tmp.replace(path)


# =========================================================================== labels
def relabel(date: pd.Series, y_raw: pd.Series) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """ml/data.py lines 198-202 on the given universe rows (the frame passed in IS the universe)."""
    df = pd.DataFrame({"date": date.to_numpy(), "y_raw_20d": y_raw.to_numpy(float)})
    mkt = df.groupby("date")["y_raw_20d"].transform("median")
    df["y_excess_20d"] = df["y_raw_20d"] - mkt
    df["y_rank_20d"] = df.groupby("date")["y_excess_20d"].rank(pct=True)
    lab = np.where(df["y_excess_20d"].notna(), (df["y_excess_20d"] > 0).astype(float), np.nan)
    return (df["y_excess_20d"].to_numpy(float), df["y_rank_20d"].to_numpy(float), lab.astype(float),
            mkt.to_numpy(float))


def _diff(a: np.ndarray, b: np.ndarray) -> dict:
    na, nb = np.isnan(a), np.isnan(b)
    fin = ~na & ~nb
    return {"nan_pattern_equal": bool(np.array_equal(na, nb)),
            "max_abs_diff": float(np.max(np.abs(a[fin] - b[fin]))) if fin.any() else 0.0,
            "n_compared": int(fin.sum())}


def hand_check(sub: pd.DataFrame, d: pd.Timestamp) -> dict:
    """Independent code path for one date: sort the finite y_raw_20d, take the middle (mean of the two middles when
    the count is even), subtract, rank with scipy's average ranks / n, threshold at zero."""
    from scipy.stats import rankdata
    g = sub[sub["date"] == d]
    y = g["y_raw_20d"].to_numpy(float)
    fin = np.isfinite(y)
    s = np.sort(y[fin])
    n = s.size
    med = float(s[n // 2]) if n % 2 else float(0.5 * (s[n // 2 - 1] + s[n // 2]))
    exc = np.where(fin, y - med, np.nan)
    rk = np.full(y.size, np.nan)
    rk[fin] = rankdata(exc[fin]) / n
    lab = np.where(fin, (exc > 0).astype(float), np.nan)
    st = {c: g[c].to_numpy(float) for c in LABELS}
    return {"date": str(d.date()), "rows": int(len(g)), "rows_with_y_raw": int(n), "clean_rows": int(g["y_clean_20d"].sum()),
            "median_y_raw_by_hand": med,
            "median_implied_by_stored": float(np.nanmedian(g["y_raw_20d"].to_numpy(float) - st["y_excess_20d"])),
            "rows_above_median": int((exc > 0).sum()), "rows_at_median": int((exc == 0).sum()),
            "rows_below_median": int((exc < 0).sum()),
            "label_mean": float(np.nanmean(lab)),
            "max_abs_diff_y_excess": float(np.nanmax(np.abs(exc - st["y_excess_20d"]))) if n else 0.0,
            "max_abs_diff_y_rank": float(np.nanmax(np.abs(rk - st["y_rank_20d"]))) if n else 0.0,
            "label_mismatches": int(np.sum(np.isfinite(lab) & (lab != st["label_beat_mkt_20d"]))),
            "nan_pattern_equal": bool(np.array_equal(np.isnan(lab), np.isnan(st["label_beat_mkt_20d"]))),
            "example_rows": [{"ticker": t, "y_raw_20d": float(a), "y_excess_20d": float(b), "y_rank_20d": float(c),
                              "label": None if not np.isfinite(e) else float(e)}
                             for t, a, b, c, e in list(zip(g["ticker"], y, st["y_excess_20d"], st["y_rank_20d"],
                                                           st["label_beat_mkt_20d"]))[:3]]}


# =========================================================================== benchmark rows
def base_rows(data_dir: Path) -> pd.DataFrame:
    """The books' base panel of a dataset: ml/books/data.py load_base on its own splits (fold windows + holdout,
    labeled, clean), i.e. exactly the rows ab_books builds its blocks from."""
    old = D.DATA_5Y
    D.DATA_5Y = Path(data_dir)
    try:
        return D.load_base(D.load_splits())
    finally:
        D.DATA_5Y = old


def bench_rows(base: pd.DataFrame, bench: str) -> pd.DataFrame:
    """Rows of the engine's equal-weight benchmark (ml/strategy_backtest.py Engine: ew_universe = every base row,
    ew_liquid = base rows with cs_rank_turnover >= LIQ_CUT)."""
    if bench == "ew_universe":
        return base
    assert bench == "ew_liquid", bench
    return base[base["cs_rank_turnover"].to_numpy(float) >= sb.LIQ_CUT]


def bench_check(b_set: pd.DataFrame, b_ctrl: pd.DataFrame) -> tuple[dict, pd.Series]:
    """Identical (date, ticker) rows and y_raw_20d -> identical benchmark: the engine's tranche path of a row is its
    own open-to-open path from the same price parquet, pinned to 1 + y_raw_20d at exit, so the equal-weight
    benchmark (tranche and daily) of two identical row sets is identical. Returns the per-signal-date gross tranche
    benchmark difference R_set - R_ctrl (mean y_raw_20d over the rows) for the correction path."""
    k = ["date", "ticker"]
    m = b_set[k + ["y_raw_20d"]].merge(b_ctrl[k + ["y_raw_20d"]], on=k, how="outer", suffixes=("_set", "_ctrl"),
                                       indicator=True)
    only_set, only_ctrl = int((m["_merge"] == "left_only").sum()), int((m["_merge"] == "right_only").sum())
    both = m[m["_merge"] == "both"]
    yd = np.abs(both["y_raw_20d_set"].to_numpy(float) - both["y_raw_20d_ctrl"].to_numpy(float))
    rs = b_set.groupby("date")["y_raw_20d"].mean()
    rc = b_ctrl.groupby("date")["y_raw_20d"].mean()
    dR = (rs - rc).dropna()
    out = {"rows_set": int(len(b_set)), "rows_control": int(len(b_ctrl)), "rows_only_in_set": only_set,
           "rows_only_in_control": only_ctrl, "y_raw_20d_max_abs_diff_on_common_rows": float(yd.max()) if yd.size else 0.0,
           "signal_dates_set": int(rs.size), "signal_dates_control": int(rc.size),
           "signal_dates_common": int(len(rs.index.intersection(rc.index))),
           "tranche_bench_max_abs_diff": float(np.abs(dR).max()) if dR.size else 0.0}
    out["identical"] = bool(only_set == 0 and only_ctrl == 0 and out["y_raw_20d_max_abs_diff_on_common_rows"] == 0.0
                            and out["signal_dates_set"] == out["signal_dates_control"] == out["signal_dates_common"])
    return out, (rs - rc)


# =========================================================================== build
def build(a) -> None:
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    t0 = time.time()
    src_pq = SRC / "model_dataset.parquet"
    tab = pq.read_table(src_pq)
    src_manifest = json.loads((SRC / "manifest.json").read_text())
    log(f"source {rel(src_pq)}: {tab.num_rows:,} rows, {tab.num_columns} columns")
    full = tab.select(["date", "ticker", "y_raw_20d", "y_clean_20d", "cs_rank_turnover", *LABELS]).to_pandas()
    full["date"] = pd.to_datetime(full["date"])
    # identity test: the same function on the full universe reproduces the stored labels
    e, r, lab, mkt_full = relabel(full["date"], full["y_raw_20d"])
    ident = {"y_excess_20d": _diff(e, full["y_excess_20d"].to_numpy(float)),
             "y_rank_20d": _diff(r, full["y_rank_20d"].to_numpy(float)),
             "label_beat_mkt_20d": _diff(lab, full["label_beat_mkt_20d"].to_numpy(float))}
    ident["reproduces_stored_labels"] = bool(all(v["nan_pattern_equal"] and v["max_abs_diff"] < 1e-12 for v in ident.values()))
    log(f"identity test on the full universe: {ident['reproduces_stored_labels']} "
        f"(max |d| y_excess {ident['y_excess_20d']['max_abs_diff']:.2e}, y_rank {ident['y_rank_20d']['max_abs_diff']:.2e})")
    assert ident["reproduces_stored_labels"], "relabel() does not reproduce ml/data.py on the full universe"
    full_med = pd.Series(mkt_full, index=full.index).groupby(full["date"]).first()
    ctrl_base = base_rows(SRC)
    ctrl_bench = bench_rows(ctrl_base, "ew_liquid")
    res = {"stream": "Q3", "built_at": datetime.now().isoformat(timespec="seconds"), "source": rel(src_pq),
           "source_rows": int(tab.num_rows), "source_manifest_built_at": src_manifest.get("built_at"),
           "label_rule": "ml/data.py lines 198-202 applied to the restricted universe's rows: per-date median of "
                         "y_raw_20d over every universe row with a non-missing y_raw_20d (clean or not; pandas "
                         "skipna), y_excess = y_raw - median, y_rank = per-date pct rank of y_excess, "
                         "label = 1(y_excess > 0) where y_excess is not NaN",
           "identity_test_full_universe": ident, "sets": {}}
    rng = np.random.default_rng(SEED)
    lab_dates = np.sort(full.loc[full["label_beat_mkt_20d"].notna(), "date"].unique())
    hand_dates = [pd.Timestamp(x) for x in np.sort(rng.choice(lab_dates, N_HAND_DATES, replace=False))]
    for name in a.sets:
        cfg = SETS[name]
        out_dir = cfg["dir"]
        mask = pc.greater_equal(tab["cs_rank_turnover"], pa.scalar(cfg["cut"], pa.float64()))
        sub_t = tab.filter(mask)
        sub = sub_t.select(["date", "ticker", "y_raw_20d", "y_clean_20d", "cs_rank_turnover", "label_up_5d",
                            *LABELS]).to_pandas()
        sub["date"] = pd.to_datetime(sub["date"])
        e, r, lab, mkt = relabel(sub["date"], sub["y_raw_20d"])
        old_lab = sub["label_beat_mkt_20d"].to_numpy(float)
        for c, v in zip(LABELS, (e, r, lab)):
            sub_t = sub_t.set_column(sub_t.schema.get_field_index(c), c, pa.array(v, type=pa.float64()))
            sub[c] = v
        assert np.array_equal(np.isnan(lab), ~np.isfinite(sub["y_raw_20d"].to_numpy(float))), "label NaN != y_raw NaN"
        out_dir.mkdir(parents=True, exist_ok=True)
        pq.write_table(sub_t, out_dir / "model_dataset.parquet")
        shutil.copyfile(SRC / "splits.json", out_dir / "splits.json")
        splits = json.loads((out_dir / "splits.json").read_text())
        f0 = splits["folds"][0]
        tr = sub[sub["date"] <= f0["train_end"]]
        man = dict(src_manifest)
        man.update({
            "built_at": datetime.now().isoformat(timespec="seconds"),
            "rows": int(len(sub)), "tickers": int(sub["ticker"].nunique()), "sessions": int(sub["date"].nunique()),
            "date_min": str(sub["date"].min().date()), "date_max": str(sub["date"].max().date()),
            "label_balance": {"beat_mkt_20d": float(np.nanmean(lab)), "up_5d": float(sub["label_up_5d"].mean()),
                              "y_clean_20d_pct": float(sub["y_clean_20d"].mean())},
            "first_fold": {"fold": f0, "train_rows": int(len(tr)),
                           "train_labeled_rows": int(tr["label_beat_mkt_20d"].notna().sum()),
                           "train_labeled_clean_rows": int((tr["label_beat_mkt_20d"].notna()
                                                            & tr["y_clean_20d"].astype(bool)).sum()),
                           "train_sessions": int(tr["date"].nunique()),
                           "note": "rows dated <= train_end; the walk-forward harness also purges by exit_date"},
            "version": f"{src_manifest.get('version')} | restricted to the {cfg['universe']} (stream Q3, "
                       "ml/IMPROVEMENT_PLAN_2.md)",
            "restriction": {"stream": "Q3", "set": name, "source": rel(SRC / "model_dataset.parquet"),
                            "row_filter": f"cs_rank_turnover >= {cfg['cut']} (full-universe per-date rank, as stored)",
                            "labels_recomputed": list(LABELS), "label_rule": res["label_rule"],
                            "features": "unchanged, including cs_rank_* ranked on the full universe",
                            "splits": "ml/data_10y/splits.json copied byte for byte"},
        })
        (out_dir / "manifest.json").write_text(json.dumps(man, indent=1, default=str))
        # ---- checks
        lab_ok = np.isfinite(lab)
        clean = sub["y_clean_20d"].to_numpy(bool)
        dcode = sub["date"]
        pdl = pd.Series(lab).groupby(dcode.to_numpy()).mean()
        pdc = pd.Series(np.where(clean, lab, np.nan)).groupby(dcode.to_numpy()).mean()
        q = lambda s: {k: float(v) for k, v in zip(("min", "p05", "median", "p95", "max"),  # noqa: E731
                                                   np.nanpercentile(s.dropna(), [0, 5, 50, 95, 100]))}
        yr = sub["date"].dt.year.to_numpy()
        per_year = {}
        for y_ in sorted(set(yr)):
            m = yr == y_
            per_year[str(y_)] = {"rows": int(m.sum()), "labeled": int((m & lab_ok).sum()),
                                 "labeled_clean": int((m & lab_ok & clean).sum()),
                                 "sessions": int(sub.loc[m, "date"].nunique()),
                                 "names_per_date_mean": float(m.sum() / max(sub.loc[m, "date"].nunique(), 1)),
                                 "label_mean": float(np.nanmean(lab[m])) if (m & lab_ok).any() else None}
        npd = sub.groupby("date").size()
        med_shift = (pd.Series(mkt, index=sub.index).groupby(sub["date"]).first() - full_med).dropna()
        flips = lab_ok & np.isfinite(old_lab)
        sb_base = base_rows(out_dir)
        bname = "ew_universe" if name == "L1" else "ew_liquid"
        bchk, _ = bench_check(bench_rows(sb_base, bname), ctrl_bench)
        bchk["benchmark_in_set_books"] = bname
        bchk["control_benchmark"] = "ew_liquid of ml/data_10y"
        hc = [hand_check(sub, d) for d in hand_dates]
        hc_ok = all(h["max_abs_diff_y_excess"] < 1e-12 and h["max_abs_diff_y_rank"] < 1e-12 and h["label_mismatches"] == 0
                    and h["nan_pattern_equal"] and abs(h["median_y_raw_by_hand"] - h["median_implied_by_stored"]) < 1e-12
                    for h in hc)
        s = {"dir": rel(out_dir), "row_filter": f"cs_rank_turnover >= {cfg['cut']}", "universe": cfg["universe"],
             "rows": int(len(sub)), "share_of_source_rows": float(len(sub) / tab.num_rows),
             "tickers": int(sub["ticker"].nunique()), "sessions": int(sub["date"].nunique()),
             "names_per_date": {"mean": float(npd.mean()), "min": int(npd.min()), "max": int(npd.max())},
             "labeled_rows": int(lab_ok.sum()), "labeled_clean_rows": int((lab_ok & clean).sum()),
             "label_balance_all_labeled": float(np.nanmean(lab)),
             "label_balance_labeled_clean": float(np.nanmean(np.where(clean, lab, np.nan))),
             "label_balance_per_date_labeled": q(pdl),
             "label_balance_per_date_labeled_clean": q(pdc),
             "labeled_dates": int(pdl.notna().sum()),
             "share_labeled_dates_balance_within_0_45_0_55": float(pdl.dropna().between(0.45, 0.55).mean()),
             "share_labeled_dates_balance_within_0_45_0_55_clean": float(pdc.dropna().between(0.45, 0.55).mean()),
             "share_labeled_dates_balance_within_0_48_0_52_clean": float(pdc.dropna().between(0.48, 0.52).mean()),
             "rows_per_year": per_year,
             "median_y_raw_restricted_minus_full_per_date": {"mean": float(med_shift.mean()), "sd": float(med_shift.std()),
                                                             **{k: v for k, v in q(med_shift).items()}},
             "share_labeled_rows_whose_label_differs_from_full_universe_label": float(
                 np.mean(lab[flips] != old_lab[flips])),
             "hand_check_dates": [str(d.date()) for d in hand_dates], "hand_check": hc, "hand_check_ok": bool(hc_ok),
             "benchmark_vs_control_ew_liquid": bchk,
             "files": {p.name: {"bytes": p.stat().st_size} for p in sorted(out_dir.iterdir())},
             "manifest_features": len(man["features"]), "splits_identical_to_source": (out_dir / "splits.json").read_bytes()
             == (SRC / "splits.json").read_bytes()}
        res["sets"][name] = s
        log(f"{name}: {s['rows']:,} rows, {s['tickers']} tickers, {s['sessions']} sessions, "
            f"{s['names_per_date']['mean']:.0f} names/date; label balance {s['label_balance_all_labeled']:.4f} "
            f"(per date {s['label_balance_per_date_labeled']['min']:.3f}..{s['label_balance_per_date_labeled']['max']:.3f}); "
            f"hand check {hc_ok}; benchmark identical to the control's ew_liquid: {bchk['identical']}")
        assert hc_ok, f"{name}: hand cross-check failed"
    res["build_seconds"] = round(time.time() - t0, 1)
    prev = json.loads((OUT / "build.json").read_text()) if (OUT / "build.json").exists() else None
    if prev:
        for k, v in prev.get("sets", {}).items():
            res["sets"].setdefault(k, v)
    wjson(OUT / "build.json", res)
    write_md()
    log("build written")


# =========================================================================== pass mark
def boot_ci(d: np.ndarray, block: int) -> dict:
    """Mean of d with a bootstrap 95% CI: block = 1 resamples months with replacement; block > 1 is a moving-block
    bootstrap (non-circular blocks of `block` consecutive months, ceil(M/block) blocks, truncated to M). B = 1000,
    a fresh generator seeded 108 for each version."""
    rng = np.random.default_rng(SEED)
    M = d.size
    block = min(block, M)          # only binds on smoke runs with fewer months than the block length
    if block == 1:
        idx = rng.integers(0, M, size=(B_BOOT, M))
    else:
        nb = math.ceil(M / block)
        st = rng.integers(0, M - block + 1, size=(B_BOOT, nb))
        idx = (st[:, :, None] + np.arange(block)[None, None, :]).reshape(B_BOOT, -1)[:, :M]
    m = d[idx].mean(1)
    lo, hi = float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))
    return {"block_months": block, "B": B_BOOT, "seed": SEED, "mean": float(d.mean()), "ci95": [lo, hi],
            "p_gt_0": float((m > 0).mean()), "ci_excludes_0": bool(lo > 0 or hi < 0), "ci_above_0": bool(lo > 0)}


def dsr_at(book: dict, N: int, var_sr: float) -> dict:
    """DSR at N trials: read from the book when ab_books ran at N, else re-deflated from the book's stored moments
    (same formula as ml/strategy_backtest.py dsr_block; only the expected-maximum Sharpe moves with N)."""
    if str(N) in book["dsr"]:
        x = book["dsr"][str(N)]
        return {"n_trials": N, "dsr": x["dsr"], "psr_vs_0": x["psr_vs_0"], "sr_annualised": x["sr_annualised"],
                "source": "books.json"}
    x = next(iter(book["dsr"].values()))
    sr0 = sb.expected_max_sr(var_sr, N)
    return {"n_trials": N, "dsr": sb.psr(x["sr_per_period"], sr0, x["T_periods"], x["skew"], x["kurtosis_pearson"]),
            "psr_vs_0": x["psr_vs_0"], "sr_annualised": x["sr_annualised"],
            "source": f"re-deflated from the moments stored at N = {x['n_trials']}"}


def ir_month_blocks(first_signal: pd.Timestamp, last_signal: pd.Timestamp) -> dict:
    """The month blocks of the engine's IR interval (ml/strategy_backtest.py Calendar, segment 'combined'): calendar
    months of the daily return days sessions[pos0 + 2 .. pos_last + H + 1]."""
    s = pd.read_parquet(PRICES, columns=["date"])["date"]
    sess = pd.DatetimeIndex(sorted(pd.to_datetime(s[s >= PRICE_START]).unique()))
    p0, p1 = sess.get_loc(first_signal), sess.get_loc(last_signal)
    days = sess[p0 + 2: p0 + 2 + (p1 - p0 + sb.HORIZON)]
    mon = sorted(set(days.strftime("%Y-%m")))
    return {"n_month_blocks": len(mon), "first": mon[0], "last": mon[-1], "n_days": len(days)}


def by_year(monthly: dict) -> dict:
    """Mean of a signal-month series by calendar year, annualised x 252/20 (descriptive)."""
    s = pd.Series(monthly, dtype=float)
    return {y: float(v * sb.PPY / sb.HORIZON) for y, v in s.groupby(s.index.str[:4]).mean().items()}


def book_reading(b: dict, N: int, var_sr: float) -> dict:
    c = b["segments"]["combined"]["20bps"]
    cn = b["segments"]["combined"]["name_level"]
    return {"key": b["key"], "benchmark": b["benchmark"], "n_signal_dates": b["n_signal_dates"], "n_months": b["n_months"],
            "basket_size_mean": b["basket_size_mean"], "excess_ann_vs_ew_20bps": c["excess_ann_vs_ew"],
            "ir_20bps": c["ir"], "ir_ci95": c["ir_ci95"], "p_ir_gt0": c["p_ir_gt0"],
            "months_positive": b["months_positive"], "turnover_per_rebalance": b["turnover_per_rebalance"],
            "excess_ann_vs_ew_name_level": cn["excess_ann_vs_ew"], "ir_name_level": cn["ir"],
            "breakeven_flat_cost_bps_per_side": b["breakeven_flat_cost_bps_per_side"],
            "capacity_rs_crore": (b["capacity"] or {}).get("aum_cap_rs_crore_p10name_5pct_adv"),
            "by_year_excess_ann_from_monthly": by_year(b["monthly_net_20bps"]),
            "cv_segment_ir_20bps": b["segments"]["cv"]["20bps"]["ir"],
            "holdout_segment_excess_ann_20bps": b["segments"]["holdout"]["20bps"]["excess_ann_vs_ew"],
            f"dsr_{N}": dsr_at(b, N, var_sr)}


def paired(bs: dict, bc: dict, adj: pd.Series | None, allow_partial: bool) -> dict:
    ms, mc = bs["monthly_net_20bps"], bc["monthly_net_20bps"]
    months = sorted(set(ms) & set(mc))
    cover = {"months_set": len(ms), "months_control": len(mc), "months_common": len(months),
             "same_signal_months": bool(set(ms) == set(mc)),
             "same_n_signal_dates": bool(bs["n_signal_dates"] == bc["n_signal_dates"]),
             "n_signal_dates": [bs["n_signal_dates"], bc["n_signal_dates"]],
             "expected_signal_months": EXPECTED_MONTHS, "months_equal_expected": bool(len(ms) == EXPECTED_MONTHS)}
    if not allow_partial:
        assert cover["same_signal_months"] and cover["same_n_signal_dates"] and cover["months_equal_expected"], \
            f"coverage differs: {cover}"
    d = np.array([ms[m] - mc[m] for m in months], float)
    if adj is not None:
        d = d + np.array([adj.get(m, 0.0) for m in months], float)
    per20 = sb.PPY / sb.HORIZON
    iid, blk = boot_ci(d, 1), boot_ci(d, BLOCK_MONTHS)
    return {"coverage": cover, "metric": "monthly_net_20bps of the set's book minus the control's (per 20-session "
                                         "tranche, mean by signal month, both vs the same EW liquid benchmark)",
            "n_months": int(d.size), "months_set_beats_control": int((d > 0).sum()),
            "mean_per_tranche": float(d.mean()), "mean_annualised_x12_6": float(d.mean() * per20),
            "sd_per_tranche": float(d.std(ddof=1)) if d.size > 1 else None,
            "max_abs": float(np.abs(d).max()) if d.size else None,
            "iid_months": iid, f"block_{BLOCK_MONTHS}_months": blk,
            "by_year_ann": by_year(dict(zip(months, d))),
            "benchmark_correction_applied": adj is not None, "_d": d}


def evaluate(name: str, books_set: dict, kn: str, kp: str, data_dir: Path, ctrl: dict, ctrl_bench: pd.DataFrame,
             var_sr: float, allow_partial: bool) -> dict:
    bn, bp = books_set["books"][kn], books_set["books"][kp]
    cn, cp = ctrl["books"][CTRL_NEUTRAL], ctrl["books"][CTRL_PLAIN]
    assert bn["benchmark"] == bp["benchmark"]
    bchk, dR = bench_check(bench_rows(base_rows(data_dir), bn["benchmark"]), ctrl_bench)
    bchk.update({"benchmark_in_set_books": bn["benchmark"], "control_benchmark": cn["benchmark"] + " of ml/data_10y",
                 "definition": "equal-weight liquid tercile (cs_rank_turnover >= 0.67), labeled clean rows of the "
                               "fold windows and the holdout"})
    adj = None
    if not bchk["identical"]:
        # tranche identity: (R_set - Rb_set) + (Rb_set - Rb_ctrl) = R_set - Rb_ctrl, averaged by signal month
        mon = pd.Series(pd.DatetimeIndex(dR.index).strftime("%Y-%m"), index=dR.index)
        adj = dR.dropna().groupby(mon[dR.dropna().index]).mean()
        bchk["correction"] = ("benchmark sets differ: the paired monthly differences were recomputed against the "
                              "control's ew_liquid (tranche benchmark difference added back by signal month); the "
                              "IR is the set's own engine reading and is NOT on the identical benchmark")
    pn, pp = paired(bn, cn, adj, allow_partial), paired(bp, cp, adj, allow_partial)
    rn = book_reading(bn, N_TRIALS, var_sr)
    ir_ok = bool(rn["ir_20bps"] >= PASS_IR and rn["ir_ci95"][0] > 0)
    pr_ok = bool(pn["mean_per_tranche"] > 0 and pn["iid_months"]["ci_above_0"])
    verdict = (ir_ok and pr_ok) if bchk["identical"] else None
    out = {"set": name, "books_json": books_set.get("_path"), "benchmark_check": bchk,
           "neutral_liquid_book": rn, "plain_liquid_book": book_reading(bp, N_TRIALS, var_sr),
           "paired_vs_control_neutral": {k: v for k, v in pn.items() if k != "_d"},
           "paired_vs_control_plain_descriptive": {k: v for k, v in pp.items() if k != "_d"},
           "pass_mark": {
               "ir_ge_0_5": bool(rn["ir_20bps"] >= PASS_IR), "ir_ci_excludes_0": bool(rn["ir_ci95"][0] > 0),
               "part_1_ir": ir_ok,
               "paired_mean_gt_0": bool(pn["mean_per_tranche"] > 0),
               "paired_iid_ci_excludes_0_above": bool(pn["iid_months"]["ci_above_0"]),
               "paired_block3_ci_excludes_0_above": bool(pn[f"block_{BLOCK_MONTHS}_months"]["ci_above_0"]),
               "part_2_paired": pr_ok,
               "readings_agree_iid_vs_block3": bool(pn["iid_months"]["ci_above_0"]
                                                    == pn[f"block_{BLOCK_MONTHS}_months"]["ci_above_0"]),
               "PASS": verdict}}
    return out, pn["_d"]


def run_compare(sets: dict, out_path: Path | None, allow_partial: bool, self_test: bool) -> dict:
    var_sr = json.loads(BOOKS_JSON.read_text())["dsr_common"]["var_sr_daily_across_66_books"]
    ctrl = json.loads(CONTROL_BOOKS.read_text())
    ctrl_base = base_rows(SRC)
    ctrl_bench = bench_rows(ctrl_base, ctrl["books"][CTRL_NEUTRAL]["benchmark"])
    dates = pd.DatetimeIndex(sorted(ctrl_base["date"].unique()))
    res = {"stream": "Q3", "plan": "ml/IMPROVEMENT_PLAN_2.md section 2, Q3", "written_at": datetime.now().isoformat(timespec="seconds"),
           "self_test": self_test,
           "pass_mark_text": "for L1 or L2, the neutral liquid book's IR >= 0.5 with its month-block 95% CI excluding "
                             "zero over the 105 signal months AND its paired monthly excess over the control's neutral "
                             "liquid book has a bootstrap 95% CI excluding zero",
           "design": {"cost": "20 bps per side (the phase headline)", "B": B_BOOT, "seed": SEED,
                      "paired_binding_reading": "months resampled with replacement (iid), CI lower bound > 0 and mean > 0",
                      "paired_robustness_reading": f"{BLOCK_MONTHS}-month moving-block bootstrap, reported beside it",
                      "ir_interval": "ml/strategy_backtest.py series_stats on the daily active series (exposure-weighted, "
                                     "month-block bootstrap, B = 1000, seed 108), as written by ml/improve/ab_books.py",
                      "ir_interval_month_blocks": ir_month_blocks(dates[0], dates[-1]),
                      "n_trials": N_TRIALS, "var_sr_daily": var_sr, "var_sr_source": rel(BOOKS_JSON)},
           "control": {"books_json": rel(CONTROL_BOOKS),
                       "neutral_liquid_book": book_reading(ctrl["books"][CTRL_NEUTRAL], N_TRIALS, var_sr),
                       "plain_liquid_book": book_reading(ctrl["books"][CTRL_PLAIN], N_TRIALS, var_sr)},
           "sets": {}}
    for name, cfg in sets.items():
        bj = json.loads(Path(cfg["books"]).read_text())
        bj["_path"] = rel(Path(cfg["books"]))
        ent, d = evaluate(name, bj, cfg["neutral"], cfg["plain"], cfg["dir"], ctrl, ctrl_bench, var_sr, allow_partial)
        cj = Path(cfg["books"]).parent / "compare.json"
        if cj.exists():
            m = json.loads(cj.read_text())["models"].get("control", {})
            ent["model_descriptive"] = {k: m.get(k) for k in ("cv_auc_mean", "cv_mean_ci95", "holdout_auc", "rank_ic_cv_mean",
                                                             "rank_ic_nw_t", "rank_ic_months_positive", "pct_folds_ge_050")}
            ent["model_descriptive"]["note"] = ("AUC and rank IC on the set's own restricted label; not comparable "
                                                "with the control's full-universe 0.5455")
        if self_test:
            ent["self_test_difference_identically_zero"] = bool(np.all(d == 0.0))
            assert ent["self_test_difference_identically_zero"], "self-test: difference is not identically zero"
            assert ent["benchmark_check"]["identical"], "self-test: benchmark check failed"
        res["sets"][name] = ent
        pm = ent["pass_mark"]
        log(f"{name}: neutral liquid IR {ent['neutral_liquid_book']['ir_20bps']:+.3f} {ent['neutral_liquid_book']['ir_ci95']}, "
            f"paired {ent['paired_vs_control_neutral']['mean_annualised_x12_6']:+.4f}/yr iid "
            f"{ent['paired_vs_control_neutral']['iid_months']['ci95']} -> PASS={pm['PASS']}")
    vs = [e["pass_mark"]["PASS"] for e in res["sets"].values()]
    res["verdict"] = ("PASS" if any(v is True for v in vs) else
                      "UNDETERMINED (benchmark mismatch)" if any(v is None for v in vs) else "FAIL")
    # definition 6: the verdict line says so when the binding (iid) and the 3-month-block readings disagree
    notes = []
    for n, e in res["sets"].items():
        pm, pn = e["pass_mark"], e["paired_vs_control_neutral"]
        if not pm["readings_agree_iid_vs_block3"]:
            notes.append(f"{n}: the iid paired CI {'excludes' if pm['paired_iid_ci_excludes_0_above'] else 'does not exclude'} "
                         f"zero on the positive side but the {BLOCK_MONTHS}-month block CI "
                         f"{'does' if pm['paired_block3_ci_excludes_0_above'] else 'does not'}; the iid reading is binding")
        if e["benchmark_check"].get("correction"):
            notes.append(f"{n}: {e['benchmark_check']['correction']}")
    res["verdict_notes"] = notes
    if out_path is not None:
        wjson(out_path, res)
    return res


def selftest(a) -> None:
    sets = {"control_vs_itself": {"books": CONTROL_BOOKS, "neutral": CTRL_NEUTRAL, "plain": CTRL_PLAIN, "dir": SRC}}
    out = Path(a.out) if a.out else OUT / "selftest.json"
    res = run_compare(sets, out, allow_partial=False, self_test=True)
    e = res["sets"]["control_vs_itself"]
    log(f"self-test: difference identically zero {e['self_test_difference_identically_zero']}, iid CI "
        f"{e['paired_vs_control_neutral']['iid_months']['ci95']}, part 2 {e['pass_mark']['part_2_paired']} (expected False)")
    if not a.out:
        write_md()


def compare(a) -> None:
    sets = {}
    for name in a.sets:
        cfg = dict(SETS[name])
        cfg["books"] = (Path(a.books_root) if a.books_root else OUT_ROOT) / cfg["tag"] / "books.json"
        sets[name] = cfg
    out_dir = Path(a.out) if a.out else OUT
    st = run_compare({"control_vs_itself": {"books": CONTROL_BOOKS, "neutral": CTRL_NEUTRAL, "plain": CTRL_PLAIN,
                                            "dir": SRC}}, None, False, True)
    res = run_compare(sets, None, a.allow_partial, False)
    e = st["sets"]["control_vs_itself"]
    res["self_test"] = {"what": "the pass-mark code path run on the control's own liquid books against themselves",
                        "difference_identically_zero": e["self_test_difference_identically_zero"],
                        "benchmark_identical": e["benchmark_check"]["identical"],
                        "iid_ci95": e["paired_vs_control_neutral"]["iid_months"]["ci95"],
                        "block3_ci95": e["paired_vs_control_neutral"][f"block_{BLOCK_MONTHS}_months"]["ci95"],
                        "part_2_paired": e["pass_mark"]["part_2_paired"], "expected_part_2": False}
    if a.allow_partial:
        res["smoke_partial_coverage"] = True
    wjson(out_dir / "liquid.json", res)
    if not a.out:
        write_md()
    log(f"verdict: {res['verdict']}")


# =========================================================================== markdown
DEFINITIONS = """\
## Definitions and deviations (fixed before any result of this stream existed)

1. **Datasets.** L1 = rows of `ml/data_10y/model_dataset.parquet` with `cs_rank_turnover >= 0.67` on that date (the
   full-universe rank, as stored); L2 = rows with `cs_rank_turnover >= 0.33`. Same columns and dtypes, the 52-feature
   manifest, `splits.json` copied byte for byte (103 folds, embargo 22, holdout 2026-08-03..2026-09-16), `exit_date`
   kept. Features, including the `cs_rank_*` columns and the per-date z-score `amihud_20` computed on the full
   universe, are unchanged, as the lead fixed.
2. **Labels.** Recomputed inside each restricted universe with `ml/data.py`'s own rule (lines 198-202):
   per-date median of `y_raw_20d` over every universe row with a non-missing `y_raw_20d` (clean or not, pandas skips
   NaN), `y_excess_20d = y_raw_20d - median`, `y_rank_20d` = per-date percentile rank of `y_excess_20d`,
   `label_beat_mkt_20d = 1(y_excess_20d > 0)` where `y_excess_20d` is not NaN. The same function applied to the full
   universe must reproduce the stored labels exactly (identity test), and five dates drawn with seed 108 are
   recomputed by a separate hand path (sort, middle value, scipy ranks).
3. **Model and books.** The control configuration through `ml/improve/ab.py` (rolling 504 sessions, exit-date purge,
   holdout once) on each dataset, then `ml/improve/ab_books.py` on the dataset's own base. In L1 every base row is
   liquid, so the liquid book is `control|vol+size|top_decile` (neutral) and `control|none|top_decile` (plain) and
   its benchmark (`ew_universe` of L1) is the equal-weight liquid tercile. In L2 the liquid book is
   `control|vol+size|liq_top_decile` / `control|none|liq_top_decile` with benchmark `ew_liquid`. The volatility+size
   neutralisation is the per-date regression on the dataset's own base rows: inside the liquid tercile for L1, inside
   the top two terciles for L2 (the control's neutral liquid book neutralises over the full universe, then picks the
   liquid decile). This is the construction the plan describes ("trained and scored on liquid rows only").
4. **Same benchmark.** `liquid.py compare` rebuilds the books' base panel of each dataset with `ml/books/data.py
   load_base` and checks that the benchmark rows (date, ticker, `y_raw_20d`) equal the control's `ew_liquid` rows
   (labeled clean liquid rows of the fold windows and the holdout). Identical rows mean an identical benchmark: each
   row's tranche path comes from the same price parquet and is pinned to `1 + y_raw_20d` at exit. If they differ,
   the paired monthly series is recomputed against the control's benchmark (the per-signal-date tranche benchmark
   difference added back by month), the IR is flagged as not on the identical benchmark, and the verdict reads
   UNDETERMINED instead of PASS/FAIL.
5. **IR interval (deviation).** The plan says "month-block 95% CI over the 105 signal months". The phase's IR and
   interval are the engine's (`ml/strategy_backtest.py series_stats` on the daily active series, exposure-weighted,
   month-block bootstrap B = 1000, seed 108, as written by `ab_books.py`). Its blocks are the calendar months of the
   daily return days, which run 20 sessions past the last signal date, so the block count is one more than the 105
   signal months (the exact count is recorded in `liquid.json` under `design.ir_interval_month_blocks`). The engine's
   reading is used unchanged because it is how the control's liquid IR (0.21) and every other book IR in both phases
   were measured. A daily series cannot be blocked by signal month without reassigning days that carry tranches of
   two signal months.
6. **Paired monthly excess.** For each of the 105 signal months: `monthly_net_20bps` of the set's neutral liquid book
   minus the control's (both are net 20 bps 20-session tranche returns minus the same EW liquid benchmark, averaged
   by signal month), so the benchmark cancels. Mean with a bootstrap 95% CI: months resampled with replacement,
   B = 1000, seed 108. This is the binding reading. "Excluding zero" is read on the positive side: the lower bound
   must be above zero and the mean positive (a CI wholly below zero would mean the set is worse than the control).
   A 3-month moving-block bootstrap (non-circular, ceil(105/3) blocks, fresh generator seeded 108) is reported beside
   it, because tranches of adjacent signal months overlap; if the two readings disagree, the verdict line says so.
   Annualised figures multiply the per-tranche mean by 252/20.
7. **Two configurations.** The mark is "L1 or L2". Both are counted in the trial ledger (6 trials), and each book's
   DSR is at N = 261 with V[SR] = 0.00387. The control's books (written at N = 241) are re-deflated at N = 261 from
   their stored moments.
8. **Descriptive only.** The models' CV AUC and rank IC are measured on each set's restricted label and are not
   comparable with the control's 0.5455. Name-level costs fill missing spreads and volatilities with the
   cross-sectional median of the dataset's own ticker set, so name-level figures can differ slightly from the
   control's for identical baskets. Neither enters the pass mark.
9. **Code-path test.** `liquid.py selftest` (and the first step of `compare`) runs the pass-mark code on the control's
   liquid books against themselves: the difference must be identically zero, the CI [0, 0] and part 2 FAIL.
"""


def _pct(x, d=1):
    return "n/a" if x is None else f"{100 * x:+.{d}f}%"


def _ci(c, d=2):
    return f"[{c[0]:+.{d}f}, {c[1]:+.{d}f}]"


def write_md() -> None:
    bj = json.loads((OUT / "build.json").read_text()) if (OUT / "build.json").exists() else None
    lj = json.loads((OUT / "liquid.json").read_text()) if (OUT / "liquid.json").exists() else None
    sj = json.loads((OUT / "selftest.json").read_text()) if (OUT / "selftest.json").exists() else None
    if lj and lj.get("smoke_partial_coverage"):
        lj = None
    status = lj["verdict"] if lj else "PENDING (full runs not yet done)"
    L = ["# Q3. A model for the liquid universe", "",
         f"**Verdict: {status}** · Plan: `ml/IMPROVEMENT_PLAN_2.md` §2 Q3 (2 configurations, 4 books = 6 trials) · "
         "Code: `ml/improve/liquid.py` · JSON: `ml/results/improve2/liquid/build.json`, `liquid.json`, `selftest.json`, "
         "`smoke.json`", "",
         "**Pass mark (fixed):** for L1 or L2, the neutral liquid book's IR ≥ 0.5 with its month-block 95% CI excluding "
         "zero over the 105 signal months **and** its paired monthly excess over the control's neutral liquid book has a "
         "bootstrap 95% CI excluding zero.", "", DEFINITIONS]
    L += ["## Datasets (`build.json`)", ""]
    if not bj:
        L += ["Not built yet.", ""]
    else:
        it = bj["identity_test_full_universe"]
        L += [f"Identity test: the label function applied to the full universe reproduces the stored labels: "
              f"**{it['reproduces_stored_labels']}** (max |Δ| `y_excess_20d` {it['y_excess_20d']['max_abs_diff']:.1e}, "
              f"`y_rank_20d` {it['y_rank_20d']['max_abs_diff']:.1e}, NaN patterns equal).", "",
              "| Set | Filter | Rows (share) | Tickers | Sessions | Names/date mean [min, max] | Label mean (labeled / clean) | "
              "Per-date label mean, p05..p95 [min, max] | Dates within 0.45-0.55 | Labels differing from full universe | "
              "Benchmark rows = control `ew_liquid` | Hand check |",
              "|---|---|---:|---:|---:|---|---|---|---:|---:|---|---|"]
        for n, s in bj["sets"].items():
            q, npd, bc = s["label_balance_per_date_labeled"], s["names_per_date"], s["benchmark_vs_control_ew_liquid"]
            L.append(f"| {n} | `{s['row_filter']}` | {s['rows']:,} ({100 * s['share_of_source_rows']:.1f}%) | {s['tickers']:,} | "
                     f"{s['sessions']:,} | {npd['mean']:.0f} [{npd['min']}, {npd['max']}] | "
                     f"{s['label_balance_all_labeled']:.4f} / {s['label_balance_labeled_clean']:.4f} | "
                     f"{q['p05']:.3f}..{q['p95']:.3f} [{q['min']:.3f}, {q['max']:.3f}] | "
                     f"{100 * s['share_labeled_dates_balance_within_0_45_0_55']:.1f}% ({s['labeled_dates']:,} dates) | "
                     f"{100 * s['share_labeled_rows_whose_label_differs_from_full_universe_label']:.1f}% | "
                     f"{bc['identical']} ({bc['rows_set']:,} vs {bc['rows_control']:,} rows) | {s['hand_check_ok']} |")
        L += ["", "Rows per year (all rows / labeled clean rows / names per date):", "",
              "| Year | " + " | ".join(bj["sets"]) + " |", "|---|" + "---:|" * len(bj["sets"])]
        years = sorted({y for s in bj["sets"].values() for y in s["rows_per_year"]})
        for y in years:
            cells = []
            for s in bj["sets"].values():
                r = s["rows_per_year"].get(y)
                cells.append("" if r is None else f"{r['rows']:,} / {r['labeled_clean']:,} / {r['names_per_date_mean']:.0f}")
            L.append(f"| {y} | " + " | ".join(cells) + " |")
        L += ["", "Hand cross-check (five dates drawn with seed 108; median by sorting, ranks by scipy):", "",
              "| Set | Date | Rows (with y_raw) | Median y_raw by hand | Median implied by stored labels | Above / at / below | "
              "Label mean | max abs Δ excess, rank | Label mismatches |", "|---|---|---:|---:|---:|---|---:|---|---:|"]
        for n, s in bj["sets"].items():
            for h in s["hand_check"]:
                L.append(f"| {n} | {h['date']} | {h['rows']} ({h['rows_with_y_raw']}) | {h['median_y_raw_by_hand']:+.6f} | "
                         f"{h['median_implied_by_stored']:+.6f} | {h['rows_above_median']} / {h['rows_at_median']} / "
                         f"{h['rows_below_median']} | {h['label_mean']:.4f} | {h['max_abs_diff_y_excess']:.0e}, "
                         f"{h['max_abs_diff_y_rank']:.0e} | {h['label_mismatches']} |")
        L += ["", "Per-date median of `y_raw_20d`, restricted minus full universe: " + "; ".join(
            f"{n} mean {_pct(s['median_y_raw_restricted_minus_full_per_date']['mean'], 2)} per 20 sessions "
            f"(sd {100 * s['median_y_raw_restricted_minus_full_per_date']['sd']:.2f}%)" for n, s in bj["sets"].items()) + ".", ""]
    L += ["## Pass mark (`liquid.json`)", ""]
    if not lj:
        L += ["Pending: the lead's full runs (see the commands below), then `python3 -m ml.improve.liquid compare`.", ""]
    else:
        ds = lj["design"]
        mb = ds["ir_interval_month_blocks"]
        L += [f"Cost 20 bps per side. IR interval month blocks: {mb['n_month_blocks']} calendar months "
              f"({mb['first']}..{mb['last']}, {mb['n_days']} return days) for 105 signal months. Paired CI: B = {ds['B']}, "
              f"seed {ds['seed']}. DSR at N = {ds['n_trials']}, V[SR] = {ds['var_sr_daily']:.5f}.", "",
              "| Book | Benchmark | Excess vs EW liquid /yr | IR [95% CI] | Months beating EW | Turnover / rebalance | "
              "Break-even bps/side | Capacity ₹ cr | Name-level excess /yr | DSR (N = 261) |",
              "|---|---|---:|---|---:|---:|---:|---:|---:|---:|"]
        rows = [("control (full-universe model), neutral", lj["control"]["neutral_liquid_book"]),
                ("control (full-universe model), plain", lj["control"]["plain_liquid_book"])]
        for n, e in lj["sets"].items():
            rows += [(f"{n}, neutral", e["neutral_liquid_book"]), (f"{n}, plain", e["plain_liquid_book"])]
        for lab, r in rows:
            be = r["breakeven_flat_cost_bps_per_side"]
            cap = r["capacity_rs_crore"]
            bm = "EW liquid tercile (L1's `ew_universe`)" if r["benchmark"] == "ew_universe" else "EW liquid tercile (`ew_liquid`)"
            L.append(f"| {lab} (`{r['key']}`) | {bm} | {_pct(r['excess_ann_vs_ew_20bps'])} | "
                     f"{r['ir_20bps']:+.2f} {_ci(r['ir_ci95'])} | {r['months_positive']}/{r['n_months']} | "
                     f"{100 * r['turnover_per_rebalance']:.0f}% | {'n/a' if be is None else f'{be:.0f}'} | "
                     f"{'n/a' if cap is None else f'{cap:,.0f}'} | {_pct(r['excess_ann_vs_ew_name_level'])} | "
                     f"{r['dsr_261']['dsr']:.3f} |")
        L += ["", "| Set | Paired vs control neutral liquid: mean /yr | iid 95% CI (/tranche) | 3-month block 95% CI | "
              "Months set > control | Part 1 (IR ≥ 0.5, CI > 0) | Part 2 (paired CI > 0) | Readings agree | Benchmark identical | **Result** |",
              "|---|---:|---|---|---:|---|---|---|---|---|"]
        for n, e in lj["sets"].items():
            p, pm = e["paired_vs_control_neutral"], e["pass_mark"]
            res = "PASS" if pm["PASS"] else ("UNDETERMINED" if pm["PASS"] is None else "FAIL")
            L.append(f"| {n} | {_pct(p['mean_annualised_x12_6'], 2)} | {_ci(p['iid_months']['ci95'], 4)} | "
                     f"{_ci(p['block_3_months']['ci95'], 4)} | {p['months_set_beats_control']}/{p['n_months']} | "
                     f"{'PASS' if pm['part_1_ir'] else 'FAIL'} | {'PASS' if pm['part_2_paired'] else 'FAIL'} | "
                     f"{pm['readings_agree_iid_vs_block3']} | {e['benchmark_check']['identical']} | **{res}** |")
        L += ["", "Plain liquid books, paired against the control's plain liquid book (descriptive, not a pass mark): " + "; ".join(
            f"{n} {_pct(e['paired_vs_control_plain_descriptive']['mean_annualised_x12_6'], 2)}/yr, iid CI "
            f"{_ci(e['paired_vs_control_plain_descriptive']['iid_months']['ci95'], 4)} per tranche"
            for n, e in lj["sets"].items()) + ".", ""]
        yrs = sorted(lj["control"]["neutral_liquid_book"]["by_year_excess_ann_from_monthly"])
        L += ["Neutral liquid books by signal year: excess vs EW liquid per year (mean of the signal months x 252/20, "
              "20 bps), and the paired difference against the control (descriptive):", "",
              "| Year | Control | " + " | ".join(f"{n} | {n} − control" for n in lj["sets"]) + " |",
              "|---|---:|" + "---:|---:|" * len(lj["sets"])]
        for y in yrs:
            cells = [_pct(lj["control"]["neutral_liquid_book"]["by_year_excess_ann_from_monthly"].get(y))]
            for e in lj["sets"].values():
                cells += [_pct(e["neutral_liquid_book"]["by_year_excess_ann_from_monthly"].get(y)),
                          _pct(e["paired_vs_control_neutral"]["by_year_ann"].get(y))]
            L.append(f"| {y} | " + " | ".join(cells) + " |")
        L += [""]
        md = [(n, e["model_descriptive"]) for n, e in lj["sets"].items() if e.get("model_descriptive")]
        if md:
            L += ["Models (descriptive, each on its own restricted label): " + "; ".join(
                f"{n} CV AUC {m['cv_auc_mean']:.4f} {_ci(m['cv_mean_ci95'], 4)}, holdout {'n/a' if m['holdout_auc'] is None else format(m['holdout_auc'], '.4f')}, rank IC "
                f"{m['rank_ic_cv_mean']:+.4f} (NW t {m['rank_ic_nw_t']:.1f})" for n, m in md) + ".", ""]
        notes = lj.get("verdict_notes") or []
        L += [f"**Verdict: {lj['verdict']}.**" + ("" if not notes else " " + " ".join(f"Note: {x}." for x in notes)), ""]
    L += ["## Code-path test (`selftest.json`)", ""]
    st = (lj or {}).get("self_test") if lj and isinstance(lj.get("self_test"), dict) else None
    if st:
        L += [f"Control's liquid books against themselves: difference identically zero **{st['difference_identically_zero']}**, "
              f"benchmark identical {st['benchmark_identical']}, iid CI {_ci(st['iid_ci95'], 4)}, block CI "
              f"{_ci(st['block3_ci95'], 4)}, part 2 {st['part_2_paired']} (expected False).", ""]
    elif sj:
        e = sj["sets"]["control_vs_itself"]
        L += [f"Control's liquid books against themselves: difference identically zero "
              f"**{e['self_test_difference_identically_zero']}**, benchmark identical {e['benchmark_check']['identical']}, "
              f"iid CI {_ci(e['paired_vs_control_neutral']['iid_months']['ci95'], 4)}, part 2 "
              f"{e['pass_mark']['part_2_paired']} (expected False); IR month blocks "
              f"{sj['design']['ir_interval_month_blocks']['n_month_blocks']}.", ""]
    else:
        L += ["Not run yet.", ""]
    smk = json.loads((OUT / "smoke.json").read_text()) if (OUT / "smoke.json").exists() else None
    if smk:
        rt = smk["runtime_estimate_full"]
        L += ["## Smoke run (`smoke.json`; code path and runtime only, outputs deleted)", ""]
        for s in smk["steps"]:
            w = s["wall_seconds"]
            w = ", ".join(f"{k} {v} s" for k, v in w.items()) if isinstance(w, dict) else f"{w} s"
            extra = f" Seconds per fold {s['seconds_per_fold']}, training rows {s['train_rows_per_fold']}." \
                if "seconds_per_fold" in s else ""
            L.append(f"- `{s['cmd']}`: {'ran' if s['ok'] else 'FAILED'} ({w}).{extra}")
            for c in s.get("checked", []):
                L.append(f"  - {c}.")
            if s.get("deviation_smoke_only"):
                L.append(f"  - Smoke-only deviation: {s['deviation_smoke_only']}")
        L += ["", f"Deleted: {', '.join(f'`{d}`' for d in smk['deleted'])}. Full-run estimate: about "
              f"{rt['total_minutes']} minutes ({'; '.join(f'{k} {v}' for k, v in rt['minutes'].items())}); {rt['note']}. "
              f"Basis: {rt['basis']}.", ""]
    L += ["## Reproduce", "", "```",
          "cd /home/user/SuryaDhana_AI && python3 -m ml.improve.liquid build",
          "cd /home/user/SuryaDhana_AI && python3 -m ml.improve.ab run --data ml/data_10y_liq --tag 10y_liq --configs control --n-jobs 2",
          "cd /home/user/SuryaDhana_AI && python3 -m ml.improve.ab run --data ml/data_10y_liq2 --tag 10y_liq2 --configs control --n-jobs 2",
          "cd /home/user/SuryaDhana_AI && python3 -m ml.improve.ab_books --tag 10y_liq --data ml/data_10y_liq --prices "
          "ml/results/improve/cache/features_prices_export_10y.parquet --price-start 2017-10-02 --n-trials 261",
          "cd /home/user/SuryaDhana_AI && python3 -m ml.improve.ab_books --tag 10y_liq2 --data ml/data_10y_liq2 --prices "
          "ml/results/improve/cache/features_prices_export_10y.parquet --price-start 2017-10-02 --n-trials 261",
          "cd /home/user/SuryaDhana_AI && python3 -m ml.improve.ab compare --data ml/data_10y_liq --tag 10y_liq",
          "cd /home/user/SuryaDhana_AI && python3 -m ml.improve.ab compare --data ml/data_10y_liq2 --tag 10y_liq2",
          "cd /home/user/SuryaDhana_AI && python3 -m ml.improve.liquid compare", "```", ""]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "LIQUID.md").write_text("\n".join(L))


# =========================================================================== main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["md", "build", "selftest", "compare"])
    ap.add_argument("--sets", nargs="+", default=list(SETS), choices=list(SETS))
    ap.add_argument("--out", default=None, help="selftest / compare: write the JSON here instead (smoke tests)")
    ap.add_argument("--books-root", default=None, help="compare: folder holding <tag>/books.json (default ab/)")
    ap.add_argument("--allow-partial", action="store_true", help="compare: smoke books covering a subset of months")
    a = ap.parse_args()
    if a.stage == "md":
        write_md()
    elif a.stage == "build":
        build(a)
    elif a.stage == "selftest":
        selftest(a)
    else:
        compare(a)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Phase 2 stream Q5: the 40-day horizon (ml/IMPROVEMENT_PLAN_2.md §2 Q5; definitions in
ml/results/improve2/h40/H40.md, fixed before any result).

1. ``build``    ml/data_10y_h40/: the rows and 52 features of ml/data_10y with every 20-day label column REPLACED
                by its 40-session version under the SAME column name (so ml/improve/ab.py runs unchanged; the
                manifest says so in ``label_horizon_sessions: 40``): y_raw_20d = open[t+41]/open[t+1] - 1 on the
                ticker's own rows (split/bonus-adjusted opens of equity_features, read from the parquet export),
                y_excess_20d / y_rank_20d / label_beat_mkt_20d against the per-date universe median, y_clean_20d
                (opens > 0, rows t+1 and t+41 present, span <= 88 days, no |ret_1d| > 22% on rows t+1..t+41) and
                exit_date = date of row t+41; splits with the same test windows and a 42-session embargo.  Before
                writing anything the same code with horizon 20 must reproduce ml/data_10y's labels, exit dates,
                ret_1d and splits exactly.
2. ``books``    40-session books for one scorer (vol+size neutral top decile and liquid-tercile top decile) on the
                base panel common to both scorers, with ml/books (build_blocks_h, neutralise, members_simple,
                BookEngine.run_members, construct.summarize) and DSR at N = 261.
3. ``compare``  the Q5 pass mark: the 40-day model's neutral full-universe book vs the 20-day control's, paired
                monthly difference of net 20 bps excess (months resampled, B = 1000, seed 108; 3-month blocks
                beside it) and the flat break-even cost per side; self-test on the control against itself;
                writes h40.json and the results part of H40.md.

    cd /home/user/SuryaDhana_AI && python3 -m ml.improve.h40 build
    cd /home/user/SuryaDhana_AI && python3 -m ml.improve.h40 books --scorer control20
    cd /home/user/SuryaDhana_AI && python3 -m ml.improve.h40 books --scorer h40
    cd /home/user/SuryaDhana_AI && python3 -m ml.improve.h40 compare

Never opens nse_market.duckdb.  Seed 108, OMP_NUM_THREADS=2, single process.
"""
from __future__ import annotations

import os

os.environ["OMP_NUM_THREADS"] = "2"
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")

import argparse
import hashlib
import json
import math
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import ml.strategy_backtest as sb
from ml.books import construct as C
from ml.books import data as D
from ml.books import engine as E
from ml.data import SPLIT_MOVE_THRESHOLD, _fwd_window_max
from ml.improve.ab import OUT_ROOT, TASK
from ml.scale5y_report import _block_counts_within, ci, nw_t, per_date_ic

ML_DIR = Path(__file__).resolve().parents[1]
REPO = ML_DIR.parent
DATA_10Y = ML_DIR / "data_10y"
DATA_H40 = ML_DIR / "data_10y_h40"
PRICES = ML_DIR / "results" / "improve" / "cache" / "features_prices_export_10y.parquet"
PRICE_START = "2017-10-02"                    # the ten-year A/B books' price grid (ml/results/improve/ab/10y/queue_10y.sh)
OUT = ML_DIR / "results" / "improve2" / "h40"
BOOKS_JSON = ML_DIR / "results" / "improve" / "books" / "books.json"
CONTROL10Y_BOOKS = OUT_ROOT / "10y" / "books.json"
H40_TAG = "10y_h40"

SEED = 108
H = 40
SPAN_DAYS = {20: 45, 40: 88}                  # calendar-day cap on date[t+H+1] - date[t+1]
EMBARGO = {20: 22, 40: 42}
HOLDOUT_START = "2026-08-01"
N_TRIALS = 261
B_BOOT = 1000
BLOCK_MONTHS = 3
NEUT = "vol+size"
BASKETS = ("top_decile", "liq_top_decile")
LABEL_COLS = ["y_raw_20d", "y_excess_20d", "y_rank_20d", "label_beat_mkt_20d", "y_clean_20d"]
DROPPED_LABELS = ["fwd_ret_5d", "label_up_5d"]
SCORERS = {
    "control20": {"preds": OUT_ROOT / "10y" / "preds" / f"control__{TASK}.parquet", "label": "label20",
                  "what": "the 20-day control (LightGBM, 52 features) trained on the 20-day label, ten-year run"},
    "h40": {"preds": OUT_ROOT / H40_TAG / "preds" / f"control__{TASK}.parquet", "label": "label_beat_mkt_20d",
            "what": "the control configuration trained on the 40-day label (ml/data_10y_h40; harness file names keep 20d)"},
}
PASS_BOOK = f"{NEUT}|top_decile"
META_KEYS = ("base_panel", "hold40_screen", "block_set_hash", "bench_R_hash", "benchmarks_H40", "descriptive_on_40d_label",
             "preds", "n_signal_dates", "n_holdout_signal_dates")
MARKER = "<!-- RESULTS (generated from h40.json by python3 -m ml.improve.h40; everything below this line is rewritten on each run) -->"

T0 = time.time()


def log(msg: str) -> None:
    print(f"[h40 +{time.time() - T0:6.0f}s] {msg}", flush=True)


def rel(p: Path) -> str:
    p = Path(p).resolve()
    try:
        return str(p.relative_to(REPO))
    except ValueError:
        return str(p)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


# =========================================================================== labels
def read_own_prices() -> pd.DataFrame:
    """equity_features rows (all tickers, 2016-10..2026-10) from the parquet export, per-ticker chronological:
    the row set ml/data.py's per-ticker shifts ran on (ETF tickers are whole tickers, so they do not change any
    other ticker's shifts)."""
    fp = pd.read_parquet(PRICES, columns=["date", "ticker", "open", "close"])
    fp["date"] = pd.to_datetime(fp["date"]).astype("datetime64[ns]")
    assert not fp.duplicated(["date", "ticker"]).any()
    return fp.sort_values(["ticker", "date"], kind="stable").reset_index(drop=True)


def own_labels(fp: pd.DataFrame, h: int) -> pd.DataFrame:
    """ml/data.py's per-ticker label block with FWD_SESSIONS = h (entry open t+1, exit open t+h+1, the ticker's own
    rows), its clean mask (span cap SPAN_DAYS[h]) and the exit date of ml/integrity/build_v2.extra_columns."""
    g = fp.groupby("ticker", sort=False)
    entry_open = g["open"].shift(-1)
    exit_open = g["open"].shift(-(h + 1))
    y_raw = exit_open / entry_open - 1
    entry_date = g["date"].shift(-1)
    exit_date = g["date"].shift(-(h + 1))
    span_days = (exit_date - entry_date).dt.days
    ret_1d = fp["close"] / g["close"].shift(1) - 1           # equity_features ret_1d = close.pct_change() per ticker
    absret = ret_1d.abs()
    fwd_absmax = absret.groupby(fp["ticker"], sort=False).transform(lambda s: _fwd_window_max(s, h + 1))
    clean = (y_raw.notna() & (entry_open > 0) & (exit_open > 0) & (span_days <= SPAN_DAYS[h])
             & (fwd_absmax <= SPLIT_MOVE_THRESHOLD))
    return pd.DataFrame({"date": fp["date"], "ticker": fp["ticker"], "y_raw": y_raw, "y_clean": clean.to_numpy(bool),
                         "exit_date": exit_date, "ret_1d": ret_1d})


def dataset_labels(keys: pd.DataFrame, own: pd.DataFrame) -> pd.DataFrame:
    """Labels on the dataset rows: own-row pieces joined one-to-one, cross-sectional pieces over the dataset rows
    of each date (ml/data.py: median over the universe rows, NaN skipped; rank of the excess; beat label)."""
    m = keys[["date", "ticker"]].merge(own, on=["date", "ticker"], how="left", validate="one_to_one")
    assert len(m) == len(keys)
    out = pd.DataFrame(index=keys.index)
    out["y_raw_20d"] = m["y_raw"].to_numpy(float)
    d = pd.Series(keys["date"].to_numpy())
    yr = pd.Series(out["y_raw_20d"].to_numpy(float))
    mkt = yr.groupby(d).transform("median")
    exc = yr - mkt
    out["y_excess_20d"] = exc.to_numpy(float)
    out["y_rank_20d"] = exc.groupby(d).rank(pct=True).to_numpy(float)
    out["label_beat_mkt_20d"] = np.where(exc.notna(), (exc > 0).astype(float), np.nan)
    out["y_clean_20d"] = m["y_clean"].fillna(False).to_numpy(bool)
    out["exit_date"] = pd.to_datetime(m["exit_date"]).to_numpy(dtype="datetime64[ns]")
    out["_ret_1d"] = m["ret_1d"].to_numpy(float)
    return out


def make_splits(dates: pd.DatetimeIndex, last_labeled: pd.Timestamp, ref: dict, embargo: int) -> dict:
    """ml/data.py month_fold / holdout rule on the dataset's sessions with the given embargo; fold months = ref's."""
    folds = []
    for f in ref["folds"]:
        y, m = (int(x) for x in f["name"].split("-"))
        in_m = dates[(dates.year == y) & (dates.month == m)]
        test_start, test_end = in_m.min(), in_m.max()
        pos = dates.get_loc(test_start)
        folds.append({"name": f["name"], "train_end": str(dates[max(pos - embargo, 0)].date()),
                      "test_start": str(test_start.date()), "test_end": str(min(test_end, last_labeled).date())})
    pos = dates.get_loc(dates[dates >= pd.Timestamp(HOLDOUT_START)][0])
    holdout = {"name": "holdout", "train_end": str(dates[pos - embargo].date()), "test_start": str(dates[pos].date()),
               "test_end": str(last_labeled.date())}
    return {"folds": folds, "holdout": holdout, "embargo_sessions": embargo}


def _same(a: np.ndarray, b: np.ndarray) -> dict:
    """Exact equality incl. NaN/NaT positions; bitwise for floats."""
    if np.issubdtype(a.dtype, np.datetime64):
        na, nb = np.isnat(a), np.isnat(b)
        eq = (na == nb).all() and (a[~na] == b[~nb]).all()
        return {"identical": bool(eq), "n_mismatch": int((na != nb).sum() + (a[~na & ~nb] != b[~na & ~nb]).sum())}
    if a.dtype == bool or b.dtype == bool:
        return {"identical": bool(np.array_equal(a.astype(bool), b.astype(bool))),
                "n_mismatch": int((a.astype(bool) != b.astype(bool)).sum())}
    a, b = a.astype(float), b.astype(float)
    na, nb = np.isnan(a), np.isnan(b)
    fin = ~na & ~nb
    bit = a[fin].view(np.int64) == b[fin].view(np.int64)
    mx = float(np.max(np.abs(a[fin] - b[fin]))) if fin.any() else 0.0
    return {"identical": bool((na == nb).all() and bit.all()), "n_nan_mismatch": int((na != nb).sum()),
            "n_value_not_bitwise_equal": int((~bit).sum()), "max_abs_diff": mx}


def verify_h20(ds10: pd.DataFrame, own20: pd.DataFrame, splits10: dict) -> dict:
    lab = dataset_labels(ds10[["date", "ticker"]], own20)
    res = {c: _same(lab[c].to_numpy(), ds10[c].to_numpy()) for c in LABEL_COLS}
    res["exit_date"] = _same(lab["exit_date"].to_numpy(dtype="datetime64[ns]"),
                             ds10["exit_date"].to_numpy(dtype="datetime64[ns]"))
    res["ret_1d (feature, recomputed from the export)"] = _same(lab["_ret_1d"].to_numpy(), ds10["ret_1d"].to_numpy())
    dates = pd.DatetimeIndex(np.sort(ds10["date"].unique()))
    last = pd.Timestamp(ds10.loc[ds10["label_beat_mkt_20d"].notna(), "date"].max())
    sp = make_splits(dates, last, splits10, EMBARGO[20])
    res["splits"] = {"identical": bool(sp["folds"] == splits10["folds"] and sp["holdout"] == splits10["holdout"]
                                       and sp["embargo_sessions"] == splits10["embargo_sessions"]),
                     "n_folds": len(sp["folds"])}
    res["all_identical"] = bool(all(v["identical"] for v in res.values()))
    return res


def build(force: bool) -> None:
    man_p, pq_p = DATA_H40 / "manifest.json", DATA_H40 / "model_dataset.parquet"
    if not force and man_p.exists() and pq_p.exists():
        man = json.loads(man_p.read_text())
        if man.get("parquet_sha256") == sha256_file(pq_p) and man.get("label_horizon_sessions") == H:
            log(f"{rel(DATA_H40)} present and its parquet matches the manifest hash; nothing to do (--force rebuilds)")
            return
    OUT.mkdir(parents=True, exist_ok=True)
    m10 = json.loads((DATA_10Y / "manifest.json").read_text())
    s10 = json.loads((DATA_10Y / "splits.json").read_text())
    ds = pd.read_parquet(DATA_10Y / "model_dataset.parquet")
    ds["date"] = pd.to_datetime(ds["date"]).astype("datetime64[ns]")
    ds["exit_date"] = pd.to_datetime(ds["exit_date"]).astype("datetime64[ns]")
    log(f"ml/data_10y: {len(ds):,} rows x {ds.shape[1]} columns")
    fp = read_own_prices()
    log(f"equity_features export: {len(fp):,} rows, {fp['ticker'].nunique()} tickers")

    # ---- 1. the code path with horizon 20 must reproduce ml/data_10y exactly
    v20 = verify_h20(ds, own_labels(fp, 20), s10)
    log("horizon-20 reproduction: " + ", ".join(f"{k}={'OK' if v['identical'] else 'DIFF'}" for k, v in v20.items()
                                                if isinstance(v, dict)))
    if not v20["all_identical"]:
        C.wjson(OUT / "build.json", {"verification_h20": v20, "verdict": "FAIL: dataset not written"})
        raise SystemExit("horizon-20 reproduction failed; see ml/results/improve2/h40/build.json")

    # ---- 2. horizon 40
    own40 = own_labels(fp, H)
    lab = dataset_labels(ds[["date", "ticker"]], own40)
    old = {c: ds[c].to_numpy() for c in LABEL_COLS + ["exit_date"]}
    feats = list(m10["features"])
    out = ds[["date", "ticker"] + feats].copy()
    for c in LABEL_COLS:
        out[c] = lab[c].to_numpy()
    out["y_clean_20d"] = out["y_clean_20d"].astype(bool)
    out["exit_date"] = lab["exit_date"].to_numpy(dtype="datetime64[ns]")
    assert out[["date", "ticker"]].equals(ds[["date", "ticker"]])
    dates = pd.DatetimeIndex(np.sort(out["date"].unique()))
    labeled = out["label_beat_mkt_20d"].notna().to_numpy()
    last = pd.Timestamp(out.loc[labeled, "date"].max())
    splits = make_splits(dates, last, s10, EMBARGO[H])
    splits["note"] = ("train = labeled rows with date <= train_end; embargo 42 sessions covers the 40-session forward "
                      "label window (entry t+1, exit t+41); the harness also purges training rows whose exit_date is on "
                      "or after test_start. LABELS ARE 40-SESSION under the 20d column names (manifest.json).")
    DATA_H40.mkdir(parents=True, exist_ok=True)
    tmp = pq_p.with_suffix(".parquet.tmp")
    out.to_parquet(tmp, index=False)
    tmp.replace(pq_p)
    (DATA_H40 / "splits.json").write_text(json.dumps(splits, indent=1))

    # ---- 3. descriptive checks (deviation 4 and the clean-mask overlap)
    cal = pd.DatetimeIndex(np.sort(fp["date"].unique()))          # every market session of the store
    clean40 = labeled & out["y_clean_20d"].to_numpy(bool)
    clean20 = ds["label_beat_mkt_20d"].notna().to_numpy() & ds["y_clean_20d"].to_numpy(bool)
    pi = np.searchsorted(cal.values, out["date"].to_numpy(dtype="datetime64[ns]"))
    ex = out["exit_date"].to_numpy(dtype="datetime64[ns]")
    has = ~np.isnat(ex)
    pe = np.full(len(out), -1)
    pe[has] = np.searchsorted(cal.values, ex[has])
    gap = has & (pe - pi > H + 1)
    first = splits["folds"][0]
    tr = out[(out["date"] <= first["train_end"])]
    trc = tr["label_beat_mkt_20d"].notna() & tr["y_clean_20d"]
    info = {
        "rows": int(len(out)), "tickers": int(out["ticker"].nunique()), "sessions": int(len(dates)),
        "labeled_rows_40d": int(labeled.sum()), "labeled_clean_rows_40d": int(clean40.sum()),
        "y_clean_share_40d": float(out["y_clean_20d"].mean()), "label_balance_40d": float(np.nanmean(out["label_beat_mkt_20d"])),
        "last_labeled_date_40d": str(last.date()),
        "labeled_clean_rows_20d": int(clean20.sum()),
        "clean_overlap": {"both": int((clean40 & clean20).sum()), "clean_40_not_20": int((clean40 & ~clean20).sum()),
                          "clean_20_not_40": int((clean20 & ~clean40).sum())},
        "rows_40d_clean_with_a_missing_market_session_in_window": int((gap & clean40).sum()),
        "share_40d_clean_with_a_missing_market_session_in_window": float((gap & clean40).sum() / max(clean40.sum(), 1)),
        "max_market_sessions_spanned_by_a_clean_40d_label": int((pe - pi)[clean40].max()),
        "first_fold": {"fold": first, "train_rows": int(len(tr)), "train_labeled_clean_rows": int(trc.sum()),
                       "train_sessions": int(tr["date"].nunique())},
        "holdout": splits["holdout"],
        "label_column_differs_from_data_10y": {c: not _same(out[c].to_numpy(), old[c])["identical"] for c in
                                               LABEL_COLS + ["exit_date"]},
        "features_identical_to_data_10y": bool(all(_same(out[c].to_numpy(), ds[c].to_numpy())["identical"] for c in feats)),
    }
    manifest = dict(m10)
    manifest.update({
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "built_by": "python3 -m ml.improve.h40 build (phase 2 stream Q5)",
        "label_horizon_sessions": H,
        "label_columns_renamed_warning": (
            "EVERY *_20d LABEL COLUMN IN THIS DATASET HOLDS THE 40-SESSION VERSION under the 20-day name, so "
            "ml/improve/ab.py runs unchanged: y_raw_20d = open[t+41]/open[t+1] - 1 (ticker's own rows, split/bonus-"
            "adjusted opens); y_excess_20d = minus the per-date universe median; y_rank_20d; label_beat_mkt_20d; "
            "y_clean_20d = opens > 0, rows t+1..t+41 present, span <= 88 days, no |ret_1d| > 22% on rows t+1..t+41; "
            "exit_date = date of row t+41. The key last_labeled_date_20d likewise holds the 40-session date."),
        "label_cols": LABEL_COLS,
        "labels_not_carried": {c: "5-session secondary label, no 40-session version, unused by the harness" for c in DROPPED_LABELS},
        "derived_from": {"rows_and_features": "ml/data_10y (identical rows, order and 52 features)",
                         "labels_from": rel(PRICES), "data_10y_manifest_built_at": m10.get("built_at")},
        "last_labeled_date_20d": str(last.date()), "last_labeled_date_40d": str(last.date()),
        "primary_task": "beat_mkt_40d stored as beat_mkt_20d (40-session next-open excess vs universe median)",
        "label_balance": {"beat_mkt_40d": info["label_balance_40d"], "y_clean_40d_pct": info["y_clean_share_40d"]},
        "embargo_sessions": EMBARGO[H],
        "first_fold": info["first_fold"],
        "verification_h20": {"all_identical": v20["all_identical"], "file": rel(OUT / "build.json")},
        "parquet_sha256": sha256_file(pq_p), "build_seconds": round(time.time() - T0, 1),
    })
    manifest.pop("secondary_task", None)
    (DATA_H40 / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str))
    C.wjson(OUT / "build.json", {
        "what": "ml/data_10y_h40 build: horizon-20 reproduction of ml/data_10y (the code-path proof), then horizon 40",
        "verification_h20": v20, "verdict": "PASS: horizon-20 code path reproduces ml/data_10y exactly; dataset written",
        "dataset": info, "splits_file": rel(DATA_H40 / "splits.json"), "manifest": rel(man_p),
        "seconds": round(time.time() - T0, 1)})
    log(f"wrote {rel(DATA_H40)}: {info['labeled_clean_rows_40d']:,} clean 40-day labels (last {last.date()}); "
        f"holdout {splits['holdout']}; first fold trains on {info['first_fold']['train_sessions']} sessions")


# =========================================================================== books
def book_base(folds: list[str] | None = None) -> tuple[pd.DataFrame, dict]:
    """40-day test-window rows, 40-day labelled and clean (ml/books/data.load_base on ml/data_10y_h40), restricted to
    rows also 20-day labelled and clean (deviation 3): the panel both scorers rank."""
    D.DATA_5Y, D.PRICES_PARQUET, D.PRICE_START = DATA_H40, PRICES, PRICE_START
    splits = D.load_splits()
    assert splits["embargo_sessions"] == EMBARGO[H]
    base = D.load_base(splits)
    n40 = len(base)
    d20 = pd.read_parquet(DATA_10Y / "model_dataset.parquet", columns=["date", "ticker", "label_beat_mkt_20d", "y_clean_20d"])
    d20["date"] = pd.to_datetime(d20["date"])
    d20 = d20.rename(columns={"label_beat_mkt_20d": "label20", "y_clean_20d": "clean20"})
    base = base.merge(d20, on=["date", "ticker"], how="left", validate="one_to_one")
    keep = base["label20"].notna().to_numpy() & base["clean20"].fillna(False).to_numpy(bool)
    base = base[keep].reset_index(drop=True)
    if folds:
        base = base[base["fold"].isin(folds)].reset_index(drop=True)
    info = {"rows_40d_clean_in_test_windows": int(n40), "rows_dropped_not_20d_clean": int((~keep).sum()),
            "rows": int(len(base)), "signal_dates": int(base["date"].nunique()),
            "first": str(base["date"].min().date()), "last": str(base["date"].max().date()),
            "folds_restricted_to": folds}
    return base, info


def load_score(base: pd.DataFrame, scorer: str, preds: Path) -> tuple[np.ndarray, dict]:
    """ml/books/data.load_scores (one-to-one join, label check, every score finite) against the scorer's own label."""
    lab = SCORERS[scorer]["label"]
    D.PREDS = preds.parent
    name = preds.name[: -len(f"__{TASK}.parquet")]
    view = base[["date", "ticker"]].assign(label_beat_mkt_20d=base[lab].to_numpy(float))
    sc, meta = D.load_scores(view, [name])
    return sc[name], meta[name]


def _hash(*arrs) -> str:
    h = hashlib.sha256()
    for a in arrs:
        h.update(np.ascontiguousarray(a).tobytes())
    return h.hexdigest()[:16]


def fold_auc_mean(base: pd.DataFrame, score: np.ndarray) -> float:
    from sklearn.metrics import roc_auc_score
    y = base["label_beat_mkt_20d"].to_numpy(float)
    a = [roc_auc_score(y[i], score[i]) for _, i in base.groupby("fold").indices.items() if len(np.unique(y[i])) == 2]
    return float(np.mean(a))


def run_books(scorer: str, preds: Path, out_dir: Path, folds: list[str] | None) -> dict:
    var_sr = json.loads(BOOKS_JSON.read_text())["dsr_common"]["var_sr_daily_across_66_books"]
    base, binfo = book_base(folds)
    if folds and not (base["segment"] == "holdout").any():
        # smoke runs only: the engine's calendar needs a holdout segment; label the last fold present as one
        last = sorted(base["fold"].unique())[-1]
        base.loc[base["fold"] == last, "segment"] = "holdout"
        binfo["smoke_note"] = f"no holdout rows: fold {last} labelled holdout for the engine (smoke only)"
    score, smeta = load_score(base, scorer, preds)
    log(f"{scorer}: base {len(base):,} rows ({binfo['rows_dropped_not_20d_clean']} dropped: not 20-day clean), "
        f"{binfo['signal_dates']} signal dates; preds {smeta['source']}")
    raw = D.read_price_parquet()
    sessions, tick, O, adv20 = D.load_prices(base, raw)
    comp = D.cost_components(raw, sessions, tick, adv20)
    pos_of = {d: i for i, d in enumerate(sessions)}
    col_of = {t: j for j, t in enumerate(tick)}
    p = base["date"].map(pos_of).to_numpy()
    cidx = base["ticker"].map(col_of).to_numpy()
    fmax = D.forward_absret_max(comp["own"], sessions, tick, H + 1)[p, cidx]
    elig = p + 1 + H <= len(sessions) - 1
    keep = elig & (fmax <= D.SPLIT_MOVE_THRESHOLD)
    sub = base[keep]
    blocks, info = E.build_blocks_h(sub, sessions, tick, O, adv20, H)
    yr = base["y_raw_20d"].to_numpy(float)
    ok = np.concatenate([np.isfinite(b.path[H]) & np.isfinite(yr[b.rows]) for b in blocks])
    match = np.concatenate([np.abs(b.path[H] - (1.0 + yr[b.rows])) < 1e-6 for b in blocks])
    screen = {"rule": "P2 H_LONG screen: ticker's |ret_1d| <= 22% on grid sessions t+1..t+41 and the t+41 session exists "
                      "(applied on top of the dataset's 40-day clean mask)",
              "rows_in": int(len(base)), "rows_not_eligible_no_exit_session": int((~elig).sum()),
              "rows_removed_by_absret_screen": int((elig & ~keep).sum()),
              "of_which_absret_gt_22pct": int((elig & (fmax > D.SPLIT_MOVE_THRESHOLD)).sum()),
              "of_which_no_trade_in_grid_window": int((elig & ~np.isfinite(fmax)).sum()),
              "removal_note": "P2's rule drops a row whose ticker has no own return on grid sessions t+1..t+41 (max is "
                              "NaN): the ticker did not trade in the 41 sessions after the signal date (its dataset "
                              "label enters at a later row t+1, the gap the ml/data.py span rule does not see)", **info,
              "exit_mark_matches_40d_label_frac": float(match[ok].mean()),
              "note": "no label pin: the exit mark is the grid open of session t+41 (forward-filled); it differs from "
                      "the dataset label only where the ticker misses grid sessions"}
    log(f"{len(blocks)} blocks {info['first']}..{info['last']}; screen removed {screen['rows_removed_by_absret_screen']} "
        f"rows; exit mark = 40-day label on {100 * screen['exit_mark_matches_40d_label_frac']:.3f}% of rows")
    eng = E.BookEngine(blocks, sessions, len(tick), H, comp)
    month_of = np.array([b.month for b in blocks])
    ew_R = eng.bench["ew_universe"]["R"]
    direction = {mo: ("up" if ew_R[month_of == mo].mean() > 0 else "down") for mo in sorted(set(month_of))}
    dates = np.unique(base["date"].to_numpy())
    codes = np.searchsorted(dates, base["date"].to_numpy())
    atr, lt = base["atr_pct"].to_numpy(float), base["log_turnover"].to_numpy(float)
    sc = E.neutralise(score, NEUT, codes, atr, lt, None)
    expo = eng.cal.expo["combined"]
    year_of = np.array([b.date.year for b in blocks])
    books = {}
    for bk in BASKETS:
        key = f"{scorer}|{NEUT}|{bk}|H{H}"
        r = eng.run_members(E.members_simple(blocks, sc, bk), bk)
        s = C.summarize(key, r, eng, {"scorer": scorer, "neutralisation": NEUT, "basket": bk}, direction)
        s["dsr"] = {str(N_TRIALS): sb.dsr_block(r["_skill_daily"], expo, var_sr, N_TRIALS, key + " skill", sb.PPY)}
        s["score_corr_atr_pct"] = C.per_date_spearman(codes, sc, atr)
        s["score_corr_log_turnover"] = C.per_date_spearman(codes, sc, lt)
        v = r["_tranche"]["20bps"]["R"] - r["_bench_R"]
        s["by_calendar_year_per_tranche_net20_excess"] = {str(y): float(v[year_of == y].mean()) for y in sorted(set(year_of))}
        s["by_calendar_year_ann_net20_excess"] = {str(y): float(v[year_of == y].mean() * sb.PPY / H) for y in sorted(set(year_of))}
        s["years_positive"] = f"{sum(v[year_of == y].mean() > 0 for y in set(year_of))}/{len(set(year_of))}"
        books[key] = s
        c = s["segments"]["combined"]["20bps"]
        be = s["breakeven_flat_cost_bps_per_side"]
        log(f"{key}: excess {c['excess_ann_vs_ew']:+.4f}/yr IR {c['ir']:+.2f} [{c['ir_ci95'][0]:+.2f}, {c['ir_ci95'][1]:+.2f}] "
            f"months+ {s['months_positive']}/{s['n_months']} turnover {s['turnover_per_rebalance']:.2f} break-even "
            f"{'n/a' if be is None else f'{be:.0f} bps'} DSR {s['dsr'][str(N_TRIALS)]['dsr']:.3f}")
    yx = base["y_excess_20d"].to_numpy(float)
    ic = per_date_ic(codes, score, yx, len(dates))
    bench = {}
    for bn in ("ew_universe", "ew_liquid"):
        b = eng.bench[bn]
        x = eng.cal.seg_series(b["D"], "combined")
        st = sb.series_stats(x, expo, eng.cal.month_codes["combined"], eng.cal.draws["combined"], rf=sb.RF_ANNUAL)
        bench[bn] = {"ann_return_tranche": float(b["R"].mean() * sb.PPY / H), "ann_mean_daily": st["ann_mean_daily"],
                     "sharpe": st["sharpe"], "names_mean": float(b["size"].mean()), "turnover_per_rebalance": b["turnover"]}
    res = {
        "stream": "Q5", "scorer": scorer, "scorer_what": SCORERS[scorer]["what"], "preds": smeta,
        "generated_by": f"python3 -m ml.improve.h40 books --scorer {scorer}" + (f" --folds {' '.join(folds)}" if folds else ""),
        "H": H, "n_trials": N_TRIALS, "var_sr_daily": var_sr, "var_sr_source": rel(BOOKS_JSON),
        "dataset": rel(DATA_H40), "prices": rel(PRICES), "price_start": PRICE_START,
        "base_panel": binfo, "hold40_screen": screen,
        "block_set_hash": _hash(np.array([b.pos for b in blocks]), np.concatenate([b.rows for b in blocks])),
        "bench_R_hash": _hash(eng.bench["ew_universe"]["R"], eng.bench["ew_liquid"]["R"]),
        "benchmarks_H40": bench, "direction_by_month": direction,
        "n_signal_dates": len(blocks), "n_holdout_signal_dates": int(sum(b.segment == "holdout" for b in blocks)),
        "descriptive_on_40d_label": {
            "what": "the scorer's raw score against the 40-day label on the base panel (same label for both scorers)",
            "rank_ic_vs_40d_excess_mean": float(np.nanmean(ic)), "rank_ic_nw_t_lag40": nw_t(ic, 40),
            "fold_auc_vs_40d_label_mean": fold_auc_mean(base, score)},
        "books": books,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    C.wjson(out_dir / f"books_{scorer}.json", res)
    log(f"wrote {rel(out_dir / f'books_{scorer}.json')}")
    return res


# =========================================================================== pass mark
def paired(a: dict, b: dict, label: str) -> dict:
    """a minus b, both book summaries from the same block set: monthly mean net 20 bps tranche excess vs EW."""
    ma, mb = a["monthly_net_20bps"], b["monthly_net_20bps"]
    assert set(ma) == set(mb), "books on different signal months"
    months = sorted(ma)
    d = np.array([ma[m] - mb[m] for m in months], float)
    M = len(d)
    iid = np.random.default_rng(SEED).integers(0, M, size=(B_BOOT, M))
    ci_iid = C.boot_mean_ci(d, iid)
    cnt = _block_counts_within(M, BLOCK_MONTHS, B_BOOT, np.random.default_rng(SEED))
    m3 = cnt @ d / M
    ci_3 = ci(m3)
    cvm = np.array([m < "2026-08" for m in months])
    dcv = d[cvm]
    ci_cv = C.boot_mean_ci(dcv, np.random.default_rng(SEED).integers(0, len(dcv), size=(B_BOOT, len(dcv))))
    sd = float(d.std(ddof=1)) if M > 1 else float("nan")
    bea, beb = a["breakeven_flat_cost_bps_per_side"], b["breakeven_flat_cost_bps_per_side"]
    bea0, beb0 = (0.0 if bea is None else bea), (0.0 if beb is None else beb)
    scale = sb.PPY / H
    ca, cb = a["segments"]["combined"]["20bps"], b["segments"]["combined"]["20bps"]
    ci_pass = bool(ci_iid[0] > 0)
    be_pass = bool(bea0 > beb0)
    return {
        "pair": label, "book_a": a["key"], "book_b": b["key"],
        "metric": "per signal month: mean over the month's signal dates of (net 20 bps 40-session tranche return - EW "
                  "universe tranche return); difference a - b; same blocks and benchmark for both books",
        "n_months": M, "first_month": months[0] if months else None, "last_month": months[-1] if months else None,
        "mean_diff_per_tranche": float(d.mean()), "mean_diff_ann": float(d.mean() * scale),
        "ci95_months_resampled": ci_iid, "ci95_months_resampled_ann": [x * scale for x in ci_iid],
        "ci95_3month_blocks": ci_3, "ci95_3month_blocks_ann": [x * scale for x in ci_3],
        "p_gt0_months_resampled": float(np.mean(d[iid].mean(1) > 0)), "p_gt0_3month_blocks": float(np.mean(m3 > 0)),
        "months_a_ahead": f"{int((d > 0).sum())}/{M}", "months_tied": int((d == 0).sum()),
        "t_naive_months": float(d.mean() / (sd / math.sqrt(M))) if M > 1 and sd > 0 else None,
        "cv_months_only": {"n_months": int(cvm.sum()), "mean_diff_ann": float(dcv.mean() * scale),
                           "ci95_months_resampled_ann": [x * scale for x in ci_cv]},
        "excess_ann_20bps": {"a": ca["excess_ann_vs_ew"], "b": cb["excess_ann_vs_ew"]},
        "ir_20bps": {"a": ca["ir"], "b": cb["ir"], "a_ci95": ca["ir_ci95"], "b_ci95": cb["ir_ci95"]},
        "breakeven_flat_cost_bps_per_side": {"a": bea, "b": beb, "a_used": bea0, "b_used": beb0},
        "ci_excludes_zero_above": ci_pass, "ci_3month_blocks_excludes_zero_above": bool(ci_3[0] > 0),
        "breakeven_higher": be_pass,
        "PASS": bool(ci_pass and be_pass),
        "PASS_strict_both_cis": bool(ci_pass and ci_3[0] > 0 and be_pass),
    }


def _ab_model_summary() -> dict | None:
    p = OUT_ROOT / H40_TAG / f"control__{TASK}.json"
    if not p.exists():
        return None
    j = json.loads(p.read_text())
    return {"file": rel(p), "label": "40-session (stored as beat_mkt_20d)", "n_folds": len(j["folds"]),
            "cv_auc_mean": j["cv_auc_mean"], "cv_auc_std": j["cv_auc_std"], "min_fold_auc": j["min_fold_auc"],
            "pct_folds_ge_050": j["pct_folds_ge_050"], "holdout_auc": (j.get("holdout") or {}).get("auc"),
            "n_features": j["n_features"], "exit_date_purge_rows_removed": j["exit_date_purge"]["rows_removed_total"],
            "note": "AUC on the 40-day label; the control's 0.5455 is on the 20-day label: description only, not the pass mark"}


def _book_row(s: dict) -> dict:
    c, cn = s["segments"]["combined"]["20bps"], s["segments"]["combined"][E.NAME_KEY]
    nk = str(N_TRIALS) if str(N_TRIALS) in s["dsr"] else sorted(s["dsr"])[0]     # context books carry N = 241
    return {"excess_ann_vs_ew_20bps": c["excess_ann_vs_ew"], "ir_20bps": c["ir"], "ir_ci95": c["ir_ci95"],
            "excess_ann_10bps": s["segments"]["combined"]["10bps"]["excess_ann_vs_ew"],
            "excess_ann_40bps": s["segments"]["combined"]["40bps"]["excess_ann_vs_ew"],
            "excess_ann_gross": s["segments"]["combined"]["gross"]["excess_ann_vs_ew"],
            "excess_ann_name_level": cn["excess_ann_vs_ew"], "name_level_cost_bps_per_side": s["name_level_trade_weighted_cost_bps_per_side"],
            "months_positive": f"{s['months_positive']}/{s['n_months']}", "years_positive": s.get("years_positive"),
            "turnover_per_rebalance": s["turnover_per_rebalance"], "turnover_annualised": s["turnover_annualised"],
            "breakeven_flat_cost_bps_per_side": s["breakeven_flat_cost_bps_per_side"],
            "capacity_rs_crore": (s["capacity"] or {}).get("aum_cap_rs_crore_p10name_5pct_adv"),
            "dsr": s["dsr"][nk]["dsr"], "dsr_N": int(nk), "psr_vs_0": s["dsr"][nk]["psr_vs_0"],
            "holdout_excess_ann_20bps": s["segments"]["holdout"]["20bps"]["excess_ann_vs_ew"]}


def compare(out_dir: Path) -> dict:
    pa, pb = out_dir / "books_h40.json", out_dir / "books_control20.json"
    assert pb.exists(), f"{rel(pb)} missing: run books --scorer control20 first"
    bc = json.loads(pb.read_text())
    ctrl = bc["books"][f"control20|{PASS_BOOK}|H{H}"]
    selftest = paired(ctrl, ctrl, "control20 - control20 (self-test)")
    st_ok = bool(selftest["mean_diff_per_tranche"] == 0.0 and selftest["ci95_months_resampled"] == [0.0, 0.0]
                 and selftest["ci95_3month_blocks"] == [0.0, 0.0] and not selftest["PASS"])
    assert st_ok, "self-test failed: comparator vs itself must give exactly zero and FAIL"
    log(f"self-test (control vs itself): diff {selftest['mean_diff_per_tranche']}, CI {selftest['ci95_months_resampled']}, "
        f"PASS={selftest['PASS']} -> {'OK' if st_ok else 'BROKEN'}")
    ctx = None
    if CONTROL10Y_BOOKS.exists():
        k20 = json.loads(CONTROL10Y_BOOKS.read_text())["books"]
        ctx = {f"control|{NEUT}|{bk} (20-session hold, 20-day label)": _book_row(k20[f"control|{NEUT}|{bk}"])
               for bk in BASKETS if f"control|{NEUT}|{bk}" in k20}
    res = {
        "stream": "Q5 (ml/IMPROVEMENT_PLAN_2.md §2): the 40-day horizon",
        "generated_by": "python3 -m ml.improve.h40 compare", "definitions_and_deviations": rel(out_dir / "H40.md"),
        "trial_ledger": {"configurations": 1, "books": 4, "trials": 5, "phase_N": N_TRIALS},
        "dsr": {"N": N_TRIALS, "var_sr_daily": bc["var_sr_daily"], "source": bc["var_sr_source"]},
        "pass_mark_rule": ("the 40-day model's vol+size full-universe top-decile 40-session book beats the 20-day control's "
                           "with the paired monthly net-20-bps-excess difference's 95% CI (months resampled, B = 1000, "
                           "seed 108) entirely above zero, AND its flat break-even cost per side is higher (no positive "
                           "break-even = 0 bps); 3-month-block CI reported beside it, strict reading = both CIs"),
        "dataset": json.loads((out_dir / "build.json").read_text())["dataset"] if (out_dir / "build.json").exists() else None,
        "comparison_code_self_test": {**selftest, "ok": st_ok},
        "books": {"control20": {k: _book_row(v) for k, v in bc["books"].items()}},
        "books_meta": {"control20": {k: bc[k] for k in META_KEYS}},
        "context_20session_books_of_the_control": ctx,
        "model_40d": _ab_model_summary(),
    }
    if pa.exists():
        bh = json.loads(pa.read_text())
        assert bh["block_set_hash"] == bc["block_set_hash"] and bh["bench_R_hash"] == bc["bench_R_hash"], \
            "the two scorers' books are not on the same blocks / benchmark"
        res["books"]["h40"] = {k: _book_row(v) for k, v in bh["books"].items()}
        res["books_meta"]["h40"] = {k: bh[k] for k in META_KEYS}
        pm = paired(bh["books"][f"h40|{PASS_BOOK}|H{H}"], ctrl, "h40 - control20, vol+size top decile (PASS MARK)")
        liq = paired(bh["books"][f"h40|{NEUT}|liq_top_decile|H{H}"], bc["books"][f"control20|{NEUT}|liq_top_decile|H{H}"],
                     "h40 - control20, vol+size liquid top decile (descriptive)")
        res["pass_mark"] = pm
        res["liquid_books_descriptive"] = liq
        res["verdict"] = "PASS" if pm["PASS"] else "FAIL"
        res["status"] = "complete"
        log(f"PASS MARK: diff {pm['mean_diff_ann']:+.4f}/yr CI {[round(x, 4) for x in pm['ci95_months_resampled_ann']]} "
            f"(3-month blocks {[round(x, 4) for x in pm['ci95_3month_blocks_ann']]}); break-even "
            f"{pm['breakeven_flat_cost_bps_per_side']['a']} vs {pm['breakeven_flat_cost_bps_per_side']['b']} bps -> {res['verdict']}")
    else:
        res["status"] = "awaiting the 40-day model (books_h40.json): comparator books and self-test only"
        res["verdict"] = None
    C.wjson(out_dir / "h40.json", res)
    write_md(out_dir, res)
    log(f"wrote {rel(out_dir / 'h40.json')} and the results part of {rel(out_dir / 'H40.md')}")
    return res


# =========================================================================== Markdown (quotes h40.json)
def _p(x, d=1, sign=True):
    return "n/a" if x is None else (f"{100 * x:+.{d}f}%" if sign else f"{100 * x:.{d}f}%")


def _ci(c, d=2):
    return "n/a" if not c else f"[{c[0]:+.{d}f}, {c[1]:+.{d}f}]"


def _cip(c, d=2):
    return "n/a" if not c else f"[{100 * c[0]:+.{d}f}, {100 * c[1]:+.{d}f}] pp"


def write_md(out_dir: Path, res: dict) -> None:
    path = out_dir / "H40.md"
    head = path.read_text().split(MARKER)[0] if path.exists() else "# Q5: the 40-day horizon\n\n"
    L = [MARKER, "", "## 3. Results (quoted from `h40.json`)", "", f"Status: **{res['status']}**." +
         (f" Verdict: **{res['verdict']}**." if res.get("verdict") else ""), ""]
    ds = res.get("dataset")
    if ds:
        L += ["### Dataset", "",
              f"- Horizon-20 code path reproduces `ml/data_10y` exactly (labels, exit dates, `ret_1d`, splits): see `build.json`.",
              f"- {ds['labeled_clean_rows_40d']:,} clean 40-day labels of {ds['rows']:,} rows (clean share "
              f"{_p(ds['y_clean_share_40d'], 2, False)}, beat share {ds['label_balance_40d']:.4f}); last labelled session "
              f"{ds['last_labeled_date_40d']}; holdout {ds['holdout']['test_start']}..{ds['holdout']['test_end']} "
              f"(train_end {ds['holdout']['train_end']}).",
              f"- Clean masks: both {ds['clean_overlap']['both']:,}; 40-day only {ds['clean_overlap']['clean_40_not_20']:,}; "
              f"20-day only {ds['clean_overlap']['clean_20_not_40']:,}. Clean 40-day labels whose window skips a market session "
              f"(deviation 4): {ds['rows_40d_clean_with_a_missing_market_session_in_window']:,} "
              f"({_p(ds['share_40d_clean_with_a_missing_market_session_in_window'], 2, False)}).",
              f"- First fold trains on {ds['first_fold']['train_sessions']} sessions "
              f"({ds['first_fold']['train_labeled_clean_rows']:,} clean labelled rows).", ""]
    bm = res["books_meta"]["control20"]
    L += ["### Book panel", "",
          f"- Base: {bm['base_panel']['rows']:,} rows on {bm['base_panel']['signal_dates']} signal dates "
          f"({bm['base_panel']['first']}..{bm['base_panel']['last']}); {bm['base_panel']['rows_dropped_not_20d_clean']:,} "
          f"40-day-clean rows dropped as not 20-day clean (deviation 3).",
          f"- 40-session screen removed {bm['hold40_screen']['rows_removed_by_absret_screen']} rows "
          f"({bm['hold40_screen'].get('of_which_absret_gt_22pct')} for a move above 22%, "
          f"{bm['hold40_screen'].get('of_which_no_trade_in_grid_window')} because the ticker did not trade in grid sessions "
          f"t+1..t+41; deviation 5 expected none, the second cause was not foreseen and is P2's rule as written); "
          f"{bm['hold40_screen']['signal_dates']} blocks {bm['hold40_screen']['first']}..{bm['hold40_screen']['last']}; "
          f"grid exit mark equals the 40-day label on {100 * bm['hold40_screen']['exit_mark_matches_40d_label_frac']:.3f}% of rows.",
          f"- EW universe (H = 40): {_p(bm['benchmarks_H40']['ew_universe']['ann_return_tranche'])}/yr; EW liquid tercile "
          f"{_p(bm['benchmarks_H40']['ew_liquid']['ann_return_tranche'])}/yr.", ""]
    L += ["### Books (40-session hold, vol+size neutral; DSR at N = 261)", "",
          f"Annualised as mean tranche value x 252/40. The holdout column covers only {bm['n_holdout_signal_dates']} "
          f"signal dates ({bm['base_panel']['last']} is the last 40-day-labelled session) and is not informative on its own.", "",
          "| Book | Excess vs EW, 20 bps | IR [95% CI] | Gross | 40 bps | Name-level | Months beating EW | Years + | "
          "Turnover / rebalance | Break-even (bps/side) | Holdout excess | DSR |",
          "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for sc_, bks in res["books"].items():
        for k, b in bks.items():
            be = b["breakeven_flat_cost_bps_per_side"]
            L.append(f"| {k} | {_p(b['excess_ann_vs_ew_20bps'])} | {b['ir_20bps']:+.2f} {_ci(b['ir_ci95'])} | "
                     f"{_p(b['excess_ann_gross'])} | {_p(b['excess_ann_40bps'])} | {_p(b['excess_ann_name_level'])} | "
                     f"{b['months_positive']} | {b['years_positive']} | {100 * b['turnover_per_rebalance']:.0f}% | "
                     f"{'none' if be is None else f'{be:.0f}'} | {_p(b['holdout_excess_ann_20bps'])} | {b['dsr']:.3f} |")
    L.append("")
    if res.get("context_20session_books_of_the_control"):
        L += ["For reference, the control's own 20-session books (`ml/results/improve/ab/10y/books.json`, 20-day label, N = 241 there): " +
              "; ".join(f"{k}: {_p(v['excess_ann_vs_ew_20bps'])}, IR {v['ir_20bps']:+.2f}"
                        for k, v in res["context_20session_books_of_the_control"].items()) + ".", ""]
    for nm in ("control20", "h40"):
        if nm in res["books_meta"]:
            d = res["books_meta"][nm]["descriptive_on_40d_label"]
            L.append(f"- {nm} raw score against the 40-day label (descriptive): rank IC {d['rank_ic_vs_40d_excess_mean']:+.4f} "
                     f"(Newey-West t, lag 40: {d['rank_ic_nw_t_lag40']:.1f}); mean fold AUC {d['fold_auc_vs_40d_label_mean']:.4f}.")
    m = res.get("model_40d")
    if m:
        ho = "n/a" if m["holdout_auc"] is None else f"{m['holdout_auc']:.4f}"
        L.append(f"- 40-day model (harness, {m['n_folds']} folds): CV AUC {m['cv_auc_mean']:.4f} ± {m['cv_auc_std']:.4f}, "
                 f"worst fold {m['min_fold_auc']:.3f}, folds ≥ 0.50 {100 * m['pct_folds_ge_050']:.0f}%, holdout {ho}; "
                 f"{m['exit_date_purge_rows_removed']:,} training rows removed by the exit-date purge. {m['note']}.")
    L.append("")
    st = res["comparison_code_self_test"]
    L += ["### Pass mark", "",
          f"Self-test (control's book against itself): difference {st['mean_diff_per_tranche']}, month CI "
          f"{st['ci95_months_resampled']}, 3-month-block CI {st['ci95_3month_blocks']}, verdict "
          f"{'PASS' if st['PASS'] else 'FAIL'} (expected FAIL) -> {'OK' if st['ok'] else 'BROKEN'}.", ""]
    pm = res.get("pass_mark")
    if pm:
        be = pm["breakeven_flat_cost_bps_per_side"]
        bea = "none" if be["a"] is None else f"{be['a']:.0f} bps"
        beb = "none" if be["b"] is None else f"{be['b']:.0f} bps"
        L += ["| Reading | 40-day model | 20-day control | Difference / test | Holds? |", "|---|---:|---:|---|---|",
              f"| Net 20 bps excess vs EW, per year | {_p(pm['excess_ann_20bps']['a'])} | {_p(pm['excess_ann_20bps']['b'])} | "
              f"{100 * pm['mean_diff_ann']:+.2f} pp/yr over {pm['n_months']} months; 95% CI (months resampled) "
              f"{_cip(pm['ci95_months_resampled_ann'])}; 3-month blocks {_cip(pm['ci95_3month_blocks_ann'])}; model ahead in "
              f"{pm['months_a_ahead']} months | {'yes' if pm['ci_excludes_zero_above'] else 'no'} |",
              f"| Flat break-even cost per side | {bea} | {beb} | higher for the 40-day model? | "
              f"{'yes' if pm['breakeven_higher'] else 'no'} |", "",
              f"**Q5 verdict: {res['verdict']}** (strict reading with both CIs: {'PASS' if pm['PASS_strict_both_cis'] else 'FAIL'}). "
              f"CV months only: {100 * pm['cv_months_only']['mean_diff_ann']:+.2f} pp/yr, CI "
              f"{_cip(pm['cv_months_only']['ci95_months_resampled_ann'])}.", ""]
        lq = res["liquid_books_descriptive"]
        lb = lq["breakeven_flat_cost_bps_per_side"]
        lba = "none" if lb["a"] is None else f"{lb['a']:.0f}"
        lbb = "none" if lb["b"] is None else f"{lb['b']:.0f}"
        L += [f"Liquid books (descriptive, no pass mark): {100 * lq['mean_diff_ann']:+.2f} pp/yr, CI "
              f"{_cip(lq['ci95_months_resampled_ann'])} (3-month blocks {_cip(lq['ci95_3month_blocks_ann'])}); "
              f"break-even {lba} vs {lbb} bps per side.", ""]
    else:
        L += ["The 40-day model's books do not exist yet; the pass mark is scored by `python3 -m ml.improve.h40 compare` "
              "after the harness run and `books --scorer h40`.", ""]
    path.write_text(head + "\n".join(L) + "\n")


# =========================================================================== CLI
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("stage", choices=["build", "books", "compare"])
    ap.add_argument("--force", action="store_true", help="build: rebuild even when the dataset matches its manifest")
    ap.add_argument("--scorer", choices=list(SCORERS), default="control20")
    ap.add_argument("--preds", default=None, help="books: predictions parquet (default: the scorer's registered file)")
    ap.add_argument("--out", default=str(OUT), help="books/compare: output folder (smoke runs: a scratch folder)")
    ap.add_argument("--folds", nargs="+", default=None, help="books: restrict the base panel to these folds (smoke only)")
    a = ap.parse_args()
    if a.stage == "build":
        build(a.force)
    elif a.stage == "books":
        run_books(a.scorer, Path(a.preds) if a.preds else SCORERS[a.scorer]["preds"], Path(a.out), a.folds)
    else:
        compare(Path(a.out))


if __name__ == "__main__":
    main()

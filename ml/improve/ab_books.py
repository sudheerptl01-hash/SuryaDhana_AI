#!/usr/bin/env python3
"""Long-only books for every A/B configuration (ml/IMPROVEMENT_PLAN.md P3: "each also scored as a
volatility+size-neutral top-decile book"), built with the P2 book machinery (ml/books) on the dataset and
prices of the given tag.  Two neutralisations (none; vol+size) x two baskets (top decile; liquid-tercile
top decile), 20-session hold, costs 10/20/40 bps and the P2 name-level model, equal-weight universe
benchmark, month-block bootstrap IR intervals, PSR/DSR on the daily net 20 bps skill series.

Deflated Sharpe: N = the plan's current ledger (default 241) and V[SR] = the cross-trial variance measured by
P2 across its 66 books (ml/results/improve/books/books.json, dsr_common.var_sr_daily_across_66_books), so
every book in the phase is deflated against the same yardstick.

    python3 -m ml.improve.ab_books --tag v2 --data ml/data_5y_v2 \
        --prices ml/results/improve/cache/features_prices_export_v2.parquet

Phase-2 hooks (ml/improve/cpcv.py; all off by default, so the default run is unchanged): --preds-dir reads
<config>__beat_mkt_20d.parquet from another folder, --out-dir / --out-name write <out-name>.json / <out-name>.md
elsewhere, --folds-only scores the CV fold months only (a CPCV path has no holdout predictions).
"""
from __future__ import annotations

import os

os.environ["OMP_NUM_THREADS"] = "2"

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

import ml.strategy_backtest as sb
from ml.books import construct as C
from ml.books import data as D
from ml.books import engine as E
from ml.improve.ab import CONFIGS, OUT_ROOT, TASK, VARIANTS, _jd

ML_DIR = Path(__file__).resolve().parents[1]
BOOKS_JSON = ML_DIR / "results" / "improve" / "books" / "books.json"
N_DEFAULT = 241
NEUTS = ("none", "vol+size")
BASKETS = ("top_decile", "liq_top_decile")
T0 = time.time()
# --folds-only: a holdout window that matches no row (the CPCV paths never score the holdout)
NO_HOLDOUT = {"name": "holdout", "train_end": "2000-01-01", "test_start": "2100-01-01", "test_end": "2000-01-01"}


def log(msg: str) -> None:
    print(f"[ab_books +{time.time() - T0:5.0f}s] {msg}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="v2")
    ap.add_argument("--data", default=str(ML_DIR / "data_5y_v2"))
    ap.add_argument("--prices", default=str(ML_DIR / "results" / "improve" / "cache" / "features_prices_export_v2.parquet"))
    ap.add_argument("--price-start", default="2022-10-03")
    ap.add_argument("--configs", nargs="+", default=None)
    ap.add_argument("--n-trials", type=int, default=N_DEFAULT)
    ap.add_argument("--preds-dir", default=None, help="read the preds parquets from here instead of <tag>/preds")
    ap.add_argument("--out-dir", default=None, help="write the outputs here instead of the tag folder")
    ap.add_argument("--out-name", default=None, help="output stem: <out-name>.json / <out-name>.md "
                                                      "instead of books.json / BOOKS_AB.md")
    ap.add_argument("--folds-only", action="store_true",
                    help="CV fold months only, no holdout rows; the engine's second segment ('holdout') is then a "
                         "placeholder holding the last fold month, and only the 'combined' segment is a reading")
    a = ap.parse_args()
    out = OUT_ROOT / a.tag
    pdir = Path(a.preds_dir).resolve() if a.preds_dir else out / "preds"     # absolute: ml/books records it repo-relative
    dest = Path(a.out_dir) if a.out_dir else out
    D.DATA_5Y, D.PREDS, D.PRICES_PARQUET, D.PRICE_START = Path(a.data), pdir, Path(a.prices), a.price_start
    names = a.configs or [n for n in ["control"] + VARIANTS if (pdir / f"{n}__{TASK}.parquet").exists()]
    names = [n for n in names if (pdir / f"{n}__{TASK}.parquet").exists()]
    var_sr = json.loads(BOOKS_JSON.read_text())["dsr_common"]["var_sr_daily_across_66_books"]
    splits = D.load_splits()
    if a.folds_only:
        splits = {**splits, "holdout": dict(NO_HOLDOUT)}
    base = D.load_base(splits)
    if a.folds_only:
        last_fold = splits["folds"][-1]["name"]
        base["segment"] = np.where(base["fold"] == last_fold, "holdout", "cv")
    scores, smeta = D.load_scores(base, names)
    raw = D.read_price_parquet()
    sessions, tick, O, adv20 = D.load_prices(base, raw)
    blocks, check = sb.build_blocks(base, sessions, tick, O, adv20)
    log(f"{a.tag}: base {len(base):,} rows, {len(blocks)} signal dates, exit-mark/label match "
        f"{check['exit_mark_matches_label_frac']:.5f}; configs {names}")
    comp = D.cost_components(raw, sessions, tick, adv20)
    eng = E.BookEngine(blocks, sessions, len(tick), sb.HORIZON, comp)
    month_of = np.array([b.month for b in blocks])
    ew_R = eng.bench["ew_universe"]["R"]
    direction = {mo: ("up" if ew_R[month_of == mo].mean() > 0 else "down") for mo in sorted(set(month_of))}
    dates = np.unique(base["date"].to_numpy())
    codes = np.searchsorted(dates, base["date"].to_numpy())
    atr, lt = base["atr_pct"].to_numpy(float), base["log_turnover"].to_numpy(float)
    expo = eng.cal.expo["combined"]
    books = {}
    for n in names:
        for nt in NEUTS:
            sc = E.neutralise(scores[n], nt, codes, atr, lt, None)
            for bk in BASKETS:
                key = f"{n}|{nt}|{bk}"
                r = eng.run_members(E.members_simple(blocks, sc, bk), bk)
                s = C.summarize(key, r, eng, {"scorer": n, "neutralisation": nt, "basket": bk}, direction)
                s["dsr"] = {str(a.n_trials): sb.dsr_block(r["_skill_daily"], expo, var_sr, a.n_trials, key + " skill", sb.PPY)}
                s["score_corr_atr_pct"] = C.per_date_spearman(codes, sc, atr)
                books[key] = s
                c = s["segments"]["combined"]["20bps"]
                log(f"{key}: excess {c['excess_ann_vs_ew']:+.3f} IR {c['ir']:+.2f} {[round(x, 2) for x in c['ir_ci95']]} "
                    f"months+ {s['months_positive']}/{s['n_months']} turnover {s['turnover_per_rebalance']:.2f} "
                    f"DSR {s['dsr'][str(a.n_trials)]['dsr']:.3f}")
    res = {"tag": a.tag, "data": a.data, "prices": a.prices, "n_trials": a.n_trials, "var_sr_source": str(BOOKS_JSON),
           "var_sr_daily": var_sr, "n_signal_dates": len(blocks), "path_check": check, "scores_meta": smeta,
           "benchmark_ew_universe_ann": None, "books": books}
    if a.folds_only:
        res["folds_only"] = {"signal_months": int(base["month"].nunique()), "placeholder_segment_holdout": last_fold,
                             "note": "no holdout rows; read segments.combined only (the engine needs a non-empty "
                                     "second segment, so 'holdout' here holds the last fold month)",
                             "preds_dir": str(pdir)}
    b = eng.bench["ew_universe"]
    x = eng.cal.seg_series(b["D"], "combined")
    st = sb.series_stats(x, expo, eng.cal.month_codes["combined"], eng.cal.draws["combined"], rf=sb.RF_ANNUAL)
    res["benchmark_ew_universe_ann"] = {"ann_mean_daily": st["ann_mean_daily"], "sharpe": st["sharpe"]}
    dest.mkdir(parents=True, exist_ok=True)
    (dest / (f"{a.out_name}.json" if a.out_name else "books.json")).write_text(json.dumps(res, indent=1, default=_jd))
    L = [f"# A/B configurations as long-only books ({a.tag})", "",
         f"P2 construction (ml/books) on {len(blocks)} signal dates; equal-weight universe benchmark; 20 bps per side headline; "
         f"DSR at N = {a.n_trials} with V[SR] = {var_sr:.3g} (P2's 66-book cross-trial variance).", "",
         "| Configuration | Neutralisation | Basket | Excess vs EW (20 bps) | IR [95% CI] | Months beating EW | Turnover / rebalance | "
         "Capacity (₹ cr) | Name-level cost excess | DSR |", "|---|---|---|---:|---|---:|---:|---:|---:|---:|"]
    for k, s in books.items():
        c, cn = s["segments"]["combined"]["20bps"], s["segments"]["combined"][E.NAME_KEY]
        cap = s["capacity"]["aum_cap_rs_crore_p10name_5pct_adv"] if s["capacity"] else float("nan")
        L.append(f"| {s['scorer']} | {s['neutralisation']} | {s['basket']} | {100 * c['excess_ann_vs_ew']:+.1f}% | "
                 f"{c['ir']:+.2f} [{c['ir_ci95'][0]:+.2f}, {c['ir_ci95'][1]:+.2f}] | {s['months_positive']}/{s['n_months']} | "
                 f"{100 * s['turnover_per_rebalance']:.0f}% | {cap:,.0f} | {100 * cn['excess_ann_vs_ew']:+.1f}% | "
                 f"{s['dsr'][str(a.n_trials)]['dsr']:.3f} |")
    (dest / (f"{a.out_name}.md" if a.out_name else "BOOKS_AB.md")).write_text("\n".join(L) + "\n")
    log("written")


if __name__ == "__main__":
    main()

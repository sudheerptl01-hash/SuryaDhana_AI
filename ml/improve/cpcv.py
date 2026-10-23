#!/usr/bin/env python3
"""Combinatorial purged cross-validation of the frozen construction (ml/IMPROVEMENT_PLAN_2.md Q2; 1 trial of N = 261).

One walk-forward path is one draw.  CPCV (Lopez de Prado, AFML ch. 12) re-scores every fold month several times, each
time with a model trained on a different set of the other months, and assembles complete backtest paths.

Design (fixed in the plan and the stream brief)
  groups    the 103 fold months of ml/data_10y/splits.json, in order, cut into N = 8 contiguous groups of
            13, 13, 13, 13, 13, 13, 13 and 12 months
  splits    every pair of groups as the test set: C(8, 2) = 28 splits, in lexicographic order of the pair
  test      the clean labelled rows of the two groups' fold test windows
  train     every clean labelled row of ml/data_10y outside the two test groups and outside the holdout window, after
            (a) purge: drop rows whose label span [date, exit_date] intersects either test group's span
                [first test date, last test date];
            (b) embargo: drop rows dated within 22 sessions after the end of each test group;
            (c) holdout: rows dated in the holdout window are never trainable, and rows whose label exit date falls on
                or after the holdout's first session are dropped too, so no training label sees a holdout price
                (the walk-forward's own rule for the holdout fold; see CPCV.md, interpretations).
            Rows of the 2017-10..2017-12 warm-up are trainable.  Training rows after a test group are used by design:
            CPCV measures path dependence, not forward performance.
  model     the control: ml/scale5y.make_model("all51") (the champion LightGBM), 52 features, raw preprocessing,
            seed 108, exactly as ml/improve/ab.py's control fold job
  paths     each group is tested in 7 splits; path j (1..7) takes, for every group, the group's j-th test occurrence in
            split order (the standard CPCV path assignment): 7 complete 103-month paths
  readings  per path: fold-month AUCs, per-date rank IC; books with the P2 construction (ml/improve/ab_books with
            --folds-only): vol+size-neutral full-universe top decile and vol+size-neutral liquid-tercile top decile,
            net 20 bps vs the equal-weight universe, IR with its month-block 95% CI, DSR at N = 261.  The construction
            is ROBUST across paths if the full-universe book has positive net excess in >= 6 of 7 paths; the liquid
            book is read the same way.  The walk-forward control's own predictions on the same 103 months are scored
            through the same hook as the reference (wf_control).

Stages (each resume-safe; outputs under ml/results/improve2/cpcv/)
  check   the design's invariants asserted on all 28 splits' row masks, no fitting -> smoke/invariants.json
  smoke   one split on a 20% sample of its training rows (seed 108): timing, memory and the full-run estimate
  fit     the 28 splits -> cache/splits/<split>.parquet + .json
  paths   preds/path<j>__beat_mkt_20d.parquet (j = 1..7) and preds/wf_control__beat_mkt_20d.parquet; AUC / IC -> paths.json
  books   ml/improve/ab_books on wf_control + path1..path7 -> books_paths.json, books_paths.md
  report  readings and verdicts -> cpcv.json, CPCV.md

    python3 -m ml.improve.cpcv check
    python3 -m ml.improve.cpcv smoke --n-jobs 1
    python3 -m ml.improve.cpcv fit --n-jobs 2
    python3 -m ml.improve.cpcv paths
    python3 -m ml.improve.cpcv books
    python3 -m ml.improve.cpcv report

Seed 108; OMP_NUM_THREADS=2; at most two worker processes (shared 4-core box).
"""
from __future__ import annotations

import os

os.environ["OMP_NUM_THREADS"] = "2"
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
os.environ["OMP_WAIT_POLICY"] = "PASSIVE"

import argparse
import itertools
import json
import multiprocessing as mp
import resource
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

import ml.improve.ab as ab
import ml.scale5y as s5
from ml.evaluation import Preprocessor, compute_metrics
from ml.scale5y_report import nw_t, per_date_ic

ML_DIR = Path(__file__).resolve().parents[1]
REPO = ML_DIR.parent
DATA = ML_DIR / "data_10y"
OUT = ML_DIR / "results" / "improve2" / "cpcv"
CACHE = OUT / "cache" / "splits"
PREDS = OUT / "preds"
WF_PREDS = ab.OUT_ROOT / "10y_p2" / "preds" / f"control__{ab.TASK}.parquet"
PRICES = ML_DIR / "results" / "improve" / "cache" / "features_prices_export_10y.parquet"
PRICE_START = "2017-10-02"
TASK, LABEL, FWD, CLEAN = ab.TASK, ab.LABEL, ab.FWD, ab.CLEAN
SEED = 108
N_GROUPS = 8
K_TEST = 2
GROUP_SIZES = (13, 13, 13, 13, 13, 13, 13, 12)
EMBARGO = 22
N_THREADS = 2
N_TRIALS = 261
ROBUST_MIN = 6
SMOKE_FRAC = 0.20
BOOKS = {"full": "vol+size|top_decile", "liquid": "vol+size|liq_top_decile"}
REF = "wf_control"

T0 = time.time()
_DF: pd.DataFrame | None = None          # set before the pool is forked
_FEATS: list[str] | None = None
_S: dict | None = None                   # row-level arrays shared by the forked workers


def log(msg: str) -> None:
    print(f"[cpcv +{time.time() - T0:6.0f}s] {msg}", flush=True)


wjson = ab.wjson


# ----------------------------------------------------------------------------- design
def make_groups(splits: dict) -> list[list[dict]]:
    folds = splits["folds"]
    assert len(folds) == sum(GROUP_SIZES) == 103, len(folds)
    out, i = [], 0
    for n in GROUP_SIZES:
        out.append(folds[i:i + n])
        i += n
    return out


SPLITS = list(itertools.combinations(range(N_GROUPS), K_TEST))          # 28, lexicographic


def split_name(s: tuple[int, int]) -> str:
    return f"s{SPLITS.index(s):02d}_g{s[0]}g{s[1]}"


def path_assignment() -> dict[int, list[tuple[int, int]]]:
    """path j (0-based) -> for each group g, the split that tests g for the (j+1)-th time in split order."""
    occ = {g: [s for s in SPLITS if g in s] for g in range(N_GROUPS)}
    n_paths = len(occ[0])
    assert all(len(v) == n_paths for v in occ.values()) and n_paths == K_TEST * len(SPLITS) // N_GROUPS == 7
    return {j: [occ[g][j] for g in range(N_GROUPS)] for j in range(n_paths)}


def load() -> dict:
    """Frame (ab.load_frame on ml/data_10y) and the row-level arrays every split needs."""
    global _DF, _FEATS, _S
    df, feats, splits = ab.load_frame(DATA, None, None, False)
    _DF, _FEATS = df, feats
    dd = df["date"].to_numpy(dtype="datetime64[ns]")
    sess = np.unique(dd)
    lab = df[LABEL].notna().to_numpy() & df[CLEAN].to_numpy().astype(bool)
    ex = df["exit_date"].to_numpy(dtype="datetime64[ns]")
    assert not np.isnat(ex[lab]).any(), "labelled rows without an exit date"
    groups = make_groups(splits)
    grp = np.full(len(df), -1, dtype=np.int8)
    month = np.full(len(df), "", dtype=object)
    for g, fl in enumerate(groups):
        for f in fl:
            m = (dd >= np.datetime64(f["test_start"])) & (dd <= np.datetime64(f["test_end"]))
            assert (grp[m] == -1).all()
            grp[m], month[m] = g, f["name"]
    ho = splits["holdout"]
    ho0 = np.datetime64(pd.Timestamp(ho["test_start"]))
    in_ho = (dd >= ho0) & (dd <= np.datetime64(pd.Timestamp(ho["test_end"])))
    assert (grp[in_ho] == -1).all()
    span = {}
    for g in range(N_GROUPS):
        d = dd[(grp == g) & lab]
        g0, g1 = d.min(), d.max()
        p1 = int(np.searchsorted(sess, g1))
        emb_end = sess[min(p1 + EMBARGO, len(sess) - 1)]
        span[g] = {"months": [f["name"] for f in groups[g]], "first_test_date": g0, "last_test_date": g1,
                   "embargo_last_date": emb_end, "n_test_rows": int(((grp == g) & lab).sum())}
    _S = {"dd": dd, "lab": lab, "ex": ex, "grp": grp, "month": month, "ho0": ho0, "in_ho": in_ho, "span": span,
          "sess": sess}
    log(f"frame: {len(df):,} rows, {len(sess)} sessions, {len(feats)} features, {int(lab.sum()):,} clean labelled; "
        f"groups {[len(s['months']) for s in span.values()]}")
    return splits


def masks(s: tuple[int, int]) -> tuple[np.ndarray, np.ndarray, dict]:
    S = _S
    dd, lab, ex, grp = S["dd"], S["lab"], S["ex"], S["grp"]
    test = lab & np.isin(grp, s)
    base = lab & ~np.isin(grp, s) & (dd < S["ho0"])
    cnt = {"clean_labelled_outside_test_and_holdout": int(base.sum())}
    drop = np.zeros(len(dd), bool)
    for g in s:
        sp = S["span"][g]
        purge = base & (dd <= sp["last_test_date"]) & (ex >= sp["first_test_date"])
        emb = base & (dd > sp["last_test_date"]) & (dd <= sp["embargo_last_date"])
        cnt[f"purged_overlap_g{g}"] = int((purge & ~drop).sum())
        drop |= purge
        cnt[f"embargoed_after_g{g}"] = int((emb & ~drop).sum())
        drop |= emb
    hop = base & ~drop & (ex >= S["ho0"])
    cnt["purged_exit_in_or_after_holdout"] = int(hop.sum())
    train = base & ~drop & ~hop
    cnt["n_train"] = int(train.sum())
    cnt["n_test"] = int(test.sum())
    cnt["train_sessions"] = int(np.unique(dd[train]).size)
    return train, test, cnt


# ----------------------------------------------------------------------------- one split
def _split_job(args) -> dict:
    s, frac, tag = args
    name = split_name(s)
    ck = (CACHE if tag is None else OUT / "cache" / "smoke") / f"{name}.json"
    pk = ck.with_suffix(".parquet")
    if tag is None and ck.exists() and pk.exists():
        return json.loads(ck.read_text())
    t0 = time.time()
    train, test, cnt = masks(s)
    idx = np.flatnonzero(train)
    if frac < 1.0:
        rng = np.random.default_rng(SEED)
        idx = idx[rng.random(idx.size) < frac]
    cols = ["date", "ticker"] + _FEATS + [LABEL, FWD]
    ci = [_DF.columns.get_loc(c) for c in cols]
    tr = _DF.iloc[idx, ci]                                  # only the columns the fit needs (memory)
    te = _DF.iloc[np.flatnonzero(test), ci]
    t_rows = time.time()
    prep = Preprocessor("raw").fit(tr[_FEATS])
    Xtr = prep.transform(tr[_FEATS])
    ytr = tr[LABEL].to_numpy(np.float32)
    t_prep = time.time()
    est = s5.make_model("all51", N_THREADS)
    est.fit(Xtr, ytr)
    t_fit = time.time()
    score = est.predict_proba(prep.transform(te[_FEATS]))[:, 1]
    yte = te[LABEL].to_numpy(np.float32)
    t_pred = time.time()
    g_of = _S["grp"][test]
    met = {"split": name, "test_groups": list(s), "sample_frac": frac, **cnt, "n_train_used": int(len(tr)),
           "auc_pooled": float(roc_auc_score(yte, score)),
           "auc_by_group": {str(g): float(roc_auc_score(yte[g_of == g], score[g_of == g])) for g in s},
           "seconds": {"rows": round(t_rows - t0, 1), "preprocess": round(t_prep - t_rows, 1),
                       "fit": round(t_fit - t_prep, 1), "predict": round(t_pred - t_fit, 1),
                       "total": round(t_pred - t0, 1)},
           "worker_maxrss_gb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6, 2)}
    preds = te[["date", "ticker"]].copy()
    preds["score"], preds["y"], preds["fwd"] = score, yte, te[FWD].to_numpy()
    preds["fold"], preds["group"] = _S["month"][test], g_of
    ck.parent.mkdir(parents=True, exist_ok=True)
    preds.to_parquet(pk, index=False)
    wjson(ck, met)
    log(f"{name}{'' if tag is None else ' [' + tag + ']'}: auc={met['auc_pooled']:.4f} groups {met['auc_by_group']} "
        f"n_train={len(tr):,} ({met['seconds']['total']}s, fit {met['seconds']['fit']}s, rss {met['worker_maxrss_gb']} GB)")
    return met


# ----------------------------------------------------------------------------- stages
def smoke(a) -> None:
    splits = load()
    sizes = {split_name(s): masks(s)[2] for s in SPLITS}
    big = max(SPLITS, key=lambda s: sizes[split_name(s)]["n_train"])
    with mp.get_context("fork").Pool(1) as pool:            # forked worker, as in the full run
        met = pool.map(_split_job, [(big, SMOKE_FRAC, "smoke")])[0]
    n_full = [v["n_train"] for v in sizes.values()]
    wf = json.loads((ab.OUT_ROOT / "10y_p2" / f"control__{TASK}.json").read_text())
    wf_pts = [(f["n_train"], f["train_seconds"]) for f in wf["folds"][-24:]]
    wf_rows, wf_sec = float(np.mean([p[0] for p in wf_pts])), float(np.mean([p[1] for p in wf_pts]))
    # fit + preprocess time is close to linear in rows for histogram GBDT: line through the smoke point and the
    # walk-forward control's last 24 folds (same model, same box, 2 workers); predict time scales with test rows
    sm_rows, sm_sec = met["n_train_used"], met["seconds"]["preprocess"] + met["seconds"]["fit"]
    slope = (wf_sec - sm_sec) / (wf_rows - sm_rows) if wf_rows != sm_rows else sm_sec / sm_rows
    icpt = sm_sec - slope * sm_rows
    per_split = [icpt + slope * n + met["seconds"]["rows"] + met["seconds"]["predict"] * sizes[k]["n_test"] / met["n_test"]
                 for k, n in zip(sizes, n_full)]
    lin5 = [5.0 * sm_sec * n / max(sizes[split_name(big)]["n_train"], 1) for n in n_full]
    est = {"per_split_seconds_line": [round(x) for x in per_split],
           "fit_full_minutes_at_2_workers_line": round(sum(per_split) / 2 / 60, 1),
           "fit_full_minutes_at_2_workers_5x_smoke": round((sum(lin5) + len(n_full) * (met["seconds"]["rows"] + met["seconds"]["predict"])) / 2 / 60, 1),
           "basis": {"smoke_rows": sm_rows, "smoke_preprocess_fit_seconds": sm_sec,
                     "walk_forward_rows_mean_last24": round(wf_rows), "walk_forward_train_seconds_mean_last24": round(wf_sec, 1)},
           "note": "the walk-forward train_seconds were measured with two workers on this box; the smoke ran one worker"}
    out = {"split": split_name(big), "test_groups": list(big), "sample_frac": SMOKE_FRAC, "metrics": met,
           "train_rows_by_split": {k: v for k, v in sizes.items()},
           "n_train_range": [int(min(n_full)), int(max(n_full))], "n_train_mean": float(np.mean(n_full)),
           "estimate": est}
    wjson(OUT / "smoke" / "smoke.json", out)
    log(f"smoke: {split_name(big)} at {SMOKE_FRAC:.0%}: {met['seconds']}; full splits {min(n_full):,}..{max(n_full):,} "
        f"train rows; estimate {est['fit_full_minutes_at_2_workers_line']} min (line) / "
        f"{est['fit_full_minutes_at_2_workers_5x_smoke']} min (5x smoke) for 28 fits at 2 workers")


def check(a) -> None:
    """Design invariants on every split's row masks (no fitting) -> smoke/invariants.json.  Asserts, then records."""
    splits = load()
    S = _S
    dd, lab, ex, grp, sess = S["dd"], S["lab"], S["ex"], S["grp"], S["sess"]
    wf = pd.read_parquet(WF_PREDS, columns=["fold"])
    wf_rows = wf[wf["fold"] != "holdout"]["fold"].value_counts().to_dict()
    month = S["month"]
    out = {}
    for s in SPLITS:
        train, test, cnt = masks(s)
        r = {"n_train": int(train.sum()), "n_test": int(test.sum())}
        assert not (train & test).any()
        assert lab[train].all() and lab[test].all()
        for g in s:
            sp = S["span"][g]
            g0, g1, e1 = sp["first_test_date"], sp["last_test_date"], sp["embargo_last_date"]
            assert not (train & (dd >= g0) & (dd <= g1)).any(), (s, g, "train row inside a test span")
            assert not (train & (dd <= g1) & (ex >= g0)).any(), (s, g, "train label overlaps a test span")
            assert not (train & (dd > g1) & (dd <= e1)).any(), (s, g, "train row inside the embargo")
            n_emb = int(((sess > g1) & (sess <= e1)).sum())
            r[f"g{g}_embargo_sessions"] = n_emb
            assert n_emb == EMBARGO or e1 == sess[-1], (s, g, n_emb)
            nxt = sess[sess > e1]
            r[f"g{g}_first_trainable_after"] = str(pd.Timestamp(nxt[0]).date()) if nxt.size else None
        assert not (train & (dd >= S["ho0"])).any() and not (train & (ex >= S["ho0"])).any()
        tm = pd.Series(month[test]).value_counts().to_dict()
        assert tm == {m: wf_rows[m] for m in tm} and set(tm) == {f["name"] for g in s for f in make_groups(splits)[g]}, s
        r["test_rows_equal_walk_forward_rows"] = True
        r["n_train_warmup_before_2018"] = int((train & (dd < np.datetime64("2018-01-01"))).sum())
        r["n_train_after_a_test_group"] = int((train & (dd > S["span"][min(s)]["last_test_date"])).sum())
        out[split_name(s)] = r
    assign = path_assignment()
    used = [(split_name(sp), g) for j, v in assign.items() for g, sp in enumerate(v)]
    assert len(used) == len(set(used)) == K_TEST * len(SPLITS)
    assert all(g in sp for v in assign.values() for g, sp in enumerate(v))
    res = {"checks": ["train and test disjoint; every row clean and labelled",
                      "no training row dated inside a test group's [first, last] test date",
                      "no training row whose [date, exit_date] intersects a test group's span (purge)",
                      f"no training row dated in the {EMBARGO} sessions after a test group (embargo; fewer only at "
                      "the end of the calendar)",
                      "no training row dated in the holdout window or with its label exit on or after the holdout start",
                      "test rows per month equal the walk-forward control's CV rows for that month",
                      "paths: every (split, group) test occurrence used by exactly one path; each path holds every "
                      "group once"],
           "all_passed": True, "n_splits": len(SPLITS), "splits": out,
           "path_assignment": {f"path{j + 1}": {f"g{g}": split_name(sp) for g, sp in enumerate(v)}
                               for j, v in assign.items()}}
    wjson(OUT / "smoke" / "invariants.json", res)
    write_md(json.loads((OUT / "cpcv.json").read_text()) if (OUT / "cpcv.json").exists() else None)
    log(f"check: all invariants hold on {len(SPLITS)} splits; train rows {min(v['n_train'] for v in out.values()):,}.."
        f"{max(v['n_train'] for v in out.values()):,}")


def fit(a) -> None:
    load()
    jobs = [(s, 1.0, None) for s in SPLITS]
    todo = [j for j in jobs if not (CACHE / f"{split_name(j[0])}.json").exists()]
    log(f"{len(jobs)} splits, {len(jobs) - len(todo)} cached, {len(todo)} to fit on {a.n_jobs} workers")
    if todo:
        with mp.get_context("fork").Pool(a.n_jobs) as pool:
            for _ in pool.imap_unordered(_split_job, todo, chunksize=1):
                pass
    log("FIT DONE")


def _month_aucs(p: pd.DataFrame) -> dict:
    return {m: float(roc_auc_score(g["y"].to_numpy(), g["score"].to_numpy())) for m, g in p.groupby("fold", sort=True)}


def _ic(p: pd.DataFrame) -> dict:
    dts = p["date"].to_numpy(dtype="datetime64[ns]")
    dates = np.unique(dts)
    codes = np.searchsorted(dates, dts)
    ic = per_date_ic(codes, p["score"].to_numpy(float), p["fwd"].to_numpy(float), len(dates))
    mon = pd.Series(ic).groupby(pd.DatetimeIndex(dates).strftime("%Y-%m")).mean()
    return {"rank_ic_mean": float(np.nanmean(ic)), "rank_ic_nw_t": nw_t(ic),
            "rank_ic_months_positive": f"{int((mon > 0).sum())}/{len(mon)}", "n_dates": int(len(dates))}


def _path_metrics(p: pd.DataFrame) -> dict:
    fa = _month_aucs(p)
    v = np.array(list(fa.values()))
    return {"n_rows": int(len(p)), "n_months": len(fa), "cv_auc_mean": float(v.mean()), "cv_auc_std": float(v.std()),
            "min_fold_auc": float(v.min()), "pct_folds_ge_050": float(np.mean(v >= 0.5)), **_ic(p), "fold_aucs": fa}


def paths(a) -> None:
    splits = json.loads((DATA / "splits.json").read_text())
    groups = make_groups(splits)
    sp = {split_name(s): pd.read_parquet(CACHE / f"{split_name(s)}.parquet") for s in SPLITS}
    meta = {split_name(s): json.loads((CACHE / f"{split_name(s)}.json").read_text()) for s in SPLITS}
    assert all(m["sample_frac"] == 1.0 for m in meta.values())
    PREDS.mkdir(parents=True, exist_ok=True)
    wf = pd.read_parquet(WF_PREDS)
    wf = wf[wf["fold"] != "holdout"].sort_values(["date", "ticker"]).reset_index(drop=True)
    wf["date"] = pd.to_datetime(wf["date"])
    wf[["date", "ticker", "score", "y", "fwd", "fold"]].to_parquet(PREDS / f"{REF}__{TASK}.parquet", index=False)
    key_wf = wf[["date", "ticker"]]
    assign = path_assignment()
    out = {"assignment": {f"path{j + 1}": {f"g{g}": split_name(s) for g, s in enumerate(v)} for j, v in assign.items()},
           "paths": {}, "reference": {REF: _path_metrics(wf)}}
    for j, v in assign.items():
        parts = []
        for g, s in enumerate(v):
            q = sp[split_name(s)]
            parts.append(q[q["group"] == g])
        p = pd.concat(parts, ignore_index=True)
        p["date"] = pd.to_datetime(p["date"])
        p = p.sort_values(["date", "ticker"]).reset_index(drop=True)
        assert len(p) == len(wf) and (p[["date", "ticker"]].to_numpy() == key_wf.to_numpy()).all(), \
            f"path{j + 1}: rows differ from the walk-forward CV rows"
        assert np.array_equal(p["y"].to_numpy(float), wf["y"].to_numpy(float)), f"path{j + 1}: label mismatch"
        p[["date", "ticker", "score", "y", "fwd", "fold"]].to_parquet(PREDS / f"path{j + 1}__{TASK}.parquet", index=False)
        pm = _path_metrics(p)
        pm["score_rank_corr_with_wf_per_date"] = float(
            pd.DataFrame({"d": p["date"], "a": p["score"], "b": wf["score"]}).groupby("d")
            .apply(lambda x: x["a"].rank().corr(x["b"].rank())).mean())
        out["paths"][f"path{j + 1}"] = pm
        log(f"path{j + 1}: cv_auc {pm['cv_auc_mean']:.4f} min {pm['min_fold_auc']:.3f} ic {pm['rank_ic_mean']:+.4f} "
            f"(t {pm['rank_ic_nw_t']:.1f}); rank corr with walk-forward {pm['score_rank_corr_with_wf_per_date']:.3f}")
    out["splits"] = meta
    out["groups"] = {f"g{g}": [f["name"] for f in fl] for g, fl in enumerate(groups)}
    wjson(OUT / "paths.json", out)
    log("paths written")


def rel(p: Path) -> str:
    return str(p.relative_to(REPO)) if p.is_relative_to(REPO) else str(p)


def books(a) -> None:
    cmd = [sys.executable, "-m", "ml.improve.ab_books", "--tag", "cpcv", "--data", rel(DATA),
           "--prices", rel(PRICES), "--price-start", PRICE_START,
           "--preds-dir", rel(PREDS), "--out-dir", rel(OUT),
           "--out-name", "books_paths", "--folds-only", "--n-trials", str(N_TRIALS),
           "--configs", REF] + [f"path{j}" for j in range(1, 8)]
    log("running " + " ".join(cmd[1:]))
    subprocess.run(cmd, cwd=REPO, check=True)


def report(a) -> None:
    pj = json.loads((OUT / "paths.json").read_text())
    bj = json.loads((OUT / "books_paths.json").read_text())
    assert bj.get("folds_only"), "books_paths.json must come from ab_books --folds-only"
    names = [f"path{j}" for j in range(1, 8)]

    def bk(n, b):
        s = bj["books"][f"{n}|{b}"]
        c = s["segments"]["combined"]["20bps"]
        return {"excess_ann_vs_ew_20bps": c["excess_ann_vs_ew"], "ir": c["ir"], "ir_ci95": c["ir_ci95"],
                "p_ir_gt0": c["p_ir_gt0"], "months_positive": f"{s['months_positive']}/{s['n_months']}",
                "turnover_per_rebalance": s["turnover_per_rebalance"],
                "name_level_excess_ann_vs_ew": s["segments"]["combined"]["name_level"]["excess_ann_vs_ew"],
                "dsr": s["dsr"][str(bj["n_trials"])]["dsr"], "by_year_per_tranche": s["by_year_per_tranche"]}

    readings = {}
    for lab_, b in BOOKS.items():
        rows = {n: bk(n, b) for n in names}
        npos = sum(r["excess_ann_vs_ew_20bps"] > 0 for r in rows.values())
        ex = np.array([r["excess_ann_vs_ew_20bps"] for r in rows.values()])
        ir = np.array([r["ir"] for r in rows.values()])
        readings[lab_] = {"book": b, "paths": rows, "reference_walk_forward_same_months": bk(REF, b),
                          "n_paths_positive_net_excess": int(npos), "n_paths": len(names),
                          "share_paths_positive": npos / len(names),
                          "n_paths_ir_ci_excludes_0": int(sum(r["ir_ci95"][0] > 0 for r in rows.values())),
                          "excess_across_paths": {"mean": float(ex.mean()), "min": float(ex.min()), "max": float(ex.max()),
                                                  "sd": float(ex.std(ddof=1))},
                          "ir_across_paths": {"mean": float(ir.mean()), "min": float(ir.min()), "max": float(ir.max())},
                          "ROBUST": bool(npos >= ROBUST_MIN)}
    plain = {f"{n}|none|{b.split('|')[1]}": bk(n, f"none|{b.split('|')[1]}") for n in [REF] + names for b in BOOKS.values()}
    aucs = np.array([pj["paths"][n]["cv_auc_mean"] for n in names])
    ics = np.array([pj["paths"][n]["rank_ic_mean"] for n in names])
    res = {
        "plan": "ml/IMPROVEMENT_PLAN_2.md Q2", "trial_count": 1, "n_trials_dsr": bj["n_trials"],
        "design": {"dataset": rel(DATA), "n_fold_months": 103, "groups": pj["groups"],
                   "group_sizes": list(GROUP_SIZES), "k_test_groups": K_TEST, "n_splits": len(SPLITS), "n_paths": len(names),
                   "embargo_sessions": EMBARGO, "model": "control: ml/scale5y.make_model('all51'), 52 features, raw, seed 108",
                   "path_assignment": pj["assignment"],
                   "purge": "drop training rows whose [date, exit_date] intersects a test group's [first, last] test date",
                   "embargo": f"drop training rows dated within {EMBARGO} sessions after each test group's last test date",
                   "holdout": "rows dated in the holdout window never trained on or scored; training rows whose label exit "
                              "date is on or after the holdout's first session are dropped",
                   "books": "ml/improve/ab_books --folds-only (P2 construction; 103 signal months; segments.combined)",
                   "robust_rule": f"positive net (20 bps) excess vs EW in >= {ROBUST_MIN} of 7 paths, read separately for "
                                  "the vol+size-neutral full-universe top decile and the liquid-tercile top decile"},
        "splits": {k: {kk: v[kk] for kk in ("test_groups", "n_train", "n_test", "train_sessions", "auc_pooled",
                                             "auc_by_group", "seconds")} for k, v in pj["splits"].items()},
        "path_metrics": {n: {k: v for k, v in pj["paths"][n].items() if k != "fold_aucs"} for n in names},
        "reference_metrics": {REF: {k: v for k, v in pj["reference"][REF].items() if k != "fold_aucs"}},
        "fold_aucs": {n: pj["paths"][n]["fold_aucs"] for n in names} | {REF: pj["reference"][REF]["fold_aucs"]},
        "auc_across_paths": {"mean": float(aucs.mean()), "min": float(aucs.min()), "max": float(aucs.max()),
                             "sd": float(aucs.std(ddof=1))},
        "rank_ic_across_paths": {"mean": float(ics.mean()), "min": float(ics.min()), "max": float(ics.max())},
        "readings": readings, "plain_books_descriptive": plain,
        "verdict": {"full_universe_neutral_top_decile": "ROBUST" if readings["full"]["ROBUST"] else "NOT ROBUST",
                    "liquid_neutral_top_decile": "ROBUST" if readings["liquid"]["ROBUST"] else "NOT ROBUST"},
        "caveat": "CPCV trains on months after the test window by design: it measures path dependence, not forward "
                  "performance",
    }
    wjson(OUT / "cpcv.json", res)
    write_md(res)
    log(f"report: full {readings['full']['n_paths_positive_net_excess']}/7 -> {res['verdict']['full_universe_neutral_top_decile']}; "
        f"liquid {readings['liquid']['n_paths_positive_net_excess']}/7 -> {res['verdict']['liquid_neutral_top_decile']}")


# ----------------------------------------------------------------------------- markdown
DESIGN_MD = [
    "# Q2: combinatorial purged cross-validation of the frozen construction", "",
    "Plan: `ml/IMPROVEMENT_PLAN_2.md` Q2 (1 trial of N = 261). Code: `ml/improve/cpcv.py`; books through "
    "`ml/improve/ab_books.py --folds-only`. Every number below is quoted from `ml/results/improve2/cpcv/cpcv.json`.", "",
    "## Design (fixed before any result)", "",
    "- Groups: the 103 fold months of `ml/data_10y/splits.json`, in order, cut into 8 contiguous groups of "
    "13, 13, 13, 13, 13, 13, 13 and 12 months (g0 = 2018-01..2019-01, ..., g7 = 2025-08..2026-07).",
    "- Splits: every pair of groups as the test set, C(8, 2) = 28 splits, in lexicographic order (s00 = g0+g1, "
    "s01 = g0+g2, ..., s27 = g6+g7).",
    "- Test rows: the clean labelled rows of the two groups' fold test windows.",
    "- Training rows: every clean labelled row of `ml/data_10y` outside the two test groups and outside the holdout "
    "window, after (a) the purge of rows whose label span [date, exit_date] intersects either test group's span "
    "[first test date, last test date] and (b) a 22-session embargo after each test group's last test date (sessions of "
    "the dataset's calendar). The 2017-10..2017-12 warm-up rows are trainable.",
    "- Model: the control (the champion LightGBM of `ml/scale5y.make_model(\"all51\")`, 52 features, raw "
    "preprocessing fitted on the training rows, seed 108), as `ml/improve/ab.py` fits it.",
    "- Paths: each group is tested in 7 of the 28 splits; path j takes, for every group, that group's j-th test "
    "occurrence in split order (the standard CPCV assignment: 2/8 x 28 = 7 paths, each covering all 103 months once). "
    "Path 1 therefore scores g0 with s00 (g0+g1), g1 with s00, g2 with s01 (g0+g2), and so on; the full table is "
    "`design.path_assignment` in `cpcv.json`.",
    "- Readings, per path: fold-month AUCs, per-date rank IC (Newey-West t, lag 20), and books with the P2 "
    "construction (`ml/improve/ab_books`): the vol+size-neutral full-universe top decile and the vol+size-neutral "
    "liquid-tercile top decile, net 20 bps per side vs the equal-weight universe, IR with its month-block 95% CI, DSR "
    "at N = 261 with V[SR] = 0.00387. **Robust across paths** if the full-universe book has positive net excess in "
    ">= 6 of 7 paths; the liquid book is read the same way.",
    "- CPCV trains on months after the test window by design: it measures path dependence, not forward performance.", "",
    "## Interpretations and deviations (written before the full run)", "",
    "- **Holdout never observed.** Besides the rows dated in the holdout window (2026-08-03..2026-09-16), the training "
    "rows whose label exit date is on or after 2026-08-03 are dropped (30,004 clean labelled rows: 30,003 dated in July "
    "2026 and one dated 2023-10-25 whose ticker's next 21 rows run past the holdout start), so no training label "
    "contains a holdout-window price. This is the walk-forward's own rule for its holdout fold and the reading of "
    "\"the holdout is never used\"; it removes rows only from splits whose test groups exclude g7 (with g7 tested, "
    "the same rows are test rows or fall to the g7 purge).",
    "- **Books on 103 months.** A CPCV path has no holdout predictions, so its books run on the 103 fold months only "
    "(`ab_books --folds-only`). The book engine requires a non-empty second segment; the hook therefore labels the last "
    "fold month (2026-07) as the engine's 'holdout' segment as a placeholder, and every reading uses the 'combined' "
    "segment (all 103 months). The walk-forward control's books in `ml/results/improve/ab/10y/` cover 105 months "
    "(with the holdout), so the like-for-like reference here is `wf_control`: the walk-forward control's own "
    "predictions on the same 103 months, scored through the same hook.",
    "- **Training-set size.** The brief estimated about 1.9M rows per split; the measured count is 1,351,005 to "
    "1,756,525 (mean 1,528,278; `smoke/smoke.json` `n_train_range`, `n_train_mean`): 2,187,230 clean labelled rows "
    "less the 47,117 holdout rows, the two test groups (about 0.5M), the purge and embargo, and the 30,004 rows whose "
    "label exits in the holdout window.", "",
    "## Smoke (timing only; `smoke/smoke.json`)", "",
    "- Split s00 (g0+g1, the largest training set, 1,756,525 rows) fitted on a 20% sample (351,062 rows, seed 108) in "
    "one forked worker: preprocess 0.9 s, fit 19.4 s, predict 4.4 s on 323,822 test rows; worker peak RSS 2.25 GB "
    "(shared frame pages included).",
    "- Full-run estimate for the 28 fits at 2 workers: 13 min (a line through the smoke point and the walk-forward "
    "control's measured fold times) to 22 min (5 x the smoke fit, scaled by each split's rows); on a busy shared box "
    "allow 20-35 min. The paths, books (8 scorers x 4 books) and report stages add about 10 min.", ""]


def write_md(res: dict | None) -> None:
    L = list(DESIGN_MD)
    iv = OUT / "smoke" / "invariants.json"
    if iv.exists():
        z = json.loads(iv.read_text())
        sp = z["splits"].values()
        L += ["## Design check (row masks of all 28 splits, no fitting; `smoke/invariants.json`)", "",
              f"All passed: {z['all_passed']}. Asserted on every split: " + "; ".join(z["checks"]) + ".",
              f"Training rows per split {min(v['n_train'] for v in sp):,}..{max(v['n_train'] for v in sp):,}; warm-up rows "
              f"(before 2018-01) used in training {min(v['n_train_warmup_before_2018'] for v in sp):,}.."
              f"{max(v['n_train_warmup_before_2018'] for v in sp):,} per split; training rows dated after the earlier "
              f"test group {min(v['n_train_after_a_test_group'] for v in sp):,}.."
              f"{max(v['n_train_after_a_test_group'] for v in sp):,} per split (CPCV trains on later months by design).", ""]
    if res is not None:
        L += ["## Verdict", "",
              f"- Full-universe neutral top decile: positive net excess in "
              f"{res['readings']['full']['n_paths_positive_net_excess']}/7 paths -> **{res['verdict']['full_universe_neutral_top_decile']}**.",
              f"- Liquid neutral top decile: positive net excess in "
              f"{res['readings']['liquid']['n_paths_positive_net_excess']}/7 paths -> **{res['verdict']['liquid_neutral_top_decile']}**.",
              f"- {res['caveat']}.", "",
              "## Model readings per path", "",
              "| Path | CV AUC ± sd | Worst month | Months >= 0.50 | Rank IC (NW t) | IC months positive | Rank corr with walk-forward |",
              "|---|---|---:|---:|---|---:|---:|"]
        for n, m in list(res["path_metrics"].items()) + list(res["reference_metrics"].items()):
            L.append(f"| {n} | {m['cv_auc_mean']:.4f} ± {m['cv_auc_std']:.4f} | {m['min_fold_auc']:.3f} | "
                     f"{100 * m['pct_folds_ge_050']:.0f}% | {m['rank_ic_mean']:+.4f} ({m['rank_ic_nw_t']:.1f}) | "
                     f"{m['rank_ic_months_positive']} | {ab._f(m.get('score_rank_corr_with_wf_per_date'), '.3f')} |")
        a = res["auc_across_paths"]
        L += ["", f"Path mean AUC across the 7 paths: mean {a['mean']:.4f}, range [{a['min']:.4f}, {a['max']:.4f}], "
                  f"sd {a['sd']:.4f}.", ""]
        for lab_, title in (("full", "Full-universe neutral top decile"), ("liquid", "Liquid-tercile neutral top decile")):
            r = res["readings"][lab_]
            L += [f"## {title} (`{r['book']}`), net 20 bps vs EW", "",
                  "| Path | Excess vs EW | IR [95% CI] | Months beating EW | Turnover | Name-level excess | DSR (N = 261) |",
                  "|---|---:|---|---:|---:|---:|---:|"]
            for n, x in list(r["paths"].items()) + [(REF + " (same 103 months)", r["reference_walk_forward_same_months"])]:
                L.append(f"| {n} | {100 * x['excess_ann_vs_ew_20bps']:+.1f}% | {x['ir']:+.2f} [{x['ir_ci95'][0]:+.2f}, "
                         f"{x['ir_ci95'][1]:+.2f}] | {x['months_positive']} | {100 * x['turnover_per_rebalance']:.0f}% | "
                         f"{100 * x['name_level_excess_ann_vs_ew']:+.1f}% | {x['dsr']:.3f} |")
            e = r["excess_across_paths"]
            L += ["", f"Positive in {r['n_paths_positive_net_excess']}/7 paths; IR CI excludes zero in "
                      f"{r['n_paths_ir_ci_excludes_0']}/7; excess across paths mean {100 * e['mean']:+.1f}%, range "
                      f"[{100 * e['min']:+.1f}%, {100 * e['max']:+.1f}%]. **{'ROBUST' if r['ROBUST'] else 'NOT ROBUST'}.**", ""]
        L += ["## Splits", "", "| Split | Test groups | Train rows | Train sessions | Test rows | AUC (pooled) | AUC by group | Fit seconds |",
              "|---|---|---:|---:|---:|---:|---|---:|"]
        for k, v in res["splits"].items():
            L.append(f"| {k} | {v['test_groups']} | {v['n_train']:,} | {v['train_sessions']} | {v['n_test']:,} | "
                     f"{v['auc_pooled']:.4f} | " + ", ".join(f"g{g} {x:.4f}" for g, x in v["auc_by_group"].items())
                     + f" | {v['seconds']['fit']} |")
        L.append("")
    else:
        L += ["## Results", "", "Not run yet: the lead queues `fit`, `paths`, `books` and `report`.", ""]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "CPCV.md").write_text("\n".join(L) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["doc", "check", "smoke", "fit", "paths", "books", "report"])
    ap.add_argument("--n-jobs", type=int, default=2)
    a = ap.parse_args()
    assert 1 <= a.n_jobs <= 2, "shared box: at most two worker processes"
    if a.stage == "doc":
        write_md(None)
        return
    {"check": check, "smoke": smoke, "fit": fit, "paths": paths, "books": books, "report": report}[a.stage](a)


if __name__ == "__main__":
    main()

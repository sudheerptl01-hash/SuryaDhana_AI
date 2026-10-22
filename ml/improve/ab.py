#!/usr/bin/env python3
"""Improvement-phase A/B harness (ml/IMPROVEMENT_PLAN.md: P1 re-runs, P3 AB1-AB6, P5 AB7).

Same protocol as the five-year run (ml/scale5y.py + ml/scale5y_nested.py): purged monthly
walk-forward folds from the dataset's splits.json, rolling 504-session training window,
22-session embargo (in the splits), EXIT-DATE PURGE of training rows whose label window
reaches the test month, untouched holdout scored once.  The champion LightGBM
configuration is used unchanged (ml/scale5y.make_model("all51")).  Nothing is tuned here.

Configurations are fixed in CONFIGS / FAMILIES below (pre-registered in the plan); a run
writes one JSON + one predictions parquet per configuration in the scale5y schema, and
`--compare` scores every variant against `control` with the plan's pass marks:
  primary    paired fold-level CV-mean AUC delta, 20-session paired block bootstrap
             (B = 1000, identical draws) 95% CI excluding zero AND mean delta >= +0.003
  secondary  per-date rank-IC delta (variant - control) with Newey-West t (lag 20) >= 2
  AB1 only   mean fold AUC over the six majority-inverted months improves by >= +0.02

Usage
  python3 -m ml.improve.ab run --data ml/data_5y_v2 --tag v2 --configs control lr_l2 baseline_mom
  python3 -m ml.improve.ab run --data ml/data_5y_v2 --tag v2 --extra ml/data_ext/extra_features.parquet \
      --market ml/data_ext/market_state.parquet --configs ab1_mkt ab2_sector ab3_fo ab4_flows ab5_all
  python3 -m ml.improve.ab compare --data ml/data_5y_v2 --tag v2

Seed 108; OMP_NUM_THREADS=2; at most two worker processes (shared 4-core box).
"""
from __future__ import annotations

import os

os.environ["OMP_NUM_THREADS"] = "2"
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
os.environ["OMP_WAIT_POLICY"] = "PASSIVE"

import argparse
import json
import math
import multiprocessing as mp
import time
from pathlib import Path

import numpy as np
import pandas as pd

import ml.scale5y as s5
from ml.eval_aggregate import WeightedAUC
from ml.evaluation import Preprocessor, compute_metrics
from ml.scale5y_nested import CB_PARAMS, window_rows
from ml.scale5y_report import _block_counts_within, ci, nw_t, per_date_ic

ML_DIR = Path(__file__).resolve().parents[1]
OUT_ROOT = ML_DIR / "results" / "improve" / "ab"
V1_EXTRA = ML_DIR / "results" / "scale5y" / "cache" / "extra_5y.parquet"
TASK = "beat_mkt_20d"
LABEL, FWD, CLEAN = "label_beat_mkt_20d", "y_excess_20d", "y_clean_20d"
SEED = 108
TRAIN_SESSIONS = 504
BLOCK = 20
B_BOOT = 1000
N_JOBS = 2
N_THREADS = 2
PASS_DELTA = 0.003
PASS_IC_T = 2.0
PASS_INVERSION = 0.02
INVERSION_MONTHS = ["2023-07", "2024-01", "2025-04", "2025-05", "2026-03", "2026-04"]
SUFF = ["deliv_value_share_20", "amihud_20"]

# Feature families, fixed in ml/IMPROVEMENT_PLAN.md P3 (names as the external-data stream writes them).
FAMILIES = {
    "F1": ["mkt_ret_20", "mkt_ret_63", "mkt_dd_252", "mkt_vol_20", "mkt_breadth_200", "sessions_since_selloff",
           "cs_dispersion_20", "vix_close", "vix_chg_20", "nifty50_pe"],
    "F2": ["ind_mom_20", "ind_ret_63", "rel_mom_20", "rel_ret_126", "rel_deliv", "indn_rank_mom_20",
           "indn_rank_ret_126", "indn_rank_deliv_sma", "indn_rank_atr", "secidx_ret_20"],
    "F3": ["fo_member", "fut_basis_near", "fut_oi_chg_5", "fut_oi_chg_20", "fut_oi_z_60", "pcr_oi", "pcr_chg_5",
           "opt_oi_to_turnover"],
    "F4": ["fii_idx_fut_net", "fii_idx_fut_net_chg_5", "fii_stk_fut_net", "client_idx_pcr"],
}
CONFIGS = {
    "control":            dict(kind="lgbm", extra=[], preprocess="raw", family="trees"),
    "lr_l2":              dict(kind="lr", extra=[], preprocess="scaled", family="linear"),
    "baseline_mom":       dict(kind="lr_mom", feats=["cs_rank_mom_20"], preprocess="scaled", family="baseline"),
    "ab1_mkt":            dict(kind="lgbm", extra=["F1"], preprocess="raw", family="trees"),
    "ab2_sector":         dict(kind="lgbm", extra=["F2"], preprocess="raw", family="trees"),
    # AB2P (plan amendment A3): same F2 columns from the permuted-industry placebo parquet (pass it as --extra)
    "ab2p_sector_placebo": dict(kind="lgbm", extra=["F2"], preprocess="raw", family="trees", placebo=True),
    "ab3_fo":             dict(kind="lgbm", extra=["F3"], preprocess="raw", family="trees"),
    "ab4_flows":          dict(kind="lgbm", extra=["F4"], preprocess="raw", family="trees"),
    "ab5_all":            dict(kind="lgbm", extra=["F1", "F2", "F3", "F4"], preprocess="raw", family="trees"),
    "ab6_lambdarank52":   dict(kind="lambdarank", extra=[], preprocess="raw", family="ranking"),
    "ab6_catboost52":     dict(kind="catboost", extra=[], preprocess="raw", family="trees"),
    "ab6_ensemble_all52": dict(kind="ensemble", members=["control", "ab6_lambdarank52", "ab6_catboost52"],
                               preprocess="rank_blend", family="ensemble"),
    "ab7_subsample5":     dict(kind="lgbm", extra=[], preprocess="raw", family="trees", subsample_dates=5),
    # AB8 (plan amendment A2): average-uniqueness sample weights (ml/hygiene/uniqueness.py concurrency_uniqueness)
    "ab8_uniqueness_w":   dict(kind="lgbm", extra=[], preprocess="raw", family="trees", uniqueness_weights=True),
    # AB0 (plan amendment A1): the frozen five-year all-50-feature LightGBM, copied from ml/results/scale5y/ for comparison only
    "all51":              dict(kind="reference", extra=[], preprocess="raw", family="trees"),
}
VARIANTS = ["all51", "ab1_mkt", "ab2_sector", "ab2p_sector_placebo", "ab3_fo", "ab4_flows", "ab5_all", "ab6_ensemble_all52", "ab7_subsample5", "ab8_uniqueness_w",
            "lr_l2", "baseline_mom", "ab6_lambdarank52", "ab6_catboost52"]

T0 = time.time()
_DF: pd.DataFrame | None = None
_DATES: pd.DatetimeIndex | None = None
_DD: np.ndarray | None = None


def log(msg: str) -> None:
    print(f"[ab +{time.time() - T0:6.0f}s] {msg}", flush=True)


def _jd(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp, np.datetime64)):
        return str(pd.Timestamp(o).date())
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def wjson(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, default=_jd))
    tmp.replace(path)


# ----------------------------------------------------------------------------- data
def load_frame(data: Path, extra: Path | None, market: Path | None, v1_extra: bool) -> tuple[pd.DataFrame, list[str], dict]:
    manifest = json.loads((data / "manifest.json").read_text())
    splits = json.loads((data / "splits.json").read_text())
    feats = list(manifest["features"])
    want = ["date", "ticker"] + feats + [LABEL, FWD, CLEAN, "y_raw_20d", "y_rank_20d", "cs_rank_turnover"]
    import pyarrow.parquet as pq
    cols_avail = set(pq.read_schema(data / "model_dataset.parquet").names)
    for c in SUFF + ["exit_date"]:
        if c in cols_avail:
            want.append(c)
    want = [c for c in dict.fromkeys(want) if c in cols_avail]
    df = pd.read_parquet(data / "model_dataset.parquet", columns=want)
    df["date"] = pd.to_datetime(df["date"])
    if v1_extra:  # v1 dataset: exit dates and the two sufficiency features live in the scale5y cache (frozen)
        ex = pd.read_parquet(V1_EXTRA)
        assert (ex["ticker"].to_numpy() == df["ticker"].to_numpy()).all()
        assert (pd.to_datetime(ex["date"]).to_numpy() == df["date"].to_numpy()).all()
        for c in SUFF:
            df[c] = ex[c].to_numpy(float)
        df["exit_date"] = pd.to_datetime(ex["exit_date"]).to_numpy()
    assert "exit_date" in df.columns, "dataset needs an exit_date column (or --v1-extra)"
    for c in SUFF:
        assert c in df.columns, f"{c} missing from the dataset"
        if c not in feats:
            feats.append(c)
    if extra is not None:
        xf = pd.read_parquet(extra)
        xf["date"] = pd.to_datetime(xf["date"])
        xcols = [c for c in xf.columns if c not in ("date", "ticker")]
        n0 = len(df)
        df = df.merge(xf[["date", "ticker"] + xcols], on=["date", "ticker"], how="left", validate="one_to_one")
        assert len(df) == n0
        log(f"extra features joined: {len(xcols)} columns, coverage "
            + ", ".join(f"{c}={df[c].notna().mean():.2f}" for c in xcols[:6]) + " ...")
    if market is not None:
        mk = pd.read_parquet(market)
        mk["date"] = pd.to_datetime(mk["date"])
        mcols = [c for c in mk.columns if c != "date"]
        n0 = len(df)
        df = df.merge(mk[["date"] + mcols], on="date", how="left", validate="many_to_one")
        assert len(df) == n0
        log(f"market-state features joined: {len(mcols)} columns")
    df["exit_date"] = pd.to_datetime(df["exit_date"]).to_numpy()
    df = df.sort_values(["date", "ticker"], kind="stable").reset_index(drop=True)
    return df, feats, splits


def features_for(name: str, base_feats: list[str], df_cols: set[str]) -> list[str]:
    spec = CONFIGS[name]
    if spec.get("feats"):
        return list(spec["feats"])
    feats = list(base_feats)
    for fam in spec.get("extra", []):
        missing = [c for c in FAMILIES[fam] if c not in df_cols]
        assert not missing, f"{name}: family {fam} columns missing from the frame: {missing}"
        feats += FAMILIES[fam]
    return feats


# ----------------------------------------------------------------------------- one fold
def _fold_job(args):
    name, spec, feats, cache = args
    ck = cache / "folds" / name / f"{spec['name']}.json"
    pk = ck.with_suffix(".parquet")
    if ck.exists() and pk.exists():
        return json.loads(ck.read_text())
    t0 = time.time()
    tr, te, n_before, n_purged = window_rows(_DF, _DD, _DATES, spec, TRAIN_SESSIONS)
    cfg = CONFIGS[name]
    n_sub = cfg.get("subsample_dates")
    if n_sub:
        # every n-th signal date of the training window, anchored on the last training date
        tpos = np.searchsorted(_DATES.values, tr["date"].to_numpy(dtype="datetime64[ns]"))
        keep = ((tpos - tpos.max()) % n_sub) == 0
        tr = tr[keep]
    prep_ = Preprocessor(cfg["preprocess"]).fit(tr[feats])
    Xtr, Xte = prep_.transform(tr[feats]), prep_.transform(te[feats])
    ytr, yte = tr[LABEL].to_numpy(np.float32), te[LABEL].to_numpy(np.float32)
    kind = cfg["kind"]
    if kind == "lgbm":
        est = s5.make_model("all51", N_THREADS)
        if cfg.get("uniqueness_weights"):
            est.fit(Xtr, ytr, sample_weight=uniqueness_weights(tr))
        else:
            est.fit(Xtr, ytr)
        score = est.predict_proba(Xte)[:, 1]
    elif kind in ("lr", "lr_mom"):
        est = s5.make_model("lr_l2" if kind == "lr" else "baseline_mom", N_THREADS)
        est.fit(Xtr, ytr)
        score = est.predict_proba(Xte)[:, 1]
    elif kind == "lambdarank":
        from lightgbm import LGBMRanker
        d = tr["date"].to_numpy()
        assert (d[1:] >= d[:-1]).all()
        grade = np.clip(np.floor(tr["y_rank_20d"].to_numpy(float) * 10), 0, 9).astype(int)
        group = tr.groupby("date", sort=True).size().to_numpy()
        p = s5.make_model("all51", N_THREADS).get_params()
        keep = {k: p[k] for k in ("num_leaves", "learning_rate", "n_estimators", "random_state")}
        est = LGBMRanker(objective="lambdarank", feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1,
                         min_data_in_leaf=200, num_threads=N_THREADS, verbosity=-1, **keep)
        est.fit(Xtr, grade, group=group)
        score = 1.0 / (1.0 + np.exp(-est.predict(Xte)))
    elif kind == "catboost":
        from catboost import CatBoostClassifier
        est = CatBoostClassifier(**CB_PARAMS, allow_writing_files=False)
        est.fit(Xtr, ytr)
        score = est.predict_proba(Xte)[:, 1]
    else:
        raise ValueError(kind)
    met = compute_metrics(yte, score, te[FWD].to_numpy(np.float32))
    met.update(fold=spec["name"], n_train=int(len(tr)), n_train_before_purge=n_before,
               n_train_purged_exit_ge_test_start=n_purged, n_features=len(feats),
               train_seconds=round(time.time() - t0, 1))
    preds = te[["date", "ticker"]].copy()
    preds["score"], preds["y"], preds["fwd"], preds["fold"] = score, yte, te[FWD].to_numpy(), spec["name"]
    ck.parent.mkdir(parents=True, exist_ok=True)
    preds.to_parquet(pk, index=False)
    wjson(ck, met)
    log(f"{name} {spec['name']}: auc={met['auc']:.4f} n_train={len(tr):,} purged={n_purged} "
        f"k={len(feats)} ({met['train_seconds']}s)")
    return met


def uniqueness_weights(tr: pd.DataFrame) -> np.ndarray:
    """Average uniqueness of each training row's label span (t+1 .. exit) among its ticker's labels in the
    window (López de Prado, AFML ch. 4), via ml/hygiene/uniqueness.py; normalised to mean 1."""
    from ml.hygiene.uniqueness import concurrency_uniqueness
    dvals = _DATES.values
    si = np.searchsorted(dvals, tr["date"].to_numpy(dtype="datetime64[ns]"))
    ex = tr["exit_date"].to_numpy(dtype="datetime64[ns]")
    ok = ~np.isnat(ex)
    ei = np.where(ok, np.searchsorted(dvals, np.where(ok, ex, dvals[0])), si + 21)
    ei = np.minimum(np.maximum(ei, si + 1), len(dvals) + 1)
    tick, codes = np.unique(tr["ticker"].to_numpy(), return_inverse=True)
    u, _ = concurrency_uniqueness(codes.astype(np.int64), si.astype(np.int64), ei.astype(np.int64), len(tick), len(dvals) + 1)
    u = np.where(np.isfinite(u) & (u > 0), u, np.nanmean(u[np.isfinite(u) & (u > 0)]))
    return (u / u.mean()).astype(np.float64)


def write_model(out: Path, name: str, specs: list[dict], feats: list[str], folds_meta: list[dict],
                preds: pd.DataFrame, params: dict, notes: str) -> dict:
    folds = [m for m in folds_meta if m["fold"] != "holdout"]
    holdout = next((m for m in folds_meta if m["fold"] == "holdout"), None)
    aucs = np.array([f["auc"] for f in folds])
    cfg = CONFIGS[name]
    payload = {
        "model": name, "family": cfg["family"], "agent": "lead-improve", "task": TASK, "params": params,
        "preprocess": cfg["preprocess"], "n_features": len(feats), "feature_subset": feats if len(feats) <= 12 else None,
        "features": feats, "folds": folds, "cv_auc_mean": float(aucs.mean()), "cv_auc_std": float(aucs.std()),
        "min_fold_auc": float(aucs.min()), "pct_folds_ge_050": float(np.mean(aucs >= 0.5)), "holdout": holdout,
        "train_seconds": round(float(sum(m.get("train_seconds", 0) for m in folds_meta)), 1),
        "exit_date_purge": {"rows_removed_total": int(sum(m.get("n_train_purged_exit_ge_test_start", 0) for m in folds_meta))},
        "notes": notes,
    }
    wjson(out / f"{name}__{TASK}.json", payload)
    (out / "preds").mkdir(parents=True, exist_ok=True)
    preds.to_parquet(out / "preds" / f"{name}__{TASK}.parquet", index=False)
    log(f"[{name}] folds={len(folds)} cv_auc={payload['cv_auc_mean']:.4f}±{payload['cv_auc_std']:.4f} "
        f"min={payload['min_fold_auc']:.4f} ge50={payload['pct_folds_ge_050']:.0%} "
        f"holdout={holdout['auc'] if holdout else float('nan'):.4f}")
    return payload


def run(a) -> None:
    global _DF, _DATES, _DD
    data, out = Path(a.data), OUT_ROOT / a.tag
    cache = out / "cache"
    df, feats, splits = load_frame(data, Path(a.extra) if a.extra else None, Path(a.market) if a.market else None,
                                   a.v1_extra)
    specs = splits["folds"] + ([] if a.skip_holdout else [splits["holdout"]])
    if a.folds:
        specs = [s for s in specs if s["name"] in a.folds]
    _DATES = pd.DatetimeIndex(np.sort(df["date"].unique()))
    _DF = df
    _DD = df["date"].to_numpy(dtype="datetime64[ns]")
    log(f"frame: {len(df):,} rows, {len(_DATES)} sessions, {len(feats)} base features, {len(specs)} fold specs")
    cols = set(df.columns)
    ctx = mp.get_context("fork")
    for name in a.configs:
        cfg = CONFIGS[name]
        if cfg["kind"] == "ensemble":
            ensemble(out, name, specs, cfg["members"])
            continue
        fl = features_for(name, feats, cols)
        jobs = [(name, s, fl, cache) for s in specs]
        jobs.sort(key=lambda j: j[1]["name"], reverse=True)
        with ctx.Pool(a.n_jobs) as pool:
            pool.map(_fold_job, jobs, chunksize=1)
        metas = [json.loads((cache / "folds" / name / f"{s['name']}.json").read_text()) for s in specs]
        preds = pd.concat([pd.read_parquet(cache / "folds" / name / f"{s['name']}.parquet") for s in specs],
                          ignore_index=True)
        params = {"train_sessions": TRAIN_SESSIONS, "n_jobs": a.n_jobs, "exit_date_purge": True,
                  "dataset": str(data), "extra": a.extra, "market": a.market, "families": cfg.get("extra", []),
                  "subsample_dates": cfg.get("subsample_dates")}
        if cfg["kind"] == "lgbm":
            params["lgbm"] = s5.make_model("all51", N_THREADS).get_params()
        elif cfg["kind"] == "catboost":
            params["catboost"] = {k: v for k, v in CB_PARAMS.items() if k != "verbose"}
        notes = (f"improvement-phase A/B ({a.tag}): walk-forward on {data.name} splits, rolling {TRAIN_SESSIONS}-session "
                 "window, exit-date purge, champion configuration unchanged; see ml/IMPROVEMENT_PLAN.md")
        write_model(out, name, specs, fl, metas, preds, params, notes)


def ensemble(out: Path, name: str, specs: list[dict], members: list[str]) -> None:
    base = None
    for j, m in enumerate(members):
        p = pd.read_parquet(out / "preds" / f"{m}__{TASK}.parquet")
        p["date"] = pd.to_datetime(p["date"])
        p = p.rename(columns={"score": f"s{j}"})
        if base is None:
            base = p
        else:
            n0 = len(base)
            q = p[["date", "ticker", "fold", f"s{j}", "y"]].rename(columns={"y": f"y{j}"})
            base = base.merge(q, on=["date", "ticker", "fold"], how="inner", validate="1:1")
            assert len(base) == n0 and (base[f"y{j}"] == base["y"]).all()
    g = base.groupby("date")
    base["score"] = np.mean(np.column_stack([g[f"s{j}"].rank(pct=True).to_numpy() for j in range(len(members))]), axis=1)
    metas = []
    for s in specs:
        f = base[base["fold"] == s["name"]]
        if f.empty:
            continue
        met = compute_metrics(f["y"].to_numpy(np.float32), f["score"].to_numpy(float), f["fwd"].to_numpy(np.float32))
        mm = json.loads((out / "cache" / "folds" / members[0] / f"{s['name']}.json").read_text())
        met.update(fold=s["name"], n_train=mm["n_train"], n_train_before_purge=mm.get("n_train_before_purge"),
                   n_train_purged_exit_ge_test_start=mm.get("n_train_purged_exit_ge_test_start"),
                   n_features=mm["n_features"], train_seconds=0.0, note="no own fit")
        metas.append(met)
    corr = {}
    for x in range(len(members)):
        for y_ in range(x + 1, len(members)):
            r = base.groupby("date").apply(lambda d: d[f"s{x}"].rank().corr(d[f"s{y_}"].rank()))
            corr[f"{members[x]}~{members[y_]}"] = round(float(r.mean()), 3)
    params = {"members": members, "combiner": "per-date percentile rank of each member, equal-weight mean; no weights fitted",
              "member_rank_corr_mean_per_date": corr}
    write_model(out, name, specs, json.loads((out / f"{members[0]}__{TASK}.json").read_text())["features"], metas,
                base[["date", "ticker", "score", "y", "fwd", "fold"]], params,
                "rank-average ensemble of the champion LightGBM, LambdaRank and CatBoost on ALL base features, "
                "no yearly re-selection (ml/PROGRAM_REPORT.md §11 item 4; plan P3 AB6)")


# ----------------------------------------------------------------------------- compare
def compare(a) -> None:
    data, out = Path(a.data), OUT_ROOT / a.tag
    df, feats, splits = load_frame(data, None, None, a.v1_extra)
    cvf = [f["name"] for f in splits["folds"]]
    names = [n for n in ["control"] + VARIANTS if (out / f"{n}__{TASK}.json").exists()]
    assert "control" in names, "control missing"
    base = df[df[LABEL].notna() & df[CLEAN].astype(bool)][["date", "ticker", LABEL, FWD, "y_raw_20d"]].copy()
    fold = pd.Series(pd.NA, index=base.index, dtype="object")
    for s in splits["folds"] + [splits["holdout"]]:
        fold[(base["date"] >= s["test_start"]) & (base["date"] <= s["test_end"])] = s["name"]
    base["fold"] = fold
    base = base[base["fold"].notna()].reset_index(drop=True)
    y = base[LABEL].to_numpy(float)
    key = base[["date", "ticker"]]
    scores, lg = {}, {}
    for n in names:
        pr = pd.read_parquet(out / "preds" / f"{n}__{TASK}.parquet", columns=["date", "ticker", "score", "y"])
        pr["date"] = pd.to_datetime(pr["date"])
        mm = key.merge(pr, on=["date", "ticker"], how="left", validate="one_to_one")
        sc = mm["score"].to_numpy(float)
        ok = np.isfinite(sc)
        assert np.array_equal(mm["y"].to_numpy(float)[ok], y[ok]), f"{n}: label mismatch"
        scores[n] = sc
        lg[n] = json.loads((out / f"{n}__{TASK}.json").read_text())
    folds_present = [f for f in cvf if all(any(x["fold"] == f for x in lg[n]["folds"]) for n in names)]
    fo = base["fold"].to_numpy()
    cvrows = np.flatnonzero(np.isin(fo, folds_present))
    allfin = np.all([np.isfinite(scores[n][cvrows]) for n in names], axis=0)
    cvrows = cvrows[allfin]
    dts = base["date"].to_numpy(dtype="datetime64[ns]")
    cdates = {f: np.unique(dts[cvrows][fo[cvrows] == f]) for f in folds_present}
    msz = np.array([len(cdates[f]) for f in folds_present])
    off = np.r_[0, np.cumsum(msz)[:-1]]
    allcv = np.concatenate([cdates[f] for f in folds_present])
    M = len(allcv)
    cnt = _block_counts_within(M, BLOCK, B_BOOT, np.random.default_rng(SEED))
    W = np.column_stack([cnt[:, off[i]:off[i] + msz[i]].sum(1) for i in range(len(folds_present))])
    mult = W / msz[None, :]
    code_cv = np.searchsorted(allcv, dts[cvrows])
    frows = {f: np.flatnonzero(fo[cvrows] == f) for f in folds_present}
    draws = {}
    for n in names:
        t1 = time.time()
        scv, ycv = scores[n][cvrows], y[cvrows]
        eng_f = {f: WeightedAUC(scv[frows[f]], ycv[frows[f]]) for f in folds_present}
        A = np.full((B_BOOT, len(folds_present)), np.nan)
        for b in range(B_BOOT):
            w = cnt[b][code_cv]
            for i, f in enumerate(folds_present):
                if W[b, i] > 0:
                    A[b, i] = eng_f[f].auc(w[frows[f]])
        draws[n] = np.nansum(np.nan_to_num(A) * mult, 1) / np.where(W > 0, mult, 0).sum(1)
        log(f"bootstrap {n}: {time.time() - t1:.0f}s")
    # rank IC per date
    dates = np.unique(dts)
    codes = np.searchsorted(dates, dts)
    yx = base[FWD].to_numpy(float)
    dmon = pd.DatetimeIndex(dates).strftime("%Y-%m").to_numpy()
    cvd_mask = np.isin(dmon, folds_present)
    ics = {n: per_date_ic(codes, scores[n], yx, len(dates)) for n in names}
    # gross top-decile excess vs EW per date (descriptive)
    yr = base["y_raw_20d"].to_numpy(float)
    nrow = np.bincount(codes, minlength=len(dates))
    ew_d = np.bincount(codes, yr, len(dates)) / np.maximum(nrow, 1)
    ex_d = {}
    for n in names:
        r = pd.Series(scores[n]).groupby(codes).rank(pct=True, method="first").to_numpy()
        top = r > 0.9
        topm = np.bincount(codes[top], yr[top], len(dates)) / np.maximum(np.bincount(codes[top], minlength=len(dates)), 1)
        ex_d[n] = topm - ew_d
    res = {"design": {"B": B_BOOT, "block_sessions": BLOCK, "n_cv_dates": int(M), "folds": folds_present,
                      "pass_marks": {"primary": f"paired CV-mean AUC delta vs control: 95% CI excludes 0 and delta >= {PASS_DELTA}",
                                     "secondary": f"per-date rank-IC delta Newey-West t (lag 20) >= {PASS_IC_T}",
                                     "ab1_inversion": f"mean AUC over {INVERSION_MONTHS} improves by >= {PASS_INVERSION}"}},
           "models": {}, "pairs": {}}
    inv = [m for m in INVERSION_MONTHS if m in folds_present]
    for n in names:
        fa = {x["fold"]: x["auc"] for x in lg[n]["folds"]}
        icv = ics[n][cvd_mask]
        mon = pd.Series(icv).groupby(dmon[cvd_mask]).mean()
        res["models"][n] = {
            "cv_auc_mean": float(np.mean([fa[f] for f in folds_present])), "cv_mean_ci95": ci(draws[n]),
            "cv_auc_std": float(np.std([fa[f] for f in folds_present])),
            "min_fold_auc": float(min(fa[f] for f in folds_present)),
            "pct_folds_ge_050": float(np.mean([fa[f] >= 0.5 for f in folds_present])),
            "holdout_auc": (lg[n]["holdout"] or {}).get("auc"),
            "n_features": lg[n]["n_features"],
            "rank_ic_cv_mean": float(np.nanmean(icv)), "rank_ic_nw_t": nw_t(icv),
            "rank_ic_months_positive": f"{int((mon > 0).sum())}/{len(mon)}",
            "inversion_months_mean_auc": float(np.mean([fa[m] for m in inv])) if inv else None,
            "top_decile_gross_excess_vs_ew_20d": float(np.nanmean(ex_d[n][cvd_mask])),
            "fold_aucs": fa, "train_seconds": lg[n]["train_seconds"],
        }
    c = "control"
    fac = {x["fold"]: x["auc"] for x in lg[c]["folds"]}
    for n in names:
        if n == c:
            continue
        fa = {x["fold"]: x["auc"] for x in lg[n]["folds"]}
        diffs = np.array([fa[f] - fac[f] for f in folds_present])
        dd = draws[n] - draws[c]
        dic = ics[n] - ics[c]
        dicv = dic[cvd_mask]
        dmonic = pd.Series(dicv).groupby(dmon[cvd_mask]).mean()
        inv_delta = (float(np.mean([fa[m] for m in inv])) - float(np.mean([fac[m] for m in inv]))) if inv else None
        primary = bool(diffs.mean() >= PASS_DELTA and ci(dd)[0] > 0)
        secondary = bool(nw_t(dicv) >= PASS_IC_T)
        entry = {"delta_cv_mean": float(diffs.mean()), "ci95": ci(dd), "p_gt_0": float(np.mean(dd > 0)),
                 "ci_excludes_0": bool(ci(dd)[0] > 0 or ci(dd)[1] < 0),
                 "folds_won": f"{int((diffs > 0).sum())}/{len(diffs)}",
                 "month_level_paired_t": float(diffs.mean() / (diffs.std(ddof=1) / math.sqrt(len(diffs)))) if len(diffs) > 1 else None,
                 "rank_ic_delta_mean": float(np.nanmean(dicv)), "rank_ic_delta_nw_t": nw_t(dicv),
                 "rank_ic_delta_months_positive": f"{int((dmonic > 0).sum())}/{len(dmonic)}",
                 "inversion_months_auc_delta": inv_delta,
                 "holdout_auc_delta": ((lg[n]["holdout"] or {}).get("auc") or np.nan) - ((lg[c]["holdout"] or {}).get("auc") or np.nan),
                 "top_decile_gross_excess_delta_20d": float(np.nanmean(ex_d[n][cvd_mask]) - np.nanmean(ex_d[c][cvd_mask])),
                 "pass_primary": primary, "pass_secondary": secondary,
                 "pass_ab1_inversion": (bool(inv_delta >= PASS_INVERSION) if (n == "ab1_mkt" and inv_delta is not None) else None),
                 "PASS": primary}
        res["pairs"][f"{n} - control"] = entry
    wjson(out / "compare.json", res)
    write_md(out, res, a.tag)
    log("compare written")


def _f(x, fmt):
    return "" if x is None or (isinstance(x, float) and not np.isfinite(x)) else format(x, fmt)


def write_md(out: Path, res: dict, tag: str) -> None:
    L = [f"# A/B comparison ({tag})", "",
         f"Protocol: {len(res['design']['folds'])} purged monthly folds, rolling {TRAIN_SESSIONS}-session window, exit-date purge; "
         f"paired 20-session block bootstrap (B = {B_BOOT}) on the pooled {res['design']['n_cv_dates']} CV dates; identical draws for every model.", "",
         "Pass marks (fixed in `ml/IMPROVEMENT_PLAN.md`): " + "; ".join(f"{k}: {v}" for k, v in res["design"]["pass_marks"].items()), "",
         "| Configuration | #feat | CV AUC ± sd | 95% CI | Folds ≥ 0.50 | Worst | Holdout | Rank IC (NW t) | Inversion-month AUC | Top-decile gross excess vs EW, 20d |",
         "|---|---:|---|---|---:|---:|---:|---|---:|---:|"]
    for n, m in res["models"].items():
        L.append(f"| {n} | {m['n_features']} | {m['cv_auc_mean']:.4f} ± {m['cv_auc_std']:.4f} | "
                 f"[{m['cv_mean_ci95'][0]:.4f}, {m['cv_mean_ci95'][1]:.4f}] | {100 * m['pct_folds_ge_050']:.0f}% | "
                 f"{m['min_fold_auc']:.3f} | {_f(m['holdout_auc'], '.4f')} | {m['rank_ic_cv_mean']:+.4f} ({m['rank_ic_nw_t']:.1f}) | "
                 f"{_f(m['inversion_months_mean_auc'], '.3f')} | {100 * m['top_decile_gross_excess_vs_ew_20d']:+.2f}% |")
    L += ["", "| Variant − control | Δ CV mean | 95% CI | Folds won | Δ rank IC (NW t) | Δ inversion-month AUC | Δ holdout | Primary | Secondary |",
          "|---|---:|---|---:|---|---:|---:|---|---|"]
    for k, p in res["pairs"].items():
        L.append(f"| {k} | {p['delta_cv_mean']:+.4f} | [{p['ci95'][0]:+.4f}, {p['ci95'][1]:+.4f}] | {p['folds_won']} | "
                 f"{p['rank_ic_delta_mean']:+.4f} ({p['rank_ic_delta_nw_t']:.1f}) | {_f(p['inversion_months_auc_delta'], '+.3f')} | "
                 f"{_f(p['holdout_auc_delta'], '+.4f')} | {'PASS' if p['pass_primary'] else 'FAIL'} | "
                 f"{'PASS' if p['pass_secondary'] else 'FAIL'} |")
    (out / "AB.md").write_text("\n".join(L) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["run", "compare"])
    ap.add_argument("--data", default=str(ML_DIR / "data_5y_v2"))
    ap.add_argument("--tag", default="v2")
    ap.add_argument("--extra", default=None)
    ap.add_argument("--market", default=None)
    ap.add_argument("--configs", nargs="+", default=["control"])
    ap.add_argument("--folds", nargs="+", default=None, help="subset of fold names (smoke tests)")
    ap.add_argument("--skip-holdout", action="store_true")
    ap.add_argument("--v1-extra", action="store_true", help="v1 dataset: take exit dates + sufficiency features from the scale5y cache")
    ap.add_argument("--n-jobs", type=int, default=N_JOBS)
    a = ap.parse_args()
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    if a.stage == "run":
        run(a)
    else:
        compare(a)


if __name__ == "__main__":
    main()

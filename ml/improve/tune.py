#!/usr/bin/env python3
"""Nested hyper-parameter selection for the control LightGBM (ml/IMPROVEMENT_PLAN_2.md Q7).

Grid (fixed in the plan): the incumbent (num_leaves 63, min_data_in_leaf 200, feature_fraction 0.8) plus
num_leaves {31, 127} x min_data_in_leaf {200, 2000} x feature_fraction {0.5, 0.8}: 9 settings, each with 300 trees,
learning rate 0.05, bagging 0.8 every iteration, seed 108 and the rest of ml/scale5y.make_model("all51").

Selection, once per calendar year Y in 2018..2026, on rows the outer walk-forward of year Y may itself train on:
  anchor   train_end of fold "Y-01" in ml/data_10y/splits.json (embargo-adjusted: every label of a row dated <= the
           anchor has exited before the first test session of year Y)
  blocks   the last 3 consecutive 21-session blocks of labelled sessions ending at the anchor
           (ml/scale5y_nested.make_blocks: each block's inner train_end is 22 sessions before its first session)
  a fit    one setting on one block: train on the rolling 504 sessions ending at the block's inner train_end, exit-date
           purge against the block's first session (ml/scale5y_nested.window_rows, the outer harness's own row rule),
           score the block's clean labelled rows, AUC
  choice   the setting with the best mean AUC over the 3 blocks (ties: grid order, incumbent first); the incumbent is
           kept unless the best beats it by >= 0.002.  A year without 3 blocks whose training windows hold >= 120
           sessions each keeps the incumbent, and the reason is recorded.

Stages
  smoke   one year, one block, every setting (fits land in the cache, so select reuses them) plus a check that the
          fitted trees honour num_leaves / min_data_in_leaf / feature_fraction -> smoke/smoke.json
  select  every inner fit (cache/<Y>/<setting>__<block>.json, resume-safe), then selected_params.json (read by
          ml/improve/ab.py, config q7_tuned), tune.json (every inner AUC) and TUNE.md.  Writes select.pid while it runs.
  audit   (added after the selection ran) inner scoring rows whose label exits on or after the outer fold Y-01's
          first test session: counts, the largest AUC change their removal could cause, and whether any year's choice
          could flip -> tune.json "audit_inner_exit" and a TUNE.md section
  report  after the outer run: folds the 'q7_tuned - control' pair of ml/results/improve/ab/10y_p2/compare.json and
          the Q7 books (books_q7.json, ml/improve/ab_books --out-name books_q7) into tune.json / TUNE.md

    python3 -m ml.improve.tune smoke --year 2026 --block blk00 --n-jobs 2
    nohup python3 -m ml.improve.tune select --n-jobs 2 > ml/results/improve2/tune/select.log 2>&1 &
    python3 -m ml.improve.tune audit --n-jobs 2
    python3 -m ml.improve.tune report

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
import multiprocessing as mp
import time
from pathlib import Path

import numpy as np
import pandas as pd

import ml.improve.ab as ab
import ml.scale5y as s5
from ml.evaluation import Preprocessor, compute_metrics
from ml.scale5y_nested import EMBARGO, INNER_LEN, make_blocks, window_rows

ML_DIR = Path(__file__).resolve().parents[1]
REPO = ML_DIR.parent
DATA = ML_DIR / "data_10y"
OUT = ML_DIR / "results" / "improve2" / "tune"
CACHE = OUT / "cache"
AB_TAG = ab.OUT_ROOT / "10y_p2"
LABEL, FWD, CLEAN = ab.LABEL, ab.FWD, ab.CLEAN
SEED = 108
YEARS = tuple(range(2018, 2027))
N_BLOCKS = 3
TRAIN_SESSIONS = 504
MIN_TRAIN_SESSIONS = 120
MARGIN = 0.002
N_THREADS = 2
INCUMBENT = (63, 200, 0.8)
GRID = [INCUMBENT] + [(nl, md, ff) for nl in (31, 127) for md in (200, 2000) for ff in (0.5, 0.8)]


def sname(nl: int, md: int, ff: float) -> str:
    return f"nl{nl}_mdl{md}_ff{ff}"


SETTINGS = {sname(*g): {"num_leaves": g[0], "min_data_in_leaf": g[1], "feature_fraction": g[2]} for g in GRID}
INC = sname(*INCUMBENT)
RULE = (f"mean AUC over the last {N_BLOCKS} {INNER_LEN}-session blocks before the anchor (each block: rolling "
        f"{TRAIN_SESSIONS}-session training window ending {EMBARGO} sessions before its first session, exit-date purge "
        f"against that session); best mean wins (ties: grid order, incumbent first) but the incumbent is kept unless "
        f"the best beats it by >= {MARGIN}; a year without {N_BLOCKS} blocks whose training windows hold >= "
        f"{MIN_TRAIN_SESSIONS} sessions keeps the incumbent")

T0 = time.time()
_DF: pd.DataFrame | None = None          # set before the pool is forked
_DD: np.ndarray | None = None
_DATES: pd.DatetimeIndex | None = None
_LABCAL: pd.DatetimeIndex | None = None
_FEATS: list[str] | None = None


def log(msg: str) -> None:
    print(f"[tune +{time.time() - T0:6.0f}s] {msg}", flush=True)


wjson = ab.wjson


def rel(p: Path) -> str:
    return str(p.relative_to(REPO)) if p.is_relative_to(REPO) else str(p)


def model(setting: str):
    """The control's LightGBM with the setting's three parameters (set_params on the make_model kwargs, which
    LightGBM honours over the colsample_bytree / min_child_samples defaults: checked in the smoke stage)."""
    return s5.make_model("all51", N_THREADS).set_params(**SETTINGS[setting])


# ----------------------------------------------------------------------------- frame and plan
def load() -> dict:
    global _DF, _DD, _DATES, _LABCAL, _FEATS
    df, feats, splits = ab.load_frame(DATA, None, None, False)
    _DF, _FEATS = df, feats
    _DD = df["date"].to_numpy(dtype="datetime64[ns]")
    _DATES = pd.DatetimeIndex(np.unique(_DD))
    lab = df[LABEL].notna().to_numpy() & df[CLEAN].to_numpy().astype(bool)
    _LABCAL = pd.DatetimeIndex(np.unique(_DD[lab]))
    log(f"frame: {len(df):,} rows, {len(_DATES)} sessions ({len(_LABCAL)} labelled), {len(feats)} features")
    return splits


def year_plan(year: int, splits: dict) -> dict:
    """Anchor, the 3 inner blocks and their eligibility for one calendar year."""
    spec = next(f for f in splits["folds"] if f["name"] == f"{year}-01")
    anchor = pd.Timestamp(spec["train_end"])
    cal = _LABCAL[_LABCAL <= anchor]
    blocks = make_blocks(cal, N_BLOCKS)
    info = []
    for b in blocks:
        te_ = pd.Timestamp(b["train_end"])
        first = _DATES[max(_DATES.get_loc(te_) - TRAIN_SESSIONS, 0)]
        n_sess = int(((_LABCAL >= first) & (_LABCAL <= te_)).sum())
        info.append({**b, "train_first": str(first.date()), "train_sessions": n_sess})
    need = N_BLOCKS * INNER_LEN + EMBARGO + MIN_TRAIN_SESSIONS - 1
    if len(blocks) < N_BLOCKS:
        reason = (f"only {len(cal)} labelled sessions up to the anchor {anchor.date()} (data start "
                  f"{_LABCAL[0].date()}): {N_BLOCKS} blocks of {INNER_LEN} sessions behind a {EMBARGO}-session embargo "
                  f"with >= {MIN_TRAIN_SESSIONS} training sessions need >= {need}; {len(blocks)} block(s) formable")
    elif min(i["train_sessions"] for i in info) < MIN_TRAIN_SESSIONS:
        reason = (f"the earliest block's training window holds {min(i['train_sessions'] for i in info)} sessions "
                  f"< {MIN_TRAIN_SESSIONS}")
    else:
        reason = None
    return {"year": year, "fold": spec["name"], "anchor": str(anchor.date()), "labelled_sessions_to_anchor": int(len(cal)),
            "blocks": info, "eligible": reason is None, "ineligible_reason": reason}


# ----------------------------------------------------------------------------- one inner fit
def _fit_job(args) -> dict:
    year, blk, setting, diag = args
    p = CACHE / str(year) / f"{setting}__{blk['name']}.json"
    if p.exists() and not diag:
        return json.loads(p.read_text())
    t0 = time.time()
    spec = {k: blk[k] for k in ("name", "train_end", "test_start", "test_end")}
    tr, te, n_before, n_purged = window_rows(_DF, _DD, _DATES, spec, TRAIN_SESSIONS)
    prep = Preprocessor("raw").fit(tr[_FEATS])
    est = model(setting)
    est.fit(prep.transform(tr[_FEATS]), tr[LABEL].to_numpy(np.float32))
    sc = est.predict_proba(prep.transform(te[_FEATS]))[:, 1]
    met = compute_metrics(te[LABEL].to_numpy(np.float32), sc, te[FWD].to_numpy(np.float32))
    out = {"year": year, "setting": setting, "params": SETTINGS[setting], "block": spec, "auc": met["auc"],
           "n_train": int(len(tr)), "n_train_before_purge": n_before, "n_train_purged_exit_ge_block_start": n_purged,
           "train_sessions": int(tr["date"].nunique()), "train_first": str(tr["date"].min().date()),
           "train_last": str(tr["date"].max().date()), "n_test": int(len(te)), "test_sessions": int(te["date"].nunique()),
           "seconds": round(time.time() - t0, 1)}
    if not p.exists():
        wjson(p, out)
    log(f"{year} {blk['name']} {setting}: auc={out['auc']:.4f} n_train={out['n_train']:,} "
        f"sessions={out['train_sessions']} purged={n_purged} ({out['seconds']}s)")
    if diag:
        out["tree_check"] = tree_check(est, len(_FEATS))
    return out


def tree_check(est, n_feat: int) -> dict:
    """What the fitted trees actually did: leaves per tree, smallest leaf, features used per tree."""
    def walk(n, feats, leaves):
        if "leaf_index" in n:
            leaves.append(n["leaf_count"])
            return
        feats.add(n["split_feature"])
        walk(n["left_child"], feats, leaves)
        walk(n["right_child"], feats, leaves)
    nl, ml_, nf = [], [], []
    for t in est.booster_.dump_model()["tree_info"]:
        f, lv = set(), []
        walk(t["tree_structure"], f, lv)
        nl.append(len(lv))
        ml_.append(min(lv))
        nf.append(len(f))
    return {"n_trees": len(nl), "max_leaves_per_tree": int(max(nl)), "min_leaf_count": int(min(ml_)),
            "max_features_per_tree": int(max(nf)), "n_features": n_feat,
            "feature_fraction_cap": int(np.ceil(est.get_params()["feature_fraction"] * n_feat))}


TREE_RULE = ("max leaves per tree <= num_leaves; max features used per tree <= ceil(feature_fraction x 52); smallest "
             "true leaf count >= 0.8 x min_data_in_leaf (LightGBM checks min_data_in_leaf on counts estimated from the "
             "hessians, so true counts of a logloss model sit slightly below it: the control itself shows 179 < 200)")


def tree_ok(c: dict, params: dict) -> bool:
    return bool(c["max_leaves_per_tree"] <= params["num_leaves"] and c["max_features_per_tree"] <= c["feature_fraction_cap"]
                and c["min_leaf_count"] >= 0.8 * params["min_data_in_leaf"])


# ----------------------------------------------------------------------------- stages
def smoke(a) -> None:
    splits = load()
    plan = year_plan(a.year, splits)
    blk = next(b for b in plan["blocks"] if b["name"] == a.block)
    sets = a.settings or list(SETTINGS)
    jobs = [(a.year, blk, s, True) for s in sets]
    jobs.sort(key=lambda j: -SETTINGS[j[2]]["num_leaves"])
    t0 = time.time()
    with mp.get_context("fork").Pool(a.n_jobs) as pool:
        res = pool.map(_fit_job, jobs, chunksize=1)
    wall = time.time() - t0
    fit_s = {r["setting"]: r["seconds"] for r in res}
    # runtime estimate for select: fit seconds scale with training rows; rows of every (year, block) window counted here
    rows = {}
    plans = {y: year_plan(y, splits) for y in YEARS}
    for y, pl in plans.items():
        if not pl["eligible"]:
            continue
        for b in pl["blocks"]:
            tr, te, _, _ = window_rows(_DF, _DD, _DATES, b, TRAIN_SESSIONS)
            rows[f"{y}|{b['name']}"] = int(len(tr))
    ref = res[0]["n_train"]
    per_block_s = sum(fit_s.values())
    total_cpu = sum(per_block_s * n / ref for n in rows.values())
    est_min = total_cpu / a.n_jobs / 60.0
    checks = {r["setting"]: {**r["tree_check"], "ok": tree_ok(r["tree_check"], r["params"])} for r in res}
    out = {"year": a.year, "block": blk, "plan": plan, "fits": [{k: v for k, v in r.items() if k != "tree_check"} for r in res],
           "tree_checks": checks, "tree_check_rule": TREE_RULE, "wall_seconds": round(wall, 1), "n_jobs": a.n_jobs,
           "select_estimate": {"inner_fits": len(rows) * len(SETTINGS), "train_rows_by_year_block": rows,
                               "method": "sum over every eligible (year, block) of the smoke block's 9 fit seconds x "
                                         "(window rows / smoke window rows), divided by the worker count",
                               "cpu_seconds": round(total_cpu), "wall_minutes_at_n_jobs": round(est_min, 1)},
           "plans": {str(y): pl for y, pl in plans.items()}}
    wjson(OUT / "smoke" / "smoke.json", out)
    log(f"smoke done: wall {wall:.0f}s; fit seconds {fit_s}; tree checks ok: {all(c['ok'] for c in checks.values())}; "
        f"select estimate {est_min:.0f} min at {a.n_jobs} workers")


def select(a) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pidf = OUT / "select.pid"
    pidf.write_text(str(os.getpid()))
    try:
        splits = load()
        plans = {y: year_plan(y, splits) for y in YEARS}
        for y, pl in plans.items():
            log(f"{y}: anchor {pl['anchor']}, {pl['labelled_sessions_to_anchor']} labelled sessions, "
                f"blocks {[(b['name'], b['test_start'], b['test_end'], b['train_sessions']) for b in pl['blocks']]}"
                + ("" if pl["eligible"] else f" -> incumbent: {pl['ineligible_reason']}"))
        jobs = [(y, b, s, False) for y, pl in plans.items() if pl["eligible"] for b in pl["blocks"] for s in SETTINGS]
        jobs.sort(key=lambda j: (-j[0], -SETTINGS[j[2]]["num_leaves"], j[1]["name"], j[2]))      # heavy first
        todo = [j for j in jobs if not (CACHE / str(j[0]) / f"{j[2]}__{j[1]['name']}.json").exists()]
        log(f"{len(jobs)} inner fits, {len(jobs) - len(todo)} cached, {len(todo)} to run on {a.n_jobs} workers")
        if todo:
            with mp.get_context("fork").Pool(a.n_jobs) as pool:
                for _ in pool.imap_unordered(_fit_job, todo, chunksize=1):
                    pass
        res = {}
        for y, b, s, _ in jobs:
            r = json.loads((CACHE / str(y) / f"{s}__{b['name']}.json").read_text())
            assert r["block"]["test_start"] == b["test_start"] and r["block"]["train_end"] == b["train_end"], (y, b, s)
            res.setdefault(y, {}).setdefault(s, {})[b["name"]] = r
        write_selection(plans, res)
        log("SELECT DONE")
    finally:
        pidf.unlink(missing_ok=True)


def write_selection(plans: dict, res: dict) -> None:
    years, per_year = {}, {}
    for y, pl in plans.items():
        if not pl["eligible"]:
            years[str(y)] = {"setting": INC, "params": SETTINGS[INC], "switched": False,
                             "basis": "incumbent kept: no eligible inner blocks", "reason": pl["ineligible_reason"]}
            per_year[str(y)] = {**pl, "inner": None, "selection": years[str(y)]}
            continue
        bn = [b["name"] for b in pl["blocks"]]
        aucs = {s: [res[y][s][n]["auc"] for n in bn] for s in SETTINGS}
        means = {s: float(np.mean(v)) for s, v in aucs.items()}
        best = max(SETTINGS, key=lambda s: means[s])                 # first maximum in grid order
        margin = means[best] - means[INC]
        switch = bool(best != INC and margin >= MARGIN)
        chosen = best if switch else INC
        years[str(y)] = {"setting": chosen, "params": SETTINGS[chosen], "switched": switch,
                         "basis": ("best setting beats the incumbent by >= %.3f" % MARGIN) if switch else
                                  ("incumbent is the best setting" if best == INC else
                                   "incumbent kept: best setting beats it by < %.3f" % MARGIN),
                         "best_setting": best, "best_mean_inner_auc": means[best],
                         "incumbent_mean_inner_auc": means[INC], "best_minus_incumbent": margin}
        per_year[str(y)] = {**pl, "inner": {
            "auc_by_setting_block": aucs, "mean_auc_by_setting": means,
            "rank_by_mean": sorted(SETTINGS, key=lambda s: -means[s]),
            "fits": {s: {n: {k: res[y][s][n][k] for k in ("auc", "n_train", "n_train_purged_exit_ge_block_start",
                                                          "train_sessions", "train_first", "train_last", "n_test",
                                                          "test_sessions", "seconds")} for n in bn} for s in SETTINGS}},
            "selection": years[str(y)]}
    sel = {"complete": True, "generated_at": pd.Timestamp.now().isoformat(timespec="seconds"),
           "generated_by": "ml/improve/tune.py select (seed 108)", "plan": "ml/IMPROVEMENT_PLAN_2.md Q7", "rule": RULE,
           "grid": SETTINGS, "incumbent": INC, "years": years}
    wjson(OUT / "selected_params.json", sel)
    old = json.loads((OUT / "tune.json").read_text()) if (OUT / "tune.json").exists() else {}
    tj = {"plan": "ml/IMPROVEMENT_PLAN_2.md Q7", "generated_at": sel["generated_at"],
          "design": {"dataset": rel(DATA), "features": len(_FEATS), "grid": SETTINGS, "incumbent": INC,
                     "fixed": {k: v for k, v in s5.make_model("all51", N_THREADS).get_params().items()
                               if k not in ("num_leaves", "min_data_in_leaf", "feature_fraction")},
                     "rule": RULE, "years": list(YEARS), "n_blocks": N_BLOCKS, "block_sessions": INNER_LEN,
                     "embargo_sessions": EMBARGO, "train_sessions": TRAIN_SESSIONS,
                     "min_train_sessions": MIN_TRAIN_SESSIONS, "margin": MARGIN,
                     "outer_test_data_used": "none: every inner row is dated <= the year's anchor (fold Y-01 train_end)"},
          "per_year": per_year,
          "summary": {"switched_years": [y for y, v in years.items() if v["switched"]],
                      "settings_by_year": {y: v["setting"] for y, v in years.items()},
                      "inner_fits": int(sum(len(v["inner"]["auc_by_setting_block"]) * N_BLOCKS
                                            for v in per_year.values() if v["inner"]))}}
    for k in ("audit_inner_exit", "outer"):
        if k in old:
            tj[k] = old[k]
    wjson(OUT / "tune.json", tj)
    write_md(tj)
    log("selected: " + "; ".join(f"{y}: {v['setting']}" + (" (switched)" if v["switched"] else "") for y, v in years.items()))


AUDIT_RULE = ("an inner block that ends at the anchor can hold rows whose label exit date (the ticker's row t+21) is on "
              "or after the first test session of the outer fold Y-01 (tickers with missing sessions); the outer fold "
              "purges such rows from its training, the inner scoring (every clean labelled row of the block, as the "
              "design defines it) keeps them.  Removing k_pos of P positives and k_neg of N negatives changes a block's "
              "AUC by at most k_pos/P + k_neg/N; a setting's 3-block mean by at most B = the mean of that over the 3 "
              "blocks; a difference of two settings' means by at most 2B.  A kept incumbent cannot flip if every "
              "(setting - incumbent) + 2B < margin; a switch cannot flip if (best - incumbent) - 2B >= margin and the "
              "best leads every other setting by more than 2B")


def _audit_job(args) -> dict:
    """Refit one setting on one block (same seed, data and threads as the selection fit) and score the block twice:
    every clean labelled row (must reproduce the cached AUC) and only the rows whose label exits before ts."""
    year, blk, setting, ts = args
    p = CACHE / str(year) / f"{setting}__{blk['name']}__audit.json"
    if p.exists():
        return json.loads(p.read_text())
    t0 = time.time()
    spec = {k: blk[k] for k in ("name", "train_end", "test_start", "test_end")}
    tr, te, _, _ = window_rows(_DF, _DD, _DATES, spec, TRAIN_SESSIONS)
    prep = Preprocessor("raw").fit(tr[_FEATS])
    est = model(setting)
    est.fit(prep.transform(tr[_FEATS]), tr[LABEL].to_numpy(np.float32))
    sc = est.predict_proba(prep.transform(te[_FEATS]))[:, 1]
    yv, fv = te[LABEL].to_numpy(np.float32), te[FWD].to_numpy(np.float32)
    keep = te["exit_date"].to_numpy(dtype="datetime64[ns]") < pd.Timestamp(ts).to_datetime64()
    out = {"year": year, "setting": setting, "block": spec, "outer_test_start": ts,
           "auc_all_rows": compute_metrics(yv, sc, fv)["auc"],
           "auc_exit_before_outer_test": compute_metrics(yv[keep], sc[keep], fv[keep])["auc"],
           "n_scored": int(len(te)), "n_kept": int(keep.sum()), "seconds": round(time.time() - t0, 1)}
    wjson(p, out)
    log(f"audit {year} {blk['name']} {setting}: all {out['auc_all_rows']:.6f} kept {out['auc_exit_before_outer_test']:.6f}")
    return out


def select_runtime(tj: dict) -> dict:
    """Measured cost of the selection: fit seconds from the cache, wall seconds of each run from select.log (a run
    stopped part-way resumes from the cache; the fits are deterministic, so resuming changes no number)."""
    secs = [json.loads(p.read_text())["seconds"] for p in CACHE.glob("*/*.json") if not p.name.endswith("__audit.json")]
    runs, cur = [], None
    lp = OUT / "select.log"
    for ln in (lp.read_text().splitlines() if lp.exists() else []):
        if "] frame:" in ln:
            cur = {"wall_seconds": 0, "fitted": 0, "cached_at_start": None}
            runs.append(cur)
        if cur is None or not ln.startswith("[tune +"):
            continue
        cur["wall_seconds"] = int(ln.split("+", 1)[1].split("s]", 1)[0])
        if " inner fits, " in ln:
            cur["cached_at_start"] = int(ln.split(" inner fits, ")[1].split(" cached")[0])
        if ": auc=" in ln:
            cur["fitted"] += 1
    return {"inner_fits": len(secs), "fit_seconds_sum": round(float(np.sum(secs))), "workers": 2, "runs": runs,
            "wall_minutes_total": round(sum(r["wall_seconds"] for r in runs) / 60, 1),
            "note": "more than one run means the selection was stopped (container restart) and resumed from the cache"}


def _choose(means: dict) -> tuple[str, bool]:
    best = max(SETTINGS, key=lambda s: means[s])
    switch = bool(best != INC and means[best] - means[INC] >= MARGIN)
    return (best if switch else INC), switch


def audit(a) -> None:
    """Post-selection audit (added after the selection ran; no choice is revised here).  Bounds the effect of the
    inner scoring rows whose label exits inside the outer test window; where the bound cannot rule out a different
    choice, refits the affected blocks and re-applies the rule without those rows."""
    splits = load()
    tj = json.loads((OUT / "tune.json").read_text())
    sel = json.loads((OUT / "selected_params.json").read_text())
    years = {}
    for y in YEARS:
        pl = year_plan(y, splits)
        if not pl["eligible"]:
            continue
        ts = pd.Timestamp(next(f for f in splits["folds"] if f["name"] == f"{y}-01")["test_start"])
        blocks, B = {}, 0.0
        for b in pl["blocks"]:
            _, te, _, _ = window_rows(_DF, _DD, _DATES, b, TRAIN_SESSIONS)
            yv = te[LABEL].to_numpy(float)
            hit = te["exit_date"].to_numpy(dtype="datetime64[ns]") >= ts.to_datetime64()
            P, N = int((yv == 1).sum()), int((yv == 0).sum())
            kp, kn = int((hit & (yv == 1)).sum()), int((hit & (yv == 0)).sum())
            bound = kp / P + kn / N
            B += bound / N_BLOCKS
            blocks[b["name"]] = {"n_scored": int(len(te)), "n_pos": P, "n_neg": N, "k_pos": kp, "k_neg": kn,
                                 "block_auc_bound": bound,
                                 "rows": [{"date": str(r.date.date()), "ticker": r.ticker, "exit_date": str(r.exit_date.date()),
                                           "label": int(getattr(r, LABEL))} for r in te[hit].itertuples(index=False)]
                                 if hit.any() else []}
        means = tj["per_year"][str(y)]["inner"]["mean_auc_by_setting"]
        s = sel["years"][str(y)]
        lead_inc = max(means[k] - means[INC] for k in SETTINGS if k != INC)
        if s["switched"]:
            best = s["setting"]
            gap = means[best] - max(means[k] for k in SETTINGS if k != best)
            safe = bool(means[best] - means[INC] - 2 * B >= MARGIN and gap > 2 * B)
        else:
            gap = None
            safe = bool(lead_inc + 2 * B < MARGIN)
        years[str(y)] = {"outer_test_start": str(ts.date()), "anchor": pl["anchor"], "blocks": blocks,
                         "n_rows": int(sum(v["k_pos"] + v["k_neg"] for v in blocks.values())),
                         "mean_auc_bound_B": B, "difference_bound_2B": 2 * B, "chosen": s["setting"],
                         "switched": s["switched"], "best_setting_minus_incumbent": lead_inc,
                         "chosen_lead_over_runner_up": gap, "choice_cannot_flip": safe, "exact": None}
    # exact check where the bound is not enough: refit every setting on the affected blocks
    jobs = [(int(y), b, st, v["outer_test_start"]) for y, v in years.items() if not v["choice_cannot_flip"]
            for b in year_plan(int(y), splits)["blocks"] if v["blocks"][b["name"]]["k_pos"] + v["blocks"][b["name"]]["k_neg"]
            for st in SETTINGS]
    if jobs:
        log(f"audit: {len(jobs)} refits for years {sorted({j[0] for j in jobs})} on {a.n_jobs} workers")
        with mp.get_context("fork").Pool(a.n_jobs) as pool:
            got = pool.map(_audit_job, jobs, chunksize=1)
        for y in sorted({j[0] for j in jobs}):
            v, inner = years[str(y)], tj["per_year"][str(y)]["inner"]
            rs = [r for r in got if r["year"] == y]
            repro = max(abs(r["auc_all_rows"] - inner["auc_by_setting_block"][r["setting"]][
                [b["name"] for b in tj["per_year"][str(y)]["blocks"]].index(r["block"]["name"])]) for r in rs)
            aucs = {st: list(inner["auc_by_setting_block"][st]) for st in SETTINGS}
            bn = [b["name"] for b in tj["per_year"][str(y)]["blocks"]]
            for r in rs:
                aucs[r["setting"]][bn.index(r["block"]["name"])] = r["auc_exit_before_outer_test"]
            means = {st: float(np.mean(x)) for st, x in aucs.items()}
            ch, sw = _choose(means)
            v["exact"] = {"blocks_refitted": sorted({r["block"]["name"] for r in rs}),
                          "refit_max_abs_diff_vs_cached_auc": repro, "mean_auc_by_setting_without_rows": means,
                          "best_without_rows": max(SETTINGS, key=lambda st: means[st]),
                          "best_minus_incumbent_without_rows": max(means[k] - means[INC] for k in SETTINGS if k != INC),
                          "chosen_without_rows": ch, "switched_without_rows": sw, "same_choice": ch == v["chosen"]}
    au = {"added": "after the selection ran (post-hoc audit; no choice was revised)", "rule": AUDIT_RULE,
          "exact_rule": "where the bound cannot rule out a flip, every setting is refitted on each affected block "
                        "(same seed, rows and threads; the refit must reproduce the cached AUC) and the block is "
                        "re-scored without the rows; the selection rule is then re-applied",
          "years": years, "n_rows_total": int(sum(v["n_rows"] for v in years.values())),
          "all_choices_unchanged": bool(all(v["choice_cannot_flip"] or (v["exact"] or {}).get("same_choice")
                                            for v in years.values()))}
    tj["audit_inner_exit"] = au
    tj["design"]["outer_test_data_used"] = (
        f"inner rows are dated <= the year's anchor (fold Y-01 train_end); {au['n_rows_total']} inner scoring rows "
        "(tickers with missing sessions) have labels that exit on or after the outer test start, and "
        "audit_inner_exit shows that no year's choice depends on them")
    tj["select_runtime"] = select_runtime(tj)
    wjson(OUT / "tune.json", tj)
    write_md(tj)
    log(f"audit: {au['n_rows_total']} inner scoring rows exit on/after the outer test start; every choice unchanged: "
        f"{au['all_choices_unchanged']}; " + ", ".join(
            f"{y}: {v['n_rows']} rows 2B={v['difference_bound_2B']:.5f} "
            + ("bound ok" if v["choice_cannot_flip"] else f"exact -> {v['exact']['chosen_without_rows']} "
               f"(same {v['exact']['same_choice']}, refit diff {v['exact']['refit_max_abs_diff_vs_cached_auc']:.1e})")
            for y, v in years.items()))


def report(a) -> None:
    tj = json.loads((OUT / "tune.json").read_text())
    cmp_ = json.loads((AB_TAG / "compare.json").read_text())
    pair = cmp_["pairs"]["q7_tuned - control"]
    outer = {"source": rel(AB_TAG / "compare.json"), "pair": pair,
             "models": {n: {k: cmp_["models"][n][k] for k in ("cv_auc_mean", "cv_mean_ci95", "cv_auc_std", "min_fold_auc",
                                                              "pct_folds_ge_050", "holdout_auc", "rank_ic_cv_mean",
                                                              "rank_ic_nw_t", "rank_ic_months_positive")}
                        for n in ("control", "q7_tuned")},
             "pass_mark": "primary: paired fold-level CV-mean AUC delta vs the control >= +0.003 with the 20-session "
                          "block-bootstrap 95% CI excluding zero (ml/IMPROVEMENT_PLAN_2.md section 1)",
             "PASS": bool(pair["pass_primary"])}
    bj = OUT / "books_q7.json"
    if bj.exists():
        b = json.loads(bj.read_text())
        outer["books"] = {"source": rel(bj), "n_trials": b["n_trials"], "books": {
            k: {"excess_ann_vs_ew_20bps": v["segments"]["combined"]["20bps"]["excess_ann_vs_ew"],
                "ir": v["segments"]["combined"]["20bps"]["ir"], "ir_ci95": v["segments"]["combined"]["20bps"]["ir_ci95"],
                "months_positive": f"{v['months_positive']}/{v['n_months']}",
                "turnover_per_rebalance": v["turnover_per_rebalance"],
                "name_level_excess_ann_vs_ew": v["segments"]["combined"]["name_level"]["excess_ann_vs_ew"],
                "dsr": v["dsr"][str(b["n_trials"])]["dsr"]} for k, v in b["books"].items()},
            "trial_books": ["q7_tuned|vol+size|top_decile", "q7_tuned|vol+size|liq_top_decile"]}
    tj["outer"] = outer
    wjson(OUT / "tune.json", tj)
    write_md(tj)
    log(f"report: q7_tuned - control delta {pair['delta_cv_mean']:+.4f} CI {pair['ci95']} -> "
        f"{'PASS' if outer['PASS'] else 'FAIL'}")


# ----------------------------------------------------------------------------- markdown
def write_md(tj: dict) -> None:
    d = tj["design"]
    L = ["# Q7: nested hyper-parameter tuning of the control LightGBM", "",
         "Plan: `ml/IMPROVEMENT_PLAN_2.md` Q7 (1 configuration, 2 books = 3 trials of N = 261). Code: `ml/improve/tune.py` "
         "(selection), `ml/improve/ab.py` config `q7_tuned` (outer run). Every number below is quoted from "
         "`ml/results/improve2/tune/tune.json` and `selected_params.json`.", "",
         "## Design (fixed before any result)", "",
         f"- Grid: the incumbent `{INC}` plus num_leaves {{31, 127}} x min_data_in_leaf {{200, 2000}} x feature_fraction "
         "{0.5, 0.8}; 9 settings, all with 300 trees, learning rate 0.05, bagging 0.8 every iteration, seed 108, the rest "
         "as `ml/scale5y.make_model(\"all51\")`. The fitted trees were checked to honour the three overrides (smoke).",
         f"- Rule: {d['rule']}.",
         "- Anchor for year Y: `train_end` of fold Y-01 in `ml/data_10y/splits.json`. The anchor is embargo-adjusted, so "
         "an inner row's label exits before the first test session of year Y unless its ticker has missing sessions "
         "(sentence corrected after the selection: such rows exist; the audit below counts them and shows that no "
         "choice depends on them).",
         "- The outer run (`python3 -m ml.improve.ab run --data ml/data_10y --tag 10y_p2 --configs q7_tuned`) trains each "
         "fold exactly like the control with its calendar year's setting; the holdout (test window from 2026-08-03) "
         "takes the 2026 setting.", "",
         "Deviations and interpretations (written before the selection ran):", "",
         "- 2018 has no inner blocks: the first row of the 10-year dataset is dated 2017-10-03 (the store's first year, "
         "from 2016-10, is feature warm-up), so only 41 labelled sessions precede the 2018 anchor (2017-11-29). The rule keeps the incumbent; the reason is "
         "recorded in `selected_params.json`.",
         "- 2019 and 2020 run with training windows shorter than 504 sessions (the data start truncates the rolling "
         "window); every block holds >= 120 training sessions, so both years are eligible (`plans` in `smoke/smoke.json`).",
         "- Ties in the best mean inner AUC are broken by grid order with the incumbent first (no tie is expected).", ""]
    sm = OUT / "smoke" / "smoke.json"
    if sm.exists():
        z = json.loads(sm.read_text())
        e = z["select_estimate"]
        L += ["## Smoke (one year, one block; `smoke/smoke.json`)", "",
              f"- Year {z['year']}, block {z['block']['name']} (test {z['block']['test_start']}..{z['block']['test_end']}, "
              f"inner train_end {z['block']['train_end']}), all 9 settings on {z['fits'][0]['n_train']:,} training rows, "
              f"{z['n_jobs']} workers, wall {z['wall_seconds']:.0f} s. Fit seconds: "
              + ", ".join(f"{f['setting']} {f['seconds']:.0f}" for f in z["fits"]) + ".",
              f"- Tree check ({z['tree_check_rule']}): "
              + ", ".join(f"{k} {'ok' if c['ok'] else 'FAILED'} (leaves <= {c['max_leaves_per_tree']}, smallest leaf "
                          f"{c['min_leaf_count']}, features/tree <= {c['max_features_per_tree']})"
                          for k, c in z["tree_checks"].items()) + ".",
              f"- Selection runtime estimate: {e['inner_fits']} inner fits, about {e['wall_minutes_at_n_jobs']:.0f} min at "
              f"{z['n_jobs']} workers ({e['method']}); the smoke's 9 fits are reused from the cache.", ""]
        if z.get("tree_check_note"):
            L[-1:-1] = [f"- Note: {z['tree_check_note']}."]
    rt = tj.get("select_runtime")
    if rt:
        L[-1:-1] = [f"- Measured (`tune.json` `select_runtime`): {rt['inner_fits']} inner fits, {rt['fit_seconds_sum']:,} fit "
                    f"seconds, {rt['wall_minutes_total']} min wall at {rt['workers']} workers over {len(rt['runs'])} run(s) ("
                    + "; ".join(f"{r['cached_at_start']} cached at start, {r['fitted']} fitted, {r['wall_seconds']} s"
                                for r in rt["runs"])
                    + ")" + (f"; {rt['note']}" if len(rt["runs"]) > 1 else "") + "."]
    hc = OUT / "harness_check.json"
    if hc.exists():
        h = json.loads(hc.read_text())
        a1, a2, q = h["ab_py_existing_behaviour"], h["ab_books_default_behaviour"], h["q7_tuned_equals_control_with_incumbent"]
        L += ["## Harness checks (`harness_check.json`)", "",
              f"- `ml/improve/ab.py` with `ae1_events`, `q7_tuned` and the `tuned` kind added: compare on tag v1 re-run "
              f"byte-identical to `{a1['reference']}`: {a1['byte_identical']} (sha256 {a1['reference_sha256'][:12]}...).",
              f"- `ml/improve/ab_books.py` with the phase-2 hooks off: the ten-year books re-run byte-identical to "
              f"`{a2['reference']}`: {a2['byte_identical']}.",
              f"- `q7_tuned` with every year set to the incumbent reproduces the control's fold 2026-07: AUC "
              f"{q['q7_tuned_auc']:.6f} vs {q['control_auc']:.6f}, scores bit-identical on {q['n_rows']:,} rows: "
              f"{q['scores_bit_identical']}.", ""]
    py = tj.get("per_year", {})
    if py:
        L += ["## Inner selection", "",
              "| Year | Anchor | Blocks (test windows) | Train sessions | Best setting | Best mean AUC | Incumbent mean AUC | "
              "Best - incumbent | Chosen |", "|---|---|---|---|---|---:|---:|---:|---|"]
        for y, v in py.items():
            s = v["selection"]
            if v["inner"] is None:
                L.append(f"| {y} | {v['anchor']} | none | | | | | | {s['setting']} (incumbent: {v['ineligible_reason']}) |")
                continue
            bl = ", ".join(f"{b['test_start']}..{b['test_end']}" for b in v["blocks"])
            ts = "/".join(str(b["train_sessions"]) for b in v["blocks"])
            L.append(f"| {y} | {v['anchor']} | {bl} | {ts} | {s['best_setting']} | {s['best_mean_inner_auc']:.4f} | "
                     f"{s['incumbent_mean_inner_auc']:.4f} | {s['best_minus_incumbent']:+.4f} | "
                     f"{s['setting']}{' (switched)' if s['switched'] else ''} |")
        L += ["", "Mean inner AUC by setting and year (3 blocks each):", "",
              "| Setting | " + " | ".join(y for y, v in py.items() if v["inner"]) + " |",
              "|---|" + "---:|" * sum(1 for v in py.values() if v["inner"])]
        for s in SETTINGS:
            L.append(f"| {s}{' (incumbent)' if s == INC else ''} | " + " | ".join(
                f"{v['inner']['mean_auc_by_setting'][s]:.4f}" for v in py.values() if v["inner"]) + " |")
        L += ["", f"Years that switched away from the incumbent: {tj['summary']['switched_years'] or 'none'}.", ""]
    au = tj.get("audit_inner_exit")
    if au:
        L += ["### Audit: inner scoring rows whose label exits inside the outer test window", "",
              f"Added {au['added']}; `tune.json` `audit_inner_exit`. Rule: {au['rule']}.", "",
              "| Year | Outer test start | Rows (block: k_pos + k_neg) | 2B | Best - incumbent | Chosen | Bound rules out a flip | "
              "Exact check without the rows |", "|---|---|---|---:|---:|---|---|---|"]
        for y, v in au["years"].items():
            rb = ", ".join(f"{n}: {b['k_pos']} + {b['k_neg']}" for n, b in v["blocks"].items() if b["k_pos"] + b["k_neg"])
            e = v.get("exact")
            ex = ("" if not e else
                  f"refit {', '.join(e['blocks_refitted'])} (max diff vs cached AUC {e['refit_max_abs_diff_vs_cached_auc']:.1e}): "
                  f"best {e['best_without_rows']}, best - incumbent {e['best_minus_incumbent_without_rows']:+.5f}, "
                  f"chosen {e['chosen_without_rows']}: {'same choice' if e['same_choice'] else 'DIFFERENT CHOICE'}")
            L.append(f"| {y} | {v['outer_test_start']} | {rb or 'none'} | {v['difference_bound_2B']:.5f} | "
                     f"{v['best_setting_minus_incumbent']:+.5f} | {v['chosen']} | {'yes' if v['choice_cannot_flip'] else 'no'} | "
                     f"{ex} |")
        L += ["", f"{au['n_rows_total']} rows in all ({au['exact_rule']}). Every year's choice is the same without them: "
                  f"{'yes' if au['all_choices_unchanged'] else 'NO (see the table)'}.", ""]
    o = tj.get("outer")
    if o:
        p, m = o["pair"], o["models"]
        L += ["## Outer walk-forward (103 folds + holdout)", "",
              f"Source: `{o['source']}`. Pass mark: {o['pass_mark']}.", "",
              "| Model | CV AUC ± sd | 95% CI | Folds >= 0.50 | Worst fold | Holdout AUC | Rank IC (NW t) |",
              "|---|---|---|---:|---:|---:|---|"]
        for n, x in m.items():
            L.append(f"| {n} | {x['cv_auc_mean']:.4f} ± {x['cv_auc_std']:.4f} | [{x['cv_mean_ci95'][0]:.4f}, "
                     f"{x['cv_mean_ci95'][1]:.4f}] | {100 * x['pct_folds_ge_050']:.0f}% | {x['min_fold_auc']:.3f} | "
                     f"{ab._f(x['holdout_auc'], '.4f')} | {x['rank_ic_cv_mean']:+.4f} ({x['rank_ic_nw_t']:.1f}) |")
        L += ["", f"q7_tuned - control: delta CV mean {p['delta_cv_mean']:+.4f}, 95% CI [{p['ci95'][0]:+.4f}, "
                  f"{p['ci95'][1]:+.4f}], folds won {p['folds_won']}, rank-IC delta {p['rank_ic_delta_mean']:+.4f} "
                  f"(NW t {p['rank_ic_delta_nw_t']:.1f}), holdout delta {ab._f(p['holdout_auc_delta'], '+.4f')}. "
                  f"**Primary mark: {'PASS' if o['PASS'] else 'FAIL'}.**", ""]
        if o.get("books"):
            L += [f"Books (P2 construction, 20 bps, DSR at N = {o['books']['n_trials']}; trial books: "
                  f"{', '.join(o['books']['trial_books'])}):", "",
                  "| Book | Excess vs EW | IR [95% CI] | Months beating EW | Turnover | Name-level excess | DSR |",
                  "|---|---:|---|---:|---:|---:|---:|"]
            for k, x in o["books"]["books"].items():
                L.append(f"| {k} | {100 * x['excess_ann_vs_ew_20bps']:+.1f}% | {x['ir']:+.2f} [{x['ir_ci95'][0]:+.2f}, "
                         f"{x['ir_ci95'][1]:+.2f}] | {x['months_positive']} | {100 * x['turnover_per_rebalance']:.0f}% | "
                         f"{100 * x['name_level_excess_ann_vs_ew']:+.1f}% | {x['dsr']:.3f} |")
            L.append("")
    else:
        L += ["## Outer walk-forward", "", "Not run yet. The selection is complete (`selected_params.json`); the outer run "
              "is `python3 -m ml.improve.ab run --data ml/data_10y --tag 10y_p2 --configs q7_tuned --n-jobs 2`, then "
              "compare, the books (`ab_books --configs control q7_tuned --out-dir ml/results/improve2/tune --out-name "
              "books_q7 --n-trials 261`) and `python3 -m ml.improve.tune report`.", ""]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "TUNE.md").write_text("\n".join(L) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["doc", "smoke", "select", "audit", "report"])
    ap.add_argument("--n-jobs", type=int, default=2)
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--block", default="blk00", help="smoke: inner block name (blk00 = the block ending at the anchor)")
    ap.add_argument("--settings", nargs="+", default=None, help="smoke: subset of settings")
    a = ap.parse_args()
    assert 1 <= a.n_jobs <= 2, "shared box: at most two worker processes"
    if a.stage == "doc":                      # design section only, before any result exists
        write_md({"design": {"rule": RULE}})
        return
    {"smoke": smoke, "select": select, "audit": audit, "report": report}[a.stage](a)


if __name__ == "__main__":
    main()

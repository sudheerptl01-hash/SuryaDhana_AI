#!/usr/bin/env python3
"""Checks of the family-E build (EVENTS.md section 6), written to ml/results/improve2/events/checks.json.

Steps (each runs in its own process under `all`, to keep memory low on the shared box):
  coverage   per year: bundles, records, symbols matched to dataset tickers, share of dataset rows with a release
             in the past 126 sessions; quarterly results coverage (R1-R3 alone, with R4); universe-rule equality;
             covered / uncovered file record counts; the rebuild equals the parquet
  pit        every raw zip re-parsed from scratch with the fixed vocabulary (per-file digests must equal
             events_raw), then 100 random dataset cells recomputed by an independent, loop-based implementation of
             the definitions from the re-parsed files dated <= t and prices dated <= t
  delete     the whole build re-run with every file and price after one month-end removed
  shift      the build on bundles up to T0, then with the later bundles appended (prices unchanged)
  abjoin     the parquet joined through ml.improve.ab.load_frame (the lead's A/B path)

Usage: python3 -m ml.events.checks all [--cells 100]      or one step: python3 -m ml.events.checks pit --cells 5
Seed 108; at most two worker processes.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from ml.events import classify as C
from ml.events import features as F
from ml.events import parse as P

ML = Path(__file__).resolve().parents[1]
OUT = ML / "results" / "improve2" / "events" / "checks.json"
SEED = 108
DELETE_FUTURE_MONTH_END = "2024-05-31"    # inside the Q4 results season: June files hold late outcomes
SHIFT_T0 = "2020-02-14"                    # inside the Q3 results season
RAW_COLS = ["file_date", "symbol", "company", "category_raw", "text", "text_len", "cat_method", "layout", "n_cont",
            "line_no", "bundle", "bm_date"]
T0 = time.time()


def log(msg: str) -> None:
    print(f"[events.checks +{time.time() - T0:6.0f}s] {msg}", flush=True)


def _jd(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp, np.datetime64)):
        return str(pd.Timestamp(o).date())
    return str(o)


def save(section: str, obj: dict) -> None:
    res = json.loads(OUT.read_text()) if OUT.exists() else {}
    res[section] = json.loads(json.dumps(obj, default=_jd))
    res["seed"] = SEED
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, indent=1))
    log(f"checks.json <- {section}")


def same(a, b, rtol: float = 1e-5, atol: float = 1e-6) -> np.ndarray:
    a, b = np.asarray(a, float), np.asarray(b, float)
    return (np.isnan(a) & np.isnan(b)) | (np.isfinite(a) & np.isfinite(b) & np.isclose(a, b, rtol=rtol, atol=atol))


def load_feats() -> pd.DataFrame:
    f = pd.read_parquet(F.OUT)
    f["date"] = pd.to_datetime(f["date"])
    return f


def compare_frames(a: pd.DataFrame, b: pd.DataFrame) -> dict:
    assert (a["ticker"].to_numpy() == b["ticker"].to_numpy()).all()
    assert (pd.to_datetime(a["date"]).to_numpy() == pd.to_datetime(b["date"]).to_numpy()).all()
    diff = {c: int((~same(a[c].to_numpy(), b[c].to_numpy(), rtol=0, atol=0)).sum()) for c in F.FEATURES}
    return {"rows_compared": int(len(a)), "cells_differing_by_column": diff, "unchanged": all(v == 0 for v in diff.values())}


# ----------------------------------------------------------------------------- coverage
def step_coverage() -> dict:
    keys = F.dataset_keys()
    prices = F.load_prices()
    ev, files = F.load_events()
    feats = load_feats()
    assert list(feats.columns) == ["date", "ticker"] + F.FEATURES
    assert len(feats) == len(keys) and (feats["ticker"].to_numpy() == keys["ticker"].to_numpy()).all()
    full, parts = F.build(ev, files, prices, keys, return_parts=True)
    res = {"parquet": {"rows": int(len(feats)), "columns": list(feats.columns), "row_set_and_order_equal_dataset": True,
                       "duplicate_keys": int(feats.duplicated(["date", "ticker"]).sum())},
           "rebuild_equals_parquet": compare_frames(full, feats)}
    del full
    ds = pd.read_parquet(F.DATASET, columns=["date", "ticker", "cs_rank_turnover"])
    ds["date"] = pd.to_datetime(ds["date"])
    pj = json.loads((P.OUT_DIR / "parse.json").read_text())
    import pyarrow.parquet as pq
    allrec = pq.read_table(F.RAW, columns=["file_date", "source"]).to_pandas()
    allrec = allrec[allrec["source"] == "an"]
    rec_year = allrec.groupby(allrec["file_date"].dt.year).size()
    cls = parts["cls"]
    an = ev[ev["source"] == "an"]
    nr = cls.loc[an.index, "non_routine"].to_numpy()
    dtick = set(ds["ticker"].unique())
    f = feats
    fyear = f["date"].dt.year
    by_year = {}
    for y in sorted(rec_year.index):
        e = an[an["file_date"].dt.year == y]
        fy = f[fyear == y]
        syms = set(e["symbol"].astype(str).unique())
        ssr = fy["sess_since_results"]
        by_year[int(y)] = {
            "bundles_parsed": pj["by_year"][str(y)]["bundles_parsed"],
            "records_all": int(rec_year[y]), "records_non_nav": int(len(e)),
            "records_non_routine": int(nr[(an["file_date"].dt.year == y).to_numpy()].sum()),
            "symbols_non_nav": len(syms), "symbols_matched_to_dataset_tickers": len(syms & dtick),
            "dataset_rows": int(len(fy)),
            "share_rows_release_in_past_126": (round(float((ssr < 126).mean()), 4) if len(fy) else None),
            "share_rows_release_in_past_126_of_known": (round(float((ssr < 126).sum() / ssr.notna().sum()), 4)
                                                       if len(fy) and ssr.notna().any() else None),
            "share_rows_sess_since_results_nan": (round(float(ssr.isna().mean()), 4) if len(fy) else None),
        }
    res["by_year"] = by_year
    rel, sess, rev = parts["releases"], parts["sess"], parts["results_events"]
    rel_q = pd.DataFrame({"ticker": rel["symbol"].astype(str).to_numpy(),
                          "q": pd.DatetimeIndex(sess[rel["s"].to_numpy()]).to_period("Q")}).drop_duplicates()
    an_obs = rev[rev["rule"].isin(["R1", "R2", "R3"])]
    an_q = pd.DataFrame({"ticker": an_obs["symbol"].astype(str).to_numpy(),
                         "q": pd.DatetimeIndex(sess[an_obs["s"].to_numpy()]).to_period("Q")}).drop_duplicates()
    ds["q"] = ds["date"].dt.to_period("Q")
    for nm, base in (("results_quarterly_liquid", ds[ds["cs_rank_turnover"] >= 0.67]), ("results_quarterly_all_dataset_names", ds)):
        b = base[["q", "ticker"]].drop_duplicates()
        m = b.merge(rel_q.assign(x=1), on=["q", "ticker"], how="left").merge(an_q.assign(z=1), on=["q", "ticker"], how="left")
        res[nm] = {str(q): {"names": int(len(g)), "share_with_release": round(float(g["x"].notna().mean()), 4),
                            "share_with_announcement_record_R1_R3": round(float(g["z"].notna().mean()), 4)}
                   for q, g in m.groupby("q")}
    res["release_sessions_total"] = int(len(rel))
    res["release_sessions_by_rules_observed"] = {k: int(v) for k, v in rel["rules"].value_counts().items()}
    res["results_observations_by_rule"] = {k: int(v) for k, v in rev["rule"].value_counts().items()}
    rs = rel.sort_values(["symbol", "s"])
    dd = rs.groupby("symbol")["s"].diff().dropna().to_numpy()
    edges = [6, 11, 21, 41, 51, 56, 61, 66, 71, 91, 127, 10 ** 6]
    res["release_spacing_sessions_histogram"] = {"edges": edges, "counts": np.histogram(dd, bins=edges)[0].tolist(),
                                                 "median": float(np.median(dd))}
    u = prices[prices["universe"] & (prices["date"] >= ds["date"].min())][["date", "ticker"]]
    mm = u.merge(ds[["date", "ticker"]], on=["date", "ticker"], how="outer", indicator=True)
    res["universe_rule_vs_dataset_rows"] = {k: int(v) for k, v in mm["_merge"].value_counts().items()}
    cov = parts["coverage"]
    covered = cov[~cov["uncovered"]]
    res["files"] = {"covered_sessions": int(len(covered)), "uncovered_sessions": int(cov["uncovered"].sum()),
                    "gap_sessions_full_runs": int(cov["gap"].sum()),
                    "min_company_records_covered": int(covered["company_records"].min()),
                    "max_company_records_uncovered_with_file": int(cov.loc[cov["uncovered"] & cov["has_file"], "company_records"].max()),
                    "sessions_without_records": [str(d.date()) for d in cov.loc[~cov["has_file"], "session"]]}
    save("coverage", res)
    return res


# ----------------------------------------------------------------------------- re-parse + point-in-time cells
def _norm_frame(df: pd.DataFrame) -> pd.DataFrame:
    o = pd.DataFrame(index=df.index)
    for c in RAW_COLS:
        x = df[c]
        if c in ("file_date", "bm_date"):
            v = pd.to_datetime(x).to_numpy("datetime64[ns]")
            iv = v.astype("int64")
            iv[np.isnat(v)] = -1
            o[c] = iv
        elif c in ("text_len", "n_cont", "line_no"):
            o[c] = pd.to_numeric(x).astype("int64").to_numpy()
        else:
            o[c] = x.astype(object).where(x.notna(), "").astype(str).to_numpy()
    return o


def _row_hash(df: pd.DataFrame) -> np.ndarray:
    return pd.util.hash_pandas_object(_norm_frame(df), index=False).to_numpy(np.uint64)


_VOCAB = None
_WANT: set[str] = set()


def _pit_job(args):
    b, m, d = args
    rec = P.parse_file(b, m, d, _VOCAB)
    if not len(rec):
        return str(d), np.uint64(0), 0, [], rec
    rec["file_date"] = pd.to_datetime(rec["file_date"])
    rec["bm_date"] = pd.to_datetime(rec["bm_date"])
    rec["source"] = np.where(rec["layout"] == "bm", "bm", "an")
    dig = np.uint64(_row_hash(rec).sum(dtype=np.uint64))
    nn = rec[(rec["source"] == "an") & ~rec["category_raw"].fillna("").str.startswith(F.NAV)]
    keep = rec[rec["symbol"].astype(str).isin(_WANT) & ~rec["category_raw"].fillna("").str.startswith(F.NAV)]
    return str(d), dig, len(rec), nn["symbol"].astype(str).tolist(), keep


def stored_digests() -> dict[str, tuple[np.uint64, int]]:
    import pyarrow.parquet as pq
    pf = pq.ParquetFile(F.RAW)
    acc: dict[str, list] = {}
    for b in pf.iter_batches(batch_size=250_000, columns=RAW_COLS):
        df = b.to_pandas()
        h = _row_hash(df)
        fd = pd.to_datetime(df["file_date"]).dt.strftime("%Y-%m-%d").to_numpy()
        u, inv = np.unique(fd, return_inverse=True)
        s = np.zeros(len(u), np.uint64)
        np.add.at(s, inv, h)
        n = np.bincount(inv, minlength=len(u))
        for i, d in enumerate(u):
            a = acc.setdefault(d, [np.uint64(0), 0])
            a[0] = np.uint64((int(a[0]) + int(s[i])) % (1 << 64))
            a[1] += int(n[i])
    return {d: (v[0], v[1]) for d, v in acc.items()}


def recompute_cell(t: pd.Timestamp, k: str, recs: pd.DataFrame, company_records: pd.Series, file_dates: set,
                   prices: pd.DataFrame) -> dict:
    """Family E for (t, k) by direct definition, from symbol k's re-parsed records of files dated <= t, the company
    record count of every file dated <= t, and prices dated <= t."""
    p = prices[prices["date"] <= t]
    sess = np.sort(p["date"].unique()).astype("datetime64[ns]")
    S = len(sess)
    ti = S - 1
    assert sess[ti] == np.datetime64(t)
    unc = np.array([(d not in file_dates) or int(company_records.get(d, 0)) < F.COVER_MIN_RECORDS
                    for d in pd.DatetimeIndex(sess)])
    gap = np.zeros(S, bool)
    i = 0
    while i < S:                                   # runs of uncovered sessions among sessions <= t
        if unc[i]:
            j = i
            while j + 1 < S and unc[j + 1]:
                j += 1
            if j - i + 1 >= F.GAP_MIN_RUN:
                gap[i:j + 1] = True
            i = j + 1
        else:
            i += 1

    def gap_in(lo: int, hi: int) -> bool:
        return lo < 0 or bool(gap[max(lo, 0):hi + 1].any())

    e = recs[recs["file_date"] <= t].reset_index(drop=True)
    cls = C.classify(e) if len(e) else None
    rels = []
    if len(e):
        rel = C.release_sessions(C.results_events(e, cls, sess))
        rels = sorted(int(x) for x in rel["s"])
    s = max(rels) if rels else None
    d = ti - s if s is not None else None
    out = {}
    if s is not None and d < F.CAP:
        out["sess_since_results"] = float(d) if not gap_in(s + 1, ti) else np.nan
    else:
        out["sess_since_results"] = float(F.CAP) if not gap_in(ti - F.CAP + 1, ti) else np.nan
    for W, name in ((5, "results_last_5"), (20, "results_last_20")):
        out[name] = 1.0 if (s is not None and d <= W - 1) else (np.nan if gap_in(ti - W + 1, ti) else 0.0)
    out["ear_3d"], out["ear_vol_z"] = np.nan, np.nan
    if s is not None and 1 <= d <= F.EAR_WINDOW - 1 and s >= 1 and not gap_in(s + 1, ti):
        dm, d0, dp = sess[s - 1], sess[s], sess[s + 1]
        pk = p[p["ticker"] == k].set_index("date")
        if dm in pk.index and dp in pk.index:
            r_k = pk.loc[dp, "close"] / pk.loc[dm, "close"] - 1.0
            q = p[p["date"] <= d0]
            last20 = q.groupby("ticker", sort=False).tail(20)
            med = last20.groupby("ticker")["turnover"].agg(lambda x: x.median() if x.notna().sum() >= 10 else np.nan)
            on_s = q[q["date"] == d0].set_index("ticker")
            members = on_s.index[((on_s["close_unadj"] >= F.MIN_PRICE).to_numpy()
                                  & (med.reindex(on_s.index).to_numpy() >= F.MIN_MED_TURNOVER))]
            cm = p[p["date"] == dm].set_index("ticker")["close"]
            cp = p[p["date"] == dp].set_index("ticker")["close"]
            rr = (cp.reindex(members) / cm.reindex(members) - 1.0).dropna()
            out["ear_3d"] = float(r_k - rr.mean())
            v = pk["volume"] * pk["close_unadj"] / pk["close"]
            if s - F.VOL_WINDOW >= 0 and d0 in v.index:
                win = v[(v.index >= sess[s - F.VOL_WINDOW]) & (v.index < d0)]
                if len(win) >= F.VOL_MIN_OBS and win.std(ddof=1) > 0:
                    out["ear_vol_z"] = float((v.loc[d0] - win.mean()) / win.std(ddof=1))
    if len(e):
        an = (e["source"] == "an").to_numpy()
        ss = np.searchsorted(sess, e["file_date"].to_numpy(dtype="datetime64[ns]"))
    else:
        an, ss = np.zeros(0, bool), np.zeros(0, int)

    def in_win(W):
        return an & (ss >= ti - W + 1) & (ss <= ti)

    def flag(c):
        return cls[c].to_numpy(bool) if cls is not None else np.zeros(0, bool)

    w = in_win(20) & flag("non_routine")
    n_ann = len({(int(a), str(b), str(c)[:300]) for a, b, c in zip(ss[w], e["category_raw"].fillna("")[w], e["text"].fillna("")[w])}) if w.any() else 0
    out["ann_count_20"] = np.nan if gap_in(ti - 19, ti) else float(n_ann)
    for W, c, name in ((20, "rating", "rating_20"), (60, "mgmt_change", "mgmt_change_60"), (20, "orders", "orders_20")):
        n = len(set(ss[in_win(W) & flag(c)].tolist()))
        out[name] = np.nan if gap_in(ti - W + 1, ti) else float(n)
    out["insolvency_60"] = 1.0 if (in_win(60) & flag("insolvency")).any() else (np.nan if gap_in(ti - 59, ti) else 0.0)
    return out


def step_pit(n_cells: int, workers: int = 2) -> dict:
    global _VOCAB, _WANT
    feats = load_feats()
    rng = np.random.default_rng(SEED)
    pick = np.sort(rng.choice(len(feats), size=n_cells, replace=False))
    cells = feats.iloc[pick].reset_index(drop=True)
    _WANT = set(cells["ticker"].astype(str))
    _VOCAB = P.load_vocabulary()
    sel, _ = P.select(P.inventory())
    jobs = list(zip(sel["bundle"], sel["member"], sel["member_date"]))
    with mp.get_context("fork").Pool(workers) as pool:
        out = pool.map(_pit_job, jobs, chunksize=8)
    log("re-parsed every raw zip")
    stored = stored_digests()
    mism = [d for d, dig, n, _, _ in out if n and (stored.get(d, (None, 0))[0] != dig or stored[d][1] != n)]
    reparse = {"files_reparsed": len(out), "records_reparsed": int(sum(n for _, _, n, _, _ in out)),
               "records_stored": int(sum(v[1] for v in stored.values())),
               "files_with_digest_mismatch": mism, "equal": (not mism) and sum(n for _, _, n, _, _ in out) == sum(v[1] for v in stored.values()),
               "method": "each zip re-parsed independently with ml/events/vocabulary.json; per-file sum of row hashes over "
                         + ", ".join(RAW_COLS) + " compared with events_raw.parquet"}
    log(f"re-parse equal: {reparse['equal']}")
    prices = F.load_prices()
    first_seen = prices.groupby("ticker", sort=False)["date"].min()
    cr = {}
    for d, _, n, syms, _ in out:
        if not n:
            continue
        dd = pd.Timestamp(d)
        cr[dd] = int(sum(1 for x in syms if x in first_seen.index and first_seen[x] <= dd))
    company_records = pd.Series(cr)
    file_dates = {pd.Timestamp(d) for d, _, n, _, _ in out if n}
    recs = pd.concat([o[4] for o in out if len(o[4])], ignore_index=True)
    by_sym = {s: g.reset_index(drop=True) for s, g in recs.groupby(recs["symbol"].astype(str), sort=False)}
    rows, mismatch = [], {c: 0 for c in F.FEATURES}
    empty = recs.iloc[:0]
    for j, r in cells.iterrows():
        t, k = pd.Timestamp(r["date"]), str(r["ticker"])
        got = recompute_cell(t, k, by_sym.get(k, empty), company_records, file_dates, prices)
        ok = {c: bool(same([r[c]], [got[c]])[0]) for c in F.FEATURES}
        for c in F.FEATURES:
            mismatch[c] += int(not ok[c])
        rows.append({"date": str(t.date()), "ticker": k, "all_equal": all(ok.values()),
                     "parquet": {c: _jd(r[c]) for c in F.FEATURES}, "recomputed": {c: _jd(got[c]) for c in F.FEATURES}})
        if (j + 1) % 20 == 0:
            log(f"pit cells {j + 1}/{n_cells}: mismatching so far {sum(not x['all_equal'] for x in rows)}")
    pit = {"n_cells": n_cells, "seed": SEED, "cells_all_equal": int(sum(x["all_equal"] for x in rows)),
           "mismatches_by_column": mismatch,
           "non_nan_cells_by_column": {c: int(sum(x["parquet"][c] is not None for x in rows)) for c in F.FEATURES},
           "method": "independent loop implementation of EVENTS.md section 4 (checks.recompute_cell) on the raw zips "
                     "re-parsed with the fixed vocabulary, restricted to files dated <= t and prices dated <= t; the "
                     "classification rules re-run on that restricted set; tolerance rtol 1e-5",
           "cells": rows}
    save("reparse", reparse)
    save("pit_cells", pit)
    return pit


# ----------------------------------------------------------------------------- truncation tests
def step_delete() -> dict:
    T = pd.Timestamp(DELETE_FUTURE_MONTH_END)
    keys = F.dataset_keys()
    feats = load_feats()
    ev, files = F.load_events(until=T)
    p_t = F.load_prices(until=T)
    k_t = keys[keys["date"] <= T].reset_index(drop=True)
    out = F.build(ev, files, p_t, k_t)
    ref = feats[feats["date"] <= T].reset_index(drop=True)
    res = compare_frames(out, ref)
    mon = (ref["date"] >= T.replace(day=1)).to_numpy()
    res.update(month=T.strftime("%Y-%m"), month_rows=int(mon.sum()),
               month_cells_differing_by_column={c: int((~same(out.loc[mon, c], ref.loc[mon, c], 0, 0)).sum()) for c in F.FEATURES},
               files_kept=int(len(files)), price_sessions_kept=int(p_t["date"].nunique()),
               method="every file and every price row dated after the month-end removed, the whole pipeline "
                      "(classification, results rules, coverage, features) re-run, rows <= month-end compared exactly")
    save("delete_future", res)
    return res


def step_shift() -> dict:
    T0_ = pd.Timestamp(SHIFT_T0)
    keys = F.dataset_keys()
    feats = load_feats()
    prices = F.load_prices()
    ev, files = F.load_events(until=T0_)
    out = F.build(ev, files, prices, keys)
    m = (keys["date"] <= T0_).to_numpy()
    res = compare_frames(out[m].reset_index(drop=True), feats[m].reset_index(drop=True))
    res.update(T0=SHIFT_T0, files_up_to_T0=int(len(files)),
               method="build 1: bundles dated <= T0 with all prices; build 2: the full parquet (every later bundle "
                      "appended); rows dated <= T0 compared exactly")
    save("shift", res)
    return res


def step_abjoin() -> dict:
    from ml.improve import ab
    df, _, _ = ab.load_frame(ML / "data_10y", F.OUT, None, False)
    cols = [c for c in F.FEATURES if c in df.columns]
    res = {"rows": int(len(df)), "columns_joined": cols, "all_ten_present": len(cols) == len(F.FEATURES),
           "coverage": {c: round(float(df[c].notna().mean()), 4) for c in cols},
           "path": "ml.improve.ab.load_frame(ml/data_10y, extra=ml/data_ext/event_features_10y.parquet): merge on date, "
                   "ticker, validate one_to_one, row count unchanged"}
    save("ab_join", res)
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["all", "coverage", "pit", "delete", "shift", "abjoin"])
    ap.add_argument("--cells", type=int, default=100)
    a = ap.parse_args()
    if a.step == "all":
        for st in ("coverage", "pit", "delete", "shift", "abjoin"):
            cmd = [sys.executable, "-m", "ml.events.checks", st] + (["--cells", str(a.cells)] if st == "pit" else [])
            log("running " + " ".join(cmd[2:]))
            subprocess.run(cmd, check=True, cwd=str(ML.parent))
        return
    {"coverage": step_coverage, "pit": lambda: step_pit(a.cells), "delete": step_delete, "shift": step_shift,
     "abjoin": step_abjoin}[a.step]()


if __name__ == "__main__":
    main()

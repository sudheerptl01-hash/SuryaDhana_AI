#!/usr/bin/env python3
"""The paper book's daily job: one idempotent command (ml/paper/RUNBOOK.md).

    OMP_NUM_THREADS=2 python3 -I ml/paper/job.py                       # the daily run
    OMP_NUM_THREADS=2 python3 -I ml/paper/job.py --prove-idempotency   # a second run that records the ledger hashes
    OMP_NUM_THREADS=2 python3 -I ml/paper/job.py --no-ingest           # no network, no store write
    OMP_NUM_THREADS=2 python3 -I ml/paper/job.py --accept-unverified-write "REASON"   # RUNBOOK section 5 only
    OMP_NUM_THREADS=2 python3 -I ml/paper/job.py --no-ingest --extension-backfill-proof  # SPEC.md amendment 10, once

A run stops before scoring while a store write that failed its verification is unresolved (ingest.json): until a later
verified write re-checks its sessions (a re-ingest after restoring the backup, or `ml/paper/ingest.py
--rebuild-features REASON`) or an operator records an acceptance with --accept-unverified-write; the ingest holds new
sessions meanwhile.

Steps: (1) ingest new sessions (ml/paper/ingest.py; the only writer of nse_market.duckdb in phase 2);
(2) rebuild the scoring frame when the store changed (ml/paper/frame.py) and the consistency proof;
(3) for every signal date from inception not yet in the ledger: the month's models (trained at the month's first
session if absent, ml/paper/models.py), scores, baskets, rows appended to ml/paper/ledger/signals.csv;
(4) marks of every book from the first entry open to the last session (ml/paper/book.py), new sessions appended to
marks.csv, earlier sessions recomputed and compared with the ledger; (5) monitors as of every new signal date
appended to monitors.csv; (6) state.json; (7) ml/results/improve2/paper/{paper.json, PAPER.md}.
Nothing already in the ledger is ever rewritten; a run with no new session appends nothing.

Extension 1 (SPEC.md amendment 10): the expanding-window challenger.  Steps (3)-(5) also cover the books
challenger_expanding and capacity_expanding: the month's expanding-window model (trained in a child process on the whole
frame when absent), its per-date scores (ml/paper/state/scores_expanding/), their rows in the same ledger files in
the order of config.SPEC_EXT['ledger_order'] (the frozen books' rows are computed by the unchanged code and are
byte-identical with or without the extension), and the extension's monitors after the frozen ones.  Every run checks
that the bytes the ledger files had before it are still their prefix (``append_only`` in the run record).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import argparse  # noqa: E402
import json  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
from datetime import datetime  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from ml.paper import book as B  # noqa: E402
from ml.paper import frame as F  # noqa: E402
from ml.paper import ingest as I  # noqa: E402
from ml.paper import models as M  # noqa: E402
from ml.paper import monitors as MON  # noqa: E402
from ml.paper import report as R  # noqa: E402
from ml.paper.common import (LEDGER_FILES, MARKS_COLS, MONITORS_COLS, RUNS_FILE, SIGNALS_COLS, STATE_JSON,  # noqa: E402
                             append_rows, fnum, ledger_hashes, log, python_info, read_csv_rows, sha256_file, wjson)
from ml.paper.config import (ALL_BOOK_ORDER, BOOK_ORDER, EXT_BACKFILL_THROUGH, EXT_BOOK_ORDER,  # noqa: E402
                             EXT_FIRST_SIGNAL_DATE, EXT_NAME, EXT_REGISTERED_UTC, INCEPTION_SIGNAL_DATE, MODELS_META_DIR,
                             RESEARCH_END, RESULTS_DIR, SPEC_EXT_HASH, SPEC_HASH, STATE_DIR, check_code_matches_spec,
                             check_extension_inputs, ext_block)

STATE_DIR_STEPS = STATE_DIR / "steps"

IDEM_JSON = RESULTS_DIR / "idempotency.json"
EXT_BACKFILL_JSON = RESULTS_DIR / "extension_backfill.json"
REPO = Path(__file__).resolve().parents[2]
EXTENSION = True      # extension 1 (SPEC.md amendment 10); prove.py switches it off for the frozen-only regeneration


def _step(step: str, args_json: str) -> None:
    """Child-process body of the two memory-heavy steps (the box is shared; a child returns its memory)."""
    args = json.loads(args_json)
    if step == "ingest":
        r = I.run()
        res = {k: r.get(k) for k in ("accepted", "store_changed", "seconds")}
        res["decisions"] = [(d["date"], d["decision"]) for d in r.get("decisions", [])]
    elif step == "frame":
        res = F.build_frame(force=args.get("force", False))
        res = {"rebuilt": res.get("rebuilt"), "rows": res.get("rows"), "date_max": res.get("date_max")}
        if res["rebuilt"] or not F.CONSISTENCY_JSON.exists():
            c = F.consistency_proof()
            res["consistency_research_end_unexplained"] = c["research_end_rows"]["cells_differing_unexplained"]
    elif step == "train_expanding":
        # the expanding window needs every row from the dataset's first session: the whole frame, in a child
        df, feats, _splits, dates, darr = load_frame(None)
        res = {"month": args["month"], "frame_rows": int(len(df)), "frame_first_date": str(dates[0].date())}
        if not M.REPRO_EXT_JSON.exists():
            r = M.reproduce_research_holdout_expanding(df, feats, dates, darr)
            res["reproduction_identical"] = r["identical"]
        meta = M.ensure_month(df, feats, dates, darr, args["month"], variant=EXT_NAME)
        res["training_rows"] = meta["training_window"]["rows"]
    else:
        raise ValueError(step)
    wjson(STATE_DIR_STEPS / f"step_{step}.json", res)


def run_child(step: str, **kw) -> dict:
    out = STATE_DIR_STEPS / f"step_{step}.json"
    out.unlink(missing_ok=True)
    code = (f"import sys; sys.path.insert(0, {str(REPO)!r}); from ml.paper import job; "
            f"job._step({step!r}, {json.dumps(json.dumps(kw))})")
    r = subprocess.run([sys.executable, "-I", "-c", code], cwd=str(REPO), env=os.environ.copy())
    if r.returncode != 0:
        raise SystemExit(f"step {step} failed with exit code {r.returncode}")
    return json.loads(out.read_text())


FRAME_LOOKBACK_DAYS = 1000      # > 504 + 22 sessions before the earliest month the run may train or score


def load_frame(lo: pd.Timestamp | None):
    """ml.improve.ab.load_frame's columns, order and sort on the frame, read from ``lo`` on (memory: the box is
    shared; ``None``: the whole frame, for the expanding window).  Every training window must start after ``lo``;
    models.train_month checks it."""
    import pyarrow.parquet as pq
    from ml.improve.ab import CLEAN, FWD, LABEL, SUFF
    manifest = json.loads((F.FRAME_DIR / "manifest.json").read_text())
    splits = json.loads((F.FRAME_DIR / "splits.json").read_text())
    feats = list(manifest["features"])
    avail = set(pq.read_schema(F.FRAME).names)
    want = ["date", "ticker"] + feats + [LABEL, FWD, CLEAN, "y_raw_20d", "y_rank_20d", "cs_rank_turnover"]
    want += [c for c in SUFF + ["exit_date"] if c in avail]
    want = [c for c in dict.fromkeys(want) if c in avail]
    df = pd.read_parquet(F.FRAME, columns=want, filters=[("date", ">=", pd.Timestamp(lo))] if lo is not None else None)
    df["date"] = pd.to_datetime(df["date"])
    for c in SUFF:
        if c not in feats:
            feats.append(c)
    df["exit_date"] = pd.to_datetime(df["exit_date"]).to_numpy()
    df = df.sort_values(["date", "ticker"], kind="stable").reset_index(drop=True)
    dates = pd.DatetimeIndex(np.sort(df["date"].unique()))
    darr = df["date"].to_numpy(dtype="datetime64[ns]")
    return df, feats, splits, dates, darr


def frame_lower_bound() -> pd.Timestamp:
    """Earliest date the run needs: the first month without signals in the ledger (or inception), and the
    research holdout fold when its reproduction check has not been run yet."""
    led = read_csv_rows(LEDGER_FILES["signals"])
    last = max((r["signal_date"] for r in led), default=None)
    start = pd.Timestamp(last).replace(day=1) if last else pd.Timestamp(INCEPTION_SIGNAL_DATE).replace(day=1)
    if not M.REPRO_JSON.exists():
        start = min(start, pd.Timestamp(json.loads((M.DATA_10Y / "splits.json").read_text())["holdout"]["test_start"]))
    return start - pd.Timedelta(days=FRAME_LOOKBACK_DAYS)


def prev_month(m: str) -> str:
    return (pd.Timestamp(m + "-01") - pd.Timedelta(days=1)).strftime("%Y-%m")


def ensure_models(df, feats, dates, darr, month: str) -> M.MonthModels:
    M.ensure_month(df, feats, dates, darr, month)
    pm = prev_month(month)
    if not (MODELS_META_DIR / f"{pm}.json").exists():
        # the logistic sign-flip monitor compares each month's logistic fit with the previous month's
        M.train_month(df, feats, dates, darr, pm, members=("logistic",), role="monitor only (logistic sign-flip baseline)")
    return M.MonthModels(month)


def ensure_models_ext(month: str) -> M.MonthModels:
    """Extension 1: the month's expanding-window model; trained (or retrained from a lost state and verified against
    the committed metadata) in a child process that reads the whole frame."""
    if not (M.state_complete(month, EXT_NAME) and M.REPRO_EXT_JSON.exists()):
        r = run_child("train_expanding", month=month)
        log(f"expanding-window model {month}: {r}", "job")
    return M.MonthModels(month, EXT_NAME)


def check_append_order(path: Path, keyfun, pending: list[dict], what: str) -> None:
    """Rows are appended in ledger order (config.SPEC_EXT['ledger_order']): every pending row sorts after the last
    ledger row."""
    if not pending:
        return
    led = read_csv_rows(path)
    if led and keyfun(pending[0]) <= keyfun(led[-1]):
        raise SystemExit(f"{what}: a pending row ({keyfun(pending[0])}) sorts before the ledger's last row "
                         f"({keyfun(led[-1])}); the ledger is append-only, see RUNBOOK 'a missed session' and section 8")


def _sig_order(r: dict) -> tuple:
    return B.signal_key(r)[:3]


def process_signals(df, feats, dates, darr, verify: bool) -> dict:
    led = read_csv_rows(LEDGER_FILES["signals"])
    done = sorted({r["signal_date"] for r in led if r["book"] in BOOK_ORDER})
    todo = [d for d in dates if d >= pd.Timestamp(INCEPTION_SIGNAL_DATE) and str(d.date()) not in set(done)]
    if done and todo and str(todo[0].date()) <= done[-1]:
        raise SystemExit(f"signal date {todo[0].date()} precedes the ledger's last signal date {done[-1]}: the ledger "
                         "is append-only; see RUNBOOK 'a missed session'")
    done_x = sorted({r["signal_date"] for r in led if r["book"] in EXT_BOOK_ORDER}) if EXTENSION else []
    todo_x = [d for d in dates if d >= pd.Timestamp(EXT_FIRST_SIGNAL_DATE) and str(d.date()) not in set(done_x)] \
        if EXTENSION else []
    B.SCORES_DIR.mkdir(parents=True, exist_ok=True)
    if EXTENSION:
        B.SCORES_EXT_DIR.mkdir(parents=True, exist_ok=True)
    cache: dict = {}
    cache_x: dict = {}
    out = {"appended_signal_dates": [], "rows_appended": 0, "regenerated_score_files": []}
    if EXTENSION:
        out.update(appended_signal_dates_expanding=[], rows_appended_expanding=0, regenerated_score_files_expanding=[])
    for ds_ in done:                     # lost state: regenerate per-date scores and check them against the ledger
        if (B.SCORES_DIR / f"scores_{ds_}.parquet").exists():
            continue
        d = pd.Timestamp(ds_)
        month = d.strftime("%Y-%m")
        if month not in cache:
            cache[month] = ensure_models(df, feats, dates, darr, month)
        sd = B.score_date(df[df["date"] == d], cache[month])
        again = [{k: str(r[k]) for k in SIGNALS_COLS} for r in B.signal_rows(sd, B.baskets(sd))]
        have = [{k: r[k] for k in SIGNALS_COLS} for r in led if r["signal_date"] == ds_ and r["book"] in BOOK_ORDER]
        if again != have:
            raise SystemExit(f"regenerated baskets of {ds_} differ from the ledger; see RUNBOOK 'lost state'")
        sd.to_parquet(B.SCORES_DIR / f"scores_{ds_}.parquet", index=False)
        out["regenerated_score_files"].append(ds_)
    for ds_ in done_x:                   # the same for the extension's score files
        if (B.SCORES_EXT_DIR / f"scores_{ds_}.parquet").exists():
            continue
        d = pd.Timestamp(ds_)
        month = d.strftime("%Y-%m")
        if month not in cache_x:
            cache_x[month] = ensure_models_ext(month)
        sd = B.score_date_ext(df[df["date"] == d], cache_x[month])
        again = [{k: str(r[k]) for k in SIGNALS_COLS} for r in B.signal_rows_ext(sd, B.baskets_ext(sd))]
        have = [{k: r[k] for k in SIGNALS_COLS} for r in led if r["signal_date"] == ds_ and r["book"] in EXT_BOOK_ORDER]
        if again != have:
            raise SystemExit(f"regenerated extension baskets of {ds_} differ from the ledger; see RUNBOOK 'lost state'")
        sd.to_parquet(B.SCORES_EXT_DIR / f"scores_{ds_}.parquet", index=False)
        out["regenerated_score_files_expanding"].append(ds_)
    pending: list[dict] = []
    for d in sorted(set(todo) | set(todo_x)):
        month = d.strftime("%Y-%m")
        rows = df[df["date"] == d]
        if d in set(todo):
            if month not in cache:
                cache[month] = ensure_models(df, feats, dates, darr, month)
            mm = cache[month]
            sd = B.score_date(rows, mm)
            sd.to_parquet(B.SCORES_DIR / f"scores_{d.date()}.parquet", index=False)
            bk = B.baskets(sd)
            pending += B.signal_rows(sd, bk)
            out["appended_signal_dates"].append(str(d.date()))
            log(f"signals {d.date()}: model {month}, universe {len(sd)}, baskets "
                + ", ".join(f"{b} {len(bk[b])}" for b in BOOK_ORDER), "job")
        if d in set(todo_x):
            if month not in cache_x:
                cache_x[month] = ensure_models_ext(month)
            sx = B.score_date_ext(rows, cache_x[month])
            sx.to_parquet(B.SCORES_EXT_DIR / f"scores_{d.date()}.parquet", index=False)
            bx = B.baskets_ext(sx)
            pending += B.signal_rows_ext(sx, bx)
            out["appended_signal_dates_expanding"].append(str(d.date()))
            log(f"signals {d.date()} (extension): expanding model {month}, universe {len(sx)}, baskets "
                + ", ".join(f"{b} {len(bx[b])}" for b in EXT_BOOK_ORDER), "job")
    pending.sort(key=B.signal_key)
    check_append_order(LEDGER_FILES["signals"], _sig_order, pending, "signals")
    n = append_rows(LEDGER_FILES["signals"], SIGNALS_COLS, pending)
    out["rows_appended"] = sum(1 for r in pending if r["book"] in BOOK_ORDER)
    if EXTENSION:
        out["rows_appended_expanding"] = n - out["rows_appended"]
    if verify:
        led = read_csv_rows(LEDGER_FILES["signals"])
        last = max((r["signal_date"] for r in led if r["book"] in BOOK_ORDER), default=None)
        if last:
            d = pd.Timestamp(last)
            mm = M.MonthModels(d.strftime("%Y-%m"))
            sd = B.score_date(df[df["date"] == d], mm)
            again = B.signal_rows(sd, B.baskets(sd))
            have = [{k: r[k] for k in SIGNALS_COLS} for r in led if r["signal_date"] == last and r["book"] in BOOK_ORDER]
            again = [{k: str(r[k]) for k in SIGNALS_COLS} for r in again]
            out["recomputed_signal_date"] = last
            out["recomputed_signals_equal_ledger"] = have == again
            old = pd.read_parquet(B.SCORES_DIR / f"scores_{last}.parquet")
            out["recomputed_scores_max_abs_diff"] = float(np.max(np.abs(
                old[["lgbm", "lambdarank", "catboost", "ensemble"]].to_numpy(float)
                - sd[["lgbm", "lambdarank", "catboost", "ensemble"]].to_numpy(float))))
        lx = max((r["signal_date"] for r in led if r["book"] in EXT_BOOK_ORDER), default=None) if EXTENSION else None
        if lx:
            d = pd.Timestamp(lx)
            sx = B.score_date_ext(df[df["date"] == d], M.MonthModels(d.strftime("%Y-%m"), EXT_NAME))
            again = [{k: str(r[k]) for k in SIGNALS_COLS} for r in B.signal_rows_ext(sx, B.baskets_ext(sx))]
            have = [{k: r[k] for k in SIGNALS_COLS} for r in led if r["signal_date"] == lx and r["book"] in EXT_BOOK_ORDER]
            out["recomputed_signal_date_expanding"] = lx
            out["recomputed_signals_equal_ledger_expanding"] = have == again
            old = pd.read_parquet(B.SCORES_EXT_DIR / f"scores_{lx}.parquet")
            out["recomputed_scores_max_abs_diff_expanding"] = float(np.max(np.abs(
                old[B.EXT_SCORE_COLS].to_numpy(float) - sx[B.EXT_SCORE_COLS].to_numpy(float))))
    return out


def process_marks() -> tuple[pd.DataFrame, dict, dict]:
    from ml.paper.config import COST_PRICE_START
    fp = pd.read_parquet(I.FEAT_LIVE, columns=["date", "ticker", "open", "high", "low", "close", "turnover"],
                         filters=[("date", ">=", pd.Timestamp(COST_PRICE_START))])
    fp["date"] = pd.to_datetime(fp["date"])
    sessions = pd.DatetimeIndex(sorted(fp["date"].unique()))
    books = ALL_BOOK_ORDER if EXTENSION else BOOK_ORDER
    mk, info = B.compute_marks(LEDGER_FILES["signals"], fp, sessions, books)
    led = read_csv_rows(LEDGER_FILES["marks"])
    rows = B.marks_ledger_rows(mk)
    key = lambda r: (r["session"], r["book"])  # noqa: E731
    have = [{k: r[k] for k in MARKS_COLS} for r in led if r["book"] in books]
    have_keys = {key(r) for r in have}
    by_key = {key(r): r for r in rows}
    old = [by_key.get(key(r)) for r in have]
    new = sorted([r for r in rows if key(r) not in have_keys], key=B.mark_key)
    chk = {"recomputed_sessions": len({r["session"] for r in have}), "recomputed_marks_equal_ledger": None}
    if have:
        if all(o is not None for o in old):
            a = pd.DataFrame(have)[MARKS_COLS]
            b = pd.DataFrame(old)[MARKS_COLS]
            num = [c for c in MARKS_COLS if c not in ("session", "book")]
            d = np.abs(a[num].replace("", np.nan).astype(float).to_numpy() - b[num].replace("", np.nan).astype(float).to_numpy())
            chk["recomputed_marks_max_abs_diff"] = float(np.nanmax(d)) if d.size else 0.0
            chk["recomputed_marks_equal_ledger"] = bool((a.to_numpy() == b.to_numpy()).all())
        else:
            chk["recomputed_marks_equal_ledger"] = False
            chk["note"] = "recomputed (session, book) keys differ from the ledger"
    check_append_order(LEDGER_FILES["marks"], lambda r: B.mark_key(r), new, "marks")
    n = append_rows(LEDGER_FILES["marks"], MARKS_COLS, new)
    chk["rows_appended"] = sum(1 for r in new if r["book"] in BOOK_ORDER)
    if EXTENSION:
        chk["rows_appended_expanding"] = n - chk["rows_appended"]
    allm = pd.DataFrame(have + new)
    if len(allm):
        for c in MARKS_COLS[2:]:
            allm[c] = allm[c].replace("", np.nan).astype(float)
        allm["_o"] = allm["book"].map({b: i for i, b in enumerate(ALL_BOOK_ORDER)})
        allm = allm.sort_values(["session", "_o"], kind="stable").drop(columns="_o").reset_index(drop=True)
    return allm, info, chk


def _mon_order(r: dict) -> tuple:
    g = EXT_NAME if MON.is_ext_row(r) else "frozen"
    return (ext_block(r["session"], g), r["session"], int(g == EXT_NAME))


def process_monitors(df, feats, marks: pd.DataFrame) -> dict:
    led = read_csv_rows(LEDGER_FILES["monitors"])
    done = {r["session"] for r in led if not MON.is_ext_row(r)}
    sig_rows = read_csv_rows(LEDGER_FILES["signals"])
    sig = sorted({r["signal_date"] for r in sig_rows if r["book"] in BOOK_ORDER})
    todo = [d for d in sig if d not in done]
    if done and todo and todo[0] <= max(done):
        raise SystemExit("monitor session precedes the ledger's last monitor session")
    done_x = {r["session"] for r in led if MON.is_ext_row(r)}
    sig_x = sorted({r["signal_date"] for r in sig_rows if r["book"] in EXT_BOOK_ORDER}) if EXTENSION else []
    todo_x = [d for d in sig_x if d not in done_x]
    out = {"rows_appended": 0, "sessions": todo}
    if EXTENSION:
        out.update(rows_appended_expanding=0, sessions_expanding=todo_x)
    if not todo and not todo_x:
        return out
    scores = {d: pd.read_parquet(B.SCORES_DIR / f"scores_{d}.parquet") for d in sig}
    for v in scores.values():
        v["date"] = pd.to_datetime(v["date"])
    scores_x = {d: pd.read_parquet(B.SCORES_EXT_DIR / f"scores_{d}.parquet") for d in sig_x}
    for v in scores_x.values():
        v["date"] = pd.to_datetime(v["date"])
    ing = json.loads(I.INGEST_JSON.read_text()) if I.INGEST_JSON.exists() else {}
    cal = I.calendar_live()
    sessions = pd.DatetimeIndex(np.sort(df["date"].unique()))
    ctx = MON.Context(df, feats, sessions, scores, marks, ing, cal)
    pending: list[tuple] = []
    for d in sorted(set(todo) | set(todo_x)):
        ctx.scores = {k: v for k, v in scores.items() if k <= d}
        if d in todo:
            rows = MON.evaluate(ctx, pd.Timestamp(d))
            pending += [((ext_block(d, "frozen"), d, 0, i), r) for i, r in enumerate(rows)]
            log(f"monitors {d}: " + "; ".join(f"{r['monitor']}[{r['scope']}]={r['value']} {r['status']}" for r in rows), "job")
        if d in todo_x:
            ctx.scores_ext = {k: v for k, v in scores_x.items() if k <= d}
            rows = MON.evaluate_ext(ctx, pd.Timestamp(d))
            pending += [((ext_block(d, EXT_NAME), d, 1, i), r) for i, r in enumerate(rows)]
            log(f"monitors {d} (extension): " + "; ".join(f"{r['monitor']}[{r['scope']}]={r['value']} {r['status']}"
                                                          for r in rows), "job")
    pending.sort(key=lambda kr: kr[0])
    rows = [r for _, r in pending]
    check_append_order(LEDGER_FILES["monitors"], _mon_order, rows, "monitors")
    n = append_rows(LEDGER_FILES["monitors"], MONITORS_COLS, rows)
    out["rows_appended"] = sum(1 for k, _ in pending if k[2] == 0)
    if EXTENSION:
        out["rows_appended_expanding"] = n - out["rows_appended"]
    return out


def write_state(store: dict) -> dict:
    """state.json: the frozen books' fields as before amendment 10 (rows of the four frozen books only), and the
    extension's under "extension"; without that key the file is what the job writes with the extension off."""
    sig_all = read_csv_rows(LEDGER_FILES["signals"])
    mk_all = read_csv_rows(LEDGER_FILES["marks"])
    mo_all = read_csv_rows(LEDGER_FILES["monitors"])
    sig = [r for r in sig_all if r["book"] in BOOK_ORDER]
    mk = [r for r in mk_all if r["book"] in BOOK_ORDER]
    mo = [r for r in mo_all if not MON.is_ext_row(r)]
    models = {}
    for p in sorted(MODELS_META_DIR.glob("*.json")):
        m = json.loads(p.read_text())
        models[m["month"]] = {"role": m["role"], "members": m["members"], "trained_as_of": m["trained_as_of"],
                              "training_frame_sha256": m["training_frame_sha256"], "files_sha256": m["files_sha256"],
                              "metadata": f"ml/paper/models/{p.name}"}
    cal = I.calendar_live()
    sig_dates = sorted({r["signal_date"] for r in sig})
    st = {"spec_hash": SPEC_HASH, "research_end": RESEARCH_END, "inception_signal_date": INCEPTION_SIGNAL_DATE,
          "last_store_session": store["last_session"], "store_rows": {"equity_eod": store["equity_eod_rows"],
                                                                     "equity_features": store["equity_features_rows"]},
          "last_signal_date": sig_dates[-1] if sig_dates else None, "signal_dates": len(sig_dates),
          "last_mark_session": max((r["session"] for r in mk), default=None),
          "last_monitor_session": max((r["session"] for r in mo), default=None),
          "models": models, "closures_recorded": sorted(cal.get("closures", {})),
          "ledger_rows": {"signals": len(sig), "marks": len(mk), "monitors": len(mo)},
          "scores_sha256": {d: sha256_file(B.SCORES_DIR / f"scores_{d}.parquet") for d in sig_dates
                            if (B.SCORES_DIR / f"scores_{d}.parquet").exists()},
          "inputs": {"ca_feed_live_sha256": sha256_file(I.CA_FEED_LIVE) if I.CA_FEED_LIVE.exists() else None,
                     "etf_list_live_sha256": sha256_file(I.ETF_LIVE) if I.ETF_LIVE.exists() else None}}
    if EXTENSION:
        xm = {}
        for p in sorted((MODELS_META_DIR / EXT_NAME).glob("*.json")):
            m = json.loads(p.read_text())
            xm[m["month"]] = {"role": m["role"], "members": m["members"], "trained_as_of": m["trained_as_of"],
                              "training_rows": m["training_window"]["rows"],
                              "training_frame_sha256": m["training_frame_sha256"], "files_sha256": m["files_sha256"],
                              "metadata": f"ml/paper/models/{EXT_NAME}/{p.name}"}
        xd = sorted({r["signal_date"] for r in sig_all if r["book"] in EXT_BOOK_ORDER})
        st["extension"] = {"name": EXT_NAME, "spec_hash": SPEC_EXT_HASH, "extends_spec_hash": SPEC_HASH,
                           "registered_utc": EXT_REGISTERED_UTC, "amendment": "ml/paper/SPEC.md section 5 (amendment 10)",
                           "books": EXT_BOOK_ORDER, "backfill_through": EXT_BACKFILL_THROUGH,
                           "last_signal_date": xd[-1] if xd else None, "signal_dates": len(xd), "models": xm,
                           "ledger_rows": {"signals": sum(1 for r in sig_all if r["book"] in EXT_BOOK_ORDER),
                                           "marks": sum(1 for r in mk_all if r["book"] in EXT_BOOK_ORDER),
                                           "monitors": sum(1 for r in mo_all if MON.is_ext_row(r))},
                           "last_mark_session": max((r["session"] for r in mk_all if r["book"] in EXT_BOOK_ORDER),
                                                    default=None),
                           "scores_sha256": {d: sha256_file(B.SCORES_EXT_DIR / f"scores_{d}.parquet") for d in xd
                                             if (B.SCORES_EXT_DIR / f"scores_{d}.parquet").exists()}}
    wjson(STATE_JSON, st)
    return st


def latest_baskets() -> dict:
    sig = read_csv_rows(LEDGER_FILES["signals"])
    if not sig:
        return {}
    last = max(r["signal_date"] for r in sig)
    return {"signal_date": last, **{b: {"size": sum(1 for r in sig if r["signal_date"] == last and r["book"] == b)}
                                    for b in (ALL_BOOK_ORDER if EXTENSION else BOOK_ORDER)}}


def file_sizes() -> dict:
    from ml.paper.common import STATE_JSON as SJ
    return {k: (p.stat().st_size if p.exists() else 0) for k, p in {**LEDGER_FILES, "state": SJ}.items()}


def prefix_sha256(path: Path, n: int) -> str:
    import hashlib
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read(n)).hexdigest()


def append_only_proof(before: dict, sizes: dict) -> dict:
    """The bytes each ledger CSV had before the run must be the file's prefix after it (rows only appended)."""
    out = {}
    for k, p in LEDGER_FILES.items():
        if before.get(k) is None:
            out[k] = {"existed_before": False}
            continue
        n = sizes[k]
        out[k] = {"bytes_before": n, "bytes_after": p.stat().st_size, "sha256_before": before[k],
                  "sha256_of_first_bytes_after": prefix_sha256(p, n),
                  "existing_rows_unchanged": prefix_sha256(p, n) == before[k]}
    return out


def rows_by_book_list(rows: list[dict]) -> dict:
    out: dict = {}
    for r in rows:
        out[r["book"]] = out.get(r["book"], 0) + 1
    return out


def run(a) -> dict:
    t0 = time.time()
    check_code_matches_spec()
    if EXTENSION:
        check_extension_inputs()
    before = ledger_hashes()
    sizes = file_sizes()
    lines_before = {k: len(read_csv_rows(p)) for k, p in LEDGER_FILES.items()}
    rec = {"started": datetime.now().isoformat(timespec="seconds"), "args": vars(a), "ledger_before": before}
    if not a.no_ingest:
        rec["ingest"] = run_child("ingest")
    if a.accept_unverified_write:
        rec["operator_acceptance"] = I.accept_unverified_write(a.accept_unverified_write)
    bad = I.unverified_write()
    if bad is not None:
        failed = [k for k, v in ((bad.get("write") or {}).get("checks") or {}).items() if not v]
        raise SystemExit(f"the store write of {bad.get('accepted') or bad.get('kind')} failed verification {failed} "
                         "(ml/results/improve2/paper/ingest.json; backup kept): nothing is scored on an unverified store. "
                         "See ml/paper/RUNBOOK.md section 5 (restore the backup and re-run, repair with ml/paper/ingest.py "
                         "--rebuild-features REASON, or accept the write with --accept-unverified-write REASON).")
    fr = run_child("frame", force=bool(a.force_frame))
    rec["frame_rebuilt"] = fr.get("rebuilt")
    df, feats, splits, dates, darr = load_frame(frame_lower_bound())
    if not M.REPRO_JSON.exists():
        M.reproduce_research_holdout(df, feats, dates, darr)
    rec["signals"] = process_signals(df, feats, dates, darr, verify=True)
    marks, minfo, mchk = process_marks()
    rec["marks"] = mchk
    rec["monitors"] = process_monitors(df, feats, marks)
    store = I.store_summary()
    state = write_state(store)
    after = ledger_hashes()
    rec["ledger_after"] = after
    rec["ledger_unchanged"] = before == after
    rec["append_only"] = append_only_proof(before, sizes)
    if not all(v.get("existing_rows_unchanged", True) for v in rec["append_only"].values()):
        raise SystemExit(f"a ledger file's earlier bytes changed in this run: {rec['append_only']}")
    if getattr(a, "extension_backfill_proof", False):
        sig_after = read_csv_rows(LEDGER_FILES["signals"])
        mk_after = read_csv_rows(LEDGER_FILES["marks"])
        mo_after = read_csv_rows(LEDGER_FILES["monitors"])
        appended = {"signals": sig_after[lines_before["signals"]:], "marks": mk_after[lines_before["marks"]:],
                    "monitors": mo_after[lines_before["monitors"]:]}
        wjson(EXT_BACKFILL_JSON, {
            "note": "ml/paper/job.py --no-ingest --extension-backfill-proof: the run that added extension 1 (SPEC.md "
                    "amendment 10) and backfilled its books from inception; no ingest, no store write",
            "extension_spec_hash": SPEC_EXT_HASH, "spec_hash_frozen_books": SPEC_HASH,
            "rows_before": lines_before,
            "rows_appended": {k: len(v) for k, v in appended.items()},
            "appended_rows_by_book": {"signals": rows_by_book_list(appended["signals"]),
                                      "marks": rows_by_book_list(appended["marks"]),
                                      "monitors": {"extension": sum(1 for r in appended["monitors"] if MON.is_ext_row(r)),
                                                   "frozen": sum(1 for r in appended["monitors"]
                                                                 if not MON.is_ext_row(r))}},
            "appended_signal_dates": sorted({r["signal_date"] for r in appended["signals"]}),
            "appended_mark_sessions": sorted({r["session"] for r in appended["marks"]}),
            "existing_rows": rec["append_only"],
            "existing_rows_unchanged": all(v.get("existing_rows_unchanged", False) for v in rec["append_only"].values()),
            "only_extension_rows_appended": (all(r["book"] in EXT_BOOK_ORDER for r in appended["signals"] + appended["marks"])
                                             and all(MON.is_ext_row(r) for r in appended["monitors"])),
            "expanding_models": {p.stem: {k: json.loads(p.read_text())[k] for k in ("trained_as_of", "spec", "training_window",
                                                                                      "files_sha256", "fit_seconds")}
                                 for p in sorted((MODELS_META_DIR / EXT_NAME).glob("*.json"))},
            "ingest_run": not a.no_ingest, "frame_rebuilt": fr.get("rebuilt")})
    if a.prove_idempotency:
        idem = {"note": "ml/paper/job.py --prove-idempotency, run after the first full run on the same store",
                "before": before, "after": after, "identical": before == after,
                "rows_appended": sum(x.get(k, 0) for x in (rec["signals"], mchk, rec["monitors"])
                                     for k in ("rows_appended", "rows_appended_expanding")),
                "recomputed_signal_date": rec["signals"].get("recomputed_signal_date"),
                "recomputed_signals_equal_ledger": rec["signals"].get("recomputed_signals_equal_ledger"),
                "recomputed_scores_max_abs_diff": rec["signals"].get("recomputed_scores_max_abs_diff"),
                "recomputed_marks_equal_ledger": mchk.get("recomputed_marks_equal_ledger"),
                "recomputed_marks_max_abs_diff": mchk.get("recomputed_marks_max_abs_diff"),
                "recomputed_signal_date_expanding": rec["signals"].get("recomputed_signal_date_expanding"),
                "recomputed_signals_equal_ledger_expanding": rec["signals"].get("recomputed_signals_equal_ledger_expanding"),
                "recomputed_scores_max_abs_diff_expanding": rec["signals"].get("recomputed_scores_max_abs_diff_expanding"),
                "frame_rebuilt_in_this_run": fr.get("rebuilt"),
                "ingest_decisions_in_this_run": rec.get("ingest", {}).get("decisions")}
        wjson(IDEM_JSON, idem)
    ext = None
    if EXTENSION:
        ext = {"inception": B.inception_summary(LEDGER_FILES["signals"], books=EXT_BOOK_ORDER),
               "overlap": B.basket_overlap(LEDGER_FILES["signals"]),
               "score_agreement": B.score_agreement(sorted(state.get("extension", {}).get("scores_sha256", {}))),
               "dsr": MON.dsr_paper(marks, EXT_BOOK_ORDER, MON.EXT_N_TRIALS_DSR)}
    R.build(state, marks, B.inception_summary(LEDGER_FILES["signals"]), latest_baskets(), MON.dsr_paper(marks), minfo,
            ext)
    rec["seconds"] = round(time.time() - t0, 1)
    rec["python"] = python_info()
    RUNS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(RUNS_FILE, "a") as fh:
        fh.write(json.dumps(rec, default=str) + "\n")
    log(f"job done in {rec['seconds']} s; ledger unchanged {rec['ledger_unchanged']}; signals +{rec['signals']['rows_appended']}, "
        f"marks +{mchk['rows_appended']}, monitors +{rec['monitors']['rows_appended']}"
        + (f"; extension: signals +{rec['signals'].get('rows_appended_expanding')}, marks "
           f"+{mchk.get('rows_appended_expanding')}, monitors +{rec['monitors'].get('rows_appended_expanding')}"
           if EXTENSION else ""), "job")
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-ingest", action="store_true", help="skip the archive and the store write")
    ap.add_argument("--force-frame", action="store_true", help="rebuild the scoring frame even if the store is unchanged")
    ap.add_argument("--prove-idempotency", action="store_true",
                    help="record ledger hashes before/after in ml/results/improve2/paper/idempotency.json")
    ap.add_argument("--extension-backfill-proof", action="store_true",
                    help="record the rows appended by this run and the hashes of the earlier rows in "
                         "ml/results/improve2/paper/extension_backfill.json (SPEC.md amendment 10)")
    ap.add_argument("--accept-unverified-write", metavar="REASON", default=None,
                    help="record an operator's acceptance of the latest store write whose verification failed "
                         "(RUNBOOK section 5); without it the job stops on such a write")
    a = ap.parse_args(argv)
    rec = run(a)
    print(json.dumps({k: rec[k] for k in ("ingest", "frame_rebuilt", "signals", "marks", "monitors", "ledger_unchanged",
                                          "seconds") if k in rec}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

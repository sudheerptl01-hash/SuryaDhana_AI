#!/usr/bin/env python3
"""The paper book's daily job: one idempotent command (ml/paper/RUNBOOK.md).

    OMP_NUM_THREADS=2 python3 -I ml/paper/job.py                       # the daily run
    OMP_NUM_THREADS=2 python3 -I ml/paper/job.py --prove-idempotency   # a second run that records the ledger hashes
    OMP_NUM_THREADS=2 python3 -I ml/paper/job.py --no-ingest           # no network, no store write

Steps: (1) ingest new sessions (ml/paper/ingest.py; the only writer of nse_market.duckdb in phase 2);
(2) rebuild the scoring frame when the store changed (ml/paper/frame.py) and the consistency proof;
(3) for every signal date from inception not yet in the ledger: the month's models (trained at the month's first
session if absent, ml/paper/models.py), scores, baskets, rows appended to ml/paper/ledger/signals.csv;
(4) marks of every book from the first entry open to the last session (ml/paper/book.py), new sessions appended to
marks.csv, earlier sessions recomputed and compared with the ledger; (5) monitors as of every new signal date
appended to monitors.csv; (6) state.json; (7) ml/results/improve2/paper/{paper.json, PAPER.md}.
Nothing already in the ledger is ever rewritten; a run with no new session appends nothing.
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
from ml.paper.config import (BOOK_ORDER, INCEPTION_SIGNAL_DATE, MODELS_META_DIR, RESEARCH_END, RESULTS_DIR,  # noqa: E402
                             SPEC_HASH, STATE_DIR, check_code_matches_spec)

STATE_DIR_STEPS = STATE_DIR / "steps"

IDEM_JSON = RESULTS_DIR / "idempotency.json"
REPO = Path(__file__).resolve().parents[2]


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


def load_frame(lo: pd.Timestamp):
    """ml.improve.ab.load_frame's columns, order and sort on the frame, read from ``lo`` on (memory: the box is
    shared).  Every training window must start after ``lo``; models.train_month checks it."""
    import pyarrow.parquet as pq
    from ml.improve.ab import CLEAN, FWD, LABEL, SUFF
    manifest = json.loads((F.FRAME_DIR / "manifest.json").read_text())
    splits = json.loads((F.FRAME_DIR / "splits.json").read_text())
    feats = list(manifest["features"])
    avail = set(pq.read_schema(F.FRAME).names)
    want = ["date", "ticker"] + feats + [LABEL, FWD, CLEAN, "y_raw_20d", "y_rank_20d", "cs_rank_turnover"]
    want += [c for c in SUFF + ["exit_date"] if c in avail]
    want = [c for c in dict.fromkeys(want) if c in avail]
    df = pd.read_parquet(F.FRAME, columns=want, filters=[("date", ">=", pd.Timestamp(lo))])
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


def process_signals(df, feats, dates, darr, verify: bool) -> dict:
    led = read_csv_rows(LEDGER_FILES["signals"])
    done = sorted({r["signal_date"] for r in led})
    todo = [d for d in dates if d >= pd.Timestamp(INCEPTION_SIGNAL_DATE) and str(d.date()) not in set(done)]
    if done and todo and str(todo[0].date()) <= done[-1]:
        raise SystemExit(f"signal date {todo[0].date()} precedes the ledger's last signal date {done[-1]}: the ledger "
                         "is append-only; see RUNBOOK 'a missed session'")
    B.SCORES_DIR.mkdir(parents=True, exist_ok=True)
    cache: dict = {}
    out = {"appended_signal_dates": [], "rows_appended": 0, "regenerated_score_files": []}
    for ds_ in done:                     # lost state: regenerate per-date scores and check them against the ledger
        if (B.SCORES_DIR / f"scores_{ds_}.parquet").exists():
            continue
        d = pd.Timestamp(ds_)
        month = d.strftime("%Y-%m")
        if month not in cache:
            cache[month] = ensure_models(df, feats, dates, darr, month)
        sd = B.score_date(df[df["date"] == d], cache[month])
        again = [{k: str(r[k]) for k in SIGNALS_COLS} for r in B.signal_rows(sd, B.baskets(sd))]
        have = [{k: r[k] for k in SIGNALS_COLS} for r in led if r["signal_date"] == ds_]
        if again != have:
            raise SystemExit(f"regenerated baskets of {ds_} differ from the ledger; see RUNBOOK 'lost state'")
        sd.to_parquet(B.SCORES_DIR / f"scores_{ds_}.parquet", index=False)
        out["regenerated_score_files"].append(ds_)
    for d in todo:
        month = d.strftime("%Y-%m")
        if month not in cache:
            cache[month] = ensure_models(df, feats, dates, darr, month)
        mm = cache[month]
        rows = df[df["date"] == d]
        sd = B.score_date(rows, mm)
        sd.to_parquet(B.SCORES_DIR / f"scores_{d.date()}.parquet", index=False)
        bk = B.baskets(sd)
        new = B.signal_rows(sd, bk)
        out["rows_appended"] += append_rows(LEDGER_FILES["signals"], SIGNALS_COLS, new)
        out["appended_signal_dates"].append(str(d.date()))
        log(f"signals {d.date()}: model {month}, universe {len(sd)}, baskets "
            + ", ".join(f"{b} {len(bk[b])}" for b in BOOK_ORDER), "job")
    if verify:
        led = read_csv_rows(LEDGER_FILES["signals"])
        last = max((r["signal_date"] for r in led), default=None)
        if last:
            d = pd.Timestamp(last)
            mm = M.MonthModels(d.strftime("%Y-%m"))
            sd = B.score_date(df[df["date"] == d], mm)
            again = B.signal_rows(sd, B.baskets(sd))
            have = [{k: r[k] for k in SIGNALS_COLS} for r in led if r["signal_date"] == last]
            again = [{k: str(r[k]) for k in SIGNALS_COLS} for r in again]
            out["recomputed_signal_date"] = last
            out["recomputed_signals_equal_ledger"] = have == again
            old = pd.read_parquet(B.SCORES_DIR / f"scores_{last}.parquet")
            out["recomputed_scores_max_abs_diff"] = float(np.max(np.abs(
                old[["lgbm", "lambdarank", "catboost", "ensemble"]].to_numpy(float)
                - sd[["lgbm", "lambdarank", "catboost", "ensemble"]].to_numpy(float))))
    return out


def process_marks() -> tuple[pd.DataFrame, dict, dict]:
    from ml.paper.config import COST_PRICE_START
    fp = pd.read_parquet(I.FEAT_LIVE, columns=["date", "ticker", "open", "high", "low", "close", "turnover"],
                         filters=[("date", ">=", pd.Timestamp(COST_PRICE_START))])
    fp["date"] = pd.to_datetime(fp["date"])
    sessions = pd.DatetimeIndex(sorted(fp["date"].unique()))
    mk, info = B.compute_marks(LEDGER_FILES["signals"], fp, sessions)
    led = read_csv_rows(LEDGER_FILES["marks"])
    last = max((r["session"] for r in led), default="")
    rows = B.marks_ledger_rows(mk)
    old = [r for r in rows if r["session"] <= last]
    new = [r for r in rows if r["session"] > last]
    have = [{k: r[k] for k in MARKS_COLS} for r in led]
    chk = {"recomputed_sessions": len({r["session"] for r in old}), "recomputed_marks_equal_ledger": None}
    if have:
        a = pd.DataFrame(have)
        b = pd.DataFrame(old)[MARKS_COLS] if old else pd.DataFrame(columns=MARKS_COLS)
        same_keys = len(a) == len(b) and (a[["session", "book"]].to_numpy() == b[["session", "book"]].to_numpy()).all()
        if same_keys:
            num = [c for c in MARKS_COLS if c not in ("session", "book")]
            d = np.abs(a[num].replace("", np.nan).astype(float).to_numpy() - b[num].replace("", np.nan).astype(float).to_numpy())
            chk["recomputed_marks_max_abs_diff"] = float(np.nanmax(d)) if d.size else 0.0
            chk["recomputed_marks_equal_ledger"] = bool((a.to_numpy() == b.to_numpy()).all())
        else:
            chk["recomputed_marks_equal_ledger"] = False
            chk["note"] = "recomputed (session, book) keys differ from the ledger"
    n = append_rows(LEDGER_FILES["marks"], MARKS_COLS, new)
    chk["rows_appended"] = n
    allm = pd.DataFrame(have + new)
    if len(allm):
        for c in MARKS_COLS[2:]:
            allm[c] = allm[c].replace("", np.nan).astype(float)
    return allm, info, chk


def process_monitors(df, feats, marks: pd.DataFrame) -> dict:
    led = read_csv_rows(LEDGER_FILES["monitors"])
    done = {r["session"] for r in led}
    sig = sorted({r["signal_date"] for r in read_csv_rows(LEDGER_FILES["signals"])})
    todo = [d for d in sig if d not in done]
    if done and todo and todo[0] <= max(done):
        raise SystemExit("monitor session precedes the ledger's last monitor session")
    if not todo:
        return {"rows_appended": 0, "sessions": []}
    scores = {d: pd.read_parquet(B.SCORES_DIR / f"scores_{d}.parquet") for d in sig}
    for v in scores.values():
        v["date"] = pd.to_datetime(v["date"])
    ing = json.loads(I.INGEST_JSON.read_text()) if I.INGEST_JSON.exists() else {}
    cal = I.calendar_live()
    sessions = pd.DatetimeIndex(np.sort(df["date"].unique()))
    ctx = MON.Context(df, feats, sessions, scores, marks, ing, cal)
    n = 0
    for d in todo:
        ctx.scores = {k: v for k, v in scores.items() if k <= d}
        rows = MON.evaluate(ctx, pd.Timestamp(d))
        n += append_rows(LEDGER_FILES["monitors"], MONITORS_COLS, rows)
        log(f"monitors {d}: " + "; ".join(f"{r['monitor']}[{r['scope']}]={r['value']} {r['status']}" for r in rows), "job")
    return {"rows_appended": n, "sessions": todo}


def write_state(store: dict) -> dict:
    sig = read_csv_rows(LEDGER_FILES["signals"])
    mk = read_csv_rows(LEDGER_FILES["marks"])
    mo = read_csv_rows(LEDGER_FILES["monitors"])
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
    wjson(STATE_JSON, st)
    return st


def latest_baskets() -> dict:
    sig = read_csv_rows(LEDGER_FILES["signals"])
    if not sig:
        return {}
    last = max(r["signal_date"] for r in sig)
    return {"signal_date": last, **{b: {"size": sum(1 for r in sig if r["signal_date"] == last and r["book"] == b)}
                                    for b in BOOK_ORDER}}


def run(a) -> dict:
    t0 = time.time()
    check_code_matches_spec()
    before = ledger_hashes()
    rec = {"started": datetime.now().isoformat(timespec="seconds"), "args": vars(a), "ledger_before": before}
    if not a.no_ingest:
        rec["ingest"] = run_child("ingest")
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
    if a.prove_idempotency:
        idem = {"note": "ml/paper/job.py --prove-idempotency, run after the first full run on the same store",
                "before": before, "after": after, "identical": before == after,
                "rows_appended": rec["signals"]["rows_appended"] + mchk["rows_appended"] + rec["monitors"]["rows_appended"],
                "recomputed_signal_date": rec["signals"].get("recomputed_signal_date"),
                "recomputed_signals_equal_ledger": rec["signals"].get("recomputed_signals_equal_ledger"),
                "recomputed_scores_max_abs_diff": rec["signals"].get("recomputed_scores_max_abs_diff"),
                "recomputed_marks_equal_ledger": mchk.get("recomputed_marks_equal_ledger"),
                "recomputed_marks_max_abs_diff": mchk.get("recomputed_marks_max_abs_diff"),
                "frame_rebuilt_in_this_run": fr.get("rebuilt"),
                "ingest_decisions_in_this_run": rec.get("ingest", {}).get("decisions")}
        wjson(IDEM_JSON, idem)
    R.build(state, marks, B.inception_summary(LEDGER_FILES["signals"]), latest_baskets(), MON.dsr_paper(marks), minfo)
    rec["seconds"] = round(time.time() - t0, 1)
    rec["python"] = python_info()
    RUNS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(RUNS_FILE, "a") as fh:
        fh.write(json.dumps(rec, default=str) + "\n")
    log(f"job done in {rec['seconds']} s; ledger unchanged {rec['ledger_unchanged']}; signals +{rec['signals']['rows_appended']}, "
        f"marks +{mchk['rows_appended']}, monitors +{rec['monitors']['rows_appended']}", "job")
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-ingest", action="store_true", help="skip the archive and the store write")
    ap.add_argument("--force-frame", action="store_true", help="rebuild the scoring frame even if the store is unchanged")
    ap.add_argument("--prove-idempotency", action="store_true",
                    help="record ledger hashes before/after in ml/results/improve2/paper/idempotency.json")
    a = ap.parse_args(argv)
    rec = run(a)
    print(json.dumps({k: rec[k] for k in ("ingest", "frame_rebuilt", "signals", "marks", "monitors", "ledger_unchanged",
                                          "seconds") if k in rec}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

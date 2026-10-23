"""Daily ingest of the paper book: new sessions into nse_market.duckdb (the only writer in phase 2).

Order of a run
  1. candidate dates = nse_historical_ingest.trading_days(last stored session + 1, today IST) with the
     ingest's holiday and special-session sets plus the closures/special sessions this stream recorded in
     ml/paper/calendar_live.json;
  2. per candidate, in date order: nse_historical_ingest.fetch_day (sec_bhavdata_full + CM enrichment,
     legacy then UDiFF, merge_sources) through a polite, disk-caching adapter; the file's own DATE1 column;
     the duplicate-day guard (frame_fingerprint vs the previous session); the PR bundle (exists and its pd
     member carries the date).  Session / closure / pending / unresolved (SPEC.md 2.6);
  3. corporate actions: ml/integrity/corporate_actions.build over every PR bundle on disk (outputs redirected to
     ml/paper/state/ca/) with the paper's parser extension (``ca_extension``: the CNSLDATN spelling of a
     consolidation, and the record date as the ex-date of a split/bonus/consolidation whose EX_DT is empty), then
     the validated split/bonus/consolidation events the ten-year feed lacks whose ex-date is after the research end,
     or on/before it with the ticker's first print on/after the ex-date after the research end (a suspension across
     the research end) -> the ten-year feed's bytes with those lines appended, staged in ml/paper/state/ca/ and
     promoted to ml/data_ext/corporate_actions_feed_live.csv only after a successful write;
     ETF symbols of the live bundles -> ml/data_ext/etf_list_live.csv;
  4. the write (lock protocol of phase 1): backup copy (free space checked; PAPER_BACKUP_DIR or
     ml/paper/state/backup/), lock file, one transaction with DuckDBStore.upsert (rolled back if any EQ/BE (date,
     ticker) pair would appear twice), build_features(con, ca_csv=<staged live feed>), CHECKPOINT, lock removed,
     verification (continuity scan and per-name prev_close breaks on the new sessions, duplicates, equity_eod and
     equity_features fingerprints for dates <= the research end); the backup is deleted once verification passed;
  5. parquet exports of the updated store for the book's prices (ml/paper/state/cache/).
A write whose verification failed holds every later ingest and stops the job until it is resolved (RUNBOOK
section 5); ``--rebuild-features REASON`` re-derives the live feed and rebuilds equity_features under the same
protocol without new sessions (the repair path).

Downloaded files live in ml/paper/state/raw/{sec,cm,pr}/ (one folder per kind, no code there) and are only
parsed as data.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # run as a script: the repository root

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import nse_historical_ingest as nhi  # noqa: E402
from ml.paper.common import dumps, log, repo_rel, sha256_file, wjson  # noqa: E402
from ml.paper.config import (CA_FEED_10Y, CA_FEED_LIVE, CALENDAR_LIVE, DB_PATH, ETF_10Y, ETF_LIVE, LOCK_FILE,
                             PR_DIRS_RESEARCH, RESEARCH_END, RESULTS_DIR, STATE_DIR)

RAW_LIVE = STATE_DIR / "raw"
RAW_SEC, RAW_CM, RAW_PR = RAW_LIVE / "sec", RAW_LIVE / "cm", RAW_LIVE / "pr"
CACHE = STATE_DIR / "cache"
CA_DIR = STATE_DIR / "ca"
EOD_LIVE = CACHE / "eod_export_live.parquet"
FEAT_LIVE = CACHE / "features_prices_export_live.parquet"
EOD_10Y = Path(__file__).resolve().parents[1] / "results" / "improve" / "cache" / "eod_export_10y.parquet"
INGEST_JSON = RESULTS_DIR / "ingest.json"
# backup copy of the store before a write: on the same machine as the store, outside git (ml/paper/state/ is ignored)
BACKUP_DIR = Path(os.environ.get("PAPER_BACKUP_DIR") or (STATE_DIR / "backup"))
CA_FEED_STAGED = CA_DIR / "corporate_actions_feed_live.staged.csv"
PR_URL = "https://archives.nseindia.com/archives/equities/bhavcopy/pr/PR{ddmmyy}.zip"
IST = ZoneInfo("Asia/Kolkata")
FWD_PREFIX = ("fwd_ret_", "label_up_")


# --------------------------------------------------------------------------- polite, caching archive client
def _getter():
    """ml.integrity.common.PoliteGetter (browser UA, 1-2 s gaps, 60 s back-off, one request in flight) with its
    lock/state files and its log redirected to this stream's folders."""
    import ml.integrity.common as ic

    class LiveGetter(ic.PoliteGetter):
        LOCK = RAW_LIVE / ".net.lock"
        STATE = RAW_LIVE / ".net_state.json"

    ic.log = lambda msg, tag="net": log(msg, "net")      # PoliteGetter logs through the module global
    RAW_LIVE.mkdir(parents=True, exist_ok=True)
    g = LiveGetter(tag="paper-net")
    return g


class ArchiveAdapter:
    """The object nse_historical_ingest.fetch_day expects (``get(url) -> bytes | None``), backed by a disk
    cache: a file fetched once is read from ml/paper/state/raw/ afterwards.  Every network outcome goes to
    ml/paper/state/raw/_manifest.csv (gitignored, wall-clock)."""

    def __init__(self, today: date):
        self.g = None
        self.today = today
        self.calls: list[dict] = []

    def _path(self, url: str) -> Path:
        name = url.rsplit("/", 1)[-1]
        if name.startswith("sec_bhavdata_full"):
            return RAW_SEC / name
        if name.startswith("PR") and name.endswith(".zip"):
            return RAW_PR / name
        return RAW_CM / name

    def get(self, url: str) -> bytes | None:
        p = self._path(url)
        if p.exists() and p.stat().st_size > 0:
            self.calls.append({"url": url, "source": "disk", "status": 200, "bytes": p.stat().st_size})
            return p.read_bytes()
        if self.g is None:
            self.g = _getter()
        st, body = self.g.get(url)
        with open(RAW_LIVE / "_manifest.csv", "a") as fh:
            fh.write(f"{p.name},{url},{st},{len(body) if body else 0},"
                     f"{datetime.now().isoformat(timespec='seconds')}\n")
        self.calls.append({"url": url, "source": "network", "status": st, "bytes": len(body) if body else 0})
        if st == 200 and body:
            from ml.integrity.common import atomic_write_bytes
            atomic_write_bytes(p, body)
            return body
        return None

    def _sleep(self) -> None:          # run_ingest compatibility; the getter already spaces requests
        pass


# --------------------------------------------------------------------------- calendar
def calendar_live() -> dict:
    if CALENDAR_LIVE.exists():
        return json.loads(CALENDAR_LIVE.read_text())
    return {"note": "Calendar decisions of the paper book's ingest (ml/paper/SPEC.md 2.6). A closure is a weekday whose "
                    "archive files echo the previous session and whose PR bundle is absent; it is never ingested.",
            "closures": {}, "special_sessions": {}, "sessions": {}}


def today_ist() -> date:
    return datetime.now(IST).date()


def store_summary(read_only: bool = True) -> dict:
    import duckdb
    con = duckdb.connect(str(DB_PATH), read_only=read_only)
    q = lambda s, *p: con.execute(s, list(p)).fetchall()  # noqa: E731
    out = {"last_session": str(q("SELECT max(date) FROM equity_eod")[0][0]),
           "equity_eod_rows": int(q("SELECT count(*) FROM equity_eod")[0][0]),
           "equity_eod_eq_be_rows": int(q("SELECT count(*) FROM equity_eod WHERE series IN ('EQ','BE')")[0][0]),
           "equity_eod_sessions": int(q("SELECT count(DISTINCT date) FROM equity_eod")[0][0]),
           "equity_features_rows": int(q("SELECT count(*) FROM equity_features")[0][0]),
           "equity_features_last": str(q("SELECT max(date) FROM equity_features")[0][0])}
    con.close()
    return out


def _date1(raw: bytes) -> list[str]:
    from ml.integrity.sessions import _date1 as d1
    return d1(raw)


def _prev_fp(d: date, accepted: list[tuple[date, pd.DataFrame]]) -> tuple[str, tuple | None]:
    if accepted:
        pd_, df = accepted[-1]
        return str(pd_), nhi.frame_fingerprint(df)
    import duckdb
    con = duckdb.connect(str(DB_PATH), read_only=True)
    store = nhi.DuckDBStore.__new__(nhi.DuckDBStore)      # read-only: no schema creation
    store.con = con
    prev = store.prev_date(d)
    fp = store.day_fingerprint(prev) if prev is not None else None
    con.close()
    return str(prev), (tuple(fp) if fp else None)


def decide_sessions(today: date | None = None) -> dict:
    """Steps 1-2: candidate dates and their decisions (no write)."""
    from ml.integrity.common import bundle_inner_date, bundle_ok
    today = today or today_ist()
    cal = calendar_live()
    st = store_summary()
    last = date.fromisoformat(st["last_session"])
    hol = set(nhi.NSE_TRADING_HOLIDAYS) | set(cal["closures"])
    spc = set(nhi.SPECIAL_SESSIONS) | set(cal["special_sessions"])
    cands = nhi.trading_days(last + timedelta(days=1), today, holidays=hol, special=spc)
    ad = ArchiveAdapter(today)
    accepted: list[tuple[date, pd.DataFrame]] = []
    decisions = []
    calls_of: dict[str, tuple[int, int]] = {}         # date -> slice of ad.calls made while deciding it
    for d in cands:
        rec = {"date": str(d), "weekday": d.strftime("%A")}
        c0 = len(ad.calls)
        sec_url = nhi.SEC_DELIVERY_URL.format(ddmmyyyy=d.strftime("%d%m%Y"))
        raw = ad.get(sec_url)
        pr_name = f"PR{d:%d%m%y}.zip"
        if raw is None:
            if d >= today:
                rec["decision"] = "pending: file not yet published"
                decisions.append(rec)
                break
            pr = ad.get(PR_URL.format(ddmmyy=d.strftime("%d%m%y")))
            calls_of[str(d)] = (c0, len(ad.calls))
            rec["sec_http"] = 404
            rec["pr_bundle"] = "present" if pr is not None else "absent"
            if pr is None:
                rec["decision"] = "closure: no sec file and no PR bundle"
                rec["_tentative"] = True
                decisions.append(rec)
                continue
            rec["decision"] = "unresolved: PR bundle present but no sec file"
            decisions.append(rec)
            break
        rec["sec_bytes"] = len(raw)
        rec["sec_sha256"] = hashlib.sha256(raw).hexdigest()
        try:
            df = nhi.fetch_day(ad, d, use_pr=True)
            rec["date1"] = _date1(raw)
        except Exception as exc:  # noqa: BLE001
            rec["decision"] = f"unresolved: unparseable sec file ({exc!r})"
            decisions.append(rec)
            break
        want = d.strftime("%d-%b-%Y")
        rec["date1_ok"] = rec["date1"] == [want]
        prev_d, prev_fp = _prev_fp(d, accepted)
        fp = nhi.frame_fingerprint(df)
        rec["fingerprint"] = list(fp)
        rec["previous_session"] = prev_d
        rec["fingerprint_previous"] = list(prev_fp) if prev_fp else None
        rec["duplicate_day_guard_echo"] = bool(prev_fp is not None and tuple(prev_fp) == tuple(fp))
        prev_sec = RAW_SEC / f"sec_bhavdata_full_{date.fromisoformat(prev_d):%d%m%Y}.csv" if prev_d != "None" else None
        rec["byte_identical_to_previous_sec_file"] = (bool(prev_sec.read_bytes() == raw)
                                                     if prev_sec is not None and prev_sec.exists() else None)
        rec["rows_all_series"] = int(len(df))
        rec["rows_eq_be"] = int(df["series"].isin(["EQ", "BE"]).sum())
        rec["isin_filled_share"] = round(float(df["isin"].notna().mean()), 4)
        pr = ad.get(PR_URL.format(ddmmyy=d.strftime("%d%m%y")))
        zp = RAW_PR / pr_name
        if pr is None:
            rec["pr_bundle"] = "absent"
        else:
            rec["pr_bundle"] = "present"
            rec["pr_bundle_inner_date"] = str(bundle_inner_date(zp))
            rec["pr_bundle_ok"] = bool(bundle_ok(zp))
            rec["pr_sha256"] = sha256_file(zp)
        is_session = rec["date1_ok"] and not rec["duplicate_day_guard_echo"] and rec.get("pr_bundle_ok", False)
        is_echo = (rec["duplicate_day_guard_echo"] or not rec["date1_ok"]) and pr is None
        calls_of[str(d)] = (c0, len(ad.calls))
        if is_session:
            rec["decision"] = "session: ingest"
            accepted.append((d, df))
        elif is_echo:
            rec["decision"] = "closure: holiday echo of the previous session (duplicate-day guard) and no PR bundle"
            rec["_tentative"] = True
        else:
            rec["decision"] = "unresolved: evidence disagrees"
            decisions.append(rec)
            break
        decisions.append(rec)
    confirm_closures(decisions, accepted, ad, calls_of)
    return {"today_ist": str(today), "store_before": st, "candidates": [str(d) for d in cands],
            "decisions": decisions, "accepted": [str(d) for d, _ in accepted],
            "network_calls": [c for c in ad.calls if c["source"] == "network"],
            "_frames": accepted}


def confirm_closures(decisions: list[dict], accepted: list, ad: ArchiveAdapter, calls_of: dict) -> list[str]:
    """A closure is permanent (it joins the holiday set of every later run), so it is recorded only when the archive
    has moved on: a later candidate of the same run was accepted as a session.  Without that evidence a missing or
    echoed file may just be late (a run after midnight IST, or an echo served before the day's file is published), so
    the date stays pending and the files fetched for it are dropped from the disk cache, so that the next run fetches
    them again instead of re-reading a stale copy."""
    last_acc = max((d for d, _ in accepted), default=None)
    reverted = []
    for rec in decisions:
        if not rec.pop("_tentative", False):
            continue
        if last_acc is not None and date.fromisoformat(rec["date"]) < last_acc:
            rec["closure_confirmed_by_later_session"] = str(last_acc)
            continue
        rec["decision"] = ("pending: " + rec["decision"].split(": ", 1)[1]
                           + "; recorded as a closure only once a later session is published")
        lo, hi = calls_of.get(rec["date"], (0, 0))
        dropped = []
        for c in ad.calls[lo:hi]:
            p = ad._path(c["url"])
            if c["status"] == 200 and p.exists():
                p.unlink()
                dropped.append(p.name)
        rec["cache_dropped"] = dropped
        reverted.append(rec["date"])
    return reverted


def record_calendar(dec: dict) -> bool:
    cal = calendar_live()
    for r in dec["decisions"]:
        ev = {k: v for k, v in r.items() if k not in ("date", "weekday")}
        if r["decision"].startswith("closure"):
            cal["closures"][r["date"]] = {"weekday": r["weekday"], **ev}
        elif r["decision"].startswith("session"):
            cal["sessions"][r["date"]] = {"weekday": r["weekday"], **ev}
    cal["closures"] = dict(sorted(cal["closures"].items()))
    cal["sessions"] = dict(sorted(cal["sessions"].items()))
    return wjson(CALENDAR_LIVE, cal)


# --------------------------------------------------------------------------- corporate actions and ETFs
def eod_base_export() -> Path:
    """EQ/BE rows of the store as it stands (the live export once one exists, else the ten-year export, which
    equals the store until the first write of this stream)."""
    if EOD_LIVE.exists():
        return EOD_LIVE
    return EOD_10Y


@contextmanager
def ca_extension(ca, record: dict):
    """The paper's extension of ml/integrity/corporate_actions.py (read-only in phase 2), active only inside this
    stream's corporate-action build (SPEC.md 2.7 and amendment 4):

    * ``classify``: a purpose whose components the module finds none adjustable is also read for the CNSLDATN /
      CNSLDTN spelling of a face-value consolidation ("CNSLDATNRE1 TO RS10" -> consolidation, ratio 10/1), which the
      module's RE_CONSOL (CONSOL / CONSL) misses;
    * ``load_bc``: a record whose EX_DT is empty and whose purpose has a split/bonus/consolidation component takes
      its record date as the ex-date (T+1 settlement: ex-date = record date; for a consolidation with a trading
      suspension any date inside the suspension gives the same adjustment).

    Every event still has to pass the module's own validation (observed open/close ratio within +-15%, ex-date shift
    within +-3 sessions); the extension only lets such events reach it.  What it touched is recorded in ``record``."""
    rx = re.compile(r"CNSLD\w*?\s*-?\s*(?:OF\s*SHARES?\s*)?(?:FRM|FROM)?\s*" + ca.CUR + ca.NUM
                    + r"\s*(?:/-)?\s*TO\s*" + ca.CUR + ca.NUM)
    orig_classify, orig_load_bc = ca.classify, ca.load_bc
    record.setdefault("purposes_read_by_extension", set())
    record.setdefault("ex_date_from_record_date", [])

    def classify(purpose: str) -> list[dict]:
        comps = orig_classify(purpose)
        if any(c["kind"] in ca.ADJUSTABLE for c in comps):
            return comps
        p = ca._norm(purpose)
        ext = []
        for m in rx.finditer(p):
            a, b = float(m.group(1)), float(m.group(2))
            if a > 0 and b > a:
                ext.append({"kind": "consolidation", "ratio": b / a, "a": a, "b": b})
        if ext:
            record["purposes_read_by_extension"].add(p)
            return ext
        return comps

    def load_bc():
        ev, stats = orig_load_bc()
        miss = ev["ex_date"].isna() & ev["record_date"].notna()
        adj = miss & ev["purpose"].map(lambda q: any(c["kind"] in ca.ADJUSTABLE for c in classify(q)))
        ev.loc[adj, "ex_date"] = ev.loc[adj, "record_date"]
        for r in ev.loc[adj].itertuples(index=False):
            record["ex_date_from_record_date"].append({"ticker": r.ticker, "ex_date": str(pd.Timestamp(r.ex_date).date()),
                                                      "purpose": r.purpose, "source": r.source_file})
        stats["paper_ex_date_from_record_date"] = int(adj.sum())
        return ev, stats

    ca.classify, ca.load_bc = classify, load_bc
    try:
        yield record
    finally:
        ca.classify, ca.load_bc = orig_classify, orig_load_bc


def feed_keys(path: Path) -> set[tuple]:
    """(ticker, ex_date, ratio rounded to 12 decimals) of a feed file (empty set when it does not exist)."""
    if not path.exists():
        return set()
    d = pd.read_csv(path, dtype={"ex_date": str}, float_precision="round_trip")
    return set(zip(d["ticker"], d["ex_date"], np.round(d["ratio"].astype(float), 12)))


def corporate_actions_live(frames: list[tuple[date, pd.DataFrame]], last_session: str) -> dict:
    """Corporate actions through ``last_session`` and the staged live feed (``CA_FEED_STAGED``): the ten-year feed's
    bytes followed by one line per validated event the ten-year feed lacks that falls in the live window.  The
    caller promotes the staged file (``promote_feed``) once the store was built with it."""
    import ml.integrity.corporate_actions as ca
    CA_DIR.mkdir(parents=True, exist_ok=True)
    staged = CA_DIR / "staged_new_sessions.parquet"
    if frames:
        x = pd.concat([f for _, f in frames], ignore_index=True)
        x["date"] = pd.to_datetime(x["date"]).astype("datetime64[ns]")
        x.to_parquet(staged, index=False)
    srcs = [str(eod_base_export())] + ([str(staged)] if frames else [])
    eod = ca.load_eod_sources(srcs)
    saved = dict(OUT=ca.OUT, DATA_EXT=ca.DATA_EXT, log=ca.log, completeness=ca.completeness,
                 dirs=list(ca.BUNDLE_DIRS))
    orig_comp = ca.completeness

    def comp_live(e, feed, ev2, allc=None):          # completeness on this stream's bundles only
        keep = list(ca.BUNDLE_DIRS)
        ca.BUNDLE_DIRS[:] = [RAW_PR]
        try:
            return orig_comp(e, feed, ev2, allc)
        finally:
            ca.BUNDLE_DIRS[:] = keep
    ext: dict = {}
    try:
        ca.OUT, ca.DATA_EXT = CA_DIR, CA_DIR
        ca.log = lambda m, tag="ca": log(m, "ca")
        ca.completeness = comp_live
        ca.BUNDLE_DIRS[:] = list(PR_DIRS_RESEARCH) + [RAW_PR]
        t0 = time.time()
        with ca_extension(ca, ext):
            res = ca.build(eod, suffix="_live_full")
        secs = round(time.time() - t0, 1)
    finally:
        ca.OUT, ca.DATA_EXT, ca.log, ca.completeness = saved["OUT"], saved["DATA_EXT"], saved["log"], saved["completeness"]
        ca.BUNDLE_DIRS[:] = saved["dirs"]
    full = pd.read_csv(CA_DIR / "corporate_actions_feed_live_full.csv", float_precision="round_trip")
    allr = pd.read_csv(CA_DIR / "corporate_actions_all_live_full.csv", low_memory=False)
    brk = pd.read_csv(CA_DIR / "price_break_flags_live_full.csv")
    f10 = pd.read_csv(CA_FEED_10Y, float_precision="round_trip")
    # events the parser extension let through: their purpose was read by it, or their ex-date is a record date
    ext_purp = ext["purposes_read_by_extension"]
    ext_keys = {(e["ticker"], e["ex_date"]) for e in ext["ex_date_from_record_date"]}
    adj_rows = allr[allr["kind"].astype(str).str.contains("split|bonus|consolidation", regex=True)]
    for r in adj_rows.itertuples(index=False):
        parts = set(str(r.purpose).split(" | "))
        if parts & ext_purp or (r.ticker, str(r.ex_date)) in ext_keys:
            ext_keys.add((r.ticker, str(r.ex_date)))
            if isinstance(r.effective_ex_date, str):
                ext_keys.add((r.ticker, r.effective_ex_date))
    key = lambda d: set(zip(d["ticker"], d["ex_date"], np.round(d["ratio"].astype(float), 12)))  # noqa: E731
    old_full = full[full["ex_date"] <= RESEARCH_END]
    only_rebuilt = sorted(map(list, key(old_full) - key(f10)))
    only_10y = sorted(map(list, key(f10) - key(old_full)))
    from_ext = [e for e in only_rebuilt if (e[0], e[1]) in ext_keys]
    # ---- the live window ----
    in10 = full.set_index(["ticker", "ex_date"]).index.isin(f10.set_index(["ticker", "ex_date"]).index)
    cand = full[~in10].copy()
    e = eod[["ticker", "date"]].copy()
    e["date"] = pd.to_datetime(e["date"]).astype("datetime64[ns]")
    e = e.sort_values("date")
    k = cand[["ticker", "ex_date"]].assign(ex_ts=pd.to_datetime(cand["ex_date"]).astype("datetime64[ns]"))
    k = k.sort_values("ex_ts")
    fp_ = pd.merge_asof(k, e.rename(columns={"date": "first_print"}), left_on="ex_ts", right_on="first_print",
                        by="ticker", direction="forward")
    cand = cand.merge(fp_[["ticker", "ex_date", "first_print"]], on=["ticker", "ex_date"], how="left")
    fpr = cand["first_print"].dt.strftime("%Y-%m-%d").fillna("")
    after_end = (cand["ex_date"] > RESEARCH_END) & (cand["ex_date"] <= last_session)
    across_end = (cand["ex_date"] <= RESEARCH_END) & (fpr > RESEARCH_END) & (fpr <= last_session)
    new = cand[after_end | across_end].copy()
    new["first_print_on_or_after_ex"] = fpr[after_end | across_end]
    new["window"] = np.where(new["ex_date"] > RESEARCH_END, "ex-date after the research end",
                             "ex-date on/before the research end, first print after it (suspension)")
    new = new.sort_values(["ex_date", "ticker"], kind="stable").reset_index(drop=True)
    # ---- the staged feed: the ten-year file's bytes, then the new lines ----
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    for r in new.itertuples(index=False):
        w.writerow([r.ticker, r.ex_date, repr(float(r.ratio)), r.kind, r.source, "True"])
    base = CA_FEED_10Y.read_bytes()
    if not base.endswith(b"\n"):
        raise SystemExit("the ten-year feed does not end with a newline")
    blob = base + buf.getvalue().encode()
    tmp = CA_FEED_STAGED.with_name(CA_FEED_STAGED.name + ".tmp")
    tmp.write_bytes(blob)
    tmp.replace(CA_FEED_STAGED)
    if not CA_FEED_STAGED.read_bytes().startswith(base):
        raise SystemExit("staged live feed does not start with the ten-year feed's bytes")
    chk = pd.read_csv(CA_FEED_STAGED, float_precision="round_trip")
    if len(chk) != len(f10) + len(new) or not np.array_equal(chk["ratio"].to_numpy(float)[len(f10):],
                                                             new["ratio"].to_numpy(float)):
        raise SystemExit("staged live feed does not re-read to the ten-year feed plus the new events")
    cur = feed_keys(CA_FEED_LIVE) if CA_FEED_LIVE.exists() else feed_keys(CA_FEED_10Y)
    changed = sorted({k[0] for k in cur ^ feed_keys(CA_FEED_STAGED)})
    exd = allr["ex_date"].fillna("").astype(str)
    win = (exd > RESEARCH_END) & (exd <= last_session)
    adjustable = allr["kind"].astype(str).str.contains("split|bonus|consolidation", regex=True)
    unvalidated = allr[win & adjustable & (allr["validated"].astype(str) != "True")
                       & allr["status"].isin(["ok", "ex_date_shifted"])]
    upcoming = allr[(exd > last_session) & adjustable].drop_duplicates(["ticker", "ex_date", "purpose"])
    return {"seconds": secs, "bundle_dirs": [repo_rel(p) for p in list(PR_DIRS_RESEARCH) + [RAW_PR]],
            "eod_sources": [repo_rel(Path(x)) for x in srcs], "I2_rebuilt_feed": res.get("I2"),
            "parser_extension": {
                "purposes_read_by_extension": sorted(ext_purp),
                "ex_date_from_record_date": ext["ex_date_from_record_date"],
                "note": "ml/paper/ingest.py ca_extension (SPEC.md 2.7): CNSLDATN spelling and record date as ex-date; "
                        "events still pass the module's validation"},
            "feed_10y_rows": int(len(f10)), "rebuilt_feed_rows_through_research_end": int(len(old_full)),
            "rebuilt_vs_10y_through_research_end": {
                "only_in_rebuilt": only_rebuilt[:50], "only_in_10y": only_10y[:50],
                "only_in_rebuilt_from_parser_extension": from_ext,
                "identical": not only_rebuilt and not only_10y,
                "identical_apart_from_parser_extension": not only_10y and len(from_ext) == len(only_rebuilt),
                "note": "research-period events found by the parser extension are reported, not applied: the live "
                        "feed adds only events of the live window, so equity_features through the research end keep "
                        "the ten-year feed's adjustments"},
            "new_validated_events": new[["ticker", "ex_date", "ratio", "kind", "source", "first_print_on_or_after_ex",
                                         "window"]].to_dict("records"),
            "new_events_from_parser_extension": [r["ticker"] for r in new.to_dict("records")
                                                 if (r["ticker"], r["ex_date"]) in ext_keys],
            "tickers_whose_feed_lines_change": changed,
            "unvalidated_adjustable_events_in_window": unvalidated[["ticker", "ex_date", "kind", "purpose",
                                                                    "observed_ratio"]].to_dict("records"),
            "price_breaks_in_window": brk[(brk["ex_date"].astype(str) > RESEARCH_END)
                                          & (brk["ex_date"].astype(str) <= last_session)].to_dict("records"),
            "upcoming_adjustable_events": upcoming[["ticker", "ex_date", "kind", "purpose"]].to_dict("records"),
            "live_feed": {"path": "ml/data_ext/corporate_actions_feed_live.csv", "rows": int(len(chk)),
                          "sha256": sha256_file(CA_FEED_STAGED), "staged": repo_rel(CA_FEED_STAGED),
                          "starts_with_ten_year_feed_bytes": True, "lines_appended": int(len(new))},
            "completeness_live_bundles": {k: res["completeness"].get(k) for k in
                                          ("corp_ind_with_abs_ret_gt_22pct", "covered_by_feed", "n_missing", "missing")}}


def promote_feed() -> str:
    """The staged feed becomes ml/data_ext/corporate_actions_feed_live.csv (after the store was built with it)."""
    CA_FEED_STAGED.replace(CA_FEED_LIVE)
    return sha256_file(CA_FEED_LIVE)


# --------------------------------------------------------------------------- per-name prev_close breaks
def eq_be_rows_store(con) -> pd.DataFrame:
    d = con.execute("SELECT date, ticker, prev_close, close FROM equity_eod WHERE series IN ('EQ','BE')").df()
    d["date"] = pd.to_datetime(d["date"]).astype("datetime64[ns]")
    return d


def price_breaks(eqbe: pd.DataFrame, sessions: list[str], feed: pd.DataFrame, allr: pd.DataFrame | None) -> dict:
    """Per-name check of the exchange's prev_close on ``sessions`` against the ticker's stored previous close.

    A break is |prev_close / stored previous close - 1| > 22% (the completeness threshold of
    ml/integrity/corporate_actions.py).  It is ``explained_by_feed`` when the live feed has events of that ticker with
    an ex-date after the stored previous session and on/before the session whose compound ratio agrees with
    prev_close / stored close within +-15% (the module's validation band); ``recorded_price_break`` when the PR
    bundles list an unadjustable action (rights, demerger, scheme, capital reduction, bonus in another security) of
    that ticker in that interval (alert, not adjusted: SPEC.md 2.7); otherwise ``unexplained``, which fails the
    write's verification and stops the job before scoring (RUNBOOK section 5)."""
    from ml.integrity.corporate_actions import AGREE_TOL, JUMP, UNADJUSTABLE
    e = eqbe.sort_values(["ticker", "date"], kind="stable").reset_index(drop=True)
    g = e.groupby("ticker", sort=False)
    e["stored_prev"] = g["close"].shift(1)
    e["stored_prev_date"] = g["date"].shift(1)
    want = pd.to_datetime(pd.Series(sessions, dtype=str)).astype("datetime64[ns]")
    s = e[e["date"].isin(set(want))]
    ok = s["stored_prev"].notna() & s["prev_close"].notna() & (s["stored_prev"] > 0)
    s = s[ok].assign(obs=lambda x: x["prev_close"] / x["stored_prev"])
    b = s[(s["obs"] - 1).abs() > JUMP]
    fd = feed.assign(ex_ts=pd.to_datetime(feed["ex_date"]).astype("datetime64[ns]"))
    un = None
    if allr is not None and len(allr):
        un = allr[allr["kind"].isin(UNADJUSTABLE)].copy()
        kd = un["ex_date"].where(un["ex_date"].notna(), un.get("record_date"))
        un["key_ts"] = pd.to_datetime(kd, errors="coerce")
    rows = []
    for r in b.itertuples(index=False):
        ev = fd[(fd["ticker"] == r.ticker) & (fd["ex_ts"] > r.stored_prev_date) & (fd["ex_ts"] <= r.date)]
        R = float(np.prod(ev["ratio"].astype(float))) if len(ev) else float("nan")
        rec = {"date": str(r.date.date()), "ticker": r.ticker, "prev_close": float(r.prev_close),
               "stored_previous_close": float(r.stored_prev), "stored_previous_date": str(r.stored_prev_date.date()),
               "calendar_days_since_stored_previous": int((r.date - r.stored_prev_date).days),
               "prev_close_over_stored_close": float(r.obs),
               "feed_events": [{"ex_date": x.ex_date, "ratio": float(x.ratio)} for x in ev.itertuples(index=False)]}
        if len(ev) and abs(r.obs / R - 1) <= AGREE_TOL:
            rec["status"] = "explained_by_feed"
        else:
            hit = [] if un is None else un[(un["ticker"] == r.ticker) & (un["key_ts"] > r.stored_prev_date)
                                         & (un["key_ts"] <= r.date)]
            if len(hit):
                rec["status"] = "recorded_price_break"
                rec["recorded"] = hit[["kind", "purpose"]].drop_duplicates().to_dict("records")
            else:
                rec["status"] = "unexplained"
        rows.append(rec)
    per = {}
    for d in sorted({str(x.date()) for x in want}):
        x = [r for r in rows if r["date"] == d]
        per[d] = {"names_with_prev": int((s["date"] == pd.Timestamp(d)).sum()), "breaks": len(x),
                  **{k: sum(r["status"] == k for r in x) for k in ("explained_by_feed", "recorded_price_break",
                                                                    "unexplained")}}
    return {"rule": "|prev_close / stored previous close - 1| > 22%; explained when the live feed's events in "
                    "(stored previous session, session] agree within +-15%",
            "sessions": per, "breaks": rows,
            "n_unexplained": sum(r["status"] == "unexplained" for r in rows),
            "n_recorded_price_break": sum(r["status"] == "recorded_price_break" for r in rows)}


def ca_all_live() -> pd.DataFrame | None:
    p = CA_DIR / "corporate_actions_all_live_full.csv"
    return pd.read_csv(p, low_memory=False) if p.exists() else None


def etf_live() -> dict:
    from ml.integrity.corporate_actions import read_members
    e10 = pd.read_csv(ETF_10Y, dtype=str, keep_default_na=False)
    etf, st = read_members("etf", dirs=[RAW_PR]) if any(RAW_PR.glob("PR*.zip")) else (pd.DataFrame(), {})
    new_rows = []
    if len(etf):
        etf = etf[etf["SYMBOL"] != ""]
        known = set(e10["symbol"])
        for sym, g in etf.sort_values("file_date").groupby("SYMBOL"):
            if sym in known:
                continue
            new_rows.append({"symbol": sym, "first_seen": g["file_date"].min().strftime("%Y-%m-%d"),
                             "last_seen": g["file_date"].max().strftime("%Y-%m-%d"),
                             "n_days": str(g["file_date"].nunique()),
                             "underlying": next((x for x in g["UNDERLYING"][::-1] if x), ""),
                             "security": g["SECURITY"].iloc[-1],
                             "series_seen": ",".join(sorted(set(g["SERIES"]))), "windows": "live"})
    out = pd.concat([e10, pd.DataFrame(new_rows, columns=e10.columns)], ignore_index=True)
    out = out.sort_values("symbol", kind="stable").reset_index(drop=True)
    tmp = ETF_LIVE.with_name(ETF_LIVE.name + ".tmp")
    out.to_csv(tmp, index=False)
    tmp.replace(ETF_LIVE)
    return {"etf_10y_symbols": int(len(e10)), "live_bundle_etf_symbols": int(etf["SYMBOL"].nunique()) if len(etf) else 0,
            "new_symbols": [r["symbol"] for r in new_rows], "live_list_symbols": int(len(out)),
            "path": "ml/data_ext/etf_list_live.csv", "sha256": sha256_file(ETF_LIVE), "read_stats": st}


# --------------------------------------------------------------------------- fingerprints
def _feature_cols(con) -> tuple[list[str], list[str]]:
    cols = [r[0] for r in con.execute("DESCRIBE equity_features").fetchall()]
    fwd = [c for c in cols if c.startswith(FWD_PREFIX)]
    rest = [c for c in cols if c not in fwd and c not in ("ticker",)]
    return rest, fwd


def fingerprints(con, boundary: str) -> dict:
    rest, fwd = _feature_cols(con)
    def per_ticker(cols):
        sql = (f"SELECT ticker, count(*) AS n, bit_xor(hash({', '.join(cols)})) AS h FROM equity_features "
               f"WHERE date <= CAST(? AS TIMESTAMP) GROUP BY ticker ORDER BY ticker")
        d = con.execute(sql, [boundary]).df()
        return {t: (int(n), int(h)) for t, n, h in zip(d["ticker"], d["n"], d["h"])}
    eod_fp = [float(v) if v is not None else None for v in con.execute(
        "SELECT count(*), round(sum(close), 4), sum(volume), round(sum(turnover), 2), round(sum(prev_close), 4), "
        "count(DISTINCT date), count(DISTINCT ticker) FROM equity_eod WHERE date <= ?", [boundary]).fetchall()[0]]
    return {"non_forward": per_ticker(rest), "forward": per_ticker(["date"] + fwd), "eod": eod_fp,
            "non_forward_columns": len(rest), "forward_columns": fwd}


def compare_fingerprints(a: dict, b: dict, ca_tickers: set[str]) -> dict:
    def diff(x, y):
        ks = set(x) | set(y)
        return sorted(k for k in ks if x.get(k) != y.get(k))
    nf = diff(a["non_forward"], b["non_forward"])
    fw = diff(a["forward"], b["forward"])
    return {"tickers_compared": len(set(a["non_forward"]) | set(b["non_forward"])),
            "non_forward_columns": a["non_forward_columns"],
            "tickers_with_changed_non_forward_rows": nf,
            "changed_tickers_explained_by_new_corporate_actions": sorted(set(nf) & ca_tickers),
            "changed_tickers_unexplained": sorted(set(nf) - ca_tickers),
            "non_forward_unchanged_except_new_ca_tickers": not (set(nf) - ca_tickers),
            "tickers_with_changed_forward_label_columns": len(fw),
            "forward_columns": a["forward_columns"],
            "equity_eod_through_boundary": {"before": a["eod"], "after": b["eod"], "identical": a["eod"] == b["eod"]}}


def forward_change_dates(con, boundary: str, before_path: Path, ca_tickers: set[str] | None = None) -> dict:
    """Rows (<= boundary) whose forward label columns changed.  build_features shifts by rows within a ticker, so a
    ticker's last 5 rows before the new sessions gain values (they were NaN); a ticker with a new corporate action
    changes by the adjustment's rounding.  Anything else is unexplained."""
    _, fwd = _feature_cols(con)
    sel = ", ".join(["date", "ticker"] + fwd)
    cur = con.execute(f"SELECT {sel} FROM equity_features WHERE date <= CAST(? AS TIMESTAMP)", [boundary]).df()
    old = pd.read_parquet(before_path)
    j = cur.merge(old, on=["date", "ticker"], suffixes=("", "_b"), how="outer", indicator=True)
    ch = np.zeros(len(j), bool)
    was_nan = np.ones(len(j), bool)
    for c in fwd:
        x, y = pd.to_numeric(j[c], errors="coerce").to_numpy(float), pd.to_numeric(j[c + "_b"], errors="coerce").to_numpy(float)
        ch |= ~((x == y) | (np.isnan(x) & np.isnan(y)))
        was_nan &= np.isnan(y) | ~(~((x == y) | (np.isnan(x) & np.isnan(y))))
    cur = cur.sort_values(["ticker", "date"])
    cur["rows_after"] = cur.groupby("ticker").cumcount(ascending=False)
    jj = j.loc[ch, ["date", "ticker"]].merge(cur[["date", "ticker", "rows_after"]], on=["date", "ticker"], how="left")
    last5 = (jj["rows_after"] < 5).to_numpy() & was_nan[ch]
    cat = jj["ticker"].isin(ca_tickers or set()).to_numpy()
    other = ~last5 & ~cat
    dts = sorted({str(pd.Timestamp(d).date()) for d in j.loc[ch, "date"]})
    return {"rows_changed": int(ch.sum()), "rows_last5_of_ticker_previously_nan": int(last5.sum()),
            "rows_of_new_corporate_action_tickers": int((cat & ~last5).sum()),
            "rows_unexplained": int(other.sum()),
            "unexplained_examples": jj.loc[other, ["date", "ticker"]].astype(str).head(10).to_dict("records"),
            "first_date": dts[0] if dts else None, "last_date": dts[-1] if dts else None,
            "rows_only_in_one": int((j["_merge"] != "both").sum())}


# --------------------------------------------------------------------------- the write
def write_store(frames: list[tuple[date, pd.DataFrame]], changed_ca_tickers: set[str], dry: bool = False,
                checked_sessions: list[str] | None = None, reason: str | None = None) -> dict:
    """Upsert ``frames`` (none for a features-only rebuild) and build equity_features with the staged live feed,
    under the lock protocol; verify; promote the staged feed.  ``checked_sessions``: the sessions whose per-name
    prev_close breaks are verified (default: the new sessions)."""
    import duckdb
    kind = "sessions" if frames else "features_rebuild"
    res: dict = {"kind": kind, "sessions": [str(d) for d, _ in frames]}
    if reason:
        res["reason"] = reason
    if LOCK_FILE.exists():
        raise SystemExit(f"lock exists: {LOCK_FILE.read_text()}")
    if Path(str(DB_PATH) + ".wal").exists():
        raise SystemExit("a .wal file exists next to the store: another writer may be active")
    if not CA_FEED_STAGED.exists():
        raise SystemExit("no staged live feed: corporate_actions_live must run before the write")
    up = None
    if frames:
        up = pd.concat([f for _, f in frames], ignore_index=True)
        up = up[nhi.EOD_COLUMNS]
        if up.duplicated(["date", "ticker", "series"]).any():
            raise SystemExit("staged rows have duplicate (date, ticker, series) keys")
        eqbe = up[up["series"].isin(["EQ", "BE"])]
        if eqbe.duplicated(["date", "ticker"]).any():
            raise SystemExit("staged rows have a ticker in both EQ and BE on one date")
    # ---- fingerprints before (read-only), backup (before the lock, P1 convention) ----
    con = duckdb.connect(str(DB_PATH), read_only=True)
    con.execute("SET threads TO 2")
    t0 = time.time()
    fp_before = fingerprints(con, RESEARCH_END)
    _, fwd = _feature_cols(con)
    CACHE.mkdir(parents=True, exist_ok=True)
    fwd_before = CACHE / "forward_columns_before_write.parquet"
    con.execute(f"COPY (SELECT {', '.join(['date', 'ticker'] + fwd)} FROM equity_features WHERE date <= "
                f"CAST('{RESEARCH_END}' AS TIMESTAMP)) TO '{fwd_before}' (FORMAT PARQUET)")
    before = {"equity_eod_rows": con.execute("SELECT count(*) FROM equity_eod").fetchall()[0][0],
              "equity_features_rows": con.execute("SELECT count(*) FROM equity_features").fetchall()[0][0],
              "overwrites_existing_keys": 0}
    if up is not None:
        keys = up[["date", "ticker", "series"]].assign(date=lambda x: pd.to_datetime(x["date"]).dt.date)
        con.register("k_df", keys)
        before["overwrites_existing_keys"] = con.execute(
            "SELECT count(*) FROM equity_eod e JOIN k_df k ON e.date = k.date AND e.ticker = k.ticker "
            "AND e.series = k.series").fetchall()[0][0]
        con.unregister("k_df")
    last_before = str(con.execute("SELECT max(date) FROM equity_eod").fetchall()[0][0])
    con.close()
    res["fingerprint_seconds"] = round(time.time() - t0, 1)
    res["before"] = before
    if dry:
        res["dry_run"] = True
        return res
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    tag = f"{min(d for d, _ in frames):%Y%m%d}" if frames else f"rebuild_{today_ist():%Y%m%d}_after_{last_before[:10]}"
    backup = BACKUP_DIR / f"nse_market_backup_pre_q1_{tag}.duckdb"
    free = shutil.disk_usage(BACKUP_DIR).free
    size = os.path.getsize(DB_PATH)
    # the backup (1x) plus room for the store to grow while equity_features is rebuilt (it grew 0.67 GB on the
    # first write) and DuckDB's spill files: 1x + max(2 GB, 0.5x)
    need = size + max(2e9, 0.5 * size)
    if free < need:
        raise SystemExit(f"not enough free space for the backup and the write ({free / 1e9:.1f} GB free, "
                         f"{need / 1e9:.1f} GB needed for a {size / 1e9:.1f} GB store)")
    st0 = os.stat(DB_PATH)
    tb = time.time()
    shutil.copy2(DB_PATH, backup)
    st1 = os.stat(DB_PATH)
    if (st0.st_size, st0.st_mtime_ns) != (st1.st_size, st1.st_mtime_ns) or os.path.getsize(backup) != st1.st_size:
        backup.unlink(missing_ok=True)
        raise SystemExit("the store changed while it was being backed up; aborting before the lock")
    res["backup"] = {"path": repo_rel(backup), "bytes": os.path.getsize(backup), "seconds": round(time.time() - tb, 1),
                     "free_bytes_before": free}
    log(f"backup {repo_rel(backup)} ({res['backup']['seconds']} s)", "write")
    doing = (f"upsert {len(up):,} rows on {res['sessions']}; " if up is not None else f"no upsert ({reason}); ") + \
        "build_features with the live corporate-action feed"
    LOCK_FILE.write_text(json.dumps({
        "owner": "Q1 paper-book stream (ml/paper/ingest.py)", "started": datetime.now().isoformat(timespec="seconds"),
        "doing": doing, "pid": os.getpid()}, indent=1))
    tw0 = time.time()
    res["lock"] = {"path": "ml/results/improve/LOCK_duckdb_write", "created": True}
    log("LOCK created", "write")
    try:
        if os.stat(DB_PATH).st_mtime_ns != st1.st_mtime_ns:
            raise SystemExit("the store changed after the backup")
        store = nhi.DuckDBStore(str(DB_PATH))
        con = store.con
        con.execute("SET threads TO 2")
        con.execute("SET memory_limit = '4GB'")
        q = lambda sql, *p: con.execute(sql, list(p)).fetchall()  # noqa: E731
        n_up = 0
        if up is not None:
            con.execute("BEGIN TRANSACTION")
            n_up = store.upsert(up)
            dups = q("SELECT count(*) FROM (SELECT date, ticker FROM equity_eod WHERE series IN ('EQ','BE') "
                     "GROUP BY 1,2 HAVING count(*) > 1)")[0][0]
            if dups:
                con.execute("ROLLBACK")
                raise SystemExit(f"rolled back: {dups} EQ/BE (date, ticker) pairs would appear twice")
            con.execute("COMMIT")
            res["upsert"] = {"rows": int(n_up), "by_date": {str(pd.Timestamp(k).date()): int(v)
                                                             for k, v in up.groupby("date").size().items()}}
        tf = time.time()
        n_feat = nhi.build_features(con, ca_csv=str(CA_FEED_STAGED))
        res["build_features"] = {"rows": int(n_feat), "seconds": round(time.time() - tf, 1),
                                 "ca_csv": "ml/data_ext/corporate_actions_feed_live.csv (staged in "
                                           f"{repo_rel(CA_FEED_STAGED)}, promoted after the write)"}
        log(f"build_features {n_feat:,} rows ({res['build_features']['seconds']} s)", "write")
        after = {"equity_eod_rows": q("SELECT count(*) FROM equity_eod")[0][0],
                 "equity_features_rows": q("SELECT count(*) FROM equity_features")[0][0],
                 "eq_be_dup_date_ticker": q("SELECT count(*) FROM (SELECT date, ticker FROM equity_eod WHERE "
                                            "series IN ('EQ','BE') GROUP BY 1,2 HAVING count(*) > 1)")[0][0],
                 "rows_on_new_dates": {str(d): q("SELECT count(*) FROM equity_eod WHERE date = ?", d)[0][0]
                                       for d, _ in frames},
                 "features_rows_on_new_dates": {str(d): q("SELECT count(*) FROM equity_features WHERE date = "
                                                          "CAST(? AS TIMESTAMP)", str(d))[0][0] for d, _ in frames}}
        after["expected_equity_eod_rows"] = before["equity_eod_rows"] + int(n_up) - int(before["overwrites_existing_keys"])
        after["row_count_as_expected"] = after["equity_eod_rows"] == after["expected_equity_eod_rows"]
        after["equity_features_rows_equal_eq_be_rows"] = (
            after["equity_features_rows"] == q("SELECT count(*) FROM equity_eod WHERE series IN ('EQ','BE')")[0][0])
        scan = nhi.check_sessions(con)
        scan["date"] = pd.to_datetime(scan["date"])
        new_d = [pd.Timestamp(d) for d, _ in frames]
        ns = scan[scan["date"].isin(new_d)]
        after["continuity_new_sessions"] = [{"date": str(r.date.date()), "n_with_prev": int(r.n_with_prev),
                                             "n_mismatch": int(r.n_mismatch), "share": float(r.share),
                                             "flagged": bool(r.flagged)} for r in ns.itertuples(index=False)]
        after["continuity_store"] = {"max_share": float(scan["share"].max()),
                                     "flagged": [str(d.date()) for d in scan.loc[scan["flagged"], "date"]]}
        res["after"] = after
        con.execute("CHECKPOINT")
        store.close()
    finally:
        LOCK_FILE.unlink(missing_ok=True)
        res["lock"]["window_seconds"] = round(time.time() - tw0, 1)
        res["lock"]["removed"] = not LOCK_FILE.exists()
        log("LOCK removed", "write")
    old_keys = feed_keys(CA_FEED_LIVE) if CA_FEED_LIVE.exists() else feed_keys(CA_FEED_10Y)
    added = sorted({(k[0], k[1]) for k in feed_keys(CA_FEED_STAGED) - old_keys})
    res["feed_lines_added"] = [{"ticker": t, "ex_date": d} for t, d in added]
    res["live_feed_sha256"] = promote_feed()       # the store is now built with it
    # ---- read-only verification after the lock (the store is no longer written) ----
    # an exception here must not leave the write unrecorded: it becomes a failed check, the backup is kept and the
    # job stops on the unresolved write (RUNBOOK section 5)
    try:
        con = duckdb.connect(str(DB_PATH), read_only=True)
        con.execute("SET threads TO 2")
        fp_after = fingerprints(con, RESEARCH_END)
        after["fingerprint_through_research_end"] = compare_fingerprints(fp_before, fp_after, changed_ca_tickers)
        after["forward_label_changes_through_research_end"] = forward_change_dates(con, RESEARCH_END, fwd_before,
                                                                              changed_ca_tickers)
        feed = pd.read_csv(CA_FEED_LIVE)
        if added:                                       # adjusted close-to-close move on each added ex-date (info)
            from ml.integrity.write_phase import known_events_check
            fd = pd.read_csv(CA_FEED_LIVE, dtype={"ex_date": str})
            ev = [(t, d) for t, d in added]
            tk = sorted({t for t, _ in added})
            ef = con.execute("SELECT date, ticker, close, close_unadj FROM equity_features WHERE ticker IN ("
                             + ",".join("?" * len(tk)) + ") ORDER BY ticker, date", tk).df()
            after["new_events_check"] = known_events_check(ef, fd, ev)
        chk = checked_sessions if checked_sessions is not None else [str(d) for d, _ in frames]
        res["checked_sessions"] = chk
        after["price_breaks"] = price_breaks(eq_be_rows_store(con), chk, feed, ca_all_live())
        con.close()
        a = res["after"]
        checks = {"row_count_as_expected": bool(a["row_count_as_expected"]),
                  "equity_features_rows_equal_eq_be_rows": bool(a["equity_features_rows_equal_eq_be_rows"]),
                  "no_duplicate_eq_be_pairs": a["eq_be_dup_date_ticker"] == 0,
                  "continuity_share_below_5pct": all(not x["flagged"] for x in a["continuity_new_sessions"]),
                  "no_unexplained_price_break": a["price_breaks"]["n_unexplained"] == 0,
                  "non_forward_unchanged_except_changed_ca_tickers":
                      bool(a["fingerprint_through_research_end"]["non_forward_unchanged_except_new_ca_tickers"]),
                  "equity_eod_through_research_end_identical":
                      bool(a["fingerprint_through_research_end"]["equity_eod_through_boundary"]["identical"]),
                  "forward_label_changes_explained": a["forward_label_changes_through_research_end"]["rows_unexplained"] == 0}
    except Exception as exc:  # noqa: BLE001
        res["verification_error"] = repr(exc)
        log(f"verification raised {exc!r}", "write")
        checks = {"verification_completed": False}
    res["checks"] = checks
    ok = all(checks.values())
    res["verified"] = bool(ok)
    if ok:
        backup.unlink(missing_ok=True)
        res["backup"]["deleted_after_verification"] = True
        log("verification passed; backup deleted", "write")
    else:
        res["backup"]["deleted_after_verification"] = False
        log(f"VERIFICATION FAILED ({[k for k, v in checks.items() if not v]}): backup kept at {repo_rel(backup)}",
            "write")
    return res


def rebuild_features_locked(reason: str) -> dict:
    """build_features(con, ca_csv=<live feed>) under the lock, for a store whose equity_features is behind
    equity_eod (e.g. a run killed between the upsert and the rebuild)."""
    if LOCK_FILE.exists():
        raise SystemExit(f"lock exists: {LOCK_FILE.read_text()}")
    LOCK_FILE.write_text(json.dumps({"owner": "Q1 paper-book stream (ml/paper/ingest.py)",
                                     "started": datetime.now().isoformat(timespec="seconds"),
                                     "doing": f"build_features only ({reason})", "pid": os.getpid()}, indent=1))
    t0 = time.time()
    try:
        store = nhi.DuckDBStore(str(DB_PATH))
        store.con.execute("SET threads TO 2")
        store.con.execute("SET memory_limit = '4GB'")
        n = nhi.build_features(store.con, ca_csv=str(CA_FEED_LIVE))
        store.con.execute("CHECKPOINT")
        store.close()
    finally:
        LOCK_FILE.unlink(missing_ok=True)
    return {"reason": reason, "rows": int(n), "seconds": round(time.time() - t0, 1)}


def export_live() -> dict:
    """EQ/BE rows and equity_features prices of the store (read-only), schema of the ten-year exports."""
    import duckdb
    import pyarrow.parquet as pq
    t0 = time.time()
    con = duckdb.connect(str(DB_PATH), read_only=True)

    def table(sql):
        r = con.execute(sql).arrow()
        return r.read_all() if hasattr(r, "read_all") else r
    eod = table("SELECT date, ticker, series, prev_close, open, high, low, last, close, vwap, volume, turnover, "
                "trades, deliv_qty, deliv_pct FROM equity_eod WHERE series IN ('EQ','BE') ORDER BY ticker, date")
    fp = table("SELECT date, ticker, open, high, low, close, volume, turnover, deliv_pct, open_unadj, close_unadj "
               "FROM equity_features ORDER BY ticker, date")
    con.close()
    CACHE.mkdir(parents=True, exist_ok=True)
    ref_dir = EOD_10Y.parent
    out = {}
    for path, tab, ref in ((EOD_LIVE, eod, "eod_export_10y.parquet"), (FEAT_LIVE, fp, "features_prices_export_10y.parquet")):
        sch = pq.read_schema(ref_dir / ref)
        if tab.schema != sch:
            tab = tab.cast(sch)
        tmp = path.with_name(path.name + ".tmp")
        pq.write_table(tab, tmp)
        tmp.replace(path)
        out[path.name] = int(tab.num_rows)
    out["seconds"] = round(time.time() - t0, 1)
    return out


def export_current() -> bool:
    """True when the live exports exist and match the store's EQ/BE row count and last session."""
    if not (EOD_LIVE.exists() and FEAT_LIVE.exists()):
        return False
    st = store_summary()
    e = pd.read_parquet(EOD_LIVE, columns=["date"])
    return len(e) == st["equity_eod_eq_be_rows"] and str(pd.Timestamp(e["date"].max()).date()) == st["last_session"]


def regenerate_live_feed(last_session: str) -> dict:
    """The live feed is gitignored (ml/data_ext/, like the store).  When it is missing after the store has sessions
    past the research end, rebuild it with the same code path from the store's own EQ/BE rows and every PR bundle on
    disk, and check it against the SHA-256 that ml/paper/ledger/state.json recorded: the store's equity_features were
    built with that feed, so a different one stops the job (RUNBOOK section 6, 'lost state')."""
    from ml.paper.common import STATE_JSON
    if not export_current():
        export_live()
    res = corporate_actions_live([], last_session)
    want = json.loads(STATE_JSON.read_text()).get("inputs", {}).get("ca_feed_live_sha256") if STATE_JSON.exists() else None
    got = res["live_feed"]["sha256"]
    log(f"live corporate-action feed was missing: regenerated ({res['live_feed']['rows']} rows), sha256 {got[:16]} "
        f"vs state.json {str(want)[:16]}", "ca")
    if want is not None and got != want:
        CA_FEED_STAGED.unlink(missing_ok=True)        # never put a feed the store was not built with in place
        raise SystemExit("the regenerated live corporate-action feed differs from the one the store was built with "
                         f"(state.json {want[:16]}, regenerated {got[:16]}); see ml/paper/RUNBOOK.md section 6")
    promote_feed()
    return {"rows": res["live_feed"]["rows"], "sha256": got, "equals_state_json": want == got if want else None,
            "new_validated_events": res["new_validated_events"]}


# --------------------------------------------------------------------------- unverified writes
def _covered(w: dict) -> set[str]:
    x = w.get("write") or {}
    return set(x.get("checked_sessions") or x.get("sessions") or w.get("accepted") or [])


def unresolved_writes(hist: dict | None = None) -> list[dict]:
    """Writes of ingest.json whose verification failed, that no operator accepted, and that no later verified write
    re-checked (a later verified write whose checked sessions include all of the failed write's sessions, e.g. the
    re-ingest after restoring the backup, or a --rebuild-features repair, which checks every session after the
    research end)."""
    if hist is None:
        if not INGEST_JSON.exists():
            return []
        hist = json.loads(INGEST_JSON.read_text())
    ws = hist.get("writes") or []
    out = []
    for i, w in enumerate(ws):
        x = w.get("write")
        if not x or x.get("verified", True) or w.get("operator_acceptance"):
            continue
        need = _covered(w)
        if any((v.get("write") or {}).get("verified") and need <= _covered(v) for v in ws[i + 1:]):
            continue
        out.append(w)
    return out


def unverified_write() -> dict | None:
    """The latest unresolved write (the job stops on it: RUNBOOK section 5)."""
    u = unresolved_writes()
    return u[-1] if u else None


def accept_unverified_write(reason: str) -> dict:
    """Record an operator's acceptance of every unresolved write (RUNBOOK section 5); the job then proceeds."""
    hist = json.loads(INGEST_JSON.read_text())
    u = unresolved_writes(hist)
    if not u:
        raise SystemExit("no unresolved store write; nothing to accept")
    acc = {"reason": reason, "date_ist": str(today_ist())}
    ids = {id(w) for w in u}
    for w in hist["writes"]:
        if id(w) in ids:
            w["operator_acceptance"] = acc
    wjson(INGEST_JSON, hist)
    return {**acc, "writes": [w.get("accepted") or w.get("write", {}).get("kind") for w in u]}


def _record_write(rec: dict) -> None:
    hist = json.loads(INGEST_JSON.read_text()) if INGEST_JSON.exists() else {"writes": []}
    hist["writes"].append({k: v for k, v in rec.items() if k not in ("network_calls", "seconds", "exports")})
    hist["last_store"] = rec.get("store_after")
    wjson(INGEST_JSON, hist)


# --------------------------------------------------------------------------- entry points
def run(today: date | None = None, dry: bool = False) -> dict:
    t0 = time.time()
    held = unverified_write()
    if held is not None and not dry:
        st = store_summary()
        sess = sorted(held.get("accepted") or [])
        if not sess or st["last_session"] >= sess[-1]:
            msg = (f"held: the store write of {sess or held['write'].get('kind')} failed verification "
                   f"({[k for k, v in (held['write'].get('checks') or {}).items() if not v]}) and is unresolved; no new "
                   "session is ingested until it is (RUNBOOK section 5)")
            log(msg, "ingest")
            return {"run_today_ist": str(today_ist()), "held": msg, "decisions": [], "accepted": [],
                    "store_changed": False, "seconds": round(time.time() - t0, 1)}
    dec = decide_sessions(today)
    frames = dec.pop("_frames")
    rec = {"run_today_ist": dec["today_ist"], **dec}
    log(f"candidates {dec['candidates']}; accepted {dec['accepted']}; "
        + "; ".join(f"{r['date']}: {r['decision']}" for r in dec["decisions"]), "ingest")
    changed = False
    if any(r["decision"].startswith(("closure", "session")) for r in dec["decisions"]) and not dry:
        record_calendar(dec)
    if frames:
        last_new = str(max(d for d, _ in frames))
        rec["corporate_actions"] = corporate_actions_live(frames, last_new)
        rec["etf"] = etf_live()
        chg = set(rec["corporate_actions"]["tickers_whose_feed_lines_change"])
        rec["write"] = write_store(frames, chg, dry=dry)
        changed = not dry
        if not dry:
            rec["store_after"] = store_summary()
    else:
        if not ETF_LIVE.exists():
            rec["etf"] = etf_live()
        if not CA_FEED_LIVE.exists():
            st0 = dec["store_before"]
            if st0["last_session"] <= RESEARCH_END:     # no session after the research end yet: live = ten-year feed
                shutil.copyfile(CA_FEED_10Y, CA_FEED_LIVE)
            elif not dry:
                rec["corporate_actions_regenerated"] = regenerate_live_feed(st0["last_session"])
    if not dry:
        st = store_summary()
        if st["equity_features_last"][:10] < st["last_session"]:
            rec["repair"] = rebuild_features_locked(f"equity_features ends {st['equity_features_last'][:10]}, "
                                                    f"equity_eod {st['last_session']}")
            changed = True
    if not dry and (changed or not export_current()):
        rec["exports"] = export_live()
    rec["seconds"] = round(time.time() - t0, 1)
    rec["store_changed"] = changed
    if changed:
        _record_write(rec)
    return rec


def rebuild_with_feed(reason: str) -> dict:
    """Repair path (no new session): re-derive the live feed with the current code from the store's EQ/BE rows and
    every PR bundle on disk, rebuild equity_features with it under the lock protocol, and verify, re-checking the
    per-name prev_close breaks of every session after the research end.  Recorded in ingest.json as a write of kind
    'features_rebuild'; a verified one resolves earlier unverified writes it re-checked."""
    t0 = time.time()
    if not export_current():
        export_live()
    st = store_summary()
    import duckdb
    con = duckdb.connect(str(DB_PATH), read_only=True)
    sess = [str(pd.Timestamp(d).date()) for (d,) in con.execute(
        "SELECT DISTINCT date FROM equity_eod WHERE date > CAST(? AS DATE) ORDER BY 1", [RESEARCH_END]).fetchall()]
    con.close()
    rec = {"run_today_ist": str(today_ist()), "kind": "features_rebuild", "reason": reason, "store_before": st}
    rec["corporate_actions"] = corporate_actions_live([], st["last_session"])
    old_sha = sha256_file(CA_FEED_LIVE) if CA_FEED_LIVE.exists() else None
    rec["live_feed_before_sha256"] = old_sha
    chg = set(rec["corporate_actions"]["tickers_whose_feed_lines_change"])
    log(f"rebuild with the live feed ({reason}): feed lines change for {sorted(chg)}", "write")
    rec["write"] = write_store([], chg, checked_sessions=sess, reason=reason)
    rec["store_after"] = store_summary()
    rec["exports"] = export_live()
    rec["store_changed"] = True
    rec["seconds"] = round(time.time() - t0, 1)
    _record_write(rec)
    return rec


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="decide and stage, no write")
    ap.add_argument("--rebuild-features", metavar="REASON", default=None,
                    help="repair path: re-derive the live feed and rebuild equity_features (RUNBOOK section 5)")
    a = ap.parse_args()
    if a.rebuild_features:
        out = rebuild_with_feed(a.rebuild_features)
    else:
        out = run(dry=a.dry_run)
    print(dumps({k: v for k, v in out.items() if k != "network_calls"}))

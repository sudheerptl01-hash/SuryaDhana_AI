"""Daily ingest of the paper book: new sessions into nse_market.duckdb (the only writer in phase 2).

Order of a run
  1. candidate dates = nse_historical_ingest.trading_days(last stored session + 1, today IST) with the
     ingest's holiday and special-session sets plus the closures/special sessions this stream recorded in
     ml/paper/calendar_live.json;
  2. per candidate, in date order: nse_historical_ingest.fetch_day (sec_bhavdata_full + CM enrichment,
     legacy then UDiFF, merge_sources) through a polite, disk-caching adapter; the file's own DATE1 column;
     the duplicate-day guard (frame_fingerprint vs the previous session); the PR bundle (exists and its pd
     member carries the date).  Session / closure / pending / unresolved (SPEC.md 2.6);
  3. corporate actions: ml/integrity/corporate_actions.build unchanged over every PR bundle on disk (outputs
     redirected to ml/paper/state/ca/), validated split/bonus events with an ex-date after the research end
     appended to the ten-year feed -> ml/data_ext/corporate_actions_feed_live.csv;
     ETF symbols of the live bundles -> ml/data_ext/etf_list_live.csv;
  4. the write (lock protocol of phase 1): backup copy in the scratchpad (free space checked), lock file,
     one transaction with DuckDBStore.upsert (rolled back if any EQ/BE (date, ticker) pair would appear
     twice), build_features(con, ca_csv=<live feed>), verification (continuity scan on the new sessions,
     duplicates, equity_eod and equity_features fingerprints for dates <= the research end), CHECKPOINT,
     lock removed; the backup is deleted once verification passed;
  5. parquet exports of the updated store for the book's prices (ml/paper/state/cache/).

Downloaded files live in ml/paper/state/raw/{sec,cm,pr}/ (one folder per kind, no code there) and are only
parsed as data.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import nse_historical_ingest as nhi
from ml.paper.common import dumps, log, sha256_file, wjson
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
SCRATCH = Path("/tmp/claude-0/-home-user-SuryaDhana-AI/a2334483-114a-5057-9fd0-81f0f14285e9/scratchpad/q1")
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
    for d in cands:
        rec = {"date": str(d), "weekday": d.strftime("%A")}
        sec_url = nhi.SEC_DELIVERY_URL.format(ddmmyyyy=d.strftime("%d%m%Y"))
        raw = ad.get(sec_url)
        pr_name = f"PR{d:%d%m%y}.zip"
        if raw is None:
            if d >= today:
                rec["decision"] = "pending: file not yet published"
                decisions.append(rec)
                break
            pr = ad.get(PR_URL.format(ddmmyy=d.strftime("%d%m%y")))
            rec["sec_http"] = 404
            rec["pr_bundle"] = "present" if pr is not None else "absent"
            if pr is None:
                rec["decision"] = "closure: no sec file and no PR bundle"
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
        if is_session:
            rec["decision"] = "session: ingest"
            accepted.append((d, df))
        elif is_echo:
            rec["decision"] = "closure: holiday echo of the previous session (duplicate-day guard) and no PR bundle"
        else:
            rec["decision"] = "unresolved: evidence disagrees"
            decisions.append(rec)
            break
        decisions.append(rec)
    return {"today_ist": str(today), "store_before": st, "candidates": [str(d) for d in cands],
            "decisions": decisions, "accepted": [str(d) for d, _ in accepted],
            "network_calls": [c for c in ad.calls if c["source"] == "network"],
            "_frames": accepted}


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


def corporate_actions_live(frames: list[tuple[date, pd.DataFrame]], last_session: str) -> dict:
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
    try:
        ca.OUT, ca.DATA_EXT = CA_DIR, CA_DIR
        ca.log = lambda m, tag="ca": log(m, "ca")
        ca.completeness = comp_live
        ca.BUNDLE_DIRS[:] = list(PR_DIRS_RESEARCH) + [RAW_PR]
        t0 = time.time()
        res = ca.build(eod, suffix="_live_full")
        secs = round(time.time() - t0, 1)
    finally:
        ca.OUT, ca.DATA_EXT, ca.log, ca.completeness = saved["OUT"], saved["DATA_EXT"], saved["log"], saved["completeness"]
        ca.BUNDLE_DIRS[:] = saved["dirs"]
    full = pd.read_csv(CA_DIR / "corporate_actions_feed_live_full.csv")
    allr = pd.read_csv(CA_DIR / "corporate_actions_all_live_full.csv", low_memory=False)
    brk = pd.read_csv(CA_DIR / "price_break_flags_live_full.csv")
    f10 = pd.read_csv(CA_FEED_10Y)
    key = lambda d: set(zip(d["ticker"], d["ex_date"], np.round(d["ratio"].astype(float), 12)))  # noqa: E731
    old_full = full[full["ex_date"] <= RESEARCH_END]
    new = full[(full["ex_date"] > RESEARCH_END) & (full["ex_date"] <= last_session)].copy()
    new = new[~new.set_index(["ticker", "ex_date"]).index.isin(f10.set_index(["ticker", "ex_date"]).index)]
    live = pd.concat([f10, new[f10.columns]], ignore_index=True).sort_values(["ticker", "ex_date"],
                                                                            kind="stable").reset_index(drop=True)
    tmp = CA_FEED_LIVE.with_name(CA_FEED_LIVE.name + ".tmp")
    live.to_csv(tmp, index=False)
    tmp.replace(CA_FEED_LIVE)
    exd = allr["ex_date"].fillna("").astype(str)
    win = (exd > RESEARCH_END) & (exd <= last_session)
    adjustable = allr["kind"].astype(str).str.contains("split|bonus|consolidation", regex=True)
    unvalidated = allr[win & adjustable & (allr["validated"].astype(str) != "True")
                       & allr["status"].isin(["ok", "ex_date_shifted"])]
    upcoming = allr[(exd > last_session) & adjustable].drop_duplicates(["ticker", "ex_date", "purpose"])
    return {"seconds": secs, "bundle_dirs": [str(p) for p in list(PR_DIRS_RESEARCH) + [RAW_PR]],
            "eod_sources": srcs, "I2_rebuilt_feed": res.get("I2"),
            "feed_10y_rows": int(len(f10)), "rebuilt_feed_rows_through_research_end": int(len(old_full)),
            "rebuilt_vs_10y_through_research_end": {
                "only_in_rebuilt": sorted(map(list, key(old_full) - key(f10)))[:50],
                "only_in_10y": sorted(map(list, key(f10) - key(old_full)))[:50],
                "identical": key(old_full) == key(f10)},
            "new_validated_events": new[["ticker", "ex_date", "ratio", "kind", "source"]].to_dict("records"),
            "unvalidated_adjustable_events_in_window": unvalidated[["ticker", "ex_date", "kind", "purpose",
                                                                    "observed_ratio"]].to_dict("records"),
            "price_breaks_in_window": brk[(brk["ex_date"].astype(str) > RESEARCH_END)
                                          & (brk["ex_date"].astype(str) <= last_session)].to_dict("records"),
            "upcoming_adjustable_events": upcoming[["ticker", "ex_date", "kind", "purpose"]].to_dict("records"),
            "live_feed": {"path": "ml/data_ext/corporate_actions_feed_live.csv", "rows": int(len(live)),
                          "sha256": sha256_file(CA_FEED_LIVE)},
            "completeness_live_bundles": {k: res["completeness"].get(k) for k in
                                          ("corp_ind_with_abs_ret_gt_22pct", "covered_by_feed", "n_missing", "missing")}}


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
def write_store(frames: list[tuple[date, pd.DataFrame]], new_ca_tickers: set[str], dry: bool = False) -> dict:
    import duckdb
    res: dict = {"sessions": [str(d) for d, _ in frames]}
    if LOCK_FILE.exists():
        raise SystemExit(f"lock exists: {LOCK_FILE.read_text()}")
    if Path(str(DB_PATH) + ".wal").exists():
        raise SystemExit("a .wal file exists next to the store: another writer may be active")
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
              "equity_features_rows": con.execute("SELECT count(*) FROM equity_features").fetchall()[0][0]}
    keys = up[["date", "ticker", "series"]].assign(date=lambda x: pd.to_datetime(x["date"]).dt.date)
    con.register("k_df", keys)
    before["overwrites_existing_keys"] = con.execute(
        "SELECT count(*) FROM equity_eod e JOIN k_df k ON e.date = k.date AND e.ticker = k.ticker "
        "AND e.series = k.series").fetchall()[0][0]
    con.unregister("k_df")
    con.close()
    res["fingerprint_seconds"] = round(time.time() - t0, 1)
    res["before"] = before
    if dry:
        res["dry_run"] = True
        return res
    SCRATCH.mkdir(parents=True, exist_ok=True)
    backup = SCRATCH / f"nse_market_backup_pre_q1_{min(d for d, _ in frames):%Y%m%d}.duckdb"
    free = shutil.disk_usage(SCRATCH).free
    size = os.path.getsize(DB_PATH)
    if free < 2 * size + 2e9:
        raise SystemExit(f"not enough free space for the backup ({free / 1e9:.1f} GB free, store {size / 1e9:.1f} GB)")
    st0 = os.stat(DB_PATH)
    tb = time.time()
    shutil.copy2(DB_PATH, backup)
    st1 = os.stat(DB_PATH)
    if (st0.st_size, st0.st_mtime_ns) != (st1.st_size, st1.st_mtime_ns) or os.path.getsize(backup) != st1.st_size:
        backup.unlink(missing_ok=True)
        raise SystemExit("the store changed while it was being backed up; aborting before the lock")
    res["backup"] = {"path": str(backup), "bytes": os.path.getsize(backup), "seconds": round(time.time() - tb, 1),
                     "free_bytes_before": free}
    log(f"backup {backup} ({res['backup']['seconds']} s)", "write")
    LOCK_FILE.write_text(json.dumps({
        "owner": "Q1 paper-book stream (ml/paper/ingest.py)", "started": datetime.now().isoformat(timespec="seconds"),
        "doing": f"upsert {len(up):,} rows on {res['sessions']}; build_features with the live corporate-action feed",
        "pid": os.getpid()}, indent=1))
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
        n_feat = nhi.build_features(con, ca_csv=str(CA_FEED_LIVE))
        res["build_features"] = {"rows": int(n_feat), "seconds": round(time.time() - tf, 1),
                                 "ca_csv": "ml/data_ext/corporate_actions_feed_live.csv"}
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
    # ---- read-only verification after the lock (the store is no longer written) ----
    con = duckdb.connect(str(DB_PATH), read_only=True)
    con.execute("SET threads TO 2")
    fp_after = fingerprints(con, RESEARCH_END)
    after["fingerprint_through_research_end"] = compare_fingerprints(fp_before, fp_after, new_ca_tickers)
    after["forward_label_changes_through_research_end"] = forward_change_dates(con, RESEARCH_END, fwd_before,
                                                                          new_ca_tickers)
    if new_ca_tickers:
        from ml.integrity.write_phase import known_events_check
        feed = pd.read_csv(CA_FEED_LIVE)
        ev = [(t, d) for t, d in zip(feed["ticker"], feed["ex_date"]) if t in new_ca_tickers and d > RESEARCH_END]
        ef = con.execute("SELECT date, ticker, close, close_unadj FROM equity_features WHERE ticker IN ("
                         + ",".join("?" * len(new_ca_tickers)) + ") ORDER BY ticker, date",
                         sorted(new_ca_tickers)).df()
        after["new_events_check"] = known_events_check(ef, feed, ev)
    con.close()
    a = res["after"]
    ok = (a["row_count_as_expected"] and a["eq_be_dup_date_ticker"] == 0
          and all(not x["flagged"] for x in a["continuity_new_sessions"])
          and a["fingerprint_through_research_end"]["non_forward_unchanged_except_new_ca_tickers"]
          and a["fingerprint_through_research_end"]["equity_eod_through_boundary"]["identical"]
          and a["forward_label_changes_through_research_end"]["rows_unexplained"] == 0)
    res["verified"] = bool(ok)
    if ok:
        backup.unlink(missing_ok=True)
        res["backup"]["deleted_after_verification"] = True
        log("verification passed; backup deleted", "write")
    else:
        res["backup"]["deleted_after_verification"] = False
        log("VERIFICATION FAILED: backup kept", "write")
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


# --------------------------------------------------------------------------- entry point
def run(today: date | None = None, dry: bool = False) -> dict:
    t0 = time.time()
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
        new_ca = {r["ticker"] for r in rec["corporate_actions"]["new_validated_events"]}
        rec["write"] = write_store(frames, new_ca, dry=dry)
        changed = not dry
        if not dry:
            rec["store_after"] = store_summary()
    else:
        if not ETF_LIVE.exists():
            rec["etf"] = etf_live()
        if not CA_FEED_LIVE.exists():               # no session after the research end yet: live feed = ten-year feed
            shutil.copyfile(CA_FEED_10Y, CA_FEED_LIVE)
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
        hist = json.loads(INGEST_JSON.read_text()) if INGEST_JSON.exists() else {"writes": []}
        hist["writes"].append({k: v for k, v in rec.items() if k not in ("network_calls", "seconds", "exports")})
        hist["last_store"] = rec.get("store_after")
        wjson(INGEST_JSON, hist)
    return rec


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="decide and stage, no write")
    a = ap.parse_args()
    print(dumps({k: v for k, v in run(dry=a.dry_run).items() if k != "network_calls"}))

#!/usr/bin/env python3
"""Session integrity of nse_market.duckdb (P1, ml/IMPROVEMENT_PLAN.md).

1. prev_close continuity scan on the parquet export (EQ/BE rows): for every
   (ticker, date) with a stored previous row, mismatch = |reported prev_close -
   stored previous close| > 0.005; per-date share = mismatches / rows with a
   stored previous row.  A date is flagged when the share exceeds 5% (I1 mark).
2. Candidate missing sessions = calendar days strictly between a flagged date
   and the stored session before it.  For each candidate the archive's
   sec_bhavdata_full file is fetched; it is kept when it parses, its own DATE1
   column names the candidate date and it is not a byte-identical (or
   fingerprint-identical) echo of the previous stored session.
3. Kept sessions are standardised with nse_historical_ingest's own parsers and
   fetch_day's enrichment order (legacy CM bhavcopy, UDiFF fallback, merge_sources).
4. 2022-03-08: the archive's sec_bhavdata_full_07032022.csv carries no BE/BZ
   rows, so the store has none for 2022-03-07.  The rows are rebuilt from the
   CM bhavcopy (cm07MAR2022bhav.csv.zip) + the MTO delivery file, with a
   construction that is first cross-validated on 2022-03-08 against that day's
   complete security-wise file.
5. Calendar audit: a PR bundle exists for every session and 404s on a closure
   (it is not echoed).  Every stored date without a bundle and every bundle date
   without stored rows is resolved through the DATE1 column of the archive's own
   files: e.g. the archive serves the 03-Nov-2021 file under 04-Nov's name and the
   04-Nov Muhurat session under 05-Nov's name (a closure), so the store holds that
   session dated 2021-11-05; such rows are re-dated (delete + insert).
6. Store-vs-PR audit (after the PR download): every stored session's closes
   against the same day's pd file in the PR bundle.

Outputs: ml/data_ext/staging/sessions_upsert.parquet (rows to upsert),
ml/data_ext/staging/sessions_delete.json (dates to delete before the upsert),
ml/results/improve/integrity/sessions.json.

Run: OMP_NUM_THREADS=2 python3 -I ml/integrity/sessions.py [--audit]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import sys
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import nse_historical_ingest as nhi  # noqa: E402
from ml.integrity.common import (DATA_EXT, EOD_EXPORT, MISSING_SESSIONS, OUT, RAW, RAW_CM,  # noqa: E402
                                 RAW_SEC, SEC_URL, PoliteGetter, atomic_write_bytes, bundle_inner_date,
                                 bundle_ok, log, pr_name, sec_name, wjson)

STAGING = DATA_EXT / "staging"
RAW_MTO = RAW / "mto"
TOL = 0.005
FLAG_SHARE = 0.05
MONTHS = nhi.MONTHS
LEGACY_CM = "https://archives.nseindia.com/content/historical/EQUITIES/{yyyy}/{mon}/cm{dd}{mon}{yyyy}bhav.csv.zip"
UDIFF_CM = "https://archives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{yyyymmdd}_F_0000.csv.zip"
MTO_URL = "https://archives.nseindia.com/archives/equities/mto/MTO_{ddmmyyyy}.DAT"
SERIES_KEPT = ["EQ", "BE", "BZ", "SM", "ST"]
_G: PoliteGetter | None = None


def getter() -> PoliteGetter:
    global _G
    if _G is None:
        _G = PoliteGetter(tag="sessions")
    return _G


def fetch_file(url: str, path: Path) -> tuple[int, bytes | None]:
    """Resume-safe: read from disk if present, else fetch politely and save."""
    if path.exists() and path.stat().st_size > 0:
        return 200, path.read_bytes()
    st, body = getter().get(url)
    if st == 200 and body:
        atomic_write_bytes(path, body)
    log(f"fetched {path.name} -> {st}", "sessions")
    return st, body


# --------------------------------------------------------------------------- #
# 1. continuity scan
# --------------------------------------------------------------------------- #
def load_eod() -> pd.DataFrame:
    e = pd.read_parquet(EOD_EXPORT)
    e["date"] = pd.to_datetime(e["date"]).astype("datetime64[ns]")
    return e.sort_values(["ticker", "date"]).reset_index(drop=True)


def continuity_scan(eod: pd.DataFrame, tol: float = TOL) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per-date mismatch share and the row-level mismatches (EQ/BE rows)."""
    e = eod.sort_values(["ticker", "date"]).reset_index(drop=True)
    g = e.groupby("ticker", sort=False)
    prev = g["close"].shift(1)
    prev_date = g["date"].shift(1)
    has = prev.notna() & e["prev_close"].notna()
    mm = has & ((e["prev_close"] - prev).abs() > tol)
    per = pd.DataFrame({"date": e["date"], "has": has, "mm": mm}).groupby("date").agg(
        n_with_prev=("has", "sum"), n_mismatch=("mm", "sum"), n_rows=("has", "size"))
    per["share"] = per["n_mismatch"] / per["n_with_prev"].where(per["n_with_prev"] > 0)
    rows = e.loc[mm, ["date", "ticker", "series", "prev_close"]].copy()
    rows["stored_prev_close"] = prev[mm].to_numpy()
    rows["stored_prev_date"] = prev_date[mm].to_numpy()
    return per.reset_index(), rows.reset_index(drop=True)


def candidate_days(per: pd.DataFrame, flag_share: float = FLAG_SHARE) -> dict[str, dict]:
    dates = pd.DatetimeIndex(sorted(per["date"]))
    out = {}
    for _, r in per[per["share"] > flag_share].iterrows():
        d = pd.Timestamp(r["date"])
        pos = dates.get_loc(d)
        p = dates[pos - 1] if pos > 0 else None
        gap = []
        if p is not None:
            x = p + timedelta(days=1)
            while x < d:
                gap.append(x.date())
                x += timedelta(days=1)
        out[str(d.date())] = {"share": float(r["share"]), "n_mismatch": int(r["n_mismatch"]),
                              "n_with_prev": int(r["n_with_prev"]),
                              "prev_stored_session": str(p.date()) if p is not None else None,
                              "gap_days": [str(x) for x in gap]}
    return out


# --------------------------------------------------------------------------- #
# 2-3. candidate sessions
# --------------------------------------------------------------------------- #
def _date1(raw: bytes) -> list[str]:
    t = nhi._read_bhav_table(raw)
    t.columns = [c.strip().upper() for c in t.columns]
    return sorted(t["DATE1"].astype(str).str.strip().unique().tolist()) if "DATE1" in t.columns else []


def eqbe_fingerprint(df: pd.DataFrame) -> tuple:
    x = df[df["series"].isin(["EQ", "BE"])]
    return (len(x), round(float(np.nansum(x["close"])), 2), round(float(np.nansum(x["volume"])), 0),
            round(float(np.nansum(x["turnover"])), 0))


def cm_enrichment(d: date) -> tuple[pd.DataFrame | None, str]:
    """fetch_day's enrichment order: legacy CM bhavcopy, then UDiFF if absent."""
    mon = MONTHS[d.month - 1]
    leg = RAW_CM / f"cm{d:%d}{mon}{d.year}bhav.csv.zip"
    udf = RAW_CM / f"BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
    raw, src = None, "none"
    if leg.exists():
        raw, src = leg.read_bytes(), leg.name
    elif udf.exists():
        raw, src = udf.read_bytes(), udf.name
    else:
        st, raw = fetch_file(LEGACY_CM.format(yyyy=d.year, mon=mon, dd=f"{d:%d}"), leg)
        src = leg.name
        if st != 200:
            st, raw = fetch_file(UDIFF_CM.format(yyyymmdd=f"{d:%Y%m%d}"), udf)
            src = udf.name if st == 200 else "none"
    if raw is None:
        return None, src
    try:
        return nhi.parse_pr_zip(raw, d), src
    except Exception as exc:  # noqa: BLE001
        log(f"enrichment parse failed for {d}: {exc!r}", "sessions")
        return None, src + " (parse failed)"


def check_candidate(d: date, prev_session: date, eod: pd.DataFrame) -> dict:
    st, raw = fetch_file(SEC_URL.format(ddmmyyyy=f"{d:%d%m%Y}"), RAW_SEC / sec_name(d))
    rec = {"date": str(d), "weekday": d.strftime("%A"), "http": st}
    if st != 200 or not raw:
        rec["verdict"] = "no file"
        return rec
    rec["bytes"], rec["sha256"] = len(raw), hashlib.sha256(raw).hexdigest()
    try:
        df = nhi.parse_sec_delivery(raw, d)
        rec["date1"] = _date1(raw)
    except Exception as exc:  # noqa: BLE001
        rec["verdict"] = f"unparseable ({exc!r})"
        return rec
    prev_path = RAW_SEC / sec_name(prev_session)
    if prev_path.exists():
        rec["byte_identical_to_prev_file"] = prev_path.read_bytes() == raw
    prev_rows = eod[eod["date"] == pd.Timestamp(prev_session)]
    rec["fingerprint_eqbe"] = list(eqbe_fingerprint(df))
    rec["fingerprint_prev_stored_eqbe"] = list(eqbe_fingerprint(prev_rows))
    rec["echo_of_prev_stored"] = rec["fingerprint_eqbe"] == rec["fingerprint_prev_stored_eqbe"]
    want = d.strftime("%d-%b-%Y")
    ok_date = rec["date1"] == [want]
    rec["rows_all_series"] = int(len(df))
    rec["rows_by_series"] = {k: int(v) for k, v in df["series"].value_counts().items()}
    if ok_date and not rec["echo_of_prev_stored"] and not rec.get("byte_identical_to_prev_file", False):
        rec["verdict"] = "session: add"
    else:
        rec["verdict"] = "echo or mis-dated: skip"
    return rec


def build_session_rows(d: date) -> tuple[pd.DataFrame, dict]:
    raw = (RAW_SEC / sec_name(d)).read_bytes()
    primary = nhi.parse_sec_delivery(raw, d)
    enrich, src = cm_enrichment(d)
    merged = nhi.merge_sources(primary, enrich)
    info = {"rows": int(len(merged)), "rows_eq_be": int(merged["series"].isin(["EQ", "BE"]).sum()),
            "by_series": {k: int(v) for k, v in merged["series"].value_counts().items()},
            "enrichment_file": src,
            "isin_filled_pct": round(100 * float(merged["isin"].notna().mean()), 2)}
    return merged, info


# --------------------------------------------------------------------------- #
# 4. 2022-03-07 BE/BZ rows from CM bhavcopy + MTO
# --------------------------------------------------------------------------- #
def parse_mto(raw: bytes) -> pd.DataFrame:
    rows = []
    for line in raw.decode("latin-1").splitlines():
        p = [x.strip() for x in line.split(",")]
        if len(p) >= 7 and p[0] == "20":
            rows.append({"ticker": p[2], "series": p[3], "mto_traded": p[4],
                         "deliv_qty": p[5], "deliv_pct": p[6]})
    m = pd.DataFrame(rows)
    for c in ("mto_traded", "deliv_qty", "deliv_pct"):
        m[c] = nhi._to_num(m[c])
    return m


def rows_from_cm_mto(d: date, cm_raw: bytes, mto_raw: bytes, series: list[str]) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(cm_raw)) as zf:
        name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        cm = pd.read_csv(zf.open(name))
    cm.columns = [c.strip().upper() for c in cm.columns]
    cm["SERIES"] = cm["SERIES"].astype(str).str.strip()
    cm = cm[cm["SERIES"].isin(series)].copy()
    vol = nhi._to_num(cm["TOTTRDQTY"])
    val = nhi._to_num(cm["TOTTRDVAL"])
    out = pd.DataFrame({
        "date": pd.Timestamp(d).normalize(),
        "ticker": cm["SYMBOL"].astype(str).str.strip(),
        "series": cm["SERIES"],
        "isin": cm["ISIN"].astype(str).str.strip() if "ISIN" in cm.columns else pd.NA,
        "prev_close": nhi._to_num(cm["PREVCLOSE"]),
        "open": nhi._to_num(cm["OPEN"]), "high": nhi._to_num(cm["HIGH"]),
        "low": nhi._to_num(cm["LOW"]), "last": nhi._to_num(cm["LAST"]),
        "close": nhi._to_num(cm["CLOSE"]),
        # sec_bhavdata_full semantics: AVG_PRICE = value / qty (2 dp); TURNOVER_LACS 2 dp
        "vwap": (val / vol.where(vol > 0)).round(2),
        "volume": vol,
        "turnover": (val / 1e5).round(2) * 1e5,
        "trades": nhi._to_num(cm["TOTALTRADES"]),
        "source": "cm_bhavcopy+mto",
    })
    if mto_raw is not None:
        mto = parse_mto(mto_raw)
        out = out.merge(mto[["ticker", "series", "deliv_qty", "deliv_pct"]], on=["ticker", "series"], how="left")
    else:
        out["deliv_qty"], out["deliv_pct"] = np.nan, np.nan
    out = out[out["volume"] > 0]
    return nhi._finalize(out)


def compare_frames(a: pd.DataFrame, b: pd.DataFrame, cols: list[str]) -> dict:
    j = a.merge(b, on=["ticker", "series"], how="outer", suffixes=("_a", "_b"), indicator=True)
    res = {"rows_a": int(len(a)), "rows_b": int(len(b)),
           "only_a": int((j["_merge"] == "left_only").sum()), "only_b": int((j["_merge"] == "right_only").sum())}
    jb = j[j["_merge"] == "both"]
    for c in cols:
        x, y = jb[c + "_a"].astype(float).to_numpy(), jb[c + "_b"].astype(float).to_numpy()
        fin = np.isfinite(x) & np.isfinite(y)
        res[c] = {"max_abs_diff": float(np.max(np.abs(x[fin] - y[fin]))) if fin.any() else 0.0,
                  "nan_mismatch": int((np.isfinite(x) != np.isfinite(y)).sum())}
    return res


def fix_2022_03_07(eod: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    d7, d8 = date(2022, 3, 7), date(2022, 3, 8)
    ev: dict = {}
    sec7 = nhi.parse_sec_delivery((RAW_SEC / sec_name(d7)).read_bytes(), d7)
    sec8 = nhi.parse_sec_delivery((RAW_SEC / sec_name(d8)).read_bytes(), d8)
    ev["archive_sec_file_rows_by_series"] = {
        "2022-03-07": {k: int(v) for k, v in sec7["series"].value_counts().items()},
        "2022-03-08": {k: int(v) for k, v in sec8["series"].value_counts().items()}}
    for dd, sec in ((d7, sec7), (d8, sec8)):
        st = eod[eod["date"] == pd.Timestamp(dd)]
        ev[f"stored_vs_archive_sec_{dd}"] = compare_frames(
            st, sec[sec["series"].isin(["EQ", "BE"])],
            ["prev_close", "open", "high", "low", "close", "volume", "turnover", "deliv_qty"])
    _, cm7 = fetch_file(LEGACY_CM.format(yyyy=2022, mon="MAR", dd="07"), RAW_CM / "cm07MAR2022bhav.csv.zip")
    _, cm8 = fetch_file(LEGACY_CM.format(yyyy=2022, mon="MAR", dd="08"), RAW_CM / "cm08MAR2022bhav.csv.zip")
    _, mto7 = fetch_file(MTO_URL.format(ddmmyyyy="07032022"), RAW_MTO / "MTO_07032022.DAT")
    _, mto8 = fetch_file(MTO_URL.format(ddmmyyyy="08032022"), RAW_MTO / "MTO_08032022.DAT")
    # cross-validate the construction on 2022-03-08 (complete security-wise file)
    cols = ["prev_close", "open", "high", "low", "last", "close", "vwap", "volume", "turnover",
            "trades", "deliv_qty", "deliv_pct"]
    rec8 = rows_from_cm_mto(d8, cm8, mto8, ["BE", "BZ"])
    ev["construction_check_2022-03-08_BE_BZ"] = compare_frames(rec8, sec8[sec8["series"].isin(["BE", "BZ"])], cols)
    rec8_all = rows_from_cm_mto(d8, cm8, mto8, SERIES_KEPT)
    ev["construction_check_2022-03-08_all_series"] = compare_frames(rec8_all, sec8, cols)
    # build 2022-03-07 BE/BZ rows
    rows7 = rows_from_cm_mto(d7, cm7, mto7, ["BE", "BZ"])
    cm7_eq = rows_from_cm_mto(d7, cm7, mto7, ["EQ", "SM", "ST"])
    ev["cm_vs_archive_sec_2022-03-07_EQ_SM_ST"] = compare_frames(cm7_eq, sec7, cols)
    ev["rows_rebuilt_2022-03-07"] = {k: int(v) for k, v in rows7["series"].value_counts().items()}
    ev["deliv_missing_in_rebuilt"] = int(rows7["deliv_qty"].isna().sum())
    # does the rebuilt close match what 2022-03-08 reports as prev_close?
    j = rows7[rows7["series"] == "BE"][["ticker", "close"]].merge(
        sec8[["ticker", "prev_close"]], on="ticker", how="inner")
    ev["rebuilt_BE_close_vs_0308_prev_close"] = {
        "tickers": int(len(j)), "equal_within_0.005": int(((j["close"] - j["prev_close"]).abs() <= TOL).sum())}
    return rows7, ev


# --------------------------------------------------------------------------- #
# 4b. coverage: traded EQ/BE securities of the pd file missing from the store
# --------------------------------------------------------------------------- #
COVERAGE_MIN_MISSING = 10      # rule fixed before the repair: rebuild a session when >= 10 are missing


def coverage_audit(eod: pd.DataFrame) -> pd.DataFrame:
    rows = []
    by_date = {k: set(v) for k, v in eod.groupby("date")["ticker"]}
    for d in sorted(by_date):
        z = RAW / pr_name(pd.Timestamp(d))
        if not z.exists() or not bundle_ok(z):
            continue
        pdf, _ = read_pr_member(z, "pd")
        if pdf is None or pdf.empty:
            continue
        pdf = pdf[pdf["SERIES"].str.strip().isin(["EQ", "BE"])]
        q = pd.to_numeric(pdf["NET_TRDQTY"].str.strip(), errors="coerce")
        px = pd.to_numeric(pdf["CLOSE_PRICE"].str.strip(), errors="coerce")
        sym = pdf["SYMBOL"].str.strip()
        st = by_date[d]
        miss = (q > 0) & ~sym.isin(st)
        rows.append({"date": pd.Timestamp(d), "pd_traded": int((q > 0).sum()), "stored": len(st),
                     "traded_not_stored": int(miss.sum()),
                     "be_traded_not_stored": int((miss & (pdf["SERIES"].str.strip() == "BE")).sum()),
                     "traded_not_stored_close_ge_10": int((miss & (px >= 10)).sum()),
                     "stored_not_in_pd": len(st - set(sym))})
    return pd.DataFrame(rows)


def repair_session(d: date, eod: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Rows of the CM bhavcopy (+ MTO delivery) absent from the day's security-wise file."""
    mon = MONTHS[d.month - 1]
    _, sec_raw = fetch_file(SEC_URL.format(ddmmyyyy=f"{d:%d%m%Y}"), RAW_SEC / sec_name(d))
    sec = nhi.parse_sec_delivery(sec_raw, d)
    st, cm_raw = fetch_file(LEGACY_CM.format(yyyy=d.year, mon=mon, dd=f"{d:%d}"),
                            RAW_CM / f"cm{d:%d}{mon}{d.year}bhav.csv.zip")
    if st != 200:
        return sec.iloc[:0], {"date": str(d), "status": f"no legacy CM bhavcopy (HTTP {st})"}
    cm_all = rows_from_cm_mto(d, cm_raw, None, SERIES_KEPT)
    k_sec = set(zip(sec["ticker"], sec["series"]))
    miss = cm_all[[(t, x) not in k_sec for t, x in zip(cm_all["ticker"], cm_all["series"])]]
    need_mto = bool((miss["series"] == "EQ").any() or (miss["series"] == "SM").any())
    if need_mto:
        _, mto_raw = fetch_file(MTO_URL.format(ddmmyyyy=f"{d:%d%m%Y}"), RAW_MTO / f"MTO_{d:%d%m%Y}.DAT")
        cm_all = rows_from_cm_mto(d, cm_raw, mto_raw, SERIES_KEPT)
        miss = cm_all[[(t, x) not in k_sec for t, x in zip(cm_all["ticker"], cm_all["series"])]]
    both = cm_all[[(t, x) in k_sec for t, x in zip(cm_all["ticker"], cm_all["series"])]]
    chk = compare_frames(both, sec, ["prev_close", "open", "high", "low", "last", "close", "volume", "trades"])
    ok_method = all(v["max_abs_diff"] == 0 and v["nan_mismatch"] == 0 for k, v in chk.items() if isinstance(v, dict))
    stored = eod[eod["date"] == pd.Timestamp(d)]
    ev = {"date": str(d), "sec_rows": int(len(sec)), "stored_eq_be": int(len(stored)),
          "store_equals_sec_file_eq_be": compare_frames(stored, sec[sec["series"].isin(["EQ", "BE"])],
                                                        ["close", "volume"])["only_a"] == 0,
          "rebuilt_rows_by_series": {k: int(v) for k, v in miss["series"].value_counts().items()},
          "cm_vs_sec_on_common_rows_identical": bool(ok_method), "used_mto": need_mto}
    return miss, ev


def repair_coverage(eod: pd.DataFrame, cov: pd.DataFrame, skip: set[str]) -> tuple[list[pd.DataFrame], dict]:
    sel = cov[(cov["traded_not_stored"] >= COVERAGE_MIN_MISSING) & ~cov["date"].dt.strftime("%Y-%m-%d").isin(skip)]
    frames, evs = [], []
    for d in sel["date"]:
        rows, ev = repair_session(pd.Timestamp(d).date(), eod)
        evs.append(ev)
        if len(rows):
            frames.append(rows)
        log(f"coverage repair {pd.Timestamp(d).date()}: {ev.get('rebuilt_rows_by_series')} "
            f"(method identical on common rows: {ev.get('cm_vs_sec_on_common_rows_identical')})", "sessions")
    rep = {"rule": f"rebuild a session when >= {COVERAGE_MIN_MISSING} traded EQ/BE securities of the PR bundle's "
                   "pd file are missing from the store; rows = CM bhavcopy rows absent from that day's "
                   "security-wise file (delivery from MTO for EQ/SM; none exists for BE/BZ)",
           "sessions": evs, "n_sessions": len(evs),
           "rows_rebuilt": int(sum(len(f) for f in frames))}
    return frames, rep


# --------------------------------------------------------------------------- #
# 5. calendar audit: PR bundle present <=> session; mis-dated sessions re-dated
# --------------------------------------------------------------------------- #
def pr_calendar() -> dict:
    """Per calendar day of the window: 'present' (zip on disk) / 'absent' (404) / 'unknown'."""
    from ml.integrity.common import STORE_END, STORE_START
    man = pd.read_csv(RAW / "_manifest.csv", dtype=str)
    man = man[man["name"].str.match(r"^PR\d{6}\.zip$")]
    absent = {pd.to_datetime(n[2:8], format="%d%m%y").date() for n in man.loc[man["status"] == "404", "name"]}
    present, misfiled = set(), {}
    for z in RAW.glob("PR*.zip"):
        zd = pd.to_datetime(z.stem[2:], format="%d%m%y").date()
        if bundle_ok(z):
            present.add(zd)
        else:
            misfiled[zd] = bundle_inner_date(z)
    days = pd.date_range(STORE_START, STORE_END, freq="D").date
    cal = {d: ("present" if d in present else "misfiled" if d in misfiled else "absent" if d in absent
               else "unknown") for d in days}
    cal["_misfiled"] = {str(k): str(v) for k, v in misfiled.items()}
    return cal


def find_file_for(d: date, max_ahead: int = 4) -> tuple[date | None, bytes | None, list]:
    """The sec_bhavdata_full file whose own DATE1 says d: d's file, else the next days' files."""
    tried = []
    for k in range(0, max_ahead + 1):
        n = d + timedelta(days=k)
        st, raw = fetch_file(SEC_URL.format(ddmmyyyy=f"{n:%d%m%Y}"), RAW_SEC / sec_name(n))
        d1 = _date1(raw) if st == 200 and raw else None
        tried.append({"file_date": str(n), "http": st, "date1": d1})
        if d1 == [d.strftime("%d-%b-%Y")]:
            return n, raw, tried
    return None, None, tried


def calendar_audit(eod: pd.DataFrame, cont_sessions: set[str]) -> tuple[list[tuple[dict, pd.DataFrame]], list[str], dict]:
    """Returns ([(action, rows)], dates to delete, report).

    Step 1: every stored date S without a PR bundle: its own archive file's DATE1 names
            the session it really holds; if that is another date D (not stored, PR bundle
            present) and the stored rows equal the file, S is re-dated to D.
    Step 2: every remaining PR-bundle date D without stored rows: the archive file whose
            DATE1 is D is added, unless it is an echo of the previous stored session.
    """
    cal = pr_calendar()
    misfiled = cal.pop("_misfiled")
    stored = {pd.Timestamp(x).date() for x in eod["date"].unique()}
    present = {d for d, v in cal.items() if v == "present"}
    absent = {d for d, v in cal.items() if v in ("absent", "misfiled")}
    unknown = sorted(d for d, v in cal.items() if v == "unknown")
    stored_without_pr = sorted(stored & absent)
    sessions_not_stored = sorted(present - stored)
    rep = {"days": len(cal), "pr_present": len(present), "pr_absent": len(absent),
           "pr_misfiled_by_archive": misfiled,
           "pr_unknown": [str(x) for x in unknown],
           "stored_dates_without_pr_bundle": [str(x) for x in stored_without_pr],
           "pr_bundle_dates_not_stored": [str(x) for x in sessions_not_stored],
           "weekend_sessions": [str(d) for d in sorted(present) if d.weekday() >= 5],
           "weekday_closures": [str(d) for d in sorted(absent) if d.weekday() < 5]}
    hol = {date.fromisoformat(x) for x in nhi.NSE_TRADING_HOLIDAYS}
    lo, hi = min(cal), max(cal)
    hol_w = {d for d in hol if lo <= d <= hi}
    closures = {d for d in absent if d.weekday() < 5}
    rep["holiday_list_vs_closures"] = {
        "closures_not_in_list": [str(d) for d in sorted(closures - hol_w)],
        "listed_but_session": [str(d) for d in sorted(hol_w & present)]}
    spc = {date.fromisoformat(x) for x in nhi.SPECIAL_SESSIONS}
    rep["special_sessions_in_window"] = {str(d): cal.get(d) for d in sorted(spc) if lo <= d <= hi}
    td = set(nhi.trading_days(lo, hi))
    rep["trading_days_vs_pr_calendar"] = {
        "trading_days_without_pr": [str(d) for d in sorted(td) if d not in present],
        "pr_sessions_not_in_trading_days": [str(d) for d in sorted(present - td)]}
    actions: list[tuple[dict, pd.DataFrame]] = []
    deletes: list[str] = []
    consumed: set[date] = set()
    cols = ["prev_close", "open", "high", "low", "close", "volume", "turnover", "deliv_qty"]
    # step 1: stored dates without a PR bundle
    for s_ in stored_without_pr:
        st, raw = fetch_file(SEC_URL.format(ddmmyyyy=f"{s_:%d%m%Y}"), RAW_SEC / sec_name(s_))
        d1 = _date1(raw) if st == 200 and raw else None
        a = {"stored_date": str(s_), "file": sec_name(s_), "date1": d1}
        true = pd.to_datetime(d1[0], format="%d-%b-%Y").date() if d1 and len(d1) == 1 else None
        if true is None or true == s_:
            a["action"] = "unresolved: stored date has no PR bundle but its file names it"
            actions.append((a, None))
            continue
        a["true_session"] = str(true)
        if true in stored or true not in present:
            a["action"] = f"unresolved: true date {true} {'already stored' if true in stored else 'has no PR bundle'}"
            actions.append((a, None))
            continue
        rows = nhi.parse_sec_delivery(raw, true)
        enrich, src = cm_enrichment(true)
        rows = nhi.merge_sources(rows, enrich)
        stored_rows = eod[eod["date"] == pd.Timestamp(s_)]
        cmp_ = compare_frames(stored_rows, rows[rows["series"].isin(["EQ", "BE"])], cols)
        same = cmp_["only_a"] == 0 and cmp_["only_b"] == 0 and all(
            v["max_abs_diff"] == 0 and v["nan_mismatch"] == 0 for v in cmp_.values() if isinstance(v, dict))
        own_st, own_raw = fetch_file(SEC_URL.format(ddmmyyyy=f"{true:%d%m%Y}"), RAW_SEC / sec_name(true))
        a.update({"session": str(true), "weekday": true.strftime("%A"), "file_used": sec_name(s_),
                  "own_file_of_true_date": {"file": sec_name(true), "http": own_st,
                                            "date1": _date1(own_raw) if own_st == 200 and own_raw else None,
                                            "byte_identical_to_used_file": own_raw == raw},
                  "rows": int(len(rows)), "rows_eq_be": int(rows["series"].isin(["EQ", "BE"]).sum()),
                  "by_series": {k: int(v) for k, v in rows["series"].value_counts().items()},
                  "enrichment_file": src, "isin_filled_pct": round(100 * float(rows["isin"].notna().mean()), 2),
                  "stored_copy": {"stored_date": str(s_), "identical_to_file": bool(same), "compare": cmp_}})
        if same:
            a["action"] = f"re-date stored {s_} -> {true}"
            deletes.append(str(s_))
            consumed.add(true)
            actions.append((a, rows))
        else:
            a["action"] = "unresolved: stored copy differs from the file"
            actions.append((a, None))
    # step 2: PR-bundle dates without stored rows (not explained by a re-date)
    for d in sessions_not_stored:
        if d in consumed:
            continue
        n, raw, tried = find_file_for(d)
        a = {"session": str(d), "weekday": d.strftime("%A"), "files_tried": tried}
        if n is None:
            a["action"] = "unresolved: no archive file names this date"
            actions.append((a, None))
            continue
        rows = nhi.parse_sec_delivery(raw, d)
        enrich, src = cm_enrichment(d)
        rows = nhi.merge_sources(rows, enrich)
        prev = max((x for x in stored if x < d), default=None)
        prev_rows = eod[eod["date"] == pd.Timestamp(prev)] if prev else eod.iloc[:0]
        echo = prev is not None and eqbe_fingerprint(rows) == eqbe_fingerprint(prev_rows)
        a.update({"file_used": sec_name(n), "rows": int(len(rows)),
                  "rows_eq_be": int(rows["series"].isin(["EQ", "BE"]).sum()),
                  "by_series": {k: int(v) for k, v in rows["series"].value_counts().items()},
                  "enrichment_file": src, "isin_filled_pct": round(100 * float(rows["isin"].notna().mean()), 2),
                  "echo_of_prev_stored": bool(echo), "found_by_continuity_scan": str(d) in cont_sessions})
        if echo:
            a["action"] = "skip: echo of the previous stored session"
            actions.append((a, None))
        else:
            a["action"] = "add session"
            actions.append((a, rows))
    rep["actions"] = [a for a, _ in actions]
    rep["stored_without_pr_unresolved"] = [a["stored_date"] for a, _ in actions
                                           if "stored_date" in a and a["action"].startswith("unresolved")]
    return actions, deletes, rep


# --------------------------------------------------------------------------- #
# 6. store vs PR bundle audit (all stored sessions)
# --------------------------------------------------------------------------- #
def read_pr_member(zpath: Path, prefix: str) -> tuple[pd.DataFrame | None, str | None]:
    """Read the member whose lower-cased name starts with prefix (e.g. 'pd', 'bc', 'etf')."""
    try:
        with zipfile.ZipFile(zpath) as zf:
            names = [n for n in zf.namelist() if Path(n).name.lower().startswith(prefix)
                     and Path(n).name.lower().endswith(".csv")]
            if not names:
                return None, None
            raw = zf.read(names[0])
    except zipfile.BadZipFile:
        return None, None
    try:
        df = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False)
    except UnicodeDecodeError:
        df = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False, encoding="latin-1")
    except pd.errors.EmptyDataError:
        return pd.DataFrame(), names[0]
    df.columns = [c.strip().upper() for c in df.columns]
    return df, names[0]


def audit_store_vs_pr(eod: pd.DataFrame, extra_rows: pd.DataFrame | None = None) -> dict:
    """Share of stored EQ/BE closes equal to the same day's pd-file close."""
    dates = sorted(eod["date"].unique())
    res, worst = [], []
    for d in dates:
        d = pd.Timestamp(d).date()
        z = RAW / pr_name(d)
        if not z.exists() or not bundle_ok(z):
            res.append({"date": str(d), "pr": "absent or misfiled"})
            continue
        pdf, name = read_pr_member(z, "pd")
        if pdf is None or pdf.empty:
            res.append({"date": str(d), "pr": "no pd member"})
            continue
        pdf = pdf[pdf["SERIES"].str.strip().isin(["EQ", "BE"])]
        pdf = pdf.assign(ticker=pdf["SYMBOL"].str.strip(),
                         pd_close=pd.to_numeric(pdf["CLOSE_PRICE"], errors="coerce"))
        st = eod.loc[eod["date"] == pd.Timestamp(d), ["ticker", "close"]]
        j = st.merge(pdf[["ticker", "pd_close"]].drop_duplicates("ticker"), on="ticker", how="left")
        both = j["pd_close"].notna()
        eq = (j["close"] - j["pd_close"]).abs() <= TOL
        r = {"date": str(d), "pr": name, "stored": int(len(st)), "in_pd": int(both.sum()),
             "equal": int((eq & both).sum())}
        r["share_equal_of_matched"] = r["equal"] / r["in_pd"] if r["in_pd"] else None
        res.append(r)
    df = pd.DataFrame(res)
    ok = df["share_equal_of_matched"].notna()
    out = {"sessions": int(len(df)), "with_pd": int(ok.sum()),
           "absent_or_unreadable": df.loc[~ok, ["date", "pr"]].to_dict("records"),
           "share_equal_min": float(df.loc[ok, "share_equal_of_matched"].min()) if ok.any() else None,
           "share_equal_median": float(df.loc[ok, "share_equal_of_matched"].median()) if ok.any() else None,
           "sessions_below_0.99": df.loc[ok & (df["share_equal_of_matched"] < 0.99)].to_dict("records")}
    df.to_csv(OUT / "store_vs_pr_audit.csv", index=False)
    return out


# --------------------------------------------------------------------------- #
def apply_fixes_to_export(eod: pd.DataFrame, upsert: pd.DataFrame, delete_dates: list[str]) -> pd.DataFrame:
    """In-memory preview of the store after the write phase (EQ/BE rows)."""
    keep = eod[~eod["date"].isin(pd.to_datetime(delete_dates))]
    add = upsert[upsert["series"].isin(["EQ", "BE"])][eod.columns.intersection(upsert.columns)].copy()
    add["date"] = pd.to_datetime(add["date"]).astype("datetime64[ns]")
    k = keep.set_index(["date", "ticker", "series"])
    a = add.set_index(["date", "ticker", "series"])
    k = k[~k.index.isin(a.index)]
    out = pd.concat([k.reset_index(), a.reset_index()], ignore_index=True)
    # a ticker must have one EQ/BE row per date (prep's assertion)
    out = out.sort_values(["ticker", "date", "series"]).drop_duplicates(["date", "ticker"], keep="last")
    return out.sort_values(["ticker", "date"]).reset_index(drop=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", action="store_true", help="also run the store-vs-PR audit (needs the PR bundles)")
    a = ap.parse_args(argv)
    t0 = time.time()
    STAGING.mkdir(parents=True, exist_ok=True)
    eod = load_eod()
    per, mm_rows = continuity_scan(eod)
    per.to_csv(OUT / "continuity_before.csv", index=False)
    cands = candidate_days(per)
    log(f"continuity scan: {len(per)} dates, flagged {list(cands)}", "sessions")
    rep: dict = {"tolerance": TOL, "flag_share": FLAG_SHARE, "flagged_before": cands,
                 "top10_share_before": per.sort_values("share", ascending=False).head(10)
                 .assign(date=lambda x: x["date"].dt.strftime("%Y-%m-%d")).to_dict("records")}
    checks, cont_frames, add_info = [], {}, {}
    for fd, c in cands.items():
        for gd in c["gap_days"]:
            rec = check_candidate(date.fromisoformat(gd), date.fromisoformat(c["prev_stored_session"]), eod)
            rec["flagged_date"] = fd
            checks.append(rec)
            log(f"candidate {gd} ({rec['weekday']}) for flagged {fd}: {rec['verdict']}", "sessions")
            if rec["verdict"] == "session: add":
                rows, info = build_session_rows(date.fromisoformat(gd))
                cont_frames[gd] = rows
                add_info[gd] = info
    rep["candidates"] = checks
    rep["sessions_to_add"] = add_info
    rep["sessions_to_add_match_lead_list"] = sorted(add_info) == sorted(MISSING_SESSIONS)
    # 2022-03-08
    rows7, ev7 = fix_2022_03_07(eod)
    mm8 = mm_rows[mm_rows["date"] == pd.Timestamp("2022-03-08")]
    ev7["mismatch_rows_2022-03-08"] = int(len(mm8))
    ev7["mismatch_by_series"] = {k: int(v) for k, v in mm8["series"].value_counts().items()}
    ev7["mismatch_stored_prev_date"] = {str(pd.Timestamp(k).date()): int(v)
                                        for k, v in mm8["stored_prev_date"].value_counts().items()}
    rep["march_2022"] = ev7
    # calendar audit (PR bundle present <=> session): re-dates + cross-check of the additions
    cal_pairs, delete_dates, cal = calendar_audit(eod, set(add_info))
    rep["calendar_audit"] = cal
    added_by_cal = {act["session"] for act in cal["actions"] if act["action"] == "add session"}
    redated = {act["session"]: act["stored_copy"]["stored_date"] for act in cal["actions"]
               if act["action"].startswith("re-date")}
    rep["redated_sessions"] = redated
    rep["calendar_vs_continuity"] = {"added_by_calendar": sorted(added_by_cal),
                                     "added_by_continuity": sorted(add_info),
                                     "identical": sorted(added_by_cal) == sorted(add_info)}
    # coverage audit (pd file vs store) and repair of sessions with >= 10 missing traded securities
    cov = coverage_audit(eod)
    cov.to_csv(OUT / "coverage_before.csv", index=False)
    cov_frames, cov_rep = repair_coverage(eod, cov, skip={"2022-03-07"} | set(redated.values()))
    cov_rep["audit_before"] = {"sessions": int(len(cov)),
                               "sessions_with_any_missing": int((cov["traded_not_stored"] > 0).sum()),
                               "sessions_ge_rule": int((cov["traded_not_stored"] >= COVERAGE_MIN_MISSING).sum()),
                               "missing_total": int(cov["traded_not_stored"].sum()),
                               "missing_close_ge_10_total": int(cov["traded_not_stored_close_ge_10"].sum()),
                               "stored_not_in_pd_total": int(cov["stored_not_in_pd"].sum())}
    rep["coverage"] = cov_rep
    # one frame per session: continuity frames for the additions, calendar frames for re-dates
    add_frames = list(cont_frames.values()) + [rows7] + cov_frames
    for act, frame in cal_pairs:
        if frame is None:
            continue
        if act["action"].startswith("re-date") or act["session"] not in cont_frames:
            add_frames.append(frame)
    upsert = pd.concat(add_frames, ignore_index=True)
    upsert["date"] = pd.to_datetime(upsert["date"]).astype("datetime64[ns]")
    assert not upsert.duplicated(["date", "ticker", "series"]).any()
    upsert.to_parquet(STAGING / "sessions_upsert.parquet", index=False)
    wjson(STAGING / "sessions_delete.json", {
        "delete_dates": delete_dates,
        "reason": {s: f"rows are the {d} session (archive echo on a closure)" for d, s in redated.items()}})
    rep["upsert_rows"] = {"total": int(len(upsert)),
                          "by_date": {str(k.date()): int(v) for k, v in upsert.groupby("date").size().items()}}
    rep["delete_dates"] = delete_dates
    # in-memory re-scan with the fixes applied
    after = apply_fixes_to_export(eod, upsert, delete_dates)
    per2, _ = continuity_scan(after)
    per2.to_csv(OUT / "continuity_after_preview.csv", index=False)
    rep["preview_after"] = {"max_share": float(per2["share"].max()),
                            "dates_over_5pct": per2.loc[per2["share"] > FLAG_SHARE, "date"].dt.strftime("%Y-%m-%d").tolist(),
                            "top10": per2.sort_values("share", ascending=False).head(10)
                            .assign(date=lambda x: x["date"].dt.strftime("%Y-%m-%d")).to_dict("records")}
    cov2 = coverage_audit(after)
    cov2.to_csv(OUT / "coverage_after_preview.csv", index=False)
    rep["coverage"]["audit_after_preview"] = {
        "sessions": int(len(cov2)), "sessions_with_any_missing": int((cov2["traded_not_stored"] > 0).sum()),
        "sessions_ge_rule": int((cov2["traded_not_stored"] >= COVERAGE_MIN_MISSING).sum()),
        "max_missing": int(cov2["traded_not_stored"].max()),
        "missing_total": int(cov2["traded_not_stored"].sum()),
        "missing_close_ge_10_total": int(cov2["traded_not_stored_close_ge_10"].sum())}
    if a.audit:
        rep["store_vs_pr_audit_before"] = audit_store_vs_pr(eod)
        rep["store_vs_pr_audit_after_preview"] = audit_store_vs_pr(after)
    rep["seconds"] = round(time.time() - t0, 1)
    wjson(OUT / "sessions.json", rep)
    log(f"sessions: add {add_info and {k: v['rows'] for k, v in add_info.items()}}, 2022-03-07 rebuilt "
        f"{ev7['rows_rebuilt_2022-03-07']}, re-dated {redated}; delete {delete_dates}; "
        f"preview max share {rep['preview_after']['max_share']:.4f} ({rep['seconds']}s)", "sessions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

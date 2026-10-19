#!/usr/bin/env python3
"""Parse the downloaded NSE archive files into staging tables (ml/data_ext/).

Outputs
-------
fo_daily_stock.parquet   one row per (date, ticker) with a stock future or a
                         stock option in that day's F&O bhavcopy
index_daily.parquet      one row per (date, index_name) from ind_close_all
fo_participant_oi.parquet one row per (date, client_type), 14 numeric columns
industry_map.csv, sector_index_map.csv, equity_master.csv  (lists.py)

Every raw file is checked for the date printed inside it (F&O TIMESTAMP /
TradDt, index ``Index Date``, participant title line); a file whose content
date differs from its file-name date (an archive "echo") is excluded and
listed in the parse report. Raw files are read in memory (zip members are
never extracted to disk). Per-file results are cached under
ml/data_ext/_cache/ keyed by file name, size and mtime, so a re-run after
more downloads only parses the new files.

Units (verified, see report): F&O open interest is reported in SHARES
(underlying quantity) in both the legacy (OPEN_INT) and UDiFF (OpnIntrst)
formats; traded volume is in CONTRACTS in both (CONTRACTS / TtlTradgVol);
turnover is rupees (VAL_INLAKH x 1e5 / TtlTrfVal). Participant-wise OI is
in contracts (as its title says).

Roll convention: for each stock on date t, ``near`` = the futures contract
with the smallest expiry >= t (on the expiry day itself the expiring
contract is still near, days_to_expiry = 0), ``next`` = the second
smallest. Days to expiry are calendar days. basis_near =
(fut_near_settle / spot_close - 1) x 365 / days_to_expiry, NaN when
days_to_expiry < 2.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import zipfile
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from ml.extdata import common as C  # noqa: E402

CACHE_DIR = C.EXT / "_cache"
FO_RE_LEGACY = re.compile(r"^fo(\d{2})([A-Z]{3})(\d{4})bhav\.csv\.zip$")
FO_RE_UDIFF = re.compile(r"^BhavCopy_NSE_FO_0_0_0_(\d{8})_F_0000\.csv\.zip$")
IDX_RE = re.compile(r"^ind_close_all_(\d{8})\.csv$")
PART_RE = re.compile(r"^fao_participant_oi_(\d{8})\.csv$")

# EOD-export dates whose bars belong to a different calendar session (found
# by this stream from archive 404s on EOD dates; the bar sequence itself is
# continuous, so a prev_close continuity scan cannot see them):
#   2021-11-05 holds the 2021-11-04 Muhurat session (volumes ~1/7 of normal;
#              P1 re-dates it in v2);
#   2023-06-29 holds the 2023-06-28 session (NSE moved the Bakri Id holiday
#              from 06-28 to 06-29; the ingest's calendar skipped 06-28);
#   2024-01-22 holds the 2024-01-20 Saturday session (22 Jan 2024 was a
#              market holiday; volumes ~1/4 of normal).
# Maps external-file date -> EOD-export date. Applied only when the EOD
# export holds the target date and not the source date (so it is inert on a
# re-dated v2 export).
EXT_TO_EOD_ALIAS = {date(2021, 11, 4): date(2021, 11, 5),
                    date(2023, 6, 28): date(2023, 6, 29),
                    date(2024, 1, 20): date(2024, 1, 22)}

FO_COLS = ["date", "ticker", "fut_near_settle", "fut_near_expiry",
           "fut_near_days_to_expiry", "fut_next_settle", "fut_next_expiry",
           "n_fut_expiries", "fut_oi_total", "fut_oi_chg_total",
           "fut_volume_contracts", "fut_turnover", "opt_call_oi", "opt_put_oi",
           "opt_call_volume", "opt_put_volume", "n_strikes", "has_future",
           "has_option", "source_format"]

PART_NUMERIC = {
    "Future Index Long": "fut_idx_long", "Future Index Short": "fut_idx_short",
    "Future Stock Long": "fut_stk_long", "Future Stock Short": "fut_stk_short",
    "Option Index Call Long": "opt_idx_call_long",
    "Option Index Put Long": "opt_idx_put_long",
    "Option Index Call Short": "opt_idx_call_short",
    "Option Index Put Short": "opt_idx_put_short",
    "Option Stock Call Long": "opt_stk_call_long",
    "Option Stock Put Long": "opt_stk_put_long",
    "Option Stock Call Short": "opt_stk_call_short",
    "Option Stock Put Short": "opt_stk_put_short",
    "Total Long Contracts": "total_long", "Total Short Contracts": "total_short",
}
MONTH_NUM = {m: i + 1 for i, m in enumerate(C.MONTHS)}


# --------------------------------------------------------------------------- #
# file-name dates
# --------------------------------------------------------------------------- #

def fo_file_date(name: str) -> tuple[date, str] | None:
    m = FO_RE_LEGACY.match(name)
    if m:
        return date(int(m.group(3)), MONTH_NUM[m.group(2)], int(m.group(1))), "legacy"
    m = FO_RE_UDIFF.match(name)
    if m:
        return datetime.strptime(m.group(1), "%Y%m%d").date(), "udiff"
    return None


def ddmmyyyy_date(regex: re.Pattern, name: str) -> date | None:
    m = regex.match(name)
    return datetime.strptime(m.group(1), "%d%m%Y").date() if m else None


# --------------------------------------------------------------------------- #
# F&O bhavcopy -> per-stock daily aggregate
# --------------------------------------------------------------------------- #

def _read_zip_csv(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        with zf.open(names[0]) as fh:
            raw = fh.read()
    return pd.read_csv(io.BytesIO(raw), low_memory=False)


def _normalise_fo(df: pd.DataFrame, fmt: str) -> tuple[pd.DataFrame, list[str]]:
    """Map either format onto common columns: kind (FUT/CE/PE), ticker,
    expiry, strike, settle, oi, oi_chg, volume_contracts, turnover_rs."""
    if fmt == "legacy":
        df = df.rename(columns=lambda c: str(c).strip())
        stamp = df["TIMESTAMP"].astype(str).str.strip().unique().tolist()
        inst = df["INSTRUMENT"].astype(str).str.strip()
        opt = df["OPTION_TYP"].astype(str).str.strip()
        kind = np.where(inst == "FUTSTK", "FUT",
                        np.where((inst == "OPTSTK") & (opt == "CE"), "CE",
                                 np.where((inst == "OPTSTK") & (opt == "PE"), "PE", "")))
        out = pd.DataFrame({
            "kind": kind,
            "ticker": df["SYMBOL"].astype(str).str.strip(),
            "expiry": pd.to_datetime(df["EXPIRY_DT"].astype(str).str.strip(),
                                     format="%d-%b-%Y", errors="coerce"),
            "strike": pd.to_numeric(df["STRIKE_PR"], errors="coerce"),
            "settle": pd.to_numeric(df["SETTLE_PR"], errors="coerce"),
            "oi": pd.to_numeric(df["OPEN_INT"], errors="coerce"),
            "oi_chg": pd.to_numeric(df["CHG_IN_OI"], errors="coerce"),
            "volume_contracts": pd.to_numeric(df["CONTRACTS"], errors="coerce"),
            "turnover_rs": pd.to_numeric(df["VAL_INLAKH"], errors="coerce") * 1e5,
            "other_stock_opt": (inst == "OPTSTK") & ~opt.isin(["CE", "PE"]),
        })
        stamps = [datetime.strptime(s, "%d-%b-%Y").date().isoformat() for s in stamp]
    else:
        df = df.rename(columns=lambda c: str(c).strip())
        tp = df["FinInstrmTp"].astype(str).str.strip()
        opt = df["OptnTp"].astype(str).str.strip()
        kind = np.where(tp == "STF", "FUT",
                        np.where((tp == "STO") & (opt == "CE"), "CE",
                                 np.where((tp == "STO") & (opt == "PE"), "PE", "")))
        xp = df["FininstrmActlXpryDt"] if "FininstrmActlXpryDt" in df.columns else df["XpryDt"]
        xp = pd.to_datetime(xp.astype(str).str.strip(), format="%Y-%m-%d", errors="coerce")
        xp = xp.fillna(pd.to_datetime(df["XpryDt"].astype(str).str.strip(),
                                      format="%Y-%m-%d", errors="coerce"))
        out = pd.DataFrame({
            "kind": kind,
            "ticker": df["TckrSymb"].astype(str).str.strip(),
            "expiry": xp,
            "strike": pd.to_numeric(df["StrkPric"], errors="coerce"),
            "settle": pd.to_numeric(df["SttlmPric"], errors="coerce"),
            "oi": pd.to_numeric(df["OpnIntrst"], errors="coerce"),
            "oi_chg": pd.to_numeric(df["ChngInOpnIntrst"], errors="coerce"),
            "volume_contracts": pd.to_numeric(df["TtlTradgVol"], errors="coerce"),
            "turnover_rs": pd.to_numeric(df["TtlTrfVal"], errors="coerce"),
            "other_stock_opt": (tp == "STO") & ~opt.isin(["CE", "PE"]),
        })
        stamps = sorted(set(pd.to_datetime(df["TradDt"].astype(str).str.strip())
                            .dt.date.astype(str)))
    return out, stamps


def aggregate_fo(path: Path) -> tuple[pd.DataFrame, dict]:
    """One F&O bhavcopy -> per-stock aggregate (date, ticker, ...)."""
    fd = fo_file_date(path.name)
    assert fd is not None, path.name
    d, fmt = fd
    raw = _read_zip_csv(path)
    n = _normalise_fo(raw, fmt)
    norm, stamps = n
    meta = {"file": path.name, "file_date": d.isoformat(), "format": fmt,
            "rows": int(len(raw)), "content_dates": stamps,
            "date_ok": stamps == [d.isoformat()],
            "n_futstk_rows": int((norm["kind"] == "FUT").sum()),
            "n_optstk_rows": int(norm["kind"].isin(["CE", "PE"]).sum()),
            "n_other_stock_option_rows": int(norm["other_stock_opt"].sum()),
            "n_bad_expiry": int(norm.loc[norm["kind"] != "", "expiry"].isna().sum())}
    ts = pd.Timestamp(d)
    fut = norm[norm["kind"] == "FUT"]
    meta["n_fut_expired_rows"] = int((fut["expiry"] < ts).sum())
    fut = fut[fut["expiry"] >= ts].sort_values(["ticker", "expiry"])
    g = fut.groupby("ticker", sort=True)
    agg = pd.DataFrame({
        "fut_oi_total": g["oi"].sum(min_count=1),
        "fut_oi_chg_total": g["oi_chg"].sum(min_count=1),
        "fut_volume_contracts": g["volume_contracts"].sum(min_count=1),
        "fut_turnover": g["turnover_rs"].sum(min_count=1),
        "n_fut_expiries": g["expiry"].nunique(),
    })
    first = g.nth(0).set_index("ticker")
    second = g.nth(1).set_index("ticker")
    agg["fut_near_settle"] = first["settle"]
    agg["fut_near_expiry"] = first["expiry"]
    agg["fut_next_settle"] = second["settle"]
    agg["fut_next_expiry"] = second["expiry"]
    agg["has_future"] = 1

    opt = norm[norm["kind"].isin(["CE", "PE"])]
    go = opt.groupby(["ticker", "kind"])
    oi = go["oi"].sum(min_count=1).unstack("kind")
    vol = go["volume_contracts"].sum(min_count=1).unstack("kind")
    oagg = pd.DataFrame(index=oi.index)
    oagg["opt_call_oi"] = oi.get("CE")
    oagg["opt_put_oi"] = oi.get("PE")
    oagg["opt_call_volume"] = vol.get("CE")
    oagg["opt_put_volume"] = vol.get("PE")
    oagg["n_strikes"] = opt.groupby("ticker")["strike"].nunique()
    oagg["has_option"] = 1

    out = agg.join(oagg, how="outer")
    out.index.name = "ticker"
    out = out.reset_index()
    out["has_future"] = out["has_future"].fillna(0).astype("int8")
    out["has_option"] = out["has_option"].fillna(0).astype("int8")
    out.insert(0, "date", ts)
    out["fut_near_days_to_expiry"] = (out["fut_near_expiry"] - ts).dt.days
    out["source_format"] = fmt
    meta["n_stocks_fut"] = int(out["has_future"].sum())
    meta["n_stocks_opt"] = int(out["has_option"].sum())
    return out[FO_COLS], meta


def fo_contract_oi(path: Path) -> pd.DataFrame:
    """Per-contract futures OI (ticker, expiry, oi, oi_chg) -- used by the
    unit-continuity check across the 2024-07 format switch."""
    d, fmt = fo_file_date(path.name)
    norm, _ = _normalise_fo(_read_zip_csv(path), fmt)
    f = norm[norm["kind"] == "FUT"][["ticker", "expiry", "oi", "oi_chg",
                                     "volume_contracts", "turnover_rs", "settle"]]
    return f.assign(date=pd.Timestamp(d))


# --------------------------------------------------------------------------- #
# ind_close_all
# --------------------------------------------------------------------------- #

IDX_MAP = {"Index Name": "index_name", "Index Date": "index_date",
           "Open Index Value": "open", "High Index Value": "high",
           "Low Index Value": "low", "Closing Index Value": "close",
           "Points Change": "points_change", "Change(%)": "pct_change",
           "Volume": "volume", "Turnover (Rs. Cr.)": "turnover_cr",
           "P/E": "pe", "P/B": "pb", "Div Yield": "div_yield"}


def parse_index_file(path: Path) -> tuple[pd.DataFrame, dict]:
    d = ddmmyyyy_date(IDX_RE, path.name)
    raw = path.read_bytes().decode("latin-1")
    df = pd.read_csv(io.StringIO(raw), dtype=str)
    df = df.rename(columns=lambda c: str(c).strip().lstrip("﻿"))
    df = df.rename(columns=IDX_MAP)
    df["index_name"] = df["index_name"].astype(str).str.strip()
    raw_dates = df["index_date"].astype(str).str.strip()
    # dd-mm-yyyy is the normal format; a few 2023 files print mm-dd-yyyy. A
    # format is accepted only if it yields exactly the file-name date.
    stamps, date_fmt = None, None
    for fmt in ("%d-%m-%Y", "%m-%d-%Y", "%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        cand = sorted(set(pd.to_datetime(raw_dates, format=fmt, errors="coerce")
                          .dt.date.astype(str)))
        if stamps is None:
            stamps = cand
        if cand == [d.isoformat()]:
            stamps, date_fmt = cand, fmt
            break
    for c in ["open", "high", "low", "close", "points_change", "pct_change",
              "volume", "turnover_cr", "pe", "pb", "div_yield"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c].astype(str).str.strip().replace({"-": None, "": None}),
                                  errors="coerce")
        else:
            df[c] = np.nan
    dup = df["index_name"].duplicated(keep="first")
    meta = {"file": path.name, "file_date": d.isoformat(), "rows": int(len(df)),
            "content_dates": stamps, "date_ok": stamps == [d.isoformat()],
            "date_format": date_fmt, "n_duplicate_names": int(dup.sum())}
    df = df[~dup]
    df.insert(0, "date", pd.Timestamp(d))
    return df[["date", "index_name", "open", "high", "low", "close", "pct_change",
               "volume", "turnover_cr", "pe", "pb", "div_yield"]], meta


# --------------------------------------------------------------------------- #
# participant-wise OI
# --------------------------------------------------------------------------- #

TITLE_DATE_RE = re.compile(r"as on\s+([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})", re.I)


def parse_participant_file(path: Path) -> tuple[pd.DataFrame, dict]:
    d = ddmmyyyy_date(PART_RE, path.name)
    txt = path.read_bytes().decode("latin-1").replace("\r\n", "\n").replace("\r", "\n")
    rows = [r for r in csv.reader(io.StringIO(txt))]
    rows = [[c.strip().strip('"').strip() for c in r] for r in rows if any(x.strip() for x in r)]
    title = " ".join(rows[0]) if rows else ""
    hdr_i = next(i for i, r in enumerate(rows) if r and r[0].lower() == "client type")
    hdr = [h.strip() for h in rows[hdr_i]]
    body = rows[hdr_i + 1:]
    m = TITLE_DATE_RE.search(title)
    tdate = None
    if m:
        try:
            tdate = datetime.strptime(f"{m.group(1)[:3]} {m.group(2)} {m.group(3)}",
                                      "%b %d %Y").date()
        except ValueError:
            tdate = None
    recs = []
    for r in body:
        if not r or not r[0]:
            continue
        rec = {"date": pd.Timestamp(d), "client_type": r[0].strip()}
        for j, h in enumerate(hdr[1:], start=1):
            key = PART_NUMERIC.get(h)
            if key is None:
                continue
            v = r[j].replace(",", "").strip() if j < len(r) else ""
            rec[key] = float(v) if v not in ("", "-") else np.nan
        recs.append(rec)
    df = pd.DataFrame(recs)
    missing_cols = [v for v in PART_NUMERIC.values() if v not in df.columns]
    for c in missing_cols:
        df[c] = np.nan
    meta = {"file": path.name, "file_date": d.isoformat(), "title": title[:160],
            "title_date": tdate.isoformat() if tdate else None,
            "date_ok": tdate == d, "client_types": df["client_type"].tolist(),
            "missing_columns": missing_cols}
    return df[["date", "client_type"] + list(PART_NUMERIC.values())], meta


# --------------------------------------------------------------------------- #
# cached driver
# --------------------------------------------------------------------------- #

def _cache_key(path: Path) -> str:
    st = path.stat()
    return f"{path.name}|{st.st_size}|{int(st.st_mtime)}"


def _parse_all(kind: str, files: list[Path], fn, use_cache: bool = True,
               update_cache: bool = True) -> tuple[pd.DataFrame, list[dict]]:
    """Parse files, reusing per-file results cached under ml/data_ext/_cache/
    (keyed by name, size, mtime). use_cache=False parses every file from the
    raw bytes; update_cache=False never writes the cache (truncated runs)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cpq = CACHE_DIR / f"{kind}_frames.parquet"
    cmeta = CACHE_DIR / f"{kind}_meta.json"
    old_df = pd.read_parquet(cpq) if (use_cache and cpq.exists()) else None
    old_meta = json.loads(cmeta.read_text()) if (use_cache and cmeta.exists()) else {}
    keep_keys, frames, metas = set(), [], []
    todo = []
    for p in files:
        k = _cache_key(p)
        if k in old_meta:
            keep_keys.add(k)
            metas.append(old_meta[k])
        else:
            todo.append((k, p))
    if old_df is not None and keep_keys:
        keep_files = {k.split("|")[0] for k in keep_keys}
        frames.append(old_df[old_df["_file"].isin(keep_files)])
    new_meta = {k: old_meta[k] for k in keep_keys}
    for i, (k, p) in enumerate(todo, 1):
        try:
            df, meta = fn(p)
        except Exception as exc:  # noqa: BLE001 -- a bad file is reported, not fatal
            meta = {"file": p.name, "error": f"{type(exc).__name__}: {exc}", "date_ok": False}
            df = None
        if df is not None:
            frames.append(df.assign(_file=p.name))
        new_meta[k] = meta
        metas.append(meta)
        if i % 100 == 0:
            print(f"  {kind}: parsed {i}/{len(todo)} new files", flush=True)
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if update_cache:
        out.to_parquet(cpq, index=False)
        cmeta.write_text(json.dumps(new_meta))
    return out, metas


def list_raw(kind: str, max_date: date | None = None,
             raw_dirs: dict | None = None) -> list[Path]:
    dirs = {"fo": C.RAW_FO, "indices": C.RAW_IDX, "participant": C.RAW_PART}
    if raw_dirs:
        dirs.update(raw_dirs)
    if kind == "fo":
        files = [p for p in dirs["fo"].glob("*.zip") if fo_file_date(p.name)]
        dates = {p: fo_file_date(p.name)[0] for p in files}
    elif kind == "indices":
        files = [p for p in dirs["indices"].glob("ind_close_all_*.csv")]
        dates = {p: ddmmyyyy_date(IDX_RE, p.name) for p in files}
    else:
        files = [p for p in dirs["participant"].glob("fao_participant_oi_*.csv")]
        dates = {p: ddmmyyyy_date(PART_RE, p.name) for p in files}
    files = [p for p in files if dates[p] is not None
             and (max_date is None or dates[p] <= max_date)]
    return sorted(files, key=lambda p: dates[p])


def load_spot() -> pd.DataFrame:
    """Spot close and 20-session median turnover per (date, ticker) from the
    EOD export (EQ/BE rows), keyed on the EOD export's own dates."""
    eod = pd.read_parquet(C.EOD_EXPORT, columns=["date", "ticker", "close", "turnover"])
    eod["date"] = pd.to_datetime(eod["date"])
    return eod


def build_fo_daily(fo_frames: pd.DataFrame, eod: pd.DataFrame) -> pd.DataFrame:
    fo = fo_frames.drop(columns=["_file"], errors="ignore").copy()
    # spot from the EOD export on the same session (alias for misdated sessions,
    # only where the export holds the alias target and not the true date)
    eod_dates = set(eod["date"].dt.date.unique())
    amap = {s: d for s, d in EXT_TO_EOD_ALIAS.items() if d in eod_dates and s not in eod_dates}
    fo["_eod_date"] = fo["date"].map(lambda t: pd.Timestamp(amap.get(t.date(), t.date())))
    spot = eod.rename(columns={"date": "_eod_date", "close": "spot_close"})[
        ["_eod_date", "ticker", "spot_close"]]
    fo = fo.merge(spot, on=["_eod_date", "ticker"], how="left").drop(columns="_eod_date")
    dte = fo["fut_near_days_to_expiry"]
    with np.errstate(divide="ignore", invalid="ignore"):
        b = (fo["fut_near_settle"] / fo["spot_close"] - 1.0) * 365.0 / dte
    fo["basis_near"] = b.where((dte >= 2) & (fo["spot_close"] > 0) & (fo["fut_near_settle"] > 0))
    fo = fo.sort_values(["date", "ticker"]).reset_index(drop=True)
    return fo


def run(max_date: date | None = None, write: bool = True, raw_dirs: dict | None = None,
        use_cache: bool = True) -> dict:
    """Parse all raw files dated <= max_date. A truncated or no-write run
    reads the per-file cache but never rewrites it."""
    C.ensure_dirs()
    report: dict = {"built_at": datetime.now().isoformat(timespec="seconds")}
    eod = load_spot()
    if max_date is not None:
        eod = eod[eod["date"] <= pd.Timestamp(max_date)]
    upd = write and max_date is None and raw_dirs is None and use_cache

    fo_files = list_raw("fo", max_date, raw_dirs)
    fo_frames, fo_meta = _parse_all("fo", fo_files, aggregate_fo, use_cache, upd)
    bad_fo = {m["file"] for m in fo_meta if not m.get("date_ok")}
    if len(fo_frames):
        fo_frames = fo_frames[~fo_frames["_file"].isin(bad_fo)]
    fo = build_fo_daily(fo_frames, eod) if len(fo_frames) else pd.DataFrame(columns=FO_COLS)
    report["fo"] = {"files_parsed": len(fo_files), "files_excluded_date_mismatch_or_error":
                    sorted(bad_fo), "rows": int(len(fo)),
                    "dates": int(fo["date"].nunique()) if len(fo) else 0,
                    "meta_sample": fo_meta[:2]}

    idx_files = list_raw("indices", max_date, raw_dirs)
    idx_frames, idx_meta = _parse_all("indices", idx_files, parse_index_file, use_cache, upd)
    bad_idx = {m["file"] for m in idx_meta if not m.get("date_ok")}
    idx = idx_frames[~idx_frames["_file"].isin(bad_idx)].drop(columns="_file") \
        if len(idx_frames) else pd.DataFrame()
    report["indices"] = {"files_parsed": len(idx_files),
                         "files_excluded_date_mismatch_or_error": sorted(bad_idx),
                         "rows": int(len(idx))}

    part_files = list_raw("participant", max_date, raw_dirs)
    part_frames, part_meta = _parse_all("participant", part_files, parse_participant_file,
                                        use_cache, upd)
    bad_part = {m["file"] for m in part_meta if not m.get("date_ok")}
    part = part_frames[~part_frames["_file"].isin(bad_part)].drop(columns="_file") \
        if len(part_frames) else pd.DataFrame()
    report["participant"] = {"files_parsed": len(part_files),
                             "files_excluded_date_mismatch_or_error": sorted(bad_part),
                             "rows": int(len(part))}
    if write:
        fo.to_parquet(C.EXT / "fo_daily_stock.parquet", index=False)
        idx.sort_values(["date", "index_name"]).to_parquet(C.EXT / "index_daily.parquet",
                                                           index=False)
        part.sort_values(["date", "client_type"]).to_parquet(
            C.EXT / "fo_participant_oi.parquet", index=False)
        (C.OUT / "parse_meta.json").write_text(json.dumps(
            {"fo": fo_meta, "indices": idx_meta, "participant": part_meta}, indent=0))
    report["_frames"] = (fo, idx, part)
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-date", default=None)
    a = ap.parse_args()
    md = date.fromisoformat(a.max_date) if a.max_date else None
    rep = run(md)
    rep.pop("_frames")
    print(json.dumps({k: (v if k != "fo" else {kk: vv for kk, vv in v.items()
                                               if kk != "meta_sample"})
                      for k, v in rep.items()}, indent=1, default=str))


if __name__ == "__main__":
    main()

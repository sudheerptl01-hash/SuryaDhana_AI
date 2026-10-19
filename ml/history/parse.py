#!/usr/bin/env python3
"""Parse the legacy CM bhavcopy + MTO delivery + PR bundle into staging tables.

Per session day (incremental, idempotent):
  parts/eod/<YYYYMMDD>.parquet   equity_eod rows (EOD_COLUMNS of nse_historical_ingest.py)
  parts/aux/<YYYYMMDD>.json      diagnostics, Bc records, ETF rows, Pd CORP_IND rows, index rows

Assembly (any time; the final names only with --final after the download ends):
  ml/data_hist/equity_eod_2016_2021.parquet    window 2016-10-03 .. 2021-09-30
  ml/data_hist/bc_records_2016_2021.csv        every Bc record + source_file + bundle_date
  ml/data_hist/etf_records_2016_2021.csv       symbol, first_seen, last_seen, underlying, ...
  ml/data_hist/pd_corp_ind_2016_2021.csv       Pd rows with a non-blank CORP_IND
  ml/data_hist/index_close_2016_2021.csv       Pd index rows (Nifty 50, India VIX, ...)
  ml/data_hist/overlap_cm_mto_2021-10.parquet  the overlap days (validation only, not for upsert)

Mapping (legacy CM -> equity_eod): prev_close=PREVCLOSE, open=OPEN, high=HIGH, low=LOW,
last=LAST, close=CLOSE, volume=TOTTRDQTY, turnover=TOTTRDVAL * TURNOVER_FACTOR (rupees),
trades=TOTALTRADES, vwap=round(TOTTRDVAL/TOTTRDQTY, 2), isin=ISIN, deliv_qty / deliv_pct
from MTO joined on SYMBOL + SERIES (NaN where MTO has no row), source='cm_mto'.

Usage:  OMP_NUM_THREADS=2 python3 -I ml/history/parse.py [--final] [--reparse]
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import zipfile
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

from ml.history.common import (  # noqa: E402
    OVERLAP_DAYS, PARTS, STAGE, WINDOW_END, WINDOW_START, get_logger, local_path, read_manifest,
)

EOD_COLUMNS = [
    "date", "ticker", "series", "isin",
    "prev_close", "open", "high", "low", "last", "close", "vwap",
    "volume", "turnover", "trades", "deliv_qty", "deliv_pct",
    "source",
]
SCHEMA = pa.schema([
    ("date", pa.date32()), ("ticker", pa.string()), ("series", pa.string()), ("isin", pa.string()),
    ("prev_close", pa.float64()), ("open", pa.float64()), ("high", pa.float64()),
    ("low", pa.float64()), ("last", pa.float64()), ("close", pa.float64()), ("vwap", pa.float64()),
    ("volume", pa.int64()), ("turnover", pa.float64()), ("trades", pa.int64()),
    ("deliv_qty", pa.int64()), ("deliv_pct", pa.float64()), ("source", pa.string()),
])
# Rupees in both: the legacy TOTTRDVAL is rupees, the store's turnover is TURNOVER_LACS * 1e5.
# Verified on the overlap days by validate.py (overlap.turnover_factor in history.json).
TURNOVER_FACTOR = 1.0
VWAP_DECIMALS = 2          # the store's vwap is sec_bhavdata AVG_PRICE, printed to 2 decimals
SOURCE = "cm_mto"
PARSER_VERSION = 3

EOD_DIR, AUX_DIR = PARTS / "eod", PARTS / "aux"
log = get_logger("hist.parse")


def _to_num(series: pd.Series) -> pd.Series:
    """Same coercion as nse_historical_ingest._to_num."""
    return pd.to_numeric(series.astype(str).str.replace(",", "", regex=False).str.strip(),
                         errors="coerce")


def _zip_member(zf: zipfile.ZipFile, pattern: str) -> str | None:
    rx = re.compile(pattern, re.IGNORECASE)
    hits = [n for n in zf.namelist() if rx.fullmatch(Path(n).name)]
    return hits[0] if hits else None


def _read_csv_str(raw: bytes) -> pd.DataFrame:
    """Every cell as raw text; 'NA' is a real NSE series code, never a null."""
    try:
        df = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False)
    except UnicodeDecodeError:
        df = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False, encoding="latin-1")
    df.columns = [str(c).strip().upper() for c in df.columns]
    return df.loc[:, [c for c in df.columns if c and not c.startswith("UNNAMED")]]


# --------------------------------------------------------------------------- CM
def read_cm(path: Path, d: date) -> tuple[pd.DataFrame, dict]:
    with zipfile.ZipFile(path) as zf:
        name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        raw = zf.read(name)
    if raw.lstrip()[:1] == b"<":
        raise ValueError(f"{path.name}: HTML body inside the zip")
    df = _read_csv_str(raw)
    need = ["SYMBOL", "SERIES", "OPEN", "HIGH", "LOW", "CLOSE", "LAST", "PREVCLOSE",
            "TOTTRDQTY", "TOTTRDVAL", "TIMESTAMP", "TOTALTRADES", "ISIN"]
    miss = [c for c in need if c not in df.columns]
    if miss:
        raise ValueError(f"{path.name}: missing columns {miss}; got {list(df.columns)}")
    ts = df["TIMESTAMP"].str.strip().str.upper()
    ts_dates = pd.to_datetime(ts, format="%d-%b-%Y", errors="coerce").dt.date
    n_ts_bad = int((ts_dates != d).sum())
    vol = _to_num(df["TOTTRDQTY"])
    val = _to_num(df["TOTTRDVAL"])
    isin = df["ISIN"].str.strip()
    out = pd.DataFrame({
        "date": d,
        "ticker": df["SYMBOL"].str.strip(),
        "series": df["SERIES"].str.strip(),
        "isin": isin.where(isin != "", None),
        "prev_close": _to_num(df["PREVCLOSE"]),
        "open": _to_num(df["OPEN"]),
        "high": _to_num(df["HIGH"]),
        "low": _to_num(df["LOW"]),
        "last": _to_num(df["LAST"]),
        "close": _to_num(df["CLOSE"]),
        "vwap": (val / vol.where(vol > 0)).round(VWAP_DECIMALS),
        "volume": vol,
        "turnover": val * TURNOVER_FACTOR,
        "trades": _to_num(df["TOTALTRADES"]),
    })
    n_raw = len(out)
    out = out[out["close"].notna() & (out["ticker"].str.len() > 0)]
    n_dup = int(out.duplicated(["ticker", "series"], keep="last").sum())
    out = out.drop_duplicates(["ticker", "series"], keep="last").reset_index(drop=True)
    diag = {"cm_file": path.name, "cm_rows_raw": n_raw, "cm_rows": len(out), "cm_dup_rows": n_dup,
            "cm_timestamp_mismatch_rows": n_ts_bad,
            "cm_timestamps": sorted(set(ts.unique().tolist()))[:3]}
    return out, diag


# --------------------------------------------------------------------------- MTO
_TRADE_DATE = re.compile(r"Trade Date\s*<([^>]+)>", re.IGNORECASE)


def read_mto(path: Path, d: date) -> tuple[pd.DataFrame, dict]:
    text = path.read_bytes().decode("latin-1")
    lines = text.splitlines()
    m = _TRADE_DATE.search("\n".join(lines[:5]))
    trade_date = None
    if m:
        try:
            trade_date = datetime.strptime(m.group(1).strip().title(), "%d-%b-%Y").date()
        except ValueError:
            trade_date = None
    recs, bad = [], 0
    for ln in lines:
        if not ln.startswith("20,"):
            continue
        f = [x.strip() for x in ln.split(",")]
        if len(f) < 7:
            bad += 1
            continue
        # 20,<sr>,<SYMBOL>,<SERIES>,<qty>,<deliv qty>,<deliv %>; tolerate commas inside SYMBOL
        recs.append((",".join(f[2:-4]), f[-4], f[-3], f[-2], f[-1]))
    mto = pd.DataFrame(recs, columns=["ticker", "series", "mto_qty", "deliv_qty", "deliv_pct"])
    for c in ("mto_qty", "deliv_qty", "deliv_pct"):
        mto[c] = _to_num(mto[c])
    n_dup = int(mto.duplicated(["ticker", "series"], keep="last").sum())
    mto = mto.drop_duplicates(["ticker", "series"], keep="last")
    diag = {"mto_file": path.name, "mto_rows": len(mto), "mto_bad_lines": bad, "mto_dup_rows": n_dup,
            "mto_trade_date": trade_date.isoformat() if trade_date else None,
            "mto_trade_date_ok": trade_date == d,
            "mto_series": mto["series"].value_counts().to_dict()}
    return mto, diag


# --------------------------------------------------------------------------- PR bundle
def read_pr(path: Path, d: date) -> tuple[dict, dict]:
    out: dict[str, list] = {"bc": [], "etf": [], "pd_corp": [], "idx": []}
    diag: dict = {"pr_file": path.name}
    with zipfile.ZipFile(path) as zf:
        diag["pr_members"] = sorted(Path(n).name for n in zf.namelist())
        bc = _zip_member(zf, r"bc\d{6}\.csv")
        etf = _zip_member(zf, r"etf\d{6}\.csv")
        pdn = _zip_member(zf, r"pd\d{6}\.csv")
        diag.update({"bc_member": bc, "etf_member": etf, "pd_member": pdn})
        if bc:
            df = _read_csv_str(zf.read(bc))
            df = df.apply(lambda s: s.str.strip())
            df["source_file"] = f"{path.name}/{Path(bc).name}"
            df["bundle_date"] = d.isoformat()
            out["bc"] = df.to_dict("records")
        if etf:
            df = _read_csv_str(zf.read(etf)).apply(lambda s: s.str.strip())
            keep = [c for c in ("MARKET", "SERIES", "SYMBOL", "SECURITY", "UNDERLYING") if c in df.columns]
            df = df[keep].copy()
            df["bundle_date"] = d.isoformat()
            out["etf"] = df.to_dict("records")
        if pdn:
            df = _read_csv_str(zf.read(pdn)).apply(lambda s: s.str.strip())
            if "CORP_IND" in df.columns:
                c = df[df["CORP_IND"] != ""].copy()
                c["bundle_date"] = d.isoformat()
                out["pd_corp"] = c.to_dict("records")
            if "IND_SEC" in df.columns:
                ix = df[(df["IND_SEC"] == "Y")].copy()
                ix = ix[[k for k in ("SECURITY", "PREV_CL_PR", "OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE",
                                     "CLOSE_PRICE") if k in ix.columns]]
                ix["date"] = d.isoformat()
                out["idx"] = ix.to_dict("records")
    diag.update({k + "_rows": len(v) for k, v in out.items()})
    return out, diag


# --------------------------------------------------------------------------- day
def build_day(d: date) -> tuple[pd.DataFrame, dict]:
    cm, diag = read_cm(local_path("cm", d), d)
    mp, pp = local_path("mto", d), local_path("pr", d)
    diag["has_mto"], diag["has_pr"] = mp.exists(), pp.exists()
    if mp.exists():
        mto, dm = read_mto(mp, d)
        diag.update(dm)
        j = cm.merge(mto, on=["ticker", "series"], how="left", indicator=True)
        hit = j["_merge"] == "both"
        diag["mto_matched_rows"] = int(hit.sum())
        diag["mto_unmatched_rows"] = int(len(mto) - hit.sum())
        diag["mto_qty_equals_volume"] = int((j.loc[hit, "mto_qty"] == j.loc[hit, "volume"]).sum())
        eqbe = j["series"].isin(["EQ", "BE"])
        diag["eqbe_rows"] = int(eqbe.sum())
        diag["eqbe_with_deliv"] = int((eqbe & j["deliv_pct"].notna()).sum())
        cm = j.drop(columns=["_merge", "mto_qty"])
    else:
        cm["deliv_qty"], cm["deliv_pct"] = np.nan, np.nan
        eqbe = cm["series"].isin(["EQ", "BE"])
        diag["eqbe_rows"], diag["eqbe_with_deliv"] = int(eqbe.sum()), 0
    cm["source"] = SOURCE
    aux = {}
    if pp.exists():
        aux, dp = read_pr(pp, d)
        diag.update(dp)
    diag["parser_version"] = PARSER_VERSION
    return cm[EOD_COLUMNS], {"diag": diag, **aux}


def to_table(df: pd.DataFrame) -> pa.Table:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    for c in ("volume", "trades", "deliv_qty"):
        df[c] = pd.array(np.round(df[c].astype("float64")), dtype="Int64")
    for c in ("prev_close", "open", "high", "low", "last", "close", "vwap", "turnover", "deliv_pct"):
        df[c] = df[c].astype("float64")
    return pa.Table.from_pandas(df[EOD_COLUMNS], schema=SCHEMA, preserve_index=False)


# --------------------------------------------------------------------------- incremental
def complete_days(final: bool) -> list[date]:
    """Session days whose CM is on disk and whose MTO / PR outcome is known."""
    man = read_manifest()
    days = []
    for (iso, kind), r in man.items():
        if kind != "cm":
            continue
        d = date.fromisoformat(iso)
        if not local_path("cm", d).exists():
            continue
        ok = True
        for k in ("mto", "pr"):
            if local_path(k, d).exists():
                continue
            rk = man.get((iso, k))
            known = rk is not None and isinstance(rk.get("status"), int)
            if not known and not (final and rk is not None):
                ok = False
        if ok:
            days.append(d)
    return sorted(days)


def parse_incremental(final: bool = False, reparse: bool = False) -> int:
    EOD_DIR.mkdir(parents=True, exist_ok=True)
    AUX_DIR.mkdir(parents=True, exist_ok=True)
    n = 0
    for d in complete_days(final):
        ep, ap = EOD_DIR / f"{d:%Y%m%d}.parquet", AUX_DIR / f"{d:%Y%m%d}.json"
        if ep.exists() and ap.exists() and not reparse:
            try:
                old = json.loads(ap.read_text())["diag"]
                stale = (old.get("parser_version") != PARSER_VERSION
                         or old.get("has_mto") != local_path("mto", d).exists()
                         or old.get("has_pr") != local_path("pr", d).exists())
            except Exception:  # noqa: BLE001
                stale = True
            if not stale:
                continue
        try:
            eod, aux = build_day(d)
        except Exception as exc:  # noqa: BLE001
            log.error("%s parse failed: %r", d, exc)
            continue
        pq.write_table(to_table(eod), ep.with_suffix(".parquet.part"))
        ep.with_suffix(".parquet.part").replace(ep)
        ap.write_text(json.dumps(aux, default=str))
        n += 1
    log.info("parsed %d day(s); parts on disk: %d", n, len(list(EOD_DIR.glob("*.parquet"))))
    return n


def load_parts(start: date, end: date) -> tuple[pd.DataFrame, list[dict]]:
    frames, auxes = [], []
    for ep in sorted(EOD_DIR.glob("*.parquet")):
        d = datetime.strptime(ep.stem, "%Y%m%d").date()
        if not (start <= d <= end):
            continue
        frames.append(pq.read_table(ep))
        ap = AUX_DIR / f"{ep.stem}.json"
        auxes.append(json.loads(ap.read_text()) if ap.exists() else {"diag": {}})
    if not frames:
        return pd.DataFrame(columns=EOD_COLUMNS), []
    tab = pa.concat_tables(frames)
    return tab.to_pandas(), auxes


def assemble(final: bool) -> dict:
    """Write the staging outputs (final names only when final=True)."""
    STAGE.mkdir(parents=True, exist_ok=True)
    sfx = "" if final else ".partial"
    frames = []
    for ep in sorted(EOD_DIR.glob("*.parquet")):
        d = datetime.strptime(ep.stem, "%Y%m%d").date()
        if WINDOW_START <= d <= WINDOW_END:
            frames.append(pq.read_table(ep))
    res: dict = {}
    if frames:
        tab = pa.concat_tables(frames).cast(SCHEMA)
        tab = tab.sort_by([("date", "ascending"), ("ticker", "ascending"), ("series", "ascending")])
        p = STAGE / f"equity_eod_2016_2021{sfx}.parquet"
        pq.write_table(tab, p.with_suffix(".parquet.part"), compression="zstd")
        p.with_suffix(".parquet.part").replace(p)
        res["eod"] = {"path": str(p), "rows": tab.num_rows}
    ov = [pq.read_table(EOD_DIR / f"{d:%Y%m%d}.parquet") for d in OVERLAP_DAYS
          if (EOD_DIR / f"{d:%Y%m%d}.parquet").exists()]
    if ov:
        p = STAGE / "overlap_cm_mto_2021-10.parquet"
        pq.write_table(pa.concat_tables(ov), p)
        res["overlap"] = {"path": str(p), "rows": sum(t.num_rows for t in ov)}

    bc, etf, pdc, idx = [], [], [], []
    for ap in sorted(AUX_DIR.glob("*.json")):
        d = datetime.strptime(ap.stem, "%Y%m%d").date()
        if not (WINDOW_START <= d <= WINDOW_END):
            continue
        a = json.loads(ap.read_text())
        bc += a.get("bc", [])
        etf += a.get("etf", [])
        pdc += a.get("pd_corp", [])
        idx += a.get("idx", [])
    if bc:
        b = pd.DataFrame(bc)
        lead = ["SERIES", "SYMBOL", "SECURITY", "RECORD_DT", "BC_STRT_DT", "BC_END_DT", "EX_DT",
                "ND_STRT_DT", "ND_END_DT", "PURPOSE"]
        cols = [c for c in lead if c in b.columns] + \
               [c for c in b.columns if c not in lead and c not in ("source_file", "bundle_date")] + \
               ["source_file", "bundle_date"]
        b = b[cols].sort_values(["bundle_date", "SYMBOL", "SERIES"], kind="stable")
        p = STAGE / f"bc_records_2016_2021{sfx}.csv"
        b.to_csv(p, index=False)
        key = [c for c in ("SYMBOL", "SERIES", "EX_DT", "RECORD_DT", "PURPOSE") if c in b.columns]
        res["bc"] = {"path": str(p), "rows": len(b), "distinct_events": int(len(b.drop_duplicates(key)))}
    if etf:
        e = pd.DataFrame(etf)
        e = e.sort_values(["bundle_date"], kind="stable")
        g = e.groupby("SYMBOL", sort=True)
        und = g["UNDERLYING"].agg(lambda s: s[s != ""].iloc[-1] if (s != "").any() else "") \
            if "UNDERLYING" in e.columns else ""
        allund = g["UNDERLYING"].agg(lambda s: " | ".join(dict.fromkeys(x for x in s if x))) \
            if "UNDERLYING" in e.columns else ""
        er = pd.DataFrame({
            "symbol": g.size().index,
            "first_seen": g["bundle_date"].min().values,
            "last_seen": g["bundle_date"].max().values,
            "underlying": und.values if hasattr(und, "values") else und,
            "n_bundles": g.size().values,
            "series": g["SERIES"].agg(lambda s: " | ".join(dict.fromkeys(s))).values,
            "security": g["SECURITY"].last().values,
            "underlying_history": allund.values if hasattr(allund, "values") else allund,
        })
        p = STAGE / f"etf_records_2016_2021{sfx}.csv"
        er.to_csv(p, index=False)
        res["etf"] = {"path": str(p), "symbols": len(er)}
    if pdc:
        pc = pd.DataFrame(pdc)
        p = STAGE / f"pd_corp_ind_2016_2021{sfx}.csv"
        pc.to_csv(p, index=False)
        res["pd_corp"] = {"path": str(p), "rows": len(pc)}
    if idx:
        ix = pd.DataFrame(idx)
        p = STAGE / f"index_close_2016_2021{sfx}.csv"
        ix.to_csv(p, index=False)
        res["idx"] = {"path": str(p), "rows": len(ix)}
    if final:
        for q in STAGE.glob("*.partial.*"):
            q.unlink()
    log.info("assembled (%s): %s", "final" if final else "partial",
             {k: {kk: vv for kk, vv in v.items() if kk != "path"} for k, v in res.items()})
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", action="store_true", help="download finished: write the final names")
    ap.add_argument("--reparse", action="store_true")
    ap.add_argument("--no-assemble", action="store_true")
    a = ap.parse_args(argv)
    parse_incremental(final=a.final, reparse=a.reparse)
    if not a.no_assemble:
        assemble(final=a.final)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

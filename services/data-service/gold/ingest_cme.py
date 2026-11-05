"""CME Group FTP (SOURCES.md C1–C4; the www host is never touched — it 403s this IP and its terms forbid scripts).

- C1 ``daily_volume.xlsx`` → ``gold_cme_daily_voi`` (COMEX GC/MGC/1OZ/QO/OG calls+puts, SI/SIL/SIC), ``oi_change``
  derived against the prior trade_date with a LAG over the table (so out-of-order backfills heal themselves)
- C2 ``efrp-report.csv`` → ``gold_cme_efrp`` (GOLD rows only)
- C3 ``product-calendar-new.xml`` (38 MB) → ``gold_cme_calendar`` via ``xml.etree.iterparse`` (never loaded whole)
- C4 ``cmeg.comex.fut.prf.csv.zip`` → ``gold_cme_prf`` + ``gold_margins`` (COMEX InitMargin)

Options rows: ``product_code`` stays ``OG`` and ``fut_or_opt`` is ``C`` / ``P`` (calls / puts) so the primary key
holds; futures rows carry ``F``. Backfills are resumable (skip stored dates) and paced 1 file / 2 s by ``ftp_fetch``.
"""
from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from gold import db, pit
from gold.db import utcnow
from gold.hosts import ftp_fetch
from shared.logging import get_logger

logger = get_logger(__name__)

FTP_VOI_LATEST = "ftp://ftp.cmegroup.com/daily_volume/daily_volume.xlsx"
FTP_VOI_ARCHIVE = "ftp://ftp.cmegroup.com/daily_volume/daily_volume_{yyyymmdd}.xlsx"
FTP_EFRP_LATEST = "ftp://ftp.cmegroup.com/efrp/efrp_transaction_breakdown/efrp-report.csv"
FTP_EFRP_ARCHIVE = "ftp://ftp.cmegroup.com/efrp/efrp_transaction_breakdown/efrp-report_{yyyymmdd}.csv"
FTP_CALENDAR = "ftp://ftp.cmegroup.com/span/util/product-calendar-new.xml"
FTP_PRF = "ftp://ftp.cmegroup.com/pub/fprf/csv/cmeg.comex.fut.prf.csv.zip"

VOI_ARCHIVE_START = date(2014, 1, 2)
EFRP_ARCHIVE_START = date(2017, 1, 20)
GOLD_SILVER_CODES: frozenset[str] = frozenset({"GC", "MGC", "1OZ", "QO", "OG", "SI", "SIL", "SIC", "SO"})
VOI_SHEET = "CME Group Vol and OI by Product"
EXCHANGE = "COMEX"


def _norm(s: Any) -> str:
    return re.sub(r"[\s①②③]+", " ", str(s or "")).strip()


def _int(v: Any) -> int | None:
    try:
        if v in (None, "", "-"):
            return None
        return round(float(v))
    except (TypeError, ValueError):
        return None


def _mdY(v: Any) -> date | None:
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.date()
    try:
        return db.strptime(str(v).strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


# ── C1 daily volume & OI ────────────────────────────────────────────────────────────────────────────

def parse_daily_volume(xlsx_bytes: bytes, *, now: datetime | None = None, codes: frozenset[str] = GOLD_SILVER_CODES) -> pd.DataFrame:
    """Rows for the COMEX gold/silver products from one ``daily_volume*.xlsx`` (streamed; read-only mode)."""
    import openpyxl

    now = now or utcnow()
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
    try:
        ws = wb[VOI_SHEET] if VOI_SHEET in wb.sheetnames else wb[wb.sheetnames[-1]]
        ws.reset_dimensions()
        trade_date: date | None = None
        header: list[str] | None = None
        rows: list[dict[str, Any]] = []
        for row in ws.iter_rows(values_only=True):
            if not row or all(c is None for c in row):
                continue
            first = _norm(row[0])
            if trade_date is None and first.lower().startswith("trade date"):
                trade_date = _mdY(first.split(":", 1)[1].strip())
                continue
            if header is None:
                if first == "Description":
                    header = [_norm(c) for c in row]
                continue
            rec = dict(zip(header, row))
            if not str(rec.get("Exchange Name") or "").upper().startswith("COMEX"):
                continue
            code = _norm(rec.get("Commodity Indicator"))
            if code not in codes:
                continue
            desc = _norm(rec.get("Product Description"))
            foi = _norm(rec.get("Future/Option Indicator")) or "F"
            if foi == "O":
                foi = "C" if "CALL" in desc.upper() else ("P" if "PUT" in desc.upper() else "O")
            rows.append({"trade_date": trade_date, "exchange": EXCHANGE, "product_code": code, "product_desc": desc, "fut_or_opt": foi,
                         "globex_volume": _int(rec.get("CME® Globex® Volume") or rec.get("CME Globex Volume")),
                         "pit_volume": _int(rec.get("Pit Volume")), "expit_volume": _int(rec.get("ExPit Volume")),
                         "otc_volume": _int(rec.get("OTC Volume")), "total_volume": _int(rec.get("Total Volume")),
                         "mtd_adv": _int(rec.get("MTD ADV")), "open_interest": _int(rec.get("Open Interest")), "oi_change": None,
                         "release_at": None, "first_seen_at": now, "source": "cme_ftp_daily_volume"})
    finally:
        wb.close()
    if trade_date is None:
        raise ValueError("daily_volume.xlsx: no 'Trade Date' cell")
    df = pd.DataFrame(rows)
    if not df.empty:
        df["release_at"] = [min(pit.release_rule("cme_voi", trade_date), now)] * len(df)
    return df


def recompute_oi_change(store: Any) -> int:
    """oi_change = OI − OI on the prior stored trade_date, per (exchange, product_code, fut_or_opt)."""
    db.execute(store, """
        UPDATE gold_cme_daily_voi SET oi_change = sub.d FROM (
            SELECT trade_date, exchange, product_code, fut_or_opt,
                   open_interest - LAG(open_interest) OVER (PARTITION BY exchange, product_code, fut_or_opt ORDER BY trade_date) AS d
            FROM gold_cme_daily_voi) AS sub
        WHERE gold_cme_daily_voi.trade_date = sub.trade_date AND gold_cme_daily_voi.exchange = sub.exchange
          AND gold_cme_daily_voi.product_code = sub.product_code AND gold_cme_daily_voi.fut_or_opt = sub.fut_or_opt
    """)
    return int(db.scalar(store, "SELECT COUNT(*) FROM gold_cme_daily_voi WHERE oi_change IS NOT NULL") or 0)


def ingest_daily_volume(store: Any, xlsx_bytes: bytes, *, now: datetime | None = None) -> dict[str, Any]:
    df = parse_daily_volume(xlsx_bytes, now=now)
    n = db.upsert(store, "gold_cme_daily_voi", df)
    recompute_oi_change(store)
    return {"rows": n, "trade_date": str(df["trade_date"].iloc[0]) if n else None}


def stored_voi_dates(store: Any) -> set[date]:
    df = db.query_df(store, "SELECT DISTINCT trade_date FROM gold_cme_daily_voi")
    return {pd.Timestamp(d).date() for d in df["trade_date"]} if not df.empty else set()


def backfill_daily_volume(store: Any, start: date, end: date, *, fetch: Callable[[str], bytes] = ftp_fetch,
                          progress: Callable[[int, int], None] | None = None, now: datetime | None = None,
                          max_files: int | None = None) -> dict[str, Any]:
    """Archive files one weekday at a time (resumable: stored dates are skipped; missing files are noted)."""
    have = stored_voi_dates(store)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    days = [d for d in days if d.weekday() < 5 and d not in have]
    if max_files:
        days = days[:max_files]
    done, missing, errors = 0, [], []
    for i, d in enumerate(days):
        url = FTP_VOI_ARCHIVE.format(yyyymmdd=d.strftime("%Y%m%d"))
        try:
            body = fetch(url)
        except Exception as exc:  # noqa: BLE001 — a missing archive day (holiday) is not a failure
            if "550" in str(exc) or "No such file" in str(exc):
                missing.append(d.isoformat())
            else:
                errors.append({"date": d.isoformat(), "error": str(exc)[:160]})
                logger.warning("gold.cme.voi.backfill_error", day=d.isoformat())
            continue
        try:
            df = parse_daily_volume(body, now=now)
            db.upsert(store, "gold_cme_daily_voi", df)
            done += 1
        except Exception as exc:  # noqa: BLE001
            errors.append({"date": d.isoformat(), "error": str(exc)[:160]})
        if progress:
            progress(i + 1, len(days))
    if done:
        recompute_oi_change(store)
    return {"files": done, "skipped_existing": len(have), "missing": missing[:50], "missing_count": len(missing),
            "errors": errors[:20], "remaining": max(0, len(days) - done - len(missing) - len(errors))}


# ── C2 EFRP ─────────────────────────────────────────────────────────────────────────────────────────

def parse_efrp(csv_text: str, *, now: datetime | None = None, keep: Callable[[str], bool] | None = None) -> pd.DataFrame:
    now = now or utcnow()
    keep = keep or (lambda desc: "GOLD" in desc.upper())
    counters: dict[tuple[Any, ...], int] = {}
    rows = []
    for rec in csv.DictReader(io.StringIO(csv_text)):
        desc = (rec.get("Product Long Desc") or "").strip()
        if not keep(desc):
            continue
        pdte = _mdY(rec.get("Original Process Date"))
        if pdte is None:
            continue
        txn = (rec.get("Transaction Type Description") or "").strip()
        exp = (rec.get("Contract Expiry (YYYY-MM)") or "").strip()
        key = (pdte, desc, txn, exp)
        counters[key] = counters.get(key, 0) + 1
        rows.append({"process_date": pdte, "product": desc, "product_line": (rec.get("Product Line") or "").strip(), "txn_type": txn,
                     "contract_expiry": exp, "fut_or_opt": (rec.get("Future/Option Indicator") or "").strip(),
                     "round_turns": _int(rec.get("Volume - Round Turns")) or 0, "row_no": counters[key], "first_seen_at": now})
    return pd.DataFrame(rows)


def ingest_efrp(store: Any, csv_text: str, *, now: datetime | None = None) -> dict[str, Any]:
    df = parse_efrp(csv_text, now=now)
    n = db.upsert(store, "gold_cme_efrp", df)
    return {"rows": n, "process_date": str(df["process_date"].iloc[0]) if n else None,
            "gold_round_turns": int(df.loc[df["product"] == "GOLD", "round_turns"].sum()) if n else 0}


def backfill_efrp(store: Any, start: date, end: date, *, fetch: Callable[[str], bytes] = ftp_fetch,
                  progress: Callable[[int, int], None] | None = None, now: datetime | None = None,
                  max_files: int | None = None) -> dict[str, Any]:
    have_df = db.query_df(store, "SELECT DISTINCT process_date FROM gold_cme_efrp")
    have = {pd.Timestamp(d).date() for d in have_df["process_date"]} if not have_df.empty else set()
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    days = [d for d in days if d.weekday() < 5 and d not in have]
    if max_files:
        days = days[:max_files]
    done = 0
    missing: list[str] = []
    errors: list[dict[str, str]] = []
    for i, d in enumerate(days):
        try:
            body = fetch(FTP_EFRP_ARCHIVE.format(yyyymmdd=d.strftime("%Y%m%d")))
            db.upsert(store, "gold_cme_efrp", parse_efrp(body.decode("utf-8", "ignore"), now=now))
            done += 1
        except Exception as exc:  # noqa: BLE001 — a missing archive day (holiday) is not a failure
            if "550" in str(exc):
                missing.append(d.isoformat())
            else:
                errors.append({"date": d.isoformat(), "error": str(exc)[:160]})
        if progress:
            progress(i + 1, len(days))
    return {"files": done, "missing_count": len(missing), "errors": errors[:20]}


# ── C3 product calendar ─────────────────────────────────────────────────────────────────────────────

_CAL_FIELDS = {"first_trade": "FTD", "last_trade": "LTD", "ltd_end_time": "LTD_END_TIME", "settle_date": "SD", "first_intent": "FID",
               "last_intent": "LID", "first_notice": "FND", "last_notice": "LND", "first_delivery": "FDD", "last_delivery": "LDD"}


def parse_product_calendar(xml_source: Any, *, now: datetime | None = None, codes: frozenset[str] = GOLD_SILVER_CODES,
                           types: Iterable[str] = ("FUT", "OOF")) -> pd.DataFrame:
    """Stream-parse the 38 MB calendar; keep gold/silver futures and options. ``xml_source`` is a path or a file-like."""
    now = now or utcnow()
    as_of: date | None = None
    rows: list[dict[str, Any]] = []
    types = set(types)
    for event, elem in ET.iterparse(xml_source, events=("end",)):
        if elem.tag == "DATE_CREATED":
            as_of = _mdY((elem.text or "").split(" ")[0])
        elif elem.tag == "PRODUCT":
            code = (elem.findtext("Commodity_Code") or "").strip()
            ptype = (elem.findtext("PRODUCT_TYPE_CODE") or "").strip()
            if code in codes and ptype in types:
                exch = (elem.findtext("Exchange") or "").strip()
                for c in elem.findall("CONTRACT"):
                    mmy = (c.findtext("Contract_Product_Code") or "").strip()
                    ccode = (c.findtext("Contract_Code") or "").strip()
                    # options: several products share a Contract_Product_Code (weekly Mon/Tue/Wed/Fri), so the option
                    # root (Contract_Code minus month letter + year digit) keeps the (as_of, exchange, symbol, mmy) key unique
                    sym = code if ptype == "FUT" else f"{code}:{ptype}:{ccode[:-2] if len(ccode) > 2 else ccode}"
                    rec: dict[str, Any] = {"as_of": as_of, "exchange": exch, "symbol": sym, "mmy": mmy, "first_seen_at": now}
                    for col, tag in _CAL_FIELDS.items():
                        txt = c.findtext(tag)
                        rec[col] = txt.strip() if col == "ltd_end_time" and txt else _mdY(txt)
                    rec["contract_code"] = ccode
                    rows.append(rec)
            elem.clear()
    df = pd.DataFrame(rows)
    if not df.empty:
        df["as_of"] = df["as_of"].fillna(now.date())
        df = df.drop_duplicates(["as_of", "exchange", "symbol", "mmy"], keep="first")
    return df


def ingest_product_calendar(store: Any, xml_source: Any, *, now: datetime | None = None) -> dict[str, Any]:
    df = parse_product_calendar(xml_source, now=now)
    n = db.upsert(store, "gold_cme_calendar", df.drop(columns=["contract_code"], errors="ignore"))
    return {"rows": n, "as_of": str(df["as_of"].iloc[0]) if n else None}


# ── C4 product reference (specs, margins) ───────────────────────────────────────────────────────────

def _iso(v: Any) -> date | None:
    try:
        return date.fromisoformat(str(v).strip()) if v not in (None, "") else None
    except ValueError:
        return None


def _flt(v: Any) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def parse_prf(zip_or_csv: bytes, *, now: datetime | None = None, codes: frozenset[str] = GOLD_SILVER_CODES) -> pd.DataFrame:
    now = now or utcnow()
    text: str
    if zip_or_csv[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(zip_or_csv)) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
            text = z.read(name).decode("utf-8", "ignore")
    else:
        text = zip_or_csv.decode("utf-8", "ignore")
    rows = []
    for rec in csv.DictReader(io.StringIO(text)):
        sym = (rec.get("Sym") or "").strip()
        if sym not in codes or (rec.get("SecTyp") or "").strip() != "FUT":
            continue
        rows.append({"biz_date": _iso(rec.get("BizDt")), "symbol": sym, "mmy": (rec.get("MMY") or "").strip(),
                     "description": rec.get("Desc"), "sec_type": rec.get("SecTyp"), "uom": rec.get("UOM"), "uom_qty": _flt(rec.get("UOMQty")),
                     "multiplier": _flt(rec.get("Mult")), "min_px_incr": _flt(rec.get("MinPxIncr")), "tick_incr_reg": _flt(rec.get("TickIncrReg")),
                     "settl_method": rec.get("SettlMeth"), "init_margin": _flt(rec.get("InitMargin")),
                     "maint_margin_field": _flt(rec.get("MaintMargin")), "mat_date": _iso(rec.get("MatDt")),
                     "first_trd": _iso(rec.get("FirstTrdDt")), "last_trd": _iso(rec.get("LastTrdDt")),
                     "first_notice": _iso(rec.get("FirstNoticeDt")), "last_notice": _iso(rec.get("LastNoticeDt")),
                     "last_efp": _iso(rec.get("LastEFPDt")), "elig_block": (rec.get("EligForBlock") == "Y"),
                     "elig_efp": (rec.get("EligForEFP") == "Y"), "elig_efr": (rec.get("EligForEFR") == "Y"), "first_seen_at": now})
    return pd.DataFrame(rows)


def ingest_prf(store: Any, body: bytes, *, now: datetime | None = None, ref_prices: dict[str, float] | None = None) -> dict[str, Any]:
    df = parse_prf(body, now=now)
    n = db.upsert(store, "gold_cme_prf", df)
    margins = []
    for r in df.itertuples(index=False):
        if r.init_margin is None or r.mat_date is None:
            continue
        ref = (ref_prices or {}).get(r.symbol)
        notional = ref * (r.uom_qty or 1) if ref else None
        margins.append({"trade_date": r.biz_date, "exchange": EXCHANGE, "symbol": r.symbol, "expiry": r.mat_date, "source": "cme_prf",
                        "margin_ccy": r.init_margin, "margin_pct": (100.0 * r.init_margin / notional) if notional else None,
                        "ref_price": ref, "first_seen_at": r.first_seen_at})
    m = db.upsert(store, "gold_margins", pd.DataFrame(margins))
    return {"rows": n, "margins": m, "biz_date": str(df["biz_date"].iloc[0]) if n else None}

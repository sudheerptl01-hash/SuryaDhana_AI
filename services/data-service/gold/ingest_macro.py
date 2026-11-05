"""Macro drivers (SOURCES.md G1–G26): Treasury real/nominal curves, FRED ``fredgraph.csv`` (keyless, plain UA),
Forex Factory calendar (IST), GPR daily/monthly, World Bank Pink Sheet, Atlanta Fed Market Probability Tracker.

All single-value series land in ``gold_series`` through ``pit.upsert_series`` (vintage-aware). The Treasury file
for a day is the same-day source; FRED is the archive one business day later — the T2 test asserts same-date
equality between the two.
"""
from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from gold import db, pit
from gold.catalog_seed import FRED_DAILY, FRED_MONTHLY, FRED_WEEKLY, TREASURY_NOM, TREASURY_REAL
from gold.db import utcnow
from shared.logging import get_logger

logger = get_logger(__name__)

IST = ZoneInfo("Asia/Kolkata")
TREASURY_URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{year}/all"
                "?type={kind}&field_tdr_date_value={year}")
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={id}"
FRED_TIMEOUT_S = 8.0          # a healthy FRED answers in < 1 s; 20 s × 18 series burned 378 s per run (R-DATA §6)
FRED_BREAKER_AFTER = 3        # consecutive failures that end the run's FRED fetching
FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
GPR_DAILY_URL = "https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls"
GPR_MONTHLY_URL = "https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xls"
WORLDBANK_URL = ("https://thedocs.worldbank.org/en/doc/5d903e848db1d1b83e0ec8f744e55570-0350012021/related/"
                 "CMO-Historical-Data-Monthly.xlsx")
ATLANTA_URL = ("https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents/research-and-data/data/"
               "market-probability-tracker/mpt_histdata.xlsx")


# ── Treasury (G1, G2) ───────────────────────────────────────────────────────────────────────────────

def parse_treasury_csv(text: str, mapping: dict[str, str], *, now: datetime | None = None) -> pd.DataFrame:
    """``Date, 5 YR, 7 YR, …`` (MM/DD/YYYY or ISO) → gold_series rows (one per series in ``mapping``)."""
    frames = []
    rdr = list(csv.DictReader(io.StringIO(text)))
    for sid, col in mapping.items():
        pts = []
        for rec in rdr:
            raw = (rec.get("Date") or "").strip()
            try:
                d = db.strptime(raw, "%m/%d/%Y").date() if "/" in raw else date.fromisoformat(raw)
            except ValueError:
                continue
            v = rec.get(col)
            if v in (None, "", "N/A"):
                continue
            pts.append((d, float(v)))
        frames.append(pit.series_frame(sid, pts, freq="D", source="treasury_csv", release_kind="treasury", now=now))
    return pd.concat([f for f in frames if not f.empty], ignore_index=True) if frames else pd.DataFrame()


def ingest_treasury(store: Any, real_text: str | None, nominal_text: str | None, *, now: datetime | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if real_text:
        out["real"] = pit.upsert_series(store, parse_treasury_csv(real_text, TREASURY_REAL, now=now), now=now)
    if nominal_text:
        out["nominal"] = pit.upsert_series(store, parse_treasury_csv(nominal_text, TREASURY_NOM, now=now), now=now)
    return out


def fetch_treasury(store: Any, http: Any, *, year: int | None = None, now: datetime | None = None) -> dict[str, Any]:
    year = year or (now or utcnow()).year
    real = http.get(TREASURY_URL.format(year=year, kind="daily_treasury_real_yield_curve"))
    nom = http.get(TREASURY_URL.format(year=year, kind="daily_treasury_yield_curve"))
    return ingest_treasury(store, real.text if real.status_code == 200 else None, nom.text if nom.status_code == 200 else None, now=now)


# ── FRED fredgraph.csv (G3–G12) ─────────────────────────────────────────────────────────────────────

def parse_fredgraph(text: str, series_id: str, *, freq: str, release_kind: str = "fred_daily", now: datetime | None = None) -> pd.DataFrame:
    """``observation_date,<ID>`` (or ``DATE,<ID>``); '.' marks a missing observation."""
    pts = []
    for rec in csv.DictReader(io.StringIO(text)):
        keys = list(rec.keys())
        if len(keys) < 2:
            continue
        raw_d, raw_v = rec[keys[0]], rec[keys[1]]
        if raw_v in (None, "", "."):
            continue
        try:
            pts.append((date.fromisoformat(raw_d.strip()), float(raw_v)))
        except ValueError:
            continue
    return pit.series_frame(series_id, pts, freq=freq, source="fred_csv", release_kind=release_kind if freq == "D" else "fetch", now=now)


def fred_catalog(group: str) -> dict[str, tuple[str, str]]:
    """series_id → (fred id, freq) for ``daily`` | ``weekly`` | ``monthly``."""
    if group == "daily":
        return {sid: (v[0], "D") for sid, v in FRED_DAILY.items()}
    if group == "weekly":
        return {sid: (v[0], "W") for sid, v in FRED_WEEKLY.items()}
    return {sid: (v[0], "M") for sid, v in FRED_MONTHLY.items()}


def fetch_fred(store: Any, http: Any, group: str, *, now: datetime | None = None, since: date | None = None) -> dict[str, Any]:
    """One keyless CSV per series; a failing series never stops the group."""
    out: dict[str, Any] = {}
    consecutive_failures = 0
    for sid, (fid, freq) in fred_catalog(group).items():
        if consecutive_failures >= FRED_BREAKER_AFTER:
            out[sid] = {"status": "skipped", "error": "breaker open: FRED unreachable this run"}   # never 378 s of timeouts again
            continue
        try:
            resp = http.get(FRED_URL.format(id=fid), timeout_s=FRED_TIMEOUT_S)
            if resp.status_code != 200:
                out[sid] = {"status": f"http_{resp.status_code}"}
                consecutive_failures += 1
                continue
            consecutive_failures = 0
            df = parse_fredgraph(resp.text, sid, freq=freq, now=now)
            if since is not None and not df.empty:
                df = df[df["report_date"] >= since]
            out[sid] = {"status": "ok", **pit.upsert_series(store, df, now=now)}
        except Exception as exc:  # noqa: BLE001 — isolation per series
            consecutive_failures += 1
            out[sid] = {"status": "error", "error": str(exc)[:160]}
            logger.warning("gold.fred.series_failed", series=sid)
    return out


# ── Forex Factory calendar (G19) ────────────────────────────────────────────────────────────────────

_FF_KINDS: tuple[tuple[str, str], ...] = (
    (r"\bCPI\b", "US_CPI"), (r"Non-Farm|Nonfarm|NFP", "US_NFP"), (r"\bPCE\b", "US_PCE"), (r"\bGDP\b", "US_GDP"),
    (r"Federal Funds Rate|FOMC", "FOMC"), (r"Unemployment Claims", "US_CLAIMS"), (r"ISM", "US_ISM"), (r"Retail Sales", "US_RETAIL"),
)


def _ff_kind(title: str, country: str) -> str:
    if country == "USD":
        for pat, kind in _FF_KINDS:
            if re.search(pat, title, re.IGNORECASE):
                return kind
        return "US_DATA"
    return f"{country}_DATA"


def mcx_in_session(ts_ist: datetime) -> bool:
    """Inside the MCX continuous session (09:00 → 23:30/23:55 IST on weekdays); holidays are not modelled here."""
    if ts_ist.weekday() >= 5:
        return False
    try:
        from shared.mcx_specs import evening_close
        close = evening_close(ts_ist.date())
    except Exception:  # noqa: BLE001
        close = time(23, 30)
    return time(9, 0) <= ts_ist.time() <= close


def parse_ff_calendar(text: str, *, now: datetime | None = None, countries: Iterable[str] = ("USD",)) -> pd.DataFrame:
    now = now or utcnow()
    data = json.loads(text)
    keep = set(countries)
    rows = []
    for ev in data:
        ctry = ev.get("country") or ""
        if keep and ctry not in keep:
            continue
        try:
            ts = datetime.fromisoformat(ev["date"])
        except (KeyError, ValueError):
            continue
        ts_ist = ts.astimezone(IST)
        rows.append({"event_date": ts_ist.date(), "time_ist": ts_ist.strftime("%H:%M"), "kind": _ff_kind(ev.get("title", ""), ctry),
                     "name": ev.get("title", "")[:120], "detail": ev.get("impact"), "country": ctry, "impact": ev.get("impact"),
                     "forecast": (ev.get("forecast") or None), "previous": (ev.get("previous") or None), "actual": (ev.get("actual") or None),
                     "in_session": mcx_in_session(ts_ist), "source": "forexfactory_thisweek", "first_seen_at": now})
    df = pd.DataFrame(rows)
    return df.drop_duplicates(["event_date", "kind", "name"], keep="last") if not df.empty else df


def ingest_ff_calendar(store: Any, text: str, *, now: datetime | None = None) -> dict[str, Any]:
    df = parse_ff_calendar(text, now=now)
    return {"rows": db.upsert(store, "gold_events", df)}


# ── GPR (G23, G24) ──────────────────────────────────────────────────────────────────────────────────

def _xls_rows(body: bytes) -> list[list[Any]]:
    import xlrd

    wb = xlrd.open_workbook(file_contents=body)
    sh = wb.sheet_by_index(0)
    return [sh.row_values(i) for i in range(sh.nrows)]


def parse_gpr(body_or_text: bytes | str, *, daily: bool, now: datetime | None = None) -> pd.DataFrame:
    """Daily file: ``DAY`` (yyyymmdd) + ``GPRD``; monthly: ``month`` + ``GPR``. Accepts the .xls or a CSV export."""
    if isinstance(body_or_text, bytes) and body_or_text[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        rows = _xls_rows(body_or_text)
        header = [str(h).strip() for h in rows[0]]
        records = [dict(zip(header, r)) for r in rows[1:]]
    else:
        text = body_or_text.decode("utf-8", "ignore") if isinstance(body_or_text, bytes) else body_or_text
        records = list(csv.DictReader(io.StringIO(text)))
    pts = []
    for rec in records:
        if daily:
            raw, val = rec.get("DAY"), rec.get("GPRD")
            try:
                d = db.strptime(str(int(float(str(raw)))), "%Y%m%d").date()
            except (TypeError, ValueError):
                continue
        else:
            raw, val = rec.get("month"), rec.get("GPR")
            try:
                if isinstance(raw, (int, float)):                      # xls serial date
                    ts = pd.Timestamp("1899-12-30") + pd.Timedelta(days=float(raw))
                else:
                    ts = pd.Timestamp(str(raw).strip())
                d = (ts + pd.offsets.MonthEnd(0)).date()
            except (TypeError, ValueError):
                continue
        if val in (None, "", "NA"):
            continue
        try:
            pts.append((d, float(str(val))))
        except (TypeError, ValueError):
            continue
    return pit.series_frame("GPR_DAILY" if daily else "GPR_MONTHLY", pts, freq="D" if daily else "M", source="iacoviello_xls", now=now)


# ── World Bank Pink Sheet (G26) ─────────────────────────────────────────────────────────────────────

def parse_worldbank_monthly(body_or_text: bytes | str, *, now: datetime | None = None) -> pd.DataFrame:
    """Sheet 'Monthly Prices': a header row with 'Gold', rows ``1960M01`` …; or the CSV export ``date,gold``."""
    pts = []
    if isinstance(body_or_text, bytes) and body_or_text[:2] == b"PK":
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(body_or_text), read_only=True, data_only=True)
        ws = wb["Monthly Prices"] if "Monthly Prices" in wb.sheetnames else wb[wb.sheetnames[0]]
        ws.reset_dimensions()
        gold_col = None
        for row in ws.iter_rows(values_only=True):
            if gold_col is None:
                for i, c in enumerate(row):
                    if isinstance(c, str) and c.strip().lower() == "gold":
                        gold_col = i
                continue
            m = re.match(r"^(\d{4})M(\d{2})$", str(row[0] or "").strip())
            if not m or gold_col is None or row[gold_col] in (None, "", "…"):
                continue
            d = (pd.Timestamp(int(m.group(1)), int(m.group(2)), 1) + pd.offsets.MonthEnd(0)).date()
            try:
                pts.append((d, float(row[gold_col])))
            except (TypeError, ValueError):
                continue
        wb.close()
    else:
        text = body_or_text.decode("utf-8", "ignore") if isinstance(body_or_text, bytes) else body_or_text
        for rec in csv.DictReader(io.StringIO(text)):
            try:
                pts.append((date.fromisoformat(rec["date"]), float(rec["gold"])))
            except (KeyError, ValueError):
                continue
    return pit.series_frame("WB_GOLD_MONTHLY_AVG", pts, freq="M", source="worldbank_cmo", now=now)


# ── Atlanta Fed Market Probability Tracker (G16) ────────────────────────────────────────────────────

def parse_atlanta_fed(xlsx_bytes: bytes, *, since: date | None = None, now: datetime | None = None) -> pd.DataFrame:
    """Long format DATA sheet (date, reference_start, target_range, field, value) → one row per (as_of, meeting).

    The file publishes the 25th / 75th percentiles (no 10/90): they are stored in ``p10_bp`` / ``p90_bp`` — see the
    contract note in the build report; ``rate_*`` are in bp; probabilities in %.
    """
    import openpyxl

    now = now or utcnow()
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
    ws = wb["DATA"]
    ws.reset_dimensions()
    acc: dict[tuple[date, date], dict[str, Any]] = {}
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0 or not row or row[0] is None:
            continue
        try:
            as_of = date.fromisoformat(str(row[0])[:10])
        except ValueError:
            continue
        if since and as_of < since:
            continue
        meeting = row[1].date() if isinstance(row[1], datetime) else pd.Timestamp(row[1]).date()
        field, val = str(row[3]).strip(), row[4]
        try:
            v = float(str(val).strip())
        except (TypeError, ValueError):
            continue
        rec = acc.setdefault((as_of, meeting), {"as_of": as_of, "meeting": meeting, "source": "atlanta_fed_mpt", "first_seen_at": now})
        rng = re.findall(r"(\d+)bps", str(row[2] or ""))
        if len(rng) == 2:
            rec["target_lo_bp"], rec["target_hi_bp"] = int(rng[0]), int(rng[1])
        if field == "Prob: cut":
            rec["prob_cut"] = v
        elif field == "Prob: hike":
            rec["prob_hike"] = v
        elif field == "Rate: mean":
            rec["rate_mean_bp"] = _to_bp(v)
        elif field == "Rate: mode":
            rec["rate_mode_bp"] = _to_bp(v)
        elif field == "Rate: 25th percentile":
            rec["p10_bp"] = _to_bp(v)
        elif field == "Rate: 75th percentile":
            rec["p90_bp"] = _to_bp(v)
    wb.close()
    df = pd.DataFrame(list(acc.values()))
    if not df.empty:
        for c in ("prob_cut", "prob_hike"):
            if c not in df.columns:
                df[c] = None
        df["prob_hold"] = (100.0 - df["prob_cut"].fillna(0).astype(float) - df["prob_hike"].fillna(0).astype(float)).round(2)
    return df


def _to_bp(v: float) -> float:
    """The file quotes rates in percent (4.17 = 4.17 %); the table stores basis points. Values ≥ 50 are already bp."""
    return round(v * 100.0, 2) if abs(v) < 50 else v


def ingest_atlanta_fed(store: Any, xlsx_bytes: bytes, *, since: date | None = None, now: datetime | None = None) -> dict[str, Any]:
    df = parse_atlanta_fed(xlsx_bytes, since=since, now=now)
    return {"rows": db.upsert(store, "gold_fed_path", df), "as_of": str(df["as_of"].max()) if not df.empty else None}


def last_as_of(store: Any) -> date | None:
    v = db.scalar(store, "SELECT MAX(as_of) FROM gold_fed_path")
    return pd.Timestamp(v).date() if v is not None else None


def default_since(store: Any, days: int = 10) -> date | None:
    last = last_as_of(store)
    return (last - timedelta(days=days)) if last else None

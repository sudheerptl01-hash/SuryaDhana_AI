"""
FII/FPI and DII cash-market flows from NSE (`/api/fiidiiTradeReact`: NSE + BSE + MSEI combined, provisional,
₹ crore). The API serves only the latest trading day, so the terminal collects it every evening; history in
`nse_fii_dii_cash` starts on 9 Oct 2026.

No archive exists (verified 6 Nov 2026, review M09): the API ignores a date parameter and NSE's "historical" report
page (/all-reports/historical-equities-fii-fpi-dii-trading-activity) only links back to the latest-day report. A
session the evening job missed cannot be re-fetched from NSE. So the sums never skip silently: `summarize` counts
sessions against the NSE session calendar (the dates in `nse_bhavcopy`) and reports "n of m sessions" plus the
missing dates; `backfill` stores the latest day when it fills a gap, imports an owner-saved NSE CSV for a gap
(validated), and lists what stays missing with the reason.
"""
from __future__ import annotations

import csv
import io
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Callable, Iterable, Optional

import httpx
import pandas as pd

PAGE = "https://www.nseindia.com/reports/fii-dii"
API = "https://www.nseindia.com/api/fiidiiTradeReact"


def _num(v: Any) -> Optional[float]:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse(records: list[dict]) -> pd.DataFrame:
    """[{category, date '09-Oct-2026', buyValue, sellValue, netValue}] → date, category (FII | DII), buy/sell/net ₹ cr."""
    rows = []
    for r in records or []:
        raw = str(r.get("category", "")).upper()
        cat = "FII" if raw.startswith("FII") or "FPI" in raw else "DII" if raw.startswith("DII") else None
        try:
            day = datetime.strptime(str(r.get("date")), "%d-%b-%Y").date()
        except ValueError:
            continue
        if cat is None:
            continue
        rows.append({"date": day, "category": cat, "buy_cr": _num(r.get("buyValue")),
                     "sell_cr": _num(r.get("sellValue")), "net_cr": _num(r.get("netValue"))})
    return pd.DataFrame(rows, columns=["date", "category", "buy_cr", "sell_cr", "net_cr"])


def fetch(headers: dict[str, str]) -> pd.DataFrame:
    with httpx.Client(headers={**headers, "Accept": "application/json,*/*", "Referer": PAGE},
                      timeout=20, follow_redirects=True) as client:
        client.get(PAGE)                      # cookie warm-up
        time.sleep(0.5)
        r = client.get(API)
        r.raise_for_status()
        return parse(r.json())


NO_ARCHIVE_NOTE = ("NSE serves only the latest session's provisional FII/DII figures (no archive: the API ignores a "
                   "date and the historical-reports page links back to the latest day, verified 6 Nov 2026), so a "
                   "session the evening job missed stays missing")
TOLERANCE_CR = 0.05                       # buy − sell must equal net within this (₹ cr) for an imported row


def session_calendar(con: Any, since: str) -> list[str]:
    """NSE sessions on or after `since` (ISO): the dates that have an NSE bhavcopy (every session has one, holidays
    and weekends none). `con` is a DuckDB connection (a store reader)."""
    rows = con.execute("SELECT DISTINCT date FROM nse_bhavcopy WHERE date >= ?::DATE ORDER BY date", [since]).fetchall()
    return [str(r[0])[:10] for r in rows]


def _label(present: int, expected: int, known: bool) -> str:
    if not known:
        return f"{present} session{'s' if present != 1 else ''} collected (session calendar unknown)"
    return f"{present} of {expected} session{'s' if expected != 1 else ''}"


def summarize(rows: list[dict], sessions: Optional[Iterable[str]] = None) -> dict[str, Any]:
    """Latest day per category plus 5-session and month-to-date sums, counted against the NSE session calendar.

    `sessions`: NSE session dates (ISO) covering the collected range (`session_calendar`). The 5-session window is
    the last five *sessions* ending on the latest collected day, and month to date is every session of that month
    up to it; a session without a row is listed in `missing_5d` / `missing_mtd` and the labels read "3 of 5
    sessions", never a silent skip. Without a calendar the old behaviour stays (the last five collected days) and
    the labels say the calendar is unknown."""
    empty = {"latest_date": None, "latest": {}, "sum_5d": {}, "mtd": {}, "sessions": 0, "sessions_5d": 0, "sessions_mtd": 0,
             "expected_5d": 0, "expected_mtd": 0, "missing_5d": [], "missing_mtd": [], "missing": [],
             "complete_5d": False, "complete_mtd": False, "label_5d": None, "label_mtd": None,
             "calendar": None, "latest_session": None, "latest_pending": False, "note": None}
    if not rows:
        return empty
    df = pd.DataFrame(rows)
    df["date"] = df["date"].astype(str).str[:10]
    present = sorted(df["date"].unique())
    last = present[-1]
    month = last[:7]
    known = sessions is not None
    cal_all = sorted({str(d)[:10] for d in (sessions or [])} | set(present)) if known else present
    cal = [d for d in cal_all if d <= last]
    window = cal[-5:]
    month_sessions = [d for d in cal if d.startswith(month)]
    have = set(present)
    by = lambda d: {c: round(float(v), 2) for c, v in d.groupby("category")["net_cr"].sum().items()}  # noqa: E731
    in5 = [d for d in window if d in have]
    inm = [d for d in month_sessions if d in have]
    miss5 = [d for d in window if d not in have]
    missm = [d for d in month_sessions if d not in have]
    gaps = [d for d in cal if present[0] <= d <= last and d not in have]
    newer = [d for d in cal_all if d > last]
    return {"latest_date": last, "latest": by(df[df["date"] == last]), "sum_5d": by(df[df["date"].isin(in5)]),
            "mtd": by(df[df["date"].isin(inm)]), "sessions": len(present),
            "sessions_5d": len(in5), "sessions_mtd": len(inm),
            "expected_5d": len(window), "expected_mtd": len(month_sessions),
            "missing_5d": miss5, "missing_mtd": missm, "missing": gaps,
            "complete_5d": known and not miss5, "complete_mtd": known and not missm,
            "window_5d": [window[0], window[-1]] if window else None,
            "label_5d": _label(len(in5), len(window), known), "label_mtd": _label(len(inm), len(month_sessions), known),
            "calendar": "nse_bhavcopy" if known else None,
            "latest_session": cal_all[-1] if cal_all else last, "latest_pending": bool(newer),
            "note": NO_ARCHIVE_NOTE if gaps else None}


# ── backfill (review M09): a job the PM runs; data-service POST /jobs/fii-dii-backfill ─────────────────────────────

def parse_nse_csv(text: str) -> pd.DataFrame:
    """An NSE 'FII/FPI & DII trading activity' CSV download (the report page's own export, saved by the owner on the
    day: CATEGORY, DATE, BUY VALUE, SELL VALUE, NET VALUE) → rows as `parse` returns them. Header matching is
    case- and space-insensitive; anything else raises ValueError."""
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    norm = {k: "".join(ch for ch in re.sub(r"\(.*?\)", "", k or "").lower() if ch.isalnum()) for k in reader.fieldnames or []}
    want = {"category": "category", "date": "date", "buyvalue": "buyValue", "sellvalue": "sellValue", "netvalue": "netValue"}
    if not set(want) <= set(norm.values()):
        raise ValueError(f"not an NSE FII/DII CSV (columns {reader.fieldnames})")
    recs = [{want[norm[k]]: v for k, v in r.items() if norm.get(k) in want} for r in reader]
    return parse(recs)


def validate_rows(df: pd.DataFrame, sessions: Iterable[str]) -> list[str]:
    """Problems that stop an import: a date that is not an NSE session, a session without both FII and DII, or
    buy − sell ≠ net."""
    cal = {str(d)[:10] for d in sessions}
    bad: list[str] = []
    for day, g in df.groupby(df["date"].astype(str)):
        if day not in cal:
            bad.append(f"{day}: not an NSE session")
        if set(g["category"]) != {"FII", "DII"}:
            bad.append(f"{day}: needs one FII and one DII row, got {sorted(g['category'])}")
        for r in g.itertuples():
            if None in (r.buy_cr, r.sell_cr, r.net_cr) or abs((r.buy_cr - r.sell_cr) - r.net_cr) > TOLERANCE_CR:
                bad.append(f"{day} {r.category}: buy − sell ≠ net")
    return bad


def backfill(stored_dates: Iterable[str], sessions: Iterable[str], upsert: Callable[[pd.DataFrame], int],
             fetch_latest: Optional[Callable[[], pd.DataFrame]] = None, csv_text: Optional[str] = None,
             since: Optional[str] = None) -> dict[str, Any]:
    """Fill gaps in `nse_fii_dii_cash` where a source exists, and say which gaps stay.

    - `fetch_latest` (NSE's latest-day API): stored only when its day is an NSE session (a refresh at any hour is
      harmless: the upsert keys on date and category).
    - `csv_text`: an owner-saved NSE CSV; imported only for sessions that are missing and only if `validate_rows`
      finds nothing wrong (a bad file imports nothing).
    Returns {filled, imported, still_missing, errors, note}."""
    cal = sorted({str(d)[:10] for d in sessions})
    have = {str(d)[:10] for d in stored_dates}
    start = since or (min(have) if have else (cal[0] if cal else None))
    gaps = [d for d in cal if start and d >= start and d not in have]
    out: dict[str, Any] = {"gaps_before": list(gaps), "filled": [], "imported": [], "errors": [], "still_missing": []}
    if fetch_latest is not None:
        try:
            df = fetch_latest()
            day = str(df["date"].max())[:10] if not df.empty else None
            if day and day in set(cal) | {datetime.now(ZoneInfo('Asia/Kolkata')).date().isoformat()}:
                upsert(df)
                if day in gaps:
                    out["filled"].append(day)
                have.add(day)
        except Exception as exc:  # noqa: BLE001 — the report must still list the gaps
            out["errors"].append(f"latest: {str(exc)[:160]}")
    if csv_text:
        try:
            df = parse_nse_csv(csv_text)
            df = df[df["date"].astype(str).isin(set(gaps) - have)]
            problems = validate_rows(df, cal)
            if problems:
                out["errors"] += problems[:20]
            elif not df.empty:
                upsert(df)
                out["imported"] = sorted({str(d) for d in df["date"].astype(str)})
                have |= set(out["imported"])
        except ValueError as exc:
            out["errors"].append(f"csv: {exc}")
    out["still_missing"] = [d for d in gaps if d not in have]
    out["note"] = NO_ARCHIVE_NOTE if out["still_missing"] else None
    return out

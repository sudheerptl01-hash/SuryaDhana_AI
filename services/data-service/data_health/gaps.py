"""Explicit gap rows (Wave 0 0.9): a session-bound capture that did not happen (pre-open book, intraday internals,
FII/DII cash, gold open, chain snapshots) is written as ``{dataset, date, reason, unrecoverable}`` so MOV / WRAP / BRF / the
DATA view say "no intraday data for 2–4 Nov" instead of showing an older day. A gap row is point-in-time (``first_seen_at``)
and never overwritten by a later success: ``clear_if_recovered`` removes it only when the capture actually exists.
"""
from __future__ import annotations

import re

from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from data_health import calendar, db
from data_health.schema import CASTS, COLUMNS

# session-bound datasets and how their presence for a day is detected (archive folder file prefix or a table)
SESSION_CAPTURES: dict[str, dict[str, Any]] = {
    "archive:preopen": {"kind": "archive", "folder": "preopen", "unrecoverable": True, "pages": "PRE"},
    "archive:internals": {"kind": "archive", "folder": "internals", "unrecoverable": True, "pages": "MOV,WRAP"},
    "nse_fii_dii_cash": {"kind": "table", "table": "nse_fii_dii_cash", "column": "date", "unrecoverable": True, "pages": "BRF,WRAP,MKT"},
    "gold_preopen_log": {"kind": "table", "table": "gold_preopen_log", "column": "day", "unrecoverable": True, "pages": "GOLD"},
    "archive:chain": {"kind": "archive", "folder": "ticks/chain", "unrecoverable": True, "pages": "OMON"},
}


def write_gaps(store: Any, dataset: str, days: Iterable[date], reason: str, *, unrecoverable: bool = True,
               source: str = "catch-up", now: datetime | None = None) -> int:
    rows = [{"dataset": dataset, "date": d, "reason": reason, "unrecoverable": unrecoverable, "source": source,
             "first_seen_at": now or db.utcnow()} for d in days]
    if not rows:
        return 0
    have = db.query_df(store, "SELECT dataset, date FROM data_gaps WHERE dataset = ?", [dataset])
    had = {(str(r.dataset), db.to_date(r.date)) for r in have.itertuples(index=False)}
    new = [r for r in rows if (r["dataset"], r["date"]) not in had]        # point-in-time: never overwrite the first sighting
    return db.upsert(store, "data_gaps", pd.DataFrame(new), COLUMNS["data_gaps"], CASTS["data_gaps"]) if new else 0


_DAY_TOKENS = re.compile(r"(?<!\d)(\d{4})-?(\d{2})-?(\d{2})(?!\d)")


def _day_from_name(name: str) -> date | None:
    """The session date in an archive file name: an ISO prefix ('2026-10-09_ALL.json') or a YYYYMMDD token anywhere
    ('market-20261025.duckdb', '20260925.csv'); impossible dates are ignored (5 Nov fix)."""
    for m in _DAY_TOKENS.finditer(name):
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        if 2000 <= d.year <= 2100:
            return d
    return None


def archive_days(root: Path, folder: str) -> set[date]:
    """Dates present in an archive folder: file names directly inside it and one level of sub-folders (surveillance keeps
    ban/ bands/ reg1/)."""
    d = root / folder
    if not d.exists():
        return set()
    out: set[date] = set()
    for p in d.iterdir():
        day = _day_from_name(p.name)
        if day is not None:
            out.add(day)
        elif p.is_dir():
            for q in p.iterdir():
                dq = _day_from_name(q.name)
                if dq is not None:
                    out.add(dq)
    return out


def table_days(store: Any, table: str, column: str, start: date, end: date) -> set[date]:
    if not db.table_exists(store, table):
        return set()
    df = db.query_df(store, f"SELECT DISTINCT {column} AS d FROM {table} WHERE {column} >= ? AND {column} <= ?", [start, end])
    return {x for x in (db.to_date(v) for v in df["d"]) if x is not None}


def detect_session_gaps(store: Any, archive_root: Path, start: date, end: date, *, holidays: Iterable[date] = (),
                        extra_sessions: Iterable[date] = (), reason: str = "stack down (no capture)", now: datetime | None = None,
                        datasets: Iterable[str] | None = None) -> dict[str, list[str]]:
    """For every session in [start, end] and every session-bound capture, write a gap row when nothing was captured.
    ``end`` must be a completed session (the caller passes ``last_completed_session``)."""
    hol, extra = set(holidays), set(extra_sessions)
    sessions = [d for d in pd.date_range(start, end).date if calendar.is_trading_day(d, hol, extra)]
    out: dict[str, list[str]] = {}
    for ds, spec in SESSION_CAPTURES.items():
        if datasets is not None and ds not in set(datasets):
            continue
        if spec["kind"] == "archive":
            have = archive_days(archive_root, spec["folder"])
        else:
            have = table_days(store, spec["table"], spec["column"], start, end)
        missing = [d for d in sessions if d not in have]
        if missing:
            write_gaps(store, ds, missing, reason, unrecoverable=bool(spec["unrecoverable"]), now=now)
        out[ds] = [d.isoformat() for d in missing]
    return out


def clear_if_recovered(store: Any, dataset: str, days: Iterable[date]) -> int:
    n = 0
    for d in days:
        n += max(0, int(db.scalar(store, "SELECT COUNT(*) FROM data_gaps WHERE dataset = ? AND date = ?", [dataset, d]) or 0))
        db.execute(store, "DELETE FROM data_gaps WHERE dataset = ? AND date = ?", [dataset, d])
    return n


def gaps(store: Any, *, since: date | None = None, dataset: str | None = None) -> list[dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []
    if since:
        where.append("date >= ?")
        params.append(since)
    if dataset:
        where.append("dataset = ?")
        params.append(dataset)
    sql = "SELECT dataset, date, reason, unrecoverable, source, first_seen_at FROM data_gaps"
    if where:
        sql += " WHERE " + " AND ".join(where)
    return db.records(db.query_df(store, sql + " ORDER BY date DESC, dataset", params), ("date",))

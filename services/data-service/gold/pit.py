"""Point-in-time helpers (PLAN 0.1 #4, §c.1 read pattern, docs/PROGRAMMATIC_DATA_ACCESS.md §3).

Every stored observation has ``report_date`` (the period it describes) and ``release_at`` (when it became
public, UTC). ``release_rule`` gives the publication instant for sources whose schedule is a rule (COT: the
Friday after a Tuesday; Treasury: 16:30 ET same day; …). A re-fetch that returns the same value is a no-op; a
changed value is a NEW row whose ``release_at`` is our fetch time and whose ``revision`` is bumped, so the
as-of read (``asof_series``) returns the vintage a reader had on that date, never the later revision.
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from gold import db
from gold.db import utcnow

ET = ZoneInfo("America/New_York")
IST = ZoneInfo("Asia/Kolkata")
UTC = ZoneInfo("UTC")

# ── COT release calendar (SOURCES.md B10, G-COT §3.5, G-STUDY §2.4) ────────────────────────────────────
# Rule: Tuesday positions are released Friday 15:30 ET; a federal holiday later in the report week (the Tuesday
# itself when the as-of date is a Monday, or Wed–Fri) pushes the release to the following Monday. The rule
# reproduces every holiday Monday on the CFTC's published 2026 schedule (Jan 5, Jun 22, Jul 6, Nov 16, Nov 30,
# Dec 28). On top of it the VERIFIED catch-up calendars G-STUDY applied (CFTC "Historical Special Announcements",
# press release 7864-19, the 9 Dec 2025 catch-up table) override: report_date → release date.
COT_RELEASE_OVERRIDES: dict[date, date] = {
    # 2025 lapse in appropriations: catch-up publications 19 Nov → 29 Dec 2025 (up to 51 days late)
    date(2025, 9, 30): date(2025, 11, 19), date(2025, 10, 7): date(2025, 11, 21), date(2025, 10, 14): date(2025, 11, 25),
    date(2025, 10, 21): date(2025, 12, 2), date(2025, 10, 28): date(2025, 12, 5), date(2025, 11, 4): date(2025, 12, 9),
    date(2025, 11, 10): date(2025, 12, 10), date(2025, 11, 18): date(2025, 12, 12), date(2025, 11, 25): date(2025, 12, 15),
    date(2025, 12, 2): date(2025, 12, 17), date(2025, 12, 9): date(2025, 12, 19), date(2025, 12, 16): date(2025, 12, 23),
    date(2025, 12, 23): date(2025, 12, 29),
    # Jan 2025 National Day of Mourning (Carter): released Monday 13 Jan
    date(2025, 1, 7): date(2025, 1, 13),
    # 2023 ION cyber incident: seven delayed reports (dates from the announcements page)
    date(2023, 1, 31): date(2023, 2, 24), date(2023, 2, 7): date(2023, 3, 3), date(2023, 2, 14): date(2023, 3, 8),
    date(2023, 2, 21): date(2023, 3, 10), date(2023, 2, 28): date(2023, 3, 14), date(2023, 3, 7): date(2023, 3, 16),
    date(2023, 3, 14): date(2023, 3, 21),
    # 2018-19 lapse in appropriations (press release 7864-19): first catch-up Fri 1 Feb 2019, then every Tue and Fri
    date(2018, 12, 24): date(2019, 2, 1), date(2018, 12, 31): date(2019, 2, 5), date(2019, 1, 8): date(2019, 2, 8),
    date(2019, 1, 15): date(2019, 2, 12), date(2019, 1, 22): date(2019, 2, 15), date(2019, 1, 29): date(2019, 2, 19),
    date(2019, 2, 5): date(2019, 2, 22), date(2019, 2, 12): date(2019, 2, 26), date(2019, 2, 19): date(2019, 3, 1),
    date(2019, 2, 26): date(2019, 3, 5), date(2019, 3, 5): date(2019, 3, 8),
}
# The CFTC's published 2026 schedule (G-COT data/release_calendar_2026_ist.csv): holiday Mondays, kept explicitly so a
# drift in the holiday rule can never move a published date.
COT_RELEASE_PUBLISHED: dict[date, date] = {
    date(2025, 12, 30): date(2026, 1, 5), date(2026, 6, 16): date(2026, 6, 22), date(2026, 6, 30): date(2026, 7, 6),
    date(2026, 11, 10): date(2026, 11, 16), date(2026, 11, 24): date(2026, 11, 30), date(2026, 12, 22): date(2026, 12, 28),
}
COT_RELEASE_EXCEPTIONS: dict[date, date] = {**COT_RELEASE_OVERRIDES, **COT_RELEASE_PUBLISHED}
# October 2013 shutdown: the catch-up dates could not be verified on cftc.gov (G-STUDY excluded these weeks). They are
# stamped with a deliberately LATE release (the first on-schedule Friday after the catch-up was certainly over) and
# ``release_source = 'unverified'`` so an as-of read never shows them early and a study can drop them.
COT_RELEASE_UNVERIFIED: dict[date, date] = {
    date(2013, 10, 1): date(2013, 11, 15), date(2013, 10, 8): date(2013, 11, 15),
    date(2013, 10, 15): date(2013, 11, 15), date(2013, 10, 22): date(2013, 11, 15),
}


def _observed(d: date) -> date:
    """A federal holiday falling on a Saturday is observed on the Friday, on a Sunday on the Monday."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    last = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def us_federal_holidays(year: int) -> set[date]:
    """The observed federal holidays (the CFTC's closures): New Year, MLK, Presidents, Memorial, Juneteenth (2021→),
    Independence, Labor, Columbus, Veterans, Thanksgiving, Christmas."""
    hol = {_observed(date(year, 1, 1)), _nth_weekday(year, 1, 0, 3), _nth_weekday(year, 2, 0, 3), _last_weekday(year, 5, 0),
           _observed(date(year, 7, 4)), _nth_weekday(year, 9, 0, 1), _nth_weekday(year, 10, 0, 2), _observed(date(year, 11, 11)),
           _nth_weekday(year, 11, 3, 4), _observed(date(year, 12, 25))}
    if year >= 2021:
        hol.add(_observed(date(year, 6, 19)))
    return hol


def cot_release_date(report_date: date) -> tuple[date, str]:
    """(release date, source) for a COT ``report_date``: ``published`` (CFTC 2026 schedule), ``verified`` (catch-up
    calendars), ``unverified`` (Oct 2013, stamped late on purpose) or ``rule`` (Friday, Monday after a holiday)."""
    if report_date in COT_RELEASE_PUBLISHED:
        return COT_RELEASE_PUBLISHED[report_date], "published"
    if report_date in COT_RELEASE_OVERRIDES:
        return COT_RELEASE_OVERRIDES[report_date], "verified"
    if report_date in COT_RELEASE_UNVERIFIED:
        return COT_RELEASE_UNVERIFIED[report_date], "unverified"
    days_to_friday = (4 - report_date.weekday()) % 7 or 7          # a Friday-dated report releases the next Friday
    friday = report_date + timedelta(days=days_to_friday)
    hol = us_federal_holidays(report_date.year) | us_federal_holidays(friday.year)
    if any((report_date + timedelta(days=i)) in hol for i in range(1, days_to_friday + 1)):
        return friday + timedelta(days=3), "rule"
    return friday, "rule"


def cot_release_source(report_date: date) -> str:
    """The ``release_source`` to store with a COT row: ``rule`` for published/verified/rule dates, else ``unverified``."""
    return "unverified" if cot_release_date(report_date)[1] == "unverified" else "rule"


def _to_utc_naive(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(tzinfo=None)


def _next_business_day(d: date, n: int = 1) -> date:
    out = d
    while n > 0:
        out += timedelta(days=1)
        if out.weekday() < 5:
            n -= 1
    return out


def cot_release_at(report_date: date) -> datetime:
    """15:30 ET on ``cot_release_date`` (Friday, the Monday after a federal holiday, or the verified catch-up date), UTC."""
    rel, _ = cot_release_date(report_date)
    return _to_utc_naive(datetime.combine(rel, time(15, 30), tzinfo=ET))


# kind → (day offset rule, local time, tz).  "nbd" = next US business day.
_SIMPLE_RULES: dict[str, tuple[int | str, time, ZoneInfo]] = {
    "treasury": (0, time(16, 30), ET),
    "fred_daily": ("nbd", time(16, 15), ET),
    "gld": (1, time(6, 0), IST),
    "iau": (1, time(6, 0), IST),
    "wgc_weekly": (3, time(11, 30), IST),           # Friday-dated week → Monday ≈ 11:30 IST
    "ibja_am": (0, time(13, 0), IST),
    "ibja_pm": (0, time(18, 0), IST),
    "sge_am": (0, time(10, 15), ZoneInfo("Asia/Shanghai")),
    "sge_pm": (0, time(14, 15), ZoneInfo("Asia/Shanghai")),
    "sge_daily": (0, time(16, 30), ZoneInfo("Asia/Shanghai")),
    "shfe": (0, time(16, 0), ZoneInfo("Asia/Shanghai")),
    "cme_voi": (1, time(14, 30), IST),              # T+1 ≈ 14:00–15:30 IST (confirm in week one, T13)
    "cme_efrp": (1, time(14, 30), IST),
    "mcx_master": (1, time(7, 30), IST),            # the file for session T appears ≈ 07:28 IST on T+1
    "rbi_wss": (7, time(17, 0), IST),               # data as of Friday T, published the following Friday ≈17:00
    "rbi_ref": (0, time(13, 30), IST),
    "lbma_turnover": (4, time(16, 0), ZoneInfo("Europe/London")),
    "eod_utc": (0, time(23, 59), UTC),
    "mcx_session": (1, time(7, 30), IST),           # a settlement for session T is public with T+1's master
    "zerodha": (0, time(9, 0), IST),
    "sge_benchmark": (0, time(14, 15), ZoneInfo("Asia/Shanghai")),
    "ff_calendar": (0, time(0, 0), UTC),
}


def release_rule(kind: str, report_date: date) -> datetime:
    """UTC-naive publication instant for ``kind`` on ``report_date``; ``fetch`` means now."""
    if kind == "cot":
        return cot_release_at(report_date)
    if kind == "fetch":
        return utcnow()
    offset, t, tz = _SIMPLE_RULES[kind]
    day = _next_business_day(report_date) if offset == "nbd" else report_date + timedelta(days=int(offset))
    return _to_utc_naive(datetime.combine(day, t, tzinfo=tz))


def series_frame(series_id: str, points: Iterable[tuple[Any, float | None]], *, freq: str, source: str,
                 quality: str = "official", release_kind: str = "fetch", now: datetime | None = None) -> pd.DataFrame:
    """Build gold_series rows from (report_date, value) pairs; None/NaN values are dropped."""
    now = now or utcnow()
    rows = []
    for d, v in points:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            continue
        rd = pd.Timestamp(d).date()
        rel = now if release_kind == "fetch" else release_rule(release_kind, rd)
        rows.append({"series_id": series_id, "report_date": rd, "freq": freq, "value": float(v),
                     "release_at": min(rel, now) if release_kind != "fetch" else now,
                     "release_source": "fetch" if release_kind == "fetch" else "rule",
                     "first_seen_at": now, "source": source, "quality": quality, "revision": 0})
    return pd.DataFrame(rows)


def upsert_series(store: Any, df: pd.DataFrame, *, now: datetime | None = None, tol: float = 1e-9) -> dict[str, int]:
    """Revision-aware upsert into gold_series.

    - unseen (series_id, report_date): inserted with the rule's release_at (capped at now)
    - same value as the latest stored vintage: no-op
    - different value: a new row, release_at = now (strictly after the previous), revision + 1
    """
    if df is None or df.empty:
        return {"inserted": 0, "revised": 0, "unchanged": 0}
    now = now or utcnow()
    ids = sorted(set(df["series_id"]))
    placeholders = ", ".join("?" for _ in ids)
    latest = db.query_df(store, f"""
        SELECT series_id, report_date, value, release_at, revision FROM gold_series
        WHERE series_id IN ({placeholders})
        QUALIFY ROW_NUMBER() OVER (PARTITION BY series_id, report_date ORDER BY release_at DESC) = 1
    """, ids)
    have: dict[tuple[str, date], tuple[float, datetime, int]] = {}
    for r in latest.itertuples(index=False):
        rd = pd.Timestamp(r.report_date).date()
        have[(r.series_id, rd)] = (float(r.value), pd.Timestamp(r.release_at).to_pydatetime(), int(r.revision))
    keep, n_ins, n_rev, n_same = [], 0, 0, 0
    for rec in df.to_dict(orient="records"):
        key = (rec["series_id"], pd.Timestamp(rec["report_date"]).date())
        prev = have.get(key)
        if prev is None:
            n_ins += 1
            keep.append(rec)
            continue
        if abs(prev[0] - float(rec["value"])) <= tol * max(1.0, abs(prev[0])):
            n_same += 1
            continue
        rec = dict(rec)
        rec["release_at"] = max(now, prev[1] + timedelta(seconds=1))
        rec["release_source"] = "fetch"
        rec["revision"] = prev[2] + 1
        rec["first_seen_at"] = now
        n_rev += 1
        keep.append(rec)
    if keep:
        db.upsert(store, "gold_series", pd.DataFrame(keep))
    return {"inserted": n_ins, "revised": n_rev, "unchanged": n_same}


def asof_series(store: Any, series_ids: list[str], *, start: date | None = None, end: date | None = None,
                asof: datetime | None = None) -> pd.DataFrame:
    """Latest vintage per report_date known at ``asof`` (default now) — the §c.1 QUALIFY read."""
    if not series_ids:
        return pd.DataFrame(columns=["series_id", "report_date", "value", "release_at", "revision", "quality", "source"])
    asof = asof or utcnow()
    placeholders = ", ".join("?" for _ in series_ids)
    params: list[Any] = [*series_ids, asof]
    extra = ""
    if start:
        extra += " AND report_date >= ?"
        params.append(start)
    if end:
        extra += " AND report_date <= ?"
        params.append(end)
    return db.query_df(store, f"""
        SELECT series_id, report_date, value, release_at, revision, quality, source, freq
        FROM gold_series
        WHERE series_id IN ({placeholders}) AND release_at <= ?{extra}
        QUALIFY ROW_NUMBER() OVER (PARTITION BY series_id, report_date ORDER BY release_at DESC) = 1
        ORDER BY series_id, report_date
    """, params)


def resample(points: pd.DataFrame, freq: str, how: str = "last") -> pd.DataFrame:
    """D → as stored; W → week ending Friday; M → calendar month end; ``how`` ∈ last|sum|mean.

    ``release_at`` of a bucket is the latest release inside it (the bucket is known only once its last point is)."""
    if points.empty or freq == "D":
        return points
    rule = {"W": "W-FRI", "M": "ME"}[freq]
    idx = pd.to_datetime(points["report_date"])
    s = pd.Series(points["value"].to_numpy(dtype="float64"), index=idx)
    agg = {"last": "last", "sum": "sum", "mean": "mean"}[how]
    vals = s.resample(rule).agg(agg).dropna()
    rel = pd.Series(pd.to_datetime(points["release_at"]).to_numpy(), index=idx).resample(rule).max()
    out = pd.DataFrame({"report_date": [d.date() for d in vals.index], "value": vals.to_numpy(),
                        "release_at": [rel.get(d) for d in vals.index]})
    return out


def latest_asof(store: Any, series_ids: list[str], *, asof: datetime | None = None) -> dict[str, dict[str, Any]]:
    """{series_id: {report_date, value, release_at}} — the newest observation known at ``asof`` per series."""
    if not series_ids:
        return {}
    asof = asof or utcnow()
    placeholders = ", ".join("?" for _ in series_ids)
    df = db.query_df(store, f"""
        SELECT series_id, report_date, value, release_at FROM gold_series
        WHERE series_id IN ({placeholders}) AND release_at <= ?
        QUALIFY ROW_NUMBER() OVER (PARTITION BY series_id ORDER BY report_date DESC, release_at DESC) = 1
    """, [*series_ids, asof])
    out: dict[str, dict[str, Any]] = {}
    for r in df.itertuples(index=False):
        out[str(r.series_id)] = {"report_date": pd.Timestamp(r.report_date).date(), "value": float(r.value),
                                 "release_at": pd.Timestamp(r.release_at).to_pydatetime()}
    return out

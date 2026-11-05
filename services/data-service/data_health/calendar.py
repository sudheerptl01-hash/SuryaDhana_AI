"""NSE trading-day arithmetic for ``expected_by`` (PLAN 1.4: trading-day aware via ``/db/market-holidays``).

Pure functions over a holiday set: the caller passes the exchange holidays it knows (the ``/db/market-holidays``
payload, a stored list, or an empty set in tests → weekdays only). A special session (the 1 Feb 2026 Sunday Budget
session) is a trading day only if the caller lists it in ``extra_sessions``.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
SESSION_CLOSE = time(15, 30)


def is_trading_day(d: date, holidays: Iterable[date] = (), extra_sessions: Iterable[date] = ()) -> bool:
    if d in set(extra_sessions):
        return True
    return d.weekday() < 5 and d not in set(holidays)


def prev_trading_day(d: date, holidays: Iterable[date] = (), extra_sessions: Iterable[date] = ()) -> date:
    """The last trading day strictly before ``d``."""
    hol, extra = set(holidays), set(extra_sessions)
    out = d - timedelta(days=1)
    while not is_trading_day(out, hol, extra):
        out -= timedelta(days=1)
    return out


def next_trading_day(d: date, holidays: Iterable[date] = (), extra_sessions: Iterable[date] = ()) -> date:
    hol, extra = set(holidays), set(extra_sessions)
    out = d + timedelta(days=1)
    while not is_trading_day(out, hol, extra):
        out += timedelta(days=1)
    return out


def add_trading_days(d: date, n: int, holidays: Iterable[date] = (), extra_sessions: Iterable[date] = ()) -> date:
    out = d
    for _ in range(n):
        out = next_trading_day(out, holidays, extra_sessions)
    return out


def last_completed_session(now_ist: datetime, holidays: Iterable[date] = (), extra_sessions: Iterable[date] = ()) -> date:
    """The most recent session whose close (15:30 IST) has passed: today after 15:30 on a trading day, else the previous one."""
    today = now_ist.date()
    if is_trading_day(today, holidays, extra_sessions) and now_ist.time() >= SESSION_CLOSE:
        return today
    return prev_trading_day(today, holidays, extra_sessions)


def sessions_between(a: date, b: date, holidays: Iterable[date] = (), extra_sessions: Iterable[date] = ()) -> int:
    """Number of trading sessions in (a, b]; negative when b < a."""
    if b < a:
        return -sessions_between(b, a, holidays, extra_sessions)
    n, d = 0, a
    while d < b:
        d = next_trading_day(d, holidays, extra_sessions)
        if d <= b:
            n += 1
    return n


def parse_hhmm(s: str | None) -> time | None:
    if not s:
        return None
    try:
        hh, mm = s.strip().split(":")
        return time(int(hh), int(mm))
    except (ValueError, AttributeError):
        return None


def deadline_for(session: date, expected_by: str | None, offset_days: int, holidays: Iterable[date] = (),
                 extra_sessions: Iterable[date] = ()) -> datetime | None:
    """IST datetime by which the dataset for ``session`` is expected: ``expected_by`` on the trading day ``offset_days`` after it."""
    t = parse_hhmm(expected_by)
    if t is None:
        return None
    day = add_trading_days(session, offset_days, holidays, extra_sessions) if offset_days > 0 else session
    return datetime.combine(day, t, tzinfo=IST)


def now_ist(now_utc_naive: datetime | None = None) -> datetime:
    if now_utc_naive is None:
        return datetime.now(IST)
    return now_utc_naive.replace(tzinfo=ZoneInfo("UTC")).astimezone(IST)

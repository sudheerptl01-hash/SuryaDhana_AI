"""Yahoo chart API (SOURCES.md A1–A6, G17) — CODE ONLY in this build; exercised with the saved bodies, never run
against Yahoo from the build machine (it throttled the 08:45 snapshot on 26 Oct).

Rules (PLAN 0.1 #2): app UA on ``query2``; daily bars with ``period1/period2`` (``range=max&interval=1d`` silently
returns MONTHLY bars — ``parse_chart`` raises ``MonthlyTrap`` when the body's granularity is not the one asked for);
one call per symbol 6 s apart (the HTTP wrapper paces); 429 → back off 5/10/20 min and log STALE.
"""
from __future__ import annotations

import io
import json
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from gold import db
from gold.catalog_seed import YAHOO_DAILY
from gold.db import utcnow
from shared.logging import get_logger

logger = get_logger(__name__)

CHART_URL = "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
INTRADAY_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
DAILY_START = date(1990, 1, 1)
INTRADAY_RETENTION_DAYS = 400
MONTH_CODES = {"F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6, "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12}
CURVE_MONTHS: tuple[str, ...] = ("GCZ26.CMX", "GCG27.CMX", "GCJ27.CMX", "GCM27.CMX", "GCQ27.CMX", "GCZ27.CMX")
SYMBOL_BY_SERIES: dict[str, str] = {sid: v[0] for sid, v in YAHOO_DAILY.items()}
SERIES_BY_SYMBOL: dict[str, str] = {v[0]: sid for sid, v in YAHOO_DAILY.items()}


class MonthlyTrap(ValueError):
    """The body's ``dataGranularity`` is not the interval requested (the ``range=max`` trap)."""


def parse_chart(text_or_obj: str | dict[str, Any], *, expect_interval: str | None = None) -> tuple[dict[str, Any], pd.DataFrame]:
    """(meta, bars[ts_utc, open, high, low, close, volume]) from a chart body; rows with a null close are dropped."""
    obj = json.loads(text_or_obj) if isinstance(text_or_obj, str) else text_or_obj
    chart = obj.get("chart") or {}
    if chart.get("error"):
        raise ValueError(f"yahoo chart error: {chart['error'].get('code')}")
    res = (chart.get("result") or [None])[0]
    if not res:
        raise ValueError("yahoo chart: empty result")
    meta = res.get("meta") or {}
    gran = meta.get("dataGranularity")
    if expect_interval and gran and gran != expect_interval:
        raise MonthlyTrap(f"asked {expect_interval}, body is {gran} (range=max trap)")
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    ts = res.get("timestamp") or []
    df = pd.DataFrame({"ts": pd.to_datetime(ts, unit="s", utc=True), "open": q.get("open"), "high": q.get("high"),
                       "low": q.get("low"), "close": q.get("close"), "volume": q.get("volume")})
    df = df[df["close"].notna()].reset_index(drop=True)
    return meta, df


def session_date(local_date: date) -> date:
    """The session a bar belongs to: a weekend-dated bar is the Globex / FX Sunday-evening open of MONDAY's session
    (CME's trade date), never a session of its own — so the completed Monday bar replaces it under the same key.

    This is the rule for a bar stamped with a DATE only (an anchored completed bar, the G-MACRO CSV seeds). A trailing
    bar stamped with a live quote TIME goes through ``quote_session_date`` instead: a weekend quote is Friday's last
    print, not Monday's open (wave 2, C-DATA-02)."""
    if local_date.weekday() >= 5:
        return local_date + timedelta(days=7 - local_date.weekday())
    return local_date


# The clocks a daily bar's session is measured by (wave 2, C-DATA-02). America/New_York, DST-correct through ZoneInfo:
FX_ROLL_HOUR = 17        # the interbank FX value date rolls at 17:00 NY; Fri 17:00 → Sun 17:00 is the weekend gap
GLOBEX_OPEN_HOUR = 18    # CME: the trade date rolls at 17:00 NY and the next session opens 18:00 NY


def _is_cash(symbol: str) -> bool:
    """True for the cash sessions (NSE, US ETFs / indices) — no overnight session, so no 17:00 roll."""
    return symbol.endswith(".NS") or symbol.startswith("^") or symbol in ("GLD", "IAU", "SLV")


def special_session_day(d: date, symbol: str | None = None) -> bool:
    """True when ``d`` is a DATED special session (MCX Muhurat, Sun 8 Nov 2026: ``shared/mcx_specs``) — a session in its
    own right even though it falls on a weekend. Scoped to INDIAN symbols (``.NS``; the MCX table dates the same Diwali
    session the NSE keeps) — elsewhere the weekend rule stands. CLAUDE.md binds every session helper to count these, and
    ``gold/reads.py`` already does; without it (8 Nov 2026) a weekend special-session bar was rolled back to the Friday,
    collided with Friday's own bar and was silently dropped by ``collapse_sessions``."""
    if symbol is not None and not symbol.endswith(".NS"):
        return False                       # COMEX / ICE / the FX fixings are shut that Sunday: dating a quote to it invents a session
    try:
        from shared import mcx_specs as specs
        return specs.special_session_on(d) is not None
    except Exception:                      # noqa: BLE001 — a missing table must never lose a bar: fall back to the weekday rule
        return False


def previous_friday(d: date, symbol: str | None = None) -> date:
    """``d`` itself on a weekday, or on a dated special session of ``symbol``'s exchange; else the Friday before it."""
    if d.weekday() < 5 or special_session_day(d, symbol):
        return d
    return d - timedelta(days=d.weekday() - 4)


def session_clock(symbol: str) -> tuple[str, int, int]:
    """(exchange zone, close hour, close minute) — the ONE clock a daily session of ``symbol`` is measured by: NSE
    (``.NS``) 15:30 IST, US cash ETFs / indices 16:00 New York, COMEX / ICE futures, DXY and the FX fixings 17:00 New
    York (the Globex day's close, which is also the trade-date roll).

    Both ``session_close_utc`` (when the bar dated D is final) and ``quote_session_date`` (which session a quote at an
    instant belongs to) read this, so the date a quote is given and the instant that date settles cannot disagree.
    Round 2 of wave 2: the cash branch dated a quote by the NEW YORK calendar day while the close was measured in
    Asia/Kolkata, so between 00:00 and 10:30 IST a live GOLDBEES.NS bar was dated to the PREVIOUS session — and since
    that session's 15:30 IST close had passed, stored as a settled ``close``. Same defect class as C-DATA-02, on the
    write side, where no read-time clamp can undo it."""
    if symbol.endswith(".NS"):
        return "Asia/Kolkata", 15, 30
    if _is_cash(symbol):
        return "America/New_York", 16, 0
    return "America/New_York", FX_ROLL_HOUR, 0


def quote_session_date(symbol: str, ts: Any) -> date:
    """The session a LIVE quote at instant ``ts`` belongs to — the rule a trailing (non-anchored) chart bar is dated by.

    Futures and FX: the trade date rolls at 17:00 New York, so a quote is dated by its NY instant shifted 7 hours; a
    result that lands on a weekend is the WEEKEND GAP (Friday 17:00 → Sunday's open), where the only quote available is
    Friday's last print, so it is dated to that Friday — never rolled forward to Monday (C-DATA-02: a Sunday-morning IST
    catch-up stored Friday's 93.91 USD/INR as next Monday, giving ``age_days`` −1 and "as of Mon 09 Nov" on screen).
    The new week starts at 17:00 NY Sunday for FX and 18:00 NY Sunday for Globex; before that hour a Sunday quote is
    still Friday's. Cash sessions (NSE, GLD / IAU / SLV, ``^`` indices) have no overnight session: the quote keeps its
    own day **in the exchange's own zone** (``session_clock``, never New York for an NSE name), and a weekend quote is
    Friday's close."""
    t = pd.Timestamp(ts)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    ny = t.tz_convert("America/New_York")
    if _is_cash(symbol):
        return previous_friday(t.tz_convert(session_clock(symbol)[0]).date(), symbol)
    rolled = (ny + pd.Timedelta(hours=24 - FX_ROLL_HOUR)).date()
    if rolled.weekday() >= 5:                                     # Friday 17:00 → Sunday: the market is shut
        return previous_friday(rolled, symbol)
    open_hour = FX_ROLL_HOUR if symbol.endswith("=X") else GLOBEX_OPEN_HOUR
    if ny.weekday() == 6 and ny.hour < open_hour:                 # Sunday, before the week opens
        return previous_friday(ny.date(), symbol)
    return rolled


def live_quote(meta: dict[str, Any], symbol: str) -> tuple[date | None, float | None]:
    """(session date, price) of the body's own last quote (``regularMarketTime`` / ``regularMarketPrice``), or (None,
    None) when the body carries none. On a weekend this IS Friday's last print, which is the honest close of Friday's
    session for a quote feed that stops printing at the roll."""
    t, p = meta.get("regularMarketTime"), meta.get("regularMarketPrice")
    if not isinstance(t, (int, float)) or isinstance(t, bool) or t <= 0:
        return None, None
    if not isinstance(p, (int, float)) or isinstance(p, bool):
        return None, None
    return quote_session_date(symbol, pd.Timestamp(int(t), unit="s", tz="UTC")), float(p)


def session_close_utc(symbol: str, trade_date: date) -> datetime:
    """When the daily bar dated ``trade_date`` is final, as a UTC-naive instant (DST-correct through the exchange zone):
    NSE (``.NS``) 15:30 IST; US cash ETFs / indices 16:00 New York; COMEX / ICE futures, DXY and the FX fixings 17:00 New
    York (the Globex day's close). Wave 1c, C-DATA-21 / C-TRADER-25: a bar fetched BEFORE this instant is the in-progress
    session (``is_partial``), never a settlement — the 03:10 IST job runs 20 minutes before the winter Globex close.

    The zone and time come from ``session_clock``, the same one ``quote_session_date`` dates a quote by."""
    zone, hh, mm = session_clock(symbol)
    local = datetime(trade_date.year, trade_date.month, trade_date.day, hh, mm, tzinfo=ZoneInfo(zone))
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def is_partial(symbol: str, trade_date: Any, first_seen_at: Any) -> bool:
    """True when the stored bar was fetched before its session closed (see ``session_close_utc``); False when the fetch time
    is unknown (nothing is flagged on a guess)."""
    d = db.to_date(trade_date)
    if d is None or first_seen_at is None or first_seen_at is pd.NaT:
        return False
    seen = pd.Timestamp(first_seen_at)
    if seen.tzinfo is not None:
        seen = seen.tz_convert("UTC").tz_localize(None)
    return bool(seen.to_pydatetime() < session_close_utc(symbol, d))


def _anchor_time(meta: dict[str, Any], local_ts: pd.Series) -> Any:
    """The exchange-local time-of-day a COMPLETED daily bar is stamped with (``currentTradingPeriod.regular.start`` —
    00:00 for futures/FX, 09:30 for GLD, 09:15 IST for GOLDBEES); falls back to the modal time of the earlier bars."""
    tz = str(local_ts.dt.tz) if local_ts.dt.tz is not None else "UTC"
    start = ((meta.get("currentTradingPeriod") or {}).get("regular") or {}).get("start")
    if isinstance(start, (int, float)) and start > 0:
        return pd.Timestamp(int(start), unit="s", tz="UTC").tz_convert(tz).time()
    times = local_ts.iloc[:-1].dt.time
    return times.mode().iloc[0] if not times.empty else None


def trade_dates(meta: dict[str, Any], bars: pd.DataFrame, symbol: str | None = None) -> pd.Series:
    """Exchange-local trade dates for chart bars (see ``dated_bars``, which also reports which bar was re-dated)."""
    return dated_bars(meta, bars, symbol)[0]


def dated_bars(meta: dict[str, Any], bars: pd.DataFrame, symbol: str | None = None) -> tuple[pd.Series, pd.Series]:
    """(trade dates, "re-dated by the quote clock" mask) for chart bars.

    A completed bar sits on the session anchor and its stamp IS its session (``session_date``). The TRAILING bar is
    dated by the instant the body was looking at (``quote_session_date`` of the later of its own stamp and
    ``regularMarketTime``) in the two cases where its stamp cannot be trusted:

    - it is not on the anchor, i.e. the stamp is a live quote time (the Sunday-evening Globex bar → Monday); and
    - its stamp falls on a WEEKEND, where Yahoo opens the next period's bucket as soon as the exchange-local date turns
      and fills it with the only print there is — Friday's last quote. ``session_date`` rolled that bucket forward to
      Monday, so a Sunday-morning IST fetch stored Friday's 93.91 USD/INR under next Monday's date, with ``age_days``
      −1 and "as of Mon 09 Nov" on screen on a Sunday (wave 2, C-DATA-02). It belongs to Friday.

    A weekday-stamped anchored bar is never moved, so a body that holds only completed bars plus a live quote from a
    later session keeps every bar on its own session.

    The second series is True exactly for the bar whose date came from the QUOTE clock rather than from its own stamp.
    ``collapse_sessions`` needs it: such a row may not alter a session that has already settled.
    """
    sym = symbol or str(meta.get("symbol") or "")
    tz = meta.get("exchangeTimezoneName") or "UTC"
    local = bars["ts"].dt.tz_convert(tz)
    dates = local.dt.date.copy()
    requoted = pd.Series(False, index=dates.index, dtype=bool)
    if len(local) == 0:
        return dates, requoted
    out = dates.map(session_date)
    anchor = _anchor_time(meta, local)
    last_local = local.iloc[-1]
    if anchor is None or last_local.time() != anchor or last_local.date().weekday() >= 5:
        out.iloc[-1] = quote_session_date(sym, _latest_instant(meta, bars["ts"].iloc[-1]))
        requoted.iloc[-1] = True
    return out, requoted


def _latest_instant(meta: dict[str, Any], ts: Any) -> pd.Timestamp:
    """The later of a bar's own stamp and the body's ``regularMarketTime`` — the latest instant the body is known to
    have been looking at, so a trailing bucket opened before the week's open is still dated by the quote inside it."""
    t = pd.Timestamp(ts)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    q = meta.get("regularMarketTime")
    if isinstance(q, (int, float)) and not isinstance(q, bool) and q > 0:
        return max(t, pd.Timestamp(int(q), unit="s", tz="UTC"))
    return t


#: ``vendor_close`` is the FIRST bar's close, i.e. Yahoo's own number for the completed session — a trailing live quote
#: merged into that session moves ``close``, never the audit copy in ``adj_close``.
_SESSION_AGG: dict[str, str] = {"open": "first", "high": "max", "low": "min", "close": "last", "vendor_close": "first", "volume": "max"}
REQUOTED = "_requoted"      # the per-bar flag ``dated_bars`` returns; dropped before the frame is built


def _naive_utc(ts: Any) -> datetime:
    """A UTC-naive instant (the store's convention) from a naive or aware value."""
    t = pd.Timestamp(ts)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    return t.tz_localize(None).to_pydatetime()


def collapse_sessions(df: pd.DataFrame, *, symbol: str = "", now: datetime | None = None) -> pd.DataFrame:
    """One row per ``trade_date``.

    Two bars of the same session meet when the trailing live quote is re-dated onto a session another bar already
    describes (the ``REQUOTED`` flag from ``dated_bars`` — Yahoo opens the next exchange-local bucket the moment the
    date turns and fills it with the only print there is). While that session is still OPEN the later print is the
    fresher one: the session keeps its REAL open / high / low and only the close moves (wave 2, C-DATA-02 —
    ``keep='last'`` used to flatten Friday's whole 94.5178 / 93.8308 range onto one quote).

    Once the session has CLOSED, a post-session print may not be merged into the bar Yahoo published for it: that bar
    is DROPPED instead (round 2 of wave 2). Yahoo's final futures close is the 13:30 ET settlement print — GCZ26's
    Thursday 4,113.5 — while the session's last trade is a different number (4,097.9), so merging a weekend bucket
    into Friday would replace a settlement with a late trade and store it as a ``close``: the honesty breach
    C-DATA-02 / C-DATA-05 are about, on the write side, where no read-time clamp can undo it and where
    ``INSERT OR REPLACE`` would overwrite the settled bar already in the store. An FX close of a settled session moves
    only through ``fx_session_close``, which names the quote it used and keeps the vendor's number in ``adj_close``.

    The drop is deliberately limited to the case where the frame ALSO carries that session's own bar. A re-dated row
    that is the only thing the body says about a settled session is kept — there is nothing better to serve, and it
    cannot overwrite a settlement either, because a session the store already holds settled is inside the fetch window
    (``period1`` = last stored bar − 5 days at the widest) and therefore comes back with its own anchored bar.

    A frame with no ``REQUOTED`` column (the G-MACRO CSV seeds: date-only rows, no quote clock) is merged as before."""
    if df.empty:
        return df.drop(columns=[REQUOTED], errors="ignore").reset_index(drop=True)
    out = df.sort_values("trade_date", kind="stable")          # oldest first, bars of one session in the order received
    if REQUOTED in out.columns:
        ref = _naive_utc(now or utcnow())
        flags = [bool(f) for f in out[REQUOTED]]
        own = {db.to_date(d) for d, f in zip(out["trade_date"], flags, strict=True) if not f}
        settled: list[bool] = []
        for flag, d in zip(flags, out["trade_date"], strict=True):
            day = db.to_date(d)
            settled.append(flag and day is not None and day in own and session_close_utc(symbol, day) <= ref)
        if any(settled):
            logger.warning("gold.yahoo.post_session_quote_dropped", symbol=symbol,
                           dates=[str(d) for d, s in zip(out["trade_date"], settled, strict=True) if s][:5])
            out = out[[not s for s in settled]]
        out = out.drop(columns=[REQUOTED])
    if out.empty or not out["trade_date"].duplicated().any():
        return out.reset_index(drop=True)
    # high / low are the extremes of the merged bars; the open and close are NOT folded into them, so an impossible
    # open (a partial Yahoo bar carrying the previous session's open) still shows as one and the UI can print '—'
    return out.groupby("trade_date", as_index=False, sort=True).agg(_SESSION_AGG)


def fx_session_close(df: pd.DataFrame, meta: dict[str, Any] | None = None, symbol: str = "") -> pd.DataFrame:
    """Rebuild the session close of an FX (``=X``) daily frame; ``df`` is one row per session, oldest first.

    Yahoo's COMPLETED FX daily bar closes at its own open — the 00:00 London snapshot, about two hours after the
    17:00 New York roll that STARTS the session — so a stored "close" dated D is really D−1's close. Measured over 282
    stored sessions, |close − own open| is ≈ 1 bp while |close − next open| is 18–33 bp, i.e. the whole daily move; the
    daily change of DXY (a real futures close) correlates −0.11 with EUR/USD dated the same day and −0.82 with it dated
    the next session, and against FRED's noon New York rates the same one-session shift appears (C-DATA-02).

    The close of session D is therefore, in order of preference: the quote feed's last print for D (``live_quote`` —
    on a weekend that is Friday's final print), else D+1's opening snapshot (≈ 2 h after D's roll). The vendor's own
    number stays in ``adj_close`` so a reader can always see what Yahoo published, and ``reads`` labels a row whose
    close is still the vendor's as ``open_snapshot`` instead of ``close``.

    Residual, by design: for a Friday whose successor is Monday, D+1's open is the Sunday-evening print, so a Friday
    close written from a weekend fetch (exact) is replaced by that print on Monday's run — a few bp, against the full
    session the old close was out by. Nothing here is a forecast: the frame describes sessions that have happened."""
    if df.empty:
        return df
    out = df.copy()
    nxt = out["open"].shift(-1)
    live_day, live_price = live_quote(meta or {}, symbol)
    close = out["close"].astype("float64").to_numpy(copy=True)
    last = len(out) - 1
    for i in range(len(out)):
        if pd.notna(nxt.iloc[i]):
            close[i] = float(nxt.iloc[i])
        elif i == last and live_price is not None and live_day is not None and db.to_date(out["trade_date"].iloc[i]) == live_day:
            close[i] = float(live_price)
    out["close"] = close
    out["high"] = out[["high", "close"]].max(axis=1)              # the rebuilt close is inside the day's range by construction
    out["low"] = out[["low", "close"]].min(axis=1)
    return out


def drop_future_rows(df: pd.DataFrame, symbol: str, now: datetime) -> pd.DataFrame:
    """No bar may carry a ``trade_date`` after the IST day of the fetch: a session cannot be described before it starts.
    The Globex and FX weeks both open on Sunday evening New York, which is already Monday in IST, so this never drops a
    legitimate in-progress bar (wave 2, C-DATA-02)."""
    if df.empty:
        return df
    today = ist_date_of(now)
    keep = [(db.to_date(d) or today) <= today for d in df["trade_date"]]
    if not all(keep):
        bad = [str(d) for d, k in zip(df["trade_date"], keep, strict=True) if not k]
        logger.warning("gold.yahoo.future_bar_dropped", symbol=symbol, dates=bad[:5], ist_date=str(today))
        df = df[keep].reset_index(drop=True)
    return df


def daily_bars_frame(meta: dict[str, Any], bars: pd.DataFrame, symbol: str, *, now: datetime | None = None) -> pd.DataFrame:
    """gold_daily_bars rows; the trade date is the SESSION date of each bar (``dated_bars``), bars of one session are
    merged while that session is open and a post-session quote is refused when it has closed (``collapse_sessions``),
    an FX close is rebuilt to the session's own close (``fx_session_close``) and a row dated after the fetch's IST day
    is dropped (``drop_future_rows``)."""
    now = now or utcnow()
    if bars.empty:
        return pd.DataFrame()
    df = bars.copy()
    df["trade_date"], df[REQUOTED] = dated_bars(meta, df, symbol)
    df["vendor_close"] = df["close"]
    df = collapse_sessions(df, symbol=symbol, now=now)
    if df.empty:
        return pd.DataFrame()
    if symbol.endswith("=X"):
        df = fx_session_close(df, meta, symbol)
    out = pd.DataFrame({"trade_date": df["trade_date"], "symbol": symbol, "open": df["open"], "high": df["high"], "low": df["low"],
                        "close": df["close"], "adj_close": df["vendor_close"], "volume": df["volume"].fillna(0).astype("int64"),
                        "source": "yahoo", "first_seen_at": now})
    return drop_future_rows(out, symbol, now)


def parse_daily_csv(text: str, symbol: str, *, now: datetime | None = None) -> pd.DataFrame:
    """The G-MACRO ``yahoo_<sym>.csv`` seeds (date,open,high,low,close,volume). Same session rules as the chart path,
    so a re-ingested seed never re-introduces the one-session FX lag (there is no quote time in a seed, so an FX close
    comes from the next session's open and the newest row keeps the vendor's)."""
    now = now or utcnow()
    df = pd.read_csv(io.StringIO(text))
    df = df[df["close"].notna()]
    df["trade_date"] = pd.to_datetime(df["date"]).dt.date.map(session_date)   # a weekend row is the Sunday-evening partial
    df["vendor_close"] = df["close"]
    # no REQUOTED column: a seed row carries a DATE, never a quote instant, so there is no post-session print to refuse
    # and a weekend row rolled onto Monday still merges with the completed Monday bar (the newer one wins)
    df = collapse_sessions(df, symbol=symbol, now=now)
    if symbol.endswith("=X"):
        df = fx_session_close(df, None, symbol)
    out = pd.DataFrame({"trade_date": df["trade_date"], "symbol": symbol, "open": df["open"], "high": df["high"], "low": df["low"],
                        "close": df["close"], "adj_close": df["vendor_close"], "volume": df["volume"].fillna(0).astype("int64"),
                        "source": "yahoo", "first_seen_at": now})
    return drop_future_rows(out, symbol, now)


def ingest_daily(store: Any, df: pd.DataFrame) -> int:
    return db.upsert(store, "gold_daily_bars", df)


def daily_params(start: date, end: date | None = None) -> dict[str, Any]:
    end = end or (utcnow().date() + timedelta(days=1))
    p1 = int(datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    p2 = int(datetime.combine(end, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    return {"period1": p1, "period2": p2, "interval": "1d", "includePrePost": "false", "events": "div,splits"}


def last_trade_date(store: Any, symbol: str) -> date | None:
    v = db.scalar(store, "SELECT MAX(trade_date) FROM gold_daily_bars WHERE symbol = ?", [symbol])
    return pd.Timestamp(v).date() if v is not None else None


PARTIAL_LOOKBACK_DAYS = 60       # how far back a partial bar is still chased (bounds the window a repair can widen to)


def partial_dates(store: Any, symbol: str, *, days: int = PARTIAL_LOOKBACK_DAYS, now: datetime | None = None) -> list[date]:
    """The stored ``yahoo`` bars of ``symbol`` in the last ``days`` that were fetched BEFORE their session closed
    (``is_partial``), oldest first — the rows whose OHLCV is an in-progress session, not a close."""
    cutoff = (now or utcnow()).date() - timedelta(days=days)
    df = db.query_df(store, """SELECT trade_date, first_seen_at FROM gold_daily_bars
                               WHERE symbol = ? AND source = 'yahoo' AND trade_date >= ? ORDER BY trade_date""", [symbol, cutoff])
    out = []
    for r in df.itertuples(index=False):
        d = db.to_date(r.trade_date)
        if d is not None and is_partial(symbol, d, r.first_seen_at):
            out.append(d)
    return out


def fetch_daily(store: Any, http: Any, *, symbols: Iterable[str] | None = None, backfill_from: date | None = None,
                now: datetime | None = None) -> dict[str, Any]:
    """One paced call per symbol. ``period1`` = the last stored bar − 5 days, WIDENED (never narrowed) by
    ``backfill_from`` and by the oldest stored partial bar, so no extra call is ever made:

    - a catch-up start used to REPLACE the routine look-back, so a run resuming from ``backfill_from`` = the day after a
      partial bar never re-fetched it (C-DATA-05: GC=F's Thu 05 Nov bar kept a mid-session close of 4,098.4 against the
      final 4,113.5, and Friday's change was computed off it). ``min`` of the two fixes that.
    - a partial bar is re-fetched until Yahoo returns it final, so it heals on the next run instead of surviving for
      good whenever an outage moves the last stored bar more than five days past it.
    """
    out: dict[str, Any] = {}
    for sym in (symbols or SERIES_BY_SYMBOL.keys()):
        try:
            last = last_trade_date(store, sym)
            routine = (last - timedelta(days=5)) if last else DAILY_START
            start = min(backfill_from, routine) if backfill_from else routine
            before = partial_dates(store, sym, now=now)
            if before and before[0] < start:
                start = before[0]
            resp = http.get(CHART_URL.format(symbol=sym), params=daily_params(start))
            if resp.status_code != 200:
                out[sym] = {"status": f"http_{resp.status_code}", "stale": True}
                continue
            meta, bars = parse_chart(resp.text, expect_interval="1d")
            n = ingest_daily(store, daily_bars_frame(meta, bars, sym, now=now))
            still = set(partial_dates(store, sym, now=now))
            out[sym] = {"status": "ok", "rows": n, "last": str(last_trade_date(store, sym)), "from": start.isoformat(),
                        "repaired_partials": len([d for d in before if d not in still]), "partials_open": len(still)}
        except Exception as exc:  # noqa: BLE001 — one symbol never stops the group
            out[sym] = {"status": "error", "error": str(exc)[:160], "stale": True}
            logger.warning("gold.yahoo.symbol_failed", symbol=sym)
    return out


PARTIAL_REPAIR_MAX_SYMBOLS = 16      # every non-cash symbol in YAHOO_DAILY; one paced call each, ~6 s apart


def settled_partials(store: Any, symbol: str, *, days: int = PARTIAL_LOOKBACK_DAYS, now: datetime | None = None) -> list[date]:
    """The stored partial bars of ``symbol`` whose session has SINCE closed, oldest first — the rows Yahoo can now
    return final. A bar of a session that is still RUNNING is excluded: re-fetching it would only store another
    in-progress price. The live defect was an INTERIOR one (GC=F's Thu 05 Nov bar with Friday's settled bar after it),
    so this is not limited to the newest bar."""
    ref = _naive_utc(now or utcnow())
    return [d for d in partial_dates(store, symbol, days=days, now=now) if session_close_utc(symbol, d) <= ref]


def repair_partials(store: Any, http: Any, *, symbols: Iterable[str] | None = None,
                    max_symbols: int = PARTIAL_REPAIR_MAX_SYMBOLS, now: datetime | None = None) -> dict[str, Any]:
    """Re-fetch ONLY the symbols holding a partial bar whose session has since closed, so such a bar heals within the
    same IST day instead of waiting for the next 03:10 overnight pull (C-DATA-05, round 2).

    In winter the 03:10 IST run lands 20 minutes before the 17:00 ET Globex close, so the session it just stored is a
    mid-session price for the whole following IST day — that is how GC=F's Thursday close stayed 4,098.4 against the
    final 4,113.5 while WEEKLY printed Friday's change against it. ``fetch_daily`` already widens ``period1`` to the
    oldest partial bar, so this is the same code on a second, cheap trigger: nothing to heal costs ZERO calls, and a
    session still running is never re-pulled. The 60-day bound in ``partial_dates`` also bounds this, so a bar Yahoo
    never returns final cannot be chased for ever."""
    cands = [s for s in (symbols or SERIES_BY_SYMBOL.keys()) if settled_partials(store, s, now=now)]
    out: dict[str, Any] = {"candidates": len(cands), "calls": 0, "skipped": 0, "symbols": {},
                           "repaired_partials": 0, "partials_open": 0, "stale": []}
    if not cands:
        return out
    picked = cands[:max_symbols]
    res = fetch_daily(store, http, symbols=picked, now=now)
    out.update({"calls": len(picked), "skipped": len(cands) - len(picked), "symbols": res,
                "repaired_partials": sum(int(v.get("repaired_partials") or 0) for v in res.values()),
                "partials_open": sum(int(v.get("partials_open") or 0) for v in res.values()),
                "stale": [s for s, v in res.items() if v.get("stale")]})
    return out


# ── intraday bars (A1 7d/1m, 60d/5m; D4 SGE handled in ingest_physical) ─────────────────────────────

def intraday_frame(bars: pd.DataFrame, symbol: str, interval: str, *, now: datetime | None = None) -> pd.DataFrame:
    now = now or utcnow()
    if bars.empty:
        return pd.DataFrame()
    return pd.DataFrame({"symbol": symbol, "ts": bars["ts"].dt.tz_convert("UTC").dt.tz_localize(None), "interval": interval,
                         "open": bars["open"], "high": bars["high"], "low": bars["low"], "close": bars["close"],
                         "volume": bars["volume"].fillna(0).astype("int64"), "source": "yahoo", "first_seen_at": now})


def ingest_intraday(store: Any, df: pd.DataFrame) -> int:
    return db.upsert(store, "gold_bars_intraday", df)


def prune_intraday(store: Any, *, days: int = INTRADAY_RETENTION_DAYS, now: datetime | None = None) -> None:
    cutoff = (now or utcnow()) - timedelta(days=days)
    db.execute(store, "DELETE FROM gold_bars_intraday WHERE ts < ?", [cutoff])


def fetch_intraday(store: Any, http: Any, *, symbols: Iterable[str] = ("GC=F", "INR=X"), first_run: bool = False,
                   now: datetime | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    plans = [("7d", "1m")] + ([("60d", "5m")] if first_run else [])
    for sym in symbols:
        for rng, itv in plans:
            try:
                resp = http.get(INTRADAY_URL.format(symbol=sym), params={"range": rng, "interval": itv, "includePrePost": "true"})
                if resp.status_code != 200:
                    out[f"{sym}:{itv}"] = {"status": f"http_{resp.status_code}", "stale": True}
                    continue
                _, bars = parse_chart(resp.text, expect_interval=itv)
                out[f"{sym}:{itv}"] = {"status": "ok", "rows": ingest_intraday(store, intraday_frame(bars, sym, itv, now=now))}
            except Exception as exc:  # noqa: BLE001
                out[f"{sym}:{itv}"] = {"status": "error", "error": str(exc)[:160], "stale": True}
    prune_intraday(store, now=now)
    return out


# ── per-month COMEX curve (A2) ──────────────────────────────────────────────────────────────────────

def month_symbol_expiry(symbol: str, store: Any | None = None) -> tuple[str, date, str]:
    """('GC', expiry, 'calendar'|'computed') for 'GCZ26.CMX': the CME calendar's last trade when stored, else the
    third-last business day of the month (COMEX rule) — labelled ``computed``."""
    code = symbol.split(".")[0]
    root, mcode, yy = code[:-3], code[-3], int(code[-2:])
    year, month = 2000 + yy, MONTH_CODES[mcode]
    mmy = f"{year}{month:02d}"
    if store is not None:
        v = db.scalar(store, "SELECT last_trade FROM gold_cme_calendar WHERE symbol = ? AND mmy = ? ORDER BY as_of DESC LIMIT 1", [root, mmy])
        if v is not None:
            return root, pd.Timestamp(v).date(), "calendar"
    last = pd.Timestamp(year, month, 1) + pd.offsets.MonthEnd(0)
    bdays = pd.bdate_range(end=last, periods=3)
    return root, bdays[0].date(), "computed"


def curve_frame_from_chart(symbol: str, meta: dict[str, Any], bars: pd.DataFrame, store: Any | None = None,
                           *, now: datetime | None = None) -> pd.DataFrame:
    now = now or utcnow()
    if bars.empty:
        return pd.DataFrame()
    root, expiry, _ = month_symbol_expiry(symbol, store)
    tz = meta.get("exchangeTimezoneName") or "America/New_York"
    last = bars.iloc[-1]
    d = last["ts"].tz_convert(tz).date()
    return pd.DataFrame([{"trade_date": d, "exchange": "COMEX", "symbol": root, "expiry": expiry, "open": last["open"], "high": last["high"],
                          "low": last["low"], "close": last["close"], "settle": None, "band_lo": None, "band_hi": None,
                          "volume": int(last["volume"] or 0), "open_interest": None, "oi_change": None, "unit": "USD/oz",
                          "source": "yahoo", "quality": "last_trade", "session_date": d, "release_at": now, "first_seen_at": now}])


def fetch_curve(store: Any, http: Any, *, symbols: Iterable[str] = CURVE_MONTHS, now: datetime | None = None) -> dict[str, Any]:
    """One 5d/1d chart call per delivery month: the last trade goes to ``gold_curve`` (the term structure) AND the daily
    bars to ``gold_daily_bars`` under the month symbol (``GCZ26.CMX``), so the header can show the matched month's own
    last / close (wave 1c, C-TRADER-9 / C-BEGINNER-6) instead of NO DATA. Yahoo gives a last trade, never a settlement:
    the curve row keeps ``quality = last_trade`` and the bar is labelled by its source."""
    out: dict[str, Any] = {}
    for sym in symbols:
        try:
            resp = http.get(CHART_URL.format(symbol=sym), params={"range": "5d", "interval": "1d"})
            if resp.status_code != 200:
                out[sym] = {"status": f"http_{resp.status_code}"}
                continue
            meta, bars = parse_chart(resp.text, expect_interval="1d")
            n_curve = db.upsert(store, "gold_curve", curve_frame_from_chart(sym, meta, bars, store, now=now))
            n_bars = ingest_daily(store, daily_bars_frame(meta, bars, sym, now=now))
            out[sym] = {"status": "ok", "rows": n_curve, "daily_bars": n_bars}
        except Exception as exc:  # noqa: BLE001
            out[sym] = {"status": "error", "error": str(exc)[:160]}
    return out


def ist_date_of(ts_utc: datetime) -> date:
    """The IST calendar day of an instant; a naive value is read as UTC (the store's convention), an aware one converted."""
    t = pd.Timestamp(ts_utc)
    t = t.tz_localize("UTC") if t.tzinfo is None else t
    return t.tz_convert(ZoneInfo("Asia/Kolkata")).date()

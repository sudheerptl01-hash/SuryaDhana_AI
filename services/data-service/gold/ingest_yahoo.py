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
    (CME's trade date), never a session of its own — so the completed Monday bar replaces it under the same key."""
    if local_date.weekday() >= 5:
        return local_date + timedelta(days=7 - local_date.weekday())
    return local_date


def session_close_utc(symbol: str, trade_date: date) -> datetime:
    """When the daily bar dated ``trade_date`` is final, as a UTC-naive instant (DST-correct through the exchange zone):
    NSE (``.NS``) 15:30 IST; US cash ETFs / indices 16:00 New York; COMEX / ICE futures, DXY and the FX fixings 17:00 New
    York (the Globex day's close). Wave 1c, C-DATA-21 / C-TRADER-25: a bar fetched BEFORE this instant is the in-progress
    session (``is_partial``), never a settlement — the 03:10 IST job runs 20 minutes before the winter Globex close."""
    if symbol.endswith(".NS"):
        zone, hh, mm = "Asia/Kolkata", 15, 30
    elif symbol.startswith("^") or symbol in ("GLD", "IAU", "SLV"):
        zone, hh, mm = "America/New_York", 16, 0
    else:
        zone, hh, mm = "America/New_York", 17, 0
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


def trade_dates(meta: dict[str, Any], bars: pd.DataFrame) -> pd.Series:
    """Exchange-local trade dates for chart bars. Completed bars sit on the session anchor; a trailing bar whose
    timestamp is a live quote time (``regularMarketTime``) is the in-progress session: dated by ``session_date`` so a
    Sunday-evening Globex bar lands on Monday and is replaced by the completed bar, never kept as a Sunday row."""
    tz = meta.get("exchangeTimezoneName") or "UTC"
    local = bars["ts"].dt.tz_convert(tz)
    dates = local.dt.date.copy()
    if len(local) == 0:
        return dates
    anchor = _anchor_time(meta, local)
    last_local = local.iloc[-1]
    if anchor is None or last_local.time() != anchor:
        dates.iloc[-1] = session_date(last_local.date())
    return dates.map(session_date)


def daily_bars_frame(meta: dict[str, Any], bars: pd.DataFrame, symbol: str, *, now: datetime | None = None) -> pd.DataFrame:
    """gold_daily_bars rows; the trade date is the exchange-local SESSION date of each bar (``trade_dates``); duplicates
    keep the last."""
    now = now or utcnow()
    if bars.empty:
        return pd.DataFrame()
    df = bars.copy()
    df["trade_date"] = trade_dates(meta, df)
    df = df.drop_duplicates("trade_date", keep="last")
    out = pd.DataFrame({"trade_date": df["trade_date"], "symbol": symbol, "open": df["open"], "high": df["high"], "low": df["low"],
                        "close": df["close"], "adj_close": df["close"], "volume": df["volume"].fillna(0).astype("int64"),
                        "source": "yahoo", "first_seen_at": now})
    return out


def parse_daily_csv(text: str, symbol: str, *, now: datetime | None = None) -> pd.DataFrame:
    """The G-MACRO ``yahoo_<sym>.csv`` seeds (date,open,high,low,close,volume)."""
    now = now or utcnow()
    df = pd.read_csv(io.StringIO(text))
    df = df[df["close"].notna()]
    df["trade_date"] = pd.to_datetime(df["date"]).dt.date.map(session_date)   # a weekend row is the Sunday-evening partial
    df = df.drop_duplicates("trade_date", keep="last")
    return pd.DataFrame({"trade_date": df["trade_date"], "symbol": symbol, "open": df["open"], "high": df["high"], "low": df["low"],
                         "close": df["close"], "adj_close": df["close"], "volume": df["volume"].fillna(0).astype("int64"),
                         "source": "yahoo", "first_seen_at": now})


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


def fetch_daily(store: Any, http: Any, *, symbols: Iterable[str] | None = None, backfill_from: date | None = None,
                now: datetime | None = None) -> dict[str, Any]:
    """One paced call per symbol (period1 = the day after the last stored bar − 5 days, or the backfill start)."""
    out: dict[str, Any] = {}
    for sym in (symbols or SERIES_BY_SYMBOL.keys()):
        try:
            last = last_trade_date(store, sym)
            start = backfill_from or ((last - timedelta(days=5)) if last else DAILY_START)
            resp = http.get(CHART_URL.format(symbol=sym), params=daily_params(start))
            if resp.status_code != 200:
                out[sym] = {"status": f"http_{resp.status_code}", "stale": True}
                continue
            meta, bars = parse_chart(resp.text, expect_interval="1d")
            n = ingest_daily(store, daily_bars_frame(meta, bars, sym, now=now))
            out[sym] = {"status": "ok", "rows": n, "last": str(last_trade_date(store, sym))}
        except Exception as exc:  # noqa: BLE001 — one symbol never stops the group
            out[sym] = {"status": "error", "error": str(exc)[:160], "stale": True}
            logger.warning("gold.yahoo.symbol_failed", symbol=sym)
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
    return ts_utc.replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Asia/Kolkata")).date()

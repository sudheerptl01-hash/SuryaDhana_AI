"""
Yahoo-only daily OHLCV ingestion with a data-quality gate.

Design rules
------------
1. **One source per series.** Every ticker's history comes from Yahoo v8 only.
   ICICI Breeze is used for live quotes, never for stored daily bars — its bars are
   unadjusted, and mixing them with Yahoo's split-adjusted history produced 2x-100x
   artificial jumps (e.g. HDFCBANK x2.0 on 2025-05-26).
2. **Adjustment drift triggers a full re-fetch.** Yahoo re-adjusts the *entire* past
   series after a split/bonus. Each incremental refresh re-downloads an overlap
   window; if stored and fresh closes disagree on the same dates, the stored history
   is on a stale adjustment basis and the ticker is replaced atomically.
3. **Bad bars never reach ``ohlcv``.** Spike-and-revert ticks, impossible OHLC and
   flat zero-volume placeholder bars are written to ``ohlcv_quarantine`` instead.
4. **No partial bars.** Today's bar is only stored after the NSE close has settled,
   and every refresh overwrites the overlap window, so a bar captured mid-session
   in the past is corrected on the next run.
"""
from __future__ import annotations

import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from shared.logging import get_logger

logger = get_logger(__name__)

IST = ZoneInfo("Asia/Kolkata")
SOURCE = "yahoo_v8"

# Bar is final once NSE's closing session + Yahoo's settle delay have passed.
SESSION_FINAL_IST = (16, 0)
OVERLAP_CALENDAR_DAYS = 14
# Stored-vs-fresh close disagreement that means "history was re-adjusted".
READJUST_MEDIAN_TOL = 0.005
READJUST_MAX_TOL = 0.02
# Spike detection: bar deviates > SPIKE_TOL (log) from BOTH surrounding levels,
# while the surrounding levels agree with each other within LEVEL_AGREE_TOL.
SPIKE_TOL = float(np.log(1.4))
LEVEL_AGREE_TOL = float(np.log(1.25))
SPIKE_WINDOW = 5
# Small OHLC inconsistencies (vendor rounding) are repaired; larger ones rejected.
OHLC_REPAIR_TOL = 0.02

STATUS_UPDATED = "updated"
STATUS_CURRENT = "current"
STATUS_BACKFILLED = "backfilled"
STATUS_READJUSTED = "readjusted"
STATUS_NO_DATA = "no_data"
STATUS_ERROR = "error"


# ── Quality gate ───────────────────────────────────────────────────────────────

def validate_bars(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split bars into (clean, quarantined). ``quarantined`` carries a ``reason``.

    Input columns: ticker, date, open, high, low, close, volume, adjusted_close.
    """
    if df.empty:
        return df, df.assign(reason=pd.Series(dtype=str))

    df = df.sort_values("date").reset_index(drop=True).copy()
    reason = pd.Series("", index=df.index, dtype=object)

    px = df[["open", "high", "low", "close"]]
    nonpos = (px <= 0).any(axis=1) | px.isna().any(axis=1)
    reason[nonpos] = "nonpositive_or_missing_price"

    # OHLC envelope: repair vendor rounding, reject real violations.
    body_hi = df[["open", "close"]].max(axis=1)
    body_lo = df[["open", "close"]].min(axis=1)
    envelope_gap = np.maximum(body_hi / df["high"] - 1, 1 - body_lo / df["low"])
    envelope_gap = envelope_gap.where(~nonpos, 0.0)
    bad_envelope = (envelope_gap > OHLC_REPAIR_TOL) | (df["high"] < df["low"] * (1 - OHLC_REPAIR_TOL))
    reason[(reason == "") & bad_envelope] = "ohlc_inconsistent"
    ok = reason == ""
    df.loc[ok, "high"] = np.maximum(df.loc[ok, "high"], body_hi[ok])
    df.loc[ok, "low"] = np.minimum(df.loc[ok, "low"], body_lo[ok])

    # Flat, zero-volume placeholder bars (vendor fills for no-trade / holiday days).
    flat = (df["volume"].fillna(0) == 0) & (df["high"] == df["low"]) & (df["open"] == df["close"])
    reason[(reason == "") & flat] = "flat_zero_volume_bar"

    # Spike-and-revert: compare each bar to the median level of the SPIKE_WINDOW bars
    # before and after it (computed over bars that passed the checks above). A split
    # or a genuine rally moves the "after" level too, so it is not flagged.
    for _ in range(3):
        ok = reason == ""
        logc = np.log(df.loc[ok, "close"])
        if len(logc) < 3:
            break
        before = logc.shift(1).rolling(SPIKE_WINDOW, min_periods=1).median()
        after = logc[::-1].shift(1).rolling(SPIKE_WINDOW, min_periods=1).median()[::-1]
        dev_b = (logc - before).abs()
        dev_a = (logc - after).abs()
        levels_agree = (before - after).abs() < LEVEL_AGREE_TOL
        same_side = np.sign(logc - before) == np.sign(logc - after)
        spikes = (dev_b > SPIKE_TOL) & (dev_a > SPIKE_TOL) & levels_agree & same_side
        spikes = spikes.fillna(False)
        if not spikes.any():
            break
        reason[spikes[spikes].index] = "spike_and_revert"

    bad = reason != ""
    quarantined = df[bad].assign(reason=reason[bad])
    return df[~bad].reset_index(drop=True), quarantined.reset_index(drop=True)


def _drop_unsettled_today(df: pd.DataFrame, now_ist: datetime) -> pd.DataFrame:
    if df.empty:
        return df
    settled = (now_ist.hour, now_ist.minute) >= SESSION_FINAL_IST
    if settled:
        return df
    today = now_ist.date()
    return df[pd.to_datetime(df["date"]).dt.date < today]


# ── Per-ticker refresh ─────────────────────────────────────────────────────────

@dataclass
class TickerResult:
    ticker: str
    status: str
    rows: int = 0
    quarantined: int = 0
    detail: str = ""


def _fetch_df(yf, ticker: str, start: date, end: date) -> pd.DataFrame:
    batch = yf.fetch_single(ticker, start=start, end=end)
    df = yf.to_dataframe(batch)
    if df.empty:
        return df
    df["ticker"] = ticker
    return df[["ticker", "date", "open", "high", "low", "close", "volume", "adjusted_close"]]


def _full_backfill(yf, store, ticker: str, years: int, now_ist: datetime, status: str) -> TickerResult:
    # Cover at least the configured window AND everything already stored, so a
    # re-adjustment re-download never silently truncates older history.
    start = now_ist.date() - timedelta(days=years * 365 + 10)
    earliest = store.get_earliest_ohlcv_date(ticker)
    if earliest is not None and earliest < start:
        start = earliest
    fresh = _drop_unsettled_today(_fetch_df(yf, ticker, start, now_ist.date()), now_ist)
    if fresh.empty:
        return TickerResult(ticker, STATUS_NO_DATA, detail="yahoo returned no bars")
    clean, bad = validate_bars(fresh)
    store.insert_quarantine(bad.drop(columns=["adjusted_close"], errors="ignore"), SOURCE)
    rows = store.replace_ticker_history(ticker, clean, SOURCE)
    return TickerResult(ticker, status, rows=rows, quarantined=len(bad))


def refresh_ticker(yf, store, ticker: str, years: int = 5, full: bool = False,
                   now_ist: Optional[datetime] = None) -> TickerResult:
    """Bring one ticker's stored history up to date (Yahoo only)."""
    now_ist = now_ist or datetime.now(IST)
    ticker = ticker.upper()
    try:
        latest = store.get_latest_ohlcv_date(ticker)
        foreign_rows = store.count_non_source_rows(ticker, SOURCE)
        if full or latest is None:
            return _full_backfill(yf, store, ticker, years, now_ist, STATUS_BACKFILLED)
        if foreign_rows:
            # Legacy ICICI (unadjusted) bars in this series → rebuild from one source.
            return _full_backfill(yf, store, ticker, years, now_ist, STATUS_READJUSTED)

        start = latest - timedelta(days=OVERLAP_CALENDAR_DAYS)
        fresh = _drop_unsettled_today(_fetch_df(yf, ticker, start, now_ist.date()), now_ist)
        if fresh.empty:
            return TickerResult(ticker, STATUS_NO_DATA, detail=f"no bars since {start}")

        stored = store.get_ohlcv(ticker, start=start - timedelta(days=30))
        stored["date"] = pd.to_datetime(stored["date"])
        fresh["date"] = pd.to_datetime(fresh["date"])

        overlap = fresh.merge(stored[["date", "close"]], on="date", suffixes=("", "_stored"))
        if not overlap.empty:
            rel = (overlap["close"] / overlap["close_stored"] - 1).abs()
            if rel.median() > READJUST_MEDIAN_TOL or rel.max() > READJUST_MAX_TOL:
                logger.info("Adjustment basis changed — full re-fetch", ticker=ticker,
                            median_diff=round(float(rel.median()), 4))
                return _full_backfill(yf, store, ticker, years, now_ist, STATUS_READJUSTED)

        # Validate new bars in the context of stored history so spike checks have
        # neighbours on both sides; only verdicts on fetched dates are applied.
        context = stored[stored["date"] < fresh["date"].min()].tail(SPIKE_WINDOW * 2)
        context = context[["date", "open", "high", "low", "close", "volume", "adjusted_close"]].assign(ticker=ticker)
        clean_all, bad_all = validate_bars(pd.concat([context, fresh], ignore_index=True))
        fresh_dates = set(fresh["date"])
        clean = clean_all[clean_all["date"].isin(fresh_dates)]
        bad = bad_all[bad_all["date"].isin(fresh_dates)]

        store.insert_quarantine(bad.drop(columns=["adjusted_close"], errors="ignore"), SOURCE)
        store.delete_ohlcv_dates(ticker, [d.date() for d in bad["date"]])
        rows = store.upsert_ohlcv(clean, source=SOURCE) if not clean.empty else 0
        new_dates = int((clean["date"].dt.date > latest).sum()) if not clean.empty else 0
        return TickerResult(ticker, STATUS_UPDATED if new_dates else STATUS_CURRENT,
                            rows=rows, quarantined=len(bad))
    except Exception as exc:  # one ticker must never abort a universe run
        logger.error("Ticker refresh failed", ticker=ticker, error=str(exc))
        return TickerResult(ticker, STATUS_ERROR, detail=str(exc)[:300])


# ── Universe refresh ───────────────────────────────────────────────────────────

@dataclass
class UniverseRefreshSummary:
    total: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    rows: int = 0
    quarantined: int = 0
    problems: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "total": self.total,
            "counts": self.counts,
            "rows_written": self.rows,
            "bars_quarantined": self.quarantined,
            "problems": self.problems[:200],
        }


def refresh_universe(yf, store, tickers: list[str], years: int = 5, full: bool = False,
                     workers: int = 3,
                     progress: Optional[Callable[[int, int], None]] = None) -> UniverseRefreshSummary:
    """Refresh many tickers with bounded concurrency (Yahoo rate-limit friendly)."""
    summary = UniverseRefreshSummary(total=len(tickers))
    done = 0

    def _one(t: str) -> TickerResult:
        time.sleep(random.uniform(0.2, 0.6))  # spread requests; provider handles 429 backoff
        return refresh_ticker(yf, store, t, years=years, full=full)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(_one, t) for t in tickers]
        for fut in as_completed(futures):
            r = fut.result()
            summary.counts[r.status] = summary.counts.get(r.status, 0) + 1
            summary.rows += r.rows
            summary.quarantined += r.quarantined
            if r.status in (STATUS_NO_DATA, STATUS_ERROR):
                summary.problems.append({"ticker": r.ticker, "status": r.status, "detail": r.detail})
            done += 1
            if progress:
                progress(done, len(tickers))
    return summary


# ── Market indices (macro features) ────────────────────────────────────────────

INDEX_SYMBOLS = {"NIFTY50": "^NSEI", "INDIAVIX": "^INDIAVIX"}


def refresh_indices(yf, store, years: int = 6) -> dict[str, int]:
    """Store NIFTY 50 and INDIA VIX daily closes (raw Yahoo index symbols)."""
    now_ist = datetime.now(IST)
    start = now_ist.date() - timedelta(days=years * 365 + 10)
    written: dict[str, int] = {}
    for name, symbol in INDEX_SYMBOLS.items():
        batch = yf.fetch_index(symbol, start=start, end=now_ist.date())
        df = _drop_unsettled_today(yf.to_dataframe(batch), now_ist)
        written[name] = store.upsert_index_daily(name, df, SOURCE) if not df.empty else 0
        if not written[name]:
            logger.warning("Index fetch returned no data", symbol=symbol)
    return written

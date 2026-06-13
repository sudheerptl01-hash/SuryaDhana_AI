#!/usr/bin/env python3
"""nse_historical_ingest.py -- resilient NSE EOD ingestion into DuckDB.

A production-grade, four-layer pipeline that fetches free historical market
data (~5 years) for all NSE cash-market equities and lands it in a DuckDB
analytical store, ready for 2-5 day swing-trading ML features.

Layers
------
1. RESILIENT ARCHIVE SCRAPER   -- session/cookie warm-up, UA rotation,
                                  randomized throttling, retries/backoff.
2. PROCESSING & COMPRESSION    -- in-memory zip extraction + vectorized
                                  pandas standardization to a uniform schema.
3. DUCKDB STORAGE              -- typed schema, PK, idempotent upsert,
                                  resume-from-last-date incremental loads.
4. ADJUSTMENT & FEATURES       -- corporate-action adjustment hook + a
                                  swing-trading feature/label matrix.

Data sources (NSE public archives)
----------------------------------
* sec_bhavdata_full_<DDMMYYYY>.csv  -- security-wise full bhavcopy. Carries
  OHLC, traded qty/turnover/trades AND deliverable qty/percent (a key NSE
  micro-structure alpha signal). Primary source.
* cm<DD><MON><YYYY>bhav.csv.zip / UDiFF BhavCopy zip -- standard price
  bhavcopy; used to enrich ISIN and as a fallback. Exercises the zip path.

Usage
-----
    # 5 years of all equities into ./nse_market.duckdb, then build features
    python3 nse_historical_ingest.py --build-features

    # Bounded backfill from a specific date
    python3 nse_historical_ingest.py --start 2023-01-01 --end 2023-03-31

    # Offline, no-network self-test of layers 2-4 with synthetic data
    python3 nse_historical_ingest.py --demo

NOTE ON NETWORK: NSE serves these files only to browser-like sessions and
many sandboxes (incl. Claude Code on the web) block nseindia.com via an
egress allowlist. Run locally, or add ``nseindia.com`` to the allowlist,
or use ``--demo`` to validate the processing/storage/feature layers offline.
"""

from __future__ import annotations

import argparse
import io
import logging
import random
import sys
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import requests
except ImportError:  # pragma: no cover
    sys.exit("pip install requests")
try:
    import duckdb
except ImportError:  # pragma: no cover
    sys.exit("pip install duckdb")


log = logging.getLogger("nse_ingest")

# --------------------------------------------------------------------------- #
# Canonical (lower_case) target schema shared by every source/provider.
# --------------------------------------------------------------------------- #
EOD_COLUMNS = [
    "date", "ticker", "series", "isin",
    "prev_close", "open", "high", "low", "last", "close", "vwap",
    "volume", "turnover", "trades", "deliv_qty", "deliv_pct",
    "source",
]


# =========================================================================== #
# LAYER 1 -- RESILIENT ARCHIVE SCRAPER
# =========================================================================== #
NSE_HOME = "https://www.nseindia.com"
SEC_DELIVERY_URL = NSE_HOME.replace("www", "archives") + "/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"
# Legacy PR/Bhavcopy zip (pre-Jul-2024) and UDiFF zip (post-Jul-2024).
PR_LEGACY_URL = NSE_HOME.replace("www", "archives") + "/content/historical/EQUITIES/{yyyy}/{mon}/cm{ddmonyyyy}bhav.csv.zip"
UDIFF_URL = NSE_HOME.replace("www", "archives") + "/content/cm/BhavCopy_NSE_CM_0_0_0_{yyyymmdd}_F_0000.csv.zip"

# Institutional-grade desktop browser User-Agent pool (rotated per request).
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]


class NSEArchiveSession:
    """A polite, resilient NSE archive client.

    NSE rejects non-browser clients, so we warm up a Session against the
    home page to capture cookies (nsit/nseappid/...), rotate browser headers
    on every request, throttle with randomized human-like delays, and retry
    with exponential backoff on transient failures.
    """

    def __init__(self, min_delay: float = 1.5, max_delay: float = 3.5,
                 timeout: int = 30, retries: int = 4):
        self.min_delay, self.max_delay = min_delay, max_delay
        self.timeout, self.retries = timeout, retries
        self.session = requests.Session()
        self._warm = False

    def _headers(self, referer: str | None = None) -> dict[str, str]:
        h = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        if referer:
            h["Referer"] = referer
        return h

    def warm_up(self) -> None:
        """Capture session cookies from the NSE home + reports pages."""
        if self._warm:
            return
        self.session.get(NSE_HOME, headers=self._headers(), timeout=self.timeout)
        # The reports page hands out the archive-scoped cookies.
        self.session.get(
            NSE_HOME + "/all-reports",
            headers=self._headers(referer=NSE_HOME),
            timeout=self.timeout,
        )
        self._warm = True
        log.debug("warm-up complete; %d cookies", len(self.session.cookies))

    def _sleep(self) -> None:
        time.sleep(random.uniform(self.min_delay, self.max_delay))

    def get(self, url: str) -> bytes | None:
        """GET bytes with cookie re-warm, UA rotation, retries/backoff.

        Returns None on a definitive 404 (e.g. market-holiday file absent).
        """
        self.warm_up()
        last_err: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                resp = self.session.get(
                    url, headers=self._headers(referer=NSE_HOME),
                    timeout=self.timeout,
                )
                if resp.status_code == 200:
                    return resp.content
                if resp.status_code == 404:
                    return None  # holiday / not published -> skip cleanly
                if resp.status_code in (401, 403):
                    self._warm = False         # cookie went stale
                    self.warm_up()
                last_err = RuntimeError(f"HTTP {resp.status_code}")
            except requests.RequestException as exc:
                last_err = exc
            time.sleep((2 ** attempt) + random.random())  # exp backoff + jitter
        log.warning("GET failed after %d tries: %s (%s)", self.retries, url, last_err)
        return None


# =========================================================================== #
# LAYER 2 -- DATA PROCESSING & COMPRESSION PIPELINE
# =========================================================================== #
def _to_num(series: pd.Series) -> pd.Series:
    """Vectorized numeric coercion; NSE uses ' - ' for null delivery cells."""
    return pd.to_numeric(
        series.astype(str).str.replace(",", "", regex=False).str.strip(),
        errors="coerce",
    )


def parse_sec_delivery(raw: bytes, trade_date: date) -> pd.DataFrame:
    """Standardize the security-wise full bhavcopy (OHLC + delivery)."""
    df = pd.read_csv(io.BytesIO(raw))
    df.columns = [c.strip().upper() for c in df.columns]  # NSE pads headers
    df = df[df["SERIES"].astype(str).str.strip().isin(["EQ", "BE", "BZ", "SM", "ST"])].copy()

    out = pd.DataFrame({
        "date": pd.Timestamp(trade_date).normalize(),
        "ticker": df["SYMBOL"].astype(str).str.strip(),
        "series": df["SERIES"].astype(str).str.strip(),
        "isin": pd.NA,
        "prev_close": _to_num(df["PREV_CLOSE"]),
        "open": _to_num(df["OPEN_PRICE"]),
        "high": _to_num(df["HIGH_PRICE"]),
        "low": _to_num(df["LOW_PRICE"]),
        "last": _to_num(df["LAST_PRICE"]),
        "close": _to_num(df["CLOSE_PRICE"]),
        "vwap": _to_num(df["AVG_PRICE"]),
        "volume": _to_num(df["TTL_TRD_QNTY"]),
        "turnover": _to_num(df["TURNOVER_LACS"]) * 1e5,  # lacs -> rupees
        "trades": _to_num(df["NO_OF_TRADES"]),
        "deliv_qty": _to_num(df["DELIV_QTY"]),
        "deliv_pct": _to_num(df["DELIV_PER"]),
        "source": "sec_delivery",
    })
    return _finalize(out)


def parse_pr_zip(raw: bytes, trade_date: date) -> pd.DataFrame:
    """Extract the price bhavcopy CSV in-memory from its zip and standardize.

    Handles both the legacy cmDDMONYYYYbhav.csv layout and the newer UDiFF
    BhavCopy layout. Primarily used to enrich ISIN.
    """
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        csv_name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        with zf.open(csv_name) as fh:
            df = pd.read_csv(fh)
    df.columns = [c.strip().upper() for c in df.columns]

    if "TOTTRDQTY" in df.columns:        # legacy layout
        m = {"OPEN": "open", "HIGH": "high", "LOW": "low", "CLOSE": "close",
             "LAST": "last", "PREVCLOSE": "prev_close", "TOTTRDQTY": "volume",
             "TOTTRDVAL": "turnover", "TOTALTRADES": "trades"}
        df = df[df["SERIES"].astype(str).str.strip().isin(["EQ", "BE", "BZ", "SM", "ST"])].copy()
        out = pd.DataFrame({"date": pd.Timestamp(trade_date).normalize(),
                            "ticker": df["SYMBOL"].astype(str).str.strip(),
                            "series": df["SERIES"].astype(str).str.strip(),
                            "isin": df.get("ISIN", pd.NA)})
        for src, dst in m.items():
            out[dst] = _to_num(df[src]) if src in df.columns else np.nan
    else:                                 # UDiFF layout
        df = df[df["SctySrs"].astype(str).str.strip().isin(["EQ", "BE", "BZ", "SM", "ST"])].copy() \
            if "SctySrs" in df.columns else df
        out = pd.DataFrame({"date": pd.Timestamp(trade_date).normalize(),
                            "ticker": df.get("TckrSymb", df.get("SYMBOL")).astype(str).str.strip(),
                            "series": df.get("SctySrs", "EQ"),
                            "isin": df.get("ISIN", pd.NA),
                            "prev_close": _to_num(df.get("PrvsClsgPric")),
                            "open": _to_num(df.get("OpnPric")),
                            "high": _to_num(df.get("HghPric")),
                            "low": _to_num(df.get("LwPric")),
                            "last": _to_num(df.get("LastPric")),
                            "close": _to_num(df.get("ClsPric")),
                            "volume": _to_num(df.get("TtlTradgVol")),
                            "turnover": _to_num(df.get("TtlTrfVal")),
                            "trades": _to_num(df.get("TtlNbOfTxsExctd"))})
    out["vwap"] = out.get("vwap", np.nan)
    out["deliv_qty"] = np.nan
    out["deliv_pct"] = np.nan
    out["source"] = "pr_bhavcopy"
    return _finalize(out)


def _finalize(out: pd.DataFrame) -> pd.DataFrame:
    """Guarantee column set/order/dtypes and drop unusable rows."""
    for col in EOD_COLUMNS:
        if col not in out.columns:
            out[col] = np.nan
    out = out[EOD_COLUMNS]
    out = out[out["close"].notna() & (out["ticker"].astype(str).str.len() > 0)]
    out = out.drop_duplicates(subset=["date", "ticker", "series"], keep="last")
    return out.reset_index(drop=True)


def merge_sources(primary: pd.DataFrame, enrich: pd.DataFrame | None) -> pd.DataFrame:
    """Left-merge ISIN (and any missing OHLC) from the price bhavcopy."""
    if enrich is None or enrich.empty:
        return primary
    keys = ["date", "ticker", "series"]
    isin_map = enrich[keys + ["isin"]].dropna(subset=["isin"])
    merged = primary.merge(isin_map, on=keys, how="left", suffixes=("", "_pr"))
    merged["isin"] = merged["isin"].fillna(merged.pop("isin_pr"))
    return merged[EOD_COLUMNS]


# =========================================================================== #
# LAYER 3 -- DUCKDB STORAGE (typed schema, PK, idempotent upsert, resume)
# =========================================================================== #
class DuckDBStore:
    def __init__(self, path: str):
        self.con = duckdb.connect(path)
        self._init_schema()

    def _init_schema(self) -> None:
        self.con.execute(
            """
            CREATE TABLE IF NOT EXISTS equity_eod (
                date       DATE        NOT NULL,
                ticker     VARCHAR     NOT NULL,
                series     VARCHAR     NOT NULL,
                isin       VARCHAR,
                prev_close DOUBLE, open DOUBLE, high DOUBLE, low DOUBLE,
                last DOUBLE, close DOUBLE, vwap DOUBLE,
                volume     BIGINT, turnover DOUBLE, trades BIGINT,
                deliv_qty  BIGINT, deliv_pct DOUBLE,
                source     VARCHAR,
                loaded_at  TIMESTAMP   DEFAULT now(),
                PRIMARY KEY (date, ticker, series)
            );
            """
        )

    def last_date(self) -> date | None:
        row = self.con.execute("SELECT max(date) FROM equity_eod").fetchone()
        return row[0] if row and row[0] is not None else None

    def has_date(self, d: date) -> bool:
        n = self.con.execute(
            "SELECT count(*) FROM equity_eod WHERE date = ?", [d]
        ).fetchone()[0]
        return n > 0

    def upsert(self, df: pd.DataFrame) -> int:
        """Idempotent insert: re-running a day overwrites, never duplicates."""
        if df.empty:
            return 0
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"]).dt.date
        for c in ("volume", "trades", "deliv_qty"):
            df[c] = df[c].round().astype("Int64")
        self.con.register("staging_df", df)
        self.con.execute(
            f"""
            INSERT INTO equity_eod ({','.join(EOD_COLUMNS)})
            SELECT {','.join(EOD_COLUMNS)} FROM staging_df
            ON CONFLICT (date, ticker, series) DO UPDATE SET
                isin=excluded.isin, prev_close=excluded.prev_close,
                open=excluded.open, high=excluded.high, low=excluded.low,
                last=excluded.last, close=excluded.close, vwap=excluded.vwap,
                volume=excluded.volume, turnover=excluded.turnover,
                trades=excluded.trades, deliv_qty=excluded.deliv_qty,
                deliv_pct=excluded.deliv_pct, source=excluded.source;
            """
        )
        self.con.unregister("staging_df")
        return len(df)

    def close(self) -> None:
        self.con.close()


# =========================================================================== #
# LAYER 4 -- ADJUSTMENT & SWING-TRADING FEATURE ENGINEERING
# =========================================================================== #
def apply_corporate_actions(df: pd.DataFrame, ca_csv: str | None) -> pd.DataFrame:
    """Back-adjust OHLC for splits/bonuses using a corporate-actions feed.

    NSE bhavcopy prices are RAW (not adjusted). Supply a CSV with columns
    [ticker, ex_date, ratio] where ``ratio`` is the multiplicative price
    factor on/after ex-date (e.g. a 1:2 split -> 0.5; a 1:1 bonus -> 0.5).
    Without a feed we return prices unadjusted and flag it, rather than
    silently fabricating an adjustment.
    """
    if not ca_csv:
        log.warning("No corporate-actions feed: prices are UNADJUSTED.")
        df["adj_factor"] = 1.0
        return df

    ca = pd.read_csv(ca_csv, parse_dates=["ex_date"])
    df = df.sort_values(["ticker", "date"]).copy()
    df["adj_factor"] = 1.0
    for tkr, grp in ca.groupby("ticker"):
        for _, ev in grp.iterrows():
            mask = (df["ticker"] == tkr) & (df["date"] < ev["ex_date"].date())
            df.loc[mask, "adj_factor"] *= float(ev["ratio"])
    for col in ("open", "high", "low", "close", "prev_close", "vwap"):
        df[f"adj_{col}"] = df[col] * df["adj_factor"]
    return df


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _true_range(df: pd.DataFrame, grp: pd.Series) -> pd.Series:
    """Vectorized True Range using a per-ticker previous close."""
    prev_close = df["close"].groupby(grp).shift(1)
    return pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)


def build_features(con: duckdb.DuckDBPyConnection,
                   horizons: tuple[int, ...] = (2, 3, 5)) -> int:
    """Compute a per-(ticker, date) swing-trading feature & label matrix.

    Features target 2-5 day holds: trend (SMA/EMA distance), momentum,
    mean-reversion (RSI, %B-style range position), volatility (ATR%, rolling
    sigma), liquidity/micro-structure (volume & delivery z-scores -- the NSE
    delivery signal), and gaps. Labels are forward returns over each horizon
    plus a binary up/down target.
    """
    df = con.execute(
        "SELECT date,ticker,open,high,low,close,volume,turnover,deliv_pct "
        "FROM equity_eod WHERE series IN ('EQ','BE') ORDER BY ticker, date"
    ).df()
    if df.empty:
        log.warning("No rows to build features from.")
        return 0

    df["date"] = pd.to_datetime(df["date"])
    g = df.groupby("ticker", group_keys=False)

    df["ret_1d"] = g["close"].pct_change()
    df["log_ret_1d"] = np.log(df["close"] / g["close"].shift(1))
    df["gap_pct"] = (df["open"] - g["close"].shift(1)) / g["close"].shift(1)
    df["range_pct"] = (df["high"] - df["low"]) / df["close"]
    df["close_pos_in_range"] = (df["close"] - df["low"]) / (df["high"] - df["low"]).replace(0, np.nan)

    for w in (5, 10, 20, 50):
        df[f"sma_{w}"] = g["close"].transform(lambda s, w=w: s.rolling(w).mean())
        df[f"dist_sma_{w}"] = df["close"] / df[f"sma_{w}"] - 1
    df["ema_12"] = g["close"].transform(lambda s: s.ewm(span=12, adjust=False).mean())
    df["ema_26"] = g["close"].transform(lambda s: s.ewm(span=26, adjust=False).mean())
    df["macd"] = df["ema_12"] - df["ema_26"]

    for w in (5, 10, 20):
        df[f"mom_{w}"] = g["close"].transform(lambda s, w=w: s / s.shift(w) - 1)
        df[f"vol_{w}"] = g["ret_1d"].transform(lambda s, w=w: s.rolling(w).std())

    df["rsi_14"] = g["close"].transform(lambda s: _rsi(s, 14))
    tr = _true_range(df, df["ticker"])
    df["atr_14"] = tr.groupby(df["ticker"]).transform(
        lambda s: s.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean())
    df["atr_pct"] = df["atr_14"] / df["close"]

    avg_vol_20 = g["volume"].transform(lambda s: s.rolling(20).mean())
    std_vol_20 = g["volume"].transform(lambda s: s.rolling(20).std())
    df["vol_ratio_20"] = df["volume"] / avg_vol_20
    df["vol_z_20"] = (df["volume"] - avg_vol_20) / std_vol_20
    df["deliv_pct_sma_20"] = g["deliv_pct"].transform(lambda s: s.rolling(20).mean())
    df["deliv_pct_z_20"] = (
        (df["deliv_pct"] - df["deliv_pct_sma_20"])
        / g["deliv_pct"].transform(lambda s: s.rolling(20).std())
    )

    hi_252 = g["high"].transform(lambda s: s.rolling(252, min_periods=20).max())
    lo_252 = g["low"].transform(lambda s: s.rolling(252, min_periods=20).min())
    df["dist_52w_high"] = df["close"] / hi_252 - 1
    df["dist_52w_low"] = df["close"] / lo_252 - 1

    # Forward-looking labels (shift -h within each ticker).
    for h in horizons:
        fwd = g["close"].transform(lambda s, h=h: s.shift(-h) / s - 1)
        df[f"fwd_ret_{h}d"] = fwd
        df[f"label_up_{h}d"] = (fwd > 0).astype("Int8")

    con.register("feat_df", df)
    con.execute("CREATE OR REPLACE TABLE equity_features AS SELECT * FROM feat_df")
    con.unregister("feat_df")
    return len(df)


# =========================================================================== #
# DATE / ORCHESTRATION HELPERS
# =========================================================================== #
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
          "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def trading_days(start: date, end: date) -> list[date]:
    """Weekdays in [start, end]. Holiday files simply 404 and are skipped."""
    days, d = [], start
    while d <= end:
        if d.weekday() < 5:  # Mon-Fri
            days.append(d)
        d += timedelta(days=1)
    return days


def fetch_day(sess: NSEArchiveSession, d: date, use_pr: bool) -> pd.DataFrame | None:
    """Layer 1+2 for a single trading day -> standardized, merged frame."""
    sec_raw = sess.get(SEC_DELIVERY_URL.format(ddmmyyyy=d.strftime("%d%m%Y")))
    if sec_raw is None:
        return None  # holiday / not yet published
    primary = parse_sec_delivery(sec_raw, d)

    enrich = None
    if use_pr:
        pr_raw = sess.get(PR_LEGACY_URL.format(
            yyyy=d.year, mon=MONTHS[d.month - 1],
            ddmonyyyy=d.strftime("%d") + MONTHS[d.month - 1] + str(d.year)))
        if pr_raw is None:
            pr_raw = sess.get(UDIFF_URL.format(yyyymmdd=d.strftime("%Y%m%d")))
        if pr_raw is not None:
            try:
                enrich = parse_pr_zip(pr_raw, d)
            except Exception as exc:  # noqa: BLE001
                log.debug("PR parse failed for %s: %s", d, exc)
    return merge_sources(primary, enrich)


def run_ingest(args: argparse.Namespace) -> None:
    store = DuckDBStore(args.db)
    start = datetime.strptime(args.start, "%Y-%m-%d").date() if args.start \
        else date.today() - timedelta(days=365 * 5)
    end = datetime.strptime(args.end, "%Y-%m-%d").date() if args.end else date.today()

    # Resume: skip everything already loaded unless --rebuild.
    last = store.last_date()
    if last and not args.rebuild and last >= start:
        start = last + timedelta(days=1)
        log.info("Resuming: last loaded date is %s; starting at %s", last, start)

    days = trading_days(start, end)
    if not days:
        log.info("Nothing to ingest for the requested window.")
    else:
        sess = NSEArchiveSession(min_delay=args.min_delay, max_delay=args.max_delay)
        log.info("Ingesting %d candidate trading days (%s .. %s)", len(days), start, end)
        total = 0
        for i, d in enumerate(days, 1):
            if not args.rebuild and store.has_date(d):
                continue
            df = fetch_day(sess, d, use_pr=not args.no_pr)
            if df is not None and not df.empty:
                total += store.upsert(df)
                log.info("[%d/%d] %s -> %d rows (cumulative %d)", i, len(days), d, len(df), total)
            else:
                log.info("[%d/%d] %s -> no file (holiday/unpublished)", i, len(days), d)
            sess._sleep()  # randomized 1.5-3.5s throttle between days
        log.info("Ingest complete: %d rows upserted.", total)

    if args.build_features:
        n = build_features(store.con)
        log.info("Built equity_features: %d rows.", n)
    store.close()


# =========================================================================== #
# OFFLINE DEMO -- exercises layers 2-4 (and the parsers) without network
# =========================================================================== #
def _synth_sec_csv(d: date, tickers: list[str], rng: np.random.Generator,
                   state: dict[str, float]) -> bytes:
    rows = []
    for t in tickers:
        prev = state[t]
        op = prev * (1 + rng.normal(0, 0.01))
        hi = op * (1 + abs(rng.normal(0, 0.012)))
        lo = op * (1 - abs(rng.normal(0, 0.012)))
        cl = rng.uniform(lo, hi)
        state[t] = cl
        vol = int(rng.uniform(1e5, 5e6))
        deliv = int(vol * rng.uniform(0.2, 0.8))
        rows.append({
            "SYMBOL": t, " SERIES": "EQ", " DATE1": d.strftime("%d-%b-%Y"),
            " PREV_CLOSE": round(prev, 2), " OPEN_PRICE": round(op, 2),
            " HIGH_PRICE": round(hi, 2), " LOW_PRICE": round(lo, 2),
            " LAST_PRICE": round(cl, 2), " CLOSE_PRICE": round(cl, 2),
            " AVG_PRICE": round((hi + lo + cl) / 3, 2),
            " TTL_TRD_QNTY": vol, " TURNOVER_LACS": round(vol * cl / 1e5, 2),
            " NO_OF_TRADES": int(vol / 100), " DELIV_QTY": deliv,
            " DELIV_PER": round(100 * deliv / vol, 2),
        })
    return pd.DataFrame(rows).to_csv(index=False).encode()


def _synth_pr_zip(d: date, tickers: list[str]) -> bytes:
    df = pd.DataFrame({
        "SYMBOL": tickers, "SERIES": "EQ",
        "OPEN": 100.0, "HIGH": 101.0, "LOW": 99.0, "CLOSE": 100.5,
        "LAST": 100.5, "PREVCLOSE": 100.0, "TOTTRDQTY": 1000,
        "TOTTRDVAL": 100500.0, "TIMESTAMP": d.strftime("%d-%b-%Y"),
        "TOTALTRADES": 50,
        "ISIN": ["INE" + f"{i:09d}" for i in range(len(tickers))],
    })
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"cm{d:%d%b%Y}bhav.csv".upper(), df.to_csv(index=False))
    return buf.getvalue()


def run_demo(args: argparse.Namespace) -> None:
    print(">> OFFLINE DEMO: synthetic bhavcopies through layers 2-4 "
          "(no network).\n")
    rng = np.random.default_rng(7)
    tickers = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ITC"]
    state = {t: float(rng.uniform(100, 3000)) for t in tickers}
    store = DuckDBStore(":memory:")

    # ~90 weekdays so 50-day / momentum windows populate.
    days = trading_days(date(2024, 1, 1), date(2024, 5, 31))
    total = 0
    for d in days:
        sec = parse_sec_delivery(_synth_sec_csv(d, tickers, rng, state), d)   # Layer 2
        pr = parse_pr_zip(_synth_pr_zip(d, tickers), d)                       # Layer 2 (zip)
        total += store.upsert(merge_sources(sec, pr))                        # Layer 3
    print(f"Layer 2+3: upserted {total} EOD rows across {len(days)} days, "
          f"{len(tickers)} tickers.")

    # Idempotency check: re-upsert one day, row count must not grow.
    before = store.con.execute("SELECT count(*) FROM equity_eod").fetchone()[0]
    d0 = days[0]
    store.upsert(merge_sources(parse_sec_delivery(_synth_sec_csv(d0, tickers, rng, dict(state)), d0), None))
    after = store.con.execute("SELECT count(*) FROM equity_eod").fetchone()[0]
    print(f"Idempotent upsert check: {before} -> {after} rows "
          f"({'OK, no duplicates' if before == after else 'FAILED'}).")

    n = build_features(store.con)                                            # Layer 4
    print(f"Layer 4: built {n} feature rows.\n")

    print("Sample equity_eod (with ISIN merged from PR zip):")
    print(store.con.execute(
        "SELECT date,ticker,series,isin,open,high,low,close,volume,deliv_pct "
        "FROM equity_eod WHERE ticker='RELIANCE' ORDER BY date LIMIT 5"
    ).df().to_string(index=False))

    print("\nSample equity_features (swing signals + 2-5d labels):")
    print(store.con.execute(
        "SELECT date,ticker,round(close,1) px,round(rsi_14,1) rsi_14,"
        "round(atr_pct,4) atr_pct,round(dist_sma_20,4) dist_sma20,"
        "round(vol_z_20,2) vol_z,round(deliv_pct_z_20,2) deliv_z,"
        "round(fwd_ret_3d,4) fwd_ret_3d,label_up_3d "
        "FROM equity_features WHERE ticker='RELIANCE' "
        "AND rsi_14 IS NOT NULL ORDER BY date LIMIT 8"
    ).df().to_string(index=False))

    print("\nFeature columns produced:")
    cols = store.con.execute("PRAGMA table_info('equity_features')").df()["name"].tolist()
    print(", ".join(cols))
    store.close()


# =========================================================================== #
# CLI
# =========================================================================== #
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default="nse_market.duckdb", help="DuckDB file path")
    p.add_argument("--start", help="Backfill start date YYYY-MM-DD (default: ~5y ago)")
    p.add_argument("--end", help="Backfill end date YYYY-MM-DD (default: today)")
    p.add_argument("--no-pr", action="store_true", help="Skip the price-bhavcopy ISIN enrichment")
    p.add_argument("--rebuild", action="store_true", help="Re-ingest even already-loaded days")
    p.add_argument("--build-features", action="store_true", help="Build equity_features after ingest")
    p.add_argument("--min-delay", type=float, default=1.5, help="Min inter-request delay (s)")
    p.add_argument("--max-delay", type=float, default=3.5, help="Max inter-request delay (s)")
    p.add_argument("--demo", action="store_true", help="Offline synthetic self-test of layers 2-4")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    if args.demo:
        run_demo(args)
    else:
        run_ingest(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

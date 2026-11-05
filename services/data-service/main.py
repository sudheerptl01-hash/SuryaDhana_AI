from __future__ import annotations

import os
import re
import sys
import asyncio
import json
import threading
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, AsyncGenerator

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, status, BackgroundTasks, Query
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.config import load_env_into_process, Settings, get_settings

# Local runs: export .env so os.environ readers (ICICI creds, service URLs) see it.
load_env_into_process()
from shared.http_guard import install_http_guard
from shared.metrics import install_observability
from shared.icici import load_icici_credentials
from shared.logging import configure_logging, get_logger
from shared.models import OHLCVBatch

from providers import DirectYahooProvider, build_live_provider, LiveDataProvider

# ── ICICI Breeze call budget ─────────────────────────────────────────────────────────────────────────────────────
# Breeze caps API calls per day ("Limit exceed: API call per day", seen 12 Oct 2026). The live pollers used to call
# it every 5 s around the clock, which exhausted the quota by the afternoon and broke every ICICI feature (holdings,
# funds, MCX bars) for the rest of the day. Poll only in market hours, at NIFTY_POLL_INTERVAL (default 15 s), and stop
# calling Breeze until midnight IST once the daily limit is hit.
_BREEZE_LIMIT: dict[str, float] = {"until": 0.0}


def _ist_now():
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo
    return _dt.now(ZoneInfo("Asia/Kolkata"))


def _in_session() -> bool:
    n = _ist_now()
    return n.weekday() < 5 and (9, 0) <= (n.hour, n.minute) <= (15, 35)


def _breeze_blocked() -> bool:
    return time.time() < _BREEZE_LIMIT["until"]


def _note_breeze_error(exc: Exception) -> None:
    """A daily-limit error blocks Breeze calls from this process until the next midnight IST."""
    if "limit exceed" in str(exc).lower():
        from datetime import timedelta as _td
        n = _ist_now()
        midnight = (n + _td(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
        _BREEZE_LIMIT["until"] = time.time() + (midnight - n).total_seconds()

from storage import DuckDBStore
import ingest
from instruments import classify_universe
from jobs import JobManager
import live_ticks as live_ticks_mod
from eod_steps import run_steps as run_eod_steps  # EOD step isolation (15 Oct incident)
import tick_store as tick_store_mod
import fo_analytics                           # W2 (DERV): F&O analytics

logger = get_logger(__name__)

_store: DuckDBStore | None = None
_yfinance: DirectYahooProvider | None = None
_live: LiveDataProvider | None = None
_jobs = JobManager()


def _data_dir(settings: Settings) -> Path:
    return Path(settings.duckdb_path).resolve().parent


def _universe_path(settings: Settings) -> Path:
    """Configured universe CSV, falling back to the locked NSE_1500 list."""
    configured = Path(settings.stock_universe_path)
    if not configured.is_absolute():
        configured = _data_dir(settings).parent / configured
    if configured.exists():
        return configured
    fallback = _data_dir(settings) / "NSE_1500.csv"
    logger.warning("STOCK_UNIVERSE_PATH missing — using fallback",
                   configured=str(configured), fallback=str(fallback))
    return fallback


def _universe_tickers(settings: Settings) -> list[str]:
    df = pd.read_csv(_universe_path(settings))
    return sorted(df["ticker"].astype(str).str.strip().str.upper().unique().tolist())


def _classify_instruments(store: DuckDBStore, settings: Settings) -> dict:
    df = classify_universe(_universe_tickers(settings), _data_dir(settings) / "reference")
    store.replace_instruments(df)
    return {k: int(v) for k, v in df["instrument_type"].value_counts().items()}


def _register_stack_dump_signal() -> None:
    """R-OPS-07: ``kill -USR1 <pid>`` writes every Python thread's stack to stderr (.logs/data-service.log). A C-level
    handler, so it works while the event loop is stuck. scripts/stack_watchdog.sh sends USR1 before a hang restart,
    but only once it finds the JSON line below in the log since the last start (with no handler, USR1 kills)."""
    import faulthandler
    import signal

    try:
        faulthandler.register(signal.SIGUSR1, file=sys.stderr, all_threads=True, chain=False)
    except (AttributeError, RuntimeError, ValueError, OSError):
        return
    print(json.dumps({"event": "stack_dump_ready", "stack_dump_signal": "SIGUSR1", "pid": os.getpid()}),
          file=sys.stderr, flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _store, _yfinance, _live
    settings = get_settings()
    configure_logging("data-service", settings.log_level)
    _register_stack_dump_signal()
    _store = DuckDBStore(settings.duckdb_path)
    if _store._read_only:
        logger.error("DuckDB opened READ-ONLY (another process holds the write lock) — "
                     "all ingestion will fail; /ready reports 503 until restarted")
    else:
        try:
            fixed = _store.fix_future_insider_dates()
            if fixed:
                logger.info("Fixed future-dated insider rows", rows=fixed)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Insider date fix skipped", error=str(exc))
        try:
            counts = _classify_instruments(_store, settings)
            logger.info("Instruments classified", **{k.lower(): v for k, v in counts.items()})
        except Exception as exc:
            logger.error("Instrument classification failed — ETF filtering disabled", error=str(exc))
    _yfinance = DirectYahooProvider()
    # Auto-connect Breeze from .env (single source of truth via shared loader) —
    # normalizes the daily session token (accepts bare token or pasted redirect URL).
    _creds = load_icici_credentials()
    _live = build_live_provider(_creds.api_key, _creds.api_secret, _creds.session_token)

    # Breeze connect is a blocking network call that can hang; run it in a
    # background thread so startup/health never waits on the broker. Pollers gate
    # on _live.is_connected() and HTTP handlers fall back to yfinance meanwhile.
    async def _bg_live_connect() -> None:
        try:
            await asyncio.to_thread(_live.connect)
            if _live.is_connected():
                logger.info("ICICI Breeze connected (auto from .env, background)",
                            provider=type(_live).__name__)
            else:
                logger.warning("No live broker connected — ICICI credentials missing; "
                               "live quotes disabled (daily history is Yahoo and unaffected)",
                               provider=type(_live).__name__)
        except Exception as e:
            if _creds.needs_daily_token:
                logger.warning("ICICI Breeze: api key/secret set but session token missing/expired — "
                               "refresh ICICI_SESSION_TOKEN in .env (daily). Using yfinance fallback.")
            else:
                logger.warning(f"ICICI Breeze connection failed: {e}. Continuing with yfinance only.")

    _live_connect_task = asyncio.create_task(_bg_live_connect())

    # Live L1 ticks (Bloomberg program B3): lazy, kill-switched (LIVE_TICKS, default OFF).
    # Borrows the provider's Breeze session; one worker thread; see live_ticks.py.
    live_ticks_mod.init(get_live_provider, prev_close_fn=_prev_close_for, holdings_fn=_holdings_symbols)

    # Warm the Market Monitor cache (≈ 5 s cold) off the event loop so the first BRIEF / MKT visit is instant.
    def _warm_monitor() -> None:
        try:
            market_monitor_snapshot(_store)
        except Exception as exc:  # noqa: BLE001 — a cold cache is only slower, never broken
            logger.warning("Market monitor warm-up failed", error=str(exc))
    if not _store._read_only:
        threading.Thread(target=_warm_monitor, name="monitor-warmup", daemon=True).start()
        threading.Thread(target=lambda: _refresh_option_history(), name="option-history", daemon=True).start()

    # Start background NIFTY poller task
    _nifty_task: asyncio.Task | None = None
    _watchlist_task: asyncio.Task | None = None

    async def _nifty_poller():
        candidates = ["NIFTY", "NIFTY50", "NSEI", "^NSEI", "NIFTY.NS"]
        redis_url = os.environ.get("REDIS_URL")

        # ── Redis client setup ────────────────────────────────────────────────
        redis_client = None
        if redis_url:
            try:
                import redis as _redis
                redis_client = _redis.from_url(redis_url, socket_connect_timeout=3)
                # Eagerly ping so we know it's reachable before the first tick
                redis_client.ping()
                logger.info("NIFTY poller: Redis connected", url=redis_url)
            except Exception as exc:
                logger.warning("NIFTY poller: Redis unavailable — live quotes won't stream", error=str(exc))
                redis_client = None
        else:
            logger.warning("NIFTY poller: REDIS_URL not set — live quotes won't stream")

        tick_count = 0
        interval = float(os.environ.get("NIFTY_POLL_INTERVAL", "15"))
        working: str | None = None          # the alias that answered last time: try only that one
        while True:
            try:
                if not _live or not _live.is_connected() or not _in_session() or _breeze_blocked():
                    await asyncio.sleep(30)
                    continue

                # ── Fetch quote (synchronous I/O → thread pool) ───────────────
                quote = None
                symbol = None
                # LV-DATA: while the websocket carries NIFTY 50 (a tick <= 5 s old) publish that tick in the REST quote's
                # shape instead of calling get_quotes: zero Breeze REST calls (L-INVENTORY: ~1,580 calls/day, 32 % of quota).
                _lt = live_ticks_mod.instance()
                _t = _lt.snapshot(["NIFTY 50"]).get("NIFTY 50") if _lt is not None else None
                if _t and _t.get("ts_age_s") is not None and _t["ts_age_s"] <= live_ticks_mod.FRESH_S:
                    quote = {"exchange_code": "NSE", "stock_code": "NIFTY", "ltp": _t["price"], "open": _t.get("open"),
                             "high": _t.get("high"), "low": _t.get("low"), "previous_close": _t.get("prev_close"),
                             "ltp_percent_change": _t.get("chg_pct"), "ltt": _t.get("ltt"), "source": "breeze_ws"}
                    symbol = working or "NIFTY"
                for cand in ([] if quote is not None else [working] if working else candidates):
                    try:
                        q = await asyncio.to_thread(_live.get_live_quote, cand)
                        if q:
                            quote = q
                            symbol = working = cand
                            break
                    except Exception as exc:
                        _note_breeze_error(exc)
                        if _breeze_blocked():
                            logger.warning("NIFTY poller: ICICI daily API limit reached, pausing until midnight IST")
                            break
                        continue

                if quote is not None and symbol is not None:
                    ts = quote.get("timestamp") or time.time()
                    payload = json.dumps(quote, default=str)

                    # ── Persist to DuckDB (non-blocking) ─────────────────────
                    try:
                        await asyncio.to_thread(_store.upsert_live_quote, symbol, ts, payload)
                    except Exception as exc:
                        logger.warning("NIFTY poller: DuckDB write failed", error=str(exc))

                    # ── Publish to Redis regardless of DuckDB result ──────────
                    if redis_client is not None:
                        msg = json.dumps(
                            {"symbol": symbol, "ts": ts, "payload": quote},
                            default=str,
                        )
                        try:
                            await asyncio.to_thread(redis_client.publish, "live.quotes", msg)
                            tick_count += 1
                            if tick_count % 12 == 1:  # log every ~1 min
                                logger.info(
                                    "NIFTY tick published",
                                    symbol=symbol,
                                    tick=tick_count,
                                    price=quote.get("last_price") or quote.get("ltp"),
                                )
                        except Exception as exc:
                            logger.warning("NIFTY poller: Redis publish failed", error=str(exc))
                            # Try to reconnect on next iteration
                            try:
                                redis_client.ping()
                            except Exception:
                                logger.warning("NIFTY poller: Redis connection lost — reconnecting")
                                try:
                                    redis_client = _redis.from_url(redis_url, socket_connect_timeout=3)
                                    redis_client.ping()
                                except Exception:
                                    redis_client = None

            except Exception as exc:
                logger.warning("NIFTY poller error", error=str(exc))
            await asyncio.sleep(interval)

    async def _watchlist_poller() -> None:
        """
        Stream live quotes for user-watched symbols.

        The UI registers starred tickers in the Redis set ``monitored.stocks``
        (via ui-api ``/monitor/subscribe``). Nothing else produces live quotes for
        those symbols, so without this poller the watchlist CMP column never ticks —
        the browser is subscribed to ``live.quotes`` but only NIFTY is ever published.

        Each cycle: read the monitored set, fetch quotes from ICICI Breeze with
        bounded concurrency (to respect API rate limits), persist to DuckDB, and
        publish each tick to ``live.quotes`` in the exact shape the ui-api monitor
        WebSocket forwards to the browser: ``{"symbol", "ts", "payload": {...}}``.
        """
        interval    = float(os.environ.get("WATCHLIST_POLL_INTERVAL", "15"))
        concurrency = int(os.environ.get("WATCHLIST_POLL_CONCURRENCY", "4"))
        max_symbols = int(os.environ.get("WATCHLIST_POLL_MAX_SYMBOLS", "50"))
        sem = asyncio.Semaphore(concurrency)

        redis_url = os.environ.get("REDIS_URL")
        redis_client = None
        if redis_url:
            try:
                import redis as _redis
                redis_client = _redis.from_url(redis_url, socket_connect_timeout=3)
                redis_client.ping()
                logger.info("Watchlist poller: Redis connected", url=redis_url)
            except Exception as exc:
                logger.warning("Watchlist poller: Redis unavailable — watchlist quotes won't stream", error=str(exc))
                redis_client = None
        else:
            logger.warning("Watchlist poller: REDIS_URL not set — watchlist quotes won't stream")

        async def _poll_one(sym: str) -> None:
            async with sem:
                try:
                    quote = await asyncio.to_thread(_live.get_live_quote, sym)
                except Exception as exc:
                    _note_breeze_error(exc)
                    logger.debug("Watchlist poller: quote fetch failed", symbol=sym, error=str(exc))
                    return
                if not quote:
                    return
                ts = quote.get("timestamp") or time.time()
                # DuckDB persistence is best-effort — streaming must not block on it.
                try:
                    await asyncio.to_thread(_store.upsert_live_quote, sym, ts, json.dumps(quote, default=str))
                except Exception:
                    pass
                msg = json.dumps({"symbol": sym, "ts": ts, "payload": quote}, default=str)
                try:
                    await asyncio.to_thread(redis_client.publish, "live.quotes", msg)
                except Exception as exc:
                    logger.warning("Watchlist poller: Redis publish failed", symbol=sym, error=str(exc))

        tick = 0
        while True:
            try:
                if not _live or not _live.is_connected() or redis_client is None or not _in_session() or _breeze_blocked():
                    await asyncio.sleep(max(interval, 30))
                    continue

                try:
                    members = await asyncio.to_thread(redis_client.smembers, "monitored.stocks")
                except Exception as exc:
                    logger.warning("Watchlist poller: failed reading monitored.stocks", error=str(exc))
                    members = set()

                symbols = [
                    (m.decode() if isinstance(m, (bytes, bytearray)) else str(m)).upper()
                    for m in (members or set())
                ]
                # NIFTY/NSEI are already streamed by the dedicated poller — skip to
                # avoid double-fetching and wasting ICICI quota.
                symbols = [s for s in symbols if s not in {"NIFTY", "NSEI"}][:max_symbols]

                if symbols:
                    await asyncio.gather(*[_poll_one(s) for s in symbols])
                    tick += 1
                    if tick % 12 == 1:  # ~once per minute
                        logger.info("Watchlist quotes published", count=len(symbols), tick=tick)
            except Exception as exc:
                logger.warning("Watchlist poller error", error=str(exc))
            await asyncio.sleep(interval)

    try:
        _nifty_task = asyncio.create_task(_nifty_poller())
    except Exception:
        _nifty_task = None
    try:
        _watchlist_task = asyncio.create_task(_watchlist_poller())
    except Exception:
        _watchlist_task = None

    logger.info("Data service started")
    yield
    # ── Shutdown ──────────────────────────────────────────────────────────────
    try:
        live_ticks_mod.shutdown_instance()
    except Exception:
        pass
    try:
        if _live_quotes is not None:
            _live_quotes.stop()          # LV-DATA: join the NSE fallback poller thread on shutdown
    except Exception:
        pass
    try:
        tick_store_mod.shutdown_store()     # W6: final tick flush (no-op when never started)
    except Exception:
        pass
    try:
        for _t in (_nifty_task, _watchlist_task, _live_connect_task):
            if _t is not None:
                _t.cancel()
        await asyncio.gather(
            *[t for t in (_nifty_task, _watchlist_task, _live_connect_task) if t is not None],
            return_exceptions=True,
        )
    except Exception:
        pass
    try:
        _live.disconnect()
    except Exception:
        pass
    try:
        _store.close()
    except Exception:
        pass
    logger.info("Data service stopped")


app = FastAPI(
    title="SuryaDhana — Data Service",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(tick_store_mod.router)   # W6: /ticks/bars, /ticks/vwap, /ticks/store-status
app.include_router(fo_analytics.router)       # W2: /db/fo/*
# Observability (Terminal v2 PLAN 1.5, shared/metrics.py): GET /metrics, X-Request-ID in/out as the correlation id,
# JSON access log (no /health /live / lines), anyio worker-thread limit raised to SD_THREAD_LIMIT (64) so the
# per-call DuckDB cursors (storage/duckdb_store.py read()/reader()) run side by side. Inside the guard.
install_observability(app, service="data-service")
# Host/Origin guard (desktop review C2-security-01: DNS rebinding + cross-site POSTs such as
# /jobs/build-ml-dataset). The OUTERMOST middleware; add any future middleware above it.
install_http_guard(app, service="data-service")


def get_store() -> DuckDBStore:
    assert _store is not None
    return _store


def get_yfinance() -> DirectYahooProvider:
    assert _yfinance is not None
    return _yfinance


def get_live_provider() -> LiveDataProvider:
    assert _live is not None
    return _live


def _extract_session_token(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    # Search regardless of scheme: a copied address bar often reads "127.0.0.1/?apisession=…".
    match = re.search(r"(?:apisession|session_token|api_session)=([^&\s#]+)", value, re.IGNORECASE)
    return match.group(1) if match else value


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    # Liveness only — cheap, never touches the DB lock (Docker healthcheck).
    return {"status": "ok", "service": "data-service",
            "db_read_only": bool(_store and _store._read_only)}


@app.get("/ready")
async def ready(store: DuckDBStore = Depends(get_store)) -> dict:
    if store._read_only:
        raise HTTPException(
            status_code=503,
            detail="DuckDB is read-only (write lock held by another process) — ingestion disabled",
        )
    return {"status": "ready", "db": store._db_path}


@app.post("/admin/migrate")
def run_migrations(store: DuckDBStore = Depends(get_store)) -> dict:
    """Re-apply the idempotent schema DDL on the existing write connection."""
    if store._read_only:
        raise HTTPException(status_code=503, detail="DuckDB is read-only — cannot migrate")
    store._init_schema()
    return {"status": "ok", "message": "Schema DDL applied"}


# ── Jobs: universe refresh + ML dataset build (Yahoo-only history) ─────────────

class RefreshUniverseRequest(BaseModel):
    mode: str = "incremental"          # "incremental" | "full"
    tickers: list[str] | None = None   # None = whole universe (minus INVALID)
    years: int | None = None
    workers: int = 3
    # daily-pipeline only: step names left out of the run. The controller (B2, Terminal v2 0.5) sends
    # ["nse_positions"]: the F&O / participant-OI files land 20:10, so the 18:30 pass is equity-only and the
    # 20:30 pass fetches them. Unknown names are ignored.
    skip_steps: list[str] = []


def _refresh_targets(store: DuckDBStore, settings: Settings, tickers: list[str] | None) -> list[str]:
    if tickers:
        return sorted({t.strip().upper() for t in tickers if t.strip()})
    inst = store.get_instruments()
    if inst.empty:
        return _universe_tickers(settings)
    return sorted(inst.loc[inst["instrument_type"] != "INVALID", "ticker"].tolist())


def _run_refresh(req: RefreshUniverseRequest, progress) -> dict:
    settings = get_settings()
    store, yf = get_store(), get_yfinance()
    targets = _refresh_targets(store, settings, req.tickers)
    years = req.years or settings.historical_years
    summary = ingest.refresh_universe(yf, store, targets, years=years,
                                      full=req.mode == "full", workers=req.workers,
                                      progress=progress).as_dict()
    summary["indices_written"] = ingest.refresh_indices(yf, store, years=years + 1)
    summary["indices_nse"] = _nse_official_index_closes(store)     # NSE's own closes win over Yahoo's snapshot
    store.checkpoint()
    return summary


NSE_INDEX_CLOSES = {"NIFTY 50": "NIFTY50", "INDIA VIX": "INDIAVIX"}


def _nse_official_index_closes(store: DuckDBStore) -> dict[str, float]:
    """Overwrite the session's NIFTY 50 / India VIX daily closes with NSE's official ones (allIndices after 15:30).
    Yahoo's daily bar can be an intraday snapshot (13 Oct 2026: VIX 14.12 stored, NSE closed it at 14.04)."""
    global _nse_live
    import nse_live
    from bhavcopy import HEADERS
    from datetime import datetime as _dt
    if _nse_live is None:
        _nse_live = nse_live.NseLive(HEADERS)
    out: dict[str, float] = {}
    try:
        payload = _nse_live.get("allIndices", ttl_open=15, ttl_closed=300)
    except Exception as exc:  # noqa: BLE001 — Yahoo's values stay
        logger.warning("NSE index closes unavailable", error=str(exc))
        return out
    for name, sym in NSE_INDEX_CLOSES.items():
        q = nse_live.parse_index_quote(payload, name)
        stamp = str(q.get("time") or "")
        try:
            day = _dt.strptime(stamp[:11], "%d-%b-%Y").date()
        except ValueError:
            continue
        if q.get("last") is not None and stamp[12:17] >= "15:30":
            store.upsert_index_daily(sym, pd.DataFrame({"date": [day.isoformat()], "close": [float(q["last"])]}), "nse")
            out[sym] = float(q["last"])
    if out:
        _monitor_cache.update(key=None)        # the market monitor snapshot read the old closes: rebuild it
    return out


@app.post("/jobs/nse-index-closes")
def nse_index_closes() -> dict:
    """Write today's official NSE closes for NIFTY 50 and India VIX (also run inside the EOD refresh)."""
    return {"written": _nse_official_index_closes(get_store())}


def _run_build(progress) -> dict:
    from ml_dataset import build_ml_dataset
    return build_ml_dataset(get_store(), progress=progress)


def _submit(kind: str, fn) -> dict:
    store = get_store()
    if store._read_only:
        raise HTTPException(status_code=503, detail="DuckDB is read-only — cannot run write jobs")
    job, created = _jobs.submit(kind, fn)
    return {**job, "already_running": not created}


@app.post("/jobs/refresh-universe")
def start_refresh_universe(req: RefreshUniverseRequest) -> dict:
    """Refresh stored daily bars (Yahoo only) + NIFTY/VIX index closes."""
    if req.mode not in ("incremental", "full"):
        raise HTTPException(status_code=422, detail="mode must be 'incremental' or 'full'")
    return _submit("refresh", lambda p: _run_refresh(req, p))


@app.post("/jobs/build-ml-dataset")
def start_build_ml_dataset() -> dict:
    """Rebuild ml_features + ml_labels from current ohlcv (atomic swap)."""
    if _jobs.is_running("refresh"):
        raise HTTPException(status_code=409, detail="A universe refresh is running — build after it finishes")
    return _submit("build", _run_build)


@app.post("/jobs/daily-pipeline")
def start_daily_pipeline(req: RefreshUniverseRequest | None = None) -> dict:
    """Refresh (incremental) → rebuild ML dataset, as one job. Used by the EOD scheduler."""
    req = req or RefreshUniverseRequest()

    def _pipeline(progress) -> dict:
        # Order + isolation (15 Oct 2026 incident, eod_steps.py): the market data the Desk, shadow,
        # MKT tab and 21:00 wrap read lands FIRST, and every step runs even if one before it failed.
        # The ML dataset rebuild (legacy 5-day ML + the v1 feature parquet) runs LAST and is
        # non-fatal: on 15 Oct it sat second, hit DuckDB's memory cap and skipped all of the below.
        # Fatal = the job ends in error (CRITICAL alert); non-fatal failures are reported in the
        # result and the controller raises a WARNING for them.
        def _monitor() -> dict:
            snap = market_monitor_snapshot(get_store())          # new bhavcopy → rebuild the cache now
            return {"as_of": snap.get("as_of")}

        steps = [
            ("refresh", lambda: _run_refresh(req, progress), True),
            ("bhavcopy", lambda: _run_bhavcopy(BhavcopyRequest(), progress), False),
            ("nse_positions", lambda: _run_nse_positions(NsePositionsRequest(), progress), False),
            ("market_monitor", _monitor, False),
            ("nse_events", lambda: _run_nse_events(progress), False),
            ("build", lambda: _run_build(progress), False),
        ]
        skip = set(req.skip_steps)
        return run_eod_steps([s for s in steps if s[0] not in skip], logger)

    if _jobs.is_running("refresh") or _jobs.is_running("build"):
        raise HTTPException(status_code=409, detail="A refresh/build job is already running")
    return _submit("daily_pipeline", _pipeline)


class BhavcopyRequest(BaseModel):
    start: date | None = None     # default: day after the last stored date (or ARCHIVE_START)
    end: date | None = None       # default: today once published (after 17:00 IST), else yesterday
    days: str = "all"             # all | weekdays | weekends (weekend special sessions exist)


def _bhavcopy_window(store: DuckDBStore, req: BhavcopyRequest) -> tuple[date, date]:
    import bhavcopy
    from datetime import datetime as _dt, timedelta as _td
    from zoneinfo import ZoneInfo
    now = _dt.now(ZoneInfo("Asia/Kolkata"))
    end = req.end or (now.date() if now.hour >= bhavcopy.PUBLISH_READY_HOUR_IST else now.date() - _td(days=1))
    if req.start:
        return req.start, end
    last = store.get_bhavcopy_meta().get("last_date")
    return (date.fromisoformat(last) + _td(days=1) if last else bhavcopy.ARCHIVE_START), end


def _run_bhavcopy(req: BhavcopyRequest, progress) -> dict:
    import bhavcopy
    store = get_store()
    start, end = _bhavcopy_window(store, req)
    if start > end:
        return {"start": start.isoformat(), "end": end.isoformat(), "note": "already up to date",
                **store.get_bhavcopy_meta()}
    if req.days not in ("all", "weekdays", "weekends"):
        raise ValueError("days must be all, weekdays or weekends")
    result = bhavcopy.ingest_range(store, start, end, _data_dir(get_settings()) / "nse_bhavcopy", progress,
                                   days_filter=req.days)
    store.checkpoint()
    return {**result, "table": store.get_bhavcopy_meta()}


@app.post("/jobs/ingest-bhavcopy")
def start_ingest_bhavcopy(req: BhavcopyRequest | None = None) -> dict:
    """Backfill / update the NSE full bhavcopy (survivorship-free universe + delivery %)."""
    return _submit("bhavcopy", lambda p: _run_bhavcopy(req or BhavcopyRequest(), p))


class NsePositionsRequest(BaseModel):
    datasets: list[str] | None = None   # fo | participant_oi | deals | mtf (default: all)
    start: date | None = None           # default: resume after the last stored date per dataset
    end: date | None = None             # default: latest file NSE has published


def _positions_window(store: DuckDBStore, dataset: str, req: NsePositionsRequest) -> tuple[date, date]:
    import nse_positions
    from datetime import datetime as _dt, timedelta as _td
    from zoneinfo import ZoneInfo
    now = _dt.now(ZoneInfo("Asia/Kolkata"))
    # F&O bhavcopy, participant OI and deals land in the evening; MTF for day T lands on T+1.
    # A file that is not out yet 404s and is retried next run (windows resume after the last stored date).
    ready = now.date() if now.hour >= 18 else now.date() - _td(days=1)
    end = req.end or (ready - _td(days=1) if dataset == "mtf" else ready)
    if req.start:
        return req.start, end
    table = {"fo": "nse_fo_daily", "participant_oi": "nse_participant_oi", "deals": "nse_deals", "mtf": "nse_mtf"}[dataset]
    last = store.last_date(table)
    if not last:
        return nse_positions.START[dataset], end
    resume = date.fromisoformat(last) + _td(days=1)
    return (resume - _td(days=7) if dataset == "deals" else resume), end   # deals: re-pull the last week


def _run_nse_positions(req: NsePositionsRequest, progress) -> dict:
    import nse_positions
    store = get_store()
    cache = _data_dir(get_settings()) / "nse_archive"
    out = {}
    for ds in req.datasets or list(nse_positions.DATASETS):
        if ds not in nse_positions.DATASETS:
            raise ValueError(f"unknown dataset {ds}; choose from {nse_positions.DATASETS}")
        start, end = _positions_window(store, ds, req)
        if start > end:
            out[ds] = {"note": "already up to date", "start": start.isoformat(), "end": end.isoformat()}
            continue
        out[ds] = (nse_positions.ingest_deals(store, start, end, progress) if ds == "deals"
                   else nse_positions.ingest_daily(store, ds, start, end, cache, progress))
    store.checkpoint()
    return {**out, "tables": store.get_positions_meta()}


@app.post("/jobs/ingest-nse-positions")
def start_ingest_nse_positions(req: NsePositionsRequest | None = None) -> dict:
    """F&O open interest, participant OI, bulk/block/short deals and MTF positions (backfill or update)."""
    return _submit("nse_positions", lambda p: _run_nse_positions(req or NsePositionsRequest(), p))


class NseFilingsRequest(BaseModel):
    symbols: list[str] | None = None    # default: most-traded EQ stocks + all F&O stocks
    top_n: int = 300
    xbrl_per_symbol: int = 1            # new quarterly shareholding filings parsed per symbol per run
    datasets: list[str] = ["insider", "shareholding"]   # or ["shareholding_reparse"] alone
    insider_since: date | None = None   # backfill insider trades year by year from this date


def _run_nse_filings(req: NseFilingsRequest, progress) -> dict:
    import httpx
    import nse_filings
    store = get_store()
    xbrl_cache = _data_dir(get_settings()) / "nse_archive" / "shareholding_xbrl"
    if req.datasets == ["shareholding_reparse"]:
        with httpx.Client(headers=nse_filings.API_HEADERS, timeout=60, follow_redirects=True) as client:
            result = nse_filings.reparse_shareholding(store, client, xbrl_cache, progress)
        store.checkpoint()
        return {**result, "tables": store.get_positions_meta()}
    if req.datasets == ["insider_gg"]:               # single-filing PIT feed only (backfill: insider_since)
        from datetime import timedelta as _td
        since = req.insider_since or (date.today() - _td(days=45))
        with httpx.Client(headers=nse_filings.API_HEADERS, timeout=60, follow_redirects=True) as client:
            result = nse_filings.ingest_pit_gg(store, since, date.today(), progress, client,
                                               _data_dir(get_settings()) / "nse_archive" / "pit_xbrl")
        store.checkpoint()
        return {**result, "tables": store.get_positions_meta()}
    symbols = req.symbols
    if not symbols:
        liquid = set(store.get_liquid_symbols(req.top_n))
        with store.reader() as con:
            fo = {r[0] for r in con.execute(
                "SELECT DISTINCT symbol FROM nse_fo_daily WHERE kind = 'stock' AND date = (SELECT MAX(date) FROM nse_fo_daily)"
            ).fetchall()}
        symbols = sorted(liquid | fo)
    result = nse_filings.ingest_filings(store, [s.upper() for s in symbols], progress,
                                        xbrl_per_symbol=req.xbrl_per_symbol, datasets=tuple(req.datasets),
                                        insider_since=req.insider_since, xbrl_cache=xbrl_cache)
    if "insider" in req.datasets:
        # since 5 May 2026 insider trades are only in the single-filing feed (NSE/CML/2026/11)
        from datetime import timedelta as _td
        try:
            with httpx.Client(headers=nse_filings.API_HEADERS, timeout=60, follow_redirects=True) as client:
                result["insider_gg"] = nse_filings.ingest_pit_gg(
                    store, req.insider_since or (date.today() - _td(days=45)), date.today(), None, client,
                    _data_dir(get_settings()) / "nse_archive" / "pit_xbrl")
        except Exception as exc:  # noqa: BLE001 — the legacy feed's result still counts
            result["insider_gg"] = {"error": str(exc)[:200]}
    store.checkpoint()
    return {**result, "tables": store.get_positions_meta()}


@app.post("/jobs/ingest-nse-filings")
def start_ingest_nse_filings(req: NseFilingsRequest | None = None) -> dict:
    """Insider trades + shareholding patterns (one request per company; run weekly)."""
    return _submit("nse_filings", lambda p: _run_nse_filings(req or NseFilingsRequest(), p))


_events_state: dict[str, Any] = {"last_run": 0.0}
_typical_cache: dict[str, Any] = {"at": 0.0, "asked": set(), "map": {}}
_EVENTS_MAX_AGE_S = 12 * 3600


def _run_nse_events(progress) -> dict:
    import nse_events
    result = nse_events.ingest_events(get_store(), progress)
    get_store().checkpoint()
    _events_state["last_run"] = time.time()
    return result


@app.post("/jobs/ingest-nse-events")
def start_ingest_nse_events() -> dict:
    """NSE event calendar + board meetings + corporate actions → nse_events (runs in the EOD pipeline)."""
    return _submit("nse_events", _run_nse_events)


@app.get("/db/events")
def get_events(start: date | None = None, end: date | None = None,
               store: DuckDBStore = Depends(get_store)) -> dict:
    """Corporate events in a date window (default: last 7 days → next 60). Starts a background refresh
    when the feeds were not pulled in the last 12 h; the response never waits for NSE."""
    from datetime import timedelta as _td
    start = start or date.today() - _td(days=7)
    end = end or date.today() + _td(days=60)
    refreshing = False
    if (time.time() - _events_state["last_run"] > _EVENTS_MAX_AGE_S and not store._read_only
            and not _jobs.is_running("nse_events")):
        _events_state["last_run"] = time.time()      # one attempt per window, even if NSE is down
        _jobs.submit("nse_events", _run_nse_events)
        refreshing = True
    rows = store.get_nse_events(start.isoformat(), end.isoformat())
    # typical results-day move for upcoming results (from nse_results), cached for an hour
    import results_history as rh
    want = sorted({r["symbol"] for r in rows if r["kind"] == "RESULTS" and r["event_date"] >= date.today().isoformat()})
    if _typical_cache["at"] < time.time() - 3600 or not set(want) <= _typical_cache["asked"]:
        try:
            with store.reader() as con:
                _typical_cache["map"] = rh.typical_moves(con, want)
            _typical_cache.update(at=time.time(), asked=set(want))
        except Exception as exc:  # noqa: BLE001 — the calendar works without it
            logger.warning("typical results moves failed", error=str(exc))
    for r in rows:
        if r["kind"] == "RESULTS" and r["symbol"] in _typical_cache["map"]:
            t = _typical_cache["map"][r["symbol"]]
            r["typical_move_pct"], r["typical_quarters"] = t["avg_abs_move_pct"], t["quarters"]
    return {"start": start.isoformat(), "end": end.isoformat(), "rows": rows, "count": len(rows),
            "refreshing": refreshing or _jobs.is_running("nse_events")}


@app.get("/db/typical-results-moves")
def typical_results_moves(symbols: str = Query(..., min_length=1, max_length=4000), store: DuckDBStore = Depends(get_store)) -> dict:
    """Average absolute results-day move (and quarters measured) per symbol, from nse_results reactions."""
    import results_history as rh
    syms = sorted({s.strip().upper() for s in symbols.split(",") if s.strip()})[:200]
    with store.reader() as con:
        m = rh.typical_moves(con, syms)
    return {"moves": {k: {"typical_move_pct": v["avg_abs_move_pct"], "quarters": v["quarters"]} for k, v in m.items()}}


@app.get("/db/security/{symbol}")
def security_profile(symbol: str, store: DuckDBStore = Depends(get_store)) -> dict:
    """One stock's profile: adjusted price stats, delivery, ownership, insiders, deals, F&O, MTF, events."""
    import security
    from shared.momentum import industries
    if not re.fullmatch(r"[A-Za-z0-9&\-]{1,20}", symbol):
        raise HTTPException(status_code=422, detail="Bad symbol")
    with store.reader() as con:
        out = security.profile(con, symbol, industries())
    if not out.get("found"):
        raise HTTPException(status_code=404, detail=f"{symbol.upper()} is not in the NSE bhavcopy")
    return out


@app.get("/db/security/{symbol}/history")
def security_history(symbol: str, days: int = Query(90, ge=5, le=3700), store: DuckDBStore = Depends(get_store)) -> dict:
    """HP: daily bars as traded (OHLC, VWAP, volume, value, trades, delivery %), change on adjusted closes, and the
    split / bonus ex-dates inside the window, newest first."""
    import security
    if not re.fullmatch(r"[A-Za-z0-9&\-]{1,20}", symbol):
        raise HTTPException(status_code=422, detail="Bad symbol")
    with store.reader() as con:
        out = security.price_history(con, symbol, days)
    if not out.get("found"):
        raise HTTPException(status_code=404, detail=f"{symbol.upper()} is not in the NSE bhavcopy")
    return out


# ── /db/closes: stored NSE closes for history panes (live-NSE program round 2, L2-API, 5 Nov 2026) ───────────────────
# NSE publishes daily history once a day (the bhavcopy, ~18:30): it is never live, and this route never makes it look
# live. COMP, the hover card's spark and 52-week range, WTCH and the news dock read it here in ONE request for up to 300
# symbols instead of one /db/security/{sym}/history read each. Point in time: only sessions already stored, up to today;
# nothing is forward-filled and today's forming bar is never invented (the live price is /live/quotes' job).
# Stocks: nse_bhavcopy, EQ/BE rows (EQ preferred, shared.nse_panel.pick_equity_rows), split/bonus-adjusted inside the
# window exactly as shared.nse_panel.adjust (the splits table + the overnight-gap rule), so a bonus is never drawn as a
# crash; the ex-dates are listed per symbol. Indices (NSE names with a space, 'NIFTY 50'): index_ohlc_daily (NSE's own
# daily index file, Terminal v2) only, never market_index_daily (its NIFTY50 / INDIAVIX rows can be Yahoo's). Company
# names: NSE's EQUITY_L list (data/reference/nse_equity_list.csv), read-only. A sync route: the threadpool, never the loop.
CLOSES_MAX_SYMBOLS = 300
CLOSES_MAX_SYMBOL_DAYS = 120_000          # symbols × calendar days per request: 300 × 400 d, or 32 × 3,700 d
_CLOSES_STOCK = re.compile(r"[A-Z0-9&\-]{1,20}")
_CLOSES_INDEX = re.compile(r"[A-Z0-9][A-Z0-9 &:/.()%\-]{2,59}")
_closes_names_state: dict[str, Any] = {"key": None, "names": {}}


def _closes_symbols(raw: str) -> list[str]:
    """'tcs, infy.ns,Nifty  50' → ['TCS', 'INFY', 'NIFTY 50'] (unique, request order); 422 on a bad or empty list."""
    out: list[str] = []
    for part in raw.split(","):
        s = " ".join(part.strip().upper().split())
        if s.endswith(".NS"):
            s = s[:-3].rstrip()
        if not s:
            continue
        if not (_CLOSES_INDEX.fullmatch(s) if " " in s else _CLOSES_STOCK.fullmatch(s)):
            raise HTTPException(status_code=422, detail=f"bad symbol {part.strip()[:40]!r}: an NSE symbol (RELIANCE, M&M) "
                                                        "or an NSE index name ('NIFTY 50')")
        out.append(s)
    out = list(dict.fromkeys(out))
    if not out:
        raise HTTPException(status_code=422, detail="no symbols given")
    if len(out) > CLOSES_MAX_SYMBOLS:
        raise HTTPException(status_code=422, detail=f"at most {CLOSES_MAX_SYMBOLS} symbols per request ({len(out)} given)")
    return out


def _closes_names_path() -> Path:
    return _data_dir(get_settings()) / "reference" / "nse_equity_list.csv"


def _closes_names() -> dict[str, str]:
    """SYMBOL → NAME OF COMPANY from NSE's EQUITY_L copy; re-read only when the file changes; {} when it is missing."""
    p = _closes_names_path()
    try:
        st = p.stat()
    except OSError:
        return {}
    key = (str(p), st.st_mtime_ns, st.st_size)
    if _closes_names_state["key"] != key:
        try:
            df = pd.read_csv(p, dtype=str)
            df.columns = [str(c).strip().upper() for c in df.columns]
            names = {str(s).strip().upper(): n.strip() for s, n in zip(df["SYMBOL"], df["NAME OF COMPANY"])
                     if isinstance(n, str) and n.strip()}
        except (OSError, KeyError, ValueError):
            names = {}
        _closes_names_state.update(key=key, names=names)
    return _closes_names_state["names"]


def _closes_frames(con: Any, symbols: list[str], start: date, end: date) -> dict[str, Any]:
    """The raw stored rows (caller holds the store's shared lock): bhavcopy EQ/BE rows + splits for the stocks,
    index_ohlc_daily rows for the indices (None when that Terminal v2 table is not deployed)."""
    import duckdb
    stocks = [s for s in symbols if " " not in s]
    indices = [s for s in symbols if " " in s]
    out: dict[str, Any] = {"bhav": None, "splits": None, "index": None, "index_table": True}
    if stocks:
        out["bhav"] = con.execute("""
            SELECT symbol, series, date, open, high, low, close, prev_close, avg_price, volume FROM nse_bhavcopy
            WHERE list_contains(?, symbol) AND series IN ('EQ', 'BE') AND date >= ?::DATE AND date <= ?::DATE""",
                                  [stocks, start.isoformat(), end.isoformat()]).df()
        out["splits"] = con.execute("SELECT ticker, date, ratio FROM splits WHERE ratio > 0 AND list_contains(?, ticker)",
                                    [stocks + [f"{s}.NS" for s in stocks]]).df()
    if indices:
        try:
            out["index"] = con.execute("""
                SELECT symbol, date, high, low, close FROM index_ohlc_daily
                WHERE list_contains(?, symbol) AND date >= ?::DATE AND date <= ?::DATE AND close IS NOT NULL""",
                                       [indices, start.isoformat(), end.isoformat()]).df()
        except duckdb.CatalogException:
            out["index_table"] = False
    return out


def _closes_num(v: Any, nd: int = 4) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, nd) if pd.notna(f) and abs(f) != float("inf") else None


def _closes_payload(frames: dict[str, Any], symbols: list[str], *, start: date, end: date, tail: int | None,
                    names: dict[str, str]) -> dict:
    """Frames → {as_of, source, series: {SYM: [{date, close}]}, meta: {SYM: {...}}, missing: {SYM: reason}}."""
    from shared.nse_panel import adjust, pick_equity_rows
    series: dict[str, list[dict]] = {}
    meta: dict[str, dict] = {}
    groups: list[tuple[str, pd.DataFrame, str, list[dict]]] = []
    bhav = frames.get("bhav")
    if bhav is not None and not bhav.empty:
        bhav = bhav.assign(date=pd.to_datetime(bhav["date"]))
        sp = frames.get("splits")
        if sp is not None and not sp.empty:
            sp = sp.assign(ticker=sp["ticker"].astype(str).str.upper().str.replace(r"\.NS$", "", regex=True),
                           date=pd.to_datetime(sp["date"]).dt.tz_localize(None).dt.normalize())
            sp = sp.drop_duplicates(["ticker", "date"])
        bars = adjust(pick_equity_rows(bhav), sp if sp is not None and not sp.empty else None)
        ca = bars.attrs.pop("corporate_actions", None)
        acts: dict[str, list[dict]] = {}
        if ca is not None and len(ca):
            for s, d, k in zip(ca["symbol"], ca["date"], ca["k"]):
                acts.setdefault(str(s), []).append({"date": pd.Timestamp(d).strftime("%Y-%m-%d"), "k": _closes_num(k, 6)})
        for sym, g in bars.groupby("symbol", sort=False):
            g = g.sort_values("date")
            groups.append((str(sym), g.rename(columns={"adj_close": "c", "adj_high": "h", "adj_low": "l"}), "nse_bhavcopy",
                           sorted(acts.get(str(sym), []), key=lambda a: a["date"])))
    ix = frames.get("index")
    if ix is not None and not ix.empty:
        ix = ix.assign(date=pd.to_datetime(ix["date"]))
        for sym, g in ix.groupby("symbol", sort=False):
            groups.append((str(sym), g.sort_values("date").rename(columns={"close": "c", "high": "h", "low": "l"}),
                           "nse_index_file", []))
    for sym, g, source, actions in groups:
        pts = [{"date": pd.Timestamp(d).strftime("%Y-%m-%d"), "close": c}
               for d, c in zip(g["date"], (_closes_num(x) for x in g["c"])) if c is not None and c > 0]
        if not pts:
            continue
        series[sym] = pts[-tail:] if tail else pts
        meta[sym] = {"source": source, "name": names.get(sym) if source == "nse_bhavcopy" else sym,
                     "first_date": pts[0]["date"], "last_date": pts[-1]["date"], "sessions": len(pts),
                     "high": _closes_num(g["h"].max(), 2), "low": _closes_num(g["l"].min(), 2),
                     "last_series": str(g["series"].iloc[-1]) if "series" in g else None, "actions": actions}
    missing: dict[str, str] = {}
    for s in symbols:
        if s in series:
            continue
        if " " not in s:
            missing[s] = f"not in the NSE bhavcopy (EQ/BE) between {start.isoformat()} and {end.isoformat()}"
        elif not frames.get("index_table", True):
            missing[s] = "index_ohlc_daily (NSE's daily index file) is not deployed on this data-service"
        else:
            missing[s] = f"no NSE daily index file row between {start.isoformat()} and {end.isoformat()}"
    last = [m["last_date"] for m in meta.values()]
    return {"as_of": max(last) if last else None, "source": "nse_bhavcopy", "from": start.isoformat(), "to": end.isoformat(),
            "tail": tail, "series": {s: series[s] for s in symbols if s in series},
            "meta": {s: meta[s] for s in symbols if s in meta}, "missing": missing,
            "generated_at": datetime.now().isoformat(timespec="seconds")}


@app.get("/db/closes")
def db_closes(symbols: str = Query(..., min_length=1, max_length=12000), days: int = Query(365, ge=5, le=3700),
              tail: int | None = Query(None, ge=1, le=3700), store: DuckDBStore = Depends(get_store)) -> dict:
    """Stored daily closes (EOD, never live) for up to 300 NSE symbols / index names in one read: split/bonus-adjusted
    bhavcopy closes oldest first (``tail``: only the last N sessions; ``meta`` high/low cover the whole ``days`` window),
    the ex-dates, the company name, the first/last stored session; ``missing`` says why a symbol has no series."""
    syms = _closes_symbols(symbols)
    if len(syms) * days > CLOSES_MAX_SYMBOL_DAYS:
        raise HTTPException(status_code=422, detail=f"{len(syms)} symbols × {days} days is over the {CLOSES_MAX_SYMBOL_DAYS:,} "
                                                    "symbol-day budget of one request: ask fewer symbols or a shorter window")
    end = date.today()
    start = end - timedelta(days=days)
    with store.reader() as con:
        frames = _closes_frames(con, syms, start, end)
    return _closes_payload(frames, syms, start=start, end=end, tail=tail, names=_closes_names())


class ResultsIngestRequest(BaseModel):
    symbols: list[str] | None = None    # default: top-N liquid at each year-end 2014–2025 (survivorship-aware)
    top_n: int = 300
    max_age_days: int = 7               # skip symbols refreshed more recently than this
    recent_events_days: int | None = None   # only symbols with a RESULTS event in the last N days (daily capture)
    # repair: replace (not merge) each fetched symbol's rows for quarters ending on/after this date. The upsert keeps
    # the earliest time, so wrong early times (governance filings taken as results, fixed 14 Oct 2026) need this.
    replace_since: str | None = None
    # only symbols that have rows for quarters ending on/after this date (with replace_since: the affected ones)
    having_since: str | None = None


def _run_results_ingest(req: ResultsIngestRequest, progress) -> dict:
    import httpx
    import results_history as rh
    import nse_filings
    from datetime import datetime as _dt, timedelta as _td
    store = get_store()
    if req.symbols:
        symbols = [s.upper() for s in req.symbols]
    elif req.recent_events_days is not None:
        with store.reader() as con:
            symbols = [r[0] for r in con.execute(
                "SELECT DISTINCT symbol FROM nse_events WHERE kind = 'RESULTS' AND event_date BETWEEN ?::DATE AND ?::DATE",
                [(date.today() - pd.Timedelta(days=req.recent_events_days)).isoformat(), date.today().isoformat()]).fetchall()]
    elif req.having_since:
        with store.reader() as con:
            symbols = [r[0] for r in con.execute(
                "SELECT DISTINCT symbol FROM nse_results WHERE period_end >= ?::DATE ORDER BY symbol", [req.having_since]).fetchall()]
    else:
        symbols = store.get_historical_liquid_symbols(req.top_n)
    out: dict[str, Any] = {"symbols": len(symbols), "fetched": 0, "skipped_fresh": 0, "empty": [], "rows": 0, "replaced": 0}
    with httpx.Client(headers=nse_filings.API_HEADERS, timeout=30, follow_redirects=True) as client:
        for i, sym in enumerate(symbols, 1):
            seen = store.results_fetched_at(sym)
            if seen is not None and _dt.now() - pd.Timestamp(seen).to_pydatetime() < _td(days=req.max_age_days):
                out["skipped_fresh"] += 1
            else:
                rel = rh.fetch_releases(sym, client=client)
                out["fetched"] += 1
                if rel.empty:
                    out["empty"].append(sym)
                else:
                    fresh_era = req.replace_since and (pd.to_datetime(rel["period_end"]) >= pd.Timestamp(req.replace_since)).any()
                    if fresh_era:              # the new fetch covers the era: a failed / partial one never deletes data
                        with store.writer() as con:
                            out["replaced"] += con.execute(
                                "DELETE FROM nse_results WHERE symbol = ? AND period_end >= ?::DATE RETURNING 1",
                                [sym, req.replace_since]).fetchall().__len__()
                    out["rows"] += store.upsert_results(rel)
            progress(i, len(symbols))
    store.checkpoint()
    out["empty_count"] = len(out["empty"])
    out["empty"] = out["empty"][:50]
    return out


@app.post("/jobs/ingest-results")
def start_ingest_results(req: ResultsIngestRequest | None = None) -> dict:
    """Quarterly results release times for many stocks (two NSE requests each; ~1.3 s per stock)."""
    return _submit("nse_results", lambda p: _run_results_ingest(req or ResultsIngestRequest(), p))


_results_misses: dict[str, float] = {}          # symbols NSE had no results for (ETFs…): retry after a day


@app.get("/db/security/{symbol}/results")
def security_results(symbol: str, store: DuckDBStore = Depends(get_store)) -> dict:
    """How the stock moved on each of its last 12 quarterly results (release time → reaction session)."""
    import results_history as rh
    from datetime import datetime as _dt, timedelta as _td
    from shared.nse_panel import adjust, pick_equity_rows
    sym = symbol.upper()
    if not re.fullmatch(r"[A-Z0-9&\-]{1,20}", sym):
        raise HTTPException(status_code=422, detail="Bad symbol")
    fetched = store.results_fetched_at(sym)
    stale = fetched is None or (_dt.now() - pd.Timestamp(fetched).to_pydatetime()) > _td(days=7)
    recently_missed = time.time() - _results_misses.get(sym, 0) < 86_400
    if stale and not recently_missed and not store._read_only:
        rel = rh.fetch_releases(sym)                      # network, outside the DB lock
        if rel.empty:
            _results_misses[sym] = time.time()
        else:
            store.upsert_results(rel)
    rel = store.get_results(sym)
    if rel.empty:
        return {"symbol": sym, "reactions": [], "summary": {"quarters": 0}}
    rel = rel[rel["released_at"] >= pd.Timestamp.now() - pd.Timedelta(days=4 * 365)]
    start = (pd.Timestamp(rel["released_at"].min()) - pd.Timedelta(days=15)).date().isoformat() if len(rel) else "2022-01-01"
    with store.reader() as con:
        raw = con.execute("SELECT * FROM nse_bhavcopy WHERE symbol = ? AND date >= ?::DATE", [sym, start]).df()
        splits = con.execute("SELECT ticker, date, ratio FROM splits WHERE ratio > 0 AND ticker IN (?, ?)",
                                     [sym, f"{sym}.NS"]).df()
    if raw.empty:
        return {"symbol": sym, "reactions": [], "summary": {"quarters": 0}}
    raw["date"] = pd.to_datetime(raw["date"])
    splits["date"] = pd.to_datetime(splits["date"]).dt.tz_localize(None).dt.normalize()
    splits["ticker"] = sym
    bars = adjust(pick_equity_rows(raw), splits)
    bars.attrs.pop("corporate_actions", None)
    n50 = store.get_index_daily("NIFTY50")
    nifty = pd.Series(n50["close"].to_numpy(), index=pd.to_datetime(n50["date"]))
    rx = rh.reactions(rel, bars[["date", "adj_open", "adj_close"]], nifty)
    return {"symbol": sym, "reactions": rx, "summary": rh.summary(rx)}


@app.get("/db/security/{symbol}/pe-history")
def security_pe_history(symbol: str, store: DuckDBStore = Depends(get_store)) -> dict:
    """Daily trailing P/E over the FA cache's span, point-in-time (each quarter counts from its filing date), on
    split/bonus-adjusted closes × today's share count; with median / quartiles and today's percentile."""
    import financials as fin
    sym = symbol.upper()
    if not re.fullmatch(r"[A-Z0-9&\-]{1,20}", sym):
        raise HTTPException(status_code=422, detail="Bad symbol")
    cache = fin.load(_data_dir(get_settings()) / "nse_archive" / "financials", sym)
    rows = fin.with_growth(cache["quarters"]) if cache and cache.get("quarters") else []
    if len(rows) < 4:
        return {"symbol": sym, "points": []}
    since = min(q["period_end"] for q in rows)
    closes = store.adjusted_closes([sym], since)
    if closes is None or closes.empty or sym not in closes.columns:
        return {"symbol": sym, "points": []}
    return {"symbol": sym, **fin.pe_series(rows, closes[sym], fin.shares_estimate(rows))}


@app.get("/db/security/{symbol}/actions")
def security_actions(symbol: str, years: int = Query(5, ge=1, le=15), store: DuckDBStore = Depends(get_store)) -> dict:
    """Bloomberg DVD for NSE: dividends (₹ per share, specials flagged), bonuses, splits, buybacks over `years`
    years, dividends per financial year, and the trailing-12-month dividend yield at the last NSE close."""
    global _nse_live
    import nse_live
    from bhavcopy import HEADERS
    sym = symbol.upper()
    if not re.fullmatch(r"[A-Z0-9&\-]{1,20}", sym):
        raise HTTPException(status_code=422, detail="Bad symbol")
    if _nse_live is None:
        _nse_live = nse_live.NseLive(HEADERS)
    try:
        out = _nse_live.symbol_actions(sym, years)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"NSE corporate actions unavailable: {exc}") from exc
    price = None
    try:
        with store.reader() as con:
            got = con.execute("SELECT close FROM nse_bhavcopy WHERE symbol = ? AND series IN ('EQ','BE') ORDER BY date DESC LIMIT 1", [sym]).fetchone()
        price = float(got[0]) if got else None
    except Exception:  # noqa: BLE001
        price = None
    ttm = out.get("ttm_dividend")
    out["price"] = price
    out["ttm_yield_pct"] = round(ttm / price * 100, 2) if ttm and price else (0.0 if ttm == 0 and price else None)
    return out


@app.get("/db/security/{symbol}/filings")
def security_filings(symbol: str, days: int = Query(30, ge=1, le=365)) -> dict:
    """The company's NSE announcements over the last `days` days (Bloomberg CN), categorised. Live from NSE."""
    global _nse_live
    import nse_live
    from bhavcopy import HEADERS
    sym = symbol.upper()
    if not re.fullmatch(r"[A-Z0-9&\-]{1,20}", sym):
        raise HTTPException(status_code=422, detail="Bad symbol")
    if _nse_live is None:
        _nse_live = nse_live.NseLive(HEADERS)
    try:
        return _nse_live.symbol_announcements(sym, days)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"NSE announcements unavailable: {exc}") from exc


_fin_misses: dict[str, float] = {}


@app.get("/db/security/{symbol}/financials")
def security_financials(symbol: str, store: DuckDBStore = Depends(get_store)) -> dict:
    """Last 12 quarters of revenue, profit, EPS (as filed) with YoY / QoQ growth, from NSE results XBRL. Cached per
    company in data/nse_archive/financials; new quarters are looked for at most once a day."""
    import financials as fin
    from datetime import datetime as _dt
    sym = symbol.upper()
    if not re.fullmatch(r"[A-Z0-9&\-]{1,20}", sym):
        raise HTTPException(status_code=422, detail="Bad symbol")
    root = _data_dir(get_settings()) / "nse_archive" / "financials"
    cache = fin.load(root, sym)
    fresh = fin.cache_current(cache) and cache.get("fetched_at", "") >= (_dt.now() - timedelta(days=1)).isoformat()
    if not fresh and time.time() - _fin_misses.get(sym, 0) > 3600:
        try:
            cache = fin.refresh(root, sym)
        except Exception as exc:  # noqa: BLE001 — serve what is cached
            logger.warning("Financials refresh failed", symbol=sym, error=str(exc))
            _fin_misses[sym] = time.time()
    rows = fin.with_growth((cache or {}).get("quarters", []))
    price = None
    try:
        with store.reader() as con:
            got = con.execute("SELECT close FROM nse_bhavcopy WHERE symbol = ? AND series IN ('EQ','BE') ORDER BY date DESC LIMIT 1", [sym]).fetchone()
        price = float(got[0]) if got else None
    except Exception:  # noqa: BLE001 — valuation is optional
        price = None
    return {"symbol": sym, "quarters": rows, "fetched_at": (cache or {}).get("fetched_at"),
            "valuation": fin.valuation(rows, price),
            "basis": "consolidated where filed, else standalone · ₹ as filed · EPS as reported (not adjusted for bonuses/splits) · "
                     "Q4 FY25 (Mar 2025) is missing for about 1 company in 8: NSE's feeds have a gap at the switch to integrated filing"}


_fin_queue: "list[str]" = []
_fin_worker: Any = None


def _fin_prefetch_loop() -> None:
    """Background: refresh queued companies' financials one at a time (polite to NSE)."""
    import financials as fin
    from datetime import datetime as _dt
    root = _data_dir(get_settings()) / "nse_archive" / "financials"
    read = 0
    while _fin_queue:
        sym = _fin_queue.pop(0)
        cache = fin.load(root, sym)
        if fin.cache_current(cache) and cache.get("fetched_at", "") >= (_dt.now() - timedelta(hours=6)).isoformat():
            continue
        try:
            fin.refresh(root, sym)
            read += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Financials prefetch failed", symbol=sym, error=str(exc))
    if read >= 20 and not _pe_rebuild["running"]:          # a sweep, not a single filing: refresh FUND's P/E percentiles
        _rebuild_pe_percentiles()


@app.post("/db/financials/prefetch")
def financials_prefetch(symbols: str = Query(..., min_length=1, max_length=20000)) -> dict:
    """Queue companies whose quarterly financials should be read in the background (e.g. results filed today)."""
    import threading
    global _fin_worker
    for sym in {x.strip().upper() for x in symbols.split(",") if x.strip()}:
        if re.fullmatch(r"[A-Z0-9&\-]{1,20}", sym) and sym not in _fin_queue:
            _fin_queue.append(sym)
    if _fin_worker is None or not _fin_worker.is_alive():
        _fin_worker = threading.Thread(target=_fin_prefetch_loop, name="fin-prefetch", daemon=True)
        _fin_worker.start()
    return {"queued": len(_fin_queue)}


@app.get("/db/financials/prefetch")
def financials_prefetch_status() -> dict:
    """The background financials reader: companies still queued, whether it is running, companies cached so far,
    and the P/E-percentile rebuild state. The queue lives in memory, so a restart empties it."""
    root = _data_dir(get_settings()) / "nse_archive" / "financials"
    return {"queued": len(_fin_queue), "running": bool(_fin_worker and _fin_worker.is_alive()),
            "cached": sum(1 for _ in root.glob("*.json")) if root.exists() else 0, "pe_percentiles": dict(_pe_rebuild)}


_pe_rebuild: dict = {"running": False, "done": 0, "total": 0, "at": None}


def _pe_percentiles_path() -> Path:
    return _data_dir(get_settings()) / "nse_archive" / "derived" / "pe_percentiles.json"


def _rebuild_pe_percentiles() -> None:
    """Background: today's P/E percentile within each company's own point-in-time P/E history (FA cache × adjusted
    closes), written to nse_archive/derived/pe_percentiles.json for FUND. One price query for all companies."""
    import json as _json
    import financials as fin
    from datetime import datetime as _dt
    store = get_store()
    root = _data_dir(get_settings()) / "nse_archive" / "financials"
    syms = sorted(p.stem for p in root.glob("*.json"))
    _pe_rebuild.update(running=True, done=0, total=len(syms))
    out: dict[str, dict] = {}
    try:
        caches = {s: fin.load(root, s) for s in syms}
        rows = {s: fin.with_growth(c["quarters"]) for s, c in caches.items() if c and len(c.get("quarters") or []) >= 4}
        if rows:
            since = min(q["period_end"] for r in rows.values() for q in r)
            closes = store.adjusted_closes(sorted(rows), since)
            for i, (s, r) in enumerate(rows.items()):
                _pe_rebuild["done"] = i + 1
                if closes is None or closes.empty or s not in closes.columns:
                    continue
                pe = fin.pe_series(r, closes[s], fin.shares_estimate(r))
                if len(pe.get("points") or []) >= 60:
                    out[s] = {k: pe.get(k) for k in ("now", "median", "p25", "p75", "percentile", "since")}
        path = _pe_percentiles_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json.dumps({"built_at": _dt.now().isoformat(timespec="seconds"), "companies": out}), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("P/E percentile rebuild failed", error=str(exc))
    finally:
        _pe_rebuild.update(running=False, at=_dt.now().isoformat(timespec="seconds"))


_pe_pct_cache: dict = {"mtime": None, "data": {}}


def _pe_percentiles() -> dict:
    """The rebuilt P/E percentiles, re-read only when the file changes (hover cards call financials-latest a lot)."""
    import json as _json
    path = _pe_percentiles_path()
    try:
        mtime = path.stat().st_mtime
        if mtime != _pe_pct_cache["mtime"]:
            _pe_pct_cache.update(mtime=mtime, data=_json.loads(path.read_text(encoding="utf-8")).get("companies", {}))
    except (OSError, ValueError):
        return {}
    return _pe_pct_cache["data"]


@app.post("/db/financials/pe-percentiles/rebuild")
def pe_percentiles_rebuild() -> dict:
    """Start the background rebuild of P/E-vs-own-history percentiles (≈ a minute or two for ~1,800 companies)."""
    import threading
    if not _pe_rebuild["running"]:
        threading.Thread(target=_rebuild_pe_percentiles, name="pe-pctl", daemon=True).start()
    return dict(_pe_rebuild)


@app.get("/db/financials-universe")
def financials_universe(store: DuckDBStore = Depends(get_store)) -> dict:
    """Every company whose results filings have been read (FA cache): latest quarter, growth, valuation and NSE
    industry — the fundamentals screener's universe. No NSE calls."""
    import csv
    root = _data_dir(get_settings()) / "nse_archive" / "financials"
    syms = sorted(p.stem for p in root.glob("*.json")) if root.exists() else []
    industry: dict[str, str] = {}
    try:
        with open(_data_dir(get_settings()) / "reference" / "nse_industry.csv", newline="", encoding="utf-8") as f:
            industry = {r["Symbol"].strip().upper(): r["Industry"].strip() for r in csv.DictReader(f) if r.get("Symbol")}
    except OSError:
        pass
    latest = financials_latest(",".join(syms), store)["latest"] if syms else {}
    rows = [{"symbol": s, "industry": industry.get(s), **v} for s, v in latest.items()]
    return {"rows": rows, "count": len(rows)}


@app.get("/db/financials-latest")
def financials_latest(symbols: str = Query(..., min_length=1, max_length=40000), store: DuckDBStore = Depends(get_store)) -> dict:
    """Latest cached quarter per company (no network): period, filing time, revenue / profit growth, and valuation
    (market cap, P/E on trailing profit, P/B) at the last NSE close. Companies never read yet are simply absent."""
    import financials as fin
    root = _data_dir(get_settings()) / "nse_archive" / "financials"
    syms = sorted({x.strip().upper() for x in symbols.split(",") if x.strip()})[:3000]
    prices: dict[str, float] = {}
    try:
        with store.reader() as con:
            got = con.execute("""
                SELECT symbol, close FROM (
                    SELECT symbol, close, row_number() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn
                    FROM nse_bhavcopy WHERE list_contains(?, symbol) AND series IN ('EQ', 'BE')
                      AND date >= current_date - INTERVAL 20 DAY) WHERE rn = 1""", [syms]).fetchall()
        prices = {s: float(c) for s, c in got if c}
    except Exception:  # noqa: BLE001 — growth still useful without prices
        prices = {}
    pct = _pe_percentiles()
    out = {}
    for sym in syms:
        cache = fin.load(root, sym)
        rows = fin.with_growth(cache["quarters"]) if cache and cache.get("quarters") else []
        if rows:
            r = rows[0]
            v = fin.valuation(rows, prices.get(sym))
            out[sym] = {**{k: r.get(k) for k in ("period_end", "filed_at", "revenue", "pat", "revenue_yoy", "pat_yoy", "pat_yoy_turn",
                                                  "pat_margin", "bank", "consolidated")},
                        "mcap": v.get("mcap"), "pe": v.get("pe"), "pb": v.get("pb"),
                        "pe_pctl": (pct.get(sym) or {}).get("percentile"), "pe_median_hist": (pct.get(sym) or {}).get("median")}
    return {"latest": out}


@app.get("/db/results-recent")
def results_recent(days: int = Query(10, ge=1, le=120), store: DuckDBStore = Depends(get_store)) -> dict:
    """Results released in the last `days` and the market's reaction (EVTS scoreboard)."""
    import results_history as rh
    with store.reader() as con:
        rows = rh.recent_reactions(con, days)
    return {"days": days, "rows": rows, "count": len(rows)}


def _fo_root() -> Path:
    return _data_dir(get_settings()) / "nse_archive" / "fo"


@app.get("/db/option-chain/{symbol}")
def option_chain_view(symbol: str, expiry: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")) -> dict:
    """End-of-day option chain from the latest cached NSE F&O bhavcopy (OI, IV, PCR, max pain, OI walls)."""
    import option_chain as oc
    if not re.fullmatch(r"[A-Za-z0-9&\-]{1,20}", symbol):
        raise HTTPException(status_code=422, detail="Bad symbol")
    fs = oc.files(_fo_root())
    if not fs:
        raise HTTPException(status_code=404, detail="No F&O bhavcopy cached (run the EOD pipeline)")
    df = oc.load(str(fs[-1][1]))
    out = oc.chain(df, symbol, expiry)
    if not out.get("found"):
        raise HTTPException(status_code=404, detail=f"{symbol.upper()} has no options on {fs[-1][0]}")
    return {**out, "underlyings": oc.underlyings(df)}


@app.get("/db/results-implied-moves")
def results_implied_moves(days: int = Query(10, ge=1, le=30), store: DuckDBStore = Depends(get_store)) -> dict:
    """F&O stocks with results in the next `days`: the move their options price by the first expiry on or after the
    results date, the part attributable to the results day (normal days from 60-session realised volatility), and
    the stock's typical results-day move. Ratio > 1 = options expect a bigger reaction than this stock usually has."""
    import numpy as np
    import option_chain as oc
    import results_history as rh
    fs = oc.files(_fo_root())
    if not fs:
        return {"rows": [], "fo_date": None}
    df = oc.load(str(fs[-1][1]))
    fo = set(oc.underlyings(df))
    today = date.today()
    with store.reader() as con:
        ev = con.execute("""SELECT DISTINCT symbol, CAST(event_date AS VARCHAR) AS d FROM nse_events
                                    WHERE kind = 'RESULTS' AND event_date >= ?::DATE AND event_date <= ?::DATE""",
                                 [today.isoformat(), (today + timedelta(days=days)).isoformat()]).fetchall()
        ev = [(s_, d_) for s_, d_ in ev if s_ in fo]
        typical = rh.typical_moves(con, sorted({s_ for s_, _ in ev})) if ev else {}
    closes = store.adjusted_closes(sorted({s_ for s_, _ in ev}), (today - timedelta(days=120)).isoformat()) if ev else pd.DataFrame()
    rows = []
    for sym, d in sorted(ev, key=lambda x: x[1]):
        opts = df[(df["TckrSymb"] == sym) & df["FinInstrmTp"].isin(oc.OPTION_TYPES)]
        expiries = sorted(e for e in opts["XpryDt"].unique() if pd.Timestamp(e).date().isoformat() >= d)
        if not expiries:
            continue
        ch = oc.chain(df, sym, pd.Timestamp(expiries[0]).date().isoformat())
        em = ch.get("expected_move_pct")
        trade_day = pd.Timestamp(opts["TradDt"].iloc[0]).date()
        n = int(np.busday_count(trade_day + timedelta(days=1), pd.Timestamp(expiries[0]).date() + timedelta(days=1)))
        r = closes[sym].dropna().pct_change().dropna().tail(60) if sym in closes.columns else pd.Series(dtype=float)
        dvol = float(r.std() * 100) if len(r) >= 20 else None
        imp = {"event_sigma_pct": None, "event_abs_move_pct": None, "normal_daily_pct": None}
        method = None
        if em and len(expiries) >= 2:          # preferred: the options' own term structure
            ch2 = oc.chain(df, sym, pd.Timestamp(expiries[1]).date().isoformat())
            n2 = int(np.busday_count(trade_day + timedelta(days=1), pd.Timestamp(expiries[1]).date() + timedelta(days=1)))
            imp = oc.implied_event_move_term(em, n, ch2.get("expected_move_pct"), n2)
            method = "term" if imp["event_sigma_pct"] is not None else None
        if method is None and em and dvol:     # fallback: realised volatility for normal days (overstates the event)
            imp = {**oc.implied_event_move(em, n, dvol), "normal_daily_pct": round(dvol, 2)}
            method = "realised"
        t = typical.get(sym) or {}
        typ = t.get("avg_abs_move_pct")
        rows.append({"symbol": sym, "results_date": d, "expiry": ch.get("expiry"), "trading_days": n, "atm_iv": ch.get("atm_iv"),
                     "expected_move_pct": em, "daily_vol_pct": round(dvol, 2) if dvol else None, **imp,
                     "typical_move_pct": typ, "quarters": t.get("quarters"), "method": method,
                     "ratio": round(imp["event_abs_move_pct"] / typ, 2) if imp.get("event_abs_move_pct") and typ else None})
    return {"rows": rows, "fo_date": str(fs[-1][0]), "days": days}


_fo_eod_cache: dict[str, Any] = {}


@app.get("/db/option-chain-live/{symbol}")
def option_chain_live(symbol: str, expiry: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")) -> dict:
    """Live option chain from NSE (≈ real time in market hours, cached 30 s), computed exactly like the end-of-day
    chain: parity-forward IVs, max pain, OI walls. Lot size comes from the latest F&O bhavcopy."""
    global _nse_live
    import nse_live
    import option_chain as oc
    from datetime import datetime as _dt
    from bhavcopy import HEADERS
    if not re.fullmatch(r"[A-Za-z0-9&\-]{1,20}", symbol):
        raise HTTPException(status_code=422, detail="Bad symbol")
    sym = symbol.upper()
    if _nse_live is None:
        _nse_live = nse_live.NseLive(HEADERS)
    fs = oc.files(_fo_root())
    lot = None
    if fs:
        key = str(fs[-1][1])
        if _fo_eod_cache.get("key") != key:
            _fo_eod_cache.update(key=key, df=oc.load(key))
        eod = _fo_eod_cache["df"]
        o = eod[(eod["TckrSymb"] == sym) & eod["FinInstrmTp"].isin(oc.OPTION_TYPES)]
        if o["NewBrdLotQty"].notna().any():
            lot = int(o["NewBrdLotQty"].dropna().iloc[0])
    try:
        info = _nse_live.get(f"option-chain-contract-info?symbol={sym}", ttl_open=600)
        exps = info.get("expiryDates") or []
        if not exps:
            raise HTTPException(status_code=404, detail=f"{sym} has no live option chain")
        want = _dt.fromisoformat(expiry).strftime("%d-%b-%Y") if expiry else exps[0]
        if want not in exps:
            want = exps[0]
        kind = "Indices" if sym in oc.INDEX_SYMBOLS else "Equity"
        payload = _nse_live.get(f"option-chain-v3?type={kind}&symbol={sym}&expiry={want}", ttl_open=30)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"NSE live option chain unavailable: {exc}") from exc
    df = oc.live_frame(payload, sym, lot)
    out = oc.chain(df, sym)
    if not out.get("found"):
        raise HTTPException(status_code=404, detail=f"{sym}: empty live chain")
    out["expiries"] = [_dt.strptime(e, "%d-%b-%Y").date().isoformat() for e in exps]
    out["live"] = True
    out["as_of"] = (payload.get("records") or {}).get("timestamp")
    return out


@app.get("/db/participant-positioning")
def participant_positioning(days: int = Query(250, ge=20, le=1500), store: DuckDBStore = Depends(get_store)) -> dict:
    """Index-futures and index-options positioning by participant (FII, DII, PRO, CLIENT) from NSE's
    participant-wise OI file: latest snapshot with 1- and 5-session changes, and the FII long ratio history."""
    with store.reader() as con:
        last_day = con.execute("SELECT MAX(date) FROM nse_participant_oi").fetchone()[0]
        if last_day is None:
            raise HTTPException(status_code=404, detail="No participant OI stored")
        since = (pd.Timestamp(last_day) - pd.Timedelta(days=int(days * 1.6) + 10)).date().isoformat()
        df = con.execute("""
            SELECT date, client_type, fut_idx_long, fut_idx_short, opt_idx_call_long, opt_idx_call_short,
                   opt_idx_put_long, opt_idx_put_short
            FROM nse_participant_oi WHERE date >= ?::DATE ORDER BY date""", [since]).df()
    if df.empty:
        raise HTTPException(status_code=404, detail="No participant OI stored")
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["client_type"].isin(["FII", "DII", "PRO", "CLIENT"])]
    df["fut_net"] = df["fut_idx_long"] - df["fut_idx_short"]
    df["fut_long_pct"] = df["fut_idx_long"] / (df["fut_idx_long"] + df["fut_idx_short"]) * 100
    # net index options exposure in contracts: long calls − short calls − (long puts − short puts) (a bullishness proxy)
    df["opt_net_bull"] = (df["opt_idx_call_long"] - df["opt_idx_call_short"]) - (df["opt_idx_put_long"] - df["opt_idx_put_short"])
    dates = sorted(df["date"].unique())
    last, d1 = dates[-1], dates[-2] if len(dates) > 1 else dates[-1]
    d5 = dates[-6] if len(dates) > 5 else dates[0]
    snap = []
    for ct in ["FII", "DII", "PRO", "CLIENT"]:
        g = df[df["client_type"] == ct].set_index("date")
        if last not in g.index:
            continue
        r = g.loc[last]
        chg = lambda d: float(r["fut_net"] - g.loc[d, "fut_net"]) if d in g.index else None  # noqa: E731
        snap.append({"client_type": ct, "fut_long": float(r["fut_idx_long"]), "fut_short": float(r["fut_idx_short"]),
                     "fut_net": float(r["fut_net"]), "fut_long_pct": round(float(r["fut_long_pct"]), 1),
                     "fut_net_chg_1d": chg(d1), "fut_net_chg_5d": chg(d5), "opt_net_bull": float(r["opt_net_bull"])})
    fii = df[df["client_type"] == "FII"].sort_values("date").tail(days)
    return {"date": str(pd.Timestamp(last).date()), "snapshot": snap,
            "fii_history": [{"date": str(d.date()), "long_pct": round(float(lp), 1), "net": float(n)}
                            for d, lp, n in zip(fii["date"], fii["fut_long_pct"], fii["fut_net"])]}


_opt_hist_state: dict[str, Any] = {"running": False}


def _option_history_cache() -> Path:
    return _data_dir(get_settings()) / "nse_archive" / "derived" / "option_history.json"


def _refresh_option_history() -> None:
    import option_chain as oc
    if _opt_hist_state["running"]:
        return
    _opt_hist_state["running"] = True
    try:
        oc.update_history(_fo_root(), _option_history_cache())
    except Exception as exc:  # noqa: BLE001
        logger.warning("Option history update failed", error=str(exc))
    finally:
        _opt_hist_state["running"] = False


@app.get("/db/option-history/{symbol}")
def option_history(symbol: str, days: int = Query(260, ge=20, le=2000)) -> dict:
    """Daily ATM IV, PCR and max pain for NIFTY / BANKNIFTY (near expiry, from the cached F&O bhavcopies).
    Served from a derived cache; a background update adds any new sessions."""
    import json
    sym = symbol.upper()
    cache = _option_history_cache()
    hist = json.loads(cache.read_text()) if cache.is_file() else {}
    rows = hist.get(sym, [])
    latest_file = None
    try:
        import option_chain as oc
        fs = oc.files(_fo_root())
        latest_file = fs[-1][0].isoformat() if fs else None
    except Exception:  # noqa: BLE001
        pass
    if (not rows or (latest_file and rows[-1]["date"] < latest_file)) and not _opt_hist_state["running"]:
        threading.Thread(target=_refresh_option_history, name="option-history", daemon=True).start()
    return {"symbol": sym, "rows": rows[-days:], "updating": _opt_hist_state["running"] or not rows}


@app.get("/db/insider-buys")
def insider_buys(days: int = Query(60, ge=7, le=365), min_value: float = Query(1e6, ge=0),
                 store: DuckDBStore = Depends(get_store)) -> dict:
    """Recent insider open-market buying (promoters / directors / KMP, ≥ ₹10 lakh by default), per stock."""
    rows = store.insider_buys(days, min_value)
    meta = store.get_positions_meta().get("nse_insider_trades", {})
    return {"days": days, "min_value": min_value, "rows": rows, "count": len(rows), "data_through": meta.get("last")}


_fii_dii_state: dict[str, Any] = {"last_try": 0.0, "running": False, "error": None}


def _refresh_fii_dii(store: DuckDBStore) -> dict:
    import fii_dii
    from bhavcopy import HEADERS
    _fii_dii_state["running"], _fii_dii_state["last_try"] = True, time.time()
    try:
        df = fii_dii.fetch(HEADERS)
        n = store.upsert_fii_dii_cash(df)
        _fii_dii_state["error"] = None
        return {"rows": n, "date": str(df["date"].max()) if not df.empty else None}
    except Exception as exc:                       # NSE hiccups must not break the page
        _fii_dii_state["error"] = str(exc)[:200]
        raise
    finally:
        _fii_dii_state["running"] = False


@app.post("/db/fii-dii-cash/refresh")
def fii_dii_refresh(store: DuckDBStore = Depends(get_store)) -> dict:
    """Fetch today's FII/DII cash figures from NSE and store them (scheduled every evening)."""
    try:
        return _refresh_fii_dii(store)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"NSE FII/DII unavailable: {exc}") from exc


@app.get("/db/fii-dii-cash")
def fii_dii_cash(days: int = Query(90, ge=5, le=3650), store: DuckDBStore = Depends(get_store)) -> dict:
    """FII and DII cash-market net buying (₹ cr) as collected, with latest / 5-session / month-to-date sums. Starts
    a background refresh at most every 30 min, so the page fills itself even if the evening job was missed."""
    import fii_dii
    if not _fii_dii_state["running"] and time.time() - _fii_dii_state["last_try"] > 1800:
        def _bg() -> None:
            try:
                _refresh_fii_dii(store)
            except Exception:
                pass
        threading.Thread(target=_bg, daemon=True).start()
    rows = store.fii_dii_cash(days)
    return {"rows": rows, "summary": fii_dii.summarize(rows), "error": _fii_dii_state["error"]}


_nse_live: Any = None


@app.get("/db/live-movers")
def live_movers(universe: str = Query("FOSec", pattern="^(NIFTY|BANKNIFTY|NIFTYNEXT50|FOSec|SecGtr20|allSec)$")) -> dict:
    """NSE live market analysis: gainers / losers, most active, volume surges, 52-week highs / lows, OI spurts and
    every index's breadth. Cached 30 s in market hours (10 min outside); nothing stored."""
    global _nse_live
    import nse_live
    from bhavcopy import HEADERS
    if _nse_live is None:
        _nse_live = nse_live.NseLive(HEADERS)
    out = _nse_live.snapshot(universe)
    if len(out["errors"]) >= 7:
        raise HTTPException(status_code=502, detail=f"NSE live data unavailable: {next(iter(out['errors'].values()))}")
    return out


@app.get("/db/announcements")
def announcements(day: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")) -> dict:
    """Every NSE equity announcement of the day (default today), categorised (results, orders, rating, m&a, insider,
    capital, people, board, analyst, press, routine, other). Live from NSE, cached 60 s in market hours."""
    global _nse_live
    import nse_live
    from datetime import datetime as _dt
    from bhavcopy import HEADERS
    if _nse_live is None:
        _nse_live = nse_live.NseLive(HEADERS)
    try:
        return _nse_live.announcements(_dt.fromisoformat(day) if day else None)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"NSE announcements unavailable: {exc}") from exc


@app.get("/db/index-members")
def index_members(index: str = Query(..., min_length=3, max_length=60, pattern=r"^[A-Za-z0-9 &/\-.]+$"),
                  group: str = Query("SECTORAL INDICES", max_length=40)) -> dict:
    """Live members of an NSE index (MOV sector board drill-down); broad indices are capped at 50 names by NSE."""
    global _nse_live
    import nse_live
    from bhavcopy import HEADERS
    if _nse_live is None:
        _nse_live = nse_live.NseLive(HEADERS)
    try:
        return _nse_live.index_members(index, group)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"NSE index members unavailable: {exc}") from exc


@app.get("/db/nifty-live")
def nifty_live() -> dict:
    """NIFTY 50 from NSE's live index list (≈1 min delayed): the header falls back to it when ICICI isn't streaming."""
    global _nse_live
    import nse_live
    from bhavcopy import HEADERS
    if _nse_live is None:
        _nse_live = nse_live.NseLive(HEADERS)
    try:
        return _nse_live.index_quote("NIFTY 50")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"NSE index data unavailable: {exc}") from exc


@app.get("/db/index-intraday")
def index_intraday(index: str = Query("NIFTY 50", max_length=40, pattern=r"^[A-Za-z0-9 &\-]+$"),
                   minutes: int = Query(1, ge=1, le=30)) -> dict:
    """Intraday path of an NSE index for the latest session (≈1 min delayed), with the previous close."""
    global _nse_live
    import nse_live
    from bhavcopy import HEADERS
    if _nse_live is None:
        _nse_live = nse_live.NseLive(HEADERS)
    try:
        out = _nse_live.index_chart(index, minutes)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"NSE chart data unavailable: {exc}") from exc
    return {"index": index.upper(), "minutes": minutes, **out}


def _internals_dir() -> Path:
    return _data_dir(get_settings()) / "nse_archive" / "internals"


@app.post("/db/internals/sample")
def internals_sample() -> dict:
    """Take one market-internals sample (NSE allIndices: breadth + segment moves) and archive it for the day."""
    global _nse_live
    import market_internals as mi
    import nse_live
    from bhavcopy import HEADERS
    if _nse_live is None:
        _nse_live = nse_live.NseLive(HEADERS)
    try:
        snap = mi.snapshot(_nse_live.get("allIndices", ttl_open=15, ttl_closed=300))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"NSE index data unavailable: {exc}") from exc
    if snap is None:
        raise HTTPException(status_code=502, detail="NSE allIndices had no NIFTY 50 row")
    return {"stored": mi.append(_internals_dir(), snap), "sample": snap}


@app.get("/db/internals")
def internals(day: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")) -> dict:
    """The day's internals samples (default: the latest archived session) and a plain-language summary."""
    import market_internals as mi
    d = _internals_dir()
    if day is None:
        files = sorted(d.glob("*.jsonl")) if d.exists() else []
        day = files[-1].stem if files else date.today().isoformat()
    rows = mi.read(d, day)
    return {"day": day, "rows": rows, "summary": mi.summary(rows)}


@app.get("/db/archive-meta")
def archive_meta() -> dict:
    """File archives kept outside DuckDB (data/nse_archive/<name>): file count and the date range, from the
    YYYY-MM-DD in file names where present, else from modification times. Warehouse → NSE datasets."""
    import re as _re
    from datetime import datetime as _dt
    root = _data_dir(get_settings()) / "nse_archive"
    out: dict[str, dict] = {}
    for name in ("preopen", "internals", "financials", "ipo", "derived"):
        d = root / name
        files = [p for p in d.iterdir() if p.is_file()] if d.exists() else []
        days = sorted(m.group(0) for p in files if (m := _re.match(r"\d{4}-\d{2}-\d{2}", p.name)))
        mtimes = sorted(_dt.fromtimestamp(p.stat().st_mtime).date().isoformat() for p in files)
        first, last = (days[0], days[-1]) if days else ((mtimes[0], mtimes[-1]) if mtimes else (None, None))
        out[f"archive:{name}"] = {"rows": len(files), "first": first, "last": last}
    return out


@app.get("/db/prev-close")
def prev_close(symbols: str = Query(..., min_length=1, max_length=8000),
               before: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"), store: DuckDBStore = Depends(get_store)) -> dict:
    """Official NSE previous close per symbol: the last bhavcopy close (EQ/BE) dated before `before`. Quote feeds
    that skip a session (Yahoo dropped 12 Oct 2026) would otherwise compute a two-day change as 'today'."""
    syms = sorted({x.strip().upper() for x in symbols.split(",") if x.strip()})[:500]
    if not syms:
        return {"before": before, "prev": {}}
    with store.reader() as con:
        rows = con.execute("""
            SELECT symbol, close, date FROM (
                SELECT symbol, close, date, row_number() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn
                FROM nse_bhavcopy WHERE list_contains(?, symbol) AND series IN ('EQ', 'BE')
                  AND date < ?::DATE AND date >= ?::DATE - INTERVAL 15 DAY) WHERE rn = 1""", [syms, before, before]).fetchall()
    return {"before": before, "prev": {s: {"close": float(c), "date": str(d)[:10]} for s, c, d in rows if c}}


@app.get("/db/index-contribution")
def index_contribution(index: str = Query("NIFTY 50", pattern="^(NIFTY 50|NIFTY BANK|NIFTY NEXT 50|NIFTY IT)$"),
                       store: DuckDBStore = Depends(get_store)) -> dict:
    """Who moved the index today, in index points. NSE does not publish live weights, so they are rebuilt:
    free-float market cap ≈ shares (latest results filing) × previous close × (1 − promoter holding, latest
    shareholding filing). points = previous index level × weight × the stock's % change. The sum is compared with
    the index's actual move so the approximation's error is visible (sector indices also cap single weights)."""
    global _nse_live
    import financials as fin
    import nse_live
    from bhavcopy import HEADERS
    if _nse_live is None:
        _nse_live = nse_live.NseLive(HEADERS)
    kind = "Broad Market Indices" if index in ("NIFTY 50", "NIFTY NEXT 50") else "Sectoral Indices"
    try:
        rows = _nse_live.get(f"heatmap-symbols?type={kind.replace(' ', '%20')}&indices={index.replace(' ', '%20')}", ttl_open=60)
        idx = nse_live.parse_index_quote(_nse_live.get("allIndices", ttl_open=15, ttl_closed=300), index)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"NSE data unavailable: {exc}") from exc
    members = nse_live.parse_heatmap(rows if isinstance(rows, list) else (rows or {}).get("data", []))
    syms = sorted(members)
    with store.reader() as con:
        promo = dict(con.execute("""
            SELECT symbol, promoter_pct FROM (
                SELECT symbol, promoter_pct, row_number() OVER (PARTITION BY symbol ORDER BY period_end DESC) AS rn
                FROM nse_shareholding WHERE list_contains(?, symbol)) WHERE rn = 1""", [syms]).fetchall())
    root = _data_dir(get_settings()) / "nse_archive" / "financials"
    out, missing = [], []
    for sym in syms:
        q = members[sym]
        last, chg = q.get("ltp"), q.get("change_pct")
        cache = fin.load(root, sym)
        shares = fin.shares_estimate(fin.with_growth(cache["quarters"])) if cache and cache.get("quarters") else None
        if last is None or chg is None or not shares:
            missing.append(sym)
            continue
        prev_px = last / (1 + chg / 100)
        ff = 1 - (promo.get(sym) or 0) / 100
        out.append({"symbol": sym, "change_pct": chg, "ffmc": shares * prev_px * ff, "promoter_pct": promo.get(sym)})
    total = sum(r["ffmc"] for r in out)
    prev_level = idx.get("previous_close") or (idx["last"] - idx["change"] if idx.get("last") is not None and idx.get("change") is not None else None)
    for r in out:
        r["weight_pct"] = round(r["ffmc"] / total * 100, 2) if total else None
        r["points"] = round(prev_level * r["ffmc"] / total * r["change_pct"] / 100, 2) if total and prev_level else None
        r.pop("ffmc")
    out.sort(key=lambda r: -(r["points"] or 0))
    explained = round(sum(r["points"] or 0 for r in out), 1)
    return {"index": index, "last": idx.get("last"), "change": idx.get("change"), "change_pct": idx.get("change_pct"),
            "explained_points": explained, "members": out, "missing": missing, "time": idx.get("time")}


@app.get("/db/index-memb")
def index_memb(index: str = Query("NIFTY 50", pattern="^(NIFTY 50|NIFTY BANK|NIFTY NEXT 50|NIFTY IT)$"),
               store: DuckDBStore = Depends(get_store)) -> dict:
    """MEMB (not /db/index-members, which is MOV's live sector drill-down): an index's members with their rebuilt weight and today's points (index-contribution), returns over
    1M / 3M / YTD / 1Y on adjusted closes, distance from the 52-week high, and P/E, market cap and last-quarter
    growth from the NSE results filings. Plus the index's breadth, top-5 concentration and weight-implied P/E."""
    import financials as fin
    base = index_contribution(index, store)
    rows = base["members"]
    syms = [r["symbol"] for r in rows]
    today = pd.Timestamp.now().normalize()
    closes = store.adjusted_closes(syms, (today - pd.Timedelta(days=400)).date().isoformat()) if syms else pd.DataFrame()
    root = _data_dir(get_settings()) / "nse_archive" / "financials"

    def ret(c: pd.Series, since: pd.Timestamp) -> float | None:
        b = c[c.index <= since]
        return round(float((c.iloc[-1] / b.iloc[-1] - 1) * 100), 2) if len(b) and len(c) else None
    for r in rows:
        c = closes[r["symbol"]].dropna() if r["symbol"] in closes.columns else pd.Series(dtype=float)
        r.update({"ret_1m": ret(c, today - pd.Timedelta(days=30)), "ret_3m": ret(c, today - pd.Timedelta(days=91)),
                  "ret_ytd": ret(c, pd.Timestamp(today.year - 1, 12, 31)), "ret_1y": ret(c, today - pd.Timedelta(days=365)),
                  "from_high_pct": round(float((c.iloc[-1] / c[c.index >= today - pd.Timedelta(days=365)].max() - 1) * 100), 2) if len(c) else None,
                  "close": round(float(c.iloc[-1]), 2) if len(c) else None})
        cache = fin.load(root, r["symbol"])
        q = fin.with_growth(cache["quarters"]) if cache and cache.get("quarters") else []
        v = fin.valuation(q, r["close"]) if q else {}
        last_q = max(q, key=lambda x: x.get("period_end") or "") if q else {}     # the cache is not in date order
        r.update({"pe": (v or {}).get("pe"), "mcap": (v or {}).get("mcap"), "pat_yoy": last_q.get("pat_yoy"),
                  "pat_turn": last_q.get("pat_yoy_turn"), "revenue_yoy": last_q.get("revenue_yoy"),
                  "quarter": last_q.get("period_end")})
    pct = _pe_percentiles()
    for r in rows:   # contribution to the index's YTD move (pp): today's weight × YTD return (start weights drift)
        r["pe_pctl"] = (pct.get(r["symbol"]) or {}).get("percentile")
        r["ytd_contrib_pp"] = round((r["weight_pct"] or 0) / 100 * r["ret_ytd"], 2) if r.get("ret_ytd") is not None else None
    w = [(r["weight_pct"] or 0) / 100 for r in rows]
    priced = [(wi, r["pe"]) for wi, r in zip(w, rows) if r.get("pe") and r["pe"] > 0]
    # weight-implied P/E = Σw / Σ(w / P/E): the index's price ÷ the earnings its weights buy (loss-makers left out)
    implied_pe = round(sum(wi for wi, _ in priced) / sum(wi / pe for wi, pe in priced), 1) if priced else None
    top5 = round(sum(sorted((r["weight_pct"] or 0 for r in rows), reverse=True)[:5]), 1)
    return {**base, "members": rows,
            "summary": {"members": len(rows), "up": sum(1 for r in rows if (r["change_pct"] or 0) > 0),
                        "down": sum(1 for r in rows if (r["change_pct"] or 0) < 0), "top5_weight_pct": top5,
                        "implied_pe": implied_pe, "pe_coverage_pct": round(sum(wi for wi, _ in priced) * 100) if priced else 0,
                        "near_high": sum(1 for r in rows if r["from_high_pct"] is not None and r["from_high_pct"] >= -5),
                        "ytd_explained_pct": round(sum(r["ytd_contrib_pp"] or 0 for r in rows), 2),
                        "index_ytd_pct": _index_ytd(index)}}


def _index_ytd(name: str) -> float | None:
    """The index's own YTD % from the valuation-history closes (NSE daily index files)."""
    h = _index_valuation_history()
    if h is None:
        return None
    g = h[h["index"] == name]
    year = str(pd.Timestamp.now().year)
    prev, cur = g[g["date"] < f"{year}-01-01"], g[g["date"] >= f"{year}-01-01"]
    if prev.empty or cur.empty:
        return None
    return round(float((cur["close"].iloc[-1] / prev["close"].iloc[-1] - 1) * 100), 2)


VALUATION_INDICES = ("NIFTY 50", "NIFTY NEXT 50", "NIFTY 500", "NIFTY MIDCAP 150", "NIFTY SMALLCAP 250", "NIFTY BANK",
                     "NIFTY IT", "NIFTY FMCG", "NIFTY PHARMA", "NIFTY AUTO", "NIFTY METAL", "NIFTY REALTY", "NIFTY ENERGY")


@app.get("/db/index-valuation")
def index_valuation() -> dict:
    """NSE's own P/E, P/B and dividend yield per index (allIndices), with 1-month / 1-year moves. After the close the
    day's figures are appended once to nse_archive/derived/index_valuation.jsonl, so a valuation history builds up."""
    global _nse_live
    import json as _json
    import nse_live
    from bhavcopy import HEADERS
    from datetime import datetime as _dt
    if _nse_live is None:
        _nse_live = nse_live.NseLive(HEADERS)
    try:
        payload = _nse_live.get("allIndices", ttl_open=15, ttl_closed=300)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"NSE index data unavailable: {exc}") from exc

    def num(v: Any) -> float | None:
        try:
            return float(str(v).replace(",", ""))
        except (TypeError, ValueError):
            return None
    rows = {r.get("index"): r for r in payload.get("data") or []}
    out = {}
    for name in VALUATION_INDICES:
        r = rows.get(name)
        if r:
            out[name] = {"last": num(r.get("last")), "change_pct": num(r.get("percentChange")), "pe": num(r.get("pe")),
                         "pb": num(r.get("pb")), "dy": num(r.get("dy")), "chg_30d": num(r.get("perChange30d")),
                         "chg_365d": num(r.get("perChange365d"))}
    ts = str(payload.get("timestamp") or "")
    try:
        day = _dt.strptime(ts[:11], "%d-%b-%Y").date().isoformat()
        after_close = ts[12:17] >= "15:30"
    except ValueError:
        day, after_close = None, False
    hist_path = _data_dir(get_settings()) / "nse_archive" / "derived" / "index_valuation.jsonl"
    if day and after_close and out:
        try:
            have = hist_path.read_text(encoding="utf-8") if hist_path.exists() else ""
            if f'"day": "{day}"' not in have:
                hist_path.parent.mkdir(parents=True, exist_ok=True)
                with hist_path.open("a", encoding="utf-8") as f:
                    f.write(_json.dumps({"day": day, "indices": {k: {x: v[x] for x in ("last", "pe", "pb", "dy")} for k, v in out.items()}}) + "\n")
        except OSError:
            pass
    history = []
    try:
        history = [_json.loads(l) for l in hist_path.read_text(encoding="utf-8").splitlines() if l.strip()][-500:]
    except (OSError, ValueError):
        history = []
    # long history from NSE's daily index files (scripts/backfill_index_valuation.py): where today's P/E sits
    long = _index_valuation_history()
    vs_hist = valuation_vs_history(long, {k: v.get("pe") for k, v in out.items()})
    n50_now = (out.get("NIFTY 50") or {}).get("pe")
    rel_hist = relative_vs_history(long, {k: v.get("pe") for k, v in out.items() if k != "NIFTY 50"}, n50_now)
    return {"timestamp": ts, "indices": out, "history_days": len(history), "vs_history": vs_hist,
            "rel_history": rel_hist, "pe_basis_from": PE_BASIS_FROM}


@app.get("/db/index-valuation-history")
def index_valuation_history(index: str = Query("NIFTY 50", max_length=40),
                            metric: str = Query("pe", pattern="^(pe|pb|dy|rel)$")) -> dict:
    """Weekly history of one index's P/E, P/B or dividend yield (NSE daily index files), with today's percentile among
    days on the same earnings basis (consolidated, from PE_BASIS_FROM)."""
    h = _index_valuation_history()
    if h is None:
        return {"index": index, "metric": metric, "points": [], "stats": None, "basis_from": None}
    if metric == "rel":     # P/E relative to NIFTY 50's on the same day (mid / small-cap premium)
        a = h[h["index"] == index.upper()][["date", "pe"]]
        b = h[h["index"] == "NIFTY 50"][["date", "pe"]].rename(columns={"pe": "n50"})
        g = a.merge(b, on="date")
        g = g[(g["pe"] > 0) & (g["n50"] > 0)].assign(rel=lambda x: x["pe"] / x["n50"])
    else:
        g = h[(h["index"] == index.upper()) & (h[metric] > 0)]
    pts = [{"date": d, "v": float(v)} for d, v in zip(g["date"].iloc[::5], g[metric].iloc[::5])]
    if len(g) and (not pts or pts[-1]["date"] != g["date"].iloc[-1]):
        pts.append({"date": str(g["date"].iloc[-1]), "v": float(g[metric].iloc[-1])})   # always end on the latest day
    basis = BASIS_FROM[metric]
    same = g[g["date"] >= basis][metric]
    stats = None
    if len(same) >= 250:
        now = float(same.iloc[-1])
        stats = {"now": now, "pctl": round(float((same < now).mean() * 100)), "median": round(float(same.median()), 2),
                 "p25": round(float(same.quantile(0.25)), 2), "p75": round(float(same.quantile(0.75)), 2),
                 "low": round(float(same.min()), 2), "high": round(float(same.max()), 2),
                 "p05": round(float(same.quantile(0.05)), 2), "p95": round(float(same.quantile(0.95)), 2),
                 "since": str(g[g["date"] >= basis]["date"].min()), "asof": str(g["date"].iloc[-1]), "days": int(len(same))}
    breaks = basis > str(g["date"].min()) if len(g) else False
    return {"index": index.upper(), "metric": metric, "points": pts, "stats": stats, "basis_from": basis if breaks else None}


@app.get("/db/index-daily")
def index_daily(symbol: str = Query("NIFTY50", pattern="^[A-Z0-9]{3,20}$"), days: int = Query(1500, ge=5, le=6000),
                store: DuckDBStore = Depends(get_store)) -> dict:
    """Daily closes of an index from market_index_daily (NIFTY50 …), oldest first: for relative-strength charts."""
    df = store.get_index_daily(symbol)
    if df.empty:
        raise HTTPException(status_code=404, detail=f"no daily history for {symbol}")
    df = df.tail(days)
    return {"symbol": symbol, "rows": [{"date": str(d)[:10], "close": float(c)} for d, c in zip(df["date"], df["close"])]}


_surv_cache: dict = {"at": 0.0, "data": None}


@app.get("/db/surveillance")
def surveillance_flags(symbols: str = Query("", max_length=8000), all_flagged: bool = False) -> dict:
    """NSE surveillance / risk flags (ASM, GSM, ESM, IRP, tight price bands, trade-to-trade, F&O ban) for `symbols`,
    plus the market-wide F&O ban list and counts. Files are NSE's daily ones, re-read at most hourly."""
    import surveillance as sv
    from bhavcopy import HEADERS
    if _surv_cache["data"] is None or time.time() - _surv_cache["at"] > 3600:
        _surv_cache.update(at=time.time(), data=sv.load(_data_dir(get_settings()) / "nse_archive" / "surveillance", HEADERS))
    data = _surv_cache["data"]
    want = [x.strip().upper() for x in symbols.split(",") if x.strip()][:500]
    counts: dict[str, int] = {}
    for v in data["surveillance"].values():
        for label in v["measures"]:
            counts[label] = counts.get(label, 0) + 1
    out = {"flags": {sym: sv.flags_for(sym, data) for sym in want}, "ban": data["ban"], "dates": data["dates"],
           "counts": counts}
    if all_flagged:          # every stock with at least one chip: for screens (FUND) that hide or mark them
        universe = set(data["surveillance"]) | set(data["ban"]) | {k for k, v in data["bands"].items()
                                                                    if (v.get("band") is not None and v["band"] <= 5) or v.get("series") in ("BE", "BZ", "SZ")}
        out["flagged"] = {sym: [c["code"] for c in f["chips"]] for sym in sorted(universe)
                          if (f := sv.flags_for(sym, data))["chips"]}
    return out


@app.get("/db/market-holidays")
def market_holidays() -> dict:
    """NSE equity (CM) trading holidays from NSE's holiday master, weekdays only (a weekend holiday closes nothing).
    These are exchange holidays: government data releases follow the government calendar, not this one."""
    global _nse_live
    import nse_live
    from bhavcopy import HEADERS
    from datetime import datetime as _dt
    if _nse_live is None:
        _nse_live = nse_live.NseLive(HEADERS)
    try:
        d = _nse_live.get("holiday-master?type=trading", ttl_open=86_400, ttl_closed=86_400)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"NSE holiday list unavailable: {exc}") from exc
    out = []
    for h in (d or {}).get("CM") or []:
        try:
            day = _dt.strptime(str(h.get("tradingDate")), "%d-%b-%Y").date()
        except ValueError:
            continue
        if day.weekday() < 5:
            out.append({"date": day.isoformat(), "weekday": day.strftime("%a"), "description": str(h.get("description") or "").rstrip("*").strip()})
    return {"holidays": sorted(out, key=lambda x: x["date"]), "source": "nseindia.com/api/holiday-master?type=trading"}


@app.get("/db/yield-gap")
def yield_gap_view() -> dict:
    """Equity vs bonds: NIFTY 50 earnings yield (NSE P/E) minus India's 10-year yield (FRED monthly, ~3 months late)."""
    import yield_gap as yg
    h = _index_valuation_history()
    nifty = h[h["index"] == "NIFTY 50"][["date", "pe"]] if h is not None else pd.DataFrame(columns=["date", "pe"])
    y10 = yg.india_10y(_data_dir(get_settings()) / "nse_archive" / "derived")
    return yg.yield_gap(nifty, y10)


@app.get("/db/seasonality")
def seasonality_view(symbol: str = Query("NIFTY 50", max_length=40), store: DuckDBStore = Depends(get_store)) -> dict:
    """SEAG: month-by-month returns of an NSE index (NSE daily index files, from 2012) or a stock (adjusted bhavcopy
    closes), with per-month averages, hit rates and the current month so far."""
    import seasonality as sea
    name = symbol.upper().strip()
    path = _data_dir(get_settings()) / "nse_archive" / "derived" / "index_valuation_history.csv"
    closes = None
    kind = "stock"
    if name.startswith("NIFTY"):
        try:
            h = pd.read_csv(path, usecols=["date", "index", "close"])
        except (OSError, ValueError):
            h = pd.DataFrame(columns=["date", "index", "close"])
        g = h[h["index"] == name]
        if len(g):
            closes, kind = pd.Series(g["close"].to_numpy(), index=pd.to_datetime(g["date"])), "index"
        elif " " in name:
            raise HTTPException(status_code=404, detail=f"{name}: no index history; available: {', '.join(sorted(h['index'].unique()))}")
    if closes is None:
        if not re.fullmatch(r"[A-Z0-9&\-]{1,20}", name):
            raise HTTPException(status_code=422, detail="Bad symbol")
        wide = store.adjusted_closes([name], "2000-01-01")
        if wide is None or wide.empty or name not in wide.columns:
            raise HTTPException(status_code=404, detail=f"{name}: no price history")
        closes = wide[name]
    return {"symbol": name, "kind": kind, **sea.seasonality(closes)}


# NSE moved index P/E and dividend yield to a consolidated basis on 31 Mar 2021: NIFTY's P/E fell 40.4 → 33.2 and its
# yield 1.07% → 0.96% with the index flat; P/B did not change (4.21 → 4.20). P/E and yield percentiles therefore compare
# today only with days from the change; P/B uses the whole history. The chart shows both, with the break marked.
PE_BASIS_FROM = "2021-03-31"
BASIS_FROM = {"pe": PE_BASIS_FROM, "dy": PE_BASIS_FROM, "pb": "2000-01-01", "rel": PE_BASIS_FROM}
_ivh_cache: dict = {"mtime": None, "df": None}


def _index_valuation_history() -> pd.DataFrame | None:
    """The backfilled index valuation history (date, index, close, pe, pb, dy), sorted, positive P/E only; re-read
    only when the file changes (the MKT panel refreshes every 15 s)."""
    path = _data_dir(get_settings()) / "nse_archive" / "derived" / "index_valuation_history.csv"
    try:
        mtime = path.stat().st_mtime
        if mtime != _ivh_cache["mtime"]:
            h = pd.read_csv(path)
            _ivh_cache.update(mtime=mtime, df=h[h["pe"] > 0].sort_values(["index", "date"]).reset_index(drop=True))
    except (OSError, ValueError, KeyError):
        return None
    return _ivh_cache["df"]


def relative_vs_history(h: pd.DataFrame | None, today_pe: dict[str, float | None], n50_pe: float | None,
                        basis_from: str = PE_BASIS_FROM, min_days: int = 250) -> dict[str, dict]:
    """Per index: today's P/E ÷ NIFTY 50's P/E, and where that ratio sits among same-basis days (the mid / small-cap
    premium, or a sector's discount, against its own history)."""
    out: dict[str, dict] = {}
    if h is None or h.empty or not n50_pe:
        return out
    n = h[(h["index"] == "NIFTY 50") & (h["date"] >= basis_from)][["date", "pe"]].rename(columns={"pe": "n50"})
    for name, now in today_pe.items():
        if not now:
            continue
        g = h[(h["index"] == name) & (h["date"] >= basis_from)][["date", "pe"]].merge(n, on="date")
        r = (g["pe"] / g["n50"])[g["n50"] > 0]
        if len(r) < min_days:
            continue
        ratio = now / n50_pe
        out[name] = {"ratio": round(ratio, 2), "pctl": round(float((r < ratio).mean() * 100)),
                     "median": round(float(r.median()), 2), "p25": round(float(r.quantile(0.25)), 2),
                     "p75": round(float(r.quantile(0.75)), 2)}
    return out


def valuation_vs_history(h: pd.DataFrame | None, today_pe: dict[str, float | None],
                         basis_from: str = PE_BASIS_FROM, min_days: int = 250) -> dict[str, dict]:
    """Per index: today's P/E percentile among same-basis trading days (from `basis_from`), with the median, middle
    half and range. Indices with fewer than `min_days` same-basis days are left out."""
    out: dict[str, dict] = {}
    if h is None or h.empty:
        return out
    for name, now in today_pe.items():
        g = h[(h["index"] == name) & (h["date"] >= basis_from)]
        if len(g) < min_days or not now:
            continue
        pe = g["pe"]
        out[name] = {"pctl": round(float((pe < now).mean() * 100)), "median": round(float(pe.median()), 1),
                     "p25": round(float(pe.quantile(0.25)), 1), "p75": round(float(pe.quantile(0.75)), 1),
                     "low": round(float(pe.min()), 1), "high": round(float(pe.max()), 1),
                     "p05": round(float(pe.quantile(0.05)), 1), "p95": round(float(pe.quantile(0.95)), 1),   # loss years blow up min/max
                     "since": str(g["date"].min()), "days": int(len(g))}
    return out


@app.get("/db/indices-live")
def indices_live(names: str = Query("NIFTY 50,NIFTY BANK,INDIA VIX", max_length=400)) -> dict:
    """Several NSE indices from one allIndices read (≈1 min delayed in session; last close otherwise): the macro
    tape's Indian rows. Yahoo's index quotes can lag a whole session after the close."""
    global _nse_live
    import nse_live
    from bhavcopy import HEADERS
    if _nse_live is None:
        _nse_live = nse_live.NseLive(HEADERS)
    try:
        payload = _nse_live.get("allIndices", ttl_open=15, ttl_closed=300)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"NSE index data unavailable: {exc}") from exc
    out = {}
    for name in [n.strip().upper() for n in names.split(",") if n.strip()][:12]:
        q = nse_live.parse_index_quote(payload, name)
        if q.get("last") is not None:
            out[name] = q
    return {"indices": out, "timestamp": payload.get("timestamp")}


@app.get("/db/gift-nifty")
def gift_nifty() -> dict:
    """GIFT NIFTY (NSE IX) and the gap it implies against NIFTY 50's last close, from NSE's market status."""
    global _nse_live
    import nse_live
    from bhavcopy import HEADERS
    if _nse_live is None:
        _nse_live = nse_live.NseLive(HEADERS)
    try:
        return _nse_live.gift_nifty()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"NSE market status unavailable: {exc}") from exc


@app.get("/db/live-quotes")
def live_quotes() -> dict:
    """Live quotes (≈1 min delayed) for ~300 large and mid caps, from NSE's heatmap lists (the MKT map's LIVE mode)."""
    global _nse_live
    import nse_live
    from bhavcopy import HEADERS
    if _nse_live is None:
        _nse_live = nse_live.NseLive(HEADERS)
    out = _nse_live.heatmap_quotes()
    if not out["quotes"]:
        raise HTTPException(status_code=502, detail="NSE heatmap unavailable")
    return out


@app.get("/db/basket-risk")
def basket_risk_endpoint(symbols: str = Query(..., min_length=1, max_length=2000), days: int = Query(365, ge=90, le=1100),
                         weights: str | None = Query(None, max_length=2000, description="comma-separated, same order as symbols"),
                         store: DuckDBStore = Depends(get_store)) -> dict:
    """Risk profile of a list of NSE symbols (comma-separated, ≤ 60): per-stock vol / beta / return / max drawdown and
    the equal-weight basket's vol, beta, drawdown, average correlation and diversification ratio."""
    import basket_risk as br
    syms = list(dict.fromkeys(s.strip().upper() for s in symbols.split(",") if s.strip()))[:60]
    rets, nifty = store.basket_returns(syms, days)
    for s in syms:
        if s not in rets.columns:
            rets[s] = float("nan")
    w = None
    if weights:
        try:
            vals = [float(x) for x in weights.split(",")]
        except ValueError:
            raise HTTPException(status_code=422, detail="weights must be numbers") from None
        raw = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        w = {s: v for s, v in zip(raw, vals)}
    return br.basket_risk(rets[syms], nifty, weights=w)


_ipo_feed: Any = None


@app.get("/db/ipo")
def ipo_monitor(months: int = Query(24, ge=3, le=120), kind: str = Query("Mainboard", pattern="^(Mainboard|SME)$"),
                store: DuckDBStore = Depends(get_store)) -> dict:
    """Open / forthcoming IPOs with live subscription, and the listing scorecard of the last `months` (NSE + bhavcopy).
    The first call starts a background fetch of past bid books (≈ 0.7 s each, cached on disk for good)."""
    global _ipo_feed
    import httpx
    import ipo_monitor as im
    from bhavcopy import HEADERS
    from datetime import timedelta
    if _ipo_feed is None:
        _ipo_feed = im.IpoFeed(_data_dir(get_settings()) / "nse_archive" / "ipo", HEADERS)
    feed = _ipo_feed
    try:
        upcoming = im.parse_upcoming(feed.upcoming())
        current = im.parse_upcoming(feed.current())
        past_all = feed.past()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"NSE IPO data unavailable: {exc}") from exc
    # merge: current (open today) wins over the forthcoming list; attach the live bid book to open issues
    issues = {r["symbol"]: r for r in upcoming}
    for r in current:
        issues[r["symbol"]] = {**issues.get(r["symbol"], {}), **{k: v for k, v in r.items() if v is not None}, "status": "Open"}
    today = date.today().isoformat()
    for r in issues.values():
        if r.get("start") and r.get("end") and r["start"] <= today <= r["end"]:
            r["status"] = "Open"
        r["days_left"] = im.days_left(r.get("end"))
        r["bids"] = None
        if r["status"] == "Open" and r.get("series") != "SME":
            try:
                r["bids"] = im.parse_bids(feed.detail(r["symbol"], "EQ"))
            except Exception:
                pass
    since = (date.today() - timedelta(days=int(months * 30.5))).isoformat()
    past = [r for r in im.parse_past(past_all, im.SME if kind == "SME" else im.MAINBOARD) if r["listing_date"] >= since]
    rows = im.scorecard(past, store.listing_paths([r["symbol"] for r in past], since))
    if kind == "Mainboard":
        feed.warm_details(past, limit=len(past))
        for r in rows:
            b = feed.cached_bids(r["symbol"]) or {}
            r.update({k: b.get(k) for k in ("qib", "nii", "retail", "total")})
    order = {"Open": 0, "Forthcoming": 1}
    return {"issues": sorted(issues.values(), key=lambda r: (order.get(r.get("status") or "", 2), r.get("end") or "")),
            "recent": rows, "buckets": im.buckets(rows) if kind == "Mainboard" else [],
            "kind": kind, "months": months, "details": dict(feed.warming),
            "bhavcopy_through": store.get_positions_meta().get("nse_bhavcopy", {}).get("last")}


_preopen_feed: Any = None


@app.get("/db/preopen")
def preopen(key: str = Query("FO", pattern="^(NIFTY|BANKNIFTY|FO|ALL)$")) -> dict:
    """NSE pre-open call auction (09:00–09:08 IST): IEP, gap and buy/sell imbalance per stock. Cached 20 s while the
    auction runs, 10 min otherwise; each session's final book is archived under data/nse_archive/preopen."""
    global _preopen_feed
    import httpx
    import preopen as po
    from bhavcopy import HEADERS
    if _preopen_feed is None:
        _preopen_feed = po.PreOpenFeed(_data_dir(get_settings()) / "nse_archive" / "preopen", HEADERS)
    try:
        return _preopen_feed.get(key)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"NSE pre-open unavailable: {exc}") from exc


@app.get("/db/deals")
def deals_monitor(days: int = Query(10, ge=1, le=120), min_value: float = Query(1e7, ge=0),
                  kind: str = Query("all", pattern="^(all|bulk|block)$"),
                  store: DuckDBStore = Depends(get_store)) -> dict:
    """Bulk and block deals of the last `days`, netted per client per stock per day (≥ ₹1 cr by default)."""
    import deals_monitor as dm
    deals, px = store.recent_deals(days)
    if kind != "all":
        deals = deals[deals["kind"] == kind]
    rows = dm.build_deals(deals, px, min_value)
    if rows:   # split-safe "since deal": adjusted closes (the raw ones in px are for share-of-volume only)
        adj = store.adjusted_closes(sorted({r["symbol"] for r in rows}), str(date.today() - timedelta(days=days + 10)))
        for r in rows:
            r["since_pct"] = store.move_since(adj, r["symbol"], r["date"])
    meta = store.get_positions_meta().get("nse_deals", {})
    return {"days": days, "min_value": min_value, "kind": kind, "rows": rows[:1500], "count": len(rows),
            "summary": dm.summarize(rows), "data_through": meta.get("last")}


@app.get("/db/short-selling")
def short_selling_view(days: int = Query(20, ge=1, le=120), store: DuckDBStore = Depends(get_store)) -> dict:
    """Institutional short selling over the last `days` sessions: per stock, quantity shorted, days with a short-sale
    disclosure, shorted quantity as % of all shares traded in the window, and the price move over the window."""
    import deals_monitor as dm
    with store.reader() as con:
        dates = [d for (d,) in con.execute(
            "SELECT DISTINCT date FROM nse_bhavcopy ORDER BY date DESC LIMIT ?", [days]).fetchall()]
        if not dates:
            return {"days": days, "rows": [], "count": 0}
        start = min(dates)
        shorts = con.execute("SELECT date, symbol, qty FROM nse_deals WHERE kind = 'short' AND date >= ?", [start]).df()
        syms = sorted(set(shorts["symbol"])) if not shorts.empty else []
        vol = con.execute("""SELECT date, symbol, SUM(volume) AS volume FROM nse_bhavcopy
                                     WHERE date >= ? AND series IN ('EQ', 'BE', 'BZ') AND list_contains(?, symbol)
                                     GROUP BY date, symbol""", [start, syms]).df() if syms else pd.DataFrame()
    rows = dm.short_selling(shorts, vol)
    if rows:
        adj = store.adjusted_closes([r["symbol"] for r in rows], str(start))
        for r in rows:
            r["move_pct"] = store.move_since(adj, r["symbol"], start)
    meta = store.get_positions_meta().get("nse_deals", {})
    return {"days": days, "from": str(start), "rows": rows[:500], "count": len(rows), "data_through": meta.get("last")}


@app.get("/db/holding-changes")
def holding_changes(store: DuckDBStore = Depends(get_store)) -> dict:
    """Ownership shifts: each covered stock's latest shareholding filing vs the previous one (percentage points)."""
    rows = store.holding_changes()
    meta = store.get_positions_meta().get("nse_shareholding", {})
    return {"rows": rows, "count": len(rows), "data_through": meta.get("last")}


@app.get("/db/mtf-monitor")
def mtf_monitor(lookback: int = Query(20, ge=5, le=120), min_amount_cr: float = Query(0, ge=0),
                store: DuckDBStore = Depends(get_store)) -> dict:
    """Margin-trading crowding: market MTF book history and per-stock funded amount, change and days-to-unwind."""
    out = store.mtf_monitor(lookback)
    if min_amount_cr:
        out["stocks"] = [r for r in out["stocks"] if (r["amount_cr"] or 0) >= min_amount_cr]
    return out


@app.get("/db/crash-filter")
def crash_filter_status(store: DuckDBStore = Depends(get_store)) -> dict:
    """The Decision Desk's crash filter today: NIFTY 50 vs its 200-day average (same series the Desk uses),
    how far NIFTY must move to flip it, and the next monthly signal date (last weekday of the month; NSE holidays
    are not modelled, so the actual signal can be a day earlier)."""
    import calendar
    n50 = store.get_index_daily("NIFTY50")
    if n50.empty:
        raise HTTPException(status_code=404, detail="No NIFTY 50 history")
    c = pd.Series(n50["close"].to_numpy(dtype=float), index=pd.to_datetime(n50["date"])).sort_index()
    sma = c.rolling(200, min_periods=180).mean()
    last, avg = float(c.iloc[-1]), float(sma.iloc[-1])
    today = date.today()
    y, m = today.year, today.month
    d = date(y, m, calendar.monthrange(y, m)[1])
    while d.weekday() >= 5:
        d = date.fromordinal(d.toordinal() - 1)
    if d < today:
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        d = date(y, m, calendar.monthrange(y, m)[1])
        while d.weekday() >= 5:
            d = date.fromordinal(d.toordinal() - 1)
    days_below = int((c < sma)[::-1].cumprod().sum()) if last < avg else 0
    return {"date": str(c.index[-1].date()), "nifty": round(last, 2), "sma200": round(avg, 2),
            "risk_on": last > avg, "gap_pct": round((last / avg - 1) * 100, 2),
            "move_needed_pct": round(max(0.0, (avg / last - 1) * 100), 2),
            "sessions_below": days_below, "next_signal_date": d.isoformat()}


@app.get("/db/nse-positions-meta")
def nse_positions_meta(store: DuckDBStore = Depends(get_store)) -> dict:
    return store.get_positions_meta()


class IndexRefreshRequest(BaseModel):
    years: int = 17


@app.post("/jobs/refresh-indices")
def start_refresh_indices(req: IndexRefreshRequest | None = None) -> dict:
    """(Re)load NIFTY 50 / India VIX daily closes for the last N years (research backfill)."""
    req = req or IndexRefreshRequest()
    return _submit("indices", lambda p: {"written": ingest.refresh_indices(get_yfinance(), get_store(),
                                                                           years=req.years)})


_monitor_cache: dict[str, Any] = {"key": None, "value": None}
_monitor_lock = threading.Lock()


def _nifty500_nse(start: str, session: str) -> tuple[pd.Series, str] | None:
    """Nifty 500 daily closes from NSE itself: the daily index-file history (backfill + the 19:15 top-up) and, for the
    bhavcopy's session when the history doesn't have it yet, NSE's live index feed after the close. Yahoo's ^CRSLDX
    left out 13 Oct 2026 (the monitor showed 21,823 "0.00% today"; NSE closed it at 22,090, +1.22%)."""
    global _nse_live
    h = _index_valuation_history()
    if h is None:
        return None
    g = h[(h["index"] == "NIFTY 500") & (h["date"] >= start)]
    s = pd.Series(g["close"].to_numpy(dtype=float), index=pd.to_datetime(g["date"])).sort_index()
    if s.empty:
        return None
    if s.index[-1] < pd.Timestamp(session):
        try:
            import nse_live
            from bhavcopy import HEADERS
            from datetime import datetime as _dt
            if _nse_live is None:
                _nse_live = nse_live.NseLive(HEADERS)
            q = nse_live.parse_index_quote(_nse_live.get("allIndices", ttl_open=15, ttl_closed=300), "NIFTY 500")
            day = _dt.strptime(str(q.get("time") or "")[:11], "%d-%b-%Y").date()
            if q.get("last") is not None and day.isoformat() == session and str(q.get("time"))[12:17] >= "15:30":
                s.loc[pd.Timestamp(session)] = float(q["last"])
        except Exception:  # noqa: BLE001 — the history alone is still right up to its last day
            pass
    if s.index[-1] < pd.Timestamp(session):
        return None                                  # NSE can't give the latest session: the caller uses NIFTY 50 from the DB
    return s, "Nifty 500"


@app.get("/db/market-monitor")
def market_monitor_snapshot(store: DuckDBStore = Depends(get_store)) -> dict:
    """Breadth, regime score, sectors and movers from the NSE bhavcopy (cached until the next EOD file)."""
    import market_monitor
    from shared.momentum import industries
    from shared.nse_panel import load_panel
    meta = store.get_bhavcopy_meta()
    key = str(meta.get("last_date"))
    with _monitor_lock:
        if _monitor_cache["key"] == key and _monitor_cache["value"] is not None:
            return _monitor_cache["value"]
        start = (pd.Timestamp(key) - pd.Timedelta(days=620)).date().isoformat()
        with store.reader() as con:
            panel = load_panel(con, start=start)
        vix = store.get_index_daily("INDIAVIX")
        vix = pd.Series(vix["close"].to_numpy(), index=pd.to_datetime(vix["date"]))
        got = _nifty500_nse(start, key)                 # NSE's daily index file; no Yahoo on the request path (PLAN §0.7)
        if got is None:
            n50 = store.get_index_daily("NIFTY50")
            got = (pd.Series(n50["close"].to_numpy(), index=pd.to_datetime(n50["date"])), "NIFTY 50")
        value = market_monitor.snapshot(panel, got[0], got[1], vix, industries())
        _monitor_cache.update(key=key, value=value)
        return value


@app.get("/db/bhavcopy-meta")
def bhavcopy_meta(store: DuckDBStore = Depends(get_store)) -> dict:
    return store.get_bhavcopy_meta()


@app.get("/jobs")
def list_jobs() -> dict:
    return {"jobs": _jobs.list()}


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job


@app.post("/admin/reclassify-instruments")
def reclassify_instruments(store: DuckDBStore = Depends(get_store)) -> dict:
    return {"counts": _classify_instruments(store, get_settings())}


@app.get("/db/instruments")
def list_instruments(store: DuckDBStore = Depends(get_store)) -> dict:
    df = store.get_instruments()
    return {
        "counts": {k: int(v) for k, v in df["instrument_type"].value_counts().items()} if not df.empty else {},
        "data": df.drop(columns=["updated_at"], errors="ignore").to_dict(orient="records"),
    }


@app.get("/db/quarantine")
def quarantine_summary(limit: int = 50, store: DuckDBStore = Depends(get_store)) -> dict:
    """Bars rejected by the ingestion quality gate, grouped by reason (audit)."""
    return store.get_quarantine_summary(limit=max(1, min(limit, 500)))


@app.get("/db/freshness")
def data_freshness(store: DuckDBStore = Depends(get_store)) -> dict:
    """How current each layer is: bars → features → labels (eligible equities only)."""
    with store.reader() as con:
        row = con.execute("""
            WITH elig AS (SELECT ticker FROM instruments WHERE ml_eligible),
                 last_bar AS (SELECT o.ticker, MAX(o.date) d FROM ohlcv o JOIN elig USING (ticker) GROUP BY 1),
                 mx AS (SELECT MAX(d) m FROM last_bar)
            SELECT (SELECT m FROM mx),
                   (SELECT COUNT(*) FROM last_bar, mx WHERE d >= m - INTERVAL 5 DAY),
                   (SELECT COUNT(*) FROM last_bar, mx WHERE d <  m - INTERVAL 5 DAY),
                   (SELECT COUNT(*) FROM elig),
                   (SELECT MAX(date) FROM ml_features),
                   (SELECT MAX(date) FROM ml_labels),
                   (SELECT MAX(date) FROM market_index_daily WHERE symbol = 'NIFTY50'),
                   (SELECT COUNT(*) FROM ohlcv_quarantine)
        """).fetchone()
    latest_bar, current, stale, eligible, feat, lbl, nifty, quarantined = row or (None,) * 8

    def _s(d):
        return str(d)[:10] if d else None

    lag_days = (latest_bar - feat).days if latest_bar and feat else None
    return {
        "latest_bar_date": _s(latest_bar),
        "eligible_tickers": eligible,
        "eligible_current": current,
        "eligible_stale": stale,
        "ml_features_latest_date": _s(feat),
        "ml_labels_latest_date": _s(lbl),
        "nifty_index_latest_date": _s(nifty),
        "features_lag_days": lag_days,
        "bars_quarantined": quarantined,
        "features_fresh": lag_days is not None and lag_days <= 4,
    }


@app.post("/admin/import-ml-data")
def import_ml_data_from_parquet(store: DuckDBStore = Depends(get_store)) -> dict:
    """
    Read computed_features.parquet and computed_labels.parquet (written by the pipeline)
    and persist them into DuckDB ml_features + ml_labels tables.

    Called automatically by pipeline.py after feature generation completes.
    Cycles the DuckDB connection through write mode to perform the import.
    """
    import duckdb as _duckdb
    import pandas as pd
    from pathlib import Path as _Path

    db_path = store._db_path
    data_dir = _Path(db_path).parent
    feat_parquet = data_dir / "computed_features.parquet"
    lbl_parquet  = data_dir / "computed_labels.parquet"

    if not feat_parquet.exists() and not lbl_parquet.exists():
        raise HTTPException(status_code=404, detail="No Parquet files found — run feature generation first")

    result = {"features": 0, "labels": 0, "status": "ok"}

    if store._read_only:
        raise HTTPException(
            status_code=503,
            detail="DuckDB is in read-only mode — restart data-service when no other process holds the DB write lock"
        )

    try:
        if feat_parquet.exists():
            # Discover Parquet columns
            parquet_cols = {r[0] for r in store.read_rows(
                f"DESCRIBE SELECT * FROM read_parquet('{feat_parquet}') LIMIT 1"
            )}

            # All numeric feature columns from feature_engine (no macro/varchar edge cases)
            numeric_features = [
                "ret_1d", "ret_5d", "ret_20d", "log_ret",
                "sma_20", "sma_50", "sma_200", "ema_12", "ema_26",
                "price_vs_sma20", "price_vs_sma50", "price_vs_sma200",
                "sma_ratio_20_50", "uptrend_20_50", "uptrend_50_200",
                "rsi_14", "rsi_7", "rsi_28",
                "macd", "macd_signal", "macd_hist",
                "bollinger_pctb", "bb_width",
                "atr_14", "atr_14_pct", "realized_vol_20d",
                "volume_zscore", "volume_ratio", "obv",
                "mfi_14", "cmf_20",
                "stoch_k", "stoch_d", "williams_r",
                "roc_5", "roc_10", "roc_20",
                "gap_pct", "high_low_ratio", "close_position",
                "is_green_candle",
                "return_lag_1d", "return_lag_2d", "return_lag_3d", "return_lag_5d", "return_lag_10d",
                "day_of_week", "month",
                "trailing_pe", "price_to_book", "ev_to_ebitda",
                "peg_ratio", "revenue_growth",
                "gross_margins", "operating_margins", "profit_margins",
                "return_on_equity", "return_on_assets",
                "debt_to_equity", "current_ratio", "altman_z",
                "insider_hold_pct", "inst_hold_pct",
                "india_vix", "vix_zscore", "nifty_ret_5d", "market_breadth",
            ]

            # Only include columns that exist in BOTH Parquet AND ml_features table
            table_cols = {r[0] for r in store.read_rows("DESCRIBE ml_features")}
            insert_cols = ["ticker", "date"]
            select_exprs = ["ticker::VARCHAR", "date::DATE"]
            for col in numeric_features:
                if col in table_cols:
                    insert_cols.append(col)
                    select_exprs.append(f"{col}::DOUBLE" if col in parquet_cols else "NULL")
            # nifty_regime (VARCHAR)
            if "nifty_regime" in table_cols:
                insert_cols.append("nifty_regime")
                select_exprs.append("TRY_CAST(nifty_regime AS VARCHAR)" if "nifty_regime" in parquet_cols else "NULL")
            insert_cols.append("feature_version")
            select_exprs.append("COALESCE(TRY_CAST(feature_version AS VARCHAR), 'v1')" if "feature_version" in parquet_cols else "'v1'")

            col_list = ", ".join(insert_cols)
            val_list = ", ".join(select_exprs)

            with store.writer() as con:
                con.execute("BEGIN TRANSACTION")
                try:
                    con.execute("DELETE FROM ml_features")
                    con.execute(f"INSERT INTO ml_features ({col_list}) SELECT {val_list} FROM read_parquet('{feat_parquet}')")
                    con.execute("COMMIT")
                except Exception:
                    con.execute("ROLLBACK")  # never leave the feature store empty
                    raise
            result["features"] = store.read_one("SELECT COUNT(*) FROM ml_features")[0]

        if lbl_parquet.exists():
            lbl_parquet_cols = {r[0] for r in store.read_rows(
                f"DESCRIBE SELECT * FROM read_parquet('{lbl_parquet}') LIMIT 1"
            )}

            def _lc(col: str, fallback: str) -> str:
                return col if col in lbl_parquet_cols else fallback

            with store.writer() as con:
                con.execute("BEGIN TRANSACTION")
                try:
                    con.execute("DELETE FROM ml_labels")
                    con.execute(f"""
                        INSERT INTO ml_labels (ticker, date, horizon_days, label_direction,
                                               label_return_pct, label_barrier,
                                               profit_target_pct, stop_loss_pct)
                        SELECT
                            ticker::VARCHAR,
                            date::DATE,
                            {_lc("TRY_CAST(horizon_days AS INTEGER)", "5")},
                            TRY_CAST(label_direction AS INTEGER),
                            label_return_pct::DOUBLE,
                            {_lc("TRY_CAST(label_barrier AS INTEGER)", "NULL")},
                            {_lc("TRY_CAST(profit_target_pct AS DOUBLE)", "2.0")},
                            {_lc("TRY_CAST(stop_loss_pct AS DOUBLE)", "2.0")}
                        FROM read_parquet('{lbl_parquet}')
                    """)
                    con.execute("COMMIT")
                except Exception:
                    con.execute("ROLLBACK")
                    raise
            result["labels"] = store.read_one("SELECT COUNT(*) FROM ml_labels")[0]

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Import failed: {exc}")

    return result


class ICICIConfigureRequest(BaseModel):
    api_key: str | None = None
    api_secret: str | None = None
    session_token: str | None = None


def _prev_close_for(symbols: list[str]) -> dict[str, float]:
    """Last bhavcopy close per symbol (A5 fallback). Runs on the live-ticks worker thread, never the loop."""
    try:
        store = get_store()
        ph = ",".join("?" * len(symbols))
        rows = store.read_rows(
            f"""SELECT symbol, close FROM nse_bhavcopy
                WHERE date = (SELECT max(date) FROM nse_bhavcopy) AND series = 'EQ' AND symbol IN ({ph})""",
            symbols)
        return {r[0]: float(r[1]) for r in rows if r[1]}
    except Exception:  # noqa: BLE001 — fallback only; the tick's own close still works
        return {}


def _holdings_symbols() -> list[str]:
    """Symbols pinned into the live-tick subscription (A1): the saved broker book."""
    try:
        import json as _json
        raw = _json.loads((Path(__file__).resolve().parents[2] / "data" / "last_holdings.json").read_text())
        return [p.get("symbol", "") for p in raw.get("positions", [])]
    except Exception:  # noqa: BLE001
        return []


@app.get("/live/ticks")
def live_ticks_view(symbols: str = Query("", max_length=8000)) -> dict:
    """L1 tick snapshot; asking for symbols AUTO-ENSURES their subscription (amendment A1 — union + TTL,
    holdings pinned, cap live_ticks.MAX_SYMBOLS = 300). Pure dict read + event flip: safe as a sync route. LIVE_TICKS=0
    ⇒ state OFF and an empty tick map. New callers use /live/quotes (every source, labelled)."""
    lt = live_ticks_mod.instance()
    if lt is None:
        return {"state": "OFF", "connected": False, "error": "live ticks not initialised",
                "as_of": datetime.now().isoformat(timespec="seconds"), "ticks": {}}
    syms = [x for x in symbols.split(",") if x.strip()]
    st = lt.ensure(syms) if syms else lt.status()
    return {**st, "as_of": datetime.now().isoformat(timespec="seconds"),
            "ticks": lt.snapshot(syms or None)}


# ── /live/quotes + /live/status (live-NSE program LV-DATA; live_quotes.py) ────────────────────────────────────────────
# Breeze websocket tick → NSE website copy (fallback poller) → last EOD close, per symbol, never Yahoo. The request path
# reads memory and a cached DuckDB row; the NSE poller runs on its own thread through the shared NseLive client.

_live_quotes: Any = None
_live_quotes_lock = threading.Lock()
_live_watch_cache: dict = {"at": 0.0, "symbols": []}


def _live_nse_client() -> Any:
    """The process's one NseLive (shared cache + 403/429 breaker with every NSE route)."""
    global _nse_live
    import nse_live
    from bhavcopy import HEADERS
    if _nse_live is None:
        _nse_live = nse_live.NseLive(HEADERS)
    return _nse_live


def _live_eod_rows(symbols: list[str]) -> dict[str, dict]:
    """Last stored close per symbol: nse_bhavcopy (EQ before BE) for stocks; index_ohlc_daily (NSE's daily index file,
    Terminal v2) then market_index_daily for indices. Within the last 30 days; runs in the threadpool, never the loop."""
    from nse_positions import index_symbol
    store = get_store()
    since = (date.today() - timedelta(days=30)).isoformat()
    eq = [s for s in symbols if " " not in s]
    ix = [s for s in symbols if " " in s]
    out: dict[str, dict] = {}
    if eq:
        rows = store.read_rows("""
            SELECT symbol, date, close, prev_close, open, high, low, volume, turnover_lacs FROM (
                SELECT *, row_number() OVER (PARTITION BY symbol ORDER BY date DESC, CASE series WHEN 'EQ' THEN 0 ELSE 1 END) AS rn
                FROM nse_bhavcopy WHERE list_contains(?, symbol) AND series IN ('EQ', 'BE') AND date >= ?::DATE) WHERE rn = 1""",
                               [eq, since])
        for s, d, c, p, o, h, lo, v, tl in rows:
            out[s] = {"date": str(d)[:10], "close": c, "prev_close": p, "open": o, "high": h, "low": lo, "volume": v,
                      "value_cr": tl / 100 if tl else None, "table": "nse_bhavcopy"}
    if ix:
        try:
            rows = store.read_rows("""
                SELECT symbol, date, open, high, low, close, prev FROM (
                    SELECT symbol, date, open, high, low, close, lag(close) OVER (PARTITION BY symbol ORDER BY date) AS prev,
                           row_number() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn
                    FROM index_ohlc_daily WHERE list_contains(?, symbol) AND date >= ?::DATE) WHERE rn = 1""", [ix, since])
        except Exception:  # noqa: BLE001 — Terminal v2 table not deployed yet: market_index_daily below
            rows = []
        for s, d, o, h, lo, c, p in rows:
            out[s] = {"date": str(d)[:10], "close": c, "prev_close": p, "open": o, "high": h, "low": lo, "volume": None,
                      "value_cr": None, "table": "index_ohlc_daily"}
        rest = {index_symbol(s): s for s in ix if s not in out}
        if rest:
            rows = store.read_rows("""
                SELECT symbol, date, close, prev FROM (
                    SELECT symbol, date, close, lag(close) OVER (PARTITION BY symbol ORDER BY date) AS prev,
                           row_number() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn
                    FROM market_index_daily WHERE list_contains(?, symbol) AND date >= ?::DATE) WHERE rn = 1""",
                                   [list(rest), since])
            for code, d, c, p in rows:
                out[rest[code]] = {"date": str(d)[:10], "close": c, "prev_close": p, "open": None, "high": None,
                                   "low": None, "volume": None, "value_cr": None, "table": "market_index_daily"}
    return out


def _live_index_members(index_name: str) -> list[str]:
    """NIFTY 50 / NIFTY BANK members for the pinned set: the stored niftyindices list (Terminal v2 index_constituents_daily),
    else NSE's heatmap list already in the shared cache (no network here)."""
    try:
        rows = get_store().read_rows("""SELECT symbol FROM index_constituents_daily WHERE index_name = ? AND date = (
                                        SELECT max(date) FROM index_constituents_daily WHERE index_name = ?)""",
                                     [index_name, index_name])
        if rows:
            return [str(r[0]).upper() for r in rows]
    except Exception:  # noqa: BLE001 — table not deployed yet
        pass
    import nse_live
    nl = _nse_live
    kind = "Broad Market Indices" if index_name in ("NIFTY 50", "NIFTY NEXT 50") else "Sectoral Indices"
    hit = nl._cache.get(nse_live.heatmap_path(kind, index_name)) if nl is not None else None
    payload = hit[1] if hit else None
    return sorted(nse_live.parse_heatmap(payload if isinstance(payload, list) else []))


def _live_watchlist() -> list[str]:
    """The starred tickers (Redis set monitored.stocks, as the watchlist poller reads it); 60 s cache, 1 s timeouts."""
    now = time.time()
    if now - _live_watch_cache["at"] < 60:
        return list(_live_watch_cache["symbols"])
    syms: list[str] = []
    url = os.environ.get("REDIS_URL")
    if url:
        try:
            import redis as _redis
            members = _redis.from_url(url, socket_connect_timeout=1, socket_timeout=1).smembers("monitored.stocks")
            syms = [(m.decode() if isinstance(m, (bytes, bytearray)) else str(m)).upper() for m in (members or set())]
        except Exception:  # noqa: BLE001 — no watchlist pins rather than a blocked worker
            syms = []
    _live_watch_cache.update(at=now, symbols=syms)
    return syms


def _live_quotes_engine() -> Any:
    global _live_quotes
    with _live_quotes_lock:
        if _live_quotes is None:
            import live_quotes as lq
            _live_quotes = lq.LiveQuotes(
                ticks_getter=live_ticks_mod.instance, nse_getter=_live_nse_client, eod_fn=_live_eod_rows,
                session_fn=lambda: bool(_live is not None and _live.is_connected()),
                watchlist_fn=_live_watchlist, members_fn=_live_index_members)
        return _live_quotes


# The pinned set (indices + NIFTY 50 / NIFTY BANK members + watchlist while the market is open) for the tick engine;
# the holdings stay pinned through init(holdings_fn=_holdings_symbols) in the lifespan.
live_ticks_mod.set_pins_source(lambda: _live_quotes_engine().pinned_symbols())


@app.get("/live/quotes")
def live_quotes_view(symbols: str = Query("", max_length=12000)) -> dict:
    """Per NSE symbol (≤ 300, indices by NSE name: 'NIFTY 50', 'NIFTY BANK', 'INDIA VIX'): price, change, OHLC, volume,
    bid/ask, ltt, source breeze_ws | nse_api | eod, age_s, state live | delayed | stale | closed | unavailable (+ reason).
    Asking ensures the websocket subscription. Memory + a cached DuckDB read only: never NSE, Breeze REST or Yahoo."""
    return _live_quotes_engine().quotes([x for x in symbols.split(",") if x.strip()])


@app.get("/live/status")
def live_status_view() -> dict:
    """Tick engine + NSE fallback health: state, subscribed, ticks_per_min, last_tick_age_s, cap, breeze_session,
    nse_fallback {ok, last_ok_at, …}, unmapped ticks, subscriptions without a first tick."""
    return _live_quotes_engine().status()


@app.get("/provider/status")
def provider_status(live: LiveDataProvider = Depends(get_live_provider)) -> dict:
    out = {
        "provider": type(live).__name__,
        "connected": live.is_connected(),
        # "stub" = no broker credentials loaded; live quotes unavailable.
        "mode": "stub" if type(live).__name__ == "StubLiveProvider" else "live",
    }
    lt = live_ticks_mod.instance()
    if lt is not None:
        out["live_ticks"] = lt.status()
    return out


@app.post("/provider/configure")
def configure_provider(req: ICICIConfigureRequest) -> dict:
    global _live

    api_key = (req.api_key if req.api_key is not None else os.environ.get("ICICI_API_KEY", "")).strip()
    api_secret = (req.api_secret if req.api_secret is not None else os.environ.get("ICICI_API_SECRET", "")).strip()
    session_token = _extract_session_token(req.session_token if req.session_token is not None else os.environ.get("ICICI_SESSION_TOKEN", ""))

    os.environ["ICICI_API_KEY"] = api_key
    os.environ["ICICI_API_SECRET"] = api_secret
    os.environ["ICICI_SESSION_TOKEN"] = session_token

    if _live is not None:
        _live.disconnect()

    _live = build_live_provider(api_key, api_secret, session_token)
    try:
        _live.connect()
        return {
            "provider": type(_live).__name__,
            "connected": _live.is_connected(),
        }
    except Exception as exc:
        logger.error("Failed to reconfigure data-service ICICI provider", error=str(exc))
        return {
            "provider": type(_live).__name__,
            "connected": False,
            "error": str(exc),
        }


# ── Historical data (Yahoo only — see ingest.py for why) ─────────────────────

class FetchHistoricalRequest(BaseModel):
    tickers: list[str]
    years: int = 5


class FetchHistoricalResponse(BaseModel):
    fetched: dict[str, int]  # ticker → rows written
    errors: list[str]
    statuses: dict[str, str] = {}


@app.post("/fetch/historical", response_model=FetchHistoricalResponse)
def fetch_historical(
    req: FetchHistoricalRequest,
    yf: DirectYahooProvider = Depends(get_yfinance),
    store: DuckDBStore = Depends(get_store),
) -> FetchHistoricalResponse:
    """Full (re)download of each ticker's history from Yahoo, replacing stored bars."""
    results: dict[str, int] = {}
    statuses: dict[str, str] = {}
    errors: list[str] = []
    for ticker in req.tickers:
        r = ingest.refresh_ticker(yf, store, ticker, years=req.years, full=True)
        statuses[r.ticker] = r.status
        if r.status in (ingest.STATUS_NO_DATA, ingest.STATUS_ERROR):
            errors.append(f"{r.ticker}: {r.status} {r.detail}".strip())
        else:
            results[r.ticker] = r.rows
    return FetchHistoricalResponse(fetched=results, errors=errors, statuses=statuses)


# ── Incremental refresh ────────────────────────────────────────────────────────

class RefreshTickerRequest(BaseModel):
    ticker: str
    start_date: date | None = None  # ignored: the overlap window is managed by ingest


class RefreshBatchRequest(BaseModel):
    tickers: list[str]
    years: int = 5


class RefreshBatchResponse(BaseModel):
    refreshed: dict[str, int]
    errors: list[str]
    # Per-ticker outcome: updated | current | backfilled | readjusted | no_data | error.
    # "current" now strictly means "Yahoo confirmed nothing new", never "fetch returned nothing".
    statuses: dict[str, str] = {}


@app.post("/fetch/refresh")
def refresh_ticker(
    req: RefreshTickerRequest,
    yf: DirectYahooProvider = Depends(get_yfinance),
    store: DuckDBStore = Depends(get_store),
) -> dict:
    r = ingest.refresh_ticker(yf, store, req.ticker, years=get_settings().historical_years)
    return {"ticker": r.ticker, "rows_written": r.rows, "status": r.status,
            "quarantined": r.quarantined, "message": r.detail}


@app.post("/fetch/refresh-batch", response_model=RefreshBatchResponse)
def refresh_batch(
    req: RefreshBatchRequest,
    yf: DirectYahooProvider = Depends(get_yfinance),
    store: DuckDBStore = Depends(get_store),
) -> RefreshBatchResponse:
    """Incrementally update daily bars for each ticker (Yahoo only, quality-gated)."""
    results: dict[str, int] = {}
    statuses: dict[str, str] = {}
    errors: list[str] = []
    for ticker in req.tickers:
        r = ingest.refresh_ticker(yf, store, ticker, years=req.years)
        statuses[r.ticker] = r.status
        if r.status in (ingest.STATUS_NO_DATA, ingest.STATUS_ERROR):
            errors.append(f"{r.ticker}: {r.status} {r.detail}".strip())
        else:
            results[r.ticker] = r.rows
    return RefreshBatchResponse(refreshed=results, errors=errors, statuses=statuses)


# ── OHLCV read ─────────────────────────────────────────────────────────────────

@app.get("/ohlcv/{ticker}")
def get_ohlcv(
    ticker: str,
    start: date | None = None,
    end: date | None = None,
    store: DuckDBStore = Depends(get_store),
) -> dict:
    df = store.get_ohlcv(ticker, start=start, end=end)
    if df.empty:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No OHLCV data for {ticker}")
    # Normalise date column to plain yyyy-mm-dd strings (lightweight-charts requirement)
    if "date" in df.columns:
        df = df.copy()
        df["date"] = df["date"].astype(str).str[:10]
    return {"ticker": ticker, "rows": len(df), "data": df.to_dict(orient="records")}


# ── Live quote ─────────────────────────────────────────────────────────────────

@app.get("/live/quote/{ticker}")
def get_live_quote(
    ticker: str,
    live: LiveDataProvider = Depends(get_live_provider),
) -> dict:
    # Without a broker session there is no live quote: say so plainly (the UI falls back to
    # its Yahoo quotes) instead of retrying a call that cannot succeed and returning a 500.
    if not live.is_connected():
        return {"ticker": ticker, "quote": None, "connected": False,
                "reason": "ICICI Breeze is not connected (session token missing or expired)"}
    if _breeze_blocked():
        return {"ticker": ticker, "quote": None, "connected": True,
                "reason": "ICICI's daily API call limit was reached: live quotes resume after midnight IST"}
    try:
        quote = live.get_live_quote(ticker)
    except Exception as exc:
        _note_breeze_error(exc)
        return {"ticker": ticker, "quote": None, "connected": True, "reason": f"ICICI quote unavailable: {str(exc)[:120]}"}
    return {"ticker": ticker, "quote": quote, "connected": True}


@app.get("/live/index/nifty")
def get_live_nifty(store: DuckDBStore = Depends(get_store)) -> dict:
    """Return the latest stored NIFTY quote (if available)."""
    rows = store.get_latest_live_quotes(limit=10)
    # prefer symbols commonly used for NIFTY
    for r in rows:
        sym = r.get("symbol", "").upper()
        if sym in ("NIFTY", "NSEI", "NIFTY50", "NIFTY.NS", "^NSEI"):
            return {"symbol": sym, "record": r}
    return {"symbol": None, "recent": rows}


# ── ICICI Breeze daily ingestion (retired) ─────────────────────────────────────

@app.post("/fetch/icici/daily")
def fetch_icici_daily() -> dict:
    """Retired: stored daily history is Yahoo-only.

    ICICI bars are unadjusted for splits/bonuses; writing them into the same series
    as Yahoo's adjusted history created artificial 2x-100x jumps. ICICI Breeze is
    still used for live quotes (/live/*).
    """
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="ICICI daily ingestion is retired — daily history is Yahoo-only. "
               "Use POST /jobs/refresh-universe.",
    )


# ── Fundamentals / Stock Metrics ──────────────────────────────────────────────

class FetchFundamentalsRequest(BaseModel):
    tickers: list[str]


class FetchFundamentalsResponse(BaseModel):
    fetched: int
    skipped: int
    errors: list[str]


@app.post("/fetch/fundamentals", response_model=FetchFundamentalsResponse)
def fetch_fundamentals(
    req: FetchFundamentalsRequest,
    store: DuckDBStore = Depends(get_store),
) -> FetchFundamentalsResponse:
    """
    Fetch PE, market cap, revenue, margins, ROCE etc. from Yahoo Finance
    and write to stock_metrics + fundamentals tables.
    ~0.6s per ticker; call with batches of 50-100 at a time.
    """
    import time as _time
    import random as _random
    from providers.fundamentals_provider import fetch_fundamentals as _fetch_fund, _get_session

    session = _get_session()
    metrics_rows: list[dict] = []
    fund_rows:    list[dict] = []
    errors:       list[str]  = []
    skipped = 0

    fund_cols = [
        "ticker","as_of_date","market_cap","trailing_pe","forward_pe","price_to_book",
        "enterprise_value","ev_to_revenue","ev_to_ebitda","total_revenue","revenue_growth",
        "gross_margins","operating_margins","profit_margins","return_on_equity",
        "return_on_assets","debt_to_equity","current_ratio","book_value","dividend_yield",
        "payout_ratio","avg_volume","shares_outstanding","insider_hold_pct","inst_hold_pct",
        "analyst_target_mean","analyst_target_high","analyst_target_low",
        "analyst_recommendation","analyst_count",
    ]

    for i, ticker in enumerate(req.tickers):
        try:
            data = _fetch_fund(ticker, session)
            if data is None:
                skipped += 1
                continue

            metrics_rows.append({
                "ticker":        ticker,
                "as_of_date":    data["as_of_date"],
                "cmp":           data.get("cmp"),
                "pe_ratio":      data.get("pe_ratio"),
                "mktcap_cr":     data.get("mktcap_cr"),
                "div_yld_pct":   data.get("div_yld_pct"),
                "np_qtr_cr":     data.get("np_qtr_cr"),
                "qtr_pft_var":   data.get("qtr_pft_var"),
                "sales_qtr_cr":  data.get("sales_qtr_cr"),
                "qtr_sal_var":   data.get("qtr_sal_var"),
                "roce_pct":      data.get("roce_pct"),
            })

            fund_row = {c: data.get(c) for c in fund_cols}
            fund_row["sector"]   = None
            fund_row["industry"] = None
            fund_row["country"]  = "India"
            fund_rows.append(fund_row)

        except Exception as exc:
            errors.append(f"{ticker}: {exc}")

        if i < len(req.tickers) - 1:
            _time.sleep(0.5 + _random.uniform(0, 0.3))

    if metrics_rows:
        store.upsert_stock_metrics(metrics_rows)
    if fund_rows:
        import pandas as pd
        df_fund = pd.DataFrame(fund_rows)
        store.upsert_fundamentals(df_fund)

    logger.info(
        "Fundamentals fetch complete",
        fetched=len(metrics_rows), skipped=skipped, errors=len(errors)
    )
    return FetchFundamentalsResponse(
        fetched=len(metrics_rows), skipped=skipped, errors=errors
    )


# ── ICICI intraday (today's bars) ──────────────────────────────────────────────

# ── Dashboard stats proxy (for ui-api — avoids concurrent DuckDB lock) ────────

@app.get("/db/stats")
def get_db_stats(store: DuckDBStore = Depends(get_store)) -> dict:
    """
    Aggregate dashboard stats (total_stocks, freshness, enrichment, data_range).
    ui-api calls this instead of opening a second DuckDB connection, which
    fails on Docker Desktop Mac (virtioFS concurrent-lock bug).
    """
    return store.get_dashboard_stats()


@app.get("/db/ohlcv-meta")
def get_ohlcv_meta(fields: str = "full", store: DuckDBStore = Depends(get_store)) -> dict:
    """
    Per-ticker OHLCV + metrics stats for the stocks list page.
    Returns a list keyed by ticker with total_rows, dates, price, metrics.
    `fields=core` trims each row to the 6 data-quality keys (payload budget S2;
    measured 655 KB -> 215 KB, -67%): ticker, latest_date, total_rows,
    days_since_update, data_density_pct, sessions_behind.
    Default stays `full` so existing consumers are unchanged (WarehouseHealth's
    grid via data_proxy - which forwards no query params - and stocks list need
    the full row).
    """
    rows = store.get_ohlcv_meta_all()
    if fields == "core":
        keep = ("ticker", "latest_date", "total_rows", "days_since_update",
                "data_density_pct", "sessions_behind")
        rows = [{k: r.get(k) for k in keep} for r in rows]
    return {"count": len(rows), "data": rows}


@app.get("/db/screener")
def run_screener(
    t1: bool = False, t2: bool = False, t3: bool = False, t4: bool = False,
    t5: bool = False, t6: bool = False, t7: bool = False, t8: bool = False,
    skip: int = 0, limit: int = 50,
    store: DuckDBStore = Depends(get_store),
) -> dict:
    """Minervini T1-T8 screener via data-service DuckDB (avoids ui-api concurrent lock)."""
    filters = {"t1": t1, "t2": t2, "t3": t3, "t4": t4,
               "t5": t5, "t6": t6, "t7": t7, "t8": t8}
    return store.run_screener(filters, skip=skip, limit=limit)


# ── ICICI intraday (today's bars) ──────────────────────────────────────────────

@app.get("/db/ohlcv-bulk")
def get_ohlcv_bulk(
    days: int = 700,
    equity_only: bool = False,
    store: DuckDBStore = Depends(get_store),
) -> dict:
    """Return all OHLCV rows for the last N days (excludes macro tickers like ^NSEI).
    Used by pipeline.py feature generation to avoid direct DuckDB access from ui-api.
    """
    with store.reader() as con:
        df = con.execute(f"""
            SELECT ticker, date::VARCHAR AS date, open, high, low, close, volume, adjusted_close
            FROM ohlcv
            WHERE date >= (CURRENT_DATE - INTERVAL '{days}' DAY)
              AND ticker NOT LIKE '^%'
              {"AND ticker IN (SELECT ticker FROM instruments WHERE ml_eligible)" if equity_only else ""}
            ORDER BY ticker, date
        """).df()
    df["date"] = df["date"].str[:10]
    return {"rows": len(df), "data": df.to_dict(orient="records")}


@app.get("/db/latest-features")
def get_latest_features(store: DuckDBStore = Depends(get_store)) -> dict:
    """Latest ml_features row per ticker — consumed by ml-service /batch-predict.

    ml-service must NOT open its own DuckDB connection: on Docker Desktop (Mac,
    virtioFS) a second connection fails with "Conflicting lock is held in PID 0"
    even read-only. data-service owns the lock, so it serves the feature matrix
    over HTTP instead.
    """
    with store.reader() as con:
        df = con.execute("""
            SELECT f.*
            FROM ml_features f
            INNER JOIN (
                SELECT ticker, MAX(date) AS max_date
                FROM ml_features
                GROUP BY ticker
            ) latest ON f.ticker = latest.ticker AND f.date = latest.max_date
        """).df()
    if "date" in df.columns:
        df["date"] = df["date"].astype(str).str[:10]
    return {"rows": len(df), "data": df.to_dict(orient="records")}


@app.get("/db/training-sample")
def get_training_sample(
    stride: int | None = None,
    per_ticker: int = 200,
    store: DuckDBStore = Depends(get_store),
) -> dict:
    """SINGLE SOURCE for training: ml_features INNER JOIN ml_labels, ORDERED BY DATE.

    stride (recommended, e.g. 5 = the label horizon): every Nth row per ticker across
      the FULL history. Consecutive 5-day labels overlap by 4 days, so a stride equal
      to the horizon gives non-overlapping labels, multi-regime coverage and a payload
      the same size as the old "last 200 rows" window.
    per_ticker (legacy, used when stride is omitted): last N rows per ticker.
    Rows are always returned in date order so callers can split by time.
    """
    if stride is not None:
        stride = max(1, min(int(stride), 20))
        keep = f"(_rn - 1) % {stride} = 0"
    else:
        keep = f"_rn_desc <= {max(10, min(int(per_ticker), 2000))}"
    with store.reader() as con:
        df = con.execute(f"""
            SELECT * FROM (
                SELECT f.*, l.label_direction, l.label_return_pct, l.label_barrier,
                       ROW_NUMBER() OVER (PARTITION BY f.ticker ORDER BY f.date)      AS _rn,
                       ROW_NUMBER() OVER (PARTITION BY f.ticker ORDER BY f.date DESC) AS _rn_desc
                FROM ml_features f
                INNER JOIN ml_labels l ON f.ticker = l.ticker AND f.date = l.date
                WHERE l.label_direction IS NOT NULL AND l.label_return_pct IS NOT NULL
            ) WHERE {keep}
            ORDER BY date, ticker
        """).df()
    df = df.drop(columns=["_rn", "_rn_desc"], errors="ignore")
    if "date" in df.columns:
        df["date"] = df["date"].astype(str).str[:10]
    return {
        "rows": len(df),
        "tickers": int(df["ticker"].nunique()) if "ticker" in df.columns else 0,
        "data": df.to_dict(orient="records"),
    }


@app.get("/db/feature-sample")
def get_feature_sample(n: int = 80000, store: DuckDBStore = Depends(get_store)) -> dict:
    """SINGLE SOURCE for the Feature Inspector (stats/correlations/distributions):
    a random sample of ml_features joined with labels. DuckDB samples server-side so
    only the sample is materialized — same canonical source as everything else."""
    n = max(1000, min(int(n), 300000))
    with store.reader() as con:
        df = con.execute(f"""
            SELECT * FROM (
                SELECT f.*, l.label_direction, l.label_return_pct
                FROM ml_features f
                INNER JOIN ml_labels l ON f.ticker = l.ticker AND f.date = l.date
            ) USING SAMPLE {n} ROWS
        """).df()
    if "date" in df.columns:
        df["date"] = df["date"].astype(str).str[:10]
    return {"rows": len(df), "data": df.to_dict(orient="records")}


@app.get("/db/fundamentals-bulk")
def get_fundamentals_bulk(store: DuckDBStore = Depends(get_store)) -> dict:
    """Return latest fundamentals snapshot per ticker (for feature generation).
    Used by pipeline.py to avoid direct DuckDB access from ui-api.
    """
    df = store.get_fundamentals()
    if not df.empty and "as_of_date" in df.columns:
        df["as_of_date"] = df["as_of_date"].astype(str).str[:10]
    return {"rows": len(df), "data": df.to_dict(orient="records")}


@app.get("/db/ml-stats")
def get_ml_stats(store: DuckDBStore = Depends(get_store)) -> dict:
    """Return ml_features + ml_labels row counts, freshness and class-balance stats."""
    with store.reader() as con:
        feat = con.execute(
            "SELECT COUNT(*) AS cnt, COUNT(DISTINCT ticker) AS tickers, "
            "MAX(date)::VARCHAR AS latest FROM ml_features"
        ).fetchone()
        lbl = con.execute(
            "SELECT COUNT(*) AS cnt, COUNT(DISTINCT ticker) AS tickers, "
            "MAX(date)::VARCHAR AS latest, "
            "SUM(CASE WHEN label_direction=1 THEN 1 ELSE 0 END) AS up_cnt, "
            "SUM(CASE WHEN label_direction=0 THEN 1 ELSE 0 END) AS dn_cnt, "
            "AVG(label_return_pct) AS avg_ret, STDDEV(label_return_pct) AS std_ret "
            "FROM ml_labels"
        ).fetchone()
    total_lbl = lbl[0] or 0
    up_lbl    = int(lbl[3] or 0)
    dn_lbl    = int(lbl[4] or 0)
    return {
        "features": {"rows": feat[0], "tickers": feat[1], "latest_date": feat[2]},
        "labels": {
            "rows": total_lbl, "tickers": lbl[1], "latest_date": lbl[2],
            "up_labels": up_lbl, "down_labels": dn_lbl,
            "class_balance_pct": round(up_lbl / total_lbl * 100, 1) if total_lbl else 0,
            "avg_return_pct": round(float(lbl[5] or 0), 4),
            "std_return_pct": round(float(lbl[6] or 0), 4),
        },
    }


@app.get("/live/intraday/{ticker}")
async def get_intraday(
    ticker: str,
    interval: str = "5minute",
    day: str | None = Query(default=None, description="Target date YYYY-MM-DD (defaults to today)"),
    live: LiveDataProvider = Depends(get_live_provider),
    store: DuckDBStore = Depends(get_store),
) -> dict:
    """Fetch intraday bars for `day` (defaults to today) via ICICI Breeze v2.

    Falls back to the last 30 daily OHLCV bars from DuckDB when the live
    provider is not connected (expired session, stub mode, etc.).
    """
    target_day = None
    if day:
        try:
            target_day = date.fromisoformat(day)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid day '{day}', expected YYYY-MM-DD")

    records_out: list[dict] = []
    source = "icici"
    previous_close: float | None = None

    if live.is_connected():
        try:
            batch = await asyncio.to_thread(live.get_intraday_ohlcv, ticker, interval, target_day)
            if batch.records:
                records_out = [r.model_dump() for r in batch.records]
        except Exception as e:
            logger.warning("Intraday fetch failed, falling back to DuckDB", ticker=ticker, error=str(e))

    if records_out:
        for r in records_out:      # epoch seconds, IST clock as UTC: the chart needs real times, not just the date
            ts = pd.Timestamp(r.get("date") or r.get("datetime") or r.get("timestamp"))
            r["ts"] = int((ts.tz_convert("Asia/Kolkata").tz_localize(None) if ts.tzinfo else ts).timestamp())

    if records_out and previous_close is None:      # ICICI bars: anchor on the last daily close before that day
        try:
            from datetime import timedelta
            d0 = target_day or date.today()
            prev = await asyncio.to_thread(store.get_ohlcv, ticker.upper(), d0 - timedelta(days=10), d0 - timedelta(days=1))
            if not prev.empty:
                previous_close = float(prev["close"].iloc[-1])
        except Exception as e:
            logger.warning("Previous close lookup failed", ticker=ticker, error=str(e))

    if not records_out and (target_day is None or target_day == date.today()):
        global _nse_live
        import nse_live
        from bhavcopy import HEADERS
        if _nse_live is None:
            _nse_live = nse_live.NseLive(HEADERS)
        try:
            minutes = int("".join(ch for ch in interval if ch.isdigit()) or 5)
            nse = await asyncio.to_thread(_nse_live.symbol_chart, ticker, minutes)
            if nse["rows"]:
                records_out, source, previous_close = nse["rows"], "nse", nse.get("previous_close")
                target_day = date.fromisoformat(nse["day"])
        except Exception as e:
            logger.warning("NSE intraday fallback failed", ticker=ticker, error=str(e))

    if not records_out:
        source = "duckdb_daily"
        try:
            from datetime import timedelta
            end_dt = target_day or date.today()
            start_dt = end_dt - timedelta(days=60)
            df = await asyncio.to_thread(store.get_ohlcv, ticker.upper(), start_dt, end_dt)
            if not df.empty:
                df = df.tail(30).copy()
                df["date"] = df["date"].astype(str).str[:10]
                df["time"] = df["date"]
                records_out = df.to_dict(orient="records")
        except Exception as e:
            logger.warning("DuckDB OHLCV fallback failed", ticker=ticker, error=str(e))

    return {
        "ticker": ticker,
        "interval": interval,
        "day": str(target_day or date.today()),
        "source": source,
        "previous_close": previous_close,
        "rows": len(records_out),
        "data": records_out,
    }


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# GOLD program (reports/gold_program/PLAN.md §c, builder B1): POST /jobs/ingest-gold, POST /jobs/gold-log and the
# GET /db/gold/* reads. Additive: every route above is untouched; the gold tables are created by DuckDBStore's
# schema init (gold/schema.py, IF NOT EXISTS). Nothing gold feeds the Decision Desk, the S1 shadow or the ticket.
# ══════════════════════════════════════════════════════════════════════════════════════════════════
import gold.api as _gold_api  # noqa: E402

# get_breeze (wave 1d): the read-only mcx_close_vwap30 group averages Breeze 1-minute bars through this session; the
# lambda resolves _breeze_connect (defined below with the Terminal v2 block) at call time.
_gold_api.configure(get_store=get_store, submit=_submit, get_breeze=lambda: _breeze_connect())
app.include_router(_gold_api.router)


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# Terminal v2 (reports/terminal_v2/PLAN.md 1.1 / 1.2 / 1.4, Wave 0 0.5 / 0.9; builder B1-DATA): the IV store
# (POST /jobs/iv-eod ?job=iv_eod|iv_weekly|iv_backfill|vix_backfill, POST /jobs/iv-intraday, POST /jobs/ingest-nse-files,
# GET /db/fo-iv/*, /db/vix-daily, /db/index-ohlc/*), the index drivers (POST /jobs/index-drivers ?job=index_drivers_daily|
# index_drivers_backfill, GET /db/index-drivers*) and data health (POST /jobs/data-health ?job=data_health_refresh,
# GET /db/data-health*). Additive: every route above is untouched; the tables are created by DuckDBStore's schema init
# (IF NOT EXISTS). Fetch + compute only; every publisher request goes through shared.http_client.PacedClient (allowlist,
# pacing, If-Modified-Since). Nothing here feeds the Decision Desk, the S1 shadow, a directional alert or the ticket.
# ══════════════════════════════════════════════════════════════════════════════════════════════════
import data_health.api as _data_health_api  # noqa: E402
import fo_iv.api as _fo_iv_api  # noqa: E402
import index_drivers.api as _index_drivers_api  # noqa: E402


def _terminal_http():
    from shared.http_client import PacedClient
    return PacedClient(timeout_s=float(os.getenv("NSE_HTTP_TIMEOUT_S", "20")))   # PLAN §0.6: 20 s (httpx read timeout, not a total)


def _archive_root() -> Path:
    return _data_dir(get_settings()) / "nse_archive"


def _market_holidays_set() -> set:
    """Exchange holidays for the data-health deadlines (weekdays only; empty when NSE's holiday master is unavailable)."""
    try:
        return {date.fromisoformat(h["date"]) for h in market_holidays().get("holidays", [])}
    except Exception:  # noqa: BLE001 — weekdays-only is the fallback
        return set()


def _breeze_connect():
    """The raw BreezeConnect of the live provider (read-only chain quotes), or None when no session is connected."""
    if _live is None:
        return None
    try:
        return getattr(_live, "_breeze", None) if _live.is_connected() else None
    except Exception:  # noqa: BLE001
        return None


def _fo_watchlist() -> list[str]:
    """The owner's F&O watchlist for the intraday pilot: IV_WATCHLIST env (comma-separated), else none (indices only)."""
    return [s.strip().upper() for s in os.getenv("IV_WATCHLIST", "").split(",") if s.strip()]


def _surface_symbols():
    """iv_surface_daily scope (O-T4 default: indices + the watchlist); IV_SURFACE_ALL=1 stores all 224 underlyings."""
    from fo_iv.iv_eod import INDEX_SYMBOLS          # IV_SURFACE_ALL=1 is handled by the configure() lambda (None = all 224)
    return set(INDEX_SYMBOLS) | set(_fo_watchlist())


_data_health_api.configure(get_store=get_store, submit=_submit, archive_root=_archive_root, holidays=_market_holidays_set)
_fo_iv_api.configure(get_store=get_store, submit=_submit, fo_root=_data_dir(get_settings()) / "nse_archive" / "fo",
                     cache_root=_data_dir(get_settings()), parquet_root=tick_store_mod.default_base_dir() / "chain",
                     http_factory=_terminal_http, get_breeze=_breeze_connect,
                     is_live=lambda: bool(_live is not None and _live.is_connected()), watchlist=_fo_watchlist,
                     surface_symbols=lambda: (None if os.getenv("IV_SURFACE_ALL", "0") == "1" else _surface_symbols()))
_index_drivers_api.configure(get_store=get_store, submit=_submit, cache_root=_data_dir(get_settings()),
                             financials_root=_data_dir(get_settings()) / "nse_archive" / "financials", http_factory=_terminal_http)
app.include_router(_data_health_api.router)
app.include_router(_fo_iv_api.router)
app.include_router(_index_drivers_api.router)

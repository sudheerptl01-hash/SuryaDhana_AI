"""
news_scanner.py — News Catalyst Terminal backend.

Reads the daily soft-catalyst scans that an external Claude session writes to
`new_scnner/YYYYMMDD.json`, normalises every ticker to Yahoo + TradingView symbols,
and enriches each pick with live market data from Yahoo Finance:

  GET /scans                 available scan files (newest first) + change marker
  GET /scan?date=latest      one scan, normalised (picks, rejected, macro, run log)
  GET /quotes?symbols=A,B    batch live quotes + 1-month sparkline
  GET /chart/{symbol}        OHLCV + indicators (SMA 20/50/200, RSI 14, ATR%) + stats
  GET /headlines/{symbol}    latest Yahoo Finance headlines for the ticker

Everything is async (httpx) with a small TTL cache, so polling from several open
terminals never blocks ui-api's event loop or hammers Yahoo.
"""
from __future__ import annotations

import asyncio
import functools
import json
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from cache import SWRCache, TTLCache, cache_headers, merge_served
from fastapi import APIRouter, HTTPException, Query, Response

router = APIRouter()

# ── Scan directory ──────────────────────────────────────────────────────────────

def _scan_dir() -> Path:
    env = os.environ.get("NEWS_SCANNER_DIR", "").strip()
    candidates = [Path(env)] if env else []
    candidates += [
        Path(__file__).resolve().parents[3] / "new_scnner",   # local: <repo>/new_scnner
        Path("/app/new_scnner"),                              # Docker bind mount
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[0]


# Accepted scan files: YYYYMMDD.json or YYYYMMDD.csv (JSON wins when both exist).
_SCAN_FILE = re.compile(r"^(\d{8})\.(json|csv)$", re.I)

# Tickers with neither an exchange field nor a suffix. The scanner prompt is
# India-only (NSE/BSE), so a bare "INFY" means NSE:INFY. Override if that changes.
DEFAULT_EXCHANGE = os.environ.get("NEWS_SCANNER_DEFAULT_EXCHANGE", "NSE").strip().upper()


def _scan_files(d: Path) -> list[tuple[str, Path]]:
    """[(yyyymmdd, path)] newest first, one file per date (JSON preferred over CSV)."""
    by_date: dict[str, Path] = {}
    for f in (d.iterdir() if d.is_dir() else []):
        m = _SCAN_FILE.match(f.name)
        if not m:
            continue
        if m.group(1) not in by_date or f.suffix.lower() == ".json":
            by_date[m.group(1)] = f
    return sorted(by_date.items(), reverse=True)


# ── Symbol normalisation ────────────────────────────────────────────────────────
# exchange label (as written by the scanner) → (Yahoo suffix, TradingView prefix, region)
_EXCHANGES: dict[str, tuple[str, str, str]] = {
    "NSE": (".NS", "NSE", "IN"),
    "BSE": (".BO", "BSE", "IN"),
    "LSE": (".L", "LSE", "UK"),
    "LSE AIM": (".L", "LSE", "UK"),
    "AIM": (".L", "LSE", "UK"),
    "NASDAQ": ("", "NASDAQ", "US"),
    "NYSE": ("", "NYSE", "US"),
    "NYSE AMERICAN": ("", "AMEX", "US"),
    "AMEX": ("", "AMEX", "US"),
}
_SUFFIX_EXCHANGE = {".NS": "NSE", ".BO": "BSE", ".L": "LSE"}
_SYMBOL_OK = re.compile(r"^[A-Z0-9.\-&^=]{1,24}$")


def _exchange_label(text: str) -> str:
    """'NSE / BSE', 'NSE, BSE', 'BSE & NSE' → 'NSE' (NSE preferred: better Yahoo coverage)."""
    t = (text or "").strip().upper()
    if "NSE" in t:
        return "NSE"
    if "BSE" in t:
        return "BSE"
    return t


def normalise_symbol(raw: str, exchange: str | None = None) -> dict[str, str] | None:
    """'LCC (NSE)' / 'UPL.NS' / 'TUN.L' / 'INFY' / '543210' → {yahoo, tv, base, exchange, region}."""
    text = (raw or "").strip().upper()
    if not text:
        return None
    hint = re.search(r"\(([^)]+)\)", text)
    ex = _exchange_label(hint.group(1) if hint else (exchange or ""))
    base = re.sub(r"\([^)]*\)", "", text).strip()
    base = re.sub(r"^(NSE|BSE)\s*:\s*", "", base)          # 'NSE:INFY' style
    for suffix, ex_name in _SUFFIX_EXCHANGE.items():
        if base.endswith(suffix):
            base, ex = base[: -len(suffix)], ex or ex_name
            break
    base = base.replace(" ", "")
    if not _SYMBOL_OK.match(base):
        return None
    if not ex:
        ex = "BSE" if base.isdigit() else DEFAULT_EXCHANGE    # numeric = BSE scrip code
    y_suffix, tv_prefix, region = _EXCHANGES.get(ex, ("", "", "OTHER"))
    return {
        "yahoo": f"{base}{y_suffix}",
        "tv": f"{tv_prefix}:{base}" if tv_prefix else base,
        "base": base,
        "exchange": ex,
        "region": region,
    }


# ── News / source parsing ───────────────────────────────────────────────────────
_NEWS_DATE = re.compile(
    r"^\s*((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:\s*[-–]\s*\d{1,2})?,?\s*\d{4}"
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}"
    r"|\d{4}-\d{2}-\d{2})\s*:\s*",
    re.I,
)


def split_news(value: Any) -> list[dict[str, str | None]]:
    """News in any shape the LLM emits → [{date, text}]:
    'Sep 22, 2026: … | Sep 24, 2026: …', a list of strings, or a list of
    {date, headline|text|title} objects."""
    if isinstance(value, list):
        out = []
        for v in value:
            if isinstance(v, dict):
                text = v.get("text") or v.get("headline") or v.get("title") or v.get("summary") or ""
                if text:
                    out.append({"date": v.get("date") or v.get("published") or None, "text": str(text).strip()})
            elif str(v).strip():
                out.extend(split_news(str(v)))
        return out
    items = []
    for part in re.split(r"\s+\|\s+|\n{2,}", str(value or "")):
        part = part.strip()
        if not part:
            continue
        m = _NEWS_DATE.match(part)
        items.append({"date": m.group(1).strip() if m else None,
                      "text": part[m.end():].strip() if m else part})
    return items


def split_thesis(text: Any) -> list[str]:
    """'1) a. 2) b.' / '1. a 2. b' / ['a', 'b'] → ['a', 'b'] — falls back to the whole text."""
    if isinstance(text, list):
        return [str(t).strip() for t in text if str(t).strip()]
    text = str(text or "")
    parts = [p.strip() for p in re.split(r"(?:^|\s)(?:\d{1,2}[.)]|Step\s*\d+[:.)])\s+", text) if p.strip()]
    return parts or ([text] if text else [])


def _source(url: str) -> dict[str, str]:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return {"url": url, "domain": host or url}


def _sources(value: Any) -> list[dict[str, str]]:
    """List of URLs, or one string with URLs separated by ; | , or newlines."""
    raw = value if isinstance(value, list) else re.split(r"[\s;|,]+", str(value or ""))
    return [_source(u.strip()) for u in raw if isinstance(u, str) and u.strip().startswith("http")]


def _conviction(value: Any) -> int:
    try:
        return max(0, min(10, int(round(float(str(value).split("/")[0])))))
    except (TypeError, ValueError):
        return 0


# Field aliases: the scanner is an LLM, so key names drift between runs/formats.
_ALIASES: dict[str, tuple[str, ...]] = {
    "ticker": ("ticker", "symbol", "yahoo_ticker", "yahoo_symbol", "nse_symbol", "bse_symbol", "stock", "ticker_symbol"),
    "company_name": ("company_name", "company", "name", "company_full_name", "full_name"),
    "exchange": ("exchange", "listing", "market", "listed_on"),
    "news": ("news", "news_summary", "news_text", "headline", "headlines", "summary", "catalyst_news",
             "news_snippet", "description", "catalyst", "event"),
    "sources": ("sources", "source", "source_urls", "urls", "links", "url", "source_url"),
    "catalyst_category": ("catalyst_category", "category", "catalyst_type"),
    "market_consensus_gap": ("market_consensus_gap", "consensus_gap", "market_gap"),
    "reflexivity_thesis": ("reflexivity_thesis", "thesis", "reflexive_thesis", "investment_thesis"),
    "conviction_score": ("conviction_score", "conviction", "score"),
}


def _field(p: dict[str, Any], name: str) -> Any:
    norm = {re.sub(r"[\s\-]+", "_", str(k).strip().lower()): v for k, v in p.items()}
    for alias in _ALIASES[name]:
        v = norm.get(alias)
        if v not in (None, "", []):
            return v
    return None


def _normalise_pick(p: dict[str, Any]) -> dict[str, Any]:
    ticker = str(_field(p, "ticker") or "")
    exchange = _field(p, "exchange")
    news = _field(p, "news")
    thesis = _field(p, "reflexivity_thesis")
    return {
        "raw_ticker": ticker,
        "symbol": normalise_symbol(ticker, str(exchange) if exchange else None),
        "company_name": _field(p, "company_name") or ticker,
        "exchange": exchange,
        "news": split_news(news),
        "news_text": news if isinstance(news, str) else "",
        "sources": _sources(_field(p, "sources")),
        "catalyst_category": _field(p, "catalyst_category"),
        "market_consensus_gap": _field(p, "market_consensus_gap"),
        "reflexivity_thesis": thesis if isinstance(thesis, str) else " ".join(map(str, thesis or [])),
        "thesis_steps": split_thesis(thesis),
        "conviction_score": _conviction(_field(p, "conviction_score")),
    }


def _normalise_rejected(r: dict[str, Any]) -> dict[str, Any]:
    raw = str(_field(r, "ticker") or "")
    symbols = [s for s in (normalise_symbol(t) for t in re.split(r"\s*/\s*", raw)) if s] if raw else []
    company = _field(r, "company_name")
    # Scans since 22 Oct 2026 name a rejected stock only by "company" ("Yes Bank (YESBANK.NS)"): the terminal
    # lists rejected rows by raw_ticker (text and React key), so it falls back to the company name, not "".
    return {"raw_ticker": raw or str(company or ""), "symbols": symbols,
            "company_name": company, "reason": r.get("reason")}


# Where a scan keeps its picks, first match wins. "stage1_candidates" is the scanner's key since 22 Oct 2026 (with
# "rejected" alongside); without it those scans read as 0 picks and the track record stopped at 20 Oct.
_PICK_KEYS = ("stage1_picks", "stage1_candidates", "picks", "stocks", "results", "data", "items", "candidates")


def load_scan_file(path: Path) -> dict[str, Any]:
    """Read one scan (JSON object, bare JSON array, or CSV) into a common raw dict:
    {'picks': [...], 'rejected': [...], meta...}. Raises ValueError when unreadable."""
    if path.suffix.lower() == ".csv":
        import csv
        with path.open(newline="", encoding="utf-8-sig") as f:
            rows = [r for r in csv.DictReader(f) if any((v or "").strip() for v in r.values())]
        return {"picks": rows, "rejected": [], "source_format": "csv"}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, list):                                   # the prompt's schema: a bare array
        return {"picks": [x for x in data if isinstance(x, dict)], "rejected": [], "source_format": "json-array"}
    if not isinstance(data, dict):
        raise ValueError("top level must be a JSON object or array")
    picks = next((data[k] for k in _PICK_KEYS if isinstance(data.get(k), list)), None)
    if picks is None and _field(data, "ticker"):
        picks = [data]                                           # a single pick object
    return {**data, "picks": [x for x in (picks or []) if isinstance(x, dict)],
            "rejected": [x for x in data.get("rejected_stage2_stage3", data.get("rejected", [])) or []
                         if isinstance(x, dict)],
            "source_format": "json"}


def _read_scan(path: Path) -> dict[str, Any]:
    try:
        raw = load_scan_file(path)
    except (OSError, ValueError, UnicodeDecodeError) as exc:     # JSONDecodeError is a ValueError
        raise HTTPException(status_code=422, detail=f"{path.name}: unreadable scan ({exc})")
    picks = [_normalise_pick(p) for p in raw["picks"]]
    unresolved = [p["raw_ticker"] for p in picks if not p["symbol"]]
    picks = [p for p in picks if p["symbol"]]
    picks.sort(key=lambda p: -(p.get("conviction_score") or 0))
    m = _SCAN_FILE.match(path.name)
    ymd = m.group(1) if m else path.stem
    return {
        "file": path.name,
        "source_format": raw["source_format"],
        "scan_date": raw.get("scan_date") or f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}",
        "generated_by": raw.get("generated_by"),
        "input_note": raw.get("input_note"),
        "macro_context": raw.get("macro_context"),
        "picks": picks,
        "unresolved_tickers": unresolved,
        "rejected": [_normalise_rejected(r) for r in raw["rejected"]],
        "disclaimer": raw.get("disclaimer"),
        "run_log": raw.get("run_log", []),
        "modified_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
        "version": int(path.stat().st_mtime),
    }


# ── TTL cache + Yahoo client ────────────────────────────────────────────────────
# Bounded (F2.1): the old module dict kept 2-year candle frames per symbol forever — the
# ui-api leak named in reports/production_review/scale_latency.md §3. Key/TTL semantics unchanged.
_cache = TTLCache("news_scanner", max_items=600, default_ttl=120)
_yahoo_sem = asyncio.Semaphore(6)
_UA = {"User-Agent": "Mozilla/5.0 (SuryaDhana-NewsTerminal)"}
_TIMEOUT = httpx.Timeout(15.0)


def _cache_get(key: str) -> Any | None:
    return _cache.get(key)


def _cache_set(key: str, value: Any, ttl: float) -> None:
    _cache.set(key, value, ttl)


def _check_symbol(symbol: str) -> str:
    s = symbol.strip().upper()
    if not _SYMBOL_OK.match(s):
        raise HTTPException(status_code=422, detail=f"invalid symbol '{symbol}'")
    return s


async def _yahoo_chart(symbol: str, rng: str, interval: str) -> dict[str, Any] | None:
    async with _yahoo_sem:
        for host in ("query1", "query2"):
            try:
                async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_UA) as client:
                    r = await client.get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{symbol}",
                                         params={"range": rng, "interval": interval,
                                                 "includePrePost": "false", "events": "div,splits"})
                if r.status_code == 200:
                    res = (r.json().get("chart") or {}).get("result")
                    return res[0] if res else None
                if r.status_code == 404:
                    return None
            except (httpx.RequestError, ValueError):
                continue
    return None


def _alt_symbol(sym: str) -> str | None:
    if sym.endswith(".NS"):
        return sym[:-3] + ".BO"
    if sym.endswith(".BO"):
        return sym[:-3] + ".NS"
    return None


async def _resolve_chart(sym: str, rng: str, interval: str) -> tuple[str, dict[str, Any] | None]:
    """Yahoo chart for `sym`, falling back to the other Indian exchange when the scanner's
    exchange guess has no Yahoo data (e.g. a BSE-only company written as X.NS)."""
    known = _cache_get(f"alias:{sym}")
    first = known or sym
    chart = await _yahoo_chart(first, rng, interval)
    if chart or known:
        return first, chart
    alt = _alt_symbol(sym)
    if alt:
        chart = await _yahoo_chart(alt, rng, interval)
        if chart:
            _cache_set(f"alias:{sym}", alt, 86400)
            return alt, chart
    return sym, None


def _candles(chart: dict[str, Any]) -> list[dict[str, Any]]:
    ts = chart.get("timestamp") or []
    q = ((chart.get("indicators") or {}).get("quote") or [{}])[0]
    out = []
    for i, t in enumerate(ts):
        o, h, l, c, v = (q.get(k, [None] * len(ts))[i] for k in ("open", "high", "low", "close", "volume"))
        if None in (o, h, l, c):
            continue
        out.append({"time": int(t), "open": float(o), "high": float(h), "low": float(l),
                    "close": float(c), "volume": int(v or 0)})
    return out


def _quote_from(chart: dict[str, Any], candles: list[dict[str, Any]]) -> dict[str, Any]:
    meta = chart.get("meta") or {}
    price = meta.get("regularMarketPrice") or (candles[-1]["close"] if candles else None)
    # Previous close = the last completed session before the live price's session. Yahoo often leaves today's daily
    # bar without a close (it's then dropped from candles), so candles[-1] can already be the previous session;
    # blindly taking candles[-2] turned KOSPI's -5.5% on 13 Oct into a two-session -8.9%.
    off = int(meta.get("gmtoffset") or 0)
    local_day = lambda t: time.strftime("%Y-%m-%d", time.gmtime(int(t) + off))  # noqa: E731
    mt = meta.get("regularMarketTime")
    prev_bar = None
    if candles and mt and local_day(candles[-1]["time"]) < local_day(mt):
        prev_bar = candles[-1]
    elif len(candles) >= 2:
        prev_bar = candles[-2]
    prev = prev_bar["close"] if prev_bar else meta.get("chartPreviousClose")
    change = (price - prev) if price is not None and prev else None
    return {
        "symbol": meta.get("symbol"),
        "name": meta.get("longName") or meta.get("shortName"),
        "currency": meta.get("currency"),
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
        "price": price,
        "prev_close": prev,
        # the sessions the change spans: a gap of more than one weekday means a holiday or a bar Yahoo skipped
        "prev_date": local_day(prev_bar["time"]) if prev_bar else None,
        "market_date": local_day(mt) if mt else None,
        "change": change,
        "change_pct": (change / prev * 100) if change is not None and prev else None,
        "day_high": meta.get("regularMarketDayHigh"),
        "day_low": meta.get("regularMarketDayLow"),
        "volume": meta.get("regularMarketVolume"),
        "high_52w": meta.get("fiftyTwoWeekHigh"),
        "low_52w": meta.get("fiftyTwoWeekLow"),
        "market_time": meta.get("regularMarketTime"),
        "gmtoffset": meta.get("gmtoffset") or 0,           # exchange-local seconds vs UTC
        "timezone": meta.get("exchangeTimezoneName"),
        "stale": bool(meta.get("regularMarketTime")) and time.time() - meta["regularMarketTime"] > 4 * 86400,
    }


# ── Indicators (pure python, trailing only) ─────────────────────────────────────

def _sma(vals: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(vals)
    s = 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= n:
            s -= vals[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def _rsi(closes: list[float], n: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0); losses += max(-d, 0)
    ag, al = gains / n, losses / n
    out[n] = 100 - 100 / (1 + ag / al) if al else 100.0
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
        out[i] = 100 - 100 / (1 + ag / al) if al else 100.0
    return out


def _atr_pct(c: list[dict[str, Any]], n: int = 14) -> float | None:
    if len(c) <= n:
        return None
    trs = [max(c[i]["high"] - c[i]["low"], abs(c[i]["high"] - c[i - 1]["close"]),
               abs(c[i]["low"] - c[i - 1]["close"])) for i in range(1, len(c))]
    atr = sum(trs[-n:]) / n
    return atr / c[-1]["close"] * 100 if c[-1]["close"] else None


def _ret(closes: list[float], bars: int) -> float | None:
    if len(closes) <= bars or not closes[-bars - 1]:
        return None
    return (closes[-1] / closes[-bars - 1] - 1) * 100


def _clean(x: Any) -> Any:
    return None if isinstance(x, float) and (math.isnan(x) or math.isinf(x)) else x


# ── Endpoints ──────────────────────────────────────────────────────────────────

def _track_record_path() -> Path:
    for root in (Path(__file__).resolve().parents[3], Path("/app")):
        p = root / "reports" / "news_scanner" / "track_record.json"
        if p.is_file():
            return p
    return Path(__file__).resolve().parents[3] / "reports" / "news_scanner" / "track_record.json"


@router.get("/track-record")
def track_record() -> dict[str, Any]:
    """How past picks did (written by scripts/news_scan_performance.py; refreshed after the EOD pipeline)."""
    p = _track_record_path()
    if not p.is_file():
        raise HTTPException(status_code=404, detail="No track record yet: run scripts/news_scan_performance.py")
    return {**json.loads(p.read_text(encoding="utf-8")), "file_mtime": int(p.stat().st_mtime)}


@router.get("/scans")
def list_scans() -> dict[str, Any]:
    d = _scan_dir()
    scans = []
    for ymd, p in _scan_files(d):
        entry = {"date": ymd, "file": p.name, "version": int(p.stat().st_mtime), "error": None}
        try:
            raw = load_scan_file(p)
            entry.update(picks=len(raw["picks"]), rejected=len(raw["rejected"]))
        except Exception as exc:   # being written / malformed: surfaced, never breaks the listing
            entry.update(picks=-1, rejected=-1, error=f"{type(exc).__name__}: {exc}"[:200])
        scans.append(entry)
    return {"directory": str(d), "exists": d.is_dir(), "scans": scans,
            "latest_version": scans[0]["version"] if scans else None}


@router.get("/scan")
def get_scan(date: str = Query("latest", pattern=r"^(latest|\d{8})$")) -> dict[str, Any]:
    d = _scan_dir()
    if not d.is_dir():
        raise HTTPException(status_code=404, detail=f"scanner folder not found: {d}")
    files = _scan_files(d)
    if not files:
        raise HTTPException(status_code=404, detail=f"no YYYYMMDD.json / .csv scans in {d}")
    if date == "latest":
        # newest file that parses — a half-written file for today must not blank the terminal
        for _, path in files:
            try:
                return _read_scan(path)
            except HTTPException:
                continue
        raise HTTPException(status_code=422, detail="no readable scan files")
    path = dict(files).get(date)
    if not path:
        raise HTTPException(status_code=404, detail=f"scan {date} not found")
    return _read_scan(path)


async def _official_prev_close(pairs: list[tuple[str, Any]]) -> list[tuple[str, Any]]:
    """Re-base NSE stocks' day change on the official previous close (our NSE bhavcopy): Yahoo's daily series can
    skip a session (12 Oct 2026 was missing), which turned 'today' into a two-day change. Applied on copies, so
    the cached Yahoo quote stays as fetched."""
    from datetime import datetime, timedelta, timezone
    ist = timezone(timedelta(hours=5, minutes=30))
    want: dict[str, list[str]] = {}
    for sym, q in pairs:
        used = str((q or {}).get("resolved_symbol") or sym)
        if q and q.get("available") and used.endswith(".NS") and q.get("market_time") and q.get("price"):
            day = datetime.fromtimestamp(q["market_time"], ist).date().isoformat()
            want.setdefault(day, []).append(used[:-3])
    if not want:
        return pairs
    prev: dict[str, float] = {}
    base = os.environ.get("DATA_SERVICE_URL", "http://localhost:8001")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0)) as client:
            for day, names in want.items():
                r = await client.get(f"{base}/db/prev-close", params={"symbols": ",".join(names), "before": day})
                if r.status_code == 200:
                    prev.update({f"{k}.NS": v["close"] for k, v in (r.json().get("prev") or {}).items()})
    except httpx.HTTPError:
        return pairs                                    # keep Yahoo's figures rather than fail the quote
    out = []
    for sym, q in pairs:
        used = str((q or {}).get("resolved_symbol") or sym)
        p = prev.get(used)
        if q and p and q.get("price"):
            ch = q["price"] - p
            q = {**q, "prev_close": p, "change": ch, "change_pct": ch / p * 100, "prev_source": "NSE"}
        out.append((sym, q))
    return out


# Per-symbol quote cache (desktop review C-PERF-01). The staleness BOUND is unchanged: a quote is never served
# older than QUOTE_MAX_AGE_S (the old 60 s TTL). What changed:
#   * single flight: concurrent requests for one symbol (several windows, the tape plus WTCH, the scheduler)
#     share ONE Yahoo fetch instead of each fetching it (the Yahoo semaphore is 6 wide, so duplicates queued);
#   * stale-while-revalidate inside the old TTL, for DISPLAY reads: a quote older than QUOTE_REFRESH_AFTER_S is
#     still served at once and refreshed in the background, so a poller never waits 1.7-2.3 s on Yahoo. The
#     TYPICAL age did change: a 60 s poller (WTCH, WEI, the macro tape) now gets the quote its previous poll
#     fetched, about 58 s old, every time (the old TTL alternated between a fresh fetch and that quote);
#   * DECISION reads ask for fresh=True (the price-alert check, POST /api/alerts/run, in-process; the controller's
#     move check via ?fresh=1): a quote at or past QUOTE_REFRESH_AFTER_S is then a miss the caller waits for
#     (sharing a refresh already running), so an alert always prices with a quote under 30 s old -- at least as
#     fresh as under the old TTL -- at the cost of 0.5-2 s more on that call (round 3 review, major);
#   * "not available" answers are kept QUOTE_UNAVAILABLE_S, as before, with no early refresh (fresh=True too).
# The oldest quote's age goes in the X-Cache-Age response header (seconds); the body is unchanged.
QUOTE_REFRESH_AFTER_S = 30.0
QUOTE_MAX_AGE_S = 60.0
QUOTE_UNAVAILABLE_S = 120.0
_quotes = SWRCache("news_scanner.quotes", max_items=600, refresh_after=QUOTE_REFRESH_AFTER_S,
                   max_age=QUOTE_MAX_AGE_S)


def _quote_policy(q: dict[str, Any]) -> tuple[float, float]:
    if q.get("available"):
        return QUOTE_REFRESH_AFTER_S, QUOTE_MAX_AGE_S
    return QUOTE_UNAVAILABLE_S, QUOTE_UNAVAILABLE_S


async def _fetch_quote(sym: str) -> dict[str, Any]:
    used, chart = await _resolve_chart(sym, "1mo", "1d")
    if not chart:
        return {"symbol": sym, "available": False}
    c = _candles(chart)
    return {**_quote_from(chart, c), "available": True, "resolved_symbol": used,
            "spark": [round(x["close"], 4) for x in c[-22:]]}


@router.get("/quotes")
async def get_quotes(symbols: str = Query(..., min_length=1, max_length=2000),
                     response: Response = None,  # type: ignore[assignment]  # injected by FastAPI
                     fresh: bool = False) -> dict[str, Any]:
    """Batch quotes. ``fresh`` (query ``?fresh=1``): for a caller that DECIDES on the price (alerts) -- every
    quote is under QUOTE_REFRESH_AFTER_S old (see the cache comment above). Plain defaults, so a direct call
    from Python without ``fresh`` gets the display behaviour."""
    syms = list(dict.fromkeys(_check_symbol(s) for s in symbols.split(",") if s.strip()))[:60]
    served = await asyncio.gather(*(_quotes.get(s, functools.partial(_fetch_quote, s), policy=_quote_policy,
                                                fresh=bool(fresh))
                                    for s in syms))
    pairs: list[tuple[str, Any]] = [(s, sv.value) for s, sv in zip(syms, served)]
    pairs = await _official_prev_close(pairs)
    cache_headers(response, merge_served(list(served)))
    return {"quotes": {s: q for s, q in pairs}, "as_of": datetime.now(timezone.utc).isoformat()}


async def _daily(sym: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """2y of daily bars (enough for SMA200) + quote — the basis for every stat."""
    key = f"d:{sym}"
    if (hit := _cache_get(key)) is not None:
        return hit
    used, chart = await _resolve_chart(sym, "2y", "1d")
    if not chart:
        tried = f"{sym} or {_alt_symbol(sym)}" if _alt_symbol(sym) else sym
        raise HTTPException(status_code=404, detail=f"No Yahoo Finance data for {tried}")
    c = _candles(chart)
    if not c:
        raise HTTPException(status_code=404, detail=f"Yahoo returned no bars for {sym}")
    out = (_quote_from(chart, c), c)
    _cache_set(key, out, 300)
    return out


def _daily_stats(quote: dict[str, Any], c: list[dict[str, Any]]) -> dict[str, Any]:
    """Returns / RSI / ATR / trend / volume / 52w position — ALWAYS from daily bars, so
    '1M return' means one month whatever range the chart is showing."""
    closes = [x["close"] for x in c]
    last = len(c) - 1
    sma20, sma50, sma200, rsi = _sma(closes, 20), _sma(closes, 50), _sma(closes, 200), _rsi(closes)
    vol20 = sum(x["volume"] for x in c[-20:]) / min(20, len(c))
    stats = {
        "ret_1d": _ret(closes, 1), "ret_5d": _ret(closes, 5), "ret_1m": _ret(closes, 21),
        "ret_3m": _ret(closes, 63), "ret_6m": _ret(closes, 126), "ret_1y": _ret(closes, 252),
        "rsi_14": rsi[last], "atr_pct": _atr_pct(c),
        "sma20": sma20[last], "sma50": sma50[last], "sma200": sma200[last],
        "above_sma50": (closes[-1] > sma50[last]) if sma50[last] else None,
        "above_sma200": (closes[-1] > sma200[last]) if sma200[last] else None,
        "avg_volume_20d": vol20, "volume_ratio": (c[-1]["volume"] / vol20) if vol20 else None,
        "pct_from_52w_high": ((closes[-1] / quote["high_52w"] - 1) * 100) if quote.get("high_52w") else None,
        "pct_from_52w_low": ((closes[-1] / quote["low_52w"] - 1) * 100) if quote.get("low_52w") else None,
        "history_days": len(c),
    }
    return {k: _clean(v) for k, v in stats.items()}


_RANGES = {"1d": "5m", "5d": "15m", "1mo": "1d", "3mo": "1d", "6mo": "1d", "1y": "1d", "2y": "1d", "5y": "1wk"}
_KEEP_DAILY = {"1mo": 22, "3mo": 64, "6mo": 127, "1y": 253, "2y": 10_000}


# `rng` (alias ?range=): naming the parameter `range` shadowed the builtin.
@router.get("/chart/{symbol}")
async def get_chart(symbol: str, rng: str = Query("1y", alias="range")) -> dict[str, Any]:
    sym = _check_symbol(symbol)
    if rng not in _RANGES:
        raise HTTPException(status_code=422, detail=f"range must be one of {list(_RANGES)}")
    key = f"c:{sym}:{rng}"
    if (hit := _cache_get(key)) is not None:
        return hit

    quote, daily = await _daily(sym)
    interval = _RANGES[rng]
    if interval == "1d":
        bars = daily
        start = max(0, len(bars) - _KEEP_DAILY[rng])
    else:  # intraday / weekly display bars; overlays computed on those bars
        _, chart = await _resolve_chart(sym, rng, interval)
        bars = _candles(chart) if chart else []
        if not bars:
            raise HTTPException(status_code=404, detail=f"No {rng} bars for {sym}")
        start = 0
    closes = [x["close"] for x in bars]
    overlays = {"sma20": _sma(closes, 20), "sma50": _sma(closes, 50),
                "sma200": _sma(closes, 200), "rsi": _rsi(closes)}

    def series(arr: list[float | None]) -> list[dict[str, Any]]:
        return [{"time": bars[i]["time"], "value": round(arr[i], 4)}
                for i in range(start, len(bars)) if arr[i] is not None]

    out = {
        "symbol": sym, "range": rng, "interval": interval, "quote": quote,
        "intraday": interval not in ("1d", "1wk"),
        "candles": bars[start:],
        **{k: series(v) for k, v in overlays.items()},
        "stats": _daily_stats(quote, daily),
    }
    _cache_set(key, out, 60 if out["intraday"] else 300)
    return out


_LEGAL_SUFFIX = re.compile(r"[,\s]+(ltd\.?|limited|inc\.?|plc|corp\.?|co\.?|n\.?v\.?|s\.?a\.?|ag|se)$", re.I)


def clean_company_name(name: str | None) -> str:
    """'Cipher Digital Inc. (formerly Cipher Mining)' → 'Cipher Digital'. Keeps words
    like 'Corporation of India' that are part of the name."""
    n = re.sub(r"\([^)]*\)", "", name or "").strip()
    n = re.sub(r"^the\s+", "", n, flags=re.I)
    prev = None
    while prev != n:
        prev, n = n, _LEGAL_SUFFIX.sub("", n).strip()
    return n


async def _yahoo_news(sym: str, count: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    try:
        async with _yahoo_sem, httpx.AsyncClient(timeout=_TIMEOUT, headers=_UA) as client:
            r = await client.get("https://query2.finance.yahoo.com/v1/finance/search",
                                 params={"q": sym, "newsCount": count, "quotesCount": 0,
                                         "enableFuzzyQuery": "false"})
        if r.status_code == 200:
            for n in r.json().get("news", [])[:count]:
                thumbs = ((n.get("thumbnail") or {}).get("resolutions") or [])
                items.append({
                    "title": n.get("title"), "publisher": n.get("publisher"), "link": n.get("link"),
                    "published_at": datetime.fromtimestamp(n["providerPublishTime"], tz=timezone.utc).isoformat()
                    if n.get("providerPublishTime") else None,
                    "related": n.get("relatedTickers", []),
                    "thumbnail": thumbs[-1]["url"] if thumbs else None,
                    "feed": "Yahoo Finance",
                })
    except (httpx.RequestError, ValueError, KeyError):
        pass
    return items


async def _google_news(company: str, region: str, count: int) -> list[dict[str, Any]]:
    """Google News RSS by EXACT company name (quoted). Yahoo has little coverage for
    Indian mid/small caps, and a bare-ticker search returns other companies
    (e.g. 'TCI' → Transcontinental Realty), so the quoted name is the safe key."""
    from email.utils import parsedate_to_datetime
    import xml.etree.ElementTree as ET

    if not company:
        return []
    loc = {"IN": ("en-IN", "IN"), "UK": ("en-GB", "GB")}.get(region, ("en-US", "US"))
    items: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_UA) as client:
            r = await client.get("https://news.google.com/rss/search",
                                 params={"q": f'"{company}"', "hl": loc[0], "gl": loc[1], "ceid": f"{loc[1]}:en"})
        if r.status_code != 200:
            return []
        for it in ET.fromstring(r.content).findall("./channel/item"):
            title, publisher = it.findtext("title") or "", it.findtext("source") or ""
            if publisher and title.endswith(f" - {publisher}"):
                title = title[: -len(publisher) - 3]
            try:
                published = parsedate_to_datetime(it.findtext("pubDate") or "").astimezone(timezone.utc).isoformat()
            except (TypeError, ValueError):
                published = None
            items.append({"title": title, "publisher": publisher, "link": it.findtext("link"),
                          "published_at": published, "related": [], "thumbnail": None, "feed": "Google News"})
    except (httpx.RequestError, ET.ParseError):
        return []
    items.sort(key=lambda x: x["published_at"] or "", reverse=True)
    return items[:count]


@router.get("/headlines/{symbol}")
async def get_headlines(symbol: str, count: int = Query(12, ge=1, le=30),
                        name: str | None = Query(None, max_length=160),
                        region: str = Query("US", pattern=r"^(US|IN|UK|OTHER)$")) -> dict[str, Any]:
    """Latest headlines: Yahoo Finance (by symbol) + Google News (by exact company name),
    de-duplicated and newest first."""
    sym = _check_symbol(symbol)
    company = clean_company_name(name)
    key = f"h:{sym}:{company}:{region}:{count}"
    if (hit := _cache_get(key)) is not None:
        return hit
    yahoo, google = await asyncio.gather(_yahoo_news(sym, count), _google_news(company, region, count))
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for item in yahoo + google:
        k = re.sub(r"\W+", "", (item["title"] or "").lower())[:80]
        if k and k not in seen:
            seen.add(k); merged.append(item)
    merged.sort(key=lambda x: x["published_at"] or "", reverse=True)
    out = {"symbol": sym, "company_query": company, "available": bool(merged), "items": merged[:count],
           "feeds": {"yahoo": len(yahoo), "google": len(google)}}
    _cache_set(key, out, 600 if merged else 120)
    return out

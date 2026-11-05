"""
Gold Pre-Open desk — where should MCX Gold open, and is the opening price worth chasing?

    fair open = MCX settlement × (COMEX now ÷ COMEX at the MCX close) × (USD/INR now ÷ USD/INR at the close)

Inputs, all free and fetched automatically:
  * MCX baseline: the previous day's settlement price, read from ICICI's public security master
    (MCXScripMaster.txt, published ~07:00 IST). Its daily price band is ±3% around that settlement,
    so the midpoint is the settlement. Overridable with the trader's own close; replaced by the
    broker's previous close when an ICICI Breeze session is live.
  * COMEX: the matching-month contract (MCX Dec ↔ GCZ26) from Yahoo 5-minute bars.
  * USD/INR: Yahoo INR=X (offshore quotes before 09:00 IST; a proxy for the NDF).
  * References: the average over the last 30 minutes before MCX closed (23:30 IST while New York
    is on daylight time, 23:55 otherwise), the same window MCX uses for its settlement price.
Context: DXY, EUR/USD, US 10-year yield (Yahoo), 10-year real yield (FRED DFII10, one day late),
headlines (Google News RSS). Fed odds, MCX circulars, SGE premium and ETF flows have no free feed:
the panel links to them.

Verdict: MCX price within the threshold (default ₹300) of fair → OK to trade the open; otherwise
don't chase, wait 15–30 minutes for the rupee's 09:00 open to settle, then recompute. The verdict
wears the `heuristic` badge (GOLD program PLAN §f): the ₹300 limit is a house rule whose measured
miss is in the accuracy log, not evidence.

GOLD program (26 Oct 2026, PLAN §b/§d): the desk's home is GOLD › HEALTH (`/api/gold/fair`); these
routes stay mounted under /api/commodity as aliases for one release. Additions: the baseline carries
its session label ("Thu 22 Oct settlement", never the ICICI file date); the duty leg (landed,
duty-paid landed, basis vs duty-paid landed — `implied_premium_pct` stays as a deprecated alias);
MCX holiday awareness for the 08:45 snapshot and the 09:10 capture; `inputs_json` on every log row;
the ICICI master is re-checked with a conditional GET; the accuracy log is dual-written to
data-service's `gold_preopen_log` when it answers.
"""
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import csv
import functools
import json
import logging
import sys
import threading
import io
import os
import re
import time
import zipfile
from collections.abc import Awaitable, Callable
from datetime import date, datetime, time as dtime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from cache import HIT, MISS, STALE, Served, TTLCache, cache_headers, merge_served
from fastapi import APIRouter, Body, HTTPException, Query, Response

for _p in (Path(__file__).resolve().parents[3], Path(__file__).resolve().parents[1]):
    if (_p / "shared").is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from shared import mcx_specs as specs  # noqa: E402

router = APIRouter()
_log = logging.getLogger("ui-api.gold_preopen")

IST = ZoneInfo("Asia/Kolkata")
NY = ZoneInfo("America/New_York")
GRAMS_PER_TROY_OZ = 31.1034768
MCX_GOLD_LOT_KG = 1                  # GOLD: 1 kg lot, price per 10 g → ₹100 P&L per ₹1 move
SECURITY_MASTER_URL = "https://directlink.icicidirect.com/MotherAppMaster/SecurityMaster.zip"
COMEX_MONTH = {1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M", 7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z"}
_UA = {"User-Agent": "Mozilla/5.0 (SuryaDhana-GoldDesk)"}
_TIMEOUT = httpx.Timeout(15.0)

# Customs duty on gold (SOURCES.md F9): BCD 10 % + AIDC 5 % = 15 % since 13 May 2026 (Notification 16/2026-Customs),
# 6 % before that (24 Jul 2024). A DATED constant read from the environment (`GOLD_IMPORT_DUTY_PCT`,
# `GOLD_IMPORT_DUTY_EFFECTIVE`; shared/config.py carries the same defaults once B3's patch lands); the owner confirms
# the primary at CBIC (PLAN §i O-3) — every render says so.
DUTY_DEFAULT_PCT = 15.0
DUTY_DEFAULT_EFFECTIVE = "2026-05-13"
DUTY_NOTIFICATION = "Notification 16/2026-Customs (BCD 10 % + AIDC 5 %)"
DUTY_NOTE = "confirm at CBIC (owner action O-3); Budget 1 Feb is a jump event"
DUTY_HISTORY: tuple[tuple[str, float], ...] = (("2024-07-24", 6.0), ("2026-05-13", 15.0))


def duty_rate() -> dict[str, Any]:
    """The dated import-duty constant the India price stack uses: {pct, effective, notification, note}."""
    try:
        pct = float(os.environ.get("GOLD_IMPORT_DUTY_PCT", "").strip() or DUTY_DEFAULT_PCT)
    except ValueError:
        pct = DUTY_DEFAULT_PCT
    effective = os.environ.get("GOLD_IMPORT_DUTY_EFFECTIVE", "").strip() or DUTY_DEFAULT_EFFECTIVE
    return {"pct": pct, "effective": effective, "notification": DUTY_NOTIFICATION, "note": DUTY_NOTE}


def landed_inr_per_10g(usd_per_oz: float, usdinr: float, quote_grams: float = 10.0) -> float:
    """COMEX/LBMA $/oz × USD/INR ÷ 31.1034768 × grams — the ex-duty landed cost (SOURCES.md M5)."""
    return usd_per_oz * usdinr / GRAMS_PER_TROY_OZ * quote_grams

CONTEXT_SERIES = [
    # key, label, Yahoo symbol, unit, gold-positive direction (-1: falling is good for gold)
    ("dxy", "Dollar index (DXY)", "DX-Y.NYB", "", -1),
    ("eurusd", "EUR/USD", "EURUSD=X", "", +1),
    ("us10y", "US 10-year yield", "^TNX", "%", -1),
    ("silver", "COMEX silver", "SI=F", "$", +1),
]
HEADLINE_TOPICS = [  # (label, Google News query, a word the title must contain to count)
    ("Gold", '"gold prices" OR "spot gold" OR "gold futures"', r"gold"),
    ("Fed", '"Federal Reserve" OR "Fed rate" OR FOMC', r"fed|fomc|powell|rate"),
    ("Iran / Hormuz", "Iran OR Hormuz OR Strait", r"iran|hormuz|strait|israel"),
    ("China gold", '"Shanghai Gold" OR "China gold" OR PBOC gold OR "gold imports"', r"china|chinese|shanghai|pboc|sge"),
    ("Rupee", "rupee dollar RBI forex", r"rupee|rbi|inr"),
]   # the "France / OAT" topic was dropped by the GOLD program (PLAN §b); topics can be narrowed via prefs gold.triggers.v1
PREFS_TRIGGERS_KEY = "gold.triggers.v1"         # {"eurusd_trigger": 1.1161, "topics": ["Gold", "Fed", …]} (B4 writes it)
DEFAULT_EURUSD_TRIGGER = 1.1161
# Explainers and rate-card pages that rank in news search but carry no news.
_EVERGREEN = re.compile(r"factors (that )?(affect|influence)|what (is|are|influences)|how to|gold rate today|"
                        r"price today in|explained|things to know|should you buy", re.I)
MANUAL_CHECKS = [
    ("Fed odds", "CME FedWatch: October hold % and December hike %", "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html"),
    ("MCX circulars", "Margin or special-margin changes for GOLD", "https://www.mcxindia.com/circulars/all-circulars"),
    # (the investing.com USD/INR link was removed by the GOLD program: 403 to scripts and INR=X is in the app)
    ("FBIL reference", "Official USD/INR reference rate (after ~13:30 IST)", "https://www.fbil.org.in/"),
    ("SGE premium", "Shanghai premium and volume at the China open", "https://en.sge.com.cn/data_DelayedQuotes"),
    ("ETF flows", "World Gold Council gold ETF flows", "https://www.gold.org/goldhub/data/gold-etfs-holdings-and-flows"),
    ("GLD holdings", "SPDR Gold Shares tonnes", "https://www.spdrgoldshares.com/usa/"),
    ("Real yields", "10-year TIPS live (FRED DFII10 is a day late)", "https://fred.stlouisfed.org/series/DFII10"),
    ("COMEX chart", "GC Dec on TradingView", "https://www.tradingview.com/chart/?symbol=COMEX%3AGCZ2026"),
    ("Kitco", "Spot gold and news", "https://www.kitco.com/charts/gold"),
]

# Bounded store (F2.1). This module checks TTL at READ time with per-read windows (fred 6 h,
# news 300 s …), so entries carry their stored_at and the cache bound only handles eviction.
_cache = TTLCache("gold_preopen", max_items=32, default_ttl=12 * 3600)


def _cached(key: str, ttl: float) -> Any | None:
    hit = _cache.get(key)
    return hit[1] if hit and time.monotonic() - hit[0] < ttl else None


def _store(key: str, value: Any) -> Any:
    _cache.set(key, (time.monotonic(), value))
    return value


# ── pure functions (unit-tested) ────────────────────────────────────────────────

def parse_mcx_gold(master_text: str) -> list[dict[str, Any]]:
    """GOLD futures rows from ICICI's MCXScripMaster.txt with the settlement implied by the band."""
    out = []
    for r in csv.DictReader(io.StringIO(master_text), skipinitialspace=True):
        if r.get("ShortName") != "GOLD" or r.get("Series") != "FUTURE":
            continue
        try:
            lo, hi = float(r["LowPriceRange"]), float(r["HighPriceRange"])
            expiry = datetime.strptime(r["ExpiryDate"], "%d-%b-%Y").date()
        except (KeyError, ValueError):
            continue
        settle = (lo + hi) / 2
        out.append({"expiry": expiry, "band_low": lo, "band_high": hi, "settlement": round(settle, 2),
                    # ICICI's header is shifted: the "MarginPercentage" column carries open interest (lots)
                    "band_pct": round((hi - settle) / settle * 100, 2), "open_interest": float(r.get("MarginPercentage") or 0)})
    return sorted(out, key=lambda c: c["expiry"])


def pick_contract(contracts: list[dict[str, Any]], today: date, roll_days: int = 5) -> dict[str, Any] | None:
    """The traded contract: highest open interest among expiries more than `roll_days` away
    (traders roll before expiry week); nearest expiry when open interest is missing."""
    live = [c for c in contracts if (c["expiry"] - today).days > roll_days]
    if not live:
        return None
    return max(live, key=lambda c: (c["open_interest"], -c["expiry"].toordinal()))


def comex_symbol(mcx_expiry: date) -> str:
    """MCX GOLD Dec-26 ↔ COMEX GCZ26 (Yahoo: GCZ26.CMX)."""
    return f"GC{COMEX_MONTH[mcx_expiry.month]}{mcx_expiry.year % 100:02d}.CMX"


def mcx_close_time(day: date) -> datetime:
    """MCX evening close: 23:30 IST while New York is on daylight time, else 23:55."""
    noon_ny = datetime(day.year, day.month, day.day, 12, tzinfo=NY)
    hh, mm = (23, 30) if noon_ny.dst() else (23, 55)
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=IST)


def previous_session(publish_day: date) -> date:
    """Trading day whose settlement a security master published on `publish_day` carries (weekends and MCX full
    holidays skipped: the Monday file after a Friday holiday carries Thursday's settlement)."""
    d = publish_day - timedelta(days=1)
    while d.weekday() >= 5 or (specs.holiday_on(d) or (None, None))[1] == "full":
        d -= timedelta(days=1)
    return d


def session_label(settle_day: date) -> str:
    """How a settlement is named everywhere (PLAN 0.1 #8): by its SESSION, e.g. 'Thu 22 Oct settlement'."""
    return f"{settle_day:%a %d %b} settlement"


def mcx_day(day: date) -> dict[str, Any]:
    """MCX calendar facts for `day`: {trading, closure, name, opens_at, closes_at, note} (full / morning / evening
    closures from shared/mcx_specs; weekends count as closed)."""
    hol = specs.holiday_on(day)
    window = specs.trading_window(day)
    out: dict[str, Any] = {"date": day.isoformat(), "trading": window is not None,
                           "closure": hol[1] if hol else ("weekend" if day.weekday() >= 5 else None),
                           "name": hol[0] if hol else None,
                           "opens_at": window[0].isoformat(timespec="minutes") if window else None,
                           "closes_at": window[1].isoformat(timespec="minutes") if window else None}
    if hol and hol[1] == "full":
        out["note"] = f"MCX closed ({hol[0]})"
    elif hol and hol[1] == "morning":
        out["note"] = f"MCX morning session closed ({hol[0]}): opens {window[0]:%H:%M}" if window else f"MCX closed ({hol[0]})"
    elif hol and hol[1] == "evening":
        out["note"] = f"MCX evening session closed ({hol[0]}): closes {window[1]:%H:%M}" if window else None
    elif day.weekday() >= 5:
        out["note"] = "MCX closed (weekend)"
    else:
        out["note"] = None
    return out


def reference_price(bars: list[tuple[datetime, float]], close_at: datetime, window_min: int = 30) -> tuple[float | None, str]:
    """Average of bars in the last `window_min` minutes before `close_at`; else the last bar before it."""
    start = close_at - timedelta(minutes=window_min)
    inside = [v for t, v in bars if start <= t < close_at]
    if inside:
        return sum(inside) / len(inside), f"{len(inside)}-bar average {start:%H:%M}–{close_at:%H:%M} IST"
    before = [(t, v) for t, v in bars if t < close_at]
    if before:
        t, v = before[-1]
        return v, f"last print before the close ({t.astimezone(IST):%d %b %H:%M} IST)"
    return None, "no data at the close"


def fair_open(settlement: float, comex_ref: float, comex_now: float, inr_ref: float, inr_now: float,
              duty_pct: float | None = None) -> dict[str, float]:
    """Multiplicative fair value plus a split of the gap into its COMEX and rupee parts, and the duty leg
    (SOURCES.md M5–M8): landed at the MCX-close references, duty-paid landed, and the settlement's basis vs duty-paid
    landed. `implied_premium_pct` (settlement vs EX-duty landed) stays for one release as a deprecated alias: it
    rolled duty, carry and premium into one "17 %" number."""
    r_c, r_i = comex_now / comex_ref, inr_now / inr_ref
    fair = settlement * r_c * r_i
    comex_part = settlement * (r_c - 1)
    inr_part = settlement * r_c * (r_i - 1)
    d = duty_rate()["pct"] if duty_pct is None else duty_pct
    landed_ref = landed_inr_per_10g(comex_ref, inr_ref)
    duty_paid_ref = landed_ref * (1 + d / 100)
    return {
        "fair_open": round(fair, 0),
        "gap": round(fair - settlement, 0),
        "gap_pct": round((fair / settlement - 1) * 100, 2),
        "comex_part": round(comex_part, 0),
        "inr_part": round(inr_part, 0),
        "rs_per_comex_dollar": round(settlement / comex_ref, 2),       # ≈ "356 × ΔCOMEX / 10"
        "rs_per_inr_rupee": round(settlement / inr_ref, 0),            # ≈ "1,521 × ΔINR"
        "landed": round(landed_ref, 0),                                # ex-duty, at the MCX-close references
        "duty_pct": d,
        "duty_paid_landed": round(duty_paid_ref, 0),
        "basis_pct": round((settlement / duty_paid_ref - 1) * 100, 2),  # MCX settlement vs duty-paid landed (M8)
        "implied_premium_pct": round((settlement / landed_ref - 1) * 100, 2),   # deprecated: duty + carry + premium
    }


def verdict(fair: float | None, mcx_price: float | None, threshold: float, now_ist: datetime,
            open_at: dtime | None = None, trading_day: bool | None = None) -> dict[str, Any]:
    """`open_at`/`trading_day` come from the MCX calendar (09:00 normally; 17:00 on a morning-closure day; no open on a
    full holiday); the defaults keep the old weekday-09:00 rule. The badge is `heuristic` (PLAN §f): the ₹300 limit is
    a house rule, and its measured miss travels with it in `/api/gold/fair.accuracy`."""
    if fair is None:
        return {"state": "NO_MODEL", "title": "Model unavailable", "badge": "heuristic",
                "detail": "COMEX, the rupee or the MCX baseline is missing: see the data notes below."}
    if trading_day is None:
        trading_day = now_ist.weekday() < 5
    opened = trading_day and now_ist.time() >= (open_at or dtime(9, 0))
    out = _verdict_body(fair, mcx_price, threshold, opened)
    out["badge"] = "heuristic"
    return out


def _verdict_body(fair: float, mcx_price: float | None, threshold: float, opened: bool) -> dict[str, Any]:
    if mcx_price is None:
        if opened:
            return {"state": "NEED_PRICE", "title": "Enter the MCX price",
                    "detail": f"MCX is open. Enter the current GOLD price (or connect ICICI) to compare with fair ₹{fair:,.0f}."}
        return {"state": "AWAITING_OPEN", "title": "Waiting for the open",
                "detail": f"House rule (heuristic, unproven — see the accuracy log): an open within ₹{threshold:,.0f} of ₹{fair:,.0f} is 'OK', beyond it 'WAIT'."}
    diff = mcx_price - fair
    if abs(diff) <= threshold:
        return {"state": "OK", "title": "OK to trade the open", "diff": round(diff, 0),
                "detail": (f"MCX ₹{mcx_price:,.0f} is ₹{abs(diff):,.0f} {'above' if diff > 0 else 'below'} fair: "
                           "the overnight move is priced in.")}
    return {"state": "WAIT", "title": "Don't chase — wait", "diff": round(diff, 0),
            "detail": (f"MCX ₹{mcx_price:,.0f} is ₹{abs(diff):,.0f} {'above' if diff > 0 else 'below'} fair "
                       f"(limit ₹{threshold:,.0f}). Wait 15–30 minutes for the rupee's 09:00 open to settle, then recompute.")}


# ── data ────────────────────────────────────────────────────────────────────────

def _master_dir() -> Path:
    base = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parents[3] / "data"))
    return base / "reference" / "icici_security_master"


def _load_mcx_master() -> tuple[str, date]:
    """MCXScripMaster.txt text and the date ICICI published it (the zip entry's date, which drives the session label).

    Re-checked whenever the copy is not today's — but with a CONDITIONAL GET (`If-Modified-Since` = the
    `Last-Modified` ICICI sent with the copy on disk): all weekend and before ICICI's ≈07:00 publish the answer is a
    304 of a few bytes instead of the 3 MB zip (SOURCES.md F1 trap; desktop review C-PERF-01 measured 1.5 s per
    expiry). The publish-date logic is unchanged: it comes from the zip entry, never from the file's download time."""
    folder = _master_dir()
    path, stamp, lastmod = folder / "MCXScripMaster.txt", folder / "MCXScripMaster.date", folder / "MCXScripMaster.lastmod"
    today = datetime.now(IST).date()
    try:
        published = date.fromisoformat(stamp.read_text().strip()) if stamp.exists() else None
    except ValueError:
        published = None
    if published != today or not path.exists():
        headers = dict(_UA)
        if path.exists() and lastmod.exists():
            since = lastmod.read_text().strip()
            if since:
                headers["If-Modified-Since"] = since
        try:
            r = httpx.get(SECURITY_MASTER_URL, timeout=httpx.Timeout(10.0, read=90.0), headers=headers)
            if r.status_code == 304:             # ICICI has not published a new file: keep the copy and its date
                pass
            else:
                r.raise_for_status()
                z = zipfile.ZipFile(io.BytesIO(r.content))
                info = z.getinfo("MCXScripMaster.txt")
                folder.mkdir(parents=True, exist_ok=True)
                path.write_bytes(z.read(info))
                published = date(*info.date_time[:3])
                stamp.write_text(published.isoformat())
                lm = r.headers.get("Last-Modified", "")
                if lm:
                    lastmod.write_text(lm)
                elif lastmod.exists():
                    lastmod.unlink()
        except Exception:  # noqa: BLE001 — keep the last good copy
            if not path.exists():
                raise
    return path.read_text(encoding="utf-8", errors="replace"), published or today


# The parsed-once MCX master is shared by the gold desk, capture-open and /api/mcx/* (desktop review C-PERF-01:
# /api/mcx/specs took 1.5 s whenever the 10-min entry had expired, because _load_mcx_master re-downloads the
# ~3 MB zip whenever ICICI's copy is not today's: every weekend, and on weekdays until ICICI publishes about
# 07:00). The bound is UNCHANGED: no caller gets a master older than MASTER_MAX_AGE_S (the old 600 s). Inside it,
# a master older than MASTER_REFRESH_AFTER_S is returned at once and re-read in a background thread; past it the
# caller loads it, and concurrent callers wait for one load instead of each downloading (single flight).
MASTER_KEY = "mcx_master"
MASTER_REFRESH_AFTER_S = 300.0
MASTER_MAX_AGE_S = 600.0
_master_load = threading.Lock()          # held while one load runs (foreground or background)


def _master_if_cached() -> tuple[str, date] | None:
    """Non-blocking (safe on the event loop): the cached master while younger than MASTER_MAX_AGE_S, starting a
    background re-read once it is older than MASTER_REFRESH_AFTER_S; None when the caller must load it."""
    hit = _cache.get(MASTER_KEY)
    if hit is None:
        return None
    age = time.monotonic() - hit[0]
    if age >= MASTER_MAX_AGE_S:
        return None
    if age >= MASTER_REFRESH_AFTER_S and _master_load.acquire(blocking=False):
        def _work() -> None:
            try:
                with contextlib.suppress(Exception):     # keep serving the cached copy; the next caller retries
                    _store(MASTER_KEY, _load_mcx_master())
            finally:
                _master_load.release()
        try:
            threading.Thread(target=_work, name="gold-master-refresh", daemon=True).start()
        except RuntimeError:                       # interpreter shutting down: no thread, nothing to release later
            _master_load.release()
    return hit[1]


def mcx_master() -> tuple[str, date]:
    """Blocking: the ICICI MCX security master (see above). Raises when it cannot be loaded and none is cached."""
    master = _master_if_cached()
    if master is not None:
        return master
    with _master_load:
        hit = _cache.get(MASTER_KEY)                  # loaded by the call we waited for?
        if hit is not None and time.monotonic() - hit[0] < MASTER_REFRESH_AFTER_S:
            return hit[1]
        return _store(MASTER_KEY, _load_mcx_master())


async def _yahoo_bars(client: httpx.AsyncClient, symbol: str, rng: str = "5d", interval: str = "5m") -> dict[str, Any]:
    r = await client.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                         params={"range": rng, "interval": interval, "includePrePost": "true"})
    res = (r.json().get("chart") or {}).get("result") if r.status_code == 200 else None
    if not res:
        return {"symbol": symbol, "bars": [], "price": None, "time": None}
    res = res[0]
    closes = (res.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
    bars = [(datetime.fromtimestamp(t, tz=timezone.utc).astimezone(IST), float(c))
            for t, c in zip(res.get("timestamp") or [], closes) if c is not None]
    meta = res.get("meta", {})
    price = meta.get("regularMarketPrice") or (bars[-1][1] if bars else None)
    t = meta.get("regularMarketTime")
    return {"symbol": symbol, "bars": bars, "price": float(price) if price else None,
            "time": datetime.fromtimestamp(t, tz=timezone.utc).astimezone(IST) if t else (bars[-1][0] if bars else None)}


def _env_seconds(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.environ.get(name, "").strip() or default))
    except ValueError:
        return default


# Yahoo series cache (desktop review C2-performance-04, then C-PERF-02). The desk used to start six uncached
# Yahoo chart requests on every call (0.5-0.9 s per call), and CMDT re-polls it every 60 s per window while BRF
# calls it too. Each series is fresh for YAHOO_TTL_S (env GOLD_PREOPEN_YAHOO_TTL_S, default 30 s; 0 turns the
# cache off) and concurrent callers share one in-flight fetch per series. C-PERF-02: a 30 s TTL under a 60 s UI
# refresh meant almost every refresh missed and waited 0.5-3.6 s on Yahoo. Now stale-while-revalidate: a series
# older than YAHOO_TTL_S but younger than YAHOO_MAX_AGE_S (env GOLD_PREOPEN_YAHOO_MAX_AGE_S, default 120 s, i.e.
# two UI refreshes; never below the TTL) is served at once and refreshed in the background, so after the first
# call the desk does not wait on Yahoo while it is in use; a series is never served older than YAHOO_MAX_AGE_S.
# The 08:45 accuracy snapshot (POST /gold-preopen/snapshot) keeps the old rule (nothing older than YAHOO_TTL_S):
# it is a recorded prediction. Only usable results (bars or a price) are kept: a failed or empty answer is
# fetched again by the next call, as before. The computation is unchanged; the series' as_of fields in the body
# say how old the Yahoo prices are, and X-Cache-Age (header) says how old the oldest cached series is.
YAHOO_TTL_S = _env_seconds("GOLD_PREOPEN_YAHOO_TTL_S", 30.0)
YAHOO_MAX_AGE_S = _env_seconds("GOLD_PREOPEN_YAHOO_MAX_AGE_S", 120.0)
YAHOO_FETCH_DEADLINE_S = 10.0         # same per-source deadline the endpoint applies (asyncio.wait_for 10)
_yahoo_inflight: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Task[dict[str, Any]]]] = {}
# Set by the accuracy snapshot: serve nothing older than YAHOO_TTL_S (no stale-while-revalidate).
_FRESH_ONLY: contextvars.ContextVar[bool] = contextvars.ContextVar("gold_yahoo_fresh_only", default=False)
# Collects (age, state) of each series one desk call used, for the X-Cache headers (None = not collecting).
_SERVED: contextvars.ContextVar[list[Served[None]] | None] = contextvars.ContextVar("gold_yahoo_served", default=None)


def _note_served(age_s: float, state: str) -> None:
    served = _SERVED.get()
    if served is not None:
        served.append(Served(None, age_s, state))


def _usable(series: Any) -> bool:
    return isinstance(series, dict) and (bool(series.get("bars")) or series.get("price") is not None)


async def _fetch_yahoo_series(key: str, symbol: str, rng: str, interval: str) -> dict[str, Any]:
    """One Yahoo chart fetch on its own client (a shared fetch must not depend on the first caller's client,
    which closes when that caller times out), stored in the cache when usable."""
    async def _get() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_UA, follow_redirects=True) as client:
            return await _yahoo_bars(client, symbol, rng, interval)
    result = await asyncio.wait_for(_get(), YAHOO_FETCH_DEADLINE_S)
    if YAHOO_TTL_S > 0 and _usable(result):
        _store(key, result)
    return result


def _retrieve(task: asyncio.Task[Any]) -> None:
    """Mark a shared fetch's exception as retrieved (all its callers may have timed out already)."""
    if not task.cancelled():
        task.exception()


def _forget_inflight(key: str, task: asyncio.Task[Any]) -> None:
    entry = _yahoo_inflight.get(key)
    if entry is not None and entry[1] is task:
        del _yahoo_inflight[key]


def _yahoo_fetch_task(key: str, symbol: str, rng: str, interval: str) -> asyncio.Task[dict[str, Any]]:
    """The in-flight fetch of one series on this loop, started if there is none (single flight). The task is
    kept in _yahoo_inflight until it ends, which also keeps a background refresh alive."""
    loop = asyncio.get_running_loop()
    entry = _yahoo_inflight.get(key)
    if entry is not None and entry[0] is loop and not entry[1].done():
        return entry[1]
    task = loop.create_task(_fetch_yahoo_series(key, symbol, rng, interval), name=f"gold-yahoo:{symbol}")
    task.add_done_callback(_retrieve)
    task.add_done_callback(functools.partial(_forget_inflight, key))
    _yahoo_inflight[key] = (loop, task)
    return task


async def _yahoo_bars_cached(symbol: str, rng: str = "5d", interval: str = "5m") -> dict[str, Any]:
    """``_yahoo_bars`` with the TTL + stale-while-revalidate cache and single-flight fetch described above."""
    key = f"yahoo:{symbol}:{rng}:{interval}"
    if YAHOO_TTL_S > 0:
        hit = _cache.get(key)
        if hit is not None:
            age = max(0.0, time.monotonic() - hit[0])
            if age < YAHOO_TTL_S:
                _note_served(age, HIT)
                return hit[1]
            if age < max(YAHOO_MAX_AGE_S, YAHOO_TTL_S) and not _FRESH_ONLY.get():
                _yahoo_fetch_task(key, symbol, rng, interval)          # background refresh; nobody waits on it
                _note_served(age, STALE)
                return hit[1]
    task = _yahoo_fetch_task(key, symbol, rng, interval)
    # shield: a caller's own deadline cancels its wait, not the fetch other callers share
    result = await asyncio.shield(task)
    _note_served(0.0, MISS)
    return result


# Headlines (Google News RSS; also BRF's /api/market/headlines) and the FRED real yield (desktop review C-PERF-02,
# the desk's other per-refresh waits). The bounds are UNCHANGED: a headline list is never served older than
# NEWS_MAX_AGE_S (the old 5-min cache), a FRED series never older than FRED_MAX_AGE_S (the old 6 h). Inside the
# bound, past its refresh point, the cached copy is returned at once and re-read in the background (single
# flight per key, on its own client), so a 60 s CMDT/BRF poller no longer waits on Google News every 5 minutes.
# A failed background read keeps the old copy until the bound, then the next caller reads it, as before.
NEWS_REFRESH_AFTER_S = 150.0
NEWS_MAX_AGE_S = 300.0
FRED_REFRESH_AFTER_S = 3 * 3600.0
FRED_MAX_AGE_S = 6 * 3600.0
BACKGROUND_DEADLINE_S = 20.0
_bg_inflight: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Task[Any]]] = {}


def _forget_background(key: str, task: asyncio.Task[Any]) -> None:
    entry = _bg_inflight.get(key)
    if entry is not None and entry[1] is task:
        del _bg_inflight[key]


def _swr_hit(key: str, refresh_after: float, max_age: float, refresh: Callable[[], Awaitable[Any]]) -> Any | None:
    """The cached value of ``key`` while younger than ``max_age`` (None: the caller reads it itself). Past
    ``refresh_after`` one background ``refresh()`` is started per key and loop (bounded by BACKGROUND_DEADLINE_S)."""
    hit = _cache.get(key)
    if hit is None:
        return None
    age = time.monotonic() - hit[0]
    if age >= max_age:
        return None
    if age >= refresh_after:
        loop = asyncio.get_running_loop()
        entry = _bg_inflight.get(key)
        if entry is None or entry[0] is not loop or entry[1].done():
            task = loop.create_task(asyncio.wait_for(refresh(), BACKGROUND_DEADLINE_S), name=f"gold-refresh:{key}")
            task.add_done_callback(_retrieve)
            task.add_done_callback(functools.partial(_forget_background, key))
            _bg_inflight[key] = (loop, task)
    return hit[1]


async def _fred_last(client: httpx.AsyncClient, series: str) -> list[tuple[str, float]]:
    """Last two observations. Daily series: cached 6 h (re-read in the background after 3 h, see above); only the
    last few weeks are requested (the full CSV goes back decades and is slow)."""
    hit = _swr_hit(f"fred:{series}", FRED_REFRESH_AFTER_S, FRED_MAX_AGE_S, lambda: _fred_fetch(series))
    if hit is not None:
        return hit
    return await _fred_fetch(series)


async def _fred_fetch(series: str) -> list[tuple[str, float]]:
    start = (datetime.now(IST).date() - timedelta(days=30)).isoformat()
    # FRED stalls requests with a browser-like User-Agent (20 s+); a plain client gets 0.3 s.
    async with httpx.AsyncClient(timeout=_TIMEOUT) as plain:
        r = await plain.get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": series, "cosd": start})
    rows = []
    for line in r.text.strip().splitlines()[1:]:
        d, _, v = line.partition(",")
        try:
            rows.append((d, float(v)))
        except ValueError:
            continue
    return _store(f"fred:{series}", rows[-2:]) if rows else rows


async def _headlines(client: httpx.AsyncClient, label: str, query: str, must: str,
                     hours: int = 24) -> list[dict[str, Any]]:
    """Google News headlines for one topic, cached 5 min (re-read in the background after 150 s, see above)."""
    hit = _swr_hit(f"news:{label}", NEWS_REFRESH_AFTER_S, NEWS_MAX_AGE_S,
                   lambda: _headlines_fetch(None, label, query, must, hours))
    if hit is not None:
        return hit
    return await _headlines_fetch(client, label, query, must, hours)


async def _headlines_fetch(client: httpx.AsyncClient | None, label: str, query: str, must: str,
                           hours: int) -> list[dict[str, Any]]:
    import xml.etree.ElementTree as ET
    if client is None:                       # a background refresh: the caller's client may be closed by now
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_UA, follow_redirects=True) as own:
            return await _headlines_fetch(own, label, query, must, hours)
    try:
        r = await client.get("https://news.google.com/rss/search",
                             params={"q": f"{query} when:1d", "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
        root = ET.fromstring(r.content)
    except (httpx.HTTPError, ET.ParseError):
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out: list[dict[str, Any]] = []
    for it in root.findall("./channel/item"):
        title, publisher = it.findtext("title") or "", it.findtext("source") or ""
        if publisher and title.endswith(f" - {publisher}"):
            title = title[: -len(publisher) - 3]
        try:
            when = parsedate_to_datetime(it.findtext("pubDate") or "")
        except (TypeError, ValueError):
            continue
        if when < cutoff or not re.search(must, title, re.I) or _EVERGREEN.search(title):
            continue
        out.append({"topic": label, "title": title, "publisher": publisher, "link": it.findtext("link"),
                    "published_at": when.astimezone(timezone.utc).isoformat()})
    out.sort(key=lambda x: x["published_at"], reverse=True)
    return _store(f"news:{label}", out[:4])


def _breeze_mcx_quote(expiry: date) -> dict[str, Any] | None:
    """Live MCX GOLD quote when an ICICI Breeze session is connected (else None). Breeze answers MCX futures quotes
    with an error (12 Oct 2026); a failed attempt is remembered for 10 min so the desk doesn't pay for it each time."""
    if _cached("mcx_quote_broken", 600):
        return None
    try:
        from routers.positions import _get_breeze_client
        breeze, err = _get_breeze_client()
        if err or breeze is None:
            return None
        q = breeze.get_quotes(stock_code="GOLD", exchange_code="MCX", product_type="futures",
                              expiry_date=f"{expiry.isoformat()}T06:00:00.000Z", right="others", strike_price="0")
        rows = q.get("Success") if isinstance(q, dict) and q.get("Status") == 200 else None
        if not rows:
            _store("mcx_quote_broken", True)
            return None
        row = rows[0]
        num = lambda k: float(row[k]) if row.get(k) not in (None, "", "0", 0) else None  # noqa: E731
        return {"ltp": num("ltp"), "open": num("open"), "previous_close": num("previous_close"),
                "time": row.get("ltt"), "source": "ICICI Breeze"}
    except Exception:  # noqa: BLE001 — the broker is optional here
        _store("mcx_quote_broken", True)
        return None


def _breeze_mcx_open(expiry: date, day: date) -> dict[str, Any] | None:
    """Today's MCX GOLD open (first 1-minute bar) and latest price (last bar close) from Breeze historical v2.
    Breeze get_quotes answers MCX futures with HTTP 500 "Object reference not set…" (checked 12 Oct 2026); the
    historical API works. Times are IST wall-clock (Breeze ignores the Z). A day of 1-minute bars takes Breeze
    10–15 s, so the result is cached for 60 s."""
    key = f"mcx_bars:{expiry}:{day}"
    hit = _cached(key, 60)
    if hit is not None:
        return hit or None
    try:
        from routers.positions import _get_breeze_client
        breeze, err = _get_breeze_client()
        if err or breeze is None:
            return None
        h = breeze.get_historical_data_v2(interval="1minute", from_date=f"{day.isoformat()}T09:00:00.000Z",
                                          to_date=f"{day.isoformat()}T23:59:00.000Z", stock_code="GOLD", exchange_code="MCX",
                                          product_type="futures", expiry_date=f"{expiry.isoformat()}T06:00:00.000Z",
                                          right="others", strike_price="0")
        bars = h.get("Success") if isinstance(h, dict) and h.get("Status") == 200 else None
        bars = sorted((b for b in bars or [] if str(b.get("datetime", "")).startswith(day.isoformat())),
                      key=lambda b: b["datetime"])
        if not bars or not bars[0].get("open"):
            _store(key, {})
            return None
        return _store(key, {"open": float(bars[0]["open"]), "ltp": float(bars[-1]["close"]), "time": bars[-1]["datetime"],
                            "source": "ICICI Breeze (1-min bars)"})
    except Exception:  # noqa: BLE001 — the broker is optional here
        return None


TREASURY_REAL_URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
                     "daily-treasury-rates.csv/{year}/all?type=daily_treasury_real_yield_curve&field_tdr_date_value={year}")


def _treasury_real_10y() -> list[tuple[str, float]]:
    """US Treasury 10-year real yield (published a day before FRED's DFII10, but the site takes
    ~20 s): fetched in the background, cached 6 h. Returns the last two (date, value) rows."""
    hit = _cached("treasury_real", 6 * 3600)
    if hit is not None:
        return hit
    year = datetime.now(IST).year
    r = httpx.get(TREASURY_REAL_URL.format(year=year), timeout=httpx.Timeout(10.0, read=60.0))
    rows = []
    for rec in csv.DictReader(io.StringIO(r.text)):
        try:
            rows.append((datetime.strptime(rec["Date"], "%m/%d/%Y").date().isoformat(), float(rec["10 YR"])))
        except (KeyError, ValueError):
            continue
    rows.sort()
    return _store("treasury_real", rows[-2:]) if rows else rows


_treasury_inflight = False


def _refresh_treasury_in_background() -> None:
    global _treasury_inflight
    if _treasury_inflight or _cached("treasury_real", 6 * 3600) is not None:
        return
    import threading
    _treasury_inflight = True

    def _work() -> None:
        global _treasury_inflight
        try:
            _treasury_real_10y()
        except Exception:  # noqa: BLE001 — FRED remains the fallback
            pass
        finally:
            _treasury_inflight = False
    threading.Thread(target=_work, name="treasury-real-yield", daemon=True).start()


def warm() -> None:
    """Start-up: fetch today's ICICI security master in the background (≈3 MB)."""
    import threading

    def _work() -> None:
        try:
            mcx_master()
        except Exception:  # noqa: BLE001 — the endpoint retries and reports
            pass
    threading.Thread(target=_work, name="gold-master-warm", daemon=True).start()
    _refresh_treasury_in_background()


WARM_SERIES_COUNT = 2 + len(CONTEXT_SERIES)          # COMEX gold + USD/INR + the context series: what warm_series asks


async def warm_series() -> int:
    """Start-up (routers/_cache_warm.py): fetch the desk's six Yahoo series into the cache, nothing else (no broker,
    news or FRED call). Returns how many came back usable (of WARM_SERIES_COUNT)."""
    now = datetime.now(IST)
    master = _master_if_cached()
    if master is None:
        try:
            master = await asyncio.to_thread(mcx_master)
        except Exception:  # noqa: BLE001 — without the master the desk falls back to December, so does this
            master = None
    contract = pick_contract(parse_mcx_gold(master[0]), now.date()) if master else None
    expiry = contract["expiry"] if contract else date(now.year, 12, 4)
    symbols = [comex_symbol(expiry), "INR=X", *(sym for _, _, sym, _, _ in CONTEXT_SERIES)]
    results = await asyncio.gather(*(asyncio.wait_for(_yahoo_bars_cached(sym), 10) for sym in symbols),
                                   return_exceptions=True)
    return sum(1 for r in results if _usable(r))


# ── prefs-driven triggers (PLAN §b: eurusd_trigger and the headline topics live in prefs gold.triggers.v1) ──────

def prefs_triggers() -> dict[str, Any]:
    """{eurusd_trigger: float | None, topics: list[str] | None} from the prefs store (routers/prefs.py), or empty values
    when the store or the key is absent / malformed. Blocking (SQLite): call off the loop."""
    out: dict[str, Any] = {"eurusd_trigger": None, "topics": None}
    try:
        from routers import prefs as ui_prefs
        rec = ui_prefs.get_store().all().get(PREFS_TRIGGERS_KEY)
        if not rec or rec.get("deleted") or not rec.get("value"):
            return out
        val = json.loads(rec["value"])
    except Exception:  # noqa: BLE001 — prefs are a convenience, never a dependency
        return out
    if isinstance(val, dict):
        try:
            trig = val.get("eurusd_trigger")
            out["eurusd_trigger"] = float(trig) if trig is not None and float(trig) > 0 else None
        except (TypeError, ValueError):
            pass
        topics = val.get("topics")
        if isinstance(topics, list) and topics:
            known = {label for label, _, _ in HEADLINE_TOPICS}
            out["topics"] = [t for t in topics if isinstance(t, str) and t in known] or None
    return out


def headline_topics(selected: list[str] | None) -> list[tuple[str, str, str]]:
    """The HEADLINE_TOPICS rows to fetch: all of them, or only the labels in `selected`."""
    if not selected:
        return list(HEADLINE_TOPICS)
    return [row for row in HEADLINE_TOPICS if row[0] in selected]


# ── endpoint ────────────────────────────────────────────────────────────────────

@router.get("/gold-preopen")
async def gold_preopen(
    baseline: float | None = Query(None, gt=0, description="Override the MCX baseline (your broker's close)"),
    mcx_price: float | None = Query(None, gt=0, description="Current / indicative MCX GOLD price"),
    threshold: float = Query(300, gt=0, le=5000),
    eurusd_trigger: float | None = Query(None, gt=0, description="EUR/USD trigger; default from prefs, else 1.1161"),
    response: Response = None,  # type: ignore[assignment]  # injected by FastAPI; None when called directly
) -> dict[str, Any]:
    served: list[Served[None]] = []
    token = _SERVED.set(served)
    try:
        return await _gold_preopen(baseline, mcx_price, threshold, eurusd_trigger)
    finally:
        _SERVED.reset(token)
        cache_headers(response, merge_served(served))


async def _gold_preopen(baseline: float | None, mcx_price: float | None, threshold: float,
                        eurusd_trigger: float | None = None) -> dict[str, Any]:
    now = datetime.now(IST)
    notes: list[str] = []
    triggers = await asyncio.to_thread(prefs_triggers)
    if eurusd_trigger is None:
        eurusd_trigger = triggers["eurusd_trigger"] or DEFAULT_EURUSD_TRIGGER
    topics = headline_topics(triggers["topics"])
    today_mcx = mcx_day(now.date())
    open_at = (datetime.fromisoformat(today_mcx["opens_at"]).time() if today_mcx["opens_at"] else None)

    # 1. MCX contract + settlement (blocking file work off the event loop, cached 10 min)
    master = _master_if_cached()
    if master is None:
        try:
            master = await asyncio.to_thread(mcx_master)
        except Exception as exc:  # noqa: BLE001
            master = None
            notes.append(f"ICICI security master unavailable ({str(exc)[:80]}): enter the MCX close manually.")
    contract = None
    if master:
        contracts = parse_mcx_gold(master[0])
        contract = pick_contract(contracts, now.date())
    settle_day = previous_session(master[1]) if master else previous_session(now.date())
    close_at = mcx_close_time(settle_day)
    last_session = previous_session(now.date() + timedelta(days=1)) if now.hour >= 23 else previous_session(now.date())
    if settle_day < last_session and not baseline:
        notes.append(f"Baseline is the {settle_day:%a %d %b} settlement: ICICI publishes the file with the "
                     f"{last_session:%a %d %b} "
                     f"settlement at about 07:30 IST on the next trading day. Until then the expected gap also includes "
                     f"{last_session:%a}'s move; the fair open itself stays valid (it scales the older settlement by every "
                     f"COMEX and rupee move since).")
    broker = await asyncio.to_thread(_breeze_mcx_quote, contract["expiry"]) if contract else None
    if contract and not broker and today_mcx["trading"] and open_at is not None and now.time() >= open_at:
        broker = await asyncio.to_thread(_breeze_mcx_open, contract["expiry"], now.date())

    base_value, base_source = None, None
    if baseline:
        base_value, base_source = baseline, "your entry"
    elif broker and broker.get("previous_close"):
        base_value, base_source = broker["previous_close"], "ICICI Breeze previous close"
    elif contract:
        base_value, base_source = contract["settlement"], f"MCX settlement {settle_day:%d %b} (price-band midpoint)"
    live_price = mcx_price or (broker or {}).get("ltp")
    price_source = "your entry" if mcx_price else ("ICICI Breeze" if live_price else None)

    # 2. market data, concurrently
    expiry = contract["expiry"] if contract else date(now.year, 12, 4)
    comex_sym = comex_symbol(expiry)
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_UA, follow_redirects=True) as client:
        tasks: list[Any] = [_yahoo_bars_cached(comex_sym), _yahoo_bars_cached("INR=X")]
        tasks += [_yahoo_bars_cached(sym) for _, _, sym, _, _ in CONTEXT_SERIES]
        tasks += [_fred_last(client, "DFII10")]
        tasks += [_headlines(client, label, q, must) for label, q, must in topics]
        # every source gets its own deadline: one slow site must not stall the desk
        results: list[Any] = list(await asyncio.gather(*(asyncio.wait_for(x, 10) for x in tasks),
                                                     return_exceptions=True))
    comex, inr = results[0], results[1]
    ctx_raw = results[2:2 + len(CONTEXT_SERIES)]
    tips = results[2 + len(CONTEXT_SERIES)]
    news_lists = results[3 + len(CONTEXT_SERIES):]

    def ok(x: Any) -> bool:
        return isinstance(x, dict) and x.get("price") is not None

    model: dict[str, Any] = {}
    comex_ref = inr_ref = None
    if ok(comex) and ok(inr):
        comex_ref, comex_how = reference_price(comex["bars"], close_at)
        inr_ref, inr_how = reference_price(inr["bars"], close_at)
        model["comex"] = {"symbol": comex_sym, "now": comex["price"], "ref": comex_ref, "ref_how": comex_how,
                          "as_of": comex["time"].isoformat() if comex["time"] else None}
        model["inr"] = {"symbol": "INR=X", "now": inr["price"], "ref": inr_ref, "ref_how": inr_how,
                        "as_of": inr["time"].isoformat() if inr["time"] else None}
        for name, leg in (("COMEX", comex), ("USD/INR", inr)):
            if leg["time"] and (now - leg["time"]).total_seconds() > 3 * 3600:
                notes.append(f"{name} last updated {leg['time']:%d %b %H:%M} IST: the market may be closed.")
    else:
        notes.append("COMEX or USD/INR prices could not be fetched from Yahoo.")
    fair = None
    if base_value and comex_ref and inr_ref:
        model.update(fair_open(base_value, comex_ref, model["comex"]["now"], inr_ref, model["inr"]["now"]))
        fair = model["fair_open"]
        model["lot_pnl_per_rupee"] = MCX_GOLD_LOT_KG * 100
        model["threshold_in_comex_dollars"] = round(threshold / model["rs_per_comex_dollar"], 1)

    context = []
    for (key, label, sym, unit, good_dir), raw in zip(CONTEXT_SERIES, ctx_raw):
        if not ok(raw):
            context.append({"key": key, "label": label, "symbol": sym, "value": None})
            continue
        ref, _ = reference_price(raw["bars"], close_at)
        chg = raw["price"] - ref if ref is not None else None
        signal = None if not chg else ("supportive" if chg * good_dir > 0 else "headwind")
        row = {"key": key, "label": label, "symbol": sym, "unit": unit, "value": round(raw["price"], 4),
               "at_close": round(ref, 4) if ref is not None else None, "change": round(chg, 4) if chg is not None else None,
               "signal": signal}
        if key == "eurusd":
            row["trigger"] = eurusd_trigger
            row["trigger_state"] = "above" if raw["price"] > eurusd_trigger else "below"
        context.append(row)
    treasury = _cached("treasury_real", 6 * 3600)
    _refresh_treasury_in_background()
    tips_source = "FRED DFII10"
    if treasury and (not isinstance(tips, list) or not tips or treasury[-1][0] > tips[-1][0]):
        tips, tips_source = treasury, "US Treasury real yield curve"
    if isinstance(tips, list) and tips:
        (d_last, v_last) = tips[-1]
        chg = v_last - tips[0][1] if len(tips) > 1 else None
        context.append({"key": "tips10", "label": "10-year real yield (TIPS)", "symbol": tips_source, "unit": "%",
                        "value": v_last, "at_close": tips[0][1] if len(tips) > 1 else None,
                        "change": round(chg, 3) if chg is not None else None,
                        "signal": None if not chg else ("supportive" if chg < 0 else "headwind"),
                        "note": f"daily close {d_last}: no free intraday feed"})

    pooled: list[dict[str, Any]] = [h for lst in news_lists if isinstance(lst, list) for h in lst]
    headlines: list[dict[str, Any]] = []
    seen: set[str] = set()
    for h in sorted(pooled, key=lambda x: str(x["published_at"]), reverse=True):
        if h["title"] not in seen:
            seen.add(h["title"])
            headlines.append(h)
    headlines = headlines[:18]
    risk_words = re.compile(r"\b(attack|strike|missile|war|sanction|closure|blockade|margin|halt|emergency|default)\b", re.I)
    event_risk = sum(1 for h in headlines if risk_words.search(h["title"]))
    duty = duty_rate()
    if today_mcx["note"]:
        notes.append(today_mcx["note"] + ".")

    return {
        "as_of": now.isoformat(),
        "contract": {"name": f"GOLD {expiry:%b-%y}".upper(), "expiry": expiry.isoformat(), "comex": comex_sym,
                     "band_low": contract["band_low"] if contract else None,
                     "band_high": contract["band_high"] if contract else None,
                     "band_pct": contract["band_pct"] if contract else None,
                     "open_interest_lots": contract["open_interest"] if contract else None},
        "baseline": {"value": base_value, "source": base_source, "session": settle_day.isoformat(),
                     "session_label": session_label(settle_day),           # "Thu 22 Oct settlement", never the file date
                     "stale": settle_day < last_session and not baseline,  # ICICI's file still carries an older session
                     "close_time": close_at.isoformat(),
                     "settlement_from_band": contract["settlement"] if contract else None,
                     "master_published": master[1].isoformat() if master else None},
        "mcx_price": {"value": live_price, "source": price_source, "broker": broker},
        "model": model,
        "duty": duty,
        "threshold": threshold,
        "verdict": verdict(fair, live_price, threshold, now, open_at=open_at, trading_day=today_mcx["trading"]),
        "holiday": None if today_mcx["closure"] is None else {"closure": today_mcx["closure"], "name": today_mcx["name"],
                                                               "opens_at": today_mcx["opens_at"], "note": today_mcx["note"]},
        # the count only (PLAN disagreement 14): a keyword tally with the heuristic badge, no sizing advice
        "event_risk": {"flagged_headlines": event_risk, "badge": "heuristic", "advice": None},
        "context": context,
        "headlines": headlines,
        "manual_checks": [{"name": n, "what": w, "url": u} for n, w, u in MANUAL_CHECKS],
        "notes": notes,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Accuracy log: the 08:45 IST prediction vs the actual MCX open, to calibrate the chase limit.
# master-controller calls /snapshot at 08:45 and /capture-open at 09:10 (Mon–Fri). Without an ICICI
# session the actual open can be typed in from the UI. One row per trading day in data/gold_preopen/log.json.
# ══════════════════════════════════════════════════════════════════════════════

MCX_OPEN = (9, 0)
_log_lock = threading.Lock()


def _r(v: Any, d: int) -> float | None:
    return round(float(v), d) if v is not None else None


def _log_path() -> Path:
    env = os.environ.get("GOLD_LOG_PATH", "").strip()
    if env:
        return Path(env)
    for root in (Path(__file__).resolve().parents[3] / "data", Path("/app/data")):
        if root.is_dir():
            return root / "gold_preopen" / "log.json"
    return Path(__file__).resolve().parents[3] / "data" / "gold_preopen" / "log.json"


def _read_log() -> dict[str, dict[str, Any]]:
    p = _log_path()
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except (OSError, ValueError):
        return {}


def _write_log(rows: dict[str, dict[str, Any]]) -> None:
    p = _log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(p)                                   # atomic: a crash never leaves half a file


def _update_day(day: str, **fields: Any) -> dict[str, Any]:
    with _log_lock:
        rows = _read_log()
        row = {**rows.get(day, {"date": day}), **{k: v for k, v in fields.items() if v is not None}}
        if row.get("actual_open") and row.get("fair_open"):
            row["error"] = round(row["actual_open"] - row["fair_open"], 1)
        if row.get("actual_open") and row.get("baseline"):
            row["naive_error"] = round(row["actual_open"] - row["baseline"], 1)
        rows[day] = row
        _write_log(rows)
    _dual_write_log_async(row)
    return row


# ── dual-write to data-service's gold_preopen_log (PLAN §c.3 gold_open_capture: "dual-write with log.json for one
# release"). Best effort, off the request path (daemon thread, 5 s timeout), never under pytest unless a test turns it
# on explicitly (GOLD_LOG_DUAL_WRITE=1): a test must never POST to the live data-service.
DATA_SVC = os.environ.get("DATA_SERVICE_URL", "http://localhost:8001").rstrip("/")
GOLD_LOG_JOB_PATH = "/jobs/gold-log"
_DUAL_WRITE_TIMEOUT = httpx.Timeout(5.0)


def dual_write_enabled() -> bool:
    flag = os.environ.get("GOLD_LOG_DUAL_WRITE", "").strip()
    if flag in ("0", "1"):
        return flag == "1"
    try:
        from shared.http_guard import in_test_mode
        if in_test_mode():
            return False
    except ImportError:
        pass
    return True


def _dual_write_log(row: dict[str, Any]) -> bool:
    """POST one accuracy-log row to data-service; False (and one structured WARNING, values omitted) on any failure."""
    try:
        r = httpx.post(f"{DATA_SVC}{GOLD_LOG_JOB_PATH}", json={"row": row}, timeout=_DUAL_WRITE_TIMEOUT)
        if r.status_code >= 400:
            _log.warning(json.dumps({"event": "gold_log_dual_write_refused", "status": r.status_code, "day": row.get("date")}))
            return False
        return True
    except httpx.HTTPError as exc:
        _log.warning(json.dumps({"event": "gold_log_dual_write_failed", "error": type(exc).__name__, "day": row.get("date")}))
        return False


def _dual_write_log_async(row: dict[str, Any]) -> None:
    if not dual_write_enabled():
        return
    try:
        threading.Thread(target=_dual_write_log, args=(dict(row),), name="gold-log-dual-write", daemon=True).start()
    except RuntimeError:                       # interpreter shutting down
        pass


def stale_baseline(row: dict[str, Any]) -> bool:
    """A row whose baseline session is older than the session before its snapshot day (the 15 Oct case): the file
    ICICI served that morning still carried an older settlement."""
    try:
        session = date.fromisoformat(str(row.get("baseline_session") or ""))
        day = date.fromisoformat(str(row.get("date") or ""))
    except ValueError:
        return bool(row.get("stale_baseline", False))
    return session < previous_session(day)


def snapshot_inputs(d: dict[str, Any], threshold: float) -> str:
    """The audit trail of one 08:45 call as compact JSON (PLAN j.2 #9 needs it to explain the 15 Oct miss)."""
    m = d.get("model") or {}
    inputs = {
        "as_of": d.get("as_of"), "threshold": threshold,
        "contract": d.get("contract", {}).get("name"), "expiry": d.get("contract", {}).get("expiry"),
        "comex_symbol": (m.get("comex") or {}).get("symbol"),
        "comex": {k: (m.get("comex") or {}).get(k) for k in ("ref", "now", "ref_how", "as_of")},
        "inr": {k: (m.get("inr") or {}).get(k) for k in ("ref", "now", "ref_how", "as_of")},
        "baseline": {k: (d.get("baseline") or {}).get(k) for k in ("value", "source", "session", "session_label", "stale",
                                                                    "close_time", "master_published")},
        "duty": d.get("duty"), "notes": d.get("notes"),
        "yahoo_cache": {"ttl_s": YAHOO_TTL_S, "max_age_s": YAHOO_MAX_AGE_S, "fresh_only": True},
    }
    return json.dumps(inputs, default=str, separators=(",", ":"))


def accuracy_stats(rows: list[dict[str, Any]], threshold: float = 300) -> dict[str, Any]:
    """Model error (actual − fair) against the naive guess (open = yesterday's settlement)."""
    done = [r for r in rows if r.get("error") is not None]
    if not done:
        return {"days": 0}
    err = sorted(abs(r["error"]) for r in done)
    naive = [abs(r["naive_error"]) for r in done if r.get("naive_error") is not None]
    mid = len(err) // 2
    return {
        "days": len(done),
        "mean_abs_error": round(sum(err) / len(err), 1),
        "median_abs_error": round(err[mid] if len(err) % 2 else (err[mid - 1] + err[mid]) / 2, 1),
        "bias": round(sum(r["error"] for r in done) / len(done), 1),
        "within_threshold_pct": round(100 * sum(e <= threshold for e in err) / len(err), 1),
        "naive_mean_abs_error": round(sum(naive) / len(naive), 1) if naive else None,
        "p90_abs_error": err[min(len(err) - 1, int(0.9 * len(err)))],
        "threshold": threshold,
    }


def snapshot_gate(now: datetime, force: bool) -> None:
    """Refuse a snapshot on a day MCX never opens (weekend, full holiday) and once today's session has opened —
    17:00 on a morning-closure day such as Dussehra 20 Oct, 09:00 otherwise; `force` overrides the opened rule."""
    today = mcx_day(now.date())
    if not today["trading"]:
        raise HTTPException(status_code=409, detail=f"{today['note'] or 'MCX closed today'}: no pre-open snapshot")
    if today["closure"] == "morning" and not force:      # PLAN c.3: the 08:45 call skips morning closures (no 09:00 open to call)
        raise HTTPException(status_code=409,
                            detail=f"{today['note']}: no 09:00 open to predict (force=true for the 17:00 session)")
    open_at = datetime.fromisoformat(today["opens_at"])
    if not force and now >= open_at:
        raise HTTPException(status_code=409, detail=(f"MCX is open (since {open_at:%H:%M}): a snapshot now would use "
                                                     "post-open prices (force=true to override)"))


def capture_gate(now: datetime) -> None:
    """Capture the open only on a trading day and only once today's session has opened (17:00 on a morning closure)."""
    today = mcx_day(now.date())
    if not today["trading"]:
        raise HTTPException(status_code=409, detail=f"{today['note'] or 'MCX closed today'}: no open to capture")
    open_at = datetime.fromisoformat(today["opens_at"])
    if now < open_at:
        raise HTTPException(status_code=409, detail=f"MCX opens at {open_at:%H:%M} today: nothing to capture yet")


@router.post("/gold-preopen/snapshot")
async def gold_snapshot(force: bool = Query(False, description="Record even after the open")) -> dict[str, Any]:
    """Record today's pre-open prediction (scheduled 08:45 IST, Mon–Fri; MCX-holiday aware, PLAN §c.3)."""
    now = datetime.now(IST)
    snapshot_gate(now, force)
    threshold = 300.0
    token = _FRESH_ONLY.set(True)          # the recorded prediction keeps the old freshness rule (no stale series)
    try:
        d = await gold_preopen(baseline=None, mcx_price=None, threshold=threshold, eurusd_trigger=None)
    finally:
        _FRESH_ONLY.reset(token)
    m = d.get("model") or {}
    if not m.get("fair_open"):
        raise HTTPException(status_code=503, detail="No fair value right now: " + "; ".join(d.get("notes") or ["inputs missing"]))
    b = d["baseline"]
    return _update_day(now.date().isoformat(), snapshot_at=now.isoformat(timespec="seconds"),
                       contract=d["contract"]["name"], expiry=d["contract"]["expiry"], comex_symbol=d["contract"]["comex"],
                       baseline=b["value"], baseline_source=b["source"], baseline_session=b["session"],
                       stale_baseline=bool(b.get("stale")), fair_open=round(m["fair_open"], 1),
                       threshold=threshold, duty_pct=(d.get("duty") or {}).get("pct"),
                       comex_ref=_r(m.get("comex", {}).get("ref"), 2), comex_now=_r(m.get("comex", {}).get("now"), 2),
                       inr_ref=_r(m.get("inr", {}).get("ref"), 4), inr_now=_r(m.get("inr", {}).get("now"), 4),
                       event_risk=d["event_risk"]["flagged_headlines"], inputs_json=snapshot_inputs(d, threshold))


@router.post("/gold-preopen/capture-open")
async def gold_capture_open() -> dict[str, Any]:
    """Fill today's actual MCX open from ICICI Breeze (scheduled 09:10 IST; 17:10 on a morning-closure day).
    Needs a live session."""
    now = datetime.now(IST)
    capture_gate(now)
    master = _master_if_cached()
    if master is None:
        master = await asyncio.to_thread(mcx_master)
    contract = pick_contract(parse_mcx_gold(master[0]), now.date())
    if not contract:
        raise HTTPException(status_code=503, detail="No MCX GOLD contract in the security master")
    q = await asyncio.to_thread(_breeze_mcx_quote, contract["expiry"])
    if not q or not q.get("open"):
        q = await asyncio.to_thread(_breeze_mcx_open, contract["expiry"], now.date())
    if not q or not q.get("open"):
        raise HTTPException(status_code=503,
                            detail="ICICI Breeze not connected (or no open print yet): enter the open on GOLD › HEALTH")
    return _update_day(now.date().isoformat(), actual_open=q["open"], actual_source=q.get("source") or "ICICI Breeze",
                       captured_at=now.isoformat(timespec="seconds"))


@router.post("/gold-preopen/actual")
def gold_set_actual(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Manual entry: {"date": "YYYY-MM-DD", "open": 125432} — the MCX GOLD opening price that day."""
    try:
        day = date.fromisoformat(str(payload.get("date") or datetime.now(IST).date().isoformat())).isoformat()
        price = float(payload["open"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Send {date: YYYY-MM-DD, open: price}") from exc
    if not 10_000 < price < 1_000_000:
        raise HTTPException(status_code=422, detail="That does not look like an MCX GOLD price (₹ per 10 g)")
    return _update_day(day, actual_open=round(price, 1), actual_source="manual")


def log_rows(days: int) -> list[dict[str, Any]]:
    """The newest `days` rows, each with `stale_baseline` (rule or stored flag) and `inputs_json` (None before 26 Oct)."""
    rows = sorted(_read_log().values(), key=lambda r: r["date"], reverse=True)[:days]
    return [{**r, "stale_baseline": stale_baseline(r), "inputs_json": r.get("inputs_json")} for r in rows]


@router.get("/gold-preopen/log")
def gold_log(days: int = Query(60, ge=1, le=400), threshold: float = Query(300, gt=0)) -> dict[str, Any]:
    rows = log_rows(days)
    return {"rows": rows, "stats": accuracy_stats(rows, threshold)}

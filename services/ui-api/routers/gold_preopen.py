"""
Gold Pre-Open desk — where should MCX Gold open, and is the opening price worth chasing?

    fair open = MCX settlement × (COMEX now ÷ COMEX at the MCX close) × (USD/INR now ÷ USD/INR at the close)

Inputs, all free and fetched automatically:
  * MCX baseline (wave 1d, 5 Nov 2026): the latest completed session's settlement proxy = the volume-weighted average of
    the last 30 minutes of ICICI Breeze 1-minute bars (MCX's own settlement window; ONE read-only call per contract per
    session, kept all night, through shared/breeze_budget). Without a Breeze session: the midpoint of the ±3 % price band
    in ICICI's public security master (MCXScripMaster.txt) — which is the settlement TWO sessions before the file's publish
    date (the band is the band of the session before it), labelled so, with the COMEX / rupee references taken at that
    session's close. Overridable with the trader's own close; replaced by the broker's previous close when get_quotes works.
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


COMEX_LIQUID_MONTHS = (2, 4, 6, 8, 10, 12)  # GC's active cycle (G, J, M, Q, V, Z); the serial months are thin


def comex_liquid_symbol(mcx_expiry: date) -> tuple[str, bool]:
    """The COMEX month every gold view matches an MCX expiry to: the delivery month itself when it is on GC's liquid cycle,
    else the NEXT liquid month (critic C-BEGINNER-26; 5 Nov review: MCXG priced GOLDTEN NOV-26 off the thin serial GCX26
    while the GOLD page and the ladder said DEC-26). Returns (Yahoo symbol, is_nearest_liquid_substitute). One helper for
    GOLD, CONTRACTS and MCXG (`routers.gold.comex_liquid_symbol` is this function)."""
    exact = comex_symbol(mcx_expiry)
    if mcx_expiry.month in COMEX_LIQUID_MONTHS:
        return exact, False
    y, m = mcx_expiry.year, mcx_expiry.month + 1
    if m > 12:
        y, m = y + 1, 1
    while m not in COMEX_LIQUID_MONTHS:
        m += 1
    return comex_symbol(date(y, m, 1)), True


def mcx_close_time(day: date) -> datetime:
    """MCX evening close: 23:30 IST while New York is on daylight time, else 23:55."""
    noon_ny = datetime(day.year, day.month, day.day, 12, tzinfo=NY)
    hh, mm = (23, 30) if noon_ny.dst() else (23, 55)
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=IST)


def previous_session(publish_day: date) -> date:
    """Trading day whose settlement a security master published on `publish_day` carries (weekends and MCX full
    holidays skipped: the Monday file after a Friday holiday carries Thursday's settlement). A dated special session
    (Muhurat, Sun 8 Nov 2026, 14:20–15:30) IS a session (wave 1e, M-D): previous_session(Mon 9 Nov) = Sun 8 Nov."""
    d = publish_day - timedelta(days=1)
    while specs.trading_window(d) is None:
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
    special = specs.special_session_on(day)
    out: dict[str, Any] = {"date": day.isoformat(), "trading": window is not None,
                           "closure": hol[1] if hol else ("weekend" if day.weekday() >= 5 and not special else None),
                           "name": hol[0] if hol else (special["name"] if special else None),
                           "opens_at": window[0].isoformat(timespec="minutes") if window else None,
                           "closes_at": window[1].isoformat(timespec="minutes") if window else None,
                           "special": special}
    if special and window:
        # a dated special session (Muhurat): trading only inside its short window, no 09:00 open to call (wave 1e, M-D)
        out["note"] = (f"MCX special session: {special['name']} {window[0]:%H:%M}–{window[1]:%H:%M} IST "
                       f"(circular {special.get('circular') or 'pending'})")
    elif hol and hol[1] == "full":
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


# Purity (wave 1d round 2, PM decision D1): the landed price built from COMEX / LBMA ($/oz × USD/INR × g ÷ 31.1034768) is the
# rupee price of FINE gold (1000 parts per 1000). Every MCX basis divides the contract's price, scaled to ₹/10 g, by landed ×
# purity / 1000 — GOLD 995, GOLDM 995, GOLDTEN 999, GOLDPETAL 999, GOLDGUINEA 999. The guinea is 999 like the petal (5 Nov:
# GOLDGUINEA ₹1,12,211 per 8 g = ₹1,40,264 per 10 g ≈ GOLDPETAL 999 ₹1,40,330, far from the ≈ ₹1,28,500 a 916 coin would
# trade at; shared/mcx_specs and CURRICULUM say 999 too). IBJA 999 compares with landed × 0.999, IBJA 995 with landed ×
# 0.995. ONE source for both services: the purity is READ from shared/mcx_specs (data-service's gold/ingest_india does the
# same, with the same fallback literals; test_gold_wave1d pins the two). The 5 Nov review found GOLD (995) divided by a 999
# price, 0.40 pp off.
LANDED_FINENESS = 1000                       # COMEX / LBMA quote FINE gold: the landed price is at 1000
REFERENCE_FINENESS = LANDED_FINENESS         # kept name: the fineness `landed` / `duty_paid_landed` are at
_PURITY_FALLBACK: dict[str, int] = {"GOLD": 995, "GOLDM": 995, "GOLDTEN": 999, "GOLDPETAL": 999, "GOLDGUINEA": 999}


def _spec_purity(family: str) -> int:
    """The delivery purity shared/mcx_specs lists for `family` ('995' → 995), else the fallback literal."""
    spec = specs.CONTRACTS.get(family)
    try:
        return int(str(spec.purity).strip()) if spec is not None else _PURITY_FALLBACK.get(family, 999)
    except ValueError:
        return _PURITY_FALLBACK.get(family, 999)


CONTRACT_FINENESS: dict[str, int] = {fam: _spec_purity(fam) for fam in _PURITY_FALLBACK}

# ICICI Breeze stock codes of the MCX gold families (the master's 6-character ShortName) and back. One table: routers.mcx
# re-exports it as `BREEZE_CODE`.
BREEZE_CODE = {"GOLD": "GOLD", "GOLDM": "GOLDMI", "GOLDTEN": "GOLDTE", "GOLDPETAL": "GOLDPE", "GOLDGUINEA": "GOLDGU"}
FAMILY_OF_BREEZE = {v: k for k, v in BREEZE_CODE.items()}


def family_code(code: str) -> str:
    """The MCX family of a family or Breeze code ('GOLDTE' → 'GOLDTEN'); upper-cased input otherwise."""
    c = str(code or "GOLD").upper()
    return FAMILY_OF_BREEZE.get(c, c)


def fineness_of(code: str) -> int:
    """The delivery purity of an MCX gold family (995 for GOLD / GOLDM, 999 for GOLDTEN / GOLDPETAL / GOLDGUINEA); a Breeze
    code works too. Unknown codes take GOLD's."""
    return CONTRACT_FINENESS.get(family_code(code), CONTRACT_FINENESS["GOLD"])


def purity_factor(code: str) -> float:
    """landed (fine gold) × this = the landed price at the contract's purity (0.995 / 0.999)."""
    return fineness_of(code) / LANDED_FINENESS


def basis_reference(code: str) -> str:
    """'landed_995' | 'landed_999': the landed price a contract's basis divides by."""
    return f"landed_{fineness_of(code)}"


def fair_open(settlement: float, comex_ref: float, comex_now: float, inr_ref: float, inr_now: float,
              duty_pct: float | None = None, fineness: int = LANDED_FINENESS) -> dict[str, Any]:
    """Multiplicative fair value plus a split of the gap into its COMEX and rupee parts, and the duty leg
    (SOURCES.md M5–M8): landed at the MCX-close references, duty-paid landed, and the settlement's basis vs the duty-paid
    landed price OF THE CONTRACT'S PURITY (`fineness`: landed × fineness / 1000; `landed` / `duty_paid_landed` stay per FINE
    gold, D1). Both legs of the basis sit at the settlement session's close (one clock). `implied_premium_pct` (settlement vs
    EX-duty landed) stays for one release as a deprecated alias: it rolled duty, carry and premium into one "17 %" number."""
    r_c, r_i = comex_now / comex_ref, inr_now / inr_ref
    fair = settlement * r_c * r_i
    comex_part = settlement * (r_c - 1)
    inr_part = settlement * r_c * (r_i - 1)
    d = duty_rate()["pct"] if duty_pct is None else duty_pct
    landed_ref = landed_inr_per_10g(comex_ref, inr_ref)
    duty_paid_ref = landed_ref * (1 + d / 100)
    duty_paid_pure = duty_paid_ref * fineness / LANDED_FINENESS
    return {
        "fair_open": round(fair, 0),
        "gap": round(fair - settlement, 0),
        "gap_pct": round((fair / settlement - 1) * 100, 2),
        "comex_part": round(comex_part, 0),
        "inr_part": round(inr_part, 0),
        "rs_per_comex_dollar": round(settlement / comex_ref, 2),       # ≈ "356 × ΔCOMEX / 10"
        "rs_per_inr_rupee": round(settlement / inr_ref, 0),            # ≈ "1,521 × ΔINR"
        "landed": round(landed_ref, 0),                                # ex-duty, per fine gold, at the MCX-close references
        "duty_pct": d,
        "duty_paid_landed": round(duty_paid_ref, 0),
        "duty_paid_landed_purity": round(duty_paid_pure, 0),           # the same at the contract's purity
        "purity": fineness,
        "basis_reference": f"landed_{fineness}",
        "basis_pct": round((settlement / duty_paid_pure - 1) * 100, 2),  # MCX settlement vs duty-paid landed of its purity (M8)
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


# ── the MCX settlement baseline (GOLD wave 1d, 5 Nov 2026) ───────────────────────────────────────────────────────────
#
# ICICI's security master is built from the exchange's contract file of the session BEFORE its publish date: its ±3 % price
# band is that session's band, centred on the settlement one session earlier still. So the band midpoint of a file published
# on D is the settlement of previous_session(previous_session(D)) — measured 5 Nov 2026 against the last-30-min VWAP of
# Breeze 1-minute bars (MCX GOLD DEC-26): the 05 Nov file's ₹1,39,452 = Tue 03 Nov ₹1,39,448; the 04 Nov file's ₹1,40,186 =
# Mon 02 Nov ₹1,40,190; the 28 Oct file's ₹1,43,073 = Mon 26 Oct ₹1,43,069. The page labelled each of them with the session
# after (one session stale: every fair-open miss in the log equalled the previous session's gold move, corr 0.98).
# MCX settles gold futures on the volume-weighted average of the last 30 minutes, so the honest proxy for the LATEST
# completed session is the last-30-min VWAP of the Breeze 1-minute bars (labelled a proxy); the band stays the fallback,
# labelled with the session it really belongs to, and the two are compared (`settlement_check`, flagged beyond 0.6 %).

BAND_LAG_SESSIONS = 2            # the band midpoint of a file published on D = the settlement two MCX sessions back
SETTLE_CHECK_PCT = 0.6           # band vs VWAP30 beyond this = the band is not that session's settlement (also the log's flag)
VWAP_WINDOW_MIN = 30             # MCX's settlement window: the last 30 minutes of the session
VWAP_READY_AFTER_S = 120.0       # a session counts as completed for the VWAP two minutes after its close (last bar in)
VWAP_FETCH_LEAD_MIN = 40         # one historical call: the bars from 40 minutes before the close to 23:59


def band_session(published: date) -> date:
    """The session whose settlement the band midpoint of a master published on `published` really is (see above)."""
    d = published
    for _ in range(BAND_LAG_SESSIONS):
        d = previous_session(d)
    return d


def band_applies_to(published: date) -> date:
    """The session the master's price band was the band OF (centred on `band_session`): the session before the publish day."""
    return previous_session(published)


def session_close_at(day: date) -> datetime:
    """The end of `day`'s MCX session: the trading window's close (an evening-closure day ends at 17:00), else the usual
    23:30 / 23:55 rule."""
    win = specs.trading_window(day)
    return win[1] if win else mcx_close_time(day)


def latest_completed_session(now: datetime, ready_after_s: float = VWAP_READY_AFTER_S) -> date:
    """The latest MCX session whose close (plus `ready_after_s` for the last bar) has passed at `now`."""
    now = now.astimezone(IST)
    today = now.date()
    win = specs.trading_window(today)
    if win and now >= win[1] + timedelta(seconds=ready_after_s):
        return today
    return previous_session(today)


def _bar_minute(bar: dict[str, Any]) -> datetime | None:
    """A Breeze bar's start minute as IST (Breeze prints IST wall clock without an offset, `2026-11-04 23:54:00`)."""
    raw = str(bar.get("datetime") or bar.get("ts") or "").strip()[:19]
    try:
        t = datetime.fromisoformat(raw.replace(" ", "T"))
    except ValueError:
        return None
    return t.replace(tzinfo=IST) if t.tzinfo is None else t.astimezone(IST)


def _bar_num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def vwap_last_minutes(bars: list[dict[str, Any]], close_at: datetime, minutes: int = VWAP_WINDOW_MIN) -> dict[str, Any] | None:
    """The volume-weighted average of the 1-minute closes in [close − `minutes`, close) — MCX's settlement window — or the
    plain average when the window traded no volume; None without a bar in the window. Pure (tested on recorded bars)."""
    start = close_at - timedelta(minutes=minutes)
    win: list[tuple[datetime, float, float]] = []
    for b in bars:
        t, c = _bar_minute(b), _bar_num(b.get("close"))
        if t is None or c is None or c <= 0 or not (start <= t < close_at):
            continue
        win.append((t, c, max(0.0, _bar_num(b.get("volume")) or 0.0)))
    if not win:
        return None
    win.sort()
    vol = sum(v for _, _, v in win)
    if vol > 0:
        value, method = sum(c * v for _, c, v in win) / vol, "volume-weighted"
    else:
        value, method = sum(c for _, c, _ in win) / len(win), "equal-weight (no volume in the window)"
    return {"value": round(value, 1), "bars": len(win), "volume": vol, "method": method,
            "window": f"{start:%H:%M}–{close_at:%H:%M} IST", "first_bar": win[0][0].isoformat(timespec="minutes"),
            "last_bar": win[-1][0].isoformat(timespec="minutes"), "last_close": win[-1][1]}


def settlement_check(band_mid: float | None, vwap: float | None, band_sess: date | None = None,
                     vwap_sess: date | None = None) -> dict[str, Any]:
    """The band midpoint vs the last-30-min VWAP: {band_vs_vwap30_pct, flagged, threshold_pct, compared}; `flagged` when they
    differ by more than SETTLE_CHECK_PCT (the band is then not that session's settlement). Unflagged without both legs."""
    out: dict[str, Any] = {"band_vs_vwap30_pct": None, "flagged": False, "threshold_pct": SETTLE_CHECK_PCT, "compared": None}
    if not band_mid or not vwap:
        out["note"] = "no last-30-min VWAP to compare the band with (no ICICI session, or no bars in the window)"
        return out
    pct = round((band_mid / vwap - 1) * 100, 2)   # the printed figure decides (0.60 % is inside the limit)
    out["band_vs_vwap30_pct"] = pct
    out["flagged"] = abs(pct) > SETTLE_CHECK_PCT
    left = f"band midpoint ({session_label(band_sess)})" if band_sess else "band midpoint"
    right = f"last-30-min VWAP ({session_label(vwap_sess)})" if vwap_sess else "last-30-min VWAP"
    out["compared"] = f"{left} vs {right}"
    return out


def band_check(band_mid: float | None, b_sess: date | None, latest: date, prev: date, v: float | None,
               prev_vwap: dict[str, Any] | None, used_sess: date | None) -> dict[str, Any]:
    """The band VALIDATED against the last-30-min VWAP of the band's OWN session (wave 1e minor, C-DATA-3 / C-TRADER-3: the
    check compared the band of S−1 with the VWAP of S, so it measured S's move — −0.60 % against a 0.6 % limit on 6 Nov, and
    any session moving more than 0.6 % would raise the amber note while nothing was wrong). The band's session VWAP is the
    latest one (`v`) or the cached / stored previous one (`prev_vwap`); without it there is NO check (`same_session` False,
    `band_vs_vwap30_pct` None, never flagged) and the cross-session gap is served as `session_move_pct` instead. Pure."""
    same: float | None = None
    if b_sess is not None:
        if v and b_sess == latest:
            same = v
        elif b_sess == prev:
            same = _vwap_value(prev_vwap, prev)
    if same is not None:
        out = settlement_check(band_mid, same, b_sess, b_sess)
        out["same_session"] = True
        return out
    out = settlement_check(band_mid, None, b_sess, None)
    out["same_session"] = False
    if band_mid and b_sess and used_sess and used_sess != b_sess:
        out["note"] = (f"the band's own session ({session_label(b_sess)}) has no last-30-min VWAP here: the band against the "
                       f"{session_label(used_sess)} would measure that session's move, not the proxy (see session_move_pct)")
    return out


def _vwap_value(vwap: dict[str, Any] | None, session: date | None = None) -> float | None:
    """The value of an OK VWAP result (of `session` when given), else None: a failed status is never a price."""
    if not isinstance(vwap, dict) or vwap.get("status") != "ok" or not vwap.get("value"):
        return None
    if session is not None and vwap.get("session") and str(vwap["session"])[:10] != session.isoformat():
        return None
    return float(vwap["value"])


def settlement_block(band_mid: float | None, published: date | None, vwap: dict[str, Any] | None,
                     latest: date, prev_vwap: dict[str, Any] | None = None) -> dict[str, Any]:
    """The settlement every gold number divides by (wave-1d CONTRACT): the latest completed session's last-30-min VWAP of
    Breeze 1-minute bars when known; else the PREVIOUS session's VWAP when it is still cached (`prev_vwap`: fresher than a
    band, which is two sessions old — checker round 1); else the band midpoint labelled with the session it REALLY belongs
    to. The band is kept beside it with its own session, and band and VWAP compared (sessions named). Pure."""
    b_sess = band_session(published) if published else None
    prev = previous_session(latest)
    v = _vwap_value(vwap)
    pv = None if v else _vwap_value(prev_vwap, prev)
    if pv is not None and b_sess is not None and prev < b_sess:
        pv = None                              # never older than the band
    used, used_sess = (vwap, latest) if v else ((prev_vwap, prev) if pv else (None, None))
    out: dict[str, Any] = {
        "band_midpoint": band_mid,
        "band_session": b_sess.isoformat() if b_sess else None,
        "band_session_label": session_label(b_sess) if b_sess else None,
        "band_applies_to": band_applies_to(published).isoformat() if published else None,
        "latest_session": latest.isoformat(),
        "latest_session_label": session_label(latest),
        "settlement_check": band_check(band_mid, b_sess, latest, prev, v, prev_vwap, used_sess),
        "vwap30": ({k: (used or {}).get(k) for k in ("value", "bars", "volume", "method", "window", "last_close", "session")}
                   if used else None),
        "vwap30_status": (vwap or {}).get("status") if isinstance(vwap, dict) else "not_fetched",
    }
    if v or pv:
        sess, val = (latest, v) if v else (prev, pv)
        out["settlement"], out["settlement_source"], out["settlement_quality"] = val, "breeze_vwap30", "vwap30_proxy"
        out["settlement_method"] = f"last-30-min VWAP of ICICI Breeze 1-minute bars ({(used or {}).get('window')}) — a proxy"
    elif band_mid and b_sess:
        sess, out["settlement"], out["settlement_source"], out["settlement_quality"] = b_sess, band_mid, "band_midpoint", "band_proxy"
        out["settlement_method"] = "ICICI price-band midpoint (±3 % band of the next session) — a proxy"
    else:
        sess, out["settlement"], out["settlement_source"], out["settlement_quality"] = None, None, None, None
        out["settlement_method"] = None
    out["settlement_session"] = sess.isoformat() if sess else None
    out["settlement_session_label"] = session_label(sess) if sess else None
    out["settlement_is_latest"] = bool(sess and sess == latest)
    # the move from the band's session to the served VWAP's, labelled as a MOVE (wave 1e minor: it was the check's number)
    sv = v or pv
    out["session_move_pct"] = (round((sv / band_mid - 1) * 100, 2)
                               if band_mid and sv and b_sess and used_sess and used_sess != b_sess else None)
    out["session_move_label"] = (f"{b_sess:%a %d %b} → {used_sess:%a %d %b} settlement move (band midpoint → last-30-min VWAP)"
                                 if out["session_move_pct"] is not None and b_sess and used_sess else None)
    how = "last-30-min VWAP, proxy" if out["settlement_source"] == "breeze_vwap30" else "band proxy"
    out["settlement_note"] = (
        None if sess is None or sess == latest
        else (f"{session_label(sess)} ({how}): the {session_label(latest)} needs the Breeze last-30-min VWAP "
              f"({str(out['vwap30_status']).replace('_', ' ')}); the fair open scales the older settlement by every COMEX and "
              f"rupee move since its close, so the expected gap also holds {latest:%a}'s move")
    )
    return out


def older_than_expected_note(served: date, expected: date, vwap_status: Any = None) -> str:
    """The 08:45 flag when the baseline belongs to an OLDER session than the latest completed one (wave 1e, M-D: on Mon
    9 Nov the expected session is the Sun 8 Nov Muhurat window; with no VWAP stored or read for it the baseline would skip
    its move — the 5 Nov stale-baseline blocker for one morning). Pure."""
    special = specs.special_session_on(expected)
    what = f"{session_label(expected)}" + (f" ({special['name']}, {special['opens']}–{special['closes']} IST)" if special else "")
    why = str(vwap_status or "not fetched").replace("_", " ")
    return (f"baseline session older than expected: the {session_label(served)} is used, but the latest completed session is "
            f"the {what} and no last-30-min VWAP is stored or read for it ({why}); the fair open also carries that "
            "session's move")


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


# ── the last-30-min VWAP from Breeze: ONE read-only historical call per contract per session, kept all night ────────────
SETTLE_BREEZE_CALLER = "ui-api.gold_settlement"       # the budget ledger's caller name (shared/breeze_budget.py)
SETTLE_OK_TTL_S = 14 * 3600.0                          # a completed session's VWAP never changes: kept the whole night
SETTLE_MISS_TTL_S = 600.0                              # an early / failed / refused answer is asked again after 10 min
SETTLE_NO_SESSION_TTL_S = 120.0                        # no ICICI session: no call was made; look again in 2 min
# Round-2 checker: a session that closed long ago will never grow bars, so an empty answer for it is final until morning
# (the CONTRACTS page polls every 5 min and queues thin back months and unverified Breeze codes); every key is also capped
# at SETTLE_MAX_CALLS calls per SETTLE_CALLS_WINDOW_S, whatever the answers were.
SETTLE_FINAL_AFTER_S = 15 * 60.0                       # 15 min after the close an empty window is final …
SETTLE_FINAL_MISS_TTL_S = 8 * 3600.0                   # … and kept 8 h (a 23:58 miss is asked again after 07:58)
SETTLE_MAX_CALLS = 4                                   # Breeze calls per key per window, then the miss is kept 8 h
SETTLE_CALLS_WINDOW_S = 12 * 3600.0
# A VWAP read too soon after the close may miss the last bars (Breeze's 1-minute bars can lag): it is cached for 14 h only
# when its last bar is within SETTLE_LAST_BAR_SLACK_MIN of the close or the read ran SETTLE_COMPLETE_AFTER_S after it;
# otherwise it is used for that request and read again after SETTLE_PARTIAL_TTL_S (03 Nov had 27 bars in 30 minutes, so a
# bar count is not the test).
SETTLE_LAST_BAR_SLACK_MIN = 3
SETTLE_COMPLETE_AFTER_S = 10 * 60.0
SETTLE_PARTIAL_TTL_S = 300.0
SETTLE_WAIT_S = 8.0                                    # a request waits at most this long for the one call, then uses the band
SETTLE_SNAPSHOT_WAIT_S = 30.0                          # the 08:45 recorded prediction waits longer for it
_settle_cache = TTLCache("gold_settlement", max_items=256, default_ttl=SETTLE_OK_TTL_S)
_settle_locks: dict[str, threading.Lock] = {}
_settle_locks_guard = threading.Lock()
_settle_inflight: set[str] = set()                     # keys whose ONE Breeze call is running right now
_settle_calls: dict[str, list[float]] = {}             # key → monotonic times of its Breeze calls (the per-key cap)
_SETTLE_WAIT: contextvars.ContextVar[float] = contextvars.ContextVar("gold_settle_wait", default=SETTLE_WAIT_S)


def _now_ist() -> datetime:
    """The wall clock in IST (one seam for tests)."""
    return datetime.now(IST)


def _settle_wait() -> float:
    return _SETTLE_WAIT.get()


def settle_breeze_enabled() -> bool:
    """GOLD_SETTLE_BREEZE=1/0 decides; unset, it is on except under pytest (a test never reaches the live broker)."""
    flag = os.environ.get("GOLD_SETTLE_BREEZE", "").strip()
    if flag in ("0", "1"):
        return flag == "1"
    try:
        from shared.http_guard import in_test_mode
        if in_test_mode():
            return False
    except ImportError:
        pass
    return True


def _breeze_session_bars(stock_code: str, expiry: date, session: date) -> tuple[list[dict[str, Any]] | None, str]:
    """Blocking. ONE read-only `get_historical_data_v2` call through the Breeze budget ledger: `session`'s 1-minute bars from
    40 minutes before its close to 23:59 (Breeze reads the times as IST wall clock and ignores the Z). Returns (bars, status),
    status ok | disabled | no_session | budget | empty | error. Never raises; prints nothing from the environment."""
    if not settle_breeze_enabled():
        return None, "disabled"
    try:
        from routers.positions import _get_breeze_client
        breeze, err = _get_breeze_client()
    except Exception:  # noqa: BLE001 — import/build failure is a session problem
        return None, "no_session"
    if err or breeze is None:
        return None, "no_session"
    start = session_close_at(session) - timedelta(minutes=VWAP_FETCH_LEAD_MIN)
    try:
        from shared.breeze_budget import BudgetExceeded, ledger
    except ImportError:  # pragma: no cover — the ledger ships with the repo
        return None, "error"
    try:
        with ledger().guard(SETTLE_BREEZE_CALLER, "get_historical_data_v2"):
            h = breeze.get_historical_data_v2(interval="1minute", from_date=f"{session.isoformat()}T{start:%H:%M}:00.000Z",
                                              to_date=f"{session.isoformat()}T23:59:00.000Z", stock_code=stock_code,
                                              exchange_code="MCX", product_type="futures",
                                              expiry_date=f"{expiry.isoformat()}T06:00:00.000Z", right="others",
                                              strike_price="0")
    except BudgetExceeded:
        return None, "budget"
    except Exception:  # noqa: BLE001 — the broker is optional here
        return None, "error"
    rows = h.get("Success") if isinstance(h, dict) and h.get("Status") == 200 else None
    if not rows:
        return None, "empty"
    return [r for r in rows if str(r.get("datetime", "")).startswith(session.isoformat())], "ok"


def _settle_key(stock_code: str, expiry: date, session: date) -> str:
    return f"vwap30:{stock_code}:{expiry.isoformat()}:{session.isoformat()}"


def session_vwap_cached(stock_code: str, expiry: date, session: date) -> dict[str, Any] | None:
    """Non-blocking: the cached result for (contract, expiry, session) — {status: ok, value, …} or {status: <why not>} — or
    None when it was never asked (or the miss expired)."""
    hit = _settle_cache.get(_settle_key(stock_code, expiry, session))
    return hit if isinstance(hit, dict) else None


def session_vwap(stock_code: str, expiry: date, session: date) -> dict[str, Any]:
    """Blocking (call via asyncio.to_thread): the cached result, else ONE Breeze call for the session (single flight per key:
    concurrent callers wait for the one call). A success is kept all night; a miss is asked again after its TTL."""
    key = _settle_key(stock_code, expiry, session)
    hit = session_vwap_cached(stock_code, expiry, session)
    if hit is not None:
        return hit
    with _settle_locks_guard:
        lock = _settle_locks.setdefault(key, threading.Lock())
    with lock:
        hit = session_vwap_cached(stock_code, expiry, session)
        if hit is not None:
            return hit
        mono = time.monotonic()
        with _settle_locks_guard:
            recent = [t for t in _settle_calls.get(key, []) if mono - t < SETTLE_CALLS_WINDOW_S]
            capped = len(recent) >= SETTLE_MAX_CALLS
            _settle_calls[key] = recent
            if not capped:
                _settle_inflight.add(key)
        result: dict[str, Any]
        if capped:      # this key has had its calls: keep the miss until morning, never another call tonight
            result = {"status": "call_cap", "session": session.isoformat(),
                      "note": f"{SETTLE_MAX_CALLS} Breeze reads in {SETTLE_CALLS_WINDOW_S / 3600:g} h gave no VWAP"}
            _settle_cache.set(key, result, ttl=SETTLE_FINAL_MISS_TTL_S)
            return result
        bars: list[dict[str, Any]] | None = None
        status = "error"
        try:
            bars, status = _breeze_session_bars(stock_code, expiry, session)
        finally:
            with _settle_locks_guard:
                _settle_inflight.discard(key)
                if status_made_call(status):
                    _settle_calls.setdefault(key, []).append(mono)
        close_at = session_close_at(session)
        vw = vwap_last_minutes(bars or [], close_at) if bars else None
        if vw:
            complete = vwap_window_complete(vw, close_at, _now_ist())
            result = {"status": "ok", **vw, "session": session.isoformat(), "source": "breeze_vwap30",
                      "stock_code": stock_code, "expiry": expiry.isoformat(), "window_complete": complete}
            ttl = SETTLE_OK_TTL_S if complete else SETTLE_PARTIAL_TTL_S
        else:
            result = {"status": "no_bars_in_window" if status == "ok" else status, "session": session.isoformat()}
            ttl = settle_miss_ttl(result["status"], close_at, _now_ist())
        _settle_cache.set(key, result, ttl=ttl)
        return result


def status_made_call(status: str | None) -> bool:
    """True when `_breeze_session_bars` reached the broker (its answer counts against the per-key cap)."""
    return status in ("ok", "empty", "error")


def vwap_window_complete(vw: dict[str, Any], close_at: datetime, read_at: datetime) -> bool:
    """A VWAP is final when its last bar sits within SETTLE_LAST_BAR_SLACK_MIN of the close, or the read ran at least
    SETTLE_COMPLETE_AFTER_S after the close (Breeze had time to deliver every bar). Pure."""
    try:
        last = datetime.fromisoformat(str(vw.get("last_bar") or ""))
    except ValueError:
        last = None
    if last is not None:
        last = last.replace(tzinfo=IST) if last.tzinfo is None else last
        if last >= close_at - timedelta(minutes=SETTLE_LAST_BAR_SLACK_MIN + 1):   # the bar that STARTS at close − 4 ends at − 3
            return True
    return read_at >= close_at + timedelta(seconds=SETTLE_COMPLETE_AFTER_S)


def settle_miss_ttl(status: str, close_at: datetime, read_at: datetime) -> float:
    """How long a miss is kept. Pure: no call made (no ICICI session / disabled) → 2 min; an empty window read more than
    SETTLE_FINAL_AFTER_S after the close → until morning (those bars never come); a budget refusal, an error or an early
    empty read → 10 min."""
    if status in ("no_session", "disabled"):
        return SETTLE_NO_SESSION_TTL_S
    if status in ("empty", "no_bars_in_window") and read_at >= close_at + timedelta(seconds=SETTLE_FINAL_AFTER_S):
        return SETTLE_FINAL_MISS_TTL_S
    return SETTLE_MISS_TTL_S


_prefetch_pending: set[str] = set()


def prefetch_session_vwaps(items: list[tuple[str, date, date]]) -> int:
    """Non-blocking: read the not-yet-cached (Breeze code, expiry, session) VWAPs ONE AFTER ANOTHER on one daemon thread (the
    CONTRACTS cards ask for every liquid expiry; nobody waits). Returns how many were queued."""
    if not settle_breeze_enabled():
        return 0
    todo: list[tuple[str, date, date]] = []
    with _settle_locks_guard:
        for it in dict.fromkeys(items):
            key = _settle_key(*it)
            if key not in _prefetch_pending and session_vwap_cached(*it) is None:
                _prefetch_pending.add(key)
                todo.append(it)
    if not todo:
        return 0

    def _work() -> None:
        for it in todo:
            try:
                session_vwap(*it)
            except Exception:  # noqa: BLE001 — one failed read never stops the others
                pass
            finally:
                with _settle_locks_guard:
                    _prefetch_pending.discard(_settle_key(*it))
    try:
        threading.Thread(target=_work, name="gold-settle-prefetch", daemon=True).start()
    except RuntimeError:  # interpreter shutting down
        with _settle_locks_guard:
            for it in todo:
                _prefetch_pending.discard(_settle_key(*it))
        return 0
    return len(todo)


async def session_vwap_async(stock_code: str, expiry: date, session: date, wait_s: float = SETTLE_WAIT_S) -> dict[str, Any]:
    """`session_vwap` off the event loop with a deadline: past it the request uses the band (the one call keeps running and
    fills the cache for the next request)."""
    hit = session_vwap_cached(stock_code, expiry, session)
    if hit is not None:
        return hit
    key = _settle_key(stock_code, expiry, session)
    with _settle_locks_guard:
        busy = key in _settle_inflight or key in _prefetch_pending
    if busy:   # the one call is already running: wait on the cache (event-loop sleep), never park a worker thread on its lock
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            await asyncio.sleep(0.25)
            hit = session_vwap_cached(stock_code, expiry, session)
            if hit is not None:
                return hit
        return {"status": "pending", "session": session.isoformat()}
    try:
        return await asyncio.wait_for(asyncio.to_thread(session_vwap, stock_code, expiry, session), wait_s)
    except (asyncio.TimeoutError, TimeoutError):
        return {"status": "pending", "session": session.isoformat()}
    except Exception:  # noqa: BLE001 — never fails the caller
        return {"status": "error", "session": session.isoformat()}


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
    # the settlement baseline (wave 1d): the latest completed session's last-30-min VWAP (Breeze 1-minute bars, ONE call per
    # contract per session, kept all night), else the band midpoint labelled with the session it really belongs to — and the
    # COMEX / rupee references are taken at THAT session's close, so the fair open scales the right settlement
    last_session = latest_completed_session(now)
    vwap = prev_vwap = None
    if contract and not baseline:
        # ONE path for every caller (routers.mcx.settlement_vwaps): the cache, then data-service's stored VWAP30 (G-DATA's
        # 23:58 read costs no call here), then ONE Breeze read; the previous session's VWAP stands in when cached
        from routers import mcx as mcxr   # late import: routers.mcx imports this module
        vwap, prev_vwap = await mcxr.settlement_vwaps("GOLD", contract["expiry"], last_session, wait_s=_settle_wait())
    settle = settlement_block(contract["settlement"] if contract else None, master[1] if master else None, vwap, last_session,
                              prev_vwap)
    settle_day = date.fromisoformat(settle["settlement_session"]) if settle["settlement_session"] else last_session
    close_at = session_close_at(settle_day)
    if settle_day < last_session and not baseline:
        notes.append(older_than_expected_note(settle_day, last_session, settle.get("vwap30_status")) + ".")
    if settle["settlement_note"] and not baseline:
        notes.append(f"Baseline is the {settle['settlement_note']}.")
    if settle["settlement_check"]["flagged"]:
        notes.append(f"The ICICI band midpoint ₹{settle['band_midpoint']:,.0f} ({settle['band_session_label']}) is "
                     f"{settle['settlement_check']['band_vs_vwap30_pct']:+.2f} % from that same session's last-30-min VWAP: "
                     "beyond the 0.6 % test, the band is not that session's settlement.")
    broker = await asyncio.to_thread(_breeze_mcx_quote, contract["expiry"]) if contract else None
    if contract and not broker and today_mcx["trading"] and open_at is not None and now.time() >= open_at:
        broker = await asyncio.to_thread(_breeze_mcx_open, contract["expiry"], now.date())

    base_value, base_source = None, None
    if baseline:
        base_value, base_source = baseline, "your entry"
    elif broker and broker.get("previous_close"):
        base_value, base_source = broker["previous_close"], "ICICI Breeze previous close"
    elif settle["settlement"]:
        base_value = settle["settlement"]
        base_source = (f"MCX {settle['settlement_session_label']} · last-30-min VWAP (Breeze 1-min bars, proxy)"
                       if settle["settlement_source"] == "breeze_vwap30"
                       else f"MCX {settle['settlement_session_label']} (ICICI price-band midpoint, proxy)")
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
        model.update(fair_open(base_value, comex_ref, model["comex"]["now"], inr_ref, model["inr"]["now"],
                               fineness=fineness_of("GOLD")))
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
                     # the band is the price band MCX applied on `band_applies_to`, centred on the `band_session` settlement
                     # (never "today's band": the 05 Nov open ₹1,45,153 sat above the 05 Nov file's top ₹1,43,635)
                     "band_applies_to": settle["band_applies_to"],
                     "band_session": settle["band_session"],
                     "open_interest_lots": contract["open_interest"] if contract else None},
        "baseline": {"value": base_value, "source": base_source, "session": settle_day.isoformat(),
                     "session_label": session_label(settle_day),           # "Wed 04 Nov settlement", never the file date
                     "stale": settle_day < last_session and not baseline,  # an older session than the latest completed one
                     # wave 1e (M-D): the session the baseline SHOULD be (the latest completed one, Muhurat included) and,
                     # when the served one is older, why — e.g. Mon 9 Nov 08:45 with no VWAP stored or read for Sun 8 Nov
                     "expected_session": last_session.isoformat(),
                     "expected_session_label": session_label(last_session),
                     "older_than_expected": bool(settle_day < last_session and not baseline),
                     "older_note": (older_than_expected_note(settle_day, last_session, settle.get("vwap30_status"))
                                    if settle_day < last_session and not baseline else None),
                     "close_time": close_at.isoformat(),
                     "settlement_source": None if baseline else settle["settlement_source"],
                     "settlement_quality": None if baseline else settle["settlement_quality"],
                     "settlement_method": None if baseline else settle["settlement_method"],
                     "settlement_check": settle["settlement_check"],
                     "latest_session": settle["latest_session"],
                     "band_midpoint": settle["band_midpoint"],
                     "band_session": settle["band_session"],
                     "band_session_label": settle["band_session_label"],
                     "settlement_from_band": contract["settlement"] if contract else None,   # deprecated alias of band_midpoint
                     "vwap30": settle["vwap30"],
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


_LABEL_DAY_RE = re.compile(r"settlement\s+(\d{1,2})\s+([A-Z][a-z]{2})")
_CONTRACT_LABEL_RE = re.compile(r"^\s*(GOLD[A-Z]*)\s+([A-Za-z]{3})-(\d{2})\s*$")
_BAND_SOURCE_RE = re.compile(r"price-band midpoint", re.I)


def labelled_session(row: dict[str, Any]) -> date | None:
    """The session a log row's baseline was LABELLED with: `baseline_session` when recorded (26 Oct →), else the day its
    `baseline_source` names ('MCX settlement 16 Oct (price-band midpoint)': the 20 Oct row used the 19 Oct master on a
    Dussehra morning, so the snapshot-day rule would mislabel it), else the rule the desk used before wave 1d (the session
    before the snapshot day)."""
    try:
        return date.fromisoformat(str(row.get("baseline_session") or "")[:10])
    except ValueError:
        pass
    try:
        day = date.fromisoformat(str(row.get("date") or "")[:10])
    except ValueError:
        return None
    m = _LABEL_DAY_RE.search(str(row.get("baseline_source") or ""))
    if m:
        try:
            got = datetime.strptime(f"{m.group(1)} {m.group(2)} {day.year}", "%d %b %Y").date()
            return got if got <= day else got.replace(year=day.year - 1)
        except ValueError:
            pass
    return previous_session(day)


@functools.lru_cache(maxsize=64)
def expiry_from_label(label: str) -> tuple[str, date] | None:
    """(family, expiry) of a log row's contract label ('GOLD DEC-26' → ('GOLD', 2026-12-04)) by the shared/mcx_specs expiry
    rule of that family and month (PM decision D2: rows written before 05 Nov carry no `expiry`); None when unparseable."""
    m = _CONTRACT_LABEL_RE.match(str(label or ""))
    if not m:
        return None
    fam = family_code(m.group(1))
    try:
        month = datetime.strptime(m.group(2).title(), "%b").month
    except ValueError:
        return None
    year = 2000 + int(m.group(3))
    if fam not in specs.CONTRACTS:
        return None
    exps = specs.active_expiries(fam, date(year, month, 1), 1)
    if not exps or (exps[0].year, exps[0].month) != (year, month):
        return None
    return fam, exps[0]


def row_contract(row: dict[str, Any]) -> tuple[str, date] | None:
    """(family, expiry) of a log row: its recorded `expiry` (05 Nov →) with the label's family, else both from the label."""
    from_label = expiry_from_label(str(row.get("contract") or "GOLD"))
    fam = from_label[0] if from_label else "GOLD"
    try:
        return fam, date.fromisoformat(str(row.get("expiry") or "")[:10])
    except ValueError:
        return from_label


def baseline_from_band(row: dict[str, Any]) -> bool:
    """True when a row's baseline is an ICICI band midpoint (wave-1d `baseline_source_kind`, else the source text)."""
    kind = row.get("baseline_source_kind")
    if kind:
        return kind == "band_midpoint"
    return bool(_BAND_SOURCE_RE.search(str(row.get("baseline_source") or "")))


def band_rule(row: dict[str, Any]) -> dict[str, Any] | None:
    """For a band baseline, the session its number REALLY belongs to (no Breeze read: the verified band rule). Before wave 1d
    the desk labelled the band of the master published on D with previous_session(D), but that band midpoint is the
    settlement of band_session(D) — one session EARLIER than its label (verified four times: 05 Nov, 04 Nov, 28 Oct, 27 Oct
    and 26 Oct files vs Breeze VWAPs). Wave-1d rows (`baseline_source_kind` 'band_midpoint') are labelled with the real
    session already. None for a baseline that is not a band."""
    if not baseline_from_band(row):
        return None
    lab = labelled_session(row)
    if lab is None:
        return None
    real = lab if row.get("baseline_source_kind") == "band_midpoint" else previous_session(lab)
    return {"labelled_session": lab.isoformat(), "real_session": real.isoformat(), "real_session_label": session_label(real),
            "mislabelled": real != lab,
            "rule": ("the band midpoint of the master published on D is the settlement of the session two before D; the label "
                     "named the session before D" if real != lab else "labelled with the band's real session")}


def _row_vwap(row: dict[str, Any], vwap: dict[str, Any] | None) -> dict[str, Any] | None:
    """The VWAP of a row's labelled session: the one given (cached Breeze result), else the value recorded on the row."""
    if _vwap_value(vwap):
        return vwap
    v = _bar_num(row.get("labelled_session_vwap30"))
    lab = labelled_session(row)
    return {"status": "ok", "value": v, "session": lab.isoformat() if lab else None} if v else None


def baseline_check(row: dict[str, Any], vwap: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The settlement check of one log row: its baseline vs the last-30-min VWAP of the session it was LABELLED with — the
    check recorded on the row, else `vwap` (the cached Breeze result for that session) or the VWAP recorded on the row. None
    when none exists (unknown, never guessed). A wave-1d snapshot's `settlement_check` is NOT this check (it compares the band
    with the LATEST session's VWAP, another session than a band baseline's label). A band baseline labelled with the right
    session is not flagged; one labelled a session late fails this test by the session's move."""
    rec = row.get("baseline_check")
    if isinstance(rec, dict) and rec.get("band_vs_vwap30_pct") is not None:
        return rec
    if row.get("baseline_source_kind") == "breeze_vwap30":
        return {"band_vs_vwap30_pct": 0.0, "flagged": False, "threshold_pct": SETTLE_CHECK_PCT,
                "compared": "baseline IS the last-30-min VWAP"}
    base = _bar_num(row.get("baseline"))
    sess = labelled_session(row)
    v = _vwap_value(_row_vwap(row, vwap))
    if not base or not v or sess is None:
        return None
    chk = settlement_check(base, v, None, sess)
    chk["compared"] = f"baseline ₹{base:,.0f} labelled {session_label(sess)} vs that session's last-30-min VWAP ₹{v:,.0f}"
    return chk


def stale_reasons(row: dict[str, Any], vwap: dict[str, Any] | None = None) -> list[str]:
    """Why a row's baseline was not the settlement it was labelled with (empty = not stale, as far as is known):
    'vwap30_check' — baseline vs that session's last-30-min VWAP beyond 0.6 % (05 Nov: ₹1,39,452 labelled Wed 04 Nov vs Wed's
    ₹1,43,237 = −2.64 %; it was Tue's ₹1,39,448); 'band_rule' — a band baseline labelled one session late (`band_rule`: every
    row before wave 1d, no Breeze read needed); 'older_session' — a labelled session older than the one before the morning
    (the 15 Oct case); 'recorded' — the snapshot's own flag."""
    out: list[str] = []
    chk = baseline_check(row, vwap)
    if chk and chk.get("flagged"):
        out.append("vwap30_check")
    br = band_rule(row)
    if br and br["mislabelled"]:
        out.append("band_rule")
    lab = labelled_session(row)
    try:
        day = date.fromisoformat(str(row.get("date") or "")[:10])
    except ValueError:
        day = None
    if lab is not None and day is not None and lab < previous_session(day):
        out.append("older_session")
    if row.get("stale_baseline") is True:
        out.append("recorded")
    return out


def stale_baseline(row: dict[str, Any], vwap: dict[str, Any] | None = None) -> bool:
    """True when `stale_reasons` names any reason (see there)."""
    return bool(stale_reasons(row, vwap))


def re_explained(row: dict[str, Any], vwap: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """A COUNTERFACTUAL beside a band row's recorded numbers (PM decision D2: flagged and re-explained, never re-scored): the
    fair open had its baseline been the last-30-min VWAP of the session it was labelled with. The references were taken at
    that session's close, so the counterfactual fair is the recorded fair × VWAP ÷ baseline. None for a VWAP baseline or
    without that session's VWAP."""
    if row.get("baseline_source_kind") == "breeze_vwap30" or not baseline_from_band(row):
        return None
    v = _vwap_value(_row_vwap(row, vwap))
    base, fair, actual = _bar_num(row.get("baseline")), _bar_num(row.get("fair_open")), _bar_num(row.get("actual_open"))
    lab = labelled_session(row)
    if not (v and base and fair and lab):
        return None
    fair_v = fair * v / base
    return {
        "labelled_session": lab.isoformat(), "labelled_session_vwap30": round(v, 1),
        "session_move_pct": round((v / base - 1) * 100, 2),
        "fair_open_on_vwap30": round(fair_v, 0),
        "error_on_vwap30": round(actual - fair_v, 0) if actual else None,
        "naive_error_on_vwap30": round(actual - v, 0) if actual else None,
        "note": ("counterfactual: the fair open had the baseline been that session's last-30-min VWAP (references unchanged: "
                 "they sat at its close); the recorded error stays the scored number"),
    }


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


def _error_stats(done: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
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
    }


STALE_REASON_WORDS = {
    "vwap30_check": f"baseline vs the last-30-min VWAP of the session it was labelled with beyond {SETTLE_CHECK_PCT:g} %",
    "band_rule": "a band midpoint labelled one session late (the band of a master is the settlement two sessions before it)",
    "older_session": "a labelled session older than the one before the morning",
    "recorded": "flagged by the snapshot itself",
}


def accuracy_stats(rows: list[dict[str, Any]], threshold: float = 300) -> dict[str, Any]:
    """Model error (actual − fair) against the naive guess (open = yesterday's settlement). Nothing is re-scored: every row
    keeps its recorded numbers; the stale-baseline rows are NAMED (`stale_baseline_dates`, `stale_by` per reason) and the
    same stats are repeated without them (`excluding_stale`), so the panel can say which mornings a stale settlement decided.
    `stale_baseline_unknown` lists scored rows nothing could decide yet (not a band, no VWAP for their session). `on_vwap30`
    is the COUNTERFACTUAL over the rows `re_explained` covers: model and naive misses had the baseline been the labelled
    session's VWAP — beside the recorded stats, never instead of them."""
    done = [r for r in rows if r.get("error") is not None]
    rule = "; or ".join(STALE_REASON_WORDS.values())
    if not done:
        return {"days": 0, "stale_baseline_count": 0, "stale_baseline_dates": [], "stale_baseline_unknown": [], "stale_by": {},
                "stale_baseline_rule": rule, "excluding_stale": {"days": 0}, "on_vwap30": {"days": 0}}
    stale = [r for r in done if r.get("stale_baseline")]
    clean = [r for r in done if not r.get("stale_baseline")]
    by: dict[str, list[str]] = {}
    for r in stale:
        for why in r.get("stale_reasons") or []:
            by.setdefault(why, []).append(str(r.get("date")))
    out = {**_error_stats(done, threshold), "threshold": threshold,
           "stale_baseline_count": len(stale),
           "stale_baseline_dates": sorted(str(r.get("date")) for r in stale),
           "stale_by": {k: sorted(v) for k, v in sorted(by.items())},
           "stale_baseline_unknown": sorted(str(r.get("date")) for r in done
                                            if not r.get("stale_baseline") and r.get("baseline_check") is None
                                            and r.get("band_rule") is None),
           "stale_baseline_rule": rule}
    out["excluding_stale"] = ({**_error_stats(clean, threshold), "threshold": threshold} if clean else {"days": 0})
    cf_rows = [r for r in done if isinstance(r.get("re_explained"), dict) and r["re_explained"].get("error_on_vwap30") is not None
               and r["re_explained"].get("naive_error_on_vwap30") is not None]
    cf = [r["re_explained"] for r in cf_rows]
    if cf:
        err = sorted(abs(c["error_on_vwap30"]) for c in cf)
        naive = [abs(c["naive_error_on_vwap30"]) for c in cf]
        mid = len(err) // 2
        out["on_vwap30"] = {
            "days": len(cf),
            "mean_abs_error": round(sum(err) / len(err), 1),
            "median_abs_error": round(err[mid] if len(err) % 2 else (err[mid - 1] + err[mid]) / 2, 1),
            "naive_mean_abs_error": round(sum(naive) / len(naive), 1),
            "within_threshold_pct": round(100 * sum(e <= threshold for e in err) / len(err), 1),
            "dates": sorted(str(r.get("date")) for r in cf_rows),
            "note": ("counterfactual, not the score: the same mornings had each baseline been the last-30-min VWAP of the "
                     "session it was labelled with (references unchanged); the recorded stats above stay the scored numbers"),
        }
    else:
        out["on_vwap30"] = {"days": 0}
    return out


def snapshot_gate(now: datetime, force: bool) -> None:
    """Refuse a snapshot on a day MCX never opens (weekend, full holiday) and once today's session has opened —
    17:00 on a morning-closure day such as Dussehra 20 Oct, 09:00 otherwise; `force` overrides the opened rule."""
    today = mcx_day(now.date())
    if not today["trading"]:
        raise HTTPException(status_code=409, detail=f"{today['note'] or 'MCX closed today'}: no pre-open snapshot")
    if today["closure"] == "morning" and not force:      # PLAN c.3: the 08:45 call skips morning closures (no 09:00 open to call)
        raise HTTPException(status_code=409,
                            detail=f"{today['note']}: no 09:00 open to predict (force=true for the 17:00 session)")
    if today.get("special") and not force:               # Muhurat: a short afternoon window, no 09:00 open (wave 1e, M-D)
        raise HTTPException(status_code=409, detail=f"{today['note']}: no 09:00 open to predict (force=true to record anyway)")
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
    wait_token = _SETTLE_WAIT.set(SETTLE_SNAPSHOT_WAIT_S)   # … and waits for the one Breeze VWAP call (wave 1d)
    try:
        d = await gold_preopen(baseline=None, mcx_price=None, threshold=threshold, eurusd_trigger=None)
    finally:
        _SETTLE_WAIT.reset(wait_token)
        _FRESH_ONLY.reset(token)
    m = d.get("model") or {}
    if not m.get("fair_open"):
        raise HTTPException(status_code=503, detail="No fair value right now: " + "; ".join(d.get("notes") or ["inputs missing"]))
    b = d["baseline"]
    kind = b.get("settlement_source")
    return _update_day(now.date().isoformat(), snapshot_at=now.isoformat(timespec="seconds"),
                       contract=d["contract"]["name"], expiry=d["contract"]["expiry"], comex_symbol=d["contract"]["comex"],
                       baseline=b["value"], baseline_source=b["source"], baseline_session=b["session"],
                       baseline_source_kind=kind, band_midpoint=b.get("band_midpoint"), band_session=b.get("band_session"),
                       settlement_check=b.get("settlement_check"),
                       baseline_check=({"band_vs_vwap30_pct": 0.0, "flagged": False, "threshold_pct": SETTLE_CHECK_PCT,
                                        "compared": "baseline IS the last-30-min VWAP"} if kind == "breeze_vwap30" else None),
                       stale_baseline=bool(b.get("stale")), fair_open=round(m["fair_open"], 1),
                       baseline_expected_session=b.get("expected_session"),
                       baseline_older_than_expected=bool(b.get("older_than_expected")),
                       baseline_note=b.get("older_note"),
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


LOG_CHECKS_PER_CALL = 3          # at most this many background VWAP reads per /log call (each session read once, then kept)


def _row_vwap_args(row: dict[str, Any]) -> tuple[str, date, date] | None:
    """(Breeze code, expiry, labelled session) of a log row's settlement check; None without a baseline or a contract. Rows
    written before 05 Nov carry no `expiry`: it comes from the contract label ('GOLD DEC-26' → 2026-12-04, PM decision D2)."""
    sess = labelled_session(row)
    rc = row_contract(row)
    if not row.get("baseline") or sess is None or rc is None:
        return None
    fam, expiry = rc
    return BREEZE_CODE.get(fam, fam), expiry, sess


def _record_on_row(day: str, **fields: Any) -> dict[str, Any] | None:
    """Add fields to a stored log row WITHOUT recomputing anything (`_update_day` re-derives error / naive_error; a check
    recorded beside the numbers must never touch them — PM decision D2)."""
    with _log_lock:
        rows = _read_log()
        if day not in rows:
            return None
        row = {**rows[day], **{k: v for k, v in fields.items() if v is not None}}
        rows[day] = row
        _write_log(rows)
    _dual_write_log_async(row)
    return row


def _fill_row_check(day: str, stock_code: str, expiry: date, sess: date) -> None:
    """Background: read that session's VWAP (one call, cached) and RECORD the row's settlement check beside its numbers
    (the row's error / naive_error are never touched)."""
    try:
        res = session_vwap(stock_code, expiry, sess)
        if res.get("status") != "ok":
            return
        row = _read_log().get(day)
        if row and not isinstance(row.get("baseline_check"), dict):
            chk = baseline_check(row, res)
            if chk:
                _record_on_row(day, baseline_check=chk, labelled_session_vwap30=res.get("value"),
                               labelled_session_vwap30_expiry=expiry.isoformat())
    except Exception:  # noqa: BLE001 — a background check never breaks the log
        _log.warning(json.dumps({"event": "gold_log_check_failed", "day": day}))


def log_rows(days: int, fill_checks: bool = False) -> list[dict[str, Any]]:
    """The newest `days` rows, each with `stale_baseline` and its `stale_reasons`, `baseline_check`, `band_rule`,
    `re_explained` (a counterfactual beside the recorded numbers) and `inputs_json` (None before 26 Oct). `fill_checks` starts
    up to LOG_CHECKS_PER_CALL background reads of the Breeze VWAP for rows whose check is unknown (one call per session,
    recorded on the row; the expiry of an old row comes from its contract label)."""
    rows = sorted(_read_log().values(), key=lambda r: r["date"], reverse=True)[:days]
    out: list[dict[str, Any]] = []
    todo: list[tuple[str, str, date, date]] = []
    calls = 0
    for r in rows:
        vw = None
        args = None if isinstance(r.get("baseline_check"), dict) else _row_vwap_args(r)
        if args:
            vw = session_vwap_cached(*args)
            if vw is None and calls < LOG_CHECKS_PER_CALL:
                todo.append((r["date"], *args))
                calls += 1
            elif vw is not None and vw.get("status") == "ok" and fill_checks:
                todo.append((r["date"], *args))      # read already: just record it on the row (no call)
        reasons = stale_reasons(r, vw)
        out.append({**r, "baseline_check": baseline_check(r, vw), "stale_baseline": bool(reasons), "stale_reasons": reasons,
                    "band_rule": band_rule(r), "re_explained": re_explained(r, vw),
                    "check_contract": ({"breeze_code": args[0], "expiry": args[1].isoformat(), "session": args[2].isoformat()}
                                       if args else None),
                    "inputs_json": r.get("inputs_json")})
    if fill_checks and todo and settle_breeze_enabled():
        def _work(items: list[tuple[str, str, date, date]] = todo) -> None:   # ONE thread, one call after another
            for day, stock, expiry, sess in items:
                _fill_row_check(day, stock, expiry, sess)
        try:
            threading.Thread(target=_work, name="gold-log-check", daemon=True).start()
        except RuntimeError:
            pass
    return out


@router.get("/gold-preopen/log")
def gold_log(days: int = Query(60, ge=1, le=400), threshold: float = Query(300, gt=0)) -> dict[str, Any]:
    rows = log_rows(days, fill_checks=True)
    return {"rows": rows, "stats": accuracy_stats(rows, threshold)}

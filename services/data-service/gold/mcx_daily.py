"""MCX gold futures daily history from ICICI Breeze: OHLC + volume + open interest per LIVE expiry (owner decision O-8,
6 Nov 2026; SOURCES.md F2). The MCX-site collectors (``mcx_official``, ``mcx_category``) stay dormant.

Storage: its own table ``gold_mcx_daily`` (trade_date, family, expiry) — never ``gold_curve``, whose readers
(``mcx_close.contracts_for``, ``reads``, ``derive``) filter ``exchange = 'MCX'`` without a source, so rows there would
silently change existing panels. ``source`` = ``breeze_daily``, ``quality`` = ``broker`` (the broker's bar, not MCX's
official bhavcopy). ``release_at`` = our fetch time of the stored values (a broker bar has no publisher release
instant), ``first_seen_at`` = the first fetch of that bar: a re-fetch with the same values writes nothing; a changed
value replaces the row with ``release_at`` = the new fetch and keeps ``first_seen_at``.

Contracts: LIVE ones only (expiry ≥ the latest completed session; Breeze daily OI is unreliable for expired contracts),
picked like the VWAP30 proxy (``mcx_close.contracts_for``: from the latest ICICI master, per family the front month plus
the next months with OI > 0, at most ``MAX_EXPIRIES``; without a master, the computed GOLD / GOLDM fronts).
Window per contract: one with no stored bar gets ``backfill_from`` or ``FIRST_FETCH_DAYS`` back; a stored one the last
``REFRESH_SESSIONS`` sessions (from its last stored bar when that is older, so a gap after downtime closes), and also
``backfill_from`` when one is given. A bar dated after the latest completed session (today's, before the close) is
partial and never stored.

Breeze: read-only ``get_historical_data_v2(interval="1day")`` only, one call per contract, every call through the shared
budget ledger (``shared.breeze_budget``, caller ``data-service.gold_breeze_daily``), ≥ 1.2 s apart, capped per run
(leftovers are reported with their reason, never dropped silently; the stalest contracts go first the next run), and
stopped after three consecutive failures. Nothing here feeds the Decision Desk, the S1 shadow, a directional alert or a
ticket price.
"""
from __future__ import annotations

import math
import os
import re
import time as _time
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from gold import db, mcx_close
from gold.db import utcnow
from shared.logging import get_logger

logger = get_logger(__name__)

IST = ZoneInfo("Asia/Kolkata")
UTC = ZoneInfo("UTC")
TABLE = "gold_mcx_daily"
SOURCE = "breeze_daily"
QUALITY = "broker"
BUDGET_CALLER = "data-service.gold_breeze_daily"
METHOD = "get_historical_data_v2"
MIN_PACE_S = 1.2                                                    # the brief's floor between two Breeze calls
MAX_CALLS = int(os.getenv("GOLD_BREEZE_DAILY_MAX_CALLS", "15"))      # per run: 5 families × 3 live months
MAX_EXPIRIES = int(os.getenv("GOLD_BREEZE_DAILY_MAX_EXPIRIES", "3"))  # per family (front + live months with OI > 0)
PACE_S = max(MIN_PACE_S, float(os.getenv("GOLD_BREEZE_DAILY_PACE_S", str(MIN_PACE_S))))
FIRST_FETCH_DAYS = 180              # a contract with no stored bar: this many calendar days back (≈ 125 sessions, < 1,000 rows)
REFRESH_SESSIONS = 10               # a stored contract: re-read the last 10 sessions (the upsert replaces a changed bar)
MAX_CONSECUTIVE_FAILURES = 3
PRICE_FIELDS: tuple[str, ...] = ("open", "high", "low", "close")
DATE_KEYS: tuple[str, ...] = ("datetime", "date")                   # the bar's date; Breeze v2 sends "datetime"
VOLUME_KEYS: tuple[str, ...] = ("volume",)
OI_KEYS: tuple[str, ...] = ("open_interest", "oi")
EXPIRY_KEYS: tuple[str, ...] = ("expiry_date",)                     # "04-DEC-2026": a row of another contract is dropped
_ISO_DAY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_ZONED = re.compile(r"\d{2}:\d{2}(:\d{2}(\.\d+)?)?\s*(Z|[+-]\d{2}:?\d{2})$", re.IGNORECASE)   # a time with an explicit zone
_KEYS_LOGGED = False                                                # the first row's key names, once per process


class BreezeCallError(RuntimeError):
    """Breeze answered with ``Status != 200``, an ``Error`` field or a body that is not a ``Success`` list."""


# ── parsing (defensive: Breeze sends numbers as numbers or strings, dates with or without T/Z) ────────────────

def parse_day(raw: Any) -> date | None:
    """The calendar date of a Breeze stamp. Naive stamps are IST wall time ('2026-11-05 00:00:00', '2026-11-05'); a
    stamp with an explicit zone ('…T00:00:00.000Z', '…+05:30') is converted to IST first, which gives the same day for
    an IST-wall stamp suffixed Z and for a true UTC instant of IST midnight ('2026-11-04T18:30:00Z' → 5 Nov).
    Also '05-11-2026', '05-Nov-2026', '04-DEC-2026'. None when it is none of these."""
    if raw is None or isinstance(raw, float) and math.isnan(raw):
        return None
    if isinstance(raw, datetime):
        return raw.astimezone(IST).date() if raw.tzinfo else raw.date()
    if isinstance(raw, date):
        return raw
    s = str(raw).strip()
    if not s:
        return None
    m = _ISO_DAY.match(s)
    if m:
        if _ZONED.search(s):
            try:
                ts = pd.Timestamp(s)
            except (ValueError, TypeError):
                ts = None
            if ts is not None and ts.tzinfo is not None:
                return ts.tz_convert(IST).date()
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    head = s.split()[0].split("T")[0]
    for fmt in ("%d-%m-%Y", "%d-%b-%Y", "%d/%m/%Y"):          # %b matches 'DEC' / 'Dec' alike (strptime ignores case)
        try:
            return datetime.strptime(head, fmt).date()  # noqa: DTZ007 — a calendar date, no zone
        except ValueError:
            continue
    return None


def num(v: Any) -> float | None:
    """A finite float from a number or a numeric string ('139341.0', '1,39,341'); None for None / '' / '-' / NaN / junk."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
    else:
        s = str(v).strip().replace(",", "")
        if not s or s in ("-", "--", "null", "None", "NaN", "nan"):
            return None
        try:
            f = float(s)
        except ValueError:
            return None
    return f if math.isfinite(f) else None


def _price(v: Any) -> float | None:
    f = num(v)
    return f if f is not None and f > 0 else None              # a zero / negative price is "no trade", never a price


def _count(v: Any) -> int | None:
    f = num(v)
    return int(round(f)) if f is not None and f >= 0 else None


def _first(row: dict[str, Any], keys: Iterable[str]) -> Any:
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return None


def parse_rows(rows: Iterable[Any], expiry: date) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Breeze ``Success`` rows → bars {trade_date, open, high, low, close, volume, open_interest} sorted by date (one
    per date, the last wins) and the counts of what was dropped: ``no_date``, ``other_contract`` (its ``expiry_date``
    names another expiry), ``no_values`` (no price and no OI), ``not_a_row``. Unknown or missing fields → None."""
    out: dict[date, dict[str, Any]] = {}
    dropped = {"no_date": 0, "other_contract": 0, "no_values": 0, "not_a_row": 0}
    for r in rows:
        if not isinstance(r, dict):
            dropped["not_a_row"] += 1
            continue
        d = parse_day(_first(r, DATE_KEYS))
        if d is None:
            dropped["no_date"] += 1
            continue
        exp_raw = _first(r, EXPIRY_KEYS)
        exp = parse_day(exp_raw) if exp_raw is not None else None
        if exp is not None and exp != expiry:
            dropped["other_contract"] += 1
            continue
        bar = {"trade_date": d, **{k: _price(r.get(k)) for k in PRICE_FIELDS},
               "volume": _count(_first(r, VOLUME_KEYS)), "open_interest": _count(_first(r, OI_KEYS))}
        if all(bar[k] is None for k in PRICE_FIELDS) and bar["open_interest"] is None:
            dropped["no_values"] += 1
            continue
        out[d] = bar
    return [out[d] for d in sorted(out)], dropped


def _log_keys_once(rows: list[Any]) -> list[str] | None:
    """The first row's KEY NAMES (never values) — logged once per process so a live run shows what Breeze sent."""
    global _KEYS_LOGGED
    first = next((r for r in rows if isinstance(r, dict)), None)
    if first is None:
        return None
    keys = sorted(str(k) for k in first)
    if not _KEYS_LOGGED:
        _KEYS_LOGGED = True
        logger.info("gold.breeze_daily.payload_keys", keys=keys)
    return keys


# ── the call ────────────────────────────────────────────────────────────────────────────────────────────────

def request_kwargs(family: str, expiry: date, start: date, end: date) -> dict[str, str]:
    """The ``get_historical_data_v2`` arguments for one contract's daily bars in [start, end] (Breeze reads IST wall
    time; the same expiry / right / strike conventions as the 1-minute VWAP30 calls that work on MCX)."""
    return {"interval": "1day", "from_date": f"{start.isoformat()}T00:00:00.000Z", "to_date": f"{end.isoformat()}T23:59:00.000Z",
            "stock_code": mcx_close.BREEZE_CODE[family], "exchange_code": "MCX", "product_type": "futures",
            "expiry_date": f"{expiry.isoformat()}T06:00:00.000Z", "right": "others", "strike_price": "0"}


def fetch_daily(breeze: Any, family: str, expiry: date, start: date, end: date) -> list[Any]:
    """One read-only call through the budget ledger: the ``Success`` rows (``[]`` for an empty answer). Raises
    ``BudgetExceeded`` before the SDK runs past the cap and ``BreezeCallError`` on ``Status != 200``, an ``Error``
    field or a non-list body."""
    from shared.breeze_budget import ledger

    with ledger().guard(BUDGET_CALLER, METHOD):
        resp = breeze.get_historical_data_v2(**request_kwargs(family, expiry, start, end))
    if not isinstance(resp, dict):
        raise BreezeCallError(f"Breeze answered {type(resp).__name__}, not a JSON object")
    status, err = resp.get("Status"), resp.get("Error")
    if str(status) != "200" or (err not in (None, "", "null", "None")):
        raise BreezeCallError(f"Breeze status {status}: {str(err)[:160]}")
    rows = resp.get("Success")
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise BreezeCallError(f"Breeze Success is {type(rows).__name__}, not a list")
    return rows


# ── which contracts, which window ───────────────────────────────────────────────────────────────────────────

def live_contracts(store: Any, session: date, *, families: Iterable[str] | None = None,
                   max_expiries: int | None = None) -> list[tuple[str, date, int]]:
    """(family, expiry, month rank: 0 = front) of the LIVE contracts on ``session`` (expiry ≥ session)."""
    out: list[tuple[str, date, int]] = []
    rank: dict[str, int] = {}
    for fam, exp in mcx_close.contracts_for(store, session, families=families,
                                             max_expiries=max_expiries if max_expiries is not None else MAX_EXPIRIES):
        if exp < session:                                    # expired: Breeze daily OI is unreliable for old contracts
            continue
        out.append((fam, exp, rank.get(fam, 0)))
        rank[fam] = rank.get(fam, 0) + 1
    return out


def stored_through(store: Any) -> dict[tuple[str, date], date]:
    """{(family, expiry): the newest stored trade_date} of the Breeze daily bars."""
    df = db.query_df(store, f"SELECT family, expiry, MAX(trade_date) AS last FROM {TABLE} WHERE source = ? GROUP BY family, expiry",
                     [SOURCE])
    out: dict[tuple[str, date], date] = {}
    for r in df.itertuples(index=False):
        e, d = db.to_date(r.expiry), db.to_date(r.last)
        if e is not None and d is not None:
            out[(str(r.family), e)] = d
    return out


def refresh_start(last: date, sessions: int = REFRESH_SESSIONS) -> date:
    """The first of the last ``sessions`` MCX sessions ending at ``last``."""
    days = mcx_close.sessions_between(last - timedelta(days=7 * sessions // 5 + 14), last)
    return days[-sessions] if len(days) >= sessions else (days[0] if days else last - timedelta(days=14))


def window_start(last_stored: date | None, last: date, backfill_from: date | None) -> date:
    """Where one contract's fetch starts: ``backfill_from`` or ``FIRST_FETCH_DAYS`` back for a contract with no stored
    bar; else the last ``REFRESH_SESSIONS`` sessions, from its last stored bar when that is older (a gap closes), and
    from ``backfill_from`` when one is given and earlier."""
    if last_stored is None:
        return backfill_from or (last - timedelta(days=FIRST_FETCH_DAYS))
    start = min(refresh_start(last), last_stored)
    return min(start, backfill_from) if backfill_from else start


def existing(store: Any, family: str, expiry: date) -> dict[date, dict[str, Any]]:
    """{trade_date: stored row} of one contract (≤ a year of daily rows)."""
    df = db.query_df(store, f"""SELECT trade_date, open, high, low, close, volume, open_interest, release_at, first_seen_at
                                 FROM {TABLE} WHERE family = ? AND expiry = ? AND source = ?""", [family, expiry, SOURCE])
    out: dict[date, dict[str, Any]] = {}
    for rec in df.to_dict(orient="records"):
        d = db.to_date(rec["trade_date"])
        if d is not None:
            out[d] = rec
    return out


def _same(a: Any, b: Any) -> bool:
    fa, fb = num(a), num(b)
    if fa is None or fb is None:
        return fa is None and fb is None
    return abs(fa - fb) <= 1e-9 * max(1.0, abs(fa))


def rows_to_write(bars: list[dict[str, Any]], have: dict[date, dict[str, Any]], family: str, expiry: date, *,
                  now: datetime) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """The rows to upsert and the counts {new, revised, unchanged}: a bar identical to the stored one is not written; a
    changed bar replaces it with ``release_at`` = now and the stored ``first_seen_at``; a new bar gets both = now."""
    keep: list[dict[str, Any]] = []
    n = {"new": 0, "revised": 0, "unchanged": 0}
    for b in bars:
        prev = have.get(b["trade_date"])
        row = {**b, "family": family, "expiry": expiry, "source": SOURCE, "quality": QUALITY, "release_at": now, "first_seen_at": now}
        if prev is None:
            n["new"] += 1
        elif all(_same(b[k], prev.get(k)) for k in (*PRICE_FIELDS, "volume", "open_interest")):
            n["unchanged"] += 1
            continue
        else:
            n["revised"] += 1
            seen = prev.get("first_seen_at")
            if seen is not None and not pd.isna(seen):
                row["first_seen_at"] = pd.Timestamp(seen).to_pydatetime()
        keep.append(row)
    return keep, n


# ── the group ───────────────────────────────────────────────────────────────────────────────────────────────

def run(store: Any, get_breeze: Callable[[], Any] | None, *, now: datetime | None = None, backfill_from: date | None = None,
        families: Iterable[str] | None = None, max_calls: int | None = None, max_expiries: int | None = None,
        pace_s: float | None = None, sleep: Callable[[float], None] = _time.sleep) -> dict[str, Any]:
    """Fetch and store the daily bars of every LIVE contract (``live_contracts``) through the latest completed MCX
    session. Returns per-contract outcomes (``contracts``), the contracts not fetched with their reason
    (``not_fetched``: capped / budget / degraded / no_session), Breeze call counts, row counts (``inserted`` = new +
    revised; ``unchanged`` is written nowhere) and the key names of the first row Breeze sent (``payload_keys``)."""
    from shared.breeze_budget import BudgetExceeded

    now = now or utcnow()
    last = mcx_close.latest_completed_session(now)
    if last is None:
        return {"status": "ok", "inserted": 0, "planned": 0, "breeze_calls": 0, "reason": "no completed MCX session in two weeks"}
    today_ist = now.replace(tzinfo=UTC).astimezone(IST).date()
    fams = [f for f in (families or mcx_close.FAMILIES) if f in mcx_close.BREEZE_CODE]
    contracts = live_contracts(store, last, families=fams, max_expiries=max_expiries)
    through = stored_through(store)
    # the stalest first (never stored, then the oldest last bar), fronts first within that, GOLD → GUINEA: a capped run's
    # leftovers lead the next run, so no contract starves when more are live than the cap
    plan = sorted(contracts, key=lambda c: (through.get((c[0], c[1])) or date.min, c[2], mcx_close.FAMILY_PRIORITY.get(c[0], 9)))
    base: dict[str, Any] = {"session": last.isoformat(), "session_label": f"{last:%a %d %b}", "planned": len(plan), "breeze_calls": 0}
    if not plan:
        return {"status": "ok", "inserted": 0, **base, "contracts": [], "not_fetched": []}

    def key(c: tuple[str, date, int]) -> dict[str, Any]:
        return {"family": c[0], "expiry": c[1].isoformat(), "rank": c[2]}

    breeze = None
    if get_breeze is not None:
        try:
            breeze = get_breeze()
        except Exception:  # noqa: BLE001 — a broken session getter is "no session", never a crash
            breeze = None
    if breeze is None:
        return {"status": "no_session", "inserted": 0, **base, "contracts": [],
                "not_fetched": [{**key(c), "reason": "no_session"} for c in plan],
                "reason": "data-service has no live Breeze session (the ≈08:00 ICICI login connects it)"}
    cap = max_calls if max_calls is not None else MAX_CALLS
    pace = PACE_S if pace_s is None else pace_s
    outcomes: list[dict[str, Any]] = []
    not_fetched: list[dict[str, Any]] = []
    counts = {"new": 0, "revised": 0, "unchanged": 0}
    calls, fails, status = 0, 0, "ok"
    payload_keys: list[str] | None = None
    for n, c in enumerate(plan):
        fam, exp, _ = c
        if calls >= cap:
            status = "capped"
            not_fetched += [{**key(rest), "reason": "capped"} for rest in plan[n:]]
            break
        start = window_start(through.get((fam, exp)), last, backfill_from)
        if calls:
            sleep(pace)
        calls += 1
        try:
            raw = fetch_daily(breeze, fam, exp, start, today_ist)
        except BudgetExceeded as exc:
            calls -= 1                                            # refused before the SDK ran: ICICI did not count it
            status = "budget"
            outcomes.append({**key(c), "status": "budget", "reason": str(exc)[:160]})
            not_fetched += [{**key(rest), "reason": "budget"} for rest in plan[n:]]
            break
        except Exception as exc:  # noqa: BLE001 — one contract never stops the others (until three in a row fail)
            fails += 1
            outcomes.append({**key(c), "status": "error", "from": start.isoformat(), "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
            if fails >= MAX_CONSECUTIVE_FAILURES:
                status = "degraded"
                not_fetched += [{**key(rest), "reason": "degraded"} for rest in plan[n + 1:]]
                break
            continue
        fails = 0
        payload_keys = payload_keys or _log_keys_once(raw)
        bars, dropped = parse_rows(raw, exp)
        complete = [b for b in bars if b["trade_date"] <= last]
        partial = [b["trade_date"].isoformat() for b in bars if b["trade_date"] > last]
        rows, cnt = rows_to_write(complete, existing(store, fam, exp), fam, exp, now=now)
        if rows:
            db.upsert(store, TABLE, pd.DataFrame(rows))
        for k in counts:
            counts[k] += cnt[k]
        newest = complete[-1] if complete else None
        outcomes.append({**key(c), "status": "ok", "from": start.isoformat(), "rows_received": len(raw), "bars": len(complete),
                         **cnt, "skipped_partial": partial, "dropped": {k: v for k, v in dropped.items() if v},
                         "first": complete[0]["trade_date"].isoformat() if complete else None,
                         "last": newest["trade_date"].isoformat() if newest else None,
                         "last_close": newest["close"] if newest else None, "last_oi": newest["open_interest"] if newest else None})
    if status == "ok" and calls and outcomes and all(o["status"] == "error" for o in outcomes):
        status = "degraded"
    logger.info("gold.breeze_daily.run", calls=calls, status=status, new=counts["new"], revised=counts["revised"],
                not_fetched=len(not_fetched))
    return {**base, "status": status, "inserted": counts["new"] + counts["revised"], **counts, "breeze_calls": calls,
            "contracts": outcomes, "not_fetched": not_fetched, "payload_keys": payload_keys}

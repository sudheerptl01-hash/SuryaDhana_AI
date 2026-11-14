"""Portfolio positions and account balance via ICICI Breeze API.

Also the ICICI auto-login TOTP routes (GOLD program PLAN §g, the BRKR "Auto-login (TOTP)" panel):
GET /totp/status · POST /totp/preview · POST /totp · DELETE /totp — see the section at the end."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import stat
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query

from errors import degraded, fail
from pydantic import BaseModel

from icici_admin import (
    ICICI_ENV_KEYS,
    EnvValueError,
    build_login_url,
    classify_breeze_error,
    collect_backend_status,
    extract_session_token,
    persist_env_updates,
    probe_breeze_connection,
    propagate_runtime_config,
    public_error_kind,
    validate_env_updates,
)

router = APIRouter()

# ── Breeze probe cache ─────────────────────────────────────────────────────────
# probe_breeze_connection() performs a full Breeze login (generate_session) that
# takes 20-30 s. The UI polls /connection-status every 15 s from two tabs, so an
# uncached, event-loop-blocking probe froze ALL of ui-api (every other request then
# hit the browser's 10 s timeout). Cache the result and let only one probe run.
_PROBE_TTL_OK_S = 600.0     # a Breeze session lasts the trading day
_PROBE_TTL_FAIL_S = 20.0
# An expired token or rejected key cannot fix itself (pasting a new token clears this
# cache), so re-logging in every 20 s only hammers ICICI from this IP. Network failures
# are retried inside the probe and re-checked after a minute.
_PROBE_TTL_BY_KIND = {"session_expired": 900.0, "credentials": 900.0, "network": 60.0}
_probe_lock = threading.Lock()          # single-flight: one Breeze login at a time
_probe_cache: dict[str, Any] = {"key": None, "at": 0.0, "result": None}
_refreshing = threading.Event()


def _run_probe(key: tuple[str, str, str]) -> dict[str, Any]:
    with _probe_lock:
        result = probe_breeze_connection(*key)  # 20-40 s full Breeze login
        _probe_cache.update(key=key, at=time.monotonic(), result=result)
        return result


def _refresh_in_background(key: tuple[str, str, str]) -> None:
    if _refreshing.is_set():
        return
    _refreshing.set()

    def _work() -> None:
        try:
            _run_probe(key)
        finally:
            _refreshing.clear()

    threading.Thread(target=_work, name="breeze-probe-refresh", daemon=True).start()


def _cached_probe(api_key: str, api_secret: str, session_token: str) -> dict[str, Any]:
    """Stale-while-revalidate: a known result is returned at once (an expired one
    triggers a background refresh); only the very first call for a credential set
    waits for the login. The UI polls every 15 s and the Next.js proxy cuts requests
    at 30 s, so a 40 s login must never sit on the request path."""
    key = (api_key, api_secret, session_token)
    hit = _probe_cache
    if hit["key"] == key and hit["result"] is not None:
        res = hit["result"]
        ttl = _PROBE_TTL_OK_S if res.get("connected") else _PROBE_TTL_BY_KIND.get(res.get("error_kind"), _PROBE_TTL_FAIL_S)
        if time.monotonic() - hit["at"] >= ttl:
            _refresh_in_background(key)
        return hit["result"]
    return _run_probe(key)


def warm_breeze_probe() -> None:
    """Called at ui-api start-up: log in once in the background so the first
    /connection-status request is served from cache."""
    api_key = os.environ.get("ICICI_API_KEY", "")
    api_secret = os.environ.get("ICICI_API_SECRET", "")
    token = os.environ.get("ICICI_SESSION_TOKEN", "")
    if api_key and api_secret and token:
        _refresh_in_background((api_key, api_secret, token))
        # The holdings/funds endpoints use a separate cached Breeze client whose first
        # construction is also a full 20-40 s login — build it now, not on the first
        # Broker Account poll (which hit the UI's 10 s timeout).
        threading.Thread(target=_get_breeze_client, name="breeze-client-warmup", daemon=True).start()


def _invalidate_breeze_state() -> None:
    """Credentials/session changed: drop the cached client AND the cached probe."""
    _invalidate_breeze_client()
    with _probe_lock:
        _probe_cache.update(key=None, at=0.0, result=None)


def _invalidate_breeze_client() -> None:
    with _client_lock:
        _client_cache.update(key=None, client=None, error=None, error_kind=None, at=0.0)


_client_lock = threading.Lock()
_client_cache: dict[str, Any] = {"key": None, "client": None, "error": None, "error_kind": None,
                                 "at": 0.0, "fails": 0}
#: how long a FAILED login is remembered before another attempt is allowed, by consecutive failure count.
#: Each attempt is a metered generate_session, so a flat 60 s was up to 1,440 calls a day — 36% of the daily cap
#: spent discovering the same failure (measured: 126 attempts on 14 Nov with no session obtainable). A new token
#: changes the cache key and bypasses this entirely, so recovery is never delayed.
_CLIENT_RETRY_BACKOFF_S = (60.0, 120.0, 300.0, 900.0)
_CLIENT_RETRY_AFTER_FAIL_S = _CLIENT_RETRY_BACKOFF_S[0]   # kept: the first wait, and what older callers read


def _retry_wait_s(fails: int) -> float:
    """The wait before the next login attempt after `fails` consecutive failures (capped at the last step)."""
    if fails <= 0:
        return 0.0
    return _CLIENT_RETRY_BACKOFF_S[min(fails, len(_CLIENT_RETRY_BACKOFF_S)) - 1]


def _client_error_kind(err: str | None) -> str:
    """Public error kind ('expired' | 'network' | 'credentials' | 'unknown') of a _get_breeze_client() failure."""
    if not (os.environ.get("ICICI_API_KEY", "") and os.environ.get("ICICI_API_SECRET", "")):
        return "credentials"
    if not os.environ.get("ICICI_SESSION_TOKEN", ""):
        return "expired"
    c = _client_cache
    kind = c.get("error_kind") if err and c.get("error") == err else classify_breeze_error(err or "")[0]
    return public_error_kind(kind)


_NETWORK_HINT = "ICICI's API could not be reached (network); this is not a login problem. It is retried by itself."


def _client_error_hint(kind: str) -> str:
    return _NETWORK_HINT if kind == "network" else "Send /login on Telegram or use the Broker tab"


def _build_breeze_client(api_key: str, api_secret: str, session_token: str):
    """(client, None, None) or (None, user-facing error, classifier kind)."""
    try:
        import requests
        try:      # breeze_connect downloads ICICI's security master at import, with no timeout: use the cache
            from shared.breeze_cache import install as _breeze_cache_install
            _breeze_cache_install()
        except Exception:  # noqa: BLE001
            pass
        from breeze_connect import BreezeConnect

        # Apply connect timeout so startup never hangs
        _orig_get = requests.get
        def _get_with_timeout(url, **kw):
            kw.setdefault("timeout", (10, 20))
            return _orig_get(url, **kw)
        requests.get = _get_with_timeout  # type: ignore[assignment]

        from shared.breeze_budget import BudgetExceeded, ledger as _ledger
        try:
            breeze = BreezeConnect(api_key=api_key)
            # generate_session is itself an ICICI API call (customer details): it goes through the budget ledger like
            # every other Breeze call (PLAN §0.11); past the cap it is refused BEFORE the SDK runs.
            with _ledger().guard(BREEZE_LOGIN_CALLER, "generate_session"):
                breeze.generate_session(api_secret=api_secret, session_token=session_token)
        except BudgetExceeded as exc:
            return None, f"Breeze budget exhausted ({exc}); the broker book is retried after the cap resets", "budget"
        finally:
            requests.get = _orig_get

        return breeze, None, None
    except Exception as exc:
        kind, message = classify_breeze_error(str(exc))
        return None, message, kind


def _get_breeze_client():
    """Cached BreezeConnect client. Only a working client is kept; a failed login is
    retried after a minute (an lru_cache used to keep the failure until a token paste)."""
    api_key = os.environ.get("ICICI_API_KEY", "")
    api_secret = os.environ.get("ICICI_API_SECRET", "")
    raw_token = os.environ.get("ICICI_SESSION_TOKEN", "")
    if not (api_key and api_secret and raw_token):
        return None, "ICICI credentials not configured in .env"
    key = (api_key, api_secret, extract_session_token(raw_token))
    with _client_lock:
        c = _client_cache
        same_key = c["key"] == key
        # a NEW token (the 08:00 job, a paste, the session guard) changes the key: the backoff never delays it
        waited = time.monotonic() - c["at"]
        fresh_failure = bool(c["error"]) and same_key and waited < _retry_wait_s(int(c.get("fails") or 0))
        if same_key and (c["client"] is not None or fresh_failure):
            return c["client"], c["error"]
        client, err, kind = _build_breeze_client(*key)
        # count consecutive failures of THIS token so each attempt waits longer than the last; any success, or a
        # token change, resets the count to zero
        fails = 0 if (client is not None or not err) else (int(c.get("fails") or 0) + 1 if same_key else 1)
        c.update(key=key, client=client, error=err, error_kind=kind, at=time.monotonic(), fails=fails)
        return client, err


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val) if val not in (None, "", "NA") else default
    except (TypeError, ValueError):
        return default


def _extract_cash_balance(funds_resp: dict[str, Any]) -> float:
    success = funds_resp.get("Success")

    if isinstance(success, list):
        for item in success:
            if not isinstance(item, dict):
                continue
            limit_type = str(item.get("limit_type", "")).strip()
            if limit_type == "0":
                return _safe_float(item.get("net_limit"))
            for key in ("net_limit", "available_margin", "available_cash", "cash_limit", "cash"):
                if item.get(key) not in (None, "", "NA"):
                    return _safe_float(item.get(key))

    if isinstance(success, dict):
        for key in ("net_limit", "available_margin", "available_cash", "cash_limit", "cash"):
            if success.get(key) not in (None, "", "NA"):
                return _safe_float(success.get(key))

    return 0.0


BREEZE_BUDGET_CALLER = "ui-api.positions"
#: F12: the login has its own label and its own quota. It shared `ui-api.positions` with holdings, funds and
#: positions — so a runaway on any of those could exhaust that caller's share and the ledger would then refuse
#: the one call the terminal cannot do without. The login is cheap (tens a day) and must never be the thing
#: that gets squeezed out.
BREEZE_LOGIN_CALLER = "ui-api.login"


def _breeze_call(fn, *args, retries: int = 1, caller: str = BREEZE_BUDGET_CALLER, **kwargs):
    """Call a Breeze SDK method through the Breeze budget ledger (shared/breeze_budget.py, PLAN §0.11: every caller
    passes through it; a call past the owner's cap raises BudgetExceeded BEFORE the SDK runs), retrying once on a
    transient network error. Each attempt is one ledger entry — ICICI counts the failed ones too."""
    import time as _t

    from shared.breeze_budget import BudgetExceeded, ledger as _ledger
    for attempt in range(retries + 1):
        try:
            with _ledger().guard(caller, getattr(fn, "__name__", "breeze")):
                return fn(*args, **kwargs)
        except BudgetExceeded:
            raise
        except Exception:
            if attempt == retries:
                raise
            _t.sleep(1.0)


def budget_counters() -> dict[str, Any]:
    """The ledger's counters alone — no I/O, so the metering tests can read them without an event loop.

    Split out when the route became async for the holiday calendar: the tests that assert "this call was
    metered" care about the ledger, not about HTTP, and making them await an unrelated network fetch would
    have coupled a metering assertion to a calendar being reachable.
    """
    from shared.breeze_budget import ledger as _ledger
    return {**_ledger().status(), "badge": "arithmetic",
            "note": "100/min · 5,000/day documented ceiling; the cap is the budget (O-T6)"}


#: the NSE holiday set, fetched once a day — it changes once a year and this endpoint is polled every 60 s
_HOLIDAYS_CACHE: dict[str, Any] = {"day": None, "days": frozenset()}


async def _nse_holidays() -> frozenset:
    """Today's NSE holiday set from data-service, cached for the IST day. Empty on any failure, which degrades
    to a weekdays-only calendar — the same fallback data-service itself uses."""
    from datetime import datetime, timedelta, timezone
    today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date().isoformat()
    if _HOLIDAYS_CACHE["day"] == today:
        return _HOLIDAYS_CACHE["days"]
    days: frozenset = frozenset()
    try:
        from shared.http_client import get_json
        data_svc = os.environ.get("DATA_SERVICE_URL", "http://localhost:8001")   # same default as routers/markets.py
        payload = await get_json(f"{data_svc}/db/market-holidays", route="read") or {}
        days = frozenset(str(h.get("date")) for h in (payload.get("holidays") or []) if h.get("date"))
    except Exception:  # noqa: BLE001 — a missing calendar must never break the budget panel
        days = frozenset()
    _HOLIDAYS_CACHE.update(day=today, days=days)
    return days


@router.get("/breeze-budget")
async def breeze_budget_status() -> dict[str, Any]:
    """The Breeze budget ledger's counters (SYS / BRKR): calls today vs the owner's cap and ICICI's ceiling, by caller
    and by SDK method, refusals, the last call. No secrets, no URLs.

    `trading_day` is here because the BRKR chip needs it and this is the payload it already reads: its pre-open
    alarm must not fire on a holiday (F10-05 — the first version said "trading days only" in a comment and
    checked the weekday, which would have cried on Guru Nanak Jayanti). Unknown is reported as None, and the
    chip treats that as "assume a weekday", i.e. no worse than before.
    """
    from datetime import datetime, timedelta, timezone

    ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    holidays = await _nse_holidays()
    trading_day = ist.weekday() < 5 and ist.date().isoformat() not in holidays
    # F13-06: the chip also needs MCX's own window, because the two exchanges do not share a calendar — MCX
    # trades an evening session on some NSE holidays (24 Nov 2026: 17:00–23:55) and is fully shut on days NSE
    # is also shut (25 Dec 2026). The chip previously hardcoded "weekday and before 23:30", which went SILENT
    # over 23:30–23:55 — the window whose Breeze bars the MCX settlement of record is computed from — and
    # cried BRKR DOWN all evening on a full MCX closure. shared/mcx_specs models this; the UI cannot, so it
    # is served.
    # F14: `null` meant BOTH "MCX is shut today" and "the lookup raised", so a server-side failure would have
    # silenced the chip all evening — on the one evening the fix was written for. They are reported as
    # different things: a window, an explicit closure, or the field omitted entirely when we could not tell.
    mcx: dict[str, int] | None = None
    mcx_known = True
    try:
        from shared import mcx_specs
        win = mcx_specs.trading_window(ist.date())
        if win:
            mcx = {"open_hm": win[0].hour * 100 + win[0].minute, "close_hm": win[1].hour * 100 + win[1].minute}
    except Exception:  # noqa: BLE001 — a missing calendar must never break the budget panel
        mcx, mcx_known = None, False
    payload = {**budget_counters(), "trading_day": trading_day, "holidays_known": bool(holidays)}
    if mcx_known:                       # omitted, not null, when the calendar could not be read
        payload["mcx_window"] = mcx     # a dict = the window; None = MCX is shut today
    return payload


# ── Holdings, today's positions and funds (Breeze field names per the SDK docs) ──
# get_portfolio_holdings  → settled demat stock: average_price, current_market_price
# get_portfolio_positions → today's trades, including delivery buys that settle T+1
#                           (segment "equity", product_type "Cash"): average_price, ltp
# get_funds               → allocated_equity, block_by_trade_equity, unallocated_balance

_SECURITY_MASTER_URL = "https://directlink.icicidirect.com/MotherAppMaster/SecurityMaster.zip"
_SECURITY_MASTER_MAX_AGE_S = 7 * 86400
_isec_lock = threading.Lock()


def _security_master_dir() -> Path:
    base = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parents[3] / "data"))
    return base / "reference" / "icici_security_master"


@lru_cache(maxsize=1)
def isec_to_nse() -> dict[str, str]:
    """ICICI stock code → NSE symbol (RELIND → RELIANCE), from ICICI's security master.
    Downloaded at most once a week; an empty map (codes shown as-is) if unavailable."""
    import csv
    import io
    import zipfile
    import requests
    folder = _security_master_dir()
    path = folder / "NSEScripMaster.txt"
    with _isec_lock:
        try:
            if not path.exists() or time.time() - path.stat().st_mtime > _SECURITY_MASTER_MAX_AGE_S:
                r = requests.get(_SECURITY_MASTER_URL, timeout=(10, 60))
                r.raise_for_status()
                folder.mkdir(parents=True, exist_ok=True)
                path.write_bytes(zipfile.ZipFile(io.BytesIO(r.content)).read("NSEScripMaster.txt"))
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 — fall back to ICICI codes
            if not path.exists():
                return {}
            text = path.read_text(encoding="utf-8", errors="replace")
    rows = csv.DictReader(io.StringIO(text), skipinitialspace=True)
    return {r["ShortName"].strip(): r["ExchangeCode"].strip() for r in rows
            if r.get("Series") in ("EQ", "BE") and r.get("ShortName") and r.get("ExchangeCode")}


class BrokerSessionError(RuntimeError):
    """ICICI rejected the session (expired or replaced by a newer login)."""


_SESSION_DEAD = ("session", "expired", "invalid", "resource not available", "authenticat")


def _checked(resp: Any, what: str) -> Any:
    """`Success` of a Breeze response, or raise with ICICI's own error text."""
    if not isinstance(resp, dict):
        raise RuntimeError(f"{what}: unexpected response {str(resp)[:120]}")
    if resp.get("Status") == 200:
        return resp.get("Success") or []
    err = str(resp.get("Error") or resp)
    if any(s in err.lower() for s in _SESSION_DEAD):
        raise BrokerSessionError(err)
    if re.search(r"no data|not found|portfolio not defined|not created a portfolio|no record", err, re.I):
        return []                                    # ICICI's ways of saying "nothing held" (e.g. no settled demat stock yet)
    raise RuntimeError(f"{what}: {err}")


def _first(row: dict[str, Any], *keys: str) -> float:
    for k in keys:
        v = _safe_float(row.get(k), default=float("nan"))
        if v == v:                                   # not NaN
            return v
    return 0.0


_BOOK_CACHE: dict[str, Any] = {"at": 0.0, "key": None, "book": None}
_BOOK_TTL_S = 30.0


def read_book(breeze) -> dict[str, Any]:
    """Holdings + today's positions + funds, cached 30 s and shared by every page and scheduler job. Each uncached
    read is three Breeze calls, and Breeze caps API calls per day (12 Oct 2026: the quota ran out by evening)."""
    import time as _t
    hit = _BOOK_CACHE
    if hit["book"] is not None and hit["key"] == id(breeze) and _t.monotonic() - hit["at"] < _BOOK_TTL_S:
        return hit["book"]
    book = _read_book_uncached(breeze)
    hit.update(at=_t.monotonic(), key=id(breeze), book=book)
    return book


def _read_book_uncached(breeze) -> dict[str, Any]:
    """Every equity line the account holds (settled + bought today) and the cash position."""
    lines: dict[str, dict[str, Any]] = {}

    def add(code: str, qty: float, avg: float, ltp: float, source: str) -> None:
        line = lines.setdefault(code, {"symbol": code, "qty": 0.0, "cost": 0.0, "ltp": ltp, "sources": []})
        line["qty"] += qty
        line["cost"] += qty * avg
        line["ltp"] = ltp or line["ltp"]
        line["sources"].append(source)

    for h in _checked(_breeze_call(breeze.get_portfolio_holdings, exchange_code="NSE", from_date="", to_date="",
                                   stock_code="", portfolio_type=""), "holdings"):
        qty = _first(h, "quantity")
        if qty > 0:
            add(str(h.get("stock_code", "")), qty, _first(h, "average_price", "average_cost"),
                _first(h, "current_market_price", "ltp", "last_traded_price", "market_value_per_share"), "settled")

    positions_method = getattr(breeze, "get_portfolio_positions", None)
    if callable(positions_method):
        for r in _checked(_breeze_call(positions_method), "positions"):
            is_equity = str(r.get("segment", "")).lower() == "equity" or str(r.get("product_type", "")).lower() == "cash"
            qty = _first(r, "quantity")
            if is_equity and qty > 0 and str(r.get("action", "")).lower() == "buy":
                add(str(r.get("stock_code", "")), qty, _first(r, "average_price", "price"),
                    _first(r, "ltp", "price"), "today (settles T+1)")

    funds: dict[str, Any] = {}
    funds_method = getattr(breeze, "get_funds", None)
    if callable(funds_method):
        try:
            f = _checked(_breeze_call(funds_method), "funds")
        except BrokerSessionError:
            raise
        except Exception:
            # ICICI's funds call sometimes answers with a non-JSON page; holdings are fine, so keep the page up and
            # show the last good funds reading, marked stale
            f = None
            if _last_funds:
                funds = {**_last_funds, "stale": 1.0}
        if isinstance(f, dict):
            alloc, blocked = _first(f, "allocated_equity"), _first(f, "block_by_trade_equity")
            unalloc = _first(f, "unallocated_balance")
            # Delivery buys spend the equity allocation (ICICI does not show them as "blocked"),
            # so free cash = unallocated + what is left of the allocation after today's buys.
            spent_today = sum(ln["cost"] for ln in lines.values() if "today" in " ".join(ln["sources"]))
            funds = {"bank_balance": _first(f, "total_bank_balance"), "allocated_equity": alloc,
                     "blocked_equity": blocked, "unallocated": unalloc, "spent_today": round(spent_today, 2),
                     "cash_available": max(0.0, alloc - blocked - spent_today) + unalloc}
            _last_funds.clear()
            _last_funds.update(funds)
        elif f is not None:
            funds = {"cash_available": _extract_cash_balance({"Success": f})}

    names = isec_to_nse() if lines else {}
    rows = []
    for line in lines.values():
        qty, cost, ltp = line["qty"], line["cost"], line["ltp"] or (line["cost"] / line["qty"])
        value = qty * ltp
        rows.append({"symbol": names.get(line["symbol"], line["symbol"]), "icici_code": line["symbol"],
                     "quantity": int(qty), "buy_price": round(cost / qty, 2),
                     "current_price": round(ltp, 2), "invested": round(cost, 2), "current_value": round(value, 2),
                     "pnl": round(value - cost, 2), "pnl_percent": round((value - cost) / cost * 100, 2) if cost else 0.0,
                     "status": " + ".join(dict.fromkeys(line["sources"]))})
    rows.sort(key=lambda r: -r["current_value"])
    return {"rows": rows, "funds": funds}


def _session_lost(exc: Exception) -> dict[str, Any]:
    """ICICI ended the session: show it as disconnected, not as an empty account."""
    _invalidate_breeze_state()
    return {"connected": False, "needs_session_refresh": True, "error_kind": "expired",
            "error": ("ICICI says this session has ended (" + str(exc)[:80] + "). Each login through the ICICI "
                      "API link creates a new token and ends the previous one: log in once, paste that token.")}


_last_funds: dict[str, Any] = {}                     # last good get_funds reading (see read_book)

# ICICI's get_funds sometimes disagrees with itself between calls a few seconds apart (seen 12 Oct 2026: the same
# account read ₹13.40 L all "unallocated" on one call and ₹6.70 L unallocated + ₹6.70 L allocated-and-blocked on the
# next). Keep the recent readings so the UI can say so instead of silently flipping the number.
_cash_readings: list[tuple[float, float]] = []          # (monotonic time, cash_available)
_CASH_WINDOW_S = 600


def _note_cash(cash: float) -> list[float]:
    now = time.monotonic()
    _cash_readings.append((now, round(cash, 2)))
    del _cash_readings[:-50]
    return sorted({c for t, c in _cash_readings if now - t <= _CASH_WINDOW_S})


@router.get("/summary")
def get_position_summary():
    """Account balance, invested value and P&L from ICICI Breeze (settled holdings + today's buys)."""
    empty = {"total_capital_inr": 0, "cash_available_inr": 0, "invested_value_inr": 0, "num_open_positions": 0,
             "total_pnl_inr": 0, "total_pnl_pct": 0, "max_drawdown_pct": 0}
    breeze, err = _get_breeze_client()
    if err:
        kind = _client_error_kind(err)
        return degraded({"connected": False, "error": err, "error_kind": kind, **empty}, "state", err)
    try:
        book = read_book(breeze)
    except BrokerSessionError as exc:
        return {**_session_lost(exc), **empty}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"ICICI Breeze unavailable: {exc}") from exc
    invested = sum(r["invested"] for r in book["rows"])
    value = sum(r["current_value"] for r in book["rows"])
    cash = book["funds"].get("cash_available", 0.0)
    readings = _note_cash(cash)
    return {
        "cash_readings_10m": readings,                  # > 1 value = ICICI reported different free cash recently
        "connected": True,
        "total_capital_inr": round(cash + value, 2),
        "cash_available_inr": round(cash, 2),
        "invested_value_inr": round(invested, 2),
        "current_value_inr": round(value, 2),
        "num_open_positions": len(book["rows"]),
        "total_pnl_inr": round(value - invested, 2),
        "total_pnl_pct": round((value - invested) / invested * 100, 2) if invested else 0.0,
        "max_drawdown_pct": 0,
        "funds": {k: round(v, 2) for k, v in book["funds"].items()},
        "as_of": datetime.now().isoformat(),  # noqa: DTZ005,DTZ011 — local clock on purpose (the broker book's own stamp)
    }


def _last_holdings_path():
    from pathlib import Path
    for root in (Path(__file__).resolve().parents[3] / "data", Path("/app/data")):
        if root.is_dir():
            return root / "last_holdings.json"
    return Path("last_holdings.json")


EMPTY_CONFIRM_MINUTES = 30
CHECKED_STAMP_EVERY_S = 900      # an unchanged book re-stamps checked_at at most every 15 min (the file is not rewritten per read)


def _remember_holdings(rows: list[dict], now: datetime | None = None) -> None:
    """Keep the last successful holdings read: when the ICICI session lapses (every morning until a login), alerts,
    the wrap and 'your stocks' still know what you hold.

    An empty read does not replace a non-empty book straight away. On 14 Oct 2026 at 00:11 a session about to expire
    answered "success" with no holdings and wiped the saved book. An empty book is accepted only when a second empty
    read comes at least EMPTY_CONFIRM_MINUTES after the first, both between 09:00 and 23:00 (a real sell-out)."""
    import json
    now = now or datetime.now()  # noqa: DTZ005,DTZ011 — local clock on purpose (the broker book's own stamp)
    try:
        keep = [{k: r.get(k) for k in ("symbol", "quantity", "buy_price", "invested")} for r in rows]
        p = _last_holdings_path()
        saved = json.loads(p.read_text()) if p.exists() else {}
        old = saved.get("positions")
        if not keep and old:
            if not (9 <= now.hour < 23):
                return                                            # overnight blip: ignore
            first = saved.get("empty_since")
            if not first or (now - datetime.fromisoformat(first)).total_seconds() > 12 * 3600:
                p.write_text(json.dumps({**saved, "empty_since": now.isoformat(timespec="seconds")}))
                return                                            # first empty read: wait for a second one
            if (now - datetime.fromisoformat(first)).total_seconds() < EMPTY_CONFIRM_MINUTES * 60:
                return
        stamp = now.isoformat(timespec="seconds")
        if old != keep or saved.get("empty_since"):
            p.write_text(json.dumps({"as_of": stamp, "checked_at": stamp, "positions": keep}))
            return
        # unchanged book: ``as_of`` stays the last CHANGE; ``checked_at`` is the last read that confirmed it. RSK dated the
        # book by as_of and read "STALE · 14 OCT · 22 d" on 5 Nov although ICICI confirmed the same (empty) book that day.
        last = saved.get("checked_at")
        try:
            due = not last or (now - datetime.fromisoformat(last)).total_seconds() >= CHECKED_STAMP_EVERY_S
        except ValueError:
            due = True
        if due:
            p.write_text(json.dumps({**saved, "checked_at": stamp}))
    except (OSError, ValueError):
        pass


def _last_known() -> dict | None:
    import json
    try:
        return json.loads(_last_holdings_path().read_text())
    except (OSError, ValueError):
        return None


@router.get("/open-positions")
def get_open_positions():
    """Every stock held: settled demat holdings plus today's delivery buys (T+1). When ICICI is not connected the
    reply carries `last_known` (the last successful read, with its time) instead of pretending the account is empty."""
    breeze, err = _get_breeze_client()
    if err:
        kind = _client_error_kind(err)
        return degraded({"connected": False, "error": err, "error_kind": kind, "positions": [], "last_known": _last_known()},
                        "state", err, hint=_client_error_hint(kind))
    try:
        rows = read_book(breeze)["rows"]
    except BrokerSessionError as exc:
        return {**_session_lost(exc), "positions": [], "last_known": _last_known()}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"ICICI Breeze unavailable: {exc}") from exc
    _remember_holdings(rows)
    return {"connected": True, "positions": rows, "count": len(rows)}


@router.get("/trade-history")
def get_trade_history(limit: int = 50):
    """Recent order history from ICICI Breeze."""
    breeze, err = _get_breeze_client()
    if err:
        kind = _client_error_kind(err)
        return degraded({"connected": False, "error": err, "error_kind": kind, "trades": [], "total_trades": 0},
                        "state", err)

    from shared.breeze_budget import BudgetExceeded
    try:
        from datetime import date, timedelta
        today = date.today().isoformat()  # noqa: DTZ005,DTZ011 — local clock on purpose (the broker book's own stamp)
        week_ago = (date.today() - timedelta(days=7)).isoformat()  # noqa: DTZ005,DTZ011 — local clock on purpose (the broker book's own stamp)

        resp = _breeze_call(breeze.get_order_list, exchange_code="NSE", from_date=week_ago, to_date=today)   # the ledger (§0.11)

        trades = []
        if resp.get("Status") == 200:
            for o in (resp.get("Success") or [])[:limit]:
                trades.append({
                    "order_id": o.get("order_id"),
                    "symbol": o.get("stock_code"),
                    "side": o.get("action"),
                    "quantity": _safe_float(o.get("quantity")),
                    "price": _safe_float(o.get("average_price") or o.get("price")),
                    "status": o.get("status"),
                    "order_type": o.get("order_type"),
                    "timestamp": o.get("order_datetime"),
                })

        return {"connected": True, "trades": trades, "total_trades": len(trades)}

    except BudgetExceeded as exc:                          # refused BEFORE the SDK ran: say so, not "ICICI unavailable"
        msg = f"Breeze budget exhausted: {exc}"
        return degraded({"connected": True, "error": msg, "error_kind": "budget", "trades": [], "total_trades": 0},
                        "state", msg, hint="the cap resets at IST midnight (SYS › Breeze budget)")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"ICICI Breeze unavailable: {exc}") from exc


@router.get("/sector-exposure")
def get_sector_exposure():
    """Current allocation by NSE industry (shared/momentum industries list), from read_book()."""
    breeze, err = _get_breeze_client()
    if err:
        kind = _client_error_kind(err)
        return degraded({"connected": False, "error": err, "error_kind": kind, "sectors": {}}, "state", err)
    try:
        rows = read_book(breeze)["rows"]
    except BrokerSessionError as exc:
        return {**_session_lost(exc), "sectors": {}}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"ICICI Breeze unavailable: {exc}") from exc
    try:
        from shared.momentum import industries
        industry = industries()
    except Exception:  # noqa: BLE001 — reference list optional
        industry = {}
    sector_values: dict[str, float] = {}
    for r in rows:
        sec = industry.get(r["symbol"], "Unknown")
        sector_values[sec] = sector_values.get(sec, 0.0) + r["current_value"]
    total = sum(sector_values.values())
    sectors = {k: {"value": round(v, 2), "pct": round(v / total * 100, 1) if total else 0}
               for k, v in sorted(sector_values.items(), key=lambda x: -x[1])}
    return {"connected": True, "sectors": sectors, "total_invested": round(total, 2)}


class SessionTokenRequest(BaseModel):
    token: str
    # True when the token comes from a login that just happened (the 08:00 job, Telegram /login): ICICI ended the
    # previous session when it issued this token, so it is saved even if the check fails. A pasted token (BRKR)
    # leaves this False and is not saved when ICICI rejects it (the token in use is kept).
    fresh_login: bool = False


class ICICICredentialsRequest(BaseModel):
    api_key: str
    api_secret: str
    client_id: str | None = None
    password: str | None = None


def _runtime_status(session_token: str | None = None) -> dict[str, Any]:
    """ICICI state for BRKR/PORT/BRIEF and the desktop shell. BLOCKING when the probe cache has no answer (a 10-40 s
    Breeze login): call it through asyncio.to_thread, never on the event loop. ``session_token`` checks that token
    instead of the one in use.

    ``error_kind`` (additive, desktop review P4): null when connected, else 'expired' (ICICI refused the token: log
    in again), 'network' (ICICI's API unreachable: NOT a login problem), 'credentials' (API key/secret missing or
    rejected) or 'unknown'. ``needs_session_refresh`` keeps its old meaning (key and secret set, not connected) and
    is also true on a network failure: read ``error_kind`` first."""
    api_key = os.environ.get("ICICI_API_KEY", "")
    api_secret = os.environ.get("ICICI_API_SECRET", "")
    if session_token is None:
        session_token = os.environ.get("ICICI_SESSION_TOKEN", "")
    client_id = os.environ.get("ICICI_CLIENT_ID", "")
    password = os.environ.get("ICICI_PASSWORD", "")

    probe: dict[str, Any] = _cached_probe(api_key, api_secret, session_token) if (api_key and api_secret and session_token) else {
        "connected": False,
        "error_kind": "credentials" if not (api_key and api_secret) else "session_expired",
        "error": (
            "ICICI API key and secret are not configured."
            if not (api_key and api_secret)
            else "ICICI session token is missing or expired."
        ),
    }
    connected = bool(probe.get("connected"))

    return {
        "connected": connected,
        "error": probe.get("error"),
        "error_kind": None if connected else public_error_kind(probe.get("error_kind")),
        "account_name": probe.get("account_name"),
        "customer_id": probe.get("customer_id"),
        "has_api_key": bool(api_key),
        "has_api_secret": bool(api_secret),
        "has_session_token": bool(session_token),
        "has_client_id": bool(client_id),
        "has_password": bool(password),
        "needs_api_credentials": not (api_key and api_secret),
        "needs_session_refresh": bool(api_key and api_secret and not probe.get("connected")),
        "login_url": build_login_url(api_key),
        "token_hint": "Paste the full ICICI redirect URL or the raw apisession/session_token value.",
    }


@router.get("/connection-status")
async def get_connection_status():
    # Blocking broker I/O runs in a worker thread — never on the event loop.
    status = await asyncio.to_thread(_runtime_status)
    status["backend"] = await collect_backend_status()
    return status


def _refuse_unsafe_env(updates: dict[str, str]) -> None:
    """400 before anything changes when a value cannot be written to .env safely (a line break would add a
    new .env line, e.g. EXECUTION_LIVE_ALLOWED=1, applied at the next start). The value is never echoed."""
    try:
        validate_env_updates(updates, ICICI_ENV_KEYS)
    except EnvValueError as e:
        fail(400, "invalid", str(e),
             hint="paste the value again as one line, without surrounding quotes, line breaks or control characters")


def _apply_credentials(updates: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Blocking part of POST /credentials, run in a worker thread (P2): environment, .env, then a fresh Breeze check.
    _invalidate_breeze_state waits for an in-flight probe (it holds the probe lock for up to 40 s), so it is here too."""
    for key, value in updates.items():
        os.environ[key] = value
    persisted = persist_env_updates(updates, allowed_keys=ICICI_ENV_KEYS)
    _invalidate_breeze_state()
    return persisted, _runtime_status()


def _apply_session_token(session_token: str, fresh_login: bool = False) -> dict[str, Any]:
    """Blocking part of POST /session-token, run in a worker thread (P2).

    A pasted token is checked with Breeze first (a fresh check, never a cached answer) and replaces the token in use
    unless ICICI refused that token itself (error_kind 'expired'): a rejected paste no longer overwrites a token that
    may still work (P16). A network or API-key failure says nothing about the token, so it is saved as before.
    A ``fresh_login`` token is saved first and then checked, as every save was before: a kill mid-check loses
    nothing, and ICICI ended the previous session when it issued this one."""
    current = os.environ.get("ICICI_SESSION_TOKEN", "")
    persisted: dict[str, Any] | None = None
    if fresh_login:
        persisted = _save_session_token(session_token)
    with _probe_lock:
        previous_probe = dict(_probe_cache)
        _probe_cache.update(key=None, at=0.0, result=None)
    status = _runtime_status(session_token)
    rejected = (persisted is None and status["error_kind"] == "expired" and status["has_session_token"]
                and not status["needs_api_credentials"] and session_token != current)
    if rejected:
        with _probe_lock:          # keep showing the last known state of the token in use
            key = _probe_cache["key"]
            if key is None or key[2] == session_token:
                _probe_cache.update(previous_probe)
        return {"rejected": True, "status": status}
    if persisted is None:
        persisted = _save_session_token(session_token)
    return {"rejected": False, "status": status, "persisted": persisted}


def _save_session_token(session_token: str) -> dict[str, Any]:
    os.environ["ICICI_SESSION_TOKEN"] = session_token
    persisted = persist_env_updates({"ICICI_SESSION_TOKEN": session_token}, allowed_keys=ICICI_ENV_KEYS)
    _invalidate_breeze_client()    # the holdings client holds the old session (the probe cache is keyed by token)
    return persisted


@router.post("/credentials")
async def save_credentials(req: ICICICredentialsRequest):
    api_key = req.api_key.strip()
    api_secret = req.api_secret.strip()
    if not api_key or not api_secret:
        raise HTTPException(status_code=400, detail="Both ICICI API key and secret are required.")

    updates = {
        "ICICI_API_KEY": api_key,
        "ICICI_API_SECRET": api_secret,
    }
    if req.client_id is not None:
        updates["ICICI_CLIENT_ID"] = req.client_id.strip()
    if req.password is not None:
        updates["ICICI_PASSWORD"] = req.password.strip()
    _refuse_unsafe_env(updates)              # before os.environ or .env change

    # .env write + the 10-40 s Breeze check: in a worker thread, so ui-api keeps answering meanwhile (P2)
    persisted, status = await asyncio.to_thread(_apply_credentials, updates)
    if os.environ.get("ICICI_SESSION_TOKEN", "").strip():
        backend = await propagate_runtime_config(
            api_key=os.environ.get("ICICI_API_KEY", ""),
            api_secret=os.environ.get("ICICI_API_SECRET", ""),
            session_token=os.environ.get("ICICI_SESSION_TOKEN", ""),
        )
    else:
        backend = await collect_backend_status()
    return {
        "saved": True,
        "persisted": persisted["persisted"],
        "env_path": persisted["path"],
        "persisted_reason": persisted.get("reason"),       # why .env was not written (key names only), else None
        "status": status,
        "backend": backend,
    }


@router.post("/session-token")
async def update_session_token(req: SessionTokenRequest):
    """Check a new ICICI Breeze session token, save it (os.environ + .env) and reconnect the services.

    A pasted token that ICICI rejects is NOT saved: the reply says ``kept_previous_token: true``. ``error_kind`` as
    in /connection-status."""
    token = req.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Token cannot be empty")

    session_token = extract_session_token(token)
    _refuse_unsafe_env({"ICICI_SESSION_TOKEN": session_token})    # before os.environ or .env change

    # The Breeze check takes 10-40 s: in a worker thread, never on the event loop (P2)
    result = await asyncio.to_thread(_apply_session_token, session_token, req.fresh_login)
    status = result["status"]
    if result["rejected"]:
        return {
            "connected": False,
            "error": f"{status['error']} This token was not saved; the token in use was kept.",
            "error_kind": status["error_kind"],
            "persisted": False,
            "env_path": None,
            "kept_previous_token": True,
            "status": status,
        }
    persisted = result["persisted"]
    if not status["connected"]:
        return {
            "connected": False,
            "error": status["error"],
            "error_kind": status["error_kind"],
            "persisted": persisted["persisted"],
            "env_path": persisted["path"],
            "persisted_reason": persisted.get("reason"),
            "status": status,
        }

    backend_sync = await propagate_runtime_config(
        api_key=os.environ.get("ICICI_API_KEY", ""),
        api_secret=os.environ.get("ICICI_API_SECRET", ""),
        session_token=session_token,
    )
    return {
        "connected": True,
        "error_kind": None,
        "message": "Session token updated and Breeze reconnected.",
        "persisted": persisted["persisted"],
        "env_path": persisted["path"],
        "persisted_reason": persisted.get("reason"),       # why .env was not written (key names only), else None
        "status": status,
        "backend": backend_sync,
    }


# (dead route /refresh-session removed — Bloomberg program F1.5; session refresh is owned
#  by the 08:00 login job + Telegram /login, which update .env and invalidate the cache)


# ══════════════════════════════════════════════════════════════════════════════
# ICICI auto-login: the TOTP secret (GOLD program PLAN §g; G-LOGIN §4). The 08:00 job (scripts/daily_session_refresh.py)
# already does a zero-touch RFC 6238 login once ICICI_TOTP_SECRET exists in .env or the macOS Keychain; these routes let
# the BRKR panel check that state, preview the code a pasted key produces (so the owner can compare it with the phone),
# save the key through the guarded .env writer only after a matching confirmation code, and remove it.
#
# Secrecy rules (binding): the secret is never echoed in any response, never logged, never put in a query string; every
# 400 carries a fixed message that cannot contain the input; `preview.code` is the only derived value that leaves the
# process (it is what the phone shows anyway). Blocking work (the Keychain probe, pgrep, file reads, the .env write) runs
# off the event loop through asyncio.to_thread.
# ══════════════════════════════════════════════════════════════════════════════

for _p in (Path(__file__).resolve().parents[3], Path(__file__).resolve().parents[1]):
    if (_p / "shared").is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from shared.icici_login import KEYCHAIN_SERVICE, TotpSpec, parse_totp_secret, totp as _totp_code  # noqa: E402

_IST = ZoneInfo("Asia/Kolkata")
_totp_log = logging.getLogger("ui-api.icici_totp")
TOTP_KEY = "ICICI_TOTP_SECRET"
TOTP_BAD_SECRET = "secret is not a usable TOTP key: paste the base32 setup key (A–Z, 2–7) or the otpauth:// URI"
TOTP_BAD_CONFIRM = "confirmation code does not match the current or previous 30-second window: compare with the phone"
LOGIN_SCRIPT = "daily_session_refresh.py"
OTP_REQUEST_FRESH_S = 360.0
_totp_clock = time.time            # monkeypatched by tests (RFC 6238 vectors at a frozen clock)


class TotpPreviewRequest(BaseModel):
    secret: str


class TotpSaveRequest(BaseModel):
    secret: str
    confirm_code: str


def _repo_root() -> Path:
    env = os.environ.get("UI_API_ENV_FILE", "").strip()
    if env:
        return Path(env).resolve().parent
    return Path(__file__).resolve().parents[3]


def _spec_from(value: str) -> TotpSpec:
    """parse_totp_secret with every failure folded into ONE fixed message (the parser's own messages are safe too,
    but a fixed one can never echo an input by construction)."""
    try:
        spec = parse_totp_secret(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(TOTP_BAD_SECRET) from exc
    if not 6 <= spec.digits <= 8 or not 15 <= spec.period <= 120:
        raise ValueError(TOTP_BAD_SECRET)
    return spec


def _bare_base32(spec: TotpSpec) -> str:
    import base64
    return base64.b32encode(spec.secret).decode("ascii").rstrip("=")


def _code_now(spec: TotpSpec, at: float | None = None) -> tuple[str, int]:
    """(code, seconds_left) for the window that contains `at` (default: now)."""
    now = _totp_clock() if at is None else at
    return _totp_code(spec, now), int(spec.period - (now % spec.period))


def _keychain_has_totp() -> bool | None:
    """True/False on macOS (an item exists / does not), None elsewhere. Attributes only: never `-w`. The return code
    is logged (M3: 36/51 = locked or denied, 44 = not found), never any value."""
    if sys.platform != "darwin":
        return None
    try:
        r = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", TOTP_KEY],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        _totp_log.warning(json.dumps({"event": "totp_keychain_probe_failed", "error": type(exc).__name__}))
        return False
    if r.returncode not in (0, 44):
        _totp_log.warning(json.dumps({"event": "totp_keychain_probe", "rc": r.returncode, "note": "locked or denied?"}))
    return r.returncode == 0


def _env_secret() -> str:
    return (os.environ.get(TOTP_KEY) or "").strip()


def _env_mode() -> str | None:
    from icici_admin import find_env_file
    path = find_env_file()
    if path is None:
        return None
    try:
        return format(stat.S_IMODE(path.stat().st_mode), "04o")
    except OSError:
        return None


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _last_login(root: Path) -> dict[str, Any] | None:
    d = _read_json(root / ".session_cache.json")
    if not d:
        return None
    return {"at": d.get("at"), "status": d.get("status"), "detail": d.get("detail")}


def _login_running() -> bool:
    """A daily_session_refresh.py process is alive (the 08:00 job, Telegram /login or the HTTP trigger)."""
    try:
        r = subprocess.run(["/usr/bin/pgrep", "-f", LOGIN_SCRIPT], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0 and bool(r.stdout.strip())


def _otp_pending(root: Path) -> bool:
    """The login script asked for an SMS OTP on Telegram less than OTP_REQUEST_FRESH_S ago."""
    p = root / "data" / "icici_otp_request.json"
    try:
        return time.time() - p.stat().st_mtime < OTP_REQUEST_FRESH_S
    except OSError:
        return False


def _next_run_ist(now: datetime | None = None) -> str | None:
    """The next 08:00 IST on a weekday (the job's CronTrigger), or None when auto-login is off."""
    if os.environ.get("ICICI_AUTO_LOGIN", "1").strip() != "1":
        return None
    now = (now or datetime.now(_IST)).astimezone(_IST)
    nxt = now.replace(hour=8, minute=0, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt.isoformat(timespec="minutes")


def _blocks(root: Path) -> dict[str, bool]:
    return {"credentials": (root / ".icici_login_block.json").is_file(),
            "totp": (root / ".icici_totp_block.json").is_file()}


def totp_status(reveal: bool = False) -> dict[str, Any]:
    """BLOCKING (Keychain probe, pgrep, files): call through asyncio.to_thread. Never includes the secret; with
    `reveal` the current code and its seconds left, computed here, so the panel can show "current code 482 913 · 17 s"."""
    root = _repo_root()
    env_value = _env_secret()
    keychain = None if env_value else _keychain_has_totp()
    source = "env" if env_value else ("keychain" if keychain else None)
    out: dict[str, Any] = {
        "configured": source is not None, "source": source, "keychain_present": keychain,
        "env_mode": _env_mode(), "env_mode_ok": _env_mode() in (None, "0600"),
        "auto_login_enabled": os.environ.get("ICICI_AUTO_LOGIN", "1").strip() == "1",
        "login_running": _login_running(), "otp_pending": _otp_pending(root),
        "last_login": _last_login(root), "next_run_ist": _next_run_ist(), "block": _blocks(root),
        "keychain_hint": f"security add-generic-password -U -s {KEYCHAIN_SERVICE} -a {TOTP_KEY} -w",
        "force_supported": True,   # POST /api/telemetry/icici-refresh {force:true} → controller ?force=1 (PLAN §g, owner Q5)
    }
    # validate the stored key on EVERY status read (never echoed, no code computed unless `reveal`): 'configured' only
    # says something is stored. 5 Nov: a 10-character non-base32 value read "TOTP CONFIGURED" for five hours and the
    # forced login stopped at "TOTP secret is not valid base32"; the 08:00 run would have done the same.
    value = env_value or None
    if not value and source == "keychain":
        from shared.icici_login import read_secret
        value = read_secret(TOTP_KEY)
    spec = None
    if value:
        try:
            spec = _spec_from(value)
        except ValueError:
            out["secret_problem"] = TOTP_BAD_SECRET
    out["usable"] = None if not value else spec is not None
    if reveal:
        out["code"], out["seconds_left"] = _code_now(spec) if spec is not None else (None, None)
    return out


@router.get("/totp/status")
async def get_totp_status(reveal: int = Query(0, ge=0, le=1)) -> dict[str, Any]:
    return await asyncio.to_thread(totp_status, bool(reveal))


@router.post("/totp/preview")
async def totp_preview(req: TotpPreviewRequest) -> dict[str, Any]:
    """The code a pasted key produces right now. Stores nothing, logs nothing; a bad key is a 400 whose body never
    contains the input."""
    try:
        spec = _spec_from(req.secret)
    except ValueError:
        fail(400, "invalid", TOTP_BAD_SECRET)
    code, left = _code_now(spec)
    return {"valid": True, "digits": spec.digits, "period": spec.period, "algorithm": spec.algorithm,
            "length": len(_bare_base32(spec)), "code": code, "seconds_left": left}


def _save_totp(b32: str) -> dict[str, Any]:
    """Blocking: the guarded .env writer (validated, atomic, mode preserved) then the process environment."""
    try:
        persisted = persist_env_updates({TOTP_KEY: b32}, allowed_keys=ICICI_ENV_KEYS)
    except EnvValueError as e:
        return {"saved": False, "persisted": False, "reason": str(e)}
    os.environ[TOTP_KEY] = b32
    mode = _env_mode()
    _totp_log.info(json.dumps({"event": "totp_secret_saved", "persisted": persisted.get("persisted"), "env_mode": mode}))
    return {"saved": True, "persisted": persisted.get("persisted", False), "persisted_reason": persisted.get("reason"),
            "env_path": persisted.get("path"), "source": "env", "env_mode": mode,
            "env_mode_warning": None if mode in (None, "0600") else f".env is {mode} — run: chmod 600 .env",
            "keychain_present": _keychain_has_totp()}


@router.post("/totp")
async def totp_save(req: TotpSaveRequest) -> dict[str, Any]:
    """Save the key to .env (allowlisted key, guarded writer) — only when `confirm_code` equals the code of the current
    or the previous window, which proves the owner compared it with the phone. Normalised to bare base32."""
    try:
        spec = _spec_from(req.secret)
    except ValueError:
        fail(400, "invalid", TOTP_BAD_SECRET)
    confirm = re.sub(r"\s", "", req.confirm_code or "")
    now = _totp_clock()
    accepted = {_totp_code(spec, now), _totp_code(spec, now - spec.period)}
    if confirm not in accepted:
        fail(400, "invalid", TOTP_BAD_CONFIRM, hint="wait for one rollover on the phone, then retype the six digits")
    result = await asyncio.to_thread(_save_totp, _bare_base32(spec))
    if not result.get("saved"):
        fail(400, "invalid", result.get("reason") or "refused")
    return result


def _clear_totp() -> dict[str, Any]:
    try:
        persisted = persist_env_updates({TOTP_KEY: ""}, allowed_keys=ICICI_ENV_KEYS)
    except EnvValueError as e:
        return {"cleared": False, "reason": str(e)}
    os.environ.pop(TOTP_KEY, None)
    keychain = _keychain_has_totp()
    _totp_log.info(json.dumps({"event": "totp_secret_cleared", "persisted": persisted.get("persisted"),
                               "keychain_still_present": bool(keychain)}))
    return {"cleared": True, "persisted": persisted.get("persisted", False), "persisted_reason": persisted.get("reason"),
            "keychain_still_present": bool(keychain),
            "keychain_hint": (f"security delete-generic-password -s {KEYCHAIN_SERVICE} -a {TOTP_KEY}" if keychain else None)}


@router.delete("/totp")
async def totp_delete() -> dict[str, Any]:
    """Disable auto-login: write `ICICI_TOTP_SECRET=` through the guarded writer. A Keychain copy is reported, never
    deleted by ui-api (the owner runs the one-liner)."""
    result = await asyncio.to_thread(_clear_totp)
    if not result.get("cleared"):
        fail(400, "invalid", result.get("reason") or "refused")
    return result

"""The 15-minute intraday pilot (PLAN 1.1 ``iv_intraday``; R-IV §5): ICICI Breeze ``get_option_chain_quotes`` for NIFTY +
BANKNIFTY (near + next expiry, both sides) plus the owner's F&O watchlist (near expiry), IV from the bid/ask mid on the
parity forward of the same snapshot, raw rows to parquet parts under ``data/ticks/chain/<date>/`` (bounded like the tick
store) and the derived rows to ``iv_intraday``.

Hard rules (PLAN §0.9 / §0.11): read-only Breeze methods only; every call acquired on the budget ledger first (B3's
``shared/breeze_budget.py``: ``ledger().decide`` as the dry run, ``ledger().guard(caller, method)`` around each SDK call,
``BudgetExceeded`` ends the tick; ``budget=None`` → the snapshot is SKIPPED, never run unmetered); skipped when the session is
not live or the clock is outside 09:20–15:30 IST; NSE option-chain-v3 beside Breeze only on O-T7 (default: off; the
``nse_iv`` column stays NULL). The Breeze chain carries no IV or Greeks (verified 4 Nov 2026): ours is computed here.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from data_health import db
from fo_iv import black76 as b76
from fo_iv.black76 import MODEL_VERSION
from fo_iv.iv_eod import INDEX_SYMBOLS, rate_for
from fo_iv.schema import CASTS, COLUMNS
from shared.logging import get_logger

logger = get_logger(__name__)

IST = ZoneInfo("Asia/Kolkata")
WINDOW = (time(9, 20), time(15, 30))
PILOT_INDICES: tuple[str, ...] = ("NIFTY", "BANKNIFTY")
DEFAULT_MAX_CALLS_PER_SNAPSHOT = 30            # ≤ 30/min (PLAN 1.1)
DEFAULT_DAILY_CAP = 800                        # ≤ 800/day
CALLER = "iv_intraday"                         # the ledger's per-caller quota name (B3 BREEZE_BUDGET_QUOTAS)
METHOD = "get_option_chain_quotes"
SOURCE = "breeze"
PARQUET_COLUMNS = ["ts", "symbol", "expiry", "right", "strike", "ltp", "bid", "ask", "bid_qty", "ask_qty", "oi", "chnge_oi", "volume", "spot", "ltt"]


@dataclass
class Snapshot:
    ts: datetime                          # UTC-naive
    symbol: str
    expiry: date
    calls: list[dict[str, Any]] = field(default_factory=list)
    puts: list[dict[str, Any]] = field(default_factory=list)


def in_window(now_ist: datetime) -> bool:
    return now_ist.weekday() < 5 and WINDOW[0] <= now_ist.time() <= WINDOW[1]


def breeze_expiry(d: date) -> str:
    return f"{d.isoformat()}T06:00:00.000Z"


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if np.isfinite(x) and x > 0 else None


def normalise_rows(rows: Iterable[dict[str, Any]], ts: datetime, symbol: str, expiry: date, right: str) -> list[dict[str, Any]]:
    out = []
    for r in rows or []:
        strike = _f(r.get("strike_price"))
        if strike is None:
            continue
        out.append({"ts": ts, "symbol": symbol, "expiry": expiry, "right": right, "strike": strike, "ltp": _f(r.get("ltp")),
                    "bid": _f(r.get("best_bid_price")), "ask": _f(r.get("best_offer_price")),
                    "bid_qty": _f(r.get("best_bid_quantity")), "ask_qty": _f(r.get("best_offer_quantity")),
                    "oi": _f(r.get("open_interest")), "chnge_oi": None if r.get("chnge_oi") is None else float(r.get("chnge_oi") or 0),
                    "volume": _f(r.get("total_quantity_traded")), "spot": _f(r.get("spot_price")), "ltt": str(r.get("ltt") or "")})
    return out


def mid_of(row: dict[str, Any]) -> float | None:
    b, a = row.get("bid"), row.get("ask")
    if b and a and a >= b:
        return (a + b) / 2.0
    return None


def derive(snapshot: Snapshot, day: date, r: float, *, now: datetime) -> list[dict[str, Any]]:
    """Per strike IV from the mid on the parity forward of this snapshot (OTM wings + 3 % ITM, as the EOD method)."""
    dte = (snapshot.expiry - day).days
    if dte <= 0:
        return []
    t = dte / 365.0
    ce = {row["strike"]: row for row in snapshot.calls}
    pe = {row["strike"]: row for row in snapshot.puts}
    ks = sorted(set(ce) & set(pe))
    spot = next((row["spot"] for row in [*snapshot.calls, *snapshot.puts] if row.get("spot")), None)
    if not ks or spot is None:
        return []
    fwd = None
    for k in sorted(ks, key=lambda k: abs(k - spot))[:3]:
        c, p = mid_of(ce[k]), mid_of(pe[k])
        if c is not None and p is not None:
            fwd = b76.forward_from_parity(k, c, p, t, r)
            break
    if fwd is None:
        fwd = spot * math.exp(r * t)
    out = []
    for k in ks:
        for right, row, call in (("CE", ce[k], True), ("PE", pe[k], False)):
            m = mid_of(row)
            allowed = (k >= fwd * (1 - b76.ITM_BAND)) if call else (k <= fwd * (1 + b76.ITM_BAND))
            iv = b76.implied_vol(m, fwd, k, t, call, r) if (m is not None and allowed) else None
            out.append({"ts": snapshot.ts, "symbol": snapshot.symbol, "expiry": snapshot.expiry, "strike": float(k), "opt_type": right, "mid": m,
                        "iv": round(iv * 100, 4) if iv else None, "nse_iv": None, "oi": row.get("oi"), "forward": round(fwd, 4), "spot": spot,
                        "source": SOURCE, "model_version": MODEL_VERSION, "r": r, "first_seen_at": now})
    return out


def write_parquet_part(root: Path, day: date, rows: list[dict[str, Any]]) -> Path | None:
    if not rows:
        return None
    import pyarrow as pa
    import pyarrow.parquet as pq

    day_dir = root / day.isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    n = max((int(p.stem.split("-")[1]) for p in day_dir.glob("part-*.parquet")), default=-1) + 1
    final = day_dir / f"part-{n:04d}.parquet"
    tmp = day_dir / f".part-{n:04d}.parquet.tmp"
    df = pd.DataFrame(rows, columns=PARQUET_COLUMNS)
    df["ts"] = pd.to_datetime(df["ts"])
    df["expiry"] = df["expiry"].astype(str)
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), tmp)
    tmp.replace(final)
    return final


def pilot_targets(store: Any, *, watchlist: Iterable[str] = (), as_of: date | None = None) -> list[tuple[str, date]]:
    """(symbol, expiry) pairs from the stored expiry table: near + next for the indices, near for the watchlist. No NSE call."""
    if not db.table_exists(store, "iv_expiry_daily"):
        return []
    day = as_of or db.to_date(db.scalar(store, "SELECT MAX(date) FROM iv_expiry_daily"))
    if day is None:
        return []
    out: list[tuple[str, date]] = []
    for sym, n in [*((s, 2) for s in PILOT_INDICES), *((s, 1) for s in watchlist if s not in PILOT_INDICES)]:
        df = db.query_df(store, "SELECT expiry FROM iv_expiry_daily WHERE symbol = ? AND date = ? AND dte >= 1 ORDER BY expiry LIMIT ?", [sym, day, n])
        out.extend((sym, d) for d in (db.to_date(v) for v in df["expiry"]) if d)
    return out


def snapshot(store: Any, breeze: Any, budget: Any, *, now: datetime | None = None, watchlist: Iterable[str] = (), parquet_root: Path | None = None,
             max_calls: int = DEFAULT_MAX_CALLS_PER_SNAPSHOT, force_window: bool = False, is_live: Callable[[], bool] | None = None) -> dict[str, Any]:
    """One tick of the pilot. Returns ``{"status": skipped|ok, "reason"?, "calls", "rows", ...}``; never raises on a bad chain."""
    now = now or db.utcnow()
    now_ist = now.replace(tzinfo=ZoneInfo("UTC")).astimezone(IST)
    day = now_ist.date()
    if budget is None:                       # checked before anything else: Breeze is never called unmetered
        return {"status": "skipped", "reason": "no budget ledger (shared/breeze_budget.py not deployed): Breeze is never called unmetered", "calls": 0}
    if breeze is None or (is_live is not None and not is_live()):
        return {"status": "skipped", "reason": "Breeze session not live", "calls": 0}
    if not force_window and not in_window(now_ist):
        return {"status": "skipped", "reason": f"outside 09:20–15:30 IST ({now_ist.strftime('%a %H:%M')})", "calls": 0}
    targets = pilot_targets(store, watchlist=watchlist, as_of=None)
    if not targets:
        return {"status": "skipped", "reason": "no stored expiries (run iv_eod first)", "calls": 0}
    need = 2 * len(targets)
    if need > max_calls:
        targets = targets[: max_calls // 2]
        need = 2 * len(targets)
    first = budget.decide(CALLER, METHOD)                      # dry run: the ledger's reason when the tick cannot start
    if not getattr(first, "allowed", False):
        return {"status": "skipped", "reason": f"budget ledger refused: {getattr(first, 'reason', 'no')}", "calls": 0,
                "retry_after_s": getattr(first, "retry_after_s", None)}
    r, _ = rate_for(store, day)
    raw: list[dict[str, Any]] = []
    derived: list[dict[str, Any]] = []
    calls, refused, errors = 0, 0, []
    stop = False
    for sym, expiry in targets:
        if stop:
            break
        snap = Snapshot(ts=now, symbol=sym, expiry=expiry)
        for right, bucket in (("call", snap.calls), ("put", snap.puts)):
            try:
                with budget.guard(CALLER, METHOD):             # acquires or raises before the SDK method runs (PLAN §0.11)
                    resp = breeze.get_option_chain_quotes(stock_code=sym, exchange_code="NFO", product_type="options",
                                                          expiry_date=breeze_expiry(expiry), right=right)
                calls += 1
                rows = resp.get("Success") if isinstance(resp, dict) else resp
                bucket.extend(normalise_rows(rows or [], now, sym, expiry, "CE" if right == "call" else "PE"))
            except Exception as exc:  # noqa: BLE001 — one leg failing never stops the snapshot; a refusal ends it
                if type(exc).__name__ == "BudgetExceeded":
                    refused += 1
                    errors.append(f"{sym} {expiry} {right}: budget refused ({exc})")
                    stop = True
                    break
                calls += 1
                errors.append(f"{sym} {expiry} {right}: {type(exc).__name__}")
        raw.extend(snap.calls)
        raw.extend(snap.puts)
        derived.extend(derive(snap, day, r, now=now))
    part = write_parquet_part(parquet_root, day, raw) if parquet_root is not None else None
    n = db.upsert(store, "iv_intraday", pd.DataFrame(derived), COLUMNS["iv_intraday"], CASTS["iv_intraday"]) if derived else 0
    logger.info("fo_iv.intraday", calls=calls, rows=n, targets=len(targets), errors=len(errors))
    return {"status": "ok" if not refused else "partial", "calls": calls, "refused": refused, "rows": n, "raw_rows": len(raw),
            "targets": [(s, e.isoformat()) for s, e in targets], "parquet": str(part) if part else None, "errors": errors[:10], "ts": db.iso_utc(now)}


def is_index(symbol: str) -> bool:
    return symbol in INDEX_SYMBOLS

"""The intraday OI / IV tape (Terminal v2 PLAN 2.1; it grew out of the 1.1 15-minute pilot) and the expiry-day reads (PLAN 2.4).

What runs (``snapshot``, one tick of ``POST /jobs/iv-intraday``; the controller calls it every 2 minutes 09:15–15:30 IST):

* **targets** come from the stored expiry table (no NSE call): NIFTY / BANKNIFTY / FINNIFTY near expiry (tier ``index_near``),
  their next expiry when it is liquid (``index_next``; FINNIFTY's December series had one strike on 5 Nov) and the owner's
  F&O watch names near expiry (``watch_near``);
* **cadence** per tier is planned against the budget each tick (``plan_cadence``): the richest plan of ``LADDER`` whose calls
  for the rest of the session fit what the ledger leaves (this caller's day cap, the ledger's own quota for it, the global
  day cap minus a reserve for the other Breeze callers). Near every 2 min / next every 2 min / watch every 15 min when the
  budget allows; the lower tiers stretch first, the near tier last. A tier is due when its last snapshot (stored row or this
  process's last attempt) is at least its cadence old;
* **Breeze codes**: ICICI's ``stock_code`` is its ShortName, not the NSE symbol (BANKNIFTY = ``CNXBAN``, FINNIFTY = ``NIFFIN``,
  INFY = ``INFTEC``). 5 Nov's pilot sent ``BANKNIFTY`` and got nothing back for four calls a tick: BANKNIFTY read OFFLINE all
  day (review M45). Indices from ``BREEZE_INDEX_CODES`` (checked against ICICI's NSEScripMaster.txt), stocks from the
  cached security master (``ExchangeCode`` → ``ShortName`` on the EQ row);
* **time to expiry** is the calendar time to 15:30 IST on the expiry day, / 365 (``t_years``): the EOD convention evaluated at
  the snapshot's clock, equal to ``b76-pcp-v1`` at 15:30, and positive through an expiry day, so the expiring series keeps
  an IV until the close (the pilot's whole-day ``dte`` was 0 on an expiry day and the series vanished). Rows carry
  ``MODEL_VERSION_INTRADAY``;
* **stores**: the raw chain rows to parquet parts under ``data/ticks/chain/<date>/`` (bid, ask, quantities, OI, OI change vs
  the previous session, volume, spot, last trade time), the derived per-strike rows to ``iv_intraday`` (mid, IV, OI, forward);
* **NSE option-chain-v3** only as the fallback (O-T7): when Breeze has no session, an injected ``nse_chain(symbol, expiry)``
  (data-service's shared, cookie-primed, 30 s-cached, breaker-guarded client) serves the indices' near expiry at most every
  ``NSE_FALLBACK_EVERY_MIN`` minutes; rows are ``source = 'nse'`` with NSE's own IV in ``nse_iv``. Not wired → skipped.

Hard rules (PLAN §0.9 / §0.11): read-only Breeze methods only (``get_option_chain_quotes``, ``get_historical_data_v2``);
every call acquired on the ledger first (``ledger().decide`` dry run, ``ledger().guard(caller, method)`` around the SDK
call; ``BudgetExceeded`` ends the tick; ``budget=None`` → skipped, never unmetered); skipped quietly without a live session
or outside the window; nothing here feeds the Decision Desk, the S1 shadow, a directional alert or a ticket price.

Reads (``oi_tape``, ``expiry_day``) compute from stored rows only — the request path never reaches a publisher. Every
derived number is ``context`` (OI change, PCR, max pain, pin risk, the straddle path) or ``arithmetic`` (IV, the
implied-vs-realised scorecard); none is a ``signal``. Sentences end "describes, does not predict".

The expiry replay (``run_expiry_replay``, PLAN 2.4, O-T16): Breeze 1-minute bars of the ATM call and put on past expiry
days into ``iv_expiry_replay`` — the historical expiry-day straddle curve XPRY compares today against. A one-off job the PM
runs after the close (refused inside the freeze windows and during the session unless forced), resumable, ≈ 2 calls per
expiry, paced and metered.
"""
from __future__ import annotations

import math
import os
import time as _time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from data_health import db

from fo_iv import black76 as b76
from fo_iv.black76 import MODEL_VERSION
from fo_iv.iv_eod import INDEX_NAMES, INDEX_SYMBOLS, rate_for
from fo_iv.schema import CASTS, COLUMNS
from shared.logging import get_logger

logger = get_logger(__name__)

IST = ZoneInfo("Asia/Kolkata")
UTC = ZoneInfo("UTC")
SESSION_OPEN, SESSION_CLOSE = time(9, 15), time(15, 30)
WINDOW = (SESSION_OPEN, SESSION_CLOSE)          # the whole session (the pilot started at 09:20 and missed the open)
TAPE_INDICES: tuple[str, ...] = ("NIFTY", "BANKNIFTY", "FINNIFTY")
PILOT_INDICES = TAPE_INDICES                    # the 1.1 name, kept for callers
MODEL_VERSION_INTRADAY = f"{MODEL_VERSION}-i"   # same Black-76 / parity method, T = clock time to 15:30 IST on expiry / 365
DEFAULT_MAX_CALLS_PER_SNAPSHOT = 30             # ≤ 30/min (PLAN 1.1): one tick never takes more
DEFAULT_DAILY_CAP = 2000                        # this caller's day cap (IV_TAPE_DAY_CAP); the ledger's own quota still wins
DEFAULT_GLOBAL_RESERVE = 600                    # calls left for the other Breeze callers (positions, margin, gold) when planning
CALLER = "iv_intraday"                          # the ledger's per-caller quota name (shared/breeze_budget.py)
METHOD = "get_option_chain_quotes"
HIST_METHOD = "get_historical_data_v2"
REPLAY_CALLER = "iv_expiry_replay"
SOURCE = "breeze"
NSE_SOURCE = "nse"
NSE_FALLBACK_EVERY_MIN = 6                      # NSE v3 throttles (403/429 → 600 s breaker): never faster than this
DUE_SLACK_S = 45.0                              # a tick a little early still counts as due (the controller fires on the minute)
MIN_NEXT_STRIKES = 10                           # the next expiry is snapped only when its last EOD had this many IV strikes
MIN_T_YEARS = 5 * 60 / (365 * 86400)            # no IV in the last five minutes of an expiry (T → 0)
PARQUET_COLUMNS = ["ts", "symbol", "expiry", "right", "strike", "ltp", "bid", "ask", "bid_qty", "ask_qty", "oi", "chnge_oi", "volume", "spot",
                   "ltt", "source"]
DESCRIBES = "describes, does not predict"

# ICICI ShortName (the Breeze stock_code) for the NSE index symbols, from NSEScripMaster.txt's Series-'0' rows:
# "NIFTY 50" → NIFTY, "NIFTY BANK" → CNXBAN, "NIFTY FIN SERVICE" → NIFFIN, "NIFTY MID SELECT" → NIFSEL.
BREEZE_INDEX_CODES: dict[str, str] = {"NIFTY": "NIFTY", "BANKNIFTY": "CNXBAN", "FINNIFTY": "NIFFIN", "MIDCPNIFTY": "NIFSEL"}
DEFAULT_STEPS: dict[str, float] = {"NIFTY": 50.0, "BANKNIFTY": 100.0, "FINNIFTY": 50.0, "MIDCPNIFTY": 25.0}

TIERS: tuple[str, ...] = ("index_near", "index_next", "watch_near")        # priority order: the last stretches first
# cadence plans, richest first (minutes; None = off this tick). The first whose rest-of-session need fits the budget runs.
LADDER: tuple[dict[str, int | None], ...] = (
    {"index_near": 2, "index_next": 2, "watch_near": 15},
    {"index_near": 2, "index_next": 4, "watch_near": 15},
    {"index_near": 2, "index_next": 6, "watch_near": 15},
    {"index_near": 2, "index_next": 10, "watch_near": 30},
    {"index_near": 2, "index_next": 15, "watch_near": 30},
    {"index_near": 3, "index_next": 15, "watch_near": 30},
    {"index_near": 4, "index_next": 30, "watch_near": 60},
    {"index_near": 6, "index_next": 30, "watch_near": None},
    {"index_near": 10, "index_next": 60, "watch_near": None},
    {"index_near": 15, "index_next": None, "watch_near": None},
    {"index_near": 30, "index_next": None, "watch_near": None},
)

_LAST_ATTEMPT: dict[tuple[str, date], datetime] = {}     # this process's last call per (symbol, expiry), UTC-naive
_EMPTY_WARNED: set[tuple[date, str]] = set()             # one warning per IST day and symbol for legs that came back empty


@dataclass
class Snapshot:
    ts: datetime                          # UTC-naive
    symbol: str
    expiry: date
    calls: list[dict[str, Any]] = field(default_factory=list)
    puts: list[dict[str, Any]] = field(default_factory=list)
    source: str = SOURCE


@dataclass(frozen=True)
class Target:
    symbol: str
    expiry: date
    tier: str


# ── time ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def to_ist(now_utc: datetime) -> datetime:
    """A UTC-naive (the store's convention) or aware datetime → aware IST."""
    return (now_utc.replace(tzinfo=UTC) if now_utc.tzinfo is None else now_utc).astimezone(IST)


def ist_wall_to_utc(day: date, t: time) -> datetime:
    """An IST wall-clock time on ``day`` → UTC-naive."""
    return datetime.combine(day, t, IST).astimezone(timezone.utc).replace(tzinfo=None)


def in_window(now_ist: datetime) -> bool:
    return now_ist.weekday() < 5 and WINDOW[0] <= now_ist.time() <= WINDOW[1]


def t_years(now_utc: datetime, expiry: date) -> float:
    """Calendar time from ``now`` to 15:30 IST on ``expiry`` in years (/ 365); 0 once the expiry has closed."""
    left = (ist_wall_to_utc(expiry, SESSION_CLOSE) - (now_utc.replace(tzinfo=None) if now_utc.tzinfo is None
                                                    else now_utc.astimezone(timezone.utc).replace(tzinfo=None))).total_seconds()
    return max(0.0, left) / (365.0 * 86400.0)


def breeze_expiry(d: date) -> str:
    return f"{d.isoformat()}T06:00:00.000Z"


def session_minutes_left(now_ist: datetime) -> float:
    close = datetime.combine(now_ist.date(), SESSION_CLOSE, IST)
    return max(0.0, (close - now_ist).total_seconds() / 60.0)


# ── ICICI codes ─────────────────────────────────────────────────────────────────────────────────────────────────────

def default_master_path() -> Path:
    env = os.environ.get("ICICI_MASTER_DIR", "").strip()
    base = Path(env) if env else Path(__file__).resolve().parents[3] / "data" / "reference" / "icici_security_master"
    return base / "NSEScripMaster.txt"


@lru_cache(maxsize=4)
def _master_codes(path: str, mtime: float) -> dict[str, str]:  # noqa: ARG001 — mtime is the cache key
    """NSE symbol (the master's last column, ExchangeCode) → ICICI ShortName from the EQ / BE rows (EQ preferred)."""
    import csv

    out: dict[str, str] = {}
    series_of: dict[str, str] = {}
    with open(path, encoding="utf-8", errors="replace", newline="") as fh:
        for raw in csv.reader(fh):
            if len(raw) < 4:
                continue
            cols = [c.strip().strip('"').strip() for c in raw]
            short, series, exch = cols[1], cols[2].upper(), cols[-1].upper()
            if not short or short == "ShortName" or series not in ("EQ", "BE") or not exch:
                continue
            if exch not in out or (series_of.get(exch) != "EQ" and series == "EQ"):
                out[exch], series_of[exch] = short, series
    return out


def master_codes(path: Path | None = None) -> dict[str, str]:
    p = path or default_master_path()
    try:
        return _master_codes(str(p), p.stat().st_mtime)
    except OSError:
        return {}


def breeze_code(symbol: str, master: Mapping[str, str] | None = None) -> str:
    """The Breeze ``stock_code`` for an NSE F&O underlying: the index table, then the security master, else the symbol."""
    sym = symbol.upper()
    if sym in BREEZE_INDEX_CODES:
        return BREEZE_INDEX_CODES[sym]
    return (master or {}).get(sym, sym)


# ── raw rows ────────────────────────────────────────────────────────────────────────────────────────────────────────

def _f(v: Any) -> float | None:
    try:
        x = float(str(v).replace(",", "")) if isinstance(v, str) else float(v)
    except (TypeError, ValueError):
        return None
    return x if np.isfinite(x) and x > 0 else None


def _signed(v: Any) -> float | None:
    try:
        x = float(str(v).replace(",", "")) if isinstance(v, str) else float(v)
    except (TypeError, ValueError):
        return None
    return x if np.isfinite(x) else None


def normalise_rows(rows: Iterable[dict[str, Any]], ts: datetime, symbol: str, expiry: date, right: str) -> list[dict[str, Any]]:
    """Breeze ``get_option_chain_quotes`` rows → the parquet schema (OI and volume in shares, as Breeze and the bhavcopy)."""
    out = []
    for r in rows or []:
        strike = _f(r.get("strike_price"))
        if strike is None:
            continue
        out.append({"ts": ts, "symbol": symbol, "expiry": expiry, "right": right, "strike": strike, "ltp": _f(r.get("ltp")),
                    "bid": _f(r.get("best_bid_price")), "ask": _f(r.get("best_offer_price")),
                    "bid_qty": _f(r.get("best_bid_quantity")), "ask_qty": _f(r.get("best_offer_quantity")),
                    "oi": _f(r.get("open_interest")), "chnge_oi": None if r.get("chnge_oi") is None else (_signed(r.get("chnge_oi")) or 0.0),
                    "volume": _f(r.get("total_quantity_traded")), "spot": _f(r.get("spot_price")), "ltt": str(r.get("ltt") or ""),
                    "source": SOURCE})
    return out


def normalise_nse_v3(payload: Mapping[str, Any] | None, ts: datetime, symbol: str, expiry: date, lot: int | None) -> Snapshot:
    """NSE ``api/option-chain-v3`` → a Snapshot in the Breeze schema. NSE's OI is in contracts: × lot to shares."""
    snap = Snapshot(ts=ts, symbol=symbol, expiry=expiry, source=NSE_SOURCE)
    rec = (payload or {}).get("records") or {}
    mult = float(lot or 1)
    spot = _f(rec.get("underlyingValue"))
    for d in rec.get("data") or []:
        for side, bucket in (("CE", snap.calls), ("PE", snap.puts)):
            x = d.get(side)
            if not isinstance(x, dict):
                continue
            strike = _f(d.get("strikePrice") or x.get("strikePrice"))
            if strike is None:
                continue
            oi, chg = _signed(x.get("openInterest")), _signed(x.get("changeinOpenInterest"))
            bucket.append({"ts": ts, "symbol": symbol, "expiry": expiry, "right": side, "strike": strike, "ltp": _f(x.get("lastPrice")),
                           "bid": _f(x.get("buyPrice1", x.get("bidprice"))), "ask": _f(x.get("sellPrice1", x.get("askPrice"))),
                           "bid_qty": _f(x.get("buyQuantity1", x.get("bidQty"))), "ask_qty": _f(x.get("sellQuantity1", x.get("askQty"))),
                           "oi": None if oi is None else oi * mult, "chnge_oi": None if chg is None else chg * mult,
                           "volume": None if _f(x.get("totalTradedVolume")) is None else float(x["totalTradedVolume"]) * mult,
                           "spot": _f(x.get("underlyingValue")) or spot, "ltt": str(rec.get("timestamp") or ""), "source": NSE_SOURCE,
                           "nse_iv": _f(x.get("impliedVolatility"))})
    return snap


def mid_of(row: Mapping[str, Any]) -> float | None:
    b, a = row.get("bid"), row.get("ask")
    if b and a and a >= b:
        return (a + b) / 2.0
    return None


# ── derived rows ────────────────────────────────────────────────────────────────────────────────────────────────────

def derive(snapshot: Snapshot, day: date, r: float, *, now: datetime) -> list[dict[str, Any]]:  # noqa: ARG001 — day kept for callers
    """Per strike IV from the bid/ask mid on the parity forward of this snapshot (OTM wings + 3 % ITM, as the EOD method),
    T = clock time to 15:30 IST on the expiry (``t_years``); nothing once the expiry's last five minutes have started."""
    t = t_years(snapshot.ts, snapshot.expiry)
    if t <= 0:
        return []
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
            iv = b76.implied_vol(m, fwd, k, t, call, r) if (m is not None and allowed and t >= MIN_T_YEARS) else None
            out.append({"ts": snapshot.ts, "symbol": snapshot.symbol, "expiry": snapshot.expiry, "strike": float(k), "opt_type": right, "mid": m,
                        "iv": round(iv * 100, 4) if iv else None, "nse_iv": row.get("nse_iv"), "oi": row.get("oi"), "forward": round(fwd, 4),
                        "spot": spot, "source": snapshot.source, "model_version": MODEL_VERSION_INTRADAY, "r": r, "first_seen_at": now})
    return out


# ── parquet (raw) ───────────────────────────────────────────────────────────────────────────────────────────────────

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
    df = pd.DataFrame(rows).reindex(columns=PARQUET_COLUMNS)
    df["ts"] = pd.to_datetime(df["ts"])
    df["expiry"] = df["expiry"].astype(str)
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), tmp)
    tmp.replace(final)
    return final


def latest_raw(root: Path | None, day: date, symbol: str, expiry: date) -> pd.DataFrame:
    """The newest stored raw snapshot of (symbol, expiry) on ``day`` (bid / ask / OI change vs the previous session)."""
    if root is None:
        return pd.DataFrame(columns=PARQUET_COLUMNS)
    day_dir = Path(root) / day.isoformat()
    for part in sorted(day_dir.glob("part-*.parquet"), reverse=True):
        try:
            df = pd.read_parquet(part)
        except Exception:  # noqa: BLE001 — a torn part is skipped, the next older one serves
            continue
        hit = df[(df["symbol"] == symbol) & (df["expiry"].astype(str) == expiry.isoformat())]
        if not hit.empty:
            return hit[hit["ts"] == hit["ts"].max()]
    return pd.DataFrame(columns=PARQUET_COLUMNS)


# ── targets, due, budget plan ───────────────────────────────────────────────────────────────────────────────────────

def tape_targets(store: Any, *, watchlist: Iterable[str] = (), today: date | None = None, as_of: date | None = None) -> list[Target]:
    """(symbol, expiry, tier) from the stored expiry table, never an NSE call: the indices' near expiry (≥ today, so the
    expiring series is snapped through its expiry day) and their next one when its last EOD was liquid; the watch names'
    near expiry."""
    if not db.table_exists(store, "iv_expiry_daily"):
        return []
    day = as_of or db.to_date(db.scalar(store, "SELECT MAX(date) FROM iv_expiry_daily"))
    if day is None:
        return []
    floor = today or day
    out: list[Target] = []
    watch = [s.upper() for s in watchlist if s and s.upper() not in TAPE_INDICES]
    syms = [*TAPE_INDICES, *dict.fromkeys(watch)]
    df = db.query_df(store, f"""SELECT symbol, expiry, n_iv_strikes FROM iv_expiry_daily WHERE date = ? AND expiry >= ?
                                AND symbol IN ({", ".join("?" for _ in syms)}) ORDER BY symbol, expiry""", [day, floor, *syms])
    for sym in syms:
        rows = df[df["symbol"] == sym]
        exps: list[tuple[date, Any]] = [(d, n) for d, n in ((db.to_date(e), n) for e, n in zip(rows["expiry"], rows["n_iv_strikes"], strict=True))
                                        if d is not None]
        if not exps:
            continue
        if sym in TAPE_INDICES:
            out.append(Target(sym, exps[0][0], "index_near"))
            if len(exps) > 1 and (exps[1][1] is None or pd.isna(exps[1][1]) or int(exps[1][1]) >= MIN_NEXT_STRIKES):
                out.append(Target(sym, exps[1][0], "index_next"))
        else:
            out.append(Target(sym, exps[0][0], "watch_near"))
    return out


def pilot_targets(store: Any, *, watchlist: Iterable[str] = (), as_of: date | None = None) -> list[tuple[str, date]]:
    """The 1.1 helper's shape: (symbol, expiry) pairs."""
    return [(t.symbol, t.expiry) for t in tape_targets(store, watchlist=watchlist, as_of=as_of)]


def last_snapshots(store: Any, day: date) -> dict[tuple[str, date], datetime]:
    """The newest stored ``iv_intraday`` ts per (symbol, expiry) on the IST ``day`` (UTC-naive)."""
    if not db.table_exists(store, "iv_intraday"):
        return {}
    lo, hi = ist_wall_to_utc(day, time(0, 0)), ist_wall_to_utc(day + timedelta(days=1), time(0, 0))
    df = db.query_df(store, "SELECT symbol, expiry, MAX(ts) AS ts FROM iv_intraday WHERE ts >= ? AND ts < ? GROUP BY symbol, expiry", [lo, hi])
    out: dict[tuple[str, date], datetime] = {}
    for sym, exp, ts in zip(df["symbol"], df["expiry"], df["ts"], strict=True):
        e = db.to_date(exp)
        if e is not None and ts is not None and not pd.isna(ts):
            out[(str(sym), e)] = pd.Timestamp(ts).to_pydatetime().replace(tzinfo=None)
    return out


def slots_left(minutes_left: float, every_min: int | None) -> int:
    """Snapshots one tier still takes at ``every_min`` until 15:30 (this tick included)."""
    if not every_min or minutes_left < 0:
        return 0
    return int(minutes_left // every_min) + 1


def plan_cadence(counts: Mapping[str, int], minutes_left: float, budget_left: float,
                 ladder: Iterable[Mapping[str, int | None]] = LADDER) -> tuple[dict[str, int | None], int, int]:
    """The richest plan whose calls for the rest of the session (2 per target per slot) fit ``budget_left``.
    Returns (cadence, need, rung); when none fits, the leanest rung (the tick itself is trimmed to the budget)."""
    rungs = [dict(r) for r in ladder]
    for i, rung in enumerate(rungs):
        need = sum(2 * int(counts.get(t, 0)) * slots_left(minutes_left, rung.get(t)) for t in TIERS)
        if need <= budget_left:
            return rung, need, i
    last = rungs[-1]
    return last, sum(2 * int(counts.get(t, 0)) * slots_left(minutes_left, last.get(t)) for t in TIERS), len(rungs) - 1


def is_due(last: datetime | None, now: datetime, every_min: int | None) -> bool:
    if not every_min:
        return False
    return last is None or (now - last).total_seconds() >= every_min * 60 - DUE_SLACK_S


def _budget_left(first: Any, daily_cap: int, reserve: int) -> tuple[float, dict[str, Any]]:
    used_caller = int(getattr(first, "caller_used_day", 0) or 0)
    quota = getattr(first, "caller_quota", None)
    cap = min(int(daily_cap), int(quota)) if isinstance(quota, int) and quota > 0 else int(daily_cap)
    used_day, cap_day = getattr(first, "used_day", None), getattr(first, "cap_day", None)
    caller_left = max(0, cap - used_caller)
    global_left = (int(cap_day) - int(used_day) - int(reserve)) if isinstance(used_day, int) and isinstance(cap_day, int) else math.inf
    left = max(0.0, min(float(caller_left), float(global_left)))
    return left, {"caller_used_day": used_caller, "caller_cap": cap, "ledger_quota": quota, "global_left_after_reserve": (
        None if global_left == math.inf else max(0, int(global_left))), "reserve": reserve}


def _env_int(name: str, default: int) -> int:
    try:
        v = int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default
    return v if v > 0 else default


# ── one tick ────────────────────────────────────────────────────────────────────────────────────────────────────────

def snapshot(store: Any, breeze: Any, budget: Any, *, now: datetime | None = None, watchlist: Iterable[str] = (), parquet_root: Path | None = None,
             max_calls: int = DEFAULT_MAX_CALLS_PER_SNAPSHOT, force_window: bool = False, is_live: Callable[[], bool] | None = None,
             daily_cap: int | None = None, reserve: int | None = None, master: Mapping[str, str] | None = None,
             nse_chain: Callable[[str, date], Mapping[str, Any] | None] | None = None, ladder: Iterable[Mapping[str, int | None]] = LADDER,
             force_all: bool = False) -> dict[str, Any]:
    """One tick of the tape. Returns ``{"status": skipped|ok|partial, "reason"?, "calls", "rows", "cadence", ...}``; never raises on
    a bad chain. ``force_all`` snaps every target regardless of cadence (an operator re-run), still metered and planned."""
    now = now or db.utcnow()
    now_ist = to_ist(now)
    day = now_ist.date()
    breeze_live = breeze is not None and (is_live is None or is_live())
    if breeze_live and budget is None:                  # checked before anything else: Breeze is never called unmetered
        return {"status": "skipped", "reason": "no budget ledger (shared/breeze_budget.py not deployed): Breeze is never called unmetered",
                "calls": 0}
    if not breeze_live and nse_chain is None:
        return {"status": "skipped", "reason": "Breeze session not live (NSE v3 fallback not wired)", "calls": 0}
    if not force_window and not in_window(now_ist):
        return {"status": "skipped", "reason": f"outside 09:15–15:30 IST ({now_ist.strftime('%a %H:%M')})", "calls": 0}
    targets = tape_targets(store, watchlist=watchlist, today=day)
    if not targets:
        return {"status": "skipped", "reason": "no stored expiries (run iv_eod first)", "calls": 0}
    if not breeze_live:
        assert nse_chain is not None                    # the not-live-and-not-wired case returned above
        return _nse_fallback_tick(store, nse_chain, targets, now=now, day=day, parquet_root=parquet_root)
    daily_cap = int(daily_cap or _env_int("IV_TAPE_DAY_CAP", DEFAULT_DAILY_CAP))
    reserve = int(reserve if reserve is not None else _env_int("IV_TAPE_GLOBAL_RESERVE", DEFAULT_GLOBAL_RESERVE))
    first = budget.decide(CALLER, METHOD)                      # dry run: the ledger's reason when the tick cannot start
    if not getattr(first, "allowed", False):
        return {"status": "skipped", "reason": f"budget ledger refused: {getattr(first, 'reason', 'no')}", "calls": 0,
                "retry_after_s": getattr(first, "retry_after_s", None)}
    left, budget_info = _budget_left(first, daily_cap, reserve)
    if left < 2:
        return {"status": "skipped", "reason": (f"tape day budget reached ({budget_info['caller_used_day']}/{budget_info['caller_cap']} {CALLER} "
                                                "calls today, IST, or the global reserve)"), "calls": 0, "budget": budget_info}
    counts = {t: sum(1 for x in targets if x.tier == t) for t in TIERS}
    cadence, need, rung = plan_cadence(counts, session_minutes_left(now_ist), left, ladder)
    seen = last_snapshots(store, day)
    due: list[Target] = []
    for tgt in sorted(targets, key=lambda x: TIERS.index(x.tier)):
        key = (tgt.symbol, tgt.expiry)
        last = max([d for d in (seen.get(key), _LAST_ATTEMPT.get(key)) if d is not None], default=None)
        if force_all or is_due(last, now, cadence.get(tgt.tier)):
            due.append(tgt)
    cap_calls = int(min(max_calls, left))
    if 2 * len(due) > cap_calls:
        due = due[: cap_calls // 2]                             # tier order: the near series keep their slot
    plan = {"cadence_min": cadence, "rung": rung, "need_rest_of_session": need, "budget_left": int(left) if left != math.inf else None,
            **budget_info}
    if not due:
        return {"status": "skipped", "reason": "nothing due at this tick (cadence)", "calls": 0, "plan": plan, "quiet": True}
    codes = master if master is not None else master_codes()
    r, _ = rate_for(store, day)
    raw: list[dict[str, Any]] = []
    derived: list[dict[str, Any]] = []
    calls, refused, errors = 0, 0, []
    empty: list[str] = []
    stop = False
    for tgt in due:
        if stop:
            break
        snap = Snapshot(ts=now, symbol=tgt.symbol, expiry=tgt.expiry)
        code = breeze_code(tgt.symbol, codes)
        for right, bucket in (("call", snap.calls), ("put", snap.puts)):
            try:
                with budget.guard(CALLER, METHOD):             # acquires or raises before the SDK method runs (PLAN §0.11)
                    resp = breeze.get_option_chain_quotes(stock_code=code, exchange_code="NFO", product_type="options",
                                                          expiry_date=breeze_expiry(tgt.expiry), right=right)
                calls += 1
                rows = resp.get("Success") if isinstance(resp, dict) else resp
                got = normalise_rows(rows or [], now, tgt.symbol, tgt.expiry, "CE" if right == "call" else "PE")
                if not got:
                    detail = resp.get("Error") if isinstance(resp, dict) else None
                    empty.append(f"{tgt.symbol}({code}) {tgt.expiry} {right}: no rows{f' ({str(detail)[:80]})' if detail else ''}")
                bucket.extend(got)
            except Exception as exc:  # noqa: BLE001 — one leg failing never stops the snapshot; a refusal ends it
                if type(exc).__name__ == "BudgetExceeded":
                    refused += 1
                    errors.append(f"{tgt.symbol} {tgt.expiry} {right}: budget refused ({exc})")
                    stop = True
                    break
                calls += 1
                errors.append(f"{tgt.symbol}({code}) {tgt.expiry} {right}: {type(exc).__name__}")
        _LAST_ATTEMPT[(tgt.symbol, tgt.expiry)] = now
        raw.extend(snap.calls)
        raw.extend(snap.puts)
        derived.extend(derive(snap, day, r, now=now))
    part = write_parquet_part(parquet_root, day, raw) if parquet_root is not None else None
    n = db.upsert(store, "iv_intraday", pd.DataFrame(derived), COLUMNS["iv_intraday"], CASTS["iv_intraday"]) if derived else 0
    fresh = sorted({e.split("(")[0] for e in empty} - {sym for d, sym in _EMPTY_WARNED if d == day})
    if fresh:                                                   # once a day per symbol: a wrong ICICI code would warn 188 times
        _EMPTY_WARNED.update((day, sym) for sym in fresh)
        logger.warning("fo_iv.tape_empty_legs", symbols=fresh, legs=empty[:6])
    logger.info("fo_iv.intraday", calls=calls, rows=n, due=len(due), targets=len(targets), rung=rung, errors=len(errors))
    return {"status": "ok" if not refused else "partial", "calls": calls, "refused": refused, "rows": n, "raw_rows": len(raw),
            "targets": [(t.symbol, t.expiry.isoformat(), t.tier) for t in due], "parquet": str(part) if part else None,
            "errors": errors[:10], "empty_legs": empty[:10], "ts": db.iso_utc(now), "plan": plan, "source": SOURCE}


def _lot_of(store: Any, symbol: str) -> int | None:
    if not db.table_exists(store, "iv_surface_daily"):
        return None
    v = db.scalar(store, "SELECT lot FROM iv_surface_daily WHERE symbol = ? AND lot IS NOT NULL ORDER BY date DESC LIMIT 1", [symbol])
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _nse_fallback_tick(store: Any, nse_chain: Callable[[str, date], Mapping[str, Any] | None], targets: list[Target], *, now: datetime,
                       day: date, parquet_root: Path | None) -> dict[str, Any]:
    """Breeze down: NSE v3 for the indices' near expiry, at most every NSE_FALLBACK_EVERY_MIN minutes (one GET each)."""
    seen = last_snapshots(store, day)
    due = [t for t in targets if t.tier == "index_near"
           and is_due(max([d for d in (seen.get((t.symbol, t.expiry)), _LAST_ATTEMPT.get((t.symbol, t.expiry))) if d], default=None),
                      now, NSE_FALLBACK_EVERY_MIN)]
    if not due:
        return {"status": "skipped", "reason": "Breeze session not live; NSE v3 fallback not due", "calls": 0, "quiet": True, "source": NSE_SOURCE}
    r, _ = rate_for(store, day)
    raw: list[dict[str, Any]] = []
    derived: list[dict[str, Any]] = []
    errors: list[str] = []
    for tgt in due:
        _LAST_ATTEMPT[(tgt.symbol, tgt.expiry)] = now
        try:
            payload = nse_chain(tgt.symbol, tgt.expiry)
        except Exception as exc:  # noqa: BLE001 — NSE refusing (403/429 → its breaker) ends the fallback tick
            errors.append(f"{tgt.symbol}: {type(exc).__name__}")
            break
        snap = normalise_nse_v3(payload, now, tgt.symbol, tgt.expiry, _lot_of(store, tgt.symbol))
        raw.extend(snap.calls)
        raw.extend(snap.puts)
        derived.extend(derive(snap, day, r, now=now))
    part = write_parquet_part(parquet_root, day, raw) if parquet_root is not None else None
    n = db.upsert(store, "iv_intraday", pd.DataFrame(derived), COLUMNS["iv_intraday"], CASTS["iv_intraday"]) if derived else 0
    return {"status": "ok" if derived else "partial", "calls": 0, "nse_requests": len(due), "rows": n, "raw_rows": len(raw), "source": NSE_SOURCE,
            "targets": [(t.symbol, t.expiry.isoformat(), t.tier) for t in due], "parquet": str(part) if part else None, "errors": errors,
            "ts": db.iso_utc(now)}


def is_index(symbol: str) -> bool:
    return symbol in INDEX_SYMBOLS


# ── tape reads (stored rows only) ───────────────────────────────────────────────────────────────────────────────────

def load_day(store: Any, symbol: str, day: date, expiry: date | None = None) -> pd.DataFrame:
    """``iv_intraday`` rows of the IST ``day`` (09:15–15:30 IST is 03:45–10:00 UTC; bounds are explicit, never ``ts::DATE``)."""
    if not db.table_exists(store, "iv_intraday"):
        return pd.DataFrame()
    lo, hi = ist_wall_to_utc(day, time(0, 0)), ist_wall_to_utc(day + timedelta(days=1), time(0, 0))
    sql = ("SELECT ts, expiry, strike, opt_type, mid, iv, nse_iv, oi, forward, spot, source FROM iv_intraday "
           "WHERE symbol = ? AND ts >= ? AND ts < ?")
    params: list[Any] = [symbol.upper(), lo, hi]
    if expiry is not None:
        sql += " AND expiry = ?"
        params.append(expiry)
    df = db.query_df(store, sql + " ORDER BY ts, expiry, strike, opt_type", params)
    if not df.empty:
        df["expiry"] = df["expiry"].map(db.to_date)
        df["ts"] = pd.to_datetime(df["ts"])
    return df


def latest_tape_day(store: Any, symbol: str, on_or_before: date | None = None) -> date | None:
    if not db.table_exists(store, "iv_intraday"):
        return None
    hi = ist_wall_to_utc(on_or_before + timedelta(days=1), time(0, 0)) if on_or_before else None
    v = db.scalar(store, "SELECT MAX(ts) FROM iv_intraday WHERE symbol = ?" + (" AND ts < ?" if hi else ""), [symbol.upper(), *([hi] if hi else [])])
    return to_ist(pd.Timestamp(v).to_pydatetime()).date() if v is not None and not pd.isna(v) else None


def max_pain(oi_ce: Mapping[float, float], oi_pe: Mapping[float, float]) -> float | None:
    """The strike at which option holders' total intrinsic value at settlement is smallest (writers' payout minimum), over the
    strikes in the snapshot. Arithmetic on OI; context, not a target."""
    strikes = np.array(sorted(set(oi_ce) | set(oi_pe)), dtype=float)
    if not len(strikes):
        return None
    ck = np.array(list(oi_ce.keys()), dtype=float)
    cv = np.array([float(v or 0) for v in oi_ce.values()], dtype=float)
    pk = np.array(list(oi_pe.keys()), dtype=float)
    pv = np.array([float(v or 0) for v in oi_pe.values()], dtype=float)
    pay = (np.maximum(0.0, strikes[:, None] - ck[None, :]) * cv[None, :]).sum(axis=1) if len(ck) else np.zeros(len(strikes))
    pay = pay + ((np.maximum(0.0, pk[None, :] - strikes[:, None]) * pv[None, :]).sum(axis=1) if len(pk) else 0.0)
    return float(strikes[int(np.argmin(pay))])                    # the first (lowest) strike on a tie


def _atm_iv(g: pd.DataFrame, fwd: float) -> float | None:
    ivs = g.dropna(subset=["iv"])
    if ivs.empty:
        return None
    pooled = ivs.groupby("strike")["iv"].mean().sort_index()
    if len(pooled) == 1:
        return float(pooled.iloc[0])
    if fwd <= pooled.index.min() or fwd >= pooled.index.max():
        return None
    return float(np.interp(fwd, pooled.index.to_numpy(dtype=float), pooled.to_numpy(dtype=float)))


def _pair_mids(g: pd.DataFrame) -> dict[float, tuple[float | None, float | None]]:
    out: dict[float, tuple[float | None, float | None]] = {}
    for k, gg in g.groupby("strike"):
        ce = gg.loc[gg["opt_type"] == "CE", "mid"]
        pe = gg.loc[gg["opt_type"] == "PE", "mid"]
        out[float(k)] = (float(ce.iloc[0]) if len(ce) and pd.notna(ce.iloc[0]) else None, float(pe.iloc[0]) if len(pe) and pd.notna(pe.iloc[0]) else None)
    return out


def _oi_sides(g: pd.DataFrame) -> tuple[dict[float, float], dict[float, float]]:
    ce = {float(k): float(v) for k, v in g.loc[g["opt_type"] == "CE"].groupby("strike")["oi"].sum(min_count=1).dropna().items()}
    pe = {float(k): float(v) for k, v in g.loc[g["opt_type"] == "PE"].groupby("strike")["oi"].sum(min_count=1).dropna().items()}
    return ce, pe


def tape_path(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Per snapshot of ONE expiry: forward, ATM strike (floating), ATM IV at the forward, the straddle at the floating ATM and
    at the day's opening ATM strike (fixed: a decay read on one instrument), call / put OI, PCR, max pain."""
    if df.empty:
        return []
    points: list[dict[str, Any]] = []
    open_k: float | None = None
    for ts, g in df.groupby("ts", sort=True):
        fwd = float(g["forward"].dropna().iloc[0]) if g["forward"].notna().any() else None
        if fwd is None:
            continue
        mids = _pair_mids(g)
        both = [k for k, (c, p) in mids.items() if c is not None and p is not None]
        atm_k = min(both, key=lambda k: abs(k - fwd)) if both else None
        if open_k is None and atm_k is not None:
            open_k = atm_k
        straddle = sum(mids[atm_k]) if atm_k is not None else None          # type: ignore[arg-type]
        ko = mids.get(open_k) if open_k is not None else None
        straddle_open = (ko[0] + ko[1]) if ko and ko[0] is not None and ko[1] is not None else None
        ce, pe = _oi_sides(g)
        c_oi, p_oi = sum(ce.values()), sum(pe.values())
        atm_iv = _atm_iv(g, fwd)
        points.append({"ts": db.iso_utc(pd.Timestamp(ts).to_pydatetime()), "ist": to_ist(pd.Timestamp(ts).to_pydatetime()).strftime("%H:%M"),
                       "forward": round(fwd, 2), "spot": None if pd.isna(g["spot"].iloc[0]) else round(float(g["spot"].iloc[0]), 2),
                       "atm_strike": atm_k, "atm_iv": None if atm_iv is None else round(atm_iv, 3),
                       "nse_atm_iv": _nse_atm(g, atm_k), "straddle": None if straddle is None else round(straddle, 2),
                       "open_strike": open_k, "straddle_open_strike": None if straddle_open is None else round(straddle_open, 2),
                       "call_oi": c_oi, "put_oi": p_oi, "pcr": round(p_oi / c_oi, 3) if c_oi else None,
                       "max_pain": max_pain(ce, pe), "n_strikes": int(g["strike"].nunique()), "source": str(g["source"].iloc[0])})
    return points


def _nse_atm(g: pd.DataFrame, k: float | None) -> float | None:
    if k is None or "nse_iv" not in g:
        return None
    v = g.loc[(g["strike"] == k), "nse_iv"].dropna()
    return round(float(v.mean()), 3) if len(v) else None


def oi_by_strike(df: pd.DataFrame, raw_latest: pd.DataFrame | None = None, *, around: float | None = None, width: int = 20) -> list[dict[str, Any]]:
    """Per strike: OI at the day's first snapshot and now (both sides), the change since the open; the latest mids; from the
    raw part, bid / ask and the OI change vs the previous session (NSE's / Breeze's ``chnge_oi``). Shares (the exchange unit)."""
    if df.empty:
        return []
    first_ts, last_ts = df["ts"].min(), df["ts"].max()
    first, last = df[df["ts"] == first_ts], df[df["ts"] == last_ts]
    f_ce, f_pe = _oi_sides(first)
    l_ce, l_pe = _oi_sides(last)
    mids = _pair_mids(last)
    strikes = sorted(set(l_ce) | set(l_pe) | set(f_ce) | set(f_pe))
    if around is not None and strikes:
        centre = min(range(len(strikes)), key=lambda i: abs(strikes[i] - around))
        strikes = strikes[max(0, centre - width): centre + width + 1]
    raw: dict[tuple[float, str], Mapping[str, Any]] = {}
    if raw_latest is not None and not raw_latest.empty:
        for rec in raw_latest.to_dict(orient="records"):
            raw[(float(rec["strike"]), str(rec["right"]))] = rec
    out = []
    for k in strikes:
        row: dict[str, Any] = {"strike": k}
        for side, fo, lo, mi in (("ce", f_ce, l_ce, 0), ("pe", f_pe, l_pe, 1)):
            o0, o1 = fo.get(k), lo.get(k)
            rr = raw.get((k, side.upper()), {})
            row.update({f"{side}_oi_open": o0, f"{side}_oi": o1, f"{side}_chg_open": (o1 - o0) if o0 is not None and o1 is not None else None,
                        f"{side}_mid": mids.get(k, (None, None))[mi], f"{side}_bid": _num(rr.get("bid")), f"{side}_ask": _num(rr.get("ask")),
                        f"{side}_chg_prev": _num(rr.get("chnge_oi"), signed=True)})
        out.append(row)
    return out


def _num(v: Any, signed: bool = False) -> float | None:
    x = _signed(v) if signed else _f(v)
    return None if x is None else float(x)


def timelapse(df: pd.DataFrame, strikes: list[float], max_frames: int = 48) -> list[dict[str, Any]]:
    """OI by strike per snapshot (calls, puts) on a fixed strike axis, ≤ ``max_frames`` frames (evenly kept, last always)."""
    if df.empty or not strikes:
        return []
    stamps = sorted(df["ts"].unique())
    if len(stamps) > max_frames:
        idx = sorted({int(round(i * (len(stamps) - 1) / (max_frames - 1))) for i in range(max_frames)})
        stamps = [stamps[i] for i in idx]
    frames = []
    for ts in stamps:
        g = df[df["ts"] == ts]
        ce, pe = _oi_sides(g)
        frames.append({"ts": db.iso_utc(pd.Timestamp(ts).to_pydatetime()), "ist": to_ist(pd.Timestamp(ts).to_pydatetime()).strftime("%H:%M"),
                       "ce": [ce.get(k) for k in strikes], "pe": [pe.get(k) for k in strikes]})
    return frames


def oi_tape(store: Any, symbol: str, *, day: date | None = None, expiry: date | None = None, parquet_root: Path | None = None,
            width: int = 15, max_frames: int = 48) -> dict[str, Any]:
    """The OMON › LIVE tape for one underlying and expiry (default: the day's nearest expiry): the path, OI by strike (open vs
    now, bid / ask), the time-lapse frames, the lot, the cadence actually seen. Stored rows only."""
    sym = symbol.upper()
    d = day or latest_tape_day(store, sym)
    base: dict[str, Any] = {"symbol": sym, "date": d.isoformat() if d else None, "badge": "context", "model_version": MODEL_VERSION_INTRADAY,
                            "units": {"oi": "shares (the exchange unit; ÷ lot for contracts)", "iv": "% annualised", "straddle": "₹ per unit"},
                            "verdict": f"Intraday OI / IV tape: {DESCRIBES}"}
    if d is None:
        return {**base, "expiry": None, "expiries": [], "path": [], "strikes": [], "frames": [], "snapshots": 0, "source": "OFFLINE"}
    df_all = load_day(store, sym, d)
    exps = sorted({e for e in df_all["expiry"] if e is not None}) if not df_all.empty else []
    exp = expiry if expiry in exps else (exps[0] if exps else None)
    df = df_all[df_all["expiry"] == exp] if exp is not None else pd.DataFrame()
    path = tape_path(df)
    last_fwd = path[-1]["forward"] if path else None
    strikes = oi_by_strike(df, latest_raw(parquet_root, d, sym, exp) if exp is not None else None, around=last_fwd, width=width)
    axis = [r["strike"] for r in strikes]
    stamps = [pd.Timestamp(t) for t in sorted(df["ts"].unique())] if not df.empty else []
    gaps = [round((b - a).total_seconds() / 60.0, 1) for a, b in zip(stamps, stamps[1:], strict=False)]
    sources = sorted({str(s) for s in df["source"].dropna()}) if not df.empty else []
    return {**base, "expiry": exp.isoformat() if exp else None, "expiries": [e.isoformat() for e in exps], "lot": _lot_of(store, sym),
            "dte_calendar": (exp - d).days if exp else None, "path": path, "strikes": strikes, "frames": timelapse(df, axis, max_frames),
            "snapshots": len(path), "first": path[0]["ist"] if path else None, "last": path[-1]["ist"] if path else None,
            "last_ts": path[-1]["ts"] if path else None, "median_gap_min": float(np.median(gaps)) if gaps else None,
            "source": ("breeze" if "breeze" in sources else sources[0]) if sources else "OFFLINE", "sources": sources}


# ── expiry day (PLAN 2.4) ───────────────────────────────────────────────────────────────────────────────────────────

REPLAY_DDL = """CREATE TABLE IF NOT EXISTS iv_expiry_replay (symbol VARCHAR NOT NULL, expiry DATE NOT NULL, ts TIMESTAMP NOT NULL,
  strike DOUBLE NOT NULL, ce_close DOUBLE, pe_close DOUBLE, ce_oi DOUBLE, pe_oi DOUBLE, ce_volume DOUBLE, pe_volume DOUBLE, straddle DOUBLE,
  spot_open DOUBLE, source VARCHAR NOT NULL, first_seen_at TIMESTAMP NOT NULL, PRIMARY KEY (symbol, expiry, ts))"""
REPLAY_COLUMNS = ["symbol", "expiry", "ts", "strike", "ce_close", "pe_close", "ce_oi", "pe_oi", "ce_volume", "pe_volume", "straddle", "spot_open",
                  "source", "first_seen_at"]
REPLAY_CASTS = {"expiry": "DATE", "ts": "TIMESTAMP", "first_seen_at": "TIMESTAMP",
                **{c: "DOUBLE" for c in ("strike", "ce_close", "pe_close", "ce_oi", "pe_oi", "ce_volume", "pe_volume", "straddle", "spot_open")}}
CURVE_MINUTES = tuple(range(0, 376, 5))         # minutes after 09:15 (09:15 … 15:30)
FAIR_EXCEED_RATE = 42.5                         # P(|Z| > √(2/π)) × 100: how often a fairly priced ATM straddle is beaten by expiry


def ensure_replay_schema(store: Any) -> None:
    db.execute(store, REPLAY_DDL)


def stored_expiries(store: Any, symbol: str, *, since: date | None = None, until: date | None = None) -> list[date]:
    if not db.table_exists(store, "iv_expiry_daily"):
        return []
    df = db.query_df(store, "SELECT DISTINCT expiry FROM iv_expiry_daily WHERE symbol = ? AND expiry >= ? AND expiry <= ? ORDER BY expiry",
                     [symbol.upper(), since or date(2000, 1, 1), until or date(2100, 1, 1)])
    return [e for e in (db.to_date(v) for v in df["expiry"]) if e is not None]


def upcoming_expiries(store: Any, symbol: str, today: date) -> list[date]:
    """Expiries ≥ today on the latest stored session (the exchange's own calendar, as the EOD file read it)."""
    if not db.table_exists(store, "iv_expiry_daily"):
        return []
    last = db.to_date(db.scalar(store, "SELECT MAX(date) FROM iv_expiry_daily WHERE symbol = ?", [symbol.upper()]))
    if last is None:
        return []
    df = db.query_df(store, "SELECT expiry FROM iv_expiry_daily WHERE symbol = ? AND date = ? AND expiry >= ? ORDER BY expiry",
                     [symbol.upper(), last, today])
    return [e for e in (db.to_date(v) for v in df["expiry"]) if e is not None]


def pin_risk(strikes: list[dict[str, Any]], spot: float | None, *, band_pct: float = 1.0, top: int = 3) -> list[dict[str, Any]]:
    """Strikes within ±``band_pct`` % of spot ranked by open interest (calls + puts): where a settlement near the strike leaves
    writers unsure of exercise. Context: it describes where the open interest sits, it does not predict the settlement."""
    if spot is None or not strikes:
        return []
    near = [r for r in strikes if abs(float(r["strike"]) - spot) / spot * 100 <= band_pct]
    ranked = sorted(near, key=lambda r: -((r.get("ce_oi") or 0) + (r.get("pe_oi") or 0)))[:top]
    return [{"strike": r["strike"], "distance_pts": round(float(r["strike"]) - spot, 2), "distance_pct": round((float(r["strike"]) / spot - 1) * 100, 3),
             "ce_oi": r.get("ce_oi"), "pe_oi": r.get("pe_oi"), "total_oi": (r.get("ce_oi") or 0) + (r.get("pe_oi") or 0)} for r in ranked]


def decay_today(path: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Today's straddle at the opening ATM strike as % of its first snapshot, by minute after 09:15."""
    base = next((p["straddle_open_strike"] for p in path if p.get("straddle_open_strike")), None)
    if not base:
        return []
    out = []
    for p in path:
        v = p.get("straddle_open_strike")
        if v is None:
            continue
        hh, mm = (int(x) for x in p["ist"].split(":"))
        out.append({"minute": (hh * 60 + mm) - (9 * 60 + 15), "ist": p["ist"], "pct_of_open": round(v / base * 100, 2), "straddle": v})
    return out


def replay_curve(store: Any, symbol: str, *, last_n: int = 26, before: date | None = None, start_minute: int = 0) -> dict[str, Any]:
    """The historical expiry-day straddle curve from ``iv_expiry_replay``: per 5-minute mark after 09:15, the median and
    25th / 75th percentile of (straddle ÷ that expiry day's straddle at ``start_minute``) over the last ``last_n`` replayed
    expiries. ``start_minute`` > 0 rebases every past day to today's first snapshot, so a tape that started late is compared
    like for like (today's line is a % of its first snapshot)."""
    empty = {"n": 0, "points": [], "expiries": [], "source": None, "start_minute": start_minute,
             "note": "no replay stored yet (the PM's after-close job, O-T16)"}
    if not db.table_exists(store, "iv_expiry_replay"):
        return empty
    df = db.query_df(store, "SELECT expiry, ts, straddle FROM iv_expiry_replay WHERE symbol = ? AND straddle IS NOT NULL"
                     + (" AND expiry < ?" if before else "") + " ORDER BY expiry, ts", [symbol.upper(), *([before] if before else [])])
    if df.empty:
        return empty
    df["expiry"] = df["expiry"].map(db.to_date)
    keep = sorted(df["expiry"].unique())[-last_n:]
    df = df[df["expiry"].isin(keep)].copy()
    ts = pd.to_datetime(df["ts"]).dt.tz_localize("UTC").dt.tz_convert(IST)   # stored UTC-naive; minutes after 09:15 IST
    df["minute"] = ts.dt.hour * 60 + ts.dt.minute - (9 * 60 + 15)
    curves: dict[date, pd.Series] = {}
    for e, g in df.groupby("expiry"):
        g = g.sort_values("minute")
        raw = pd.Series(g["straddle"].to_numpy(dtype=float), index=g["minute"].to_numpy())
        raw = raw[~raw.index.duplicated()]
        base = raw.asof(start_minute) if raw.index.min() <= start_minute else raw.iloc[0]
        if base is None or pd.isna(base) or base <= 0:
            continue
        curves[e] = (raw / float(base) * 100)[raw.index >= min(start_minute, raw.index.max())]
    pts = []
    for m in (m for m in CURVE_MINUTES if m >= start_minute) if start_minute else CURVE_MINUTES:
        vals = [float(s.asof(m)) for s in curves.values() if not s.empty and s.index.min() <= m and pd.notna(s.asof(m))]
        if vals:
            pts.append({"minute": m, "median": round(float(np.median(vals)), 2), "p25": round(float(np.percentile(vals, 25)), 2),
                        "p75": round(float(np.percentile(vals, 75)), 2), "n": len(vals)})
    if start_minute and pts and pts[0]["minute"] != start_minute:      # the rebase point itself (every day = 100 % there)
        pts.insert(0, {"minute": start_minute, "median": 100.0, "p25": 100.0, "p75": 100.0, "n": len(curves)})
    return {"n": len(curves), "points": pts, "expiries": [e.isoformat() for e in sorted(curves)], "source": "breeze 1-minute bars (backfilled)",
            "start_minute": start_minute,
            "note": "last-trade closes of the ATM call + put at the expiry-day open strike; today's line uses bid/ask mids"
                    + (f"; rebased to {((9 * 60 + 15 + start_minute) // 60):02d}:{((9 * 60 + 15 + start_minute) % 60):02d} IST, "
                       "today's first snapshot" if start_minute else "")}


def scorecard(store: Any, symbol: str, *, n: int = 26, before: date | None = None) -> dict[str, Any]:
    """Implied vs realised, one row per past expiry E (the gold accuracy-log pattern: each row's numbers were stored before
    the outcome and are never re-scored). Implied = the ATM straddle (call + put at the strike nearest the parity forward) at the
    close of the last session before E, as % of that forward, from ``iv_surface_daily``; 1σ = ``expected_move_pct``.
    Realised = NSE's closing index value on E against that forward (index options settle on the close). The naive comparator
    is the RV20 (close-to-close) move over the same days. Arithmetic; ``describes, does not predict``."""
    sym = symbol.upper()
    name = INDEX_NAMES.get(sym)
    if name is None or not db.table_exists(store, "iv_expiry_daily") or not db.table_exists(store, "index_ohlc_daily"):
        return {"rows": [], "stats": {"n": 0}, "note": "the scorecard covers the indices (NSE's index file holds their closes)"}
    cutoff = before or (date.today() + timedelta(days=1))  # noqa: DTZ011 — an IST session date bound only
    ex = db.query_df(store, """WITH p AS (SELECT expiry, MAX(date) AS p_date FROM iv_expiry_daily WHERE symbol = ? AND date < expiry AND expiry < ?
                                          GROUP BY expiry ORDER BY expiry DESC LIMIT ?)
                               SELECT p.expiry, p.p_date, d.dte, d.forward, d.atm_iv, d.expected_move_pct, d.first_seen_at
                               FROM p JOIN iv_expiry_daily d ON d.symbol = ? AND d.expiry = p.expiry AND d.date = p.p_date
                               ORDER BY p.expiry""", [sym, cutoff, int(n), sym])
    if ex.empty:
        return {"rows": [], "stats": {"n": 0}}
    ex["expiry"] = ex["expiry"].map(db.to_date)
    ex["p_date"] = ex["p_date"].map(db.to_date)
    days = sorted({*ex["expiry"], *ex["p_date"]})
    closes = db.query_df(store, f"SELECT date, close FROM index_ohlc_daily WHERE symbol = ? AND date IN ({', '.join('?' for _ in days)})", [name, *days])
    close_of = {db.to_date(d): float(c) for d, c in zip(closes["date"], closes["close"], strict=True) if c is not None and not pd.isna(c)}
    surf = db.query_df(store, f"""SELECT date, expiry, strike, opt_type, price FROM iv_surface_daily WHERE symbol = ? AND price IS NOT NULL
                                  AND date IN ({', '.join('?' for _ in ex['p_date'])})""", [sym, *ex["p_date"]]) if db.table_exists(store, "iv_surface_daily") \
        else pd.DataFrame(columns=["date", "expiry", "strike", "opt_type", "price"])
    if not surf.empty:
        surf["date"] = surf["date"].map(db.to_date)
        surf["expiry"] = surf["expiry"].map(db.to_date)
    rv = db.query_df(store, f"SELECT date, rv20_cc FROM iv_summary_daily WHERE symbol = ? AND date IN ({', '.join('?' for _ in ex['p_date'])})",
                     [sym, *ex["p_date"]]) if db.table_exists(store, "iv_summary_daily") else pd.DataFrame(columns=["date", "rv20_cc"])
    rv_of = {db.to_date(d): (None if v is None or pd.isna(v) else float(v)) for d, v in zip(rv["date"], rv["rv20_cc"], strict=True)}
    rows = []
    for rec in ex.to_dict(orient="records"):
        e, p, fwd = rec["expiry"], rec["p_date"], rec["forward"]
        if fwd is None or pd.isna(fwd) or e not in close_of:
            continue
        fwd = float(fwd)
        strad = None
        k_used = None
        if not surf.empty:
            s = surf[(surf["date"] == p) & (surf["expiry"] == e)]
            piv = s.pivot_table(index="strike", columns="opt_type", values="price", aggfunc="first")
            if {"CE", "PE"} <= set(piv.columns):
                piv = piv.dropna(subset=["CE", "PE"])
                if not piv.empty:
                    k_used = float(min(piv.index, key=lambda k: abs(k - fwd)))
                    strad = float(piv.loc[k_used, "CE"] + piv.loc[k_used, "PE"])
        realised = (close_of[e] / fwd - 1) * 100
        dte = int(rec["dte"]) if rec["dte"] is not None and not pd.isna(rec["dte"]) else (e - p).days
        rv20 = rv_of.get(p)
        naive = rv20 * math.sqrt(dte / 365.0) * math.sqrt(2 / math.pi) if rv20 is not None else None
        implied = strad / fwd * 100 if strad is not None else None
        rows.append({"expiry": e.isoformat(), "priced_on": p.isoformat(), "dte": dte, "forward": round(fwd, 2), "strike": k_used,
                     "straddle": None if strad is None else round(strad, 2), "implied_move_pct": None if implied is None else round(implied, 3),
                     "implied_1sd_pct": None if rec["expected_move_pct"] is None or pd.isna(rec["expected_move_pct"]) else round(float(rec["expected_move_pct"]), 3),
                     "settle": round(close_of[e], 2), "realised_move_pct": round(realised, 3),
                     "ratio": None if not implied else round(abs(realised) / implied, 3),
                     "exceeded": None if implied is None else bool(abs(realised) > implied),
                     "naive_move_pct": None if naive is None else round(naive, 3), "implied_recorded_at": db.iso_utc(rec["first_seen_at"])})
    scored = [r for r in rows if r["implied_move_pct"] is not None]
    stats: dict[str, Any] = {"n": len(scored)}
    if scored:
        ratios = sorted(r["ratio"] for r in scored)
        err_i = [abs(abs(r["realised_move_pct"]) - r["implied_move_pct"]) for r in scored]
        both = [r for r in scored if r["naive_move_pct"] is not None]
        stats.update({"exceeded_pct": round(100 * sum(r["exceeded"] for r in scored) / len(scored), 1), "fair_exceeded_pct": FAIR_EXCEED_RATE,
                      "median_ratio": round(float(np.median(ratios)), 3), "mean_ratio": round(float(np.mean(ratios)), 3),
                      "mean_abs_miss_pct": round(float(np.mean(err_i)), 3)})
        if both:
            err_n = [abs(abs(r["realised_move_pct"]) - r["naive_move_pct"]) for r in both]
            err_ib = [abs(abs(r["realised_move_pct"]) - r["implied_move_pct"]) for r in both]
            stats.update({"naive_mean_abs_miss_pct": round(float(np.mean(err_n)), 3), "implied_closer": int(sum(a < b for a, b in zip(err_ib, err_n, strict=True))),
                          "compared": len(both)})
    return {"rows": rows[::-1], "stats": stats, "badge": "arithmetic",
            "definition": ("implied = ATM straddle at the last close before expiry ÷ forward; realised = the expiry-day close ÷ that forward − 1; "
                           "the fair reference (fair_exceeded_pct) is P(|Z| > √(2/π)) under a normal; before costs"),
            "verdict": f"Implied vs realised on past expiries: {DESCRIBES}"}


def expiry_day(store: Any, symbol: str, *, day: date | None = None, now: datetime | None = None, parquet_root: Path | None = None,
               n_score: int = 26) -> dict[str, Any]:
    """XPRY: on an expiry day the expiring series' OI unwind by strike, the max-pain path, today's straddle decay against the
    historical expiry-day curve, the pin-risk strikes; every day the next expiry, the curve and the scorecard."""
    sym = symbol.upper()
    now = now or db.utcnow()
    today = day or to_ist(now).date()
    ups = upcoming_expiries(store, sym, today)
    is_exp = bool(ups) and ups[0] == today
    if not is_exp and day is not None and today in stored_expiries(store, sym, since=today, until=today):
        is_exp = True                                       # a past expiry day asked by date
    out: dict[str, Any] = {"symbol": sym, "date": today.isoformat(), "is_expiry_day": is_exp,
                           "next_expiry": next((e.isoformat() for e in ups if e > today or (e == today and not is_exp)), None),
                           "badge": "context", "verdict": f"Expiry-day view: {DESCRIBES}"}
    past = stored_expiries(store, sym, until=today - timedelta(days=1))
    out["last_expiry"] = past[-1].isoformat() if past else None
    live: dict[str, Any] = {"snapshots": 0}
    if is_exp:
        df = load_day(store, sym, today, expiry=today)
        path = tape_path(df)
        spot = path[-1]["spot"] if path else None
        strikes = oi_by_strike(df, latest_raw(parquet_root, today, sym, today), around=spot, width=15)
        live = {"snapshots": len(path), "first": path[0]["ist"] if path else None, "last": path[-1]["ist"] if path else None,
                "last_ts": path[-1]["ts"] if path else None, "spot": spot, "path": [{k: p[k] for k in ("ts", "ist", "forward", "spot", "max_pain",
                "straddle", "straddle_open_strike", "atm_iv", "pcr")} for p in path], "unwind": strikes, "pin_risk": pin_risk(strikes, spot),
                "decay": decay_today(path), "open_strike": path[0]["open_strike"] if path else None,
                "source": path[-1]["source"] if path else "OFFLINE"}
    out["live"] = live
    start = int(live["decay"][0]["minute"]) if live.get("decay") else 0
    out["curve"] = replay_curve(store, sym, before=today, start_minute=max(0, start if start > 5 else 0))
    if live.get("decay") and out["curve"]["points"]:
        m = live["decay"][-1]["minute"]
        ref = min(out["curve"]["points"], key=lambda p: abs(p["minute"] - m))
        live["vs_curve"] = {"minute": m, "today_pct": live["decay"][-1]["pct_of_open"], "median_pct": ref["median"], "p25": ref["p25"],
                            "p75": ref["p75"], "n": ref["n"]}
    out["scorecard"] = scorecard(store, sym, n=n_score, before=today + timedelta(days=1) if not is_exp else today)
    return out


# ── the expiry replay backfill (O-T16; the PM runs it after the close) ──────────────────────────────────────────────

FREEZE = ((time(7, 45), time(9, 20)), (time(9, 15), time(15, 30)), (time(18, 30), time(21, 15)))


def replay_window_ok(now_ist: datetime) -> tuple[bool, str]:
    """Never inside the freeze windows (07:45–09:20, 18:30–21:15) or the session (the tape owns the budget then)."""
    if now_ist.weekday() >= 5:
        return True, "weekend"
    for lo, hi in FREEZE:
        if lo <= now_ist.time() <= hi:
            return False, f"inside {lo:%H:%M}–{hi:%H:%M} IST ({now_ist:%H:%M}); run after 15:30 outside the freeze windows"
    return True, "ok"


def _strike_step(store: Any, symbol: str, p_date: date | None, expiry: date) -> float:
    if p_date is not None and db.table_exists(store, "iv_surface_daily"):
        df = db.query_df(store, "SELECT DISTINCT strike FROM iv_surface_daily WHERE symbol = ? AND date = ? AND expiry = ? ORDER BY strike",
                         [symbol, p_date, expiry])
        ks = df["strike"].astype(float).to_numpy()
        if len(ks) >= 3:
            diffs = np.diff(ks)
            diffs = diffs[diffs > 0]
            if len(diffs):
                return float(pd.Series(diffs).mode().iloc[0])
    return DEFAULT_STEPS.get(symbol, 50.0)


def bars_to_rows(ce: list[dict[str, Any]], pe: list[dict[str, Any]], *, symbol: str, expiry: date, strike: float, spot_open: float | None,
                 now: datetime) -> list[dict[str, Any]]:
    """Breeze 1-minute option bars (``datetime`` is IST wall time) → replay rows keyed by minute (both sides required), ``ts``
    stored UTC-naive like every other table."""
    def by_min(rows: list[dict[str, Any]]) -> dict[pd.Timestamp, dict[str, Any]]:
        out = {}
        for r in rows or []:
            try:
                t = pd.Timestamp(str(r.get("datetime"))[:19]).floor("min")
            except ValueError:
                continue
            out[t] = r
        return out
    c, p = by_min(ce), by_min(pe)
    rows = []
    for t in sorted(set(c) & set(p)):
        cc, pc = _f(c[t].get("close")), _f(p[t].get("close"))
        ts_utc = ist_wall_to_utc(t.date(), t.time())          # the store's convention: UTC-naive
        rows.append({"symbol": symbol, "expiry": expiry, "ts": ts_utc, "strike": strike, "ce_close": cc, "pe_close": pc,
                     "ce_oi": _f(c[t].get("open_interest")), "pe_oi": _f(p[t].get("open_interest")), "ce_volume": _f(c[t].get("volume")),
                     "pe_volume": _f(p[t].get("volume")), "straddle": (cc + pc) if cc is not None and pc is not None else None,
                     "spot_open": spot_open, "source": "breeze_1m", "first_seen_at": now})
    return rows


def fetch_option_bars(breeze: Any, budget: Any, *, code: str, expiry: date, strike: float, right: str, day: date,
                      caller: str = REPLAY_CALLER) -> list[dict[str, Any]]:
    """One metered ``get_historical_data_v2`` call: 1-minute bars of one option on ``day`` (≤ 376 bars, one call)."""
    with budget.guard(caller, HIST_METHOD):
        resp = breeze.get_historical_data_v2(interval="1minute", from_date=f"{day.isoformat()}T09:15:00.000Z", to_date=f"{day.isoformat()}T15:30:00.000Z",
                                             stock_code=code, exchange_code="NFO", product_type="options", expiry_date=breeze_expiry(expiry),
                                             right=right, strike_price=str(int(strike)) if float(strike).is_integer() else str(strike))
    rows = resp.get("Success") if isinstance(resp, dict) else resp
    return list(rows or [])


def run_expiry_replay(store: Any, breeze: Any, budget: Any, *, symbols: Iterable[str] = ("NIFTY",), since: date | None = None,
                      until: date | None = None, now: datetime | None = None, max_calls: int = 120, force: bool = False,
                      pace_s: float = 1.1, master: Mapping[str, str] | None = None, sleep: Callable[[float], None] = _time.sleep) -> dict[str, Any]:
    """Backfill ``iv_expiry_replay``: per past expiry E, the ATM strike at E's open (NSE's index open, else the last close), the
    call and put 1-minute bars of E (2 metered calls), stored by minute. Resumable (stored expiries are skipped); ≤ ``max_calls``."""
    now = now or db.utcnow()
    ok, why = replay_window_ok(to_ist(now))
    if not ok and not force:
        return {"job": "expiry_replay", "status": "skipped", "reason": why, "calls": 0}
    if budget is None:
        return {"job": "expiry_replay", "status": "skipped", "reason": "no budget ledger: Breeze is never called unmetered", "calls": 0}
    if breeze is None:
        return {"job": "expiry_replay", "status": "skipped", "reason": "Breeze session not live", "calls": 0}
    ensure_replay_schema(store)
    today = to_ist(now).date()
    codes = master if master is not None else master_codes()
    done = db.query_df(store, "SELECT DISTINCT symbol, expiry FROM iv_expiry_replay")
    have = {(str(s), db.to_date(e)) for s, e in zip(done["symbol"], done["expiry"], strict=True)}
    calls, stored, errors, todo_left = 0, 0, [], 0
    per_symbol: dict[str, int] = {}
    refused = False
    for sym in [s.upper() for s in symbols]:
        if refused:
            break
        name = INDEX_NAMES.get(sym)
        exps = [e for e in stored_expiries(store, sym, since=since or today - timedelta(days=200), until=min(until or today, today - timedelta(days=1)))
                if (sym, e) not in have]
        for e in exps:
            if calls + 2 > max_calls:
                todo_left += 1
                continue
            p_date = db.to_date(db.scalar(store, "SELECT MAX(date) FROM iv_expiry_daily WHERE symbol = ? AND expiry = ? AND date < ?", [sym, e, e]))
            spot = None
            if name and db.table_exists(store, "index_ohlc_daily"):
                row = store.read_one("SELECT open, close FROM index_ohlc_daily WHERE symbol = ? AND date = ?", [name, e])
                spot = _f(row[0]) if row else None
                if spot is None and p_date is not None:
                    prev = store.read_one("SELECT close FROM index_ohlc_daily WHERE symbol = ? AND date = ?", [name, p_date])
                    spot = _f(prev[0]) if prev else None
            if spot is None:
                errors.append(f"{sym} {e}: no index open or previous close stored")
                continue
            step = _strike_step(store, sym, p_date, e)
            k = round(spot / step) * step
            try:
                ce = fetch_option_bars(breeze, budget, code=breeze_code(sym, codes), expiry=e, strike=k, right="call", day=e)
                calls += 1
                sleep(pace_s)
                pe = fetch_option_bars(breeze, budget, code=breeze_code(sym, codes), expiry=e, strike=k, right="put", day=e)
                calls += 1
                sleep(pace_s)
            except Exception as exc:  # noqa: BLE001 — a refusal ends the run; an SDK error skips the expiry
                if type(exc).__name__ == "BudgetExceeded":
                    errors.append(f"{sym} {e}: budget refused ({exc})")
                    refused = True
                    break
                calls += 1
                errors.append(f"{sym} {e}: {type(exc).__name__}")
                continue
            rows = bars_to_rows(ce, pe, symbol=sym, expiry=e, strike=k, spot_open=spot, now=now)
            stored += db.upsert(store, "iv_expiry_replay", pd.DataFrame(rows), REPLAY_COLUMNS, REPLAY_CASTS) if rows else 0
            per_symbol[sym] = per_symbol.get(sym, 0) + (1 if rows else 0)
    return {"job": "expiry_replay", "status": "ok" if not errors else "degraded", "calls": calls, "rows": stored, "expiries": per_symbol,
            "remaining": todo_left, "errors": errors[:20], "caller": REPLAY_CALLER}

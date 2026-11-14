"""The Breeze budget ledger (Terminal v2 PLAN §0.11, B3): ONE module every ICICI Breeze caller passes through.

ICICI documents 100 calls/min and 5,000 calls/day per app, shared by every caller in every process (the live-quote
provider, the tick engine, the chain poller, margin calls, the gold capture, the broker book). Those documented limits
are the CEILING; the owner's cap (O-T6, pending — defaults below) is the BUDGET. The ledger keeps a per-minute and a
per-day counter persisted to SQLite (so the counters survive a restart and are shared across the three processes on
this Mac), a per-caller daily quota, and a HARD STOP at the cap: ``acquire`` raises ``BudgetExceeded`` before the
SDK method runs, never after.

Usage (sync; the SDK is sync and runs on worker threads)::

    from shared.breeze_budget import ledger, BudgetExceeded
    with ledger().guard("ui-api.margin", "margin_calculator") as call:   # raises BudgetExceeded past the cap
        resp = breeze.margin_calculator(legs, "NFO")

Rules:
* the day is the IST calendar day (ICICI's quota resets on their clock; IST is the conservative reading);
* the minute is a sliding 60 s window;
* ``cap_day`` / ``cap_minute`` are clamped to the documented ceiling even when the environment asks for more;
* a caller's quota is only its own share — the global cap still wins;
* refusals are recorded too (``status()`` reports them) and exported as ``breeze_budget_used`` gauges;
* nothing here opens a socket; the ledger never prints tokens or any ``.env`` value.

Environment: ``BREEZE_BUDGET_DB`` (SQLite path; under pytest a temp file so a test can never write ``data/``),
``BREEZE_BUDGET_CAP_DAY`` (default 4000), ``BREEZE_BUDGET_CAP_MINUTE`` (default 60),
``BREEZE_BUDGET_QUOTAS`` (``caller=n,caller=n``; defaults ``iv_intraday=800,ui-api.login=500``, …).
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

DOC_LIMIT_PER_MINUTE = 100          # ICICI Breeze documented ceiling (R-IV §2 / R-OPTIONS §4: "100/min, 5,000/day shared")
DOC_LIMIT_PER_DAY = 5000
DEFAULT_CAP_PER_MINUTE = 60         # the owner's budget, below the ceiling (O-T6 pending; PLAN 1.1: "≤ 30/min" for the poller)
DEFAULT_CAP_PER_DAY = 4000
DEFAULT_CALLER_QUOTAS: dict[str, int] = {
    # `chain_poller` was removed (F15): it was the O-T6 pilot's name and no code ever declared that caller,
    # so it reserved 700/day of a 4,000 cap for something that does not exist while reading as coverage. The
    # companion gate requires a quota for every caller the code DOES declare, so a real chain poller added
    # tomorrow fails the suite until it is given one.
    "iv_intraday": 800,
    # F10-02: until 14 Nov 2026 the live-quote poller was not metered at all, so it had no quota either — and
    # it is the biggest spender in the stack: data-service's NIFTY poller calls get_live_quote whenever the
    # websocket tick is older than 5 s (its own comment prices that at ~1,580/day), and the watchlist poller
    # does the same per STARRED SYMBOL every 15 s with no websocket shortcut, which is unbounded in the number
    # of symbols. Against a 4,000/day cap already promising 1,500 to the chain and IV pilots, an unbounded
    # fallback can empty the day and the first symptom is the chain and margin failing mid-session.
    # 1,500 is deliberately above normal use so it bites only a runaway, and a refusal is now visible on the
    # BRKR chip rather than silent. Tune with BREEZE_BUDGET_QUOTAS once Monday gives a real number.
    "data-service.live_quote": 1500,
    "data-service.intraday": 300,
    "data-service.history": 600,          # a backfill walks this in chunks; it must not own the whole day
    "execution.ltp": 200, "execution.order_status": 200, "execution.portfolio": 100,
    "live_execution.ltp": 200,
    # F11-01: the first pass gave quotas to the callers it had just NAMED in code and left the ones that
    # actually spend unbounded — measured from the live ledger, 7 of 9 entries belonged to callers that had
    # never made a single call, while ui-api.positions (1,039 all-time, including the 14 Nov login runaway)
    # had none. The same scope-not-logic mistake as the gate's roots, one commit later. Every caller that
    # exists in the code now has one, and a test enforces that (test_breeze_budget.py).
          # holdings / funds / positions, plus the metered generate_session
    # Sized against MEASURED per-day peaks from data/breeze_budget.sqlite, not against totals. (F13-08: the
    # "1,038 spent" in an earlier message was an all-time sum, 937 in fact; quotas are per DAY and the peak
    # that matters is 578.) A caller quota caps a share so no one path can empty the day — it is not a second
    # ceiling, and cap_day 4,000 remains the real one.
    #   ui-api.positions  peak 578 (13 Nov)  -> 1200
    #   ui-api.login      peak 115 (14 Nov, a failing-login day, every call a failed generate_session) -> 300
    #   ui-api.probe      peak 122 (13 Nov)  -> 250
    # F13-07: login was first set to 120 against that 115 — 96% of its own bound, the identical arithmetic
    # this same commit had just fixed for positions. A failing TOTP day is exactly when attempts pile up, and
    # a refused generate_session means no broker session for the REST OF THE DAY even if the owner answers
    # the OTP. The one call the terminal cannot do without gets the most headroom, not the least.
    "ui-api.positions": 1200,         # holdings / funds / positions
    # 500 against a MEASURED method-level peak of 202 generate_session calls in a day. The caller-label view
    # showed only 115 because the attempts were split across two labels — which is the same reason both login
    # paths now share one label: a bound you can dodge by relabelling is not a bound. Still an eighth of
    # cap_day 4,000.
    "ui-api.login": 500,              # generate_session only — kept separate so holdings cannot starve it
    "ui-api.probe": 250,              # the connection probe (peak 122)
    "ui-api.margin": 200,             # OSTR's SPAN calls
    "ui-api.gold_settlement": 100,
    "data-service.gold_vwap30": 150,  # the 23:58 MCX settlement VWAP
    "data-service.gold_breeze_daily": 100,
    "iv_expiry_replay": 200,
    # Found by the source gate, NOT by the ledger — neither has spent a call yet, so a ledger-driven list
    # would have missed both. ui-api.mcx is the F6-01 path itself: four Breeze calls that bypassed metering
    # entirely until 14 Nov and still have not run under a live session.
    "ui-api.mcx": 500,               # MCX quotes, 35 s TTL against a 30 s poll across ~5 contracts
    "ui-api.gold-preopen": 100,
    # the Monday MCX-options probe: a hand-run script, but it IS metered, so it gets a bound like everything
    # else rather than an exemption (scripts/probe_mcx_options.py, 2N+2 calls per snapshot)
    "probe.mcx_options": 150,
    # These deliberately SUM ABOVE cap_day: a quota caps one caller's share so no single path can empty the
    # day, while cap_day remains the real ceiling. Scaling them down to sum to the cap would reserve quota for
    # callers that are idle on most days (the execution ones are dormant entirely) and starve the live ones.
}   # O-T6 pilot: ≈ 700/day for the chain poller;
#   iv_intraday = the fo_iv 15-minute pilot's caller name (PLAN 1.1 ≤ 800/day; the pilot also enforces it itself)
MINUTE_WINDOW_S = 60.0
KEEP_DAYS = 3                       # rows older than this are pruned (the ledger stays a few hundred KB)

ENV_DB = "BREEZE_BUDGET_DB"
ENV_CAP_DAY = "BREEZE_BUDGET_CAP_DAY"
ENV_CAP_MINUTE = "BREEZE_BUDGET_CAP_MINUTE"
ENV_QUOTAS = "BREEZE_BUDGET_QUOTAS"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY, ts REAL NOT NULL, day TEXT NOT NULL, caller TEXT NOT NULL, method TEXT NOT NULL,
    ok INTEGER, ms REAL);
CREATE INDEX IF NOT EXISTS calls_day ON calls(day);
CREATE INDEX IF NOT EXISTS calls_ts ON calls(ts);
CREATE TABLE IF NOT EXISTS refusals (
    id INTEGER PRIMARY KEY, ts REAL NOT NULL, day TEXT NOT NULL, caller TEXT NOT NULL, method TEXT NOT NULL,
    reason TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS refusals_day ON refusals(day);
"""


class BudgetExceeded(RuntimeError):
    """Raised by ``acquire`` BEFORE a Breeze call when the minute cap, the day cap or the caller's quota is reached."""

    def __init__(self, decision: Decision) -> None:
        super().__init__(decision.reason)
        self.decision = decision

    @property
    def retry_after_s(self) -> float | None:
        return self.decision.retry_after_s


@dataclass(frozen=True)
class Decision:
    """What the ledger decided for one call: counters as of the decision (the call itself included when allowed)."""

    allowed: bool
    reason: str
    caller: str
    method: str
    used_minute: int
    used_day: int
    caller_used_day: int
    cap_minute: int
    cap_day: int
    caller_quota: int | None
    retry_after_s: float | None = None
    call_id: int | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "allowed": self.allowed, "reason": self.reason, "caller": self.caller, "method": self.method,
            "used_minute": self.used_minute, "used_day": self.used_day, "caller_used_day": self.caller_used_day,
            "cap_minute": self.cap_minute, "cap_day": self.cap_day, "caller_quota": self.caller_quota,
            "retry_after_s": None if self.retry_after_s is None else round(self.retry_after_s, 1),
        }


def ist_day(ts: float) -> str:
    return datetime.fromtimestamp(ts, IST).date().isoformat()


def _clamp_cap(value: int | None, default: int, ceiling: int) -> int:
    v = default if value is None else int(value)
    if v <= 0:
        v = default
    return min(v, ceiling)


def parse_quotas(text: str | None, default: Mapping[str, int] | None = None) -> dict[str, int]:
    """``"iv_intraday=700,ui-api.login=400"`` → dict; malformed items are ignored; defaults fill the rest."""
    out = dict(default or DEFAULT_CALLER_QUOTAS)
    for item in (text or "").split(","):
        if "=" not in item:
            continue
        k, v = item.split("=", 1)
        with suppress(ValueError):
            n = int(v.strip())
            if n > 0 and k.strip():
                out[k.strip()] = n
    return out


class BreezeBudget:
    """The SQLite-backed ledger. Thread-safe; one instance per process is enough (``ledger()``), but several
    processes may share one file (SQLite's own locking; writes are a single INSERT each)."""

    def __init__(self, path: Path | str, *, cap_minute: int | None = None, cap_day: int | None = None,
                 quotas: Mapping[str, int] | None = None, clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path)
        self.cap_minute = _clamp_cap(cap_minute, DEFAULT_CAP_PER_MINUTE, DOC_LIMIT_PER_MINUTE)
        self.cap_day = _clamp_cap(cap_day, DEFAULT_CAP_PER_DAY, DOC_LIMIT_PER_DAY)
        self.quotas: dict[str, int] = dict(DEFAULT_CALLER_QUOTAS if quotas is None else quotas)
        self._clock = clock
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=5.0, isolation_level=None)
        with suppress(sqlite3.DatabaseError):
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self._last_prune = 0.0

    # ── counters ────────────────────────────────────────────────────────────────────────────────────────────
    def _counts(self, now: float, caller: str) -> tuple[int, int, int]:
        day = ist_day(now)
        cur = self._conn.execute(
            "SELECT (SELECT COUNT(*) FROM calls WHERE ts > ?), (SELECT COUNT(*) FROM calls WHERE day = ?), "
            "(SELECT COUNT(*) FROM calls WHERE day = ? AND caller = ?)",
            (now - MINUTE_WINDOW_S, day, day, caller))
        m, d, c = cur.fetchone()
        return int(m), int(d), int(c)

    def _oldest_in_minute(self, now: float) -> float | None:
        row = self._conn.execute("SELECT MIN(ts) FROM calls WHERE ts > ?", (now - MINUTE_WINDOW_S,)).fetchone()
        return float(row[0]) if row and row[0] is not None else None

    def _seconds_to_ist_midnight(self, now: float) -> float:
        dt = datetime.fromtimestamp(now, IST)
        midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        return max(1.0, 86400.0 - (dt - midnight).total_seconds())

    # ── the decision ────────────────────────────────────────────────────────────────────────────────────────
    def decide(self, caller: str, method: str = "") -> Decision:
        """The decision WITHOUT recording anything (a dry run for status pages and schedulers)."""
        with self._lock:
            now = self._clock()
            return self._decide_locked(now, caller, method)

    def _decide_locked(self, now: float, caller: str, method: str) -> Decision:
        used_m, used_d, used_c = self._counts(now, caller)
        quota = self.quotas.get(caller)

        def decision(allowed: bool, reason: str, retry_after_s: float | None = None) -> Decision:
            return Decision(allowed, reason, caller, method, used_m, used_d, used_c, self.cap_minute, self.cap_day, quota,
                            retry_after_s)

        if used_d + 1 > self.cap_day:
            return decision(False, f"day cap reached ({used_d}/{self.cap_day} Breeze calls today, IST)",
                            self._seconds_to_ist_midnight(now))
        if quota is not None and used_c + 1 > quota:
            return decision(False, f"caller quota reached ({caller}: {used_c}/{quota} today)", self._seconds_to_ist_midnight(now))
        if used_m + 1 > self.cap_minute:
            oldest = self._oldest_in_minute(now)
            wait = (oldest + MINUTE_WINDOW_S - now) if oldest is not None else MINUTE_WINDOW_S
            return decision(False, f"minute cap reached ({used_m}/{self.cap_minute} in the last 60 s)", max(0.1, wait))
        return decision(True, "ok")

    def acquire(self, caller: str, method: str = "") -> Decision:
        """Record one call if the budget allows it (counters include it), else record the refusal and raise."""
        with self._lock:
            now = self._clock()
            d = self._decide_locked(now, caller, method)
            if not d.allowed:
                self._conn.execute("INSERT INTO refusals(ts, day, caller, method, reason) VALUES (?,?,?,?,?)",
                                   (now, ist_day(now), caller, method, d.reason))
                self._gauges(d.used_minute, d.used_day)
                raise BudgetExceeded(d)
            cur = self._conn.execute("INSERT INTO calls(ts, day, caller, method) VALUES (?,?,?,?)",
                                     (now, ist_day(now), caller, method))
            call_id = int(cur.lastrowid or 0)
            d = Decision(True, "ok", caller, method, d.used_minute + 1, d.used_day + 1, d.caller_used_day + 1,
                         d.cap_minute, d.cap_day, d.caller_quota, None, call_id)
            self._gauges(d.used_minute, d.used_day)
            self._maybe_prune(now)
            return d

    def complete(self, call_id: int | None, ok: bool, ms: float | None = None) -> None:
        """Mark the outcome of a recorded call (an SDK error still counts against the budget: ICICI counted it)."""
        if call_id is None:
            return
        with self._lock, suppress(sqlite3.DatabaseError):
            self._conn.execute("UPDATE calls SET ok = ?, ms = ? WHERE id = ?", (1 if ok else 0, ms, call_id))

    @contextmanager
    def guard(self, caller: str, method: str = "") -> Iterator[Decision]:
        """``with ledger().guard(caller, method):`` — acquires (or raises ``BudgetExceeded``), then records the outcome."""
        d = self.acquire(caller, method)
        t0 = self._clock()
        try:
            yield d
        except BaseException:
            self.complete(d.call_id, False, (self._clock() - t0) * 1000)
            raise
        else:
            self.complete(d.call_id, True, (self._clock() - t0) * 1000)

    # ── reporting ───────────────────────────────────────────────────────────────────────────────────────────
    def status(self) -> dict[str, object]:
        """Counters for the SYS page / ``/api/positions/breeze-budget`` (no secrets, no URLs)."""
        with self._lock:
            now = self._clock()
            day = ist_day(now)
            used_m, used_d, _ = self._counts(now, "")
            by_caller = {str(c): int(n) for c, n in self._conn.execute(
                "SELECT caller, COUNT(*) FROM calls WHERE day = ? GROUP BY caller ORDER BY 2 DESC", (day,))}
            by_method = {str(m): int(n) for m, n in self._conn.execute(
                "SELECT method, COUNT(*) FROM calls WHERE day = ? GROUP BY method ORDER BY 2 DESC", (day,))}
            refused = int(self._conn.execute("SELECT COUNT(*) FROM refusals WHERE day = ?", (day,)).fetchone()[0])
            errors = int(self._conn.execute("SELECT COUNT(*) FROM calls WHERE day = ? AND ok = 0", (day,)).fetchone()[0])
            last = self._conn.execute("SELECT ts, caller, method, ok FROM calls ORDER BY id DESC LIMIT 1").fetchone()
        return {
            "day_ist": day, "used_day": used_d, "cap_day": self.cap_day, "ceiling_day": DOC_LIMIT_PER_DAY,
            "used_minute": used_m, "cap_minute": self.cap_minute, "ceiling_minute": DOC_LIMIT_PER_MINUTE,
            "remaining_day": max(0, self.cap_day - used_d), "quotas": dict(self.quotas),
            "by_caller": by_caller, "by_method": by_method, "refused_today": refused, "errors_today": errors,
            "last_call": None if last is None else {"at": datetime.fromtimestamp(last[0], IST).isoformat(timespec="seconds"),
                                                     "caller": last[1], "method": last[2], "ok": last[3]},
            "path": self.path.name,
        }

    def _gauges(self, used_minute: int, used_day: int) -> None:
        with suppress(Exception):                      # metrics are optional (shared/metrics.py degrades to no-ops)
            from shared.metrics import set_breeze_budget
            set_breeze_budget("minute", used_minute)
            set_breeze_budget("day", used_day)

    def _maybe_prune(self, now: float) -> None:
        if now - self._last_prune < 3600:
            return
        self._last_prune = now
        cutoff = now - KEEP_DAYS * 86400
        with suppress(sqlite3.DatabaseError):
            self._conn.execute("DELETE FROM calls WHERE ts < ?", (cutoff,))
            self._conn.execute("DELETE FROM refusals WHERE ts < ?", (cutoff,))

    def close(self) -> None:
        with self._lock, suppress(sqlite3.DatabaseError):
            self._conn.close()


# ── the process-wide ledger ─────────────────────────────────────────────────────────────────────────────────
_singleton: BreezeBudget | None = None
_singleton_lock = threading.Lock()


def _in_test_mode() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST")) and "pytest" in sys.modules


def default_path() -> Path:
    env = os.environ.get(ENV_DB, "").strip()
    if env:
        return Path(env)
    if _in_test_mode():                                # a test never writes data/ (LIVE STACK OFF LIMITS)
        return Path(tempfile.gettempdir()) / "suryadhana-tests" / f"breeze_budget-{os.getpid()}.sqlite"
    for root in (Path(__file__).resolve().parents[1] / "data", Path("/app/data")):
        if root.is_dir():
            return root / "breeze_budget.sqlite"
    return Path("breeze_budget.sqlite")


def _env_int(name: str) -> int | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def ledger() -> BreezeBudget:
    """The process-wide ledger, built from the environment on first use (``reset_ledger()`` for tests)."""
    global _singleton
    with _singleton_lock:
        path = default_path()
        if _singleton is None or _singleton.path != path:
            _singleton = BreezeBudget(path, cap_minute=_env_int(ENV_CAP_MINUTE), cap_day=_env_int(ENV_CAP_DAY),
                                      quotas=parse_quotas(os.environ.get(ENV_QUOTAS)))
        return _singleton


def reset_ledger() -> None:
    """Tests: drop the singleton so the next ``ledger()`` re-reads the environment."""
    global _singleton
    with _singleton_lock:
        if _singleton is not None:
            _singleton.close()
        _singleton = None

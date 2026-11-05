"""
Tick persistence + intraday bars/VWAP (worldclass program W6 — closes "ticks are memory-only",
QuantLab adoption A4; GAPS §1 "VWAP / session volume profile" MISS-B; feeds W1's chart studio).

Design
------
- `TickStore.append(symbol, tick)` is called from live_ticks' `_on_tick` (socketio receive thread):
  it must stay O(µs) — one normalize + one deque append under a lock, no IO, never raises
  (bad rows are dropped and counted as `append_strikes`).
- A single daemon flusher thread (owned by the store, started lazily on the first append,
  stoppable) drains the buffer every FLUSH_S=30 s and on shutdown. Each drain writes **numbered
  part files** `data/ticks/YYYY-MM-DD/part-NNNN.parquet` (append to parquet = read-modify-write
  is wrong; parts + glob-read is the correct pattern). Writes go to a dot-prefixed temp file in
  the same directory, then `os.replace` (atomic on POSIX): a partial/crashed part can never
  corrupt earlier parts, and readers never see a half-written file.
- Bounded: buffer capped at BUFFER_CAP=50 000 rows (drop-oldest + `dropped` counter — never OOM).
  Rows that fail to flush (e.g. disk full) are dropped and counted (`rows_lost_on_flush_error`)
  rather than re-queued forever.
- Columns (one row per L1 tick): symbol, ts (IST ISO), price, qty (per-tick, if the feed sends
  one), ttq (cumulative day volume as Breeze sends it), bid, ask, prev_close. Explicit pyarrow
  schema so every part has identical dtypes and a day's parts always concat cleanly.
- Volume semantics (the part people get wrong): Breeze `ttq` is the *cumulative* traded quantity.
  Per symbol+day: if ttq is monotone non-decreasing (≥99 % of steps, tolerating one feed reset),
  per-tick volume = diff(ttq) clipped at 0 and the first observation contributes 0 (volume traded
  before we subscribed is unattributable — VWAP is "since first tick seen", stated honestly).
  Otherwise fall back to summing per-tick qty; with neither, volume is 0 and VWAP is null.
- Kill switch: TICK_PERSIST (default **ON**). The hook in live_ticks constructs the store lazily
  only when a tick actually flows, so with LIVE_TICKS=0 (no websocket) this module costs nothing;
  with LIVE_TICKS=1 persistence is on unless TICK_PERSIST=0. Env is read once per worker life.
- Storage dir: TICKS_DIR env override, else <repo>/data/ticks (same data/ dir as market.duckdb;
  this module NEVER touches the DuckDB). No retention job tonight — rotation/compaction of old
  day-dirs is a stated follow-up.

Endpoints (mounted on the data-service app by the PM):
  GET /ticks/bars?symbol=&date=YYYY-MM-DD&interval=1m|5m|15m
      → {"symbol","date","interval","bars":[{"t":"HH:MM","o","h","l","c","v"}],
         "vwap":float|null,"source":"icici-ws"}            (contract frozen for W1 — do not rename)
      missing day/symbol → 200 with empty bars + note.
  GET /ticks/vwap?symbol=&date=   → running VWAP + total observed volume.
  GET /ticks/store-status         → buffer size, rows flushed today, last flush, drops, strikes.
Routes are sync defs (FastAPI runs them in the threadpool): pandas work never blocks the loop.
pandas/pyarrow are imported inside functions so importing this module stays cheap for live_ticks.
"""
from __future__ import annotations

import os
import re
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pytz
from fastapi import APIRouter, Query

from shared.logging import get_logger

logger = get_logger("tick-store")

IST = pytz.timezone("Asia/Kolkata")

FLUSH_S = 30.0                       # flusher cadence
BUFFER_CAP = 50_000                  # drop-oldest beyond this — never OOM
SOURCE = "icici-ws"                  # provenance label in every payload (W1 contract)

COLS = ["symbol", "ts", "price", "qty", "ttq", "bid", "ask", "prev_close"]
NUMERIC_COLS = COLS[2:]
_FREQ = {"1m": "1min", "5m": "5min", "15m": "15min"}      # pandas 3.x spellings ("T" is gone)
_TS_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T")          # guards dir names against junk ts
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONOTONE_FRACTION = 0.99            # ttq treated as cumulative when ≥99 % of steps are ≥ 0

_PA_SCHEMA: Any = None               # built lazily — keeps module import light


def persist_enabled() -> bool:
    """TICK_PERSIST kill switch, default ON. The live_ticks hook only consults this when a tick
    actually flows, i.e. when LIVE_TICKS=1 armed the websocket — so the default is effectively
    "persist whenever ticks flow" and costs nothing while LIVE_TICKS=0. Set TICK_PERSIST=0 to
    stream without writing. Read once per worker life (flipping it needs a restart)."""
    return os.getenv("TICK_PERSIST", "1") == "1"


def default_base_dir() -> Path:
    """TICKS_DIR env override, else <repo>/data/ticks (parent dir of market.duckdb)."""
    env = os.getenv("TICKS_DIR", "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "data" / "ticks"


def _ist_now_iso() -> str:
    return datetime.now(IST).isoformat(timespec="seconds")


def _ist_today() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


def _f(v: Any) -> Optional[float]:
    """Safe float-or-None; never raises."""
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _pa_schema() -> Any:
    global _PA_SCHEMA
    if _PA_SCHEMA is None:
        import pyarrow as pa
        _PA_SCHEMA = pa.schema([
            ("symbol", pa.string()), ("ts", pa.string()), ("price", pa.float64()),
            ("qty", pa.float64()), ("ttq", pa.float64()), ("bid", pa.float64()),
            ("ask", pa.float64()), ("prev_close", pa.float64()),
        ])
    return _PA_SCHEMA


def _normalize_symbol(s: str) -> str:
    return s.strip().upper().replace(".NS", "").replace(".BO", "")


def _next_part_index(day_dir: Path) -> int:
    """Max existing part number + 1 — rescanned per flush so a restarted process continues
    numbering instead of overwriting."""
    best = -1
    for p in day_dir.glob("part-*.parquet"):
        try:
            best = max(best, int(p.stem.split("-", 1)[1]))
        except (ValueError, IndexError):
            continue
    return best + 1


class TickStore:
    """Bounded in-memory tick buffer + lazy daemon flusher → daily parquet part files.

    `flush_s=None` disables the background thread entirely (tests drive `flush()` manually).
    Thread-safety: `append` (socketio thread) and the flusher share one lock; parquet IO happens
    outside the lock so appends never wait on disk.
    """

    def __init__(self, base_dir: Optional[Path | str] = None,
                 flush_s: Optional[float] = FLUSH_S, buffer_cap: int = BUFFER_CAP) -> None:
        self._base = Path(base_dir) if base_dir is not None else default_base_dir()
        self._flush_s = flush_s
        self._lock = threading.Lock()
        # Part writes are serialized: two overlapping flushes (shutdown's final flush racing a slow
        # in-flight one past stop()'s 10 s join) would pick the same part index and the second
        # os.replace would overwrite the first part — silently losing those ticks.
        self._write_lock = threading.Lock()
        self._buf: deque[dict[str, Any]] = deque(maxlen=max(int(buffer_cap), 1))
        self._thread: Optional[threading.Thread] = None
        self._stop_ev = threading.Event()
        self._stopped = False
        # counters (all mutated under the lock)
        self._appended = 0
        self._dropped = 0                   # buffer-cap evictions
        self._strikes = 0                   # rows rejected by append (bad symbol/price)
        self._flushed_total = 0
        self._rows_today = 0
        self._flush_day = _ist_today()
        self._parts_written = 0
        self._flush_errors = 0
        self._rows_lost = 0                 # rows dropped because a part write failed
        self._last_error: Optional[str] = None
        self._last_flush_at: Optional[str] = None
        self._last_flush_rows = 0

    # ── hot path ─────────────────────────────────────────────────────────────

    def append(self, symbol: Any, tick: dict) -> bool:
        """Buffer one live_ticks row. O(µs), never raises: a malformed row is dropped and
        counted in `append_strikes`. Returns True when the row was buffered."""
        try:
            sym = _normalize_symbol(str(symbol))
            price = float(tick["price"])
            if not sym or len(sym) > 24:
                raise ValueError("bad symbol")
        except Exception:  # noqa: BLE001 — strike, never break the feed
            with self._lock:
                self._strikes += 1
            return False
        ts = str(tick.get("as_of") or "")
        if not _TS_DATE_RE.match(ts):
            ts = _ist_now_iso()             # also guards the YYYY-MM-DD dir name against junk
        row = {"symbol": sym, "ts": ts, "price": price,
               "qty": _f(tick.get("qty") if tick.get("qty") is not None else tick.get("ltq")),
               "ttq": _f(tick.get("ttq")), "bid": _f(tick.get("bid")), "ask": _f(tick.get("ask")),
               "prev_close": _f(tick.get("prev_close"))}
        with self._lock:
            if len(self._buf) == self._buf.maxlen:
                self._dropped += 1          # deque(maxlen) evicts the oldest row silently
            self._buf.append(row)
            self._appended += 1
        if self._flush_s is not None and self._thread is None and not self._stopped:
            self._start_flusher()
        return True

    # ── flusher ──────────────────────────────────────────────────────────────

    def _start_flusher(self) -> None:
        with self._lock:
            if self._stopped or (self._thread is not None and self._thread.is_alive()):
                return
            self._thread = threading.Thread(target=self._run, name="tick-store-flush", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        while not self._stop_ev.wait(self._flush_s):
            try:
                self.flush()
            except Exception as exc:  # noqa: BLE001 — the flusher must survive anything
                with self._lock:
                    self._flush_errors += 1
                    self._last_error = f"{type(exc).__name__}: {exc}"[:200]
        try:
            self.flush()                    # final drain on shutdown
        except Exception:  # noqa: BLE001
            pass

    def flush(self) -> int:
        """Drain the buffer to parquet parts (one part per day present in the drain).
        Returns rows written. Safe to call from tests / shutdown even with no thread."""
        with self._lock:
            if not self._buf:
                return 0
            rows = list(self._buf)
            self._buf.clear()
        by_date: dict[str, list[dict]] = {}
        for r in rows:
            by_date.setdefault(r["ts"][:10], []).append(r)
        written = 0
        with self._write_lock:
            for day, day_rows in sorted(by_date.items()):
                try:
                    written += self._write_part(day, day_rows)
                except Exception as exc:  # noqa: BLE001 — drop + count; re-queueing would grow forever
                    with self._lock:
                        self._flush_errors += 1
                        self._rows_lost += len(day_rows)
                        self._last_error = f"{type(exc).__name__}: {exc}"[:200]
        today = _ist_today()
        with self._lock:
            if self._flush_day != today:
                self._flush_day, self._rows_today = today, 0
            self._rows_today += written
            self._flushed_total += written
            self._last_flush_at = _ist_now_iso()
            self._last_flush_rows = written
        return written

    def _write_part(self, day: str, rows: list[dict]) -> int:
        """Atomic part write: temp file in the same dir, then os.replace. A crash mid-write
        leaves only a dot-prefixed temp that no reader globs — earlier parts stay intact."""
        import pyarrow as pa  # noqa: F401 — deferred heavy import
        import pyarrow.parquet as pq
        day_dir = self._base / day
        day_dir.mkdir(parents=True, exist_ok=True)
        n = _next_part_index(day_dir)
        final = day_dir / f"part-{n:04d}.parquet"
        tmp = day_dir / f".part-{n:04d}.parquet.tmp-{os.getpid()}"
        try:
            table = _pa_table(rows)
            pq.write_table(table, tmp)
            os.replace(tmp, final)
        finally:
            if tmp.exists():                # write or replace failed — never leave live junk
                try:
                    tmp.unlink()
                except OSError:
                    pass
        with self._lock:
            self._parts_written += 1
        return len(rows)

    # ── read-side helpers ────────────────────────────────────────────────────

    def pending_rows(self, symbol: str, date: str) -> list[dict]:
        """Not-yet-flushed buffer rows for symbol+date, so bars are current between flushes."""
        with self._lock:
            return [dict(r) for r in self._buf if r["symbol"] == symbol and r["ts"][:10] == date]

    # ── lifecycle / introspection ────────────────────────────────────────────

    def stop(self) -> None:
        """Idempotent: stop the flusher and drain whatever is buffered (shutdown path)."""
        self._stopped = True
        self._stop_ev.set()
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=10)
        self._thread = None
        try:
            self.flush()                    # covers flush_s=None stores and raced appends
        except Exception:  # noqa: BLE001
            pass

    def stats(self) -> dict:
        with self._lock:
            return {
                "buffer_rows": len(self._buf), "buffer_cap": self._buf.maxlen,
                "appended_total": self._appended, "dropped": self._dropped,
                "append_strikes": self._strikes,
                "rows_flushed_today": self._rows_today, "flush_day": self._flush_day,
                "rows_flushed_total": self._flushed_total, "parts_written": self._parts_written,
                "last_flush_at": self._last_flush_at, "last_flush_rows": self._last_flush_rows,
                "flush_errors": self._flush_errors, "rows_lost_on_flush_error": self._rows_lost,
                "last_error": self._last_error,
                "flusher_alive": bool(self._thread is not None and self._thread.is_alive()),
                "flush_interval_s": self._flush_s, "dir": str(self._base),
            }


def _pa_table(rows: list[dict]) -> Any:
    import pyarrow as pa
    return pa.Table.from_pylist(rows, schema=_pa_schema())


# ── module singleton (same register pattern as live_ticks: one per process) ──

_instance: Optional[TickStore] = None
_instance_lock = threading.Lock()


def get_store() -> TickStore:
    """Create-on-first-use singleton — the live_ticks hook calls this only when a tick flows."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = TickStore()
        return _instance


def instance() -> Optional[TickStore]:
    return _instance


def shutdown_store() -> None:
    """Lifespan shutdown: final flush; no-op when persistence never started."""
    global _instance
    inst = _instance
    if inst is not None:
        inst.stop()
    _instance = None


# ── day readers (module-level: they serve old parquet even if no store is live) ──

def _day_frame(symbol: str, date: str, base_dir: Optional[Path] = None) -> tuple[Any, list[str]]:
    """One symbol's ticks for one day, oldest-first: parquet parts (numeric order) + the live
    buffer. Unreadable parts are skipped with a note (crash-safety: a bad part never hides the
    good ones). Returns (DataFrame with parsed `_dt`, notes)."""
    import pandas as pd
    import pyarrow.parquet as pq
    base = Path(base_dir) if base_dir is not None else default_base_dir()
    day_dir = base / date
    notes: list[str] = []
    frames: list[Any] = []
    parts = sorted(day_dir.glob("part-*.parquet"),
                   key=lambda p: (_part_sort_key(p), p.name)) if day_dir.is_dir() else []
    skipped = 0
    for p in parts:
        try:
            frames.append(pq.read_table(p).to_pandas())
        except Exception:  # noqa: BLE001 — a corrupt/partial part is skipped, never fatal
            skipped += 1
    if skipped:
        notes.append(f"skipped {skipped} unreadable part file(s)")
    inst = _instance
    if inst is not None:
        pending = inst.pending_rows(symbol, date)
        if pending:
            frames.append(pd.DataFrame(pending, columns=COLS))
    if not frames:
        return pd.DataFrame(columns=COLS), notes
    df = pd.concat(frames, ignore_index=True)
    df = df[df["symbol"] == symbol]
    if df.empty:
        return pd.DataFrame(columns=COLS), notes
    for c in NUMERIC_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[df["price"].notna()]
    df = df.assign(_dt=pd.to_datetime(df["ts"], format="ISO8601"))
    # stable sort: ts has seconds precision, so arrival order breaks ties (parts then buffer)
    df = df.sort_values("_dt", kind="stable").reset_index(drop=True)
    return df, notes


def _part_sort_key(p: Path) -> int:
    try:
        return int(p.stem.split("-", 1)[1])
    except (ValueError, IndexError):
        return 1 << 30


def _tick_volumes(df: Any) -> tuple[Any, str]:
    """Per-tick traded volume for ONE symbol's day (df oldest-first, unique RangeIndex).

    Modes:
      cumulative-ttq — ttq has ≥2 observations and ≥99 % of its steps are non-decreasing
                       (Breeze ttq = cumulative day volume): v = diff(ttq) clipped at 0;
                       the first observation contributes 0 (pre-subscribe volume unattributable).
      per-tick-qty   — otherwise, when a qty column exists: v = qty per tick.
      none           — no usable volume: v = 0 everywhere (VWAP becomes null).
    """
    import pandas as pd
    ttq = df["ttq"]
    t = ttq.dropna()
    if len(t) >= 2:
        d = t.diff()
        steps = d.dropna()
        if len(steps) and float((steps >= 0).mean()) >= _MONOTONE_FRACTION:
            out = pd.Series(0.0, index=df.index)
            out.loc[d.index] = d.fillna(0.0).clip(lower=0.0)
            return out, "cumulative-ttq"
    qty = df["qty"]
    if qty.notna().any():
        return qty.fillna(0.0), "per-tick-qty"
    return pd.Series(0.0, index=df.index), "none"


def _vwap(df: Any, v: Any) -> tuple[Optional[float], int]:
    total = float(v.sum())
    if total <= 0:
        return None, 0
    return round(float((df["price"] * v).sum() / total), 4), int(round(total))


# ── FastAPI router (PM mounts via app.include_router) ────────────────────────

router = APIRouter(tags=["ticks"])


@router.get("/ticks/bars")
def ticks_bars(symbol: str = Query(..., min_length=1, max_length=24),
               date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
               interval: str = Query("1m", pattern=r"^(1m|5m|15m)$")) -> dict:
    """OHLCV bars + session VWAP resampled from the day's tick parquet (plus the live buffer).
    Contract frozen for W1's chart studio — key names must not change. Missing day/symbol →
    200 with empty bars + note. Sync def: pandas runs in the threadpool, off the event loop."""
    sym = _normalize_symbol(symbol)
    day = date or _ist_today()
    df, notes = _day_frame(sym, day)
    if df.empty:
        notes.append(f"no tick data for {sym} on {day}")
        return {"symbol": sym, "date": day, "interval": interval, "bars": [],
                "vwap": None, "source": SOURCE, "note": "; ".join(notes)}
    v, mode = _tick_volumes(df)
    bins = df["_dt"].dt.floor(_FREQ[interval])
    import pandas as pd
    agg = (pd.DataFrame({"bin": bins, "price": df["price"], "v": v})
           .groupby("bin", sort=True)
           .agg(o=("price", "first"), h=("price", "max"), l=("price", "min"),
                c=("price", "last"), v=("v", "sum")))
    bars = [{"t": row.Index.strftime("%H:%M"), "o": round(float(row.o), 2),
             "h": round(float(row.h), 2), "l": round(float(row.l), 2),
             "c": round(float(row.c), 2), "v": int(round(float(row.v)))}
            for row in agg.itertuples()]
    vwap, _vol = _vwap(df, v)
    if vwap is None and mode == "none":
        notes.append("no per-tick volume observed (no ttq/qty) — vwap unavailable")
    out = {"symbol": sym, "date": day, "interval": interval, "bars": bars,
           "vwap": vwap, "source": SOURCE}
    if notes:
        out["note"] = "; ".join(notes)
    return out


@router.get("/ticks/vwap")
def ticks_vwap(symbol: str = Query(..., min_length=1, max_length=24),
               date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")) -> dict:
    """Running session VWAP + total observed volume (since first tick seen, stated honestly)."""
    sym = _normalize_symbol(symbol)
    day = date or _ist_today()
    df, notes = _day_frame(sym, day)
    if df.empty:
        notes.append(f"no tick data for {sym} on {day}")
        return {"symbol": sym, "date": day, "vwap": None, "volume": 0, "ticks": 0,
                "volume_mode": "none", "source": SOURCE, "note": "; ".join(notes)}
    v, mode = _tick_volumes(df)
    vwap, vol = _vwap(df, v)
    out = {"symbol": sym, "date": day, "vwap": vwap, "volume": vol, "ticks": int(len(df)),
           "last_price": round(float(df["price"].iloc[-1]), 2), "volume_mode": mode,
           "as_of": str(df["ts"].iloc[-1]), "source": SOURCE}
    if notes:
        out["note"] = "; ".join(notes)
    return out


@router.get("/ticks/store-status")
def ticks_store_status() -> dict:
    """Persistence health: buffer size, rows flushed today, last flush, drops, strikes."""
    inst = _instance
    out: dict[str, Any] = {"persist_enabled": persist_enabled(),
                           "started": inst is not None,
                           "as_of": _ist_now_iso()}
    out.update(inst.stats() if inst is not None else {"dir": str(default_base_dir())})
    return out

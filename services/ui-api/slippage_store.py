"""
slippage_store.py — C6 (§4.8) realised implementation-shortfall persistence.

Persists, per scheduled execution, the realised implementation shortfall the backtest
charged via the live execution scheduler:

    arrival price · realised VWAP · participation (Q/ADV) · n_slices · n_sessions ·
    fill_ratio · implementation-shortfall bps · the per-name temporary-impact coef Y_i

This is the measured-fill record that the nightly recalibration hook (`recalibrate_yi`)
regresses to ground each name's Y_i in realised fills over time, rather than a static
Amihud transform.

Hard requirements (audit §4.8):
  • `CREATE TABLE IF NOT EXISTS slippage (...)` — idempotent schema.
  • Write DEFENSIVELY: a write failure (DuckDB single-writer lock held by data-service,
    missing file, read-only mount) MUST NEVER crash a backtest. Every DB op is wrapped;
    failures are swallowed and surfaced only via the returned status, never raised.

Topology note: `services/ui-api/db.py` opens a *read-only* shared connection (the
analytics path reads off a snapshot while data-service holds the write lock). Slippage
persistence therefore opens its OWN short-lived WRITE connection to the live store, and
yields gracefully if the lock is unavailable — the backtest is unaffected either way.
"""
from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import duckdb

# Resolve the live store the same way db.py does (DATABASE_URL / DUCKDB_PATH env, else
# the repo-relative default). We open a *separate* write connection on demand.
_DB_PATH = (
    os.environ.get("DATABASE_URL")
    or os.environ.get("DUCKDB_PATH")
    or str(Path(__file__).resolve().parent.parent.parent / "data" / "market.duckdb")
)

SLIPPAGE_DDL = """
CREATE TABLE IF NOT EXISTS slippage (
    run_id              VARCHAR,
    ts                  TIMESTAMP,
    ticker              VARCHAR,
    entry_date          VARCHAR,
    side                VARCHAR,
    arrival_price       DOUBLE,
    realised_vwap       DOUBLE,
    alloc               DOUBLE,
    adv                 DOUBLE,
    participation       DOUBLE,
    n_slices            INTEGER,
    n_sessions          INTEGER,
    fill_ratio          DOUBLE,
    is_bps              DOUBLE,
    y_i                 DOUBLE,
    unfilled_notional   DOUBLE,
    atr_pct             DOUBLE
);
"""

# Column order MUST match SLIPPAGE_DDL for the positional INSERT below.
_COLUMNS = [
    "run_id", "ts", "ticker", "entry_date", "side", "arrival_price", "realised_vwap",
    "alloc", "adv", "participation", "n_slices", "n_sessions", "fill_ratio", "is_bps",
    "y_i", "unfilled_notional", "atr_pct",
]

_write_lock = threading.Lock()


def _open_write_conn(db_path: str, retries: int = 3, base_sleep: float = 0.2):
    """Open a short-lived WRITE connection, or None if the lock is unavailable.

    DuckDB is single-writer; data-service usually holds the lock. We retry briefly,
    then give up gracefully (return None) — the caller treats None as "skip persistence,
    do not crash the backtest".
    """
    import time
    for attempt in range(retries):
        try:
            return duckdb.connect(db_path, read_only=False)
        except Exception:
            if attempt < retries - 1:
                time.sleep(min(base_sleep * (2 ** attempt), 2.0))
    return None


class SlippageCollector:
    """Accumulates per-execution slippage rows during a backtest, then flushes once.

    Use as a `slippage_sink` for `simulate_portfolio`: pass `collector.add` and call
    `collector.flush()` after the run. `add` is allocation-light and NEVER touches the
    DB (so it cannot slow or crash the hot sim loop); all I/O happens in `flush`, fully
    guarded. A failed flush returns a status dict with `written=0` and the reason — the
    backtest result is already computed and is returned regardless.
    """

    def __init__(self, run_id: str, side: str = "BUY", db_path: Optional[str] = None) -> None:
        self.run_id = str(run_id)
        self.side = side.upper()
        self.db_path = db_path or _DB_PATH
        self._rows: list[dict] = []

    def add(self, row: dict) -> None:
        """Buffer one realised-execution row (called from the sim's slippage_sink)."""
        try:
            self._rows.append(dict(row))
        except Exception:
            pass   # buffering must never raise into the sim loop

    @property
    def n_buffered(self) -> int:
        return len(self._rows)

    def _row_tuple(self, r: dict, ts: datetime) -> tuple:
        def _f(key, default=0.0):
            v = r.get(key, default)
            try:
                return float(v)
            except (TypeError, ValueError):
                return default

        def _i(key, default=0):
            try:
                return int(r.get(key, default) or default)
            except (TypeError, ValueError):
                return default

        ed = r.get("entry_date")
        return (
            self.run_id, ts, str(r.get("ticker", "")), (str(ed) if ed is not None else None),
            self.side, _f("arrival_price"), _f("realised_vwap"), _f("alloc"), _f("adv"),
            _f("participation"), _i("n_slices"), _i("n_sessions"), _f("fill_ratio", 1.0),
            _f("is_bps"), _f("y_i", 1.0), _f("unfilled_notional"), _f("atr_pct"),
        )

    def flush(self) -> dict:
        """Write all buffered rows to the `slippage` table. Never raises.

        Returns {"written": int, "ok": bool, "reason": str|None}. On any failure the
        backtest is untouched; the rows are simply not persisted this run.
        """
        if not self._rows:
            return {"written": 0, "ok": True, "reason": "no rows"}
        ts = datetime.now(timezone.utc).replace(tzinfo=None)
        with _write_lock:
            conn = _open_write_conn(self.db_path)
            if conn is None:
                return {"written": 0, "ok": False, "reason": "write lock unavailable"}
            try:
                conn.execute(SLIPPAGE_DDL)
                placeholders = ", ".join(["?"] * len(_COLUMNS))
                tuples = [self._row_tuple(r, ts) for r in self._rows]
                conn.executemany(
                    f"INSERT INTO slippage ({', '.join(_COLUMNS)}) VALUES ({placeholders})",
                    tuples,
                )
                return {"written": len(tuples), "ok": True, "reason": None}
            except Exception as exc:   # pragma: no cover - lock/IO dependent
                return {"written": 0, "ok": False, "reason": str(exc)}
            finally:
                try:
                    conn.close()
                except Exception:
                    pass


def ensure_slippage_table(db_path: Optional[str] = None) -> bool:
    """Idempotently create the `slippage` table. Returns True on success, never raises."""
    with _write_lock:
        conn = _open_write_conn(db_path or _DB_PATH)
        if conn is None:
            return False
        try:
            conn.execute(SLIPPAGE_DDL)
            return True
        except Exception:
            return False
        finally:
            try:
                conn.close()
            except Exception:
                pass

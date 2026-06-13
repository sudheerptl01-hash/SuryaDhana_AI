"""
trial_ledger.py — C4 (§3.6): persistent cross-campaign research-trial ledger.

The Deflated Sharpe Ratio haircut is only as honest as its trial count N. Today N is
the number of surviving combos *within a single grid run* (~43). But the true search
intensity is far larger: every parameter sweep, every profile re-run, and the WFO's
per-window combo selection (`analytics._pick_best` choosing among ≤63 combos PER WINDOW)
are all uncounted trials. Deflating against a denominator far smaller than the real
search breadth lets DSR over-state robustness — at scale you run the search hundreds of
times and will eventually deploy a lucky combo DSR wrongly certified.

This module persists EVERY distinct configuration ever evaluated, across sessions, to a
DuckDB `research_trials` table, and exposes a reader so the DSR path can deflate against
the campaign-wide count (cluster-adjusted by `effective_trials.effective_n`) instead of
one run's survivors.

    research_trials(
        trial_id, run_id, ts, source, config_hash,
        sharpe, n_obs, skew, kurtosis, daily_returns_ref
    )

  source ∈ {grid_combo, param_sweep, wfo_window_select, manual_backtest}
  config_hash  — deterministic hash of the configuration; dedupes identical re-runs so
                 re-running the same grid 10× does NOT inflate N 10× (a genuine repeat is
                 not a new independent test).

Defensive-write contract (identical to `slippage_store.py`, audit §4.8): a write failure
(DuckDB single-writer lock held by data-service, missing file, read-only mount) MUST NEVER
crash a backtest or grid search. Every DB op is wrapped; failures are swallowed and
surfaced only via the returned status, never raised. db.py's shared connection is
READ-ONLY, so persistence opens its OWN short-lived WRITE connection on demand and yields
gracefully (status `ok=False`) if the lock is unavailable. The reader opens a short-lived
READ-ONLY connection and returns a neutral count on any failure so DSR falls back to the
per-run nominal denominator.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import duckdb

_DB_PATH = (
    os.environ.get("DATABASE_URL")
    or os.environ.get("DUCKDB_PATH")
    or str(Path(__file__).resolve().parent.parent.parent / "data" / "market.duckdb")
)

VALID_SOURCES = {"grid_combo", "param_sweep", "wfo_window_select", "manual_backtest"}

RESEARCH_TRIALS_DDL = """
CREATE TABLE IF NOT EXISTS research_trials (
    trial_id            VARCHAR,
    run_id              VARCHAR,
    ts                  TIMESTAMP,
    source              VARCHAR,
    config_hash         VARCHAR,
    sharpe              DOUBLE,
    n_obs               INTEGER,
    skew                DOUBLE,
    kurtosis            DOUBLE,
    daily_returns_ref   VARCHAR
);
"""

# Column order MUST match RESEARCH_TRIALS_DDL for the positional INSERT below.
_COLUMNS = [
    "trial_id", "run_id", "ts", "source", "config_hash",
    "sharpe", "n_obs", "skew", "kurtosis", "daily_returns_ref",
]

_write_lock = threading.Lock()


def config_hash(config) -> str:
    """Deterministic short hash of a configuration, for dedupe across re-runs.

    Accepts any JSON-serialisable structure (a list of filter dicts, a param dict, a
    string). Keys are sorted so dict ordering does not change the hash; non-serialisable
    values fall back to their ``repr``. Two byte-identical configurations always hash to
    the same value, so the same combo evaluated in two sessions counts ONCE.
    """
    try:
        payload = json.dumps(config, sort_keys=True, default=repr, separators=(",", ":"))
    except (TypeError, ValueError):
        payload = repr(config)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _open_conn(db_path: str, read_only: bool, retries: int = 3, base_sleep: float = 0.2):
    """Open a short-lived connection, or None if the lock is unavailable.

    DuckDB is single-writer; data-service usually holds the write lock. We retry briefly
    on write, then give up gracefully (return None) — the caller treats None as
    "skip / fall back, do not crash".
    """
    import time
    for attempt in range(retries):
        try:
            return duckdb.connect(db_path, read_only=read_only)
        except Exception:
            if attempt < retries - 1:
                time.sleep(min(base_sleep * (2 ** attempt), 2.0))
    return None


def _coerce_row(run_id: str, source: str, r: dict, ts: datetime) -> tuple:
    def _f(key, default=0.0):
        try:
            v = r.get(key, default)
            v = float(v)
            return v if v == v else default     # NaN -> default
        except (TypeError, ValueError):
            return default

    def _i(key, default=0):
        try:
            return int(r.get(key, default) or default)
        except (TypeError, ValueError):
            return default

    cfg = r.get("config", r.get("combo"))
    chash = r.get("config_hash") or config_hash(cfg)
    src = source if source in VALID_SOURCES else "manual_backtest"
    ref = r.get("daily_returns_ref")
    return (
        str(r.get("trial_id") or uuid.uuid4().hex[:16]),
        str(run_id), ts, src, str(chash),
        _f("sharpe"), _i("n_obs"), _f("skew"), _f("kurtosis", 3.0),
        (str(ref) if ref is not None else None),
    )


class TrialLedger:
    """Accumulates research-trial rows during a campaign, then flushes once.

    Buffering (`record`) is allocation-light and NEVER touches the DB, so it cannot slow
    or crash the hot grid/WFO loop; all I/O happens in `flush`, fully guarded. A failed
    flush returns a status dict with `written=0` and the reason — the campaign result is
    already computed and is returned regardless.
    """

    def __init__(self, run_id: Optional[str] = None, source: str = "grid_combo",
                 db_path: Optional[str] = None) -> None:
        self.run_id = str(run_id or uuid.uuid4().hex[:16])
        self.source = source if source in VALID_SOURCES else "manual_backtest"
        self.db_path = db_path or _DB_PATH
        self._rows: list[dict] = []

    def record(self, sharpe: float, config=None, n_obs: int = 0, skew: float = 0.0,
               kurtosis: float = 3.0, daily_returns_ref: Optional[str] = None,
               source: Optional[str] = None, config_hash: Optional[str] = None) -> None:
        """Buffer one evaluated trial. Never raises into the caller's loop."""
        try:
            self._rows.append({
                "sharpe": sharpe, "config": config, "n_obs": n_obs, "skew": skew,
                "kurtosis": kurtosis, "daily_returns_ref": daily_returns_ref,
                "source": source or self.source, "config_hash": config_hash,
            })
        except Exception:
            pass

    @property
    def n_buffered(self) -> int:
        return len(self._rows)

    def flush(self, dedupe: bool = True) -> dict:
        """Write buffered rows to `research_trials`. Never raises.

        With `dedupe=True` (default), only configs whose `config_hash` is NOT already in
        the table are inserted — so re-running the identical campaign does not inflate N.
        Returns {"written": int, "ok": bool, "reason": str|None, "skipped": int}.
        """
        if not self._rows:
            return {"written": 0, "ok": True, "reason": "no rows", "skipped": 0}
        ts = datetime.now(timezone.utc).replace(tzinfo=None)
        with _write_lock:
            conn = _open_conn(self.db_path, read_only=False)
            if conn is None:
                return {"written": 0, "ok": False, "reason": "write lock unavailable",
                        "skipped": 0}
            try:
                conn.execute(RESEARCH_TRIALS_DDL)
                tuples = [_coerce_row(self.run_id, r.get("source", self.source), r, ts)
                          for r in self._rows]
                skipped = 0
                if dedupe:
                    try:
                        existing = {row[0] for row in conn.execute(
                            "SELECT DISTINCT config_hash FROM research_trials").fetchall()}
                    except Exception:
                        existing = set()
                    seen: set[str] = set()
                    kept = []
                    for t in tuples:
                        chash = t[4]
                        if chash in existing or chash in seen:
                            skipped += 1
                            continue
                        seen.add(chash)
                        kept.append(t)
                    tuples = kept
                if not tuples:
                    return {"written": 0, "ok": True, "reason": "all deduped",
                            "skipped": skipped}
                placeholders = ", ".join(["?"] * len(_COLUMNS))
                conn.executemany(
                    f"INSERT INTO research_trials ({', '.join(_COLUMNS)}) "
                    f"VALUES ({placeholders})", tuples)
                return {"written": len(tuples), "ok": True, "reason": None,
                        "skipped": skipped}
            except Exception as exc:   # pragma: no cover - lock/IO dependent
                return {"written": 0, "ok": False, "reason": str(exc), "skipped": 0}
            finally:
                try:
                    conn.close()
                except Exception:
                    pass


def ensure_research_trials_table(db_path: Optional[str] = None) -> bool:
    """Idempotently create the `research_trials` table. Returns True, never raises."""
    with _write_lock:
        conn = _open_conn(db_path or _DB_PATH, read_only=False)
        if conn is None:
            return False
        try:
            conn.execute(RESEARCH_TRIALS_DDL)
            return True
        except Exception:
            return False
        finally:
            try:
                conn.close()
            except Exception:
                pass


def count_trials(since: Optional[str] = None, source: Optional[str] = None,
                 distinct: bool = True, db_path: Optional[str] = None) -> int:
    """Cross-campaign trial count from the ledger. Never raises.

    `since` — ISO date/timestamp lower bound on `ts` (inclusive).
    `source` — restrict to one source bucket (e.g. only `grid_combo`).
    `distinct` — count DISTINCT config_hash (the honest independent-config count) vs raw
                 row count. Default True: identical re-runs collapse to one trial.

    Returns 0 on a missing table or any read failure, so the DSR caller falls back to its
    per-run nominal trial count (never deflates against a bogus number).
    """
    conn = _open_conn(db_path or _DB_PATH, read_only=True)
    if conn is None:
        return 0
    try:
        col = "DISTINCT config_hash" if distinct else "*"
        sql = f"SELECT COUNT({col}) FROM research_trials"
        clauses, params = [], []
        if since:
            clauses.append("ts >= ?")
            params.append(str(since))
        if source:
            clauses.append("source = ?")
            params.append(str(source))
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        row = conn.execute(sql, params).fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


def read_trial_sharpes(since: Optional[str] = None, source: Optional[str] = None,
                       distinct: bool = True, limit: Optional[int] = None,
                       db_path: Optional[str] = None) -> list[float]:
    """Return the per-config Sharpes recorded in the ledger (one row per distinct config
    when `distinct`). Feeds the trial-Sharpe DISPERSION used by `expected_max_sharpe`.
    Returns [] on any failure."""
    conn = _open_conn(db_path or _DB_PATH, read_only=True)
    if conn is None:
        return []
    try:
        if distinct:
            base = ("SELECT config_hash, ANY_VALUE(sharpe) AS sharpe FROM research_trials")
            group = " GROUP BY config_hash"
        else:
            base = "SELECT sharpe FROM research_trials"
            group = ""
        clauses, params = [], []
        if since:
            clauses.append("ts >= ?")
            params.append(str(since))
        if source:
            clauses.append("source = ?")
            params.append(str(source))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = base + where + group
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = conn.execute(sql, params).fetchall()
        if distinct:
            return [float(r[1]) for r in rows if r[1] is not None]
        return [float(r[0]) for r in rows if r[0] is not None]
    except Exception:
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass

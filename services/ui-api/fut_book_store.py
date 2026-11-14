"""The PAPER MCX futures book's store (FINAL ROUND R5-FUTBOOK): SQLite ``data/paper_fut.sqlite`` owned by ui-api.

The single-leg futures sibling of ``fo_book_store.py`` (the paper F&O book), with the same discipline:

PAPER ONLY, by construction:
  * every position row carries ``mode`` with a ``CHECK (mode = 'paper')`` constraint — the database itself refuses any
    other value, whatever a caller sends;
  * this module imports no broker client and knows no order method; it stores what the paper route
    (``routers/fut_book.py``) hands it and nothing else;
  * nothing here is read by the Decision Desk, the S1 shadow, a directional alert or the MCXG ticket's price — the
    ticket keeps pricing from the desk's quote path and "records nothing"; booking is a separate, explicit action.

Point-in-time:
  * positions are never rewritten in place except to close / settle them (status, exit price, exit source, exit costs,
    closed_at); the entry price, its source, its cost and its time stay as booked;
  * marks are append-only: ``paper_fut_marks`` keeps one row per (position, as_of) and a REVISED value for the same
    as_of is a new row with its own ``first_seen_at``, never an overwrite;
  * every action (book / close / settle) is a journal row with its payload, and a close/settle row records its realised
    money (gross, costs, net) AT the close — the book reads those facts back, never recomputes them against moved marks.

Tables: ``paper_fut_positions`` (one row per futures leg), ``paper_fut_marks``, ``paper_fut_journal``.

Path: ``PAPER_FUT_DB`` (resolved per call, so tests point it at a temp file), else ``<repo>/data/paper_fut.sqlite``.
WAL, busy_timeout 5 s, created on the first WRITE: a read of a book that does not exist yet answers empty and creates
no file. Sync API (each call opens and closes its connection); the routes call it from worker threads
(``asyncio.to_thread``) so the event loop never waits on the disk.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
ENV_DB = "PAPER_FUT_DB"
BUSY_TIMEOUT_MS = 5000
SCHEMA_VERSION = 1
_WRITE_LOCK = threading.Lock()

DDL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS paper_fut_positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  family TEXT NOT NULL,
  expiry TEXT NOT NULL,
  side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
  lots INTEGER NOT NULL CHECK (lots > 0),
  multiplier REAL NOT NULL CHECK (multiplier > 0),
  unit TEXT,
  entry_price REAL NOT NULL CHECK (entry_price > 0),
  entry_price_source TEXT NOT NULL,
  entry_costs REAL NOT NULL DEFAULT 0,
  brokerage_per_order REAL NOT NULL DEFAULT 20,
  note TEXT,
  opened_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
  exit_price REAL CHECK (exit_price IS NULL OR exit_price >= 0),
  exit_price_source TEXT,
  exit_costs REAL,
  exit_kind TEXT CHECK (exit_kind IS NULL OR exit_kind IN ('close', 'settle')),
  closed_at TEXT,
  mode TEXT NOT NULL DEFAULT 'paper' CHECK (mode = 'paper')
);
CREATE INDEX IF NOT EXISTS ix_pfut_pos_status ON paper_fut_positions(status);

CREATE TABLE IF NOT EXISTS paper_fut_marks (
  position_id INTEGER NOT NULL REFERENCES paper_fut_positions(id),
  as_of TEXT NOT NULL,
  price REAL NOT NULL,
  price_source TEXT NOT NULL,
  session TEXT,
  quality TEXT,
  first_seen_at TEXT NOT NULL,
  PRIMARY KEY (position_id, as_of, first_seen_at)
);

CREATE TABLE IF NOT EXISTS paper_fut_journal (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  action TEXT NOT NULL,
  position_id INTEGER,
  payload TEXT NOT NULL
);
"""

POSITION_COLS = ("id", "family", "expiry", "side", "lots", "multiplier", "unit", "entry_price", "entry_price_source",
                 "entry_costs", "brokerage_per_order", "note", "opened_at", "status", "exit_price",
                 "exit_price_source", "exit_costs", "exit_kind", "closed_at", "mode")
MARK_COLS = ("position_id", "as_of", "price", "price_source", "session", "quality", "first_seen_at")


def now_ist() -> str:
    return datetime.now(IST).isoformat(timespec="seconds")


def default_db_path() -> Path:
    env = os.environ.get(ENV_DB, "").strip()
    if env:
        return Path(env).expanduser()
    for root in (Path(__file__).resolve().parents[2] / "data", Path("/app/data")):
        if root.is_dir():
            return root / "paper_fut.sqlite"
    return Path("paper_fut.sqlite")


class BookError(ValueError):
    """A request the book refuses (unknown position, already closed, bad fill); the router maps it to 4xx."""


def realised_from_row(row: sqlite3.Row | dict[str, Any] | None) -> tuple[float, float, float] | None:
    """(gross_inr, costs_inr, realised_inr) from a closed position's stored fill columns (written once at close,
    never rewritten), else None. realised_inr is net of the recorded entry + exit costs. Arithmetic only."""
    if row is None or row["exit_price"] is None:
        return None
    q = (1 if row["side"] == "buy" else -1) * int(row["lots"]) * float(row["multiplier"])
    gross = q * (float(row["exit_price"]) - float(row["entry_price"]))
    costs = float(row["entry_costs"] or 0.0) + float(row["exit_costs"] or 0.0)
    return round(gross, 2), round(costs, 2), round(gross - costs, 2)


class FutBookStore:
    """One SQLite file. Each public call opens its own connection (sqlite3 objects never cross threads)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else default_db_path()

    # ── plumbing ────────────────────────────────────────────────────────────────────────────────────────────────
    def _absent(self) -> bool:
        """No book file yet: reads answer empty without creating one (only a write creates the file)."""
        return not self.path.exists()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None, check_same_thread=False)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript(DDL)
            conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with _WRITE_LOCK, self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    @staticmethod
    def _journal(conn: sqlite3.Connection, action: str, position_id: int | None, payload: dict[str, Any]) -> None:
        conn.execute("INSERT INTO paper_fut_journal(ts, action, position_id, payload) VALUES (?, ?, ?, ?)",
                     (now_ist(), action, position_id, json.dumps(payload, default=str, ensure_ascii=False)))

    # ── book ────────────────────────────────────────────────────────────────────────────────────────────────────
    def book(self, *, family: str, expiry: str, side: str, lots: int, multiplier: float, entry_price: float,
             entry_price_source: str, entry_costs: float = 0.0, brokerage_per_order: float = 20.0,
             unit: str | None = None, note: str | None = None, opened_at: str | None = None,
             context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Write one futures position. Mode is always 'paper' (the column default; the CHECK refuses anything else).
        ``context`` is the point-in-time snapshot the router took AT the booking (the ticket as shown); it is stored
        verbatim in the journal row and never recomputed."""
        ts = opened_at or now_ist()
        with self._tx() as conn:
            cur = conn.execute(
                """INSERT INTO paper_fut_positions(family, expiry, side, lots, multiplier, unit, entry_price,
                       entry_price_source, entry_costs, brokerage_per_order, note, opened_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (family.upper(), str(expiry)[:10], side, int(lots), float(multiplier), unit, float(entry_price),
                 str(entry_price_source or "unstated"), float(entry_costs or 0.0), float(brokerage_per_order), note, ts))
            pid = int(cur.lastrowid or 0)
            payload: dict[str, Any] = {"family": family.upper(), "expiry": str(expiry)[:10], "side": side,
                                       "lots": int(lots), "entry_price": float(entry_price),
                                       "entry_price_source": str(entry_price_source or "unstated"),
                                       "entry_costs": round(float(entry_costs or 0.0), 2)}
            if context is not None:
                payload["context"] = context
            self._journal(conn, "book", pid, payload)
        return self.position(pid)

    # ── close / settle ──────────────────────────────────────────────────────────────────────────────────────────
    def close(self, fills: list[dict[str, Any]], *, closed_at: str | None = None,
              action: str = "close") -> list[dict[str, Any]]:
        """``fills``: [{position_id, exit_price, exit_price_source, exit_costs}]. Refuses a position that is not open.
        ``action`` 'settle' marks an expired contract settled at the stored settlement of record. Each journal row
        records the fill's realised money point-in-time: ``gross_inr`` (signed qty × multiplier × (exit − entry)),
        ``costs_inr`` (the recorded entry + exit cost sides), ``realised_inr`` (net of those costs)."""
        if action not in ("close", "settle"):
            raise BookError(f"unknown close action {action!r}")
        ts = closed_at or now_ist()
        with self._tx() as conn:
            for f in fills:
                pid = int(f["position_id"])
                if not float(f["exit_price"]) >= 0:
                    raise BookError(f"position {pid}: an exit price must be ≥ 0 (got {f['exit_price']})")
                row = conn.execute("SELECT * FROM paper_fut_positions WHERE id = ?", (pid,)).fetchone()
                if row is None:
                    raise BookError(f"position {pid} does not exist")
                if row["status"] != "open":
                    raise BookError(f"position {pid} is already {row['status']}")
                exit_price, exit_costs = float(f["exit_price"]), float(f.get("exit_costs") or 0.0)
                src = str(f.get("exit_price_source") or "unstated")
                conn.execute("""UPDATE paper_fut_positions SET status = 'closed', exit_price = ?, exit_price_source = ?,
                                exit_costs = ?, exit_kind = ?, closed_at = ? WHERE id = ?""",
                             (exit_price, src, exit_costs, action, ts, pid))
                q = (1 if row["side"] == "buy" else -1) * int(row["lots"]) * float(row["multiplier"])
                gross = q * (exit_price - float(row["entry_price"]))
                costs = float(row["entry_costs"] or 0.0) + exit_costs
                self._journal(conn, action, pid, {
                    "family": row["family"], "expiry": row["expiry"], "side": row["side"], "lots": row["lots"],
                    "exit_price": exit_price, "exit_price_source": src, "exit_costs": round(exit_costs, 2),
                    "gross_inr": round(gross, 2), "costs_inr": round(costs, 2), "realised_inr": round(gross - costs, 2)})
        return [self.position(int(f["position_id"])) for f in fills]

    # ── reads ───────────────────────────────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _pos(row: sqlite3.Row) -> dict[str, Any]:
        return {k: row[k] for k in POSITION_COLS}

    def position(self, pid: int) -> dict[str, Any]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM paper_fut_positions WHERE id = ?", (pid,)).fetchone()
        if row is None:
            raise BookError(f"position {pid} does not exist")
        return self._pos(row)

    def positions(self, *, status: str | None = None) -> list[dict[str, Any]]:
        if self._absent():
            return []
        sql, args = "SELECT * FROM paper_fut_positions", list[Any]()
        if status:
            sql += " WHERE status = ?"
            args.append(status)
        with self._conn() as conn:
            rows = conn.execute(sql + " ORDER BY id", args).fetchall()
        return [self._pos(r) for r in rows]

    def journal(self, limit: int = 50) -> list[dict[str, Any]]:
        if self._absent():
            return []
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM paper_fut_journal ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
        return [{"id": r["id"], "ts": r["ts"], "action": r["action"], "position_id": r["position_id"],
                 "payload": json.loads(r["payload"])} for r in rows]

    # ── marks (append-only) ─────────────────────────────────────────────────────────────────────────────────────
    def add_marks(self, marks: list[dict[str, Any]]) -> int:
        """Append daily marks. A mark for a (position, as_of) already stored with the SAME price is skipped
        (idempotent); a different price for the same as_of is a REVISION row with its own ``first_seen_at``, never an
        overwrite. Returns the number of rows written."""
        written = 0
        with self._tx() as conn:
            for m in marks:
                pid, as_of = int(m["position_id"]), str(m["as_of"])[:10]
                same = conn.execute("""SELECT price FROM paper_fut_marks WHERE position_id = ? AND as_of = ?
                                       ORDER BY first_seen_at DESC LIMIT 1""", (pid, as_of)).fetchone()
                if same is not None and abs(float(same["price"]) - float(m["price"])) < 1e-9:
                    continue
                seen = datetime.now(IST).isoformat(timespec="microseconds")  # a revision in the same second is its own row
                cur = conn.execute(
                    f"INSERT OR IGNORE INTO paper_fut_marks({', '.join(MARK_COLS)}) VALUES ({', '.join('?' * len(MARK_COLS))})",
                    (pid, as_of, float(m["price"]), str(m.get("price_source") or "unstated"), m.get("session"),
                     m.get("quality"), m.get("first_seen_at") or seen))
                written += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        return written

    def marks(self, position_ids: list[int] | None = None, *, limit: int = 2000) -> list[dict[str, Any]]:
        if self._absent():
            return []
        sql, args = "SELECT * FROM paper_fut_marks WHERE 1 = 1", list[Any]()
        if position_ids:
            sql += f" AND position_id IN ({','.join('?' * len(position_ids))})"
            args.extend(int(i) for i in position_ids)
        with self._conn() as conn:
            rows = conn.execute(sql + " ORDER BY position_id, as_of, first_seen_at LIMIT ?", [*args, int(limit)]).fetchall()
        return [{k: r[k] for k in MARK_COLS} for r in rows]

    def latest_marks(self, position_ids: list[int], *, through: str | None = None) -> dict[int, dict[str, Any]]:
        """The newest mark per position (the latest revision of the latest session); with ``through`` (YYYY-MM-DD)
        only marks dated on or before it — an expired contract never reads a mark from after its expiry."""
        out: dict[int, dict[str, Any]] = {}
        for m in self.marks(position_ids, limit=100_000):
            if through is not None and str(m["as_of"])[:10] > through:
                continue
            out[int(m["position_id"])] = m          # ordered by as_of, first_seen_at: the last one wins
        return out

    def prev_mark(self, pid: int, before: str) -> dict[str, Any] | None:
        """The latest mark dated strictly before ``before`` (YYYY-MM-DD) — the day-MTM baseline."""
        if self._absent():
            return None
        with self._conn() as conn:
            r = conn.execute("""SELECT * FROM paper_fut_marks WHERE position_id = ? AND as_of < ?
                                ORDER BY as_of DESC, first_seen_at DESC LIMIT 1""", (int(pid), str(before)[:10])).fetchone()
        return {k: r[k] for k in MARK_COLS} if r else None


def get_store() -> FutBookStore:
    """The store for the current PAPER_FUT_DB (resolved per call so tests can repoint it)."""
    return FutBookStore(default_db_path())

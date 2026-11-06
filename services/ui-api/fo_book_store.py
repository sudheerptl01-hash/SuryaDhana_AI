"""The PAPER F&O book's store (Terminal v2 PLAN 2.2, W2-BOOK): SQLite ``data/paper_fo.sqlite`` owned by ui-api.

PAPER ONLY, by construction:
  * every position row carries ``mode`` with a ``CHECK (mode = 'paper')`` constraint — the database itself refuses any
    other value, whatever a caller sends;
  * this module imports no broker client and knows no order method; it stores what the paper routes
    (``routers/fo_book.py``) hand it and nothing else;
  * it is separate from the cash book (the Decision Desk ledger, ``decision_desk.db``) and from the legacy PORT engine
    (``PAPER_TRADES_DB``): nothing here is read by the Desk, the S1 shadow, a directional alert or a ticket price.

Point-in-time (PLAN §0.3):
  * positions are never rewritten in place except to close / roll them (status, exit price, exit source, closed_at);
    the entry price, its source and its time stay as booked;
  * marks are append-only: ``paper_fo_marks`` keeps one row per (position, kind, as_of) and a REVISED value for the same
    as_of (the 22:05 bhavcopy re-publication) is a new row with its own ``first_seen_at``, never an overwrite;
  * every action (book / close / roll / save / delete) is a journal row with its payload (``paper_fo_journal``).

Tables: ``paper_fo_structures`` (a named group of legs booked together), ``paper_fo_positions`` (one row per leg),
``paper_fo_marks``, ``paper_fo_journal``, ``fo_saved_structures`` (OSTR's "save / name a structure", not a booking).

Path: ``PAPER_FO_DB`` (resolved per call, so tests point it at a temp file), else ``<repo>/data/paper_fo.sqlite``.
WAL, busy_timeout 5 s, created on the first WRITE (a book, a save, a mark of an open position): a read of a book that
does not exist yet (RSK › F&O, OSTR's saved list on a fresh install) answers empty and creates no file. Sync API (each call opens and closes its connection); the routes call it from
worker threads (``asyncio.to_thread``) so the event loop never waits on the disk.
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
ENV_DB = "PAPER_FO_DB"
BUSY_TIMEOUT_MS = 5000
SCHEMA_VERSION = 1
_WRITE_LOCK = threading.Lock()

DDL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS paper_fo_structures (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  symbol TEXT NOT NULL,
  created_at TEXT NOT NULL,
  source TEXT NOT NULL,
  note TEXT,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
  closed_at TEXT,
  mode TEXT NOT NULL DEFAULT 'paper' CHECK (mode = 'paper')
);

CREATE TABLE IF NOT EXISTS paper_fo_positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  structure_id INTEGER NOT NULL REFERENCES paper_fo_structures(id),
  symbol TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('CE', 'PE', 'FUT')),
  side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
  strike REAL,
  expiry TEXT NOT NULL,
  lots INTEGER NOT NULL CHECK (lots > 0),
  lot_size INTEGER NOT NULL CHECK (lot_size > 0),
  entry_price REAL NOT NULL CHECK (entry_price >= 0),
  entry_iv REAL,
  entry_forward REAL,
  entry_price_source TEXT NOT NULL,
  entry_costs REAL NOT NULL DEFAULT 0,
  opened_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed', 'rolled')),
  exit_price REAL CHECK (exit_price IS NULL OR exit_price >= 0),
  exit_price_source TEXT,
  exit_costs REAL,
  closed_at TEXT,
  rolled_from INTEGER,
  rolled_to INTEGER,
  mode TEXT NOT NULL DEFAULT 'paper' CHECK (mode = 'paper')
);
CREATE INDEX IF NOT EXISTS ix_pfo_pos_structure ON paper_fo_positions(structure_id);
CREATE INDEX IF NOT EXISTS ix_pfo_pos_status ON paper_fo_positions(status);

CREATE TABLE IF NOT EXISTS paper_fo_marks (
  position_id INTEGER NOT NULL REFERENCES paper_fo_positions(id),
  kind TEXT NOT NULL CHECK (kind IN ('eod', 'session')),
  as_of TEXT NOT NULL,
  mark_date TEXT NOT NULL,
  price REAL NOT NULL,
  iv REAL,
  forward REAL,
  spot REAL,
  t_days REAL,
  price_source TEXT NOT NULL,
  mark_method TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  PRIMARY KEY (position_id, kind, as_of, first_seen_at)
);

CREATE TABLE IF NOT EXISTS paper_fo_journal (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  action TEXT NOT NULL,
  structure_id INTEGER,
  payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fo_saved_structures (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  symbol TEXT NOT NULL,
  legs TEXT NOT NULL,
  note TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (name, symbol)
);
"""

POSITION_COLS = ("id", "structure_id", "symbol", "kind", "side", "strike", "expiry", "lots", "lot_size", "entry_price",
                 "entry_iv", "entry_forward", "entry_price_source", "entry_costs", "opened_at", "status", "exit_price",
                 "exit_price_source", "exit_costs", "closed_at", "rolled_from", "rolled_to", "mode")
MARK_COLS = ("position_id", "kind", "as_of", "mark_date", "price", "iv", "forward", "spot", "t_days", "price_source",
             "mark_method", "first_seen_at")


def now_ist() -> str:
    return datetime.now(IST).isoformat(timespec="seconds")


def default_db_path() -> Path:
    env = os.environ.get(ENV_DB, "").strip()
    if env:
        return Path(env).expanduser()
    for root in (Path(__file__).resolve().parents[2] / "data", Path("/app/data")):
        if root.is_dir():
            return root / "paper_fo.sqlite"
    return Path("paper_fo.sqlite")


class BookError(ValueError):
    """A request the book refuses (unknown position, already closed, wrong state); the router maps it to 4xx."""


class FoBookStore:
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
    def _journal(conn: sqlite3.Connection, action: str, structure_id: int | None, payload: dict[str, Any]) -> None:
        conn.execute("INSERT INTO paper_fo_journal(ts, action, structure_id, payload) VALUES (?, ?, ?, ?)",
                     (now_ist(), action, structure_id, json.dumps(payload, default=str, ensure_ascii=False)))

    # ── book ────────────────────────────────────────────────────────────────────────────────────────────────────
    def book(self, *, name: str, symbol: str, legs: list[dict[str, Any]], source: str, note: str | None = None,
             opened_at: str | None = None) -> dict[str, Any]:
        """Write one structure and its legs. ``legs`` items carry kind, side, strike, expiry, lots, lot_size,
        entry_price, entry_iv, entry_forward, entry_price_source, entry_costs. Mode is always 'paper'."""
        if not legs:
            raise BookError("a structure needs at least one leg")
        ts = opened_at or now_ist()
        with self._tx() as conn:
            cur = conn.execute("INSERT INTO paper_fo_structures(name, symbol, created_at, source, note) VALUES (?, ?, ?, ?, ?)",
                               (name, symbol.upper(), ts, source, note))
            sid = int(cur.lastrowid or 0)
            ids = [self._insert_leg(conn, sid, symbol, leg, ts) for leg in legs]
            self._journal(conn, "book", sid, {"name": name, "symbol": symbol.upper(), "legs": legs, "position_ids": ids})
        return self.structure(sid)

    @staticmethod
    def _insert_leg(conn: sqlite3.Connection, sid: int, symbol: str, leg: dict[str, Any], ts: str,
                    rolled_from: int | None = None) -> int:
        cur = conn.execute(
            """INSERT INTO paper_fo_positions(structure_id, symbol, kind, side, strike, expiry, lots, lot_size, entry_price,
                   entry_iv, entry_forward, entry_price_source, entry_costs, opened_at, rolled_from)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (sid, symbol.upper(), leg["kind"], leg["side"], leg.get("strike"), str(leg["expiry"])[:10], int(leg["lots"]),
             int(leg["lot_size"]), float(leg["entry_price"]), leg.get("entry_iv"), leg.get("entry_forward"),
             str(leg.get("entry_price_source") or "unstated"), float(leg.get("entry_costs") or 0.0), ts, rolled_from))
        return int(cur.lastrowid or 0)

    # ── close / roll ────────────────────────────────────────────────────────────────────────────────────────────
    def close(self, fills: list[dict[str, Any]], *, closed_at: str | None = None, action: str = "close",
              status: str = "closed") -> list[dict[str, Any]]:
        """``fills``: [{position_id, exit_price, exit_price_source, exit_costs}]. Refuses a position that is not open."""
        ts = closed_at or now_ist()
        touched: set[int] = set()
        with self._tx() as conn:
            for f in fills:
                pid = int(f["position_id"])
                if not float(f["exit_price"]) >= 0:            # also refused by the column's CHECK (new files)
                    raise BookError(f"position {pid}: an exit price must be ≥ 0 (got {f['exit_price']})")
                row = conn.execute("SELECT structure_id, status FROM paper_fo_positions WHERE id = ?", (pid,)).fetchone()
                if row is None:
                    raise BookError(f"position {pid} does not exist")
                if row["status"] != "open":
                    raise BookError(f"position {pid} is already {row['status']}")
                conn.execute("""UPDATE paper_fo_positions SET status = ?, exit_price = ?, exit_price_source = ?, exit_costs = ?,
                                closed_at = ? WHERE id = ?""",
                             (status, float(f["exit_price"]), str(f.get("exit_price_source") or "unstated"),
                              float(f.get("exit_costs") or 0.0), ts, pid))
                touched.add(int(row["structure_id"]))
            for sid in touched:
                self._settle_structure(conn, sid, ts)
                self._journal(conn, action, sid, {"fills": [f for f in fills]})
        return [self.position(int(f["position_id"])) for f in fills]

    def roll(self, closes: list[dict[str, Any]], opens: list[dict[str, Any]], *, ts: str | None = None) -> dict[str, Any]:
        """Close ``closes`` (status 'rolled') and open ``opens`` in the SAME structure, linking rolled_from / rolled_to
        pairwise (opens[i] replaces closes[i]). One transaction: either the whole roll lands or none of it."""
        if len(closes) != len(opens) or not closes:
            raise BookError("a roll pairs each closed leg with one new leg")
        when = ts or now_ist()
        with self._tx() as conn:
            sids = set()
            new_ids: list[int] = []
            for c, o in zip(closes, opens, strict=True):
                pid = int(c["position_id"])
                if not (float(c["exit_price"]) >= 0 and float(o["entry_price"]) >= 0):
                    raise BookError(f"position {pid}: roll prices must be ≥ 0")
                row = conn.execute("SELECT * FROM paper_fo_positions WHERE id = ?", (pid,)).fetchone()
                if row is None:
                    raise BookError(f"position {pid} does not exist")
                if row["status"] != "open":
                    raise BookError(f"position {pid} is already {row['status']}")
                sid = int(row["structure_id"])
                sids.add(sid)
                new_id = self._insert_leg(conn, sid, row["symbol"], o, when, rolled_from=pid)
                conn.execute("""UPDATE paper_fo_positions SET status = 'rolled', exit_price = ?, exit_price_source = ?,
                                exit_costs = ?, closed_at = ?, rolled_to = ? WHERE id = ?""",
                             (float(c["exit_price"]), str(c.get("exit_price_source") or "unstated"),
                              float(c.get("exit_costs") or 0.0), when, new_id, pid))
                new_ids.append(new_id)
            for sid in sids:
                self._journal(conn, "roll", sid, {"closes": closes, "opens": opens, "new_position_ids": new_ids})
        return {"closed": [self.position(int(c["position_id"])) for c in closes], "opened": [self.position(i) for i in new_ids]}

    @staticmethod
    def _settle_structure(conn: sqlite3.Connection, sid: int, ts: str) -> None:
        left = conn.execute("SELECT COUNT(*) FROM paper_fo_positions WHERE structure_id = ? AND status = 'open'", (sid,)).fetchone()[0]
        if int(left) == 0:
            conn.execute("UPDATE paper_fo_structures SET status = 'closed', closed_at = ? WHERE id = ? AND status = 'open'", (ts, sid))

    # ── reads ───────────────────────────────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _pos(row: sqlite3.Row) -> dict[str, Any]:
        return {k: row[k] for k in POSITION_COLS}

    def position(self, pid: int) -> dict[str, Any]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM paper_fo_positions WHERE id = ?", (pid,)).fetchone()
        if row is None:
            raise BookError(f"position {pid} does not exist")
        return self._pos(row)

    def positions(self, *, status: str | None = "open", ids: list[int] | None = None,
                  structure_id: int | None = None) -> list[dict[str, Any]]:
        if self._absent():
            return []
        sql, args = "SELECT * FROM paper_fo_positions WHERE 1 = 1", list[Any]()
        if status:
            sql += " AND status = ?"
            args.append(status)
        if ids:
            sql += f" AND id IN ({','.join('?' * len(ids))})"
            args.extend(int(i) for i in ids)
        if structure_id is not None:
            sql += " AND structure_id = ?"
            args.append(int(structure_id))
        with self._conn() as conn:
            rows = conn.execute(sql + " ORDER BY structure_id, id", args).fetchall()
        return [self._pos(r) for r in rows]

    def structure(self, sid: int) -> dict[str, Any]:
        with self._conn() as conn:
            s = conn.execute("SELECT * FROM paper_fo_structures WHERE id = ?", (sid,)).fetchone()
            if s is None:
                raise BookError(f"structure {sid} does not exist")
            legs = conn.execute("SELECT * FROM paper_fo_positions WHERE structure_id = ? ORDER BY id", (sid,)).fetchall()
        return {**{k: s[k] for k in s.keys()}, "positions": [self._pos(r) for r in legs]}

    def structures(self, *, status: str | None = "open") -> list[dict[str, Any]]:
        if self._absent():
            return []
        with self._conn() as conn:
            if status:
                rows = conn.execute("SELECT id FROM paper_fo_structures WHERE status = ? ORDER BY id", (status,)).fetchall()
            else:
                rows = conn.execute("SELECT id FROM paper_fo_structures ORDER BY id").fetchall()
        return [self.structure(int(r["id"])) for r in rows]

    def journal(self, limit: int = 50) -> list[dict[str, Any]]:
        if self._absent():
            return []
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM paper_fo_journal ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
        return [{"id": r["id"], "ts": r["ts"], "action": r["action"], "structure_id": r["structure_id"],
                 "payload": json.loads(r["payload"])} for r in rows]

    # ── marks (append-only) ─────────────────────────────────────────────────────────────────────────────────────
    def add_marks(self, marks: list[dict[str, Any]], *, min_session_gap_s: float = 900.0) -> int:
        """Append marks. An EOD mark for a (position, as_of) already stored with the SAME price is skipped (idempotent);
        a different price is a revision row. A session mark is kept at most once per ``min_session_gap_s`` per position.
        Returns the number of rows written."""
        written = 0
        with self._tx() as conn:
            for m in marks:
                pid, kind, as_of = int(m["position_id"]), str(m["kind"]), str(m["as_of"])
                last = conn.execute("""SELECT as_of, price FROM paper_fo_marks WHERE position_id = ? AND kind = ?
                                       ORDER BY as_of DESC, first_seen_at DESC LIMIT 1""", (pid, kind)).fetchone()
                if kind == "eod":
                    same = conn.execute("""SELECT price FROM paper_fo_marks WHERE position_id = ? AND kind = 'eod' AND as_of = ?
                                           ORDER BY first_seen_at DESC LIMIT 1""", (pid, as_of)).fetchone()
                    if same is not None and abs(float(same["price"]) - float(m["price"])) < 1e-9:
                        continue
                elif last is not None:
                    try:
                        gap = (datetime.fromisoformat(as_of) - datetime.fromisoformat(str(last["as_of"]))).total_seconds()
                    except ValueError:
                        gap = min_session_gap_s
                    if gap < min_session_gap_s:
                        continue
                seen = datetime.now(IST).isoformat(timespec="microseconds")   # a revision in the same second is still its own row
                cur = conn.execute(f"INSERT OR IGNORE INTO paper_fo_marks({', '.join(MARK_COLS)}) VALUES ({', '.join('?' * len(MARK_COLS))})",
                             (pid, kind, as_of, str(m.get("mark_date") or as_of[:10]), float(m["price"]), m.get("iv"), m.get("forward"),
                              m.get("spot"), m.get("t_days"), str(m.get("price_source") or "unstated"),
                              str(m.get("mark_method") or "close"), m.get("first_seen_at") or seen))
                written += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        return written

    def marks(self, position_ids: list[int] | None = None, *, kind: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        if self._absent():
            return []
        sql, args = "SELECT * FROM paper_fo_marks WHERE 1 = 1", list[Any]()
        if position_ids:
            sql += f" AND position_id IN ({','.join('?' * len(position_ids))})"
            args.extend(int(i) for i in position_ids)
        if kind:
            sql += " AND kind = ?"
            args.append(kind)
        with self._conn() as conn:
            rows = conn.execute(sql + " ORDER BY position_id, as_of, first_seen_at LIMIT ?", [*args, int(limit)]).fetchall()
        return [{k: r[k] for k in MARK_COLS} for r in rows]

    def latest_eod_marks(self, position_ids: list[int], *, through: str | None = None) -> dict[int, dict[str, Any]]:
        """The newest EOD mark per position (the latest revision of the latest session); with ``through`` (YYYY-MM-DD)
        only marks dated on or before it (an expired contract never reads a mark from after its expiry)."""
        out: dict[int, dict[str, Any]] = {}
        for m in self.marks(position_ids, kind="eod", limit=100_000):
            if through is not None and str(m["mark_date"])[:10] > through:
                continue
            out[int(m["position_id"])] = m          # ordered by as_of, first_seen_at: the last one wins
        return out

    def eod_spot_on(self, symbol: str, day: str) -> dict[str, Any] | None:
        """The underlying price an end-of-day chain dated ``day`` carried (stored with any EOD mark of ``symbol`` dated that
        day; the latest revision wins) — on an expiry day, the final settlement price. None when nothing was stored."""
        if self._absent():
            return None
        with self._conn() as conn:
            r = conn.execute("""SELECT m.spot, m.price_source, m.as_of FROM paper_fo_marks m
                                JOIN paper_fo_positions p ON p.id = m.position_id
                                WHERE p.symbol = ? AND m.kind = 'eod' AND m.mark_date = ? AND m.spot IS NOT NULL AND m.spot > 0
                                ORDER BY m.first_seen_at DESC LIMIT 1""", (symbol.upper(), day[:10])).fetchone()
        return {"spot": float(r["spot"]), "price_source": str(r["price_source"]), "as_of": str(r["as_of"])} if r else None

    # ── saved structures (OSTR: save / name; not a booking) ─────────────────────────────────────────────────────
    def save_structure(self, *, name: str, symbol: str, legs: list[dict[str, Any]], note: str | None = None) -> dict[str, Any]:
        ts = now_ist()
        with self._tx() as conn:
            conn.execute("""INSERT INTO fo_saved_structures(name, symbol, legs, note, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)
                            ON CONFLICT(name, symbol) DO UPDATE SET legs = excluded.legs, note = excluded.note,
                            updated_at = excluded.updated_at""",
                         (name, symbol.upper(), json.dumps(legs, default=str), note, ts, ts))
            row = conn.execute("SELECT id FROM fo_saved_structures WHERE name = ? AND symbol = ?", (name, symbol.upper())).fetchone()
            self._journal(conn, "save", None, {"saved_id": int(row["id"]), "name": name, "symbol": symbol.upper(), "legs": legs})
        return self.saved(int(row["id"]))

    def saved(self, saved_id: int) -> dict[str, Any]:
        with self._conn() as conn:
            r = conn.execute("SELECT * FROM fo_saved_structures WHERE id = ?", (int(saved_id),)).fetchone()
        if r is None:
            raise BookError(f"saved structure {saved_id} does not exist")
        return {"id": r["id"], "name": r["name"], "symbol": r["symbol"], "legs": json.loads(r["legs"]), "note": r["note"],
                "created_at": r["created_at"], "updated_at": r["updated_at"]}

    def saved_list(self, symbol: str | None = None) -> list[dict[str, Any]]:
        if self._absent():
            return []
        with self._conn() as conn:
            if symbol:
                rows = conn.execute("SELECT id FROM fo_saved_structures WHERE symbol = ? ORDER BY updated_at DESC", (symbol.upper(),)).fetchall()
            else:
                rows = conn.execute("SELECT id FROM fo_saved_structures ORDER BY updated_at DESC").fetchall()
        return [self.saved(int(r["id"])) for r in rows]

    def delete_saved(self, saved_id: int) -> bool:
        with self._tx() as conn:
            cur = conn.execute("DELETE FROM fo_saved_structures WHERE id = ?", (int(saved_id),))
            if cur.rowcount:
                self._journal(conn, "delete_saved", None, {"saved_id": int(saved_id)})
            return bool(cur.rowcount)


def get_store() -> FoBookStore:
    """The store for the current PAPER_FO_DB (resolved per call so tests can repoint it)."""
    return FoBookStore(default_db_path())

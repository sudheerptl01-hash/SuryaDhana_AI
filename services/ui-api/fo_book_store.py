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
# Since this date every close/settle journal row records its realised money point-in-time (FINAL ROUND wave B, SPEC M3);
# earlier closes are derived from the stored fills (entry/exit price + costs columns, immutable after close) where the
# position rows still exist, else their realised shows null.
REALISED_RECORDED_FROM = "2026-11-14"

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


def ist_day(ts: Any) -> str | None:
    """The IST session date (YYYY-MM-DD) a timestamp belongs to; None when it does not parse. A naive timestamp is
    taken as IST (the store writes IST isoformat); an aware one in any zone converts — so a UTC stamp just after
    18:30 UTC counts to the NEXT IST date (the day-scoping rule of ``day_summary``)."""
    try:
        d = datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=IST)
    return d.astimezone(IST).date().isoformat()


def _realised_from_row(row: sqlite3.Row | dict[str, Any] | None) -> tuple[float, float, float] | None:
    """(gross_inr, costs_inr, realised_inr) derived from a closed/rolled position's stored fill columns (entry/exit
    price and the two costs sides — written once at close, never rewritten), else None. realised_inr is net of the
    recorded costs."""
    if row is None or row["exit_price"] is None:
        return None
    q = (1 if row["side"] == "buy" else -1) * int(row["lots"]) * int(row["lot_size"])
    gross = q * (float(row["exit_price"]) - float(row["entry_price"]))
    costs = float(row["entry_costs"] or 0.0) + float(row["exit_costs"] or 0.0)
    return round(gross, 2), round(costs, 2), round(gross - costs, 2)


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
        """``fills``: [{position_id, exit_price, exit_price_source, exit_costs}]. Refuses a position that is not open.

        The journal (one row per touched structure, carrying THAT structure's fills only) records each fill's realised
        money point-in-time (SPEC M3): ``gross_inr`` (signed qty × (exit − entry)), ``costs_inr`` (the entry and exit
        cost sides it already knows), ``realised_inr`` (net of those costs). The day read and the loss streak read
        these recorded facts back; they are never recomputed against moved marks."""
        ts = closed_at or now_ist()
        by_struct: dict[int, list[dict[str, Any]]] = {}
        with self._tx() as conn:
            for f in fills:
                pid = int(f["position_id"])
                if not float(f["exit_price"]) >= 0:            # also refused by the column's CHECK (new files)
                    raise BookError(f"position {pid}: an exit price must be ≥ 0 (got {f['exit_price']})")
                row = conn.execute("SELECT * FROM paper_fo_positions WHERE id = ?", (pid,)).fetchone()
                if row is None:
                    raise BookError(f"position {pid} does not exist")
                if row["status"] != "open":
                    raise BookError(f"position {pid} is already {row['status']}")
                exit_price, exit_costs = float(f["exit_price"]), float(f.get("exit_costs") or 0.0)
                conn.execute("""UPDATE paper_fo_positions SET status = ?, exit_price = ?, exit_price_source = ?, exit_costs = ?,
                                closed_at = ? WHERE id = ?""",
                             (status, exit_price, str(f.get("exit_price_source") or "unstated"), exit_costs, ts, pid))
                q = (1 if row["side"] == "buy" else -1) * int(row["lots"]) * int(row["lot_size"])
                gross = q * (exit_price - float(row["entry_price"]))
                costs = float(row["entry_costs"] or 0.0) + exit_costs
                by_struct.setdefault(int(row["structure_id"]), []).append(
                    {"position_id": pid, "exit_price": exit_price, "exit_price_source": str(f.get("exit_price_source") or "unstated"),
                     "exit_costs": exit_costs, "symbol": row["symbol"], "gross_inr": round(gross, 2),
                     "costs_inr": round(costs, 2), "realised_inr": round(gross - costs, 2)})
            for sid, sfills in by_struct.items():
                self._settle_structure(conn, sid, ts)
                self._journal(conn, action, sid, {"fills": sfills})
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

    # ── day summary (SPEC M1: the risk cockpit's TODAY read; PAPER book only) ───────────────────────────────────
    def day_summary(self, day: str) -> dict[str, Any]:
        """One IST session day of the PAPER book, aggregated here (never client-side money math):

        * ``realised_inr`` — the day's realised P&L net of the recorded costs (``gross_inr`` / ``costs_inr`` beside
          it), summed over the day's close / settle / roll events. Each event's money is the journal's recorded
          point-in-time figures (SPEC M3); an older row without them is derived from the stored fill columns
          (immutable after close) and labelled so; underivable → that event's realised is null, with a note.
        * ``mtm_change_inr`` — open positions' change on ``day``: the latest stored mark dated that day against the
          latest EOD mark before it (entry price when none), summed; null when nothing is marked that day.
          Positions without a mark dated ``day`` are listed in ``mtm_unmarked``.
        * ``bookings`` / ``closes`` / ``rolls`` — the day's journal events (a settle counts as a close: the exchange
          realised it); ``trades`` lists them chronologically with their money.
        * ``loss_streak`` — consecutive close/settle events with negative net realised, chronological over the whole
          journal up to the end of ``day`` (a roll never counts; a non-negative close resets it; an event whose
          realised cannot be derived leaves it unchanged). Session/stand-down rules live in the client.

        Day scoping: the journal row's ``ts`` converted to the IST calendar date (``ist_day``). Arithmetic over the
        paper book only — describes, does not predict."""
        day = str(day)[:10]
        out: dict[str, Any] = {"date": day, "realised_inr": 0.0, "realised_gross_inr": 0.0, "costs_inr": 0.0,
                               "mtm_change_inr": None, "mtm_positions": 0, "mtm_unmarked": [],
                               "bookings": 0, "closes": 0, "rolls": 0, "loss_streak": 0, "trades": [],
                               "realised_basis": "net of the recorded entry + exit costs", "notes": []}
        if self._absent():
            return out
        notes: set[str] = set()
        with self._conn() as conn:
            jrows = conn.execute("SELECT * FROM paper_fo_journal ORDER BY id").fetchall()
            pos = {int(r["id"]): r for r in conn.execute("SELECT * FROM paper_fo_positions").fetchall()}
            structs = {int(r["id"]): r for r in conn.execute("SELECT id, name, symbol FROM paper_fo_structures").fetchall()}
            seen: set[tuple[Any, ...]] = set()
            streak = 0
            for r in jrows:
                action = str(r["action"])
                if action not in ("book", "close", "settle", "roll"):
                    continue
                ev_day = ist_day(r["ts"])
                if ev_day is None or ev_day > day:
                    continue
                try:
                    payload = json.loads(r["payload"])
                except (TypeError, ValueError):
                    continue
                sid = r["structure_id"]
                s = structs.get(int(sid)) if sid is not None else None
                head = {"ts": r["ts"], "action": action, "structure_id": sid,
                        "name": s["name"] if s else None, "symbol": s["symbol"] if s else None}
                if action == "book":
                    if ev_day == day:
                        out["bookings"] += 1
                        out["trades"].append({**head, "position_ids": list(payload.get("position_ids") or []),
                                              "realised_inr": None, "gross_inr": None, "costs_inr": None, "realised_source": None})
                    continue
                fill_rows = payload.get("fills") if action in ("close", "settle") else payload.get("closes")
                fill_rows = [f for f in (fill_rows or []) if isinstance(f, dict) and f.get("position_id") is not None]
                pids = sorted({int(f["position_id"]) for f in fill_rows})
                key = (str(r["ts"]), action, tuple(pids))
                if key in seen:        # pre-M3 rows journalled every fill once per touched structure: one event
                    continue
                seen.add(key)
                gross = costs = net = 0.0
                known, source = True, "journal"
                for f in fill_rows:
                    if action in ("close", "settle") and f.get("realised_inr") is not None:
                        gross += float(f.get("gross_inr") or 0.0)
                        costs += float(f.get("costs_inr") or 0.0)
                        net += float(f["realised_inr"])
                        continue
                    source = "derived from the stored fills"
                    got = _realised_from_row(pos.get(int(f["position_id"])))
                    if got is None:
                        known = False
                        notes.add(f"realised is recorded on each close from {REALISED_RECORDED_FROM}; an earlier close "
                                  "could not be derived from the stored fills — its realised shows null")
                        continue
                    g, c, n = got
                    gross, costs, net = gross + g, costs + c, net + n
                if action in ("close", "settle"):
                    if known and fill_rows:
                        streak = streak + 1 if net < 0 else 0
                    if ev_day == day:
                        out["closes"] += 1
                elif ev_day == day:
                    out["rolls"] += 1
                if ev_day == day:
                    if known:
                        out["realised_inr"] = round(out["realised_inr"] + net, 2)
                        out["realised_gross_inr"] = round(out["realised_gross_inr"] + gross, 2)
                        out["costs_inr"] = round(out["costs_inr"] + costs, 2)
                    out["trades"].append({**head, "position_ids": pids,
                                          "realised_inr": round(net, 2) if known else None,
                                          "gross_inr": round(gross, 2) if known else None,
                                          "costs_inr": round(costs, 2) if known else None,
                                          "realised_source": source if known else None})
            out["loss_streak"] = streak
            # open MTM change on `day`, from the stored marks (point-in-time; the route freshens today's marks first)
            mtm, marked = 0.0, 0
            for p in pos.values():
                if p["status"] != "open" or (ist_day(p["opened_at"]) or "9999-12-31") > day:
                    continue
                pid = int(p["id"])
                cur = conn.execute("""SELECT price FROM paper_fo_marks WHERE position_id = ? AND mark_date = ?
                                      ORDER BY as_of DESC, first_seen_at DESC LIMIT 1""", (pid, day)).fetchone()
                if cur is None:
                    out["mtm_unmarked"].append(pid)
                    continue
                base = conn.execute("""SELECT price FROM paper_fo_marks WHERE position_id = ? AND kind = 'eod' AND mark_date < ?
                                       ORDER BY mark_date DESC, as_of DESC, first_seen_at DESC LIMIT 1""", (pid, day)).fetchone()
                base_px = float(base["price"]) if base is not None else float(p["entry_price"])
                q = (1 if p["side"] == "buy" else -1) * int(p["lots"]) * int(p["lot_size"])
                mtm += q * (float(cur["price"]) - base_px)
                marked += 1
            out["mtm_positions"] = marked
            if marked:
                out["mtm_change_inr"] = round(mtm, 2)
        out["notes"] = sorted(notes)
        return out

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

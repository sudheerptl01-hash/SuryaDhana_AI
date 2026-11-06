"""
User preferences, server-side (desktop program D3, PLAN §1 "User settings" / AC-12).

The terminal's user settings (watchlist, pins, recents, saved tickets, page preferences) used to
live only in each browser's localStorage, so the desktop app (a new origin) and every other
browser started empty. They now live here, keyed exactly like the localStorage keys, and the UI
client (ui/lib/prefs/sync.ts) hydrates before first render and writes through.

GET    /api/prefs                          -> {prefs: {key: {value, updated_at, deleted, provisional, origin}}, server_time,
                                               migration: {legacy_import_at, legacy_origin, legacy_keys, inferred}}
PUT    /api/prefs/{key}   {value, updated_at}   last-write-wins per key; older -> 409 + current
DELETE /api/prefs/{key}?updated_at=<ms>         tombstone (deleted=true) so deletes propagate
POST   /api/prefs/import  {items: {key: value}, origin, provisional?: bool}
                                           fill-only migration (never overwrites a real value;
                                           tombstones count as present) ->
                                           {imported, skipped, rejected, prefs, server_time}

Migration and provisional values
- A LEGACY import (provisional=false, the default) carries values that existed in a browser's
  localStorage before the sync code first ran there (the old :3000 origin): it fills keys that are
  absent OR provisional on the server.
- A PROVISIONAL import (provisional=true) carries values a never-synced device wrote after the
  sync code was installed, typically a component persisting its default state on first mount (the
  watchlist's `[]`): it fills absent keys only and is marked provisional, so a later legacy import
  still wins over it. Without this, opening the desktop app first would plant `[]` on the server
  and the owner's real watchlist from the old origin would be skipped.
- Any PUT/DELETE is a deliberate write and clears the provisional mark (LWW as usual).

Migration provenance (wave-2 contract K2): GET returns a durable top-level ``migration`` block,
``{legacy_import_at: epoch ms | null, legacy_origin: str | null, legacy_keys: int, inferred: bool}``.
It is written ONCE, by the first legacy import FROM A LEGACY BROWSER ORIGIN (http(s) on port 3000, the
old browser terminal; the same rule as the backfill and the UI's isLegacyBrowserOrigin) that carries at least
one valid item (``legacy_keys`` = the keys that import actually filled; 0 when the server already held real
values for all of them). A non-provisional import from any other origin (an earlier app build's WKWebView store,
a browser tab on localhost:8010) fills values as before but records no migration (desktop review RAPI-02), and a
block that an older build wrote for such an origin is reported as NO_MIGRATION and replaced by the first real
one. Otherwise nothing clears it: PUTs and DELETEs rewrite a record's own ``origin``/``provisional`` (so per-record
provenance fades as the owner edits), but never this block. It lives in the ``meta`` table. A store that
already held the migration before this field existed is backfilled once from per-record provenance (the
UI's own rule: live, non-provisional records written from a port-3000 origin); that block says
``inferred: true`` and its ``legacy_import_at`` is the earliest such record's server time. Never
migrated: ``{legacy_import_at: null, legacy_origin: null, legacy_keys: 0, inferred: false}``. A quarantined
(corrupt) store starts a fresh block. The UI's migration notice and ``start-local.sh status`` read it.

Semantics
- `updated_at` is the client's change time in epoch ms (Date.now()). A write wins iff its
  updated_at is newer than the stored one; an identical (updated_at, value, deleted) replay is an
  idempotent 200 (several windows may flush the same queued write); anything else -> 409 with
  the current record so the client adopts the server state. Timestamps > now + 24 h are refused
  (a far-future stamp would win forever).
- Limits: key ^[A-Za-z0-9._:-]{1,128}$, value <= 256 KB (UTF-8), <= 5 MB across live values,
  <= 500 live keys. Tombstones do not count and are pruned after 90 days.
- Values are opaque strings (the localStorage value verbatim). Lone UTF-16 surrogates cannot be
  stored as SQLite TEXT and are refused with 422.
- PUT and import require `Content-Type: application/json` (415 otherwise; desktop review
  C2-security-08): a cross-site page can send `text/plain` or form bodies without a CORS preflight, so
  together with the Origin guard (shared/http_guard.py) this keeps other sites from filling the quota.

Storage: SQLite (NOT DuckDB: tiny, write-heavy, must never contend with the 4 GB market DB),
file PREFS_DB (default <repo>/data/ui_prefs.sqlite), WAL, busy_timeout 5 s, created on demand,
schema versioned with PRAGMA user_version (1). The ``meta`` table (k TEXT PRIMARY KEY, v TEXT) is
additive and created on open without changing user_version: a ui-api from before K2 ignores it, so a
rollback keeps working on the same file. A file that is not a database / is corrupt is
renamed to `<file>.corrupt-<ts>` (never deleted) and a fresh store is created: preferences are
replicated in every client, and clients re-upload keys the server lacks, so the store self-heals.
A store written by a NEWER schema is refused with 503 (never downgraded).

In-app import from the old browser terminal (page review 5 Nov 2026, M35). The owner's watchlist and pins live
only in the localStorage of the browser that used http://localhost:3000, which nothing but a page ON that origin can
read. One click in the terminal (POST /api/prefs/legacy-import) starts a one-shot page on 127.0.0.1:3000 (and [::1]
when free), served by this process: no Next dev server, no second door to the API. Opened in that browser, the page
reads the same SYNC keys the sync code's legacy import reads (the UI sends them), shows what it found, and only on
the owner's click posts them to itself; this module then runs the fill-only legacy import above (it never replaces
a value the owner set in the app; a provisional default is filled) with the page's own origin, so the K2 migration
block is recorded exactly as the :3000 sync code would have. The page is single-use (closed after an import), lives
at most LEGACY_IMPORT_TTL_S, answers only /import with a random token, checks Host (DNS rebinding) and, for the POST,
Origin + Content-Type + the token, and refuses to start when anything already listens on the port (the Next UI then
imports by itself). GET /api/prefs/legacy-import reports its state and the imported / skipped key NAMES (never a
value); POST /api/prefs/legacy-import/stop closes it.

Event loop: GET/DELETE are sync handlers (threadpool); PUT/import read the capped body
asynchronously and run the SQLite work in the threadpool. Logs are structured JSON lines with
keys, sizes and outcomes only, never values.
"""
from __future__ import annotations

import contextlib
import hmac
import html
import json
import logging
import os
import re
import secrets
import socket
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from errors import error_block, fail
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

router = APIRouter()
log = logging.getLogger("ui-api.prefs")

KEY_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
MAX_VALUE_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 5 * 1024 * 1024
MAX_KEYS = 500
MAX_IMPORT_ITEMS = 500
TOMBSTONE_TTL_MS = 90 * 24 * 3600 * 1000
MAX_FUTURE_SKEW_MS = 24 * 3600 * 1000
MAX_TIMESTAMP = 2**53 - 1
# Request body caps (JSON escaping can inflate a value up to 6x for control characters).
MAX_PUT_BODY = 6 * MAX_VALUE_BYTES + 4096
MAX_IMPORT_BODY = 8 * 1024 * 1024
SCHEMA_VERSION = 1
BUSY_TIMEOUT_MS = 5000
META_MIGRATION = "migration"                 # meta row: the K2 migration block (JSON)
META_MIGRATION_CHECKED = "migration.backfill_checked"
LEGACY_BROWSER_PORT = 3000                   # the old browser terminal (ui/lib/prefs/migration.ts)
NO_MIGRATION: dict[str, Any] = {"legacy_import_at": None, "legacy_origin": None, "legacy_keys": 0, "inferred": False}

_SQLITE_CORRUPT = 11
_SQLITE_NOTADB = 26


def _now_ms() -> int:
    return int(time.time() * 1000)


def _event(event: str, **fields: Any) -> None:
    """One structured JSON log line (never values: keys, sizes, outcomes)."""
    with contextlib.suppress(Exception):  # logging must never break a request
        log.info(json.dumps({"event": event, **fields}, ensure_ascii=False, default=str))


def default_db_path() -> Path:
    env = os.environ.get("PREFS_DB", "").strip()
    if env:
        return Path(env).expanduser()
    for root in (Path(__file__).resolve().parents[3] / "data", Path("/app/data")):
        if root.is_dir():
            return root / "ui_prefs.sqlite"
    return Path("ui_prefs.sqlite")


class PrefsUnavailable(RuntimeError):
    """The store cannot be opened (newer schema, unreadable directory, disk I/O)."""


class QuotaExceeded(ValueError):
    pass


class InvalidValue(ValueError):
    pass


def _utf8_len(value: str) -> int:
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError as e:  # lone surrogate: not storable as SQLite TEXT
        raise InvalidValue("value is not valid unicode (lone surrogate)") from e


def _is_corruption(e: BaseException) -> bool:
    if not isinstance(e, sqlite3.DatabaseError) or isinstance(e, sqlite3.OperationalError):
        return False
    code = getattr(e, "sqlite_errorcode", None)
    if code is not None:
        return (code & 0xFF) in (_SQLITE_CORRUPT, _SQLITE_NOTADB)
    msg = str(e).lower()
    return "not a database" in msg or "malformed" in msg


def is_legacy_browser_origin(origin: Any) -> bool:
    """http(s) origin on port 3000 (same rule as ui/lib/prefs/migration.ts isLegacyBrowserOrigin)."""
    if not isinstance(origin, str) or not origin:
        return False
    try:
        u = urlsplit(origin)
        return u.scheme in ("http", "https") and u.port == LEGACY_BROWSER_PORT
    except ValueError:
        return False


def _migration_block(raw: str | None) -> dict[str, Any]:
    if not raw:
        return dict(NO_MIGRATION)
    try:
        d = json.loads(raw)
    except ValueError:
        return dict(NO_MIGRATION)
    if not isinstance(d, dict):
        return dict(NO_MIGRATION)
    at, origin, keys = d.get("legacy_import_at"), d.get("legacy_origin"), d.get("legacy_keys")
    if not is_legacy_browser_origin(origin):       # written by the pre-RAPI-02 rule for a non-3000 origin
        return dict(NO_MIGRATION)
    return {
        "legacy_import_at": int(at) if isinstance(at, (int, float)) and not isinstance(at, bool) else None,
        "legacy_origin": origin if isinstance(origin, str) else None,
        "legacy_keys": int(keys) if isinstance(keys, int) and not isinstance(keys, bool) and keys >= 0 else 0,
        "inferred": bool(d.get("inferred", False)),
    }


def _record(row: sqlite3.Row | tuple | None) -> dict[str, Any] | None:
    if row is None:
        return None
    _key, value, updated_at, deleted = row[0], row[1], row[2], row[3]
    return {"value": None if deleted else value, "updated_at": int(updated_at), "deleted": bool(deleted)}


class PrefsStore:
    """One SQLite file, one serialized connection (writes are tiny; a lock is simpler than a pool).

    BEGIN IMMEDIATE + busy_timeout also make it safe if two processes ever share the file.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

    # ── connection lifecycle ───────────────────────────────────────────────────────────────
    def _open(self) -> sqlite3.Connection:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise PrefsUnavailable(f"cannot create {self.path.parent.name}/: {e.strerror}") from e
        deadline = time.monotonic() + BUSY_TIMEOUT_MS / 1000
        while True:
            conn = sqlite3.connect(str(self.path), timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None,
                                   check_same_thread=False)
            try:
                conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
                # Switching a fresh file to WAL takes an exclusive lock and can return SQLITE_BUSY
                # without consulting the busy handler, so racing first opens retry here.
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                self._migrate(conn)
                self._ensure_meta(conn)
                return conn
            except sqlite3.OperationalError as e:
                conn.close()
                msg = str(e).lower()
                if ("locked" in msg or "busy" in msg) and time.monotonic() < deadline:
                    time.sleep(0.02)
                    continue
                raise
            except BaseException:
                conn.close()
                raise

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version > SCHEMA_VERSION:
            raise PrefsUnavailable(f"prefs store schema v{version} is newer than this ui-api (v{SCHEMA_VERSION})")
        if version == SCHEMA_VERSION:
            return
        conn.execute("BEGIN IMMEDIATE")
        try:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])  # re-check under the lock
            if version == SCHEMA_VERSION:
                conn.execute("COMMIT")
                return
            conn.execute(
                """CREATE TABLE IF NOT EXISTS prefs (
                       key        TEXT PRIMARY KEY,
                       value      TEXT,
                       updated_at INTEGER NOT NULL,
                       deleted    INTEGER NOT NULL DEFAULT 0,
                       bytes      INTEGER NOT NULL DEFAULT 0,
                       provisional INTEGER NOT NULL DEFAULT 0,
                       origin     TEXT,
                       server_at  INTEGER NOT NULL
                   ) WITHOUT ROWID"""
            )
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise

    @staticmethod
    def _ensure_meta(conn: sqlite3.Connection) -> None:
        """The additive meta table, plus a one-time backfill of the K2 migration block for a store that was
        migrated before the block existed (see the module docstring)."""
        conn.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL) WITHOUT ROWID")
        if conn.execute("SELECT 1 FROM meta WHERE k = ?", (META_MIGRATION_CHECKED,)).fetchone():
            return
        conn.execute("BEGIN IMMEDIATE")
        try:
            if conn.execute("SELECT 1 FROM meta WHERE k = ?", (META_MIGRATION_CHECKED,)).fetchone() is None:
                has_block = conn.execute("SELECT 1 FROM meta WHERE k = ?", (META_MIGRATION,)).fetchone()
                rows = conn.execute("SELECT origin, server_at FROM prefs WHERE deleted = 0 AND provisional = 0 "
                                    "AND origin IS NOT NULL").fetchall()
                legacy = [(str(o), int(at)) for o, at in rows if is_legacy_browser_origin(o)]
                if legacy and not has_block:
                    counts: dict[str, int] = {}
                    for o, _ in legacy:
                        counts[o] = counts.get(o, 0) + 1
                    origin = min(counts, key=lambda o: (-counts[o], o))
                    block = {"legacy_import_at": min(at for _, at in legacy), "legacy_origin": origin,
                             "legacy_keys": len(legacy), "inferred": True}
                    conn.execute("INSERT INTO meta (k, v) VALUES (?, ?)", (META_MIGRATION, json.dumps(block)))
                    _event("prefs.migration_backfilled", origin=origin, keys=len(legacy))
                conn.execute("INSERT INTO meta (k, v) VALUES (?, ?)", (META_MIGRATION_CHECKED, str(_now_ms())))
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

    def _quarantine(self, err: BaseException) -> None:
        if self._conn is not None:
            with contextlib.suppress(Exception):  # a corrupt file may refuse a clean close
                self._conn.close()
            self._conn = None
        stamp = time.strftime("%Y%m%d-%H%M%S")
        moved = []
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(self.path) + suffix)
            if p.exists():
                dest = Path(f"{self.path}{suffix}.corrupt-{stamp}")
                try:
                    p.replace(dest)
                    moved.append(dest.name)
                except OSError:
                    pass
        log.error(json.dumps({"event": "prefs.quarantine", "file": self.path.name, "moved": moved,
                              "error": type(err).__name__, "message": str(err)[:200]}))

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            try:
                self._conn = self._open()
            except PrefsUnavailable:
                raise
            except sqlite3.DatabaseError as e:
                if not _is_corruption(e):
                    raise PrefsUnavailable(f"prefs store unavailable: {e}") from e
                self._quarantine(e)
                try:
                    self._conn = self._open()
                except sqlite3.DatabaseError as e2:
                    raise PrefsUnavailable(f"prefs store unavailable after quarantine: {e2}") from e2
        return self._conn

    def _run(self, fn):
        """Run fn(conn) under the lock; on corruption quarantine, recreate and retry once."""
        with self._lock:
            for attempt in (0, 1):
                conn = self._connection()
                try:
                    return fn(conn)
                except sqlite3.DatabaseError as e:
                    if attempt == 0 and _is_corruption(e):
                        self._quarantine(e)
                        continue
                    if isinstance(e, sqlite3.OperationalError):
                        raise PrefsUnavailable(f"prefs store busy or unwritable: {e}") from e
                    raise
            raise PrefsUnavailable("prefs store unavailable")  # pragma: no cover

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # ── queries ────────────────────────────────────────────────────────────────────────────
    def all(self) -> dict[str, dict[str, Any]]:
        """Every record, plus its provenance (`provisional`, `origin`) for the UI's one-time migration notice."""
        def q(conn: sqlite3.Connection):
            rows = conn.execute(
                "SELECT key, value, updated_at, deleted, provisional, origin FROM prefs ORDER BY key").fetchall()
            return {r[0]: {**(_record(r) or {}), "provisional": bool(r[4]), "origin": r[5]} for r in rows}
        return self._run(q)

    def migration(self) -> dict[str, Any]:
        """The durable K2 migration block (NO_MIGRATION until the first legacy import)."""
        def q(conn: sqlite3.Connection):
            row = conn.execute("SELECT v FROM meta WHERE k = ?", (META_MIGRATION,)).fetchone()
            return _migration_block(row[0] if row else None)
        return self._run(q)

    def snapshot(self) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
        """Every record and the migration block, read under one lock."""
        with self._lock:
            return self.all(), self.migration()

    @staticmethod
    def _get(conn: sqlite3.Connection, key: str):
        return conn.execute("SELECT key, value, updated_at, deleted FROM prefs WHERE key = ?", (key,)).fetchone()

    @staticmethod
    def _check_quota(conn: sqlite3.Connection, key: str, nbytes: int) -> None:
        count, total = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(bytes), 0) FROM prefs WHERE deleted = 0 AND key != ?", (key,)
        ).fetchone()
        if count + 1 > MAX_KEYS:
            raise QuotaExceeded(f"too many preference keys (max {MAX_KEYS})")
        if total + nbytes > MAX_TOTAL_BYTES:
            raise QuotaExceeded(f"preferences exceed {MAX_TOTAL_BYTES // (1024 * 1024)} MB in total")

    @staticmethod
    def _prune(conn: sqlite3.Connection, now: int) -> None:
        conn.execute("DELETE FROM prefs WHERE deleted = 1 AND server_at < ?", (now - TOMBSTONE_TTL_MS,))

    def write(self, key: str, value: str | None, updated_at: int, origin: str | None = None
              ) -> tuple[bool, dict[str, Any]]:
        """LWW upsert (value None = tombstone). Returns (applied_or_idempotent, record)."""
        deleted = value is None
        nbytes = 0 if deleted else _utf8_len(value)  # type: ignore[arg-type]

        def tx(conn: sqlite3.Connection):
            conn.execute("BEGIN IMMEDIATE")
            try:
                cur = self._get(conn, key)
                if cur is not None:
                    c_updated, c_deleted, c_value = int(cur[2]), bool(cur[3]), cur[1]
                    same = c_deleted == deleted and (deleted or c_value == value)
                    if updated_at < c_updated or (updated_at == c_updated and not same):
                        conn.execute("ROLLBACK")
                        return False, _record(cur)
                    if updated_at == c_updated and same:
                        conn.execute("ROLLBACK")
                        return True, _record(cur)
                if not deleted:
                    self._check_quota(conn, key, nbytes)
                now = _now_ms()
                conn.execute(
                    """INSERT INTO prefs (key, value, updated_at, deleted, bytes, provisional, origin, server_at)
                       VALUES (?, ?, ?, ?, ?, 0, ?, ?)
                       ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at,
                         deleted = excluded.deleted, bytes = excluded.bytes, provisional = 0,
                         origin = excluded.origin, server_at = excluded.server_at""",
                    (key, None if deleted else value, updated_at, int(deleted), nbytes, origin, now),
                )
                self._prune(conn, now)
                conn.execute("COMMIT")
                return True, {"value": None if deleted else value, "updated_at": updated_at, "deleted": deleted}
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
        return self._run(tx)

    def import_items(self, items: dict[str, Any], origin: str | None, provisional: bool = False) -> dict[str, Any]:
        """Fill-only import. Legacy (provisional=False): fills keys absent or provisional on the server.
        Provisional: fills absent keys only, marked provisional. Tombstones always count as present."""
        imported: list[str] = []
        skipped: list[str] = []
        rejected: dict[str, str] = {}
        valid: dict[str, tuple[str, int]] = {}
        for key in sorted(items):
            value = items[key]
            if not isinstance(key, str) or not KEY_RE.match(key):
                rejected[str(key)[:140]] = "invalid key"
                continue
            if not isinstance(value, str):
                rejected[key] = "value must be a string"
                continue
            try:
                n = _utf8_len(value)
            except InvalidValue as e:
                rejected[key] = str(e)
                continue
            if n > MAX_VALUE_BYTES:
                rejected[key] = f"value larger than {MAX_VALUE_BYTES // 1024} KB"
                continue
            valid[key] = (value, n)

        def tx(conn: sqlite3.Connection):
            conn.execute("BEGIN IMMEDIATE")
            try:
                now = _now_ms()
                for key, (value, n) in valid.items():
                    row = conn.execute("SELECT deleted, provisional, updated_at FROM prefs WHERE key = ?",
                                       (key,)).fetchone()
                    replace_provisional = (row is not None and not provisional and bool(row[1]) and not row[0])
                    if row is not None and not replace_provisional:
                        skipped.append(key)
                        continue
                    try:
                        self._check_quota(conn, key, n)
                    except QuotaExceeded as e:
                        rejected[key] = str(e)
                        continue
                    stamp = max(now, int(row[2]) + 1) if row is not None else now
                    conn.execute(
                        """INSERT INTO prefs (key, value, updated_at, deleted, bytes, provisional, origin, server_at)
                           VALUES (?, ?, ?, 0, ?, ?, ?, ?)
                           ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at,
                             deleted = 0, bytes = excluded.bytes, provisional = excluded.provisional,
                             origin = excluded.origin, server_at = excluded.server_at""",
                        (key, value, stamp, n, int(provisional), origin, now),
                    )
                    imported.append(key)
                if not provisional and valid and is_legacy_browser_origin(origin):
                    current = conn.execute("SELECT v FROM meta WHERE k = ?", (META_MIGRATION,)).fetchone()
                    if current is None or _migration_block(current[0])["legacy_import_at"] is None:
                        block = {"legacy_import_at": now, "legacy_origin": origin, "legacy_keys": len(imported),
                                 "inferred": False}
                        conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)",
                                     (META_MIGRATION, json.dumps(block)))
                        _event("prefs.migration_recorded", origin=origin, keys=len(imported))
                prefs = {}
                for key in valid:
                    rec = _record(self._get(conn, key))
                    if rec is not None:
                        prefs[key] = rec
                conn.execute("COMMIT")
                return prefs
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
        prefs = self._run(tx)
        return {"imported": imported, "skipped": skipped, "rejected": rejected, "prefs": prefs}


_stores: dict[str, PrefsStore] = {}
_stores_lock = threading.Lock()


def get_store() -> PrefsStore:
    """The store for the current PREFS_DB (resolved per call so tests can repoint it)."""
    path = default_db_path()
    k = str(path)
    with _stores_lock:
        st = _stores.get(k)
        if st is None:
            st = _stores[k] = PrefsStore(path)
        return st


def close_all() -> None:
    """Close every open store (tests; graceful shutdown); a running one-shot import page is stopped and forgotten."""
    global _legacy
    legacy_import_stop("closed")
    with _legacy_lock:
        _legacy = None
    with _stores_lock:
        for st in _stores.values():
            st.close()
        _stores.clear()


# ── HTTP layer ─────────────────────────────────────────────────────────────────────────────────

def _check_key(key: str) -> None:
    if not KEY_RE.match(key or ""):
        fail(422, "invalid", "invalid preference key", hint="keys match ^[A-Za-z0-9._:-]{1,128}$")


def _check_ts(updated_at: Any) -> int:
    if isinstance(updated_at, bool) or not isinstance(updated_at, (int, float)):
        fail(422, "invalid", "updated_at must be epoch milliseconds")
    if isinstance(updated_at, float):
        if not updated_at.is_integer():
            fail(422, "invalid", "updated_at must be an integer (epoch ms)")
        updated_at = int(updated_at)
    if updated_at < 0 or updated_at > MAX_TIMESTAMP:
        fail(422, "invalid", "updated_at out of range")
    if updated_at > _now_ms() + MAX_FUTURE_SKEW_MS:
        fail(422, "invalid", "updated_at is more than 24 h in the future", hint="check the client clock")
    return int(updated_at)


def _origin(o: Any) -> str | None:
    if not isinstance(o, str):
        return None
    return re.sub(r"[^\x20-\x7e]", "", o)[:200] or None


def _require_json_content_type(request: Request) -> None:
    """415 unless the body is declared as JSON (`application/json`, parameters such as charset allowed)."""
    media_type = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        fail(415, "invalid", "Content-Type must be application/json",
             hint="send the body as JSON with the header Content-Type: application/json")


async def _read_json(request: Request, limit: int) -> Any:
    """Read the body with a hard cap (Content-Length is checked first, chunked bodies are counted)."""
    _require_json_content_type(request)
    cl = request.headers.get("content-length")
    if cl is not None:
        try:
            if int(cl) > limit:
                fail(413, "invalid", f"request body larger than {limit // 1024} KB")
        except ValueError:
            fail(400, "invalid", "bad Content-Length")
    buf = bytearray()
    async for chunk in request.stream():
        buf.extend(chunk)
        if len(buf) > limit:
            fail(413, "invalid", f"request body larger than {limit // 1024} KB")
    try:
        return json.loads(bytes(buf) or b"null")
    except (ValueError, UnicodeDecodeError):
        fail(422, "invalid", "body is not valid JSON")


def _unavailable(e: PrefsUnavailable):
    _event("prefs.unavailable", message=str(e)[:200])
    fail(503, "state", str(e), hint="the preferences store (PREFS_DB) could not be opened; the terminal keeps local settings")


def _conflict(key: str, current: dict[str, Any]) -> JSONResponse:
    message = "a newer value is stored on the server"
    return JSONResponse({"detail": message, "error": error_block("state", message), "key": key,
                         "current": current, "server_time": _now_ms()}, status_code=409)


@router.get("")
def list_prefs() -> dict[str, Any]:
    """Every preference (tombstones included, so clients can apply deletes) plus the K2 migration block."""
    try:
        prefs, migration = get_store().snapshot()
    except PrefsUnavailable as e:
        _unavailable(e)
    return {"prefs": prefs, "server_time": _now_ms(), "migration": migration}


def _do_write(key: str, value: str | None, updated_at: int, origin: str | None, op: str):
    try:
        ok, rec = get_store().write(key, value, updated_at, origin)
    except PrefsUnavailable as e:
        _unavailable(e)
    except QuotaExceeded as e:
        _event(f"prefs.{op}", key=key, result="quota")
        fail(413, "invalid", str(e), hint="remove unused preferences")
    except InvalidValue as e:
        fail(422, "invalid", str(e))
    if not ok:
        _event(f"prefs.{op}", key=key, result="conflict", updated_at=updated_at, current_at=rec["updated_at"])
        return _conflict(key, rec)
    _event(f"prefs.{op}", key=key, result="ok", updated_at=updated_at,
           bytes=0 if value is None else len(value), origin=origin)
    return {"key": key, "pref": rec, "server_time": _now_ms()}


@router.put("/{key}")
async def put_pref(key: str, request: Request):
    """Last-write-wins upsert of one key: body {value: string, updated_at: epoch ms}."""
    _check_key(key)
    body = await _read_json(request, MAX_PUT_BODY)
    if not isinstance(body, dict):
        fail(422, "invalid", "body must be an object {value, updated_at}")
    value = body.get("value")
    if not isinstance(value, str):
        fail(422, "invalid", "value must be a string")
    updated_at = _check_ts(body.get("updated_at"))
    try:
        nbytes = _utf8_len(value)
    except InvalidValue as e:
        fail(422, "invalid", str(e))
    if nbytes > MAX_VALUE_BYTES:
        fail(413, "invalid", f"value larger than {MAX_VALUE_BYTES // 1024} KB")
    origin = _origin(body.get("origin")) or _origin(request.headers.get("origin"))
    return await run_in_threadpool(_do_write, key, value, updated_at, origin, "put")


@router.delete("/{key}")
def delete_pref(key: str, request: Request, updated_at: int | None = Query(None)):
    """Tombstone one key (deleted=true) with LWW against the stored updated_at."""
    _check_key(key)
    if updated_at is None:
        fail(422, "invalid", "updated_at query parameter is required (epoch ms)")
    ts = _check_ts(updated_at)
    return _do_write(key, None, ts, _origin(request.headers.get("origin")), "delete")


@router.post("/import")
async def import_prefs(request: Request):
    """One-time migration: {items: {key: value}, origin}. Only keys absent on the server are written."""
    body = await _read_json(request, MAX_IMPORT_BODY)
    if not isinstance(body, dict) or not isinstance(body.get("items"), dict):
        fail(422, "invalid", "body must be {items: {key: value}, origin}")
    items: dict[str, Any] = body["items"]
    if len(items) > MAX_IMPORT_ITEMS:
        fail(413, "invalid", f"at most {MAX_IMPORT_ITEMS} items per import")
    origin = _origin(body.get("origin"))
    provisional = body.get("provisional", False)
    if not isinstance(provisional, bool):
        fail(422, "invalid", "provisional must be a boolean")

    def run() -> dict[str, Any]:
        try:
            return get_store().import_items(items, origin, provisional)
        except PrefsUnavailable as e:
            _unavailable(e)
            raise  # pragma: no cover - _unavailable raises

    out = await run_in_threadpool(run)
    _event("prefs.import", origin=origin, provisional=provisional, imported=out["imported"],
           skipped=len(out["skipped"]), rejected=sorted(out["rejected"]))
    return {**out, "server_time": _now_ms()}


# ── In-app import from the old browser terminal (page review 5 Nov 2026, M35; see the module docstring) ─────────

LEGACY_IMPORT_TTL_S = 600
LEGACY_IMPORT_MAX_KEYS = 100
_LEGACY_STATES = ("idle", "waiting", "done", "expired", "stopped", "closed", "port_busy", "failed")


def legacy_import_port() -> int:
    """The old browser terminal's port (PREFS_LEGACY_IMPORT_PORT overrides, for tests only)."""
    try:
        p = int(os.environ.get("PREFS_LEGACY_IMPORT_PORT", LEGACY_BROWSER_PORT))
    except ValueError:
        return LEGACY_BROWSER_PORT
    return p if 1 <= p <= 65535 else LEGACY_BROWSER_PORT


def _port_answers(host: str, port: int, family: int = socket.AF_INET) -> bool:
    """True when something already accepts connections on host:port (never bind over another listener)."""
    try:
        with socket.socket(family, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            return s.connect_ex((host, port)) == 0
    except OSError:
        return False


class _Server4(ThreadingHTTPServer):
    allow_reuse_address = False            # never share the port with a listener that is already there
    daemon_threads = True


class _Server6(_Server4):
    address_family = socket.AF_INET6


class _LegacyImportSession:
    """One single-use import page: token, allowed keys, listeners, outcome (key names only)."""

    def __init__(self, port: int, keys: list[str]):
        self.port = port
        self.keys = keys
        self.token = secrets.token_urlsafe(24)
        self.started_at = _now_ms()
        self.expires_at = self.started_at + LEGACY_IMPORT_TTL_S * 1000
        self.state = "waiting"
        self.result: dict[str, Any] | None = None
        self.finished_at: int | None = None
        self.servers: list[ThreadingHTTPServer] = []
        self.timer: threading.Timer | None = None
        self.nonce = secrets.token_urlsafe(16)

    @property
    def url(self) -> str:
        return f"http://localhost:{self.port}/import?t={self.token}"

    def hosts(self) -> set[str]:
        return {f"localhost:{self.port}", f"127.0.0.1:{self.port}", f"[::1]:{self.port}"}

    def origins(self) -> set[str]:
        return {f"http://{h}" for h in self.hosts()}

    def public(self) -> dict[str, Any]:
        live = self.state == "waiting"
        r = self.result or {}
        return {"state": self.state, "port": self.port, "url": self.url if live else None,
                "urls": [self.url, f"http://127.0.0.1:{self.port}/import?t={self.token}"] if live else [],
                "expires_at": self.expires_at, "started_at": self.started_at, "finished_at": self.finished_at,
                "imported": list(r.get("imported", [])), "skipped": list(r.get("skipped", [])),
                "rejected": sorted(r.get("rejected", {})), "found": r.get("found")}


_legacy: _LegacyImportSession | None = None
_legacy_lock = threading.Lock()


def _legacy_close(sess: _LegacyImportSession, state: str) -> None:
    """Stop the listeners (from any thread except their own serve loop) and record the final state."""
    if sess.state == "waiting":
        sess.state = state
        sess.finished_at = _now_ms()
    if sess.timer is not None:
        sess.timer.cancel()
    for srv in sess.servers:
        with contextlib.suppress(Exception):
            srv.shutdown()
        with contextlib.suppress(Exception):
            srv.server_close()
    sess.servers = []


def legacy_import_stop(state: str = "stopped") -> dict[str, Any]:
    """Close a running import page (POST /api/prefs/legacy-import/stop, close_all)."""
    with _legacy_lock:
        sess = _legacy
    if sess is None:
        return {"state": "idle"}
    _legacy_close(sess, state)
    return sess.public()


def _page_html(sess: _LegacyImportSession) -> str:
    keys = json.dumps(sess.keys)
    tok = json.dumps(sess.token)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SuryaDhana · import settings</title><style>
body{{background:#05070a;color:#d7dde8;font:14px/1.5 ui-monospace,Menlo,monospace;margin:0;padding:24px;max-width:720px}}
h1{{font-size:15px;letter-spacing:2px;color:#ffb000;margin:0 0 12px}} .k{{color:#7f8a9c}} .ok{{color:#16d98a}} .warn{{color:#ffb000}}
button{{font:inherit;font-weight:700;letter-spacing:1px;background:#ffb000;color:#05070a;border:0;padding:10px 16px;min-height:44px;cursor:pointer}}
button[disabled]{{opacity:.5;cursor:default}} li{{margin:2px 0}} code{{color:#ffb000}}
</style></head><body><h1>SURYADHANA · IMPORT SETTINGS FROM THE BROWSER TERMINAL</h1>
<p class="k">This one-time page runs on <code>{html.escape(f"http://localhost:{sess.port}")}</code>, the old terminal's address, so it can
read the watchlist, pins and page settings this browser kept for it. Nothing leaves this computer; the terminal's own
copy is filled only where you have not set the same setting in the app.</p>
<div id="found">Reading this browser's settings…</div>
<p><button id="go" disabled>IMPORT</button></p><div id="out"></div>
<script nonce="{sess.nonce}">
(function () {{
  var KEYS = {keys}, T = {tok}, items = {{}}, n = 0;
  function count(v) {{ try {{ var x = JSON.parse(v); return Array.isArray(x) ? x.length : null }} catch (e) {{ return null }} }}
  var lines = [];
  for (var i = 0; i < KEYS.length; i++) {{
    var v = null;
    try {{ v = window.localStorage.getItem(KEYS[i]) }} catch (e) {{ v = null }}
    if (v === null) continue;
    items[KEYS[i]] = v; n++;
    var c = count(v);
    var name = KEYS[i] === 'suryadhana.watchlist' ? 'watchlist' : KEYS[i] === 'newsTerminal.pins.v1' ? 'pins' : KEYS[i];
    lines.push('<li>' + name.replace(/[<>&]/g, '') + (c !== null ? ' · ' + c + (c === 1 ? ' entry' : ' entries') : '') + '</li>');
  }}
  var found = document.getElementById('found'), go = document.getElementById('go'), out = document.getElementById('out');
  if (!n) {{
    found.innerHTML = '<p class="warn">This browser holds no terminal settings for this address. If you used the old terminal in another browser, copy this page\\'s address into that browser.</p>';
    return;
  }}
  found.innerHTML = '<p>Found ' + n + ' setting' + (n === 1 ? '' : 's') + ':</p><ul>' + lines.join('') + '</ul>';
  go.disabled = false;
  go.textContent = 'IMPORT ' + n + ' SETTING' + (n === 1 ? '' : 'S');
  go.onclick = function () {{
    go.disabled = true; out.textContent = 'Importing…';
    fetch('/import?t=' + encodeURIComponent(T), {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ items: items }}) }})
      .then(function (r) {{ return r.json().then(function (j) {{ return [r.ok, j] }}) }})
      .then(function (a) {{
        var ok = a[0], j = a[1] || {{}};
        if (!ok) {{ out.innerHTML = '<p class="warn">' + String(j.detail || 'the import was refused').replace(/[<>&]/g, '') + '</p>'; return }}
        var imp = (j.imported || []).length, sk = (j.skipped || []).length;
        out.innerHTML = '<p class="ok">Imported ' + imp + ' setting' + (imp === 1 ? '' : 's') + '.' + (sk ? ' Kept ' + sk + ' you already set in the app.' : '')
          + '</p><p class="k">You can close this tab; the terminal picks the settings up on its next focus.</p>';
      }})
      .catch(function () {{ out.innerHTML = '<p class="warn">The terminal did not answer. Start the import again from the terminal.</p>' }});
  }};
}})();
</script></body></html>"""


class _LegacyHandler(BaseHTTPRequestHandler):
    server_version = "SuryaDhanaImport"
    sys_version = ""
    session: _LegacyImportSession | None = None          # bound per session (a subclass per session)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - BaseHTTPRequestHandler's signature
        return                                            # no access log with the token in it

    def _send(self, code: int, body: bytes, ctype: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, obj: dict[str, Any]) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _check(self) -> tuple[_LegacyImportSession, dict[str, list[str]]] | None:
        sess = self.session
        u = urlsplit(self.path)
        if sess is None or u.path != "/import":
            self._json(404, {"detail": "not found"})
            return None
        if (self.headers.get("Host") or "").lower() not in sess.hosts():
            self._json(403, {"detail": "wrong host"})
            return None
        q = parse_qs(u.query)
        tok = (q.get("t") or [""])[0]
        if sess.state != "waiting" or _now_ms() > sess.expires_at:
            self._json(410, {"detail": "this import page has closed: start it again from the terminal"})
            return None
        if not hmac.compare_digest(tok.encode(), sess.token.encode()):
            self._json(403, {"detail": "this link is not valid: start the import again from the terminal"})
            return None
        return sess, q

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        got = self._check()
        if got is None:
            return
        sess, _q = got
        csp = (f"default-src 'none'; script-src 'nonce-{sess.nonce}'; style-src 'unsafe-inline'; connect-src 'self'; "
               "form-action 'none'; frame-ancestors 'none'; base-uri 'none'")
        self._send(200, _page_html(sess).encode(), "text/html; charset=utf-8", {"Content-Security-Policy": csp})

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        got = self._check()
        if got is None:
            return
        sess, _q = got
        origin = (self.headers.get("Origin") or "").lower()
        if origin not in sess.origins():
            self._json(403, {"detail": "the import must come from the import page itself"})
            return
        if (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower() != "application/json":
            self._json(415, {"detail": "Content-Type must be application/json"})
            return
        try:
            n = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            n = -1
        if n < 0 or n > MAX_IMPORT_BODY:
            self._json(413, {"detail": "request body too large"})
            return
        try:
            body = json.loads(self.rfile.read(n) or b"null")
        except (ValueError, UnicodeDecodeError):
            self._json(422, {"detail": "body is not valid JSON"})
            return
        items = body.get("items") if isinstance(body, dict) else None
        if not isinstance(items, dict):
            self._json(422, {"detail": "body must be {items: {key: value}}"})
            return
        allowed = set(sess.keys)
        items = {k: v for k, v in items.items() if k in allowed}
        try:
            out = get_store().import_items(items, origin, provisional=False)
        except PrefsUnavailable as e:
            self._json(503, {"detail": str(e)[:200]})
            return
        found = len(items)
        sess.result = {"imported": out["imported"], "skipped": out["skipped"], "rejected": out["rejected"], "found": found}
        sess.state = "done"
        sess.finished_at = _now_ms()
        _event("prefs.legacy_import_page", origin=origin, found=found, imported=out["imported"],
               skipped=len(out["skipped"]), rejected=sorted(out["rejected"]))
        self._json(200, {"imported": out["imported"], "skipped": out["skipped"], "rejected": sorted(out["rejected"])})
        threading.Thread(target=_legacy_close, args=(sess, "done"), daemon=True).start()   # single use

    def do_HEAD(self) -> None:  # noqa: N802 - http.server API
        self._json(405, {"detail": "method not allowed"})

    def do_PUT(self) -> None:  # noqa: N802 - http.server API
        self._json(405, {"detail": "method not allowed"})

    do_DELETE = do_PUT
    do_OPTIONS = do_PUT
    do_PATCH = do_PUT


def legacy_import_start(keys: list[str]) -> tuple[int, dict[str, Any]]:
    """Start (or return the running) one-shot import page. (status, body); 409 when the port is taken."""
    global _legacy
    with _legacy_lock:
        cur = _legacy
        if cur is not None and cur.state == "waiting" and _now_ms() < cur.expires_at and cur.servers:
            return 200, cur.public()
        if cur is not None:
            _legacy_close(cur, "expired")
        port = legacy_import_port()
        if _port_answers("127.0.0.1", port) or _port_answers("::1", port, socket.AF_INET6):
            _event("prefs.legacy_import_page", result="port_busy", port=port)
            return 409, {"state": "port_busy", "port": port,
                         "detail": f"something already listens on port {port} (the Next dev UI?): open "
                                   f"http://localhost:{port} in your usual browser; its own sync code imports the settings"}
        sess = _LegacyImportSession(port, keys)
        handler = type("_BoundLegacyHandler", (_LegacyHandler,), {"session": sess})
        try:
            sess.servers.append(_Server4(("127.0.0.1", port), handler))
        except OSError as e:
            _event("prefs.legacy_import_page", result="bind_failed", port=port, error=type(e).__name__)
            return 409, {"state": "port_busy", "port": port, "detail": f"port {port} is not free ({type(e).__name__})"}
        with contextlib.suppress(OSError):                  # [::1] too: some browsers resolve localhost to ::1 first
            sess.servers.append(_Server6(("::1", port), handler))
        for srv in sess.servers:
            threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.25}, daemon=True,
                             name=f"prefs-legacy-import-{port}").start()
        sess.timer = threading.Timer(LEGACY_IMPORT_TTL_S, _legacy_close, args=(sess, "expired"))
        sess.timer.daemon = True
        sess.timer.start()
        _legacy = sess
        _event("prefs.legacy_import_page", result="started", port=port, keys=len(keys), ipv6=len(sess.servers) > 1)
        return 200, sess.public()


def legacy_import_status() -> dict[str, Any]:
    with _legacy_lock:
        sess = _legacy
    if sess is None:
        return {"state": "idle"}
    if sess.state == "waiting" and _now_ms() > sess.expires_at:
        _legacy_close(sess, "expired")
    return sess.public()


@router.post("/legacy-import")
async def legacy_import_begin(request: Request):
    """Start the one-shot import page on the old terminal's port: body {keys: [SYNC keys]} -> {state, url, …}."""
    body = await _read_json(request, 64 * 1024)
    keys = body.get("keys") if isinstance(body, dict) else None
    if not isinstance(keys, list) or not keys:
        fail(422, "invalid", "body must be {keys: [preference keys]}")
    clean = sorted({k for k in keys if isinstance(k, str) and KEY_RE.match(k)})
    if not clean or len(clean) > LEGACY_IMPORT_MAX_KEYS:
        fail(422, "invalid", f"between 1 and {LEGACY_IMPORT_MAX_KEYS} valid keys")
    status, out = await run_in_threadpool(legacy_import_start, clean)
    if status != 200:
        return JSONResponse({**out, "error": error_block("state", out.get("detail", "port busy"))}, status_code=status)
    return out


@router.get("/legacy-import")
def legacy_import_get() -> dict[str, Any]:
    """The import page's state and the imported / skipped key names (never a value)."""
    return legacy_import_status()


@router.post("/legacy-import/stop")
def legacy_import_end() -> dict[str, Any]:
    """Close the import page now."""
    return legacy_import_stop("stopped")

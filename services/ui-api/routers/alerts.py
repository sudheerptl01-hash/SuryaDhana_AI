"""
Alerts (ALRT): the price alerts the terminal always had, plus the typed alert engine (Terminal v2 PLAN 2.3, 43-page
review M41) over any STORED series — IV30 / percentile / rank, IV − RV, 25Δ skew, the ATM straddle, OI at a strike and
the OI wall, futures basis and rollover, F&O ban entry / exit, results within N days, FII / DII net cash, India VIX,
the NIFTY driver, the gold health clauses and a dataset going stale. The rule model, the series catalogue and the
evaluator are pure (``alert_engine.py``); this module stores, reads upstream and serves.

Not a broker order, never a direction: PAPER ONLY, nothing here feeds the Decision Desk, the S1 shadow or a ticket
price, and every template is direction-free (tests/test_alert_engine.py scans them).

Price alerts (unchanged contract; WTCH, the stock window, Telegram /alert):
GET  /api/alerts                levels + recent hits {"alerts": {sym: {above, below, move, yahoo}}, "history": [...]}
PUT  /api/alerts/{sym}          {"above": 2200 | null, "below": 2050 | null, "move": 3 | null, "yahoo": "TCS.NS"}  (all null → delete)
POST /api/alerts/run            price the alerted symbols (fresh quotes) and fire crossings → {"hits": [...], "checked", "priced",
                                 "fires": [...typed fires...], "rules_checked"}; ``?scope=all|live|eod`` picks the typed rules
                                 evaluated (eod = stored series only, no quote reads); ``?dispatch=1`` (the controller) also
                                 returns "dispatch": every fire not yet announced (price + typed, each AT MOST once, ≤ 30 min
                                 old); without dispatch the answer carries "page_notify" (see Delivery below)
GET  /api/alerts/feed           the scheduler's notifications (data/notifications.jsonl), newest first

Typed rules (the engine):
GET  /api/alerts/series         the series kinds: params, unit, badge, cadence, ops, source, definition, example
GET  /api/alerts/rules          every rule with its summary, state and last fire (?symbol=, ?origin=rule|price|all)
POST /api/alerts/rules          create {series, op, value, window, cooldown_min, repeat, channel, note} → the rule (422 + why)
PUT  /api/alerts/rules/{id}     replace a rule's definition (the state resets when the condition changes)
PUT  /api/alerts/rules/{id}/action  {"action": "snooze", "minutes": 60} | resume | pause | delete
DELETE /api/alerts/rules/{id}
PUT  /api/alerts/rules/from-text    {"text": "iv_pctile:NIFTY above 80 repeat"} → {"ok", "rule" | "error"} (Telegram /rule)
GET  /api/alerts/rules/evaluate     dry run: each rule's current value, as-of, metric and whether it holds (no state change)
GET  /api/alerts/fires          the fired inbox, price and typed, newest first, grouped by symbol (?symbol=, ?limit=)

Storage: SQLite <data>/alerts.sqlite (ALERTS_DB overrides; next to ALERTS_PATH in tests): ``alert_rules`` (price levels
are rows with origin 'price', ids ``px:<SYM>:<side>``), ``alert_fires`` (append-only: a fire is never deleted; the
legacy view hides what fell out of its last 50), ``alert_meta``. The first open imports <data>/price_alerts.json
unchanged, and every price-alert change is mirrored back to that file (the notifications feed and a rolled-back
ui-api read it): a JSON written by someone else since our last mirror (an older ui-api after a rollback, a test) is
re-imported, so neither side ever loses a level.

Delivery is AT MOST ONCE, not exactly once: a dispatch=1 run marks the fires it returns as dispatched in the same
transaction, before the controller delivers them, so a controller that times out or dies after that commit loses those
fires (they stay in the fired inbox, never re-sent); a fire nobody claims within 30 min is marked 'expired'. Price hits
found by a run WITHOUT dispatch (WTCH's own check) are left to the controller when it has called within the last 3 min
(``page_notify`` false: the page posts no banner of its own, so the Mac sees one, and Telegram gets it too); when the
controller has not, the run marks them 'page' (``page_notify`` true: the page announces them, a late controller never
repeats them) — one banner either way.

Reads: every series reads STORED data through data-service, except four routes that can start a refresh of their own
when read (/db/fii-dii-cash, /db/events, /db/surveillance, /db/fo/rollover: alert_engine.Need.side_effect). POST /run
(the scheduler's rounds, WTCH) skips those inside the restart freeze windows (07:45–09:20 and 18:30–21:15 IST): their
rules read "no value" there (never a fire, never a baseline move) and are evaluated at the next round outside.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field

for _p in (Path(__file__).resolve().parents[3], Path(__file__).resolve().parents[1]):
    if (_p / "shared").is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
    if (_p / "alert_engine.py").is_file() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import alert_engine as engine  # noqa: E402
from cache import TTLCache  # noqa: E402

router = APIRouter()
_lock = threading.RLock()            # reentrant: routers/notifications.py holds it around _read()
HISTORY_MAX = 50
MAX_RULES = 200
DISPATCH_MAX_AGE = timedelta(minutes=30)
DISPATCHER_LIVE = timedelta(minutes=3)      # the controller asks every minute in session; 3 min absorbs one missed round
#: CLAUDE.md "Restart freeze windows (IST)": no read that can start a data-service refresh is made from POST /run inside them
FREEZE_WINDOWS: tuple[tuple[tuple[int, int], tuple[int, int]], ...] = (((7, 45), (9, 20)), ((18, 30), (21, 15)))
_SYM = re.compile(r"^[A-Za-z0-9&^.=_-]{1,30}$")
IST = timezone(timedelta(hours=5, minutes=30))
DATA_SVC = os.environ.get("DATA_SERVICE_URL", "http://localhost:8001").rstrip("/")
_READS = TTLCache("alerts.reads", max_items=256, default_ttl=300.0)
_SCHEMA_READY: set[str] = set()


def _now() -> datetime:
    """The clock the engine evaluates against (tests pin it)."""
    return datetime.now(IST)


def _path() -> Path:
    env = os.environ.get("ALERTS_PATH", "").strip()
    if env:
        return Path(env)
    for root in (Path(__file__).resolve().parents[3] / "data", Path("/app/data")):
        if root.is_dir():
            return root / "price_alerts.json"
    return Path("price_alerts.json")


def _db_path() -> Path:
    env = os.environ.get("ALERTS_DB", "").strip()
    return Path(env) if env else _path().with_name("alerts.sqlite")


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# storage
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
SCHEMA = """
CREATE TABLE IF NOT EXISTS alert_rules (
  id TEXT PRIMARY KEY, series TEXT NOT NULL, kind TEXT NOT NULL, symbol TEXT, params TEXT NOT NULL DEFAULT '{}',
  op TEXT NOT NULL, value REAL, win INTEGER, cooldown_min INTEGER NOT NULL DEFAULT 0, repeat TEXT NOT NULL DEFAULT 'once',
  channel TEXT NOT NULL DEFAULT 'both', note TEXT, status TEXT NOT NULL DEFAULT 'active', snooze_until TEXT,
  origin TEXT NOT NULL DEFAULT 'rule', created_at TEXT NOT NULL, updated_at TEXT NOT NULL, state TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS alert_fires (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, rule_id TEXT, origin TEXT NOT NULL, series TEXT, kind TEXT, symbol TEXT,
  fired_at TEXT NOT NULL, as_of TEXT, text TEXT NOT NULL, channel TEXT NOT NULL DEFAULT 'both', payload TEXT NOT NULL,
  hit_key TEXT, hidden INTEGER NOT NULL DEFAULT 0, dispatched_at TEXT);
CREATE INDEX IF NOT EXISTS alert_fires_symbol ON alert_fires (symbol, seq);
CREATE INDEX IF NOT EXISTS alert_fires_pending ON alert_fires (dispatched_at, seq);
CREATE TABLE IF NOT EXISTS alert_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def _connect() -> sqlite3.Connection:
    p = _db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=5.0, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    key = str(p.resolve())
    if key not in _SCHEMA_READY or not p.exists():
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        _SCHEMA_READY.add(key)
    return conn


class _Tx:
    """``with _Tx() as c:`` — one connection, one IMMEDIATE transaction, the JSON mirror synced first."""

    def __init__(self, sync: bool = True) -> None:
        self.sync = sync

    def __enter__(self) -> sqlite3.Connection:
        _lock.acquire()
        try:
            self.c = _connect()
            self.c.execute("BEGIN IMMEDIATE")
            if self.sync:
                _sync_from_json(self.c)
        except BaseException:
            _lock.release()
            raise
        return self.c

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        try:
            self.c.execute("ROLLBACK" if exc_type else "COMMIT")
        finally:
            self.c.close()
            _lock.release()


def _meta(c: sqlite3.Connection, key: str) -> str | None:
    r = c.execute("SELECT value FROM alert_meta WHERE key = ?", (key,)).fetchone()
    return r["value"] if r else None


def _set_meta(c: sqlite3.Connection, key: str, value: str) -> None:
    c.execute("INSERT INTO alert_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


# ── the legacy price alerts (origin 'price') ────────────────────────────────────────────────────────────────
_SIDE_OP = {"above": "above", "below": "below", "move": "change_pct"}
_OP_SIDE = {v: k for k, v in _SIDE_OP.items()}


def hit_key(h: dict[str, Any]) -> str:
    return f"{h.get('at')}|{h.get('sym')}|{h.get('side')}|{h.get('level')}"


def legacy_hit_text(h: dict[str, Any]) -> str:
    """The banner text master_controller.price_alerts_check formats for a hit (byte-identical: the dispatch list and
    the controller's own loop must announce the same words; tests/test_alert_rules.py pins both)."""
    if h.get("side") == "move":
        return f"{h['sym']} {h['change_pct']:+.1f}% today (alert at ±{h['level']:g}%, now ₹{h['price']:,.2f})"
    return f"{h['sym']} {'rose above' if h.get('side') == 'above' else 'fell below'} ₹{h['level']:,.2f} (now ₹{h['price']:,.2f})"


def _legacy_from_db(c: sqlite3.Connection) -> dict[str, Any]:
    alerts: dict[str, dict[str, Any]] = {}
    for r in c.execute("SELECT symbol, op, value, params FROM alert_rules WHERE origin = 'price' AND status = 'active' ORDER BY symbol, op"):
        side = _OP_SIDE.get(r["op"])
        if side is None or r["value"] is None:
            continue
        lv = alerts.setdefault(r["symbol"], {})
        lv[side] = r["value"]
        yahoo = json.loads(r["params"] or "{}").get("yahoo")
        if yahoo:
            lv["yahoo"] = yahoo
    history = [json.loads(r["payload"]) for r in c.execute(
        "SELECT payload FROM alert_fires WHERE origin = 'price' AND hidden = 0 ORDER BY seq DESC LIMIT ?", (HISTORY_MAX,))]
    return {"alerts": alerts, "history": history}


def _apply_legacy(c: sqlite3.Connection, d: dict[str, Any], now: datetime, dispatched: str | None = None) -> None:
    """Make the DB's price levels and visible price history equal ``d`` (the legacy dict). Fires are never deleted."""
    stamp = _iso(now)
    want: dict[str, tuple[str, str, float, str | None]] = {}
    for sym, lv in (d.get("alerts") or {}).items():
        if not isinstance(lv, dict):
            continue
        for side, op in _SIDE_OP.items():
            v = lv.get(side)
            if v is not None:
                want[f"px:{sym}:{side}"] = (str(sym), op, float(v), lv.get("yahoo"))
    have = {r["id"]: r for r in c.execute("SELECT id, op, value, params FROM alert_rules WHERE origin = 'price'")}
    for rid in set(have) - set(want):
        c.execute("DELETE FROM alert_rules WHERE id = ?", (rid,))
    for rid, (sym, op, v, yahoo) in want.items():
        params = json.dumps({"symbol": sym, **({"yahoo": yahoo} if yahoo else {})}, sort_keys=True)
        old = have.get(rid)
        if old is not None and old["value"] == v and old["params"] == params:
            continue
        c.execute("""INSERT INTO alert_rules (id, series, kind, symbol, params, op, value, win, cooldown_min, repeat, channel, note,
                     status, snooze_until, origin, created_at, updated_at, state)
                     VALUES (?, ?, 'price', ?, ?, ?, ?, NULL, 0, 'once', 'both', NULL, 'active', NULL, 'price', ?, ?, '{}')
                     ON CONFLICT(id) DO UPDATE SET value = excluded.value, params = excluded.params, updated_at = excluded.updated_at,
                     status = 'active'""", (rid, f"price:{sym}", sym, params, op, v, stamp, stamp))
    hist = [h for h in (d.get("history") or []) if isinstance(h, dict)][:HISTORY_MAX]
    keys = [hit_key(h) for h in hist]
    visible = [(r["seq"], r["hit_key"], r["dispatched_at"]) for r in c.execute(
        "SELECT seq, hit_key, dispatched_at FROM alert_fires WHERE origin = 'price' AND hidden = 0 ORDER BY seq DESC")]
    vis_keys = [k for _, k, _ in visible]
    keyset = set(keys)
    kept = [k for k in vis_keys if k in keyset]
    new = [k for k in keys if k not in set(vis_keys)]
    incremental = keys[: len(new)] == new and keys[len(new):] == kept
    carried: dict[str, str | None] = {}
    if incremental:
        for seq, k, _ in visible:
            if k not in keyset:
                c.execute("UPDATE alert_fires SET hidden = 1 WHERE seq = ?", (seq,))
        todo = hist[: len(new)]
    else:                                         # an external rewrite reordered the history: rebuild the visible list
        carried = {k: disp for _, k, disp in visible}
        c.execute("UPDATE alert_fires SET hidden = 1 WHERE origin = 'price' AND hidden = 0")
        todo = hist
    for h in reversed(todo):                      # oldest first, so the newest gets the highest seq
        k = hit_key(h)
        disp = dispatched if incremental else carried.get(k, dispatched or "imported")
        c.execute("""INSERT INTO alert_fires (rule_id, origin, series, kind, symbol, fired_at, as_of, text, channel, payload, hit_key, dispatched_at)
                     VALUES (?, 'price', ?, 'price', ?, ?, ?, ?, 'both', ?, ?, ?)""",
                  (f"px:{h.get('sym')}:{h.get('side')}", f"price:{h.get('sym')}", h.get("sym"), stamp, h.get("at"),
                   _safe_text(h), json.dumps(h, sort_keys=True), k, disp))


def _safe_text(h: dict[str, Any]) -> str:
    try:
        return legacy_hit_text(h)
    except (KeyError, TypeError, ValueError):
        return f"{h.get('sym')} {h.get('side')} {h.get('level')}"


def _mirror_json(c: sqlite3.Connection) -> None:
    """Write <data>/price_alerts.json from the DB (atomic) and remember its hash."""
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(_legacy_from_db(c), indent=1, sort_keys=True).encode("utf-8")
    tmp = p.with_suffix(".tmp")
    tmp.write_bytes(body)
    tmp.replace(p)
    _set_meta(c, "json_sha", hashlib.sha256(body).hexdigest())


def _sync_from_json(c: sqlite3.Connection) -> None:
    """Import price_alerts.json when it changed since our last mirror (the first open is the migration)."""
    p = _path()
    try:
        raw = p.read_bytes()
    except OSError:
        if _meta(c, "json_sha") is not None:      # the file went away: put it back from the DB
            _mirror_json(c)
        return
    sha = hashlib.sha256(raw).hexdigest()
    if sha == _meta(c, "json_sha"):
        return
    try:
        d = json.loads(raw.decode("utf-8")) if raw.strip() else {}
    except (UnicodeDecodeError, ValueError):
        d = None
    if isinstance(d, dict):
        _apply_legacy(c, {"alerts": d.get("alerts", {}), "history": d.get("history", [])}, _now(), dispatched="imported")
        if _meta(c, "migrated_at") is None:
            _set_meta(c, "migrated_at", _iso(_now()))
    _set_meta(c, "json_sha", sha)


def _read() -> dict[str, Any]:
    """The price alerts as the legacy dict ({"alerts", "history"}): what GET /api/alerts and the notifications feed read."""
    with _Tx() as c:
        return _legacy_from_db(c)


def _write(d: dict[str, Any], dispatched: str | None = None) -> None:
    """Store a legacy dict as the price alerts (and mirror price_alerts.json). ``dispatched`` stamps the new hits (e.g.
    'page': the page that ran the check announces them; the dispatch queue skips them)."""
    with _Tx() as c:
        _apply_legacy(c, d, _now(), dispatched=dispatched)
        _mirror_json(c)


LEVEL_KEYS = ("above", "below", "move")


def check_levels(alerts: dict[str, dict[str, Any]], prices: dict[str, Optional[float]], now: Optional[str] = None,
                 changes: Optional[dict[str, Optional[float]]] = None) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Pure: crossed levels → hits; crossed sides are removed, symbols with no level left are dropped. `move` fires
    when today's change (vs NSE's official previous close, from `changes`) reaches ±move %."""
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    left: dict[str, dict[str, Any]] = {}
    hits: list[dict[str, Any]] = []
    for sym, lv in alerts.items():
        lv = dict(lv)
        p = prices.get(sym)
        if p is not None and p == p:
            if lv.get("above") is not None and p >= lv["above"]:
                hits.append({"sym": sym, "side": "above", "level": lv["above"], "price": p, "at": now})
                lv.pop("above")
            if lv.get("below") is not None and p <= lv["below"]:
                hits.append({"sym": sym, "side": "below", "level": lv["below"], "price": p, "at": now})
                lv.pop("below")
            ch = (changes or {}).get(sym)
            if lv.get("move") is not None and ch is not None and abs(ch) >= lv["move"]:
                hits.append({"sym": sym, "side": "move", "level": lv["move"], "price": p, "change_pct": round(ch, 2), "at": now})
                lv.pop("move")
        if any(lv.get(k) is not None for k in LEVEL_KEYS):
            left[sym] = lv
    return left, hits


class Levels(BaseModel):
    above: Optional[float] = Field(None, gt=0)
    below: Optional[float] = Field(None, gt=0)
    move: Optional[float] = Field(None, gt=0, le=50)        # ± % day move vs the official previous close
    yahoo: Optional[str] = Field(None, max_length=30)


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# typed rules: storage helpers
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
def _rule_from_row(r: sqlite3.Row) -> dict[str, Any]:
    rule = {"id": r["id"], "series": r["series"], "kind": r["kind"], "symbol": r["symbol"], "params": json.loads(r["params"] or "{}"),
            "op": r["op"], "value": r["value"], "window": r["win"], "cooldown_min": r["cooldown_min"], "repeat": r["repeat"],
            "channel": r["channel"], "note": r["note"], "status": r["status"], "snooze_until": r["snooze_until"], "origin": r["origin"],
            "created_at": r["created_at"], "updated_at": r["updated_at"], "state": json.loads(r["state"] or "{}")}
    return rule


def _decorate(rule: dict[str, Any]) -> dict[str, Any]:
    """Add the display fields: summary, label, condition, unit, badge, cadence, source (all direction-free)."""
    kind = engine.KINDS.get(rule["kind"])
    if kind is None:
        return rule
    params = {k: v for k, v in (rule.get("params") or {}).items() if k != "yahoo"}
    if rule.get("origin") == "price":
        params = {"symbol": rule["symbol"]}
        rule = {**rule, "repeat": "once", "channel": "both"}
    try:
        summary = engine.rule_summary({**rule, "params": params})
        label = engine.label_for(rule["kind"], params)
        cond = engine.condition_text({**rule, "params": params})
    except (KeyError, ValueError):
        summary, label, cond = rule["series"], rule["series"], rule["op"]
    return {**rule, "summary": summary, "label": label, "condition": cond, "unit": engine.unit_for(rule["kind"], params),
            "badge": kind.badge, "cadence": kind.cadence, "source": kind.source}


def _insert_rule(c: sqlite3.Connection, rid: str, body: dict[str, Any], now: datetime, state: dict[str, Any] | None = None,
                 created_at: str | None = None, status: str = "active", snooze_until: str | None = None) -> None:
    c.execute("""INSERT INTO alert_rules (id, series, kind, symbol, params, op, value, win, cooldown_min, repeat, channel, note, status,
                 snooze_until, origin, created_at, updated_at, state) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'rule', ?, ?, ?)
                 ON CONFLICT(id) DO UPDATE SET series = excluded.series, kind = excluded.kind, symbol = excluded.symbol,
                 params = excluded.params, op = excluded.op, value = excluded.value, win = excluded.win,
                 cooldown_min = excluded.cooldown_min, repeat = excluded.repeat, channel = excluded.channel, note = excluded.note,
                 status = excluded.status, snooze_until = excluded.snooze_until, updated_at = excluded.updated_at, state = excluded.state""",
              (rid, body["series"], body["kind"], body["symbol"], json.dumps(body["params"], sort_keys=True), body["op"], body["value"],
               body["window"], body["cooldown_min"], body["repeat"], body["channel"], body["note"], status, snooze_until,
               created_at or _iso(now), _iso(now), json.dumps(state or {}, sort_keys=True)))


def _get_rule(c: sqlite3.Connection, rid: str) -> dict[str, Any] | None:
    r = c.execute("SELECT * FROM alert_rules WHERE id = ?", (rid,)).fetchone()
    return _rule_from_row(r) if r else None


def _create_rule(raw: dict[str, Any], rid: str | None = None) -> dict[str, Any]:
    body = engine.validate_rule(raw)
    now = _now()
    with _Tx() as c:
        n = c.execute("SELECT COUNT(*) FROM alert_rules WHERE origin = 'rule'").fetchone()[0]
        old = _get_rule(c, rid) if rid else None
        if old is not None and old["origin"] != "rule":
            raise engine.RuleError("that id is a price alert: change it with PUT /api/alerts/{sym}")
        if old is None and n >= MAX_RULES:
            raise engine.RuleError(f"at most {MAX_RULES} rules: delete one first")
        rid = rid or f"r-{secrets.token_hex(5)}"
        same = old is not None and all(old.get(k) == body.get(k) for k in ("series", "op", "value", "window"))
        keep = old if (old is not None and same) else None
        _insert_rule(c, rid, body, now, state=keep["state"] if keep else {}, created_at=old["created_at"] if old else None,
                     status=(keep["status"] if keep and keep["status"] != "fired" else "active"),
                     snooze_until=keep["snooze_until"] if keep else None)
        return _decorate(_get_rule(c, rid) or {})


def _rule_or_404(c: sqlite3.Connection, rid: str) -> dict[str, Any]:
    rule = _get_rule(c, rid)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"no rule {rid}")
    return rule


def _apply_action(rid: str, action: str, minutes: float | None) -> dict[str, Any]:
    now = _now()
    with _Tx() as c:
        rule = _rule_or_404(c, rid)
        if rule["origin"] == "price":
            raise HTTPException(status_code=409, detail="a price alert: change it with PUT /api/alerts/{sym}")
        state = dict(rule["state"])
        if action == "delete":
            c.execute("DELETE FROM alert_rules WHERE id = ?", (rid,))
            return {"deleted": rid}
        if action == "snooze":
            m = minutes if minutes is not None else 60.0
            if not 1 <= m <= engine.MAX_COOLDOWN_MIN:
                raise HTTPException(status_code=422, detail=f"snooze minutes 1–{engine.MAX_COOLDOWN_MIN}")
            status, until = "snoozed", _iso(now + timedelta(minutes=m))
        elif action == "resume":
            status, until = "active", None
            state["armed"] = True                  # a resumed one-shot / level rule is armed again
        elif action == "pause":
            status, until = "paused", None
        else:
            raise HTTPException(status_code=422, detail="action must be snooze, resume, pause or delete")
        c.execute("UPDATE alert_rules SET status = ?, snooze_until = ?, state = ?, updated_at = ? WHERE id = ?",
                  (status, until, json.dumps(state, sort_keys=True), _iso(now), rid))
        return _decorate(_rule_or_404(c, rid))


def _fire_row(r: sqlite3.Row) -> dict[str, Any]:
    p = json.loads(r["payload"] or "{}")
    if r["origin"] == "price":
        side = p.get("side")
        return {"seq": r["seq"], "origin": "price", "rule_id": r["rule_id"], "series": r["series"], "kind": "price", "symbol": r["symbol"],
                "at": p.get("at") or r["fired_at"], "as_of": p.get("at"), "text": r["text"], "channel": r["channel"], "badge": engine.BADGE_ARITH,
                "op": _SIDE_OP.get(side or "", side), "observed": p.get("price"), "threshold": p.get("level"), "label": f"{r['symbol']} price",
                "source": "live NSE quote", "dispatched": r["dispatched_at"] is not None}
    return {**p, "seq": r["seq"], "origin": "rule", "dispatched": r["dispatched_at"] is not None}


def _dispatcher_live(c: sqlite3.Connection, now: datetime) -> bool:
    """The controller called POST /run?dispatch=1 within DISPATCHER_LIVE: it will deliver what a page's run finds."""
    last = engine._parse_ts(_meta(c, "dispatch_last_call"))
    return last is not None and timedelta(0) <= now - last <= DISPATCHER_LIVE


def _claim(c: sqlite3.Connection, now: datetime, started: datetime | None = None) -> list[dict[str, Any]]:
    """Every fire not announced yet (price + typed), each AT MOST once, oldest first: they are marked dispatched here,
    before the controller delivers them (a controller that dies after this commit loses them; module docstring). The
    first dispatcher call starts the queue at the start of its own run: what fired before the controller ever asked is
    not replayed, what this run fired is sent. A fire older than 30 min is marked expired instead of arriving late."""
    _set_meta(c, "dispatch_last_call", _iso(now))
    if _meta(c, "dispatch_since") is None:
        since = _iso(started or now)
        _set_meta(c, "dispatch_since", since)
        c.execute("UPDATE alert_fires SET dispatched_at = 'predates-dispatcher' WHERE dispatched_at IS NULL AND fired_at < ?", (since,))
    out: list[dict[str, Any]] = []
    oldest = _iso(now - DISPATCH_MAX_AGE)
    stamp = _iso(now)
    for r in c.execute("SELECT * FROM alert_fires WHERE dispatched_at IS NULL ORDER BY seq").fetchall():
        if r["fired_at"] < oldest:
            c.execute("UPDATE alert_fires SET dispatched_at = 'expired' WHERE seq = ?", (r["seq"],))
            continue
        c.execute("UPDATE alert_fires SET dispatched_at = ? WHERE seq = ?", (stamp, r["seq"]))
        if r["origin"] == "price":
            out.append({"seq": r["seq"], "origin": "price", "kind": "price", "title": "SuryaDhana price alert", "telegram_title": "Price alert",
                        "text": r["text"], "channel": "both", "symbol": r["symbol"], "at": r["fired_at"], "badge": engine.BADGE_ARITH})
        else:
            p = json.loads(r["payload"] or "{}")
            out.append({"seq": r["seq"], "origin": "rule", "kind": "rule", "title": "SuryaDhana alert", "telegram_title": "Alert",
                        "text": r["text"], "channel": r["channel"], "symbol": r["symbol"], "at": r["fired_at"], "badge": p.get("badge"),
                        "rule_id": r["rule_id"]})
    return out


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# typed rules: upstream reads + evaluation
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
async def _fetch_ds(path: str, params: dict[str, str]) -> Any:
    """One data-service GET through the process-wide client. Most routes serve stored tables only; the four flagged
    ``Need.side_effect`` (fii-dii-cash, events, surveillance, rollover) can start a refresh of their own when read, so
    POST /run skips them inside the freeze windows (``_freeze_window``)."""
    from shared.http_client import get_json
    return await get_json(f"{DATA_SVC}{path}", route="read", params=params or None, timeout=20.0)


async def _fetch_local(name: str) -> Any:
    """An in-process ui-api view (no HTTP to ourselves)."""
    if name == "data_health":
        from routers import data_health
        return await data_health.data_health(response=Response(), page=None)
    raise ValueError(f"no local view {name}")


def _freeze_window(now: datetime) -> str | None:
    """'18:30–21:15' when ``now`` (IST) is inside a restart freeze window, else None."""
    t = now.astimezone(IST)
    hm = (t.hour, t.minute)
    for a, b in FREEZE_WINDOWS:
        if a <= hm < b:
            return f"{a[0]:02d}:{a[1]:02d}–{b[0]:02d}:{b[1]:02d}"
    return None


async def _read_need(n: engine.Need) -> Any:
    key = f"{n.source}|{n.path}|{n.params}"
    hit = _READS.get(key)
    if hit is not None:
        return hit
    try:
        body = await (_fetch_ds(n.path, dict(n.params)) if n.source == "ds" else _fetch_local(n.path))
    except Exception as exc:  # noqa: BLE001 - one dead upstream: that series reads 'unavailable', never the run
        _READS.set(key, exc, ttl=30.0)
        return exc
    _READS.set(key, body, ttl=n.ttl_s)
    return body


async def _quotes(tickers: list[str], fresh: bool) -> dict[str, Any]:
    """Live-hub quotes for NSE stocks / indices (routers.news_scanner.get_quotes; '.NS' and the NSE index tickers never
    reach Yahoo). Batches of 60, the route's cap."""
    from routers.news_scanner import get_quotes
    out: dict[str, Any] = {}
    ts = sorted(set(t for t in tickers if t))
    for i in range(0, len(ts), 60):
        out.update((await get_quotes(symbols=",".join(ts[i:i + 60]), fresh=fresh))["quotes"])
    return out


def _scoped(rule: dict[str, Any], scope: str) -> bool:
    k = engine.KINDS.get(rule["kind"])
    if k is None:
        return False
    if scope == "live":
        return k.cadence == "live"
    if scope == "eod":
        return k.cadence != "live" or rule["kind"] == "vix"
    return True


async def _observe(rules: list[dict[str, Any]], live: bool, quotes: dict[str, Any] | None = None,
                   fresh: bool = True, gate: bool = False) -> dict[str, engine.Observation]:
    """Each rule's observation (shared reads fetched once). ``gate``: skip the reads that can start a data-service
    refresh inside a freeze window (the scheduler's rounds; the dry run, a page read like any other, is not gated)."""
    today = _now().date()
    window = _freeze_window(_now()) if gate else None
    per: dict[str, list[engine.Need]] = {}
    for r in rules:
        try:
            per[r["id"]] = engine.needs(r["kind"], r["params"], today, live)
        except engine.RuleError:
            per[r["id"]] = []
    all_needs = {n for ns in per.values() for n in ns}
    q_needed = [n.path for n in all_needs if n.source == "quote"]
    q = dict(quotes or {})
    missing = [t for t in q_needed if t not in q]
    if missing:
        try:
            q.update(await _quotes(missing, fresh))
        except Exception as exc:  # noqa: BLE001 - quotes down: the live series read unavailable
            q.update({t: exc for t in missing})
    other = [n for n in all_needs if n.source != "quote"]
    skipped = {n: engine.ReadSkipped(f"skipped inside the {window} IST freeze window (this data-service read can start a refresh); "
                                     "read at the next round outside it") for n in other if window and n.side_effect}
    other = [n for n in other if n not in skipped]
    bodies = await asyncio.gather(*(_read_need(n) for n in other))
    got: dict[engine.Need, Any] = {**dict(zip(other, bodies, strict=True)), **skipped}
    for n in all_needs:
        if n.source == "quote":
            got[n] = q.get(n.path)
    out: dict[str, engine.Observation] = {}
    for r in rules:
        try:
            out[r["id"]] = engine.extract(r["kind"], r["params"], got, today, live)
        except Exception as exc:  # noqa: BLE001 - a malformed payload: unavailable, with why
            out[r["id"]] = engine.Observation(None, None, engine.KINDS[r["kind"]].source, note=f"could not read: {type(exc).__name__}")
    return out


def _load_rules(scope: str = "all", ids: list[str] | None = None) -> list[dict[str, Any]]:
    with _Tx() as c:
        rows = [_rule_from_row(r) for r in c.execute("SELECT * FROM alert_rules WHERE origin = 'rule' ORDER BY created_at")]
    rows = [r for r in rows if (ids is None or r["id"] in ids) and _scoped(r, scope)]
    return rows


def _store_evaluations(rules: list[dict[str, Any]], obs: dict[str, engine.Observation], now: datetime) -> list[dict[str, Any]]:
    """Re-read each rule (a concurrent edit wins), evaluate, persist state + fires in one transaction."""
    fires: list[dict[str, Any]] = []
    with _Tx(sync=False) as c:
        for loaded in rules:
            rule = _get_rule(c, loaded["id"])
            if rule is None or rule["updated_at"] != loaded["updated_at"] or rule["id"] not in obs:
                continue
            ev = engine.evaluate(rule, obs[rule["id"]], now)
            c.execute("UPDATE alert_rules SET state = ?, status = ?, snooze_until = ? WHERE id = ?",
                      (json.dumps(ev.state, sort_keys=True, default=str), ev.status, ev.snooze_until, rule["id"]))
            if ev.fire:
                f = ev.fire
                c.execute("""INSERT INTO alert_fires (rule_id, origin, series, kind, symbol, fired_at, as_of, text, channel, payload)
                             VALUES (?, 'rule', ?, ?, ?, ?, ?, ?, ?, ?)""",
                          (rule["id"], f["series"], f["kind"], f["symbol"], _iso(now), f.get("as_of"), f["text"], f["channel"],
                           json.dumps(f, sort_keys=True, default=str)))
                fires.append(f)
    return fires


async def evaluate_rules(scope: str = "all", quotes: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], int]:
    """Evaluate every active / snoozed typed rule in ``scope`` → (new fires, rules checked)."""
    rules = await asyncio.to_thread(_load_rules, scope)
    rules = [r for r in rules if r["status"] in ("active", "snoozed")]
    if not rules:
        return [], 0
    obs = await _observe(rules, live=scope != "eod", quotes=quotes, gate=True)
    fires = await asyncio.to_thread(_store_evaluations, rules, obs, _now())
    return fires, len(rules)


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# routes — price alerts (the legacy contract)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
@router.get("")
def list_alerts() -> dict[str, Any]:
    with _lock:
        return _read()


# ── routes — typed rules (registered before PUT /{sym} so 'rules' is never read as a symbol) ────────────────
class RuleBody(BaseModel):
    series: str = Field(..., max_length=120)
    op: str = Field(..., max_length=20)
    value: Optional[float] = None
    window: Optional[int] = None
    cooldown_min: Optional[int] = None
    repeat: str = Field("once", max_length=10)
    channel: str = Field("both", max_length=10)
    note: Optional[str] = Field(None, max_length=400)


class ActionBody(BaseModel):
    action: str = Field(..., max_length=10)
    minutes: Optional[float] = None


class TextBody(BaseModel):
    text: str = Field(..., max_length=400)


@router.get("/series")
def list_series() -> dict[str, Any]:
    """The series kinds the engine can watch (for the ALRT builder, the other pages' create-alert buttons, Telegram /series)."""
    return {"kinds": engine.catalog(), "ops": list(engine.OPS), "op_words": engine.OP_WORDS, "channels": list(engine.CHANNELS),
            "repeats": list(engine.REPEATS), "pctile_window": engine.PCTILE_WINDOW, "max_rules": MAX_RULES,
            "note": "alerts describe a level, never a direction; nothing here feeds the Decision Desk, the S1 shadow or a ticket price"}


@router.get("/rules")
def list_rules(symbol: Optional[str] = Query(None, max_length=30), origin: str = Query("all", pattern="^(all|rule|price)$")) -> dict[str, Any]:
    with _Tx() as c:
        rows = [_rule_from_row(r) for r in c.execute("SELECT * FROM alert_rules ORDER BY origin DESC, created_at")]
        last = {r["rule_id"]: r["fired_at"] for r in c.execute("SELECT rule_id, MAX(fired_at) AS fired_at FROM alert_fires GROUP BY rule_id")}
    if origin != "all":
        rows = [r for r in rows if r["origin"] == origin]
    if symbol:
        rows = [r for r in rows if (r["symbol"] or "").upper() == symbol.upper()]
    out = [{**_decorate(r), "last_fired_at": last.get(r["id"])} for r in rows]
    return {"rules": out, "count": len(out), "as_of": _iso(_now())}


@router.post("/rules")
def create_rule(body: RuleBody) -> dict[str, Any]:
    try:
        return _create_rule(body.model_dump())
    except engine.RuleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/rules/from-text")
def create_rule_from_text(body: TextBody) -> dict[str, Any]:
    """Telegram /rule and GO: one line → a stored rule. Always 200 with ok / error (the bot shows the error)."""
    try:
        return {"ok": True, "rule": _create_rule(engine.parse_rule_text(body.text))}
    except engine.RuleError as exc:
        return {"ok": False, "error": str(exc)}


@router.get("/rules/evaluate")
async def dry_run(ids: Optional[str] = Query(None, max_length=2000)) -> dict[str, Any]:
    """Each typed rule's current reading — value, as-of, the compared metric, whether the condition holds — WITHOUT
    changing any state (the ALRT 'now' column; a GET-able probe for the controller and the owner)."""
    want = [s for s in (ids or "").split(",") if s] or None
    rules = await asyncio.to_thread(_load_rules, "all", want)
    obs = await _observe(rules, live=True, fresh=False) if rules else {}
    rows = []
    for r in rules:
        o = obs.get(r["id"]) or engine.Observation(None)
        metric, why = engine.measure(r, o)
        sat = engine.condition(r, metric, o.value, (r.get("state") or {}).get("last_value"))
        rows.append({"id": r["id"], "value": o.value, "as_of": o.as_of, "source": o.source, "metric": metric, "satisfied": sat,
                     "reason": why or o.note, "unit": engine.unit_for(r["kind"], r["params"]), "badge": engine.KINDS[r["kind"]].badge,
                     "history_n": len(o.history)})
    return {"rows": rows, "as_of": _iso(_now()), "note": "a dry run: nothing fired, no state changed"}


@router.put("/rules/{rule_id}/action")
def rule_action(rule_id: str, body: ActionBody) -> dict[str, Any]:
    return _apply_action(rule_id, body.action.lower(), body.minutes)


@router.put("/rules/{rule_id}")
def replace_rule(rule_id: str, body: RuleBody) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", rule_id):
        raise HTTPException(status_code=400, detail="bad rule id")
    try:
        return _create_rule(body.model_dump(), rid=rule_id)
    except engine.RuleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: str) -> dict[str, Any]:
    return _apply_action(rule_id, "delete", None)


@router.get("/fires")
def list_fires(symbol: Optional[str] = Query(None, max_length=30), limit: int = Query(100, ge=1, le=1000),
               origin: str = Query("all", pattern="^(all|rule|price)$")) -> dict[str, Any]:
    """The fired inbox (price + typed), newest first, and the same fires grouped by symbol."""
    sql, args = "SELECT * FROM alert_fires WHERE hidden = 0", list[Any]()
    if origin != "all":
        sql += " AND origin = ?"
        args.append(origin)
    if symbol:
        sql += " AND symbol = ?"
        args.append(symbol.upper())
    sql += " ORDER BY seq DESC LIMIT ?"
    args.append(limit)
    with _Tx() as c:
        fires = [_fire_row(r) for r in c.execute(sql, args)]
    return {"fires": fires, "groups": engine.group_fires(fires), "count": len(fires), "as_of": _iso(_now())}


# ── PUT /{sym}: the legacy price-alert setter (after the specific routes) ──────────────────────────────────
@router.put("/{sym}")
def set_alert(sym: str, body: Levels) -> dict[str, Any]:
    if not _SYM.match(sym) or (body.yahoo and not _SYM.match(body.yahoo)):
        raise HTTPException(status_code=400, detail="bad symbol")
    with _lock:
        d = _read()
        if "move" not in body.model_fields_set:      # older callers (WTCH 🔔) send only above/below: keep a move level
            body.move = d["alerts"].get(sym, {}).get("move")
        if body.above is None and body.below is None and body.move is None:
            d["alerts"].pop(sym, None)
        else:
            d["alerts"][sym] = {k: v for k, v in (("above", body.above), ("below", body.below), ("move", body.move),
                                                  ("yahoo", body.yahoo or d["alerts"].get(sym, {}).get("yahoo") or f"{sym}.NS"))
                                if v is not None}
        _write(d)
        return _read()


def _dispatcher_live_now() -> bool:
    with _Tx(sync=False) as c:
        return _dispatcher_live(c, _now())


def _apply_hits(prices: dict[str, Optional[float]], changes: dict[str, Optional[float]], page: bool) -> list[dict[str, Any]]:
    """Re-read the levels (they may have changed while we priced), fire the crossings, store them. ``page``: the page
    that asked announces these hits itself (no live dispatcher), so the queue marks them 'page'. Blocking: runs in a
    worker thread (the event loop never waits on SQLite or the JSON mirror)."""
    with _lock:
        d = _read()
        left, hits = check_levels(d["alerts"], prices, changes=changes)
        if hits:
            d["alerts"] = left
            d["history"] = (hits + d["history"])[:HISTORY_MAX]
            _write(d, dispatched="page" if page else None)
    return hits


@router.post("/run")
async def run_alerts(scope: str = "all", dispatch: bool = False) -> dict[str, Any]:
    """Price every alerted symbol and fire the crossings (called every minute in market hours by the scheduler), then
    evaluate the typed rules in ``scope``.

    Prices with FRESH quotes only (each under news_scanner.QUOTE_REFRESH_AFTER_S, 30 s, old): the quote cache's
    stale-while-revalidate answer is for display, and at the scheduler's 60 s cadence it would always be the
    previous minute's quote (round 3 review, major). ``scope=eod`` (out of session) reads no quotes at all.

    Without ``dispatch`` (WTCH's own check) the answer says ``page_notify``: true when no controller has asked in the
    last 3 min, so the page announces the hits itself (and the queue never repeats them); false when the controller
    will deliver them (Mac + Telegram), so the page posts no banner of its own."""
    from routers.news_scanner import get_quotes
    started = _now()
    if scope not in ("all", "live", "eod"):
        raise HTTPException(status_code=422, detail="scope must be all, live or eod")
    alerts = (await asyncio.to_thread(_read))["alerts"] if scope != "eod" else {}
    page = not dispatch and not await asyncio.to_thread(_dispatcher_live_now)
    out: dict[str, Any] = {"hits": [], "checked": len(alerts), "priced": 0}
    quotes: dict[str, Any] = {}
    if alerts:
        yahoo = {sym: lv.get("yahoo") or f"{sym}.NS" for sym, lv in alerts.items()}
        ys = sorted(set(yahoo.values()))
        for i in range(0, len(ys), 60):
            quotes.update((await get_quotes(symbols=",".join(ys[i:i + 60]), fresh=True))["quotes"])
        prices = {sym: (quotes.get(y) or {}).get("price") if (quotes.get(y) or {}).get("available") else None for sym, y in yahoo.items()}
        changes = {sym: (quotes.get(y) or {}).get("change_pct") if (quotes.get(y) or {}).get("available") else None for sym, y in yahoo.items()}
        hits = await asyncio.to_thread(_apply_hits, prices, changes, page)
        out.update(hits=hits, priced=sum(p is not None for p in prices.values()))
    if not dispatch:
        out["page_notify"] = page
    try:
        fires, n = await evaluate_rules(scope, quotes=quotes)
    except Exception as exc:  # noqa: BLE001 - the typed engine never takes the price alerts down with it
        fires, n = [], 0
        out["rules_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    out.update(fires=fires, rules_checked=n, scope=scope)
    if dispatch:
        def claim() -> list[dict[str, Any]]:
            with _Tx(sync=False) as c:
                return _claim(c, _now(), started)
        out["dispatch"] = await asyncio.to_thread(claim)
    return out


@router.get("/feed")
def notification_feed(limit: int = 50) -> dict[str, Any]:
    """The notifications the scheduler sent (price, move, filing, wrap), newest first: <data>/notifications.jsonl."""
    p = _path().with_name("notifications.jsonl")
    try:
        lines = p.read_text(encoding="utf-8").splitlines()[-max(1, min(limit, 500)):]
    except OSError:
        return {"items": []}
    items = []
    for ln in reversed(lines):
        try:
            items.append(json.loads(ln))
        except ValueError:
            continue
    return {"items": items}


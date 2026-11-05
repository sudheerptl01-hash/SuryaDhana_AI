"""Server-side user preferences (routers/prefs.py, desktop program D3 / AC-12).

Every test runs on a temp SQLite file (PREFS_DB -> tmp_path) through a minimal app that mounts
only the prefs router plus the repo's error-contract handlers (mirrors main.py, no live deps).
"""
from __future__ import annotations

import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from errors import code_for_status, error_block, validation_error_handler  # noqa: E402
from routers import prefs  # noqa: E402


def _make_app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(StarletteHTTPException)
    async def _handler(request: Request, exc: StarletteHTTPException):  # same as main.py
        d = exc.detail
        if isinstance(d, dict) and "code" in d and "message" in d:
            block = error_block(d["code"], str(d["message"]), d.get("hint"))
            message = str(d["message"])
        else:
            message = d if isinstance(d, str) else str(d)
            block = error_block(code_for_status(exc.status_code), message)
        return JSONResponse({"detail": message, "error": block}, status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))

    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.include_router(prefs.router, prefix="/api/prefs", tags=["prefs"])
    return app


@pytest.fixture()
def db_path(tmp_path, monkeypatch) -> Path:
    p = tmp_path / "ui_prefs.sqlite"
    monkeypatch.setenv("PREFS_DB", str(p))
    prefs.close_all()
    yield p
    prefs.close_all()


@pytest.fixture()
def client(db_path) -> TestClient:
    return TestClient(_make_app())


def _put(c: TestClient, key: str, value: str, ts: int):
    return c.put(f"/api/prefs/{key}", json={"value": value, "updated_at": ts})


def _assert_envelope(r, status: int, code: str):
    assert r.status_code == status, r.text
    body = r.json()
    assert isinstance(body["detail"], str) and body["detail"]
    assert body["error"]["code"] == code
    return body


# ── CRUD ───────────────────────────────────────────────────────────────────────────────────────

def test_empty_store_lists_nothing_and_creates_file_on_demand(client, db_path):
    assert not db_path.exists()
    r = client.get("/api/prefs")
    assert r.status_code == 200
    body = r.json()
    assert body["prefs"] == {}
    assert abs(body["server_time"] - int(time.time() * 1000)) < 60_000
    assert db_path.exists()


def test_put_get_round_trip(client):
    r = _put(client, "suryadhana.watchlist", '["TCS","INFY"]', 1_000)
    assert r.status_code == 200
    assert r.json()["pref"] == {"value": '["TCS","INFY"]', "updated_at": 1_000, "deleted": False}
    got = client.get("/api/prefs").json()["prefs"]
    # GET adds each record's provenance (provisional, origin) for the UI's one-time migration notice
    assert got == {"suryadhana.watchlist": {"value": '["TCS","INFY"]', "updated_at": 1_000, "deleted": False,
                                            "provisional": False, "origin": None}}


def test_survives_a_new_store_instance(client, db_path):
    _put(client, "newsTerminal.pins.v1", "{}", 5)
    prefs.close_all()  # simulate a ui-api restart
    assert prefs.PrefsStore(db_path).all()["newsTerminal.pins.v1"]["value"] == "{}"


def test_sqlite_is_wal_with_versioned_schema(client, db_path):
    client.get("/api/prefs")
    con = sqlite3.connect(str(db_path))
    try:
        assert con.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert con.execute("PRAGMA user_version").fetchone()[0] == prefs.SCHEMA_VERSION
    finally:
        con.close()
    st = prefs.get_store()
    assert st._connection().execute("PRAGMA busy_timeout").fetchone()[0] == prefs.BUSY_TIMEOUT_MS


# ── last-write-wins ────────────────────────────────────────────────────────────────────────────

def test_lww_rejects_older_with_409_and_current(client):
    assert _put(client, "k", "a", 100).status_code == 200
    r = _put(client, "k", "b", 50)
    body = _assert_envelope(r, 409, "state")
    assert body["current"] == {"value": "a", "updated_at": 100, "deleted": False}
    assert body["key"] == "k"
    assert _put(client, "k", "c", 200).status_code == 200
    assert client.get("/api/prefs").json()["prefs"]["k"]["value"] == "c"


def test_identical_replay_is_idempotent_but_same_stamp_other_value_conflicts(client):
    assert _put(client, "k", "v", 300).status_code == 200
    again = _put(client, "k", "v", 300)          # a second window flushing the same queued write
    assert again.status_code == 200 and again.json()["pref"]["value"] == "v"
    clash = _put(client, "k", "w", 300)
    assert clash.status_code == 409 and clash.json()["current"]["value"] == "v"


# ── tombstones ─────────────────────────────────────────────────────────────────────────────────

def test_delete_writes_a_tombstone_that_wins_over_older_puts(client):
    _put(client, "k", "v", 100)
    r = client.delete("/api/prefs/k", params={"updated_at": 200})
    assert r.status_code == 200
    assert r.json()["pref"] == {"value": None, "updated_at": 200, "deleted": True}
    assert client.get("/api/prefs").json()["prefs"]["k"] == {"value": None, "updated_at": 200, "deleted": True,
                                                             "provisional": False, "origin": None}
    stale = _put(client, "k", "old", 150)          # a device that never saw the delete
    assert stale.status_code == 409 and stale.json()["current"]["deleted"] is True
    assert client.delete("/api/prefs/k", params={"updated_at": 200}).status_code == 200   # idempotent
    assert _put(client, "k", "back", 400).status_code == 200                                # resurrect
    assert client.get("/api/prefs").json()["prefs"]["k"]["deleted"] is False


def test_delete_older_than_current_conflicts_and_unknown_key_creates_tombstone(client):
    _put(client, "k", "v", 500)
    _assert_envelope(client.delete("/api/prefs/k", params={"updated_at": 400}), 409, "state")
    r = client.delete("/api/prefs/never.seen", params={"updated_at": 10})
    assert r.status_code == 200 and r.json()["pref"]["deleted"] is True
    _assert_envelope(client.delete("/api/prefs/k"), 422, "invalid")  # updated_at is required


def test_tombstones_are_pruned_after_ttl(client, monkeypatch):
    client.delete("/api/prefs/gone", params={"updated_at": 1})
    monkeypatch.setattr(prefs, "TOMBSTONE_TTL_MS", -1)  # every tombstone is now "old"
    _put(client, "other", "x", 2)                      # pruning runs on writes
    assert "gone" not in client.get("/api/prefs").json()["prefs"]


def test_tombstones_do_not_count_against_the_key_quota(client, monkeypatch):
    monkeypatch.setattr(prefs, "MAX_KEYS", 2)
    _put(client, "a", "1", 1)
    client.delete("/api/prefs/a", params={"updated_at": 2})
    assert _put(client, "b", "1", 1).status_code == 200
    assert _put(client, "c", "1", 1).status_code == 200
    _assert_envelope(_put(client, "d", "1", 1), 413, "invalid")


# ── import (migration from the old browser origin) ─────────────────────────────────────────────

def test_import_fills_only_absent_keys(client):
    _put(client, "suryadhana.watchlist", '["SERVER"]', 100)
    client.delete("/api/prefs/suryadhana.cmd.recent.v1", params={"updated_at": 100})
    before = int(time.time() * 1000)
    r = client.post("/api/prefs/import", json={"origin": "http://localhost:3000", "items": {
        "suryadhana.watchlist": '["LOCAL"]',            # present -> skipped (never overwritten)
        "suryadhana.cmd.recent.v1": '["X"]',            # tombstone counts as present -> skipped
        "newsTerminal.pins.v1": '{"TCS.NS":{}}',        # absent -> imported
        "bad key!": "x",                                # invalid -> rejected
        "suryadhana.ticket.v1": 5,                      # not a string -> rejected
    }})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["imported"] == ["newsTerminal.pins.v1"]
    assert sorted(body["skipped"]) == ["suryadhana.cmd.recent.v1", "suryadhana.watchlist"]
    assert set(body["rejected"]) == {"bad key!", "suryadhana.ticket.v1"}
    assert body["prefs"]["suryadhana.watchlist"]["value"] == '["SERVER"]'
    assert body["prefs"]["suryadhana.cmd.recent.v1"]["deleted"] is True
    pin = body["prefs"]["newsTerminal.pins.v1"]
    assert pin["value"] == '{"TCS.NS":{}}' and pin["updated_at"] >= before
    stored = client.get("/api/prefs").json()["prefs"]
    assert stored["suryadhana.watchlist"]["value"] == '["SERVER"]'
    # importing again is a no-op
    again = client.post("/api/prefs/import", json={"items": {"newsTerminal.pins.v1": "{}"}, "origin": "x"}).json()
    assert again["imported"] == [] and again["skipped"] == ["newsTerminal.pins.v1"]


def test_import_validates_shape_and_count(client, monkeypatch):
    _assert_envelope(client.post("/api/prefs/import", json={"items": []}), 422, "invalid")
    _assert_envelope(client.post("/api/prefs/import", content=b"not json",
                                 headers={"content-type": "application/json"}), 422, "invalid")
    monkeypatch.setattr(prefs, "MAX_IMPORT_ITEMS", 2)
    _assert_envelope(client.post("/api/prefs/import", json={"items": {"a": "1", "b": "2", "c": "3"}}), 413, "invalid")


def test_import_respects_total_quota_per_key(client, monkeypatch):
    monkeypatch.setattr(prefs, "MAX_TOTAL_BYTES", 10)
    body = client.post("/api/prefs/import", json={"items": {"a": "12345", "b": "67890", "c": "x"}}).json()
    assert body["imported"] == ["a", "b"]
    assert "c" in body["rejected"]


def test_provisional_defaults_never_beat_a_legacy_migration(client):
    """App opened first: its default '[]' is imported provisionally; the old origin's real watchlist
    (legacy import) must still replace it. A deliberate PUT makes a value non-provisional."""
    r = client.post("/api/prefs/import", json={"items": {"suryadhana.watchlist": "[]"}, "origin": "app", "provisional": True})
    assert r.json()["imported"] == ["suryadhana.watchlist"]
    prov_at = r.json()["prefs"]["suryadhana.watchlist"]["updated_at"]
    again = client.post("/api/prefs/import", json={"items": {"suryadhana.watchlist": '["X"]'}, "provisional": True}).json()
    assert again["skipped"] == ["suryadhana.watchlist"]                       # provisional never overwrites
    legacy = client.post("/api/prefs/import", json={"items": {"suryadhana.watchlist": '["TCS","INFY"]'},
                                                    "origin": "http://localhost:3000"}).json()
    assert legacy["imported"] == ["suryadhana.watchlist"]
    rec = legacy["prefs"]["suryadhana.watchlist"]
    assert rec["value"] == '["TCS","INFY"]' and rec["updated_at"] > prov_at  # devices that adopted '[]' see it as newer
    second = client.post("/api/prefs/import", json={"items": {"suryadhana.watchlist": '["OTHER"]'}}).json()
    assert second["skipped"] == ["suryadhana.watchlist"]                      # a migrated value is real, not provisional


def test_a_deliberate_write_clears_provisional(client):
    client.post("/api/prefs/import", json={"items": {"k": "default"}, "provisional": True})
    t = client.get("/api/prefs").json()["prefs"]["k"]["updated_at"]
    assert _put(client, "k", "edited", t + 1).status_code == 200
    legacy = client.post("/api/prefs/import", json={"items": {"k": "legacy"}}).json()
    assert legacy["skipped"] == ["k"] and legacy["prefs"]["k"]["value"] == "edited"
    client.post("/api/prefs/import", json={"items": {"gone": "d"}, "provisional": True})
    client.delete("/api/prefs/gone", params={"updated_at": int(time.time() * 1000) + 1000})
    assert client.post("/api/prefs/import", json={"items": {"gone": "legacy"}}).json()["skipped"] == ["gone"]


def test_provisional_flag_must_be_boolean(client):
    _assert_envelope(client.post("/api/prefs/import", json={"items": {"a": "1"}, "provisional": "yes"}), 422, "invalid")


# ── validation limits ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("key", ["", "a" * 129, "has space", "semi;colon", "ümlaut", "slash%2Fkey"])
def test_invalid_keys_are_refused(client, key):
    r = client.put(f"/api/prefs/{key}", json={"value": "v", "updated_at": 1})
    assert r.status_code in (404, 405, 422)   # "" never routes; the rest hit the key check
    if r.status_code == 422:
        _assert_envelope(r, 422, "invalid")


def test_valid_key_alphabet_and_max_length(client):
    key = "A-z_0.9:" + "x" * 120
    assert len(key) == 128
    assert _put(client, key, "v", 1).status_code == 200


def test_value_size_limit_is_utf8_bytes(client):
    exact = "€" * (prefs.MAX_VALUE_BYTES // 3) + "x" * (prefs.MAX_VALUE_BYTES % 3)   # € = 3 bytes
    assert len(exact.encode("utf-8")) == prefs.MAX_VALUE_BYTES
    assert _put(client, "big", exact, 1).status_code == 200
    _assert_envelope(_put(client, "big2", exact + "x", 1), 413, "invalid")


def test_total_size_and_key_count_quotas(client, monkeypatch):
    monkeypatch.setattr(prefs, "MAX_TOTAL_BYTES", 10)
    assert _put(client, "a", "12345", 1).status_code == 200
    assert _put(client, "b", "12345", 1).status_code == 200
    _assert_envelope(_put(client, "c", "1", 1), 413, "invalid")
    assert _put(client, "a", "1", 2).status_code == 200      # replacing a key frees its own bytes
    monkeypatch.setattr(prefs, "MAX_TOTAL_BYTES", 10**9)
    monkeypatch.setattr(prefs, "MAX_KEYS", 3)
    assert _put(client, "c", "1", 1).status_code == 200
    _assert_envelope(_put(client, "d", "1", 1), 413, "invalid")
    assert _put(client, "c", "2", 2).status_code == 200      # updating an existing key is fine


def test_bad_bodies_and_timestamps(client):
    _assert_envelope(client.put("/api/prefs/k", json={"value": 5, "updated_at": 1}), 422, "invalid")
    _assert_envelope(client.put("/api/prefs/k", json={"value": "v"}), 422, "invalid")
    _assert_envelope(client.put("/api/prefs/k", json={"value": "v", "updated_at": -1}), 422, "invalid")
    _assert_envelope(client.put("/api/prefs/k", json={"value": "v", "updated_at": 1.5}), 422, "invalid")
    _assert_envelope(client.put("/api/prefs/k", json={"value": "v", "updated_at": True}), 422, "invalid")
    future = int(time.time() * 1000) + prefs.MAX_FUTURE_SKEW_MS + 60_000
    _assert_envelope(client.put("/api/prefs/k", json={"value": "v", "updated_at": future}), 422, "invalid")
    _assert_envelope(client.put("/api/prefs/k", json=["v"]), 422, "invalid")
    assert client.put("/api/prefs/k", json={"value": "v", "updated_at": 7.0}).status_code == 200  # integral float


def test_oversized_body_is_refused_before_parsing(client):
    huge = b'{"value":"' + b"x" * (prefs.MAX_PUT_BODY + 10) + b'","updated_at":1}'
    _assert_envelope(client.put("/api/prefs/k", content=huge, headers={"content-type": "application/json"}),
                     413, "invalid")


# ── unicode ────────────────────────────────────────────────────────────────────────────────────

def test_unicode_values_round_trip_exactly(client):
    value = '["RELIANCE","टाटा","日本","₹1,23,456.78","🚀📈","line\\nbreak","quote\\"q","\\u0000nul"]'
    assert _put(client, "suryadhana.comp.v1", value, 1).status_code == 200
    assert client.get("/api/prefs").json()["prefs"]["suryadhana.comp.v1"]["value"] == value
    raw = "tab\tnew\nline \u0000 nul 🚀 ₹ टाटा"
    assert _put(client, "raw", raw, 1).status_code == 200
    assert client.get("/api/prefs").json()["prefs"]["raw"]["value"] == raw


def test_lone_surrogate_is_refused(client):
    r = client.put("/api/prefs/k", content=b'{"value":"bad \\ud800 half","updated_at":1}',
                   headers={"content-type": "application/json"})
    _assert_envelope(r, 422, "invalid")


# ── concurrency ────────────────────────────────────────────────────────────────────────────────

def test_concurrent_writes_converge_to_the_newest(client, db_path):
    errors: list[str] = []
    n_threads, n_writes = 12, 20

    def worker(t: int):
        c = TestClient(_make_app())
        for i in range(n_writes):
            ts = i * n_threads + t + 1
            r = _put(c, "shared", f"t{t}-i{i}", ts)
            if r.status_code not in (200, 409):
                errors.append(f"shared {r.status_code}")
            r2 = _put(c, f"own.{t}", str(i), i + 1)
            if r2.status_code != 200:
                errors.append(f"own {r2.status_code}")

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=60)
    assert not errors, errors[:5]
    got = client.get("/api/prefs").json()["prefs"]
    newest = (n_writes - 1) * n_threads + (n_threads - 1) + 1
    assert got["shared"]["updated_at"] == newest
    assert got["shared"]["value"] == f"t{n_threads - 1}-i{n_writes - 1}"
    for t in range(n_threads):
        assert got[f"own.{t}"] == {"value": str(n_writes - 1), "updated_at": n_writes, "deleted": False,
                                   "provisional": False, "origin": None}


def test_two_store_instances_on_one_file_serialize(db_path):
    """Two independent connections (e.g. two processes) on the same WAL file: no lost updates."""
    a, b = prefs.PrefsStore(db_path), prefs.PrefsStore(db_path)
    try:
        def w(st, base):
            for i in range(50):
                st.write(f"k{base}", str(i), i + 1)
        ta, tb = threading.Thread(target=w, args=(a, 1)), threading.Thread(target=w, args=(b, 2))
        for t in (ta, tb):
            t.start()
        for t in (ta, tb):
            t.join()
        allp = a.all()
        assert allp["k1"]["value"] == "49" and allp["k2"]["value"] == "49"
    finally:
        a.close()
        b.close()


# ── corrupted / foreign files ──────────────────────────────────────────────────────────────────

def test_corrupted_file_is_quarantined_and_store_recreated(client, db_path):
    """Documented behavior: a non-database file is renamed to <file>.corrupt-<ts> (kept for forensics)
    and a fresh store is created; clients re-upload what the server lacks (self-healing)."""
    db_path.write_bytes(b"this is definitely not an sqlite database" * 100)
    r = client.get("/api/prefs")
    assert r.status_code == 200 and r.json()["prefs"] == {}
    quarantined = list(db_path.parent.glob(db_path.name + ".corrupt-*"))
    assert quarantined and quarantined[0].read_bytes().startswith(b"this is definitely")
    assert _put(client, "k", "v", 1).status_code == 200
    assert client.get("/api/prefs").json()["prefs"]["k"]["value"] == "v"


def test_corruption_detected_mid_session_recovers(client, db_path):
    assert _put(client, "k", "v", 1).status_code == 200
    prefs.close_all()
    for suffix in ("-wal", "-shm"):
        Path(str(db_path) + suffix).unlink(missing_ok=True)
    db_path.write_bytes(b"\x00" * 4096)
    assert client.get("/api/prefs").status_code == 200
    assert _put(client, "k2", "v", 1).status_code == 200


def test_newer_schema_is_refused_not_downgraded(client, db_path):
    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA user_version=99")
    con.commit()
    con.close()
    body = _assert_envelope(client.get("/api/prefs"), 503, "state")
    assert "newer" in body["detail"]
    assert db_path.exists() and not list(db_path.parent.glob("*.corrupt-*"))


def test_unwritable_location_is_503_not_500(client, tmp_path, monkeypatch):
    blocker = tmp_path / "file-not-dir"
    blocker.write_text("x")
    monkeypatch.setenv("PREFS_DB", str(blocker / "sub" / "prefs.sqlite"))
    prefs.close_all()
    _assert_envelope(client.get("/api/prefs"), 503, "state")


# ── event-loop purity ──────────────────────────────────────────────────────────────────────────

def test_blocking_handlers_are_sync_and_async_ones_offload():
    import inspect
    assert not inspect.iscoroutinefunction(prefs.list_prefs)
    assert not inspect.iscoroutinefunction(prefs.delete_pref)
    for fn in (prefs.put_pref, prefs.import_prefs):
        src = inspect.getsource(fn)
        assert "run_in_threadpool" in src, fn.__name__


def test_logs_never_contain_values(client, caplog):
    import logging
    caplog.set_level(logging.INFO, logger="ui-api.prefs")
    secret = "VALUE-THAT-MUST-NOT-BE-LOGGED"
    _put(client, "k", secret, 1)
    client.post("/api/prefs/import", json={"items": {"k2": secret}, "origin": "o"})
    assert caplog.records, "expected structured log lines"
    assert all(secret not in rec.getMessage() for rec in caplog.records)


def test_get_exposes_provenance_for_the_migration_notice(client):
    """A legacy import records its origin and is not provisional; a provisional default says so (FX-UI notice)."""
    client.post("/api/prefs/import", json={"items": {"suryadhana.watchlist": "[]"}, "origin": "app", "provisional": True})
    rec = client.get("/api/prefs").json()["prefs"]["suryadhana.watchlist"]
    assert rec["provisional"] is True
    client.post("/api/prefs/import", json={"items": {"suryadhana.watchlist": '["TCS"]'}, "origin": "http://localhost:3000"})
    rec = client.get("/api/prefs").json()["prefs"]["suryadhana.watchlist"]
    assert rec["provisional"] is False and rec["origin"] == "http://localhost:3000" and rec["value"] == '["TCS"]'

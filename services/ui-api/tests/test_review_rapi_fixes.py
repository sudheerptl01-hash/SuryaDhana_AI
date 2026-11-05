"""Regression tests for the final review's R-API findings that live in ui-api (RAPI-01, -02, -05, -06, -07, -08,
-09, -10). RAPI-03/-11 (shared/http_guard.py) are in tests/unit/test_http_guard.py; RAPI-04 in test_env_roundtrip.py."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest
import redis.exceptions as redis_exc
from fastapi import FastAPI
from fastapi.testclient import TestClient

UI_API = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(UI_API))

from routers import _features_explorer as fx
from routers import _loop_watchdog as wd
from routers import client_errors as ce
from routers import monitor as mon
from routers import prefs

pytestmark = pytest.mark.filterwarnings("ignore:DataFrame columns are not unique:UserWarning")


# ── RAPI-05: a stall seen only after the whole process was frozen is labelled post hoc ─────────────────

@pytest.fixture
def wd_records(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    out: list[dict] = []
    monkeypatch.setattr(wd.log, "handle", lambda r: out.append({"event": r.getMessage(), **getattr(r, "fields", {})}))
    return out


def _dog(stream: Any) -> wd.LoopStallWatchdog:
    loop = asyncio.new_event_loop()
    dog = wd.LoopStallWatchdog(loop, stall_s=5.0, check_s=0.5, stream=stream)
    loop.close()
    return dog


def test_a_watcher_gap_marks_the_stall_and_heads_the_dump(wd_records: list[dict]) -> None:
    with tempfile.TemporaryFile("w+") as stream:
        dog = _dog(stream)
        dog.last_beat = 100.0
        dog.tick(148.5, watcher_gap=48.0)                  # the 15:40 drill: first check 48 s late
        stream.seek(0)
        dump = stream.read()
    assert wd_records[0]["event"] == "loop_stall" and wd_records[0]["post_hoc"] is True
    assert wd_records[0]["watcher_gap_s"] == 48.0 and "NOT show what blocked" in wd_records[0]["hint"]
    assert dump.startswith("--- loop_watchdog: post-hoc dump") and "thread 0x" in dump.lower()
    assert dog.post_hoc_stalls == 1 and dog.stalls == 1


def test_an_ordinary_stall_is_not_post_hoc(wd_records: list[dict]) -> None:
    with tempfile.TemporaryFile("w+") as stream:
        dog = _dog(stream)
        dog.last_beat = 100.0
        dog.tick(105.6, watcher_gap=0.5)                   # the watcher ran on time, the loop did not
        stream.seek(0)
        dump = stream.read()
    assert wd_records[0]["event"] == "loop_stall" and "post_hoc" not in wd_records[0]
    assert "post-hoc" not in dump and dog.post_hoc_stalls == 0


@pytest.mark.skipif(not hasattr(signal, "SIGSTOP"), reason="needs SIGSTOP")
def test_a_real_sigstop_is_reported_post_hoc() -> None:
    """The reviewer's case end to end: a child ui-api-like loop with the watchdog is frozen with SIGSTOP."""
    code = textwrap.dedent(f"""
        import asyncio, sys, time
        sys.path.insert(0, {str(UI_API)!r})
        from routers import _loop_watchdog as wd
        async def main():
            dog = wd.LoopStallWatchdog(asyncio.get_running_loop(), stall_s=0.3, beat_s=0.05, check_s=0.05,
                                       stream=sys.stderr).start()
            await asyncio.sleep(0.2)
            print("READY", flush=True)
            time.sleep(2.0)            # the loop stays busy after the freeze, so the watcher is first to look
            await asyncio.sleep(0.2)
            await dog.stop()
        asyncio.run(main())
    """)
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert proc.stdout is not None and proc.stdout.readline().strip() == "READY"
        os.kill(proc.pid, signal.SIGSTOP)
        time.sleep(1.0)
        os.kill(proc.pid, signal.SIGCONT)
        _, err = proc.communicate(timeout=20)
    finally:
        if proc.poll() is None:
            proc.kill()
    stalls = [json.loads(ln) for ln in err.splitlines() if ln.startswith("{") and '"loop_stall"' in ln]
    assert stalls and stalls[0].get("post_hoc") is True and stalls[0]["watcher_gap_s"] >= 0.8, err[-2000:]
    assert "post-hoc dump" in err


# ── RAPI-06 / RAPI-07: client error reports ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, secret", [
    ('fetch failed {"apisession": "S3CR3T-123456", "session_token":"TKN-abcdef"}', "S3CR3T-123456"),
    ('fetch failed {"apisession": "S3CR3T-123456", "session_token":"TKN-abcdef"}', "TKN-abcdef"),
    ("Authorization: Basic dXNlcjpwYXNz api_key: AKIA1234567890", "dXNlcjpwYXNz"),
    ("Authorization: Basic dXNlcjpwYXNz api_key: AKIA1234567890", "AKIA1234567890"),
    ("{'password': 'hunter22'}", "hunter22"),
    ("client_secret=abcd1234&x=1", "abcd1234"),
    ("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.e30.x", "eyJhbGciOiJIUzI1NiJ9"),
    ("auth Basic QWxhZGRpbjpvcGVu", "QWxhZGRpbjpvcGVu"),
])
def test_json_colon_and_basic_credentials_are_masked(text: str, secret: str) -> None:
    out = ce._clean_text(text, 500)
    assert secret not in out and "<redacted>" in out


def test_masking_keeps_the_shape_and_spares_ordinary_text() -> None:
    assert ce._clean_text('{"apisession": "S"}', 100) == '{"apisession": "<redacted>"}'
    assert ce._clean_text("Authorization: Bearer abcdefghij", 100) == "Authorization: Bearer <redacted>"
    for ok in ("Unexpected token < in JSON at position 0", "max_tokens: 500", "tokens left: 3"):
        assert ce._clean_text(ok, 100) == ok


def test_a_report_is_one_line_for_every_line_splitter() -> None:
    body = {"message": "boom\u2028{\"event\": \"loop_stall\", \"forged\": true}\x85FORGED\u2029x\u202eevil",
            "stack": "Error\n    at f (a.js:1)\u2028forged\tline"}
    fields = ce.sanitize_report(body)
    record = logging.LogRecord("suryadhana.client_errors", logging.WARNING, __file__, 1, "client_error", None, None)
    record.fields = fields
    line = ce._JsonLineFormatter().format(record)
    assert len(line.splitlines()) == 1 and len(line.split("\n")) == 1
    assert "\u2028" not in line and "\x85" not in line and "\u202e" not in line
    assert fields["stack"].count("\n") == 1 and "\t" in fields["stack"]          # stack keeps \n and \t


# ── RAPI-08: malformed monitor messages are answered, not raised ──────────────────────────────────────

@pytest.fixture
def monitor_client(monkeypatch: pytest.MonkeyPatch):
    def down() -> Any:
        raise ConnectionError("Connection refused")
    monkeypatch.setattr(mon, "_open_quotes_pubsub", down)
    monkeypatch.setattr(mon, "_ws_active", 0)
    monkeypatch.setattr(mon, "RESTART_BACKOFF_S", (60.0,))
    mon.manager.active.clear()
    app = FastAPI()
    app.include_router(mon.router, prefix="/api/monitor")
    with TestClient(app) as c:
        yield c


def test_non_object_and_badly_typed_messages_get_bad_message(monitor_client: TestClient) -> None:
    with monitor_client.websocket_connect("/api/monitor/ws/monitor") as ws:
        assert ws.receive_json()["error"] == "redis_unavailable"
        for raw in ("[1]", '"x"', "5", "null", "true"):
            ws.send_text(raw)
            assert ws.receive_json() == {"error": "bad_message"}
        ws.send_json({"action": "subscribe", "symbols": "TCS"})        # a string, not a list
        assert ws.receive_json() == {"error": "bad_message", "action": "subscribe"}
        ws.send_json({"action": "subscribe", "symbols": ["tcs", 5, None, {"x": 1}, "infy"]})
        assert set(ws.receive_json()["subscribed"]) == {"TCS", "INFY"}
        ws.send_json({"action": "subscribe", "symbols": [f"S{i}" for i in range(900)]})
        assert len(ws.receive_json()["subscribed"]) == mon.MAX_SYMBOLS
        ws.send_json({"action": "unsubscribe", "symbols": [1, "s0"]})
        assert len(ws.receive_json()["subscribed"]) == mon.MAX_SYMBOLS - 1
        ws.send_json({"action": {"nested": [1, 2]}})
        assert ws.receive_json() == {"error": "unknown_action", "action": None}
        ws.send_text("not json")                                           # still ignored, as before
        ws.send_json({"action": "ping"})
        assert ws.receive_json() == {"pong": True}                         # the socket survived all of it


# ── RAPI-01: joins against a Redis that accepts TCP but never answers fail together, fast ─────────────

class _HungRedis:
    """Accepts connections and never sends a byte (SIGSTOPped Redis, a wedged one)."""

    def __init__(self) -> None:
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(64)
        self.port = self.sock.getsockname()[1]
        self.conns: list[socket.socket] = []
        self._stop = False
        self.thread = threading.Thread(target=self._accept, daemon=True)
        self.thread.start()

    def _accept(self) -> None:
        self.sock.settimeout(0.1)
        while not self._stop:
            try:
                c, _ = self.sock.accept()
                self.conns.append(c)
            except OSError:
                continue

    def close(self) -> None:
        self._stop = True
        self.thread.join(2)
        for c in self.conns:
            c.close()
        self.sock.close()


@pytest.fixture
def hung_redis(monkeypatch: pytest.MonkeyPatch):
    srv = _HungRedis()
    monkeypatch.setattr(mon, "REDIS_URL", f"redis://127.0.0.1:{srv.port}/0")
    monkeypatch.setattr(mon, "HANDSHAKE_TIMEOUT_S", 0.5)
    monkeypatch.setattr(mon, "RESTART_BACKOFF_S", (60.0,))
    yield srv
    srv.close()


def test_concurrent_joins_share_one_attempt_and_fail_within_one_handshake(hung_redis, monkeypatch) -> None:
    monkeypatch.setattr(mon, "FAILED_JOIN_MEMORY_S", 0.3)

    async def scenario() -> dict[str, Any]:
        hub = mon._QuotesHub(asyncio.get_running_loop())
        t0 = time.monotonic()
        results = await asyncio.gather(*(hub.join(mon._Subscriber()) for _ in range(4)), return_exceptions=True)
        together = time.monotonic() - t0
        t1 = time.monotonic()
        with pytest.raises(mon.RedisUnavailable):              # inside the memory window: fails at once
            await hub.join(mon._Subscriber())
        at_once = time.monotonic() - t1
        attempts_then = hub.connect_attempts
        await asyncio.sleep(0.35)                               # memory expired: a fresh attempt
        with pytest.raises(redis_exc.TimeoutError):            # a real second probe, timed out again
            await hub.join(mon._Subscriber())
        out = {"results": results, "together": together, "at_once": at_once, "attempts_then": attempts_then,
               "attempts": hub.connect_attempts, "subscribers": len(hub.subscribers)}
        if hub._restart is not None:
            hub._restart.cancel()
        return out
    out = asyncio.run(scenario())
    assert all(isinstance(r, redis_exc.TimeoutError) for r in out["results"])
    assert out["together"] < 1.5, out                        # was: k-th join waited k x 10 s
    assert out["attempts_then"] == 1 and out["at_once"] < 0.1
    assert out["attempts"] == 2 and out["subscribers"] == 6  # they stay registered for the reconnect


def test_the_probe_fails_fast_where_the_subscription_timeout_would_wait(hung_redis) -> None:
    t0 = time.monotonic()
    with pytest.raises(redis_exc.TimeoutError):
        mon._probe_redis()
    assert time.monotonic() - t0 < 2.0


# ── RAPI-02: only an import from the old :3000 browser terminal records the migration ─────────────────

NONE = {"legacy_import_at": None, "legacy_origin": None, "legacy_keys": 0, "inferred": False}


@pytest.fixture
def prefs_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db = tmp_path / "ui_prefs.sqlite"
    monkeypatch.setenv("PREFS_DB", str(db))
    prefs.close_all()
    app = FastAPI()
    app.include_router(prefs.router, prefix="/api/prefs")
    yield TestClient(app), db
    prefs.close_all()


def _import(c: TestClient, items: dict[str, str], origin: str, provisional: bool = False) -> None:
    r = c.post("/api/prefs/import", json={"items": items, "origin": origin, "provisional": provisional})
    assert r.status_code == 200, r.text


def test_a_non_provisional_import_from_the_app_origin_records_no_migration(prefs_client) -> None:
    c, _ = prefs_client
    _import(c, {"suryadhana.watchlist": "[]"}, "http://127.0.0.1:8010", provisional=True)
    _import(c, {"suryadhana.watchlist": "[]"}, "http://127.0.0.1:8010")            # the review's reproduction
    _import(c, {"suryadhana.pins": '["desk"]'}, "http://localhost:8010")            # a browser tab on :8010
    assert c.get("/api/prefs").json()["migration"] == NONE
    _import(c, {"suryadhana.compare": '["TCS"]'}, "http://localhost:3000")          # the real migration
    m = c.get("/api/prefs").json()["migration"]
    assert m["legacy_origin"] == "http://localhost:3000" and m["legacy_keys"] == 1 and m["inferred"] is False


def test_a_block_written_for_a_non_legacy_origin_reads_as_none_and_is_replaced(prefs_client) -> None:
    c, db = prefs_client
    c.get("/api/prefs")                                                             # creates the store
    bogus = {"legacy_import_at": 1761300000000, "legacy_origin": "http://127.0.0.1:8010", "legacy_keys": 1,
             "inferred": False}
    import sqlite3
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('migration', ?)", (json.dumps(bogus),))
    prefs.close_all()
    assert c.get("/api/prefs").json()["migration"] == NONE
    _import(c, {"suryadhana.watchlist": '["INFY"]'}, "http://127.0.0.1:3000")
    assert c.get("/api/prefs").json()["migration"]["legacy_origin"] == "http://127.0.0.1:3000"


# ── RAPI-09 / RAPI-10: DEXP reads one file version; the slow fallback is logged ───────────────────────

def _matrix(path: Path, seed: int) -> None:
    import numpy as np
    import pandas as pd
    rng = np.random.default_rng(seed)
    n = 300
    df = pd.DataFrame({"ticker": rng.choice(["AAA", "BBB", "CCC"], n), "date": [f"2024-01-{1 + i % 28:02d}" for i in range(n)],
                       "rsi_14": rng.normal(50, 10, n), "macd": rng.normal(0, 1, n)})
    df.to_parquet(path, index=False, row_group_size=50)


KW = {"page": 1, "page_size": 20, "ticker": None, "sort_by": "rsi_14", "sort_dir": "desc", "v": 1,
      "feature_cols": ["rsi_14", "macd"]}


def test_a_rebuild_landing_mid_request_is_never_cached_or_mixed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    live, new = tmp_path / "computed_features.parquet", tmp_path / "next.parquet"
    _matrix(live, 1)
    _matrix(new, 2)
    ex = fx.FeaturesExplorer()
    real = fx._read_columns
    swapped = {"done": False}

    def read_then_rebuild(src: Path, columns: list[str]):
        out = real(src, columns)
        if not swapped["done"]:
            swapped["done"] = True
            os.replace(new, live)                     # the Phase-3 rebuild lands between our reads
        return out
    monkeypatch.setattr(fx, "_read_columns", read_then_rebuild)
    got = ex.page(live, **KW)
    expected = fx.legacy_page(live, **KW)             # the NEW file, read whole
    assert json.dumps(got, default=str) == json.dumps(expected, default=str)
    assert ex.stats["file_changed"] == 1
    sig = fx.file_signature(live)
    assert all(k[0] == sig for k in list(ex._base._d) + list(ex._order._d) + list(ex._pages._d))


def test_the_slow_fallback_is_logged_once_per_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import pandas as pd
    lines: list[str] = []
    monkeypatch.setattr(fx.log, "warning", lambda msg, *a, **k: lines.append(msg))
    indexed = tmp_path / "indexed.parquet"
    df = pd.DataFrame({"ticker": ["AAA"] * 5, "date": ["2024-01-01"] * 5, "rsi_14": [1.0] * 5, "macd": [0.0] * 5})
    df.index = pd.Index([10, 11, 12, 13, 14], name="row")
    df.to_parquet(indexed, index=True)
    ex = fx.FeaturesExplorer()
    for _ in range(3):
        ex.page(indexed, **KW)
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["event"] == "features_explorer.legacy_fallback" and "index=False" in rec["reason"]
    assert rec["file"] == "indexed.parquet" and ex.stats["legacy"] == 3
    plain = tmp_path / "plain.parquet"
    _matrix(plain, 3)
    ex.page(plain, **KW)
    assert len(lines) == 1                                         # the fast path logs nothing
    assert pq.ParquetFile(plain).schema_arrow.pandas_metadata["index_columns"] == []

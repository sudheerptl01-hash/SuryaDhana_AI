"""In-app settings import from the old browser terminal (page review 5 Nov 2026, M35; routers/prefs.py).

The one-shot import page is started on a free test port (PREFS_LEGACY_IMPORT_PORT) on a temp PREFS_DB; every rule
has a negative control: a wrong token, a foreign Host or Origin, a non-JSON body, keys outside the allowlist, a
second POST after the single use, a port that is already taken, and a value the owner set in the app (never replaced).
"""
from __future__ import annotations

import http.client
import json
import socket
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from routers import prefs  # noqa: E402

KEYS = ["suryadhana.watchlist", "newsTerminal.pins.v1", "suryadhana.omon.v1"]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    port = _free_port()
    monkeypatch.setenv("PREFS_DB", str(tmp_path / "ui_prefs.sqlite"))
    monkeypatch.setenv("PREFS_LEGACY_IMPORT_PORT", str(port))
    monkeypatch.setattr(prefs, "LEGACY_BROWSER_PORT", port)       # the test port plays the old :3000 origin
    prefs.close_all()
    app = FastAPI()
    app.include_router(prefs.router, prefix="/api/prefs")
    c = TestClient(app)
    yield c, port
    prefs.close_all()


def _start(c: TestClient, keys=KEYS):
    return c.post("/api/prefs/legacy-import", json={"keys": keys})


def _req(port: int, method: str, path: str, body: bytes | None = None, headers: dict | None = None):
    h = {"Host": f"localhost:{port}", **(headers or {})}
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request(method, path, body=body, headers=h)
    r = conn.getresponse()
    data = r.read()
    conn.close()
    return r.status, dict(r.getheaders()), data


def _post_items(port: int, token: str, items: dict, *, origin: str | None = None, ctype: str = "application/json"):
    body = json.dumps({"items": items}).encode()
    return _req(port, "POST", f"/import?t={token}", body,
                {"Origin": origin or f"http://localhost:{port}", "Content-Type": ctype, "Content-Length": str(len(body))})


def _token(url: str) -> str:
    return url.split("t=", 1)[1]


def test_start_serves_the_page_and_reports_waiting(env):
    c, port = env
    r = _start(c)
    assert r.status_code == 200
    b = r.json()
    assert b["state"] == "waiting" and b["port"] == port and b["url"].startswith(f"http://localhost:{port}/import?t=")
    st, headers, html = _req(port, "GET", f"/import?t={_token(b['url'])}")
    assert st == 200 and b"IMPORT SETTINGS FROM THE BROWSER TERMINAL" in html
    assert "script-src 'nonce-" in headers["Content-Security-Policy"] and "connect-src 'self'" in headers["Content-Security-Policy"]
    for k in KEYS:                                          # the page reads exactly the keys the UI sent
        assert k.encode() in html
    assert c.get("/api/prefs/legacy-import").json()["state"] == "waiting"
    # a second start while it waits returns the same page (one listener, one token)
    assert _start(c).json()["url"] == b["url"]


def test_wrong_token_host_and_paths_are_refused(env):
    c, port = env
    tok = _token(_start(c).json()["url"])
    assert _req(port, "GET", "/import?t=wrong" + "x" * 20)[0] == 403              # negative control: token
    assert _req(port, "GET", f"/import?t={tok}", headers={"Host": f"evil.example:{port}"})[0] == 403   # DNS rebinding
    assert _req(port, "GET", f"/other?t={tok}")[0] == 404
    assert _req(port, "PUT", f"/import?t={tok}", b"{}")[0] == 405
    assert _req(port, "GET", f"/import?t={tok}")[0] == 200                         # the right one still works


def test_post_fills_only_absent_or_provisional_keys_and_records_the_migration(env):
    c, port = env
    store = prefs.get_store()
    store.write("suryadhana.omon.v1", "INFY", 1_000, "http://127.0.0.1:8010")            # set in the app: kept
    store.import_items({"suryadhana.watchlist": "[]"}, "http://127.0.0.1:8010", provisional=True)   # a default: filled
    tok = _token(_start(c).json()["url"])
    items = {"suryadhana.watchlist": '["TCS","INFY"]', "newsTerminal.pins.v1": '["RELIANCE"]', "suryadhana.omon.v1": "TCS",
             "not.allowed.key": "x"}
    st, _h, body = _post_items(port, tok, items)
    assert st == 200, body
    out = json.loads(body)
    assert sorted(out["imported"]) == ["newsTerminal.pins.v1", "suryadhana.watchlist"]
    assert out["skipped"] == ["suryadhana.omon.v1"]
    allp = store.all()
    assert allp["suryadhana.watchlist"]["value"] == '["TCS","INFY"]' and allp["suryadhana.omon.v1"]["value"] == "INFY"
    assert "not.allowed.key" not in allp                                              # negative control: allowlist
    mig = store.migration()
    assert mig["legacy_import_at"] and mig["legacy_origin"] == f"http://localhost:{port}" and mig["legacy_keys"] == 2
    s = c.get("/api/prefs/legacy-import").json()
    assert s["state"] == "done" and sorted(s["imported"]) == ["newsTerminal.pins.v1", "suryadhana.watchlist"]
    assert "TCS" not in json.dumps(s)                                                   # names only, never a value


def test_post_needs_origin_json_and_is_single_use(env):
    c, port = env
    tok = _token(_start(c).json()["url"])
    items = {"suryadhana.watchlist": '["TCS"]'}
    assert _post_items(port, tok, items, origin="http://evil.example")[0] == 403       # negative control: Origin
    assert _post_items(port, tok, items, ctype="text/plain")[0] == 415                   # negative control: JSON only
    assert "suryadhana.watchlist" not in prefs.get_store().all()                         # nothing written by those
    assert _post_items(port, tok, items)[0] == 200
    # single use: the page closes after an import
    import time
    for _ in range(40):
        if not prefs._legacy or not prefs._legacy.servers:
            break
        time.sleep(0.05)
    with pytest.raises(OSError):
        _post_items(port, tok, items)


def test_port_busy_refuses_to_start(env, monkeypatch):
    c, _port = env
    with socket.socket() as other:                     # something (the Next dev UI) already listens on the port
        other.bind(("127.0.0.1", 0))
        other.listen(1)
        monkeypatch.setenv("PREFS_LEGACY_IMPORT_PORT", str(other.getsockname()[1]))
        r = _start(c)
    assert r.status_code == 409 and r.json()["state"] == "port_busy"
    assert "imports the settings" in r.json()["detail"]


def test_stop_and_expiry_close_the_page(env, monkeypatch):
    c, port = env
    tok = _token(_start(c).json()["url"])
    assert c.post("/api/prefs/legacy-import/stop").json()["state"] == "stopped"
    with pytest.raises(OSError):
        _req(port, "GET", f"/import?t={tok}")
    # an expired page answers 410 while it still listens, and reports expired
    tok2 = _token(_start(c).json()["url"])
    prefs._legacy.expires_at = 0
    assert _req(port, "GET", f"/import?t={tok2}")[0] == 410
    assert c.get("/api/prefs/legacy-import").json()["state"] == "expired"


def test_start_validates_keys(env):
    c, _port = env
    assert c.post("/api/prefs/legacy-import", json={"keys": []}).status_code == 422
    assert c.post("/api/prefs/legacy-import", json={"keys": ["bad key!"]}).status_code == 422
    assert c.post("/api/prefs/legacy-import", content=b'{"keys":["a"]}', headers={"Content-Type": "text/plain"}).status_code == 415
    assert c.get("/api/prefs/legacy-import").json()["state"] == "idle"

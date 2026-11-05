"""scratch_server --prefs-db: /api/prefs served locally on a scratch SQLite file (FX-OPS, for FX-UI's E2E).

No live stack, no network: the backend is an ``httpx.MockTransport`` that records every forwarded request, so
each test can prove /api/prefs never left the scratch server while everything else still did.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from desktop_qa import scratch_server


def _app(tmp_path: Path, **kw):
    from fastapi.testclient import TestClient

    ui = tmp_path / "export"
    ui.mkdir()
    (ui / "index.html").write_text("<html>index</html>")
    seen: list[httpx.Request] = []

    def backend(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, headers={"content-type": "application/json"},
                              stream=httpx.ByteStream(json.dumps({"forwarded": req.url.path}).encode()))

    client = httpx.AsyncClient(transport=httpx.MockTransport(backend), base_url="http://backend")
    return TestClient(scratch_server.create_app(ui, "http://backend", client=client, **kw)), seen


def test_prefs_db_serves_prefs_locally_and_forwards_the_rest(tmp_path):
    db = tmp_path / "prefs" / "ui_prefs.sqlite"
    c, seen = _app(tmp_path, prefs_db=db, block_mutations=True)
    with c:
        assert c.get("/__qa/health").json()["prefs"] == f"local:{db.resolve()}"
        assert c.get("/api/prefs").json()["prefs"] == {}
        r = c.put("/api/prefs/watchlist", json={"value": '["TCS"]', "updated_at": 1000})
        assert r.status_code == 200 and r.json()["pref"]["value"] == '["TCS"]'
        assert c.get("/api/prefs").json()["prefs"]["watchlist"]["value"] == '["TCS"]'
        r = c.post("/api/prefs/import", json={"items": {"watchlist": "[]", "pins": "[1]"}, "origin": "http://x"})
        assert r.status_code == 200 and r.json()["imported"] == ["pins"] and r.json()["skipped"] == ["watchlist"]
        later = r.json()["prefs"]["pins"]["updated_at"] + 1  # the import stamped pins with server time
        assert c.delete(f"/api/prefs/pins?updated_at={later}").status_code == 200
        # every prefs call stayed local: the backend saw none of them
        assert not [q for q in seen if q.url.path.startswith("/api/prefs")]
        # --block-mutations still guards what is forwarded; GETs still reach the backend
        assert c.post("/api/desk/run", json={}).status_code == 403
        assert c.get("/api/desk/status").json() == {"forwarded": "/api/desk/status"}
        assert [q.url.path for q in seen] == ["/api/desk/status"]
    # the writes landed in the scratch file (and only there)
    with sqlite3.connect(db) as con:
        rows = dict(con.execute("SELECT key, deleted FROM prefs").fetchall())
    assert rows == {"watchlist": 0, "pins": 1}


def test_prefs_db_keeps_ui_api_error_contract(tmp_path):
    c, _ = _app(tmp_path, prefs_db=tmp_path / "p.sqlite")
    with c:
        assert c.put("/api/prefs/k", json={"value": "new", "updated_at": 2000}).status_code == 200
        r = c.put("/api/prefs/k", json={"value": "old", "updated_at": 1000})
        assert r.status_code == 409 and r.json()["current"]["value"] == "new"
        r = c.delete("/api/prefs/k")  # updated_at missing -> errors.fail(422)
        assert r.status_code == 422 and isinstance(r.json()["detail"], str) and r.json()["error"]["code"] == "invalid"
        r = c.delete("/api/prefs/k?updated_at=notanint")  # FastAPI validation -> same envelope
        assert r.status_code == 422 and r.json()["error"]["code"] == "invalid"
        assert c.put("/api/prefs/bad key!", json={"value": "x", "updated_at": 1}).status_code == 422


def test_prefs_db_honours_inject(tmp_path):
    inject = scratch_server.parse_inject([r"^/api/prefs$=503"])
    c, seen = _app(tmp_path, prefs_db=tmp_path / "p.sqlite", inject=inject)
    with c:
        r = c.get("/api/prefs")
        assert r.status_code == 503 and "injected" in r.json()["detail"] and not seen
        assert c.put("/api/prefs/k", json={"value": "v", "updated_at": 1}).status_code == 200  # not matched


def test_without_prefs_db_prefs_are_forwarded(tmp_path):
    """Backwards compatible: no --prefs-db means /api/prefs goes to the backend exactly as before."""
    c, seen = _app(tmp_path)
    assert c.get("/__qa/health").json()["prefs"] == "forwarded"
    assert c.get("/api/prefs").json() == {"forwarded": "/api/prefs"}
    assert [q.url.path for q in seen] == ["/api/prefs"]
    assert not (tmp_path / "export" / "ui_prefs.sqlite").exists()


def test_prefs_db_refuses_the_live_store_and_directories(tmp_path):
    with pytest.raises(ValueError, match="live store"):
        scratch_server.load_prefs_module(scratch_server.LIVE_PREFS_DB)
    with pytest.raises(ValueError, match="directory"):
        scratch_server.load_prefs_module(tmp_path)
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("x")
    assert scratch_server.main(["--ui", str(ui), "--prefs-db", str(scratch_server.LIVE_PREFS_DB)]) == 2


def test_prefs_module_copies_are_isolated(tmp_path):
    a = scratch_server.load_prefs_module(tmp_path / "a.sqlite")
    b = scratch_server.load_prefs_module(tmp_path / "b.sqlite")
    try:
        a.get_store().write("k", "from-a", 1)
        assert b.get_store().all() == {} and a.get_store().all()["k"]["value"] == "from-a"
    finally:
        a.close_all()
        b.close_all()

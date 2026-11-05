"""Durable migration provenance in GET /api/prefs (wave-2 contract K2).

``migration: {legacy_import_at, legacy_origin, legacy_keys, inferred}`` is written once, by the first legacy
(non-provisional) import with at least one valid item, kept in the SQLite ``meta`` table, and never cleared by
PUT/DELETE (which DO rewrite the per-record provenance the UI used to rely on). A store migrated before the
field existed is backfilled once from per-record provenance. Runs on a temp PREFS_DB through the router.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from routers import prefs

LEGACY = "http://localhost:3000"
APP = "http://127.0.0.1:8010"
NONE = {"legacy_import_at": None, "legacy_origin": None, "legacy_keys": 0, "inferred": False}


@pytest.fixture()
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    p = tmp_path / "ui_prefs.sqlite"
    monkeypatch.setenv("PREFS_DB", str(p))
    prefs.close_all()
    yield p
    prefs.close_all()


@pytest.fixture()
def client(db_path: Path) -> TestClient:
    app = FastAPI()
    app.include_router(prefs.router, prefix="/api/prefs")
    return TestClient(app)


def _import(c: TestClient, items: dict[str, str], origin: str, provisional: bool = False) -> dict:
    r = c.post("/api/prefs/import", json={"items": items, "origin": origin, "provisional": provisional})
    assert r.status_code == 200, r.text
    return r.json()


def _migration(c: TestClient) -> dict:
    r = c.get("/api/prefs")
    assert r.status_code == 200
    return r.json()["migration"]


def test_a_fresh_store_reports_no_migration(client: TestClient) -> None:
    body = client.get("/api/prefs").json()
    assert body["migration"] == NONE and body["prefs"] == {} and isinstance(body["server_time"], int)


def test_the_first_legacy_import_is_recorded_and_survives_every_later_write(client: TestClient) -> None:
    out = _import(client, {"watchlist": '["TCS"]', "pins": '["desk"]', "bad key!": "x"}, LEGACY)
    assert sorted(out["imported"]) == ["pins", "watchlist"]
    m = _migration(client)
    assert m["legacy_origin"] == LEGACY and m["legacy_keys"] == 2 and m["inferred"] is False
    assert abs(m["legacy_import_at"] - out["server_time"]) < 60_000
    recorded = dict(m)
    # deliberate writes from the app rewrite the per-record provenance ...
    assert client.put("/api/prefs/watchlist", json={"value": '["INFY"]', "updated_at": out["server_time"] + 10,
                                                    "origin": APP}).status_code == 200
    assert client.delete("/api/prefs/pins", params={"updated_at": out["server_time"] + 20}).status_code == 200
    records = client.get("/api/prefs").json()["prefs"]
    assert records["watchlist"]["origin"] == APP and records["pins"]["deleted"] is True
    # ... but never the migration block
    assert _migration(client) == recorded


def test_only_the_first_legacy_import_counts(client: TestClient) -> None:
    _import(client, {"watchlist": '["TCS"]'}, LEGACY)
    first = _migration(client)
    _import(client, {"recents": '["WEI"]', "pins": "[]"}, "http://127.0.0.1:3000")      # a second old browser
    assert _migration(client) == first


def test_provisional_imports_and_empty_or_invalid_legacy_imports_record_nothing(client: TestClient) -> None:
    _import(client, {"watchlist": "[]"}, APP, provisional=True)                       # the app's own defaults
    assert _migration(client) == NONE
    r = client.post("/api/prefs/import", json={"items": {}, "origin": LEGACY})
    assert r.status_code == 200 and _migration(client) == NONE
    _import(client, {"bad key!": "x", "k": 5}, LEGACY)                                  # nothing valid in it
    assert _migration(client) == NONE
    out = _import(client, {"watchlist": '["TCS"]'}, LEGACY)                            # replaces the provisional []
    assert out["imported"] == ["watchlist"]
    assert _migration(client)["legacy_keys"] == 1


def test_a_legacy_import_that_fills_nothing_is_still_the_migration(client: TestClient) -> None:
    assert client.put("/api/prefs/watchlist", json={"value": '["INFY"]', "updated_at": 1000, "origin": APP}).status_code == 200
    out = _import(client, {"watchlist": '["TCS"]'}, LEGACY)
    assert out["imported"] == [] and out["skipped"] == ["watchlist"]
    m = _migration(client)
    assert m["legacy_origin"] == LEGACY and m["legacy_keys"] == 0 and m["legacy_import_at"] is not None


def test_a_store_migrated_before_k2_is_backfilled_once(db_path: Path, client: TestClient) -> None:
    # a v1 store written by the pre-K2 ui-api: no meta table, two records from the old :3000 browser
    con = sqlite3.connect(db_path)
    con.execute("""CREATE TABLE prefs (key TEXT PRIMARY KEY, value TEXT, updated_at INTEGER NOT NULL,
                   deleted INTEGER NOT NULL DEFAULT 0, bytes INTEGER NOT NULL DEFAULT 0,
                   provisional INTEGER NOT NULL DEFAULT 0, origin TEXT, server_at INTEGER NOT NULL) WITHOUT ROWID""")
    rows = [("watchlist", '["TCS"]', 5, 0, 7, 0, LEGACY, 2000), ("pins", "[]", 5, 0, 2, 0, LEGACY, 1500),
            ("recents", "[]", 5, 0, 2, 1, LEGACY, 1000),            # provisional: not evidence
            ("old", None, 5, 1, 0, 0, LEGACY, 900),                 # tombstone: not evidence
            ("tickets", "[]", 5, 0, 2, 0, APP, 800)]                # written in the app
    con.executemany("INSERT INTO prefs VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    con.execute("PRAGMA user_version=1")
    con.commit()
    con.close()
    m = _migration(client)
    assert m == {"legacy_import_at": 1500, "legacy_origin": LEGACY, "legacy_keys": 2, "inferred": True}
    _import(client, {"newkey": "1"}, "http://localhost:3000")       # a later legacy import does not replace it
    assert _migration(client) == m
    prefs.close_all()                                                 # reopen: the backfill does not run again
    con = sqlite3.connect(db_path)
    con.execute("DELETE FROM meta WHERE k = ?", (prefs.META_MIGRATION,))
    con.commit()
    con.close()
    assert _migration(client) == NONE


def test_a_store_without_legacy_records_is_not_backfilled(db_path: Path, client: TestClient) -> None:
    assert client.put("/api/prefs/watchlist", json={"value": "[]", "updated_at": 1, "origin": APP}).status_code == 200
    prefs.close_all()
    assert _migration(client) == NONE


def test_the_meta_table_leaves_the_schema_version_alone(db_path: Path, client: TestClient) -> None:
    """A pre-K2 ui-api (rollback) must still open the file: user_version stays 1, prefs table unchanged."""
    _import(client, {"watchlist": '["TCS"]'}, LEGACY)
    con = sqlite3.connect(db_path)
    assert con.execute("PRAGMA user_version").fetchone()[0] == prefs.SCHEMA_VERSION == 1
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert tables == {"prefs", "meta"}
    con.close()


@pytest.mark.parametrize("origin, legacy", [
    ("http://localhost:3000", True), ("https://127.0.0.1:3000", True), ("http://127.0.0.1:8010", False),
    ("http://localhost", False), ("tauri://localhost", False), ("", False), (None, False), ("http://[::1]:3000", True),
    ("garbage", False),
])
def test_legacy_origin_rule_matches_the_ui(origin: object, legacy: bool) -> None:
    assert prefs.is_legacy_browser_origin(origin) is legacy


def test_a_corrupt_migration_row_reads_as_no_migration(db_path: Path, client: TestClient) -> None:
    _import(client, {"watchlist": '["TCS"]'}, LEGACY)
    prefs.close_all()
    con = sqlite3.connect(db_path)
    con.execute("UPDATE meta SET v = ? WHERE k = ?", ("{not json", prefs.META_MIGRATION))
    con.commit()
    con.close()
    assert _migration(client) == NONE

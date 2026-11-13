"""F1.3 — nightly backup: snapshot-sourced, verified, rotated; zstd optional (fixture DB).

Plus the settings store (ui_prefs.sqlite, desktop review C2-reliability-ops-06): online backup, verified, same
rotation. Every test runs against temp dirs; the autouse fixture points PREFS_DB at a temp path so no test
ever reads the live data/ui_prefs.sqlite or writes data/backups.
"""
# ruff: noqa: DTZ001, DTZ005, DTZ007 - backup names are local calendar dates (naive by design, like db_backup)
import builtins
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import build_evening_snapshot as snap
import db_backup

PREFS_SCHEMA = """CREATE TABLE prefs (key TEXT PRIMARY KEY, value TEXT, updated_at INTEGER NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0, bytes INTEGER NOT NULL DEFAULT 0, provisional INTEGER NOT NULL DEFAULT 0,
    origin TEXT, server_at INTEGER NOT NULL) WITHOUT ROWID"""


@pytest.fixture(autouse=True)
def _isolated_prefs(tmp_path, monkeypatch):
    monkeypatch.setenv("PREFS_DB", str(tmp_path / "no-store" / "ui_prefs.sqlite"))
    # the other small stores too: no test ever reads the live data/*.sqlite
    monkeypatch.setenv("ALERTS_DB", str(tmp_path / "no-store" / "alerts.sqlite"))
    monkeypatch.setenv("JOB_QUEUE_DB", str(tmp_path / "no-store" / "job_queue.sqlite"))
    monkeypatch.setenv("ASK_AUDIT_DB", str(tmp_path / "no-store" / "ask_audit.sqlite"))


def make_store(path: Path, n: int = 3) -> sqlite3.Connection:
    """A WAL-mode store like ui-api's (schema v1). Returns the OPEN connection: its last commit stays in -wal."""
    con = sqlite3.connect(str(path), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA wal_autocheckpoint=0")       # keep every commit in the -wal, like a busy ui-api
    con.execute(PREFS_SCHEMA)
    con.execute("PRAGMA user_version=1")
    for i in range(n):
        con.execute("INSERT INTO prefs VALUES (?, ?, ?, 0, 1, 0, 'http://localhost:3000', ?)", (f"k{i}", "v", i, i))
    con.execute("INSERT INTO prefs VALUES ('gone', NULL, 9, 1, 0, 0, NULL, 9)")  # a tombstone
    return con


@pytest.fixture()
def world(tmp_path):
    db = tmp_path / "market.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE nse_bhavcopy AS SELECT range AS x FROM range(5)")
    con.close()
    pointer = tmp_path / "pointer.json"
    snap.build(db=db, dest_dir=tmp_path / "snaps", pointer=pointer)
    return {"db": db, "pointer": pointer, "dest": tmp_path / "backups"}


def test_backup_prefers_snapshot_verifies_and_writes_meta(world):
    meta = db_backup.run(db=world["db"], dest=world["dest"], pointer=world["pointer"])
    assert meta["src"] == "evening_snapshot" and meta["rows"] == 5
    assert meta["prefs"]["skipped"] == "absent"          # no settings store yet: skipped, not an error
    out = world["dest"] / meta["file"]
    assert out.exists() and len(meta["sha256"]) == 64
    saved = json.loads((world["dest"] / f"market-{datetime.now():%Y%m%d}.meta.json").read_text())
    assert saved["rows"] == 5 and saved["sha256"] == meta["sha256"]


def test_backup_falls_back_to_private_copy_without_pointer(world, tmp_path):
    meta = db_backup.run(db=world["db"], dest=world["dest"], pointer=tmp_path / "absent.json")
    assert meta["src"] == "private_copy" and meta["rows"] == 5


def test_zstd_absent_falls_back_to_plain_copy(world, monkeypatch):
    real_import = builtins.__import__

    def no_zstd(name, *a, **k):
        if name == "zstandard":
            raise ImportError("no zstd in this env")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_zstd)
    meta = db_backup.run(db=world["db"], dest=world["dest"], pointer=world["pointer"])
    assert meta["compressed"] is False and meta["file"].endswith(".duckdb")
    con = duckdb.connect(str(world["dest"] / meta["file"]), read_only=True)
    assert con.execute("SELECT COUNT(*) FROM nse_bhavcopy").fetchone()[0] == 5
    con.close()


def test_rotation_keeps_7_daily_plus_sunday_weeklies(tmp_path):
    dest = tmp_path
    today = datetime(2026, 10, 15)
    # 30 days of backups; Sundays: Oct 11, Oct 4, Sep 27, Sep 20, Sep 13 (5 sundays)
    for i in range(30):
        d = today - timedelta(days=i)
        (dest / f"market-{d:%Y%m%d}.duckdb").write_bytes(b"x")
        (dest / f"market-{d:%Y%m%d}.meta.json").write_text("{}")
    removed = db_backup.rotate(dest, today=today)
    kept = sorted(p.name for p in dest.glob("market-*.duckdb"))
    assert removed and all(n.startswith("market-") for n in removed)
    kept_dates = [datetime.strptime(n.split("-")[1].split(".")[0], "%Y%m%d") for n in kept]
    dailies = [d for d in kept_dates if (today - d).days < 7]
    older = [d for d in kept_dates if (today - d).days >= 7]
    assert len(dailies) == 7
    # last 4 Sundays = Oct 11 (inside the daily window) + Oct 4, Sep 27, Sep 20 beyond it
    assert all(d.weekday() == 6 for d in older) and len(older) == 3
    assert len(removed) == 30 - len(kept)
    # meta files of removed backups are gone too
    assert len(list(dest.glob("market-*.meta.json"))) == len(kept)


# ── settings store (ui_prefs.sqlite) ─────────────────────────────────────────────────────────────────────

def test_prefs_online_backup_captures_wal_and_is_self_contained(tmp_path):
    db = tmp_path / "ui_prefs.sqlite"
    live = make_store(db)                               # stays open: the rows live in the -wal
    try:
        assert Path(str(db) + "-wal").stat().st_size > 0
        naive = tmp_path / "naive.sqlite"
        shutil.copy(db, naive)                          # what a plain cp does (no -wal)
        with sqlite3.connect(naive) as c:
            assert not c.execute("SELECT name FROM sqlite_master WHERE name = 'prefs'").fetchone(), \
                "a plain copy must miss the WAL-only data (otherwise this test proves nothing)"
        dest = tmp_path / "backups"
        meta = db_backup.backup_prefs(db, dest, "20261025")
        out = dest / "ui_prefs-20261025.sqlite"
        assert meta["keys"] == 4 and meta["live_keys"] == 3 and meta["user_version"] == 1
        assert meta["sha256"] == hashlib.sha256(out.read_bytes()).hexdigest() and meta["file"] == out.name
        assert json.loads((dest / "ui_prefs-20261025.meta.json").read_text())["sha256"] == meta["sha256"]
        assert sorted(p.name for p in dest.iterdir()) == ["ui_prefs-20261025.meta.json", "ui_prefs-20261025.sqlite"]
        with sqlite3.connect(out) as c:
            assert c.execute("PRAGMA journal_mode").fetchone()[0] == "delete"      # one file, no -wal needed
            assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert c.execute("SELECT COUNT(*) FROM prefs WHERE deleted = 0").fetchone()[0] == 3
        # the live store is untouched and still writable by its owner
        live.execute("INSERT INTO prefs VALUES ('k9', 'v', 10, 0, 1, 0, NULL, 10)")
        assert live.execute("SELECT COUNT(*) FROM prefs").fetchone()[0] == 5
    finally:
        live.close()


def test_prefs_backup_works_with_the_store_closed(tmp_path):
    db = tmp_path / "ui_prefs.sqlite"
    make_store(db, n=2).close()                         # ui-api stopped: checkpointed, no -wal/-shm
    meta = db_backup.backup_prefs(db, tmp_path / "b", "20261025")
    assert meta["live_keys"] == 2


def test_prefs_backup_failure_leaves_nothing_and_is_reported(tmp_path, world):
    bad = tmp_path / "ui_prefs.sqlite"
    bad.write_bytes(b"this is not a database" * 100)
    with pytest.raises(sqlite3.DatabaseError):
        db_backup.backup_prefs(bad, tmp_path / "b", "20261025")
    assert not [p for p in (tmp_path / "b").iterdir()], "no partial backup or temp file left behind"
    # in the nightly run a broken store never costs the DuckDB backup, but it is reported
    meta = db_backup.run(db=world["db"], dest=world["dest"], pointer=world["pointer"], prefs_db=bad)
    assert meta["rows"] == 5 and (world["dest"] / meta["file"]).exists()
    assert "DatabaseError" in meta["prefs"]["error"]


def test_main_exit_code_follows_the_prefs_backup(tmp_path, monkeypatch, capsys):
    db = tmp_path / "ui_prefs.sqlite"
    make_store(db).close()
    dest = tmp_path / "b"
    assert db_backup.main(["--prefs-only", "--dest", str(dest), "--prefs-db", str(db)]) == 0
    assert (dest / f"ui_prefs-{datetime.now():%Y%m%d}.sqlite").exists()
    assert '"live_keys": 3' in capsys.readouterr().out
    bad = tmp_path / "bad.sqlite"
    bad.write_bytes(b"x" * 4096)
    assert db_backup.main(["--prefs-only", "--dest", str(dest), "--prefs-db", str(bad)]) == 1
    assert "ui_prefs backup FAILED" in capsys.readouterr().err
    # full run: the DuckDB part succeeded, the settings part failed -> exit 1 (the controller alerts)
    monkeypatch.setattr(db_backup, "run", lambda **kw: {"file": "market-x.duckdb", "prefs": {"error": "boom"}})
    assert db_backup.main(["--dest", str(dest)]) == 1
    monkeypatch.setattr(db_backup, "run", lambda **kw: {"file": "market-x.duckdb", "prefs": {"skipped": "absent"}})
    assert db_backup.main(["--dest", str(dest)]) == 0


def test_rotation_counts_sundays_per_family(tmp_path):
    """Both families on the same 30 days keep the same 7 daily + 3 older Sundays (a combined count would
    give each family only 2 older Sundays)."""
    today = datetime(2026, 10, 15)
    for i in range(30):
        d = today - timedelta(days=i)
        (tmp_path / f"market-{d:%Y%m%d}.duckdb").write_bytes(b"x")
        (tmp_path / f"ui_prefs-{d:%Y%m%d}.sqlite").write_bytes(b"x")
        (tmp_path / f"ui_prefs-{d:%Y%m%d}.meta.json").write_text("{}")
    db_backup.rotate(tmp_path, today=today)
    market = sorted(p.name[7:15] for p in tmp_path.glob("market-*.duckdb"))
    prefs = sorted(p.name[9:17] for p in tmp_path.glob("ui_prefs-*.sqlite"))
    assert market == prefs and len(prefs) == 10
    assert len(list(tmp_path.glob("ui_prefs-*.meta.json"))) == 10


def test_stale_temp_copies_of_killed_runs_are_removed(tmp_path):
    db = tmp_path / "ui_prefs.sqlite"
    make_store(db).close()
    dest = tmp_path / "b"
    dest.mkdir()
    (dest / ".ui_prefs-20261024.sqlite.tmp-999999").write_bytes(b"partial")
    mine = dest / f".ui_prefs-20261024.sqlite.tmp-{os.getpid()}"   # a live pid: never touched
    mine.write_bytes(b"in progress")
    db_backup.backup_prefs(db, dest, "20261025")
    assert not (dest / ".ui_prefs-20261024.sqlite.tmp-999999").exists() and mine.exists()


def test_default_prefs_db_follows_prefs_db_env(monkeypatch, tmp_path):
    monkeypatch.setenv("PREFS_DB", str(tmp_path / "x.sqlite"))
    assert db_backup.default_prefs_db() == tmp_path / "x.sqlite"
    monkeypatch.delenv("PREFS_DB")
    assert db_backup.default_prefs_db() == ROOT / "data" / "ui_prefs.sqlite"


# ── job queue + ASK audit stores (F-24/F-31: same pattern as alerts) ─────────────────────────────────────


def make_job_queue_store(path: Path, n: int = 4) -> None:
    """A WAL store shaped like data-service's job_queue.sqlite (job_queue.py _SCHEMA, the counted columns)."""
    con = sqlite3.connect(str(path))
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("""CREATE TABLE jobs (job_id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
        attempt INTEGER NOT NULL DEFAULT 1, requeued INTEGER NOT NULL DEFAULT 0, submitted_at TEXT NOT NULL)""")
    for i in range(n):
        con.execute("INSERT INTO jobs VALUES (?, 'evening', 'done', 1, 0, ?)", (f"j{i}", f"2026-11-13T18:0{i}:00"))
    con.commit()
    con.close()


def make_ask_audit_store(path: Path, n: int = 2) -> None:
    """ASK's audit log (ask_engine.AUDIT_SCHEMA shape: ts, question, sql, rows_returned, model)."""
    con = sqlite3.connect(str(path))
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("""CREATE TABLE ask_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, question TEXT,
        sql TEXT, rows_returned INTEGER, model TEXT)""")
    for i in range(n):
        con.execute("INSERT INTO ask_audit (ts, question, sql, rows_returned, model) VALUES (?, ?, ?, ?, ?)",
                    (f"2026-11-13T18:0{i}:00+00:00", "how many rows?", "SELECT 1", 1, "direct-read"))
    con.commit()
    con.close()


def test_job_queue_backup_copies_counts_and_skips_absent(tmp_path):
    db = tmp_path / "job_queue.sqlite"
    make_job_queue_store(db, n=4)
    dest = tmp_path / "b"
    meta = db_backup.backup_job_queue(db, dest, "20261113")
    out = dest / "job_queue-20261113.sqlite"
    assert meta["jobs"] == 4 and meta["file"] == out.name and out.exists()
    assert meta["sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
    assert json.loads((dest / "job_queue-20261113.meta.json").read_text())["jobs"] == 4
    with sqlite3.connect(out) as c:
        assert c.execute("PRAGMA journal_mode").fetchone()[0] == "delete"      # self-contained single file
        assert c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 4
    # a missing store is quietly skipped, never an error — and nothing is written
    absent = db_backup.backup_job_queue(tmp_path / "nope.sqlite", dest, "20261114")
    assert absent == {"skipped": "absent", "src": str(tmp_path / "nope.sqlite")}
    assert not (dest / "job_queue-20261114.sqlite").exists()


def test_ask_audit_backup_copies_counts_and_skips_absent(tmp_path):
    db = tmp_path / "ask_audit.sqlite"
    make_ask_audit_store(db, n=2)
    dest = tmp_path / "b"
    meta = db_backup.backup_ask_audit(db, dest, "20261113")
    out = dest / "ask_audit-20261113.sqlite"
    assert meta["questions"] == 2 and meta["file"] == out.name and out.exists()
    assert json.loads((dest / "ask_audit-20261113.meta.json").read_text())["sha256"] == meta["sha256"]
    with sqlite3.connect(out) as c:
        assert c.execute("SELECT COUNT(*) FROM ask_audit").fetchone()[0] == 2
    absent = db_backup.backup_ask_audit(tmp_path / "nope.sqlite", dest, "20261114")
    assert absent["skipped"] == "absent"
    assert not (dest / "ask_audit-20261114.sqlite").exists()


def test_run_includes_both_new_families_and_rotation_covers_them(world, tmp_path):
    jq = tmp_path / "job_queue.sqlite"
    aa = tmp_path / "ask_audit.sqlite"
    make_job_queue_store(jq, n=3)
    make_ask_audit_store(aa, n=1)
    meta = db_backup.run(db=world["db"], dest=world["dest"], pointer=world["pointer"],
                         job_queue_db=jq, ask_audit_db=aa)
    assert meta["job_queue"]["jobs"] == 3 and meta["ask_audit"]["questions"] == 1
    stamp = f"{datetime.now():%Y%m%d}"
    assert (world["dest"] / f"job_queue-{stamp}.sqlite").exists()
    assert (world["dest"] / f"ask_audit-{stamp}.sqlite").exists()
    # with no stores at all (fresh install): quietly skipped, exit path unchanged
    meta2 = db_backup.run(db=world["db"], dest=world["dest"], pointer=world["pointer"])
    assert meta2["job_queue"]["skipped"] == "absent" and meta2["ask_audit"]["skipped"] == "absent"
    # the new families rotate like the others (per-family Sundays)
    dest = tmp_path / "rot"
    dest.mkdir()
    today = datetime(2026, 10, 15)
    for i in range(30):
        d = today - timedelta(days=i)
        (dest / f"job_queue-{d:%Y%m%d}.sqlite").write_bytes(b"x")
        (dest / f"ask_audit-{d:%Y%m%d}.sqlite").write_bytes(b"x")
        (dest / f"ask_audit-{d:%Y%m%d}.meta.json").write_text("{}")
    db_backup.rotate(dest, today=today)
    assert len(list(dest.glob("job_queue-*.sqlite"))) == 10            # 7 daily + 3 older Sundays
    assert len(list(dest.glob("ask_audit-*.sqlite"))) == 10
    assert len(list(dest.glob("ask_audit-*.meta.json"))) == 10


def test_main_reports_job_queue_and_ask_audit_failures(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(db_backup, "run",
                        lambda **kw: {"file": "market-x.duckdb", "prefs": {"skipped": "absent"},
                                      "alerts": {"skipped": "absent"}, "job_queue": {"error": "boom"},
                                      "ask_audit": {"skipped": "absent"}})
    assert db_backup.main(["--dest", str(tmp_path)]) == 1
    assert "job_queue backup FAILED" in capsys.readouterr().err
    monkeypatch.setattr(db_backup, "run",
                        lambda **kw: {"file": "market-x.duckdb", "prefs": {}, "alerts": {},
                                      "job_queue": {}, "ask_audit": {"error": "bad file"}})
    assert db_backup.main(["--dest", str(tmp_path)]) == 1
    assert "ask_audit backup FAILED" in capsys.readouterr().err


def test_default_store_paths_follow_env(monkeypatch, tmp_path):
    monkeypatch.setenv("JOB_QUEUE_DB", str(tmp_path / "q.sqlite"))
    assert db_backup.default_job_queue_db() == tmp_path / "q.sqlite"
    monkeypatch.delenv("JOB_QUEUE_DB")
    assert db_backup.default_job_queue_db() == ROOT / "data" / "job_queue.sqlite"
    monkeypatch.setenv("ASK_AUDIT_DB", str(tmp_path / "a.sqlite"))
    assert db_backup.default_ask_audit_db() == tmp_path / "a.sqlite"
    monkeypatch.delenv("ASK_AUDIT_DB")
    assert db_backup.default_ask_audit_db() == ROOT / "data" / "ask_audit.sqlite"

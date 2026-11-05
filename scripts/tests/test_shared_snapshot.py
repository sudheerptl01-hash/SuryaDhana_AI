"""F2.3/S3 — evening snapshot: build/verify/pointer/prune/current/orphans (fixture DB)."""
import json
import os
import sys
import time
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import build_evening_snapshot as snap  # noqa: E402


@pytest.fixture()
def world(tmp_path):
    db = tmp_path / "market.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE nse_bhavcopy AS SELECT 1 AS x UNION ALL SELECT 2")
    con.close()
    return {"db": db, "dest": tmp_path / "snaps", "pointer": tmp_path / "pointer.json"}


def test_build_verifies_writes_pointer_and_matching_wal_name(world):
    wal = Path(str(world["db"]) + ".wal")
    wal.write_bytes(b"walbytes")
    meta = snap.build(db=world["db"], dest_dir=world["dest"], pointer=world["pointer"])
    p = Path(meta["path"])
    assert p.exists() and p.name.startswith("evening-") and meta["rows"] == 2
    assert p.with_suffix(".duckdb.wal").exists()                    # minor 9: same stem
    saved = json.loads(world["pointer"].read_text())
    assert saved["path"] == str(p) and saved["db_mtime_ns"] == world["db"].stat().st_mtime_ns


def test_prune_keeps_two_and_current_honours_staleness(world, monkeypatch):
    # distinct stamps per build (same-minute runs would otherwise collide on the filename)
    import datetime as _dt
    stamps = iter(["20260101-0001", "20260101-0002", "20260101-0003"])
    for _ in range(3):
        stamp = next(stamps)
        monkeypatch.setattr(snap, "datetime", type("D", (), {
            "now": staticmethod(lambda s=stamp: type("T", (), {
                "strftime": staticmethod(lambda fmt, s=s: s),
                "isoformat": staticmethod(lambda timespec=None, s=s: s)})())}))
        time.sleep(0.02)
        snap.build(db=world["db"], dest_dir=world["dest"], pointer=world["pointer"])
    monkeypatch.setattr(snap, "datetime", _dt.datetime)
    snaps = list(world["dest"].glob("evening-*.duckdb"))
    assert len(snaps) <= 2                                           # keep=2
    # current(): fresh + matching mtime → path
    assert snap.current(pointer=world["pointer"], db=world["db"]) is not None
    # source DB changes → strict current() refuses, allow_stale accepts
    con = duckdb.connect(str(world["db"]))
    con.execute("INSERT INTO nse_bhavcopy VALUES (3)")
    con.close()
    os.utime(world["db"], ns=(time.time_ns(), time.time_ns()))
    assert snap.current(pointer=world["pointer"], db=world["db"]) is None
    assert snap.current(pointer=world["pointer"], db=world["db"], allow_stale=True) is not None
    # too old → None either way
    old = Path(json.loads(world["pointer"].read_text())["path"])
    past = time.time() - 48 * 3600
    os.utime(old, (past, past))
    assert snap.current(pointer=world["pointer"], db=world["db"], allow_stale=True) is None


def test_orphan_tmp_cleanup_removes_only_old(world):
    world["dest"].mkdir(parents=True)
    old = world["dest"] / "evening-x.duckdb.tmp"
    new = world["dest"] / "evening-y.duckdb.tmp"
    old.write_bytes(b"1")
    new.write_bytes(b"1")
    past = time.time() - 7200
    os.utime(old, (past, past))
    assert snap.cleanup_orphan_tmp(world["dest"]) == 1
    assert not old.exists() and new.exists()


def test_build_retries_on_torn_copy(world, monkeypatch):
    calls = {"n": 0}
    real = snap._fast_copy

    def tearing(src, dest):
        real(src, dest)
        if calls["n"] == 0 and str(src).endswith(".duckdb"):
            calls["n"] += 1
            os.utime(src, ns=(time.time_ns(), time.time_ns()))       # source "changed" mid-copy
    monkeypatch.setattr(snap, "_fast_copy", tearing)
    meta = snap.build(db=world["db"], dest_dir=world["dest"], pointer=world["pointer"])
    assert Path(meta["path"]).exists() and calls["n"] == 1           # succeeded on retry

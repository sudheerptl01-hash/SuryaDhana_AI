"""Wave 0.1 code half: ``scripts/db_backup.py --offsite`` copies tonight's files to the owner's target (O-T1), verifies the
DuckDB copy by sha256, keeps the same rotation there, and never harms the local backup. Negative controls: no target →
skipped (exit 0); a target that is not mounted → exit 1 with the local backup intact; a tampered off-site copy fails
the sha256 check. Temp dirs only; PREFS_DB points at a temp path."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import build_evening_snapshot as snap  # noqa: E402
import db_backup  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("PREFS_DB", str(tmp_path / "no-store" / "ui_prefs.sqlite"))
    monkeypatch.delenv("OFFSITE_BACKUP_DIR", raising=False)


@pytest.fixture()
def world(tmp_path, monkeypatch):
    """A 7-row fixture DB + its evening snapshot. ``main()`` is pointed at it too (it defaults to the LIVE
    data/market.duckdb and pointer, which a test must never read or clone)."""
    db = tmp_path / "market.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE nse_bhavcopy AS SELECT range AS x FROM range(7)")
    con.close()
    pointer = tmp_path / "pointer.json"
    snap.build(db=db, dest_dir=tmp_path / "snaps", pointer=pointer)
    real_run = db_backup.run
    monkeypatch.setattr(db_backup, "run", lambda **kw: real_run(**{"db": db, "pointer": pointer, **kw}))
    return {"db": db, "pointer": pointer, "dest": tmp_path / "backups", "offsite": tmp_path / "offsite"}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_offsite_copy_is_verified_and_rotated(world):
    meta = db_backup.run(db=world["db"], dest=world["dest"], pointer=world["pointer"])
    world["offsite"].mkdir()
    stale = world["offsite"] / "market-20200101.duckdb"           # an old off-site file: rotation removes it
    stale.write_bytes(b"old")
    (world["offsite"] / "market-20200101.meta.json").write_text("{}")
    out = db_backup.copy_offsite(world["dest"], meta, world["offsite"])
    assert out["sha256_verified"] is True and out["target"] == str(world["offsite"])
    assert meta["file"] in out["files"] and f"market-{datetime.now():%Y%m%d}.meta.json" in out["files"]  # noqa: DTZ005
    assert _sha(world["offsite"] / meta["file"]) == meta["sha256"]
    assert "market-20200101.duckdb" in out["rotated"] and not stale.exists()
    assert not list(world["offsite"].glob(".*.tmp-*")), "no temp file left behind"


def test_cli_flag_and_env_default(world, monkeypatch, capsys):
    rc = db_backup.main(["--dest", str(world["dest"]), "--offsite", str(world["offsite"])])
    assert rc == 0
    result = json.loads(capsys.readouterr().out.split("RESULT ", 1)[1])
    assert result["offsite"]["sha256_verified"] is True
    # bare --offsite reads OFFSITE_BACKUP_DIR; unset → skipped, still exit 0 (negative control)
    rc = db_backup.main(["--dest", str(world["dest"]), "--offsite"])
    assert rc == 0
    result = json.loads(capsys.readouterr().out.split("RESULT ", 1)[1])
    assert result["offsite"]["skipped"] == "unset" and "O-T1" in result["offsite"]["hint"]
    target2 = world["offsite"].parent / "offsite2"
    monkeypatch.setenv("OFFSITE_BACKUP_DIR", str(target2))
    rc = db_backup.main(["--dest", str(world["dest"]), "--offsite"])
    assert rc == 0 and (target2 / json.loads(capsys.readouterr().out.split("RESULT ", 1)[1])["file"]).exists()
    # without the flag nothing is copied even when the env is set (the controller opts in explicitly)
    rc = db_backup.main(["--dest", str(world["dest"])])
    assert rc == 0 and "offsite" not in json.loads(capsys.readouterr().out.split("RESULT ", 1)[1])


def test_unmounted_target_exits_1_and_keeps_the_local_backup(world, capsys):
    missing = world["offsite"] / "volume" / "not-mounted"          # parent missing too: never auto-created
    rc = db_backup.main(["--dest", str(world["dest"]), "--offsite", str(missing)])
    assert rc == 1
    out, err = capsys.readouterr()
    result = json.loads(out.split("RESULT ", 1)[1])
    assert "not mounted" in result["offsite"]["error"] and "off-site copy FAILED" in err
    assert (world["dest"] / result["file"]).exists() and result["rows"] == 7
    assert not missing.exists()


def test_sha256_mismatch_is_an_error(world, monkeypatch):
    meta = db_backup.run(db=world["db"], dest=world["dest"], pointer=world["pointer"])
    world["offsite"].mkdir()

    def corrupt_copy(src: Path, dest: Path) -> None:
        dest.write_bytes(b"corrupted")

    monkeypatch.setattr(snap, "_fast_copy", corrupt_copy)
    with pytest.raises(RuntimeError, match="sha256 mismatch"):
        db_backup.copy_offsite(world["dest"], meta, world["offsite"])


def test_offsite_target_resolution(monkeypatch):
    assert db_backup.offsite_target(None) is None
    assert db_backup.offsite_target("") is None
    monkeypatch.setenv("OFFSITE_BACKUP_DIR", "/Volumes/Backup/sd")
    assert db_backup.offsite_target("") == Path("/Volumes/Backup/sd")
    assert db_backup.offsite_target("/tmp/x") == Path("/tmp/x")

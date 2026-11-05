"""
Read-snapshot refresh policy (snapshot.py).

Hermetic: the "live DB" is a small file in tmp_path; the snapshot only copies bytes,
so no DuckDB is needed. A fake clock drives the TTL.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from snapshot import ReadSnapshot  # noqa: E402


class Clock:
    def __init__(self) -> None:
        self.t = 1_000.0

    def __call__(self) -> float:
        return self.t


def _setup(tmp_path, ttl=600.0):
    src = tmp_path / "market.duckdb"
    src.write_bytes(b"v1")
    clock = Clock()
    snap = ReadSnapshot(lambda: str(src), directory=str(tmp_path / "snap"), ttl=ttl, grace=0.0, clock=clock)
    return src, clock, snap


def _touch(src, data: bytes) -> None:
    src.write_bytes(data)
    st = os.stat(src)
    os.utime(src, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))  # guarantee a new mtime


def test_unchanged_source_is_never_recopied_even_when_old(tmp_path):
    src, clock, snap = _setup(tmp_path)
    first = snap.get()
    clock.t += 10 * 3600            # far past the TTL: age alone must not trigger a copy
    assert snap.get() == first
    assert snap.builds == 1
    assert open(first, "rb").read() == b"v1"


def test_changed_source_within_ttl_serves_current_copy(tmp_path):
    src, clock, snap = _setup(tmp_path)
    first = snap.get()
    _touch(src, b"v2")
    clock.t += 60
    assert snap.get() == first
    assert snap.builds == 1


def test_changed_source_after_ttl_refreshes_in_background(tmp_path):
    src, clock, snap = _setup(tmp_path)
    first = snap.get()
    _touch(src, b"v2")
    clock.t += 601
    assert snap.get() == first      # served immediately, no blocking copy in the request
    snap.wait_for_refresh(5)
    second = snap.get()
    assert second != first and open(second, "rb").read() == b"v2"
    assert snap.builds == 2


def test_fresh_read_blocks_until_snapshot_matches_source(tmp_path):
    src, clock, snap = _setup(tmp_path)
    snap.get()
    _touch(src, b"v2")
    path = snap.get(fresh=True)
    assert open(path, "rb").read() == b"v2"


def test_wal_is_copied_and_its_changes_are_detected(tmp_path):
    src, clock, snap = _setup(tmp_path)
    wal = tmp_path / "market.duckdb.wal"
    wal.write_bytes(b"w1")
    path = snap.get()
    assert open(f"{path}.wal", "rb").read() == b"w1"
    _touch(wal, b"w1w2")
    assert open(f"{snap.get(fresh=True)}.wal", "rb").read() == b"w1w2"


def test_restarted_process_adopts_existing_snapshot(tmp_path):
    src, clock, snap = _setup(tmp_path)
    first = snap.get()
    again = ReadSnapshot(lambda: str(src), directory=str(tmp_path / "snap"), clock=clock)
    assert again.get() == first
    assert again.builds == 0


def test_invalidate_forces_rebuild_and_old_versions_are_cleaned(tmp_path):
    src, clock, snap = _setup(tmp_path)
    first = snap.get()
    snap.invalidate(first)
    second = snap.get()
    assert second != first and not os.path.exists(first)
    _touch(src, b"v3")
    third = snap.get(fresh=True)
    time.sleep(0.2)                 # grace=0 timer deletes the superseded version
    assert not os.path.exists(second) and os.path.exists(third)

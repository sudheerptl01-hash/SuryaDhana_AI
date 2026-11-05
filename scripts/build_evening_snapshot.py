#!/usr/bin/env python
"""Shared evening snapshot of the DuckDB (Bloomberg program F2.3/S3, amendments A7 + minor 9).

One consistent copy per evening, built at 19:20 IST by master-controller, consumed by the
19:45 news job, the 19:50 paper shadow and the 02:15 backup — instead of each making its own
4.7 GB private copy. On APFS the copy is a clone (~1 s, no physical duplication).

    python scripts/build_evening_snapshot.py            # build + verify + pointer + prune
    python scripts/build_evening_snapshot.py --current  # print tonight's path (or nothing)

Pointer file: data/.evening_snapshot.json  {path, created_at, db_mtime_ns, db_size, rows}
Consumers NEVER read controller state — they read SURYA_SNAPSHOT_PATH (injected at job-spawn
time from this pointer, amendment A7) or the pointer file directly, and silently fall back to
their old private-copy behaviour when absent or stale.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "market.duckdb"
DEST_DIR = ROOT / "data" / "snapshots" / "evening"
POINTER = ROOT / "data" / ".evening_snapshot.json"
KEEP = 2                       # tonight's + yesterday's
ORPHAN_TMP_AGE_S = 3600
VERIFY_TABLE = "nse_bhavcopy"


def _signature(path: Path) -> tuple[int, int]:
    st = path.stat()
    return st.st_mtime_ns, st.st_size


def _fast_copy(src: Path, dest: Path) -> None:
    """APFS clone when available (`cp -c`: copy-on-write, ~1 s for 4.7 GB), else plain copy."""
    try:
        subprocess.run(["cp", "-c", str(src), str(dest)], check=True, capture_output=True, timeout=600)
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        shutil.copy2(src, dest)


def _verify(db_path: Path) -> int:
    import duckdb
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        return int(con.execute(f"SELECT COUNT(*) FROM {VERIFY_TABLE}").fetchone()[0])
    finally:
        con.close()


def cleanup_orphan_tmp(dest_dir: Path = DEST_DIR, max_age_s: int = ORPHAN_TMP_AGE_S) -> int:
    """Remove interrupted-copy leftovers (*.tmp*) older than an hour; returns count removed."""
    n = 0
    now = time.time()
    for p in dest_dir.glob("*.tmp*"):
        try:
            if now - p.stat().st_mtime > max_age_s:
                p.unlink()
                n += 1
        except OSError:
            pass
    return n


def prune(dest_dir: Path = DEST_DIR, keep: int = KEEP) -> list[str]:
    """Keep the newest `keep` evening-*.duckdb (with their .wal); delete the rest."""
    snaps = sorted(dest_dir.glob("evening-*.duckdb"), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = []
    for old in snaps[keep:]:
        for p in (old, old.with_suffix(".duckdb.wal")):
            if p.exists():
                p.unlink()
                removed.append(p.name)
    return removed


def build(db: Path = DB, dest_dir: Path = DEST_DIR, pointer: Path = POINTER, keep: int = KEEP) -> dict:
    """Copy → verify → publish. Torn-copy safe: the source signature must match before and
    after the copy, else retry once (the DB is written by EOD jobs; 19:20 is quiet but not
    guaranteed). The WAL lands beside the snapshot under the SAME stem (minor 9: DuckDB pairs
    by name)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    cleanup_orphan_tmp(dest_dir)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    final = dest_dir / f"evening-{stamp}.duckdb"
    tmp = dest_dir / f"evening-{stamp}.duckdb.tmp"
    wal_src = Path(str(db) + ".wal")

    last_err = "unknown"
    for attempt in (1, 2):
        sig_before = _signature(db)
        _fast_copy(db, tmp)
        wal_tmp = dest_dir / f"evening-{stamp}.duckdb.wal.tmp"
        if wal_src.exists():
            _fast_copy(wal_src, wal_tmp)
        if _signature(db) != sig_before:
            last_err = "source changed during copy"
            tmp.unlink(missing_ok=True)
            wal_tmp.unlink(missing_ok=True)
            continue
        if wal_tmp.exists():
            wal_tmp.replace(dest_dir / f"evening-{stamp}.duckdb.wal")   # minor 9: matching stem
        tmp.replace(final)
        try:
            rows = _verify(final)
        except Exception as exc:  # noqa: BLE001 — verification failure = unusable snapshot
            last_err = f"verify failed: {exc}"
            final.unlink(missing_ok=True)
            (dest_dir / f"evening-{stamp}.duckdb.wal").unlink(missing_ok=True)
            continue
        if rows <= 0:
            last_err = "verify: 0 rows"
            continue
        meta = {"path": str(final), "created_at": datetime.now().isoformat(timespec="seconds"),
                "db_mtime_ns": sig_before[0], "db_size": sig_before[1], "rows": rows}
        pointer.write_text(json.dumps(meta, indent=1))
        meta["pruned"] = prune(dest_dir, keep)
        return meta
    raise RuntimeError(f"evening snapshot failed after 2 attempts: {last_err}")


def current(max_age_h: float = 24.0, allow_stale: bool = False,
            pointer: Path = POINTER, db: Path = DB) -> str | None:
    """Tonight's snapshot path, or None. Strict mode additionally requires the live DB to be
    unchanged since the snapshot (same mtime) — right for same-evening consumers (19:45/19:50);
    `allow_stale=True` accepts a changed source (right for the 02:15 backup, which knowingly
    lags the 20:30/20:45 ingests — see RUNBOOK)."""
    try:
        meta = json.loads(pointer.read_text())
        path = Path(meta["path"])
        if not path.exists():
            return None
        age_h = (time.time() - path.stat().st_mtime) / 3600
        if age_h > max_age_h:
            return None
        if not allow_stale and db.exists() and db.stat().st_mtime_ns != meta.get("db_mtime_ns"):
            return None
        return str(path)
    except (OSError, ValueError, KeyError):
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Build or query the shared evening DuckDB snapshot")
    ap.add_argument("--current", action="store_true", help="print tonight's snapshot path if fresh")
    ap.add_argument("--allow-stale", action="store_true")
    args = ap.parse_args()
    if args.current:
        p = current(allow_stale=args.allow_stale)
        if p:
            print(p)
            return
        sys.exit(1)
    t0 = time.time()
    meta = build()
    print(f"RESULT {json.dumps({**meta, 'seconds': round(time.time() - t0, 2)})}")


if __name__ == "__main__":
    main()

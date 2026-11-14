#!/usr/bin/env python
"""ASK analyst snapshot re-cut (R5-ASK2; F4 PENDING §6 "snapshot re-cut after iv_eod").

The 19:20 shared evening snapshot is cut BEFORE the 20:30 pass lands iv_eod, so ASK answers IV questions a
session behind (labelled amber, but real — F4 "Data freshness" §3). The 19:20 cut itself is FROZEN: the
19:50 S1 shadow and the 02:15 backup read it, so it is never re-cut. This script cuts a SECOND copy for ASK
only, at a STABLE path the static `ASK_SNAPSHOT_DB` env var can name:

    data/snapshots/ask/ask_evening.duckdb

Scheduled by the controller job `snapshot_ask_refresh` at 21:40 IST Mon–Fri (after the 20:30
nse_positions_catchup runs iv_eod LAST — a PM patch request adds the job + the .env line; see
~/.suryadhana_pm_scratch/final_round_20261113/r5-ask2/patches/). Outside both restart freeze windows; it
fetches nothing and restarts nothing — one APFS clone + verify + atomic replace.

Recipe (same as scripts/build_evening_snapshot.py): APFS clone (`cp -c`, ~1 s for 5.4 GB, no physical
duplication), torn-copy retry by source signature (a checkpoint during the copy rewrites the main file),
verify by opening the copy read-only and counting rows, then one atomic `os.replace` — a reader mid-query
keeps its open POSIX handle; the next ASK query sees the fresh file (ask_engine keys every cache on
path + mtime + size, so the swap can never serve a stale catalog or as-of).

    python scripts/build_ask_snapshot.py                 # cut + verify + swap; prints one summary line
    python scripts/build_ask_snapshot.py --src X --dest Y --verify-table T   # tests / ops override
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SRC = ROOT / "data" / "market.duckdb"
DEFAULT_DEST = ROOT / "data" / "snapshots" / "ask" / "ask_evening.duckdb"
DEFAULT_VERIFY_TABLE = "nse_bhavcopy"
META_SUFFIX = ".meta.json"       # written beside the dest: created_at, rows, src signature (ops evidence)


def _signature(path: Path) -> tuple[int, int]:
    st = path.stat()
    return st.st_mtime_ns, st.st_size


def _fast_copy(src: Path, dest: Path) -> None:
    """APFS clone when available (`cp -c`: copy-on-write), else plain copy (same as build_evening_snapshot)."""
    try:
        subprocess.run(["cp", "-c", str(src), str(dest)], check=True, capture_output=True, timeout=600)
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        shutil.copy2(src, dest)


def _verify(db_path: Path, table: str) -> int:
    import duckdb
    con = duckdb.connect(str(db_path), read_only=True, config={"enable_external_access": False})
    try:
        row = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
        return int(row[0]) if row else 0
    finally:
        con.close()


def build(src: Path, dest: Path, verify_table: str) -> dict:
    """Cut src -> dest atomically; returns the meta dict. Raises on a missing source, a torn copy that failed
    both attempts, or a copy that verifies to zero rows (the old dest file is left untouched in every case)."""
    if not src.exists():
        raise FileNotFoundError(f"source DB missing: {src}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + f".tmp{int(time.time())}")
    try:
        for attempt in (0, 1):
            sig = _signature(src)
            _fast_copy(src, tmp)
            if _signature(src) == sig or attempt == 1:
                break
            tmp.unlink(missing_ok=True)                 # the source moved under the copy — once more
        rows = _verify(tmp, verify_table)
        if rows <= 0:
            raise RuntimeError(f"verify failed: {verify_table} has {rows} rows in the copy")
        tmp.replace(dest)                               # atomic: a reader never sees a half-written file
    finally:
        tmp.unlink(missing_ok=True)
    meta = {"path": str(dest), "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "rows": rows, "src_mtime_ns": sig[0], "src_size": sig[1]}
    meta_tmp = dest.with_name(dest.name + META_SUFFIX + ".tmp")
    meta_tmp.write_text(json.dumps(meta, indent=1))
    meta_tmp.replace(dest.with_name(dest.name + META_SUFFIX))
    return meta


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    ap.add_argument("--verify-table", default=DEFAULT_VERIFY_TABLE)
    args = ap.parse_args()
    t0 = time.time()
    try:
        meta = build(args.src, args.dest, args.verify_table)
    except Exception as exc:  # noqa: BLE001 — one honest line; the controller job reads stderr
        print(f"ask snapshot FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"ask snapshot built: {meta['path']} rows={meta['rows']} in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

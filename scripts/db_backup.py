#!/usr/bin/env python
"""Nightly DuckDB backup (Bloomberg program F1.3; runs 02:15 IST from master-controller).

Source preference: tonight's shared evening snapshot (consistent, zero extra live-DB read —
`build_evening_snapshot.current(allow_stale=True)`, because by 02:15 the live DB has taken the
20:30 F&O catch-up and 20:45 results ingest; that ≤1-trading-day lag is the documented loss
window, see docs/RUNBOOK_RESTORE.md). Fallback: a private consistent copy of the live DB using
the same torn-copy-safe helper.

Output: data/backups/duckdb/market-YYYYMMDD.duckdb[.zst] + market-YYYYMMDD.meta.json
        {rows, sha256, src, src_mtime_ns, compressed, missed_nights, missed_nights_new} — missed_nights
        (missed_backup_days) names
        the prior nights in the rotation window that have no verified copy: after a multi-night outage the
        catch-up runs ONE backup (point-in-time; a missed night cannot be back-dated) and the gap is recorded
        here and said once on Telegram by the controller instead of being silently absorbed (F4 §1d);
        missed_nights_new holds only the stamps no earlier meta named (what the controller's one line says).
Rotation: keep 7 daily + 4 weekly (Sundays). Verification: read-only open + row count of
nse_bhavcopy on the pre-compression copy; sha256 recorded for restore-integrity checks.

The terminal's settings store (ui-api's data/ui_prefs.sqlite, PREFS_DB overrides; desktop program D3) is
backed up first, into the same directory and rotation — as are the alert store (alerts-YYYYMMDD.sqlite), the
durable job queue (job_queue-YYYYMMDD.sqlite, data/job_queue.sqlite / JOB_QUEUE_DB; F-24/F-31) and ASK's audit
log (ask_audit-YYYYMMDD.sqlite, data/ask_audit.sqlite / ASK_AUDIT_DB), each quietly skipped while its store does
not exist yet: ui_prefs-YYYYMMDD.sqlite + ui_prefs-YYYYMMDD.meta.json
{keys, live_keys, sha256, bytes, user_version}. It is copied with SQLite's online backup API (a consistent
snapshot while ui-api writes; a plain file copy would miss the -wal), switched to a single-file rollback
journal, checked with PRAGMA integrity_check and written atomically. An absent store is skipped (fresh
install); a failed settings backup makes the run exit 1 AFTER the DuckDB backup (the controller alerts).
Restore: docs/RUNBOOK_RESTORE.md §8.

One backup at a time: a run holds an exclusive lock on <dest>/.db_backup.lock (flock; the kernel drops it when
the process dies, so there is no stale lock to clean). A second run (the 02:15 job, master-controller's start-up
catch-up of a missed night, a manual run) exits 75 at once and writes nothing; the controller logs it as skipped.

    python scripts/db_backup.py [--dest data/backups/duckdb] [--prefs-db PATH] [--prefs-only]
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_evening_snapshot as snap

DEST_DEFAULT = ROOT / "data" / "backups" / "duckdb"
KEEP_DAILY = 7
KEEP_WEEKLY = 4                      # Sundays, beyond the daily window
LOCK_NAME = ".db_backup.lock"
EXIT_BUSY = 75                       # EX_TEMPFAIL: another backup holds the lock; nothing was written
# Backup families sharing one directory and one rotation policy (file globs per family). Each family rotates on
# its own, so the "last 4 Sundays" are counted per family (a combined count would let two families' copies of
# one Sunday take two of the four slots).
FAMILIES: tuple[tuple[str, ...], ...] = (
    ("market-*.duckdb", "market-*.duckdb.zst"),
    ("ui_prefs-*.sqlite",),
    ("alerts-*.sqlite",),
    ("job_queue-*.sqlite",),    # data-service's durable job queue (R2-QUEUE; F-24/F-31)
    ("ask_audit-*.sqlite",),    # ASK's audit log (questions + SQL, never payloads)
    ("paper_fo-*.sqlite",),    # the paper F&O book — the owner's track record (F3-RISK, 14 Nov 2026)
)


class BackupBusy(RuntimeError):
    """Another backup run holds the lock in this backup directory."""


@contextmanager
def single_run(dest: Path) -> Iterator[None]:
    """Exclusive, non-blocking lock on dest/.db_backup.lock for the whole run: two backups never run at once.
    flock is tied to the open file, so a crashed or killed run releases it with no clean-up."""
    dest.mkdir(parents=True, exist_ok=True)
    with (dest / LOCK_NAME).open("a+") as fh:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BackupBusy(f"another backup is running ({dest / LOCK_NAME} is locked)") from exc
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _now() -> datetime:
    """Local wall-clock time: backup file names and meta stamps are local dates by design."""
    return datetime.now()  # noqa: DTZ005


def default_prefs_db() -> Path:
    """ui-api's settings store, resolved like services/ui-api/routers/prefs.py (PREFS_DB, else data/)."""
    env = os.environ.get("PREFS_DB", "").strip()
    return Path(env).expanduser() if env else ROOT / "data" / "ui_prefs.sqlite"


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while blob := f.read(chunk):
            h.update(blob)
    return h.hexdigest()


def _consistent_private_copy(db: Path, tmpdir: Path) -> Path:
    """Torn-copy-safe private copy of the live DB (fallback when no snapshot exists)."""
    for _ in (1, 2):
        sig = snap._signature(db)
        dest = tmpdir / "private.duckdb"
        snap._fast_copy(db, dest)
        wal = Path(str(db) + ".wal")
        if wal.exists():
            snap._fast_copy(wal, tmpdir / "private.duckdb.wal")
        if snap._signature(db) == sig:
            return dest
        dest.unlink(missing_ok=True)
    raise RuntimeError("live DB kept changing during both copy attempts")


def _compress_if_possible(src: Path, dest_stem: Path) -> tuple[Path, bool]:
    """zstd when importable (shared jupyter_env: never pip-install here), else plain copy."""
    try:
        import zstandard
    except ImportError:
        out = dest_stem.with_suffix(".duckdb")
        snap._fast_copy(src, out)
        return out, False
    out = dest_stem.with_suffix(".duckdb.zst")
    cctx = zstandard.ZstdCompressor(level=6)
    with src.open("rb") as fin, out.open("wb") as fout:
        cctx.copy_stream(fin, fout)
    return out, True


def rotate(dest: Path, today: datetime | None = None,
           keep_daily: int = KEEP_DAILY, keep_weekly: int = KEEP_WEEKLY) -> list[str]:
    """Delete backups older than the daily window unless they are among the last
    `keep_weekly` Sunday backups, per family (market DuckDB, ui_prefs SQLite). Meta files follow their backup."""
    removed: list[str] = []
    for globs in FAMILIES:
        removed += _rotate_family(dest, globs, today or _now(), keep_daily, keep_weekly)
    return removed


def _rotate_family(dest: Path, globs: tuple[str, ...], today: datetime, keep_daily: int, keep_weekly: int) -> list[str]:
    removed: list[str] = []
    dated: list[tuple[datetime, Path]] = []
    for p in [p for g in globs for p in dest.glob(g)]:
        try:
            d = datetime.strptime(p.name.split("-")[1].split(".")[0], "%Y%m%d")  # noqa: DTZ007 - a local date
        except (IndexError, ValueError):
            continue
        dated.append((d, p))
    sundays = sorted({d for d, _ in dated if d.weekday() == 6}, reverse=True)[:keep_weekly]
    cutoff = today - timedelta(days=keep_daily)
    for d, p in dated:
        if d > cutoff or d in sundays:        # daily = the last 7 days; weekly = last 4 Sundays (overlap ok)
            continue
        p.unlink(missing_ok=True)
        meta = p.parent / (p.name.split(".")[0] + ".meta.json")
        meta.unlink(missing_ok=True)
        removed.append(p.name)
    return removed


def missed_backup_days(dest: Path, today: datetime | None = None, lookback: int = KEEP_DAILY) -> list[str]:
    """The dated stamps (YYYYMMDD, ascending) of the last ``lookback`` nights before ``today`` with no verified
    market backup in ``dest``. A night counts as covered only by its market-<stamp>.meta.json — db_backup.py
    writes the meta last, after verification, so a killed run's partial .duckdb does not count (same convention
    as the controller's backup_done_today). Pure read: nothing is written.

    Semantics (R5-OPS2, F4 §1d "the 12 Nov gap night"): a backup is point-in-time — a missed night can never be
    re-created after the fact, so there is nothing to re-run per missed day. The correct catch-up after a
    multi-night outage is ONE backup of the data as it stands; this function only names the nights that have no
    copy, so the gap is recorded in tonight's meta ("missed_nights") and surfaced as one Telegram line instead
    of being silently absorbed. Bounds: never today (today's backup is the run in progress), never at or before
    the oldest surviving backup (a fresh install, and nights the rotation legitimately removed, are not missed).
    """
    now = today or _now()
    have: set[str] = set()
    if dest.is_dir():
        for p in dest.glob("market-*.meta.json"):
            stamp = p.name.split("-")[1].split(".")[0]
            try:
                datetime.strptime(stamp, "%Y%m%d")  # noqa: DTZ007 - a local date, like the file names
            except ValueError:
                continue
            have.add(stamp)
    if not have:
        return []
    oldest = min(have)
    missed = [stamp for back in range(1, max(0, int(lookback)) + 1)
              if (stamp := (now - timedelta(days=back)).strftime("%Y%m%d")) > oldest and stamp not in have]
    return sorted(missed)


def _recorded_missed_nights(dest: Path) -> set[str]:
    """Stamps an earlier meta already names in its missed_nights: a gap night is said ONCE on Telegram (the run
    that first sees it), not re-alerted every night for the week it stays inside the lookback window. The metas
    rotate with their backups, always later than the stamp leaves the window, so the dedup never forgets early."""
    seen: set[str] = set()
    if dest.is_dir():
        for p in dest.glob("market-*.meta.json"):
            try:
                val = json.loads(p.read_text()).get("missed_nights")
            except (OSError, ValueError):
                continue
            if isinstance(val, list):
                seen.update(str(s) for s in val)
    return seen


def _open_source(db: Path) -> sqlite3.Connection:
    """Read-only connection to the live store (mode=ro: never writes, never checkpoints). A WAL store whose -shm
    cannot be used read-only (ui-api stopped, -shm gone) falls back to a normal connection that only reads."""
    try:
        con = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
        con.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        return con
    except sqlite3.OperationalError:
        return sqlite3.connect(str(db), timeout=10)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _clean_stale_tmp(dest: Path) -> None:
    """Temp copies left by a killed run (.ui_prefs-*.sqlite.tmp-<pid>, pid gone)."""
    for t in dest.glob(".ui_prefs-*.sqlite.tmp-*"):
        pid = t.name.rsplit("-", 1)[-1]
        if pid.isdigit() and not _pid_alive(int(pid)):
            t.unlink(missing_ok=True)


def backup_prefs(db: Path, dest: Path, stamp: str) -> dict[str, Any]:
    """Online-backup the settings store into dest/ui_prefs-<stamp>.sqlite (+ .meta.json); verified, atomic.

    Returns the meta dict, or {"skipped": "absent", ...} when there is no store yet. Raises on any failure
    (nothing partial is left behind: the copy is built in a temp file and renamed only once verified)."""
    if not db.is_file():
        return {"skipped": "absent", "src": str(db)}
    dest.mkdir(parents=True, exist_ok=True)
    _clean_stale_tmp(dest)
    out = dest / f"ui_prefs-{stamp}.sqlite"
    tmp = dest / f".ui_prefs-{stamp}.sqlite.tmp-{os.getpid()}"
    tmp.unlink(missing_ok=True)
    try:
        src = _open_source(db)
        try:
            dst = sqlite3.connect(str(tmp))
            try:
                src.backup(dst)                                   # one step: a consistent snapshot
                dst.execute("PRAGMA journal_mode=DELETE")         # single self-contained file (no -wal/-shm)
                check = dst.execute("PRAGMA integrity_check").fetchone()[0]
                if check != "ok":
                    raise RuntimeError(f"ui_prefs backup failed integrity_check: {check}")
                has_table = dst.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'prefs'").fetchone()
                keys = dst.execute("SELECT COUNT(*) FROM prefs").fetchone()[0] if has_table else 0
                live = dst.execute("SELECT COUNT(*) FROM prefs WHERE deleted = 0").fetchone()[0] if has_table else 0
                user_version = dst.execute("PRAGMA user_version").fetchone()[0]
            finally:
                dst.close()
        finally:
            src.close()
        os.replace(tmp, out)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    meta = {"keys": keys, "live_keys": live, "user_version": user_version, "sha256": _sha256(out),
            "bytes": out.stat().st_size, "file": out.name, "src": str(db),
            "created_at": _now().isoformat(timespec="seconds")}
    (dest / f"ui_prefs-{stamp}.meta.json").write_text(json.dumps(meta, indent=1))
    return meta


def _backup_prefs_safely(prefs_db: Path | None, dest: Path, stamp: str) -> dict[str, Any]:
    try:
        return backup_prefs(prefs_db or default_prefs_db(), dest, stamp)
    except Exception as exc:  # noqa: BLE001 - reported in the result; main() exits 1
        return {"error": f"{type(exc).__name__}: {exc}"[:300]}


def default_alerts_db() -> Path:
    """ui-api's alert store (routers/alerts.py: ALERTS_DB, else data/alerts.sqlite next to price_alerts.json)."""
    env = os.environ.get("ALERTS_DB", "").strip()
    return Path(env).expanduser() if env else ROOT / "data" / "alerts.sqlite"


def backup_alerts(db: Path, dest: Path, stamp: str) -> dict[str, Any]:
    """Online-backup the alert store (typed rules + the append-only fire log, W2-ALERTS) into dest/alerts-<stamp>.sqlite
    (+ .meta.json) the way the settings store is: SQLite's backup API (consistent while ui-api writes in WAL mode),
    a single-file rollback journal, PRAGMA integrity_check, an atomic rename. {"skipped": "absent"} before ui-api has
    created the store. Raises on any failure (nothing partial is left behind)."""
    if not db.is_file():
        return {"skipped": "absent", "src": str(db)}
    dest.mkdir(parents=True, exist_ok=True)
    for t in dest.glob(".alerts-*.sqlite.tmp-*"):
        pid = t.name.rsplit("-", 1)[-1]
        if pid.isdigit() and not _pid_alive(int(pid)):
            t.unlink(missing_ok=True)
    out = dest / f"alerts-{stamp}.sqlite"
    tmp = dest / f".alerts-{stamp}.sqlite.tmp-{os.getpid()}"
    tmp.unlink(missing_ok=True)
    try:
        src = _open_source(db)
        try:
            dst = sqlite3.connect(str(tmp))
            try:
                src.backup(dst)
                dst.execute("PRAGMA journal_mode=DELETE")
                check = dst.execute("PRAGMA integrity_check").fetchone()[0]
                if check != "ok":
                    raise RuntimeError(f"alerts backup failed integrity_check: {check}")
                names = {r[0] for r in dst.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
                rules = dst.execute("SELECT COUNT(*) FROM alert_rules").fetchone()[0] if "alert_rules" in names else 0
                fires = dst.execute("SELECT COUNT(*) FROM alert_fires").fetchone()[0] if "alert_fires" in names else 0
            finally:
                dst.close()
        finally:
            src.close()
        os.replace(tmp, out)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    meta = {"rules": rules, "fires": fires, "sha256": _sha256(out), "bytes": out.stat().st_size, "file": out.name,
            "src": str(db), "created_at": _now().isoformat(timespec="seconds")}
    (dest / f"alerts-{stamp}.meta.json").write_text(json.dumps(meta, indent=1))
    return meta


def _backup_alerts_safely(alerts_db: Path | None, dest: Path, stamp: str) -> dict[str, Any]:
    try:
        return backup_alerts(alerts_db or default_alerts_db(), dest, stamp)
    except Exception as exc:  # noqa: BLE001 - reported in the result; main() exits 1
        return {"error": f"{type(exc).__name__}: {exc}"[:300]}


def default_job_queue_db() -> Path:
    """data-service's durable job queue (job_queue.default_db_path: JOB_QUEUE_DB, else data/job_queue.sqlite)."""
    env = os.environ.get("JOB_QUEUE_DB", "").strip()
    return Path(env).expanduser() if env else ROOT / "data" / "job_queue.sqlite"


def default_ask_audit_db() -> Path:
    """ASK's audit log (ask_engine._audit_path: ASK_AUDIT_DB, else data/ask_audit.sqlite)."""
    env = os.environ.get("ASK_AUDIT_DB", "").strip()
    return Path(env).expanduser() if env else ROOT / "data" / "ask_audit.sqlite"


def default_paper_fo_db() -> Path:
    """The paper F&O book — the owner's track record (fo_book_store: PAPER_FO_DB, else data/paper_fo.sqlite)."""
    env = os.environ.get("PAPER_FO_DB", "").strip()
    return Path(env).expanduser() if env else ROOT / "data" / "paper_fo.sqlite"


def _backup_sqlite_store(db: Path, dest: Path, stamp: str, prefix: str,
                         counters: dict[str, str]) -> dict[str, Any]:
    """Online-backup a small SQLite store into dest/<prefix>-<stamp>.sqlite (+ .meta.json), exactly the way the
    settings and alert stores are backed up: SQLite's backup API (a consistent snapshot while the owner writes in
    WAL mode), a single-file rollback journal, PRAGMA integrity_check, an atomic rename. ``counters`` maps a meta
    key to a table whose row count it records (0 when the table does not exist yet). A missing source file is
    handled quietly: {"skipped": "absent"} — a fresh install has no store yet and that is not an error. Raises on
    any real failure (nothing partial is left behind)."""
    if not db.is_file():
        return {"skipped": "absent", "src": str(db)}
    dest.mkdir(parents=True, exist_ok=True)
    for t in dest.glob(f".{prefix}-*.sqlite.tmp-*"):     # temp copies left by a killed run
        pid = t.name.rsplit("-", 1)[-1]
        if pid.isdigit() and not _pid_alive(int(pid)):
            t.unlink(missing_ok=True)
    out = dest / f"{prefix}-{stamp}.sqlite"
    tmp = dest / f".{prefix}-{stamp}.sqlite.tmp-{os.getpid()}"
    tmp.unlink(missing_ok=True)
    try:
        src = _open_source(db)
        try:
            dst = sqlite3.connect(str(tmp))
            try:
                src.backup(dst)
                dst.execute("PRAGMA journal_mode=DELETE")
                check = dst.execute("PRAGMA integrity_check").fetchone()[0]
                if check != "ok":
                    raise RuntimeError(f"{prefix} backup failed integrity_check: {check}")
                names = {r[0] for r in dst.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
                counts = {key: (dst.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                                if table in names else 0) for key, table in counters.items()}
            finally:
                dst.close()
        finally:
            src.close()
        os.replace(tmp, out)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    meta = {**counts, "sha256": _sha256(out), "bytes": out.stat().st_size, "file": out.name,
            "src": str(db), "created_at": _now().isoformat(timespec="seconds")}
    (dest / f"{prefix}-{stamp}.meta.json").write_text(json.dumps(meta, indent=1))
    return meta


def backup_job_queue(db: Path, dest: Path, stamp: str) -> dict[str, Any]:
    """Online-backup the durable job queue (R2-QUEUE) into dest/job_queue-<stamp>.sqlite (+ .meta.json), the
    alerts way. {"skipped": "absent"} quietly before data-service has created the store."""
    return _backup_sqlite_store(db, dest, stamp, "job_queue", {"jobs": "jobs"})


def _backup_job_queue_safely(job_queue_db: Path | None, dest: Path, stamp: str) -> dict[str, Any]:
    try:
        return backup_job_queue(job_queue_db or default_job_queue_db(), dest, stamp)
    except Exception as exc:  # noqa: BLE001 - reported in the result; main() exits 1
        return {"error": f"{type(exc).__name__}: {exc}"[:300]}


def backup_ask_audit(db: Path, dest: Path, stamp: str) -> dict[str, Any]:
    """Online-backup ASK's audit log into dest/ask_audit-<stamp>.sqlite (+ .meta.json), the alerts way.
    {"skipped": "absent"} quietly before the first question has created the store."""
    return _backup_sqlite_store(db, dest, stamp, "ask_audit", {"questions": "ask_audit"})


def _backup_ask_audit_safely(ask_audit_db: Path | None, dest: Path, stamp: str) -> dict[str, Any]:
    try:
        return backup_ask_audit(ask_audit_db or default_ask_audit_db(), dest, stamp)
    except Exception as exc:  # noqa: BLE001 - reported in the result; main() exits 1
        return {"error": f"{type(exc).__name__}: {exc}"[:300]}


def backup_paper_fo(db: Path, dest: Path, stamp: str) -> dict[str, Any]:
    """Online-backup the paper F&O book (the owner's track record) into dest/paper_fo-<stamp>.sqlite, the alerts
    way. {"skipped": "absent"} quietly before the first booked structure. F3-RISK (14 Nov 2026): this store was
    in no backup family at all."""
    return _backup_sqlite_store(db, dest, stamp, "paper_fo", {"structures": "paper_fo_structures", "positions": "paper_fo_positions", "journal": "paper_fo_journal"})


def _backup_paper_fo_safely(paper_fo_db: Path | None, dest: Path, stamp: str) -> dict[str, Any]:
    try:
        return backup_paper_fo(paper_fo_db or default_paper_fo_db(), dest, stamp)
    except Exception as exc:  # noqa: BLE001 - reported in the result; main() exits 1
        return {"error": f"{type(exc).__name__}: {exc}"[:300]}


def run_prefs(dest: Path = DEST_DEFAULT, prefs_db: Path | None = None) -> dict[str, Any]:
    """Settings-store backup alone (with rotation): `--prefs-only`, e.g. before a migration."""
    meta = _backup_prefs_safely(prefs_db, dest, _now().strftime("%Y%m%d"))
    if dest.is_dir():
        meta["rotated"] = rotate(dest)
    return meta


def run(db: Path = snap.DB, dest: Path = DEST_DEFAULT, pointer: Path = snap.POINTER,
        prefs_db: Path | None = None, alerts_db: Path | None = None,
        job_queue_db: Path | None = None, paper_fo_db: Path | None = None, ask_audit_db: Path | None = None) -> dict:
    dest.mkdir(parents=True, exist_ok=True)
    stamp = _now().strftime("%Y%m%d")
    # Read BEFORE anything is written tonight: the nights in the rotation window with no verified copy (a backup
    # is point-in-time, so a missed night cannot be back-dated; it is recorded, and the controller says so once —
    # missed_nights_new carries only the stamps no earlier meta has named, so the Telegram line never repeats).
    missed_nights = missed_backup_days(dest)
    missed_new = sorted(set(missed_nights) - _recorded_missed_nights(dest))
    # The small SQLite stores first (tiny, seconds): a DuckDB failure below must not cost the night's copies.
    prefs = _backup_prefs_safely(prefs_db, dest, stamp)
    alerts = _backup_alerts_safely(alerts_db, dest, stamp)
    job_queue = _backup_job_queue_safely(job_queue_db, dest, stamp)     # the durable queue's trail (F-24/F-31)
    paper_fo = _backup_paper_fo_safely(paper_fo_db, dest, stamp)     # the durable queue's trail (F-24/F-31)
    ask_audit = _backup_ask_audit_safely(ask_audit_db, dest, stamp)     # ASK's audit log (no payloads inside)
    stem = dest / f"market-{stamp}"
    with tempfile.TemporaryDirectory(prefix="dbbackup_") as td:
        src_path = snap.current(max_age_h=30, allow_stale=True, pointer=pointer, db=db)
        src_kind = "evening_snapshot"
        if src_path is None:
            src_path = str(_consistent_private_copy(db, Path(td)))
            src_kind = "private_copy"
        src = Path(src_path)
        rows = snap._verify(src)                       # verify BEFORE compression
        if rows <= 0:
            raise RuntimeError("backup source verified empty")
        out, compressed = _compress_if_possible(src, stem)
    meta = {"rows": rows, "sha256": _sha256(out), "src": src_kind,
            "src_mtime_ns": src.stat().st_mtime_ns if src.exists() else None,
            "compressed": compressed, "created_at": _now().isoformat(timespec="seconds"),
            "file": out.name, "bytes": out.stat().st_size,
            "missed_nights": missed_nights, "missed_nights_new": missed_new}
    (dest / f"market-{stamp}.meta.json").write_text(json.dumps(meta, indent=1))
    meta["rotated"] = rotate(dest)
    meta["prefs"] = prefs
    meta["alerts"] = alerts
    meta["job_queue"] = job_queue
    meta["ask_audit"] = ask_audit
    meta["paper_fo"] = paper_fo
    return meta


def offsite_target(arg: str | None) -> Path | None:
    """The off-machine copy target: ``--offsite DIR``, else ``OFFSITE_BACKUP_DIR`` (.env / environment), else None
    (Terminal v2 Wave 0.1; the owner decides the target, O-T1: a mounted volume, an rclone mount, an external SSD)."""
    raw = (arg or os.environ.get("OFFSITE_BACKUP_DIR", "")).strip()
    return Path(raw).expanduser() if raw else None


def copy_offsite(dest: Path, meta: dict[str, Any], target: Path, *, keep_daily: int = KEEP_DAILY,
                 keep_weekly: int = KEEP_WEEKLY) -> dict[str, Any]:
    """Copy tonight's backup files (the .zst when zstd was available, else the .duckdb; the ui_prefs / alerts /
    job_queue / ask_audit .sqlite copies; every .meta.json) to ``target`` and verify the DuckDB copy by sha256
    against the recorded hash. Each file lands via a
    temp name + rename, so a cut mount never leaves a half file under the real name. The target keeps the same
    rotation (7 daily + 4 Sundays). Raises on any failure; the local backup is already complete by then."""
    files: list[str] = []
    for name in (meta.get("file"), (meta.get("prefs") or {}).get("file"), (meta.get("alerts") or {}).get("file"),
                 (meta.get("job_queue") or {}).get("file"), (meta.get("ask_audit") or {}).get("file"),
                 (meta.get("paper_fo") or {}).get("file")):
        if name and (dest / name).is_file():
            files.append(name)
            stem_meta = name.split(".")[0] + ".meta.json"
            if (dest / stem_meta).is_file():
                files.append(stem_meta)
    if not files:
        raise RuntimeError("nothing to copy off-site: no backup file in the result")
    if not target.is_dir():
        if target.parent.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            raise RuntimeError(f"off-site target is not mounted / does not exist: {target}")
    copied: list[str] = []
    for name in files:
        tmp = target / f".{name}.tmp-{os.getpid()}"
        try:
            snap._fast_copy(dest / name, tmp)
            os.replace(tmp, target / name)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        copied.append(name)
    got = _sha256(target / str(meta["file"]))
    if got != meta.get("sha256"):
        raise RuntimeError(f"off-site copy sha256 mismatch for {meta['file']}: {got[:12]} != {str(meta.get('sha256'))[:12]}")
    rotated = rotate(target, keep_daily=keep_daily, keep_weekly=keep_weekly)
    return {"target": str(target), "files": copied, "sha256_verified": True, "rotated": rotated,
            "bytes": sum((target / n).stat().st_size for n in copied)}


def _copy_offsite_safely(dest: Path, meta: dict[str, Any], target: Path | None) -> dict[str, Any]:
    if target is None:
        return {"skipped": "unset", "hint": "set OFFSITE_BACKUP_DIR in .env or pass --offsite DIR (O-T1)"}
    try:
        return copy_offsite(dest, meta, target)
    except Exception as exc:  # noqa: BLE001 - reported in the result; main() exits 1
        return {"error": f"{type(exc).__name__}: {exc}"[:300], "target": str(target)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Nightly DuckDB + settings-store backup with rotation")
    ap.add_argument("--dest", default=str(DEST_DEFAULT))
    ap.add_argument("--prefs-db", type=Path, default=None,
                    help="settings store to back up (default: PREFS_DB, else data/ui_prefs.sqlite)")
    ap.add_argument("--prefs-only", action="store_true", help="back up only the settings store (seconds)")
    ap.add_argument("--offsite", nargs="?", const="", default=None, metavar="DIR",
                    help="also copy tonight's files to DIR (default: OFFSITE_BACKUP_DIR from .env); sha256-verified, "
                         "same rotation; a failure exits 1 after the local backup")
    args = ap.parse_args(argv)
    t0 = time.time()
    try:
        with single_run(Path(args.dest)):
            if args.prefs_only:
                meta = run_prefs(dest=Path(args.dest), prefs_db=args.prefs_db)
            else:
                meta = run(dest=Path(args.dest), prefs_db=args.prefs_db)
                if args.offsite is not None:
                    meta["offsite"] = _copy_offsite_safely(Path(args.dest), meta, offsite_target(args.offsite))
    except BackupBusy as exc:
        print(f"skipped: {exc}; nothing written", file=sys.stderr)
        return EXIT_BUSY
    print(f"RESULT {json.dumps({**meta, 'seconds': round(time.time() - t0, 2)})}")
    rc = 0
    prefs = meta if args.prefs_only else meta.get("prefs", {})
    if "error" in prefs:
        print(f"ui_prefs backup FAILED ({prefs['error']}); the DuckDB backup is fine: {meta.get('file')}",
              file=sys.stderr)
        rc = 1
    for key in ("alerts", "job_queue", "ask_audit"):
        part = {} if args.prefs_only else meta.get(key) or {}
        if "error" in part:
            print(f"{key} backup FAILED ({part['error']}); the DuckDB backup is fine: {meta.get('file')}",
                  file=sys.stderr)
            rc = 1
    offsite = meta.get("offsite") or {}
    if "error" in offsite:
        print(f"off-site copy FAILED ({offsite['error']}); the local backup is fine: {meta.get('file')}", file=sys.stderr)
        rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())

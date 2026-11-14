"""DurableJobManager (job_queue.py, R2-QUEUE): persisted rows, one-per-kind dedupe, the lease + heartbeat,
kill-resume (expired lease → re-queued → adopted by the next submit), sync-row recording, and the compact
recent() view. The surface must stay a drop-in for jobs.JobManager ({job, created} and the legacy job keys),
because master_controller polls GET /jobs/{id} for status running|done|error."""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import pytest

from job_queue import DurableJobManager, default_db_path

LEGACY_KEYS = {"job_id", "kind", "status", "progress", "total", "started_at", "finished_at", "result", "error"}


def _wait(mgr: DurableJobManager, job_id: str, timeout: float = 10.0) -> dict:
    """Wait for a terminal job AND for the worker to leave the live mirror. The worker sets the mirror's status
    before ``_finish()`` commits the row, so a status-only wait can win the race against the SQLite write (the
    F2 flake in test_error_is_persisted): once the job is out of ``_running``, the row is committed."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        with mgr._lock:                                  # noqa: SLF001 - the race under test is internal
            in_mirror = job_id in mgr._running           # noqa: SLF001
        j = mgr.get(job_id)
        if j and j["status"] not in ("running", "queued") and not in_mirror:
            return j
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def _wait_row(db: Path, job_id: str, timeout: float = 10.0) -> str:
    """Poll the PERSISTED row (never the in-memory mirror) to a terminal status — the de-flake asked for by
    F-RISK F2: assertions about what a restart will see wait on the row itself, not on a sleep."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        with sqlite3.connect(db) as con:
            row = con.execute("SELECT status FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row and row[0] not in ("running", "queued"):
            return row[0]
        time.sleep(0.02)
    raise AssertionError("job row never reached a terminal status in SQLite")


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "job_queue.sqlite"


def test_submit_runs_persists_and_survives_restart(db: Path):
    mgr = DurableJobManager(db, heartbeat_s=60)
    job, created = mgr.submit("refresh", lambda p: (p(3, 3), {"written": 7})[1])
    assert created and job["status"] in ("running", "done") and LEGACY_KEYS <= set(job)
    done = _wait(mgr, job["job_id"])
    assert done["status"] == "done" and done["result"] == {"written": 7} and done["finished_at"]
    assert _wait_row(db, job["job_id"]) == "done"        # the restart below reads the row, so wait on the row
    mgr.close()

    # a fresh manager on the same file (a restart) still serves the row — the queue is the store
    mgr2 = DurableJobManager(db)
    j = mgr2.get(job["job_id"])
    assert j and j["status"] == "done" and j["result"] == {"written": 7} and LEGACY_KEYS <= set(j)
    assert any(x["job_id"] == job["job_id"] for x in mgr2.list())
    mgr2.close()


def test_one_job_per_kind_and_is_running(db: Path):
    mgr = DurableJobManager(db, heartbeat_s=60)
    gate = threading.Event()
    j1, created1 = mgr.submit("bhavcopy", lambda p: (gate.wait(10), {"ok": True})[1])
    j2, created2 = mgr.submit("bhavcopy", lambda p: {"ok": False})
    assert created1 and not created2 and j2["job_id"] == j1["job_id"]
    assert mgr.is_running("bhavcopy") and not mgr.is_running("refresh")
    # drop-in for main._submit's response shape
    assert {**j2, "already_running": not created2}["already_running"] is True
    gate.set()
    assert _wait(mgr, j1["job_id"])["result"] == {"ok": True}
    assert not mgr.is_running("bhavcopy")
    mgr.close()


def test_error_is_persisted(db: Path):
    mgr = DurableJobManager(db, heartbeat_s=60)
    def boom(p):
        raise ValueError("nope")
    job, _ = mgr.submit("build", boom)
    done = _wait(mgr, job["job_id"])
    assert done["status"] == "error" and "ValueError: nope" in done["error"] and done["result"] is None
    assert _wait_row(db, job["job_id"]) == "error"       # de-flake: mgr2 reads SQLite, so wait on the row
    mgr.close()
    mgr2 = DurableJobManager(db)
    assert mgr2.get(job["job_id"])["status"] == "error"
    mgr2.close()


def test_kill_resume_expired_lease_is_requeued_and_adopted(db: Path):
    """The acceptance test: a crash mid-job leaves a leased running row; the next start re-queues it and the
    next submit of that kind adopts the same job_id (attempt 2) and re-runs."""
    mgr_a = DurableJobManager(db, lease_s=0.2, heartbeat_s=3600)   # no renewal: the 'crash'
    job, _ = mgr_a.submit("nse_positions", lambda p: (threading.Event().wait(), {})[1])   # blocks forever
    mgr_a.close()                                                   # heartbeat gone == process dead
    from datetime import datetime, timezone
    deadline = time.time() + 5
    while time.time() < deadline:                                   # wait out the 0.2 s lease
        with sqlite3.connect(db) as con:
            lease = con.execute("SELECT lease_expires_at FROM jobs WHERE job_id = ?", (job["job_id"],)).fetchone()[0]
        if lease and datetime.fromisoformat(lease) < datetime.now(timezone.utc):
            break
        time.sleep(0.05)

    mgr_b = DurableJobManager(db, heartbeat_s=60)                   # the restart
    row = mgr_b.get(job["job_id"])
    assert row["status"] == "queued" and row["requeued"] is True

    resumed, created = mgr_b.submit("nse_positions", lambda p: {"resumed": True})
    assert created and resumed["job_id"] == job["job_id"] and resumed["attempt"] == 2
    done = _wait(mgr_b, job["job_id"])
    assert done["status"] == "done" and done["result"] == {"resumed": True} and done["attempt"] == 2
    mgr_b.close()


def test_fresh_lease_of_live_pid_is_left_alone(db: Path):
    """A running row whose lease is current and whose pid is alive (this process) is NOT requeued."""
    mgr_a = DurableJobManager(db, lease_s=120, heartbeat_s=60)
    gate = threading.Event()
    job, _ = mgr_a.submit("gold:gold_overnight", lambda p: (gate.wait(10), {"ok": 1})[1])
    mgr_b = DurableJobManager(db, heartbeat_s=60)
    assert mgr_b.get(job["job_id"])["status"] == "running"
    gate.set()
    _wait(mgr_a, job["job_id"])
    mgr_a.close(); mgr_b.close()


def test_heartbeat_flushes_progress_and_extends_lease(db: Path):
    mgr = DurableJobManager(db, lease_s=120, heartbeat_s=3600)
    gate = threading.Event()

    def fn(progress):
        progress(42, 100)
        gate.wait(10)
        return {"ok": True}

    job, _ = mgr.submit("iv:iv_eod", fn)
    time.sleep(0.1)
    assert mgr.flush_heartbeat() == 1
    with sqlite3.connect(db) as con:
        progress, total, hb, lease = con.execute(
            "SELECT progress, total, heartbeat_at, lease_expires_at FROM jobs WHERE job_id = ?",
            (job["job_id"],)).fetchone()
    assert (progress, total) == (42, 100) and hb and lease and lease > hb
    gate.set()
    _wait(mgr, job["job_id"])
    mgr.close()


def test_record_sync_persists_row_and_returns_result_unchanged(db: Path):
    mgr = DurableJobManager(db, heartbeat_s=60)
    out = mgr.record_sync("nse_index_closes", lambda: {"written": {"^NSEI": 26000.0}})
    assert out == {"written": {"^NSEI": 26000.0}}                   # the endpoint's contract is untouched
    rows = [r for r in mgr.recent() if r["kind"] == "nse_index_closes"]
    assert rows and rows[0]["status"] == "done"

    with pytest.raises(RuntimeError):
        mgr.record_sync("fii_dii_backfill", lambda: (_ for _ in ()).throw(RuntimeError("nse down")))
    err = [r for r in mgr.recent() if r["kind"] == "fii_dii_backfill"]
    assert err and err[0]["status"] == "error" and "nse down" in err[0]["error"]
    mgr.close()


def test_recent_is_compact_and_capped(db: Path):
    mgr = DurableJobManager(db, heartbeat_s=60)
    for i in range(5):
        mgr.record_sync(f"k{i}", lambda i=i: {"i": i})
    rows = mgr.recent(3)
    assert len(rows) == 3 and all("result" not in r for r in rows)
    assert {"job_id", "kind", "status", "attempt", "requeued", "submitted_at", "finished_at",
            "duration_s"} <= set(rows[0])
    mgr.close()


def test_recent_default_50_and_cap_500(db: Path):
    """F-24/F-31: an evening's trail fits — recent() defaults to 50 rows and clamps any ask to 500."""
    mgr = DurableJobManager(db, heartbeat_s=60, keep=600)
    now = "2026-11-13T18:00:00+00:00"
    with sqlite3.connect(db) as con:
        con.executemany(
            "INSERT INTO jobs (job_id, kind, status, progress, total, attempt, requeued, submitted_at,"
            " started_at, finished_at) VALUES (?, 'evening', 'done', 1, 1, 1, 0, ?, ?, ?)",
            [(f"j{i:04d}", f"2026-11-13T18:{i // 60:02d}:{i % 60:02d}+00:00", now, now) for i in range(520)])
        con.commit()
    assert len(mgr.recent()) == 50                       # default unchanged (the cheap poll)
    assert len(mgr.recent(520)) == 500                   # cap raised 200 → 500: the full trail in one call
    assert len(mgr.recent(500)) == 500
    assert len(mgr.recent(0)) == 1                       # floor stays 1
    assert all({"attempt", "requeued"} <= set(r) for r in mgr.recent(5))
    mgr.close()


def test_recent_running_rows_carry_live_progress(db: Path):
    """A running row in recent() shows the mirror's fresh progress (no heartbeat needed), with attempt/requeued."""
    mgr = DurableJobManager(db, heartbeat_s=3600)
    gate = threading.Event()

    def fn(progress):
        progress(5, 10)
        gate.wait(10)
        return {"ok": True}

    job, _ = mgr.submit("tape", fn)
    deadline = time.time() + 5
    row = None
    while time.time() < deadline:                        # wait on the mirror's progress, not a sleep
        row = next((r for r in mgr.recent() if r["job_id"] == job["job_id"]), None)
        if row and row["progress"] == 5:
            break
        time.sleep(0.02)
    assert row and row["status"] == "running" and (row["progress"], row["total"]) == (5, 10)
    assert row["attempt"] == 1 and row["requeued"] is False and "result" not in row
    gate.set()
    _wait(mgr, job["job_id"])
    mgr.close()


def test_history_trim_keeps_cap(db: Path):
    mgr = DurableJobManager(db, heartbeat_s=60, keep=10)
    for _ in range(25):
        mgr.record_sync("trim", lambda: {"ok": True})
    with sqlite3.connect(db) as con:
        n = con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    assert n <= 11      # keep + at most the row being inserted
    mgr.close()


def test_default_db_path_env_override(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("JOB_QUEUE_DB", raising=False)
    assert default_db_path(tmp_path) == tmp_path / "job_queue.sqlite"
    monkeypatch.setenv("JOB_QUEUE_DB", str(tmp_path / "elsewhere.sqlite"))
    assert default_db_path(tmp_path) == tmp_path / "elsewhere.sqlite"


def test_a_flood_of_successes_does_not_erase_a_failure(tmp_path) -> None:
    """The evidence problem, found on 14 Nov: `nse_results` died twice on 13 Nov with a TypeError that took
    every company's results data with it, and by the next morning the rows were gone — pruned by 83 ordinary
    successes, because _trim ranked successes and failures together by recency. A failure is the row worth
    keeping: it is the only durable record outside a log line, and the DATA page reads this store to decide
    whether a dataset's job is healthy.
    """
    mgr = DurableJobManager(tmp_path / "q.sqlite", keep=5)
    con = mgr._connect()

    def _row(job_id: str, kind: str, status: str, at: str) -> None:
        con.execute(
            "INSERT INTO jobs (job_id, kind, status, progress, total, attempt, requeued, submitted_at, error) "
            "VALUES (?, ?, ?, 0, 0, 1, 0, ?, ?)",
            (job_id, kind, status, at, "TypeError: boom" if status == "error" else None))

    _row("e1", "nse_results", "error", "2026-11-13T15:15:00+00:00")
    for i in range(40):                                        # a busy day of successes after it
        _row(f"d{i}", "ingest", "done", f"2026-11-14T{i // 2:02d}:{(i % 2) * 30:02d}:00+00:00")
    con.commit()
    mgr._trim(con)
    con.commit()

    kept_errors = con.execute("SELECT COUNT(*) FROM jobs WHERE status = 'error'").fetchone()[0]
    kept_done = con.execute("SELECT COUNT(*) FROM jobs WHERE status = 'done'").fetchone()[0]
    assert kept_errors == 1, "the failure was pruned by successes — the exact 13 Nov evidence loss"
    assert kept_done == 5, f"successes should still be capped at keep=5, got {kept_done}"
    con.close()


def test_job_failures_counts_crashes_and_states_the_window_it_can_speak_for(tmp_path) -> None:
    """F11-06: the DATA page printed only the LAST run's word, so `nse_results` read FRESH on 14 Nov although
    its job had died twice the evening before — on the one page whose whole job is data trust, for a table
    EVTS reads before the open.

    Two things must hold for the count to be honest: a crash-REQUEUED row counts (a job killed by a restart
    becomes 'queued', not 'error', and a restart is what every deploy does), and the window the store can
    speak for travels with the number — a 0 over a period the store never held is a claim, not a measurement.
    """
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from data_health.reads import job_failures

    db = tmp_path / "jq.sqlite"
    mgr = DurableJobManager(db, keep=50)
    con = mgr._connect()

    def _row(job_id: str, kind: str, status: str, at: str, requeued: int = 0) -> None:
        con.execute(
            "INSERT INTO jobs (job_id, kind, status, progress, total, attempt, requeued, submitted_at, error) "
            "VALUES (?, ?, ?, 0, 0, 1, ?, ?, ?)",
            (job_id, kind, status, requeued, at, "TypeError: boom" if status == "error" else None))

    _row("a", "nse_results", "error", "2026-11-13T15:15:00+00:00")
    _row("b", "nse_results", "done", "2026-11-13T22:45:00+00:00")          # a later success must not hide it
    _row("c", "fo_iv:iv_repair", "queued", "2026-11-13T18:19:00+00:00", requeued=1)   # killed by a restart
    _row("d", "ingest_bhavcopy", "done", "2026-11-14T06:00:00+00:00")
    con.commit()
    con.close()

    counts, since, counted = job_failures(db)
    assert counts.get("nse_results") == 1, f"a crash hidden by a later success: {counts}"
    assert counts.get("fo_iv:iv_repair") == 1, "a crash-requeued row is a crash"
    assert counts.get("iv_repair") == 1, "the bare job id resolves too (kinds are '<group>:<id>')"
    assert "ingest_bhavcopy" not in counts, "a healthy job must not be given a crash"
    assert {"nse_results", "ingest_bhavcopy"} <= counted, "the store must report every kind it has seen"

    # F12: the lookup the PAGE performs, which is the one that was wrong — a catalog row carries a
    # master-controller job id (`results_capture_daily`), not the data-service submit kind (`nse_results`),
    # and the first version asserted only the kind. 55 of 69 rows could never have shown a crash.
    from data_health.reads import _failures_for, _keys_for

    row_results = {"id": "nse_results", "ingest_job": "results_capture_daily"}
    assert "nse_results" in _keys_for(row_results), "the controller id must resolve to the submit kind"
    assert _failures_for(row_results, counts, counted) == 1, "the page's own lookup missed the crash"

    # a dataset the store HAS seen and that has not crashed reads 0…
    assert _failures_for({"id": "x", "ingest_job": "ingest_bhavcopy"}, counts, counted) == 0
    # …and one it has never seen reads None, not 0: "never seen" is not "never crashed"
    assert _failures_for({"id": "nowhere", "ingest_job": "nothing"}, counts, counted) is None
    assert _failures_for({"id": "endpoint_row", "ingest_job": ""}, counts, counted) is None

    assert since, "a window must always be reported"

    # and a store that does not exist says so rather than claiming zero crashes
    empty, no_since, no_kinds = job_failures(tmp_path / "missing.sqlite")
    assert empty == {} and no_since is None and no_kinds == set()
    assert _failures_for(row_results, empty, no_kinds) is None, "no store must mean a dash, never a zero"


def test_the_kind_map_covers_the_generic_submit_kinds(tmp_path) -> None:
    """F13-01: the map held only the four pairs one review happened to name.

    data-service submits several datasets under GENERIC kinds — "bhavcopy", "refresh", "build", "indices" —
    so the rows behind them stayed dark however often their job crashed. `nse_bhavcopy` is the worst of them:
    it is the table every equity panel on the terminal reads. The inverse was provable on the live store,
    which held kind "refresh" while the `ohlcv` row printed a dash.

    Also pinned: every key resolves against the failures BEFORE any falls back to "known but clean". Checking
    both per key let the first merely-known alias short-circuit to 0 and hide a crash recorded under a later
    one.
    """
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from data_health.reads import _DATASET_TO_KIND, _failures_for, _keys_for

    # the generic kinds, read off main.py's own _submit() sites
    main_src = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    for dataset, kind in _DATASET_TO_KIND.items():
        if ":" in kind:
            continue                                   # submitted by a sub-package, not main.py
        assert f'_submit("{kind}"' in main_src, f"{dataset} maps to a kind main.py does not submit: {kind}"
        assert kind in _keys_for({"id": dataset, "ingest_job": "whatever"}), dataset

    # nse_bhavcopy specifically — the dataset every equity panel reads
    keys = _keys_for({"id": "nse_bhavcopy", "ingest_job": "eod_data_pipeline"})
    assert "bhavcopy" in keys, f"the bhavcopy kind is unreachable from its row: {keys}"

    # a crash under a LATER alias must win over an earlier alias the store merely knows
    failures = {"bhavcopy": 3}
    counted = {"eod_data_pipeline", "bhavcopy"}
    assert _failures_for({"id": "nse_bhavcopy", "ingest_job": "eod_data_pipeline"}, failures, counted) == 3, (
        "an earlier known-but-clean alias short-circuited past a real crash")


def test_the_retention_floor_is_ist_and_compared_as_an_instant(tmp_path, monkeypatch) -> None:
    """F13-02: the floor was naive UTC rendered raw on a page whose every other time is IST.

    It read "crash counting began 2026-11-14 07:17" when counting began at 12:47 IST — a 5.5 h over-claim
    covering the whole morning, including the 08:45 gold snapshot. That is the same defect F12 found in the
    PREVIOUS floor, re-expressed inside the fix written to answer it. And `max()` over two ISO strings with
    different offsets compares text, not moments.
    """
    import sys
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from data_health.reads import _later_iso, _retention_floor

    floor = _retention_floor(tmp_path / "q.sqlite")
    assert floor and ("+05:30" in floor), f"the floor must be offset-aware IST: {floor}"
    assert datetime.fromisoformat(floor).utcoffset().total_seconds() == 5.5 * 3600

    # compared as instants: a UTC row 10 minutes LATER must win over an IST floor, despite sorting lower
    utc_later = "2026-11-14T08:00:00+00:00"            # 13:30 IST
    ist_floor = "2026-11-14T13:20:00+05:30"
    assert _later_iso(utc_later, ist_floor) == utc_later, "string comparison picked the wrong moment"
    assert _later_iso(None, ist_floor) == ist_floor and _later_iso(utc_later, None) == utc_later


def test_one_job_that_writes_eight_datasets_lights_all_eight() -> None:
    """R14-A: `/jobs/ingest-nse-files` records ONE kind for a job that produces eight datasets.

    Transcribing pairs by hand left every one of them dark, so the 20:30 evening pass could fail and
    index_ohlc_daily, nse_fo_volt, nse_contract_delta, nse_combined_oi, nse_participant_vol, nse_fii_stats
    and nse_mwpl_clients would all still read clean on the page whose job is data trust. The mapping is
    derived from the job's own TERMINAL_DATASETS table, so a dataset added to that job is covered the day it
    is added — hand-transcription is the mistake this column has now repeated at three different levels.
    """
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from data_health.reads import _failures_for, _keys_for, _nse_files_datasets

    # R15-A: this used to read `produced = _nse_files_datasets()` and then iterate `produced` — asserting the
    # derived tuple against ITSELF, which passes whatever the derivation returns. It now checks against the
    # job's OWN authority: the set `/jobs/ingest-nse-files` validates its input against, which includes
    # nse_bhavcopy (the If-Modified-Since revision pass). Dropping that half left the terminal's most-read
    # table reporting a positive 0 on a night its job crashed.
    import re

    api_src = (Path(__file__).resolve().parents[1] / "fo_iv" / "api.py").read_text(encoding="utf-8")
    m = re.search(r"known\s*=\s*set\(nse_positions\.TERMINAL_DATASET_NAMES\)\s*\|\s*\{([^}]*)\}", api_src)
    assert m, "the nse_files job no longer declares its dataset set the way this test reads it"
    extra = {x.strip().strip('\'"') for x in m.group(1).split(",") if x.strip()}
    assert "nse_bhavcopy" in extra, extra

    produced = _nse_files_datasets()
    for dataset in extra:
        assert dataset in produced, (
            f"{dataset} is accepted by the job but missing from the derivation — it would read a positive 0 "
            f"on a night the job crashed")
    assert len(produced) >= 8, f"the nse_files job table shrank unexpectedly: {produced}"
    assert "index_ohlc_daily" in produced and "nse_fii_stats" in produced

    failures = {"nse_files": 2}
    counted = {"nse_files"}
    for dataset in produced:
        keys = _keys_for({"id": dataset, "ingest_job": "nse_positions_catchup"})
        assert "nse_files" in keys, f"{dataset} cannot see its own job's crash: {keys}"
        assert _failures_for({"id": dataset, "ingest_job": "nse_positions_catchup"}, failures, counted) == 2, dataset

    # a dataset NOT produced by that job must not inherit its crash
    assert _failures_for({"id": "unrelated", "ingest_job": "whatever"}, failures, counted) is None


def test_every_mapped_key_is_a_real_catalog_id_or_job() -> None:
    """R14-B: `_DATASET_TO_KIND` carried `nse_indices`, which is not a catalog id at all — the dataset the
    `indices` kind writes is `market_index_daily`, so that row stayed dark while the map looked complete.
    A map whose keys nothing matches is worse than a missing entry: it reads as coverage."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from data_health import catalog
    from data_health.reads import _DATASET_TO_KIND, _JOB_ID_TO_KIND

    rows = catalog.build_rows() if hasattr(catalog, "build_rows") else catalog.rows()
    ids = {str(r["id"]) for r in rows}
    jobs = {str(r.get("ingest_job") or "") for r in rows}

    unknown_ds = sorted(k for k in _DATASET_TO_KIND if k not in ids)
    assert not unknown_ds, f"_DATASET_TO_KIND keys that are not catalog ids: {unknown_ds}"
    unknown_job = sorted(k for k in _JOB_ID_TO_KIND if k not in jobs)
    assert not unknown_job, f"_JOB_ID_TO_KIND keys that are not any row's ingest_job: {unknown_job}"


def test_the_floor_comparison_survives_a_naive_mark_file(tmp_path) -> None:
    """R14-C: comparing a naive datetime with an aware one raises TypeError, not ValueError — and that is
    exactly the upgrade path this function exists for (a mark written by the earlier, naive code beside
    offset-aware job rows). `health()` calls job_failures() unguarded, so the uncaught version took the whole
    69-row payload down."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from data_health.reads import _later_iso

    naive = "2026-11-14T07:17:02"                 # what the previous code wrote
    aware = "2026-11-13T17:47:00+00:00"           # what the job rows carry
    assert _later_iso(aware, naive) == naive, "a naive mark must not raise"
    assert _later_iso(naive, aware) == aware
    assert _later_iso("nonsense", aware) == aware


def test_a_dataset_with_two_producer_jobs_sums_their_crashes() -> None:
    """`nse_bhavcopy` is written by TWO independent jobs — the 18:30 pipeline (kind `daily_pipeline`) and the
    22:45 revision pass (kind `nse_files`) — and "first matching key wins" reported 2 crashes on a night there
    were 7. Never a false clean, but an undercount on the one dataset with two producers is still a number
    that is not the number, on the page whose job is to be the number.

    The import must also be whole: `_nse_files_datasets` swallows ImportError, and a probe run without
    `shared` on the path returned an empty tuple and a quietly wrong answer — so this asserts the derivation
    is non-empty before trusting anything it says.
    """
    import sys

    repo = Path(__file__).resolve().parents[3]
    for p in (str(repo), str(repo / "services/data-service")):
        if p not in sys.path:
            sys.path.insert(0, p)
    from data_health.reads import _failures_for, _keys_for, _nse_files_datasets

    assert len(_nse_files_datasets()) >= 8, (
        "the nse_files derivation came back empty — an ImportError is being swallowed and every answer "
        "below it would be quietly wrong")

    row = {"id": "nse_bhavcopy", "ingest_job": "eod_data_pipeline"}
    keys = _keys_for(row)
    assert {"daily_pipeline", "nse_files"} <= set(keys), keys

    assert _failures_for(row, {"daily_pipeline": 2, "nse_files": 5}, {"daily_pipeline", "nse_files"}) == 7
    assert _failures_for(row, {"nse_files": 3}, {"nse_files"}) == 3
    assert _failures_for(row, {}, {"daily_pipeline"}) == 0          # known, clean
    assert _failures_for(row, {}, set()) is None                    # never seen


def test_a_group_of_jobs_writing_one_table_lights_that_table() -> None:
    """R18-A: the job store held exactly ONE failure — `fo_iv:iv_repair` — and ZERO of 69 dataset rows
    reported it.

    Job kinds are `<group>:<job_id>`, and a GROUP writes the same tables from several job ids: the fo_iv
    endpoint submits iv_eod | iv_weekly | iv_backfill | vix_backfill | iv_repair into the same IV store,
    while every catalog row names only `iv_eod`. So four of the five could never light the column, and the
    IV rows printed "never seen" while the store had seen two of their jobs and one of them had crashed —
    a false clean on the page whose whole job is to be the number.

    The mapping is read from the FUNCTION that submits each group's kinds, never transcribed. That is the
    point: this column has had a producer-mapping defect in four consecutive rounds, every one of them a
    hand-written list, and a file-scoped first attempt at this very fix mapped `iv_eod` to `nse_files`
    because `fo_iv/api.py` submits both.
    """
    import sys

    repo = Path(__file__).resolve().parents[3]
    for p in (str(repo), str(repo / "services/data-service")):
        if p not in sys.path:
            sys.path.insert(0, p)
    from data_health.reads import _failures_for, _groups_from_source, _keys_for

    groups = _groups_from_source()
    assert groups.get("iv_eod") == "fo_iv", (
        f"iv_eod must resolve to the fo_iv group — a file-scoped scan called it nse_files: {groups.get('iv_eod')}")
    assert groups.get("iv_weekly") == "fo_iv", groups.get("iv_weekly")

    row = {"id": "iv_surface_daily", "ingest_job": "iv_eod"}
    keys = _keys_for(row)
    assert "group:fo_iv" in keys, f"the IV datasets cannot see their own group's crashes: {keys}"

    # a crash under ANY of the group's job ids reaches the datasets that group writes
    assert _failures_for(row, {"group:fo_iv": 2}, {"group:fo_iv"}) == 2
    # and a different group's crash does NOT
    assert _failures_for(row, {"group:gold": 4}, {"group:gold"}) is None


def test_the_health_payload_builds_end_to_end() -> None:
    """A smoke test for `reads.health()` itself, because the suite had none and a NameError shipped.

    I added `"job_failures_scope": _failure_scope(...)` to the row in one edit and the function definition in
    another — and the second edit failed its assertion before writing. Every unit test still passed, because
    they all call the helpers directly; nothing built a row. data-service's /db/data-health returned 500 and
    ui-api degraded to a 22-row fallback with no Crashes column at all, live, until a probe caught it.

    So: construct the payload the way the endpoint does, and assert its shape. A function the page calls must
    be exercised by something other than the page.
    """
    import sys

    repo = Path(__file__).resolve().parents[3]
    for p in (str(repo), str(repo / "services/data-service")):
        if p not in sys.path:
            sys.path.insert(0, p)
    import data_health.reads as reads

    # every name the row builder references must exist before it is called
    for name in ("_failures_for", "_failure_scope", "_keys_for", "job_failures", "_nse_files_datasets"):
        assert callable(getattr(reads, name, None)), f"reads.{name} is referenced by health() and missing"

    row = {"id": "iv_surface_daily", "ingest_job": "iv_eod", "label": "x", "pages": "DERV",
           "publisher": "p", "cadence": "daily", "max_age_sessions": 1, "freshness_kind": "table",
           "verdict": "v", "badge": "context"}
    failures, since, counted = reads.job_failures()
    # the two calls health() makes per row, together, in order
    count = reads._failures_for(row, failures, counted)
    scope = reads._failure_scope(row, failures)
    assert count is None or isinstance(count, int), count
    assert scope is None or isinstance(scope, str), scope
    if count:
        assert scope, "a non-zero count must say what it counted"

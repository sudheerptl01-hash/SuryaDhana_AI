"""FINAL round D-PIPE (P0-2 / P0-3 / P0-11): the job-vs-catalog table-unmoved verdict respects expected_by / session
logic (a holiday or a pre-deadline run is never a failure), a red row aged a second session yields exactly ONE
escalation record, an intraday tape gap is detected on a fixture and deduped per day, and the gold pre-open log sync
makes ``/api/data/health`` stop saying ``gap`` while the accuracy log holds the row. Temp DuckDB only."""
from __future__ import annotations

# ruff: noqa: DTZ001
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "data-service"))

from data_health import db, escalations, gaps, reads, watermarks  # noqa: E402
from data_health.schema import CASTS, COLUMNS  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


def utc_naive(ist: datetime) -> datetime:
    return ist.astimezone(timezone.utc).replace(tzinfo=None)


@pytest.fixture
def store(tmp_path: Path):
    from storage.duckdb_store import DuckDBStore

    s = DuckDBStore(str(tmp_path / "rot.duckdb"))
    yield s
    s.close()


def seed_job_dataset(store, *, job="j_test", ds="ds_test", table="t_pipe", expected_by="19:00",
                     cadence="daily", max_age=1, offset=0, days=()) -> None:
    row = {"id": ds, "label": ds, "pages": "SYS", "publisher": "test", "publish_time_ist": None, "expected_by": expected_by,
           "expected_offset_days": offset, "cadence": cadence, "max_age_sessions": max_age, "unrecoverable": False,
           "ingest_job": job, "freshness_kind": "table", "table_name": table, "freshness_column": "date",
           "freshness_where": None, "dictionary_anchor": None, "verdict": "PUBLISH-CORE", "badge": "arithmetic",
           "note": None, "verified_at": None, "verified_by": None}
    db.upsert(store, "dataset_catalog", pd.DataFrame([row]), COLUMNS["dataset_catalog"], CASTS["dataset_catalog"])
    db.execute(store, f"CREATE TABLE IF NOT EXISTS {table} (date DATE)")
    for d in days:
        db.execute(store, f"INSERT INTO {table} VALUES (?)", [d])


# ── P0-2: the table-unmoved verdict ────────────────────────────────────────────────────────────────────────────────

def test_a_job_whose_table_did_not_move_is_failed(store, tmp_path):
    # Wed 4 Nov 2026 22:30 IST, table stuck at 30 Oct (3 sessions behind, past the budget) → red → FAILED
    seed_job_dataset(store, days=[date(2026, 10, 30)])
    now = utc_naive(datetime(2026, 11, 4, 22, 30, tzinfo=IST))
    out = watermarks.verify_job(store, tmp_path, "j_test", now=now)
    assert out["status"] == "FAILED" and out["reasons"] == ["table_unmoved:ds_test"]
    # the escalation record exists exactly once, and a re-check the same session adds nothing
    assert len(escalations.list_escalations(store, kind="table_unmoved")) == 1
    watermarks.verify_job(store, tmp_path, "j_test", now=now)
    assert len(escalations.list_escalations(store, kind="table_unmoved")) == 1
    # the persisted verdict surfaces on the health row of the dataset (job_check)
    rows = {r["id"]: r for r in reads.health(store, tmp_path, now=now)["rows"]}
    assert rows["ds_test"]["job_check"]["status"] == "FAILED"
    assert "table_unmoved:ds_test" in rows["ds_test"]["job_check"]["reasons"]


def test_holidays_weekends_and_predeadline_runs_are_never_failures(store, tmp_path):
    seed_job_dataset(store, days=[date(2026, 11, 3)])
    hol = {date(2026, 11, 4)}                                             # Wednesday holiday: 3 Nov is the due session
    now = utc_naive(datetime(2026, 11, 4, 22, 30, tzinfo=IST))
    out = watermarks.verify_job(store, tmp_path, "j_test", now=now, holidays=hol)
    assert out["status"] == "ok", out
    # Saturday: last session Friday 6 Nov stored → nothing due beyond it
    seed_job_dataset(store, job="j_sat", ds="ds_sat", table="t_sat", days=[date(2026, 11, 6)])
    sat = utc_naive(datetime(2026, 11, 7, 12, 0, tzinfo=IST))
    assert watermarks.verify_job(store, tmp_path, "j_sat", now=sat)["status"] == "ok"
    # a run before the 19:00 deadline: today's session is not due yet, yesterday stored → ok
    seed_job_dataset(store, job="j_early", ds="ds_early", table="t_early", days=[date(2026, 11, 3)])
    early = utc_naive(datetime(2026, 11, 4, 18, 0, tzinfo=IST))
    assert watermarks.verify_job(store, tmp_path, "j_early", now=early)["status"] == "ok"


def test_amber_within_budget_is_behind_not_failed_and_weekly_is_unjudged(store, tmp_path):
    # structural T+1 row (offset 1, budget 2): one session behind reads amber → "behind", never FAILED
    seed_job_dataset(store, job="j_t1", ds="ds_t1", table="t_t1", expected_by="23:00", max_age=2, offset=1,
                     days=[date(2026, 11, 2)])
    now = utc_naive(datetime(2026, 11, 4, 23, 30, tzinfo=IST))
    out = watermarks.verify_job(store, tmp_path, "j_t1", now=now)
    assert out["status"] == "ok" and out["behind"] == ["ds_t1"]
    # weekly cadence (COT reads amber every Friday by design): unjudged, never failed
    seed_job_dataset(store, job="j_wk", ds="ds_wk", table="t_wk", cadence="weekly", expected_by=None, max_age=11, days=[])
    out = watermarks.verify_job(store, tmp_path, "j_wk", now=now)
    assert out["status"] == "no_judged_dataset"
    assert out["datasets"][0]["verdict"] == "unjudged"


def test_the_exact_prior_watermark_rule_with_before(store, tmp_path):
    # table one session behind (amber) but the caller's pre-run watermark shows it did not move → FAILED
    seed_job_dataset(store, days=[date(2026, 11, 3)])
    now = utc_naive(datetime(2026, 11, 4, 22, 30, tzinfo=IST))
    out = watermarks.verify_job(store, tmp_path, "j_test", now=now, before={"ds_test": "2026-11-03"})
    assert out["status"] == "FAILED" and out["reasons"] == ["table_unmoved:ds_test"]
    # the same run with the table advanced to the due session → ok
    db.execute(store, "INSERT INTO t_pipe VALUES (?)", [date(2026, 11, 4)])
    out = watermarks.verify_job(store, tmp_path, "j_test", now=now, before={"ds_test": "2026-11-03"})
    assert out["status"] == "ok"
    # holiday with before: nothing was due past the watermark → ok even though nothing moved
    seed_job_dataset(store, job="j_hol", ds="ds_hol", table="t_hol", days=[date(2026, 11, 3)])
    out = watermarks.verify_job(store, tmp_path, "j_hol", now=now, holidays={date(2026, 11, 4)},
                                before={"ds_hol": "2026-11-03"})
    assert out["status"] == "ok"


# ── P0-2: red-row ageing escalation ────────────────────────────────────────────────────────────────────────────────

def test_a_red_row_aged_two_sessions_yields_exactly_one_escalation(store, tmp_path):
    red = [{"id": "ohlcv", "state": "red", "note": "2 session(s) behind the expected one"}]
    wed = utc_naive(datetime(2026, 11, 4, 16, 10, tzinfo=IST))            # last session 4 Nov: first sighting, no record
    assert escalations.scan_red_aging(store, tmp_path, now=wed, health_rows=red) == []
    thu = utc_naive(datetime(2026, 11, 5, 16, 10, tzinfo=IST))            # still red a session later: ONE record
    new = escalations.scan_red_aging(store, tmp_path, now=thu, health_rows=red)
    assert len(new) == 1 and new[0]["dataset"] == "ohlcv" and new[0]["kind"] == "red_aged"
    assert "red since 2026-11-04" in new[0]["detail"]
    # the same session again (the hourly re-scan): deduped, nothing new
    assert escalations.scan_red_aging(store, tmp_path, now=thu, health_rows=red) == []
    assert len(escalations.list_escalations(store, kind="red_aged")) == 1
    # recovery: a fresh row writes no record and resets the streak
    fresh = [{"id": "ohlcv", "state": "fresh", "note": None}]
    fri = utc_naive(datetime(2026, 11, 6, 16, 10, tzinfo=IST))
    assert escalations.scan_red_aging(store, tmp_path, now=fri, health_rows=fresh) == []
    sat_red = utc_naive(datetime(2026, 11, 9, 16, 10, tzinfo=IST))        # red again later: a NEW first sighting
    assert escalations.scan_red_aging(store, tmp_path, now=sat_red, health_rows=red) == []


# ── P0-3: the intraday tape gap ────────────────────────────────────────────────────────────────────────────────────

def _tape_row(store, sym: str, ts_ist: datetime) -> None:
    ts = utc_naive(ts_ist)
    db.execute(store, "INSERT INTO iv_intraday (ts, symbol, expiry, strike, opt_type, mid, oi, source, model_version, first_seen_at) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
               [ts, sym, date(2026, 11, 17), 25000.0, "CE", 100.0, 1000.0, "breeze", "b76-pcp-v1-i", ts])


def test_tape_gap_detected_on_a_fixture_and_deduped(store, tmp_path):
    # Fri 13 Nov, 11:00 IST: NIFTY's newest snapshot 09:35 (85 min old), BANKNIFTY never snapped today
    _tape_row(store, "NIFTY", datetime(2026, 11, 13, 9, 35, tzinfo=IST))
    now = utc_naive(datetime(2026, 11, 13, 11, 0, tzinfo=IST))
    new = escalations.tape_gap_check(store, now=now)
    assert len(new) == 1 and new[0]["kind"] == "tape_gap"
    assert "NIFTY: newest 09:35 IST" in new[0]["detail"] and "BANKNIFTY: no snapshot today" in new[0]["detail"]
    rows = gaps.gaps(store, dataset="iv_intraday")
    assert len(rows) == 1 and rows[0]["date"] == "2026-11-13" and "tape gap" in rows[0]["reason"]
    # an hour later, still gapped: the day's record exists, nothing new (one Telegram line per day)
    later = utc_naive(datetime(2026, 11, 13, 12, 0, tzinfo=IST))
    assert escalations.tape_gap_check(store, now=later) == []


def test_tape_gap_is_quiet_when_fresh_out_of_window_and_on_holidays(store, tmp_path):
    now = utc_naive(datetime(2026, 11, 13, 11, 0, tzinfo=IST))
    _tape_row(store, "NIFTY", datetime(2026, 11, 13, 10, 56, tzinfo=IST))
    _tape_row(store, "BANKNIFTY", datetime(2026, 11, 13, 10, 58, tzinfo=IST))
    assert escalations.tape_gap_check(store, now=now) == []               # both fresh (≤ 10 min)
    evening = utc_naive(datetime(2026, 11, 13, 16, 0, tzinfo=IST))
    assert escalations.tape_gap_check(store, now=evening) == []           # out of the window
    open_grace = utc_naive(datetime(2026, 11, 13, 9, 20, tzinfo=IST))
    assert escalations.tape_gap_check(store, now=open_grace) == []        # the open's grace: judged from 09:30
    holiday = utc_naive(datetime(2026, 11, 13, 11, 0, tzinfo=IST))
    assert escalations.tape_gap_check(store, now=holiday, holidays={date(2026, 11, 13)}) == []


# ── P0-11: one store, one definition for the gold pre-open log ─────────────────────────────────────────────────────

def test_gold_preopen_sync_fills_missing_days_and_clears_the_false_gap(store, tmp_path):
    from gold import ingest_local

    # the table holds 6 Nov with its inputs_json (the dual-written copy); log.json holds 5 AND 6 Nov
    ingest_local.upsert_preopen_log(store, {"day": "2026-11-06", "contract": "GOLD DEC-26", "fair_open": 141000.0,
                                            "baseline": 140500.0, "inputs_json": {"kept": True}})
    log = {"2026-11-05": {"date": "2026-11-05", "contract": "GOLD DEC-26", "fair_open": 140800.0, "baseline": 140300.0},
           "2026-11-06": {"date": "2026-11-06", "contract": "GOLD DEC-26", "fair_open": 999999.0}}
    p = tmp_path / "log.json"
    p.write_text(json.dumps(log), encoding="utf-8")
    # the false gap: 5 Nov recorded as a gap while the accuracy log holds the row
    gaps.write_gaps(store, "gold_preopen_log", [date(2026, 11, 5), date(2026, 11, 4)], "stack down (no capture)")
    out = ingest_local.sync_preopen_log(store, p)
    assert out["days"] == ["2026-11-05"]                                  # missing day only; 6 Nov never overwritten
    kept = store.read_one("SELECT fair_open, inputs_json FROM gold_preopen_log WHERE day = ?", [date(2026, 11, 6)])
    assert kept[0] == 141000.0 and kept[1] is not None
    recovered = gaps.clear_recovered(store, tmp_path)
    assert recovered == {"gold_preopen_log": ["2026-11-05"]}
    left = gaps.gaps(store, dataset="gold_preopen_log")
    assert [r["date"] for r in left] == ["2026-11-04"]                    # the genuinely lost session keeps its gap row
    # and the health read no longer calls 5 Nov a gap: the stored day IS the as-of now
    cat_row = {"id": "gold_preopen_log", "cadence": "session", "freshness_kind": "table", "expected_by": "09:15",
               "expected_offset_days": 0, "max_age_sessions": 1, "table_name": "gold_preopen_log", "freshness_column": "day"}
    now_ist = datetime(2026, 11, 5, 16, 0, tzinfo=IST)                    # state_for takes the IST-aware clock
    st = reads.state_for(cat_row, reads.as_of_for(store, cat_row, tmp_path), now_ist, gap_days=set())
    assert st["state"] == "fresh"


# ── the API surface the controller calls ───────────────────────────────────────────────────────────────────────────

def test_the_router_serves_the_check_the_scan_and_the_escalations_read(store, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import data_health.api as dh_api

    (tmp_path / "nse_archive").mkdir(exist_ok=True)
    dh_api.configure(get_store=lambda: store, submit=lambda kind, fn: {"status": "unused"},
                     archive_root=lambda: tmp_path / "nse_archive", holidays=lambda: set())
    app = FastAPI()
    app.include_router(dh_api.router)
    c = TestClient(app)
    seed_job_dataset(store, days=[date(2026, 10, 30)])
    r = c.post("/jobs/data-health?job=job_watermark_check", json={"ingest_job": "j_test"})
    assert r.status_code == 200 and r.json()["status"] == "FAILED" and r.json()["reasons"] == ["table_unmoved:ds_test"]
    assert c.post("/jobs/data-health?job=job_watermark_check").status_code == 422     # ingest_job is required
    r = c.post("/jobs/data-health?job=escalations_scan", json={"preopen_log_path": str(tmp_path / "absent.json")})
    assert r.status_code == 200 and "new" in r.json() and "gaps_recovered" in r.json()
    r = c.get("/db/data-health/escalations", params={"kind": "table_unmoved"})
    assert r.status_code == 200 and r.json()["count"] == 1 and r.json()["rows"][0]["dataset"] == "ds_test"


def test_sync_is_idempotent_and_survives_a_missing_file(store, tmp_path):
    from gold import ingest_local

    missing = ingest_local.sync_preopen_log(store, tmp_path / "absent.json")
    assert missing["inserted"] == 0 and "missing" in missing
    p = tmp_path / "log.json"
    p.write_text(json.dumps({"2026-11-10": {"date": "2026-11-10", "contract": "GOLD DEC-26", "fair_open": 141100.0}}),
                 encoding="utf-8")
    assert ingest_local.sync_preopen_log(store, p)["inserted"] == 1
    assert ingest_local.sync_preopen_log(store, p)["inserted"] == 0       # second run: nothing to add

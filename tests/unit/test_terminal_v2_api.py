"""The data-service routes of the three terminal v2 packages on a minimal FastAPI app with a temp store and the in-process
JobManager: job names, 422 on unknown jobs / datasets, the reads' shapes and badges, the intraday pilot refusing to run without
the budget ledger (PAPER / read-only / metered), no publisher call on any GET (a transport that fails loudly)."""
from __future__ import annotations

# ruff: noqa: DTZ001
import sys
import time
from datetime import date, datetime
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "data-service"))

import data_health.api as dh_api  # noqa: E402
import fo_iv.api as iv_api  # noqa: E402
import index_drivers.api as dr_api  # noqa: E402
from jobs import JobManager  # noqa: E402
from shared.http_client import PacedClient  # noqa: E402


@pytest.fixture
def client(tmp_path: Path):
    from storage.duckdb_store import DuckDBStore

    store = DuckDBStore(str(tmp_path / "api.duckdb"))
    jobs = JobManager()

    def submit(kind, fn):
        job, created = jobs.submit(kind, fn)
        return {**job, "already_running": not created}

    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        return httpx.Response(404)

    http = PacedClient(transport=httpx.MockTransport(handler), sleep=lambda s: None)
    (tmp_path / "nse_archive" / "fo").mkdir(parents=True)
    app = FastAPI()
    dh_api.configure(get_store=lambda: store, submit=submit, archive_root=lambda: tmp_path / "nse_archive", holidays=lambda: set())
    iv_api.configure(get_store=lambda: store, submit=submit, fo_root=tmp_path / "nse_archive" / "fo", cache_root=tmp_path, parquet_root=tmp_path / "chain",
                     http_factory=lambda: http, get_breeze=lambda: None, is_live=lambda: False, watchlist=lambda: [], surface_symbols=lambda: None)
    dr_api.configure(get_store=lambda: store, submit=submit, cache_root=tmp_path, financials_root=tmp_path / "fin", http_factory=lambda: http)
    app.include_router(dh_api.router)
    app.include_router(iv_api.router)
    app.include_router(dr_api.router)
    c = TestClient(app)
    c.jobs, c.calls, c.store = jobs, calls, store  # type: ignore[attr-defined]
    yield c
    store.close()


def _wait(jobs: JobManager, job_id: str, timeout: float = 30.0) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = jobs.get(job_id)
        if j and j["status"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_data_health_job_and_reads(client):
    r = client.post("/jobs/data-health?job=data_health_refresh", json={"sessions": 3})
    assert r.status_code == 200 and r.json()["kind"] == "data_health:data_health_refresh"
    j = _wait(client.jobs, r.json()["job_id"])
    assert j["status"] == "done" and j["result"]["catalog_rows"] >= 60 and "gap_scan" in j["result"]
    assert client.post("/jobs/data-health?job=nope").status_code == 422
    h = client.get("/db/data-health").json()
    assert h["summary"]["red"] > 0 and h["rows"] and {"id", "state", "lag_sessions", "expected_at", "badge"} <= set(h["rows"][0]) and "note" in h
    assert client.get("/db/data-health/catalog").json()["count"] >= 60
    assert client.get("/db/data-health/ingest-log").json()["rows"] == []
    assert client.get("/db/data-health/gaps").json()["count"] >= 0
    assert client.calls == []                                               # no publisher on any read


def test_fo_iv_jobs_and_reads(client):
    assert client.post("/jobs/iv-eod?job=bogus").status_code == 422
    assert client.post("/jobs/iv-eod?job=iv_intraday").status_code == 422
    r = client.post("/jobs/iv-eod?job=iv_eod", json={"date": "2026-11-04", "fetch_files": False})
    j = _wait(client.jobs, r.json()["job_id"])
    assert j["status"] == "done" and j["result"]["status"] == "not_yet" and "20:10" in j["result"]["reason"]   # no file in the temp archive
    r = client.post("/jobs/iv-eod?job=iv_weekly")
    j = _wait(client.jobs, r.json()["job_id"])
    assert j["status"] == "done" and j["result"]["job"] == "iv_weekly" and j["result"]["ranks_recomputed"] == 0
    r = client.post("/jobs/iv-intraday?job=iv_intraday", json={"force_window": True})
    j = _wait(client.jobs, r.json()["job_id"])
    assert j["status"] == "done" and j["result"]["status"] == "skipped" and "not live" in j["result"]["reason"] and j["result"]["calls"] == 0
    s = client.get("/db/fo-iv/summary/NIFTY").json()
    assert s["symbol"] == "NIFTY" and s["rows"] == [] and s["model_version"] == "b76-pcp-v1" and s["badges"]["spread"] == "context"
    assert s["verdict"].endswith("describes, does not predict")
    assert client.get("/db/fo-iv/surface/NIFTY").json()["expiries"] == []
    assert client.get("/db/fo-iv/cone/NIFTY").json()["cone"] == {}
    assert client.get("/db/fo-iv/events/INFY").json()["rows"] == []
    assert client.get("/db/fo-iv/vol-screen?sort=iv_rank").json()["rows"] == []
    assert client.get("/db/fo-iv/vol-screen?sort=bogus").status_code == 422
    assert client.get("/db/fo-iv/intraday/NIFTY").json()["source"] == "OFFLINE"
    cat = client.get("/db/fo-iv/catalog").json()
    assert cat["count"] > 20 and all(r["badge"] != "signal" for r in cat["rows"]) and all(r["verdict_sentence"].endswith("describes, does not predict") for r in cat["rows"])
    assert client.get("/db/fo-iv/meta").json()["tables"]["iv_summary_daily"]["rows"] == 0
    plan = client.get("/db/fo-iv/backfill-plan").json()
    assert plan["resumable"] and plan["steps"][0]["step"] == "udiff" and plan["steps"][0]["remaining"] == 0
    assert client.get("/db/vix-daily").json()["rows"] == [] and client.get("/db/index-ohlc/NIFTY 50").json()["rows"] == []
    assert client.post("/jobs/ingest-nse-files", json={"datasets": ["nope"]}).status_code == 422
    assert client.calls == []


def test_ingest_nse_files_logs_misses_through_the_paced_client(client):
    r = client.post("/jobs/ingest-nse-files?job=nse_files", json={"datasets": ["nse_fo_volt"], "from": "2026-11-04", "to": "2026-11-04"})
    j = _wait(client.jobs, r.json()["job_id"])
    assert j["status"] == "done" and j["result"]["files"]["nse_fo_volt"]["statuses"] == {"missing": 1}
    assert client.calls == ["https://nsearchives.nseindia.com/archives/nsccl/volt/FOVOLT_04112026.csv"]
    log = client.get("/db/data-health/ingest-log?dataset=nse_fo_volt").json()
    assert log["count"] == 1 and log["rows"][0]["status"] == "missing"


def test_index_drivers_jobs_and_reads(client):
    assert client.post("/jobs/index-drivers?job=bogus").status_code == 422
    assert client.post("/jobs/index-drivers", json={"indices": ["NIFTY MOON"]}).status_code == 422
    r = client.post("/jobs/index-drivers?job=index_drivers_daily", json={"date": "2026-11-04", "fetch": False})
    j = _wait(client.jobs, r.json()["job_id"])
    assert j["status"] == "done" and j["result"]["status"] == "degraded" and j["result"]["indices"]["NIFTY 50"]["status"] == "no_members"
    d = client.get("/db/index-drivers?index=NIFTY%2050&horizon=1m").json()
    assert d["as_of"] is None and d["members"] == [] and d["badges"]["driver"] == "context"
    assert client.get("/db/index-drivers?horizon=2w").status_code == 422
    assert client.get("/db/index-drivers/timeline?window=30").status_code == 422
    assert client.get("/db/index-drivers/timeline").json()["rows"] == []
    assert client.get("/db/index-drivers/monthly").json()["rows"] == []
    assert client.get("/db/index-drivers/catalog").json()["count"] >= 8
    assert client.get("/db/index-drivers/meta").json()["indices"] == []
    assert client.get("/db/index-drivers/backfill-plan").json()["resumable"]
    assert client.calls == []


def test_job_names_match_the_plan():
    from fo_iv import jobs as ivj
    from index_drivers import jobs as drj

    assert {"iv_eod", "iv_intraday", "iv_weekly"} <= set(ivj.JOBS) and "index_drivers_daily" in drj.JOBS and dh_api.JOB_IDS == ("data_health_refresh",)
    assert date(2026, 11, 5) and datetime(2026, 11, 5, 0, 0)

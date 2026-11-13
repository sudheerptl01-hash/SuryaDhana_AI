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


def test_ingest_nse_files_defaults_to_the_last_completed_session_not_today(client, monkeypatch):
    """check:B2-CTRL minor: with no from / to the route asked for date.today() — on a holiday or a weekend that is a
    'missing' row for a non-session date. The default is now the last completed NSE session (the docstring's promise)."""
    from data_health import calendar as cal

    sat_10 = datetime(2026, 11, 7, 10, 0, tzinfo=cal.IST)                  # Saturday morning → Friday 6 Nov
    monkeypatch.setattr(cal, "now_ist", lambda now_utc_naive=None: sat_10)
    r = client.post("/jobs/ingest-nse-files", json={"datasets": ["nse_fo_volt"]})
    j = _wait(client.jobs, r.json()["job_id"])
    assert j["result"]["from"] == j["result"]["to"] == "2026-11-06"
    assert client.calls == ["https://nsearchives.nseindia.com/archives/nsccl/volt/FOVOLT_06112026.csv"]
    # negative control: an explicit window is used as given
    client.calls.clear()
    r = client.post("/jobs/ingest-nse-files", json={"datasets": ["nse_fo_volt"], "from": "2026-11-04", "to": "2026-11-04"})
    assert _wait(client.jobs, r.json()["job_id"])["result"]["to"] == "2026-11-04" and client.calls[-1].endswith("FOVOLT_04112026.csv")


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

    # FINAL round D-PIPE (P0-2/P0-3): job_watermark_check (table-unmoved verdict) and escalations_scan joined the plan
    assert {"iv_eod", "iv_intraday", "iv_weekly"} <= set(ivj.JOBS) and "index_drivers_daily" in drj.JOBS
    assert dh_api.JOB_IDS == ("data_health_refresh", "job_watermark_check", "escalations_scan")
    assert date(2026, 11, 5) and datetime(2026, 11, 5, 0, 0)


# ── API_CONTRACT §6 conformance: ui-api's fixture rows go INTO the real tables, the contract routes must give them back ──
def _ui_fixtures():
    import importlib.util

    spec = importlib.util.spec_from_file_location("_tv2_ui_fixtures", ROOT / "services" / "ui-api" / "tests" / "_terminal_v2_fixtures.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _seed(store, table: str, rows: list[dict]) -> None:
    import pandas as pd

    meta = store.read_rows(f"SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_name = '{table}'")
    cols = {r[0] for r in meta}
    df = pd.DataFrame([{k: v for k, v in r.items() if k in cols} for r in rows])
    if "index_name" in cols and "index_name" not in df.columns:
        df["index_name"] = "NIFTY 50"
    for name, dtype, nullable in meta:                     # NOT NULL columns the ui-api fixture does not carry
        if nullable == "NO" and name not in df.columns:
            df[name] = ("b76-pcp-v1" if name == "model_version" else "2026-11-04 21:05:00" if dtype.startswith("TIMESTAMP")
                        else "fixture" if dtype == "VARCHAR" else 0)
    store.write(f"INSERT INTO {table} BY NAME SELECT * FROM f", frames={"f": df})


def _same(got: list[dict], want: list[dict], keys: set[str]) -> None:
    assert len(got) == len(want), (len(got), len(want))
    for g, w in zip(got, want, strict=True):
        for k in keys:
            gv, wv = g.get(k), w.get(k)
            if isinstance(wv, float) and isinstance(gv, (int, float)):
                assert abs(gv - wv) < 1e-6, (k, gv, wv)
            elif k in ("ts", "released_at") and wv:
                assert gv and gv[:16].replace("T", " ") >= "2026", (k, gv)    # timestamps re-serialised with an offset
            else:
                assert gv == wv, (k, gv, wv)


def test_contract_routes_return_what_ui_api_reads(client):
    """5 Nov: ui-api read /db/iv/* and /db/index-drivers/{contribution,fit,state,weights} (API_CONTRACT §6) and data-service
    served neither, so OMON / DERV / EVTS / MEMB / DESK read OFFLINE with the tables populated. ui-api's own fixture rows are
    stored in the real tables; each contract route must return them with the keys ui-api composes."""
    from fo_iv import schema as iv_schema
    from index_drivers import schema as dr_schema

    fx = _ui_fixtures()
    store = client.store
    iv_schema.ensure_schema(store)
    dr_schema.ensure_schema(store)
    _seed(store, "iv_summary_daily", fx.IV_SUMMARY)
    _seed(store, "vix_daily", [r for r in fx.VIX_ROWS if r["close"] is not None])
    _seed(store, "iv_expiry_daily", fx.IV_EXPIRY_20261104 + fx.IV_EXPIRY_GHOST)
    _seed(store, "iv_surface_daily", fx.IV_SURFACE_20261104 + fx.IV_SURFACE_GHOST)
    _seed(store, "iv_event_log", fx.IV_EVENTS_INFY + fx.IV_EVENTS_NIFTY)
    _seed(store, "iv_intraday", [{**r, "model_version": "b76-pcp-v1"} for r in fx.IV_INTRADAY])
    d = fx.DRIVERS
    _seed(store, "index_contribution_daily", d["contribution"])
    _seed(store, "index_contribution_fit", d["fit"])
    _seed(store, "index_driver_state", [r for r in d["state"] if r["leader"] != "STALE"])   # the PK keeps one revision per key
    _seed(store, "index_weights_daily", d["weights"])
    _seed(store, "index_constituents_daily", [{"date": r["date"], "symbol": r["symbol"], "industry": r["industry"], "source": "fixture"}
                                              for r in d["contribution"]])

    s = client.get("/db/iv/summary?symbol=nifty&days=750").json()
    want = fx.IV_SUMMARY[-750:]
    assert s["model_version"] == "b76-pcp-v1" and s["rows"][0]["date"] < s["rows"][-1]["date"]          # ascending
    _same(s["rows"], want, {"date", "iv30_cm", "near_atm_iv", "near_expiry", "monthly_expiry", "rv20_yz", "iv_rank_252", "iv_pctile_252"})
    assert client.get("/db/iv/summary?symbol=INFY").json()["rows"] == []

    e = client.get("/db/iv/expiry?symbol=NIFTY").json()
    assert e["as_of"] == "2026-11-04"
    _same(e["rows"], sorted(fx.IV_EXPIRY_20261104, key=lambda r: r["expiry"]), {"date", "expiry", "dte", "atm_iv", "skew_25d", "forward_source", "quality_flags"})
    ghost = client.get("/db/iv/expiry?symbol=NIFTY&date=2026-10-07").json()                 # a non-stored day → the latest on or before it
    assert ghost["as_of"] == "2026-10-05" and ghost["rows"][0]["atm_iv"] == 11.2
    assert client.get("/db/iv/expiry?symbol=NIFTY&date=2026-01-01").json()["rows"] == []      # nothing on or before → empty, never a later day

    sf = client.get("/db/iv/surface?symbol=NIFTY&date=2026-11-04").json()
    assert len(sf["rows"]) == len(fx.IV_SURFACE_20261104)
    assert {"expiry", "strike", "opt_type", "iv", "delta", "log_moneyness", "oi", "volume", "price_source"} <= set(sf["rows"][0])

    ev = client.get("/db/iv/events?symbol=INFY&n=1").json()["rows"]
    assert len(ev) == 1 and ev[0]["crush_pct"] == -41.0 and ev[0]["released_at"].startswith("2026-10-16")
    it = client.get("/db/iv/intraday?symbol=NIFTY").json()
    assert it["as_of"] == "2026-11-05" and len(it["rows"]) == len(fx.IV_INTRADAY) and it["rows"][0]["ts"].endswith("+00:00")
    assert client.get("/db/iv/intraday?symbol=NIFTY&date=2026-11-06").json()["rows"] == []   # a named day is that day only
    vx = client.get("/db/iv/vix?days=10").json()["rows"]
    assert len(vx) == 10 and vx[0]["date"] < vx[-1]["date"]
    sc = client.get("/db/iv/screen").json()
    assert sc["date"] == fx.IV_SUMMARY[-1]["date"] and [r["symbol"] for r in sc["rows"]] == ["NIFTY"] and "ban" in sc["rows"][0]

    c = client.get("/db/index-drivers/contribution?index=NIFTY%2050&days=5").json()["rows"]
    assert len(c) == 15 and {r["date"] for r in c} == {r["date"] for r in d["contribution"][-15:]}
    assert {"symbol", "industry", "ret_pct", "weight_pct", "points", "prev_index_level", "date"} <= set(c[0])
    assert {r["industry"] for r in c} == {m[1] for m in fx.MEMBERS}
    f = client.get("/db/index-drivers/fit?index=NIFTY%2050&days=400").json()["rows"]
    _same(f, d["fit"], {"date", "actual_points", "explained_points", "residual_points", "prev_index_level"})
    st = client.get("/db/index-drivers/state?index=NIFTY%2050&days=5").json()["rows"]
    assert sorted((r["window_sessions"], r["leader"]) for r in st) == [(20, "HDFCBANK"), (60, "HDFCBANK")] and st[0]["change_date"] in (None, "2026-10-14")
    last = d["weights"][-1]["date"]
    w = client.get(f"/db/index-drivers/weights?index=NIFTY%2050&date={last}").json()
    assert w["as_of"] == last and {r["symbol"] for r in w["rows"]} == {m[0] for m in fx.MEMBERS} and all(r["method"] and r["industry"] for r in w["rows"])
    assert client.get("/db/index-drivers/weights?date=bogus").status_code == 422
    # negative control: an unknown index is empty, never another index's rows
    assert client.get("/db/index-drivers/contribution?index=NIFTY%20BANK").json()["rows"] == []
    assert client.calls == []

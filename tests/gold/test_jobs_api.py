"""The job registry (due rules, aliases, dormant groups, failure isolation, backfill switches) and the FastAPI router:
POST /jobs/ingest-gold, POST /jobs/gold-log, GET /db/gold/* (PLAN §c.3, §c.5)."""
from __future__ import annotations

# ruff: noqa: DTZ001
# (timestamps are UTC-naive by the store's convention)
import itertools
import json
from datetime import date, datetime, timedelta

import pytest
from _support import FIXTURES, G_CME, G_COT, G_KITCO, G_MACRO, FakeHttp, FakeResponse, read
from gold import api as gold_api
from gold import catalog_seed, db, ingest_cme, ingest_india, ingest_yahoo, jobs, pit


def _ctx(store, now, http=None, **kw):
    return jobs.Ctx(store=store, http=http or FakeHttp(), now=now, **kw)


def test_run_job_isolates_failures_and_reports_every_group(store, now, monkeypatch):
    def boom(ctx):
        raise RuntimeError("publisher down")

    monkeypatch.setitem(jobs.GROUPS, "boom", jobs.Group("boom", boom, "always"))
    res = jobs.run_job(store, FakeHttp(), "t", ["duty", "boom", "mcx_official", "nope", "events"], now=now, force=True)
    g = res["groups"]
    assert g["duty"]["status"] == "ok" and g["duty"]["inserted"] == 2
    assert g["boom"]["status"] == "error" and "publisher down" in g["boom"]["error"]
    assert g["mcx_official"]["status"] == "dormant" and "O-8" in g["mcx_official"]["reason"]
    assert g["nope"]["status"] == "unknown"
    assert g["events"]["status"] == "ok" and g["events"]["inserted"] > 50          # ran after the failure
    assert res["job"] == "t" and res["rows_total"] >= 52 and "gold_events" in res["tables"] and res["tables"]["gold_events"]["rows"] > 0


def test_due_rules_daily_weekly_monthly_force_and_backfill(store, now):
    g = jobs.GROUPS["treasury"]
    ctx = _ctx(store, now)
    assert jobs.is_due(g, ctx) == (True, "never fetched")
    db.upsert(store, "gold_series", __import__("pandas").DataFrame([{"series_id": "UST_REAL_10Y", "report_date": date(2026, 10, 23),
             "freq": "D", "value": 2.66, "release_at": now, "release_source": "rule", "first_seen_at": now - timedelta(hours=2),
             "source": "treasury_csv", "quality": "official", "revision": 0}]))
    assert jobs.is_due(g, ctx)[0] is False
    assert jobs.is_due(g, _ctx(store, now + timedelta(hours=7)))[0] is True
    assert jobs.is_due(g, _ctx(store, now, force=True)) == (True, "forced")
    assert jobs.is_due(g, _ctx(store, now, backfill_from=date(2020, 1, 1)))[0] is True
    assert jobs.is_due(jobs.GROUPS["cot"], ctx)[0] is True                       # always
    monthly = jobs.GROUPS["imf_official"]
    early = datetime(2026, 11, 3, 5, 0)
    assert jobs.is_due(monthly, _ctx(store, early)) == (True, "never fetched")          # a first fetch is never gated
    db.upsert(store, "gold_series", __import__("pandas").DataFrame([{"series_id": "IMF_GOLD_OZ_IND", "report_date": date(2026, 8, 31),
             "freq": "M", "value": 1.0, "release_at": now, "release_source": "fetch", "first_seen_at": now, "source": "imf_irfcl",
             "quality": "official", "revision": 0}]))
    assert jobs.is_due(monthly, _ctx(store, early)) == (False, "monthly: due from day 24")
    assert jobs.is_due(monthly, _ctx(store, datetime(2026, 11, 25, 5, 0)))[0] is True


def test_daily_retry_slot_runs_when_the_previous_slot_found_nothing_new(store, now, monkeypatch):
    """PLAN §c.3: the 17:15 CME retry must run when the 15:45 run still found yesterday's file — and must NOT run when
    15:45 already brought the T+1 file (the 6 h gap). The outcome of every run is recorded in gold_ingest_state."""
    files = {d: read(G_CME / f"daily_volume_{d}.xlsx", binary=True) for d in ("20261021", "20261022")}
    served = {"day": "20261021"}
    monkeypatch.setattr(jobs, "ftp_fetch", lambda url, **kw: files[served["day"]])
    g = jobs.GROUPS["cme_voi"]
    t1545_22 = datetime(2026, 10, 22, 10, 15)                                   # 15:45 IST Thu 22 Oct
    r1 = jobs.run_group("cme_voi", _ctx(store, t1545_22))
    assert r1["status"] == "ok" and r1["trade_date"] == "2026-10-21" and r1["advanced"] is True
    assert jobs.last_run(store, g)["after"] == "2026-10-21"
    due, why = jobs.is_due(g, _ctx(store, t1545_22 + timedelta(hours=1.5)))     # 17:15: nothing to retry
    assert due is False and "new data" in why
    assert jobs.run_group("cme_voi", _ctx(store, t1545_22 + timedelta(hours=1.5)))["status"] == "skipped"
    t1545_23 = datetime(2026, 10, 23, 10, 15)                                   # 15:45 IST Fri 23 Oct: the 22 Oct file is late
    r3 = jobs.run_group("cme_voi", _ctx(store, t1545_23))
    assert r3["status"] == "ok" and r3["trade_date"] == "2026-10-21" and r3["advanced"] is False   # same file, nothing new
    due, why = jobs.is_due(g, _ctx(store, t1545_23 + timedelta(hours=1.5)))     # 17:15 retry IS due
    assert due is True and "nothing new" in why
    assert jobs.is_due(g, _ctx(store, t1545_23 + timedelta(minutes=30)))[0] is False   # but not within the hour (no hammering)
    served["day"] = "20261022"
    r4 = jobs.run_group("cme_voi", _ctx(store, t1545_23 + timedelta(hours=1.5)))
    assert r4["status"] == "ok" and r4["trade_date"] == "2026-10-22" and r4["advanced"] is True
    assert jobs.run_group("cme_voi", _ctx(store, t1545_23 + timedelta(hours=3)))["status"] == "skipped"
    assert jobs.is_due(g, _ctx(store, t1545_23 + timedelta(hours=8)))[0] is True            # the 03:10 cme_voi_final slot
    # an error is recorded as "nothing new" so the retry slot runs; a forced run ignores the rule
    monkeypatch.setattr(jobs, "ftp_fetch", lambda url, **kw: (_ for _ in ()).throw(RuntimeError("ftp down")))
    r5 = jobs.run_group("cme_voi", _ctx(store, t1545_23 + timedelta(hours=8)))
    assert r5["status"] == "error" and r5["advanced"] is False and jobs.last_run(store, g)["status"] == "error"
    assert jobs.is_due(g, _ctx(store, t1545_23 + timedelta(hours=9, minutes=1)))[0] is True
    assert jobs.is_due(g, _ctx(store, t1545_23 + timedelta(hours=8, minutes=1), force=True)) == (True, "forced")


def test_monthly_groups_fetch_once_per_month_and_retry_every_three_days_until_the_value_arrives(store, monkeypatch):
    """The converse defect: an unchanged monthly re-fetch writes nothing, so MAX(first_seen_at) never advanced and
    monthly_due re-fetched every monthly group daily after publish_day. Now a run that brought the month's value gates
    the group until next month; a run that found nothing new retries after MONTHLY_GAP_H."""
    value = {"month": date(2026, 10, 31), "v": 100.0}

    def run(ctx):
        from gold import ingest_physical
        return ingest_physical.ingest_series(ctx.store, pit.series_frame("MTEST", [(value["month"], value["v"])], freq="M", source="mtest",
                                                                         now=ctx.now), now=ctx.now)

    monkeypatch.setitem(jobs.GROUPS, "mtest", jobs.Group("mtest", run, "monthly", "gold_series", "source = 'mtest'", publish_day=10))
    g = jobs.GROUPS["mtest"]
    assert jobs.is_due(g, _ctx(store, datetime(2026, 11, 9, 5, 0))) == (True, "never fetched")      # a first fetch is never gated
    day10 = datetime(2026, 11, 10, 5, 0)
    r = jobs.run_group("mtest", _ctx(store, day10))
    assert r["status"] == "ok" and r["advanced"] is True and r["inserted"] == 1
    for later in (timedelta(days=1), timedelta(days=4), timedelta(days=19)):
        due, why = jobs.is_due(g, _ctx(store, day10 + later))
        assert due is False and "fetched this month" in why                                      # not daily any more
    dec10 = datetime(2026, 12, 10, 5, 0)
    assert jobs.is_due(g, _ctx(store, datetime(2026, 12, 9, 5, 0))) == (False, "monthly: due from day 10")
    r = jobs.run_group("mtest", _ctx(store, dec10))                                              # publisher late: same value
    assert r["status"] == "ok" and r["advanced"] is False and r["unchanged"] == 1
    assert jobs.is_due(g, _ctx(store, dec10 + timedelta(days=1)))[0] is False                    # gap 72 h
    assert jobs.is_due(g, _ctx(store, dec10 + timedelta(days=3, hours=1)))[0] is True            # retry
    value.update(month=date(2026, 11, 30), v=101.0)
    r = jobs.run_group("mtest", _ctx(store, dec10 + timedelta(days=3, hours=1)))
    assert r["advanced"] is True and jobs.is_due(g, _ctx(store, dec10 + timedelta(days=7)))[0] is False
    assert "swiss" in jobs.MONTHLY_SET and jobs.GROUPS["swiss"].publish_day == 22                 # E19 refreshes on its own


def test_every_dated_group_has_a_freshness_column_so_advanced_can_be_true(store, now):
    """A dated group whose table had no FRESHNESS entry could never record ``advanced`` and would retry every hour."""
    for g in jobs.GROUPS.values():
        if g.cadence == "always" or g.table is None:
            continue
        assert g.table in jobs.FRESHNESS, g.name
        assert jobs.FRESHNESS[g.table] in __import__("gold.schema", fromlist=["COLUMNS"]).COLUMNS[g.table], g.name
        assert jobs.freshness(store, g) is None                                   # empty table → None, not an error
    assert jobs.freshness(store, jobs.GROUPS["duty"]) is None                      # an undated group has no freshness


def test_amfi_backfill_visits_every_month_end_once(store, now):
    months = jobs.amfi_months(date(2026, 10, 26), date(2018, 1, 1))
    assert months[0] == date(2017, 12, 31) and months[-1] == date(2026, 9, 30) and len(months) == 106
    assert all(m == jobs._month_end(m) for m in months)
    assert all((b.year * 12 + b.month) - (a.year * 12 + a.month) == 1 for a, b in itertools.pairwise(months))   # no month skipped
    assert jobs.amfi_months(date(2026, 10, 26), date(2026, 1, 15)) == [date(2025, 12, 31), date(2026, 1, 31), date(2026, 2, 28),
                                                                       date(2026, 3, 31), date(2026, 4, 30), date(2026, 5, 31),
                                                                       date(2026, 6, 30), date(2026, 7, 31), date(2026, 8, 31),
                                                                       date(2026, 9, 30)]
    assert jobs.amfi_months(date(2026, 10, 26)) == [date(2026, 8, 31), date(2026, 9, 30)]                 # no backfill: two months
    assert jobs.amfi_months(date(2026, 3, 1), date(2026, 2, 20)) == [date(2026, 1, 31), date(2026, 2, 28)]    # Feb's 28th is a month-end
    http = FakeHttp(default=FakeResponse(404, ""))
    res = jobs.run_group("amfi", _ctx(store, now, http=http, backfill_from=date(2018, 1, 1)))
    urls = [u for u, _ in http.calls]
    assert len(urls) == 106 and len(set(urls)) == 106 and urls[0].endswith("amdec2017repo.xls") and urls[-1].endswith("amsep2026repo.xls")
    assert res["status"] == "degraded" and res["2026-07-31"] == {"status": "http_404"}


def test_aliases_and_dormant_names():
    assert jobs.resolve("cme_voi_final") == "cme_voi" and jobs.resolve("etf") == "etf_holdings"
    assert jobs.resolve("bars_1m") == "intraday_bars" and jobs.resolve("fed_path") == "atlanta_fed"
    assert jobs.resolve("margins") == "zerodha_margins" and jobs.resolve("lbma_wgc") == "wgc_price"
    for name in ("mcx_official", "mcx_category", "breeze_daily"):
        assert name in jobs.DORMANT
    controller_groups = {"treasury", "yahoo_daily", "cme_voi_final", "fred_daily", "calendar_us", "bars_1m", "etf", "fed_path", "gpr_daily",
                         "monthly_due", "mcx_master", "margins", "health", "brief", "ibja_am", "inr_ref", "cme_voi", "cme_prf", "sge_daily",
                         "sge_benchmark", "shfe", "ibja_pm", "derive_india", "lbma_wgc", "cme_efrp", "derive_global", "cot", "wgc_etf",
                         "rbi_wss", "lbma_turnover", "wgc_premiums", "fred_weekly", "cme_calendar"}
    assert all(jobs.resolve(g) in jobs.GROUPS for g in controller_groups), [g for g in controller_groups if jobs.resolve(g) not in jobs.GROUPS]


def test_cot_group_incremental_and_not_yet(store, now):
    body = read(G_COT.parent / "scratch" / "api_gold_72hh-3qpy.json")
    http = FakeHttp({"72hh-3qpy": FakeResponse(200, body), "kh3c-gbw2": FakeResponse(200, "[]"), "6dca-aqww": FakeResponse(200, "[]"),
                     "jun7-fc8e": FakeResponse(200, "[]")})
    res = jobs.run_group("cot", _ctx(store, now, http))
    assert res["status"] == "ok" and res["datasets"]["disagg_f"]["status"] == "ok" and res["datasets"]["disagg_c"]["status"] == "not_yet"
    assert res["inserted"] > 0 and res["identity_violations"] == 0          # the datasets carry `typed`, not `inserted`: no rename
    assert "$where" in http.calls[0][1]["params"] and "cftc_contract_market_code in" in http.calls[0][1]["params"]["$where"]
    res2 = jobs.run_group("cot", _ctx(store, now, FakeHttp(default=FakeResponse(200, "[]"))))
    assert res2["not_yet"] is True and res2["inserted"] == 0


def test_yahoo_group_backs_off_on_the_monthly_trap_and_429(store, now):
    trap = read(G_KITCO / "yahoo_gcf_max_1d.json")
    http = FakeHttp({"GC=F": FakeResponse(200, trap), "SI=F": FakeResponse(429, "Too Many Requests")}, default=FakeResponse(404, ""))
    res = jobs.run_group("yahoo_daily", _ctx(store, now, http, params={"symbols": ["GC=F", "SI=F", "PL=F"]}))
    assert res["symbols"]["GC=F"]["status"] == "error" and "range=max trap" in res["symbols"]["GC=F"]["error"]
    assert res["symbols"]["SI=F"]["status"] == "http_429" and set(res["stale"]) == {"GC=F", "SI=F", "PL=F"}
    p = ingest_yahoo.daily_params(date(2000, 8, 30), date(2026, 10, 26))
    assert p["interval"] == "1d" and p["period1"] == 967593600 and "range" not in p


def test_mcx_master_group_uses_a_conditional_get(store, now, tmp_path):
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        zi = zipfile.ZipInfo("MCXScripMaster.txt", date_time=(2026, 10, 26, 7, 28, 0))
        z.writestr(zi, read(FIXTURES / "MCXScripMaster_gold_20261026.txt"))
    http = FakeHttp({"SecurityMaster.zip": FakeResponse(200, "", buf.getvalue(), {"Last-Modified": "Mon, 26 Oct 2026 01:58:26 GMT"})})
    res = jobs.run_group("mcx_master", _ctx(store, now, http))
    assert res["status"] == "ok" and res["inserted"] == 30 and res["session_date"] == "2026-10-23" and res["published"] == "2026-10-26"
    assert db.get_state(store, "mcx_master.last_modified") == "Mon, 26 Oct 2026 01:58:26 GMT"
    http2 = FakeHttp({"SecurityMaster.zip": FakeResponse(304, "")})
    res2 = jobs.run_group("mcx_master", _ctx(store, now, http2))
    assert res2["status"] == "not_modified" and http2.calls[0][1]["headers"]["If-Modified-Since"] == "Mon, 26 Oct 2026 01:58:26 GMT"
    assert ingest_india.previous_mcx_session(date(2026, 10, 26)) == date(2026, 10, 23)


def test_manual_group_accepts_only_catalogued_published_series(store, now):
    res = jobs.run_group("india_imports", _ctx(store, now, params={"values": [
        {"series_id": "INDIA_GOLD_IMPORTS_USD_BN", "report_date": "2026-09-30", "value": 1.80},
        {"series_id": "NOT_A_SERIES", "report_date": "2026-09-30", "value": 1}]}))
    assert res["inserted"] == 1 and res["rejected"] == ["NOT_A_SERIES"]
    res2 = jobs.run_group("etf_holdings", _ctx(store, now, FakeHttp(default=FakeResponse(404, ""))))
    assert res2["status"] == "degraded" and "inserted" not in res2 and res2["inserted_total"] == 0     # legs → aggregate renamed


# ── the router ──────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def client(store, now):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    submitted: list[tuple[str, dict]] = []

    def submit(kind, fn):
        res = fn(lambda a, b: None)
        submitted.append((kind, res))
        return {"job_id": f"j{len(submitted)}", "kind": kind, "status": "done", "result": res, "already_running": False}

    gold_api.configure(get_store=lambda: store, submit=submit, http=FakeHttp(default=FakeResponse(404, "")))
    app = FastAPI()
    app.include_router(gold_api.router)
    catalog_seed.seed(store)
    c = TestClient(app)
    c.submitted = submitted  # type: ignore[attr-defined]
    return c


def test_ingest_endpoint_contract(client):
    assert client.post("/jobs/ingest-gold?job=x", json={"groups": []}).status_code == 422
    assert client.post("/jobs/ingest-gold?job=x", json={"groups": ["nope"]}).status_code == 422
    r = client.post("/jobs/ingest-gold?job=gold_mcx_master", json={"job": "gold_mcx_master", "groups": ["duty", "margins", "breeze_daily"], "force": True})
    assert r.status_code == 200 and r.json()["job_id"] == "j1" and r.json()["kind"] == "gold:gold_mcx_master"
    _kind, res = client.submitted[0]
    assert res["groups"]["duty"]["status"] == "ok" and res["groups"]["margins"]["status"] == "http_404"
    assert res["groups"]["breeze_daily"]["status"] == "dormant" and "tables" in res
    r2 = client.post("/jobs/ingest-gold?job=bf&backfill_from=2026-10-01", json={"groups": ["duty"]})
    assert r2.status_code == 200 and client.submitted[1][1]["backfill_from"] == "2026-10-01"


def test_gold_log_merges_snapshot_and_capture(client):
    r = client.post("/jobs/gold-log", json={"day": "2026-10-26", "contract": "GOLD DEC-26", "baseline": 146079,
                                            "baseline_source": "MCX settlement 23 Oct (price-band midpoint)", "comex_ref": 4009.55,
                                            "comex_now": 4022.3, "inr_ref": 94.93, "inr_now": 94.9, "fair_open": 144181, "event_risk": 2,
                                            "snapshot_at": "2026-10-26T08:45:00+05:30", "inputs_json": {"window": "23:30"}})
    assert r.status_code == 200 and r.json() == {"inserted": 1, "day": "2026-10-26"}
    r = client.post("/jobs/gold-log", json={"date": "2026-10-26", "actual_open": 143000, "actual_source": "ICICI Breeze (1-min bars)",
                                            "error": -1181, "naive_error": -3079, "captured_at": "2026-10-26T09:10:00+05:30"})
    assert r.status_code == 200
    rows = client.get("/db/gold/log?days=3650").json()                       # the window is wall-clock; the fixture day is fixed
    row = rows["rows"][-1]
    assert row["day"] == "2026-10-26" and row["fair_open"] == 144181 and row["actual_open"] == 143000 and row["baseline_session"] == "2026-10-23"
    assert row["stale_baseline"] is False and json.loads(row["inputs_json"]) == {"window": "23:30"}
    # stored UTC-naive, SERVED with an explicit offset (wave 1c: no naive datetime string leaves the package)
    assert row["snapshot_at"] == "2026-10-26T03:15:00+00:00" and row["captured_at"] == "2026-10-26T03:40:00+00:00"
    assert rows["accuracy"]["days"] == 1 and rows["accuracy"]["median_abs_error"] == 1181
    assert client.post("/jobs/gold-log", json={"fair_open": 1}).status_code == 422


def test_reads_shapes(client, store, now):
    from gold import ingest_macro

    ingest_macro.ingest_treasury(store, read(G_MACRO / "data" / "treasury_real_2026.csv"), None, now=now)
    ingest_yahoo.ingest_daily(store, ingest_yahoo.parse_daily_csv(read(G_MACRO / "data" / "yahoo_GC_F.csv"), "GC=F", now=now))
    s = client.get("/db/gold/series", params={"ids": "UST_REAL_10Y,NOPE", "from": "2026-10-01", "freq": "W"}).json()
    assert s["freq"] == "W" and [x["series_id"] for x in s["series"]] == ["UST_REAL_10Y", "NOPE"]
    pt = s["series"][0]["points"][-1]
    assert pt["report_date"] == "2026-10-23" and pt["value"] == 2.66 and pt["release_at"].startswith("2026-10-23T20:30")
    assert s["series"][0]["catalog"]["badge"] == "context" and s["series"][1]["points"] == []
    asof = client.get("/db/gold/series", params={"ids": "UST_REAL_10Y", "asof": "2026-10-01T00:00:00"}).json()
    assert asof["series"][0]["points"][-1]["report_date"] < "2026-10-01"
    b = client.get("/db/gold/bars", params={"symbol": "COMEX_GC_FRONT", "interval": "1d", "from": "2026-10-01"}).json()
    assert b["symbol"] == "GC=F" and b["series_id"] == "COMEX_GC_FRONT" and b["rows"][-1]["trade_date"] == "2026-10-26"   # Monday's session, never the Sunday partial
    assert client.get("/db/gold/cot").json()["rows"] == []
    assert client.get("/db/gold/catalog").json()["count"] >= 190
    assert client.get("/db/gold/curve", params={"exchange": "MCX"}).json() == {"exchange": "MCX", "date": None, "rows": [], "ghost_1w": []}
    assert client.get("/db/gold/curve", params={"exchange": "NSE"}).status_code == 422
    today = db.utcnow().date()                                                # meta's staleness is wall-clock: seed one fresh point
    from gold import ingest_physical
    ingest_physical.ingest_series(store, pit.series_frame("UST_REAL_10Y", [(today, 2.7)], freq="D", source="treasury_csv", now=now), now=now)
    meta = client.get("/db/gold/meta").json()
    assert meta["tables"]["gold_daily_bars"]["rows"] == 6564 and meta["series"]["fresh"] >= 1 and meta["series"]["stored"] >= 1
    # the cme/prf read behind ui-api's /api/gold/contracts?exchange=COMEX comex_spec card
    assert client.get("/db/gold/cme/prf", params={"symbol": "GC"}).json() == {"symbol": "GC", "biz_date": None, "rows": []}
    ingest_cme.ingest_prf(store, read(G_CME / "cmeg.comex.fut.prf.csv.zip", binary=True), now=now, ref_prices={"GC": 4007.9})
    prf = client.get("/db/gold/cme/prf", params={"symbol": "GC"}).json()
    assert prf["biz_date"] == "2026-10-26" and len(prf["rows"]) >= 20 and all(r["symbol"] == "GC" for r in prf["rows"])
    assert prf["rows"][0]["mat_date"] <= prf["rows"][-1]["mat_date"] and any(r["mmy"] == "202612" for r in prf["rows"])
    assert client.get("/db/gold/cme/prf", params={"symbol": "MGC"}).json()["rows"] and client.get("/db/gold/cme/prf", params={"symbol": "ZZ"}).json()["rows"] == []
    assert client.get("/db/gold/cme/prf", params={"symbol": "A" * 13}).status_code == 422
    groups = client.get("/db/gold/groups").json()
    assert "cot" in groups["groups"] and groups["dormant"]["mcx_official"]
    plan = client.get("/db/gold/backfill-plan").json()["steps"]
    assert [s["order"] for s in plan] == list(range(1, 11)) and plan[1]["groups"] == ["cot"] and plan[5]["body"]["backfill_from"] == "2014-01-02"
    assert all("curl -s -X POST 'http://127.0.0.1:8001/jobs/ingest-gold?job=" in s["curl"] for s in plan)
    assert client.get("/db/gold/events", params={"from": "2026-10-26", "to": "bad"}).status_code == 422
    assert client.get("/db/gold/brief").json()["available"] is False
    assert client.get("/db/gold/fed-path").json() == {"as_of": None, "rows": []}

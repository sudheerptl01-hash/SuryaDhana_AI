"""G4 (Terminal v2 PLAN 1.7): the dataset catalog covers every ingest and every new table, ``expected_by`` is trading-day aware,
the state rule (fresh / amber / red / gap) with negative controls, ``ingest_log`` sha256 dedupe, an If-Modified-Since re-fetch
writing a revision row, explicit gap rows and their clearing. Temp DuckDB only."""
from __future__ import annotations

# ruff: noqa: DTZ001
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "data-service"))

from data_health import calendar, catalog, db, gaps, ingest_log, reads  # noqa: E402
from data_health.schema import TABLES  # noqa: E402
from shared.http_client import PacedClient  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def store(tmp_path: Path):
    from storage.duckdb_store import DuckDBStore

    s = DuckDBStore(str(tmp_path / "dh.duckdb"))
    yield s
    s.close()


def _client(handler) -> PacedClient:
    return PacedClient(transport=httpx.MockTransport(handler), sleep=lambda s: None)


# ── catalog ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_catalog_covers_every_new_table_ingest_and_job(store):
    import nse_positions
    from fo_iv import schema as iv_schema
    from index_drivers import schema as dr_schema

    n = catalog.seed(store)
    rows = catalog.build_rows()
    assert n == len(rows) >= 60
    ids = set(catalog.ids())
    for t in (*iv_schema.TABLES, *dr_schema.TABLES, "ingest_log", "data_gaps"):
        assert t in ids, t
    for ds in nse_positions.TERMINAL_DATASET_NAMES:
        if ds.endswith("_zip"):
            continue
        assert ds in ids, ds
    for job in ("iv_eod", "iv_intraday", "index_drivers_daily", "data_health_refresh", "nse_positions_catchup", "eod_data_pipeline", "results_capture_daily"):
        assert job in catalog.job_ids(), job
    for r in rows:
        assert r["badge"] != "signal" and r["verdict"] in catalog.VERDICTS and r["pages"], r["id"]
        if r["freshness_kind"] == "table":
            assert r["table_name"] and r["freshness_column"], r["id"]
    assert catalog.seed(store) == n                                       # idempotent
    assert {t for (t,) in store.read_rows("SELECT table_name FROM information_schema.tables")} >= set(TABLES)


# ── trading-day calendar and the state rule ────────────────────────────────────────────────────────────────────────

def test_expected_by_is_trading_day_aware():
    hol = {date(2026, 11, 5)}                                             # a Thursday holiday
    assert calendar.prev_trading_day(date(2026, 11, 9), hol) == date(2026, 11, 6)
    assert calendar.next_trading_day(date(2026, 11, 4), hol) == date(2026, 11, 6)
    assert calendar.sessions_between(date(2026, 11, 2), date(2026, 11, 9), hol) == 4         # 3, 4, 6, 9
    assert calendar.sessions_between(date(2026, 11, 9), date(2026, 11, 2), hol) == -4
    dl = calendar.deadline_for(date(2026, 11, 4), "23:00", 1, hol)                               # T+1 file: the next trading day is Fri 6
    assert dl == datetime(2026, 11, 6, 23, 0, tzinfo=IST)
    assert calendar.deadline_for(date(2026, 11, 4), "21:00", 0) == datetime(2026, 11, 4, 21, 0, tzinfo=IST)
    assert calendar.deadline_for(date(2026, 11, 4), None, 0) is None
    assert calendar.last_completed_session(datetime(2026, 11, 4, 15, 29, tzinfo=IST)) == date(2026, 11, 3)
    assert calendar.last_completed_session(datetime(2026, 11, 4, 15, 30, tzinfo=IST)) == date(2026, 11, 4)
    assert calendar.last_completed_session(datetime(2026, 11, 7, 12, 0, tzinfo=IST)) == date(2026, 11, 6)     # Saturday
    assert calendar.is_trading_day(date(2026, 2, 1), extra_sessions={date(2026, 2, 1)})                         # the Sunday Budget session


def _row(**kw):
    base = {"id": "x", "cadence": "daily", "freshness_kind": "table", "expected_by": "21:00", "expected_offset_days": 0, "max_age_sessions": 1}
    base.update(kw)
    return base


def test_state_rule_fresh_amber_red_gap_with_negative_controls():
    now = datetime(2026, 11, 4, 22, 30, tzinfo=IST)                      # after the 21:00 deadline for 4 Nov
    assert reads.state_for(_row(), date(2026, 11, 4), now)["state"] == "fresh"
    amber = reads.state_for(_row(), date(2026, 11, 3), now)
    assert amber["state"] == "amber" and amber["lag_sessions"] == 1 and amber["due_session"] == "2026-11-04"
    assert reads.state_for(_row(), date(2026, 10, 30), now)["state"] == "red"
    assert reads.state_for(_row(), None, now)["state"] == "red"
    # before the deadline the previous session is still fresh ("due by 21:00"), not amber
    early = datetime(2026, 11, 4, 19, 0, tzinfo=IST)
    r = reads.state_for(_row(), date(2026, 11, 3), early)
    assert r["state"] == "fresh" and r["lag_sessions"] == 1 and "due by" in r["note"]
    # T+1 datasets (MTF): the file for 3 Nov is expected by 23:00 on 4 Nov → at 22:30 on 4 Nov, stored 2 Nov is fresh for the due session (2 Nov)
    mtf = _row(expected_by="23:00", expected_offset_days=1, max_age_sessions=2)
    assert reads.state_for(mtf, date(2026, 11, 2), now)["state"] == "fresh"
    assert reads.state_for(mtf, date(2026, 10, 30), now)["state"] == "amber"
    # gap: a data_gaps row for the due session renders GAP, but only while nothing newer is stored (negative control)
    g = reads.state_for(_row(), date(2026, 11, 3), now, gap_days={date(2026, 11, 4)})
    assert g["state"] == "gap"
    assert reads.state_for(_row(), date(2026, 11, 4), now, gap_days={date(2026, 11, 4)})["state"] == "fresh"
    # endpoint / live rows are composed by ui-api
    assert reads.state_for(_row(freshness_kind="endpoint"), None, now)["state"] == "unknown"
    assert reads.state_for(_row(cadence="live"), None, now)["state"] == "unknown"
    # weekly cadence: calendar-day budget
    wk = _row(cadence="weekly", expected_by=None, max_age_sessions=7)
    assert reads.state_for(wk, date(2026, 10, 30), now)["state"] == "fresh"
    assert reads.state_for(wk, date(2026, 10, 24), now)["state"] == "amber"
    assert reads.state_for(wk, date(2026, 10, 1), now)["state"] == "red"


# ── ingest_log ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_ingest_log_sha256_dedupe_and_if_modified_since_revision(store, tmp_path):
    body = {"v": b"a,b\n1,2\n", "lm": "Wed, 04 Nov 2026 12:00:00 GMT"}
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.headers.get("If-Modified-Since") == body["lm"]:
            return httpx.Response(304, headers={"Last-Modified": body["lm"]})
        return httpx.Response(200, content=body["v"], headers={"Last-Modified": body["lm"]})

    http = _client(handler)
    url = "https://nsearchives.nseindia.com/archives/nsccl/volt/FOVOLT_04112026.csv"
    day = date(2026, 11, 4)
    t0 = datetime(2026, 11, 4, 15, 0)
    f1 = ingest_log.fetch_logged(store, http, "nse_fo_volt", day, url, cache_root=tmp_path, now=t0)
    assert f1.status == "downloaded" and f1.revision == 0 and f1.cached_path and f1.cached_path.exists()
    f2 = ingest_log.fetch_logged(store, http, "nse_fo_volt", day, url, cache_root=tmp_path, now=t0)
    assert f2.status == "cached" and len(seen) == 1                                       # the cache answers, no request
    # revalidate with the same Last-Modified → 304 → not_modified, still revision 0 (negative control: no revision row)
    f3 = ingest_log.fetch_logged(store, http, "nse_fo_volt", day, url, cache_root=tmp_path, revalidate=True, now=t0)
    assert f3.status == "not_modified" and f3.revision == 0 and seen[-1].headers.get("If-Modified-Since") == body["lm"]
    # the publisher re-publishes (new Last-Modified, same bytes) → 200 with the same sha256 → not_modified, no revision
    body["lm"] = "Wed, 04 Nov 2026 16:35:00 GMT"
    f4 = ingest_log.fetch_logged(store, http, "nse_fo_volt", day, url, cache_root=tmp_path, revalidate=True, now=t0)
    assert f4.status == "not_modified" and f4.revision == 0
    # a changed body → revised, revision 1, the cache replaced
    body["v"] = b"a,b\n1,3\n"
    body["lm"] = "Wed, 04 Nov 2026 22:05:00 GMT"
    f5 = ingest_log.fetch_logged(store, http, "nse_fo_volt", day, url, cache_root=tmp_path, revalidate=True, now=t0)
    assert f5.status == "revised" and f5.revision == 1 and f5.cached_path.read_bytes() == b"a,b\n1,3\n"
    log = store.read("SELECT status, revision, sha256 FROM ingest_log WHERE dataset = 'nse_fo_volt' ORDER BY fetched_at")
    assert list(log["status"]) == ["downloaded", "not_modified", "not_modified", "revised"]
    assert log["sha256"].iloc[0] != log["sha256"].iloc[-1] and int(log["revision"].iloc[-1]) == 1
    assert ingest_log.latest_success(store, "nse_fo_volt", day)["revision"] == 1
    # 404 → missing; an HTML body → error; neither raises
    http404 = _client(lambda r: httpx.Response(404))
    url5 = url.replace("04112026", "05112026")
    assert ingest_log.fetch_logged(store, http404, "nse_fo_volt", date(2026, 11, 5), url5, cache_root=tmp_path, now=t0).status == "missing"
    html = _client(lambda r: httpx.Response(200, content=b"<html>blocked</html>"))
    url6 = url.replace("04112026", "06112026")
    assert ingest_log.fetch_logged(store, html, "nse_fo_volt", date(2026, 11, 6), url6, cache_root=tmp_path, now=t0).status == "error"


# ── gap rows ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_gap_rows_are_written_once_and_render_as_gap(store, tmp_path):
    (tmp_path / "preopen").mkdir()
    (tmp_path / "preopen" / "2026-11-04_FO.json").write_text("{}")
    (tmp_path / "internals").mkdir()
    now = datetime(2026, 11, 5, 3, 0)
    found = gaps.detect_session_gaps(store, tmp_path, date(2026, 11, 2), date(2026, 11, 4), now=now, datasets=["archive:preopen", "archive:internals"])
    assert found["archive:preopen"] == ["2026-11-02", "2026-11-03"] and found["archive:internals"] == ["2026-11-02", "2026-11-03", "2026-11-04"]
    assert db.scalar(store, "SELECT COUNT(*) FROM data_gaps") == 5
    gaps.detect_session_gaps(store, tmp_path, date(2026, 11, 2), date(2026, 11, 4), now=now + __import__("datetime").timedelta(hours=1),
                             datasets=["archive:preopen", "archive:internals"])
    assert db.scalar(store, "SELECT COUNT(*) FROM data_gaps") == 5                           # point-in-time: never rewritten
    assert db.scalar(store, "SELECT MIN(first_seen_at) FROM data_gaps") == now
    catalog.seed(store)
    h = reads.health(store, tmp_path, now=datetime(2026, 11, 4, 10, 30))                       # 16:00 IST on 4 Nov: last session = 4 Nov
    by = {r["id"]: r for r in h["rows"]}
    assert by["archive:internals"]["state"] == "gap" and by["archive:internals"]["gap_dates"][-1] == "2026-11-04"
    assert by["archive:preopen"]["state"] == "fresh" and by["archive:preopen"]["as_of"] == "2026-11-04"   # the capture exists
    assert h["summary"]["gap"] >= 1 and "note" in h and by["desk_mark"]["state"] == "unknown"
    assert gaps.clear_if_recovered(store, "archive:internals", [date(2026, 11, 4)]) == 1
    assert db.scalar(store, "SELECT COUNT(*) FROM data_gaps") == 4


# ── the ui-api contract: /db/data-health rows carry every key ui-api's compose_b1_health reads ─────────────────────
# (services/ui-api/routers/data_health.py; its fixture B1_HEALTH mirrors these keys — check:B3-API found the ui-api
# reading max_age / t_plus / source_kind, keys this package never served)
UI_API_READS = {"id", "label", "pages", "publisher", "published_ist", "expected_by", "as_of", "lag_sessions", "state", "unrecoverable",
                "job_id", "dictionary_anchor", "badge", "max_age_sessions", "cadence", "note"}


def test_health_rows_carry_the_keys_ui_api_composes(store, tmp_path):
    catalog.seed(store)
    h = reads.health(store, tmp_path, now=datetime(2026, 11, 5, 16, 30))
    assert h["rows"] and "last_session" in h
    for r in h["rows"]:
        missing = UI_API_READS - set(r)
        assert not missing, (r["id"], missing)
        assert isinstance(r["pages"], list) and r["state"] in reads.STATES
    # negative control: the catalog table itself does NOT carry the composed keys (state / as_of / job_id come from health())
    raw = reads.catalog(store)["rows"][0]
    assert "state" not in raw and "job_id" not in raw and "ingest_job" in raw


# ── the equity bhavcopy re-publication (Wave 0 0.5; PLAN §0.3 as amended 5 Nov 2026; check:B1-DATA major) ───────────
BHAV_HEAD = ("SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, "
             "TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER\n")
BHAV_1830 = BHAV_HEAD + "INFY, EQ, 04-Nov-2026, 1500.00, 1501.00, 1510.00, 1490.00, 1505.00, 1505.50, 1502.00, 100000, 1502.00, 5000, 50000, 50.00\n"
BHAV_2205 = BHAV_HEAD + "INFY, EQ, 04-Nov-2026, 1500.00, 1501.00, 1510.00, 1490.00, 1505.00, 1506.25, 1502.00, 100000, 1502.00, 5000, 60000, 60.00\n"
LM_1830 = "Wed, 04 Nov 2026 13:05:00 GMT"        # 18:35 IST
LM_2205 = "Wed, 04 Nov 2026 16:35:00 GMT"        # 22:05 IST (R-DATA §4's measured re-publication)
DAY = date(2026, 11, 4)


def _bhav_rows(store):
    return db.query_df(store, "SELECT symbol, close, deliv_pct, first_seen_at, release_at FROM nse_bhavcopy WHERE date = ?", [DAY])


def test_http_date_parses_rfc1123_gmt_to_aware_utc():
    import bhavcopy as bc

    dt = bc.parse_http_date(LM_2205)
    assert dt is not None and dt.utcoffset() == __import__("datetime").timedelta(0) and (dt.hour, dt.minute) == (16, 35)
    assert bc.utc_naive(dt) == datetime(2026, 11, 4, 16, 35) and bc.utc_naive(dt).tzinfo is None
    # negative controls: absent / garbage → None (never "now" by accident); a zone-less date is read as GMT, not IST
    assert bc.parse_http_date(None) is None and bc.parse_http_date("yesterday evening") is None
    assert bc.utc_naive(bc.parse_http_date("Wed, 04 Nov 2026 16:35:00 -0000")) == datetime(2026, 11, 4, 16, 35)


def test_bhavcopy_first_sighting_then_the_2205_revision_is_versioned_not_overwritten(store, tmp_path):
    import bhavcopy as bc
    import nse_positions

    cache = tmp_path / "nse_bhavcopy"
    first_fetch = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=BHAV_1830, headers={"Last-Modified": LM_1830})))
    res = bc.ingest_range(store, DAY, DAY, cache, client=first_fetch)
    assert res["days_loaded"] == 1
    # the 18:30 sighting is stamped: first_seen_at (our clock), release_at = the publisher's Last-Modified, an ingest_log row
    rows = _bhav_rows(store)
    assert rows["release_at"].iloc[0] == datetime(2026, 11, 4, 13, 5) and not rows["first_seen_at"].isna().any()
    first_seen = rows["first_seen_at"].iloc[0]
    log = ingest_log.recent(store, days=3650, dataset="nse_bhavcopy")
    assert [(r["status"], r["revision"]) for r in log] == [("downloaded", 0)] and log[0]["last_modified"] == LM_1830
    first_bytes = bc.cache_path(cache, DAY).read_bytes()

    seen_ims: list[str | None] = []

    def republished(req):
        seen_ims.append(req.headers.get("If-Modified-Since"))
        return httpx.Response(200, text=BHAV_2205, headers={"Last-Modified": LM_2205})

    out = nse_positions.revise_bhavcopy(store, _client(republished), DAY, cache, now=datetime(2026, 11, 4, 17, 15))
    assert seen_ims == [LM_1830], "the conditional GET carries the 18:30 copy's Last-Modified"
    assert out["status"] == "revised" and out["revision"] == 1 and out["release_at_source"] == "last_modified"
    # both copies on disk: the first untouched, the revision beside it
    assert bc.cache_path(cache, DAY).read_bytes() == first_bytes
    assert bc.revision_paths(cache, DAY) == [bc.revision_path(cache, DAY, 1)] and out["archived"] == "2026/sec_bhavdata_full_20261104.r1.csv.gz"
    # the table holds the latest publication; release_at = the revision's Last-Modified; first_seen_at = the FIRST sighting
    rows = _bhav_rows(store)
    assert rows["close"].iloc[0] == 1506.25 and rows["deliv_pct"].iloc[0] == 60.0
    assert rows["release_at"].iloc[0] == datetime(2026, 11, 4, 16, 35) and rows["first_seen_at"].iloc[0] == first_seen != datetime(2026, 11, 4, 17, 15)
    log = ingest_log.recent(store, days=3650, dataset="nse_bhavcopy")
    assert sorted((r["status"], r["revision"]) for r in log) == [("downloaded", 0), ("revised", 1)]
    # a re-ingest from cache reads the newest copy (never silently back to the 18:30 values)
    assert bc.latest_cached_path(cache, DAY) == bc.revision_path(cache, DAY, 1)
    text, status = bc.download_day(DAY, cache, first_fetch)
    assert status == "cached" and "1506.25" in text
    # negative control: 304 → nothing written, nothing archived
    out = nse_positions.revise_bhavcopy(store, _client(lambda r: httpx.Response(304)), DAY, cache, now=datetime(2026, 11, 4, 18, 0))
    assert out["status"] == "not_modified" and len(bc.revision_paths(cache, DAY)) == 1 and _bhav_rows(store)["close"].iloc[0] == 1506.25


def test_bhavcopy_revision_edge_cases(store, tmp_path):
    import gzip

    import bhavcopy as bc
    import nse_positions

    cache = tmp_path / "nse_bhavcopy"
    def same(r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=BHAV_1830, headers={"Last-Modified": LM_1830})

    # (a) a day stored before this release (cached, in the table, no ingest_log row) answered with the same bytes: not a revision
    p = bc.cache_path(cache, DAY)
    p.parent.mkdir(parents=True)
    p.write_bytes(gzip.compress(BHAV_1830.encode()))
    store.upsert_bhavcopy(bc.parse_bhavcopy(BHAV_1830))
    out = nse_positions.revise_bhavcopy(store, _client(same), DAY, cache, now=datetime(2026, 11, 4, 17, 15))
    assert out["status"] == "not_modified" and bc.revision_paths(cache, DAY) == []
    rows = _bhav_rows(store)
    assert rows["release_at"].iloc[0] == datetime(2026, 11, 4, 13, 5) and not rows["first_seen_at"].isna().any()
    # (b) an outage day (nothing on disk, nothing stored): the 22:45 fetch is the first sighting → the FIRST copy, not r1
    d2 = date(2026, 11, 5)
    body2 = BHAV_2205.replace("04-Nov-2026", "05-Nov-2026")
    out = nse_positions.revise_bhavcopy(store, _client(lambda r: httpx.Response(200, text=body2, headers={"Last-Modified": LM_2205})),
                                        d2, cache, now=datetime(2026, 11, 5, 17, 15))
    assert out["status"] == "downloaded" and bc.cache_path(cache, d2).exists() and bc.revision_paths(cache, d2) == []
    r2 = db.query_df(store, "SELECT first_seen_at, release_at FROM nse_bhavcopy WHERE date = ?", [d2])
    assert r2["first_seen_at"].iloc[0] == datetime(2026, 11, 5, 17, 15) and r2["release_at"].iloc[0] == datetime(2026, 11, 4, 16, 35)
    # (c) a body carrying another session's rows is refused (as the 18:30 ingest refuses it): nothing archived, nothing stored
    d3 = date(2026, 11, 6)
    out = nse_positions.revise_bhavcopy(store, _client(lambda r: httpx.Response(200, text=BHAV_2205)), d3, cache, now=datetime(2026, 11, 6, 17, 15))
    assert out["status"] == "date_mismatch" and not bc.cache_path(cache, d3).exists()
    assert db.scalar(store, "SELECT COUNT(*) FROM nse_bhavcopy WHERE date = ?", [d3]) == 0
    # (d) no Last-Modified header: release_at falls back to the fetch time and says so
    d4 = date(2026, 11, 9)
    body4 = BHAV_1830.replace("04-Nov-2026", "09-Nov-2026")
    out = nse_positions.revise_bhavcopy(store, _client(lambda r: httpx.Response(200, text=body4)), d4, cache, now=datetime(2026, 11, 9, 17, 0))
    assert out["release_at_source"] == "fetch_time"

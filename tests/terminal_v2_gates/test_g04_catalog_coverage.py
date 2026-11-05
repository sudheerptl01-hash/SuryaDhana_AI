"""G4 addition: "every ingest job and every page data source has a catalog row" (PLAN 1.7), checked against the code that
schedules jobs and the code that lists pages — not against a hand list. B1's ``tests/test_data_health.py`` covers the new
tables, ``expected_by``, GAP rows, the sha256 dedupe and the If-Modified-Since revision; this file closes the loop:

* every job ``scripts/master_controller.py`` schedules (``add_job(id=…)`` + ``GOLD_JOBS``) is a catalog ``ingest_job``,
  or is named in ``NOT_AN_INGEST`` with the reason it writes no dataset, or in ``KNOWN_JOB_GAPS`` (an ingest without a
  row today, dated, with the follow-up);
* every catalog ``ingest_job`` names a job that exists (controller, gold or a data-service ``/jobs`` id);
* every page in ``ui/app/page.tsx`` COMMAND_PAGES appears in some row's ``pages``, or in ``KNOWN_PAGE_GAPS``.

A NEW job or page without a row fails (the negative controls run the same rule on an invented id). The two known-gap
lists may only shrink: an entry whose gap is closed is reported by ``test_known_gaps_are_still_gaps`` so the list is
pruned with the fix (never silently kept)."""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "data-service"))

from data_health import catalog  # noqa: E402

CONTROLLER = ROOT / "scripts" / "master_controller.py"
PAGE_TSX = ROOT / "ui" / "app" / "page.tsx"

#: scheduled jobs that write no dataset (so no freshness row) — the reason is part of the contract
NOT_AN_INGEST: dict[str, str] = {
    "close_note": "Telegram note composed from stored data",
    "morning_note": "Telegram note composed from stored data",
    "controller_heartbeat": "the controller's own heartbeat file (liveness, not data)",
    "data_health_check": "the checker that reads the data-health view",
    "db_backup_catchup": "one-off re-run of db_backup_daily (catalogued)",
    "gold_downtime_catchup": "one-off re-run of catalogued gold jobs after downtime",
    "startup_catchup": "one-off re-run of catalogued jobs after downtime",
    "icici_session_refresh_startup": "one-off run of icici_session_refresh (catalogued)",
    "morning_sweep": "08:35 pass that re-runs catalogued fetches",
    "nse_evening_pass": "22:45 pass that re-runs catalogued fetches",
    "iv_weekly": "Saturday recompute of the iv_eod tables (catalogued under iv_eod)",
    "filing_alerts": "alerts read stored filings",
    "move_alerts": "alerts read stored quotes",
    "price_alerts_check": "alerts read live quotes",
    "shared_snapshot_build": "read-only copy of market.duckdb for readers (no new data)",
    "weekly_journal": "a report written from stored data",
    "eod_rebalancing": "dormant legacy 5-day pipeline (autopilot OFF)",
    "intraday_inference": "dormant legacy 5-day pipeline (autopilot OFF)",
    "overnight_rl_retrain": "dormant legacy 5-day pipeline (autopilot OFF)",
    "pre_market_sync": "dormant legacy 5-day pipeline (autopilot OFF)",
}

#: ingests without a catalog row on 5 Nov 2026 (B6-GATES; follow-up for the catalog owner, see the B6 result)
KNOWN_JOB_GAPS: dict[str, str] = {
    "daily_wrap": "WRAP's archive reports/daily_wrap/<date>.md (WRAP shows its own chip)",
    "financials_sweep": "data/nse_archive/financials (FA / FUND pages, drivers' share counts)",
    "gold_open_capture": "gold open log (GOLD pre-open desk)",
    "gold_open_capture_evening": "gold open log, evening leg",
    "gold_intraday_bars": "COMEX 1-minute bars (gold_intraday_*)",
    "gold_india_midday": "IBJA midday leg of the India ladder",
    "gold_weekly": "WGC / RBI / LBMA weekly series",
    "gold_cme_calendar": "CME contract calendar",
}

#: catalog ingest_job values that name no scheduled or data-service job (a row that can never find its job's last run)
KNOWN_ORPHAN_INGEST_JOBS: dict[str, str] = {}

#: pages whose data source has no row (each page's own route in brackets)
KNOWN_PAGE_GAPS: dict[str, str] = {
    "ECO": "/api/market/eco-calendar",
    "SEAG": "/api/market/seasonality (stored daily bars)",
    "FUND": "/api/... fundamentals screen (data/nse_archive/financials)",
    "ALRT": "/api/alerts + live quotes",
    "IPO": "/api/market/ipo (data/nse_archive/ipo)",
    "COMP": "/api/news-scanner/chart (stored daily bars)",
    "OVRV": "legacy overview widgets (stored daily bars)",
    "PIPE": "legacy pipeline / watchlist (stored daily bars)",
    "LWSC": "legacy LW scanner (stored daily bars)",
    "CMDT": "/api/commodity/overview (Yahoo through the one cached fetcher)",
    "DEXP": "data explorer (every DuckDB table)",
}

#: data-service job ids run inside a controller pass (POST /jobs/... with ?job=)
DATA_SERVICE_JOBS = {"iv_eod", "iv_intraday", "iv_weekly", "iv_backfill", "vix_backfill", "index_drivers_daily",
                     "index_drivers_backfill", "data_health_refresh"}


def scheduled_jobs(src: str) -> set[str]:
    """Every literal ``id=`` of an ``add_job`` call plus the ``GOLD_JOBS`` keys (static: the controller is never imported)."""
    tree = ast.parse(src)
    ids: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_job":
            for kw in node.keywords:
                if kw.arg == "id" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    ids.add(kw.value.value)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "GOLD_JOBS" \
                and isinstance(node.value, ast.Dict):
            ids |= {k.value for k in node.value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    return ids


def page_codes(src: str) -> set[str]:
    m = re.search(r"const COMMAND_PAGES: CommandPage\[\] = \[(.*?)\n\]", src, re.DOTALL)
    assert m, "COMMAND_PAGES not found in ui/app/page.tsx"
    return set(re.findall(r"\{\s*id:\s*'[^']+',\s*code:\s*'([^']+)'", m.group(1)))


def uncovered_jobs(jobs: set[str], catalogued: set[str]) -> set[str]:
    return {j for j in jobs if j not in catalogued and j not in NOT_AN_INGEST and j not in KNOWN_JOB_GAPS}


def uncovered_pages(pages: set[str], catalogued_pages: set[str]) -> set[str]:
    return {p for p in pages if p not in catalogued_pages and p not in KNOWN_PAGE_GAPS}


@pytest.fixture(scope="module")
def jobs() -> set[str]:
    return scheduled_jobs(CONTROLLER.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def pages() -> set[str]:
    return page_codes(PAGE_TSX.read_text(encoding="utf-8"))


def test_the_parsers_see_the_real_registries(jobs, pages):
    assert len(pages) == 43 and {"OMON", "DERV", "MEMB", "SYS", "GOLD"} <= pages
    assert {"index_drivers_daily", "nse_evening_pass", "morning_sweep", "iv_intraday", "iv_weekly", "data_health_check",
            "gold_overnight", "eod_data_pipeline"} <= jobs and len(jobs) >= 50


def test_every_scheduled_job_has_a_row_or_a_stated_reason(jobs):
    missing = uncovered_jobs(jobs, catalog.job_ids())
    assert not missing, f"scheduled job(s) with no catalog row and no stated reason: {sorted(missing)}"


def test_every_catalog_ingest_job_names_a_real_job(jobs):
    orphans = {j for j in catalog.job_ids() if j not in jobs and j not in DATA_SERVICE_JOBS and j not in KNOWN_ORPHAN_INGEST_JOBS}
    assert not orphans, f"catalog rows name jobs that do not exist: {sorted(orphans)}"


def test_every_page_has_a_data_source_row(pages):
    missing = uncovered_pages(pages, catalog.pages())
    assert not missing, f"page(s) with no catalog row: {sorted(missing)}"
    stray = catalog.pages() - pages - {"DES", "ERN", "NEWS"}          # stock-window tabs + the news dock (not pages)
    assert not stray, f"catalog rows name unknown pages: {sorted(stray)}"


def test_negative_controls_a_new_job_or_page_without_a_row_fails(jobs, pages):
    assert uncovered_jobs(jobs | {"brand_new_ingest"}, catalog.job_ids()) == {"brand_new_ingest"}
    assert uncovered_pages(pages | {"ZZZZ"}, catalog.pages()) == {"ZZZZ"}
    assert scheduled_jobs('s.add_job(f, id="x_job")\nGOLD_JOBS: dict[str, GoldJob] = {"g1": 1}') == {"x_job", "g1"}


def test_known_gaps_are_still_gaps(jobs, pages):
    """The lists only shrink: a closed gap (or a renamed id) must leave the list with its fix."""
    stale_jobs = {j for j in KNOWN_JOB_GAPS if j in catalog.job_ids() or j not in jobs}
    stale_pages = {p for p in KNOWN_PAGE_GAPS if p in catalog.pages() or p not in pages}
    stale_orphans = {j for j in KNOWN_ORPHAN_INGEST_JOBS if j not in catalog.job_ids()}
    stale_reasons = {j for j in NOT_AN_INGEST if j not in jobs}
    assert not (stale_jobs or stale_pages or stale_orphans or stale_reasons), (
        f"prune the gate's lists: jobs {sorted(stale_jobs)} pages {sorted(stale_pages)} orphans {sorted(stale_orphans)} "
        f"reasons for unscheduled jobs {sorted(stale_reasons)}")

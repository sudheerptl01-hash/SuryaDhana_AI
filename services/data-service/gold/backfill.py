"""The one-off backfill plan (PLAN §c.4) as data: each step is a ``POST /jobs/ingest-gold`` against the RUNNING
data-service (the DuckDB file is held by that process; nothing here opens it directly), in order, with the pacing the
plan requires (CME FTP 1 file / 2 s, Yahoo one call per symbol 6 s apart with ``period1/period2``) and the expected
duration. Every step is resumable: stored dates / rows are skipped on a re-run.

The Yahoo step is CODE ONLY in this build (never run from the build machine); the owner runs it after the deploy.
"""
from __future__ import annotations

from typing import Any

DATA_SERVICE = "http://127.0.0.1:8001"


def steps() -> list[dict[str, Any]]:
    """Ordered steps; ``body`` is the JSON for ``POST {DATA_SERVICE}/jobs/ingest-gold?job=<job>``."""
    out: list[dict[str, Any]] = [
        {"order": 1, "job": "gold_backfill_catalog", "groups": ["catalog", "duty", "preopen_log", "brief", "events"],
         "body": {"groups": ["catalog", "duty", "preopen_log", "brief", "events"], "force": True},
         "expect": "catalog ~190 rows; duty 2 rows; log.json 4 rows; briefs 10 files", "duration": "seconds"},
        {"order": 2, "job": "gold_backfill_cot", "groups": ["cot"], "body": {"groups": ["cot"], "backfill_from": "1986-01-01"},
         "expect": "1,939 + 1,648 + 1,063 + 1,063 typed rows (+ micro / Coinbase); identity_violations 0", "duration": "~20 s (4 API calls)"},
        {"order": 3, "job": "gold_backfill_macro", "groups": ["treasury", "fred_daily", "fred_weekly", "fred_monthly", "gpr", "worldbank",
                                                              "atlanta_fed", "calendar_us"],
         "body": {"groups": ["treasury", "fred_daily", "fred_weekly", "fred_monthly", "gpr", "worldbank", "atlanta_fed", "calendar_us"],
                  "backfill_from": "2003-01-01"},
         "expect": "Treasury 2003→ (one file per year); FRED full CSVs (~150k rows); GPR, World Bank, Atlanta Fed 2023→", "duration": "~3 min"},
        {"order": 4, "job": "gold_backfill_physical", "groups": ["etf_holdings", "wgc_etf", "wgc_premiums", "wgc_sd", "wgc_price",
                                                                 "imf_official", "sge_benchmark", "lbma_turnover", "lbma_vault", "amfi"],
         "body": {"groups": ["etf_holdings", "wgc_etf", "wgc_premiums", "wgc_sd", "wgc_price", "imf_official", "sge_benchmark",
                             "lbma_turnover", "lbma_vault", "amfi"], "backfill_from": "2000-01-01"},
         "expect": "GLD 5,7xx rows; WGC weekly 2003→ (gated O-1); IMF top-20 from 2000-01; SGE benchmark 2,553 points; AMFI 2018→",
         "duration": "~2 min"},
        {"order": 5, "job": "gold_backfill_cme_calendar", "groups": ["cme_calendar", "cme_prf", "cme_efrp", "cme_voi"],
         "body": {"groups": ["cme_calendar", "cme_prf", "cme_efrp", "cme_voi"], "force": True},
         "expect": "calendar 304 COMEX gold/silver contracts; prf ~120 rows + margins; today's EFRP and VOI files", "duration": "~3 min (38 MB XML)"},
        {"order": 6, "job": "gold_backfill_cme_voi", "groups": ["cme_voi"],
         "body": {"groups": ["cme_voi"], "backfill_from": "2014-01-02"},
         "expect": "3,227 archive files, 1 file / 2 s, ~330 MB transient (one file in RAM at a time)", "duration": "≈2 h, resumable"},
        {"order": 7, "job": "gold_backfill_cme_efrp", "groups": ["cme_efrp"],
         "body": {"groups": ["cme_efrp"], "backfill_from": "2017-01-20"},
         "expect": "3,704 archive files, GOLD rows only kept", "duration": "≈2 h, resumable"},
        {"order": 8, "job": "gold_backfill_yahoo", "groups": ["yahoo_daily", "yahoo_curve", "intraday_bars"],
         "body": {"groups": ["yahoo_daily", "yahoo_curve", "intraday_bars"], "backfill_from": "1990-01-01"},
         "expect": "~110k daily rows across 19 symbols (one call each, 6 s apart, app UA, period1/period2); 60d/5m + 7d/1m bars",
         "duration": "~3 min — CODE ONLY in this build; run after the deploy, never while the 08:45 snapshot depends on Yahoo"},
        {"order": 9, "job": "gold_backfill_india", "groups": ["mcx_master", "zerodha_margins", "ibja_pm", "rbi_wss", "inr_ref"],
         "body": {"groups": ["mcx_master", "zerodha_margins", "ibja_pm", "rbi_wss", "inr_ref"], "backfill_from": "2026-09-01"},
         "expect": "today's master only (MCX history starts the day the job runs); IBJA 30 days from the page; RBI WSS by Friday",
         "duration": "~1 min"},
        {"order": 10, "job": "gold_backfill_derive", "groups": ["derive_india", "derive_global"],
         "body": {"groups": ["derive_india", "derive_global"], "force": True},
         "expect": "landed / duty-paid / premiums / basis / KGX / ratios / GVZ sigma / carry / put-call", "duration": "seconds"},
    ]
    for s in out:
        body: dict[str, Any] = dict(s["body"])
        body["job"] = s["job"]
        s["curl"] = (f"curl -s -X POST '{DATA_SERVICE}/jobs/ingest-gold?job={s['job']}' -H 'Content-Type: application/json' "
                     f"-d '{_json(body)}'  # then poll GET {DATA_SERVICE}/jobs/<job_id>")
    return out


def _json(obj: dict[str, Any]) -> str:
    import json

    return json.dumps(obj, separators=(",", ":"))

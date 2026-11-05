"""The ``dataset_catalog`` seed (PLAN 1.4; R-DATA §3's 45 rows + the terminal v2 tables), code not data.

One row per dataset the terminal shows: who publishes it, when (IST, *measured* where R-DATA measured it), the IST time
by which it is expected in the store (``expected_by`` on the trading day ``expected_offset_days`` after the session it
describes), the lag budget before red, the job that ingests it, how freshness is read (``freshness_kind``: ``table`` →
``MAX(column)`` of ``table_name``; ``archive`` → dated files under ``data/nse_archive/<folder>``; ``file`` → a derived
file; ``endpoint`` → composed by ui-api from telemetry / its own stores — this service reports ``unknown``), the
dictionary anchor, the verdict and the badge. ``scripts/tests`` (B6) assert every ingest job and every page's data source
has a row (the gold "no catalog row, no panel" rule, PLAN §0.12).

``max_age_sessions`` is in trading sessions for ``daily`` / ``session`` cadences and in calendar days for every other
cadence. No row carries ``signal``: no pre-registered study has passed as a forecast anywhere in the terminal.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from data_health import db
from data_health.schema import CASTS, COLUMNS

VERIFIED_AT = datetime(2026, 11, 4, 16, 50, tzinfo=timezone.utc).replace(tzinfo=None)   # R-DATA / R-IV / R-DRIVERS probes, 4 Nov 2026 22:20 IST
VERIFIED_BY = "R-DATA §3 (4 Nov 2026) + B1-DATA probes (5 Nov 2026)"
BADGES = ("signal", "context", "arithmetic", "heuristic")
VERDICTS = ("PUBLISH-CORE", "PUBLISH-CONTEXT", "LINK-ONLY", "DO-NOT-PUBLISH")
CADENCES = ("live", "session", "daily", "weekly", "monthly", "quarterly", "static", "manual", "derived")
KINDS = ("table", "archive", "file", "endpoint")
DICT = "docs/NSE_DATA_DICTIONARY.md"
TDICT = "docs/TERMINAL_DATA_DICTIONARY.md"


def _row(id_: str, label: str, pages: str, publisher: str, publish: str | None, expected_by: str | None, cadence: str,
         max_age: int, job: str | None, kind: str, *, table: str | None = None, column: str | None = None, where: str | None = None,
         offset: int = 0, unrecoverable: bool = False, anchor: str | None = None, verdict: str = "PUBLISH-CORE",
         badge: str = "arithmetic", note: str | None = None) -> dict[str, Any]:
    assert cadence in CADENCES, id_
    assert kind in KINDS, id_
    assert verdict in VERDICTS and badge in BADGES, id_
    assert badge != "signal", id_
    if kind == "table":
        assert table and column, id_
    return {"id": id_, "label": label, "pages": pages, "publisher": publisher, "publish_time_ist": publish, "expected_by": expected_by,
            "expected_offset_days": offset, "cadence": cadence, "max_age_sessions": max_age, "unrecoverable": unrecoverable,
            "ingest_job": job, "freshness_kind": kind, "table_name": table, "freshness_column": column, "freshness_where": where,
            "dictionary_anchor": anchor or f"{TDICT}#{id_}", "verdict": verdict, "badge": badge, "note": note,
            "verified_at": VERIFIED_AT, "verified_by": VERIFIED_BY}


NSE = "NSE (nsearchives.nseindia.com)"
# PLAN §0.3 as amended by the PM on 5 Nov 2026: how each kind of table versions its revisions (rendered in the dictionary)
LATEST_WINS_NOTE = ("derived: the latest computation per key (re-runs replace the row with their computed_at / first_seen_at / "
                    "model_version); a past vintage is recomputed from the archived source files versioned in ingest_log")
DERIVED_LATEST_WINS = frozenset({"iv_surface_daily", "iv_expiry_daily", "iv_summary_daily", "iv_event_log", "index_weights_daily",
                                 "index_contribution_daily", "index_contribution_fit", "index_driver_state"})
BHAVCOPY_REVISIONS_NOTE = ("revisions: the 22:45 pass re-fetches with If-Modified-Since; the table holds the LATEST publication "
                           "(release_at = the publisher's Last-Modified of that copy, first_seen_at = our first sighting of the "
                           "day); both copies stay on disk (data/nse_bhavcopy/YYYY/sec_bhavdata_full_YYYYMMDD.csv.gz = the "
                           "first, ….rN.csv.gz = revision N) and each fetch is an ingest_log row (sha256, Last-Modified, revision)")
NSEAPI = "NSE (www.nseindia.com/api)"
DERIVED = "SuryaDhana (derived)"


def build_rows() -> list[dict[str, Any]]:
    r: list[dict[str, Any]] = []
    # ── R-DATA §3 rows 1–30: the NSE / Yahoo / derived datasets ────────────────────────────────────────────────────
    r.append(_row("ohlcv", "Yahoo daily bars (1,496 tickers)", "EQS,CHRT,WHSE,DESK,BTST", "Yahoo Finance (chart API)", "~18:00", "19:00",
                  "daily", 1, "eod_data_pipeline", "table", table="ohlcv", column="date", anchor=f"{DICT}#yahoo",
                  note="PLAN §0.7: no new Yahoo caller; the existing refresh stays"))
    r.append(_row("nse_bhavcopy", "NSE equity full bhavcopy", "DES,EQS,DEAL,MKT,DESK", NSE, "~18:30; re-published 22:05 (measured)", "19:00",
                  "daily", 1, "eod_data_pipeline", "table", table="nse_bhavcopy", column="date", anchor=f"{DICT}#bhavcopy",
                  note=BHAVCOPY_REVISIONS_NOTE))
    r.append(_row("nse_fo_daily", "F&O bhavcopy per-underlying aggregate", "DERV,OMON,OSTR,MKT", NSE, "20:10 (measured)", "21:00", "daily", 1,
                  "nse_positions_catchup", "table", table="nse_fo_daily", column="date", anchor=f"{DICT}#fo-bhavcopy"))
    r.append(_row("nse_participant_oi", "Participant-wise open interest", "MKT", NSE, "20:10 (measured)", "21:00", "daily", 1,
                  "nse_positions_catchup", "table", table="nse_participant_oi", column="date", anchor=f"{DICT}#participant-oi"))
    r.append(_row("nse_deals", "Bulk / block / short-selling deals", "DEAL,DESK", NSEAPI, "evening", "21:00", "daily", 1, "nse_positions_catchup",
                  "table", table="nse_deals", column="date", anchor=f"{DICT}#deals", note="late additions appear on later days: ingest_log keeps the revisions"))
    r.append(_row("nse_mtf", "Margin-trading funded positions (T−1 file)", "MRGN", NSE, "22:12 for T−1 (measured)", "23:00", "daily", 2,
                  "nse_positions_catchup", "table", table="nse_mtf", column="date", offset=1, anchor=f"{DICT}#mtf",
                  note="structural T+1: the file for session T lands at 22:12 on T+1 (22:45 pass)"))
    r.append(_row("nse_fii_dii_cash", "FII / DII cash (NSE serves the latest day only)", "BRF,WRAP,MKT", NSEAPI, "same evening (provisional)", "21:00",
                  "session", 1, "nse_positions_catchup", "table", table="nse_fii_dii_cash", column="date", unrecoverable=True,
                  anchor=f"{DICT}#fii-dii", note="a day not fetched the same evening is lost: gap row"))
    r.append(_row("nse_insider_trades", "Insider trades (PIT, per stock)", "INSD", NSEAPI, "intimation ≈ T+2", None, "weekly", 7, "nse_filings_weekly",
                  "table", table="nse_insider_trades", column="intimation_date", anchor=f"{DICT}#insider", verdict="PUBLISH-CONTEXT", badge="context"))
    r.append(_row("nse_shareholding", "Shareholding pattern (XBRL)", "HDS", NSEAPI, "quarterly, ≤ 21 days after quarter end", None, "quarterly", 100,
                  "nse_filings_weekly", "table", table="nse_shareholding", column="period_end", anchor=f"{DICT}#shareholding", badge="context"))
    r.append(_row("nse_results", "Results release times", "ERN,EVTS,RSCH", NSEAPI, "filing timestamp (real time)", "21:30", "daily", 1,
                  "results_capture_daily", "table", table="nse_results", column="released_at", anchor=f"{DICT}#results",
                  note="catch-up window = days down + 3 (Wave 0 0.9)"))
    r.append(_row("nse_events", "Corporate calendar (results dates, board meetings, actions)", "EVTS,ERN", NSEAPI, "forward-looking", "19:00", "daily", 1,
                  "eod_data_pipeline", "table", table="nse_events", column="first_seen", anchor=f"{DICT}#events", badge="context"))
    r.append(_row("market_index_daily", "NIFTY 50 + India VIX closes (Desk series)", "DERV,MKT,RSK", "Yahoo + NSE allIndices", "15:30 close", "19:00", "daily", 1,
                  "eod_data_pipeline", "table", table="market_index_daily", column="date", where="symbol = 'NIFTY50'",
                  note="the crash filter's series; O-T9 decides whether the NSE daily file replaces it (DO NOT CHANGE without review); "
                       "every other index in this table is NSE-only (source nse_daily_file) from the first run: the PK (symbol, date) "
                       "holds one source per day, so the Yahoo rows are not kept beside them"))
    r.append(_row("market_monitor", "Market monitor (breadth, regime, market map)", "MKT,BRF,WRAP", DERIVED, "derived", "19:00", "derived", 1, "eod_data_pipeline",
                  "endpoint", note="as_of from /db/market-monitor (ui-api composes)", badge="context"))
    r.append(_row("index_valuation_history", "Index valuation history (P/E, P/B, DY)", "MKT,BRF", NSE, "ind_close_all (read 19:15; re-written 23:20)", "20:00", "daily", 1,
                  "index_valuation_daily", "file", column="csv:date", table="nse_archive/derived/index_valuation_history.csv", anchor=f"{DICT}#ind-close-all",
                  badge="context"))
    r.append(_row("option_chain_eod", "EOD option chain + IV (from the F&O file)", "OMON,OSTR", DERIVED, "from nse_fo_daily", "21:00", "derived", 1, "nse_positions_catchup",
                  "endpoint", note="computed on request from the cached F&O file; as_of = the file's date"))
    r.append(_row("option_history_json", "Legacy near-expiry ATM IV history (NIFTY, BANKNIFTY)", "DERV", DERIVED, "lazy on request", "21:00", "derived", 1, None,
                  "file", column="json:date", table="nse_archive/derived/option_history.json", verdict="PUBLISH-CONTEXT", badge="context",
                  note="superseded by iv_summary_daily; kept one release as an alias (PLAN 1.1)"))
    r.append(_row("option_chain_live", "Live option chain (NSE option-chain-v3, 30 s TTL)", "OMON", NSEAPI, "live", None, "live", 1, None, "endpoint",
                  verdict="PUBLISH-CONTEXT", badge="context", note="never stored; the 15-min Breeze pilot stores iv_intraday instead"))
    r.append(_row("archive:preopen", "Pre-open book (order imbalance)", "PRE", NSEAPI, "09:00–09:08", "09:12", "session", 1, "preopen_capture", "archive",
                  table="preopen", column="date", unrecoverable=True, anchor=f"{DICT}#preopen", badge="context"))
    r.append(_row("archive:internals", "Intraday breadth samples (2-min)", "MOV,WRAP", NSEAPI, "live 09:15–15:31", "15:35", "session", 1, "internals_sample",
                  "archive", table="internals", column="date", unrecoverable=True, anchor=f"{DICT}#internals", badge="context"))
    r.append(_row("nse_live", "NSE live quotes / movers / indices / GIFT / announcements", "MOV,WTCH,CF,BRF", NSEAPI, "live", None, "live", 1, None, "endpoint",
                  note="≤ 60 s in session; the header chip shows LINK DOWN / DELAYED"))
    r.append(_row("surveillance", "Surveillance / price bands / F&O ban list", "EQS,DESK", NSE, "evening (ban list 19:24 for the next session)", "19:30", "daily", 1,
                  None, "archive", table="surveillance", column="date", anchor=f"{DICT}#surveillance", badge="context"))
    r.append(_row("breeze_session", "ICICI Breeze session (quotes, MCX, holdings)", "BRKR,PORT,MCXG,GOLD", "ICICI Direct", "08:00 login", "08:30", "session", 1,
                  "icici_session_refresh", "endpoint", note="ui-api telemetry: logged in by 08:30 without a human (Wave 0 0.3)"))
    r.append(_row("tick_store", "Breeze live ticks (tick store)", "CHRT", "ICICI Direct", "live", None, "live", 1, None, "archive", table="ticks", column="date",
                  verdict="LINK-ONLY", badge="context", note="never armed (LIVE_TICKS=0) by decision O-T29"))
    r.append(_row("breeze_security_master", "ICICI security master", "MCXG,GOLD", "ICICI Direct", "daily", "08:00", "daily", 1, "gold_mcx_master", "file",
                  column="mtime", table="cache/breeze/SecurityMaster.zip"))
    r.append(_row("news_scanner", "News scanner JSON (owner-run)", "NEWS", "owner", "manual", None, "manual", 5, None, "archive", table="../new_scnner", column="date",
                  verdict="PUBLISH-CONTEXT", badge="context", note="news picks performed like random same-size stocks (news_scan_track_record)"))
    r.append(_row("news_track_record", "News scanner track record", "NEWS", DERIVED, "derived", "20:00", "derived", 1, "news_track_record_daily", "endpoint",
                  verdict="PUBLISH-CONTEXT", badge="context"))
    r.append(_row("desk_mark", "Decision Desk mark / plans (paper)", "DESK", DERIVED, "derived", "20:00", "derived", 1, "desk_daily", "endpoint",
                  note="ui-api composes from data/desk*.sqlite; PAPER ONLY"))
    r.append(_row("alpha_shadow", "S1 paper shadow NAV", "ALFA,RSCH", DERIVED, "derived", "20:15", "derived", 1, "alpha_shadow_daily", "file", column="mtime",
                  table="../alpha_lab/paper/state.json"))
    r.append(_row("ml_features", "ML features (dormant pipeline)", "MLEN,GBOX", DERIVED, "derived", "19:30", "derived", 1, "eod_data_pipeline", "table",
                  table="ml_features", column="date", verdict="PUBLISH-CONTEXT", badge="context", note="labels lag 5 sessions by design"))
    r.append(_row("db_backup", "Verified DuckDB backup", "SYS", DERIVED, "02:15", "03:00", "daily", 1, "db_backup_daily", "archive", table="../backups/duckdb",
                  column="date", offset=1, verdict="PUBLISH-CONTEXT", badge="context"))
    # ── R-DATA §3 rows 31–44: the gold program (tables live in the same store) ─────────────────────────────────────
    r.append(_row("gold_daily_bars", "Gold: Yahoo daily series / GC curve / 1-min bars", "GOLD,MCXG,WEI", "Yahoo (one cached fetcher)", "continuous", "04:00", "daily", 1,
                  "gold_overnight", "table", table="gold_daily_bars", column="trade_date", offset=1, anchor="docs/GOLD_DATA_DICTIONARY.md#A1", badge="context"))
    r.append(_row("gold_cot", "Gold: CFTC COT", "GOLD", "CFTC (Socrata)", "Fri 15:30 ET for Tue", None, "weekly", 9, "gold_cot_weekly", "table", table="gold_cot",
                  column="report_date", anchor="docs/GOLD_DATA_DICTIONARY.md#B10", badge="context", verdict="PUBLISH-CONTEXT"))
    r.append(_row("gold_cme_daily_voi", "Gold: CME daily OI / volume (FTP)", "GOLD", "CME Group (ftp.cmegroup.com)", "T+1 ≈ 14:30", "17:30", "daily", 2, "gold_cme_daily",
                  "table", table="gold_cme_daily_voi", column="trade_date", offset=1, anchor="docs/GOLD_DATA_DICTIONARY.md#C1", badge="context",
                  note="0 rows until the 229-EPSV fix (Wave 0 0.4)"))
    r.append(_row("gold_fred_daily", "Gold: FRED daily series (18)", "GOLD", "FRED", "~07:00 next day", "08:00", "daily", 2, "gold_fred_daily", "table", table="gold_series",
                  column="report_date", where="source = 'fred_csv' AND freq = 'D'", offset=1, anchor="docs/GOLD_DATA_DICTIONARY.md#G3", badge="context",
                  note="keyed REST + breaker (Wave 0 0.4, O-T3)"))
    r.append(_row("gold_treasury", "Gold: US Treasury real / nominal curves", "GOLD", "US Treasury", "~04:00", "08:00", "daily", 2, "gold_overnight", "table",
                  table="gold_series", column="report_date", where="source = 'treasury_csv'", offset=1, anchor="docs/GOLD_DATA_DICTIONARY.md#G2", badge="context"))
    r.append(_row("gold_etf_holdings", "Gold: GLD / IAU holdings", "GOLD", "SPDR / iShares", "~06:00", "07:00", "daily", 2, "gold_morning", "table",
                  table="gold_etf_holdings", column="report_date", offset=1, anchor="docs/GOLD_DATA_DICTIONARY.md#A4", badge="context"))
    r.append(_row("gold_asia_daily", "Gold: SGE / SHFE", "GOLD", "SGE / SHFE", "16:00", "17:00", "daily", 1, "gold_asia_close", "table", table="gold_asia_daily",
                  column="trade_date", anchor="docs/GOLD_DATA_DICTIONARY.md#D1", badge="context"))
    r.append(_row("gold_fed_path", "Gold: Atlanta Fed market-implied path", "GOLD", "Atlanta Fed", "weekly", None, "weekly", 7, "gold_morning", "table",
                  table="gold_fed_path", column="as_of", anchor="docs/GOLD_DATA_DICTIONARY.md#G17", badge="context"))
    r.append(_row("gold_curve_mcx", "Gold: MCX master / margins / price band", "GOLD,MCXG", "ICICI Breeze (security master)", "07:30", "08:00", "daily", 1,
                  "gold_mcx_master", "table", table="gold_curve", column="trade_date", where="exchange = 'MCX'", offset=1, anchor="docs/GOLD_DATA_DICTIONARY.md#F1"))
    r.append(_row("gold_india_ibja", "Gold: IBJA AM / PM, RBI reference rate", "GOLD", "IBJA / RBI", "13:30 / 18:00", "18:30", "daily", 1, "gold_india_pm", "table",
                  table="gold_series", column="report_date", where="series_id LIKE 'IBJA%'", anchor="docs/GOLD_DATA_DICTIONARY.md#E1", badge="context"))
    r.append(_row("gold_health_daily", "Gold: health snapshot", "GOLD", DERIVED, "08:40", "09:00", "session", 1, "gold_health_snapshot", "table",
                  table="gold_health_daily", column="day", badge="context", note="describes, does not predict"))
    r.append(_row("gold_brief_docs", "Gold: morning brief", "GOLD", DERIVED, "09:05", "09:30", "session", 1, "gold_brief_ingest", "table", table="gold_brief_docs",
                  column="report_date", badge="context"))
    r.append(_row("gold_preopen_log", "Gold: pre-open fair value + captured open (accuracy log)", "GOLD", DERIVED, "08:45 / 09:10", "09:15", "session", 1,
                  "gold_preopen_snapshot", "table", table="gold_preopen_log", column="day", unrecoverable=True, badge="heuristic"))
    r.append(_row("gold_events", "Gold: US calendar + compiled gold events", "GOLD", "ForexFactory / CME / compiled", "hourly 09:00–23:00", "23:30", "daily", 1,
                  "gold_calendar_refresh", "table", table="gold_events", column="first_seen_at", badge="context"))
    # ── R-DATA §3 row 45 (the verified-but-missing NSE evening files) → the new ingests (PLAN 1.1 / 1.4) ───────────
    r.append(_row("nse_fo_volt", "NSE F&O daily volatility (FOVOLT, EWMA λ=0.995)", "DERV,OMON", NSE, "≈ 17:00 (measured 16:58 on 3 Nov, 17:01 on 4 Nov)", "21:00", "daily", 1,
                  "iv_eod", "table", table="nse_fo_volt", column="date", anchor=f"{DICT}#fovolt", note="the exchange's margin vol; a third RV line"))
    r.append(_row("nse_contract_delta", "NSE contract delta factors", "OMON,DERV", NSE, "≈ 18:30–19:20 (measured 18:28 on 3 Nov, 19:18 on 4 Nov)", "21:00", "daily", 1, "iv_eod",
                  "table", table="nse_contract_delta", column="date", anchor=f"{DICT}#contract-delta", verdict="PUBLISH-CONTEXT", badge="context",
                  note="NSE's own delta beside ours; |Δ_ours − Δ_nse| > 0.05 is logged"))
    r.append(_row("nse_combined_oi", "NSE combined OI / delta-equivalent OI vs MWPL", "OMON,DERV", NSE, "19:23 (measured; deleq 19:18)", "21:00", "daily", 1,
                  "nse_positions_catchup", "table", table="nse_combined_oi", column="date", anchor=f"{DICT}#combined-oi", verdict="PUBLISH-CONTEXT", badge="context"))
    r.append(_row("nse_participant_vol", "Participant-wise trading volume (contracts)", "MKT", NSE, "20:10 (measured)", "21:00", "daily", 1, "nse_positions_catchup",
                  "table", table="nse_participant_vol", column="date", anchor=f"{DICT}#participant-vol", verdict="PUBLISH-CONTEXT", badge="context"))
    r.append(_row("nse_fii_stats", "FII derivative statistics", "MKT", NSE, "20:10 (measured)", "21:00", "daily", 1, "nse_positions_catchup", "table",
                  table="nse_fii_stats", column="date", anchor=f"{DICT}#fii-stats", verdict="PUBLISH-CONTEXT", badge="context"))
    r.append(_row("nse_mwpl_clients", "Clients ≥ 3 % of MWPL (T−1)", "OMON,DERV", NSE, "18:20 for T−1 (measured)", "21:00", "daily", 2, "nse_positions_catchup",
                  "table", table="nse_mwpl_clients", column="date", offset=1, anchor=f"{DICT}#mwpl-cli", verdict="PUBLISH-CONTEXT", badge="context"))
    # ── PLAN 1.1: the IV store ──────────────────────────────────────────────────────────────────────────────────────
    r.append(_row("index_ohlc_daily", "Every NSE index OHLC (ind_close_all)", "DERV,MKT,MEMB", NSE, "read 19:15; re-written 23:20 (measured)", "21:30", "daily", 1, "iv_eod", "table",
                  table="index_ohlc_daily", column="date", anchor=f"{DICT}#ind-close-all", note="Parkinson / Yang-Zhang inputs; the index level L for the drivers"))
    r.append(_row("vix_daily", "India VIX OHLC", "DERV,OMON", NSE, "daily file (re-written 23:20); vixhistory API for the backfill", "21:30", "daily", 1, "iv_eod", "table",
                  table="vix_daily", column="date", anchor=f"{DICT}#vix", note="one source for the VIX everywhere (PLAN 1.1 rules)"))
    r.append(_row("iv_surface_daily", "IV surface per strike (Black-76 on the parity forward)", "OMON,DERV", DERIVED, "from the F&O file (20:10)", "21:30", "daily", 1,
                  "iv_eod", "table", table="iv_surface_daily", column="date", note="scope: indices + watchlist (O-T4 default); model_version + r on every row"))
    r.append(_row("iv_expiry_daily", "IV per expiry (ATM, 25Δ / 10Δ, skew, PCR, expected move)", "OMON,DERV,EVTS", DERIVED, "from the F&O file (20:10)", "21:30", "daily", 1,
                  "iv_eod", "table", table="iv_expiry_daily", column="date"))
    r.append(_row("iv_summary_daily", "IV summary per underlying (iv30/60/90 cm, rank AND percentile, RV cc / Parkinson / YZ, FOVOLT)", "OMON,DERV,DES,EVTS",
                  DERIVED, "from the F&O file (20:10)", "21:30", "daily", 1, "iv_eod", "table", table="iv_summary_daily", column="date",
                  note="IV − RV is context, never coloured; rank and percentile both labelled by definition"))
    r.append(_row("iv_event_log", "Results IV-crush ledger", "EVTS,DES", DERIVED, "from nse_results + iv_expiry_daily", "21:30", "daily", 3, "iv_eod", "table",
                  table="iv_event_log", column="first_seen_at", verdict="PUBLISH-CONTEXT", badge="context", note="describes past events, does not forecast the next"))
    r.append(_row("iv_intraday", "Intraday IV path (15-min Breeze pilot)", "OMON", "ICICI Breeze (chain quotes)", "09:20–15:30 every 15 min", "15:45", "session", 1,
                  "iv_intraday", "table", table="iv_intraday", column="ts", unrecoverable=True, verdict="PUBLISH-CONTEXT", badge="context",
                  note="through the Breeze budget ledger only; skipped without a live session"))
    r.append(_row("archive:chain", "Raw chain snapshots (parquet parts)", "OMON", "ICICI Breeze", "09:20–15:30 every 15 min", "15:45", "session", 1, "iv_intraday",
                  "archive", table="../ticks/chain", column="date", unrecoverable=True, verdict="PUBLISH-CONTEXT", badge="context"))
    r.append(_row("rate_curve", "Risk-free rate (dated constant; O-T5)", "OMON,OSTR", DERIVED, "dated constant 6.5 %", None, "static", 400, "iv_eod", "table",
                  table="rate_curve", column="date", note="recorded as r on every IV row; a change never rewrites history"))
    # ── PLAN 1.2: the drivers ──────────────────────────────────────────────────────────────────────────────────────
    r.append(_row("index_constituents_daily", "Index constituents (NIFTY 50, NIFTY BANK), archived daily", "MEMB,MOV", "niftyindices.com", "on reconstitution",
                  "20:00", "daily", 1, "index_drivers_daily", "table", table="index_constituents_daily", column="date", anchor=f"{DICT}#constituents",
                  note="display-only posture (O-T11); members as of today applied before the first archived list"))
    r.append(_row("index_weights_daily", "Index weights: official top-10 (NSE file) + rebuilt + calibrated", "MEMB", f"{NSE} + {DERIVED}",
                  "top-10 file 16:30 (measured 4 Nov)", "20:45", "daily", 1, "index_drivers_daily", "table", table="index_weights_daily", column="date",
                  anchor=f"{DICT}#top10", note="calibration equals the official top-10 to 0.01 pp on the day the file exists"))
    r.append(_row("index_contribution_daily", "Index points per member per day (additive attribution)", "MEMB,DESK", DERIVED, "19:25 job", "20:45", "daily", 1,
                  "index_drivers_daily", "table", table="index_contribution_daily", column="date", note="an identity with its residual shown"))
    r.append(_row("index_contribution_fit", "Attribution fit (actual vs explained points, residual)", "MEMB", DERIVED, "19:25 job", "20:45", "daily", 1,
                  "index_drivers_daily", "table", table="index_contribution_fit", column="date"))
    r.append(_row("index_driver_state", "Driver regime (leader with hysteresis, concentration, breadth)", "MEMB,BRF", DERIVED, "19:25 job", "20:45", "daily", 1,
                  "index_drivers_daily", "table", table="index_driver_state", column="date", verdict="PUBLISH-CONTEXT", badge="context",
                  note="describes, does not predict; no colour on the leader"))
    # ── bookkeeping (Wave 0 0.5 / 0.9) ─────────────────────────────────────────────────────────────────────────────
    r.append(_row("ingest_log", "Ingest log (url, Last-Modified, sha256, revisions)", "SYS", DERIVED, "every fetch", None, "derived", 1, "data_health_refresh", "table",
                  table="ingest_log", column="fetched_at", verdict="PUBLISH-CONTEXT", badge="context"))
    r.append(_row("data_gaps", "Explicit gap rows for lost session captures", "SYS,MOV,WRAP,BRF", DERIVED, "08:35 sweep / start-up catch-up", None, "derived", 1,
                  "data_health_refresh", "table", table="data_gaps", column="first_seen_at", verdict="PUBLISH-CONTEXT", badge="context"))
    seen: set[str] = set()
    for row in r:
        assert row["id"] not in seen, f"duplicate catalog id {row['id']}"
        seen.add(row["id"])
        if row["id"] in DERIVED_LATEST_WINS:
            row["note"] = f"{row['note']}; {LATEST_WINS_NOTE}" if row["note"] else LATEST_WINS_NOTE
    return r


def seed_frame() -> pd.DataFrame:
    return pd.DataFrame(build_rows())


def seed(store: Any) -> int:
    """Idempotent: INSERT OR REPLACE every row (the catalog is code, not data)."""
    return db.upsert(store, "dataset_catalog", seed_frame(), COLUMNS["dataset_catalog"], CASTS["dataset_catalog"])


def ids() -> list[str]:
    return [r["id"] for r in build_rows()]


def job_ids() -> set[str]:
    return {r["ingest_job"] for r in build_rows() if r["ingest_job"]}


def pages() -> set[str]:
    return {p for r in build_rows() for p in r["pages"].split(",") if p}


def by_id(id_: str) -> dict[str, Any] | None:
    for r in build_rows():
        if r["id"] == id_:
            return r
    return None

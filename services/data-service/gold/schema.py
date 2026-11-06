"""The gold tables (PLAN §c.1, 19 tables; plus ``gold_mcx_daily``, O-8 6 Nov 2026), their casts and the ``gold_cot_metrics`` view.

Conventions (from ``storage/duckdb_store.py``): ``CREATE TABLE IF NOT EXISTS`` so a restart creates them,
``INSERT OR REPLACE`` through ``DuckDBStore._upsert(table, df, cols, casts)``. All timestamps UTC;
``report_date`` is a DATE in the publisher's calendar. Every observation carries ``release_at`` (when it
became public), ``release_source`` (``publisher`` | ``rule`` | ``fetch``) and ``first_seen_at`` (our fetch time).
"""
from __future__ import annotations

from typing import Any

GOLD_DDL = """
-- 1. the data dictionary as a table (drives the page's "about" popovers, freshness and the badge rules)
CREATE TABLE IF NOT EXISTS gold_series_catalog (
  series_id VARCHAR PRIMARY KEY, name VARCHAR NOT NULL, source_entry VARCHAR NOT NULL,
  publisher VARCHAR NOT NULL, url VARCHAR NOT NULL, freq VARCHAR NOT NULL,
  unit VARCHAR NOT NULL, publish_time_ist VARCHAR, lag_note VARCHAR,
  access VARCHAR NOT NULL, terms VARCHAR, verdict VARCHAR NOT NULL,
  verdict_reason VARCHAR, badge VARCHAR NOT NULL,
  evidence VARCHAR, beginner_note VARCHAR, pro_note VARCHAR, how_pros_use_it VARCHAR,
  resample VARCHAR NOT NULL DEFAULT 'last',
  ingest_job VARCHAR, max_age_days INTEGER NOT NULL, verified_at TIMESTAMP, verified_by VARCHAR);

-- 2. every single-value series, point-in-time
CREATE TABLE IF NOT EXISTS gold_series (
  series_id VARCHAR NOT NULL, report_date DATE NOT NULL, freq VARCHAR NOT NULL, value DOUBLE NOT NULL,
  release_at TIMESTAMP NOT NULL, release_source VARCHAR NOT NULL,
  first_seen_at TIMESTAMP NOT NULL, source VARCHAR NOT NULL, quality VARCHAR NOT NULL,
  revision INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (series_id, report_date, release_at));

-- 3. CFTC COT: raw payload + typed wide row
CREATE TABLE IF NOT EXISTS gold_cot_raw (dataset VARCHAR NOT NULL, id VARCHAR NOT NULL, report_date DATE NOT NULL,
  contract_code VARCHAR NOT NULL, market_name VARCHAR, payload JSON NOT NULL, first_seen_at TIMESTAMP NOT NULL,
  PRIMARY KEY (dataset, id));
CREATE TABLE IF NOT EXISTS gold_cot (report_date DATE NOT NULL, contract_code VARCHAR NOT NULL,
  fut_or_combined VARCHAR NOT NULL,
  report VARCHAR NOT NULL,
  open_interest BIGINT, oi_chg BIGINT,
  nc_long BIGINT, nc_short BIGINT, nc_spread BIGINT, c_long BIGINT, c_short BIGINT, nr_long BIGINT, nr_short BIGINT,
  pm_long BIGINT, pm_short BIGINT, sd_long BIGINT, sd_short BIGINT, sd_spread BIGINT,
  mm_long BIGINT, mm_short BIGINT, mm_spread BIGINT, or_long BIGINT, or_short BIGINT, or_spread BIGINT,
  chg_nc_long BIGINT, chg_nc_short BIGINT, chg_c_long BIGINT, chg_c_short BIGINT, chg_nr_long BIGINT, chg_nr_short BIGINT,
  chg_pm_long BIGINT, chg_pm_short BIGINT, chg_sd_long BIGINT, chg_sd_short BIGINT, chg_sd_spread BIGINT,
  chg_mm_long BIGINT, chg_mm_short BIGINT, chg_mm_spread BIGINT, chg_or_long BIGINT, chg_or_short BIGINT, chg_or_spread BIGINT,
  traders_total INTEGER, traders_mm_long INTEGER, traders_mm_short INTEGER, traders_mm_spread INTEGER,
  traders_sd_long INTEGER, traders_sd_short INTEGER, traders_pm_long INTEGER, traders_pm_short INTEGER,
  traders_or_long INTEGER, traders_or_short INTEGER,
  conc_gross4_long DOUBLE, conc_gross4_short DOUBLE, conc_gross8_long DOUBLE, conc_gross8_short DOUBLE,
  conc_net4_long DOUBLE, conc_net4_short DOUBLE, conc_net8_long DOUBLE, conc_net8_short DOUBLE,
  release_at TIMESTAMP NOT NULL, release_source VARCHAR NOT NULL, first_seen_at TIMESTAMP NOT NULL, source VARCHAR NOT NULL,
  PRIMARY KEY (report_date, contract_code, fut_or_combined, report));

-- 4-7. CME FTP
CREATE TABLE IF NOT EXISTS gold_cme_daily_voi (trade_date DATE NOT NULL, exchange VARCHAR NOT NULL, product_code VARCHAR NOT NULL,
  product_desc VARCHAR, fut_or_opt VARCHAR NOT NULL, globex_volume BIGINT, pit_volume BIGINT, expit_volume BIGINT, otc_volume BIGINT,
  total_volume BIGINT, mtd_adv BIGINT, open_interest BIGINT, oi_change BIGINT,
  release_at TIMESTAMP NOT NULL, first_seen_at TIMESTAMP NOT NULL, source VARCHAR NOT NULL,
  PRIMARY KEY (trade_date, exchange, product_code, fut_or_opt));
CREATE TABLE IF NOT EXISTS gold_cme_efrp (process_date DATE NOT NULL, product VARCHAR NOT NULL, product_line VARCHAR,
  txn_type VARCHAR NOT NULL, contract_expiry VARCHAR NOT NULL, fut_or_opt VARCHAR, round_turns BIGINT NOT NULL, row_no INTEGER NOT NULL,
  first_seen_at TIMESTAMP NOT NULL, PRIMARY KEY (process_date, product, txn_type, contract_expiry, row_no));
CREATE TABLE IF NOT EXISTS gold_cme_calendar (as_of DATE NOT NULL, exchange VARCHAR NOT NULL, symbol VARCHAR NOT NULL, mmy VARCHAR NOT NULL,
  first_trade DATE, last_trade DATE, ltd_end_time VARCHAR, settle_date DATE, first_intent DATE, last_intent DATE,
  first_notice DATE, last_notice DATE, first_delivery DATE, last_delivery DATE, first_seen_at TIMESTAMP NOT NULL,
  PRIMARY KEY (as_of, exchange, symbol, mmy));
CREATE TABLE IF NOT EXISTS gold_cme_prf (biz_date DATE NOT NULL, symbol VARCHAR NOT NULL, mmy VARCHAR NOT NULL, description VARCHAR,
  sec_type VARCHAR, uom VARCHAR, uom_qty DOUBLE, multiplier DOUBLE, min_px_incr DOUBLE, tick_incr_reg DOUBLE, settl_method VARCHAR,
  init_margin DOUBLE, maint_margin_field DOUBLE, mat_date DATE, first_trd DATE, last_trd DATE, first_notice DATE, last_notice DATE,
  last_efp DATE, elig_block BOOLEAN, elig_efp BOOLEAN, elig_efr BOOLEAN, first_seen_at TIMESTAMP NOT NULL,
  PRIMARY KEY (biz_date, symbol, mmy));

-- 8. settlement curve per exchange per day — source in the key so proxy and official coexist
CREATE TABLE IF NOT EXISTS gold_curve (trade_date DATE NOT NULL, exchange VARCHAR NOT NULL, symbol VARCHAR NOT NULL, expiry DATE NOT NULL,
  open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, settle DOUBLE, band_lo DOUBLE, band_hi DOUBLE, volume BIGINT, open_interest BIGINT,
  oi_change BIGINT, unit VARCHAR NOT NULL, source VARCHAR NOT NULL,
  quality VARCHAR NOT NULL, session_date DATE NOT NULL,
  release_at TIMESTAMP NOT NULL, first_seen_at TIMESTAMP NOT NULL,
  PRIMARY KEY (trade_date, exchange, symbol, expiry, source));

-- 9. margins (Zerodha NRML mirror for MCX; CME InitMargin for COMEX)
CREATE TABLE IF NOT EXISTS gold_margins (trade_date DATE NOT NULL, exchange VARCHAR NOT NULL, symbol VARCHAR NOT NULL, expiry DATE NOT NULL,
  source VARCHAR NOT NULL, margin_ccy DOUBLE, margin_pct DOUBLE, ref_price DOUBLE, first_seen_at TIMESTAMP NOT NULL,
  PRIMARY KEY (trade_date, exchange, symbol, expiry, source));

-- 10-11. bars
CREATE TABLE IF NOT EXISTS gold_daily_bars (trade_date DATE NOT NULL, symbol VARCHAR NOT NULL, open DOUBLE, high DOUBLE, low DOUBLE,
  close DOUBLE, adj_close DOUBLE, volume BIGINT, source VARCHAR NOT NULL, first_seen_at TIMESTAMP NOT NULL,
  PRIMARY KEY (trade_date, symbol, source));
CREATE TABLE IF NOT EXISTS gold_bars_intraday (symbol VARCHAR NOT NULL, ts TIMESTAMP NOT NULL, interval VARCHAR NOT NULL,
  open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT, source VARCHAR NOT NULL, first_seen_at TIMESTAMP NOT NULL,
  PRIMARY KEY (symbol, ts, interval));

-- 12. Shanghai (SGE spot/deferred, SHFE futures)
CREATE TABLE IF NOT EXISTS gold_asia_daily (trade_date DATE NOT NULL, exchange VARCHAR NOT NULL, contract VARCHAR NOT NULL,
  open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, settle DOUBLE, vwap DOUBLE, volume_kg DOUBLE, turnover DOUBLE,
  open_interest BIGINT, oi_change BIGINT, direction VARCHAR, delivery_lots BIGINT, unit VARCHAR NOT NULL, source VARCHAR NOT NULL,
  release_at TIMESTAMP NOT NULL, first_seen_at TIMESTAMP NOT NULL, PRIMARY KEY (trade_date, exchange, contract, source));

-- 13. ETF holdings (GLD, IAU; GOLDBEES AUM monthly from AMFI goes to gold_series)
CREATE TABLE IF NOT EXISTS gold_etf_holdings (report_date DATE NOT NULL, fund VARCHAR NOT NULL, tonnes DOUBLE, ounces DOUBLE, shares BIGINT,
  nav DOUBLE, aum_usd_mn DOUBLE, premium_discount DOUBLE, release_at TIMESTAMP NOT NULL, first_seen_at TIMESTAMP NOT NULL, source VARCHAR NOT NULL,
  PRIMARY KEY (report_date, fund, source));

-- 14. Fed path (Atlanta Fed MPT)
CREATE TABLE IF NOT EXISTS gold_fed_path (as_of DATE NOT NULL, meeting DATE NOT NULL, prob_cut DOUBLE, prob_hike DOUBLE, prob_hold DOUBLE,
  rate_mean_bp DOUBLE, rate_mode_bp DOUBLE, p10_bp DOUBLE, p90_bp DOUBLE, target_lo_bp INTEGER, target_hi_bp INTEGER,
  first_seen_at TIMESTAMP NOT NULL, source VARCHAR NOT NULL, PRIMARY KEY (as_of, meeting, source));

-- 15. the gold calendar
CREATE TABLE IF NOT EXISTS gold_events (event_date DATE NOT NULL, time_ist VARCHAR, kind VARCHAR NOT NULL, name VARCHAR NOT NULL, detail VARCHAR,
  country VARCHAR, impact VARCHAR, forecast VARCHAR, previous VARCHAR, actual VARCHAR, in_session BOOLEAN, source VARCHAR NOT NULL,
  first_seen_at TIMESTAMP NOT NULL, PRIMARY KEY (event_date, kind, name));

-- 16-18. pre-open log (migrates data/gold_preopen/log.json), briefs, daily health snapshot
CREATE TABLE IF NOT EXISTS gold_preopen_log (day DATE PRIMARY KEY, snapshot_at TIMESTAMP, contract VARCHAR, expiry DATE,
  baseline DOUBLE, baseline_source VARCHAR, baseline_session DATE, comex_symbol VARCHAR, comex_ref DOUBLE, comex_now DOUBLE,
  inr_ref DOUBLE, inr_now DOUBLE, fair_open DOUBLE, threshold DOUBLE, event_risk INTEGER, actual_open DOUBLE, actual_source VARCHAR,
  captured_at TIMESTAMP, error DOUBLE, naive_error DOUBLE, stale_baseline BOOLEAN, inputs_json VARCHAR);
CREATE TABLE IF NOT EXISTS gold_brief_docs (report_date DATE PRIMARY KEY, generated_at TIMESTAMP, schema_version VARCHAR, bias VARCHAR,
  bias_score DOUBLE, confidence DOUBLE, model_fair_open DOUBLE, open_signal VARCHAR, doc JSON NOT NULL, file_sha256 VARCHAR NOT NULL,
  first_seen_at TIMESTAMP NOT NULL);
CREATE TABLE IF NOT EXISTS gold_health_daily (day DATE PRIMARY KEY, snapshot_at TIMESTAMP NOT NULL, verdict VARCHAR, gauges JSON NOT NULL);

-- 19. MCX category-wise OI (dormant until a collector exists; schema fixed now)
CREATE TABLE IF NOT EXISTS gold_mcx_category_oi (as_of DATE NOT NULL, commodity VARCHAR NOT NULL, instrument VARCHAR NOT NULL,
  category VARCHAR NOT NULL, long_pos BIGINT, short_pos BIGINT, open_interest BIGINT, granularity VARCHAR NOT NULL,
  first_seen_at TIMESTAMP NOT NULL, source VARCHAR NOT NULL, PRIMARY KEY (as_of, commodity, instrument, category));

-- 20. MCX gold futures daily bars per LIVE expiry from ICICI Breeze (owner decision O-8, 6 Nov 2026; SOURCES.md F2).
-- Its own table, never gold_curve: gold_curve readers filter exchange = 'MCX' without a source, so rows there would
-- change existing panels. Volume and open interest in lots; release_at = our fetch time (a broker bar has no publisher
-- release instant), first_seen_at = the first fetch of that bar (kept on re-fetch).
CREATE TABLE IF NOT EXISTS gold_mcx_daily (trade_date DATE NOT NULL, family VARCHAR NOT NULL, expiry DATE NOT NULL,
  open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT, open_interest BIGINT,
  source VARCHAR NOT NULL, quality VARCHAR NOT NULL, release_at TIMESTAMP NOT NULL, first_seen_at TIMESTAMP NOT NULL,
  PRIMARY KEY (trade_date, family, expiry));

-- ingest bookkeeping (additive to §c.1): conditional-GET validators, backfill cursors, last run per group
CREATE TABLE IF NOT EXISTS gold_ingest_state (key VARCHAR PRIMARY KEY, value VARCHAR, updated_at TIMESTAMP NOT NULL);

-- the cheap part of gold_cot_metrics as a VIEW (nets, Δ, % OI); the windowed index/z/percentile and the
-- quadrant / fund-driver labels are computed in gold/cot_metrics.py (they need gold_daily_bars Tue→Tue prices)
CREATE OR REPLACE VIEW gold_cot_metrics AS
SELECT report_date, contract_code, fut_or_combined, report, open_interest, oi_chg,
       mm_long - mm_short AS mm_net, sd_long - sd_short AS sd_net, pm_long - pm_short AS pm_net,
       or_long - or_short AS or_net, nr_long - nr_short AS nr_net, nc_long - nc_short AS nc_net, c_long - c_short AS c_net,
       (pm_long - pm_short) + (sd_long - sd_short) AS comm_net,
       chg_mm_long - chg_mm_short AS mm_net_chg, chg_sd_long - chg_sd_short AS sd_net_chg,
       chg_pm_long - chg_pm_short AS pm_net_chg, chg_or_long - chg_or_short AS or_net_chg,
       chg_nr_long - chg_nr_short AS nr_net_chg,
       100.0 * (mm_long - mm_short) / NULLIF(open_interest, 0) AS mm_net_pct_oi,
       100.0 * mm_long / NULLIF(open_interest, 0) AS mm_long_pct_oi, 100.0 * mm_short / NULLIF(open_interest, 0) AS mm_short_pct_oi,
       100.0 * ((pm_long - pm_short) + (sd_long - sd_short)) / NULLIF(open_interest, 0) AS comm_net_pct_oi,
       (mm_long - mm_short) * 100.0 / 1e6 AS mm_net_moz, (mm_long - mm_short) * 100.0 / 32150.7466 AS mm_net_t,
       release_at, first_seen_at, source
FROM gold_cot;
"""

GOLD_TABLES: tuple[str, ...] = (
    "gold_series_catalog", "gold_series", "gold_cot_raw", "gold_cot", "gold_cme_daily_voi", "gold_cme_efrp",
    "gold_cme_calendar", "gold_cme_prf", "gold_curve", "gold_margins", "gold_daily_bars", "gold_bars_intraday",
    "gold_asia_daily", "gold_etf_holdings", "gold_fed_path", "gold_events", "gold_preopen_log", "gold_brief_docs",
    "gold_health_daily", "gold_mcx_category_oi", "gold_mcx_daily",
)
PLAN_TABLE_COUNT = 19          # §c.1; gold_ingest_state is bookkeeping on top; gold_mcx_daily (O-8, 6 Nov 2026) is additive

# The freshness column per table (for get_positions_meta / the WHSE panel).
FRESHNESS_COLUMN: dict[str, str] = {
    "gold_series": "report_date", "gold_cot": "report_date", "gold_curve": "trade_date", "gold_cme_daily_voi": "trade_date",
    "gold_cme_efrp": "process_date", "gold_daily_bars": "trade_date", "gold_bars_intraday": "ts",
    "gold_etf_holdings": "report_date", "gold_asia_daily": "trade_date", "gold_fed_path": "as_of", "gold_events": "event_date",
    "gold_preopen_log": "day", "gold_brief_docs": "report_date", "gold_health_daily": "day",
    "gold_cme_calendar": "as_of", "gold_cme_prf": "biz_date",      # wave 1c (C-TRADER-13): /db/gold/meta must show the calendar
    "gold_mcx_daily": "trade_date",
}


def ddl_statements() -> list[str]:
    """The CREATE statements, one per entry (the store runs them at every start; all are IF NOT EXISTS / OR REPLACE).
    Comment lines are dropped first so a ``;`` inside a comment can never split a statement."""
    body = "\n".join(line for line in GOLD_DDL.splitlines() if not line.lstrip().startswith("--"))
    return [s.strip() for s in body.split(";") if s.strip()]


def ensure_schema(store: Any) -> None:
    """Create the gold tables on ``store`` (idempotent). ``DuckDBStore._init_schema`` does the same at start-up."""
    with store.writer() as con:
        for stmt in ddl_statements():
            con.execute(stmt)


def positions_meta(store: Any) -> dict[str, dict[str, Any]]:
    """{table: {first, last, rows}} for the freshness-bearing gold tables (the WHSE panel / pre_market_sync rows)."""
    out: dict[str, dict[str, Any]] = {}
    with store.reader() as con:
        for table, col in FRESHNESS_COLUMN.items():
            try:
                lo, hi, n = con.execute(f"SELECT MIN({col}), MAX({col}), COUNT(*) FROM {table}").fetchone()
                out[table] = {"first": str(lo)[:19] if lo else None, "last": str(hi)[:19] if hi else None, "rows": int(n or 0)}
            except Exception as exc:  # noqa: BLE001 — a store opened before the gold DDL ran
                out[table] = {"first": None, "last": None, "rows": 0, "error": type(exc).__name__}
    return out

_TS = "TIMESTAMP"
_D = "DATE"

# Column order + casts per table (the ``_upsert`` contract). Every column of the DDL is listed, in DDL order.
COLUMNS: dict[str, list[str]] = {
    "gold_series_catalog": ["series_id", "name", "source_entry", "publisher", "url", "freq", "unit", "publish_time_ist",
                            "lag_note", "access", "terms", "verdict", "verdict_reason", "badge", "evidence", "beginner_note",
                            "pro_note", "how_pros_use_it", "resample", "ingest_job", "max_age_days", "verified_at", "verified_by"],
    "gold_series": ["series_id", "report_date", "freq", "value", "release_at", "release_source", "first_seen_at", "source",
                    "quality", "revision"],
    "gold_cot_raw": ["dataset", "id", "report_date", "contract_code", "market_name", "payload", "first_seen_at"],
    "gold_cot": ["report_date", "contract_code", "fut_or_combined", "report", "open_interest", "oi_chg",
                 "nc_long", "nc_short", "nc_spread", "c_long", "c_short", "nr_long", "nr_short",
                 "pm_long", "pm_short", "sd_long", "sd_short", "sd_spread", "mm_long", "mm_short", "mm_spread",
                 "or_long", "or_short", "or_spread",
                 "chg_nc_long", "chg_nc_short", "chg_c_long", "chg_c_short", "chg_nr_long", "chg_nr_short",
                 "chg_pm_long", "chg_pm_short", "chg_sd_long", "chg_sd_short", "chg_sd_spread",
                 "chg_mm_long", "chg_mm_short", "chg_mm_spread", "chg_or_long", "chg_or_short", "chg_or_spread",
                 "traders_total", "traders_mm_long", "traders_mm_short", "traders_mm_spread", "traders_sd_long",
                 "traders_sd_short", "traders_pm_long", "traders_pm_short", "traders_or_long", "traders_or_short",
                 "conc_gross4_long", "conc_gross4_short", "conc_gross8_long", "conc_gross8_short",
                 "conc_net4_long", "conc_net4_short", "conc_net8_long", "conc_net8_short",
                 "release_at", "release_source", "first_seen_at", "source"],
    "gold_cme_daily_voi": ["trade_date", "exchange", "product_code", "product_desc", "fut_or_opt", "globex_volume", "pit_volume",
                           "expit_volume", "otc_volume", "total_volume", "mtd_adv", "open_interest", "oi_change", "release_at",
                           "first_seen_at", "source"],
    "gold_cme_efrp": ["process_date", "product", "product_line", "txn_type", "contract_expiry", "fut_or_opt", "round_turns",
                      "row_no", "first_seen_at"],
    "gold_cme_calendar": ["as_of", "exchange", "symbol", "mmy", "first_trade", "last_trade", "ltd_end_time", "settle_date",
                          "first_intent", "last_intent", "first_notice", "last_notice", "first_delivery", "last_delivery",
                          "first_seen_at"],
    "gold_cme_prf": ["biz_date", "symbol", "mmy", "description", "sec_type", "uom", "uom_qty", "multiplier", "min_px_incr",
                     "tick_incr_reg", "settl_method", "init_margin", "maint_margin_field", "mat_date", "first_trd", "last_trd",
                     "first_notice", "last_notice", "last_efp", "elig_block", "elig_efp", "elig_efr", "first_seen_at"],
    "gold_curve": ["trade_date", "exchange", "symbol", "expiry", "open", "high", "low", "close", "settle", "band_lo", "band_hi",
                   "volume", "open_interest", "oi_change", "unit", "source", "quality", "session_date", "release_at", "first_seen_at"],
    "gold_margins": ["trade_date", "exchange", "symbol", "expiry", "source", "margin_ccy", "margin_pct", "ref_price", "first_seen_at"],
    "gold_daily_bars": ["trade_date", "symbol", "open", "high", "low", "close", "adj_close", "volume", "source", "first_seen_at"],
    "gold_bars_intraday": ["symbol", "ts", "interval", "open", "high", "low", "close", "volume", "source", "first_seen_at"],
    "gold_asia_daily": ["trade_date", "exchange", "contract", "open", "high", "low", "close", "settle", "vwap", "volume_kg",
                        "turnover", "open_interest", "oi_change", "direction", "delivery_lots", "unit", "source", "release_at",
                        "first_seen_at"],
    "gold_etf_holdings": ["report_date", "fund", "tonnes", "ounces", "shares", "nav", "aum_usd_mn", "premium_discount",
                          "release_at", "first_seen_at", "source"],
    "gold_fed_path": ["as_of", "meeting", "prob_cut", "prob_hike", "prob_hold", "rate_mean_bp", "rate_mode_bp", "p10_bp", "p90_bp",
                      "target_lo_bp", "target_hi_bp", "first_seen_at", "source"],
    "gold_events": ["event_date", "time_ist", "kind", "name", "detail", "country", "impact", "forecast", "previous", "actual",
                    "in_session", "source", "first_seen_at"],
    "gold_preopen_log": ["day", "snapshot_at", "contract", "expiry", "baseline", "baseline_source", "baseline_session",
                         "comex_symbol", "comex_ref", "comex_now", "inr_ref", "inr_now", "fair_open", "threshold", "event_risk",
                         "actual_open", "actual_source", "captured_at", "error", "naive_error", "stale_baseline", "inputs_json"],
    "gold_brief_docs": ["report_date", "generated_at", "schema_version", "bias", "bias_score", "confidence", "model_fair_open",
                        "open_signal", "doc", "file_sha256", "first_seen_at"],
    "gold_health_daily": ["day", "snapshot_at", "verdict", "gauges"],
    "gold_mcx_category_oi": ["as_of", "commodity", "instrument", "category", "long_pos", "short_pos", "open_interest",
                             "granularity", "first_seen_at", "source"],
    "gold_mcx_daily": ["trade_date", "family", "expiry", "open", "high", "low", "close", "volume", "open_interest", "source", "quality",
                       "release_at", "first_seen_at"],
    "gold_ingest_state": ["key", "value", "updated_at"],
}

_BIG = "BIGINT"
_INT = "INTEGER"
_DBL = "DOUBLE"

CASTS: dict[str, dict[str, str]] = {
    "gold_series_catalog": {"max_age_days": _INT, "verified_at": _TS},
    "gold_series": {"report_date": _D, "value": _DBL, "release_at": _TS, "first_seen_at": _TS, "revision": _INT},
    "gold_cot_raw": {"report_date": _D, "payload": "JSON", "first_seen_at": _TS},
    "gold_cot": {"report_date": _D, "release_at": _TS, "first_seen_at": _TS,
                 **{c: _BIG for c in COLUMNS["gold_cot"] if c.startswith(("chg_", "nc_", "c_", "nr_", "pm_", "sd_", "mm_", "or_"))
                    or c in ("open_interest", "oi_chg")},
                 **{c: _INT for c in COLUMNS["gold_cot"] if c.startswith("traders_")},
                 **{c: _DBL for c in COLUMNS["gold_cot"] if c.startswith("conc_")}},
    "gold_cme_daily_voi": {"trade_date": _D, "release_at": _TS, "first_seen_at": _TS,
                           **{c: _BIG for c in ("globex_volume", "pit_volume", "expit_volume", "otc_volume", "total_volume",
                                                "mtd_adv", "open_interest", "oi_change")}},
    "gold_cme_efrp": {"process_date": _D, "round_turns": _BIG, "row_no": _INT, "first_seen_at": _TS},
    "gold_cme_calendar": {**{c: _D for c in ("as_of", "first_trade", "last_trade", "settle_date", "first_intent", "last_intent",
                                              "first_notice", "last_notice", "first_delivery", "last_delivery")},
                          "first_seen_at": _TS},
    "gold_cme_prf": {**{c: _D for c in ("biz_date", "mat_date", "first_trd", "last_trd", "first_notice", "last_notice", "last_efp")},
                     **{c: _DBL for c in ("uom_qty", "multiplier", "min_px_incr", "tick_incr_reg", "init_margin", "maint_margin_field")},
                     **{c: "BOOLEAN" for c in ("elig_block", "elig_efp", "elig_efr")}, "first_seen_at": _TS},
    "gold_curve": {"trade_date": _D, "expiry": _D, "session_date": _D, "release_at": _TS, "first_seen_at": _TS,
                   **{c: _DBL for c in ("open", "high", "low", "close", "settle", "band_lo", "band_hi")},
                   "volume": _BIG, "open_interest": _BIG, "oi_change": _BIG},
    "gold_margins": {"trade_date": _D, "expiry": _D, "margin_ccy": _DBL, "margin_pct": _DBL, "ref_price": _DBL, "first_seen_at": _TS},
    "gold_daily_bars": {"trade_date": _D, "first_seen_at": _TS, "volume": _BIG,
                        **{c: _DBL for c in ("open", "high", "low", "close", "adj_close")}},
    "gold_bars_intraday": {"ts": _TS, "first_seen_at": _TS, "volume": _BIG, **{c: _DBL for c in ("open", "high", "low", "close")}},
    "gold_asia_daily": {"trade_date": _D, "release_at": _TS, "first_seen_at": _TS,
                        **{c: _DBL for c in ("open", "high", "low", "close", "settle", "vwap", "volume_kg", "turnover")},
                        "open_interest": _BIG, "oi_change": _BIG, "delivery_lots": _BIG},
    "gold_etf_holdings": {"report_date": _D, "release_at": _TS, "first_seen_at": _TS, "shares": _BIG,
                          **{c: _DBL for c in ("tonnes", "ounces", "nav", "aum_usd_mn", "premium_discount")}},
    "gold_fed_path": {"as_of": _D, "meeting": _D, "first_seen_at": _TS, "target_lo_bp": _INT, "target_hi_bp": _INT,
                      **{c: _DBL for c in ("prob_cut", "prob_hike", "prob_hold", "rate_mean_bp", "rate_mode_bp", "p10_bp", "p90_bp")}},
    "gold_events": {"event_date": _D, "in_session": "BOOLEAN", "first_seen_at": _TS},
    "gold_preopen_log": {"day": _D, "expiry": _D, "baseline_session": _D, "snapshot_at": _TS, "captured_at": _TS,
                         "event_risk": _INT, "stale_baseline": "BOOLEAN",
                         **{c: _DBL for c in ("baseline", "comex_ref", "comex_now", "inr_ref", "inr_now", "fair_open", "threshold",
                                              "actual_open", "error", "naive_error")}},
    "gold_brief_docs": {"report_date": _D, "generated_at": _TS, "first_seen_at": _TS, "doc": "JSON",
                        **{c: _DBL for c in ("bias_score", "confidence", "model_fair_open")}},
    "gold_health_daily": {"day": _D, "snapshot_at": _TS, "gauges": "JSON"},
    "gold_mcx_category_oi": {"as_of": _D, "first_seen_at": _TS, "long_pos": _BIG, "short_pos": _BIG, "open_interest": _BIG},
    "gold_mcx_daily": {"trade_date": _D, "expiry": _D, "release_at": _TS, "first_seen_at": _TS,
                       **{c: _DBL for c in ("open", "high", "low", "close")}, "volume": _BIG, "open_interest": _BIG},
    "gold_ingest_state": {"updated_at": _TS},
}

BATCH_ROWS = 50_000     # memory discipline (15 Oct OOM incident): never hand DuckDB more than this per insert

"""The IV tables (PLAN 1.1; R-IV §6 DDL adopted, plus ``first_seen_at`` where R-IV left it implicit and the three NSE
context tables FOVOLT / Contract_Delta / combined OI). ``CREATE TABLE IF NOT EXISTS`` so a restart creates them; the store's
``_init_schema`` runs ``ddl_statements()`` through a guarded import. Point-in-time: every row carries the session it
describes (``date``), our fetch / compute time (``first_seen_at``) and, where a model is involved, ``model_version`` and
``r``.

Vintages (PLAN §0.3 as amended by the PM on 5 Nov 2026): the four DERIVED tables ``iv_surface_daily``, ``iv_expiry_daily``,
``iv_summary_daily`` and ``iv_event_log`` keep the LATEST computation per natural key — a re-run (the 22:45 retry, a
backfill resume, a ``model_version`` bump) replaces the row in place, ``first_seen_at`` / ``model_version`` / ``r`` updated
with it. A past vintage is reproducible because every SOURCE file (the F&O bhavcopies, FOVOLT, Contract_Delta, the index
file) is archived on disk and versioned in ``ingest_log`` (url, fetched_at, publisher Last-Modified, sha256); a study that
needs one recomputes it from those files. The source tables (``nse_fo_volt``, ``nse_contract_delta``, ``nse_combined_oi``,
``vix_daily``, ``index_ohlc_daily``) hold what the publisher's latest copy says, revisions logged in ``ingest_log``.
"""
from __future__ import annotations

from typing import Any

DDL = """
-- per strike, per expiry, per session: the surface (indices + watchlist by default; all 224 on O-T4)
CREATE TABLE IF NOT EXISTS iv_surface_daily (
  date DATE NOT NULL, symbol VARCHAR NOT NULL, expiry DATE NOT NULL, strike DOUBLE NOT NULL, opt_type VARCHAR NOT NULL,
  price DOUBLE, price_source VARCHAR, forward DOUBLE, forward_source VARCHAR,
  t_years DOUBLE, r DOUBLE, iv DOUBLE, delta DOUBLE, vega DOUBLE,
  oi DOUBLE, oi_chg DOUBLE, volume DOUBLE, lot INTEGER, log_moneyness DOUBLE,
  model_version VARCHAR NOT NULL, source_file VARCHAR, first_seen_at TIMESTAMP NOT NULL,
  PRIMARY KEY (date, symbol, expiry, strike, opt_type));

-- per expiry per session: ATM, skew, counts (all underlyings, ~400 rows/day)
CREATE TABLE IF NOT EXISTS iv_expiry_daily (
  date DATE NOT NULL, symbol VARCHAR NOT NULL, expiry DATE NOT NULL, dte INTEGER, forward DOUBLE, forward_source VARCHAR,
  atm_iv DOUBLE, iv_25d_put DOUBLE, iv_25d_call DOUBLE, skew_25d DOUBLE, iv_10d_put DOUBLE, iv_10d_call DOUBLE,
  n_iv_strikes INTEGER, call_oi DOUBLE, put_oi DOUBLE, pcr DOUBLE, expected_move_pct DOUBLE,
  quality_flags VARCHAR, model_version VARCHAR NOT NULL, r DOUBLE, first_seen_at TIMESTAMP NOT NULL,
  PRIMARY KEY (date, symbol, expiry));

-- per underlying per session: the series every page charts (~224 rows/day)
CREATE TABLE IF NOT EXISTS iv_summary_daily (
  date DATE NOT NULL, symbol VARCHAR NOT NULL, spot DOUBLE, spot_source VARCHAR,
  iv30_cm DOUBLE, iv60_cm DOUBLE, iv90_cm DOUBLE, near_atm_iv DOUBLE, near_expiry DATE, near_dte INTEGER,
  monthly_atm_iv DOUBLE, monthly_expiry DATE, skew_25d_30 DOUBLE, term_slope_30_90 DOUBLE,
  iv_rank_252 DOUBLE, iv_pctile_252 DOUBLE, rv20_cc DOUBLE, rv20_parkinson DOUBLE, rv20_yz DOUBLE, fovolt_ann DOUBLE,
  iv_minus_rv20 DOUBLE, expected_move_1d_pct DOUBLE, quality_flags VARCHAR, model_version VARCHAR NOT NULL, r DOUBLE,
  first_seen_at TIMESTAMP NOT NULL,
  PRIMARY KEY (date, symbol));

-- India VIX OHLC (ind_close_all daily; the vixhistory API for the one-off backfill)
CREATE TABLE IF NOT EXISTS vix_daily (date DATE PRIMARY KEY, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, prev_close DOUBLE,
  source VARCHAR NOT NULL, first_seen_at TIMESTAMP NOT NULL);

-- every NSE index OHLC from ind_close_all (Parkinson / Yang-Zhang; the drivers' index level L)
CREATE TABLE IF NOT EXISTS index_ohlc_daily (symbol VARCHAR NOT NULL, date DATE NOT NULL, open DOUBLE, high DOUBLE, low DOUBLE,
  close DOUBLE, source VARCHAR NOT NULL, first_seen_at TIMESTAMP NOT NULL, PRIMARY KEY (symbol, date));

-- results IV-crush ledger (context: describes past events, does not forecast the next)
CREATE TABLE IF NOT EXISTS iv_event_log (symbol VARCHAR NOT NULL, released_at TIMESTAMP NOT NULL, expiry DATE,
  iv_pre_5d DOUBLE, iv_pre_1d DOUBLE, iv_post_1d DOUBLE, crush_pct DOUBLE, implied_move_pct DOUBLE, realised_move_pct DOUBLE,
  pre_session DATE, post_session DATE, implied_method VARCHAR, model_version VARCHAR, first_seen_at TIMESTAMP NOT NULL,
  PRIMARY KEY (symbol, released_at));

-- the 15-minute pilot (derived rows; the raw chain snapshots are parquet parts under data/ticks/chain/<date>/)
CREATE TABLE IF NOT EXISTS iv_intraday (ts TIMESTAMP NOT NULL, symbol VARCHAR NOT NULL, expiry DATE NOT NULL, strike DOUBLE NOT NULL,
  opt_type VARCHAR NOT NULL, mid DOUBLE, iv DOUBLE, nse_iv DOUBLE, oi DOUBLE, forward DOUBLE, spot DOUBLE, source VARCHAR NOT NULL,
  model_version VARCHAR NOT NULL, r DOUBLE, first_seen_at TIMESTAMP NOT NULL,
  PRIMARY KEY (ts, symbol, expiry, strike, opt_type, source));

-- the dated risk-free rate (O-T5: a constant until the owner chooses the RBI 91-day T-bill)
CREATE TABLE IF NOT EXISTS rate_curve (date DATE NOT NULL, tenor VARCHAR NOT NULL, rate DOUBLE NOT NULL, source VARCHAR NOT NULL,
  first_seen_at TIMESTAMP NOT NULL, PRIMARY KEY (date, tenor, source));

-- NSE's own EWMA volatility per underlying (FOVOLT, λ = 0.995, annualised × √365)
CREATE TABLE IF NOT EXISTS nse_fo_volt (date DATE NOT NULL, symbol VARCHAR NOT NULL, close DOUBLE, prev_close DOUBLE, log_return DOUBLE,
  ewma_daily_vol DOUBLE, ann_vol DOUBLE, fut_vol DOUBLE, fut_ann_vol DOUBLE, applicable_ann_vol DOUBLE, first_seen_at TIMESTAMP NOT NULL,
  PRIMARY KEY (date, symbol));

-- NSE's delta per contract (margins): the cross-check column
CREATE TABLE IF NOT EXISTS nse_contract_delta (date DATE NOT NULL, symbol VARCHAR NOT NULL, expiry DATE NOT NULL, strike DOUBLE NOT NULL,
  opt_type VARCHAR NOT NULL, delta_factor DOUBLE, first_seen_at TIMESTAMP NOT NULL, PRIMARY KEY (date, symbol, expiry, strike, opt_type));

-- combined OI / delta-equivalent OI vs MWPL (crowding context; the deleq file carries notional + futures-equivalent OI,
-- the combineoi zip the MWPL / OI / next-day limit)
CREATE TABLE IF NOT EXISTS nse_combined_oi (date DATE NOT NULL, symbol VARCHAR NOT NULL, isin VARCHAR, mwpl DOUBLE, oi DOUBLE,
  fut_equiv_oi DOUBLE, limit_next_day DOUBLE, notional_oi DOUBLE, first_seen_at TIMESTAMP NOT NULL, PRIMARY KEY (date, symbol));
"""

TABLES: tuple[str, ...] = ("iv_surface_daily", "iv_expiry_daily", "iv_summary_daily", "vix_daily", "index_ohlc_daily", "iv_event_log",
                           "iv_intraday", "rate_curve", "nse_fo_volt", "nse_contract_delta", "nse_combined_oi")
PLAN_TABLE_COUNT = 11

_TS, _D, _DBL, _INT = "TIMESTAMP", "DATE", "DOUBLE", "INTEGER"

COLUMNS: dict[str, list[str]] = {
    "iv_surface_daily": ["date", "symbol", "expiry", "strike", "opt_type", "price", "price_source", "forward", "forward_source", "t_years", "r",
                         "iv", "delta", "vega", "oi", "oi_chg", "volume", "lot", "log_moneyness", "model_version", "source_file", "first_seen_at"],
    "iv_expiry_daily": ["date", "symbol", "expiry", "dte", "forward", "forward_source", "atm_iv", "iv_25d_put", "iv_25d_call", "skew_25d",
                        "iv_10d_put", "iv_10d_call", "n_iv_strikes", "call_oi", "put_oi", "pcr", "expected_move_pct", "quality_flags",
                        "model_version", "r", "first_seen_at"],
    "iv_summary_daily": ["date", "symbol", "spot", "spot_source", "iv30_cm", "iv60_cm", "iv90_cm", "near_atm_iv", "near_expiry", "near_dte",
                         "monthly_atm_iv", "monthly_expiry", "skew_25d_30", "term_slope_30_90", "iv_rank_252", "iv_pctile_252", "rv20_cc",
                         "rv20_parkinson", "rv20_yz", "fovolt_ann", "iv_minus_rv20", "expected_move_1d_pct", "quality_flags", "model_version",
                         "r", "first_seen_at"],
    "vix_daily": ["date", "open", "high", "low", "close", "prev_close", "source", "first_seen_at"],
    "index_ohlc_daily": ["symbol", "date", "open", "high", "low", "close", "source", "first_seen_at"],
    "iv_event_log": ["symbol", "released_at", "expiry", "iv_pre_5d", "iv_pre_1d", "iv_post_1d", "crush_pct", "implied_move_pct", "realised_move_pct",
                     "pre_session", "post_session", "implied_method", "model_version", "first_seen_at"],
    "iv_intraday": ["ts", "symbol", "expiry", "strike", "opt_type", "mid", "iv", "nse_iv", "oi", "forward", "spot", "source", "model_version", "r",
                    "first_seen_at"],
    "rate_curve": ["date", "tenor", "rate", "source", "first_seen_at"],
    "nse_fo_volt": ["date", "symbol", "close", "prev_close", "log_return", "ewma_daily_vol", "ann_vol", "fut_vol", "fut_ann_vol", "applicable_ann_vol",
                    "first_seen_at"],
    "nse_contract_delta": ["date", "symbol", "expiry", "strike", "opt_type", "delta_factor", "first_seen_at"],
    "nse_combined_oi": ["date", "symbol", "isin", "mwpl", "oi", "fut_equiv_oi", "limit_next_day", "notional_oi", "first_seen_at"],
}

CASTS: dict[str, dict[str, str]] = {
    "iv_surface_daily": {"date": _D, "expiry": _D, "first_seen_at": _TS, "lot": _INT,
                         **{c: _DBL for c in ("strike", "price", "forward", "t_years", "r", "iv", "delta", "vega", "oi", "oi_chg", "volume", "log_moneyness")}},
    "iv_expiry_daily": {"date": _D, "expiry": _D, "first_seen_at": _TS, "dte": _INT, "n_iv_strikes": _INT,
                        **{c: _DBL for c in ("forward", "atm_iv", "iv_25d_put", "iv_25d_call", "skew_25d", "iv_10d_put", "iv_10d_call", "call_oi",
                                             "put_oi", "pcr", "expected_move_pct", "r")}},
    "iv_summary_daily": {"date": _D, "near_expiry": _D, "monthly_expiry": _D, "first_seen_at": _TS, "near_dte": _INT,
                         **{c: _DBL for c in ("spot", "iv30_cm", "iv60_cm", "iv90_cm", "near_atm_iv", "monthly_atm_iv", "skew_25d_30", "term_slope_30_90",
                                              "iv_rank_252", "iv_pctile_252", "rv20_cc", "rv20_parkinson", "rv20_yz", "fovolt_ann", "iv_minus_rv20",
                                              "expected_move_1d_pct", "r")}},
    "vix_daily": {"date": _D, "first_seen_at": _TS, **{c: _DBL for c in ("open", "high", "low", "close", "prev_close")}},
    "index_ohlc_daily": {"date": _D, "first_seen_at": _TS, **{c: _DBL for c in ("open", "high", "low", "close")}},
    "iv_event_log": {"released_at": _TS, "expiry": _D, "pre_session": _D, "post_session": _D, "first_seen_at": _TS,
                     **{c: _DBL for c in ("iv_pre_5d", "iv_pre_1d", "iv_post_1d", "crush_pct", "implied_move_pct", "realised_move_pct")}},
    "iv_intraday": {"ts": _TS, "expiry": _D, "first_seen_at": _TS, **{c: _DBL for c in ("strike", "mid", "iv", "nse_iv", "oi", "forward", "spot", "r")}},
    "rate_curve": {"date": _D, "rate": _DBL, "first_seen_at": _TS},
    "nse_fo_volt": {"date": _D, "first_seen_at": _TS, **{c: _DBL for c in ("close", "prev_close", "log_return", "ewma_daily_vol", "ann_vol", "fut_vol",
                                                                             "fut_ann_vol", "applicable_ann_vol")}},
    "nse_contract_delta": {"date": _D, "expiry": _D, "strike": _DBL, "delta_factor": _DBL, "first_seen_at": _TS},
    "nse_combined_oi": {"date": _D, "first_seen_at": _TS, **{c: _DBL for c in ("mwpl", "oi", "fut_equiv_oi", "limit_next_day", "notional_oi")}},
}

FRESHNESS_COLUMN: dict[str, str] = {"iv_surface_daily": "date", "iv_expiry_daily": "date", "iv_summary_daily": "date", "vix_daily": "date",
                                    "index_ohlc_daily": "date", "iv_event_log": "first_seen_at", "iv_intraday": "ts", "rate_curve": "date",
                                    "nse_fo_volt": "date", "nse_contract_delta": "date", "nse_combined_oi": "date"}


def ddl_statements() -> list[str]:
    body = "\n".join(line for line in DDL.splitlines() if not line.lstrip().startswith("--"))
    return [s.strip() for s in body.split(";") if s.strip()]


def ensure_schema(store: Any) -> None:
    with store.writer() as con:
        for stmt in ddl_statements():
            con.execute(stmt)


def positions_meta(store: Any) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for table, col in FRESHNESS_COLUMN.items():
        try:
            row = store.read_one(f"SELECT MIN({col}), MAX({col}), COUNT(*) FROM {table}")
            lo, hi, n = row if row else (None, None, 0)
            out[table] = {"first": str(lo)[:19] if lo else None, "last": str(hi)[:19] if hi else None, "rows": int(n or 0)}
        except Exception as exc:  # noqa: BLE001
            out[table] = {"first": None, "last": None, "rows": 0, "error": type(exc).__name__}
    return out

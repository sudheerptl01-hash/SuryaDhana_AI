"""The IV series registry (the gold ``catalog_seed`` idea for the vol tables): every metric a page may render, with its
definition, badge, precedent and the table it comes from. A panel renders a metric only if it has a row here with a
verdict of PUBLISH-CORE / PUBLISH-CONTEXT (no row, no panel); ``/db/fo-iv/catalog`` serves it. No row is ``signal``:
no pre-registered study has passed any vol series as a forecast (PLAN §0.1). Context metrics are never coloured
bullish / bearish; the IV − RV spread is a volatility risk premium, not a direction.

The dataset-level rows (publisher, cadence, expected_by) live in ``data_health.catalog``; this registry is per metric.
"""
from __future__ import annotations

from typing import Any

BADGES = ("signal", "context", "arithmetic", "heuristic")
VERDICTS = ("PUBLISH-CORE", "PUBLISH-CONTEXT", "LINK-ONLY", "DO-NOT-PUBLISH")
DESCRIBES = "describes, does not predict"


def _s(series_id: str, name: str, table: str, column: str, badge: str, definition: str, precedent: str, *, unit: str = "vol pt",
       verdict: str = "PUBLISH-CORE", window: str | None = None, note: str | None = None) -> dict[str, Any]:
    assert badge in BADGES and badge != "signal", series_id
    assert verdict in VERDICTS, series_id
    return {"series_id": series_id, "name": name, "table": table, "column": column, "unit": unit, "badge": badge, "verdict": verdict,
            "definition": definition, "precedent": precedent, "window": window, "note": note, "verdict_sentence": f"{name}: {DESCRIBES}"}


def build_rows() -> list[dict[str, Any]]:
    r = [
        _s("IV30_CM", "30-day constant-maturity ATM IV", "iv_summary_daily", "iv30_cm", "arithmetic",
           "ATM variance interpolated between the two expiries bracketing 30 calendar days (VIX-style), annualised; with no bracket, the ATM IV "
           "of the one expiry nearest 30 d inside 10–60 d (flat term, flag cm30_flat)", "Bloomberg HIVG / IVOL; Cboe VIX method"),
        _s("IV60_CM", "60-day constant-maturity ATM IV", "iv_summary_daily", "iv60_cm", "arithmetic", "as IV30_CM at 60 days", "Bloomberg OVDV term tab"),
        _s("IV90_CM", "90-day constant-maturity ATM IV", "iv_summary_daily", "iv90_cm", "arithmetic", "as IV30_CM at 90 days", "Bloomberg OVDV term tab"),
        _s("NEAR_ATM_IV", "Near-expiry ATM IV (dte > 2)", "iv_summary_daily", "near_atm_iv", "arithmetic",
           "ATM IV of the first expiry more than 2 days out; a saw-tooth by construction (R-IV §3)", "Sensibull / Opstra IV chart",
           note="chart the constant-maturity series for history; this one is the live expiry"),
        _s("MONTHLY_ATM_IV", "~1-month ATM IV (first expiry 20–60 d)", "iv_summary_daily", "monthly_atm_iv", "arithmetic",
           "ATM IV of the first expiry 20–60 days out (a weekly when one falls in the window; not NSE's monthly series)",
           "Bloomberg OVDV; India VIX (variance strip) sits ≈ 1 pt above it"),
        _s("IV_RANK_252", "IV rank (252 sessions)", "iv_summary_daily", "iv_rank_252", "arithmetic",
           "where today's IV30_CM sits between the 252-session minimum and maximum, 0–100", "Bloomberg IVOL rank; tastytrade IVR", unit="%", window="252 sessions"),
        _s("IV_PCTILE_252", "IV percentile (252 sessions)", "iv_summary_daily", "iv_pctile_252", "arithmetic",
           "share of the past 252 sessions whose IV30_CM was below today's", "Bloomberg IVOL %ile; thinkorswim IV percentile", unit="%", window="252 sessions",
           note="OMON's former 'IV rank' label was this number (O-T8)"),
        _s("SKEW_25D_30", "25Δ skew at 30 days", "iv_summary_daily", "skew_25d_30", "context", "25Δ put IV minus 25Δ call IV, interpolated to 30 days",
           "Bloomberg SKEW; Cboe SKEW; ORATS skew"),
        _s("TERM_SLOPE_30_90", "Term slope 30 → 90", "iv_summary_daily", "term_slope_30_90", "context", "IV90_CM minus IV30_CM", "Bloomberg OVDV term; Opstra term structure"),
        _s("RV20_CC", "Realised vol 20 d (close-to-close)", "iv_summary_daily", "rv20_cc", "arithmetic", "σ of 20 daily log returns × √252", "Bloomberg HVG"),
        _s("RV20_PARKINSON", "Realised vol 20 d (Parkinson)", "iv_summary_daily", "rv20_parkinson", "arithmetic", "√(mean ln(H/L)² / 4 ln 2) × √252", "Bloomberg HVG (Parkinson)"),
        _s("RV20_YZ", "Realised vol 20 d (Yang-Zhang)", "iv_summary_daily", "rv20_yz", "arithmetic", "overnight + k·open-close + (1−k)·Rogers-Satchell variance × 252",
           "Bloomberg HVG (Yang-Zhang); IBKR Volatility Lab",
           note="a range-outlier session (a bad high / low print) leaves the range terms: flag rv_range_outlier"),
        _s("FOVOLT_ANN", "NSE FOVOLT annualised vol", "iv_summary_daily", "fovolt_ann", "context", "NSE's EWMA (λ 0.995) daily vol × √365: the exchange's margin vol",
           "NSE F&O daily volatility file", note="the exchange's number, shown as published"),
        _s("IV_MINUS_RV20", "IV30 − RV20 close-to-close (volatility risk premium)", "iv_summary_daily", "iv_minus_rv20", "context", "IV30_CM minus RV20_CC",
           "Market Chameleon IV30 vs HV; Bloomberg VCA",
           note="close-to-close is the estimator of record; the Parkinson / Yang-Zhang spreads are shown beside it, each named; never coloured bullish/bearish"),
        _s("EXPECTED_MOVE_1D", "1-day expected move", "iv_summary_daily", "expected_move_1d_pct", "arithmetic", "IV30_CM / √252", "Bloomberg OSA expected move; thinkorswim MMM", unit="%"),
        _s("EXPIRY_ATM_IV", "ATM IV per expiry", "iv_expiry_daily", "atm_iv", "arithmetic", "IV interpolated at the parity forward, per expiry", "Bloomberg OVDV"),
        _s("EXPIRY_SKEW_25D", "25Δ skew per expiry", "iv_expiry_daily", "skew_25d", "context", "25Δ put IV − 25Δ call IV, each by inverting that strike's own delta", "ORATS skew",
           note="the near expiry's own history (dte > 2) gives its percentile; the 30-day series has its own"),
        _s("PAID_VS_DELIVERED", "IV paid vs vol delivered (monthly expiries)", "iv_expiry_daily", "atm_iv", "context",
           "ATM IV of each NSE monthly expiry at ≈ 30 DTE minus the close-to-close realised vol (zero-mean) over that option's own life, entry close → expiry close",
           "ORATS implied vs realised; Bloomberg VCA", verdict="PUBLISH-CONTEXT"),
        _s("EXPIRY_PCR", "Put/call OI ratio per expiry", "iv_expiry_daily", "pcr", "context", "put OI ÷ call OI (contracts) on the expiry", "Sensibull PCR",
           note="never coloured green ≥ 1 (Wave 0 0.6)"),
        _s("EXPIRY_EXPECTED_MOVE", "Expected move to expiry", "iv_expiry_daily", "expected_move_pct", "arithmetic", "ATM IV × √T (1σ)", "Bloomberg OSA", unit="%"),
        _s("SURFACE_IV", "IV per strike", "iv_surface_daily", "iv", "arithmetic", "Black-76 IV on the parity forward; traded strikes only", "Bloomberg OMON / OVDV smile"),
        _s("SURFACE_DELTA", "Delta per strike", "iv_surface_daily", "delta", "arithmetic", "Black-76 delta (discounted) at the strike's own IV", "Bloomberg OMON",
           note="NSE's Contract_Delta factor shown beside it"),
        _s("VIX_CLOSE", "India VIX", "vix_daily", "close", "context", "NSE's India VIX close (OHLC stored)", "NSE India VIX", note="one source for the VIX everywhere"),
        _s("EVENT_CRUSH", "Results IV crush", "iv_event_log", "crush_pct", "context", "near-expiry ATM IV after the release ÷ before − 1", "ORATS / Market Chameleon earnings",
           unit="%", verdict="PUBLISH-CONTEXT"),
        _s("EVENT_IMPLIED_VS_REALISED", "Implied vs realised event move", "iv_event_log", "implied_move_pct", "context",
           "term-split implied event σ (else ATM IV / √252) beside the realised pre→post move", "ORATS earnings", unit="%", verdict="PUBLISH-CONTEXT"),
        _s("INTRADAY_ATM_IV", "Intraday ATM IV (15-min pilot)", "iv_intraday", "iv", "context", "Black-76 IV from the bid/ask mid on the Breeze chain, every 15 min",
           "Quantsapp IV live; Bloomberg OMON intraday", verdict="PUBLISH-CONTEXT", note="SourceChip LIVE Breeze / OFFLINE; stored only through the budget ledger"),
        _s("NSE_DELTA_FACTOR", "NSE delta factor", "nse_contract_delta", "delta_factor", "context", "NSE Clearing's delta per contract (margins)", "NSE Contract_Delta file",
           verdict="PUBLISH-CONTEXT"),
        _s("MWPL_FUT_EQUIV_OI", "Futures-equivalent OI (delta-equivalent)", "nse_combined_oi", "fut_equiv_oi", "context", "NSE's portfolio-wise futures-equivalent OI",
           "NSE combineoi_deleq file", verdict="PUBLISH-CONTEXT", unit="shares"),
        _s("RATE_R", "Risk-free rate used", "rate_curve", "rate", "arithmetic", "dated constant 6.5 % (O-T5) recorded as r on every row", "—", unit="%"),
    ]
    seen: set[str] = set()
    for row in r:
        assert row["series_id"] not in seen, row["series_id"]
        seen.add(row["series_id"])
    return r


def by_id() -> dict[str, dict[str, Any]]:
    return {r["series_id"]: r for r in build_rows()}


def badges() -> dict[str, str]:
    return {r["series_id"]: r["badge"] for r in build_rows()}

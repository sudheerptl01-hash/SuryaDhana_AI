#!/usr/bin/env python
"""Build the Terminal v2 LEARN assets: ``glossary.json`` and ``tooltips.json`` (the G-EDU ``build_glossary.py`` pattern).

    python reports/terminal_v2/LEARN/build_assets.py          # write glossary.json + tooltips.json beside this file
    python reports/terminal_v2/LEARN/validate_learn.py        # check them (validate_learn.py --write runs this first)

The terms and tooltips are code here (one place to edit); the JSON files are the build and are committed. B4-UI reads
``tooltips.json`` / ``glossary.json`` from this folder; a copy bundled under ``ui/`` must stay identical (the validator
checks it). Every non-panel tooltip key is a stored column or an API payload field of the Terminal v2 tables and routes
(the validator proves each one exists in the code, read as text, never imported).

Labelling rules (PLAN §0.1, binding): badges ``context`` / ``arithmetic`` / ``heuristic`` only (no ``signal`` exists);
context metrics are never described with direction words (bullish, bearish, buy, sell, long/short build-up, …); a
verdict sentence ends "describes, does not predict"; no composite score; no sizing advice. Every ``short``, ``long`` and
tooltip value is one line of at most 200 characters; ``long`` is empty rather than a copy of ``short``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
VERSION = "2026-11-05"
AGENT = "B5-DOCS"
DESCRIBES = "describes, does not predict"

# The entries PLAN 1.6 and the B5 brief require (the validator refuses a build without each of them).
REQUIRED_TERMS: tuple[str, ...] = (
    "IV rank", "IV percentile", "constant-maturity IV", "put-call-parity forward", "25Δ skew", "Parkinson volatility",
    "Yang-Zhang volatility", "FOVOLT", "SPAN margin", "exposure margin", "points attribution", "attribution residual",
    "hysteresis", "delta-equivalent OI", "MWPL",
)

# fmt: off
TERMS: list[dict[str, Any]] = [
    # ── the required entries ──────────────────────────────────────────────────────────────────────────────────────
    {"term": "IV rank", "aliases": ["IVR", "iv_rank_252"],
     "short": "Where today's IV sits in its 252-session range: (IV − min) ÷ (max − min) × 100. 0 = at the low, 100 = at the high. Not the percentile.",
     "long": "Fixture: iv30_cm 12.81 in a 8.50–28.87 range → rank 21. One spike stretches the range and pulls every later rank down. Badge `arithmetic`.",
     "see_also": ["IV percentile", "constant-maturity IV"]},
    {"term": "IV percentile", "aliases": ["IVP", "iv_pctile_252"],
     "short": "The share of the last 252 sessions whose IV was below today's. 60 means IV was lower on 60 % of those days. Not the rank.",
     "long": "Same fixture, percentile 60 while the rank is 21. OMON's old \"IV rank\" was a percentile of the saw-tooth near-expiry series; both now show, each by its definition.",
     "see_also": ["IV rank", "constant-maturity IV"]},
    {"term": "constant-maturity IV", "aliases": ["iv30_cm", "iv60_cm", "iv90_cm", "CM IV"],
     "short": "ATM IV at a fixed horizon (30 / 60 / 90 days), interpolated in variance between the two expiries that bracket it, the way India VIX is built.",
     "long": "Weekly expiries make near-expiry ATM IV saw-tooth with the calendar, so a history needs a fixed horizon: σ²·T is interpolated linearly in T, then annualised.",
     "see_also": ["fixed-expiry series", "India VIX", "ATM IV"]},
    {"term": "put-call-parity forward", "aliases": ["parity forward", "PCP forward", "forward_source"],
     "short": "The forward implied by traded options: F = K + (C − P)·e^{rT} at the strike nearest spot where both the call and the put traded.",
     "long": "No dividend input needed. Fallback, stored as forward_source: parity → matching future (also if they differ > 0.5 %) → spot·e^{rT}. NIFTY 3 Nov 2026: 23,931.23.",
     "see_also": ["Black-76", "risk-free rate"]},
    {"term": "25Δ skew", "aliases": ["skew_25d", "skew_25d_30", "25-delta skew"],
     "short": "25-delta put IV minus 25-delta call IV, each strike found by inverting its own delta. Positive = puts dearer than calls; NIFTY runs 2–3 vol points.",
     "long": "Interpolated to 30 days as skew_25d_30. It is why India VIX sits ≈ 1 vol point above the ATM iv30_cm. A `context` number in the neutral token: it " + DESCRIBES + ".",
     "see_also": ["constant-maturity IV", "India VIX", "smile"]},
    {"term": "Parkinson volatility", "aliases": ["rv20_parkinson", "Parkinson"],
     "short": "Realised vol from the daily high–low range: √(mean ln(H/L)² ÷ 4 ln 2) × √252 over 20 sessions. Needs only high and low.",
     "long": "Uses more of each day than close-to-close, so it is less noisy over 20 sessions; it ignores overnight gaps, which is why Yang-Zhang is shown beside it.",
     "see_also": ["Yang-Zhang volatility", "realised volatility"]},
    {"term": "Yang-Zhang volatility", "aliases": ["rv20_yz", "YZ", "Yang-Zhang"],
     "short": "Realised vol from open, high, low and close: overnight variance + k·open-to-close variance + (1 − k)·Rogers-Satchell, annualised × √252.",
     "long": "k = 0.34 ÷ (1.34 + (n + 1)/(n − 1)). The one estimator here that handles overnight gaps; indices take OHLC from index_ohlc_daily, stocks from nse_bhavcopy.",
     "see_also": ["Parkinson volatility", "realised volatility", "FOVOLT"]},
    {"term": "FOVOLT", "aliases": ["fovolt_ann", "NSE daily volatility", "EWMA vol"],
     "short": "NSE Clearing's own volatility per F&O underlying: an EWMA of squared log returns with λ = 0.995, annualised × √365 (not √252).",
     "long": "σ²ₜ = 0.995·σ²ₜ₋₁ + 0.005·rₜ². FOVOLT_DDMMYYYY.csv, published ≈ 17:00 IST (16:58 and 17:01 measured); the vol margins are set on. A `context` line beside IV.",
     "see_also": ["realised volatility", "SPAN margin"]},
    {"term": "SPAN margin", "aliases": ["span_margin_required", "SPAN", "initial margin"],
     "short": "The clearing corporation's initial margin: the worst loss of the whole position over 16 price × vol scenarios, plus spread charges, with a short-option minimum.",
     "long": "Spreads earn offsets: a NIFTY condor needed ₹81,497.07 in Breeze. The 12 %-of-notional estimate measured 4.8× too high. OSTR: Breeze → NSE SPAN file → heuristic.",
     "see_also": ["exposure margin", "SPAN risk-parameter file"]},
    {"term": "exposure margin", "aliases": ["non_span_margin_required", "non-SPAN margin"],
     "short": "The flat extra margin added on top of SPAN: a percentage of notional per underlying that earns no spread offset.",
     "long": "Breeze returns it as non_span_margin_required; total margin = SPAN + exposure. Both are `arithmetic`: an exchange rule, not a view.",
     "see_also": ["SPAN margin"]},
    {"term": "points attribution", "aliases": ["index points", "contribution", "MEMB points"],
     "short": "Each member's share of the index move in points: previous index level × its weight × its return. Additive, so any horizon is the sum of its days.",
     "long": "L from NSE's daily index file, r from adjusted closes, w rebuilt from filings and calibrated to NSE's top-10 file. An identity shown with its residual; it " + DESCRIBES + ".",
     "see_also": ["attribution residual", "calibration (iwf_correction)", "driver leader"]},
    {"term": "attribution residual", "aliases": ["residual_points", "residual"],
     "short": "The index move minus the sum of member points on a day: what the identity does not explain. The fit chip prints it beside the MAE.",
     "long": "Comes from stale weights between filings, a missing close and the bank index's capping. A 60-session MAE above 25 points marks the fit `degraded`.",
     "see_also": ["points attribution", "calibration (iwf_correction)"]},
    {"term": "hysteresis", "aliases": ["driver change rule", "tenure_sessions"],
     "short": "The driver leader changes only when a challenger has led the incumbent by ≥ 1.3× (20-session) or 1.2× (60-session) for 5 consecutive sessions.",
     "long": "Without it the top name flipped 63 times in 208 sessions; with it, 5 times. The raw leader is stored beside the held one. No colour on the leader; it " + DESCRIBES + ".",
     "see_also": ["driver leader", "points attribution"]},
    {"term": "delta-equivalent OI", "aliases": ["fut_equiv_oi", "futures-equivalent OI", "combineoi_deleq"],
     "short": "NSE's portfolio-wise futures-equivalent open interest: options OI weighted by delta and added to futures, per stock, across exchanges.",
     "long": "From combineoi_deleq_DDMMYYYY.csv (≈ 19:18 IST). Shown with the % of MWPL as a `context` column on OMON and DERV, never coloured.",
     "see_also": ["MWPL", "NSE delta factor"]},
    {"term": "MWPL", "aliases": ["market-wide position limit", "mwpl_pct", "ban list"],
     "short": "The market-wide position limit for a stock's F&O book. OI above 95 % of it puts the stock in the F&O ban (no new positions) until it falls below 80 %.",
     "long": "The MWPL zip lands ≈ 19:23 IST; the ban list (≈ 19:24) is named for the next session; clients holding ≥ 3 % of the limit come as a file dated the previous session.",
     "see_also": ["delta-equivalent OI", "open interest"]},
    # ── supporting terms ──────────────────────────────────────────────────────────────────────────────────────────
    {"term": "implied volatility", "aliases": ["IV", "implied vol"],
     "short": "The volatility that makes an option's model price equal its market price: a price restated in vol units, quoted annualised in vol points.",
     "long": "Computed per traded strike with Black-76 on the parity forward; an untraded strike carries NSE's theoretical settle, so it gets no IV (price_source flags it).",
     "see_also": ["Black-76", "ATM IV", "realised volatility"]},
    {"term": "Black-76", "aliases": ["b76-pcp-v1", "model_version"],
     "short": "Black's option model on the forward rather than the spot: the convention behind every stored IV and Greek, named by model_version (b76-pcp-v1).",
     "long": "T = calendar days ÷ 365 at the 15:30 close; r recorded on every row; a change of convention is a new model_version and new rows, never an overwrite.",
     "see_also": ["put-call-parity forward", "implied volatility", "point-in-time"]},
    {"term": "ATM IV", "aliases": ["atm_iv", "near_atm_iv", "monthly_atm_iv"],
     "short": "IV interpolated at the forward, not at the nearest strike. Near = the first expiry with more than 2 days left; monthly = the first expiry 20–60 days out.",
     "long": "Expiry-day and T ≤ 2 d rows stay in the surface but are left out of \"near\": their IV jumps with the calendar.",
     "see_also": ["constant-maturity IV", "fixed-expiry series"]},
    {"term": "fixed-expiry series", "aliases": ["IV by contract"],
     "short": "One expiry's ATM IV from listing to expiry: the series that follows a single contract through its life.",
     "long": "", "see_also": ["constant-maturity IV", "ATM IV"]},
    {"term": "smile", "aliases": ["volatility smile", "log_moneyness"],
     "short": "IV plotted against strike for one expiry; stored in log-moneyness ln(K ÷ F) so surfaces compare across days.",
     "long": "", "see_also": ["25Δ skew"]},
    {"term": "term structure", "aliases": ["term_slope_30_90", "term slope"],
     "short": "IV by expiry. The slope iv90_cm − iv30_cm is positive when far months are dearer, the usual state, and often inverts around events.",
     "long": "A `context` number: it " + DESCRIBES + ".", "see_also": ["constant-maturity IV"]},
    {"term": "realised volatility", "aliases": ["RV", "rv20_cc", "historical volatility", "HV"],
     "short": "The volatility the price delivered: close-to-close σ of 20 daily log returns × √252, shown beside the Parkinson, Yang-Zhang and FOVOLT estimates.",
     "long": "", "see_also": ["Parkinson volatility", "Yang-Zhang volatility", "FOVOLT", "volatility risk premium"]},
    {"term": "volatility risk premium", "aliases": ["iv_minus_rv20", "IV − RV", "VRP"],
     "short": "IV minus realised vol: what options price over what the index has been delivering. A `context` spread in the neutral token, never coloured.",
     "long": "The \"IV paid vs vol delivered\" ledger over the last 12 monthly expiries shows how often the premium exceeded the move; it " + DESCRIBES + ".",
     "see_also": ["implied volatility", "realised volatility"]},
    {"term": "expected move", "aliases": ["expected_move_pct", "expected_move_1d_pct", "1σ move"],
     "short": "The one-standard-deviation move the options price in: ATM IV × √T to expiry, or iv30_cm ÷ √252 for one day. A model's arithmetic, not a forecast.",
     "long": "The hit-rate panel counts how often the realised move stayed inside it over 60 sessions.",
     "see_also": ["ATM IV", "straddle"]},
    {"term": "straddle", "aliases": ["straddle price"],
     "short": "ATM call + ATM put at one expiry: the market's price for movement in either direction. Its decay through the day is the expiry-day curve.",
     "long": "", "see_also": ["expected move"]},
    {"term": "IV crush", "aliases": ["crush_pct", "event IV", "results IV"],
     "short": "The change in near-expiry ATM IV across a results release: IV after ÷ IV before − 1, kept per stock with the implied and the realised move.",
     "long": "The EVTS ledger lists the last 8 releases per stock (IV before and after, implied vs realised move); it " + DESCRIBES + ".",
     "see_also": ["expected move", "implied volatility"]},
    {"term": "India VIX", "aliases": ["VIX", "vix_daily"],
     "short": "NSE's model-free 30-day volatility index from NIFTY option prices (a variance strip over the OTM wings). Stored as OHLC in vix_daily, one source for every page.",
     "long": "Nightly from the ind_close_all file; a one-off backfill from NSE's historicalOR/vixhistory (≤ 1 year per call). It includes the skew, so it sits above ATM iv30_cm.",
     "see_also": ["constant-maturity IV", "25Δ skew"]},
    {"term": "risk-free rate", "aliases": ["r", "rate_curve"],
     "short": "The rate in the model: a dated constant (6.5 %, O-T5) recorded as r on every stored row, so a later change never rewrites history.",
     "long": "With the forward taken from parity the rate barely matters: 100 bp moves a 30-day ATM NIFTY IV by ≈ 0.01 vol point.",
     "see_also": ["put-call-parity forward", "point-in-time"]},
    {"term": "put/call OI ratio", "aliases": ["pcr", "PCR"],
     "short": "Put open interest ÷ call open interest on an expiry. A `context` ratio shown uncoloured: it says which side holds more open contracts, nothing more.",
     "long": "", "see_also": ["open interest"]},
    {"term": "open interest", "aliases": ["OI", "oi_chg"],
     "short": "Contracts outstanding at the close, per strike and expiry; its daily change is a `context` column. OI-change classes tested as a swing rule showed no edge (H2).",
     "long": "", "see_also": ["delta-equivalent OI", "put/call OI ratio"]},
    {"term": "NSE delta factor", "aliases": ["delta_factor", "Contract_Delta"],
     "short": "NSE Clearing's own delta per option contract (Contract_Delta file, ≈ 18:30–19:20 IST), shown beside our Black-76 delta; a gap above 0.05 is logged.",
     "long": "", "see_also": ["delta-equivalent OI", "Black-76"]},
    {"term": "SPAN risk-parameter file", "aliases": ["nsccl.YYYYMMDD.s.zip", "SPAN file"],
     "short": "NSE Clearing's end-of-day SPAN parameters (risk arrays per contract, spread charges, short-option minimum), ≈ 17:02 IST. Lets OSTR price margin offline.",
     "long": "No scheduled job downloads it yet: the parser and the fallback read whatever file sits in data/nse_archive/span/.",
     "see_also": ["SPAN margin", "exposure margin"]},
    {"term": "driver leader", "aliases": ["leader", "driver regime", "raw_leader"],
     "short": "The member with the largest |points| over a rolling 20- or 60-session window, held with hysteresis; shown in the neutral token with its tenure and share.",
     "long": "\"20-session leader BHARTIARTL for N sessions, 12.5 % of member points\" says what moved the index; it " + DESCRIBES + ".",
     "see_also": ["hysteresis", "points attribution", "breadth (EW − CW)"]},
    {"term": "breadth (EW − CW)", "aliases": ["ew_minus_cw_pp", "equal-weight minus cap-weight"],
     "short": "The members' equal-weight return minus the cap-weight (index) return over 20 sessions, in percentage points. Negative = a few heavyweights carried the index.",
     "long": "A `context` number; \"narrow\" or \"broad\" " + DESCRIBES + ".", "see_also": ["concentration", "driver leader"]},
    {"term": "concentration", "aliases": ["top5_share", "hhi_contrib", "weight_hhi", "effective_n"],
     "short": "How few names explain the move: the top-5 share of |points|, the Herfindahl of contributions and of weights, and 1 ÷ Σ weight² (effective number of names).",
     "long": "", "see_also": ["breadth (EW − CW)", "points attribution"]},
    {"term": "calibration (iwf_correction)", "aliases": ["iwf_correction", "rebuilt_calibrated", "weight_method"],
     "short": "Rebuilt weights are scaled to NSE's daily top-10 file (≈ 16:30 IST): iwf_correction = official ÷ rebuilt for the ten names, the other forty pro rata, Σ = 100.",
     "long": "NSE publishes no full daily weight file for free and the equity-stockIndices endpoint is dead (404). The calibrated rebuild explained 99.6 % of daily variance.",
     "see_also": ["points attribution", "attribution residual"]},
    {"term": "point-in-time", "aliases": ["PIT", "first_seen_at", "release_at"],
     "short": "Every stored row carries the period it describes, when the publisher released it and when we first saw it; a source revision is a new row, never an overwrite.",
     "long": "Derived tables keep the latest computation per key; a past vintage is recomputed from the archived source files, which ingest_log versions by sha256.",
     "see_also": ["ingest log revision", "gap row", "Black-76"]},
    {"term": "ingest log revision", "aliases": ["revision", "ingest_log", "If-Modified-Since"],
     "short": "A re-fetch whose body changed (sha256) is logged as revision + 1 with the publisher's Last-Modified; the 22:45 pass re-checks the equity bhavcopy this way.",
     "long": "NSE re-published the 4 Nov equity bhavcopy at 22:05 IST, after a first evening copy. Note: NSE's Last-Modified header is GMT; add 5:30 for IST.",
     "see_also": ["point-in-time", "expected-by"]},
    {"term": "expected-by", "aliases": ["expected_by", "max_age_sessions", "data health"],
     "short": "The IST time by which the terminal expects a dataset stored, trading-day aware. Past it the DATA view shows amber, past its lag budget red. No composite score.",
     "long": "Page wording: \"stored 30 Oct · expected by 21:00 · 3 sessions behind · catch-up 19:30 tomorrow\". States: live, fresh, amber, red, gap.",
     "see_also": ["gap row", "ingest log revision", "SourceChip"]},
    {"term": "gap row", "aliases": ["data_gaps", "unrecoverable"],
     "short": "An explicit row saying a session-bound capture (pre-open book, breadth samples, FII/DII, gold open) was lost while the stack was down; pages say so.",
     "long": "", "see_also": ["expected-by", "point-in-time"]},
    {"term": "SourceChip", "aliases": ["source chip"],
     "short": "The chip on every panel header: LIVE Breeze, LIVE NSE, DELAYED with its age, STALE, OFFLINE or GAP. Daily data shows its date, not a clock.",
     "long": "", "see_also": ["expected-by", "badge"]},
    {"term": "badge", "aliases": ["context", "arithmetic", "heuristic"],
     "short": "Each derived number's label: `arithmetic` (identity or model convention), `context` (a description), `heuristic` (a house rule, its error shown). No `signal` exists.",
     "long": "`signal` needs a FINDINGS PASS row from a pre-registered study (PIT data, |t| ≥ 2 in the full sample and both halves, after costs). None has passed here.",
     "see_also": ["SourceChip", "point-in-time"]},
    {"term": "days to expiry", "aliases": ["dte", "near_dte", "DTE"],
     "short": "Calendar days from the trade date to the expiry at the 15:30 close; T = dte ÷ 365 in the model. Read from the file, never assumed from a weekday.",
     "long": "", "see_also": ["Black-76", "ATM IV"]},
    {"term": "Breeze budget", "aliases": ["budget ledger", "breeze_budget"],
     "short": "One ledger every ICICI Breeze call passes through: per-minute and per-day counters in SQLite, per-caller quotas, a hard stop at the owner's cap.",
     "long": "The documented 100/min and 5,000/day are the ceiling; the owner's cap (O-T6) is the budget. The 15-minute chain pilot and the margin calls share it.",
     "see_also": ["SPAN margin"]},
]

# keys = stored columns (fo_iv / index_drivers / data_health schemas) or API payload fields (derivatives, markets index-drivers,
# options margin, data health): validate_learn.py check 6 proves each one exists in the code; dotted keys are panel ids.
TOOLTIPS: dict[str, str] = {
    # iv_summary_daily / GET /api/derivatives/iv/{symbol}
    "iv30_cm": "30-day constant-maturity ATM IV, interpolated in variance between the bracketing expiries (VIX method). arithmetic.",
    "iv60_cm": "60-day constant-maturity ATM IV. arithmetic.",
    "iv90_cm": "90-day constant-maturity ATM IV. arithmetic.",
    "near_atm_iv": "ATM IV of the first expiry with more than 2 days left; saw-tooths with the weekly calendar, hence the CM series.",
    "near_expiry": "The expiry the near ATM IV is read from (dte > 2).",
    "near_dte": "Calendar days to the near expiry at the 15:30 close.",
    "monthly_atm_iv": "ATM IV of the first expiry 20–60 days out.",
    "monthly_expiry": "The expiry the monthly ATM IV is read from.",
    "iv_rank_252": "IV rank: (today − 252-session min) ÷ (max − min) × 100 on iv30_cm. Not the percentile.",
    "iv_pctile_252": "IV percentile: share of the last 252 sessions with iv30_cm below today. Not the rank.",
    "skew_25d_30": "25Δ put IV − 25Δ call IV interpolated to 30 days; positive = puts dearer. context, uncoloured.",
    "term_slope_30_90": "iv90_cm − iv30_cm; positive = far months dearer. context.",
    "rv20_cc": "Realised vol, close-to-close, 20 sessions × √252. arithmetic.",
    "rv20_parkinson": "Realised vol from the daily high–low range (Parkinson), 20 sessions × √252.",
    "rv20_yz": "Realised vol from open/high/low/close incl. overnight gaps (Yang-Zhang), 20 sessions × √252.",
    "fovolt_ann": "NSE Clearing's EWMA vol (λ 0.995) annualised × √365: the margin vol. context.",
    "iv_minus_rv20": "iv30_cm − rv20_cc: the volatility risk premium. context, never coloured.",
    "expected_move_1d_pct": "One-day 1σ move implied by iv30_cm ÷ √252. arithmetic.",
    "quality_flags": "Stored data-quality flags: untraded strikes, forward fallback, thin expiry, grid change.",
    "spot": "Underlying close used; spot_source says whether it came from the F&O file or the daily index file.",
    "spot_source": "Where the spot came from: the UDiFF UndrlygPric column or the ind_close_all file (legacy era).",
    # iv_expiry_daily / surface
    "forward": "Forward price for the expiry, from put-call parity at the strike nearest spot where both sides traded.",
    "forward_source": "parity (preferred) · future (also when |F_pcp − F_fut| > 0.5 %) · spot·e^{rT} (flagged).",
    "atm_iv": "IV interpolated at the forward for this expiry. arithmetic.",
    "iv_25d_put": "IV at the strike whose own Black-76 delta is −0.25.",
    "iv_25d_call": "IV at the strike whose own Black-76 delta is +0.25.",
    "skew_25d": "iv_25d_put − iv_25d_call for this expiry. context, uncoloured.",
    "iv_10d_put": "IV at the −0.10-delta strike (the far put wing).",
    "iv_10d_call": "IV at the +0.10-delta strike (the far call wing).",
    "n_iv_strikes": "Strikes with a computable IV (traded; OTM wings plus 3 % ITM). Stocks: near/next month only.",
    "call_oi": "Call open interest on the expiry, contracts.",
    "put_oi": "Put open interest on the expiry, contracts.",
    "pcr": "put_oi ÷ call_oi. context; never coloured green or red.",
    "expected_move_pct": "1σ move to expiry: ATM IV × √T. arithmetic.",
    "dte": "Calendar days to this expiry at the 15:30 close.",
    "iv": "Black-76 IV on the parity forward for this strike; blank when the strike did not trade.",
    "delta": "Black-76 delta (discounted) at the strike's own IV; the NSE delta factor sits beside it.",
    "vega": "Price change per 1 vol-point of IV, per unit.",
    "price_source": "cls (ClsPric with volume > 0) or none: untraded strikes carry NSE's theoretical settle and get no IV.",
    "log_moneyness": "ln(K ÷ F): the x-axis of the smile, comparable across days.",
    "model_version": "The IV convention (b76-pcp-v1: Black-76 on the parity forward, T = days ÷ 365). A new convention = new rows.",
    "r": "Risk-free rate used, dated constant 6.5 % (O-T5), recorded on every row.",
    "t_years": "Calendar days to expiry ÷ 365.",
    # iv_event_log
    "iv_pre_5d": "Near-expiry ATM IV five sessions before the results release.",
    "iv_pre_1d": "Near-expiry ATM IV the session before the release.",
    "iv_post_1d": "Near-expiry ATM IV the session after the release.",
    "crush_pct": "iv_post_1d ÷ iv_pre_1d − 1: the IV crush. Describes past releases, does not forecast the next.",
    "implied_move_pct": "The move the options priced before the release (term-structure split of the event σ).",
    "realised_move_pct": "|move| at the next open/close after the release.",
    "implied_method": "How the implied event move was derived (term-structure split or the straddle).",
    # iv_intraday
    "nse_iv": "NSE's own option-chain-v3 IV stored beside ours in the same snapshot (two models, labelled; O-T7).",
    "mid": "Bid/ask midpoint the intraday IV is computed from, never the last trade.",
    # NSE context files
    "delta_factor": "NSE Clearing's delta per contract (Contract_Delta file, ≈ 18:30–19:20 IST). Cross-check of ours. context.",
    "fut_equiv_oi": "NSE's portfolio-wise futures-equivalent OI (delta-weighted). context.",
    "notional_oi": "Notional open interest from the combineoi_deleq file.",
    "mwpl": "Market-wide position limit for the stock (combineoi zip).",
    "limit_next_day": "Next session's position limit per the combineoi zip.",
    "mwpl_pct": "Open interest as % of the market-wide position limit; ≥ 95 % = F&O ban next session. context.",
    "next_results": "Next results date from nse_events, for the screener's results_within filter.",
    "ban": "In the F&O ban list for the next session (named for the next trading day).",
    "ewma_daily_vol": "NSE's EWMA daily volatility (λ 0.995) from the FOVOLT file.",
    "ann_vol": "FOVOLT annualised volatility (× √365) for the underlying.",
    "fut_vol": "FOVOLT annualised volatility of the current-month future.",
    # POST /api/options/margin
    "span_margin_required": "SPAN initial margin for the whole structure (offsets included). arithmetic; source chip BREEZE / NSE SPAN FILE / HEURISTIC.",
    "non_span_margin_required": "Exposure margin added on top of SPAN, a flat % of notional with no spread offset.",
    "total_margin": "span_margin_required + non_span_margin_required.",
    "source_chip": "Where the margin came from: BREEZE (live session) → NSE SPAN FILE (offline) → HEURISTIC (last resort).",
    "error_factor_measured": "The heuristic's measured error: 4.8× over Breeze SPAN on the NIFTY 09-Nov-2026 iron condor.",
    # index drivers
    "points": "Previous index level × weight × return: this member's share of the index move, in points. arithmetic.",
    "weight_pct": "Point-in-time index weight (rebuilt from filings, calibrated to NSE's top-10 file). arithmetic.",
    "ret_pct": "The member's adjusted return over the horizon.",
    "residual_points": "Index move − Σ member points: what the identity does not explain. Shown, never hidden.",
    "explained_points": "Σ member points over the horizon.",
    "actual_points": "The index's own move over the horizon from NSE's daily file.",
    "leader": "Largest |points| over the window, held with hysteresis (≥ 1.3× / 1.2× for 5 sessions). context, no colour.",
    "raw_leader": "Today's largest |points| name before hysteresis: the one that flips every two sessions.",
    "tenure_sessions": "Sessions the current leader has held the regime.",
    "leader_share": "Leader's |points| as a share of all members' |points| over the window.",
    "changed_from": "The previous leader before the last regime change.",
    "change_date": "When the current leader took over under the hysteresis rule.",
    "top5_share": "Share of |points| from the five largest contributors over the window.",
    "hhi_contrib": "Herfindahl index of contribution shares (1 = one name did it all).",
    "weight_hhi": "Herfindahl index of index weights.",
    "effective_n": "1 ÷ Σ weight²: how many names the index effectively is.",
    "ew_minus_cw_pp": "Equal-weight minus cap-weight return over 20 sessions, pp; negative = narrow. context.",
    "ew_pct": "Equal-weight return of the members over the window.",
    "cw_pct": "Cap-weight (index) return over the window.",
    "members_up": "Members with a positive return over the window.",
    "members_down": "Members with a negative return over the window.",
    "iwf_correction": "official top-10 weight ÷ rebuilt weight on the calibration day; the other 40 names pro rata.",
    "method": "official_top10 (NSE file) · rebuilt (filings) · rebuilt_calibrated (scaled to the file).",
    "weight_method": "Which weight set priced the day: rebuilt_calibrated when the top-10 file existed, else rebuilt.",
    "index_close_source": "nse_daily_file: the index level is NSE's ind_close_all, never Yahoo.",
    "prev_index_level": "L_{d−1}, the level the points are measured from.",
    # data health
    "expected_by": "IST time the dataset should be stored by (trading-day aware). Past it: amber; past the lag budget: red.",
    "lag_sessions": "Trading sessions between the last stored row and the last completed session.",
    "max_age_sessions": "Lag budget before the row turns red (sessions for daily data, days otherwise).",
    "unrecoverable": "A missed capture cannot be backfilled (session-bound): a gap row is written instead.",
    "revision": "0 for the first fetch; +1 each time a re-fetch changed the body (sha256).",
    "sha256": "Hash of the fetched body: the dedupe key for revisions.",
    "last_modified": "The publisher's Last-Modified header (GMT; IST = +5:30), the clock evidence for the schedule.",
    # panels (dotted = panel ids; prefix = page)
    "omon.history": "iv30_cm with the monthly line and India VIX overlay; results/budget/expiry markers; rank and percentile chips, each defined. Bloomberg HIVG.",
    "omon.term": "Near/next/far ATM IV + 30/60/90 CM, 25Δ skew with its 1-y percentile, straddle vs history, IV vs RV (cc/Parkinson/YZ/FOVOLT). Bloomberg OVDV.",
    "omon.chain": "Greeks per strike from Black-76; NSE delta beside ours; MWPL % for stocks. Bloomberg OMON.",
    "omon.live": "Today's 15-minute IV path from Breeze chain snapshots; SourceChip LIVE Breeze / LIVE NSE / OFFLINE. context.",
    "vol.skew": "25Δ / 10Δ skew history and the smile today vs one month ago. Bloomberg SKEW. context.",
    "vol.term": "Term structure today and the 30→90 slope history. Bloomberg VCA. context.",
    "vol.cone": "Min / 25 / 50 / 75 / max of constant-maturity IV by tenor over 1/3/5 years, with today's term. Bloomberg GV cone.",
    "vol.iv_vs_rv": "IV paid vs vol delivered over the last 12 monthly expiries, and the expected-move hit-rate over 60 sessions. context.",
    "vol.screener": "All 224 underlyings: iv30_cm, rank, percentile, rv20_yz, spread, term slope, skew, next results, ban, MWPL %. Sort, filter, export.",
    "evts.crush": "Per-stock results IV-crush ledger: last 8 releases, IV before/after, crush %, implied vs realised. ORATS earnings. context.",
    "des.iv_strip": "Profile IV strip: iv30_cm, rank, percentile, skew, IV − RV, next results. Bloomberg DES. context.",
    "memb.regime": "Driver regime strip: leader with tenure and share, 60-session leader, top-5 share, EW − CW, in the neutral token; describes, does not predict.",
    "memb.table": "Members over the chosen horizon: weight, return, points, share; the PTS column follows the horizon. Bloomberg MEMB.",
    "memb.sectors": "Σ points by NSE industry over the horizon. Bloomberg IMAP.",
    "memb.monthly": "12-month leaderboard: leader, top-3 add and drag per month. context.",
    "memb.concentration": "Top-5 share, contribution and weight HHI, effective N, EW − CW over time.",
    "memb.fit": "The identity's fit: explained vs actual points, MAE and R² over 60 sessions, today's residual, which weights priced the day.",
    "mov.today": "Who moved the index today, live from the heatmap (the only live panel; history on MEMB).",
    "desk.book_vs_nifty": "The Desk's real lots × stored closes in pp of NAV beside NIFTY's leaderboard; 'in the liquid fund since 30 Oct' while in cash.",
    "ostr.margin": "Real margin for the structure: SPAN + exposure from Breeze, else the NSE SPAN file, else the heuristic with its 4.8× error printed.",
    "data.table": "Every catalogued dataset: stored date, expected by, sessions behind, catch-up slot, state fresh/amber/red/gap. No composite score.",
    "data.chip": "Header chip 'DATA n STALE' counting red rows; links to SYS › DATA.",
}
# fmt: on

START_HERE: list[str] = ["implied volatility", "IV rank", "IV percentile", "constant-maturity IV", "put-call-parity forward",
                         "25Δ skew", "realised volatility", "FOVOLT", "SPAN margin", "points attribution", "attribution residual",
                         "hysteresis", "badge"]


def build() -> tuple[dict[str, Any], dict[str, Any]]:
    """The two JSON documents (pure: the same module text always gives the same output)."""
    terms = [{"term": t["term"], "short": t["short"], "long": t.get("long", ""), "see_also": list(t.get("see_also", [])),
              "aliases": list(t.get("aliases", []))} for t in TERMS]
    glossary = {"version": VERSION, "agent": AGENT, "count": len(terms), "required": list(REQUIRED_TERMS),
                "start_here": START_HERE, "terms": terms}
    panels = sorted(k for k in TOOLTIPS if "." in k)
    tooltips = {"version": VERSION, "agent": AGENT, "count": len(TOOLTIPS),
                "note": "keys = stored columns / API payload fields of the Terminal v2 tables and routes, or panel ids "
                        "(`panels`, page.panel); every value is one line of at most 200 characters",
                "panels": panels, "tooltips": dict(sorted(TOOLTIPS.items()))}
    return glossary, tooltips


def dumps(doc: dict[str, Any]) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=1) + "\n"


def main() -> None:
    glossary, tooltips = build()
    (HERE / "glossary.json").write_text(dumps(glossary), encoding="utf-8")
    (HERE / "tooltips.json").write_text(dumps(tooltips), encoding="utf-8")
    print(f"wrote glossary.json ({glossary['count']} terms) and tooltips.json ({tooltips['count']} tooltips, "
          f"{len(tooltips['panels'])} panels)")


if __name__ == "__main__":
    main()

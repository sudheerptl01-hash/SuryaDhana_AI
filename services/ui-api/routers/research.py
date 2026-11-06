"""
Research library (RSCH) — every study this project ran, with its verdict, in the terminal.

The reports are the markdown files the research scripts write under reports/<study>/, the strategy lab's
alpha_lab/reports/ (S1 / S1H / S2 / S3, the quick tests, the avoid library) and the reference documents in
docs/. CATALOG carries a curated verdict and one-line takeaway per study (the reports phrase their verdicts
differently, so they are not parsed). A report not in CATALOG is still listed: an engineering record (the
build / design / review program folders in _DIR_KIND) with verdict ENGINEERING, anything else with "—".
Files are served read-only and only from inside reports/, alpha_lab/reports/, alpha_lab/PLAN.md and docs/.

Every entry carries `kind` (study / reference / engineering / other) so a page can count studies honestly, and
`updated` is the study's own date read from its header (a "Last updated" line first, else the first written date
of the title / preamble, else a dated override) with `modified` (the file's mtime) beside it: a file touched
today by an unrelated edit no longer reads "today" (m095).

The first entry is a generated verdict summary (SUMMARY_ID): what works / what fails / what measures, built from
CATALOG at request time, so the page opens on verdicts and never on an engineering changelog (m096).

GET /api/research               → list of studies (id, title, area, verdict, kind, takeaway, updated, data files) + counts
GET /api/research/doc?id=…      → one study's markdown
GET /api/research/verdict?id=…  → one study's catalog row (verdict, takeaway, date) without the markdown
GET /api/research/file?id=…&name=… → a CSV/JSON data file that sits next to a report
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

router = APIRouter()
_IST = timezone(timedelta(hours=5, minutes=30))

_REPO = Path(__file__).resolve().parents[3]
_SKIP_DIRS = {"ui_audit", "daily_wrap"}   # daily wraps have their own page (WRAP)
_DATA_EXT = {".csv", ".json"}
# alpha_lab's dated book printout is a snapshot of one day's research book (`run_today.py` prints today's); listing it
# would read as a current book
_SKIP_FILES = {"alpha_lab/reports/today_book.md"}
SUMMARY_ID = "rsch:summary"

# Verdict families (Terminal v2 PLAN 1.6). A forecast verdict tests a claim about the future; a measurement verdict is
# a description or an identity; REFERENCE supports a study; ENGINEERING is a build / design / review record.
FORECAST_VERDICTS = ("ADOPTED", "PASS", "PROMISING", "FAIL", "NO EDGE")
MEASURE_VERDICTS = ("DESCRIPTIVE", "ARITHMETIC")

# Uncatalogued documents in these report folders are engineering records or journals, not studies (m093).
_DIR_KIND: dict[str, tuple[str, str, str]] = {
    d: ("Engineering", "ENGINEERING", "An engineering record (charter, build, design, review, critique or audit): it carries "
                                      "no research verdict.")
    for d in ("bloomberg_program", "desktop_app", "worldclass_program", "production_review", "resilience_review", "live_nse")
}
_DIR_KIND["journal"] = ("Journal", "REFERENCE",
                        "Weekly decision journal: what the Desk and the paper shadow did that week. A record, not a study.")

# The study's own date where its header carries none that the parser can use (window dates such as "2020-01-01 →
# 2026-10-13" are skipped on purpose: they are the sample, not the day the study ran).
_DATED: dict[str, str] = {
    **{f"alpha_lab/reports/{n}.md": "2026-10-14" for n in (
        "s1_gateA", "s1_gateB", "s1_full", "s1_noveto_diagA", "s1_smoke", "s1H_gateA", "s1H_gateB", "s1H_smoke")},
}
# A document whose first heading no longer describes it (the improvement log became the operations journal).
_TITLE: dict[str, str] = {
    "docs/IMPROVEMENT_LOG.md": "Improvement log: the operations journal (newest entry first)",
}

# id → (area, verdict, takeaway). Verdicts: ADOPTED, PASS, PROMISING, FAIL, NO EDGE, REFERENCE,
# DESCRIPTIVE (a measured description, never a forecast) and ARITHMETIC (an identity / exchange rule) — Terminal v2 PLAN 1.6.
CATALOG: dict[str, tuple[str, str, str]] = {
    "docs/IMPROVEMENT_LOG.md": (
        "What's new", "REFERENCE",
        "The operations journal, newest entry first: what changed, what was deployed, what was checked and what is still "
        "open. The 11–15 Oct terminal sprint (the Bloomberg function map, FA, FUND, MEMB, SEAG, ECO…) sits further down."),
    "reports/worldclass_program/REPORT.md": (
        "Engineering", "ENGINEERING",
        "World-class program (15 Oct 2026): 8 expert builders + 2 adversarial critics in one night. Shipped 5 new "
        "terminal pages (CHRT charts, DERV futures/basis/rollover, OSTR option strategies, MCXG gold desk, RSK "
        "VaR/stress), tick persistence, flaw fixes (55 ms where 1.45 s was) and the MC drawdown lens (S1H flags "
        "DD-FRAGILE — read mc_drawdown.md). Trader critic: TRADE-READY for EOD NSE + MCX paper; engineering critic: "
        "SHIP-WITH-FIXES, all fixed same night; 937 tests. Missing list + two owner actions inside (git remote!)."),
    "reports/bloomberg_program/bloomberg_verdict.md": (
        "Engineering", "ENGINEERING",
        "Bloomberg program (14–15 Oct 2026): analyze→design→build→test→adversarial critique. Critic's verdict NO "
        "with two criticals — tick wire-key mismatch (UI could never render a tick; fixed + contract-pinned same "
        "night, chips now earn LIVE from row truth) and zero repo protection (no git remote, frozen files untracked "
        "— OWNER ACTION). Live feed: CONNECTING→LIVE 3/3 subscribed in market session, honest DISCONNECTED after "
        "midnight rollover. 781 tests, 37/37 pages, 178 rps p95 185 ms, event-loop 1.2× under contention. "
        "Full trail: reports/bloomberg_program/ (REQUIREMENTS → … → test_report, REPORT)."),
    "reports/production_review/REPORT.md": (
        "Engineering", "ENGINEERING",
        "Production review (14 Oct 2026): six parallel audits — health (37/37 pages, 738 tests green), design "
        "system + live design review, duplicate-function removal (~233 LOC + 2 latent bugs), backend↔frontend "
        "contract, scale & latency (warm routes 7–50 ms; the real debts named), operator DevEx (5/10). "
        "Consolidated priority actions at the end."),
    "reports/evidence_probability/FINDINGS.md": (
        "Synthesis", "PASS",
        "Every condition from every study, re-measured on one frame (1,945 liquid NSE stocks, 2011–2026) as a "
        "probability of beating the market, then merged. A liquid stock beats the average over 20 sessions ~45% of "
        "the time; the best evidence lifts that to ~50%, the worst cuts it to ~41% (high volatility: 32% chance of the "
        "worst fifth vs 20%). The logistic merge ranks twice as well as momentum alone, is calibrated out of sample, "
        "and as a Desk veto adds +0.9 to +1.4 pts/yr (paper shadow first). Pays at 60 sessions, about break-even at "
        "20, loses at 5. Label recipe for short / swing / long inside."),
    "reports/evidence_probability/REPORT.md": (
        "Synthesis", "REFERENCE",
        "Full tables: 38 conditions × 3 horizons × 2 universes, credibility, merged-model calibration and buckets, Desk "
        "book test, market regime, label diagnostics, today's readings."),
    "reports/evidence_probability/PLAN.md": (
        "Synthesis", "REFERENCE",
        "Pre-registered plan for the evidence → probability study (14 Oct 2026, 18:10, before any number)."),
    "reports/evidence_probability/first_run_coverage_leak/REPORT.md": (
        "Synthesis", "REFERENCE",
        "First run, kept for the record: the merged model used coverage flags chosen with hindsight (stocks whose data "
        "were fetched because they are liquid today) and rewarded membership; corrected the same evening."),
    "reports/phase_b_extended/REPORT.md": (
        "Strategy", "ADOPTED",
        "Momentum held across 16 years incl. an unseen decade (2011–2020), after real ICICI costs and tax. "
        "Basis of the Decision Desk rules (66% equity share, worst drawdown ≈ −22%)."),
    "reports/phase_b/REPORT.md": (
        "Strategy", "PROMISING",
        "Monthly momentum beat NIFTY after costs and tax in 2019–2026; promoted only after the 2011–2020 check."),
    "reports/costs/CAPITAL_VIABILITY.md": (
        "Costs", "REFERENCE",
        "Yearly cost drag by style: 5-day swing loses ~48–108%/yr to charges; monthly momentum 3–20%; "
        "a position needs ≥ ₹25.5k for a ≤ 1% round trip on ICICI MoneySaver."),
    "reports/desk_filter/REPORT.md": (
        "Strategy", "PASS",
        "Skipping stocks with a non-institutional bulk-deal net buy in the last 20 sessions passed the holdout. "
        "OFF until the owner reviews it (DESK_AVOID_BULK_BUY_DAYS)."),
    "reports/handbook_swing/REPORT.md": (
        "Swing", "FAIL",
        "SuryaDhana Scanner Handbook rules, 2020 → today: −17.8% CAGR after ICICI costs (gross ≈ break-even) vs "
        "Nifty 500 +12.4% and Desk +18.5%. Failed every pre-registered measure; 2011 run skipped."),
    "reports/handbook_swing/DIAGNOSTICS.md": (
        "Swing", "FAIL",
        "Why it failed: median hold 3 sessions, 21% of capital used, regime-4 entries worst; holding winners "
        "40–60 sessions turns positive in R but ≈ 0 vs the universe."),
    "reports/results_drift/FINDINGS.md": (
        "Results", "PASS",
        "Strong bad results keep hurting: after a ≤ −5% vs-market results reaction stocks lag another 2.0–3.7% over 60 "
        "sessions (t ≤ −2.8 both periods), a valid avoid-filter. Good-news drift fails the discovery bar. Re-run 14 Oct "
        "on corrected 2025–26 release times (governance filings had been taken as results): verdicts unchanged."),
    "reports/results_drift/corrected_2026-10-14/REPORT.md": (
        "Results", "REFERENCE", "Post-results drift re-run on corrected release times (14 Oct 2026): 16,271 events, same plan."),
    "reports/results_filter/FINDINGS.md": (
        "Strategy", "FAIL",
        "As a Decision Desk filter, skipping stocks after a ≤ −5% results reaction changes nothing material. On corrected "
        "release times (14 Oct) holdout CAGR is 3.86% vs 3.98% without it (was 4.30% before the fix): no benefit."),
    "reports/fii_positioning/FINDINGS.md": (
        "Flows", "NO EDGE",
        "FII index-futures positioning does not predict NIFTY over 5–20 sessions: flow terciles −0.53% (t −1.34), "
        "extreme FII shorting +0.05% (t 0.07). Context, not a timing signal."),
    "reports/earnings_growth_drift/FINDINGS.md": (
        "Results", "NO EDGE",
        "What the numbers said (profit ≥ +30% & revenue ≥ +10% y/y, from NSE filings) does not predict the next 60 "
        "sessions. The pre-registered broad re-run (5,785 filings, 1,142 companies incl. 16 since delisted) removed "
        "the first run's selection bias: strong growth +1.3% (t 0.9) / +1.0%, ≈ 0 after costs, H1 FAIL."),
    "reports/earnings_growth_drift/broad/REPORT.md": (
        "Results", "REFERENCE", "Broad re-run tables: 5,785 filings from 1,142 companies by growth bucket, 20 / 60 sessions."),
    "reports/earnings_growth_drift/REPORT.md": (
        "Results", "REFERENCE", "Full tables: 1,691 filings from 241 companies by growth bucket, 20 / 60 sessions."),
    "reports/earnings_growth_drift/PLAN.md": (
        "Results", "REFERENCE", "Pre-registered plan for the earnings-growth drift study (13 Oct 2026, before the data)."),
    "reports/results_drift/REPORT.md": (
        "Results", "REFERENCE",
        "Full PEAD tables: 16,247 NSE results 2015–2026 by reaction bucket, timing, liquidity and year."),
    "reports/results_drift/PLAN.md": (
        "Results", "REFERENCE", "The pre-registered plan for the post-results drift study (written before any result)."),
    "reports/held_overnight/FINDINGS.md": (
        "Flows", "PROMISING",
        "Six NSE-flow hypotheses: only insider open-market buys (H4) look promising (forward test from Oct-2026); "
        "retail bulk-deal buying is a negative filter. Delivery %, OI build-up, MTF: no edge."),
    "reports/held_overnight/REPORT.md": (
        "Flows", "REFERENCE",
        "Full tables behind the held-overnight findings (H1–H6, discovery vs holdout, Newey-West t)."),
    "reports/ml_labels/FINDINGS.md": (
        "ML", "FAIL",
        "New 20-session excess-rank labels beat the old 5-day labels on every measure, but the ML top-20 book "
        "still trails plain Desk momentum after costs; NSE flow features add nothing."),
    "reports/ml_labels/REPORT.md": (
        "ML", "FAIL",
        "Audit of the production labels (v2 flaws) and the walk-forward comparison tables."),
    "reports/idea_lab/REPORT.md": (
        "Ideas", "NO EDGE",
        "Eight India-specific ideas (circuits, overnight momentum, lottery, dividends, splits…) on 1,374 stocks: "
        "none survives the holdout after costs. Circuit rebound was removed."),
    "reports/value_area/REPORT.md": (
        "Price action", "NO EDGE",
        "Upside value-area breakouts fail back to the POC more than chance and lag the market: usable only as a veto."),
    "reports/poc_conditional/REPORT.md": (
        "Price action", "NO EDGE",
        "No value-area event beats a random entry into the same stocks; moving averages only shift trend drift."),
    "reports/news_scanner/REPORT.md": (
        "News", "NO EDGE",
        "199 news-scanner picks (25 Sep – 7 Oct 2026) performed like random stocks of similar liquidity; too few days to judge."),
    "reports/data_quality/NSE_PANEL_QA.md": (
        "Data", "REFERENCE",
        "NSE bhavcopy panel vs Yahoo: 0.13% of days differ by > 1 point; 1,064 corporate actions applied; "
        "1,922 delisted symbols restored (survivorship-free)."),
    "reports/data_quality/NSE_PANEL_QA_2010_2019.md": (
        "Data", "REFERENCE", "Spot-check of the 2010–2019 classic bhavcopy era."),
    "docs/PRODUCT_STRATEGY.md": (
        "Plan", "REFERENCE", "The product plan: sleeves, Decision Desk, promotion gates, phases A–E."),
    "docs/NSE_DATA_DICTIONARY.md": (
        "Data", "REFERENCE", "Every free NSE dataset, verified live: files, APIs, publication timing, access traps."),
    # ── GOLD program (26 Oct 2026). Nested paths are not auto-discovered, so every report is listed here; a row whose
    # file does not exist yet (FINDINGS.md, the data dictionary: B5/B7 write them) is simply not listed until it does.
    "reports/gold_program/FINDINGS.md": (
        "Gold", "FAIL",
        "The gold studies' verdict rows (fii_positioning format): no positioning or macro series passes as a forecast; "
        "COT, OI quadrants, ETF flows, real yields and the dollar explain the week they describe. Nothing gold feeds the "
        "Decision Desk, the S1 shadow or the paper ticket's price."),
    "reports/gold_program/G-STUDY/FINDINGS.md": (
        "Gold", "FAIL",
        "CFTC positioning as a forecast: FAIL at 1/4/13 weeks for every metric (managed-money net, COT index, z-score, "
        "commercials, small specs, OI, options-only, GLD, real yields, DXY); 0 of 69 walk-forward long/flat rules beat "
        "buy-and-hold. PASS as a description: same-week Spearman +0.65 between the funds' net change and gold's move. "
        "Month-of-year and the OI quadrant are context only. Publish a 'who did what' strip, never a signal."),
    "reports/gold_program/G-STUDY/REPORT.md": (
        "Gold", "REFERENCE",
        "Long form of the positioning study: 1,063 weekly COT reports 2006–2026 priced on GC=F, release-dated, "
        "Newey-West t; sub-period stability, the 2024–26 doubling with funds cutting length, the driver-label rules."),
    "reports/gold_program/SOURCES.md": (
        "Gold", "REFERENCE",
        "Every gold data source the program verified (140 entries: prices, CFTC, CME FTP, Shanghai, physical, India, macro) "
        "with its verdict (PUBLISH-CORE / PUBLISH-CONTEXT / LINK-ONLY / DO-NOT-PUBLISH), access, terms and ingest notes, "
        "the 71 derived metrics with their badges, the evidence ledger and the IST cadence map."),
    "reports/gold_program/PLAN.md": (
        "Gold", "REFERENCE",
        "The phase-2 build plan for the GOLD page: binding principles, builder ownership, the nine sub-views panel by "
        "panel, the WEI/BRF/CMDT/MCXG consolidation, 19 DuckDB tables and the IST job schedule, the /api/gold contract, "
        "LEARN, the labelling rules, ICICI TOTP auto-login, tests, owner actions and risks."),
    "reports/gold_program/API_CONTRACT.md": (
        "Gold", "REFERENCE",
        "The /api/gold/* and /api/positions/totp/* contract as implemented by ui-api (shapes, caches, freshness states, "
        "the health-verdict rules, what degrades how when data-service or Yahoo is away)."),
    "docs/GOLD_DATA_DICTIONARY.md": (
        "Gold", "REFERENCE", "Every gold series the terminal stores, generated from the catalog: publisher, cadence, lag, "
        "formula, verdict and badge."),
    "reports/gold_program/G-EDU/CURRICULUM.md": (
        "Gold", "REFERENCE",
        "LEARN: gold from zero to professional in ten parts (units and purity, venues and the rupee price build, futures "
        "mechanics, the players, drivers and regimes 2001–2025, reading the data, carry/options/term structure, panel "
        "micro-copy, daily/weekly/monthly routines) with the 129-term glossary and 93 tooltips beside it."),
    "reports/gold_program/G-EDU/REPORT.md": (
        "Gold", "REFERENCE", "The education layer's own report: what was verified, the [B]/[P] layer design, what each "
        "panel's micro-copy must say and must not claim."),
    "reports/gold_program/G-COT/REPORT.md": (
        "Gold", "REFERENCE",
        "CFTC Commitments of Traders for COMEX gold: the four Socrata datasets (disaggregated/legacy × futures/combined), "
        "release calendar in IST, the trader groups explained, the weekly metrics table 1986→2026 and the study seed."),
    "reports/gold_program/G-CME/REPORT.md": (
        "Gold", "REFERENCE",
        "COMEX via CME's FTP server (the www site blocks this IP): daily volume and open interest by product since 2014, "
        "EFRP prints, the product calendar (FND/LTD) and the product reference file; warehouse stocks and bulletins stay "
        "link-only until the owner resolves the block (O-2)."),
    "reports/gold_program/G-KITCO/REPORT.md": (
        "Gold", "REFERENCE",
        "What Kitco's gold charts show and how to do them our way (IST first, MCX hours, previous-day overlay, settle line, "
        "session bands); the Yahoo 429 finding (one fetcher, no new pollers) and the nine-sub-view page sketch."),
    "reports/gold_program/G-APP/REPORT.md": (
        "Gold", "REFERENCE",
        "Audit of gold inside the terminal before the program: six surfaces, four Yahoo fetchers, the fair-open model "
        "printed five times; the consolidation and the 43rd-page touch points."),
    "reports/gold_program/G-INDIA/REPORT.md": (
        "Gold", "FAIL",
        "India: the duty (15 % since 13 May 2026), the rupee price build (landed → duty-paid → IBJA premium → MCX basis), "
        "the ICICI master as the only free daily MCX OI, GOLDTEN missing from the specs; G-INDIA-1 (AMFI gold-ETF flows "
        "as timing) FAIL."),
    "reports/gold_program/G-LOGIN/REPORT.md": (
        "Gold", "REFERENCE",
        "ICICI auto-login with TOTP: the code already does it end to end (RFC 6238 tested); only the secret is missing. "
        "Owner steps to get the setup key, Keychain vs .env, the BRKR panel design and the hardening list."),
    "reports/gold_program/G-MACRO/REPORT.md": (
        "Gold", "REFERENCE",
        "Macro drivers verified live (Treasury, FRED keyless CSV, Atlanta Fed, ForexFactory, GPR, World Bank): real yields "
        "and the dollar explain the week (weekly beta ≈ −1.0 to DXY in every regime) but nothing leads; the KGX "
        "decomposition, gold in INR/EUR/JPY/CNY, GVZ sizing, seasonality with its caveat."),
    "reports/terminal_v2/PLAN.md": (
        "Terminal v2", "REFERENCE",
        "The Terminal v2 build program (4 Nov 2026): IV history and daily IV analysis, who drives NIFTY, the options "
        "desk (real SPAN margin, paper F&O book), a data tier that says when it is stale, the appliance platform — in "
        "four waves with the binding honesty rules (badges, store-then-show, point-in-time, no Yahoo, frozen trading "
        "rules) and the 31 owner decisions."),
    "reports/terminal_v2/API_CONTRACT.md": (
        "Terminal v2", "REFERENCE",
        "The ui-api contract as implemented for Wave 1 (B3): /api/derivatives/iv/*, /vol-screen, /api/market/index-drivers*, "
        "/api/desk/attribution, POST /api/options/margin, /api/data/health, the Breeze budget ledger — with the key "
        "inventory generated from the test fixtures (the test fails when the document and the code disagree)."),
    "reports/terminal_v2/R-IV/REPORT.md": (
        "Terminal v2", "DESCRIPTIVE",
        "IV history (DESCRIPTIVE): a point-in-time IV store from the stored NSE F&O bhavcopies (Black-76 on the parity "
        "forward, constant-maturity 30/60/90, rank AND percentile each defined, 25Δ skew, IV vs three realised vols, the "
        "results IV-crush ledger). Prototype corr 0.998 vs the product's ATM IV, 0.983 vs India VIX. Describes, does not "
        "predict: no IV series carries a signal badge."),
    "reports/terminal_v2/R-DRIVERS/REPORT.md": (
        "Terminal v2", "DESCRIPTIVE",
        "Index drivers (DESCRIPTIVE): who moved NIFTY, in index points per name per day (previous level × PIT weight × "
        "return), weights rebuilt from filings and calibrated to NSE's daily top-10 file (R² 0.996, MAE 9.4 pts/day over "
        "229 sessions), a driver state with hysteresis, sector and breadth. An accounting identity with its residual "
        "shown; describes, does not predict."),
    "reports/terminal_v2/R-OPTIONS/REPORT.md": (
        "Terminal v2", "ARITHMETIC",
        "SPAN margin (ARITHMETIC): the OSTR heuristic was 4.8× too high (₹3.9 L vs Breeze SPAN ₹81,497 for the same "
        "NIFTY condor). Real margin now: Breeze margin_calculator when the session is live → the NSE SPAN risk-parameter "
        "file parsed offline (16-scenario risk arrays, calendar-spread charge, short-option minimum) → the heuristic last, "
        "with its measured error printed. Plus the options-trader toolkit audit and ranking."),
    "reports/terminal_v2/R-DATA/REPORT.md": (
        "Terminal v2", "REFERENCE",
        "Data update side: what runs when and what it writes, 55 % market-hours availability over 14 days, the freshness "
        "matrix of every dataset the terminal shows (22 green / 15 amber / 8 red on 4 Nov), the measured NSE publication "
        "clock (F&O 20:10, bhavcopy re-published 22:05, MTF 22:12) and the data-health page spec behind /api/data/health."),
    "reports/terminal_v2/STUDIES.md": (
        "Terminal v2", "REFERENCE",
        "Study registry (B8, 5 Nov 2026): three studies pre-registered before any result — TV-IVRV (IV − RV spread and IV "
        "percentile vs next-month vol and return), TV-DRIVERS (do NIFTY's drivers persist; does a driver change precede "
        "anything), TV-GEX (a dealer-gamma proxy vs the next-day range). Signed verdict rule: t ≥ 2 in the claimed direction, "
        "full sample and both halves, after costs. Results PROVISIONAL until the stored backfill reproduces them."),
    "reports/terminal_v2/studies/iv_rv/FINDINGS.md": (
        "Terminal v2", "FAIL",
        "TV-IVRV, PROVISIONAL (5 Nov 2026; 1,487 NIFTY / 1,459 BANKNIFTY sessions 2020-10 → 2026-10 recomputed from the "
        "cached F&O files): the IV − RV spread and the IV percentile carry information about next month's realised vol beyond "
        "trailing RV (CONTEXT-ONLY by ceiling; NIFTY t 4.7 / 3.0, both halves) but time neither the seller's edge (FAIL: the "
        "spread's effect flips sign between halves) nor the index return ('buy fear' FAIL after the 0.93 % cash round trip). "
        "0 PASS of 12: the IV chips keep arithmetic / context; describes, does not predict."),
    "reports/terminal_v2/studies/drivers/FINDINGS.md": (
        "Terminal v2", "FAIL",
        "TV-DRIVERS, PROVISIONAL (583 fit-gated sessions, Nov 2023 → Oct 2026; the cached share counts start in late 2023): "
        "the 20-session NIFTY leader does not keep a bigger share of the next month's move than the largest-weight name (FAIL, "
        "t −3.2 the wrong way) and does not keep driving relative to NIFTY (FAIL, t −0.3; long-only after costs −1.0 % per "
        "tranche); driver changes PENDING (15 events < 20). The regime strip stays context: describes, does not predict."),
    "reports/terminal_v2/studies/gex/FINDINGS.md": (
        "Terminal v2", "FAIL",
        "TV-GEX, PROVISIONAL (1,740 sessions 2019-10 → 2026-11; Wave 3.3's precondition): neither gamma-exposure convention "
        "forecasts NIFTY's next-day range beyond recent ranges, IV and the expiry calendar — the vendor net-gamma share is flat "
        "(t −0.3); the 'writers are short' gamma load comes with SMALLER ranges (t −3.2, both halves), against the claim; "
        "selling the next-day straddle on 'long-gamma' days earns nothing after costs. The proxy stays heuristic."),
    "reports/gold_program/G-PHYSICAL/REPORT.md": (
        "Gold", "REFERENCE",
        "Physical supply and demand, OTC and the balance sheet: WGC chart API, GLD daily tonnes since 2004, IMF official "
        "gold by country, SGE withdrawals and Au(T+D), LBMA vaults and turnover, RBI reserves, IBJA; the terms posture "
        "(display with attribution, never re-serve) is the real constraint."),
    # ── study documents that were listed without a verdict (m093) ────────────────────────────────────────────────────
    "reports/fii_positioning/REPORT.md": (
        "Flows", "REFERENCE",
        "Full tables behind the FII positioning verdict: flow terciles and extreme FII shorting against NIFTY's next 5–20 "
        "sessions, Newey-West t."),
    "reports/fii_positioning/PLAN.md": (
        "Flows", "REFERENCE", "Pre-registered plan for the FII index-futures positioning study (written before any result)."),
    "reports/results_filter/REPORT.md": (
        "Strategy", "REFERENCE", "Full tables behind the results-filter verdict: Desk holdout CAGR with and without the filter."),
    "reports/results_filter/PLAN.md": (
        "Strategy", "REFERENCE", "Pre-registered plan for the Decision Desk 'skip after bad results' filter test."),
    "reports/ml_labels/LABEL_REVIEW_CHECK.md": (
        "ML", "REFERENCE",
        "An outside 'label logic review' checked against this repository (15 Oct 2026): the code it reviewed does not exist "
        "here; the repo's labels and the label study stand."),
    "reports/gold_program/STUDIES.md": (
        "Gold", "REFERENCE", "The gold program's study registry: one list of study ids, each with its plan and its verdict file."),
    "reports/gold_program/FINAL_REPORT.md": (
        "Gold", "REFERENCE", "GOLD program final report (5 Nov 2026): what shipped, how it was verified, what is still open."),
    "reports/gold_program/OWNER_GUIDE.md": (
        "Gold", "REFERENCE", "The owner's guide to the GOLD page: what each sub-view shows and the labelling rules behind it."),
    "reports/terminal_v2/RATING.md": (
        "Terminal v2", "REFERENCE",
        "Product rating of the terminal (4 Nov 2026), page by page, from the seven Terminal v2 research reports: what a "
        "professional would use and what is missing."),
    "reports/terminal_v2/RATING_20261105.md": (
        "Terminal v2", "REFERENCE", "Re-rating after the 5 Nov 43-page expert review (same scale as the 4 Nov rating)."),
    # ── alpha_lab: the strategy lab's pre-registered family of six and its leads (M22). Paper only; nothing here is a
    # live rule. Gate A = 2020-01-01 → 2026-10-13, Gate B = 2011 → 2019, real ICICI costs + slippage. ───────────────────
    "alpha_lab/reports/FINDINGS.md": (
        "Alpha lab", "PASS",
        "The strategy lab's family of six (pre-registered 14 Oct 2026, real ICICI costs): S1 Sentinel momentum (top-20 "
        "momentum minus five avoid flags, monthly, crash filter) PASSES both gates: 28.0% CAGR 2020 → Oct 2026 (NIFTY 9.6%, "
        "drawdown −16.5%) and 15.8% in the unseen 2011–2019 decade (NIFTY 7.9%, drawdown −34.6%, 5 of 9 years, at the "
        "edge of both bars). S1H passes A and fails B; S2 fails its drawdown budget; S3 leader-dip delivery FAILS: STAY "
        "AWAY. Q1 excess carry is the first Robust F&O lead. A backtest pass: the paper shadow (from 15 Oct) is the "
        "forward test."),
    "alpha_lab/reports/s1_gateA.md": (
        "Alpha lab", "PASS",
        "S1 Gate A (2020-01 → 2026-10-13): CAGR 28.02% vs NIFTY 9.63% and the equal-weight universe 24.16%, max drawdown "
        "−16.5%, IR 0.74, 81 rebalances, after ICICI costs: PASS 5/5. Monte-Carlo p95 drawdown −26.0%, within the −30% "
        "budget."),
    "alpha_lab/reports/s1_gateB.md": (
        "Alpha lab", "PASS",
        "S1 Gate B, the unseen decade (2011 → 2019): CAGR 15.80% vs NIFTY 7.87%, max drawdown −34.6% against the −35% bar, "
        "5 of 9 years ahead of NIFTY against the 5 needed: PASS at the edge of both bars. The Monte-Carlo lens flags it "
        "DD-FRAGILE (p95 −39.2%)."),
    "alpha_lab/reports/s1_full.md": (
        "Alpha lab", "REFERENCE",
        "S1 over the whole 2011 → Oct 2026 panel (informational, no pre-registered gate): CAGR 20.97% vs NIFTY 8.63%, max "
        "drawdown −34.6%, IR 0.60, costs ₹38.2 L on ₹10 L → ₹2.0 cr. 2018 −18.3% vs NIFTY +3.2%: the edge comes in bursts."),
    "alpha_lab/reports/s1_noveto_diagA.md": (
        "Alpha lab", "REFERENCE",
        "Diagnostic: S1 without the avoid-flag veto, same 2020 → 2026 window: CAGR 28.37% but max drawdown −21.8% (−16.5% "
        "with the veto). The refusal rules remove pain; they do not add return."),
    "alpha_lab/reports/s1H_gateA.md": (
        "Alpha lab", "PASS",
        "S1H (₹50 L, 85/15, a whole-lot NIFTY futures short when NIFTY < its 200-DMA), Gate A: CAGR 26.25%, max drawdown "
        "−24.0%, IR 0.69: PASS. Monte-Carlo p95 drawdown −31.9%: DD-FRAGILE."),
    "alpha_lab/reports/s1H_gateB.md": (
        "Alpha lab", "FAIL",
        "S1H Gate B (2011 → 2019): CAGR 14.68% vs NIFTY 7.87%, but only 4 of 9 years ahead of NIFTY (5 needed): FAIL. The "
        "hedge's cost shows up as lagging most calm years."),
    "alpha_lab/reports/s1_smoke.md": (
        "Alpha lab", "REFERENCE", "S1 mechanics smoke run (Oct 2025 → Oct 2026): proves the engine runs end to end; no verdict."),
    "alpha_lab/reports/s1H_smoke.md": (
        "Alpha lab", "REFERENCE", "S1H mechanics smoke run (Oct 2025 → Oct 2026): proves the engine runs end to end; no verdict."),
    "alpha_lab/reports/s2_RESULTS.md": (
        "Alpha lab", "FAIL",
        "S2 Horizon-60 probability book (₹10 L, every 12th Friday): Gate A FAIL on drawdown (−32.0% against the −30% "
        "budget) despite 23.6% CAGR; Gate B not run, per protocol. S2H (hedged) passes A (19.4%, drawdown −28.0%) and "
        "fails B (3 of 9 years ahead of NIFTY)."),
    "alpha_lab/reports/s3_RESULTS.md": (
        "Alpha lab", "FAIL",
        "S3 leader-dip, the pre-registered stay-away: delivery with 5-session holds FAILS (1,498 trades, win 47.2%, "
        "−0.006% a trade after costs, CAGR −4.28%, drawdown −58.1%): STAY AWAY. The futures variant keeps +0.295% a trade "
        "net (923 trades, win 53.2%) but 1-lot sizing deploys ~₹23 L of ₹1 Cr (+1.9%/yr on capital): a capacity-capped "
        "lead, FAIL as a book."),
    "alpha_lab/reports/quick_tests_RESULTS.md": (
        "Alpha lab", "PROMISING",
        "Five pre-registered F&O quick tests (gross diagnostics, not strategies): Q1 excess carry is Robust, stock futures "
        "at a discount to fair value lag over the next 20 sessions in both periods (−0.49%, t −4.2 / −0.38%, t −2.9). A lead "
        "for its own pre-registered study, never a live rule. Q2 option/stock volume, Q3 variance risk premium and Q4 index "
        "OI-PCR: no effect. Q5 (F&O entry / exit) is descriptive only."),
    "alpha_lab/reports/avoid_rules.md": (
        "Alpha lab", "PASS",
        "The avoid library: 12 'do not newly buy when…' rules with measured odds (base: a liquid stock beats the market ~45% "
        "of the time). Robust: below the 200-DMA (42.1% at 60 sessions), bottom-decile momentum (38.5%), within 10% of the "
        "52-week low, a split / bonus in the last 20 sessions (40.2% at 5 sessions), an upside value-area break, "
        "top-decile volatility (worst fifth 32% vs 20%); plus the retired-ideas list so nobody rebuilds them."),
    "alpha_lab/reports/mc_drawdown.md": (
        "Alpha lab", "DESCRIPTIVE",
        "Monte-Carlo drawdown lens (block bootstrap of monthly returns, 10,000 resamples, report-only): S1 Gate A within "
        "budget (p95 −26.0%); S1 Gate B and S1H A / B DD-FRAGILE (p95 beyond the −30% / −35% budgets although the realised "
        "paths passed). Describes, does not predict."),
    "alpha_lab/reports/hedge_overlay.md": (
        "Alpha lab", "REFERENCE",
        "Modeled index puts (Black-Scholes at India VIX × 1.1; MODELED, never gated, blind to panic skew): always-hedged "
        "costs ~5%/yr of CAGR; the liquid-fund yield convention moves S1 by ±0.7 pts for ±2 pts of yield."),
    "alpha_lab/reports/claims_matrix.md": (
        "Alpha lab", "REFERENCE",
        "~70 claims from two imported research documents reconciled against this repo's measurements: OI quadrants, PCR "
        "and max pain fail on the data; post-split drift and the abnormal-volume premium are sign-flipped in India."),
    "alpha_lab/reports/plan_review.md": (
        "Alpha lab", "REFERENCE",
        "Red-team review of the alpha-lab plan before any run: 17 findings, 6 blockers; all 11 sign-off conditions were "
        "adopted into the plan's Amendments v2 before the gates ran."),
    "alpha_lab/reports/shadow_status.md": (
        "Alpha lab", "REFERENCE",
        "The S1 / S1H paper shadow (forward test from 15 Oct 2026, nightly 19:50; paper only, no orders): NAV against NIFTY "
        "as of the file's date. A forward record, far too short to judge."),
    "alpha_lab/PLAN.md": (
        "Alpha lab", "REFERENCE",
        "The alpha-lab plan, pre-registered 14 Oct 2026 ~21:05 IST before any backtest: S1 / S2 / S3 rules, Gate A (2020 →) "
        "and Gate B (2011–2019) bars, the Appendix Q quick tests and Amendments v2."),
}
_ORDER = list(CATALOG)


def _root() -> Path:
    env = os.environ.get("RESEARCH_ROOT", "").strip()
    for p in ([Path(env)] if env else []) + [_REPO, Path("/app")]:
        if (p / "reports").is_dir():
            return p
    return _REPO


def _discover(root: Path) -> list[str]:
    ids = [i for i in _ORDER if (root / i).is_file()]
    found = [p for p in (root / "reports").glob("*/*.md") if p.parent.name not in _SKIP_DIRS]
    found += list((root / "alpha_lab" / "reports").glob("*.md"))
    extra = sorted(rel for rel in (str(p.relative_to(root)) for p in found)
                   if rel not in CATALOG and rel not in _SKIP_FILES)
    return ids + extra


def _resolve(root: Path, rel: str) -> Path:
    """Map an id to a file strictly inside reports/, alpha_lab/ or docs/ (no traversal, markdown only). The generated
    summary has no file behind it, so it never resolves (its data-file route would otherwise read the repo root)."""
    if rel == SUMMARY_ID or rel not in _discover(root):
        raise HTTPException(status_code=404, detail="Unknown report")
    return (root / rel).resolve()


def _title(path: Path) -> str:
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("# "):
                    return line[2:].strip()
    except OSError:
        pass
    return path.stem.replace("_", " ").title()


def _classify(rel: str) -> tuple[str, str, str]:
    """(area, verdict, takeaway): the CATALOG row, else the folder's kind (engineering records, journals), else Other."""
    if rel in CATALOG:
        return CATALOG[rel]
    parts = rel.split("/")
    if len(parts) >= 3 and parts[0] == "reports" and parts[1] in _DIR_KIND:
        return _DIR_KIND[parts[1]]
    return ("Other", "—", "")


def kind_of(verdict: str) -> str:
    if verdict in FORECAST_VERDICTS or verdict in MEASURE_VERDICTS:
        return "study"
    return {"REFERENCE": "reference", "ENGINEERING": "engineering", "SUMMARY": "summary"}.get(verdict, "other")


_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_TEXT_DATE = re.compile(r"\b(\d{1,2})(?:\s*[–-]\s*(\d{1,2}))?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s+(20\d\d)\b",
                        re.IGNORECASE)
_ISO_DATE = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)(?!\d)")
_ISO_RANGE = re.compile(r"\b\d{4}-\d\d(?:-\d\d)?\s*(?:→|->|to)\s*\d{4}-\d\d(?:-\d\d)?")
_CODE = re.compile(r"`[^`]*`")
_UPDATED_LINE = re.compile(r"\b(last updated|updated|as of|generated|run)\b", re.IGNORECASE)
_HEADER_LINES = 15


def _dates_in(line: str) -> list[date]:
    """Dates written on one header line. A range ("11–15 Oct 2026") counts as its last day. An ISO date counts only on a
    "generated / run / as of / updated" line, and never inside code or a sample window ("2020-01-01 → 2026-10-13",
    "--panel-start 2010-01-01"): those are the data's span, not the day the study ran."""
    out: list[date] = []
    line = _CODE.sub(" ", line)
    for m in _TEXT_DATE.finditer(line):
        try:
            out.append(date(int(m.group(4)), _MONTHS[m.group(3).lower()[:3]], int(m.group(2) or m.group(1))))
        except ValueError:
            continue
    if _UPDATED_LINE.search(line):
        for m in _ISO_DATE.finditer(_ISO_RANGE.sub(" ", line)):
            try:
                out.append(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
            except ValueError:
                continue
    return out


def study_date(path: Path, rel: str, modified: date) -> date | None:
    """The study's own date (m095): a dated override, else a "Last updated / As of / Generated / run" line in the header,
    else the first date written in the title or preamble. A date after the file's last modification cannot be the
    study's own, so it is ignored. None = the header carries no usable date."""
    if rel in _DATED:
        return date.fromisoformat(_DATED[rel])
    first: date | None = None
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for n, line in enumerate(fh):
                if n >= _HEADER_LINES:
                    break
                found = [d for d in _dates_in(line) if d <= modified]
                if not found:
                    continue
                pick = max(found) if ("→" in line or "–" in line) else found[0]
                if _UPDATED_LINE.search(_CODE.sub(" ", line)):
                    return pick
                if first is None:
                    first = pick
    except OSError:
        return None
    return first


def _data_files(path: Path, rel: str) -> list[dict[str, Any]]:
    """CSV / JSON files beside a report. alpha_lab keeps every run's files in one folder, so a lab report lists only the
    files of its own run (s1_gateA.md → s1_gateA_*.csv; s3_RESULTS.md → s3_*; the quick tests → qt_*)."""
    if not (rel.startswith("reports/") or rel.startswith("alpha_lab/reports/")):
        return []
    files = sorted((f for f in path.parent.iterdir() if f.is_file() and f.suffix in _DATA_EXT), key=lambda f: f.name)
    if rel.startswith("alpha_lab/reports/"):
        stem = path.stem
        own = [f for f in files if f.stem.startswith(stem)]
        if not own:
            prefix = {"quick_tests_RESULTS": "qt_"}.get(stem, stem.split("_")[0] + "_")
            own = [f for f in files if f.name.startswith(prefix)] if stem != "FINDINGS" else []
        files = own
    return [{"name": f.name, "kb": round(f.stat().st_size / 1024, 1)} for f in files]


def _entry(root: Path, rel: str) -> dict[str, Any]:
    path = root / rel
    area, verdict, takeaway = _classify(rel)
    st = path.stat()
    modified = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
    dated = study_date(path, rel, modified.astimezone(_IST).date())
    updated = datetime.combine(dated, time(0, 0), tzinfo=_IST).isoformat() if dated else modified.isoformat()
    return {"id": rel, "title": _TITLE.get(rel) or _title(path), "area": area, "verdict": verdict, "kind": kind_of(verdict),
            "takeaway": takeaway, "updated": updated, "dated_from": "document" if dated else "file",
            "modified": modified.isoformat(),
            "lines": sum(1 for _ in path.open(encoding="utf-8", errors="replace")), "data_files": _data_files(path, rel)}


# ── the generated verdict summary (m096) ──────────────────────────────────────────────────────────────────────────────
_SUMMARY_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("What works: the verdicts you may act on", ("ADOPTED", "PASS")),
    ("Leads: promising, not yet proven", ("PROMISING",)),
    ("What fails: do not trade these, however good they look on a chart", ("FAIL", "NO EDGE")),
    ("What measures: read it, never forecast from it", ("DESCRIPTIVE", "ARITHMETIC")),
)


def counts_of(entries: list[dict[str, Any]]) -> dict[str, int]:
    kinds = [e["kind"] for e in entries]
    return {"studies": kinds.count("study"),
            "forecast_verdicts": sum(e["verdict"] in FORECAST_VERDICTS for e in entries),
            "measurements": sum(e["verdict"] in MEASURE_VERDICTS for e in entries),
            "references": kinds.count("reference"), "engineering": kinds.count("engineering"), "other": kinds.count("other")}


def summary_doc(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """A verdict summary built from the catalog at request time: never stale against CATALOG, never hand-edited."""
    by = {v: [e for e in entries if e["verdict"] == v] for v in FORECAST_VERDICTS + MEASURE_VERDICTS}
    c = counts_of(entries)
    n_work = len(by["ADOPTED"]) + len(by["PASS"])
    n_fail = len(by["FAIL"]) + len(by["NO EDGE"])
    takeaway = (f"{c['forecast_verdicts']} forecast verdicts — {n_work} ADOPTED or PASS, {len(by['PROMISING'])} PROMISING, "
                f"{n_fail} FAIL or NO EDGE — and {c['measurements']} measurements, every one pre-registered and judged after "
                "real ICICI costs. A PASS on a backtest is not a forward result: the Decision Desk's paper book and the S1 "
                "paper shadow are the forward tests.")
    lines = ["# Verdict summary: what works, what fails, what measures", "",
             f"Generated from the research catalog when this page opened: {c['studies']} studies carry a verdict; "
             f"{c['references']} reference documents and {c['engineering']} engineering records sit in the list beside them "
             "without one. Costs are the real ICICI delivery round trip (≈ 0.93 % + ₹24, `shared/trading_costs.py`).", ""]
    for heading, verdicts in _SUMMARY_GROUPS:
        rows = [e for v in verdicts for e in by[v]]
        lines += [f"## {heading} ({len(rows)})", ""]
        for e in rows:
            lines.append(f"- **{e['verdict']}** · {e['area']} · **{e['title']}** — {e['takeaway']} `{e['id']}`")
        lines.append("")
    lines += ["Everything else on this page is REFERENCE (plans, full tables, data dictionaries) or an ENGINEERING record "
              "(build, design and review reports): read them for how a number was made, not for whether it predicts."]
    dated = [e["updated"] for e in entries if e["kind"] == "study"]
    md = "\n".join(lines) + "\n"
    return {"id": SUMMARY_ID, "title": "Verdict summary: what works, what fails, what measures", "area": "Start here",
            "verdict": "SUMMARY", "kind": "summary", "takeaway": takeaway, "updated": max(dated, key=datetime.fromisoformat) if dated else None,
            "dated_from": "document", "modified": None, "lines": md.count("\n"), "data_files": [], "markdown": md}


def _entries(root: Path) -> list[dict[str, Any]]:
    return [_entry(root, rel) for rel in _discover(root)]


@router.get("")
def list_research() -> dict[str, Any]:
    entries = _entries(_root())
    summary = {k: v for k, v in summary_doc(entries).items() if k != "markdown"}
    return {"data": [summary, *entries], "counts": counts_of(entries)}


@router.get("/doc")
def get_doc(id: str = Query(..., max_length=200)) -> dict[str, Any]:
    root = _root()
    if id == SUMMARY_ID:
        return summary_doc(_entries(root))
    path = _resolve(root, id)
    return {**_entry(root, id), "markdown": path.read_text(encoding="utf-8", errors="replace")}


@router.get("/verdict")
def get_verdict(id: str = Query(..., max_length=200)) -> dict[str, Any]:
    """One study's catalog row without its markdown: what a page footer or banner reads at render time, so a page can
    never quote a superseded verdict (FUND quoted PROMISING while the library said NO EDGE: M21)."""
    root = _root()
    _resolve(root, id)
    e = _entry(root, id)
    return {k: e[k] for k in ("id", "title", "area", "verdict", "kind", "takeaway", "updated")}


@router.get("/file")
def get_file(id: str = Query(..., max_length=200), name: str = Query(..., max_length=200)) -> FileResponse:
    root = _root()
    report = _resolve(root, id)
    if not re.fullmatch(r"[\w.\-]+", name) or Path(name).suffix not in _DATA_EXT:
        raise HTTPException(status_code=400, detail="Bad file name")
    f = (report.parent / name).resolve()
    if f.parent != report.parent or not f.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(f, filename=name, media_type="text/csv" if f.suffix == ".csv" else "application/json")

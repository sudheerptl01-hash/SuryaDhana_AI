"""
Research library (RSCH) — every study this project ran, with its verdict, in the terminal.

The reports are the markdown files the research scripts write under reports/<study>/ plus the two
reference documents in docs/. CATALOG carries a curated verdict and one-line takeaway per study (the
reports phrase their verdicts differently, so they are not parsed); any report not in CATALOG is still
listed, with verdict "—". Files are served read-only and only from inside reports/ and docs/.

GET /api/research               → list of studies (id, title, area, verdict, takeaway, updated, data files)
GET /api/research/doc?id=…      → one study's markdown
GET /api/research/file?id=…&name=… → a CSV/JSON data file that sits next to a report
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

router = APIRouter()

_REPO = Path(__file__).resolve().parents[3]
_SKIP_DIRS = {"ui_audit", "daily_wrap"}   # daily wraps have their own page (WRAP)
_DATA_EXT = {".csv", ".json"}

# id → (area, verdict, takeaway). Verdicts: ADOPTED, PASS, PROMISING, FAIL, NO EDGE, REFERENCE,
# DESCRIPTIVE (a measured description, never a forecast) and ARITHMETIC (an identity / exchange rule) — Terminal v2 PLAN 1.6.
CATALOG: dict[str, tuple[str, str, str]] = {
    "docs/IMPROVEMENT_LOG.md": (
        "What's new", "REFERENCE",
        "The 11–14 Oct 2026 terminal sprint. Start here: what to know first (surveillance flags on your holdings, the "
        "results release-time fix), the Bloomberg function map, then every new function (FA, FUND, MEMB, SEAG, ECO, HP, "
        "valuation history, options into results, short selling…) with how each was checked."),
    "reports/worldclass_program/REPORT.md": (
        "Engineering", "REFERENCE",
        "World-class program (15 Oct 2026): 8 expert builders + 2 adversarial critics in one night. Shipped 5 new "
        "terminal pages (CHRT charts, DERV futures/basis/rollover, OSTR option strategies, MCXG gold desk, RSK "
        "VaR/stress), tick persistence, flaw fixes (55 ms where 1.45 s was) and the MC drawdown lens (S1H flags "
        "DD-FRAGILE — read mc_drawdown.md). Trader critic: TRADE-READY for EOD NSE + MCX paper; engineering critic: "
        "SHIP-WITH-FIXES, all fixed same night; 937 tests. Missing list + two owner actions inside (git remote!)."),
    "reports/bloomberg_program/bloomberg_verdict.md": (
        "Engineering", "REFERENCE",
        "Bloomberg program (14–15 Oct 2026): analyze→design→build→test→adversarial critique. Critic's verdict NO "
        "with two criticals — tick wire-key mismatch (UI could never render a tick; fixed + contract-pinned same "
        "night, chips now earn LIVE from row truth) and zero repo protection (no git remote, frozen files untracked "
        "— OWNER ACTION). Live feed: CONNECTING→LIVE 3/3 subscribed in market session, honest DISCONNECTED after "
        "midnight rollover. 781 tests, 37/37 pages, 178 rps p95 185 ms, event-loop 1.2× under contention. "
        "Full trail: reports/bloomberg_program/ (REQUIREMENTS → … → test_report, REPORT)."),
    "reports/production_review/REPORT.md": (
        "Engineering", "REFERENCE",
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
        "Terminal v2", "REFERENCE",
        "TV-IVRV, PROVISIONAL (5 Nov 2026; 1,487 NIFTY / 1,459 BANKNIFTY sessions 2020-10 → 2026-10 recomputed from the "
        "cached F&O files): the IV − RV spread and the IV percentile carry information about next month's realised vol beyond "
        "trailing RV (CONTEXT-ONLY by ceiling; NIFTY t 4.7 / 3.0, both halves) but time neither the seller's edge (FAIL: the "
        "spread's effect flips sign between halves) nor the index return ('buy fear' FAIL after the 0.93 % cash round trip). "
        "0 PASS of 12: the IV chips keep arithmetic / context; describes, does not predict."),
    "reports/terminal_v2/studies/drivers/FINDINGS.md": (
        "Terminal v2", "REFERENCE",
        "TV-DRIVERS, PROVISIONAL (583 fit-gated sessions, Nov 2023 → Oct 2026; the cached share counts start in late 2023): "
        "the 20-session NIFTY leader does not keep a bigger share of the next month's move than the largest-weight name (FAIL, "
        "t −3.2 the wrong way) and does not keep driving relative to NIFTY (FAIL, t −0.3; long-only after costs −1.0 % per "
        "tranche); driver changes PENDING (15 events < 20). The regime strip stays context: describes, does not predict."),
    "reports/terminal_v2/studies/gex/FINDINGS.md": (
        "Terminal v2", "REFERENCE",
        "TV-GEX, PROVISIONAL (1,740 sessions 2019-10 → 2026-11; Wave 3.3's precondition): neither gamma-exposure convention "
        "forecasts NIFTY's next-day range beyond recent ranges, IV and the expiry calendar — the vendor net-gamma share is flat "
        "(t −0.3); the 'writers are short' gamma load comes with SMALLER ranges (t −3.2, both halves), against the claim; "
        "selling the next-day straddle on 'long-gamma' days earns nothing after costs. The proxy stays heuristic."),
    "reports/gold_program/G-PHYSICAL/REPORT.md": (
        "Gold", "REFERENCE",
        "Physical supply and demand, OTC and the balance sheet: WGC chart API, GLD daily tonnes since 2004, IMF official "
        "gold by country, SGE withdrawals and Au(T+D), LBMA vaults and turnover, RBI reserves, IBJA; the terms posture "
        "(display with attribution, never re-serve) is the real constraint."),
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
    extra = sorted(str(p.relative_to(root)) for p in (root / "reports").glob("*/*.md")
                   if p.parent.name not in _SKIP_DIRS and str(p.relative_to(root)) not in CATALOG)
    return ids + extra


def _resolve(root: Path, rel: str) -> Path:
    """Map an id to a file strictly inside reports/ or docs/ (no traversal, markdown only)."""
    if rel not in _discover(root):
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


def _entry(root: Path, rel: str) -> dict[str, Any]:
    path = root / rel
    area, verdict, takeaway = CATALOG.get(rel, ("Other", "—", ""))
    data: list[dict[str, Any]] = []
    if rel.startswith("reports/"):
        files = sorted((f for f in path.parent.iterdir() if f.is_file() and f.suffix in _DATA_EXT), key=lambda f: f.name)
        data = [{"name": f.name, "kb": round(f.stat().st_size / 1024, 1)} for f in files]
    st = path.stat()
    return {"id": rel, "title": _title(path), "area": area, "verdict": verdict, "takeaway": takeaway,
            "updated": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            "lines": sum(1 for _ in path.open(encoding="utf-8", errors="replace")), "data_files": data}


@router.get("")
def list_research() -> dict[str, Any]:
    root = _root()
    return {"data": [_entry(root, rel) for rel in _discover(root)]}


@router.get("/doc")
def get_doc(id: str = Query(..., max_length=200)) -> dict[str, Any]:
    root = _root()
    path = _resolve(root, id)
    return {**_entry(root, id), "markdown": path.read_text(encoding="utf-8", errors="replace")}


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

# World-Class Program — charter (15 Oct 2026, 03:00 IST)

Owner's ask: two agent teams — **Team 1 builds** (one expert per feature, fixes known flaws, tests),
**Team 2 critiques** (does the terminal have everything a trader needs for the Indian market + MCX gold;
what is still missing; what is flawed). Bar: world-class, Bloomberg-like. Builds on the Bloomberg program
(reports/bloomberg_program/, closed 01:00 with critic verdict + remediations).

## Standing constraints (unchanged, non-negotiable)
- PAPER ONLY. No live orders anywhere; no MCX order placement (owner-gated). Trading rules frozen
  (shared/momentum.py, decision_desk.py, trading_costs.py; alpha_lab gates per Amendments v2 — additive
  lenses allowed, gating changes not).
- Python: /Users/sudheer/Desktop/jupyter_env/bin/python. No new pip installs into jupyter_env without
  checking it's shared. No commits. No Telegram sends by agents. Never print secrets.
- Restarts: PM only; data-service/master-controller never 07:45–09:20 or 18:30–21:15 IST.
- ICICI quota: read-only quote calls allowed sparingly; websocket preferred; no order APIs.
- Test gate: the five suites + tsc must be green at integration (baseline 781; each builder adds tests).

## Phase 0 — GAPS.md (PM, done first)
Trader-requirements matrix: NSE cash · NSE F&O · MCX gold · platform. Grades: HAVE / PARTIAL / MISSING-
BUILDABLE / MISSING-EXTERNAL (needs paid data, eligibility, or exchange agreements — listed honestly).

## Team 1 — builders (disjoint file ownership; PM applies all shared-file patch blocks)
| ID | Expert | Feature | Owns (new/exclusive) |
|----|--------|---------|----------------------|
| W1 | Frontend charting engineer | CHRT — interactive candlestick chart studio (D/W/M + intraday when available), indicators, ticker-linked | ui/components/ChartStudio.tsx, ui/lib/chartData.ts, services/ui-api/routers/charts.py |
| W2 | Derivatives quant | DERV — futures term structure, basis & rollover history, PCR/max-pain history, participant-OI context | services/ui-api/routers/derivatives.py, ui/components/DerivativesDesk.tsx |
| W3 | Options engineer | OSTR — strategy builder: payoffs, Greeks (B-76), breakevens, margin estimate, chain-fed | services/ui-api/routers/options_strategy.py, ui/components/StrategyBuilder.tsx |
| W4 | Commodities engineer | GOLD+ — MCX session awareness (09:00–23:30, MCX holiday calendar), gold contract specs/margins, live MCX quotes via Breeze if entitled (degrade honestly), COMEX/USDINR overlay, paper gold ticket | services/ui-api/routers/mcx.py, ui/components/McxGoldDesk.tsx (extends CMDT tab), scripts tests |
| W5 | Risk quant | RISK — portfolio VaR (hist-sim on the panel), beta/sector decomposition, stress replays (2020-03, 2024-06-04), drawdown ladder vs limits | services/ui-api/routers/riskdash.py, ui/components/RiskDashboard.tsx |
| W6 | Data engineer | TICKS — tick persistence to daily parquet + session VWAP endpoint (feeds W1 intraday), replay-safe | services/data-service/tick_store.py (+patch block for live_ticks.py hook), ui-api proxy in charts.py via W1 contract |
| W7 | Performance engineer | FLAWS — 60 s TTL cache for the 69.5 MB bulk-per-call routes; payload trims (fundamentals-screen, mtf-monitor, events, announcements); critic's LOW items (422 envelope, upstream URL leak, lw days<=0 message) | services/ui-api/routers/alpha.py, lw_scanner.py, bulk_cache.py (new), the 4 payload routes' routers |
| W8 | Validation quant + ops | A1 Monte-Carlo drawdown lens (alpha_lab/backtest/mc.py, additive, never gates) + A2 Friday decision journal (controller job + composer) | alpha_lab/backtest/mc.py, scripts/journal_composer.py, scripts/master_controller.py (sole owner tonight) |

Shared files (PM-only, builders hand patch blocks in their reports): ui/app/page.tsx (tab+GO registration),
ui/lib/api.ts, services/ui-api/main.py, services/data-service/main.py, services/data-service/live_ticks.py,
CLAUDE.md. Build reports: reports/worldclass_program/build_w<N>.md.

## Phase: integrate + test (PM)
Apply patch blocks → five suites + tsc → ui_audit (37+new pages) → restarts in safe window (<07:45 else
>09:20) → endpoint spot-checks → latency guard on new routes.

## Team 2 — critics (fresh agents, read-only + GET-only, after integration)
- C1 **Trader-completeness critic**: a desk trader's audit — NSE cash, F&O, MCX gold workflows end-to-end
  on the live terminal; scores each workflow; produces the still-missing list (buildable vs external).
- C2 **Engineering critic**: re-scores the 6-point Bloomberg bar + hunts defects in tonight's new code.
Verdicts: reports/worldclass_program/critique_trader.md, critique_engineering.md.

## Phase: REPORT
reports/worldclass_program/REPORT.md + artifact page + IMPROVEMENT_LOG + memory. Features missing
(external) stated plainly with what each would take.

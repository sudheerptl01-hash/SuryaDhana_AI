# Bloomberg-grade program — charter (14 Oct 2026, 22:05 IST)

Owner's order: an agent army that **analyzes → designs → builds → tests → adversarially critiques** whether this is
truly a production-grade Bloomberg terminal; plan first, execute phase by phase; the design must be highly
scalable and must retrofit the EXISTING flows, not only add new ones.

## The bar ("production-grade Bloomberg" means, for this program)
1. **Fast**: warm interactions feel instant; no endpoint a trader touches in-session over 500 ms warm; first
   paint of any tab under ~3 s cold.
2. **Live**: positions/watchlist tick from the broker feed when connected, with visible freshness and fallback.
3. **Never lies, never blanks**: one error contract end-to-end; stale data is labelled, not hidden.
4. **Survives**: a disk wipe, a process crash, a restart at any hour — documented, automated, tested.
5. **Scales in design**: single-operator Mac today, but every retrofit chooses the pattern that works at 100
   users (bounded caches, shared snapshots, push-not-poll, stateless handlers) — no dead-end hacks.
6. **Disciplined surface**: no dead routes, no duplicate conventions, docs match the territory, CI gates green.

## Phases and gates (sequential; parallelism inside each phase)
| Phase | Team | Output | Gate to proceed |
|---|---|---|---|
| 1 ANALYZE | 1 agent | `REQUIREMENTS.md` — F-/S-numbered requirements with acceptance criteria, from the six production-review reports + repo memories | PM review: complete, testable, in-scope |
| 2 DESIGN | 2 agents (systems, UI/UX) **+ 1 red-team critic** | `DESIGN_SYSTEMS.md`, `DESIGN_UIX.md`, `design_review.md` | every BLOCKER from the critic amended into the designs before any code |
| 3 BUILD | 5 agents, disjoint file ownership | code + unit tests per workstream, each reporting `build_<ws>.md` | all suites + tsc green per workstream |
| 4 TEST | 2 agents + PM-run restarts | `test_report.md`: full regression (37 pages, all suites), latency re-measure vs baseline CSV, small honest load test, live-data behaviour | zero regressions vs baseline; new features verified live |
| 5 CRITIQUE | 1 adversarial agent | `bloomberg_verdict.md` — scores the bar above 1–6, hunts for what still fails, checks nothing forbidden was touched | — (its verdict is reported as-is, including failure) |
| 6 REPORT | PM | final summary to the owner + IMPROVEMENT_LOG + memory | — |

## Workstreams (Phase 3 ownership map — no two agents share a file)
- **B1 Reliability/Ops**: `.env.example`, `docs/RUNBOOK_RESTORE.md`, nightly DuckDB backup job (master-controller
  + script), `.github/workflows/ci.yml`, dead-route removal (the 8 from contract_audit), parking the orphaned
  `pipeline.py` parquet routes.
- **B2 Backend scale**: `services/ui-api/cache.py` (bounded TTL, shared), news_scanner cache migration,
  `asyncio.to_thread` on the flagged DuckDB-in-async routes, shared evening snapshot (ReadSnapshot reuse by
  desk/news/shadow call-sites), error-contract module + adoption in the three shape families.
- **B3 Live data**: Breeze L1 websocket subscriber in data-service for book+watchlist symbols (≤50, quota-free),
  in-memory tick store, ui-api `GET /api/quotes/ticks` snapshot endpoint, frontend hook: WATCH/book switch to
  ticks when connected (freshness chip), Yahoo fallback unchanged.
- **B4 Frontend/design**: F-001 news-pill dock, F-002 kit-level `tabular-nums`, F-004 ALERT z-fix, #FFF→T.bright,
  DESK clip, GO recall/history, the 3-amber token unification, per-tab `dynamic()` imports, System page
  concurrent probes.
- **B5 Docs/architecture**: CLAUDE.md service-map + roadmap rewrite, root `README.md`, GETTING_STARTED fix,
  repo-root legacy sweep into `docs/legacy/` (move, never delete), `scripts/nse_panel_qa_old.py` → legacy.

## Standing constraints (every agent, every phase)
No git commits · no Telegram sends · no trading-rule changes (`shared/momentum.py`, `shared/decision_desk.py`,
`shared/trading_costs.py` semantics frozen; `alpha_lab/`, research `reports/*/REPORT|FINDINGS`, study scripts
frozen) · service restarts only by the PM, never 07:45–09:20 or 18:30–21:15 IST · ICICI quota respected: no
polling REST quote loops; live data = websocket only · every change lands with a test · failures reported plainly.

## Timeline intent
Tonight (22:00→): Phases 1–3. Overnight/early morning: Phase 4 (restarts ~06:30, before the 07:45 freeze).
Phase 5–6 after. If anything slips, the stack is left healthy and the report says exactly where it stopped.

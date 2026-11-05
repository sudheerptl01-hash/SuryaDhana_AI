# Build report — B5 Docs/architecture truth (14 Oct 2026, ~22:35 IST)

Scope: F5.1–F5.5 per REQUIREMENTS §B5 + DESIGN_UIX §9; amendments honoured (minor 12: plain `mv`, nothing
deleted; builder-owned scripts untouched). No commits, no restarts, no Telegram.

## F5.1 CLAUDE.md surgery — DONE (4 surgical edits, everything else intact)
| Section | Change |
|---|---|
| `## Project` header | 5 stale bullets (XGBoost→RL, ₹10K, 5-day) → current reality: paper-only Desk + S1 shadow, terminal, data, legacy note |
| `## Architecture` | 8-service table → **"what actually runs"** 4-process table + dormant-legacy paragraph (DESIGN §9.1 draft verbatim) |
| `## Running Services` | docker-first block → `start-local.sh` canonical verbs + UI_MODE=prod + **restart freeze windows**; docker kept as legacy line |
| new `## How to run things` | the five test suites with exact commands, tsc, ui_audit, PYTHONPATH conventions, **shadow status command** (devex findability miss), mypy |
| `## 16-Week Roadmap` | → `## Where the plan lives` pointers (PRODUCT_STRATEGY · IMPROVEMENT_LOG · RSCH · alpha_lab) |
AC: `grep "Phase 1"` roadmap row gone ✓ · `shadow` findable (5 hits) ✓ · table matches live :8001/:8008/:8010 ✓.
Kept byte-identical: Python Environment, Key Files, Data Sources, **Trading Rules**, Anti-Patterns, Development Workflow.

## F5.2 README.md — DONE (new, 38 lines)
What-this-is + paper-only banner · quick start (start/status/stop) · the three surfaces (terminal, Telegram bot incl.
`/shadow`, RSCH) · where-things-live (CLAUDE.md, GETTING_STARTED, **RUNBOOK_RESTORE** — B1's file, verified present ✓,
IMPROVEMENT_LOG, alpha_lab) · safety. Link check: all 8 referenced paths exist ✓.

## F5.3 GETTING_STARTED.md — REWRITTEN (was wrong top to bottom)
Fixed against the devex findings: start-local.sh runs the FULL stack (old text said "UI API + frontend only");
real `.env` key names (`ICICI_API_KEY/SECRET/SESSION_TOKEN/CLIENT_ID/PASSWORD/MOBILE`, `TELEGRAM_*` — old text
had `BREEZE_*` names that exist nowhere); session token is **daily** (old: "~30 days"); Chrome/Playwright and
Node 20+ prerequisites; 4.4 GB DB restore pointer; daily job rhythm; freeze windows; `ui/.next-prod` fact.
Removed: the live-trading enablement walkthrough (contradicted the paper-only posture) → replaced with the
owner-review rule. Removed the dead 11-service ✓-table and May-era tab guide.

## F5.4 Root sweep — DONE with proofs (73 → 25 root files)
Method: full-text scan of every live zone (services, ui/{app,components,lib,context}, scripts, shared, alpha_lab,
tests, infra, k8s, docs, .claude + core files; node_modules/.next*/legacy excluded) for each candidate name.
- **MOVED 50** (nothing deleted): 48 zero-reference root files → `docs/legacy/` (md/txt/py) and `docs/legacy/data/`
  (14 csv/json/log) + `scripts/nse_panel_qa_old.py` (0 refs, proven) + `SOTA_NESTED_HOLDOUT_VERDICT.md` (its one
  pinning link in docs/PROGRAMMATIC_DATA_ACCESS.md updated to the new path first).
- **KEPT 18 by live reference** (rule: any grep hit stays): the alpha-pipeline trio (`alpha_hypotheses.md`,
  `validated_alpha.md`, `novel_alpha_engine.py` — imported by services/ui-api/routers/alpha.py, run_alpha_pipeline.sh,
  compose, .claude agents) · sweep outputs their generator scripts still write/read at root (`sota_alpha_search_*`,
  `sota_nested_holdout_*`, `sota_phase1_orthogonality.json`, `suryadhana_wfo_results.json`, `wfo_rescore_results.json`,
  `decile_optimization_results.csv`, `direction_aware_results.csv`, `all_filters_backtest_results.csv`,
  `combinatorial_backtest_results.md`, `DECILE_OPTIMIZATION_REPORT.md`, `BILLIONAIRE_SCALE_AUDIT.md`) ·
  `QUICKSTART.md` (pinned by `.claude/COMPLETE_SUMMARY.md` — not my file to edit).
- `docs/legacy/README.md` manifest written (grouped, with supersession notes).
- Regression: core 271 ✓ · scripts 130 ✓ (nothing imported the moved files — proofs held).
**AC "≤15 root entries": NOT met — 25** (7 core/personal + 18 reference-pinned). The pins are real code paths;
un-pinning means editing the generator scripts/agents (follow-up, not tonight's mandate).

## F5.5 --help floor — 5/6 DONE, 1 handoff
| Script | Before | After |
|---|---|---|
| scripts/ui_audit.py | 0.06 s ✓ (already good) | — |
| scripts/nifty500_pipeline.py | 0.02 s ✓ | — |
| scripts/evidence_probability_study.py | 0.81 s ✓ | — |
| scripts/daily_session_refresh.py (B-owned, measured only) | 0.14 s ✓ | — |
| **alpha_lab/run_today.py** | **22.8 s and it EXECUTED the flow** (no argparse; rewrote today_book.md — idempotent, no harm) | argparse added before heavy imports, `__main__`-guarded (no parse on import) → **0.02 s**; plain-run behaviour unchanged; 12 alpha_lab tests ✓; zero importers (verified) |
| **scripts/master_controller.py** | `--help` **hangs** (no argparse; module import starts work; stray killed) | **NOT-DONE — handoff to B1** (file owner tonight). Suggested one-liner at top of `__main__` path: argparse with description before the uvicorn run |

## NOT-DONE / handoffs (honest list)
1. master_controller.py --help → B1 (above).
2. Root ≤15: blocked by 18 live pins; follow-up proposal: repoint the 6 generator scripts' output paths +
   .claude references, then sweep the remainder.
3. `.claude/COMPLETE_SUMMARY.md` (stale meta referencing QUICKSTART) — outside my file list.
4. Observed mid-build (not mine): B2's shared-snapshot hook landed in `alpha_lab/backtest/data_access.py`
   per the PLAN amendment; my GETTING_STARTED "daily rhythm" already matches it.

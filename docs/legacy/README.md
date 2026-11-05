# docs/legacy — superseded root files (moved 14 Oct 2026, Bloomberg-program B5)

Nothing here is deleted history: these are working-tree MOVES of root-level files that a reference scan
(services, ui, scripts, shared, alpha_lab, tests, docs, infra, .claude + core files) proved unreferenced.
Files still referenced by live code stayed at the repo root (manifest + proofs:
reports/bloomberg_program/build_b5.md).

- **BACKTEST_*.md (7)** — Backtest-lab guides/verifications, May–Jun 2026 sprint; superseded by the terminal's Backtest tab docs + docs/BACKTEST_LAB_REFERENCE.md
- **SOTA_*_VERDICT.md / SOTA_*_{SUMMARY,REPORT}.md** — SOTA combinatorial/horizon/inversion/regime sweeps (Jun 2026): every construction lever dead OOS; superseded by alpha_lab (Oct 2026)
- **sota_*_{results,run,stdout}.{csv,json,log} → data/** — raw outputs of those sweeps (their *_search.py runners for the four moved ones were root strays; generator scripts for the kept ones remain in scripts/)
- **sota_*_search.py (4)** — root-stray sweep runners whose outputs were re-pointed nowhere live
- **TRADE_EXPLORER_*.md (3), DASHBOARD_*.md (2)** — May 2026 UI-era feature docs; superseded by docs/IMPROVEMENT_LOG.md terminal sprint
- **PHASE_5_COMPLETION.md, RL_TRAINING_IMPLEMENTATION.md, TIER_1_IMPLEMENTATION.md, NSE_UNIVERSE_SETUP_COMPLETE.md, DEPLOYMENT_SUMMARY.txt, OOS_ALPHA_DISCOVERY_REPORT.md, BACKTEST_AND_UI_FIXES.md, api_architecture_map.md** — milestone/delivery notes from the dormant 8-service era; architecture truth now lives in CLAUDE.md + reports/production_review/architecture_reality.md
- **ONBOARDING.md, project.md, 2026-06-05-*_trading_strategyMaster.txt** — early onboarding/strategy drafts; superseded by README.md + GETTING_STARTED.md + docs/PRODUCT_STRATEGY.md
- **all_filters/direction_aware/decile CSVs that were unreferenced, wfo_rescore partner files** — sweep outputs with no live reader
- **nse_panel_qa_old.py** — superseded panel-QA script (see reports/data_quality/ for the current QA); 0 references proven before the move

Raw data files live under `docs/legacy/data/`.

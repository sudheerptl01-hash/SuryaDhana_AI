"""P5 hygiene stream of the SuryaDhana improvement phase (ml/IMPROVEMENT_PLAN.md, section 2-P5).

Every input is a frozen v1 artefact on disk, read-only; nse_market.duckdb is never opened.

Modules
-------
common      paths, seed, logging, JSON writer, Newey-West t, circular block bootstrap
pbo         probability of backtest overfitting by CSCV (Bailey, Borwein, Lopez de Prado & Zhu 2017),
            generic T x M implementation + the three pre-registered applications -> pbo.json
delivery    durability of the delivery signal (raw and residual rank IC by year, liquidity,
            market direction, pre/post March 2026) -> delivery_durability.json
uniqueness  average label uniqueness (Lopez de Prado) for the 2025-01 fold's training window
            -> uniqueness.json
report      HYGIENE.md, quoting the three JSON files

Run (from the repo root, 2 threads, seed 108):
    PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 python3 -m ml.hygiene.pbo
    PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 python3 -m ml.hygiene.delivery
    PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 python3 -m ml.hygiene.uniqueness
    PYTHONDONTWRITEBYTECODE=1 python3 -m ml.hygiene.report
"""

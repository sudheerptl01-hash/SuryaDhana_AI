"""Pre-registered Terminal v2 studies (builder B8; Terminal v2 PLAN §1 B8 and Wave 3.3's precondition).

Each study has a `PLAN.md` under `reports/terminal_v2/studies/<dir>/` written before any result was looked at (registry:
`reports/terminal_v2/STUDIES.md`), a runnable script here that reads only stored data (a DuckDB holding the production
tables, opened read-only, plus the study-only inputs `build_inputs.py` recomputes from the cached NSE files), and
`FINDINGS.md` rows once it has run. No network access anywhere in this package; nothing here writes under `data/`.

Studies: TV-IVRV (`tv_ivrv.py`: IV − RV spread and IV percentile vs next-20-session realised vol and return), TV-DRIVERS
(`tv_drivers.py`: NIFTY driver persistence and driver changes), TV-GEX (`tv_gex.py`: a dealer-gamma proxy vs the
next-day range). Shared machinery: `common.py` (statistics, the signed verdict rule, costs, honest exits).
"""

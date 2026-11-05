# GOLD program — study registry (the one list of study ids)

One row per study id. **This file is the source of truth for ids**: PLAN.md §i O-13, SOURCES.md §"proposed studies" /
M44–M45, `docs/GOLD_DATA_DICTIONARY.md` (generated from SOURCES.md), `services/ui-api/routers/gold.py` evidence strings,
`ui/components/gold/*.tsx` `evidence=` props, G-EDU and the aggregate `reports/gold_program/FINDINGS.md` must use the ids
below. Maintained by B7 (studies); an id is never reused once a plan or a FINDINGS row carries it.

**Why this file exists (4 Nov 2026).** Wave 1 shipped two different studies under `GS-P4`: PLAN.md O-13 / SOURCES.md
called the IMF monthly central-bank-buying study GS-P4, while the B7 brief, the script `gs_p4_seasonality_in_inr.py`,
its pre-registered plan and the FINDINGS rows the PM already merged mean "seasonality in rupees". Resolution: **GS-P4 stays
seasonality in rupees** (the plan, script, results and FINDINGS rows exist); the central-bank-buying study gets the fresh
id **GS-P5** (nothing of it exists yet). Patch requests in wave 1b rename the five references.

## Verdict vocabulary

PASS · CONTEXT-ONLY · FAIL · VOID (a pre-registered statistic voided by its own control; badge = FAIL) · PENDING
(pre-registered, data not stored). Rules: PLAN f.1; `scripts/gold_studies/FINDINGS_ROW_TEMPLATE.md`;
`common.verdict` (a statistic, sign-free) and `common.verdict_traded` (a traded rule, signed: it must pay).

## Registry

| Id | Hypothesis (one line) | Data | Status (4 Nov 2026) | Verdict | Plan / script | FINDINGS |
|---|---|---|---|---|---|---|
| G-STUDY | Does weekly COT positioning (managed-money net and friends) forecast gold 1 / 4 / 13 weeks ahead? | CFTC Socrata disagg + legacy 2006→, GC=F | run (wave 0, 26 Oct 2026); re-run by T4 | FAIL as a forecast; PASS as a same-week description (Spearman 0.65) | `reports/gold_program/G-STUDY/` (`g_study.py`) | `reports/gold_program/G-STUDY/FINDINGS.md`; aggregate rows in `FINDINGS.md` |
| G-MACRO | H1 real yield, H2 the dollar, H3 month-of-year (USD), H4 GPR, H5 fair value | FRED, Yahoo, World Bank 1971→ | run (wave 0) | H1/H2 CONTEXT (explainers, no lead); H3 CONTEXT-ONLY; H4 FAIL; H5 DO-NOT-PUBLISH | `reports/gold_program/G-MACRO/` (`g_study.py`) | `reports/gold_program/G-MACRO/FINDINGS.md`; aggregate rows |
| G-INDIA-1 | Do AMFI monthly gold-ETF flows time rupee gold? | AMFI monthly, 79 months | run (wave 0) | FAIL as timing (ρ +0.12, p 0.31) | `reports/gold_program/G-INDIA/` | aggregate row |
| G-STUDY-2 | Does the DAILY OI × price quadrant (COMEX GC product OI) forecast 1 / 5 / 20 sessions; does the folklore rule pay? | `gold_cme_daily_voi` 2014→ (needs O-6 + the CME FTP backfill), `gold_daily_bars` | **PENDING** — pre-registered 26 Oct, amended A1–A4; script exits 3 | — | `reports/gold_program/G-STUDY-2/PLAN.md` · `scripts/gold_studies/g_study_2_oi_quadrant.py` | PENDING row (template) |
| GS-P1 | Do daily GLD tonnes (1 / 5 / 20-day Δ) forecast COMEX gold 5 / 20 sessions ahead? | SPDR archive 2004-11→ (5,515 trust dates), GC=F | run 26 Oct 2026, re-run 4 Nov (identical) | **CONTEXT-ONLY**: FAIL as a forecast (6/6), PASS as description (same-week 0.29) | `reports/gold_program/GS-P1/PLAN.md` · `scripts/gold_studies/gs_p1_gld_tonnes.py` | `reports/gold_program/GS-P1/FINDINGS.md`, `FINDINGS_ROW.md` |
| GS-P2 | Do WGC weekly ETF flows by region (global / NA / EU / Asia) forecast 1 / 4 (13) weeks ahead? | `gold_series` WGC_ETF_HOLD_T_* 2003→ (needs O-1 + the `gold_weekly` backfill), point-in-time per decision | **PENDING** — pre-registered 26 Oct, amended A1–A4; script exits 3; fixture = replay check only | — | `reports/gold_program/GS-P2/PLAN.md` · `scripts/gold_studies/gs_p2_wgc_flows.py` | PENDING row (template) |
| GS-P3 | SGE premium and Au(T+D) OI as a forecast (after ≥ 2 years of stored history) | `gold_asia_daily` (SGE / SHFE), starts the day the jobs start | not pre-registered yet — waits for history | — | — | — |
| GS-P4 | Month-of-year seasonality of gold **in rupees** (festival months, Akshaya Tritiya, Dec/Jan; walk-forward best-6-months after 0.15 %/switch) | World Bank × DEXINUS 1973→ (644 months), GC=F × USD/INR month-ends 2000→, GOLDBEES | run 26 Oct 2026, re-run 4 Nov (identical) | **VOID (pre-registered statistic) / FAIL (post-hoc drift-adjusted, capped)** — drift, not a calendar | `reports/gold_program/GS-P4/PLAN.md` · `scripts/gold_studies/gs_p4_seasonality_in_inr.py` | `reports/gold_program/GS-P4/FINDINGS.md`, `FINDINGS_ROW.md` |
| GS-P5 | IMF monthly central-bank net buying → next-month gold return (formerly listed as "GS-P4" in PLAN.md O-13 / SOURCES.md M45) | IMF IFS / IRFCL monthly (E12; one country × three months on disk today) | not pre-registered yet — waits for the `gold_morning` monthly ingest and its own PLAN.md | — (honest prior: FAIL as timing) | — | `ph.official` keeps `context`, evidence "GS-P5 pending" |
| GS-PREMIUM | India dealer premium / Shanghai premium as a forecast (after ≥ 2 years of stored IBJA / SGE history) | `gold_asia_daily`, IBJA ladder | not pre-registered yet — waits for history | — | — | — |
| G-INDIA-OI | MCX GOLD / GOLDM OI matrix (after 60 stored sessions; owner decision O-8 on the source) | `gold_mcx_category_oi`, Breeze daily | not pre-registered yet — waits for history and O-8 | — | — | — |

## Where each id is referenced today (checked 4 Nov 2026)

- `GS-P4` = seasonality: this registry, `GS-P4/PLAN.md`, `scripts/gold_studies/gs_p4_seasonality_in_inr.py`,
  `tests/test_gold_study_reproduce.py`, PLAN.md §0.2 ownership row, aggregate `FINDINGS.md` rows 32–36 and the prose at
  line 62 (all correct).
- `GS-P4` = central-bank buying (to be renamed **GS-P5** by patch request): PLAN.md:513 (O-13), SOURCES.md:506 / 845 / 884
  (→ `docs/GOLD_DATA_DICTIONARY.md` regenerates), `services/ui-api/routers/gold.py` (`"central banks: GS-P4 pending"`),
  `ui/components/gold/PhysicalView.tsx` (`evidence="GS-P4 pending"`), `reports/gold_program/G-EDU/parts/04_panels_routines_appendix.md`
  §8.2.9 (→ `CURRICULUM.md` regenerates). `reports/gold_program/G-PHYSICAL/REPORT.md` (lines 265, 606) is a dated wave-0
  research report and keeps its historical wording.

## Running a pending study when its data exists

Outside the IST busy windows (Mon–Fri 07:45–15:45 and 18:30–21:15 the scripts refuse to copy the live file: exit 5
`live file busy`; `--allow-market-hours` overrides):

```bash
P=/Users/sudheer/Desktop/jupyter_env/bin/python
PYTHONWARNINGS=ignore $P scripts/gold_studies/g_study_2_oi_quadrant.py --db data/market.duckdb   # ≥ 500 sessions of gold_cme_daily_voi
PYTHONWARNINGS=ignore $P scripts/gold_studies/gs_p2_wgc_flows.py --db data/market.duckdb         # gold_series WGC_ETF_HOLD_T_*
```

Each copies the DuckDB file (+ WAL) to a temp directory, opens the copy read-only, removes it when done (`--tmp-dir` to
place it), and writes `REPORT.md` / `FINDINGS.md` / `FINDINGS_ROW.md` under its study directory; paste `FINDINGS_ROW.md`
(4-column) into `reports/gold_program/FINDINGS.md` in place of the PENDING row and add the study's row here.

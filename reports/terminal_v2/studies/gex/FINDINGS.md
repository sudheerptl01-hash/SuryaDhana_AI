# TV-GEX · FINDINGS (GEX-style proxy → next-day range)

**PROVISIONAL** — computed on inputs recomputed from the cached NSE files in a scratch store (PLAN §0.3: a past vintage is recomputed from the files), not on the stored, backfilled tables. No study result reaches a badge without the PM.

Run 2026-11-05T08:20:27+05:30 on `~/.suryadhana_pm_scratch/v2/B8-STUDIES/inputs.duckdb`. Plan: `reports/terminal_v2/studies/gex/PLAN.md` (pre-registered before any result; Terminal v2 PLAN Wave 3.3's precondition).

| Signal | Result (full sample) | Both halves |
|---|---|---|
| X1 · NGS (C1 vendor convention: dealers long calls, short puts) → next-day range, sign − | b −0.150 (t −0.30, n 1740); leg cond − all 0.0035 %F (t 0.25); cond after costs 0.0021 %F (t 0.15; halves 0.72 / −0.53) → **FAIL** | b −0.759 (t −0.93) / b 0.641 (t 1.17) |
| X2 · TGL (C2 'writers are short': short-gamma load) → next-day range, sign + | b −0.114 (t −3.20, n 1507); leg cond − all −0.0038 %F (t −0.24); cond after costs −0.0084 %F (t −0.53; halves −0.57 / −0.24); strong AGAINST the registered sign in the full sample and both halves (a description, never a signal: the opposite claim was not pre-registered) → **FAIL** | b −0.148 (t −2.58) / b −0.182 (t −4.46) |

- **Badge consequence:** X1: stays heuristic; X2: stays heuristic. The proxy can never be `signal` while the dealers' sign is an assumption. No study result reaches a badge without the PM.

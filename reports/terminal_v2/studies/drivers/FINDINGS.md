# TV-DRIVERS · FINDINGS (NIFTY drivers: persistence and changes)

**PROVISIONAL** — computed on inputs recomputed from the cached NSE files in a scratch store (PLAN §0.3: a past vintage is recomputed from the files), not on the stored, backfilled tables. No study result reaches a badge without the PM.

Run 2026-11-05T08:20:28+05:30 on `~/.suryadhana_pm_scratch/v2/B8-STUDIES/inputs.duckdb`. Plan: `reports/terminal_v2/studies/drivers/PLAN.md` (pre-registered before any result).

| Signal | Result (full sample) | Both halves |
|---|---|---|
| D1 · 20-session leader's share of the next 20 sessions minus the weight leader's (sign +) | mean −0.022 (t −3.23, n 583); \|t\| ≥ 2 against the registered sign in the full sample only; H1 empty: the pre-registered split (2023-04-30) falls outside the gated sample, so the both-halves condition cannot be met until the point-in-time share-count history reaches back → **FAIL** | — (no observation) / mean −0.022 (t −3.23) |
| D2 · the driver keeps driving: s·(R_leader − R_NIFTY), close T+1 → T+21 (sign +) | mean −0.123 (t −0.26, n 583); TL-D2 long-only cash after 0.93 % RT: −0.977 % per tranche (t −1.45; halves — / −1.45); H1 empty: the pre-registered split (2023-04-30) falls outside the gated sample, so the both-halves condition cannot be met until the point-in-time share-count history reaches back → **FAIL** | — (no observation) / mean −0.123 (t −0.26) |
| D3r · after a leader change: NIFTY next-20 return minus its mean (two-sided) | mean 0.403 (t 0.41, n 15); 15 thinned events < 20 → **PENDING** | — (no observation) / mean 0.403 (t 0.41) |
| D3v · after a leader change: RV change (RVF − rv20) minus its mean (sign +) | mean 1.879 (t 1.05, n 15); 15 thinned events < 20 → **PENDING** | — (no observation) / mean 1.879 (t 1.05) |

- **Badge consequence:** the regime strip keeps `context` and its sentence keeps "describes, does not predict"; nothing from this study enters momentum.py, decision_desk.py, an alert or the ticket. No study result reaches a badge without the PM.

# TV-IVRV · FINDINGS (IV − RV spread, IV percentile → next-20-session vol / return)

**PROVISIONAL** — computed on inputs recomputed from the cached NSE files in a scratch store (PLAN §0.3: a past vintage is recomputed from the files), not on the stored, backfilled tables. No study result reaches a badge without the PM.

Run 2026-11-05T08:20:03+05:30 on `~/.suryadhana_pm_scratch/v2/B8-STUDIES/inputs.duckdb`. Plan: `reports/terminal_v2/studies/iv_rv/PLAN.md` (pre-registered before any result). Verdict counts over the 12 graded entries: FAIL 8, CONTEXT-ONLY 4.

| Signal | Result (full sample) | Both halves |
|---|---|---|
| NIFTY · S1 IV − RV spread (iv30_cm − rv20_cc) → seller's edge iv30_cm − RVF (sign +) | b 0.047 (t 0.37, n 1487); TL1 cond − all 0.482 %F (t 1.66); cond after costs 0.730 %F (t 2.51; halves 0.01 / 4.89) → **FAIL** | b 0.412 (t 3.18) / b −0.221 (t −1.87) |
| NIFTY · S1 IV − RV spread (iv30_cm − rv20_cc) → RVF given rv20 (information, sign +) | b 0.707 (t 4.72, n 1487); no traded leg (ceiling CONTEXT-ONLY) → **CONTEXT-ONLY** | b 0.343 (t 2.28) / b 1.005 (t 4.72) |
| NIFTY · S1 IV − RV spread (iv30_cm − rv20_cc) → next-20-session return (buy fear, sign +) | b 0.124 (t 1.39, n 1487); TL2 excess −0.88 %/yr after 0.93 % RT (t −0.70; halves −0.28 / −0.69) → **FAIL** | b 0.228 (t 2.08) / b 0.036 (t 0.34) |
| NIFTY · S2 IV percentile (iv_pctile_252) → seller's edge iv30_cm − RVF (sign +) | b 0.009 (t 0.81, n 1487); TL1 cond − all 0.502 %F (t 2.45); cond after costs 0.750 %F (t 3.65; halves 0.18 / 5.58) → **FAIL** | b 0.026 (t 1.37) / b 0.011 (t 0.69) |
| NIFTY · S2 IV percentile (iv_pctile_252) → RVF given rv20 (information, sign +) | b 0.056 (t 2.96, n 1487); no traded leg (ceiling CONTEXT-ONLY) → **CONTEXT-ONLY** | b 0.056 (t 2.20) / b 0.083 (t 3.18) |
| NIFTY · S2 IV percentile (iv_pctile_252) → next-20-session return (buy fear, sign +) | b 0.006 (t 0.72, n 1487); TL2 excess 1.20 %/yr after 0.93 % RT (t 0.54; halves −0.49 / 1.32) → **FAIL** | b 0.002 (t 0.13) / b 0.020 (t 1.64) |
| BANKNIFTY · S1 IV − RV spread (iv30_cm − rv20_cc) → seller's edge iv30_cm − RVF (sign +) | b 0.025 (t 0.27, n 1459); TL1 cond − all −0.264 %F (t −0.55); cond after costs −0.177 %F (t −0.37; halves −0.76 / 0.03) → **FAIL** | b 0.187 (t 1.63) / b −0.166 (t −1.55) |
| BANKNIFTY · S1 IV − RV spread (iv30_cm − rv20_cc) → RVF given rv20 (information, sign +) | b 0.787 (t 6.63, n 1459); no traded leg (ceiling CONTEXT-ONLY) → **CONTEXT-ONLY** | b 0.631 (t 4.40) / b 1.183 (t 3.99) |
| BANKNIFTY · S1 IV − RV spread (iv30_cm − rv20_cc) → next-20-session return (buy fear, sign +) | b 0.176 (t 2.16, n 1459); TL2 excess −0.37 %/yr after 0.93 % RT (t −0.21; halves −0.45 / 0.19) → **CONTEXT-ONLY** | b 0.216 (t 1.43) / b 0.127 (t 1.78) |
| BANKNIFTY · S2 IV percentile (iv_pctile_252) → seller's edge iv30_cm − RVF (sign +) | b 0.011 (t 0.58, n 1459); TL1 cond − all 0.657 %F (t 2.18); cond after costs 0.744 %F (t 2.47; halves −0.28 / 3.76) → **FAIL** | b 0.059 (t 3.24) / b 0.001 (t 0.06) |
| BANKNIFTY · S2 IV percentile (iv_pctile_252) → RVF given rv20 (information, sign +) | b 0.040 (t 1.54, n 1459); no traded leg (ceiling CONTEXT-ONLY) → **FAIL** | b 0.047 (t 1.56) / b 0.116 (t 2.82) |
| BANKNIFTY · S2 IV percentile (iv_pctile_252) → next-20-session return (buy fear, sign +) | b 0.016 (t 1.45, n 1459); TL2 excess 0.94 %/yr after 0.93 % RT (t 0.33; halves −0.09 / 0.52) → **FAIL** | b 0.041 (t 1.53) / b 0.010 (t 0.69) |

- **Badge consequence:** anything but PASS leaves the panels as they are (`arithmetic` for IV / rank / percentile, `context` for the spread). No study result reaches a badge without the PM.
- Every sentence on a panel still ends "describes, does not predict".

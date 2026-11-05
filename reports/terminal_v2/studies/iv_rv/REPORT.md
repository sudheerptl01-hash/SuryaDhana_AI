# TV-IVRV · IV − RV spread and IV percentile vs next-20-session vol and return — report

**PROVISIONAL** — computed on inputs recomputed from the cached NSE files in a scratch store (PLAN §0.3: a past vintage is recomputed from the files), not on the stored, backfilled tables. No study result reaches a badge without the PM.

Run 2026-11-05T08:20:03+05:30 · inputs `~/.suryadhana_pm_scratch/v2/B8-STUDIES/inputs.duckdb` · plan `reports/terminal_v2/studies/iv_rv/PLAN.md` (pre-registered 5 Nov 2026 07:57 IST, before any result).

## Data-quality gates

- **NIFTY**: graded sessions 1487 (2020-10-06 → 2026-10-05); TL1 tranches 1345; gates {"iv_rows": 1760, "iv_rows_off_calendar": 0, "gate_iv30_vs_prototype": {"n": 578, "median_abs_diff": 0.0027, "pass": true}, "gate_rv20_stored_vs_recomputed": {"n": 0, "note": "no stored rv20_cc (index_ohlc_daily not backfilled): recomputed", "pass": true}, "no_cm30_rows": 0}
- **BANKNIFTY**: graded sessions 1459 (2020-10-08 → 2026-10-05); TL1 tranches 1047; gates {"iv_rows": 1760, "iv_rows_off_calendar": 0, "gate_rv20_stored_vs_recomputed": {"n": 0, "note": "no stored rv20_cc (index_ohlc_daily not backfilled): recomputed", "pass": true}, "no_cm30_rows": 45}

## Graded statistics (signed; t is Newey-West; halves split 30 Sep 2023)

| Underlying · signal → statistic | b full (t) | H1 b (t) | H2 b (t) | traded leg | verdict | notes |
|---|---|---|---|---|---|---|
| NIFTY · S1 → G1 | 0.0465 (0.37) | 0.4117 (3.18) | −0.2208 (−1.87) | TL1 cond − all 0.482 %F (t 1.66); cond after costs 0.730 %F (t 2.51; halves 0.01 / 4.89) | **FAIL** |  |
| NIFTY · S1 → G2 | 0.7069 (4.72) | 0.3435 (2.28) | 1.0053 (4.72) | no traded leg (ceiling CONTEXT-ONLY) | **CONTEXT-ONLY** |  |
| NIFTY · S1 → G3 | 0.1242 (1.39) | 0.2279 (2.08) | 0.0360 (0.34) | TL2 excess −0.88 %/yr after 0.93 % RT (t −0.70; halves −0.28 / −0.69) | **FAIL** |  |
| NIFTY · S2 → G1 | 0.0094 (0.81) | 0.0258 (1.37) | 0.0110 (0.69) | TL1 cond − all 0.502 %F (t 2.45); cond after costs 0.750 %F (t 3.65; halves 0.18 / 5.58) | **FAIL** |  |
| NIFTY · S2 → G2 | 0.0563 (2.96) | 0.0562 (2.20) | 0.0830 (3.18) | no traded leg (ceiling CONTEXT-ONLY) | **CONTEXT-ONLY** |  |
| NIFTY · S2 → G3 | 0.0064 (0.72) | 0.0022 (0.13) | 0.0195 (1.64) | TL2 excess 1.20 %/yr after 0.93 % RT (t 0.54; halves −0.49 / 1.32) | **FAIL** |  |
| BANKNIFTY · S1 → G1 | 0.0248 (0.27) | 0.1868 (1.63) | −0.1658 (−1.55) | TL1 cond − all −0.264 %F (t −0.55); cond after costs −0.177 %F (t −0.37; halves −0.76 / 0.03) | **FAIL** |  |
| BANKNIFTY · S1 → G2 | 0.7872 (6.63) | 0.6306 (4.40) | 1.1827 (3.99) | no traded leg (ceiling CONTEXT-ONLY) | **CONTEXT-ONLY** |  |
| BANKNIFTY · S1 → G3 | 0.1758 (2.16) | 0.2161 (1.43) | 0.1274 (1.78) | TL2 excess −0.37 %/yr after 0.93 % RT (t −0.21; halves −0.45 / 0.19) | **CONTEXT-ONLY** |  |
| BANKNIFTY · S2 → G1 | 0.0108 (0.58) | 0.0590 (3.24) | 0.0014 (0.06) | TL1 cond − all 0.657 %F (t 2.18); cond after costs 0.744 %F (t 2.47; halves −0.28 / 3.76) | **FAIL** |  |
| BANKNIFTY · S2 → G2 | 0.0404 (1.54) | 0.0466 (1.56) | 0.1157 (2.82) | no traded leg (ceiling CONTEXT-ONLY) | **FAIL** |  |
| BANKNIFTY · S2 → G3 | 0.0158 (1.45) | 0.0405 (1.53) | 0.0101 (0.69) | TL2 excess 0.94 %/yr after 0.93 % RT (t 0.33; halves −0.09 / 0.52) | **FAIL** |  |

## Negative controls (t full / H1 / H2; a control meeting the statistic's condition voids it)

| Underlying · signal | control | G1 | G2 | G3 |
|---|---|---|---|---|
| NIFTY · S1 | N1_lag250 | −0.73 / 0.56 / −2.08 | 0.91 / −0.05 / 1.83 | 1.36 / 0.63 / 1.83 |
| NIFTY · S1 | N2_circular_shift | 0.48 / 0.27 / 1.22 | −1.10 / −0.29 / −2.24 | 1.33 / 1.65 / 0.61 |
| NIFTY · S1 | N3_permutation | 0.56 / 1.50 / −1.14 | 0.92 / 0.77 / 0.39 | 0.84 / 0.56 / 0.48 |
| NIFTY · S1 | N4_option_free (cap) | −0.02 / 0.40 / −0.33 | 0.81 / 0.83 / −0.46 | −0.83 / −0.23 / −0.96 |
| NIFTY · S2 | N1_lag250 | 0.01 / −1.06 / 0.49 | −0.93 / −0.45 / −0.24 | −1.09 / −0.10 / −1.37 |
| NIFTY · S2 | N2_circular_shift | 0.22 / −1.26 / 0.72 | 0.38 / 0.80 / −0.72 | 0.73 / −0.64 / 1.57 |
| NIFTY · S2 | N3_permutation | 0.96 / 1.38 / −0.02 | −1.50 / −1.20 / −1.03 | −1.75 / −0.55 / −1.94 |
| BANKNIFTY · S1 | N1_lag250 | −0.42 / 1.29 / −2.21 | 0.27 / −0.78 / 1.85 | 0.48 / −0.07 / 1.21 |
| BANKNIFTY · S1 | N2_circular_shift | 0.69 / 1.64 / −0.00 | −0.82 / −0.37 / −0.64 | −0.62 / 0.48 / −1.11 |
| BANKNIFTY · S1 | N3_permutation | −1.02 / −0.40 / −1.51 | 1.78 / 0.55 / 1.32 | −0.85 / −0.92 / −0.43 |
| BANKNIFTY · S1 | N4_option_free (cap) | 0.73 / −0.13 / 0.89 | 1.56 / 2.06 / −0.85 | 0.33 / 0.11 / 0.35 |
| BANKNIFTY · S2 | N1_lag250 | 0.45 / −0.56 / 0.84 | −1.35 / −0.99 / −0.92 | −0.81 / −1.09 / −0.09 |
| BANKNIFTY · S2 | N2_circular_shift | 1.06 / −0.55 / 1.31 | 0.24 / 0.19 / −0.98 | −0.67 / −1.63 / 1.03 |
| BANKNIFTY · S2 | N3_permutation | 1.28 / 0.40 / 1.03 | −0.56 / 0.11 / −1.14 | 0.99 / 0.73 / 0.50 |

## Traded legs

Cash cost (TL2): 0.931 % per round trip (`shared/trading_costs.py` default model, ₹1,00,000 tranche); option schedule (TL1): `FnoCosts` {"as_of": "2026-11 (B8 reading; verify against a contract note)", "stt_sell_pct": 0.15, "stt_exercise_pct": 0.15, "exchange_pct": 0.03503, "sebi_pct": 0.0001, "stamp_buy_pct": 0.003, "gst_pct": 18.0, "brokerage_pct": 0.1, "half_spread_pct": 0.5, "floor_pct": 0.15}.

| Underlying · signal | TL1 n (cond) | uncond seller %F (t) | cond − all %F (t; H1 / H2) | cond after costs %F (t; H1 / H2) | TL2 excess %/yr (t; H1 / H2) | TL2 at 0.15 % floor (t) |
|---|---|---|---|---|---|---|
| NIFTY · S1 | 1176 (291) | 0.248 (1.25) | 0.482 (1.66; −0.18 / 3.42) | 0.730 (2.51; 0.01 / 4.89) | −0.88 (−0.70; −0.28 / −0.69) | 1.15 (0.88) |
| NIFTY · S2 | 1176 (502) | 0.248 (1.25) | 0.502 (2.45; −0.09 / 3.80) | 0.750 (3.65; 0.18 / 5.58) | 1.20 (0.54; −0.49 / 1.32) | 2.50 (1.13) |
| BANKNIFTY · S1 | 894 (215) | 0.087 (0.32) | −0.264 (−0.55; −0.78 / −0.17) | −0.177 (−0.37; −0.76 / 0.03) | −0.37 (−0.21; −0.45 / 0.19) | 1.68 (0.91) |
| BANKNIFTY · S2 | 894 (407) | 0.087 (0.32) | 0.657 (2.18; −0.30 / 3.32) | 0.744 (2.47; −0.28 / 3.76) | 0.94 (0.33; −0.09 / 0.52) | 2.29 (0.80) |

## Robustness (not graded): S3 = IV rank

| Underlying | G1 b (t) | G2 b (t) | G3 b (t) |
|---|---|---|---|
| NIFTY | 0.0141 (0.64) | 0.0754 (2.29) | 0.0147 (1.02) |
| BANKNIFTY | −0.0150 (−0.39) | 0.1065 (2.22) | 0.0321 (1.87) |

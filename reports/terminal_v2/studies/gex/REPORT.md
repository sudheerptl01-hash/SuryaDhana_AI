# TV-GEX · dealer-gamma proxy vs NIFTY's next-day range — report

**PROVISIONAL** — computed on inputs recomputed from the cached NSE files in a scratch store (PLAN §0.3: a past vintage is recomputed from the files), not on the stored, backfilled tables. No study result reaches a badge without the PM.

Run 2026-11-05T08:20:27+05:30 · inputs `~/.suryadhana_pm_scratch/v2/B8-STUDIES/inputs.duckdb` · plan `reports/terminal_v2/studies/gex/PLAN.md` (pre-registered 5 Nov 2026 08:00 IST, before any result).

Sessions 1760 (2019-10-01 → 2026-11-04); graded X1 1740, X2 1507; one-session straddle tranches 1755 (exit priced from the settle price: 0.0 %); days with a skipped expiry (< 4 IV strikes): 9; index OHLC rows stored: 0 (the range is the most-traded NIFTY future's high / low).

## Graded regressions (Y = 100 ln(H/L) of T+1; controls Ȳ5, Ȳ20, iv30_cm, expiry-day dummy; Newey-West 5 lags; halves split 31 Mar 2023)

| Proxy | b full (t) | H1 b (t) | H2 b (t) | R² | traded leg | verdict | notes |
|---|---|---|---|---|---|---|---|
| X1 NGS (C1 vendor convention: dealers long calls, short puts) → next-day range, sign − | −0.1502 (−0.30) | −0.7587 (−0.93) | 0.6411 (1.17) | 0.481 | leg cond − all 0.0035 %F (t 0.25); cond after costs 0.0021 %F (t 0.15; halves 0.72 / −0.53) | **FAIL** |  |
| X2 TGL (C2 'writers are short': short-gamma load) → next-day range, sign + | −0.1141 (−3.20) | −0.1485 (−2.58) | −0.1816 (−4.46) | 0.235 | leg cond − all −0.0038 %F (t −0.24); cond after costs −0.0084 %F (t −0.53; halves −0.57 / −0.24) | **FAIL** | strong AGAINST the registered sign in the full sample and both halves (a description, never a signal: the opposite claim was not pre-registered) |

## Controls and robustness (t full / H1 / H2)

| Proxy | row | t |
|---|---|---|
| X1 | N1_lag250 | 0.35 / −0.66 / 1.78 (b 0.0731) |
| X1 | N2_circular_shift | −0.91 / −0.31 / −0.82 (b −0.1674) |
| X1 | N3_permutation | −1.19 / −2.17 / 1.00 (b −0.1977) |
| X1 | cap: NOS | 3.73 / 3.08 / 4.84 (b 0.5341) |
| X1 | robust: range of T+2 | −0.54 / −2.07 / 1.75 (b −0.1941) |
| X1 | robust: without iv30_cm | −0.64 / −1.10 / 0.88 (b −0.3883) |
| X2 | N1_lag250 | −0.89 / −1.18 / −0.13 (b −0.0233) |
| X2 | N2_circular_shift | −0.03 / 0.29 / 0.21 (b −0.0007) |
| X2 | N3_permutation | 1.84 / 2.26 / 0.50 (b 0.0457) |
| X2 | cap: OILOAD | −2.31 / −1.57 / −2.25 (b −0.1158) |
| X2 | robust: range of T+2 | −1.75 / −2.04 / −1.82 (b −0.0803) |
| X2 | robust: without iv30_cm | −3.38 / −3.17 / −4.33 (b −0.1395) |

## Traded legs (near ATM straddle, close T+1 → close T+2, % of the forward after the F&O schedule)

- **X1**: n 1506 (conditional 572); unconditional seller −0.0014 %F (t −0.17); leg cond − all 0.0035 %F (t 0.25); cond after costs 0.0021 %F (t 0.15; halves 0.72 / −0.53).
- **X2**: n 1254 (conditional 588); unconditional seller −0.0046 %F (t −0.52); leg cond − all −0.0038 %F (t −0.24); cond after costs −0.0084 %F (t −0.53; halves −0.57 / −0.24).

## Participant cross-check (not graded)

```
{
 "Client": {
  "n": 1760,
  "share_net_short_calls": 0.545455,
  "share_net_short_puts": 0.956818,
  "share_net_long_gamma": 0.060227,
  "agreement_with_C1_sign": 0.174531
 },
 "FII": {
  "n": 1759,
  "share_net_short_calls": 0.181922,
  "share_net_short_puts": 0.010233,
  "share_net_long_gamma": 0.984082,
  "agreement_with_C1_sign": 0.866894
 },
 "Pro": {
  "n": 1760,
  "share_net_short_calls": 0.750568,
  "share_net_short_puts": 0.597159,
  "share_net_long_gamma": 0.279545,
  "agreement_with_C1_sign": 0.322342
 }
}
```

Latest proxy reading (context only): `{"NGS": 0.140962, "TGL": -0.050878, "gex_net_cr": 12805.914981, "zero_gamma_dist_pct": 0.658174}`.

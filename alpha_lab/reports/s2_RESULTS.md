# S2 — Horizon-60 probability book (run 2026-10-14 21:01, panel snapshot 2026-10-14)

## S2 (plain ₹10L)
config: `{"capital": 1000000, "n_positions": 20, "cash_rate": 0.06, "slippage": 0.0005, "sleeve_frac": 0.0, "hedge": false, "hedge_cost": 0.0003, "nifty_lot": 75, "margin_frac": 0.13, "max_weight": 0.15, "stale_exit_sessions": 10, "stale_zero_sessions": 60}`
grid: every 12th trading Friday from first trading Friday of 2016 → 44 dates; forced stale exits: 5; regime whipsaws: 14

### Smoke 2025-10-01→2026-10-13 (mechanics only): 255 sessions, 4 rebalances, costs ₹86,598, equity NaN-free: True

### S2 Gate A (2020-01-01→2026-10-13): **FAIL**
- ✅ 1a CAGR 23.56% > NIFTY 9.63% (price-to-price)
- ✅ 1b CAGR 23.56% > EW universe 17.78%
- ❌ 2  maxDD -32.0% ≥ −30% and ≥ 1.25×NIFTY (-48.0%)
- ✅ 3  IR 0.74 ≥ 0.45
- ✅ 4  decisions 27 ≥ 25
- decisions 27 · traded ₹91,922,731 · costs ₹472,178 · risk-off rebalances 6 · IR 0.74

```
      strategy  nifty    ew
2020      19.5   14.8  27.3
2021      58.6   24.1  38.5
2022      -0.9    4.3  -2.5
2023      77.4   20.0  45.2
2024      29.2    8.8  17.9
2025      -2.2   10.5   1.8
2026      -0.2  -13.0   1.2
```

**Verdict: Gate A FAIL — Gate B not run (per protocol).**

## S2H (hedged ₹50L, 85/15, whole-lot NIFTY short)
config: `{"capital": 5000000, "n_positions": 20, "cash_rate": 0.06, "slippage": 0.0005, "sleeve_frac": 0.15, "hedge": true, "hedge_cost": 0.0003, "nifty_lot": 75, "margin_frac": 0.13, "max_weight": 0.15, "stale_exit_sessions": 10, "stale_zero_sessions": 60}`
grid: every 12th trading Friday from first trading Friday of 2016 → 44 dates; forced stale exits: 5; regime whipsaws: 14

### Smoke 2025-10-01→2026-10-13 (mechanics only): 255 sessions, 4 rebalances, costs ₹405,504, equity NaN-free: True

### S2H Gate A (2020-01-01→2026-10-13): **PASS**
- ✅ 1a CAGR 19.36% > NIFTY 9.63% (price-to-price)
- ✅ 1b CAGR 19.36% > EW universe 17.78%
- ✅ 2  maxDD -28.0% ≥ −30% and ≥ 1.25×NIFTY (-48.0%)
- ✅ 3  IR 0.51 ≥ 0.45
- ✅ 4  decisions 27 ≥ 25
- decisions 27 · traded ₹381,410,505 · costs ₹1,961,984 · risk-off rebalances 6 · IR 0.51

```
      strategy  nifty    ew
2020      19.9   14.8  27.3
2021      50.3   24.1  38.5
2022      -0.5    4.3  -2.5
2023      65.3   20.0  45.2
2024      26.7    8.8  17.9
2025     -14.1   10.5   1.8
2026       2.8  -13.0   1.2
```

### Gate B uses a 2011-anchored grid (same 12-week rule); the model first trades in 2013 (2 years of labels needed) — 2011–12 sit in cash, which the gate window includes honestly.

### S2H Gate B (2011-01-01→2019-12-31): **FAIL**
- ✅ 1a CAGR 9.93% > NIFTY 7.87%
- ✅ 1b CAGR 9.93% > EW universe 3.55%
- ✅ 2  maxDD -24.9% ≥ −35%
- ❌ 3  excess years vs NIFTY 3/9 ≥ 5

```
      strategy  nifty    ew
2011       5.9  -24.9 -35.8
2012       6.1   27.7  34.6
2013       6.8    6.8 -11.3
2014      62.7   31.4  53.5
2015      13.1   -4.1   2.3
2016      -3.7    3.0   2.6
2017      23.8   28.6  45.3
2018     -11.0    3.2 -19.5
2019       0.0   12.0  -5.3
```

### Full 2011→2026 (2011 anchor): CAGR 14.23% vs NIFTY 8.63% / EW 9.35%, maxDD -35.8%

## Family table (S2 runs)

| Run | Window | Verdict | CAGR | NIFTY | EW-T | maxDD | IR |
|---|---|---|---|---|---|---|---|
| S2 | Gate A | FAIL | 23.56% | 9.63% | 17.78% | -32.0% | 0.74 |
| S2H | Gate A | PASS | 19.36% | 9.63% | 17.78% | -28.0% | 0.51 |
| S2H | Gate B | FAIL | 9.93% | 7.87% | 3.55% | -24.9% | 0.02 |

Notes: VA-break feature skipped (profile cost); results flags exist only where NSE covers the symbol (uncovered names are simply never flagged — stated asymmetry, no coverage column fed to the model); labels masked on >50% one-day data breaks (vendored convention).

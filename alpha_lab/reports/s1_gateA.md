# S1 gateA: 2020-01-01 → 2026-10-13
- CAGR **28.02%** vs NIFTY 9.63% / EW-T 24.16% · maxDD **-16.5%** vs -38.4% · IR 0.74 · rebalances 81 · costs ₹825,153
- forced stale exits: 2; regime whipsaws: 11

### Gate A: **PASS**
- ✅ 1a CAGR 28.02% > NIFTY 9.63% (price-to-price)
- ✅ 1b CAGR 28.02% > EW universe 24.16%
- ✅ 2  maxDD -16.5% ≥ −30% and ≥ 1.25×NIFTY (-48.0%)
- ✅ 3  IR 0.74 ≥ 0.45
- ✅ 4  decisions 81 ≥ 30

```
      strategy  nifty    ew
2020      51.7   14.8  19.1
2021      87.4   24.1  59.1
2022      -0.7    4.3   4.8
2023      37.5   20.0  53.2
2024      33.9    8.8  35.5
2025       4.2   10.5   5.3
2026      -1.3  -13.0  -0.1
```

config: `{"capital": 1000000, "n_positions": 20, "cash_rate": 0.06, "slippage": 0.0005, "sleeve_frac": 0.0, "hedge": false, "hedge_cost": 0.0003, "nifty_lot": 75, "margin_frac": 0.13, "max_weight": 0.15, "stale_exit_sessions": 10, "stale_zero_sessions": 60}` · panel snapshot 2026-10-14 21:02

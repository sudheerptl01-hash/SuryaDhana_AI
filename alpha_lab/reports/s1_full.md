# S1 full: 2011-01-03 → 2026-10-13
- CAGR **20.97%** vs NIFTY 8.63% / EW-T 14.38% · maxDD **-34.6%** vs -38.4% · IR 0.60 · rebalances 189 · costs ₹3,821,620
- forced stale exits: 7; regime whipsaws: 35

### Gates (informational): **FAIL**
- ✅ 1a CAGR 20.97% > NIFTY 8.63% (price-to-price)
- ✅ 1b CAGR 20.97% > EW universe 14.38%
- ❌ 2  maxDD -34.6% ≥ −30% and ≥ 1.25×NIFTY (-48.0%)
- ✅ 3  IR 0.60 ≥ 0.45
- ✅ 4  decisions 189 ≥ 30

```
      strategy  nifty    ew
2011       1.0  -24.9 -37.1
2012      37.3   27.7  41.9
2013      -0.8    6.8  -6.0
2014      88.0   31.4  53.3
2015      -7.3   -4.1  11.8
2016      11.9    3.0  10.3
2017      74.2   28.6  60.4
2018     -18.3    3.2 -19.7
2019      -2.0   12.0  -6.7
2020      52.5   14.9  20.1
2021      87.6   24.1  59.1
2022      -0.7    4.3   4.8
2023      37.6   20.0  53.2
2024      34.0    8.8  35.5
2025       4.2   10.5   5.3
2026      -1.3  -13.0  -0.1
```

config: `{"capital": 1000000, "n_positions": 20, "cash_rate": 0.06, "slippage": 0.0005, "sleeve_frac": 0.0, "hedge": false, "hedge_cost": 0.0003, "nifty_lot": 75, "margin_frac": 0.13, "max_weight": 0.15, "stale_exit_sessions": 10, "stale_zero_sessions": 60}` · panel snapshot 2026-10-14 21:03

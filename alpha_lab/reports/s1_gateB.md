# S1 gateB: 2011-01-03 → 2019-12-31
- CAGR **15.80%** vs NIFTY 7.87% / EW-T 7.43% · maxDD **-34.6%** vs -26.2% · IR 0.43 · rebalances 107 · costs ₹830,642
- forced stale exits: 5; regime whipsaws: 24

### Gate B: **PASS**
- ✅ 1a CAGR 15.80% > NIFTY 7.87%
- ✅ 1b CAGR 15.80% > EW universe 7.43%
- ✅ 2  maxDD -34.6% ≥ −35%
- ✅ 3  excess years vs NIFTY 5/9 ≥ 5

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
```

config: `{"capital": 1000000, "n_positions": 20, "cash_rate": 0.06, "slippage": 0.0005, "sleeve_frac": 0.0, "hedge": false, "hedge_cost": 0.0003, "nifty_lot": 75, "margin_frac": 0.13, "max_weight": 0.15, "stale_exit_sessions": 10, "stale_zero_sessions": 60}` · panel snapshot 2026-10-14 21:02

# A/B configurations as long-only books (10y_liq2)

P2 construction (ml/books) on 2158 signal dates; equal-weight universe benchmark; 20 bps per side headline; DSR at N = 261 with V[SR] = 0.00387 (P2's 66-book cross-trial variance).

| Configuration | Neutralisation | Basket | Excess vs EW (20 bps) | IR [95% CI] | Months beating EW | Turnover / rebalance | Capacity (₹ cr) | Name-level cost excess | DSR |
|---|---|---|---:|---|---:|---:|---:|---:|---:|
| control | none | top_decile | +4.4% | +0.80 [-0.00, +1.55] | 56/105 | 75% | 345 | +0.6% | 0.000 |
| control | none | liq_top_decile | +2.1% | +0.34 [-0.39, +1.02] | 57/105 | 77% | 809 | -0.7% | 0.000 |
| control | vol+size | top_decile | +6.6% | +1.48 [+0.71, +2.25] | 69/105 | 81% | 302 | +1.3% | 0.000 |
| control | vol+size | liq_top_decile | +2.3% | +0.40 [-0.30, +1.14] | 60/105 | 83% | 617 | -1.9% | 0.000 |

# A/B configurations as long-only books (10y_liq)

P2 construction (ml/books) on 2158 signal dates; equal-weight universe benchmark; 20 bps per side headline; DSR at N = 261 with V[SR] = 0.00387 (P2's 66-book cross-trial variance).

| Configuration | Neutralisation | Basket | Excess vs EW (20 bps) | IR [95% CI] | Months beating EW | Turnover / rebalance | Capacity (₹ cr) | Name-level cost excess | DSR |
|---|---|---|---:|---|---:|---:|---:|---:|---:|
| control | none | top_decile | +2.1% | +0.39 [-0.36, +1.10] | 53/105 | 79% | 806 | -0.7% | 0.000 |
| control | none | liq_top_decile | +2.1% | +0.39 [-0.36, +1.10] | 53/105 | 79% | 806 | -0.7% | 0.000 |
| control | vol+size | top_decile | +1.2% | +0.27 [-0.49, +1.02] | 50/105 | 84% | 671 | -2.8% | 0.000 |
| control | vol+size | liq_top_decile | +1.2% | +0.27 [-0.49, +1.02] | 50/105 | 84% | 671 | -2.8% | 0.000 |

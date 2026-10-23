# A/B configurations as long-only books (10y)

P2 construction (ml/books) on 2158 signal dates; equal-weight universe benchmark; 20 bps per side headline; DSR at N = 241 with V[SR] = 0.00387 (P2's 66-book cross-trial variance).

| Configuration | Neutralisation | Basket | Excess vs EW (20 bps) | IR [95% CI] | Months beating EW | Turnover / rebalance | Capacity (₹ cr) | Name-level cost excess | DSR |
|---|---|---|---:|---|---:|---:|---:|---:|---:|
| control | none | top_decile | +7.5% | +1.37 [+0.51, +2.21] | 69/105 | 72% | 168 | +2.8% | 0.000 |
| control | none | liq_top_decile | -0.0% | +0.01 [-0.73, +0.71] | 52/105 | 76% | 785 | -2.8% | 0.000 |
| control | vol+size | top_decile | +10.5% | +2.32 [+1.51, +3.10] | 83/105 | 78% | 157 | +3.9% | 0.081 |
| control | vol+size | liq_top_decile | +1.2% | +0.21 [-0.52, +0.93] | 55/105 | 82% | 603 | -3.1% | 0.000 |
| lr_l2 | none | top_decile | +1.0% | +0.18 [-0.69, +1.08] | 48/105 | 49% | 286 | -1.9% | 0.000 |
| lr_l2 | none | liq_top_decile | -3.0% | -0.29 [-0.99, +0.40] | 49/105 | 53% | 996 | -4.9% | 0.000 |
| lr_l2 | vol+size | top_decile | +9.5% | +1.92 [+1.05, +2.78] | 74/105 | 66% | 169 | +3.5% | 0.006 |
| lr_l2 | vol+size | liq_top_decile | +2.8% | +0.43 [-0.27, +1.12] | 61/105 | 73% | 514 | -1.5% | 0.000 |
| baseline_mom | none | top_decile | -8.9% | -1.22 [-2.02, -0.41] | 32/105 | 89% | 160 | -16.0% | 0.000 |
| baseline_mom | none | liq_top_decile | -9.3% | -0.92 [-1.59, -0.27] | 36/105 | 91% | 520 | -13.8% | 0.000 |
| baseline_mom | vol+size | top_decile | -7.9% | -1.49 [-2.21, -0.73] | 38/105 | 89% | 173 | -14.5% | 0.000 |
| baseline_mom | vol+size | liq_top_decile | -8.7% | -1.21 [-1.87, -0.54] | 36/105 | 91% | 531 | -13.1% | 0.000 |

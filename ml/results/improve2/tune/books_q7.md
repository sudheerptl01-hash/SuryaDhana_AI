# A/B configurations as long-only books (10y_p2)

P2 construction (ml/books) on 2158 signal dates; equal-weight universe benchmark; 20 bps per side headline; DSR at N = 261 with V[SR] = 0.00387 (P2's 66-book cross-trial variance).

| Configuration | Neutralisation | Basket | Excess vs EW (20 bps) | IR [95% CI] | Months beating EW | Turnover / rebalance | Capacity (₹ cr) | Name-level cost excess | DSR |
|---|---|---|---:|---|---:|---:|---:|---:|---:|
| control | none | top_decile | +7.5% | +1.37 [+0.51, +2.21] | 69/105 | 72% | 168 | +2.8% | 0.000 |
| control | none | liq_top_decile | -0.0% | +0.01 [-0.73, +0.71] | 52/105 | 76% | 785 | -2.8% | 0.000 |
| control | vol+size | top_decile | +10.5% | +2.32 [+1.51, +3.10] | 83/105 | 78% | 157 | +3.9% | 0.070 |
| control | vol+size | liq_top_decile | +1.2% | +0.21 [-0.52, +0.93] | 55/105 | 82% | 603 | -3.1% | 0.000 |
| q7_tuned | none | top_decile | +8.1% | +1.45 [+0.57, +2.28] | 70/105 | 71% | 170 | +3.4% | 0.000 |
| q7_tuned | none | liq_top_decile | +0.4% | +0.08 [-0.61, +0.75] | 52/105 | 75% | 739 | -2.4% | 0.000 |
| q7_tuned | vol+size | top_decile | +11.8% | +2.61 [+1.82, +3.38] | 82/105 | 78% | 156 | +5.3% | 0.271 |
| q7_tuned | vol+size | liq_top_decile | +2.8% | +0.45 [-0.24, +1.14] | 57/105 | 82% | 575 | -1.5% | 0.000 |

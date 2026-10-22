# A/B configurations as long-only books (v2)

P2 construction (ml/books) on 919 signal dates; equal-weight universe benchmark; 20 bps per side headline; DSR at N = 241 with V[SR] = 0.00387 (P2's 66-book cross-trial variance).

| Configuration | Neutralisation | Basket | Excess vs EW (20 bps) | IR [95% CI] | Months beating EW | Turnover / rebalance | Capacity (₹ cr) | Name-level cost excess | DSR |
|---|---|---|---:|---|---:|---:|---:|---:|---:|
| control | none | top_decile | -0.0% | +0.01 [-1.16, +1.24] | 19/45 | 70% | 406 | -3.1% | 0.000 |
| control | none | liq_top_decile | -1.9% | -0.34 [-1.51, +0.78] | 18/45 | 74% | 1,735 | -3.6% | 0.000 |
| control | vol+size | top_decile | +7.8% | +1.99 [+0.91, +3.17] | 34/45 | 78% | 214 | +2.3% | 0.062 |
| control | vol+size | liq_top_decile | +5.9% | +1.04 [+0.03, +2.15] | 26/45 | 82% | 912 | +2.2% | 0.000 |
| lr_l2 | none | top_decile | -3.8% | -0.49 [-1.67, +0.61] | 16/45 | 44% | 1,306 | -5.7% | 0.000 |
| lr_l2 | none | liq_top_decile | -7.6% | -0.94 [-1.93, -0.09] | 19/45 | 52% | 1,763 | -8.9% | 0.000 |
| lr_l2 | vol+size | top_decile | +7.9% | +1.70 [+0.58, +2.92] | 32/45 | 62% | 256 | +3.1% | 0.023 |
| lr_l2 | vol+size | liq_top_decile | +2.3% | +0.41 [-0.61, +1.57] | 29/45 | 71% | 743 | -1.5% | 0.000 |
| baseline_mom | none | top_decile | -4.3% | -0.52 [-1.27, +0.29] | 19/45 | 88% | 240 | -10.8% | 0.000 |
| baseline_mom | none | liq_top_decile | -1.7% | -0.12 [-0.88, +0.77] | 21/45 | 92% | 456 | -6.9% | 0.000 |
| baseline_mom | vol+size | top_decile | -4.1% | -0.76 [-1.58, -0.01] | 20/45 | 89% | 212 | -10.8% | 0.000 |
| baseline_mom | vol+size | liq_top_decile | -1.4% | -0.16 [-1.04, +0.72] | 20/45 | 93% | 500 | -5.9% | 0.000 |

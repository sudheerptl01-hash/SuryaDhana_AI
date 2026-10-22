# A/B configurations as long-only books (v1)

P2 construction (ml/books) on 913 signal dates; equal-weight universe benchmark; 20 bps per side headline; DSR at N = 241 with V[SR] = 0.00387 (P2's 66-book cross-trial variance).

| Configuration | Neutralisation | Basket | Excess vs EW (20 bps) | IR [95% CI] | Months beating EW | Turnover / rebalance | Capacity (₹ cr) | Name-level cost excess | DSR |
|---|---|---|---:|---|---:|---:|---:|---:|---:|
| control | none | top_decile | -0.9% | -0.15 [-1.29, +1.01] | 19/45 | 67% | 260 | -3.6% | 0.000 |
| control | none | liq_top_decile | -2.1% | -0.35 [-1.42, +0.67] | 16/45 | 73% | 1,417 | -3.7% | 0.000 |
| control | vol+size | top_decile | +7.2% | +2.05 [+1.16, +3.05] | 35/45 | 77% | 208 | +2.2% | 0.081 |
| control | vol+size | liq_top_decile | +5.1% | +0.92 [-0.05, +2.02] | 25/45 | 81% | 927 | +1.5% | 0.000 |
| all51 | none | top_decile | -1.2% | -0.21 [-1.37, +0.94] | 20/45 | 68% | 265 | -3.9% | 0.000 |
| all51 | none | liq_top_decile | -2.3% | -0.39 [-1.35, +0.57] | 19/45 | 75% | 1,364 | -3.9% | 0.000 |
| all51 | vol+size | top_decile | +6.5% | +1.85 [+0.93, +2.93] | 34/45 | 77% | 210 | +1.5% | 0.037 |
| all51 | vol+size | liq_top_decile | +4.4% | +0.79 [-0.24, +1.92] | 28/45 | 82% | 847 | +0.7% | 0.000 |
| ab7_subsample5 | none | top_decile | +0.1% | +0.01 [-1.09, +1.12] | 22/45 | 73% | 263 | -2.9% | 0.000 |
| ab7_subsample5 | none | liq_top_decile | -1.8% | -0.32 [-1.30, +0.67] | 22/45 | 79% | 1,207 | -3.7% | 0.000 |
| ab7_subsample5 | vol+size | top_decile | +6.9% | +2.19 [+1.19, +3.29] | 36/45 | 81% | 213 | +1.6% | 0.132 |
| ab7_subsample5 | vol+size | liq_top_decile | +4.7% | +0.96 [-0.07, +2.03] | 28/45 | 84% | 838 | +0.8% | 0.000 |
| ab8_uniqueness_w | none | top_decile | -0.1% | -0.03 [-1.15, +1.13] | 20/45 | 68% | 247 | -2.9% | 0.000 |
| ab8_uniqueness_w | none | liq_top_decile | -1.1% | -0.21 [-1.29, +0.87] | 19/45 | 74% | 1,425 | -2.8% | 0.000 |
| ab8_uniqueness_w | vol+size | top_decile | +7.8% | +2.22 [+1.29, +3.23] | 38/45 | 77% | 205 | +2.8% | 0.141 |
| ab8_uniqueness_w | vol+size | liq_top_decile | +6.8% | +1.21 [+0.21, +2.36] | 28/45 | 81% | 946 | +3.1% | 0.001 |

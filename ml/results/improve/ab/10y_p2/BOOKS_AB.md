# A/B configurations as long-only books (10y_p2)

P2 construction (ml/books) on 2158 signal dates; equal-weight universe benchmark; 20 bps per side headline; DSR at N = 270 with V[SR] = 0.00387 (P2's 66-book cross-trial variance).

| Configuration | Neutralisation | Basket | Excess vs EW (20 bps) | IR [95% CI] | Months beating EW | Turnover / rebalance | Capacity (₹ cr) | Name-level cost excess | DSR |
|---|---|---|---:|---|---:|---:|---:|---:|---:|
| control | none | top_decile | +7.5% | +1.37 [+0.51, +2.21] | 69/105 | 72% | 168 | +2.8% | 0.000 |
| control | none | liq_top_decile | -0.0% | +0.01 [-0.73, +0.71] | 52/105 | 76% | 785 | -2.8% | 0.000 |
| control | vol+size | top_decile | +10.5% | +2.32 [+1.51, +3.10] | 83/105 | 78% | 157 | +3.9% | 0.066 |
| control | vol+size | liq_top_decile | +1.2% | +0.21 [-0.52, +0.93] | 55/105 | 82% | 603 | -3.1% | 0.000 |
| ae1_events | none | top_decile | +8.4% | +1.62 [+0.82, +2.44] | 73/105 | 74% | 167 | +3.6% | 0.000 |
| ae1_events | none | liq_top_decile | +1.9% | +0.32 [-0.37, +0.94] | 55/105 | 77% | 766 | -0.9% | 0.000 |
| ae1_events | vol+size | top_decile | +11.2% | +2.46 [+1.71, +3.20] | 79/105 | 78% | 159 | +4.7% | 0.139 |
| ae1_events | vol+size | liq_top_decile | +3.6% | +0.55 [-0.16, +1.28] | 57/105 | 82% | 586 | -0.7% | 0.000 |
| q7_tuned | none | top_decile | +8.1% | +1.45 [+0.57, +2.28] | 70/105 | 71% | 170 | +3.4% | 0.000 |
| q7_tuned | none | liq_top_decile | +0.4% | +0.08 [-0.61, +0.75] | 52/105 | 75% | 739 | -2.4% | 0.000 |
| q7_tuned | vol+size | top_decile | +11.8% | +2.61 [+1.82, +3.38] | 82/105 | 78% | 156 | +5.3% | 0.261 |
| q7_tuned | vol+size | liq_top_decile | +2.8% | +0.45 [-0.24, +1.14] | 57/105 | 82% | 575 | -1.5% | 0.000 |
| q9_expanding | none | top_decile | +9.5% | +1.67 [+0.90, +2.39] | 72/105 | 70% | 176 | +5.2% | 0.000 |
| q9_expanding | none | liq_top_decile | +1.3% | +0.19 [-0.52, +0.83] | 56/105 | 73% | 782 | -1.3% | 0.000 |
| q9_expanding | vol+size | top_decile | +14.9% | +3.06 [+2.29, +3.86] | 85/105 | 75% | 147 | +8.2% | 0.761 |
| q9_expanding | vol+size | liq_top_decile | +5.2% | +0.78 [+0.06, +1.54] | 67/105 | 81% | 555 | +0.6% | 0.000 |
| control_s109 | none | top_decile | +8.0% | +1.46 [+0.58, +2.30] | 68/105 | 72% | 167 | +3.4% | 0.000 |
| control_s109 | none | liq_top_decile | +0.8% | +0.14 [-0.57, +0.80] | 53/105 | 76% | 796 | -1.9% | 0.000 |
| control_s109 | vol+size | top_decile | +10.4% | +2.29 [+1.48, +3.10] | 79/105 | 78% | 156 | +3.9% | 0.058 |
| control_s109 | vol+size | liq_top_decile | +1.8% | +0.30 [-0.41, +1.05] | 59/105 | 82% | 605 | -2.5% | 0.000 |
| control_s110 | none | top_decile | +7.3% | +1.35 [+0.45, +2.19] | 68/105 | 72% | 168 | +2.6% | 0.000 |
| control_s110 | none | liq_top_decile | +1.1% | +0.17 [-0.59, +0.87] | 57/105 | 76% | 770 | -1.6% | 0.000 |
| control_s110 | vol+size | top_decile | +9.9% | +2.19 [+1.39, +2.99] | 78/105 | 78% | 157 | +3.4% | 0.030 |
| control_s110 | vol+size | liq_top_decile | +2.3% | +0.36 [-0.38, +1.08] | 57/105 | 82% | 604 | -2.0% | 0.000 |
| control_s111 | none | top_decile | +7.8% | +1.43 [+0.56, +2.26] | 70/105 | 72% | 167 | +3.2% | 0.000 |
| control_s111 | none | liq_top_decile | +0.8% | +0.13 [-0.57, +0.79] | 51/105 | 76% | 781 | -1.9% | 0.000 |
| control_s111 | vol+size | top_decile | +10.5% | +2.32 [+1.53, +3.09] | 78/105 | 78% | 154 | +4.0% | 0.066 |
| control_s111 | vol+size | liq_top_decile | +1.8% | +0.31 [-0.40, +0.99] | 53/105 | 82% | 614 | -2.4% | 0.000 |
| q9_expanding_s109 | none | top_decile | +9.3% | +1.65 [+0.83, +2.36] | 73/105 | 69% | 178 | +5.0% | 0.000 |
| q9_expanding_s109 | none | liq_top_decile | +1.5% | +0.22 [-0.48, +0.87] | 60/105 | 73% | 789 | -1.1% | 0.000 |
| q9_expanding_s109 | vol+size | top_decile | +14.9% | +3.08 [+2.29, +3.89] | 84/105 | 75% | 148 | +8.2% | 0.773 |
| q9_expanding_s109 | vol+size | liq_top_decile | +4.9% | +0.74 [-0.05, +1.51] | 68/105 | 80% | 565 | +0.4% | 0.000 |
| q9_expanding_s110 | none | top_decile | +9.3% | +1.67 [+0.88, +2.39] | 71/105 | 70% | 179 | +4.9% | 0.000 |
| q9_expanding_s110 | none | liq_top_decile | +2.0% | +0.28 [-0.42, +0.94] | 58/105 | 73% | 788 | -0.7% | 0.000 |
| q9_expanding_s110 | vol+size | top_decile | +14.5% | +2.99 [+2.19, +3.77] | 86/105 | 75% | 147 | +7.8% | 0.682 |
| q9_expanding_s110 | vol+size | liq_top_decile | +5.6% | +0.86 [+0.07, +1.67] | 70/105 | 81% | 560 | +1.1% | 0.000 |

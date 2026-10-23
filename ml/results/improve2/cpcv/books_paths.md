# A/B configurations as long-only books (cpcv)

P2 construction (ml/books) on 2126 signal dates; equal-weight universe benchmark; 20 bps per side headline; DSR at N = 261 with V[SR] = 0.00387 (P2's 66-book cross-trial variance).

| Configuration | Neutralisation | Basket | Excess vs EW (20 bps) | IR [95% CI] | Months beating EW | Turnover / rebalance | Capacity (₹ cr) | Name-level cost excess | DSR |
|---|---|---|---:|---|---:|---:|---:|---:|---:|
| wf_control | none | top_decile | +7.9% | +1.45 [+0.59, +2.27] | 69/103 | 73% | 166 | +3.2% | 0.000 |
| wf_control | none | liq_top_decile | +0.3% | +0.07 [-0.66, +0.80] | 52/103 | 76% | 774 | -2.4% | 0.000 |
| wf_control | vol+size | top_decile | +10.3% | +2.26 [+1.46, +3.09] | 81/103 | 79% | 155 | +3.7% | 0.053 |
| wf_control | vol+size | liq_top_decile | +0.8% | +0.14 [-0.57, +0.87] | 53/103 | 82% | 597 | -3.5% | 0.000 |
| path1 | none | top_decile | +9.9% | +1.69 [+0.95, +2.43] | 72/103 | 70% | 190 | +5.5% | 0.000 |
| path1 | none | liq_top_decile | +3.0% | +0.41 [-0.18, +1.02] | 58/103 | 73% | 815 | +0.5% | 0.000 |
| path1 | vol+size | top_decile | +15.3% | +2.93 [+2.23, +3.68] | 87/103 | 74% | 141 | +8.7% | 0.634 |
| path1 | vol+size | liq_top_decile | +5.4% | +0.75 [+0.01, +1.47] | 63/103 | 79% | 537 | +1.0% | 0.000 |
| path2 | none | top_decile | +9.7% | +1.58 [+0.86, +2.32] | 69/103 | 68% | 192 | +5.6% | 0.000 |
| path2 | none | liq_top_decile | +2.9% | +0.39 [-0.29, +1.03] | 53/103 | 72% | 847 | +0.4% | 0.000 |
| path2 | vol+size | top_decile | +15.9% | +3.22 [+2.51, +3.96] | 87/103 | 74% | 139 | +9.3% | 0.883 |
| path2 | vol+size | liq_top_decile | +6.3% | +0.91 [+0.11, +1.67] | 66/103 | 80% | 549 | +1.8% | 0.000 |
| path3 | none | top_decile | +9.7% | +1.49 [+0.73, +2.23] | 65/103 | 67% | 213 | +5.8% | 0.000 |
| path3 | none | liq_top_decile | +3.4% | +0.45 [-0.20, +1.08] | 53/103 | 72% | 830 | +0.9% | 0.000 |
| path3 | vol+size | top_decile | +15.5% | +3.08 [+2.40, +3.84] | 83/103 | 74% | 140 | +8.9% | 0.791 |
| path3 | vol+size | liq_top_decile | +4.9% | +0.70 [-0.01, +1.45] | 62/103 | 80% | 544 | +0.3% | 0.000 |
| path4 | none | top_decile | +8.7% | +1.33 [+0.61, +2.12] | 67/103 | 66% | 222 | +4.9% | 0.000 |
| path4 | none | liq_top_decile | +4.2% | +0.56 [-0.08, +1.23] | 56/103 | 70% | 888 | +1.8% | 0.000 |
| path4 | vol+size | top_decile | +14.3% | +2.91 [+2.10, +3.70] | 81/103 | 74% | 140 | +7.7% | 0.612 |
| path4 | vol+size | liq_top_decile | +4.8% | +0.70 [-0.06, +1.49] | 64/103 | 80% | 556 | +0.2% | 0.000 |
| path5 | none | top_decile | +10.7% | +1.56 [+0.89, +2.25] | 67/103 | 65% | 203 | +6.8% | 0.000 |
| path5 | none | liq_top_decile | +4.8% | +0.57 [-0.06, +1.21] | 57/103 | 68% | 851 | +2.5% | 0.000 |
| path5 | vol+size | top_decile | +15.9% | +3.22 [+2.48, +4.00] | 86/103 | 73% | 146 | +9.4% | 0.885 |
| path5 | vol+size | liq_top_decile | +5.3% | +0.78 [+0.01, +1.56] | 58/103 | 80% | 515 | +0.7% | 0.000 |
| path6 | none | top_decile | +11.3% | +1.86 [+1.08, +2.60] | 72/103 | 69% | 206 | +7.0% | 0.002 |
| path6 | none | liq_top_decile | +6.3% | +0.83 [+0.18, +1.49] | 61/103 | 72% | 800 | +3.6% | 0.000 |
| path6 | vol+size | top_decile | +17.1% | +3.55 [+2.84, +4.30] | 87/103 | 74% | 141 | +10.4% | 0.985 |
| path6 | vol+size | liq_top_decile | +8.7% | +1.25 [+0.50, +2.00] | 73/103 | 80% | 557 | +4.1% | 0.000 |
| path7 | none | top_decile | +11.0% | +1.81 [+1.07, +2.57] | 71/103 | 69% | 191 | +6.7% | 0.001 |
| path7 | none | liq_top_decile | +3.1% | +0.44 [-0.17, +1.05] | 56/103 | 75% | 764 | +0.4% | 0.000 |
| path7 | vol+size | top_decile | +16.7% | +3.34 [+2.62, +4.10] | 90/103 | 73% | 141 | +10.1% | 0.942 |
| path7 | vol+size | liq_top_decile | +5.8% | +0.86 [+0.12, +1.65] | 66/103 | 80% | 531 | +1.3% | 0.000 |

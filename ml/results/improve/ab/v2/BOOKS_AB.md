# A/B configurations as long-only books (v2)

P2 construction (ml/books) on 919 signal dates; equal-weight universe benchmark; 20 bps per side headline; DSR at N = 241 with V[SR] = 0.00387 (P2's 66-book cross-trial variance).

| Configuration | Neutralisation | Basket | Excess vs EW (20 bps) | IR [95% CI] | Months beating EW | Turnover / rebalance | Capacity (₹ cr) | Name-level cost excess | DSR |
|---|---|---|---:|---|---:|---:|---:|---:|---:|
| control | none | top_decile | -0.0% | +0.01 [-1.16, +1.24] | 19/45 | 70% | 406 | -3.1% | 0.000 |
| control | none | liq_top_decile | -1.9% | -0.34 [-1.51, +0.78] | 18/45 | 74% | 1,735 | -3.6% | 0.000 |
| control | vol+size | top_decile | +7.8% | +1.99 [+0.91, +3.17] | 34/45 | 78% | 214 | +2.3% | 0.062 |
| control | vol+size | liq_top_decile | +5.9% | +1.04 [+0.03, +2.15] | 26/45 | 82% | 912 | +2.2% | 0.000 |
| ab1_mkt | none | top_decile | +0.6% | +0.13 [-1.12, +1.43] | 24/45 | 75% | 358 | -3.0% | 0.000 |
| ab1_mkt | none | liq_top_decile | -0.5% | -0.09 [-1.15, +0.94] | 21/45 | 78% | 1,325 | -2.6% | 0.000 |
| ab1_mkt | vol+size | top_decile | +7.8% | +2.27 [+1.31, +3.26] | 34/45 | 80% | 229 | +2.5% | 0.158 |
| ab1_mkt | vol+size | liq_top_decile | +4.2% | +0.78 [-0.23, +1.88] | 29/45 | 83% | 921 | +0.6% | 0.000 |
| ab2_sector | none | top_decile | +2.8% | +0.58 [-0.61, +1.85] | 24/45 | 72% | 461 | -0.6% | 0.000 |
| ab2_sector | none | liq_top_decile | -2.2% | -0.37 [-1.36, +0.64] | 19/45 | 76% | 1,498 | -4.1% | 0.000 |
| ab2_sector | vol+size | top_decile | +10.9% | +3.16 [+2.19, +4.19] | 35/45 | 78% | 231 | +5.8% | 0.758 |
| ab2_sector | vol+size | liq_top_decile | +6.1% | +1.14 [+0.12, +2.27] | 26/45 | 82% | 919 | +2.6% | 0.001 |
| ab2p_sector_placebo | none | top_decile | +1.4% | +0.31 [-0.94, +1.53] | 28/45 | 72% | 401 | -2.0% | 0.000 |
| ab2p_sector_placebo | none | liq_top_decile | -0.5% | -0.10 [-1.18, +0.98] | 24/45 | 76% | 1,465 | -2.5% | 0.000 |
| ab2p_sector_placebo | vol+size | top_decile | +10.1% | +2.99 [+2.00, +3.97] | 36/45 | 77% | 225 | +4.8% | 0.647 |
| ab2p_sector_placebo | vol+size | liq_top_decile | +5.0% | +0.97 [-0.07, +2.08] | 27/45 | 82% | 931 | +1.4% | 0.000 |
| ab3_fo | none | top_decile | +0.7% | +0.16 [-1.01, +1.30] | 21/45 | 68% | 461 | -2.1% | 0.000 |
| ab3_fo | none | liq_top_decile | -0.5% | -0.09 [-1.22, +0.92] | 21/45 | 74% | 1,925 | -1.9% | 0.000 |
| ab3_fo | vol+size | top_decile | +8.1% | +2.12 [+1.15, +3.18] | 33/45 | 78% | 218 | +2.7% | 0.099 |
| ab3_fo | vol+size | liq_top_decile | +5.7% | +1.13 [+0.20, +2.13] | 24/45 | 82% | 959 | +2.2% | 0.001 |
| ab4_flows | none | top_decile | +4.4% | +0.82 [-0.35, +2.08] | 26/45 | 70% | 383 | +1.1% | 0.000 |
| ab4_flows | none | liq_top_decile | +0.3% | +0.05 [-0.85, +0.99] | 23/45 | 76% | 1,405 | -1.7% | 0.000 |
| ab4_flows | vol+size | top_decile | +6.1% | +1.83 [+0.64, +3.03] | 28/45 | 80% | 226 | +0.7% | 0.035 |
| ab4_flows | vol+size | liq_top_decile | +2.7% | +0.52 [-0.42, +1.54] | 25/45 | 83% | 914 | -0.9% | 0.000 |
| ab5_all | none | top_decile | +5.2% | +1.01 [-0.26, +2.35] | 28/45 | 72% | 484 | +1.8% | 0.000 |
| ab5_all | none | liq_top_decile | +2.5% | +0.39 [-0.64, +1.41] | 27/45 | 79% | 1,479 | +0.5% | 0.000 |
| ab5_all | vol+size | top_decile | +10.4% | +3.18 [+2.20, +4.26] | 38/45 | 79% | 242 | +5.3% | 0.759 |
| ab5_all | vol+size | liq_top_decile | +6.3% | +1.27 [+0.38, +2.31] | 30/45 | 84% | 934 | +2.8% | 0.002 |
| ab6_ensemble_all52 | none | top_decile | +7.7% | +1.57 [+0.62, +2.70] | 34/45 | 71% | 278 | +3.4% | 0.012 |
| ab6_ensemble_all52 | none | liq_top_decile | +5.5% | +0.79 [-0.35, +1.95] | 31/45 | 77% | 1,074 | +2.4% | 0.000 |
| ab6_ensemble_all52 | vol+size | top_decile | +10.8% | +2.87 [+1.76, +3.96] | 38/45 | 74% | 200 | +5.5% | 0.561 |
| ab6_ensemble_all52 | vol+size | liq_top_decile | +9.1% | +1.58 [+0.42, +2.82] | 32/45 | 80% | 862 | +5.4% | 0.011 |
| lr_l2 | none | top_decile | -3.8% | -0.49 [-1.67, +0.61] | 16/45 | 44% | 1,306 | -5.7% | 0.000 |
| lr_l2 | none | liq_top_decile | -7.6% | -0.94 [-1.93, -0.09] | 19/45 | 52% | 1,763 | -8.9% | 0.000 |
| lr_l2 | vol+size | top_decile | +7.9% | +1.70 [+0.58, +2.92] | 32/45 | 62% | 256 | +3.1% | 0.023 |
| lr_l2 | vol+size | liq_top_decile | +2.3% | +0.41 [-0.61, +1.57] | 29/45 | 71% | 743 | -1.5% | 0.000 |
| baseline_mom | none | top_decile | -4.3% | -0.52 [-1.27, +0.29] | 19/45 | 88% | 240 | -10.8% | 0.000 |
| baseline_mom | none | liq_top_decile | -1.7% | -0.12 [-0.88, +0.77] | 21/45 | 92% | 456 | -6.9% | 0.000 |
| baseline_mom | vol+size | top_decile | -4.1% | -0.76 [-1.58, -0.01] | 20/45 | 89% | 212 | -10.8% | 0.000 |
| baseline_mom | vol+size | liq_top_decile | -1.4% | -0.16 [-1.04, +0.72] | 20/45 | 93% | 500 | -5.9% | 0.000 |
| ab6_lambdarank52 | none | top_decile | +6.4% | +1.07 [+0.03, +2.17] | 29/45 | 69% | 202 | +0.9% | 0.001 |
| ab6_lambdarank52 | none | liq_top_decile | +7.4% | +0.87 [-0.14, +1.90] | 28/45 | 77% | 574 | +3.0% | 0.000 |
| ab6_lambdarank52 | vol+size | top_decile | +4.8% | +1.33 [+0.27, +2.37] | 31/45 | 72% | 201 | +0.4% | 0.003 |
| ab6_lambdarank52 | vol+size | liq_top_decile | +4.1% | +0.77 [-0.35, +1.82] | 24/45 | 76% | 843 | +1.3% | 0.000 |
| ab6_catboost52 | none | top_decile | +0.2% | +0.05 [-1.12, +1.26] | 21/45 | 66% | 461 | -2.7% | 0.000 |
| ab6_catboost52 | none | liq_top_decile | -1.0% | -0.17 [-1.34, +0.98] | 24/45 | 71% | 1,980 | -2.6% | 0.000 |
| ab6_catboost52 | vol+size | top_decile | +9.1% | +2.28 [+1.18, +3.51] | 35/45 | 76% | 210 | +3.7% | 0.167 |
| ab6_catboost52 | vol+size | liq_top_decile | +6.3% | +1.04 [-0.02, +2.19] | 27/45 | 80% | 931 | +2.6% | 0.000 |

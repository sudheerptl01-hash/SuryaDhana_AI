# Evidence → probability: one frame for every condition, merged and tested

Generated 2026-10-14 18:22 by `scripts/evidence_probability_study.py` (plan: `PLAN.md`, written before any number). 428,920 stock-dates (391,344 in the liquid universe L, 278,702 in the Desk's top 300), 1,945 symbols, 930 signal dates to 2026-10-13. Round trip 0.955% at ₹50,000. Runtime 77 s.

## Conditional probabilities: liquid universe L, 5 sessions

P(beat) = share of flagged stocks that beat the universe's average over the next 5 sessions (entry next open), vs all covered stocks the same weeks. Lift and mean excess: weekly difference, flagged minus covered (Newey-West t). P(bottom 20%) = share that landed in the worst fifth (20% by construction for the covered set). Credibility: empirical-Bayes P(the effect has this sign).

| Family | Condition | Exp. | Events pre / 2024+ | P(beat) % flagged vs base | Lift pp pre / 2024+ | Mean excess % (t) pre / 2024+ | P(bottom 20%) flagged vs base | Verdict | Credibility |
|---|---|---|---|---|---|---|---|---|---|
| Momentum & trend | Momentum score, top decile | + | 22,982 / 11,886 | 48.0 vs 45.4 | +2.5 / +2.8 | +0.32 (4.7) / +0.17 (1.6) | 24.3 vs 19.9 | Holds (weaker) | 100% |
| Momentum & trend | Momentum score, bottom decile | − | 22,306 / 11,748 | 43.3 vs 45.4 | -1.5 / -2.7 | -0.08 (-1.0) / -0.21 (-2.5) | 19.7 vs 19.9 | Holds (weaker) | 99% |
| Momentum & trend | Close below its 200-day average | − | 80,003 / 49,420 | 44.9 vs 46.3 | -1.7 / -2.4 | -0.17 (-4.1) / -0.16 (-2.8) | 18.9 vs 19.9 | Robust | 100% |
| Momentum & trend | Within 5% of the 52-week high | + | 52,322 / 22,145 | 46.4 vs 44.4 | +0.9 / +1.7 | +0.06 (0.8) / -0.00 (-0.0) | 20.9 vs 19.9 | No effect | 75% |
| Momentum & trend | Within 10% of the 52-week low | − | 28,478 / 17,881 | 45.9 vs 46.8 | -0.8 / -1.7 | -0.15 (-2.0) / -0.16 (-1.7) | 17.1 vs 19.9 | Holds (weaker) | 99% |
| Risk | 60-day volatility, top decile | − | 23,028 / 11,917 | 42.5 vs 45.4 | -3.3 / -2.4 | -0.20 (-2.1) / -0.11 (-1.0) | 30.6 vs 19.9 | Holds (weaker) | 98% |
| Risk | Beta, top decile | − | 22,164 / 11,908 | 42.7 vs 45.3 | -2.4 / -3.4 | -0.10 (-0.9) / -0.09 (-0.6) | 25.6 vs 19.9 | No effect | 85% |
| Risk | Biggest 1-day gain in 20 days, top decile | − | 23,032 / 11,914 | 43.8 vs 45.4 | -1.9 / -1.3 | -0.03 (-0.4) / +0.01 (0.1) | 27.7 vs 19.9 | No effect | 60% |
| Risk | Amihud illiquidity, top decile | 0 | 23,037 / 11,914 | 43.9 vs 45.4 | -1.6 / -1.7 | +0.06 (0.9) / +0.06 (0.6) | 27.2 vs 19.9 | No effect | 84% |
| Volume & attention | Abnormal volume (5d vs 60d), top decile | − | 23,030 / 11,912 | 44.3 vs 45.4 | -0.8 / -1.6 | -0.02 (-0.5) / -0.14 (-2.3) | 25.7 vs 19.9 | No effect | 96% |
| Volume & attention | 20-day overnight return, top decile | − | 23,039 / 11,911 | 43.9 vs 45.4 | -2.0 / -1.0 | -0.06 (-1.1) / +0.04 (0.4) | 26.1 vs 19.9 | No effect | 74% |
| Volume & attention | Delivery surge top decile + 20d return > 0 | 0 | 7,921 / 7,712 | 43.3 vs 44.1 | -0.8 / -2.1 | +0.06 (0.6) / -0.26 (-2.4) | 27.2 vs 19.9 | Unstable | 89% |
| Price action | Upside value-area break, last 5 sessions | − | 36,449 / 16,496 | 44.1 vs 44.9 | -1.5 / -1.2 | -0.15 (-3.2) / -0.20 (-2.4) | 22.4 vs 19.9 | Robust | 100% |
| Price action | Upside VA break on ≥ 2× volume | − | 17,864 / 8,944 | 43.1 vs 44.6 | -2.4 / -2.7 | -0.07 (-0.9) / -0.30 (-2.8) | 24.8 vs 19.9 | No effect | 99% |
| Price action | Downside VA break on ≥ 2× volume | − | 4,721 / 3,115 | 46.3 vs 45.9 | +0.3 / -0.0 | -0.13 (-1.1) / -0.14 (-1.1) | 19.6 vs 19.9 | No effect | 93% |
| Price action | 52-week-high breakout on volume, last 5 sessions | − | 16,965 / 7,099 | 44.9 vs 44.3 | -0.1 / +2.0 | -0.05 (-0.5) / +0.09 (0.5) | 25.1 vs 19.9 | No effect | 57% |
| Price action | Burst: day ≥ +4% on higher volume, last 5 sessions | − | 48,900 / 25,396 | 43.4 vs 45.1 | -1.7 / -1.5 | -0.09 (-2.1) / -0.10 (-1.7) | 26.0 vs 19.9 | Holds (weaker) | 100% |
| Price action | RSI(2) < 5 above the 200-day average | + | 6,955 / 3,496 | 49.9 vs 45.4 | +3.4 / +3.7 | +0.30 (2.2) / +0.20 (1.0) | 16.9 vs 19.9 | Holds (weaker) | 98% |
| Price action | RSI(2) < 5 in a momentum leader | + | 2,778 / 1,590 | 53.1 vs 46.1 | +4.0 / +7.9 | +0.49 (2.8) / +0.58 (2.5) | 17.9 vs 19.9 | Robust | 100% |
| Reversal | 5-day return, bottom decile | + | 22,351 / 11,770 | 46.8 vs 45.4 | +0.9 / +1.6 | +0.04 (0.6) / +0.17 (1.9) | 21.1 vs 19.9 | No effect | 94% |
| Reversal | 5-day bottom decile on below-normal volume | + | 12,906 / 7,266 | 47.3 vs 45.2 | +1.6 / +2.7 | +0.14 (1.5) / +0.30 (3.2) | 20.5 vs 19.9 | Holds (weaker) | 100% |
| Reversal | 20-day return, bottom decile | + | 22,357 / 11,772 | 45.3 vs 45.4 | -0.1 / +0.2 | -0.06 (-0.7) / +0.02 (0.2) | 20.7 vs 19.9 | No effect | 66% |
| Results & corporate | Strong bad results (≤ −5% vs market), last 60 sessions | − | 7,953 / 5,784 | 44.0 vs 45.4 | -1.3 / -2.2 | -0.13 (-1.3) / -0.16 (-2.4) | 19.7 vs 18.3 | Holds (weaker) | 99% |
| Results & corporate | Strong good results (≥ +5%), last 60 sessions | + | 8,904 / 6,329 | 47.5 vs 45.5 | +1.2 / +2.6 | +0.13 (1.5) / +0.23 (3.1) | 19.3 vs 18.2 | Holds (weaker) | 100% |
| Results & corporate | Any results, last 20 sessions | 0 | 51,879 / 20,582 | 46.0 vs 45.9 | +0.8 / -2.0 | +0.08 (0.9) / -0.34 (-2.3) | 17.4 vs 18.4 | Unstable | 65% |
| Results & corporate | Split / bonus ex-date, last 20 sessions | − | 1,156 / 664 | 40.2 vs 45.4 | -6.5 / -3.9 | -0.80 (-4.2) / -0.95 (-2.4) | 28.6 vs 19.9 | Robust | 100% |
| Flows | Non-institutional bulk-deal net buy, last 20 sessions | − | 3,042 / 3,149 | 43.7 vs 44.2 | -3.2 / +1.5 | -0.33 (-1.7) / +0.20 (1.2) | 25.3 vs 19.9 | No effect | 59% |
| Flows | MF / insurer bulk-deal net buy, last 20 sessions | + | 417 / 800 | 48.2 vs 44.2 | +3.3 / +3.7 | +0.62 (1.3) / +0.30 (1.1) | 17.8 vs 19.9 | No effect | 85% |
| Flows | Non-institutional bulk-deal net sell, last 20 sessions | 0 | 3,454 / 3,971 | 45.7 vs 44.2 | +0.4 / +2.9 | +0.19 (0.9) / +0.16 (1.5) | 23.2 vs 19.9 | No effect | 94% |
| Flows | Fresh insider buy (≥ ₹10 lakh), last 21 sessions | + | 647 / 424 | 50.4 vs 45.5 | +2.7 / +7.6 | +0.18 (0.8) / +0.51 (1.5) | 17.9 vs 18.7 | No effect | 87% |
| Flows | Insider sale (≥ ₹10 lakh), last 63 sessions | 0 | 5,537 / 2,439 | 46.1 vs 45.2 | -0.1 / +2.0 | -0.14 (-1.9) / +0.10 (1.0) | 17.3 vs 18.5 | No effect | 81% |
| Flows | F&O long build-up (5d price > +3%, OI > +10%) | 0 | 1,890 / 954 | 44.5 vs 46.4 | -3.5 / +0.5 | -0.57 (-3.3) / -0.04 (-0.2) | 21.1 vs 14.7 | No effect | 99% |
| Flows | F&O short build-up (5d price < −3%, OI > +10%) | 0 | 1,882 / 1,467 | 47.5 vs 46.9 | +0.0 / -2.6 | +0.08 (0.5) / -0.10 (-0.7) | 14.7 vs 15.2 | No effect | 55% |
| Flows | Put/call OI ratio, top quintile of F&O stocks | + | 7,562 / 5,846 | 47.7 vs 46.3 | +1.3 / +1.4 | +0.07 (1.1) / +0.07 (1.3) | 14.7 vs 15.0 | No effect | 96% |
| Flows | Near 52w high + MTF growth top decile | − | 1,401 / 2,289 | 45.3 vs 46.1 | +0.6 / -0.8 | +0.08 (0.4) / +0.11 (0.5) | 24.6 vs 21.6 | No effect | 72% |
| Flows | Shareholding accumulation filed, last 20 sessions | + | 1,128 / 1,967 | 50.0 vs 48.7 | -1.3 / -0.1 | -0.35 (-0.8) / +0.22 (0.8) | 15.5 vs 15.6 | No effect | 57% |

## Conditional probabilities: liquid universe L, 20 sessions

P(beat) = share of flagged stocks that beat the universe's average over the next 20 sessions (entry next open), vs all covered stocks the same weeks. Lift and mean excess: weekly difference, flagged minus covered (Newey-West t). P(bottom 20%) = share that landed in the worst fifth (20% by construction for the covered set). Credibility: empirical-Bayes P(the effect has this sign).

| Family | Condition | Exp. | Events pre / 2024+ | P(beat) % flagged vs base | Lift pp pre / 2024+ | Mean excess % (t) pre / 2024+ | P(bottom 20%) flagged vs base | Verdict | Credibility |
|---|---|---|---|---|---|---|---|---|---|
| Momentum & trend | Momentum score, top decile | + | 22,976 / 11,513 | 49.4 vs 45.1 | +4.8 / +3.6 | +1.32 (5.7) / +0.55 (1.6) | 22.7 vs 19.9 | Holds (weaker) | 100% |
| Momentum & trend | Momentum score, bottom decile | − | 22,292 / 11,387 | 41.5 vs 45.1 | -2.6 / -4.3 | -0.51 (-2.0) / -0.92 (-3.1) | 21.0 vs 19.9 | Holds (weaker) | 100% |
| Momentum & trend | Close below its 200-day average | − | 79,964 / 47,948 | 44.0 vs 45.9 | -2.8 / -2.9 | -0.69 (-5.1) / -0.60 (-3.2) | 19.6 vs 19.9 | Robust | 100% |
| Momentum & trend | Within 5% of the 52-week high | + | 52,300 / 21,522 | 47.7 vs 44.2 | +2.3 / +3.0 | +0.40 (1.9) / +0.19 (0.5) | 19.1 vs 19.9 | No effect | 96% |
| Momentum & trend | Within 10% of the 52-week low | − | 28,470 / 17,041 | 45.0 vs 46.4 | -2.4 / -2.4 | -0.65 (-3.0) / -0.71 (-2.4) | 18.0 vs 19.9 | Robust | 100% |
| Risk | 60-day volatility, top decile | − | 23,002 / 11,550 | 40.8 vs 45.1 | -5.0 / -3.6 | -0.79 (-2.6) / -0.49 (-1.4) | 32.0 vs 19.9 | Holds (weaker) | 99% |
| Risk | Beta, top decile | − | 22,145 / 11,543 | 42.1 vs 45.0 | -3.4 / -3.3 | -0.31 (-0.8) / -0.37 (-0.7) | 27.0 vs 19.9 | No effect | 81% |
| Risk | Biggest 1-day gain in 20 days, top decile | − | 23,015 / 11,545 | 42.7 vs 45.1 | -2.5 / -2.1 | -0.08 (-0.4) / -0.05 (-0.2) | 27.8 vs 19.9 | No effect | 65% |
| Risk | Amihud illiquidity, top decile | 0 | 23,033 / 11,546 | 43.4 vs 45.1 | -1.6 / -2.2 | +0.21 (1.0) / -0.05 (-0.1) | 26.7 vs 19.9 | No effect | 78% |
| Volume & attention | Abnormal volume (5d vs 60d), top decile | − | 23,024 / 11,544 | 44.4 vs 45.1 | +0.0 / -1.1 | +0.06 (0.5) / -0.16 (-1.1) | 23.4 vs 19.9 | No effect | 62% |
| Volume & attention | 20-day overnight return, top decile | − | 23,027 / 11,539 | 43.6 vs 45.1 | -2.1 / -0.8 | -0.20 (-1.1) / +0.21 (0.9) | 26.0 vs 19.9 | No effect | 63% |
| Volume & attention | Delivery surge top decile + 20d return > 0 | 0 | 7,917 / 7,464 | 43.2 vs 43.6 | +0.4 / -1.0 | +0.34 (1.1) / -0.28 (-1.0) | 25.3 vs 19.9 | No effect | 50% |
| Price action | Upside value-area break, last 5 sessions | − | 36,435 / 16,186 | 44.6 vs 44.7 | -0.6 / -0.5 | -0.18 (-1.5) / -0.25 (-1.2) | 21.5 vs 19.9 | No effect | 96% |
| Price action | Upside VA break on ≥ 2× volume | − | 17,859 / 8,746 | 43.3 vs 44.4 | -0.7 / -1.9 | +0.01 (0.0) / -0.56 (-2.1) | 23.5 vs 19.9 | Unstable | 86% |
| Price action | Downside VA break on ≥ 2× volume | − | 4,721 / 3,017 | 45.6 vs 45.4 | -0.1 / +0.2 | -0.21 (-0.9) / -0.06 (-0.2) | 18.2 vs 19.9 | No effect | 79% |
| Price action | 52-week-high breakout on volume, last 5 sessions | − | 16,961 / 6,881 | 46.0 vs 44.1 | +3.0 / +2.9 | +0.56 (2.2) / +0.15 (0.4) | 22.4 vs 19.9 | No effect | 96% |
| Price action | Burst: day ≥ +4% on higher volume, last 5 sessions | − | 48,880 / 24,738 | 43.5 vs 44.8 | -1.5 / -1.1 | -0.13 (-1.1) / -0.10 (-0.6) | 25.0 vs 19.9 | No effect | 89% |
| Price action | RSI(2) < 5 above the 200-day average | + | 6,954 / 3,374 | 47.0 vs 44.7 | +2.7 / +0.8 | +0.54 (1.9) / -0.09 (-0.3) | 17.9 vs 19.9 | No effect | 87% |
| Price action | RSI(2) < 5 in a momentum leader | + | 2,778 / 1,541 | 50.7 vs 45.4 | +5.7 / +5.5 | +1.30 (3.7) / +0.42 (0.9) | 17.6 vs 19.9 | No effect | 100% |
| Reversal | 5-day return, bottom decile | + | 22,337 / 11,407 | 44.9 vs 45.1 | -0.3 / +0.2 | -0.05 (-0.3) / +0.10 (0.7) | 21.8 vs 19.9 | No effect | 61% |
| Reversal | 5-day bottom decile on below-normal volume | + | 12,898 / 7,010 | 44.4 vs 44.9 | -1.1 / +0.1 | -0.05 (-0.3) / +0.15 (1.0) | 22.3 vs 19.9 | No effect | 72% |
| Reversal | 20-day return, bottom decile | + | 22,345 / 11,412 | 44.2 vs 45.1 | -1.0 / -0.1 | -0.32 (-1.4) / -0.02 (-0.1) | 21.2 vs 19.9 | No effect | 83% |
| Results & corporate | Strong bad results (≤ −5% vs market), last 60 sessions | − | 7,952 / 5,604 | 44.0 vs 45.1 | -1.1 / -1.1 | -0.04 (-0.1) / -0.30 (-1.2) | 20.0 vs 18.3 | No effect | 83% |
| Results & corporate | Strong good results (≥ +5%), last 60 sessions | + | 8,897 / 6,127 | 48.6 vs 45.1 | +2.9 / +4.0 | +0.39 (1.4) / +0.79 (3.3) | 18.7 vs 18.3 | Holds (weaker) | 100% |
| Results & corporate | Any results, last 20 sessions | 0 | 51,868 / 20,567 | 46.0 vs 45.7 | +0.6 / -0.6 | -0.01 (-0.1) / -0.38 (-1.7) | 17.3 vs 18.4 | No effect | 86% |
| Results & corporate | Split / bonus ex-date, last 20 sessions | − | 1,156 / 653 | 43.0 vs 45.2 | -2.7 / +2.4 | -1.16 (-2.2) / +0.29 (0.3) | 25.9 vs 19.9 | Unstable | 87% |
| Flows | Non-institutional bulk-deal net buy, last 20 sessions | − | 3,036 / 3,015 | 42.5 vs 43.6 | -3.2 / +1.3 | -0.80 (-1.5) / +0.21 (0.6) | 26.6 vs 19.9 | No effect | 64% |
| Flows | MF / insurer bulk-deal net buy, last 20 sessions | + | 417 / 771 | 48.3 vs 43.8 | +0.6 / +6.3 | +1.51 (1.2) / +1.10 (1.5) | 18.4 vs 19.9 | No effect | 84% |
| Flows | Non-institutional bulk-deal net sell, last 20 sessions | 0 | 3,449 / 3,810 | 44.7 vs 43.7 | +1.0 / +2.6 | +0.45 (0.6) / +0.41 (1.0) | 22.8 vs 19.9 | No effect | 80% |
| Flows | Fresh insider buy (≥ ₹10 lakh), last 21 sessions | + | 647 / 360 | 49.5 vs 45.5 | +3.6 / +5.0 | +1.12 (1.7) / +0.77 (0.9) | 16.8 vs 18.5 | No effect | 88% |
| Flows | Insider sale (≥ ₹10 lakh), last 63 sessions | 0 | 5,536 / 2,274 | 45.2 vs 45.0 | -1.2 / +3.7 | -0.47 (-2.2) / +0.32 (1.4) | 16.1 vs 18.3 | Unstable | 73% |
| Flows | F&O long build-up (5d price > +3%, OI > +10%) | 0 | 1,888 / 947 | 43.8 vs 44.7 | -3.2 / +2.6 | -0.94 (-2.2) / +0.30 (0.7) | 19.3 vs 15.9 | Unstable | 79% |
| Flows | F&O short build-up (5d price < −3%, OI > +10%) | 0 | 1,880 / 1,437 | 46.1 vs 46.2 | -0.5 / -1.3 | +0.25 (0.9) / +0.05 (0.2) | 15.3 vs 15.6 | No effect | 75% |
| Flows | Put/call OI ratio, top quintile of F&O stocks | + | 7,555 / 5,674 | 46.2 vs 45.5 | +0.1 / +1.4 | +0.10 (0.6) / +0.34 (2.3) | 15.2 vs 15.4 | No effect | 98% |
| Flows | Near 52w high + MTF growth top decile | − | 1,401 / 2,225 | 46.1 vs 46.9 | -0.3 / +0.6 | +0.15 (0.3) / -0.03 (-0.1) | 23.6 vs 20.3 | No effect | 53% |
| Flows | Shareholding accumulation filed, last 20 sessions | + | 1,128 / 1,964 | 49.6 vs 49.5 | -8.1 / +3.3 | -1.60 (-1.6) / +0.26 (0.5) | 14.2 vs 13.7 | No effect | 56% |

## Conditional probabilities: liquid universe L, 60 sessions

P(beat) = share of flagged stocks that beat the universe's average over the next 60 sessions (entry next open), vs all covered stocks the same weeks. Lift and mean excess: weekly difference, flagged minus covered (Newey-West t). P(bottom 20%) = share that landed in the worst fifth (20% by construction for the covered set). Credibility: empirical-Bayes P(the effect has this sign).

| Family | Condition | Exp. | Events pre / 2024+ | P(beat) % flagged vs base | Lift pp pre / 2024+ | Mean excess % (t) pre / 2024+ | P(bottom 20%) flagged vs base | Verdict | Credibility |
|---|---|---|---|---|---|---|---|---|---|
| Momentum & trend | Momentum score, top decile | + | 22,968 / 10,774 | 49.1 vs 44.3 | +6.1 / +2.0 | +3.48 (5.5) / +0.79 (0.8) | 21.4 vs 19.9 | No effect | 100% |
| Momentum & trend | Momentum score, bottom decile | − | 22,268 / 10,669 | 38.5 vs 44.3 | -4.8 / -5.4 | -2.16 (-3.6) / -2.15 (-3.7) | 22.7 vs 19.9 | Robust | 100% |
| Momentum & trend | Close below its 200-day average | − | 79,863 / 45,361 | 42.1 vs 45.0 | -4.7 / -3.6 | -1.99 (-5.4) / -1.26 (-3.0) | 20.2 vs 19.9 | Robust | 100% |
| Momentum & trend | Within 5% of the 52-week high | + | 52,267 / 20,006 | 48.3 vs 43.6 | +4.4 / +2.5 | +1.40 (2.7) / +0.31 (0.3) | 17.7 vs 19.9 | No effect | 99% |
| Momentum & trend | Within 10% of the 52-week low | − | 28,454 / 16,020 | 42.5 vs 45.4 | -5.9 / -3.9 | -2.54 (-6.1) / -2.01 (-2.8) | 19.3 vs 19.9 | Robust | 100% |
| Risk | 60-day volatility, top decile | − | 22,949 / 10,820 | 38.4 vs 44.3 | -7.1 / -5.5 | -2.18 (-2.7) / -1.76 (-1.7) | 33.1 vs 19.9 | Holds (weaker) | 100% |
| Risk | Beta, top decile | − | 22,098 / 10,820 | 40.1 vs 44.2 | -5.1 / -6.0 | -0.92 (-0.9) / -1.58 (-1.1) | 27.8 vs 19.9 | No effect | 85% |
| Risk | Biggest 1-day gain in 20 days, top decile | − | 22,972 / 10,819 | 41.2 vs 44.3 | -3.3 / -3.9 | -0.47 (-0.9) / -0.77 (-1.1) | 28.7 vs 19.9 | No effect | 89% |
| Risk | Amihud illiquidity, top decile | 0 | 23,020 / 10,815 | 42.4 vs 44.3 | -1.5 / -3.7 | +0.41 (0.7) / -0.66 (-0.7) | 27.0 vs 19.9 | No effect | 55% |
| Volume & attention | Abnormal volume (5d vs 60d), top decile | − | 23,003 / 10,814 | 43.9 vs 44.3 | +0.3 / -1.6 | +0.35 (1.5) / -0.54 (-1.9) | 23.0 vs 19.9 | No effect | 54% |
| Volume & attention | 20-day overnight return, top decile | − | 22,996 / 10,811 | 42.8 vs 44.3 | -2.0 / -1.4 | -0.33 (-0.8) / +0.07 (0.1) | 26.5 vs 19.9 | No effect | 75% |
| Volume & attention | Delivery surge top decile + 20d return > 0 | 0 | 7,906 / 6,946 | 42.3 vs 42.6 | +1.8 / -2.4 | +1.24 (2.5) / -0.84 (-1.8) | 25.0 vs 19.9 | Unstable | 66% |
| Price action | Upside value-area break, last 5 sessions | − | 36,406 / 15,228 | 44.7 vs 44.0 | +0.7 / +0.2 | +0.29 (1.3) / -0.25 (-0.6) | 20.4 vs 19.9 | No effect | 80% |
| Price action | Upside VA break on ≥ 2× volume | − | 17,847 / 8,211 | 43.8 vs 43.7 | +0.9 / -2.0 | +0.71 (2.4) / -0.86 (-2.1) | 22.3 vs 19.9 | Unstable | 73% |
| Price action | Downside VA break on ≥ 2× volume | − | 4,716 / 2,824 | 43.8 vs 44.5 | -0.6 / -0.6 | -0.92 (-2.2) / -0.41 (-0.7) | 19.2 vs 19.9 | No effect | 98% |
| Price action | 52-week-high breakout on volume, last 5 sessions | − | 16,953 / 6,396 | 47.2 vs 43.5 | +5.0 / +1.6 | +2.46 (3.9) / +0.44 (0.4) | 20.9 vs 19.9 | No effect | 100% |
| Price action | Burst: day ≥ +4% on higher volume, last 5 sessions | − | 48,834 / 23,386 | 43.0 vs 43.9 | -1.5 / -2.0 | +0.02 (0.1) / -0.41 (-0.8) | 24.2 vs 19.9 | No effect | 62% |
| Price action | RSI(2) < 5 above the 200-day average | + | 6,951 / 3,160 | 46.0 vs 44.1 | +2.5 / +1.9 | +0.60 (1.1) / -0.25 (-0.3) | 19.2 vs 19.9 | No effect | 73% |
| Price action | RSI(2) < 5 in a momentum leader | + | 2,778 / 1,460 | 49.2 vs 44.7 | +5.1 / +4.2 | +1.55 (2.2) / +0.30 (0.3) | 19.1 vs 19.9 | No effect | 95% |
| Reversal | 5-day return, bottom decile | + | 22,308 / 10,689 | 43.4 vs 44.3 | -1.3 / -0.5 | -0.74 (-2.5) / +0.02 (0.1) | 22.8 vs 19.9 | Unstable | 95% |
| Reversal | 5-day bottom decile on below-normal volume | + | 12,879 / 6,544 | 43.1 vs 44.1 | -1.3 / -0.6 | -0.67 (-1.5) / +0.15 (0.4) | 23.2 vs 19.9 | No effect | 74% |
| Reversal | 20-day return, bottom decile | + | 22,311 / 10,691 | 41.9 vs 44.3 | -2.8 / -0.7 | -1.49 (-3.2) / -0.06 (-0.1) | 23.2 vs 19.9 | No effect | 99% |
| Results & corporate | Strong bad results (≤ −5% vs market), last 60 sessions | − | 7,952 / 5,114 | 43.9 vs 44.2 | -0.5 / +0.9 | -0.16 (-0.2) / -0.40 (-0.7) | 21.0 vs 18.3 | No effect | 74% |
| Results & corporate | Strong good results (≥ +5%), last 60 sessions | + | 8,880 / 5,637 | 47.4 vs 44.3 | +2.4 / +3.3 | +1.04 (1.8) / +1.58 (1.8) | 17.4 vs 18.3 | No effect | 99% |
| Results & corporate | Any results, last 20 sessions | 0 | 51,842 / 18,681 | 45.5 vs 45.4 | +0.4 / -2.4 | +0.01 (0.0) / -0.17 (-0.3) | 18.0 vs 18.5 | No effect | 55% |
| Results & corporate | Split / bonus ex-date, last 20 sessions | − | 1,156 / 625 | 44.1 vs 44.3 | -0.2 / +0.5 | -0.46 (-0.5) / +1.48 (0.9) | 21.8 vs 19.9 | No effect | 53% |
| Flows | Non-institutional bulk-deal net buy, last 20 sessions | − | 3,019 / 2,787 | 41.8 vs 42.5 | -1.4 / +1.8 | -0.22 (-0.2) / +0.19 (0.2) | 26.8 vs 19.9 | No effect | 50% |
| Flows | MF / insurer bulk-deal net buy, last 20 sessions | + | 416 / 703 | 47.9 vs 42.6 | -0.2 / +6.1 | +0.73 (0.3) / +2.77 (1.8) | 16.3 vs 19.9 | No effect | 84% |
| Flows | Non-institutional bulk-deal net sell, last 20 sessions | 0 | 3,436 / 3,542 | 43.8 vs 42.5 | +1.5 / +2.2 | +0.20 (0.2) / +0.97 (0.9) | 23.3 vs 19.9 | No effect | 74% |
| Flows | Fresh insider buy (≥ ₹10 lakh), last 21 sessions | + | 647 / 327 | 47.9 vs 44.3 | +3.2 / +1.0 | +2.46 (2.0) / -0.47 (-0.2) | 15.4 vs 17.6 | Unstable | 87% |
| Flows | Insider sale (≥ ₹10 lakh), last 63 sessions | 0 | 5,528 / 1,938 | 45.1 vs 44.6 | -3.1 / +7.2 | -1.75 (-3.8) / +0.65 (0.8) | 15.5 vs 17.7 | Unstable | 100% |
| Flows | F&O long build-up (5d price > +3%, OI > +10%) | 0 | 1,885 / 925 | 40.7 vs 42.1 | -1.7 / -0.1 | -0.60 (-0.8) / -0.08 (-0.1) | 18.5 vs 16.0 | No effect | 73% |
| Flows | F&O short build-up (5d price < −3%, OI > +10%) | 0 | 1,877 / 1,368 | 43.6 vs 43.0 | +0.6 / -0.9 | +0.04 (0.1) / -0.08 (-0.1) | 14.9 vs 15.7 | No effect | 51% |
| Flows | Put/call OI ratio, top quintile of F&O stocks | + | 7,546 / 5,337 | 44.8 vs 43.1 | +1.1 / +2.1 | +0.47 (1.2) / +0.72 (1.9) | 14.9 vs 15.5 | No effect | 98% |
| Flows | Near 52w high + MTF growth top decile | − | 1,401 / 2,070 | 45.8 vs 46.4 | +1.2 / -0.8 | +1.73 (1.9) / -0.15 (-0.2) | 22.0 vs 19.4 | No effect | 80% |
| Flows | Shareholding accumulation filed, last 20 sessions | + | 1,128 / 1,774 | 55.0 vs 50.2 | +4.0 / +2.0 | -0.81 (-0.6) / -0.47 (-0.5) | 12.1 vs 13.5 | No effect | 72% |

## Conditional probabilities: Desk top 300, 20 sessions

P(beat) = share of flagged stocks that beat the universe's average over the next 20 sessions (entry next open), vs all covered stocks the same weeks. Lift and mean excess: weekly difference, flagged minus covered (Newey-West t). P(bottom 20%) = share that landed in the worst fifth (20% by construction for the covered set). Credibility: empirical-Bayes P(the effect has this sign).

| Family | Condition | Exp. | Events pre / 2024+ | P(beat) % flagged vs base | Lift pp pre / 2024+ | Mean excess % (t) pre / 2024+ | P(bottom 20%) flagged vs base | Verdict | Credibility |
|---|---|---|---|---|---|---|---|---|---|
| Momentum & trend | Momentum score, top decile | + | 15,627 / 5,260 | 51.1 vs 46.4 | +5.3 / +2.6 | +1.46 (5.8) / +0.55 (1.3) | 20.9 vs 19.7 | Holds (weaker) | 100% |
| Momentum & trend | Momentum score, bottom decile | − | 17,447 / 3,280 | 43.5 vs 46.5 | -2.7 / -3.7 | -0.45 (-1.7) / -0.58 (-1.7) | 22.3 vs 19.7 | No effect | 98% |
| Momentum & trend | Close below its 200-day average | − | 85,461 / 16,650 | 45.4 vs 47.1 | -3.1 / -2.5 | -0.63 (-4.6) / -0.48 (-2.1) | 20.6 vs 19.9 | Robust | 100% |
| Momentum & trend | Within 5% of the 52-week high | + | 39,517 / 9,424 | 49.5 vs 45.7 | +2.5 / +2.2 | +0.46 (2.1) / +0.11 (0.3) | 17.8 vs 20.0 | No effect | 96% |
| Momentum & trend | Within 10% of the 52-week low | − | 31,783 / 6,194 | 46.2 vs 47.6 | -2.9 / -1.2 | -0.72 (-3.3) / -0.33 (-1.0) | 19.4 vs 19.9 | No effect | 100% |
| Risk | 60-day volatility, top decile | − | 12,560 / 2,355 | 42.1 vs 46.8 | -5.1 / -1.7 | -0.92 (-2.7) / +0.50 (0.7) | 32.8 vs 19.7 | Unstable | 95% |
| Risk | Beta, top decile | − | 17,025 / 3,909 | 43.0 vs 46.3 | -3.5 / -3.7 | -0.33 (-0.8) / -0.28 (-0.4) | 28.0 vs 19.8 | No effect | 75% |
| Risk | Biggest 1-day gain in 20 days, top decile | − | 12,393 / 2,080 | 44.4 vs 46.9 | -2.3 / -0.6 | -0.14 (-0.6) / +1.03 (1.7) | 27.5 vs 19.7 | No effect | 55% |
| Risk | Amihud illiquidity, top decile | 0 | 6,703 / 3 | 45.7 vs 48.0 | -4.3 / -44.8 | -0.96 (-1.8) / -3.98 (—) | 25.6 vs 19.4 | too little data | 86% |
| Volume & attention | Abnormal volume (5d vs 60d), top decile | − | 14,601 / 2,893 | 46.4 vs 46.7 | -0.3 / -0.4 | -0.06 (-0.4) / +0.17 (0.6) | 22.0 vs 19.7 | No effect | 56% |
| Volume & attention | 20-day overnight return, top decile | − | 12,667 / 2,101 | 44.9 vs 46.9 | -2.0 / -1.9 | -0.13 (-0.6) / +0.05 (0.1) | 25.3 vs 19.7 | No effect | 70% |
| Volume & attention | Delivery surge top decile + 20d return > 0 | 0 | 2,918 / 1,617 | 44.1 vs 44.8 | -1.2 / +0.5 | -0.22 (-0.6) / +0.33 (0.8) | 24.6 vs 20.0 | No effect | 50% |
| Price action | Upside value-area break, last 5 sessions | − | 30,992 / 6,080 | 46.0 vs 46.1 | -0.5 / +0.2 | -0.13 (-1.1) / +0.12 (0.5) | 20.9 vs 20.0 | No effect | 74% |
| Price action | Upside VA break on ≥ 2× volume | − | 13,787 / 2,472 | 44.5 vs 45.9 | -1.4 / -2.1 | -0.07 (-0.4) / +0.03 (0.1) | 22.9 vs 20.0 | No effect | 61% |
| Price action | Downside VA break on ≥ 2× volume | − | 4,543 / 1,147 | 47.6 vs 46.9 | +0.6 / +0.7 | -0.06 (-0.3) / +0.12 (0.3) | 19.4 vs 20.0 | No effect | 52% |
| Price action | 52-week-high breakout on volume, last 5 sessions | − | 10,690 / 2,350 | 48.3 vs 45.5 | +1.4 / +5.4 | +0.32 (1.2) / +0.74 (1.4) | 20.2 vs 20.0 | No effect | 92% |
| Price action | Burst: day ≥ +4% on higher volume, last 5 sessions | − | 38,386 / 6,719 | 44.3 vs 46.2 | -2.2 / -0.7 | -0.26 (-2.1) / +0.14 (0.5) | 24.8 vs 20.0 | Unstable | 95% |
| Price action | RSI(2) < 5 above the 200-day average | + | 5,800 / 1,358 | 48.9 vs 46.3 | +3.3 / +3.0 | +0.58 (1.8) / +0.16 (0.4) | 17.8 vs 20.0 | No effect | 92% |
| Price action | RSI(2) < 5 in a momentum leader | + | 2,029 / 675 | 52.7 vs 46.9 | +6.7 / +3.9 | +1.57 (4.2) / +0.51 (0.9) | 16.6 vs 19.7 | No effect | 100% |
| Reversal | 5-day return, bottom decile | + | 15,555 / 3,417 | 46.8 vs 46.6 | -0.0 / +1.5 | -0.02 (-0.2) / +0.22 (1.0) | 22.0 vs 19.7 | No effect | 65% |
| Reversal | 5-day bottom decile on below-normal volume | + | 8,556 / 1,888 | 46.0 vs 46.4 | -0.6 / +1.6 | +0.00 (0.0) / +0.13 (0.5) | 23.0 vs 19.8 | No effect | 60% |
| Reversal | 20-day return, bottom decile | + | 16,849 / 3,606 | 45.7 vs 46.5 | -0.9 / +0.1 | -0.20 (-0.8) / -0.02 (-0.1) | 22.0 vs 19.7 | No effect | 74% |
| Results & corporate | Strong bad results (≤ −5% vs market), last 60 sessions | − | 6,966 / 3,347 | 45.7 vs 46.3 | -0.9 / +0.7 | -0.02 (-0.0) / +0.11 (0.4) | 21.3 vs 19.3 | No effect | 59% |
| Results & corporate | Strong good results (≥ +5%), last 60 sessions | + | 7,736 / 3,642 | 48.8 vs 46.2 | +2.2 / +3.9 | +0.22 (0.8) / +0.89 (3.7) | 20.3 vs 19.4 | No effect | 100% |
| Results & corporate | Any results, last 20 sessions | 0 | 46,083 / 12,577 | 47.3 vs 46.6 | +1.4 / -1.3 | +0.01 (0.1) / -0.30 (-1.6) | 18.1 vs 19.3 | No effect | 86% |
| Results & corporate | Split / bonus ex-date, last 20 sessions | − | 964 / 241 | 45.4 vs 46.3 | -0.8 / +1.1 | -0.71 (-1.4) / +1.09 (0.7) | 23.1 vs 20.0 | No effect | 77% |
| Flows | Non-institutional bulk-deal net buy, last 20 sessions | − | 1,367 / 583 | 41.1 vs 44.7 | -6.8 / -3.5 | -1.35 (-1.4) / +0.15 (0.2) | 27.2 vs 20.0 | No effect | 66% |
| Flows | MF / insurer bulk-deal net buy, last 20 sessions | + | 189 / 176 | 52.3 vs 44.9 | -3.7 / +13.1 | +0.04 (0.0) / +2.99 (2.2) | 20.5 vs 20.0 | No effect | 72% |
| Flows | Non-institutional bulk-deal net sell, last 20 sessions | 0 | 1,580 / 962 | 44.8 vs 45.1 | -0.3 / +0.7 | +0.39 (0.4) / +0.03 (0.1) | 22.7 vs 20.0 | No effect | 56% |
| Flows | Fresh insider buy (≥ ₹10 lakh), last 21 sessions | + | 595 / 171 | 50.3 vs 46.1 | +2.3 / +1.1 | +0.98 (1.4) / -0.52 (-0.5) | 17.4 vs 18.6 | No effect | 69% |
| Flows | Insider sale (≥ ₹10 lakh), last 63 sessions | 0 | 5,131 / 1,532 | 45.0 vs 46.1 | -2.3 / +1.0 | -0.44 (-2.1) / -0.12 (-0.4) | 17.5 vs 18.3 | No effect | 96% |
| Flows | F&O long build-up (5d price > +3%, OI > +10%) | 0 | 1,883 / 911 | 44.1 vs 45.0 | -2.8 / +2.8 | -0.95 (-2.2) / +0.21 (0.5) | 21.1 vs 17.5 | Unstable | 84% |
| Flows | F&O short build-up (5d price < −3%, OI > +10%) | 0 | 1,867 / 1,409 | 46.9 vs 46.3 | +0.5 / +0.1 | +0.26 (0.9) / +0.10 (0.3) | 16.7 vs 17.5 | No effect | 78% |
| Flows | Put/call OI ratio, top quintile of F&O stocks | + | 7,535 / 5,588 | 46.6 vs 45.7 | +0.2 / +1.6 | +0.11 (0.7) / +0.33 (2.2) | 17.1 vs 17.4 | No effect | 98% |
| Flows | Near 52w high + MTF growth top decile | − | 475 / 650 | 47.8 vs 47.9 | -1.0 / +2.7 | -0.80 (-1.1) / +0.57 (1.4) | 18.8 vs 19.7 | No effect | 70% |
| Flows | Shareholding accumulation filed, last 20 sessions | + | 993 / 1,732 | 48.8 vs 48.0 | -9.7 / +6.5 | -2.20 (-2.6) / +0.41 (0.8) | 17.2 vs 17.0 | Unstable | 66% |
| ML | ML A2 score, bottom 30% of the top 300 | − | 51,611 / 12,595 | 42.9 vs 46.2 | -3.5 / -2.7 | -0.50 (-2.4) / -0.13 (-0.5) | 25.7 vs 20.0 | No effect | 98% |
| ML | ML A2 score, top decile of the top 300 | + | 17,787 / 4,340 | 51.1 vs 46.2 | +5.2 / +3.6 | +0.88 (4.0) / +0.44 (1.3) | 16.6 vs 20.0 | Holds (weaker) | 100% |

## Credibility as a forecast

Shrinkage fitted on pre-2024 data predicts whether each effect keeps its sign in 2024+; this is how often it did.

| Universe | h | Conditions | Predicted replication (mean) | Actual | Predicted ≥ 80%: actual | τ (spread of true effects, %) |
|---|---|---|---|---|---|---|
| L | 5 | 36 | 74% | 69% | 14: 93% | 0.202 |
| L | 20 | 36 | 73% | 61% | 12: 75% | 0.411 |
| L | 60 | 36 | 76% | 53% | 17: 59% | 0.995 |
| T | 5 | 38 | 73% | 68% | 10: 90% | 0.162 |
| T | 20 | 38 | 71% | 53% | 14: 71% | 0.403 |
| T | 60 | 38 | 75% | 55% | 15: 67% | 0.928 |

## Merge: walk-forward models (L, 20 sessions)

A = momentum percentile only · B = scorecard (shrunk naive Bayes) · C = L2 logistic on every flag + coverage flags + momentum. Rank IC of each model's P(win) (and −P(bottom)) against the 20-session excess, weekly.

| Model | Target | IC 2016–23 (t) | IC 2024+ (t) | IC all (t) |
|---|---|---|---|---|
| A | bot | 0.0181 (1.7) | 0.0075 (0.9) | 0.0154 (1.9) |
| A | win | 0.0356 (2.7) | 0.0353 (2.1) | 0.0355 (3.3) |
| B | bot | 0.0492 (4.0) | 0.0470 (3.1) | 0.0486 (4.8) |
| B | win | 0.0553 (4.2) | 0.0626 (3.5) | 0.0571 (5.2) |
| C | bot | 0.0601 (4.5) | 0.0801 (3.7) | 0.0651 (5.8) |
| C | win | 0.0637 (5.2) | 0.0923 (5.1) | 0.0709 (6.9) |

Paired weekly IC gain, C minus A:

| Target | Period | IC gain | t (NW) | Weeks |
|---|---|---|---|---|
| win | all | 0.0354 | 4.78 | 558 |
| win | 2024+ | 0.0570 | 3.70 | 140 |
| win | 2016–23 | 0.0281 | 3.44 | 418 |
| bot | all | 0.0497 | 5.01 | 558 |
| bot | 2024+ | 0.0726 | 3.19 | 140 |
| bot | 2016–23 | 0.0420 | 3.96 | 418 |

### Calibration (does a predicted 55% come true 55% of the time?)

| Target | Model | Period | Rows | Mean predicted % | Realised % | Slope | Brier skill |
|---|---|---|---|---|---|---|---|
| win | A | 2016–23 | 171,890 | 46.5 | 44.9 | 0.73 | +0.15% |
| win | A | 2024+ | 114,712 | 45.3 | 44.3 | 0.96 | +0.23% |
| win | B | 2016–23 | 171,890 | 45.3 | 44.9 | 0.52 | +0.13% |
| win | B | 2024+ | 114,712 | 43.2 | 44.3 | 0.66 | +0.18% |
| win | C | 2016–23 | 171,890 | 45.1 | 44.9 | 0.62 | +0.34% |
| win | C | 2024+ | 114,712 | 44.4 | 44.3 | 0.87 | +0.69% |
| bot | A | 2016–23 | 171,890 | 19.9 | 19.9 | 0.38 | -0.05% |
| bot | A | 2024+ | 114,712 | 19.9 | 19.9 | 0.48 | -0.00% |
| bot | B | 2016–23 | 171,890 | 28.3 | 19.9 | 0.40 | -6.32% |
| bot | B | 2024+ | 114,712 | 29.0 | 19.9 | 0.38 | -7.44% |
| bot | C | 2016–23 | 171,890 | 19.9 | 19.9 | 0.84 | +1.58% |
| bot | C | 2024+ | 114,712 | 20.2 | 19.9 | 0.88 | +1.85% |

Model C, P(win), 2024+, by predicted decile:

| Decile | Predicted % | Realised % | Rows |
|---|---|---|---|
| 1 | 37.1 | 37.4 | 11,472 |
| 2 | 39.9 | 39.4 | 11,471 |
| 3 | 41.2 | 41.8 | 11,471 |
| 4 | 42.3 | 41.4 | 11,471 |
| 5 | 43.4 | 43.8 | 11,471 |
| 6 | 44.6 | 45.1 | 11,471 |
| 7 | 45.9 | 47.5 | 11,471 |
| 8 | 47.5 | 46.7 | 11,471 |
| 9 | 49.5 | 48.7 | 11,471 |
| 10 | 53.0 | 51.0 | 11,472 |

Model C, P(bottom 20%), 2024+, by predicted decile:

| Decile | Predicted % | Realised % | Rows |
|---|---|---|---|
| 1 | 12.2 | 13.5 | 11,472 |
| 2 | 13.9 | 13.5 | 11,471 |
| 3 | 16.0 | 16.5 | 11,471 |
| 4 | 17.7 | 18.0 | 11,471 |
| 5 | 18.8 | 18.6 | 11,471 |
| 6 | 19.8 | 18.8 | 11,471 |
| 7 | 21.0 | 20.8 | 11,471 |
| 8 | 22.9 | 22.2 | 11,471 |
| 9 | 25.8 | 25.5 | 11,471 |
| 10 | 34.1 | 32.1 | 11,472 |

### Decision buckets (out of sample)

BUY = P(win) in the top 10% of that year's training predictions and not AVOID; AVOID = P(bottom) in the top 20%. Excess vs the liquid universe over 20 sessions; raw = the stock's own return; after cost = raw − round trip.

| Model | Period | Bucket | Share % | Rows | P(beat) % | Excess % | Bottom 20% % | Top 20% % | Raw % | After cost % | P(profit after cost) % |
|---|---|---|---|---|---|---|---|---|---|---|---|
| B | 2016–23 | AVOID | 20.7 | 35,575 | 41.9 | -0.26 | 28.0 | 22.9 | +1.57 | +0.62 | 47.0 |
| B | 2016–23 | BUY | 9.1 | 15,666 | 48.6 | +0.79 | 17.9 | 22.5 | +2.65 | +1.69 | 53.3 |
| B | 2016–23 | NEUTRAL | 70.2 | 120,649 | 45.3 | -0.03 | 17.8 | 19.0 | +1.62 | +0.67 | 49.8 |
| B | 2024+ | AVOID | 21.3 | 24,415 | 42.2 | -0.14 | 27.8 | 22.8 | +0.88 | -0.07 | 43.1 |
| B | 2024+ | BUY | 8.4 | 9,638 | 49.3 | +0.61 | 18.3 | 23.2 | +1.48 | +0.52 | 48.8 |
| B | 2024+ | NEUTRAL | 70.3 | 80,659 | 44.3 | -0.03 | 17.8 | 18.8 | +0.99 | +0.03 | 45.0 |
| C | 2016–23 | AVOID | 21.9 | 37,620 | 41.3 | -0.45 | 27.9 | 22.2 | +1.48 | +0.52 | 46.6 |
| C | 2016–23 | BUY | 7.7 | 13,316 | 49.2 | +0.67 | 16.1 | 21.6 | +2.58 | +1.63 | 54.4 |
| C | 2016–23 | NEUTRAL | 70.4 | 120,954 | 45.6 | +0.06 | 17.8 | 19.3 | +1.68 | +0.72 | 49.9 |
| C | 2024+ | AVOID | 25.4 | 29,158 | 40.9 | -0.42 | 27.4 | 21.5 | +0.57 | -0.38 | 42.0 |
| C | 2024+ | BUY | 9.6 | 10,989 | 50.9 | +1.09 | 16.0 | 23.6 | +2.57 | +1.62 | 52.8 |
| C | 2024+ | NEUTRAL | 65.0 | 74,565 | 44.6 | +0.00 | 17.6 | 19.0 | +0.95 | -0.01 | 44.9 |

### Desk book test (top 300, monthly, net of ICICI costs at ₹25,000 a position, vs the universe)

| Book | Net excess %/yr 2016–23 | 2024+ | All | IR | Turnover | Costs %/yr | Months |
|---|---|---|---|---|---|---|---|
| Momentum (Desk) | +16.76 | -1.76 | +12.13 | 0.87 | 0.275 | 3.31 | 128 |
| Momentum + merged veto (C bottom 30%) | +14.75 | -3.31 | +10.24 | 0.75 | 0.279 | 3.36 | 128 |
| Momentum + ML A2 veto (bottom 30%) | +18.21 | +1.29 | +13.98 | 1.03 | 0.280 | 3.36 | 128 |
| Merged P(win) ranking (C) | +2.82 | +2.09 | +2.64 | 0.22 | 0.431 | 5.18 | 128 |

## Market regime (is it a good time to own stocks at all?)

Basket = equal-weight liquid universe, next open → 20 sessions. Single stock = share of stocks whose own 20-session return beat the round-trip cost.

| Period | State | Weeks | P(basket up) % | Basket 20d % | P(NIFTY up) % | NIFTY 20d % | P(stock profit after cost) % |
|---|---|---|---|---|---|---|---|
| 2011–23 | NIFTY below 200-DMA | 181 | 66.3 | +2.18 | 65.2 | +1.87 | 53.6 |
| 2011–23 | NIFTY above 200-DMA | 496 | 60.9 | +0.91 | 58.3 | +0.64 | 46.4 |
| 2011–23 | breadth Q1 | 111 | 60.4 | +2.72 | 64.0 | +2.18 | 55.0 |
| 2011–23 | breadth Q2 | 130 | 56.9 | +0.33 | 56.2 | +0.62 | 46.3 |
| 2011–23 | breadth Q3 | 142 | 62.7 | +0.71 | 60.6 | +0.55 | 47.3 |
| 2011–23 | breadth Q4 | 133 | 57.9 | +0.43 | 54.1 | +0.32 | 43.9 |
| 2011–23 | breadth Q5 | 161 | 71.4 | +2.13 | 65.2 | +1.33 | 49.9 |
| 2024+ | NIFTY below 200-DMA | 49 | 67.3 | +2.44 | 57.1 | +0.59 | 51.3 |
| 2024+ | NIFTY above 200-DMA | 91 | 51.6 | +0.24 | 59.3 | +0.17 | 41.7 |
| 2024+ | breadth Q1 | 22 | 68.2 | +3.06 | 54.5 | +1.25 | 55.5 |
| 2024+ | breadth Q2 | 38 | 47.4 | -0.48 | 57.9 | -0.42 | 39.9 |
| 2024+ | breadth Q3 | 35 | 48.6 | -0.00 | 51.4 | -0.19 | 40.2 |
| 2024+ | breadth Q4 | 26 | 73.1 | +2.64 | 76.9 | +1.40 | 50.8 |
| 2024+ | breadth Q5 | 19 | 57.9 | +1.25 | 52.6 | +0.19 | 44.0 |

## Labels: what a model should learn from

### The label itself, by horizon (liquid universe, weekly, 2011+)

| h | Rows | Market share of variance % | P(raw > 0) % | P(raw > cost) % | P(beat universe) % | Inside ±cost dead zone % | 'Beat' labels that lose money % | Mean |excess| % | Week-to-week persistence | Ternary +/0/− % |
|---|---|---|---|---|---|---|---|---|---|---|
| 5 | 344,851 | 26.2 | 49.5 | 41.4 | 45.4 | 18.9 | 25.9 | 3.72 | 0.01 | 36 / 19 / 45 |
| 10 | 343,910 | 26.1 | 50.4 | 44.5 | 45.3 | 13.3 | 22.8 | 5.25 | 0.47 | 39 / 13 / 48 |
| 20 | 341,115 | 25.7 | 51.4 | 47.4 | 45.1 | 9.2 | 19.7 | 7.53 | 0.71 | 41 / 9 / 50 |
| 60 | 333,680 | 24.1 | 53.1 | 50.8 | 44.3 | 5.0 | 16.4 | 13.65 | 0.90 | 42 / 5 / 53 |
| 120 | 322,784 | 23.4 | 54.1 | 52.6 | 43.3 | 3.3 | 14.2 | 20.48 | 0.95 | 42 / 3 / 55 |

### Which horizon carries information (rank IC of fixed signals vs the excess label; t)

| Signal | h=5 | h=10 | h=20 | h=60 | h=120 |
|---|---|---|---|---|---|
| 20d reversal (−ret20) | 0.0129 (2.7) | 0.0073 (1.2) | 0.0034 (0.4) | -0.0162 (-1.8) | -0.0308 (-3.4) |
| 5d reversal (−ret5) | 0.0333 (7.2) | 0.0214 (4.6) | 0.0133 (2.7) | -0.0054 (-1.1) | -0.0153 (-3.0) |
| low volatility (−vol60) | 0.0412 (5.8) | 0.0454 (5.0) | 0.0499 (4.2) | 0.0707 (3.7) | 0.0830 (3.0) |
| merged P(win), model C (OOS) | — | — | 0.0709 (6.9) | — | — |
| momentum (+) | 0.0234 (3.9) | 0.0352 (4.4) | 0.0473 (4.5) | 0.0743 (4.7) | 0.0998 (4.5) |
| near 52w high (c/high) | 0.0258 (3.6) | 0.0383 (4.1) | 0.0522 (4.1) | 0.0865 (4.7) | 0.1151 (4.8) |

### Can the horizon pay its costs? Momentum top decile held h sessions, non-overlapping rebalances

| h | Rebalances | Top-decile excess %/yr (gross) | Turnover | Costs %/yr | Net %/yr | Bottom decile %/yr |
|---|---|---|---|---|---|---|
| 5 | 819 | +15.5 | 0.19 | 9.3 | +6.2 | -5.3 |
| 10 | 409 | +16.5 | 0.27 | 6.6 | +10.0 | -7.7 |
| 20 | 204 | +15.8 | 0.38 | 4.7 | +11.1 | -8.2 |
| 60 | 67 | +15.2 | 0.62 | 2.6 | +12.6 | -8.5 |
| 120 | 33 | +12.0 | 0.79 | 1.6 | +10.4 | -8.0 |

### Relative triple-barrier labels (±1·σ√h on the stock-vs-universe line)

| h | Up % | Neither % | Down % | Median days to touch | Agrees with excess sign % | Momentum IC vs barrier label (t) | Momentum IC vs plain excess (t) |
|---|---|---|---|---|---|---|---|
| 5 | 19.4 | 64.3 | 16.4 | 3 | 95.4 | 0.0235 (4.6) | 0.0228 (3.8) |
| 20 | 24.3 | 55.6 | 20.1 | 11 | 93.7 | 0.0448 (4.9) | 0.0468 (4.4) |
| 60 | 27.2 | 50.3 | 22.5 | 31 | 92.6 | 0.0808 (6.3) | 0.0741 (4.6) |

## Today's readings (research only: not a trading signal, nothing changes in the Desk)

Final model C fitted on everything labelled up to 2026-10-13 minus 21 sessions. BUY / AVOID thresholds = top 10% / top 20% of its training predictions.

**Highest P(beat), not AVOID**

| Symbol | P(beat) % | P(bottom 20%) % | Call | Momentum pct | Flags on |  |
|---|---|---|---|---|---|---|
| NEULANDLAB | 57.5 | 13.7 | BUY | 77 | rsi2_pullback, rsi2_leader, loser_5d, quiet_loser_5d, loser_20d, results_strong_up |  |
| NAVINFLUOR | 57.3 | 13.2 | BUY | 89 | near_52w_high, results_strong_up |  |
| LAURUSLABS | 57.3 | 13.2 | BUY | 99 | mom_top10, near_52w_high, results_strong_up |  |
| SHILPAMED | 57.2 | 15.2 | BUY | 99 | mom_top10, rsi2_pullback, rsi2_leader, loser_5d, quiet_loser_5d |  |
| GLAND | 56.7 | 16.8 | BUY | 95 | mom_top10, near_52w_high, breakout_52w, burst, results_strong_up |  |
| FINCABLES | 56.6 | 15.2 | BUY | 92 | mom_top10, near_52w_high, va_up_break, results_strong_up |  |
| TFCILTD | 56.3 | 17.7 | BUY | 97 | mom_top10, near_52w_high, va_up_break, burst, bulk_other_sell |  |
| SYRMA | 56.1 | 14.6 | BUY | 97 | mom_top10, near_52w_high |  |
| REDINGTON | 55.7 | 14.4 | BUY | 88 | results_strong_up |  |
| APARINDS | 55.5 | 14.7 | BUY | 91 | mom_top10, near_52w_high |  |
| DIVISLAB | 55.5 | 12.8 | BUY | 97 | mom_top10, near_52w_high, results_strong_up, insider_sale |  |
| ATHERENERG | 54.7 | 16.0 | BUY | 95 | mom_top10, results_strong_up, fo_long_buildup |  |
| PAISALO | 54.7 | 19.0 | BUY | 98 | mom_top10, bulk_other_buy, insider_fresh_buy |  |
| SANSERA | 54.5 | 16.7 | BUY | 99 | mom_top10 |  |
| CUPID | 54.5 | 17.0 | BUY | 100 | mom_top10, near_52w_high, breakout_52w, burst |  |
| BHEL | 54.4 | 14.8 | BUY | 92 | mom_top10, near_52w_high, abnormal_volume, delivery_surge_up |  |
| AZAD | 54.3 | 16.5 | BUY | 92 | mom_top10, near_52w_high, overnight_mom |  |
| KTKBANK | 54.0 | 15.4 | BUY | 92 | mom_top10, near_52w_high, va_up_break |  |
| RADICO | 53.9 | 13.5 | BUY | 93 | mom_top10, near_52w_high |  |
| M&MFIN | 53.8 | 14.5 | BUY | 54 | below_200dma, results_strong_up |  |
| MOTHERSON | 53.3 | 13.3 | BUY | 82 | results_strong_up |  |
| RRKABEL | 53.2 | 16.1 | BUY | 97 | mom_top10 |  |
| COFORGE | 53.2 | 15.3 | BUY | 82 | near_52w_high, va_up_break, burst, results_strong_up |  |
| KIRLOSENG | 53.0 | 18.2 | BUY | 92 | mom_top10, lottery_max |  |
| AEGISLOG | 52.9 | 20.0 | BUY | 96 | mom_top10, burst |  |

**Highest P(bottom 20%)**

| Symbol | P(beat) % | P(bottom 20%) % | Call | Momentum pct | Flags on |  |
|---|---|---|---|---|---|---|
| AHCL | 30.5 | 50.0 | AVOID | 7 | mom_bot10, below_200dma, high_vol, lottery_max, illiquid, overnight_mom, delivery_surge_up, burst, bulk_other_buy |  |
| UTTAMSUGAR | 36.0 | 47.9 | AVOID | 81 | near_52w_high, high_vol, lottery_max, illiquid, abnormal_volume, overnight_mom, delivery_surge_up, va_up_break, va_up_break_hivol, breakout_52w, burst, bulk_other_buy, mtf_surge_near_high |  |
| MOBIKWIK | 36.1 | 47.6 | AVOID | 56 | high_vol, high_beta, lottery_max, abnormal_volume, overnight_mom, delivery_surge_up, burst, bulk_other_buy, insider_fresh_buy |  |
| INDORAMA | 39.7 | 47.1 | AVOID | 94 | mom_top10, high_vol, high_beta, lottery_max, illiquid, overnight_mom, burst |  |
| PREMIERPOL | 38.9 | 43.9 | AVOID | 92 | mom_top10, near_52w_high, high_vol, lottery_max, illiquid, abnormal_volume, overnight_mom, delivery_surge_up, va_up_break, va_up_break_hivol, breakout_52w, burst, insider_sale, mtf_surge_near_high |  |
| SHRINGARMS | 37.1 | 41.9 | AVOID | 85 | near_52w_high, high_vol, high_beta, lottery_max, abnormal_volume, overnight_mom, delivery_surge_up, va_up_break, va_up_break_hivol, breakout_52w, burst |  |
| DPABHUSHAN | 39.8 | 41.7 | AVOID | 91 | mom_top10, near_52w_high, high_vol, lottery_max, illiquid, delivery_surge_up, va_up_break, va_up_break_hivol, breakout_52w, burst, mtf_surge_near_high |  |
| BIRLACABLE | 42.0 | 41.2 | AVOID | 98 | mom_top10, high_vol, illiquid, overnight_mom, burst |  |
| SYNCOMF | 38.0 | 40.9 | AVOID | 82 | high_vol, lottery_max, illiquid, overnight_mom, delivery_surge_up, burst |  |
| SHANTIGOLD | 39.3 | 40.3 | AVOID | 95 | mom_top10, near_52w_high, high_vol, lottery_max, abnormal_volume, overnight_mom, breakout_52w, burst, bulk_other_buy |  |
| AEROENTER | 40.4 | 40.2 | AVOID | 80 | high_vol, high_beta, lottery_max, illiquid, burst, insider_fresh_buy |  |
| MANINDS | 39.3 | 39.5 | AVOID | 93 | mom_top10, high_vol, high_beta, lottery_max, overnight_mom |  |
| INDIAGLYCO | 39.1 | 39.0 | AVOID | 93 | mom_top10, high_vol, lottery_max, illiquid, abnormal_volume, va_up_break, va_up_break_hivol, breakout_52w, burst |  |
| MARINE | 44.0 | 38.9 | AVOID | 98 | mom_top10, near_52w_high, high_vol, high_beta, lottery_max, bulk_other_buy, bulk_other_sell, mtf_surge_near_high |  |
| BHAGERIA | 44.8 | 38.8 | AVOID | 97 | mom_top10, near_52w_high, high_vol, lottery_max, illiquid, overnight_mom, mtf_surge_near_high |  |
| RSYSTEMS | 35.7 | 38.6 | AVOID | 30 | below_200dma, high_vol, lottery_max, illiquid, abnormal_volume, delivery_surge_up, burst |  |
| DMCC | 37.9 | 38.3 | AVOID | 72 | near_52w_high, high_vol, lottery_max, illiquid, abnormal_volume, overnight_mom, delivery_surge_up, breakout_52w, burst |  |
| INOXGREEN | 37.8 | 38.2 | AVOID | 14 | below_200dma, near_52w_low, high_vol, high_beta, lottery_max, abnormal_volume, burst, loser_5d, loser_20d, bulk_other_sell |  |
| VINDHYATEL | 40.3 | 38.1 | AVOID | 95 | mom_top10, near_52w_high, high_vol, high_beta, lottery_max, breakout_52w, burst |  |
| AVADHSUGAR | 40.7 | 37.8 | AVOID | 98 | mom_top10, near_52w_high, high_vol, lottery_max, illiquid, overnight_mom, breakout_52w, burst |  |
| BLUSPRING | 40.3 | 37.6 | AVOID | 96 | mom_top10, near_52w_high, high_vol, illiquid, abnormal_volume, overnight_mom, va_up_break, va_up_break_hivol, breakout_52w, burst |  |
| MACPOWER | 42.3 | 37.5 | AVOID | 95 | mom_top10, high_vol, lottery_max, illiquid, overnight_mom, loser_5d, quiet_loser_5d |  |
| CHEMPLASTS | 34.9 | 37.4 | AVOID | 20 | below_200dma, high_vol, lottery_max, illiquid, abnormal_volume, delivery_surge_up, burst |  |
| MVGJL | 36.5 | 37.0 | AVOID | 64 | high_vol, illiquid, overnight_mom, burst |  |
| AEROFLEX | 44.0 | 36.8 | AVOID | 97 | mom_top10, near_52w_high, high_vol, high_beta, abnormal_volume, va_up_break, va_up_break_hivol, burst, results_strong_up |  |

**Your holdings**

| Symbol | P(beat) % | P(bottom 20%) % | Call | Momentum pct | Flags on |  |
|---|---|---|---|---|---|---|
| AEROFLEX | 44.0 | 36.8 | AVOID | 97 | mom_top10, near_52w_high, high_vol, high_beta, abnormal_volume, va_up_break, va_up_break_hivol, burst, results_strong_up |  |
| CUPID | 54.5 | 17.0 | BUY | 100 | mom_top10, near_52w_high, breakout_52w, burst |  |
| PCJEWELLER | 44.1 | 29.1 | AVOID | 73 | high_vol, abnormal_volume, overnight_mom, delivery_surge_up, breakout_52w, burst | outside L |
| SYNCOMF | 38.0 | 40.9 | AVOID | 82 | high_vol, lottery_max, illiquid, overnight_mom, delivery_surge_up, burst |  |


---
name: empirical-findings
description: Measured conditional-return diagnostics from market.duckdb that ground each Phase-1 alpha hypothesis
metadata:
  type: project
---

# Empirical edge diagnostics (liquid universe, ~939 tickers, since 2024 filter, adjusted returns)

**Why:** these measured numbers justify each hypothesis economically and give Agent 2 baselines. **How to apply:** if a future re-mine contradicts these, the edge has decayed — update here.

- **Baseline:** pooled lag-1 daily autocorr = **+0.038** (weak daily continuation, NOT reversal on average). Reversal lives in tails + specific conditions, not the mean.
- **Overreaction reversal:** fwd-5d return after z-scored daily return (20d window): z<-2.5 → **+0.78%** (53.5% win) vs mid bucket +0.20%. Extreme down days revert up.
- **Vol-regime gates reversal:** after -1.5z down day, reversal works ONLY in high-vol regime (sd20>long-run |r|): +0.57% (52.4% win) vs low-vol +0.03% (49% win).
- **Volume-shock = information filter (KEY):** big down move (r<-3%) WITHOUT >3x vol → +0.64% fwd5 (reverts up); WITH >3x vol → -0.19% (continues down, 45.5% win). Up moves same: no-vol-shock drifts +0.89%, vol-shock only +0.28%. Volume-confirmed = informational (no reversal); unconfirmed = liquidity noise (reversal).
- **Gaps:** fwd-3d: gap<-5% → +0.88% (53.7% win, gap-down reversal); gap>5% → +1.10% (53.4% win, gap-up continuation). Asymmetric.
- **Variance Ratio regime:** VR5<0.8 (mean-revert): mom5→fwd5 corr **-0.053** (down-mom reverts). VR5>1.2 up (trend): mom→fwd corr **+0.049** (continuation). Regime-conditional momentum/reversal switch.
- **Range contraction alone is NOT enough:** NR7 contraction did not raise |fwd5| move (0.041 vs 0.043). Need DIRECTIONAL breakout trigger, not just contraction.
- **Directional breakout:** close>20d-high → +0.50% fwd5; with prior contraction → 51.5% win. Add volume confirm for strength.
- **52-week-high anchoring (strong):** close within 2% of 252d high → +0.96% fwd10 (54% win) vs 75-90%-below-high +0.15%. Anchoring underreaction.
- **Market lead-lag:** corr(today stock r, yesterday equal-weight mkt r) = **+0.049** (laggard underreaction to prior-day market).

"""Narrative blocks for REPORT.md. Every number quoted here is taken from the tables generated in the same
report (results.json); figures are rounded as printed there."""

PROSE = {}

PROSE["HEADLINE_PROSE"] = """
**What the DEV evidence supports (and how strongly)**

1. **Horizon: hold 20 days.** Skill is highest at h=10 (phase-averaged DEV excess +23.8%/yr, t 4.79) but
   costs decide: DEV CAGR at 80 bps is 16.2% (h=10) vs 19.6% (h=15) vs 25.2% (h=20); at 130 bps 2.6% vs
   10.2% vs 17.7%. The training horizon barely matters: any of the three scores held 20 days earns
   +15.1..+18.1% DEV excess (t 3.3-4.0).
2. **Neutraliser: the per-date OLS residual on [shrunk beta, vol_20, log_turn20, mom_12_1] ("neumom")**
   beats neu, which beats size and none. Phase-averaged DEV t at h=20: 4.11 / 3.81 / 2.90 / 3.27; at h=10:
   4.90 (neumom) / 4.79 (neu) / 3.70 (none). Dropping beta/vol neutralisation is a cliff. It turns the 2026
   phase-averaged excess negative (none -7.7%, size -1.8%). It also restores the market-direction-dependent
   beta tilt (corr 0.60 with the window's market return vs 0.06 for neumom).
3. **Label form: continuous rank (RANK), 20/60/20 and top-30% binary are statistically tied on DEV.**
   With neumom the phase-averaged t values are 4.11 / 5.07 / 4.57, and the composite mean ranks are
   2.9 / 3.3 / 3.6. The 30/40/30 and 33/33/33 forms are slightly weaker (3.61 / 3.30 with neu). Rare or
   symmetric binary cuts fall off cliffs: T10 3.01, T20 3.39, T50 1.23. An explicit bottom-30% AVOID
   model fails as a long score (0.09) and as an avoid list. The pre-declared composite picks
   **neumom RANK**.
4. **The robust edge is still the avoid side.** Bottom-30% AUC is 0.548 (DEV) and 0.554 (2026) for
   neumom RANK, while top-30% AUC is only 0.517 and 0.508. Dropping the model's bottom 10-30% from an
   equal-weight book adds +1.7..+3.8%/yr on DEV (t 3.4-3.8). It adds +1.3..+1.8% in 2026 (t 1.0-1.8),
   with factor-adjusted alpha +2.5%/yr (t 3.73) in 2026.
5. **2026 holdout (never used to choose): positive but weak for the selected label.** Single-phase
   excess is +9.2% (t 1.54). The phase-averaged excess, which is phase-robust, is **+3.9%/yr (t 0.60)**.
   The default calendar phase happened to be the best of 5. Net CAGR was 13.9% phase-averaged vs a 10.2%
   random baseline and a Nifty 500 down 7.8%. The tail forms did better in 2026 (neumom T30 +11.6%,
   t 2.14). Most of that came from a high-vol loading in a high-vol momentum rally: neumom T30's 2026
   factor alpha is +1.8% (t 0.31).
6. **Statistics.** The best DEV t (4.25) clears the {NSPEC}-spec Bonferroni hurdle of {BONF_SPEC} and the
   hurdle of {BONF_ALL} that includes round 1, but not by much. Against a persistence-matched random null the model sits
   5.5 sd above the null mean on DEV. A constant per-stock random tilt can reach +19.5% DEV excess with
   NW t 3.9 (max of 40), so Newey-West t is NOT reliable for persistent tilts (Section 7).
"""

PROSE["EVENTS_PROSE"] = """
* **Rank labels make the event rate a design parameter, not a market outcome.** Every (h, neutraliser)
  has +1 = 30.0% in every year, regime and month (monthly std 0.0001). Correlation with the Nifty month is
  noise (-0.12..+0.04). The cut sets the rate exactly: 20%, 30% or 33%.
* **What does move when parameters change:**
  * **Liquidity mix.** "none" puts slightly fewer +1 in the illiquid tercile (28.8/30.7/30.7 at h=20).
    Neutralising on log_turn20 flattens this to 29.3-29.4 / 30.8-30.9 / 29.9-30.0.
  * **Sub-universes.** On fno_proxy names +1 is 29.3-30.5% but -1 is only 25.4-25.8%: large liquid names
    disperse less and sit in the middle class. A label defined on the full elig cross-section is therefore
    not 30/40/30 inside the F&O universe. On liq5, +1/-1 are 30.2-30.5% / 29.3-29.4%.
  * **Class churn from the neutraliser.** Versus neu, neumom changes 3.5-3.8% of class assignments, size
    8.1-8.4% and none 10.8-11.0%. The neutraliser explains 1.1-1.2% (size) to 4.2% (neumom) of the
    cross-sectional variance.
  * **Horizon.** Lag-1 label autocorrelation is 0.86 / 0.90 / 0.93 for h = 10 / 15 / 20 (window overlap).
    corr(pct_t, pct_t+h) is -0.016..+0.006, so successive non-overlapping labels are independent. There is
    no label-level momentum or reversal to exploit or to fear.
"""

PROSE["TILT_PROSE"] = """
* Without beta/vol neutralisation the label's composition follows the market. In up windows +1 names have
  higher beta (+0.09 z for none/size at h=20); in down windows they have lower beta (-0.23 z). The
  correlation with the window's market return is 0.60-0.67, and the same holds for vol (0.42-0.46). A model
  trained on such a label partly learns market timing. With neu/neumom the beta tilt is -0.04/-0.06 z in
  both states (corr 0.06-0.16) and the vol tilt correlation is 0.07-0.14.
* neu still embeds the realised 12-1 momentum premium: the mom_12_1 tilt is +0.067 z at h=20. neumom
  removes it (-0.021 z).
* Small static tilts remain after OLS (vol -0.09 z, size +0.08 z). Ranking residuals is non-linear:
  high-vol names have right-skewed residuals whose median sits below zero.
* Coherence (3b) shows that a relative +1 is not an absolute winner. P(net>0 | +1) is 89-92% overall but
  84-98% by year. In the worst month it falls to 37.9% (h=20), 46.2% (h=15) and 56.1% (h=10).
  Monthly P(net>0 | +1) correlates 0.42-0.64 with the Nifty month. P(net>0 | -1) is 2.9% in bull_up20
  windows vs 17.4% in bear_dn20 windows. The class is regime-free; its absolute payoff is not. Pair the
  label with a separate regime/exposure layer (R2_regime) if absolute drawdowns matter.
"""

PROSE["XS_PROSE"] = """
* **Learnability is stable and survives 2026.** On the common yardstick (rank IC vs the XR_neu h=20
  residual rank), neutralised (neu/neumom) RANK models have DEV IC 0.060-0.071 and 2026 IC 0.050-0.061. neumom RANK has
  the most reliable DEV IC (0.063, non-overlapping t 8.6; 2026 0.061). 2023 was the weak year
  (0.023-0.047).
* **Asymmetry persists in lab v2.** For RANK models, bottom-30% AUC is 0.538-0.557 on DEV (t 4.7-15.9)
  vs top-30% AUC of 0.516-0.521. In 2026 top-30% AUC is 0.49-0.51, a coin flip, while bottom-30% AUC is
  0.553-0.559. The precision table shows the same pattern. neumom RANK's top-20 picks land in +1
  30.1 / 37.2 / 36.7 / 33.5% of the time (2023/24/25/26, base 30%) and in -1 25.4-29.7%.
* **Binary tail labels learn dispersion, not direction.** T30 has the best top-30% AUC (0.542 DEV, 0.564
  2026) but a low IC (0.034), and its score is +0.31 correlated with vol_20. B30 has the best bottom-30%
  AUC (0.572) and a score -0.73 correlated with idio_vol_60. Its "avoid" list holds high-vol names that
  appear in both tails. That list earned +138 bps vs the universe's +84 bps in 2026, so avoiding it lost
  money. A high tail-class AUC is not a high expected-return rank.
"""

PROSE["INVEST_PROSE"] = """
* All neutralised RANK, 3-class and T30 models beat the horizon-matched random by +12.9..+19.1%/yr on DEV
  (K20, step 5, 50 bps; NW t 2.6-4.3), with every DEV year positive. The h=20 random baseline itself
  earned 11.8% on DEV, so it is the bar to beat, not zero.
* The DEV maxDD of the top books (-25.6..-32.8%) is similar to random (about -30%). A relative label
  improves returns, not absolute drawdowns.
* In 2026 the neutral RANK books were weakest (+3.3..+3.9% phase-averaged). The vol-loaded tail books
  were strongest (+8.9..+14.9%). none/size were negative (-7.7 / -1.8%), which reproduces the round-1
  finding that raw-return ranks lost their edge in 2026.
* Using B30 as a long score is worthless: +0.7% phase-averaged DEV excess, -15.2% in 2026.
"""

PROSE["SENS_PROSE"] = """
**Plateaus vs cliffs (DEV-based, 2026 for information)**

| parameter | robust plateau | cliff / fragile | evidence |
|---|---|---|---|
| horizon (net of cost) | h=20 (h=15 at 50 bps) | h=10 at >=80 bps | DEV CAGR 80bp 16.2/19.6/25.2%; 130bp 2.6/10.2/17.7% (h10/15/20) |
| training horizon | any of 10/15/20 when held 20d | - | held-20d DEV excess +18.1/+15.1/+18.0% (t 4.02/3.29/3.75) |
| neutraliser | neumom ~ neu | none / size (2026 negative) | phase-avg DEV t 4.11/3.81/3.27/2.90; 2026 +3.9/+3.3/-7.7/-1.8% |
| label form / rank cut | RANK, C20, T30 (C30/C33 slightly lower) | T50, T10, B30 | phase-avg DEV t (neu) RANK 3.81, C20 4.87, C30 3.61, C33 3.30, T30 4.26, T20 3.39, T10 3.01, T50 1.23, B30 0.09 |
| K (long book) | smooth slope 10..50, no cliff | - | neumom RANK DEV excess +32.1/+19.1/+16.9/+11.9% (t 4.95/4.25/4.18/3.66) for K=10/20/30/50; maxDD -25..-27% throughout |
| step | 5 ~ 10 after phase-averaging | single-phase step 10 | neu RANK K20 s10 2026 excess -12.4..+15.4% across 10 phases |
| liquidity tier | liq2 (more edge) | - | neumom RANK DEV excess +19.1% liq2 vs +14.3% liq5 (t 4.25 vs 3.28) |
| cost | excess vs random nearly cost-invariant | absolute CAGR | about -1.5%/yr per +10 bps at h=20 (about 12.6 round trips/yr) |
| avoid cut | drop worst 10-30% | - | neumom RANK DEV +1.7/+3.1/+3.8/+5.4% for 10/20/30/50% (t 3.6/3.8/3.4/3.2); 2026 t 1.84/1.23/1.02/0.96 |

The event rates of the book move with K and the cut. A K=20 book holds the top ~2% of about 1,050
names a day. The EW top-10% / top-20% / top-30% books earn +8.7 / +7.0 / +6.8% DEV excess (neumom RANK),
so the alpha decays smoothly with depth rather than collapsing.
"""

PROSE["LUCK_PROSE"] = """
* **iid random picker:** sd 1.9% CAGR on DEV and 4.7% over the 9.5-month 2026 (h=20). This is the band
  `S.compare` implicitly uses.
* **Constant per-stock random tilt (picks the same names repeatedly):** excess sd 6.7% DEV and 13.0% 2026.
  NW t sd is 1.37 / 1.54 instead of 1.0, and the max of 40 seeds is +19.5% (t 3.89) on DEV, the same size
  as the models. **Newey-West t overstates significance for persistent tilts.**
* **Persistence-matched null** (random scores with the model's own rank autocorrelation, lag-5 0.71,
  lag-250 0.20): NW t sd is 1.03-1.10, so it is calibrated for rotating scores like these. Every candidate
  sits 5.4-5.7 sd above its null on DEV. In 2026 neumom RANK is at the 98th percentile (z 2.2), neu RANK
  the 82nd (z 1.0), and C20 / T30 the 100th (z 2.5 / 4.0).
"""

PROSE["FACTOR_PROSE"] = """
* **Not a boring factor tilt on the long side.** neumom RANK's DEV alpha after six long-short factors
  (vol, 12-1 momentum, liquidity, 5d reversal, beta, distance to 200dma) is +17.4%/yr (t 3.99, R2 0.05).
  The best single-characteristic sort gets +11.5% (12-1 momentum, t 1.62). Low-vol, liquidity and
  reversal sorts lose to random on DEV. Tail-binary forms carry real factor exposure: T30 R2 0.30 (vol
  beta 0.47), T10 R2 0.39.
* **2026 was a factor storm.** Annualised long-short returns: momentum +26%, distance to 200dma +18%, vol
  +18%, beta +10%, liquidity -5%. The neutral scores are short trend (dist_sma200 beta -0.51 for neumom
  RANK, -0.74 for neu RANK) and long liquidity, so their raw 2026 excess (+8.9% neumom RANK) understates
  the factor-adjusted alpha (+11.6%, t 1.78).
* **The avoid side is partly replicable by a boring rule on DEV.** Dropping the worst 30% by 12-1
  momentum earns +3.7% (t 3.14), about the same as the model avoid overlays (+3.3..+3.8%, t 2.7-3.5). In
  2026 the momentum rule did better (+5.4%, t 2.07 vs +0.9..+1.8%). The model avoid overlays still carry
  significant factor-adjusted alpha in both periods (+2.5..+3.1%/yr, t 3.7-5.0 for neumom), so they are
  not just momentum. A momentum filter plus the model's avoid list is an obvious R2_alpha ensemble
  candidate.
"""

PROSE["SELECT_PROSE"] = """
**Holdout exam of the leading DEV candidates (2026 shown for information only; the choice was made
above on DEV):**

@@HOLDOUT_TABLE@@

* **Selected label (DEV): XR_neumom, h=20, continuous per-date residual rank (RANK)**, trained as a
  LightGBM regression on pct-0.5. 2026 net of 50 bps: 13.9% phase-averaged CAGR vs 10.2% random.
  Phase-averaged excess +3.9% (t 0.60), factor alpha +11.6% (t 1.78), 98th percentile of the
  persistence-matched null. That is a pass in sign and a weak pass in strength.
* **The top three DEV candidates (neumom RANK, neumom C20, neumom T30) are a statistical tie**: mean
  ranks 2.9 / 3.3 / 3.6, with DEV differences of under 1 t-unit. **What is robust is the neutraliser
  (neumom) and the horizon (20d), not the exact label form.** Do not read the 2026 ordering (T30 > C20 >
  RANK) as evidence for tail forms. It follows the high-vol rally and the T30 factor alpha is about 0.
* Recommended label stack from this study:
  1. **Primary selection label:** y = per-date percentile rank of the OLS residual of winsorised
     open[t+1]->close[t+20] on [0.5*clip(beta_60,0,3)+0.5, vol_20, log_turn20, mom_12_1] over elig_base. Train on
     the continuous rank. An equal-weight rank ensemble of RANK / C20 / T30 models trained on this same
     residual is the natural next step (R2_alpha).
  2. **Avoid label:** the bottom tail of the SAME score. Drop the worst 10-30%; the 10% cut was the most
     robust in 2026, t 1.84. Do NOT train a dedicated bottom-30% classifier (B30): it learns volatility.
  3. **Execution:** K=20 (10-30 is a plateau), 20-day hold, stagger entries daily or weekly (phase risk),
     liq2 universe, cost stress at 80 and 130 bps. Expect roughly random +4..+16%/yr (2026 to DEV) at
     about random-like drawdowns.
"""

PROSE["PROSCONS"] = """
**Pros (XR_neumom h=20 RANK)**
* The event rate is fixed by construction (30/40/30 or any chosen cut) in every year, regime and month,
  with no market encoding (corr with the Nifty month about 0).
* Its composition does not depend on market direction (beta-tilt corr 0.06). Its factor R2 is low (0.05)
  and its DEV factor-alpha t is near the top (3.99; neumom C20 4.02, neumom T30 4.15).
* It is the most reliably learnable of the h=20 models (DEV IC t 8.6 on the common yardstick), with no
  IC decay in 2026 (0.061).
* Every DEV year is positive (+18.3 / +35.8 / +5.9% vs random for 2023/24/25). It is robust to K 10-50,
  step 5/10, costs of 50-130 bps and liq5.
* It passes every bias check: next-open entry, NaN where undefined, CA-adjusted, segment/suspension
  guards, labels independent of eligibility filters, walk-forward OOS only, and selection on DEV only.

**Cons and failure modes**
* The 2026 edge is small once phase luck is removed (+3.9%/yr, t 0.60). The +9.2% single-phase figure is
  the luckiest of 5 calendar phases.
* Long-side skill is weak (2026 top-30% AUC 0.508). The book makes money mostly by not holding the
  losers.
* It is structurally short trend and long liquidity, so it lags in momentum/high-vol rallies such as
  2026, where vol-loaded tail forms and plain 12-1 momentum did much better.
* It does not reduce absolute drawdowns (DEV maxDD -25.6% vs random -30%). A +1 label still loses money
  in up to 62% of cases in a bad month (h=20).
* Capacity: median pick turnover is Rs 24 cr/day. At a Rs 25 cr book, 8.5% of tickets exceed 10% of ADV.
  The edge is larger in liq2 than in liq5.
* Multiple testing: {NSPEC} distinct DEV specs plus about 600 in round 1. The best DEV t (4.25) clears
  Bonferroni ({BONF_SPEC} / {BONF_ALL}) only narrowly, and the choice among the top-3 forms is at noise level.
* Shorts were not evaluated in round 2. Round 1 found single-stock F&O shorts lose; use -1 as avoid/exit
  only. On F&O names the -1 class is under-represented (25.5% vs 30%).
"""

PROSE["LABISSUES"] = """
1. **Calendar-phase sensitivity of single-run `S.compare` results.** The signal calendar trades only 1 of
   `step` possible phases. For neu RANK at K20 step 10, the 2026 excess ranges from -12.4% to +15.4%
   across the 10 phases, and the default phase is the best one. For the selected model at step 5 the
   default phase was also the best of 5 (+9.2% vs a phase-average of +3.9%). Recommendation: report the
   phase-averaged book (`s7_phase.py`) for every holdout claim. It is equivalent to daily-staggered entries.
2. **Newey-West t is miscalibrated for persistent tilts.** Constant per-stock random scores give NW t sd
   1.37 (DEV) and 1.54 (2026), with a max of 3.9 in 40 draws. Use a persistence-matched null
   (`s6b_matched_null.py`, sd 1.03-1.10) or block-bootstrap the excess before reading a t of 3 as
   significant.
3. **Round-trip cost on re-picked names.** `Sim` charges a full round trip on every name at every sleeve
   rebalance. For top-20 books the measured 20-day name retention is only 8-10%, so this is about right.
   For the avoid/EW books (70-100% of the universe) most names are retained in reality, so their absolute
   CAGRs are understated by up to about 6%/yr at 50 bps. Excess vs random-70% is unaffected because both
   legs pay.
4. **Score-NaN asymmetry in `Sim.run`.** The strategy draws from finite-score rows and the random
   baseline from all mask rows. This is harmless for `walk_forward2` scores (all elig rows scored). For
   characteristic sorts with NaN (mom_12_1 is NaN on 11.8% of elig rows, the young names) the baseline
   universe differs.
5. **`xs_metrics` has no down-side AUC.** The avoid side needs the score inverted and a bottom-class binary
   target (done here in `s4_xs.py`). Suggest adding `auc_down` to lablib.
6. **Sub-universe class shares.** A rank label built on the full elig cross-section is 29.5/45/25.5 inside
   fno_proxy, not 30/40/30. Re-rank inside the traded universe if the label is used as a target there.
7. **Survivorship conditioning of the ranking cross-section.** V_h needs a defined r_h, so 1.0% / 1.6% /
   2.1% of elig rows (h=10/15/20) that hit a suspension, segment break or label_block inside the window are
   NaN and excluded from that date's ranking. This is correct as a label. Sim handles these names with
   forced exits, so the investability numbers are not survivorship-biased.
"""

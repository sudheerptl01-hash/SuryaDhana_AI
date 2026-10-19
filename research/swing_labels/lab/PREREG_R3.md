# Round 3 pre-registration (written before any round-3 number was computed)

Frozen on 2026-10-15, before training the production ensemble.

## Frozen label
XR_neumom, h = 20, continuous residual rank (round-2 winner; reproduced bit-exact by the devil).
File: `results/R3_devil/label_h20_neumom.npz` (`pct` = label in (0,1], `r` = raw executable return,
`resid` = OLS residual). Reporting classes: +1 if pct > 0.7, -1 if pct <= 0.3, else 0.

## Frozen production score (PROD)
PROD = per-date mean of the cross-sectional percentile ranks (over elig_base rows with a finite
score) of 10 `L.walk_forward2` regression models on y = pct - 0.5, h = 20, mask = elig_base,
default parameters, random_state in {1,2,3,4,5} x date_offset in {0,1} (the two halves of the
training-date grid). File: `results/_lead/prod_h20.npz` (`prod`, `members`, `pct`).
Reason (decided before seeing results): the devil showed single models share only 63% of
their top-20 across seeds, so production must average model noise. The 3-seed ensemble and
the single model are reported alongside PROD for transparency; PROD is not swapped for
either of them on the basis of any result.

## Frozen book (baseline process)
Weekly signal (step 5), 4 staggered sleeves, top 20 per sleeve by PROD among elig_base, slot
sizing (1/20 of sleeve), entry next open, pure 20-day time exit, forced exit at the last valid
close on suspension/label_block. Costs 50 bps round trip central, 80 bps stress. Gross exposure
100%. Avoid list = bottom 30% of PROD on the signal date. No regime layer, no event sleeve.
Performance is always quoted phase-averaged over the 5 weekly entry phases (= a daily-staggered
book), against (a) the 5-seed horizon-matched random top-20 on the same mask and (b) the
equal-weight universe.

## Decision rules for round 3
* Selection uses DEV (2023-01-01 .. 2025-12-31) only. 2026-01-01 .. 2026-10-14 is reported, never
  used to choose. It is lightly contaminated (reported in rounds 1-2).
* Every add-on (exit rule, sizing rule, hedge, long/short, exposure rule) is tested as a
  pre-declared short list, written in ROUND3_BRIEF.md before running. An add-on is adopted only if
  its DEV phase-averaged gain over the frozen baseline has a paired NW t >= 2 and does not raise
  maxDD by more than 3 pp; otherwise the baseline stands.
* The clean exam is data after 2026-10-14 (forward protocol to be written by R3_exam).

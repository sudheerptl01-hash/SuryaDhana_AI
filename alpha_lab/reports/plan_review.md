# Red-team review of alpha_lab/PLAN.md (14 Oct 2026)

Reviewer: adversarial validator (fork). Static analysis only; no backtests run. Files read: PLAN.md, README.md,
lib/ (momentum, nse_panel, trading_costs, xs_labels), reports/evidence_probability/{PLAN,FINDINGS}.md,
reports/phase_b_extended/REPORT.md, reports/ml_labels/FINDINGS.md §5, reports/costs/CAPITAL_VIABILITY.md.
Benchmark facts pinned from market_index_daily (read-only snapshot): NIFTY 50 price CAGR **7.87%** and maxDD
**−26.2%** over 2011-01→2019-12; **9.55%** and **−38.4%** over 2020-01→2026-10-14; India VIX from 2009-09-22;
`fut_close` from **2019-10-01**; `nse_results.released_at` from 2007.

## Findings

**1. BLOCKER — Gate A barely discriminates for long-only breadth; "beats the market" is being tested against the
easiest benchmark on the shelf.** In 2020–26 the equal-weight liquid universe trounced NIFTY 50 (small/mid-cap
regime; the project's own studies show EW-universe 20-session means of +0.9–2.7% per week-state). A random
20-name book from universe T plausibly clears "NIFTY + 1.5 pts with IR ≥ 0.45" in this window. A pass would then
be sold as edge when it is beta to breadth.
*Smallest fix:* add Gate A criterion 1b: CAGR after costs > **equal-weight universe-T CAGR** over the same window
(and report EW-L for S3). Keep the NIFTY test too. Same addition to Gate B.

**2. BLOCKER — The dividend treatment makes criterion 1 arithmetically unfair.** The panel is price-only: the book
forgoes ~1.2–1.5%/yr of dividends it would actually receive, AND the gate then adds +1.5 pts to the (also
price-only) NIFTY. That double-penalises the strategy by ~2.7–3 pts. Either compare price-to-price with margin 0
(both sides ex-div, roughly cancelling), or credit the book a stated dividend proxy and keep the +1.5 on NIFTY.
*Smallest fix:* criterion 1 becomes "book price-CAGR > NIFTY price-CAGR + 0"; note the ~equal dividend yields as
the justification. Log the edit (it is a pre-run gate change, allowed now, not after numbers exist).

**3. BLOCKER — S3 futures variant is unimplementable at the stated capital.** Post-SEBI Nov-2024, one single-stock
futures lot is ₹15–20L notional. The spec says ₹10L book, 5 concurrent names at 20% (₹2L) each: that is 1/8th of
one lot. Margin-financed leverage (~8× on ₹10L to carry 5 lots) would be reckless and must not be smuggled in via
"MIS". Also `fut_close` exists only from 2019-10, so a futures variant can never run Gate B.
*Smallest fix:* re-spec S3-futures at **₹1 crore capital, exactly 1 lot per name, max 5 lots** (≈ ₹75–90L
exposure, SPAN+exposure margin ≈ ₹18–25L held in the liquid sleeve), Gate A only, Gate B = N/A (data), and say the
delivery variant alone carries Gate B. Report per-lot economics.

**4. BLOCKER — S1H/S2H hedge is lumpy and its margin has no funding source.** NIFTY futures lot ≈ 75 × ~22,600 ≈
**₹17L notional** against a ₹10L book: the hedge is 0% or ~170%. And in the hedged variant the equity stays fully
invested, so there is no cash to post ~12–15% margin — the spec funds margin "from the liquid sleeve" that the
100%-equity book does not have.
*Smallest fix:* hedged variants assume **₹50L book** with a permanent **85% equity / 15% liquid sleeve**; hedge =
nearest whole lot to equity value (report residual net exposure per month); margin sits inside the 15% sleeve.
Pre-2019-10 basis-zero proxying stays flagged.

**5. BLOCKER — Gate A criterion 4 (≥ 30 decisions) is impossible for S2 as scheduled.** 12-week cadence over
2020-01→2026-10 gives ~29 rebalances; S2 fails the gate by construction regardless of merit.
*Smallest fix:* count decisions as rebalance-dates × names traded, or lower the S2 bar to ≥ 25 rebalances; pick
one now and write it in.

**6. BLOCKER — "skip if in F&O ban" (S3) cannot be computed: there is no historical ban-list or MWPL table in the
DB.** As written the rule is silently unimplementable, which is how look-ahead and survivorship bugs get invented
ad hoc at coding time.
*Smallest fix:* replace with an implementable proxy fixed now: skip if the stock hit ±~10% from prev close AND
closed at its high/low on day t (circuit proxy from bhavcopy), and drop the ban clause with a note that ban data
starts only when we begin capturing it.

**7. MAJOR — Universe T's ₹20 floor uses split-adjusted close: hindsight.** A 2015 stock at ₹100 that later splits
1:10 shows adjusted ₹10 and is excluded in 2015 using future information (ml_labels already flagged this; PLAN
inherits it via `lib/momentum.eligible`). Direction of bias is ambiguous (splits follow rallies — it removes some
future winners AND some junk).
*Smallest fix:* use `raw_close ≥ ₹20` for the floor in alpha_lab runs (one line in the engine's eligible call),
and note the deviation from the Desk's implementation in FINDINGS.

**8. MAJOR — Gate B is oversold for S2 and S3; the honesty note understates contamination.** The S2 feature list
and the S3 setup were selected because `evidence_probability` showed them working on **2011–2026** (its P1
discovery period IS 2011–19). Walk-forward refits make only the *weights* out of sample; feature/setup *selection*
saw every year the gates will touch. The same is true of S1's five veto flags.
*Smallest fix:* rewrite the honesty note: "2011–19 is cold for none of the three signal sets; Gate B tests
implementation-level robustness (portfolio construction, costs, interactions), not discovery. The only
uncontaminated test is the forward paper period." Add a mandatory 6-month forward shadow before any 'winner'
label.

**9. MAJOR — Multiplicity accounting.** Six configurations (3 strategies × base/variant) against a Gate A that
(pre-fix 1) a breadth-beta book passes: family-wise false-pass risk is material; even post-fix, state the family
size in FINDINGS and report all runs, including failures, in one table. The "one revision round" rule is loose.
*Smallest fix:* append to PLAN: "the family is 6 runs; all are reported; a revision may change only execution
mechanics (costs, scheduling, caps), never a signal definition — a signal change is a new strategy needing fresh
pre-registration and an untouched test window."

**10. MAJOR — Crash-filter mechanics are under-specified and expensive.** Full liquidation and re-entry on each
200-DMA flip churns the whole book (≈ 2 × full-book costs per whipsaw; 2015–16 and 2020 whipsawed). Post-crash
re-entry also voids the buffer: every name is a *new* entry, so all five vetoes bind at once — intended? And is
the filter evaluated only at month-end signals (lag up to a month) or daily (not in spec)?
*Smallest fix:* spec now: filter evaluated at monthly signal dates only; re-entries after risk-off are new entries
(vetoes bind); costs charged on both flips; report whipsaw count.

**11. MAJOR — Delisting/suspension exits are unspecified.** Survivorship-free panels contain names that stop
trading mid-hold. xs_labels' convention (exit at last traded open, ffill ≤ h) exists for labels, not the engine.
*Smallest fix:* engine rule, fixed now: if a holding has no trade for 10 sessions at a rebalance, it is exited at
its last traded close with double slippage; if it never trades again, the position is written to zero on the day
coverage ends. State the rule in PLAN.

**12. MAJOR — Freeze the data window.** "→ latest" drifts with every rerun; results and bhavcopy ingest daily.
*Smallest fix:* Gate A = 2020-01-01 → **2026-10-13** inclusive; smoke = 2025-10-01 → 2026-10-13; write the panel
snapshot date into every report header.

**13. MINOR — Flat 6% liquid yield.** Short rates were ~3.5–4% in 2020–21 and 7%+ in 2011–14; a flat 6% flatters
risk-off periods in Gate A and penalises them in Gate B. Keep 6% but add a one-line sensitivity (4% and 8%) to the
risk-off-heavy variants.

**14. MINOR — S2's 12-week grid anchor is undefined** (holiday drift changes every subsequent date).
*Fix:* "every 12th trading Friday counted from the first trading Friday of 2016" — write it in.

**15. MINOR — Results-flag asymmetry.** The bad-results veto only exists where `nse_results` covers the symbol
(coverage from 2007 but incomplete for delisted names); uncovered names are never vetoed. Acceptable, but say it,
and never feed coverage itself to S2 (the evidence_probability leak); PLAN says neutralised — keep the test from
that study in the lab's test suite.

**16. MINOR — Reproducibility.** No pinned run command, config hash, or environment note per gate run.
*Fix:* each strategy script prints its full config dict + panel snapshot date into its report; seeds fixed where
any randomness exists (logistic solver is deterministic; fine).

**17. MINOR — The §Claims "quick tests" have no gates.** If any field-guide claim gets a quick test, pre-register
its pass rule in an appendix first, else it becomes a fishing trip.

## Conditions for sign-off (edit PLAN.md before any gate run)
1. Add EW-universe benchmark to Gates A and B (finding 1).
2. Replace criterion 1 with price-to-price, margin 0; document the dividend reasoning (finding 2).
3. Re-spec S3-futures: ₹1Cr, 1 lot/name, max 5, Gate A only (finding 3).
4. Re-spec hedged variants: ₹50L book, 85/15 structure, whole-lot hedge, residual exposure reported (finding 4).
5. Fix S2's decision-count gate (finding 5).
6. Replace the F&O-ban clause with the circuit proxy (finding 6).
7. Switch universe floors to raw close in the lab engine (finding 7).
8. Rewrite the Gate-B honesty note + add the 6-month forward-shadow requirement (finding 8).
9. Append the multiplicity/family statement and the tightened revision rule (finding 9).
10. Spec crash-filter evaluation timing, re-entry veto behaviour, and whipsaw cost reporting (finding 10).
11. Add the delisting exit rule (finding 11) and freeze all window end-dates at 2026-10-13 (finding 12).

Minor findings 13–17 may be folded in at implementation but must appear in FINDINGS.md caveats.

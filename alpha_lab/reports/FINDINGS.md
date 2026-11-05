# Alpha Lab findings — 14 Oct 2026

Owner's brief: at least three deterministic, evidence-driven strategies that beat the market; derivatives
considered; "stay away" rules so we win by refusing known-bad situations; staged validation (2020–26 first,
2011→ only on a pass); a parallel team of specialist agents; everything in this folder.

**The honesty line first.** Nothing is unbeatable, and nothing here promises always winning. What survived below
is: a probability tilt that beat two benchmarks after real ICICI costs across 16 years, a refusal library with
measured odds, and a hedge that converts crash years into flat-to-positive ones at a whipsaw price. Every claim
has a file, a config and a pre-registered gate behind it; every failure is reported with the same prominence.
Per the red-team's binding note: **2011–19 was cold for none of these signal sets** (they were selected on
evidence whose window includes it), so Gate B measures implementation robustness, not discovery — a ≥ 6-month
forward paper shadow is required before any "winner" label is final.

## How the team ran (six specialists, in parallel)
| Role | Output |
|---|---|
| Red-team validator | `plan_review.md`: 17 findings, 6 blockers; all 11 sign-off conditions adopted into PLAN Amendments v2 **before** any gate run |
| Claims analyst | `claims_matrix.md`: ~70 claims from your two documents reconciled against our measurements |
| S2 developer | `s2_RESULTS.md` + equity CSVs |
| S3 developer | `s3_RESULTS.md` + trade CSVs (incl. one false-PASS bug it caught itself before recording) |
| Derivatives & risk analyst | `hedge_overlay.md` (modeled puts, yield sensitivity), `avoid_rules.md` |
| New-signals researcher | `quick_tests_RESULTS.md`: the 5 pre-registered Appendix-Q tests |
| PM / engine (main session) | `../PLAN.md`, `../backtest/engine.py` (9 unit tests), S1 runs, `../run_today.py`, this report |

## The family of six: all verdicts in one table
Windows frozen: Gate A = 2020-01-01→2026-10-13 · Gate B = 2011-01-01→2019-12-31. All CAGRs after ICICI
costs + slippage; benchmarks are price-to-price (NIFTY 50 and the equal-weight point-in-time universe).

| Run | Gate A | Gate B | Key numbers |
|---|---|---|---|
| **S1 Sentinel momentum** (₹10L, monthly, veto + crash filter) | **PASS** (5/5) | **PASS** (4/4) | A: **28.0%** vs 9.6/24.2, DD −16.5%, IR 0.74 · B: **15.8%** vs 7.9/7.4, DD −34.6%, 5/9 years · Full 2011–26: **21.0%** vs 8.6/14.4, DD −34.6%, IR 0.60, costs ₹38.2L on ₹10L→₹2.0 cr |
| S1H (hedged, ₹50L 85/15, whole-lot NIFTY short) | **PASS** | FAIL (4/9 excess years) | A: 26.3%, DD −24.0% · B: 14.7% vs 7.9, DD −29.0% — beat NIFTY over the decade but lagged it in 5 of 9 years |
| S2 Horizon-60 probability book (₹10L, 12-weekly) | FAIL (DD −32.0% vs −30 budget) | not run (protocol) | A: 23.6% vs 9.6/17.8, IR 0.74 — returns fine, tail too deep unhedged |
| S2H (hedged) | **PASS** | FAIL (3/9 excess years) | A: 19.4%, DD −28.0%, IR 0.51 · B: 9.9% vs 7.9, DD −24.9% |
| S3 Leader-dip, delivery (₹10L, 5-session holds) | **FAIL** — the pre-registered expectation | not run | 1,498 trades, win 47.2%, −0.006%/trade: **costs eat the whole edge. STAY AWAY.** |
| S3 Leader-dip, futures (₹1Cr, 1 lot/name) | FAIL as a book | N/A (data era) | Signal survives futures costs: 923 trades, **win 53.2%, +0.295%/trade net**, +5 of 7 years, DD −17.7% — but 1-lot sizing deploys only ~₹23L of ₹1Cr → +1.9%/yr on capital. A capacity-capped overlay lead, not a strategy |

**What this answers in your words:** the things that are *failing with probability* are now rules we refuse
(S3-delivery's verdict, the avoid library below); the things *highly recommended with probability* concentrate in
S1; merging the two is exactly what S1 is — momentum picks minus every robust avoid flag — and the diagnostic run
proves the point: without the veto, same window, CAGR 28.4% but maxDD **−21.8%**; with it, 28.0% and **−16.5%**.
The refusal rules don't add return; they remove pain — that is the "win by not playing" mechanism, measured.

## S1 — what it actually is (deterministic monthly flow)
1. Last session of the month, after close: universe = 300 most liquid NSE stocks (raw close ≥ ₹20, EQ, no ETFs).
2. Rank by the Desk's momentum score (6m & 12m return ÷ volatility).
3. Strike out any name that is: below its 200-DMA · within 10% of its 52-week low · top-decile 60-day volatility ·
   split/bonus ex-date in the last 20 sessions · strong bad results in the last 60 sessions.
4. Hold the top 20 survivors, equal weight, with a 1.5× buffer (keep a holding while it ranks ≤ 30).
5. If NIFTY < its 200-DMA at the signal: everything to a liquid fund (S1) or hold and short NIFTY futures (S1H).
6. Execute at the next open. Nothing else, ever. `python alpha_lab/run_today.py` prints today's exact book —
   currently **RISK-OFF** (NIFTY 22,623 < 200-DMA 24,218), 191 of 300 names vetoed, book parked/hedged.
- Year by year (full run): 2011 +1.0 vs NIFTY −24.9 · 2014 +88.0 · 2017 +74.2 · **2018 −18.3 vs +3.2** ·
  2021 +87.4 · **2025 +4.2 vs +10.5** — the edge arrives in bursts and three to four years a decade lag badly.
  That is the real price of this premium; anyone who can't sit through 2018 or 2013 won't collect 2014 or 2021.
- Capacity: fine at ₹10L–₹1Cr (top-300 liquidity, 20 names, monthly). Costs ran ≈ 3.3%/yr of the book.

## The derivatives answer (your options question, honestly)
- **What we can gate:** the NIFTY-futures short (S1H/S2H). It passes Gate A, turned 2026's −13% NIFTY into +20.0%
  (S1H), and failed Gate B only on year-consistency — hedging costs show up as lagging most calm years.
- **What we can only model:** index puts. The analyst's Black-Scholes×VIX study (`hedge_overlay.md`): always-hedged
  costs ~5%/yr of CAGR; regime-only puts look free in the model *because the model is blind to panic skew* — so it
  is labelled MODELED and stays ungated until we capture ~6 months of real NIFTY option chains.
- **New, and genuinely interesting:** the five pre-registered F&O tests (Appendix Q) produced one **Robust** result
  — **Q1 excess carry**: stocks whose futures trade at a discount to fair value lag over the next 20 sessions in
  *both* periods (−0.49% t −4.2 / −0.38% t −2.9; Q5−Q1 spread +0.72%/+0.79% per signal, t ≈ 3.6/3.7). This is the
  first derivatives-derived signal in the whole project to pass a pre-registered bar. Per the rules it is a LEAD:
  the next legitimate step is its own strategy study (e.g. a carry veto/tilt inside S1's F&O names), freshly
  pre-registered. Also notable, descriptive only: stocks *removed* from F&O lag −6.4% over 60 sessions (n=80).
  Q2 (option/stock volume), Q3 (variance risk premium), Q4 (index OI-PCR): No effect — three clean nulls that
  close three folklore doors.

## The avoid library (the "stay away" half of your request)
`avoid_rules.md` — 12 rules with measured odds; the strongest, as a daily checklist (base: a liquid stock beats
the market ~45% of the time, worst-fifth 20%):
below its 200-DMA (42% beat, robust at 5/20/60d) · momentum bottom decile (38.5% at 60d) · near the 52-week low ·
split/bonus in the last 20 sessions (40%, worst-fifth 29%) · fresh strong-bad results (39%) · top-decile
volatility (worst-fifth **32%**) · upside value-area break (5d) · burst days. Plus the retired-ideas list
(quadrants, delivery surges, MTF, FII ratios, max pain) so nobody rebuilds them.

## Your two research documents
`claims_matrix.md` reconciles all ~70 claims. Headlines: the field guide's own evidence notes already disclaim its
folklore (quadrants/PCR/max-pain) and our data agrees; two imported priors are **sign-flipped in India**
(post-split drift and abnormal-volume premium are negative here); the brief's P1 cash features are ~70% already
measured in this repo; its IV features need per-strike archives we don't hold (fetchable from NSE if you want that
backfill); and its own "max pain: none expected" is confirmed.

## What I recommend next (your call, nothing changes without you)
> **Decision taken 14 Oct 2026, ~21:15:** the owner started the paper shadow. S1 (₹10L) and S1H (₹50L) run
> forward from **15 Oct 2026**, flat until the October month-end signal, via `alpha_lab/paper/shadow.py`
> (nightly job `alpha_shadow_daily` 19:50 IST; replayed through the gated engine each evening so paper can
> never drift from the validated code). Telegram: fill-day + Friday NAV messages, `/shadow` on demand.
> Paper only — no orders. Runs in parallel with, and fully isolated from, the Decision Desk's paper book.
1. ~~Promote S1 to a 6-month paper forward shadow~~ **done — started 15 Oct 2026** (see the note above; it is close to, but not identical to, the Desk: raw-price floor, the 5-flag veto).

2. **Pre-register the excess-carry strategy study** (the one new Robust signal) — carry tilt/veto inside S1.
3. **Start capturing** NIFTY option chains + MWPL/ban lists daily (makes the puts overlay and ban filter real
   within months).
4. Keep S3 delivery on the stay-away list; revisit the futures variant only with a revised, pre-registered sizing
   spec (its one allowed mechanics revision) if you want the +0.3%/trade edge at small capacity.
5. The liquid-yield convention moves S1 by ±0.7 pts for ±2 pts of yield (`hedge_overlay.md`) — immaterial.

## Caveats that stay attached to every number
Price-only curves both sides (dividends ≈ cancel); hedged variants carry lot-size residuals, margin earning 0 and
a pre-2019-10 spot-proxy for index futures; the ₹20 floor here is raw-close (deviation from the Desk noted);
survivorship-free panel with delisting exits per the amendment; family of 6 runs, all reported; S1's Gate-B pass
sits at the edge of its drawdown (−34.6 vs −35) and year-count (5/9) bars — respect how thin that margin is.

# Alpha Lab plan (pre-registered 14 Oct 2026, ~21:05 IST, before any backtest below was run)

Everything numeric in this file was fixed from *prior* evidence (the project's existing studies, listed per rule)
— not tuned on the runs this plan gates. Deviations found later must be logged in FINDINGS.md as post-hoc.

## Common frame
- **Prices:** vendored survivorship-free NSE bhavcopy panel from 2010-01 (`lib/nse_panel.py`), split/bonus adjusted.
- **Universe T (S1, S2):** the Desk's point-in-time top 300 by 126-session median turnover; EQ, adjusted close ≥ ₹20,
  ≥ 250 sessions history, no ETFs (`lib/momentum.py`). **Universe L (S3):** EQ, raw close ≥ ₹20, 20-session median
  turnover ≥ ₹5 cr, ≥ 250 sessions, no ETFs.
- **Execution:** signals at a session close; orders at the **next session's open**. Equal weight at entry.
- **Costs:** delivery = ICICI MoneySaver round trip by position size (vendored `trading_costs.py`) + 0.05%/side
  slippage. Futures = 0.03%/side all-in. Liquid-fund idle cash 6%/yr for S1/S2 (Desk convention); S3 idle cash 0%.
- **Capital for cost computation:** ₹10,00,000 (₹10L) book → S1/S2 positions ≈ ₹50,000 each (20 names).
- **Benchmarks:** NIFTY 50 price index (have 2009→) and the equal-weight liquid-universe return. Beat-the-market
  claims are judged against **NIFTY 50 + 1.5 pts/yr** (proxy for total-return dividends ~1.2–1.5%).

## Stages and gates (the owner's protocol)
- **Stage 0 smoke:** 2025-10-01 → latest. Mechanics only (fills, costs, no NaNs). No verdict.
- **Gate A (2020-01-01 → latest), all must hold:**
  1. CAGR after costs > NIFTY 50 CAGR + 1.5 pts.
  2. Max drawdown ≥ −30% absolute, and no deeper than 1.25 × NIFTY 50's max drawdown in the window.
  3. Monthly-excess information ratio vs NIFTY 50 ≥ 0.45.
  4. ≥ 30 independent rebalance/entry decisions.
- **Gate B (2011-01-01 → 2019-12-31, run only after an A-pass; then full 2011→latest):**
  1. CAGR after costs > NIFTY 50 CAGR in that window (no +1.5 margin — the decade is harder and data is thinner).
  2. Max drawdown ≥ −35% absolute (the window contains 2011 and 2015–16 bears; NIFTY's own was ≈ −25%).
  3. Positive excess year in ≥ 5 of the 9 years.
- **Honesty notes fixed in advance:**
  - For S1's momentum core, 2011–19 is **not** untouched (phase_b_extended already ran momentum there, and it
    passed). Gate B for S1 is a consistency check, not discovery. For S2's merged model and S3, the 2011–19 window
    has never been run in these configurations; price-only components face it cold; event-flag components simply
    don't exist before 2019-10 and degrade away (that is the honest behaviour, not a bug).
  - Multiplicity: exactly **3 strategies + 2 pre-named overlay variants each** (below). No parameter sweeps. If a
    strategy fails a gate it is reported failed; any revision is one round, post-hoc-labelled, judged only on data
    the revision did not look at.

## S1 — Sentinel momentum (monthly, deterministic)
Evidence base: phase_b / phase_b_extended (ADOPTED momentum), evidence_probability (robust avoid flags).
- Signal date: last session of each month; execution at the next open. Universe T.
- Rank by `mom_nse` (6m & 12m return ÷ 1-yr vol, cross-sectional z, the Desk's own score).
- Book: top 20, buffer 1.5× (hold while rank ≤ 30), equal weight, max 15% per name.
- **Avoid-veto on new entries only** (never force-sells a holding). A stock cannot be *newly* bought if, at signal:
  1. below its 200-day average, or
  2. within 10% of its 52-week low, or
  3. 60-day volatility in the universe's top decile, or
  4. split/bonus ex-date in the last 20 sessions, or
  5. strong bad results (≤ −5% vs market reaction) in the last 60 sessions.
  (Each flag individually Robust/Holds in `reports/evidence_probability/`; the set is fixed here, not fitted.)
- Regime: NIFTY 50 close < its 200-day average at signal → book goes to the liquid fund at the next open
  (the Desk's approved crash filter).
- **Variant S1H (hedge instead of exit):** same book, but on risk-off the equity stays and a NIFTY-futures short
  of equal notional is carried (futures cost 0.03%/side at each monthly reset; margin funded from the liquid
  sleeve at 6%). This is the derivatives overlay, honestly priced from `fut_close` where available (2019-10→),
  spot-proxied with basis 0 before that (flagged).
- **Variant S1P (modeled puts, report-only):** risk-off → hold equity + buy 1-month ~5%-OTM NIFTY puts sized to
  notional, priced Black-Scholes with India VIX × 1.1 (skew bump). **Modeled, not market prices; never gated,
  reported for information.**

## S2 — Horizon-60 probability book (every 12 weeks, deterministic)
Evidence base: evidence_probability (merged P(win) calibrated OOS; 60-session BUY−AVOID spread 3.3–3.5% vs 0.96%
cost; label study: 60d momentum net +12.6%/yr).
- Signal: every 12th Friday (first signal = first Friday ≥ 2016-01 with 2 training years; for Gate A runs the
  walk-forward starts 2016 so 2020 predictions are honestly out of sample).
- Walk-forward logistic (L2, C=0.1, yearly January refits, training ends 61 sessions before the test year) on
  universe T with **price-only robust flags + momentum percentile** as of 2011 (below-200dma, near-52w-low,
  near-52w-high, mom top/bottom decile, high-vol decile, split-ex-20d) plus event flags (bad/good results 60d,
  burst, VA-break) only once each has ≥ 2 years of history. Targets: P(top-fifth of 60-session next-open excess)
  and P(bottom-fifth). Hindsight coverage flags neutralised at prediction (the leak fix from
  `reports/evidence_probability/`).
- Book: long the top 20 by P(top) among stocks **not** AVOID (P(bottom) in that year's training top 20% — threshold
  from training predictions only), buffer 1.5×, equal weight; hold 12 weeks; same crash filter as S1.
- Variant S2H: futures hedge on risk-off, as S1H.

## S3 — Leader-dip (daily scan, 5-session hold)
Evidence base: evidence_probability (RSI(2)<5 in momentum leader: Robust at 5 sessions, +0.49%/+0.58% weekly
excess, 53% beat rate both periods); handbook F_rsi2 (+0.15R gross, killed by costs).
- Universe L. Setup at any close t: momentum percentile ≥ 0.70, close > 200-day average, RSI(2) < 5.
- Enter next open; exit at the open of t+6 (5 full sessions). Max 5 concurrent names, 20% of book each; one
  entry per stock per 10 sessions; skip if the stock is in F&O ban or hit a circuit at t.
- **Two cost profiles, both reported:** delivery (MoneySaver + slippage) and futures (0.03%/side, only the ~180
  F&O names, from 2019-10). Pre-registered expectation: delivery fails Gate A; the futures variant is the live
  candidate. If both fail → verdict "stay away", which is itself the owner's requested outcome.

## The avoid library (deliverable, not a gate)
A standing "do not touch today" checklist compiled from every Robust/Holds avoid flag with its measured
probabilities, to be served later in the terminal. Nothing to gate; it ships in FINDINGS.md.

## Claims from the two attached research documents
Fork agent A maps every testable claim in `inputs/oi_field_guide.md` and `inputs/feature_research_brief.md` to
{already tested here → verdict | untested but testable on our data | untestable without tick/strike data}. Up to
three untested claims with plausible evidence value get quick pre-registered tests appended to this plan **before**
being run; the rest are catalogued only.

---

## Amendments v2 (14 Oct 2026, ~21:50 IST — BEFORE any gate run; from reports/plan_review.md sign-off conditions)
All 11 conditions adopted verbatim; gate numbers below supersede the originals.

1. **Benchmarks (findings 1, 2).** Gate A/B criterion 1 becomes two price-to-price tests, margin 0 (the book and
   both benchmarks are all ex-dividend, yields roughly cancel):
   1a. CAGR after costs > NIFTY 50 price CAGR.
   1b. CAGR after costs > the **equal-weight universe benchmark** (universe T for S1/S2, universe L for S3),
       reconstituted at the same signal dates, no costs — the "random breadth book" bar.
2. **S3 futures variant (3):** ₹1 crore capital, exactly 1 lot per name (lot notional ≈ ₹5L before 2024-11-20,
   ≈ ₹15L after — dated proxy), max 5 lots; margin from the cash sleeve; **Gate A only** (fut_close starts
   2019-10); the delivery variant alone faces Gate B.
3. **Hedged variants S1H/S2H (4):** ₹50L book, permanent **85% equity / 15% liquid sleeve**; hedge = nearest whole
   NIFTY-futures lot (75 × NIFTY) to the equity value, residual net exposure reported monthly; SPAN+exposure
   margin ≈ 13% of hedge notional sits in the sleeve earning 0 while the hedge is on; pre-2019-10 basis-zero proxy
   stays flagged.
4. **S2 decision gate (5):** criterion 4 for S2 = **≥ 25 rebalances** (12-week cadence gives ~29 in Gate A).
5. **S3 ban clause (6):** replaced by the circuit proxy — skip entry if on the signal day |close/prev − 1| ≥ 9.5%
   with the close pinned at the day's high (up) or low (down). Ban-list capture starts forward only.
6. **Universe floor (7):** the lab engine uses **raw close ≥ ₹20** (not adjusted) for both universes; deviation
   from the Desk's implementation noted in FINDINGS.
7. **Gate B honesty (8), rewritten:** 2011–19 is cold for **none** of the three signal sets (all were selected on
   evidence whose discovery window includes 2011–19). Gate B tests implementation-level robustness — portfolio
   construction, costs, interactions — **not discovery**. The only uncontaminated test is forward: any strategy
   passing both gates still needs a **≥ 6-month paper forward shadow** before being called a winner.
8. **Multiplicity (9):** the pre-registered family is **6 runs** (S1, S1H, S2, S2H, S3-delivery, S3-futures). All
   are reported, including failures, in one table. A revision may change only execution mechanics (costs,
   scheduling, caps) — never a signal definition; a signal change is a new strategy with fresh pre-registration.
9. **Crash filter (10):** evaluated at monthly signal dates only; post-risk-off re-entries are new entries (all
   vetoes bind); both flip directions pay full trading costs; whipsaw count reported.
10. **Delisting rule (11):** a holding with no trade for 10 sessions at a rebalance exits at its last traded close
    with **double slippage**; a name stale for 60 sessions is written to **zero** in the daily mark (conservative
    stand-in for "coverage ended"). Counts reported.
11. **Frozen windows (12):** smoke 2025-10-01→2026-10-13 · Gate A 2020-01-01→**2026-10-13** · Gate B
    2011-01-01→2019-12-31 · full 2011-01-01→2026-10-13. Every report prints the panel snapshot date and config.
12. Minors 13–17 adopted: liquid-yield sensitivity (4%/8%) reported for risk-off-heavy variants; S2 grid = every
    12th trading Friday counted from the first trading Friday of 2016; results-veto coverage asymmetry noted and
    the coverage-leak regression test kept in the lab suite; full config printed per run; any field-guide quick
    test gets its pass rule appended here before running.

## Appendix Q (pre-registered 14 Oct 2026, ~22:20 IST, before any of these ran): five quick tests from the claims matrix §B
Frame for all: weekly signals (last session of each week), entry next open, Newey-West t (lags 1/4/12 for h=5/20/60),
costs noted but tests are gross cross-sectional diagnostics, NOT strategies. Periods: P-a 2019-10→2023-12,
P-b 2024-01→2026-10-13 (test 3: 2009-10→2019-12 and 2020-01→2026-10-13). Pass bar = same sign and |t| ≥ 2 in BOTH
periods ("Robust"); one period only = "Lead". All five are reported whatever the outcome; a pass makes a LEAD for a
future strategy pre-registration, never a live rule. Directional hypotheses fixed now:
- Q1 FUT-04 excess carry: annualised stock-futures basis minus 6.5%, ex-dividend windows stripped; quintiles within
  F&O names; H: bottom (discount) quintile LAGS over 20 sessions.
- Q2 OPT-08 O/S ₹-proxy: 5-day opt_value / 5-day cash turnover, quintiles within F&O names; H: top quintile LAGS
  over 5 and 20 sessions.
- Q3 POS-05 variance risk premium: (VIX/100)² − 21-session realised NIFTY variance; monthly terciles; H: high-VRP
  tercile → HIGHER next 20/60-session NIFTY and EW-universe returns.
- Q4 POS-06 index OI-PCR percentile (252-session window) and its 5-session change; BOTH signs allowed → exploratory
  by construction (a pass still only = Lead).
- Q5 EVT-03 F&O entry/exit events (first/last appearance in nse_fo_daily, ±60 sessions vs liquid universe):
  descriptive only, CIs, no gate (small n; entry events confounded by the 2019-10 data start — drop the first 60 days).

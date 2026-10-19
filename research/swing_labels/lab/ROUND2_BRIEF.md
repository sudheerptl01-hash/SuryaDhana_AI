# Round 2 Brief — converge on the label stack for a 5–20 day NSE swing trader

Read `TEAM_BRIEF.md` first (conventions still apply), then this file. Lab dir:
`/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab`
Round-1 artifacts: `results/<A_barrier|B_relative|C_trendscan|D_setups|E_auditor>/` (results.json,
tables_autogen.md / report_tables.md, scripts) and `results/_lead/round1_results.json` (all structured
outputs). Market context: `results/_lead/market_context.json`.

## Lab v2 — what changed (rebuilt; round-1 numbers are NOT directly comparable)
* **Sector data removed.** The NSE constituent lists were a 2026 snapshot (look-ahead/survivorship;
  +56 bps/10d "has-sector" edge in 2021–25 that vanished in 2026). `sec_rel_mom20` and `F.sector`
  no longer exist. Do not reintroduce any current-snapshot membership data.
* **ETFs/MF units excluded** (`elig_equity`: ISIN starts with INE). Cross-sectional features rebuilt
  without them.
* **`elig_next` removed from `elig_base`** (it was look-ahead). Labels are NaN anyway when t+1 is missing.
* **Corporate actions:** duplicate exchange records (ex-dates 1–7 days apart) de-duplicated (47 dropped);
  550/559 splits+bonuses located on the actual price-gap day; 8,545 dividends; 161 rights; the rest
  are `label_block`.
* **New evaluation API — use these, not the old ones:**
  * `S = L.Sim(P, F, fw)`; `S.run(score, mask, h, step, top_k, side, exit_rule, pt, sl, cost_bps,
    start, end_exit, sizing='slot'|'equal', select_quantile=(lo,hi), cash_yield)` — **daily
    mark-to-market**, staggered sleeves, next-open entry, half cost at entry/half at exit, forced exit
    at last valid close on suspension / label_block / sleeve rebalance, slot sizing (unfilled slots =
    cash), fixed trading-day signal calendar (not mask-dependent). Returns CAGR, daily Sharpe, daily
    maxDD, exposure, trade stats, calendar-year returns.
  * `S.compare(score, mask, h, seeds=(1,2,3,4,5), **same_kwargs)` → strategy + **horizon-matched
    random baseline on the same mask** + `excess_cagr_vs_random` + `excess_daily_nw_t` (Newey-West,
    lag h). **This excess t is the primary investability statistic.**
  * `L.walk_forward2(target, mask, P, F, h, kind)` → OOS score that **scores all mask rows** in each
    test year (no label-defined look-ahead filter); `min_train`/`min_test` configurable for sparse
    event masks.
  * `L.xs_metrics(score, target, mask, P, h, binary_target=None)` → per-date cross-sectional rank IC
    and AUC with **non-overlapping t-stats**, dev vs holdout, IC by year. **Never report pooled AUC
    for absolute labels** (it measures market timing — round-1 canary proved it).
  * Windows: `L.DEV = ("2023-01-01","2025-12-31")` (exits land by dev end), `L.HOLDOUT` = 2026.
* Validation of Sim: `validate_sim.json` (hand-calculated trade, random bands, foresight canaries).

## Consolidated round-1 findings (the facts round 2 builds on)
1. **Absolute direction labels encode the market, not the stock.** Daily share of +1 ranges 17–82%,
   corr 0.60–0.72 with the market return over the same window; cross-sectional AUC only ~0.53;
   pooled AUC ≈ a within-date-shuffled label's. Absolute labels at 10–20d failed or tied random in
   the 2026 holdout (a down year: Nifty 500 −7.8% YTD).
2. **Costs decide the horizon.** Random top-20, 50 bps: h=10 ≈ +1.6% dev CAGR; h=20 ≈ +11.5%
   (Nifty 500 +15.5%). h=5 burns ~25%/yr. ⇒ 20-day holds are the economic sweet spot; 10 is
   marginal; 5 is not viable. **Always compare with the horizon-matched random baseline.**
3. **Relative, risk-neutralized rank labels are regime-free and the most investable.** B_relative's
   XR_neu (per-date rank of the residual of open[t+1]→close[t+h] after OLS on beta_60, vol_20,
   log_turn20; +1 top 30% / 0 / −1 bottom 30%) at h=20: dev 29.5% vs random 12.0%; 2026 +12.7%
   (annualized) vs random 5.7%; NW t 3.13 dev / 1.84 holdout. Raw-return rank (XRraw) lost its edge
   in 2026; vol-normalized (XRvn) failed. Note "excess-vs-index rank" ≡ raw rank (index leg is constant
   per date) — use factor-neutral residuals.
4. **The robust edge is the AVOID side.** Down-class (−1) cross-sectional AUC 0.54–0.57 in every year
   vs 0.48–0.54 for up. "Avoid30" overlays (drop the model's bottom 30%, hold the rest) beat random in
   2026 for almost every model. Single-stock shorts (F&O) lose ~−20%/yr even with a model → use −1 as
   **avoid / exit**, not as shorts.
5. **Exits:** stops and ATR trails destroy value; fixed 20-day holds capture 81–113% of the natural
   exit of good labels. Barrier labels are fine as *labels* (classes match P&L) but execute with a
   time exit.
6. **Trend-scanning (adaptive horizon) is not better than fixed 20d** — |t*| and L* match a driftless
   random walk null. Market-excess trend-scan (TSX_T5) has a stable IC (0.066 dev / 0.065 2026) and is
   useful as an avoid filter.
7. **Classic setups give no lift** (breakouts, pullbacks, VCP, delivery spikes, RS leaders: date-matched
   excess within ±13 bps; 20d volume breakout significantly negative). One real but episodic gate:
   **R1dn capitulation reversal** (close < prior 20d low on volume while Nifty-500 20d momentum < 0):
   P(+1) 0.45→0.557, +58 bps/event, month-block t 6.3, Bonferroni-passing, positive every year but
   concentrated in a few months.
8. **Statistics:** ~1.35M rows ≈ only ~1,000 independent observations; persistent-tilt luck band means
   a skill-less tilt can beat iid random by ~3pp CAGR; ~600 variants were tried in round 1 →
   discount accordingly (deflated Sharpe / Bonferroni). 2026 was *reported* in round 1, so it is a
   lightly-contaminated holdout: still never select on it.

## Scorecard v2 (every candidate)
event rates (overall / year / regime / liquidity tercile / corr with market) · xs IC and xs AUC (dev,
holdout, by year, non-overlap t) · `S.compare` at the horizon you claim (50 bps and 80 bps; dev and
holdout; excess vs random + NW t; exposure; maxDD) · number of variants tried · pros/cons.
Selection on DEV only.

## Round 2 roles

### R2_rel — Relative (selection) label architect
Build the definitive relative label on lab v2 for h ∈ {10, 15, 20}.
* Target: r_h = open[t+1]→close[t+h] (NaN where `fw.ok(h)` false), winsorized 1/99% per date, then
  per-date cross-sectional OLS residual among elig_base on [shrunk beta (0.5·beta_60+0.5), vol_20,
  log_turn20] (= XR_neu). Variants: + mom_12_1 (momentum-neutral); size-only; no neutralization.
* Label forms: 3-class rank 30/40/30, 20/60/20, 33/33/33; continuous per-date rank (regression);
  binary top-30 vs rest; binary bottom-30 vs rest (an explicit AVOID model).
* For each: event rates (verify stability), xs IC/AUC, `S.compare`: long top-K (K ∈ {10,20,30,50},
  step ∈ {5,10}); AVOID overlay = equal-weight all elig minus model bottom 30%
  (`select_quantile=(0.3,1.0), sizing='equal'`) vs universe equal-weight (`(0,1)`); liq2 vs liq5;
  50/80/130 bps.
* Deliver a **parameter-sensitivity map** (back-and-forth): how event rates, IC, excess-vs-random and
  2026 move when you change rank cut, horizon, neutralizers, K, step, liquidity tier. Identify robust
  plateaus vs cliffs. Select on DEV; report holdout.

### R2_dual — "Both conditions must accept" (the client's idea), formalized
* Label-side conjunctions: DUAL_up = (relative top-30% residual rank) AND (absolute net exec return >
  +τ, τ=50 bps) — and a path version: AND (long triple-barrier +1 at h=20, 3.0×/1.5× ATR). DUAL_down =
  bottom-30% AND absolute < −τ. Else 0; NaN where undefined.
* Compare with pure relative (R2_rel's XR_neu) and pure absolute: event rates by regime/year (the dual
  +1 share now moves with the market — quantify), label/P&L coherence (mean net per class),
  learnability (xs IC/AUC), investability (`S.compare` long top-K, avoid overlay with a DUAL_down model).
* Two-model alternative: score = rank(relative model) + rank(absolute model), or product of
  probabilities. And input-side conditions (rule gates such as close>sma200 ∧ xr_mom60>0.7 used only
  as SAMPLE filters) vs label-side conditions.
* Verdict: does requiring both conditions make more real money / fewer drawdowns than pure relative?

### R2_regime — Market regime & exposure layer
Absolute labels mostly encode the market; test timing the market separately.
* Date-level dataset (~1,430 dates): targets = Nifty 500 next-20d executable return > 0 (and > +1%),
  equal-weight elig-universe next-20d return > 0; features = mkt_*, breadth50, breadth_ad, dispersion,
  vix (walk-forward by year; small logistic/LGBM; few parameters).
* Simple rules too: N500 > 200dma; breadth50 > 0.5; vix < trailing median; mkt_mom60 > 0.
* Apply as an exposure scaler on (a) the universe equal-weight book and (b) a relative-model top-20 book
  (train a quick XR_neu regression via walk_forward2): 100% invested risk-on, 50%/0% risk-off with cash
  yield 6.5%. Report CAGR, Sharpe, maxDD, switches/yr, dev and holdout. Does timing help net of whipsaw?

### R2_event — Event sleeve: capitulation reversal
* Re-validate R1dn on lab v2 with `S` (slot sizing, fixed calendar): lookback 10/20/40, volume
  thresholds, market filters, h ∈ {5,10,20}; month-concentration diagnostics.
* Meta-label via `walk_forward2` on event rows (small min_train) and compare all-events vs top-scored.
* Scan 3–5 other overreaction/reversal events under Bonferroni across everything tested.
* Combination: daily-return correlation with a relative top-20 book; combined portfolio (e.g. 80/20).

### R2_alpha — Alpha source & ensemble
* Train walk_forward2 models on XR_neu (regression), an absolute A2-style barrier label (binary, h=20,
  3.0/1.5 ATR) and a market-excess trend label; score correlations; rank-average ensemble → xs IC and
  `S.compare`.
* Feature-group ablation on the XR_neu model: drop {momentum}, {vol/risk}, {volume/turnover},
  {delivery}, {market/regime}, {xs ranks}, {technicals: rsi/range/gap/hi-lo}; ΔIC and Δexcess; importance
  stability by year. Is NSE delivery data adding value?
* Factor attribution: regress the best book's daily excess-vs-random on long–short factor returns built
  from the same universe (size via log_turn20, momentum mom_12_1, reversal mom_5, low-vol vol_20, beta)
  → alpha t after factors. Is the edge just low-vol/reversal?

### Judges (after the refiners): J_pm (portfolio manager: real money, costs, capacity, drawdowns,
simplicity) and J_stat (statistician: multiple testing, deflated Sharpe, leakage, holdout honesty).
Each produces a ranked recommendation of the final LABEL STACK (primary selection label, avoid label,
regime layer, event sleeve) with confidence and caveats.

### Devil's advocate (after the judges): independently reproduce the winning stack from scratch, run
perturbation tests (random 50% entity halves, 1-day signal lag, quarter-by-quarter), deflated Sharpe
with the total variants count, capacity/impact at ₹5L/₹25L/₹1Cr per name vs ADV, and a "boring
explanation" test (does a simple factor tilt replicate it?). Verdict: survives / caveats / fails.

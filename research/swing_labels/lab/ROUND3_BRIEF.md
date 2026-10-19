# Round 3 Brief — from the winning label to an investment process (and the honest exam)

Lab: `/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab`
Read in order: `TEAM_BRIEF.md` (conventions), `ROUND2_BRIEF.md` (lab v2 + round-1 facts),
`PREREG_R3.md` (frozen label, frozen PROD score, frozen baseline book, adoption rule), then this file.
Round-2 outputs: `results/_lead/round2_results.json` (refiners, judges J_pm/J_stat, devil). The devil's
full results: `results/R3_devil/results.json` and scripts `results/R3_devil/s*.py` (s7_capacity.py has a
per-trade-cost copy of L.Sim validated bit-exact; reuse it). Label files: `results/R2_rel/labels_h{10,15,20}.npz`
(r, rw, pct_neu, pct_neumom, pct_size, pct_none, res_*), `results/R2_rel/meta.npz` (E, liq5, fno),
`results/R2_alpha/labels.npz` (barrier, trend-scan), `results/R2_dual/labels_h{10,20}.npz` (dual labels),
`results/_lead/atlas_v2.json` (label event-rate atlas + random cost curve).

## Round-2 verdict you build on (do not re-litigate)
* Label: XR_neumom h=20 continuous residual rank (classes 30/40/30 for reporting). Book: weekly, 4
  staggered sleeves, top-20, 20-day time exit, liq2, 50 bps. Avoid = bottom 30% of the same score
  (veto/exit, never a short in the cash segment). No regime timing layer, no event sleeve in the core.
* Devil: survives with caveats. Single model, phase-averaged: DEV +15.8%/yr excess vs random (t 4.11),
  2026 +3.9% (t 0.60); 3-seed ensemble 2026 −0.2%. DSR 0.63–0.76 at N≈2,000 trials (Bonferroni-haircut
  excess +6.7%). Planning number ≈ +5%/yr excess (range 0–10%). Edge lives in mid/small caps (F&O-proxy
  top-200 only +3.6% DEV). Capacity ≈ ₹25 L per name (≈ ₹20 cr AUM). Each day of signal delay −1.9 pp/yr.
  2026 IC intact (0.061) but the long book does not monetise it (top-30 AUC 0.508); avoid side is the most
  durable component. Book is short momentum by construction (2026: 12-1 momentum top-20 +32.9% vs random).

## New shared tools (use them; do not fork your own versions of these)
* `r3common.py` — `C.set_agent(name)`, `C.load_sim()`, `C.load_prod()` (frozen PROD score, label pct,
  10 member scores), `C.phase_avg(S, score, mask, mask_tag, h, kw, period, with_ew)` (period "dev" | "hold"
  | (start, end)), `C.compare`, `C.paired(a, b)` (paired diff + NW t), `C.stats_from_daily(r)`,
  `C.market_daily(index_name)`, `C.table(title, columns, rows, note)`, `C.save(section, obj)`.
  Random/EW baselines are cached in `results/_lead/rb_cache`: use a DISTINCT `mask_tag` for every
  distinct mask (e.g. "liq2", "liq5", "fno", "liq2_fno") or you will read the wrong baseline.
* PROD = `results/_lead/prod_h20.npz` (built by `build_prod.py`, info in `prod_h20_info.json`).
* Index data (`L.market_series(name)`): "Nifty 50 Futures Index" (near-month futures, rolled: use it for
  short-futures hedge P&L), "Nifty 50 Futures TR Index", "Nifty 1D Rate Index" (overnight cash yield:
  use it for cash), "Nifty 50 Arbitrage", "Nifty 500", "Nifty500 Equal Weight" (from 2023-04),
  "Nifty Midcap 150", "Nifty Smallcap 250", "Nifty Midcap Select" (from 2021-09; MIDCPNIFTY futures
  exist), "India VIX". Nifty indices are PRICE indices (≈1.2%/yr dividends missing); lab prices are
  CA-adjusted incl. dividends — say so when comparing.
* `fno_proxy` feature (top ~200 by turnover) proxies the F&O list.

## House rules for round 3
1. Selection on DEV only; 2026 reported. Adoption rule (PREREG): an add-on is adopted only if its DEV
   phase-averaged gain vs the frozen baseline has paired NW t ≥ 2 and maxDD worsens by ≤ 3 pp.
2. Phase-averaged numbers only (`C.phase_avg`); 5-seed random + EW baselines; 50 bps central, 80 stress.
3. Every variant counts: report `variants_tested`. Test only the pre-declared lists below (you may add at
   most 3 extra variants if you justify them in advance in your REPORT.md before running them).
4. Machine: 4 CPUs, 15 GB RAM, no swap, two agents run at once. Keep each Python process < 4 GB (load only
   needed columns; `del` big arrays), run ONE heavy process at a time, LightGBM n_jobs ≤ 2. Run scripts
   with `python3 -u` and `set -o pipefail`; log to `results/<agent>/log_*.txt`.
5. Outputs: `results/<agent>/results.json` (all numbers via `C.save`), including a section
   `html_tables` = list of `C.table(...)` records (numbers as fractions, e.g. 0.153 for 15.3%) and a
   section `charts` = {chart_id: {"type": "line"|"bar", "x": [...], "series": {name: [...]}, "note": ...}}
   ready to plot, plus `results/<agent>/REPORT.md` (findings, pros/cons, caveats). Your final answer is
   the structured summary the workflow asks for.
6. Never look ahead: any decision at signal date t uses data ≤ t; trades fill at open t+1 or later.

---------------------------------------------------------------------------------------------------
## R3_book — production book, exits, sizing, capacity, turnover, tax
1. **Reproduce + ensemble.** Phase-averaged DEV and 2026 (50/80 bps) for: PROD (10-model rank-average),
   the devil's single model (`results/R3_devil/wf_main.npz`), the devil 3-seed ensemble (main, seed1,
   seed2 rank-averaged). Excess vs random and vs EW, NW t, maxDD, Sharpe, vol, by calendar year, by
   quarter, phase range. PROD stays the production score regardless (pre-registered).
2. **Exit / hold rules** (pre-declared list; baseline E0 = pure 20-day time exit):
   E1 carry: at a sleeve's rebalance, names that are in the new top-20 AND currently held in that sleeve
      are kept (no exit/entry cost; they also earn the close→next-open gap they would otherwise miss).
   E2w early exit (weekly check): every 5 trading days within the hold, if a held name's PROD rank on
      that date is ≤ 0.30 (avoid tail), exit at the next open; cash (Nifty 1D Rate) until the rebalance.
   E2d same as E2w with a daily check.
   E3 catastrophe stop: exit at next open if close ≤ 0.75 × entry price.
   S1 sizing: inverse-vol_20 weights within each sleeve's picks (cap 2× equal weight, fully invested).
   Report turnover (round trips/yr, % of book traded/yr), cost drag, CAGR, excess, paired t vs E0, maxDD.
3. **Capacity tiers.** Square-root impact per side = Y × daily vol_20 × sqrt(position / ADV20), Y ∈ {0.5, 1.0},
   capped at 10%; ADV20 = 20-day median traded value up to t (panel `turnover`, rupees). AUM tiers
   ₹1 cr, ₹5 cr, ₹20 cr, ₹50 cr, ₹100 cr (position = AUM/80 per name). Policies: (a) liq2 uncapped,
   (b) liq2 with a 5%-of-ADV20 participation cap (excess size stays in cash), (c) liq5 universe,
   (d) liq5 + cap. Random baselines pay impact on their own picks. Deliver a capacity table and the AUM
   where absolute CAGR falls to the EW universe / to Nifty 500.
4. **Operations + tax.** Orders per week, positions held, average ADV of picks, median participation.
   Tax illustration for an Indian individual: all gains short-term (STCG 20% since 23-Jul-2024, 15%
   before; STCL carried forward), vs buy-and-hold Nifty 500 (LTCG 12.5% above ₹1.25 L, paid at sale).
   Simple annual realisation model; note that frequent trading may be taxed as business income instead.
5. **Charts data** (`charts`): monthly equity curves (DEV and 2026 separately, and one contiguous
   2023-01 → 2026-10 curve) for PROD book, random, EW universe, Nifty 500 price; quarterly excess bars;
   drawdown series (weekly sampled).

## R3_twoway — "down is fine too": monetising both directions
1. **Outcome tables.** For the realised label classes (+1/0/−1, neumom h=20) and for PROD score deciles
   (what is tradable): mean and median absolute 20-day net return (open t+1 → close t+20, minus 50 bps),
   P(net > 0), P(net < −5%), by year and by ex-ante market state (Nifty 500 above/below 200-dma; Nifty 500
   20d momentum sign). Top-minus-bottom decile spread and monotonicity.
2. **Down-side strategies** (pre-declared; DEV select, 2026 report; daily mark-to-market; stats via
   `C.stats_from_daily`; vs the unhedged PROD book):
   D0 avoid veto only (EW universe minus bottom 30%; round-2 baseline).
   D1a PROD long book + short Nifty 50 futures, hedge ratio 1.0, rebalanced weekly.
   D1b same with ex-ante rolling 60-day beta of the book to the futures index (data ≤ t−1), weekly.
   D1c same as D1b with "Nifty Midcap Select" (attribution: closer size match; liquidity caveat).
   Hedge P&L = −β × r(futures index) (the futures index embeds roll/basis). Costs: 1 bp on traded hedge
   notional per weekly adjustment + 2 bps per monthly roll. Margin: 15% of notional, half in cash
   earning Nifty 1D Rate, funded by scaling the long book to 1/(1 + 0.075β).
   D2 long/short inside F&O (fno_proxy ∩ elig_base, PROD re-ranked within it): long top-K / short
      bottom-K via stock futures, dollar-neutral, K ∈ {10, 20}. Short leg daily P&L = −r(stock, CA-adjusted)
      + r(Nifty 1D Rate) (futures carry); futures cost 25 bps round trip per leg; cash long at 50 bps
      (or futures long at 25 bps — report both).
   D3 core long book (full liq2 universe, cash) + 50% overlay short of F&O bottom-20 futures.
   D4 F&O short-only bottom-20 (futures) on cash collateral, to price the down side alone.
   Report CAGR, vol, Sharpe, maxDD, worst month, % positive months, correlation with Nifty 500,
   performance in the months when Nifty 500 fell > 3%, and 2026 YTD.
3. **Verdict**: which use of the −1 side is viable for an Indian swing trader (cash only; cash + index
   futures; full F&O), with numbers and honest costs.

## R3_scen — scenario & event-rate atlas (the label explainer for the client)
1. **Label zoo × horizon** (h = 5, 10, 15, 20): old repo label (close[t]→close[t+h] > 0 on raw prices,
   NaN→0), clean sign (open t+1 → close t+h > 0), cost-aware 3-class (±50 bps), triple barrier
   (2.0/2.0 and 3.0/1.5, √h-scaled), relative XR_neu 30/40/30, XR_neumom 30/40/30, DUAL_up/DUAL_down
   (relative top/bottom-30 AND |net| > 50 bps in the same direction). Event rates (class shares), daily
   +1 share sd and p5/p95, monthly corr with the market, mean net return by class (coherence).
2. **Filters ("conditions") × label**: none (all rows with a valid forward window and not label_block),
   elig_base (liq2), liq5, F&O proxy, and input gates used as sample filters only: trend gate
   (close > sma200 & xr_mom60 > 0.7), washout gate (R2_event A1), high-delivery gate (deliv_pct top
   tercile). How event rates and class coherence change with each condition.
3. **Scenarios**: ex-ante (known at t): Nifty 500 above/below 200-dma; 20d market momentum sign;
   breadth50 above/below 0.5; India VIX terciles. Ex-post (explanatory only): realised Nifty 500 20d
   return bins < −5%, −5..0, 0..+5, > +5%. For each scenario × label: +1 share, P(net > 0 | +1), mean net
   | +1, mean net | −1; and for PROD: top-20 mean net, excess vs universe mean, rank IC.
4. **Horizon economics**: random-book CAGR by h and cost (atlas_v2), the overnight-vs-intraday split of
   universe returns (close→open vs open→close, equal-weight elig_base, DEV and 2026) and what fraction
   a 5/10/15/20-day open-to-close hold forfeits (the "overnight tax").
5. **Charts**: monthly +1 share of clean-sign h=20 vs XR_neumom h=20 vs the market's monthly return;
   event-rate-by-horizon bars; scenario heatmap data.

## R3_risk — exposure, drawdowns, expectations, monitoring and kill rules
1. **Drawdown anatomy** of the PROD book on one contiguous window 2023-01-01 → 2026-10-14 (phase-averaged):
   top-5 drawdowns (peak, trough, recovery, depth, length) vs Nifty 500, EW universe and random over the
   same windows; monthly return distribution; % months beating random / EW.
2. **Exposure policies** (pre-declared): static 100% / 80% / 60% (rest in Nifty 1D Rate), and the single
   governor breadth50 < 0.5 → 50% invested at sleeve rebalance only. DEV, 2026, and PRE (2021-09 → 2022-12)
   on the EW book (no PROD scores exist before 2023; say so). CAGR, maxDD, Sharpe, Calmar.
3. **Expectations**: block-bootstrap (20–60 day blocks) of the phase-averaged excess series shifted to the
   planning mean (+5%/yr) and to 0: distribution of 6-, 12-, 24-month excess; P(negative excess year);
   ranges of absolute returns combined with the EW universe.
4. **Kill / review rules**: calibrate candidates (rolling 6-month excess < −5%; rolling 3-month mean IC
   < 0.02; 12-month excess < 0) — false-alarm probability within 24 months for a +5%/yr book and detection
   probability/time for a 0%/yr book (persistence-matched). Recommend the rule set and a weekly
   monitoring dashboard (IC, top-20 hit rate, avoid-tail realised return, turnover, slippage vs open).

## R3_exam — adversarial verification, final exam, forward protocol (runs after the four above)
1. Independently re-compute at least 2 headline numbers from EACH of R3_book, R3_twoway, R3_scen,
   R3_risk with your own code (not their scripts); flag any discrepancy > 10% relative or any look-ahead
   (early exits, hedge betas, impact ADV, gates must use data ≤ t).
2. Apply the adoption rule to every add-on; list adopted vs rejected with the evidence.
3. Final exam table: frozen process on 2026 (single model vs PROD), phase-averaged, with the 2026 random
   and EW baselines, and the precision-weighted forward estimate.
4. Write the forward protocol for data after 2026-10-14: exact frozen spec, retrain rule, success
   criteria, kill/review rules, challengers to evaluate only on fresh data.

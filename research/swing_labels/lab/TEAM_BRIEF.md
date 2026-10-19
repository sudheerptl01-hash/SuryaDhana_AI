# SuryaDhana Label Research — Team Brief (read fully before starting)

## The client's question
"I want to be a swing trader holding **5 to 20 trading days** on NSE cash equities. What is the
**real, unbiased label** that tells me which stock is going up (or down — both are useful),
such that none of the known labeling problems leak in? What are the event rates, scenarios and
impacts, and how do I invest with it?"

## What is already established (do NOT re-derive; build on it)
The original repo label `label_up_hd = (close[t+h]/close[t] - 1 > 0)` was proven wrong on 5 grounds
(12 months of real NSE data, h=3):
1. **Unexecutable entry**: signal at close[t] can only trade at open[t+1]. Close-entry mean 3d return
   +2.7 bps vs next-open entry −15.4 bps (overnight gap +18.1 bps/trade is phantom edge).
2. **0 bps boundary**: round-trip NSE delivery cost ≈ 22.3 bps statutory (STT 0.1%+0.1%, stamp 0.015%
   buy, exch 0.00297%/side, SEBI, GST); all-in 25–35 bps large caps, 35–60 mid, 60–130 small.
   ±50 bps dead zone reclassified 14.1% of labels as economically flat.
3. **Path-blind**: triple-barrier (1.5/1.0 ATR, 5d) → 24.4% target, 46.2% stop, 29.4% time exit, while
   the sign label said 46.3% "up".
4. **Untradeable bars labeled**: BE (trade-for-trade) 6.7%, circuit-locked 0.87%, <₹20 11.1%, a "3-day"
   label spanning 182 calendar days across a suspension.
5. **Implementation corruption**: NaN forward return → label 0; unadjusted prices (splits = fake −50%);
   ticker-keyed identity (renames split, reused symbols splice); same-date EQ+BE duplicates.
Also measured: monthly P(up,3d) ranged **31%–67%** (label mostly encodes market regime); lag-1
autocorrelation of overlapping 3d labels = 0.64 (≈ theory 2/3) → samples are not independent.
India-specific: **no overnight shorting in the cash segment** (shorts need stock futures/SLB; only ~200
F&O names). "Down" labels are still valuable as avoid/exit signals and for F&O names.

## The lab (already built — use it, don't rebuild data)
Directory: `LAB = /tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab`
```python
import sys; sys.path.insert(0, LAB); import lablib as L
P  = L.load_panel()      # ~3.5M rows, one per (entity, date), sorted entity,date. Jan-2021..Oct-2026
F  = L.load_features()   # same row order; point-in-time features + elig_* flags + 'sector', 'fno_proxy'
fw = L.Fwd(P)            # fw.at(arr, k) = value at t+k in the same segment; fw.ok(h) = valid window mask
```
Read `lablib.py` (it is short) — especially `barrier_labels`, `fwd_return`, `market_fwd`,
`event_report`, `overlap_autocorr`, `walk_forward`, `portfolio_sim`, `benchmark`.
Data facts: `build_meta.json`, `features_meta.json`.
* `entity` = ISIN-based identity; renames and ISIN-changing splits are bridged; symbol reuse is not.
* `open/high/low/close/vwap` are **corporate-action adjusted** from NSE's official book-closure (Bc)
  records in the daily PR archive: splits, bonuses, consolidations, dividends (so adjusted series are
  ~total return) and rights (TERP). Each split/bonus is located on the day the raw price actually
  jumps and validated (`ca.py`, `ca_events.parquet`, `build_meta.json` → `ca`). `raw_close`/`raw_open`
  are the unadjusted prints. NOTE (verified): NSE's PREV_CLOSE field is NOT adjusted for corporate
  actions — do not use it as a CA detector.
* `label_block` rows = unadjustable events (demergers, schemes, capital reduction, unlocated
  split/bonus, unexplained >35% adjusted daily moves, >5% prev-close data gaps). `fw.ok(h)` already
  excludes any window containing one. Weekend special sessions (Muhurat Sundays, Saturday DR
  sessions, Budget-day sessions) are included.
* Segments: windows never cross a `seg_break` (>45-day suspension gap).
* `F.elig_base` = EQ series ∧ raw price ≥ ₹20 ∧ 20d turnover ≥ ₹2 cr ∧ ≥120 bars seasoned ∧ not
  locked (high>low) ∧ next bar within 5 days ∧ 0.5% ≤ ATR% ≤ 15% ∧ file-date check. `elig_liq5` = ₹5 cr.
  `fno_proxy` = top-200 by turnover that day (proxy for shortable F&O names).
* Market proxy: Nifty 500 (`L.market_series("Nifty 500")`, `L.market_fwd(P, h)`). India VIX in `vix`.
* Features: `L.FEATURES` (55, all PIT). Market/regime features are included.

## Non-negotiable conventions (these are what make a label "bias-free")
1. Entry at **open[t+1]**. Never close[t].
2. Labels are **NaN where undefined** (`fw.ok(h)` false, missing entry, segment break). Never 0.
3. Eligibility/event filters choose **which rows are samples**; they **never change label values**.
4. Use adjusted prices for returns; volume features already adjusted (`volume_adj`).
5. Costs: assume **50 bps round trip** central case; always also report a **80 bps stress**.
6. Any model evaluation uses `L.walk_forward` (expanding window, yearly folds 2023–2026, embargo h+2).
   Never random K-fold. Report out-of-sample only.
7. Investability uses `L.portfolio_sim` from **2023-01-01 to 2026-09-10** and must be compared with
   (a) a **random-pick baseline** from the same mask (`random_seed=…`, average ≥3 seeds) and
   (b) `L.benchmark(P)` (Nifty 500 price index — note stocks are adjusted, so prefer the random baseline
   as the fair comparison).
8. Report **both sides** (long "up" and short/avoid "down") where meaningful; flag which short results
   are only realistic on `fno_proxy` names.
9. **Holdout discipline (selection bias guard):** the team will compare many labels and parameters.
   All *selection* decisions (which candidate/parameter is best) must be made on **2023–2025** results
   only. **2026 (Jan–Sep) is the final-exam holdout**: report it separately in every table, never tune
   on it. Always state how many variants you tried (needed for multiple-testing discounting).

## Compute etiquette (shared 4-CPU, 15 GB machine; another agent may be running)
* `n_jobs=2` for LightGBM (default in lablib). Use `date_step=2` in `walk_forward` for training speed.
* Load only the columns you need where possible; `del` large arrays between variants; float32 where OK.
* Budget: at most ~6 full walk-forward evaluations per agent; use event-rate screening to pick which.
* Write your scripts and outputs under `LAB/results/<your_agent_id>/` (create it). Save every key
  number to `results.json` there as you go (so work survives interruption). Never edit `lablib.py`,
  `panel.parquet` or `features.parquet` — copy code into your own script if you need a variant.
* Do not download anything from NSE; the data is complete.

## Standard scorecard (report this for every candidate label you evaluate)
* `candidate_id`, family, exact formula, horizon(s), side(s), parameters.
* **Event rates** on `elig_base`: overall class shares; by year; monthly positive-share mean/std/min/max;
  by regime (bull/bear × up20/dn20); by liquidity tercile; `corr_monthly_pos_vs_mkt_ret`
  (regime dependence; closer to 0 = less market-beta in the label).
* **Bias checklist**: executable entry, cost-aware, path-aware, NaN-safe, CA-safe, suspension-safe,
  survivorship-safe, regime-neutral, overlap handling.
* **Learnability** (walk-forward OOS): AUC (binary/multiclass) or daily rank IC (regression); top-decile
  hit rate vs base rate per year.
* **Investability**: portfolio_sim top_k=20, step=5 (and h-appropriate variants), 50 bps and 80 bps,
  vs random baseline and Nifty 500: CAGR, Sharpe, maxDD, hit rate, mean trade, by-year.
* **Pros / cons / failure modes**, and how its event rate moves when parameters change.

Be quantitative and honest. A label that looks great but leaks, or only works in one year, is a failure
— say so. Negative results are valuable.

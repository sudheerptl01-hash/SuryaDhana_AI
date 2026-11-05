# "Label Logic Review" vs this repo — verification (15 Oct 2026, ~06:45 IST)

Owner-shared review: claude.ai/artifact/U9xndCg2p14Ex1uhnkmwNX ("Are fwd_ret_{h}d / label_up_{h}d
the right labels?"). Its code under review, `nse_historical_ingest.py:406–487`, **does not exist in
this repository and never has** (`git log --all` has no such path; none of its quoted lines —
`(fwd > 0).astype("Int8")`, `apply_corporate_actions(…, ca_csv)`, a labelled `SELECT … IN ('EQ','BE')`
— appear here). Its five grounds are sound general tests, so they were applied to the two label
sets this repo actually has.

## Scorecard
| Review ground | Production label (`feature_engine.build_labels_v2`, ML Engine default) | v3 labels in `computed_features_v2.parquet` (after Amendment 1) |
|---|---|---|
| 1 · entry price | **FAIL** — `adj[t+5]/adj[t]`, close entry | PASS — next-open entry (`xs_labels.forward_open_returns`) |
| 2 · decision boundary | **FAIL** — 0.15% hurdle vs ≈0.93% ICICI round trip | PASS by design — cross-sectional excess rank; the regime drift is removed (excess ≡ 0 per date) |
| 3 · path | label_barrier PASS (triple barrier, stop-first on double touch); label_direction path-blind | Fixed 20-session horizon **by design**: the Desk has no per-trade stop, so the label matches how the book trades. A stop-managed swing system would need triple-barrier labels. |
| 4 · untradeable bars | PARTIAL — 12-calendar-day cap ✓, jump filter ✓; no circuit/series checks (Yahoo source) | **FIXED tonight** — `y_elig` + `y_elig_reason` (EQ, ≥₹20, ₹1 cr median turnover, entry bar exists, entry not locked) |
| 5 · implementation | PASS — NaN kept, rows dropped, adjusted prices | **FIXED tonight** — see the self-caught deviation below |
| (overlap) | ML Engine purges 5 + embargo 5 (right for 5d) | lag-1 autocorr **0.935** measured; manifest prescribes purge ≥ 20 sessions |

## Measured on this repo's data (production label, liquid EQ, 2020-06 → 2026-10, 1.81 M rows)
- Close entry credits **+30.3 bps per trade** of overnight gap that cannot be executed (mean 5-day
  return +46.3 bps close-entry vs +16.0 bps from the next open). The review measured +18.1 bps on a
  one-year window of a different codebase; the mechanism is the same and it is larger here.
- **20.9%** of production "UP" labels would not beat the real ICICI round trip from the executable entry.
- Production P(UP) swings **24.4% → 72.9% by month**: the label mostly encodes the market regime.

Conclusion: do not use the production label (or the ML Engine's default dataset) for new
research. Use the v2 matrix's `y_rank_20d_desk` (the label the ML-labels study validated) or
`y_rank_20d`. The legacy pipeline was left untouched; it is dormant.

## Self-caught deviation in the first v2 build (fixed: Amendment 1)
Re-reading the canonical study (`scripts/ml_label_study.py:314–317`) against the review exposed two
deviations in the v2 build from earlier the same night:
1. **Unclean windows were not masked before computing excess.** That let 232 data-break windows pollute their dates'
   benchmark means and ranks. The clean window was also 20 sessions where the study uses h+1 = 21.
2. **The broad label universe had no liquidity floor and no entry-fillability check.**

Both are fixed. The amendment is recorded in the build script's docstring, with the original spec text left in place, before any
model was trained. Effect: 83.0% of rows are trainable. Excluded rows: illiquid 127.5K, non-EQ
series 118.9K, below ₹20 32.8K, no entry bar 1.2K, locked entry 1.0K. The study's exact Desk
universe now ships as its own label set (`y_desk_universe`, `y_rank_20d_desk`; 420.6K rows).
There are 10 definition/leak tests.

## Where the review does not transfer
- **Costs:** its model is a discount broker (≈22 bps statutory plus ₹0–20 per order), giving τ = 60 bps.
  On ICICI MoneySaver the break-even is ≈93 bps plus ₹24 DP (`shared/trading_costs.py`). Any
  up/down hurdle here must be at least that, so the review's τ is too low for this account.
- **Triple barrier:** this is the right tool for a stop-managed 2–5 day swing book. The repo's evidence says
  that book loses to ICICI costs (the legacy autopilot is OFF for that reason). Keep triple-barrier labels for
  meta-labelling or veto research, which is the queued ML-veto lead, and not as the main label.

# SuryaDhana roadmap: what is done, what stays open, and the exact next action for each

**Date:** 2026-10-22 · **Inputs:** `ml/PROGRAM_REPORT.md`, `ml/IMPROVEMENT_PLAN.md`, `ml/results/improve/IMPROVEMENT_RESULTS.md`, `ml/GOALS.md`.

The program's standing verdict is unchanged by anything found so far: a real, small, now better-measured signal; a long-only construction that beats the equal-weight universe on paper; no proof that survives multiple-testing deflation; no capital. This file lists what remains between that state and each stage of `ml/GOALS.md`, in the order the evidence says to do it, with the data each item needs and whether it is reachable from this environment.

## 1. Done in the improvement phase (see `ml/results/improve/IMPROVEMENT_RESULTS.md`)

Data integrity (sessions, corporate actions, ETFs; v2 and ten-year datasets) · deliberate volatility+size neutralisation (B1 pass) · turnover levers measured (B2/B3 fail) · name-level cost model · probability of backtest overfitting · delivery durability test · overlapping-label tests (closed) · four external feature families built point-in-time with a placebo for the one with look-ahead · 2016-2021 history loaded · eight A/Bs on external data (one real, sub-threshold gain: F&O; sector gains shown to be look-ahead by a placebo) · ten-year re-runs: the signal holds in every calendar year 2018-2026 and the neutral book beats the universe in each, while its liquid version earns nothing over ten years.

## 2. Stage 1 → Stage 2: what the paper book needs (reachable here)

1. **Freeze the construction and start the forward record.** The candidate is now a deliberate book: LightGBM on the 52 features, score residualised per date on volatility and size ranks, full-universe top decile (or the buffered decile, which cut turnover 18-26% at no cost), 20-session hold, equal-weight universe benchmark; the liquid-tercile version runs alongside as the capacity test, because over ten years it has earned nothing (+1.2%/yr, interval including zero) while the full-universe book beat the universe in every year. Write the specification into `ml/PROGRAM_REPORT.md` §10 and run the daily job. Nothing else shortens the time to Stage 2: at the observed liquid-book IR (about 0.8 to 1.0) the PSR 95% hurdle needs three to four years of live record; at the full-universe IR (about 2) it needs about one year, but that book's capacity is about ₹160 to 280 crore depending on the scorer.
2. **Monitoring as specified** (program report §10 alerts), plus two additions from this phase: the per-date correlation of the live score with `atr_pct` and `log_turnover` after neutralisation (must stay within ±0.05), and the residual delivery IC (the durable part), not the raw one.
3. **Realistic costs for the paper book:** replace the pessimistic Corwin-Schultz spread with quoted spreads once an order-book or tick feed is available; until then report both the 20 bps and the name-level figures.

## 3. Signal: what could still raise the information coefficient (ranked by mechanism strength and reachability)

| Item | Mechanism | Data | Reachable from this environment | Status |
|---|---|---|---|---|
| Market-state conditioning, sector-relative momentum, F&O positioning, FII/DII flows | regime conditioning; industry momentum; informed-trader positioning | built (P3) | yes (archive) | tested: F&O +0.0020 AUC (real, below the bar); the rest add nothing; sector = look-ahead |
| Industry classification that is point in time | removes the look-ahead in today's index lists | historical index constituent changes (NSE press releases; niftyindices.com rebalancing notices) | partly (press-release PDFs on the archive are not parsed) | open; placebo control in place |
| Fundamentals: value, profitability, accruals, earnings surprise | the largest documented cross-sectional premia | quarterly results and shareholding patterns (NSE/BSE corporate filings; `www.nseindia.com` API is blocked here; the PR bundles' `an` announcement files carry the filing text) | announcements yes, structured financials no | open; needs a filings feed or a vendor |
| Analyst revisions, institutional holdings by stock | post-revision drift; smart-money flow | vendor data; quarterly shareholding patterns (NSE API) | no | open |
| News and announcements (NLP) | event drift | `an<date>.txt` in every PR bundle, 2016 onward (on disk already) | yes | open; a defined study with a pass mark before any model |
| Intraday / order-book | microstructure, realistic spreads | tick data (vendor) | no | open |

## 4. Proof: what raises confidence without new signal

1. **Ten-year folds** (2018-01 to 2026-07, 103 months): done; the Stage-0 criteria hold over eight years and the "one regime" caveat is closed (`ml/results/improve/IMPROVEMENT_RESULTS.md` §9).
2. **Combinatorial purged cross-validation** for the final frozen configuration (one path is one draw): reachable; about one day of compute at 2 threads for the LightGBM control.
3. **The forward record** (section 2). No backtest can replace it.

## 5. Not planned

Transformers, foundation models, reinforcement learning, more bhavcopy-derived feature engineering, feature selection: the evidence in `ml/PROGRAM_REPORT.md` §5-§6 and this phase (AB0, AB7, AB8) is against spending on them.

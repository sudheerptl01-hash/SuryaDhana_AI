# SuryaDhana roadmap: what is done, what stays open, and the exact next action for each

**Date:** 2026-10-23 (after improvement phase 2) · **Inputs:** `ml/PROGRAM_REPORT.md` (§13, §14), `ml/IMPROVEMENT_PLAN.md`, `ml/IMPROVEMENT_PLAN_2.md`, `ml/results/improve/IMPROVEMENT_RESULTS.md`, `ml/results/improve2/IMPROVEMENT_RESULTS.md`, `ml/GOALS.md`, `ml/PROCESS.md`.

The program's standing verdict is unchanged: a real signal, now measured over ten years; a volatility+size-neutral long-only construction that beats the equal-weight universe in every year on paper; no proof that survives multiple-testing deflation; no capital. Phase 2 added one model-side gain above the bar (an expanding training window, exploratory) and closed five ideas with evidence. This file lists what remains between that state and each stage of `ml/GOALS.md`, in the order the evidence says to do it, with the data each item needs and whether it is reachable from this environment.

## 1. Done

**Phase 1** (`ml/results/improve/IMPROVEMENT_RESULTS.md`): data integrity (sessions, corporate actions, ETFs; v2 and ten-year datasets) · deliberate volatility+size neutralisation (B1 pass) · turnover levers measured (B2/B3 fail) · name-level cost model · probability of backtest overfitting · delivery durability · overlapping-label tests (closed) · four external feature families with a placebo · 2016-2021 history · eight A/Bs on external data (one real, sub-threshold gain: F&O) · ten-year re-runs.

**Phase 2** (`ml/results/improve2/IMPROVEMENT_RESULTS.md`): the forward record started (2026-10-19, four books; six since spec amendment 10 on 2026-10-23) · a liquid-universe model (Q3, FAIL: restricting the training universe loses information) · an F&O long-short through stock futures (Q4, FAIL: the hedge works, the short leg loses net of carry and costs) · a 40-day horizon (Q5, FAIL) · announcement events from 2,488 PR bundles (4,956,205 announcement records, 91,226 board-meeting list rows; Q6, FAIL: the earnings-reaction drift is real but already in the model) · nested hyper-parameter tuning (Q7, FAIL) · combinatorial purged CV (Q2, ROBUST, 7/7 paths) · an expanding training window (Q9, PASS on both marks, exploratory) · seed calibration of paired book tests (Q10, the Q9 gain is REAL) · gates at N = 270 (gate 1 passes for the expanding window; no capital).

## 2. Stage 1 → Stage 2: the forward record (reachable here; this is the critical path)

1. **Run the daily job on every trading day** (owner: a named operator on the machine that holds `nse_market.duckdb` and `ml/paper/state/`; `ml/paper/RUNBOOK.md`; prompt 2 of `ml/PROMPT.md`). One command after 19:00 IST; commit the ledger. Until the scheduled task of RUNBOOK section 7 exists, a missed evening is caught up by the next run, but a missed special session is not (a session cannot be inserted before the ledger's last one; RUNBOOK section 6). Nothing else shortens the time to Stage 2. The PSR 95% hurdle against SR* = 0 needs, at the backtest Sharpe, skew and kurtosis net of 20 bps (`ml/results/improve/ab/10y_p2/books.json`, `dsr.270.min_track_record_periods_psr95_vs_0`), about 72 sessions of live record for the expanding full-universe book (IR 3.06; 72 to 76 over its seeds) and 126 for the rolling one (IR 2.32), roughly three and a half to six months, and about 1,109 sessions, four and a half years, for the capacity-bearing expanding liquid book (IR 0.78; 926 to 1,241 over its seeds). Stage 2 also needs twelve months without a monitor alarm (three are at alert now, item 5) and gate 5 on the liquid book, so the earliest Stage-2 review is not before late October 2027.
2. **Before 2026-11-08:** add the Muhurat session to `ml/paper/calendar_live.json` once the exchange announces it (runbook calendar section). Without it, the first tranche's exit moves from 2026-11-18 to 2026-11-19.
3. **Keep free disk above about 5.5 GB** (the backup taken before each store write).
4. **Champion-challenger reads (owner: program lead), under the rule registered in `ml/paper/SPEC.md` section 6 (amendment 11, committed before any live month matured).** Six-month read after 2027-04-19: descriptive only. Twelve-month read after 2027-10-19: the expanding window replaces the rolling window in the book of record (through a new pre-registered plan) only if the mean paired monthly excess `challenger_expanding` − `primary` is above zero, the expanding score's monthly rank IC beats the rolling score's in at least 7 of 12 live months, and neither expanding book has a `paper_active_ir_6m` alert. Otherwise both run on; after 2028-10-19 a switch needs the paired interval above zero, and a mean at or below zero stops the expanding books. The twelve-month rule cannot be "the interval excludes zero": the seed-averaged backtest gain is +4.44 pp a year [+2.90, +5.97] over 105 months (`ml/results/improve2/seeds/seeds.json`), so twelve live months give an interval of about ±4.5 pp. The capacity pair is reported, not decisive. No further backtest decides this. Do not search window lengths on the backtest: each length is a new trial, and the forward record is the test.
5. **Monitoring as specified** (`ml/paper/SPEC.md`, program report §10 and §13.7). Two monitors were at alert at inception (feature drift on `ret_126d`; a pre-inception inversion month), and since amendment 10 the expanding challenger's `neutral_score_corr` (0.048 to 0.058 against 0.05, the `log_turnover` term; `ml/paper/RUNBOOK.md` section 8); watch whether they clear.
6. **Realistic costs:** replace the pessimistic Corwin-Schultz spread with quoted spreads once an order-book or tick feed is available; until then report both the 20 bps and the name-level figures. The expanding liquid book's edge after name-level costs is +0.6% a year, so this item decides whether the capacity book is worth anything.

## 3. Integrity items (reachable here; small)

1. **Three research-period consolidations are unadjusted** in the research store (KAUSHALYA 2024-01-12 ratio 100, SHEKHAWATI 2024-08-28, VERTOZ 2025-06-25, both ratio 10). Cause: `ml/integrity/corporate_actions.py` `RE_CONSOL` misses the "CNSLDATN"/"CNSLDTN" spelling, and events with an empty ex-date field are dropped. Next action: port the paper's parser extension (`ml/paper/ingest.py` `ca_extension`) into `ml/integrity/`, rebuild the feed under the lock, and re-run the control on the ten-year data to confirm nothing moves (their jump rows are not universe rows of `ml/data_10y`, so no change is expected).
2. **The `y_clean_20d` screen is forward-looking.** Research books exclude the 0.33% of rows it masks (mostly crashes), which flatters research excess by about 0.4 pp a year; the live books hold every name. Next action: report research books both ways in the next cycle so the live-versus-backtest comparison is like-for-like.
3. **Training-time monitor for the expanding model:** about 100 s per fit at 2.1 million rows and growing; the monthly retrain in the paper job takes longer each month. Check at each retrain that the job finishes inside the evening window.

## 4. Signal: what could still raise the information coefficient (ranked by mechanism strength and reachability)

| Item | Mechanism | Data | Reachable from this environment | Status |
|---|---|---|---|---|
| Training history | a model that remembers earlier sell-offs ranks better in the next one | already in the store | yes | **done (Q9): +0.0079 AUC, rank IC 0.088 → 0.103**; in the forward record as a challenger |
| A logistic benchmark on an expanding window | makes gate 1 a like-for-like comparison | already in the store | yes | open; one configuration, register it before running |
| Fundamentals: value, profitability, accruals, earnings surprise | the largest documented cross-sectional premia | quarterly results and shareholding patterns (NSE/BSE filings; the `www.nseindia.com` API is blocked here) | announcements yes, structured financials no | open; needs a filings feed or a vendor |
| Analyst revisions, institutional holdings by stock | post-revision drift; smart-money flow | vendor data; quarterly shareholding patterns (NSE API) | no | open |
| Industry classification that is point in time | removes the look-ahead in today's index lists | historical index constituent changes (NSE press releases; niftyindices.com notices) | partly (press-release PDFs are not parsed) | open; placebo control in place |
| Market state, sector-relative momentum, F&O positioning, flows | regime conditioning; informed positioning | built | yes | tested (phase 1): F&O +0.0020 AUC (real, below the bar); the rest add nothing |
| Announcements and earnings reaction | event drift | PR-bundle `an` files 2016 onward | yes | **tested (Q6): FAIL**; `ear_3d` IC +0.042 (t 7.9) is real but mostly spanned; retry only with filings data that fills its 2022-2024 coverage gaps |
| Intraday / order-book | microstructure, realistic spreads | tick data (vendor) | no | open |

## 5. Proof: what raises confidence without new signal

1. **Ten-year folds:** done (phase 1).
2. **Combinatorial purged cross-validation:** done (Q2, robust 7/7 for both neutral books).
3. **Seed calibration:** done for the control and the expanding window (Q10). Any new paired book comparison registers seed replicates (`ml/PROCESS.md` step 9).
4. **The forward record** (section 2). No backtest can replace it.

## 6. Closed with evidence; do not retry without new information

Transformers, foundation models, reinforcement learning, more bhavcopy-derived feature engineering, feature selection (program report §5-§6; phase-1 AB0, AB7, AB8) · a liquid-universe-only model (Q3) · a futures-hedged long-short at current carry and costs (Q4) · a 40-day horizon (Q5) · announcement-event features from the PR-bundle `an` files (Q6; retry only with a filings feed that fills the 2022-2024 coverage gaps) · hyper-parameter tuning of the champion (Q7).

## 7. Decisions needed from management

1. **A persistent machine or scheduled task for the daily job** (`ml/paper/RUNBOOK.md` section 7, described but not created). The forward record is the critical path, and today it depends on one person running one command every trading evening on the machine that holds the store.
2. **Whether to buy a structured filings or fundamentals feed** (quarterly results, shareholding patterns): the one open signal item with a strong documented mechanism (section 4). The `www.nseindia.com` API is blocked from this environment.
3. **Whether to buy order-book or tick data for realistic costs** (section 2 item 6). It decides whether the capacity book is worth anything: the expanding liquid book's edge after name-level costs is +0.6% a year.

**Next research cycle (owner: program lead).** Register `ml/IMPROVEMENT_PLAN_3.md` before any phase-3 job, with the reachable items: the expanding-window logistic benchmark (section 4), research books reported both ways on `y_clean_20d` (section 3 item 2) and the consolidation fix (section 3 item 1). Proposed date: by 2026-11-30, after the first November retrain and the first tranche exit (2026-11-18) have run cleanly; the program lead confirms or moves it. The forward record runs regardless and is not part of any research plan.

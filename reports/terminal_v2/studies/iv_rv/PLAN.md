# TV-IVRV · Do the IV − RV spread and the IV percentile forecast NSE index volatility or returns? Pre-registered plan

Written Thu 5 Nov 2026, 07:57–07:59 IST (file final 07:59:09 IST; B8-STUDIES, Terminal v2 wave 1) **before any result was computed** (inputs build started 08:06:01, first result 08:15:55): no
statistic of this plan, no forward window and no traded leg had been looked at when this file was written. The only
numbers known were descriptive (R-IV §3: the prototype agrees with the product's ATM IV at corr 0.998 and with India VIX
at 0.983; IV rank 21 / percentile 60 on 4 Nov). Script: `scripts/terminal_studies/tv_ivrv.py` (inputs:
`scripts/terminal_studies/build_inputs.py`). Registry: `reports/terminal_v2/STUDIES.md`. Owner context: Terminal v2 PLAN
§0.1 (#1, #14) and §1 (B8). Nothing in this study feeds the Decision Desk, the S1 shadow, a directional alert, the paper
ticket's price or OSTR's default IV (PLAN §0.8); a PASS changes a badge only through a FINDINGS row, the PM and the
owner's separate approval. **No study result reaches a badge without the PM.**

## Question

Every options vendor that prints an "IV percentile" chip or an "IV − RV premium" panel implies a forecast:

1. **the seller's claim** — when IV is rich (high IV − RV spread, high IV percentile), the volatility actually delivered
   over the next month falls short of the IV paid by more than usual, so selling premium then pays better;
2. **the information claim** — the option market's IV carries information about next month's realised volatility beyond
   what trailing realised volatility already says;
3. **the "buy fear" claim** — a high IV percentile (fear) precedes a higher index return over the next month.

Does any of the three hold for NIFTY (graded) and NIFTY BANK (replication) at the 20-session horizon, after costs, in
both halves of the sample? Terminal v2 shows `iv30_cm`, `iv_pctile_252`, `iv_rank_252` and `iv_minus_rv20` with
`arithmetic` / `context` badges; this study decides whether any of them may ever carry more.

## Data (stored; no network; read-only)

- **IV (production):** `iv_summary_daily` (`model_version = b76-pcp-v1`), columns `iv30_cm`, `iv_pctile_252`,
  `iv_rank_252`, `monthly_atm_iv`, `quality_flags`, for `symbol IN ('NIFTY', 'BANKNIFTY')`, read on a read-only
  snapshot copy (`--db`; never the live `data/market.duckdb` in an IST busy window — `scripts/gold_studies/common.py`
  `open_snapshot` rule).
- **IV (vintage / provisional path, PLAN §0.3 amendment):** the same rows recomputed from the cached NSE F&O
  bhavcopies under `data/nse_archive/fo/<year>/` (read-only; 1,760 files: legacy `foDDMONYYYYbhav.csv.zip`
  2019-10-01 → 2024-07-05, UDiFF `BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip` 2024-07-08 → 2026-11-04) by the
  production code itself: `fo_iv.files.load` → `fo_iv.iv_eod.compute_day(symbols={NIFTY, BANKNIFTY})`, the 252-session
  rank and percentile by `fo_iv.iv_eod.rank_and_percentile` on `iv30_cm` (falling back to `monthly_atm_iv`, as
  production does), written by `build_inputs.py` to a scratch DuckDB under `~/.suryadhana_pm_scratch/` (never `data/`).
  Results from this path are labelled **PROVISIONAL** until the stored-table run (after the owner-approved O-T4
  backfill) reproduces them.
- **Index closes:** NSE's daily index file closes (`ind_close_all`). Production: `index_ohlc_daily` (`NIFTY 50`,
  `NIFTY BANK`, source `nse_daily_file`) where stored; history before it from
  `data/nse_archive/derived/index_valuation_history.csv` (the same NSE file's closes, 2012-02-21 → 2026-10-30,
  1,777 sessions since Sep 2019); sessions after its last row from the UDiFF file's `UndrlygPric`. Never Yahoo.
- **Straddle prices (traded leg):** the per-strike `ClsPric` / `TtlTradgVol` (legacy `CLOSE` / `CONTRACTS`) of the
  NIFTY / BANKNIFTY options in the same cached files (`study_fo_contracts`, written by `build_inputs.py`); settlement =
  the index close on the expiry date (NSE settles index options on the closing index value).
- **Data-quality gates (run before any statistic; a failure stops the study with exit 4):**
  (i) on the UDiFF era the recomputed NIFTY `iv30_cm` matches `reports/terminal_v2/R-IV/iv_compare_NIFTY.csv` with a
  median |difference| ≤ 0.05 vol-pt (the G2 replay rule); (ii) where a stored `rv20_cc` exists it matches the study's
  recomputation within 0.01 vol-pt on ≥ 99 % of rows; (iii) rows flagged `no_cm30` are dropped from S1/S2/S3 (no
  fallback to the near series — the saw-tooth R-IV §3 warns about).

## Release alignment (the look-ahead guard)

The F&O bhavcopy for session T is published ≈ 20:10 IST on T (R-DATA §4; the `iv_eod` job runs after it), so a signal
dated T is first actionable at the **close of T+1**. Every forward window starts there: realised vol and returns use the
closes T+1 … T+21 (20 returns); the straddle is sold at the T+1 close. Expanding statistics (terciles, the 252-session
percentile) use values strictly before the decision date.

## Signals (fixed)

- **S1 · spread** = `iv30_cm(T) − rv20_cc(T)` in vol points, `rv20_cc` = √252 × 100 × stdev of the 20 log close-to-close
  returns ending T (the production `realised.close_to_close` formula).
- **S2 · IV percentile** = `iv_pctile_252(T)` (share of the prior 252 sessions' `iv30_cm` below today's).
- **S3 · IV rank** = `iv_rank_252(T)` — reported as a robustness row, **not graded** (a monotone cousin of S2).

## Targets (fixed)

- **RVF** = √252 × 100 × stdev of the 20 log returns close(T+1) → close(T+21).
- **VRPR** (the seller's realised edge) = `iv30_cm(T) − RVF`, vol points.
- **RET** = 100 × (close(T+21) / close(T+1) − 1), %.

## Graded statistics (signed: the registered direction is the claim's)

| Id | Claim | Statistic | Registered sign | Ceiling |
|---|---|---|---|---|
| G1 | seller's claim | OLS slope of VRPR on S (univariate), Newey-West t (Bartlett, 19 lags) | **+** | PASS (with its traded leg TL1) |
| G2 | information claim | partial slope b of S in RVF = a + b·S + c·rv20_cc(T), Newey-West t (19 lags) | **+** | CONTEXT-ONLY (a description of the vol forecast; nothing is traded on it) |
| G3 | buy-fear claim | OLS slope of RET on S, Newey-West t (19 lags) | **+** | PASS (with its traded leg TL2) |

Each for S ∈ {S1, S2} and each underlying: 6 graded entries per underlying. NIFTY decides the badge question for the
index panels; NIFTY BANK is the replication (a NIFTY PASS with a NIFTY BANK t ≤ −2 in the opposite sign is capped at
CONTEXT-ONLY).

## Traded legs (walk-forward, after costs)

Nothing is fitted. The only learned quantity is the tercile cut-off: **top tercile** = S(T) ≥ the 2/3 quantile of S over
all sessions strictly before T, with ≥ 252 prior observations (the first 252 sessions are warm-up, never graded). One
tranche per session.

- **TL1 (G1, short premium when rich):** when S(T) is in its top tercile, sell the NIFTY (NIFTY BANK) ATM straddle at
  the close of T+1 and hold it to expiry. Expiry = the listed expiry whose calendar days-to-expiry from T+1 is closest to
  30 among those with 21–45 days; strike = the listed strike nearest that expiry's T+1 forward (`iv_expiry_daily.forward`,
  the parity forward) with **both** legs traded (volume > 0) on T+1; if none within ±1 % of the forward, no tranche.
  P&L (% of the forward F) = 100 × (C + P − |S_E − K|) / F − cost; S_E = the index close on the expiry date.
  The benchmark is the **unconditional seller** (the same straddle sold every session). Graded: (i) mean P&L of the
  top-tercile tranches minus the mean of all tranches, Newey-West t with 21 lags (tranches overlap), and (ii) the
  top-tercile seller's own mean P&L after costs, Newey-West t (21 lags) — **both** signed > 0 with t ≥ 2 in the full
  graded span and in both halves.
- **TL2 (G3, buy fear):** long NIFTY (the cash instrument NIFTYBEES) for 20 sessions when S(T) is in its top tercile,
  else flat; positions smoothed over the 20 overlapping tranches; excess return vs buy-and-hold scaled to the rule's
  average exposure (`scripts/gold_studies/common.evaluate_long_flat`), Newey-West t (19 lags); signed > 0 with t ≥ 2 in
  the full graded span and in both halves.

## Costs

- **Cash legs (TL2):** `shared/trading_costs.py`, `default_model()` (COST_PROFILE default `icici_moneysaver`), delivery
  round trip on ₹1,00,000 per tranche (≈ 0.93 % on 5 Nov 2026; the value used is recorded in `summary.json`). The project
  floor (0.15 % per round trip, ≈ a NIFTY-futures expression) is run as a **sensitivity, not graded**.
- **Option legs (TL1):** `shared/trading_costs.py` prices cash equity only (no F&O schedule; it is frozen). The study
  charges a dated F&O schedule written in `scripts/terminal_studies/common.py` (`FnoCosts`, as of Nov 2026, the builder's
  reading — verify against a contract note): STT 0.15 % of premium on the sell order and 0.15 % of the intrinsic value of
  an exercised leg at expiry; exchange 0.03503 % of premium per order; SEBI ₹10/crore; stamp 0.003 % on buys; GST 18 % on
  brokerage + exchange + SEBI; brokerage ₹20 per order expressed as 0.10 % of premium; a half-spread of 0.50 % of premium
  per order; never below the project floor of 0.15 % of the premium per order. A lower true schedule only makes the test
  easier, so a FAIL stands; a PASS is re-run on the owner's contract-note numbers before it is reported.

## Halves

H1 = graded start → **30 Sep 2023**; H2 = 1 Oct 2023 → the last session with a complete forward window. (Graded span
≈ Oct 2020 → Oct 2026 after the 252-session warm-up of the percentile and terciles on files from 1 Oct 2019.)

## Verdict rule (binding; vocabulary of `scripts/gold_studies/FINDINGS_ROW_TEMPLATE.md`)

- **PASS** — the statistic's t ≥ 2 **in the registered direction** in the full sample and in both halves, **and** its
  traded leg (TL1 for G1, TL2 for G3) meets the after-cost condition above, **and** no negative control voids it, **and**
  the N4 cap does not apply. A PASS is a `signal` *candidate* only: the PM and the owner decide; nothing feeds a trade.
- **CONTEXT-ONLY** — the statistic's t ≥ 2 in the registered direction in the full sample only; or the statistic
  passes but the traded leg fails after costs; or G2 passes (its ceiling); or a cap below applies.
- **FAIL** — everything else, including a t ≥ 2 in the *opposite* direction (a sign flip was never registered).
- **VOID** — a negative control N1–N3 meets the PASS condition for that statistic (badge = FAIL).
- **PENDING** — the inputs are not stored yet (exit 3) or the sample is below the minimum (exit 4).
- Badge consequence: anything but PASS leaves the panels as they are (`arithmetic` for IV / rank / percentile,
  `context` for the spread), with the evidence line "no forecasting power (TV-IVRV, <date>)" where the row is FAIL.

## Negative controls (pre-registered; a control that "passes" voids the statistic it shadows)

- **N1 · placebo lag:** S lagged by 250 sessions (a year-old number) must FAIL G1–G3.
- **N2 · circular shift:** S rotated by half the sample length (keeps its autocorrelation, breaks the alignment) must
  FAIL G1–G3.
- **N3 · permutation:** S permuted across dates (seed 20261105) must FAIL G1–G3.
- **N4 · option-free spread (structural cap, S1 only):** S1* = `rv60_cc(T) − rv20_cc(T)` (no option price in it). If
  S1* meets the same G1 or G2 condition with |t| at least S1's, S1's verdict on that statistic is capped at
  CONTEXT-ONLY: the effect is realised-vol mean reversion, not information in the option price.

## Multiple testing

2 signals × 3 statistics × 2 underlyings = 12 graded entries (+ S3 robustness rows + the cost sensitivity). At a 5 %
level about 0.6 entries would show |t| ≥ 2 in the full sample by chance; the both-halves condition, the signed rule, the
after-cost traded leg and N1–N4 are the guard.

## Minimum sample

≥ 750 graded sessions per underlying for G1–G3 and ≥ 300 TL1 tranches; otherwise exit 4 (`insufficient history`).

## Prior and what each outcome would mean

Honest prior, from the international literature (Christensen-Prabhala 1998; Bollerslev-Tauchen-Zhou 2009; the VRP being
positive on average) and the R-IV descriptive numbers: **G2 likely PASS as a description** (IV knows something about
next month's vol beyond trailing RV) → CONTEXT-ONLY by ceiling; **G1 likely CONTEXT-ONLY or FAIL** (sellers earn on
average, but timing by the spread is weak and the straddle's costs are real); **G3 likely FAIL** (a 20-session "buy
fear" rule against a 0.93 % cash round trip). A G1 PASS would be the first `signal` candidate in F&O and would still need
the PM, the owner and a re-run on contract-note costs.

## Outputs

`reports/terminal_v2/studies/iv_rv/`: `summary.json`, `REPORT.md` (every table), `FINDINGS.md` (study-page rows),
`FINDINGS_ROW.md` (4-column rows for an aggregate), `results/*.csv`. Every file carries **PROVISIONAL** while the
inputs come from the scratch recomputation rather than the stored backfilled tables.

## How to run

```bash
P=/Users/sudheer/Desktop/jupyter_env/bin/python
# 1) inputs (scratch DuckDB, recomputed from the cached F&O files with the production fo_iv code; ≈ 30–45 min, resumable)
nice -n 10 $P scripts/terminal_studies/build_inputs.py --fo --out ~/.suryadhana_pm_scratch/v2/B8-STUDIES/inputs.duckdb
# 2) the study (read-only on the inputs; --db a snapshot of market.duckdb once the O-T4 backfill exists)
$P scripts/terminal_studies/tv_ivrv.py --db ~/.suryadhana_pm_scratch/v2/B8-STUDIES/inputs.duckdb --provisional
```

Exit codes: 0 ran · 3 data not yet ingested · 4 insufficient history (or a data-quality gate failed) · 5 the live file
may not be copied now (IST busy window).

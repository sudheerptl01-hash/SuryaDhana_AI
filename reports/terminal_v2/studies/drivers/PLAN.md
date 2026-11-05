# TV-DRIVERS · Do NIFTY's drivers persist, and does a driver change precede anything? Pre-registered plan

Written Thu 5 Nov 2026, by 07:59 IST (file final 07:59:52 IST; B8-STUDIES, Terminal v2 wave 1) **before any result was computed** (inputs build started 08:06:01, first result 08:17:41): no
forward window, persistence statistic or event study of this plan had been looked at when this file was written. The
only numbers known were R-DRIVERS' descriptive ones (fit R² 0.996 / MAE 9.4 pts over 229 sessions; the naive 20-session
leader changed 63 times in 208 sessions, 5 times with hysteresis in 2026). Script: `scripts/terminal_studies/tv_drivers.py`
(inputs: `scripts/terminal_studies/build_inputs.py --drivers`). Registry: `reports/terminal_v2/STUDIES.md`. Nothing in
this study feeds `shared/momentum.py`, `shared/decision_desk.py`, the S1 shadow, a directional alert or the ticket
(PLAN §0.8, §1.2 "nothing enters momentum.py …"). **No study result reaches a badge without the PM.**

## Question

MEMB's DRIVER REGIME strip says "BHARTIARTL has led the 20-session move for N sessions (12.5 % of member points) —
describes, does not predict". The owner's question ("earlier Infosys drove NIFTY, now someone else") invites three
forecasts that the page must not imply unless they hold:

1. **Q1 · share persistence** — does the 20-session leader's share of the index move persist over the next 20 sessions
   by more than its index weight alone would say?
2. **Q2 · signed persistence ("the driver keeps driving")** — does the leader keep moving in the same direction relative
   to NIFTY over the next 20 sessions, enough to pay after costs?
3. **Q3 · driver changes** — does a (hysteresis) leader change precede a different NIFTY return or a vol expansion over
   the next 20 sessions?

## Data (stored; no network; read-only)

- **Production:** `index_contribution_daily` (NIFTY 50: `date, symbol, ret_pct, weight_pct, points, weight_method`),
  `index_contribution_fit` (`actual_points, explained_points, residual_points, members_priced, index_level,
  prev_index_level`), `index_driver_state` (`window_sessions = 20`, `leader`, `raw_leader`, `change_date`), read on a
  read-only snapshot copy (`--db`).
- **Vintage / provisional path (PLAN §0.3 amendment: recompute from the stored inputs):** the same three tables built by
  the production backfill code (`index_drivers.jobs.run_backfill`, B1) into a scratch DuckDB under
  `~/.suryadhana_pm_scratch/` from a **read-only extract** of the evening snapshot `data/snapshots/evening/
  evening-20261030-1920.duckdb` (`nse_bhavcopy` 2010-01-04 → 2026-10-30, `splits`, `nse_shareholding`), the cached XBRL
  share counts `data/nse_archive/financials/<SYM>.json` (`filed_at` = point in time), NSE's index closes
  (`data/nse_archive/derived/index_valuation_history.csv` → `index_ohlc_daily` with source `valuation_history`), and the
  NIFTY 50 list of 4 Nov 2026 (`reports/terminal_v2/R-DRIVERS/evidence/ind_nifty50list.csv`) as the only stored
  `index_constituents_daily` list — production's rule then applies it before its date ("members as of 4 Nov 2026 applied
  before"). No top-10 weight file exists before 4 Nov 2026, so the provisional weights are method `rebuilt`
  (uncalibrated) throughout. Results from this path are **PROVISIONAL**.
- **Survivorship and the fit gate (binding).** Before a point-in-time constituent history exists (Wave 2.9), today's
  members stand in for past ones; the attribution identity measures the damage every day. A session **passes** when
  `members_priced ≥ 45` and the trailing 60-session mean of `|residual_points| / prev_index_level` is ≤ **0.10 %** (G3's
  25-point gate scaled to the level). A decision date T is used only if every session from T−19 to T+21 passes; an event
  in Q3 likewise. The share of sessions passing, by year, is reported first. If fewer than 500 decision dates pass, the
  study stops at **PENDING** (exit 4) until the constituent history exists.
- **NIFTY level:** `index_contribution_fit.index_level` (NSE's closes; never Yahoo).

## Release alignment

`index_drivers_daily` runs at 19:25 IST on T (retry 20:35), so the leader of T is first actionable at the **close of
T+1**. Forward sums use the sessions T+2 … T+21 (the points of session d are the move from close d−1 to close d);
forward returns run close(T+1) → close(T+21).

## Definitions (fixed)

- `W20_i(T)` = Σ points of member i over sessions T−19 … T; `F20_i(T)` = Σ points over T+2 … T+21.
- **Leader** `L(T)` = `index_driver_state.leader` for the 20-session window (hysteresis: a challenger replaces the
  incumbent after 5 consecutive sessions at ≥ 1.3 × its |W20|; production `index_drivers.compute.WINDOWS[20]`).
  **Weight leader** `W(T)` = the member with the largest `weight_pct` on T. **Raw leader** = argmax_i |W20_i(T)|.
- `share_fwd(X, T)` = |F20_X(T)| / Σ_i |F20_i(T)|.
- `s(T)` = sign of `W20_L(T)` (the direction the leader pushed). `R_X(T)` = the compounded return of X from close(T+1) to
  close(T+21) (members: from the stored `ret_pct`, split-adjusted by production; NIFTY: from `index_level`), in %.
- **Leader change event**: a date T with `L(T) ≠ L(T−1)`; events are thinned to non-overlapping ones (an event is kept
  only if it is ≥ 21 sessions after the previously kept event).

## Graded statistics (signed)

| Id | Claim | Statistic | Registered sign | Ceiling |
|---|---|---|---|---|
| D1 | the leader keeps a bigger share of the move than its weight explains | mean of `share_fwd(L,T) − share_fwd(W,T)`, Newey-West t (Bartlett, 19 lags) | **+** | PASS as description (CONTEXT-ONLY at most for a badge) |
| D2 | the driver keeps driving (relative to NIFTY) | mean of `s(T) × (R_L(T) − R_NIFTY(T))`, Newey-West t (19 lags) | **+** | PASS (with its traded leg TL-D2) |
| D3r | a leader change precedes a different NIFTY return | mean of `R_NIFTY(T) − μ_R` over thinned events (μ_R = mean over all gated dates), plain t | none registered (two-sided) | CONTEXT-ONLY |
| D3v | a leader change precedes a vol expansion | mean of `(RVF(T) − rv20_cc(T)) − μ_Δ` over thinned events, plain t; RVF = √252·100·stdev of the 20 log index returns close(T+1)→close(T+21), rv20_cc likewise ending T | **+** | CONTEXT-ONLY |

Robustness (reported, not graded): D1 with the raw leader; D1 as a per-date cross-sectional rank IC (|W20_i| share vs
|F20_i| share, minus weight vs |F20_i| share); D2 / D3 on the 60-session window (1.2 ×, 5 sessions).

## Traded leg (walk-forward, after costs)

**TL-D2:** when `s(T) > 0`, buy the leader in cash at the close of T+1 and hold 20 sessions (one tranche per decision
date; long-only — cash shorts cannot be held overnight); per-tranche excess = `R_L(T) − R_NIFTY(T) − cost`. Nothing is
fitted (the leader rule is production's, fixed). Graded: the mean excess after costs, Newey-West t (19 lags), signed
> 0 with t ≥ 2 in the full sample and both halves. Sensitivity (reported, not graded): the futures pair (long L / short
NIFTY when s > 0, the reverse when s < 0) at the 0.15 % project floor per leg per round trip.

## Costs

Cash leg: `shared/trading_costs.py` `default_model()` delivery round trip on ₹1,00,000 per tranche (≈ 0.93 % on
5 Nov 2026, COST_PROFILE default; recorded in `summary.json`); the benchmark NIFTY leg is charged nothing (conservative).
Futures sensitivity: 0.15 % per leg per round trip (the project floor; above the F&O statutory schedule).

## Halves

H1 = first gated decision date → **30 Apr 2023**; H2 = 1 May 2023 → the last gated date with a complete forward window.

## Verdict rule (binding)

- **PASS** (D2 only) — t ≥ 2 in the registered direction in the full sample and both halves, TL-D2 meets its condition,
  no control voids it, the weight-leader cap does not apply. A PASS is a candidate for the regime strip's wording, never
  an input to any trade; the PM and the owner decide.
- **PASS as description** (D1) — the D1 condition in the full sample and both halves; the strip may then say "leaders
  have tended to keep their share (TV-DRIVERS, <date>)" with a `context` badge.
- **CONTEXT-ONLY** — t ≥ 2 in the registered direction in the full sample only; D2 passing without its traded leg; D3r
  with |t| ≥ 2 in the full sample and both halves (any sign; nothing was registered); D3v meeting the PASS condition
  (its ceiling).
- **FAIL** — everything else, including a t ≥ 2 against the registered sign.
- **VOID** — a negative control meets the condition of the statistic it shadows (badge = FAIL).
- **PENDING** — fewer than 500 gated decision dates (D1/D2) or fewer than 20 thinned events (D3), or the tables are not
  stored (exit 3/4).

## Negative controls (pre-registered)

- **N1 · placebo leader:** at each date a member drawn with probability ∝ `weight_pct` (seed 20261105) replaces L in D1
  and D2: must FAIL.
- **N2 · stale leader:** `L(T−250)` with `s(T−250)` replaces L and s in D2: must FAIL.
- **N3 · shifted events:** the D3 event dates rotated by half the gated sample: D3r and D3v must FAIL.
- **Weight-leader cap (structural, D2):** W replaces L in D2 (with W's own `s`). If W meets the D2 condition with |t| at
  least L's, D2 is capped at CONTEXT-ONLY — the effect is size / beta, not "driving".

## Multiple testing

4 graded entries (D1, D2 with TL-D2, D3r, D3v) + robustness rows. The signed rule, both halves, the after-cost leg and
N1–N3 are the guard; D3 has few events (power is low and the page will say so).

## Prior and what each outcome would mean

Honest prior: **D1 PASS as description** is plausible (|points| ∝ weight × |return| and absolute returns cluster);
**D2 FAIL** (one-month single-stock momentum is weak or reverses in large caps, and the cash round trip costs 0.93 %);
**D3 FAIL or PENDING** (few events). A D2 PASS would change no trade: at most the regime strip's sentence and badge,
through the PM and the owner.

## Outputs

`reports/terminal_v2/studies/drivers/`: `summary.json`, `REPORT.md` (the fit-gate table by year first), `FINDINGS.md`,
`FINDINGS_ROW.md`, `results/*.csv`. **PROVISIONAL** while the tables come from the scratch rebuild with today's
membership.

## How to run

```bash
P=/Users/sudheer/Desktop/jupyter_env/bin/python
# inputs: read-only extract of the evening snapshot + the production index_drivers backfill into a scratch DuckDB (≈ 15 min)
nice -n 10 $P scripts/terminal_studies/build_inputs.py --drivers --snapshot data/snapshots/evening/evening-20261030-1920.duckdb \
    --out ~/.suryadhana_pm_scratch/v2/B8-STUDIES/inputs.duckdb
$P scripts/terminal_studies/tv_drivers.py --db ~/.suryadhana_pm_scratch/v2/B8-STUDIES/inputs.duckdb --provisional
```

Exit codes as in `reports/terminal_v2/studies/iv_rv/PLAN.md`.

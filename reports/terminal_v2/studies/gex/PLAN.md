# TV-GEX · Does a GEX-style dealer-gamma proxy forecast NIFTY's next-day range? Pre-registered plan

Written Thu 5 Nov 2026, by 08:00 IST (file final 08:00:33 IST; B8-STUDIES, Terminal v2 wave 1) **before any result was computed** (inputs build started 08:06:01, first result 08:16:29): no gamma
number, range regression or traded leg of this plan had been computed or looked at. This is the precondition of Terminal
v2 PLAN Wave 3.3 ("B8 study `reports/terminal_v2/studies/gex/PLAN.md` before results, before it may become `context`").
Script: `scripts/terminal_studies/tv_gex.py` (inputs: `scripts/terminal_studies/build_inputs.py --fo`). Registry:
`reports/terminal_v2/STUDIES.md`. Nothing here feeds the Decision Desk, the S1 shadow, a directional alert or the
ticket. **No study result reaches a badge without the PM.**

## Question

US vendors (SpotGamma, SqueezeMetrics, Unusual Whales) chart "dealer gamma exposure": when dealers are long gamma they
hedge against the move (calmer sessions, "pinning"); when short gamma they hedge with it (wider sessions). NSE publishes
no dealer/customer split and no option trade tape, so in India the dealers' sign is an **assumption** (R-WORLD §5 #4,
R-OPTIONS §2) and the proxy carries `heuristic`. Does either sign convention's proxy, computed from the stored F&O
bhavcopy, forecast NIFTY's **next-day range** beyond what recent ranges, the IV level and the expiry calendar already
say — and does the vendor's use of it ("sell premium on long-gamma days") pay after costs?

## Data (stored; no network; read-only)

- **Option surface:** `iv_surface_daily` (NIFTY; production scope: the first three expiries, ±15 % moneyness; `strike,
  opt_type, oi, iv, forward, t_years, r, volume`) and `iv_expiry_daily` (`forward`, `dte`) and `iv_summary_daily`
  (`iv30_cm`). Vintage / provisional path (PLAN §0.3 amendment): recomputed from the cached F&O bhavcopies
  `data/nse_archive/fo/<year>/` (2019-10-01 → 2026-11-04; open interest is in units in both formats — verified on
  4–9 Jul 2024 across the legacy → UDiFF boundary: NIFTY futures OI 15.73 M vs 15.79 M) by production's
  `fo_iv.iv_eod.compute_day` into a scratch DuckDB. **PROVISIONAL** until the stored-table run reproduces it.
- **Next-day range:** NIFTY's own high / low are not stored before `index_ohlc_daily` starts (the NSE closes file on disk
  carries closes only), so the range is measured on the **most-traded NIFTY future** of session T+1 (largest contracts
  traded among NIFTY futures that day) from the cached file of T+1 (`HghPric` / `LwPric`; legacy `HIGH` / `LOW`):
  **Y = 100 × ln(H / L)**. Robustness (reported): the index's own range from `index_ohlc_daily` where stored.
- **Straddle prices (traded leg):** per-strike `ClsPric` / `SttlmPric` / volume in the same files (`study_fo_contracts`).
- **Participant OI (cross-check, not graded):** `data/nse_archive/participant_oi/<year>/fao_participant_oi_DDMMYYYY.csv`
  (contracts; Client / DII / FII / Pro × index call / put long / short), 2019-10 →.

## Release alignment

The F&O file for T is published ≈ 20:10 IST on T; the proxy dated T describes the book at the close of T and is
available before session T+1 opens. The graded target is the range of **session T+1** (the vendor's literal claim). The
traded leg can only act at the close of T+1 with end-of-day prices, so it covers close(T+1) → close(T+2).

## The proxy (fixed)

For session T and NIFTY:

- **Expiries:** the first three listed expiries with days-to-expiry ≥ 1 on T (the contract expiring on T has T = 0 and no
  gamma). **Strikes:** |K / F_e − 1| ≤ 15 %, OI > 0. F_e = the expiry's forward (`iv_expiry_daily.forward`).
- **σ per strike:** the strike's own Black-76 IV from `iv_surface_daily` (the mean when CE and PE both carry one); else
  linear interpolation in log-moneyness ln(K / F_e) between the nearest IV-bearing strikes of that expiry; flat beyond
  the outermost IV-bearing strike; an expiry with fewer than 4 IV-bearing strikes is skipped (flag `few_iv_strikes`).
- **Gamma** (Black-76, identical for CE and PE): Γ = e^{−rT} φ(d1) / (F σ √T), d1 = (ln(F/K) + σ²T/2) / (σ √T), T and r
  from the surface row.
- **Dollar gamma per 1 % move:** DG = Γ × OI(units) × F² × 0.01 (₹).
- **C1 · vendor convention** (dealers long calls, short puts — customers sell calls, buy puts): GEX = Σ_CE DG − Σ_PE DG;
  graded proxy **NGS** = GEX / (Σ_CE DG + Σ_PE DG) ∈ [−1, 1]. Claim: higher NGS → **smaller** next-day range.
- **C2 · "writers are short"** (Terminal v2 PLAN 3.3 wording; dealers short every option): dealer gamma = −Σ_all DG;
  graded proxy **TGL** = ln(Σ_all DG(T) / median of Σ_all DG over the 252 prior sessions) (scale-free short-gamma load).
  Claim: higher TGL → **larger** next-day range.
- **Zero-gamma level** (reported context, not graded): the spot S* in [0.9 F, 1.1 F] of the near expiry where C1's GEX,
  recomputed with every F_e scaled by S*/F (σ, T fixed), crosses zero; distance (F − S*) / F.

## Graded statistics (signed)

OLS **Y(T+1) = a + b·X(T) + c1·Ȳ5(T) + c2·Ȳ20(T) + c3·iv30_cm(T) + c4·EXP(T+1) + e**, where Ȳ5 / Ȳ20 = the mean of Y
over the 5 / 20 sessions ending T (known at T), EXP = 1 when T+1 is a NIFTY expiry day; Newey-West t (Bartlett, 5 lags).

| Id | Proxy X | Registered sign of b | Ceiling |
|---|---|---|---|
| X1 | NGS (C1) | **−** | PASS (with TL-X1) → `context` candidate, never `signal` (the sign is an assumption) |
| X2 | TGL (C2) | **+** | PASS (with TL-X2) → `context` candidate, never `signal` |

Robustness (reported, not graded): the same regression for the range of T+2; the index's own range where stored; NGS
and TGL without the iv30_cm control.

## Traded legs (walk-forward, after costs)

Nothing is fitted; terciles are expanding over strictly earlier values with ≥ 252 observations (the first 252 sessions
are warm-up). One tranche per session; the position is the **near ATM straddle**: the nearest expiry with ≥ 3 calendar
days to expiry on T+1, the strike nearest that expiry's T+1 forward with both legs traded on T+1 (else none within ±1 %
→ no tranche); sold at the close of T+1, bought back at the close of T+2 (`ClsPric` when traded on T+2, else
`SttlmPric`, flagged). P&L in % of the forward after the F&O schedule below.

- **TL-X1 (C1, "sell on long-gamma days"):** sell when NGS(T) is in its top tercile.
- **TL-X2 (C2, "sell when the short-gamma load is light"):** sell when TGL(T) is in its bottom tercile.
- Graded for each: (i) mean P&L of the conditional tranches minus the mean of all tranches (the unconditional one-day
  seller), Newey-West t (1 lag), and (ii) the conditional seller's own mean P&L after costs, Newey-West t (1 lag) —
  **both** signed > 0 with t ≥ 2 in the full span and both halves.

## Costs

`shared/trading_costs.py` prices cash equity only (frozen, no F&O schedule). Option orders are charged the dated F&O
schedule in `scripts/terminal_studies/common.py` (`FnoCosts`, as of Nov 2026, the builder's reading — verify against a
contract note): STT 0.15 % of premium on sells; exchange 0.03503 % of premium per order; SEBI ₹10/crore; stamp 0.003 %
on buys; GST 18 % on brokerage + exchange + SEBI; brokerage ₹20 per order as 0.10 % of premium; half-spread 0.50 % of
premium per order; never below 0.15 % of premium per order (the project floor). Four orders per tranche.

## Halves

H1 = first graded session → **31 Mar 2023**; H2 = 1 Apr 2023 → the last session with a T+1 (T+2 for the legs) file.

## Verdict rule (binding)

- **PASS** — b's t ≥ 2 in the registered direction in the full sample and both halves, the traded leg meets (i) and
  (ii), no control voids it and the OI-only cap does not apply. Consequence: the GEX panel may move from `heuristic` to
  `context` (PM + owner); it can never become `signal` while the dealers' sign is an assumption.
- **CONTEXT-ONLY** — t ≥ 2 in the registered direction in the full sample only; or b passes but the traded leg fails;
  or a cap applies. The panel stays `heuristic` with the evidence line.
- **FAIL** — everything else, including t ≥ 2 against the registered sign. The panel stays `heuristic` with
  "no forecasting power (TV-GEX, <date>)".
- **VOID** — N1–N3 meet the condition of the statistic they shadow (badge = FAIL). **PENDING** — exit 3 / 4.

## Negative controls (pre-registered)

- **N1 · placebo lag:** X lagged 250 sessions must FAIL. **N2 · circular shift** by half the sample must FAIL.
  **N3 · permutation** (seed 20261105) must FAIL.
- **N4 · OI-only placebo (cap for X1):** NOS = (Σ_CE OI − Σ_PE OI) / Σ OI over the same strikes and expiries (no gamma
  weighting). If NOS meets X1's condition with |t| at least NGS's, X1 is capped at CONTEXT-ONLY (a put-call OI ratio,
  not gamma).
- **N5 · OI-load placebo (cap for X2):** ln(Σ OI / its 252-session prior median) in place of TGL; same cap rule.

## Participant cross-check (reported, not graded)

For each session: the Pro and FII net index-call and net index-put positions (long − short contracts) from the
participant file of T. Reported: the share of sessions in which Pro / FII are net short calls and net short puts, and the
agreement between "Pro net short gamma" (short calls + short puts > long) and C1's sign. A convention the participant
file contradicts most days is named in the report; it does not change the verdict rule above.

## Multiple testing

2 graded entries (X1, X2), each with its traded leg; controls and robustness rows are reported. The signed rule, both
halves, the after-cost leg and N1–N5 are the guard.

## Minimum sample

≥ 750 graded sessions with all controls (exit 4 otherwise); ≥ 300 conditional tranches per traded leg.

## Prior and what each outcome would mean

Honest prior: **X1 FAIL** — the vendor convention assumes US customer flow; Indian retail is a net option buyer and the
writers are prop / FII desks, so "customers sell calls" is the wrong story here; **X2 CONTEXT-ONLY at best** — the gamma
load is concentrated in the near expiry, which the expiry dummy and the IV control absorb. Even a PASS leaves the proxy
below `signal` (PLAN 3.3); it would justify showing the panel beside participant OI with a `context` badge.

## Outputs

`reports/terminal_v2/studies/gex/`: `summary.json`, `REPORT.md`, `FINDINGS.md`, `FINDINGS_ROW.md`, `results/*.csv`;
**PROVISIONAL** while the inputs come from the scratch recomputation.

## How to run

```bash
P=/Users/sudheer/Desktop/jupyter_env/bin/python
nice -n 10 $P scripts/terminal_studies/build_inputs.py --fo --out ~/.suryadhana_pm_scratch/v2/B8-STUDIES/inputs.duckdb
$P scripts/terminal_studies/tv_gex.py --db ~/.suryadhana_pm_scratch/v2/B8-STUDIES/inputs.duckdb --provisional
```

Exit codes as in `reports/terminal_v2/studies/iv_rv/PLAN.md`.

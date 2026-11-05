# BILLIONAIRE_SCALE_AUDIT — SuryaDhana_AI

**Mandate:** Forensic capacity & catastrophe audit — can this engine scale a *real* edge from
retail (₹10k) to billionaire-tier institutional AUM (₹100Cr → ₹1,000Cr+) without the edge
silently eroding to zero or a tail event vaporising capital?
**Branch:** `feature/backtest-lab-institutional` · **Mode:** `PAPER` (verified locked, untouched) · **Date:** 2026-06-13
**Auditor:** SuryaDhana-Quant-Architect — acting as Risk Compliance Officer / Head of Quant Execution / Forensic Code Auditor
**Read-only audit.** No active component modified, nothing committed. This is the only file written.

> **Scope discipline.** The prior `SOTA_QUANT_GAP_REPORT.md` + `SOTA_GAP_REMEDIATION_SUMMARY.md`
> identified and remediated G1–G11 (PIT fundamentals, survivorship as-of membership + delist
> force-close, √-law + Amihud impact, HMM regime, DSR/PBO, Fama-French attribution, triple-barrier
> + meta-labeling, purged K-fold, TWAP/VWAP/POV scheduler, fractional Kelly, bounded telemetry).
> **That work is real and is credited here, not re-litigated.** This audit asks a different, harder
> question — *capacity* — and finds that several G1–G11 mechanisms, while present and correct in
> form, are **mis-defaulted, mis-calibrated, or structurally incomplete for billionaire AUM**. The
> bias work made the backtest *honest*; it did not make it *scalable*.

---

## SECTION 1 — THE SCORE

# 🏛️ SAFE-SCALING CAPABILITY: **4 / 10**

**One-line verdict:** *Institutional-grade bias hygiene and a genuine realism stack, bolted onto a
capacity model that is structurally incapable of pricing a billionaire-tier block. The system can
now honestly tell you a retail edge is fake; it cannot yet tell you the truth about a ₹100Cr fill.*

### Why not lower (the floor is held by real engineering)
- **Look-ahead is genuinely controlled.** `resolve_trade_exit` (`backtest_engine.py:391-450`) walks
  the *forward* path with gap-aware fills (`opens` gap-down → fill at open, L432), trails off
  *prior* highs only (L439, never assumes the same-day high preceded the low), and nets round-trip
  friction. Indicator windows are all trailing; VIPT uses `shift(1)` baselines (L185-191). This is
  not a leaky backtester.
- **WFO is real.** `_core_wfo` does per-window IS-optimise → embargo → OOS-stitch and *reports its
  own failure* (the headline VMI+VIPT+BetaDecouple+Intention combo: +114% in-sample → DSR≈0.00,
  PBO=0.15, −36% to −60% MaxDD). The engine already refutes most of its own "edges."
- **Friction floor is respected.** `friction_bps=15.0` default (`resolve_trade_exit:397`) = the
  mandated 0.15% round-trip; never lower.
- **Execution safety envelope is institutional.** `MODE=PAPER` hard default
  (`live_execution.py:107`), 2% daily-loss kill-switch that *cannot be disabled at runtime*
  (`DAILY_LOSS_LIMIT_PCT=0.02`, L38; `check_daily_loss_limit` L748), `asyncio.Lock`-guarded state,
  SQLite audit trail. The live order path is the most mature part of the codebase.

### Why not higher (the ceiling is capacity, and it is a hard wall)
The capacity model has **three structural defects that compound** precisely as AUM grows, and they
are the difference between a 4 and an 8:

1. **The at-scale auto-impact only charges the *temporary* leg and leaves the *permanent* leg and
   the *participation cap* off** (`analytics.py:779-787` sets `ctx.auto_impact = 1.0` but never sets
   `amihud_coef` or `max_participation_pct`). So the engine's own "default-on-at-scale" safeguard
   (G4) auto-enables the *cheapest third* of the cost stack and silently omits the two terms that
   dominate at billionaire AUM — permanent Kyle-λ impact and the physical "you cannot buy more than
   exists" cap. A ₹100Cr run through the auto-path fills **108% of the median name's ADV in a single
   bar** (computed below) and is charged a √-law cost as if that were physically possible.

2. **The auto-impact coefficient is a hardcoded global `1.0`** (`analytics.py:785`), not the
   per-name Amihud coefficient the engine *already computes* (`amihud_illiq`, `backtest_engine.py:160-170`).
   A ₹10Cr order into a p25-liquidity microcap (ADV ₹5.78Cr) and into a top-decile large-cap
   (ADV ₹207Cr) are charged using the *same* coefficient. The endogenous calibration that G4 built
   exists but is orphaned from the auto-path.

3. **Multiple-testing correction is correct *within one run* but blind *across the research
   campaign*.** DSR counts `n_trials = len(surviving_combos)` from a *single* invocation
   (`combinatorial_grid_search.py:390-393`, "43 trials") and there is **no persistent cross-session
   trial ledger** (grep confirmed zero). Every parameter sweep, profile re-run, and the WFO's
   *per-window* combo selection is a free, uncounted trial. At billionaire scale you will run this
   search hundreds of times; the DSR you trust is computed against a denominator that is a small
   fraction of the true search intensity, so it *systematically over-states* an edge's robustness.

### Capacity grade by AUM band (the headline number, grounded in this repo's real ADV)

Universe ADV distribution (1,496 names, last-20-bar dollar volume, queried live from
`data/market.duckdb`): **median ₹18.37Cr/day**, p25 ₹5.78Cr, p10 ₹2.50Cr; only **270 names (18%)
trade > ₹100Cr/day**, only **42 names (2.8%) > ₹500Cr/day**. Universe median ATR% ≈ 3.24%.

| AUM band | Realistic verdict | Engine behaviour today |
|---|---|---|
| ₹10k – ₹10L | Edge survives if real | Impact off (correctly negligible); honest |
| ₹10L – ₹1Cr | Marginal; impact ~0.2–0.7%/trade eats most swing edge | Auto-impact ON, temp-leg only — **under-prices** |
| ₹1Cr – ₹10Cr | Capacity-critical; participation 5–55% of median ADV | **No ADV cap auto-on** → fills the impossible |
| ₹10Cr – ₹100Cr | Most of the universe is untradeable | Engine fills 100%+ of ADV, charges flat coef 1.0 — **fiction** |
| ₹100Cr – ₹1,000Cr+ | Only ~42 names liquid enough; need multi-day POV schedules | **No schedule in backtest**, instantaneous fill assumed |

**A 4/10 means: trustworthy below ₹1Cr, dangerous to believe above ₹10Cr.** The honest path to an 8
is Section 3 + Section 4.

---

## SECTION 2 — FATAL RISK LOG

Severity key: 🔴 Catastrophic (direct capital-destruction / believing a fiction at scale) ·
🟠 High (material mis-pricing of edge or risk) · 🟡 Medium (degrades trust, not immediately fatal).
"Already mitigated?" credits G1–G11 where the *mechanism* exists, and states why it is **still fatal
at billionaire AUM**.

| # | Location (`file:line`) | Flaw | Mechanism of loss | Severity | Already mitigated? |
|---|---|---|---|---|---|
| **C1** | `services/ui-api/routers/analytics.py:779-787` | At-scale auto-impact sets `ctx.auto_impact=1.0` (temporary √-law leg) but **never auto-enables `amihud_coef` (permanent leg) nor `max_participation_pct` (ADV cap)**. | A ₹100Cr+ run fills any size at the printed price minus only the temporary cost; the permanent market-move-against-you and the physical "order > available liquidity" are both uncharged. The headline return at scale is a **fiction that omits the dominant cost terms** → capital deployed on an edge that doesn't survive real fills. | 🔴 | **Partial (G4).** Temp leg auto-on; permanent leg + ADV cap exist (`backtest_engine.py:689-692`, `:673-674`) but are **off unless the user manually passes them**. Fatal because the *default scale path* is the one users trust. |
| **C2** | `services/ui-api/routers/analytics.py:785` | Auto-impact coefficient is a **hardcoded global `1.0`**, not the per-name `amihud_illiq` the engine already computes (`backtest_engine.py:160-170`). | A microcap (p25 ADV ₹5.78Cr) and a large-cap (ADV ₹207Cr) are charged the *same* √-law coefficient. Illiquid-name cost is under-stated by the ratio of their Amihud λ's — the engine's *own* endogenous calibration is bypassed → the backtest favours illiquid names that are uninvestable at scale. | 🔴 | **No** (the calibration data exists but the auto-path ignores it). |
| **C3** | `services/ui-api/backtest_engine.py:670-674`; `analytics.py:860` | When `max_participation_pct is None` (the default, incl. the auto-scale path) the ADV cap is **skipped entirely** — `alloc` is clipped only by `cash`. | At ₹100Cr/5-positions, per-position ₹20Cr = **108% of the median name's ₹18.37Cr ADV**; the engine fills it in one bar. You cannot buy a day-and-a-bit of an entire stock's volume at the close without moving the tape 10–30%. Backtest books a fill that is **physically impossible** → over-stated capacity by orders of magnitude. | 🔴 | **Partial (G4).** Cap *implemented* and unit-tested (`test_backtest_engine.py:468`), but **not auto-on at scale** — the one moment it must fire. |
| **C4** | `scripts/combinatorial_grid_search.py:390-393`; no persistent counter (grep ∅) | DSR `n_trials` = surviving combos **in a single run only** (~43). Parameter sweeps, profile re-runs, and the WFO's per-window combo selection (`analytics.py:_simulate_window` over ≤63 combos *per window*) are **uncounted trials**. | The multiple-testing haircut uses a denominator far smaller than the true search intensity → DSR/PSR **over-state robustness**. At scale you run this search hundreds of times; you will deploy a lucky combo that DSR wrongly certified. The empirical proof is already in the repo: every top combo has DSR≈0.00 *even at the honest count* — the true cross-campaign DSR is worse still. | 🟠 | **Partial (G3).** DSR/PBO correctly wired per-run; the *cross-session trial ledger* the prior report's own blueprint asked for (G3 step 4) was **not built**. |
| **C5** | `services/ui-api/routers/analytics.py:818-835` | Candidate selection sorts by `mktcap_cr` desc (size tilt) and falls back to `adv20` desc when PIT mktcap is NaN — i.e. **selection prefers the largest / most-liquid names**, which is *correct for capacity* but means the **backtested edge is measured on a size-biased subset**, while the alpha factors (VMI, Intention) are microcap-skewed. | The combo's reported Sharpe is generated on names the size-sort *kept*; at scale you are forced into exactly those large names where the factor edge is weakest (factor crowding + lower idiosyncratic vol). Edge measured ≠ edge deliverable. | 🟡 | Partial — `sector_neutral` selection exists (`:820-828`) but is opt-in; default is the raw size sort. |
| **C6** | `services/ui-api/backtest_engine.py:688` | Temporary impact is charged **once, as if the whole parent order executes instantaneously** at entry (`2·coef·ATR%·√(alloc/ADV)`). There is **no participation-of-volume schedule in the backtest** — the 2–5d holding window is not used to *spread* the entry. | A ₹20Cr order modelled as one instantaneous √-law hit *under-states* impact for a block that in reality must be worked over multiple sessions (each session's slice hits thinner liquidity — exactly what `execution_scheduler._U_SHAPE` models in *execution* but not in the *backtest*). Backtest and live diverge precisely at the sizes that matter. | 🟠 | **Partial (G9).** Scheduler exists in `execution-service` (TWAP/VWAP/POV, partial fills) but the **backtest impact model does not call it** → no backtest↔live parity at scale. |
| **C7** | `services/ui-api/backtest_engine.py:428, 431-433` | Per-trade risk control is a **fixed-% stop** (`stop_loss_pct`) by default; ATR-scaled stops (`atr_stop_mult`, `analytics.py:288, 600-603`) are **opt-in**. There is **no daily portfolio max-VaR / max-loss limit inside `simulate_portfolio`** — only a peak-to-trough `max_drawdown_halt_pct` (`backtest_engine.py:624-627`). | A fixed-% stop is too tight in a 6%-ATR storm (stopped out on noise) and too loose in a 1%-ATR calm (rides a loss). With the universe median ATR at 3.24% and grid-search combos already showing **−36% to −60% MaxDD**, a fixed stop is an active capital-destruction vector. No daily-VaR halt means a single gap day can cut deeper than the drawdown-halt notices. | 🟠 | **Partial (G5-extension).** ATR stops + vol-target sizing exist but are **off by default**; no VaR limit at all. |
| **C8** | `services/execution-service/live_execution.py:313-318` | `_update_daily_pnl` persists `daily_loss = -self._tx_costs_today` — i.e. the **dashboard/telemetry daily-loss figure excludes unrealized mark-to-market losses** (comment L316 is explicit). | The *active* kill-switch (`check_daily_loss_limit:753-755`) correctly *does* include unrealized PnL, so capital is protected — but the **operator-facing daily-PnL row under-reports intraday loss**. A risk officer watching the dashboard sees only paid tx-costs and is blind to a −1.9% unrealized hole until the kill-switch fires at −2%. Decision-making on a misleading number. | 🟡 | The kill-switch logic itself is sound; this is a **telemetry/observability** defect, not a control defect. |
| **C9** | `services/ui-api/backtest_engine.py:1007-1039` (`deflated_sharpe_ratio`) | DSR formula assumes **independent trials** (`expected_max_sharpe:994-1005`), but the 63 filter combos are **heavily overlapping** (shared factors). The code's own docstring (`combinatorial_grid_search.py:280`) admits this makes DSR "a conservative lower bound" — yet the *winner-selection verdict* (L335-339) keys off raw DSR thresholds (≥0.95 / ≥0.5) as if independent. | The effective number of independent trials is **less** than nominal, so DSR is conservative *for ranking robustness* — but the inverse error bites at scale: when you *add* a near-duplicate combo, nominal N rises and DSR drops, perversely penalising a robust signal for the search's redundancy. Mis-calibrated trial geometry → wrong combo certified/rejected. | 🟡 | Acknowledged in docstring; not corrected (no effective-N / cluster-adjusted trial count). |
| **D1** | `data/market.duckdb` — `corporate_events`, `splits`, `dividends`, `index_membership`, `delistings` all empty/absent | Survivorship (G2) and PIT-fundamental (G1) mechanisms are **mechanism-complete but data-starved**; `stock_metrics` has 4 snapshot dates (2026-05-26→06-04). | Backtests still run on the **current 1,496 survivors**; the survivorship premium (Brown-Goetzmann-Ibbotson-Ross: +1–4%/yr) is *unquantified*, so every reported CAGR/Sharpe at every AUM is **upward-biased by an unknown amount**. At billionaire scale you are sizing into an over-stated edge. | 🔴 | **Mechanism mitigated (G1/G2), data not.** The engine flags `membership_pit=False`/`fundamentals_pit` — honest, but the bias is *live* until the tables are backfilled. |

**Tally: 9 fatal/material findings (4 🔴 Catastrophic, 3 🟠 High, 2 🟡 Medium) that remain unmitigated
or only partially mitigated *at billionaire AUM*** — distinct from the 11 (G1–G11) the prior audit
closed at retail scale. **C1–C3 + D1 are the four that make the score a 4 and not an 8.**

### 🔴 Single highest-severity unmitigated risk

**C1 + C3 jointly: the at-scale auto-safeguard charges only the temporary impact leg and never
auto-caps participation, so a billionaire-tier run fills 100%+ of a name's ADV in one bar and books
a fiction.** This is the single most dangerous gap because it fires silently on *exactly* the runs
where capital is largest, and it makes the engine's headline number *more* misleading the *more*
capital you deploy — the opposite of what a capacity model must do.

---

## SECTION 3 — MATHEMATICAL REMEDIATION FRAMEWORK

### 3.1 The capacity-decay curve (computed live against this repo's ADV distribution)

Using the engine's *own* temporary-impact functional (`backtest_engine.py:688`) with the auto-path
coefficient `Y = impact_coef = 1.0`, universe median ATR `σ = 3.24%`, `max_positions = 5` (equal
weight, per-position alloc `= AUM/5`), deploying into the **median-liquidity** name (ADV ₹18.37Cr)
and a **p25** name (ADV ₹5.78Cr):

$$\text{Impact}_{\text{rt}}(\%) \;=\; 2\,Y\,\sigma_{\text{ATR}}\sqrt{\frac{Q}{\text{ADV}}}, \qquad Q=\frac{\text{AUM}}{N_{\text{pos}}}$$

| AUM | Per-position Q | Participation Q/ADV (median) | Temp impact % (median ADV) | Temp impact % (p25 ADV) |
|---:|---:|---:|---:|---:|
| ₹1L | ₹0.02L | 0.01% | 0.07% | 0.12% |
| ₹10L | ₹2L | 0.11% | 0.21% | 0.38% |
| ₹1Cr | ₹0.2Cr | 1.09% | 0.68% | 1.21% |
| ₹10Cr | ₹2Cr | **10.9%** | 2.14% | 3.81% |
| ₹100Cr | ₹20Cr | **108.9%** ⚠️ | 6.76% | 12.06% |
| ₹1,000Cr | ₹200Cr | **1,088%** ⚠️ | 21.39% | 38.13% |

**Read-off:** a 2–5d swing edge is typically **1–3% gross**. Net edge → 0 (impact ≥ gross) at:
- **~₹1Cr** for a p25-liquidity name (impact 1.2% ≈ a 1% edge), and
- **~₹5–10Cr** for a median name (impact 1.5–2.1%).

Above ₹100Cr the participation column exceeds 100% of ADV — the √-law itself is **out of its domain
of validity** (it is calibrated for participation ≲ 10%). The engine's omission of `max_participation_pct`
(C3) lets it extrapolate the √-law into a regime where the true cost is super-linear (you walk the
entire book). **This is the mathematical core of the 4/10: capacity is exhausted between ₹1Cr and
₹10Cr for the strategies the grid search actually surfaces (microcap-skewed factors), not at ₹100Cr.**

### 3.2 Complete the impact stack: temporary + permanent + participation domain guard

Replace the single-leg auto-impact with the full Almgren-Chriss / Kyle / Amihud decomposition,
**per-name and capped**:

$$
\Delta_{\text{total}} \;=\; \underbrace{2\,Y_i\,\sigma_i\sqrt{\frac{Q}{\text{ADV}_i}}}_{\text{temporary (Tóth-Lillo-Bouchaud)}} \;+\; \underbrace{\lambda_i\,Q}_{\text{permanent (Kyle 1985)}}, \qquad \lambda_i \propto \text{ILLIQ}_i^{\text{Amihud}}
$$

with the **endogenous per-name** coefficient the engine already computes
(`backtest_engine.py:160-170`):

$$
\text{ILLIQ}_i \;=\; \Big\langle \frac{|r_{i,t}|}{\text{DollarVol}_{i,t}} \Big\rangle_{60\text{d}}, \qquad Y_i = f(\text{ILLIQ}_i) \;\;(\text{calibrate, not } Y_i\equiv 1)
$$

**Hard participation guard** (the missing domain check) — never fill more than a fraction of ADV,
and spread the rest:

$$
Q_{\text{day}} \;\le\; \phi \cdot \text{ADV}_i, \quad \phi \le 0.10; \qquad \text{days-to-fill} = \big\lceil Q / (\phi\,\text{ADV}_i)\big\rceil
$$

**Rule:** auto-enable *all three* (`impact_coef`=per-name `Y_i`, `amihud_coef`=per-name λ, **and**
`max_participation_pct=10`) under the same `per_pos/med_adv > 0.005` trigger that today enables only
the first (`analytics.py:784`).

### 3.3 Dynamic capital allocation — replace equal-weight with risk-parity + fractional Kelly

The book is equal-weight by default (`base = nav / max_positions`, `backtest_engine.py:659`). At
scale, equal-weight over-concentrates risk in the high-ATR names. Use **inverse-vol / risk-parity**
budgeting (the `vol_target_pct` path already does the per-name half of this — make it the default and
add the portfolio constraint):

$$
w_i \;=\; \frac{1/\sigma_i}{\sum_j 1/\sigma_j} \quad\text{(risk parity)}, \qquad \text{s.t.}\;\; w_i \le \min\!\Big(w_{\text{cap}},\, \frac{\phi\,\text{ADV}_i}{\text{NAV}}\Big)\;\text{(liquidity-capped)}
$$

**Fractional Kelly** for the *gross* exposure (the engine's rolling estimator,
`backtest_engine.py:636-643`, is correct — make it size the *book*, not just cap a bet):

$$
f^\star \;=\; \frac{W}{1} - \frac{1-W}{R}, \qquad \text{deploy } \kappa f^\star,\;\; \kappa \in [0.25, 0.5]
$$

where $W$, $R$ are estimated **strictly point-in-time** from the strategy's own closed trades.
Half-Kelly ($\kappa=0.5$) is the institutional norm (full Kelly's variance is ruinous at scale).

### 3.4 Tail-risk: ATR stops on by default + daily portfolio VaR halt

Replace the fixed-% default stop with a vol-adjusted stop (already implemented as opt-in
`atr_stop_mult` — make it the default):

$$
\text{stop}_i \;=\; \text{entry}_i \cdot \big(1 - k\,\sigma^{\text{ATR}}_i\big), \quad k \in [1.5, 2.5]
$$

Add a **daily portfolio VaR / loss governor** inside `simulate_portfolio` (today only a
peak-to-trough drawdown halt exists, `:624-627`):

$$
\text{VaR}_{99,\,1\text{d}} = z_{0.99}\,\sigma_{\text{port}}\sqrt{\Delta t}\,\cdot\text{NAV}; \qquad \text{halt new entries if } \text{realised daily loss} \le -\ell,\; \ell = 2\%
$$

This mirrors the *live* 2% kill-switch (`live_execution.py:38`) inside the *backtest* so sim and live
enforce identical tail limits — and fixes the asymmetry where the backtest can ride a one-day −5% gap
that live would have halted.

### 3.5 Regime-adaptive filter gating — extend the existing HMM to *disable* mean-reversion filters

The 2-state Gaussian HMM (G5, causal forward-filtered posterior $P(\text{bull}\mid \mathcal F_t)$) exists
and soft-throttles exposure. Extend it from a *sizing* throttle to a *filter selector*: a
mean-reversion filter (e.g. Intention pullback) is *toxic* in an expansionary breakout regime and a
breakout filter (VIPT) is toxic in a crash. Let the regime posterior **switch the active filter set**:

$$
P(s_t = k \mid \mathcal F_t) = \frac{P(x_t\mid s_t=k)\sum_j P(s_t=k\mid s_{t-1}=j)\,P(s_{t-1}=j\mid\mathcal F_{t-1})}{\sum_m[\cdots]}, \quad k\in\{\text{bull, bear}\}
$$

$$
\text{active\_filters}(t) = \begin{cases} \{\text{breakout, momentum}\} & P(\text{bull}\mid\mathcal F_t) > 0.6 \\ \{\text{mean-reversion, defensive}\} & P(\text{bull}\mid\mathcal F_t) < 0.4 \\ \text{flat / reduced gross} & \text{otherwise} \end{cases}
$$

A 3-state Gaussian-Mixture (low-vol-bull / high-vol-bear / range) on (realised vol, return skew)
gives a cleaner crash state than the 2-state HMM. Overlay a Bayesian online change-point alarm
(Adams-MacKay 2007) on realised vol to *tighten* $\phi$, $k$, and $\kappa$ for $N$ days after a
structural break.

### 3.6 Cross-campaign multiple-testing — persist a trial ledger and deflate against it

$$
\text{DSR} = \Phi\!\left[\frac{(\widehat{SR}-SR_0)\sqrt{T-1}}{\sqrt{1-\gamma_3\widehat{SR}+\frac{\gamma_4-1}{4}\widehat{SR}^2}}\right], \quad SR_0 = \sqrt{\widehat{\mathrm{Var}}(SR)}\,\Big[(1-\gamma)\Phi^{-1}\!\big(1-\tfrac1N\big)+\gamma\,\Phi^{-1}\!\big(1-\tfrac{1}{Ne}\big)\Big]
$$

The fix is **N**, not the formula. Persist a `research_trials` ledger (every distinct config ever
evaluated, across sessions + WFO per-window selections), and set $N = N_{\text{effective}}$ using a
cluster-adjusted count (collapse near-duplicate overlapping combos via their return-correlation, per
Harvey-Liu 2015's effective-test count) so DSR neither under-counts (C4) nor over-penalises
redundancy (C9).

---

## SECTION 4 — STEP-BY-STEP EXECUTION ROADMAP

Phased to move the score from **4 → 8** without modifying behaviour at retail scale (every change is
gated by the existing `per_pos/med_adv > 0.005` auto-trigger or is opt-in→default). `MODE=PAPER`
preserved throughout; no live order path touched.

### Phase 0 — Stop the bleeding (the four 🔴; ~1 day, pure backend, no schema/UI)
1. **C1+C3 — complete the auto-scale safeguard.** In `analytics.py:779-787`, when the scale trigger
   fires, set **all three**: `ctx.auto_impact` (temp), `ctx.auto_amihud` (permanent, from the
   per-name `amihud_illiq` already in the frame), **and** `ctx.auto_participation = 10.0`. Pass
   `amihud_coef` and `max_participation_pct` through `_simulate_window` (`:858-861`) from these.
   *Effect: a ₹100Cr run can no longer fill 108% of ADV nor omit permanent impact.*
2. **C2 — per-name coefficient.** Replace the scalar `auto_impact=1.0` with a per-candidate
   `Y_i = g(amihud_illiq_i)` mapped at `_compute_advanced_factors` time; pass per-candidate into
   `simulate_portfolio` (the `cand["amihud"]` hook already exists, `backtest_engine.py:690`).
3. **D1 — quantify the survivorship premium once.** Even before backfilling membership, run the
   headline combo on the current survivors and emit a *bounded* warning banner with the
   Brown-Goetzmann-Ibbotson-Ross +1–4%/yr range as an explicit CAGR haircut in
   `combinatorial_backtest_results.md`, so no number is consumed without the caveat attached.

### Phase 1 — Honest tail risk (the 🟠 stops/VaR; ~1 day, backend + 2 config flags)
4. **C7 — flip defaults.** Make `atr_stop_mult` (k=2.0) the default stop and `vol_target_pct` the
   default sizing in `BacktestRequest` (`analytics.py:278-288`); keep fixed-% as an explicit opt-out.
5. **Daily-VaR governor.** Add a per-bar realised-daily-loss halt to `simulate_portfolio`
   (`backtest_engine.py:624-627`) mirroring the live 2% kill-switch, so sim/live tail limits match.
6. **C8 — telemetry fix.** In `_update_daily_pnl` (`live_execution.py:313-318`) persist
   `unrealized - tx_costs_today` (the figure the *active* guard already uses), so the dashboard
   stops under-reporting intraday loss. (Observability only — control path unchanged.)

### Phase 2 — Backtest↔live parity at scale (C6; ~2–3 days, backend)
7. **Call the scheduler from the backtest.** Route the at-scale entry through
   `execution_scheduler.schedule_children` (TWAP/VWAP/POV, partial fills, `_U_SHAPE` liquidity) so a
   ₹20Cr block is *worked over multiple sessions* in the sim exactly as live would, charging the
   per-slice √-law against thinning intraday liquidity. This unifies the two impact models and gives
   true parity — the simulator stops over-stating capacity for blocks.
8. **Slippage reconciliation loop.** Persist realised IS (`execution_scheduler` already computes
   `implementation_shortfall_bps`) to a `slippage` table; nightly regress realised slip on
   $\sigma\sqrt{Q/\text{ADV}}$ to **recalibrate** the backtest's per-name $Y_i$ — closing the loop so
   the simulator self-corrects toward live reality.

### Phase 3 — Statistical honesty across the campaign (C4, C9; ~2 days, backend + 1 table)
9. **`research_trials` ledger.** New DuckDB table `research_trials(run_id, config_hash, sharpe, daily_returns_ref, ts)`;
   every grid-search combo, parameter sweep, and WFO per-window selection writes a row. DSR
   (`backtest_engine.py:1007`) reads $N$ from this ledger, cluster-adjusted via return-correlation
   (effective-test count), not from one run's surviving count.
10. **Surface it.** WFO/grid output reports both nominal and effective trial count and the
    cross-campaign DSR, so the operator sees how much of the certified edge is search luck.

### Phase 4 — Capital allocation + regime-adaptive filters (3.3, 3.5; ~3–4 days)
11. **Risk-parity default + liquidity-capped weights** (`simulate_portfolio` sizing block,
    `backtest_engine.py:659-674`); fractional-Kelly sizes the *book* gross, not just a per-bet cap.
12. **Regime → filter-set switch.** Extend the HMM/GMM posterior to select the *active filter set*
    (3.5), disabling mean-reversion filters in expansionary/crash regimes — wired through the
    `regime_scale_by_date` plumbing that already exists (`backtest_engine.py:632-633`).

### Phase 5 — Data backfill to unlock G1/G2/G7 fully (D1; ongoing, data-eng)
13. Backfill `index_membership` + `delistings` (NSE reconstitution circulars) and PIT `stock_metrics`
    (announcement-date-stamped quarterly snapshots, report-lag ≥ 45 trading days) and the intraday
    triple-barrier `label_barrier`. Until done, the engine *correctly* runs on survivors and flags
    it — but the survivorship premium remains a live, unquantified bias on every AUM band.

### UI re-wiring (cross-cutting, after Phase 0–1)
- **Capacity panel** in `BacktestPanel.tsx`: render the §3.1 capacity-decay curve for the *current*
  config (participation %, impact %, net edge vs AUM) with a red zone where participation > 10% ADV —
  so the desk *sees* the AUM at which the edge dies before deploying.
- **Scale-fiction banner** whenever `impact_auto_enabled` is true but `amihud_coef`/`max_participation_pct`
  are still off (until Phase 0 lands), and a persistent **point-in-time / survivorship banner** while
  `membership_pit=False` or `fundamentals_pit=False` (Directive #1 / Guardrail #3 compliance).

---

## Verification ledger (every claim checked against source, this audit)
- `MODE=PAPER` intact: `live_execution.py:107`, backtest engine docstring `:16`. ✔ Not modified.
- No secrets hardcoded; ICICI creds from env: `live_execution.py:333-334`. ✔
- Auto-impact sets only `auto_impact=1.0`, never `amihud_coef`/`max_participation_pct`:
  `analytics.py:779-787` + grep (auto-enable of those two returns ∅ outside tests). ✔ (C1, C2, C3)
- Participation cap skipped when `None`: `backtest_engine.py:673-674`. ✔ (C3)
- DSR `n_trials` = single-run surviving combos; no persistent counter: `combinatorial_grid_search.py:390-393`,
  grep for `trial_count|trials.json|cumulative` ∅. ✔ (C4)
- DSR independence assumption + acknowledged-but-uncorrected overlap: `backtest_engine.py:994-1005`,
  docstring `combinatorial_grid_search.py:280`. ✔ (C9)
- Fixed-% default stop, ATR stop opt-in, no daily-VaR halt in sim: `backtest_engine.py:428, 624-627`;
  `analytics.py:288, 600-603`. ✔ (C7)
- Persisted daily-PnL excludes unrealized; active kill-switch includes it: `live_execution.py:316-317`
  vs `:753-755`. ✔ (C8)
- ADV distribution + capacity curve computed live from `data/market.duckdb` (1,496 names): median
  ₹18.37Cr, p25 ₹5.78Cr, 18% of names >₹100Cr ADV, median ATR 3.24%. ✔ (§1, §3.1)
- Empirical OOS collapse corroborated: `combinatorial_backtest_results.md` top combos all DSR≈0.00,
  PBO=0.15, −36% to −60% MaxDD. ✔
- Look-ahead controls verified sound (gap-aware, prior-peak trailing): `backtest_engine.py:391-450`. ✔
- **No system code modified; nothing committed; only this report written.** ✔
```

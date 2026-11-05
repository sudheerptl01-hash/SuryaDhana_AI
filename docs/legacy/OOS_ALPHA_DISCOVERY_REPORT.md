# SuryaDhana — Out-of-Sample Alpha Discovery Report

> **Verdict up front (statistical honesty outranks a positive number):**
> **NO configuration produced a positive out-of-sample return with DSR > 0.95.**
> Every Decile-10 config is **negative OOS even *gross* (equal-weight, zero impact)** — this
> is a signal that does not survive walk-forward, *not* a real edge consumed by costs.
> Market impact (Pillar B) then finishes the thin 2-way intersection. **No capital should be
> deployed on these signals.** The least-bad config is documented; it is still a loser.

- **Generated:** institutional research run · **MODE:** PAPER · DB strictly read-only
- **Capital base:** ₹1,00,00,000 (₹1 Crore) · **Max positions:** 5 · **Horizon:** 5 trading days
- **Universe:** 1,496 NSE tickers (full traded universe, PIT-active per day) · **Span:** 2021-05-17 → 2026-06-11 (~5y)
- **WFO:** rolling IS = 365d / OOS = 90d / embargo ≥ horizon · **17 stitched OOS windows**
- **Constraints ACTIVE (verified in code, not assumed):** Pillar B = Amihud/√-law market impact (per-name endogenous Y_i + permanent Kyle-λ + 10% ADV participation cap); Pillar C = inverse-vol position sizing (wᵢ∝1/σᵢ via ATR); friction floor 0.15% round-trip (additive, never bypassed).

---

## Phase 0 — Data Availability Verdict

| Required input | Status | Evidence |
|---|---|---|
| **Daily delivery quantity / delivery %** (for IDS) | **ABSENT** | Exhaustive `information_schema.columns` scan for `deliv`/`qty`/`turnover`/`traded` across all 17 tables → **zero matches**. `ohlcv` carries only `open, high, low, close, volume, adjusted_close`. `volume` is total traded quantity; there is no delivery breakdown. |
| **Nifty-50 index series** (for Beta-Residual) | **PRESENT (proxy)** | Ticker `NIFTY1` in `ohlcv`: 1,256 rows, full 2021-05→2026-06 range, 0 nulls. ETF-priced (~155→289), so its *returns* track Nifty-50 1:1 — valid for beta/correlation. |
| **Sector grouping** (for Sector Alpha) | **PRESENT** | `data/NSE_1500.csv` (`ticker, sector`), the production `_sector_map()` source. |

**Consequence for Feature 1 (Institutional Delivery Shock, IDS):** it is **NOT buildable** from
existing data and was **dropped, not proxied.** Substituting `volume` for delivery quantity
would be fabricating the signal — the whole point of IDS is that *delivery* (shares actually
taken to settlement) diverges from *traded volume*. Building it would have been dishonest. The
study proceeded with the two features that *can* be built point-in-time. **To unlock IDS, the
NSE Bhavcopy `DELIV_QTY`/`DELIV_PER` columns must be ingested into `ohlcv` (a separate,
idempotent ingestion job) before this feature can be evaluated.**

---

## Phase 1 — Features Built (point-in-time, zero look-ahead)

Both live in the sealed production factor pipeline `backtest_engine.compute_market_relative`
(cross-sectional pass), registered in `FIELD_MAP` / `FILTER_CATALOG` / `MARKET_RELATIVE_FIELDS`,
and flow natively through the `mode='decile'` engine.

| # | Feature | Column | Formula (all windows strictly trailing) |
|---|---|---|---|
| 1 | Institutional Delivery Shock | — | **DROPPED** — no delivery data (Phase 0) |
| 2 | Idiosyncratic Momentum (Beta-Residual) | `beta_resid_5d` | rolling 30d OLS β of stock daily ret vs **real Nifty (NIFTY1)**; residual = `ret5_stock − β·ret5_market`, ×100 |
| 3 | Volatility-Adjusted Sector Alpha | `vol_adj_sector_alpha_14` | `(stock 14d ret − sector 14d ret) / stock 14d ATR%` (equal-weight sector composite, contemporaneous cross-section) |

**Look-ahead self-audit — PASS (exact).** Recomputing each feature on a cutoff date using only
data ≤ cutoff yields **byte-identical** values to the full-frame computation
(`max|full − truncated| = 0.000e+00` for both). A future leak would change them; it does not.
Unit tests added in `services/ui-api/tests/test_suryadhana_structural_features.py` (7 tests,
including the PIT property, NaN/zero-volume safety, and decile-rankability).

**Distribution sanity (full universe):** `beta_resid_5d` 87.8% non-null (12.2% NaN = 30-day beta
warm-up), no infs, ~symmetric around 0. `vol_adj_sector_alpha_14` 97.9% non-null, no infs
(the `atr_pct > 0` guard holds); heavy upper tail from near-zero-ATR names, but the decile rank
is order-based so magnitude outliers do not distort selection.

---

## Phase 2 — Decile-10 Combinatorial Screen (UNCONSTRAINED signal proxy)

Daily cross-sectional Decile-10 (top tenth) per feature; the 3-way collapses to the 2-way since
only two features survived Phase 0. Overlap-corrected (÷HORIZON) daily-basket proxy, ≥120-trade floor.

| Config | Avg names/day | Trades | Win% | PF | Avg net 5d | CAGR | MaxDD | Calmar |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| IdioMom (β-resid) · D10 | 79.9 | 92,970 | 47.1 | 1.19 | +0.518% | +32.1% | -30.7% | 1.04 |
| VolAdjSectAlpha · D10 | 83.6 | 103,535 | 46.8 | 1.21 | +0.492% | +35.4% | -19.8% | 1.79 |
| **2-way ∩ · D10∩D10** | **37.1** | 43,092 | 49.2 | 1.33 | **+0.918%** | +54.6% | -29.0% | 1.88 |

The intersection nearly doubles per-trade edge and lifts win rate — the features look complementary.
**This is the idealized wide-basket proxy and is the trap.** It equal-weights ALL ~37–84 top-decile
names every day and de-overlaps the 5-day horizon. It is hypothesis generation, **not** a capital
certification. All three advanced to the gauntlet.

---

## Phase 3 — Production WFO Gauntlet (the real verdict, ₹1 Cr, B + C active)

**Pillar B activation proof** (read from the live sim context, not assumed):
`{impact_temp_leg_on: true, impact_permanent_leg_on: true, impact_adv_cap_on: true,
impact_full_stack_auto: true, impact_coef_per_name: true, auto_participation_pct: 10.0}`.
At ₹1 Cr / 5 = ₹20 lakh per position, the `per_position_notional / median_ADV > 0.005` trigger
fires on the NSE universe → all three impact legs auto-on. **Pillar C:** `sizing_mode='risk_parity'`.

### Headline — stitched OUT-OF-SAMPLE, NET of impact + inverse-vol sizing

| Config | OOS CAGR | MaxDD | Win% | PF | Sharpe | **Study DSR** | Trades | OOS Alpha (ann.) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| IdioMom (β-resid) · D10 | **−5.57%** | −22.24% | 39.7 | 0.67 | −1.630 | **0.000** | 1,082 | −6.05% |
| VolAdjSectAlpha · D10 | **−4.80%** | −19.88% | 39.6 | 0.67 | −1.590 | **0.000** | 1,139 | −5.26% |
| 2-way ∩ · D10∩D10 | **−40.21%** | −89.39% | 39.8 | 0.64 | −1.900 | **0.000** | 1,061 | −50.35% |

Benchmark (Nifty proxy) over the same stitched OOS span: **+108% to +111%.** Every strategy lost
money in a market that more than doubled → **deeply negative alpha** across the board. DSR is 0.000
because the OOS Sharpe is negative — it cannot, even before multiple-testing deflation, approach 0.95.

---

## The Truth Check — where, exactly, the alpha leaks

The screen showed +32% to +55% CAGR; the WFO shows −4.8% to −40%. This is **not** "a real edge
eaten by market impact." The gross-vs-net decomposition (same Decile-10 selection through the WFO
engine, toggling each pillar) proves the signal is already dead before any cost:

| Config | A) equal-wt, **NO impact** (≈gross) | B) +Pillar B (impact) | C) +Pillar C (inv-vol) | D) **FULL (B+C)** |
|---|---:|---:|---:|---:|
| IdioMom · D10 — CAGR | **−25.12%** | −41.51% | −4.96% | −5.57% |
| IdioMom · D10 — MaxDD | −76.70% | −91.00% | −20.19% | −22.24% |
| VolAdjSect · D10 — CAGR | **−26.11%** | −40.79% | −4.34% | −4.80% |
| VolAdjSect · D10 — MaxDD | −76.61% | −90.92% | −18.22% | −19.88% |
| 2-way ∩ — CAGR | **−3.89%** (Sharpe +0.07) | −53.85% | −2.36% | −40.21% |
| 2-way ∩ — MaxDD | −57.80% | −97.20% | −41.36% | −89.39% |

**Leak point #1 — the signal does not survive concentration (the dominant failure).**
Even gross (column A), the solo features are **−25%/−26% CAGR** OOS. The +32–35% screen number is a
~80-names/day, /HORIZON-de-overlapped *basket*; the WFO holds **5 mktcap-sorted positions** with real
next-open entry and ATR stops. The Decile-10 edge is *diffuse* — it exists weakly across the top tenth
but evaporates once you concentrate to 5 names. The screen and the deployable portfolio are different
animals, and the gap between them is the whole story.

**Leak point #2 — Amihud impact annihilates the thin 2-way (₹1 Cr).**
The 2-way looks least-bad gross (−3.9%, ~flat) but column B shows impact alone drives it to
**−53.9% CAGR, −97% MaxDD.** The intersection thins the daily universe to ~37 names → the 5 picks are
disproportionately *illiquid* (high Amihud λ), so √-law + permanent impact at ₹20 lakh/position is
catastrophic. **The 2-way's apparent gross flatness is an illiquidity mirage.** This is the textbook
"edge exists on paper, entirely consumed at scale" case — but here even the paper edge is ~zero.

**Leak point #3 — inverse-vol sizing helps risk, can't fix expectancy.**
Pillar C is the one *good* news: it cuts solo MaxDD from −76% to ~−20% by down-weighting volatile
names (compare A→C). But you cannot size your way out of a negative-expectancy signal — C is still
≈−5% CAGR. Sizing controls *how much* you lose, not *whether*.

### Data-snooping / multiple-testing honesty

- **Trials evaluated this study:** Phase-2 screen = **3 Decile-10 configs** (2 solo + 1 intersection);
  Phase-3 WFO = the **same 3** configs pinned through `_core_wfo`. Study-level DSR deflates each
  config's OOS Sharpe against all 3 WFO trials. Because every OOS Sharpe is **negative**, DSR = 0.000
  regardless of trial count — the multiple-testing correction is not even the binding constraint here.
- **Survivorship bias (upward):** `index_membership` / `delistings` tables are empty → the backtest
  runs on *today's survivors only*. The engine's own `_survivorship_warning` flags a
  **+1.5–3%/yr CAGR upward bias** (Brown-Goetzmann-Ibbotson-Ross 1992). **True OOS is even worse than
  reported above.** This reinforces the FAIL verdict; it cannot rescue it.

---

## Final Verdict & Least-Bad

**No configuration clears positive OOS CAGR with DSR > 0.95. All three FAIL.** The two SuryaDhana
features are honest, point-in-time, and screen attractively as wide baskets, but the edge does not
survive walk-forward concentration to a deployable 5-position book — and market impact destroys the
thin intersection outright at ₹1 Cr.

**Least-bad (still a loser, do not deploy): `VolAdjSectAlpha · D10` solo** — OOS CAGR −4.80%,
MaxDD −19.88%, Sharpe −1.59, DSR 0.000. It is the least-bad only because inverse-vol sizing contains
its drawdown; its expectancy is still negative.

### Recommendations (honest next steps, not curve-fitting)

1. **Do not deploy.** None of these signals is a tradeable edge at ₹1 Cr (or any scale).
2. **The concentration gap is the research question.** A signal that works as an ~80-name basket but
   dies at 5 names may have value in a *higher-capacity, lower-concentration* construction (e.g. 20–30
   equal-risk names) — but that is a different, unproven hypothesis, and capacity at low concentration
   must be re-checked against impact.
3. **Ingest NSE delivery data** (`DELIV_QTY`/`DELIV_PER`) so IDS can finally be tested — it is the one
   genuinely *structural/institutional* signal of the three and was the most differentiated hypothesis;
   it remains unevaluated only because the data is missing.
4. **Backfill `index_membership` + `delistings`** to remove the survivorship premium before any future
   CAGR is read at face value.

---

### Reproducibility

| Artifact | Path |
|---|---|
| Feature implementation (PIT) | `services/ui-api/backtest_engine.py::compute_market_relative` |
| Field registration | `backtest_engine.py::FIELD_MAP`, `routers/analytics.py::FILTER_CATALOG` / `MARKET_RELATIVE_FIELDS` |
| Real-Nifty injection | `routers/analytics.py::_nifty_returns` → `_load_prepared` |
| Feature unit tests (7) | `services/ui-api/tests/test_suryadhana_structural_features.py` |
| Phase-2 decile screen | `scripts/suryadhana_decile_screen.py` |
| Phase-3 WFO gauntlet | `scripts/suryadhana_wfo_gauntlet.py` → `suryadhana_wfo_results.json` |

Backend test suite after changes: **238 passed** (231 pre-existing + 7 new), zero regressions.
Physics core (`analytics.py` engine, decile/impact/sizing pillars) was **not modified** — features
were added around it and routed through the existing decile + WFO machinery.

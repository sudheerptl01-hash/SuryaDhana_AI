# SOTA Verdict — Time-Series Regime-Timing Overlay on a Broad Book

**Status:** COMPLETE · **Verdict:** CLEAN NEGATIVE (no surviving edge) · **Date:** 2026-06-18
**Mode:** PAPER · **DB:** read-only `data/market.duckdb` · **Capital:** Rs1,00,00,000 (Rs1 Cr) · **Seed:** 42
**OOS span:** 2021-05-17 -> 2026-06-17 · **WFO:** rolling IS=365d -> embargoed OOS=90d · **17 OOS windows / cell**
**Friction:** 15.0 bps floor + **additive** Amihud impact (forced-explicit at every N: impact_coef=1.0 + amihud_coef=1.0 + 10% ADV cap) · **Sizing:** inverse-vol (`risk_parity`)
**Certifier:** production `routers.analytics._core_wfo` (no re-implementation) · **Script:** `sota_regime_timing_search.py`

---

## (a) The NEW hypothesis and why it is orthogonal to the falsified library

**Hypothesis.** The falsified decile/intersection program asked *which names* (cross-sectional
rank on the 27-factor library). Its post-mortem is decisive: over the OOS span the equal-weight
benchmark returned **+122%** while every cross-sectional cohort underperformed deeply, gross of
impact — the **selection axis carries no positive OOS information**. The new bet changes the axis
entirely: **WHEN to hold market exposure**, a time-series bet on the *benchmark's own regime
state*, applied to a **broad book** (N in {30,50,100}) so the timing signal expresses on a
diversified substrate instead of 5 idiosyncratic names.

**Why it is mechanically orthogonal — not cosmetically.** The regime signal is computed from the
**benchmark index return series**, never from any per-name cross-sectional rank. It is uncorrelated
by construction with the decile library: it does not touch *which* names are held; it scales/halts
the *time* the book is allowed to be long. Three production overlays were certified:
- **SMA-GATE** — block new entries when the benchmark sits below its own trailing SMA(200).
- **HMM-GATE** — causal 2-state Gaussian-HMM; block entries when P(bull|data<=t) < 0.5.
- **HMM-SOFT** — scale every allocation by the continuous P(bull) in [0,1] (smooth gross throttle).
All three are strictly trailing/causal (no look-ahead): the SMA and HMM at bar T use only benchmark
returns <= T. The fitted HMM separates states by **volatility** (sigma 1.67% vs 0.90%), i.e. it is a
vol-regime classifier. Substrate primary = a light long-only participation gate (`price_gt_ma200`),
identical across every cell incl. controls, so any delta is attributable solely to the overlay.

## (b) Experiment design

| Item | Value |
|---|---|
| Overlay variants | OFF (control), SMA-GATE, HMM-GATE, HMM-SOFT |
| Breadth N | 30, 50, 100 (genuinely broad; prior study saturated by N~20) |
| Cells | 4 x 3 = **12** WFO runs |
| Certifier | `_core_wfo` — rolling IS=365d -> embargoed OOS=90d; empty candidate pool => pure OOS stitch, no per-window re-selection, no OOS peeking |
| Cost realism | 15 bps floor + explicit Amihud stack forced at every N (auto-Amihud below scale trigger at Rs1Cr/N, so explicit legs forced; `impact_active=True` 12/12) |
| Sizing | inverse-vol (`risk_parity`) every cell |
| DSR trial count | n_eff = **12** (every cell searched, not just survivors) — Bailey/Lopez de Prado deflation |
| Control logic | each overlay cell judged vs its **N-matched OFF** control (identical cost stack) |

## (c) Measured results — full 12-cell OOS matrix (NET of Amihud + inverse-vol)

Benchmark OOS total return over the same stitched span: **+122.0%** in every cell.

| Regime | N | OOS CAGR% | MaxDD% | Calmar | Sharpe | study-DSR | dCalmar vs OFF | dMaxDD vs OFF | impact |
|---|---:|---:|---:|---:|---:|---:|---:|---:|:--:|
| OFF (control) | 30 | -17.19 | -58.46 | 0.290 | -1.560 | 0.000 | — | — | ON |
| OFF (control) | 50 | -19.11 | -63.89 | 0.300 | -1.120 | 0.000 | — | — | ON |
| OFF (control) | 100 | -18.29 | -62.24 | 0.290 | -1.060 | 0.000 | — | — | ON |
| SMA-GATE | 30 | -15.34 | -52.37 | 0.290 | -1.690 | 0.000 | +0.000 | +6.09 | ON |
| SMA-GATE | 50 | -17.81 | -59.08 | 0.300 | -1.260 | 0.000 | +0.000 | +4.81 | ON |
| SMA-GATE | 100 | -17.33 | -57.88 | 0.300 | -1.220 | 0.000 | +0.010 | +4.36 | ON |
| **HMM-GATE** | **30** | **-6.18** | **-33.02** | 0.190 | **-0.730** | 0.002 | -0.100 | **+25.44** | ON |
| HMM-GATE | 50 | -7.21 | -42.88 | 0.170 | -0.540 | 0.007 | -0.130 | +21.01 | ON |
| HMM-GATE | 100 | -7.32 | -42.95 | 0.170 | -0.540 | 0.007 | -0.120 | +19.29 | ON |
| HMM-SOFT | 30 | -8.78 | -37.56 | 0.230 | -1.380 | 0.000 | -0.060 | +20.90 | ON |
| HMM-SOFT | 50 | -12.57 | -48.75 | 0.260 | -1.300 | 0.000 | -0.040 | +15.14 | ON |
| HMM-SOFT | 100 | -12.98 | -50.97 | 0.250 | -1.230 | 0.000 | -0.040 | +11.27 | ON |

**Cells with OOS CAGR > 0: 0/12. Cells clearing study-DSR > 0.95: 0/12. Max study-DSR = 0.0071.**

## (d) Verdict

**Does the regime-timing lever clear DSR > 0.95 with positive OOS alpha? NO.** Zero of 12 cells
produce positive OOS CAGR; every cell has a negative OOS Sharpe; the best study-DSR is **0.0071**,
nowhere near the 0.95 gate. No cell that beats its OFF control on drawdown also beats it on Calmar
while turning the sign positive.

**The precise reason it failed (and it is informative, not just a null):**
1. **The overlay works mechanically as a risk reducer — it just can't manufacture alpha.** The
   HMM vol-gate is a genuinely effective *defense*: at N=30 it **halved the drawdown** (-58.46% ->
   -33.02%, dMaxDD **+25.4 pts**), cut the CAGR loss by ~64% (-17.2% -> -6.2%), and nearly halved
   the Sharpe penalty (-1.56 -> -0.73). But it only ever **scales a structurally-losing book toward
   zero** — it never crosses into positive territory, because there is no positive return for the
   timing to *protect*. You cannot time your way into alpha that the underlying book does not have.
2. **Calmar does not improve, by construction.** A gate that removes exposure shrinks the numerator
   (return) and the denominator (drawdown) together. SMA-GATE trims both proportionally => Calmar is
   pinned at the control's ~0.29-0.30 (dCalmar ~ 0.000). HMM-GATE cuts drawdown harder but cuts
   return even harder => Calmar *falls* to 0.17-0.19. No timing variant raises the risk-adjusted
   ratio above the do-nothing control.
3. **The opportunity cost is the killer.** The benchmark rose **+122%** over the span. Sitting in
   cash during high-vol regimes forgoes that broad-market upside; the book is long a losing
   cross-section when on, and flat when off — so the best achievable outcome is "lose less," not
   "make money." This is the same binding constraint the decile study hit: **the names themselves
   underperform a rising market; no exposure-timing wrapper changes that.**
4. **Breadth is again not the lever.** Widening 30 -> 50 -> 100 does not flip the sign in any
   variant; HMM-GATE saturates (N=50 ~ N=100), and on the OFF/SMA arms more breadth means more
   turnover and *deeper* drawdown net of impact.

**Is it worth a follow-up?** Only with a different *primary*. The HMM vol-gate is a validated,
production-ready **drawdown-control wrapper** (+25 pts of MaxDD at N=30) — but it is worthless until
it has a primary book with positive gross-of-timing OOS return to protect. The corollary, now
triple-confirmed (single-factor, orthogonal multi-factor, and timing overlays), is that **the entire
long-only signal stack derived from this 100-NSE / 27-factor library underperforms its own
equal-weight benchmark OOS net of realistic costs.** The credible next bet is *not* another wrapper
on this stack — it is either (i) a short/market-neutral construction so the book is not structurally
long a losing cross-section, or (ii) a different return engine (e.g. the ML `prob_up` meta-label as
a *primary*, not a screen) that produces positive gross return for the HMM gate to then de-risk.

## (e) Artifacts (all at repo root, UNSTAGED — nothing committed or pushed)

| File | Contents |
|---|---|
| `sota_regime_timing_search.py` | typed, config-driven, seeded (42) experiment driver; routes 12 cells through production `_core_wfo` |
| `sota_regime_timing_results.csv` | full 12-cell matrix, all metrics + per-cell impact/regime proof |
| `sota_regime_timing_results.json` | machine-readable matrix (this report's source numbers) |
| `sota_regime_timing_run.log` | full stdout incl. per-cell Pillar-B + regime-map activation proof |
| `SOTA_REGIME_TIMING_VERDICT.md` | this verdict |

**Integrity attestation:** impact_active=True in 12/12 cells; all 9 overlay cells carry populated
regime maps (1080 dates); all cells 17 OOS windows; DSR deflated against honest n_eff=12; selection
is in-sample inside `_core_wfo` (empty OOS candidate pool); no look-ahead, no time-series shuffle,
read-only DuckDB, no secrets. Verdict reproduces to the basis point at seed=42.

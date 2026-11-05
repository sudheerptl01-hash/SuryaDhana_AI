# SOTA INVERSION VERDICT — Dollar/Beta-Neutral Long-Short Spread

**Date:** 2026-06-18 · **Mode:** PAPER · **Capital:** ₹1,00,00,000 · **Seed:** 42 (deterministic)
**Span:** 2021-05-17 → 2026-06-17 · **WFO:** IS=365d / OOS=90d / embargo=7d · 17 windows
**Read-only DuckDB · nothing staged / committed / pushed**

---

## The question

Three independent programs (single-factor, PCA-orthogonal multi-factor under breadth,
regime-timing overlay) triple-confirmed that the **long-only** 27-factor decile stack
underperforms its own +122% equal-weight benchmark OOS, net of cost. **Is that
underperformance mis-signed *information* (tradeable by inverting the construction), or
merely concentration / vol-drag with NO directional edge?**

The test: a **dollar-neutral (and dollar+beta-neutral) long-short spread** that SHORTS the
screened cohort the long-only book bought, and goes LONG the equal-weight benchmark. If the
selection axis carries real mis-signed info, the spread isolates it, nets out market beta,
and yields positive OOS alpha clearing **DSR > 0.95**.

---

## (a) Execution path used — and why

**Path: spread-on-WFO-windows (NOT native short).**

The production engine is **strictly long-only**. Verified by grep over both
`services/ui-api/routers/analytics.py` and `services/ui-api/backtest_engine.py`: there is
**no** short / borrow / negative-weight / leverage / market-neutral code path. The DuckDB
also has **no** shortable / F&O / SLB flag (checked every table). Faking a short through the
long-only `simulate_portfolio` would be dishonest, so I did not.

Instead the spread is built **honestly on top of the same machinery**:

- Same DB read + same prepared panel via `analytics._load_context` → `_load_prepared`
  (`be.compute_indicators` + `be.compute_market_relative`). **No indicator reimplementation,
  no look-ahead.**
- Same WFO windows via `analytics._wfo_windows` (rolling IS→embargoed OOS, contiguous OOS
  tiling) — the **identical** windows the falsified studies used.
- Same per-name forward economics via `ctx.resolve(sig, ticker)` — the engine's own
  look-ahead-free, friction-baked, stop/time-exit-resolved entry dict (`net_return_pct`,
  `gross_return_pct`, `atr_pct`, `adv`=ADV20, `amihud`=ILLIQ, `sector`).
- Same cross-sectional decile recipe via `be.assign_decile` (bit-for-bit the production
  screen) to define the short cohort each bar.
- Same impact arithmetic copied byte-faithfully from `simulate_portfolio`
  (`backtest_engine.py` L1085 / L1126): temporary √-law round-trip `2·Y·ATR%·√(alloc/ADV)`
  and permanent Amihud round-trip `amihud_coef·ILLIQ·alloc·100`, **debited symmetrically on
  BOTH legs.**

Script: `sota_inversion_spread_search.py` (typed, config-driven, seeded, logged).

---

## (b) Exact long-short construction

| Component | Definition |
|---|---|
| **Investable universe** | Per bar, the **top-100 most-liquid names by signal-day ADV20** — the production benchmark constituency (`_build_benchmark`, `BENCHMARK_LABEL = "Nifty-50 proxy (top-100 mkt-cap, equal-weight)"`). NaN-ADV microcaps dropped from BOTH legs. |
| **LONG leg** | Equal-weight, that 100-name benchmark cross-section (the rising tape). Gross notional = ₹1Cr. |
| **SHORT leg** | The decile-screened cohort the long-only book *bought* (e.g. `vol_adj_sector_alpha↑D10`, `atr_pct↓D1`), restricted to the **shortable universe** = top-half by ADV (decile ≥ 6), top-N by liquidity. Gross notional = ₹1Cr. |
| **Dollar-neutral** | Long ₹1Cr − Short ₹1Cr (equal gross per leg). |
| **Beta-neutral** | Long leg scaled by the **IS-estimated** short-cohort beta (β̂≈0.35), applied OOS only (no OOS fit). Realized OOS spread β falls to **≈0.05** — confirmed neutral. |
| **Shortable-universe assumption** | No SLB/F&O flag exists → short leg restricted to the top-half-by-ADV of the already-top-100-liquid universe (≈ NSE F&O/SLB-eligible large caps). **Documented assumption.** A stricter top-decile gate leaves ~1-2 names (an idiosyncratic coin-flip, not a cohort). |
| **Borrow / financing** | Indian SLB lending fee = **150 bps/yr** (mid of the 50–200 bps/yr band), pro-rated over the ~5-day hold. **Stated assumption.** |
| **Friction floor** | 15.0 bps/leg (baked into `net_return_pct` by the engine resolver) → long-short round-trip pays ~2×. |
| **Amihud impact** | Symmetric — same √-law + permanent ILLIQ formula on BOTH legs at each leg's per-slot notional. |
| **Overlap correction** | Signals fire daily but trades hold 5 days → returns overlap. Sampled **non-overlapping** (every 5th signal date) so each 5-day move is counted once. **(Without this, naive overlapping compounding inflated gross CAGR to a fantasy ~1000%/yr — a pure annualization artifact, now removed.)** |
| **Breadth floor** | Minimum 5 shortable names/bar; thinner bars carry no short. |

Trial grid: **4 cohorts × 2 neutralizations × 4 breadths N∈{5,10,20,30} = 32 cells.**

---

## (c) MEASURED results (net of 15bps×2 + symmetric Amihud + 150bps/yr borrow)

Non-overlapping OOS cadence ≈ **51.2 bars/yr**. DSR deflated against **n_eff = 32** (every
cell searched). Representative cells (full 32 in `sota_inversion_spread_results.csv`):

| Cell (short cohort \| neutral \| N) | GROSS CAGR | **NET CAGR** | Sharpe | Calmar | MaxDD | spread β | **DSR** |
|---|---:|---:|---:|---:|---:|---:|---:|
| low-ATR↓D1 \| beta \| N=5 | +21.3% | **+11.4%** | 0.77 | 0.61 | −18.6% | 0.05 | **0.0186** |
| low-ATR↓D1 \| beta \| N=10 | +20.6% | **+10.7%** | 0.79 | 0.68 | −15.6% | 0.05 | **0.0186** |
| vol_adj_sector_alpha↑D10 \| beta \| N=5 | +28.6% | **−4.3%** | −0.04 | −0.14 | −29.8% | 0.04 | 0.0006 |
| sector_rel_mom↑D10 \| dollar \| N=10 | +12.1% | **−27.7%** | −1.21 | −0.43 | −63.8% | −0.17 | 0.0000 |
| squeeze↑D10 \| dollar \| N=5 | −1.6% | **−28.6%** | −1.43 | −0.42 | −67.4% | 0.06 | 0.0000 |

**Campaign summary:** net CAGR range −33.7% … +11.4%. **DSR range 0.0000 … 0.0186.**
**0 / 32 cells clear DSR > 0.95.** Max DSR in the entire campaign = **0.0186** (53× below gate).

**Long-only control (alongside, from the prior triple-confirmed verdicts):** long-only
orthogonal decile intersections = **0/12 positive OOS**, every Sharpe negative, study-DSR =
0.0000; the screened cohort underperforms its own +122% benchmark. The inversion does **flip
the sign to positive NET CAGR on 8/32 cells** (all the `low-ATR↓D1` cohort) — a genuine
change from the long-only all-negative result — **but none survives the statistical gate.**

### Friction decomposition (the economic crux)

Per non-overlapping bar, the short-leg cost is **Amihud+√-law impact ≈ 0.102%** vs **borrow
≈ 0.027%** — i.e. **market impact is ~3-4× the borrow cost.** Long-leg impact ≈ 0.120%/bar.
Total ≈ 0.25%/bar × 51 bars/yr ≈ **~13%/yr of friction drag**, which exactly accounts for the
gross→net collapse (e.g. vol_adj_sector_alpha: +28.6% gross → −4.3% net, a 33pt gap).
**The killer is symmetric market impact on a thin, volatile short cohort — NOT the borrow.**
Even a 0-bps borrow assumption would not rescue these cells.

---

## (d) VERDICT

**Does the inversion flip the sign to positive OOS alpha clearing DSR > 0.95? — NO.**

The diagnostic is **mixed by cohort**, and the script measured all three regimes:

1. **"Real info, wrong sign — but killed by short frictions"** (16/32 cells:
   `vol_adj_sector_alpha↑D10`, `sector_rel_mom↑D10`). These have **positive GROSS spread**
   (+12% … +29% CAGR) but go **negative NET** — the cross-section *does* carry weak
   mis-signed information, and the spread β≈0 confirms it is not just market beta. The edge
   is **economically destroyed by symmetric Amihud market impact** (32pt gap), and is
   **statistically a multiple-testing artifact** (DSR ≤ 0.001).

2. **"Marginally tradeable gross, but not statistically real"** (8/32 cells: `low-ATR↓D1`).
   The only cohort with **positive NET CAGR** (beta-neutral: +10.7–11.4%, Sharpe ~0.78,
   β≈0.05, MaxDD −16/−19%). This is the closest thing to an edge the entire SuryaDhana
   research program has produced on the short side. **But DSR = 0.0186 — 53× below the 0.95
   gate.** Across 32 honestly-counted trials this Sharpe is fully explained by selection
   luck; it is **not** a deflation-surviving edge. Reporting it as tradeable would violate
   the anti-curve-fit mandate.

3. **"No info, just concentration drag"** (8/32 cells: `squeeze↑D10`). **GROSS is already
   ≤ 0** — the long-only loss on this cohort was idiosyncratic concentration, not
   tradeable mis-signed information. Inversion cannot help where there is no signal to flip.

**Minimum tradeable breadth N:** Not applicable — no cell is tradeable. Moreover the short
cohort is **mechanically capped**: the factor-decile ∩ shortable-universe intersection inside
a 100-name book yields a handful of names, so **N=20 and N=30 are numerically identical to
N≈10** in every cohort (same breadth-saturation seen in the long-only study). Breadth is not
the lever on the short side either.

**Why (the math).** The spread isolates a genuinely β-neutral (β≈0.05) cross-sectional
component. For two cohorts that component is weakly **positive gross** — so the selection
axis is not *pure* noise; it carries faint mis-signed directional info. But the magnitude
(gross Sharpe ~1, pre-cost) is (i) **below the symmetric market-impact cost** of trading a
thin, high-ATR short cohort, and (ii) **below the Deflated-Sharpe haircut** for 32 trials.
The long-only diagnostic was therefore a blend: *real-but-tiny mis-signed info on the
vol/alpha cohorts* + *pure concentration drag on the squeeze cohort* — and in **neither case
is the information large enough to monetize after honest impact and multiple-testing
correction.**

**Clean negative — and it is a valid, valuable result.** The inversion thesis is falsified:
inverting the construction does not manufacture a DSR-surviving edge. The long-short axis
joins single-factor, orthogonal multi-factor, and regime-timing as **exhausted** for this
100-NSE / 27-factor library.

---

## (e) Artifacts on disk (unstaged — nothing committed / pushed)

- `sota_inversion_spread_search.py` — the search script (typed, config-driven, seeded)
- `sota_inversion_spread_results.csv` — 32-cell matrix (all metrics + DSR)
- `sota_inversion_spread_results.json` — full payload + survivors + best-gross/least-bad
- `sota_inversion_spread_run.log` — run log
- `SOTA_INVERSION_VERDICT.md` — this verdict

**Method certifications:** selection (β̂) IS-only, applied OOS (no leakage). Amihud impact
active (>0) on both legs in every cell. Overlap removed (non-overlapping 5-day bars). DSR
deflated against the full n_eff=32. No future data, no shuffle, no skipped walk-forward.

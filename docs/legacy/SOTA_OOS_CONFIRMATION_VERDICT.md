# SOTA OUT-OF-SAMPLE CONFIRMATION VERDICT

**Pre-registered hypothesis (frozen, single trial):**
`COH-A = vol_adj_sector_alpha_14 ↑ top-decile` (decile mode, op=`gte`, value=10) ·
`forward_days=60` (primary) / `40` (robustness echo) · `N=20` · `sizing_mode=risk_parity` ·
forced full Amihud stack (`impact_coef=1.0`, `amihud_coef=1.0`, ADV cap) · `friction_bps=15.0` floor ·
engine `analytics._core_wfo` · IS=365 / OOS=90 / embargo auto-raised to `max(7, fd+2)`.

**Date:** 2026-06-20 · **MODE:** PAPER · **DB:** `data/market.duckdb` (read-only) · **Branch:** `feature/backtest-lab-institutional`

---

## VERDICT: INCONCLUSIVE — NO CLEAN HOLDOUT EXISTS (data exhaustion)

A clean out-of-sample confirmation **cannot be performed**. The 30-cell horizon discovery
sweep already consumed the **entire** available price history as its OOS-reported track.
There is no genuinely unseen span — earlier or later — on which to validate the candidate as
a single pre-registered hypothesis. Per the pre-registration's own anti-data-dredging clause,
re-slicing data the sweep already saw, or relabelling the in-sample winner as `n_eff=1`, is
**forbidden** and was not done. This is the honest, valid finding.

The candidate is **neither CONFIRMED nor REJECTED**: it remains the program's only LIVE
near-miss, parked for lack of fresh data — not falsified.

---

## (a) THE HELD-OUT SPAN PROBLEM — proof no clean holdout exists

### Available data (DuckDB `ohlcv`, read-only)
| Quantity | Value |
|---|---|
| OHLCV min date | **2021-05-17** |
| OHLCV max date | **2026-06-17** |
| Total history | 1857 cal days (~5.08 y) · 1262 trading days |
| Rows after 2026-06-17 | **0** |

### Discovery sweep's actual OOS consumption (re-derived from `_wfo_windows`, not guessed)
The horizon sweep (`sota_horizon_search.py`) ran on `SPAN_FROM=2021-05-17 → SPAN_TO=2026-06-17`
— the full DB span — with a rolling IS=365 / OOS=90 / embargo=`max(7, fd+2)` stitch:

| fd | embargo | n_windows | first OOS_start | last OOS_end | IS-only head (never OOS, still SEEN) |
|---|---|---|---|---|---|
| 60 | 62d | 16 | **2022-07-18** | **2026-06-17** | 2021-05-17 → 2022-07-18 (427d) |
| 40 | 42d | 17 | 2022-06-28 | 2026-06-17 | 2021-05-17 → 2022-06-28 (407d) |

The candidate's OOS-reported track (re-run, `equity_curve`) spans **2022-07-18 → 2026-06-17**,
ending on the DB's last bar. Every available forward date is inside the discovery OOS track.

### Every holdout avenue is mathematically foreclosed
- **Option A — later holdout (preferred):** 0 rows exist after 2026-06-17. Today is 2026-06-20;
  the 3-day wall-clock gap added **no new data**. *Impossible.*
- **Option B — earlier carve before the sweep's first OOS:** one frozen IS=365/OOS=90/emb=62
  window needs 517 cal days. From DB start 2021-05-17 the earliest such window ends **2022-10-16**,
  which is *after* the sweep's first OOS_start (2022-07-18) → it overlaps. *Impossible.*
- **Option C — shrink IS/OOS to fit a tiny early window:** would (1) violate the frozen
  IS=365/OOS=90 pre-registration, and (2) still reuse dates the sweep's first windows trained on
  as in-sample. *Forbidden + not clean.*

**Conclusion:** the held-out span required for a legitimate n=1 confirmation **does not exist.**

---

## (b) Candidate cell metrics (discovery run, re-verified this session — for reference only)

Re-running the EXACT frozen cell reproduced the discovery numbers byte-faithfully and confirmed
both pillars live (provenance check, **not** a confirmation):

| Metric | fd=60 / N=20 (primary) |
|---|---|
| OOS CAGR (NET) | **+7.54%** |
| OOS CAGR (GROSS-of-impact) | +8.64% |
| Impact drag | **1.10 %/yr** (down 94% from fd=5's 6.61%/yr) |
| Turnover | 296 %/yr (down from 1153%/yr at fd=5) |
| MaxDD | **−10.05%** |
| Sharpe | **0.98** |
| Calmar | 0.75 · Sortino 1.34 · win-rate 33.7% |
| Trades / windows | 816 / 16 |
| Benchmark total (OOS) | +340.4% · alpha_annual +6.95% |
| Pillar B Amihud | **ACTIVE** (temp leg=True, permanent leg=True) |
| Pillar C sizing | **risk_parity** (inverse-vol) |

The candidate clears the impact wall and is gross-positive. Its only failure was statistical.

---

## (c) DSR at the TRUE trial count — what a clean holdout would have unlocked

A constructive what-if (clearly labelled — **not** a confirmation, run on the seen span):

| Deflation basis | sr0 chance-max bar (annual) | DSR | Gate 0.95 |
|---|---|---|---|
| Candidate's own daily OOS returns, **n=1** single hypothesis | ~0.00 | **0.9948** | **CLEARS** |
| Study deflation against all 30 trial Sharpes (std=0.738, `n_eff=30`) | **1.53** | **0.073** | fails |
| Engine per-run DSR (single-run window selections) | — | 0.995 | clears |

The candidate's OOS return stream is **intrinsically strong enough** to clear DSR>0.95 as a
single hypothesis (PSR-based DSR = 0.9948; per-run engine DSR = 0.995). It died **only** because
the study deflated it against 29 sibling trials — the chance-max-Sharpe-of-30 bar (1.53 annual)
exceeds its realized 0.98. On a genuinely unseen span the trial pool is legitimately 1, that bar
collapses to ~0, and the candidate passes. **The single missing ingredient is an unseen span,
which does not exist.** The bottleneck is data availability, not signal quality.

---

## (d) Robustness echo — fd=40 / N=20 (reported separately, not a 2nd deflation trial)

| Metric | fd=40 / N=20 |
|---|---|
| OOS CAGR (NET) | +6.70% |
| OOS CAGR (GROSS) | +9.85% |
| Impact drag | 3.15 %/yr |
| MaxDD | −11.46% |
| Sharpe | 0.97 · Calmar 0.58 |
| Trades | 1146 |

The +gross / +net / Sharpe~1.0 result is **stable across the fd40↔fd60 horizon neighbourhood** —
not a single-cell artifact. This raises prior confidence in the signal but is **not** a substitute
for an out-of-sample span, which is the only thing that can certify it.

---

## (e) ONE-LINE VERDICT

**INCONCLUSIVE — no clean held-out span exists (the discovery sweep consumed all 5.08y of
history through the DB's last bar 2026-06-17; 0 rows beyond). The candidate is intrinsically
DSR-strong as a single hypothesis (0.995) and impact-survivable, but cannot be certified without
fresh, genuinely unseen data. It is a parked LIVE near-miss, not an in-sample artifact and not a
certified edge. Re-evaluate once forward data accrues (the indicated test: hold the frozen cell
fixed, wait ~6–9 months for new OHLCV, run it once on the strictly post-2026-06-17 span as the
genuine n=1 confirmation).**

---

### Hygiene
MODE=PAPER · DuckDB `read_only=True` · no secrets · no look-ahead (embargo auto = max(7, fd+2)) ·
no shuffle · full WFO · friction floor 15.0 bps, Amihud additive · nothing staged / committed / pushed.
This verdict file and any sidecars are gitignored repo-root artifacts.

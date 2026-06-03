---
name: hypothesis-families
description: Phase-1 alpha hypothesis families in alpha_hypotheses.md + shared notation conventions for downstream agents
metadata:
  type: project
---

# Phase-1 hypothesis families (alpha_hypotheses.md at repo root)

**Why:** avoid duplication in future sprints; keep notation consistent for Agents 2/3/4. **How to apply:** new edges must add a distinct conditioning variable (see Distinctness Matrix, Appendix B of the deliverable).

11 hypotheses, 4 pillars:
- **Conditional reversal / overreaction:** H1 (vol-gated 1-day z-shock reversal), H11 (turnover-shock liquidity reversal, no price move).
- **Microstructure / underreaction:** H2 (volume-confirmed information drift / PEAD analogue), H3 (gap polarity: fade gap-down, ride gap-up), H7 (cross-sectional lead-lag laggard catch-up).
- **Volatility regime & range dynamics:** H5 (compression→directional breakout), H9 (low-vol band-fade carry, excludes breakouts), H4 (variance-ratio regime switch), H10 (Hurst persistence trend).
- **Behavioral / stat-arb:** H6 (52-week-high anchoring drift, strongest measured edge +0.96% fwd10), H8 (beta-residual mean-reversion, market-neutral).

## Notation conventions (reuse in future sprints)
- $A_t$=adjusted_close, $C/O/H/L/V$=raw OHLCV, $r_t=\ln(A_t/A_{t-1})$, $g_t=O_t/C_{t-1}-1$, $\rho_t=(H_t-L_t)/C_t$.
- Every hyper-param given as (notation, default, range) table — this is the UI-knob contract for Agent 4.
- Global liquidity gate §0.3: $\Lambda_{\min}$=5e7 turnover, $N_{\text{hist}}$=252, $P_{\min}$=20. ≈939 eligible tickers.
- Holding always in 2–15 band. Entry executes at next open or current close — never a future bar.

## Self-imposed design rules learned this sprint
- Contraction alone (NR7) is NOT an edge — needs directional breakout trigger (drove H5 vs H9 split).
- Volume gate FLIPS sign of post-move return (drove H1 vs H2 split) — this is the key discriminator in the dataset.
- No sector labels available → lead-lag/sector strategies must build data-driven correlation groups (H7).

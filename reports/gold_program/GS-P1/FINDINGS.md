# GS-P1 · GLD daily tonnes vs COMEX gold: findings (04 Nov 2026)

Pre-registered (`PLAN.md`); tables in `REPORT.md`; script `scripts/gold_studies/gs_p1_gld_tonnes.py`. 5515 daily GLD holdings (SPDR archive) 2004-11-18 → 2026-10-22, priced on GC=F; the trust posts day T after the COMEX settlement, so entry = close of T+1 (no forward window contains a public close); Newey-West t for the overlapping 5- and 20-session windows; costs 0.15 % per round trip.

**Verdict: FAIL as a forecast (6 of 6 signal × horizon tests; largest |t| 1.06); PASS as a description — the tonnes move WITH the price (same-week Spearman 0.29, stable across halves) and follow it rather than lead it. The ETF panel is context, not a timing tool.**

| Signal | Result (full sample) | Both halves |
|---|---|---|
| S1 · 1-day Δ tonnes → 5 sessions | IC 0.005 (t −0.13); tercile spread 0.08 % (t 0.69); OOS −2.31 %/yr after costs (t −1.80) → **FAIL** | IC 0.022 (t 0.52) / IC −0.014 (t −0.78) |
| S1 · 1-day Δ tonnes → 20 sessions | IC 0.007 (t 0.33); tercile spread 0.24 % (t 0.68); OOS −1.40 %/yr after costs (t −1.64) → **FAIL** | IC 0.005 (t 0.19) / IC 0.010 (t 0.22) |
| S2 · 5-day Δ tonnes → 5 sessions | IC 0.018 (t 0.08); tercile spread −0.02 % (t −0.22); OOS −0.75 %/yr after costs (t −0.42) → **FAIL** | IC 0.035 (t 0.44) / IC −0.005 (t −0.54) |
| S2 · 5-day Δ tonnes → 20 sessions | IC 0.018 (t 0.75); tercile spread −0.04 % (t 0.02); OOS −0.94 %/yr after costs (t −0.77) → **FAIL** | IC 0.014 (t 0.44) / IC 0.026 (t 0.68) |
| S3 · 20-day Δ tonnes → 5 sessions | IC 0.036 (t 1.06); tercile spread 0.10 % (t 0.69); OOS 2.14 %/yr after costs (t 1.06) → **FAIL** | IC 0.033 (t 0.51) / IC 0.036 (t 1.05) |
| S3 · 20-day Δ tonnes → 20 sessions | IC 0.036 (t 1.00); tercile spread 0.02 % (t 0.11); OOS 1.50 %/yr after costs (t 0.87) → **FAIL** | IC 0.010 (t 0.26) / IC 0.068 (t 1.43) |
| Same-week Δ tonnes vs Δ price (description, not a forecast) | Spearman 0.294 (n 1144) → **PASS as description** | 0.281 / 0.310 |

- Rank IC never clears |t| 2 at 5 or 20 sessions (largest |t| 1.06); the walk-forward long/flat rule after 0.15 % earns at best 2.14 %/yr over scaled buy-and-hold (S3@5, t 1.06) out of sample from 2013-09-12.
- Entry one session later (T+2) changes nothing (REPORT.md); the negative controls (60-session placebo, seeded shuffle) behave: ok = True.
- Lead/lag: Spearman(Δtonnes, Δprice) is 0.18 on the same day, 0.11 when the price leads by one session and 0.06 when the tonnes lead — the trust's holdings respond to the price, not the other way round (creations/redemptions settle after the move).
- Same-week relation: Spearman 0.294 (halves 0.281 / 0.310, n 1144); same day 0.185. In line with G-STUDY (weekly 4-week change t ≤ 1.0) and G-MACRO (contemporaneous only).
- Sample: 5515 trust dates 2004-11-18 → 2026-10-22 (median lag trust date → entry 1 day, max 5); halves at 2015-12-31; costs 0.15 % per round trip; data display-only under SPDR's disclaimer (O-1) — only statistics are published.
- **Use:** `ph.etf` and the ETF-HOLDINGS health tile keep the `context` badge with the caption 'moves with the price, does not lead it (GS-P1, 26 Oct 2026)'; divergence (price up, tonnes down) stays a description of who is buying, never an alert or a signal.

# TV-DRIVERS · NIFTY driver persistence and driver changes — report

**PROVISIONAL** — computed on inputs recomputed from the cached NSE files in a scratch store (PLAN §0.3: a past vintage is recomputed from the files), not on the stored, backfilled tables. No study result reaches a badge without the PM.

Run 2026-11-05T08:20:28+05:30 · inputs `~/.suryadhana_pm_scratch/v2/B8-STUDIES/inputs.duckdb` · plan `reports/terminal_v2/studies/drivers/PLAN.md` (pre-registered 5 Nov 2026 08:00 IST, before any result).

## The fit gate first (today's members stand in for past ones; the identity measures the damage)

Sessions 744 (2023-11-01 → 2026-10-30); gated decision dates 583 (minimum 500); weight methods ['rebuilt'].

| year | sessions | passing | decision_ok | mae60_median_pct |
|---|---|---|---|---|
| 2023 | 41 | 0.00 | 0.00 |  |
| 2024 | 249 | 0.68 | 0.60 | 0.06 |
| 2025 | 249 | 1.00 | 1.00 | 0.05 |
| 2026 | 205 | 1.00 | 0.90 | 0.04 |

## Graded statistics (signed; Newey-West 19 lags for D1/D2, plain t over thinned events for D3; halves split 30 Apr 2023)

| Statistic | mean full (t, n) | H1 (t) | H2 (t) | verdict | notes |
|---|---|---|---|---|---|
| D1 20-session leader's share of the next 20 sessions minus the weight leader's (sign +) | −0.0222 (−3.23, 583) |  (—) | −0.0222 (−3.23) | **FAIL** | |t| ≥ 2 against the registered sign in the full sample only; H1 empty: the pre-registered split (2023-04-30) falls outside the gated sample, so the both-halves condition cannot be met until the point-in-time share-count history reaches back |
| D2 the driver keeps driving: s·(R_leader − R_NIFTY), close T+1 → T+21 (sign +) | −0.1235 (−0.26, 583) |  (—) | −0.1235 (−0.26) | **FAIL** | H1 empty: the pre-registered split (2023-04-30) falls outside the gated sample, so the both-halves condition cannot be met until the point-in-time share-count history reaches back |
| D3r after a leader change: NIFTY next-20 return minus its mean (two-sided) | 0.4034 (0.41, 15) |  (—) | 0.4034 (0.41) | **PENDING** | 15 thinned events < 20 |
| D3v after a leader change: RV change (RVF − rv20) minus its mean (sign +) | 1.8793 (1.05, 15) |  (—) | 1.8793 (1.05) | **PENDING** | 15 thinned events < 20 |

## Traded leg and sensitivity

- TL-D2 (long the leader in cash when it pushed up, 20 sessions, vs NIFTY, after 0.931 % per round trip): −0.977 % per tranche (t −1.45; halves — / −1.45; 290 tranches) → ok = False.
- Futures pair at the 0.15 % floor per leg (not graded): −0.423 % (t −0.89).

## Controls (t full / H1 / H2)

| Control | statistic | t |
|---|---|---|
| N1_random_weight_leader | D1 | −6.43 / — / −6.43 (mean −0.0407) |
| N1_random_weight_leader | D2 | 0.30 / — / 0.30 (mean 0.0651) |
| N2_stale_leader_250 | D2 | −0.25 / — / −0.25 (mean −0.1661) |
| N3_shifted_events | D3r | 0.04 / — / 0.04 (mean 0.0259) |
| N3_shifted_events | D3v | −0.04 / — / −0.04 (mean −0.0785) |
| cap: weight leader | D2 | −1.39 / — / −1.39 (mean −0.5636) |

## Robustness (not graded)

| Row | mean full (t) | H1 (t) | H2 (t) |
|---|---|---|---|
| D1_raw_leader | −0.0216 (−3.43) |  (—) | −0.0216 (−3.43) |
| D1_rank_ic | −0.2055 (−15.68) |  (—) | −0.2055 (−15.68) |
| D2_window60 | −0.3638 (−0.75) |  (—) | −0.3638 (−0.75) |
| D3_window60 D3r | 0.5263 (0.55) |  (—) | 0.5263 (0.55) |
| D3_window60 D3v | 0.5104 (0.23) |  (—) | 0.5104 (0.23) |

Thinned leader-change events (15): 2024-05-29, 2024-08-09, 2024-09-18, 2024-11-07, 2025-03-12, 2025-04-22, 2025-06-03, 2025-07-03, 2025-09-03, 2025-10-08, 2025-12-26, 2026-02-18, 2026-05-21, 2026-07-29, 2026-09-25

Latest 20-session leader (context): `{"date": "2026-10-30", "leader": "HDFCBANK"}`.

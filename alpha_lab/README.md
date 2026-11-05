# Alpha Lab — self-contained strategy research (started 14 Oct 2026)

Owner request: build at least three deterministic, evidence-driven strategies that beat the market, including an
options/derivatives component; validate in stages (recent years first, then the untouched decade); keep every new
analysis **in this folder**; where code from the main repo is reused, carry a copy here.

**Honesty charter (binding on everything in this folder):**
1. **No strategy is "unbeatable", and nothing here promises always winning.** Markets pay for risk and information;
   the honest goals are: tilt the win probability, refuse known-bad situations, cap the left tail, and pay real costs.
   Any result that looks like free money is treated as a bug until proven otherwise.
2. **Pre-registration.** `PLAN.md` fixes universes, rules, parameters, cost model, gates and the order of runs
   *before* any backtest number is seen. A strategy passes or fails as specified. One revision round is allowed,
   must be labelled post-hoc, and re-gates on data the revision never saw.
3. **Staged validation (the owner's protocol).**
   - Stage 0 smoke: 1 Oct 2025 → latest (mechanics only, no verdict).
   - **Gate A:** 2020-01-01 → latest.
   - **Gate B:** 2011-01-01 → 2019-12-31, run **only if Gate A passes**, then the full 2011 → latest curve.
4. **Real frictions.** ICICI MoneySaver delivery costs via the vendored cost model, +0.05%/side slippage on
   delivery, +0.03%/side total friction on futures (brokerage+STT+slippage), both sides. No interest on idle cash
   unless stated (liquid-fund 6%/yr where the Desk convention applies).
5. **Point in time.** Survivorship-free NSE panel from 2010 (vendored loader); signals use data to the signal close
   only; entries at the next open; event data joins only after its real publication date; datasets that start late
   (F&O/deals 2019-10, MTF 2022-01) are NaN before, never zero.
6. **Paper only.** Nothing in this folder changes the Decision Desk, the live system, or any trading rule.
   Promotion to even paper-shadow status is the owner's decision after reading the reports.

**Layout**
```
alpha_lab/
  README.md, PLAN.md          this charter + the pre-registered plan
  inputs/                     the two research documents the owner attached (converted to markdown)
  lib/                        vendored copies of shared code (see lib/ORIGINS.md; drift-checked by tests/)
  backtest/engine.py          the common monthly/weekly engine (costs, equity curve, stats, gates)
  strategies/                 s1_sentinel.py, s2_horizon60.py, s3_leader_dip.py, overlays.py
  reports/                    everything generated here (claims matrix, gate runs, FINDINGS.md)
  tests/                      unit tests incl. vendored-drift checks
```

**Team protocol** (mapped to how a top-tier quant shop splits the work):
| Role | Who | Output |
|---|---|---|
| PM / principal scientist | main session | PLAN.md, final verdicts, FINDINGS.md |
| Data engineering | main session | lib/ vendoring, data_access, integrity checks |
| Claims analyst | fork agent A | `reports/claims_matrix.md`: every testable claim in the two input docs vs our evidence |
| Red-team validator | fork agent B | `reports/plan_review.md`: attacks on PLAN.md (look-ahead, multiplicity, costs, capacity) |
| Execution research | main session | strategy code + gate runs |
| Risk | engine | drawdown/exposure caps enforced in code, reported per run |

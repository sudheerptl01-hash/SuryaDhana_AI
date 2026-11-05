# Desk filter "skip after bad results": findings (11 Oct 2026)

Pre-registered in `PLAN.md`; full numbers in `REPORT.md`; script `scripts/results_filter_backtest.py` (the Desk's own
simulator and entry blocklist, fed with results events, no strategy code changed).

**Verdict: FAIL — no material effect, do not adopt.**

> **Correction, 14 Oct 2026:** re-run on corrected results release times (2025–26 governance filings had been
> taken as results; see `reports/results_drift/FINDINGS.md`) in `corrected_2026-10-14/`, with the corrected
> events file (that report's header names the default path, but `--events` pointed at
> `reports/results_drift/corrected_2026-10-14/events.csv`). Holdout CAGR with the filter **3.86%** vs 3.98% without
> (it was 4.30% before the correction). Full period 13.16% vs 13.21%. **Verdict unchanged, and clearer: no benefit.**

- Holdout (Jul-2024 →): CAGR 4.30% vs 3.98% for the approved rules, but max drawdown −7.91% vs −7.90%. The
  pre-registered bar requires the drawdown to be no deeper, and it is deeper by 0.01 percentage points. The verdict
  is FAIL by the rule; in practice the effect is neutral.
- Full window 2015–2026: CAGR 13.27% vs 13.22%, with the same −22.0% drawdown. Discovery: 15.53% vs 15.56%.
- Why so little: the filter kept only **23** names out of the Desk in 11 years. Momentum leaders rarely suffer a
  ≤ −5% results reaction. The names it skipped did fine anyway (median next month +0.4%, mean +4.2%).

**What stays useful:** the stock-level finding (reports/results_drift, H2 PASS) still holds for discretionary
buys outside the Desk. That is why the terminal shows ⚠ BAD RESULTS as a flag, not as a Desk rule.

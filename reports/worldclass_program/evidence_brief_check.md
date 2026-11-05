# Evidence Brief ("The Canon…") vs the terminal — feature check (15 Oct 2026, ~04:00 IST)

Owner asked whether the Algo Trading Evidence Brief's content is already included as features.
Strategy claims were reconciled earlier in `alpha_lab/reports/claims_matrix.md`; this checks the
brief's ACTIONABLE/feature content (§5, §6, §8, §9 playbook, §10 plan) against the repo tonight.

## Included (verified)
- Sleeve 1 equity momentum rotation = the live Decision Desk + alpha_lab S1 (both gates passed);
  regime gate, vol-adjusted ranking, monthly cadence — all per the brief's A-grade template.
- Point-in-time data layer + daily ingestion (DuckDB panel 2010→, EOD pipeline, xs_features).
- Validation gauntlet: purged WFO, DSR/effective-trials, pre-registered gates (alpha_lab) +
  triple-barrier/CPCV in the ML workspace.
- Costs + ladders: shared/trading_costs.py, −2% halt, −20% HARD; RSK page (W5) shows the ladder.
- Sizing: 15% vol target (Desk), quarter-Kelly sizer (legacy risk service), costs ticket.
- Paper-first discipline + ledger: Desk paper (Sep→), S1 shadow (15 Oct→), SQLite audit,
  slippage store.
- §5.2 options structures + Greeks: OSTR (tonight) prices all of them; DERV supplies VIX
  percentile/PCR context.

## Included as tooling, deliberately not promoted (evidence or owner rules)
- Sleeve 2 ML swing: pipeline exists; ML < Desk after costs (reports/ml_labels) → parked;
  meta-label/ML-veto = queued lead.
- Sleeve 5 VRP selling: brief itself says 0% until the lot wall; tooling ready, strategy parked.
- OpenAlgo/VPS/static-IP/algo-ID: live-compliance path; Breeze-direct + Mac is the costed owner
  decision; moot in paper mode (GAPS.md §6).

## NOT included — genuinely new items from this brief (queue, pre-registered where research)
1. **Sleeve 3 MCX trend** (EWMAC + breakout + carry on gold/crude/natgas, vol-targeted) —
   prerequisite: MCX bhavcopy history ingest; tonight's MCXG desk is monitoring, not strategy.
2. **IC-decay monthly report per sleeve** — small ops/research feature; nothing equivalent exists.
3. **Event-calendar sub-signals**: index add/delete flow, F&O-list changes, lock-in-expiry
   tracker (PEAD itself already tested: bad PASS / good FAIL).
4. **Slippage-audit closed loop**: realised paper/live slippage auto-feeding the cost model
   (store exists; the feedback loop does not).
5. **HRP across sleeves** — premature with one live sleeve; activates when a second passes gates.

These five feed the final REPORT's "missing — buildable" list alongside the trader-critic's findings.

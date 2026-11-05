# W8 — QuantLab adoptions A1 (MC drawdown lens) + A2 (Friday decision journal) · build report, 15 Oct 2026

Spec: `reports/bloomberg_program/quantlab_gap_analysis.md` §A1/§A2. Gates FROZEN (PLAN Amendments v2) —
A1 is a REPORTING lens only, A2 is operations plumbing. No gate, StrategyConfig, decision_desk,
trading_costs, strategy or flag file was touched. No restarts, no commits, no Telegram sends tonight.

## Shipped (own files)

| File | What |
|---|---|
| `alpha_lab/backtest/mc.py` NEW | Circular block bootstrap (block = 3 months, wrap-around) of the MONTHLY (ME) return series of the persisted gate equity curves (`reports/s1*_equity.csv` — reused, engine logic not forked; same ME convention as `engine.monthly_excess_ir`); 10,000 resamples over the window's own horizon; DD vs running peak incl. start capital; p50/p90/p95/max beside realized maxDD (daily AND month-end granularity). `default_rng(seed=108)`, fully vectorized — **0.1 s for all 5 windows** (10k × up to 189 months). CLI `--strategy s1\|s1h\|both` (both = default, writes `reports/mc_drawdown.md` + `.json`), `--resamples/--block/--seed`. `shadow_status_lines()` helper for the shadow patch (never raises; [] unless `mc_drawdown.md` exists). |
| `alpha_lab/tests/test_mc.py` NEW | 8 tests: constant-positive → p95 = 0; one −50% month in 72 → p95 ≥ single-path DD and max ≈ double-crash; seed determinism (108 = 108 ≠ 109); block-3 vs iid shuffle on an autocorrelated regime series → deeper p95/p50 (clustering preserved, asserted directionally); circular wrap mechanics + horizon length; ME convention matches the engine; DD-FRAGILE truth table on a deterministic curve (fires only when realized passed AND p95 breached; `budget=None` never flags); shadow line absent/broken-json/present. |
| `scripts/journal_composer.py` NEW | `compose_weekly()` → deterministic markdown template (NO LLM, localhost only: ui-api + the controller telemetry ui-api proxies + alpha_lab report files). Sections: Desk actions (NAV week/since-start from nav marks, plans→buys/sells/est-costs, events, emergency-stop banner) · S1/S1H shadow (since-start + week NAV vs NIFTY from `shadow_nav.csv`, rebalances, honest EW-not-tracked-live line) · vetoes that fired (`today_book.md`: blocked count + refused leaders with reasons) · regime (monitor 0–4 score + S1 crash filter) · next decisions (month-end signal date, weekday count, signal-day/weekend edge cases) · job failures (scheduler `last_status` + ERROR lines in the log ring, **with an honesty note when the ring doesn't reach back to Monday**). Per-section degradation when any source is down; `api.missing` listed. Prints `RESULT {week, path, summary, telegram}` for the scheduler; **never sends anything itself**. `--dry-run` prints and writes nothing. |
| `scripts/tests/test_journal.py` NEW | 7 tests: calendar (ISO week key, Mon–Fri window, last weekday of month — 30 Oct, weekday counting); signal-day/Saturday edges; full-week compose on canned endpoints + tmp shadow fixtures (deterministic, one screenful < 45 lines, digest ≤ 3,500 chars); every section degrades honestly with all sources down; log-ring honesty note; desk stop flag/no-NAV; shadow needs ≥ 2 sessions for a week change. |
| `scripts/master_controller.py` (sole editor tonight) | Header cron doc line + `weekly_journal()` job (pattern-matched to `daily_wrap`/`nse_filings_weekly`: `_get_lock` + `_track`, subprocess with `PYTHONPATH=_ROOT`, parses `RESULT`, `_record_notification("journal", …)`, digest sent at runtime via the existing `_alerts.info` AlertDispatcher — its Markdown-400 plain-text fallback covers underscore-heavy job ids) + registration `CronTrigger(day_of_week="fri", hour=20, minute=10, timezone=IST)`, `misfire_grace_time=12h`. 20:10 sits after desk_daily 19:30 / alpha_shadow_daily 19:50, before nse_positions_catchup 20:30; the 18:30–21:15 freeze governs restarts, not jobs. |
| `alpha_lab/reports/mc_drawdown.md` + `.json` | The A1 run output (table below). |

## A1 — the pre-registered DD-FRAGILE rule (written in `mc.py`'s docstring BEFORE any real curve ran)

> A variant is **DD-FRAGILE** on a gate window if the p95 resampled drawdown breaches that gate's
> pre-registered absolute drawdown budget even though the realized path passed it.
> Budgets, cited from `alpha_lab/PLAN.md` "Stages and gates" criterion 2 (unchanged by Amendments v2):
> **Gate A −30% absolute** ("Max drawdown ≥ −30% absolute…"), **Gate B −35% absolute**. Gate A's
> relative 1.25×NIFTY leg is NOT resampled (single benchmark path). The full 2011→ window has no
> pre-registered budget → no flag. REPORT-ONLY; gates frozen.

Note: the W8 brief's "−25% for S1 class" was a placeholder — per its own instruction the budgets were
read from PLAN/Amendments and are −30% (A) / −35% (B), cited above. Synthetic tests ran green before
the real curves were touched.

## A1 — S1/S1H MC table (10,000 resamples, block 3, seed 108; signed DD %)

| Run | Window | Months | Realized DD (daily) | Realized DD (ME) | p50 | p90 | p95 | Max | Budget | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| S1 | gateA | 81 | −16.5% | −13.2% | −14.5% | −23.1% | −26.0% | −46.3% | −30.0% | within budget |
| S1 | gateB | 107 | −34.6% | −26.5% | −23.2% | −34.9% | −39.2% | −68.6% | −35.0% | **DD-FRAGILE** |
| S1 | full | 189 | −34.6% | −26.5% | −23.4% | −34.1% | −37.8% | −65.4% | — | report-only (no budget) |
| S1H | gateA | 81 | −24.0% | −23.6% | −19.8% | −28.2% | −31.9% | −52.9% | −30.0% | **DD-FRAGILE** |
| S1H | gateB | 107 | −29.0% | −27.8% | −22.4% | −34.0% | −38.2% | −65.1% | −35.0% | **DD-FRAGILE** |
| S1H | full | — | curve not persisted (`s1H_full_equity.csv`) | | | | | | | |

Realized daily DDs reproduce FINDINGS.md exactly (−16.5 / −34.6 / −24.0 / −29.0). The honest read
(full paragraph in `alpha_lab/reports/mc_drawdown.md`): reshuffling 3-month blocks of the SAME history
breaches the budget in >5% of resamples for S1-gateB and both S1H windows — quantifying FINDINGS'
"S1's Gate-B pass sits at the edge of its −35% bar" warning. Month-end granularity understates
intramonth DD (compare the two realized columns), which makes a p95 breach the conservative direction.
Changes no verdict; the owner decides any use.

## Patch blocks for the PM (shared files — NOT edited by me)

### 1. `alpha_lab/paper/shadow.py` (status composer line; shows only when `mc_drawdown.md` exists)
a) imports — after the exact line `from backtest import engine  # noqa: E402`:
```python
from backtest import mc  # noqa: E402  (A1 drawdown lens — report-only)
```
b) in `render_status(...)` — immediately BEFORE the exact anchor line
`    lines += ["", "Gated evidence: alpha_lab/reports/FINDINGS.md · rules: alpha_lab/PLAN.md §S1 + Amendments v2."]`:
```python
    lines += mc.shadow_status_lines()
```
Verified output of the helper against tonight's real report:
`MC p95 DD (Gate A, 10k×3m block bootstrap, report-only): S1 -26.0% (realized -16.5%) · S1H -31.9% (realized -24.0%)`
(absent report / broken json → `[]`, status never breaks; no shadow test touches `render_status`).

### 2. `alpha_lab/README.md` (run docs) — in the Layout block, after the `backtest/engine.py` line:
```
  backtest/mc.py              A1 Monte-Carlo drawdown lens: block-bootstrap DD distribution (REPORT-ONLY, never gates)
```

### 3. `CLAUDE.md` "How to run things", alpha-lab block (optional, owner's file):
```bash
PYTHONPATH=alpha_lab $P alpha_lab/backtest/mc.py            # A1 MC drawdown lens → alpha_lab/reports/mc_drawdown.md (report-only)
```

### 4. `alpha_lab/reports/FINDINGS.md` (optional pointer, "Caveats" list):
```
- A1 MC drawdown lens (report-only, 15 Oct): `reports/mc_drawdown.md` — pre-registered p95 rule flags S1 gateB and S1H gateA/gateB DD-FRAGILE; gates and verdicts unchanged.
```

## A2 — live dry-run output (`python scripts/journal_composer.py --dry-run`, stack up, nothing sent)

```
# Weekly decision journal — 2026-W42 (12 Oct → 16 Oct 2026)

PAPER ONLY — nothing below is a live order or a trade instruction.

## Decision Desk (paper, monthly momentum)
- NAV ₹5,01,389 · +0.05% this week (3 marks) · +0.28% since start · 0 positions · drawdown 0.00%
- No rebalance this week (monthly cadence — see Next decisions).

## S1/S1H paper shadow (alpha_lab)
- Since 15 Oct start: S1 0.00% · S1H 0.00% · NIFTY 0.00%
- Week change n/a (1 session(s) of shadow NAV inside this week).
- No rebalance yet — armed and flat; first signal = the last October session.
- Benchmarks: NIFTY above; the EW-universe benchmark is a gate-time artifact (FINDINGS.md), not tracked live.

## Vetoes that fired (S1 avoid rules)
- 191 of 300 universe names blocked (as of 2026-10-14)
- Momentum leaders refused: LIQUID1 r1 [near_52w_low] · LIQUIDCASE r2 [near_52w_low] · CUPID r3 [vol60_top_decile] · WELCORP r4 [vol60_top_decile] · CPPLUS r6 [vol60_top_decile] · SHILPAMED r7 [vol60_top_decile] · +13 more

## Regime
- Market monitor: 0/4 RISK-OFF · exposure guide 0–20% · 9 days at this score
- S1 crash filter: RISK-OFF (NIFTY 22,623 vs 200-DMA 24,218)

## Next decisions
- Month-end momentum signal: Fri 30 Oct (last weekday of the month), 11 weekday(s) away; fills at the next open. NSE holidays not subtracted.
- Desk and S1 shadow decide on the same cadence; crash filter is evaluated at the signal.

## Job health this week
- Jobs whose LAST run errored: db_backup_daily
- No ERROR lines in the controller log window.
- Honesty note: the log ring only reaches back to Wed 14 Oct 23:49 — earlier failures this week are not visible here.

Deterministic template (scripts/journal_composer.py, no LLM) · evidence: alpha_lab/reports/FINDINGS.md · plan: docs/PRODUCT_STRATEGY.md
```
(+ the Telegram digest block, printed under a "NOT sent" banner; the EW line was added after this
capture and re-verified live.) Real catch already: **db_backup_daily's last run errored** — surfaced
for the owner, not touched tonight.

## Test results

- `alpha_lab` suite: **20 passed** (12 baseline + 8 new `test_mc.py`), 0.3 s.
- `scripts/tests`: **137 passed** (130 baseline + 7 new `test_journal.py`), 1.8 s — includes the
  master_controller import tests, so the edited controller still loads clean.
- `compileall` on `master_controller.py`, `journal_composer.py`, `mc.py` + both test files: OK.
- `mc.py` full run: 0.1 s (requirement "seconds": met with margin). Dry-run against the live stack: above.
- Not run (out of W8 scope, unchanged code paths): ui-api/execution suites, tsc.

## Risks / notes

1. **Three windows flag DD-FRAGILE** under the pre-registered rule (S1 gateB, S1H gateA+gateB). This is
   information, not a gate: block-3 bootstrap cuts >3-month dependence (momentum crashes can be longer),
   and ME granularity understates realized pain — both caveats are printed in the report. Owner should
   read `mc_drawdown.md` before leaning on S1H's cushion.
2. The shadow patch (block 1) is inert until the PM applies it; `shadow_status_lines()` is already
   tested against absent/broken/real inputs.
3. Journal week-maths need ≥2 NAV marks in the week (first real Friday run, 16 Oct, will have them for
   the Desk; the shadow line says "n/a" honestly until it has two sessions).
4. `weekly_journal` fires first on Fri 16 Oct 20:10 IST; it sends ONE `_alerts.info` digest at runtime
   (controller's existing helper, Markdown-fallback safe). Nothing was sent tonight (dry-run only).
5. Log-ring failures section sees only the last 500 controller lines; the honesty note states the
   visible window every time it falls short of Monday.

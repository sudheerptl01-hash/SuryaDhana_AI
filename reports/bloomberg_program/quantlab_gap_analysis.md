# QuantLab Channel Review vs the real SuryaDhana — what's actually missing (14 Oct 2026, ~22:50 IST)

Source analyzed: the owner-attached report "QuantLab Channel Review: Strategies, Evidence and SuryaDhana Gaps"
(reviews @Quantlab, 376 videos; itself a gap analysis). **Critical reading note:** that report graded the channel
against the *planning briefs'* 90-day blueprint — not against this repository. Several of its "Adopt — not in any
brief" items already run in production here. This document re-grades every one of its recommendations against the
code that exists tonight.

## Its seven actions, re-checked against the repo

| Report's action | Repo reality (evidence) | Re-verdict |
|---|---|---|
| 1. "Decide the storage engine (Parquet+DuckDB; QuestDB only for ticks)" | Decided long ago and in production: DuckDB 4.4 GB survivorship-free store + parquet artifacts; snapshot/backup machinery shipped tonight (B1) | **Already done** |
| 2. "Add Monte Carlo drawdown acceptance tests to validation" | **Genuinely missing.** alpha_lab gates (PLAN Amendments v2) judge the single realized path's maxDD; no resampled drawdown distribution anywhere | **ADOPT — best item in the report** (spec below) |
| 3. "Build a Telegram alert bot" | Exists and rich: 20 commands, price/±%/filing/results alerts, ICICI OTP hand-off, /shadow, morning/close/wrap notes | **Already done** |
| 3b. "Trading-holiday tracker" | Exists: NSE holiday calendar endpoint + scheduler holiday guards + ECO page (Dussehra 20 Oct handled) | **Already done** |
| 3c. "LLM weekly trade journal over the ledger" | Partial: daily wrap (21:00), Desk month-end brief, shadow Friday NAV line — but **no weekly decision journal** ("what did the system decide and why: picks, vetoes that fired, costs, vs benchmarks") | **ADOPT (small)** (spec below) |
| 4. "Watch the AWS deployment video before choosing a VPS" | Decision already parked deliberately: memory `cloud_hosting_costs` (AWS Mumbai ₹730–9,650/mo; advice = Mac + static-IP gateway until capital grows); SEBI static-IP rule known | **Covered as a pending owner decision** — the video adds nothing the costing note lacks |
| 4b. "HMM regimes walkthrough when regime work tops the queue" | Already tagged a refinement in our own claims work; regime score (0–4) runs in production | **Covered — keep queued** |
| 5. "Queue K-means peer clustering + RS-momentum sector feature" | Matches our open leads: claims_matrix SEC-01/02 are *untested-testable-now*; MKT tab has industry rotation but no RS-momentum second axis | **ADOPT as research tickets** (pre-registration required per house rules) |
| 6. "Skip the strategy demos" (MACD/EMA, RSI+ATR, NN/RL) | Agrees with our evidence: handbook-style systems FAILED gates here after real costs; NN/RL demos are below our validation bar | **Agree — nothing to take** |
| 7. "Channel = monthly tooling feed; beware distraction" | — | Agree |

**Strategy/evidence content:** the report itself concludes the channel is behind our briefs on validation, costs,
F&O features and point-in-time hygiene — and it is *further* behind the repo (738-test stack, pre-registered
gates, live paper shadow). Nothing to import on the strategy side. One of its B-grades (Chan cointegration pairs
via F&O legs) stays where our own evidence put pairs: test-later-small, after core sleeves.

### Addendum (15 Oct, after the Bloomberg program): one more of its gaps closed tonight
The report's §4 row "Websocket real-time layer — Adopt at execution time" is now **DONE**, ahead of its
schedule: the Bloomberg program shipped the Breeze-websocket L1 tick engine (data-service `live_ticks.py`,
ui-api `/api/quotes/ticks`, `ui/lib/liveTicks.ts`) — kill-switched `LIVE_TICKS`, zero REST quota, verified
CONNECTING→LIVE 3/3 subscribed in a valid session. Its "QuestDB only if tick data arrives" advice is therefore
live now (A4 below): ticks are in-memory only; parquet-append is the recommended first persistence step.

## The genuinely adoptable pieces (specs)

### A1. Monte Carlo drawdown acceptance test (validation upgrade — the report's one real catch)
- Where: `alpha_lab/backtest/engine.py` + a new `alpha_lab/backtest/mc.py`; wired into gate output and the
  shadow's status.
- Spec: block-bootstrap the strategy's **monthly** return series (block = 3 months, preserves regime clustering),
  10,000 resamples over the window length; report the drawdown distribution (p50/p90/p95/max) alongside the
  realized maxDD. **Acceptance addition (pre-registered before first use):** a strategy variant is flagged
  "DD-FRAGILE" if its p95 resampled drawdown breaches the gate's budget even when the realized path passed —
  reported, never silently gating (gates are frozen by Amendments v2; this is an added lens, owner decides use).
- Also: run it once on S1/S1H gate curves and print in FINDINGS; add the p95 line to `shadow_status.md`.
- Effort: ~2–3 h including tests. **Recommend building in the next session, not tonight** (tonight's builders are
  at capacity and alpha_lab edits need their own care).

### A2. Weekly decision journal (Friday, after the shadow job)
- Where: extend `scripts/master_controller.py` weekly (Fri 20:10) job + a small composer module; Telegram + a
  markdown appended under `reports/journal/`.
- Content, mechanical not "LLM-mystical": this week's Desk/shadow actions (rebalances, fills, costs), vetoes that
  fired and on whom, regime state changes, NAV vs NIFTY/EW, upcoming decisions (next month-end), any job
  failures. One screenful. The "LLM" part is just the prose glue — generated at compose time by the controller
  calling nothing external (template text; keep it deterministic — honest improvement over the report's idea,
  which assumed an external LLM call).
- Effort: ~1–2 h. Next session.

### A3. Two pre-registered research tickets (queue, do not run tonight)
1. **K-means peer clustering** for SEC-01/02: cluster 252-day return correlations (universe L), k by silhouette,
   point-in-time (rolling refit yearly); use clusters as peer groups for the spillover features; PASS bar per the
   house Robust rule. Also doubles as a pairs-candidate generator (ties to the carry/pairs later-small note).
2. **RS-momentum sector feature** (the RRG second axis): slope of sector RS-ratio vs NIFTY alongside the existing
   rotation rank; test as a MKT-level context feature; optional four-quadrant RRG panel in the MKT tab if the
   feature proves informative (visualization follows evidence, not before).

### A4. Tick persistence note (forward-looking, ties to tonight's B3)
The report's "QuestDB only if tick data arrives" is now live advice: B3's feed keeps ticks in memory only.
Decision for later: append ticks to daily parquet (cheap, enables the footprint/CVD research the intraday memory
wants) vs a TSDB. Recommend parquet-append first; revisit a TSDB only if intraday research becomes a program.

## Marketing filter
The report's red-flag checklist for trading channels is sound and worth keeping; filed here by reference. Its
conclusion stands for us too: the risk isn't bad advice, it's distraction — we take A1–A4 and ignore the other
370 videos.

## Bottom line
Strategy content: nothing missing on our side. Operations: three of its five "missing" utilities already run in
this repo (the report couldn't see them). Real adoptions: **Monte Carlo drawdown lens (A1)**, **weekly decision
journal (A2)**, **two research tickets (A3)**, **tick-persistence decision noted (A4)** — all queued for the next
session; none touches tonight's build.

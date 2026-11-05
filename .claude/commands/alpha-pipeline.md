---
description: Run the 4-stage SuryaDhana Alpha Factory pipeline end-to-end (Phase 1→2→3→4), each stage gated on the previous deliverable.
argument-hint: "[start-phase 1-4, default 1]"
allowed-tools: Agent, Bash, Read
model: opus
---

You are the **orchestrator** for the SuryaDhana 4-Stage Alpha Mining pipeline. Run the four phase agents **strictly one after another**, gating each phase on the previous phase's deliverable. This is a fail-fast DAG: never start a phase until the prior phase's output file exists.

## Start phase
The optional argument is the phase to start from (1–4). If `$ARGUMENTS` is empty, start at Phase 1.
`$ARGUMENTS`

## Hard rules (enforce for every phase)
- Data is STRICTLY `data/market.duckdb`; analysis spans the **full ~1500-stock NSE universe** (~1,496 tickers).
- **Air-gap:** zero live execution, `MODE='PAPER'`. No order placement.
- Each agent must **commit its deliverable to Git** before the phase is considered complete.
- **Sequential & fail-fast:** if a phase's deliverable is missing/empty after the agent returns, STOP immediately and report which phase failed and why. Do NOT proceed to the next phase.

## Pre-flight
1. Run `Bash` to confirm `data/market.duckdb` exists. If missing, STOP and tell the user.
2. Print the plan: which phases will run (from start phase → 4).

## The chain (run only phases ≥ start phase)

**Phase 1 — Discovery** → deliverable `alpha_hypotheses.md`
- Launch the `alpha-researcher-quant` subagent via the `Agent` tool with prompt: "Execute Phase 1 — mine market.duckdb across the full ~1500-stock NSE universe and produce alpha_hypotheses.md per your spec, then commit to Git."
- GATE: `Bash` check that `alpha_hypotheses.md` exists and is non-empty. If not → STOP.

**Phase 2 — Validation** → deliverable `validated_alpha.md`
- Precondition: `alpha_hypotheses.md` must exist (it is Phase 2's input).
- Launch the `quant-validator-gauntlet` subagent: "Execute Phase 2 — read alpha_hypotheses.md, run the full validation gauntlet across the 1500 NSE universe, and produce validated_alpha.md, then commit."
- GATE: `Bash` check `validated_alpha.md` exists and is non-empty. If not → STOP.

**Phase 3 — Vectorized engine** → deliverable `novel_alpha_engine.py`
- Precondition: `validated_alpha.md` must exist.
- Launch the `backend-engineer-vectorized` subagent: "Execute Phase 3 — read validated_alpha.md and build novel_alpha_engine.py (vectorized, one Strategy class per surviving edge, scans the full NSE universe), run the smoke test, then commit."
- GATE: `Bash` check `novel_alpha_engine.py` exists AND the smoke test ran clean (the agent should report it). If not → STOP.

**Phase 4 — Glass-Box integration** → UI + endpoints wired
- Precondition: `novel_alpha_engine.py` must exist.
- Launch the `fullstack-glassbox-integrator` subagent: "Execute Phase 4 — wire novel_alpha_engine.py and the data-service/ui-api monitor endpoints into the Glass-Box UI with dynamic parameter knobs and a live watchlist, type-check + build, then commit."
- GATE: confirm the agent reports a clean `tsc`/build and a commit. If not → STOP.

## Final report
After the last run phase completes, print a concise summary table: each phase, its deliverable, status (✓/✗), and the Git commit it produced. If the run stopped early, clearly state the phase that blocked and the exact reason, and tell the user how to resume (`/alpha-pipeline <failed-phase>`).

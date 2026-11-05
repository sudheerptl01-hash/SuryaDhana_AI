#!/usr/bin/env bash
#
# run_alpha_pipeline.sh — Unattended SuryaDhana 4-Stage Alpha Factory pipeline.
#
# Runs the four phase agents STRICTLY one after another in headless mode,
# gating each phase on the previous phase's deliverable file. Fail-fast: if any
# deliverable is missing/empty, the pipeline stops and exits non-zero.
#
#   Phase 1  alpha-researcher-quant        -> alpha_hypotheses.md
#   Phase 2  quant-validator-gauntlet      -> validated_alpha.md
#   Phase 3  backend-engineer-vectorized   -> novel_alpha_engine.py
#   Phase 4  fullstack-glassbox-integrator -> Glass-Box UI integration (+ git commit)
#
# USAGE
#   scripts/run_alpha_pipeline.sh            # run all phases 1->4
#   scripts/run_alpha_pipeline.sh 3          # resume from Phase 3
#
# ENV OVERRIDES
#   CLAUDE_MODEL   model for each phase (default: opus)
#   CLAUDE_PERM    permission flag (default: --dangerously-skip-permissions)
#                  Headless agents must write files + run git/python unattended,
#                  so permissions are bypassed. Safe here ONLY because the
#                  pipeline is air-gapped (MODE=PAPER, zero live execution).
#                  Set CLAUDE_PERM="--permission-mode acceptEdits" to be stricter.
#
set -euo pipefail

ROOT="/Users/sudheer/MahaKubera_108/SuryaDhana_AI"
cd "$ROOT"

MODEL="${CLAUDE_MODEL:-opus}"
PERM="${CLAUDE_PERM:---dangerously-skip-permissions}"
START="${1:-1}"
mkdir -p logs

if ! command -v claude >/dev/null 2>&1; then
  echo "✗ 'claude' CLI not found on PATH." >&2; exit 1
fi
if [ ! -f data/market.duckdb ]; then
  echo "✗ data/market.duckdb missing — cannot run analysis." >&2; exit 1
fi

run_phase () {
  local n="$1" agent="$2" deliverable="$3" prompt="$4"
  if [ "$START" -gt "$n" ]; then
    echo "↷ Skipping Phase $n ($agent) — start=$START"
    return 0
  fi
  echo ""
  echo "════════════════════════════════════════════════════════════"
  echo "▶ PHASE $n — $agent"
  echo "════════════════════════════════════════════════════════════"
  claude -p "$prompt" --model "$MODEL" $PERM 2>&1 | tee "logs/alpha_phase_${n}.log"
  # Gate (Phase 4 has no single-file deliverable; pass "-" to skip the check)
  if [ "$deliverable" != "-" ] && [ ! -s "$deliverable" ]; then
    echo "✗ PHASE $n FAILED — deliverable '$deliverable' is missing or empty. Stopping pipeline." >&2
    exit 1
  fi
  [ "$deliverable" != "-" ] && echo "✓ Phase $n complete → $deliverable"
}

run_phase 1 alpha-researcher-quant alpha_hypotheses.md \
  "Use the alpha-researcher-quant agent to Execute Phase 1: mine data/market.duckdb across the FULL ~1500-stock NSE universe, produce alpha_hypotheses.md exactly per your spec, and commit it to Git."

run_phase 2 quant-validator-gauntlet validated_alpha.md \
  "Use the quant-validator-gauntlet agent to Execute Phase 2: read alpha_hypotheses.md, run the full validation gauntlet across the 1500 NSE universe in data/market.duckdb, produce validated_alpha.md, and commit it to Git."

run_phase 3 backend-engineer-vectorized novel_alpha_engine.py \
  "Use the backend-engineer-vectorized agent to Execute Phase 3: read validated_alpha.md, build a vectorized novel_alpha_engine.py (one Strategy class per surviving edge, scanning the full NSE universe), run its smoke test, and commit it to Git."

run_phase 4 fullstack-glassbox-integrator - \
  "Use the fullstack-glassbox-integrator agent to Execute Phase 4: wire novel_alpha_engine.py and the data-service / ui-api monitor endpoints into the Glass-Box UI with dynamic per-strategy parameter knobs and a live watchlist, type-check + build the UI, and commit the integration to Git."

echo ""
echo "🎉 Alpha Factory pipeline finished (phases ${START}→4). Logs in ./logs/alpha_phase_*.log"

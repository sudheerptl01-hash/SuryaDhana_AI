export const meta = {
  name: 'swing-label-round2',
  description: 'Round 2: five refiners converge on the 5-20d label stack, two judges rank it, devil\'s advocate tries to break it',
  phases: [
    { title: 'Refine', detail: 'relative, dual-condition, regime, event sleeve, alpha/ensemble' },
    { title: 'Judge', detail: 'portfolio-manager and statistician judges rank the label stack' },
    { title: 'Attack', detail: 'devil\'s advocate reproduces and stress-tests the winner' },
  ],
}

const LAB = '/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab'

const COMMON = (id) => `You are a senior quant researcher on a systematic NSE (India) equity team, round 2 of a label-design study for a 5-20 trading-day swing trader.
Read, in order: ${LAB}/TEAM_BRIEF.md, ${LAB}/ROUND2_BRIEF.md (your role is the section "${id}"), ${LAB}/lablib.py (especially the v2 section: Sim, xs_metrics, walk_forward2, DEV/HOLDOUT), ${LAB}/validate_sim.json, ${LAB}/build_meta.json, ${LAB}/features_meta.json. Skim round-1 artifacts in ${LAB}/results/ as needed (results/_lead/round1_results.json has every round-1 structured output).
Rules: lab v2 only (no sector data, ETFs excluded, elig_base as rebuilt). Next-open entry; NaN (never 0) where undefined; filters choose samples, never change label values; walk_forward2 for models; L.Sim.compare (horizon-matched random baseline, NW t) for investability; xs_metrics for learnability; 50 and 80 bps; select on DEV only, report 2026 holdout separately; state how many variants you tried. n_jobs=2 for LightGBM; another agent shares this 4-CPU/15GB machine.
Work in ${LAB}/results/${id}/ (create it). Save scripts there; run them with python3 via Bash (timeout up to 600000 ms); keep each run < ~9 min by staging and persisting intermediates (npz/parquet/json). Keep results.json updated. Write REPORT.md with markdown tables of real numbers (if direct writing of the report is blocked, generate it from a python script). Be quantitative, honest about negatives, and explicit about event rates and how they move when parameters change.`

const CAND = {
  type: 'object',
  properties: {
    candidate_id: { type: 'string' }, family: { type: 'string' }, definition: { type: 'string' },
    horizon: { type: 'string' }, event_rates: { type: 'string' },
    xs_ic_dev: { type: ['number', 'null'] }, xs_ic_holdout: { type: ['number', 'null'] },
    xs_auc_note: { type: 'string' },
    dev_cagr_50: { type: ['number', 'null'] }, dev_random_cagr_50: { type: ['number', 'null'] },
    dev_excess_nw_t: { type: ['number', 'null'] }, dev_maxdd: { type: ['number', 'null'] },
    dev_cagr_80: { type: ['number', 'null'] },
    holdout_cagr_50: { type: ['number', 'null'] }, holdout_random_cagr_50: { type: ['number', 'null'] },
    holdout_excess_nw_t: { type: ['number', 'null'] },
    sensitivity_note: { type: 'string' },
    pros: { type: 'array', items: { type: 'string' } }, cons: { type: 'array', items: { type: 'string' } },
    verdict: { type: 'string', enum: ['strong', 'promising', 'weak', 'reject'] },
  },
  required: ['candidate_id', 'family', 'definition', 'horizon', 'event_rates', 'pros', 'cons', 'verdict'],
}
const REFINE_SCHEMA = {
  type: 'object',
  properties: {
    agent_id: { type: 'string' }, headline: { type: 'string' },
    candidates: { type: 'array', items: CAND },
    key_findings: { type: 'array', items: { type: 'string' } },
    recommendation: { type: 'string' },
    lab_issues_found: { type: 'array', items: { type: 'string' } },
    variants_tried: { type: ['number', 'null'] }, report_path: { type: 'string' },
  },
  required: ['agent_id', 'headline', 'candidates', 'key_findings', 'recommendation', 'report_path'],
}
const STACK_SCHEMA = {
  type: 'object',
  properties: {
    judge: { type: 'string' },
    primary_selection_label: { type: 'string' },
    avoid_label: { type: 'string' },
    regime_layer: { type: 'string' },
    event_sleeve: { type: 'string' },
    horizon_and_exit: { type: 'string' },
    ranking: { type: 'array', items: { type: 'object', properties: {
      rank: { type: 'number' }, candidate_id: { type: 'string' }, score_0_100: { type: 'number' }, reason: { type: 'string' } },
      required: ['rank', 'candidate_id', 'score_0_100', 'reason'] } },
    expected_performance: { type: 'string' },
    confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
    caveats: { type: 'array', items: { type: 'string' } },
    open_questions_for_devil: { type: 'array', items: { type: 'string' } },
  },
  required: ['judge', 'primary_selection_label', 'avoid_label', 'regime_layer', 'event_sleeve', 'horizon_and_exit', 'ranking', 'confidence', 'caveats'],
}
const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['survives', 'survives_with_caveats', 'fails'] },
    reproduced_numbers: { type: 'string' },
    perturbation_results: { type: 'string' },
    deflated_sharpe: { type: 'string' },
    capacity_costs: { type: 'string' },
    boring_explanation_test: { type: 'string' },
    issues: { type: 'array', items: { type: 'string' } },
    final_recommendation: { type: 'string' },
    report_path: { type: 'string' },
  },
  required: ['verdict', 'reproduced_numbers', 'perturbation_results', 'issues', 'final_recommendation'],
}

const clip = (o, n) => { const s = JSON.stringify(o); return s.length > n ? s.slice(0, n) + '...[truncated]' : s }

phase('Refine')
const ROLES = ['R2_rel', 'R2_dual', 'R2_alpha', 'R2_regime', 'R2_event']
const refined = (await parallel(ROLES.map(id => () =>
  agent(COMMON(id), { label: id, phase: 'Refine', schema: REFINE_SCHEMA, agentType: 'general-purpose' })
))).filter(Boolean)
log(`${refined.length}/${ROLES.length} refiners returned`)

phase('Judge')
const dossier = refined.map(r => clip(r, 14000)).join('\n\n')
const JUDGE = (lens) => `You are an independent judge on an investment committee. Lens: ${lens}.
Read ${LAB}/TEAM_BRIEF.md and ${LAB}/ROUND2_BRIEF.md, then the round-2 refiners' REPORT.md/results.json files in ${LAB}/results/R2_*/ (and round-1 context in ${LAB}/results/_lead/round1_results.json). You may run small python checks with ${LAB}/lablib.py if a claim looks doubtful (n_jobs=2, runs < 9 min).
Structured summaries of the refiners follow:
${dossier}
Task: decide the final LABEL STACK for a 5-20 trading-day NSE swing trader who wants to know which stocks will go up and which to avoid (down), free of the known biases. Rank the candidates (score 0-100 with reasons), and specify: primary selection label (exact formula), avoid label, regime/exposure layer (or none), event sleeve (or none), horizon and exit rule, expected performance ranges (dev and holdout, after costs, vs random and Nifty 500), confidence, caveats, and open questions for the devil's advocate. Selection must rest on DEV evidence; treat 2026 as confirmation only. Penalize complexity and multiple-testing exposure.`
const judges = (await parallel([
  () => agent(JUDGE('PORTFOLIO MANAGER — real money after costs, drawdowns, capacity, turnover, simplicity, robustness across regimes'), { label: 'J_pm', phase: 'Judge', schema: STACK_SCHEMA, agentType: 'general-purpose' }),
  () => agent(JUDGE('STATISTICIAN — multiple testing, deflated Sharpe, overfitting, leakage, effective sample size, holdout honesty'), { label: 'J_stat', phase: 'Judge', schema: STACK_SCHEMA, agentType: 'general-purpose' }),
])).filter(Boolean)
log(`${judges.length}/2 judges returned`)

phase('Attack')
const devil = await agent(`You are the devil's advocate on the investment committee. Your job is to try to BREAK the recommended label stack.
Read ${LAB}/TEAM_BRIEF.md, ${LAB}/ROUND2_BRIEF.md (section "Devil's advocate"), ${LAB}/lablib.py (v2 section), and the round-2 results in ${LAB}/results/R2_*/.
Judges' recommendations:
${judges.map(j => clip(j, 9000)).join('\n\n')}
Refiner summaries (for reference):
${refined.map(r => clip(r, 5000)).join('\n\n')}
Do, with code (work in ${LAB}/results/R3_devil/, n_jobs=2, each run < 9 min, persist intermediates):
1. Independently re-derive the recommended primary label and its model from scratch (your own code, not the refiners' scripts), retrain with walk_forward2, and re-simulate with Sim.compare; confirm or refute the headline dev/holdout numbers.
2. Perturbations: two random 50% entity halves (hash of entity), 1-day extra signal lag, quarter-by-quarter excess, top_k and step changes; does the edge persist?
3. Deflated Sharpe / multiple-testing haircut using the total variants tried across rounds 1 and 2 (sum the variants_tried counts you can find; round 1 tried roughly 600).
4. Capacity/impact: per-name position sizes of Rs 5 lakh / 25 lakh / 1 crore vs 20d median turnover of the actual picks; add a square-root impact model and report net returns.
5. Boring-explanation test: build simple factor tilts from the same universe (low-vol, short-term reversal, small-size, momentum) and check whether one of them reproduces the edge.
Return a verdict (survives / survives_with_caveats / fails) with numbers.`, { label: 'R3_devil', phase: 'Attack', schema: VERDICT_SCHEMA, agentType: 'general-purpose' })

return { refined, judges, devil }
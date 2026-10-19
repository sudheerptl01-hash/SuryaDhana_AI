export const meta = {
  name: 'swing-label-round3',
  description: 'Round 3: production process, two-way monetisation, scenario atlas, risk policy; each verified adversarially; then final exam and forward protocol',
  phases: [
    { title: 'Build', detail: 'R3_book, R3_scen, R3_twoway, R3_risk (each followed by its own adversarial verifier)' },
    { title: 'Verify', detail: 'independent re-computation and look-ahead review of each builder' },
    { title: 'Exam', detail: 'R3_exam: adoption decisions, final exam, final process, forward protocol' },
  ],
}

const LAB = '/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab'

const COMMON = (role) => `You are ${role}, a member of a buy-side quant research team designing labels and an investment process for a 5-20 trading-day NSE swing trader. Lab directory: ${LAB}.
Before doing anything, read these files in order: ${LAB}/TEAM_BRIEF.md, ${LAB}/ROUND2_BRIEF.md, ${LAB}/PREREG_R3.md, ${LAB}/ROUND3_BRIEF.md. Your mandate is the section "## ${role}" of ROUND3_BRIEF.md; the "House rules for round 3" section is binding.
Use the shared helpers in ${LAB}/r3common.py (import r3common as C; C.set_agent("${role}")). Work only inside ${LAB}/results/${role}/ (scripts, logs, results.json, REPORT.md). Another agent runs at the same time on this 4-CPU / 15 GB machine: one heavy Python process at a time, keep each under ~4 GB, LightGBM n_jobs <= 2, run with python3 -u and set -o pipefail.
Work like a skeptical senior quant: after every result, look at the event rates and the pros/cons again, and look for the boring explanation (a factor tilt, a cost artefact, a baseline mismatch, phase luck) before you claim anything. Selection on DEV only; 2026 is reported, never used to choose. Never invent or round-trip a number you did not compute; every number in your answer must exist in your results.json. Include the html_tables and charts sections described in the house rules, written for a non-quant client (clear titles and notes).
Aim to finish within about 75 minutes of work. Your final answer is the structured summary required by the schema, filled from your results.json.`

const ROLES = [
  { role: 'R3_book', extra: 'Save item 1 (reproduction of PROD vs single model vs 3-seed ensemble, phase-averaged, DEV and 2026, 50 and 80 bps, vs random and vs EW) to results.json as soon as it is done; the lead depends on it. For the exits and capacity, start from the devil\'s per-trade-cost Sim copy in results/R3_devil/s7_capacity.py and validate your copy bit-exact against L.Sim on the baseline before using it.' },
  { role: 'R3_scen', extra: 'Many base numbers exist in results/_lead/atlas_v2.json and the round-2 label files: reuse them only where the definitions match exactly, otherwise recompute. The audience is a non-quant client who asked: are the existing labels right, what happens with and without conditions/filters, what are the event rates, and how does each scenario change them. Make every table self-explanatory.' },
  { role: 'R3_twoway', extra: 'The client said "down is also fine and up is also fine": quantify honestly whether the -1 side can be monetised (avoid veto, index-futures hedge, F&O long/short, short-only), with realistic Indian-market costs, margin and carry exactly as specified in your mandate; document any deviation in REPORT.md before running it.' },
  { role: 'R3_risk', extra: 'PROD scores exist for 2023-2026 only (walk-forward); for PRE 2021-09..2022-12 use the EW-universe book and say so. Kill-rule calibration must use dependence-preserving resampling (block bootstrap or persistence-matched nulls), not iid draws.' },
]

const BUILD_SCHEMA = {
  type: 'object',
  properties: {
    agent: { type: 'string' },
    headline: { type: 'string', description: '2-4 plain-English sentences with the key numbers' },
    recommendation: { type: 'string' },
    key_numbers: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, dev: { type: 'string' }, holdout_2026: { type: 'string' }, note: { type: 'string' } }, required: ['name'] } },
    findings: { type: 'array', items: { type: 'object', properties: { claim: { type: 'string' }, evidence: { type: 'string' }, confidence: { type: 'string' } }, required: ['claim', 'evidence'] } },
    adopted_addons: { type: 'array', items: { type: 'string' } },
    rejected_addons: { type: 'array', items: { type: 'string' } },
    pros: { type: 'array', items: { type: 'string' } },
    cons: { type: 'array', items: { type: 'string' } },
    caveats: { type: 'array', items: { type: 'string' } },
    variants_tested: { type: 'integer' },
    results_json: { type: 'string' },
    report_md: { type: 'string' },
    html_table_ids: { type: 'array', items: { type: 'string' } },
    chart_ids: { type: 'array', items: { type: 'string' } },
  },
  required: ['agent', 'headline', 'recommendation', 'key_numbers', 'findings', 'variants_tested', 'results_json', 'report_md'],
}

const VERIFY_SCHEMA = {
  type: 'object',
  properties: {
    agent_checked: { type: 'string' },
    verdict: { type: 'string', enum: ['confirmed', 'confirmed_with_corrections', 'unreliable'] },
    checks: { type: 'array', items: { type: 'object', properties: { item: { type: 'string' }, theirs: { type: 'string' }, mine: { type: 'string' }, reproduced: { type: 'boolean' }, note: { type: 'string' } }, required: ['item', 'reproduced'] } },
    lookahead_or_bugs: { type: 'array', items: { type: 'string' } },
    corrections: { type: 'array', items: { type: 'string' } },
    report_md: { type: 'string' },
  },
  required: ['agent_checked', 'verdict', 'checks', 'lookahead_or_bugs', 'corrections'],
}

const EXAM_SCHEMA = {
  type: 'object',
  properties: {
    verdict: { type: 'string' },
    adoption_decisions: { type: 'array', items: { type: 'object', properties: { addon: { type: 'string' }, decision: { type: 'string' }, evidence: { type: 'string' } }, required: ['addon', 'decision', 'evidence'] } },
    final_exam: { type: 'string' },
    final_process: { type: 'string' },
    expected_performance: { type: 'string' },
    forward_protocol: { type: 'string' },
    spot_checks: { type: 'array', items: { type: 'string' } },
    caveats: { type: 'array', items: { type: 'string' } },
    report_md: { type: 'string' },
  },
  required: ['verdict', 'adoption_decisions', 'final_exam', 'final_process', 'expected_performance', 'forward_protocol', 'report_md'],
}

const verifyPrompt = (role, summary) => `You are an adversarial verifier (R3_verify_${role}) for the round-3 work of ${role} in a quant research lab at ${LAB}. Read ${LAB}/ROUND3_BRIEF.md (section "## ${role}" and the house rules) and ${LAB}/PREREG_R3.md, then ${role}'s REPORT.md, results.json and scripts in ${LAB}/results/${role}/.
${role}'s structured summary:
${JSON.stringify(summary, null, 1)}
Your job, defaulting to skepticism:
1. Independently re-compute at least 3 of their headline numbers with your own code (you may use r3common.py and lablib; do NOT import or copy their scripts). Report theirs vs yours; a relative gap > 10% (or a sign flip) is a discrepancy you must explain.
2. Review their code for look-ahead and errors: decisions at signal date t must use data <= t and fill at open t+1 or later (early exits, hedge betas, ADV/impact inputs, gates, regime flags); costs and carry exactly as specified; correct mask_tag for cached random/EW baselines (a reused tag with a different mask reads the wrong baseline); phase averaging over all 5 phases; DEV-only selection; html_tables numbers consistent with results.json.
3. If you find an error, compute the corrected number yourself and report it under corrections.
Work only in ${LAB}/results/R3_verify_${role}/ (write a short REPORT.md there). Machine limits: one heavy Python process at a time, under ~4 GB, python3 -u, set -o pipefail. Aim for about 30 minutes. Your final answer is the structured verdict.`

phase('Build')
const results = await pipeline(
  ROLES,
  (r) => agent(`${COMMON(r.role)}\n\nRole-specific notes: ${r.extra}`, { label: r.role, phase: 'Build', schema: BUILD_SCHEMA }),
  (summary, r) => summary
    ? agent(verifyPrompt(r.role, summary), { label: `verify:${r.role}`, phase: 'Verify', schema: VERIFY_SCHEMA }).then((v) => ({ role: r.role, summary, verify: v }))
    : { role: r.role, summary: null, verify: null },
)
const done = results.filter(Boolean)
log(`builders done: ${done.map((d) => `${d.role}=${d.summary ? 'ok' : 'FAILED'}/${d.verify ? d.verify.verdict : 'no-verify'}`).join(', ')}`)

phase('Exam')
const exam = await agent(`${COMMON('R3_exam')}

Item 1 of your mandate (independent re-computation) was done per builder by dedicated verifiers; their verdicts are below. Spot-check anything a verifier flagged or could not reproduce, use corrected numbers wherever a verifier issued a correction, and then do items 2-4: apply the PREREG adoption rule to every add-on, produce the final exam table (frozen process on 2026, single model vs PROD, phase-averaged, with random and EW baselines, plus a precision-weighted forward estimate), write the final investment process for the client (label, score, universe, book, entries/exits, avoid veto, how the -1 side is used, exposure and hedge policy, capacity limits, monitoring and kill rules), the expected performance in plain numbers, and the forward protocol for data after 2026-10-14. Work in ${LAB}/results/R3_exam/.

Builder summaries and verifier verdicts:
${JSON.stringify(done, null, 1)}`, { label: 'R3_exam', phase: 'Exam', schema: EXAM_SCHEMA })

return { builders: done, exam }

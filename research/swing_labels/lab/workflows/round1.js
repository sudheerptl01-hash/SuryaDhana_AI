export const meta = {
  name: 'swing-label-round1',
  description: 'Round 1: auditor + four quant specialists design and measure 5-20 day swing labels on 5.75y of real NSE data',
  phases: [{ title: 'Specialists', detail: 'auditor, barrier, relative/rank, trend-scan/quality, setups/meta-label' }],
}

const LAB = '/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab'

const COMMON = (id) => `You are a senior member of a quant research team at a systematic investment firm, working on NSE (India) cash equities.
FIRST read ${LAB}/TEAM_BRIEF.md completely, then ${LAB}/lablib.py, ${LAB}/ca.py, ${LAB}/build_meta.json, ${LAB}/features_meta.json and ${LAB}/sanity.json.
Then read your role in ${LAB}/round1_roles.md (section "${id}") — that is your assignment.
Follow every convention in the brief: next-open entry, NaN (never 0) where a label is undefined, filters never change label values, walk-forward only (L.walk_forward), 50 bps central and 80 bps stress costs, random-pick baseline, selection on 2023-2025 with 2026 as untouched holdout, n_jobs=2, date_step=2, <=6 full walk-forward runs.
Work in ${LAB}/results/${id}/ (create it). Keep results.json there updated as you go, and finish by writing a thorough REPORT.md there with markdown tables of real measured numbers (event-rate tables, by-year/regime tables, learnability and investability tables, pros/cons). Later judges will read REPORT.md, so make it self-contained.
Save every script in your results dir and run it with python3 via the Bash tool using a long timeout (timeout up to 600000 ms). Keep each script run under ~9 minutes: split work into stages that persist intermediate arrays/results to disk (npz/parquet/json) so later stages reload instead of recomputing. Loading P and F takes ~30-60s, so batch several variants per script run. If something is slow, subsample dates (e.g. every 2nd date) for screening and say so.
Be quantitative and honest — a label that leaks or only works in one year is a failure; say so. Your final structured output summarizes your candidates with real measured numbers.`

const CAND = {
  type: 'object',
  properties: {
    candidate_id: { type: 'string' },
    family: { type: 'string' },
    definition: { type: 'string' },
    horizon: { type: 'string' },
    sides: { type: 'string' },
    n_samples: { type: ['number', 'null'] },
    class_shares: { type: 'string' },
    monthly_pos_std: { type: ['number', 'null'] },
    regime_corr: { type: ['number', 'null'] },
    by_year_note: { type: 'string' },
    auc_or_ic: { type: ['number', 'null'] },
    top_decile_vs_base: { type: 'string' },
    cagr_50bps: { type: ['number', 'null'] },
    sharpe_50bps: { type: ['number', 'null'] },
    maxdd_50bps: { type: ['number', 'null'] },
    cagr_80bps: { type: ['number', 'null'] },
    random_baseline_cagr: { type: ['number', 'null'] },
    holdout_2026_note: { type: 'string' },
    pros: { type: 'array', items: { type: 'string' } },
    cons: { type: 'array', items: { type: 'string' } },
    verdict: { type: 'string', enum: ['strong', 'promising', 'weak', 'reject'] },
  },
  required: ['candidate_id', 'family', 'definition', 'horizon', 'sides', 'class_shares', 'pros', 'cons', 'verdict'],
}

const SCHEMA = {
  type: 'object',
  properties: {
    agent_id: { type: 'string' },
    headline: { type: 'string' },
    candidates: { type: 'array', items: CAND },
    key_findings: { type: 'array', items: { type: 'string' } },
    lab_issues_found: { type: 'array', items: { type: 'string' } },
    variants_tried: { type: ['number', 'null'] },
    report_path: { type: 'string' },
  },
  required: ['agent_id', 'headline', 'candidates', 'key_findings', 'report_path'],
}

const ROLES = ['E_auditor', 'A_barrier', 'B_relative', 'C_trendscan', 'D_setups']

phase('Specialists')
log(`Launching ${ROLES.length} specialists (2 run concurrently on this 4-CPU box)`)
const results = await parallel(ROLES.map(id => () =>
  agent(COMMON(id), { label: id, phase: 'Specialists', schema: SCHEMA, agentType: 'general-purpose' })
))
const ok = results.filter(Boolean)
log(`${ok.length}/${ROLES.length} specialists returned`)
return { results: ok, missing: ROLES.filter((id, i) => !results[i]) }
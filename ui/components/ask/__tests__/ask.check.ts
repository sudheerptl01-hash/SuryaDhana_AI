/**
 * R2-ASK node check (FINAL ROUND; RATING §7 R9-R1): the ASK pure model — the renderer-side citation guardrail
 * (G7: an uncited numeric line never renders), cell/text safety (G4: rows are painted as text) — plus static
 * scans of the ask sources: badge `heuristic` with the exact disclosure, "describes, does not predict", zero
 * direction words in UI copy, no HTML sink (dangerouslySetInnerHTML / innerHTML / eval), the panel's only
 * endpoints are /api/ask*, and the RSCH mount is present.
 *
 * Run with plain node ≥ 23.6 (type stripping, no deps):
 *   node ui/components/ask/__tests__/ask.check.ts
 * Also type-checked by `cd ui && npx tsc --noEmit`. Exits non-zero on any failing check.
 */
import * as fs from 'node:fs'
import * as path from 'node:path'

type ModelMod = typeof import('../model')
const M = (await import(new URL('../model.ts', import.meta.url).href)) as ModelMod

const DIR = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..')
const read = (rel: string): string => fs.readFileSync(path.join(DIR, rel), 'utf8')

let failed = 0
let passed = 0
function check(name: string, cond: unknown, extra?: unknown): void {
  if (cond) { passed++; return }
  failed++
  console.error(`FAIL ${name}${extra !== undefined ? ` :: ${JSON.stringify(extra)}` : ''}`)
}

const SOURCES = [{ table: 'index_ohlc_daily', as_of: '2026-11-12' }]

// ── G7, renderer side: uncited numeric lines never render ───────────────────────────────────────────────────

{
  const { lines, withheldHere } = M.renderableLines([
    { text: 'NIFTY closed at 26050.4 [index_ohlc_daily · as-of 2026-11-12].', cited: true },
    { text: 'It moved 120 points since the prior session.', cited: true },        // numeric, uncited -> withheld
    { text: 'One row per symbol per session.', cited: false },                    // no number -> fine
  ], SOURCES)
  check('cited numeric line renders', lines[0].text.includes('26050.4') && lines[0].cited)
  check('uncited numeric line is withheld with the standing text', lines[1].text === M.WITHHELD_TEXT && withheldHere === 1)
  check('numberless prose renders uncited', lines[2].text.includes('One row') && !lines[2].cited)
}
{
  const { lines, withheldHere } = M.renderableLines(
    [{ text: '26050.4 came from nowhere [made_up_table · as-of 2026-11-12].', cited: true }], SOURCES)
  check('a citation must name a table in the payload sources', lines[0].text === M.WITHHELD_TEXT && withheldHere === 1)
}
{
  const { lines } = M.renderableLines([{ text: M.WITHHELD_TEXT, cited: false }], SOURCES)
  check('a server-withheld line stays withheld, not double-counted', lines[0].text === M.WITHHELD_TEXT)
}
check('empty lines are dropped', M.renderableLines([{ text: '  ', cited: false }], SOURCES).lines.length === 0)

// ── helpers ─────────────────────────────────────────────────────────────────────────────────────────────────

check('sourceLabel carries table + as-of', M.sourceLabel({ table: 'notes', as_of: '2026-11-12' }) === 'notes · as-of 2026-11-12')
check('sourceLabel says undated when there is no date', M.sourceLabel({ table: 'notes', as_of: null }) === 'notes · undated')
check('cellText never returns markup, nulls become the em dash',
  M.cellText(null) === '—' && M.cellText(26050.4) === '26050.4' && M.cellText('<b>x</b>') === '<b>x</b>')
check('statusParts: provider · model, snapshot day, degraded reason',
  (() => { const p = M.statusParts({ provider: 'ollama', model: 'llama3.1:8b', snapshot: { file: 'f', as_of: '2026-11-12' }, degraded: true, degraded_reason: 'analyst offline — the data reads still work' })
           return p[0] === 'ollama · llama3.1:8b' && p[1] === 'snapshot 2026-11-12' && p[2].includes('analyst offline') })())
check('statusParts without a snapshot says so', M.statusParts({ provider: 'ollama', model: 'm', snapshot: null, degraded: false, degraded_reason: null })[1] === 'no snapshot yet')

// ── static scans of the ask sources (labelling rules, PLAN §1) ──────────────────────────────────────────────

const panel = read('AskPanel.tsx')
const api = read('api.ts')
const model = read('model.ts')
const rsch = fs.readFileSync(path.resolve(DIR, '..', 'ResearchLibrary.tsx'), 'utf8')

check('badge is heuristic with the exact LLM disclosure',
  panel.includes('badge="heuristic"') && panel.includes('an LLM wrote this from the cited rows — verify before acting on it'))
check('the mandatory honesty line is on the panel', panel.includes('describes, does not predict'))
check('the feeds-nothing line is on the panel', panel.includes('not the Decision Desk, not the S1 shadow'))
check('the audit note names what is stored and what never is', panel.includes('never the row payloads'))

// G4 renderer half: no HTML sink anywhere in the ask sources — row content and answers paint as text
for (const [name, src] of [['AskPanel.tsx', panel], ['api.ts', api], ['model.ts', model]] as const) {
  check(`${name} has no HTML sink`, !/dangerouslySetInnerHTML|innerHTML|document\.write|\beval\s*\(|new Function/.test(src))
}

// zero direction words in the ask UI copy (comments stripped; identifiers/URLs are not copy)
const copyOnly = panel.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
for (const word of ['bullish', 'bearish', 'buy', 'sell', 'rally', 'crash', 'breakout', 'upside', 'downside', 'oversold', 'overbought']) {
  check(`no direction word '${word}' in panel copy`, !new RegExp(`\\b${word}\\b`, 'i').test(copyOnly))
}

// the panel's only endpoints are /api/ask* (R3-ASK adds the 4th: /api/ask/audit for the empty state)
const endpoints = [...new Set([...api.matchAll(/['"`](\/api\/[^'"`]*)['"`]/g)].map(m => m[1]))]
check('api.ts calls /api/ask endpoints only', endpoints.length === 4 && endpoints.every(e => e.startsWith('/api/ask')), endpoints)
check('the panel itself holds no endpoint strings', !/\/api\//.test(panel.replace(/^\s*\*.*$/gm, '')))
check('no publisher or data-service URL in the ask UI', !/https?:\/\//.test(panel + model) )

// the RSCH mount (this builder owns these lines)
check('RSCH mounts AskPanel as the ask sub-view',
  rsch.includes("useSubView(['library', 'ask']") && rsch.includes('<AskPanel />') && rsch.includes("from '@/components/ask/AskPanel'"))
check('RSCH names the sub-view in its tabs', rsch.includes('ASK · the cited read-only analyst'))

// ── R3-ASK: the empty state (F2-design ask) ─────────────────────────────────────────────────────────────────

check('3-4 describe-only example questions exist', M.EXAMPLE_QUESTIONS.length >= 3 && M.EXAMPLE_QUESTIONS.length <= 4)
// each example must be describe-only: anchored on stored data, and free of every forecast/advice shape the
// server refuses (a refused example would teach the user the panel is broken)
const FORECASTISH = /\bwill\s|\btomorrow\b|\bnext\s+(week|month|session|expiry)\b|\bshould\s+(i|we|one)\b|\bpredict|\bforecast|\btarget\b|\brecommend|\bbest\b|\bcheap\b|\bexpensive\b|\bworth\b|\bgood\s+(entry|exit)|\bstop[-\s]?loss\b/i
for (const ex of M.EXAMPLE_QUESTIONS) {
  check(`example is describe-only: ${ex}`, /stored/i.test(ex) && !FORECASTISH.test(ex), ex)
}
check('the panel renders the examples and fills the box on click',
  panel.includes('EXAMPLE_QUESTIONS.map') && panel.includes('onPick={setQ}') && panel.includes('onPick(value)'))
check('the empty state shows only pre-query', panel.includes('{!res && !busy && <EmptyState'))
check('recent questions come from the audit tail and show no payloads',
  panel.includes('askAudit(') && panel.includes('never the row payloads') && !/r\.(rows|columns|answer)\b/.test(panel))
check('auditLineLabel is question · rows · time only — IST-labelled (R4-ASK, F3-design nit)',
  M.auditLineLabel({ ts: '2026-11-13T22:10:05+00:00', question: 'q', rows_returned: 3 }) === 'q · 3 row(s) · 2026-11-14 03:40 IST')
check('direct reads are filtered out of the recent list', panel.includes("r.question !== '(direct read)'"))

// ── R4-ASK: IST audit times + refused rows never become suggestions + the health placeholder ────────────────

check('auditTimeIST converts the server UTC ts (+5:30) and labels it',
  M.auditTimeIST('2026-11-13T19:01:00+00:00') === '2026-11-14 00:31 IST')     // the F3-design probe case: 00:31 IST
check('auditTimeIST treats a zoneless ts as UTC', M.auditTimeIST('2026-11-13T19:01:00') === '2026-11-14 00:31 IST')
check('auditTimeIST handles an explicit Z suffix', M.auditTimeIST('2026-11-13T18:46:05Z') === '2026-11-14 00:16 IST')
check('auditTimeIST falls back unlabelled on garbage', M.auditTimeIST('not-a-time') === 'not-a-time' && M.auditTimeIST('') === '')
check('refused audit rows are filtered out of the recent suggestions', panel.includes('!r.refused'))
check('the audit row type carries refused', api.includes('refused?: boolean'))
check('a placeholder line holds the status strip while the health fetch is in flight',
  panel.includes('checking the analyst + snapshot age…'))
check('the ask POST waits past the server LLM budget (2 × ASK_LLM_TIMEOUT_S + query)',
  (() => { const m = api.match(/ASK_CLIENT_TIMEOUT_MS = (\d+)_?(\d*)/); if (!m) return false
           const v = Number(`${m[1]}${m[2]}`); return v >= 310_000 })())

// ── R3-ASK: the snapshot-age tone (F2-design: louder when degraded) ─────────────────────────────────────────

const SNAP = { file: 'evening-20261113-1920.duckdb', as_of: '2026-11-13' }
const FRESH = { iv_summary_max: '2026-11-13', stale: false, note: null }
const STALE = { iv_summary_max: '2026-11-12', stale: true, note: 'cut before the 2026-11-13 iv_eod — iv_summary_daily inside it ends 2026-11-12' }
check('fresh snapshot: ok tone, plain date line',
  (() => { const a = M.snapshotAgeLine(SNAP, FRESH, true); return a.tone === 'ok' && a.text === 'snapshot 2026-11-13' })())
check('snapshot predating the newest iv_summary_daily session: amber',
  (() => { const a = M.snapshotAgeLine(SNAP, STALE, true); return a.tone === 'amber' && a.text.includes('iv_summary_daily inside it ends 2026-11-12') })())
check('the same staleness with the analyst offline: loud',
  M.snapshotAgeLine(SNAP, STALE, false).tone === 'loud')
check('no snapshot at all is amber, never silent',
  (() => { const a = M.snapshotAgeLine(null, null, true); return a.tone === 'amber' && a.text === 'no snapshot yet' })())
check('missing age block degrades to the plain ok line', M.snapshotAgeLine(SNAP, null, true).tone === 'ok')
check('the panel paints amber inline and loud as a bordered strip',
  panel.includes("age.tone === 'amber'") && panel.includes("age?.tone === 'loud'") && panel.includes('borderLeft: `3px solid ${T.amber}`'))

// ── R3-ASK: analyst_ready states (F2-trader ask) ────────────────────────────────────────────────────────────

check('the health type carries analyst_ready + analyst_note + snapshot_age',
  api.includes('analyst_ready: boolean') && api.includes('analyst_note: string | null') && api.includes('snapshot_age: SnapshotAge | null'))
check('the offline line matches the server constant', M.OFFLINE_LINE === 'analyst offline — the data reads still work')
check('the panel shows the offline line when the analyst is not ready',
  panel.includes('!health.analyst_ready') && panel.includes('health.analyst_note ?? OFFLINE_LINE'))

console.log(`ask.check: ${passed} passed, ${failed} failed`)
if (failed > 0) process.exit(1)

/**
 * E-PLAN node check (FINAL ROUND wave E; F-11): the GPLN pure model — tile → SourceChip mapping, formatters,
 * the one-number-once-per-page EXPIRY dedupe, the watchlist line — plus static scans of the gameplan sources
 * (no direction words in copy, every tile title a fact, the mandatory "describes, does not predict" line,
 * no `signal` badge, no data-service or publisher URL in the UI: the one read is /api/gameplan).
 *
 * Run with plain node ≥ 23.6 (type stripping, no deps):
 *   node ui/components/gameplan/__tests__/gameplan.check.ts
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

// ── tile → SourceChip plan (the kit's sourceOf renders a live plan; its own tests cover EOD/STALE) ───────────

check('dead tile → dead plan with the calm error as hint',
  (() => { const p = M.tileChipPlan({ ok: false, badge: 'context', source: 'x', error: 'the data service did not answer' })
           return p.dead && p.hint === 'the data service did not answer' && p.source === 'x' })())
check('missing tile → dead plan', M.tileChipPlan(undefined).dead && M.tileChipPlan(undefined).hint === 'tile missing from the payload')
check('live tile → its own as-of and source, no invented hint',
  (() => { const p = M.tileChipPlan({ ok: true, badge: 'arithmetic', source: 'index_ohlc_daily', as_of: '2026-11-12' })
           return !p.dead && p.asOf === '2026-11-12' && p.source === 'index_ohlc_daily' && p.hint === null })())
check('live tile with no as-of keeps null (the kit renders OFFLINE, never an invented date)',
  (() => { const p = M.tileChipPlan({ ok: true, badge: 'context' }); return !p.dead && p.asOf === null })())

// ── formatters ───────────────────────────────────────────────────────────────────────────────────────────────

check('num groups Indian style', M.num(26050) === '26,050' && M.num(null) === '—')
check('pct signs both ways', M.pct(0.21) === '+0.21%' && M.pct(-1.5) === '-1.50%' && M.pct(undefined) === '—')
check('pts prints signed points', M.pts(0.3) === '+0.3' && M.pts(-0.25, 2) === '-0.25' && M.pts(null) === '—')
check('day renders DD Mon', M.day('2026-11-18') === '18 Nov' && M.day('2026-11-18T15:30:00+05:30') === '18 Nov' && M.day('nope') === '')

// ── one number once per page: the EXPIRY dedupe ──────────────────────────────────────────────────────────────

const eco = [
  { date: '2026-11-18', kind: 'EXPIRY', what: 'NIFTY weekly F&O expiry', time: '15:30' },
  { date: '2026-11-18', kind: 'CPI', what: 'CPI inflation', time: '16:00' },
  { date: '2026-11-19', kind: 'EXPIRY', what: 'next weekly expiry' },
]
check('an EXPIRY row on the chain tile’s expiry date is dropped; everything else stays',
  (() => { const out = M.dedupeEcoRows(eco, '2026-11-18')
           return out.length === 2 && out[0].kind === 'CPI' && out[1].kind === 'EXPIRY' })())
check('no chain expiry → nothing dropped', M.dedupeEcoRows(eco, null).length === 3)

// ── the watchlist line ───────────────────────────────────────────────────────────────────────────────────────

check('watchlist line caps at 8 + tail',
  M.watchlistLine(['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J']) === 'A, B, C, D, E, F, G, H +2')
check('empty watchlist names the fix, not a ranking', M.watchlistLine([]) === 'empty — add names on WTCH')

// ── static scans of the page sources (labelling rules, PLAN §1) ──────────────────────────────────────────────

const SOURCES = ['GamePlan.tsx', 'model.ts', 'api.ts'].map(f => [f, read(f)] as const)
const DIRECTION = /\b(buy|sell|bullish|bearish|should|opportunity|setups?|bias|breakout|go long|go short|right side|wrong side)\b/i
for (const [f, src] of SOURCES) {
  // strings + comments both count: the checker greps the diff the same way
  check(`no direction words in ${f}`, !DIRECTION.test(src), src.match(DIRECTION)?.[0])
  check(`no 'signal' badge in ${f}`, !/['"]signal['"]/.test(src))
}
const page = read('GamePlan.tsx')
check('the mandatory line is the model’s PAGE_NOTE and the page renders it',
  M.PAGE_NOTE.endsWith('describes, does not predict') && /\{PAGE_NOTE\}/.test(page))
check('the page states what it never feeds', /S1 shadow/.test(page) && /ticket/.test(page))
check('the UI reads only /api/gameplan (no data-service, no publisher)',
  !/8001|\/db\/|yahoo|nseindia/i.test(read('api.ts')))
check('every tile title is in the model (one source of copy)',
  ['overnight', 'levels', 'oi', 'iv', 'events', 'focus'].every(k => (M.TILE_TITLES as Record<string, string>)[k]))
check('badges come from the payload, not hardcoded tones',
  !/bullish|bearish/.test(read('model.ts')))

console.log(`gameplan.check: ${passed} passed, ${failed} failed`)
if (failed) process.exit(1)

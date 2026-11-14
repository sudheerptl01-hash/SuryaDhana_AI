/**
 * Commodity lane checks (final round R5-EVTS): EVTS carries MCX trade holidays + special sessions
 * (shared/mcx_specs) and the gold program's stored US releases (gold_events) as ONE lane with source chips,
 * and each event is drawn once on the page: the five-week grid's ◆ eco line skips the eco-calendar ids the
 * lane covers (US data days, FOMC, exchange special sessions).
 *
 * Run with plain node 25 (type stripping, no deps):
 *   node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON ui/components/__tests__/commodity_lane.check.ts
 * Also type-checked by `cd ui && npx tsc --noEmit`. Exits non-zero on any failing check.
 */
import * as fs from 'node:fs'
import * as path from 'node:path'

const UI = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..')
const src = (rel: string) => fs.readFileSync(path.join(UI, rel), 'utf8')

let failed = 0
let passed = 0
function check(name: string, cond: unknown): void {
  if (cond) { passed++; return }
  failed++
  console.error(`FAIL ${name}`)
}

const evts = src('components/EventCalendar.tsx')
const api = src('lib/api.ts')

// ── the lane exists, is badged context, and chips its sources ────────────────────────────────────────────────
check('EVTS has the commodity lane panel', /title="Commodity calendar"/.test(evts))
check('the lane is badged context', /badge="context"\s*\n?\s*title="Commodity calendar"/.test(evts))
check('the lane fetches the commodity calendar', /getCommodityCalendar\(7, 40\)/.test(evts))
check('rows carry a per-row source chip', /cmdtySourceChip\(r\.source\)/.test(evts) && /MCX CIRCULAR/.test(evts) && /GOLD_EVENTS · STORED/.test(evts))
check('MCX kinds have their own chips', /MCX_HOLIDAY: \{/.test(evts) && /MCX_SESSION: \{/.test(evts))

// ── no duplication: the ◆ grid line skips what the lane carries ──────────────────────────────────────────────
check('the grid ◆ line skips covered eco ids', /if \(e\.id && coveredEcoIds\.has\(e\.id\)\) continue/.test(evts))
check('covered ids come from the lane payload', /cmdty\?\.covers_eco_ids/.test(evts))
// negative control: the pre-fix ecoByDay (every eco row mapped unconditionally, single line) is gone
check('negative control: the unconditional ecoByDay map is gone', !/for \(const e of eco\) m\.set\(e\.date/.test(evts))

// ── labelling rules: context, no direction words on the new surface ──────────────────────────────────────────
check('no direction words in EVTS', !/bullish|bearish/i.test(evts))
check('the lane subtitle says what it is and the window', /MCX trade holidays & special sessions/.test(evts))

// ── the client exists and is typed ───────────────────────────────────────────────────────────────────────────
check('api client hits the new endpoint', /'\/api\/market\/commodity-calendar'/.test(api))
check('CommodityEvent carries covers_eco_id and source', /covers_eco_id: string \| null/.test(api) && /interface CommodityEvent/.test(api))
check('EcoEvent now carries the row id the server already sends', /interface EcoEvent \{ id\?: string \| null;/.test(api))

console.log(`commodity_lane.check: ${passed} passed, ${failed} failed`)
if (failed) process.exit(1)

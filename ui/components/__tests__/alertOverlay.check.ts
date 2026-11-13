/**
 * E-DIFF node check (FINAL ROUND T-22 + F-19b): the alert overlay's pure halves (lib/alertOverlay.ts) — rule →
 * chart-line mapping, the "alert at this level" draft, line hit-testing — and the BRF "since your last look"
 * diff; plus static source scans of the wiring (InteractiveSeries priceLines + the two kit fixes, Brief's
 * neutral A/D (L-15) + what-changed strip, ALRT's merged legacy rows and chart-line focus). Every user-facing
 * string this builder added is scanned with the engine's own direction-word vocabulary.
 *
 * Run with plain node ≥ 23.6 (type stripping, no deps):
 *   node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON ui/components/__tests__/alertOverlay.check.ts
 * Also type-checked by `cd ui && npx tsc --noEmit`. Exits non-zero on any failing check.
 */
import * as fs from 'node:fs'
import * as path from 'node:path'

type OverlayMod = typeof import('../../lib/alertOverlay')
type EngineMod = typeof import('../../lib/alertsEngine')
const A = (await import(new URL('../../lib/alertOverlay.ts', import.meta.url).href)) as OverlayMod
const E = (await import(new URL('../../lib/alertsEngine.ts', import.meta.url).href)) as EngineMod

const UI = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..')
const src = (rel: string): string => fs.readFileSync(path.join(UI, rel), 'utf8')

let failed = 0
let passed = 0
function check(name: string, cond: unknown, extra?: unknown): void {
  if (cond) { passed++; return }
  failed++
  console.error(`FAIL ${name}${extra !== undefined ? ` :: ${JSON.stringify(extra)}` : ''}`)
}

// ── the op words are the engine's own (direction-free) vocabulary ───────────────────────────────────────────
check('LEVEL_OP_WORD is in parity with alertsEngine OP_LABEL', A.LEVEL_OPS.every(op => A.LEVEL_OP_WORD[op] === E.OP_LABEL[op]), A.LEVEL_OP_WORD)
check('line titles and the menu copy carry no direction words', [
  ...Object.values(A.LEVEL_OP_WORD).map(w => `ALERT · ${w}`),
  'ALERT · at or over · one-shot',
  'opens the rule builder pre-filled — a level, not a recommendation',
].every(t => E.directionWords(t).length === 0))

// ── rule → chart line (alertLinesFor) ───────────────────────────────────────────────────────────────────────
const rule = (o: Partial<OverlayRule>): OverlayRule =>
  ({ id: 'r-1', series: 'price:NIFTY', op: 'above', value: 25000, status: 'active', origin: 'rule', ...o })
type OverlayRule = { id: string; series: string; op: string; value?: number | null; status: string; origin?: string }

{
  const rules: OverlayRule[] = [
    rule({ id: 'a', value: 26000 }),
    rule({ id: 'b', op: 'cross_down', value: 25000, status: 'snoozed' }),
    rule({ id: 'legacy', value: 25500, origin: 'price' }),
    rule({ id: 'paused', value: 24000, status: 'paused' }),               // out: paused
    rule({ id: 'fired', value: 24100, status: 'fired' }),                 // out: fired (one-shot done)
    rule({ id: 'move', op: 'change_pct', value: 3 }),                     // out: not a level op
    rule({ id: 'tcs', series: 'price:TCS', value: 3200 }),                // out: another symbol
    rule({ id: 'iv', series: 'iv30:NIFTY', value: 18 }),                  // out: another kind
    rule({ id: 'nul', value: null }),                                     // out: no level
    rule({ id: 'neg', value: -5 }),                                       // out: price must be > 0
  ]
  const lines = A.alertLinesFor(rules, 'NIFTY', 'price')
  check('level ops on the symbol+kind only, active/snoozed only, ascending',
    lines.map(l => l.id).join(',') === 'b,legacy,a', lines.map(l => `${l.id}@${l.price}`))
  check('a legacy (origin price) row is flagged and labelled one-shot', lines[1].legacy && lines[1].title.includes('one-shot') && !lines[0].legacy)
  check('the title is the rule’s own op word', lines[0].title === 'ALERT · crosses from over' && lines[2].title === 'ALERT · at or over'
    && lines[1].title === 'ALERT · at or over · one-shot')
  check('.NS and case are normalised', A.alertLinesFor(rules, 'nifty.NS', 'price').length === 3)
  const iv = A.alertLinesFor(rules, 'NIFTY', 'iv30')
  check('the iv30 kind matches iv30 rules only (negative value fine for other kinds, >0 enforced for price only)',
    iv.length === 1 && iv[0].id === 'iv')
}

// ── "alert at this level" (draftAtLevel) ────────────────────────────────────────────────────────────────────
{
  const up = A.draftAtLevel('price', 'NIFTY', 25901.237, 25713)
  check('a level over the last value crosses from under', up?.op === 'cross_up' && up.series === 'price:NIFTY' && up.repeat === 'once', up)
  check('price snaps to the NSE 0.05 tick', up?.value === 25901.25, up?.value)
  const dn = A.draftAtLevel('price', 'tcs.NS', 3100, 3212.4)
  check('a level under the last value crosses from over; symbol normalised', dn?.op === 'cross_down' && dn.series === 'price:TCS')
  const noref = A.draftAtLevel('price', 'NIFTY', 25000, null)
  check('no reference value → at or over (a level statement, not a direction)', noref?.op === 'above')
  const iv = A.draftAtLevel('iv30', 'NIFTY', 18.2345, 14.1)
  check('iv30 rounds to 0.1 vol pt', iv?.value === 18.2 && iv.series === 'iv30:NIFTY')
  check('an unusable level draws no draft', A.draftAtLevel('price', 'NIFTY', NaN) === null && A.draftAtLevel('price', 'NIFTY', -4) === null && A.draftAtLevel('price', '', 100) === null)
  check('a draft never carries a note (nothing to scan, nothing to refuse)', up != null && !('note' in up && up.note))
}

// ── line hit-testing (nearestLevel) ─────────────────────────────────────────────────────────────────────────
{
  const coords = new Map([[100, 40], [200, 80], [300, null as number | null]])
  const of = (p: number) => coords.get(p)
  check('closest line within tolerance wins', A.nearestLevel([100, 200, 300], 43, of) === 100)
  check('outside tolerance → null', A.nearestLevel([100, 200], 60, of) === null)
  check('a line without a coordinate (off-scale) is skipped', A.nearestLevel([300], 40, of) === null)
  check('exact boundary (6 px) still hits', A.nearestLevel([100], 46, of) === 100)
}

// ── BRF "since your last look" (briefChanges) ───────────────────────────────────────────────────────────────
{
  const prev = { at: '2026-11-12T18:42:07', nums: { NIFTY: '25,713', 'India VIX': '11.20' }, events: ['TCS·RESULTS·2026-11-18'] }
  const cur = { at: '2026-11-13T08:55:00', nums: { NIFTY: '25,802', 'India VIX': '11.20' },
                events: ['TCS·RESULTS·2026-11-18', 'INFY·AGM·2026-11-19', 'M&M·RESULTS·2026-11-20'] }
  const fires = ['2026-11-12T10:00:00', '2026-11-13T07:05:00', '2026-11-13T08:15:00']
  const d = A.briefChanges(prev, cur, fires)
  check('a moved number shows old → new', d.some(c => c.label === 'NIFTY' && c.from === '25,713' && c.to === '25,802'), d)
  check('an unmoved number is silent', !d.some(c => c.label === 'India VIX'))
  check('new events counted with their names', d.some(c => c.label === 'events' && c.text === '2 new events for your stocks (INFY, M&M)'), d)
  check('fires counted strictly after the previous look', d.some(c => c.label === 'alerts' && c.text === '2 alert fires'))
  check('no previous look → nothing (first visit is not a diff)', A.briefChanges(null, cur, fires).length === 0)
  check('a previous look newer than now → nothing (clock skew is not news)', A.briefChanges({ ...prev, at: '2027-01-01T00:00:00' }, cur, fires).length === 0)
  check('nothing changed → empty', A.briefChanges({ ...cur, at: '2026-11-13T08:00:00' }, cur, []).length === 0)
  check('diff lines carry no direction words', d.every(c => E.directionWords(`${c.label} ${c.text ?? ''} ${c.from ?? ''} ${c.to ?? ''}`).length === 0))
}
{
  const snap = { at: '2026-11-13T08:55:00', nums: { NIFTY: '25,802' }, events: ['TCS·RESULTS·2026-11-18'] }
  const back = A.parseBriefSnapshot(JSON.stringify(snap))
  check('snapshot round-trips', back != null && back.at === snap.at && back.nums.NIFTY === '25,802' && back.events.length === 1)
  check('corrupt snapshots never parse', A.parseBriefSnapshot('{junk') === null && A.parseBriefSnapshot('null') === null
    && A.parseBriefSnapshot(JSON.stringify({ at: 'yesterday' })) === null && A.parseBriefSnapshot('') === null)
  check('junk fields are dropped, not kept', (() => {
    const p = A.parseBriefSnapshot(JSON.stringify({ at: '2026-11-13T08:55:00', nums: { a: 1, b: 'ok' }, events: ['x', 7] }))
    return p != null && !('a' in p.nums) && p.nums.b === 'ok' && p.events.join(',') === 'x'
  })())
  check('istStamp is an IST wall clock', /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/.test(A.istStamp(new Date())))
  check('sinceLabel prints day month hh:mm', A.sinceLabel('2026-11-12T18:42:07') === '12 Nov 18:42' && A.sinceLabel('garbage') === 'garbage')
}

// ── static source scans: the wiring this builder owns ───────────────────────────────────────────────────────
{
  const isrc = src('components/terminal/InteractiveSeries.tsx')
  check('InteractiveSeries draws priceLines through createPriceLine on the primary series',
    isrc.includes('createPriceLine') && isrc.includes('removePriceLine') && isrc.includes('priceLines'))
  check('line clicks hit-test within 6 px via priceToCoordinate', isrc.includes('subscribeClick') && isrc.includes('priceToCoordinate') && isrc.includes('<= 6'))
  check('the level menu derives its price from coordinateToPrice and only PRE-FILLS (draftAlert)',
    isrc.includes('coordinateToPrice') && isrc.includes('data-sd-level-menu') && isrc.includes('draftAlert(d)') && !isrc.includes('createAlert('))
  check('kit fix 1: a linked crosshair fills the peer legend synchronously from its own data; point-less echoes are ignored',
    isrc.includes('legendPartsAt(s.series, t)') && isrc.includes('const userEvent = !!p.point') && isrc.includes('if (!userEvent && time != null) return'))
  check('kit fix 2: one refit on the first real resize, never after a user gesture',
    isrc.includes('s.refitDone') && isrc.includes('s.userGesture') && isrc.includes('s.fitW') && /refitDone = true\s*\n\s*chartRef\.current\.timeScale\(\)\.fitContent\(\)/.test(isrc))
  check('the overlay reads BOTH stores and listens for alert changes', isrc.includes("getAlertRules('all')") && isrc.includes('ALERTS_EVENT'))
  check('a clicked line opens the rule in ALRT (focus hand-off + goToPage)', isrc.includes('ALERT_FOCUS_KEY') && isrc.includes("goToPage('alerts')"))

  const brf = src('components/Brief.tsx')
  check('BRF L-15: pre-open F&O A/D is a neutral figure', brf.includes('<span style={{ color: T.text }}>{pre.data.advances} / {pre.data.declines}</span>'))
  check('BRF L-15 negative control: no green/red A/D remains', !brf.includes('T.green }}>{pre.data.advances') && !brf.includes('T.red }}>{pre.data.declines'))
  check('BRF L-15: the NIFTY 500 breadth counts are neutral', brf.includes('color: T.text }}>{sm.n500_adv} up') && !brf.includes('T.green }}>{sm.n500_adv'))
  check('BRF what-changed: snapshot + diff through lib/alertOverlay, written only after the previous one was read',
    brf.includes('BRIEF_LASTLOOK_KEY') && brf.includes('parseBriefSnapshot(') && brf.includes('briefChanges(') && brf.includes("lastLook === 'unread'") && brf.includes('data-brief-lastlook'))
  check('BRF what-changed strip renders old → new with the previous look’s date', brf.includes('sinceLabel(lastLook.at)') && brf.includes('{c.from}') && brf.includes('{c.to}'))

  const alrt = src('components/AlertsCenter.tsx')
  check('ALRT merge view: one table over both stores', alrt.includes("getAlertRules('all')") && alrt.includes('one-shot · legacy'))
  check('ALRT: a legacy row’s ✕ writes the price store, never the rule action route', alrt.includes('removeLegacy') && alrt.includes("String(r.id).split(':')[2]"))
  check('ALRT adopts the chart-line focus once (read + removed)', alrt.includes('sessionStorage.getItem(ALERT_FOCUS_KEY)') && alrt.includes('sessionStorage.removeItem(ALERT_FOCUS_KEY)'))

  // ownership guard: this build never touches the alert engine or invents an alert kind
  const overlay = src('lib/alertOverlay.ts')
  check('the overlay never posts a rule itself (pre-fill only; the engine and its kinds are untouched)',
    !overlay.includes('postAlertRule') && !overlay.includes('axios') && !/Kind\(/.test(overlay))
}

// ── verdict ─────────────────────────────────────────────────────────────────────────────────────────────────
console.log(`alertOverlay.check: ${passed} passed, ${failed} failed`)
if (failed > 0) process.exit(1)

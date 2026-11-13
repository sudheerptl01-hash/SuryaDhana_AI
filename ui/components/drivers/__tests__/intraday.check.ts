/**
 * MEMB within-day contribution timeline (FINAL round R2-DRIV; RATING R9-I3), every rule with a negative control:
 *
 *  S  stacking: positives up from 0, negatives down; a null contributes nothing (the gap stays a gap); segments
 *     reconstruct exactly the values they were stacked from.
 *  E  extent covers the stack totals and both lines and always includes zero.
 *  C  coverage line is honest: priced of total, named gaps with weights ("never filled"), the index series' source,
 *     and a late first print says there is no data before it.
 *  R  the residual is printed once, as arithmetic wording, with no direction words anywhere.
 *  W  wiring (static): MEMB mounts the panel outside TabGrey; the component polls only when live; the route file
 *     carries the describes clause.
 *
 * Run with plain node ≥ 22.6 (type stripping, no deps):
 *   node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON ui/components/drivers/__tests__/intraday.check.ts
 */
import * as fs from 'node:fs'
import * as path from 'node:path'

type Mod = typeof import('../intradayModel')
const M = (await import(new URL('../intradayModel.ts', import.meta.url).href)) as Mod

const UI = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..', '..')
const src = (rel: string) => fs.readFileSync(path.join(UI, rel), 'utf8')

let failed = 0
let passed = 0
function check(name: string, cond: unknown, extra?: unknown): void {
  if (cond) { passed++; return }
  failed++
  console.error(`FAIL ${name}${extra !== undefined ? ` :: ${JSON.stringify(extra)}` : ''}`)
}

const payload = (over: Partial<import('../intradayModel').IntradayDriversPayload> = {}): import('../intradayModel').IntradayDriversPayload => ({
  index: 'NIFTY 50', date: '2026-11-13', interval: '1m', live: false,
  minutes: ['14:15', '14:16', '14:17'],
  prev_index_level: 25299.35,
  actual_pts: [-10, -20, -30], explained_pts: [-9, -18, -27], residual_pts: [-1, -2, -3],
  priced: [2, 2, 2], others_pts: [0, -1, -2], residual_now: -3, index_source: 'icici-ws',
  members: {
    add: [{ symbol: 'A', industry: null, weight_pct: 10, points: 6, ret_pct: 0.2, source: 'icici-ws', series: [2, 4, 6] }],
    drag: [{ symbol: 'B', industry: null, weight_pct: 8, points: -31, ret_pct: -1.5, source: 'icici-ws', series: [-11, -21, -31] }],
    rest: [],
  },
  coverage: { members_total: 50, members_priced: 48, gaps: [{ symbol: 'ETERNAL', weight_pct: 1.2, reason: 'no prints on either source' }] },
  weight_method: 'rebuilt_calibrated', weights_as_of: '2026-11-13',
  first_minute: '14:15', last_minute: '15:30', as_of: '2026-11-13T22:00:00+05:30',
  badges: { timeline: 'context', members: 'arithmetic', fit: 'arithmetic' },
  note: 'points = previous index close × weight × intraday return … — describes, does not predict',
  ...over,
})

// ── S. stacking ────────────────────────────────────────────────────────────────────────────────────
{
  const shown = M.shownSeries(payload())
  check('S1 shown = adds, drags, then OTHERS when it is non-zero', shown.map(s => s.symbol).join(','), 'A,B,OTHERS')
  check('S1 shown order', shown.map(s => s.symbol).join(',') === 'A,B,OTHERS', shown.map(s => s.symbol))
  const seg = M.stackAt(shown, 1)
  const a = seg.find(s => s.symbol === 'A')
  const b = seg.find(s => s.symbol === 'B')
  const o = seg.find(s => s.symbol === 'OTHERS')
  check('S2 positives stack up from 0', a && a.y0 === 0 && a.y1 === 4, seg)
  check('S2 negatives stack down, OTHERS below B', b && b.y0 === 0 && b.y1 === -21 && o && o.y0 === -21 && o.y1 === -22, seg)
  check('S2 each segment reconstructs its value', seg.every(s => [4, -21, -1].includes(Number((s.y1 - s.y0).toFixed(6)))), seg)
  const withNull = M.stackAt([{ symbol: 'A', color: '#111', series: [null, 2] }, { symbol: 'B', color: '#222', series: [3, 3] }], 0)
  check('S3 a null contributes nothing (the gap stays a gap)', withNull.length === 1 && withNull[0].symbol === 'B' && withNull[0].y1 === 3, withNull)
  check('S3 negative control: at i=1 both stack', M.stackAt([{ symbol: 'A', color: '#111', series: [null, 2] }, { symbol: 'B', color: '#222', series: [3, 3] }], 1).length === 2)
  const noOthers = M.shownSeries(payload({ others_pts: [0, 0, null] }))
  check('S4 an all-zero OTHERS is not drawn', noOthers.every(s => s.symbol !== 'OTHERS'), noOthers.map(s => s.symbol))
}

// ── E. extent ──────────────────────────────────────────────────────────────────────────────────────
{
  const p = payload()
  const [lo, hi] = M.extentOf(p, M.shownSeries(p))
  check('E1 extent covers the downward stack and the upward one', lo <= -33 && hi >= 6, [lo, hi])
  const flat = payload({ actual_pts: [null, null, null], explained_pts: [null, null, null], others_pts: [null, null, null],
    members: { add: [], drag: [], rest: [] } })
  const [l0, h0] = M.extentOf(flat, M.shownSeries(flat))
  check('E2 nothing priced → [0, 0], zero always included', l0 === 0 && h0 === 0, [l0, h0])
}

// ── C. coverage honesty ────────────────────────────────────────────────────────────────────────────
{
  const line = M.coverageLine(payload())
  check('C1 priced of total', line.includes('48 of 50 members priced'), line)
  check('C1 gaps named with weight and "never filled"', line.includes('gaps (never filled): ETERNAL 1.2%w'), line)
  check('C1 index source named', line.includes('index series from icici-ws'), line)
  check('C2 a late first print is stated honestly', line.includes('first print 14:15 — no data before it'), line)
  const fullDay = M.coverageLine(payload({ first_minute: '09:15', coverage: { members_total: 50, members_priced: 50, gaps: [] } }))
  check('C2 negative control: a full session adds neither clause', !fullDay.includes('first print') && !fullDay.includes('gaps'), fullDay)
}

// ── R. residual + labelling ────────────────────────────────────────────────────────────────────────
{
  const r = M.residualLine(payload()) ?? ''
  check('R1 the residual is stated with its meaning', r.startsWith('residual −3.0 pts at 15:30') && r.includes('do not explain'), r)
  check('R1 no residual, no line', M.residualLine(payload({ residual_now: null })) === null)
  const all = [r, M.coverageLine(payload()), payload().note ?? ''].join(' ')
  check('R2 no direction words anywhere', !/\b(bullish|bearish|buy|sell|long|short)\b/i.test(all), all)
  check('R2 negative control: the scan sees a direction word', /\b(bullish)\b/i.test('bullish'))
  check('R3 fmtPts2 signs with U+2212 and shows a dash for null', M.fmtPts2(-3) === '−3.0' && M.fmtPts2(4.25, 2) === '+4.25' && M.fmtPts2(null) === '—')
}

// ── H. hover + axis helpers ────────────────────────────────────────────────────────────────────────
{
  const shown = M.shownSeries(payload())
  const rows = M.hoverRows(shown, 2, 2)
  check('H1 hover rows are |points| descending, top k', rows.length === 2 && rows[0].symbol === 'B' && rows[1].symbol === 'A', rows)
  check('H2 nearestIdx clamps', M.nearestIdx(-0.5, 10) === 0 && M.nearestIdx(2, 10) === 9 && M.nearestIdx(0.5, 11) === 5)
  const grid = Array.from({ length: 20 }, (_, i) => `${9 + Math.floor((50 + i) / 60)}:${String((50 + i) % 60).padStart(2, '0')}`)
  const ticks = M.axisTicks(grid)                                     // 09:50 … 10:09: first, 10:00, last
  check('H3 axis ticks keep the first slot, hours and the last slot', ticks.join(',') === '0,10,19', ticks)
  const crowded = M.axisTicks(['09:58', '09:59', '10:00', '10:01', '10:02'])
  check('H3 negative control: a tick within 4 slots of the last kept one is dropped', crowded.join(',') === '0', crowded)
}

// ── W. wiring (static) ─────────────────────────────────────────────────────────────────────────────
{
  const im = src('components/IndexMembers.tsx')
  const cp = src('components/drivers/IntradayDrivers.tsx')
  check('W1 MEMB mounts the panel for driver indices', im.includes('<IntradayDrivers index={index} />'))
  check('W1 the mount sits OUTSIDE TabGrey (live ticks, not the nightly fit)', !/TabGrey[^]*?IntradayDrivers/.test(im.split('<IntradayDrivers')[0].slice(-400)))
  check('W2 the component polls only when the session is live', cp.includes('if (r.data.live) timer = setTimeout(load, 60_000)'))
  check('W3 the empty state is honest, never a spinner forever', cp.includes('stays honestly blank'))
  check('W4 the footer falls back to the describes clause', cp.includes("p.note ?? 'describes, does not predict'"))
  check('W5 context badge on the panel, arithmetic on the residual', cp.includes("p?.badges?.timeline ?? 'context'") && cp.includes("p.badges?.fit ?? 'arithmetic'"))
}

console.log(`intraday.check: ${passed} passed, ${failed} failed`)
if (failed) process.exit(1)

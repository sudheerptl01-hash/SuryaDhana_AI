/**
 * B-XPRY chart-kit checks (FINAL ROUND wave B; charts/PLAN.md §4 rows B2/B3/B5), every rule with a negative control:
 *
 *  T  session minutes → kit times: a minute after 09:15 IST on the session date becomes the IST wall clock treated
 *     as UTC (the interactiveModel convention), so the chart's axis and crosshair READ as IST.
 *  P  sessionPoints: out-of-session minutes dropped, a null value stays null (a whitespace gap, never interpolated).
 *  F  sessionFormat: 2 dp with the axis unit; thousands grouped whole (en-IN).
 *  L  the strike ladder's window math and the crosshair's legend line (values readable, never tooltip-only).
 *  S  static scans: SessionChart renders through InteractiveSeries (LWC 4.x via the one wrapper — no direct
 *     createChart, no 5.x addSeries); the live tape panes share linkGroup "omon-live"; ExpiryDay stamps its charts
 *     with the session date; a bare mount keeps the fallback legend line; the session constants mirror tapeModel's.
 *
 * Run with plain node ≥ 22.6 (type stripping, no deps):
 *   node ui/components/expiry/__tests__/charts.check.ts
 */
import * as fs from 'node:fs'
import * as path from 'node:path'

type ChartsModel = typeof import('../chartsModel')
type TapeModel = typeof import('../tapeModel')
type InteractiveModel = typeof import('../../terminal/interactiveModel')
const CM = (await import(new URL('../chartsModel.ts', import.meta.url).href)) as ChartsModel
const TM = (await import(new URL('../tapeModel.ts', import.meta.url).href)) as TapeModel
const IM = (await import(new URL('../../terminal/interactiveModel.ts', import.meta.url).href)) as InteractiveModel

const UI = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..', '..')
const src = (rel: string) => fs.readFileSync(path.join(UI, rel), 'utf8')

let failed = 0
let passed = 0
function check(name: string, cond: unknown, extra?: unknown): void {
  if (cond) { passed++; return }
  failed++
  console.error(`FAIL ${name}${extra !== undefined ? ` :: ${JSON.stringify(extra)}` : ''}`)
}

// ── T. session minutes → kit times ──────────────────────────────────────────────────────────────────
{
  const t0 = CM.minuteToTime('2026-11-09', 0)
  check('T1 minute 0 is 09:15 IST wall clock treated as UTC', t0 === Date.UTC(2026, 10, 9, 9, 15) / 1000, t0)
  check('T1 the crosshair time text then READS as IST', IM.timeText(t0!) === '09 NOV 09:15', IM.timeText(t0!))
  const t371 = CM.minuteToTime('2026-11-09', 371)
  check('T2 minute 371 is 15:26', IM.timeText(t371!) === '09 NOV 15:26', IM.timeText(t371!))
  check('T2 coerceTime passes the epoch through unchanged (a number is already display-shifted)', IM.coerceTime(t0!) === t0)
  check('T3 negative control: a bad day or minute is null', CM.minuteToTime('yesterday', 10) === null && CM.minuteToTime('2026-11-09', NaN) === null)
  check('T4 the session constants mirror tapeModel (one convention)', CM.SESSION_START_MIN === TM.SESSION_START_MIN && CM.SESSION_LEN_MIN === TM.SESSION_LEN_MIN)
  check('T5 istDateOf crosses midnight IST, not UTC', CM.istDateOf(Date.UTC(2026, 10, 13, 20, 0)) === '2026-11-14' && CM.istDateOf(Date.UTC(2026, 10, 13, 10, 0)) === '2026-11-13')
}

// ── P. sessionPoints ────────────────────────────────────────────────────────────────────────────────
{
  const pts = CM.sessionPoints('2026-11-09', [1, -5, 200, 376, NaN], [100, 1, 50.5, 2, 3])
  check('P1 out-of-session minutes dropped (x < 0, x > xMax, NaN)', pts.length === 2 && pts[0].v === 100 && pts[1].v === 50.5, pts)
  const gap = CM.sessionPoints('2026-11-09', [1, 3, 5], [10, null, Infinity])
  check('P2 a null or non-finite value STAYS null (a visible gap, never interpolated)', gap.length === 3 && gap[1].v === null && gap[2].v === null, gap)
  check('P2 negative control: shapeLine turns that null into a whitespace row', (IM.shapeLine(gap)[1] as { value?: number }).value === undefined)
  check('P3 a bad day yields no points rather than invented times', CM.sessionPoints('nope', [1], [1]).length === 0)
  check('P4 a custom xMax clips later minutes', CM.sessionPoints('2026-11-09', [100, 300], [1, 2], 200).length === 1)
}

// ── F. sessionFormat ────────────────────────────────────────────────────────────────────────────────
{
  const pct = CM.sessionFormat('%')
  const plain = CM.sessionFormat('')
  check('F1 2 dp with the unit', pct(42.94) === '42.94%' && pct(0.953) === '0.95%')
  check('F2 thousands grouped whole (forwards, strikes)', plain(24996.7) === '24,997' && pct(25040.67) === '25,041%')
  check('F3 negative values keep the sign (JS half-up rounding: −1234.5 → −1234)', plain(-1234.5) === '-1,234', plain(-1234.5))
}

// ── L. the strike ladder window + legend line ───────────────────────────────────────────────────────
{
  check('L1 full view shows every row', JSON.stringify(CM.visibleRows(31, { min: 0, max: 30 })) === '{"i0":0,"i1":30}')
  check('L1 a zoomed view clips to whole rows', JSON.stringify(CM.visibleRows(31, { min: 3.4, max: 9.2 })) === '{"i0":3,"i1":10}')
  check('L1 negative control: an empty ladder has no rows', CM.visibleRows(0, { min: 0, max: 0 }).i1 === -1)
  const fmt = (v: number) => (v > 0 ? `+${v}` : `${v}`)
  check('L2 the crosshair legend prints strike + both sides', CM.rowLegend(24250, -51545, 322790, fmt) === '24,250 · calls -51545 · puts +322790')
  check('L2 a missing side is an em dash, never 0', CM.rowLegend(25000, null, 5, fmt) === '25,000 · calls — · puts +5')
}

// ── S. static scans ─────────────────────────────────────────────────────────────────────────────────
{
  const charts = src('components/expiry/charts.tsx')
  const oitape = src('components/expiry/OiTape.tsx')
  const xpry = src('components/expiry/ExpiryDay.tsx')
  check('S1 SessionChart renders through InteractiveSeries (the one LWC wrapper)', /from '@\/components\/terminal\/InteractiveSeries'/.test(charts) && /<InteractiveSeries/.test(charts))
  check('S1 negative control: no direct createChart or 5.x addSeries( in the expiry charts', !/createChart\(/.test(charts) && !/\baddSeries\(/.test(charts))
  check('S2 the live tape panes share linkGroup omon-live (one calendar)', (oitape.match(/linkGroup="omon-live"/g) ?? []).length === 2)
  check('S3 ExpiryDay stamps its session charts with the session date', (xpry.match(/date=\{d\.date\}/g) ?? []).length >= 2)
  check('S4 a bare mount keeps the fallback legend line (values never tooltip-only)', (charts.match(/data-sd-chart-cursor/g) ?? []).length === 2)
  check('S5 the ladder blocks page scroll while zooming (touchAction none, non-passive wheel)', /touchAction: 'none'/.test(charts) && /passive: false/.test(charts))
  check('S6 the SVG v2 math comes from the kit, not a re-implementation', /from '@\/components\/terminal\/chart'/.test(charts) && /zoomDomain|panDomain/.test(charts))
  check('S7 the curve honesty fields are read (as_of + replay_pending)', /replay_pending/.test(xpry) && /as_of/.test(xpry))
  check('S8 no green/red direction colour in the expiry charts', !/T\.(green|red)\b/.test(charts) && !/T\.(green|red)\b/.test(xpry))
}

console.log(`charts.check: ${passed} passed, ${failed} failed`)
if (failed) process.exit(1)

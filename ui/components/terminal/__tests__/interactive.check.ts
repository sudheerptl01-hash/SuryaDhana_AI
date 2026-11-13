/**
 * B-KIT node check (FINAL ROUND W3, charts/PLAN.md §4 + §6): the interactive chart kit's pure halves —
 * series shaping, time coercion, the band → area-pair, markers, the link-group registry, the theme object and
 * the SVG v2 interaction math — plus static source scans (one theme source, 4.x LWC API names only, the
 * attribution mark untouched). LWC itself needs DOM + canvas, so the node check never renders it (§6).
 *
 * Run with plain node ≥ 23.6 (type stripping, no deps):
 *   node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON ui/components/terminal/__tests__/interactive.check.ts
 * Also type-checked by `cd ui && npx tsc --noEmit`. Exits non-zero on any failing check.
 */
import * as fs from 'node:fs'
import * as path from 'node:path'

type ModelMod = typeof import('../interactiveModel')
type LinkMod = typeof import('../linkGroups')
type ChartMod = typeof import('../chart')
const M = (await import(new URL('../interactiveModel.ts', import.meta.url).href)) as ModelMod
const L = (await import(new URL('../linkGroups.ts', import.meta.url).href)) as LinkMod
const C = (await import(new URL('../chart.ts', import.meta.url).href)) as ChartMod

const TERMINAL = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..')
const read = (rel: string): string => fs.readFileSync(path.join(TERMINAL, rel), 'utf8')

let failed = 0
let passed = 0
function check(name: string, cond: unknown, extra?: unknown): void {
  if (cond) { passed++; return }
  failed++
  console.error(`FAIL ${name}${extra !== undefined ? ` :: ${JSON.stringify(extra)}` : ''}`)
}

// ── time coercion ────────────────────────────────────────────────────────────────────────────────────

check('date-only stays a business day', M.coerceTime('2026-11-12') === '2026-11-12')
check('zoned ISO → epoch s shifted +05:30 (UTC render reads IST)',
  M.coerceTime('2026-11-13T04:30:00Z') === Date.UTC(2026, 10, 13, 4, 30) / 1000 + 19_800)
check('+05:30-zoned ISO lands on the same display epoch as its UTC twin',
  M.coerceTime('2026-11-13T10:00:00+05:30') === M.coerceTime('2026-11-13T04:30:00Z'))
check('zone-less ISO is an IST wall clock, shown unchanged',
  M.coerceTime('2026-11-13T10:00:00') === Date.UTC(2026, 10, 13, 10, 0) / 1000)
check('epoch seconds pass through', M.coerceTime(1_700_000_000) === 1_700_000_000)
check('epoch milliseconds divided down', M.coerceTime(1_700_000_000_123) === 1_700_000_000)
check('garbage time → null', M.coerceTime('13-Nov-2026') === null && M.coerceTime(NaN) === null && M.coerceTime(undefined) === null)
check('timeText prints a business day as-is', M.timeText('2026-11-12') === '2026-11-12')
check('timeText prints an epoch as DD MON HH:MM', M.timeText(Date.UTC(2026, 10, 13, 10, 5) / 1000) === '13 NOV 10:05')

// ── series shaping ───────────────────────────────────────────────────────────────────────────────────

const shaped = M.shapeLine([
  { t: '2026-11-12', v: 18.2 },
  { t: '2026-11-10', v: 17.0 },
  { t: '2026-11-11', v: null },          // → whitespace gap
  { t: '2026-11-10', v: 17.5 },          // duplicate: the LAST write wins
  { t: 'not-a-date', v: 9 },             // dropped
])
check('shapeLine sorts ascending', shaped.map(p => p.time).join(',') === '2026-11-10,2026-11-11,2026-11-12')
check('shapeLine dedupes keeping the last write', shaped[0].value === 17.5)
check('null v → whitespace row (a gap, never interpolated)', shaped[1].value === undefined && !('value' in shaped[1]))
check('finite v kept', shaped[2].value === 18.2)

const candles = M.shapeCandles([
  { t: '2026-11-11', o: 1, h: 2, l: 0.5, c: 1.5 },
  { t: '2026-11-12', o: 1, h: null, l: 0.5, c: 1.5 },   // incomplete bar → whitespace
])
check('shapeCandles maps o/h/l/c', candles[0].open === 1 && candles[0].high === 2 && candles[0].low === 0.5 && candles[0].close === 1.5)
check('incomplete candle → whitespace', !('close' in candles[1]))

const sigA = M.seriesSignature([{ id: 'a', points: [] }, { id: 'b', type: 'candles', points: [] }])
const sigB = M.seriesSignature([{ id: 'a', points: [{ t: '2026-11-12', v: 1 }] }, { id: 'b', type: 'candles', points: [] }])
const sigC = M.seriesSignature([{ id: 'a', axis: 'L', points: [] }, { id: 'b', type: 'candles', points: [] }])
check('data-only changes keep the signature (no rebuild flicker)', sigA === sigB)
check('an axis change rebuilds', sigA !== sigC)
check('a band changes the signature', M.seriesSignature([], { lo: [], hi: [] }) !== M.seriesSignature([]))

// ── band → area pair ─────────────────────────────────────────────────────────────────────────────────

const pair = M.bandAreaOptions('#b58bff', '#0a0d13')
check('band hi fill is the translucent band colour', pair.hi.topColor === '#b58bff26' && pair.hi.bottomColor === '#b58bff26')
check('band lo fill is the PANEL mask', pair.lo.topColor === '#0a0d13' && pair.lo.bottomColor === '#0a0d13')
check('band areas are quiet (no price line / last value / crosshair marker)',
  !pair.hi.priceLineVisible && !pair.hi.lastValueVisible && !pair.hi.crosshairMarkerVisible && !pair.lo.priceLineVisible)

// ── markers ──────────────────────────────────────────────────────────────────────────────────────────

const pal = { results: '#b58bff', expiry: '#747e92', default: '#39c6ff' }
const mk = M.toMarkers([
  { t: '2026-11-12', kind: 'expiry' },
  { t: '2026-11-10', kind: 'results' },
  { t: 'bad', kind: 'results' },
  { t: '2026-11-11', kind: 'anything-else' },
], pal)
check('markers sorted ascending, unparsable dropped', mk.length === 3 && mk[0].time === '2026-11-10' && mk[2].time === '2026-11-12')
check('results marker is violet circle', mk[0].color === pal.results && mk[0].shape === 'circle')
check('expiry marker is muted square', mk[2].color === pal.expiry && mk[2].shape === 'square')
check('unknown kind falls back to cyan', mk[1].color === pal.default)
check('markers sit aboveBar', mk.every(m => m.position === 'aboveBar'))

// ── theme object ─────────────────────────────────────────────────────────────────────────────────────

const tk = { bg: '#05070a', panel: '#0a0d13', border: '#1a2130', borderHi: '#2a3448', muted: '#8691a5', text: '#d6dbe4', mono: 'JetBrains Mono' }
const theme = M.buildChartTheme(tk) as Record<string, any>   // eslint-disable-line @typescript-eslint/no-explicit-any
check('theme: solid panel background', theme.layout.background.type === 'solid' && theme.layout.background.color === tk.panel)
check('theme: muted mono axis text', theme.layout.textColor === tk.muted && theme.layout.fontFamily === tk.mono && theme.layout.fontSize === 10)
check('theme: grid on the border token', theme.grid.vertLines.color === tk.border && theme.grid.horzLines.color === tk.border)
check('theme: dashed crosshair (LineStyle.Dashed = 2, CrosshairMode.Normal = 0)',
  theme.crosshair.mode === 0 && theme.crosshair.vertLine.style === 2 && theme.crosshair.vertLine.labelBackgroundColor === tk.borderHi)
check('theme: both price scales bordered', theme.rightPriceScale.borderColor === tk.border && theme.leftPriceScale.borderColor === tk.border)
check('theme: scroll + scale on (the free zoom/pan)', theme.handleScroll === true && theme.handleScale === true)
check('theme: attribution mark untouched (licence)', !('attributionLogo' in (theme.layout ?? {})))

// ── link-group registry (one trading calendar only — the spike finding) ──────────────────────────────

{
  L._resetLinks()
  const got: string[] = []
  const a = L.registerLink('omon', 'nse', { onRange: r => got.push(`a:${r.from}-${r.to}`), onCrosshair: t => got.push(`a:x:${t}`) })
  const b = L.registerLink('omon', 'nse', { onRange: r => got.push(`b:${r.from}-${r.to}`) })
  const gold = L.registerLink('omon', 'comex', { onRange: r => got.push(`gold:${r.from}-${r.to}`) })
  const other = L.registerLink('derv', 'nse', { onRange: r => got.push(`other:${r.from}-${r.to}`) })
  L.broadcastRange(a.id, { from: 10, to: 60 })
  check('same group + same calendar receives', got.includes('b:10-60'))
  check('same group, OTHER calendar never receives (spike finding)', !got.some(x => x.startsWith('gold:')))
  check('other group never receives', !got.some(x => x.startsWith('other:')))
  check('the sender never echoes itself', !got.some(x => x.startsWith('a:10')))
  check('peer count scopes to (group, calendar)', L.linkPeerCount(a.id) === 1 && L.linkPeerCount(gold.id) === 0)

  // re-entrancy: a receiver that broadcasts back must be dropped, not loop
  got.length = 0
  const c = L.registerLink('loop', 'nse', { onRange: () => { L.broadcastRange(d.id, { from: 0, to: 1 }); got.push('c') } })
  const d = L.registerLink('loop', 'nse', { onRange: () => got.push('d') })
  L.broadcastRange(d.id, { from: 5, to: 9 })
  check('re-entrant broadcast is dropped (no echo loop)', got.join(',') === 'c')

  got.length = 0
  b.unregister()
  L.broadcastCrosshair(a.id, '2026-11-12')
  check('crosshair broadcast reaches handlers; unregistered members silent',
    !got.some(x => x.startsWith('b:')) && L.linkPeerCount(a.id) === 0)
  check('crosshair null (cleared) is deliverable', (() => { let ok = false; const e = L.registerLink('omon', 'nse', { onCrosshair: t => { ok = t === null } }); L.broadcastCrosshair(a.id, null); e.unregister(); return ok })())
  c.unregister(); d.unregister(); a.unregister(); gold.unregister(); other.unregister()
  L._resetLinks()
}

// ── SVG v2 interaction math (chart.ts) ───────────────────────────────────────────────────────────────

const full = { min: 0, max: 100 }
const z1 = C.zoomDomain(full, full, 0.5, 0.5, 2)
check('zoom in halves the span about the focus', Math.abs(z1.max - z1.min - 50) < 1e-9 && Math.abs(z1.min - 25) < 1e-9)
const z2 = C.zoomDomain(z1, full, 10, 0.5, 2)
check('zoom out clamps to the full domain', z2.min === 0 && z2.max === 100)
const z3 = C.zoomDomain(full, full, 1e-9, 0.5, 2)
check('zoom in clamps to minSpan', Math.abs(z3.max - z3.min - 2) < 1e-9)
const zEdge = C.zoomDomain({ min: 80, max: 100 }, full, 2, 1, 2)
check('zoom at the right edge stays inside', zEdge.max <= 100 + 1e-9 && zEdge.min >= 0)
const p1 = C.panDomain({ min: 20, max: 40 }, full, 0.5)
check('pan shifts by the fraction of the span', p1.min === 30 && p1.max === 50)
const p2 = C.panDomain({ min: 90, max: 100 }, full, 1)
check('pan clamps at the edge', p2.max === 100 && p2.min === 90)
check('nearestIndex snaps (skipping non-finite)', C.nearestIndex([1, 5, NaN, 9], 6) === 1 && C.nearestIndex([1, 5, NaN, 9], 7.5) === 3)
check('nearestIndex on empty → −1', C.nearestIndex([], 1) === -1)
check('clampDomain keeps the span', (() => { const v = C.clampDomain({ min: -10, max: 30 }, full); return v.min === 0 && v.max === 40 })())

// ── legend ───────────────────────────────────────────────────────────────────────────────────────────

check('fmtValue defaults to 2 dp (0 dp above 1000)', M.fmtValue(18.234) === '18.23' && M.fmtValue(25713.4) === '25713' && M.fmtValue(null) === '—')
check('fmtValue honours a custom format', M.fmtValue(0.1234, v => `${(v * 100).toFixed(1)}%`) === '12.3%')
check('legendLine joins time and parts with ·',
  M.legendLine('2026-02-23', [{ label: 'IV30', text: '11.73%' }, { label: 'SPOT', text: '25713' }]) === '2026-02-23 · IV30 11.73% · SPOT 25713')

// ── static source scans (one theme source; 4.x API names only; the shell contract) ───────────────────

const isrc = read('InteractiveSeries.tsx')
const themeSrc = read('chartTheme.ts')
const shellSrc = read('ExpandableChart.tsx')
check('InteractiveSeries themes from ./chartTheme only', isrc.includes("from './chartTheme'") && !/createChart\([^)]*\{\s*layout/.test(isrc))
check('chartTheme binds the T tokens to the pure builder', themeSrc.includes("from '@/components/news/format'") && themeSrc.includes('buildChartTheme(T)'))
check('4.x API names only (no 5.x addSeries)', isrc.includes('addLineSeries') && isrc.includes('addCandlestickSeries')
  && isrc.includes('addAreaSeries') && isrc.includes('addHistogramSeries') && !/\.addSeries\(/.test(isrc))
check('FIT and PNG are the spike-proven calls', isrc.includes('fitContent()') && isrc.includes('takeScreenshot()'))
check('nothing turns the attribution mark off', !isrc.includes('attributionLogo') && !themeSrc.replace(/\/\*[\s\S]*?\*\/|\/\/[^\n]*/g, '').includes('attributionLogo'))
check('the shell portals the expanded child and locks body scroll', shellSrc.includes('createPortal') && shellSrc.includes("overflow = 'hidden'"))
check('the shell closes on Escape', shellSrc.includes("'Escape'"))
check('crosshair values go to the legend slot, never tooltip-only', isrc.includes('setLegend') && shellSrc.includes('data-sd-chart-legend'))
check('link sync is calendar-scoped in the component', isrc.includes("calendar = 'nse'") && isrc.includes('registerLink(linkGroup, calendar'))

// ── verdict ──────────────────────────────────────────────────────────────────────────────────────────

console.log(`interactive.check: ${passed} passed, ${failed} failed`)
if (failed > 0) process.exit(1)

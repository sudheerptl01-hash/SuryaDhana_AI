/**
 * Terminal pages checks (W2-UI-PAGES): price formatting (C1-trader-ux-08), PAPER ONLY presentation on PORT
 * (C1-trader-ux-04), the ICICI login URL never printed (C1-trader-ux-05), dim-text contrast (C1-trader-ux-15),
 * px-sized SVG charts with round ticks and non-overlapping labels (C1-trader-ux-17), EQS row memoization
 * (C2-performance-01), the COMP multi-window merge (C3-logic-unchanged-02) and copy polish (C1-trader-ux-18).
 * Round 3 (F3-UI-PAGES): latest-request-wins hand-offs (CT-01), OMON walls from the server (RUP-01/CT-02), the DESK
 * watchlist layout (CT-03), PORT fail-closed (RUP-02), COMP remove-last (RUP-03), EQS flash clearing (RUP-04),
 * no regex lookbehind (RUP-07), one unit per column and closed-market wording (C1-08/-13/-18, CT-05/-11/-13/-14).
 * Round 4 (F4B-UI-PAGES): every hand-rolled sign site (C1-18), OMON's refresh vs a slow answer and the guard in a ref (P1),
 * DERV height-based ticks (R11), ICICI error_kind wording on BRKR/PORT/BRIEF (P4), MOV polling on the session clock
 * (P5), the alert form prefill (P11), ALFA scans with the new value (P12), EQS columns (CT-08), INSD order, MKT
 * wording and the BTST IST file stamp (P16).
 *
 * Run with plain node 25 (type stripping, no deps):
 *   node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON ui/components/__tests__/pages.check.ts
 * Also type-checked by `cd ui && npx tsc --noEmit`. Exits non-zero on any failing check.
 */
import * as fs from 'node:fs'
import * as path from 'node:path'

type FormatMod = typeof import('../../lib/format/index')
type ChartMod = typeof import('../terminal/chart')
type PolicyMod = typeof import('../portfolio/policy')
type CompareMod = typeof import('../compareSet')
type SeqMod = typeof import('../requestSeq')
type OmonMod = typeof import('../omonModel')
type DeskMod = typeof import('../deskLayout')
type FlashMod = typeof import('../flashClock')
type MdMod = typeof import('../terminal/mdInline')
type IciciMod = typeof import('../portfolio/iciciState')
type ModelsMod = typeof import('../pageModels')
type SessionMod = typeof import('../desktop/session')
const F = (await import(new URL('../../lib/format/index.ts', import.meta.url).href)) as FormatMod
const C = (await import(new URL('../terminal/chart.ts', import.meta.url).href)) as ChartMod
const P = (await import(new URL('../portfolio/policy.ts', import.meta.url).href)) as PolicyMod
const S = (await import(new URL('../compareSet.ts', import.meta.url).href)) as CompareMod
const R = (await import(new URL('../requestSeq.ts', import.meta.url).href)) as SeqMod
const O = (await import(new URL('../omonModel.ts', import.meta.url).href)) as OmonMod
const DL = (await import(new URL('../deskLayout.ts', import.meta.url).href)) as DeskMod
const FC = (await import(new URL('../flashClock.ts', import.meta.url).href)) as FlashMod
const MD = (await import(new URL('../terminal/mdInline.ts', import.meta.url).href)) as MdMod
const IC = (await import(new URL('../portfolio/iciciState.ts', import.meta.url).href)) as IciciMod
const PM = (await import(new URL('../pageModels.ts', import.meta.url).href)) as ModelsMod
const SE = (await import(new URL('../desktop/session.ts', import.meta.url).href)) as SessionMod

const UI = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..')
const src = (rel: string) => fs.readFileSync(path.join(UI, rel), 'utf8')

let failed = 0
let passed = 0
let pending = 0
function check(name: string, cond: unknown, extra?: unknown): void {
  if (cond) {
    passed++
    return
  }
  failed++
  console.error(`FAIL ${name}${extra !== undefined ? ` :: ${JSON.stringify(extra)}` : ''}`)
}

const MINUS = '−'

// ── 1. prices as the exchange shows them (C1-trader-ux-08) ───────────────────────────────────────
{
  check('F1 311.65 stays 311.65', F.fmtPx(311.65) === '311.65', F.fmtPx(311.65))
  check('F1 125.99 stays 125.99', F.fmtPx(125.99) === '125.99', F.fmtPx(125.99))
  check('F1 57.45 / 76.41', F.fmtPx(57.45) === '57.45' && F.fmtPx(76.41) === '76.41')
  check('F1 whole number gets .00', F.fmtPx(33100) === '33,100.00', F.fmtPx(33100))
  check('F1 one decimal gets two', F.fmtPx(1125.3) === '1,125.30', F.fmtPx(1125.3))
  check('F1 Indian grouping', F.fmtPx(144376) === '1,44,376.00' && F.fmtPx(10332756) === '1,03,32,756.00', F.fmtPx(144376))
  check('F1 rupee price', F.fmtInrPx(311.65) === '₹311.65' && F.fmtInrPx(3910.3) === '₹3,910.30', F.fmtInrPx(3910.3))
  check('F1 negative uses U+2212', F.fmtInrPx(-5) === `${MINUS}₹5.00` && F.fmtFixed(-1234.5) === `${MINUS}1,234.50`, F.fmtInrPx(-5))
  check('F1 no negative zero', F.fmtFixed(-0.001) === '0.00' && F.fmtInrPx(-0.004) === '₹0.00', F.fmtFixed(-0.001))
  check('F1 index level 2 dp', F.fmtIdx(22600) === '22,600.00' && F.fmtIdx(22600.04) === '22,600.04', F.fmtIdx(22600))
  check('F1 missing values', F.fmtPx(null) === '—' && F.fmtPx(undefined) === '—' && F.fmtPx(NaN) === '—' && F.fmtIdx(Infinity) === '—')
  check('F1 signed', F.fmtSigned(12.5) === '+12.50' && F.fmtSigned(-3.25) === `${MINUS}3.25` && F.fmtSigned(0.001) === '0.00')
  // negative control: the Desk's old formatter (fmtInr(w.close, 1)) printed an impossible off-tick price
  const oldDesk = (v: number) => `₹${v.toLocaleString('en-IN', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}`
  check('F1 negative control: old Desk Last rounded 311.65 to 311.7', oldDesk(311.65) === '₹311.7' && F.fmtInrPx(311.65) !== oldDesk(311.65))
  const oldEqs = (v: number) => v.toLocaleString('en-IN', { maximumFractionDigits: 2 })
  check('F1 negative control: old EQS CMP had ragged decimals', oldEqs(1125.3) === '1,125.3' && oldEqs(33100) === '33,100')
}

// ── 2. minus glyphs and server sentences ────────────────────────────────────────────────────────
{
  check('F2 unicodeMinus on numbers only', F.unicodeMinus('-1.23% vs 2026-10-23 (-5)') === `${MINUS}1.23% vs 2026-10-23 (${MINUS}5)`,
    F.unicodeMinus('-1.23% vs 2026-10-23 (-5)'))
  check('F2 asciiMinus for CSV', F.asciiMinus(`${MINUS}₹5.00 / ${MINUS}1.2%`) === '-₹5.00 / -1.2%')
  check('F2 Western grouping re-grouped', F.indianGrouping('within ₹300 of ₹144,376') === 'within ₹300 of ₹1,44,376',
    F.indianGrouping('within ₹300 of ₹144,376'))
  check('F2 big numbers', F.indianGrouping('12,345,678.50 lots') === '1,23,45,678.50 lots', F.indianGrouping('12,345,678.50 lots'))
  check('F2 followed by a comma', F.indianGrouping('₹144,376, then ₹2,500') === '₹1,44,376, then ₹2,500', F.indianGrouping('₹144,376, then ₹2,500'))
  check('F2 Indian / dates / times / small untouched',
    F.indianGrouping('₹1,44,376 on 2026-10-23 at 09:15, 300 and 4.5') === '₹1,44,376 on 2026-10-23 at 09:15, 300 and 4.5',
    F.indianGrouping('₹1,44,376 on 2026-10-23 at 09:15, 300 and 4.5'))
}

// ── 3. default date ranges end today (C1-trader-ux-18) ─────────────────────────────────────────
{
  check('F3 IST calendar day', F.istDateISO(new Date('2026-10-24T20:00:00Z')) === '2026-10-25', F.istDateISO(new Date('2026-10-24T20:00:00Z')))
  check('F3 month shift clamps', F.shiftMonthsISO('2026-03-31', -1) === '2026-02-28' && F.shiftMonthsISO('2026-10-25', -9) === '2026-01-25'
    && F.shiftMonthsISO('2026-01-15', -36) === '2023-01-15', [F.shiftMonthsISO('2026-03-31', -1), F.shiftMonthsISO('2026-10-25', -9)])
  const r = F.trailingRange(9, new Date('2026-10-25T08:00:00Z'))
  check('F3 trailing range', r.from === '2026-01-25' && r.to === '2026-10-25', r)
  for (const [file, stale] of [['components/GlassBoxStudio.tsx', ["'2025-09-01'", "'2026-05-31'"]], ['components/MLEngineWorkspace.tsx', ["'2025-12-31'"]]] as const) {
    check(`F3 ${file} has no stale hard-coded default range`, stale.every(d => !src(file).includes(`useState(${d})`)) && src(file).includes('trailingRange('), file)
  }
}

// ── 4. charts in CSS px, round ticks, labels that never overlap (C1-trader-ux-17) ───────────────
{
  check('C1 chart height keeps the aspect ratio', C.chartHeight(840, 420, 150) === 240 && C.chartHeight(420, 420, 150) === 150)
  check('C1 chart height clamps', C.chartHeight(4000, 420, 150) === 240 && C.chartHeight(100, 420, 150) === 120 && C.chartHeight(0, 420, 150) === 150)
  check('C1 nice steps', C.niceStep(108, 4) === 50 && C.niceStep(1.3, 4) === 0.5 && C.niceStep(4135, 6) === 1000 && C.niceStep(10, 4) === 2.5,
    [C.niceStep(108, 4), C.niceStep(1.3, 4), C.niceStep(4135, 6), C.niceStep(10, 4)])
  const t = C.niceTicks(-38, 70, 4)
  check('C1 DERV-style ticks are round (were 70 / 16 / −38)', JSON.stringify(t) === JSON.stringify([0, 50]) || t.every(v => v % 10 === 0), t)
  const x = C.niceTicks(19865, 24000, 6)
  check('C1 OSTR x ticks are round (were 19865 / 20948 / …)', x.length >= 3 && x.every(v => v % 500 === 0) && x[0] >= 19865 && x[x.length - 1] <= 24000, x)
  check('C1 ticks include zero when the range crosses it', C.niceTicks(-120000, 160000, 5).includes(0))
  check('C1 no -0 tick', !C.niceTicks(-1, 1, 4).some(v => Object.is(v, -0)))
  const ax = C.niceAxis(10.2, 11.5, 3)
  check('C1 niceAxis decimals print ticks distinctly', new Set(ax.ticks.map(v => v.toFixed(ax.dp))).size === ax.ticks.length && ax.dp >= 1, ax)
  check('C1 step decimals', C.stepDecimals(5) === 0 && C.stepDecimals(2.5) === 1 && C.stepDecimals(0.25) === 2)
  // OI-by-strike axis: 41 strikes at 9 px pitch; ATM 20 and the walls 25 / 14 always labelled, no two labels closer than 40 px
  const L = C.pickAxisLabels(41, 9, 40, [20, 25, 14])
  const gaps = L.slice(1).map((v, i) => (v - L[i]) * 9)
  check('C1 strike axis keeps ATM and walls', [20, 25, 14].every(i => L.includes(i)), L)
  check('C1 strike axis: regular labels stay clear of the must labels', L.filter(i => ![20, 25, 14].includes(i)).every(i => [20, 25, 14].every(m => Math.abs(m - i) * 9 >= 40)), L)
  check('C1 strike axis labels more than first/last', L.length >= 6, L)
  check('C1 strike axis: regular labels at least the min gap apart', L.filter(i => ![20, 25, 14].includes(i)).every((v, k, a) => k === 0 || (v - a[k - 1]) * 9 >= 40), gaps)
  check('C1 strike axis with wide pitch labels every strike', C.pickAxisLabels(5, 80, 40).length === 5)
  // round strikes: NIFTY 50-point strikes 21,250 … 23,950 at 9 px; ATM 22,600 and walls 23,500 / 21,500 kept
  const strikes = Array.from({ length: 55 }, (_, i) => 21250 + 50 * i)
  const RL = C.pickRoundLabels(strikes, 9, 46, [27, 45, 5])
  const regular = RL.filter(i => ![27, 45, 5].includes(i))
  check('C1 round strike labels: musts kept', [27, 45, 5].every(i => RL.includes(i)), RL)
  check('C1 round strike labels land on round strikes (was 21,850 / 22,050)', regular.length >= 2 && regular.every(i => strikes[i] % 500 === 0),
    regular.map(i => strikes[i]))
  check('C1 round strike labels never closer than the gap', RL.every((v, k) => k === 0 || (v - RL[k - 1]) * 9 >= 46 || [v, RL[k - 1]].every(i => [27, 45, 5].includes(i))),
    RL.map(i => strikes[i]))
  check('C1 round labels with missing strikes still spaced', (() => { const vals = [100, 105, 110, 120, 125, 150, 175, 200]; const r = C.pickRoundLabels(vals, 30, 40); return r.every((v, k) => k === 0 || (v - r[k - 1]) * 30 >= 40) })())
  // breakeven labels 'BE 22,324.9' and 'BE 22,875.1' 30 px apart, 63 px wide: second row
  const rows = C.staggerRows([{ x: 300, w: 63 }, { x: 330, w: 63 }, { x: 600, w: 63 }])
  check('C1 overlapping labels go to a second row', rows[0] === 0 && rows[1] === 1 && rows[2] === 0, rows)
  check('C1 non-overlapping labels stay on row 0', C.staggerRows([{ x: 100, w: 40 }, { x: 200, w: 40 }]).every(r => r === 0))
  // one ₹ unit per axis (was ₹1.3L next to ₹88.9k)
  const ticks = [-50000, 0, 50000, 100000, 150000]
  const unit = C.rupeeAxisUnit(ticks)
  const labels = ticks.map(v => C.fmtAxisRupees(v, unit, 50000))
  check('C1 one unit for the whole axis', unit.suffix === 'L' && labels.every(l => l === '₹0' || l.endsWith('L')), labels)
  check('C1 axis labels', JSON.stringify(labels) === JSON.stringify([`${MINUS}₹0.5L`, '₹0', '₹0.5L', '₹1.0L', '₹1.5L']), labels)
  const oldShort = (v: number) => Math.abs(v) >= 1e5 ? `${(v / 1e5).toFixed(1)}L` : Math.abs(v) >= 1e3 ? `${(v / 1e3).toFixed(1)}k` : v.toFixed(0)
  check('C1 negative control: the old OSTR axis mixed L and k', oldShort(130000).endsWith('L') && oldShort(88900).endsWith('k'))
  check('C1 crore and thousand units', C.rupeeAxisUnit([2e7]).suffix === ' cr' && C.rupeeAxisUnit([5000]).suffix === 'K' && C.rupeeAxisUnit([500]).suffix === '')
  check('C1 text width estimate', Math.abs(C.textWidth('BE 22,324.9', 9.5) - 11 * 9.5 * 0.6) < 1e-9)
  // every converted chart is drawn in px (no viewBox scaling with height:auto) and uses useChartSize
  const charts = ['components/OptionChain.tsx', 'components/DerivativesDesk.tsx', 'components/StrategyBuilder.tsx', 'components/DecisionDesk.tsx',
    'components/RiskDashboard.tsx', 'components/MarketMonitor.tsx', 'components/Compare.tsx', 'components/RotationChart.tsx',
    'components/MarginMonitor.tsx', 'components/ParticipantPositioning.tsx', 'components/MarketMap.tsx']
  for (const f of charts) {
    const s = src(f)
    check(`C1 ${f}: px-sized SVG (no viewBox + height:auto scaling)`, !/viewBox=\{[^}]*\}\s*style=\{\{\s*width:\s*'100%',\s*height:\s*'auto'/.test(s) && s.includes('useChartSize('), f)
  }
  // stock window chart (lightweight-charts): legend in its own row, no volume tag on the price axis
  const ipc = src('components/IndicatorPriceChart.tsx')
  check('C1 stock chart legend sits above the plot, not over the lines', ipc.includes('data-testid="chart-legend"')
    && !ipc.includes('absolute top-2 left-2 z-10'))
  check('C1 stock chart volume series draws no axis tag or price line', /addHistogramSeries\(\{[\s\S]{0,200}?lastValueVisible: false, priceLineVisible: false/.test(ipc))
  const kit = src('components/terminal/index.tsx')
  check('C1 kit hook measures before paint and on resize', kit.includes('export function useChartSize(') && kit.includes('ResizeObserver') && kit.includes('useLayoutEffect'))
}

// ── 5. PORT on a PAPER-ONLY terminal (C1-trader-ux-04) ─────────────────────────────────────────
{
  const liveRestored = P.executionPolicy({ mode: 'LIVE', state: 'ACTIVE', live_allowed: false, mode_policy: 'PAPER_ONLY' })
  check('P1 PAPER ONLY label', liveRestored.paperOnly && liveRestored.modeLabel === 'PAPER ONLY' && liveRestored.modeTone === 'paper', liveRestored)
  check('P1 LIVE never drawn selected', !liveRestored.showLiveSelected && !liveRestored.liveSelectable, liveRestored)
  check('P1 engine-reports-LIVE warning', liveRestored.engineLiveMismatch === true)
  check('P1 no liquidate while the engine reports LIVE (the server refuses it)', !liveRestored.liquidateAllowed)
  const paper = P.executionPolicy({ mode: 'PAPER', state: 'ACTIVE', live_allowed: false, mode_policy: 'PAPER_ONLY' })
  check('P1 PAPER engine: liquidate offered, labelled PAPER', paper.liquidateAllowed && paper.liquidateLabel.includes('PAPER') && !paper.engineLiveMismatch, paper)
  check('P1 halted: no liquidate', !P.executionPolicy({ mode: 'PAPER', state: 'HALTED', live_allowed: false }).liquidateAllowed)
  check('P1 either signal means PAPER ONLY (fail closed)', P.executionPolicy({ mode: 'PAPER', mode_policy: 'paper_only' }).paperOnly
    && P.executionPolicy({ mode: 'PAPER', live_allowed: false, mode_policy: 'LIVE_ALLOWED' }).paperOnly)
  const opted = P.executionPolicy({ mode: 'LIVE', state: 'ACTIVE', live_allowed: true, mode_policy: 'LIVE_ALLOWED', available: true })
  check('P1 owner opt-in: behaves as before', opted.known && !opted.paperOnly && opted.showLiveSelected && opted.liveSelectable && opted.modeLabel === 'LIVE'
    && opted.liquidateAllowed, opted)
  // RUP-02: fail CLOSED. Unknown, missing or contradicting policy fields mean PAPER ONLY (the old rows here locked in
  // the fail-open: an older-API status and a null status both offered LIVE and its 'Real orders' confirm)
  const old = P.executionPolicy({ mode: 'LIVE', state: 'ACTIVE' })
  check('P1 status without the policy fields: PAPER ONLY (fail closed)', !old.known && old.paperOnly && !old.liveSelectable && !old.showLiveSelected
    && old.engineLiveMismatch && !old.liquidateAllowed, old)
  const none = P.executionPolicy(null)
  check('P1 null status (first refresh failed): STATUS UNKNOWN · PAPER ONLY, no LIVE, no LIQUIDATE',
    none.paperOnly && !none.statusKnown && none.modeLabel === 'STATUS UNKNOWN · PAPER ONLY' && none.modeTone === 'unknown'
    && !none.liveSelectable && !none.showLiveSelected && !none.liquidateAllowed && !none.engineLiveMismatch, none)
  check('P1 undefined status fails closed too', P.executionPolicy(undefined).paperOnly && !P.executionPolicy(undefined).liquidateAllowed)
  const placeholder = P.executionPolicy({ available: false, mode: 'PAPER', state: 'UNAVAILABLE' })   // LivePortfolio's old defaultStatus
  check('P1 the page placeholder never enables LIVE or LIQUIDATE', placeholder.paperOnly && !placeholder.liveSelectable && !placeholder.liquidateAllowed, placeholder)
  check('P1 live_allowed alone is not enough (both fields must allow LIVE)',
    P.executionPolicy({ mode: 'PAPER', live_allowed: true }).paperOnly && P.executionPolicy({ mode: 'PAPER', mode_policy: 'LIVE_ALLOWED' }).paperOnly
    && P.executionPolicy({ mode: 'PAPER', live_allowed: true, mode_policy: 'PAPER_ONLY' }).paperOnly)
  check('P1 engine offline: no liquidate even when LIVE is allowed', !P.executionPolicy({ mode: 'PAPER', state: 'UNAVAILABLE', available: false,
    live_allowed: true, mode_policy: 'LIVE_ALLOWED' }).liquidateAllowed)
  check('P1 opted-in but halted: no liquidate', !P.executionPolicy({ mode: 'LIVE', state: 'HALTED', live_allowed: true, mode_policy: 'LIVE_ALLOWED' }).liquidateAllowed)
  // negative control: the wave-2 rule (paperOnly only when a field SAYS paper) was fail-open on null
  const waveTwo = (st: { live_allowed?: boolean; mode_policy?: string } | null) => st?.live_allowed === false || String(st?.mode_policy ?? '').toUpperCase() === 'PAPER_ONLY'
  check('P1 negative control: the wave-2 rule offered LIVE for a null status', !waveTwo(null) && P.executionPolicy(null).paperOnly)
  const lp = src('components/LivePortfolio.tsx')
  check('P1 PORT uses the policy for the chip, toggle and liquidate', lp.includes('executionPolicy(status)') && lp.includes('policy.modeLabel')
    && lp.includes('policy.liveSelectable') && lp.includes('policy.liquidateAllowed'))
  check('P1 the policy reads the server status, never the placeholder', !lp.includes('executionPolicy(s)') && !lp.includes('executionPolicy(defaultStatus)'))
  check('P1 refresh: a positions / orders failure never drops a good status', lp.includes('Promise.allSettled([') && !/await Promise\.all\(\[\s*getExecutionStatus/.test(lp))
  check('P1 no invented KPIs without a status', lp.includes('{status && <KPIStrip status={status}') && lp.includes('{status && <DailyLossMeter status={status}'))
  check('P1 PORT money in Indian units, losses keep their sign (no ₹10.0K, no unsigned loss)', !lp.includes('toFixed(1)}K`')
    && !lp.includes("dailyPositive ? '+' : ''}₹") && lp.includes('const signedRs ='))
  check('P1 PORT header no longer prints the raw engine mode', !lp.includes(">{s.mode}</Chip>"))
  check('P1 LIVE confirm unreachable when paper only', lp.includes('showLiveConfirm && policy.liveSelectable'))
}

// ── 6. the ICICI login URL is never printed (C1-trader-ux-05) ───────────────────────────────────
{
  for (const f of ['components/LivePortfolio.tsx', 'components/PortfolioSummary.tsx']) {
    const s = src(f)
    check(`L1 ${f}: no login URL as text`, !/\{\s*(status|connectionStatus)\??\.login_url\s*\}/.test(s), f)
    check(`L1 ${f}: no login URL in an href`, !/href=\{[^}]*login_url/.test(s), f)
    check(`L1 ${f}: LOG IN TO ICICI opens it externally`, s.includes('LOG IN TO ICICI ↗') && /openExternal\(String\((status|connectionStatus)\.login_url\)\)/.test(s), f)
    check(`L1 ${f}: no login URL logged`, !/console\.\w+\([^)]*login_url/.test(s), f)
  }
  check('L1 BRKR: no absolute dev path in the copy', !src('components/PortfolioSummary.tsx').includes('/Users/'))
}

// ── 7. dim text contrast (C1-trader-ux-15): tokens live in news/format.ts and app/globals.css ──
{
  const lum = (h: string) => {
    const c = h.replace('#', '')
    const [r, g, b] = [0, 2, 4].map(i => parseInt(c.slice(i, i + 2), 16) / 255).map(v => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
  }
  const ratio = (a: string, b: string) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05) }
  const fmt = src('components/news/format.ts'), css = src('app/globals.css')
  const tok = (re: RegExp, s: string) => (s.match(re)?.[1] ?? '').toLowerCase()
  const dimTs = tok(/\bdim:\s*'(#[0-9a-fA-F]{6})'/, fmt), mutedTs = tok(/\bmuted:\s*'(#[0-9a-fA-F]{6})'/, fmt)
  const dimCss = tok(/--t-dim:\s*(#[0-9a-fA-F]{6})/, css), mutedCss = tok(/--t-muted:\s*(#[0-9a-fA-F]{6})/, css)
  const BG = ['#020304', '#05070a', '#0a0d13', '#0e121a', '#080b10']   // strip, bg, panel, panel2, table head
  if (dimTs === '#475063') {
    pending++
    console.log('PENDING T1 dim token still #475063 (2.3–2.5:1): apply patch requests PR-W2-UI-PAGES-1/2 (news/format.ts, app/globals.css)')
  } else {
    check('T1 dim text ≥ 4.5:1 on every terminal background', BG.every(b => ratio(dimTs, b) >= 4.5), BG.map(b => ratio(dimTs, b).toFixed(2)))
    check('T1 muted stays at least as bright as dim (hierarchy kept)', lum(mutedTs) >= lum(dimTs), [mutedTs, dimTs])
    check('T1 CSS variables mirror the TS tokens', dimCss === dimTs && mutedCss === mutedTs, [dimCss, dimTs, mutedCss, mutedTs])
  }
  check('T1 no hard-coded old dim hex in EQS', !src('components/StockTable.tsx').includes('#475063'))
}

// ── 8. EQS rows memoized, hover in CSS (C2-performance-01) ───────────────────────────────────────
{
  const s = src('components/StockTable.tsx')
  check('E1 memoized row component', s.includes('const StockRow = memo(function StockRow('))
  check('E1 no hover state on the table', !s.includes('setHovered') && !s.includes('onMouseEnter') && s.includes('hover:bg-[#131926]'))
  check('E1 stable callbacks for the rows', s.includes('const handleRowClick = useCallback(') && s.includes('const handleWatchToggle = useCallback('))
  check('E1 rows get only their own live value / flash / watched flag',
    // live program (reports/live_nse): the row's own live-service price first (a primitive, so the memo holds), the
    // monitor socket's value otherwise
    s.includes('live={livePx(stock.ticker) ?? liveQuotes[stock.ticker]?.ltp}') && s.includes('flash={flashMap[stock.ticker] ?? null}') && s.includes('watched={watched.has(stock.ticker)}'))
  check('E1 index ticks do not flash the table', s.includes('if (!tickers.has(sym)) return'))
  check('E1 CMP printed with exactly 2 decimals', s.includes('fmtFixed(price, 2)'))
  check('E1 incremental mount: a screenful first, the rest in transitions, all rows in the end',
    /const FIRST_ROWS = \d+/.test(s) && s.includes('n: g.n + CHUNK') && s.includes('startTransition(() => setGrow(') && s.includes('limit >= displayed.length ? displayed : displayed.slice(0, limit)'))
}

// ── 9. COMP in two windows (C3-logic-unchanged-02) ─────────────────────────────────────────────
{
  check('M1 add', JSON.stringify(S.compareAdd(['TCS'], 'infy')) === '["TCS","INFY"]')
  const eight = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']
  check('M1 add: no duplicate, cap 8, same array when unchanged', S.compareAdd(['TCS'], 'TCS').length === 1 && S.compareAdd(eight, 'Z') === eight)
  check('M1 remove', JSON.stringify(S.compareRemove(['TCS', 'INFY'], 'TCS')) === '["INFY"]' && S.compareRemove(eight, 'Z') === eight)
  check('M1 sameList', S.sameList(['A', 'B'], ['A', 'B']) && !S.sameList(['A', 'B'], ['B', 'A']) && !S.sameList(['A'], ['A', 'B']))
  // two windows read [TCS, INFY, HCLTECH]; window 1 adds WIPRO (stored), window 2 later removes INFY
  const seed = ['TCS', 'INFY', 'HCLTECH']
  const stored1 = S.compareAdd(seed, 'WIPRO')
  const staleWrite = seed.filter(x => x !== 'INFY')                  // the old code: window 2's mount-time copy
  const merged = S.compareRemove(stored1, 'INFY')                    // the fix: the edit applies to the latest saved set
  check('M1 negative control: the stale write loses WIPRO', !staleWrite.includes('WIPRO'))
  check('M1 merge on write keeps both edits', JSON.stringify(merged) === '["TCS","HCLTECH","WIPRO"]', merged)
  const s = src('components/Compare.tsx')
  check('M1 Compare adopts external changes of its key', s.includes('useExternalPrefChange(COMP_KEY'))
  check('M1 Compare never echoes an adopted value', s.includes('if (v === stored.current) return'))
  check('M1 Compare edits merge on write', s.includes('compareAdd(latestSyms(), s)') && s.includes('compareRemove(latestSyms(), s)'))
}

// ── 10. copy polish (C1-trader-ux-18) ──────────────────────────────────────────────────────────
{
  const pipe = src('components/PipelineStudio.tsx')
  const steps = [...pipe.matchAll(/label: '([①②③④⑤⑥⑦⑧⑨])/g)].map(m => m[1])
  check('Y1 PIPE steps numbered once each', steps.length >= 5 && new Set(steps).size === steps.length, steps)
  check('Y1 no dev paths in RSK / DESK copy', !src('components/RiskDashboard.tsx').includes('read from CLAUDE.md')
    && !src('components/DecisionDesk.tsx').includes('charges from shared/trading_costs.py'))
  const EMOJI = /[\u{1F300}-\u{1FAFF}\u{26A1}]/u
  for (const f of ['components/StockTable.tsx', 'components/LivePortfolio.tsx', 'components/PortfolioSummary.tsx', 'components/MLEngineWorkspace.tsx',
    'components/PipelineStudio.tsx', 'components/SystemStatusWidget.tsx', 'components/ModelLab.tsx', 'components/LWScanner.tsx']) {
    check(`Y1 ${f}: kit glyphs, no emoji`, !EMOJI.test(src(f)), f)
  }
  const kit = src('components/terminal/index.tsx')
  check('Y1 kit fmtPct prints U+2212 for losses', kit.includes("r < 0 ? '\\u2212'"))
  check('Y1 CSV keeps ASCII minus', kit.includes('asciiMinus('))
  check("Y1 one crore casing ('cr')", !/toFixed\(2\)\} Cr`/.test(kit) && !src('components/OptionChain.tsx').includes(' Cr`'))
}

// ── 11. latest request wins on page hand-offs (CT-01: 'RELIANCE OMON' from another page showed NIFTY) ──────────
{
  const q = R.createRequestSeq()
  const a = q.begin(), b = q.begin()
  check('R1 only the newest request is current', !q.isCurrent(a) && q.isCurrent(b))
  q.cancel()
  check('R1 cancel drops every request in flight', !q.isCurrent(b))
  // the race: OMON mounts on NIFTY, the hand-off switches to RELIANCE in the same tick; RELIANCE answers first
  type Resp = { sym: string; resolve: () => void }
  const simulate = (guarded: boolean): string | null => {
    const seq = R.createRequestSeq()
    let data: string | null = null
    const pending: Resp[] = []
    const load = (sym: string) => {
      const mine = seq.begin()
      pending.push({ sym, resolve: () => { if (!guarded || seq.isCurrent(mine)) data = sym } })
    }
    load('NIFTY'); load('RELIANCE')
    pending[1].resolve()      // RELIANCE at .43
    pending[0].resolve()      // NIFTY at .46: the later answer
    return data
  }
  check('R1 the superseded NIFTY answer is dropped: the page ends on RELIANCE', simulate(true) === 'RELIANCE', simulate(true))
  check('R1 negative control: without the guard the later NIFTY answer won (the CT-01 bug)', simulate(false) === 'NIFTY')
  check('R1 hand-off key read before the first request', O.omonInitialSymbol('reliance') === 'RELIANCE' && O.omonInitialSymbol(null) === 'NIFTY'
    && O.omonInitialSymbol('  M&M ') === 'M&M' && O.omonInitialSymbol('BAJAJ-AUTO') === 'BAJAJ-AUTO'
    && O.omonInitialSymbol('<img src=x>') === 'NIFTY' && O.omonInitialSymbol('') === 'NIFTY')
  const oc = src('components/OptionChain.tsx')
  check('R1 OMON starts on the hand-off symbol', oc.includes('useState(() => omonInitialSymbol(readHandoff()))') && !oc.includes("useState('NIFTY')"))
  check('R1 OMON drops superseded chain responses (EOD, LIVE and the fallback)', (oc.match(/current\(\)/g) ?? []).length >= 4 && oc.includes('seq.begin(selection)'))
  check('R1 OMON clears the old chain on a symbol change', oc.includes('useEffect(() => { setData(null); setLiveNote(null); setPricer(null); setRolled(null) }, [symbol])'))
  // terminal v2: the IV history moved to components/vol/IvHistoryChart (useIvHistory); the guard moved with it
  const ivh = src('components/vol/IvHistoryChart.tsx')
  check('R1 OMON IV history ignores a stale symbol', oc.includes('useIvHistory(symbol') && ivh.includes('let alive = true') && (ivh.match(/if \(!alive\) return|if \(alive\)/g) ?? []).length >= 4)
  const dl = src('components/DealsMonitor.tsx')
  check('R1 DEAL starts on the hand-off window and ignores stale windows', dl.includes('useState(() => (readHandoff() ? 30 : 10))')
    && dl.includes('if (current) setData(r.data)') && dl.includes('return () => { current = false }'))
  const cp = src('components/Compare.tsx')
  check('R1 COMP keeps only the newest fetch', cp.includes('if (seq.isCurrent(mine)) setData(Object.fromEntries(got))'))
  const sb = src('components/StrategyBuilder.tsx')
  check('R1 OSTR keeps only the newest chain and analysis', sb.includes('if (!current()) return\n        setChain(r.data)') && sb.includes('if (current()) { setAnalysis(r.data)'))
  check('R1 DERV already guards every load (seq.current === mine)', (src('components/DerivativesDesk.tsx').match(/seq\.current === mine|seq\.current !== mine/g) ?? []).length >= 6)
}

// ── 12. OMON OI walls: the server's walls, never the biggest bar in the window (RUP-01 / CT-02) ────────────────
{
  // NIFTY live, 23 Oct: rows 21,250 … 23,950 (55 strikes); resistance [24000, 23500, 23000], support [21500, …]
  const strikes = Array.from({ length: 55 }, (_, i) => 21250 + 50 * i)
  const ce = strikes.map(k => (k === 23500 ? 1.92e7 : 1e6))      // the in-window call maximum is 23,500
  const marks = O.wallMarks(strikes, [24000, 23500, 23000], [21500, 22000])
  const call = marks.find(m => m.side === 'call')!, put = marks.find(m => m.side === 'put')!
  check('W1 call wall outside the window: an edge marker at 24,000, not a bar', call.at === 'right' && call.strike === 24000, call)
  check('W1 put wall inside the window: its own bar', put.at === 'bar' && put.at === 'bar' && (put as { index: number }).index === strikes.indexOf(21500), put)
  const fmtK = (v: number) => v.toLocaleString('en-IN')
  check('W1 edge marker says so', O.edgeLabel(call, fmtK) === 'CALL WALL 24,000 →', O.edgeLabel(call, fmtK))
  const oldArgmax = strikes[ce.reduce((b, v, i) => (v > ce[b] ? i : b), 0)]
  check('W1 negative control: the wave-2 chart labelled the in-window maximum (23,500) as the wall', oldArgmax === 23500 && call.strike !== oldArgmax)
  const left = O.wallMarks(strikes, [23000], [20000]).find(m => m.side === 'put')!
  check('W1 a put wall below the window: left edge marker', left.at === 'left' && O.edgeLabel(left, fmtK) === '← PUT WALL 20,000', left)
  const same = O.wallMarks(strikes, [22600], [22600])
  check('W1 one strike holding both walls: both on its bar', same.length === 2 && same.every(m => m.at === 'bar' && (m as { index: number }).index === strikes.indexOf(22600)))
  check('W1 no open interest on a side: no mark', O.wallMarks(strikes, [], [21500]).length === 1 && O.wallMarks(strikes, null, undefined).length === 0
    && O.wallMarks([], [24000], [21500]).length === 0)
  const gap = O.wallMarks([100, 110, 130], [120], []).find(m => m.side === 'call')!
  check('W1 a wall strike missing from the plotted strikes but inside them: positioned between', gap.at === 'between' && Math.abs((gap as { pos: number }).pos - 1.5) < 1e-9, gap)
  check('W1 ATM marker on the server ATM (the chain highlight), else the forward', O.atmIndex(strikes, 22600, 22612) === strikes.indexOf(22600)
    && O.atmIndex(strikes, null, 22612) === strikes.indexOf(22650) && O.atmIndex(strikes, 99999, null) === -1)
  const oc = src('components/OptionChain.tsx')
  check('W1 OiBars takes the walls from data.resistance / data.support', oc.includes('wallMarks(strikes, data.resistance, data.support)') && !oc.includes('const argmax'))
  check('W1 ATM line drawn at the bar centre (it sat on the bar edge)', oc.includes('x1={cx(atm)} x2={cx(atm)}'))
}

// ── 13. DESK momentum watchlist: every column at 1600, graceful at 1100 (CT-03) ─────────────────────────────
{
  // measured row widths (WebKit, 25 Oct): 1,569–1,572 px at the 1600 px window, 1,409–1,412 at 1440, 1,068–1,072 at the
  // 1100 px minimum; the table measured 973 px with live data (risk chips and event badges)
  check('D1 1600 window: watchlist beside the side panels, with room for the whole table',
    DL.deskWatchLayout(1569) === 'side' && DL.deskWatchLayout(1572) === 'side' && 1569 - DL.DESK_GAP - DL.DESK_SIDE_W >= DL.WATCH_TABLE_W)
  check('D1 1440 / 1100 windows: watchlist full width (the table fits the whole row)', DL.deskWatchLayout(1409) === 'stacked'
    && DL.deskWatchLayout(1412) === 'stacked' && DL.deskWatchLayout(1068) === 'stacked' && 1068 >= DL.WATCH_TABLE_W)
  check('D1 side by side only with room for the measured 973 px table', DL.WATCH_TABLE_W >= 973
    && [1409, 1412, 1440, 1569, 1572, 1700].every(w => DL.deskWatchLayout(w) === 'stacked' || w - DL.DESK_GAP - DL.DESK_SIDE_W >= 973))
  // negative control: the first cut (960) put the 1,412 px row side by side with 962 px for a 973 px table
  check('D1 negative control: a 960 px budget hid PROFIT Y/Y at 1440', 1412 >= 960 + DL.DESK_SIDE_W + DL.DESK_GAP && 1412 - DL.DESK_GAP - DL.DESK_SIDE_W < 973)
  check('D1 unmeasured or bogus width: stacked', DL.deskWatchLayout(0) === 'stacked' && DL.deskWatchLayout(NaN) === 'stacked')
  check('D1 grid templates', DL.deskGridColumns('side') === `minmax(0, 1fr) ${DL.DESK_SIDE_W}px` && DL.deskGridColumns('stacked') === 'minmax(0, 1fr)')
  // the wave-2 grid: 1.25fr of (1,569 − 10) = 866 px for a 1,033 px table → NEXT EVENT out of view
  const oldBox = Math.round((1569 - 10) * 1.25 / 2.25)
  check('D1 negative control: the old 1.25fr / 1fr grid gave the watchlist 866 px for a 1,033 px table', oldBox === 866 && oldBox < 1033)
  const heads = [{ label: '#', left: 0, right: 36 }, { label: 'STOCK', left: 36, right: 200 }, { label: 'NEXT EVENT', left: 840, right: 960 }, { label: 'P/E', left: 960, right: 1010 }]
  const hid = DL.hiddenHeaders(0, 866, heads)
  check('D1 out-of-view columns are named, in table order', JSON.stringify(hid) === JSON.stringify({ left: [], right: ['NEXT EVENT', 'P/E'] }), hid)
  check('D1 the cue', DL.hiddenColumnsCue(hid) === '⇢ scroll for NEXT EVENT, P/E' && DL.hiddenColumnsCue({ left: [], right: [] }) === ''
    && DL.hiddenColumnsCue(DL.hiddenHeaders(100, 1010, heads)) === '⇠ #, STOCK', DL.hiddenColumnsCue(DL.hiddenHeaders(100, 1010, heads)))
  check('D1 many hidden columns are summarised', DL.hiddenColumnsCue({ left: [], right: ['A', 'B', 'C', 'D', 'E'] }) === '⇢ scroll for A, B, C +2')
  const dd = src('components/DecisionDesk.tsx')
  check('D1 DESK uses the measured layout and names hidden columns', dd.includes('gridTemplateColumns: deskGridColumns(layout)') && dd.includes('data-testid="watch-hidden-cue"')
    && !dd.includes("gridTemplateColumns: 'minmax(0, 1.25fr) minmax(0, 1fr)'"))
  const order = ['rank', 'symbol', 'sector', 'close', 'ret6', 'ret12', 'event', 'pe', 'pat'].map(k => dd.indexOf(`{ key: '${k}', label:`, dd.indexOf('const watchCols')))
  check('D1 priority order: Last and Next event before the context columns', order.every((v, i) => v > 0 && (i === 0 || v > order[i - 1])), order)
  check('D1 Industry cut with an ellipsis (full name on hover)', dd.includes('maxWidth: INDUSTRY_MAX_W') && dd.includes('title={w.sector}'))
  check('D1 P/E at one decimal (was 17× next to 9.4×)', dd.includes('fmtFixed(fin[w.symbol].pe, 1)'))
}

// ── 14. COMP: remove the last symbol, then add (RUP-03) ─────────────────────────────────────────────
{
  const raw = JSON.stringify({ syms: ['TCS'], period: '1y' })
  // mount [TCS] (stored = raw), ✕ TCS → [] (an empty set is never written, storage still says TCS), add INFY
  check('M2 remove last, then add: only the new symbol', JSON.stringify(S.compareAdd(S.compareBase([], raw, raw), 'INFY')) === '["INFY"]')
  const oldBase = (shown: string[], r: string | null) => (r != null ? (JSON.parse(r).syms as string[]) : shown)
  check('M2 negative control: the wave-2 merge brought the removed TCS back', JSON.stringify(S.compareAdd(oldBase([], raw), 'INFY')) === '["TCS","INFY"]')
  const other = JSON.stringify({ syms: ['TCS', 'WIPRO'], period: '1y' })
  check('M2 another window wrote since: its set is the base (merge on write kept)', JSON.stringify(S.compareBase(['TCS'], other, raw)) === '["TCS","WIPRO"]')
  check('M2 an unreadable stored value never merges into the defaults', JSON.stringify(S.compareBase(['HDFCBANK'], '{oops', raw)) === '["HDFCBANK"]'
    && S.parseCompareSyms('{oops') === null && S.parseCompareSyms(null) === null && S.parseCompareSyms('{"syms":[1]}') === null)
  check('M2 nothing stored yet: this window\'s set', JSON.stringify(S.compareBase(['TCS', 'INFY'], null, null)) === '["TCS","INFY"]')
  check('M2 Compare uses it', src('components/Compare.tsx').includes('const latestSyms = () => compareBase(syms, readRaw(), stored.current)'))
}

// ── 15. EQS flashes always clear (RUP-04) ───────────────────────────────────────────────────────────
{
  // fake clock: timers fire in time order when the clock advances
  const makeClock = () => {
    let now = 0, id = 0
    const q = new Map<number, { at: number; fn: () => void }>()
    const timers = { set: (fn: () => void, ms: number) => { q.set(++id, { at: now + ms, fn }); return id }, clear: (h: unknown) => { q.delete(h as number) } }
    const advance = (to: number) => {
      for (;;) {
        const next = [...q.entries()].filter(([, t]) => t.at <= to).sort((a, b) => a[1].at - b[1].at)[0]
        if (!next) break
        q.delete(next[0]); now = next[1].at; next[1].fn()
      }
      now = to
    }
    return { timers, advance, size: () => q.size }
  }
  const c = makeClock(), cleared: string[] = []
  const fc = FC.createFlashClock(sym => cleared.push(sym), 700, c.timers)
  fc.flashed('TCS'); c.advance(300); fc.flashed('INFY')
  c.advance(700)
  check('F4 two ticks 300 ms apart: the first clears at 700 ms (it used to be cancelled by the second)', JSON.stringify(cleared) === '["TCS"]', cleared)
  c.advance(1000)
  check('F4 … and the second at 1,000 ms; nothing pending', JSON.stringify(cleared) === '["TCS","INFY"]' && fc.pending().length === 0 && c.size() === 0, cleared)
  fc.flashed('TCS'); c.advance(1500); fc.flashed('TCS'); c.advance(1900)
  check('F4 a new tick of the same symbol restarts only its own clear', cleared.length === 2 && fc.pending().join() === 'TCS')
  c.advance(2200)
  check('F4 restarted clear fires 700 ms after the latest tick', cleared.length === 3 && cleared[2] === 'TCS')
  fc.flashed('A'); fc.flashed('B'); fc.dispose(); c.advance(9999)
  check('F4 unmount cancels every pending clear', cleared.length === 3 && fc.pending().length === 0)
  // negative control: the old effect (one timer per batch, cancelled by the effect cleanup on the next batch)
  const o = makeClock(), oldCleared: string[] = []
  let cancel: (() => void) | null = null
  const oldEffect = (batch: string[]) => { cancel?.(); const h = o.timers.set(() => oldCleared.push(...batch), 700); cancel = () => o.timers.clear(h) }
  oldEffect(['TCS']); o.advance(300); oldEffect(['INFY']); o.advance(5000)
  check('F4 negative control: the old timer left TCS flashing for good', JSON.stringify(oldCleared) === '["INFY"]', oldCleared)
  const st = src('components/StockTable.tsx')
  check('F4 EQS uses the per-symbol clock, no batch timer in the effect cleanup', st.includes('flashClock.flashed(sym)') && !st.includes('return () => clearTimeout(timer)'))
  check('R9 a new result set mounts a screenful first again (same render)', st.includes('if (grow.of !== displayed) setGrow({ of: displayed, n: FIRST_ROWS })'))
  check('R9 rows get the IST day, so event badges re-render once a day', st.includes('today={today}') && st.includes('function useIstDay()'))
  check('E2 EQS P/E, ROCE and yield at fixed decimals (was 17 next to 10.4)', st.includes('fmtFixed(stock.pe_ratio, 1)') && st.includes('fmtFixed(stock.roce_pct, 1)')
    && st.includes('fmtFixed(stock.div_yld_pct, 2)') && !/\{fmt\(stock\.(pe_ratio|roce_pct|div_yld_pct)/.test(st))
  check('E2 EQS company · sector on one line (rows were two lines, ~50 px)', st.includes('· {stock.sector_name}') && !st.includes("<span className={clsx('text-[10px]', isDark ? 'text-slate-400' : 'text-gray-400')}>{stock.sector_name}</span>"))
}

// ── 16. no regex lookbehind in page chunks (RUP-07: WebKit < 16.4 cannot parse it) ───────────────────
{
  const noLookbehind = (rel: string) => !/\(\?<[=!]/.test(src(rel).replace(/^\s*(\/\/|\*).*$/gm, ''))
  for (const f of ['lib/format/index.ts', 'components/terminal/Markdown.tsx', 'components/terminal/mdInline.ts']) {
    check(`G1 ${f}: no lookbehind`, noLookbehind(f), f)
  }
  check('G1 grouping at the start, in brackets and back to back', F.indianGrouping('144,376 lots') === '1,44,376 lots'
    && F.indianGrouping('(144,376)') === '(1,44,376)' && F.indianGrouping('1,000,000 2,000,000') === '10,00,000 20,00,000'
    && F.indianGrouping('v1,234,567') === 'v12,34,567', [F.indianGrouping('(144,376)'), F.indianGrouping('1,000,000 2,000,000')])
  check('G1 decimals and already-Indian numbers untouched', F.indianGrouping('₹1,44,376.50 and 12,345.678') === '₹1,44,376.50 and 12,345.678')
  // the reader's inline tokens are unchanged on every report and doc (old pattern, lookbehind and all, runs in node)
  const OLD = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\)|(?<![\w*])\*[^*\s][^*]*\*(?!\w))/g
  const oldTokens = (t: string) => [...t.matchAll(OLD)].map(m => `${m.index}:${m[0]}`)
  const ROOT = path.resolve(UI, '..')
  const mdFiles: string[] = []
  const walk = (d: string, depth: number) => {
    if (depth > 6) return
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const p = path.join(d, e.name)
      if (e.isDirectory()) walk(p, depth + 1)
      else if (e.name.endsWith('.md') && fs.statSync(p).size < 2_000_000) mdFiles.push(p)
    }
  }
  for (const d of ['reports', 'docs']) if (fs.existsSync(path.join(ROOT, d))) walk(path.join(ROOT, d), 0)
  const extra = ['**bold** and *it* and a*b*c', '***x***', 'x *y* z', '2*3*4', '*a* *b*', '`*n*` [l](https://x.y) *i*', '**a** *b**c*']
  let lines = 0, diffs = 0, firstDiff = ''
  for (const t of [...extra, ...mdFiles.flatMap(f => fs.readFileSync(f, 'utf8').split('\n'))]) {
    lines++
    const a = oldTokens(t).join('|'), b = MD.inlineTokens(t).map(x => `${x.start}:${x.text}`).join('|')
    if (a !== b) { diffs++; if (!firstDiff) firstDiff = t.slice(0, 120) }
  }
  check(`G1 reader tokens identical to the lookbehind pattern on ${mdFiles.length} reports/docs (${lines} lines)`, diffs === 0 && mdFiles.length > 20, { diffs, firstDiff })
}

// ── 17. units, decimals and closed-market wording (C1-08 / CT-05 / CT-11 / C1-13 / C1-18) ─────────────
{
  const u = F.countUnit([1.13e7, 85.5e5, 8.5e5])
  check('U1 one unit for the DERV OI column (was 1.13 cr above 85.5 L)', u.suffix === ' L' && [1.13e7, 85.5e5, 8.5e5].map(v => F.fmtCount(v, u)).join('|') === '113.0 L|85.5 L|8.5 L',
    [1.13e7, 85.5e5, 8.5e5].map(v => F.fmtCount(v, u)))
  const c = F.countUnit([-24.9e5, 26.4e5, 1.1e5])
  check('U1 signed OI change: + and U+2212', [-24.9e5, 26.4e5, 1.1e5].map(v => F.fmtCount(v, c, true)).join('|') === `${MINUS}24.9 L|+26.4 L|+1.1 L`)
  check('U1 crore only above 100 cr; small counts plain', F.countUnit([2.5e9]).suffix === ' cr' && F.fmtCount(2.5e9, F.countUnit([2.5e9])) === '250.00 cr'
    && F.countUnit([4200]).suffix === '' && F.fmtCount(4200, F.countUnit([4200])) === '4,200' && F.fmtCount(null, u) === '—' && F.fmtCount(1, u) === '0.0 L')
  const ii = src('components/IndexIntraday.tsx')
  check('U2 index chart axis and prev tag at 2 dp (prev close 22,687.65 printed 22687.5)', ii.includes('precision: INDEX_PRICE_PRECISION') && ii.includes('INDEX_PRICE_PRECISION = PRICE_DP')
    && !/precision: index === 'INDIA VIX' \? 2 : 1/.test(ii) && F.PRICE_DP === 2)
  const mm = src('components/MarketMonitor.tsx')
  check('U2 MKT index tile and 200-DMA at 2 dp (was 21,428 vs BRF 21,427.60)', mm.includes('value={fmtIdx(b.index)}') && mm.includes('200-DMA ${fmtIdx(b.index_sma200)}'))
  const dv = src('components/DerivativesDesk.tsx')
  check('U3 DERV OI columns use one unit each and show it in the header', dv.includes('countUnit(term.legs.map(r => r.oi))') && dv.includes('fmtCount(r.oi_chg, chgU, true)'))
  check('CT-11 DERV rollover OI legs share one unit', dv.includes('const u = countUnit([c.near_oi, c.next_oi, c.far_oi])') && !dv.includes('value={`${oiFmt(c.near_oi)}`}')
    && [1.13e7, 85.5e5, 8.5e5].map(v => F.fmtCount(v, F.countUnit([1.13e7, 85.5e5, 8.5e5]))).join(' / ') === '113.0 L / 85.5 L / 8.5 L')
  check('U3 DERV axes: height-based ticks over the padded range, a % unit on the basis', dv.includes('axisTicks(lLo, lHi, chartH)') && dv.includes('lUnit="%"') && dv.includes('{fmtFixed(v, lAxis.dp)}{lUnit}'))
  check('U3 the basis axis now has more than 0 and 50 (−45 … +85)', C.niceTicks(-45, 85, 6).length >= 5 && C.niceTicks(-45, 85, 4).length === 2, [C.niceTicks(-45, 85, 6), C.niceTicks(-45, 85, 4)])
  check('W2 MOV: today in session, the session date when closed', F.sessionWord(true, '23-Oct-2026 16:00:00') === 'today' && F.sessionWord(undefined, null) === 'today'
    && F.sessionWord(false, '23-Oct-2026 16:00:00') === 'last session (23 Oct)' && F.sessionWord(false, '3-Nov-2026 09:00:00') === 'last session (03 Nov)'
    && F.sessionWord(false, 'garbage') === 'last session')
  const mv = src('components/LiveMovers.tsx')
  check('W2 MOV panels use the session word', mv.includes('subtitle={`${when} vs previous close · pick an index`}') && !mv.includes('subtitle="today vs previous close'))
  check('W2 WTCH: no "today" and no green 0 / 0 on a closed market', src('components/WatchMonitor.tsx').includes("marketOpen ? 'Up / down today' : 'Up / down · last session'"))
  check('W2 BRF subtitle clock in 24-hour IST', src('components/Brief.tsx').includes("hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })\n  const istHM"))
  const cp = src('components/Compare.tsx')
  check('Y2 COMP signed numbers through the kit (U+2212)', cp.includes('{fmtPct(r.ret, 1)}') && cp.includes('fmtPct(r.dd, 1, false)') && !cp.includes("r.ret >= 0 ? '+' : ''"))
  check('Y2 market map colours a value as printed (−0.03 → "0.0%" is not red)', src('components/MarketMap.tsx').includes("Number(g.avg.toFixed(1)) > 0 ? T.green : Number(g.avg.toFixed(1)) < 0 ? T.red : T.muted"))
  check('Y2 no colour emoji on WTCH / ALRT (CT-14)', !/[\u{1F300}-\u{1FAFF}]/u.test(src('components/WatchMonitor.tsx')) && !/[\u{1F300}-\u{1FAFF}]/u.test(src('components/AlertsCenter.tsx')))
  // CT-14: the header bell and the stock window's ALERT chip drew the Apple colour emoji; now the monochrome glyph
  for (const f of ['components/AlertsBell.tsx', 'components/terminal/ChartActions.tsx']) {
    check(`Y2 ${f}: monochrome bell glyph, no colour emoji`, !/\u{1F514}/u.test(src(f)) && src(f).includes('<BellGlyph'), f)
  }
  check('Y2 negative control: the emoji test sees the old bell', /\u{1F514}/u.test(src('components/terminal/ChartActions.tsx').replace('<BellGlyph /> ALERT', '\u{1F514} ALERT')))
  // C1-13: stock-window DES rows and MOV internals name the session they show instead of 'today'
  check('W3 session label: today vs the session date', F.sessionDayLabel('2026-10-25', '2026-10-25') === 'today'
    && F.sessionDayLabel('2026-10-23', '2026-10-25') === 'on 23 Oct' && F.sessionDayLabel('2026-11-08', '2026-11-09') === 'on 08 Nov'
    && F.sessionDayLabel(null, '2026-10-25') === 'today' && F.sessionDayLabel('23-Oct-2026', '2026-10-25') === 'today'
    && F.sessionDayLabel('2026-13-01', '2026-10-25') === 'today', [F.sessionDayLabel('2026-10-23', '2026-10-25'), F.sessionDayLabel('2026-11-08', '2026-11-09')])
  const prof = src('components/StockProfile.tsx')
  check('W3 DES turnover / delivery rows carry the session date, not "today"', !prof.includes('k="Turnover today') && !prof.includes('k="Delivery % today')
    && prof.includes('k={`Turnover ${day(px.date)} / 20d median`}') && prof.includes('k={`Delivery % ${day(px.date)} / 20d avg`}'))
  const mi = src('components/MarketInternals.tsx')
  check('W3 MOV internals: the session date and U+2212 in the net range', mi.includes('net range {sessionDayLabel(data?.day)} {fmtSigned(s.net_worst, 0)}')
    && !mi.includes('net range today {s.net_worst}'))
  check('W3 MEMB explained points signed with U+2212', src('components/IndexMembers.tsx').includes('they explain ${fmtSigned(d.explained_points, 1)} of'))
  check('Y2 no dev paths in CHRT / BRKR copy', !src('components/ChartStudio.tsx').includes('(lib/chartData.ts)</span>') && !src('components/PortfolioSummary.tsx').includes('icici_session_helper.py'))
  const cs = src('components/ChartStudio.tsx')
  check('Y2 CHRT RSI pane on the price pane\'s time axis (whitespace bars, equal axis widths)', cs.includes('(v == null ? { time: times[i] } : { time: times[i], value: v })')
    && (cs.match(/minimumWidth: PRICE_AXIS_W/g) ?? []).length === 2)
  check('Y2 stock-chart legend row reserved (no layout shift)', src('components/IndicatorPriceChart.tsx').includes('min-h-[23px] h-[23px]'))
  // C1-18: no hand-rolled `X >= 0 ? '+' : ''` + `X.toFixed(n)` left in the page files (it printed an ASCII '-' for losses)
  const EXPR = String.raw`[A-Za-z_][\w.!]*(?:\[[^\]\s]+\])?(?:[.!]\w+)*!?`
  const handRolled = new RegExp(String.raw`[{$]\{?(${EXPR}) (>=|>) 0 \? '\+' : ''\}\$?\{\1\.toFixed\(\d\)\}`)
  const SHELL = ['AlertsBell', 'CommandBar', 'ErrorCatcher', 'MarketCommandHeader', 'StockDetailModal']
  const pageFiles = fs.readdirSync(path.join(UI, 'components')).filter(f => f.endsWith('.tsx') && !SHELL.some(x => f.startsWith(x)))
  const left = pageFiles.filter(f => handRolled.test(src(`components/${f}`)))
  check(`Y3 signed numbers use fmtSigned / fmtPct in all ${pageFiles.length} page files`, left.length === 0 && pageFiles.length > 60, left)
  check('Y3 negative control: the pattern is detected', handRolled.test("{r.move_pct > 0 ? '+' : ''}{r.move_pct.toFixed(1)}") && handRolled.test("${d.change > 0 ? '+' : ''}${d.change.toFixed(1)}"))
  check('Y3 fmtSigned: U+2212 for losses, + for gains, grouping', F.fmtSigned(-24.94, 1) === `${MINUS}24.9` && F.fmtSigned(1234.5, 1) === '+1,234.5' && F.fmtSigned(0, 1) === '0.0')
}

// ── 18. round 4 (F4B-UI-PAGES): the rest of C1-18, P1, R11, P4, P5, P11, P12, CT-08, P16 ─────────────────────────
{
  // C1-18 remainder: ANY hand-rolled `? '+' : ''` sign (followed by toFixed, fmtNum, fmt, num, … all printed an ASCII
  // '-' for losses) in the page files and the kit's ChartActions. Shell-owned files are patch requests.
  const plusSign = /\?\s*(['"`])\+\1\s*:\s*(['"`])\2/
  const SHELL4 = ['AlertsBell', 'CommandBar', 'ErrorCatcher', 'MarketCommandHeader', 'StockDetailModal']
  const pages4 = fs.readdirSync(path.join(UI, 'components')).filter(f => /\.tsx?$/.test(f) && !SHELL4.some(x => f.startsWith(x)))
    .map(f => `components/${f}`).concat(['components/terminal/ChartActions.tsx', 'components/terminal/Markdown.tsx'])
  const signLeft = pages4.filter(f => plusSign.test(src(f)))
  check(`Y4 no hand-rolled '+' sign left in ${pages4.length} page files (was ~20 sites in 15 files)`, signLeft.length === 0 && pages4.length > 70, signLeft)
  check('Y4 negative control: the round-3 leftovers are detected', [
    "actual <span>{(d.change ?? 0) >= 0 ? '+' : ''}{d.change?.toFixed(1)} pts</span>",
    '{gift.change != null ? `${gift.change > 0 ? \'+\' : \'\'}${fmt(gift.change)}` : \'\'}',
    "const fPct = (n: number) => `${n >= 0 ? '+' : ''}${fNum(n)}%`",
    "({overlay.premium.pct > 0 ? '+' : ''}{fmtNum(overlay.premium.pct, 2)}%)",
  ].every(x => plusSign.test(x)) && !plusSign.test("`${v > 0 ? '+' : v < 0 ? '−' : ''}`"))
  check('Y4 the converted sites print U+2212 (fmtNum gave ASCII)', F.fmtSigned(-51.5, 2) === `${MINUS}51.50` && Number(-51.5).toLocaleString('en-IN', { minimumFractionDigits: 2 }) === '-51.50'
    && F.fmtSigned(-12.34, 1) === `${MINUS}12.3` && F.fmtSigned(-0.004, 2) === '0.00' && F.fmtSigned(null, 2) === '—')
  check('Y4 signed rupees: +₹ / −₹ / ₹0', F.fmtSignedInr(1234.4) === '+₹1,234' && F.fmtSignedInr(-144376) === `${MINUS}₹1,44,376` && F.fmtSignedInr(0.2) === '₹0'
    && F.fmtSignedInr(null) === '—', [F.fmtSignedInr(1234.4), F.fmtSignedInr(-144376)])
  const csvKit = src('components/terminal/index.tsx')
  check('Y4 CSV exports keep ASCII minus (the kit turns U+2212 back into "-")', csvKit.includes('asciiMinus(t.replace(') && F.asciiMinus(`${MINUS}51.50`) === '-51.50')

  // P1: the OMON guard lives in a ref, and a 30 s LIVE refresh never supersedes a slower answer for the same selection
  const ocs = src('components/OptionChain.tsx')
  check('P1 OMON guard in a ref (useRequestSeq), not useMemo', ocs.includes('const seq = useRequestSeq()') && !ocs.includes('useMemo(createRequestSeq'))
  const memoLeft = fs.readdirSync(path.join(UI, 'components')).filter(f => f.endsWith('.tsx') && src(`components/${f}`).includes('useMemo(createRequestSeq'))
  check('P1 no page keeps a request guard in useMemo', memoLeft.length === 0, memoLeft)
  const useSeq = src('components/useRequestSeq.ts')
  check('P1 useRequestSeq: one guard per mount in a ref, cancelled on unmount', useSeq.includes('useRef<RequestSeq | null>(null)') && useSeq.includes('useEffect(() => () => seq.cancel(), [seq])'))
  check('P1 OMON refresh skips a tick while the same selection is in flight', ocs.includes('if (refresh && seq.busy(selection)) return')
    && ocs.includes('setInterval(() => load(true), 30_000)') && ocs.includes('void run.finally(() => seq.settle(mine))'))
  {
    const q = R.createRequestSeq()
    const a = q.begin('NIFTY|x|live')
    check('P1 busy while in flight, not after settle', q.busy('NIFTY|x|live') && !q.busy('RELIANCE|x|live') && (q.settle(a), !q.busy('NIFTY|x|live')))
    const b = q.begin('NIFTY|x|live'); const c = q.begin('RELIANCE|x|live'); q.settle(b)
    check('P1 settling a superseded token changes nothing', q.busy('RELIANCE|x|live') && !q.isCurrent(b) && q.isCurrent(c))
    q.cancel()
    check('P1 cancel: nothing busy, nothing current', !q.busy('RELIANCE|x|live') && !q.isCurrent(c))
  }
  // OMON LIVE with a 30 s refresh against a slow backend (event-driven, fake clock)
  const simOmon = (o: { guardRefresh: boolean; liveMs: number; liveFails: boolean; eodMs: number; until: number }) => {
    const seq = R.createRequestSeq()
    let data = null as string | null, note = null as string | null, now = 0
    const evs: { t: number; fn: () => void }[] = []
    const at = (t: number, fn: () => void) => { evs.push({ t, fn }) }
    const sel = 'NIFTY||live'
    const load = (refresh: boolean) => {
      if (refresh && o.guardRefresh && seq.busy(sel)) return
      const mine = seq.begin(sel), current = () => seq.isCurrent(mine), settle = () => seq.settle(mine)
      at(now + o.liveMs, () => {
        if (!o.liveFails) { if (current()) { data = `live@${now}`; note = null } settle(); return }
        if (!current()) { settle(); return }
        note = 'live chain unavailable: showing end of day'
        at(now + o.eodMs, () => { if (current()) data = `eod@${now}`; settle() })
      })
    }
    load(false)
    for (let t = 30_000; t <= o.until; t += 30_000) at(t, () => load(true))
    while (evs.length) {
      evs.sort((x, y) => x.t - y.t)
      const e = evs.shift()!
      if (e.t > o.until) break
      now = e.t; e.fn()
    }
    return { data, note }
  }
  const slow = simOmon({ guardRefresh: true, liveMs: 35_000, liveFails: false, eodMs: 0, until: 150_000 })
  check('P1 a 35 s live answer with a 30 s refresh is shown', slow.data !== null && slow.data.startsWith('live@'), slow)
  check('P1 negative control: the round-3 code dropped every answer slower than 30 s', simOmon({ guardRefresh: false, liveMs: 35_000, liveFails: false, eodMs: 0, until: 150_000 }).data === null)
  const fb = simOmon({ guardRefresh: true, liveMs: 40_000, liveFails: true, eodMs: 5_000, until: 150_000 })
  check('P1 live failing at 40 s falls back to end of day with the note (and each refresh retries live)', fb.data !== null && fb.data.startsWith('eod@') && fb.note !== null, fb)
  const fbOld = simOmon({ guardRefresh: false, liveMs: 40_000, liveFails: true, eodMs: 5_000, until: 150_000 })
  check('P1 negative control: the round-3 code showed neither the fallback nor the note', fbOld.data === null, fbOld)
  check('P1 a fast answer still refreshes every 30 s', simOmon({ guardRefresh: true, liveMs: 3_000, liveFails: false, eodMs: 0, until: 95_000 }).data === 'live@93000')
  for (const f of ['components/Compare.tsx', 'components/StrategyBuilder.tsx', 'components/AlphaDiscoveryDesk.tsx']) {
    check(`P1 ${f}: request guard from useRequestSeq`, src(f).includes('useRequestSeq()'), f)
  }

  // R11: DERV ticks over the padded range, about one per 30 px of chart height, never fewer than 3
  const basis = C.axisTicks(-38.28 - 6.47, 69.54 + 6.47, 216)      // NIFTY basis_ann_pct 23 Oct, padded 6 %
  check('R11 the NIFTY basis axis has negative labels and ≥ 5 ticks', basis.ticks.some(v => v < 0) && basis.ticks.length >= 5, basis.ticks)
  check('R11 negative control: 4 ticks over the unpadded range gave 2 labels (50 and 0)', C.niceTicks(-45, 85, 4).length === 2)
  const short = C.axisTicks(0, 1.1, 122)
  check('R11 at least 3 ticks on a short chart', short.ticks.length >= 3 && C.axisTicks(9, 11, 60).ticks.length >= 3, [short.ticks, C.axisTicks(9, 11, 60).ticks])
  check('R11 tick count follows the chart height (8 at most)', C.axisTicks(0, 100, 400).ticks.length <= 9 && C.axisTicks(0, 100, 400).ticks.length > C.axisTicks(0, 100, 100).ticks.length)
  check('R11 a range that crosses zero always labels 0 (the zero line the basis is read against)', [[-7.3, 73.8], [-44.75, 76.01], [-0.6, 0.95], [-12, 3]]
    .every(([lo, hi]) => C.axisTicks(lo, hi, 216).ticks.includes(0)), [[-7.3, 73.8], [-0.6, 0.95]].map(([lo, hi]) => C.axisTicks(lo, hi, 216).ticks))

  // P4: error_kind on BRKR / PORT / BRIEF
  check('P4 kind from a reply: null connected, unknown for missing / odd', IC.iciciErrorKind({ connected: true, error_kind: null }) === null
    && IC.iciciErrorKind({ connected: false, error_kind: 'network' }) === 'network' && IC.iciciErrorKind({ connected: false }) === 'unknown'
    && IC.iciciErrorKind({ connected: false, error_kind: 'session_expired' }) === 'unknown' && IC.iciciErrorKind(null) === null)
  check('P4 the first known kind wins (summary before connection-status)', IC.pickErrorKind({ connected: false }, { connected: false, error_kind: 'network' }) === 'network'
    && IC.pickErrorKind({ connected: false, error_kind: 'expired' }, { connected: false, error_kind: 'network' }) === 'expired'
    && IC.pickErrorKind(null, undefined) === null && IC.pickErrorKind({ connected: false }, null) === 'unknown')
  const net = IC.iciciIssue('network')
  check('P4 network: "ICICI unreachable (network) — your session may still be valid", no login advice', net.headline === 'ICICI unreachable (network) — your session may still be valid'
    && !net.suggestLogin && !/\/login/.test(`${net.headline} ${net.detail}`) && net.chip === 'ICICI UNREACHABLE')
  const exp = IC.iciciIssue('expired', { fallback: 'The ICICI session has expired or is invalid.' })
  check('P4 expired unchanged: server text, login offered', exp.headline === 'The ICICI session has expired or is invalid.' && exp.suggestLogin && exp.chip === 'NOT CONNECTED')
  const cred = IC.iciciIssue('credentials', { keyMissing: true }), rej = IC.iciciIssue('credentials', { keyMissing: false })
  check('P4 credentials: key / secret missing (or rejected), the key form, no login', /missing/.test(cred.headline) && /rejected/.test(rej.headline) && /BRKR/.test(cred.detail ?? '') && cred.showCredentials && !cred.suggestLogin)
  check('P4 unknown keeps the old wording and the login', IC.iciciIssue('unknown', { fallback: '' }).suggestLogin && IC.iciciIssue('unknown').chip === 'NOT CONNECTED')
  check('P4 BRIEF line per kind (old text for expired / unknown)', IC.briefSessionLine(null) === 'connected' && IC.briefSessionLine('network').startsWith('ICICI unreachable (network)')
    && IC.briefSessionLine('expired') === 'expired: log in (Broker tab) or enable TOTP auto-login' && IC.briefSessionLine('unknown') === IC.briefSessionLine('expired'))
  const oldBrkr = (_kind: string) => 'Or send /login to the Telegram bot'      // round 3: the line was unconditional
  check('P4 negative control: before, a network outage still said "send /login"', /\/login/.test(oldBrkr('network')) && !net.suggestLogin)
  const brkr = src('components/PortfolioSummary.tsx'), port = src('components/LivePortfolio.tsx'), brf = src('components/Brief.tsx')
  check('P4 BRKR: kind first, /login advice only when a login can help', brkr.includes('pickErrorKind(summary, connectionStatus)')
    && brkr.includes("{(issue?.suggestLogin ?? true) && !totp?.login_running && <div style={{ marginTop: 4, color: T.muted }}>Or send /login") && brkr.includes('data-icici-kind="network"')   // gold program: no /login advice while a login is already running
    && brkr.includes('{connectionStatus?.login_url && issue?.suggestLogin !== false && ('))
  check('P4 PORT banner: network / credentials wording, no login form for them', port.includes('const kind = iciciErrorKind(status)') && port.includes('{!issue && status.login_url && (')
    && port.includes("{!issue && <div className=\"flex gap-2\">"))
  check('P4 BRIEF System line from the kind', brf.includes('briefSessionLine(brokerKind)') && !brf.includes("broker.data?.connected ? 'connected' : 'expired: log in"))

  // P5: MOV keeps polling while the client's NSE clock says OPEN
  const istMs = (iso: string) => Date.parse(`${iso}+05:30`)
  const openMon = SE.nseSession(istMs('2026-10-26T09:20:00')).state === 'OPEN', sun = SE.nseSession(istMs('2026-10-25T11:00:00')).state === 'OPEN'
  check('P5 poll after a "closed" reply once the session opens (Mon 09:20 IST)', openMon && PM.moversPollDue(false, openMon))
  check('P5 no poll on a closed Sunday after a "closed" reply', !sun && !PM.moversPollDue(false, sun) && PM.moversPollDue(true, false) && PM.moversPollDue(undefined, false))
  const oldMovRule = (serverOpen: boolean | undefined) => serverOpen !== false      // round 3: `if (data?.market_open !== false) load()`
  check('P5 negative control: the old rule never polled again after a "closed" reply, even at 09:20', !oldMovRule(false) && openMon)
  check('P5 MOV wires the clock in', src('components/LiveMovers.tsx').includes("moversPollDue(data?.market_open, nseSession(Date.now()).state === 'OPEN')"))

  // P11: the alert form shows the saved levels once they arrive; typed text wins
  const empty = { up: '', down: '', move: '' }
  const filled = PM.alertFormFill(empty, {}, { above: 3450, below: 3180, move: 5 })
  check('P11 saved levels fill the form after the first server read', filled.up === '3450' && filled.down === '3180' && filled.move === '5', filled)
  const typed = PM.alertFormFill({ up: '3500', down: '', move: '' }, { up: true }, { above: 3450, below: 3180, move: null })
  check('P11 a box the user typed in keeps its text; the others take the saved levels', typed.up === '3500' && typed.down === '3180' && typed.move === '', typed)
  check('P11 no saved levels: the form is unchanged (same object)', PM.alertFormFill(empty, {}, undefined) === empty && PM.alertFormFill(empty, {}, {}) === empty)
  check('P11 negative control: useState(initial) alone kept the empty boxes', ((cur?: { above?: number }) => (cur?.above ? String(cur.above) : ''))(undefined) === '')
  const ca = src('components/terminal/ChartActions.tsx')
  check('P11 ChartActions refills untouched boxes when the levels arrive', ca.includes('setFields(f => alertFormFill(f, touched.current, cur))') && ca.includes('touched.current[k] = true'))

  // P12: ALFA scans with the value just chosen
  const al = src('components/AlphaDiscoveryDesk.tsx')
  check('P12 scan-mode buttons pass the new mode', al.includes('onClick={() => { setScanMode(m); doScan(true, { mode: m }) }}') && !al.includes('setTimeout(() => doScan(true), 0)'))
  check('P12 knobs: the scan reads the new value from the ref, not a stale closure', al.includes('const next = { ...scanArgs.current.params, [name]: v }')
    && al.includes('const args = { ...scanArgs.current, ...over }') && al.includes('}, [addToast, scanSeq])'))
  check('P12 only the newest scan is shown', al.includes('if (!scanSeq.isCurrent(mine)) return\n      setScan(res.data)'))

  // P16: INSD 'Who' order, MKT wording, map chip, EQS columns, BTST IST stamp
  check('P16 INSD categories in one order whatever DuckDB returns', PM.orderCategories('Promoter Group, Promoter') === 'Promoter, Promoter Group'
    && PM.orderCategories('Promoter, Promoter Group') === 'Promoter, Promoter Group' && PM.orderCategories('KMP, Director, Promoter and Director') === 'Promoter and Director, Director, KMP'
    && PM.orderCategories(null) === '' && PM.orderCategories('Zeta, Alpha') === 'Alpha, Zeta')
  const rawA: string = 'Promoter Group, Promoter', rawB: string = 'Promoter, Promoter Group'
  check('P16 negative control: the raw strings differ between refreshes', rawA !== rawB && PM.orderCategories(rawA) === PM.orderCategories(rawB))
  check('P16 INSD renders the ordered list', src('components/InsiderMonitor.tsx').includes('{orderCategories(r.categories)}'))
  const mk = src('components/MarketMonitor.tsx')
  check('P16 MKT names the EOD session instead of "today"', mk.includes('const day = sessionDayLabel(data.as_of)') && mk.includes('${pct(b.index_chg_pct)} ${day} · 200-DMA')
    && !mk.includes("today · 200-DMA") && !mk.includes('empty="None today"') && mk.includes('changed from ${d.regime.changed_from} ${sessionDayLabel(d.as_of)}'))
  check('Y4 MKT server sentences (regime detail, yield-gap range) print U+2212', mk.includes('{unicodeMinus(String(c.detail ?? ""))}')
    && src('components/IndexValuation.tsx').includes('{unicodeMinus(`median ${s.median} · middle half ${s.p25} to ${s.p75}`)}')
    && F.unicodeMinus('ratio 0.56 · NH−NL 10d avg -73') === `ratio 0.56 · NH−NL 10d avg ${MINUS}73` && F.unicodeMinus('median -2.45 · middle half -2.69 to -2.18') === `median ${MINUS}2.45 · middle half ${MINUS}2.69 to ${MINUS}2.18`)
  check('Y4 BRF / SEAG / FUND / ALRT / WRAP negatives with U+2212 (a DOM scan found ASCII "-" there)',
    src('components/Brief.tsx').includes('net {fmtSigned(sm.net_worst, 0)} … +{Math.max(0, sm.net_best ?? 0)} {sessionDayLabel(internals.data?.day)}')
    && (src('components/Seasonality.tsx').match(/fmtFixed\((v|m\.avg), 1\)/g) ?? []).length === 2 && !/\.toFixed\(1\)\}%?<\/span> \},/.test(src('components/FundamentalsScreen.tsx'))
    && (src('components/FundamentalsScreen.tsx').match(/fmtFixed\(r\.(pe|pb|pat_margin|margin), 1\)/g) ?? []).length === 6
    && src('components/AlertsCenter.tsx').includes("{unicodeMinus(String(n.body ?? ''))}") && src('components/DailyWrap.tsx').includes('<Markdown source={unicodeMinus(md)} />') && src('components/DailyWrap.tsx').includes("{unicodeMinus(String(w.teaser ?? ''))}"))
  check('Y4 unicodeMinus leaves Markdown syntax alone (lists, rules, tables, dates)', F.unicodeMinus('- item\n---\n|---|---|\n2026-10-23 (-0.39%)') === `- item\n---\n|---|---|\n2026-10-23 (${MINUS}0.39%)`)
  check('P16 market-map chip says LAST SESSION on a weekend / before the open', src('components/MarketMap.tsx').includes("todayMatters() ? 'TODAY' : 'LAST SESSION'"))
  const st = src('components/StockTable.tsx')
  check('CT-08 EQS: star first, no duplicate HEALTH column, 8 px less padding, no 1,400 px floor', !st.includes('>Health</th>') && !st.includes('min-w-[1400px]')
    && st.indexOf('title="Watchlist">★</th>') < st.indexOf("toggleSort('ticker')") && !/'px-3 py-2 text-/.test(st) && !st.includes('"px-3 py-1.5'))
  check('CT-08 EQS names out-of-view columns', st.includes('hiddenColumnsCue(hiddenHeaders(b.left, b.right, heads))') && st.includes('data-eqs-cue'))
  check('P16 BTST file stamp in IST (21:40 IST is 16:10 UTC)', F.istFileStamp(new Date('2026-10-25T16:10:05Z')) === '2026-10-25-21-40-05'
    && F.istFileStamp(new Date('2026-10-25T20:00:00Z')) === '2026-10-26-01-30-00', F.istFileStamp(new Date('2026-10-25T16:10:05Z')))
  check('P16 negative control: the old toISOString stamp is UTC', new Date('2026-10-25T16:10:05Z').toISOString().slice(0, 19).replace(/[:T]/g, '-') === '2026-10-25-16-10-05')

  // DESK: the PM's in-page confirmation stays; Cancel is focused once, not on every re-render
  const dd = src('components/DecisionDesk.tsx')
  check('DESK re-enable asks in the page (ReenableConfirm), never window.confirm', dd.includes('<ReenableConfirm onCancel={() => setConfirmReenable(false)} onConfirm={reenable} />')
    && !/window\.confirm|\bconfirm\(/.test(dd.replace(/\/\/.*$/gm, '').replace(/\/\*[\s\S]*?\*\//g, '')))
  check('DESK confirm focuses Cancel once (it re-focused on every DESK re-render)', dd.includes("useEffect(() => { el?.querySelector<HTMLButtonElement>('[data-role=\"cancel-wrap\"] button')?.focus() }, [el])"))
}

console.log(`${passed} passed, ${failed} failed${pending ? `, ${pending} pending (patch requests)` : ''}`)
if (failed) process.exit(1)

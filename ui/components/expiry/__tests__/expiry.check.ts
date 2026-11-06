/**
 * W2-TAPE UI checks (reports/terminal_v2/PLAN.md 2.1 the intraday tape, 2.4 XPRY, M42 / m073 CHRT), every rule with a
 * negative control:
 *
 *  C  the tape chip: stored snapshots are DELAYED with their age at render time, never LIVE; none → OFFLINE.
 *  I  times are IST: the API's UTC stamps (+00:00) print 5 h 30 m later (the pilot panel printed 08:05 for 13:35).
 *  O  OI units: shares by default, contracts only with a lot; signed changes; "since the open" is honest about a late start.
 *  X  XPRY sentences: the decay-vs-curve read, the scorecard read, the expiry words; each ends "describes, does not predict".
 *  S  static scans of the new views: every kit <Panel carries source=; no `signal` badge; no bullish / bearish; the OI bars
 *     never use the green / red tokens (context is never coloured as direction, review m003).
 *  H  CHRT (M42 / m073): opens on the active symbol, EMA 200 on by default, instruments index / future / IV30 / OI.
 *
 * Run with plain node ≥ 22.6 (type stripping, no deps):
 *   node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON ui/components/expiry/__tests__/expiry.check.ts
 * Also type-checked by `cd ui && npx tsc --noEmit`. Exits non-zero on any failing check.
 */
import * as fs from 'node:fs'
import * as path from 'node:path'

type ModelMod = typeof import('../tapeModel')
type ChartMod = typeof import('../chartModel')
const M = (await import(new URL('../tapeModel.ts', import.meta.url).href)) as ModelMod
const CM = (await import(new URL('../chartModel.ts', import.meta.url).href)) as ChartMod

const UI = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..', '..')
const src = (rel: string) => fs.readFileSync(path.join(UI, rel), 'utf8')

let failed = 0
let passed = 0
function check(name: string, cond: unknown, extra?: unknown): void {
  if (cond) { passed++; return }
  failed++
  console.error(`FAIL ${name}${extra !== undefined ? ` :: ${JSON.stringify(extra)}` : ''}`)
}

// ── C. the tape chip ────────────────────────────────────────────────────────────────────────────────
{
  const now = Date.parse('2026-11-06T05:00:00Z')                       // 10:30 IST
  const chip = { state: 'delayed' as const, source: 'BREEZE', as_of: '2026-11-06T04:58:00+00:00', age_s: 5, hint: 'stored' }
  const s = M.tapeSource(chip, now)
  check('C1 a stored snapshot is DELAYED with its age recomputed at render time (120 s, not the API\'s 5 s)', s.state === 'delayed' && s.ageS === 120, s)
  check('C1 negative control: the chip is never LIVE, whatever the API sent', M.tapeSource({ ...chip, state: 'live' as never }, now).state === 'delayed')
  check('C2 no snapshot → OFFLINE with the reason', M.tapeSource({ ...chip, state: 'offline', as_of: null }, now).state === 'offline' && M.tapeSource(null, now).state === 'offline')
}

// ── I. IST times ────────────────────────────────────────────────────────────────────────────────────
{
  check('I1 the pilot\'s 08:05 UTC stamp is 13:35 IST', M.istClock('2026-11-05T08:05:00+00:00') === '13:35', M.istClock('2026-11-05T08:05:00+00:00'))
  check('I1 negative control: slicing the ISO string (the old panel) would read 08:05', '2026-11-05T08:05:00+00:00'.slice(11, 16) === '08:05')
  check('I2 minutes after 09:15 ↔ HH:MM', M.minuteLabel(0) === '09:15' && M.minuteLabel(375) === '15:30' && M.minuteOf('13:35') === 260 && M.minuteOf('x') === null)
}

// ── O. OI units and "since the open" ────────────────────────────────────────────────────────────────
{
  check('O1 shares by default (lakh above 1 L)', M.fmtOi(3_754_205, 65, false) === '37.5 L' && M.fmtOi(52_000, 65, false) === '52,000')
  check('O1 contracts only with a lot', M.fmtOi(3_754_205, 65, true) === '57,757' && M.fmtOi(3_754_205, null, true) === '37.5 L')
  check('O2 signed changes use the true minus', M.fmtSignedOi(-1_828_385, null, false) === '−18.3 L' && M.fmtSignedOi(200, null, false) === '+200')
  const late = M.sinceLabel('13:35')
  check('O3 a late first snapshot is named, never called the open', late.late && late.text.includes('13:35') && late.text.includes('started late'))
  check('O3 negative control: a 09:16 start is the open', !M.sinceLabel('09:16').late && M.sinceLabel('09:16').text.startsWith('since the open'))
  const u = M.unwindRead([{ strike: 1, ce_oi_open: 100, ce_oi: 60, pe_oi_open: 50, pe_oi: 50 } as never, { strike: 2, ce_oi_open: 100, ce_oi: 40, pe_oi_open: null, pe_oi: 25 } as never])
  check('O4 the unwind totals (calls −50 %, puts +50 % on the stored sides)', u.cePct === -50 && u.ceNow === 100 && u.peOpen === 50 && u.pePct === 50, u)
}

// ── X. XPRY sentences ───────────────────────────────────────────────────────────────────────────────
{
  const r = M.decayVsCurve({ minute: 240, today_pct: 35, median_pct: 52, p25: 44, p75: 61, n: 26 })
  check('X1 decay vs the curve: where today sits, ends with describes', !!r && r.includes('13:15') && r.includes('below the 25th percentile') && r.endsWith('Describes, does not predict.'), r)
  check('X1 inside the middle half', M.decayVsCurve({ minute: 240, today_pct: 50, median_pct: 52, p25: 44, p75: 61, n: 26 })?.includes('inside the middle half'))
  check('X1 negative control: nothing to compare → null', M.decayVsCurve(null) === null)
  const sr = M.scoreRead({ n: 26, exceeded_pct: 58, fair_exceeded_pct: 42.5, median_ratio: 1.12, compared: 26, implied_closer: 17 })
  check('X2 the scorecard read names the comparison, repeats no stat number (same number once per page), before costs', sr.includes('more often than')
    && !/\d/.test(sr.replace('RV20', 'RV')) && sr.includes('Before costs') && sr.endsWith('describes, does not predict.'), sr)
  check('X2 about-fair wording near the reference', M.scoreRead({ n: 10, exceeded_pct: 45, fair_exceeded_pct: 42.5 }).includes('about as often as'))
  check('X2 negative control: no row → says so', M.scoreRead({ n: 0 }).startsWith('No scored expiry yet'))
  check('X3 expiry words on and off an expiry day', M.expiryWords({ is_expiry_day: false, next_expiry: '2026-11-09', symbol: 'NIFTY', date: '2026-11-06' }).includes('the next is Mon 2026-11-09')
    && M.expiryWords({ is_expiry_day: true, next_expiry: '2026-11-17', symbol: 'NIFTY', date: '2026-11-09' }).includes('expires today'))
  const fr = [{ ts: 'a', ist: '09:16', ce: [1], pe: [2] }, { ts: 'b', ist: '09:18', ce: [3], pe: [4] }]
  check('X5 API phrases start a sentence capitalised', M.sentence('the tape snaps NIFTY') === 'The tape snaps NIFTY' && M.sentence(null) === '')
  check('X4 the time-lapse frame clamps', M.frameAt(fr, 9)?.ist === '09:18' && M.frameAt(fr, -3)?.ist === '09:16' && M.frameAt([], 0) === null)
}

// ── S. static scans of the new views ────────────────────────────────────────────────────────────────
{
  const dir = path.join(UI, 'components', 'expiry')
  const files = fs.readdirSync(dir).filter(f => f.endsWith('.tsx')).map(f => `components/expiry/${f}`)
  const panelTags = (s: string) => {
    const out: string[] = []
    const re = /<Panel\b/g
    let m: RegExpExecArray | null
    while ((m = re.exec(s))) {
      let depth = 0, i = m.index
      for (; i < s.length; i++) {
        const ch = s[i]
        if (ch === '{') depth++
        else if (ch === '}') depth--
        else if (ch === '>' && depth === 0) break
      }
      out.push(s.slice(m.index, i + 1))
    }
    return out
  }
  const missing = files.flatMap(f => panelTags(src(f)).filter(t => !/\bsource=\{/.test(t)).map(t => `${f}: ${t.slice(0, 60)}`))
  check('S1 every Panel in components/expiry carries source=', missing.length === 0, missing)
  check('S1 negative control: the scanner flags a bare Panel', panelTags('<Panel title="x">b</Panel>').filter(t => !/\bsource=\{/.test(t)).length === 1)
  check('S2 no signal badge in the new views', files.every(f => !/badge(?:=|:\s*)["']signal["']/.test(src(f))))
  check('S3 no bullish / bearish words', files.every(f => !/\b(bullish|bearish)\b/i.test(src(f))))
  check('S3 negative control: the scan sees the word', /\b(bullish|bearish)\b/i.test('a bullish read'))
  const charts = src('components/expiry/charts.tsx')
  check('S4 the OI bars use the neutral palette (calls cyan, puts violet), never green / red', /CALL_COLOR = T\.cyan/.test(charts) && /PUT_COLOR = T\.violet/.test(charts)
    && !/T\.(green|red)/.test(charts) && !/T\.(green|red)/.test(src('components/expiry/OiTape.tsx')) && !/T\.(green|red)/.test(src('components/expiry/ExpiryDay.tsx')))
  check('S5 the tape never hand-builds a LIVE chip', !/state: 'live'/.test(src('components/expiry/OiTape.tsx')) && !/state: 'live'/.test(src('components/expiry/tapeModel.ts')))
  check('S6 the tape prints IST times from the API (no ISO slicing)', !/\.slice\(11, 16\)/.test(src('components/expiry/OiTape.tsx')))
  check('S7 XPRY reads and writes the active symbol', /useActiveSymbol\(\)/.test(src('components/expiry/ExpiryDay.tsx')) && /setActive\(\{ symbol: s \}\)/.test(src('components/expiry/ExpiryDay.tsx')))
}

// ── H. CHRT (M42 / m073) ────────────────────────────────────────────────────────────────────────────
{
  const cs = src('components/ChartStudio.tsx')
  check('H1 CHRT opens on the active symbol (m073 / M34), not a hard-coded RELIANCE', /useActiveSymbol\(\)/.test(cs) && !/symbol: symbolProp = 'RELIANCE'/.test(cs))
  check('H1 negative control: the old default is gone', !cs.includes("ChartStudio({ symbol: symbolProp = 'RELIANCE' }"))
  check('H2 EMA 200 is on by default (m073)', /ema200: true/.test(cs))
  check('H3 CHRT charts an index, the near future, IV30 and OI (M42)', ['index', 'future', 'iv'].every(k => cs.includes(`'${k}'`)) && cs.includes('fetchInstrument') && cs.includes('OI'))
  check('H4 an intraday bar after 15:30 is never drawn (the session ends at 15:30)', cs.includes('inSession(r.bars)'))
  const bars = [{ t: '09:14' }, { t: '09:15' }, { t: '15:30' }, { t: '15:45' }]
  check('H4 inSession keeps 09:15–15:30 only', CM.inSession(bars).map(b => b.t).join(',') === '09:15,15:30')
  check('H4 negative control: a morning bar is kept', CM.inSession([{ t: '10:00' }]).length === 1)
  const pts = [{ t: '2026-10-30', iv30: 12 }, { t: '2026-11-02', iv30: 13 }, { t: '2026-11-05', iv30: null }]
  const al = CM.alignOverlay(pts, ['2026-10-29', '2026-10-30', '2026-11-02', '2026-11-03', '2026-11-05', '2026-11-30'], 'iv30')
  check('H5 overlays align bar-for-bar: as-of the bar, a null stays a gap, never carried > 10 days', JSON.stringify(al) === JSON.stringify([null, 12, 13, 13, null, null]), al)
  check('H5 negative control: a monthly bar takes the bucket\'s last value', CM.alignOverlay(pts.slice(0, 2), ['2026-11-06'], 'iv30')[0] === 13)
}

console.log(`expiry.check: ${passed} passed, ${failed} failed`)
if (failed) process.exit(1)

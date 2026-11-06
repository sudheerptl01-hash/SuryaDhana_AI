/**
 * Terminal v2, wave 1 UI checks (reports/terminal_v2/PLAN.md 0.6 / 1.1–1.4 / G9), every rule with a negative control:
 *
 *  S  source chips: `sourceOf` states (DELAYED date / STALE / OFFLINE / LIVE / GAP / INPUT / REFERENCE), NSE stamps, the
 *     intraday clock; a static scan that EVERY kit `<Panel` in ui/app + ui/components carries `source=` (the gold kit
 *     renders its own catalog lag chip and is checked for it instead).
 *  B  badges: context is the neutral tone; no new view ships a `signal` badge; no bullish / bearish wording.
 *  R  IV rank vs IV percentile on the R-IV-shaped fixture (rank 21 · percentile 60) — the old OMON "IV rank" was the
 *     percentile; OMON / VOL / the profile strip print both, each defined.
 *  V  the IV arithmetic (paid vs delivered, hit-rate, straddle vs 1σ, OSTR seeds from OMON strikes, term words).
 *  A  the active-symbol store: parse, newest-wins, a new symbol drops the old expiry / strikes, ≤ 4 strikes, corrupt values.
 *  D  drivers wording: the regime strip ends "describes, does not predict", the fit chip, the 60-session leader.
 *  H  SYS › DATA: worst-first order, n STALE, page filter, honest sentences, no score.
 *  T  unknown `?tab=` → a toast naming the release; GO aliases VOL / DATA / DRVR / IMAP / CONTRIB.
 *  P  page wiring: PCR / VIX neutral, MOV's two INTRADAY titles, the live today panel on MOV + BRF only, the horizon
 *     table on MEMB only, OPEN IN OSTR, the OSTR margin chip with the 4.8× error, the header DATA chip, VIX once.
 *
 * Run with plain node ≥ 22.6 (type stripping, no deps):
 *   node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON ui/components/vol/__tests__/terminal_v2.check.ts
 * Also type-checked by `cd ui && npx tsc --noEmit`. Exits non-zero on any failing check.
 */
import * as fs from 'node:fs'
import * as path from 'node:path'

type SourceMod = typeof import('../../terminal/source')
type VolMod = typeof import('../volModel')
type ActiveMod = typeof import('../../../lib/activeSymbolCore')
type DriversMod = typeof import('../../drivers/driversModel')
type HealthMod = typeof import('../../datahealth/healthModel')
type DeepMod = typeof import('../../../lib/deepLink')
type AliasMod = typeof import('../../../lib/goAliases')
type KeysMod = typeof import('../../../lib/prefs/keys')
const S = (await import(new URL('../../terminal/source.ts', import.meta.url).href)) as SourceMod
const V = (await import(new URL('../volModel.ts', import.meta.url).href)) as VolMod
const A = (await import(new URL('../../../lib/activeSymbolCore.ts', import.meta.url).href)) as ActiveMod
const D = (await import(new URL('../../drivers/driversModel.ts', import.meta.url).href)) as DriversMod
const H = (await import(new URL('../../datahealth/healthModel.ts', import.meta.url).href)) as HealthMod
const DL = (await import(new URL('../../../lib/deepLink.ts', import.meta.url).href)) as DeepMod
const GA = (await import(new URL('../../../lib/goAliases.ts', import.meta.url).href)) as AliasMod
const K = (await import(new URL('../../../lib/prefs/keys.ts', import.meta.url).href)) as KeysMod
type B76Mod = typeof import('../../../lib/black76')
const B = (await import(new URL('../../../lib/black76.ts', import.meta.url).href)) as B76Mod

const UI = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..', '..')
const src = (rel: string) => fs.readFileSync(path.join(UI, rel), 'utf8')

let failed = 0
let passed = 0
function check(name: string, cond: unknown, extra?: unknown): void {
  if (cond) { passed++; return }
  failed++
  console.error(`FAIL ${name}${extra !== undefined ? ` :: ${JSON.stringify(extra)}` : ''}`)
}

// ── S. source chips ────────────────────────────────────────────────────────────────────────────────
{
  const now = new Date('2026-11-05T16:30:00Z')                          // Thu 5 Nov 2026 22:00 IST
  const fresh = S.sourceOf('2026-11-04', { source: 'NSE F&O bhavcopy', now })
  // live program (reports/live_nse honesty rule): daily data reads EOD + its date (was 'DELAYED · 04 NOV'); still never a clock
  check('S1 a daily as-of inside max age: EOD with its date, never a clock', fresh.state === 'delayed' && S.sourceChipText(fresh, now).label === 'EOD · 04 NOV', S.sourceChipText(fresh, now))
  const old = S.sourceOf('2026-10-30', { source: 'NSE', now })
  check('S1 older than max age (4 d): STALE', old.state === 'stale' && S.sourceChipText(old, now).label === 'STALE · 30 OCT', S.sourceChipText(old, now))
  check('S1 negative control: the same date with a 10-day cap is not stale', S.sourceOf('2026-10-30', { now, maxAgeDays: 10 }).state === 'delayed')
  check('S1 no as-of: OFFLINE (never an invented date)', S.sourceOf(null, { now }).state === 'offline' && S.sourceChipText(S.sourceOf(null, { now })).label === 'OFFLINE')
  check('S1 live feed', S.sourceChipText(S.sourceOf('2026-11-05T10:00:00+05:30', { live: true, source: 'Breeze', now }), now).label === 'LIVE · BREEZE')
  check('S1 gap', S.sourceChipText(S.sourceOf('2026-11-04', { gap: true, now }), now).label === 'GAP · 04 NOV')
  const intraday = S.sourceOf('2026-11-05T21:42:00+05:30', { source: 'Yahoo', now })
  check('S1 an intraday as-of from today shows the feed and its IST clock', S.sourceChipText(intraday, now).label === 'DELAYED · YAHOO · 21:42', S.sourceChipText(intraday, now))
  check('S1 an intraday as-of from another day shows its date', S.sourceChipText(S.sourceOf('2026-11-03T15:30:00+05:30', { source: 'NSE', now, maxAgeDays: 9 }), now).label === 'DELAYED · 03 NOV')
  check('S1 INPUT and REFERENCE chips', S.sourceChipText(S.inputSource('your legs')).label === 'INPUT' && S.sourceChipText(S.referenceSource('rules')).label === 'REFERENCE'
    && S.sourceChipText(S.undatedSource('NSE calendar')).label === 'DELAYED · NSE CALENDAR')
  check('S2 NSE stamps → ISO with the IST offset', S.nseStampIso('23-Oct-2026 16:00:00') === '2026-10-23T16:00:00+05:30' && S.nseStampIso('05-NOV-2026') === '2026-11-05'
    && S.nseStampIso('2026-11-05 09:15') === '2026-11-05T09:15:00+05:30' && S.nseStampIso('2026-11-05') === '2026-11-05')
  check('S2 an unparsable stamp is null (the chip then reads OFFLINE)', S.nseStampIso('garbage') === null && S.nseStampIso('31-Foo-2026') === null && S.nseStampIso(null) === null)
  check('S3 sub-view URL helpers keep every other parameter', S.withSub('?tab=derivatives&sym=TCS', 'vol') === '?tab=derivatives&sym=TCS&sub=vol'
    && S.withSub('?tab=derivatives&sub=vol', null) === '?tab=derivatives' && S.subFromSearch('?sub=vol', ['desk', 'vol']) === 'vol' && S.subFromSearch('?sub=x', ['vol']) === null)

  // G9 static scan: every kit <Panel …> opening tag carries source= (the scanner itself is checked on a synthetic tag)
  const panelTags = (s: string): string[] => {
    const out: string[] = []
    for (const m of s.matchAll(/<Panel\b/g)) {
      let i = (m.index ?? 0) + 6, depth = 0, q: string | null = null
      for (; i < s.length; i++) {
        const c = s[i]
        if (q) { if (c === q) q = null }
        else if ((c === '"' || c === "'") && depth === 0) q = c
        else if (c === '{') depth++
        else if (c === '}') depth--
        else if (c === '>' && depth === 0) break
      }
      out.push(s.slice(m.index ?? 0, i + 1))
    }
    return out
  }
  const missing = (s: string) => panelTags(s).filter(t => !/\bsource=\{/.test(t))
  check('S4 scanner negative control: a bare <Panel title="x"> is flagged, one with source= is not',
    missing('<Panel title="x" right={<b>{a > b ? 1 : 2}</b>}>body</Panel>').length === 1 && missing('<Panel title="x" source={s}>b</Panel>').length === 0)
  const offenders: string[] = []
  const walk = (dir: string) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      if (e.name === 'node_modules' || e.name === '__tests__' || e.name.startsWith('.')) continue
      const p = path.join(dir, e.name)
      if (e.isDirectory()) walk(p)
      else if (p.endsWith('.tsx')) {
        const rel = path.relative(UI, p)
        if (rel === path.join('components', 'terminal', 'index.tsx')) continue
        const s = fs.readFileSync(p, 'utf8')
        const miss = missing(s)
        // the GOLD kit wraps the kit Panel and renders the gold catalog lag chip itself (gold PLAN §f)
        if (rel === path.join('components', 'gold', 'kit.tsx') && /<LagChipEl freshness=\{freshness\}/.test(s)) continue
        if (miss.length) offenders.push(`${rel} (${miss.length})`)
      }
    }
  }
  walk(path.join(UI, 'app')); walk(path.join(UI, 'components'))
  check('S4 G9: every Panel header on every page carries a SourceChip (source=)', offenders.length === 0, offenders)
  // the two local panel shells (CMDT, WHSE) take a required source and render the kit chip
  for (const f of ['components/CommodityTab.tsx', 'components/WarehouseHealth.tsx']) {
    const s = src(f)
    check(`S4 ${f}: the local Panel requires source and renders <SourceChip info={source} />`, /\n {2}source: SourceInfo\n/.test(s) && s.includes('<SourceChip info={source} />'))
  }
  // staleness never only in prose (PLAN 1.4): RSK broker book, WRAP archive, CMDT board, WTCH book
  check('S5 RSK: the broker book staleness is a chip, not "(stale)" in the subtitle', src('components/RiskDashboard.tsx').includes('<SourceChip info={brokerSrc} />') && !src('components/RiskDashboard.tsx').includes("> 24 ? ' (stale)' : ''"))
  check('S5 WRAP: the archive chip goes STALE when the 21:00 wrap is missed', /source=\{sourceOf\(list\[0\]\?\.date \?\? null, \{ source: 'daily_wrap 21:00 IST', maxAgeDays: 4 \}\)\}/.test(src('components/DailyWrap.tsx')))
  check('S5 CMDT: the board chip and a STALE mark per stale quote', src('components/CommodityTab.tsx').includes('<SourceChip info={boardSrc} />') && src('components/CommodityTab.tsx').includes('data-cmdt-stale'))
  check('S5 WTCH: the book chip says live ICICI vs the last-known file', src('components/WatchMonitor.tsx').includes("source: 'ICICI last-known book'") && src('components/WatchMonitor.tsx').includes('source={monitorSrc}'))
}

// ── B. badges and words ────────────────────────────────────────────────────────────────────────────
{
  check('B1 context is the neutral tone (never a buy / sell colour)', S.BADGES.context.tone === 'muted' && S.badgeSpec('context').label === 'CONTEXT')
  check('B1 negative control: signal is the only green badge', S.BADGES.signal.tone === 'green' && Object.values(S.BADGES).filter(b => b.tone === 'green').length === 1)
  check('B1 unknown badge falls back to context', S.badgeSpec('bogus').label === 'CONTEXT')
  check('B2 describes() appends once and is idempotent', S.describes('narrow breadth') === 'narrow breadth — describes, does not predict' && S.describes(S.describes('x')) === S.describes('x'))
  check('B2 the drivers model uses the same sentence', D.DESCRIBES === S.DESCRIBES && D.describes('a.') === S.describes('a.'))
  const newViews = ['components/vol', 'components/drivers', 'components/datahealth'].flatMap(d => fs.readdirSync(path.join(UI, d)).filter(f => /\.tsx?$/.test(f)).map(f => `${d}/${f}`))
  const signalUse = newViews.filter(f => /badge(?:=|:\s*)["']signal["']/.test(src(f)))
  check('B3 no new view ships a `signal` badge (none exists: PLAN §0.1)', signalUse.length === 0, signalUse)
  const dirWords = newViews.filter(f => /\b(bullish|bearish)\b/i.test(src(f).replace(/never (?:a colour or a direction word|bullish \/ bearish)|never .{0,30}bullish.{0,10}bearish/gi, '')))
  check('B3 no bullish / bearish wording on context (vol / drivers / data)', dirWords.length === 0, dirWords)
  check('B3 negative control: the word scan sees "bullish"', /\b(bullish|bearish)\b/i.test('IV rising is bullish'))
  const drv = src('components/drivers/DriversView.tsx')
  check('B4 the drivers views draw no green / red (context in the neutral token)', !/T\.(green|red)\b/.test(drv))
  check('B4 the regime strip is the neutral token', /data-driver-regime[\s\S]{0,200}borderLeft: `3px solid \$\{T\.muted\}`/.test(drv))
}

// ── R. IV rank vs IV percentile (R-IV §3: the old "IV rank 73" was a percentile) ───────────────────────
{
  // 252 sessions: 151 at 10 %, 100 at 20 %, one spike at 50 %; today 18.4 %
  const xs = [...Array(151).fill(10), ...Array(100).fill(20), 50]
  const today = 18.4
  const pctile = S.percentileOf(xs, today), rank = S.rankOf(xs, today)
  check('R1 percentile = share of the past year below today ≈ 60', pctile != null && Math.abs(pctile - 59.92) < 0.1, pctile)
  check('R1 rank = where today sits between the min and the max ≈ 21', rank != null && Math.abs(rank - 21) < 0.01, rank)
  const oldOmon = Math.round((xs.filter(v => v < today).length / xs.length) * 100)
  check('R1 negative control: the old OMON "IV rank" formula is the percentile, not the rank', oldOmon === 60 && Math.round(rank ?? 0) !== oldOmon)
  check('R1 too few sessions: neither is computed', S.percentileOf([1, 2, 3], 2) === null && S.rankOf([1, 2, 3], 2) === null && S.rankOf(xs, null) === null)
  const ivh = src('components/vol/IvHistoryChart.tsx')
  check('R2 OMON history prints BOTH chips, each defined on hover from the route definitions', ivh.includes('IV PERCENTILE') && ivh.includes('IV RANK')
    && ivh.includes('v2.definitions.iv_pctile_252') && ivh.includes('v2.definitions.iv_rank_252'))
  check('R2 the legacy fallback labels its number a percentile (Wave 0.6)', /aria-label="IV percentile">\s*IV PERCENTILE \{pct != null/.test(ivh))
  const oc = src('components/OptionChain.tsx')
  check('R2 OMON no longer prints "IV rank" for a percentile', !oc.includes('IV rank ${rank} (share of the past year below today)') && oc.includes('<IvHistoryChart'))
  check('R2 the VOL screener and the profile strip carry both columns', src('components/vol/VolView.tsx').includes("label: 'IV rank'") && src('components/vol/VolView.tsx').includes("label: 'IV pctile'")
    && src('components/vol/IvStrip.tsx').includes("cell('IV RANK'") && src('components/vol/IvStrip.tsx').includes("cell('IV PCTILE'"))
}

// ── V. IV arithmetic ──────────────────────────────────────────────────────────────────────────────
{
  const rows = [
    { date: '2026-09-01', spot: 100, monthly_expiry: '2026-09-29', monthly_atm_iv: 14, rv20_yz: 11, expected_move_1d_pct: 1 },
    { date: '2026-09-28', spot: 100.9, monthly_expiry: '2026-09-29', monthly_atm_iv: 13, rv20_yz: 12, expected_move_1d_pct: 1 },
    { date: '2026-09-30', spot: 103, monthly_expiry: '2026-10-27', monthly_atm_iv: 12, rv20_yz: 12.5, expected_move_1d_pct: 1 },
    { date: '2026-10-26', spot: 103.5, monthly_expiry: '2026-10-27', monthly_atm_iv: 15, rv20_yz: null, rv20_cc: 9, expected_move_1d_pct: 1 },
  ]
  // M02 (fix wave 2): the ledger is the server's (NSE monthlies, IV at ≈ 30 DTE, vol delivered over the option's own life);
  // the client only summarises closed months — the old client ledger (first expiry 20–60 d, trailing RV20 before expiry,
  // cc under a YZ header) is gone
  const ledger = [
    { expiry: '2026-09-29', open: false, paid_minus_delivered: -1.24 }, { expiry: '2026-10-27', open: false, paid_minus_delivered: 3.74 },
    { expiry: '2026-11-23', open: true, paid_minus_delivered: null },
  ]
  const ps = V.paidSummary(ledger)
  check('V1 paid vs delivered: the mean and the "paid above" count use closed months only', ps.closed === 2 && ps.open === 1 && ps.paid_above === 1 && Math.abs((ps.mean ?? 0) - 1.25) < 1e-9, ps)
  check('V1 negative control: an open month never enters the mean (it would read 1.25 → null-poisoned)', V.paidSummary([{ expiry: 'x', open: true, paid_minus_delivered: 9 }]).mean === null)
  check('V1 the client ledger is gone (no first-session-IV vs trailing-RV20 arithmetic)', !('ivPaidLedger' in V) && src('components/vol/VolView.tsx').includes('getIvPaidDelivered(symbol, 12)'))
  // M01: the spread of record is close-to-close and the others are named; FOVOLT on both annualisations
  const vr = V.ivVsRv([{ date: '2026-11-05', iv30_cm: 12.8, rv20_cc: 17.2, rv20_parkinson: 13.51, rv20_yz: 15.09, fovolt_ann: 16.5, iv_minus_rv20: -4.4 }])!
  check('V1f IV − RV is close-to-close; Parkinson and YZ spreads beside it', vr.spread === -4.4 && vr.spreadYz === -2.29 && vr.spreadParkinson === -0.71 && Math.abs((vr.fovolt252 ?? 0) - 16.5 * Math.sqrt(252 / 365)) < 1e-9, vr)
  const noStored = V.ivVsRv([{ date: '2026-11-05', iv30_cm: 12.8, rv20_cc: 17.2, rv20_yz: 15.09 }])!
  check('V1f negative control: without a stored spread it falls back to cc, never to Yang-Zhang (the 5 Nov mislabel)', noStored.spread === -4.4 && noStored.spread !== noStored.spreadYz)
  check('V1f the OMON tile says close-to-close, not YZ', src('components/vol/ChainStrip.tsx').includes('label="IV30 − RV20 (close-to-close)"') && !src('components/vol/ChainStrip.tsx').includes('label="IV30 − RV20 (YZ)"'))
  // M03: two skews, each with its own series' percentile
  const cs0 = src('components/vol/ChainStrip.tsx')
  check('V1g the skew tile pairs the near skew with the near series and the 30-day skew with the 30-day series', cs0.includes('nearSkew.pctile') && cs0.includes('percentileOf(lastYear(rows).map(r => r.skew_25d_30), skew30, 60)')
    && !cs0.includes('const skewNow = near?.skew_25d ?? last?.skew_25d_30'))
  // m047: Greeks on the OTM side's IV; m053: the straddle against realised windows, not the √(2/π) identity
  check('V1h OTM-side IV for the Greeks', V.otmIv(23850, 24545, 15.0, 17.4) === 17.4 && V.otmIv(24600, 24545, 15.5, 15.6) === 15.5 && V.otmIv(100, null, 12, 13) === 12)
  const oldPick = (ce: number | null, pe: number | null) => ce ?? pe
  check('V1h negative control: the old ce ?? pe pick took the ITM call (15.0)', oldPick(15.0, 17.4) === 15.0 && V.otmIv(23850, 24545, 15.0, 17.4) !== oldPick(15.0, 17.4))
  const spots = Array.from({ length: 40 }, (_, i) => ({ date: `d${i}`, spot: 100 * (1 + (i % 2 ? 0.02 : 0)) }))
  const sh = V.straddleHitRate(spots, 1.0, 1)
  check('V1i straddle breakeven vs past windows of the same length', sh.windows === 39 && sh.beyond === 39 && sh.share === 100 && V.straddleHitRate(spots, 5, 1).beyond === 0, sh)
  check('V1i negative control: no breakeven or no sessions → no share', V.straddleHitRate(spots, null, 2).share === null && V.straddleHitRate(spots, 1, 0).share === null)
  check('V1i the 0.80× identity is gone', !cs0.includes('× the priced move in the ATM tile'))
  check('V1j weekdays to expiry (Thu → Mon = 2 sessions)', V.weekdaysBetween('2026-11-05', '2026-11-09') === 2 && V.weekdaysBetween('2026-11-09', '2026-11-05') === 0)
  // m071 / m067
  const ex = [{ expiry: 'a', dte: 4, smile: [1, 2, 3] }, { expiry: 'b', dte: 18, smile: [1, 2, 3] }, { expiry: 'c', dte: 32, smile: [1, 2] }, { expiry: 'd', dte: 54, smile: [1, 2, 3] }]
  check('V1k like tenors: the expiry nearest 30 d with a smile', V.nearestTenor(ex, 30)?.expiry === 'b' && V.nearestTenor([{ expiry: 'x', dte: 2, smile: [1, 2, 3] }], 30) === null)
  check('V1l the basis chart keeps DTE ≥ 3', JSON.stringify(V.basisForChart([{ dte: 1, basis_ann_pct: 55 }, { dte: 3, basis_ann_pct: 4.2 }, { dte: 10, basis_ann_pct: null }], 3)) === '[null,4.2,null]')
  // round 2: the F&O guard on the shared active symbol (a DEAL pick of a cash-only name must not move DERV / OMON)
  const list = ['TCS', 'INFY', 'KAYNES']
  check('V2a fnoVerdict: an index is adopted before the list loads; a stock waits; on the list → adopt; off it → reject',
    V.fnoVerdict('NIFTY', undefined) === 'adopt' && V.fnoVerdict('TCS', undefined) === 'wait' && V.fnoVerdict('tcs', list) === 'adopt' && V.fnoVerdict('IRFC', list) === 'reject')
  check('V2a list unavailable → adopt (no guard beats a page that never follows); empty candidate → reject',
    V.fnoVerdict('IRFC', null) === 'adopt' && V.fnoVerdict('', list) === 'reject' && V.fnoVerdict(null, list) === 'reject')
  check('V2a negative control: a cash-only name is never adopted once the list is known', V.fnoVerdict('IRFC', list) !== 'adopt' && V.fnoVerdict('IRFC', ['NIFTY']) === 'reject')
  // the GO expiry hand-off: TCS OMON 27NOV writes {symbol, expiry} to the store (the bar's own write, pure core)
  const mkS = () => { const m = new Map<string, string>(); return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => { m.set(k, v) } } }
  const hw = mkS(), hs = mkS()
  A.writeActiveSymbol({ symbol: 'TCS', expiry: '2026-11-27' }, hw, hs, new Date('2026-11-06T04:00:00Z'))
  const handed = A.readActiveSymbol(hw, hs)
  check('V2b the GO expiry is read for the same symbol while it has not passed', V.handoffExpiry(handed, 'TCS', '2026-11-06') === '2026-11-27' && V.handoffExpiry(handed, 'TCS', '2026-11-27') === '2026-11-27')
  check('V2b negative controls: another symbol, a passed expiry, no expiry → the nearest series (null)',
    V.handoffExpiry(handed, 'INFY', '2026-11-06') === null && V.handoffExpiry(handed, 'TCS', '2026-11-28') === null
    && V.handoffExpiry({ symbol: 'TCS', expiry: null }, 'TCS', '2026-11-06') === null && V.handoffExpiry(null, 'TCS', '2026-11-06') === null)
  const chain = { symbol: 'TCS', expiry: '2026-11-24', expiries: ['2026-11-24', '2026-12-29'] }
  check('V2c an unlisted GO expiry is named (the chain answered with its nearest)', V.expiryNote('2026-11-27', chain) === '2026-11-27 is not a listed TCS expiry: showing 2026-11-24; the next listed after it is 2026-12-29.')
  check('V2c negative control: a listed expiry, or none asked, prints no note', V.expiryNote('2026-12-29', { ...chain, expiry: '2026-12-29' }) === null && V.expiryNote(null, chain) === null)
  const sk = [{ month: '2026-01', expiry: null, reason: 'gap' }, { month: '2025-11', expiry: null, reason: 'gap' }, { month: '2025-12', expiry: null, reason: 'gap' },
              { month: '2026-04', expiry: '2026-04-28', reason: 'no entry row' }, { month: '2026-06', expiry: null, reason: 'gap' }]
  check('V2f the paid-vs-delivered ledger names its skipped months, consecutive gaps folded into one run',
    JSON.stringify(V.skippedRuns(sk)) === JSON.stringify(['2025-11 → 2026-01: gap', '2026-04 (2026-04-28): no entry row', '2026-06: gap']), V.skippedRuns(sk))
  check('V2f negative control: a month with its own expiry is never folded into a run; nothing skipped → nothing printed',
    V.skippedRuns([{ month: '2026-03', expiry: null, reason: 'gap' }, { month: '2026-04', expiry: '2026-04-28', reason: 'gap' }]).length === 2 && V.skippedRuns([]).length === 0)
  check('V2d istDay is the IST calendar day', V.istDay(new Date('2026-11-05T18:29:00Z')) === '2026-11-05' && V.istDay(new Date('2026-11-05T18:31:00Z')) === '2026-11-06')
  // M04 on OVME: the pricer's T is the chain's t_days; the old days + ½ gives another theta / vega for the same contract
  const at = B.black76('call', 24_000, 24_550, B.tYears(4), 0.15), half = B.black76('call', 24_000, 24_550, (4 + 0.5) / 365, 0.15)
  check('V2e one clock: OVME at t_days 4 equals the chain\'s Greeks at T = 4 / 365', Math.abs(at.thetaDay - B.black76('call', 24_000, 24_550, 4 / 365, 0.15).thetaDay) < 1e-12)
  check('V2e negative control: the half-day T moves theta and vega (the M04 symptom)', Math.abs(at.thetaDay - half.thetaDay) > 0.1 && Math.abs(at.vega - half.vega) > 0.05, { at, half })
  // "percentile of the past year" = the last 252 sessions, never the ≈3-year fetch (B4-UI check major)
  const series = Array.from({ length: 500 }, (_, i) => ({ v: i < 248 ? 100 + i : i - 248 }))   // old high values, recent low ones
  const yr = V.lastYear(series).map(x => x.v), today = 300   // recent 252 values are 0..251, the old 248 are 100..347
  const below = (xs: number[]) => xs.filter(x => x < today).length / xs.length * 100
  check('V1b the 1-year window is the last 252 sessions and its percentile differs from the full series',
    V.ONE_YEAR_SESSIONS === 252 && yr.length === 252 && below(yr) === 100 && Math.abs(below(series.map(x => x.v)) - 100 * (252 + 200) / 500) < 1e-9 && below(yr) !== below(series.map(x => x.v)))
  {
    const cs = fs.readFileSync(path.join(UI, 'components', 'vol', 'ChainStrip.tsx'), 'utf8')
    const vv = fs.readFileSync(path.join(UI, 'components', 'vol', 'VolView.tsx'), 'utf8')
    const da = fs.readFileSync(path.join(UI, 'components', 'drivers', 'DeskAttribution.tsx'), 'utf8')
    const usesFullHistory = (src: string) => /percentileOf\(rows\.map\(r => r\.skew_25d_30\)/.test(src)
    check('V1c skew percentiles use lastYear(rows) on OMON and DERV › VOL', !usesFullHistory(cs) && !usesFullHistory(vv) && /lastYear\(rows\)/.test(cs) && /lastYear\(rows\)/.test(vv))
    check('V1c negative control: the old full-history call is caught', usesFullHistory("percentileOf(rows.map(r => r.skew_25d_30), last?.skew_25d_30, 60)"))
    // same number once per page (PLAN §0.4): the ladder chips own each expiry's ATM IV; the ATM tile owns the priced move;
    // the DESK header owns the NAV
    const repeats = (src: string, desk: string) => /pct1\(near\.atm_iv\)/.test(src) || /sigma_to_expiry_pct/.test(src) || /fmtInr\(d\.nav\)/.test(desk)
    check('V1d OMON strip repeats neither the ladder IVs nor the priced move; DESK attribution does not repeat the NAV', !repeats(cs, da))
    {
    const ic = fs.readFileSync(path.join(UI, 'components', 'IndexContribution.tsx'), 'utf8')
    const stamped = (src: string) => /data-contrib-stamp/.test(src) && /contributionStamp\(d\.time\)/.test(src)
    check('V1e WHO MOVED THE INDEX prints NSE\'s publish time (today) or the session date (asked 5 Nov: live or stale?)', stamped(ic))
    check('V1e negative control: a panel without the stamp is caught', !stamped('<span>actual {fmtSigned(d.change, 1)} pts</span>'))
  }
  check('V1d negative control: the old strip and sentence are caught', repeats('${pct1(near.atm_iv)} / x · 1σ to expiry {pct1(straddle.sigma_to_expiry_pct, 2)}', '(NAV {fmtInr(d.nav)})'))
  }
  const hit = V.expectedMoveHitRate(rows, 60)
  check('V2 hit-rate counts next-session moves inside ±expected move (1 %)', hit.sessions === 3 && hit.inside === 2 && hit.reference > 68 && hit.reference < 68.3, hit)
  const sv = V.straddleView(100, 100, 20000, 12, 30)
  check('V3 straddle vs the lognormal 1σ to expiry', sv.price === 200 && Math.abs((sv.pct_of_forward ?? 0) - 1) < 1e-9 && Math.abs((sv.sigma_to_expiry_pct ?? 0) - 12 * Math.sqrt(30 / 365)) < 1e-9)
  check('V3 no price, no ratio', V.straddleView(null, 100, 20000, 12, 30).straddle_over_sigma === null && V.straddleView(1, 1, 100, 12, 0).sigma_to_expiry_pct === null)
  const seed = (ks: number[]) => V.legsFromStrikes(ks).map(l => `${l.side[0]}${l.kind}${l.strike}`).join(' ')
  check('V4 OMON → OSTR seeds: 1 straddle, 2 strangle, 3 iron fly, 4 iron condor', seed([100]) === 'bCE100 bPE100' && seed([110, 90]) === 'bPE90 bCE110'
    && seed([90, 100, 110]) === 'bPE90 sPE100 sCE100 bCE110' && seed([80, 90, 110, 120]) === 'bPE80 sPE90 sCE110 bCE120', [seed([100]), seed([90, 100, 110]), seed([80, 90, 110, 120])])
  check('V4 junk strikes are dropped; none → no legs', V.legsFromStrikes([NaN, -5, 0]).length === 0 && seed([100, 100]) === 'bCE100 bPE100')
  check('V5 term words describe a shape, never a direction', V.termWord(1) === 'upward (longer-dated IV higher)' && V.termWord(-1) === 'inverted (near IV higher)' && V.termWord(0.2) === 'flat' && V.termWord(null) === '—')
}

// ── A. active-symbol store ────────────────────────────────────────────────────────────────────────
{
  const mem = () => { const m = new Map<string, string>(); return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => { m.set(k, v) }, m } }
  check('A1 a malformed value never crashes a page', A.parseActiveSymbol('{oops') === null && A.parseActiveSymbol('{"symbol":"<img>"}') === null && A.parseActiveSymbol(null) === null)
  const p = A.parseActiveSymbol(JSON.stringify({ symbol: 'nifty', expiry: '2026-11-25', strikes: [24000, 23500, 24000, 25000, 22000, 26000], at: '2026-11-05T10:00:00Z' }))
  check('A1 parse: upper-cased, strikes deduped + sorted + capped at 4, ISO expiry', p?.symbol === 'NIFTY' && p.expiry === '2026-11-25' && JSON.stringify(p.strikes) === '[22000,23500,24000,25000]', p)
  const cur = { symbol: 'NIFTY', expiry: '2026-11-25', strikes: [24000], at: '2026-11-05T10:00:00Z' }
  const sw = A.mergeActive(cur, { symbol: 'TCS' }, '2026-11-05T10:01:00Z')
  check('A2 a new symbol drops the old expiry and strikes (they belonged to the old chain)', sw?.symbol === 'TCS' && sw.expiry === null && sw.strikes.length === 0, sw)
  const keep = A.mergeActive(cur, { strikes: [24100, 23900] }, '2026-11-05T10:02:00Z')
  check('A2 same symbol: the expiry is kept and the strikes replaced', keep?.expiry === '2026-11-25' && JSON.stringify(keep?.strikes) === '[23900,24100]')
  const naive = { ...cur, symbol: 'TCS' }
  check('A2 negative control: a naive spread would carry NIFTY strikes onto TCS', naive.strikes.length === 1 && sw?.strikes.length === 0)
  const win = mem(), shared = mem()
  A.writeActiveSymbol({ symbol: 'RELIANCE', expiry: '2026-11-25', strikes: [1300] }, win, shared, new Date('2026-11-05T10:00:00Z'))
  shared.setItem(A.ACTIVE_SYMBOL_KEY, JSON.stringify({ symbol: 'INFY', expiry: null, strikes: [], at: '2026-11-05T11:00:00Z' }))
  check('A3 the newest pick wins across the window and the synced layer', A.readActiveSymbol(win, shared)?.symbol === 'INFY')
  win.setItem(A.ACTIVE_SYMBOL_WINDOW_KEY, JSON.stringify({ symbol: 'TCS', expiry: null, strikes: [], at: '2026-11-05T12:00:00Z' }))
  check('A3 this window\'s newer pick beats the synced default', A.readActiveSymbol(win, shared)?.symbol === 'TCS')
  check('A4 the synced key is a SYNC prefs key (prefs-synced, PLAN 1.3)', K.isSyncKey(A.ACTIVE_SYMBOL_KEY) && A.ACTIVE_SYMBOL_KEY === 'activeSymbol.v1' && K.classifyKey(A.ACTIVE_SYMBOL_WINDOW_KEY) !== 'sync')
}

// ── D. drivers wording ────────────────────────────────────────────────────────────────────────────
{
  const d20 = { leader: 'BHARTIARTL', tenure: 9, leader_share: 0.125, sentence: '20-session leader BHARTIARTL for 9 sessions, 12.5 % of member points — describes, does not predict' }
  const tl60 = { points: [{ date: '2026-09-10', leader: 'INFY', changed: false }, { date: '2026-09-11', leader: 'HDFCBANK', changed: true }, { date: '2026-11-04', leader: 'HDFCBANK', changed: false }] }
  const line = D.regimeLine(d20, tl60, 0.44, -0.95, 'narrow')
  check('D1 the regime strip: both leaders, top-5, EW − CW, ending once with "describes, does not predict"',
    line === '20-session leader BHARTIARTL for 9 sessions, 12.5 % of member points; 60-session leader HDFCBANK since 11 Sep; top-5 of the move 44 %; EW − CW −0.95 pp: narrow — describes, does not predict', line)
  check('D1 nothing stored: no line (the strip says "backfill pending" instead)', D.regimeLine(null, null, null, null) === null)
  check('D1 negative control: a route sentence without the ending still ends with it', (D.regimeLine({ leader: 'X', sentence: 'leader X' }, null, null, null) ?? '').endsWith(S.DESCRIBES))
  check('D2 60-session leader and since when', JSON.stringify(D.leader60(tl60)) === '{"leader":"HDFCBANK","since":"2026-09-11"}' && D.leader60({ points: [] }) === null)
  const chip = D.fitChip({ index_move_pts: -2169, explained_pts: -2132, as_of: '2026-11-04', horizon: { name: 'ytd' }, fit: { mae_60s: 9.4, degraded: false }, weight_method: { label: "weights rebuilt, calibrated to NSE's top-10" } })
  check('D3 the fit chip', chip === "explains −2,132 of −2,169 YTD points · MAE 9.4 pts/day · weights rebuilt, calibrated to NSE's top-10 on 04 Nov", chip)
  const dated = D.fitChip({ index_move_pts: 474, explained_pts: 477, as_of: '2026-11-02', horizon: { name: '1m' }, fit: { mae_60s: 0.36 }, weight_method: { label: "weights rebuilt, calibrated to NSE's top-10 on 2026-11-02" } })
  check('D3 a label that already names its date gets no second "on <date>"', dated === "explains +477 of +474 1-month points · MAE 0.4 pts/day · weights rebuilt, calibrated to NSE's top-10 on 2026-11-02", dated)
  const twice = D.regimeLine({ leader: 'HDFCBANK', sentence: '20-session leader HDFCBANK, EW − CW −1.30 pp: narrow — describes, does not predict' }, null, 1, -0.46, 'even')
  check('D1 one breadth number per line: the route sentence\'s EW − CW is not repeated', (twice ?? '').split('EW − CW').length === 2 && !(twice ?? '').includes('−0.46'), twice)
  check('D3 a degraded fit says so; no numbers, no chip', (D.fitChip({ index_move_pts: 1, explained_pts: 1, fit: { mae_60s: 40, degraded: true } }) ?? '').includes('FIT DEGRADED') && D.fitChip({ explained_pts: null, index_move_pts: 3 }) === null)
}

// ── H. SYS › DATA ─────────────────────────────────────────────────────────────────────────────────
{
  const row = (id: string, state: string, lag: number | null, pages: string[] = ['DERV']) => ({ id, label: id, pages, publisher: 'NSE', published_ist: '20:10', expected_by: '21:00',
    as_of: '2026-10-30', lag_sessions: lag, state, unrecoverable: false, job_id: null, last_run: null, next_run: null, catchup_at: null, note: '', dictionary_anchor: null })
  const rows = [row('a', 'fresh', 0), row('b', 'amber', 1), row('c', 'red', 4, ['OMON']), row('d', 'gap', null), row('e', 'red', 6)]
  check('H1 worst first, then most sessions behind', H.sortRows(rows).map(r => r.id).join('') === 'decba', H.sortRows(rows).map(r => r.id))
  check('H2 n STALE = amber + red + gaps (from the summary when sent)', H.staleCount({ summary: { green: 1, amber: 1, red: 2, gaps: 1 }, rows: [] }) === 4 && H.staleCount({ rows } as never) === 4 && H.staleCount(null) === 0)
  check('H3 filter by page', H.filterByPage(rows, 'omon').map(r => r.id).join('') === 'c' && H.filterByPage(rows, null).length === 5)
  const sentence = H.rowSentence({ ...row('x', 'red', 3), catchup_at: '2026-11-06T19:30:00+05:30' })
  check('H4 the honest sentence', sentence === 'stored 30 Oct · expected by 21:00 · 3 sessions behind · catch-up 19:30 6 Nov', sentence)
  check('H4 the server note wins when sent', H.rowSentence({ ...row('x', 'red', 3), note: 'stored 30 Oct · expected by 21:00 · 4 sessions behind' }).endsWith('4 sessions behind'))
  const view = src('components/datahealth/DataHealthView.tsx') + src('components/datahealth/healthModel.ts')
  check('H5 no composite score in the data view', !/\bscore\b/i.test(view.replace(/composite score|never a composite score|no score/gi, '')))
  // 5 Nov: a catalogued job that never ran has last_run {ts: null, …}: `r.last_run.ts.slice` threw and the whole SYS › DATA view
  // showed FAILED TO RENDER (the 43-page audit visits ?tab=system, not the sub-view)
  check('H7 a never-run job (last_run.ts null) renders "never run", never throws', view.includes('r.last_run?.ts ?') && !/r\.last_run\.ts\.slice/.test(view.replace('r.last_run?.ts ? ` · ${r.last_run.ts.slice', ''))
    && src('components/datahealth/healthModel.ts').includes('last_run: { ts: string | null'))
  check('H6 the header DATA n STALE chip opens SYS › DATA', src('components/MarketCommandHeader.tsx').includes('<DataStaleChip />') && src('components/datahealth/DataHealthView.tsx').includes("setSubInUrl('data')")
    && src('components/SystemTelemetry.tsx').includes("useSubView(['system', 'data'] as const, 'system')"))
}

// ── T. unknown ?tab= and GO aliases ───────────────────────────────────────────────────────────────
{
  const tabs = ['brief', 'options', 'derivatives']
  check('T1 an unknown tab is named; a known one / none is not', DL.unknownTab('?tab=gold', tabs) === 'gold' && DL.unknownTab('?tab=options', tabs) === null && DL.unknownTab('?sym=TCS', tabs) === null)
  check('T1 the toast names the release build date', DL.unknownTabText('gold', '20261025-111000-abc1234') === 'GOLD is not in this release (built 25 Oct) — showing BRF', DL.unknownTabText('gold', '20261025-111000-abc1234'))
  check('T1 a development build says so', DL.unknownTabText('gold', null).includes('a development build'))
  check('T1 negative control: parseLocation alone falls back silently to the landing page', DL.parseLocation('?tab=gold', tabs, 'brief').tab === 'brief')
  check('T1 page.tsx mounts the toast inside the provider', src('app/page.tsx').includes('<UnknownTabToast tabs={TAB_IDS} />'))
  const t = (q: string) => JSON.stringify(GA.aliasTargets(q))
  check('T2 VOL → DERV › VOL, DATA → SYS › DATA', t('vol') === '[{"kind":"page","id":"derivatives","view":"vol"}]' && t('DATA') === '[{"kind":"page","id":"system","view":"data"}]')
  check('T2 DRVR / IMAP / CONTRIB → MEMB', ['DRVR', 'IMAP', 'CONTRIB'].every(a => t(a) === '[{"kind":"page","id":"memb"}]'))
  check('T2 negative control: a two-word query is not an alias', GA.aliasTargets('VOL NIFTY').length === 0)
}

// ── P. page wiring (Wave 0.6, 1.1–1.4) ────────────────────────────────────────────────────────────
{
  const oc = src('components/OptionChain.tsx'), dv = src('components/DerivativesDesk.tsx'), mv = src('components/LiveMovers.tsx')
  check('P1 OMON PCR in the neutral token (≥ 1 used to be green)', !oc.includes('(data.pcr_oi ?? 1) >= 1 ? T.green : T.red') && /label="Put \/ call OI" value=\{data\.pcr_oi \?\? '—'\} color=\{T\.text\}/.test(oc))
  check('P1 DERV PCR and VIX neutral', !dv.includes('(maxPain.pcr_oi ?? 1) >= 1 ? T.green : T.red') && !dv.includes('(vix?.pctile_1y ?? 0) < 80 ? T.green : T.red')
    && !dv.includes('(vix.pctile_1y ?? 0) < 80 ? T.green : T.red') && !dv.includes('complacent'))
  check('P1 DERV VIX level once per page (the strip), none in the VIX panel tiles', (dv.match(/value=\{num\(vix\??\.level, 2\)\}/g) ?? []).length === 1)
  check('P1 OMON shows the VIX only on the IV chart (vix_daily overlay)', !/INDIA VIX/i.test(oc.replace(/\/\*\*[\s\S]*?\*\//, '')) && src('components/vol/IvHistoryChart.tsx').includes("label: 'India VIX'"))
  check('P2 MOV: the two INTRADAY panels have distinct titles', mv.includes('title="Intraday · NIFTY 50"') && mv.includes('title="Intraday · NIFTY BANK"') && !mv.includes('<Panel title="Intraday" '))
  const contribUsers = fs.readdirSync(path.join(UI, 'components')).filter(f => f.endsWith('.tsx') && f !== 'IndexContribution.tsx' && /<IndexContribution\b/.test(src(`components/${f}`)))
  check('P3 the live today panel (WHO MOVED THE INDEX) renders on MOV only among pages (BRF keeps its one line)', JSON.stringify(contribUsers) === '["LiveMovers.tsx"]', contribUsers)
  const horizonUsers = ['app/page.tsx', ...fs.readdirSync(path.join(UI, 'components')).filter(f => f.endsWith('.tsx')).map(f => `components/${f}`)].filter(f => src(f).includes('useDrivers('))
  check('P3 the horizon table on MEMB only', JSON.stringify(horizonUsers) === '["components/IndexMembers.tsx"]', horizonUsers)
  check('P3 MOV keeps the live panel with a "history on MEMB" footer', mv.includes('history on MEMB ›') && mv.includes("goToPage('memb')"))
  // W2-TAPE mounted XPRY (PLAN 2.4) as DERV's third sub-view: DESK | VOL | XPRY, still one page
  check('P4 DERV › VOL (and › XPRY) are sub-views (O-T14), not a 44th page', dv.includes("useSubView(['desk', 'vol', 'xpry'] as const, 'desk')") && dv.includes('<VolView symbol={symbol}')
    && dv.includes('<ExpiryDay symbol={symbol}') && !src('app/page.tsx').includes("id: 'vol'") && !src('app/page.tsx').includes("id: 'xpry'"))
  check('P4 negative control: the two-view list (before XPRY) no longer matches', !dv.includes("useSubView(['desk', 'vol'] as const, 'desk')"))
  check('P5 OMON: OPEN IN OSTR carries symbol + expiry + strikes through the active-symbol store', oc.includes('writeActive({ symbol: data.symbol, expiry: data.expiry, strikes: picks })') && oc.includes("goToPage('ostrategy')"))
  check('P5 OMON: j / k strike cursor and space picks', oc.includes("e.key === 'j'") && oc.includes("e.key === 'k'") && oc.includes("e.key === ' '"))
  check('P5 OMON: Greeks columns from lib/black76 (greeksFor) on the chain\'s own T (t_days, M04) and the OTM side\'s IV', oc.includes("greeksFor('call', data.forward, r.strike, kIv, tDays)")
    && oc.includes('const kIv = otmIv(r.strike, data.forward, r.ce.iv, r.pe.iv)') && src('components/vol/ChainStrip.tsx').includes("from '@/lib/black76'"))
  check('P5 negative control: the integer-day Greeks call is gone', !oc.includes("greeksFor('call', data.forward, r.strike, kIv, data.days_to_expiry)"))
  check('P5b OMON chain units: OI / OI CHG in contracts like VOLUME, the header says so (M05)', oc.includes("inContracts(ce, 'oi', data.lot)") && oc.includes("const oiUnit = data?.lot ? 'contracts' : 'shares'"))
  check('P5c OMON walls in side colours, no "support / resistance" (m003)', !oc.includes('call wall (resistance) / put wall (support)') && !oc.includes('red = calls (resistance)'))
  check('P5d OMON IV history open by default (m050)', oc.includes('const [histOpen, setHistOpen] = useState(true)'))
  check('P5e DERV follows the active symbol (the shared convention)', dv.includes('useActiveSymbol()') && dv.includes("useState(() => active?.symbol ?? 'NIFTY')"))
  check('P5f DERV roll cost is the calendar spread (m065)', dv.includes('label="Calendar roll · near → next"') && !dv.includes('sub="what rolling a long costs today"'))
  // round 2 (checker notes): the rest of m003, the F&O guard on adoption, the GO expiry hand-off, OVME on the chain's T
  check('P5g m003: OMON OI CHG in the neutral token with its sign; DERV walls "call / put" in the neutral token',
    oc.includes("const chg = (v: number | null) => <span style={{ color: v == null || v === 0 ? T.dim : T.text }}>{v == null ? '—' : signedLakh(v)}</span>")
    && dv.includes('label="OI walls · call / put"') && !oc.includes('where writers sit = support / resistance'))
  check('P5g negative control: green / red OI change and "OI walls (R / S)" are gone',
    !oc.includes('v > 0 ? T.green : v < 0 ? T.red') && !dv.includes('label="OI walls (R / S)"'))
  check('P5h DERV and OMON adopt an external active symbol only when it is F&O (fnoVerdict)', dv.includes("if (s && fnoVerdict(s, fno) === 'adopt') setSymbolState(")
    && dv.includes("setSymbolState(prev => (fnoVerdict(prev, fno) === 'reject' ? 'NIFTY' : prev))") && oc.includes('const verdict = fnoVerdict(s, fnoList)'))
  check('P5h negative control: the unconditional adoption is gone', !dv.includes('useEffect(() => { if (active?.symbol) setSymbolState(prev => (prev === active.symbol ? prev : active.symbol)) }, [active?.symbol])'))
  check('P5i OMON reads the GO expiry hand-off (TCS OMON 27NOV) on mount and on the hand-off event, and says when it is not listed',
    oc.includes("useState<string | null>(() => (typeof window === 'undefined' ? null : handoffExpiry(readActiveSymbol(), omonInitialSymbol(readHandoff()), istDay())))")
    && oc.includes('const sym = omonInitialSymbol(s), e = handoffExpiry(readActiveSymbol(), sym, istDay())') && oc.includes('expiryNote(askedExpiry, data)'))
  const op = src('components/OptionPricer.tsx')
  check('P5j OVME prices on the chain\'s t_days (M04), the label has no half day', op.includes('black76(pick.side, F, K, chainDays / 365, chainIv / 100)')
    && op.includes('const chainDays = chainTDays(data)') && !op.includes('days_to_expiry) + 0.5') && !op.includes('+½'))
  const sb = src('components/StrategyBuilder.tsx')
  check('P6 OSTR opens on the active symbol and seeds the picked strikes once', sb.includes("useState(() => readActiveSymbol()?.symbol ?? 'NIFTY')") && sb.includes('seedFromStrikes(seed.strikes, chain)'))
  check('P6 OSTR margin: the route answers, the chip names BREEZE / NSE SPAN FILE / HEURISTIC, the 4.8× error is printed', sb.includes('postMargin(symbol, body, forward)')
    && sb.includes('source={marginSource(margin, marginErr, ul.market)}') &&   // cd8778e: the market state makes the chip CLOSE after hours
    sb.includes('data-ostr-heuristic-error') && sb.includes('error_factor_measured ?? 4.8'))
  check('P6 negative control: the old panel was titled ESTIMATE with no source', !sb.includes('title="Margin & costs — ESTIMATE"'))
  check('P7 EVTS: the IV-crush ledger; the profile: the IV strip', src('components/EventCalendar.tsx').includes('<CrushLedger />') && src('components/StockProfile.tsx').includes('<IvStrip symbol={p.symbol}'))
  check('P7 DESK: Book vs NIFTY attribution, honest in cash', src('components/DecisionDesk.tsx').includes('<DeskAttribution />') && src('components/drivers/DeskAttribution.tsx').includes('Book = liquid fund since'))
  const dv2 = src('components/drivers/DriversView.tsx')
  check('P7 the monthly board lists only positive adds and negative drags', dv2.includes('r.top3_add.filter(x => x.points > 0)') && dv2.includes('r.top3_drag.filter(x => x.points < 0)'))
  check('P8 empty stores say "backfill pending", never a fake value', ['components/vol/VolView.tsx', 'components/vol/api.ts', 'components/drivers/DriversView.tsx', 'components/drivers/api.ts'].every(f => src(f).includes('backfill pending')))
}

console.log(`terminal_v2.check: ${passed} passed, ${failed} failed`)
if (failed) process.exit(1)

/**
 * GOLD page checks (gold program PLAN §h T7 / T9, builder B4A-UI-CORE).
 *
 *  R  the 43rd page is registered everywhere a page lives: app/page.tsx (Tab union, TAB_IDS, COMMAND_PAGES, lazyTab,
 *     render case), components/shell/tabModules.ts, components/desktop/pages.ts, lib/goAliases.ts (XAU, GC)
 *  T9 repetition is a defect: exactly one component renders <GoldPreOpen>; Brief.tsx no longer calls getGoldPreOpen;
 *     CommodityTab.tsx has no GoldPreOpen; MCXG has no specs table (the shared selector instead); "fair open" is the
 *     subject of at most one panel title on the gold page
 *  H  the health sentence ends "describes, does not predict"; no composite score anywhere (types, payload guard)
 *  B  badge rendering rules: context is the neutral tone, never a buy/sell colour; no "bullish/bearish" in the views
 *  M  signed numbers use U+2212; no hand-rolled '+' sign in the gold files
 *  U  one unit per column in the WEEKLY table; the unit picker labels are distinct; the four instrument labels are distinct
 *  S  sessions.ts (DST bands, Globex axis, CME trade date) and the bar helpers (dayGroups, resample5m, weeks, months,
 *     seasonality) against hand-computed values
 *  P  prefs (contract selection, URL state) round-trip; the catalog gate; the one-line echoes (WEI, BRF, MCXG): the
 *     SERVER's line / brf_line verbatim, the client composition only as a fallback; BRF colour on the arithmetic only
 *  I  every PLAN panel id in the B4A views is one of the a.* ids; every tooltip key the views use exists in tooltips.json
 *     (the UI copy or G-EDU, the source of truth); the §f.2 gate (`series=`) on EVERY panel
 *  F  wave 1b fixes stay fixed: the picked family reaches /positioning/daily and /curve; the event-words chip keys on
 *     the count; the weekly default window; a deep link never writes the synced contract; PLAN a.1's sub-view aliases
 *
 * Run with plain node 25 (type stripping, no deps):
 *   node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON ui/components/__tests__/gold.check.ts
 * Also type-checked by `cd ui && npx tsc --noEmit`. Exits non-zero on any failing check.
 */
import * as fs from 'node:fs'
import * as nodeModule from 'node:module'
import * as path from 'node:path'

const UI = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..')

// '@/x' (the app's alias) and extensionless relative specifiers → files under ui/, for node's ESM resolver
;(nodeModule as unknown as { registerHooks?: (h: unknown) => void }).registerHooks?.({
  resolve(spec: string, ctx: unknown, next: (s: string, c: unknown) => unknown) {
    const tryFile = (base: string): string | null => {
      for (const cand of [base, `${base}.ts`, `${base}.tsx`, path.join(base, 'index.ts')]) {
        if (fs.existsSync(cand) && fs.statSync(cand).isFile()) return cand
      }
      return null
    }
    if (spec.startsWith('@/')) {
      const hit = tryFile(path.join(UI, spec.slice(2)))
      if (hit) return next(`file://${hit}`, ctx)
    }
    try {
      return next(spec, ctx)
    } catch (e) {
      if (/^(\.|\/|file:)/.test(spec) && !/\.[cm]?[jt]sx?$/.test(spec)) {
        const base = spec.startsWith('file:') ? new URL(spec).pathname : spec.startsWith('/') ? spec
          : path.join(path.dirname(new URL((ctx as { parentURL: string }).parentURL).pathname), spec)
        const hit = tryFile(base)
        if (hit) return next(`file://${hit}`, ctx)
      }
      throw e
    }
  },
})

type FormatMod = typeof import('../../lib/gold/format')
type SessionsMod = typeof import('../../lib/gold/sessions')
type PrefsMod = typeof import('../../lib/gold/prefs')
type TypesMod = typeof import('../../lib/gold/types')
type AliasMod = typeof import('../../lib/goAliases')
type PagesMod = typeof import('../desktop/pages')
type GoldHealth = import('../../lib/gold/types').GoldHealth

const F = (await import(new URL('../../lib/gold/format.ts', import.meta.url).href)) as FormatMod
const S = (await import(new URL('../../lib/gold/sessions.ts', import.meta.url).href)) as SessionsMod
const PR = (await import(new URL('../../lib/gold/prefs.ts', import.meta.url).href)) as PrefsMod
const TY = (await import(new URL('../../lib/gold/types.ts', import.meta.url).href)) as TypesMod
const AL = (await import(new URL('../../lib/goAliases.ts', import.meta.url).href)) as AliasMod
const PG = (await import(new URL('../desktop/pages.ts', import.meta.url).href)) as PagesMod

const src = (rel: string) => fs.readFileSync(path.join(UI, rel), 'utf8')
const walk = (dir: string): string[] => fs.readdirSync(dir, { withFileTypes: true }).flatMap(d => {
  const p = path.join(dir, d.name)
  if (d.isDirectory()) return d.name === '__tests__' || d.name === 'node_modules' ? [] : walk(p)
  return /\.tsx?$/.test(d.name) ? [p] : []
})

let failed = 0, passed = 0
function check(name: string, cond: unknown, extra?: unknown): void {
  if (cond) { passed++; return }
  failed++
  console.error(`FAIL ${name}${extra !== undefined ? ` :: ${JSON.stringify(extra)}` : ''}`)
}
const eq = (name: string, a: unknown, b: unknown) => check(name, JSON.stringify(a) === JSON.stringify(b), { got: a, want: b })
const near = (name: string, a: number | null, b: number, tol = 1e-6) => check(name, a != null && Math.abs(a - b) <= tol, { got: a, want: b })

const MINUS = '−'
const B4A_VIEWS = ['GoldPage', 'HealthView', 'DailyView', 'WeeklyView', 'MonthlyView', 'ContractsView', 'HealthStrip', 'GoldPreOpen', 'GoldAccuracyLog', 'kit']
  .map(n => `components/gold/${n}.tsx`)

// ── R. the 43rd page, registered in every place a page lives ──────────────────────────────────────
{
  const page = src('app/page.tsx')
  check('R1 Tab union has gold', /type Tab = [^\n]*'gold'/.test(page))
  check('R2 TAB_IDS has gold once', (page.match(/const TAB_IDS: Tab\[\] = \[[\s\S]*?\]/)?.[0].match(/'gold'/g) ?? []).length === 1)
  const row = /\{\s*id:\s*'gold',\s*code:\s*'GOLD',\s*label:\s*'Gold terminal',\s*hint:\s*'([^']*)'\s*\}/.exec(page)
  check('R3 COMMAND_PAGES row {gold, GOLD, Gold terminal}', !!row)
  check('R3 hint names the sub-views', !!row && /positioning \(COT\)/.test(row[1]) && /health check/.test(row[1]))
  check('R3 GOLD row sits next to MCXG (DerivativesGold group)', page.indexOf("id: 'mcxgold'") < page.indexOf("id: 'gold'") && page.indexOf("id: 'gold'") < page.indexOf("id: 'glassbox'"))
  check('R4 lazyTab(gold) + render case', page.includes("const GoldPage = lazyTab('gold', m => m.GoldPage)") && page.includes("case 'gold': return <GoldPage />"))
  check('R5 CMDT no longer says Gold desk', !/Commodities · Gold desk/.test(page) && !/MCX gold pre-open fair value/.test(page))
  const tabs = src('components/shell/tabModules.ts')
  check('R6 tabModules loader for gold', tabs.includes("gold: () => import('@/components/gold/GoldPage')"))
  eq('R7 desktop PAGE_META.gold', PG.PAGE_META.gold, { code: 'GOLD', label: 'Gold terminal' })
  eq('R7 desktop PAGE_META.commodity dropped the desk', PG.PAGE_META.commodity, { code: 'CMDT', label: 'Commodities' })
  eq('R7 window title', PG.windowTitle(PG.pageMeta('gold')), 'GOLD · Gold terminal — SuryaDhana')
  eq('R8 GO aliases XAU / GC open the gold page', [AL.aliasTargets('xau'), AL.aliasTargets('GC')], [[{ kind: 'page', id: 'gold' }], [{ kind: 'page', id: 'gold' }]])
  eq('R8 GOLD itself is not an alias (exact code match ranks first in GO)', AL.aliasTargets('GOLD'), [])
  eq('R8 PLAN a.1 sub-view aliases GPHY / GMAC / LRN / COT hand the sub-view over', [AL.aliasTargets('GPHY'), AL.aliasTargets('gmac'), AL.aliasTargets('LRN'), AL.aliasTargets('COT')],
    [[{ kind: 'page', id: 'gold', sub: 'physical' }], [{ kind: 'page', id: 'gold', sub: 'macro' }], [{ kind: 'page', id: 'gold', sub: 'learn' }], [{ kind: 'page', id: 'gold', sub: 'positioning' }]])
  check('R8 every alias sub is a GOLD sub-view and CommandBar routes it', Object.values(AL.GO_ALIASES).flat().every(t => t.kind !== 'page' || !t.sub || (TY.GOLD_SUBS as readonly string[]).includes(t.sub))
    && /'sub' in a[\s\S]*setGoldSubInUrl\(a\.sub/.test(src('components/CommandBar.tsx')))
  check('R9 the macro tape names the instrument', src('components/MarketCommandHeader.tsx').includes("{ sym: 'GC=F', label: 'GOLD GC1' }"))
  const gp = src('components/gold/GoldPage.tsx')
  check('R10 nine sub-views in tab order', JSON.stringify(TY.GOLD_SUBS) === JSON.stringify(['health', 'daily', 'weekly', 'monthly', 'positioning', 'physical', 'macro', 'contracts', 'learn']))
  check('R10 GoldPage mounts the glossary drawer once', (gp.match(/<GlossaryPanel \/>/g) ?? []).length === 1)
  check('R10 GoldPage code-splits the other builders\' views', /import\('\.\/PositioningView'\)/.test(gp) && /import\('\.\/PhysicalView'\)/.test(gp) && /import\('\.\/MacroView'\)/.test(gp) && /import\('\.\/LearnView'\)/.test(gp))
  check('R11 the prefs keys are registered as SYNC', ['gold.contract.v1', 'gold.layer.v1', 'gold.triggers.v1', 'goldPreOpen.v1'].every(k => src('lib/prefs/keys.ts').includes(`'${k}'`)))
}

// ── T9. repetition is a defect ───────────────────────────────────────────────────────────────────
{
  const files = walk(path.join(UI, 'components')).concat(walk(path.join(UI, 'app')))
  const renders = files.filter(f => /<GoldPreOpen[\s/>]/.test(fs.readFileSync(f, 'utf8'))).map(f => path.relative(UI, f))
  eq('T9 exactly one component renders <GoldPreOpen>', renders, ['components/gold/HealthView.tsx'])
  check('T9 the old ui/components/GoldPreOpen.tsx is gone (moved)', !fs.existsSync(path.join(UI, 'components/GoldPreOpen.tsx')) && !fs.existsSync(path.join(UI, 'components/GoldAccuracyLog.tsx')))
  check('T9 the localStorage key goldPreOpen.v1 survived the move', src('components/gold/GoldPreOpen.tsx').includes("const STORE = 'goldPreOpen.v1'"))
  const brief = src('components/Brief.tsx')
  check('T9 Brief.tsx has no getGoldPreOpen call and no gold panel', !/getGoldPreOpen/.test(brief) && !/goldPanel|goldFirst|Gold open \(MCX\)/.test(brief))
  check('T9 Brief.tsx reads /api/gold/health for its one line', /getGoldHealth\('W'\)/.test(brief) && /brfLine\(/.test(brief) && (brief.match(/data-brief-gold/g) ?? []).length === 1)
  const cmdt = src('components/CommodityTab.tsx')
  check('T9 CommodityTab.tsx has no GoldPreOpen and no desk wording', !/GoldPreOpen/.test(cmdt) && !/[Gg]old desk/.test(cmdt) && !/pre-open desk/.test(cmdt.replace(/\/\*\*[\s\S]*?\*\//, '')))
  check('T9 CMDT gold tile carries the GOLD › chip and the chart opens WEEKLY', /data-gold-chip/.test(cmdt) && /setGoldSubInUrl\('weekly'\)/.test(cmdt))
  const mcxg = src('components/McxGoldDesk.tsx')
  check('T9 MCXG: the specs table is gone, the shared selector is in', !/Contract specs — MCX gold family/.test(mcxg) && !/\/api\/mcx\/specs/.test(mcxg) && /<ContractSelector /.test(mcxg))
  check('T9 MCXG: the overlay is one line (no implied-premium prose, no four stats)', !/implied_premium_pct != null \? `MCX premium/.test(mcxg) && !/label="Landed \(no duty\)"/.test(mcxg) && /data-mcx-overlay/.test(mcxg))
  check('T9 MCXG: contract selection is the shared prefs key', /useGoldContract\(\)/.test(mcxg) && !/useState<ContractCode>/.test(mcxg))
  const wei = src('components/WorldMarkets.tsx')
  check('T9 WEI: one extra GOLD line under the GC=F row, hover card, nothing else', (wei.match(/data-wei-gold/g) ?? []).length === 1 && /<GoldHoverCard \/>/.test(wei) && /weiLine\(gold\)/.test(wei))
  // "fair open" as a panel TITLE at most once across the gold views (ui_audit's runtime T9 counts titles, not labels)
  const titles = B4A_VIEWS.flatMap(f => [...src(f).matchAll(/title=\{?["'`]([^"'`]+)["'`]/g)].map(m => m[1]))
  check('T9 "fair open" is the subject of ≤ 1 panel title', titles.filter(t => /fair open/i.test(t)).length <= 1, titles.filter(t => /fair open/i.test(t)))
  // the B4A views never fetch a publisher: everything goes through /api/gold (or /api/mcx on MCXG)
  const hosts = B4A_VIEWS.map(f => src(f)).join('\n').match(/https?:\/\/[a-z0-9.-]+/gi) ?? []
  // link-only anchors (TradingView, CME pages, MCX circulars, DGCX, JPX, the SGE delayed-quotes page tile on DAILY) are allowed; fetch targets are not
  check('T9 no publisher fetch from the views (only link-only anchors)', hosts.every(h => !/yahoo|cftc|cmegroup\.com\/.*ftp|fred\.stlouisfed|spdr|ibja/i.test(h) || /tradingview|cmegroup|mcxindia|dgcx|jpx|en\.sge\.com\.cn/.test(h)), hosts)
}

// ── H. the health sentence and the no-score rule ─────────────────────────────────────────────────
{
  eq('H1 suffix appended once', F.healthLine('WEAK WEEK, DOLLAR-DRIVEN · gold −2.8 % Thu'), `WEAK WEEK, DOLLAR-DRIVEN · gold −2.8 % Thu · ${F.HEALTH_SUFFIX}`)
  eq('H1 suffix kept when present (trailing punctuation stripped)', F.healthLine(`x · ${F.HEALTH_SUFFIX}.`), `x · ${F.HEALTH_SUFFIX}`)
  eq('H1 empty → placeholder', F.healthLine('   '), F.NO_VERDICT)
  check('H1 the suffix is the PLAN wording', F.HEALTH_SUFFIX === 'describes, does not predict' && F.healthLine('x').endsWith('describes, does not predict'))
  check('H2 composite score rejected', F.hasCompositeScore({ score: 3 }) && F.hasCompositeScore({ verdict: {}, OF: 7 }) && F.hasCompositeScore({ tightness_index: 1 }) && !F.hasCompositeScore({ verdict: {}, gauges: [] }))
  const types = src('lib/gold/types.ts')
  const healthBlock = /export interface GoldHealth \{[\s\S]*?\n\}/.exec(types)?.[0] ?? ''
  check('H3 GoldHealth has no score / composite field', healthBlock.length > 0 && !/\bscore\b|composite|tightness|n_of/.test(healthBlock))
  const hv = src('components/gold/HealthView.tsx').replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
  check('H4 HealthView prints the suffix and renders the composite warning, never a number out of 7', /HEALTH_SUFFIX/.test(hv) && /hasCompositeScore/.test(hv) && !/\bof 7\b|\bN of\b|\/ 7\b/.test(hv))
  eq('H5 verdict words ≤ 24 chars with an ellipsis', F.verdictWords('WEAK WEEK, DOLLAR-DRIVEN AND SOMETHING LONGER · x'), 'WEAK WEEK, DOLLAR-DRIVE…')
  eq('H5 the PLAN example (24 chars) is not truncated', F.verdictWords('Weak week, dollar-driven · gold −2.8 %'), 'WEAK WEEK, DOLLAR-DRIVEN')
  eq('H5 verdict words of the placeholder are empty', F.verdictWords(F.NO_VERDICT), '')
}

// ── B. badges: context is neutral, never a buy/sell colour ───────────────────────────────────────
{
  eq('B1 the four badges', Object.keys(F.BADGES), ['signal', 'context', 'arithmetic', 'heuristic'])
  check('B1 context tone is the neutral token', F.BADGES.context.tone === 'muted' && F.badgeSpec('context').tone === 'muted')
  check('B1 context chip names the study and date', /G-STUDY 26 Oct 2026/.test(F.BADGES.context.title))
  check('B1 an unknown badge falls back to context (never signal)', F.badgeSpec('made-up').label === 'CONTEXT' && F.badgeSpec(null).tone === 'muted')
  check('B2 colour only for price changes and arithmetic', !F.mayColour('context') && F.mayColour('arithmetic') && F.mayColour('context', true) && !F.mayColour('heuristic'))
  check('B2 changeTone neutral when colour is not allowed', F.changeTone(-3, false) === 'muted' && F.changeTone(-3, true) === 'red' && F.changeTone(0, true) === 'muted')
  check('B2 arrows allowed on context metrics', F.arrow(2) === '▲' && F.arrow(-1) === '▼' && F.arrow(0) === '')
  const words = B4A_VIEWS.map(f => [f, src(f)] as const).filter(([, s]) => /\b(bullish|bearish)\b/i.test(s)).map(([f]) => f)
  eq('B3 no "bullish/bearish" in the B4A views', words, [])
  check('B4 lag chip: STALE beyond the catalog max age; OFFLINE when unavailable', F.lagChip({ state: 'delayed', age_days: 6 }, 4).label === 'STALE' && F.lagChip({ state: 'unavailable' }).label === 'OFFLINE'
    && F.lagChip({ state: 'live', source: 'Breeze' }).label === 'LIVE · BREEZE' && F.lagChip(null).label === 'NO DATA')
}

// ── M. U+2212 everywhere; no hand-rolled '+' ─────────────────────────────────────────────────────
{
  eq('M1 fmtK', [F.fmtK(104206), F.fmtK(-2883), F.fmtK(0)], ['+104.2k', `${MINUS}2.9k`, '0.0k'])
  eq('M1 fmtSignedPctSp', [F.fmtSignedPctSp(0.4), F.fmtSignedPctSp(-2.83, 2)], ['+0.4 %', `${MINUS}2.83 %`])
  eq('M1 fmtInr0 / fmtUsd', [F.fmtInr0(146079), F.fmtInr0(-5), F.fmtUsd(4007.9, 1), F.fmtUsd(-1.5, 1)], ['₹1,46,079', `${MINUS}₹5`, '$4,007.90'.slice(0, 7) + '9', `${MINUS}$1.50`.replace('$1.50', '$1.5')])
  eq('M1 fmtInUnit converts and groups', [F.fmtInUnit(4000, 'inr_10g', 95), F.fmtInUnit(4000, 'usd_g', null), F.fmtInUnit(4000, 'inr_g', null)],
    [`₹${(4000 * 95 * 10 / F.GRAMS_PER_OZ).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, `$${(4000 / F.GRAMS_PER_OZ).toFixed(3)}`, '—'])
  const plusSign = /\?\s*(['"`])\+\1\s*:\s*(['"`])\2/
  const left = B4A_VIEWS.concat(['components/McxGoldDesk.tsx', 'components/WorldMarkets.tsx', 'components/CommodityTab.tsx', 'lib/gold/format.ts']).filter(f => plusSign.test(src(f)))
  eq('M2 no hand-rolled "+" sign in the gold files', left, [])
  const ascii = B4A_VIEWS.map(f => [f, src(f)] as const).filter(([, s]) => /['"`]-\$\{|['"`]-₹/.test(s)).map(([f]) => f)
  eq('M2 no ASCII minus glued to a currency glyph', ascii, [])
}

// ── U. one unit per column; distinct labels ──────────────────────────────────────────────────────
{
  const wk = src('components/gold/WeeklyView.tsx')
  const colsBlock = /const cols: Column<WeekTableRow>\[\] = \[([\s\S]*?)\n  \]/.exec(wk)?.[1] ?? ''
  const labels = [...colsBlock.matchAll(/label: (?:'([^']+)'|`([^`]+)`)/g)].map(m => m[1] ?? m[2])
  check('U1 week table parsed', labels.length >= 12, labels)
  const units = ['$/oz', '%', 'vol', 'OI Δ', 'lots', '₹/10 g', 'Δ t']
  const numeric = labels.filter(l => !/^Day$|COT/.test(l))
  check('U1 every numeric column names its unit', numeric.every(l => units.some(u => l.includes(u))), numeric.filter(l => !units.some(u => l.includes(u))))
  check('U1 no column mixes $ and ₹', labels.every(l => !(/\$/.test(l) && /₹/.test(l))))
  check('U1 one unit per column (never two currency glyphs)', labels.every(l => (l.match(/\$|₹/g) ?? []).length <= 1))
  eq('U2 unit picker labels distinct', new Set(Object.values(F.UNIT_LABEL)).size, TY.GOLD_UNITS.length)
  eq('U3 the four instrument labels are distinct strings', new Set(Object.values(TY.INSTRUMENTS)).size, 4)
  check('U3 the instrument line names all four', src('components/gold/HealthStrip.tsx').includes('INSTRUMENTS.spot') && src('components/gold/HealthStrip.tsx').includes('INSTRUMENTS.front') && src('components/gold/HealthStrip.tsx').includes('INSTRUMENTS.matched'))
  eq('U4 GOLDTEN is a family (PM decision)', TY.GOLD_FAMILIES.includes('GOLDTEN'), true)
}

// ── S. sessions: DST, the Globex axis, bars ──────────────────────────────────────────────────────
{
  const t = (iso: string) => Date.parse(iso)
  check('S1 US DST on 26 Oct 2026, off 2 Nov 2026', S.usDstActive(t('2026-10-26T06:00:00Z')) && !S.usDstActive(t('2026-11-02T06:00:00Z')))
  check('S1 UK DST ended 25 Oct 2026 01:00 UTC', S.ukDstActive(t('2026-10-24T12:00:00Z')) && !S.ukDstActive(t('2026-10-26T12:00:00Z')))
  eq('S2 Globex open in IST: 03:30 (US summer) / 04:30 (US winter)', [S.fmtHM(S.globexOpenIst(true)), S.fmtHM(S.globexOpenIst(false))], ['03:30', '04:30'])
  eq('S2 MCX close 23:30 / 23:55', [S.fmtHM(S.mcxCloseIst(true)), S.fmtHM(S.mcxCloseIst(false))], ['23:30', '23:55'])
  eq('S2 IST → NY', [S.fmtHM(S.istToNy(18 * 60 + 30, true)), S.fmtHM(S.istToNy(19 * 60 + 30, false))], ['09:00', '09:00'])
  const bands = S.sessionBands({ usDst: true, ukDst: false })
  const london = bands.find(b => b.key === 'london')!, ny = bands.find(b => b.key === 'newyork')!, mcx = bands.find(b => b.key === 'mcx')!
  eq('S3 London 13:30–22:00 IST in GMT', [S.fmtHM(london.start), S.fmtHM(london.end)], ['13:30', '22:00'])
  eq('S3 New York 18:30–23:00 IST in EDT (09:00–13:30 ET, PLAN a.3)', [S.fmtHM(ny.start), S.fmtHM(ny.end)], ['18:30', '23:00'])
  eq('S3 New York 19:30–00:00 IST in EST (PLAN a.3)', (() => { const b = S.sessionBands({ usDst: false, ukDst: false }).filter(x => x.key === 'newyork'); return [S.fmtHM(b[0].start), S.fmtHM(b[0].end)] })(), ['19:30', '00:00'])
  eq('S3 MCX 09:00–23:30 IST', [S.fmtHM(mcx.start), S.fmtHM(mcx.end)], ['09:00', '23:30'])
  check('S3 Shanghai night session is split at midnight', bands.filter(b => b.key === 'shanghai').length === 3 && bands.every(b => b.start < b.end && b.end <= 1440))
  check('S3 the maintenance hour is 17:00–18:00 ET', (() => { const m = bands.find(b => b.key === 'maintenance')!; return S.fmtHM(S.istToNy(m.start, true)) === '17:00' && S.fmtHM(S.istToNy(m.end, true)) === '18:00' })())
  eq('S4 axis position: 0 at the Globex open, wraps', [S.axisPos(S.globexOpenIst(true), true), S.axisPos(S.globexOpenIst(true) - 1, true)], [0, 1439])
  eq('S4 CME trade date: Sunday 20:00 ET belongs to Monday', S.cmeTradeDate(t('2026-10-26T00:00:00Z')), '2026-10-26')
  eq('S4 CME trade date: Monday 16:00 ET is still Monday', S.cmeTradeDate(t('2026-10-26T20:00:00Z')), '2026-10-26')
  eq('S4 IST date / minutes', [S.istDate(t('2026-10-26T20:00:00Z')), S.istMinutes(t('2026-10-26T20:00:00Z'))], ['2026-10-27', 90])
  check('S4 axis ticks every 3 h start after the open', S.axisTicksIst(true, 180)[0].pos === 150 && S.axisTicksIst(true, 180).length === 8)
  // bars
  eq('S5 barMs: ISO day, epoch s, epoch ms', [S.barMs('2026-10-26'), S.barMs(1_761_436_800), S.barMs(1_761_436_800_000)], [Date.UTC(2026, 9, 26), 1_761_436_800_000, 1_761_436_800_000])
  eq('S5 barDate', [S.barDate('2026-10-26T09:30:00+05:30'), S.barDate(Date.UTC(2026, 9, 26, 12))], ['2026-10-26', '2026-10-26'])
  const oneMin = Array.from({ length: 12 }, (_, i) => ({ ts: Date.UTC(2026, 9, 26, 0, i), o: 4000 + i, h: 4001 + i, l: 3999 + i, c: 4000.5 + i, v: 10 }))
  const five = S.resample5m(oneMin)
  eq('S5 resample5m: 12 minutes → 3 buckets, OHLC and volume', [five.length, five[0].o, five[0].h, five[0].l, five[0].c, five[0].v, five[2].v], [3, 4000, 4005, 3999, 4004.5, 50, 20])
  const groups = S.dayGroups([...oneMin, { ts: Date.UTC(2026, 9, 27, 1, 0), o: 1, h: 1, l: 1, c: 1, v: 1 }], true)
  eq('S5 dayGroups by CME trade date', groups.map(g => [g.date, g.pts.length]), [['2026-10-26', 12], ['2026-10-27', 1]])
  const daily = [
    { ts: '2026-10-19', o: 100, h: 101, l: 99, c: 100, v: 1 }, { ts: '2026-10-20', o: 100, h: 103, l: 99, c: 102, v: 1 }, { ts: '2026-10-21', o: 102, h: 104, l: 101, c: 101, v: 1 },
    { ts: '2026-10-22', o: 101, h: 102, l: 98, c: 98, v: 1 }, { ts: '2026-10-23', o: 98, h: 100, l: 97, c: 99, v: 1 }, { ts: '2026-10-26', o: 99, h: 100, l: 98, c: 100, v: 1 },
  ]
  const d = S.dailyOhlc(daily)
  eq('S6 isoWeekKey / weekdayIndex', [S.isoWeekKey('2026-10-26'), S.isoWeekKey('2026-01-01'), S.weekdayIndex('2026-10-26'), S.weekdayIndex('2026-10-25')], ['2026-W44', '2026-W01', 0, 6])
  const wk = S.resampleOhlc(d, 'W')
  eq('S6 weekly candles: Mon–Fri folded, date = last session', wk.map(k => [k.date, k.o, k.h, k.l, k.c]), [['2026-10-23', 100, 104, 97, 99], ['2026-10-26', 99, 100, 98, 100]])
  eq('S6 monthly candles', S.resampleOhlc(d, 'M').length, 1)
  eq('S6 sma(3)', S.sma([1, 2, 3, 4], 3), [null, null, 2, 3])
  const rows = S.weekRows(d, 26)
  eq('S6 weekRows: two weeks, Friday slot filled, week total vs the previous close', [rows.length, rows[0].days[4]?.date, rows[0].total_pct, rows[1].days[0]?.date], [2, '2026-10-23', null, '2026-10-26'])
  near('S6 week total of the second week (100 vs 99)', rows[1].total_pct, (100 / 99 - 1) * 100)
  const ch = S.dailyChanges(d)
  near('S6 daily change 20 Oct', ch.get('2026-10-20') ?? null, 2)
  near('S6 returnOver 7 d (26 Oct vs 19 Oct)', S.returnOver(d, 7) ?? null, 0)
  check('S6 returnOver longer than the history → null', S.returnOver(d, 365) === null)
  const monthly = [10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 1].map((m, i) => ({ date: `${2024 + Math.floor((i + 9) / 12)}-${String(m).padStart(2, '0')}-28`, o: 1, h: 1, l: 1, c: 100 * (1 + 0.01 * i), v: 0 }))
  const season = S.seasonality(monthly)
  check('S7 seasonality: 12 cells, two Januaries, hit rate 1', season.length === 12 && season[0].n === 2 && season[0].hit_rate === 1 && season[6].n === 1)
  eq('S7 percentileOf', [S.percentileOf([1, 2, 3, 4], 3), S.percentileOf([], 1), S.percentileOf([1], null)], [75, null, null])
  eq('S8 shiftDays / closeOnOrBefore', [S.shiftDays('2026-03-01', -1), S.closeOnOrBefore(d, '2026-10-24'), S.closeOnOrBefore(d, '2026-10-18')], ['2026-02-28', 99, null])
}

// ── P. prefs, URL state, the gate, the echoes ────────────────────────────────────────────────────
{
  eq('P1 parseContractSel defaults and sanitises', PR.parseContractSel('{"family":"GOLDTEN","expiry":"2026-11-05","exchange":"XYZ","options":1}'), { exchange: 'MCX', family: 'GOLDTEN', expiry: '2026-11-05', options: false })
  eq('P1 garbage → default', PR.parseContractSel('nope'), PR.DEFAULT_SEL)
  const search = PR.buildGoldSearch('?tab=gold&x=1', { sub: 'weekly', family: 'GOLDM', expiry: '2026-12-04', unit: 'inr_10g', window: 'W' })
  eq('P2 URL round trip keeps other params', PR.parseGoldUrl(search), { sub: 'weekly', family: 'GOLDM', expiry: '2026-12-04', unit: 'inr_10g', window: 'W' })
  check('P2 tab kept, gold params stripped on leave', search.includes('tab=gold') && search.includes('x=1') && PR.stripGoldSearch(search) === '?tab=gold&x=1')
  eq('P2 unknown values ignored', PR.parseGoldUrl('?sub=nope&c=SILVER&unit=oz&win=Q&exp=2026-13-99'), {})
  eq('P3 publishGate', [F.publishGate({ A: { verdict: 'PUBLISH-CORE', badge: 'context' }, B: { verdict: 'LINK-ONLY', badge: 'context' }, C: { verdict: 'PUBLISH-CONTEXT' } }, 'A'),
    F.publishGate({ A: { verdict: 'PUBLISH-CORE', badge: 'context' } }, 'B'), F.publishGate({ A: { verdict: 'PUBLISH-CORE', badge: 'context' }, B: { verdict: 'LINK-ONLY', badge: 'context' } }, 'B'),
    F.publishGate({ C: { verdict: 'PUBLISH-CONTEXT' } }, 'C'), F.publishGate({}, 'A'), F.publishGate(null, null)], ['ok', 'no-verdict', 'no-verdict', 'no-verdict', 'unknown', 'unknown'])
  const h: GoldHealth = {
    as_of: '2026-10-26T09:00:00+05:30', window: 'W', line: '', freshness: { state: 'delayed' },
    verdict: { line: 'Weak week, dollar-driven · gold −2.8 % Thu was the dollar and real yields, not futures selling', clauses: [] },
    gauges: [
      { key: 'positioning', label: 'POSITIONING', value: 104206, unit: 'contracts', change: -2883, state: 'delayed', badge: 'context' },
      { key: 'curve_roll', label: 'CURVE', value: 1.03, unit: '%', state: 'delayed', badge: 'arithmetic', rule: '(F2/F1 − 1) × 365/days', front: 'DEC-26', next: 'FEB-27', fnd_date: '2026-11-30' },
    ],
    fair: { fair_value: 144181, mcx_live: null, premium_rupees: null, premium_pct: null, comex: 4004.3, comex_symbol: 'GCZ26.CMX', usdinr: 94.93, landed: 122042, duty_pct: 15,
            duty_paid_landed: 140348, basis_pct: 0.4, settlement: 146079, settlement_session: '2026-10-22' },
  }
  eq('P4 WEI line (fallback: the payload has no server line)', F.weiLine(h), `GOLD · WEAK WEEK, DOLLAR-DRIVEN · basis +0.4 % · COT MM +104.2k (${MINUS}2.9k) · roll DEC→FEB · FND 30 Nov`)
  check('P4 WEI line never prints the gauge rule prose', !/F2\/F1/.test(F.weiLine(h)))
  const serverWei = `GOLD · NO FRESH READ · basis +0.4 % · COT MM +104k (${MINUS}2.9k) · roll DEC-26→FEB-27 2026-11-30 · GOLD ›`
  eq('P4 WEI renders the SERVER line verbatim (minus the GOLD › the chip renders)', F.weiLine({ ...h, line: serverWei, lines: { wei: serverWei, brf: null } }), serverWei.replace(' · GOLD ›', ''))
  eq('P4 verdict words come from verdict.headline; a number-first clause is not a verdict', [F.healthWords({ ...h, verdict: { ...h.verdict, headline: 'Weak week, dollar-driven' } }), F.healthWords({ ...h, verdict: { line: 'FUNDS NET 104,206 (−2.7 % w/w) · x', clauses: [] } }), F.healthWords(h)],
    ['WEAK WEEK, DOLLAR-DRIVEN', '', 'WEAK WEEK, DOLLAR-DRIVEN'])
  eq('P4 naive store timestamps are UTC, not local (COT release_at 19:30Z = 01:00 IST Sat)', [F.istClock('2026-10-30T19:30:00'), F.istClock('2026-10-30T19:30:00+05:30'), F.utcClock('2026-10-30 19:30:00'), F.parseIso('nope')],
    ['01:00 IST', '19:30 IST', '19:30Z', null])
  eq('P4 evidence chips name the study; the finding is on hover', [F.badgeSpec('context', 'G-STUDY 26 Oct 2026: explains the week — does not forecast').label,
    F.badgeSpec('context', 'short').label, /does not forecast/.test(F.badgeSpec('context', 'G-STUDY 26 Oct 2026: explains the week — does not forecast').title)],
    ['CONTEXT · G-STUDY 26 Oct 2026', 'CONTEXT · short', true])
  check('P4 lag chip source is shortened on the chip, full in the title', F.lagChip({ state: 'delayed', source: 'SPDR Gold Shares (displayed with attribution)' }).label.length < 32
    && /displayed with attribution/.test(F.lagChip({ state: 'delayed', source: 'SPDR Gold Shares (displayed with attribution)' }).title))
  check('P4 WEI line uses U+2212 only', !/-\d/.test(F.weiLine(h)))
  const before = F.brfLine(h, 8 * 60 + 50)
  eq('P4 BRF before the open (fallback: no server line, no live quote → no OK/WAIT)', [before.phase, before.text], ['before_open', `Gold open: fair ₹1,44,181 (gap ${MINUS}1,898) · WEAK WEEK, DOLLAR-DRIVEN`])
  const waitF = F.brfLine({ ...h, fair: { ...h.fair, mcx_live: 144700, premium_rupees: 519 } }, 8 * 60 + 50)
  check('P4 BRF fallback prints WAIT beyond the ₹300 limit, coloured red, words neutral', / · WAIT · /.test(waitF.text) && waitF.segments.find(s => s.text === 'WAIT')?.tone === 'red'
    && waitF.segments.filter(s => /WEAK WEEK/.test(s.text)).every(s => s.tone === 'muted'))
  const after = F.brfLine({ ...h, fair: { ...h.fair, actual_open: 142058, fair_value: 144181, snapshot_fair: 144938, snapshot_error: -2880 } }, 9 * 60 + 20)
  eq('P4 BRF after the captured open = the 08:45 SNAPSHOT fair and its measured error, not the live fair value', [after.phase, after.text], ['after_open', `Gold opened ₹1,42,058 vs fair ₹1,44,938 (miss ${MINUS}₹2,880) · WEAK WEEK, DOLLAR-DRIVEN`])
  check('P4 BRF the miss is the only coloured run (amber beyond the limit), the words stay neutral', after.segments.find(s => /miss/.test(s.text))?.tone === 'amber' && after.segments.filter(s => /WEAK/.test(s.text)).every(s => s.tone === 'muted'))
  const hol = F.brfLine({ ...h, fair: { ...h.fair, mcx_holiday: { name: 'Dussehra', closure: 'morning', opens_at: '17:00' } } }, 10 * 60)
  eq('P4 BRF on an MCX morning closure', [hol.phase, hol.text], ['holiday', 'Gold: MCX closed (Dussehra, opens 17:00) · WEAK WEEK, DOLLAR-DRIVEN'])
  eq('P4 BRF without health', F.brfLine(null, 600).text, 'Gold: health unavailable')
  const serverBrf = 'Gold opened ₹1,42,058 vs fair ₹1,44,938 (miss ₹−2,880) · WEAK WEEK, DOLLAR-DRIVEN · GOLD ›'
  const srv = F.brfLine({ ...h, brf_line: serverBrf, lines: { wei: null, brf: serverBrf }, fair: { ...h.fair, fair_value: 150000, actual_open: 142058 } }, 11 * 60)
  eq('P4 BRF renders the SERVER brf_line verbatim (Indian grouping, no GOLD ›): the live fair value (150,000 here) never leaks into the morning call', [srv.phase, srv.text], ['after_open', serverBrf.replace(' · GOLD ›', '')])
  eq('P4 BRF server line: western ₹ groups become Indian', F.brfLine({ ...h, brf_line: 'Gold opened ₹122,271 vs fair ₹123,091 (miss ₹−820) · GOLD ›' }, 600).text, 'Gold opened ₹1,22,271 vs fair ₹1,23,091 (miss ₹−820)')
  check('P4 BRF server form: miss parsed with the glyph before the sign', srv.segments.find(s => /miss/.test(s.text))?.tone === 'amber')
  const okSrv = F.brfLine({ ...h, brf_line: 'Gold open: fair ₹1,44,181 (gap −1,898) · OK · WEAK WEEK, DOLLAR-DRIVEN · GOLD ›' }, 8 * 60)
  eq('P4 BRF segments: OK green, everything else neutral', okSrv.segments.map(s => s.tone), ['muted', 'green', 'muted', 'muted'])
  const brf = src('components/Brief.tsx')
  check('P4 Brief.tsx renders the segments (colour on the arithmetic only) and lets the line wrap', /goldLine\.segments\.map/.test(brf) && !/color: goldHealth\.data \? goldTone/.test(brf)
    && !/data-brief-gold[\s\S]{0,400}textOverflow: 'ellipsis'/.test(brf))
  eq('P4 MCXG one-line overlay', F.mcxOverlayLine(h.fair), 'COMEX GCZ26 $4,004.30 · ₹/$ 94.93 · duty-paid landed ₹1,40,348 · fair ₹1,44,181 · live vs fair —'.replace('$4,004.30', '$4,004.3'))
  check('P4 the overlay line has no implied-premium prose', !/premium/i.test(F.mcxOverlayLine(h.fair)))
  eq('P5 session labels by session, never the file date', [F.sessionLabel('2026-10-22'), F.sessionLabel(null, 'Thu 22 Oct settlement'), F.dayLabel('2026-10-20'), F.comexMonthLabel('GCZ26.CMX'), F.comexCode('GC=F'), F.expiryMonthLabel('2026-12-04')],
    ['Thu 22 Oct settlement', 'Thu 22 Oct settlement', 'Tue 20 Oct', 'DEC-26', 'GC1', 'DEC-26'])
  eq('P6 countdown / clocks', [F.countdown(3 * 3600 + 4 * 60 + 9), F.countdown(0), F.utcClock('2026-10-26T00:13:00Z'), F.istClock('2026-10-26T00:13:00Z')], ['3h04m', 'now', '00:13Z', '05:43 IST'])
  // contracts helpers
  const fam = (code: string, tick: number, pct: number, oi: number, purity = '995', rule = '5th') => ({ code, purity, expiry_rule: rule, tick_value: tick, hedge_ratio_oz: tick / 3.1, round_trip: { pct, total: 1 }, expiries: [{ oi, margin_inr: 1000 * tick, margin_pct: 9.25 }] })
  const diff = F.contractDiff(fam('GOLD', 100, 0.018, 16650), fam('GOLDPETAL', 1, 0.344, 20000, '999', 'month-end'))
  eq('P7 diff strip keys', diff.map(d => d.key), [...F.DIFF_KEYS])
  check('P7 diff strip flags what changed', diff.every(d => d.changed) && diff.find(d => d.key === 'cost_pct')!.to === '0.344 %')
  eq('P7 diff of the same family: nothing changed', F.contractDiff(fam('GOLD', 100, 0.018, 1), fam('GOLD', 100, 0.018, 1)).filter(d => d.changed), [])
  check('P7 roll warning', /roll in progress/.test(F.rollWarning(-3000, 1200) ?? '') && /under way/.test(F.rollWarning(-500, 1200) ?? '') && F.rollWarning(100, 100) === null && F.rollWarning(null, 1) === null)
  near('P7 annualised carry (F2/F1 − 1) × 365/days', F.annualisedCarry(100, 101, 365), 1)
  eq('P7 daysBetween / daysWord', [F.daysBetween('2026-10-26', '2026-11-30'), F.daysWord('2026-11-30', '2026-10-26'), F.daysWord('2026-10-26', '2026-10-26'), F.daysWord('2026-10-20', '2026-10-26')], [35, 'in 35 d', 'today', '6 d ago'])
}

// ── I. panel ids and tooltip keys ────────────────────────────────────────────────────────────────
{
  const kitSrc = src('components/gold/kit.tsx')
  const PLAN_IDS = new Set(['h.verdict', 'h.gauges', 'h.open', 'h.accuracy', 'h.moved', 'h.events', 'h.headlines', 'h.brief',
    'd.24h', 'd.3day', 'd.sge', 'd.quadrant', 'd.tape', 'w.candles', 'w.table', 'w.grid', 'w.whodid',
    'm.candles', 'm.ladder', 'm.season', 'm.official', 'm.physical', 'm.balance', 'm.liquidity',
    'c.selector', 'c.comex', 'c.mcx', 'c.roll', 'c.spec', 'c.links'])
  const ids = B4A_VIEWS.flatMap(f => [...src(f).matchAll(/(?:<GoldPanel[^>]*?\sid=|data-gold-panel=)"([a-z]+\.[a-z0-9.]+)"/g)].map(m => m[1]))
  eq('I1 every B4A panel id is a PLAN a.* id', ids.filter(i => !PLAN_IDS.has(i)), [])
  const seen = new Set(ids)
  eq('I1 the B4A sub-views cover their PLAN panels', [...PLAN_IDS].filter(i => !seen.has(i)), [])
  check('I1 no panel id is rendered twice across the B4A views', ids.length === seen.size, ids.filter((x, i) => ids.indexOf(x) !== i))
  const tips = JSON.parse(src('lib/gold/tooltips.json')) as { tooltips?: Record<string, string> } & Record<string, unknown>
  const tipMap = (tips.tooltips ?? tips) as Record<string, string>
  const used = B4A_VIEWS.flatMap(f => [...src(f).matchAll(/\btip\('([a-z0-9_]+)'\)|tooltips\['([a-z0-9_]+)'\]/g)].map(m => m[1] ?? m[2]))
  // G-EDU/tooltips.json is the source of truth (wave 1b): the UI copy follows it key for key; a key in either counts
  const geduPath = path.resolve(UI, '..', 'reports', 'gold_program', 'G-EDU', 'tooltips.json')
  const gedu = fs.existsSync(geduPath) ? ((JSON.parse(fs.readFileSync(geduPath, 'utf8')) as { tooltips?: Record<string, string> }).tooltips ?? {}) : {}
  eq('I2 every tooltip key the B4A views use exists in tooltips.json (UI copy or G-EDU)', [...new Set(used)].filter(k => !(k in tipMap) && !(k in gedu)), [])
  // §f.2: the rendering gate on EVERY panel — each <GoldPanel> names the catalog series it reads (`series=`; [] for a
  // link-only / request-path panel) and hands the catalog over, so kit.tsx can blank it without a PUBLISH verdict
  // (the attribute block of each <GoldPanel …> runs to the next <GoldPanel; a panel's children never carry another's attrs)
  const panels = B4A_VIEWS.flatMap(f => src(f).split('<GoldPanel ').slice(1).map(chunk => [f, chunk.split('<GoldPanel ')[0]] as const))
  const attrsOf = (chunk: string) => chunk.slice(0, chunk.search(/>\s*\n|>\s*</) + 1)
  check('I4 every B4A panel is gated (series= and catalog=)', panels.length >= 29 && panels.every(([, c]) => /\bseries=\{/.test(attrsOf(c)) && /\bcatalog=\{/.test(attrsOf(c))),
    panels.filter(([, c]) => !/\bseries=\{/.test(attrsOf(c)) || !/\bcatalog=\{/.test(attrsOf(c))).map(([f, c]) => `${f}: ${/id="([^"]+)"/.exec(c)?.[1]}`))
  // the generated data dictionary lists every catalog row (docs/GOLD_DATA_DICTIONARY.md, from catalog_seed.py)
  const dictPath = path.resolve(UI, '..', 'docs', 'GOLD_DATA_DICTIONARY.md')
  const dict = fs.existsSync(dictPath) ? fs.readFileSync(dictPath, 'utf8') : ''
  const seriesUsed = [...new Set(B4A_VIEWS.flatMap(f => [...src(f).matchAll(/series=\{(?:inr \? )?\[([^\]]*)\]/g)].flatMap(m => [...m[1].matchAll(/'([A-Z0-9_]+)'/g)].map(x => x[1]))))]
  check('I4 the views gate on ≥ 40 distinct catalog series', seriesUsed.length >= 40, seriesUsed.length)
  eq('I4 every gated series id is a catalog row (GOLD_DATA_DICTIONARY.md)', dict ? seriesUsed.filter(id => !dict.includes(`| ${id} |`)) : [], [])
  check('I4 kit.tsx blanks a panel without a PUBLISH verdict and notes an unloaded catalog', /panelGate\(catalog, series\)/.test(kitSrc) && /gate\.gate === 'no-verdict'/.test(kitSrc) && /catalog\?/.test(kitSrc))
  check('I2 tooltips.json carries the 93+ one-liners', Object.keys(tipMap).length >= 93)
  // the catalog "about" popover and the [B]/[P] micro-copy exist on every panel (PLAN a.1)
  const kit = src('components/gold/kit.tsx')
  check('I3 GoldPanel renders badge · lag chip · about · [B]/[P] copy', /<BadgeChip badge=\{badge\}/.test(kit) && /<LagChipEl freshness=\{freshness\}/.test(kit) && /<About row=\{row\}/.test(kit) && /data-gold-copy=\{layer\}/.test(kit))
  check('I3 the "no verdict — not published" placeholder exists', F.NO_VERDICT === 'no verdict — not published' && /NoVerdict/.test(src('components/gold/HealthView.tsx')))
}

// ── F. wave 1b fixes stay fixed ───────────────────────────────────────────────────────────────────
{
  const api = src('lib/gold/api.ts')
  check('F1 api.ts sends the family on /positioning/daily and /curve', /getGoldPositioningDaily = \(exchange: 'COMEX' \| 'MCX', days = 60, family\?/.test(api) && /getGoldCurve = \(exchange: 'COMEX' \| 'MCX', date\?: string, family\?/.test(api))
  check('F1 WEEKLY / DAILY / CONTRACTS pass the picked family', /getGoldPositioningDaily\('MCX', 90, sel\.family\)/.test(src('components/gold/WeeklyView.tsx'))
    && /getGoldPositioningDaily\('MCX', 20, sel\.family\)/.test(src('components/gold/DailyView.tsx')) && /getGoldCurve\('MCX', undefined, sel\.family\)/.test(src('components/gold/ContractsView.tsx')))
  check('F1 CONTRACTS filters the chain by equality, not startsWith', !/startsWith\(sel\.family\)/.test(src('components/gold/ContractsView.tsx')))
  check('F1 WEEKLY / MONTHLY ask /bars for the Yahoo symbol (API_CONTRACT §2.4)', /const DAILY_SYMBOL = 'GC=F'/.test(src('components/gold/WeeklyView.tsx')) && /const DAILY_SYMBOL = 'GC=F'/.test(src('components/gold/MonthlyView.tsx')))
  check('F1 MONTHLY memoises its 26-year payloads', (src('components/gold/MonthlyView.tsx').match(/memoGet\(/g) ?? []).length >= 5)
  const pre = src('components/gold/GoldPreOpen.tsx')
  check('F2 the EVENT WORDS chip keys on the flagged-headline count, never on `advice` (null by design)', /flagged_headlines \?\? 0\) > 0/.test(pre) && !/event_risk\.advice/.test(pre))
  const gp = src('components/gold/GoldPage.tsx')
  check('F3 the page window defaults to W (WEI / BRF read ?window=W)', /useState<Window>\(initial\.window \?\? 'W'\)/.test(gp))
  check('F3 a deep link\'s ?c=/?exp= is a page-local override, never written to prefs on mount', /useState<Partial<GoldContractSel> \| null>/.test(gp) && !/updateSel\(\{ \.\.\.\(initial\.family/.test(gp) && !/updateStored\(\{ \.\.\.\(initial/.test(gp))
  check('F4 c.links wears a plain LINK-ONLY chip, no evidence badge', /LINK-ONLY<\/Chip>/.test(src('components/gold/ContractsView.tsx')) && !/<BadgeChip badge="context" evidence="links"/.test(src('components/gold/ContractsView.tsx')))
  check('F4 c.mcx has its own full-width row', /id="c\.mcx"[\s\S]{0,300}gridColumn: '1 \/ -1'/.test(src('components/gold/ContractsView.tsx')))
  check('F5 DAILY gates the SGE panel on the catalog id SGE_DAILY (not an invented one)', /series=\{\['SGE_DAILY'\]\}/.test(src('components/gold/DailyView.tsx')) && !/SGE_AU9999 \?\?/.test(src('components/gold/DailyView.tsx')))
  check('F5 the POSITIONING tile copy is a rule; g.words carries the state', !/long, not crowded\.'/.test(src('components/gold/HealthView.tsx')) && /g\.words &&/.test(src('components/gold/HealthView.tsx')))
  const kitSrc = src('components/gold/kit.tsx')
  check('F6 kit.tsx parses store timestamps through parseIso', /parseIso\(f\.as_of\)/.test(kitSrc) && !/new Date\(f\.as_of\)/.test(kitSrc))
}

// ── W. wave 1c: the critics' fixes stay fixed (C-TRADER / C-BEGINNER / C-DATA refs in the names) ─────────────────
{
  // C-TRADER-1 / C-DATA-1: a zone-less store timestamp is UTC; offsets are taken as written; a 1-minute bar renders at the IST
  // time freshness.as_of says (the store's last bar '2026-11-04T21:04:56' ↔ as_of '2026-11-05T02:34:56+05:30')
  eq('W1 barMs: zone-less = UTC, Z and +05:30 as written, space-separated too', [S.barMs('2026-11-04T21:04:56'), S.barMs('2026-11-04T21:04:56Z'), S.barMs('2026-11-05T02:34:56+05:30'), S.barMs('2026-11-04 21:04:56'), S.barMs('2026-11-04T21:04:56+00:00')],
    [Date.UTC(2026, 10, 4, 21, 4, 56), Date.UTC(2026, 10, 4, 21, 4, 56), Date.UTC(2026, 10, 4, 21, 4, 56), Date.UTC(2026, 10, 4, 21, 4, 56), Date.UTC(2026, 10, 4, 21, 4, 56)])
  eq('W1 the last 1m bar renders at the IST clock of freshness.as_of (02:34 IST, not 21:04)', [S.barIstHM('2026-11-04T21:04:56'), F.istClock('2026-11-05T02:34:56+05:30')], ['02:34', '02:34 IST'])
  check('W1 negative control: a browser-local parse of the same string would be 5 h 30 m early (so the rule matters)', new Date('2026-11-04T21:04:56').getTime() !== S.barMs('2026-11-04T21:04:56') || new Date().getTimezoneOffset() === 0)
  eq('W1 dayGroups places a zone-less 18:09 UTC bar on the right CME trade date and IST position', (() => { const g = S.dayGroups([{ ts: '2026-11-04T18:09:59', o: 1, h: 1, l: 1, c: 4070, v: 1 }], false); return [g[0].date, S.fmtHM(S.istMinutes(g[0].pts[0].ms))] })(), ['2026-11-04', '23:39'])
  // C-TRADER-2 / C-TRADER-17: legend closes from the STORED daily bars, today is 'last', the dashed line is the previous session's close
  const dly = S.dailyOhlc([{ ts: '2026-11-02', o: 1, h: 1, l: 1, c: 3969.6, v: 1 }, { ts: '2026-11-03', o: 1, h: 1, l: 1, c: 3940.4, v: 1 }])
  const grp = [{ date: '2026-11-02', pts: [{ c: 3937.1 }] }, { date: '2026-11-03', pts: [{ c: 3949.8 }] }, { date: '2026-11-04', pts: [{ c: 4073.2 }] }]
  const leg = S.legendCloses(grp, dly, { price: 4078.3 }, 3)
  eq('W2 legend: finished sessions at the stored close (3,940.4, not the bucket end 3,949.8); today = live last', leg.map(r => [r.date, r.px, r.kind, r.bucketFallback]), [['2026-11-02', 3969.6, 'close', false], ['2026-11-03', 3940.4, 'close', false], ['2026-11-04', 4078.3, 'last', false]])
  eq('W2 legend Δ references: each vs the stored close of the session before', leg.map(r => r.prevClose), [null, 3969.6, 3940.4])
  eq('W2 negative control: a date with no daily bar falls back to the bucket end and SAYS so', S.legendCloses([{ date: '2026-11-03', pts: [{ c: 3949.8 }] }, { date: '2026-11-04', pts: [{ c: 1 }] }], [], null, 3)[0], { date: '2026-11-03', px: 3949.8, kind: 'close', prevClose: null, bucketFallback: true })
  eq('W2 the dashed line is the PREVIOUS session\'s stored close, never today\'s last', [S.prevSessionClose(dly, '2026-11-04'), S.prevSessionClose(dly, '2026-11-03'), S.prevSessionClose([], '2026-11-04')], [{ date: '2026-11-03', c: 3940.4 }, { date: '2026-11-02', c: 3969.6 }, null])
  const dv = src('components/gold/DailyView.tsx')
  check('W2 DailyView draws the server settle_line only when it is a settlement (never a last trade) and labels the fallback as a Yahoo daily close', /last\.\?trade/.test(dv) && /close \(Yahoo daily, not settlement\)/.test(dv) && /legendCloses\(/.test(dv))
  // C-DATA-7 / C-BEGINNER-21 / C-DATA-18: the Δ text branches on change_unit
  eq('W3 gaugeChange: Shanghai week change is $/oz, never a %', F.gaugeChangeText({ key: 'shanghai', unit: '$/oz', change: 47.36, change_unit: '$/oz', change_window: 'W' }), '+$47.36/oz W')
  eq('W3 gaugeChange: without change_unit a $/oz tile still prints $/oz (the old bug printed +47.36 %)', F.gaugeChangeText({ key: 'shanghai', unit: '$/oz', change: 47.36, change_window: 'W' }), '+$47.36/oz W')
  eq('W3 gaugeChange: the price tile is % of price; contracts / tonnes keep their unit; real yield prints bp from change_bp', [F.gaugeChangeText({ key: 'trend', unit: '$/oz', change: 0.6689, change_unit: '%', change_window: 'W' }, true), F.gaugeChangeText({ key: 'positioning', unit: 'contracts', change: 1356, change_unit: 'contracts', change_window: 'W' }),
    F.gaugeChangeText({ key: 'etf', unit: 't', change: -2.85, change_unit: 't', change_window: 'D' }), F.gaugeChangeText({ key: 'real_yield', unit: '%', change: null, change_bp: -4, change_window: 'W' }), F.gaugeChangeText({ key: 'x', unit: '%', change: null })],
    ['+0.67 % W', '+1,356 contracts W', `${MINUS}2.85 t D`, `${MINUS}4 bp W`, ''])
  eq('W3 gaugeChange: a % level without change_unit is in bp (0.02 pp → +2 bp); with change_unit bp the value is already bp', [F.gaugeChangeText({ key: 'ry', unit: '%', change: 0.02 }), F.gaugeChangeText({ key: 'ry', unit: '%', change: -4, change_unit: 'bp' })], ['+2 bp', `${MINUS}4 bp`])
  check('W3 HealthView renders the Δ through gaugeChangeText and never fmtSignedPctSp on a non-price tile', /gaugeChangeText\(g, priceTile\)/.test(src('components/gold/HealthView.tsx')) && !/fmtSignedPctSp\(g\.change/.test(src('components/gold/HealthView.tsx')))
  // C-TRADER-11 / C-DATA-21 / C-DATA-9: the whole week, impact order, past rows dropped, ★ only High or an FOMC decision
  const evs = [
    { event_date: '2026-11-05', time_ist: '03:00', impact: 'Low', kind: 'US_DATA', name: 'Already out' },
    { event_date: '2026-11-05', time_ist: '19:20', impact: 'Low', kind: 'FOMC', name: 'FOMC Member Hammack Speaks' },
    { event_date: '2026-11-06', time_ist: '19:00', impact: 'High', kind: 'US_NFP', name: 'Non-Farm Employment Change' },
    { event_date: '2026-11-05', time_ist: '19:00', impact: 'Medium', kind: 'US_CLAIMS', name: 'Unemployment Claims' },
    { event_date: '2026-11-05', time_ist: '23:30', impact: 'context', kind: 'MCX_EXPIRY', name: 'MCX GOLDM expiry' },
    { event_date: '2026-11-06', time_ist: null, impact: 'context', kind: 'FESTIVAL', name: 'Dhanteras' },
    { event_date: '2026-11-11', time_ist: '00:30', impact: 'High', kind: 'FOMC', name: 'FOMC Statement' },
    ...Array.from({ length: 12 }, (_, i) => ({ event_date: '2026-11-07', time_ist: `${10 + i}:00`, impact: 'Low', kind: 'US_DATA', name: `filler ${i}` })),
  ]
  const ordered = F.orderEvents(evs, '2026-11-05T12:00')
  eq('W4 orderEvents: the past 03:00 row is dropped, nothing else is cut (18 of 19 rows), High first then Medium, roll/holiday, Low', [ordered.length, ordered[0].name, ordered[1].name, ordered[2].name, ordered[3].name, ordered[4].name, ordered[5].name, ordered[6].name],
    [18, 'Non-Farm Employment Change', 'FOMC Statement', 'Unemployment Claims', 'MCX GOLDM expiry', 'Dhanteras', 'FOMC Member Hammack Speaks', 'filler 0'])
  check('W4 orderEvents: a dated row without a time stays all day; with no clock nothing is dropped', F.orderEvents([{ event_date: '2026-11-05', time_ist: null, impact: 'Low', kind: 'X', name: 'all day' }], '2026-11-05T23:50').length === 1 && F.orderEvents(evs).length === 19)
  check('W4 ★ on High and on an FOMC decision, never on a Fed speaker or a Low row', F.eventStar({ impact: 'High', kind: 'US_NFP', name: 'NFP' }) && F.eventStar({ impact: 'Low', kind: 'FOMC', name: 'FOMC Statement' }) && !F.eventStar({ impact: 'Low', kind: 'FOMC', name: 'FOMC Member Hammack Speaks' }) && !F.eventStar({ impact: 'High', kind: 'FOMC', name: 'Fed Chair Powell Speaks' }) && !F.eventStar({ impact: 'Low', kind: 'US_DATA', name: 'Natural Gas Storage' }))
  check('W4 HealthView renders every ordered row (no .slice cap) through orderEvents', /orderEvents\(events\.data\?\.events/.test(src('components/gold/HealthView.tsx')) && !/eventRows\.slice\(0, 14\)|events\.slice\(0, 14\)/.test(src('components/gold/HealthView.tsx')))
  // C-TRADER-15 / C-DATA-12: the brief header reads the TOP-LEVEL bias / confidence; open_signal never renders
  eq('W5 briefHeader: top-level fields; synthesis fallback; never open_signal', [F.briefHeader({ bias: 'neutral', confidence: 0.45, label: null, doc: { open_signal: 'aligned_tradeable' } }), F.briefHeader({ bias: null, confidence: null, label: null, doc: { synthesis: { bias: 'bearish', confidence: 0.6 } } }), F.briefHeader({ bias: null, confidence: null, label: null, doc: {} })],
    ['automated brief · bias neutral · confidence 45 %', 'automated brief · bias bearish · confidence 60 %', 'automated brief · bias — · confidence —'])
  check('W5 HealthView never renders open_signal and reads the top-level fields through briefHeader', !/open_signal/.test(src('components/gold/HealthView.tsx').replace(/\/\*[\s\S]*?\*\//g, '').replace(/copyP="[^"]*"/g, '')) && /briefHeader\(b\)/.test(src('components/gold/HealthView.tsx')))
  // C-BEGINNER-4 / C-TRADER-13 / C-DATA-8: the DES card by the matched month, tick in display units, settlement and uom in words
  eq('W6 comexMmy / mmyLabel / specMatches', [F.comexMmy('GCZ26.CMX'), F.comexMmy('GC=F'), F.mmyLabel('202611'), F.specMatches({ mmy: '202611' }, 'GCZ26.CMX'), F.specMatches({ mmy: '202612' }, 'GCZ26.CMX'), F.specMatches({ mmy: null }, 'GCZ26.CMX')], ['202612', null, 'NOV-26', false, true, null])
  eq('W6 specTick: the PRF MinPxIncr 1.0 × DisplayFactor 0.1 = $0.10 = $10; a server tick_usd wins; GC convention without a factor', [F.specTick({ symbol: 'GC', min_px_incr: 1, display_factor: 0.1, multiplier: 100 }), F.specTick({ symbol: 'GC', min_px_incr: 1, tick_usd: 0.1, multiplier: 100 }), F.specTick({ symbol: 'GC', min_px_incr: 1, multiplier: 100 }), F.specTick({ symbol: 'SI', min_px_incr: 0.005, multiplier: 5000 }), F.specTick(null)],
    [{ tick: 0.1, value: 10 }, { tick: 0.1, value: 10 }, { tick: 0.1, value: 10 }, { tick: 0.005, value: 25 }, null])
  eq('W6 settlement / uom words', [F.settlMethodWord('P'), F.settlMethodWord('physical delivery'), F.settlMethodWord('C'), F.settlMethodWord(null), F.uomWord('oz_tr'), F.uomWord('kg'), F.uomWord(null)], ['physical delivery', 'physical delivery', 'cash-settled', '—', 'troy oz', 'kilograms', 'oz'])
  eq('W6 margin history: the $25 row of another product is dropped, one point per date, ≥ 3 dates', [F.marginHistoryPoints([{ trade_date: '2026-11-04', margin_usd: 25 }, { trade_date: '2026-11-04', margin_usd: 19785 }, { trade_date: '2026-11-03', margin_usd: 19700 }, { trade_date: '2026-11-02', margin_usd: 19600 }]), F.marginHistoryPoints([{ trade_date: '2026-11-04', margin_usd: 19785 }])], [[19600, 19700, 19785], []])
  const cv = src('components/gold/ContractsView.tsx')
  check('W6 ContractsView: the card names the PRF month, flags a mismatch, prints the tick through specTick and the words', /specMatches\(spec, comexMatched\)/.test(cv) && /data-gold-spec-mismatch/.test(cv) && /specTick\(spec\)/.test(cv) && /settlMethodWord\(/.test(cv) && /uomWord\(spec\.uom\)/.test(cv) && /marginHistoryPoints\(spec\.margin_history\)/.test(cv))
  check('W6 the term structure marks the matched month\'s FND and the ladder heads its carry "to next month" (C-TRADER-24 / C-DATA-16)', /data-gold-fnd-tick/.test(cv) && /carry to next month % p\.a\./.test(cv) && /days to last trade/.test(cv))
  // C-BEGINNER-5 / C-DATA-11 / C-TRADER-10: basis clock labels
  eq('W7 basisClockLabel / liveBasisPct', [F.basisClockLabel(1.5, 'Tue 03 Nov settlement'), F.basisClockLabel(null, 'x'), F.basisClockLabel(0.41, null), F.liveBasisPct(143249, 142663), F.liveBasisPct(1, 0), F.liveBasisPct(null, 1)],
    ['basis +1.50 % at the Tue 03 Nov settlement vs that session\'s duty-paid', 'basis —', 'basis +0.41 % at the last settlement vs that session\'s duty-paid', (143249 / 142663 - 1) * 100, null, null])
  const hs = src('components/gold/HealthStrip.tsx').replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
  check('W7 the strip: no "NO DATA" beside a live price; settle — says the backfill is coming; the matched last is labelled Yahoo, not settlement; the settlement basis names its session', !/NO DATA/.test(hs) && /arrives with the CME backfill/.test(hs) && /not settlement/.test(hs) && /at the \{basisSession\} vs that session/.test(hs) && /COT funds net \(managed money\)/.test(hs))
  check('W7 the strip shows the live MCX above the settlement while the session runs and a live-vs-now basis (C-TRADER-10)', /mcxLive != null && mcxTrading/.test(hs) && /basis live vs duty-paid now/.test(hs) && /liveBasisPct\(mcxLive, hf\?\.duty_paid_landed\)/.test(hs))
  // wave-1c re-check major: strip.basis_pct is the LIVE figure whenever the server holds a quote (basis_clock 'now'), so the
  // settlement label must read basis_settle_pct, and the live figure appears only while MCX trades (never a cached LTP after the close)
  check('W7 one basis per clock: settlement from basis_settle_pct, live only while trading, never basis_pct under the settlement label',
    /const basisSettle = s\?\.basis_settle_pct \?\? \(s\?\.basis_clock === 'settlement'/.test(hs) && /const basisLive = mcxTrading \? \(s\?\.basis_live_pct/.test(hs)
    && !/fmtSignedPctSp\(s\.basis_pct, 2\)/.test(hs) && /fmtSignedPctSp\(basisSettle, 2\)/.test(hs) && /const mcxTrading = s\?\.mcx_shown === 'live' \|\| !!mcxOpen\?\.is_open/.test(hs))
  // C-TRADER-20 / C-BEGINNER-18 / C-BEGINNER-19 / C-TRADER-23: Western grouping for counts, ordinals, percentiles
  eq('W8 fmtCount / fmtSignedCount: Western grouping, U+2212', [F.fmtCount(105562), F.fmtSignedCount(1356), F.fmtSignedCount(-2883), F.fmtSignedCount(0), F.fmtCount(null)], ['105,562', '+1,356', `${MINUS}2,883`, '0', '—'])
  check('W8 rupees keep the Indian grouping (only rupees)', F.fmtInr0(146079) === '₹1,46,079' && !/1,05,562/.test(F.fmtCount(105562)))
  eq('W8 ordinal: 1st 2nd 3rd 11th 12th 13th 21st 93rd 100th', [1, 2, 3, 11, 12, 13, 21, 93, 100].map(F.ordinal), ['1st', '2nd', '3rd', '11th', '12th', '13th', '21st', '93rd', '100th'])
  eq('W8 percentileText: the word is percentile; < 60 observations says so instead', [F.percentileText(93, '3 y'), F.percentileText(14, null, 14, '2025-09'), F.percentileText(null), F.percentileText(50, '1 y', 60)], ['93rd percentile (3 y)', '14 obs. since 2025-09 — too few for a percentile', '—', '50th percentile (1 y)'])
  check('W8 PERCENTILE_MIN_N is 60 and MONTHLY hides the gold/M2 percentile under it', F.PERCENTILE_MIN_N === 60 && /ratio\.length >= PERCENTILE_MIN_N/.test(src('components/gold/MonthlyView.tsx')))
  check('W8 no view prints "th pct" by hand', B4A_VIEWS.every(f => !/\$\{[^}]*\}th pct/.test(src(f))))
  // C-TRADER-27: the verdict line on screen uses U+2212 even when the server sends an ASCII hyphen; hyphenated month codes keep theirs
  eq('W9 healthLine turns a signed ASCII hyphen into U+2212 and leaves DEC-26→FEB-27 alone', F.healthLine('x · real yield -4 bp · roll DEC-26→FEB-27 (-5.3 %/yr) · GLD -2.9 t on the day'), `x · real yield ${MINUS}4 bp · roll DEC-26→FEB-27 (${MINUS}5.3 %/yr) · GLD ${MINUS}2.9 t on the day · ${F.HEALTH_SUFFIX}`)
  check('W9 HealthView separates the head from the suffix with a space and a middle dot', /\{head\}\s*\{' '\}\s*<span[^>]*>· \{HEALTH_SUFFIX\}/.test(src('components/gold/HealthView.tsx')))
  // C-TRADER-16: the verdict's week label follows the server (verdict → payload → the TREND gauge's window_label)
  const hh = (extra: Partial<GoldHealth>): GoldHealth => ({ as_of: '', window: 'W', line: '', freshness: { state: 'delayed' }, verdict: { line: '', clauses: [] }, gauges: [], fair: {} as GoldHealth['fair'], ...extra })
  eq('W10 verdictWindowLabel precedence', [F.verdictWindowLabel(hh({ verdict: { line: '', clauses: [], window_label: 'Mon 02 Nov → Wed 04 Nov' }, gauges: [{ key: 'trend', label: '', value: 1, unit: '', state: 'delayed', badge: 'context', window_label: 'x' }] })),
    F.verdictWindowLabel(hh({ gauges: [{ key: 'trend', label: '', value: 1, unit: '', state: 'delayed', badge: 'context', window_label: 'week to date (since the Fri 30 Oct close)' }] })), F.verdictWindowLabel(hh({})), F.verdictWindowLabel(null)],
    ['Mon 02 Nov → Wed 04 Nov', 'week to date (since the Fri 30 Oct close)', null, null])
  check('W10 HealthView prints the server wording, never a client-composed "over the week"', /verdictWindowLabel\(h\)/.test(src('components/gold/HealthView.tsx')) && !/over the week/.test(src('components/gold/HealthView.tsx')))
  check('W10 the verdict panel passes maxAgeDays={null} (its age is its oldest input, not COMEX_GC_FRONT\'s cap) and kit honours an explicit null', /id="h\.verdict"[\s\S]{0,1200}maxAgeDays=\{null\}/.test(src('components/gold/HealthView.tsx')) && /maxAgeDays === undefined \? row\?\.max_age_days : maxAgeDays/.test(src('components/gold/kit.tsx')))
  // C-TRADER-14 / C-BEGINNER-13: h.open after the bell; the honest [B] copy
  const rowsLog = [{ date: '2026-11-05', fair_open: 141086, actual_open: 139726, error: -1360, naive_error: -460 }]
  eq('W11 morningCall: pre-open before 09:15; the call after; open missing; no snapshot; closed on a weekend / full closure', [
    F.morningCall(9 * 60 + 14, 4, '2026-11-05', rowsLog).phase, F.morningCall(9 * 60 + 15, 4, '2026-11-05', rowsLog).phase, F.morningCall(23 * 60 + 53, 4, '2026-11-05', [{ date: '2026-11-05', fair_open: 141086 }]).phase,
    F.morningCall(23 * 60 + 53, 4, '2026-11-05', [{ date: '2026-11-04', fair_open: 1, actual_open: 1 }]).phase, F.morningCall(23 * 60 + 53, 4, '2026-11-05', null).phase, F.morningCall(12 * 60, 6, '2026-11-07', rowsLog).phase, F.morningCall(12 * 60, 4, '2026-11-05', rowsLog, 'full').phase],
    ['pre_open', 'call', 'open_missing', 'no_snapshot', 'no_snapshot', 'closed', 'closed'])
  const pre = src('components/gold/GoldPreOpen.tsx')
  check('W11 GoldPreOpen hides the pre-open verdict strip once the call is settled and renders the three after-09:15 states', /call\.phase !== 'call' && call\.phase !== 'no_snapshot' && call\.phase !== 'open_missing'/.test(pre) && /data-gold-call="open-missing"/.test(pre) && /data-gold-call="no-snapshot"/.test(pre) && /NO SNAPSHOT TODAY \(JOB MISSED\)/.test(pre))
  const copyB = F.preOpenCopyB({ days: 15, median_abs_error: 1360, mean_abs_error: 1510, naive_mean_abs_error: 1180 })
  check('W11 the [B] copy is the honest wording: house rule, measured miss, worse than naive, "not advice"; never an action rule', /house rule \(₹300\)/.test(copyB) && /missed by ₹1,360 on a typical morning/.test(copyB) && /worse than/.test(copyB) && /arithmetic to read, not advice/.test(copyB) && !/trade your plan/i.test(copyB) && !/trade your plan/i.test(pre))
  check('W11 the [B] copy with no scored days says the rule is unproven; a model that beats naive says so', /no scored mornings yet/.test(F.preOpenCopyB({ days: 0 })) && /beats/.test(F.preOpenCopyB({ days: 5, median_abs_error: 200, mean_abs_error: 250, naive_mean_abs_error: 900 })))
  // C-BEGINNER-7: <Term> on the first use of the glossary words on HEALTH / DAILY / WEEKLY / MONTHLY / CONTRACTS
  const termsOf = (f: string) => new Set([...src(f).matchAll(/<Term t="([^"]+)"/g)].map(m => m[1]))
  const wantTerms: Record<string, string[]> = {
    'components/gold/HealthView.tsx': ['real yield', 'basis point', 'managed money', 'duty-paid landed', 'roll', 'GLD', 'MCX basis', 'DXY', 'FND / LTD'],
    'components/gold/GoldPreOpen.tsx': ['chase limit', 'fair open'],
    'components/gold/DailyView.tsx': ['open interest', 'OI quadrants', 'settlement by session'],
    'components/gold/WeeklyView.tsx': ['COT', 'managed money', 'IBJA rate', 'GLD'],
    'components/gold/MonthlyView.tsx': ['DXY', 'landed price', 'PBoC', 'SGE withdrawals'],
    'components/gold/ContractsView.tsx': ['roll', 'FND / LTD', 'open interest', 'contango', 'MCX basis', 'first notice day'],
  }
  const gl = JSON.parse(src('lib/gold/glossary.json')) as { terms: { term: string; aliases?: string[] }[] }
  const known = new Set(gl.terms.flatMap(t => [t.term.toLowerCase(), ...(t.aliases ?? []).map(a => a.toLowerCase())]))
  for (const [f, want] of Object.entries(wantTerms)) {
    const have = termsOf(f)
    eq(`W12 ${f} wraps its glossary words in <Term>`, want.filter(t => !have.has(t)), [])
    eq(`W12 ${f}: every <Term t=> names a glossary term or alias`, [...have].filter(t => !known.has(t.toLowerCase()) && t !== 'hit rate'), [])
  }
  // C-TRADER-19 / PLAN §f.6: ONE fair block per page load feeds every sub-view
  const gpSrc = src('components/gold/GoldPage.tsx')
  check('W13 GoldPage hands the overview\'s health.fair to every sub-view as `fair` (and the overview itself)', /const fair = overview\?\.health\?\.fair \?\? null/.test(gpSrc) && /fair, overview, onNavigate/.test(gpSrc))
  check('W13 no sub-view fetches /api/gold/overview on its own (the page does, once)', B4A_VIEWS.filter(f => !/GoldPage|HealthStrip/.test(f)).every(f => !/getGoldOverview\(/.test(src(f))))
  check('W13 CONTRACTS prints the landed / duty-paid rupee from the page\'s fair block, not its own fetch', /fair\?\.duty_paid_landed \?\? mc\.basis\.duty_paid_landed_inr/.test(cv) && /the same rupee as HEALTH and PHYSICAL/.test(cv))
  // C-TRADER-6 / C-DATA-5 / C-TRADER-22: MONTHLY's official sector = net-purchase bars in tonnes (the holders table is PHYSICAL's); no RBI price-implied estimate
  const mv = src('components/gold/MonthlyView.tsx')
  check('W14 m.official renders NetPurchases once; no holders DataTable and no RBI price-implied tonnes on MONTHLY', /<NetPurchases bars=\{purchases\} \/>/.test(mv) && !/officialCols/.test(mv) && !/rbi\.tonnes_est|rbi &&|RBI_GOLD_RESERVES_USD_MN/.test(mv))
  check('W14 the ₹ / basket ladder note renders once with its reason (C-BEGINNER-15)', /data-gold-ladder-note/.test(mv) && /fill as the USD\/INR/.test(mv))
  // C-DATA-6 / C-DATA-20: COT release printed from the server's IST label (WEEKLY)
  check('W15 WeeklyView prints release_ist and never istLabel(release_at)', /c\.latest\.release_ist \?\?/.test(src('components/gold/WeeklyView.tsx')) && !/istLabel\(c\.latest\.release_at/.test(src('components/gold/WeeklyView.tsx')))
  // C-TRADER-26: the SGE panel never shows "no verdict" in the release build — a link tile instead
  check('W16 d.sge: no NoVerdict; the SGE link tile instead', !/id="d\.sge"[\s\S]{0,1500}<NoVerdict/.test(dv) && /LinkTile name="SGE delayed quotes"/.test(dv))
}

console.log(`gold.check: ${passed} passed, ${failed} failed`)
if (failed) process.exit(1)

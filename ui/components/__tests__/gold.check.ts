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
  // round 2 (CT-01): the list grew from ['SGE_DAILY'] to every catalog id the panel RENDERS — the 1-minute bars it draws
  // and the USDCNY leg it converts at — so the §f.2 gate covers all three. Still exact, still only real seeded ids.
  check('F5 DAILY gates the SGE panel on the catalog ids it renders (SGE_DAILY + BARS_1M + the FX leg; no invented one)',
    /series=\{\['SGE_DAILY', 'BARS_1M', 'FX_CNY'\]\}/.test(src('components/gold/DailyView.tsx')) && !/SGE_AU9999 \?\?/.test(src('components/gold/DailyView.tsx')))
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
  check('W2 DailyView draws the server settle_line only when it is a settlement (never a last trade) and labels the fallback as a Yahoo daily close', /last\.\?trade/.test(dv) && /close \(Yahoo daily, not settlement\)/.test(dv) && /kitcoLegend\(/.test(dv) && /legendCloses\(/.test(src('lib/gold/kitco.ts')))
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
  check('W5 HealthView never renders open_signal and reads the top-level fields through briefHeader', !/open_signal/.test(src('components/gold/HealthView.tsx').replace(/\/\*[\s\S]*?\*\//g, '').replace(/copyP="[^"]*"/g, '')) && /briefHeader\(b(, [^)]*)?\)/.test(src('components/gold/HealthView.tsx')))
  // C-BEGINNER-4 / C-TRADER-13 / C-DATA-8: the DES card by the matched month, tick in display units, settlement and uom in words
  eq('W6 comexMmy / mmyLabel / specMatches', [F.comexMmy('GCZ26.CMX'), F.comexMmy('GC=F'), F.mmyLabel('202611'), F.specMatches({ mmy: '202611' }, 'GCZ26.CMX'), F.specMatches({ mmy: '202612' }, 'GCZ26.CMX'), F.specMatches({ mmy: null }, 'GCZ26.CMX')], ['202612', null, 'NOV-26', false, true, null])
  eq('W6 specTick: the PRF MinPxIncr 1.0 × DisplayFactor 0.1 = $0.10 = $10; a server tick_usd wins; GC convention without a factor', [F.specTick({ symbol: 'GC', min_px_incr: 1, display_factor: 0.1, multiplier: 100 }), F.specTick({ symbol: 'GC', min_px_incr: 1, tick_usd: 0.1, multiplier: 100 }), F.specTick({ symbol: 'GC', min_px_incr: 1, multiplier: 100 }), F.specTick({ symbol: 'SI', min_px_incr: 0.005, multiplier: 5000 }), F.specTick(null)],
    [{ tick: 0.1, value: 10 }, { tick: 0.1, value: 10 }, { tick: 0.1, value: 10 }, { tick: 0.005, value: 25 }, null])
  eq('W6 settlement / uom words', [F.settlMethodWord('P'), F.settlMethodWord('physical delivery'), F.settlMethodWord('C'), F.settlMethodWord(null), F.uomWord('oz_tr'), F.uomWord('kg'), F.uomWord(null)], ['physical delivery', 'physical delivery', 'cash-settled', '—', 'troy oz', 'kilograms', 'oz'])
  eq('W6 margin history: the $25 row of another product is dropped, one point per date, ≥ 3 dates', [F.marginHistoryPoints([{ trade_date: '2026-11-04', margin_usd: 25 }, { trade_date: '2026-11-04', margin_usd: 19785 }, { trade_date: '2026-11-03', margin_usd: 19700 }, { trade_date: '2026-11-02', margin_usd: 19600 }]), F.marginHistoryPoints([{ trade_date: '2026-11-04', margin_usd: 19785 }])], [[19600, 19700, 19785], []])
  const cv = src('components/gold/ContractsView.tsx')
  check('W6 ContractsView: the card names the PRF month, flags a mismatch, prints the tick through specTick and the words', /specMatches\(spec, comexMatched\)/.test(cv) && /data-gold-spec-mismatch/.test(cv) && /specTick\(spec\)/.test(cv) && /settlMethodWord\(/.test(cv) && /uomWord\(spec\.uom\)/.test(cv) && /marginHistoryPoints\(spec\.margin_history\)/.test(cv))
  // wave 1d: the server's carry is 'annualised vs the front expiry (as /curve)' (C-DATA-16), so the ladder heads it 'carry vs front' (the old
  // 'to next month' head contradicted the served convention), and on GOLD › CONTRACTS the chain prints it once (chainOnPage)
  check('W6 the term structure marks the matched month\'s FND and the ladder heads its carry "vs front", the served convention (C-TRADER-24 / C-DATA-16 / wave 1d)',
    /data-gold-fnd-tick/.test(cv) && /carry vs front % p\.a\./.test(cv) && !/carry to next month/.test(cv) && /carry_convention/.test(cv) && /days to last trade/.test(cv))
  // C-BEGINNER-5 / C-DATA-11 / C-TRADER-10: basis clock labels
  eq('W7 basisClockLabel / liveBasisPct', [F.basisClockLabel(1.5, 'Tue 03 Nov settlement'), F.basisClockLabel(null, 'x'), F.basisClockLabel(0.41, null), F.liveBasisPct(143249, 142663), F.liveBasisPct(1, 0), F.liveBasisPct(null, 1)],
    ['basis +1.50 % at the Tue 03 Nov settlement vs that session\'s duty-paid', 'basis —', 'basis +0.41 % at the last settlement vs that session\'s duty-paid', (143249 / 142663 - 1) * 100, null, null])
  const hs = src('components/gold/HealthStrip.tsx').replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
  check('W7 the strip: no "NO DATA" beside a live price; no last trade says the backfill is coming; the last trade is labelled Yahoo, not settlement; the settlement basis names its session through basisSettleLabel (printed once, REREVIEW)',
    !/NO DATA/.test(hs) && /arrives with the CME backfill/.test(hs) && /not settlement/.test(hs) && /basisSettleLabel\(s\?\.basis_session_label/.test(hs) && !/at the \{basisSession\} vs that session/.test(hs) && /COT funds net \(managed money\)/.test(hs))
  // wave 1d: the client never recomputes a basis (the purity of the landed price is the server's basis_reference; a client ratio of
  // a 995 contract over a 999 duty-paid price is the cross-purity error the 5 Nov review found)
  check('W7 the strip shows the live MCX above the settlement while the session runs and the SERVER\'s live-vs-now basis, never a client ratio (C-TRADER-10 / wave 1d; wave 1e: through stripBasis)',
    /mcxLive != null && mcxTrading/.test(hs) && /basis live vs duty-paid now/.test(hs) && !/liveBasisPct\(/.test(hs) && /stripBasis\(s, mcxOpen\?\.is_open\)/.test(hs))
  // wave-1c re-check major: strip.basis_pct is the LIVE figure whenever the server holds a quote (basis_clock 'now'), so the
  // settlement label must read basis_settle_pct, and the live figure appears only while MCX trades (never a cached LTP after the close)
  check('W7 one basis per clock: settlement from basis_settle_pct, live only while trading, never basis_pct under the settlement label',
    !/fmtSignedPctSp\(s\.basis_pct, 2\)/.test(hs) && /fmtSignedPctSp\(basisSettle, 2\)/.test(hs) && /fmtSignedPctSp\(basisLive, 2\)/.test(hs))
  eq('W7 stripBasis: live = basis_live_pct while trading; settle = basis_settle_pct; basis_pct at clock now never under the settlement label; no live figure after the close', [
    F.stripBasis({ basis_pct: 0.89, basis_clock: 'now', basis_live_pct: 0.89, basis_settle_pct: 0.69, mcx_shown: 'live' }, true),
    F.stripBasis({ basis_pct: 0.89, basis_clock: 'now', basis_live_pct: null, basis_settle_pct: null, mcx_shown: 'settlement' }, false),
    F.stripBasis({ basis_pct: 0.69, basis_clock: 'settlement', basis_live_pct: null, basis_settle_pct: null, mcx_shown: 'settlement' }, false)],
    [{ live: 0.89, settle: 0.69, trading: true }, { live: null, settle: null, trading: false }, { live: null, settle: 0.69, trading: false }])
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
  check('W13 GoldPage hands the overview\'s health.fair to every sub-view as `fair` (and the overview itself, with its load state)', /const fair = overview\?\.health\?\.fair \?\? null/.test(gpSrc) && /fair, overview, overviewStatus, onNavigate/.test(gpSrc))
  check('W13 no sub-view fetches /api/gold/overview on its own (the page does, once)', B4A_VIEWS.filter(f => !/GoldPage|HealthStrip/.test(f)).every(f => !/getGoldOverview\(/.test(src(f))))
  check('W13 CONTRACTS prints the landed / duty-paid rupee from the page\'s fair block, not its own fetch', /pageFair\?\.duty_paid_landed \?\? mc\.basis\.duty_paid_landed_inr/.test(cv) && /const pageFair = \(fair\?\.contract \?\? sel\.family\) === sel\.family \? fair : null/.test(cv) && /the same rupee as HEALTH and PHYSICAL/.test(cv))
  // C-TRADER-6 / C-DATA-5 / C-TRADER-22: MONTHLY's official sector = net-purchase bars in tonnes (the holders table is PHYSICAL's); no RBI price-implied estimate
  const mv = src('components/gold/MonthlyView.tsx')
  check('W14 m.official renders NetPurchases once; no holders DataTable and no RBI price-implied tonnes on MONTHLY', /<NetPurchases bars=\{purchases\} \/>/.test(mv) && !/officialCols/.test(mv) && !/rbi\.tonnes_est|rbi &&|RBI_GOLD_RESERVES_USD_MN/.test(mv))
  check('W14 the ₹ / basket ladder note renders once with its reason (C-BEGINNER-15)', /data-gold-ladder-note/.test(mv) && /fill as the USD\/INR/.test(mv))
  // C-DATA-6 / C-DATA-20: COT release printed from the server's IST label (WEEKLY)
  check('W15 WeeklyView prints release_ist and never istLabel(release_at)', /c\.latest\.release_ist \?\?/.test(src('components/gold/WeeklyView.tsx')) && !/istLabel\(c\.latest\.release_at/.test(src('components/gold/WeeklyView.tsx')))
  // C-TRADER-26: the SGE panel never shows "no verdict" in the release build — a link tile instead
  check('W16 d.sge: no NoVerdict; the SGE link tile instead', !/id="d\.sge"[\s\S]{0,1500}<NoVerdict/.test(dv) && /LinkTile name="SGE delayed quotes"/.test(dv))
}

// ── X. wave 1d (5 Nov 2026 review): the settlement names its source, TREND its values, the basis its purity; the Kitco chart ──
{
  type KitcoMod = typeof import('../../lib/gold/kitco')
  const K = (await import(new URL('../../lib/gold/kitco.ts', import.meta.url).href)) as KitcoMod
  // X1 settlement line: source + session + proxy; a server with no source is the band midpoint (never a better source invented)
  eq('X1 settlementLine names session and source (VWAP · band · pre-1d server with a value · nothing at all)', [
    F.settlementLine({ settlement_source: 'breeze_vwap30', settlement_session: '2026-11-04' }),
    F.settlementLine({ settlement_source: 'band_midpoint', settlement_session: '2026-11-03' }),
    F.settlementLine({ settlement: 139452, settlement_session_label: 'Wed 04 Nov settlement' }),
    F.settlementLine({ settlement: null, settlement_source: null, settlement_session: '2026-11-04' }),
    F.settlementLine(null),
  ], ['Wed 04 Nov · last-30-min VWAP (Breeze) — proxy', 'Tue 03 Nov · price-band midpoint (ICICI master) — proxy',
      'Wed 04 Nov · price-band midpoint (ICICI master; source not stated) — proxy', 'no settlement', 'no settlement'])
  // R2 (checker): a null source never reads as a confident band on nothing; with a value it is the band AND the muted caution
  check('X1 R2 negative control: no settlement → no band words, no note', !/band/.test(F.settlementLine({ settlement: null })) && F.settlementNote({ settlement: null, settlement_source: null }) === null)
  check('X1 R2 pre-1d server (a value, no source) → the muted caution (its session label can be one session late)', F.settlementNote({ settlement: 139452, settlement_session: '2026-11-04' })?.tone === 'muted'
    && /did not name/.test(F.settlementNote({ settlement: 139452 })?.text ?? '') && !F.settlementCheck({ settlement: 139452, band_midpoint: 139452 }).available)
  // X2 the band-vs-VWAP check: > 0.6 % flags; ≤ 0.6 % does not (negative control); a band settlement has nothing to test
  const vw = { settlement: 143237, settlement_source: 'breeze_vwap30', band_midpoint: 139452, band_session: '2026-11-03' }
  const c1 = F.settlementCheck(vw)
  check('X2 recomputed check flags the 5 Nov case (band ₹1,39,452 vs VWAP ₹1,43,237 = −2.64 %)', c1.flagged && c1.available && c1.pct != null && Math.abs(c1.pct - (139452 / 143237 - 1) * 100) < 1e-9, c1)
  check('X2 negative control: 0.5 % apart is not flagged', !F.settlementCheck({ ...vw, band_midpoint: 143237 * 1.005 }).flagged)
  check('X2 negative control: exactly 0.6 % is not flagged (strictly more than)', !F.settlementCheck({ ...vw, band_midpoint: 143237 * 1.006 - 1e-6 }).flagged)
  check('X2 the server\'s settlement_check wins (flagged true even with a small pct)', F.settlementCheck({ ...vw, settlement_check: { band_vs_vwap30_pct: 0.1, flagged: true } }).flagged)
  check('X2 the server\'s unflagged check stays unflagged', !F.settlementCheck({ ...vw, settlement_check: { band_vs_vwap30_pct: 0.2, flagged: false } }).flagged)
  eq('X2 a band settlement has no VWAP to test (not available, not flagged)', F.settlementCheck({ settlement: 139452, settlement_source: 'band_midpoint', band_midpoint: 139452 }), { pct: null, flagged: false, available: false })
  // X3 notes: amber when flagged; a muted caution on the band fallback; nothing when they agree
  check('X3 settlementNote is amber and names the band session when flagged', F.settlementNote(vw)?.tone === 'amber' && /Tue 03 Nov/.test(F.settlementNote(vw)?.text ?? '') && /0\.6 %/.test(F.settlementNote(vw)?.text ?? ''))
  // R2 (§f.6): the cell prints the settlement; the note prints the band's value and the %, never the settlement's value again
  check('X3 R2 the flagged note carries the band value, not the settlement value (negative control: ₹1,43,237 absent)', /1,39,452/.test(F.settlementNote(vw)?.text ?? '') && !/1,43,237/.test(F.settlementNote(vw)?.text ?? ''))
  check('X3 band fallback → a muted caution', F.settlementNote({ settlement: 1, settlement_source: 'band_midpoint' })?.tone === 'muted')
  check('X3 negative control: VWAP and band within 0.6 % → no note', F.settlementNote({ ...vw, band_midpoint: 143300 }) === null)
  check('X3 settlementNoteShort repeats the fact, never the numbers (the strip prints them once per view, §f.6)', F.settlementNoteShort(vw)?.tone === 'amber' && !/\d/.test(F.settlementNoteShort(vw)?.text.replace('30', '') ?? '1') && F.settlementNoteShort({ ...vw, band_midpoint: 143300 }) === null)
  check('X3 c.mcx uses the chain note (its settle column is the band of the chain session; the strip carries the numbers)', /chainSettleNote\(chain, chainSettle\)/.test(src('components/gold/ContractsView.tsx')))
  check('X3 bandReferenceLine: the band with its real session; null when the band IS the settlement (printed once)',
    F.bandReferenceLine(vw) === 'ICICI band midpoint ₹1,39,452 · belongs to the Tue 03 Nov session (reference)' && F.bandReferenceLine({ settlement_source: 'band_midpoint', band_midpoint: 1 }) === null)
  check('X3 R2 bandReferenceLine without its value (the strip\'s flagged note prints it): the session, no rupee figure', /Tue 03 Nov/.test(F.bandReferenceLine(vw, false) ?? '') && !/₹|1,39,452/.test(F.bandReferenceLine(vw, false) ?? '₹'))
  check('X3 R2 h.open drops the band value exactly when its amber check note shows', /bandReferenceLine\(bl, blNote\?\.tone !== 'amber'\)/.test(src('components/gold/GoldPreOpen.tsx')))
  // F6 (8 Nov 2026): h.open sent the pick's family but printed GOLD 1 kg's numbers under the pick's header — a GOLDPETAL
  // reader met a ₹1,42,540 'settlement' beside their own ₹14,339, ten times out, with nothing saying which was which.
  {
    const pre8 = src('components/gold/GoldPreOpen.tsx')
    check('X3 F6 h.open prints ONE line for the pick, in the pick\'s own unit, from the server\'s contract_fair',
      /data-gold-open-pick/.test(pre8) && /cf\.fair_value/.test(pre8) && /cf\.quote_unit/.test(pre8)
      && /cf\.chase_limit/.test(pre8) && /\{cf\.model_note\}/.test(pre8))
    check('X3 F6 the pick line appears ONLY for a non-GOLD family (the scored history is GOLD, and it is not re-pointed)',
      /sel\?\.family && sel\.family !== 'GOLD' \? \(data\?\.contract_fair \?\? null\) : null/.test(pre8))
    check('X3 F6 the subtitle says whose model the other numbers are',
      /model on GOLD 1 kg, not your \$\{cf\.contract\}/.test(pre8))
    check('X3 F6 negative control: the panel never prices the pick from the GOLD baseline',
      !/contract_fair[^\n]*baseline/.test(pre8) && !/cf\.fair_value[^\n]*data\.baseline/.test(pre8))
  }
  eq('X3 quality chip', [F.settlementQualityChip('vwap30_proxy'), F.settlementQualityChip('band_proxy'), F.settlementQualityChip('proxy'), F.settlementQualityChip(null, 'breeze_vwap30')], ['VWAP30 PROXY', 'BAND PROXY', 'BAND PROXY', 'VWAP30 PROXY'])
  // X4 TREND: values and the words they earn; the server's words win
  eq('X4 trendWordsFrom: below both / above both / between / missing', [F.trendWordsFrom(-0.47, -9.72), F.trendWordsFrom(1, 2), F.trendWordsFrom(0.5, -3), F.trendWordsFrom(null, 1)], ['below both averages', 'above both', 'between', null])
  eq('X4 trendValuesLine prints the three values (drawdown_52w_pct or drawdown_pct)', [F.trendValuesLine({ vs_20d_pct: -0.47, vs_200d_pct: -9.72, drawdown_52w_pct: -23.46 }), F.trendValuesLine({ drawdown_pct: -5 })],
    [`vs 20 d ${MINUS}0.47 % · vs 200 d ${MINUS}9.72 % · drawdown ${MINUS}23.46 % from the 52-week high`, `drawdown ${MINUS}5.00 % from the 52-week high`])
  check('X4 the server\'s trend_words win over the computed ones', F.trendWords({ vs_20d_pct: 1, vs_200d_pct: 1, trend_words: 'between' }) === 'between' && F.trendWords({ vs_20d_pct: -1, vs_200d_pct: -1 }) === 'below both averages')
  const hv = src('components/gold/HealthView.tsx')
  check('X4 the TREND tile renders trendValuesLine + trendWords and never its rule as the headline word', /trendValuesLine\(g\)/.test(hv) && /trendWords\(g\)/.test(hv) && /dir && !trendTile/.test(hv) && /data-gold-trend-values/.test(hv))
  // X5 purity: the basis names its landed reference; a cross-purity reference is flagged
  eq('X5 basisReferenceFor / basisReferenceLabel / basisPurityShort (D1: GUINEA is 999)', [F.basisReferenceFor('GOLD'), F.basisReferenceFor('goldm'), F.basisReferenceFor('GOLDTEN'), F.basisReferenceFor('GOLDPETAL'), F.basisReferenceFor('GOLDGUINEA'), F.basisReferenceFor('X'),
    F.basisReferenceLabel('landed_995'), F.basisReferenceLabel(null), F.basisPurityShort('landed_999'), F.basisPurityShort(undefined)],
    ['landed_995', 'landed_995', 'landed_999', 'landed_999', 'landed_999', null, 'vs the 995 duty-paid landed', 'purity of the landed reference not stated', 'landed at 999 fine', 'landed purity not stated'])
  check('X5 D1: GOLDGUINEA against 999 is its own purity; against 995 (or a 916 a server might still send) it is flagged', !F.basisPurityMismatch('landed_999', 'GOLDGUINEA') && F.basisPurityMismatch('landed_995', 'GOLDGUINEA') && F.basisPurityMismatch('landed_916', 'GOLDGUINEA'))
  eq('X5 D1: FAMILY_PURITY is the PM\'s table (GOLD/GOLDM 995; TEN/PETAL/GUINEA 999)', F.FAMILY_PURITY, { GOLD: 995, GOLDM: 995, GOLDTEN: 999, GOLDPETAL: 999, GOLDGUINEA: 999 })
  check('X5 D1: no UI copy calls GUINEA 916', !/GUINEA 916/.test(src('components/gold/HealthView.tsx')) && !/GOLDGUINEA: 916/.test(src('lib/gold/format.ts')))
  check('X5 basisPurityMismatch: GOLD read against 999 is flagged; GOLD against 995 is not; no reference is not', F.basisPurityMismatch('landed_999', 'GOLD') && !F.basisPurityMismatch('landed_995', 'GOLD') && !F.basisPurityMismatch(null, 'GOLD'))
  check('X5 the India-basis tile wears a LIVE chip on the live clock and a dated SETTLEMENT chip (with its source quality) only on the settlement clock (wave 1e: basisClockChip names the clock)',
    /basisClockChip\(g, overview, settleBlock\)/.test(hv) && /data-gold-basis-chip=\{chip\.kind\}/.test(hv) && !/SETTLEMENT · PROXY · \{dayLabel\(g\.report_date\)\}/.test(hv) && /basisTileWords\([^;]*g\.basis_reference\)/.test(hv))
  // X6 the strip: one settlement block, the label printed once, the COMEX price once
  const st = F.stripSettlement({ mcx_settle: 139452, mcx_settle_session: '2026-11-04', mcx_settle_session_label: 'Wed 04 Nov settlement', mcx_settle_quality: 'proxy' } as never,
    { settlement_source: 'breeze_vwap30', band_midpoint: 139452, band_session: '2026-11-03' } as never)
  // R2 negative control (the checker's repro): a legacy BAND value never borrows the fair block's VWAP source — that mix is the blocker's mislabel
  eq('X6 R2 stripSettlement: a legacy band value keeps its own (unstated) source; another value\'s VWAP label is not borrowed', [st.settlement, st.settlement_session, st.settlement_source, st.band_session], [139452, '2026-11-04', null, null])
  check('X6 R2 …and it then reads as the band with the muted caution, never "last-30-min VWAP"', !/VWAP/.test(F.settlementLine(st)) && F.settlementNote(st)?.tone === 'muted' && !F.settlementCheck(st).flagged)
  const stSame = F.stripSettlement({ mcx_settle: 143237, mcx_settle_session: '2026-11-04' } as never, { settlement: 143237, settlement_source: 'breeze_vwap30', band_midpoint: 139452, band_session: '2026-11-03', settlement_check: { band_vs_vwap30_pct: -2.64, flagged: true } } as never)
  eq('X6 R2 stripSettlement: the fair block fills source / band / check only when its settlement IS the value', [stSame.settlement_source, stSame.band_session, F.settlementCheck(stSame).flagged], ['breeze_vwap30', '2026-11-03', true])
  check('X6 R2 stripSettlement: a strip with no value takes the WHOLE block from the fair block (value and label together)', F.stripSettlement({} as never, { settlement: 143237, settlement_source: 'breeze_vwap30', settlement_session: '2026-11-04' } as never).settlement_source === 'breeze_vwap30'
    && F.stripSettlement({ mcx_settle: 1, mcx_settle_source: 'band_midpoint' } as never, null).settlement_source === 'band_midpoint')
  check('X6 stripSettlement: the contract\'s own names win over the legacy ones', F.stripSettlement({ settlement: 143237, mcx_settle: 139452, settlement_session: '2026-11-04' } as never).settlement === 143237)
  const sentence = 'at the Wed 04 Nov settlement vs that session\'s duty-paid landed'
  check('X6 basisSettleLabel prints the server sentence verbatim ("at the" exactly once)', F.basisSettleLabel(sentence) === sentence && (F.basisSettleLabel(sentence).match(/at the/g) ?? []).length === 1)
  check('X6 basisSettleLabel wraps a bare session label once; falls back to the ISO session', F.basisSettleLabel('Tue 03 Nov settlement') === 'at the Tue 03 Nov settlement vs that session\'s duty-paid landed' && F.basisSettleLabel(null, '2026-11-03') === sentence.replace('Wed 04', 'Tue 03'))
  check('X6 sameComexPrint: the same quantity prints once; a real difference prints both (negative control)', F.sameComexPrint(4072.2, 4072.2) && F.sameComexPrint(4072.2, 4072.24) && !F.sameComexPrint(4072.2, 4105) && !F.sameComexPrint(null, 4072.2))
  const hs2 = src('components/gold/HealthStrip.tsx')
  check('X6 the strip renders settlementLine + settlementNote, never a leading "settle —", and prints the daily bar only when it differs', /settlementLine\(st\)/.test(hs2) && /settlementNote\(st\)/.test(hs2) && !/>settle — </.test(hs2) && /!comexOnce/.test(hs2) && /data-gold-settle-note/.test(hs2))
  // X7 the pre-open desk: the baseline names its source; the band names its session; a typed override is the user's
  const fairStub = { baseline: { value: 143237, source: 's', session: '2026-11-04', close_time: '', settlement_from_band: 139452, session_label: 'Wed 04 Nov settlement' } } as never
  const bs = F.baselineSettlement(fairStub, { contract: 'GOLD', settlement: 143237, settlement_source: 'breeze_vwap30', band_midpoint: 139452, band_session: '2026-11-03' } as never, 'GOLD')
  eq('X7 baselineSettlement: /fair.baseline value + session, the same family\'s fair (same settlement value) fills source / band', [bs?.settlement, bs?.settlement_session, bs?.settlement_source, bs?.band_session], [143237, '2026-11-04', 'breeze_vwap30', '2026-11-03'])
  check('X7 negative control: another family\'s fair block never fills the baseline\'s source', F.baselineSettlement(fairStub, { contract: 'GOLDM', settlement_source: 'breeze_vwap30' } as never, 'GOLD')?.settlement_source == null)
  // R2 (checker): a broker previous close is labelled as what it is, even when the block also carries the settle block's source
  const brokerStub = { baseline: { value: 140190, source: 'ICICI Breeze previous close', session: '2026-11-04', session_label: 'Wed 04 Nov settlement', settlement_source: 'breeze_vwap30', settlement_quality: 'vwap30_proxy',
    band_midpoint: 139452, band_session: '2026-11-03', settlement_check: { band_vs_vwap30_pct: -2.64, flagged: true } } } as never
  const bk = F.baselineSettlement(brokerStub, { contract: 'GOLD', settlement: 143237, settlement_source: 'breeze_vwap30' } as never, 'GOLD')
  check('X7 R2 broker previous close → its own label (never "last-30-min VWAP"), its own chip, no band check', bk?.settlement_source === 'breeze_previous_close' && /previous close/.test(F.settlementLine(bk)) && !/VWAP/.test(F.settlementLine(bk))
    && F.settlementQualityChip(bk?.settlement_quality, bk?.settlement_source) === 'BROKER CLOSE' && !F.settlementCheck(bk).flagged && F.settlementNote(bk)?.tone === 'muted', bk)
  const nullSrc = F.baselineSettlement({ baseline: { value: 140190, source: 'x', session: '2026-11-04', settlement_source: null } } as never, { contract: 'GOLD', settlement: 143237, settlement_source: 'breeze_vwap30' } as never, 'GOLD')
  check('X7 R2 a null source on a value that is NOT the fair block\'s settlement is not filled with the VWAP label (negative control)', nullSrc?.settlement_source == null && !/VWAP/.test(F.settlementLine(nullSrc)))
  check('X7 R2 baselineSourceKind', F.baselineSourceKind('your entry') === 'user_entry' && F.baselineSourceKind('ICICI Breeze previous close') === 'breeze_previous_close' && F.baselineSourceKind('MCX Wed 04 Nov settlement · last-30-min VWAP') === null)
  const po = src('components/gold/GoldPreOpen.tsx')
  check('X7 h.open prints settlementLine for the baseline, the amber check note and the band\'s session (no "Today\'s MCX band")', /settlementLine\(bl\)/.test(po) && /settlementNoteShort\(bl\)/.test(po) && /set around the \{bandDay\} settlement/.test(po) && !/Today&apos;s MCX band/.test(po) && /your typed close \(override\)/.test(po))
  // X8 CONTRACTS / MCXG: margin dates, 1 % move, ticket margin, ladder vs chain
  eq('X8 marginHistoryDates counts the one stored row (REREVIEW "0 dates"); sub-$1,000 rows are not margins', [F.marginHistoryDates([{ trade_date: '2026-11-05', margin_usd: 19702 }]), F.marginHistoryDates([{ trade_date: 'a', margin_usd: 25 }]), F.marginHistoryDates(null)], [1, 0, 0])
  eq('X8 onePctMove at the live price, else the server\'s settlement figure', [F.onePctMove({ one_pct_move_inr: 139452, multiplier: 100 }, 144014), F.onePctMove({ one_pct_move_inr: 139452, multiplier: 100 }, null)],
    [{ value: 144014, at: 'live' }, { value: 139452, at: 'settlement' }])
  const tk = { notional: 144405, indicative_margin: 8664, margin_pct_indicative: 6 }
  eq('X8 ticketMargin: the card\'s dated NRML % of this notional, not the 6 % constant (5 Nov: ₹8,664 vs the card\'s 9.25 %)', [F.ticketMargin(tk, { margin_pct: 9.25, margin_source: 'zerodha_nrml', margin_date: '2026-11-05' }).value, F.ticketMargin(tk, { margin_pct: 9.25 }).kind], [Math.round(144405 * 0.0925), 'card_mirror'])
  check('X8 ticketMargin: a server mirror wins; no mirror at all → the constant, labelled as such', F.ticketMargin({ ...tk, margin_source: 'zerodha_nrml' }, { margin_pct: 9.25 }).kind === 'server_mirror' && F.ticketMargin(tk, null).kind === 'constant' && /indicative constant/.test(F.ticketMargin(tk, null).label))
  const cvx = src('components/gold/ContractsView.tsx')
  check('X8 R2 the 1 % move prints its number once: "at the live price", never "at live ₹…" (the same number twice)', /'at the live price'/.test(cvx) && !/at live \$\{fmtInr0\(livePrice\)\}/.test(cvx))
  check('X8 GOLD › CONTRACTS: the ladder omits settle / band / carry (the chain prints them once) and the chain drops OI / ΔOI (the ladder prints them once)', /chainOnPage livePrice=\{livePrice\}/.test(cvx) && /\.\.\.\(chainOnPage \? \[\] : \[/.test(cvx) && !/key: 'doi'/.test(cvx) && /marginHistoryDates\(spec\.margin_history\)/.test(cvx))
  check('X8 MCXG\'s ticket margin comes from ticketMargin with the picked expiry\'s card', /ticketMargin\(ticket, pickedExpiry\)/.test(src('components/McxGoldDesk.tsx')) && /livePrice=\{liveLtp\}/.test(src('components/McxGoldDesk.tsx')))
  check('X8 an empty brief shows no bias word; a brief with a body keeps its header', !/bias/.test(F.briefHeader({ bias: 'bullish', confidence: 0.5 } as never, false)) && /bias bullish/.test(F.briefHeader({ bias: 'bullish', confidence: 0.5 } as never)))
  check('X8 WEEKLY: COMEX OI Δ is the GC product (the POSITIONING / DAILY definition); a repeated volume is not printed as data', /oiChangeByDate\(comex\.data\?\.rows, 'GC'\)/.test(src('components/gold/WeeklyView.tsx')) && /— \(repeat\)/.test(src('components/gold/WeeklyView.tsx')) && !/dupVolume\(r\) \? ' \?'/.test(src('components/gold/WeeklyView.tsx')))
  // X9 the Kitco-style chart (pure arithmetic)
  eq('X9 Kitco\'s nine timeframes, in its order', K.KITCO_TIMEFRAMES.map(t => t.label), ['24 h', '3 days', '30 days', '60 days', '6 months', '1 year', '5 years', '10 years', 'all'])
  eq('X9 Kitco\'s units', K.KITCO_UNITS.map(u => K.KITCO_UNIT_LABEL[u]), ['USD/oz', '₹/10 g', '₹/g', 'USD/g', 'USD/kg'])
  near('X9 USD/kg = $/oz × 1000 ÷ 31.1034768', K.kitcoConvert(4000, 'usd_kg', null), 4000 * 1000 / 31.1034768)
  near('X9 USD/g', K.kitcoConvert(4000, 'usd_g', null), 4000 / 31.1034768)
  near('X9 ₹/10 g landed = $/oz × USD/INR × 10 ÷ 31.1034768', K.kitcoConvert(4000, 'inr_10g', 94.5), 4000 * 94.5 * 10 / 31.1034768)
  near('X9 ₹/g duty-paid × 1.15', K.kitcoConvert(4000, 'inr_g', 94.5, 1.15), 4000 * 94.5 / 31.1034768 * 1.15)
  check('X9 negative control: a rupee unit with no rate (or no dated duty) is not drawn; a dollar unit needs neither', K.kitcoConvert(4000, 'inr_10g', null) === null && K.kitcoConvert(4000, 'inr_10g', 94, null) === null && K.kitcoConvert(4000, 'usd_oz', null, null) === 4000)
  eq('X9 dutyMultiplier: the dated duty only from its effective day', [K.dutyMultiplier('2026-05-13', { pct: 15, effective: '2026-05-13' }), K.dutyMultiplier('2026-05-12', { pct: 15, effective: '2026-05-13' }), K.dutyMultiplier('2026-06-01', null)], [1.15, null, null])
  const fxs = [{ ms: 100, v: 80 }, { ms: 200, v: 81 }, { ms: 300, v: 82 }]
  eq('X9 fxAsOf: the latest rate at or before the instant; none before the first', [K.fxAsOf(fxs, 50), K.fxAsOf(fxs, 100), K.fxAsOf(fxs, 250), K.fxAsOf(fxs, 999), K.fxAsOf([], 1)], [null, 80, 81, 82, null])
  const dfx = K.dailyFxPoints([{ ts: '2026-11-03', c: 94.7 }, { ts: '2026-11-04', c: 94.6 }, { ts: '2026-11-02', c: null }])
  check('X9 dailyFxPoints: a daily close is known from the END of its day (no same-day look-ahead into intraday points)', dfx.length === 2 && dfx[0].ms === Date.parse('2026-11-04T00:00:00Z') - 1 && K.fxAsOf(dfx, Date.parse('2026-11-04T10:00:00Z')) === 94.7)
  eq('X9 mergeFx: the 1-minute span replaces the daily points inside it', K.mergeFx([{ ms: 10, v: 1 }, { ms: 50, v: 2 }, { ms: 90, v: 3 }], [{ ms: 40, v: 9 }, { ms: 60, v: 9.5 }]).map(p => p.v), [1, 9, 9.5, 3])
  const ser = K.kitcoSeries([{ ms: 50, usd: 4000 }, { ms: 150, usd: 4010 }, { ms: 250, usd: 4020 }], { unit: 'inr_10g', duty: 'ex_duty', fx: [{ ms: 100, v: 90 }], dutyRate: null, startMs: null })
  check('X9 kitcoSeries: a point before the first stored rupee rate is dropped (counted), never converted at today\'s rate', ser.pts.length === 2 && ser.dropped === 1 && Math.abs(ser.pts[0].v - 4010 * 90 * 10 / 31.1034768) < 1e-6)
  const ser2 = K.kitcoSeries([{ ms: Date.parse('2026-05-01T00:00:00Z'), usd: 4000 }, { ms: Date.parse('2026-06-01T00:00:00Z'), usd: 4000 }], { unit: 'inr_10g', duty: 'duty_paid', fx: [{ ms: 0, v: 90 }], dutyRate: { pct: 15, effective: '2026-05-13' }, startMs: null })
  check('X9 kitcoSeries duty-paid: only from the duty\'s effective date (the store keeps no duty history)', ser2.pts.length === 1 && ser2.dropped === 1)
  const ser3 = K.kitcoSeries([{ ms: 50, usd: 1 }, { ms: 150, usd: 2 }], { unit: 'usd_oz', duty: 'ex_duty', fx: [], dutyRate: null, startMs: 100 })
  check('X9 kitcoSeries: the window starts at startMs', ser3.pts.length === 1 && ser3.pts[0].v === 2 && ser3.firstMs === 150)
  const ks = K.kitcoStats([{ ms: 1, v: 10 }, { ms: 2, v: 14 }, { ms: 3, v: 8 }, { ms: 4, v: 12 }], 11)
  eq('X9 kitcoStats vs the previous close', [ks?.hi, ks?.lo, ks?.hiMs, ks?.loMs, ks?.chg, ks?.baseKind], [14, 8, 2, 3, 1, 'prev_close'])
  eq('X9 kitcoStats without a previous close: vs the window\'s first point', [K.kitcoStats([{ ms: 1, v: 10 }, { ms: 2, v: 12 }])?.chg, K.kitcoStats([{ ms: 1, v: 10 }, { ms: 2, v: 12 }])?.baseKind, K.kitcoStats([])], [2, 'window_first', null])
  const big = Array.from({ length: 10_000 }, (_, i) => ({ ms: i, v: Math.sin(i / 50) * 100 + (i === 7777 ? 500 : 0) - (i === 1234 ? 400 : 0) }))
  const dec = K.decimate(big, 1600)
  check('X9 decimate keeps the window\'s extremes and the last point within the budget', dec.length <= 1601 && dec.some(p => p.ms === 7777) && dec.some(p => p.ms === 1234) && dec[dec.length - 1].ms === 9999 && dec.every((p, i) => i === 0 || p.ms >= dec[i - 1].ms))
  check('X9 decimate leaves a short series alone', K.decimate([{ ms: 1, v: 1 }, { ms: 2, v: 2 }]).length === 2)
  const t0 = Date.parse('2026-11-04T18:30:00Z')
  const tt24 = K.timeTicks(t0, t0 + 86_400_000), ttAll = K.timeTicks(Date.parse('2000-08-30T00:00:00Z'), Date.parse('2026-11-05T00:00:00Z'))
  check('X9 timeTicks: clock labels inside a day, years over 26 years, never more than asked', tt24.length > 0 && tt24.every(t => /^\d{2}:00$|^\d{2} [A-Z][a-z]{2}$/.test(t.label)) && ttAll.length > 0 && ttAll.length <= 8 && ttAll.every(t => /^\d{4}$/.test(t.label)))
  eq('X9 the page unit → the panel unit (₹/tola reads ₹/10 g)', ['usd_oz', 'inr_g', 'tola', 'x'].map(K.kitcoUnitFromPage), ['usd_oz', 'inr_g', 'inr_10g', 'usd_oz'])
  const dvx = src('components/gold/DailyView.tsx'), kc = src('components/gold/KitcoChart.tsx')
  check('X9 d.24h is the Kitco panel: every timeframe and unit chip, the duty toggle, the stats, the Kitco link — a LINK (the stack never fetches kitco.com)',
    /KITCO_TIMEFRAMES\.map/.test(dvx) && /KITCO_UNITS\.map/.test(dvx) && /data-gold-kitco-duty="duty_paid"/.test(dvx) && /data-gold-kitco-stats/.test(dvx) && /href=\{KITCO_URL\}/.test(dvx)
    && !walk(path.join(UI, 'lib')).concat(walk(path.join(UI, 'components'))).some(f => /(fetch|get|getJson|client\.get)\([^)]*kitco\.com/.test(fs.readFileSync(f, 'utf8'))))
  check('X9 the chart reads only /api/gold/bars (GC=F, INR=X) — no Yahoo, no other source', /getGoldBars\('INR=X', '1d'/.test(dvx) && /getGoldBars\('INR=X', '1m'\)/.test(dvx) && !/query[12]\.finance\.yahoo|yfinance/.test(dvx + kc))
  check('X9 the price change is the only colour (§f.3); session bands on 24 h; previous close dashed', /kstats\.chg > 0 \? T\.green/.test(dvx) && /data-gold-band=\{b\.key\}/.test(kc) && /data-gold-prev-close/.test(kc))
  // ── X10 (round 2, D4): CONTRACTS › MCX CHAIN — one session, the band's own, never the request date ─────────────────
  const curveR2 = { date: '2026-11-05', chain_session: '2026-11-03', chain_session_label: 'Tue 03 Nov settlement', oi_session: '2026-11-04',
    points: [{ expiry: '2026-12-04', settle_or_last: 139452, source: 'icici_master_band', trade_date: '2026-11-04', session_date: '2026-11-04' }] }
  const ch = F.chainSession(curveR2)
  eq('X10 chainSession: the server\'s chain_session (the band\'s own), the OI\'s session, the band source', [ch.session, ch.day, ch.oiSession, ch.source], ['2026-11-03', 'Tue 03 Nov', '2026-11-04', 'band_midpoint'])
  check('X10 negative control: a pre-1d /curve (no chain_session) is NOT dated by the request date or the row\'s re-keyed session_date', F.chainSession({ ...curveR2, chain_session: null, chain_session_label: null }).session === null
    && F.chainSession({ ...curveR2, chain_session: null, chain_session_label: null }).day === '')
  eq('X10 chainRowSettlement: a band row is dated by the chain session, never its session_date (Wed 04 Nov, the file\'s re-key)', F.chainRowSettlement(curveR2.points[0], ch), { settlement: 139452, settlement_source: 'band_midpoint', settlement_session: '2026-11-03' })
  const basisR2 = F.curveBasisSettlement({ mcx_front_inr: 143237, mcx_front_session: '2026-11-04', mcx_front_session_label: 'Wed 04 Nov settlement', mcx_front_quality: 'vwap30_proxy', mcx_front_source: 'breeze_vwap30',
    band_midpoint: 139452, band_session: '2026-11-03', settlement_check: { band_vs_vwap30_pct: -2.64, flagged: true } })
  eq('X10 curveBasisSettlement maps the basis block\'s mcx_front_* names (the real server sends no settlement_source there)', [basisR2?.settlement, basisR2?.settlement_source, basisR2?.settlement_session], [143237, 'breeze_vwap30', '2026-11-04'])
  const cn = F.chainSettleNote(ch, basisR2)
  check('X10 chainSettleNote: band chain (Tue 03 Nov) + VWAP basis (Wed 04 Nov) → the note says both sessions, amber when flagged, no numbers',
    cn?.tone === 'amber' && /Tue 03 Nov/.test(cn.text) && /Wed 04 Nov/.test(cn.text) && /band/.test(cn.text) && !/1,39,452|1,43,237/.test(cn.text), cn)
  check('X10 negative control: the note never claims "this panel uses the last-30-min VWAP" for a band chain', !/this panel uses the last-30-min VWAP/.test(cn?.text ?? ''))
  check('X10 band chain + band basis → the muted band caution; an official / VWAP chain on the basis\'s session → no note', F.chainSettleNote(ch, { settlement: 139452, settlement_source: 'band_midpoint', settlement_session: '2026-11-03' })?.tone === 'muted'
    && F.chainSettleNote({ source: 'breeze_vwap30', session: '2026-11-04', day: 'Wed 04 Nov', oiSession: null }, basisR2) === null)
  check('X10 c.mcx never prints `session ${dayLabel(mc.date)}`; it renders chain_session_label and the OI session, and the basis line has no request-date fallback',
    !/session \$\{dayLabel\(mc\.date\)\}/.test(cvx) && /mc\?\.chain_session_label/.test(cvx) && /OI at the \$\{dayLabel\(chain\.oiSession\)\} close/.test(cvx) && !/mc\.date \? `\$\{dayLabel\(mc\.date\)\} settlement`/.test(cvx)
    && /chainRowSettlement\(p, chain\)/.test(cvx) && /data-gold-chain-session/.test(cvx))
  // ── X11 (round 2, D5): Kitco — one date's close is ONE rupee number on every timeframe; each number once per panel ─────
  const fxD = K.dailyFxRows([{ ts: '2026-11-03', c: 88.0 }, { ts: '2026-11-04', c: 88.5 }, { ts: '2026-11-02', c: null }])
  eq('X11 fxOnDate: the close of the date itself, a holiday takes the latest earlier date, none before the first', [K.fxOnDate(fxD, '2026-11-04'), K.fxOnDate(fxD, '2026-11-05'), K.fxOnDate(fxD, '2026-11-01')], [88.5, 88.5, null])
  const wedClose24h = K.dailyCloseIn(4000, '2026-11-04', 'inr_10g', 'duty_paid', fxD, { pct: 15, effective: '2026-05-13' })
  const allSer = K.kitcoSeries([{ ms: Date.parse('2026-11-03T00:00:00Z'), usd: 3950, date: '2026-11-03' }, { ms: Date.parse('2026-11-04T00:00:00Z'), usd: 4000, date: '2026-11-04' }],
    { unit: 'inr_10g', duty: 'duty_paid', fx: K.dailyFxPoints([{ ts: '2026-11-03', c: 88.0 }, { ts: '2026-11-04', c: 88.5 }]), dutyRate: { pct: 15, effective: '2026-05-13' }, startMs: null, fxDaily: fxD })
  near('X11 the Wed 04 Nov close converts at Wed\'s INR=X close (88.5): 24 h\'s dashed line = the same date on \'all\'', wedClose24h, 4000 * 88.5 * 10 / 31.1034768 * 1.15)
  check('X11 …and \'all\' prints the very same number for that date', allSer.pts.length === 2 && wedClose24h != null && Math.abs(allSer.pts[1].v - wedClose24h) < 1e-9, allSer)
  const lagged = K.kitcoSeries([{ ms: Date.parse('2026-11-04T00:00:00Z'), usd: 4000 }], { unit: 'inr_10g', duty: 'ex_duty', fx: K.dailyFxPoints([{ ts: '2026-11-03', c: 88.0 }, { ts: '2026-11-04', c: 88.5 }]), dutyRate: null, startMs: null })
  check('X11 negative control: the round-1 instant rule (no date) gave the PREVIOUS day\'s rate (88.0) — the defect the date rule removes', Math.abs(lagged.pts[0].v - 4000 * 88.0 * 10 / 31.1034768) < 1e-9)
  const legend = K.kitcoLegend([{ date: '2026-11-03', pts: [{ c: 3950 }] }, { date: '2026-11-04', pts: [{ c: 4000 }] }, { date: '2026-11-05', pts: [{ c: 4050 }] }],
    [{ date: '2026-11-02', o: 0, h: 0, l: 0, c: 3900, v: 0 }, { date: '2026-11-03', o: 0, h: 0, l: 0, c: 3950, v: 0 }, { date: '2026-11-04', o: 0, h: 0, l: 0, c: 4000, v: 0 }], { price: 4050 }, (u: number) => u, 1, '2026-11-04')
  check('X11 the 24 h legend prints each number once: no today row (the stats + the chart\'s last), the dashed date keeps only its Δ, the older close prints its value',
    legend.length === 2 && !legend.some(l => /Thu 05 Nov|last /.test(l)) && /^Wed 04 Nov ▲50\.0/.test(legend[1]) && !/4000\.0|4,000\.0/.test(legend[1]) && /dashed line/.test(legend[1]) && /Tue 03 Nov close .* 3,?950\.0 ▲50\.0/.test(legend[0]), legend)
  check('X11 DailyView: the dashed close uses the date rule (closeIn); the stats row has no "prev close" number; the subtitle never repeats the live price; the strip\'s reference is named',
    /prevCloseK = prevClose \? closeIn\(prevClose\.c, prevClose\.date\)/.test(dvx) && !/>prev close <b/.test(dvx) && !/live \$\{fmtInUnit\(live\.price/.test(dvx) && /data-gold-kitco-strip-ref/.test(dvx) && /settleValue=\{serverSettle \? undefined : prevCloseK\}/.test(dvx))
  check('X11 3 days takes its high / low from the same 1-minute highs and lows as 24 h (a 3-day high is never below the 24 h high)', /if \(!intraday \|\| !kstats0\) return kstats0/.test(dvx) && /else for \(const b of data\?\.bars \?\? \[\]\)/.test(dvx))
  check('X11 the 1-minute rupee bars load for every rupee window (the last value is one number on every window)', /maybe\(rupee, \(\) => getGoldBars\('INR=X', '1m'\)\)/.test(dvx))
  check('X11 the charts mark high / low without re-printing the stats row\'s numbers (§f.6)', !/hi \{fmtFixed\(/.test(kc) && !/lo \{fmtFixed\(/.test(kc) && /data-gold-hilo-marks/.test(kc))
  check('X11 the header strip names its change\'s reference where it prints', /data-gold-strip-chg-ref/.test(hs2))
  // ── X12 (round 2, D3): PETAL (₹/1 g) / GUINEA (₹/8 g) scaled to ₹/10 g beside ₹/10 g values, labelled ───────────────
  eq('X12 quoteGrams / quoteUnitShort from the server\'s quote unit or the family', [F.quoteGrams('₹ per 1 g'), F.quoteGrams('₹/8 g'), F.quoteGrams('GOLDGUINEA'), F.quoteGrams('GOLD'), F.quoteGrams('x'), F.quoteUnitShort('₹ per 10 g'), F.quoteUnitShort('GOLDPETAL')],
    [1, 8, 8, 10, null, '₹/10 g', '₹/1 g'])
  const g8 = F.toPer10g(112211, '₹ per 8 g'), g1 = F.toPer10g(14033, 'GOLDPETAL'), g10 = F.toPer10g(139452, 'GOLD')
  check('X12 toPer10g: GUINEA × 1.25 (₹1,12,211 → ₹1,40,264), PETAL × 10, GOLD untouched (negative control), the label says so', Math.round(g8.value ?? 0) === 140264 && g8.scaled && /scaled from ₹\/8 g/.test(g8.label)
    && g1.value === 140330 && g1.from === '₹/1 g' && !g10.scaled && g10.value === 139452 && g10.label === '₹/10 g')
  const ref = 143986
  check('X12 ladderPer10g: explicit unit → scaled; an unscaled PETAL / GUINEA bar labelled ₹/10 g is read in the unit nearer the 10 g reference; an already-scaled one is left alone',
    F.ladderPer10g({ value: 14033, unit: '₹/1 g' }, null).value === 140330
    && F.ladderPer10g({ value: 14033, unit: '₹/10 g', label: 'MCX GOLDPETAL NOV-26 settle' }, ref).value === 140330
    && Math.round(F.ladderPer10g({ value: 112211, unit: '₹/10 g', label: 'MCX GOLDGUINEA NOV-26 settle' }, ref).value ?? 0) === 140264
    && F.ladderPer10g({ value: 140264, unit: '₹/10 g', label: 'MCX GOLDGUINEA NOV-26 settle' }, ref).scaled === false
    && F.ladderPer10g({ value: 139452, unit: '₹/10 g', label: 'MCX GOLD DEC-26 settle' }, ref).scaled === false
    && F.ladderPer10g({ value: 140330, scaled_from: '₹/1 g', unit: '₹/10 g' }, ref).value === 140330)
  check('X12 the chain / ladder print the family\'s own unit (never "settle ₹/10 g" on PETAL) and a ₹/10 g column for a scaled family; PHYSICAL scales its bars',
    /label: `settle \$\{famUnit\}`/.test(cvx) && /label: `settle \$\{chainUnit\}/.test(cvx) && /'₹\/10 g eq\.'/.test(cvx) && !/'settle ₹\/10 g'/.test(cvx) && /ladderPer10g\(s, dutyPaidRef\)/.test(src('components/gold/PriceLadder.tsx')))
  // ── X13 (round 2, D2): the accuracy log flags and re-explains, never rewrites ─────────────────────────────────────
  const rowStale = { date: '2026-11-05', stale_baseline: true, baseline_check: { band_vs_vwap30_pct: -2.64, flagged: true, compared: 'baseline ₹1,39,452 labelled Wed 04 Nov settlement vs that session\'s last-30-min VWAP ₹1,43,237' } }
  eq('X13 logCheckWords: flagged (its own sentence) · ok · unknown · flagged by the session rule', [F.logCheckWords(rowStale).state, F.logCheckWords({ baseline_check: { band_vs_vwap30_pct: 0.1, flagged: false } }).state, F.logCheckWords({}).state, F.logCheckWords({ stale_baseline: true }).state],
    ['flagged', 'ok', 'unknown', 'flagged'])
  check('X13 the flagged words keep the stored numbers and re-explain them', /labelled Wed 04 Nov/.test(F.logCheckWords(rowStale).text) && /stored numbers stand/.test(F.logCheckWords(rowStale).text))
  const ar = F.accuracyRead({ mean_abs_error: 1500, naive_mean_abs_error: 1200, stale_baseline_count: 7, stale_baseline_dates: ['2026-10-27'], stale_baseline_unknown: ['2026-10-26'], excluding_stale: { days: 0 } }, [])
  check('X13 accuracyRead: every-row verdict, the stale rows named, unknown counted, and the read without them', ar.better === false && ar.stale === 7 && ar.unknown === 1 && /no scored day left/.test(ar.cleanLine ?? ''))
  check('X13 negative control: no stale rows → no "without the stale rows" line', F.accuracyRead({ mean_abs_error: 1, naive_mean_abs_error: 2, stale_baseline_count: 0, excluding_stale: { days: 3, mean_abs_error: 1, naive_mean_abs_error: 2 } }, []).cleanLine === null)
  check('X13 the log table shows the check column and the strip both reads', /key: 'check', label: 'Check vs VWAP30'/.test(src('components/gold/GoldAccuracyLog.tsx')) && /accuracyRead\(stats, rows\)/.test(src('components/gold/GoldAccuracyLog.tsx')))
  // ── X14 (round 2): the India-basis tile and the strip print each phrase / day once ─────────────────────────────────
  eq('X14 basisTileWords: the server label once; the purity added only when the label does not name it', [
    F.basisTileWords('live MCX (ICICI Breeze) vs duty-paid landed at 995 now', 'landed_995'),
    F.basisTileWords('at the Wed 04 Nov settlement vs that session\'s duty-paid landed', 'landed_995'),
    F.basisTileWords(null, 'landed_999')],
    ['live MCX (ICICI Breeze) vs duty-paid landed at 995 now', 'at the Wed 04 Nov settlement vs that session\'s duty-paid landed · vs the 995 duty-paid landed', 'vs the 999 duty-paid landed'])
  check('X14 the India-basis tile value is signed (+0.42 %), the same sign the strip prints', /g\.key === 'india_basis'\) return fmtSignedPctSp\(g\.value, 2\)/.test(hv) && /basisTileWords\(/.test(hv))
  check('X14 the strip\'s live branch dates the settlement basis by its own session first (a stored fallback can be older)', /dayLabel\(s\?\.basis_settle_date \?\? s\?\.basis_session\) \|\| settlementDay\(st\)/.test(hs2))
}

// ── Y. wave 1e (the 6 Nov final critics C-DATA-3 / C-TRADER-3): one basis per clock for the PICKED contract (M-A), one real
//       yield per page (M-B), the Shanghai legs reproduce the premium (M-C), a baseline older than expected is flagged (M-D),
//       and the UI minors (M-E). Fixtures are the real 6 Nov 09:17–09:21 payloads, trimmed. Every rule has a negative control.
{
  type Ov = import('../../lib/gold/types').GoldOverview
  type GH = import('../../lib/gold/types').GoldHealth
  const AS_OF = '2026-11-06T09:21:42+05:30'
  // /api/gold/overview?contract=GOLDTEN at 09:21 (MCX open, the live Breeze quote folded in by apply_live_mcx)
  const liveGauge = { key: 'india_basis', label: 'INDIA BASIS', value: 0.89, unit: '%', state: 'live', badge: 'context', clock: 'now', basis_contract: 'GOLDTEN NOV-26',
    basis_label: 'live MCX (ICICI Breeze (1-min bars)) vs duty-paid landed at 999 now', basis_reference: 'landed_999', release_at: '2026-11-06T09:10:20+05:30',
    report_date: '2026-11-06', settle_basis_pct: 0.69, settle_basis_date: '2026-11-05', settlement_source: 'breeze_vwap30', settlement_quality: 'vwap30_proxy' }
  const ryFred = { key: 'real_yield', label: 'REAL YIELD 10-y', value: 2.65, unit: '%', state: 'delayed', badge: 'context', series_id: 'FRED_DFII10', report_date: '2026-11-03', change_bp: 5 }
  const ovHealth = { as_of: AS_OF, window: 'W', line: '', freshness: { state: 'delayed' }, fair: { comex: { symbol: 'GCZ26.CMX', price: 4052, as_of: '2026-11-06T09:10:20+05:30' }, mcx_live: 142542, mcx_live_as_of: '2026-11-06T14:50:00+05:30' },
    gauges: [liveGauge, ryFred],
    verdict: { line: '', clauses: [{ rule_id: 'H4', text: 'India basis +0.9 % vs duty-paid landed 999 (live)', series_id: 'MCX_BASIS_PCT', value: 0.89, clock: 'now' }] } } as unknown as GH
  const ov = { as_of: AS_OF, contract: { mcx: 'GOLDTEN', expiry: '2026-11-30' }, session: { mcx: { is_open: true }, comex: { is_open: true } },
    strip: { basis_pct: 0.89, basis_clock: 'now', basis_live_pct: 0.89, basis_settle_pct: 0.69, mcx_shown: 'live', mcx_live: 142542, mcx_live_as_of: '2026-11-06T14:50:00+05:30',
             real_10y: 2.65, real_10y_date: '2026-11-03' },
    quote: { available: true, quote: { ltp: 142542, time: '2026-11-06 09:20:00' } }, health: ovHealth, freshness: {} } as unknown as Ov
  // /api/gold/health at 09:17 (GOLD, the settlement clock): the payload HEALTH rendered before wave 1e
  const goldHealth = { as_of: '2026-11-06T09:17:00+05:30', window: 'W', line: '', freshness: { state: 'delayed' }, fair: {},
    gauges: [{ key: 'india_basis', value: 0.85, unit: '%', state: 'delayed', badge: 'context', clock: 'settlement', basis_contract: 'GOLD DEC-26', settle_basis_date: '2026-11-05' }],
    verdict: { line: '', clauses: [{ rule_id: 'H4', text: 'India basis +0.8 % vs duty-paid landed 995 (Thu 05 Nov settlement)', value: 0.85 }] } } as unknown as GH

  // M-A: which payload HEALTH renders
  const pk = F.pickPageHealth(ov, 'ok', goldHealth)
  check('Y1 HEALTH renders the overview\'s health (picked contract, live quote applied), never /health when the overview has one', pk.source === 'overview' && pk.health === ovHealth)
  check('Y1 while the overview loads nothing is rendered (no GOLD flash under a GOLDTEN strip); /health only once the overview failed',
    F.pickPageHealth(null, 'loading', goldHealth).waiting && F.pickPageHealth(null, 'loading', goldHealth).health === null
    && F.pickPageHealth(null, 'error', goldHealth).source === 'health' && F.pickPageHealth({ health: null }, 'ok', goldHealth).source === 'health')
  eq('Y1 needsHealthFallback: never with an overview health, never while loading', [F.needsHealthFallback(ov, 'ok'), F.needsHealthFallback(null, 'loading'), F.needsHealthFallback(null, 'error'), F.needsHealthFallback({ health: null }, 'ok')],
    [false, false, true, true])
  // M-A: strip == gauge == verdict, for a non-GOLD pick during MCX hours
  const ag = F.basisAgreement(ov, ovHealth)
  check('Y2 strip == gauge == verdict (GOLDTEN, live clock): +0.89 % three times, one clock', ag.ok && ag.clock === 'now' && ag.strip === 0.89 && ag.gauge === 0.89 && ag.verdict === 0.89
    && F.fmtSignedPctSp(ag.strip, 2) === F.fmtSignedPctSp(ag.gauge, 2) && F.fmtSignedPctSp(ag.gauge, 2) === '+0.89 %')
  const agOld = F.basisAgreement(ov, goldHealth)
  check('Y2 negative control: the pre-1e page (GOLDTEN strip, /health GOLD gauge at the settlement) is flagged, not printed as two bases', !agOld.ok && /GOLD DEC-26/.test(agOld.reason ?? ''))
  const sameContractSettle = { ...goldHealth, gauges: [{ ...goldHealth.gauges[0], basis_contract: 'GOLDTEN NOV-26' }] } as unknown as GH
  check('Y2 negative control: the right contract at the settlement clock while the strip prints a live basis is flagged', !F.basisAgreement(ov, sameContractSettle).ok)
  const h4Off = { ...ovHealth, verdict: { line: '', clauses: [{ rule_id: 'H4', text: 'India basis +0.7 % (live)', value: 0.69, clock: 'now' }] } } as unknown as GH
  check('Y2 negative control: an H4 clause on another value is flagged', !F.basisAgreement(ov, h4Off).ok && /verdict/.test(F.basisAgreement(ov, h4Off).reason ?? ''))
  const ovClosed = { ...ov, session: { mcx: { is_open: false }, comex: { is_open: true } }, strip: { basis_pct: 0.69, basis_clock: 'settlement', basis_settle_pct: 0.69, mcx_shown: 'settlement' } } as unknown as Ov
  const hClosed = { ...ovHealth, gauges: [{ ...liveGauge, value: 0.69, clock: 'settlement', state: 'delayed' }], verdict: { line: '', clauses: [{ rule_id: 'H4', text: 'India basis +0.7 % (Thu 05 Nov settlement)', value: 0.69, clock: 'settlement' }] } } as unknown as GH
  check('Y2 MCX closed: strip == gauge == verdict at the settlement clock', F.basisAgreement(ovClosed, hClosed).ok && F.basisAgreement(ovClosed, hClosed).clock === 'settlement')
  // M-A: the chip names its clock; a future time is never printed
  eq('Y3 basisClockChip: LIVE · MCX (Breeze bar minute) · COMEX (the Yahoo leg\'s time)', F.basisClockChip(liveGauge as never, ov), { kind: 'live', text: 'LIVE · MCX 09:20 · COMEX 09:10' })
  const ovNoQuote = { ...ov, quote: null } as unknown as Ov
  eq('Y3 negative control: only the +5:30-shifted mcx_live_as_of (14:50 at 09:21) → the time is not printed', F.basisClockChip(liveGauge as never, ovNoQuote)?.text, 'LIVE · MCX time not stated · COMEX 09:10')
  eq('Y3 the settlement chip names source quality and session', F.basisClockChip({ clock: 'settlement', settle_basis_date: '2026-11-05', settlement_source: 'breeze_vwap30', settlement_quality: 'vwap30_proxy' } as never, ov)?.text,
    'SETTLEMENT · VWAP30 PROXY · Thu 05 Nov')
  eq('Y3 the server\'s clock_label wins (contract named), plus the COMEX leg\'s time; a served label in the future is not printed', [
    F.basisClockChip({ ...liveGauge, clock_label: 'LIVE · GOLDTEN NOV-26 · 09:20 IST' } as never, ov)?.text,
    F.basisClockChip({ ...liveGauge, clock_label: 'LIVE · GOLDTEN NOV-26 · 14:50 IST' } as never, ov)?.text,
    F.basisClockChip({ clock: 'settlement', clock_label: 'SETTLEMENT · BAND PROXY · Wed 04 Nov' } as never, ov)?.text],
    ['LIVE · GOLDTEN NOV-26 · 09:20 IST · COMEX 09:10', 'LIVE · MCX 09:20 · COMEX 09:10', 'SETTLEMENT · BAND PROXY · Wed 04 Nov'])
  eq('Y3 istHm: Breeze\'s zone-less IST time read as IST; a time after as_of is dropped', [F.istHm('2026-11-06 09:16:00', AS_OF), F.istHm('2026-11-06T14:46:00+05:30', AS_OF), F.istHm('2026-11-06T09:10:20+05:30', AS_OF), F.istHm(null, AS_OF)],
    ['09:16', '', '09:10', ''])
  eq('Y3 mcxLiveClock: the strip prints \'live · 09:20\' (Breeze bar), never 14:50', [F.mcxLiveClock(ov), F.mcxLiveClock(ovNoQuote)], ['09:20', ''])
  const hvY = src('components/gold/HealthView.tsx')
  const kitY = src('components/gold/kit.tsx')
  check('Y4 HealthView and LearnView read usePageHealth (no own /health fetch); the hook passes the pick to the fallback',
    /usePageHealth\(\{ overview, overviewStatus, window, sel \}/.test(hvY) && !/getGoldHealth\(/.test(hvY) && /usePageHealth\(/.test(src('components/gold/LearnView.tsx')) && !/getGoldHealth\(/.test(src('components/gold/LearnView.tsx'))
    && /getGoldHealth\(p\.window, \{ contract: p\.sel\.family, expiry: p\.sel\.expiry \}\)/.test(kitY) && /pickPageHealth\(p\.overview, p\.overviewStatus, fb\.data\)/.test(kitY))
  check('Y4 HEALTH says a disagreement and a fallback in words (never two bases silently)', /data-gold-basis-mismatch/.test(hvY) && /basisAgreement\(overview, h\)/.test(hvY) && /data-gold-health-fallback/.test(hvY))
  check('Y4 getGoldHealth / getGoldPremiums carry contract + expiry; Brief / WEI keep the GOLD echo (window only)',
    /getGoldHealth = \(window: Window = 'D', q: ContractQuery = \{\}\)/.test(src('lib/gold/api.ts')) && /getGoldPremiums = \(days = 365, q: ContractQuery = \{\}\)/.test(src('lib/gold/api.ts')) && /getGoldHealth\('W'\)/.test(src('components/Brief.tsx')))
  check('Y4 the strip prints the live quote\'s minute and reads stripBasis (the same function the check uses)', /mcxLiveClock\(overview\)/.test(src('components/gold/HealthStrip.tsx')) && /data-gold-strip-mcx-clock/.test(src('components/gold/HealthStrip.tsx')))

  // M-B: one 10-y real yield per page
  const stripFixed = { real_10y: 2.6, real_10y_date: '2026-11-05', real_10y_series_id: 'UST_REAL_10Y' }
  const hFixed = { gauges: [{ key: 'real_yield', value: 2.6, report_date: '2026-11-05', series_id: 'UST_REAL_10Y', label_note: 'UST_REAL_10Y: fresher than FRED_DFII10 (last 2026-11-03)' }] } as unknown as GH
  const macroDriver = { value: 2.6, report_date: '2026-11-05', series_id: 'UST_REAL_10Y' }
  const pr = F.pageRealYield(stripFixed, hFixed)
  check('Y5 the fixed server: strip == gauge == MACRO print \'2.60 % · Thu 05 Nov\', no mismatch note',
    F.realYieldPrint(pr.value, pr.date) === '2.60 % · Thu 05 Nov' && F.realYieldPrint(hFixed.gauges[0].value, hFixed.gauges[0].report_date) === F.realYieldPrint(macroDriver.value, macroDriver.report_date)
    && F.realYieldMismatch(pr, macroDriver) === null && pr.seriesId === 'UST_REAL_10Y')
  const prOld = F.pageRealYield({ real_10y: 2.65, real_10y_date: '2026-11-03' }, { gauges: [ryFred] } as unknown as GH)
  check('Y5 negative control: the 6 Nov page (strip / HEALTH FRED Tue, MACRO Treasury Thu) is said on MACRO, without repeating the number',
    /older point \(Tue 03 Nov, FRED DFII10/.test(F.realYieldMismatch(prOld, macroDriver) ?? '') && !/2\.65/.test(F.realYieldMismatch(prOld, macroDriver) ?? ''))
  const prGaugeFresher = F.pageRealYield({ real_10y: 2.65, real_10y_date: '2026-11-03' }, hFixed)
  check('Y5 the fresher of strip and gauge wins (same quantity, the later date); a tie keeps the strip', prGaugeFresher.from === 'gauge' && prGaugeFresher.value === 2.6
    && F.pageRealYield({ real_10y: 2.61, real_10y_date: '2026-11-05' }, hFixed).from === 'strip')
  check('Y5 the strip, its hover card and MACRO read pageRealYield; MACRO renders label_note verbatim (never \'no stored points\')',
    /pageRealYield\(s, overview\?\.health\)/.test(src('components/gold/HealthStrip.tsx')) && /pageRealYield\(s, o\.health\)/.test(src('components/gold/HealthStrip.tsx'))
    && /realYieldMismatch\(pageRy, d\)/.test(src('components/gold/MacroView.tsx')) && !/the primary series has no stored points/.test(src('components/gold/MacroView.tsx')))

  // M-C: the printed legs reproduce the printed premium
  const shBad = { sge_usd_oz: 4035.79, london_pm_usd: 4037.8, premium_usd: 1.5 }
  const shGood = { sge_usd_oz: 4035.79, london_pm_usd: 4037.8, premium_usd: -2.01, reconciles: true }
  check('Y6 shanghaiReconcile: 4,035.79 − 4,037.80 = −2.01 → a premium of −2.01 reconciles; the 6 Nov +1.50 does not', F.shanghaiReconcile(shGood).ok === true && F.shanghaiReconcile(shBad).ok === false
    && F.shanghaiReconcile(shBad).legs === -2.01 && Math.abs((F.shanghaiReconcile(shBad).diff ?? 0) + 3.51) < 1e-9)
  check('Y6 negative control: a server reconciles=false wins even when the client legs agree; missing leg → null', F.shanghaiReconcile({ ...shGood, reconciles: false }).ok === false && F.shanghaiReconcile({ premium_usd: 1 }).ok === null)
  check('Y6 PHYSICAL shows the mismatch note and the server\'s recompute note', /shanghaiReconcile\(sh\)/.test(src('components/gold/PhysicalView.tsx')) && /data-shanghai-reconcile="mismatch"/.test(src('components/gold/PhysicalView.tsx')) && /sh\.recompute_note/.test(src('components/gold/PhysicalView.tsx')))

  // M-D: the baseline session older than the latest completed session (Muhurat Sun 8 Nov missing on Mon 9 Nov)
  const muhurat = { settlement: 143900, settlement_source: 'breeze_vwap30', settlement_session: '2026-11-06', settlement_quality: 'vwap30_proxy', settlement_is_latest: false, latest_session: '2026-11-08' }
  check('Y7 a baseline older than the latest completed session (Fri 06 Nov vs the Sun 08 Nov Muhurat) is an amber note naming both sessions',
    /older than expected/.test(F.settlementOlderThanLatest(muhurat) ?? '') && /Fri 06 Nov/.test(F.settlementOlderThanLatest(muhurat) ?? '') && /Sun 08 Nov/.test(F.settlementOlderThanLatest(muhurat) ?? '')
    && F.settlementNote(muhurat)?.tone === 'amber' && /older than expected/.test(F.settlementNoteShort(muhurat)?.text ?? ''))
  check('Y7 negative controls: the latest session\'s VWAP, a broker close and no settlement raise nothing',
    F.settlementOlderThanLatest({ ...muhurat, settlement_is_latest: true, latest_session: '2026-11-06' }) === null
    && F.settlementOlderThanLatest({ ...muhurat, settlement_source: 'breeze_previous_close' }) === null && F.settlementOlderThanLatest({ settlement: null }) === null)
  // the server's Mon 9 Nov 08:45 shape (gold_preopen wave 1e): /fair.baseline.older_than_expected + expected_session + older_note
  const fair9Nov = { baseline: { value: 143900, source: 'Fri 06 Nov settlement (last-30-min VWAP)', session: '2026-11-06', settlement_source: 'breeze_vwap30', settlement_quality: 'vwap30_proxy',
    older_than_expected: true, expected_session: '2026-11-08', older_note: 'baseline session older than expected: the Fri 06 Nov settlement is used, but the latest completed session is the Sun 08 Nov settlement (Muhurat trading, 14:20–15:30 IST) and no last-30-min VWAP is stored or read for it (not fetched); the fair open also carries that session\'s move' } }
  const bl9 = F.baselineSettlement(fair9Nov as never, null, 'GOLD')
  check('Y7 Mon 9 Nov 08:45: /fair.baseline.older_than_expected becomes the amber note in the server\'s words (Muhurat named)',
    bl9?.settlement_is_latest === false && bl9?.latest_session === '2026-11-08' && F.settlementNote(bl9)?.tone === 'amber' && /^Baseline session older than expected: .*Muhurat trading, 14:20–15:30 IST/.test(F.settlementNote(bl9)?.text ?? ''))
  check('Y7 negative control: the same baseline with older_than_expected false and no later session raises nothing',
    F.settlementNote(F.baselineSettlement({ baseline: { ...fair9Nov.baseline, older_than_expected: false, expected_session: '2026-11-06', older_note: null } } as never, null, 'GOLD')) === null)
  check('Y7 the strip and the baseline carry the latest-session fields through', F.stripSettlement(muhurat).latest_session === '2026-11-08' && F.stripSettlement(muhurat).settlement_is_latest === false)

  // M-E: event tags, delayed COMEX leg, Kitco grouping, the rupee leg, OI span, WEEKLY impossible open
  eq('Y8 eventSessionTag: untimed rows are ALL DAY / a closure, never AFTER CLOSE; timed rows keep their words', [
    F.eventSessionTag({ time_ist: null, kind: 'FESTIVAL', name: 'Dhanteras', in_session: false, after_close: false })?.text,
    F.eventSessionTag({ time_ist: null, kind: 'MCX_HOLIDAY', name: 'MCX morning closure: Diwali-Balipratipada', in_session: false })?.text,
    F.eventSessionTag({ time_ist: '14:20', kind: 'MCX_SPECIAL', name: 'Muhurat trading', in_session: true })?.text,
    F.eventSessionTag({ time_ist: '00:30', kind: 'FOMC', name: 'FOMC', in_session: false, after_close: true })?.text],
    ['ALL DAY', 'MORNING CLOSED', 'IN SESSION', 'AFTER CLOSE · gap risk'])
  type Fr = import('../../lib/gold/types').Freshness
  const fr632 = F.delayedIfOld({ state: 'live', source: 'Yahoo (cached fetcher)', age_s: 632 } as Fr)
  check('Y8 a \'live\' COMEX leg 632 s old reads DELAYED ≈11 min; a 60 s one stays LIVE', fr632?.state === 'delayed' && /≈11 min delayed/.test(fr632?.source ?? '')
    && F.delayedIfOld({ state: 'live', source: 'Yahoo', age_s: 60 } as Fr)?.state === 'live')
  const KK = (await import(new URL('../../lib/gold/kitco.ts', import.meta.url).href)) as typeof import('../../lib/gold/kitco')
  eq('Y8 Kitco: USD units in Western grouping, rupees Indian', [KK.fmtKitco(132339, 0, 'usd_kg'), KK.fmtKitco(132339, 0, 'inr_10g'), KK.fmtKitco(132339, 0, 'USD/kg'), KK.fmtKitcoSigned(-1234.5, 1, 'usd_oz'), KK.fmtKitcoSigned(0, 0, 'usd_kg')],
    ['132,339', '1,32,339', '132,339', `${MINUS}1,234.5`, '0'])
  const inrFlat = F.inrLegWords({ now: 94.465, ref: 94.46499, as_of: '2026-11-05T15:40:00' })
  check('Y8 the rupee leg is dated (21:10 IST Thu 05 Nov) and said to be unchanged since the close; a moved leg is not', inrFlat?.flat === true && /21:10 IST Thu 05 Nov/.test(inrFlat?.text ?? '')
    && F.inrLegWords({ now: 94.4, ref: 94.465, as_of: '2026-11-06T03:50:00Z' })?.flat === false)
  const span = F.oiSpanByDate([{ trade_date: '2026-11-03', sessions_spanned: 3, span_note: 'over 3 sessions (master skipped 2)' }, { trade_date: '2026-11-04', sessions_spanned: 1 }])
  check('Y8 WEEKLY: a 3-session ΔOI is labelled, a 1-session one is not', span.get('2026-11-03')?.n === 3 && !span.has('2026-11-04') && /over \{r\.mcxSpan\.n\} sessions/.test(src('components/gold/WeeklyView.tsx')))
  const ten = { expiries: [{ expiry: '2026-12-31', oi: 12249, in_tender: false }, { expiry: '2026-11-30', oi: 29503, in_tender: true, tender_note: 'in tender since Sun 01 Nov (5 d)' }, { expiry: '2027-01-29', oi: 6604, in_tender: false }] }
  const ax = F.autoExpiry(ten)
  check('Y8 the default GOLDTEN pick: NOV-26 (OI front) is in tender → the page follows DEC-26 and says why; NOV-26 stays selectable',
    ax.expiry === '2026-12-31' && ax.front === '2026-11-30' && /in tender since Sun 01 Nov \(5 d\): the page follows DEC-26/.test(ax.reason ?? '')
    && /autoExpiry=\{auto\}/.test(src('components/gold/GoldPage.tsx')) && /sel\.expiry \|\| !auto\.expiry \? sel/.test(src('components/gold/GoldPage.tsx')))
  check('Y8 negative controls: a front not in tender keeps the server\'s pick; no family data → the server\'s pick',
    F.autoExpiry({ expiries: [{ expiry: '2026-12-04', oi: 15726, in_tender: false }, { expiry: '2027-02-05', oi: 1334 }] }).expiry === null && F.autoExpiry(null).expiry === null
    && F.autoExpiry({ expiries: [{ expiry: '2026-11-30', oi: 5, in_tender: true }] }).expiry === null)
  check('Y8 the accuracy read: the [B] copy says how many scored mornings were stale; the counterfactual is labelled, never the score',
    /7 of them priced off a stale settlement/.test(F.preOpenCopyB({ days: 8, median_abs_error: 1360, mean_abs_error: 1885, naive_mean_abs_error: 2008, stale_baseline_count: 7 }))
    && !/stale/.test(F.preOpenCopyB({ days: 8, median_abs_error: 1360, stale_baseline_count: 0 }))
    && /^counterfactual, not the score .* median miss ₹187 .* 71\.4 % within ₹300 .* naive ₹898/.test(F.onVwap30Line({ on_vwap30: { days: 7, median_abs_error: 187, mean_abs_error: 330.1, within_threshold_pct: 71.4, naive_mean_abs_error: 898.1 } }) ?? '')
    && F.onVwap30Line({ on_vwap30: null }) === null && /band midpoint labelled one session late/.test(F.staleReasonWords(['band_rule'])) && F.staleReasonWords([]) === '')
  const thu = S.dailyOhlc([{ ts: '2026-11-04', o: 4000, h: 4080, l: 3990, c: 4072.2 }, { ts: '2026-11-05', o: 3940.8, h: 4155.8, l: 4067.0, c: 4098.4, partial: true }])
  check('Y8 WEEKLY: the impossible Thu open (3,940.8 under a low of 4,067.0) is flagged, not drawn; the partial flag is carried',
    thu[1].openOutside === true && thu[1].o === 4098.4 && thu[1].rawOpen === 3940.8 && thu[1].partial === true && !thu[0].openOutside && !thu[0].partial)
  check('Y8 negative control: an open inside the range and the partial dates from /bars.daily_closes', S.dailyOhlc([{ ts: '2026-11-05', o: 4070, h: 4155.8, l: 4067, c: 4098.4 }], new Set(['2026-11-05']))[0].partial === true
    && !S.dailyOhlc([{ ts: '2026-11-05', o: 4070, h: 4155.8, l: 4067, c: 4098.4 }])[0].openOutside)

  // ── C-DATA-06: the shape ui-api ACTUALLY serves — the open withheld, the raw value beside it ──────────────────
  const served = S.dailyOhlc([{ ts: '2026-11-05', o: null, o_raw: 3940.8, ohlc_note: "open outside the day's range (Yahoo repeated the previous bar's open on a partial bar): withheld",
    h: 4155.8, l: 4067.0, c: 4098.4, v: 208286, partial: true }])[0]
  check('Y8b a WITHHELD open (o null, o_raw 3,940.8) is flagged exactly like an impossible one: o stays the close, the table prints —',
    served.openOutside === true && served.rawOpen === 3940.8 && served.o === 4098.4 && served.partial === true && /withheld/.test(served.note ?? ''),
    served)
  check('Y8b negative controls: o null with NO o_raw defaults to the close and is NOT flagged; a sane bar carries no note',
    S.dailyOhlc([{ ts: '2026-11-05', o: null, h: 4155.8, l: 4067, c: 4098.4 }])[0].openOutside === undefined
    && S.dailyOhlc([{ ts: '2026-11-05', o: null, h: 4155.8, l: 4067, c: 4098.4 }])[0].o === 4098.4
    && S.dailyOhlc([{ ts: '2026-11-04', o: 4000, h: 4080, l: 3990, c: 4072.2, o_raw: 3940.8 }])[0].openOutside === undefined)
  check('Y8b the withheld-open shape is typed (Bar and BarLike carry o_raw / c_raw / ohlc_note)',
    /o_raw\?: number \| null/.test(src('lib/gold/types.ts')) && /ohlc_note\?: string \| null/.test(src('lib/gold/types.ts'))
    && /o_raw\?: number \| null/.test(src('lib/gold/sessions.ts')))

  // ── CT-01 / F1: the SGE overlay may never set the 24-h axis in a foreign unit ─────────────────────────────────
  const main = [4035, 4046, 4098, 4128].map(c => ({ c }))
  const cny = [868, 884].map(c => ({ c }))
  const usd = [4036.76, 4129.92].map(c => ({ c }))
  check('CT-01 overlayOnScale: raw CNY/g (868) is OFF the $/oz scale and withheld with a reason; the converted series fits',
    KK.overlayOnScale(cny, main).pts === null && /off this chart's scale by 79 %/.test(KK.overlayOnScale(cny, main).why ?? '')
    && KK.overlayOnScale(usd, main).pts?.length === 2 && KK.overlayOnScale(usd, main).why === null,
    { cny: KK.overlayOnScale(cny, main), usd: KK.overlayOnScale(usd, main) })
  check('CT-01 overlayOnScale negative controls: an empty overlay is silent, no main series never draws, the tolerance is the only gate',
    KK.overlayOnScale([], main).pts === null && KK.overlayOnScale([], main).why === null
    && KK.overlayOnScale(usd, []).pts === null && /no series to scale/.test(KK.overlayOnScale(usd, []).why ?? '')
    && KK.overlayOnScale([{ c: 4046 * 1.24 }], main).pts?.length === 1 && KK.overlayOnScale([{ c: 4046 * 1.3 }], main).pts === null)
  const dv = src('components/gold/DailyView.tsx')
  check('CT-01 DailyView gates the SGE overlay on the SERVER\'s unit, matches it to the COMEX day on screen and runs it through overlayOnScale',
    /sgeUnitOk = \(sge\.data\?\.unit \?\? null\) === 'USD\/oz'/.test(dv)
    && /sgeGroups\.find\(g => g\.date === comexDay\.date\)/.test(dv)
    && /overlayOnScale\(sgeUnitOk \? sgeDay\?\.pts : null, comexDay\?\.pts, 25\)/.test(dv)
    && /sge=\{sgePts\}/.test(dv) && !/dayGroups\(sge\.data\.bars, usDst\)\.slice\(-1\)/.test(dv))
  check('CT-01 the d.sge panel dates its bars (never "today" for Friday\'s on a Sunday) and prints the native price and the rate it converted at',
    !/bars today/.test(dv) && /dayLabel\(sgeDay\.date\)/.test(dv) && /c_cny_g/.test(dv) && /at USDCNY /.test(dv)
    && /sgeWhyNoOverlay/.test(dv))
  // round 2: ONE rate per drawn session (the per-bar rule stepped the line $18 at Beijing midnight with no price move),
  // the rate's own partial flag, the refused-row count, the catalog gate over BOTH series the panel renders plus the FX
  // leg, and a lookup miss that no longer borrows the 'a line needs two' wording
  check('CT-01 r2 the panel names ONE rate for the whole session, flags a partial rate and says how many rows were refused',
    /the whole session at USDCNY /.test(dv) && /itself a partial print/.test(dv)
    && /sge\.data\?\.fx\?\.partial && sgeBar\.usdcny_date === sge\.data\.fx\.report_date/.test(dv)
    && /dropped_no_fx/.test(dv) && /no stored USDCNY on or before their session/.test(dv)
    && /ONE rate per session/.test(dv))
  check('CT-01 r2 negative controls: the old per-bar wording is gone, the catalog gate covers the FX leg and the 1-m bars, and a payload-row miss has its own sentence',
    !/\bat USDCNY \{fmtFixed\(sgeBar\.usdcny, 4\)\}[^]]*?\{' '\}— overlaid/.test(dv)
    && /series=\{\['SGE_DAILY', 'BARS_1M', 'FX_CNY'\]\}/.test(dv)
    && /could not be matched to its payload row/.test(dv)
    && /sgeDay\.pts\.length < 2/.test(dv))
  check('CT-01 r2 the payload shape is typed: the native twins of a withheld price, the rate\'s partial flag, the window\'s vintages and the refused count',
    /o_raw_cny_g\?: number \| null/.test(src('lib/gold/types.ts')) && /c_raw_cny_g\?: number \| null/.test(src('lib/gold/types.ts'))
    && /partial\?: boolean \| null; conversion\?: string \| null/.test(src('lib/gold/types.ts'))
    && /fx_vintages\?: string\[\] \| null/.test(src('lib/gold/types.ts')) && /dropped_no_fx\?: number \| null/.test(src('lib/gold/types.ts')))
}

console.log(`gold.check: ${passed} passed, ${failed} failed`)
if (failed) process.exit(1)

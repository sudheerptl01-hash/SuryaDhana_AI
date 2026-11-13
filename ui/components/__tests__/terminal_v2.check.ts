/**
 * Terminal v2 gate G9 (reports/terminal_v2/PLAN.md §1.7), B6-GATES: the UI rules as whole-tree static scans plus the pure
 * helpers, each rule with a negative control. B4's ui/components/vol/__tests__/terminal_v2.check.ts tests its own views in
 * depth (tests/terminal_v2_gates/test_g00_registry.py names those checks); this file is the independent, tree-wide gate:
 *
 *  G9.1 "IV percentile" and "IV rank" are different numbers and both are defined: every view that prints one prints the
 *       other, each with its hover definition from the route (`definitions.iv_rank_252` / `iv_pctile_252`).
 *  G9.2 context panels are never coloured by direction: no `badge="context"` Panel takes a data-dependent accent or the
 *       green / red direction tokens, and no VIX level is coloured green / red (a level is context).
 *  G9.3 the drivers' regime strip ends "describes, does not predict" whatever sentence the route sends.
 *  G9.4 every kit `<Panel` on every page carries `source=` (its SourceChip) — an independent scanner from B4's.
 *  G9.5 the VIX level once per page: at most one VIX level display (Stat / Line / Cell label) per page and the files it
 *       renders directly; the header tape is chrome, not a page.
 *  G9.6 unknown `?tab=` → a toast naming the release, for every id not in TAB_IDS and never for one that is.
 *  G9.7 the live "who moved the index" panel on MOV only among the pages (BRF keeps a one-line summary), the horizon
 *       table (`useDrivers(`) on MEMB only.
 *
 * Pre-existing (pre-v2) breaches of G9.2 are listed in KNOWN_PRE_V2 with the B6 patch request that fixes them: the check
 * fails on any breach NOT in that list (a new one), and passes while the listed ones remain or once they are fixed.
 *
 * Run with plain node ≥ 23.6 (type stripping, no deps):
 *   node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON ui/components/__tests__/terminal_v2.check.ts
 * Also type-checked by `cd ui && npx tsc --noEmit`. Exits non-zero on any failing check.
 */
import * as fs from 'node:fs'
import * as path from 'node:path'

type SourceMod = typeof import('../terminal/source')
type DriversMod = typeof import('../drivers/driversModel')
type DeepMod = typeof import('../../lib/deepLink')
const S = (await import(new URL('../terminal/source.ts', import.meta.url).href)) as SourceMod
const D = (await import(new URL('../drivers/driversModel.ts', import.meta.url).href)) as DriversMod
const DL = (await import(new URL('../../lib/deepLink.ts', import.meta.url).href)) as DeepMod

const UI = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..')
const read = (rel: string): string => fs.readFileSync(path.join(UI, rel), 'utf8')

let failed = 0
let passed = 0
function check(name: string, cond: unknown, extra?: unknown): void {
  if (cond) { passed++; return }
  failed++
  console.error(`FAIL ${name}${extra !== undefined ? ` :: ${JSON.stringify(extra)}` : ''}`)
}

/** Source text with comments blanked (line and block), so prose never counts as rendered UI. */
function code(s: string): string {
  return s.replace(/\/\*[\s\S]*?\*\//g, m => m.replace(/[^\n]/g, ' ')).replace(/(^|[^:'"`])\/\/[^\n]*/g, '$1')
}

/** Every .tsx under ui/app and ui/components (no tests, no node_modules), as repo-relative paths. */
function tsxFiles(): string[] {
  const out: string[] = []
  const walk = (dir: string): void => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      if (e.name === 'node_modules' || e.name === '__tests__' || e.name.startsWith('.')) continue
      const p = path.join(dir, e.name)
      if (e.isDirectory()) walk(p)
      else if (p.endsWith('.tsx')) out.push(path.relative(UI, p))
    }
  }
  walk(path.join(UI, 'app'))
  walk(path.join(UI, 'components'))
  return out.sort()
}

/** The opening `<Panel …>` tags of a source (JSX-aware: `>` inside `{…}` or quotes does not end the tag). */
function panelTags(s: string): { line: number, tag: string }[] {
  const out: { line: number, tag: string }[] = []
  const re = /<Panel(?=[\s>])/g
  let m: RegExpExecArray | null
  while ((m = re.exec(s)) !== null) {
    let i = m.index + 6
    let depth = 0
    let quote: string | null = null
    for (; i < s.length; i++) {
      const c = s[i]
      if (quote) { if (c === quote) quote = null; continue }
      if (depth === 0 && (c === '"' || c === "'")) { quote = c; continue }
      if (c === '{') depth++
      else if (c === '}') depth--
      else if (c === '>' && depth === 0) break
    }
    out.push({ line: s.slice(0, m.index).split('\n').length, tag: s.slice(m.index, i + 1) })
  }
  return out
}

/** The value of a JSX prop in an opening tag: `{…}` (balanced) or a quoted string; null when absent. */
function prop(tag: string, name: string): string | null {
  const m = new RegExp(`\\s${name}=`).exec(tag)
  if (!m) return null
  let i = m.index + m[0].length
  if (tag[i] === '"' || tag[i] === "'") {
    const end = tag.indexOf(tag[i], i + 1)
    return tag.slice(i, end + 1)
  }
  if (tag[i] !== '{') return null
  let depth = 0
  const start = i
  for (; i < tag.length; i++) {
    if (tag[i] === '{') depth++
    else if (tag[i] === '}' && --depth === 0) break
  }
  return tag.slice(start, i + 1)
}

const FILES = tsxFiles()
const SRC = new Map(FILES.map(f => [f, code(read(f))] as const))

// ── G9.1 IV percentile vs IV rank ─────────────────────────────────────────────────────────────────
{
  // a series with one spike: most of the year sits below today (percentile high) while today is near the low end of
  // the min–max range (rank low) — the two numbers the old OMON chip conflated
  const year = [...Array.from({ length: 240 }, (_, i) => 10 + i * 0.01), 40]
  const today = 12.5
  const pct = S.percentileOf(year, today), rank = S.rankOf(year, today)
  check('G9.1 IV percentile and IV rank are both defined and differ on a spiky year', pct != null && rank != null && Math.abs(pct - 99.59) < 0.01 && Math.abs(rank - 8.3) < 0.1, { pct, rank })
  const even = Array.from({ length: 101 }, (_, i) => i)
  check('G9.1 negative control: on an evenly spread year they coincide', Math.abs((S.percentileOf(even, 50) ?? -1) - (S.rankOf(even, 50) ?? -2)) < 1)
  check('G9.1 too short a history: neither is computed', S.percentileOf([1, 2, 3], 2) === null && S.rankOf([1, 2, 3], 2) === null)
  // every view that prints one prints the other, and each carries the route definition as its hover text
  const rankRe = /iv_rank_252|['"`>]\s*IV RANK\b|['"`]IV rank['"`]/
  const pctRe = /iv_pctile_252|IV PCTILE|IV PERCENTILE|['"`]IV pctile['"`]|['"`]IV percentile['"`]/
  const shows = FILES.filter(f => rankRe.test(SRC.get(f) ?? '') || pctRe.test(SRC.get(f) ?? ''))
  const lonely = shows.filter(f => !(rankRe.test(SRC.get(f) ?? '') && pctRe.test(SRC.get(f) ?? '')))
  check('G9.1 every view that prints IV rank also prints IV percentile (and vice versa)', shows.length >= 3 && lonely.length === 0, { shows, lonely })
  const undefinedDefs = shows.filter(f => {
    const s = SRC.get(f) ?? ''
    const usesRank = /iv_rank_252/.test(s)
    const usesPct = /iv_pctile_252/.test(s)
    return (usesRank && !/definitions\??\.iv_rank_252/.test(s)) || (usesPct && !/definitions\??\.iv_pctile_252/.test(s))
  }).filter(f => !f.endsWith('OptionChain.tsx'))            // OMON sorts the screener by iv_pctile; its chips live in IvHistoryChart
  check('G9.1 each printed rank / percentile carries its route definition on hover', undefinedDefs.length === 0, undefinedDefs)
  const contract = fs.readFileSync(path.join(UI, '..', 'reports', 'terminal_v2', 'API_CONTRACT.md'), 'utf8')
  check('G9.1 the API contract defines both fields', /iv_rank_252/.test(contract) && /iv_pctile_252/.test(contract))
  check('G9.1 negative control: the pairing rule flags a view printing only a rank', rankRe.test("label: 'IV rank'") && !pctRe.test("label: 'IV rank'"))
}

// ── G9.2 context is never coloured by direction ───────────────────────────────────────────────────
// Pre-v2 breaches (B6 patch requests: the two regime panels and the two VIX levels go neutral; the fixed green / red
// category accents are listed for B4's review). Keys: `file:context-panel-title-or-label`.
const KNOWN_PRE_V2 = new Set([
  'components/MarketMonitor.tsx:Market regime',             // accent={SCORE_COLOR[s]} (patch request)
  'components/Brief.tsx:regime',                            // accent={m ? SCORE_COLOR[m.regime.score] : T.amber} (patch request)
  'components/MarketMonitor.tsx:VIX',                       // India VIX Stat accent green < 80th pctile else red (patch request)
  'components/Brief.tsx:VIX',                               // India VIX line red ≥ 80th pctile (patch request)
  'components/Compare.tsx:green',                           // fixed category accents on context panels (B4 review)
  'components/DealsMonitor.tsx:red',
  'components/EventCalendar.tsx:green',
  'components/InsiderMonitor.tsx:green',
  'components/MarginMonitor.tsx:red',
])
function contextBreaches(file: string, s: string): string[] {
  const out: string[] = []
  for (const { tag } of panelTags(s)) {
    const badge = prop(tag, 'badge')
    if (!badge || !/['"]context['"]/.test(badge)) continue
    const accent = prop(tag, 'accent') ?? ''
    const title = (prop(tag, 'title') ?? '').replace(/^["'{]+|["'}]+$/g, '')
    if (/[?[]/.test(accent)) out.push(`${file}:${/regime/i.test(title) || /regime/.test(accent) ? (title.includes('Market regime') ? 'Market regime' : 'regime') : title}`)
    else if (/\bT\.(green|red)\b/.test(accent)) out.push(`${file}:${/T\.green/.test(accent) ? 'green' : 'red'}`)
  }
  // a VIX level is context: never green / red, whatever its percentile
  const vixLine = /(?:label|k)=["'](?:India |INDIA )?VIX["'][^\n]*\b(?:accent|c|color)=\{[^}\n]*\bT\.(?:green|red)\b/g
  if (vixLine.test(s)) out.push(`${file}:VIX`)
  return out
}
{
  const breaches = FILES.flatMap(f => contextBreaches(f, SRC.get(f) ?? ''))
  const unknown = breaches.filter(b => !KNOWN_PRE_V2.has(b))
  check('G9.2 context panels: no new data-dependent or green / red accent, no green / red VIX level', unknown.length === 0, unknown)
  const v2 = breaches.filter(b => /components\/(vol|drivers|datahealth)\//.test(b))
  check('G9.2 the v2 views carry no breach at all (no exemption applies to them)', v2.length === 0, v2)
  const neg = contextBreaches('x.tsx', `<Panel title="Breadth" badge="context" accent={b > 0 ? T.green : T.red} source={s}>
    <Stat label="India VIX" value={v} accent={(p ?? 0) < 80 ? T.green : T.red} />`)
  check('G9.2 negative control: a value-coloured context panel and a red/green VIX are both caught', neg.length === 2, neg)
  check('G9.2 negative control: a fixed category accent on a context panel passes', contextBreaches('x.tsx', '<Panel title="x" badge="context" accent={T.cyan} source={s}>').length === 0)
  check('G9.2 the context badge itself is the muted tone', S.BADGES.context.tone === 'muted')
}

// ── G9.3 the regime strip suffix ──────────────────────────────────────────────────────────────────
{
  const route = ['HDFCBANK led NIFTY over 20 sessions', 'leaders rotated.', 'breadth narrow ', `already ends — ${S.DESCRIBES}`]
  const lines = route.map(sentence => D.regimeLine({ leader: 'HDFCBANK', sentence }, null, null, null))
  check('G9.3 the regime strip ends "describes, does not predict" for any route sentence, once', lines.every(l => l != null && l.endsWith(S.DESCRIBES) && l.split(S.DESCRIBES).length === 2), lines)
  check('G9.3 negative control: a raw route sentence does not end that way', !route[0].endsWith(S.DESCRIBES))
  const dv = SRC.get('components/drivers/DriversView.tsx') ?? ''
  check('G9.3 the strip renders regimeLine / describes, never a raw sentence', /data-driver-regime/.test(dv) && /regimeLine\(/.test(dv))
}

// ── G9.4 every Panel carries its SourceChip ───────────────────────────────────────────────────────
{
  const offenders: string[] = []
  let total = 0
  for (const f of FILES) {
    if (f === path.join('components', 'terminal', 'index.tsx')) continue          // the kit's own definition
    for (const { line, tag } of panelTags(SRC.get(f) ?? '')) {
      total++
      if (prop(tag, 'source') === null && !/\{\.\.\.[^}]*\}/.test(tag)) offenders.push(`${f}:${line}`)
    }
  }
  // the gold kit wraps the kit Panel and renders the gold catalog's own lag chip (gold PLAN §f)
  const goldKit = SRC.get(path.join('components', 'gold', 'kit.tsx')) ?? ''
  const realOffenders = offenders.filter(o => !(o.startsWith(path.join('components', 'gold', 'kit.tsx')) && /<LagChipEl freshness=\{freshness\}/.test(goldKit)))
  check('G9.4 every <Panel on every page carries source= (its SourceChip)', total >= 120 && realOffenders.length === 0, { total, realOffenders })
  check('G9.4 negative control: the scanner flags a bare Panel and not one with source=',
    panelTags('<Panel title="a" right={<b>{x > 1 ? 1 : 2}</b>}>b</Panel>').filter(t => prop(t.tag, 'source') === null).length === 1
    && panelTags('<Panel title="a" source={sourceOf(d)}>b</Panel>').filter(t => prop(t.tag, 'source') === null).length === 0)
  check('G9.4 the kit renders the chip from the prop', /\{source && <SourceChip info=\{source\} \/>\}/.test(read('components/terminal/index.tsx')))
}

// ── G9.5 the VIX level once per page ──────────────────────────────────────────────────────────────
/** Page component files (page.tsx lazyTab ids → the component's file) and the local files each renders directly. */
function pageFiles(): Map<string, string[]> {
  const page = read('app/page.tsx')
  const out = new Map<string, string[]>()
  const comps = [...page.matchAll(/lazyTab\('([^']+)', m => m\.(\w+)\)/g)].map(m => [m[1], m[2]] as const)
  // the landing page is imported eagerly: `case 'brief': return <Brief …`
  for (const m of page.matchAll(/case '([a-z]+)': return <(\w+)\b/g)) if (!comps.some(([id]) => id === m[1])) comps.push([m[1], m[2]] as const)
  for (const [id, comp] of comps) {
    const file = FILES.find(f => new RegExp(`export (?:default )?(?:function|const) ${comp}\\b`).test(read(f)))
    if (!file) continue
    const deps = [...(SRC.get(file) ?? '').matchAll(/from '(?:@\/components\/|\.\/)((?:vol|drivers|datahealth)\/\w+|\w+)'/g)]
      .map(m => path.join('components', `${m[1]}.tsx`)).filter(p => FILES.includes(p) && !p.includes(`${path.sep}terminal`))
    out.set(id, [file, ...deps])
  }
  return out
}
function vixLevels(s: string): number {
  return (s.match(/\b(?:label|k)=["'](?:India |INDIA )?VIX["']/g) ?? []).length
}
{
  const pages = pageFiles()
  const over: Record<string, number> = {}
  for (const [id, files] of pages) {
    const n = files.reduce((a, f) => a + vixLevels(SRC.get(f) ?? ''), 0)
    if (n > 1) over[id] = n
  }
  check('G9.5 the page map resolves every page incl. the eager BRF', pages.size === 44 && pages.has('brief'), [...pages.keys()].length)
  check('G9.5 the VIX level once per page', Object.keys(over).length === 0, over)
  const count = (id: string): number => (pages.get(id) ?? []).reduce((a, f) => a + vixLevels(SRC.get(f) ?? ''), 0)
  check('G9.5 DERV, MKT and BRF each show it once, so the rule is not vacuous', count('derivatives') === 1 && count('markets') === 1 && count('brief') === 1,
    { derv: count('derivatives'), mkt: count('markets'), brf: count('brief') })
  check('G9.5 negative control: two VIX level displays on one page are counted', vixLevels('<Stat label="INDIA VIX" value={a} /> <Line k="India VIX" v={b} />') === 2
    && vixLevels("{ label: 'India VIX', color: T.green, values: vix }") === 0)
}

// ── G9.6 unknown ?tab= → a toast ─────────────────────────────────────────────────────────────────
{
  const page = read('app/page.tsx')
  const tabBlock = /const TAB_IDS: Tab\[\] = \[([\s\S]*?)\]/.exec(page)?.[1] ?? ''
  const tabs = [...tabBlock.matchAll(/'([^']+)'/g)].map(m => m[1])
  check('G9.6 TAB_IDS parsed (44 pages)', tabs.length === 44, tabs.length)
  check('G9.6 unknown ?tab= names the page and the release for any id not in TAB_IDS',
    tabs.every(t => DL.unknownTab(`?tab=${t}`, tabs) === null) && DL.unknownTab('?tab=vol', tabs) === 'vol' && DL.unknownTab('?tab=data', tabs) === 'data')
  check('G9.6 the toast text names the release date', DL.unknownTabText('vol', '20261105-041017-abc1234') === 'VOL is not in this release (built 05 Nov) — showing BRF')
  check('G9.6 negative control: a page removed from TAB_IDS would be toasted', DL.unknownTab('?tab=gold', tabs.filter(t => t !== 'gold')) === 'gold')
  check('G9.6 the toast is mounted on the page', /<UnknownTabToast tabs=\{TAB_IDS\} \/>/.test(code(page)))
}

// ── G9.7 one live today panel, one horizon table ──────────────────────────────────────────────────
{
  const pages = pageFiles()
  const hosts = (re: RegExp): string[] => [...pages].filter(([, files]) => files.some(f => re.test(SRC.get(f) ?? ''))).map(([id]) => id).sort()
  check('G9.7 the live today panel (<IndexContribution) on MOV only among the pages', JSON.stringify(hosts(/<IndexContribution\b/)) === '["movers"]', hosts(/<IndexContribution\b/))
  check('G9.7 the horizon table (useDrivers) on MEMB only', JSON.stringify(hosts(/\buseDrivers\(/)) === '["memb"]', hosts(/\buseDrivers\(/))
  check('G9.7 negative control: the host finder sees a page that renders it', hosts(/<Panel\b/).length > 30)
}

console.log(`terminal_v2 (G9 gate) check: ${passed} passed, ${failed} failed`)
if (failed) process.exit(1)

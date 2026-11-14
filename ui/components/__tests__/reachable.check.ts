/**
 * Every page-level component is REACHABLE from the terminal (F6-04, 14 Nov 2026).
 *
 * Why this gate exists: wave 5 shipped `commodity/CommodityDesk.tsx` — 387 lines, a working API behind it, its
 * own tests — and it was imported by NOTHING. CMDT rendered the old tab, so the feature could not be opened by
 * anyone, and it was reported as live. No gate caught it, because an unmounted component type-checks, lints and
 * unit-tests perfectly. The F5 critic found it by reading the network log of a live page.
 *
 * So this closes the CLASS rather than that one instance: a component that declares itself a page/desk/view and
 * is referenced by no other source file fails here. It is deliberately conservative — it only looks at the
 * populations where "unreachable" means "a user cannot get to it", and it carries an explicit allowlist so a
 * deliberate stand-alone (a template, a story, a deprecated shim kept for one release) is a decision on the
 * record instead of a silent orphan.
 *
 * Run: node --experimental-strip-types ui/components/__tests__/reachable.check.ts
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'

const UI = resolve(import.meta.dirname, '..', '..')
const COMPONENTS = join(UI, 'components')

/** Components intentionally not mounted anywhere, each with the reason it stays. Shrink this list, never grow it
 *  without a reason a reviewer would accept. */
const ALLOWED_ORPHANS: Record<string, string> = {
  'TradeExplorer.tsx': 'pre-terminal-kit trade journal (601 lines); BACKLOG F-12 decides whether to adopt or delete it',
  'DataPipeline.tsx': 'pre-terminal-kit pipeline view (228 lines, gradient/emoji styling); kept until the kit port or deletion',
  'KPICard.tsx': 'superseded by QuantKPICard; kept one release for any stale import',
  'IvLivePath.tsx': 'retired by wave B (expiry/OiTape supersedes it) but KEPT ON PURPOSE: live.check.ts and tests/integration/test_live_gates.py read its source as the fixture for the quiet-LIVE lesson it taught',
}

const SKIP_DIRS = new Set(['__tests__', 'node_modules', 'dist'])

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) {
      if (!SKIP_DIRS.has(name)) walk(p, out)
    } else if (name.endsWith('.tsx')) {
      out.push(p)
    }
  }
  return out
}

/** Every source file that could reference a component (the app shell, libs and the components themselves). */
const sources = [
  ...walk(COMPONENTS),
  ...['app', 'lib'].flatMap(d => {
    const root = join(UI, d)
    const acc: string[] = []
    const rec = (dir: string) => {
      for (const name of readdirSync(dir)) {
        const p = join(dir, name)
        if (statSync(p).isDirectory()) { if (!SKIP_DIRS.has(name)) rec(p) } else if (/\.(tsx?|mts)$/.test(name)) acc.push(p)
      }
    }
    rec(root)
    return acc
  }),
]
const text = new Map(sources.map(f => [f, readFileSync(f, 'utf8')]))

let passed = 0
let failed = 0
const check = (name: string, ok: boolean, detail?: unknown) => {
  if (ok) { passed++ } else { failed++; console.log(`FAIL ${name}${detail === undefined ? '' : ` :: ${JSON.stringify(detail)}`}`) }
}

/** A component "declares itself a surface" when it exports a component whose name the shell would mount. */
const orphans: string[] = []
for (const file of walk(COMPONENTS)) {
  const base = file.split('/').pop()!
  const src = text.get(file)!
  const exported = [...src.matchAll(/export\s+(?:default\s+)?function\s+([A-Z]\w+)/g)].map(m => m[1])
  if (exported.length === 0) continue                        // no component export: a helper module, not a surface
  // referenced by any OTHER file, by import path or by JSX usage of one of its exports
  const stem = base.replace(/\.tsx$/, '')
  const referenced = sources.some(other => {
    if (other === file) return false
    const s = text.get(other)!
    if (s.includes(`/${stem}'`) || s.includes(`/${stem}"`) || s.includes(`./${stem}`)) return true
    return exported.some(name => new RegExp(`<${name}[\\s/>]|\\b${name}\\s*[,}]`).test(s))
  })
  if (!referenced) orphans.push(base)
}

const unexpected = orphans.filter(o => !(o in ALLOWED_ORPHANS))
check('every page-level component is reachable from the shell (or allowlisted with a reason)',
  unexpected.length === 0, unexpected)

// the allowlist may not rot: an entry that became reachable must be removed from it
const stale = Object.keys(ALLOWED_ORPHANS).filter(a => !orphans.includes(a))
check('the orphan allowlist carries no entry that is now mounted', stale.length === 0, stale)

// the two desks F5 found dead must stay mounted, by name — the regression that started this gate
const tab = text.get(join(COMPONENTS, 'CommodityTab.tsx')) ?? ''
check('CMDT mounts both commodity desks', /<CommodityDesk\s+group="SILVER"/.test(tab) && /<CommodityDesk\s+group="CRUDE"/.test(tab))
const mcxg = text.get(join(COMPONENTS, 'McxGoldDesk.tsx')) ?? ''
check('MCXG mounts the paper futures book', /<FutBook\b/.test(mcxg))

// negative control: the detector must be able to see a reference at all
check('negative control: a known-mounted component is seen as referenced',
  sources.some(f => f !== join(COMPONENTS, 'commodity', 'CommodityDesk.tsx') && (text.get(f) ?? '').includes('CommodityDesk')))

console.log(`reachable.check: ${passed} passed, ${failed} failed`)
if (failed > 0) process.exit(1)

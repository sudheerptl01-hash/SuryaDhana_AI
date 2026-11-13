/**
 * R2-TYPE checks (FINAL ROUND round 2, 13 Nov 2026): O-F2 type-scale adoption + the named F-DESIGN /
 * F-PROBE holds this builder closed.
 *
 *  - Type ramp: the --t-fs-* tokens name the terminal's REAL whole-pixel ramp (9/10/11/12/13/15/18) and the
 *    half-pixel micro-steps (8.5/9.5/10.5/11.5/12.5) are gone from every component, lib and app file —
 *    F-DESIGN defect 2 ("six distinct sub-12 px sizes... read as drift").
 *  - Adoption: the terminal kit's DOM text styles reference the tokens instead of loose numbers, so every
 *    page that builds on the kit inherits the scale.
 *  - Chip truncation (F-DESIGN defect 4): the Panel header wraps instead of clipping its chips; the gold
 *    chipSource() drops the parenthetical and trims word-by-word (no more "YAHOO (CACHED FET…").
 *  - MOV 52-week highs/lows counts are neutral (the one L-15 residue, F-DESIGN defect 1).
 *  - ALRT (F-PROBE smalls): ＋ADD RULE failure renders an inline validation message; the legacy price-alert
 *    list renders only while the typed engine is down, so a level never prints in two tables.
 *
 * Run with plain node 25 (type stripping, no deps):
 *   node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON ui/components/__tests__/type_scale.check.ts
 * Also type-checked by `cd ui && npx tsc --noEmit`. Exits non-zero on any failing check.
 */
import * as fs from 'node:fs'
import * as path from 'node:path'

const UI = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..')
const src = (rel: string) => fs.readFileSync(path.join(UI, rel), 'utf8')

let failed = 0
let passed = 0
function check(name: string, cond: unknown, extra?: unknown): void {
  if (cond) { passed++; return }
  failed++
  console.error(`FAIL ${name}${extra !== undefined ? ` :: ${JSON.stringify(extra)}` : ''}`)
}

// ── tokens: the real ramp, defined once and driving the page base ────────────────────────────────────────
{
  const css = src('app/globals.css')
  for (const [name, px] of [['nano', 9], ['micro', 10], ['data', 11], ['body', 12], ['base', 13], ['lead', 15], ['title', 18]] as const)
    check(`token --t-fs-${name}: ${px}px declared`, css.includes(`--t-fs-${name}: ${px}px;`))
  check('body adopts the base token', /font-size: var\(--t-fs-base\);/.test(css))
  check('globals.css has no loose numeric font-size left (tokens only)', !/font-size: \d/.test(css))
}

// ── half-pixel ramp is dead terminal-wide (numeric sweep, compact.css excluded — another owner) ──────────
{
  const offenders: string[] = []
  // compact.css is C-PHONE's; the other two are files OTHER R2 builders were writing while this sweep ran
  // (13 Nov 2026, untracked in git at sweep time) — theirs to align, not this builder's to touch.
  // PM: remove these two entries at integration once their waves land on the whole-pixel ramp.
  const SKIP = new Set([
    path.join('app', 'compact.css'),
    // R2-CHECK (13 Nov): AskPanel.tsx and IntradayDrivers.tsx were aligned to the whole-pixel ramp at
    // integration (the dated SKIP entries for the two in-flight files are gone — the gate now covers them).
  ])
  const halfPx = /fontSize: \d+\.5\b|fontSize=\{\d+\.5\}|text-\[\d+\.5px\]|font-size: \d+\.5px/
  const walk = (dir: string): void => {
    for (const e of fs.readdirSync(path.join(UI, dir), { withFileTypes: true })) {
      if (e.isDirectory()) {
        if (['node_modules', 'dist', '.next'].includes(e.name)) continue
        walk(path.join(dir, e.name))
      } else if (/\.(tsx?|css)$/.test(e.name) && !SKIP.has(path.join(dir, e.name))) {
        if (halfPx.test(src(path.join(dir, e.name)))) offenders.push(path.join(dir, e.name))
      }
    }
  }
  for (const d of ['components', 'lib', 'app']) walk(d)
  check('no half-pixel font size anywhere in components/lib/app', offenders.length === 0, offenders.slice(0, 8))
}

// ── the kit adopts the tokens (DOM styles only; chart-library configs keep numbers elsewhere) ────────────
{
  const kit = src('components/terminal/index.tsx')
  for (const t of ['nano', 'micro', 'data', 'body'])
    check(`kit references var(--t-fs-${t})`, kit.includes(`var(--t-fs-${t})`))
  // the micro-ramp numbers are gone from the kit's text styles (large display numbers 16/20/22 may stay)
  check('kit has no loose 9–13 px fontSize left', !/fontSize: (9|10|11|12|13)[,\s}]/.test(kit))
  check('Panel header wraps its chips instead of clipping them', /<header style=\{\{ display: 'flex', alignItems: 'center', flexWrap: 'wrap'/.test(kit))
  check('SourceChip never shrinks mid-text', /whiteSpace: 'nowrap', flex: 'none', \.\.\.style \}\}>/.test(kit))
}

// ── gold chip truncation (lib/gold/format.ts chipSource) ─────────────────────────────────────────────────
{
  const f = src('lib/gold/format.ts')
  const fn = f.slice(f.indexOf('function chipSource'), f.indexOf('export function lagChip'))
  check('gold chipSource drops the parenthetical (hover keeps it whole)', fn.includes('replace(/\\s*\\(.*$/'))
  check('gold chipSource trims word-by-word before the ellipsis', /words\.pop\(\)/.test(fn))
}

// ── MOV 52-week highs/lows: the last L-15 residue is neutral ─────────────────────────────────────────────
{
  const mov = src('components/LiveMovers.tsx')
  check('MOV 52-wk counts are one neutral span', /label="52-week highs \/ lows" value=\{<span style=\{\{ color: T\.text \}\}>\{data\.highs\.count\} \/ \{data\.lows\.count\}<\/span>\}/.test(mov))
  check('MOV negative control: no green/red on the 52-wk counts', !/52-week highs \/ lows" value=\{<span><span style=\{\{ color: T\.green/.test(mov))
}

// ── ALRT: inline validation + one list for the legacy levels ─────────────────────────────────────────────
{
  const a = src('components/AlertsCenter.tsx')
  check('ADD RULE failure sets an inline problem, not only the strip message', /if \(!draft\) \{ setRuleProblem\(problem \|\| 'check the fields above'\); return \}/.test(a))
  check('the problem renders beside the button as role=alert', /\{ruleProblem && <span role="alert"/.test(a))
  check('a successful save clears the problem', /setRuleProblem\(null\)/.test(a))
  check('legacy price table renders only while the typed engine is down', /\{engineDown && <div style=\{SCROLL_X\}>\s*\n?\s*<DataTable columns=\{cols\}/.test(a))
  check('negative control: the legacy table renders exactly once (inside the guard)', (a.match(/<DataTable columns=\{cols\}/g) ?? []).length === 1)
}

// ── R3-NITS (FINAL ROUND round 3): the F2 visual/honesty nits, each measured before the fix ──────────────
{
  // F2-DESIGN: the ONE half-px leaf left in 15 pages was OMON's settlement <sup>s</sup> — the UA styles sup as
  // font-size 'smaller', which computes 8.25px inside the 11px chain table. It is pinned to the 9px nano step.
  const omon = src('components/OptionChain.tsx')
  check("OMON settlement sup pinned to the nano token (no UA 'smaller' leaf)",
    /<sup style=\{\{ fontSize: 'var\(--t-fs-nano\)' \}\}>s<\/sup>/.test(omon))
  check('negative control: no unstyled <sup>s element left in OMON', !/<sup>s/.test(omon))
  // the F1 trader's volume/OI unit-chip ask: the per-column "(ctr)" / "(sh)" suffixes already state the unit per
  // column — recorded in place, not duplicated with a third chip
  check('OMON unit-chip decision recorded at the chain header', omon.includes('recorded as already satisfied, not duplicated'))

  // F2-DESIGN: the GOLD gauge-delta sub ("$103.89 ▲+$96.79/oz vs the median of the previous 5 pairs") clipped 18px
  // at 315px — Stat gains an opt-in wrap and the HEALTH gauges use it
  const kit = src('components/terminal/index.tsx')
  check('Stat implements wrap (normal whitespace, no ellipsis)', /wrap \? \{ whiteSpace: 'normal' as const, overflowWrap: 'anywhere' as const/.test(kit))
  check('HEALTH gauges pass wrap', /<Stat big=\{false\} wrap label=/.test(src('components/gold/HealthView.tsx')))

  // F2-DESIGN UI ask: hover tooltip on ellipsis-truncated DataTable cells — measured per cell (scrollWidth vs
  // clientWidth + text-overflow ellipsis) on hover, never a blanket title on every cell
  check('DataTable sets a measured title on truncated cells only',
    /el\.scrollWidth <= el\.clientWidth \+ 1/.test(kit) && /getComputedStyle\(el\)\.textOverflow !== 'ellipsis'/.test(kit)
    && /onMouseOver=\{onOverCell\}/.test(kit))
  check('an element with its own title is never overwritten', /if \(el\.title \|\| el\.scrollWidth/.test(kit))

  // F2-TRADER: "GO IMPORT has still never been run" — the WTCH empty state offers the one-time settings import
  const wtch = src('components/WatchMonitor.tsx')
  check('WTCH empty state links the settings import (GO IMPORT)', /data-wtch-import onClick=\{\(\) => openSettingsImport\(\)\}/.test(wtch))
  check('…with the RUNBOOK §8 one-liner', wtch.includes('RUNBOOK §8 one-liner: open http://localhost:3000 once in the browser you used before'))
  check('…keeping the original empty-state sentence (zero copy drift)',
    wtch.includes('Nothing to watch yet: add a ticker above, ☆ PIN a stock from any chart, or connect ICICI to see your holdings.'))
}

console.log(`type_scale.check: ${passed} passed, ${failed} failed`)
if (failed) process.exit(1)

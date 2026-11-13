/**
 * R4-UI checks (FINAL ROUND round 4, 14 Nov 2026): F3-DESIGN §1.3 — BRF news-pick / headline rows get the
 * measured-title tooltip.
 *
 *  - F3-design live-hovered 6 truncated news-scanner pick titles on BRF (desktop + phone): title=null on all,
 *    because they are plain spans, not .t-table cells, so R3's delegated DataTable handler misses them.
 *  - Fix: Brief.tsx carries the same measured rule on the rows themselves (titleWhenClipped) — a title with
 *    the full text ONLY when the text is actually clipped (text-overflow ellipsis AND scrollWidth beyond
 *    clientWidth), never overwriting an existing title, nothing on a span that fits. Zero copy changes.
 *
 * Run with plain node 25 (type stripping, no deps):
 *   node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON ui/components/__tests__/brief_tooltip.check.ts
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

const brief = src('components/Brief.tsx')

// ── the handler itself: measured, non-overwriting, ellipsis-gated ─────────────────────────────────────────
{
  check('Brief.tsx declares titleWhenClipped', brief.includes('const titleWhenClipped = (e: ReactMouseEvent<HTMLElement>)'))
  check('handler never overwrites an existing title and skips unclipped text',
    brief.includes('if (el.title || el.scrollWidth <= el.clientWidth + 1) return'))
  check('handler only fires on an ellipsis element (same gate as the kit\'s onOverCell)',
    brief.includes("if (getComputedStyle(el).textOverflow !== 'ellipsis') return"))
  check('handler sets the full text as the title', /const full = \(el\.innerText \|\| ''\)\.trim\(\)\s*\n\s*if \(full\) el\.title = full/.test(brief))
  check('React MouseEvent type imported', brief.includes('type MouseEvent as ReactMouseEvent'))
}

// ── the named rows carry it ───────────────────────────────────────────────────────────────────────────────
{
  // news-scanner pick rows: the catalyst_category span is the one F3 measured truncated (maxWidth 250, ellipsis)
  check('news-pick catalyst span is wired', /onMouseOver=\{titleWhenClipped\}[^>]*>\{p\.catalyst_category\}/.test(brief))
  // headline rows (named alongside picks): measured rule attached — a wrapped headline sets no title (gate)
  check('headline title span is wired', /onMouseOver=\{titleWhenClipped\}[^>]*>\{h\.title\}/.test(brief))
  // the insider-categories span is the identical ellipsis pattern on the same page (maxWidth 220)
  check('insider categories span is wired', /onMouseOver=\{titleWhenClipped\}[^>]*>\{r\.categories\}/.test(brief))
  // every statically-ellipsised span in Brief.tsx is covered (measured handler or an explicit title)
  const lines = brief.split('\n').filter(l => l.includes("textOverflow: 'ellipsis'"))
  const uncovered = lines.filter(l => !l.includes('onMouseOver={titleWhenClipped}') && !l.includes('title='))
  check('no ellipsis span in Brief.tsx is left without a tooltip path', uncovered.length === 0, uncovered.slice(0, 4))
}

// ── negative controls ─────────────────────────────────────────────────────────────────────────────────────
{
  // zero copy changes: the handler adds no user-visible string (titles come from the row's own text)
  const handler = brief.slice(brief.indexOf('const titleWhenClipped'), brief.indexOf('}', brief.indexOf('if (full) el.title = full')) + 1)
  check('handler introduces no literal copy', !/['"`][A-Z][a-z]+ /.test(handler))
  // the kit's delegated .t-table handler is untouched (R3-NITS's, not this builder's)
  const kit = src('components/terminal/index.tsx')
  check('kit onOverCell untouched', kit.includes('const onOverCell = (e: MouseEvent<HTMLDivElement>) => {')
    && kit.includes('if (el.title || el.scrollWidth <= el.clientWidth + 1) continue'))
}

console.log(`brief_tooltip.check: ${passed} passed, ${failed} failed`)
if (failed > 0) process.exit(1)

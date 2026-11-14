/**
 * SYS › DATA, the Crashes column — the two meanings it exists to separate.
 *
 * The column answers "did the job that produces this dataset crash?", and it has three distinct answers that
 * must never be confusable:
 *
 *   a number > 0  — it crashed this many times in the counted window
 *   0             — it ran and did not crash
 *   —             — this store has never seen that job, so there is nothing to count
 *
 * R15-E: `0` and `—` were both rendered at `T.dim`, and `{r.job_failures || '·'}` turned the clean zero into
 * a middot — so "ran clean" and "never seen" were the same glyph in the same colour, on the one page whose
 * whole purpose is telling the owner which of those is true.
 *
 * Source-level, because the page's correctness here is about which branch renders what, not about layout.
 */
import { readFileSync } from 'node:fs'

let passed = 0
let failed = 0
const check = (name: string, ok: boolean, detail?: unknown) => {
  if (ok) { passed++ } else { failed++; console.log(`FAIL ${name}${detail === undefined ? '' : ` :: ${JSON.stringify(detail)}`}`) }
}

const src = readFileSync(new URL('../DataHealthView.tsx', import.meta.url), 'utf8')
// comments stripped before any claim about behaviour: three gates in this repo were fooled by their own prose
const code = src.replace(/\{\/\*[\s\S]*?\*\/\}/g, '').replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '')

const col = code.slice(code.indexOf("key: 'fails'"), code.indexOf("key: 'note'"))
check('the Crashes column exists', col.length > 50, col.length)

// the three branches, each distinguishable
check('null renders an em dash', col.includes('—'))
check('a clean run renders a literal 0, not a middot', />\{?\s*0\s*\}?</.test(col) || col.includes('>0<'), col.slice(0, 400))
check('the old `|| ·` collapse is gone', !col.includes("|| '·'"))
check('a crash count is amber', col.includes('T.amber'))
check('clean-zero and never-seen do NOT share a colour',
  !(col.match(/T\.dim/g) ?? []).length || (col.includes('T.muted') && col.includes('T.dim')))

// and each of the two quiet states explains itself, because a dash with no hover is a shrug
check('the dash says why there is nothing to count', /—<\/span>/.test(col) && col.includes('title='))
check('the zero says what window it speaks for', col.includes('counted window'))

// the page must also state the window the counts cover — a 0 over a period the store never held is a claim
check('the subtitle dates the counting', code.includes('crash counting began'))
check('…from the payload, never from the clock', !/crash counting began[\s\S]{0,80}new Date/.test(code))

console.log(`crashesColumn.check: ${passed} passed, ${failed} failed`)
if (failed > 0) process.exit(1)

/**
 * BRKR › Broker budget panel — the contract, enforced on the source.
 *
 * The panel exists because the chip's hover promised "the BRKR page shows which caller spent the quota" and
 * the page showed nothing of the kind. What matters about it is as much what it must NOT do as what it shows:
 * it reads a credential-adjacent area of the API and must never reach the one endpoint whose payload embeds
 * the API key.
 *
 * Source-level rather than render-level because the page it lives on shows real balances and must never be
 * opened or screenshotted by a test.
 */
import { readFileSync } from 'node:fs'

let passed = 0
let failed = 0
const check = (name: string, ok: boolean, detail?: unknown) => {
  if (ok) { passed++ } else { failed++; console.log(`FAIL ${name}${detail === undefined ? '' : ` :: ${JSON.stringify(detail)}`}`) }
}

const panel = readFileSync(new URL('../BudgetPanel.tsx', import.meta.url), 'utf8')
const host = readFileSync(new URL('../../PortfolioSummary.tsx', import.meta.url), 'utf8')
// comments stripped before any claim about what the CODE does — a comment naming an endpoint must not pass
// for a call to it (the mistake three separate gates in this repo made before)
const code = panel.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '')

// ── what it must never touch ────────────────────────────────────────────────────────────────────────────
check('never reads connection-status (its payload embeds the API key in login_url)',
  !code.includes('connection-status'))
check('reads only the credential-free budget endpoint',
  (code.match(/fetch\(/g) ?? []).length === 1 && code.includes('/api/positions/breeze-budget'))
check('no secret-shaped field is referenced', !/login_url|api_key|session_token|secret/i.test(code))

// ── what it must show, because each one is a distinct fact the owner needs ───────────────────────────────
for (const field of ['by_caller', 'quotas', 'remaining_day', 'refused_today', 'errors_today']) {
  check(`renders ${field}`, code.includes(field), field)
}
check('refusals and failures are described as different things',
  /refused/i.test(panel) && /failed/i.test(panel))

// ── the judgement calls, which are the easy ones to get wrong ────────────────────────────────────────────
check('amber is reserved for a caller over ITS OWN quota, not merely a busy one',
  code.includes('n > q'))
check('the last call’s ok is compared truthily, not === false (the API may send 0/1)',
  !code.includes('ok === false'))
check('a failed fetch degrades to a message, never to a false zero',
  code.includes('setErr(true)') && /Broker budget unavailable/.test(panel))

// ── and it must be reachable in the state that matters most ──────────────────────────────────────────────
const hostCode = host.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
check('mounted TWICE on BRKR — a day with no session is when the budget matters most',
  (hostCode.match(/<BudgetPanel\s*\/>/g) ?? []).length === 2,
  (hostCode.match(/<BudgetPanel\s*\/>/g) ?? []).length)
check('every mount carries a SourceChip (the G9.4 convention)',
  (hostCode.match(/title="Broker budget"[\s\S]{0,220}?source=/g) ?? []).length === 2)

console.log(`budgetPanel.check: ${passed} passed, ${failed} failed`)
if (failed > 0) process.exit(1)

/**
 * MCXG paper futures book checks (FINAL ROUND R5-FUTBOOK) — labelling and the ticket contract, each with its rule:
 *
 *  FB-01  the MCXG ticket's quote path KEEPS "records nothing" (PLAN 0.1 #7 unchanged) — booking is the separate,
 *         explicit FutBook action, mounted in the desk after the ticket panel.
 *  FB-02  FutBook carries the binding labels: PAPER, badge arithmetic, "describes, does not predict", and the mark's
 *         settlement source words (VWAP / band midpoint) — and no composite score.
 *  FB-03  no direction words colour the book (bullish/bearish/upside/downside/target) — P&L red/green is the
 *         position's own arithmetic, allowed; a market view is not.
 *  FB-04  the component talks to /api/mcx/book only — no order-API word exists in it.
 *
 * Run with plain node 25 (type stripping, no deps):
 *   node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON ui/components/__tests__/futbook.check.ts
 * Also type-checked by `cd ui && npx tsc --noEmit`. Exits non-zero on any failing check.
 */
import * as fs from 'node:fs'
import * as path from 'node:path'

const here = path.dirname(new URL(import.meta.url).pathname)
const comp = path.resolve(here, '..')
const read = (rel: string) => fs.readFileSync(path.join(comp, rel), 'utf8')

let failures = 0
const check = (name: string, ok: boolean, why?: string) => {
  if (!ok) { failures += 1; console.error(`FAIL  ${name}${why ? ` — ${why}` : ''}`) }
  else console.log(`ok    ${name}`)
}

const desk = read('McxGoldDesk.tsx')
const futbook = read('mcxg/FutBook.tsx')

// FB-01 — the ticket still records nothing; the book is the explicit action mounted after it
check('FB-01 ticket keeps "records nothing"', (desk.match(/records nothing/g) ?? []).length >= 3)
check('FB-01 FutBook is mounted in the desk', desk.includes("from '@/components/mcxg/FutBook'") && desk.includes('<FutBook'))
check('FB-01 the mount sits after the ticket panel', desk.indexOf('<FutBook') > desk.indexOf('Paper gold ticket'))
check('FB-01 the book itself restates the ticket contract', futbook.includes('records nothing'))

// FB-02 — binding labels
check('FB-02 PAPER label', futbook.includes('PAPER ONLY') && futbook.includes('>PAPER<'))
check('FB-02 badge arithmetic', futbook.includes('badge="arithmetic"'))
check('FB-02 describes, does not predict', futbook.includes('describes, does not predict'))
check('FB-02 settlement source words on the mark', futbook.includes('VWAP') && futbook.includes('band midpoint'))
check('FB-02 settlement of record for expired contracts', futbook.includes('settlement of record'))

// FB-03 — no direction words (negative control: the file must still speak about sides, which are allowed)
for (const word of ['bullish', 'bearish', 'upside', 'downside', 'price target']) {
  check(`FB-03 no "${word}"`, !futbook.toLowerCase().includes(word))
}
check('FB-03 control: sides are allowed and present', futbook.includes("'buy'") && futbook.includes("'sell'"))

// FB-04 — the paper book API only; no order-API word
check('FB-04 talks to /api/mcx/book', futbook.includes("'/api/mcx/book'") && futbook.includes("post('/api/mcx/book/mark')"))
for (const word of ['place_order', 'placeOrder', 'square_off', 'cancel_order']) {
  check(`FB-04 no "${word}"`, !futbook.includes(word))
}
check('FB-04 no order API copy promise', futbook.includes('No order API exists'))

if (failures > 0) { console.error(`${failures} futbook check(s) failed`); process.exit(1) }
console.log('futbook.check.ts: all checks passed')

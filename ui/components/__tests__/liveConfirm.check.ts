// Item 8 (22 Nov spec): the quiet hint and the hover line carry NSE's confirmation age, live; no confirmation, no NSE words.
import * as nodeModule from 'node:module'
;(nodeModule as unknown as { registerHooks?: (h: unknown) => void }).registerHooks?.({
  resolve(spec: string, ctx: unknown, next: (s: string, c: unknown) => unknown) {
    try { return next(spec, ctx) } catch (e) {
      if (/^(\.|\/|file:)/.test(spec) && !/\.[cm]?[jt]sx?$/.test(spec)) return next(`${spec}.ts`, ctx)
      throw e
    }
  },
})
const LQ = (await import(new URL('../../lib/liveQuotes.ts', import.meta.url).href)) as typeof import('../../lib/liveQuotes')
let failed = 0, passed = 0
const check = (n: string, c: unknown, x?: unknown) => { if (c) { passed++; return } failed++; console.error(`FAIL ${n} :: ${JSON.stringify(x)}`) }
const NOW = Date.UTC(2026, 10, 5, 4, 50, 30)
const iso = (ms: number) => `${new Date(ms + 330 * 60_000).toISOString().slice(0, 19)}+05:30`
const OPEN = { state: 'open' as const, session_date: '2026-11-05' }
const CR = "quiet: no tick for 1320 s on a healthy feed; NSE's copy (95 s old) shows the same price and volume"
const p = LQ.parseLiveQuotes({ quotes: {
  ABB: { price: 5000, source: 'breeze_ws', age_s: 1320, state: 'live', reason: CR, ltt: iso(NOW - 1_320_000), confirmed_by: 'nse_quote', confirmed_age_s: 95 },
  IDEA: { price: 9, source: 'breeze_ws', age_s: 92, state: 'live', reason: 'quiet: no new trade or quote for 92 s on a healthy feed', ltt: iso(NOW - 92_000) },
  TCS: { price: 4000, source: 'breeze_ws', age_s: 0.4, state: 'live', reason: null, ltt: iso(NOW) } } }, NOW)
check('parse keeps confirmed_by / confirmed_age_s', p.quotes.ABB.confirmed_by === 'nse_quote' && p.quotes.ABB.confirmed_age_s === 95, p.quotes.ABB)
const a = LQ.quoteSource(p.quotes.ABB, OPEN, NOW + 4_000)
check('a confirmed row: LIVE·q, chip age = local refresh (4 s), confirmS = 95 + 4', a.state === 'live' && a.quiet === true && a.ageS === 4 && a.confirmS === 99, a)
check('its hint says how old NSE\'s copy is now', /NSE's copy 2m old shows the same price and volume/.test(a.hint ?? ''), a.hint)
const b = LQ.quoteSource(p.quotes.IDEA, OPEN, NOW + 1_000)
check('negative: an unconfirmed quiet row (≤ 120 s) has no confirmS and no NSE words', b.confirmS == null && !/NSE/.test(b.hint ?? ''), b)
const pane = LQ.liveSourceInfo([p.quotes.ABB, p.quotes.IDEA, p.quotes.TCS], OPEN, 'ok', NOW + 4_000)
check('the pane chip carries the oldest confirmation behind it', pane?.state === 'live' && pane?.confirmS === 99, pane)
const line = LQ.quoteLine(p.quotes.ABB, OPEN, NOW + 4_000)
check('hover line: quiet · last trade … · NSE check … ago', /LIVE · quiet · last trade \d\d:\d\d:\d\d IST \(\d+m ago\) · NSE check .+ ago/.test(line), line)
const stalled = LQ.quoteSource(p.quotes.ABB, OPEN, NOW + 15_000)
check('negative: a window that stopped refreshing shows DELAYED (no LIVE, no confirm age)', stalled.state === 'delayed' && stalled.confirmS == null, stalled)
console.log(`confirm.check: ${passed} passed, ${failed} failed`)
if (failed) process.exit(1)

/**
 * Live program checks (reports/live_nse, builder LV-UI): the one live-quote hook (ui/lib/liveQuotes.ts), the pane rules
 * (ui/components/liveModel.ts), the hover card's stored half (ui/components/terminal/hoverModel.ts), the chip text
 * (ui/components/terminal/source.ts) and the adoption across the panes L-INVENTORY ranked — each rule with a negative
 * control, under plain node ≥ 23.6 (type stripping, no deps):
 *
 *   node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON ui/components/__tests__/live.check.ts
 *
 * Also type-checked by `cd ui && npx tsc --noEmit`. Exits non-zero on any failing check.
 *
 *  L1  symbols: only NSE codes leave the window (the service 422s a whole batch on one bad symbol)
 *  L2  the wire body is validated (types, enums, finiteness; a row without a price is unavailable)
 *  L3  a row's chip: LIVE only when the server said live AND this window received it seconds ago; NSE website rows
 *      DELAYED with their age; CLOSE <session> after the close; OFFLINE with a reason
 *  L4  a pane's chip over its rows: worst state, its oldest age, a mix count; null until the service answers
 *  L5  the hover card's time + source line; the fallback line never says LIVE for a Yahoo row
 *  L6  the store: one request for the union, per-symbol cadence, new symbols fetched alone, 404 → once a minute,
 *      errors back off, closed market / hidden window slow down, nothing after the last consumer leaves, ≤ 300 a request
 *  L7  liveModel: NSE website never LIVE; who-moved points recomputed on live rows; levels; underlyings; header chip
 *  L8  hoverModel: adjusted spark (a split is not a cliff), range position
 *  L9  source.ts: the age / mix / CLOSE wording, and the pre-live labels unchanged
 *  L10 static adoption scans over the UI tree (the hover card first), with negative controls on synthetic snippets
 */
import * as fs from 'node:fs'
import * as nodeModule from 'node:module'
import * as path from 'node:path'

;(nodeModule as unknown as { registerHooks?: (h: unknown) => void }).registerHooks?.({
  resolve(spec: string, ctx: unknown, next: (s: string, c: unknown) => unknown) {
    try {
      return next(spec, ctx)
    } catch (e) {
      if (/^(\.|\/|file:)/.test(spec) && !/\.[cm]?[jt]sx?$/.test(spec)) return next(`${spec}.ts`, ctx)
      throw e
    }
  },
})

type LQMod = typeof import('../../lib/liveQuotes')
type ModelMod = typeof import('../liveModel')
type HoverMod = typeof import('../terminal/hoverModel')
type SourceMod = typeof import('../terminal/source')
const LQ = (await import(new URL('../../lib/liveQuotes.ts', import.meta.url).href)) as LQMod
const M = (await import(new URL('../liveModel.ts', import.meta.url).href)) as ModelMod
const H = (await import(new URL('../terminal/hoverModel.ts', import.meta.url).href)) as HoverMod
const S = (await import(new URL('../terminal/source.ts', import.meta.url).href)) as SourceMod

const UI = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..')
const read = (rel: string): string => fs.readFileSync(path.join(UI, rel), 'utf8')
/** Source text with comments blanked (line and block), so prose never counts as code. */
const code = (s: string): string =>
  s.replace(/\/\*[\s\S]*?\*\//g, m => m.replace(/[^\n]/g, ' ')).replace(/(^|[^:'"`\\])\/\/[^\n]*/g, '$1')

let failed = 0
let passed = 0
function check(name: string, cond: unknown, extra?: unknown): void {
  if (cond) { passed++; return }
  failed++
  console.error(`FAIL ${name}${extra !== undefined ? ` :: ${JSON.stringify(extra)}` : ''}`)
}

// 5 Nov 2026 10:20:30 IST
const NOW = Date.UTC(2026, 10, 5, 4, 50, 30)
const iso = (ms: number) => `${new Date(ms + 330 * 60_000).toISOString().slice(0, 19)}+05:30`
type Row = import('../../lib/liveQuotes').LiveQuote
const row = (over: Partial<Row> = {}): Row => ({
  symbol: 'RELIANCE', price: 1480.5, change: 12.3, change_pct: 0.84, prev_close: 1468.2, open: 1470, day_high: 1485, day_low: 1466,
  volume: 1_234_567, value_cr: 182.4, bid: 1480.4, ask: 1480.6, ltt: iso(NOW - 1_000), source: 'breeze_ws', age_s: 1, state: 'live',
  reason: null, received_at: NOW, ...over,
})
const OPEN = { state: 'open' as const, session_date: '2026-11-05' }
const CLOSED = { state: 'closed' as const, session_date: '2026-11-05' }

// ── L1 symbols ──────────────────────────────────────────────────────────────────────────────────────────────────
{
  const n = LQ.normLiveSymbol
  check('L1 .NS stripped, upper-cased', n('reliance.ns') === 'RELIANCE' && n(' m&m ') === 'M&M' && n('BAJAJ-AUTO') === 'BAJAJ-AUTO')
  check('L1 index names keep their (collapsed) spaces', n('nifty  50') === 'NIFTY 50' && n('NIFTY FIN SERVICE') === 'NIFTY FIN SERVICE' && n('INDIA VIX') === 'INDIA VIX')
  check('L1 negative: Yahoo / BSE forms never leave the window', [ '^NSEI', 'INR=X', 'GC=F', 'RELIANCE.BO', 'BZ=F', '^GSPC', 'A/B' ].every(x => n(x) === null))
  check('L1 negative: empty, non-string, over-long', n('') === null && n(null) === null && n(undefined) === null
    && n('A'.repeat(21)) === null && n('A B C D E F G') === null && n(`NIFTY ${'X'.repeat(40)}`) === null)
}

// ── L2 wire body ────────────────────────────────────────────────────────────────────────────────────────────────
{
  const b = LQ.parseLiveQuotes({
    as_of: '2026-11-05T10:20:30+05:30', market: { state: 'open', session_date: '2026-11-05' },
    quotes: {
      RELIANCE: { price: 1480.5, change: '12.3', change_pct: 0.84, prev_close: 1468.2, ltt: '2026-11-05T10:20:29+05:30', source: 'breeze_ws', age_s: 1, state: 'live' },
      'NIFTY 50': { price: 24389.5, change_pct: 1.79, prev_close: 23960.6, source: 'nse_api', age_s: 48, state: 'delayed' },
      BAD: { price: 'x', state: 'live' },
      ODD: { price: 10, state: 'shouting', source: 'breeze_ws' },
      NAN: { price: Number.NaN, state: 'live' },
      'INR=X': { price: 83.1, state: 'live' },
    },
  }, NOW)
  check('L2 rows parsed and keyed by the NSE symbol', b.quotes.RELIANCE?.price === 1480.5 && b.quotes.RELIANCE.change === 12.3 && b.quotes['NIFTY 50']?.state === 'delayed')
  check('L2 market and as_of kept', b.market?.state === 'open' && b.market.session_date === '2026-11-05' && b.asOf === '2026-11-05T10:20:30+05:30')
  check('L2 negative: a row without a finite price is unavailable, never live', b.quotes.BAD?.state === 'unavailable' && b.quotes.BAD.price === null
    && b.quotes.NAN?.state === 'unavailable')
  check('L2 negative: an unknown state is unavailable', b.quotes.ODD?.state === 'unavailable' && b.quotes.ODD.price === null)
  check('L2 negative: a non-NSE key is dropped', !('INR=X' in b.quotes))
  const g = LQ.parseLiveQuotes('garbage', NOW)
  check('L2 negative: garbage body → nothing', Object.keys(g.quotes).length === 0 && g.market === null)
  check('L2 received_at stamped', b.quotes.RELIANCE.received_at === NOW)
}

// ── L3 one row's chip ───────────────────────────────────────────────────────────────────────────────────────────
{
  const live = LQ.quoteSource(row(), OPEN, NOW)
  check('L3 a fresh Breeze row is LIVE · BREEZE with its age', live.state === 'live' && S.sourceChipText(live, new Date(NOW)).label === 'LIVE · BREEZE · 1s', S.sourceChipText(live, new Date(NOW)))
  const old = LQ.quoteSource(row({ received_at: NOW - 30_000 }), OPEN, NOW)
  check('L3 negative: a live row this window got 30 s ago is NOT live (stalled poll)', old.state === 'delayed' && (old.ageS ?? 0) >= 30, old)
  const nse = LQ.quoteSource(row({ source: 'nse_api', state: 'delayed', age_s: 48 }), OPEN, NOW)
  check('L3 an NSE website row is DELAYED · NSE · 48s', nse.state === 'delayed' && S.sourceChipText(nse, new Date(NOW)).label === 'DELAYED · NSE · 48s', S.sourceChipText(nse, new Date(NOW)))
  const closed = LQ.quoteSource(row({ state: 'closed', source: 'eod', ltt: '2026-11-04T15:29:59+05:30' }), CLOSED, NOW)
  check('L3 after the close: CLOSE · <session date>', closed.state === 'closed' && S.sourceChipText(closed, new Date(NOW)).label === 'CLOSE · 04 NOV', S.sourceChipText(closed, new Date(NOW)))
  const mc = LQ.quoteSource(row({ state: 'live' }), CLOSED, NOW)
  check('L3 a market the service calls closed never reads LIVE', mc.state === 'closed')
  const stale = LQ.quoteSource(row({ state: 'stale', source: 'eod', age_s: 1800 }), OPEN, NOW)
  check('L3 a stale row reads STALE with its age', stale.state === 'stale' && S.sourceChipText(stale, new Date(NOW)).label === 'STALE · NSE EOD · 30m', S.sourceChipText(stale, new Date(NOW)))
  const off = LQ.quoteSource(row({ state: 'unavailable', price: null, reason: 'not subscribed and no NSE row' }), OPEN, NOW)
  check('L3 unavailable → OFFLINE with the reason', off.state === 'offline' && off.hint === 'not subscribed and no NSE row')
  check('L3 age = server age + time in this window', Math.round(LQ.quoteAgeS(row({ age_s: 2, received_at: NOW - 3_000 }), NOW) ?? -1) === 5)
}

// ── L4 a pane's chip ────────────────────────────────────────────────────────────────────────────────────────────
{
  const all = LQ.liveSourceInfo([row(), row({ symbol: 'TCS', age_s: 2 })], OPEN, 'ok', NOW)
  check('L4 all live → LIVE, oldest age, no mix tag', all?.state === 'live' && S.sourceChipText(all!, new Date(NOW)).label === 'LIVE · BREEZE · 2s', all && S.sourceChipText(all, new Date(NOW)))
  const mixed = LQ.liveSourceInfo([row(), row({ symbol: 'X', source: 'nse_api', state: 'delayed', age_s: 55 }), row({ symbol: 'Y', age_s: 1 })], OPEN, 'ok', NOW)
  check('L4 negative: one NSE row demotes the pane to DELAYED with its age and a mix count', mixed?.state === 'delayed'
    && S.sourceChipText(mixed!, new Date(NOW)).label === 'DELAYED · NSE · 55s · 2/3 LIVE', mixed && S.sourceChipText(mixed, new Date(NOW)))
  const cl = LQ.liveSourceInfo([row({ state: 'closed', ltt: '2026-11-05T15:29:58+05:30' }), row({ symbol: 'B', state: 'closed', ltt: '2026-11-05T15:29:59+05:30' })], CLOSED, 'ok', NOW)
  check('L4 every row closed → CLOSE · 05 NOV', cl?.state === 'closed' && S.sourceChipText(cl!, new Date(NOW)).label === 'CLOSE · 05 NOV')
  check('L4 null until the service answers (idle / loading / not deployed)', LQ.liveSourceInfo([row()], OPEN, 'idle', NOW) === null
    && LQ.liveSourceInfo([row()], OPEN, 'loading', NOW) === null && LQ.liveSourceInfo([row()], OPEN, 'missing', NOW) === null)
  const err = LQ.liveSourceInfo([row()], OPEN, 'error', NOW)
  check('L4 negative: a failing service is OFFLINE, never the last LIVE chip', err?.state === 'offline')
  const none = LQ.liveSourceInfo([row({ state: 'unavailable', price: null })], OPEN, 'ok', NOW)
  check('L4 no priced row → OFFLINE', none?.state === 'offline')
}

// ── L5 time + source lines ──────────────────────────────────────────────────────────────────────────────────────
{
  const l = LQ.quoteLine(row({ ltt: '2026-11-05T10:20:29+05:30' }), OPEN, NOW)
  check('L5 hover line: BREEZE LIVE · HH:MM:SS IST · age', l === 'BREEZE LIVE · 10:20:29 IST · 1s ago', l)
  const d = LQ.quoteLine(row({ source: 'nse_api', state: 'delayed', age_s: 52, ltt: '2026-11-05T10:19:38+05:30' }), OPEN, NOW)
  check('L5 hover line: NSE DELAYED', d === 'NSE DELAYED · 10:19:38 IST · 52s ago', d)
  const c = LQ.quoteLine(row({ state: 'closed', source: 'eod', ltt: '2026-11-04T15:29:59+05:30' }), CLOSED, NOW)
  check('L5 hover line after the close: CLOSE <day> · last trade', c === 'CLOSE 04 NOV · last trade 15:29:59 IST', c)
  check('L5 no row → no live quote · why', LQ.quoteLine(null, OPEN, NOW).startsWith('no live quote'))
  check('L5 negative: the fallback line never says LIVE for a Yahoo row', H.fallbackLine({ market_time: Math.floor(NOW / 1000) - 60 }) === 'YAHOO · DELAYED · last trade 10:19:30 IST'
    && !/LIVE/.test(H.fallbackLine({ source: 'yahoo', state: 'live', market_time: Math.floor(NOW / 1000) })))
  check('L5 a live-backed fallback row names its own source', H.fallbackLine({ source: 'breeze_ws', state: 'live', age_s: 1.2 }) === 'BREEZE LIVE · 1s old'
    && H.fallbackLine({ source: 'nse_api', state: 'delayed', age_s: 40 }) === 'NSE DELAYED · 40s old')
}

// ── overlay ─────────────────────────────────────────────────────────────────────────────────────────────────────
{
  const base = { symbol: 'RELIANCE.NS', price: 1400, change_pct: -1, day_high: 1410, day_low: 1390, spark: [1, 2, 3], high_52w: 1600, low_52w: 1200, name: 'Reliance' }
  const o = LQ.overlayQuote(base, row()) as typeof base & { live_source?: string }
  check('overlay: price / move / day range from the live row', o.price === 1480.5 && o.change_pct === 0.84 && o.day_high === 1485 && o.day_low === 1466)
  check('overlay: name, spark and 52-week range kept', o.name === 'Reliance' && o.spark.length === 3 && o.high_52w === 1600 && o.live_source === 'breeze_ws')
  check('overlay negative: an unavailable row leaves the record untouched', LQ.overlayQuote(base, row({ state: 'unavailable', price: null })) === base)
}

// ── L6 the store ────────────────────────────────────────────────────────────────────────────────────────────────
{
  type Timer = { at: number; fn: () => void; id: number }
  function harness(respond: (syms: string[]) => { status: number; body: unknown }) {
    let t = NOW
    let seq = 0
    let timers: Timer[] = []
    let hidden = false
    const calls: string[][] = []
    const urls: string[] = []
    const store = LQ.createLiveStore({
      get: async (url) => {
        urls.push(url)
        const syms = decodeURIComponent(url.split('symbols=')[1] ?? '').split(',')
        calls.push(syms)
        return respond(syms)
      },
      now: () => t,
      setTimer: (fn, ms) => { const id = ++seq; timers.push({ at: t + ms, fn, id }); return id },
      clearTimer: id => { timers = timers.filter(x => x.id !== id) },
      hidden: () => hidden,
    })
    const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve() }
    /** advance the fake clock, firing due timers in order */
    const advance = async (ms: number) => {
      const end = t + ms
      for (;;) {
        timers.sort((a, b) => a.at - b.at)
        const next = timers[0]
        if (!next || next.at > end) break
        timers.shift()
        t = Math.max(t, next.at)
        next.fn()
        await flush()
      }
      t = end
      await flush()
    }
    return { store, calls, urls, advance, flush, setHidden: (h: boolean) => { hidden = h }, timers: () => timers.length, now: () => t }
  }
  const okBody = (market: 'open' | 'closed' = 'open') => (syms: string[]) => ({
    status: 200,
    body: { as_of: iso(NOW), market: { state: market, session_date: '2026-11-05' },
            quotes: Object.fromEntries(syms.map(s => [s, { price: 100, change_pct: 1, prev_close: 99, source: 'breeze_ws', age_s: 1, state: market === 'open' ? 'live' : 'closed', ltt: iso(NOW) }])) },
  })

  {
    const h = harness(okBody())
    h.store.register(1, ['RELIANCE', 'TCS'], 3_000)
    h.store.register(2, ['NIFTY 50', 'TCS'], 2_000)
    await h.advance(0)
    check('L6 one request carries the union of every consumer', h.calls.length >= 1 && JSON.stringify([...new Set(h.calls.flat())].sort()) === JSON.stringify(['NIFTY 50', 'RELIANCE', 'TCS']), h.calls)
    check('L6 the request goes to /api/live/quotes only (no Yahoo, no news-scanner)', h.urls.every(u => u.startsWith('/api/live/quotes?symbols=')) && !h.urls.some(u => /yahoo|news-scanner|\.NS/i.test(decodeURIComponent(u))))
    const snap = h.store.snapshot()
    check('L6 rows land in the snapshot with status ok', snap.status === 'ok' && snap.quotes.get('TCS')?.price === 100 && snap.market?.state === 'open')
    h.calls.length = 0
    await h.advance(2_000)
    check('L6 per-symbol cadence: at 2 s only the 2 s symbols are due', JSON.stringify(h.calls.flat().sort()) === JSON.stringify(['NIFTY 50', 'TCS']), h.calls)
    h.calls.length = 0
    await h.advance(1_000)
    check('L6 per-symbol cadence: at 3 s the 3 s symbol is due', h.calls.flat().includes('RELIANCE'), h.calls)
    h.calls.length = 0
    h.store.register(3, ['INFY'], 3_000)
    await h.advance(1_100)
    check('L6 a new symbol is fetched within a second (riding a due round when one is due anyway)', h.calls.some(c => c.includes('INFY')), h.calls)
    h.store.unregister(1); h.store.unregister(2); h.store.unregister(3)
    h.calls.length = 0
    await h.advance(120_000)
    check('L6 negative: nothing is polled after the last consumer leaves', h.calls.length === 0, h.calls)
    h.store.dispose()
  }
  {
    const h = harness(okBody())
    h.store.register(1, ['RELIANCE', 'TCS'], 10_000)
    await h.advance(0)
    await h.advance(2_000)
    h.calls.length = 0
    h.store.register(2, ['INFY'], 10_000)
    await h.advance(1_100)
    check('L6 a new symbol between rounds is fetched at once, alone (not the whole union)', h.calls.length === 1 && JSON.stringify(h.calls[0]) === '["INFY"]', h.calls)
    h.calls.length = 0
    h.store.register(3, ['INFY', 'RELIANCE'], 10_000)
    await h.advance(500)
    check('L6 negative: symbols already held fresh are not fetched again on a new consumer', h.calls.length === 0, h.calls)
    h.store.dispose()
  }
  {
    const h = harness(() => ({ status: 404, body: { detail: 'Not Found' } }))
    h.store.register(1, ['RELIANCE'], 2_000)
    await h.advance(0)
    check('L6 a missing route (404) → status missing (consumers keep their own chips)', h.store.snapshot().status === 'missing')
    h.calls.length = 0
    await h.advance(30_000)
    check('L6 404: not asked again within the minute', h.calls.length === 0, h.calls)
    await h.advance(31_000)
    check('L6 404: asked again after a minute', h.calls.length === 1, h.calls)
    h.store.dispose()
  }
  {
    const h = harness(() => ({ status: 503, body: null }))
    h.store.register(1, ['RELIANCE'], 2_000)
    await h.advance(0)
    check('L6 an error → status error', h.store.snapshot().status === 'error')
    check('L6 errors back off 2 → 4 s', h.store.nextDelay() === 2_000)
    await h.advance(2_000)
    check('L6 second error → 4 s', h.store.nextDelay() === 4_000)
    h.store.dispose()
  }
  {
    const h = harness(okBody('closed'))
    h.store.register(1, ['RELIANCE'], 2_000)
    await h.advance(0)
    h.calls.length = 0
    await h.advance(10_000)
    check('L6 NSE closed: no 2 s polling (≥ 30 s)', h.calls.length === 0, h.calls)
    await h.advance(25_000)
    check('L6 NSE closed: still polled, slowly', h.calls.length === 1, h.calls)
    h.store.dispose()
  }
  {
    const h = harness(okBody())
    h.setHidden(true)
    h.store.register(1, ['RELIANCE'], 2_000)
    await h.advance(0)
    h.calls.length = 0
    await h.advance(10_000)
    check('L6 hidden window: no 2 s polling', h.calls.length === 0, h.calls)
    h.setHidden(false)
    await h.store.pollNow()
    check('L6 window visible again: polled at once', h.calls.length === 1, h.calls)
    h.store.dispose()
  }
  {
    const many = Array.from({ length: 650 }, (_, i) => `S${i}`)
    const h = harness(okBody())
    h.store.register(1, many, 5_000)
    await h.advance(0)
    check('L6 ≤ 300 symbols per request (650 → 3 requests)', h.calls.length === 3 && h.calls.every(c => c.length <= LQ.MAX_SYMBOLS_PER_REQUEST), h.calls.map(c => c.length))
    h.store.dispose()
  }
  {
    const h = harness(syms => ({ status: 200, body: { market: { state: 'open', session_date: '2026-11-05' }, quotes: Object.fromEntries(syms.filter(s => s !== 'GHOST').map(s => [s, { price: 1, state: 'live', source: 'breeze_ws', age_s: 0 }])) } }))
    h.store.register(1, ['RELIANCE', 'GHOST'], 2_000)
    await h.advance(0)
    check('L6 a symbol the server did not return is unavailable, not silently absent', h.store.snapshot().quotes.get('GHOST')?.state === 'unavailable')
    h.store.dispose()
  }
}

// ── status (SYS live feeds) ──────────────────────────────────────────────────────────────────────────────────
{
  const st = LQ.parseLiveStatus({ state: 'live', subscribed: 101, ticks_per_min: '3400', last_tick_age_s: 0.4, cap: 500, breeze_session: true,
                                  nse_fallback: { ok: true, last_ok_at: '2026-11-05T10:20:00+05:30' } })
  check('status: the contract fields, validated', st?.state === 'LIVE' && st.subscribed === 101 && st.ticks_per_min === 3400 && st.breeze_session === true && st.nse_fallback?.ok === true)
  check('status negative: garbage → null; wrong types → null fields', LQ.parseLiveStatus('x') === null && LQ.parseLiveStatus([]) === null
    && LQ.parseLiveStatus({ state: 3, breeze_session: 'yes', cap: 'n/a' })?.breeze_session === null && LQ.parseLiveStatus({ cap: 'n/a' })?.cap === null)
  check('status: SYS renders the live-feeds panel', /<LiveFeedStatus \/>/.test(code(read('components/SystemTelemetry.tsx'))) && /fetchLiveStatus/.test(code(read('components/LiveFeedStatus.tsx'))))
}

// ── L7 liveModel ────────────────────────────────────────────────────────────────────────────────────────────────
{
  const fresh = M.nseDelayedSource('05-Nov-2026 10:20:25', { marketOpen: true, now: NOW })
  check('L7 negative: an NSE website stamp 5 s old is still DELAYED, never LIVE', fresh.state === 'delayed' && Math.round(fresh.ageS ?? -1) === 5, fresh)
  const minute = M.nseDelayedSource('05-Nov-2026 10:14', { marketOpen: true, now: NOW })
  check('L7 a minute-only stamp reads DELAYED with its age and says it is stamped to the minute', minute.state === 'delayed' && /minute/.test(minute.hint ?? '')
    && S.sourceChipText(minute, new Date(NOW)).label === 'DELAYED · NSE · 7m', S.sourceChipText(minute, new Date(NOW)))
  check('L7 older than 10 min in session → STALE', M.nseDelayedSource('05-Nov-2026 10:05', { marketOpen: true, now: NOW }).state === 'stale')
  const cl = M.nseDelayedSource('04-Nov-2026 15:30', { marketOpen: false, now: NOW })
  check('L7 session over → CLOSE · <day>', cl.state === 'closed' && S.sourceChipText(cl, new Date(NOW)).label === 'CLOSE · 04 NOV')
  check('L7 no stamp → OFFLINE', M.nseDelayedSource(null, { marketOpen: true, now: NOW }).state === 'offline')

  const payload = { index: 'NIFTY 50', last: 24300, change: 300, change_pct: 1.25, explained_points: 290, time: '05-Nov-2026 10:14', missing: [],
    members: [
      { symbol: 'HDFCBANK', change_pct: 1, weight_pct: 10, points: 24, promoter_pct: 0 },
      { symbol: 'RELIANCE', change_pct: 2, weight_pct: 8, points: 38.4, promoter_pct: 50 },
      { symbol: 'TCS', change_pct: -1, weight_pct: 4, points: -9.6, promoter_pct: 72 },
    ] }
  const none = M.liveContribution(payload, {})
  check('L7 who moved, no live rows: the payload unchanged (counts 0)', none.liveMembers === 0 && !none.indexLive && none.explained_points === 290 && none.last === 24300)
  const lr = (price: number, change_pct: number, prev_close: number | null = null, state = 'live') => ({ price, change_pct, prev_close, state, change: null })
  const live = M.liveContribution(payload, { 'NIFTY 50': lr(24400, 1.67, 24000), HDFCBANK: lr(1700, 2), TCS: lr(4000, -0.5) })
  const h = live.members.find(m => m.symbol === 'HDFCBANK')!, t = live.members.find(m => m.symbol === 'TCS')!, r = live.members.find(m => m.symbol === 'RELIANCE')!
  check('L7 points = previous level × weight × live move (prev level from the live index row)', h.points === 48 && t.points === -4.8, { h, t })
  check('L7 a member without a live row keeps the payload move', r.points === 38.4 && r.change_pct === 2)
  check('L7 explained total and index from the live rows; sorted by points', Math.abs(live.explained_points - 81.6) < 0.05 && live.indexLive && live.last === 24400
    && live.change === 400 && live.members[0].symbol === 'HDFCBANK' && live.liveMembers === 2, live)
  check('L7 negative: an unavailable row is ignored', M.liveContribution(payload, { HDFCBANK: { price: null, change_pct: 9, prev_close: null, state: 'unavailable' } }).liveMembers === 0)
  check('L7 liveLevel prefers a priced service row and says so', M.liveLevel({ last: 1, change_pct: 0 }, lr(2, 3)).fromService
    && !M.liveLevel({ last: 1, change_pct: 0 }, null).fromService && M.liveLevel({ last: 1, change_pct: 0 }, null).last === 1)
  check('L7 F&O underlyings → live symbols', M.underlyingLiveSymbol('NIFTY') === 'NIFTY 50' && M.underlyingLiveSymbol('BANKNIFTY') === 'NIFTY BANK'
    && M.underlyingLiveSymbol('FINNIFTY') === 'NIFTY FIN SERVICE' && M.underlyingLiveSymbol('reliance') === 'RELIANCE' && M.underlyingLiveSymbol('') === null)
  const hc = M.liveHeaderChip(LQ.quoteSource(row({ symbol: 'NIFTY 50' }), OPEN, NOW), iso(NOW - 1000))
  check('L7 header chip: ● LIVE on a fresh Breeze index row', hc?.text === '● LIVE' && hc.tone === 'live')
  const hd = M.liveHeaderChip(LQ.quoteSource(row({ source: 'nse_api', state: 'delayed', age_s: 70 }), OPEN, NOW), iso(NOW - 70_000))
  check('L7 negative: header chip on an NSE row is ● NSE · age (delayed), never ● LIVE', hd?.text === '● NSE · 70s' && hd.tone === 'delayed', hd)
  const hcl = M.liveHeaderChip(LQ.quoteSource(row({ state: 'closed', ltt: '2026-11-04T15:30:00+05:30' }), CLOSED, NOW), '2026-11-04T15:30:00+05:30')
  check('L7 header chip after the close: CLOSE 04-NOV', hcl?.text === 'CLOSE 04-NOV' && hcl.tone === 'closed', hcl)
  check('L7 header chip: no row → null (the header keeps its older sources)', M.liveHeaderChip(null, null) === null)
}

// ── L8 hoverModel ───────────────────────────────────────────────────────────────────────────────────────────────
{
  // newest first; a 1:1 bonus on day 3 halves the raw close, the adjusted change that day is +1 %
  const rows = [
    { date: '2026-11-04', close: 101, change_pct: 1 },
    { date: '2026-11-03', close: 100, change_pct: 1 },     // ex-date: raw 200 → 100, adjusted +1 %
    { date: '2026-11-02', close: 198, change_pct: 0.5 },
    { date: '2026-10-30', close: 197, change_pct: null },
  ]
  const sp = H.adjustedSpark(rows)
  check('L8 adjusted spark: oldest first, ends on the last close', sp.length === 4 && sp[sp.length - 1] === 101)
  check('L8 negative: a bonus is not a cliff (no step near −50 %)', sp.every((v, i) => i === 0 || Math.abs(v / sp[i - 1] - 1) < 0.05), sp)
  const hh = H.hoverHistory({ rows, summary: { high: 120, low: 80, to: '2026-11-04' } })
  check('L8 hover history: 52w from the adjusted summary, last date', hh?.high_52w === 120 && hh.low_52w === 80 && hh.last_date === '2026-11-04')
  check('L8 no rows → null', H.hoverHistory({ rows: [], summary: null }) === null && H.hoverHistory(null) === null)
  check('L8 range position clipped to [0, 1]', H.rangePos(100, 80, 120) === 0.5 && H.rangePos(130, 80, 120) === 1 && H.rangePos(50, 80, 120) === 0 && H.rangePos(100, 120, 120) === null)
  check('L8 short day', H.shortDay('2026-11-04') === '04 NOV' && H.shortDay('x') === '')
}

// ── L9 source.ts wording ────────────────────────────────────────────────────────────────────────────────────────
{
  const d = new Date(NOW)
  check('L9 the pre-live labels are unchanged without an age', S.sourceChipText(S.sourceOf('2026-11-05T10:00:00+05:30', { live: true, source: 'Breeze', now: d }), d).label === 'LIVE · BREEZE'
    && S.sourceChipText(S.sourceOf('2026-11-03T15:30:00+05:30', { source: 'NSE', now: d, maxAgeDays: 9 }), d).label === 'DELAYED · 03 NOV')
  check('L9 EOD panes say EOD + the date (daily data is never live)', S.sourceChipText(S.sourceOf('2026-11-04', { source: 'NSE F&O bhavcopy', now: d }), d).label === 'EOD · 04 NOV'
    && /End-of-day data from NSE F&O bhavcopy/i.test(S.sourceChipText(S.sourceOf('2026-11-04', { source: 'NSE F&O bhavcopy', now: d }), d).title))
  check('L9 negative: an old daily as-of is STALE, not EOD; an undated feed keeps its name', S.sourceChipText(S.sourceOf('2026-10-30', { now: d }), d).label === 'STALE · 30 OCT'
    && S.sourceChipText(S.undatedSource('NSE calendar')).label === 'DELAYED · NSE CALENDAR')
  check('L9 ages: seconds, then minutes, then hours', S.fmtAgeS(0.4) === '0s' && S.fmtAgeS(89) === '89s' && S.fmtAgeS(90) === '2m' && S.fmtAgeS(5400) === '2h' && S.fmtAgeS(null) === '')
  check('L9 mix tag only when SOME rows are live', S.sourceChipText({ state: 'delayed', source: 'NSE', asOf: iso(NOW), ageS: 50, mix: { live: 0, total: 5 } }, d).label === 'DELAYED · NSE · 50s'
    && S.sourceChipText({ state: 'live', source: 'BREEZE', asOf: iso(NOW), ageS: 1, mix: { live: 5, total: 5 } }, d).label === 'LIVE · BREEZE · 1s')
  check('L9 CLOSE without a date', S.sourceChipText({ state: 'closed', source: 'NSE', asOf: null }, d).label === 'CLOSE')
}

// ── L10 static adoption scans ───────────────────────────────────────────────────────────────────────────────────
{
  const HOOK = /from\s+['"]@\/lib\/liveQuotes['"]/
  const adopted = (src: string) => HOOK.test(src) && /\buseLiveQuotes\b|\buseNseQuotes\b/.test(src)
  check('L10 negative control: the adoption scan rejects a file without the hook', !adopted("import { useLiveQuotes } from '@/context/AppContext'\nuseLiveQuotes()"))
  // the panes L-INVENTORY ranked (the hover card first), each on the hook and rendering a chip
  const PANES: [string, string][] = [
    ['components/terminal/index.tsx', 'hover card'], ['components/WatchMonitor.tsx', 'WTCH'], ['components/IndexContribution.tsx', 'MOV who moved'],
    ['components/LiveMovers.tsx', 'MOV tiles + drill-down'], ['components/IndexIntraday.tsx', 'intraday tips'], ['components/Brief.tsx', 'BRF book + who moved'],
    ['components/StockDetailModal.tsx', 'stock window'], ['components/DecisionDesk.tsx', 'DESK holdings'], ['components/MarketCommandHeader.tsx', 'header + tape'],
    ['components/ChartStudio.tsx', 'CHRT last price'], ['components/OptionChain.tsx', 'OMON spot'], ['components/DerivativesDesk.tsx', 'DERV spot'],
    ['components/IndexMembers.tsx', 'MEMB today'], ['components/AlertsCenter.tsx', 'ALRT prices'], ['components/PortfolioSummary.tsx', 'BRKR day move'],
    ['components/LiveMonitorBar.tsx', 'watchlist line'], ['components/news/NewsTerminal.tsx', 'news dock'], ['components/WorldMarkets.tsx', 'WEI India'],
    ['components/StockTable.tsx', 'EQS CMP'], ['components/MarketMap.tsx', 'market map rest'],
  ]
  const notAdopted = PANES.filter(([f]) => !adopted(code(read(f)))).map(([f, w]) => `${w} (${f})`)
  check('L10 every ranked pane reads the live hook', notAdopted.length === 0, notAdopted)
  // a pane renders its own chip, or (IndexContribution / IndexIntraday / MarketInternals) hands it to the parent Panel
  // through onSource, and every parent passes one
  const CHIP = /<SourceChip\b|\bsource=\{|data-feed=|data-sd-price=|\bonSource\?\.\(/
  const noChip = PANES.filter(([f]) => !CHIP.test(code(read(f)))).map(([f]) => f)
  check('L10 every adopted pane renders a source chip (or hands it to its Panel)', noChip.length === 0, noChip)
  const handed = ['IndexIntraday', 'IndexContribution', 'MarketInternals']
  const parents = ['components/LiveMovers.tsx', 'components/Brief.tsx'].map(f => code(read(f)))
  // JSX renders only (a generic such as useLoad<MarketInternals>( is a type, not a render)
  const bare = handed.flatMap(c => parents.flatMap(p => [...p.matchAll(new RegExp(`<${c}\\b[^>]*>(?!\\()`, 'g'))].map(m => m[0]))).filter(t => !/onSource=/.test(t))
  check('L10 every parent of a chip-handing pane takes its chip (onSource)', bare.length === 0, bare)
  check('L10 negative control: the onSource scan catches a bare render', /<IndexIntraday\b[^>]*>/.test('<IndexIntraday height={190} />') && !/onSource=/.test('<IndexIntraday height={190} />'))

  const kit = code(read('components/terminal/index.tsx'))
  const hover = kit.slice(kit.indexOf('function HoverCard'), kit.indexOf('// NSE surveillance marks'))
  check('L10 hover card: no "Yahoo · ≈1 min delayed", a time + source line, the spark labelled daily', !kit.includes('Yahoo · ≈1 min delayed')
    && /live\.lineFor\(sym\)/.test(hover) && /1M DAILY CLOSES/.test(hover) && /data-sd-spark="daily"/.test(hover))
  check('L10 hover card reads quotes only through the live hook; the old route only as the fallback', !/getNewsQuotes/.test(hover) && /needFallback/.test(hover)
    && /function hoverFallback[\s\S]*?getNewsQuotes/.test(kit) && !/getNewsQuotes/.test(kit.slice(kit.indexOf('function hoverStored'), kit.indexOf('const fallbackCache'))))
  check('L10 hover card 52w / spark from NSE bhavcopy history (getStockHistory), not Yahoo', /getStockHistory\(sym, 366\)/.test(kit))

  // the Yahoo overwrite path (useLiveTicks → /api/quotes/ticks Yahoo rows) is gone from the panes that had it (D4)
  const ticks = ['components/StockDetailModal.tsx', 'components/WatchMonitor.tsx', 'components/DecisionDesk.tsx'].filter(f => /useLiveTicks\(/.test(code(read(f))))
  check('L10 D4: no pane overlays the old tick map (Yahoo rows while ticks were off)', ticks.length === 0, ticks)
  check('L10 negative control: the D4 scan catches the old form', /useLiveTicks\(/.test('const liveT = useLiveTicks(nseSyms)'))

  // the hook talks only to the live service
  const hook = code(read('lib/liveQuotes.ts'))
  check('L10 the hook calls /api/live/quotes and nothing Yahoo', hook.includes('/api/live/quotes') && !/news-scanner|yahoo|getNewsQuotes|finance\.yahoo/i.test(hook))

  // NSE website data never claims LIVE: no sourceOf(… source: 'NSE…', live: <not false>) anywhere in components
  const NSE_LIVE = /\bsourceOf\([^;]*?source:\s*(?:[\w.!?]+\s*\?\s*)?['"`]NSE[^;]*?\blive:\s*(?!false\b)[^,}\s]/
  check('L10 negative control: the NSE-live scan catches the old MOV chip', NSE_LIVE.test("sourceOf(nseStampIso(data?.timestamp), { live: !!data?.market_open, source: 'NSE' })".replace(/\{ live: (.*?), source: 'NSE' \}/, "{ source: 'NSE', live: $1 }")))
  const comps: string[] = []
  const walk = (dir: string): void => {
    for (const e of fs.readdirSync(path.join(UI, dir), { withFileTypes: true })) {
      if (e.name === 'node_modules' || e.name === '__tests__' || e.name.startsWith('.')) continue
      const rel = path.join(dir, e.name)
      if (e.isDirectory()) walk(rel)
      else if (rel.endsWith('.tsx')) comps.push(rel)
    }
  }
  walk('components')
  const nseLive = comps.filter(f => NSE_LIVE.test(code(read(f))))
  check('L10 no NSE-website chip can read LIVE (DELAYED <age>, CLOSE after the session)', nseLive.length === 0, nseLive)

  // the MOV panels each carry their own chip (D6), not one shared feed chip
  const mov = code(read('components/LiveMovers.tsx'))
  check('L10 D6: MOV intraday ×2 / who moved / internals take their own chips', /source=\{srcN50 \?\? feedSource\}/.test(mov) && /source=\{srcBank \?\? feedSource\}/.test(mov)
    && /source=\{srcContrib \?\? feedSource\}/.test(mov) && /source=\{srcInternals \?\? feedSource\}/.test(mov) && /<IndexContribution onSource=\{setSrcContrib\} \/>/.test(mov))
  // BRF re-polls its NSE lines (D5)
  const brf = code(read('components/Brief.tsx'))
  check('L10 D5: BRF re-polls who moved, valuation, options, GIFT, internals', /getIndexContribution\('NIFTY 50'\), \[\], \{ ms: 120_000 \}/.test(brf)
    && /getIndexValuation\(\), \[\], \{ ms: 60_000 \}/.test(brf) && /getGiftNifty, \[\], \{ ms: 60_000/.test(brf) && /getMarketInternals\(\), \[\], \{ ms: 120_000 \}/.test(brf)
    && /\}, \[\], \{ ms: 60_000 \}\)/.test(brf))
  // the stock window: the live service is the only price once it answers
  const modal = code(read('components/StockDetailModal.tsx'))
  check('L10 stock window: a legacy socket value cannot overwrite a live-service price', /if \(liveQ\?\.ltp !== undefined && !lqPriced\)/.test(modal) && /marker: liveMarker\(lqInfo, lq\.ltt\)/.test(modal))
  // the market map: no Yahoo for NSE names while the live service answers
  const map = code(read('components/MarketMap.tsx'))
  check('L10 market map: the Yahoo leg runs only while the live service does not answer', /if \(svcOk\.current\) return/.test(map) && /useLiveQuotes\(rest, \{ intervalMs: 15_000/.test(map))
}

// ── PM fixes after the adversarial checks (5 Nov) ────────────────────────────────────────────────────────────────
{
  // a request that never settles becomes a feed error after the deadline; the caller's own abort stays an AbortError
  const hang = (_url: string, init: { signal: AbortSignal }) => new Promise<never>((_, rej) => init.signal.addEventListener('abort', () => rej(Object.assign(new Error('aborted'), { name: 'AbortError' }))))
  let timedOut = ''
  try { await LQ.timedGet(hang as never, '/api/live/quotes?symbols=X', undefined, 50) } catch (e) { timedOut = (e as Error).message }
  check('L11 a hung GET becomes a feed error after its deadline', /timed out/.test(timedOut), timedOut)
  const own = new AbortController(); let name = ''
  const pending = LQ.timedGet(hang as never, '/x', own.signal, 5000).catch(e => { name = (e as Error).name })
  own.abort(); await pending
  check('L11 negative control: the caller aborting (unmount) is still an AbortError, not a feed error', name === 'AbortError', name)
  check('L11 the hook re-derives on a shared 1 s clock, not only on responses', /useSyncExternalStore\(key \? subscribeClock : noopSubscribe, clockNow, clockServer\)/.test(fs.readFileSync(path.join(UI, 'lib', 'liveQuotes.ts'), 'utf8'))
    && LQ._clockForTest().CLOCK_MS === 1000)
  // a stored EOD row during the session carries the previous session's move
  const eodStale = { price: 1500, change_pct: -3.1, change: -48, prev_close: 1548, state: 'stale', source: 'eod' }
  const nseLive = { price: 1530, change_pct: 2.0, change: 30, prev_close: 1500, state: 'delayed', source: 'nse_api' }
  check('L12 isStaleEod flags only the in-session EOD row', LQ.isStaleEod(eodStale) && !LQ.isStaleEod(nseLive) && !LQ.isStaleEod({ source: 'eod', state: 'closed' }))
  const ov = LQ.overlayQuote({ price: 1490, change_pct: 2.0, change: 29 }, eodStale as never) as Record<string, unknown>
  check('L12 overlay keeps the base row\'s change when the live row is an in-session EOD row', ov.change_pct === 2.0 && ov.change === 29 && ov.price === 1500, ov)
  const ov2 = LQ.overlayQuote({ price: 1490, change_pct: 1.0 }, nseLive as never) as Record<string, unknown>
  check('L12 negative control: a delayed NSE row does overwrite the change', ov2.change_pct === 2.0, ov2)
  const lvl = M.liveLevel({ last: 24000, change_pct: 1.5 }, eodStale as never)
  check('L12 liveLevel ignores an in-session EOD row (the payload\'s NSE move stands)', lvl.change_pct === 1.5 && lvl.fromService === false, lvl)
  check('L12 negative control: a delayed NSE row is used', M.liveLevel({ last: 24000, change_pct: 1.5 }, nseLive as never).fromService === true)
  const map = fs.readFileSync(path.join(UI, 'components', 'MarketMap.tsx'), 'utf8')
  check('L12 market map tiles never colour by an in-session EOD move', /!\(q\.source === 'eod' && q\.state === 'stale'\)\) svcChg\[s\] = q\.change_pct/.test(map))
  // the stored 15-minute IV pilot is never LIVE
  const iv = fs.readFileSync(path.join(UI, 'components', 'vol', 'IvLivePath.tsx'), 'utf8')
  check('L13 IV live path: stored 15-min snapshots are DELAYED with their age, never LIVE', /state: 'delayed', source: src, asOf: lastTs, ageS/.test(iv) && !/state: 'live'/.test(iv))
  check('L13 negative control: the old literal is caught', /state: 'live'/.test("return { state: 'live', source: src, asOf: lastTs }"))
}

// ── round 2 (L2-UI, 5 Nov): COMP on NSE closes, OSTR seeded from the live chain, WTCH / news dock on the NSE base ──
// L20 COMP (components/CompareCloses.ts)  L21 OSTR (components/strategySeed.ts)  L22 the NSE base layer (news/nseBase.ts)
// L23 the dock's NSE chart (news/nseChart.ts)  L24 static: no Yahoo request for an NSE row on COMP / WTCH / the dock
type CmpMod = typeof import('../CompareCloses')
type SeedMod = typeof import('../strategySeed')
type BaseMod = typeof import('../news/nseBase')
type NChartMod = typeof import('../news/nseChart')
const CMP = (await import(new URL('../CompareCloses.ts', import.meta.url).href)) as CmpMod
const SEED = (await import(new URL('../strategySeed.ts', import.meta.url).href)) as SeedMod
const NB = (await import(new URL('../news/nseBase.ts', import.meta.url).href)) as BaseMod
const NC = (await import(new URL('../news/nseChart.ts', import.meta.url).href)) as NChartMod
{
  // L20: which source each compared symbol reads
  check('L20 NSE codes go to the closes route', ['TCS', 'M&M', 'BAJAJ-AUTO'].every(s => CMP.seriesSource(s) === 'nse_closes'))
  check('L20 the benchmark reads the stored index closes, a ^ or dotted code Yahoo, junk nowhere',
    CMP.seriesSource('^NSEI') === 'index_store' && CMP.seriesSource('^GSPC') === 'yahoo' && CMP.seriesSource('RELIANCE.BO') === 'yahoo' && CMP.seriesSource('BAD SYM') === 'invalid')
  check('L20 negative control: an NSE code is never a Yahoo symbol', !['TCS', 'INFY', 'M&M'].some(s => CMP.seriesSource(s) === 'yahoo'))
  check('L20 period start in calendar days', CMP.periodStart('2026-11-05', '1y') === '2025-11-04' && CMP.periodStart('2026-11-05', '1mo') === '2026-10-05', CMP.periodStart('2026-11-05', '1y'))
  const body = { as_of: '2026-11-04', source: 'nse_bhavcopy', series: {
    TCS: [{ date: '2026-11-04', close: 4000 }, { date: '2026-11-03', close: 3990 }, { date: 'bad', close: 1 }, { date: '2026-11-02', close: -5 }, { date: '2025-01-02', close: 3000 }],
    'INFY.NS': [{ date: '2026-11-04', close: '1500.5' }, { date: '2026-11-03', close: 1490 }],
  } }
  const got = CMP.seriesFromCloses(body, ['TCS', 'INFY', 'HCLTECH'], '2026-10-05')
  check('L20 closes → ascending, finite, positive, dated, trimmed to the period', JSON.stringify(got.TCS) === JSON.stringify({ sym: 'TCS', dates: ['2026-11-03', '2026-11-04'], close: [3990, 4000] }), got.TCS)
  check('L20 a .NS key and a string close are read', got.INFY?.close[1] === 1500.5, got.INFY)
  check('L20 negative control: a symbol the route lacks has no series (never filled from another source)', got.HCLTECH === null)
  const short = CMP.cleanSeries('NIFTY 50', [{ date: '2026-11-03', close: 24000 }, { date: '2026-11-04', close: 24100 }], '2025-11-04')
  const store = CMP.cleanSeries('^NSEI', [{ date: '2025-11-04', close: 22000 }, { date: '2026-11-04', close: 24100 }], '2025-11-04')
  const b1 = CMP.pickBench(short, store, '2025-11-04')
  check('L20 a 2-session NSE index file does not make a 1-year benchmark: the stored closes stand in', b1.source === 'index_store' && b1.series?.dates[0] === '2025-11-04', b1)
  const b2 = CMP.pickBench(store, null, '2025-11-04')
  check('L20 NSE\'s daily index file wins once it covers the period', b2.source === 'nse_index_file' && b2.series?.sym === '^NSEI', b2)
  check('L20 coversPeriod negative control', !CMP.coversPeriod(short, '2025-11-04') && CMP.coversPeriod(store, '2025-11-04'))
  const data = { '^NSEI': store!, TCS: got.TCS!, '^GSPC': { sym: '^GSPC', dates: ['2026-11-04'], close: [6000] } }
  const src = CMP.compareSource(data, { bench: 'nse_index_file', now: new Date(Date.UTC(2026, 10, 5, 6)) })
  const chip = S.sourceChipText(src, new Date(Date.UTC(2026, 10, 5, 6)))
  check('L20 the chip is EOD · <last NSE close>, source NSE closes, never live', src.state === 'delayed' && src.source === 'NSE closes' && chip.label === 'EOD · 04 NOV', [src, chip])
  check('L20 the chip names the Yahoo symbols only for non-NSE codes', /\^GSPC: not NSE codes, Yahoo/.test(src.hint ?? '') && !/TCS[^,]*Yahoo/.test(src.hint ?? ''), src.hint)
  check('L20 STALE past 4 days', CMP.compareSource({ TCS: got.TCS! }, { now: new Date(Date.UTC(2026, 10, 12, 6)) }).state === 'stale')
  check('L20 header label', CMP.closesLabel('2026-11-04') === 'NSE closes · 04 Nov 2026' && CMP.closesLabel(null) === 'NSE closes · none stored')
  check('L20 the stored-index chip says it may hold Yahoo-ingested rows', /may be Yahoo-ingested/.test(CMP.compareSource(data, { bench: 'index_store' }).hint ?? ''))
}
{
  // L21: OSTR's seed
  const at = (h: number, m: number, d = 5) => Date.UTC(2026, 10, d, h, m) - 330 * 60_000      // IST wall → epoch ms
  check('L21 the service market state picks the seed', SEED.seedMode({ marketState: 'open', calendarOpen: false, nowMs: at(8, 0) }) === 'live'
    && SEED.seedMode({ marketState: 'closed', calendarOpen: true, nowMs: at(11, 0) }) === 'eod' && SEED.seedMode({ marketState: 'pre-open', calendarOpen: true, nowMs: at(9, 5) }) === 'eod')
  check('L21 without it, the calendar from 09:15 (options have no pre-open)', SEED.seedMode({ marketState: null, calendarOpen: true, nowMs: at(10, 20) }) === 'live'
    && SEED.seedMode({ marketState: null, calendarOpen: true, nowMs: at(9, 5) }) === 'eod' && SEED.seedMode({ marketState: null, calendarOpen: false, nowMs: at(10, 20) }) === 'eod')
  const liveChain = { live: true, as_of: '05-Nov-2026 10:19:30', date: '2026-11-05' }
  const s1 = SEED.chainSeedSource(liveChain, { mode: 'live', nowMs: at(10, 20, 5) + 30_000 })
  check('L21 the live chain reads DELAYED · NSE · <age> from its own stamp', s1.state === 'delayed' && S.sourceChipText(s1).label === 'DELAYED · NSE · 60s', [s1, S.sourceChipText(s1)])
  const fresh = SEED.chainSeedSource({ ...liveChain, as_of: '05-Nov-2026 10:20:29' }, { mode: 'live', nowMs: at(10, 20, 5) + 30_000 })
  check('L21 negative control: even a 1 s old NSE chain is never LIVE', fresh.state === 'delayed', fresh)
  check('L21 a seed 11 min old is STALE', SEED.chainSeedSource(liveChain, { mode: 'live', nowMs: at(10, 31) }).state === 'stale')
  const fb = SEED.chainSeedSource({ date: '2026-11-04' }, { mode: 'live', nowMs: at(10, 20), liveNote: 'live chain unavailable (HTTP 502)' })
  check('L21 the EOD fallback in session reads EOD · <date> with the reason', S.sourceChipText(fb, new Date(at(10, 20))).label === 'EOD · 04 NOV' && fb.hint === 'live chain unavailable (HTTP 502)', fb)
  const cl = SEED.chainSeedSource({ date: '2026-11-05' }, { mode: 'eod', nowMs: at(20, 30), marketState: 'closed', sessionDate: '2026-11-05' })
  check('L21 after the close the bhavcopy chain reads CLOSE · <date>', cl.state === 'closed' && S.sourceChipText(cl).label === 'CLOSE · 05 NOV', cl)
  const nf = SEED.chainSeedSource({ date: '2026-11-04' }, { mode: 'eod', nowMs: at(16, 0), marketState: 'closed', sessionDate: '2026-11-05' })
  check('L21 the session ended without its file: STALE, says which file is missing', nf.state === 'stale' && /2026-11-05 F&O bhavcopy is not stored yet/.test(nf.hint ?? ''), nf)
  const am = SEED.chainSeedSource({ date: '2026-11-05' }, { mode: 'eod', nowMs: at(8, 30, 6), marketState: 'closed', sessionDate: '2026-11-05' })
  check('L21 negative control: before the next open the last session\'s file is CLOSE, not stale', am.state === 'closed', am)
  check('L21 a file older than 4 days is STALE', SEED.chainSeedSource({ date: '2026-10-28' }, { mode: 'eod', nowMs: at(8, 30, 6), marketState: 'closed', sessionDate: '2026-11-05' }).state === 'stale')
  check('L21 stamp clock + drift', SEED.stampClock('05-Nov-2026 10:19:30') === '10:19:30' && Math.abs((SEED.spotDriftPct(24000, 24120) ?? 0) - 0.5) < 1e-9 && SEED.spotDriftPct(null, 1) === null)
  const sb = code(read('components/StrategyBuilder.tsx'))
  check('L21 OSTR asks the live chain only in session, EOD otherwise and as the fallback',
    /mode === 'live'\s*\?\s*getOptionChainLive\(symbol, expiry \?\? undefined\)/.test(sb) && /return eod\(\)/.test(sb) && /modeNow\.current\(\)/.test(sb))
  const liveTrue = sb.match(/sourceOf\([^)]*live:\s*true[^)]*\)/g) ?? []
  check('L21 the legs / payoff chips come from the seed rule; the only live:true chip is the Breeze margin answer', (sb.match(/source=\{seedSrc \?\?/g) ?? []).length === 2
    && liveTrue.length === 1 && /source: 'BREEZE'/.test(liveTrue[0]), liveTrue)
  // pricing math untouched: the analyze body and the margin call read the chain's forward, never the live spot
  const analyze = sb.slice(sb.indexOf("axios.post<Analysis>('/api/options/strategy/analyze'"), sb.indexOf("}, { timeout: 15000 })"))
  check('L21 the analyze body is the pre-live one (forward from the chain, DTE + 0.5, ATM IV default)', /\bforward,\n/.test(analyze) && analyze.includes('days_to_expiry: Math.max(0, chain.days_to_expiry) + 0.5') && analyze.includes('default_iv: chain.atm_iv ?? 15'), analyze.slice(0, 200))
  check('L21 the live spot never reaches pricing or margin', !/spotNow|ulRow/.test(analyze) && !/postMargin\([^)]*spotNow/.test(sb) && /const forward = chain\?\.forward \?\? chain\?\.future \?\? chain\?\.spot \?\? null/.test(sb))
  check('L21 a calendar-chosen seed is corrected once by the service\'s first market state, never re-seeded by the clock later',
    /if \(!marketState \|\| !chain \|\| checkedSeed\.current\) return\s*checkedSeed\.current = true\s*if \(modeNow\.current\(\) !== loadedMode\) loadChain\(\)/.test(sb)
    && !/\[loadChain, marketState\]|\[marketState, loadChain\]/.test(sb))
  check('L21 negative control: the pricing scan catches a live spot in the body', /spotNow|ulRow/.test("axios.post<Analysis>('/api/options/strategy/analyze', { symbol, forward: spotNow ?? forward,"))
}
{
  // L22: the NSE base layer
  const pts = (n: number, from = 100) => Array.from({ length: n }, (_, i) => ({ date: new Date(Date.UTC(2025, 10, 5) + i * 86_400_000).toISOString().slice(0, 10), close: from + i }))
  const body = { series: { TCS: pts(250), INFY: pts(30), WIPRO: pts(250) }, meta: { TCS: { name: 'Tata Consultancy Services Limited', high: 420, low: 90, last_date: '2026-07-12' } } }
  const base = NB.nseBaseFromCloses(body, ['TCS', 'INFY.NS', 'WIPRO', 'HCLTECH'])
  check('L22 meta high / low → the 52-week range on adjusted daily bars; the name from NSE', base.TCS?.range_basis === 'high_low' && base.TCS?.high_52w === 420 && base.TCS?.name === 'Tata Consultancy Services Limited', base.TCS)
  check('L22 the spark is the last 22 closes', base.TCS?.spark.length === 22 && base.TCS?.spark[21] === 349, base.TCS?.spark.slice(-2))
  check('L22 without meta, a full year of closes gives a CLOSING range (labelled)', base.WIPRO?.range_basis === 'closes' && base.WIPRO?.high_52w === 349 && base.WIPRO?.low_52w === 100, base.WIPRO)
  check('L22 negative control: 30 sessions are not a 52-week range', base.INFY?.range_basis === null && base.INFY?.high_52w === null, base.INFY)
  check('L22 a symbol without closes has no base (never another source)', base.HCLTECH === null)
  const b: import('../news/nseBase').NseBase = { symbol: 'TCS', name: 'TCS Ltd', spark: [100, 101, 102], high_52w: 1480, low_52w: 900, range_basis: 'high_low', last_date: '2026-11-04' }
  const live = row({ symbol: 'TCS', price: 1490, change_pct: 1.2, change: 17.7, day_high: 1495, day_low: 1470 })
  const r1 = NB.nseQuoteRow('TCS', b, live)
  check('L22 the live half: price / move / day range from the hook', r1.price === 1490 && r1.change_pct === 1.2 && r1.day_high === 1495 && r1.available === true && r1.live_source === 'breeze_ws', r1)
  check('L22 today\'s live point extends the spark and the 52-week high', r1.spark?.[r1.spark.length - 1] === 1490 && r1.spark?.length === 4 && r1.high_52w === 1495 && r1.low_52w === 900, r1)
  const eod = row({ symbol: 'TCS', price: 1478, change_pct: -2.5, change: -38, source: 'eod', state: 'stale', day_high: 1500, ltt: '2026-11-04T15:30:00+05:30' })
  const r2 = NB.nseQuoteRow('TCS', b, eod)
  check('L22 negative control: an in-session EOD row never paints yesterday\'s move, spark point or range', r2.change_pct === undefined && r2.spark?.length === 3 && r2.high_52w === 1480 && r2.stale === true, r2)
  const r3 = NB.nseQuoteRow('TCS', b, undefined, 'fallback name')
  check('L22 no live row: the stored half only, not available, no price', r3.available === false && r3.price === undefined && r3.name === 'TCS Ltd' && r3.base_source === 'nse_closes', r3)
  check('L22 the name falls back to the directory without a base', NB.nseQuoteRow('TCS', null, undefined, 'Tata Consultancy').name === 'Tata Consultancy')
  const syms = ['TCS.NS', 'AAPL', 'GC=F', 'M&M.NS', 'RELIANCE.BO']
  check('L22 the 60 s Yahoo call carries non-NSE symbols only while the live service answers (ok / error / idle)',
    ['ok', 'error', 'idle', 'loading'].every(st => !NB.yahooCallSymbols(syms, st).some(y => /\.NS$/.test(y))) && NB.yahooCallSymbols(syms, 'ok').length === 3, NB.yahooCallSymbols(syms, 'ok'))
  check('L22 only a missing live route (404, not deployed) puts NSE rows on the pre-live route', NB.yahooCallSymbols(syms, 'missing').filter(y => /\.NS$/.test(y)).length === 2)
  check('L22 titles name the basis and the stored date', /adjusted NSE daily bars \(stored to 2026-11-04\)/.test(NB.baseTitles(r1).range) && /CLOSING range/.test(NB.baseTitles({ ...r1, range_basis: 'closes' }).range))
}
{
  // L23: the dock's NSE chart (a 1:1 bonus with ex-date 3 Nov: older prices × 0.5, older volume × 2)
  const rows = [
    { date: '2026-11-04', open: 995, high: 1005, low: 990, close: 1000, volume: 2000 },
    { date: '2026-11-03', open: 1000, high: 1001, low: 985, close: 990, volume: 2100, action_k: 0.5 },
    { date: '2026-11-02', open: 1990, high: 2010, low: 1980, close: 2000, volume: 1000 },
    { date: '2026-11-01', open: 1950, high: 1965, low: 1940, close: 1960, volume: 900 },
  ]
  const c = NC.adjustedDailyCandles(rows)
  check('L23 bhavcopy rows → oldest first, adjusted before the ex-date (a bonus is not a crash)', c.map(x => x.close).join() === '980,1000,990,1000' && c[1].volume === 2000 && c[2].volume === 2100, c)
  const raw = NC.adjustedDailyCandles(rows.map(r => ({ ...r, action_k: null })))
  check('L23 negative control: without the factor the old prices stay doubled', raw[1].close === 2000)
  const w = NC.weeklyCandles(NC.adjustedDailyCandles([
    { date: '2026-11-06', open: 10, high: 12, low: 9, close: 11, volume: 1 }, { date: '2026-11-05', open: 9, high: 13, low: 8, close: 10, volume: 1 },
    { date: '2026-11-03', open: 8, high: 9, low: 7, close: 9, volume: 1 }, { date: '2026-10-30', open: 7, high: 8, low: 6, close: 7, volume: 1 },
  ]))
  check('L23 weekly bars carry each week\'s last trading day, its high / low / close', w.length === 2 && new Date(w[1].time * 1000).toISOString().slice(0, 10) === '2026-11-06' && w[1].high === 13 && w[1].low === 7 && w[1].close === 11 && w[1].volume === 3, w)
  check('L23 RSI of a straight rise is 100; SMA', NC.rsiSeries(Array.from({ length: 20 }, (_, i) => i + 1))[19] === 100 && NC.smaSeries([1, 2, 3, 4], 2)[3] === 3.5)
  const many = Array.from({ length: 300 }, (_, i) => ({ date: new Date(Date.UTC(2026, 10, 4) - i * 86_400_000).toISOString().slice(0, 10), open: 100, high: 101, low: 99, close: 100 + (299 - i) * 0.1, volume: 10 }))
  const d1 = NC.nseDailyChart('TCS', many, '1mo')
  check('L23 a daily range: ≤ 22 candles, EOD bhavcopy, no quote of its own', !!d1 && d1.candles.length === 22 && d1.intraday === false && d1.source_kind === 'nse_bhavcopy' && d1.quote.available === false && d1.last_date === '2026-11-04', d1 && { n: d1.candles.length, last: d1.last_date })
  check('L23 stats always from daily bars (SMA 200 known on a 1M view)', !!d1 && d1.stats.sma200 != null && d1.stats.history_days === 300 && d1.sma200.length === 22)
  check('L23 5Y is weekly', NC.nseDailyChart('TCS', many, '5y')?.interval === '1wk')
  check('L23 1D: an empty tick store is no chart (never a Yahoo bar)', NC.nseIntradayChart('TCS', '2026-11-05', [], many) === null)
  const i1 = NC.nseIntradayChart('TCS', '2026-11-05', [{ t: '09:15', o: 1, h: 2, l: 1, c: 2, v: 5 }, { t: '09:20', o: 2, h: 3, l: 2, c: 3, v: 5 }], many)
  check('L23 1D from the tick store on an IST wall-clock axis', !!i1 && i1.intraday && i1.source_kind === 'tick_store' && new Date(i1.candles[0].time * 1000).toISOString().slice(11, 16) === '09:15', i1?.candles[0])
}
{
  // L24: no Yahoo request for an NSE row (static, comments stripped), with negative controls on the old forms
  const cp = code(read('components/Compare.tsx')), wm = code(read('components/WatchMonitor.tsx')), nt = code(read('components/news/NewsTerminal.tsx'))
  const yahooNs = /`\$\{s\}\.NS`/
  check('L24 COMP: NSE codes read getMarketCloses; Yahoo only through the non-NSE list', /getMarketCloses\(nse, PERIOD_DAYS\[p\]\)/.test(cp) && /other\.map\(s => getNewsChart\(s, p\)/.test(cp) && !yahooNs.test(cp), null)
  check('L24 negative control: the old COMP mapping is caught', yahooNs.test("const yahoo = (s: string) => (s.startsWith('^') || s.includes('.') ? s : `${s}.NS`)"))
  check('L24 WTCH: the 60 s quotes call carries yahooCallSymbols only; NSE rows are built from the base + hook',
    /const callKey = yahooCallSymbols\(/.test(wm) && /getNewsQuotes\(syms\.slice\(i, i \+ 60\)\)/.test(wm) && /const syms = callKey \? callKey\.split/.test(wm) && /nseQuoteRow\(r\.sym, nseBase\.base\[r\.sym\], liveQ\.quotes\[r\.sym\]/.test(wm))
  check('L24 negative control: the old WTCH call over every row is caught', !/const syms = callKey/.test('const syms = yahooKey ? yahooKey.split(\',\') : []'))
  check('L24 news dock: quotes through yahooCallSymbols; the TERMINAL chart of an NSE pick from NSE bars',
    /getNewsQuotes\(callKey\.split\(','\)\)/.test(nt) && /selNse \? nseChartFor\(selNse, effRange\) : getNewsChart\(selected, effRange\)/.test(nt) && !/getNewsQuotes\(symbolsKey/.test(nt))
  check('L24 negative control: the old dock calls are caught', /getNewsQuotes\(symbolsKey/.test("getNewsQuotes(symbolsKey.split(','))") && !/selNse \?/.test('getNewsChart(selected, range)'))
  const pure = ['components/news/nseBase.ts', 'components/news/useNseBase.ts', 'components/news/nseChart.ts', 'components/CompareCloses.ts', 'components/strategySeed.ts'].map(f => [f, code(read(f))] as const)
  const leaky = pure.filter(([, t]) => /news-scanner|getNewsQuotes|getNewsChart|finance\.yahoo|yfinance/i.test(t)).map(([f]) => f)
  check('L24 the new NSE modules never reach a Yahoo path', leaky.length === 0, leaky)
  check('L24 every pane keeps its live chip (sourceFor / the hook\'s source)', /liveQ\.sourceFor\(/.test(wm) && /liveNse\.sourceFor\(/.test(nt) && /ul\.sourceFor\(/.test(code(read('components/StrategyBuilder.tsx'))))
}

console.log(`live.check: ${passed} passed, ${failed} failed`)
if (failed) process.exit(1)

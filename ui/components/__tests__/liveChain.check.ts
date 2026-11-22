/**
 * Live option chain checks (22 Nov 2026; OMON / OSTR / BRF on GET /api/live/option-chain ← data-service live_chain.py):
 * the chain chip from the payload's feed block, the OI chip, one strike side's feed (dimming + hover), the poll cadence,
 * the session rule, the receipt normaliser, OSTR's seed-age rule — each with a negative control — plus static wiring
 * scans of the three pages. Plain node ≥ 23.6 (type stripping, no deps):
 *
 *   node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON ui/components/__tests__/liveChain.check.ts
 *
 *  C1 chain chip: LIVE · BREEZE · <age> · n/m LIVE only while the band's freshest Breeze-PRICED tick (price_source) is
 *     seconds old, n = the Breeze-priced sides; a stalled window, a quiet band, untraded strikes, a skewed clock →
 *     not LIVE; STALE past 10 min; no priced tick → DELAYED · NSE / EOD (an NSE outage: the bhavcopy with its age and
 *     NSE's error); CLOSE after the session
 *  C2 OI chip (PCR / walls): the base frame's chip, never LIVE
 *  C3 one strike side, by price_source: a Breeze trade full strength with its age; NSE / bhavcopy / an untraded band
 *     strike (OI live, price NSE's) dimmed with the price's source, age and why
 *  C4 OSTR's seed is a snapshot: LIVE ≤ 10 s past its as_of, then DELAYED / STALE; NSE's chain alone never LIVE
 *  C5 OMON's cadence: 2.5 s while the live chain can tick, 30 s on NSE alone / no engine
 *  C6 the session rule: the service's market state, else the calendar from 09:15 IST — never the browser's local clock
 *  C7 the receipt normaliser: received_at + the master's listed expiries
 *  C8 static: OMON / OSTR / BRF wiring, BRF's walls in side colours, the route the getter asks is the one ui-api serves
 */
import * as fs from 'node:fs'
import * as nodeModule from 'node:module'
import * as path from 'node:path'

;(nodeModule as unknown as { registerHooks?: (h: unknown) => void }).registerHooks?.({
  resolve(spec: string, ctx: unknown, next: (s: string, c: unknown) => unknown) {
    try { return next(spec, ctx) } catch (e) {
      if (/^(\.|\/|file:)/.test(spec) && !/\.[cm]?[jt]sx?$/.test(spec)) return next(`${spec}.ts`, ctx)
      throw e
    }
  },
})

type ModelMod = typeof import('../liveModel')
type SeedMod = typeof import('../strategySeed')
type SourceMod = typeof import('../terminal/source')
type LQMod = typeof import('../../lib/liveQuotes')
const M = (await import(new URL('../liveModel.ts', import.meta.url).href)) as ModelMod
const SEED = (await import(new URL('../strategySeed.ts', import.meta.url).href)) as SeedMod
const S = (await import(new URL('../terminal/source.ts', import.meta.url).href)) as SourceMod
const LQ = (await import(new URL('../../lib/liveQuotes.ts', import.meta.url).href)) as LQMod

const UI = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..')
const read = (rel: string): string => fs.readFileSync(path.join(UI, rel), 'utf8')
const code = (s: string): string =>
  s.replace(/\/\*[\s\S]*?\*\//g, m => m.replace(/[^\n]/g, ' ')).replace(/(^|[^:'"`\\])\/\/[^\n]*/g, '$1')

let failed = 0, passed = 0
const check = (name: string, cond: unknown, extra?: unknown): void => {
  if (cond) { passed++; return }
  failed++
  console.error(`FAIL ${name}${extra !== undefined ? ` :: ${JSON.stringify(extra)}` : ''}`)
}

// Mon 23 Nov 2026 10:20:30 IST
const NOW = Date.UTC(2026, 10, 23, 4, 50, 30)
const iso = (ms: number) => `${new Date(ms + 330 * 60_000).toISOString().slice(0, 19)}+05:30`
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const nseStamp = (ms: number) => { const d = new Date(ms + 330 * 60_000); return `${String(d.getUTCDate()).padStart(2, '0')}-${MON[d.getUTCMonth()]}-${d.getUTCFullYear()} ${d.toISOString().slice(11, 19)}` }
const label = (i: import('../terminal/source').SourceInfo, at = NOW) => S.sourceChipText(i, new Date(at)).label

type Side = import('../liveModel').LiveChainSideLike
/** a strike side; `price_source` follows the contract: breeze_ws for a traded live side, the base frame's otherwise */
const side = (source: string, age_s: number, tick_state: string, over: Partial<Side> = {}): Side =>
  ({ price: 100, source, price_source: source, age_s, tick_state, ...over })
/** a live chain payload as ui-api serves it (2 strikes; the band holds 24400), received at `at` */
function chain(at: number, over: Record<string, unknown> = {}, feed: Record<string, unknown> = {}, rows?: unknown) {
  return {
    symbol: 'NIFTY', live: true, date: '2026-11-23', expiry: '2026-11-25', expiries: ['2026-11-25'], as_of: iso(at), base: 'nse',
    served_by: 'live_chain', fallback_reason: null, received_at: at,
    rows: (rows ?? [
      { strike: 24400, band: true, ce: side('breeze_ws', 0.6, 'live', { bid: 120.4, ask: 120.6, ltt: iso(at - 1_000) }), pe: side('nse', 48, 'waiting_first_tick') },
      { strike: 24500, band: false, ce: side('nse', 48, 'outside_band'), pe: side('nse', 48, 'outside_band') },
    ]) as { strike: number; band?: boolean; ce: Side; pe: Side }[],
    feed: { as_of: iso(at), nse_as_of: nseStamp(at - 48_000), eod_date: null, base: 'nse', base_error: null, base_age_s: 48,
            counts: { breeze_ws: 1, nse: 3, eod: 0 }, band: { width: 10 },
            expiry: { master_expiries: ['2026-12-02', '2026-11-25', '2026-12-30'] },
            subscription: { engine: 'LIVE', enabled: true, healthy: true, waiting_first_tick: 1, over_cap: 0 }, ...feed },
    ...over,
  }
}
const OPEN = { marketOpen: true }

// ── C1 the chain chip ───────────────────────────────────────────────────────────────────────────────────────────────
{
  const live = M.liveChainSource(chain(NOW), { now: NOW, ...OPEN })
  check('C1 a fresh band: LIVE · BREEZE · <age> · <live>/<all> LIVE', live.state === 'live' && label(live) === 'LIVE · BREEZE · 1s · 1/4 LIVE', [live, label(live)])
  check('C1 the hint names the Breeze-priced sides, the band and the other sides\' price source with its age',
    /1 of 4 strike sides priced from Breeze trades \(ATM ± 10 strikes\)/.test(live.hint ?? '') && /the other 3 priced from NSE's option chain \(v3\), 48s old/.test(live.hint ?? ''), live.hint)
  // 23 Nov: the LIVE count is the sides whose PRICE is a Breeze trade (price_source), not every side on the socket
  const mixed = [
    { strike: 24400, band: true, ce: side('breeze_ws', 0.6, 'live'), pe: side('breeze_ws', 0.4, 'live', { price_source: 'nse' }) },
    { strike: 24450, band: true, ce: side('breeze_ws', 1.2, 'live'), pe: side('breeze_ws', 2, 'live', { price_source: 'nse' }) },
    { strike: 24500, band: false, ce: side('nse', 48, 'outside_band'), pe: side('nse', 48, 'outside_band') },
  ]
  const cm = M.liveChainSource(chain(NOW, {}, { counts: { breeze_ws: 4, nse: 2, eod: 0 } }, mixed), { now: NOW, ...OPEN })
  check('C1 the LIVE count is price_source = breeze_ws (2 traded of 6), not the 4 sides on the socket', label(cm) === 'LIVE · BREEZE · 1s · 2/6 LIVE'
    && /2 of them on the socket without a trade today/.test(cm.hint ?? ''), [label(cm), cm.hint])
  check('C1 negative control: counting by source would have said 4/6', mixed.flatMap(r => [r.ce, r.pe]).filter(x => x.source === 'breeze_ws').length === 4)
  const untradedOnly = [{ strike: 24400, band: true, ce: side('breeze_ws', 0.3, 'live', { price_source: 'nse' }), pe: side('breeze_ws', 0.3, 'live', { price_source: 'nse' }) }]
  const uo = M.liveChainSource(chain(NOW, {}, { counts: { breeze_ws: 2, nse: 0, eod: 0 } }, untradedOnly), { now: NOW, ...OPEN })
  check('C1 negative control: fresh ticks on untraded strikes (OI / book only) never make the chain LIVE', uo.state === 'delayed' && label(uo) === 'DELAYED · NSE · 48s'
    && /2 sides tick on the socket \(OI \/ book live\) but none has traded today/.test(uo.hint ?? ''), [label(uo), uo.hint])
  const noPs = [{ strike: 24400, band: true, ce: { price: 100, source: 'breeze_ws', age_s: 0.5, tick_state: 'live' }, pe: side('nse', 48, 'outside_band') }]
  check('C1 negative control: a side without price_source is never counted Breeze-priced', M.liveChainSource(chain(NOW, {}, {}, noPs), { now: NOW, ...OPEN }).state !== 'live')
  const stalled = M.liveChainSource(chain(NOW - 15_000), { now: NOW, ...OPEN })
  check('C1 negative control: the same chain this window received 15 s ago is DELAYED, never LIVE', stalled.state === 'delayed' && /received 15s ago/.test(stalled.hint ?? '')
    && label(stalled) === 'DELAYED · BREEZE · 16s · 1/4 LIVE', [stalled.state, label(stalled), stalled.hint])
  const quietRows = [{ strike: 24400, band: true, ce: side('breeze_ws', 40, 'quiet'), pe: side('nse', 48, 'waiting_first_tick') }]
  const quiet = M.liveChainSource(chain(NOW, {}, { counts: { breeze_ws: 1, nse: 1, eod: 0 } }, quietRows), { now: NOW, ...OPEN })
  check('C1 negative control: a band whose freshest tick is 40 s old (quiet) is DELAYED with why', quiet.state === 'delayed' && /no Breeze tick on the band's traded strikes for 40s/.test(quiet.hint ?? ''), quiet)
  const q6 = M.liveChainSource(chain(NOW, {}, { counts: { breeze_ws: 1, nse: 1, eod: 0 } }, [{ strike: 24400, band: true, ce: side('breeze_ws', 6, 'quiet'), pe: side('nse', 48, 'outside_band') }]), { now: NOW, ...OPEN })
  check('C1 an all-quiet band within 10 s carries the quiet cue (LIVE·q)', q6.state === 'live' && q6.quiet === true && label(q6).startsWith('LIVE·q · BREEZE · 6s'), label(q6))
  const edge = (age: number) => M.liveChainSource(chain(NOW, {}, {}, [{ strike: 24400, band: true, ce: side('breeze_ws', age, 'live'), pe: side('nse', 48, 'outside_band') }]), { now: NOW, ...OPEN }).state
  check('C1 the bound is CHAIN_LIVE_MAX_S on the freshest tick now (10 s live, 10.5 s not)', edge(10) === 'live' && edge(10.5) === 'delayed', [edge(10), edge(10.5)])
  check('C1 the bound is the live quote rows\' own (LOCAL_LIVE_MAX_S), not a second number', M.CHAIN_LIVE_MAX_S === LQ.LOCAL_LIVE_MAX_S, [M.CHAIN_LIVE_MAX_S, LQ.LOCAL_LIVE_MAX_S])
  const skewAhead = M.liveChainSource({ ...chain(NOW - 30_000), received_at: NOW }, { now: NOW, ...OPEN })
  const skewBehind = M.liveChainSource({ ...chain(NOW), received_at: NOW - 30_000 }, { now: NOW, ...OPEN })
  check('C1 negative control: either clock saying 30 s old keeps it off LIVE (server as_of or this window\'s receipt)', skewAhead.state === 'delayed' && skewBehind.state === 'delayed', [skewAhead.state, skewBehind.state])
  const old = M.liveChainSource(chain(NOW - 11 * 60_000), { now: NOW, ...OPEN })
  check('C1 STALE past 10 min', old.state === 'stale', old)
  const noTick = chain(NOW, {}, { counts: { breeze_ws: 0, nse: 4, eod: 0 }, subscription: { engine: 'LIVE', enabled: true, healthy: true, waiting_first_tick: 4, over_cap: 0 } },
    [{ strike: 24400, band: true, ce: side('nse', 48, 'waiting_first_tick'), pe: side('nse', 48, 'waiting_first_tick') }])
  const nse = M.liveChainSource(noTick, { now: NOW, ...OPEN })
  check('C1 nothing ticking: DELAYED · NSE · <age> from NSE\'s own stamp, saying why', nse.state === 'delayed' && label(nse) === 'DELAYED · NSE · 48s' && /4 contracts subscribed, waiting for their first tick/.test(nse.hint ?? ''), [label(nse), nse.hint])
  const fresh = M.liveChainSource({ ...noTick, feed: { ...noTick.feed, nse_as_of: nseStamp(NOW - 1_000) } }, { now: NOW, ...OPEN })
  check('C1 negative control: a 1 s old NSE frame with no tick is never LIVE', fresh.state === 'delayed', fresh)
  // an NSE outage (data-service remembers the failure 30 s): base 'eod' + base_error
  const outage = { base: 'eod', eod_date: '2026-11-20', nse_as_of: null, base_error: 'NSE is throttling us', base_age_s: 240_000, counts: { breeze_ws: 0, nse: 0, eod: 4 } }
  const eod = M.liveChainSource(chain(NOW, {}, outage, [{ strike: 24400, band: true, ce: side('eod', 240_000, 'feed_off'), pe: side('eod', 240_000, 'feed_off') }]), { now: NOW, ...OPEN })
  check('C1 an NSE outage with no tick: DELAYED · EOD · <bhavcopy date>, NSE\'s error and the age on hover', eod.state === 'delayed' && label(eod) === 'EOD · 20 NOV'
    && /NSE's option chain failed \(NSE is throttling us\): the stored F&O bhavcopy stands in · 2\.8 d old/.test(eod.hint ?? ''), [eod.state, label(eod), eod.hint])
  check('C1 negative control: the outage chip is never LIVE and never NSE', eod.state !== 'live' && eod.source === 'NSE F&O bhavcopy')
  const outageLive = M.liveChainSource(chain(NOW, {}, { ...outage, counts: { breeze_ws: 1, nse: 0, eod: 3 } },
    [{ strike: 24400, band: true, ce: side('breeze_ws', 0.5, 'live'), pe: side('eod', 240_000, 'feed_off') }]), { now: NOW, ...OPEN })
  check('C1 an NSE outage with Breeze trades on the band: LIVE on those, the rest named as the bhavcopy with its age', label(outageLive) === 'LIVE · BREEZE · 1s · 1/2 LIVE'
    && /the other 1 priced from the 2026-11-20 F&O bhavcopy, 2\.8 d old/.test(outageLive.hint ?? ''), [label(outageLive), outageLive.hint])
  const closed = M.liveChainSource(chain(NOW), { now: NOW, marketOpen: false })
  check('C1 after the session: CLOSE · <session>, even with Breeze sides', closed.state === 'closed' && label(closed) === 'CLOSE · 23 NOV', label(closed))
  const fb = M.liveChainSource({ live: true, date: '2026-11-23', as_of: nseStamp(NOW - 50_000), rows: [], served_by: 'nse_fallback', fallback_reason: 'data-service has no /live/option-chain yet (HTTP 404: not deployed)' }, { now: NOW, ...OPEN })
  check('C1 ui-api\'s NSE fallback: DELAYED · NSE · <age>, the fallback reason in the hint', label(fb) === 'DELAYED · NSE · 50s' && /not deployed/.test(fb.hint ?? ''), [label(fb), fb.hint])
  const fbFeed = M.liveChainSource({ ...chain(NOW), served_by: 'nse_fallback' }, { now: NOW, ...OPEN })
  check('C1 negative control: a body marked nse_fallback is never read as the live chain, whatever it carries', fbFeed.state !== 'live', fbFeed)
  const eodChain = M.liveChainSource({ live: false, date: '2026-11-20', rows: [] }, { now: NOW, ...OPEN })
  check('C1 the end-of-day chain: its date', label(eodChain) === 'EOD · 20 NOV', label(eodChain))
}

// ── C2 the OI chip (PCR / walls) ────────────────────────────────────────────────────────────────────────────────────
{
  const c = chain(NOW)
  const oi = M.chainOiSource(c, { now: NOW, ...OPEN })
  check('C2 PCR / walls on a ticking chain keep the base frame\'s chip: DELAYED · NSE · <age>', oi.state === 'delayed' && label(oi) === 'DELAYED · NSE · 48s' && /PCR and OI walls/.test(oi.hint ?? ''), [label(oi), oi.hint])
  check('C2 negative control: the chain chip of the same payload is LIVE (the OI rule is what differs)', M.liveChainSource(c, { now: NOW, ...OPEN }).state === 'live')
  const oiEod = M.chainOiSource(chain(NOW, {}, { base: 'eod', eod_date: '2026-11-20' }), { now: NOW, ...OPEN })
  check('C2 on an EOD base: EOD · <date>; after the close: CLOSE', label(oiEod) === 'EOD · 20 NOV' && M.chainOiSource(c, { now: NOW, marketOpen: false }).state === 'closed', label(oiEod))
}

// ── C3 one strike side ──────────────────────────────────────────────────────────────────────────────────────────────
{
  const c = chain(NOW)
  const br = M.chainSideFeed(c.rows[0].ce, c, { now: NOW + 2_000, ...OPEN })
  check('C3 a Breeze tick: full strength, its age now, last trade and book on hover', !!br && br.dim === false && /Breeze websocket · tick 3s old · last trade 10:20:29 IST · bid 120.40 \/ ask 120.60/.test(br.title), br?.title)
  check('C3 its own chip (OVME): LIVE · BREEZE while seconds old, DELAYED after', br?.info.state === 'live' && M.chainSideFeed(c.rows[0].ce, c, { now: NOW + 12_000, ...OPEN })?.info.state === 'delayed')
  const out = M.chainSideFeed(c.rows[1].ce, c, { now: NOW, ...OPEN })
  check('C3 an NSE side outside the band: dimmed, source + age + why', !!out && out.dim && /^NSE's option chain \(v3\) · 48s old · not live: outside the live band \(ATM ± 10 strikes\)$/.test(out.title), out?.title)
  check('C3 negative control: an NSE side\'s own chip is never LIVE', out?.info.state === 'delayed', out?.info)
  const waiting = M.chainSideFeed(c.rows[0].pe, c, { now: NOW, ...OPEN })
  check('C3 a band side waiting for its first tick says so', !!waiting && waiting.dim && /subscribed, waiting for its first tick/.test(waiting.title), waiting?.title)
  const ce = chain(NOW, {}, { base: 'eod', eod_date: '2026-11-20' })
  const e = M.chainSideFeed(side('eod', 240_000, 'feed_off'), ce, { now: NOW, ...OPEN })
  check('C3 a bhavcopy side: dimmed, names the file\'s date', !!e && e.dim && /^the 2026-11-20 F&O bhavcopy · not live: the websocket is off$/.test(e.title) && label(e.info) === 'EOD · 20 NOV', [e?.title, e && label(e.info)])
  const eo = M.chainSideFeed(side('eod', 240_000, 'feed_off'), chain(NOW, {}, { base: 'eod', eod_date: '2026-11-20', base_error: 'NSE is throttling us' }), { now: NOW, ...OPEN })
  check('C3 during an NSE outage the bhavcopy side says NSE\'s chain is unavailable', !!eo && /^the 2026-11-20 F&O bhavcopy \(NSE's chain unavailable\) · not live/.test(eo.title), eo?.title)
  // 23 Nov: a band strike on the socket that has not traded today: OI / book live, PRICE still NSE's → dimmed, says both
  const ut = M.chainSideFeed(side('breeze_ws', 0.8, 'live', { price_source: 'nse', bid: 99.5, ask: 101 }), c, { now: NOW, ...OPEN })
  check('C3 an untraded band strike is DIMMED: price from NSE with its age, OI / book from the live tick', !!ut && ut.dim
    && /^price: NSE's option chain \(v3\) · 48s old — no trade today on the Breeze websocket · OI, book and volume: Breeze tick 1s old · bid 99\.50 \/ ask 101\.00$/.test(ut.title), ut?.title)
  check('C3 its price chip (OVME) is NSE\'s, never LIVE', ut?.info.state === 'delayed' && label(ut!.info) === 'DELAYED · NSE · 48s', ut && label(ut.info))
  check('C3 negative control: dimming by source alone would have shown it at full strength', side('breeze_ws', 0.8, 'live', { price_source: 'nse' }).source === 'breeze_ws')
  check('C3 negative control: an EOD chain or NSE\'s fallback has no per-side feed (one source, the chip says it)',
    M.chainSideFeed(side('nse', 1, 'live'), { live: false, date: '2026-11-20', rows: [] }, { now: NOW, ...OPEN }) === null
    && M.chainSideFeed(c.rows[0].ce, { ...c, served_by: 'nse_fallback' }, { now: NOW, ...OPEN }) === null)
}

// ── C4 OSTR's seed is a snapshot ────────────────────────────────────────────────────────────────────────────────────
{
  const seed = chain(NOW, {}, {}, [{ strike: 24400, band: true, ce: side('breeze_ws', 0, 'live'), pe: side('nse', 48, 'outside_band') }])
  const at = (dt: number) => SEED.chainSeedSource(seed, { mode: 'live', nowMs: NOW + dt, marketState: 'open' })
  check('C4 within 10 s of its as_of: LIVE · BREEZE', at(3_000).state === 'live' && label(at(3_000), NOW + 3_000).startsWith('LIVE · BREEZE · 3s'), label(at(3_000), NOW + 3_000))
  check('C4 at 9.9 s still LIVE; at 10.5 s DELAYED (a seed is a snapshot)', at(9_900).state === 'live' && at(10_500).state === 'delayed', [at(9_900).state, at(10_500).state])
  check('C4 then DELAYED · BREEZE · <age>, STALE past 10 min', label(at(45_000), NOW + 45_000).startsWith('DELAYED · BREEZE · 45s') && at(11 * 60_000).state === 'stale', [label(at(45_000), NOW + 45_000), at(11 * 60_000).state])
  const tickAged = chain(NOW, {}, {}, [{ strike: 24400, band: true, ce: side('breeze_ws', 8, 'live'), pe: side('nse', 48, 'outside_band') }])
  const ta = SEED.chainSeedSource(tickAged, { mode: 'live', nowMs: NOW + 3_000, marketState: 'open' })
  check('C4 negative control: a snapshot 3 s old whose freshest tick was 8 s old is not LIVE (11 s of exchange age)', ta.state === 'delayed', ta)
  check('C4 the hint says it is a seed snapshot', /seeded from: a snapshot, seeded once/.test(at(3_000).hint ?? ''), at(3_000).hint)
  check('C4 the market closing under a live seed: CLOSE · <session>', SEED.chainSeedSource(seed, { mode: 'live', nowMs: NOW + 5_000, marketState: 'closed' }).state === 'closed')
  const nseOnly = SEED.chainSeedSource({ live: true, as_of: nseStamp(NOW - 1_000), date: '2026-11-23' }, { mode: 'live', nowMs: NOW, marketState: 'open' })
  check('C4 negative control: NSE\'s chain alone (the fallback) is never LIVE, even 1 s old', nseOnly.state === 'delayed' && label(nseOnly) === 'DELAYED · NSE · 1s', label(nseOnly))
  const ph = SEED.seedPhrase(seed)
  check('C4 the legs phrase names the live chain, its census and that it is seeded once', /premiums from the live chain as of 10:20:30 IST \(1 of 2 strike sides priced from Breeze trades/.test(ph) && /a snapshot, seeded once/.test(ph), ph)
  check('C4 each seeded leg records its own side\'s source (booked point in time)',
    /^Breeze websocket trade tick on the live chain 10:20:30 IST/.test(SEED.seedSourcePhrase(seed, seed.rows[0].ce))
    && /^NSE option chain 10:19:42 IST on the live chain 10:20:30 IST \(not ticking\)$/.test(SEED.seedSourcePhrase(seed, seed.rows[0].pe))
    && /^NSE option chain 10:19:42 IST on the live chain 10:20:30 IST \(no trade today on the socket\)$/.test(SEED.seedSourcePhrase(seed, side('breeze_ws', 0.5, 'live', { price_source: 'nse' })))
    && SEED.seedSourcePhrase({ date: '2026-11-20' }) === 'NSE F&O bhavcopy 2026-11-20', [SEED.seedSourcePhrase(seed, seed.rows[0].ce), SEED.seedSourcePhrase(seed, seed.rows[0].pe)])
  check('C4 the headline: live chain vs NSE in session vs the bhavcopy', /^live chain as of 10:20:30 IST \(1 of 2 strike sides priced from Breeze trades, NSE's option chain elsewhere\)$/.test(SEED.seedHeadline(seed))
    && /^NSE option chain in session/.test(SEED.seedHeadline({ live: true, as_of: nseStamp(NOW), date: '2026-11-23' })), SEED.seedHeadline(seed))
}

// ── C5 OMON's cadence ───────────────────────────────────────────────────────────────────────────────────────────────
{
  check('C5 a ticking live chain: every 2.5 s', M.liveChainPollMs(chain(NOW)) === 2_500 && M.CHAIN_POLL_MS === 2_500)
  check('C5 subscribed, no first tick yet: still 2.5 s (the ticks are coming)', M.liveChainPollMs(chain(NOW, {}, { counts: { breeze_ws: 0, nse: 4, eod: 0 } })) === 2_500)
  check('C5 negative control: NSE\'s chain alone / the engine switched off / nothing yet: 30 s',
    M.liveChainPollMs({ live: true, rows: [], served_by: 'nse_fallback' }) === 30_000
    && M.liveChainPollMs(chain(NOW, {}, { counts: { breeze_ws: 0, nse: 4, eod: 0 }, subscription: { enabled: false, engine: 'OFF' } })) === 30_000
    && M.liveChainPollMs(null) === 30_000)
}

// ── C6 the session rule ─────────────────────────────────────────────────────────────────────────────────────────────
{
  const at = (h: number, m: number) => Date.UTC(2026, 10, 23, h, m) - 330 * 60_000
  check('C6 the service\'s market state wins', M.optionsSessionMode({ marketState: 'open', calendarOpen: false, nowMs: at(8, 0) }) === 'live'
    && M.optionsSessionMode({ marketState: 'closed', calendarOpen: true, nowMs: at(11, 0) }) === 'eod' && M.optionsSessionMode({ marketState: 'pre-open', calendarOpen: true, nowMs: at(9, 5) }) === 'eod')
  check('C6 without it, the calendar from 09:15 IST', M.optionsSessionMode({ marketState: null, calendarOpen: true, nowMs: at(9, 15) }) === 'live'
    && M.optionsSessionMode({ marketState: null, calendarOpen: true, nowMs: at(9, 14) }) === 'eod' && M.optionsSessionMode({ marketState: null, calendarOpen: false, nowMs: at(10, 0) }) === 'eod')
  check('C6 OSTR\'s seedMode is the same rule (one rule, not two)', [[null, true, at(10, 0)], ['closed', true, at(10, 0)], ['open', false, at(7, 0)], [null, true, at(9, 0)]]
    .every(([s, c, n]) => SEED.seedMode({ marketState: s as never, calendarOpen: c as boolean, nowMs: n as number }) === M.optionsSessionMode({ marketState: s as never, calendarOpen: c as boolean, nowMs: n as number })))
  const browserClock = /new Date\(\),\s*m = d\.getHours\(\) \* 60 \+ d\.getMinutes\(\)/
  const oc = code(read('components/OptionChain.tsx')), brf = code(read('components/Brief.tsx'))
  check('C6 OMON and BRF no longer pick the chain by the browser\'s local clock', !browserClock.test(oc) && !browserClock.test(brf)
    && /optionsSessionMode\(\{ marketState: ul\.market\?\.state \?\? null, calendarOpen, nowMs: now \}\)/.test(oc)
    && /optMode\.current = \(\) => optionsSessionMode\(\{ marketState: liveBook\.market\?\.state \?\? null, calendarOpen/.test(brf))
  check('C6 negative control: the scan catches the old OMON line', browserClock.test("useState(() => { const d = new Date(), m = d.getHours() * 60 + d.getMinutes(); return d.getDay() >= 1 })"))
}

// ── C7 the receipt normaliser ───────────────────────────────────────────────────────────────────────────────────────
{
  const n = M.normaliseLiveChain(chain(NOW - 5_000, { received_at: undefined }), NOW)
  check('C7 received_at stamped; expiries = the master\'s listed ones, sorted', n.received_at === NOW && JSON.stringify(n.expiries) === JSON.stringify(['2026-11-25', '2026-12-02', '2026-12-30']), n.expiries)
  check('C7 negative control: chain()\'s own list on an NSE v3 frame is the one expiry (a one-chip ladder)', chain(NOW).expiries.length === 1)
  const fb = M.normaliseLiveChain({ live: true, expiry: '2026-11-25', expiries: ['2026-11-25', '2026-12-02'], rows: [], served_by: 'nse_fallback' }, NOW)
  check('C7 NSE\'s fallback keeps its own (NSE-listed) expiries; only the stamp is added', JSON.stringify(fb.expiries) === JSON.stringify(['2026-11-25', '2026-12-02']) && fb.received_at === NOW)
  const odd = M.normaliseLiveChain(chain(NOW, { expiry: '2026-11-27' }, { expiry: { master_expiries: ['2026-12-02', 'junk', 7] } }), NOW)
  check('C7 the chosen expiry is always listed; junk dropped', JSON.stringify(odd.expiries) === JSON.stringify(['2026-11-27', '2026-12-02']), odd.expiries)
}

// ── C8 static wiring ────────────────────────────────────────────────────────────────────────────────────────────────
{
  const oc = code(read('components/OptionChain.tsx'))
  check('C8 OMON: the live branch reads the live chain, the EOD branch the bhavcopy route',
    /getLiveOptionChain\(symbol, expiry \?\? undefined\)\.then\(r => \{ if \(current\(\)\) \{ setData\(r\.data\)/.test(oc) && /const run = !live \? eod\(\)\.catch\(fail\)/.test(oc) && !/getOptionChainLive\(/.test(oc))
  check('C8 OMON: one chain chip from the feed block, reused by the smile / OI / tiles panels',
    /const chainSource = data\?\.live \? liveChainSource\(data, \{ now, marketOpen \}\)/.test(oc) && (oc.match(/source=\{chainSource\}/g) ?? []).length === 4)
  check('C8 OMON: NSE / bhavcopy sides are faded with a hover on every side cell', (oc.match(/opacity: cO/g) ?? []).length === 5 && (oc.match(/opacity: pO/g) ?? []).length === 5
    && (oc.match(/title=\{cf\?\.title\}/g) ?? []).length === 4 && (oc.match(/title=\{pf\?\.title\}/g) ?? []).length === 4 && /gcell\(gfmt\(gc\?\.delta, 'd'\), itmCall, 'right', cf\)/.test(oc))
  check('C8 OMON: Greeks stay on the chain\'s own IV (no second IV method)', /const kIv = otmIv\(r\.strike, data\.forward, r\.ce\.iv, r\.pe\.iv\)/.test(oc) && !/impliedVol|ivFrom|solveIv/.test(oc))
  const pr = code(read('components/OptionPricer.tsx'))
  check('C8 OVME: the picked side\'s own feed on the live chain', /isLiveWsChain\(data\) && leg/.test(pr) && /chainSideFeed\(leg, data, \{ now: Date\.now\(\), marketOpen \}\)\?\.info/.test(pr))
  const sb = code(read('components/StrategyBuilder.tsx'))
  check('C8 OSTR: the seed reads the live chain in session; calendar legs on another expiry stay on NSE\'s chain (no subscriptions)',
    /mode === 'live'\s*\?\s*getLiveOptionChain\(symbol, expiry \?\? undefined\)/.test(sb) && /loadedMode === 'live' \? getOptionChainLive\(sym, e\)/.test(sb))
  check('C8 OSTR: a booked leg records its side\'s source', /const base = seedSourcePhrase\(c, row \? \(l\.kind === 'CE' \? row\.ce : row\.pe\) : null\)/.test(sb))
  const brf = code(read('components/Brief.tsx'))
  const line = brf.slice(brf.indexOf('NIFTY options{'), brf.indexOf('Industries, 1 month'))
  check('C8 BRF: the expected move on the live chain chip, PCR / walls on the OI chip',
    /<LiveChainChip chain=\{opt\.data\} marketOpen=\{optSession === 'live'\}/.test(line) && /kind="oi"/.test(line) && /getLiveOptionChain\('NIFTY'\)\.catch\(\(\) => getOptionChain\('NIFTY'\)\)/.test(brf))
  check('C8 BRF: the walls in side colours (m003), never red / green', !/T\.(red|green)/.test(line) && /color: T\.cyan \}\} title="call wall/.test(line) && /color: T\.violet \}\} title="put wall/.test(line), line.slice(0, 200))
  check('C8 negative control: the wall scan catches the old red / green walls', /T\.(red|green)/.test("<span style={{ color: T.red }}>{opt.data.resistance[0]}</span>/<span style={{ color: T.green }}>{opt.data.support[0]}</span>"))
  const api = code(read('lib/api.ts'))
  const route = fs.readFileSync(path.join(UI, '..', 'services', 'ui-api', 'routers', 'live_option_chain.py'), 'utf8')
  const main = fs.readFileSync(path.join(UI, '..', 'services', 'ui-api', 'main.py'), 'utf8')
  check('C8 the getter asks the route ui-api serves (/api/live + /option-chain/{symbol}) and stamps the receipt',
    /client\.get<LiveOptionChain>\(`\/api\/live\/option-chain\/\$\{encodeURIComponent\(symbol\)\}`/.test(api) && /normaliseLiveChain\(r\.data, Date\.now\(\)\)/.test(api)
    && /@router\.get\("\/option-chain\/\{symbol\}"\)/.test(route) && /app\.include_router\(live_option_chain\.router, prefix="\/api\/live"/.test(main))
  const chip = code(read('components/LiveChainChip.tsx'))
  check('C8 BRF\'s chip ages on the shared 1 s clock between its 60 s polls', /useLiveClock\(isLiveWsChain\(chain\)\)/.test(chip) && /export function useLiveClock/.test(read('lib/liveQuotes.ts')))
}

console.log(`liveChain.check: ${passed} passed, ${failed} failed`)
if (failed) process.exit(1)

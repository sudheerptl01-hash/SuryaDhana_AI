/**
 * OSTR's seed (live program round 2, reports/live_nse, builder L2-UI; the live chain of 22 Nov 2026): which option chain
 * the strategy builder takes its spot / forward and leg premiums from, and what its chip says. Pure, no DOM, no React,
 * relative imports only (unit-tested under plain node by ui/components/__tests__/live.check.ts, section L21, and
 * liveChain.check.ts). Only StrategyBuilder.tsx uses it.
 *
 *  - While NSE trades (09:15–15:30 IST on a trading day: the live quote service's market state when it has answered,
 *    else the client calendar — liveModel.optionsSessionMode, the rule OMON shares) the seed is the live chain
 *    (`/api/live/option-chain`: NSE's option-chain v3 with the Breeze websocket overlaid on the strikes around the money,
 *    ui-api falling back to NSE's chain alone). A seed is a SNAPSHOT: its chip reads LIVE · BREEZE only while the
 *    snapshot is within 10 s of its as_of and its band's ticks were seconds old, then DELAYED · BREEZE · <age>, STALE
 *    past 10 min (liveModel.liveChainSource; ↻ CHAIN re-seeds). NSE's chain alone (the fallback) is NEVER live: DELAYED ·
 *    NSE · <age> from its own records.timestamp, STALE once 10 min old.
 *  - In session with the live chain failing: the end-of-day chain, EOD · <date> with the reason.
 *  - After the close (and before 09:15): the F&O bhavcopy chain labelled CLOSE · <its date>; STALE when that file is
 *    older than the session that just ended (the day's file lands about 20:10) or more than 4 days old.
 *  - The pricing math (POST /api/options/strategy/analyze, Black-76) is untouched: only the inputs' source changes.
 */
import { isLiveWsChain, liveChainCensus, liveChainSource, nseDelayedSource, optionsSessionMode, pricedLive, type ChainMode,
         type LiveChainLike, type LiveChainSideLike, type MarketStateLike as LiveMarketState } from './liveModel'
import { ageDaysOf, nseStampIso, sourceOf, type SourceInfo } from './terminal/source'

export type SeedMode = ChainMode
export type MarketStateLike = LiveMarketState

/** 'HH:MM' minutes since midnight IST. */
function istMinutes(nowMs: number): number {
  const d = new Date(nowMs + 330 * 60_000)
  return d.getUTCHours() * 60 + d.getUTCMinutes()
}

/** 'YYYY-MM-DD' IST. */
export function istDate(nowMs: number): string {
  return new Date(nowMs + 330 * 60_000).toISOString().slice(0, 10)
}

/** The seed source for a chain load now: liveModel.optionsSessionMode (one session rule for OMON and OSTR). */
export function seedMode(o: { marketState: MarketStateLike | null | undefined; calendarOpen: boolean; nowMs: number }): SeedMode {
  return optionsSessionMode(o)
}

export interface ChainLike extends LiveChainLike { live?: boolean; as_of?: string | null; date: string }

/**
 * The legs / payoff panels' SourceChip for the chain the book was seeded from.
 *  - the live chain (Breeze overlay): a snapshot — LIVE · BREEZE ≤ 10 s past its as_of, then DELAYED / STALE by age;
 *  - NSE's chain alone: DELAYED · NSE · <age> (STALE past 10 min), never LIVE;
 *  - EOD chain while NSE trades (the live chain failed): EOD · <date> with the reason;
 *  - EOD chain otherwise: CLOSE · <date>, or STALE when a newer session has ended without its file / > 4 days old.
 */
export function chainSeedSource(chain: ChainLike, o: { mode: SeedMode; nowMs: number; marketState?: MarketStateLike | null;
  sessionDate?: string | null; liveNote?: string | null }): SourceInfo {
  if (isLiveWsChain(chain)) {
    return liveChainSource(chain, { now: o.nowMs, marketOpen: o.marketState ? o.marketState === 'open' : o.mode === 'live',
      hint: 'the live chain the legs were seeded from: a snapshot, seeded once · ↻ CHAIN re-seeds' })
  }
  if (chain.live) {
    return nseDelayedSource(chain.as_of ?? null, { marketOpen: true, now: o.nowMs, source: 'NSE',
      hint: "NSE option chain (v3) the legs were seeded from: premiums and the forward are as of this stamp, not live · ↻ CHAIN re-seeds" })
  }
  const date = chain.date
  if (o.mode === 'live') {
    return sourceOf(date, { source: 'NSE F&O bhavcopy', hint: o.liveNote ?? 'end-of-day chain while NSE trades', now: new Date(o.nowMs) })
  }
  const today = istDate(o.nowMs)
  const age = ageDaysOf(date, new Date(o.nowMs))
  const sessionEnded = o.marketState === 'closed' && o.sessionDate === today && istMinutes(o.nowMs) >= 15 * 60 + 30
  if (sessionEnded && o.sessionDate && date < o.sessionDate) {
    return { state: 'stale', source: 'NSE F&O bhavcopy', asOf: date, ageDays: age,
             hint: `the ${o.sessionDate} F&O bhavcopy is not stored yet (it lands about 20:10): seeded from the ${date} close` }
  }
  if (age == null) return { state: 'offline', source: 'NSE F&O bhavcopy', asOf: null, ageDays: null, hint: 'the chain carries no date' }
  if (age > 4) return { state: 'stale', source: 'NSE F&O bhavcopy', asOf: date, ageDays: age, hint: `the newest stored F&O bhavcopy is ${date}` }
  return { state: 'closed', source: 'NSE F&O bhavcopy', asOf: date, ageDays: null, hint: `NSE closed: premiums and the forward are the ${date} close (F&O bhavcopy settlement prices)` }
}

/** 'HH:MM:SS' IST of NSE's chain stamp ('05-Nov-2026 12:31:05'); '' when unparsable. */
export function stampClock(stamp: string | null | undefined): string {
  const iso = nseStampIso(stamp ?? null)
  if (!iso || /^\d{4}-\d{2}-\d{2}$/.test(iso)) return ''
  const t = Date.parse(iso)
  return Number.isFinite(t) ? new Date(t + 330 * 60_000).toISOString().slice(11, 19) : ''
}

/** The live chain's census for the phrases (liveModel.liveChainCensus: Breeze-PRICED sides of all sides) + its clock. */
function liveCensus(chain: ChainLike & { feed: NonNullable<ChainLike['feed']> }): { live: number; total: number; clock: string } {
  const n = liveChainCensus(chain)
  return { live: n.priced, total: n.total, clock: stampClock(chain.feed.as_of ?? chain.as_of) }
}

/** The page subtitle's chain phrase (which chain, as of when). */
export function seedHeadline(chain: ChainLike): string {
  if (isLiveWsChain(chain)) {
    const c = liveCensus(chain)
    return `live chain as of ${c.clock || '—'} IST (${c.live} of ${c.total} strike sides priced from Breeze trades, ${chain.feed.base === 'eod' ? 'the F&O bhavcopy' : "NSE's option chain"} elsewhere)`
  }
  return chain.live ? `NSE option chain in session (≈1 min behind) as of ${stampClock(chain.as_of) || chain.as_of || '—'} IST` : `NSE F&O bhavcopy ${chain.date}`
}

/**
 * Where ONE seeded price came from (booked and saved with the leg, point in time): on the live chain the strike side's
 * PRICE source (`price_source`) — a Breeze trade tick, else NSE's chain or the bhavcopy base (an untraded band strike
 * keeps the base frame's price though its OI ticks live); otherwise the chain's.
 */
export function seedSourcePhrase(chain: ChainLike, side?: LiveChainSideLike | null): string {
  if (isLiveWsChain(chain)) {
    const at = stampClock(chain.feed.as_of ?? chain.as_of)
    if (pricedLive(side)) return `Breeze websocket trade tick on the live chain ${at} IST${side?.ltt ? ` (last trade ${stampClock(side.ltt)})` : ''}`
    if (!side) return `live chain ${at} IST`
    const why = side.source === 'breeze_ws' ? 'no trade today on the socket' : 'not ticking'
    const ps = side.price_source && side.price_source !== 'breeze_ws' ? side.price_source : side.source !== 'breeze_ws' ? side.source : chain.feed.base
    if (ps === 'eod') return `F&O bhavcopy ${chain.feed.eod_date ?? chain.date} on the live chain ${at} IST (${why})`
    return `NSE option chain ${stampClock(chain.feed.nse_as_of) || 'unstamped'} IST on the live chain ${at} IST (${why})`
  }
  return chain.live ? `NSE option chain in session ${stampClock(chain.as_of) || chain.as_of || ''} IST` : `NSE F&O bhavcopy ${chain.date}`
}

/** The legs panel's "where the premiums come from" phrase. */
export function seedPhrase(chain: ChainLike): string {
  if (isLiveWsChain(chain)) {
    const c = liveCensus(chain)
    return `premiums from the live chain as of ${c.clock ? `${c.clock} IST` : 'an unstamped time'} (${c.live} of ${c.total} strike sides priced from Breeze trades, ${chain.feed.base === 'eod' ? 'the F&O bhavcopy' : "NSE's option chain"} elsewhere; a snapshot, seeded once; ↻ CHAIN re-seeds)`
  }
  if (chain.live) {
    const c = stampClock(chain.as_of)
    return `premiums from NSE's option chain as of ${c ? `${c} IST` : 'an unstamped time'} (seeded once, ≈1 min behind the market; ↻ CHAIN re-seeds)`
  }
  return `premiums from the ${chain.date} F&O bhavcopy close`
}

/** The underlying's move since the chain's snapshot, % (null without both prices). Context only: never re-prices legs. */
export function spotDriftPct(chainSpot: number | null | undefined, livePrice: number | null | undefined): number | null {
  if (chainSpot == null || livePrice == null || !(chainSpot > 0) || !Number.isFinite(livePrice)) return null
  return (livePrice / chainSpot - 1) * 100
}

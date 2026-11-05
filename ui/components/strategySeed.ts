/**
 * OSTR's seed (live program round 2, reports/live_nse, builder L2-UI): which option chain the strategy builder takes its
 * spot / forward and leg premiums from, and what its chip says. Pure, no DOM, no React, relative imports only
 * (unit-tested under plain node by ui/components/__tests__/live.check.ts, section L21). Only StrategyBuilder.tsx uses it.
 *
 *  - While NSE trades (09:15–15:30 IST on a trading day: the live quote service's market state when it has answered,
 *    else the client calendar) the seed is NSE's live option chain (`/api/market/option-chain-live`, option-chain-v3
 *    through data-service nse_live, 30 s cache). NSE refreshes that chain about once a minute and L-INVENTORY measured
 *    it 34–92 s behind: it is NEVER live — the chip reads DELAYED · NSE · <age> from its own records.timestamp and
 *    STALE once the seed is 10 min old (the legs are seeded once; ↻ CHAIN re-seeds at NSE's latest).
 *  - In session with the live chain failing: the end-of-day chain, EOD · <date> with the reason.
 *  - After the close (and before 09:15): the F&O bhavcopy chain labelled CLOSE · <its date>; STALE when that file is
 *    older than the session that just ended (the day's file lands about 20:10) or more than 4 days old.
 *  - The pricing math (POST /api/options/strategy/analyze, Black-76) is untouched: only the inputs' source changes.
 */
import { nseDelayedSource } from './liveModel'
import { ageDaysOf, nseStampIso, sourceOf, type SourceInfo } from './terminal/source'

export type SeedMode = 'live' | 'eod'
export type MarketStateLike = 'open' | 'pre-open' | 'closed'

/** 'HH:MM' minutes since midnight IST. */
function istMinutes(nowMs: number): number {
  const d = new Date(nowMs + 330 * 60_000)
  return d.getUTCHours() * 60 + d.getUTCMinutes()
}

/** 'YYYY-MM-DD' IST. */
export function istDate(nowMs: number): string {
  return new Date(nowMs + 330 * 60_000).toISOString().slice(0, 10)
}

/**
 * The seed source for a chain load now. The live quote service's market state wins when known (it applies NSE's
 * holiday list); without it the client calendar (`calendarOpen`, 09:00–15:30 on a trading day) from 09:15 on —
 * options do not trade in the 09:00–09:15 pre-open.
 */
export function seedMode(o: { marketState: MarketStateLike | null | undefined; calendarOpen: boolean; nowMs: number }): SeedMode {
  if (o.marketState === 'open') return 'live'
  if (o.marketState === 'pre-open' || o.marketState === 'closed') return 'eod'
  return o.calendarOpen && istMinutes(o.nowMs) >= 9 * 60 + 15 ? 'live' : 'eod'
}

export interface ChainLike { live?: boolean; as_of?: string | null; date: string }

/**
 * The legs / payoff panels' SourceChip for the chain the book was seeded from.
 *  - live chain: DELAYED · NSE · <age> (STALE past 10 min), never LIVE;
 *  - EOD chain while NSE trades (the live chain failed): EOD · <date> with the reason;
 *  - EOD chain otherwise: CLOSE · <date>, or STALE when a newer session has ended without its file / > 4 days old.
 */
export function chainSeedSource(chain: ChainLike, o: { mode: SeedMode; nowMs: number; marketState?: MarketStateLike | null;
  sessionDate?: string | null; liveNote?: string | null }): SourceInfo {
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

/** The legs panel's "where the premiums come from" phrase. */
export function seedPhrase(chain: ChainLike): string {
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

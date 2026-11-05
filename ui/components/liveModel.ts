/**
 * Pane-side rules of the live program (reports/live_nse): how a pane turns NSE's website stamps and the live quote
 * rows (lib/liveQuotes.ts) into numbers and SourceChips. Pure, no DOM, no React; relative imports only (unit-tested
 * under plain node by ui/components/__tests__/live.check.ts).
 *
 *  - `nseDelayedSource`: NSE's website feeds (allIndices, heatmap, live-analysis, option-chain-v3, chart feed) are
 *    never live — L-CAPACITY measured them 49–172 s behind, stamped to the minute or worse — so their chip reads
 *    DELAYED · NSE · <age> while NSE trades, STALE past `staleAfterS`, CLOSE · <day> once the session is over.
 *  - `liveContribution`: "who moved the index" recomputed on live rows: points = previous index level × weight × the
 *    member's % change (the data-service formula, weights unchanged intraday because they are built on the previous
 *    close); members without a live row keep the NSE payload's move, and the count says how many are live.
 *  - `liveLevel`: an index / underlying level for a tile: the live row when it has a price, else the payload's.
 */
import { nseStampIso, type SourceInfo } from './terminal/source'

/** An NSE website stamp older than this while NSE trades reads STALE (10 min: the feeds refresh about every minute). */
export const NSE_STALE_AFTER_S = 600

/** The chip of a pane fed by NSE's website: DELAYED · NSE · <age> / STALE / CLOSE · <day> / OFFLINE. */
export function nseDelayedSource(stamp: string | null | undefined, opts: { marketOpen: boolean; now: number; source?: string; staleAfterS?: number; hint?: string | null }): SourceInfo {
  const source = opts.source ?? 'NSE'
  const iso = nseStampIso(stamp ?? null)
  if (!iso) return { state: 'offline', source, asOf: null, ageDays: null, hint: opts.hint ?? 'no NSE time stamp in the payload' }
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(iso)
  if (!opts.marketOpen) return { state: 'closed', source, asOf: iso.slice(0, 10), ageDays: null, hint: opts.hint ?? `NSE closed: last session's figures (${stamp})` }
  if (dateOnly) return { state: 'delayed', source, asOf: iso, ageDays: null, hint: opts.hint ?? null }
  const t = Date.parse(iso)
  const ageS = Number.isFinite(t) ? Math.max(0, (opts.now - t) / 1000) : null
  const minuteOnly = !/:\d{2}:\d{2}/.test(String(stamp ?? ''))
  const why = `${opts.hint ? `${opts.hint} · ` : ''}NSE's website, not a live feed${minuteOnly ? ' (stamped to the minute)' : ''}`
  if (ageS != null && ageS > (opts.staleAfterS ?? NSE_STALE_AFTER_S)) return { state: 'stale', source, asOf: iso, ageDays: 0, ageS, hint: why }
  return { state: 'delayed', source, asOf: iso, ageDays: 0, ageS, hint: why }
}

export interface LiveRowLike { price: number | null; change_pct: number | null; change?: number | null; prev_close: number | null; state: string; source?: string | null }

export interface ContribMember { symbol: string; change_pct: number; weight_pct: number | null; points: number | null; promoter_pct: number | null }
export interface ContribPayload {
  index: string; last: number | null; change: number | null; change_pct: number | null; explained_points: number; time?: string
  members: ContribMember[]; missing: string[]
}
export interface LiveContrib extends ContribPayload {
  /** members whose move came from a live row */
  liveMembers: number
  /** the index level / change came from a live row */
  indexLive: boolean
}

// a stored EOD row during the session ('stale', source 'eod') carries the previous session's move: it is not a live row
// for "who moved" or the index level, so the payload's NSE move stands (check:LV-UI major)
const usable = (r: LiveRowLike | null | undefined): r is LiveRowLike =>
  !!r && r.state !== 'unavailable' && r.price != null && Number.isFinite(r.price) && !(r.source === 'eod' && r.state === 'stale')

/** "Who moved the index" on live rows (see the file header). Returns the payload unchanged (counts 0) without any. */
export function liveContribution(d: ContribPayload, live: Readonly<Record<string, LiveRowLike | null | undefined>>): LiveContrib {
  const ix = live[d.index]
  const indexLive = usable(ix)
  const payloadPrev = d.last != null && d.change != null ? d.last - d.change
    : d.last != null && d.change_pct != null ? d.last / (1 + d.change_pct / 100) : null
  const prevLevel = indexLive && ix.prev_close != null ? ix.prev_close : payloadPrev
  let liveMembers = 0
  const members = d.members.map(m => {
    const r = live[m.symbol]
    if (!usable(r) || r.change_pct == null || !Number.isFinite(r.change_pct)) return m
    liveMembers++
    const points = m.weight_pct != null && prevLevel ? Math.round(prevLevel * (m.weight_pct / 100) * (r.change_pct / 100) * 100) / 100 : m.points
    return { ...m, change_pct: r.change_pct, points }
  }).sort((a, b) => (b.points ?? 0) - (a.points ?? 0))
  const explained = Math.round(members.reduce((a, m) => a + (m.points ?? 0), 0) * 10) / 10
  if (!indexLive) return { ...d, members, explained_points: liveMembers ? explained : d.explained_points, liveMembers, indexLive }
  const last = ix.price as number
  const change = ix.change ?? (ix.prev_close != null ? last - ix.prev_close : d.change)
  const change_pct = ix.change_pct ?? (ix.prev_close ? (last / ix.prev_close - 1) * 100 : d.change_pct)
  return { ...d, last, change, change_pct, members, explained_points: liveMembers ? explained : d.explained_points, liveMembers, indexLive }
}

/**
 * A tile's level and change: the live service's row when it is priced, else the payload's. `fromService` says which
 * (the row's own state — live / delayed / closed — is the chip's business, not this flag's).
 */
export function liveLevel(payload: { last: number | null; change_pct: number | null } | null | undefined, row: LiveRowLike | null | undefined):
  { last: number | null; change_pct: number | null; fromService: boolean } {
  if (usable(row)) return { last: row.price, change_pct: row.change_pct ?? payload?.change_pct ?? null, fromService: true }
  return { last: payload?.last ?? null, change_pct: payload?.change_pct ?? null, fromService: false }
}

export interface HeaderChip { text: string; tone: 'live' | 'delayed' | 'closed' | 'down'; title: string }

/**
 * The header's NIFTY chip from a live-service row (lib/feedState.ts FeedChip shape): ● LIVE (a Breeze tick seconds
 * old), ● NSE · 48s (NSE's website through the service), ◌ STALE HH:MM, CLOSE DD-MON; null for no row (the header
 * then keeps its older sources).
 */
export function liveHeaderChip(info: SourceInfo | null | undefined, ltt: string | null | undefined): HeaderChip | null {
  if (!info || info.state === 'offline') return null
  const t = ltt ? Date.parse(ltt) : NaN
  const clock = Number.isFinite(t) ? new Date(t + 330 * 60_000).toISOString().slice(11, 19) : ''
  const age = info.ageS != null ? (info.ageS < 90 ? `${Math.round(info.ageS)}s` : `${Math.round(info.ageS / 60)}m`) : ''
  const src = info.source ?? ''
  if (info.state === 'live') return { text: '● LIVE', tone: 'live', title: `${src === 'BREEZE' ? 'ICICI Breeze websocket' : src} · last tick ${clock || 'n/a'} IST${age ? ` · ${age} old` : ''}` }
  if (info.state === 'closed') {
    const MON = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
    const d = info.asOf && /^\d{4}-(\d{2})-(\d{2})/.exec(info.asOf)
    return { text: d ? `CLOSE ${d[2]}-${MON[Number(d[1]) - 1]}` : 'CLOSED', tone: 'closed', title: `NSE closed: the last session's close${clock ? ` (last trade ${clock} IST)` : ''}` }
  }
  if (info.state === 'stale') return { text: `◌ STALE${clock ? ` ${clock.slice(0, 5)}` : ''}`, tone: 'down', title: `${src} quote older than expected while NSE trades${age ? ` · ${age} old` : ''}` }
  return { text: `● ${src === 'BREEZE' ? 'ICICI' : src || 'NSE'}${age ? ` · ${age}` : ''}`, tone: 'delayed', title: `${src === 'NSE' ? "NSE's website, about 1 min behind" : `${src} quote, delayed`}${clock ? ` · ${clock} IST` : ''}${age ? ` · ${age} old` : ''}` }
}

/** NSE's F&O underlying code → the live service's symbol (an index's name; a stock is itself). */
const INDEX_UNDERLYINGS: Readonly<Record<string, string>> = Object.freeze({
  NIFTY: 'NIFTY 50', BANKNIFTY: 'NIFTY BANK', FINNIFTY: 'NIFTY FIN SERVICE', MIDCPNIFTY: 'NIFTY MID SELECT', NIFTYNXT50: 'NIFTY NEXT 50',
})
export function underlyingLiveSymbol(fo: string | null | undefined): string | null {
  const s = String(fo ?? '').trim().toUpperCase()
  if (!s) return null
  return INDEX_UNDERLYINGS[s] ?? s
}

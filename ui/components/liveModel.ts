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
 *  - the live option chain (22 Nov 2026; OMON / OSTR / BRF, ui-api /api/live/option-chain ← data-service live_chain.py):
 *    `liveChainSource` (the chain chip from the payload's feed block: LIVE · BREEZE · <age> · 42/114 LIVE only while
 *    the band's freshest tick is seconds old, else DELAYED / STALE by age, the base frame's DELAYED · NSE / EOD chip
 *    when nothing ticks, CLOSE after the session), `chainOiSource` (PCR / walls: the base frame's chip, never LIVE),
 *    `chainSideFeed` (one strike side: dimmed unless it is a Breeze tick, with its source and age), `liveChainPollMs`,
 *    `optionsSessionMode` (the session rule OMON and OSTR share), `normaliseLiveChain` (receipt time + listed expiries).
 *    Tested by ui/components/__tests__/liveChain.check.ts.
 */
import { fmtAgeS, nseStampIso, sourceOf, type SourceInfo } from './terminal/source'

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

// ── the live option chain (22 Nov 2026) ─────────────────────────────────────────────────────────────────────────────
// GET /api/live/option-chain/{symbol} (ui-api routers/live_option_chain.py) ← data-service /live/option-chain
// (live_chain.py): NSE's option-chain v3 frame (else the last F&O bhavcopy) with the Breeze websocket overlaid on ATM ±
// width strikes. Every strike side says where it came from (`source` breeze_ws | nse | eod, `age_s`, `tick_state`), the
// chain carries a `feed` block (counts per source, the band, as_of, nse_as_of), and ui-api says which upstream answered
// (`served_by` live_chain | nse_fallback — the NSE fallback has no feed block and reads DELAYED · NSE like before).
// `price_source` (23 Nov) says where the shown PRICE came from: breeze_ws only when the contract traded today on the
// socket; an untraded band strike keeps the base frame's price while its OI / book / volume are live (`source` stays
// breeze_ws). The chip's LIVE count, the LIVE age and the dimming read `price_source`; a side without it is never
// counted as Breeze-priced (the conservative reading). During an NSE outage data-service serves the bhavcopy base
// (`base: 'eod'`, `base_error`), remembered for 30 s.

export interface LiveChainSideLike {
  price?: number | null; oi?: number | null
  source?: string | null; price_source?: string | null; age_s?: number | null; tick_state?: string | null; error?: string | null
  bid?: number | null; ask?: number | null; ltp?: number | null; ltt?: string | null
}
export interface LiveChainFeedLike {
  as_of?: string | null; nse_as_of?: string | null; eod_date?: string | null; base?: string | null; base_error?: string | null
  base_age_s?: number | null; counts?: Readonly<Record<string, number | null | undefined>> | null
  band?: { width?: number | null } | null
  expiry?: { master_expiries?: readonly string[] | null } | null
  subscription?: { enabled?: boolean | null; engine?: string | null; healthy?: boolean | null; waiting_first_tick?: number | null; over_cap?: number | null } | null
}
export interface LiveChainLike {
  live?: boolean; as_of?: string | null; date?: string; expiry?: string; expiries?: string[]
  rows?: readonly { strike: number; band?: boolean; ce: LiveChainSideLike; pe: LiveChainSideLike }[]
  feed?: LiveChainFeedLike | null; served_by?: string | null; fallback_reason?: string | null; received_at?: number | null
}

/** A chain is LIVE only while its freshest Breeze-PRICED tick is at most this many seconds old NOW — the same bound as a
 *  live quote row this window received (lib/liveQuotes LOCAL_LIVE_MAX_S; liveChain.check.ts pins the two equal). A seed
 *  snapshot therefore reads LIVE no later than 10 s past its as_of, then DELAYED / STALE by age. */
export const CHAIN_LIVE_MAX_S = 10
/** OMON's poll while the live chain answers with its overlay (data-service memoises it 1 s). */
export const CHAIN_POLL_MS = 2_500
/** ... and while it cannot tick (the NSE fallback, the tick engine switched off): NSE's chain changes about once a minute. */
export const CHAIN_SLOW_POLL_MS = 30_000

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
const ISO_TS = /^\d{4}-\d{2}-\d{2}T/
const istDate = (iso: string | null | undefined): string | null => {
  const t = iso && ISO_TS.test(iso) ? Date.parse(iso) : NaN
  return Number.isFinite(t) ? new Date(t + 330 * 60_000).toISOString().slice(0, 10) : null
}
const istClockOf = (iso: string | null | undefined): string => {
  const t = iso && ISO_TS.test(iso) ? Date.parse(iso) : NaN
  return Number.isFinite(t) ? new Date(t + 330 * 60_000).toISOString().slice(11, 19) : ''
}
/** '48s' / '6m' under a day and a half, else '2.8 d' (a bhavcopy base is days old). */
const fmtLongAge = (s: number): string => (s < 36 * 3600 ? fmtAgeS(s) : `${(s / 86_400).toFixed(1)} d`)

/** The payload is data-service's live chain (a feed block, not ui-api's NSE fallback). */
export function isLiveWsChain<C extends LiveChainLike>(c: C | null | undefined): c is C & { feed: LiveChainFeedLike } {
  return !!c && c.served_by !== 'nse_fallback' && !!c.feed && typeof c.feed === 'object'
}

/** The side's shown price is a Breeze trade tick (`price_source`); absent = not (never assumed). */
export const pricedLive = (s: LiveChainSideLike | null | undefined): boolean => !!s && s.price_source === 'breeze_ws'

/** Seconds since the snapshot, now: the larger of this window's receipt age and the payload's own as_of age — a skewed
 *  server clock can only make it older, never younger. Null with neither. */
export function chainSnapshotAgeS(c: LiveChainLike, now: number): number | null {
  const local = finite(c.received_at) ? Math.max(0, (now - c.received_at) / 1000) : null
  const iso = c.feed?.as_of ?? (c.as_of && ISO_TS.test(c.as_of) ? c.as_of : null)
  const t = iso && ISO_TS.test(iso) ? Date.parse(iso) : NaN
  const server = Number.isFinite(t) ? Math.max(0, (now - t) / 1000) : null
  if (local == null && server == null) return null
  return Math.max(local ?? 0, server ?? 0)
}

export interface LiveChainCensus {
  /** sides whose PRICE is a Breeze trade (price_source): the chip's LIVE count */
  priced: number
  /** sides on the socket at all (source breeze_ws: OI / book / volume live), untraded band strikes included */
  ticking: number
  total: number
  /** the freshest Breeze-priced tick, aged to `now` (at the snapshot without `now`) */
  freshestS: number | null
  /** every priced side is quiet on a healthy feed */
  allQuiet: boolean
}
/** The live chain's census (one place: the chip, OMON's subtitle and OSTR's phrases all read it). */
export function liveChainCensus(c: LiveChainLike, now?: number): LiveChainCensus {
  const snapS = now == null ? 0 : chainSnapshotAgeS(c, now) ?? 0
  let priced = 0, ticking = 0, total = 0, quiet = 0
  let freshest: number | null = null
  for (const r of c.rows ?? []) {
    for (const s of [r.ce, r.pe]) {
      if (!s) continue
      total++
      if (s.source === 'breeze_ws') ticking++
      if (!pricedLive(s)) continue
      priced++
      if (s.tick_state === 'quiet') quiet++
      if (finite(s.age_s)) { const a = s.age_s + snapS; if (freshest == null || a < freshest) freshest = a }
    }
  }
  const n = c.feed?.counts
  if (!total && n) total = Object.values(n).reduce<number>((a, v) => a + (finite(v) ? v : 0), 0)
  return { priced, ticking, total, freshestS: freshest, allQuiet: priced > 0 && quiet === priced }
}

/** Why no side is Breeze-priced (the census, then the feed block's subscription state), for a hint. */
function noTickWhy(f: LiveChainFeedLike, n: LiveChainCensus): string {
  if (n.ticking > 0) return `${n.ticking} sides tick on the socket (OI / book live) but none has traded today`
  const s = f.subscription ?? {}
  if (s.enabled === false) return 'the Breeze websocket is switched off'
  if (s.engine === 'OFF') return 'the Breeze websocket is off'
  if (finite(s.waiting_first_tick) && s.waiting_first_tick > 0) return `${s.waiting_first_tick} contracts subscribed, waiting for their first tick`
  if (finite(s.over_cap) && s.over_cap > 0) return `${s.over_cap} contracts over the websocket's option cap`
  if (s.healthy === false) return 'the Breeze websocket is unhealthy'
  return 'no fresh Breeze tick on the band'
}

/**
 * The base frame's chip: NSE's v3 chain DELAYED · NSE · <age> (STALE past 10 min); the bhavcopy (an NSE outage: base
 * 'eod' + base_error) EOD · <its date>, DELAYED with its age and NSE's error on hover (STALE once 2 sessions behind);
 * CLOSE after the session.
 */
function baseSource(c: LiveChainLike & { feed: LiveChainFeedLike }, o: { now: number; marketOpen: boolean }, hint: string): SourceInfo {
  const f = c.feed
  const snap = chainSnapshotAgeS(c, o.now)
  if (f.base === 'eod') {
    const day = f.eod_date ?? c.date ?? null
    const age = finite(f.base_age_s) ? f.base_age_s + (snap ?? 0) : null
    const why = `${hint}${f.base_error ? ` · NSE's option chain failed (${f.base_error}): the stored F&O bhavcopy stands in` : ''}${age != null ? ` · ${fmtLongAge(age)} old` : ''}`
    if (!o.marketOpen) return { state: 'closed', source: 'NSE F&O bhavcopy', asOf: day, ageDays: null, hint: why }
    return sourceOf(day, { source: 'NSE F&O bhavcopy', hint: why, now: new Date(o.now) })
  }
  if (f.nse_as_of) return nseDelayedSource(f.nse_as_of, { marketOpen: o.marketOpen, now: o.now, hint })
  if (!o.marketOpen) return { state: 'closed', source: 'NSE', asOf: istDate(f.as_of), ageDays: null, hint }
  if (finite(f.base_age_s) && snap != null) {
    const ageS = f.base_age_s + snap
    return { state: ageS > NSE_STALE_AFTER_S ? 'stale' : 'delayed', source: 'NSE', asOf: f.as_of ?? null, ageDays: 0, ageS, hint }
  }
  return { state: 'offline', source: 'NSE', asOf: null, ageDays: null, hint: `${hint} · no NSE time stamp in the payload` }
}

/**
 * The live chain's chip (OMON's chain / smile / OI / tiles panels, BRF's expected move, OSTR's seed):
 *  - not the live payload (ui-api's NSE fallback): DELAYED · NSE · <age> from NSE's stamp, as before; an EOD chain: its date;
 *  - after the session: CLOSE · <session>;
 *  - Breeze-priced sides (price_source) whose freshest tick is ≤ CHAIN_LIVE_MAX_S old now: LIVE · BREEZE · <age> ·
 *    <priced>/<all> LIVE ('LIVE·q' when every priced side is quiet on a healthy feed);
 *  - Breeze-priced sides but older (a window that stopped refreshing, a band with no trade lately, a seed snapshot
 *    ageing): DELAYED · BREEZE · <age>, STALE past NSE_STALE_AFTER_S;
 *  - no Breeze-priced side: the base frame's chip (DELAYED · NSE · <age> / EOD · <date> with its age) and why.
 */
export function liveChainSource(c: LiveChainLike, o: { now: number; marketOpen: boolean; hint?: string | null; staleAfterS?: number }): SourceInfo {
  if (!isLiveWsChain(c)) {
    if (!c.live) return sourceOf(c.date ?? null, { source: 'NSE F&O bhavcopy', hint: o.hint ?? null, now: new Date(o.now) })
    const why = c.fallback_reason ? `Breeze overlay unavailable (${c.fallback_reason}) · ` : ''
    return nseDelayedSource(c.as_of ?? null, { marketOpen: o.marketOpen, now: o.now, hint: o.hint ?? `${why}NSE option chain (v3), refreshed by NSE about once a minute` })
  }
  const f = c.feed
  const snap = chainSnapshotAgeS(c, o.now)
  const n = liveChainCensus(c, o.now)
  const baseWord = f.base === 'eod' ? `the ${f.eod_date ?? 'last'} F&O bhavcopy` : "NSE's option chain (v3)"
  const width = finite(f.band?.width) ? f.band!.width : null
  const band = width ? `ATM ± ${width} strikes` : 'the strikes around the money'
  const others = Math.max(0, n.total - n.priced)
  const baseAge = finite(f.base_age_s) ? f.base_age_s + (snap ?? 0) : null
  const untraded = n.ticking > n.priced ? `, ${n.ticking - n.priced} of them on the socket without a trade today (OI / book live)` : ''
  const rest = others ? ` · the other ${others} priced from ${baseWord}${baseAge != null ? `, ${fmtLongAge(baseAge)} old` : ''}${untraded}` : ''
  const lead = o.hint ? `${o.hint} · ` : ''
  if (!o.marketOpen) {
    if (n.priced) return { state: 'closed', source: 'BREEZE', asOf: istDate(f.as_of), ageDays: null, hint: `${lead}NSE closed: the session's last live chain` }
    return baseSource(c, o, `${lead}NSE closed: the session's last chain from ${baseWord}`)
  }
  const mix = n.total > 0 ? { live: n.priced, total: n.total } : null
  const sides = `${n.priced} of ${n.total} strike sides priced from Breeze trades (${band})`
  if (n.priced > 0 && n.freshestS != null && n.freshestS <= CHAIN_LIVE_MAX_S) {
    return { state: 'live', source: 'BREEZE', asOf: f.as_of ?? null, ageDays: 0, ageS: n.freshestS, mix, quiet: n.allQuiet ? true : undefined,
             hint: `${lead}${sides}, the freshest tick ${fmtAgeS(n.freshestS)} old${rest}` }
  }
  if (n.priced > 0) {
    const why = snap != null && snap > CHAIN_LIVE_MAX_S ? `received ${fmtAgeS(snap)} ago, not refreshed since`
      : `no Breeze tick on the band's traded strikes for ${n.freshestS != null ? fmtAgeS(n.freshestS) : 'a while'} (quiet on a healthy feed)`
    const age = n.freshestS
    return { state: age != null && age > (o.staleAfterS ?? NSE_STALE_AFTER_S) ? 'stale' : 'delayed', source: 'BREEZE', asOf: f.as_of ?? null,
             ageDays: 0, ageS: age, mix, hint: `${lead}${why} · ${sides}${rest}` }
  }
  return baseSource(c, o, `${lead}no strike side priced from the Breeze websocket: ${noTickWhy(f, n)}`)
}

/**
 * PCR, OI walls and max pain sum the band's live OI with the base frame's OI on every other strike, so they carry the
 * BASE frame's chip (DELAYED · NSE · <age> / EOD · <date> / CLOSE after the session) — never LIVE.
 */
export function chainOiSource(c: LiveChainLike, o: { now: number; marketOpen: boolean }): SourceInfo {
  if (!isLiveWsChain(c)) return liveChainSource(c, o)
  const what = c.feed.base === 'eod' ? `the ${c.feed.eod_date ?? 'last'} F&O bhavcopy` : "NSE's option chain (v3)"
  return baseSource(c, o, `PCR and OI walls sum the live band's OI with ${what} on every other strike: labelled by the older source`)
}

const TICK_WHY: Readonly<Record<string, string>> = {
  waiting_first_tick: 'subscribed, waiting for its first tick', over_cap: "over the websocket's option cap",
  not_subscribed: 'not subscribed', stale: 'its last tick is too old', not_vouched: 'its quiet tick is not vouched by the feed',
  feed_unhealthy: 'the websocket is unhealthy', other_session: 'its last tick is from another session', feed_off: 'the websocket is off',
  no_master: 'not in the ICICI security master', error: 'subscription error',
}

export interface SideFeed { dim: boolean; title: string; info: SourceInfo }

/**
 * One strike side of the live chain, by where its shown PRICE came from (`price_source`): a Breeze trade tick is shown
 * at full strength with its age, LTT and book; anything else — NSE's chain, the bhavcopy, and an untraded band strike
 * whose OI / book tick live but whose price is still the base frame's — is DIMMED, the price's source and age (and the
 * live OI / book, when it ticks) on hover. Null for any other chain (one source: the chip says it). `info` is the price's
 * own chip (OVME's pricer).
 */
export function chainSideFeed(side: LiveChainSideLike | null | undefined, c: LiveChainLike | null | undefined,
                              o: { now: number; marketOpen: boolean }): SideFeed | null {
  if (!side || !c || !isLiveWsChain(c)) return null
  const f = c.feed
  const snap = chainSnapshotAgeS(c, o.now) ?? 0
  const onSocket = side.source === 'breeze_ws'
  const tickAge = onSocket && finite(side.age_s) ? side.age_s + snap : null
  const book = finite(side.bid) || finite(side.ask) ? ` · bid ${finite(side.bid) ? side.bid.toFixed(2) : '—'} / ask ${finite(side.ask) ? side.ask.toFixed(2) : '—'}` : ''
  if (pricedLive(side)) {
    const clock = istClockOf(side.ltt)
    const quiet = side.tick_state === 'quiet' ? ' (quiet: no new tick on a healthy feed)' : ''
    const title = `Breeze websocket · tick ${tickAge != null ? fmtAgeS(tickAge) : 'n/a'} old${quiet}${clock ? ` · last trade ${clock} IST` : ''}${book}`
    const info: SourceInfo = !o.marketOpen
      ? { state: 'closed', source: 'BREEZE', asOf: istDate(f.as_of), ageDays: null, hint: title }
      : tickAge != null && tickAge <= CHAIN_LIVE_MAX_S
        ? { state: 'live', source: 'BREEZE', asOf: side.ltt ?? f.as_of ?? null, ageDays: 0, ageS: tickAge, quiet: side.tick_state === 'quiet' ? true : undefined, hint: title }
        : { state: tickAge != null && tickAge > NSE_STALE_AFTER_S ? 'stale' : 'delayed', source: 'BREEZE', asOf: side.ltt ?? f.as_of ?? null, ageDays: 0, ageS: tickAge, hint: title }
    return { dim: false, title, info }
  }
  // the shown price is the base frame's (NSE's chain or the bhavcopy), whatever ticks beside it
  const ps = side.price_source && side.price_source !== 'breeze_ws' ? side.price_source : !onSocket && side.source ? side.source : f.base ?? 'nse'
  const eod = ps === 'eod'
  const baseAge = !onSocket && finite(side.age_s) ? side.age_s + snap : finite(f.base_age_s) ? f.base_age_s + snap : null
  const what = eod ? `the ${f.eod_date ?? 'last'} F&O bhavcopy${f.base_error ? " (NSE's chain unavailable)" : ''}` : "NSE's option chain (v3)"
  const priceWhat = `${what}${!eod && baseAge != null ? ` · ${fmtAgeS(baseAge)} old` : ''}`
  let title: string
  if (onSocket) {
    title = `price: ${priceWhat} — no trade today on the Breeze websocket · OI, book and volume: Breeze tick ${tickAge != null ? fmtAgeS(tickAge) : 'n/a'} old${book}`
  } else {
    const width = finite(f.band?.width) ? f.band!.width : null
    const state = side.tick_state ?? ''
    const why = state === 'outside_band' ? `outside the live band (ATM ± ${width ?? '?'} strikes)` : TICK_WHY[state] ?? (state || 'not on the websocket')
    title = `${priceWhat} · not live: ${why}${side.error ? ` (${side.error})` : ''}`
  }
  const info = baseSource({ ...c, feed: { ...f, base: eod ? 'eod' : 'nse' } }, o, title)
  return { dim: true, title, info }
}

/** OMON's poll cadence for the chain on screen: fast while the live chain can tick, slow on the NSE fallback / no engine. */
export function liveChainPollMs(c: LiveChainLike | null | undefined): number {
  if (!isLiveWsChain(c)) return CHAIN_SLOW_POLL_MS
  const ticking = finite(c.feed.counts?.breeze_ws) && (c.feed.counts?.breeze_ws ?? 0) > 0
  return ticking || c.feed.subscription?.enabled !== false ? CHAIN_POLL_MS : CHAIN_SLOW_POLL_MS
}

export type ChainMode = 'live' | 'eod'
export type MarketStateLike = 'open' | 'pre-open' | 'closed'

/**
 * Which chain OMON / OSTR / BRF read now: the live quote service's market state when it has answered (it applies NSE's
 * holiday list and special sessions); without it the client calendar (`calendarOpen`, 09:00–15:30 IST on a trading day)
 * from 09:15 IST — options do not trade in the 09:00–09:15 pre-open. Never the browser's local clock.
 */
export function optionsSessionMode(o: { marketState: MarketStateLike | null | undefined; calendarOpen: boolean; nowMs: number }): ChainMode {
  if (o.marketState === 'open') return 'live'
  if (o.marketState === 'pre-open' || o.marketState === 'closed') return 'eod'
  const d = new Date(o.nowMs + 330 * 60_000)
  return o.calendarOpen && d.getUTCHours() * 60 + d.getUTCMinutes() >= 9 * 60 + 15 ? 'live' : 'eod'
}

/**
 * A live chain as received: stamped with this window's receipt time (`received_at`, the snapshot clock), and its
 * `expiries` = the security master's listed expiries (feed.expiry.master_expiries) when it carries them — an NSE v3
 * base frame holds one expiry, so chain()'s own list would show a one-chip ladder. Any other body: only the stamp.
 */
export function normaliseLiveChain<C extends LiveChainLike>(body: C, receivedAt: number): C & { received_at: number } {
  const out = { ...body, received_at: receivedAt }
  if (!isLiveWsChain(body)) return out
  const listed = (body.feed.expiry?.master_expiries ?? []).filter((e): e is string => typeof e === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(e))
  if (listed.length) out.expiries = [...new Set([...listed, ...(body.expiry ? [body.expiry] : [])])].sort()
  return out
}

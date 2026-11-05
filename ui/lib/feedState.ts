/**
 * Live-feed chips that never claim "live" on a closed market or while the link is down (C1-trader-ux-13).
 * Pure, no DOM, no imports (unit-tested by `node ui/components/desktop/__tests__/desktop.check.ts`); the React
 * side is components/shell/useFeed.ts (market session from the shared holiday rule + the shell's link state).
 *
 * Wording:
 *  - link down (ui-api unreachable): the value on screen is the last one received → STALE / LINK DOWN;
 *  - market closed (weekend, holiday, before 09:00, after 15:30 IST): the value is the last session's close →
 *    "CLOSE 23-OCT" (or CLOSED), and a connected socket reads "SOCKET OK · NO TICKS" instead of STREAMING;
 *  - market open (pre-open counts: the auction prints): the original chips, unchanged.
 *
 * Data beats the calendar (R-UI-SHELL-03): `marketOpen` from useFeedState is already "the calendar says open OR a
 * live tick arrived in the last LIVE_TICK_MAX_AGE_MS", and the NIFTY chip also counts an NSE print stamped within
 * NSE_PRINT_MAX_AGE_MS of now, so a session the calendar does not know (Muhurat, a special Saturday session) never
 * reads CLOSE <day> / NO TICKS while it prints. The reverse is not inferred: a quiet feed on a trading day keeps the
 * calendar's wording. A "live tick" is a QUOTE with a fresh exchange time that is a new print (quotePrint /
 * isLivePrint, round 4b): heartbeats, acks and the previous session's quotes that data-service keeps publishing on a
 * weekday holiday never flip a chip to LIVE.
 *
 * Stale quotes (P9): during NSE's regular hours a NIFTY quote more than QUOTE_STALE_MS old reads ◌ STALE <time>, and
 * a stopped ICICI stream gives way to NSE's print (pickNiftySource).
 *
 * Chrome polling cadence (R-UI-SHELL-06 / C-PERF-06): chromePollMs slows the header's NIFTY polls to IDLE_POLL_MS
 * while the market is closed or the window is hidden; the live cadence is unchanged.
 */

/** A monitor-socket tick younger than this means the market is printing (whatever the calendar says). */
export const LIVE_TICK_MAX_AGE_MS = 90_000
/** An NSE index print (`time` of /api/market/nifty-live, ≈1 min cadence in session) younger than this, likewise. */
export const NSE_PRINT_MAX_AGE_MS = 3 * 60_000
/** Header chrome poll interval while the market is closed or the window hidden. */
export const IDLE_POLL_MS = 60_000

const MONTH_INDEX: Record<string, number> = { JAN: 0, FEB: 1, MAR: 2, APR: 3, MAY: 4, JUN: 5, JUL: 6, AUG: 7, SEP: 8, OCT: 9, NOV: 10, DEC: 11 }

/** NSE's IST stamp "23-Oct-2026 15:30" (seconds optional) → epoch ms; null when unrecognised. */
export function nseTimeToEpoch(asOf: string | null | undefined): number | null {
  if (!asOf || typeof asOf !== 'string') return null
  const m = /^(\d{1,2})-([A-Za-z]{3})-(\d{4})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?/.exec(asOf.trim())
  if (!m) return null
  const mon = MONTH_INDEX[m[2].toUpperCase()]
  if (mon === undefined) return null
  // IST = UTC+05:30, no DST
  return Date.UTC(Number(m[3]), mon, Number(m[1]), Number(m[4]), Number(m[5]), Number(m[6] ?? 0)) - 330 * 60_000
}

/** True when `asOf` (an NSE IST stamp) is a print from the last NSE_PRINT_MAX_AGE_MS (a little clock skew allowed). */
export function isFreshPrint(asOf: string | null | undefined, now: number): boolean {
  const t = nseTimeToEpoch(asOf)
  return t !== null && now - t <= NSE_PRINT_MAX_AGE_MS && t - now <= 2 * 60_000
}

/** True when a live tick arrived at `lastTickAt` (epoch ms; 0 = never) within LIVE_TICK_MAX_AGE_MS of `now`. */
export function isLiveTick(lastTickAt: number, now: number): boolean {
  return lastTickAt > 0 && now - lastTickAt <= LIVE_TICK_MAX_AGE_MS && lastTickAt - now <= 60_000
}

// ── what counts as a live tick (round 4b: the round-3 rule counted EVERY monitor-socket message) ─────────────────
// The monitor socket also carries {pong}, {ok, subscribed} acks and {error} replies, and data-service keeps publishing
// ICICI REST quotes on a weekday NSE holiday (its poller has no holiday check) whose last trade is the previous
// session's. Only a QUOTE whose own exchange time is fresh AND that is a new print for its symbol (price or traded
// volume changed since the last message for that symbol) is evidence that NSE is trading now. Breeze stamps an
// index quote with the fetch time (23 Oct: NIFTY ltt 15:35:52 after the 15:30 close), so a fresh stamp alone is not
// proof: an unchanged print never counts, and a symbol's first message only seeds the comparison.

/**
 * An exchange time stamp → epoch ms, or null when it is not one: NSE / Breeze REST "23-Oct-2026 15:35:52" (IST),
 * the Breeze websocket's "Fri Oct 23 15:35:52 2026" (IST), or ISO-8601 WITH a zone ("2026-10-23T15:35:52+05:30").
 * A zone-less ISO string or a bare number is refused (data-service's `ts` is its publish time, not a trade time).
 */
export function exchangeTimeToEpoch(v: unknown): number | null {
  if (typeof v !== 'string') return null
  const s = v.trim()
  const nse = nseTimeToEpoch(s)
  if (nse !== null) return nse
  const ws = /^(?:[A-Za-z]{3}\s+)?([A-Za-z]{3})\s+(\d{1,2})\s+(\d{1,2}):(\d{2}):(\d{2})\s+(\d{4})$/.exec(s)
  if (ws) {
    const mon = MONTH_INDEX[ws[1].toUpperCase()]
    if (mon === undefined) return null
    return Date.UTC(Number(ws[6]), mon, Number(ws[2]), Number(ws[3]), Number(ws[4]), Number(ws[5])) - 330 * 60_000
  }
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})$/.test(s)) {
    const t = Date.parse(s)
    return Number.isFinite(t) ? t : null
  }
  return null
}

/** One quote message of the monitor socket, reduced to what the live-evidence rule needs. */
export interface QuotePrint {
  sym: string
  /** Price + traded volume: a different key is a new print for the symbol. */
  key: string
  /** Exchange time of the last trade (epoch ms), null when the message carries none. */
  at: number | null
}

const num = (v: unknown): number | null => {
  const n = typeof v === 'number' ? v : typeof v === 'string' && v.trim() !== '' ? Number(v) : NaN
  return Number.isFinite(n) ? n : null
}

/**
 * A monitor-socket message as a quote print, or null for anything else: a heartbeat reply ({pong}), a subscription
 * ack ({ok, subscribed}), an error ({error}), or a message without a symbol or a numeric last price.
 */
export function quotePrint(msg: unknown): QuotePrint | null {
  if (!msg || typeof msg !== 'object' || Array.isArray(msg)) return null
  const m = msg as Record<string, unknown>
  if ('error' in m || 'pong' in m || 'subscribed' in m) return null
  const p = m.payload && typeof m.payload === 'object' && !Array.isArray(m.payload) ? (m.payload as Record<string, unknown>) : null
  if (!p) return null
  const symRaw = typeof m.symbol === 'string' ? m.symbol : typeof p.symbol === 'string' ? p.symbol : ''
  const sym = symRaw.trim().toUpperCase()
  if (!sym) return null
  const ltp = num(p.ltp) ?? num(p.last_price) ?? num(p.lastPrice) ?? num(p.last) ?? num(p.price)
  if (ltp === null) return null
  const vol = num(p.total_quantity_traded) ?? num(p.volume) ?? num(p.ttq)
  const at = exchangeTimeToEpoch(p.ltt) ?? exchangeTimeToEpoch(p.last_trade_time) ?? exchangeTimeToEpoch(p.exchange_time)
  return { sym, key: `${ltp}|${vol ?? ''}`, at }
}

/**
 * True when `p` is evidence that the market is trading now: its exchange time is within LIVE_TICK_MAX_AGE_MS of
 * `now` (a little clock skew allowed) AND it differs from `prevKey`, the previous print seen for that symbol
 * (undefined = first message: it only seeds the comparison). A stale replay, a repeated print and a message
 * without an exchange time never count.
 */
export function isLivePrint(p: QuotePrint, prevKey: string | undefined, now: number): boolean {
  if (p.at === null || prevKey === undefined || prevKey === p.key) return false
  return now - p.at <= LIVE_TICK_MAX_AGE_MS && p.at - now <= 60_000
}

// ── stale quotes in market hours (P9) ─────────────────────────────────────────────────────────────────────────

/** A NIFTY quote older than this while NSE is in its regular session reads STALE instead of ● LIVE / ● NSE. */
export const QUOTE_STALE_MS = 5 * 60_000
/** The STALE rule applies from 09:20 IST (pre-open and the first prints are excluded) to the 15:30 close. */
const STALE_FROM_MIN = 9 * 60 + 20
const STALE_TO_MIN = 15 * 60 + 30

function istMinuteOfDay(epochMs: number): number {
  return Math.floor((((epochMs + 330 * 60_000) % 86_400_000) + 86_400_000) % 86_400_000 / 60_000)
}

/** HH:MM IST of an epoch, without Intl (pure, the same under node and in WebKit). */
export function istHhmm(epochMs: number): string {
  const m = istMinuteOfDay(epochMs)
  return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`
}

/** True when a quote stamped `quoteAt` is more than QUOTE_STALE_MS old during NSE's regular hours (09:20–15:30 IST). */
export function isStaleQuote(quoteAt: number | null | undefined, now: number): boolean {
  if (quoteAt == null || !Number.isFinite(quoteAt)) return false
  const m = istMinuteOfDay(now)
  return m >= STALE_FROM_MIN && m < STALE_TO_MIN && now - quoteAt > QUOTE_STALE_MS
}

/** The exchange time of a stored / streamed ICICI quote: its `ltt`, else the publish `ts` (epoch s or ms). */
export function liveQuoteAt(q: { ts?: unknown; raw?: Record<string, unknown> | null } | null | undefined): number | null {
  if (!q) return null
  const ltt = exchangeTimeToEpoch(q.raw?.ltt)
  if (ltt !== null) return ltt
  const ts = num(q.ts)
  if (ts === null || ts <= 0) return null
  return ts < 1e12 ? ts * 1000 : ts
}

/**
 * The header's NIFTY source: the ICICI stream, else NSE's live index, else the last stored ICICI quote (STALE).
 * P9: a stream that stopped (its quote more than QUOTE_STALE_MS older than NSE's print) gives way to NSE.
 */
export function pickNiftySource(i: { wsLtp: unknown; wsAt: number | null; nseLast: unknown; nseAt: number | null; storedLtp: unknown }):
  'ICICI' | 'NSE' | 'STALE' | null {
  const has = (v: unknown) => v !== null && v !== undefined
  const wsBehind = i.wsAt !== null && i.nseAt !== null && i.nseAt - i.wsAt > QUOTE_STALE_MS
  if (has(i.wsLtp) && !(wsBehind && has(i.nseLast))) return 'ICICI'
  if (has(i.nseLast)) return 'NSE'
  return has(i.storedLtp) ? 'STALE' : null
}

/**
 * What the stock window's price is (CT-07): LIVE (broker ticks), DELAYED · <as of> (a delayed quote while NSE
 * trades) or CLOSE <day> (NSE closed). "NSE trades" is the same evidence as the header's NIFTY chip: the calendar,
 * a live tick (useFeedState's marketOpen) OR a fresh NSE index print, so a session the calendar does not know
 * (Muhurat) never reads CLOSE <day> while NSE prints. `asOf` is the quote's own time (ISO, NSE or Breeze stamp); a
 * stamp from an earlier IST day carries its date.
 */
export function stockPriceMarker(i: { live: boolean; marketOpen: boolean; asOf: string | null | undefined; nseStamp: string | null | undefined; now: number }): string {
  const printing = i.marketOpen || isFreshPrint(i.nseStamp, i.now)
  if (!printing) {
    const day = sessionDay(i.nseStamp)
    return day ? `CLOSE ${day}` : 'CLOSED'
  }
  if (i.live) return 'LIVE'
  const t = exchangeTimeToEpoch(i.asOf)
  if (t === null) return 'DELAYED'
  const sameDay = Math.floor((t + 330 * 60_000) / 86_400_000) === Math.floor((i.now + 330 * 60_000) / 86_400_000)
  if (sameDay) return `DELAYED · ${istHhmm(t)} IST`
  const d = new Date(t + 330 * 60_000)
  return `DELAYED · ${String(d.getUTCDate()).padStart(2, '0')}-${MONTHS[d.getUTCMonth()]} ${istHhmm(t)} IST`
}

/** Poll interval for a header chrome poll: `baseMs` while live and visible, else at least `idleMs`. */
export function chromePollMs(baseMs: number, s: { marketOpen: boolean; hidden: boolean }, idleMs = IDLE_POLL_MS): number {
  return s.marketOpen && !s.hidden ? baseMs : Math.max(baseMs, idleMs)
}

export type FeedTone = 'live' | 'delayed' | 'closed' | 'down'

export interface FeedChip {
  text: string
  tone: FeedTone
  title: string
}

const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']

/** "23-Oct-2026 15:30" (NSE) or "2026-10-23…" (ISO) → "23-OCT"; null when unrecognised. */
export function sessionDay(asOf: string | null | undefined): string | null {
  if (!asOf || typeof asOf !== 'string') return null
  const nse = /^(\d{1,2})-([A-Za-z]{3})-\d{4}/.exec(asOf.trim())
  if (nse) return `${nse[1].padStart(2, '0')}-${nse[2].toUpperCase()}`
  const iso = /^\d{4}-(\d{2})-(\d{2})/.exec(asOf.trim())
  if (iso) {
    const m = Number(iso[1])
    return m >= 1 && m <= 12 ? `${iso[2]}-${MONTHS[m - 1]}` : null
  }
  return null
}

/** The header's NIFTY source chip. `src` as computed by MarketCommandHeader (ICICI stream → NSE → stored quote). */
export function niftySourceChip(i: {
  src: 'ICICI' | 'NSE' | 'STALE' | null
  wsConnected: boolean
  marketOpen: boolean
  linkDown: boolean
  asOf?: string | null
  /** Epoch ms for the NSE print freshness test (omit: the calendar alone decides, as before). */
  now?: number
  /** Exchange time of the quote shown (epoch ms): older than QUOTE_STALE_MS in NSE's regular hours reads STALE (P9). */
  quoteAt?: number | null
}): FeedChip {
  if (i.linkDown) return { text: '◌ STALE', tone: 'down', title: 'ui-api unreachable: showing the last value received' }
  if (i.src === null || i.src === 'STALE') {
    return { text: '◌ STALE', tone: 'down', title: 'last stored ICICI quote: may be from an earlier session' }
  }
  // an NSE print from the last few minutes means NSE is printing (a special session the calendar does not know)
  const printing = i.src === 'NSE' && i.now !== undefined && isFreshPrint(i.asOf, i.now)
  if (!i.marketOpen && !printing) {
    const day = sessionDay(i.asOf)
    return {
      text: day ? `CLOSE ${day}` : 'CLOSED',
      tone: 'closed',
      title: `NSE closed: last session's close${i.asOf ? ` · ${i.asOf}` : ''}`,
    }
  }
  // NSE is open but this quote stopped updating (a stalled stream or NSE feed): never ● LIVE / ● NSE on an old value
  if (i.now !== undefined && i.quoteAt != null && isStaleQuote(i.quoteAt, i.now)) {
    const at = istHhmm(i.quoteAt)
    return { text: `◌ STALE ${at}`, tone: 'down',
             title: `last ${i.src === 'ICICI' ? 'ICICI' : 'NSE'} quote at ${at} IST: more than ${QUOTE_STALE_MS / 60_000} min old while NSE is open` }
  }
  if (i.src === 'ICICI') {
    return i.wsConnected
      ? { text: '● LIVE', tone: 'live', title: 'ICICI Breeze stream' }
      : { text: '● ICICI', tone: 'live', title: 'ICICI Breeze quote (stream reconnecting)' }
  }
  return { text: '● NSE', tone: 'delayed', title: `NSE live index, ≈1 min delayed${i.asOf ? ` · ${i.asOf}` : ''}` }
}

/** A socket-state chip (watchlist bar 'STREAMING', ALFA 'WS LIVE'): `live` / `offline` are the page's own words. */
export function socketChip(i: { connected: boolean; marketOpen: boolean; linkDown: boolean; live: string; offline: string }): FeedChip {
  if (i.linkDown) return { text: '◌ LINK DOWN', tone: 'down', title: 'ui-api unreachable: no ticks until it is back' }
  if (!i.connected) return { text: i.offline, tone: 'down', title: 'live socket not connected' }
  if (!i.marketOpen) return { text: '● SOCKET OK · NO TICKS', tone: 'closed', title: 'socket connected; NSE is closed, so no ticks arrive' }
  return { text: i.live, tone: 'live', title: 'live socket connected' }
}

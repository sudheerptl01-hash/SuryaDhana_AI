'use client'

/**
 * useLiveQuotes — the terminal's ONE client of the live NSE quote service (reports/live_nse, contract "LV-UI"):
 * `GET /api/live/quotes?symbols=A,B` (ui-api, ≤ 2 s SWR, single flight) ← data-service `/live/quotes`, which answers
 * every NSE symbol (stocks and indices: 'NIFTY 50', 'NIFTY BANK', 'INDIA VIX', …) from, in order, the Breeze websocket
 * tick (≤ 5 s = live) → NSE's website (≈ 1 min, delayed) → the last EOD close (closed after the session, stale during
 * it). Never Yahoo. Requesting a symbol ENSURES its websocket subscription server-side (union + TTL), so a pane only
 * has to ask.
 *
 * One poller per window: every mounted consumer registers its symbols; each symbol is due at the fastest interval any
 * consumer holding it asked for (never under 2 s), and one request (≤ 300 symbols, the contract's cap) carries every
 * symbol due now — so the header's 2 s NIFTY and a map's 15 s names share the poller without the map's names riding
 * the header's cadence. Everything slows to 30 s while NSE is closed or the window is hidden, backs off
 * 2 → 4 → 8 → 30 s on errors, and checks a missing route (404, the service not deployed yet) once a minute. A newly asked symbol is fetched at once (alone), so a hover card does not wait for
 * the next round. The wire shape is isolated in `parseLiveQuotes`; the chip rules in `quoteSource` / `liveSourceInfo`;
 * the hover card's time line in `quoteLine`. All pure, unit-tested by ui/components/__tests__/live.check.ts.
 *
 * Honesty (binding): a row is LIVE only when the server said so AND this window received it in the last
 * LOCAL_LIVE_MAX_S seconds (a stalled poller never keeps a LIVE chip); NSE website rows are DELAYED with their age;
 * after the close every price reads CLOSE <session date>; a symbol the service cannot price is 'unavailable' (never
 * filled from another source here).
 */
import { useEffect, useMemo, useSyncExternalStore } from 'react'
import type { SourceInfo } from '../components/terminal/source'

// ── wire shape (the contract) ───────────────────────────────────────────────────────────────────────────────

export type LiveSource = 'breeze_ws' | 'nse_api' | 'eod'
export type LiveState = 'live' | 'delayed' | 'stale' | 'closed' | 'unavailable'
export type LiveMarketState = 'open' | 'pre-open' | 'closed'

export interface LiveQuote {
  symbol: string
  price: number | null
  change: number | null
  change_pct: number | null
  prev_close: number | null
  open: number | null
  day_high: number | null
  day_low: number | null
  volume: number | null
  value_cr: number | null
  bid: number | null
  ask: number | null
  /** exchange time of the last trade, ISO with +05:30 (null when the source gives none) */
  ltt: string | null
  source: LiveSource | string
  /** the server's age of the row at its as_of, seconds */
  age_s: number | null
  state: LiveState
  reason: string | null
  /** epoch ms this window received the row: age now = age_s + (now − received_at) / 1000 */
  received_at: number
}

export interface LiveMarket { state: LiveMarketState; session_date: string | null }

export interface LiveBatch { asOf: string | null; market: LiveMarket | null; quotes: Record<string, LiveQuote> }

/** The contract's cap per request. */
export const MAX_SYMBOLS_PER_REQUEST = 300
/** Never poll faster than this, whatever a consumer asks. */
export const MIN_INTERVAL_MS = 2_000
export const DEFAULT_INTERVAL_MS = 3_000
/** NSE closed, or the window hidden: prices do not move (or nobody looks). */
export const IDLE_INTERVAL_MS = 30_000
/** The route answered 404 (not deployed yet): look again this often. */
export const MISSING_RETRY_MS = 60_000
export const BACKOFF_MS = [2_000, 4_000, 8_000, 30_000] as const
/** A row the server called live stays live on screen only this long after we received it (a stalled poll ≠ live). */
export const LOCAL_LIVE_MAX_S = 10
/** a /api/live/quotes request older than this is abandoned and counted as a feed error */
export const LIVE_REQUEST_TIMEOUT_MS = 7000
/** Rows nobody asks for any more are dropped after this (bounded memory). */
export const EVICT_AFTER_MS = 5 * 60_000
export const MAX_ROWS = 1_500

const STATES: readonly LiveState[] = ['live', 'delayed', 'stale', 'closed', 'unavailable']
const MARKET_STATES: readonly LiveMarketState[] = ['open', 'pre-open', 'closed']

const num = (v: unknown): number | null => {
  const n = typeof v === 'number' ? v : typeof v === 'string' && v.trim() !== '' ? Number(v) : NaN
  return Number.isFinite(n) ? n : null
}
const str = (v: unknown): string | null => (typeof v === 'string' && v.trim() !== '' ? v.trim() : null)

/**
 * An NSE symbol as the live service keys it: upper case, no '.NS'; index names keep their spaces ('NIFTY 50').
 * Null for anything that is not an NSE code: a BSE '.BO' code, a Yahoo form ('^NSEI', 'INR=X', 'GC=F', 'AAPL' with a
 * suffix), an empty or over-long string. (A bare US ticker such as 'AAPL' is indistinguishable from an NSE code here:
 * callers pass NSE symbols only.)
 */
export function normLiveSymbol(raw: string | null | undefined): string | null {
  if (typeof raw !== 'string') return null
  let s = raw.trim().toUpperCase().replace(/\s+/g, ' ')
  if (s.endsWith('.NS')) s = s.slice(0, -3).trimEnd()
  // the service's own rule (ui-api routers/live.py normalize_symbol): one bad symbol fails the whole batch with a 422,
  // so anything it would refuse never leaves the window — a stock code (1–20 of A–Z 0–9 & -) or an index name (2–6
  // such words, ≤ 40 characters); '.BO', '^NSEI', 'INR=X', 'GC=F' … are not NSE codes
  if (STOCK_RE.test(s) || (s.length <= 40 && INDEX_RE.test(s))) return s
  return null
}
const STOCK_RE = /^[A-Z0-9&\-]{1,20}$/
const INDEX_RE = /^[A-Z0-9&\-]+(?: [A-Z0-9&\-]+){1,5}$/

/** The wire body → validated rows (never trust the raw payload: types, enums, finiteness). */
export function parseLiveQuotes(body: unknown, receivedAt: number): LiveBatch {
  const b = body && typeof body === 'object' && !Array.isArray(body) ? (body as Record<string, unknown>) : {}
  const m = b.market && typeof b.market === 'object' ? (b.market as Record<string, unknown>) : null
  const market: LiveMarket | null = m && MARKET_STATES.includes(m.state as LiveMarketState)
    ? { state: m.state as LiveMarketState, session_date: str(m.session_date) }
    : null
  const quotes: Record<string, LiveQuote> = {}
  const raw = b.quotes && typeof b.quotes === 'object' && !Array.isArray(b.quotes) ? (b.quotes as Record<string, unknown>) : {}
  for (const [k, v] of Object.entries(raw)) {
    const sym = normLiveSymbol(k)
    if (!sym || !v || typeof v !== 'object') continue
    const q = v as Record<string, unknown>
    const state = STATES.includes(q.state as LiveState) ? (q.state as LiveState) : 'unavailable'
    const price = num(q.price)
    quotes[sym] = {
      symbol: sym,
      price: state === 'unavailable' ? null : price,
      change: num(q.change), change_pct: num(q.change_pct), prev_close: num(q.prev_close), open: num(q.open),
      day_high: num(q.day_high), day_low: num(q.day_low), volume: num(q.volume), value_cr: num(q.value_cr),
      bid: num(q.bid), ask: num(q.ask),
      ltt: str(q.ltt),
      source: str(q.source) ?? 'unknown',
      age_s: num(q.age_s),
      // a row without a price is not a quote, whatever its state says
      state: price == null ? 'unavailable' : state,
      reason: str(q.reason),
      received_at: receivedAt,
    }
  }
  return { asOf: str(b.as_of), market, quotes }
}

// ── chip rules ──────────────────────────────────────────────────────────────────────────────────────────────

/** The chip's feed name for a row's source. */
export function sourceName(src: string | null | undefined): string {
  return src === 'breeze_ws' ? 'BREEZE' : src === 'nse_api' ? 'NSE' : src === 'eod' ? 'NSE EOD' : src ? String(src).toUpperCase() : ''
}

/** Seconds since the row's as-of, now (server age at receipt + time since); null when the row carries no age at all. */
export function quoteAgeS(q: Pick<LiveQuote, 'age_s' | 'received_at' | 'ltt'>, now: number): number | null {
  if (q.age_s != null) return Math.max(0, q.age_s + (now - q.received_at) / 1000)
  const t = q.ltt ? Date.parse(q.ltt) : NaN
  return Number.isFinite(t) ? Math.max(0, (now - t) / 1000) : null
}

/** 'YYYY-MM-DD' (IST) of an ISO time; null when unparsable. */
function istDay(iso: string | null | undefined): string | null {
  if (!iso) return null
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) return iso
  const t = Date.parse(iso)
  return Number.isFinite(t) ? new Date(t + 330 * 60_000).toISOString().slice(0, 10) : null
}

/** 'HH:MM:SS' IST of an ISO time; '' when unparsable. */
export function istClock(iso: string | null | undefined): string {
  const t = iso ? Date.parse(iso) : NaN
  if (!Number.isFinite(t)) return ''
  return new Date(t + 330 * 60_000).toISOString().slice(11, 19)
}

/** One row's SourceChip: LIVE · BREEZE · 2s / DELAYED · NSE · 48s / STALE · … / CLOSE · 05 NOV / OFFLINE (+ why). */
export function quoteSource(q: LiveQuote | null | undefined, market: LiveMarket | null, now: number): SourceInfo {
  if (!q || q.state === 'unavailable' || q.price == null) {
    return { state: 'offline', source: 'LIVE', asOf: null, ageDays: null, hint: q?.reason ?? 'no NSE quote for this symbol' }
  }
  const source = sourceName(q.source)
  const ageS = quoteAgeS(q, now)
  const local = (now - q.received_at) / 1000
  const closed = q.state === 'closed' || (market?.state === 'closed' && q.state !== 'stale')
  if (closed) {
    const day = istDay(q.ltt) ?? market?.session_date ?? null
    return { state: 'closed', source, asOf: day, ageDays: null, hint: q.reason ?? `last trade ${q.ltt ?? 'n/a'}` }
  }
  if (q.state === 'live' && local <= LOCAL_LIVE_MAX_S) return { state: 'live', source, asOf: q.ltt, ageDays: 0, ageS, hint: q.reason }
  if (q.state === 'live' || q.state === 'delayed') {
    return { state: 'delayed', source, asOf: q.ltt, ageDays: 0, ageS,
             hint: q.reason ?? (q.state === 'live' ? 'live row, but this window has not refreshed it' : source === 'NSE' ? "NSE's website, about 1 min behind" : null) }
  }
  return { state: 'stale', source, asOf: q.ltt, ageDays: 0, ageS, hint: q.reason ?? 'older than expected while NSE trades' }
}

const RANK: Record<string, number> = { live: 0, delayed: 1, stale: 2, closed: 3, offline: 4 }

/**
 * A pane's SourceChip over its rows: every row closed → CLOSE <session>; otherwise the WORST row state with that
 * state's oldest age, and a mix count when only some rows are live ('DELAYED · NSE · 48s · 40/52 LIVE'). Null while
 * the service has not answered (status 'idle' / 'loading' / 'missing'): the pane keeps its own chip.
 */
export function liveSourceInfo(rows: readonly (LiveQuote | null | undefined)[], market: LiveMarket | null, status: FeedStatus, now: number): SourceInfo | null {
  if (status === 'idle' || status === 'loading' || status === 'missing') return null
  const infos = rows.map(q => quoteSource(q, market, now))
  if (!infos.length) return status === 'error' ? { state: 'offline', source: 'LIVE', asOf: null, ageDays: null, hint: 'live quote service not answering' } : null
  const priced = infos.filter(i => i.state !== 'offline')
  if (status === 'error') {
    return { state: 'offline', source: 'LIVE', asOf: null, ageDays: null, hint: 'live quote service not answering: the prices shown are the last received' }
  }
  if (!priced.length) return { state: 'offline', source: 'LIVE', asOf: null, ageDays: null, hint: infos[0].hint ?? 'no NSE quote' }
  if (priced.every(i => i.state === 'closed')) {
    const days = priced.map(i => i.asOf).filter((d): d is string => !!d).sort()
    const day = days.length ? days[days.length - 1] : market?.session_date ?? null
    return { state: 'closed', source: priced[0].source, asOf: day, ageDays: null, hint: `${priced.length} prices at the last session's close` }
  }
  const open = priced.filter(i => i.state !== 'closed')
  const worst = open.reduce((a, i) => (RANK[i.state] > RANK[a.state] ? i : a), open[0])
  const same = open.filter(i => i.state === worst.state)
  const ageS = same.reduce<number | null>((a, i) => (i.ageS != null && (a == null || i.ageS > a) ? i.ageS : a), null)
  const live = open.filter(i => i.state === 'live').length
  const bySource = new Map<string, number>()
  for (const i of open) bySource.set(`${i.state} ${i.source}`, (bySource.get(`${i.state} ${i.source}`) ?? 0) + 1)
  const breakdown = [...bySource.entries()].map(([k, n]) => `${n} ${k.toUpperCase()}`).join(' · ')
  const missing = infos.length - priced.length
  return {
    state: worst.state, source: worst.source, asOf: worst.asOf ?? null, ageDays: 0, ageS,
    mix: { live, total: infos.length },
    hint: `${breakdown}${missing ? ` · ${missing} without a quote` : ''}`,
  }
}

/**
 * The hover card / stock window time line: 'BREEZE LIVE · 10:42:13 IST · 1s ago', 'NSE DELAYED · 10:41:20 IST · 52s
 * ago', 'CLOSE 05 NOV · last trade 15:29:59 IST', 'STALE · 10:12:00 IST · 31m ago', 'no live quote · <why>'.
 */
export function quoteLine(q: LiveQuote | null | undefined, market: LiveMarket | null, now: number): string {
  const s = quoteSource(q, market, now)
  if (!q || s.state === 'offline') return `no live quote · ${s.hint ?? 'unavailable'}`
  const clock = istClock(q.ltt)
  const at = clock ? `${clock} IST` : 'time n/a'
  const age = s.ageS != null ? `${fmtAge(s.ageS)} ago` : ''
  switch (s.state) {
    case 'live': return `${s.source} LIVE · ${at}${age ? ` · ${age}` : ''}`
    case 'delayed': return `${s.source} DELAYED · ${at}${age ? ` · ${age}` : ''}`
    case 'closed': {
      const d = s.asOf && /^\d{4}-(\d{2})-(\d{2})$/.exec(s.asOf)
      const MON = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
      return `CLOSE${d ? ` ${d[2]} ${MON[Number(d[1]) - 1]}` : ''}${clock ? ` · last trade ${clock} IST` : ''}`
    }
    default: return `STALE · ${s.source} · ${at}${age ? ` · ${age}` : ''}`
  }
}

/** Same rule as the chip ('48s', '6m', '3h'). */
export function fmtAge(ageS: number): string {
  const a = Math.max(0, ageS)
  return a < 90 ? `${Math.round(a)}s` : a < 90 * 60 ? `${Math.round(a / 60)}m` : `${Math.round(a / 3600)}h`
}

/**
 * Overlay a live row onto a quote-shaped record (the news-scanner `Quote` shape WTCH / ALRT / BRF use): price, change,
 * day range and volume come from the live row; everything else (name, 52-week range, sparkline) stays. A row without
 * a price leaves the record untouched.
 */
/** true for the stored EOD row the service returns DURING the session (state 'stale', source 'eod'): its change is the
 *  previous session's move and must never be shown as today's (check:LV-UI major). */
export function isStaleEod(q: { source?: string | null; state?: string | null } | null | undefined): boolean {
  return !!q && q.source === 'eod' && q.state === 'stale'
}

export function overlayQuote<T extends Record<string, unknown>>(base: T | null | undefined, q: LiveQuote | null | undefined): T | null | undefined {
  if (!q || q.price == null || q.state === 'unavailable') return base
  const o: Record<string, unknown> = { ...(base ?? {}) }
  o.price = q.price
  const prevSessionMove = isStaleEod(q)               // keep the base row's change: the EOD row's is yesterday's
  if (q.change_pct != null && !prevSessionMove) o.change_pct = q.change_pct
  if (q.change != null && !prevSessionMove) o.change = q.change
  if (q.prev_close != null) o.prev_close = q.prev_close
  if (q.day_high != null) o.day_high = q.day_high
  if (q.day_low != null) o.day_low = q.day_low
  if (q.volume != null) o.volume = q.volume
  o.available = true
  o.live_source = q.source
  o.live_state = q.state
  return o as T
}

// ── the store (one per window) ──────────────────────────────────────────────────────────────────────────────

export type FeedStatus = 'idle' | 'loading' | 'ok' | 'error' | 'missing'

export interface LiveSnapshot {
  version: number
  status: FeedStatus
  market: LiveMarket | null
  asOf: string | null
  lastOkAt: number
  error: string | null
  quotes: ReadonlyMap<string, LiveQuote>
}

export interface LiveStoreDeps {
  /** GET a URL; resolve {status, body} (body may be null) or reject on a network error */
  get: (url: string, signal: AbortSignal) => Promise<{ status: number; body: unknown }>
  now: () => number
  setTimer: (fn: () => void, ms: number) => unknown
  clearTimer: (t: unknown) => void
  hidden: () => boolean
}

export interface LiveStore {
  register(id: number, symbols: readonly string[], intervalMs: number): void
  unregister(id: number): void
  subscribe(cb: () => void): () => void
  getVersion(): number
  snapshot(): LiveSnapshot
  /** the union being polled (sorted) — tests and SYS */
  union(): string[]
  /** poll every symbol now (tests; the visibility handler) */
  pollNow(): Promise<void>
  /** the delay the scheduler will use for the next poll (tests) */
  nextDelay(): number
  dispose(): void
}

export function createLiveStore(deps: LiveStoreDeps): LiveStore {
  const subs = new Map<number, { symbols: string[]; intervalMs: number }>()
  const quotes = new Map<string, LiveQuote>()
  const listeners = new Set<() => void>()
  let version = 0
  let status: FeedStatus = 'idle'
  let market: LiveMarket | null = null
  let asOf: string | null = null
  let lastOkAt = 0
  let error: string | null = null
  let fails = 0
  let timer: unknown = null
  let inflight: Promise<void> | null = null
  let ctl: AbortController | null = null
  let pendingNew = new Set<string>()
  /** per symbol: when it is next due (epoch ms) */
  const due = new Map<string, number>()
  /** a symbol polled at about the same time as another one rides along (one request, not two) */
  const SLACK_MS = 400
  let lastRequestAt = 0
  let disposed = false
  let snap: LiveSnapshot | null = null

  const bump = () => {
    version++
    snap = null
    for (const l of listeners) {
      try { l() } catch { /* a consumer must not break the poller */ }
    }
  }
  const union = (): string[] => {
    const u = new Set<string>()
    for (const s of subs.values()) for (const x of s.symbols) u.add(x)
    return [...u].sort()
  }
  const idle = () => deps.hidden() || market?.state === 'closed'
  /** the cadence of one symbol: the fastest interval of any consumer holding it (never under 2 s; ≥ 30 s when idle) */
  const intervalOf = (sym: string): number => {
    let ms = Infinity
    for (const s of subs.values()) if (s.symbols.includes(sym)) ms = Math.min(ms, s.intervalMs)
    const base = Math.max(MIN_INTERVAL_MS, Number.isFinite(ms) ? ms : DEFAULT_INTERVAL_MS)
    return idle() ? Math.max(base, IDLE_INTERVAL_MS) : base
  }
  const nextDelay = (): number => {
    if (status === 'missing') return MISSING_RETRY_MS
    if (fails > 0) return BACKOFF_MS[Math.min(fails - 1, BACKOFF_MS.length - 1)]
    const all = union()
    if (!all.length) return IDLE_INTERVAL_MS
    const t = deps.now()
    let next = Infinity
    for (const s of all) next = Math.min(next, (due.get(s) ?? t) - t)
    return Math.max(500, Math.min(Number.isFinite(next) ? next : DEFAULT_INTERVAL_MS, IDLE_INTERVAL_MS))
  }
  const schedule = (ms: number) => {
    if (disposed) return
    if (timer != null) deps.clearTimer(timer)
    timer = deps.setTimer(() => { timer = null; void run(false) }, ms)
  }

  async function fetchBatch(symbols: string[]): Promise<void> {
    for (let i = 0; i < symbols.length; i += MAX_SYMBOLS_PER_REQUEST) {
      const chunk = symbols.slice(i, i + MAX_SYMBOLS_PER_REQUEST)
      ctl = new AbortController()
      lastRequestAt = deps.now()
      const r = await deps.get(`/api/live/quotes?symbols=${encodeURIComponent(chunk.join(','))}`, ctl.signal)
      if (r.status === 404) { status = 'missing'; error = 'live quote service not deployed (404)'; return }
      if (r.status < 200 || r.status >= 300) throw new Error(`HTTP ${r.status}`)
      const batch = parseLiveQuotes(r.body, deps.now())
      for (const [k, q] of Object.entries(batch.quotes)) quotes.set(k, q)
      // a symbol we asked for and the server did not return is unavailable, not silently absent
      for (const k of chunk) {
        if (!(k in batch.quotes) && !quotes.has(k)) {
          quotes.set(k, { symbol: k, price: null, change: null, change_pct: null, prev_close: null, open: null, day_high: null, day_low: null,
                          volume: null, value_cr: null, bid: null, ask: null, ltt: null, source: 'none', age_s: null, state: 'unavailable',
                          reason: 'not returned by the live quote service', received_at: deps.now() })
        }
      }
      if (batch.market) market = batch.market
      asOf = batch.asOf ?? asOf
      status = 'ok'; error = null; lastOkAt = deps.now()
    }
  }

  function evict(keep: Set<string>) {
    const t = deps.now()
    for (const [k, q] of quotes) if (!keep.has(k) && t - q.received_at > EVICT_AFTER_MS) quotes.delete(k)
    if (quotes.size > MAX_ROWS) {
      const old = [...quotes.values()].filter(q => !keep.has(q.symbol)).sort((a, b) => a.received_at - b.received_at)
      for (const q of old.slice(0, quotes.size - MAX_ROWS)) quotes.delete(q.symbol)
    }
  }

  async function run(onlyNew: boolean): Promise<void> {
    if (disposed) return
    if (inflight) { await inflight; if (!onlyNew) return }
    const all = union()
    if (!all.length) { status = status === 'missing' ? 'missing' : 'idle'; return }
    const t0 = deps.now()
    // a regular round carries every symbol due now (a 404 or an error round retries everything)
    const dueNow = status === 'missing' || fails > 0 ? all : all.filter(s => (due.get(s) ?? 0) <= t0 + SLACK_MS)
    const want = onlyNew ? [...pendingNew].filter(s => all.includes(s)) : dueNow
    pendingNew = onlyNew ? new Set() : new Set([...pendingNew].filter(s => !want.includes(s)))
    if (!want.length) { if (!onlyNew && subs.size) schedule(nextDelay()); return }
    if (status === 'idle') { status = 'loading'; bump() }
    inflight = (async () => {
      try {
        await fetchBatch(want)
        fails = 0
        const t1 = deps.now()
        for (const s of want) due.set(s, t1 + intervalOf(s))
        for (const s of [...due.keys()]) if (!all.includes(s)) due.delete(s)
        evict(new Set(all))
      } catch (e) {
        if ((e as { name?: string })?.name === 'AbortError') return      // unmounted / disposed: not a feed failure
        fails++
        status = 'error'
        error = e instanceof Error ? e.message : 'live quote request failed'
      } finally {
        ctl = null
        bump()
      }
    })()
    try { await inflight } finally { inflight = null }
    if (subs.size && (!onlyNew || timer == null)) schedule(nextDelay())
  }

  return {
    register(id, symbols, intervalMs) {
      const before = new Set(union())
      subs.set(id, { symbols: [...symbols], intervalMs })
      // new to the poll, and not already held fresh (a cached row older than LOCAL_LIVE_MAX_S is fetched again at once)
      const t = deps.now()
      const added = symbols.filter(s => !before.has(s) && !(quotes.has(s) && t - quotes.get(s)!.received_at <= LOCAL_LIVE_MAX_S * 1000))
      if (!added.length) { if (timer == null && !inflight) schedule(0); return }
      for (const s of added) pendingNew.add(s)
      if (timer == null && !inflight) { schedule(0); return }           // nothing running: a full round now
      // a new symbol while polling: fetch it alone, soon (≥ 1 s after the last request, so a burst of hovers is one call)
      const wait = Math.max(50, 1_000 - (deps.now() - lastRequestAt))
      deps.setTimer(() => { void run(true) }, wait)
    },
    unregister(id) {
      subs.delete(id)
      if (!subs.size) {
        if (timer != null) { deps.clearTimer(timer); timer = null }
        ctl?.abort()
      }
    },
    subscribe(cb) {
      listeners.add(cb)
      return () => { listeners.delete(cb) }
    },
    getVersion: () => version,
    snapshot() {
      if (!snap) snap = { version, status, market, asOf, lastOkAt, error, quotes }
      return snap
    },
    union,
    pollNow: () => { due.clear(); return run(false) },     // everything due now (the window became visible)
    nextDelay,
    dispose() {
      disposed = true
      if (timer != null) deps.clearTimer(timer)
      timer = null
      ctl?.abort()
      listeners.clear()
      subs.clear()
    },
  }
}

// ── the React side ──────────────────────────────────────────────────────────────────────────────────────────

let store: LiveStore | null = null
let nextId = 1

/**
 * GET with a deadline: a hung request (ui-api event-loop stall) becomes a FEED ERROR after `ms`, so the store backs off and
 * bumps its version; the caller's own abort (unmount / dispose) still surfaces as AbortError and stays silent
 * (check:LV-UI major). Exported for the node check.
 */
export async function timedGet(fetchImpl: (url: string, init: { signal: AbortSignal; headers: Record<string, string> }) => Promise<{ status: number; json: () => Promise<unknown> }>,
                               url: string, signal: AbortSignal | undefined, ms: number): Promise<{ status: number; body: unknown }> {
  const t = new AbortController()
  const onAbort = () => t.abort()
  signal?.addEventListener('abort', onAbort)
  const timer = setTimeout(() => t.abort(), ms)
  try {
    const r = await fetchImpl(url, { signal: t.signal, headers: { Accept: 'application/json' } })
    const body = await r.json().catch(() => null)
    return { status: r.status, body }
  } catch (e) {
    if (t.signal.aborted && !signal?.aborted) throw new Error(`live quote request timed out after ${ms / 1000} s`)
    throw e
  } finally {
    clearTimeout(timer)
    signal?.removeEventListener('abort', onAbort)
  }
}

function browserStore(): LiveStore {
  if (store) return store
  const s = createLiveStore({
    get: (url, signal) => timedGet(fetch, url, signal, LIVE_REQUEST_TIMEOUT_MS),
    now: () => Date.now(),
    setTimer: (fn, ms) => setTimeout(fn, ms),
    clearTimer: t => clearTimeout(t as ReturnType<typeof setTimeout>),
    hidden: () => typeof document !== 'undefined' && document.visibilityState === 'hidden',
  })
  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') void s.pollNow() })
  }
  store = s
  return s
}

export interface LiveQuotesResult {
  /** rows for the asked symbols that the service has answered, keyed by the normalised NSE symbol */
  quotes: Record<string, LiveQuote>
  market: LiveMarket | null
  status: FeedStatus
  /** the pane's chip over its rows (null until the service answers, or while it is not deployed: keep your own chip) */
  source: SourceInfo | null
  /** true once the service answered with at least one priced row for these symbols */
  available: boolean
  /** one row's chip */
  sourceFor: (symbol: string) => SourceInfo | null
  /** the hover-card style time line for one row */
  lineFor: (symbol: string) => string | null
  /** epoch ms of the render's clock (so a pane's ages agree with each other) */
  now: number
}

const SERVER_SNAPSHOT = 0
// stable identities for useSyncExternalStore (a new subscribe function per render would re-subscribe every render)
const subscribeStore = (cb: () => void) => browserStore().subscribe(cb)
const storeVersion = () => browserStore().getVersion()
const serverVersion = () => SERVER_SNAPSHOT

/**
 * One shared 1 s clock for every live hook (check:LV-UI major): a chip's age must keep growing while a request hangs, so
 * the hook re-derives on this tick, not only when a response lands — a stalled poll can never hold a LIVE chip. One
 * interval app-wide, started on the first subscriber and stopped with the last.
 */
const CLOCK_MS = 1000
const clock = { now: Date.now(), subs: new Set<() => void>(), timer: null as ReturnType<typeof setInterval> | null }
function subscribeClock(cb: () => void): () => void {
  clock.subs.add(cb)
  if (!clock.timer) clock.timer = setInterval(() => { clock.now = Date.now(); clock.subs.forEach(f => f()) }, CLOCK_MS)
  return () => {
    clock.subs.delete(cb)
    if (!clock.subs.size && clock.timer) { clearInterval(clock.timer); clock.timer = null }
  }
}
const clockNow = () => clock.now
const clockServer = () => 0
/** exported for the node check: the age a frozen store would show after `ms` without a response */
export function _clockForTest() { return { subscribeClock, clockNow, CLOCK_MS } }

const noopSubscribe = () => () => {}

/**
 * Live NSE quotes for `symbols` (NSE codes or index names; '.NS' is stripped; anything else is ignored). Empty list or
 * `enabled: false` = nothing polled. `intervalMs` (default 3 s, never under 2 s) is the cadence this pane wants; the
 * window's single poller runs at the fastest one asked.
 */
export function useLiveQuotes(symbols: readonly (string | null | undefined)[], opts: { intervalMs?: number; enabled?: boolean } = {}): LiveQuotesResult {
  const enabled = opts.enabled !== false
  const intervalMs = Math.max(MIN_INTERVAL_MS, opts.intervalMs ?? DEFAULT_INTERVAL_MS)
  const key = enabled
    ? [...new Set(symbols.map(normLiveSymbol).filter((s): s is string => !!s))].sort().join('|')
    : ''
  const s = typeof window === 'undefined' ? null : browserStore()
  const version = useSyncExternalStore(subscribeStore, storeVersion, serverVersion)
  const tick = useSyncExternalStore(key ? subscribeClock : noopSubscribe, clockNow, clockServer)   // ages advance with no response

  useEffect(() => {
    if (!s || !key) return
    const id = nextId++
    s.register(id, key.split('|'), intervalMs)
    return () => s.unregister(id)
  }, [s, key, intervalMs])

  return useMemo<LiveQuotesResult>(() => {
    const now = Math.max(Date.now(), tick)
    const snap = s?.snapshot()
    const syms = key ? key.split('|') : []
    const quotes: Record<string, LiveQuote> = {}
    for (const k of syms) {
      const q = snap?.quotes.get(k)
      if (q) quotes[k] = q
    }
    const status: FeedStatus = !key ? 'idle' : snap?.status ?? 'idle'
    const market = snap?.market ?? null
    const rows = syms.map(k => quotes[k])
    const answered = rows.filter((q): q is LiveQuote => !!q)
    const source = liveSourceInfo(answered.length ? rows : [], market, status, now)
    return {
      quotes, market, status, source, now,
      available: (status === 'ok' || status === 'error') && answered.some(q => q.price != null),
      sourceFor: (sym: string) => {
        const k = normLiveSymbol(sym)
        if (!k || status === 'missing' || status === 'idle') return null
        const q = quotes[k]
        return q ? quoteSource(q, market, now) : null
      },
      lineFor: (sym: string) => {
        const k = normLiveSymbol(sym)
        const q = k ? quotes[k] : undefined
        return q ? quoteLine(q, market, now) : null
      },
    }
  }, [version, tick, key, s])  // eslint-disable-line react-hooks/exhaustive-deps
}

/** Tests only: drop the window's store. */
export function resetLiveQuotesStore(): void {
  store?.dispose()
  store = null
}

// ── the feed's own status (SYS live-feeds panel) ────────────────────────────────────────────────────────────

export interface LiveStatus {
  state: 'OFF' | 'CONNECTING' | 'LIVE' | 'DEGRADED' | 'DISCONNECTED' | string
  subscribed: number | null
  ticks_per_min: number | null
  last_tick_age_s: number | null
  cap: number | null
  breeze_session: boolean | null
  nse_fallback: { ok: boolean | null; last_ok_at: string | null } | null
}

/** `GET /api/live/status` → the validated contract fields; null when the route is missing (404) or unreachable. */
export function parseLiveStatus(body: unknown): LiveStatus | null {
  if (!body || typeof body !== 'object' || Array.isArray(body)) return null
  const b = body as Record<string, unknown>
  const nf = b.nse_fallback && typeof b.nse_fallback === 'object' ? (b.nse_fallback as Record<string, unknown>) : null
  return {
    state: typeof b.state === 'string' ? b.state.toUpperCase() : 'UNKNOWN',
    subscribed: num(b.subscribed), ticks_per_min: num(b.ticks_per_min), last_tick_age_s: num(b.last_tick_age_s), cap: num(b.cap),
    breeze_session: typeof b.breeze_session === 'boolean' ? b.breeze_session : null,
    nse_fallback: nf ? { ok: typeof nf.ok === 'boolean' ? nf.ok : null, last_ok_at: str(nf.last_ok_at) } : null,
  }
}

export async function fetchLiveStatus(signal?: AbortSignal): Promise<{ status: number; data: LiveStatus | null }> {
  try {
    const r = await fetch('/api/live/status', { signal, headers: { Accept: 'application/json' } })
    if (!r.ok) return { status: r.status, data: null }
    return { status: r.status, data: parseLiveStatus(await r.json().catch(() => null)) }
  } catch {
    return { status: 0, data: null }
  }
}

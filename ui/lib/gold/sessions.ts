/**
 * Trading-session bands for the 24-hour gold chart (PLAN a.3 `d.24h`, G-KITCO §5.2), DST-aware, in IST.
 *
 * The chart's day is the CME Globex day: 18:00 ET → 17:00 ET (03:30 → 02:30 IST in US summer, 04:30 → 03:30 in
 * US winter), with the 17:00–18:00 ET maintenance hour hatched. Bands (IST): Sydney/Tokyo 03:30–11:30; Shanghai
 * (SGE) 06:30–09:00 & 11:00–13:00 plus the night session 17:30–00:00; London 12:30–21:00 (BST) / 13:30–22:00 (GMT);
 * New York 18:30–23:00 (EDT) / 19:30–00:00 (EST); MCX 09:00–23:30 (US summer) / 23:55 (US winter). IST has no DST.
 *
 * Pure module (no DOM, no imports): unit-tested by ui/components/__tests__/gold.check.ts. Minutes are IST
 * minutes-of-day; a band that crosses midnight is returned as two segments so the chart can draw it on one axis.
 */

export const IST_OFFSET_MIN = 330
const DAY_MIN = 1440

export interface Band {
  key: 'sydney' | 'shanghai' | 'london' | 'newyork' | 'mcx' | 'maintenance'
  name: string
  /** IST minutes of day, start inclusive, end exclusive; end may equal 1440 (midnight) */
  start: number
  end: number
}

/** Second Sunday of March → first Sunday of November, 02:00 local (US DST). Takes a UTC instant. */
export function usDstActive(t: number | Date): boolean {
  const d = typeof t === 'number' ? new Date(t) : t
  const y = d.getUTCFullYear()
  const start = Date.UTC(y, 2, nthSunday(y, 2, 2), 7)    // 02:00 EST = 07:00 UTC
  const end = Date.UTC(y, 10, nthSunday(y, 10, 1), 6)    // 02:00 EDT = 06:00 UTC
  const ms = d.getTime()
  return ms >= start && ms < end
}

/** Last Sunday of March 01:00 UTC → last Sunday of October 01:00 UTC (UK DST). */
export function ukDstActive(t: number | Date): boolean {
  const d = typeof t === 'number' ? new Date(t) : t
  const y = d.getUTCFullYear()
  const start = Date.UTC(y, 2, lastSunday(y, 2), 1)
  const end = Date.UTC(y, 9, lastSunday(y, 9), 1)
  const ms = d.getTime()
  return ms >= start && ms < end
}

function nthSunday(year: number, month: number, n: number): number {
  const first = new Date(Date.UTC(year, month, 1)).getUTCDay()
  return 1 + ((7 - first) % 7) + (n - 1) * 7
}

function lastSunday(year: number, month: number): number {
  const last = new Date(Date.UTC(year, month + 1, 0))
  return last.getUTCDate() - last.getUTCDay()
}

/** IST minute-of-day of a UTC instant. */
export function istMinutes(t: number | Date): number {
  const ms = typeof t === 'number' ? t : t.getTime()
  return (((Math.floor(ms / 60_000) + IST_OFFSET_MIN) % DAY_MIN) + DAY_MIN) % DAY_MIN
}

/** IST calendar date (YYYY-MM-DD) of a UTC instant. */
export function istDate(t: number | Date): string {
  const ms = (typeof t === 'number' ? t : t.getTime()) + IST_OFFSET_MIN * 60_000
  return new Date(ms).toISOString().slice(0, 10)
}

/** NY offset from IST in minutes: 570 (EDT) or 630 (EST). */
export function nyOffsetMin(usDst: boolean): number {
  return usDst ? 570 : 630
}

/** IST minute-of-day → NY minute-of-day. */
export function istToNy(istMin: number, usDst: boolean): number {
  return (((istMin - nyOffsetMin(usDst)) % DAY_MIN) + DAY_MIN) % DAY_MIN
}

/** The Globex open (18:00 ET) in IST minutes: 03:30 in US summer, 04:30 in US winter. */
export function globexOpenIst(usDst: boolean): number {
  return 18 * 60 + nyOffsetMin(usDst) - DAY_MIN
}

/** MCX evening close in IST minutes: 23:30 in US summer, 23:55 in US winter (shared/mcx_specs.evening_close). */
export function mcxCloseIst(usDst: boolean): number {
  return usDst ? 23 * 60 + 30 : 23 * 60 + 55
}

/** 'HH:MM' for an IST or NY minute-of-day. */
export function fmtHM(min: number): string {
  const m = ((min % DAY_MIN) + DAY_MIN) % DAY_MIN
  return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`
}

/** The session bands for a day, in IST minutes. Bands over midnight are split at 1440. */
export function sessionBands(opts: { usDst: boolean; ukDst: boolean }): Band[] {
  const { usDst, ukDst } = opts
  const ny = nyOffsetMin(usDst)
  const raw: Band[] = [
    { key: 'sydney', name: 'Sydney / Tokyo', start: 3 * 60 + 30, end: 11 * 60 + 30 },
    { key: 'shanghai', name: 'Shanghai (SGE)', start: 6 * 60 + 30, end: 9 * 60 },
    { key: 'shanghai', name: 'Shanghai (SGE)', start: 11 * 60, end: 13 * 60 },
    { key: 'shanghai', name: 'Shanghai (SGE) night', start: 17 * 60 + 30, end: DAY_MIN },
    { key: 'london', name: 'London', start: (ukDst ? 12 : 13) * 60 + 30, end: (ukDst ? 21 : 22) * 60 },
    { key: 'newyork', name: 'New York', start: 9 * 60 + ny, end: 13 * 60 + 30 + ny },          // 09:00–13:30 ET (PLAN a.3)
    { key: 'mcx', name: 'MCX', start: 9 * 60, end: mcxCloseIst(usDst) },
    { key: 'maintenance', name: 'CME maintenance (17:00–18:00 ET)', start: 17 * 60 + ny, end: 18 * 60 + ny },
  ]
  const out: Band[] = []
  for (const b of raw) {
    let s = b.start, e = b.end
    if (s >= DAY_MIN) { s -= DAY_MIN; e -= DAY_MIN }          // a band wholly after IST midnight (the CME maintenance hour)
    if (e <= DAY_MIN) { if (s < e) out.push({ ...b, start: s, end: e }); continue }
    out.push({ ...b, start: s, end: DAY_MIN })                   // a band across IST midnight: two segments
    if (e - DAY_MIN > 0) out.push({ ...b, start: 0, end: e - DAY_MIN })
  }
  return out
}

/**
 * Position of an IST minute on the 24-h chart axis that starts at the Globex open: 0 at the open, 1439 just before.
 * Lets a day's bars (18:00 ET → 17:00 ET) sit left to right without wrapping.
 */
export function axisPos(istMin: number, usDst: boolean): number {
  return (((istMin - globexOpenIst(usDst)) % DAY_MIN) + DAY_MIN) % DAY_MIN
}

/** The CME trade date (the ET date on which the session settles) of a UTC instant. */
export function cmeTradeDate(t: number | Date, usDst = usDstActive(t)): string {
  const ms = typeof t === 'number' ? t : t.getTime()
  const nyMs = ms - (usDst ? 4 : 5) * 3_600_000
  const d = new Date(nyMs)
  if (d.getUTCHours() >= 18) d.setUTCDate(d.getUTCDate() + 1)
  return d.toISOString().slice(0, 10)
}

/** Round axis ticks (IST) every `stepMin` minutes from the Globex open, as [axisPos, istMin] pairs. */
export function axisTicksIst(usDst: boolean, stepMin = 180): { pos: number; ist: number }[] {
  const open = globexOpenIst(usDst)
  const first = Math.ceil(open / stepMin) * stepMin
  const out: { pos: number; ist: number }[] = []
  for (let m = first; m < open + DAY_MIN; m += stepMin) out.push({ pos: m - open, ist: m % DAY_MIN })
  return out
}

// ── bars: pure helpers shared by DAILY / WEEKLY / MONTHLY (unit-tested under node) ───────────────

/** The bar shape `/api/gold/bars` sends (ts = ISO instant, 'YYYY-MM-DD' for daily bars, or epoch s/ms). */
export interface BarLike { ts: string | number; o: number | null; h: number | null; l: number | null; c: number | null; v?: number | null }

/** An ISO datetime with no zone: 'YYYY-MM-DDTHH:MM[:SS[.fff]]' (also with a space). The store writes these in UTC. */
const NAIVE_DATETIME = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/

/**
 * A bar's timestamp as epoch ms: ISO strings WITH an offset ('…+05:30', '…Z', '…+00:00' — the offsets B1 emits) are
 * taken as written; a zone-less datetime is **UTC** (data-service `tz_convert('UTC').tz_localize(None)` strips the zone
 * before `isoformat()`; `new Date('2026-11-04T18:09:59')` would read it as browser-local and plot every bar 5 h 30 m
 * early on an IST machine — C-TRADER-1 / C-DATA-1); 'YYYY-MM-DD' is UTC midnight; epoch seconds or ms pass through.
 */
export function barMs(ts: string | number): number {
  if (typeof ts === 'number') return ts < 1e12 ? ts * 1000 : ts
  const s = ts.trim()
  const n = Number(s)
  if (Number.isFinite(n) && s !== '') return n < 1e12 ? n * 1000 : n
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return new Date(`${s}T00:00:00Z`).getTime()
  if (NAIVE_DATETIME.test(s)) return new Date(`${s.replace(' ', 'T')}Z`).getTime()
  return new Date(s).getTime()
}

/** IST 'HH:MM' of a bar's timestamp (through `barMs`, so a naive store string lands on the IST clock it belongs to). */
export function barIstHM(ts: string | number): string {
  const ms = barMs(ts)
  return Number.isFinite(ms) ? fmtHM(istMinutes(ms)) : '—'
}

/** A daily bar's trade date: the string's date part when it has one, else the UTC date of the instant. */
export function barDate(ts: string | number): string {
  if (typeof ts === 'string') {
    const m = /^(\d{4}-\d{2}-\d{2})/.exec(ts)
    if (m) return m[1]
  }
  const ms = barMs(ts)
  return Number.isFinite(ms) ? new Date(ms).toISOString().slice(0, 10) : ''
}

export interface DayPt { ms: number; pos: number; c: number; h: number; l: number; v: number }

/** Intraday bars → points on the Globex-day axis, grouped by CME trade date (oldest first, bars sorted by time). */
export function dayGroups(bars: readonly BarLike[], usDst: boolean): { date: string; pts: DayPt[] }[] {
  const map = new Map<string, DayPt[]>()
  for (const b of bars) {
    if (b.c == null || !Number.isFinite(b.c)) continue
    const ms = barMs(b.ts)
    if (!Number.isFinite(ms)) continue
    const date = cmeTradeDate(ms, usDst)
    const pt: DayPt = { ms, pos: axisPos(istMinutes(ms), usDst), c: b.c, h: b.h ?? b.c, l: b.l ?? b.c, v: b.v ?? 0 }
    const arr = map.get(date)
    if (arr) arr.push(pt); else map.set(date, [pt])
  }
  return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([date, pts]) => ({ date, pts: pts.sort((a, b) => a.ms - b.ms) }))
}

export interface LegendRow {
  /** the CME trade date of the group */
  date: string
  /** today's live / last traded price, or the stored daily close of a finished session */
  px: number | null
  /** 'last' while the session is running; 'close' = the stored daily bar's close (not an exchange settlement) */
  kind: 'last' | 'close'
  /** the stored daily close of the session before (the reference of the Δ), null when it is not stored */
  prevClose: number | null
  /** true when the day's price is the intraday bucket's end because no daily bar is stored for that date */
  bucketFallback: boolean
}

/**
 * The d.24h legend rows (C-TRADER-2 / C-DATA-1): one per CME trade date of the last `n` intraday groups, the finished
 * sessions priced at the STORED DAILY CLOSE (gold_daily_bars, keyed by trade date — never the last minute of the IST
 * bucket, which is a different clock), today at `live` (else the last stored minute) and labelled 'last'. Each Δ is
 * against the stored close of the previous trade date; when a daily bar is missing the row says so (`bucketFallback`)
 * instead of printing a bucket end as a close.
 */
export function legendCloses(groups: readonly { date: string; pts: readonly { c: number }[] }[], daily: readonly Ohlc[], live: { price: number } | null, n = 3): LegendRow[] {
  const closeOf = new Map(daily.map(k => [k.date, k.c]))
  const last = groups.slice(-n)
  return last.map((g, i) => {
    const isToday = i === last.length - 1
    const bucketEnd = g.pts[g.pts.length - 1]?.c ?? null
    const stored = closeOf.get(g.date) ?? null
    const prevDate = last[i - 1]?.date ?? null
    const prevClose = prevDate ? (closeOf.get(prevDate) ?? null) : (daily.filter(k => k.date < g.date).pop()?.c ?? null)
    if (isToday) return { date: g.date, px: live?.price ?? bucketEnd, kind: 'last', prevClose, bucketFallback: false }
    return { date: g.date, px: stored ?? bucketEnd, kind: 'close', prevClose, bucketFallback: stored == null }
  })
}

/** The previous finished session's stored daily close (the dashed reference line of d.24h), or null. */
export function prevSessionClose(daily: readonly Ohlc[], todayDate: string | null | undefined): { date: string; c: number } | null {
  const before = todayDate ? daily.filter(k => k.date < todayDate) : daily.slice(0, -1)
  const k = before[before.length - 1]
  return k ? { date: k.date, c: k.c } : null
}

/** 1-minute → 5-minute buckets (open = first, close = last, hi/lo, volume summed); bucket ts = epoch ms. */
export function resample5m(bars: readonly BarLike[]): BarLike[] {
  const out: BarLike[] = []
  let cur: { key: number; o: number; h: number; l: number; c: number; v: number; ts: number } | null = null
  for (const b of bars) {
    if (b.c == null || !Number.isFinite(b.c)) continue
    const ms = barMs(b.ts)
    if (!Number.isFinite(ms)) continue
    const key = Math.floor(ms / 300_000)
    if (!cur || cur.key !== key) {
      if (cur) out.push({ ts: cur.ts, o: cur.o, h: cur.h, l: cur.l, c: cur.c, v: cur.v })
      cur = { key, o: b.o ?? b.c, h: b.h ?? b.c, l: b.l ?? b.c, c: b.c, v: b.v ?? 0, ts: key * 300_000 }
    } else {
      cur.h = Math.max(cur.h, b.h ?? b.c); cur.l = Math.min(cur.l, b.l ?? b.c); cur.c = b.c; cur.v += b.v ?? 0
    }
  }
  if (cur) out.push({ ts: cur.ts, o: cur.o, h: cur.h, l: cur.l, c: cur.c, v: cur.v })
  return out
}

/** A daily / weekly / monthly candle keyed by its (period-end) trade date. */
export interface Ohlc { date: string; o: number; h: number; l: number; c: number; v: number }

/** Daily bars → clean candles (close required; open/high/low default to the close), sorted, one per date. */
export function dailyOhlc(bars: readonly BarLike[]): Ohlc[] {
  const map = new Map<string, Ohlc>()
  for (const b of bars) {
    if (b.c == null || !Number.isFinite(b.c)) continue
    const date = barDate(b.ts)
    if (!date) continue
    map.set(date, { date, o: b.o ?? b.c, h: b.h ?? b.c, l: b.l ?? b.c, c: b.c, v: b.v ?? 0 })
  }
  return [...map.values()].sort((a, b) => a.date.localeCompare(b.date))
}

/** Monday-based week key 'YYYY-Www' of an ISO date (ISO 8601 week numbering). */
export function isoWeekKey(date: string): string {
  const [y, m, d] = date.split('-').map(Number)
  const t = new Date(Date.UTC(y, m - 1, d))
  const day = (t.getUTCDay() + 6) % 7                      // Mon = 0
  t.setUTCDate(t.getUTCDate() - day + 3)                   // the Thursday of this week decides the year
  const isoYear = t.getUTCFullYear()
  const jan4 = new Date(Date.UTC(isoYear, 0, 4))
  const week = 1 + Math.round(((t.getTime() - jan4.getTime()) / 86_400_000 - 3 + ((jan4.getUTCDay() + 6) % 7)) / 7)
  return `${isoYear}-W${String(week).padStart(2, '0')}`
}

/** 0 = Monday … 6 = Sunday for an ISO date. */
export function weekdayIndex(date: string): number {
  const [y, m, d] = date.split('-').map(Number)
  return (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7
}

/** Daily candles → weekly ('W', Mon–Fri) or monthly ('M') candles; date = the last trade date of the period. */
export function resampleOhlc(daily: readonly Ohlc[], freq: 'W' | 'M'): Ohlc[] {
  const out: Ohlc[] = []
  let cur: Ohlc | null = null
  let key = ''
  for (const d of daily) {
    const k = freq === 'W' ? isoWeekKey(d.date) : d.date.slice(0, 7)
    if (!cur || k !== key) {
      if (cur) out.push(cur)
      cur = { ...d }
      key = k
    } else {
      cur.h = Math.max(cur.h, d.h); cur.l = Math.min(cur.l, d.l); cur.c = d.c; cur.v += d.v; cur.date = d.date
    }
  }
  if (cur) out.push(cur)
  return out
}

/** Simple moving average of the closes, aligned to the input (null until `n` values exist). */
export function sma(values: readonly number[], n: number): (number | null)[] {
  const out: (number | null)[] = []
  let sum = 0
  for (let i = 0; i < values.length; i++) {
    sum += values[i]
    if (i >= n) sum -= values[i - n]
    out.push(i >= n - 1 ? sum / n : null)
  }
  return out
}

export interface WeekRow { week: string; monday: string; days: (Ohlc | null)[]; total_pct: number | null }

/** The last `weeks` Mon–Fri rows of daily Δ % (close vs the previous close) with the week total (last close vs the close before the week). */
export function weekRows(daily: readonly Ohlc[], weeks = 26): WeekRow[] {
  const byWeek = new Map<string, { monday: string; days: (Ohlc | null)[]; firstPrev: number | null; last: number | null }>()
  let prev: number | null = null
  for (const d of daily) {
    const k = isoWeekKey(d.date)
    let w = byWeek.get(k)
    if (!w) {
      const wd = weekdayIndex(d.date)
      const [y, m, dd] = d.date.split('-').map(Number)
      const mon = new Date(Date.UTC(y, m - 1, dd - wd)).toISOString().slice(0, 10)
      w = { monday: mon, days: [null, null, null, null, null], firstPrev: prev, last: null }
      byWeek.set(k, w)
    }
    const idx = weekdayIndex(d.date)
    if (idx < 5) w.days[idx] = d
    w.last = d.c
    prev = d.c
  }
  return [...byWeek.entries()].slice(-weeks).map(([week, w]) => ({
    week, monday: w.monday, days: w.days,
    total_pct: w.firstPrev != null && w.last != null && w.firstPrev !== 0 ? (w.last / w.firstPrev - 1) * 100 : null,
  }))
}

/** Daily Δ % of each candle vs the previous candle's close (null for the first). */
export function dailyChanges(daily: readonly Ohlc[]): Map<string, number | null> {
  const out = new Map<string, number | null>()
  for (let i = 0; i < daily.length; i++) {
    const p = daily[i - 1]?.c
    out.set(daily[i].date, p != null && p !== 0 ? (daily[i].c / p - 1) * 100 : null)
  }
  return out
}

/** The close on or before `date` (ISO), or null when the history starts later. */
export function closeOnOrBefore(daily: readonly Ohlc[], date: string): number | null {
  let lo = 0, hi = daily.length - 1, best = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (daily[mid].date <= date) { best = mid; lo = mid + 1 } else hi = mid - 1
  }
  return best >= 0 ? daily[best].c : null
}

/** `iso` moved by `days` calendar days (UTC arithmetic). */
export function shiftDays(iso: string, days: number): string {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10)
}

/** Return in % from the close `days` calendar days before the last candle to the last close (null when too short). */
export function returnOver(daily: readonly Ohlc[], days: number): number | null {
  if (daily.length < 2) return null
  const last = daily[daily.length - 1]
  const from = shiftDays(last.date, -days)
  if (daily[0].date > from) return null
  const base = closeOnOrBefore(daily, from)
  return base != null && base !== 0 ? (last.c / base - 1) * 100 : null
}

export interface SeasonCell { month: number; mean_pct: number | null; hit_rate: number | null; n: number; p10: number | null; p90: number | null; t: number | null }

/** Calendar-month seasonality from monthly candles: mean Δ %, hit rate, n, p10/p90 and the t-stat of the mean. */
export function seasonality(monthly: readonly Ohlc[]): SeasonCell[] {
  const buckets: number[][] = Array.from({ length: 12 }, () => [])
  for (let i = 1; i < monthly.length; i++) {
    const p = monthly[i - 1].c
    if (!p) continue
    const mon = Number(monthly[i].date.slice(5, 7))
    buckets[mon - 1].push((monthly[i].c / p - 1) * 100)
  }
  return buckets.map((xs, i) => {
    const n = xs.length
    if (!n) return { month: i + 1, mean_pct: null, hit_rate: null, n: 0, p10: null, p90: null, t: null }
    const mean = xs.reduce((a, b) => a + b, 0) / n
    const sd = n > 1 ? Math.sqrt(xs.reduce((a, b) => a + (b - mean) ** 2, 0) / (n - 1)) : 0
    const s = [...xs].sort((a, b) => a - b)
    const q = (p: number) => s[Math.min(n - 1, Math.max(0, Math.round((n - 1) * p)))]
    return { month: i + 1, mean_pct: mean, hit_rate: xs.filter(x => x > 0).length / n, n, p10: q(0.1), p90: q(0.9), t: sd > 0 && n > 1 ? mean / (sd / Math.sqrt(n)) : null }
  })
}

/** Percentile rank (0–100) of `x` within `values` (share of values ≤ x). */
export function percentileOf(values: readonly number[], x: number | null | undefined): number | null {
  const xs = values.filter(Number.isFinite)
  if (!xs.length || x == null || !Number.isFinite(x)) return null
  return (xs.filter(v => v <= x).length / xs.length) * 100
}

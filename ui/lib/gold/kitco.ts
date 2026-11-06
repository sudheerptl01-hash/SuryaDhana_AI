/**
 * The Kitco-style chart on GOLD › DAILY (d.24h, wave 1d): Kitco's timeframes (24 h · 3 days · 30 days · 60 days · 6 months ·
 * 1 year · 5 years · 10 years · all) and units (USD/oz, ₹/10 g landed ex-duty or duty-paid, ₹/g, USD/g, USD/kg), built ONLY
 * from bars the store already holds and `/api/gold/bars` already serves: GC=F 1-minute (the 5-minute job) and daily bars,
 * INR=X 1-minute and daily bars for the rupee conversion. Kitco itself stays a link (its terms forbid scraping; its widget is
 * HTTP-only). The chart is `arithmetic` (unit conversion of stored prices); nothing here is a forecast.
 *
 * Rules carried by this module:
 *  - every rupee point is converted with the USD/INR of ITS OWN date (PM decision D5): a DAILY close with the INR=X close of
 *    the same date (the latest stored date at or before it), so one date's close prints the same rupee value on every
 *    timeframe (24 h's dashed previous close = that date on 'all'); a 1-MINUTE point with the latest stored 1-minute rate at
 *    or before the minute. Never today's rate applied to history; a point with no stored rupee rate (INR=X begins Dec 2003)
 *    is dropped, and the panel says from when the rupee line starts;
 *  - duty-paid applies the DATED duty only from the day it took effect (15 % since 13 May 2026); the store keeps no duty
 *    history, so earlier points are not invented — the duty-paid line starts at the effective date and says so;
 *  - the window's high / low / change are of the plotted (converted) series; the change is vs the previous session's
 *    stored close on 24 h and 3 days, vs the window's first close otherwise.
 *
 * Pure module (no React, no DOM): unit-tested under node by ui/components/__tests__/gold.check.ts.
 */
import { GRAMS_PER_OZ, dayLabel, fmtSignedPctSp, pctChange } from './format'
import { fmtFixed } from '@/lib/format'
import { legendCloses, type Ohlc } from './sessions'

/**
 * A number in a Kitco unit (wave 1e minor, C-TRADER-20 convention): Western grouping for every USD unit (usd_oz / usd_g /
 * usd_kg: '1,32,339' → '132,339'), Indian for the rupee units; U+2212 minus. `unit` may be a KitcoUnit or a label
 * ('USD/kg', '₹/10 g').
 */
export function fmtKitco(v: number | null | undefined, dp: number, unit: KitcoUnit | string | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const usd = /^(usd|USD|\$)/u.test(String(unit ?? ''))
  if (!usd) return fmtFixed(v, dp)
  const s = Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp })
  const zero = Number(Math.abs(v).toFixed(dp)) === 0
  return `${v < 0 && !zero ? '\u2212' : ''}${s}`
}

/** fmtKitco with a sign ('+1,234' / '−1,234'; '0' unsigned). */
export function fmtKitcoSigned(v: number | null | undefined, dp: number, unit: KitcoUnit | string | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const body = fmtKitco(Math.abs(v), dp, unit)
  const zero = Number(Math.abs(v).toFixed(dp)) === 0
  return zero ? body : `${v > 0 ? '+' : '\u2212'}${body}`
}

export type KitcoTf = '24h' | '3d' | '30d' | '60d' | '6m' | '1y' | '5y' | '10y' | 'all'
export type KitcoUnit = 'usd_oz' | 'inr_10g' | 'inr_g' | 'usd_g' | 'usd_kg'
export type DutyMode = 'ex_duty' | 'duty_paid'

export interface KitcoTimeframe {
  key: KitcoTf
  label: string
  /** calendar days back from the last bar; null = everything stored */
  days: number | null
  /** which stored bars draw it */
  source: '1m' | '1d'
}

/** Kitco's nine timeframes, in its order. 24 h and 3 days draw the stored 1-minute bars; the rest the stored daily closes. */
export const KITCO_TIMEFRAMES: readonly KitcoTimeframe[] = Object.freeze([
  { key: '24h', label: '24 h', days: 1, source: '1m' },
  { key: '3d', label: '3 days', days: 3, source: '1m' },
  { key: '30d', label: '30 days', days: 30, source: '1d' },
  { key: '60d', label: '60 days', days: 60, source: '1d' },
  { key: '6m', label: '6 months', days: 183, source: '1d' },
  { key: '1y', label: '1 year', days: 365, source: '1d' },
  { key: '5y', label: '5 years', days: 1826, source: '1d' },
  { key: '10y', label: '10 years', days: 3653, source: '1d' },
  { key: 'all', label: 'all', days: null, source: '1d' },
] as KitcoTimeframe[])

export const KITCO_UNITS: readonly KitcoUnit[] = Object.freeze(['usd_oz', 'inr_10g', 'inr_g', 'usd_g', 'usd_kg'] as KitcoUnit[])

export const KITCO_UNIT_LABEL: Readonly<Record<KitcoUnit, string>> = Object.freeze({
  usd_oz: 'USD/oz', inr_10g: '₹/10 g', inr_g: '₹/g', usd_g: 'USD/g', usd_kg: 'USD/kg',
})

/** The first stored day the daily request asks for ('all'): the store's history begins later (GC=F 30 Aug 2000), the panel says so. */
export const KITCO_ALL_FROM = '1990-01-01'
/** Timeframes up to this many days read the short daily load; longer ones the full history (one memoised read). */
export const KITCO_SHORT_DAYS = 400

export function isRupee(u: KitcoUnit): boolean {
  return u === 'inr_10g' || u === 'inr_g'
}

/** The page-global unit → the panel's unit (₹/tola has no Kitco unit: it reads ₹/10 g). */
export function kitcoUnitFromPage(u: string): KitcoUnit {
  return u === 'usd_oz' || u === 'inr_10g' || u === 'inr_g' || u === 'usd_g' ? u : u === 'tola' ? 'inr_10g' : 'usd_oz'
}

export function timeframe(key: KitcoTf): KitcoTimeframe {
  return KITCO_TIMEFRAMES.find(t => t.key === key) ?? KITCO_TIMEFRAMES[0]
}

/** Decimals per unit: USD/g 3, the rest 2 (₹/10 g and USD/kg print whole-number grouping via the kit). */
export function kitcoDp(u: KitcoUnit): number {
  return u === 'usd_g' ? 3 : u === 'usd_kg' || u === 'inr_10g' ? 0 : 2
}

/**
 * A $/oz price in a Kitco unit. Rupee units need the USD/INR of the bar's own time; duty-paid needs the dated duty
 * multiplier for that time (null before the duty's effective date: the point is not drawn). Returns null when a needed
 * leg is missing.
 */
export function kitcoConvert(usdOz: number | null | undefined, unit: KitcoUnit, usdinr: number | null | undefined, dutyMult: number | null | undefined = 1): number | null {
  if (usdOz == null || !Number.isFinite(usdOz)) return null
  switch (unit) {
    case 'usd_oz': return usdOz
    case 'usd_g': return usdOz / GRAMS_PER_OZ
    case 'usd_kg': return (usdOz * 1000) / GRAMS_PER_OZ
    default: {
      if (usdinr == null || !Number.isFinite(usdinr) || dutyMult == null || !Number.isFinite(dutyMult)) return null
      const perGram = ((usdOz * usdinr) / GRAMS_PER_OZ) * dutyMult
      return unit === 'inr_10g' ? perGram * 10 : perGram
    }
  }
}

/** A dated duty: the multiplier (1 + pct/100) on or after `effective`, null before it (the store has no duty history). */
export function dutyMultiplier(dateIso: string, duty: { pct: number | null | undefined; effective: string | null | undefined } | null | undefined): number | null {
  if (!duty || duty.pct == null || !Number.isFinite(duty.pct) || !duty.effective) return null
  return dateIso.slice(0, 10) >= duty.effective.slice(0, 10) ? 1 + duty.pct / 100 : null
}

export interface FxPt { ms: number; v: number }

/** The latest stored rate at or before `ms` (binary search over ascending points); null before the first one. */
export function fxAsOf(fx: readonly FxPt[], ms: number): number | null {
  let lo = 0, hi = fx.length - 1, ans = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (fx[mid].ms <= ms) { ans = mid; lo = mid + 1 } else hi = mid - 1
  }
  return ans >= 0 ? fx[ans].v : null
}

/** Daily rates are dated, not timed: a date's close is known from the END of that day (UTC midnight of the next day). */
export function dailyFxPoints(rows: readonly { ts: string | number; c: number | null }[]): FxPt[] {
  const out: FxPt[] = []
  for (const r of rows) {
    if (r.c == null || !Number.isFinite(r.c)) continue
    const d = typeof r.ts === 'string' ? r.ts.slice(0, 10) : new Date(r.ts).toISOString().slice(0, 10)
    const ms = Date.parse(`${d}T00:00:00Z`)
    if (Number.isFinite(ms)) out.push({ ms: ms + 86_400_000 - 1, v: r.c })
  }
  return out.sort((a, b) => a.ms - b.ms)
}

/** A dated daily rate (INR=X daily close of `date`). */
export interface DailyFx { date: string; v: number }

/** The stored INR=X daily closes, ascending by date (null closes dropped). */
export function dailyFxRows(rows: readonly { ts: string | number; c: number | null }[]): DailyFx[] {
  const out: DailyFx[] = []
  for (const r of rows) {
    if (r.c == null || !Number.isFinite(r.c)) continue
    const d = typeof r.ts === 'string' ? r.ts.slice(0, 10) : new Date(r.ts).toISOString().slice(0, 10)
    if (/^\d{4}-\d{2}-\d{2}$/u.test(d)) out.push({ date: d, v: r.c })
  }
  return out.sort((a, b) => a.date.localeCompare(b.date))
}

/** The USD/INR close of `dateIso` itself, else of the latest stored date before it (a holiday); null before the first. */
export function fxOnDate(fx: readonly DailyFx[], dateIso: string): number | null {
  const d = dateIso.slice(0, 10)
  let lo = 0, hi = fx.length - 1, ans = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (fx[mid].date <= d) { ans = mid; lo = mid + 1 } else hi = mid - 1
  }
  return ans >= 0 ? fx[ans].v : null
}

/**
 * One DAILY close in a Kitco unit at its own date's rate and duty (D5): the one rule the daily series, the 24 h dashed
 * previous close and the legend share, so a date's close is the same rupee number on every timeframe.
 */
export function dailyCloseIn(usdOz: number | null | undefined, dateIso: string, unit: KitcoUnit, duty: DutyMode, fxDaily: readonly DailyFx[],
  dutyRate: { pct: number | null | undefined; effective: string | null | undefined } | null): number | null {
  if (!isRupee(unit)) return kitcoConvert(usdOz, unit, null)
  const mult = duty === 'duty_paid' ? dutyMultiplier(dateIso, dutyRate) : 1
  return kitcoConvert(usdOz, unit, fxOnDate(fxDaily, dateIso), mult)
}

/** Merge two ascending rate series (1-minute where stored, daily elsewhere), the finer one winning inside its span. */
export function mergeFx(daily: readonly FxPt[], intraday: readonly FxPt[]): FxPt[] {
  if (!intraday.length) return [...daily]
  const lo = intraday[0].ms, hi = intraday[intraday.length - 1].ms
  return [...daily.filter(p => p.ms < lo || p.ms > hi), ...intraday].sort((a, b) => a.ms - b.ms)
}

export interface KPt { ms: number; v: number }

/**
 * The plotted series: each $/oz point in the window converted with its own rate and duty — a point that carries a `date`
 * (a daily close) at the INR=X close of that date (`fxDaily`, D5), a timed point (a 1-minute bar) at the latest stored rate
 * at or before its instant (`fx`). `startMs` is the window's first instant (null = all). Points that cannot be converted
 * are dropped (counted in `dropped`).
 */
export function kitcoSeries(pts: readonly { ms: number; usd: number; date?: string }[], opts: {
  unit: KitcoUnit; duty: DutyMode; fx: readonly FxPt[]; dutyRate: { pct: number | null | undefined; effective: string | null | undefined } | null; startMs: number | null
  fxDaily?: readonly DailyFx[]
}): { pts: KPt[]; dropped: number; firstMs: number | null } {
  const out: KPt[] = []
  let dropped = 0
  for (const p of pts) {
    if (opts.startMs != null && p.ms < opts.startMs) continue
    if (p.date && opts.fxDaily) {
      const v = dailyCloseIn(p.usd, p.date, opts.unit, opts.duty, opts.fxDaily, opts.dutyRate)
      if (v == null) { dropped++; continue }
      out.push({ ms: p.ms, v })
      continue
    }
    const inr = isRupee(opts.unit) ? fxAsOf(opts.fx, p.ms) : null
    const mult = isRupee(opts.unit) ? (opts.duty === 'duty_paid' ? dutyMultiplier(new Date(p.ms + 330 * 60_000).toISOString().slice(0, 10), opts.dutyRate) : 1) : 1
    const v = kitcoConvert(p.usd, opts.unit, inr, mult)
    if (v == null) { dropped++; continue }
    out.push({ ms: p.ms, v })
  }
  return { pts: out, dropped, firstMs: out.length ? out[0].ms : null }
}

export interface KStats { first: number; last: number; hi: number; lo: number; hiMs: number; loMs: number; chg: number; chgPct: number; base: number; baseKind: 'prev_close' | 'window_first' }

/**
 * High / low / change of the plotted window. The change is vs `prevClose` (the previous session's stored close, already in
 * the plotted unit) when given, else vs the window's first point.
 */
export function kitcoStats(pts: readonly KPt[], prevClose?: number | null): KStats | null {
  if (!pts.length) return null
  let hi = -Infinity, lo = Infinity, hiMs = 0, loMs = 0
  for (const p of pts) {
    if (p.v > hi) { hi = p.v; hiMs = p.ms }
    if (p.v < lo) { lo = p.v; loMs = p.ms }
  }
  const first = pts[0].v, last = pts[pts.length - 1].v
  const usePrev = prevClose != null && Number.isFinite(prevClose) && prevClose !== 0
  const base = usePrev ? (prevClose as number) : first
  return { first, last, hi, lo, hiMs, loMs, chg: last - base, chgPct: base ? (last / base - 1) * 100 : 0, base, baseKind: usePrev ? 'prev_close' : 'window_first' }
}

/**
 * Thin a long series for drawing, keeping each bucket's low and high in time order so the window's extremes survive (the
 * stats are computed on the full series, never on the thinned one).
 */
export function decimate(pts: readonly KPt[], maxPts = 1600): KPt[] {
  if (pts.length <= maxPts) return [...pts]
  const buckets = Math.max(1, Math.floor(maxPts / 2))
  const size = pts.length / buckets
  const out: KPt[] = []
  for (let b = 0; b < buckets; b++) {
    const s = Math.floor(b * size), e = Math.min(pts.length, Math.floor((b + 1) * size))
    if (e <= s) continue
    let mn = pts[s], mx = pts[s]
    for (let i = s; i < e; i++) { if (pts[i].v < mn.v) mn = pts[i]; if (pts[i].v > mx.v) mx = pts[i] }
    if (mn === mx) out.push(mn)
    else if (mn.ms <= mx.ms) out.push(mn, mx)
    else out.push(mx, mn)
  }
  const last = pts[pts.length - 1]
  if (out[out.length - 1] !== last) out.push(last)
  return out
}

/** Time-axis ticks for a window: hours inside 3 days, days inside 60, months inside 2 years, else years (UTC-agnostic IST labels). */
export function timeTicks(startMs: number, endMs: number, maxTicks = 8): { ms: number; label: string }[] {
  const span = endMs - startMs
  if (!(span > 0)) return []
  const IST = 330 * 60_000
  const H = 3_600_000, D = 24 * H
  const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  const out: { ms: number; label: string }[] = []
  const istParts = (ms: number) => { const d = new Date(ms + IST); return { y: d.getUTCFullYear(), m: d.getUTCMonth(), d: d.getUTCDate(), h: d.getUTCHours() } }
  if (span <= 3.5 * D) {
    const stepH = [1, 2, 3, 4, 6, 12, 24].find(h => span / (h * H) <= maxTicks) ?? 24
    let t = Math.ceil((startMs + IST) / (stepH * H)) * stepH * H - IST
    for (; t <= endMs; t += stepH * H) { const p = istParts(t); out.push({ ms: t, label: p.h === 0 ? `${String(p.d).padStart(2, '0')} ${MON[p.m]}` : `${String(p.h).padStart(2, '0')}:00` }) }
    return out
  }
  if (span <= 75 * D) {
    const stepD = [1, 2, 5, 7, 10, 14].find(d => span / (d * D) <= maxTicks) ?? 14
    let t = Math.ceil((startMs + IST) / D) * D - IST
    for (let i = 0; t <= endMs; t += D, i++) { if (i % stepD === 0) { const p = istParts(t); out.push({ ms: t, label: `${String(p.d).padStart(2, '0')} ${MON[p.m]}` }) } }
    return out
  }
  if (span <= 800 * D) {
    const months = span / (30.44 * D)
    const stepM = [1, 2, 3, 6].find(m => months / m <= maxTicks) ?? 6
    const s = istParts(startMs)
    for (let y = s.y, m = s.m + 1; ; m++) {
      if (m > 11) { m = 0; y++ }
      const t = Date.UTC(y, m, 1) - IST
      if (t > endMs) break
      if (m % stepM === 0) out.push({ ms: t, label: m === 0 ? String(y) : `${MON[m]} ${String(y).slice(2)}` })
    }
    return out
  }
  const years = span / (365.25 * D)
  const stepY = [1, 2, 5, 10].find(y => years / y <= maxTicks) ?? 10
  const s = istParts(startMs), e = istParts(endMs)
  for (let y = s.y + 1; y <= e.y; y++) if (y % stepY === 0) out.push({ ms: Date.UTC(y, 0, 1) - IST, label: String(y) })
  return out
}

/**
 * The legend under the 24-h chart (C-TRADER-2 / C-DATA-1; round 2, PLAN §f.6): finished sessions at their STORED DAILY
 * CLOSE (gold_daily_bars; a Yahoo daily close, not an exchange settlement), each Δ vs the stored close of the session
 * before, each close at its own date's rupee rate (`closeIn`, D5). Each number prints once on the panel: today's row is
 * gone (the stats row prints the change, the chart the last) and the previous session's close value is on the dashed line,
 * so its row keeps only its own Δ. Never the last minute of an IST bucket.
 */
export function kitcoLegend(groups: readonly { date: string; pts: readonly { c: number }[] }[], daily: readonly Ohlc[], live: { price: number } | null,
  closeIn: (usd: number, date: string) => number | null, dp: number, dashedDate: string | null, unit?: KitcoUnit | string | null): string[] {
  const out: string[] = []
  for (const r of legendCloses(groups, daily, live, 3)) {
    if (r.kind === 'last') continue
    if (r.px == null) { out.push(`${dayLabel(r.date)} close —`); continue }
    const pxC = closeIn(r.px, r.date)
    const prevDate = daily.filter(k => k.date < r.date).pop()?.date ?? null
    const prevC = r.prevClose != null && prevDate ? closeIn(r.prevClose, prevDate) : null
    const chg = pxC != null && prevC != null ? pxC - prevC : null
    const pct = pctChange(prevC, pxC)
    const what = r.bucketFallback ? 'last stored minute (no daily bar yet)' : 'close (Yahoo daily, not settlement)'
    const delta = chg != null ? `${chg >= 0 ? '▲' : '▼'}${fmtKitco(Math.abs(chg), dp, unit)} (${fmtSignedPctSp(pct, 2)} vs ${prevDate ? `the ${dayLabel(prevDate)}` : 'the previous stored'} close)` : '(previous close not stored)'
    out.push(r.date === dashedDate && !r.bucketFallback
      ? `${dayLabel(r.date)} ${delta} — its close is the dashed line`
      : `${dayLabel(r.date)} ${what} ${pxC == null ? '—' : fmtKitco(pxC, dp, unit)} ${delta}`)
  }
  return out
}

/** The Kitco link the panel shows beside the chart (a link only: never fetched by the stack, PLAN 0.1 #6). */
export const KITCO_URL = 'https://www.kitco.com/charts/gold'

/**
 * Pure logic for the interactive chart kit (FINAL ROUND W3, charts/PLAN.md §4): everything InteractiveSeries.tsx
 * needs that is NOT React or lightweight-charts — series shaping, time coercion, the band → area-pair mapping,
 * marker specs, the LWC theme builder and the crosshair-legend text. No runtime imports (type-only imports are
 * erased), so it runs under plain node ≥ 23.6 in ui/components/terminal/__tests__/interactive.check.ts.
 *
 * Time convention (matches MarketInternals/IndexIntraday): lightweight-charts renders epoch times as UTC, so an
 * intraday stamp is shifted +5:30 at coercion — the chart's clock then READS as IST. Date-only strings stay
 * business days ('2026-11-12'). The kit changes rendering only: wording, badges and colour semantics stay with
 * the caller (GOLD labelling rules).
 */
import type { ChartOptions, ColorType, CrosshairMode, DeepPartial, LineStyle } from 'lightweight-charts'

// ── public types (the PLAN §4 contract) ──────────────────────────────────────────────────────────────

/** A point's time: 'YYYY-MM-DD', an ISO timestamp, epoch seconds or epoch milliseconds. */
export type TimeLike = string | number

export interface SeriesPoint { t: TimeLike; v: number | null }
export interface CandlePoint { t: TimeLike; o: number | null; h: number | null; l: number | null; c: number | null }

export type KitSeriesType = 'line' | 'area' | 'candles' | 'histogram'

export interface SeriesSpec {
  id: string
  /** legend label; the id (uppercased) when missing */
  label?: string
  /** series colour; the kit palette by position when missing */
  color?: string
  /** default 'line' */
  type?: KitSeriesType
  /** price scale: 'R' (default) or 'L' */
  axis?: 'L' | 'R'
  points: SeriesPoint[] | CandlePoint[]
  /** value → text for the axis label and the crosshair legend (default: 2 dp) */
  format?: (v: number) => string
  /** line width in px (default 2 for the first series, 1 after) */
  w?: number
  dashed?: boolean
  /** an overlay scale of its own (the volume histogram pattern): hidden axis, bottom 18% of the pane */
  overlay?: boolean
}

export interface BandSpec {
  lo: SeriesPoint[]
  hi: SeriesPoint[]
  color?: string
  /** the band's price scale (default 'R', like the series) */
  axis?: 'L' | 'R'
}

export interface MarkerSpec { t: TimeLike; kind: string; label?: string }

// ── time coercion ────────────────────────────────────────────────────────────────────────────────────

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/
const HAS_ZONE = /(?:Z|[+−-]\d{2}:?\d{2})$/
const WALL = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/
const IST_OFFSET_S = 19_800 // +05:30

/**
 * A TimeLike → what lightweight-charts takes: a 'YYYY-MM-DD' business day stays a string; an intraday stamp
 * becomes epoch SECONDS shifted +05:30 so the UTC-rendered clock reads IST (an ISO stamp with an explicit zone
 * is converted; one without a zone is taken as an IST wall clock, shown unchanged). A NUMBER passes through as
 * given (milliseconds > 1e11 divided down to seconds) — a caller handing epochs has already applied its own
 * display convention (the MarketInternals pattern). Null when unparsable.
 */
export function coerceTime(t: TimeLike | null | undefined): string | number | null {
  if (t == null) return null
  if (typeof t === 'number') {
    if (!Number.isFinite(t)) return null
    return Math.round(t > 1e11 ? t / 1000 : t)
  }
  const str = t.trim()
  if (DATE_ONLY.test(str)) return str
  const m = WALL.exec(str)
  if (!m) return null
  if (HAS_ZONE.test(str)) {
    const ms = Date.parse(str.replace('−', '-'))
    if (!Number.isFinite(ms)) return null
    return Math.round(ms / 1000) + IST_OFFSET_S
  }
  // no zone: the wall clock IS the display clock (treat as UTC so LWC shows it unchanged)
  const ms = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] ?? 0))
  return Math.round(ms / 1000)
}

/** Sort key for a coerced time (business days sort against epochs by their UTC midnight). */
export function timeKey(ct: string | number): number {
  return typeof ct === 'number' ? ct : Date.parse(`${ct}T00:00:00Z`) / 1000
}

/** True when any point of any series carries an intraday time (the chart then shows a clock axis). */
export function isIntraday(series: readonly SeriesSpec[]): boolean {
  return series.some(s => s.points.some(p => typeof coerceTime((p as SeriesPoint).t) === 'number'))
}

/** The crosshair legend's time text: a business day as-is, an epoch as 'DD MON HH:MM' (IST by construction). */
export function timeText(time: string | number | null | undefined): string {
  if (time == null) return ''
  if (typeof time === 'string') return time
  if (!Number.isFinite(time)) return ''
  const d = new Date(time * 1000)
  const MON = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
  const dd = String(d.getUTCDate()).padStart(2, '0')
  const hh = String(d.getUTCHours()).padStart(2, '0')
  const mm = String(d.getUTCMinutes()).padStart(2, '0')
  return `${dd} ${MON[d.getUTCMonth()]} ${hh}:${mm}`
}

// ── series shaping ───────────────────────────────────────────────────────────────────────────────────

export interface KitValuePoint { time: string | number; value?: number }
export interface KitCandlePoint { time: string | number; open?: number; high?: number; low?: number; close?: number }

/** Coerce + sort ascending + dedupe (keep the last write per time) — what LWC's setData demands. */
function orderPoints<P extends { t: TimeLike }>(points: readonly P[]): { time: string | number; p: P }[] {
  const rows: { time: string | number; key: number; p: P }[] = []
  for (const p of points) {
    const time = coerceTime(p.t)
    if (time == null) continue
    rows.push({ time, key: timeKey(time), p })
  }
  rows.sort((a, b) => a.key - b.key)
  const out: { time: string | number; p: P }[] = []
  for (const r of rows) {
    if (out.length && timeKey(out[out.length - 1].time) === r.key) out[out.length - 1] = { time: r.time, p: r.p }
    else out.push({ time: r.time, p: r.p })
  }
  return out
}

/** Line / area / histogram data: a null or non-finite v becomes a whitespace row `{ time }` (a visible gap). */
export function shapeLine(points: readonly SeriesPoint[]): KitValuePoint[] {
  return orderPoints(points).map(({ time, p }) =>
    p.v == null || !Number.isFinite(p.v) ? { time } : { time, value: p.v })
}

/** Candle data: a row missing any of o/h/l/c becomes a whitespace row `{ time }`. */
export function shapeCandles(points: readonly CandlePoint[]): KitCandlePoint[] {
  return orderPoints(points).map(({ time, p }) => {
    const { o, h, l, c } = p
    if (o == null || h == null || l == null || c == null ||
        ![o, h, l, c].every(Number.isFinite)) return { time }
    return { time, open: o, high: h, low: l, close: c }
  })
}

/**
 * A change signature over what forces a series REBUILD (ids, types, axes, colours, band/overlay shape).
 * Data-only updates keep the handles and just setData, so a live tape never flickers.
 */
export function seriesSignature(series: readonly SeriesSpec[], band?: BandSpec | null): string {
  const s = series.map(x => [x.id, x.type ?? 'line', x.axis ?? 'R', x.color ?? '', x.w ?? '', x.dashed ? 1 : 0, x.overlay ? 1 : 0].join(':')).join('|')
  return band ? `${s}#band:${band.color ?? ''}:${band.axis ?? 'R'}` : s
}

// ── band → area pair (spike-proven) ──────────────────────────────────────────────────────────────────

export interface AreaPairOptions {
  lineColor: string
  topColor: string
  bottomColor: string
  lineWidth: 1 | 2 | 3 | 4
  priceLineVisible: boolean
  lastValueVisible: boolean
  crosshairMarkerVisible: boolean
}

/**
 * The p25–p75 (cone) band as two LWC area series: `hi` filled with a translucent band colour, `lo` filled with
 * the PANEL background to mask below the band's floor. Add BOTH before the line series so lines draw on top.
 */
export function bandAreaOptions(color: string, panelBg: string): { hi: AreaPairOptions; lo: AreaPairOptions } {
  const quiet = { lineColor: 'rgba(0,0,0,0)', lineWidth: 1 as const, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }
  return {
    hi: { ...quiet, topColor: `${color}26`, bottomColor: `${color}26` },
    lo: { ...quiet, topColor: panelBg, bottomColor: panelBg },
  }
}

// ── markers ──────────────────────────────────────────────────────────────────────────────────────────

export interface MarkerPalette { results: string; expiry: string; default: string }
export interface KitMarker {
  time: string | number
  position: 'aboveBar' | 'belowBar' | 'inBar'
  shape: 'circle' | 'square' | 'arrowUp' | 'arrowDown'
  color: string
  text?: string
  size?: number
}

/** Marker colour/shape by kind — the vol/charts.tsx convention: results violet, expiry muted, anything else cyan. */
export function markerSpec(kind: string, palette: MarkerPalette): { color: string; shape: KitMarker['shape'] } {
  if (kind === 'results') return { color: palette.results, shape: 'circle' }
  if (kind === 'expiry') return { color: palette.expiry, shape: 'square' }
  return { color: palette.default, shape: 'circle' }
}

/** MarkerSpec[] → LWC markers, sorted ascending (setMarkers demands it); unparsable times dropped. */
export function toMarkers(markers: readonly MarkerSpec[], palette: MarkerPalette): KitMarker[] {
  const out: KitMarker[] = []
  for (const m of markers) {
    const time = coerceTime(m.t)
    if (time == null) continue
    const spec = markerSpec(m.kind, palette)
    out.push({ time, position: 'aboveBar', shape: spec.shape, color: spec.color, size: 1, ...(m.label ? { text: m.label } : null) })
  }
  return out.sort((a, b) => timeKey(a.time) - timeKey(b.time))
}

// ── theme builder (bound to the T tokens by chartTheme.ts — the ONE theme source at runtime) ─────────

export interface ThemeTokens { bg: string; panel: string; border: string; borderHi: string; muted: string; text: string; mono: string }

/**
 * The terminal's lightweight-charts options from the token set. Literal enum values (CrosshairMode.Normal = 0,
 * LineStyle.Dashed = 2, ColorType.Solid = 'solid' in 4.2.3) so this stays node-checkable without loading LWC.
 * layout.attributionLogo is NOT set: the TradingView mark stays (licence attribution).
 */
export function buildChartTheme(tk: ThemeTokens): DeepPartial<ChartOptions> {
  return {
    layout: {
      background: { type: 'solid' as ColorType.Solid, color: tk.panel },
      textColor: tk.muted,
      fontFamily: tk.mono,
      fontSize: 10,
    },
    grid: { vertLines: { color: tk.border }, horzLines: { color: tk.border } },
    crosshair: {
      mode: 0 as CrosshairMode, // Normal
      vertLine: { color: tk.muted, width: 1, style: 2 as LineStyle, labelBackgroundColor: tk.borderHi }, // Dashed
      horzLine: { color: tk.muted, width: 1, style: 2 as LineStyle, labelBackgroundColor: tk.borderHi },
    },
    rightPriceScale: { borderColor: tk.border },
    leftPriceScale: { borderColor: tk.border },
    timeScale: { borderColor: tk.border, rightOffset: 3 },
    handleScroll: true,
    handleScale: true,
  }
}

// ── crosshair legend ─────────────────────────────────────────────────────────────────────────────────

export interface LegendPart { label: string; text: string; color?: string }

/** The default value text when a spec has no `format`: trimmed to at most 2 dp. */
export function fmtValue(v: number | null | undefined, format?: (v: number) => string): string {
  if (v == null || !Number.isFinite(v)) return '—'
  if (format) return format(v)
  const a = Math.abs(v)
  return v.toFixed(a >= 1000 ? 0 : 2)
}

/** '12 NOV · IV30 18.2% · SPOT 25,713' — the shell legend line (plain text; the component wraps it in spans). */
export function legendLine(time: string, parts: readonly LegendPart[]): string {
  const body = parts.map(p => `${p.label} ${p.text}`).join(' · ')
  return time && body ? `${time} · ${body}` : time || body
}

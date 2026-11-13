/**
 * Pure helpers for the expiry charts' lightweight-charts conversion (FINAL ROUND wave B, B-XPRY; charts/PLAN.md §4
 * rows B2/B3/B5). No React, no runtime imports (type-only imports are erased), so it runs under plain node ≥ 22.6 in
 * ui/components/expiry/__tests__/charts.check.ts.
 *
 * Time convention (interactiveModel.ts): lightweight-charts renders epoch times as UTC, so a session minute is turned
 * into epoch seconds of the IST WALL clock treated as UTC — the chart's axis and the crosshair's time text then read
 * as IST unchanged. The kit changes rendering only: wording, badges and colour semantics stay with the caller.
 */
import type { SeriesPoint } from '@/components/terminal/interactiveModel'

// mirrors tapeModel's session constants (no runtime import: plain-node ESM would need an explicit extension)
export const SESSION_START_MIN = 9 * 60 + 15
export const SESSION_LEN_MIN = 375

const DAY = /^(\d{4})-(\d{2})-(\d{2})$/

/** The IST calendar date of an epoch (ms): the session date a dateless chart falls back to. */
export function istDateOf(nowMs: number): string {
  return new Date(nowMs + 5.5 * 3600_000).toISOString().slice(0, 10)
}

/**
 * A session minute (after 09:15 IST) on `day` ('YYYY-MM-DD') → epoch SECONDS of that IST wall clock treated as UTC
 * (the interactiveModel convention, so the chart's clock reads IST). Null when the day or minute is unusable.
 */
export function minuteToTime(day: string | null | undefined, minute: number): number | null {
  const m = DAY.exec(day ?? '')
  if (!m || !Number.isFinite(minute)) return null
  const total = SESSION_START_MIN + Math.round(minute)
  return Date.UTC(+m[1], +m[2] - 1, +m[3], Math.floor(total / 60), total % 60) / 1000
}

/** The session series' (x minutes, y values) → kit points on `day`; minutes outside [0, xMax] are dropped. */
export function sessionPoints(day: string, x: readonly number[], y: readonly (number | null)[], xMax: number = SESSION_LEN_MIN): SeriesPoint[] {
  const out: SeriesPoint[] = []
  for (let i = 0; i < x.length; i++) {
    const m = x[i]
    if (!Number.isFinite(m) || m < 0 || m > xMax) continue
    const t = minuteToTime(day, m)
    if (t == null) continue
    const v = y[i]
    out.push({ t, v: v == null || !Number.isFinite(v) ? null : v })
  }
  return out
}

/** Axis/legend text for a session series: 2 dp with the axis unit; thousands (forwards, strikes) grouped whole. */
export function sessionFormat(unit: string): (v: number) => string {
  return (v: number) => (Math.abs(v) >= 1000 ? `${Math.round(v).toLocaleString('en-IN')}${unit}` : `${v.toFixed(2)}${unit}`)
}

/** The visible row window of a strike ladder for an index-domain view: first and last row index (inclusive). */
export function visibleRows(n: number, view: { min: number; max: number }): { i0: number; i1: number } {
  if (n <= 0) return { i0: 0, i1: -1 }
  const i0 = Math.max(0, Math.min(n - 1, Math.floor(view.min)))
  const i1 = Math.max(i0, Math.min(n - 1, Math.ceil(view.max)))
  return { i0, i1 }
}

/** The crosshair line a hovered strike row prints (values readable in the legend, never tooltip-only). */
export function rowLegend(strike: number, ce: number | null, pe: number | null, fmt: (v: number) => string): string {
  const f = (v: number | null) => (v == null || !Number.isFinite(v) ? '—' : fmt(v))
  return `${strike.toLocaleString('en-IN')} · calls ${f(ce)} · puts ${f(pe)}`
}

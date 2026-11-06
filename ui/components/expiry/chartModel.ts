/**
 * CHRT overlay helpers (5 Nov review M42 / M45), pure and dependency-free so ui/components/expiry/__tests__/expiry.check.ts
 * runs them under plain node; ChartStudio.tsx imports them.
 */
import type { ChartBar } from '@/lib/chartData'

export interface OverlayPoint { t: string; [k: string]: number | string | null | undefined }

const SESSION_FIRST = '09:15'
const SESSION_LAST = '15:30'

/** Intraday bars stamped 09:15–15:30 IST only (the tick store keeps post-close prints; 5 Nov's bars ran to 15:55). */
export function inSession<B extends Pick<ChartBar, 't'>>(bars: B[]): B[] {
  return bars.filter(b => b.t.slice(0, 5) >= SESSION_FIRST && b.t.slice(0, 5) <= SESSION_LAST)
}

/** An overlay's value for each bar time: the latest point dated on or before the bar (W / M bars take the bucket's last),
 *  never carried more than `maxGapDays` calendar days (a gap in the store stays a gap). Bar dates ascending. */
export function alignOverlay(points: OverlayPoint[], barDates: string[], key: string, maxGapDays = 10): (number | null)[] {
  const day = (iso: string) => Date.UTC(Number(iso.slice(0, 4)), Number(iso.slice(5, 7)) - 1, Number(iso.slice(8, 10))) / 86_400_000
  const out: (number | null)[] = []
  let j = 0
  let last: { v: number | null; t: string } | null = null
  for (const d of barDates) {
    while (j < points.length && points[j].t <= d) {
      const v = points[j][key]
      last = { v: typeof v === 'number' && Number.isFinite(v) ? v : null, t: points[j].t }
      j++
    }
    out.push(last && day(d) - day(last.t) <= maxGapDays ? last.v : null)
  }
  return out
}


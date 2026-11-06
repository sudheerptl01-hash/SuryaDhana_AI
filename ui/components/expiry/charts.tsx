'use client'

/**
 * Two small SVG charts for the tape and XPRY on the existing canvas kit (PLAN §0.13: no new dependency), drawn in CSS px
 * through `useChartSize`:
 *  - `SessionChart`: series against minutes after 09:15 IST (the axis reads HH:MM), a left and a right axis, an optional
 *    shaded band (the historical expiry-day curve's middle half);
 *  - `StrikeBars`: per strike, calls to the right and puts to the left (OI or its change), with the forward marked.
 * Context numbers use the neutral palette: calls cyan, puts violet — never green / red (PLAN §0.1, review m003).
 */
import { CHART_BOX, T, fmtFixed, useChartSize } from '@/components/terminal'
import { axisTicks } from '@/components/terminal/chart'
import { SESSION_LEN_MIN, minuteLabel } from './tapeModel'

export const CALL_COLOR = T.cyan
export const PUT_COLOR = T.violet

export interface SessionSeries { label: string; color: string; x: number[]; y: (number | null)[]; axis?: 'L' | 'R'; dash?: string; w?: number }

export function SessionChart({ series, height = 170, lUnit = '', rUnit = '', band, ariaLabel = 'session chart', xMax = SESSION_LEN_MIN }: {
  series: SessionSeries[]; height?: number; lUnit?: string; rUnit?: string
  band?: { x: number[]; lo: number[]; hi: number[]; color?: string }; ariaLabel?: string; xMax?: number
}) {
  const { ref, w: W, h: H } = useChartSize(900, height, { maxRatio: 1.2 })
  const hasR = series.some(s => s.axis === 'R')
  const padL = 52, padR = hasR ? 52 : 14, top = 8, chartH = H - 30
  const vals = (axis: 'L' | 'R') => series.filter(s => (s.axis ?? 'L') === axis).flatMap(s => s.y)
    .concat(axis === 'L' && band ? [...band.lo, ...band.hi] : []).filter((v): v is number => v != null && Number.isFinite(v))
  const range = (v: number[]) => {
    let lo = v.length ? Math.min(...v) : 0, hi = v.length ? Math.max(...v) : 1
    const pad = (hi - lo || Math.abs(hi) || 1) * 0.08
    lo -= pad; hi += pad
    return [lo, hi] as const
  }
  const [lLo, lHi] = range(vals('L')), [rLo, rHi] = range(vals('R'))
  const x = (m: number) => padL + (Math.max(0, Math.min(xMax, m)) / xMax) * (W - padL - padR)
  const yL = (v: number) => top + (1 - (v - lLo) / (lHi - lLo || 1)) * chartH
  const yR = (v: number) => top + (1 - (v - rLo) / (rHi - rLo || 1)) * chartH
  const path = (s: SessionSeries) => {
    const y = (s.axis ?? 'L') === 'L' ? yL : yR
    let pen = false
    return s.y.map((v, i) => {
      if (v == null || !Number.isFinite(v)) { pen = false; return '' }
      const seg = `${pen ? 'L' : 'M'}${x(s.x[i]).toFixed(1)},${y(v).toFixed(1)}`
      pen = true
      return seg
    }).join('')
  }
  const bandPath = band && band.x.length
    ? `M${band.x.map((m, i) => `${x(m).toFixed(1)},${yL(band.hi[i]).toFixed(1)}`).join('L')}L${[...band.x].reverse().map((m, i) =>
        `${x(m).toFixed(1)},${yL(band.lo[band.x.length - 1 - i]).toFixed(1)}`).join('L')}Z`
    : ''
  const lAxis = axisTicks(lLo, lHi, chartH)
  const rAxis = hasR ? axisTicks(rLo, rHi, chartH) : { ticks: [] as number[], dp: 0 }
  const hours = [0, 45, 105, 165, 225, 285, 345, 375].filter(m => m <= xMax)
  return (
    <div ref={ref} style={CHART_BOX}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ display: 'block' }} role="img" aria-label={ariaLabel}>
        {lAxis.ticks.map(v => (
          <g key={`l${v}`}>
            <line x1={padL} x2={W - padR} y1={yL(v)} y2={yL(v)} stroke={T.border} strokeDasharray="2 4" />
            <text x={padL - 6} y={yL(v) + 3} fill={T.dim} fontSize={10} fontFamily={T.mono} textAnchor="end">{fmtFixed(v, lAxis.dp)}{lUnit}</text>
          </g>
        ))}
        {rAxis.ticks.map(v => <text key={`r${v}`} x={W - padR + 6} y={yR(v) + 3} fill={T.dim} fontSize={10} fontFamily={T.mono}>{fmtFixed(v, rAxis.dp)}{rUnit}</text>)}
        {bandPath && <path d={bandPath} fill={band?.color ?? T.muted} opacity={0.16} />}
        {series.map(s => <path key={s.label} d={path(s)} fill="none" stroke={s.color} strokeWidth={s.w ?? 1.5} strokeDasharray={s.dash} opacity={0.95} />)}
        {hours.map(m => (
          <text key={m} x={x(m)} y={H - 8} fill={T.dim} fontSize={10} fontFamily={T.mono} textAnchor={m === 0 ? 'start' : m === xMax ? 'end' : 'middle'}>{minuteLabel(m)}</text>
        ))}
      </svg>
    </div>
  )
}

/** Calls to the right of the axis, puts to the left; `mark` = the forward (dashed line across). Values in the caller's unit. */
export function StrikeBars({ strikes, ce, pe, mark, height, fmt, ariaLabel = 'open interest by strike' }: {
  strikes: number[]; ce: (number | null)[]; pe: (number | null)[]; mark?: number | null; height?: number
  fmt: (v: number) => string; ariaLabel?: string
}) {
  const rowH = 13
  const baseH = height ?? Math.max(120, strikes.length * rowH + 24)
  const { ref, w: W } = useChartSize(900, baseH, { minRatio: 1, maxRatio: 1 })
  const H = baseH
  const mid = W / 2
  const lab = 58
  const span = Math.max(1, ...ce.map(v => Math.abs(v ?? 0)), ...pe.map(v => Math.abs(v ?? 0)))
  const half = Math.max(20, mid - lab / 2 - 8 - 56)                 // 56 px kept for the value label at the bar's end
  const w = (v: number | null) => (v == null || !Number.isFinite(v) ? 0 : (Math.abs(v) / span) * half)
  const y = (i: number) => 10 + i * rowH
  const markI = mark == null ? null : strikes.findIndex((k, i) => i === strikes.length - 1 || (k <= mark && strikes[i + 1] > mark))
  return (
    <div ref={ref} style={CHART_BOX}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ display: 'block' }} role="img" aria-label={ariaLabel}>
        <text x={mid + lab / 2 + 4} y={8} fill={CALL_COLOR} fontSize={9} fontFamily={T.mono}>CALLS →</text>
        <text x={mid - lab / 2 - 4} y={8} fill={PUT_COLOR} fontSize={9} fontFamily={T.mono} textAnchor="end">← PUTS</text>
        {strikes.map((k, i) => {
          const c = ce[i], p = pe[i]
          const neg = (v: number | null) => v != null && v < 0
          return (
            <g key={k}>
              <text x={mid} y={y(i) + 10} fill={T.muted} fontSize={10} fontFamily={T.mono} textAnchor="middle">{k.toLocaleString('en-IN')}</text>
              <rect x={mid + lab / 2} y={y(i) + 2} width={w(c)} height={rowH - 4} fill={CALL_COLOR} opacity={neg(c) ? 0.35 : 0.8} />
              <rect x={mid - lab / 2 - w(p)} y={y(i) + 2} width={w(p)} height={rowH - 4} fill={PUT_COLOR} opacity={neg(p) ? 0.35 : 0.8} />
              {c != null && <text x={mid + lab / 2 + w(c) + 3} y={y(i) + 10} fill={T.dim} fontSize={9} fontFamily={T.mono}>{fmt(c)}</text>}
              {p != null && <text x={mid - lab / 2 - w(p) - 3} y={y(i) + 10} fill={T.dim} fontSize={9} fontFamily={T.mono} textAnchor="end">{fmt(p)}</text>}
              <title>{`${k}: calls ${c == null ? '—' : fmt(c)} · puts ${p == null ? '—' : fmt(p)}`}</title>
            </g>
          )
        })}
        {markI != null && markI >= 0 && <line x1={8} x2={W - 8} y1={y(markI) + rowH} y2={y(markI) + rowH} stroke={T.amber} strokeDasharray="4 3" opacity={0.8} />}
      </svg>
    </div>
  )
}

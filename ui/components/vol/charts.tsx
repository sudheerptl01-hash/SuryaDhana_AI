'use client'

/**
 * Small SVG charts for the IV / drivers panels on the existing canvas kit (PLAN §0.13: no new charting dependency):
 * drawn in CSS px through `useChartSize` (C1-17), round ticks from terminal/chart.ts, month labels thinned to fit.
 *  - `LineChart`: up to a handful of series on a left and a right axis, optional shaded band (an IV cone's p25–p75),
 *    vertical event markers (results / expiry) and a dashed zero line.
 *  - `BarRow`: horizontal signed bars (sector contribution, monthly leader) in the neutral palette.
 */
import { CHART_BOX, T, fmtFixed, useChartSize } from '@/components/terminal'
import { axisTicks, textWidth } from '@/components/terminal/chart'

export interface LineSeries { label: string; color: string; values: (number | null | undefined)[]; axis?: 'L' | 'R'; dash?: string; w?: number }
export interface Marker { i: number; kind: string }

export function LineChart({ dates, series, height = 200, zero = false, lUnit = '', rUnit = '', band, markers = [], ariaLabel = 'time series' }: {
  dates: string[]; series: LineSeries[]; height?: number; zero?: boolean; lUnit?: string; rUnit?: string
  /** a shaded band on the left axis (lo / hi per point) */
  band?: { lo: (number | null)[]; hi: (number | null)[]; color?: string }
  markers?: Marker[]; ariaLabel?: string
}) {
  const { ref, w: W, h: H } = useChartSize(900, height, { maxRatio: 1.25 })
  const hasR = series.some(s => s.axis === 'R')
  const padL = 50, padR = hasR ? 46 : 14, top = 10, chartH = H - 42
  const vals = (axis: 'L' | 'R') => series.filter(s => (s.axis ?? 'L') === axis).flatMap(s => s.values)
    .concat(axis === 'L' && band ? [...band.lo, ...band.hi] : [])
    .filter((v): v is number => v != null && Number.isFinite(v))
  const lv = vals('L'), rv = vals('R')
  let lLo = lv.length ? Math.min(...lv) : 0, lHi = lv.length ? Math.max(...lv) : 1
  if (zero) { lLo = Math.min(lLo, 0); lHi = Math.max(lHi, 0) }
  const lPad = (lHi - lLo || 1) * 0.06; lLo -= lPad; lHi += lPad
  let rLo = rv.length ? Math.min(...rv) : 0, rHi = rv.length ? Math.max(...rv) : 1
  const rPad = (rHi - rLo || 1) * 0.06; rLo -= rPad; rHi += rPad
  const n = Math.max(dates.length - 1, 1)
  const x = (i: number) => padL + (i / n) * (W - padL - padR)
  const yL = (v: number) => top + (1 - (v - lLo) / (lHi - lLo || 1)) * chartH
  const yR = (v: number) => top + (1 - (v - rLo) / (rHi - rLo || 1)) * chartH
  const path = (s: LineSeries) => {
    const y = (s.axis ?? 'L') === 'L' ? yL : yR
    return s.values.map((v, i) => (v == null || !Number.isFinite(v) ? '' :
      `${i === 0 || s.values[i - 1] == null || !Number.isFinite(s.values[i - 1] as number) ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`)).join('')
  }
  const bandPath = (() => {
    if (!band) return ''
    const up: string[] = [], down: string[] = []
    band.hi.forEach((v, i) => { const lo = band.lo[i]; if (v != null && lo != null && Number.isFinite(v) && Number.isFinite(lo)) { up.push(`${x(i).toFixed(1)},${yL(v).toFixed(1)}`); down.unshift(`${x(i).toFixed(1)},${yL(lo).toFixed(1)}`) } })
    return up.length ? `M${up.join('L')}L${down.join('L')}Z` : ''
  })()
  const months = dates.map((d, i) => ({ i, m: d.slice(0, 7) })).filter((p, i, a) => i === 0 || p.m !== a[i - 1].m)
  const pitch = months.length > 1 ? (W - padL - padR) / months.length : W
  const every = Math.max(1, Math.ceil(56 / Math.max(pitch, 1)), Math.ceil(months.length / 14))
  const lAxis = axisTicks(lLo, lHi, chartH)
  const rAxis = rv.length ? axisTicks(rLo, rHi, chartH) : { ticks: [] as number[], dp: 0 }
  const markerColor = (k: string) => (k === 'results' ? T.violet : k === 'expiry' ? T.dim : T.cyan)
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
      {zero && lLo < 0 && lHi > 0 && <line x1={padL} x2={W - padR} y1={yL(0)} y2={yL(0)} stroke={T.borderHi} strokeDasharray="4 4" />}
      {bandPath && <path d={bandPath} fill={band?.color ?? T.violet} opacity={0.14} />}
      {markers.filter(m => m.i >= 0 && m.i < dates.length).map((m, k) => (
        <line key={`m${k}`} x1={x(m.i)} x2={x(m.i)} y1={top} y2={top + chartH} stroke={markerColor(m.kind)} strokeDasharray={m.kind === 'expiry' ? '1 3' : '3 3'} opacity={m.kind === 'expiry' ? 0.5 : 0.9}>
          <title>{`${m.kind} · ${dates[m.i]}`}</title>
        </line>
      ))}
      {series.map(s => <path key={s.label} d={path(s)} fill="none" stroke={s.color} strokeWidth={s.w ?? 1.5} strokeDasharray={s.dash} opacity={0.95} />)}
      {months.filter((_, k) => k % every === 0).filter(p => x(p.i) + textWidth('Mmm 26', 10) <= W).map(p => (
        <text key={p.m} x={x(p.i)} y={H - 6} fill={T.dim} fontSize={10} fontFamily={T.mono}>
          {new Date(`${p.m}-01T00:00:00`).toLocaleDateString('en-IN', { month: 'short', year: '2-digit' })}
        </text>
      ))}
    </svg>
    </div>
  )
}

/** Signed horizontal bars (sector contribution, leaderboard): neutral palette, sign by direction only (PLAN §0.1). */
export function BarRow({ label, value, max, unit = '', color = T.cyan, sub }: { label: React.ReactNode; value: number | null; max: number; unit?: string; color?: string; sub?: React.ReactNode }) {
  const v = value ?? 0
  const pct = max > 0 ? Math.min(100, (Math.abs(v) / max) * 100) : 0
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '150px 1fr 76px', gap: 8, alignItems: 'center', fontSize: 11, fontFamily: T.mono, padding: '2px 0' }}>
      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{label}</span>
      <div style={{ height: 8, background: '#0f141d', position: 'relative' }}>
        <div style={{ position: 'absolute', top: 0, bottom: 0, left: v < 0 ? `${50 - pct / 2}%` : '50%', width: `${pct / 2}%`, background: color, opacity: 0.8 }} />
        <div style={{ position: 'absolute', top: 0, bottom: 0, left: '50%', width: 1, background: T.border }} />
      </div>
      <span style={{ textAlign: 'right', color: T.text }}>{value == null ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(1)}${unit}`}{sub}</span>
    </div>
  )
}

/** An x–y line chart on numeric axes (the smile: IV against log-moneyness), today solid and a ghost dashed. */
export function XYChart({ series, height = 170, xLabel = '', yUnit = '%', ariaLabel = 'x-y chart', markX }: {
  series: { label: string; color: string; points: { x: number; y: number }[]; dash?: string; w?: number }[]
  height?: number; xLabel?: string; yUnit?: string; ariaLabel?: string
  /** a vertical reference line (log-moneyness 0 = the forward) */
  markX?: number | null
}) {
  const { ref, w: W, h: H } = useChartSize(520, height, { maxRatio: 1.25 })
  const pts = series.flatMap(s => s.points).filter(p => Number.isFinite(p.x) && Number.isFinite(p.y))
  const padL = 44, padR = 12, top = 8, chartH = H - 38
  if (pts.length < 2) return <div ref={ref} style={CHART_BOX} />
  let xLo = Math.min(...pts.map(p => p.x)), xHi = Math.max(...pts.map(p => p.x))
  let yLo = Math.min(...pts.map(p => p.y)), yHi = Math.max(...pts.map(p => p.y))
  const xp = (xHi - xLo || 1) * 0.03, yp = (yHi - yLo || 1) * 0.08
  xLo -= xp; xHi += xp; yLo -= yp; yHi += yp
  const x = (v: number) => padL + ((v - xLo) / (xHi - xLo || 1)) * (W - padL - padR)
  const y = (v: number) => top + (1 - (v - yLo) / (yHi - yLo || 1)) * chartH
  const yAxis = axisTicks(yLo, yHi, chartH)
  const xAxis = axisTicks(xLo, xHi, Math.max(60, (W - padL - padR) / 2.2))
  return (
    <div ref={ref} style={CHART_BOX}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ display: 'block' }} role="img" aria-label={ariaLabel}>
        {yAxis.ticks.map(v => (
          <g key={`y${v}`}>
            <line x1={padL} x2={W - padR} y1={y(v)} y2={y(v)} stroke={T.border} strokeDasharray="2 4" />
            <text x={padL - 6} y={y(v) + 3} fill={T.dim} fontSize={10} fontFamily={T.mono} textAnchor="end">{fmtFixed(v, yAxis.dp)}{yUnit}</text>
          </g>
        ))}
        {xAxis.ticks.map(v => <text key={`x${v}`} x={x(v)} y={H - 16} fill={T.dim} fontSize={10} fontFamily={T.mono} textAnchor="middle">{fmtFixed(v, xAxis.dp)}</text>)}
        {markX != null && markX >= xLo && markX <= xHi && <line x1={x(markX)} x2={x(markX)} y1={top} y2={top + chartH} stroke={T.amber} strokeDasharray="3 3" opacity={0.7} />}
        {series.map(s => {
          const ps = s.points.filter(p => Number.isFinite(p.x) && Number.isFinite(p.y)).sort((a, b) => a.x - b.x)
          return <path key={s.label} d={ps.map((p, i) => `${i ? 'L' : 'M'}${x(p.x).toFixed(1)},${y(p.y).toFixed(1)}`).join('')} fill="none"
            stroke={s.color} strokeWidth={s.w ?? 1.5} strokeDasharray={s.dash} opacity={0.95} />
        })}
        {xLabel && <text x={W - padR} y={H - 3} fill={T.dim} fontSize={9.5} fontFamily={T.mono} textAnchor="end">{xLabel}</text>}
      </svg>
    </div>
  )
}

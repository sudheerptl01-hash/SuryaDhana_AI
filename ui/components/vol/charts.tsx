'use client'

/**
 * Small SVG charts for the IV / drivers panels on the existing canvas kit (PLAN §0.13: no new charting dependency):
 * drawn in CSS px through `useChartSize` (C1-17), round ticks from terminal/chart.ts, month labels thinned to fit.
 *  - `LineChart`: up to a handful of series on a left and a right axis, optional shaded band (an IV cone's p25–p75),
 *    vertical event markers (results / expiry) and a dashed zero line.
 *  - `BarRow`: horizontal signed bars (sector contribution, monthly leader) in the neutral palette.
 *  - `XYChart`: an x–y line chart on numeric axes (the smile: IV against log-moneyness).
 *
 * FINAL ROUND W3 (charts/PLAN.md §4, SVG kit v2): `LineChart` and `XYChart` carry `useChartInteraction` —
 * wheel + pinch x-zoom, drag pan, double-click reset and a nearest-point crosshair whose values are printed in the
 * surrounding ExpandableChart legend slot (or an inline readout when the chart is mounted bare — readable, never
 * tooltip-only). Every existing call site (MKT drivers, IvHistoryChart until B-OMON's conversion lands) inherits the
 * interaction with NO API change; the props and exports are unchanged. `BarRow` stays a one-value meter on purpose:
 * an x-zoom has no meaning on it and a wheel-capturing listener on an 8-px row would break page scroll over the
 * drivers leaderboards (its exact value is already printed on the row).
 */
import { useCallback, useEffect, useId, useMemo, useRef, type CSSProperties, type ReactNode } from 'react'
import { CHART_BOX, T, fmtFixed, useChartSize } from '@/components/terminal'
import { Crosshair, axisTicks, textWidth, useChartInteraction } from '@/components/terminal/chart'
import { useChartShell } from '@/components/terminal/ExpandableChart'

export interface LineSeries { label: string; color: string; values: (number | null | undefined)[]; axis?: 'L' | 'R'; dash?: string; w?: number }
export interface Marker { i: number; kind: string }

// ── shell wiring shared by the SVG v2 charts (also used by DERV's RollCurve) ─────────────────────────

/** The inline crosshair readout when a chart is mounted without an ExpandableChart shell. */
const READOUT: CSSProperties = {
  position: 'absolute', top: 2, right: 8, fontFamily: T.mono, fontSize: 10, color: T.muted,
  background: 'rgba(10,13,19,0.88)', border: `1px solid ${T.border}`, padding: '1px 6px',
  pointerEvents: 'none', zIndex: 2, maxWidth: '85%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
}

/**
 * `useChartSize` hands out a callback ref; `useChartInteraction` wants a ref OBJECT. This pairs them: pass `setRef`
 * to the wrapper div and `box` to the interaction hook (exported for DERV's RollCurve, which lives outside this file).
 */
export function useInteractionRef(sizeRef: (el: HTMLElement | null) => void) {
  const box = useRef<HTMLDivElement | null>(null)
  const setRef = useCallback((el: HTMLDivElement | null) => { box.current = el; sizeRef(el) }, [sizeRef])
  return { box, setRef }
}

/**
 * Wire an SVG v2 chart to its surrounding ExpandableChart (when one exists): the crosshair `readout` goes to the
 * shell legend slot and the shell's FIT button maps to the interaction's reset. Returns true when a shell is
 * present (the caller then skips its inline readout). Values stay readable either way — never tooltip-only.
 */
export function useShellWiring(readout: ReactNode | null, reset: () => void): boolean {
  const shell = useChartShell()
  const resetRef = useRef(reset)
  resetRef.current = reset
  useEffect(() => {
    if (!shell) return
    return shell.registerActions({ fit: () => resetRef.current() })
  }, [shell])
  useEffect(() => {
    if (!shell) return
    shell.setLegend(readout)
  }, [shell, readout])
  useEffect(() => {
    if (!shell) return
    return () => shell.setLegend(null)
  }, [shell])
  return !!shell
}

export function LineChart({ dates, series, height = 200, zero = false, lUnit = '', rUnit = '', band, markers = [], ariaLabel = 'time series' }: {
  dates: string[]; series: LineSeries[]; height?: number; zero?: boolean; lUnit?: string; rUnit?: string
  /** a shaded band on the left axis (lo / hi per point) */
  band?: { lo: (number | null)[]; hi: (number | null)[]; color?: string }
  markers?: Marker[]; ariaLabel?: string
}) {
  const { ref, w: W, h: H } = useChartSize(900, height, { maxRatio: 1.25 })
  const { box, setRef } = useInteractionRef(ref)
  const clipId = useId().replace(/[^a-zA-Z0-9_-]/g, '')
  const hasR = series.some(s => s.axis === 'R')
  const padL = 50, padR = hasR ? 46 : 14, top = 10, chartH = H - 42
  const plotW = W - padL - padR
  const n = dates.length
  // SVG kit v2: wheel / pinch x-zoom, drag pan, double-click reset, nearest-point crosshair over the index domain
  const idx = useMemo(() => dates.map((_, i) => i), [dates])
  const ia = useChartInteraction(box, { min: 0, max: Math.max(n - 1, 1) }, { points: idx })
  ia.setPlot(padL, plotW)
  const view = ia.view

  const vals = (axis: 'L' | 'R') => series.filter(s => (s.axis ?? 'L') === axis).flatMap(s => s.values)
    .concat(axis === 'L' && band ? [...band.lo, ...band.hi] : [])
    .filter((v): v is number => v != null && Number.isFinite(v))
  const lv = vals('L'), rv = vals('R')
  let lLo = lv.length ? Math.min(...lv) : 0, lHi = lv.length ? Math.max(...lv) : 1
  if (zero) { lLo = Math.min(lLo, 0); lHi = Math.max(lHi, 0) }
  const lPad = (lHi - lLo || 1) * 0.06; lLo -= lPad; lHi += lPad
  let rLo = rv.length ? Math.min(...rv) : 0, rHi = rv.length ? Math.max(...rv) : 1
  const rPad = (rHi - rLo || 1) * 0.06; rLo -= rPad; rHi += rPad
  const span = view.max - view.min || 1
  const x = (i: number) => padL + ((i - view.min) / span) * plotW
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
  const visMonths = months.filter(p => p.i >= view.min - 0.5 && p.i <= view.max + 0.5)
  const pitch = visMonths.length > 1 ? plotW / visMonths.length : plotW
  const every = Math.max(1, Math.ceil(56 / Math.max(pitch, 1)), Math.ceil(visMonths.length / 14))
  const lAxis = axisTicks(lLo, lHi, chartH)
  const rAxis = rv.length ? axisTicks(rLo, rHi, chartH) : { ticks: [] as number[], dp: 0 }
  const markerColor = (k: string) => (k === 'results' ? T.violet : k === 'expiry' ? T.dim : T.cyan)

  // crosshair readout: the snapped session's date + every series value there (shell legend, or inline when bare)
  const ci = ia.cursor && ia.cursor.i >= 0 && ia.cursor.i < n && ia.cursor.i >= Math.floor(view.min) && ia.cursor.i <= Math.ceil(view.max) ? ia.cursor.i : null
  const readout = ci == null ? null : (
    <span>
      <span style={{ color: T.dim }}>{dates[ci]}</span>
      {series.map((s, k) => {
        const v = s.values[ci]
        if (v == null || !Number.isFinite(v)) return null
        const dp = (s.axis ?? 'L') === 'L' ? lAxis.dp : rAxis.dp
        const unit = (s.axis ?? 'L') === 'L' ? lUnit : rUnit
        return <span key={k}> · {s.label} <b style={{ color: s.color, fontWeight: 400 }}>{fmtFixed(v, Math.min(dp + 1, 2))}{unit}</b></span>
      })}
    </span>
  )
  const hasShell = useShellWiring(readout, ia.reset)
  const firstY = (() => {
    if (ci == null) return null
    for (const s of series) {
      const v = s.values[ci]
      if (v != null && Number.isFinite(v)) return ((s.axis ?? 'L') === 'L' ? yL : yR)(v)
    }
    return null
  })()

  return (
    <div ref={setRef} style={{ ...CHART_BOX, position: 'relative', touchAction: 'none', cursor: 'crosshair' }}>
    {!hasShell && readout && <div style={READOUT}>{readout}</div>}
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ display: 'block' }} role="img" aria-label={ariaLabel}>
      <defs><clipPath id={clipId}><rect x={padL} y={0} width={Math.max(plotW, 0)} height={H} /></clipPath></defs>
      {lAxis.ticks.map(v => (
        <g key={`l${v}`}>
          <line x1={padL} x2={W - padR} y1={yL(v)} y2={yL(v)} stroke={T.border} strokeDasharray="2 4" />
          <text x={padL - 6} y={yL(v) + 3} fill={T.dim} fontSize={10} fontFamily={T.mono} textAnchor="end">{fmtFixed(v, lAxis.dp)}{lUnit}</text>
        </g>
      ))}
      {rAxis.ticks.map(v => <text key={`r${v}`} x={W - padR + 6} y={yR(v) + 3} fill={T.dim} fontSize={10} fontFamily={T.mono}>{fmtFixed(v, rAxis.dp)}{rUnit}</text>)}
      {zero && lLo < 0 && lHi > 0 && <line x1={padL} x2={W - padR} y1={yL(0)} y2={yL(0)} stroke={T.borderHi} strokeDasharray="4 4" />}
      <g clipPath={`url(#${clipId})`}>
        {bandPath && <path d={bandPath} fill={band?.color ?? T.violet} opacity={0.14} />}
        {markers.filter(m => m.i >= 0 && m.i < dates.length).map((m, k) => (
          <line key={`m${k}`} x1={x(m.i)} x2={x(m.i)} y1={top} y2={top + chartH} stroke={markerColor(m.kind)} strokeDasharray={m.kind === 'expiry' ? '1 3' : '3 3'} opacity={m.kind === 'expiry' ? 0.5 : 0.9}>
            <title>{`${m.kind} · ${dates[m.i]}`}</title>
          </line>
        ))}
        {series.map(s => <path key={s.label} d={path(s)} fill="none" stroke={s.color} strokeWidth={s.w ?? 1.5} strokeDasharray={s.dash} opacity={0.95} />)}
        {ci != null && <Crosshair x={x(ci)} y={firstY} top={top} height={chartH} left={padL} width={plotW} />}
      </g>
      {(() => {
        const labels = visMonths.filter((_, k) => k % every === 0).filter(p => x(p.i) >= padL - 1 && x(p.i) + textWidth('Mmm 26', 10) <= W)
        if (labels.length) return labels.map(p => (
          <text key={p.m} x={x(p.i)} y={H - 6} fill={T.dim} fontSize={10} fontFamily={T.mono}>
            {new Date(`${p.m}-01T00:00:00`).toLocaleDateString('en-IN', { month: 'short', year: '2-digit' })}
          </text>
        ))
        // zoomed inside one month: label the visible edges with their session dates instead
        const i0 = Math.max(0, Math.ceil(view.min)), i1 = Math.min(n - 1, Math.floor(view.max))
        if (i0 > i1) return null
        return (
          <g>
            <text x={padL} y={H - 6} fill={T.dim} fontSize={10} fontFamily={T.mono}>{dates[i0]}</text>
            {i1 > i0 && <text x={W - padR} y={H - 6} fill={T.dim} fontSize={10} fontFamily={T.mono} textAnchor="end">{dates[i1]}</text>}
          </g>
        )
      })()}
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
  series: { label: string; color: string; points: { x: number; y: number; label?: string }[]; dash?: string; w?: number }[]
  height?: number; xLabel?: string; yUnit?: string; ariaLabel?: string
  /** a vertical reference line (log-moneyness 0 = the forward) */
  markX?: number | null
}) {
  const { ref, w: W, h: H } = useChartSize(520, height, { maxRatio: 1.25 })
  const { box, setRef } = useInteractionRef(ref)
  const clipId = useId().replace(/[^a-zA-Z0-9_-]/g, '')
  const pts = series.flatMap(s => s.points).filter(p => Number.isFinite(p.x) && Number.isFinite(p.y))
  const padL = 44, padR = 12, top = 8, chartH = H - 38
  const plotW = W - padL - padR
  let xLo = pts.length ? Math.min(...pts.map(p => p.x)) : 0, xHi = pts.length ? Math.max(...pts.map(p => p.x)) : 1
  let yLo = pts.length ? Math.min(...pts.map(p => p.y)) : 0, yHi = pts.length ? Math.max(...pts.map(p => p.y)) : 1
  const xp = (xHi - xLo || 1) * 0.03, yp = (yHi - yLo || 1) * 0.08
  xLo -= xp; xHi += xp; yLo -= yp; yHi += yp
  // SVG kit v2: zoom / pan / crosshair over the numeric x-domain; the crosshair snaps to the FIRST series' points
  const anchor = useMemo(() => {
    const s0 = series[0]
    return (s0 ? s0.points.filter(p => Number.isFinite(p.x) && Number.isFinite(p.y)).sort((a, b) => a.x - b.x) : [])
  }, [series])
  const ia = useChartInteraction(box, { min: xLo, max: xHi }, { points: anchor.map(p => p.x) })
  ia.setPlot(padL, plotW)
  const view = ia.view
  const cp = ia.cursor && anchor[ia.cursor.i] && anchor[ia.cursor.i].x >= view.min && anchor[ia.cursor.i].x <= view.max ? anchor[ia.cursor.i] : null
  const xDp = Math.abs(view.max - view.min) < 1 ? 3 : 1
  const readout = cp == null ? null : (
    <span>
      <span style={{ color: T.dim }}>{cp.label ?? `x ${cp.x.toFixed(xDp)}`}</span>
      {cp.label == null ? null : <span style={{ color: T.dim }}> · x {cp.x.toFixed(xDp)}</span>}
      <span> · <b style={{ color: series[0]?.color ?? T.text, fontWeight: 400 }}>{cp.y.toFixed(2)}{yUnit}</b></span>
    </span>
  )
  const hasShell = useShellWiring(readout, ia.reset)
  if (pts.length < 2) return <div ref={setRef} style={CHART_BOX} />
  const x = (v: number) => padL + ((v - view.min) / (view.max - view.min || 1)) * plotW
  const y = (v: number) => top + (1 - (v - yLo) / (yHi - yLo || 1)) * chartH
  const yAxis = axisTicks(yLo, yHi, chartH)
  const xAxis = axisTicks(view.min, view.max, Math.max(60, plotW / 2.2))
  return (
    <div ref={setRef} style={{ ...CHART_BOX, position: 'relative', touchAction: 'none', cursor: 'crosshair' }}>
      {!hasShell && readout && <div style={READOUT}>{readout}</div>}
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ display: 'block' }} role="img" aria-label={ariaLabel}>
        <defs><clipPath id={clipId}><rect x={padL} y={0} width={Math.max(plotW, 0)} height={H} /></clipPath></defs>
        {yAxis.ticks.map(v => (
          <g key={`y${v}`}>
            <line x1={padL} x2={W - padR} y1={y(v)} y2={y(v)} stroke={T.border} strokeDasharray="2 4" />
            <text x={padL - 6} y={y(v) + 3} fill={T.dim} fontSize={10} fontFamily={T.mono} textAnchor="end">{fmtFixed(v, yAxis.dp)}{yUnit}</text>
          </g>
        ))}
        {xAxis.ticks.filter(v => v >= view.min && v <= view.max).map(v => <text key={`x${v}`} x={x(v)} y={H - 16} fill={T.dim} fontSize={10} fontFamily={T.mono} textAnchor="middle">{fmtFixed(v, xAxis.dp)}</text>)}
        <g clipPath={`url(#${clipId})`}>
          {markX != null && markX >= view.min && markX <= view.max && <line x1={x(markX)} x2={x(markX)} y1={top} y2={top + chartH} stroke={T.amber} strokeDasharray="3 3" opacity={0.7} />}
          {series.map(s => {
            const ps = s.points.filter(p => Number.isFinite(p.x) && Number.isFinite(p.y)).sort((a, b) => a.x - b.x)
            return <path key={s.label} d={ps.map((p, i) => `${i ? 'L' : 'M'}${x(p.x).toFixed(1)},${y(p.y).toFixed(1)}`).join('')} fill="none"
              stroke={s.color} strokeWidth={s.w ?? 1.5} strokeDasharray={s.dash} opacity={0.95} />
          })}
          {cp != null && <Crosshair x={x(cp.x)} y={y(cp.y)} top={top} height={chartH} left={padL} width={plotW} />}
        </g>
        {xLabel && <text x={W - padR} y={H - 3} fill={T.dim} fontSize={9.5} fontFamily={T.mono} textAnchor="end">{xLabel}</text>}
      </svg>
    </div>
  )
}

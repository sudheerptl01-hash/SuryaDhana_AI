'use client'

/**
 * The two expiry/tape charts, on the FINAL ROUND interactive kit (charts/PLAN.md §4, rows B2/B3/B5; B-XPRY):
 *  - `SessionChart`: series against minutes after 09:15 IST, now rendered by lightweight-charts through
 *    `InteractiveSeries` (wheel zoom, drag pan, crosshair; intraday timestamps first-class — the minute grid is
 *    turned into IST wall-clock times by `chartsModel.minuteToTime`); the historical expiry-day band is the
 *    kit's area-pair. Inside an `ExpandableChart` the crosshair values fill the shell legend; mounted bare, a
 *    legend line under the chart prints them (values readable, never tooltip-only).
 *  - `StrikeBars`: per strike, calls to the right and puts to the left (SVG kit v2 — the strike axis is not a
 *    time axis): wheel zoom and drag pan over the strike window, double-click reset, and a crosshair that snaps
 *    to the nearest strike row and prints strike + both sides' OI.
 * Component APIs are unchanged (optional `date`/`linkGroup` added), so OiTape/ExpiryDay callers inherit.
 * Context numbers use the neutral palette: calls cyan, puts violet — never green / red (PLAN §0.1, review m003).
 */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { CHART_BOX, T, useChartSize } from '@/components/terminal'
import { clampDomain, panDomain, zoomDomain, type XDomain } from '@/components/terminal/chart'
import { useChartShell } from '@/components/terminal/ExpandableChart'
import { InteractiveSeries, type InteractiveSeriesProps, type SeriesSpec } from '@/components/terminal/InteractiveSeries'
import { istDateOf, rowLegend, sessionFormat, sessionPoints, visibleRows, SESSION_LEN_MIN } from './chartsModel'

export const CALL_COLOR = T.cyan
export const PUT_COLOR = T.violet

export interface SessionSeries { label: string; color: string; x: number[]; y: (number | null)[]; axis?: 'L' | 'R'; dash?: string; w?: number }

const LEGEND_STYLE = { fontFamily: T.mono, fontSize: 10, color: T.muted, marginTop: 3, minHeight: 14,
                       whiteSpace: 'nowrap' as const, overflow: 'hidden', textOverflow: 'ellipsis' }

export function SessionChart({ series, height = 170, lUnit = '', rUnit = '', band, ariaLabel = 'session chart', xMax = SESSION_LEN_MIN,
                               date = null, linkGroup, onReady }: {
  series: SessionSeries[]; height?: number; lUnit?: string; rUnit?: string
  band?: { x: number[]; lo: number[]; hi: number[]; color?: string }; ariaLabel?: string; xMax?: number
  /** the session date (YYYY-MM-DD) the minutes belong to — honest crosshair time text; today (IST) when omitted */
  date?: string | null
  /** panes registering the same group share visible range + crosshair (one trading calendar only) */
  linkGroup?: string
  /** the kit's escape hatch (overlays, probes) — see InteractiveSeries.onReady */
  onReady?: InteractiveSeriesProps['onReady']
}) {
  const shell = useChartShell()
  const [cursor, setCursor] = useState<string | null>(null)
  const day = date ?? istDateOf(Date.now())
  const fmtL = sessionFormat(lUnit)
  const fmtR = sessionFormat(rUnit)
  const specs: SeriesSpec[] = series.map((s, i) => ({
    id: `s${i}-${s.label.replace(/[^a-z0-9]+/gi, '-')}`, label: s.label, color: s.color, type: 'line',
    axis: s.axis ?? 'L', w: s.w ?? 1.5, dashed: !!s.dash, format: (s.axis ?? 'L') === 'L' ? fmtL : fmtR,
    points: sessionPoints(day, s.x, s.y, xMax),
  }))
  const bandSpec = band && band.x.length
    ? { lo: sessionPoints(day, band.x, band.lo, xMax), hi: sessionPoints(day, band.x, band.hi, xMax), color: band.color ?? T.muted, axis: 'L' as const }
    : null
  const labelOf = new Map(specs.map(s => [s.id, { label: s.label ?? s.id, format: s.format }]))
  const chart = (
    <InteractiveSeries series={specs} band={bandSpec} unitL={lUnit} unitR={rUnit} height={height} linkGroup={linkGroup}
      ariaLabel={ariaLabel} onReady={onReady}
      onCrosshair={shell ? undefined : (t, values) => {
        if (t == null) { setCursor(null); return }
        const parts = Object.entries(values).filter(([, v]) => v != null)
          .map(([id, v]) => `${labelOf.get(id)?.label ?? id} ${(labelOf.get(id)?.format ?? String)(v as number)}`)
        setCursor(parts.length ? `${t} · ${parts.join(' · ')}` : t)
      }} />
  )
  if (shell) return <div style={{ height: '100%', minHeight: Math.min(height, 120), minWidth: 0 }}>{chart}</div>
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ height, minWidth: 0 }}>{chart}</div>
      <div data-sd-chart-cursor style={LEGEND_STYLE}>{cursor ?? 'wheel = zoom · drag = pan · double-click = reset'}</div>
    </div>
  )
}

// ── SVG kit v2, vertical: the strike ladder's interaction (index domain along Y) ──────────────────────
// `useChartInteraction` (terminal/chart.ts) is x-domain only; the ladder's strike axis runs vertically, so this
// local hook reuses the kit's pure math (zoomDomain / panDomain / clampDomain) with clientY in place of clientX.

interface VerticalInteraction { view: XDomain; zoomed: boolean; hover: number | null; setPlot: (top: number, height: number) => void }

function useVerticalInteraction(ref: { readonly current: Element | null }, n: number,
                                onHover?: (i: number | null) => void): VerticalInteraction {
  const full: XDomain = { min: 0, max: Math.max(0, n - 1) }
  const [view, setView] = useState<XDomain>(full)
  const [zoomed, setZoomed] = useState(false)
  const [hover, setHover] = useState<number | null>(null)
  const st = useRef({ view, full, onHover, plot: { top: 0, height: 1 }, drag: null as { py: number; view: XDomain; moved: boolean } | null,
                      hoverI: null as number | null })
  st.current.view = view
  st.current.onHover = onHover

  useEffect(() => {                                   // new ladder length: reset unless the user zoomed
    st.current.full = { min: 0, max: Math.max(0, n - 1) }
    setView(v => (zoomed ? clampDomain(v, st.current.full) : { ...st.current.full }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [n])

  useEffect(() => {
    const el = ref.current
    if (!el || typeof window === 'undefined') return
    const s = st.current
    const frac = (clientY: number): number => {
      const r = el.getBoundingClientRect()
      return s.plot.height > 0 ? (clientY - r.top - s.plot.top) / s.plot.height : 0.5
    }
    const apply = (next: XDomain) => {
      const isFull = Math.abs(next.min - s.full.min) < 1e-9 && Math.abs(next.max - s.full.max) < 1e-9
      setView(next)
      setZoomed(!isFull)
    }
    const report = (i: number | null) => {
      if (i === s.hoverI) return
      s.hoverI = i
      setHover(i)
      s.onHover?.(i)
    }
    const hoverAt = (clientY: number) => {
      const f = frac(clientY)
      if (f < -0.02 || f > 1.02) { report(null); return }
      const i = Math.round(s.view.min + f * (s.view.max - s.view.min))
      report(Math.max(0, Math.min(Math.round(s.full.max), i)))
    }
    const minSpan = () => Math.min(4, Math.max(1, s.full.max))
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const factor = Math.exp((e.deltaY || 0) * (e.ctrlKey ? 0.01 : 0.0022))
      apply(zoomDomain(s.view, s.full, factor, frac(e.clientY), minSpan()))
    }
    const onDown = (e: PointerEvent) => {
      if (e.button !== 0 && e.pointerType === 'mouse') return
      try { (el as HTMLElement).setPointerCapture?.(e.pointerId) } catch { /* detached */ }
      s.drag = { py: e.clientY, view: { ...s.view }, moved: false }
    }
    const onMove = (e: PointerEvent) => {
      if (s.drag) {
        const dy = e.clientY - s.drag.py
        if (Math.abs(dy) > 2) s.drag.moved = true
        if (s.drag.moved) {
          apply(panDomain(s.drag.view, s.full, s.plot.height > 0 ? -dy / s.plot.height : 0))
          return
        }
      }
      hoverAt(e.clientY)
    }
    const onUp = () => { s.drag = null }
    const onLeave = () => { s.drag = null; report(null) }
    const onDbl = () => apply({ ...s.full })
    el.addEventListener('wheel', onWheel as EventListener, { passive: false })
    el.addEventListener('pointerdown', onDown as EventListener)
    el.addEventListener('pointermove', onMove as EventListener)
    el.addEventListener('pointerup', onUp as EventListener)
    el.addEventListener('pointercancel', onUp as EventListener)
    el.addEventListener('pointerleave', onLeave as EventListener)
    el.addEventListener('dblclick', onDbl as EventListener)
    return () => {
      el.removeEventListener('wheel', onWheel as EventListener)
      el.removeEventListener('pointerdown', onDown as EventListener)
      el.removeEventListener('pointermove', onMove as EventListener)
      el.removeEventListener('pointerup', onUp as EventListener)
      el.removeEventListener('pointercancel', onUp as EventListener)
      el.removeEventListener('pointerleave', onLeave as EventListener)
      el.removeEventListener('dblclick', onDbl as EventListener)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ref.current])

  return { view, zoomed, hover, setPlot: (top, height) => { st.current.plot = { top, height: Math.max(1, height) } } }
}

/** Calls to the right of the axis, puts to the left; `mark` = the forward (dashed line across). Values in the caller's unit. */
export function StrikeBars({ strikes, ce, pe, mark, height, fmt, ariaLabel = 'open interest by strike' }: {
  strikes: number[]; ce: (number | null)[]; pe: (number | null)[]; mark?: number | null; height?: number
  fmt: (v: number) => string; ariaLabel?: string
}) {
  const rowH0 = 13
  const baseH = height ?? Math.max(120, strikes.length * rowH0 + 24)
  const { ref, w: W } = useChartSize(900, baseH, { minRatio: 1, maxRatio: 1 })
  const svgRef = useRef<SVGSVGElement | null>(null)
  const shell = useChartShell()
  const [cursor, setCursor] = useState<string | null>(null)
  const n = strikes.length
  const H = baseH
  const top = 10
  const plotH = H - top - 14
  const ia = useVerticalInteraction(svgRef, n, i => {
    const line = i == null || i >= n ? null : rowLegend(strikes[i], ce[i], pe[i], fmt)
    if (shell) shell.setLegend(line)
    else setCursor(line)
  })
  ia.setPlot(top, plotH)
  const { i0, i1 } = visibleRows(n, ia.view)
  const span = Math.max(1e-9, ia.view.max - ia.view.min)
  const rowH = n ? Math.max(6, plotH / (span + 1)) : rowH0
  const y = (i: number) => top + (i - ia.view.min) * rowH
  const mid = W / 2
  const lab = 58
  const vis = Array.from({ length: Math.max(0, i1 - i0 + 1) }, (_, k) => i0 + k)
  const maxAbs = Math.max(1, ...vis.map(i => Math.abs(ce[i] ?? 0)), ...vis.map(i => Math.abs(pe[i] ?? 0)))
  const half = Math.max(20, mid - lab / 2 - 8 - 56)                 // 56 px kept for the value label at the bar's end
  const w = (v: number | null) => (v == null || !Number.isFinite(v) ? 0 : (Math.abs(v) / maxAbs) * half)
  const markI = mark == null ? null : strikes.findIndex((k, i) => i === strikes.length - 1 || (k <= mark && strikes[i + 1] > mark))
  const fontK = rowH >= 11 ? 10 : 9
  return (
    <div ref={ref} style={CHART_BOX}>
      <svg ref={svgRef} width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={ariaLabel}
        style={{ display: 'block', touchAction: 'none', cursor: 'crosshair' }}>
        <text x={mid + lab / 2 + 4} y={8} fill={CALL_COLOR} fontSize={9} fontFamily={T.mono}>CALLS →</text>
        <text x={mid - lab / 2 - 4} y={8} fill={PUT_COLOR} fontSize={9} fontFamily={T.mono} textAnchor="end">← PUTS</text>
        {ia.zoomed && <text x={W - 8} y={8} fill={T.dim} fontSize={9} fontFamily={T.mono} textAnchor="end">zoomed · double-click = all strikes</text>}
        {vis.map(i => {
          const k = strikes[i]
          const c = ce[i], p = pe[i]
          const neg = (v: number | null) => v != null && v < 0
          const yy = y(i)
          if (yy + rowH < top || yy > top + plotH) return null
          const barH = Math.max(3, rowH - 4)
          return (
            <g key={k} opacity={ia.hover == null || ia.hover === i ? 1 : 0.55}>
              <text x={mid} y={yy + rowH / 2 + 3.5} fill={ia.hover === i ? T.text : T.muted} fontSize={fontK} fontFamily={T.mono} textAnchor="middle">{k.toLocaleString('en-IN')}</text>
              <rect x={mid + lab / 2} y={yy + (rowH - barH) / 2} width={w(c)} height={barH} fill={CALL_COLOR} opacity={neg(c) ? 0.35 : 0.8} />
              <rect x={mid - lab / 2 - w(p)} y={yy + (rowH - barH) / 2} width={w(p)} height={barH} fill={PUT_COLOR} opacity={neg(p) ? 0.35 : 0.8} />
              {c != null && rowH >= 9 && <text x={mid + lab / 2 + w(c) + 3} y={yy + rowH / 2 + 3.5} fill={T.dim} fontSize={9} fontFamily={T.mono}>{fmt(c)}</text>}
              {p != null && rowH >= 9 && <text x={mid - lab / 2 - w(p) - 3} y={yy + rowH / 2 + 3.5} fill={T.dim} fontSize={9} fontFamily={T.mono} textAnchor="end">{fmt(p)}</text>}
              <title>{`${k}: calls ${c == null ? '—' : fmt(c)} · puts ${p == null ? '—' : fmt(p)}`}</title>
            </g>
          )
        })}
        {ia.hover != null && ia.hover >= i0 && ia.hover <= i1 && (
          <line data-sd-crosshair="1" x1={8} x2={W - 8} y1={y(ia.hover) + rowH / 2} y2={y(ia.hover) + rowH / 2}
            stroke={T.muted} strokeDasharray="3 3" opacity={0.8} style={{ pointerEvents: 'none' }} />
        )}
        {markI != null && markI >= i0 && markI <= i1 && <line x1={8} x2={W - 8} y1={y(markI) + rowH} y2={y(markI) + rowH} stroke={T.amber} strokeDasharray="4 3" opacity={0.8} />}
      </svg>
      {!shell && <div data-sd-chart-cursor style={LEGEND_STYLE}>{cursor ?? 'wheel = zoom the strike window · drag = pan · double-click = reset'}</div>}
    </div>
  )
}

/** A small flex column for a chart inside an ExpandableChart shell: notes keep their height, the chart takes the rest. */
export function ChartWithNotes({ chart, above, below }: { chart: ReactNode; above?: ReactNode; below?: ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0, minWidth: 0 }}>
      {above}
      <div style={{ flex: 1, minHeight: 0, minWidth: 0 }}>{chart}</div>
      {below}
    </div>
  )
}

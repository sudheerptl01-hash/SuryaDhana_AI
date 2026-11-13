'use client'

/**
 * InteractiveSeries — the ONE lightweight-charts (4.2.3) wrapper for the terminal (FINAL ROUND W3,
 * charts/PLAN.md §4). Replaces per-page createChart copies over time:
 *
 *   <InteractiveSeries
 *     series={[{ id: 'iv30', label: 'IV30', color: T.amber, type: 'line', axis: 'R',
 *                points: [{ t: '2026-11-12', v: 18.2 }], format: pct1 },
 *              { id: 'px', type: 'candles', points: ohlc } ]}
 *     band={{ lo, hi, color }} markers={[{ t, kind: 'results' }]} unitL="%" unitR=""
 *     linkGroup="omon" height={220} onCrosshair={(t, values) => ...} />
 *
 *  - dynamic-imports LWC in an effect (ssr-safe; the chunk loads only on chart pages, as ChartStudio does);
 *  - 4.x API names ONLY (addLineSeries / addAreaSeries / addCandlestickSeries / addHistogramSeries — the pin
 *    stays 4.2.3; 5.x renamed these to addSeries);
 *  - theme applied once from ./chartTheme (the T tokens) — no per-chart theme objects;
 *  - `band` → the area-pair (translucent hi + panel-masked lo, added first so lines draw on top);
 *  - `markers` → LWC markers on the primary series; a null point → a whitespace gap, never interpolated;
 *  - `linkGroup` shares visible range + crosshair ONLY within one trading calendar (`calendar`, default 'nse' —
 *    the spike's cross-calendar misalignment finding);
 *  - crosshair values go to the surrounding ExpandableChart's legend slot (readable, never tooltip-only) and to
 *    `onCrosshair`; FIT (fitContent) and PNG (takeScreenshot → saveDownload) register on the same shell.
 *  - the TradingView attribution mark stays (licence) — nothing here turns it off.
 *
 * Wheel zoom, drag pan, pinch and kinetic scroll are LWC's own (handleScroll/handleScale from the theme).
 */
import { useEffect, useRef, useState } from 'react'
import type { IChartApi, ISeriesApi, LineStyle, SeriesMarker, SeriesType, Time } from 'lightweight-charts'
import { saveDownload } from '@/lib/platform'
import { BAND_COLOR, BAND_MASK, CANDLE_OPTIONS, MARKER_PALETTE, OVERLAY_COLOR, SERIES_FALLBACK, terminalChartOptions } from './chartTheme'
import { useChartShell } from './ExpandableChart'
import { broadcastCrosshair, broadcastRange, registerLink } from './linkGroups'
import {
  bandAreaOptions, fmtValue, isIntraday, seriesSignature, shapeCandles, shapeLine, timeText, toMarkers,
  type BandSpec, type CandlePoint, type MarkerSpec, type SeriesPoint, type SeriesSpec,
} from './interactiveModel'
import { T } from '@/components/news/format'

export type { BandSpec, CandlePoint, MarkerSpec, SeriesPoint, SeriesSpec } from './interactiveModel'

type AnySeries = ISeriesApi<SeriesType>

export interface InteractiveSeriesProps {
  series: SeriesSpec[]
  /** a shaded band (an IV cone's p25–p75) — rendered as the spike-proven area-pair */
  band?: BandSpec | null
  /** vertical event markers (results / expiry / …) */
  markers?: MarkerSpec[]
  /** unit suffix for the left / right price axis when a series has no `format` of its own */
  unitL?: string
  unitR?: string
  /** panes registering the same group share visible range + crosshair (within one `calendar` only) */
  linkGroup?: string
  /** the trading calendar this pane's times live on (default 'nse'); panes only link within one calendar */
  calendar?: string
  height?: number
  /** the crosshair's time label (null when it leaves) and the value per series id */
  onCrosshair?: (t: string | null, values: Record<string, number | null>) => void
  /** escape hatch: the raw IChartApi once built (price lines, scrubbers — overlay work, not theme changes) */
  onReady?: (chart: IChartApi) => void
  ariaLabel?: string
}

export function InteractiveSeries({ series, band = null, markers = [], unitL = '', unitR = '', linkGroup,
                                    calendar = 'nse', height = 220, onCrosshair, onReady, ariaLabel }: InteractiveSeriesProps) {
  const boxRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const [ready, setReady] = useState(0)
  const shell = useChartShell()

  // latest props for the subscriptions created once in the mount effect
  const live = useRef({ series, band, markers, unitL, unitR, onCrosshair, applying: false, linkId: 0,
                        handles: new Map<string, AnySeries>(), bandHandles: [] as AnySeries[], sig: '', fitted: false })
  live.current.series = series
  live.current.band = band
  live.current.markers = markers
  live.current.unitL = unitL
  live.current.unitR = unitR
  live.current.onCrosshair = onCrosshair

  // ── build the chart once (dynamic import), destroy on unmount ──────────────────────────────────────
  useEffect(() => {
    let disposed = false
    let ro: ResizeObserver | null = null
    let unregister: (() => void) | null = null
    void (async () => {
      const lw = await import('lightweight-charts')
      const el = boxRef.current
      if (disposed || !el) return
      const chart = lw.createChart(el, { ...terminalChartOptions(), width: el.clientWidth || 300, height: el.clientHeight || height })
      chartRef.current = chart
      const s = live.current

      // keep the canvas at the box's size (the ExpandableChart overlay re-measures through this)
      if (typeof ResizeObserver !== 'undefined') {
        ro = new ResizeObserver(() => {
          const b = boxRef.current
          if (b && chartRef.current) chartRef.current.applyOptions({ width: b.clientWidth, height: b.clientHeight })
        })
        ro.observe(el)
      }

      // link group: one visible range + one crosshair per (group, calendar)
      if (linkGroup) {
        const reg = registerLink(linkGroup, calendar, {
          onRange: r => {
            s.applying = true
            try { chart.timeScale().setVisibleLogicalRange(r) } finally { s.applying = false }
          },
          onCrosshair: t => {
            const first = firstDataHandle(s.handles, s.series)
            s.applying = true
            try {
              if (t == null || !first) chart.clearCrosshairPosition()
              else chart.setCrosshairPosition(0, t as Time, first)
            } finally { s.applying = false }
          },
        })
        s.linkId = reg.id
        unregister = reg.unregister
      }

      chart.timeScale().subscribeVisibleLogicalRangeChange(r => {
        if (!r || s.applying || !s.linkId) return
        broadcastRange(s.linkId, { from: r.from, to: r.to })
      })

      chart.subscribeCrosshairMove(p => {
        const time = (p.time as string | number | undefined) ?? null
        if (!s.applying && s.linkId) broadcastCrosshair(s.linkId, time)
        if (time == null) {
          shell?.setLegend(null)
          s.onCrosshair?.(null, {})
          return
        }
        const values: Record<string, number | null> = {}
        const parts: { label: string; text: string; color?: string }[] = []
        for (const spec of s.series) {
          const h = s.handles.get(spec.id)
          const d = h ? (p.seriesData.get(h) as { value?: number; close?: number } | undefined) : undefined
          const v = d == null ? null : d.value ?? d.close ?? null
          values[spec.id] = v
          if (v != null) parts.push({ label: (spec.label ?? spec.id).toUpperCase(), text: fmtValue(v, spec.format), color: spec.color })
        }
        const tLabel = timeText(time)
        s.onCrosshair?.(tLabel, values)
        shell?.setLegend(
          <span>
            <span style={{ color: T.dim }}>{tLabel}</span>
            {parts.map((x, i) => (
              <span key={i}> · {x.label} <b style={{ color: T.bright, fontWeight: 400 }}>{x.text}</b></span>
            ))}
          </span>,
        )
      })

      onReady?.(chart)
      setReady(n => n + 1)
    })()
    return () => {
      disposed = true
      ro?.disconnect()
      unregister?.()
      shell?.setLegend(null)
      live.current.handles.clear()
      live.current.bandHandles = []
      live.current.sig = ''
      live.current.fitted = false
      chartRef.current?.remove()
      chartRef.current = null
    }
    // the chart is built once per mount; linkGroup/calendar changes need a remount (pass a key)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── (re)build series + set data whenever props change ──────────────────────────────────────────────
  useEffect(() => {
    const chart = chartRef.current
    if (!chart || !ready) return
    const s = live.current
    const sig = seriesSignature(series, band)

    if (sig !== s.sig) {
      // shape changed (ids / types / axes / colours / band): rebuild — band areas FIRST so lines draw on top
      for (const h of s.bandHandles) chart.removeSeries(h)
      for (const h of s.handles.values()) chart.removeSeries(h)
      s.bandHandles = []
      s.handles.clear()
      s.sig = sig

      if (band) {
        const axisId = band.axis === 'L' ? 'left' : 'right'
        const pair = bandPairOptions(band.color ?? BAND_COLOR)
        const hi = chart.addAreaSeries({ ...pair.hi, priceScaleId: axisId })
        const lo = chart.addAreaSeries({ ...pair.lo, priceScaleId: axisId })
        s.bandHandles = [hi, lo]
      }
      series.forEach((spec, i) => {
        const color = spec.color ?? SERIES_FALLBACK[i % SERIES_FALLBACK.length]
        const scaleId = spec.overlay ? `overlay-${spec.id}` : spec.axis === 'L' ? 'left' : 'right'
        const priceFormat = spec.format
          ? { type: 'custom' as const, formatter: spec.format, minMove: 0.01 }
          : axisUnit(spec, unitL, unitR)
            ? { type: 'custom' as const, formatter: (v: number) => `${v.toFixed(1)}${axisUnit(spec, unitL, unitR)}`, minMove: 0.01 }
            : undefined
        const common = { priceScaleId: scaleId, ...(priceFormat ? { priceFormat } : null) }
        let h: AnySeries
        const type = spec.type ?? 'line'
        if (type === 'candles') h = chart.addCandlestickSeries({ ...CANDLE_OPTIONS, ...common })
        else if (type === 'histogram') h = chart.addHistogramSeries({ color: spec.color ?? OVERLAY_COLOR, ...common })
        else if (type === 'area') h = chart.addAreaSeries({ lineColor: color, topColor: `${color}33`, bottomColor: `${color}05`, lineWidth: lineW(spec, i), ...common })
        else h = chart.addLineSeries({ color, lineWidth: lineW(spec, i), ...(spec.dashed ? { lineStyle: 2 as LineStyle } : null), ...common })
        if (spec.overlay) chart.priceScale(scaleId).applyOptions({ visible: false, scaleMargins: { top: 0.82, bottom: 0 } })
        s.handles.set(spec.id, h)
      })
      if (series.some(x => x.axis === 'L') || band?.axis === 'L') chart.applyOptions({ leftPriceScale: { visible: true } })
      chart.applyOptions({ timeScale: { timeVisible: isIntraday(series), secondsVisible: false } })
    }

    // data (every run): whitespace rows keep gaps honest
    if (band && s.bandHandles.length === 2) {
      s.bandHandles[0].setData(shapeLine(band.hi) as never[])
      s.bandHandles[1].setData(shapeLine(band.lo) as never[])
    }
    for (const spec of series) {
      const h = s.handles.get(spec.id)
      if (!h) continue
      if ((spec.type ?? 'line') === 'candles') h.setData(shapeCandles(spec.points as CandlePoint[]) as never[])
      else h.setData(shapeLine(spec.points as SeriesPoint[]) as never[])
    }
    const primary = firstDataHandle(s.handles, series)
    if (primary) primary.setMarkers(toMarkers(markers, MARKER_PALETTE) as SeriesMarker<Time>[])
    if (!s.fitted && series.some(x => x.points.length)) {
      chart.timeScale().fitContent()
      s.fitted = true
    }
  }, [ready, series, band, markers, unitL, unitR])

  // ── FIT / PNG on the surrounding shell ──────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!shell || !ready) return
    const fit = () => chartRef.current?.timeScale().fitContent()
    const png = () => {
      const chart = chartRef.current
      if (!chart) return
      const stem = (shell.title ?? 'chart').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'chart'
      chart.takeScreenshot().toBlob(b => { if (b) void saveDownload(b, `${stem}-${new Date().toLocaleDateString('en-CA')}.png`) }, 'image/png')
    }
    return shell.registerActions({ fit, png })
  }, [shell, ready])

  return (
    <div ref={boxRef} role="img" aria-label={ariaLabel ?? 'interactive chart'} data-sd-chart="lwc"
      style={{ width: '100%', height: '100%', minHeight: height, minWidth: 0, position: 'relative' }} />
  )
}

// ── small helpers (component-local; the pure halves live in interactiveModel.ts) ──────────────────────

function lineW(spec: SeriesSpec, i: number): 1 | 2 | 3 | 4 {
  const w = spec.w ?? (i === 0 ? 2 : 1)
  return (w >= 4 ? 4 : w >= 3 ? 3 : w >= 2 ? 2 : 1)
}

function axisUnit(spec: SeriesSpec, unitL: string, unitR: string): string {
  return (spec.axis === 'L' ? unitL : unitR) || ''
}

/** The first non-overlay series with a handle: markers + the linked crosshair anchor live on it. */
function firstDataHandle(handles: Map<string, AnySeries>, series: readonly SeriesSpec[]): AnySeries | null {
  for (const spec of series) {
    if (spec.overlay) continue
    const h = handles.get(spec.id)
    if (h) return h
  }
  return null
}

function bandPairOptions(color: string) {
  return bandAreaOptions(color, BAND_MASK)
}

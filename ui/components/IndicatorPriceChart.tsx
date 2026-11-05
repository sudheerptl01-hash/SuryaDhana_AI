'use client'

/**
 * IndicatorPriceChart — reusable lightweight-charts surface with a fully
 * customizable indicator stack. Used by every price chart in the app.
 *
 *   • Price pane: candles or line + volume + overlay indicators (MAs, Bollinger, VWAP)
 *   • Oscillator pane: a second, time-synced chart appears only when an oscillator
 *     (RSI / MACD / Stochastic / ATR / CCI) is active
 *   • Series are reconciled in place (added / updated / removed) so tweaking a
 *     period or colour never tears the chart down → zero layout shift
 *   • Legend row above the plot with live last-values (never drawn over the lines, C1-trader-ux-17)
 */
import clsx from 'clsx'
import { T } from '@/components/terminal'   // T.muted for axis text (RUP-06: one muted grey)
import { useEffect, useRef } from 'react'
import {
  createChart, ColorType, CrosshairMode, LineStyle,
  type IChartApi, type ISeriesApi, type LogicalRange,
} from 'lightweight-charts'
import {
  type Bar, type IndicatorConfig, type IndicatorLine,
  INDICATOR_DEFS, computeAll,
} from '@/lib/indicators'
import { fmtFixed } from '@/lib/format'

interface Props {
  bars: Bar[]
  chartType: 'line' | 'candle'
  isDark: boolean
  indicators: IndicatorConfig[]
  height?: number
  showVolume?: boolean
  /** Show only the last N bars; earlier bars stay loaded (scroll left) so long averages have their warm-up. */
  visibleBars?: number
  /** Dashed horizontal reference (e.g. the previous close on an intraday chart). */
  refLine?: { price: number; label: string } | null
  /** A comparison line on its own scale, e.g. relative strength vs NIFTY rebased to 100. */
  overlay?: { label: string; color?: string; data: { time: string; value: number }[] } | null
}

export function IndicatorPriceChart({
  bars, chartType, isDark, indicators, height = 320, showVolume = true, visibleBars, refLine, overlay,
}: Props) {
  const mainRef = useRef<HTMLDivElement>(null)
  const oscRef  = useRef<HTMLDivElement>(null)

  const chartRef   = useRef<IChartApi | null>(null)
  const oscChartRef = useRef<IChartApi | null>(null)
  const priceRef   = useRef<ISeriesApi<any> | null>(null)
  const volumeRef  = useRef<ISeriesApi<'Histogram'> | null>(null)
  const priceLines = useRef<Map<string, ISeriesApi<'Line'>>>(new Map())
  const oscLines   = useRef<Map<string, ISeriesApi<'Line'>>>(new Map())
  const syncLock   = useRef(false)
  const refLineRef = useRef<any>(null)
  const overlayRef = useRef<ISeriesApi<'Line'> | null>(null)

  // Latest props for use inside imperative chart callbacks / reconcilers
  const stateRef = useRef({ bars, chartType, indicators, isDark, showVolume, visibleBars, refLine, overlay })
  stateRef.current = { bars, chartType, indicators, isDark, showVolume, visibleBars, refLine, overlay }

  const hasOsc = indicators.some(c => c.visible && INDICATOR_DEFS[c.kind].pane === 'oscillator')

  const palette = {
    // terminal palette (components/news/format.ts T)
    bg:     isDark ? '#05070a' : '#f2f5fa',
    text:   isDark ? T.muted : '#6b7280',
    grid:   isDark ? '#10151f' : '#f1f5f9',
    border: isDark ? '#1a2130' : '#e5e7eb',
    guide:  isDark ? 'rgba(111,122,142,0.35)' : 'rgba(100,116,139,0.30)',
  }

  // ── Build guide-line series (e.g. RSI 30/70) across the full time axis ──────
  function guideLines(barsIn: Bar[], cfgs: IndicatorConfig[]): IndicatorLine[] {
    if (!barsIn.length) return []
    const vals = new Set<number>()
    for (const c of cfgs) {
      if (!c.visible) continue
      const def = INDICATOR_DEFS[c.kind]
      if (def.pane !== 'oscillator' || !def.guides) continue
      for (const g of def.guides) vals.add(g)
    }
    return [...vals].map(v => ({
      id: `guide:${v}`, cfgId: 'guide', label: '', color: palette.guide,
      pane: 'oscillator' as const, lineWidth: 1, lineStyle: LineStyle.Dashed,
      data: barsIn.map(b => ({ time: b.time, value: v })),
    }))
  }

  function reconcile(
    chart: IChartApi, map: Map<string, ISeriesApi<'Line'>>, lines: IndicatorLine[], scaleId: string,
  ) {
    const desired = new Set(lines.map(l => l.id))
    for (const [id, series] of map) {
      if (!desired.has(id)) { try { chart.removeSeries(series) } catch { /* gone */ } map.delete(id) }
    }
    for (const l of lines) {
      let s = map.get(l.id)
      if (!s) {
        s = chart.addLineSeries({
          color: l.color, lineWidth: l.lineWidth as any, lineStyle: l.lineStyle,
          priceScaleId: scaleId, priceLineVisible: false, lastValueVisible: false,
          crosshairMarkerVisible: l.cfgId !== 'guide',
        })
        map.set(l.id, s)
      } else {
        s.applyOptions({ color: l.color, lineWidth: l.lineWidth as any, lineStyle: l.lineStyle })
      }
      s.setData(l.data as any)
    }
  }

  // ── Reconcile data + indicator series (no chart teardown) ──────────────────
  function paint() {
    const { bars, chartType, indicators, showVolume } = stateRef.current
    if (!priceRef.current || !chartRef.current) return
    const t = (d: any) => (typeof d === 'string' ? d.split('T')[0] : d)
    const tbars: Bar[] = bars.map(b => ({ ...b, time: t(b.time) }))
    // intraday bars carry epoch seconds (IST clock as UTC): show hh:mm on the axis
    const timeVisible = typeof tbars[0]?.time === 'number'
    chartRef.current.applyOptions({ timeScale: { timeVisible } })
    oscChartRef.current?.applyOptions({ timeScale: { timeVisible } })
    if (refLineRef.current) { try { priceRef.current.removePriceLine(refLineRef.current) } catch {} refLineRef.current = null }
    const rl = stateRef.current.refLine
    if (rl && Number.isFinite(rl.price)) refLineRef.current = priceRef.current.createPriceLine({
      price: rl.price, color: '#8a94a6', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: rl.label })

    if (chartType === 'candle') {
      priceRef.current.setData(
        tbars.map(b => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })) as any)
    } else {
      priceRef.current.setData(tbars.map(b => ({ time: b.time, value: b.close })) as any)
    }
    if (volumeRef.current) {
      volumeRef.current.setData(showVolume && tbars.some(b => b.volume > 0) ? tbars.map(b => ({
        time: b.time, value: b.volume,
        color: b.close >= b.open ? '#16d98a44' : '#ff4d5e44',
      })) as any : [])
    }

    const { price, oscillator } = computeAll(indicators, tbars)
    reconcile(chartRef.current, priceLines.current, price, 'right')

    // comparison overlay (own scale, upper part of the pane so it doesn't sit on the volume bars)
    const ov = stateRef.current.overlay
    if (ov && ov.data.length) {
      if (!overlayRef.current) {
        overlayRef.current = chartRef.current.addLineSeries({ color: ov.color ?? '#a78bfa', lineWidth: 2, priceScaleId: 'overlay',
          priceLineVisible: false, lastValueVisible: true, lineStyle: LineStyle.Solid })
        chartRef.current.priceScale('overlay').applyOptions({ scaleMargins: { top: 0.08, bottom: 0.3 }, visible: false })
      }
      overlayRef.current.setData(ov.data as any)
    } else if (overlayRef.current) {
      try { chartRef.current.removeSeries(overlayRef.current) } catch { /* gone */ }
      overlayRef.current = null
    }

    if (oscChartRef.current) {
      const all = [...guideLines(tbars, indicators), ...oscillator]
      reconcile(oscChartRef.current, oscLines.current, all, 'right')
    }

    const n = stateRef.current.visibleBars
    if (n && tbars.length > n) {
      const range = { from: tbars.length - n - 0.5, to: tbars.length - 0.5 }
      chartRef.current.timeScale().setVisibleLogicalRange(range)
      oscChartRef.current?.timeScale().setVisibleLogicalRange(range)
    } else {
      chartRef.current.timeScale().fitContent()
      oscChartRef.current?.timeScale().fitContent()
    }
  }

  // ── Main chart lifecycle (recreate on theme / chart-type change) ───────────
  useEffect(() => {
    if (!mainRef.current) return
    const chart = createChart(mainRef.current, {
      layout: { background: { type: ColorType.Solid, color: palette.bg }, textColor: palette.text },
      grid:   { vertLines: { color: palette.grid }, horzLines: { color: palette.grid } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: palette.border },
      timeScale: { borderColor: palette.border, timeVisible: false, secondsVisible: false, visible: !hasOsc },
      width: mainRef.current.clientWidth, height,
    })
    const price: ISeriesApi<any> = chartType === 'candle'
      ? chart.addCandlestickSeries({
          upColor: '#16d98a', downColor: '#ff4d5e',
          borderUpColor: '#16d98a', borderDownColor: '#ff4d5e',
          wickUpColor: '#16d98a', wickDownColor: '#ff4d5e',
        })
      : chart.addLineSeries({ color: '#ffb000', lineWidth: 2 })

    // no axis label / price line: on the overlay scale its '14.91M' tag sat on the price axis ticks (C1-17);
    // the last volume is in the legend row instead
    const volume = chart.addHistogramSeries({
      color: '#c7d2fe', priceFormat: { type: 'volume' }, priceScaleId: 'volume',
      lastValueVisible: false, priceLineVisible: false,
    })
    chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } })

    chartRef.current = chart
    priceRef.current = price
    volumeRef.current = volume
    priceLines.current.clear()

    const ro = new ResizeObserver(e => {
      if (e[0] && chartRef.current) chartRef.current.applyOptions({ width: e[0].contentRect.width })
    })
    ro.observe(mainRef.current)

    paint()

    return () => {
      ro.disconnect()
      try { chart.remove() } catch { /* noop */ }
      chartRef.current = null; priceRef.current = null; volumeRef.current = null; refLineRef.current = null
      overlayRef.current = null
      priceLines.current.clear()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDark, chartType, height])

  // ── Oscillator pane lifecycle + time-sync (only when an oscillator is active)
  useEffect(() => {
    if (!hasOsc || !oscRef.current || !chartRef.current) {
      if (oscChartRef.current) { try { oscChartRef.current.remove() } catch { /* noop */ } }
      oscChartRef.current = null; oscLines.current.clear()
      chartRef.current?.applyOptions({ timeScale: { visible: true } })
      return
    }
    chartRef.current.applyOptions({ timeScale: { visible: false } })

    const osc = createChart(oscRef.current, {
      layout: { background: { type: ColorType.Solid, color: palette.bg }, textColor: palette.text },
      grid:   { vertLines: { color: palette.grid }, horzLines: { color: palette.grid } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: palette.border },
      timeScale: { borderColor: palette.border, timeVisible: false, secondsVisible: false },
      width: oscRef.current.clientWidth, height: 130,
    })
    oscChartRef.current = osc
    oscLines.current.clear()

    const main = chartRef.current
    const fromMain = (r: LogicalRange | null) => {
      if (syncLock.current || !r) return
      syncLock.current = true; osc.timeScale().setVisibleLogicalRange(r); syncLock.current = false
    }
    const fromOsc = (r: LogicalRange | null) => {
      if (syncLock.current || !r) return
      syncLock.current = true; main.timeScale().setVisibleLogicalRange(r); syncLock.current = false
    }
    main.timeScale().subscribeVisibleLogicalRangeChange(fromMain)
    osc.timeScale().subscribeVisibleLogicalRangeChange(fromOsc)

    const ro = new ResizeObserver(e => {
      if (e[0] && oscChartRef.current) oscChartRef.current.applyOptions({ width: e[0].contentRect.width })
    })
    ro.observe(oscRef.current)

    paint()

    return () => {
      ro.disconnect()
      try { main.timeScale().unsubscribeVisibleLogicalRangeChange(fromMain) } catch { /* noop */ }
      try { osc.remove() } catch { /* noop */ }
      oscChartRef.current = null; oscLines.current.clear()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDark, chartType, hasOsc, height])

  // ── Repaint on data / indicator changes (in place, no teardown) ────────────
  useEffect(() => { paint() /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [bars, indicators, refLine?.price, overlay])

  // ── Legend (one entry per indicator, primary line, live last value) ────────
  const { price: pLines, oscillator: oLines } = computeAll(indicators, bars)
  const legend = [...pLines, ...oLines].filter(l => l.cfgId !== 'guide')
  const seen = new Set<string>()
  const legendEntries = legend.filter(l => (seen.has(l.cfgId) ? false : (seen.add(l.cfgId), true)))
  const lastBar = bars.length ? bars[bars.length - 1] : null
  const lastVol = showVolume && lastBar && lastBar.volume > 0 ? lastBar.volume : null

  return (
    <div className={clsx('rounded-xl overflow-hidden border', isDark ? 'border-slate-700' : 'border-gray-200')}>
      <div className="relative">
        {/* RUP-08: the legend row is always there and one line high (it scrolls sideways when crowded), so the
            price pane never jumps down when the bars arrive or an indicator is added */}
        <div data-testid="chart-legend"
               className={clsx('flex flex-nowrap items-center gap-x-3 px-2 py-1 border-b whitespace-nowrap overflow-x-auto overflow-y-hidden min-h-[23px] h-[23px]',
                               isDark ? 'border-slate-800' : 'border-gray-100')}>
            {overlay && overlay.data.length > 0 && (
              <div className="flex flex-shrink-0 items-center gap-1.5 text-[10px] font-mono font-bold" style={{ color: overlay.color ?? '#a78bfa' }}>
                <span className="w-2.5 h-[2px]" style={{ background: overlay.color ?? '#a78bfa' }} />
                {overlay.label} <span className="opacity-80">{fmtFixed(overlay.data[overlay.data.length - 1].value, 1)}</span>
              </div>)}
            {legendEntries.map(l => {
              const last = l.data.length ? l.data[l.data.length - 1].value : null
              return (
                <div key={l.cfgId} className="flex flex-shrink-0 items-center gap-1.5 text-[10px] font-mono font-bold"
                  style={{ color: l.color }}>
                  <span className="w-2.5 h-[2px]" style={{ background: l.color }} />
                  {l.label.replace(/ [↑↓].*$/, '')}
                  {last !== null && <span className="opacity-80">{fmtFixed(last, 2)}</span>}
                </div>
              )
            })}
            {lastVol != null && (
              <div className="flex flex-shrink-0 items-center gap-1.5 text-[10px] font-mono font-bold" style={{ color: '#c7d2fe' }}>
                <span className="w-2.5 h-[6px]" style={{ background: '#c7d2fe', opacity: 0.6 }} />
                VOL <span className="opacity-80">{fmtVolume(lastVol)}</span>
              </div>)}
        </div>
        <div ref={mainRef} className="w-full" />
      </div>
      <div ref={oscRef} className={clsx('w-full', hasOsc ? 'block border-t' : 'hidden',
        isDark ? 'border-slate-800' : 'border-gray-100')} />
    </div>
  )
}

/** Share volume in Indian units, one 'cr' / 'L' casing with the rest of the terminal. */
function fmtVolume(v: number): string {
  if (v >= 1e7) return `${(v / 1e7).toFixed(2)} cr`
  if (v >= 1e5) return `${(v / 1e5).toFixed(2)} L`
  return Math.round(v).toLocaleString('en-IN')
}

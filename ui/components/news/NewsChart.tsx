'use client'

/**
 * NewsChart — terminal price chart (lightweight-charts, TradingView's open-source
 * library) on Yahoo OHLCV: candles + volume + SMA 20/50/200 overlays, with a
 * time-synced RSI(14) pane. TradingViewEmbed renders TradingView's official
 * widget for the same symbol as an alternate view.
 */
import { Z } from '@/lib/z'
import { useEffect, useRef } from 'react'
import {
  createChart, ColorType, CrosshairMode, LineStyle,
  type IChartApi, type ISeriesApi, type UTCTimestamp,
} from 'lightweight-charts'
import type { ChartData, Point } from './types'
import { T } from './format'

export interface Overlays { sma20: boolean; sma50: boolean; sma200: boolean; rsi: boolean }

const SMA_COLORS = { sma20: T.cyan, sma50: T.amber, sma200: T.violet } as const

export function NewsChart({ data, overlays, height = 420 }: {
  data: ChartData
  overlays: Overlays
  height?: number
}) {
  const mainEl = useRef<HTMLDivElement>(null)
  const rsiEl = useRef<HTMLDivElement>(null)
  const charts = useRef<IChartApi[]>([])

  useEffect(() => {
    if (!mainEl.current) return
    // Shift to exchange-local time so a 09:15 IST open reads 09:15, not 03:45 UTC.
    const off = data.quote?.gmtoffset ?? 0
    const t = (x: number) => (x + off) as UTCTimestamp
    const rsiH = overlays.rsi ? Math.round(height * 0.24) : 0
    const common = {
      layout: { background: { type: ColorType.Solid, color: T.panel }, textColor: T.muted,
                fontFamily: T.mono, fontSize: 11 },
      grid: { vertLines: { color: '#111724' }, horzLines: { color: '#111724' } },
      crosshair: { mode: CrosshairMode.Normal,
                   vertLine: { color: T.amberDim, labelBackgroundColor: T.amberDim },
                   horzLine: { color: T.amberDim, labelBackgroundColor: T.amberDim } },
      rightPriceScale: { borderColor: T.border },
      timeScale: { borderColor: T.border, timeVisible: data.intraday, secondsVisible: false },
      width: mainEl.current.clientWidth,
    }

    const main = createChart(mainEl.current, { ...common, height: height - rsiH,
      timeScale: { ...common.timeScale, visible: !overlays.rsi } })
    const candles = main.addCandlestickSeries({
      upColor: T.green, downColor: T.red, borderUpColor: T.green, borderDownColor: T.red,
      wickUpColor: T.green, wickDownColor: T.red,
    })
    candles.setData(data.candles.map(c => ({ time: t(c.time), open: c.open, high: c.high, low: c.low, close: c.close })))

    const vol = main.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: 'vol' })
    main.priceScale('vol').applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } })
    vol.setData(data.candles.map(c => ({
      time: t(c.time), value: c.volume,
      color: c.close >= c.open ? 'rgba(22,217,138,0.28)' : 'rgba(255,77,94,0.28)',
    })))

    const line = (pts: Point[], color: string) => {
      const s = main.addLineSeries({ color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
                                     crosshairMarkerVisible: false })
      s.setData(pts.map(p => ({ time: t(p.time), value: p.value })))
    }
    ;(['sma20', 'sma50', 'sma200'] as const).forEach(k => {
      if (overlays[k] && data[k].length) line(data[k], SMA_COLORS[k])
    })
    main.timeScale().fitContent()
    charts.current = [main]

    let rsiChart: IChartApi | null = null
    if (overlays.rsi && rsiEl.current) {
      rsiChart = createChart(rsiEl.current, { ...common, height: rsiH })
      const r: ISeriesApi<'Line'> = rsiChart.addLineSeries({ color: T.amber, lineWidth: 1, priceLineVisible: false })
      r.setData(data.rsi.map(p => ({ time: t(p.time), value: p.value })))
      ;[70, 30].forEach(level => r.createPriceLine({
        price: level, color: level === 70 ? 'rgba(255,77,94,0.5)' : 'rgba(22,217,138,0.5)',
        lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: '',
      }))
      rsiChart.timeScale().fitContent()
      // keep both panes on the same visible range
      main.timeScale().subscribeVisibleLogicalRangeChange(range => {
        if (range) rsiChart?.timeScale().setVisibleLogicalRange(range)
      })
      rsiChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
        if (range) main.timeScale().setVisibleLogicalRange(range)
      })
      charts.current.push(rsiChart)
    }

    const ro = new ResizeObserver(entries => {
      const w = entries[0]?.contentRect.width
      if (w) charts.current.forEach(c => c.applyOptions({ width: w }))
    })
    ro.observe(mainEl.current)
    return () => {
      ro.disconnect()
      charts.current.forEach(c => { try { c.remove() } catch { /* already removed */ } })
      charts.current = []
    }
  }, [data, overlays, height])

  return (
    <div style={{ height }}>
      <div ref={mainEl} />
      {overlays.rsi && (
        <div style={{ position: 'relative' }}>
          <span style={{ position: 'absolute', left: 8, top: 4, zIndex: Z.raised, fontFamily: T.mono,
                         fontSize: 10, color: T.amber, letterSpacing: 1 }}>RSI 14</span>
          <div ref={rsiEl} />
        </div>
      )}
    </div>
  )
}

/**
 * Third-party frame sandbox (C2-security-05 item 4): the widget keeps scripts, its own origin's storage, forms and
 * "open on TradingView" popups (escaping the sandbox so the opened tab is a normal page), but it can never navigate
 * the terminal's window (no allow-top-navigation) or start a download (no allow-downloads), so a compromised
 * widget script cannot drop a file through the desktop app's download handler.
 */
export const TRADINGVIEW_SANDBOX = 'allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox allow-forms'

/** TradingView's official embeddable chart (same symbol, TradingView's own data feed). */
export function TradingViewEmbed({ tvSymbol, height = 420 }: { tvSymbol: string; height?: number }) {
  const params = new URLSearchParams({
    symbol: tvSymbol, interval: 'D', theme: 'dark', style: '1', locale: 'en',
    toolbarbg: '0a0d13', hidesidetoolbar: '0', symboledit: '1', saveimage: '1',
    withdateranges: '1', timezone: 'exchange', studies: '[]',
  })
  return (
    <iframe
      key={tvSymbol}
      title={`TradingView ${tvSymbol}`}
      src={`https://s.tradingview.com/widgetembed/?${params.toString()}`}
      sandbox={TRADINGVIEW_SANDBOX}
      style={{ width: '100%', height, border: 0, background: T.panel }}
      allowFullScreen
    />
  )
}

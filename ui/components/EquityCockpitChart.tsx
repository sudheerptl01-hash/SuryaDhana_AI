'use client'

import { useEffect, useRef, useState } from 'react'
import { createChart, ColorType, CrosshairMode, LineStyle, type IChartApi } from 'lightweight-charts'
import type { EquityPoint } from '@/lib/backtest'

/**
 * Interactive equity cockpit: compounded NAV (amber) vs benchmark (slate dashed)
 * on the main scale, with a shaded drawdown profile on a bottom sub-scale.
 * lightweight-charts gives free zoom/pan; a crosshair legend shows the values on
 * the hovered day.
 */
export function EquityCockpitChart({ data }: { data: EquityPoint[] }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const [legend, setLegend] = useState<{ date: string; nav: number; bench: number; dd: number } | null>(null)

  useEffect(() => {
    if (!containerRef.current || !data.length) return
    const el = containerRef.current

    const chart = createChart(el, {
      layout: { background: { type: ColorType.Solid, color: '#0f172a' }, textColor: '#94a3b8', fontFamily: 'JetBrains Mono, monospace' },
      grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#334155', scaleMargins: { top: 0.08, bottom: 0.32 } },
      timeScale: { borderColor: '#334155', timeVisible: false, rightOffset: 4 },
      width: el.clientWidth,
      height: 320,
    })

    const navSeries = chart.addAreaSeries({
      lineColor: '#f59e0b', topColor: 'rgba(245,158,11,0.28)', bottomColor: 'rgba(245,158,11,0.02)',
      lineWidth: 2, priceFormat: { type: 'price', precision: 0, minMove: 1 },
    })
    const benchSeries = chart.addLineSeries({
      color: '#64748b', lineWidth: 1, lineStyle: LineStyle.Dashed,
      priceFormat: { type: 'price', precision: 0, minMove: 1 },
    })
    const ddSeries = chart.addAreaSeries({
      lineColor: '#ef4444', topColor: 'rgba(239,68,68,0.05)', bottomColor: 'rgba(239,68,68,0.45)',
      lineWidth: 1, priceScaleId: 'dd', priceFormat: { type: 'price', precision: 1, minMove: 0.1 },
    })
    chart.priceScale('dd').applyOptions({ scaleMargins: { top: 0.72, bottom: 0 }, borderColor: '#334155' })

    const toTime = (d: string) => d.slice(0, 10)
    navSeries.setData(data.map(d => ({ time: toTime(d.date) as any, value: d.nav })))
    benchSeries.setData(data.map(d => ({ time: toTime(d.date) as any, value: d.benchmark_nav })))
    ddSeries.setData(data.map(d => ({ time: toTime(d.date) as any, value: d.drawdown_pct })))
    chart.timeScale().fitContent()
    chartRef.current = chart

    const last = data[data.length - 1]
    setLegend({ date: last.date, nav: last.nav, bench: last.benchmark_nav, dd: last.drawdown_pct })

    chart.subscribeCrosshairMove(param => {
      if (!param.time) return
      const navV = param.seriesData.get(navSeries) as any
      const benchV = param.seriesData.get(benchSeries) as any
      const ddV = param.seriesData.get(ddSeries) as any
      if (navV) setLegend({ date: String(param.time), nav: navV.value, bench: benchV?.value ?? 0, dd: ddV?.value ?? 0 })
    })

    const ro = new ResizeObserver(entries => {
      if (entries[0] && chartRef.current) chartRef.current.applyOptions({ width: entries[0].contentRect.width })
    })
    ro.observe(el)
    return () => { ro.disconnect(); chart.remove(); chartRef.current = null }
  }, [data])

  const fmt = (n: number) => '₹' + n.toLocaleString('en-IN', { maximumFractionDigits: 0 })

  return (
    <div className="relative w-full">
      {legend && (
        <div className="absolute left-2 top-2 z-10 rounded-md bg-slate-900/80 backdrop-blur px-3 py-2 text-[11px] font-mono border border-slate-700/60 pointer-events-none">
          <span className="text-slate-500">{legend.date}</span>
          <span className="ml-3 text-amber-400">NAV {fmt(legend.nav)}</span>
          <span className="ml-3 text-slate-400">BMK {fmt(legend.bench)}</span>
          <span className={`ml-3 ${legend.dd < 0 ? 'text-rose-400' : 'text-emerald-400'}`}>DD {legend.dd.toFixed(1)}%</span>
        </div>
      )}
      <div ref={containerRef} className="w-full rounded-xl overflow-hidden border border-slate-800" />
    </div>
  )
}

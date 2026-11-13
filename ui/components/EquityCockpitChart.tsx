'use client'

import { useEffect, useRef, useState } from 'react'
import { createChart, ColorType, CrosshairMode, LineStyle, type IChartApi } from 'lightweight-charts'
import type { EquityPoint } from '@/lib/backtest'
import { ExpandableChart, useChartShell } from '@/components/terminal/ExpandableChart'
import { saveDownload } from '@/lib/platform'

/**
 * Interactive equity cockpit: compounded NAV (amber) vs benchmark (slate dashed)
 * on the main scale, with a shaded drawdown profile on a bottom sub-scale.
 * lightweight-charts gives free zoom/pan; a crosshair legend shows the values on
 * the hovered day. FINAL ROUND C7: sits in the ExpandableChart shell (FIT · PNG ⤓ · ⛶
 * expand), registering its FIT/PNG through the shell context like InteractiveSeries.
 */
function CockpitInner({ data, width, height }: { data: EquityPoint[]; width: number; height: number }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const shell = useChartShell()
  const [legend, setLegend] = useState<{ date: string; nav: number; bench: number; dd: number } | null>(null)

  useEffect(() => {
    if (!containerRef.current || !data.length) return
    const el = containerRef.current

    const chart = createChart(el, {
      layout: { background: { type: ColorType.Solid, color: '#05070a' }, textColor: '#8a94a6', fontFamily: 'JetBrains Mono, monospace' },
      grid: { vertLines: { color: '#1a2130' }, horzLines: { color: '#1a2130' } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#2a3448', scaleMargins: { top: 0.08, bottom: 0.32 } },
      timeScale: { borderColor: '#2a3448', timeVisible: false, rightOffset: 4 },
      width: el.clientWidth,
      height: el.clientHeight || 320,
    })

    const navSeries = chart.addAreaSeries({
      lineColor: '#ffb000', topColor: 'rgba(245,158,11,0.28)', bottomColor: 'rgba(245,158,11,0.02)',
      lineWidth: 2, priceFormat: { type: 'price', precision: 0, minMove: 1 },
    })
    const benchSeries = chart.addLineSeries({
      color: '#6f7a8e', lineWidth: 1, lineStyle: LineStyle.Dashed,
      priceFormat: { type: 'price', precision: 0, minMove: 1 },
    })
    const ddSeries = chart.addAreaSeries({
      lineColor: '#ef4444', topColor: 'rgba(239,68,68,0.05)', bottomColor: 'rgba(239,68,68,0.45)',
      lineWidth: 1, priceScaleId: 'dd', priceFormat: { type: 'price', precision: 1, minMove: 0.1 },
    })
    chart.priceScale('dd').applyOptions({ scaleMargins: { top: 0.72, bottom: 0 }, borderColor: '#2a3448' })

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

    // FIT / PNG through the shell header (no-ops when mounted bare)
    const unregister = shell?.registerActions({
      fit: () => chart.timeScale().fitContent(),
      png: () => {
        chart.takeScreenshot().toBlob(b => { if (b) void saveDownload(b, `equity-curve-${new Date().toLocaleDateString('en-CA')}.png`) }, 'image/png')
      },
    })
    return () => { unregister?.(); chart.remove(); chartRef.current = null }
  }, [data, shell])

  // the shell measures the box (collapsed height, or the overlay when expanded)
  useEffect(() => {
    if (chartRef.current && width > 0) chartRef.current.applyOptions({ width, height: Math.max(200, height) })
  }, [width, height])

  const fmt = (n: number) => '₹' + n.toLocaleString('en-IN', { maximumFractionDigits: 0 })

  return (
    <div className="relative w-full h-full">
      {legend && (
        <div className="absolute left-2 top-2 z-10 rounded-md bg-slate-900/80 backdrop-blur px-3 py-2 text-[11px] font-mono border border-slate-700/60 pointer-events-none">
          <span className="text-slate-500">{legend.date}</span>
          <span className="ml-3 text-amber-400">NAV {fmt(legend.nav)}</span>
          <span className="ml-3 text-slate-400">BMK {fmt(legend.bench)}</span>
          <span className={`ml-3 ${legend.dd < 0 ? 'text-rose-400' : 'text-emerald-400'}`}>DD {legend.dd.toFixed(1)}%</span>
        </div>
      )}
      <div ref={containerRef} className="w-full h-full overflow-hidden" />
    </div>
  )
}

export function EquityCockpitChart({ data }: { data: EquityPoint[] }) {
  return (
    <ExpandableChart title="Compounded equity" badges={[{ label: 'arithmetic', note: 'NAV, benchmark NAV and drawdown compounded from the backtest fills.' }]}
      legend="NAV (amber) · benchmark (dashed) · drawdown (lower) — hover for values" height={320}>
      {({ width, height }) => <CockpitInner data={data} width={width} height={height} />}
    </ExpandableChart>
  )
}

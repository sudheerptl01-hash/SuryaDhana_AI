'use client'

import { Z } from '@/lib/z'
import { fmtSigned, sessionDayLabel } from '@/lib/format'   // signed numbers with U+2212 (C1-trader-ux-18)
import { apiError } from '@/lib/errors'
/**
 * Market internals through the session: NIFTY 500 advances − declines (bars) against the % move of NIFTY 50,
 * Midcap 150 and Smallcap 250 (lines). Sampled every 2 min by the master-controller's internals_sample job from
 * NSE's allIndices (data/nse_archive/internals). Answers "is this rally broad or a few heavyweights?".
 */
import { useEffect, useRef, useState } from 'react'
import { createChart, ColorType, CrosshairMode, type IChartApi, type ISeriesApi } from 'lightweight-charts'
import { getMarketInternals, type InternalsSample, type MarketInternals as Data } from '@/lib/api'
import { T, fmtPct, tone } from '@/components/terminal'

const LINES: [keyof InternalsSample, string, string][] = [['n50_pct', 'NIFTY 50', T.amber], ['mid_pct', 'MID 150', '#38bdf8'], ['small_pct', 'SMALL 250', '#c084fc']]

/** '13-Oct-2026 11:34' → epoch seconds with the IST clock as UTC (lightweight-charts shows it as-is). */
function nseTime(ts: string): number | null {
  const m = /^(\d{2})-(\w{3})-(\d{4}) (\d{2}):(\d{2})/.exec(ts)
  if (!m) return null
  const mon = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'].indexOf(m[2])
  return mon < 0 ? null : Date.UTC(+m[3], mon, +m[1], +m[4], +m[5]) / 1000
}

export function MarketInternals({ height = 200 }: { height?: number }) {
  const [data, setData] = useState<Data | null>(null)
  const [error, setError] = useState<string | null>(null)
  const box = useRef<HTMLDivElement>(null)
  const chart = useRef<IChartApi | null>(null)
  const bars = useRef<ISeriesApi<'Histogram'> | null>(null)
  const lines = useRef<ISeriesApi<'Line'>[]>([])

  useEffect(() => {
    let alive = true
    const load = () => getMarketInternals().then(r => { if (alive) { setData(r.data); setError(null) } })
      .catch(e => { if (alive) setError(apiError(e, 'unavailable')) })
    load(); const iv = setInterval(load, 120_000)
    return () => { alive = false; clearInterval(iv) }
  }, [])

  useEffect(() => {
    if (!box.current) return
    const c = createChart(box.current, {
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: T.muted, fontFamily: T.mono, fontSize: 10 },
      grid: { vertLines: { visible: false }, horzLines: { color: T.border } },
      crosshair: { mode: CrosshairMode.Normal },
      leftPriceScale: { visible: true, borderColor: T.borderHi, scaleMargins: { top: 0.1, bottom: 0.05 } },
      rightPriceScale: { borderColor: T.borderHi, scaleMargins: { top: 0.1, bottom: 0.05 } },
      timeScale: { borderColor: T.borderHi, timeVisible: true, secondsVisible: false },
      handleScroll: false, handleScale: false, width: box.current.clientWidth, height,
    })
    bars.current = c.addHistogramSeries({ priceScaleId: 'left', priceFormat: { type: 'volume' }, priceLineVisible: false, lastValueVisible: true })
    lines.current = LINES.map(([, , color]) => c.addLineSeries({ color, lineWidth: 2, priceLineVisible: false,
      priceFormat: { type: 'custom', formatter: (v: number) => `${fmtSigned(v, 2)}%` } }))
    chart.current = c
    const ro = new ResizeObserver(e => { if (e[0]) c.applyOptions({ width: e[0].contentRect.width }) })
    ro.observe(box.current)
    return () => { ro.disconnect(); c.remove(); chart.current = null; bars.current = null; lines.current = [] }
  }, [height])

  useEffect(() => {
    if (!chart.current || !bars.current || !data) return
    const rows = data.rows.map(r => ({ r, t: nseTime(r.nse_ts) })).filter((x): x is { r: InternalsSample; t: number } => x.t != null)
    const seen = new Set<number>(), uniq = rows.filter(x => !seen.has(x.t) && seen.add(x.t))
    bars.current.setData(uniq.filter(x => x.r.n500_adv != null && x.r.n500_dec != null).map(({ r, t }) => {
      const net = r.n500_adv! - r.n500_dec!
      return { time: t as any, value: net, color: net >= 0 ? 'rgba(22,217,138,0.55)' : 'rgba(255,77,94,0.55)' }
    }))
    LINES.forEach(([k], i) => lines.current[i]?.setData(uniq.filter(x => x.r[k] != null).map(({ r, t }) => ({ time: t as any, value: r[k] as number }))))
    chart.current.timeScale().fitContent()
  }, [data])

  const s = data?.summary, last = data?.rows[data.rows.length - 1]
  return (
    <div>
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'baseline', fontFamily: T.mono, fontSize: 11, marginBottom: 4 }}>
        {s?.n500_adv != null && <span>NIFTY 500 <span style={{ color: T.green }}>{s.n500_adv} up</span> / <span style={{ color: T.red }}>{s.n500_dec} down</span>
          <span style={{ color: T.dim }}> · A/D {s.ad_ratio?.toFixed(2) ?? '—'}</span></span>}
        {LINES.map(([k, label, color]) => last?.[k] != null &&
          <span key={label}><span style={{ color }}>■</span> {label} <span style={{ color: tone(last[k] as number) }}>{fmtPct(last[k] as number, 2)}</span></span>)}
        {s?.divergence && <span style={{ color: T.amber, fontWeight: 700 }}>⚠ {s.divergence}</span>}
        {/* C1-13: the sampled session's date when it is not today (weekend, holiday, before the open); U+2212 minus */}
        {s?.net_best != null && s.samples > 1 && <span style={{ color: T.dim }}>net range {sessionDayLabel(data?.day)} {fmtSigned(s.net_worst, 0)} … +{Math.max(0, s.net_best)}</span>}
      </div>
      <div ref={box} style={{ width: '100%', height, position: 'relative' }}>
        {(!data || data.rows.length < 2) && <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, color: T.dim, zIndex: Z.raised, textAlign: 'center', padding: 12 }}>
          {error ? `Internals unavailable: ${error}` : !data ? 'Loading…' : 'Sampling every 2 minutes in session (09:15–15:30): the line fills in as the day goes on.'}</div>}
      </div>
      <div style={{ fontSize: 10, color: T.dim, marginTop: 2 }}>
        bars: NIFTY 500 advances − declines (left) · lines: % move (right) · NSE, sampled every 2 min{data?.day ? ` · ${data.day}` : ''}{s?.samples ? ` · ${s.samples} samples since ${s.first?.slice(12)}` : ''}
      </div>
    </div>
  )
}

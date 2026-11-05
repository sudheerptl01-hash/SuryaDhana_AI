'use client'

import { Z } from '@/lib/z'
import { apiError } from '@/lib/errors'
/**
 * Intraday index chart (Bloomberg GIP-style): today's path of an NSE index against its previous close,
 * green above / red below the close. Source: NSE's chart feed (≈1 min delayed) via /api/market/index-intraday;
 * refreshes every 60 s while NSE is open. Live program (reports/live_nse): the headline level and the chart's last
 * point come from the live NSE quote service (the Breeze websocket index tick, every 3 s) while the session runs; the
 * 1-min path stays NSE's chart feed. `onSource` hands the panel its own chip (the live row's, else the feed's stamp).
 */
import { useEffect, useRef, useState } from 'react'
import { createChart, ColorType, CrosshairMode, LineStyle, type IChartApi, type IPriceLine, type ISeriesApi } from 'lightweight-charts'
import { getIndexIntraday, type IndexIntraday as Data } from '@/lib/api'
import { Chip, T, fmtIdx, fmtPct, type SourceInfo } from '@/components/terminal'
import { useLiveQuotes } from '@/lib/liveQuotes'
import { nseDelayedSource } from '@/components/liveModel'
import { useMarketOpen } from '@/components/shell/useFeed'
import { PRICE_DP } from '@/lib/format'

/** decimals on the chart's price axis and price-line tags: NSE prints index levels (and VIX) with 2 (C1-08) */
export const INDEX_PRICE_PRECISION = PRICE_DP
const INDICES: [string, string][] = [['NIFTY 50', 'NIFTY'], ['NIFTY BANK', 'BANK'], ['NIFTY MIDCAP 150', 'MID150'], ['NIFTY IT', 'IT'], ['INDIA VIX', 'VIX']]

function marketOpenIST(): boolean {
  const ist = new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }))
  const m = ist.getHours() * 60 + ist.getMinutes()
  return ist.getDay() >= 1 && ist.getDay() <= 5 && m >= 9 * 60 && m <= 15 * 60 + 35
}

/** IST wall-clock minute of an ISO time as the chart's epoch seconds (NSE's chart encodes IST wall-clock as UTC). */
export function istMinuteTs(iso: string | null | undefined): number | null {
  const t = iso ? Date.parse(iso) : NaN
  return Number.isFinite(t) ? Math.floor((t + 330 * 60_000) / 60_000) * 60 : null
}

export function IndexIntraday({ height = 200, initial = 'NIFTY 50', onSource }: { height?: number; initial?: string; onSource?: (s: SourceInfo | null) => void }) {
  const [index, setIndex] = useState(initial)
  const [data, setData] = useState<Data | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [hover, setHover] = useState<{ time: string; value: number } | null>(null)
  const box = useRef<HTMLDivElement>(null)
  const chart = useRef<IChartApi | null>(null)
  const series = useRef<ISeriesApi<'Baseline'> | null>(null)
  const prevLine = useRef<IPriceLine | null>(null)

  useEffect(() => {
    let alive = true
    const load = () => getIndexIntraday(index).then(r => { if (alive) { setData(r.data); setError(null) } })
      .catch(e => { if (alive) setError(apiError(e, 'unavailable')) })
    setData(null); load()
    const iv = setInterval(() => { if (marketOpenIST()) load() }, 60_000)
    return () => { alive = false; clearInterval(iv) }
  }, [index])

  useEffect(() => {
    if (!box.current) return
    const c = createChart(box.current, {
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: T.muted, fontFamily: T.mono, fontSize: 10 },
      grid: { vertLines: { visible: false }, horzLines: { color: T.border } },
      crosshair: { mode: CrosshairMode.Magnet },
      rightPriceScale: { borderColor: T.borderHi, scaleMargins: { top: 0.1, bottom: 0.08 } },
      timeScale: { borderColor: T.borderHi, timeVisible: true, secondsVisible: false, fixLeftEdge: true, fixRightEdge: true },
      handleScroll: false, handleScale: false,
      width: box.current.clientWidth, height,
    })
    const s = c.addBaselineSeries({
      topLineColor: T.green, topFillColor1: 'rgba(22,217,138,0.22)', topFillColor2: 'rgba(22,217,138,0.02)',
      bottomLineColor: T.red, bottomFillColor1: 'rgba(255,77,94,0.02)', bottomFillColor2: 'rgba(255,77,94,0.22)',
      lineWidth: 2, priceLineVisible: false,
    })
    c.subscribeCrosshairMove(p => {
      const v = p.time != null ? (p.seriesData.get(s) as { value?: number } | undefined) : undefined
      if (v?.value == null || typeof p.time !== 'number') { setHover(null); return }
      const d = new Date(p.time * 1000)
      setHover({ time: `${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')}`, value: v.value })
    })
    chart.current = c; series.current = s
    const ro = new ResizeObserver(e => { if (e[0]) c.applyOptions({ width: e[0].contentRect.width }) })
    ro.observe(box.current)
    return () => { ro.disconnect(); c.remove(); chart.current = null; series.current = null; prevLine.current = null }
  }, [height])

  useEffect(() => {
    const s = series.current
    if (!s || !chart.current) return
    const rows = data?.rows ?? []
    const prev = data?.previous_close ?? rows[0]?.open
    // C1-08 / CT-05: every index level (and VIX) at NSE's 2 decimals, axis and the 'prev' tag included (precision 1
    // printed the 22,687.65 previous close as 22687.5). minMove stays 0.01: index values move in 0.01, not a 0.05 tick
    s.applyOptions({ baseValue: { type: 'price', price: prev ?? 0 }, priceFormat: { type: 'price', precision: INDEX_PRICE_PRECISION, minMove: 0.01 } })
    s.setData(rows.map(r => ({ time: r.ts as any, value: r.close })))
    if (prevLine.current) s.removePriceLine(prevLine.current)
    prevLine.current = prev ? s.createPriceLine({ price: prev, color: T.dim, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: 'prev' }) : null
    chart.current.timeScale().fitContent()
  }, [data, index])

  // the live tip: the index's live row while the session runs (a closed row is the close the chart already ends on)
  const live = useLiveQuotes([index], { intervalMs: 3_000 })
  const lq = live.quotes[index.toUpperCase()]
  const tip = lq && lq.price != null && (lq.state === 'live' || lq.state === 'delayed') ? lq : null
  const tipTs = tip ? istMinuteTs(tip.ltt) : null
  useEffect(() => {
    const s = series.current
    const rws = data?.rows ?? []
    if (!s || !tip || tipTs == null || !rws.length || tipTs < rws[rws.length - 1].ts) return
    try { s.update({ time: tipTs as any, value: tip.price as number }) } catch { /* an out-of-order point: keep the feed's path */ }
  }, [tip?.price, tipTs, data])  // eslint-disable-line react-hooks/exhaustive-deps
  const marketOpen = useMarketOpen()
  const lastRow = data?.rows?.length ? data.rows[data.rows.length - 1] : null
  const feedStamp = lastRow ? `${new Date(lastRow.ts * 1000).toISOString().slice(0, 19)}+05:30` : null
  const src: SourceInfo | null = tip && live.source ? { ...live.source, hint: `last point: live quote${live.source.hint ? ` (${live.source.hint})` : ''}; 1-min path: NSE chart feed` }
    : data ? nseDelayedSource(feedStamp, { marketOpen, now: Date.now(), hint: 'NSE chart feed, 1-min points' }) : null
  const srcKey = src ? `${src.state}|${src.source}|${Math.round((src.ageS ?? 0) / 5)}|${src.asOf}` : ''
  useEffect(() => { onSource?.(src) }, [srcKey])  // eslint-disable-line react-hooks/exhaustive-deps

  const rows = data?.rows ?? []
  const last = tip?.price ?? (rows.length ? rows[rows.length - 1].close : null)
  const prev = data?.previous_close ?? tip?.prev_close ?? null
  const chg = last != null && prev ? (last / prev - 1) * 100 : null
  const hi = rows.length ? Math.max(...rows.map(r => r.high), tip?.price ?? -Infinity) : null
  const lo = rows.length ? Math.min(...rows.map(r => r.low), tip?.price ?? Infinity) : null
  const shown = hover?.value ?? last
  const shownChg = shown != null && prev ? (shown / prev - 1) * 100 : null
  const up = (shownChg ?? 0) >= 0
  const fmt = (v: number | null) => fmtIdx(v)   // index levels (and VIX) with NSE's 2 decimals (C1-08)

  return (
    <div>
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 6 }}>
        {INDICES.map(([name, short]) => <Chip key={name} active={index === name} color={T.cyan} onClick={() => setIndex(name)}>{short}</Chip>)}
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap', fontFamily: T.mono }}>
        <span style={{ fontSize: 20, fontWeight: 700, color: T.text }}>{fmt(shown)}</span>
        <span style={{ fontSize: 12, fontWeight: 700, color: up ? T.green : T.red }}>{fmtPct(shownChg, 2)}</span>
        <span style={{ fontSize: 10.5, color: T.dim }}>{hover ? `at ${hover.time}` : data?.day ? `${data.day.slice(5)} · prev ${fmt(prev)}` : ''}</span>
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 10.5, color: T.muted }}>H {fmt(hi)} · L {fmt(lo)}{chg != null && hi != null && lo != null && prev ? ` · range ${((hi - lo) / prev * 100).toFixed(2)}%` : ''}</span>
      </div>
      <div ref={box} style={{ width: '100%', height, marginTop: 4, position: 'relative' }}>
        {!rows.length && <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, color: T.dim, zIndex: Z.raised }}>
          {error ? `NSE chart unavailable: ${error}` : data ? 'No intraday data yet' : 'Loading…'}</div>}
      </div>
      <div style={{ fontSize: 10, color: T.dim, marginTop: 2 }}>{tip
        ? `level: ${live.lineFor(index) ?? 'live quote'} · path: NSE chart feed, 1-min, ≈1 min delayed`
        : 'NSE chart feed · 1-min · ≈1 min delayed · refreshes every minute in session'}</div>
    </div>
  )
}

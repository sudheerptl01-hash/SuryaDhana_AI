'use client'

/**
 * ChartStudio — CHRT: the terminal's interactive chart page (worldclass W1).
 *
 * Candlestick + volume for any NSE ticker on D / W / M bars (resampled EOD from
 * DuckDB via /api/charts/ohlcv) and 1m/5m/15m intraday bars when the W6 tick
 * store is live (/api/charts/intraday — degrades honestly to a note until then).
 * EMA(20/50/200), Bollinger(20,2) overlays and an RSI(14) sub-pane, all computed
 * client-side in lib/chartData.ts. lightweight-charts is dynamic-imported so its
 * chunk loads only when the tab is opened.
 *
 * Provenance is always on screen: EOD bars are labelled DuckDB EOD with their
 * as-of date; intraday bars carry the tick source (icici-ws) and session VWAP.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type {
  IChartApi, IPriceLine, ISeriesApi, LogicalRange, Time, UTCTimestamp,
} from 'lightweight-charts'
import {
  Chip, Empty, ErrorBox, Label, Loading, Notice, PageHeader, Panel, SourceChip, T, TickerLink, fmtPct, tone, sourceOf } from '@/components/terminal'
import { useLiveQuotes } from '@/lib/liveQuotes'
import { fmtVol } from '@/components/news/format'
import { apiError } from '@/lib/errors'
import { Z } from '@/lib/z'
import {
  DEFAULT_DAYS, RANGE_OPTIONS, bollinger, ema, fetchDailyBars, fetchIntradayBars, istChartTime, rsi,
  type ChartBar, type ChartTf, type IntradayInterval, type Timeframe,
} from '@/lib/chartData'

const MAIN_H = 430
const RSI_H = 120
/** right price-axis width of both panes (px): equal widths keep the two plot areas aligned (CT-14) */
const PRICE_AXIS_W = 72
const EOD_TFS: Timeframe[] = ['D', 'W', 'M']
const TICK_TFS: IntradayInterval[] = ['1m', '5m', '15m']

type LwModule = typeof import('lightweight-charts')

interface ChartHandles {
  main: IChartApi
  rsiChart: IChartApi
  candles: ISeriesApi<'Candlestick'>
  vol: ISeriesApi<'Histogram'>
  ema20: ISeriesApi<'Line'>
  ema50: ISeriesApi<'Line'>
  ema200: ISeriesApi<'Line'>
  bbU: ISeriesApi<'Line'>
  bbM: ISeriesApi<'Line'>
  bbL: ISeriesApi<'Line'>
  rsiLine: ISeriesApi<'Line'>
  vwapLine: IPriceLine | null
}

type DataState =
  | { kind: 'eod'; bars: ChartBar[]; asOf: string | null }
  | { kind: 'ticks'; bars: ChartBar[]; date: string; vwap: number | null; source: string | null; note?: string }

interface SymbolRow { t: string; n: string }

const timeKey = (t: Time): string =>
  typeof t === 'number' ? String(t)
    : typeof t === 'string' ? t
    : `${t.year}-${String(t.month).padStart(2, '0')}-${String(t.day).padStart(2, '0')}`

const px = (v: number | null | undefined, digits = 2): string =>
  v == null || !Number.isFinite(v) ? '—' : v.toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits })

// module-level symbol directory cache: one fetch per session, shared with re-mounts
let symbolDir: SymbolRow[] | null = null

export function ChartStudio({ symbol: symbolProp = 'RELIANCE' }: { symbol?: string }) {
  const [symbol, setSymbol] = useState(symbolProp.toUpperCase())
  useEffect(() => { setSymbol(symbolProp.toUpperCase()) }, [symbolProp])

  const [tf, setTf] = useState<ChartTf>('D')
  const [range, setRange] = useState<'auto' | string>('auto')
  const [show, setShow] = useState({ ema20: true, ema50: true, ema200: false, bb: false, rsi: true, vol: true })
  const [data, setData] = useState<DataState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [hoverIdx, setHoverIdx] = useState<number | null>(null)
  const [ready, setReady] = useState(false)

  const isIntraday = tf === '1m' || tf === '5m' || tf === '15m'
  const days = range === 'auto' ? DEFAULT_DAYS[isIntraday ? 'D' : (tf as Timeframe)] : Number(range)

  const mainBox = useRef<HTMLDivElement>(null)
  const rsiBox = useRef<HTMLDivElement>(null)
  const api = useRef<ChartHandles | null>(null)
  const lwRef = useRef<LwModule | null>(null)
  const idxByKey = useRef<Map<string, number>>(new Map())
  const fitKey = useRef('')
  const seq = useRef(0)

  // ── chart construction (lightweight-charts dynamic-imported: lazy chunk) ──────
  useEffect(() => {
    let disposed = false
    let cleanup: (() => void) | null = null
    void (async () => {
      const lw = await import('lightweight-charts')
      if (disposed || !mainBox.current || !rsiBox.current) return
      lwRef.current = lw
      const base = {
        layout: { background: { type: lw.ColorType.Solid, color: 'transparent' }, textColor: T.muted, fontFamily: T.mono, fontSize: 10 },
        grid: { vertLines: { visible: false }, horzLines: { color: T.border } },
        crosshair: { mode: lw.CrosshairMode.Magnet },
        timeScale: { borderColor: T.borderHi, timeVisible: true, secondsVisible: false },
      }
      const main = lw.createChart(mainBox.current, {
        ...base, width: mainBox.current.clientWidth, height: MAIN_H,
        // CT-14: one fixed price-axis width on both panes, so their plot areas (and dates) line up
        rightPriceScale: { borderColor: T.borderHi, scaleMargins: { top: 0.06, bottom: 0.2 }, minimumWidth: PRICE_AXIS_W },
      })
      const rsiChart = lw.createChart(rsiBox.current, {
        ...base, width: rsiBox.current.clientWidth, height: RSI_H,
        rightPriceScale: { borderColor: T.borderHi, scaleMargins: { top: 0.12, bottom: 0.08 }, minimumWidth: PRICE_AXIS_W },
      })
      const candles = main.addCandlestickSeries({
        upColor: T.green, downColor: T.red, borderVisible: false,
        wickUpColor: T.green, wickDownColor: T.red, priceLineColor: T.dim,
      })
      const vol = main.addHistogramSeries({ priceScaleId: 'vol', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false })
      main.priceScale('vol').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } })
      const line = (color: string, dotted = false) => main.addLineSeries({
        color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        ...(dotted ? { lineStyle: lw.LineStyle.Dotted } : {}),
      })
      const ema20 = line(T.cyan)
      const ema50 = line(T.amber)
      const ema200 = line(T.violet)
      const bbU = line(T.dim)
      const bbL = line(T.dim)
      const bbM = line(T.dim, true)
      const rsiLine = rsiChart.addLineSeries({
        color: T.cyan, lineWidth: 1, priceLineVisible: false,
        autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }),
      })
      for (const lvl of [70, 30]) rsiLine.createPriceLine({ price: lvl, color: T.dim, lineWidth: 1, lineStyle: lw.LineStyle.Dashed, axisLabelVisible: false, title: '' })

      // keep the two panes on one time axis (guard against subscribe loops)
      let syncing = false
      const follow = (to: IChartApi) => (r: LogicalRange | null) => {
        if (!r || syncing) return
        syncing = true
        to.timeScale().setVisibleLogicalRange(r)
        syncing = false
      }
      main.timeScale().subscribeVisibleLogicalRangeChange(follow(rsiChart))
      rsiChart.timeScale().subscribeVisibleLogicalRangeChange(follow(main))

      main.subscribeCrosshairMove(p => {
        if (p.time == null) { setHoverIdx(null); return }
        setHoverIdx(idxByKey.current.get(timeKey(p.time)) ?? null)
      })

      const ro = new ResizeObserver(es => {
        const w = es[0]?.contentRect.width
        if (w) { main.applyOptions({ width: w }); rsiChart.applyOptions({ width: w }) }
      })
      ro.observe(mainBox.current)
      api.current = { main, rsiChart, candles, vol, ema20, ema50, ema200, bbU, bbM, bbL, rsiLine, vwapLine: null }
      setReady(true)
      cleanup = () => { ro.disconnect(); main.remove(); rsiChart.remove(); api.current = null }
    })()
    return () => { disposed = true; cleanup?.() }
  }, [])

  // ── data loading ───────────────────────────────────────────────────────────────
  const load = useCallback(async () => {
    const id = ++seq.current
    setLoading(true)
    setError(null)
    try {
      if (tf === '1m' || tf === '5m' || tf === '15m') {
        const r = await fetchIntradayBars(symbol, tf)
        if (seq.current !== id) return
        setData({ kind: 'ticks', bars: r.bars, date: r.date, vwap: r.vwap, source: r.source, note: r.note ?? r.error_info?.message })
      } else {
        const r = await fetchDailyBars(symbol, tf, days)
        if (seq.current !== id) return
        setData({ kind: 'eod', bars: r.bars, asOf: r.as_of })
      }
      setHoverIdx(null)
    } catch (e) {
      if (seq.current === id) { setError(apiError(e, 'chart data unavailable')); setData(null) }
    } finally {
      if (seq.current === id) setLoading(false)
    }
  }, [symbol, tf, days])
  useEffect(() => { void load() }, [load])
  useEffect(() => {
    if (!isIntraday) return
    const iv = setInterval(() => { void load() }, 60_000)
    return () => clearInterval(iv)
  }, [isIntraday, load])

  // ── live last-price line (live program, reports/live_nse) ─────────────────────
  // The live NSE quote service's price for the symbol (Breeze websocket → NSE ≈ 1 min → the last close), every 2 s, as
  // a dotted price line on the candles titled by its state (LIVE / NSE / STALE / CLOSE) — on every timeframe, so a
  // daily chart shows where the stock trades now. The bars themselves stay the tick store / DuckDB EOD.
  const liveQ = useLiveQuotes([symbol], { intervalMs: 2_000 })
  const lq = liveQ.quotes[symbol.toUpperCase().replace(/\.NS$/, '')]
  const lqInfo = lq && lq.price != null && lq.state !== 'unavailable' ? liveQ.sourceFor(symbol) : null
  const lastLine = useRef<IPriceLine | null>(null)
  useEffect(() => {
    const a = api.current
    const lw = lwRef.current
    if (!a || !lw) return
    if (lastLine.current) { try { a.candles.removePriceLine(lastLine.current) } catch { /* series rebuilt */ } lastLine.current = null }
    if (!lq || lq.price == null || !lqInfo) return
    const title = lqInfo.state === 'live' ? 'LIVE' : lqInfo.state === 'closed' ? 'CLOSE' : lqInfo.state === 'stale' ? 'STALE' : 'NSE'
    lastLine.current = a.candles.createPriceLine({ price: lq.price, color: lqInfo.state === 'live' ? T.green : T.muted, lineWidth: 1,
                                                   lineStyle: lw.LineStyle.Dotted, axisLabelVisible: true, title })
  }, [lq?.price, lqInfo?.state, ready, data])  // eslint-disable-line react-hooks/exhaustive-deps

  // ── push bars + indicators into the series ─────────────────────────────────────
  useEffect(() => {
    const a = api.current
    const lw = lwRef.current
    if (!a || !lw || !data) return
    const bars = data.bars
    const times: Time[] = data.kind === 'ticks'
      ? bars.map(b => istChartTime(data.date, b.t) as UTCTimestamp)
      : bars.map(b => b.t as Time)
    const idx = new Map<string, number>()
    times.forEach((t, i) => idx.set(timeKey(t), i))
    idxByKey.current = idx

    a.candles.setData(bars.map((b, i) => ({ time: times[i], open: b.o, high: b.h, low: b.l, close: b.c })))
    a.vol.setData(show.vol
      ? bars.map((b, i) => ({ time: times[i], value: b.v, color: b.c >= b.o ? 'rgba(22,217,138,.4)' : 'rgba(255,77,94,.4)' }))
      : [])

    const closes = bars.map(b => b.c)
    const lineData = (vals: (number | null)[]) =>
      vals.flatMap((v, i) => (v == null ? [] : [{ time: times[i], value: v }]))
    a.ema20.setData(show.ema20 ? lineData(ema(closes, 20)) : [])
    a.ema50.setData(show.ema50 ? lineData(ema(closes, 50)) : [])
    a.ema200.setData(show.ema200 ? lineData(ema(closes, 200)) : [])
    if (show.bb) {
      const bb = bollinger(closes, 20, 2)
      a.bbU.setData(lineData(bb.upper)); a.bbM.setData(lineData(bb.mid)); a.bbL.setData(lineData(bb.lower))
    } else { a.bbU.setData([]); a.bbM.setData([]); a.bbL.setData([]) }
    // CT-14: the RSI pane carries every bar's time (whitespace before RSI has 14 bars), so the logical-range sync
    // maps bar i to bar i; without them its index 0 was bar 14 and the pane sat 14 bars off the price pane
    a.rsiLine.setData(show.rsi ? rsi(closes, 14).map((v, i) => (v == null ? { time: times[i] } : { time: times[i], value: v })) : [])

    if (a.vwapLine) { a.candles.removePriceLine(a.vwapLine); a.vwapLine = null }
    if (data.kind === 'ticks' && data.vwap != null && bars.length)
      a.vwapLine = a.candles.createPriceLine({ price: data.vwap, color: T.cyan, lineWidth: 1, lineStyle: lw.LineStyle.Dashed, axisLabelVisible: true, title: 'VWAP' })

    const key = `${symbol}|${tf}|${days}`   // 60 s intraday refresh keeps the zoom; a new symbol/tf/range refits
    if (fitKey.current !== key && bars.length) { fitKey.current = key; a.main.timeScale().fitContent() }
  }, [data, show, ready, symbol, tf, days])

  // ── symbol search ──────────────────────────────────────────────────────────────
  const [q, setQ] = useState('')
  const [openSearch, setOpenSearch] = useState(false)
  const [syms, setSyms] = useState<SymbolRow[] | null>(symbolDir)
  useEffect(() => {
    if (!openSearch || syms) return
    fetch('/api/stocks/symbols')
      .then(r => r.json())
      .then((j: { data?: { t?: string; n?: string }[] }) => {
        symbolDir = (j.data ?? []).map(s => ({ t: String(s.t ?? ''), n: String(s.n ?? s.t ?? '') })).filter(s => s.t)
        setSyms(symbolDir)
      })
      .catch(() => setSyms([]))
  }, [openSearch, syms])
  const matches = useMemo(() => {
    const u = q.trim().toUpperCase()
    if (!u || !syms) return []
    const pre = syms.filter(s => s.t.startsWith(u))
    const sub = syms.filter(s => !s.t.startsWith(u) && (s.t.includes(u) || s.n.toUpperCase().includes(u)))
    return [...pre, ...sub].slice(0, 9)
  }, [q, syms])
  const pick = (s: string) => {
    const sym = s.trim().toUpperCase()
    if (!sym) return
    setSymbol(sym)
    setQ('')
    setOpenSearch(false)
  }

  // ── readout ────────────────────────────────────────────────────────────────────
  const bars = data?.bars ?? []
  const shownIdx = hoverIdx != null && hoverIdx < bars.length ? hoverIdx : bars.length - 1
  const shown = shownIdx >= 0 ? bars[shownIdx] : null
  const prevClose = data?.kind === 'ticks'
    ? (bars[0]?.o ?? null)                                   // session change vs open
    : shownIdx > 0 ? bars[shownIdx - 1].c : null             // vs previous D/W/M bar
  const chgPct = shown && prevClose ? (shown.c / prevClose - 1) * 100 : null
  const chgLabel = data?.kind === 'ticks' ? 'vs open' : tf === 'D' ? 'vs prev day' : tf === 'W' ? 'vs prev week' : 'vs prev month'

  const provenance = data?.kind === 'ticks'
    ? `${(data.source ?? 'tick store').toUpperCase()} · ${data.date}${data.vwap != null ? ` · VWAP ${px(data.vwap)}` : ''}`
    : data ? `DUCKDB EOD · AS OF ${data.asOf ?? '—'}` : '…'

  const tfChip = (t: ChartTf, color: string) => (
    <Chip key={t} active={tf === t} color={color} onClick={() => setTf(t)} aria-label={`timeframe ${t}`}>{t}</Chip>
  )
  const indChip = (k: keyof typeof show, label: string, color: string) => (
    <Chip key={k} active={show[k]} color={color} onClick={() => setShow(s => ({ ...s, [k]: !s[k] }))}>{label}</Chip>
  )

  const degradedNote = data?.kind === 'ticks' && !bars.length ? (data.note ?? 'no intraday bars') : null

  return (
    <div>
      <PageHeader code="CHRT" title="Chart Studio"
        subtitle="candles · EMA / Bollinger / RSI · D / W / M from EOD · intraday when the tick store is live"
        right={
          <span style={{ position: 'relative', display: 'inline-block' }}>
            <input
              value={q}
              onChange={e => { setQ(e.target.value); setOpenSearch(true) }}
              onFocus={() => setOpenSearch(true)}
              onBlur={() => setTimeout(() => setOpenSearch(false), 150)}
              onKeyDown={e => {
                if (e.key === 'Enter') pick(matches[0]?.t ?? q)
                else if (e.key === 'Escape') { setQ(''); setOpenSearch(false) }
              }}
              placeholder="symbol… (RELIANCE)"
              aria-label="chart symbol search"
              style={{ width: 210, background: '#07090d', color: T.text, border: `1px solid ${T.border}`,
                       fontFamily: T.mono, fontSize: 12, padding: '6px 8px', borderRadius: 0, outline: 'none' }}
            />
            {openSearch && matches.length > 0 && (
              <div style={{ position: 'absolute', top: '100%', right: 0, width: 300, zIndex: Z.commandbar,
                            background: T.panel, border: `1px solid ${T.borderHi}`, boxShadow: '0 8px 24px rgba(0,0,0,.6)' }}>
                {matches.map(m => (
                  <div key={m.t} onMouseDown={() => pick(m.t)} role="button"
                    style={{ display: 'flex', gap: 10, padding: '6px 10px', cursor: 'pointer', fontSize: 11,
                             fontFamily: T.mono, borderBottom: `1px solid ${T.border}` }}>
                    <span style={{ color: T.amber, fontWeight: 700, minWidth: 92 }}>{m.t}</span>
                    <span style={{ color: T.muted, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{m.n}</span>
                  </div>
                ))}
              </div>
            )}
          </span>
        }
      />

      <Panel source={sourceOf(data?.kind === 'eod' ? data.asOf : data?.kind === 'ticks' ? data.date : null, { source: data?.kind === 'ticks' ? (data.source ?? 'tick store') : 'DuckDB EOD' })}
        title={<span><TickerLink symbol={symbol} /> <span style={{ color: T.dim, fontWeight: 400 }}>· {tf}</span></span>}
        subtitle={provenance}
        right={
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            {!isIntraday && (
              <select value={range} onChange={e => setRange(e.target.value)} aria-label="lookback range"
                style={{ background: '#07090d', color: T.text, border: `1px solid ${T.border}`, fontFamily: T.mono,
                         fontSize: 10, padding: '3px 5px', borderRadius: 0 }}>
                <option value="auto">AUTO</option>
                {RANGE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            )}
            <Chip color={T.cyan} onClick={() => { void load() }} title="refresh">↻</Chip>
          </span>
        }
        pad={10}
      >
        {/* toolbar: timeframes + indicators */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 5, flexWrap: 'wrap', marginBottom: 8 }}>
          {EOD_TFS.map(t => tfChip(t, T.amber))}
          <span style={{ width: 1, height: 14, background: T.border, margin: '0 4px' }} />
          {TICK_TFS.map(t => tfChip(t, T.cyan))}
          <span style={{ flex: 1 }} />
          {indChip('ema20', 'EMA 20', T.cyan)}
          {indChip('ema50', 'EMA 50', T.amber)}
          {indChip('ema200', 'EMA 200', T.violet)}
          {indChip('bb', 'BB 20·2', T.text)}
          {indChip('rsi', 'RSI 14', T.cyan)}
          {indChip('vol', 'VOL', T.muted)}
        </div>

        {/* crosshair OHLC readout */}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap', fontFamily: T.mono,
                      fontVariantNumeric: 'tabular-nums', marginBottom: 6, minHeight: 24 }}>
          <span style={{ fontSize: 19, fontWeight: 700, color: T.bright }}>{px(shown?.c)}</span>
          <span style={{ fontSize: 12, fontWeight: 700, color: tone(chgPct) }}>{fmtPct(chgPct, 2)}</span>
          <span style={{ fontSize: 9.5, color: T.dim, letterSpacing: 1 }}>{shown ? chgLabel.toUpperCase() : ''}</span>
          {shown && (
            <span style={{ fontSize: 11, color: T.muted, display: 'inline-flex', gap: 10, flexWrap: 'wrap' }}>
              <span>{data?.kind === 'ticks' ? `${shown.t} IST` : shown.t}</span>
              <span>O <span style={{ color: T.text }}>{px(shown.o)}</span></span>
              <span>H <span style={{ color: T.green }}>{px(shown.h)}</span></span>
              <span>L <span style={{ color: T.red }}>{px(shown.l)}</span></span>
              <span>C <span style={{ color: tone(shown.c - shown.o) }}>{px(shown.c)}</span></span>
              <span>V <span style={{ color: T.text }}>{fmtVol(shown.v)}</span></span>
            </span>
          )}
          <span style={{ flex: 1 }} />
          {lqInfo && lq && <span data-sd-chart-last title={`dotted line on the chart: ${liveQ.lineFor(symbol) ?? ''}`}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11, color: T.muted }}>
            last <span style={{ color: T.text, fontWeight: 700 }}>{px(lq.price)}</span>
            <span style={{ color: tone(lq.change_pct) }}>{fmtPct(lq.change_pct, 2)}</span>
            <SourceChip info={lqInfo} /></span>}
          <Label color={isIntraday ? T.cyan : T.muted}>
            {isIntraday ? 'BARS: BROKER TICKS (ICICI WS)' : 'BARS: DUCKDB EOD · YAHOO HISTORY'}
          </Label>
        </div>

        {error && <div style={{ marginBottom: 8 }}><ErrorBox error={error} onRetry={() => { void load() }} /></div>}
        {degradedNote && !error && (
          <div style={{ marginBottom: 8 }}>
            <Notice color={T.amber}>
              <b style={{ color: T.amber }}>INTRADAY UNAVAILABLE — {degradedNote}.</b>{' '}
              The chart shows nothing rather than fake bars; D / W / M history above remains live from DuckDB EOD.
            </Notice>
          </div>
        )}

        {/* panes */}
        <div style={{ position: 'relative' }}>
          <div ref={mainBox} style={{ width: '100%', height: MAIN_H }} />
          {(!ready || (loading && !bars.length)) && !error && (
            <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: Z.raised }}>
              <Loading label={ready ? `${symbol} ${tf}` : 'chart engine'} />
            </div>
          )}
          {ready && !loading && !bars.length && !error && !degradedNote && (
            <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: Z.raised }}>
              <Empty title="No bars" hint="No OHLCV rows in this window — try a longer range." />
            </div>
          )}
        </div>
        <div style={{ display: show.rsi ? 'block' : 'none' }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', margin: '6px 0 2px' }}>
            <Label color={T.cyan}>RSI 14</Label>
            <Label color={T.dim}>70 / 30 BANDS · WILDER</Label>
          </div>
          <div ref={rsiBox} style={{ width: '100%', height: RSI_H }} />
        </div>

        <div style={{ marginTop: 8, fontSize: 10, color: T.dim, display: 'flex', gap: 14, flexWrap: 'wrap' }}>
          <span>EMA / Bollinger / RSI computed from the bars shown</span>
          <span>W/M bars are labelled by the bucket&apos;s last trading day</span>
          {isIntraday && <span>intraday refreshes every 60 s · times are IST</span>}
        </div>
      </Panel>
    </div>
  )
}

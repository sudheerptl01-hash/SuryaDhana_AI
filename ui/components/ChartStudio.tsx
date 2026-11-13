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
 *
 * W2-TAPE (5 Nov review M42 / m073 / M34 / M45):
 *  - an NSE index charts too (NIFTY, BANKNIFTY, FINNIFTY …: `index_ohlc_daily`, NSE's daily index file; quick chips by
 *    the search box); the page opens on the ACTIVE SYMBOL (lib/activeSymbol) and writes it back on a pick — never a
 *    hard-coded RELIANCE;
 *  - overlays from stored tables (/api/charts/overlay): the near-month FUTURE close on the price pane, and a lower pane
 *    that switches RSI 14 → IV30 (iv_summary_daily, with the near ATM IV and RV20) → F&O OI (call / put / futures) →
 *    BASIS (the near future vs spot, annualised); each with its badge and source chip; daily timeframes only;
 *  - EMA 200 on by default (price sat on it on 5 Nov);
 *  - intraday bars outside 09:15–15:30 are never drawn (`inSession`), and a session that starts late says so.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type {
  IChartApi, IPriceLine, ISeriesApi, LogicalRange, MouseEventParams, Time, UTCTimestamp,
} from 'lightweight-charts'
import {
  Chip, Empty, ErrorBox, Label, Loading, Notice, PageHeader, Panel, SourceChip, T, TickerLink, fmtPct, tone, sourceOf } from '@/components/terminal'
import { useLiveQuotes } from '@/lib/liveQuotes'
import { useActiveSymbol } from '@/lib/activeSymbol'
import { ALERTS_EVENT, draftAlert } from '@/lib/alerts'
import { getAlertRules } from '@/lib/alertsClient'
import { alertLevelsFor } from '@/lib/alertsEngine'
import { draftAtLevel, nearestLevel } from '@/lib/alertOverlay'
import { goToPage } from '@/lib/navigate'
import { alignOverlay, inSession, type OverlayPoint } from '@/components/expiry/chartModel'
import { fmtVol } from '@/components/news/format'
import { apiError } from '@/lib/errors'
import { saveDownload } from '@/lib/platform'
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
  futLine: ISeriesApi<'Line'>
  ivLine: ISeriesApi<'Line'>
  ivNear: ISeriesApi<'Line'>
  rvLine: ISeriesApi<'Line'>
  oiCall: ISeriesApi<'Line'>
  oiPut: ISeriesApi<'Line'>
  oiFut: ISeriesApi<'Line'>
  basisLine: ISeriesApi<'Line'>
  vwapLine: IPriceLine | null
}

/** The lower pane: RSI 14 (computed from the bars) or a stored daily series (M42). */
type LowerPane = 'rsi' | 'iv' | 'oi' | 'basis'
type OverlayKind = 'iv' | 'oi' | 'future'
interface OverlayResponse {
  symbol: string; kind: OverlayKind; points: OverlayPoint[]; as_of: string | null; badge: string; source: string; unit: string
  note?: string; ok?: boolean; error_info?: { code: string; message: string }
}
const INDEX_CHIPS = ['NIFTY', 'BANKNIFTY', 'FINNIFTY']

/** The CHRT overlay reader (stored tables only, through ui-api /api/charts/overlay). */
export async function fetchInstrument(symbol: string, kind: OverlayKind, days: number): Promise<OverlayResponse> {
  const r = await fetch(`/api/charts/overlay?symbol=${encodeURIComponent(symbol)}&kind=${kind}&days=${days}`)
  const body = (await r.json().catch(() => null)) as OverlayResponse | { detail?: string } | null
  if (!r.ok || !body || !('points' in body)) throw new Error((body as { detail?: string } | null)?.detail ?? `HTTP ${r.status}`)
  return body
}

type DataState =
  | { kind: 'eod'; bars: ChartBar[]; asOf: string | null; index?: string | null; closeOnly?: number }
  | { kind: 'ticks'; bars: ChartBar[]; date: string; vwap: number | null; source: string | null; note?: string; coverage?: string }

interface SymbolRow { t: string; n: string }

const timeKey = (t: Time): string =>
  typeof t === 'number' ? String(t)
    : typeof t === 'string' ? t
    : `${t.year}-${String(t.month).padStart(2, '0')}-${String(t.day).padStart(2, '0')}`

const px = (v: number | null | undefined, digits = 2): string =>
  v == null || !Number.isFinite(v) ? '—' : v.toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits })

// module-level symbol directory cache: one fetch per session, shared with re-mounts
let symbolDir: SymbolRow[] | null = null

export function ChartStudio({ symbol: symbolProp }: { symbol?: string }) {
  // M34 / m073: open on the active symbol (OMON / DES / the GO bar write it), never a hard-coded RELIANCE
  const [active, setActive] = useActiveSymbol()
  const [symbol, setSymbol] = useState(() => (symbolProp ?? active?.symbol ?? 'NIFTY').toUpperCase())
  useEffect(() => { if (symbolProp) setSymbol(symbolProp.toUpperCase()) }, [symbolProp])
  useEffect(() => {
    if (!symbolProp && active?.symbol && active.symbol.toUpperCase() !== symbol) setSymbol(active.symbol.toUpperCase())
  }, [active?.symbol])  // eslint-disable-line react-hooks/exhaustive-deps

  const [tf, setTf] = useState<ChartTf>('D')
  const [range, setRange] = useState<'auto' | string>('auto')
  const [show, setShow] = useState({ ema20: true, ema50: true, ema200: true, bb: false, rsi: true, vol: true })
  const [lower, setLower] = useState<LowerPane>('rsi')
  const lowerRef = useRef<LowerPane>('rsi')
  lowerRef.current = lower
  const [showFut, setShowFut] = useState(false)
  const [overlays, setOverlays] = useState<Partial<Record<OverlayKind, OverlayResponse | { error: string }>>>({})
  const [data, setData] = useState<DataState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [hoverIdx, setHoverIdx] = useState<number | null>(null)
  const [ready, setReady] = useState(false)
  // FINAL ROUND C5 (chart kit consistency): ⛶ grows the panes to the window height in place (Esc restores) —
  // CHRT is already a full-page chart, so "expand" here means taller panes, never a remounting overlay
  const [tall, setTall] = useState(false)

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
        // the 0–100 frame only while the pane shows RSI; IV30 / OI / BASIS autoscale on their own values
        autoscaleInfoProvider: () => (lowerRef.current === 'rsi' ? { priceRange: { minValue: 0, maxValue: 100 } } : null),
      })
      const lowerLine = (color: string, dotted = false, volume = false) => rsiChart.addLineSeries({
        color, lineWidth: 1, priceLineVisible: false, lastValueVisible: true,
        ...(dotted ? { lineStyle: lw.LineStyle.Dashed } : {}), ...(volume ? { priceFormat: { type: 'volume' as const } } : {}),
      })
      const ivLine = lowerLine(T.cyan)
      const ivNear = lowerLine(T.cyan, true)
      const rvLine = lowerLine(T.muted, true)
      const oiCall = lowerLine(T.cyan, false, true)
      const oiPut = lowerLine(T.violet, false, true)
      const oiFut = lowerLine(T.amber, true, true)
      const basisLine = lowerLine(T.amber)
      const futLine = main.addLineSeries({ color: T.amber, lineWidth: 1, lineStyle: lw.LineStyle.Dotted, priceLineVisible: false,
                                           lastValueVisible: true, crosshairMarkerVisible: false, title: 'FUT' })
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
      api.current = { main, rsiChart, candles, vol, ema20, ema50, ema200, bbU, bbM, bbL, rsiLine, futLine, ivLine, ivNear, rvLine,
                      oiCall, oiPut, oiFut, basisLine, vwapLine: null }
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
        const cov = (r as { coverage_note?: string }).coverage_note
        setData({ kind: 'ticks', bars: inSession(r.bars), date: r.date, vwap: r.vwap, source: r.source, note: r.note ?? r.error_info?.message, coverage: cov })
      } else {
        const r = await fetchDailyBars(symbol, tf, days)
        if (seq.current !== id) return
        const x = r as { kind?: string; close_only?: number; index_name?: string }
        setData({ kind: 'eod', bars: r.bars, asOf: r.as_of, index: x.kind === 'index' ? (x.index_name ?? symbol) : null, closeOnly: x.close_only ?? 0 })
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

  // ── M42 overlays (daily, stored tables): the near future on the price pane, IV30 / OI / basis in the lower pane ─────
  const wanted: OverlayKind[] = isIntraday ? [] : [...(showFut || lower === 'basis' ? ['future' as const] : []),
    ...(lower === 'iv' ? ['iv' as const] : []), ...(lower === 'oi' ? ['oi' as const] : [])]
  const wantedKey = wanted.join(',')
  useEffect(() => {
    if (!wantedKey) return
    let alive = true
    for (const k of wantedKey.split(',') as OverlayKind[]) {
      fetchInstrument(symbol, k, Math.max(days, 400))
        .then(r => { if (alive) setOverlays(o => ({ ...o, [k]: r })) })
        .catch((e: unknown) => { if (alive) setOverlays(o => ({ ...o, [k]: { error: apiError(e, 'overlay unavailable') } })) })
    }
    return () => { alive = false }
  }, [symbol, days, wantedKey])
  useEffect(() => { setOverlays({}) }, [symbol])

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

  // alert lines (PLAN 2.3): every price rule / price alert level on this symbol, dashed amber, titled ALERT
  const [alertLevels, setAlertLevels] = useState<number[]>([])
  const alertLines = useRef<IPriceLine[]>([])
  useEffect(() => {
    let on = true
    const read = () => { getAlertRules('all').then(r => { if (on) setAlertLevels(alertLevelsFor(r.data.rules, symbol)) }).catch(() => {}) }
    read()
    const iv = setInterval(read, 60_000)
    window.addEventListener(ALERTS_EVENT, read)
    return () => { on = false; clearInterval(iv); window.removeEventListener(ALERTS_EVENT, read) }
  }, [symbol])
  useEffect(() => {
    const a = api.current
    const lw = lwRef.current
    if (!a || !lw) return
    for (const l of alertLines.current) { try { a.candles.removePriceLine(l) } catch { /* series rebuilt */ } }
    alertLines.current = alertLevels.map(price => a.candles.createPriceLine({ price, color: T.amber, lineWidth: 1, lineStyle: lw.LineStyle.Dashed,
                                                                            axisLabelVisible: true, title: 'ALERT' }))
  }, [alertLevels, ready, data])  // eslint-disable-line react-hooks/exhaustive-deps

  // E-DIFF T-22: click an ALERT line → the rule in ALRT; right-click a level → "alert at this level"
  // (pre-fills the typed-rule builder — the existing draftAlert path; the owner reviews and saves)
  useEffect(() => {
    const a = api.current
    const el = mainBox.current
    if (!a || !el || !ready) return
    const click = (p: MouseEventParams) => {
      if (!p.point) return
      const hit = nearestLevel(alertLevels, p.point.y, px => a.candles.priceToCoordinate(px))
      if (hit != null) goToPage('alerts')
    }
    a.main.subscribeClick(click)
    const onCtx = (e: MouseEvent) => {
      const r = el.getBoundingClientRect()
      const raw = a.candles.coordinateToPrice(e.clientY - r.top)
      const price = raw == null ? null : Number(raw)
      if (price == null || !Number.isFinite(price)) return
      e.preventDefault()
      const d = draftAtLevel('price', symbol, price, lq?.price ?? null)
      if (d) draftAlert(d)
    }
    el.addEventListener('contextmenu', onCtx)
    return () => { a.main.unsubscribeClick(click); el.removeEventListener('contextmenu', onCtx) }
  }, [ready, alertLevels, symbol, lq?.price])  // eslint-disable-line react-hooks/exhaustive-deps

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
    a.rsiLine.setData(show.rsi && lower === 'rsi' ? rsi(closes, 14).map((v, i) => (v == null ? { time: times[i] } : { time: times[i], value: v })) : [])
    // M42 overlays: aligned to every bar time (whitespace where the store has no value) so the panes stay bar-for-bar
    const ov = (k: OverlayKind) => { const o = overlays[k]; return o && 'points' in o ? o.points : null }
    const barDates = data.kind === 'eod' ? bars.map(b => b.t) : []
    const series = (k: OverlayKind, key: string) => {
      const pts = ov(k)
      if (!pts || data.kind !== 'eod') return []
      return alignOverlay(pts, barDates, key).map((v, i) => (v == null ? { time: times[i] } : { time: times[i], value: v }))
    }
    a.futLine.setData(showFut ? series('future', 'fut') : [])
    a.ivLine.setData(lower === 'iv' ? series('iv', 'iv30') : [])
    a.ivNear.setData(lower === 'iv' ? series('iv', 'near') : [])
    a.rvLine.setData(lower === 'iv' ? series('iv', 'rv20') : [])
    a.oiCall.setData(lower === 'oi' ? series('oi', 'call_oi') : [])
    a.oiPut.setData(lower === 'oi' ? series('oi', 'put_oi') : [])
    a.oiFut.setData(lower === 'oi' ? series('oi', 'fut_oi') : [])
    a.basisLine.setData(lower === 'basis' ? series('future', 'basis_ann_pct') : [])

    if (a.vwapLine) { a.candles.removePriceLine(a.vwapLine); a.vwapLine = null }
    if (data.kind === 'ticks' && data.vwap != null && bars.length)
      a.vwapLine = a.candles.createPriceLine({ price: data.vwap, color: T.cyan, lineWidth: 1, lineStyle: lw.LineStyle.Dashed, axisLabelVisible: true, title: 'VWAP' })

    const key = `${symbol}|${tf}|${days}`   // 60 s intraday refresh keeps the zoom; a new symbol/tf/range refits
    if (fitKey.current !== key && bars.length) { fitKey.current = key; a.main.timeScale().fitContent() }
  }, [data, show, ready, symbol, tf, days, overlays, lower, showFut])

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
    setActive({ symbol: sym })                     // the shared convention: CHRT writes the active symbol on a pick
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
    : data?.kind === 'eod' && data.index ? `NSE INDEX FILE · ${data.index} · AS OF ${data.asOf ?? '—'}`
    : data ? `DUCKDB EOD · AS OF ${data.asOf ?? '—'}` : '…'
  const isIndexChart = data?.kind === 'eod' && !!data.index
  const ovOf = (k: OverlayKind): OverlayResponse | null => { const o = overlays[k]; return o && 'points' in o ? o : null }
  const ovErr = (k: OverlayKind): string | null => { const o = overlays[k]; return o && 'error' in o ? o.error : (o && 'points' in o && o.ok === false ? (o.note ?? 'unavailable') : null) }
  const lowerKind: OverlayKind | null = lower === 'iv' ? 'iv' : lower === 'oi' ? 'oi' : lower === 'basis' ? 'future' : null
  const lowerOv = lowerKind ? ovOf(lowerKind) : null
  const lowerSrc = lowerKind ? sourceOf(lowerOv?.as_of ?? null, { source: lowerOv?.source ?? (lowerKind === 'iv' ? 'iv_summary_daily' : 'nse_fo_daily'), maxAgeDays: 5,
                                                                   hint: ovErr(lowerKind) ?? undefined }) : null
  const lowerLegend: Record<LowerPane, string> = {
    rsi: 'RSI 14 · 70 / 30 BANDS · WILDER',
    iv: 'IV30 (cyan) · NEAR ATM IV (dashed) · RV20 CLOSE-TO-CLOSE (grey) · % ANNUALISED · ARITHMETIC',
    oi: 'F&O OPEN INTEREST, ALL STRIKES + EXPIRIES (FALLS AT EVERY EXPIRY AS CONTRACTS SETTLE) · CALLS (cyan) · PUTS (violet) · FUTURES (amber, dashed) · SHARES · CONTEXT',
    basis: 'NEAR FUTURE vs SPOT · ANNUALISED BASIS % · ARITHMETIC',
  }

  const tfChip = (t: ChartTf, color: string) => (
    <Chip key={t} active={tf === t} color={color} onClick={() => setTf(t)} aria-label={`timeframe ${t}`}>{t}</Chip>
  )
  const indChip = (k: keyof typeof show, label: string, color: string) => (
    <Chip key={k} active={show[k]} color={color} onClick={() => setShow(s => ({ ...s, [k]: !s[k] }))}>{label}</Chip>
  )

  const degradedNote = data?.kind === 'ticks' && !bars.length ? (data.note ?? 'no intraday bars') : null

  // ── FIT · PNG ⤓ · ⛶ (FINAL ROUND C5: the chart-kit header actions, CHRT keeps its own toolbar) ─────────
  const mainH = tall && typeof window !== 'undefined' ? Math.max(MAIN_H, window.innerHeight - 360) : MAIN_H
  useEffect(() => {
    const a = api.current
    if (!a) return
    a.main.applyOptions({ height: mainH })
  }, [mainH, ready])
  useEffect(() => {
    if (!tall) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setTall(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [tall])
  const fitChart = () => api.current?.main.timeScale().fitContent()
  const pngChart = () => {
    const a = api.current
    if (!a) return
    const c1 = a.main.takeScreenshot()
    const c2 = show.rsi ? a.rsiChart.takeScreenshot() : null
    const out = document.createElement('canvas')
    out.width = Math.max(c1.width, c2?.width ?? 0)
    out.height = c1.height + (c2?.height ?? 0)
    const ctx = out.getContext('2d')
    if (!ctx) return
    ctx.fillStyle = T.bg
    ctx.fillRect(0, 0, out.width, out.height)
    ctx.drawImage(c1, 0, 0)
    if (c2) ctx.drawImage(c2, 0, c1.height)
    out.toBlob(b => { if (b) void saveDownload(b, `chrt-${symbol.toLowerCase()}-${tf}-${new Date().toLocaleDateString('en-CA')}.png`) }, 'image/png')
  }

  return (
    <div>
      <PageHeader code="CHRT" title="Chart Studio"
        subtitle="candles · EMA / Bollinger / RSI · D / W / M from EOD · intraday when the tick store is live"
        right={
          <span style={{ position: 'relative', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            {INDEX_CHIPS.map(ix => <Chip key={ix} active={symbol === ix} color={T.amber} onClick={() => pick(ix)} title={`chart the ${ix} index`}>{ix}</Chip>)}
            <Chip color={T.muted} title="open ALRT with a rule: this symbol crosses a level (dashed ALERT lines show the levels set)"
              onClick={() => draftAlert({ series: `price:${symbol.toUpperCase().replace(/\.NS$/, '')}`, op: 'cross_up',
                                          value: lq?.price != null ? Math.round(lq.price * 1.02 * 20) / 20 : null, repeat: 'repeat', cooldown_min: 30 })}>＋ ALERT</Chip>
            <input
              value={q}
              onChange={e => { setQ(e.target.value); setOpenSearch(true) }}
              onFocus={() => setOpenSearch(true)}
              onBlur={() => setTimeout(() => setOpenSearch(false), 150)}
              onKeyDown={e => {
                if (e.key === 'Enter') pick(matches[0]?.t ?? q)
                else if (e.key === 'Escape') { setQ(''); setOpenSearch(false) }
              }}
              placeholder="symbol… (RELIANCE, NIFTY)"
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
            <Chip color={T.cyan} onClick={fitChart} title="Fit the whole series back into view" aria-label="fit chart"
              style={{ fontSize: 9, padding: '1px 6px' }}>FIT</Chip>
            <Chip color={T.cyan} onClick={pngChart} title="Save the chart (both panes) as a PNG image" aria-label="download chart as png"
              style={{ fontSize: 9, padding: '1px 6px' }}>PNG ⤓</Chip>
            <Chip color={T.cyan} active={tall} onClick={() => setTall(v => !v)} aria-label={tall ? 'restore chart height' : 'expand chart panes to the window height'}
              title={tall ? 'Restore the standard pane height (Esc)' : 'Grow the panes to the window height (Esc restores)'}
              style={{ fontSize: 9, padding: '1px 6px' }}>{tall ? '✕ RESTORE' : '⛶'}</Chip>
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
        {/* M42: F&O overlays from the stored tables (daily timeframes) */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 5, flexWrap: 'wrap', marginBottom: 8 }} data-sd-chart-overlays>
          <span style={{ fontSize: 10, color: T.dim, letterSpacing: 1 }}>F&amp;O</span>
          <Chip active={showFut} color={T.amber} onClick={() => setShowFut(v => !v)} title="the near-month future's close on the price pane (nse_fo_daily)">FUT</Chip>
          <span style={{ width: 1, height: 14, background: T.border, margin: '0 4px' }} />
          <span style={{ fontSize: 10, color: T.dim, letterSpacing: 1 }}>LOWER PANE</span>
          {(['rsi', 'iv', 'oi', 'basis'] as LowerPane[]).map(k => (
            <Chip key={k} active={lower === k} color={T.cyan} onClick={() => { setLower(k); if (k === 'rsi' && !show.rsi) setShow(s => ({ ...s, rsi: true })); if (k !== 'rsi') setShow(s => ({ ...s, rsi: true })) }}>
              {k === 'rsi' ? 'RSI 14' : k === 'iv' ? 'IV30' : k === 'oi' ? 'OI' : 'BASIS'}
            </Chip>
          ))}
          {isIntraday && lower !== 'rsi' && <span style={{ fontSize: 10, color: T.amber }}>IV30 / OI / basis are daily series: switch to D, W or M to draw them</span>}
          {showFut && ovErr('future') && <span style={{ fontSize: 10, color: T.amber }}>FUT: {ovErr('future')}</span>}
          {data?.kind === 'eod' && (data.closeOnly ?? 0) > 0 && <span style={{ fontSize: 10, color: T.dim }}>{data.closeOnly} early bars are close-only (NSE index history)</span>}
        </div>

        {/* crosshair OHLC readout */}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap', fontFamily: T.mono,
                      fontVariantNumeric: 'tabular-nums', marginBottom: 6, minHeight: 24 }}>
          <span style={{ fontSize: 19, fontWeight: 700, color: T.bright }}>{px(shown?.c)}</span>
          <span style={{ fontSize: 12, fontWeight: 700, color: tone(chgPct) }}>{fmtPct(chgPct, 2)}</span>
          <span style={{ fontSize: 10, color: T.dim, letterSpacing: 1 }}>{shown ? chgLabel.toUpperCase() : ''}</span>
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
            {isIntraday ? 'BARS: BROKER TICKS (ICICI WS)' : isIndexChart ? 'BARS: NSE DAILY INDEX FILE' : 'BARS: DUCKDB EOD · YAHOO HISTORY'}
          </Label>
        </div>

        {error && <div style={{ marginBottom: 8 }}><ErrorBox error={error} onRetry={() => { void load() }} /></div>}
        {data?.kind === 'ticks' && data.coverage && bars.length > 0 && (
          <div style={{ marginBottom: 8 }}><Notice color={T.amber}>{data.coverage}.</Notice></div>
        )}
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
          <div ref={mainBox} style={{ width: '100%', height: mainH }} />
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
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', margin: '6px 0 2px', flexWrap: 'wrap' }}>
            <Label color={T.cyan}>{lower === 'rsi' ? 'RSI 14' : lower === 'iv' ? 'IV30' : lower === 'oi' ? 'OI' : 'BASIS'}</Label>
            <Label color={T.dim}>{lowerLegend[lower]}</Label>
            {lowerSrc && <SourceChip info={lowerSrc} />}
            {lowerKind && ovErr(lowerKind) && <span style={{ fontSize: 10, color: T.amber }}>{ovErr(lowerKind)}</span>}
            {lowerKind && <span style={{ fontSize: 10, color: T.dim }}>describes, does not predict</span>}
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

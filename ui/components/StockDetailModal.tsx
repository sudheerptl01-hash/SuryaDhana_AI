'use client'

import { Z } from '@/lib/z'
import { apiError } from '@/lib/errors'
import { useLiveTicks } from '@/lib/liveTicks'
import type { TickerFocus } from '@/lib/openTicker'
import clsx from 'clsx'
import { useEffect, useMemo, useState, useCallback } from 'react'
import { getStockDetail, getStockOHLCV, getDataIntraday, getDataOHLCV, getDataLiveQuote, getIndexDaily } from '@/lib/api'
import { useTheme } from '@/context/ThemeContext'
import { useLiveQuotes } from '@/context/AppContext'
import { IndicatorPriceChart } from './IndicatorPriceChart'
import { IndicatorMenu } from './IndicatorMenu'
import { defaultIndicators, type IndicatorConfig } from '@/lib/indicators'
import { ChartActions } from './terminal/ChartActions'
import { StockProfile } from './StockProfile'
import { PriceHistory } from './PriceHistory'
import { SeasonalityView } from './Seasonality'
import { EventBadge, SourceChip } from './terminal'
import { useFinancialsLatest } from '@/lib/useFinancials'
import { useSurveillance } from '@/lib/useSurveillance'
import { RiskChips } from './RiskChips'
import { daysUntil, useCorpEvents } from '@/lib/useCorpEvents'
import { useFeedState } from '@/components/shell/useFeed'
import { stockPriceMarker } from '@/lib/feedState'
import { lastNsePrint } from '@/lib/liveEvidence'

/**
 * The header's price line (CT-07, C2-performance-03): last price, ▲/▼ change and %, and what the price IS: LIVE
 * (broker ticks), DELAYED · <as of> (a delayed quote while NSE trades) or CLOSE <day> (NSE closed: the last
 * session's close), like the header's NIFTY chip: a fresh NSE print counts as "NSE trades" too, so a session the
 * calendar does not know (Muhurat) never reads CLOSE <day> while the header says ● NSE (round 4b; the rule is
 * lib/feedState.ts stockPriceMarker). The as-of is the quote's own time (broker tick, else the ICICI quote's ltt).
 * Neutral colours and a static dot unless the price is live; no endless pulse.
 * Display only: the price, change and % come from the same quote the window always used.
 */
/** Previous close implied by a quote's price and its % change (null when either is missing). */
function impliedPrev(price: number | null | undefined, pct: number | null | undefined): number | null {
  return price != null && pct != null && Number.isFinite(price) && Number.isFinite(pct) && pct > -100 ? price / (1 + pct / 100) : null
}

function priceLine(i: { price: number; prevClose: number | null; live: boolean; marketOpen: boolean; asOf: string | null; nseStamp: string | null }) {
  // change and % are measured from ONE previous close against the price shown (never a % from another source)
  const prev = i.prevClose != null && Number.isFinite(i.prevClose) && i.prevClose > 0 ? i.prevClose : null
  const chg = prev ? i.price - prev : null
  const pct = prev && chg != null ? (chg / prev) * 100 : null
  const marker = stockPriceMarker({ live: i.live, marketOpen: i.marketOpen, asOf: i.asOf, nseStamp: i.nseStamp, now: Date.now() })
  return { chg, pct, marker }
}

interface StockDetailModalProps {
  ticker: string | null
  onClose: () => void
  /** open on Profile (and scroll to FA / ERN) instead of the chart */
  focus?: TickerFocus | null
  /** Open this stock in another terminal window (contract K4: /?tab=<page>&sym=<SYM>); no button when absent. */
  onNewWindow?: () => void
}

type PeriodDays = 'intraday' | 5 | 30 | 90 | 252 | 756 | 1260
type ChartType = 'line' | 'candle'

// Extra history loaded before the visible window so 150/200-day averages draw from the first visible bar
const WARMUP_BARS = 200

const PERIODS: { label: string; days: PeriodDays }[] = [
  { label: 'Today', days: 'intraday' },
  { label: '5D',  days: 5 },
  { label: '1M',  days: 30 },
  { label: '3M',  days: 90 },
  { label: '1Y',  days: 252 },
  { label: '3Y',  days: 756 },
  { label: '5Y',  days: 1260 },
]

// ── Main modal ────────────────────────────────────────────────────────────────

/** Esc closes the stock window (C1-trader-ux-09) unless focus is in a text box or another handler took the key. */
function useEscapeToClose(active: boolean, onClose: () => void): void {
  useEffect(() => {
    if (!active) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return
      const el = e.target as HTMLElement | null
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable)) return
      e.preventDefault()
      onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [active, onClose])
}

export function StockDetailModal({ ticker, onClose, focus, onNewWindow }: StockDetailModalProps) {
  const { isDark }      = useTheme()
  useEscapeToClose(!!ticker, onClose)
  const { liveQuotes }  = useLiveQuotes()
  const liveQ           = ticker ? liveQuotes[ticker.toUpperCase()] : null

  const [detail, setDetail]             = useState<any>(null)
  const events = useCorpEvents()
  const { fin: headFin } = useFinancialsLatest(ticker ? [ticker.toUpperCase().replace(/\.NS$/, '')] : [])
  const risk = useSurveillance(ticker ? [ticker.toUpperCase().replace(/\.NS$/, '')] : [])
  const [loading, setLoading]           = useState(false)
  const [error, setError]               = useState<string | null>(null)
  // Open straight onto the chart — users want the chart, not the details, first.
  const [activeTab, setActiveTab]       = useState<'profile' | 'details' | 'chart' | 'hp' | 'seag'>('chart')
  const [ohlcv, setOhlcv]               = useState<any[]>([])
  const [chartLoading, setChartLoading] = useState(false)
  const [chartError, setChartError]     = useState<string | null>(null)
  const [period, setPeriod]             = useState<PeriodDays>(90)
  const [chartType, setChartType]       = useState<ChartType>('candle')
  const [isIntraday, setIsIntraday]     = useState(false)
  const [intradaySource, setIntradaySource] = useState<string | null>(null)
  const [prevClose, setPrevClose] = useState<number | null>(null)
  const [livePrice, setLivePrice]       = useState<number | null>(null)
  // Day for the intraday (5-min) chart — defaults to today; user can pick any trading day
  const [chartDay, setChartDay]         = useState<string>(() => new Date().toISOString().split('T')[0])
  // the shown quote's own exchange time (ICICI ltt) for the DELAYED · <time> marker (CT-07); broker ticks carry theirs.
  // Its previous close is the change base when that REST quote is all the window has (no tick, no socket quote).
  const [quoteAt, setQuoteAt]           = useState<string | null>(null)
  const [quotePrev, setQuotePrev]       = useState<number | null>(null)
  // Customizable indicator stack (defaults to the four classic moving averages)
  const [indicators, setIndicators]     = useState<IndicatorConfig[]>(defaultIndicators)

  useEffect(() => {
    if (!ticker) return
    setLoading(true)
    setError(null)
    setDetail(null)
    setActiveTab(focus === 'hp' || focus === 'seag' ? focus : focus ? 'profile' : 'chart')
    setLivePrice(null)
    setQuoteAt(null)
    setQuotePrev(null)
    // Fetch detail + live price in parallel
    Promise.all([
      getStockDetail(ticker),
      getDataLiveQuote(ticker).catch(() => null),
    ])
      .then(([detailRes, quoteRes]) => {
        setDetail(detailRes.data)
        const q = quoteRes?.data?.quote
        if (q) {
          const p = q.ltp ?? q.last_price ?? q.lastPrice ?? q.price
          if (p) {
            setLivePrice(Number(p))
            setQuoteAt(typeof q.ltt === 'string' ? q.ltt : null)
            const pc = Number(q.previous_close)
            setQuotePrev(Number.isFinite(pc) && pc > 0 ? pc : null)
          }
        }
      })
      .catch(err => setError(apiError(err, 'Failed to load stock detail')))
      .finally(() => setLoading(false))
  }, [ticker])

  // Merge WS live price into livePrice state
  useEffect(() => {
    if (liveQ?.ltp !== undefined) {
      setLivePrice(liveQ.ltp)
      if (typeof liveQ.raw?.ltt === 'string') setQuoteAt(liveQ.raw.ltt)
    }
  }, [liveQ?.ltp]) // eslint-disable-line react-hooks/exhaustive-deps

  // Broker websocket snapshot (2 s poll) beats the legacy WS value when it has this stock
  const tickBase = ticker ? ticker.toUpperCase().replace(/\.NS$/, '') : ''
  const liveT = useLiveTicks(tickBase ? [tickBase] : [])
  const tick = liveT.ticks[tickBase]
  useEffect(() => { if (tick?.price != null) setLivePrice(tick.price) }, [tick?.price])
  const priceChip: 'live' | 'delayed' | 'degraded' =
    liveT.state === 'live' && tick ? 'live' : liveT.state === 'degraded' ? 'degraded' : 'delayed'
  const { marketOpen } = useFeedState()
  const px = livePrice !== null
    ? priceLine({ price: livePrice,
                  prevClose: tick?.prev_close ?? impliedPrev(tick?.price, tick?.chg_pct)
                    ?? (typeof liveQ?.raw?.previous_close === 'number' ? liveQ.raw.previous_close : null) ?? impliedPrev(liveQ?.ltp, liveQ?.change_pct)
                    ?? quotePrev,
                  live: priceChip === 'live', marketOpen, asOf: tick?.as_of ?? quoteAt, nseStamp: lastNsePrint() })
    : null

  // the page behind the window must not scroll while it is open (F-006)
  useEffect(() => {
    if (!ticker) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = prev }
  }, [ticker])

  const fetchOHLCV = useCallback(async (p: PeriodDays) => {
    if (!ticker) return
    setChartLoading(true)
    setChartError(null)
    const intraday = p === 'intraday'
    setIsIntraday(intraday)
    try {
      // lightweight-charts requires yyyy-mm-dd — strip ISO time component if present
      const toDate = (v: any) => typeof v === 'string' ? v.split('T')[0] : v

      if (intraday) {
        // Use data-service proxy for intraday bars (5-min) for the selected day
        const res = await getDataIntraday(ticker, '5minute', chartDay)
        setIntradaySource(res.data?.source ?? null)
        setPrevClose(res.data?.previous_close ?? null)
        const rows = (res.data?.source === 'duckdb_daily' ? [] : res.data?.data || []).map((r: any) => ({
          date:   r.ts ?? toDate(r.date || r.datetime || r.timestamp),
          open:   r.open,  high:   r.high,
          low:    r.low,   close:  r.close,
          volume: r.volume ?? 0,
        })).filter((r: any) => r.date && r.close)
        if (rows.length === 0) {
          // Fallback: get last 10 days from data proxy ohlcv
          const fb = await getDataOHLCV(ticker)
          const d = (fb.data?.data || []).slice(-10).map((r: any) => ({
            date: toDate(r.date), open: r.open, high: r.high,
            low: r.low, close: r.close, volume: r.volume ?? 0,
          }))
          setOhlcv(d)
        } else {
          setOhlcv(rows)
        }
      } else {
        // Try data-service proxy first (richer data), fall back to ui-api stock endpoint
        try {
          const res = await getDataOHLCV(ticker)
          const all: any[] = res.data?.data || []
          const sliced = all.slice(-(Number(p) + WARMUP_BARS)).map((r: any) => ({
            date: toDate(r.date), open: r.open, high: r.high,
            low: r.low, close: r.close, volume: r.volume ?? 0,
          }))
          setOhlcv(sliced.length ? sliced : [])
        } catch {
          // Fallback to existing ui-api stock OHLCV endpoint
          const res = await getStockOHLCV(ticker, (p as number) + WARMUP_BARS)
          setOhlcv((res.data?.rows || []).map((r: any) => ({ ...r, date: toDate(r.date) })))
        }
      }
    } catch (err: any) {
      setChartError(apiError(err, 'Failed to load chart data'))
    } finally {
      setChartLoading(false)
    }
  }, [ticker, chartDay])

  useEffect(() => {
    if (activeTab === 'chart') fetchOHLCV(period)
  }, [activeTab, period, fetchOHLCV])

  // relative strength vs NIFTY 50 (daily charts): close ÷ NIFTY close, rebased to 100 at the first visible bar
  const [rsOn, setRsOn] = useState(false)
  const [nifty, setNifty] = useState<Map<string, number> | null>(null)
  useEffect(() => {
    if (!rsOn || nifty) return
    getIndexDaily('NIFTY50', 6000).then(r => setNifty(new Map(r.data.rows.map(x => [x.date, x.close])))).catch(() => setNifty(new Map()))
  }, [rsOn, nifty])
  const rsOverlay = useMemo(() => {
    if (!rsOn || !nifty || period === 'intraday' || !ohlcv.length) return null
    const pts = ohlcv.map(r => ({ time: String(r.date).slice(0, 10), s: r.close, n: nifty.get(String(r.date).slice(0, 10)) }))
      .filter((x): x is { time: string; s: number; n: number } => x.n != null && x.s > 0)
    const start = Math.max(0, pts.length - Number(period))
    const base = pts[start]
    if (!base) return null
    return { label: 'RS vs NIFTY', color: '#e5e7eb', data: pts.map(x => ({ time: x.time, value: (x.s / x.n) / (base.s / base.n) * 100 })) }
  }, [rsOn, nifty, period, ohlcv])

  if (!ticker) return null

  return (
    <div
      className="fixed inset-0 flex items-center justify-center backdrop-blur-sm p-0 md:p-4"
      style={{ zIndex: Z.modal, background: 'rgba(5,7,10,.7)', top: 'var(--shell-top, 0px)' }}
      onClick={e => e.target === e.currentTarget && onClose()}
      role="dialog" aria-modal="true" aria-label={`Stock window ${ticker}`} data-sd-stock-window=""
    >
      {/* <768px: full-height sheet (no rounded corners, no gutter); desktop: centered window */}
      <div className={clsx(
        'w-full max-w-6xl h-full max-h-full md:h-auto md:max-h-[92vh] overflow-y-auto rounded-none md:rounded-2xl border shadow-2xl',
        isDark ? 'bg-slate-900 border-slate-700' : 'bg-white border-gray-200',
      )}>
        {/* Header */}
        {/* wraps the actions below the identity when narrow (1100 px): the price never sits over ☆ PIN (CT-07) */}
        <div className={clsx(
          'sticky top-0 border-b px-6 py-4 flex flex-wrap justify-between items-center gap-x-4 gap-y-2 z-10',
          isDark ? 'bg-slate-900 border-slate-700' : 'bg-white border-gray-200',
        )}>
          <div className="flex items-center gap-3 min-w-0 flex-1" style={{ minWidth: 300 }}>
            <span style={{ fontFamily: 'var(--t-mono)', fontSize: 10, fontWeight: 700, letterSpacing: 1.5,
                           color: '#05070a', background: '#ffb000', padding: '3px 7px' }}>NSE</span>
            <div className="min-w-0">
              {/* wraps instead of running under the action buttons (event badges + MCAP chip can be wide) */}
              <div className="flex items-center flex-wrap gap-x-3 gap-y-1">
                <h2 className="text-xl font-bold" style={{ fontFamily: 'var(--t-display)', letterSpacing: 1.5, color: '#ffb000' }}>{ticker}</h2>
                {livePrice !== null && px && (
                  <span data-sd-price={px.marker} title={px.marker === 'LIVE' ? 'Broker websocket ticks (ICICI Breeze)'
                      : px.marker.startsWith('DELAYED') ? 'Delayed quote (not a broker tick): not a live price' : "NSE closed: the last session's close"}
                    style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: 'var(--t-mono)', fontSize: 13, fontWeight: 700,
                             padding: '1px 7px', whiteSpace: 'nowrap', border: `1px solid ${px.marker === 'LIVE' ? 'rgba(22,217,138,.55)' : '#2a3448'}`,
                             color: px.marker === 'LIVE' ? '#16d98a' : '#f2f5fa', background: px.marker === 'LIVE' ? 'rgba(22,217,138,.08)' : 'transparent' }}>
                    <span aria-hidden style={{ width: 6, height: 6, borderRadius: 6, flex: 'none', background: px.marker === 'LIVE' ? '#16d98a' : '#5c6678' }} />
                    ₹{livePrice.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    {px.chg != null && px.pct != null && (
                      <span style={{ fontSize: 11.5, fontWeight: 600, color: px.chg >= 0 ? '#16d98a' : '#ff4d5e' }}>
                        {px.chg >= 0 ? '▲' : '▼'} {Math.abs(px.chg).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        {' '}({px.pct >= 0 ? '+' : '−'}{Math.abs(px.pct).toFixed(2)}%)</span>
                    )}
                    <span style={{ fontSize: 9, fontWeight: 600, letterSpacing: 1, color: px.marker === 'LIVE' ? '#16d98a' : '#8a94a6' }}>{px.marker}</span>
                  </span>
                )}
                {livePrice !== null && <SourceChip state={priceChip} />}
                <RiskChips flags={risk[ticker.toUpperCase().replace(/\.NS$/, '')]} max={3} />
                {(events.get(ticker.toUpperCase()) ?? []).slice(0, 2).map(e => (
                  <EventBadge key={`${e.kind}-${e.event_date}`} kind={e.kind} date={e.event_date} days={daysUntil(e.event_date)} detail={e.detail} />
                ))}
                {(() => { const f = headFin[ticker.toUpperCase().replace(/\.NS$/, '')]
                  if (!f || (f.mcap == null && f.pe == null)) return null
                  return <span title="market cap (L = lakh crore) and P/E on the last four quarters, from NSE results filings · Profile → FA"
                    style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 10, letterSpacing: 0.6, padding: '1px 6px', border: '1px solid #2a3448', color: '#8a94a6', whiteSpace: 'nowrap' }}>
                    {f.mcap != null && <>₹{f.mcap >= 1e12 ? `${(f.mcap / 1e12).toFixed(2)}L` : Math.round(f.mcap / 1e7).toLocaleString('en-IN')} cr</>}
                    {f.pe != null && <> · <span style={{ color: '#ffb000' }}>{f.pe.toFixed(1)}×</span> P/E</>}
                  </span> })()}
              </div>
              {(detail?.company_name || detail?.fundamentals?.sector) && (
                <p className={clsx('text-xs', isDark ? 'text-slate-400' : 'text-gray-400')}>
                  {[detail?.company_name, detail?.fundamentals?.sector].filter(Boolean).join(' · ')}</p>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0 flex-wrap justify-end ml-auto">
            <ChartActions ticker={ticker} name={detail?.company_name} from="Stock detail" alertLayout="row"
              style={{ marginRight: 6 }} />
            <div className={clsx('flex items-center gap-1 rounded-lg p-1', isDark ? 'bg-slate-800' : 'bg-gray-100')}>
              <button
                onClick={() => setActiveTab('profile')}
                className={clsx(
                  'px-3 py-1.5 rounded-md text-xs font-semibold transition-all whitespace-nowrap',
                  activeTab === 'profile'
                    ? (isDark ? 'bg-slate-700 shadow text-amber-400' : 'bg-white shadow text-indigo-600')
                    : (isDark ? 'text-slate-400 hover:text-slate-200' : 'text-gray-500 hover:text-gray-700'),
                )}
                title="Ownership, insiders, deals, F&O, delivery (NSE files)"
              >
                Profile
              </button>
              <button
                onClick={() => setActiveTab('details')}
                className={clsx(
                  'px-3 py-1.5 rounded-md text-xs font-semibold transition-all whitespace-nowrap',
                  activeTab === 'details'
                    ? (isDark ? 'bg-slate-700 shadow text-amber-400' : 'bg-white shadow text-indigo-600')
                    : (isDark ? 'text-slate-400 hover:text-slate-200' : 'text-gray-500 hover:text-gray-700'),
                )}
                title="Data coverage and fundamentals snapshot"
              >
                Data
              </button>
              <button
                onClick={() => setActiveTab('chart')}
                className={clsx(
                  'px-3 py-1.5 rounded-md text-xs font-semibold transition-all whitespace-nowrap',
                  activeTab === 'chart'
                    ? (isDark ? 'bg-slate-700 shadow text-amber-400' : 'bg-white shadow text-indigo-600')
                    : (isDark ? 'text-slate-400 hover:text-slate-200' : 'text-gray-500 hover:text-gray-700'),
                )}
              >
                ▤ Chart
              </button>
              <button
                onClick={() => setActiveTab('hp')}
                className={clsx(
                  'px-3 py-1.5 rounded-md text-xs font-semibold transition-all whitespace-nowrap',
                  activeTab === 'hp'
                    ? (isDark ? 'bg-slate-700 shadow text-amber-400' : 'bg-white shadow text-indigo-600')
                    : (isDark ? 'text-slate-400 hover:text-slate-200' : 'text-gray-500 hover:text-gray-700'),
                )}
                title="Historical prices (HP): every session as traded, with delivery %"
              >
                HP
              </button>
              <button
                onClick={() => setActiveTab('seag')}
                className={clsx(
                  'px-3 py-1.5 rounded-md text-xs font-semibold transition-all whitespace-nowrap',
                  activeTab === 'seag'
                    ? (isDark ? 'bg-slate-700 shadow text-amber-400' : 'bg-white shadow text-indigo-600')
                    : (isDark ? 'text-slate-400 hover:text-slate-200' : 'text-gray-500 hover:text-gray-700'),
                )}
                title="Seasonality (SEAG): average return by calendar month"
              >
                SEAG
              </button>
            </div>
            {onNewWindow && (
              <button
                onClick={onNewWindow}
                title="Open this stock in a new window"
                aria-label={`Open ${ticker} in a new window`}
                style={{ fontFamily: 'var(--t-mono)', fontSize: 10, fontWeight: 700, letterSpacing: 1.2, color: '#39c6ff',
                         background: 'transparent', border: '1px solid #2a3448', padding: '5px 8px', cursor: 'pointer', whiteSpace: 'nowrap' }}
              >
                ⧉ NEW WINDOW
              </button>
            )}
            <button
              onClick={onClose}
              title="Close (Esc)"
              aria-label="Close the stock window"
              className={clsx(
                'text-xl leading-none w-7 h-7 flex items-center justify-center rounded-lg transition-colors',
                isDark ? 'text-slate-400 hover:text-slate-200 hover:bg-slate-700' : 'text-gray-400 hover:text-gray-700 hover:bg-gray-100',
              )}
            >
              ✕
            </button>
          </div>
        </div>

        <div className="p-6">
          {loading && (
            <div className="space-y-3">
              {Array(4).fill(0).map((_, i) => (
                <div key={i} className={clsx('h-14 animate-pulse rounded-xl', isDark ? 'bg-slate-800' : 'bg-gray-100')} />
              ))}
            </div>
          )}

          {error && (
            <div className="rounded-xl bg-rose-50 border border-rose-200 p-4 text-rose-600 text-sm">{error}</div>
          )}

          {/* ── Details Tab ─────────────────────────────────────────────── */}
          {!loading && !error && detail && activeTab === 'details' && (
            <div className="space-y-6">
              <Section title="OHLCV Data" isDark={isDark}>
                <div className="grid grid-cols-2 gap-3">
                  <Stat label="Total Rows" value={detail.ohlcv.total_rows.toLocaleString()} isDark={isDark} />
                  <Stat label="Data Density" value={`${detail.ohlcv.data_density_pct.toFixed(1)}%`} isDark={isDark} />
                  <div className="col-span-2">
                    <Stat label="Date Range" value={`${detail.ohlcv.first_date} → ${detail.ohlcv.latest_date}`} mono isDark={isDark} />
                  </div>
                  <Stat label="Missing Days" value={detail.ohlcv.missing_rows} isDark={isDark}
                    color={detail.ohlcv.missing_rows > 20 ? 'rose' : 'emerald'} />
                  <Stat label="Last Updated" value={`${detail.data_quality.days_since_update} day(s) ago`} isDark={isDark}
                    color={detail.data_quality.days_since_update <= 1 ? 'emerald' : 'amber'} />
                </div>
              </Section>

              {(detail.index_name || detail.nifty_bucket || detail.midcap_bucket) && (
                <Section title="Index Membership" isDark={isDark}>
                  <div className="grid grid-cols-2 gap-3">
                    <Stat label="Index" value={detail.index_name ?? '—'} isDark={isDark} />
                    <Stat label="Nifty Bucket" value={detail.nifty_bucket ? `Nifty ${detail.nifty_bucket}` : '—'} isDark={isDark} />
                    <div className="col-span-2">
                      <Stat label="Midcap Bucket" value={detail.midcap_bucket ? `Midcap ${detail.midcap_bucket}` : '—'} isDark={isDark} />
                    </div>
                  </div>
                </Section>
              )}

              {detail.fundamentals?.available && (
                <Section title="Fundamentals" isDark={isDark}>
                  <div className="grid grid-cols-2 gap-3">
                    <Stat label="P/E Ratio" value={fmt(detail.fundamentals.trailing_pe, '.2f')} isDark={isDark} />
                    <Stat label="P/B Ratio" value={fmt(detail.fundamentals.price_to_book, '.2f')} isDark={isDark} />
                    <Stat label="ROE" value={fmt(detail.fundamentals.roe, '%')} isDark={isDark} />
                    <Stat label="D/E Ratio" value={fmt(detail.fundamentals.debt_to_equity, '.2f')} isDark={isDark} />
                    <Stat label="Dividend Yield" value={fmt(detail.fundamentals.dividend_yield, '%')} isDark={isDark} />
                    <Stat label="Sector" value={detail.fundamentals.sector ?? '—'} isDark={isDark} />
                  </div>
                </Section>
              )}

              {detail.upcoming_events?.length > 0 && (
                <Section title="Upcoming Events" isDark={isDark}>
                  <div className="space-y-2">
                    {detail.upcoming_events.map((ev: any, i: number) => (
                      <div key={i} className={clsx(
                        'flex justify-between items-center rounded-lg border px-4 py-2.5',
                        isDark ? 'bg-slate-800 border-slate-700' : 'bg-gray-50 border-gray-200',
                      )}>
                        <span className={clsx('text-sm font-medium', isDark ? 'text-slate-200' : 'text-gray-700')}>{ev.type}</span>
                        <span className="text-xs font-mono text-indigo-500">{ev.date}</span>
                      </div>
                    ))}
                  </div>
                </Section>
              )}

              <Section title="Corporate History" isDark={isDark}>
                <div className="grid grid-cols-2 gap-3">
                  <Stat label="Dividends" value={detail.dividends.count} isDark={isDark} />
                  <Stat label="Stock Splits" value={detail.splits.count} isDark={isDark} />
                </div>
              </Section>

              <div className={clsx(
                'rounded-xl border p-4',
                detail.data_quality.overall === 'excellent' ? 'border-emerald-700 bg-emerald-900/20' :
                detail.data_quality.overall === 'good'      ? 'border-teal-700 bg-teal-900/20' :
                detail.data_quality.overall === 'fair'      ? 'border-amber-700 bg-amber-900/20' :
                                                              (isDark ? 'border-slate-700 bg-slate-800/30' : 'border-gray-200 bg-gray-50'),
              )}>
                <p className={clsx('text-xs font-medium mb-2', isDark ? 'text-slate-400' : 'text-gray-500')}>Data Health</p>
                <div className="flex items-center gap-4">
                  <div>
                    <p className={clsx('text-xs', isDark ? 'text-slate-400' : 'text-gray-400')}>Density</p>
                    <p className={clsx('text-lg font-black mt-0.5', isDark ? 'text-slate-100' : 'text-gray-900')}>
                      {detail.ohlcv.data_density_pct.toFixed(1)}%
                    </p>
                  </div>
                  <div className={clsx('w-px h-10', isDark ? 'bg-slate-700' : 'bg-gray-200')} />
                  <div>
                    <p className={clsx('text-xs', isDark ? 'text-slate-400' : 'text-gray-400')}>Last updated</p>
                    <p className={clsx('text-lg font-black mt-0.5',
                      detail.data_quality.days_since_update <= 1 ? 'text-emerald-500' :
                      detail.data_quality.days_since_update <= 3 ? 'text-amber-500' :
                      (isDark ? 'text-slate-300' : 'text-gray-600'),
                    )}>
                      {detail.data_quality.days_since_update}d ago
                    </p>
                  </div>
                  <div className={clsx('w-px h-10', isDark ? 'bg-slate-700' : 'bg-gray-200')} />
                  <div>
                    <p className={clsx('text-xs', isDark ? 'text-slate-400' : 'text-gray-400')}>Total rows</p>
                    <p className={clsx('text-lg font-black mt-0.5', isDark ? 'text-slate-100' : 'text-gray-900')}>
                      {detail.ohlcv.total_rows.toLocaleString()}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ── Chart Tab ─────────────────────────────────────────────── */}
          {activeTab === 'hp' && <PriceHistory ticker={ticker} />}
          {activeTab === 'seag' && <SeasonalityView symbol={ticker} />}
          {activeTab === 'profile' && <StockProfile ticker={ticker} focus={focus === 'fa' || focus === 'ern' ? focus : undefined} />}

          {activeTab === 'chart' && (
            <div className="space-y-4">
              {/* Controls */}
              <div className="flex items-center justify-between flex-wrap gap-2">
                <div className="flex items-center gap-2">
                  <p className={clsx('text-sm font-semibold', isDark ? 'text-slate-200' : 'text-gray-700')}>
                    {ticker} · {
                      period === 'intraday' ? 'Today (Intraday)' :
                      period <= 30  ? `${period}D` :
                      period === 90 ? '3M' :
                      period === 252 ? '1Y' :
                      period === 756 ? '3Y' : '5Y'
                    }
                  </p>
                  {isIntraday && (
                    <span className={clsx(
                      'flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full border',
                      intradaySource !== 'icici' ? (isDark ? 'border-slate-600 text-slate-300' : 'border-gray-300 text-gray-600')
                        : isDark ? 'bg-emerald-900/30 border-emerald-700/40 text-emerald-400' : 'bg-emerald-50 border-emerald-300 text-emerald-700',
                    )}>
                      {/* static dot (C2-performance-03): an idle stock window never repaints forever */}
                      <span className="w-1.5 h-1.5 rounded-full" style={{ background: intradaySource === 'icici' ? '#16d98a' : '#5c6678' }} />
                      {intradaySource === 'icici' ? 'ICICI LIVE' : intradaySource === 'nse' ? 'NSE · LTP 5-MIN (no volume)' : 'NO INTRADAY · LAST 10 DAYS'}
                    </span>
                  )}
                  {isIntraday && prevClose && ohlcv.length > 0 && typeof ohlcv[ohlcv.length - 1].date === 'number' && (() => {
                    const last = ohlcv[ohlcv.length - 1].close, chg = (last / prevClose - 1) * 100
                    return <span className="font-mono text-xs" style={{ color: chg >= 0 ? '#16d98a' : '#ff4d5e' }}>
                      {last.toFixed(2)} · {Math.abs(chg) < 0.005 ? '' : chg > 0 ? '+' : '−'}{Math.abs(chg).toFixed(2)}% <span style={{ color: '#8a94a6' }}>vs prev close {prevClose.toFixed(2)}</span></span>
                  })()}
                </div>
                <div className="flex items-center gap-2">
                  {/* Chart type toggle */}
                  <div className={clsx('flex items-center gap-1 rounded-lg p-1', isDark ? 'bg-slate-800' : 'bg-gray-100')}>
                    {(['line', 'candle'] as ChartType[]).map(ct => (
                      <button
                        key={ct}
                        onClick={() => setChartType(ct)}
                        className={clsx(
                          'px-2.5 py-1 rounded-md text-xs font-bold transition-all capitalize',
                          chartType === ct
                            ? (isDark ? 'bg-slate-700 shadow text-amber-400' : 'bg-white shadow text-indigo-600')
                            : (isDark ? 'text-slate-400 hover:text-slate-200' : 'text-gray-500 hover:text-gray-700'),
                        )}
                      >
                        {ct === 'line' ? 'Line' : 'Candle'}
                      </button>
                    ))}
                  </div>
                  {/* Period selector */}
                  <div className={clsx('flex items-center gap-1 rounded-lg p-1', isDark ? 'bg-slate-800' : 'bg-gray-100')}>
                    {PERIODS.map(({ label, days }) => (
                      <button
                        key={days}
                        onClick={() => setPeriod(days)}
                        className={clsx(
                          'px-2.5 py-1 rounded-md text-xs font-bold transition-all',
                          period === days
                            ? (isDark ? 'bg-slate-700 shadow text-amber-400' : 'bg-white shadow text-indigo-600')
                            : (isDark ? 'text-slate-400 hover:text-slate-200' : 'text-gray-500 hover:text-gray-700'),
                        )}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                  {/* Intraday day picker — 5-min chart for today or any chosen trading day */}
                  {period === 'intraday' && (
                    <div className={clsx('flex items-center gap-1.5 rounded-lg px-2 py-1', isDark ? 'bg-slate-800' : 'bg-gray-100')}>
                      <span className="text-xs">📅</span>
                      <input
                        type="date"
                        value={chartDay}
                        max={new Date().toISOString().split('T')[0]}
                        onChange={e => setChartDay(e.target.value)}
                        className={clsx('px-2 py-1 rounded-md text-xs font-mono outline-none border',
                          isDark ? 'bg-slate-700 border-slate-600 text-slate-200' : 'bg-white border-gray-300 text-gray-700')}
                      />
                    </div>
                  )}
                </div>
              </div>

              {/* Indicator toolbar — add / customize overlays + oscillators */}
              <div className={clsx('rounded-xl border px-2.5 py-2',
                isDark ? 'bg-slate-800/40 border-slate-700' : 'bg-gray-50 border-gray-200')}>
                <div className="flex items-center gap-3 flex-wrap">
                  <IndicatorMenu indicators={indicators} onChange={setIndicators} isDark={isDark} />
                  {period !== 'intraday' && (
                    <button onClick={() => setRsOn(v => !v)}
                      title="relative strength: the stock's close ÷ NIFTY 50's, rebased to 100 at the start of the window (rising = beating NIFTY)"
                      className={clsx('px-2.5 py-1 rounded-md text-[11px] font-semibold border transition-all',
                        rsOn ? 'border-violet-400 text-violet-300 bg-violet-900/30' : (isDark ? 'border-slate-600 text-slate-400 hover:text-slate-200' : 'border-gray-300 text-gray-500'))}>
                      RS vs NIFTY {rsOn ? '✓' : ''}
                    </button>)}
                </div>
              </div>

              {chartLoading && (
                <div className={clsx('h-72 animate-pulse rounded-xl flex items-center justify-center',
                  isDark ? 'bg-slate-800' : 'bg-gray-100',
                )}>
                  <span className={clsx('text-sm', isDark ? 'text-slate-400 animate-pulse' : 'text-gray-400')}>
                    Loading chart…
                  </span>
                </div>
              )}

              {chartError && (
                <div className="rounded-xl bg-amber-50 border border-amber-200 p-4 text-amber-700 text-sm">
                  {chartError}
                </div>
              )}

              {!chartLoading && !chartError && ohlcv.length > 0 && (
                <IndicatorPriceChart
                  bars={ohlcv.map(r => ({
                    time: r.date, open: r.open, high: r.high, low: r.low, close: r.close, volume: r.volume ?? 0,
                  }))}
                  chartType={chartType}
                  isDark={isDark}
                  indicators={indicators}
                  visibleBars={period === 'intraday' ? undefined : Number(period)}
                  refLine={period === 'intraday' && prevClose ? { price: prevClose, label: 'prev close' } : null}
                  overlay={rsOverlay}
                />
              )}

              {!chartLoading && !chartError && ohlcv.length === 0 && (
                <div className={clsx(
                  'rounded-xl border p-12 text-center',
                  isDark ? 'border-slate-700 bg-slate-800/30' : 'border-gray-200 bg-gray-50',
                )}>
                  <p className={clsx('text-sm', isDark ? 'text-slate-400' : 'text-gray-400')}>
                    No price history available for {ticker}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Sub-components ────────────────────────────────────────────────────────────

function Section({ title, children, isDark }: { title: string; children: React.ReactNode; isDark: boolean }) {
  return (
    <div>
      <h3 className={clsx('text-xs font-bold uppercase tracking-wider mb-3', isDark ? 'text-slate-400' : 'text-gray-400')}>
        {title}
      </h3>
      {children}
    </div>
  )
}

function Stat({ label, value, color = 'slate', mono = false, isDark }: {
  label: string; value: any; color?: 'slate' | 'emerald' | 'rose' | 'amber'; mono?: boolean; isDark: boolean
}) {
  const valueColors = {
    slate:   isDark ? 'text-slate-100' : 'text-gray-900',
    emerald: 'text-emerald-500',
    rose:    'text-rose-500',
    amber:   'text-amber-500',
  }
  return (
    <div className={clsx('rounded-xl border px-4 py-3', isDark ? 'bg-slate-800/50 border-slate-700' : 'bg-gray-50 border-gray-200')}>
      <p className={clsx('text-xs', isDark ? 'text-slate-400' : 'text-gray-400')}>{label}</p>
      <p className={clsx('text-base font-bold mt-0.5', mono ? 'font-mono text-sm' : '', valueColors[color])}>
        {value ?? '—'}
      </p>
    </div>
  )
}

function fmt(val: number | null | undefined, format: string): string {
  if (val === null || val === undefined) return '—'
  if (format === '%') return `${(val * 100).toFixed(2)}%`
  if (format === '.2f') return val.toFixed(2)
  return String(val)
}

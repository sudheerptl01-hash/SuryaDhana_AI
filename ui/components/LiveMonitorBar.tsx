'use client'

/**
 * LiveMonitorBar — Horizontal ticker bar showing:
 *  - NIFTY 50 live index price (polled every 5s from /api/monitor/live/nifty)
 *  - Watchlist stocks with live prices from the WebSocket
 *  - Flash green/red animation on price change
 *  - WS connection indicator
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import { useLiveQuotes, useWatchlist } from '@/context/AppContext'
import { monitorLiveNifty } from '@/lib/api'

interface Props {
  isDark?: boolean
}

// ── Price flash hook ──────────────────────────────────────────────────────────

function usePriceFlash(price: number | undefined): 'up' | 'down' | null {
  const [flash, setFlash]   = useState<'up' | 'down' | null>(null)
  const prevPriceRef        = useRef<number | undefined>(undefined)

  useEffect(() => {
    if (price === undefined) return
    const prev = prevPriceRef.current
    if (prev !== undefined && price !== prev) {
      const dir = price > prev ? 'up' : 'down'
      setFlash(dir)
      const id = setTimeout(() => setFlash(null), 800)
      prevPriceRef.current = price
      return () => clearTimeout(id)
    }
    prevPriceRef.current = price
  }, [price])

  return flash
}

// ── NIFTY chip ────────────────────────────────────────────────────────────────

function NiftyChip({ isDark }: { isDark: boolean }) {
  const { liveQuotes } = useLiveQuotes()
  const [httpNifty, setHttpNifty] = useState<any>(null)

  // Poll HTTP fallback every 5s in case WS isn't publishing NIFTY
  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      try {
        const res = await monitorLiveNifty()
        if (!cancelled) setHttpNifty(res.data)
      } catch { /* silent */ }
    }
    poll()
    const id = setInterval(poll, 5000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  // Prefer WS quote, fall back to HTTP
  const wsQuote = liveQuotes['NIFTY'] || liveQuotes['NSEI']
  const record  = wsQuote?.raw || httpNifty?.record?.payload || httpNifty?.record || null
  const ltp     = wsQuote?.ltp ?? record?.ltp ?? record?.last_price ?? record?.close ?? null
  const flash   = usePriceFlash(ltp ?? undefined)

  const chg    = wsQuote?.change   ?? record?.change   ?? null
  const chgPct = wsQuote?.change_pct ?? record?.change_pct ?? null
  const isUp   = chg !== null ? chg >= 0 : null

  return (
    <div className={clsx(
      'flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-mono font-bold transition-colors duration-100',
      isDark ? 'bg-slate-800/60 border-slate-700/60' : 'bg-gray-50 border-gray-200',
      flash === 'up'   && (isDark ? 'bg-emerald-900/40 border-emerald-600/50' : 'bg-emerald-50 border-emerald-300'),
      flash === 'down' && (isDark ? 'bg-rose-900/30    border-rose-600/50'   : 'bg-rose-50    border-rose-300'),
    )}>
      <span className={clsx('text-[10px] tracking-widest', isDark ? 'text-slate-400' : 'text-gray-400')}>NIFTY</span>
      {ltp !== null ? (
        <>
          <span className={clsx(
            'tabular-nums font-black',
            flash === 'up'   ? 'text-emerald-400' :
            flash === 'down' ? 'text-rose-400'    :
            isDark ? 'text-slate-100' : 'text-gray-900',
          )}>
            {Number(ltp).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
          {chgPct !== null && (
            <span className={clsx(
              'text-[10px] font-semibold px-1.5 py-0.5 rounded-md',
              isUp
                ? (isDark ? 'bg-emerald-900/50 text-emerald-400' : 'bg-emerald-100 text-emerald-700')
                : (isDark ? 'bg-rose-900/30    text-rose-400'    : 'bg-rose-100    text-rose-600'),
            )}>
              {isUp ? '+' : ''}{Number(chgPct).toFixed(2)}%
            </span>
          )}
        </>
      ) : (
        <span className={clsx('text-[10px]', isDark ? 'text-slate-500' : 'text-gray-400')}>—</span>
      )}
    </div>
  )
}

// ── Watchlist ticker chip ─────────────────────────────────────────────────────

function WatchlistChip({ ticker, isDark }: { ticker: string; isDark: boolean }) {
  const { liveQuotes } = useLiveQuotes()
  const quote  = liveQuotes[ticker.toUpperCase()]
  const ltp    = quote?.ltp
  const chgPct = quote?.change_pct
  const flash  = usePriceFlash(ltp)
  const isUp   = chgPct !== undefined ? chgPct >= 0 : null

  return (
    <div className={clsx(
      'flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-xs font-mono transition-colors duration-100',
      isDark ? 'bg-slate-800/50 border-slate-700/40' : 'bg-gray-50 border-gray-200',
      flash === 'up'   && (isDark ? 'bg-emerald-900/30 border-emerald-600/40' : 'bg-emerald-50 border-emerald-200'),
      flash === 'down' && (isDark ? 'bg-rose-900/20    border-rose-600/40'    : 'bg-rose-50    border-rose-200'),
    )}>
      <span className={clsx('font-bold', isDark ? 'text-amber-400' : 'text-indigo-600')}>
        {ticker}
      </span>
      {ltp !== undefined ? (
        <>
          <span className={clsx(
            'tabular-nums font-semibold',
            flash === 'up'   ? 'text-emerald-400' :
            flash === 'down' ? 'text-rose-400'    :
            isDark ? 'text-slate-200' : 'text-gray-800',
          )}>
            {Number(ltp).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
          {isUp !== null && chgPct !== undefined && (
            <span className={clsx(
              'text-[10px] font-semibold',
              isUp ? (isDark ? 'text-emerald-400' : 'text-emerald-600') : (isDark ? 'text-rose-400' : 'text-rose-600'),
            )}>
              {isUp ? '▲' : '▼'} {Math.abs(chgPct).toFixed(2)}%
            </span>
          )}
        </>
      ) : (
        <span className={clsx('text-[10px]', isDark ? 'text-slate-600' : 'text-gray-400')}>—</span>
      )}
    </div>
  )
}

// ── WS status indicator ───────────────────────────────────────────────────────

function WsIndicator({ connected, isDark }: { connected: boolean; isDark: boolean }) {
  return (
    <div
      className={clsx(
        'flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-[10px] font-semibold font-mono',
        connected
          ? (isDark ? 'bg-emerald-900/30 border-emerald-700/40 text-emerald-400' : 'bg-emerald-50 border-emerald-200 text-emerald-700')
          : (isDark ? 'bg-slate-800/40   border-slate-700/30   text-slate-500'   : 'bg-gray-50   border-gray-200   text-gray-400'),
      )}
      title={connected ? 'WebSocket live' : 'WebSocket reconnecting…'}
    >
      <span className={clsx('w-1.5 h-1.5 rounded-full', connected ? 'bg-emerald-400 animate-pulse' : 'bg-slate-500')} />
      {connected ? 'LIVE' : 'RECONNECTING'}
    </div>
  )
}

// ── Main bar ──────────────────────────────────────────────────────────────────

export function LiveMonitorBar({ isDark = true }: Props) {
  const { watchlist } = useWatchlist()
  const { wsConnected } = useLiveQuotes()

  // Only render if there's something to show
  if (watchlist.length === 0 && !wsConnected) return null

  return (
    <div className={clsx(
      'w-full px-4 py-2 border-b flex items-center gap-2 overflow-x-auto',
      isDark ? 'border-slate-800/60 bg-slate-900/40' : 'border-gray-100 bg-gray-50/80',
    )}>
      {/* WS connection indicator */}
      <WsIndicator connected={wsConnected} isDark={isDark} />

      {/* Divider */}
      <span className={clsx('text-xs', isDark ? 'text-slate-700' : 'text-gray-300')}>|</span>

      {/* NIFTY index */}
      <NiftyChip isDark={isDark} />

      {/* Watchlist tickers */}
      {watchlist.length > 0 && (
        <>
          <span className={clsx('text-xs', isDark ? 'text-slate-700' : 'text-gray-300')}>|</span>
          <span className={clsx('text-[10px] font-bold uppercase tracking-wider shrink-0', isDark ? 'text-slate-500' : 'text-gray-400')}>
            Watchlist
          </span>
          {watchlist.map(ticker => (
            <WatchlistChip key={ticker} ticker={ticker} isDark={isDark} />
          ))}
        </>
      )}
    </div>
  )
}

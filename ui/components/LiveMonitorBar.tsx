'use client'

/**
 * LiveMonitorBar: slim WATCHLIST line under the terminal header. Shows each watched
 * stock with its live price from the ICICI websocket (flashes green/red on ticks).
 * NIFTY lives in the header, so it isn't repeated here. Hidden when the watchlist is empty.
 */
import { useEffect, useRef, useState } from 'react'
import { useLiveQuotes, useWatchlist } from '@/context/AppContext'
import { T } from '@/components/terminal'
import { socketChip } from '@/lib/feedState'
import { useFeedState } from '@/components/shell/useFeed'

function useFlash(price: number | undefined): 'up' | 'down' | null {
  const [flash, setFlash] = useState<'up' | 'down' | null>(null)
  const prev = useRef<number | undefined>(undefined)
  useEffect(() => {
    if (price === undefined) return
    if (prev.current !== undefined && price !== prev.current) {
      setFlash(price > prev.current ? 'up' : 'down')
      const id = setTimeout(() => setFlash(null), 800)
      prev.current = price
      return () => clearTimeout(id)
    }
    prev.current = price
  }, [price])
  return flash
}

function Ticker({ ticker, onRemove }: { ticker: string; onRemove: () => void }) {
  const { liveQuotes } = useLiveQuotes()
  const q = liveQuotes[ticker.toUpperCase()]
  const flash = useFlash(q?.ltp)
  const c = q?.change_pct
  return (
    <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 7, padding: '0 12px', borderRight: `1px solid ${T.border}`,
                   background: flash === 'up' ? 'rgba(22,217,138,.12)' : flash === 'down' ? 'rgba(255,77,94,.12)' : 'transparent',
                   transition: 'background .3s', height: '100%', alignSelf: 'stretch', lineHeight: '24px' }}>
      <span style={{ color: T.amber, fontWeight: 600, fontSize: 11 }}>{ticker}</span>
      <span style={{ color: T.text, fontSize: 11 }}>
        {q?.ltp != null ? Number(q.ltp).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'}
      </span>
      {c != null && <span style={{ fontSize: 10, color: c >= 0 ? T.green : T.red }}>{c >= 0 ? '▲' : '▼'} {Math.abs(c).toFixed(2)}%</span>}
      <button onClick={onRemove} title={`Remove ${ticker} from watchlist`}
        style={{ background: 'none', border: 'none', color: T.dim, cursor: 'pointer', fontSize: 10, padding: 0 }}>×</button>
    </span>
  )
}

export function LiveMonitorBar(_: { isDark?: boolean }) {
  const { watchlist, removeFromWatchlist } = useWatchlist()
  const { wsConnected } = useLiveQuotes()
  const feed = useFeedState()
  if (watchlist.length === 0) return null
  // never 'STREAMING' on a closed market or while the link is down (C1-trader-ux-13, lib/feedState.ts)
  const chip = socketChip({ connected: wsConnected, ...feed, live: '● STREAMING', offline: '◌ WS RECONNECTING' })
  return (
    <div style={{ display: 'flex', alignItems: 'center', height: 24, borderBottom: `1px solid ${T.border}`, background: '#06080c',
                  overflowX: 'auto', whiteSpace: 'nowrap', fontFamily: T.mono }}>
      <span style={{ background: T.cyan, color: T.bg, fontSize: 9, fontWeight: 700, letterSpacing: 1.2, padding: '0 8px',
                     height: '100%', display: 'flex', alignItems: 'center', flex: 'none' }}>WATCHLIST</span>
      <span title={chip.title} style={{ fontSize: 9, color: chip.tone === 'live' ? T.green : chip.tone === 'closed' ? T.muted : T.dim,
                                        padding: '0 10px', letterSpacing: 1, flex: 'none' }}>
        {chip.text}
      </span>
      {watchlist.map(t => <Ticker key={t} ticker={t} onRemove={() => removeFromWatchlist(t)} />)}
    </div>
  )
}

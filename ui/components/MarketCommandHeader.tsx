'use client'

/**
 * MarketCommandHeader — NSE Operations Center command strip.
 *
 * Visual language: ISRO mission control × Bloomberg terminal.
 * Chakra Petch (display) + JetBrains Mono (data).
 * Live NIFTY price with oscilloscope waveform behind it.
 * Service health capsules.  IST clock.  Pulsing corona logo.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import { useLiveQuotes, useDataServiceStatus, useWatchlist } from '@/context/AppContext'
import { useTheme } from '@/context/ThemeContext'

// ── IST Clock ─────────────────────────────────────────────────────────────────

function ISTClock() {
  const [time, setTime] = useState('')
  const [date, setDate] = useState('')
  useEffect(() => {
    const tick = () => {
      const now = new Date()
      const ist = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }))
      setTime(ist.toLocaleTimeString('en-IN', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }))
      setDate(ist.toLocaleDateString('en-IN', { weekday: 'short', day: '2-digit', month: 'short' }))
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [])

  const h = Number(time.slice(0, 2))
  const isOpen = h >= 9 && h < 16  // NSE 9:15–15:30 IST (approximated)

  return (
    <div className="flex flex-col items-end gap-0.5 select-none">
      <div className="flex items-center gap-2">
        <div className={clsx(
          'w-1.5 h-1.5 rounded-full',
          isOpen ? 'bg-jade animate-pulse' : 'bg-slate-600'
        )} />
        <span className={clsx(
          'text-[10px] font-semibold tracking-widest uppercase',
          isOpen ? 'text-jade' : 'text-slate-500'
        )}>
          {isOpen ? 'NSE OPEN' : 'MARKET CLOSED'}
        </span>
      </div>
      <span className="text-data font-mono text-sm tabular-nums font-bold tracking-tight">{time}</span>
      <span className="text-[10px] text-label font-mono uppercase tracking-widest">{date} IST</span>
    </div>
  )
}

// ── Oscilloscope waveform (CSS-animated SVG) ──────────────────────────────────

function OscilloscopeWave({ ticking }: { ticking: boolean }) {
  return (
    <svg
      viewBox="0 0 240 48"
      xmlns="http://www.w3.org/2000/svg"
      className="absolute inset-0 w-full h-full opacity-25 pointer-events-none"
      preserveAspectRatio="none"
    >
      <defs>
        <linearGradient id="waveGrad" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%"   stopColor="#F5A623" stopOpacity="0" />
          <stop offset="30%"  stopColor="#F5A623" stopOpacity="0.9" />
          <stop offset="70%"  stopColor="#F5A623" stopOpacity="0.9" />
          <stop offset="100%" stopColor="#F5A623" stopOpacity="0" />
        </linearGradient>
        <filter id="waveGlow">
          <feGaussianBlur stdDeviation="1.5" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      <path
        d="M0,24 L20,24 L25,8 L30,40 L35,12 L40,36 L45,20 L50,28 L55,24 L70,24 L75,6 L80,42 L85,10 L90,38 L95,16 L100,32 L105,24 L120,24 L125,8 L130,40 L135,14 L140,34 L145,18 L150,30 L155,24 L170,24 L175,7 L180,41 L185,11 L190,37 L195,17 L200,31 L205,24 L240,24"
        fill="none"
        stroke="url(#waveGrad)"
        strokeWidth="1.5"
        filter="url(#waveGlow)"
        className={ticking ? 'wave-sweep' : ''}
      />
      <style>{`
        @keyframes waveSweep {
          0%   { stroke-dashoffset: 800; opacity: 0.4; }
          30%  { opacity: 1; }
          70%  { opacity: 1; }
          100% { stroke-dashoffset: 0; opacity: 0.4; }
        }
        .wave-sweep {
          stroke-dasharray: 800;
          animation: waveSweep 2.4s cubic-bezier(0.4, 0, 0.2, 1) infinite;
        }
      `}</style>
    </svg>
  )
}

// ── NIFTY price panel ─────────────────────────────────────────────────────────

function NiftyPanel() {
  const { liveQuotes, wsConnected } = useLiveQuotes()
  const [httpNifty, setHttpNifty] = useState<any>(null)
  const [ticking, setTicking] = useState(false)
  const prevLtpRef  = useRef<number | undefined>(undefined)
  const tickTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      try {
        const res = await fetch('/api/data/live/index/nifty')
        if (!cancelled && res.ok) {
          const d = await res.json()
          setHttpNifty(d)
        }
      } catch { /* silent */ }
    }
    poll()
    const id = setInterval(poll, 5000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  const wsQuote  = liveQuotes['NIFTY'] || liveQuotes['NSEI']
  const httpRec  = (() => {
    const p = httpNifty?.record?.payload
    if (!p) return null
    if (typeof p === 'string') { try { return JSON.parse(p) } catch { return null } }
    return p
  })()
  const ltp      = wsQuote?.ltp ?? httpRec?.ltp ?? null
  const prevClose = wsQuote?.raw?.previous_close ?? httpRec?.previous_close ?? null
  const change    = ltp != null && prevClose != null ? ltp - prevClose : wsQuote?.change ?? null
  const changePct = wsQuote?.change_pct ?? wsQuote?.raw?.ltp_percent_change ?? httpRec?.ltp_percent_change ?? null
  const isUp      = change != null ? change >= 0 : null
  const high      = wsQuote?.raw?.high ?? httpRec?.high ?? null
  const low       = wsQuote?.raw?.low  ?? httpRec?.low  ?? null
  const open      = wsQuote?.raw?.open ?? httpRec?.open ?? null

  // Trigger waveform sweep on each new tick
  useEffect(() => {
    if (ltp === undefined || ltp === null) return
    if (prevLtpRef.current !== ltp) {
      prevLtpRef.current = ltp
      setTicking(true)
      if (tickTimerRef.current) clearTimeout(tickTimerRef.current)
      tickTimerRef.current = setTimeout(() => setTicking(false), 2500)
    }
  }, [ltp])

  return (
    <div className="relative flex items-center gap-6 px-5 py-3 overflow-hidden" style={{ minWidth: 320 }}>
      {/* Oscilloscope waveform backdrop */}
      <OscilloscopeWave ticking={ticking || wsConnected} />

      {/* Main price block */}
      <div className="relative z-10 flex flex-col gap-0.5">
        <div className="flex items-baseline gap-2">
          <span className="text-label text-[10px] font-semibold tracking-widest uppercase">NIFTY 50</span>
          <span className={clsx(
            'text-[9px] font-semibold tracking-wider px-1.5 py-0.5 rounded border',
            wsConnected
              ? 'text-jade border-jade/40 bg-jade/10'
              : 'text-slate-500 border-slate-700 bg-slate-800/50'
          )}>
            {wsConnected ? '⬤ LIVE' : '◌ POLL'}
          </span>
        </div>
        <div className={clsx(
          'text-4xl font-black tabular-nums tracking-tight transition-colors duration-300',
          ticking
            ? isUp === false ? 'text-crimson' : 'text-jade'
            : 'text-bright',
        )}>
          {ltp != null
            ? ltp.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
            : '——.——'}
        </div>
        <div className="flex items-center gap-3">
          {changePct != null && (
            <span className={clsx(
              'flex items-center gap-1 text-sm font-bold tabular-nums',
              isUp ? 'text-jade' : 'text-crimson'
            )}>
              {isUp ? '▲' : '▼'}
              {Math.abs(Number(changePct)).toFixed(2)}%
            </span>
          )}
          {change != null && (
            <span className={clsx('text-xs font-semibold tabular-nums', isUp ? 'text-jade/70' : 'text-crimson/70')}>
              {change >= 0 ? '+' : ''}{change.toFixed(2)}
            </span>
          )}
        </div>
      </div>

      {/* OHLC mini-stats */}
      {(open || high || low || prevClose) && (
        <div className="relative z-10 flex flex-col gap-1 border-l border-border-dim pl-5">
          {[
            { label: 'O', value: open },
            { label: 'H', value: high },
            { label: 'L', value: low },
            { label: 'PC', value: prevClose },
          ].map(({ label, value }) => value != null && (
            <div key={label} className="flex items-baseline gap-1.5">
              <span className="text-[9px] text-label font-semibold tracking-wider w-4">{label}</span>
              <span className="text-[11px] text-data font-mono tabular-nums">
                {Number(value).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Service health capsules ───────────────────────────────────────────────────

function ServiceCapsule({ name, ok, detail }: { name: string; ok: boolean | null; detail?: string }) {
  return (
    <div
      title={detail || name}
      className={clsx(
        'flex items-center gap-1.5 px-2.5 py-1 rounded border text-[9px] font-semibold tracking-wider uppercase cursor-default select-none',
        ok === true  ? 'border-jade/30 bg-jade/8 text-jade/80' :
        ok === false ? 'border-crimson/30 bg-crimson/8 text-crimson/60' :
                       'border-border-dim bg-transparent text-label'
      )}
    >
      <span className={clsx(
        'w-1 h-1 rounded-full',
        ok === true  ? 'bg-jade animate-pulse' :
        ok === false ? 'bg-crimson' :
                       'bg-slate-600'
      )} />
      {name}
    </div>
  )
}

// ── Watchlist ticker strip ────────────────────────────────────────────────────

function usePriceFlash(ltp: number | undefined): 'up' | 'down' | null {
  const [flash, setFlash] = useState<'up' | 'down' | null>(null)
  const prev = useRef<number | undefined>(undefined)
  useEffect(() => {
    if (ltp == null) return
    if (prev.current != null && ltp !== prev.current) {
      setFlash(ltp > prev.current ? 'up' : 'down')
      const t = setTimeout(() => setFlash(null), 700)
      prev.current = ltp
      return () => clearTimeout(t)
    }
    prev.current = ltp
  }, [ltp])
  return flash
}


// ── Main Header ───────────────────────────────────────────────────────────────

interface Props {
  onRefresh:   () => void
  refreshing:  boolean
  totalStocks: number
  latestDate?: string
  activeTab:   string
  tabs: { id: string; label: string; badge?: number }[]
  onTabChange: (id: string) => void
}

export function MarketCommandHeader({
  onRefresh, refreshing, totalStocks, latestDate, activeTab, tabs, onTabChange,
}: Props) {
  const { isDark, toggleTheme } = useTheme()
  const { wsConnected } = useLiveQuotes()
  const { dataServiceStatus } = useDataServiceStatus()

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Chakra+Petch:ital,wght@0,300;0,400;0,600;0,700;1,300&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

        :root {
          --bg-void:    #030810;
          --bg-deep:    #050D1A;
          --bg-panel:   #070E1B;
          --border-dim: #111E30;
          --border-med: #1A2D44;
          --border-hot: #F5A623;
          --amber-hot:  #F5A623;
          --amber-dim:  #7A5010;
          --jade:       #00C896;
          --crimson:    #FF3B47;
          --data:       #7DA4BE;
          --label:      #3D5872;
          --bright:     #C8DCF0;
          --white:      #E6EFF8;
        }

        .font-display  { font-family: 'Chakra Petch', 'Chakra Petch', sans-serif; }
        .font-data     { font-family: 'JetBrains Mono', 'Courier New', monospace; }

        .text-jade    { color: var(--jade); }
        .text-crimson { color: var(--crimson); }
        .text-data    { color: var(--data); }
        .text-label   { color: var(--label); }
        .text-bright  { color: var(--bright); }
        .text-white-sd { color: var(--white); }

        .bg-jade\\/8 { background-color: rgba(0,200,150,0.08); }
        .bg-crimson\\/8 { background-color: rgba(255,59,71,0.08); }
        .border-jade\\/30 { border-color: rgba(0,200,150,0.3); }
        .border-jade\\/40 { border-color: rgba(0,200,150,0.4); }
        .border-crimson\\/30 { border-color: rgba(255,59,71,0.3); }
        .bg-jade\\/10 { background-color: rgba(0,200,150,0.1); }
        .bg-jade\\/20 { background-color: rgba(0,200,150,0.2); }
        .border-border-dim { border-color: var(--border-dim); }
        .bg-void { background-color: var(--bg-void); }
        .bg-deep { background-color: var(--bg-deep); }

        /* Diagonal grid overlay (CSS only) */
        .cmd-grid-bg {
          background-image:
            repeating-linear-gradient(
              -45deg,
              transparent,
              transparent 20px,
              rgba(17,30,48,0.35) 20px,
              rgba(17,30,48,0.35) 21px
            );
        }

        /* Sun corona pulse */
        @keyframes corona {
          0%, 100% { box-shadow: 0 0 0 0 rgba(245,166,35,0.2), 0 0 0 0 rgba(245,166,35,0.1); }
          50%       { box-shadow: 0 0 12px 3px rgba(245,166,35,0.35), 0 0 30px 8px rgba(245,166,35,0.12); }
        }
        .sun-corona { animation: corona 2.8s ease-in-out infinite; }

        /* Amber radial bloom behind logo */
        .amber-bloom {
          background: radial-gradient(ellipse 140px 80px at center, rgba(245,166,35,0.08) 0%, transparent 70%);
        }

        /* Tab sliding indicator */
        .tab-indicator {
          position: absolute;
          bottom: -1px;
          height: 2px;
          background: var(--amber-hot);
          border-radius: 2px 2px 0 0;
          box-shadow: 0 0 8px rgba(245,166,35,0.6);
          transition: left 0.25s cubic-bezier(0.4,0,0.2,1), width 0.25s cubic-bezier(0.4,0,0.2,1);
        }

        /* Scanline overlay */
        .scanline::after {
          content: '';
          position: absolute;
          inset: 0;
          background: repeating-linear-gradient(
            0deg,
            transparent,
            transparent 2px,
            rgba(0,0,0,0.04) 2px,
            rgba(0,0,0,0.04) 4px
          );
          pointer-events: none;
          z-index: 1;
        }

        /* Glowing amber separator line */
        .amber-sep {
          border-bottom: 1px solid rgba(245,166,35,0.08);
          box-shadow: 0 1px 0 rgba(245,166,35,0.04);
        }

        .market-header-bg {
          background: linear-gradient(
            to bottom,
            rgba(3,8,16,1) 0%,
            rgba(5,13,26,0.97) 60%,
            rgba(5,13,26,0.92) 100%
          );
          backdrop-filter: blur(20px) saturate(1.4);
          -webkit-backdrop-filter: blur(20px) saturate(1.4);
        }
      `}</style>

      <header className="sticky top-0 z-50 scanline amber-sep">
        <div className="market-header-bg cmd-grid-bg">

          {/* ── Top strip ─────────────────────────────────────────────── */}
          <div className="w-full px-4 lg:px-6 py-3 flex items-stretch gap-0">

            {/* ── LOGO ────────────────────────────────────────────────── */}
            <div className="flex items-center gap-4 pr-5 border-r border-border-dim amber-bloom">
              {/* Sun icon */}
              <div className="relative flex-shrink-0">
                <div
                  className={clsx(
                    'w-12 h-12 rounded-full flex items-center justify-center text-2xl select-none sun-corona',
                    'bg-gradient-to-br from-amber-400 via-amber-500 to-orange-600 shadow-lg'
                  )}
                  style={{ boxShadow: '0 0 20px rgba(245,166,35,0.3)' }}
                >
                  ☀
                </div>
                {/* Live pulse ring */}
                {wsConnected && (
                  <span className="absolute -top-0.5 -right-0.5 w-3.5 h-3.5 rounded-full border-2 border-void bg-jade flex items-center justify-center">
                    <span className="w-1.5 h-1.5 rounded-full bg-jade animate-pulse" />
                  </span>
                )}
              </div>

              {/* Brand text */}
              <div className="flex flex-col gap-0.5">
                <h1
                  className="font-display text-2xl font-bold tracking-tight text-white-sd"
                  style={{ letterSpacing: '0.04em', color: 'var(--white)' }}
                >
                  SURYADHANA
                </h1>
                <p
                  className="font-display text-[10px] font-light tracking-widest uppercase"
                  style={{ color: 'var(--amber-hot)', letterSpacing: '0.18em' }}
                >
                  NSE QUANT · XGBOOST + RL
                </p>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="font-data text-[9px] text-label tabular-nums">
                    {totalStocks.toLocaleString()} stocks
                  </span>
                  {latestDate && (
                    <>
                      <span className="text-[9px] text-label opacity-40">·</span>
                      <span className="font-data text-[9px] text-label tabular-nums">{latestDate}</span>
                    </>
                  )}
                </div>
              </div>
            </div>

            {/* ── NIFTY live price panel ───────────────────────────── */}
            <div className="flex-1 border-r border-border-dim font-data">
              <NiftyPanel />
            </div>

            {/* ── Right controls ────────────────────────────────────── */}
            <div className="flex items-center gap-4 pl-5">
              {/* Service health */}
              <div className="flex flex-col gap-1.5">
                <ServiceCapsule
                  name="DATA"
                  ok={dataServiceStatus.health === 'ok'}
                  detail={`data-service: ${dataServiceStatus.health}`}
                />
                <ServiceCapsule
                  name="DB"
                  ok={dataServiceStatus.ready}
                  detail="DuckDB ready"
                />
                <ServiceCapsule
                  name="ICICI"
                  ok={dataServiceStatus.connected}
                  detail={`Provider: ${dataServiceStatus.provider ?? 'unknown'}`}
                />
              </div>

              {/* IST clock */}
              <div className="border-l border-border-dim pl-4">
                <ISTClock />
              </div>

              {/* Action buttons */}
              <div className="flex flex-col gap-2 border-l border-border-dim pl-4">
                {/* Theme toggle */}
                <button
                  onClick={toggleTheme}
                  title={isDark ? 'Day mode' : 'Night mode'}
                  className={clsx(
                    'w-8 h-8 rounded-lg border flex items-center justify-center text-sm transition-all duration-200',
                    isDark
                      ? 'border-amber-700/40 bg-amber-500/5 text-amber-400 hover:bg-amber-500/15 hover:border-amber-500/50'
                      : 'border-slate-300 bg-white text-slate-600 hover:bg-slate-100',
                  )}
                >
                  {isDark ? '☀' : '◑'}
                </button>

                {/* Refresh */}
                <button
                  onClick={onRefresh}
                  disabled={refreshing}
                  title="Refresh NSE data"
                  className={clsx(
                    'w-8 h-8 rounded-lg border flex items-center justify-center text-sm transition-all duration-200',
                    refreshing
                      ? 'border-border-dim text-label cursor-not-allowed'
                      : 'border-amber-700/40 bg-amber-500/5 text-amber-400 hover:bg-amber-500/15 hover:border-amber-500/50'
                  )}
                >
                  <span className={clsx('text-base', refreshing && 'animate-spin inline-block')}>↻</span>
                </button>
              </div>
            </div>

          </div>

          {/* Watchlist now lives solely in the LiveMonitorBar (single source) to
              avoid a duplicate banner stacked directly below this header. */}

          {/* ── Tab navigation ────────────────────────────────────────────── */}
          <TabNav tabs={tabs} active={activeTab} onChange={onTabChange} />

        </div>
      </header>
    </>
  )
}

// ── Tab navigation with sliding amber underline ───────────────────────────────

function TabNav({ tabs, active, onChange }: {
  tabs: { id: string; label: string; badge?: number }[]
  active: string
  onChange: (id: string) => void
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [indicator, setIndicator] = useState({ left: 0, width: 0 })

  const updateIndicator = useCallback(() => {
    if (!containerRef.current) return
    const el = containerRef.current.querySelector(`[data-tab="${active}"]`) as HTMLElement | null
    if (!el) return
    const rect = el.getBoundingClientRect()
    const parentRect = containerRef.current.getBoundingClientRect()
    setIndicator({ left: rect.left - parentRect.left, width: rect.width })
  }, [active])

  useEffect(() => {
    updateIndicator()
    window.addEventListener('resize', updateIndicator)
    return () => window.removeEventListener('resize', updateIndicator)
  }, [updateIndicator])

  const ICONS: Record<string, string> = {
    overview: '▦', stocks: '↗', backtest: '⌬', positions: '◈',
    pipeline: '⬡', scanner: '◎', explorer: '⊞', system: '⊕',
  }

  return (
    <div
      ref={containerRef}
      className="relative flex gap-0 overflow-x-auto border-t"
      style={{ borderColor: 'var(--border-dim)' }}
    >
      {/* Sliding indicator */}
      <div
        className="tab-indicator"
        style={{ left: indicator.left, width: indicator.width }}
      />

      {tabs.map(({ id, label, badge }) => {
        const isActive = id === active
        return (
          <button
            key={id}
            data-tab={id}
            onClick={() => onChange(id)}
            className={clsx(
              'relative flex items-center gap-2 px-5 py-2.5 text-xs transition-all duration-200 whitespace-nowrap font-display font-semibold tracking-wider',
              isActive
                ? 'text-white-sd'
                : 'text-label hover:text-data',
            )}
            style={{
              fontFamily: "'Chakra Petch', sans-serif",
              color: isActive ? 'var(--white)' : undefined,
            }}
          >
            <span className="text-[11px] opacity-60">{ICONS[id] ?? '◻'}</span>
            {label.toUpperCase()}
            {badge != null && badge > 0 && (
              <span
                className="ml-1 px-1.5 py-0.5 rounded text-[9px] font-bold"
                style={{
                  background: 'rgba(245,166,35,0.15)',
                  color: 'var(--amber-hot)',
                  border: '1px solid rgba(245,166,35,0.25)',
                }}
              >
                {badge}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}

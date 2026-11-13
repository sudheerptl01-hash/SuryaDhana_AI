'use client'

import { apiError } from '@/lib/errors'
import { fmtSigned } from '@/lib/format'   // signed numbers with U+2212 (C1-trader-ux-18)
import { useRequestSeq } from '@/components/useRequestSeq'
import { TickerLink, ResearchNote, BadgeChip } from '@/components/terminal'
import { goToPage } from '@/lib/navigate'

/**
 * AlphaDiscoveryDesk — Phase 4 Glass-Box Alpha Discovery tab.
 *
 * Every number on screen is traceable to a live endpoint; every strategy parameter is a
 * live, tweakable control rendered from the engine's own PARAM_SPEC.
 *
 *   • Strategy registry + knobs  → /api/alpha/strategies (PARAM_SPEC, never hardcoded)
 *   • Universe-wide scan         → /api/alpha/scan (full ~1500 NSE universe)
 *   • Live watchlist             → addToWatchlist() ⇒ /api/monitor/subscribe + WS filter
 *   • Live ticks                 → WS /api/monitor/ws/monitor (flash green/red)
 *   • Ticker activation          → <StockDetailModal/> (intraday + OHLCV charts)
 *
 * Air-gap: MODE = PAPER. No execution affordances. Read/scan only.
 *
 * Honesty (5 Nov 2026 review): every net figure is after the real ICICI round trip (shared/trading_costs.py at the
 * position size the payload names, ≈ 0.93 % at ₹1,00,000), with n and a 95 % interval for the window and for the whole
 * loaded history (M19); no Yahoo call from this page (the "Refresh Matched" button and the System Status widget's
 * quick refresh were Yahoo fetches on the request path: removed, the stored EOD panel is the source); the LIVE chip no
 * longer overlaps the KPI strip (m089); CHG % shows the last close-to-close change after the close (m090).
 * Aesthetic: NSE void terminal — JetBrains Mono + Chakra Petch, #05070a/#0a0d13 voids,
 * amber/jade/violet/crimson accents.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Chip, PageHeader, T, fmtInrPx } from '@/components/terminal'
import clsx from 'clsx'
import {
  getAlphaStrategies, runAlphaScan,
  type AlphaStrategiesResponse, type AlphaScanResponse, type AlphaScanResult,
  type AlphaParamSpec,
} from '@/lib/api'
import { useWatchlist, useLiveQuotes } from '@/context/AppContext'
import { socketChip } from '@/lib/feedState'
import { useFeedState } from '@/components/shell/useFeed'
import { useToast } from '@/context/ToastContext'
import { StockDetailModal } from './StockDetailModal'

interface Props { isDark?: boolean }

/** Realised-edge block of /api/alpha/scan (routers/alpha.py edge_stats): after the real round trip, with intervals. */
export interface AlphaEdgeStats {
  n_with_forward: number; mean_net5_bps: number; median_net5_bps: number; win_rate: number
  mean_gross5_bps?: number; cost_bps?: number; win_rate_ci95?: [number, number] | null
  mean_net5_ci95_bps?: [number, number] | null; n_dates?: number | null; ci_method?: string
  top3_dates?: { date: string; n: number; mean_net5_bps: number }[]; top3_dates_signal_share?: number
}
export interface AlphaCost { model: string; profile: string; position_inr: number; round_trip_pct: number; round_trip_inr: number }
type ScanV2 = AlphaScanResponse & {
  edge_history?: AlphaEdgeStats | null
  cost?: AlphaCost
  history_window?: { from: string; to: string; days: number }
  results: (AlphaScanResult & { eod_change_pct?: number | null; eod_change_date?: string | null })[]
}

const fmtBps = (v: number | null | undefined) => v == null ? '—' : `${fmtSigned(v, 0)} bps`
const fmtCi = (ci: [number, number] | null | undefined, f: (v: number) => string) => ci ? `95% ${f(ci[0])} to ${f(ci[1])}` : 'no interval (one signal date)'
const pct0 = (v: number) => `${(v * 100).toFixed(0)}%`

/** One realised-edge tile: mean net with its interval, win rate with its interval, n on n dates. Neutral colour: these
 *  are realised outcomes of a NO EDGE family (arithmetic), never a buy / sell cue. */
export function EdgeTile({ label, e, sub }: { label: string; e: AlphaEdgeStats | null | undefined; sub?: string }) {
  return (
    <div className="rounded-xl border px-3 py-2.5" style={{ background: PANEL, borderColor: '#2A3F58', minWidth: 0 }}>
      <div className="flex items-center gap-2">
        <span className="text-[9px] font-bold tracking-widest chakra" style={{ color: '#5E7793' }}>{label}</span>
        <span style={{ flex: 1 }} />
        <BadgeChip badge="arithmetic" note="Realised 5-session outcomes after the real round trip; no forecast is claimed." />
      </div>
      {e ? (
        <>
          <div className="text-lg font-bold font-mono tabular-nums leading-tight" style={{ color: T.text }}>
            {fmtBps(e.mean_net5_bps)} <span className="text-[10px]" style={{ color: T.muted }}>mean net</span>
          </div>
          <div className="text-[10px] font-mono" style={{ color: T.muted }}>{fmtCi(e.mean_net5_ci95_bps, v => fmtBps(v))}</div>
          <div className="text-[10px] font-mono mt-0.5" style={{ color: '#aab3c2' }}>
            win {pct0(e.win_rate)}{e.win_rate_ci95 ? ` (${pct0(e.win_rate_ci95[0])}–${pct0(e.win_rate_ci95[1])})` : ''} · n = {e.n_with_forward}
            {e.n_dates != null ? ` on ${e.n_dates} dates` : ''}
          </div>
          {e.top3_dates_signal_share != null && e.top3_dates_signal_share >= 0.25 && (
            <div className="text-[10px] mt-0.5" style={{ color: T.amber }}
                 title={(e.top3_dates ?? []).map(d => `${d.date}: ${d.n} signals, mean ${fmtBps(d.mean_net5_bps)}`).join('\n')}>
              {pct0(e.top3_dates_signal_share)} of the signals fell on 3 days
            </div>
          )}
        </>
      ) : <div className="text-lg font-bold font-mono" style={{ color: T.muted }}>—</div>}
      {sub && <div className="text-[9px] mt-0.5" style={{ color: T.muted }}>{sub}</div>}
    </div>
  )
}

const VOID = T.bg
const PANEL = T.panel

// ── Param knob (slider + number for numerics, toggle for booleans) ───────────────

function ParamKnob({
  name, spec, value, onChange, isDark,
}: {
  name: string; spec: AlphaParamSpec
  value: number | boolean
  onChange: (v: number | boolean) => void
  isDark: boolean
}) {
  if (spec.type === 'bool') {
    const on = Boolean(value)
    return (
      <div className="flex items-center justify-between py-2">
        <div className="flex flex-col">
          <span className="text-[11px] font-bold tracking-wide" style={{ color: T.text }}>{name}</span>
          {spec.label && <span className="text-[10px]" style={{ color: '#5E7793' }}>{spec.label}</span>}
        </div>
        <button
          onClick={() => onChange(!on)}
          className="relative inline-flex h-5 w-10 items-center rounded-full transition-colors"
          style={{ background: on ? 'rgba(52,211,153,0.25)' : 'rgba(94,119,147,0.18)', border: `1px solid ${on ? '#34D399' : '#2A3F58'}` }}
          aria-pressed={on}
        >
          <span
            className="inline-block h-3.5 w-3.5 rounded-full transition-transform"
            style={{ background: on ? '#34D399' : '#aab3c2', transform: on ? 'translateX(22px)' : 'translateX(3px)' }}
          />
        </button>
      </div>
    )
  }

  const num = Number(value)
  const min = spec.min ?? 0
  const max = spec.max ?? 1
  const step = spec.step ?? 0.01
  return (
    <div className="py-2">
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex flex-col">
          <span className="text-[11px] font-bold tracking-wide" style={{ color: T.text }}>{name}</span>
          {spec.label && <span className="text-[10px]" style={{ color: '#5E7793' }}>{spec.label}</span>}
        </div>
        <input
          type="number"
          value={num}
          min={min} max={max} step={step}
          onChange={(e) => onChange(Number(e.target.value))}
          className="w-20 px-2 py-1 rounded-md text-[11px] font-mono text-right outline-none"
          style={{ background: VOID, border: '1px solid #2A3F58', color: T.amber }}
        />
      </div>
      <input
        type="range"
        min={min} max={max} step={step} value={num}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full alpha-range"
      />
      <div className="flex justify-between text-[9px] mt-0.5" style={{ color: T.muted }}>
        <span>{min}</span><span>{max}</span>
      </div>
    </div>
  )
}

// ── Live result row (flashes green/red on tick) ──────────────────────────────────

function ResultRow({
  r, watched, ltp, changePct, flash, onToggle, onActivate,
}: {
  r: AlphaScanResult & { eod_change_pct?: number | null; eod_change_date?: string | null }
  watched: boolean
  ltp?: number
  changePct?: number
  flash: 'up' | 'down' | null
  onToggle: () => void
  onActivate: () => void
}) {
  const net5bps = r.net5 != null ? r.net5 * 1e4 : null
  // after the close there is no live change: show the last session's close-to-close move, marked EOD (m090)
  const chg = changePct != null ? changePct : r.eod_change_pct ?? null
  const chgEod = changePct == null && r.eod_change_pct != null
  return (
    <tr
      className="alpha-row transition-colors cursor-pointer"
      style={{ borderBottom: '1px solid rgba(42,63,88,0.35)' }}
      onClick={onActivate}
    >
      <td className="px-3 py-2">
        <button
          onClick={(e) => { e.stopPropagation(); onToggle() }}
          className="text-[11px] w-5 h-5 rounded-md flex items-center justify-center transition-all"
          style={{
            border: `1px solid ${watched ? T.amber : '#2A3F58'}`,
            background: watched ? 'rgba(255,178,0,0.12)' : 'transparent',
            color: watched ? T.amber : '#5E7793',
          }}
          title={watched ? 'Unsubscribe live monitor' : 'Subscribe live monitor'}
        >
          {watched ? '★' : '☆'}
        </button>
      </td>
      <td className="px-3 py-2 font-bold text-[12px]"><TickerLink symbol={r.ticker} /></td>
      <td className="px-3 py-2 text-[11px] font-mono" style={{ color: '#aab3c2' }}>{r.date}</td>
      <td
        className="px-3 py-2 text-[12px] font-mono text-right tabular-nums"
        style={{
          color: flash === 'up' ? '#34D399' : flash === 'down' ? '#FF6080' : '#E8F0FA',
          transition: 'color 120ms ease',
        }}
      >
        {ltp != null ? fmtInrPx(ltp) : r.last_close != null ? fmtInrPx(r.last_close) : '—'}
      </td>
      <td
        className="px-3 py-2 text-[11px] font-mono text-right tabular-nums"
        style={{ color: chg == null ? T.muted : chg >= 0 ? '#34D399' : '#FF6080' }}
        title={chgEod ? `Close-to-close change of the last session (${r.eod_change_date ?? 'EOD'}); no live tick` : 'Live change vs the previous close'}
      >
        {chg != null ? `${fmtSigned(chg, 2)}%` : '—'}{chgEod && <span style={{ color: T.dim, fontSize: 9 }}> EOD</span>}
      </td>
      <td
        className="px-3 py-2 text-[11px] font-mono text-right tabular-nums"
        style={{ color: net5bps == null ? T.muted : T.text }}
        title="Realised 5-session return after the real ICICI round trip (shared/trading_costs.py); '—' = fewer than 5 sessions since the signal"
      >
        {net5bps != null ? `${fmtSigned(net5bps, 0)} bps` : '—'}
      </td>
    </tr>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────────

export function AlphaDiscoveryDesk({ isDark = true }: Props) {
  const { watchlist, addToWatchlist, removeFromWatchlist, isWatched } = useWatchlist()
  const { liveQuotes, wsConnected } = useLiveQuotes()
  const feed = useFeedState()
  // never 'WS LIVE' on a closed market or while the link is down (C1-trader-ux-13, lib/feedState.ts)
  const wsChip = socketChip({ connected: wsConnected, ...feed, live: '● WS LIVE', offline: '○ WS OFFLINE' })
  const { addToast } = useToast()

  const [registry, setRegistry] = useState<AlphaStrategiesResponse | null>(null)
  const [registryErr, setRegistryErr] = useState<string | null>(null)
  const [strategyId, setStrategyId] = useState<string>('')
  const [params, setParams] = useState<Record<string, number | boolean>>({})

  const [scan, setScan] = useState<ScanV2 | null>(null)
  const [scanning, setScanning] = useState(false)
  const [scanMode, setScanMode] = useState<'latest' | 'recent' | 'all'>('recent')
  const [activeTicker, setActiveTicker] = useState<string | null>(null)

  // Flash bookkeeping — prior LTP per symbol for green/red diff
  const prevLtpRef = useRef<Record<string, number>>({})
  const [flashes, setFlashes] = useState<Record<string, 'up' | 'down' | null>>({})
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // ── Load the strategy registry (Glass-Box: PARAM_SPEC straight from engine) ──
  useEffect(() => {
    let alive = true
    getAlphaStrategies()
      .then((res) => {
        if (!alive) return
        const data = res.data
        setRegistry(data)
        const first = data.default ?? Object.keys(data.strategies)[0]
        if (first) {
          setStrategyId(first)
          const defaults: Record<string, number | boolean> = {}
          for (const [name, spec] of Object.entries(data.strategies[first].params)) {
            defaults[name] = spec.default
          }
          setParams(defaults)
        }
      })
      .catch((err) => {
        setRegistryErr(apiError(err, 'failed to load engine'))
        addToast('Alpha engine registry unreachable', 'error')
      })
    return () => { alive = false }
  }, [addToast])

  const strategy = strategyId ? registry?.strategies[strategyId] : undefined

  // ── Run a scan across the full universe ──────────────────────────────────────
  // P12: a scan reads the CURRENT strategy / knobs / mode from a ref. The mode buttons and the knobs called doScan from
  // a closure made before their own state update, so each scan ran with the previous value (one step behind). Only the
  // newest scan's answer (or error) is shown: a slower earlier scan never overwrites it (latest request wins, CT-01).
  type ScanArgs = { strategyId: string; params: Record<string, number | boolean>; mode: 'latest' | 'recent' | 'all' }
  const scanArgs = useRef<ScanArgs>({ strategyId, params, mode: scanMode })
  useEffect(() => { scanArgs.current = { strategyId, params, mode: scanMode } }, [strategyId, params, scanMode])
  const scanSeq = useRequestSeq()
  const doScan = useCallback(async (silent = false, over: Partial<ScanArgs> = {}) => {
    const args = { ...scanArgs.current, ...over }
    scanArgs.current = args
    if (!args.strategyId) return
    const mine = scanSeq.begin()
    setScanning(true)
    try {
      const res = await runAlphaScan({
        strategy_id: args.strategyId,
        params: args.params,
        mode: args.mode,
        recent_days: 15,
        days: 400,
        max_results: 500,
        include_diagnostics: true,
      })
      if (!scanSeq.isCurrent(mine)) return
      setScan(res.data)
      if (!silent) {
        addToast(
          `${res.data.n_signals_window} signals across ${res.data.universe.eligible} eligible / ${res.data.universe.total} tickers · ${res.data.latency.total_s}s`,
          'success',
        )
      }
    } catch (err: any) {
      if (!scanSeq.isCurrent(mine)) return
      const detail = apiError(err, 'scan failed')
      addToast(`Scan failed: ${detail}`, 'error')
    } finally {
      if (scanSeq.isCurrent(mine)) setScanning(false)
    }
  }, [addToast, scanSeq])

  // Initial scan once defaults are loaded
  const didInitialScan = useRef(false)
  useEffect(() => {
    if (strategyId && Object.keys(params).length && !didInitialScan.current) {
      didInitialScan.current = true
      doScan(true)
    }
  }, [strategyId, params, doScan])

  // ── Knob change → debounced re-scan (live tuning) ────────────────────────────
  const onParamChange = useCallback((name: string, v: number | boolean) => {
    const next = { ...scanArgs.current.params, [name]: v }          // P12: the scan below uses THIS value
    scanArgs.current = { ...scanArgs.current, params: next }
    setParams(next)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => { doScan(true) }, 450)
  }, [doScan])

  // ── Switch strategy → reset to that strategy's PARAM_SPEC defaults ───────────
  const onStrategyChange = useCallback((sid: string) => {
    if (!registry) return
    setStrategyId(sid)
    const defaults: Record<string, number | boolean> = {}
    for (const [name, spec] of Object.entries(registry.strategies[sid].params)) {
      defaults[name] = spec.default
    }
    setParams(defaults)
    didInitialScan.current = false
  }, [registry])

  // ── Subscribe ALL matched tickers to the live monitor ────────────────────────
  const subscribeAll = useCallback(() => {
    if (!scan) return
    let added = 0
    scan.tickers.forEach((t) => { if (!isWatched(t)) { addToWatchlist(t); added++ } })
    addToast(added ? `Subscribed ${added} tickers to live monitor` : 'All matched tickers already monitored', added ? 'success' : 'info')
  }, [scan, isWatched, addToWatchlist, addToast])

  // ── Live tick flash detection ────────────────────────────────────────────────
  useEffect(() => {
    const next: Record<string, 'up' | 'down' | null> = {}
    for (const [sym, q] of Object.entries(liveQuotes)) {
      const ltp = q.ltp
      if (ltp == null) continue
      const prev = prevLtpRef.current[sym]
      if (prev != null && ltp !== prev) next[sym] = ltp > prev ? 'up' : 'down'
      prevLtpRef.current[sym] = ltp
    }
    if (Object.keys(next).length) {
      setFlashes((f) => ({ ...f, ...next }))
      const id = setTimeout(() => {
        setFlashes((f) => {
          const c = { ...f }
          for (const k of Object.keys(next)) c[k] = null
          return c
        })
      }, 320)
      return () => clearTimeout(id)
    }
  }, [liveQuotes])

  const knobEntries = useMemo(
    () => Object.entries(strategy?.knobs ?? {}),
    [strategy],
  )
  const flagEntries = useMemo(
    () => Object.entries(strategy?.flags ?? {}),
    [strategy],
  )

  // ── Render ────────────────────────────────────────────────────────────────────
  return (
    <div className="space-y-4">
      <style>{`
        /* Chakra Petch is self-hosted (globals.css @font-face): no Google Fonts request (desktop program D4) */
        .alpha-range { -webkit-appearance: none; height: 4px; border-radius: 3px; background: linear-gradient(90deg,#ffb000,#2A3F58); outline: none; }
        .alpha-range::-webkit-slider-thumb { -webkit-appearance: none; width: 14px; height: 14px; border-radius: 50%; background: #ffb000; cursor: pointer; border: 2px solid ${VOID}; }
        .alpha-range::-moz-range-thumb { width: 14px; height: 14px; border-radius: 50%; background: #ffb000; cursor: pointer; border: 2px solid ${VOID}; }
        .alpha-row:hover { background: rgba(255,178,0,0.04); }
        .chakra { font-family: 'Chakra Petch', sans-serif; }
        @keyframes alphascan { 0%,100% { opacity: .4 } 50% { opacity: 1 } }
      `}</style>

      {/* ── Air-gap header banner ───────────────────────────────────────────── */}
      <PageHeader code="ALFA" title="Alpha Discovery Desk"
        status={<Chip color={T.green} active>PAPER · EXECUTION DISABLED</Chip>}
        subtitle="Strategy engine scans · tweak knobs · monitor matched setups"
        right={<Chip color={wsChip.tone === 'live' ? T.green : wsChip.tone === 'closed' ? T.muted : T.red}
          active={wsChip.tone === 'live'}>{wsChip.text}</Chip>} />
      <ResearchNote verdict="NO EDGE" report="reports/idea_lab/REPORT.md">
        Out-of-sample tests of India-specific ideas (circuits, overnight momentum, lottery stocks, dividends, splits) found no edge
        after costs. Treat matches here as research leads, not trades.
      </ResearchNote>

      <div className="grid grid-cols-1 xl:grid-cols-[340px_1fr] gap-4">
        {/* ── Left rail: status + pipeline + knobs ──────────────────────────── */}
        <div className="space-y-4">
          {/* Data source: the stored EOD panel. No fetch from this page (Yahoo budget, CLAUDE.md; M29). */}
          <div className="rounded-2xl border" style={{ background: PANEL, borderColor: '#2A3F58' }}>
            <div className="px-4 py-3 border-b" style={{ borderColor: 'rgba(42,63,88,0.5)' }}>
              <h3 className="chakra text-xs font-bold tracking-widest uppercase" style={{ color: '#E8F0FA' }}>
                ⚙ Data
              </h3>
            </div>
            <div className="px-4 py-3 space-y-1.5 text-[11px]" style={{ color: '#8aa0b8' }}>
              <p>Scans read the stored EOD panel (data-service{scan ? `, as of ${scan.as_of}` : ''}), refreshed by the scheduled
                evening pipeline. This page fetches nothing itself.</p>
              <p>Service health: <span role="button" tabIndex={0} onClick={() => goToPage('system')}
                onKeyDown={e => { if (e.key === 'Enter') goToPage('system') }}
                style={{ color: T.cyan, cursor: 'pointer' }}>SYS ›</span></p>
            </div>
          </div>

          {/* Strategy knobs (PARAM_SPEC-driven) */}
          <div className="rounded-2xl border" style={{ background: PANEL, borderColor: '#2A3F58' }}>
            <div className="px-4 py-3 border-b flex items-center justify-between" style={{ borderColor: 'rgba(42,63,88,0.5)' }}>
              <h3 className="chakra text-xs font-bold tracking-widest uppercase" style={{ color: '#E8F0FA' }}>
                ◈ Strategy Knobs
              </h3>
              {scanning && (
                <span className="text-[9px] font-bold tracking-widest" style={{ color: T.amber, animation: 'alphascan 1s infinite' }}>
                  SCANNING…
                </span>
              )}
            </div>
            <div className="px-4 py-3 space-y-2">
              {registryErr && (
                <div className="text-[11px] px-3 py-2 rounded-md" style={{ background: 'rgba(255,96,128,0.08)', border: '1px solid #FF6080', color: '#FF8080' }}>
                  {registryErr}
                </div>
              )}
              {!registry && !registryErr && (
                <div className="space-y-2">
                  {[0, 1, 2].map((i) => (
                    <div key={i} className="h-8 rounded-md animate-pulse" style={{ background: 'rgba(42,63,88,0.3)' }} />
                  ))}
                </div>
              )}
              {registry && (
                <>
                  {/* Strategy selector */}
                  <div className="mb-1">
                    <label className="text-[10px] font-bold tracking-wide" style={{ color: '#5E7793' }}>STRATEGY</label>
                    <select
                      value={strategyId}
                      onChange={(e) => onStrategyChange(e.target.value)}
                      className="w-full mt-1 px-2 py-1.5 rounded-md text-[11px] font-bold outline-none"
                      style={{ background: VOID, border: '1px solid #2A3F58', color: T.text }}
                    >
                      {Object.entries(registry.strategies).map(([sid, m]) => (
                        <option key={sid} value={sid}>{m.name}</option>
                      ))}
                    </select>
                  </div>

                  <div className="h-px my-1" style={{ background: 'rgba(42,63,88,0.5)' }} />

                  {/* Numeric knobs */}
                  {knobEntries.map(([name, spec]) => (
                    <ParamKnob key={name} name={name} spec={spec} value={params[name] ?? spec.default} onChange={(v) => onParamChange(name, v)} isDark={isDark} />
                  ))}

                  {flagEntries.length > 0 && <div className="h-px my-1" style={{ background: 'rgba(42,63,88,0.5)' }} />}

                  {/* Flag toggles */}
                  {flagEntries.map(([name, spec]) => (
                    <ParamKnob key={name} name={name} spec={spec} value={params[name] ?? spec.default} onChange={(v) => onParamChange(name, v)} isDark={isDark} />
                  ))}

                  {/* Scan mode + run */}
                  <div className="h-px my-1" style={{ background: 'rgba(42,63,88,0.5)' }} />
                  <div className="flex gap-1">
                    {(['latest', 'recent', 'all'] as const).map((m) => (
                      <button
                        key={m}
                        onClick={() => { setScanMode(m); doScan(true, { mode: m }) }}
                        className="flex-1 px-2 py-1 rounded-md text-[10px] font-bold uppercase transition-all"
                        style={{
                          border: `1px solid ${scanMode === m ? T.amber : '#2A3F58'}`,
                          background: scanMode === m ? 'rgba(255,178,0,0.12)' : 'transparent',
                          color: scanMode === m ? T.amber : '#5E7793',
                        }}
                      >
                        {m}
                      </button>
                    ))}
                  </div>
                  <button
                    onClick={() => doScan(false)}
                    disabled={scanning}
                    className="w-full mt-1 flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-[11px] font-bold transition-all"
                    style={{
                      border: '1px solid #ffb000',
                      background: 'rgba(255,178,0,0.14)',
                      color: T.amber,
                      cursor: scanning ? 'wait' : 'pointer',
                    }}
                  >
                    {scanning && <span className="w-3 h-3 border-2 border-t-transparent rounded-full animate-spin" style={{ borderColor: T.amber, borderTopColor: 'transparent' }} />}
                    {scanning ? 'Scanning universe…' : '▶ Run Scan'}
                  </button>
                </>
              )}
            </div>
          </div>
        </div>

        {/* ── Right: stats + live results grid ──────────────────────────────── */}
        <div className="space-y-4">
          {/* Scan summary strip */}
          <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
            <SummaryStat label="ELIGIBLE UNIVERSE" value={scan ? `${scan.universe.eligible}` : '—'} sub={scan ? `/ ${scan.universe.total} total` : ''} accent="#4ACFE8" />
            <SummaryStat label="SIGNALS (WINDOW)" value={scan ? `${scan.n_signals_window}` : '—'}
              sub={scan ? `${scan.n_signals_total} in the loaded history${scan.history_window ? ` (${scan.history_window.from} → ${scan.history_window.to})` : ''}` : ''} accent="#ffb000" />
            <EdgeTile label="WINDOW · NET 5D" e={scan?.edge as AlphaEdgeStats | null | undefined}
              sub={scan?.edge ? 'signals in this window with 5 sessions since' : 'no signal here has 5 sessions yet'} />
            <EdgeTile label="HISTORY · NET 5D" e={scan?.edge_history}
              sub="every signal in the loaded history: the sample that matters" />
          </div>
          {scan?.cost && (
            <div className="text-[10px] px-1" style={{ color: T.muted }}>
              Net = 5-session return − {scan.cost.round_trip_pct.toFixed(2)}% (the {scan.cost.profile.replace('icici_moneysaver', 'ICICI MoneySaver').replace(/_/g, ' ')} delivery round trip
              at ₹{Math.round(scan.cost.position_inr).toLocaleString('en-IN')} a position, {scan.cost.model}). A gap open fills worse than the
              adjusted open: slippage is not modelled. Interval: {scan.edge_history?.ci_method ?? 'bootstrap over signal dates'}. One year of an
              in-sample window: the pre-registered idea-lab holdout found no edge after costs.
            </div>
          )}

          {/* Results grid */}
          <div className="rounded-2xl border overflow-hidden" style={{ background: PANEL, borderColor: '#2A3F58' }}>
            <div className="px-4 py-3 border-b flex items-center justify-between flex-wrap gap-2" style={{ borderColor: 'rgba(42,63,88,0.5)' }}>
              <div className="flex items-center gap-2">
                <h3 className="chakra text-xs font-bold tracking-widest uppercase" style={{ color: '#E8F0FA' }}>
                  ◈ Matched Setups
                </h3>
                {scan && (
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded" style={{ background: 'rgba(74,207,232,0.08)', color: '#4ACFE8' }}>
                    as of {scan.as_of} · {scan.latency.total_s}s
                  </span>
                )}
              </div>
              <button
                onClick={subscribeAll}
                disabled={!scan?.tickers.length}
                className="px-3 py-1.5 rounded-lg text-[10px] font-bold transition-all"
                style={{
                  border: `1px solid ${scan?.tickers.length ? T.amber : '#2A3F58'}`,
                  background: scan?.tickers.length ? 'rgba(255,178,0,0.10)' : 'transparent',
                  color: scan?.tickers.length ? T.amber : T.muted,
                  cursor: scan?.tickers.length ? 'pointer' : 'not-allowed',
                }}
              >
                ★ Monitor all {scan?.tickers.length ?? 0} names
              </button>
            </div>

            <div className="overflow-auto" style={{ maxHeight: '60vh' }}>
              {scanning && !scan && (
                <div className="p-4 space-y-2">
                  {Array.from({ length: 8 }).map((_, i) => (
                    <div key={i} className="h-9 rounded-md animate-pulse" style={{ background: 'rgba(42,63,88,0.25)' }} />
                  ))}
                </div>
              )}
              {scan && scan.results.length === 0 && (
                <div className="p-10 text-center">
                  <p className="text-[12px] font-bold" style={{ color: '#aab3c2' }}>No setups in this window.</p>
                  <p className="text-[10px] mt-1" style={{ color: '#5E7793' }}>
                    Loosen <span style={{ color: T.amber }}>gap_threshold</span>, enable Leg A, or widen the scan mode to “all”.
                  </p>
                </div>
              )}
              {scan && scan.results.length > 0 && (
                <table className="w-full">
                  <thead>
                    <tr className="sticky top-0 z-10" style={{ background: VOID }}>
                      {['', 'TICKER', 'SIGNAL DATE', 'LTP / CLOSE', 'CHG% (LIVE / EOD)', 'NET 5D (AFTER COSTS)'].map((h, i) => (
                        <th key={i} className={clsx('px-3 py-2 text-[9px] font-bold tracking-widest uppercase', i >= 3 ? 'text-right' : 'text-left')} style={{ color: '#5E7793' }}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {scan.results.map((r) => {
                      const q = liveQuotes[r.ticker.toUpperCase()]
                      return (
                        <ResultRow
                          key={`${r.ticker}-${r.date}`}
                          r={r}
                          watched={isWatched(r.ticker)}
                          ltp={q?.ltp}
                          changePct={q?.change_pct}
                          flash={flashes[r.ticker.toUpperCase()] ?? null}
                          onToggle={() => isWatched(r.ticker) ? removeFromWatchlist(r.ticker) : addToWatchlist(r.ticker)}
                          onActivate={() => setActiveTicker(r.ticker)}
                        />
                      )
                    })}
                  </tbody>
                </table>
              )}
            </div>
          </div>

          {/* Resolved params footer (provenance / Glass-Box transparency) */}
          {scan && (
            <div className="rounded-xl border px-4 py-2.5 flex items-center gap-4 flex-wrap" style={{ background: PANEL, borderColor: '#2A3F58' }}>
              <span className="text-[9px] font-bold tracking-widest" style={{ color: '#5E7793' }}>RESOLVED PARAMS (engine-coerced)</span>
              {Object.entries(scan.params).map(([k, v]) => (
                <span key={k} className="text-[10px] font-mono" style={{ color: '#aab3c2' }}>
                  {k}=<span style={{ color: T.amber }}>{String(v)}</span>
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Ticker activation → intraday + OHLCV charts (data-proxy) */}
      {activeTicker && <StockDetailModal ticker={activeTicker} onClose={() => setActiveTicker(null)} />}
    </div>
  )
}

function SummaryStat({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent: string }) {
  return (
    <div className="rounded-xl border px-3 py-2.5" style={{ background: PANEL, borderColor: '#2A3F58' }}>
      <div className="text-[9px] font-bold tracking-widest chakra" style={{ color: '#5E7793' }}>{label}</div>
      <div className="text-lg font-bold font-mono tabular-nums leading-tight" style={{ color: accent }}>{value}</div>
      {sub && <div className="text-[9px]" style={{ color: T.muted }}>{sub}</div>}
    </div>
  )
}

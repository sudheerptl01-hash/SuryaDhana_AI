'use client'

/**
 * AlphaDiscoveryDesk — Phase 4 Glass-Box Alpha Discovery tab.
 *
 * Every number on screen is traceable to a live endpoint; every strategy parameter is a
 * live, tweakable control rendered from the engine's own PARAM_SPEC.
 *
 *   • System Status widget       → /api/data/health · /ready · /provider/status
 *   • Data Pipeline panel        → /api/data/fetch/refresh-batch (async, non-blocking)
 *   • Strategy registry + knobs  → /api/alpha/strategies (PARAM_SPEC, never hardcoded)
 *   • Universe-wide scan         → /api/alpha/scan (full ~1500 NSE universe)
 *   • Live watchlist             → addToWatchlist() ⇒ /api/monitor/subscribe + WS filter
 *   • Live ticks                 → WS /api/monitor/ws/monitor (flash green/red)
 *   • Ticker activation          → <StockDetailModal/> (intraday + OHLCV charts)
 *
 * Air-gap: MODE = PAPER. No execution affordances. Read/scan only.
 * Aesthetic: NSE void terminal — JetBrains Mono + Chakra Petch, #030810/#070E1B voids,
 * amber/jade/violet/crimson accents.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import clsx from 'clsx'
import {
  getAlphaStrategies, runAlphaScan, fetchRefreshBatch,
  type AlphaStrategiesResponse, type AlphaScanResponse, type AlphaScanResult,
  type AlphaParamSpec,
} from '@/lib/api'
import { useWatchlist, useLiveQuotes } from '@/context/AppContext'
import { useToast } from '@/context/ToastContext'
import { SystemStatusWidget } from './SystemStatusWidget'
import { StockDetailModal } from './StockDetailModal'

interface Props { isDark?: boolean }

const VOID = '#030810'
const PANEL = '#070E1B'

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
          <span className="text-[11px] font-bold tracking-wide" style={{ color: '#C8DCF0' }}>{name}</span>
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
            style={{ background: on ? '#34D399' : '#7DA4BE', transform: on ? 'translateX(22px)' : 'translateX(3px)' }}
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
          <span className="text-[11px] font-bold tracking-wide" style={{ color: '#C8DCF0' }}>{name}</span>
          {spec.label && <span className="text-[10px]" style={{ color: '#5E7793' }}>{spec.label}</span>}
        </div>
        <input
          type="number"
          value={num}
          min={min} max={max} step={step}
          onChange={(e) => onChange(Number(e.target.value))}
          className="w-20 px-2 py-1 rounded-md text-[11px] font-mono text-right outline-none"
          style={{ background: VOID, border: '1px solid #2A3F58', color: '#FFB200' }}
        />
      </div>
      <input
        type="range"
        min={min} max={max} step={step} value={num}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full alpha-range"
      />
      <div className="flex justify-between text-[9px] mt-0.5" style={{ color: '#3D5872' }}>
        <span>{min}</span><span>{max}</span>
      </div>
    </div>
  )
}

// ── Live result row (flashes green/red on tick) ──────────────────────────────────

function ResultRow({
  r, watched, ltp, changePct, flash, onToggle, onActivate,
}: {
  r: AlphaScanResult
  watched: boolean
  ltp?: number
  changePct?: number
  flash: 'up' | 'down' | null
  onToggle: () => void
  onActivate: () => void
}) {
  const net5bps = r.net5 != null ? r.net5 * 1e4 : null
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
            border: `1px solid ${watched ? '#FFB200' : '#2A3F58'}`,
            background: watched ? 'rgba(255,178,0,0.12)' : 'transparent',
            color: watched ? '#FFB200' : '#5E7793',
          }}
          title={watched ? 'Unsubscribe live monitor' : 'Subscribe live monitor'}
        >
          {watched ? '★' : '☆'}
        </button>
      </td>
      <td className="px-3 py-2 font-bold text-[12px]" style={{ color: '#C8DCF0' }}>{r.ticker}</td>
      <td className="px-3 py-2 text-[11px] font-mono" style={{ color: '#7DA4BE' }}>{r.date}</td>
      <td
        className="px-3 py-2 text-[12px] font-mono text-right tabular-nums"
        style={{
          color: flash === 'up' ? '#34D399' : flash === 'down' ? '#FF6080' : '#E8F0FA',
          transition: 'color 120ms ease',
        }}
      >
        {ltp != null ? `₹${ltp.toFixed(2)}` : r.last_close != null ? `₹${r.last_close.toFixed(2)}` : '—'}
      </td>
      <td
        className="px-3 py-2 text-[11px] font-mono text-right tabular-nums"
        style={{ color: changePct == null ? '#3D5872' : changePct >= 0 ? '#34D399' : '#FF6080' }}
      >
        {changePct != null ? `${changePct >= 0 ? '+' : ''}${changePct.toFixed(2)}%` : '—'}
      </td>
      <td
        className="px-3 py-2 text-[11px] font-mono text-right tabular-nums"
        style={{ color: net5bps == null ? '#3D5872' : net5bps >= 0 ? '#34D399' : '#FF6080' }}
        title="Realised net 5-day edge (forward diagnostic, friction-adjusted)"
      >
        {net5bps != null ? `${net5bps >= 0 ? '+' : ''}${net5bps.toFixed(0)} bps` : '—'}
      </td>
    </tr>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────────

export function AlphaDiscoveryDesk({ isDark = true }: Props) {
  const { watchlist, addToWatchlist, removeFromWatchlist, isWatched } = useWatchlist()
  const { liveQuotes, wsConnected } = useLiveQuotes()
  const { addToast } = useToast()

  const [registry, setRegistry] = useState<AlphaStrategiesResponse | null>(null)
  const [registryErr, setRegistryErr] = useState<string | null>(null)
  const [strategyId, setStrategyId] = useState<string>('')
  const [params, setParams] = useState<Record<string, number | boolean>>({})

  const [scan, setScan] = useState<AlphaScanResponse | null>(null)
  const [scanning, setScanning] = useState(false)
  const [scanMode, setScanMode] = useState<'latest' | 'recent' | 'all'>('recent')
  const [activeTicker, setActiveTicker] = useState<string | null>(null)
  const [pipelineBusy, setPipelineBusy] = useState(false)

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
        setRegistryErr(err?.response?.data?.detail || err?.message || 'failed to load engine')
        addToast('Alpha engine registry unreachable', 'error')
      })
    return () => { alive = false }
  }, [addToast])

  const strategy = strategyId ? registry?.strategies[strategyId] : undefined

  // ── Run a scan across the full universe ──────────────────────────────────────
  const doScan = useCallback(async (silent = false) => {
    if (!strategyId) return
    setScanning(true)
    try {
      const res = await runAlphaScan({
        strategy_id: strategyId,
        params,
        mode: scanMode,
        recent_days: 15,
        days: 400,
        max_results: 500,
        include_diagnostics: true,
      })
      setScan(res.data)
      if (!silent) {
        addToast(
          `${res.data.n_signals_window} signals across ${res.data.universe.eligible} eligible / ${res.data.universe.total} tickers · ${res.data.latency.total_s}s`,
          'success',
        )
      }
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || 'scan failed'
      addToast(`Scan failed: ${detail}`, 'error')
    } finally {
      setScanning(false)
    }
  }, [strategyId, params, scanMode, addToast])

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
    setParams((prev) => ({ ...prev, [name]: v }))
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

  // ── Data Pipeline: refresh matched tickers' data (async, non-blocking) ───────
  const refreshMatched = useCallback(async () => {
    if (!scan || !scan.tickers.length) { addToast('Run a scan first', 'warning'); return }
    setPipelineBusy(true)
    addToast(`Refreshing OHLCV for ${Math.min(scan.tickers.length, 25)} matched tickers…`, 'info')
    try {
      const res = await fetchRefreshBatch({ tickers: scan.tickers.slice(0, 25), years: 1 })
      const refreshed = res.data?.refreshed ?? {}
      const total = Object.values(refreshed).reduce((s: number, v: any) => s + (Number(v) || 0), 0)
      addToast(`Pipeline: ${total} rows refreshed`, 'success')
    } catch (err: any) {
      addToast(`Refresh failed: ${err?.response?.data?.detail || err?.message}`, 'error')
    } finally {
      setPipelineBusy(false)
    }
  }, [scan, addToast])

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
        @import url('https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@500;600;700&display=swap');
        .alpha-range { -webkit-appearance: none; height: 4px; border-radius: 3px; background: linear-gradient(90deg,#FFB200,#2A3F58); outline: none; }
        .alpha-range::-webkit-slider-thumb { -webkit-appearance: none; width: 14px; height: 14px; border-radius: 50%; background: #FFB200; cursor: pointer; border: 2px solid ${VOID}; }
        .alpha-range::-moz-range-thumb { width: 14px; height: 14px; border-radius: 50%; background: #FFB200; cursor: pointer; border: 2px solid ${VOID}; }
        .alpha-row:hover { background: rgba(255,178,0,0.04); }
        .chakra { font-family: 'Chakra Petch', sans-serif; }
        @keyframes alphascan { 0%,100% { opacity: .4 } 50% { opacity: 1 } }
      `}</style>

      {/* ── Air-gap header banner ───────────────────────────────────────────── */}
      <div
        className="rounded-2xl border px-5 py-3 flex items-center justify-between flex-wrap gap-3"
        style={{ background: PANEL, borderColor: '#2A3F58' }}
      >
        <div className="flex items-center gap-3">
          <span
            className="chakra text-xs font-bold tracking-[0.2em] px-3 py-1 rounded-md"
            style={{ background: 'rgba(255,178,0,0.10)', border: '1px solid #FFB200', color: '#FFB200' }}
          >
            ◈ ALPHA DISCOVERY DESK
          </span>
          <span
            className="text-[10px] font-bold tracking-widest px-2.5 py-1 rounded-md"
            style={{ background: 'rgba(52,211,153,0.10)', border: '1px solid #34D399', color: '#34D399' }}
            title="Air-gapped — no live execution"
          >
            MODE: PAPER · EXECUTION DISABLED
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px]" style={{ color: '#5E7793' }}>monitor link</span>
          <span
            className="inline-flex items-center gap-1.5 text-[10px] font-bold px-2.5 py-1 rounded-full"
            style={{
              background: wsConnected ? 'rgba(52,211,153,0.10)' : 'rgba(255,96,128,0.10)',
              border: `1px solid ${wsConnected ? '#34D399' : '#FF6080'}`,
              color: wsConnected ? '#34D399' : '#FF6080',
            }}
          >
            <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: wsConnected ? '#34D399' : '#FF6080' }} />
            {wsConnected ? 'WS LIVE' : 'WS OFFLINE'}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[340px_1fr] gap-4">
        {/* ── Left rail: status + pipeline + knobs ──────────────────────────── */}
        <div className="space-y-4">
          <SystemStatusWidget isDark={isDark} />

          {/* Data Pipeline panel */}
          <div className="rounded-2xl border" style={{ background: PANEL, borderColor: '#2A3F58' }}>
            <div className="px-4 py-3 border-b" style={{ borderColor: 'rgba(42,63,88,0.5)' }}>
              <h3 className="chakra text-xs font-bold tracking-widest uppercase" style={{ color: '#E8F0FA' }}>
                ⚙ Data Pipeline
              </h3>
            </div>
            <div className="px-4 py-3 space-y-2">
              <p className="text-[10px]" style={{ color: '#5E7793' }}>
                Refresh OHLCV for the current matched set via the data-service async fetch.
              </p>
              <button
                onClick={refreshMatched}
                disabled={pipelineBusy || !scan?.tickers.length}
                className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-[11px] font-bold transition-all"
                style={{
                  border: `1px solid ${pipelineBusy ? '#2A3F58' : '#6E56CF'}`,
                  background: pipelineBusy ? 'rgba(110,86,207,0.06)' : 'rgba(110,86,207,0.14)',
                  color: pipelineBusy ? '#5E7793' : '#A78BFA',
                  cursor: pipelineBusy || !scan?.tickers.length ? 'not-allowed' : 'pointer',
                }}
              >
                {pipelineBusy && <span className="w-3 h-3 border-2 border-t-transparent rounded-full animate-spin" style={{ borderColor: '#A78BFA', borderTopColor: 'transparent' }} />}
                {pipelineBusy ? 'Refreshing…' : `↻ Refresh Matched (${Math.min(scan?.tickers.length ?? 0, 25)})`}
              </button>
            </div>
          </div>

          {/* Strategy knobs (PARAM_SPEC-driven) */}
          <div className="rounded-2xl border" style={{ background: PANEL, borderColor: '#2A3F58' }}>
            <div className="px-4 py-3 border-b flex items-center justify-between" style={{ borderColor: 'rgba(42,63,88,0.5)' }}>
              <h3 className="chakra text-xs font-bold tracking-widest uppercase" style={{ color: '#E8F0FA' }}>
                ◈ Strategy Knobs
              </h3>
              {scanning && (
                <span className="text-[9px] font-bold tracking-widest" style={{ color: '#FFB200', animation: 'alphascan 1s infinite' }}>
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
                      style={{ background: VOID, border: '1px solid #2A3F58', color: '#C8DCF0' }}
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
                        onClick={() => { setScanMode(m); setTimeout(() => doScan(true), 0) }}
                        className="flex-1 px-2 py-1 rounded-md text-[10px] font-bold uppercase transition-all"
                        style={{
                          border: `1px solid ${scanMode === m ? '#FFB200' : '#2A3F58'}`,
                          background: scanMode === m ? 'rgba(255,178,0,0.12)' : 'transparent',
                          color: scanMode === m ? '#FFB200' : '#5E7793',
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
                      border: '1px solid #FFB200',
                      background: 'rgba(255,178,0,0.14)',
                      color: '#FFB200',
                      cursor: scanning ? 'wait' : 'pointer',
                    }}
                  >
                    {scanning && <span className="w-3 h-3 border-2 border-t-transparent rounded-full animate-spin" style={{ borderColor: '#FFB200', borderTopColor: 'transparent' }} />}
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
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <SummaryStat label="ELIGIBLE UNIVERSE" value={scan ? `${scan.universe.eligible}` : '—'} sub={scan ? `/ ${scan.universe.total} total` : ''} accent="#4ACFE8" />
            <SummaryStat label="SIGNALS (WINDOW)" value={scan ? `${scan.n_signals_window}` : '—'} sub={scan ? `${scan.n_signals_total} hist` : ''} accent="#FFB200" />
            <SummaryStat label="WIN RATE" value={scan?.edge ? `${(scan.edge.win_rate * 100).toFixed(1)}%` : '—'} sub={scan?.edge ? `n=${scan.edge.n_with_forward}` : 'no fwd window'} accent="#34D399" />
            <SummaryStat label="MEAN NET 5D" value={scan?.edge ? `${scan.edge.mean_net5_bps >= 0 ? '+' : ''}${scan.edge.mean_net5_bps} bps` : '—'} sub="friction-adj" accent={scan?.edge && scan.edge.mean_net5_bps >= 0 ? '#34D399' : '#FF6080'} />
          </div>

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
                  border: `1px solid ${scan?.tickers.length ? '#FFB200' : '#2A3F58'}`,
                  background: scan?.tickers.length ? 'rgba(255,178,0,0.10)' : 'transparent',
                  color: scan?.tickers.length ? '#FFB200' : '#3D5872',
                  cursor: scan?.tickers.length ? 'pointer' : 'not-allowed',
                }}
              >
                ★ Monitor All ({scan?.tickers.length ?? 0})
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
                  <p className="text-[12px] font-bold" style={{ color: '#7DA4BE' }}>No setups in this window.</p>
                  <p className="text-[10px] mt-1" style={{ color: '#5E7793' }}>
                    Loosen <span style={{ color: '#FFB200' }}>gap_threshold</span>, enable Leg A, or widen the scan mode to “all”.
                  </p>
                </div>
              )}
              {scan && scan.results.length > 0 && (
                <table className="w-full">
                  <thead>
                    <tr className="sticky top-0 z-10" style={{ background: VOID }}>
                      {['', 'TICKER', 'SIGNAL DATE', 'LTP / CLOSE', 'CHG%', 'NET 5D'].map((h, i) => (
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
                <span key={k} className="text-[10px] font-mono" style={{ color: '#7DA4BE' }}>
                  {k}=<span style={{ color: '#FFB200' }}>{String(v)}</span>
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
      {sub && <div className="text-[9px]" style={{ color: '#3D5872' }}>{sub}</div>}
    </div>
  )
}

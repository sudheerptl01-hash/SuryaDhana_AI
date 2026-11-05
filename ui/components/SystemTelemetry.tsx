'use client'

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Chip, PageHeader, T, TabSkeleton, Tabs, useSubView } from '@/components/terminal'
import { DataHealthView } from '@/components/datahealth/DataHealthView'
import clsx from 'clsx'
import {
  getTelemetryStatus,
  getTelemetryLogs,
  setAutopilot,
} from '@/lib/api'
import { SystemStatusWidget } from '@/components/SystemStatusWidget'
import { LiveFeedStatus } from '@/components/LiveFeedStatus'

// ── Types ─────────────────────────────────────────────────────────────────────
interface ScheduledJob {
  id: string
  name: string
  next_run_ist: string | null
  next_run_unix: number | null
  last_latency_ms: number | null
  avg_latency_ms: number | null
  last_status: string | null
  last_run_ts: string | null
  samples: number
}

interface TelemetryStatus {
  master_controller_online: boolean
  broker_latency_ms: number | null
  ist_now: string
  scheduler: {
    scheduler_running: boolean
    autopilot: { enabled: boolean; toggled_at: string }
    jobs: ScheduledJob[]
  } | null
  system: {
    cpu_pct: number
    mem_pct: number
    mem_used_gb: number
    mem_total_gb: number
  }
}

interface ParsedLogLine {
  ts: string
  level: string
  job: string
  msg: string
  [key: string]: string
}

const JOB_SCHEDULE: Record<string, string> = {
  icici_session_refresh:         '08:00 IST  · Mon–Fri (TOTP login)',
  icici_session_refresh_startup: 'once at start-up (trading morning)',
  pre_market_sync:      '08:30 IST',
  intraday_inference:   '09:15–15:30 IST  · every 15 min',
  eod_rebalancing:      '15:15 IST',
  overnight_rl_retrain: '23:00 IST',
  eod_data_pipeline:    '18:30 IST  · Mon–Fri',
  desk_daily:           '19:30 IST  · Mon–Fri (paper)',
  nse_positions_catchup: '20:30 IST  · Mon–Fri',
  nse_filings_weekly:   'Sat 09:00 IST',
  gold_preopen_snapshot: '08:45 IST  · Mon–Fri',
  preopen_capture:      '09:09:30 IST  · Mon–Fri',
  gold_open_capture:    '09:10 IST  · Mon–Fri',
  price_alerts_check:   'every minute  · 09:15–15:30 Mon–Fri',
  move_alerts:          'every 5 min  · 09:20–15:30 Mon–Fri',
  filing_alerts:        'every 5 min  · 08:00–22:55 Mon–Sat',
  news_track_record_daily: '19:45 IST  · Mon–Fri',
  results_capture_daily: '20:45 IST  · Mon–Fri',
  index_valuation_daily: '19:15 IST  · Mon–Fri',
  daily_wrap:           '21:00 IST  · Mon–Fri',
  morning_note:         '08:50 IST  · Mon–Fri',
  internals_sample:     'every 2 min  · 09:15–15:31 Mon–Fri',
  close_note:           '15:40 IST  · Mon–Fri',
  financials_sweep:     'Sat 10:00 IST (FA / RV cache)',
}

const LOG_LEVEL_STYLE: Record<string, string> = {
  INFO:  'text-emerald-400',
  WARN:  'text-amber-400',
  ERROR: 'text-rose-400',
}

// ── Countdown hook ────────────────────────────────────────────────────────────
function useCountdown(nextRunUnix: number | null): string {
  const [label, setLabel] = useState('—')

  useEffect(() => {
    if (!nextRunUnix) { setLabel('—'); return }
    const tick = () => {
      const diff = nextRunUnix - Math.floor(Date.now() / 1000)
      if (diff <= 0) { setLabel('NOW'); return }
      const h = Math.floor(diff / 3600)
      const m = Math.floor((diff % 3600) / 60)
      const s = diff % 60
      if (h > 0)      setLabel(`${h}h ${m}m`)
      else if (m > 0) setLabel(`${m}m ${s.toString().padStart(2, '0')}s`)
      else            setLabel(`${s}s`)
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [nextRunUnix])

  return label
}

// ── Sub-components ────────────────────────────────────────────────────────────
function LatencyPill({ ms, isDark }: { ms: number | null; isDark: boolean }) {
  if (ms === null) return <span className={clsx('text-xs font-mono', isDark ? 'text-slate-500' : 'text-gray-400')}>—</span>
  const color = ms < 50
    ? (isDark ? 'text-emerald-400' : 'text-emerald-600')
    : ms < 200
      ? (isDark ? 'text-amber-400' : 'text-amber-600')
      : (isDark ? 'text-rose-400' : 'text-rose-600')
  return <span className={clsx('text-xs font-mono font-bold', color)}>{ms.toFixed(0)}ms</span>
}

function MiniBar({ pct, color }: { pct: number; color: string }) {
  return (
    <div className="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden">
      <div
        className={clsx('h-full rounded-full transition-all duration-700', color)}
        style={{ width: `${Math.min(pct, 100)}%` }}
      />
    </div>
  )
}

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span className={clsx(
      'inline-block w-2 h-2 rounded-full mr-2',
      ok ? 'bg-emerald-500 animate-pulse' : 'bg-rose-500',
    )} />
  )
}

function JobRow({ job, isDark }: { job: ScheduledJob; isDark: boolean }) {
  const countdown = useCountdown(job.next_run_unix)
  const schedule = JOB_SCHEDULE[job.id] ?? '—'
  const statusColor =
    job.last_status === 'done'  ? (isDark ? 'text-emerald-400' : 'text-emerald-600') :
    job.last_status === 'error' ? (isDark ? 'text-rose-400'    : 'text-rose-600')    :
    isDark ? 'text-slate-500' : 'text-gray-400'

  return (
    <tr className={clsx(
      'border-b text-xs transition-colors',
      isDark ? 'border-slate-700/30 hover:bg-slate-700/20' : 'border-gray-100 hover:bg-gray-50',
    )}>
      <td className={clsx('py-2 px-3 font-mono font-semibold', isDark ? 'text-amber-300' : 'text-indigo-700')}>
        {job.name}
      </td>
      <td className={clsx('py-2 px-3 font-mono', isDark ? 'text-slate-400' : 'text-gray-500')}>
        {schedule}
      </td>
      <td className={clsx('py-2 px-3 font-mono font-bold tabular-nums', isDark ? 'text-slate-100' : 'text-gray-800')}>
        {countdown}
      </td>
      <td className="py-2 px-3">
        <LatencyPill ms={job.last_latency_ms} isDark={isDark} />
      </td>
      <td className={clsx('py-2 px-3 font-mono font-semibold uppercase', statusColor)}>
        {job.last_status ?? '—'}
      </td>
    </tr>
  )
}

// ── Log terminal ──────────────────────────────────────────────────────────────
function LogTerminal({ lines, isDark }: { lines: string[]; isDark: boolean }) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const prevLen = useRef(0)

  useEffect(() => {
    if (lines.length !== prevLen.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
      prevLen.current = lines.length
    }
  }, [lines.length])

  return (
    <div
      ref={scrollRef}
      className={clsx(
        'font-mono text-xs leading-5 overflow-y-auto h-56 rounded-lg px-3 py-2 border',
        isDark ? 'bg-slate-950 border-slate-700/40' : 'bg-gray-950 border-gray-800',
      )}
    >
      {lines.length === 0 ? (
        <span className="text-slate-600">Awaiting log stream…</span>
      ) : (
        lines.map((raw, idx) => {
          let entry: ParsedLogLine | null = null
          try { entry = JSON.parse(raw) } catch { /* raw line */ }

          if (!entry) return (
            <div key={idx} className="text-slate-500">{raw}</div>
          )

          const levelStyle = LOG_LEVEL_STYLE[entry.level] ?? 'text-slate-400'
          return (
            <div key={idx} className="flex gap-2 min-w-0">
              <span className="text-slate-600 shrink-0">{entry.ts?.slice(11, 19) ?? ''}</span>
              <span className={clsx('shrink-0 w-10 font-bold', levelStyle)}>{entry.level}</span>
              <span className="text-cyan-500 shrink-0">[{entry.job}]</span>
              <span className={clsx('truncate', levelStyle === 'text-rose-400' ? 'text-rose-300' : 'text-slate-300')}>
                {entry.msg}
                {entry.latency_ms && <span className="text-slate-500 ml-1">· {entry.latency_ms}ms</span>}
              </span>
            </div>
          )
        })
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// Main component
// ══════════════════════════════════════════════════════════════════════════════
function SystemTelemetryMain({ isDark = true, tabs }: { isDark?: boolean; tabs?: ReactNode }) {
  const [status, setStatus]           = useState<TelemetryStatus | null>(null)
  const [logLines, setLogLines]       = useState<string[]>([])
  const [autopilotOn, setAutopilotOn] = useState(true)
  const [toggling, setToggling]       = useState(false)
  const [error, setError]             = useState<string | null>(null)

  // ── Fetch status every 10s ────────────────────────────────────────────────
  const fetchStatus = useCallback(async () => {
    try {
      const res = await getTelemetryStatus()
      const data: TelemetryStatus = res.data
      setStatus(data)
      setAutopilotOn(data.scheduler?.autopilot?.enabled ?? true)
      setError(null)
    } catch (e: any) {
      setError('Cannot reach telemetry backend')
    }
  }, [])

  // ── Fetch logs every 5s (polling fallback; SSE proxy can be fragile) ──────
  const fetchLogs = useCallback(async () => {
    try {
      const res = await getTelemetryLogs(80)
      setLogLines(res.data ?? [])
    } catch { /* silent */ }
  }, [])

  useEffect(() => {
    // all mount probes fire concurrently — the page must paint within one slow probe, not their sum
    void Promise.allSettled([fetchStatus(), fetchLogs()])
    const statusId = setInterval(fetchStatus, 10_000)
    const logId    = setInterval(fetchLogs,   5_000)
    return () => { clearInterval(statusId); clearInterval(logId) }
  }, [fetchStatus, fetchLogs])

  // ── SSE log stream (primary, polling above is fallback) ───────────────────
  useEffect(() => {
    if (typeof window === 'undefined') return
    const es = new EventSource('/api/telemetry/logs/stream')
    es.onmessage = (e) => {
      if (!e.data || e.data.trim() === '') return
      setLogLines(prev => {
        const next = [...prev, e.data]
        return next.slice(-200)
      })
    }
    es.onerror = () => { /* SSE dropped — polling fallback handles it */ }
    return () => es.close()
  }, [])

  // ── Autopilot toggle ──────────────────────────────────────────────────────
  const handleAutopilotToggle = async () => {
    setToggling(true)
    try {
      await setAutopilot(!autopilotOn)
      setAutopilotOn(v => !v)
    } catch { /* handled by next status poll */ }
    finally { setToggling(false) }
  }

  const online  = status?.master_controller_online ?? false
  const jobs    = status?.scheduler?.jobs ?? []
  const sys     = status?.system
  const brokerMs = status?.broker_latency_ms ?? null

  const nextJob = jobs.reduce<ScheduledJob | null>((closest, job) => {
    if (!job.next_run_unix) return closest
    if (!closest || !closest.next_run_unix) return job
    return job.next_run_unix < closest.next_run_unix ? job : closest
  }, null)

  const cpuColor  = (sys?.cpu_pct  ?? 0) > 80 ? 'bg-rose-500'    : (sys?.cpu_pct  ?? 0) > 50 ? 'bg-amber-500' : 'bg-emerald-500'
  const memColor  = (sys?.mem_pct  ?? 0) > 85 ? 'bg-rose-500'    : (sys?.mem_pct  ?? 0) > 60 ? 'bg-amber-500' : 'bg-cyan-500'

  // first paint before any probe answers: skeleton, not a wall of '—'
  if (!status && !error) {
    return (
      <div className="space-y-5">
        <PageHeader code="SYS" title="System" subtitle="scheduler · jobs · latency · logs" />
        {tabs}
        <TabSkeleton />
      </div>
    )
  }

  return (
    <div className="space-y-5">

      <PageHeader code="SYS" title="System"
        status={<Chip color={online ? T.green : T.red} active>{online ? '● MASTER CONTROLLER ONLINE' : '○ CONTROLLER OFFLINE'}</Chip>}
        subtitle={status ? `scheduler · jobs · latency · logs · ${status.ist_now?.slice(11, 19)} IST` : 'scheduler · jobs · latency · logs'} />
      {tabs}
      {/* ── Data-Service & Provider Status ─────────────────────────────────── */}
      <SystemStatusWidget isDark={isDark} />
      {/* ── live program: the live NSE quote service (Breeze websocket → NSE → close) ── */}
      <LiveFeedStatus />

    <div className={clsx(
      'rounded-2xl border shadow-lg overflow-hidden',
      isDark ? 'border-slate-700/50 bg-slate-900/60' : 'border-gray-200 bg-white',
    )}>
      {/* ── Header bar ────────────────────────────────────────────────────── */}
      <div className={clsx(
        'flex items-center justify-between px-5 py-3 border-b',
        isDark ? 'border-slate-700/40 bg-slate-900/80' : 'border-gray-200 bg-gray-50',
      )}>
        <div className="flex items-center gap-3">
          <span style={{ width: 3, height: 12, background: T.amber }} />
          <div>
            <h2 className={clsx('text-sm font-bold tracking-widest uppercase', isDark ? 'text-slate-100' : 'text-gray-900')}>
              System Telemetry
            </h2>
            <p className={clsx('text-xs', isDark ? 'text-slate-500' : 'text-gray-400')}>
              <StatusDot ok={online} />
              {online ? 'Master controller online' : 'Master controller offline'}
              {status && <span className="ml-2">· {status.ist_now?.slice(11, 19)} IST</span>}
            </p>
          </div>
        </div>

        {/* AUTOPILOT TOGGLE */}
        <button
          onClick={handleAutopilotToggle}
          disabled={toggling || !online}
          className={clsx(
            'relative flex items-center gap-2.5 px-5 py-2 rounded-full text-sm font-black tracking-wider uppercase transition-all duration-300 border-2',
            toggling && 'opacity-60 cursor-wait',
            !online && 'opacity-40 cursor-not-allowed',
            autopilotOn
              ? isDark
                ? 'bg-emerald-500/20 border-emerald-400/60 text-emerald-300 shadow-lg shadow-emerald-500/20'
                : 'bg-emerald-600 border-emerald-600 text-white shadow-md shadow-emerald-200'
              : isDark
                ? 'bg-rose-500/10 border-rose-500/40 text-rose-400'
                : 'bg-rose-50 border-rose-300 text-rose-600',
          )}
        >
          <span className={clsx(
            'w-2.5 h-2.5 rounded-full',
            autopilotOn ? 'bg-emerald-400 shadow-sm shadow-emerald-400 animate-pulse' : 'bg-rose-500',
          )} />
          AUTOPILOT: {autopilotOn ? 'ON' : 'OFF'}
        </button>
      </div>

      {error && (
        <div className="px-5 py-2 text-xs text-rose-400 bg-rose-950/30 border-b border-rose-900/30">
          ⚠ {error}
        </div>
      )}

      <div className="p-5 space-y-5">
        {/* ── KPI row ─────────────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">

          {/* Next Job */}
          <div className={clsx(
            'rounded-xl p-3.5 border',
            isDark ? 'border-slate-700/40 bg-slate-800/40' : 'border-gray-200 bg-gray-50',
          )}>
            <p className={clsx('text-xs font-semibold uppercase tracking-wider mb-1', isDark ? 'text-slate-500' : 'text-gray-400')}>
              Next Job
            </p>
            <p className={clsx('text-xs font-mono truncate mb-1', isDark ? 'text-slate-300' : 'text-gray-700')}>
              {nextJob?.name ?? '—'}
            </p>
            <NextJobCountdown nextRunUnix={nextJob?.next_run_unix ?? null} isDark={isDark} />
          </div>

          {/* Broker Latency */}
          <div className={clsx(
            'rounded-xl p-3.5 border',
            isDark ? 'border-slate-700/40 bg-slate-800/40' : 'border-gray-200 bg-gray-50',
          )}>
            <p className={clsx('text-xs font-semibold uppercase tracking-wider mb-1', isDark ? 'text-slate-500' : 'text-gray-400')}>
              Broker Latency
            </p>
            <div className="flex items-end gap-1 mt-2">
              {brokerMs !== null ? (
                <>
                  <span className={clsx(
                    'text-2xl font-black font-mono tabular-nums',
                    brokerMs < 50   ? (isDark ? 'text-emerald-400' : 'text-emerald-600') :
                    brokerMs < 200  ? (isDark ? 'text-amber-400'   : 'text-amber-600')   :
                                      (isDark ? 'text-rose-400'    : 'text-rose-600'),
                  )}>
                    {brokerMs.toFixed(0)}
                  </span>
                  <span className={clsx('text-xs pb-1', isDark ? 'text-slate-500' : 'text-gray-400')}>ms</span>
                </>
              ) : (
                <span className={clsx('text-2xl font-black', isDark ? 'text-slate-600' : 'text-gray-300')}>—</span>
              )}
            </div>
            <p className={clsx('text-xs mt-1', isDark ? 'text-slate-600' : 'text-gray-400')}>ICICI execution svc</p>
          </div>

          {/* CPU */}
          <div className={clsx(
            'rounded-xl p-3.5 border',
            isDark ? 'border-slate-700/40 bg-slate-800/40' : 'border-gray-200 bg-gray-50',
          )}>
            <div className="flex items-center justify-between mb-1">
              <p className={clsx('text-xs font-semibold uppercase tracking-wider', isDark ? 'text-slate-500' : 'text-gray-400')}>CPU</p>
              <span className={clsx(
                'text-sm font-black font-mono',
                (sys?.cpu_pct ?? 0) > 80 ? (isDark ? 'text-rose-400'    : 'text-rose-600')    :
                (sys?.cpu_pct ?? 0) > 50 ? (isDark ? 'text-amber-400'   : 'text-amber-600')   :
                                            (isDark ? 'text-emerald-400' : 'text-emerald-600'),
              )}>
                {sys?.cpu_pct?.toFixed(1) ?? '—'}%
              </span>
            </div>
            <MiniBar pct={sys?.cpu_pct ?? 0} color={cpuColor} />
          </div>

          {/* Memory */}
          <div className={clsx(
            'rounded-xl p-3.5 border',
            isDark ? 'border-slate-700/40 bg-slate-800/40' : 'border-gray-200 bg-gray-50',
          )}>
            <div className="flex items-center justify-between mb-1">
              <p className={clsx('text-xs font-semibold uppercase tracking-wider', isDark ? 'text-slate-500' : 'text-gray-400')}>Memory</p>
              <span className={clsx(
                'text-sm font-black font-mono',
                (sys?.mem_pct ?? 0) > 85 ? (isDark ? 'text-rose-400'  : 'text-rose-600')  :
                (sys?.mem_pct ?? 0) > 60 ? (isDark ? 'text-amber-400' : 'text-amber-600') :
                                            (isDark ? 'text-cyan-400'  : 'text-cyan-600'),
              )}>
                {sys?.mem_pct?.toFixed(1) ?? '—'}%
              </span>
            </div>
            <MiniBar pct={sys?.mem_pct ?? 0} color={memColor} />
            {sys && (
              <p className={clsx('text-xs mt-1', isDark ? 'text-slate-600' : 'text-gray-400')}>
                {sys.mem_used_gb}GB / {sys.mem_total_gb}GB
              </p>
            )}
          </div>
        </div>

        {/* ── Job schedule table ───────────────────────────────────────────── */}
        {jobs.length > 0 && (
          <div className={clsx('rounded-xl border overflow-hidden', isDark ? 'border-slate-700/40' : 'border-gray-200')}>
            <table className="w-full">
              <thead>
                <tr className={clsx(
                  'text-xs font-bold uppercase tracking-wider border-b',
                  isDark ? 'border-slate-700/40 bg-slate-800/60 text-slate-500' : 'border-gray-100 bg-gray-50 text-gray-400',
                )}>
                  <th className="py-2 px-3 text-left">Job</th>
                  <th className="py-2 px-3 text-left">Schedule (IST)</th>
                  <th className="py-2 px-3 text-left">Next Run In</th>
                  <th className="py-2 px-3 text-left">Last Latency</th>
                  <th className="py-2 px-3 text-left">Status</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map(job => <JobRow key={job.id} job={job} isDark={isDark} />)}
              </tbody>
            </table>
          </div>
        )}

        {/* ── Live log terminal ────────────────────────────────────────────── */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <p className={clsx('text-xs font-bold uppercase tracking-wider', isDark ? 'text-slate-500' : 'text-gray-400')}>
              Live System Logs
            </p>
            <span className={clsx('text-xs font-mono', isDark ? 'text-slate-600' : 'text-gray-400')}>
              {logLines.length} lines
            </span>
          </div>
          <LogTerminal lines={logLines} isDark={isDark} />
        </div>
      </div>
    </div>
    </div>
  )
}

// ── Next-job countdown (extracted to avoid stale closure in table) ────────────
function NextJobCountdown({ nextRunUnix, isDark }: { nextRunUnix: number | null; isDark: boolean }) {
  const label = useCountdown(nextRunUnix)
  return (
    <p className={clsx(
      'text-lg font-black font-mono tabular-nums',
      isDark ? 'text-amber-300' : 'text-indigo-700',
    )}>
      {label}
    </p>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// SYS › SYSTEM | DATA (terminal v2 PLAN 1.4; O-T14 default: a sub-view, GO alias DATA, header chip DATA n STALE)
// ══════════════════════════════════════════════════════════════════════════════
export function SystemTelemetry({ isDark = true }: { isDark?: boolean }) {
  const [sub, setSub] = useSubView(['system', 'data'] as const, 'system')
  const tabs = <Tabs items={[{ id: 'system', label: 'System · services · jobs · logs' }, { id: 'data', label: 'DATA · freshness of every dataset' }]}
    active={sub} onChange={setSub} />
  if (sub === 'data') {
    return (
      <div className="space-y-5">
        <PageHeader code="SYS" title="System" subtitle="DATA · every catalogued dataset: stored as-of, expected-by, sessions behind, catch-up" />
        {tabs}
        <DataHealthView />
      </div>
    )
  }
  return <SystemTelemetryMain isDark={isDark} tabs={tabs} />
}

'use client'

import { Z } from '@/lib/z'
import { apiError } from '@/lib/errors'
import { TickerLink, ResearchNote, undatedSource } from '@/components/terminal'

import { useEffect, useState, useCallback, useRef } from 'react'
import { Btn, Chip, Empty, ErrorBox, Loading, PageHeader, Panel, T, MINUS, fmtInrPx, fmtPct } from '@/components/terminal'
import { executionPolicy, type ExecPolicy } from '@/components/portfolio/policy'
import { iciciErrorKind, iciciIssue } from '@/components/portfolio/iciciState'
import { goToPage } from '@/lib/navigate'
import { openExternal } from '@/lib/platform'
import clsx from 'clsx'
import {
  getExecutionStatus,
  getLivePositions,
  getExecutionOrders,
  setExecutionMode,
  setActiveModel,
  executeLiquidate,
  resetEngine,
} from '@/lib/api'
import {
  getICICIConnectionStatus,
  getPositionSummary,
  saveICICICredentials,
  updateSessionToken,
  getTradingConfig,
} from '@/lib/api'

interface EngineStatus {
  available: boolean
  mode: 'PAPER' | 'LIVE'
  state: 'ACTIVE' | 'HALTED' | 'COOLING' | 'UNAVAILABLE'
  active_model: string
  equity: number
  equity_start_of_day: number
  daily_pnl_inr: number
  daily_pnl_pct: number
  daily_loss_limit_pct: number
  kill_switch_headroom_pct: number
  unrealized_pnl_inr: number
  open_positions: number
  kill_switch_reason: string
  available_models: string[]
  /** PAPER ONLY guard (ui-api routers/execution.py): false = LIVE is refused on this terminal */
  live_allowed?: boolean
  mode_policy?: 'PAPER_ONLY' | 'LIVE_ALLOWED'
}

interface LivePosition {
  symbol: string
  quantity: number
  avg_entry_price: number
  ltp: number
  unrealized_pnl: number
  unrealized_pnl_pct: number
  market_value: number
  signal_source: string
  stop_loss_price: number
  entry_time: string
}

interface OrderRecord {
  order_id: string
  symbol: string
  side: string
  quantity: number
  price: number
  mode: string
  status: string
  signal_source: string
  timestamp: string
  notes: string
}

const REFRESH_INTERVAL_MS = 8000

const MODEL_COLORS: Record<string, string> = {
  'XGBoost':              'bg-violet-500/20 text-violet-300 border-violet-500/40',
  'RL Agent':             'bg-cyan-500/20 text-cyan-300 border-cyan-500/40',
  'XGBoost+RL Ensemble':  'bg-amber-500/20 text-amber-300 border-amber-500/40',
  'Manual':               'bg-slate-500/20 text-slate-300 border-slate-500/40',
  'KILL_SWITCH':          'bg-rose-500/20 text-rose-300 border-rose-500/40',
}

/** Rupee amount in Indian units (C1-08 / CT-11): crore and lakh, else the full amount (₹10,000.00, never ₹10.0K). */
function fmt(n: number): string {
  const sign = n < 0 ? MINUS : '', a = Math.abs(n)
  if (a >= 1e7) return `${sign}${(a / 1e7).toFixed(2)} cr`
  if (a >= 1e5) return `${sign}${(a / 1e5).toFixed(2)} L`
  return `${sign}${a.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}
/** Signed rupee amount: '+₹1,234.00' / '−₹1,234.00' (the sign used to be dropped for losses) */
const signedRs = (n: number): string => `${n > 0 ? '+' : n < 0 ? MINUS : ''}₹${fmt(Math.abs(n))}`

function fmtTime(iso: string): string {
  try { return new Date(iso).toLocaleTimeString('en-IN', { hour12: false }) }
  catch { return iso }
}

// ── Daily Loss Meter ──────────────────────────────────────────────────────────
function DailyLossMeter({ status, isDark }: { status: EngineStatus; isDark: boolean }) {
  const used = Math.abs(Math.min(status.daily_pnl_pct, 0))
  const limit = status.daily_loss_limit_pct
  const pct = Math.min((used / limit) * 100, 100)
  const danger = pct >= 80
  const critical = pct >= 95

  return (
    <div className={clsx(
      'rounded-xl border p-4',
      critical
        ? 'border-rose-500 bg-rose-950/40 animate-pulse'
        : danger
          ? 'border-orange-500/60 bg-orange-950/30'
          : isDark ? 'border-slate-700/50 bg-slate-800/40' : 'border-gray-200 bg-white'
    )}>
      <div className="flex items-center justify-between mb-2">
        <span className={clsx(
          'text-xs font-bold uppercase tracking-wider',
          critical ? 'text-rose-400' : danger ? 'text-orange-400' : isDark ? 'text-slate-400' : 'text-gray-500'
        )}>
          Daily Loss Guard {critical ? '⚠ CRITICAL' : danger ? '⚠ WARNING' : ''}
        </span>
        <span className={clsx(
          'text-sm font-black tabular-nums',
          status.daily_pnl_pct < 0 ? 'text-rose-400' : 'text-emerald-400'
        )}>
          {fmtPct(status.daily_pnl_pct, 3)}
        </span>
      </div>
      <div className={clsx('w-full h-3 rounded-full overflow-hidden', isDark ? 'bg-slate-700' : 'bg-gray-200')}>
        <div
          className={clsx(
            'h-full rounded-full transition-all duration-500',
            critical ? 'bg-rose-500' : danger ? 'bg-orange-500' : 'bg-emerald-500'
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="flex justify-between mt-1.5 text-xs">
        <span className={clsx(isDark ? 'text-slate-500' : 'text-gray-400')}>
          ₹{fmt(Math.abs(status.daily_pnl_inr))} used
        </span>
        <span className={clsx(isDark ? 'text-slate-500' : 'text-gray-400')}>
          Limit: −{limit.toFixed(1)}% (₹{fmt(status.equity_start_of_day * limit / 100)})
        </span>
      </div>
    </div>
  )
}

// ── Control Panel ─────────────────────────────────────────────────────────────
function ControlPanel({
  status,
  policy,
  isDark,
  onModeChange,
  onModelChange,
  onKillSwitch,
  onReset,
  busy,
}: {
  status: EngineStatus
  policy: ExecPolicy
  isDark: boolean
  onModeChange: (mode: 'PAPER' | 'LIVE') => void
  onModelChange: (model: string) => void
  onKillSwitch: () => void
  onReset: () => void
  busy: boolean
}) {
  const [showLiveConfirm, setShowLiveConfirm] = useState(false)
  const [showKillConfirm, setShowKillConfirm] = useState(false)
  // PAPER ONLY (C1-trader-ux-04): never draw LIVE as selected or live-green when the server refuses LIVE
  const isLive = policy.showLiveSelected
  const isHalted = status.state === 'HALTED'
  const paper = policy.paperOnly

  return (
    <div className={clsx(
      'rounded-2xl border p-5 space-y-5',
      isHalted
        ? 'border-rose-500 bg-rose-950/30'
        : isDark ? 'border-slate-700/50 bg-slate-900/60' : 'border-gray-200 bg-white shadow-sm'
    )}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className={clsx(
            'w-3 h-3 rounded-full',
            isHalted
              ? 'bg-rose-500'
              : isLive
                ? 'bg-emerald-500 animate-pulse'
                : 'bg-amber-400'
          )} />
          <h2 className={clsx(
            'text-base font-black tracking-tight',
            isHalted ? 'text-rose-400' : isDark ? 'text-slate-100' : 'text-gray-900'
          )}>
            Execution Control Panel
          </h2>
          {/* CT-06: the legacy engine is dormant (autopilot OFF); its raw 'ACTIVE' (= not halted) read as running */}
          <span className={clsx(
            'text-xs font-bold px-2 py-0.5 rounded-full border',
            isHalted
              ? 'bg-rose-500/20 text-rose-400 border-rose-500/40'
              : isLive
                ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                : 'bg-slate-500/15 text-slate-400 border-slate-500/30'
          )} title={policy.statusKnown ? `engine state ${status.state} · autopilot OFF (the monthly strategy runs on DESK)` : 'execution status unavailable'}>
            {isHalted ? 'HALTED' : !policy.statusKnown ? 'STATUS UNKNOWN' : status.state === 'UNAVAILABLE' ? 'OFFLINE' : 'LEGACY · DORMANT'}
          </span>
        </div>
        {isHalted && (
          <button
            onClick={onReset}
            disabled={busy}
            className="px-3 py-1.5 rounded-lg text-xs font-bold bg-slate-700 hover:bg-slate-600 text-slate-100 border border-slate-600 transition-all"
          >
            Reset Engine
          </button>
        )}
      </div>

      {isHalted && status.kill_switch_reason && (
        <div className="rounded-lg border border-rose-500/50 bg-rose-950/40 p-3 text-sm text-rose-300 font-mono">
          <span className="font-bold text-rose-400">HALT REASON: </span>
          {status.kill_switch_reason}
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 items-end">
        {/* Model Selector */}
        <div className="space-y-1.5">
          <label className={clsx('text-xs font-semibold uppercase tracking-wider', isDark ? 'text-slate-400' : 'text-gray-500')}>
            Active Model
          </label>
          <select
            value={status.active_model}
            onChange={(e) => onModelChange(e.target.value)}
            disabled={isHalted || busy || !policy.statusKnown}
            className={clsx(
              'w-full rounded-lg border px-3 py-2.5 text-sm font-semibold transition-all focus:outline-none focus:ring-2',
              isDark
                ? 'bg-slate-800 border-slate-600 text-slate-100 focus:ring-amber-500/40'
                : 'bg-white border-gray-300 text-gray-900 focus:ring-indigo-500',
              (isHalted || busy || !policy.statusKnown) && 'opacity-50 cursor-not-allowed'
            )}
          >
            {(status.available_models || ['XGBoost', 'RL Agent', 'XGBoost+RL Ensemble', 'Manual']).map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </div>

        {/* PAPER / LIVE Toggle */}
        <div className="space-y-1.5">
          <label className={clsx('text-xs font-semibold uppercase tracking-wider', isDark ? 'text-slate-400' : 'text-gray-500')}>
            Execution Mode
          </label>
          <div className={clsx(
            'flex rounded-lg border overflow-hidden',
            isDark ? 'border-slate-600' : 'border-gray-300'
          )}>
            <button
              onClick={() => onModeChange('PAPER')}
              disabled={isHalted || busy || !isLive}
              className={clsx(
                'flex-1 py-2.5 text-sm font-bold transition-all',
                !isLive
                  ? 'bg-amber-500 text-black'
                  : isDark
                    ? 'bg-slate-800 text-slate-400 hover:bg-slate-700 hover:text-slate-200'
                    : 'bg-white text-gray-500 hover:bg-gray-50',
                (isHalted || busy) && 'opacity-50 cursor-not-allowed'
              )}
            >
              PAPER
            </button>
            {policy.liveSelectable ? (
              <button
                onClick={() => setShowLiveConfirm(true)}
                disabled={isHalted || busy || status.mode === 'LIVE'}
                className={clsx(
                  'flex-1 py-2.5 text-sm font-bold transition-all',
                  status.mode === 'LIVE'
                    ? 'bg-emerald-500 text-black'
                    : isDark
                      ? 'bg-slate-800 text-slate-400 hover:bg-slate-700 hover:text-rose-300'
                      : 'bg-white text-gray-500 hover:bg-red-50 hover:text-red-600',
                  (isHalted || busy) && 'opacity-50 cursor-not-allowed'
                )}
              >
                LIVE
              </button>
            ) : (
              <button
                disabled
                aria-disabled="true"
                data-testid="live-disabled"
                title="LIVE is disabled: SuryaDhana runs PAPER ONLY. ui-api refuses LIVE mode and every live order."
                className="flex-1 py-2.5 text-sm font-bold bg-slate-800 text-slate-500 cursor-not-allowed line-through"
              >
                LIVE
              </button>
            )}
          </div>
          {paper && (
            <p className="text-xs" style={{ color: T.muted }} data-testid="paper-only-note">
              PAPER ONLY · LIVE is disabled on this terminal: ui-api refuses LIVE mode and every live order.
            </p>
          )}
        </div>

        {/* Kill Switch */}
        <div className="space-y-1.5">
          <label className={clsx('text-xs font-semibold uppercase tracking-wider text-rose-500')}>
            Emergency Control
          </label>
          <button
            onClick={() => setShowKillConfirm(true)}
            disabled={!policy.liquidateAllowed || busy}
            title={!policy.statusKnown ? 'Disabled: the execution status is unavailable'
              : paper ? `Closes every position in the PAPER book (${status.open_positions} open) and halts the legacy engine. Nothing is sent to the broker.` : undefined}
            className={clsx(
              'w-full py-2.5 rounded-lg text-sm font-black tracking-wide transition-all border-2',
              !policy.liquidateAllowed
                ? 'bg-slate-700 border-slate-600 text-slate-500 cursor-not-allowed'
                : status.open_positions === 0
                  // CT-06: nothing open: an outline, not a full red alarm button (it still halts the engine, with its confirm)
                  ? 'bg-transparent border-rose-500/60 text-rose-300 hover:bg-rose-950/40'
                  : 'bg-rose-600 border-rose-500 text-white hover:bg-rose-500 hover:border-rose-400 hover:scale-[1.02] active:scale-95 shadow-lg shadow-rose-500/30',
              busy && 'opacity-50 cursor-not-allowed'
            )}
          >
            {isHalted ? 'ENGINE HALTED' : policy.liquidateLabel}
          </button>
        </div>
      </div>

      {policy.engineLiveMismatch && (
        <div className="rounded-lg border p-3 text-sm font-mono" data-testid="engine-live-mismatch"
             style={{ borderColor: `${T.amber}88`, color: T.amber }}>
          ▲ The legacy engine reported LIVE, but this terminal runs PAPER ONLY: ui-api switches it back to PAPER and
          refuses every order, so nothing can reach the broker.
        </div>
      )}

      {/* LIVE mode confirmation dialog (never reachable on a PAPER ONLY terminal) */}
      {showLiveConfirm && policy.liveSelectable && (
        <div className="rounded-xl border border-rose-500 bg-rose-950/60 p-4 space-y-3">
          <p className="text-rose-300 font-bold text-sm">
            ▲ You are switching to LIVE mode. Real orders will be sent to ICICI Breeze.
            Real money will be traded. Confirm?
          </p>
          <div className="flex gap-3">
            <button
              onClick={() => { onModeChange('LIVE'); setShowLiveConfirm(false) }}
              className="px-4 py-2 rounded-lg bg-rose-600 text-white text-sm font-bold hover:bg-rose-500"
            >
              Yes, Go LIVE
            </button>
            <button
              onClick={() => setShowLiveConfirm(false)}
              className="px-4 py-2 rounded-lg bg-slate-700 text-slate-200 text-sm font-semibold hover:bg-slate-600"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Kill switch confirmation dialog */}
      {showKillConfirm && (
        <div className="rounded-xl border-2 border-rose-500 bg-rose-950/80 p-5 space-y-4">
          <div className="flex items-start gap-3">
            <span className="text-3xl" style={{ color: T.red }}>▲</span>
            <div>
              <p className="text-rose-200 font-black text-base">{paper ? 'LIQUIDATE ALL PAPER POSITIONS?' : 'LIQUIDATE ALL POSITIONS?'}</p>
              <p className="text-rose-400 text-sm mt-1">
                This will immediately sell ALL open positions and halt the engine.
                No new orders will be accepted until you manually reset.
                This action CANNOT be undone automatically.
                {paper && ' PAPER ONLY: this closes the paper book; nothing is sent to the broker.'}
              </p>
            </div>
          </div>
          <div className="flex gap-3">
            <button
              onClick={() => { onKillSwitch(); setShowKillConfirm(false) }}
              className="px-6 py-3 rounded-xl bg-rose-600 text-white text-sm font-black hover:bg-rose-500 border-2 border-rose-400 shadow-lg shadow-rose-500/40 transition-all"
            >
              CONFIRM LIQUIDATE
            </button>
            <button
              onClick={() => setShowKillConfirm(false)}
              className="px-5 py-3 rounded-xl bg-slate-700 text-slate-200 text-sm font-semibold hover:bg-slate-600"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── KPI Strip ─────────────────────────────────────────────────────────────────
function KPIStrip({ status, isDark }: { status: EngineStatus; isDark: boolean }) {
  const dailyPositive = status.daily_pnl_inr >= 0
  const unrealizedPositive = status.unrealized_pnl_inr >= 0

  const cards = [
    {
      label: 'Net Equity',
      value: `₹${fmt(status.equity)}`,
      sub: `Start: ₹${fmt(status.equity_start_of_day)}`,
      color: 'indigo',
    },
    {
      label: 'Daily PnL',
      value: signedRs(status.daily_pnl_inr),
      sub: fmtPct(status.daily_pnl_pct, 3),
      color: dailyPositive ? 'emerald' : 'rose',
    },
    {
      label: 'Unrealized PnL',
      value: signedRs(status.unrealized_pnl_inr),
      sub: `${status.open_positions} position${status.open_positions !== 1 ? 's' : ''}`,
      color: unrealizedPositive ? 'cyan' : 'orange',
    },
    {
      label: 'Kill Switch Room',
      value: `${status.kill_switch_headroom_pct.toFixed(2)}%`,
      sub: `to −${status.daily_loss_limit_pct.toFixed(1)}% limit`,
      color: status.kill_switch_headroom_pct < 0.5 ? 'rose' : status.kill_switch_headroom_pct < 1 ? 'orange' : 'slate',
    },
  ]

  const colorMap: Record<string, { card: string; value: string }> = {
    indigo:  { card: isDark ? 'border-indigo-700/40 bg-indigo-950/30' : 'border-indigo-200 bg-indigo-50',  value: isDark ? 'text-indigo-300' : 'text-indigo-900' },
    emerald: { card: isDark ? 'border-emerald-700/40 bg-emerald-950/30' : 'border-emerald-200 bg-emerald-50', value: isDark ? 'text-emerald-300' : 'text-emerald-800' },
    rose:    { card: isDark ? 'border-rose-700/40 bg-rose-950/30' : 'border-rose-200 bg-rose-50',    value: isDark ? 'text-rose-300' : 'text-rose-800' },
    cyan:    { card: isDark ? 'border-cyan-700/40 bg-cyan-950/30' : 'border-cyan-200 bg-cyan-50',    value: isDark ? 'text-cyan-300' : 'text-cyan-800' },
    orange:  { card: isDark ? 'border-orange-700/40 bg-orange-950/30' : 'border-orange-200 bg-orange-50', value: isDark ? 'text-orange-300' : 'text-orange-800' },
    slate:   { card: isDark ? 'border-slate-700/40 bg-slate-800/30' : 'border-gray-200 bg-gray-50',  value: isDark ? 'text-slate-200' : 'text-gray-900' },
  }

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      {cards.map(({ label, value, sub, color }) => {
        const c = colorMap[color] ?? colorMap.slate
        return (
          <div key={label} className={clsx('rounded-xl border p-4', c.card)}>
            <p className={clsx('text-xs font-semibold uppercase tracking-wider', isDark ? 'text-slate-500' : 'text-gray-400')}>
              {label}
            </p>
            <p className={clsx('text-xl font-black mt-1.5 tabular-nums', c.value)}>{value}</p>
            <p className={clsx('text-xs mt-0.5', isDark ? 'text-slate-500' : 'text-gray-400')}>{sub}</p>
          </div>
        )
      })}
    </div>
  )
}

// ── Positions Table ───────────────────────────────────────────────────────────
function PositionsTable({ positions, isDark }: { positions: LivePosition[]; isDark: boolean }) {
  if (positions.length === 0) {
    return (
      <Panel source={undatedSource('legacy engine (dormant)')} title="Open positions (0)">
        <Empty title="No active positions" hint="The engine populates positions when signals fire (autopilot is OFF)." />
      </Panel>
    )
  }

  return (
    <div className={clsx('rounded-2xl border overflow-hidden', isDark ? 'border-slate-700/50' : 'border-gray-200')}>
      <div className={clsx('px-5 py-4 border-b flex items-center justify-between', isDark ? 'border-slate-700/30 bg-slate-800/50' : 'border-gray-100 bg-gray-50')}>
        <h3 className={clsx('text-sm font-black uppercase tracking-wider', isDark ? 'text-slate-200' : 'text-gray-700')}>
          Live Positions
        </h3>
        <span className={clsx('text-xs', isDark ? 'text-slate-500' : 'text-gray-400')}>
          {positions.length} position{positions.length !== 1 ? 's' : ''}
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className={clsx('border-b', isDark ? 'border-slate-700/40 bg-slate-800/30' : 'border-gray-100 bg-gray-50')}>
              {['Symbol', 'Qty', 'Avg Entry', 'LTP', 'Mkt Value', 'Unrlzd PnL', 'Ret%', 'Signal', 'Entry Time'].map(h => (
                <th key={h} className={clsx(
                  'px-4 py-3 text-xs font-bold uppercase tracking-wide whitespace-nowrap',
                  h === 'Symbol' ? 'text-left' : 'text-right',
                  isDark ? 'text-slate-400' : 'text-gray-500'
                )}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className={clsx('divide-y', isDark ? 'divide-slate-700/30' : 'divide-gray-100')}>
            {positions.map((pos) => {
              const pnlPos = pos.unrealized_pnl >= 0
              const retPos = pos.unrealized_pnl_pct >= 0
              const stopPct = pos.stop_loss_price > 0
                ? ((pos.ltp - pos.stop_loss_price) / pos.stop_loss_price * 100)
                : null
              const nearStop = stopPct !== null && stopPct < 1

              return (
                <tr
                  key={pos.symbol}
                  className={clsx(
                    'transition-colors',
                    nearStop
                      ? isDark ? 'bg-rose-950/20 hover:bg-rose-950/30' : 'bg-rose-50 hover:bg-rose-100'
                      : isDark ? 'hover:bg-slate-700/20' : 'hover:bg-gray-50'
                  )}
                >
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      {nearStop && <span className="text-rose-500 text-xs">⚠</span>}
                      <TickerLink symbol={pos.symbol.replace('.NS', '')} style={{ fontWeight: 800 }} />
                    </div>
                  </td>
                  <td className={clsx('px-4 py-3 text-right tabular-nums', isDark ? 'text-slate-300' : 'text-gray-700')}>
                    {pos.quantity}
                  </td>
                  <td className={clsx('px-4 py-3 text-right tabular-nums', isDark ? 'text-slate-400' : 'text-gray-500')}>
                    {fmtInrPx(pos.avg_entry_price)}
                  </td>
                  <td className={clsx('px-4 py-3 text-right font-bold tabular-nums', isDark ? 'text-slate-200' : 'text-gray-800')}>
                    {fmtInrPx(pos.ltp)}
                  </td>
                  <td className={clsx('px-4 py-3 text-right tabular-nums', isDark ? 'text-slate-300' : 'text-gray-600')}>
                    ₹{fmt(pos.market_value)}
                  </td>
                  <td className={clsx('px-4 py-3 text-right font-bold tabular-nums', pnlPos ? 'text-emerald-400' : 'text-rose-400')}>
                    {signedRs(pos.unrealized_pnl)}
                  </td>
                  <td className={clsx('px-4 py-3 text-right font-bold tabular-nums text-xs', retPos ? 'text-emerald-400' : 'text-rose-400')}>
                    {fmtPct(pos.unrealized_pnl_pct, 2)}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <span className={clsx(
                      'px-2 py-0.5 rounded-full text-xs font-bold border whitespace-nowrap',
                      MODEL_COLORS[pos.signal_source] ?? MODEL_COLORS['Manual']
                    )}>
                      {pos.signal_source}
                    </span>
                  </td>
                  <td className={clsx('px-4 py-3 text-right text-xs tabular-nums', isDark ? 'text-slate-500' : 'text-gray-400')}>
                    {fmtTime(pos.entry_time)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Order Log ─────────────────────────────────────────────────────────────────
function OrderLog({ orders, isDark }: { orders: OrderRecord[]; isDark: boolean }) {
  return (
    <div className={clsx('rounded-2xl border overflow-hidden', isDark ? 'border-slate-700/50' : 'border-gray-200')}>
      <div className={clsx('px-5 py-4 border-b', isDark ? 'border-slate-700/30 bg-slate-800/50' : 'border-gray-100 bg-gray-50')}>
        <h3 className={clsx('text-sm font-black uppercase tracking-wider', isDark ? 'text-slate-200' : 'text-gray-700')}>
          Order Log
        </h3>
      </div>
      {orders.length === 0 ? (
        <div className={clsx('py-8 text-center text-sm', isDark ? 'text-slate-600' : 'text-gray-400')}>
          No orders recorded yet
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className={clsx('border-b', isDark ? 'border-slate-700/40 bg-slate-800/30' : 'border-gray-100 bg-gray-50')}>
                {['Time', 'Symbol', 'Side', 'Qty', 'Price', 'Mode', 'Status', 'Signal', 'Notes'].map(h => (
                  <th key={h} className={clsx(
                    'px-3 py-2.5 text-xs font-bold uppercase tracking-wide',
                    ['Time', 'Symbol', 'Notes'].includes(h) ? 'text-left' : 'text-right',
                    isDark ? 'text-slate-400' : 'text-gray-500'
                  )}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className={clsx('divide-y text-xs', isDark ? 'divide-slate-700/20' : 'divide-gray-50')}>
              {orders.map((o) => (
                <tr key={o.order_id} className={clsx(
                  'transition-colors',
                  isDark ? 'hover:bg-slate-700/20' : 'hover:bg-gray-50'
                )}>
                  <td className={clsx('px-3 py-2.5 tabular-nums', isDark ? 'text-slate-500' : 'text-gray-400')}>
                    {fmtTime(o.timestamp)}
                  </td>
                  <td className={clsx('px-3 py-2.5 font-bold', isDark ? 'text-slate-200' : 'text-gray-900')}>
                    {o.symbol.replace('.NS', '')}
                  </td>
                  <td className={clsx(
                    'px-3 py-2.5 text-right font-bold',
                    o.side === 'BUY' ? 'text-emerald-400' : 'text-rose-400'
                  )}>
                    {o.side}
                  </td>
                  <td className={clsx('px-3 py-2.5 text-right tabular-nums', isDark ? 'text-slate-300' : 'text-gray-700')}>
                    {o.quantity}
                  </td>
                  <td className={clsx('px-3 py-2.5 text-right tabular-nums', isDark ? 'text-slate-400' : 'text-gray-600')}>
                    {fmtInrPx(o.price)}
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <span className={clsx(
                      'px-1.5 py-0.5 rounded text-xs font-bold',
                      o.mode === 'LIVE'
                        ? 'bg-emerald-500/20 text-emerald-400'
                        : 'bg-amber-500/20 text-amber-400'
                    )}>
                      {o.mode}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <span className={clsx(
                      'px-1.5 py-0.5 rounded text-xs font-bold',
                      o.status === 'FILLED'
                        ? 'bg-emerald-500/20 text-emerald-400'
                        : o.status === 'REJECTED'
                          ? 'bg-rose-500/20 text-rose-400'
                          : 'bg-slate-500/20 text-slate-400'
                    )}>
                      {o.status}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <span className={clsx(
                      'px-1.5 py-0.5 rounded text-xs font-semibold border',
                      MODEL_COLORS[o.signal_source] ?? MODEL_COLORS['Manual']
                    )}>
                      {o.signal_source}
                    </span>
                  </td>
                  <td className={clsx('px-3 py-2.5 font-mono max-w-48 truncate', isDark ? 'text-slate-500' : 'text-gray-400')}>
                    {o.notes}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── ICICI Connection Banner (shown when not connected in LIVE mode) ────────────
function ICICIBanner({ isDark }: { isDark: boolean }) {
  const [status, setStatus] = useState<any>(null)
  const [token, setToken] = useState('')
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  useEffect(() => {
    getICICIConnectionStatus().then(r => setStatus(r.data)).catch(() => {})
  }, [])

  const connect = async () => {
    if (!token.trim()) return
    setSaving(true)
    setMsg(null)
    try {
      const res = await updateSessionToken(token.trim())
      if (res.data?.connected) {
        setMsg({ ok: true, text: 'Connected to ICICI Breeze.' })
        const s = await getICICIConnectionStatus()
        setStatus(s.data)
      } else {
        setMsg({ ok: false, text: res.data?.error || 'Token rejected.' })
      }
    } catch {
      setMsg({ ok: false, text: 'Connection failed.' })
    } finally {
      setSaving(false)
    }
  }

  if (!status || status.connected) return null
  // P4: a network outage is not an expired session (no login push); a missing / rejected key needs BRKR first
  const kind = iciciErrorKind(status)
  const issue = kind && kind !== 'expired' && kind !== 'unknown'
    ? iciciIssue(kind, { keyMissing: !(status.has_api_key && status.has_api_secret) }) : null

  return (
    <div className={clsx(
      'rounded-xl border p-4',
      isDark ? 'border-amber-600/40 bg-amber-950/20' : 'border-amber-200 bg-amber-50'
    )} data-icici-kind={kind ?? undefined}>
      <p className={clsx('text-sm font-bold mb-3', isDark ? 'text-amber-300' : 'text-amber-800')}>
        {issue ? `● ${issue.headline} · running in PAPER mode only` : '● ICICI Breeze not connected · running in PAPER mode only'}
      </p>
      {issue?.detail && <p className="text-xs mb-3" style={{ color: T.text }}>{issue.detail}</p>}
      {issue?.kind === 'network' && (
        <div className="mb-3"><Btn size="sm" onClick={() => { getICICIConnectionStatus().then(r => setStatus(r.data)).catch(() => {}) }}>↻ Recheck</Btn></div>
      )}
      {issue?.kind === 'credentials' && (
        <div className="mb-3"><Btn size="sm" onClick={() => goToPage('broker')}>Open BRKR ›</Btn></div>
      )}
      {/* The login URL carries the API key: open it in the browser, never print it (C1-trader-ux-05) */}
      {!issue && status.login_url && (
        <div className="mb-3 flex items-center gap-3">
          <Btn variant="primary" size="sm" onClick={() => openExternal(String(status.login_url))}
               title="Opens ICICI's login page in your browser">LOG IN TO ICICI ↗</Btn>
          <span className="text-xs" style={{ color: T.muted }}>then paste the redirect URL or session token below</span>
        </div>
      )}
      {!issue && <div className="flex gap-2">
        <input
          type="password"
          value={token}
          onChange={e => setToken(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && connect()}
          placeholder={status.token_hint || 'Paste redirect URL or session token'}
          className={clsx(
            'flex-1 rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2',
            isDark
              ? 'bg-slate-800 border-slate-600 text-slate-100 focus:ring-amber-500/40'
              : 'bg-white border-gray-300 text-gray-900 focus:ring-amber-400'
          )}
        />
        <button
          onClick={connect}
          disabled={saving || !token.trim()}
          className="px-4 py-2 rounded-lg bg-amber-500 text-black text-sm font-bold hover:bg-amber-400 disabled:opacity-50"
        >
          {saving ? 'Connecting…' : 'Connect'}
        </button>
      </div>}
      {msg && (
        <p className={clsx('text-xs mt-2 font-semibold', msg.ok ? 'text-emerald-400' : 'text-rose-400')}>
          {msg.ok ? '✓ ' : '✕ '}{msg.text}
        </p>
      )}
    </div>
  )
}

// ── Main LivePortfolio Component ───────────────────────────────────────────────
export function LivePortfolio({ isDark = true }: { isDark?: boolean }) {
  const [status, setStatus] = useState<EngineStatus | null>(null)
  const [positions, setPositions] = useState<LivePosition[]>([])
  const [orders, setOrders] = useState<OrderRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null)
  const [toast, setToast] = useState<{ type: 'success' | 'error'; msg: string } | null>(null)
  /** the latest GET /api/execution/status failed (null = it answered) */
  const [statusErr, setStatusErr] = useState<string | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const showToast = useCallback((type: 'success' | 'error', msg: string) => {
    setToast({ type, msg })
    setTimeout(() => setToast(null), 4000)
  }, [])

  // RUP-02: the three reads settle independently, so a positions / orders failure never throws a good status away
  // (with no status the page fails closed: STATUS UNKNOWN · PAPER ONLY, no LIVE, no LIQUIDATE)
  const refresh = useCallback(async () => {
    const [statusRes, posRes, ordersRes] = await Promise.allSettled([
      getExecutionStatus(),
      getLivePositions(),
      getExecutionOrders(30),
    ])
    if (statusRes.status === 'fulfilled' && statusRes.value.data) {
      setStatus(statusRes.value.data)
      setStatusErr(null)
      setLastRefresh(new Date())
    } else {
      setStatusErr(statusRes.status === 'rejected' ? apiError(statusRes.reason, 'execution status unavailable') : 'execution status unavailable')
    }
    if (posRes.status === 'fulfilled') setPositions(posRes.value.data?.positions || [])
    if (ordersRes.status === 'fulfilled') setOrders(ordersRes.value.data?.orders || [])
    for (const r of [statusRes, posRes, ordersRes]) if (r.status === 'rejected') console.error('LivePortfolio refresh error:', r.reason)
    setLoading(false)
  }, [])

  useEffect(() => {
    refresh()
    intervalRef.current = setInterval(refresh, REFRESH_INTERVAL_MS)
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [refresh])

  const handleModeChange = async (mode: 'PAPER' | 'LIVE') => {
    setBusy(true)
    try {
      await setExecutionMode(mode, mode === 'LIVE')
      showToast('success', `Switched to ${mode} mode`)
      await refresh()
    } catch (err: any) {
      showToast('error', apiError(err, `Failed to switch to ${mode} mode`))
    } finally {
      setBusy(false)
    }
  }

  const handleModelChange = async (model: string) => {
    setBusy(true)
    try {
      await setActiveModel(model)
      showToast('success', `Active model: ${model}`)
      await refresh()
    } catch (err: any) {
      showToast('error', `Failed to set model: ${model}`)
    } finally {
      setBusy(false)
    }
  }

  const handleKillSwitch = async () => {
    setBusy(true)
    try {
      const res = await executeLiquidate('Manual LIQUIDATE & HALT from dashboard')
      showToast(
        res.data?.halted ? 'success' : 'error',
        res.data?.halted
          ? `Liquidated ${res.data.flattened_positions?.length ?? 0} positions. Engine HALTED.`
          : 'Liquidation failed — check logs.'
      )
      await refresh()
    } catch (err: any) {
      showToast('error', apiError(err, 'Kill switch failed'))
    } finally {
      setBusy(false)
    }
  }

  const handleReset = async () => {
    setBusy(true)
    try {
      await resetEngine()
      showToast('success', 'Engine reset for new trading day')
      await refresh()
    } catch (err: any) {
      showToast('error', apiError(err, 'Engine reset failed'))
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <Loading label="Loading execution engine" />

  const defaultStatus: EngineStatus = {
    available: false,
    mode: 'PAPER',
    state: 'UNAVAILABLE',
    active_model: 'XGBoost',
    equity: 10000,
    equity_start_of_day: 10000,
    daily_pnl_inr: 0,
    daily_pnl_pct: 0,
    daily_loss_limit_pct: 2,
    kill_switch_headroom_pct: 2,
    unrealized_pnl_inr: 0,
    open_positions: 0,
    kill_switch_reason: '',
    available_models: ['XGBoost', 'RL Agent', 'XGBoost+RL Ensemble', 'Manual'],
  }

  const s = status ?? defaultStatus
  // the policy reads the SERVER's status only: the placeholder above never makes LIVE or LIQUIDATE available
  const policy = executionPolicy(status)

  return (
    <div className="space-y-3 relative">
      {/* Toast notification */}
      {toast && (
        <div className={clsx(
          'fixed top-20 right-6 px-5 py-3 rounded-xl border font-semibold text-sm shadow-2xl transition-all duration-300',
          toast.type === 'success'
            ? 'bg-emerald-900 border-emerald-500 text-emerald-200'
            : 'bg-rose-900 border-rose-500 text-rose-200'
        )} style={{ zIndex: Z.toast }}>
          {toast.type === 'success' ? '✓ ' : '✕ '}{toast.msg}
        </div>
      )}

      {/* CT-06: the strip and menu call this page Portfolio; the title says which book it is */}
      <PageHeader code="PORT" title="Portfolio · Legacy Engine"
        status={<>
          <Chip color={policy.modeTone === 'live' ? T.green : policy.modeTone === 'unknown' ? T.red : T.amber} active>{policy.modeLabel}</Chip>
          <Chip color={T.muted} title="Legacy 5-day engine: autopilot OFF; the approved strategy runs on DESK">LEGACY · DORMANT</Chip>
          {s.state === 'HALTED' ? <Chip color={T.red} active>HALTED</Chip> : null}
          {status && !status.available ? <Chip color={T.red}>ENGINE OFFLINE</Chip> : null}
          {status && statusErr ? <Chip color={T.red} title={statusErr}>STATUS STALE</Chip> : null}
        </>}
        subtitle="legacy 5-day XGBoost engine book · autopilot OFF (the monthly strategy runs on DESK)"
        right={<span style={{ fontSize: 10, color: T.dim }}>refreshed {lastRefresh?.toLocaleTimeString('en-IN', { hour12: false }) ?? '—'}</span>} />
      <ResearchNote verdict="FAIL" report="docs/PRODUCT_STRATEGY.md">
        This is the legacy 5-day engine. After real ICICI costs it loses about 45–50% a year (5 positions turned over
        weekly), which is why its autopilot is OFF. The approved strategy is the monthly Decision Desk (DESK), in paper mode.
      </ResearchNote>

      {/* ICICI connection prompt */}
      <ICICIBanner isDark={isDark} />

      {!status && (
        <ErrorBox error={`Execution status unavailable${statusErr ? ` (${statusErr})` : ''}: PAPER ONLY, LIVE and LIQUIDATE are disabled until ui-api answers`}
                  onRetry={() => { void refresh() }} />
      )}

      {/* Control Panel */}
      <ControlPanel
        status={s}
        policy={policy}
        isDark={isDark}
        onModeChange={handleModeChange}
        onModelChange={handleModelChange}
        onKillSwitch={handleKillSwitch}
        onReset={handleReset}
        busy={busy}
      />

      {/* KPI strip and loss meter: the engine's numbers only (never the placeholder's invented ₹10,000) */}
      {status && <KPIStrip status={status} isDark={isDark} />}
      {status && <DailyLossMeter status={status} isDark={isDark} />}

      {/* Positions Table */}
      <PositionsTable positions={positions} isDark={isDark} />

      {/* Order Log */}
      <OrderLog orders={orders} isDark={isDark} />
    </div>
  )
}

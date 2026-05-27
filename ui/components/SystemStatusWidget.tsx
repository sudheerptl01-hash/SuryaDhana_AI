'use client'

/**
 * SystemStatusWidget — Binds /api/data/health + /ready + /provider/status
 * to a premium "System Status" panel for the Overview & System tabs.
 *
 * Features:
 *  - Colour-coded dot indicators per service
 *  - Provider (ICICI/yfinance) connection chip
 *  - Collapsible ICICI credential configurator
 *  - Auto-polls every 30s (driven by AppContext.dataServiceStatus)
 */

import { useCallback, useState } from 'react'
import clsx from 'clsx'
import { useDataServiceStatus } from '@/context/AppContext'
import { configureDataProvider, fetchRefreshBatch } from '@/lib/api'
import { useToast } from '@/context/ToastContext'

interface Props {
  isDark?: boolean
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function StatusDot({ ok, pending }: { ok: boolean; pending?: boolean }) {
  if (pending) return (
    <span className="inline-block w-2.5 h-2.5 rounded-full bg-amber-400 animate-pulse" />
  )
  return (
    <span className={clsx(
      'inline-block w-2.5 h-2.5 rounded-full',
      ok ? 'bg-emerald-500 animate-pulse' : 'bg-rose-500',
    )} />
  )
}

function ServiceRow({
  label, ok, detail, pending = false, isDark
}: {
  label: string; ok: boolean; detail?: string; pending?: boolean; isDark: boolean
}) {
  return (
    <div className="flex items-center justify-between py-2">
      <div className="flex items-center gap-2.5">
        <StatusDot ok={ok} pending={pending} />
        <span className={clsx('text-xs font-semibold', isDark ? 'text-slate-300' : 'text-gray-700')}>
          {label}
        </span>
      </div>
      {detail && (
        <span className={clsx(
          'text-xs font-mono px-2 py-0.5 rounded-md',
          ok
            ? (isDark ? 'bg-emerald-900/40 text-emerald-300' : 'bg-emerald-50 text-emerald-700')
            : (isDark ? 'bg-rose-900/30   text-rose-400'    : 'bg-rose-50   text-rose-600'),
        )}>
          {detail}
        </span>
      )}
    </div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────

export function SystemStatusWidget({ isDark = true }: Props) {
  const { dataServiceStatus, refreshDataStatus } = useDataServiceStatus()
  const { addToast } = useToast()

  const [showConfig, setShowConfig]   = useState(false)
  const [apiKey,    setApiKey]        = useState('')
  const [apiSecret, setApiSecret]     = useState('')
  const [sessionToken, setSessionToken] = useState('')
  const [saving, setSaving]           = useState(false)
  const [quickRefreshing, setQRefreshing] = useState(false)

  const ds = dataServiceStatus
  const isUnknown = ds.lastChecked === null

  // ── Save ICICI credentials ─────────────────────────────────────────────────
  const handleSaveCredentials = useCallback(async () => {
    if (!apiKey || !apiSecret || !sessionToken) {
      addToast('All three ICICI fields are required', 'warning')
      return
    }
    setSaving(true)
    try {
      await configureDataProvider({ api_key: apiKey, api_secret: apiSecret, session_token: sessionToken })
      addToast('ICICI Breeze credentials applied — provider reconnecting', 'success')
      setShowConfig(false)
      setTimeout(refreshDataStatus, 2000) // re-poll status
    } catch (err: any) {
      addToast(
        `Credential save failed: ${err?.response?.data?.detail || err?.message || 'unknown error'}`,
        'error',
      )
    } finally {
      setSaving(false)
    }
  }, [apiKey, apiSecret, sessionToken, addToast, refreshDataStatus])

  // ── Quick single-ticker refresh ────────────────────────────────────────────
  const handleQuickRefresh = useCallback(async () => {
    setQRefreshing(true)
    try {
      const res = await fetchRefreshBatch({ tickers: ['RELIANCE', 'TCS', 'HDFCBANK'], years: 1 })
      const data = res.data
      const total = Object.values(data?.refreshed ?? {}).reduce((s: number, v: any) => s + (v as number), 0)
      addToast(`Quick refresh: ${total} rows updated`, 'success')
    } catch (err: any) {
      addToast(`Refresh failed: ${err?.response?.data?.detail || err?.message}`, 'error')
    } finally {
      setQRefreshing(false)
    }
  }, [addToast])

  const providerShort = ds.provider
    ? ds.provider.replace('Provider', '').replace('ICICIBreeze', 'ICICI Breeze').replace('DirectYahoo', 'Yahoo v8').replace('YFinance', 'yFinance')
    : 'Unknown'

  const cardBase = isDark ? 'border-slate-700/50 bg-slate-800/40' : 'border-gray-200 bg-white'
  const inputBase = clsx(
    'w-full px-3 py-2 rounded-lg text-xs font-mono border outline-none transition-colors',
    isDark
      ? 'bg-slate-900 border-slate-600 text-slate-200 placeholder-slate-500 focus:border-amber-500/60'
      : 'bg-white border-gray-300 text-gray-800 placeholder-gray-400 focus:border-indigo-400',
  )

  return (
    <div className={clsx('rounded-2xl border shadow-sm', cardBase)}>
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className={clsx(
        'flex items-center justify-between px-5 py-3 border-b',
        isDark ? 'border-slate-700/40' : 'border-gray-100',
      )}>
        <div className="flex items-center gap-2">
          <span className="text-sm">🛰️</span>
          <h3 className={clsx('text-sm font-bold tracking-widest uppercase', isDark ? 'text-slate-100' : 'text-gray-900')}>
            System Status
          </h3>
          {ds.lastChecked && (
            <span className={clsx('text-xs font-mono', isDark ? 'text-slate-500' : 'text-gray-400')}>
              · checked {new Date(ds.lastChecked).toLocaleTimeString()}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={refreshDataStatus}
            className={clsx(
              'text-xs px-2 py-1 rounded-md border transition-all',
              isDark
                ? 'border-slate-600 text-slate-400 hover:text-slate-200 hover:border-slate-500'
                : 'border-gray-200 text-gray-400 hover:text-gray-700',
            )}
            title="Refresh service status"
          >
            ↻
          </button>
          <button
            onClick={() => setShowConfig(v => !v)}
            className={clsx(
              'text-xs px-3 py-1 rounded-md border transition-all font-medium',
              showConfig
                ? (isDark ? 'bg-amber-500/20 border-amber-500/50 text-amber-300' : 'bg-indigo-50 border-indigo-300 text-indigo-600')
                : (isDark ? 'border-slate-600 text-slate-400 hover:text-slate-200' : 'border-gray-200 text-gray-400 hover:text-gray-700'),
            )}
          >
            {showConfig ? '↑ Hide Config' : '⚙ Configure ICICI'}
          </button>
        </div>
      </div>

      <div className="px-5 py-4 space-y-1">
        {/* ── Service rows ──────────────────────────────────────────────────── */}
        <div className={clsx('divide-y rounded-xl overflow-hidden border', isDark ? 'border-slate-700/30 divide-slate-700/20' : 'border-gray-100 divide-gray-100')}>
          <div className="px-4">
            <ServiceRow
              label="data-service"
              ok={ds.health === 'ok'}
              detail={isUnknown ? 'polling…' : ds.health === 'ok' ? 'healthy' : 'unreachable'}
              pending={isUnknown}
              isDark={isDark}
            />
          </div>
          <div className="px-4">
            <ServiceRow
              label="DuckDB"
              ok={ds.ready}
              detail={isUnknown ? 'polling…' : ds.ready ? 'mounted' : 'not ready'}
              pending={isUnknown}
              isDark={isDark}
            />
          </div>
          <div className="px-4">
            <ServiceRow
              label={`Provider: ${providerShort}`}
              ok={ds.connected}
              detail={ds.connected ? 'connected' : 'disconnected'}
              pending={isUnknown}
              isDark={isDark}
            />
          </div>
        </div>

        {/* ── Provider chip ─────────────────────────────────────────────────── */}
        {ds.provider && (
          <div className="flex items-center gap-2 pt-1">
            <span className={clsx(
              'inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-1 rounded-full border',
              ds.connected
                ? (isDark ? 'bg-emerald-900/30 border-emerald-700/50 text-emerald-300' : 'bg-emerald-50 border-emerald-200 text-emerald-700')
                : (isDark ? 'bg-amber-900/20  border-amber-700/40  text-amber-400'    : 'bg-amber-50  border-amber-200  text-amber-700'),
            )}>
              {ds.connected ? '● LIVE' : '○ FALLBACK'} · {providerShort}
            </span>
            {!ds.connected && (
              <span className={clsx('text-xs', isDark ? 'text-slate-500' : 'text-gray-400')}>
                Using yfinance v8 fallback
              </span>
            )}
          </div>
        )}

        {/* ── Quick actions ──────────────────────────────────────────────────── */}
        <div className="flex items-center gap-2 pt-2">
          <button
            onClick={handleQuickRefresh}
            disabled={quickRefreshing}
            className={clsx(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border transition-all',
              quickRefreshing
                ? (isDark ? 'border-slate-600 text-slate-500 bg-slate-800/30' : 'border-gray-200 text-gray-400')
                : (isDark ? 'border-indigo-600/60 text-indigo-300 bg-indigo-900/30 hover:bg-indigo-900/50' : 'border-indigo-300 text-indigo-600 bg-indigo-50 hover:bg-indigo-100'),
            )}
          >
            {quickRefreshing && <span className="w-2.5 h-2.5 border border-t-transparent border-indigo-400 rounded-full animate-spin" />}
            {quickRefreshing ? 'Refreshing…' : '⚡ Quick Refresh (3 stocks)'}
          </button>
        </div>

        {/* ── ICICI Credentials Form ────────────────────────────────────────── */}
        {showConfig && (
          <div className={clsx(
            'mt-3 rounded-xl border p-4 space-y-3',
            isDark ? 'border-amber-700/30 bg-amber-950/20' : 'border-amber-200 bg-amber-50',
          )}>
            <p className={clsx('text-xs font-bold uppercase tracking-wider', isDark ? 'text-amber-400' : 'text-amber-700')}>
              ICICI Breeze Credentials
            </p>
            <p className={clsx('text-xs', isDark ? 'text-slate-400' : 'text-gray-500')}>
              Session token rotates daily. Paste the full callback URL or just the token value.
            </p>
            <input
              className={inputBase}
              type="password"
              placeholder="API Key"
              value={apiKey}
              onChange={e => setApiKey(e.target.value)}
              autoComplete="off"
            />
            <input
              className={inputBase}
              type="password"
              placeholder="API Secret"
              value={apiSecret}
              onChange={e => setApiSecret(e.target.value)}
              autoComplete="off"
            />
            <input
              className={inputBase}
              type="text"
              placeholder="Session Token (or full callback URL)"
              value={sessionToken}
              onChange={e => setSessionToken(e.target.value)}
              autoComplete="off"
            />
            <div className="flex gap-2">
              <button
                onClick={handleSaveCredentials}
                disabled={saving}
                className={clsx(
                  'flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-bold border transition-all',
                  saving
                    ? (isDark ? 'border-slate-600 text-slate-500 bg-slate-800/30' : 'border-gray-200 text-gray-400')
                    : (isDark ? 'border-emerald-600/60 text-emerald-300 bg-emerald-900/30 hover:bg-emerald-900/50' : 'border-emerald-500 text-white bg-emerald-600 hover:bg-emerald-700'),
                )}
              >
                {saving && <span className="w-2.5 h-2.5 border border-t-transparent border-emerald-400 rounded-full animate-spin" />}
                {saving ? 'Applying…' : '✓ Apply & Reconnect'}
              </button>
              <button
                onClick={() => setShowConfig(false)}
                className={clsx('px-3 py-2 rounded-lg text-xs font-medium', isDark ? 'text-slate-500 hover:text-slate-300' : 'text-gray-400 hover:text-gray-600')}
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

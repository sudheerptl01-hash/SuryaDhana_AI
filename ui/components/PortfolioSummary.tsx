'use client'

import { useEffect, useState, useCallback } from 'react'
import clsx from 'clsx'
import { getPositionSummary, getOpenPositions, updateSessionToken } from '@/lib/api'

interface Summary {
  connected: boolean
  error?: string
  total_capital_inr: number
  cash_available_inr: number
  invested_value_inr: number
  num_open_positions: number
  total_pnl_inr: number
  total_pnl_pct: number
  as_of?: string
}

interface Position {
  symbol: string
  quantity: number
  buy_price: number
  current_price: number
  invested: number
  current_value: number
  pnl: number
  pnl_percent: number
}

export function PortfolioSummary() {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [positions, setPositions] = useState<Position[]>([])
  const [loading, setLoading] = useState(true)
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null)

  const [sessionToken, setSessionToken] = useState('')
  const [connecting, setConnecting] = useState(false)
  const [connectMsg, setConnectMsg] = useState<{ ok: boolean; text: string } | null>(null)

  const refresh = useCallback(async () => {
    try {
      const [sumRes, posRes] = await Promise.all([
        getPositionSummary(),
        getOpenPositions(),
      ])
      setSummary(sumRes.data)
      setPositions(posRes.data?.positions || [])
      setLastRefresh(new Date())
    } catch (err) {
      console.error('Portfolio fetch error:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    const interval = setInterval(refresh, 15000)
    return () => clearInterval(interval)
  }, [refresh])

  const handleConnect = async () => {
    if (!sessionToken.trim()) return
    setConnecting(true)
    setConnectMsg(null)
    try {
      const res = await updateSessionToken(sessionToken.trim())
      if (res.data?.connected) {
        setConnectMsg({ ok: true, text: 'Connected! Refreshing portfolio…' })
        setSessionToken('')
        await refresh()
      } else {
        setConnectMsg({ ok: false, text: res.data?.error || 'Connection failed. Check your token.' })
      }
    } catch (err: any) {
      setConnectMsg({ ok: false, text: err?.response?.data?.detail || 'Failed to update token.' })
    } finally {
      setConnecting(false)
    }
  }

  if (loading) {
    return (
      <div className="space-y-4">
        {Array(3).fill(0).map((_, i) => (
          <div key={i} className="h-28 animate-pulse rounded-2xl bg-gray-100" />
        ))}
      </div>
    )
  }

  if (!summary?.connected) {
    return (
      <div className="space-y-6">
        {/* Session Token Input */}
        <div className="rounded-2xl border border-indigo-200 bg-indigo-50 p-6">
          <h3 className="text-base font-bold text-indigo-800 mb-1">Connect ICICI Breeze</h3>
          <p className="text-sm text-indigo-600 mb-4">Paste your session token to connect your trading account.</p>
          <div className="flex gap-2">
            <input
              type="password"
              value={sessionToken}
              onChange={(e) => setSessionToken(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleConnect()}
              placeholder="Paste ICICI session token here…"
              className="flex-1 rounded-lg border border-indigo-200 bg-white px-4 py-2.5 text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            />
            <button
              onClick={handleConnect}
              disabled={connecting || !sessionToken.trim()}
              className={clsx(
                'px-5 py-2.5 rounded-lg text-sm font-semibold transition-all',
                connecting || !sessionToken.trim()
                  ? 'bg-indigo-200 text-indigo-400 cursor-not-allowed'
                  : 'bg-indigo-600 text-white hover:bg-indigo-700 shadow-sm'
              )}
            >
              {connecting ? 'Connecting…' : 'Connect'}
            </button>
          </div>
          {connectMsg && (
            <p className={clsx('text-sm mt-3 font-medium', connectMsg.ok ? 'text-emerald-600' : 'text-rose-600')}>
              {connectMsg.ok ? '✓ ' : '✕ '}{connectMsg.text}
            </p>
          )}
        </div>

        {/* Error / instructions */}
        <div className="rounded-2xl border border-amber-200 bg-amber-50 p-6">
          <div className="flex items-start gap-4">
            <div className="text-3xl">🔌</div>
            <div>
              <h3 className="text-base font-bold text-amber-800 mb-1">
                {summary?.error || 'Credentials not configured'}
              </h3>
              <p className="text-amber-700 text-sm mb-3">Generate a fresh session token to connect.</p>
              <div className="bg-white rounded-xl p-4 border border-amber-200 font-mono text-xs text-gray-600 space-y-1">
                <p className="text-gray-400 mb-1"># Run this to get your session token:</p>
                <p>/Users/sudheer/Desktop/jupyter_env/bin/python scripts/icici_session_helper.py</p>
              </div>
            </div>
          </div>
        </div>

        {/* Trading config */}
        <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
          <h3 className="text-base font-bold text-gray-900 mb-4">Trading Configuration</h3>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
            {[
              { label: 'Starting Capital', value: '₹10,000', sub: 'Phase 6 target' },
              { label: 'Max Positions', value: '5', sub: 'simultaneously' },
              { label: 'Stop Loss', value: '2%', sub: 'per position' },
              { label: 'Holding Period', value: '5 days', sub: 'time-stop' },
              { label: 'Max per Stock', value: '15%', sub: 'of portfolio' },
              { label: 'Max per Sector', value: '40%', sub: 'sector limit' },
            ].map(({ label, value, sub }) => (
              <div key={label} className="rounded-xl bg-gray-50 border border-gray-200 p-4">
                <p className="text-xs text-gray-400 font-medium">{label}</p>
                <p className="text-xl font-bold text-gray-900 mt-1">{value}</p>
                <p className="text-xs text-gray-400 mt-0.5">{sub}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    )
  }

  const isProfit = summary.total_pnl_inr >= 0
  const investedPct = summary.total_capital_inr > 0
    ? (summary.invested_value_inr / summary.total_capital_inr) * 100
    : 0

  return (
    <div className="space-y-6">
      {/* Live indicator + refresh */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          <span className="text-xs text-emerald-600 font-semibold">LIVE · ICICI Breeze</span>
        </div>
        <div className="text-xs text-gray-400">
          Last refresh: {lastRefresh?.toLocaleTimeString('en-IN') ?? '—'}
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <SummaryCard
          label="Total Portfolio"
          value={`₹${fmt(summary.total_capital_inr)}`}
          sub="net worth"
          color="indigo"
        />
        <SummaryCard
          label="Invested"
          value={`₹${fmt(summary.invested_value_inr)}`}
          sub={`${investedPct.toFixed(1)}% deployed`}
          color="violet"
        />
        <SummaryCard
          label="Cash Available"
          value={`₹${fmt(summary.cash_available_inr)}`}
          sub="ready to invest"
          color="cyan"
        />
        <SummaryCard
          label={isProfit ? 'Total P&L ▲' : 'Total P&L ▼'}
          value={`${isProfit ? '+' : ''}₹${fmt(Math.abs(summary.total_pnl_inr))}`}
          sub={`${isProfit ? '+' : ''}${summary.total_pnl_pct.toFixed(2)}% return`}
          color={isProfit ? 'emerald' : 'rose'}
        />
      </div>

      {/* Capital Allocation */}
      <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
        <h3 className="text-sm font-bold text-gray-700 mb-4">Capital Allocation</h3>
        <div className="space-y-3">
          <div>
            <div className="flex justify-between text-xs text-gray-500 mb-1.5">
              <span>Invested ({investedPct.toFixed(1)}%)</span>
              <span>₹{fmt(summary.invested_value_inr)}</span>
            </div>
            <div className="w-full h-3 rounded-full bg-gray-100 overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-indigo-500 to-violet-500 rounded-full"
                style={{ width: `${investedPct}%` }}
              />
            </div>
          </div>
          <div>
            <div className="flex justify-between text-xs text-gray-500 mb-1.5">
              <span>Cash Reserve ({(100 - investedPct).toFixed(1)}%)</span>
              <span>₹{fmt(summary.cash_available_inr)}</span>
            </div>
            <div className="w-full h-3 rounded-full bg-gray-100 overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-emerald-500 to-teal-500 rounded-full"
                style={{ width: `${100 - investedPct}%` }}
              />
            </div>
          </div>
        </div>
      </div>

      {/* Open Positions */}
      <div className="rounded-2xl border border-gray-200 bg-white overflow-hidden shadow-sm">
        <div className="p-5 border-b border-gray-100 flex items-center justify-between">
          <h3 className="text-base font-bold text-gray-900">
            Open Positions
            <span className="ml-2 text-gray-400 font-normal text-sm">({positions.length})</span>
          </h3>
        </div>

        {positions.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50">
                  <th className="px-4 py-3 text-left text-xs font-bold text-gray-500 uppercase">Symbol</th>
                  <th className="px-4 py-3 text-right text-xs font-bold text-gray-500 uppercase">Qty</th>
                  <th className="px-4 py-3 text-right text-xs font-bold text-gray-500 uppercase">Avg Cost</th>
                  <th className="px-4 py-3 text-right text-xs font-bold text-gray-500 uppercase">LTP</th>
                  <th className="px-4 py-3 text-right text-xs font-bold text-gray-500 uppercase">P&L</th>
                  <th className="px-4 py-3 text-right text-xs font-bold text-gray-500 uppercase">Return</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {positions.map((pos) => (
                  <tr key={pos.symbol} className="hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3 font-bold text-gray-900">{pos.symbol}</td>
                    <td className="px-4 py-3 text-right text-gray-600 tabular-nums">{pos.quantity}</td>
                    <td className="px-4 py-3 text-right text-gray-500 tabular-nums">₹{pos.buy_price.toFixed(2)}</td>
                    <td className="px-4 py-3 text-right font-semibold text-gray-800 tabular-nums">₹{pos.current_price.toFixed(2)}</td>
                    <td className={clsx('px-4 py-3 text-right font-bold tabular-nums', pos.pnl >= 0 ? 'text-emerald-600' : 'text-rose-600')}>
                      {pos.pnl >= 0 ? '+' : ''}₹{fmt(pos.pnl)}
                    </td>
                    <td className={clsx('px-4 py-3 text-right font-bold tabular-nums', pos.pnl_percent >= 0 ? 'text-emerald-600' : 'text-rose-600')}>
                      {pos.pnl_percent >= 0 ? '+' : ''}{pos.pnl_percent.toFixed(2)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="py-12 text-center text-gray-400 text-sm">
            <div className="text-3xl mb-3 opacity-30">📭</div>
            No active holdings in your Demat account.
          </div>
        )}
      </div>

      {/* Risk Rules */}
      <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
        <h3 className="text-sm font-bold text-gray-700 mb-4">Active Risk Rules</h3>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          {[
            { label: 'Max Positions', val: '5' },
            { label: 'Per Stock', val: '15%' },
            { label: 'Per Sector', val: '40%' },
            { label: 'Stop Loss', val: '-2%' },
            { label: 'Time Stop', val: '5 days' },
            { label: 'Daily Limit', val: '-2%' },
          ].map(({ label, val }) => (
            <div key={label} className="text-center rounded-lg bg-gray-50 border border-gray-200 px-3 py-2.5">
              <p className="text-xs text-gray-400">{label}</p>
              <p className="text-base font-bold text-gray-900 mt-0.5">{val}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function SummaryCard({ label, value, sub, color }: { label: string; value: string; sub: string; color: string }) {
  const colors: Record<string, string> = {
    indigo:  'border-indigo-200 bg-indigo-50',
    violet:  'border-violet-200 bg-violet-50',
    cyan:    'border-cyan-200 bg-cyan-50',
    emerald: 'border-emerald-200 bg-emerald-50',
    rose:    'border-rose-200 bg-rose-50',
  }
  const textColors: Record<string, string> = {
    indigo: 'text-indigo-900',
    violet: 'text-violet-900',
    cyan: 'text-cyan-900',
    emerald: 'text-emerald-900',
    rose: 'text-rose-900',
  }
  return (
    <div className={clsx('rounded-2xl border p-5', colors[color] ?? colors.indigo)}>
      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider">{label}</p>
      <p className={clsx('text-2xl font-black mt-2', textColors[color] ?? 'text-gray-900')}>{value}</p>
      <p className="text-xs text-gray-400 mt-1">{sub}</p>
    </div>
  )
}

function fmt(n: number): string {
  if (n >= 1_00_000) return `${(n / 1_00_000).toFixed(2)}L`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return n.toFixed(2)
}

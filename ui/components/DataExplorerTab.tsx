'use client'

import { apiError } from '@/lib/errors'
import React, { useCallback, useEffect, useState } from 'react'
import { DataHealthBar } from './DataHealthBar'
import { SkeletonGrid, FullTabLoader } from './LoadingOverlay'
import {
  fetchRefreshBatch,
  fetchHistorical,
  fetchFundamentals,
  getDataProviderStatus,
} from '@/lib/api'
import { useToast } from '@/context/ToastContext'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || ''

interface ExplorerPage {
  health: {
    total_rows: number
    total_tickers: number
    date_min: string | null
    date_max: string | null
    avg_null_pct: number
    feature_count: number
    null_counts: Record<string, number>
  }
  columns: string[]
  rows: Record<string, any>[]
  page: number
  page_size: number
  total_rows: number
  total_pages: number
}

const NULL_COLOR = 'text-slate-600 italic'
const TICKER_COLOR = 'text-amber-400 font-semibold'
const DATE_COLOR   = 'text-teal-400'

function cellClass(col: string, val: any) {
  if (val === null || val === undefined) return NULL_COLOR
  if (col === 'ticker') return TICKER_COLOR
  if (col === 'date')   return DATE_COLOR
  if (typeof val === 'number') {
    if (col.includes('rsi') && val > 70) return 'text-red-400'
    if (col.includes('rsi') && val < 30) return 'text-emerald-400'
    if (val > 0) return 'text-emerald-300'
    if (val < 0) return 'text-red-400'
  }
  return 'text-slate-300'
}

function fmtCell(val: any): string {
  if (val === null || val === undefined) return '—'
  if (typeof val === 'number') return val.toFixed(4)
  return String(val)
}

// ── Data Pipeline Controls ────────────────────────────────────────────────────

function DataPipelineControls() {
  const { addToast } = useToast()
  const [tickersInput, setTickersInput] = useState('RELIANCE,TCS,HDFCBANK,INFY,ICICIBANK')
  const [years, setYears]               = useState(1)
  const [busyRefresh, setBusyRefresh]   = useState(false)
  const [busyHist,    setBusyHist]      = useState(false)
  const [busyFund,    setBusyFund]      = useState(false)
  const [provider, setProvider]         = useState<string | null>(null)

  // Fetch provider status on mount
  useEffect(() => {
    getDataProviderStatus()
      .then(r => setProvider(r.data?.provider ?? 'unknown'))
      .catch(() => setProvider(null))
  }, [])

  const parseTickers = () =>
    tickersInput.split(/[\s,]+/).map(t => t.trim().toUpperCase()).filter(Boolean)

  const handleRefreshBatch = async () => {
    const tickers = parseTickers()
    if (!tickers.length) { addToast('Enter at least one ticker', 'warning'); return }
    setBusyRefresh(true)
    try {
      const res  = await fetchRefreshBatch({ tickers, years })
      const rows = Object.values(res.data?.refreshed ?? {}).reduce((s: number, v: any) => s + Number(v), 0)
      const errs = res.data?.errors?.length ?? 0
      addToast(
        `Incremental refresh: ${rows} rows updated across ${tickers.length} tickers${errs ? ` · ${errs} errors` : ''}`,
        errs > 0 ? 'warning' : 'success',
      )
    } catch (err: any) {
      addToast(`Refresh failed: ${apiError(err)}`, 'error')
    } finally {
      setBusyRefresh(false)
    }
  }

  const handleHistorical = async () => {
    const tickers = parseTickers()
    if (!tickers.length) { addToast('Enter at least one ticker', 'warning'); return }
    setBusyHist(true)
    try {
      const res  = await fetchHistorical({ tickers, years })
      const rows = Object.values(res.data?.fetched ?? {}).reduce((s: number, v: any) => s + Number(v), 0)
      addToast(`Historical fetch complete: ${rows} rows for ${tickers.length} tickers`, 'success')
    } catch (err: any) {
      addToast(`Historical fetch failed: ${apiError(err)}`, 'error')
    } finally {
      setBusyHist(false)
    }
  }

  const handleFundamentals = async () => {
    const tickers = parseTickers()
    if (!tickers.length) { addToast('Enter at least one ticker', 'warning'); return }
    setBusyFund(true)
    try {
      const res = await fetchFundamentals({ tickers })
      addToast(
        `Fundamentals: ${res.data?.fetched ?? 0} enriched · ${res.data?.skipped ?? 0} skipped`,
        'success',
      )
    } catch (err: any) {
      addToast(`Fundamentals failed: ${apiError(err)}`, 'error')
    } finally {
      setBusyFund(false)
    }
  }

  const isBusy = busyRefresh || busyHist || busyFund

  return (
    <div className="rounded border border-slate-700 bg-slate-900 px-4 py-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[10px] font-semibold tracking-widest text-amber-400 mb-0.5">
            DATA PIPELINE CONTROLS
          </div>
          <div className="text-[10px] text-slate-500 font-mono">
            Direct data-service proxy · /api/data/fetch/*
          </div>
        </div>
        {provider && (
          <span className="text-[10px] font-mono px-2 py-0.5 rounded border border-slate-600 text-slate-400">
            LIVE FEED · {provider.replace('Provider','').replace('DirectYahoo','Yahoo v8').replace('ICICIBreeze','ICICI Breeze')}
          </span>
        )}
      </div>

      {/* Ticker + year inputs */}
      <div className="flex flex-wrap gap-2">
        <input
          className="flex-1 min-w-48 rounded border border-slate-700 bg-slate-800 px-3 py-1.5 font-mono text-xs text-slate-200 placeholder-slate-600 focus:border-amber-500/60 focus:outline-none"
          placeholder="Tickers (comma-separated): RELIANCE,TCS,INFY…"
          value={tickersInput}
          onChange={e => setTickersInput(e.target.value)}
          disabled={isBusy}
        />
        <select
          className="rounded border border-slate-700 bg-slate-800 px-2 py-1.5 font-mono text-xs text-slate-300 focus:border-amber-500/60 focus:outline-none"
          value={years}
          onChange={e => setYears(Number(e.target.value))}
          disabled={isBusy}
        >
          {[1, 2, 3, 5].map(y => <option key={y} value={y}>{y}Y</option>)}
        </select>
      </div>

      {/* Action buttons */}
      <div className="flex flex-wrap gap-2">
        <ActionButton
          label="↻ Incremental Refresh"
          desc="Only fetch missing bars (fast)"
          busy={busyRefresh}
          disabled={isBusy}
          color="indigo"
          onClick={handleRefreshBatch}
        />
        <ActionButton
          label="⇣ Full Historical"
          desc={`${years}Y backfill (slow)`}
          busy={busyHist}
          disabled={isBusy}
          color="violet"
          onClick={handleHistorical}
        />
        <ActionButton
          label="ƒ Fetch Fundamentals"
          desc="PE · MCap · ROCE (0.6s/ticker)"
          busy={busyFund}
          disabled={isBusy}
          color="amber"
          onClick={handleFundamentals}
        />
      </div>

      {isBusy && (
        <p className="text-[10px] font-mono text-slate-500 animate-pulse">
          Processing… UI remains responsive. Check logs for per-ticker status.
        </p>
      )}
    </div>
  )
}

function ActionButton({
  label, desc, busy, disabled, color, onClick
}: {
  label: string; desc: string; busy: boolean; disabled: boolean
  color: 'indigo' | 'violet' | 'amber'; onClick: () => void
}) {
  const colors = {
    indigo: 'border-cyan-700/50 text-cyan-400 hover:border-cyan-500 hover:text-cyan-300 disabled:text-slate-600 disabled:border-slate-700',
    violet: 'border-violet-700/50 text-violet-400 hover:border-violet-500 hover:text-violet-300 disabled:text-slate-600 disabled:border-slate-700',
    amber:  'border-amber-700/50  text-amber-400  hover:border-amber-500  hover:text-amber-300  disabled:text-slate-600 disabled:border-slate-700',
  }
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`flex items-center gap-1.5 px-3 py-1.5 rounded border text-[11px] font-mono font-semibold transition-all ${colors[color]}`}
    >
      {busy && <span className={`w-2.5 h-2.5 border border-t-transparent rounded-full animate-spin border-current`} />}
      <span>
        {busy ? 'Running…' : label}
        <span className="ml-1 text-[9px] opacity-50">{desc}</span>
      </span>
    </button>
  )
}

// ── Main DataExplorerTab ───────────────────────────────────────────────────────

export function DataExplorerTab() {
  const [data, setData]       = useState<ExplorerPage | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState<string | null>(null)
  const [page, setPage]       = useState(1)
  const [pageSize]            = useState(50)
  const [ticker, setTicker]   = useState('')
  const [sortBy, setSortBy]   = useState('date')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [tickerInput, setTickerInput] = useState('')

  const fetch = useCallback(async (p = page) => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({
        page: String(p),
        page_size: String(pageSize),
        sort_by: sortBy,
        sort_dir: sortDir,
      })
      if (ticker) params.set('ticker', ticker)
      const res = await window.fetch(`${API_BASE}/api/pipeline/features-explorer?${params}`)
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }))
        setError(body.detail || 'Failed to load features')
        setData(null)
      } else {
        setData(await res.json())
      }
    } catch (e: any) {
      setError(e.message || 'Network error')
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, ticker, sortBy, sortDir])

  useEffect(() => { fetch(page) }, [page, sortBy, sortDir, ticker])

  const handleSort = (col: string) => {
    if (col === sortBy) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortBy(col)
      setSortDir('desc')
    }
    setPage(1)
  }

  const handleSearch = () => {
    setTicker(tickerInput.trim().toUpperCase())
    setPage(1)
  }

  const SortIcon = ({ col }: { col: string }) => {
    if (col !== sortBy) return <span className="text-slate-700"> ⇅</span>
    return <span className="text-amber-400">{sortDir === 'asc' ? ' ↑' : ' ↓'}</span>
  }

  if (loading && !data) return <FullTabLoader message="Loading feature explorer…" />

  return (
    <div className="flex flex-col gap-4">
      {/* Pipeline Controls */}
      <DataPipelineControls />

      {/* Health Bar */}
      <div className="rounded border border-slate-700 bg-slate-900 px-4 py-3">
        <div className="mb-2 text-[10px] font-semibold tracking-widest text-slate-500">DATASET HEALTH</div>
        <DataHealthBar health={data?.health ?? null} loading={loading && !data} />
      </div>

      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex gap-1">
          <input
            className="w-32 rounded border border-slate-700 bg-slate-800 px-2 py-1 font-mono text-xs text-slate-200 placeholder-slate-600 focus:border-amber-500 focus:outline-none"
            placeholder="Ticker…"
            value={tickerInput}
            onChange={e => setTickerInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSearch()}
          />
          <button
            onClick={handleSearch}
            className="rounded border border-slate-600 bg-slate-800 px-2 py-1 font-mono text-[10px] text-amber-400 hover:border-amber-500 transition-colors"
          >
            FILTER
          </button>
          {ticker && (
            <button
              onClick={() => { setTicker(''); setTickerInput(''); setPage(1) }}
              className="rounded border border-slate-700 bg-slate-800 px-2 py-1 font-mono text-[10px] text-slate-400 hover:text-red-400 transition-colors"
            >
              ✕
            </button>
          )}
        </div>
        <span className="font-mono text-[10px] text-slate-500">
          {data ? `${data.total_rows.toLocaleString('en-IN')} rows · page ${data.page}/${data.total_pages}` : ''}
        </span>
        <button
          onClick={() => fetch(page)}
          className="ml-auto rounded border border-slate-700 px-2 py-1 font-mono text-[10px] text-slate-400 hover:text-amber-400 transition-colors"
        >
          ↺ REFRESH
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="rounded border border-red-800 bg-red-900/20 px-4 py-3 font-mono text-xs text-red-400">
          {error}
        </div>
      )}

      {/* Table */}
      {loading && data ? (
        <SkeletonGrid rows={10} cols={data.columns.length} />
      ) : data && data.rows.length > 0 ? (
        <div className="overflow-x-auto rounded border border-slate-700">
          <table className="w-full text-[11px] font-mono">
            <thead>
              <tr className="border-b border-slate-700 bg-slate-800/80">
                {data.columns.map(col => (
                  <th
                    key={col}
                    onClick={() => handleSort(col)}
                    className="cursor-pointer whitespace-nowrap px-3 py-2 text-left text-[9px] tracking-widest text-slate-400 hover:text-amber-400 transition-colors select-none"
                  >
                    {col.toUpperCase().replace(/_/g, '_')}
                    <SortIcon col={col} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row, ri) => (
                <tr
                  key={ri}
                  className="border-b border-slate-800/60 hover:bg-slate-800/40 transition-colors"
                >
                  {data.columns.map(col => (
                    <td key={col} className={`whitespace-nowrap px-3 py-1.5 ${cellClass(col, row[col])}`}>
                      {fmtCell(row[col])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : data ? (
        <div className="rounded border border-slate-700 py-16 text-center font-mono text-xs text-slate-500">
          No rows found{ticker ? ` for ticker "${ticker}"` : ''}
        </div>
      ) : null}

      {/* Pagination */}
      {data && data.total_pages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <button
            disabled={page <= 1}
            onClick={() => setPage(p => Math.max(1, p - 1))}
            className="rounded border border-slate-700 px-3 py-1 font-mono text-[10px] text-slate-400 hover:text-amber-400 disabled:opacity-30 transition-colors"
          >
            ← PREV
          </button>
          <span className="font-mono text-[10px] text-slate-500">
            {page} / {data.total_pages}
          </span>
          <button
            disabled={page >= data.total_pages}
            onClick={() => setPage(p => Math.min(data.total_pages, p + 1))}
            className="rounded border border-slate-700 px-3 py-1 font-mono text-[10px] text-slate-400 hover:text-amber-400 disabled:opacity-30 transition-colors"
          >
            NEXT →
          </button>
        </div>
      )}
    </div>
  )
}

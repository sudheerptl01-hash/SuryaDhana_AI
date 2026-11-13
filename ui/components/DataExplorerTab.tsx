'use client'

import { apiError } from '@/lib/errors'
import React, { useCallback, useEffect, useState } from 'react'
import { DataHealthBar } from './DataHealthBar'
import { SkeletonGrid, FullTabLoader } from './LoadingOverlay'
import { BadgeChip, SourceChip, sourceOf } from '@/components/terminal'
import { duplicateColumns, FUNDAMENTAL_FEATURES } from './dexpRules'
import { useCatalogTone } from '@/lib/dataHealthStore'

/*
 * DEXP (5 Nov 2026 review, M29 / m115): the three data buttons (incremental refresh, full historical, fundamentals)
 * called Yahoo Finance from the request path with no warning, against the CLAUDE.md Yahoo budget (a 26 Oct 429 took the
 * 08:45 gold snapshot down). They are removed: prices come from the scheduled evening pipeline, and the one guarded
 * manual path is the header's UPDATE DATA (it asks again inside the EOD window). The "LIVE FEED · ICICI Breeze" chip on
 * this EOD grid is gone; every block carries a badge; numbers are no longer coloured as if they were signals.
 */

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

// Feature values are descriptions (context), so they are never coloured as buy / sell cues (no red / green by sign or
// RSI band): only nulls, tickers and dates are styled.
function cellClass(col: string, val: any) {
  if (val === null || val === undefined) return NULL_COLOR
  if (col === 'ticker') return TICKER_COLOR
  if (col === 'date')   return DATE_COLOR
  return 'text-slate-300'
}

function fmtCell(val: any): string {
  if (val === null || val === undefined) return '—'
  if (typeof val === 'number') return val.toFixed(4)
  return String(val)
}

// ── Data source note (replaces the Yahoo fetch buttons) ────────────────────────

function DataSourceNote({ asOf }: { asOf: string | null }) {
  const catTone = useCatalogTone()                       // F-27: the ml_features catalog verdict tones the chip
  return (
    <div className="rounded border border-slate-700 bg-slate-900 px-4 py-3 space-y-1.5">
      <div className="flex items-center gap-2">
        <div className="text-[10px] font-semibold tracking-widest text-amber-400">DATA SOURCE</div>
        <span className="flex-1" />
        <SourceChip info={catTone(sourceOf(asOf, { source: 'ml_features · EOD', maxAgeDays: 4 }), 'ml_features')} />
      </div>
      <p className="text-[11px] text-slate-400 leading-relaxed">
        This grid reads the stored <span className="font-mono text-slate-300">ml_features</span> table (data-service): end of day, rebuilt by
        the scheduled evening pipeline. Nothing on this page fetches data. The manual fetch buttons that called Yahoo Finance were
        removed (they ran beside the 03:10 gold pull and the 08:45 pre-open snapshot); for a one-off refresh use the header&apos;s
        UPDATE DATA, which asks again inside the 18:30–21:15 window.
      </p>
    </div>
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

  const dupOf = data ? duplicateColumns(data.columns, data.rows) : {}

  if (loading && !data) return <FullTabLoader message="Loading feature explorer…" />

  return (
    <div className="flex flex-col gap-4">
      {/* Data source (no fetch from this page: M29) */}
      <DataSourceNote asOf={data?.health?.date_max ?? null} />

      {/* Health Bar */}
      <div className="rounded border border-slate-700 bg-slate-900 px-4 py-3">
        <div className="mb-2 flex items-center gap-2 text-[10px] font-semibold tracking-widest text-slate-500">DATASET HEALTH
          <BadgeChip badge="arithmetic" note="Row, ticker and null counts of the stored table." /></div>
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
        <BadgeChip badge="context" note="Trailing technical / market features: descriptions. The technical-rule family FAILS after costs (RSCH handbook swing) and the 5-day ML labels FAIL (RSCH ML labels)." />
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
        <>
        {(() => {
          const dups = duplicateColumns(data.columns, data.rows)
          const fundNull = data.columns.filter(c => FUNDAMENTAL_FEATURES.includes(c) && data.rows.every(r => r[c] == null))
          if (!Object.keys(dups).length && !fundNull.length) return null
          return (
            <div className="rounded border border-slate-700/60 bg-slate-900/60 px-3 py-2 text-[11px] text-slate-400 leading-relaxed" data-dexp-notes>
              {Object.keys(dups).length > 0 && <div>Same values on every row of this page: {Object.entries(dups).map(([c, of]) => `${c.toUpperCase()} = ${of.toUpperCase()}`).join(' · ')}.
                A <span className="font-mono">return_lag_k</span> column is the k-session trailing return (not a lagged 1-day return), so the 1- and 5-session ones
                repeat RET_1D and RET_5D by definition; the model&apos;s default inputs leave the duplicates out.</div>}
              {fundNull.length > 0 && <div>{fundNull.length} fundamental columns are empty on every row: only one undated fundamentals snapshot exists, so a
                point-in-time join leaves them NULL on dated rows (they are not in the model&apos;s default inputs).</div>}
            </div>
          )
        })()}
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
                    {dupOf[col] && <span className="ml-1 text-[9px] text-slate-500" title={`identical to ${dupOf[col].toUpperCase()} on this page`}>= {dupOf[col].toUpperCase()}</span>}
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
        </>
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

'use client'

import { TickerLink, fmtNum } from '@/components/terminal'
import { fmtSigned } from '@/lib/format'   // signed numbers with U+2212 (C1-trader-ux-18)

import { useMemo, useState } from 'react'
import clsx from 'clsx'
import type { Trade } from '@/lib/backtest'

type SortCol = keyof Pick<Trade,
  'entry_date' | 'exit_date' | 'ticker' | 'return_pct' | 'gross_return_pct' |
  'holding_days' | 'pnl' | 'capital_allocated' | 'exit_reason'>

const REASON_LABEL: Record<string, string> = {
  stop_loss: 'STOP', trailing_stop: 'TRAIL', time_stop: 'TIME',
}
const REASON_COLOR: Record<string, string> = {
  stop_loss: 'text-rose-400', trailing_stop: 'text-amber-400', time_stop: 'text-slate-400',
}

const PAGE = 25

const num = (n: number, d = 2) => fmtNum(n, d)

interface Props {
  trades: Trade[]
  onTradeClick?: (t: Trade) => void
}

export function BacktestTradeGrid({ trades, onTradeClick }: Props) {
  const [sortCol, setSortCol] = useState<SortCol>('exit_date')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [groupBy, setGroupBy] = useState<'none' | 'ticker' | 'sector' | 'exit_reason'>('none')
  const [tickerFilter, setTickerFilter] = useState('')
  const [reasonFilter, setReasonFilter] = useState<'all' | string>('all')
  const [winFilter, setWinFilter] = useState<'all' | 'win' | 'loss'>('all')
  const [page, setPage] = useState(0)

  const toggleSort = (c: SortCol) => {
    if (c === sortCol) setSortDir(d => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortCol(c); setSortDir('desc') }
    setPage(0)
  }

  const filtered = useMemo(() => {
    let r = trades
    if (tickerFilter) r = r.filter(t => t.ticker.toLowerCase().includes(tickerFilter.toLowerCase()))
    if (reasonFilter !== 'all') r = r.filter(t => t.exit_reason === reasonFilter)
    if (winFilter !== 'all') r = r.filter(t => (winFilter === 'win' ? t.is_win : !t.is_win))
    const sorted = [...r].sort((a, b) => {
      const av: any = a[sortCol]; const bv: any = b[sortCol]
      const cmp = typeof av === 'string' ? av.localeCompare(bv) : (av - bv)
      return sortDir === 'asc' ? cmp : -cmp
    })
    return sorted
  }, [trades, tickerFilter, reasonFilter, winFilter, sortCol, sortDir])

  // Flatten with group headers when grouping is on
  const items = useMemo(() => {
    if (groupBy === 'none') return filtered.map(t => ({ type: 'trade' as const, t }))
    const groups = new Map<string, Trade[]>()
    for (const t of filtered) {
      const key = String((groupBy === 'sector' ? (t.sector || 'Unknown') : t[groupBy]) ?? 'Unknown')
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key)!.push(t)
    }
    const out: Array<{ type: 'group'; key: string; rows: Trade[] } | { type: 'trade'; t: Trade }> = []
    for (const [key, rows] of [...groups.entries()].sort((a, b) => b[1].length - a[1].length)) {
      out.push({ type: 'group', key, rows })
      rows.forEach(t => out.push({ type: 'trade', t }))
    }
    return out
  }, [filtered, groupBy])

  const pageCount = Math.max(1, Math.ceil(items.length / PAGE))
  const safePage = Math.min(page, pageCount - 1)
  const pageItems = items.slice(safePage * PAGE, (safePage + 1) * PAGE)

  const Th = ({ col, label, right }: { col: SortCol; label: string; right?: boolean }) => (
    <th
      onClick={() => toggleSort(col)}
      className={clsx('px-2 py-1.5 font-bold uppercase tracking-wider cursor-pointer whitespace-nowrap select-none hover:bg-slate-700/40',
        right ? 'text-right' : 'text-left')}
    >
      {label}<span className="ml-1 text-amber-500">{sortCol === col ? (sortDir === 'asc' ? '▲' : '▼') : ''}</span>
    </th>
  )

  return (
    <div className="font-mono text-[11px] text-slate-200">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2 px-3 py-2 border-b border-slate-700/50 bg-slate-900/40">
        <input
          value={tickerFilter}
          onChange={e => { setTickerFilter(e.target.value); setPage(0) }}
          placeholder="filter ticker…"
          className="px-2 py-1 rounded bg-slate-800 border border-slate-700 text-slate-200 w-32 focus:border-amber-500 outline-none"
        />
        <select value={reasonFilter} onChange={e => { setReasonFilter(e.target.value); setPage(0) }}
          className="px-2 py-1 rounded bg-slate-800 border border-slate-700 text-slate-200">
          <option value="all">all exits</option>
          <option value="stop_loss">stop-loss</option>
          <option value="trailing_stop">trailing</option>
          <option value="time_stop">time-stop</option>
        </select>
        <select value={winFilter} onChange={e => { setWinFilter(e.target.value as any); setPage(0) }}
          className="px-2 py-1 rounded bg-slate-800 border border-slate-700 text-slate-200">
          <option value="all">win+loss</option>
          <option value="win">wins</option>
          <option value="loss">losses</option>
        </select>
        <div className="flex items-center gap-1 ml-auto">
          <span className="text-slate-500">group:</span>
          {(['none', 'ticker', 'sector', 'exit_reason'] as const).map(g => (
            <button key={g} onClick={() => { setGroupBy(g); setPage(0) }}
              className={clsx('px-2 py-1 rounded', groupBy === g ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40' : 'bg-slate-800 text-slate-400 border border-slate-700')}>
              {g === 'none' ? 'off' : g === 'exit_reason' ? 'reason' : g}
            </button>
          ))}
        </div>
        <span className="text-slate-500">{filtered.length} rows</span>
      </div>

      {/* Table */}
      <div className="overflow-x-auto max-h-[460px] overflow-y-auto">
        <table className="w-full border-collapse">
          <thead className="sticky top-0 z-10 bg-slate-900 text-slate-400 border-b border-slate-700">
            <tr>
              <Th col="entry_date" label="Entry" />
              <Th col="exit_date" label="Exit" />
              <Th col="ticker" label="Ticker" />
              <Th col="capital_allocated" label="Capital ₹" right />
              <Th col="gross_return_pct" label="Gross %" right />
              <Th col="return_pct" label="Net %" right />
              <Th col="pnl" label="PnL ₹" right />
              <Th col="holding_days" label="Hold" right />
              <Th col="exit_reason" label="Exit" />
            </tr>
          </thead>
          <tbody>
            {pageItems.map((it, i) => {
              if (it.type === 'group') {
                const rows = it.rows
                const wins = rows.filter(r => r.is_win).length
                const avg = rows.reduce((s, r) => s + r.return_pct, 0) / rows.length
                const pnl = rows.reduce((s, r) => s + r.pnl, 0)
                return (
                  <tr key={`g-${it.key}-${i}`} className="bg-slate-800/70 border-y border-slate-700">
                    <td colSpan={9} className="px-2 py-1.5 font-bold text-amber-300">
                      ▸ {it.key}
                      <span className="ml-3 text-slate-400 font-normal">
                        {rows.length} trades · {((wins / rows.length) * 100).toFixed(0)}% win ·
                        avg <span className={avg >= 0 ? 'text-emerald-400' : 'text-rose-400'}>{fmtSigned(avg, 2)}%</span> ·
                        PnL <span className={pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}>₹{num(pnl, 0)}</span>
                      </span>
                    </td>
                  </tr>
                )
              }
              const t = it.t
              return (
                <tr key={`${t.ticker}-${t.entry_date}-${i}`}
                  onClick={() => onTradeClick?.(t)}
                  className="border-b border-slate-800/60 hover:bg-amber-500/10 cursor-pointer">
                  <td className="px-2 py-1 text-slate-400">{t.entry_date}</td>
                  <td className="px-2 py-1 text-slate-400">{t.exit_date}</td>
                  <td className="px-2 py-1"><TickerLink symbol={t.ticker} />{t.sector && t.sector !== 'Unknown' && <span className="ml-1.5 text-[9px] text-slate-500 uppercase tracking-wide">{t.sector}</span>}</td>
                  <td className="px-2 py-1 text-right tabular-nums text-slate-300">{num(t.capital_allocated, 0)}</td>
                  <td className={clsx('px-2 py-1 text-right tabular-nums', t.gross_return_pct >= 0 ? 'text-emerald-400/80' : 'text-rose-400/80')}>{fmtSigned(t.gross_return_pct, 2)}</td>
                  <td className={clsx('px-2 py-1 text-right tabular-nums font-bold', t.return_pct >= 0 ? 'text-emerald-400' : 'text-rose-400')}>{fmtSigned(t.return_pct, 2)}</td>
                  <td className={clsx('px-2 py-1 text-right tabular-nums', t.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400')}>{fmtSigned(t.pnl, 0)}</td>
                  <td className="px-2 py-1 text-right tabular-nums text-slate-400">{t.holding_days}</td>
                  <td className={clsx('px-2 py-1 font-bold', REASON_COLOR[t.exit_reason])}>{REASON_LABEL[t.exit_reason]}</td>
                </tr>
              )
            })}
            {pageItems.length === 0 && (
              <tr><td colSpan={9} className="px-2 py-10 text-center text-slate-500">No trades match the filters</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between px-3 py-2 border-t border-slate-700/50 text-slate-400">
        <span>page {safePage + 1} / {pageCount}</span>
        <div className="flex gap-1">
          <button disabled={safePage === 0} onClick={() => setPage(p => Math.max(0, p - 1))}
            className="px-2 py-1 rounded bg-slate-800 border border-slate-700 disabled:opacity-40">‹ prev</button>
          <button disabled={safePage >= pageCount - 1} onClick={() => setPage(p => Math.min(pageCount - 1, p + 1))}
            className="px-2 py-1 rounded bg-slate-800 border border-slate-700 disabled:opacity-40">next ›</button>
        </div>
      </div>
    </div>
  )
}

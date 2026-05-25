'use client'

import clsx from 'clsx'
import { useState } from 'react'

interface Stock {
  ticker: string
  latest_price: number
  price_date: string
  total_rows: number
  first_date: string
  latest_date: string
  years_of_data: number
  data_density_pct: number
  days_since_update: number
  data_quality: string
  ma50?: number
  ma150?: number
  ma200?: number
  rs_rating?: number
  sepa_stage?: string
  filters?: Record<string, boolean>
}

interface StockTableProps {
  stocks: Stock[]
  onRowClick: (ticker: string) => void
  loading?: boolean
}

const SEPA_COLORS: Record<string, string> = {
  'Stage 3': 'bg-emerald-100 text-emerald-700 border-emerald-200',
  'Stage 2': 'bg-indigo-100 text-indigo-700 border-indigo-200',
  'Stage 4': 'bg-rose-100 text-rose-700 border-rose-200',
  'Stage 1': 'bg-gray-100 text-gray-600 border-gray-200',
}

const QUALITY_DOTS: Record<string, string> = {
  excellent: 'bg-emerald-500',
  good: 'bg-teal-500',
  fair: 'bg-amber-400',
  poor: 'bg-rose-400',
}

export function StockTable({ stocks, onRowClick, loading }: StockTableProps) {
  const [hovered, setHovered] = useState<string | null>(null)

  if (loading) {
    return (
      <div className="space-y-2 p-4">
        {Array(8).fill(0).map((_, i) => (
          <div key={i} className="h-11 animate-pulse rounded-lg bg-gray-100" />
        ))}
      </div>
    )
  }

  if (stocks.length === 0) {
    return (
      <div className="py-16 text-center">
        <div className="text-4xl mb-3 opacity-30">📭</div>
        <p className="text-gray-500 font-medium">No stocks match the selected filters</p>
        <p className="text-gray-400 text-sm mt-1">Try removing some filters</p>
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-200 bg-gray-50">
            <th className="px-4 py-3 text-left text-xs font-bold uppercase tracking-wider text-gray-500">Ticker</th>
            <th className="px-4 py-3 text-right text-xs font-bold uppercase tracking-wider text-gray-500">Price ₹</th>
            <th className="px-4 py-3 text-right text-xs font-bold uppercase tracking-wider text-gray-500">MA 50/150/200</th>
            <th className="px-4 py-3 text-center text-xs font-bold uppercase tracking-wider text-gray-500">SEPA Stage</th>
            <th className="px-4 py-3 text-center text-xs font-bold uppercase tracking-wider text-gray-500">RS</th>
            <th className="px-4 py-3 text-left text-xs font-bold uppercase tracking-wider text-gray-500">Density</th>
            <th className="px-4 py-3 text-center text-xs font-bold uppercase tracking-wider text-gray-500">Health</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {stocks.map((stock) => {
            const sepaKey = stock.sepa_stage?.split(':')[0]?.trim() ?? ''
            const sepaColor = SEPA_COLORS[sepaKey] ?? 'bg-gray-100 text-gray-500 border-gray-200'
            const qualityDot = QUALITY_DOTS[stock.data_quality] ?? 'bg-gray-300'
            const priceVsMa50 = stock.ma50 && stock.latest_price > stock.ma50

            return (
              <tr
                key={stock.ticker}
                onClick={() => onRowClick(stock.ticker)}
                onMouseEnter={() => setHovered(stock.ticker)}
                onMouseLeave={() => setHovered(null)}
                className={clsx(
                  'cursor-pointer transition-colors',
                  hovered === stock.ticker ? 'bg-indigo-50' : 'hover:bg-gray-50'
                )}
              >
                {/* Ticker */}
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <div className={clsx('w-2 h-2 rounded-full flex-shrink-0', qualityDot)} />
                    <span className="font-black text-gray-900">{stock.ticker}</span>
                  </div>
                </td>

                {/* Price */}
                <td className="px-4 py-3 text-right">
                  <span className={clsx('font-semibold', priceVsMa50 ? 'text-emerald-600' : 'text-gray-700')}>
                    ₹{stock.latest_price?.toFixed(2)}
                  </span>
                </td>

                {/* MA */}
                <td className="px-4 py-3 text-right font-mono text-xs text-gray-400">
                  {stock.ma50
                    ? `${stock.ma50.toFixed(0)} / ${stock.ma150?.toFixed(0) ?? '—'} / ${stock.ma200?.toFixed(0) ?? '—'}`
                    : '—'}
                </td>

                {/* SEPA Stage */}
                <td className="px-4 py-3 text-center">
                  <span className={clsx('inline-block rounded-lg border px-2.5 py-0.5 text-xs font-bold', sepaColor)}>
                    {sepaKey || 'N/A'}
                  </span>
                </td>

                {/* RS Rating */}
                <td className="px-4 py-3 text-center">
                  <span className={clsx(
                    'inline-block rounded px-2 py-0.5 text-xs font-bold',
                    (stock.rs_rating ?? 0) >= 70
                      ? 'bg-emerald-100 text-emerald-700'
                      : 'text-gray-400'
                  )}>
                    {stock.rs_rating ?? '—'}
                  </span>
                </td>

                {/* Density bar */}
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2 min-w-[80px]">
                    <div className="h-1.5 w-16 rounded-full bg-gray-200 overflow-hidden">
                      <div
                        className={clsx(
                          'h-full rounded-full',
                          stock.data_density_pct >= 95 ? 'bg-emerald-500' :
                          stock.data_density_pct >= 85 ? 'bg-teal-500' :
                          stock.data_density_pct >= 70 ? 'bg-amber-400' : 'bg-rose-400'
                        )}
                        style={{ width: `${Math.min(100, stock.data_density_pct)}%` }}
                      />
                    </div>
                    <span className="text-xs text-gray-400 tabular-nums">
                      {stock.data_density_pct?.toFixed(0)}%
                    </span>
                  </div>
                </td>

                {/* Quality dot only — no text label */}
                <td className="px-4 py-3 text-center">
                  <div className="flex items-center justify-center">
                    <div className={clsx('w-3 h-3 rounded-full', qualityDot)} title={stock.data_quality} />
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

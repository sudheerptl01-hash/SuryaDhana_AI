'use client'

import React from 'react'

interface HealthStats {
  total_rows: number
  total_tickers: number
  date_min: string | null
  date_max: string | null
  avg_null_pct: number
  feature_count: number
}

interface DataHealthBarProps {
  health: HealthStats | null
  loading?: boolean
}

export function DataHealthBar({ health, loading }: DataHealthBarProps) {
  if (loading) {
    return (
      <div className="flex gap-4 animate-pulse">
        {[80, 64, 96, 72, 56].map((w, i) => (
          <div key={i} className="h-5 rounded bg-slate-700" style={{ width: w }} />
        ))}
      </div>
    )
  }
  if (!health) return null

  const nullOk = health.avg_null_pct < 5
  const nullWarn = health.avg_null_pct >= 5 && health.avg_null_pct < 15
  const nullColor = nullOk ? 'text-emerald-400' : nullWarn ? 'text-amber-400' : 'text-red-400'

  const chips: { label: string; value: string; color: string }[] = [
    { label: 'ROWS', value: health.total_rows.toLocaleString('en-IN'), color: 'text-amber-400' },
    { label: 'TICKERS', value: String(health.total_tickers), color: 'text-violet-400' },
    { label: 'FEATURES', value: String(health.feature_count), color: 'text-teal-400' },
    {
      label: 'WINDOW',
      value: health.date_min && health.date_max
        ? `${health.date_min} → ${health.date_max}`
        : 'N/A',
      color: 'text-slate-300',
    },
    { label: 'NULL%', value: `${health.avg_null_pct.toFixed(1)}%`, color: nullColor },
  ]

  return (
    <div className="flex flex-wrap gap-x-5 gap-y-1 text-[10px] font-mono">
      {chips.map(c => (
        <span key={c.label} className="flex items-center gap-1">
          <span className="text-slate-500">{c.label}</span>
          <span className={c.color}>{c.value}</span>
        </span>
      ))}
    </div>
  )
}

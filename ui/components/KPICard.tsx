'use client'

import clsx from 'clsx'

interface KPICardProps {
  label: string
  value: string | number
  subtext?: string
  trend?: 'up' | 'down' | 'stable'
  color?: 'indigo' | 'emerald' | 'rose' | 'amber' | 'violet' | 'cyan' | 'slate'
  icon?: React.ReactNode
}

const COLORS = {
  indigo:  'border-indigo-200 bg-indigo-50 text-indigo-600 [&_.val]:text-indigo-900',
  emerald: 'border-emerald-200 bg-emerald-50 text-emerald-600 [&_.val]:text-emerald-900',
  rose:    'border-rose-200 bg-rose-50 text-rose-600 [&_.val]:text-rose-900',
  amber:   'border-amber-200 bg-amber-50 text-amber-600 [&_.val]:text-amber-900',
  violet:  'border-violet-200 bg-violet-50 text-violet-600 [&_.val]:text-violet-900',
  cyan:    'border-cyan-200 bg-cyan-50 text-cyan-600 [&_.val]:text-cyan-900',
  slate:   'border-gray-200 bg-white text-gray-500 [&_.val]:text-gray-900',
}

export function KPICard({ label, value, subtext, trend, color = 'indigo', icon }: KPICardProps) {
  return (
    <div className={clsx('rounded-2xl border p-5 transition-all hover:shadow-md hover:scale-[1.01]', COLORS[color])}>
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <p className="text-xs font-semibold uppercase tracking-wider opacity-70">{label}</p>
          <p className="val mt-2 text-3xl font-black truncate">{value}</p>
          {subtext && <p className="mt-1 text-xs opacity-60">{subtext}</p>}
          {trend && (
            <p className="mt-2 text-xs font-semibold">
              {trend === 'up' ? '↑ Up' : trend === 'down' ? '↓ Down' : '→ Stable'}
            </p>
          )}
        </div>
        {icon && <div className="text-2xl opacity-60 ml-2 mt-0.5">{icon}</div>}
      </div>
    </div>
  )
}

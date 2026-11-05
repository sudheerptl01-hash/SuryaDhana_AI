'use client'

import clsx from 'clsx'

interface KPICardProps {
  label: string
  value: string | number
  subtext?: string
  trend?: 'up' | 'down' | 'stable'
  color?: 'indigo' | 'emerald' | 'rose' | 'amber' | 'violet' | 'cyan' | 'slate'
  icon?: React.ReactNode
  isDark?: boolean
}

const COLORS_LIGHT = {
  indigo:  'border-indigo-200 bg-indigo-50 text-indigo-600 [&_.val]:text-indigo-900',
  emerald: 'border-emerald-200 bg-emerald-50 text-emerald-600 [&_.val]:text-emerald-900',
  rose:    'border-rose-200 bg-rose-50 text-rose-600 [&_.val]:text-rose-900',
  amber:   'border-amber-200 bg-amber-50 text-amber-600 [&_.val]:text-amber-900',
  violet:  'border-violet-200 bg-violet-50 text-violet-600 [&_.val]:text-violet-900',
  cyan:    'border-cyan-200 bg-cyan-50 text-cyan-600 [&_.val]:text-cyan-900',
  slate:   'border-gray-200 bg-white text-gray-500 [&_.val]:text-gray-900',
}

const COLORS_DARK = {
  indigo:  'border-indigo-700/40 bg-gradient-to-br from-indigo-950/40 to-indigo-900/20 text-indigo-300 [&_.val]:text-indigo-200 shadow-lg shadow-indigo-500/5',
  emerald: 'border-emerald-700/40 bg-gradient-to-br from-emerald-950/40 to-emerald-900/20 text-emerald-300 [&_.val]:text-emerald-200 shadow-lg shadow-emerald-500/5',
  rose:    'border-rose-700/40 bg-gradient-to-br from-rose-950/40 to-rose-900/20 text-rose-300 [&_.val]:text-rose-200 shadow-lg shadow-rose-500/5',
  amber:   'border-amber-700/40 bg-gradient-to-br from-amber-950/40 to-amber-900/20 text-amber-300 [&_.val]:text-amber-200 shadow-lg shadow-amber-500/5',
  violet:  'border-violet-700/40 bg-gradient-to-br from-violet-950/40 to-violet-900/20 text-violet-300 [&_.val]:text-violet-200 shadow-lg shadow-violet-500/5',
  cyan:    'border-cyan-700/40 bg-gradient-to-br from-cyan-950/40 to-cyan-900/20 text-cyan-300 [&_.val]:text-cyan-200 shadow-lg shadow-cyan-500/5',
  slate:   'border-slate-700/40 bg-gradient-to-br from-slate-800/40 to-slate-700/20 text-slate-300 [&_.val]:text-slate-100 shadow-lg shadow-slate-700/5',
}

export function KPICard({ label, value, subtext, trend, color = 'indigo', icon, isDark = true }: KPICardProps) {
  const COLORS = isDark ? COLORS_DARK : COLORS_LIGHT
  return (
    <div className={clsx('rounded-xl border p-5 transition-all duration-300 hover:shadow-xl hover:scale-[1.02] cursor-default group', COLORS[color])}>
      <style>{`
        @keyframes shimmer {
          0% { box-shadow: 0 0 0 0 rgba(var(--color-rgb), 0); }
          50% { box-shadow: 0 0 12px 2px rgba(var(--color-rgb), 0.2); }
          100% { box-shadow: 0 0 0 0 rgba(var(--color-rgb), 0); }
        }
      `}</style>
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

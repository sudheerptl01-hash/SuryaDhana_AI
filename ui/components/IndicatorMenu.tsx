'use client'

/**
 * IndicatorMenu — reusable indicator picker + per-indicator customization.
 *
 * Drop into any chart toolbar. Exposes an "Add Indicator" dropdown and an inline
 * editor for every active indicator: colour swatch, parameter inputs (period,
 * std-dev, …), visibility toggle and remove. Fully controlled via `indicators` +
 * `onChange` so the parent owns state and persistence.
 */
import clsx from 'clsx'
import { useState } from 'react'
import {
  type IndicatorConfig, type IndicatorKind,
  INDICATOR_DEFS, INDICATOR_ORDER, indicatorLabel, makeIndicator,
} from '@/lib/indicators'

interface Props {
  indicators: IndicatorConfig[]
  onChange: (next: IndicatorConfig[]) => void
  isDark: boolean
}

export function IndicatorMenu({ indicators, onChange, isDark }: Props) {
  const [open, setOpen] = useState(false)

  const add = (kind: IndicatorKind) => {
    onChange([...indicators, makeIndicator(kind)])
    setOpen(false)
  }
  const patch = (id: string, p: Partial<IndicatorConfig>) =>
    onChange(indicators.map(c => (c.id === id ? { ...c, ...p } : c)))
  const patchParam = (id: string, key: string, value: number) =>
    onChange(indicators.map(c => (c.id === id ? { ...c, params: { ...c.params, [key]: value } } : c)))
  const remove = (id: string) => onChange(indicators.filter(c => c.id !== id))

  const chip = isDark ? 'bg-slate-800 border-slate-700' : 'bg-gray-100 border-gray-200'
  const sub  = isDark ? 'text-slate-400' : 'text-gray-500'
  const inp  = clsx('w-12 px-1 py-0.5 rounded text-[11px] font-mono outline-none border text-center',
    isDark ? 'bg-slate-900 border-slate-700 text-slate-200' : 'bg-white border-gray-300 text-gray-700')

  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      {/* Add-indicator dropdown */}
      <div className="relative">
        <button
          onClick={() => setOpen(o => !o)}
          className={clsx(
            'flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-bold border transition-colors',
            isDark ? 'bg-indigo-900/40 border-indigo-700 text-indigo-300 hover:bg-indigo-900/60'
                   : 'bg-indigo-50 border-indigo-200 text-indigo-700 hover:bg-indigo-100',
          )}
        >
          <span className="text-sm leading-none">ƒ</span> Indicators
          <span className="text-[9px] opacity-70">▾</span>
        </button>

        {open && (
          <>
            <div className="fixed inset-0 z-20" onClick={() => setOpen(false)} />
            <div className={clsx(
              'absolute left-0 mt-1 z-30 w-56 max-h-80 overflow-y-auto rounded-xl border shadow-2xl py-1',
              isDark ? 'bg-slate-900 border-slate-700' : 'bg-white border-gray-200',
            )}>
              {(['price', 'oscillator'] as const).map(pane => (
                <div key={pane}>
                  <div className={clsx('px-3 pt-2 pb-1 text-[10px] font-bold uppercase tracking-wider', sub)}>
                    {pane === 'price' ? 'Overlays' : 'Oscillators'}
                  </div>
                  {INDICATOR_ORDER.filter(k => INDICATOR_DEFS[k].pane === pane).map(kind => {
                    const def = INDICATOR_DEFS[kind]
                    return (
                      <button
                        key={kind}
                        onClick={() => add(kind)}
                        className={clsx(
                          'w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left transition-colors',
                          isDark ? 'text-slate-200 hover:bg-slate-800' : 'text-gray-700 hover:bg-gray-100',
                        )}
                      >
                        <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: def.defaultColor }} />
                        {def.label}
                      </button>
                    )
                  })}
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      {/* Active indicator chips with inline editors */}
      {indicators.map(cfg => {
        const def = INDICATOR_DEFS[cfg.kind]
        return (
          <div
            key={cfg.id}
            className={clsx('flex items-center gap-1.5 pl-1.5 pr-1 py-0.5 rounded-lg border', chip,
              !cfg.visible && 'opacity-50')}
          >
            <input
              type="color"
              value={cfg.color}
              onChange={e => patch(cfg.id, { color: e.target.value })}
              title="Line colour"
              className="w-4 h-4 rounded cursor-pointer border-0 bg-transparent p-0"
            />
            <span className={clsx('text-[11px] font-bold font-mono', isDark ? 'text-slate-200' : 'text-gray-700')}>
              {indicatorLabel(cfg)}
            </span>
            {def.params.map(spec => (
              <input
                key={spec.key}
                type="number"
                min={spec.min}
                max={spec.max}
                step={spec.step ?? 1}
                value={cfg.params[spec.key]}
                title={spec.label}
                onChange={e => {
                  const v = Number(e.target.value)
                  if (!Number.isNaN(v)) patchParam(cfg.id, spec.key, v)
                }}
                className={inp}
              />
            ))}
            <button
              onClick={() => patch(cfg.id, { visible: !cfg.visible })}
              title={cfg.visible ? 'Hide' : 'Show'}
              className={clsx('text-xs px-0.5 leading-none', sub, 'hover:opacity-80')}
            >
              {cfg.visible ? '◉' : '○'}
            </button>
            <button
              onClick={() => remove(cfg.id)}
              title="Remove"
              className={clsx('text-xs px-0.5 leading-none hover:text-rose-500', sub)}
            >
              ✕
            </button>
          </div>
        )
      })}
    </div>
  )
}

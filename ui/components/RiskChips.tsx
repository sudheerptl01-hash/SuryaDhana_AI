'use client'

/** NSE surveillance / risk chips for one stock (ASM LT 1, GSM 2, BAND 5%, T2T, F&O BAN…); renders nothing when clean. */
import type { RiskFlags } from '@/lib/api'
import { T } from '@/components/terminal'

const COLOR = { high: T.red, medium: T.amber, low: T.muted } as const

export function RiskChips({ flags, max = 3 }: { flags?: RiskFlags | null; max?: number }) {
  const chips = flags?.chips ?? []
  if (!chips.length) return null
  const shown = chips.slice(0, max)
  return (
    <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center', flexWrap: 'nowrap' }}
      title={chips.map(c => `${c.code}: ${c.why}`).join('\n') + '\n(NSE surveillance files; context, not a signal)'}>
      {shown.map(c => (
        <span key={c.code} style={{ fontFamily: T.mono, fontSize: 9, letterSpacing: 0.6, color: COLOR[c.level], whiteSpace: 'nowrap',
                                    border: `1px solid ${COLOR[c.level]}66`, padding: '0 4px' }}>⚑ {c.code}</span>))}
      {chips.length > max && <span style={{ fontSize: 9, color: T.dim }}>+{chips.length - max}</span>}
    </span>
  )
}

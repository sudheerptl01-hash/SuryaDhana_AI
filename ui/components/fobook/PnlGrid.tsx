'use client'

/**
 * OSTR v2 — the 2-D P&L grid (review M39 / PLAN 2.2): spot −5 … +5 % (rows) × IV −10 … +10 pts (columns) at one date
 * (chips: today … the nearest expiry). Every cell is a Black-76 revaluation of every leg from POST
 * /api/options/strategy/analyze (`grid: true`); badge arithmetic; costs excluded. Green / red is the P&L's sign
 * (arithmetic), intensity its size against the largest cell of the date shown.
 */
import { useMemo, useState } from 'react'
import { BadgeChip, Chip, Label, T } from '@/components/terminal'
import { gridMaxAbs, heatColor } from './ostrModel'

export interface PnlGridData {
  spot_pct: number[]; spot: number[]; iv_shift: number[]; days: number[]; pnl: number[][][]; badge: string; note: string
}

const compact = (v: number) => {
  const a = Math.abs(v), s = v < 0 ? '−' : v > 0 ? '+' : ''
  if (a >= 1e7) return `${s}₹${(a / 1e7).toFixed(1)}cr`
  if (a >= 1e5) return `${s}₹${(a / 1e5).toFixed(1)}L`
  if (a >= 1e3) return `${s}₹${(a / 1e3).toFixed(1)}k`
  return `${s}₹${a.toFixed(0)}`
}

/** ±0 is every leg at ITS OWN IV (the chain's IV per strike / expiry), not the ATM IV the page header already prints. */
export const IV_ZERO_HEADER = "±0 (each leg's IV)"

export function PnlGrid({ grid }: { grid: PnlGridData }) {
  const [di, setDi] = useState(0)
  const d = Math.min(di, grid.days.length - 1)
  const slice = grid.pnl[d] ?? []
  const maxAbs = useMemo(() => gridMaxAbs(slice), [slice])
  const rows = grid.spot_pct.map((p, i) => ({ p, i })).reverse()           // +5 % on top
  return (
    <div data-ostr-grid>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 }}>
        <Label>P&L at</Label>
        {grid.days.map((x, i) => (
          <Chip key={x} color={T.cyan} active={i === d} onClick={() => setDi(i)}>{i === 0 ? 'today' : i === grid.days.length - 1 ? `expiry (+${x}d)` : `+${x}d`}</Chip>
        ))}
        <span style={{ flex: 1 }} />
        <BadgeChip badge={grid.badge} note={grid.note} />
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', fontFamily: T.mono, fontSize: 10, width: '100%', minWidth: 520 }}>
          <thead>
            <tr>
              <th style={{ color: T.dim, textAlign: 'left', padding: '3px 6px', fontWeight: 400 }}>spot \ IV</th>
              {grid.iv_shift.map(s => (
                <th key={s} style={{ color: s === 0 ? T.text : T.dim, padding: '3px 4px', fontWeight: s === 0 ? 600 : 400, textAlign: 'right' }}>
                  {s === 0 ? IV_ZERO_HEADER : `${s > 0 ? '+' : '−'}${Math.abs(s)}`}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(({ p, i }) => (
              <tr key={p}>
                <td style={{ color: p === 0 ? T.text : T.dim, padding: '3px 6px', whiteSpace: 'nowrap', fontWeight: p === 0 ? 600 : 400 }}>
                  {p === 0 ? 'fwd' : `${p > 0 ? '+' : '−'}${Math.abs(p)}%`} <span style={{ color: T.dim }}>{grid.spot[i].toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
                </td>
                {(slice[i] ?? []).map((v, j) => (
                  <td key={j} title={`spot ${grid.spot[i].toLocaleString('en-IN')} · IV ${grid.iv_shift[j] >= 0 ? '+' : ''}${grid.iv_shift[j]} pts · ₹${v.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`}
                    style={{ background: heatColor(v, maxAbs, T.green, T.red, T.panel3), color: T.bright, textAlign: 'right', padding: '3px 4px',
                             border: `1px solid ${T.panel}`, outline: p === 0 && grid.iv_shift[j] === 0 ? `1px solid ${T.amber}` : undefined }}>
                    {compact(v)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{ fontSize: 10, color: T.dim, marginTop: 6, lineHeight: 1.5 }}>{grid.note}. Columns shift every leg&apos;s own IV by the same points. The amber-outlined cell: the forward and the IVs unchanged.</div>
    </div>
  )
}

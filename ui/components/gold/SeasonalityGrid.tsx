'use client'

/**
 * m.season — seasonality grid (PLAN a.5; shared component, rendered by MonthlyView): mean monthly return and hit rate
 * per calendar month, Indian festival months marked, with the caption from G-STUDY / G-MACRO H3 ("Dec/Jan strong
 * historically; no month passes in both halves; walk-forward best-6-months +0.3 %/yr"). Context metric: the cell
 * shade is a neutral intensity, never green/red; hover shows the box of outcomes when the caller provides it.
 */
import { T } from '@/components/terminal'
import { signedPct } from './goldViewModel'

export interface SeasonRow { month: number; mean_pct: number | null; hit_rate?: number | null; n?: number | null; p10?: number | null; p90?: number | null; t?: number | null }

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const FESTIVAL: Record<number, string> = { 4: 'Akshaya Tritiya', 10: 'Dhanteras / Diwali (Oct–Nov)', 11: 'Dhanteras / Diwali (Oct–Nov)' }

export function SeasonalityGrid({ rows, since, source, tips }: { rows: SeasonRow[]; since?: string; source?: string; tips: (k: string) => string | undefined }) {
  const maxA = Math.max(0.5, ...rows.map(r => Math.abs(r.mean_pct ?? 0)))
  const byM = new Map(rows.map(r => [r.month, r]))
  return (
    <div data-seasonality>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(12, minmax(0, 1fr))', gap: 3 }}>
        {MONTHS.map((m, i) => {
          const r = byM.get(i + 1)
          const a = r?.mean_pct != null ? Math.abs(r.mean_pct) / maxA : 0
          const tip = r ? `${m}: mean ${signedPct(r.mean_pct, 2)} · hit rate ${r.hit_rate != null ? `${Math.round(r.hit_rate * 100)} %` : '—'}${r.n != null ? ` · n ${r.n}` : ''}${r.p10 != null && r.p90 != null ? ` · p10 ${signedPct(r.p10, 1)} / p90 ${signedPct(r.p90, 1)}` : ''}${r.t != null ? ` · t ${r.t.toFixed(1)}` : ''}${FESTIVAL[i + 1] ? ` · ${FESTIVAL[i + 1]}` : ''}` : `${m}: no data`
          return (
            <div key={m} title={`${tip}\n${tips('season_mean') ?? ''}`} style={{ border: `1px solid ${FESTIVAL[i + 1] ? T.amberDim : T.border}`, padding: '5px 2px', textAlign: 'center', background: `rgba(181,139,255,${(0.08 + a * 0.5).toFixed(2)})` }}>
              <div style={{ fontSize: 9, color: T.muted, fontFamily: T.mono }}>{m}{FESTIVAL[i + 1] ? ' ✦' : ''}</div>
              <div style={{ fontSize: 11, color: T.bright, fontFamily: T.mono }}>{r ? signedPct(r.mean_pct, 1) : '—'}</div>
              <div style={{ fontSize: 8.5, color: T.dim, fontFamily: T.mono }} title={tips('season_hit_rate')}>{r?.hit_rate != null ? `${Math.round(r.hit_rate * 100)} %` : ''}</div>
            </div>
          )
        })}
      </div>
      <div style={{ fontSize: 10, color: T.muted, marginTop: 6, lineHeight: 1.5 }}>
        Mean monthly return and hit rate{since ? ` since ${since}` : ''}{source ? ` (${source})` : ''}; ✦ = Indian festival month. Dec/Jan strong historically; no month passes in both halves — in USD (G-MACRO H3) or in rupees once the +1 %/month drift is removed (GS-P4, 26 Oct 2026); festival months do not pass;
        walk-forward best-6-months +0.3 %/yr USD, +1.1 %/yr rupees after costs — both FAIL. Context, not a signal.
      </div>
    </div>
  )
}

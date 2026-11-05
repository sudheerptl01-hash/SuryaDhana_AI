'use client'

/**
 * mc.kgx — "Gold or the dollar?" (PLAN a.8): the period's gold move in USD split into pure gold + the USD effect
 * (DXY weights) with a separate rupee leg for MCX. An identity (arithmetic badge): total = pure + usd_effect; the
 * identity line prints only when all three legs exist. When the dollar leg is missing the bar shows the total (and the
 * rupee leg when present) and the caller's `note` says why the split is empty — never the developer assertion the
 * critic saw (C-BEGINNER-14). Signs use U+2212; the bar colours are the neutral palette with the pure-gold leg in amber.
 */
import { CHART_BOX, T, useChartSize } from '@/components/terminal'
import { kgxConsistent, signedPct } from './goldViewModel'

export function KgxBar({ period, total, pure, usdEffect, inrEffect, weights, note, tips }: {
  period: string; total: number | null; pure: number | null; usdEffect: number | null; inrEffect?: number | null
  weights?: Record<string, number>; /** why the split is empty (shown instead of the identity line) */ note?: string | null
  tips: (k: string) => string | undefined
}) {
  const { ref, w } = useChartSize(640, 70, { minRatio: 1, maxRatio: 1 })
  const split = pure != null && usdEffect != null
  const legs = [
    { key: 'total', label: `gold in USD (${period})`, v: total, color: T.borderHi, tip: 'kgx_total' },
    ...(split ? [
      { key: 'pure', label: 'pure gold', v: pure, color: T.amber, tip: 'kgx_pure_gold' },
      { key: 'usd', label: 'USD effect (DXY basket)', v: usdEffect, color: T.cyan, tip: 'kgx_usd_effect' },
    ] : []),
    ...(inrEffect != null ? [{ key: 'inr', label: 'rupee leg (USD/INR), for MCX', v: inrEffect, color: T.violet, tip: 'kgx_inr_effect' }] : []),
  ]
  const maxA = Math.max(0.1, ...legs.map(l => Math.abs(l.v ?? 0)))
  const labelW = 190
  const half = (w - labelW - 70) / 2
  const cx = labelW + half
  const rowH = 16
  const h = legs.length * rowH + 6
  const ok = kgxConsistent(total, pure, usdEffect)
  return (
    <div ref={ref} style={CHART_BOX}>
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Gold or the dollar">
        <line x1={cx} x2={cx} y1={0} y2={h} stroke={T.borderHi} />
        {legs.map((l, i) => {
          const y = i * rowH + 3
          const len = ((Math.abs(l.v ?? 0)) / maxA) * half
          return (
            <g key={l.key} data-kgx-leg={l.key}>
              <title>{tips(l.tip)}</title>
              <text x={2} y={y + 10} fontSize={9.5} fontFamily={T.mono} fill={T.text}>{l.label}</text>
              {l.v != null && <rect x={l.v >= 0 ? cx : cx - len} y={y + 2} width={Math.max(1, len)} height={9} fill={l.color} opacity={0.85} />}
              <text x={l.v != null && l.v >= 0 ? cx + len + 4 : cx - len - 4} y={y + 10} textAnchor={l.v != null && l.v >= 0 ? 'start' : 'end'} fontSize={9.5} fontFamily={T.mono} fill={T.bright}>{signedPct(l.v, 2)}</text>
            </g>
          )
        })}
      </svg>
      <div style={{ fontSize: 10, color: T.muted, marginTop: 2 }}>
        {split
          ? <span data-kgx-identity={ok ? 'holds' : 'off'}>total = pure + USD effect {ok ? <span style={{ color: T.dim }}>(identity holds)</span> : <span style={{ color: T.amber }}>(identity off by more than 0.02 pp)</span>}</span>
          : <span data-kgx-unavailable style={{ color: T.amber }}>{note ?? 'USD effect unavailable: the split needs the DXY basket’s daily closes'}</span>}
        {split && weights && Object.keys(weights).length > 0 && <span style={{ color: T.dim }}> · basket {Object.entries(weights).map(([k, v]) => `${k} ${(v * 100).toFixed(1)} %`).join(' · ')}</span>}
      </div>
    </div>
  )
}

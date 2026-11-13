'use client'

/**
 * p.whois — who is long / who is short (PLAN a.6): paired horizontal bars per trader group (long to the right, short
 * to the left) with the week's Δ arrows and the "closed longs / covered shorts / new longs / new shorts" chips.
 * Every long has a short: the five disaggregated groups sum to the open interest. Legacy groups (non-commercial /
 * commercial) sit behind a toggle. Context metric: neutral tokens only (PLAN §f.3).
 *
 * Layout: [group label | short number · short bar ◀ 0 ▶ long bar · long number | chips]; the bar half-width leaves
 * room for the numbers on both sides so a large short (swap dealers) never runs into the label column.
 */
import { useState } from 'react'
import { CHART_BOX, Chip, T, useChartSize } from '@/components/terminal'
import type { CotGroup } from '@/lib/gold/types'
import { deltaArrow, num, pct, signed, whoDidWords } from './goldViewModel'

const DISAGG = ['mm', 'or', 'nr', 'sd', 'pm'] as const
const LEGACY = ['nc', 'c', 'nr'] as const
const LABEL: Record<string, string> = {
  mm: 'Managed money (funds, CTAs)', or: 'Other reportables', nr: 'Non-reportable (small traders)',
  sd: 'Swap dealers (banks\' OTC book)', pm: 'Producer / merchant', nc: 'Non-commercial (legacy)', c: 'Commercial (legacy)',
}
const ROW_H = 38
const NUM_W = 72          // room for "1,43,884 ▼" beside each bar end

export function CotWhoIsLong({ groups, oi, tips }: { groups: CotGroup[]; oi: number | null; tips: (k: string) => string | undefined }) {
  const [legacy, setLegacy] = useState(false)
  const keys = legacy ? LEGACY : DISAGG
  const rows = keys.map(k => groups.find(g => g.key === k)).filter((g): g is CotGroup => !!g)
  const { ref, w } = useChartSize(760, 40, { minRatio: 1, maxRatio: 1 })
  const maxV = Math.max(1, ...rows.flatMap(g => [g.long ?? 0, g.short ?? 0]))
  const labelW = Math.min(210, Math.max(150, w * 0.22))
  const chipW = Math.min(320, Math.max(200, w * 0.26))
  const half = Math.max(50, (w - labelW - chipW) / 2 - NUM_W - 6)
  const cx = labelW + NUM_W + half
  const h = rows.length * ROW_H + 18
  const sx = (v: number) => (v / maxV) * half
  return (
    <div ref={ref} style={CHART_BOX}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 10, color: T.muted, marginBottom: 4 }}>
        <span title={tips('who_did')}>short ◀ · ▶ long · contracts as of the report Tuesday · Δ on the week</span>
        <span style={{ flex: 1 }} />
        <Chip color={T.muted} active={legacy} onClick={() => setLegacy(l => !l)} title="Legacy report groups (non-commercial / commercial / non-reportable); the disaggregated groups are the default">{legacy ? 'LEGACY GROUPS' : 'DISAGGREGATED'}</Chip>
      </div>
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Who is long, who is short">
        <line x1={cx} x2={cx} y1={0} y2={h - 16} stroke={T.borderHi} />
        {rows.map((g, i) => {
          const y = i * ROW_H + 4
          const L = g.long ?? 0, S = g.short ?? 0
          const words = g.who_did?.length ? g.who_did : whoDidWords(g.chg_long, g.chg_short)
          return (
            <g key={g.key} data-cot-group={g.key}>
              <text x={4} y={y + 13} fontSize={11} fontFamily={T.mono} fill={T.text}>{(LABEL[g.key] ?? g.label).slice(0, 30)}</text>
              <text x={4} y={y + 25} fontSize={9} fontFamily={T.mono} fill={T.dim}>net {signed(g.net)} · {oi ? pct(g.net_pct_oi ?? ((g.net ?? 0) / oi) * 100, 1) : '—'} of OI</text>
              <rect x={cx - sx(S)} y={y + 5} width={sx(S)} height={10} fill={T.muted} opacity={0.75}><title>{`${g.label} short ${num(S)}`}</title></rect>
              <rect x={cx} y={y + 5} width={sx(L)} height={10} fill={T.violet} opacity={0.85}><title>{`${g.label} long ${num(L)}`}</title></rect>
              <text x={cx - sx(S) - 4} y={y + 13} textAnchor="end" fontSize={9} fontFamily={T.mono} fill={T.muted}>{num(S)} {deltaArrow(g.chg_short)}</text>
              <text x={cx + sx(L) + 4} y={y + 13} fontSize={9} fontFamily={T.mono} fill={T.text}>{num(L)} {deltaArrow(g.chg_long)}</text>
              <text x={cx - sx(S) - 4} y={y + 25} textAnchor="end" fontSize={9} fontFamily={T.mono} fill={T.dim}>Δ {signed(g.chg_short)}</text>
              <text x={cx + sx(L) + 4} y={y + 25} fontSize={9} fontFamily={T.mono} fill={T.dim}>Δ {signed(g.chg_long)}</text>
              <foreignObject x={w - chipW} y={y} width={chipW} height={ROW_H - 2}>
                <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap', justifyContent: 'flex-end', alignItems: 'flex-start', lineHeight: 1.1 }} title={tips('who_did')}>
                  {words.length ? words.map(wd => <Chip key={wd} color={T.muted} style={{ fontSize: 9, padding: '1px 5px', whiteSpace: 'nowrap' }}>{wd}</Chip>) : <Chip color={T.dim} style={{ fontSize: 9, padding: '1px 5px' }}>unchanged</Chip>}
                </div>
              </foreignObject>
            </g>
          )
        })}
        <text x={cx} y={h - 3} textAnchor="middle" fontSize={9} fontFamily={T.mono} fill={T.dim}>0</text>
      </svg>
    </div>
  )
}

'use client'

/**
 * Industry rotation (RRG-style): x = relative strength vs the equal-weight NSE universe (100 = in line with its
 * own 50-day trend), y = momentum of that strength (100 = flat). Tails = last 8 weeks, dot = this week.
 * Industries tend to rotate clockwise: Improving → Leading → Weakening → Lagging. Descriptive, not a signal.
 */
import { useMemo, useState } from 'react'
import { CHART_BOX, Chip, Panel, T, useChartSize, undatedSource } from '@/components/terminal'

export interface RotationRow { industry: string; stocks: number; quadrant: string; tail: { date: string; x: number | null; y: number | null }[] }

const Q_COLOR: Record<string, string> = { Leading: T.green, Weakening: T.amber, Lagging: T.red, Improving: T.cyan }
const PAD = 40

export function RotationChart({ rows }: { rows: RotationRow[] }) {
  // CSS px (C1-17): industry labels stay 9.5 px at any width
  const { ref, w: W, h: H } = useChartSize(1240, 600, { minRatio: 0.75, maxRatio: 1.1 })
  const [focus, setFocus] = useState<string | null>(null)
  const [only, setOnly] = useState<string | null>(null)
  const pts = rows.flatMap(r => r.tail).filter(p => p.x != null && p.y != null) as { x: number; y: number }[]
  const span = useMemo(() => {
    const dx = Math.max(2, ...pts.map(p => Math.abs(p.x - 100))) * 1.12
    const dy = Math.max(1, ...pts.map(p => Math.abs(p.y - 100))) * 1.12
    return { dx, dy }
  }, [pts])
  const sx = (x: number) => PAD + ((x - (100 - span.dx)) / (2 * span.dx)) * (W - 2 * PAD)
  const sy = (y: number) => H - PAD - ((y - (100 - span.dy)) / (2 * span.dy)) * (H - 2 * PAD)
  const shown = rows.filter(r => !only || r.quadrant === only)
  const counts = Object.fromEntries(Object.keys(Q_COLOR).map(q => [q, rows.filter(r => r.quadrant === q).length]))

  return (
    <Panel source={undatedSource('NSE EOD (weekly)')} badge="context" title="Industry rotation" accent={T.cyan} pad={0}
      subtitle="relative strength vs the NSE universe (→) and its momentum (↑) · 8-week tails · clockwise rotation is typical"
      right={<div style={{ display: 'flex', gap: 4 }}>
        <Chip color={T.muted} active={!only} onClick={() => setOnly(null)}>ALL</Chip>
        {Object.keys(Q_COLOR).map(q => <Chip key={q} color={Q_COLOR[q]} active={only === q} onClick={() => setOnly(only === q ? null : q)}>{q.toUpperCase()} {counts[q]}</Chip>)}
      </div>}>
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 260px' }}>
        <div ref={ref} style={CHART_BOX}>
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ display: 'block' }} role="img" aria-label="Industry rotation">
          {[['Leading', sx(100), PAD, W - PAD, sy(100)], ['Weakening', sx(100), sy(100), W - PAD, H - PAD],
            ['Lagging', PAD, sy(100), sx(100), H - PAD], ['Improving', PAD, PAD, sx(100), sy(100)]].map(([q, x1, y1, x2, y2]) => (
            <g key={q as string}>
              <rect x={x1 as number} y={y1 as number} width={(x2 as number) - (x1 as number)} height={(y2 as number) - (y1 as number)}
                    fill={Q_COLOR[q as string]} opacity={0.045} />
              <text x={(q === 'Leading' || q === 'Weakening') ? (x2 as number) - 8 : (x1 as number) + 8}
                    y={(q === 'Leading' || q === 'Improving') ? (y1 as number) + 16 : (y2 as number) - 8}
                    textAnchor={(q === 'Leading' || q === 'Weakening') ? 'end' : 'start'}
                    fontSize={12} fontFamily={T.display} letterSpacing={2} fill={Q_COLOR[q as string]} opacity={0.75}>
                {(q as string).toUpperCase()}
              </text>
            </g>
          ))}
          <line x1={sx(100)} x2={sx(100)} y1={PAD} y2={H - PAD} stroke={T.borderHi} />
          <line x1={PAD} x2={W - PAD} y1={sy(100)} y2={sy(100)} stroke={T.borderHi} />
          <text x={W - PAD} y={H - 12} textAnchor="end" fontSize={10} fill={T.dim} fontFamily={T.mono}>RS-ratio → stronger than the market</text>
          <text x={14} y={PAD - 12} fontSize={10} fill={T.dim} fontFamily={T.mono}>↑ RS-momentum</text>
          {shown.map(r => {
            const t = r.tail.filter(p => p.x != null && p.y != null) as { x: number; y: number; date: string }[]
            if (t.length < 2) return null
            const last = t[t.length - 1]
            const c = Q_COLOR[r.quadrant]
            const dim = focus && focus !== r.industry
            return (
              <g key={r.industry} opacity={dim ? 0.15 : 1} onMouseEnter={() => setFocus(r.industry)} onMouseLeave={() => setFocus(null)} style={{ cursor: 'default' }}>
                {t.slice(1).map((p, i) => (
                  <line key={i} x1={sx(t[i].x)} y1={sy(t[i].y)} x2={sx(p.x)} y2={sy(p.y)} stroke={c}
                        strokeWidth={focus === r.industry ? 2.4 : 1.1} opacity={0.2 + (0.6 * (i + 1)) / t.length} />
                ))}
                {t.slice(0, -1).map((p, i) => <circle key={i} cx={sx(p.x)} cy={sy(p.y)} r={1.8} fill={c} opacity={0.35 + (0.4 * i) / t.length} />)}
                <circle cx={sx(last.x)} cy={sy(last.y)} r={focus === r.industry ? 6 : 4.5} fill={c} stroke={T.bg} strokeWidth={1.5} />
                <text x={sx(last.x) + 7} y={sy(last.y) + 3} fontSize={focus === r.industry ? 11.5 : 9.5} fontFamily={T.mono}
                      fill={focus === r.industry ? T.bright : T.text}>
                  {r.industry.length > 22 && focus !== r.industry ? `${r.industry.slice(0, 21)}…` : r.industry}
                </text>
                <title>{`${r.industry} (${r.stocks} stocks): ${r.quadrant} · RS-ratio ${last.x.toFixed(1)} · momentum ${last.y.toFixed(1)} · week of ${last.date}`}</title>
              </g>
            )
          })}
        </svg>
        </div>
        <div style={{ borderLeft: `1px solid ${T.border}`, maxHeight: 600, overflowY: 'auto' }}>
          {(['Leading', 'Improving', 'Weakening', 'Lagging'] as const).map(q => (
            <div key={q}>
              <div style={{ padding: '7px 10px 3px', fontFamily: T.display, fontSize: 10, letterSpacing: 1.5, color: Q_COLOR[q] }}>{q.toUpperCase()}</div>
              {rows.filter(r => r.quadrant === q).map(r => {
                const l = r.tail[r.tail.length - 1]
                return (
                  <div key={r.industry} onMouseEnter={() => setFocus(r.industry)} onMouseLeave={() => setFocus(null)}
                    style={{ display: 'flex', justifyContent: 'space-between', gap: 6, padding: '3px 10px', fontSize: 11,
                             background: focus === r.industry ? T.panel3 : 'transparent', cursor: 'default' }}>
                    <span style={{ color: T.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.industry}</span>
                    <span style={{ color: T.muted, fontFamily: T.mono, flex: 'none' }}>{l.x?.toFixed(1)} · {l.y?.toFixed(1)}</span>
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      </div>
    </Panel>
  )
}

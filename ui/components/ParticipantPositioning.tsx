'use client'

/**
 * Who holds index futures: FII / DII / Pro / Client long and short contracts, net, long %, and how the net changed
 * over 1 and 5 sessions, plus one year of the FII long ratio (NSE participant-wise OI, end of day). Underneath: FII and DII
 * cash-market net buying (₹ cr), collected daily from NSE since 12 Oct 2026.
 */
import { useEffect, useState } from 'react'
import { getFiiDiiCash, getParticipants, type FiiDiiCash, type ParticipantRow } from '@/lib/api'
import { CHART_BOX, DataTable, Panel, T, type Column, tone, useChartSize, sourceOf } from '@/components/terminal'
import { cashCoverage } from '@/components/marketPagesModel'

const LABEL: Record<string, string> = { FII: 'Foreign institutions (FII)', DII: 'Domestic institutions (DII)', PRO: 'Proprietary traders', CLIENT: 'Clients (retail + HNI)' }
const k = (v: number | null | undefined) => (v == null ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v) >= 1e5 ? `${(Math.abs(v) / 1e5).toFixed(2)} L` : Math.abs(v).toLocaleString('en-IN')}`)
const crore = (v: number | undefined) => (v == null ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}₹${Math.abs(v).toLocaleString('en-IN', { maximumFractionDigits: 0 })} cr`)

/**
 * FII / DII cash-market net buying: latest session, the last 5 sessions and month to date. M09: each sum says how
 * many of its sessions are collected ("3 of 5 sessions · missing 02 Nov, 03 Nov", data-service's NSE session
 * calendar), in amber when one is missing: never a silent skip.
 */
export function CashFlows({ cash, compact = false }: { cash: FiiDiiCash; compact?: boolean }) {
  const s = cash.summary
  if (!s.latest_date) return null
  const cov5 = cashCoverage(s, '5d'), covM = cashCoverage(s, 'mtd')
  const cell = (label: string, rec: Record<string, number>, note?: string, gap = false) => (
    <span style={{ whiteSpace: 'nowrap' }}>
      <span style={{ color: T.dim }}>{label}{note ? <span style={{ fontSize: 9, color: gap ? T.amber : T.dim }}> ({note})</span> : null} </span>
      <span style={{ color: T.amber }}>FII</span> <span style={{ color: tone(rec.FII) }}>{crore(rec.FII)}</span>
      <span style={{ color: T.cyan, marginLeft: 6 }}>DII</span> <span style={{ color: tone(rec.DII) }}>{crore(rec.DII)}</span>
    </span>
  )
  const day = new Date(`${s.latest_date}T00:00:00`).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })
  return (
    <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: '4px 16px', fontSize: compact ? 11 : 11.5 }}>
      {cell(day, s.latest)}
      {!compact && (s.sessions_5d ?? 0) > 1 && cell('5 sessions', s.sum_5d, cov5.text, cov5.gap)}
      {!compact && (s.sessions_mtd ?? 0) > 0 && cell('month to date', s.mtd, covM.text, covM.gap)}
    </span>
  )
}

export function ParticipantPositioning() {
  const [d, setD] = useState<Awaited<ReturnType<typeof getParticipants>>['data'] | null>(null)
  const [cash, setCash] = useState<FiiDiiCash | null>(null)
  useEffect(() => { getParticipants(250).then(r => setD(r.data)).catch(() => {}) }, [])
  useEffect(() => { getFiiDiiCash(60).then(r => setCash(r.data)).catch(() => {}) }, [])
  const { ref: chartRef, w: W, h: H } = useChartSize(520, 150)   // CSS px (C1-17)
  if (!d) return null
  const cols: Column<ParticipantRow>[] = [
    { key: 'ct', label: 'Participant', render: r => <span style={{ color: r.client_type === 'FII' ? T.amber : T.text }}>{LABEL[r.client_type] ?? r.client_type}</span> },
    { key: 'long', label: 'Index fut. long', align: 'right', render: r => k(r.fut_long).replace('+', '') },
    { key: 'short', label: 'Short', align: 'right', render: r => k(r.fut_short).replace('+', '') },
    { key: 'net', label: 'Net', align: 'right', sort: r => r.fut_net, render: r => <span style={{ color: tone(r.fut_net), fontWeight: 600 }}>{k(r.fut_net)}</span> },
    { key: 'pct', label: 'Long %', align: 'right', sort: r => r.fut_long_pct, render: r => <span style={{ color: r.fut_long_pct >= 50 ? T.green : T.red }}>{r.fut_long_pct}%</span> },
    { key: 'c1', label: 'Net chg 1d', align: 'right', render: r => <span style={{ color: tone(r.fut_net_chg_1d) }}>{k(r.fut_net_chg_1d)}</span> },
    { key: 'c5', label: 'Net chg 5d', align: 'right', render: r => <span style={{ color: tone(r.fut_net_chg_5d) }}>{k(r.fut_net_chg_5d)}</span> },
    { key: 'opt', label: 'Index options (bull − bear)', align: 'right', render: r => <span style={{ color: tone(r.opt_net_bull) }}>{k(r.opt_net_bull)}</span> },
  ]
  const h = d.fii_history
  const P = 26
  // fit the series; draw the 50% "balanced" line only when the data comes near it (FIIs sat at 5–20% long for most of 2025–26)
  const lo = Math.max(0, Math.floor(Math.min(...h.map(x => x.long_pct)) - 2)), hi = Math.min(100, Math.ceil(Math.max(...h.map(x => x.long_pct)) + 2))
  const ticks = [lo, Math.round((lo + hi) / 2), hi, ...(50 > lo && 50 < hi ? [50] : [])]
  const x = (i: number) => P + (i / Math.max(h.length - 1, 1)) * (W - 2 * P)
  const y = (v: number) => 8 + (1 - (v - lo) / (hi - lo || 1)) * (H - 28)
  const last = h[h.length - 1]
  return (
    <Panel source={sourceOf(d.date, { source: 'NSE participant OI' })} badge="context" title="Who holds index futures" accent={T.violet} pad={0}
      subtitle={`NSE participant-wise open interest · ${d.date} · contracts · options = long calls − short calls − (long puts − short puts)`}>
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.7fr) minmax(300px, 1fr)' }}>
        <div>
          <DataTable columns={cols} rows={d.snapshot} rowKey={r => r.client_type} dense />
          {cash?.summary.latest_date && (
            <div style={{ padding: '8px 10px', borderTop: `1px solid ${T.border}`, fontSize: 11 }}>
              <div style={{ fontSize: 10, color: T.muted, letterSpacing: 0.5, marginBottom: 4 }}>CASH MARKET NET BUYING · NSE + BSE, provisional · history collected from 12 Oct 2026</div>
              <CashFlows cash={cash} />
            </div>
          )}
        </div>
        <div style={{ borderLeft: `1px solid ${T.border}`, padding: '8px 10px' }}>
          <div style={{ fontSize: 10.5, color: T.muted, marginBottom: 4 }}>
            FII index-futures long ratio, 1 year · now <b style={{ color: (last?.long_pct ?? 50) >= 50 ? T.green : T.red }}>{last?.long_pct}%</b>
            <span style={{ color: T.dim }}> · 50% = balanced · tested: does not predict NIFTY over 5–20 sessions (RSCH)</span>
          </div>
          <div ref={chartRef} style={CHART_BOX}>
          <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ display: 'block' }} role="img" aria-label="FII long ratio">
            {ticks.map(v => (
              <g key={v}>
                <line x1={P} x2={W - P} y1={y(v)} y2={y(v)} stroke={v === 50 ? T.borderHi : T.border} strokeDasharray="3 4" />
                <text x={P - 4} y={y(v) + 3} textAnchor="end" fontSize={9} fill={T.dim} fontFamily={T.mono}>{v.toFixed(0)}%</text>
              </g>
            ))}
            <path d={h.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.long_pct).toFixed(1)}`).join('')} fill="none" stroke={T.amber} strokeWidth={1.6} />
            <text x={P} y={H - 4} fontSize={9} fill={T.dim} fontFamily={T.mono}>{h[0]?.date}</text>
            <text x={W - P} y={H - 4} textAnchor="end" fontSize={9} fill={T.dim} fontFamily={T.mono}>{last?.date}</text>
          </svg>
          </div>
        </div>
      </div>
    </Panel>
  )
}

'use client'

import { apiError } from '@/lib/errors'
/**
 * SEAG · seasonality (Bloomberg SEAG) for an NSE index or stock: average return by calendar month with its hit rate,
 * and the year × month heatmap behind it. The current month shows "so far" and is not in the averages.
 * Used as a page (GO: SEAG, with an index / ticker picker) and as the SEAG tab of the stock window.
 */
import { useEffect, useState } from 'react'
import { getSeasonality, type Seasonality as SeasonalityData } from '@/lib/api'
import { Btn, Chip, ErrorBox, Input, Loading, PageHeader, Panel, T, fmtFixed, fmtPct, undatedSource } from '@/components/terminal'   // fmtFixed: U+2212 (C1-18)

const INDICES = ['NIFTY 50', 'NIFTY BANK', 'NIFTY IT', 'NIFTY MIDCAP 100', 'NIFTY SMALLCAP 100', 'NIFTY FMCG', 'NIFTY PHARMA', 'NIFTY METAL']

/** cell colour: green / red with strength by size (±6% = full) */
const heat = (v: number | null | undefined) => {
  if (v == null) return 'transparent'
  const a = Math.min(1, Math.abs(v) / 6) * 0.55 + 0.05
  return v >= 0 ? `rgba(34,197,94,${a.toFixed(2)})` : `rgba(239,68,68,${a.toFixed(2)})`
}

export function SeasonalityView({ symbol }: { symbol: string }) {
  const [d, setD] = useState<SeasonalityData | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    setD(null); setErr(null)
    getSeasonality(symbol).then(r => { if (live) setD(r.data) })
      .catch(e => { if (live) setErr(apiError(e, 'seasonality unavailable')) })
    return () => { live = false }
  }, [symbol])
  if (err) return <ErrorBox error={err} />
  if (!d) return <Loading label="seasonality" />
  if (!d.months.length || d.years < 2) return <div style={{ color: T.dim, fontSize: 12, padding: 12 }}>Not enough history for {symbol}.</div>
  const thisMonth = d.current?.month ?? new Date().toLocaleDateString('en-US', { month: 'short' })
  const maxAbs = Math.max(1, ...d.months.map(m => Math.abs(m.avg ?? 0)))
  const W = 1200, H = 150, mid = H / 2, bw = W / 12
  const best = [...d.months].filter(m => m.avg != null).sort((a, b) => b.avg! - a.avg!)
  return (
    <div style={{ fontFamily: T.mono }}>
      <div style={{ fontSize: 11.5, color: T.muted, marginBottom: 6 }}>
        <span style={{ color: T.amber }}>{d.symbol}</span> · {d.years} years of monthly returns ({d.from?.slice(0, 7)} → {d.to?.slice(0, 7)})
        {d.current && <> · <span style={{ color: T.text }}>{d.current.month} {d.current.year} so far</span>{' '}
          <span style={{ color: d.current.ret >= 0 ? T.green : T.red }}>{fmtPct(d.current.ret, 1)}</span>
          <span style={{ color: T.dim }}> (to {d.current.asof})</span></>}
        {best.length >= 2 && <> · best month on average <span style={{ color: T.green }}>{best[0].month}</span>, worst <span style={{ color: T.red }}>{best[best.length - 1].month}</span></>}
      </div>
      <svg viewBox={`0 0 ${W} ${H + 34}`} style={{ width: '100%', height: 190, display: 'block' }}>
        <line x1={0} x2={W} y1={mid} y2={mid} stroke={T.border} />
        {d.months.map((m, i) => {
          const v = m.avg ?? 0, h = (Math.abs(v) / maxAbs) * (mid - 14)
          const x = i * bw + bw * 0.18, w = bw * 0.64, now = m.month === thisMonth
          return <g key={m.month}>
            <title>{`${m.month}: average ${fmtPct(m.avg, 2)}, median ${fmtPct(m.median, 2)}, up ${m.pct_up}% of ${m.n} years, best ${fmtPct(m.best, 1)}, worst ${fmtPct(m.worst, 1)}`}</title>
            <rect x={x} width={w} y={v >= 0 ? mid - h : mid} height={Math.max(1, h)} fill={v >= 0 ? T.green : T.red} opacity={now ? 1 : 0.7}
              stroke={now ? T.amber : 'none'} strokeWidth={now ? 2 : 0} />
            <text x={x + w / 2} y={v >= 0 ? mid - h - 4 : mid + h + 12} textAnchor="middle" fontSize={11} fill={T.text}>{fmtPct(m.avg, 1)}</text>
            <text x={x + w / 2} y={H + 14} textAnchor="middle" fontSize={12} fill={now ? T.amber : T.muted} fontWeight={now ? 700 : 400}>{m.month}</text>
            <text x={x + w / 2} y={H + 29} textAnchor="middle" fontSize={10.5} fill={(m.pct_up ?? 0) >= 65 ? T.green : (m.pct_up ?? 100) <= 35 ? T.red : T.dim}>{m.pct_up}% up</text>
          </g>
        })}
      </svg>
      <div style={{ overflowX: 'auto', marginTop: 8 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
          <thead><tr style={{ color: T.muted, fontSize: 10, letterSpacing: 0.8 }}>
            <th style={{ textAlign: 'left', padding: '4px 6px' }}>YEAR</th>
            {d.months.map(m => <th key={m.month} style={{ padding: '4px 4px', textAlign: 'right', color: m.month === thisMonth ? T.amber : T.muted }}>{m.month.toUpperCase()}</th>)}
            <th style={{ padding: '4px 6px', textAlign: 'right' }}>YEAR</th>
          </tr></thead>
          <tbody>
            {d.grid.map(r => <tr key={r.year} style={{ borderTop: `1px solid ${T.border}` }}>
              <td style={{ padding: '3px 6px', color: T.text }}>{r.year}</td>
              {d.months.map(m => {
                const cur = d.current && r.year === d.current.year && m.month === d.current.month
                const v = cur ? d.current!.ret : r.months[m.month]
                return <td key={m.month} title={cur ? 'so far this month' : undefined}
                  style={{ padding: '3px 4px', textAlign: 'right', background: heat(v), color: v == null ? T.dim : T.text,
                           outline: cur ? `1px dashed ${T.amber}` : undefined, outlineOffset: -2 }}>{v == null ? '' : fmtFixed(v, 1)}</td>
              })}
              <td title={d.current && r.year === d.current.year ? `year to date (to ${d.current.asof})` : 'calendar-year return'}
                style={{ padding: '3px 6px', textAlign: 'right', fontWeight: 600, color: (r.year_ret ?? 0) >= 0 ? T.green : T.red, whiteSpace: 'nowrap' }}>
                {r.year_ret == null ? '' : fmtPct(r.year_ret, 1)}{d.current && r.year === d.current.year && <span style={{ color: T.dim, fontSize: 9, fontWeight: 400 }}> YTD</span>}</td>
            </tr>)}
            <tr style={{ borderTop: `2px solid ${T.border}`, color: T.muted }}>
              <td style={{ padding: '4px 6px' }}>AVG</td>
              {d.months.map(m => <td key={m.month} style={{ padding: '4px 4px', textAlign: 'right', color: (m.avg ?? 0) >= 0 ? T.green : T.red }}>{m.avg == null ? '' : fmtFixed(m.avg, 1)}</td>)}
              <td />
            </tr>
          </tbody>
        </table>
      </div>
      <div style={{ fontSize: 10, color: T.dim, marginTop: 6, lineHeight: 1.5 }}>
        Close-to-close on the last session of each month ({d.kind === 'index' ? 'NSE index closes' : 'split- and bonus-adjusted NSE closes, dividends excluded'}).
        The current month (dashed) is not in the averages. Each month is only {d.years - 1}–{d.years} observations: a
        description of the past, not a forecast. Hover a bar for its median, best and worst year.
      </div>
    </div>
  )
}

/** The SEAG page: pick an index or type a ticker. */
export function SeasonalityPage() {
  const [sym, setSym] = useState('NIFTY 50')
  const [txt, setTxt] = useState('')
  const go = () => { const t = txt.trim().toUpperCase().replace(/\.NS$/, ''); if (t) { setSym(t); setTxt('') } }
  return (
    <div>
      <PageHeader code="SEAG" title="Seasonality" subtitle="average return by calendar month, how often each month was up, and every year behind it" />
      <Panel source={undatedSource('NSE closes', 'monthly returns; the window is printed in the panel')} badge="context" title={sym} accent={T.amber}
        right={<div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          {INDICES.map(i => <Chip key={i} color={T.amber} active={sym === i} onClick={() => setSym(i)}>{i.replace('NIFTY ', '')}</Chip>)}
          <span onKeyDown={e => { if (e.key === 'Enter') go() }}><Input value={txt} onChange={setTxt} placeholder="any ticker…" width={110} /></span>
          <Btn size="sm" onClick={go}>GO</Btn>
        </div>}>
        <SeasonalityView symbol={sym} />
      </Panel>
    </div>
  )
}

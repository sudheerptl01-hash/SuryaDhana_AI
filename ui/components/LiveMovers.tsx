'use client'

import { apiError } from '@/lib/errors'
/**
 * MOV — live movers during the NSE session: gainers and losers in the chosen universe, most active by value,
 * volume surges vs the 1-week average, live 52-week highs and lows, F&O open-interest spurts, and a sector board
 * with each index's advance / decline split. NSE live analysis (≈1 min delayed), refreshed every 30 s while the
 * market is open. MKT has the end-of-day picture.
 */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { getIndexMembers, getLiveMovers, getMarketMonitor, type LiveIndex, type LiveMover, type LiveMovers as Data } from '@/lib/api'
import { MarketMap, type MapRow } from '@/components/MarketMap'
import { Chip, ErrorBox, Loading, PageHeader, Panel, Stat, T, TickerLink, fmtPct, fmtPx, fmtSigned } from '@/components/terminal'
import { IndexIntraday } from '@/components/IndexIntraday'
import { sessionWord } from '@/lib/format'
import { moversPollDue } from '@/components/pageModels'
import { nseSession } from '@/components/desktop/session'
import { MarketInternals } from '@/components/MarketInternals'
import { IndexContribution } from '@/components/IndexContribution'

const UNIVERSES: [string, string][] = [['NIFTY', 'NIFTY 50'], ['BANKNIFTY', 'BANK NIFTY'], ['NIFTYNEXT50', 'NEXT 50'], ['FOSec', 'F&O'], ['SecGtr20', '> ₹20'], ['allSec', 'ALL']]
const tone = (v: number | null | undefined) => (v == null || Math.abs(v) < 0.005 ? T.muted : v > 0 ? T.green : T.red)
const cr = (v: number | null | undefined) => (v == null ? '—' : v >= 100 ? `₹${v.toFixed(0)} cr` : `₹${v.toFixed(1)} cr`)
const px = (v: number | null | undefined) => fmtPx(v)   // exchange decimals: always 2 dp (C1-08)

function Mini<R extends { symbol: string }>({ title, accent, rows, cols, note }: {
  title: string; accent: string; rows: R[]; note?: ReactNode
  cols: { label: string; render: (r: R) => ReactNode; align?: 'right' }[]
}) {
  return (
    <Panel title={title} accent={accent} pad={0} subtitle={note}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: T.mono, fontSize: 11.5, fontVariantNumeric: 'tabular-nums' }}>
        <thead>
          <tr>{[{ label: '', align: undefined }, ...cols].map((c, i) => (
            <th key={i} style={{ padding: '4px 8px', textAlign: c.align ?? 'left', color: T.dim, fontWeight: 400, fontSize: 9.5, letterSpacing: 0.5, borderBottom: `1px solid ${T.border}` }}>{i === 0 ? 'STOCK' : c.label.toUpperCase()}</th>))}</tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.symbol} style={{ borderBottom: `1px solid ${T.border}` }}>
              <td style={{ padding: '4px 8px' }}><TickerLink symbol={r.symbol} /></td>
              {cols.map((c, i) => <td key={i} style={{ padding: '4px 8px', textAlign: c.align ?? 'left', whiteSpace: 'nowrap' }}>{c.render(r)}</td>)}
            </tr>))}
          {!rows.length && <tr><td colSpan={cols.length + 1} style={{ padding: 10, color: T.dim }}>—</td></tr>}
        </tbody>
      </table>
    </Panel>
  )
}

function SectorTile({ x, active, onClick }: { x: LiveIndex; active?: boolean; onClick?: () => void }) {
  const n = (x.advances ?? 0) + (x.declines ?? 0)
  const up = n ? ((x.advances ?? 0) / n) * 100 : 50
  const c = x.change_pct ?? 0
  const bg = c >= 0 ? `rgba(22,217,138,${Math.min(0.08 + Math.abs(c) / 4, 0.45)})` : `rgba(255,77,94,${Math.min(0.08 + Math.abs(c) / 4, 0.45)})`
  return (
    <div title={`${x.index}: ${fmtPct(x.change_pct)} · ${x.advances ?? '—'} up / ${x.declines ?? '—'} down · 30d ${fmtPct(x.pct_30d, 1)} · 1y ${fmtPct(x.pct_365d, 1)} · click for members`}
         onClick={onClick} role="button"
         style={{ background: bg, border: `1px solid ${active ? T.amber : T.border}`, padding: '6px 8px', minWidth: 0, cursor: 'pointer' }}>
      <div style={{ fontSize: 10, color: T.text, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{x.index.replace(/^NIFTY /, '')}</div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginTop: 2 }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: T.bright }}>{fmtPct(x.change_pct)}</span>
        <span style={{ fontSize: 9.5, color: T.muted }}>{x.advances ?? '—'}/{x.declines ?? '—'}</span>
      </div>
      <div style={{ height: 3, background: T.red, marginTop: 4 }}><div style={{ height: 3, width: `${up}%`, background: T.green }} /></div>
    </div>
  )
}

export function LiveMovers() {
  const [universe, setUniverse] = useState('FOSec')
  const [data, setData] = useState<Data | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [group, setGroup] = useState<'SECTORAL INDICES' | 'THEMATIC INDICES' | 'BROAD MARKET INDICES'>('SECTORAL INDICES')
  const [mapRows, setMapRows] = useState<MapRow[] | null>(null)
  const [drill, setDrill] = useState<string | null>(null)
  const [members, setMembers] = useState<Awaited<ReturnType<typeof getIndexMembers>>['data'] | null>(null)
  useEffect(() => {
    if (!drill) { setMembers(null); return }
    let alive = true
    const get = () => getIndexMembers(drill, group).then(r => alive && setMembers(r.data)).catch(() => alive && setMembers(null))
    get(); const iv = setInterval(get, 60_000)
    return () => { alive = false; clearInterval(iv) }
  }, [drill, group])
  useEffect(() => { getMarketMonitor().then(r => setMapRows((r.data as { map?: MapRow[] }).map ?? null)).catch(() => {}) }, [])

  const load = useCallback(() => {
    getLiveMovers(universe).then(r => { setData(r.data); setError(null) }).catch(e => setError(apiError(e, 'unavailable')))
  }, [universe])
  useEffect(() => { setData(null); load() }, [load])
  // P5: also poll while the client's NSE clock says OPEN: a 'closed' reply before 09:15 used to stop the refresh for good
  useEffect(() => {
    const iv = setInterval(() => { if (moversPollDue(data?.market_open, nseSession(Date.now()).state === 'OPEN')) load() }, 30_000)
    return () => clearInterval(iv)
  }, [load, data?.market_open])

  const idx = useMemo(() => {
    const all = data?.indices ?? []
    const find = (name: string) => all.find(i => i.index === name)
    return { n50: find('NIFTY 50'), n500: find('NIFTY 500'), mid: find('NIFTY MIDCAP 100'), small: find('NIFTY SMALLCAP 100'),
             tiles: all.filter(i => i.group === group).sort((a, b) => (b.change_pct ?? 0) - (a.change_pct ?? 0)) }
  }, [data, group])

  const chg = (r: LiveMover) => <span style={{ color: tone(r.change_pct), fontWeight: 600 }}>{fmtPct(r.change_pct)}</span>
  const last = (r: LiveMover) => <span style={{ color: T.text }}>{px(r.ltp)}</span>
  const when = sessionWord(data?.market_open, data?.timestamp)
  const breadth = (i?: LiveIndex) => i ? <span><span style={{ color: T.green }}>{i.advances}</span> / <span style={{ color: T.red }}>{i.declines}</span></span> : '—'

  return (
    <div>
      <PageHeader code="MOV" title="Live Movers"
        subtitle={`NSE live market analysis, ≈1 min delayed · ${data?.timestamp ?? 'loading'}${data && !data.market_open ? ' · market closed: last session' : ' · every 30 s'}`}
        right={<div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          {data?.market_open && <span style={{ fontSize: 10, color: T.green, marginRight: 6, letterSpacing: 0.5 }}>● LIVE</span>}
          {UNIVERSES.map(([k, l]) => <Chip key={k} color={T.amber} active={universe === k} onClick={() => setUniverse(k)}>{l}</Chip>)}
        </div>} />
      {error && <ErrorBox error={error} />}
      {!data && !error && <Loading label="Reading NSE live market data" />}
      {data && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 10, marginBottom: 12 }}>
            <Stat label="NIFTY 50" value={px(idx.n50?.last)} sub={<span><span style={{ color: tone(idx.n50?.change_pct) }}>{fmtPct(idx.n50?.change_pct)}</span> · {breadth(idx.n50)}</span>} />
            <Stat label="NIFTY 500 breadth" value={breadth(idx.n500)} sub={<span style={{ color: tone(idx.n500?.change_pct) }}>{fmtPct(idx.n500?.change_pct)}</span>} />
            <Stat label="Midcap 100 / Smallcap 100" value={<span><span style={{ color: tone(idx.mid?.change_pct) }}>{fmtPct(idx.mid?.change_pct, 1)}</span> / <span style={{ color: tone(idx.small?.change_pct) }}>{fmtPct(idx.small?.change_pct, 1)}</span></span>} />
            <Stat label="52-week highs / lows" value={<span><span style={{ color: T.green }}>{data.highs.count}</span> / <span style={{ color: T.red }}>{data.lows.count}</span></span>} sub={`new ${when === 'today' ? 'today' : `in the ${when}`}, all NSE`} />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))', gap: 12, marginBottom: 12 }}>
            <Panel title="Intraday" subtitle={`${when} vs previous close · pick an index`} accent={T.green}><IndexIntraday height={190} /></Panel>
            <Panel title="Intraday" subtitle={`${when} vs previous close · pick an index`} accent={T.green}><IndexIntraday height={190} initial="NIFTY BANK" /></Panel>
          </div>
          <Panel title="Who moved the index" subtitle={`each stock's contribution ${when === 'today' ? 'today' : `in the ${when}`}, in index points`} accent={T.green}
            style={{ marginBottom: 12 }}><IndexContribution /></Panel>
          <Panel title="Market internals" subtitle="is the move broad or a few heavyweights? breadth through the day vs the size segments" accent={T.amber}
            style={{ marginBottom: 12 }}><MarketInternals height={200} /></Panel>

          <Panel title="Sector board" accent={T.violet} subtitle="index move · bar = share of members up · hover for 30-day and 1-year"
            right={<div style={{ display: 'flex', gap: 4 }}>{(['SECTORAL INDICES', 'THEMATIC INDICES', 'BROAD MARKET INDICES'] as const).map(g =>
              <Chip key={g} color={T.violet} active={group === g} onClick={() => { setGroup(g); setDrill(null) }}>{g.split(' ')[0]}</Chip>)}</div>}
            style={{ marginBottom: 12 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 6 }}>
              {idx.tiles.map(x => <SectorTile key={x.index} x={x} active={drill === x.index} onClick={() => setDrill(d => (d === x.index ? null : x.index))} />)}
            </div>
            {drill && (
              <div style={{ marginTop: 10, borderTop: `1px solid ${T.border}`, paddingTop: 8 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10.5, color: T.muted, marginBottom: 6 }}>
                  <span><b style={{ color: T.amber }}>{drill}</b> · members, live{members?.capped ? ' · NSE lists the first 50' : ''} · best to worst</span>
                  <span role="button" style={{ color: T.dim, cursor: 'pointer' }} onClick={() => setDrill(null)}>✕ close</span>
                </div>
                {!members ? <div style={{ fontSize: 11, color: T.dim }}>Reading members…</div> : (
                  <div className="t-nums" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 4 }}>
                    {members.members.map(m => (
                      <div key={m.symbol} style={{ display: 'flex', justifyContent: 'space-between', gap: 6, padding: '3px 6px', border: `1px solid ${T.border}`, fontSize: 11 }}>
                        <TickerLink symbol={m.symbol} />
                        <span style={{ color: tone(m.change_pct), fontFamily: T.mono }}>{fmtPct(m.change_pct)}</span>
                      </div>))}
                  </div>
                )}
              </div>
            )}
          </Panel>

          {mapRows && mapRows.length > 0 && <div style={{ marginBottom: 12 }}><MarketMap rows={mapRows} /></div>}

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(380px, 1fr))', gap: 12, alignItems: 'start' }}>
            <Mini title={`Gainers · ${UNIVERSES.find(u => u[0] === universe)?.[1]}`} accent={T.green} rows={data.gainers}
              cols={[{ label: 'Last', render: last, align: 'right' }, { label: 'Chg', render: chg, align: 'right' }, { label: 'Value', render: r => <span style={{ color: T.muted }}>{cr(r.value_cr)}</span>, align: 'right' }]} />
            <Mini title={`Losers · ${UNIVERSES.find(u => u[0] === universe)?.[1]}`} accent={T.red} rows={data.losers}
              cols={[{ label: 'Last', render: last, align: 'right' }, { label: 'Chg', render: chg, align: 'right' }, { label: 'Value', render: r => <span style={{ color: T.muted }}>{cr(r.value_cr)}</span>, align: 'right' }]} />
            <Mini title="Most active · by value" accent={T.amber} rows={data.most_active} note="all NSE"
              cols={[{ label: 'Last', render: last, align: 'right' }, { label: 'Chg', render: chg, align: 'right' }, { label: 'Value', render: r => <span style={{ color: T.text }}>{cr(r.value_cr)}</span>, align: 'right' }]} />
            <Mini title="Volume surge" accent={T.cyan} rows={data.volume_surge.filter(r => (r.value_cr ?? 0) >= 1).slice(0, 20)} note={`${when === 'today' ? "today's" : `the ${when}'s`} volume ÷ the 1-week average · all NSE · ≥ ₹1 cr traded`}
              cols={[{ label: '× week', render: r => <span style={{ color: (r.vs_week ?? 0) >= 10 ? T.amber : T.text, fontWeight: 600 }}>{r.vs_week != null ? `${r.vs_week.toFixed(1)}×` : '—'}</span>, align: 'right' },
                     { label: 'Chg', render: chg, align: 'right' }, { label: 'Value', render: r => <span style={{ color: T.muted }}>{cr(r.value_cr)}</span>, align: 'right' }]} />
            <Mini title={`New 52-week highs · ${data.highs.count}`} accent={T.green} rows={data.highs.rows} note="newest first, all NSE"
              cols={[{ label: 'Last', render: last, align: 'right' }, { label: 'Chg', render: chg, align: 'right' }, { label: 'Old high', render: r => <span style={{ color: T.dim }}>{px(r.prev_level)} <span style={{ fontSize: 9.5 }}>{r.prev_date?.slice(0, 6)}</span></span>, align: 'right' }]} />
            <Mini title={`New 52-week lows · ${data.lows.count}`} accent={T.red} rows={data.lows.rows} note="newest first, all NSE"
              cols={[{ label: 'Last', render: last, align: 'right' }, { label: 'Chg', render: chg, align: 'right' }, { label: 'Old low', render: r => <span style={{ color: T.dim }}>{px(r.prev_level)} <span style={{ fontSize: 9.5 }}>{r.prev_date?.slice(0, 6)}</span></span>, align: 'right' }]} />
            <Mini title="F&O open-interest spurts" accent={T.violet} rows={data.oi_spurts} note="futures + options OI vs yesterday · rising OI with a falling price often means fresh shorts"
              cols={[{ label: 'OI chg', render: r => <span style={{ color: tone(r.oi_change_pct), fontWeight: 600 }}>{fmtPct(r.oi_change_pct, 1)}</span>, align: 'right' },
                     { label: 'Contracts', render: r => <span style={{ color: T.muted }}>{fmtSigned(r.oi_change == null ? null : Math.round(r.oi_change), 0)}</span>, align: 'right' },
                     { label: 'Price', render: r => <span style={{ color: T.text }}>{px(r.underlying)}</span>, align: 'right' }]} />
          </div>
          {Object.keys(data.errors).length > 0 && (
            <div style={{ fontSize: 10, color: T.amber, marginTop: 8 }}>Some NSE feeds did not answer: {Object.keys(data.errors).join(', ')} (kept the rest).</div>
          )}
        </>
      )}
    </div>
  )
}

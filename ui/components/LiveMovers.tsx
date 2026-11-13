'use client'

import { apiError } from '@/lib/errors'
/**
 * MOV — live movers during the NSE session: gainers and losers in the chosen universe, most active by value,
 * volume surges vs the 1-week average, live 52-week highs and lows, F&O open-interest spurts, and a sector board
 * with each index's advance / decline split. NSE live analysis (≈1 min delayed), refreshed every 30 s while the
 * market is open. MKT has the end-of-day picture.
 *
 * Live program (reports/live_nse): NSE's website is never LIVE (49–172 s behind, L-CAPACITY), so its panels read
 * DELAYED · NSE · <age> (or CLOSE · <day>); each panel carries its OWN chip (the intraday charts, who moved the index
 * and the internals report theirs through `onSource`), and the NIFTY 50 tile, the who-moved points, the intraday tips
 * and the sector drill-down members come from the live NSE quote service (Breeze websocket) when it answers.
 */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { getIndexMembers, getLiveMovers, getLiveQuotes, getMarketMonitor, type LiveIndex, type LiveMover, type LiveMovers as Data, type MarketMonitor as Monitor } from '@/lib/api'
import { fillValue, nseDateIso, shortDateWithYear, sortHighLow, splitNoHistory, volumeSurge } from '@/components/marketPagesModel'
import { MarketMap, type MapRow } from '@/components/MarketMap'
import { Chip, ErrorBox, Loading, PageHeader, Panel, Stat, T, TickerLink, fmtPct, fmtPx, fmtSigned, sourceOf, type SourceInfo } from '@/components/terminal'
import { goToPage } from '@/lib/navigate'
import { IndexIntraday } from '@/components/IndexIntraday'
import { sessionWord } from '@/lib/format'
import { moversPollDue } from '@/components/pageModels'
import { nseSession } from '@/components/desktop/session'
import { MarketInternals } from '@/components/MarketInternals'
import { IndexContribution } from '@/components/IndexContribution'
import { SourceChip } from '@/components/terminal'
import { useLiveQuotes } from '@/lib/liveQuotes'
import { liveLevel, nseDelayedSource } from '@/components/liveModel'

const UNIVERSES: [string, string][] = [['NIFTY', 'NIFTY 50'], ['BANKNIFTY', 'BANK NIFTY'], ['NIFTYNEXT50', 'NEXT 50'], ['FOSec', 'F&O'], ['SecGtr20', '> ₹20'], ['allSec', 'ALL']]
const tone = (v: number | null | undefined) => (v == null || Math.abs(v) < 0.005 ? T.muted : v > 0 ? T.green : T.red)
const cr = (v: number | null | undefined) => (v == null ? '—' : v >= 100 ? `₹${v.toFixed(0)} cr` : `₹${v.toFixed(1)} cr`)
const px = (v: number | null | undefined) => fmtPx(v)   // exchange decimals: always 2 dp (C1-08)

function Mini<R extends { symbol: string }>({ title, accent, rows, cols, note, source }: {
  title: string; accent: string; rows: R[]; note?: ReactNode; source: SourceInfo
  cols: { label: string; render: (r: R) => ReactNode; align?: 'right' }[]
}) {
  return (
    <Panel title={title} accent={accent} pad={0} source={source}>
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
      {/* m020: the panel's note sits under its table (in the header it wrapped one word per line beside the chip) */}
      {note && <div style={{ padding: '5px 8px', fontSize: 10, color: T.dim, borderTop: `1px solid ${T.border}`, lineHeight: 1.45 }}>{note}</div>}
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
      {/* L-15: the advancers-share bar is breadth context — neutral fill over the border track, not green on red */}
      <div style={{ height: 3, background: T.border, marginTop: 4 }}><div style={{ height: 3, width: `${up}%`, background: T.muted }} /></div>
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
  // MKT's end-of-day picture: the map, and after the close the volume shockers and the day's turnover (M27, m017)
  const [eod, setEod] = useState<Monitor | null>(null)
  useEffect(() => { getMarketMonitor().then(r => { setEod(r.data); setMapRows((r.data as { map?: MapRow[] }).map ?? null) }).catch(() => {}) }, [])

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

  // m017: after the close NSE's live lists drop the traded value; fill it from MKT's EOD turnover and the live-quotes
  // map (NSE heatmap, which keeps the session's value), never left as "—" on every row
  const closed = !!data && !data.market_open
  const [quoteValues, setQuoteValues] = useState<Record<string, number | null>>({})
  useEffect(() => {
    if (!closed) return
    let live = true
    getLiveQuotes().then(r => { if (live) setQuoteValues(Object.fromEntries(Object.entries(r.data.quotes).map(([k, q]) => [k, q.value_cr]))) }).catch(() => {})
    return () => { live = false }
  }, [closed])
  const eodValue = useMemo(() => {
    const m = new Map<string, number>()
    for (const list of Object.values(eod?.movers ?? {})) for (const r of (list as { symbol: string; turnover_cr: number | null }[])) if (r.turnover_cr != null) m.set(r.symbol, r.turnover_cr)
    return m
  }, [eod])
  const sessionIso = nseDateIso(data?.timestamp)
  const eodSame = !!eod?.as_of && (!sessionIso || eod.as_of === sessionIso)
  const valueOf = useCallback((sym: string) => (eodSame ? eodValue.get(sym) : undefined) ?? quoteValues[sym] ?? undefined, [eodSame, eodValue, quoteValues])
  const withValue = useCallback(<R extends { symbol: string; value_cr?: number | null }>(rows: R[]) => fillValue(rows, [valueOf]), [valueOf])
  // M27: the 52-week lists by date, then by ₹ traded (not NSE's alphabetical order); a row with no previous level
  // (a new listing, in BOTH lists with "old high 0.00") leaves them and is named once (m018)
  const hl = useMemo(() => {
    const split = splitNoHistory(data?.highs.rows ?? [], data?.lows.rows ?? [])
    return { highs: sortHighLow(withValue(split.highs), valueOf), lows: sortHighLow(withValue(split.lows), valueOf), noHistory: split.noHistory }
  }, [data, withValue, valueOf])
  const surge = useMemo(() => volumeSurge(data?.volume_surge ?? [], !!data?.market_open,
    (eod?.movers as { volume_shockers?: { symbol: string; close: number | null; chg_pct: number | null; turnover_cr: number | null; vol_x: number | null }[] } | undefined)?.volume_shockers ?? null,
    eod?.as_of ?? null, sessionIso), [data, eod, sessionIso])
  const chg = (r: LiveMover) => <span style={{ color: tone(r.change_pct), fontWeight: 600 }}>{fmtPct(r.change_pct)}</span>
  const last = (r: LiveMover) => <span style={{ color: T.text }}>{px(r.ltp)}</span>
  const when = sessionWord(data?.market_open, data?.timestamp)
  // PLAN §0.5: every panel names its feed and as-of. NSE's live analysis is ≈ 1 min behind: DELAYED · NSE · <age>,
  // never LIVE (the old chip said LIVE · NSE while the market was open); CLOSE · <day> once the session is over.
  const feedSource = data ? nseDelayedSource(data.timestamp, { marketOpen: !!data.market_open, now: Date.now(), hint: 'NSE live analysis, 30 s cache' })
    : sourceOf(null, { source: 'NSE' })
  const sectorSource = data ? nseDelayedSource(data.timestamp, { marketOpen: !!data.market_open, now: Date.now(), hint: 'sector rows from NSE allIndices, typically 1–3 min behind' }) : feedSource
  // each panel's own chip, reported by the panel itself (null until it has data: the shared feed chip meanwhile)
  const [srcN50, setSrcN50] = useState<SourceInfo | null>(null)
  const [srcBank, setSrcBank] = useState<SourceInfo | null>(null)
  const [srcContrib, setSrcContrib] = useState<SourceInfo | null>(null)
  const [srcInternals, setSrcInternals] = useState<SourceInfo | null>(null)
  // the NIFTY 50 tile and the drill-down members: live NSE quotes when the service answers
  const liveIdx = useLiveQuotes(['NIFTY 50'], { intervalMs: 3_000 })
  const n50 = liveLevel(idx.n50 ?? null, liveIdx.quotes['NIFTY 50'])
  const liveMembers = useLiveQuotes(members?.members.map(m => m.symbol) ?? [], { intervalMs: 3_000, enabled: !!drill })
  // L-15: A/D figures are context — neutral, never green/red
  const breadth = (i?: LiveIndex) => i ? <span style={{ color: T.text }}>{i.advances} / {i.declines}</span> : '—'

  return (
    <div>
      <PageHeader code="MOV" title="Live Movers"
        subtitle={`NSE live market analysis, ≈1 min delayed · ${data?.timestamp ?? 'loading'}${data && !data.market_open ? ' · market closed: last session' : ' · every 30 s'}`}
        right={<div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          {data?.market_open && <span title="NSE is in session; the lists below are NSE's live analysis, about 1 min behind" style={{ fontSize: 10, color: T.green, marginRight: 6, letterSpacing: 0.5 }}>● NSE OPEN</span>}
          {UNIVERSES.map(([k, l]) => <Chip key={k} color={T.amber} active={universe === k} onClick={() => setUniverse(k)}>{l}</Chip>)}
        </div>} />
      {error && <ErrorBox error={error} />}
      {!data && !error && <Loading label="Reading NSE live market data" />}
      {data && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 10, marginBottom: 12 }}>
            <Stat label="NIFTY 50" value={px(n50.last)} sub={<span><span style={{ color: tone(n50.change_pct) }}>{fmtPct(n50.change_pct)}</span> · {breadth(idx.n50)}
              {' '}<SourceChip info={n50.fromService && liveIdx.source ? liveIdx.source : sectorSource} style={{ marginLeft: 4 }} /></span>} />
            {/* m019: name the universe and the clock (MKT's breadth is a different, 1,394-stock liquid universe at the close) */}
            <Stat label="NIFTY 500 breadth" value={breadth(idx.n500)} sub={<span><span style={{ color: tone(idx.n500?.change_pct) }}>{fmtPct(idx.n500?.change_pct)}</span>
              <span style={{ color: T.dim }}> · the index&apos;s members, NSE {data.timestamp?.slice(12, 17) ?? ''}{eod?.breadth?.universe ? ` · MKT counts ${Number(eod.breadth.universe).toLocaleString('en-IN')} liquid stocks` : ''}</span></span>} />
            <Stat label="Midcap 100 / Smallcap 100" value={<span><span style={{ color: tone(idx.mid?.change_pct) }}>{fmtPct(idx.mid?.change_pct, 1)}</span> / <span style={{ color: tone(idx.small?.change_pct) }}>{fmtPct(idx.small?.change_pct, 1)}</span></span>} />
            <Stat label="52-week highs / lows" value={<span><span style={{ color: T.green }}>{data.highs.count}</span> / <span style={{ color: T.red }}>{data.lows.count}</span></span>} sub={`new ${when === 'today' ? 'today' : `in the ${when}`}, all NSE`} />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))', gap: 12, marginBottom: 12 }}>
            {/* PLAN 0.6 (R-UI S9): two INTRADAY panels used to share one title; each names the index it opens on */}
            <Panel title="Intraday · NIFTY 50" subtitle={`${when} vs previous close · pick an index`} accent={T.green} source={srcN50 ?? feedSource} badge="arithmetic"><IndexIntraday height={190} onSource={setSrcN50} /></Panel>
            <Panel title="Intraday · NIFTY BANK" subtitle={`${when} vs previous close · pick an index`} accent={T.green} source={srcBank ?? feedSource} badge="arithmetic"><IndexIntraday height={190} initial="NIFTY BANK" onSource={setSrcBank} /></Panel>
          </div>
          <Panel title="Who moved the index" subtitle={`each stock's contribution ${when === 'today' ? 'today' : `in the ${when}`}, in index points`} accent={T.green}
            style={{ marginBottom: 12 }} source={srcContrib ?? feedSource} badge="arithmetic"><IndexContribution onSource={setSrcContrib} />
            {/* PLAN 1.2: MOV keeps the live today panel; every horizon (5d / 1m / YTD / since the last driver change) is on MEMB */}
            <div style={{ marginTop: 6, fontSize: 10.5, color: T.muted, display: 'flex', justifyContent: 'flex-end' }}>
              <span role="button" tabIndex={0} data-testid="mov-history-on-memb" onClick={() => goToPage('memb')}
                onKeyDown={e => { if (e.key === 'Enter') goToPage('memb') }}
                style={{ color: T.cyan, cursor: 'pointer', letterSpacing: 0.5 }}>history on MEMB ›</span>
            </div></Panel>
          <Panel title="Market internals" subtitle="is the move broad or a few heavyweights? breadth through the day vs the size segments" accent={T.amber}
            style={{ marginBottom: 12 }} source={srcInternals ?? feedSource} badge="context"><MarketInternals height={200} onSource={setSrcInternals} /></Panel>

          <Panel title="Sector board" accent={T.violet} subtitle="index move · bar = share of members up · hover for 30-day and 1-year" source={sectorSource}
            right={<div style={{ display: 'flex', gap: 4 }}>{(['SECTORAL INDICES', 'THEMATIC INDICES', 'BROAD MARKET INDICES'] as const).map(g =>
              <Chip key={g} color={T.violet} active={group === g} onClick={() => { setGroup(g); setDrill(null) }}>{g.split(' ')[0]}</Chip>)}</div>}
            style={{ marginBottom: 12 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 6 }}>
              {idx.tiles.map(x => <SectorTile key={x.index} x={x} active={drill === x.index} onClick={() => setDrill(d => (d === x.index ? null : x.index))} />)}
            </div>
            {drill && (
              <div style={{ marginTop: 10, borderTop: `1px solid ${T.border}`, paddingTop: 8 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10.5, color: T.muted, marginBottom: 6 }}>
                  <span><b style={{ color: T.amber }}>{drill}</b> · members{liveMembers.available && liveMembers.source ? <> <SourceChip info={liveMembers.source} /></> : ', NSE heatmap ≈ 1 min'}{members?.capped ? ' · NSE lists the first 50' : ''} · best to worst</span>
                  <span role="button" style={{ color: T.dim, cursor: 'pointer' }} onClick={() => setDrill(null)}>✕ close</span>
                </div>
                {!members ? <div style={{ fontSize: 11, color: T.dim }}>Reading members…</div> : (
                  <div className="t-nums" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 4 }}>
                    {members.members.map(m => ({ ...m, change_pct: liveLevel({ last: m.ltp, change_pct: m.change_pct }, liveMembers.quotes[m.symbol]).change_pct }))
                      .sort((a, b) => (b.change_pct ?? -999) - (a.change_pct ?? -999)).map(m => (
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
            <Mini source={feedSource} title={`Gainers · ${UNIVERSES.find(u => u[0] === universe)?.[1]}`} accent={T.green} rows={withValue(data.gainers)}
              cols={[{ label: 'Last', render: last, align: 'right' }, { label: 'Chg', render: chg, align: 'right' }, { label: 'Value', render: r => <span style={{ color: T.muted }}>{cr(r.value_cr)}</span>, align: 'right' }]} />
            <Mini source={feedSource} title={`Losers · ${UNIVERSES.find(u => u[0] === universe)?.[1]}`} accent={T.red} rows={withValue(data.losers)}
              cols={[{ label: 'Last', render: last, align: 'right' }, { label: 'Chg', render: chg, align: 'right' }, { label: 'Value', render: r => <span style={{ color: T.muted }}>{cr(r.value_cr)}</span>, align: 'right' }]} />
            <Mini source={feedSource} title="Most active · by value" accent={T.amber} rows={withValue(data.most_active)} note={closed ? 'all NSE · value: the session total (MKT EOD / NSE heatmap)' : 'all NSE'}
              cols={[{ label: 'Last', render: last, align: 'right' }, { label: 'Chg', render: chg, align: 'right' }, { label: 'Value', render: r => <span style={{ color: T.text }}>{cr(r.value_cr)}</span>, align: 'right' }]} />
            <Mini source={surge.basis === 'eod' ? sourceOf(eod?.as_of ?? null, { source: 'NSE EOD (MKT)' }) : feedSource} title="Volume surge" accent={T.cyan} rows={surge.rows} note={surge.note}
              cols={[{ label: '× week', render: r => <span style={{ color: (r.vs_week ?? 0) >= 10 ? T.amber : T.text, fontWeight: 600 }}>{r.vs_week != null ? `${r.vs_week.toFixed(1)}×` : '—'}</span>, align: 'right' },
                     { label: 'Chg', render: chg, align: 'right' }, { label: 'Value', render: r => <span style={{ color: T.muted }}>{cr(r.value_cr)}</span>, align: 'right' }]} />
            <Mini source={feedSource} title={`New 52-week highs · ${data.highs.count}`} accent={T.green} rows={hl.highs}
              note={`all NSE · newest date first, then by ₹ traded${data.highs.rows.length < data.highs.count ? ` · NSE's list carries ${data.highs.rows.length} of ${data.highs.count}` : ''}${hl.noHistory.length ? ` · no 52-week history yet (left out): ${hl.noHistory.join(', ')}` : ''}`}
              cols={[{ label: 'Last', render: last, align: 'right' }, { label: 'Chg', render: chg, align: 'right' },
                     { label: 'Old high', render: r => <span style={{ color: T.dim }}>{px(r.prev_level)} <span style={{ fontSize: 9.5 }}>{shortDateWithYear(r.prev_date)}</span></span>, align: 'right' }]} />
            <Mini source={feedSource} title={`New 52-week lows · ${data.lows.count}`} accent={T.red} rows={hl.lows}
              note={`all NSE · newest date first, then by ₹ traded${data.lows.rows.length < data.lows.count ? ` · NSE's list carries ${data.lows.rows.length} of ${data.lows.count}` : ''}`}
              cols={[{ label: 'Last', render: last, align: 'right' }, { label: 'Chg', render: chg, align: 'right' },
                     { label: 'Old low', render: r => <span style={{ color: T.dim }}>{px(r.prev_level)} <span style={{ fontSize: 9.5 }}>{shortDateWithYear(r.prev_date)}</span></span>, align: 'right' }]} />
            <Mini source={feedSource} title="F&O open-interest spurts" accent={T.violet} rows={data.oi_spurts} note="futures + options OI vs yesterday · context: the held-overnight study found no edge in OI build-ups (RSCH)"
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

'use client'

import { apiError } from '@/lib/errors'
/**
 * DEAL — block & bulk deals: every named-client bulk or block deal on NSE, netted per client per stock per day
 * (intraday round trips drop out), with the deal's share of the day's volume and the move since. Mutual funds,
 * insurers and pension funds are tagged: the held-overnight study (H3) found their buying harmless-to-good and
 * everyone else's bulk buying followed by lagging returns. Click a client to see all their deals.
 */
import { useEffect, useMemo, useState } from 'react'
import { getDeals, getShortSelling, type Deal, type ShortRow } from '@/lib/api'
import { daysUntil, useCorpEvents } from '@/lib/useCorpEvents'
import { Chip, DataTable, ErrorBox, EventBadge, Input, Loading, PageHeader, Panel, ResearchNote, Stat, T, TickerLink, type Column, fmtPct, fmtPx, sourceOf } from '@/components/terminal'

const cr = (v: number | null | undefined) => (v == null ? '—' : v >= 1e9 ? `₹${(v / 1e7).toFixed(0)} cr` : v >= 1e7 ? `₹${(v / 1e7).toFixed(1)} cr` : `₹${(v / 1e5).toFixed(1)} L`)
const pct = (v: number | null) => fmtPct(v, 1)
type Side = 'all' | 'buy' | 'sell' | 'inst'
/** GO `TCS DEAL` hands the symbol over through this key (and a suryadhana:deal event when the page is open). */
export { DEAL_KEY } from '@/lib/pageKeys'
import { DEAL_KEY } from '@/lib/pageKeys'

const readHandoff = (): string | null => { try { return localStorage.getItem(DEAL_KEY) } catch { return null } }

export function DealsMonitor() {
  // CT-01: 'TCS DEAL' from another page writes the hand-off key before this page mounts. Start on its window
  // (30 days, ≥ ₹10 L) so the first request is the right one, instead of a 10-day ≥ ₹1 cr request racing it.
  const [days, setDays] = useState(() => (readHandoff() ? 30 : 10))
  const [minValue, setMinValue] = useState(() => (readHandoff() ? 1e6 : 1e7))
  const [kind, setKind] = useState<'all' | 'bulk' | 'block'>('all')
  const [side, setSide] = useState<Side>('all')
  const [q, setQ] = useState(() => readHandoff() ?? '')
  const [data, setData] = useState<Awaited<ReturnType<typeof getDeals>>['data'] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const events = useCorpEvents()
  useEffect(() => {
    const take = () => {
      try {
        const sym = localStorage.getItem(DEAL_KEY)
        if (sym) { localStorage.removeItem(DEAL_KEY); setQ(sym); setDays(30); setMinValue(1e6); setSide('all') }
      } catch { /* storage blocked */ }
    }
    take()
    window.addEventListener('suryadhana:deal', take)
    return () => window.removeEventListener('suryadhana:deal', take)
  }, [])
  useEffect(() => {
    // latest window wins (CT-01): a slower answer for a window the user already left never replaces the current one
    let current = true
    setData(null); setError(null)
    getDeals(days, minValue, kind).then(r => { if (current) setData(r.data) }).catch(e => { if (current) setError(apiError(e, 'unavailable')) })
    return () => { current = false }
  }, [days, minValue, kind])

  const rows = useMemo(() => {
    const needle = q.trim().toUpperCase()
    return (data?.rows ?? []).filter(r =>
      (side === 'all' || (side === 'inst' ? r.institution : r.direction === side))
      && (!needle || r.symbol.includes(needle) || (r.client_name ?? '').toUpperCase().includes(needle)))
  }, [data, side, q])

  const s = data?.summary
  // most active clients in the window: gross value, net direction, how many stocks (the "who is trading" view)
  const clients = useMemo(() => {
    const m = new Map<string, { name: string; gross: number; net: number; stocks: Set<string>; inst: boolean }>()
    for (const r of data?.rows ?? []) {
      const k = r.client_name ?? '—'
      const c = m.get(k) ?? { name: k, gross: 0, net: 0, stocks: new Set<string>(), inst: r.institution }
      c.gross += r.value; c.net += r.direction === 'buy' ? r.value : -r.value; c.stocks.add(r.symbol)
      m.set(k, c)
    }
    return [...m.values()].sort((a, b) => b.gross - a.gross).slice(0, 12)
  }, [data])
  const cols: Column<Deal>[] = [
    { key: 'date', label: 'Date', sort: r => r.date, render: r => <span style={{ color: T.text }}>{r.date.slice(5)}</span> },
    { key: 'kind', label: 'Type', sort: r => r.kind, render: r => <span style={{ color: r.kind === 'block' ? T.violet : T.muted, fontSize: 10, letterSpacing: 0.5 }}>{r.kind.toUpperCase()}</span> },
    { key: 'symbol', label: 'Stock', sort: r => r.symbol, render: r => <TickerLink symbol={r.symbol} /> },
    { key: 'client', label: 'Client', sort: r => r.client_name ?? '', render: r => (
      <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center', maxWidth: 340 }}>
        {r.institution && <span title="mutual fund / insurer / pension fund" style={{ color: T.cyan, fontSize: 9, border: `1px solid ${T.cyan}`, padding: '0 3px' }}>MF/INS</span>}
        <span role="button" title={`all deals by ${r.client_name}`} onClick={e => { e.stopPropagation(); setQ(r.client_name ?? '') }}
              style={{ color: T.text, cursor: 'pointer', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.client_name ?? '—'}</span>
      </span>) },
    { key: 'side', label: 'Side', sort: r => r.direction, render: r => <span style={{ color: r.direction === 'buy' ? T.green : T.red, fontWeight: 600 }}>{r.direction.toUpperCase()}</span> },
    { key: 'qty', label: 'Qty', align: 'right', sort: r => r.qty, render: r => <span style={{ color: T.muted }}>{Math.round(r.qty).toLocaleString('en-IN')}</span> },
    { key: 'px', label: 'Avg ₹', align: 'right', sort: r => r.avg_price, render: r => <span style={{ color: T.muted }}>{fmtPx(r.avg_price)}</span> },
    { key: 'value', label: 'Value', align: 'right', sort: r => r.value, render: r => <span style={{ color: r.direction === 'buy' ? T.green : T.red, fontWeight: 600 }}>{cr(r.value)}</span> },
    { key: 'vol', label: '% of day vol', align: 'right', sort: r => r.pct_of_volume ?? -1,
      render: r => r.pct_of_volume == null ? <span style={{ color: T.dim }}>—</span> : <span style={{ color: r.pct_of_volume >= 25 ? T.amber : T.muted }}>{r.pct_of_volume.toFixed(1)}%</span> },
    { key: 'since', label: 'Since deal', align: 'right', sort: r => r.since_pct ?? -999,
      render: r => r.since_pct == null || r.date === r.last_date ? <span style={{ color: T.dim }}>—</span> : <span style={{ color: r.since_pct >= 0 ? T.green : T.red }}>{pct(r.since_pct)}</span> },
    { key: 'event', label: 'Next event', render: r => { const e = events.get(r.symbol)?.[0]; return e ? <EventBadge kind={e.kind} date={e.event_date} days={daysUntil(e.event_date)} typical={e.typical_move_pct} detail={e.detail} /> : <span style={{ color: T.dim }}>—</span> } },
  ]

  return (
    <div>
      <PageHeader code="DEAL" title="Block & Bulk Deals"
        subtitle={`named-client deals on NSE, netted per client per day · NSE bulk/block files${data?.data_through ? ` · data through ${data.data_through.slice(0, 10)}` : ''}`}
        right={<div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          {[1, 5, 10, 30].map(d => <Chip key={d} color={T.amber} active={days === d} onClick={() => setDays(d)}>{d}D</Chip>)}
          <span style={{ width: 8 }} />
          {[[1e6, '≥ ₹10 L'], [1e7, '≥ ₹1 cr'], [1e8, '≥ ₹10 cr']].map(([v, l]) => <Chip key={l} color={T.green} active={minValue === v} onClick={() => setMinValue(v as number)}>{l}</Chip>)}
          <span style={{ width: 8 }} />
          {(['all', 'bulk', 'block'] as const).map(k => <Chip key={k} color={T.violet} active={kind === k} onClick={() => setKind(k)}>{k.toUpperCase()}</Chip>)}
        </div>} />
      <ResearchNote verdict="REFERENCE" report="reports/held_overnight/FINDINGS.md">
        H3: stocks net-bought in a bulk deal by a client that is <b>not</b> a mutual fund or insurer lagged random picks by 2.2% / 1.2% over the
        next 20 sessions (2019–23 / 2024–26, borderline in the holdout). MF / insurer buying: +1.0% / +1.3%, promising, not proven.
        The Desk's avoid filter built on this is OFF pending your review.
      </ResearchNote>
      {error && <ErrorBox error={error} />}
      {!data && !error && <Loading label="Reading bulk and block deals" />}
      {data && s && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 10, marginBottom: 12 }}>
            <Stat label="Deals (netted)" value={s.deals.toLocaleString('en-IN')} sub={`last ${days} day${days > 1 ? 's' : ''} · ≥ ${cr(minValue)}`} />
            <Stat label="Bought" value={cr(s.buy_value)} color={T.green} />
            <Stat label="Sold" value={cr(s.sell_value)} color={T.red} />
            <Stat label="MF / insurer / pension" value={cr(s.institution_value)} color={T.cyan}
                  sub={s.buy_value + s.sell_value > 0 ? `${((s.institution_value / (s.buy_value + s.sell_value)) * 100).toFixed(0)}% of deal value` : undefined} />
          </div>
          {clients.length > 0 && (
            <Panel source={sourceOf(data?.data_through ?? null, { source: 'NSE deals' })} badge="context" title="Most active clients" accent={T.cyan} style={{ marginBottom: 12 }}
              subtitle={`by gross deal value over ${days} day${days > 1 ? 's' : ''} · click to see their deals`}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(330px, 1fr))', gap: '4px 18px', fontSize: 11.5 }}>
                {clients.map(c => (
                  <div key={c.name} role="button" onClick={() => setQ(c.name)}
                       style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 80px 60px', gap: 8, cursor: 'pointer', padding: '2px 0', borderBottom: `1px solid ${T.border}` }}>
                    <span style={{ color: T.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={c.name}>
                      {c.inst && <span style={{ color: T.cyan, fontSize: 9 }}>MF/INS </span>}{c.name}</span>
                    <span style={{ textAlign: 'right', color: c.net >= 0 ? T.green : T.red }}>{c.net >= 0 ? 'net buy' : 'net sell'}</span>
                    <span style={{ textAlign: 'right', color: T.muted }}>{cr(c.gross)}</span>
                  </div>))}
              </div>
            </Panel>
          )}
          {s.top_net.length > 0 && (
            <Panel source={sourceOf(data?.data_through ?? null, { source: 'NSE deals' })} badge="arithmetic" title="Biggest net flows" accent={T.amber} subtitle="buy value minus sell value per stock, all clients">
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 18px', fontSize: 12 }}>
                {s.top_net.map(t => (
                  <span key={t.symbol} style={{ display: 'inline-flex', gap: 6, alignItems: 'baseline' }}>
                    <TickerLink symbol={t.symbol} />
                    <span style={{ color: t.net_value >= 0 ? T.green : T.red }}>{t.net_value >= 0 ? '+' : '−'}{cr(Math.abs(t.net_value))}</span>
                  </span>))}
              </div>
            </Panel>
          )}
          <div style={{ height: 12 }} />
          <Panel source={sourceOf(data?.data_through ?? null, { source: 'NSE deals' })} title={`${rows.length.toLocaleString('en-IN')} deals${data.count > data.rows.length ? ` (newest ${data.rows.length.toLocaleString('en-IN')} of ${data.count.toLocaleString('en-IN')})` : ''}`} pad={0} accent={T.violet}
            subtitle="click a client to see all their deals · % of day vol ≥ 25% in amber"
            right={<div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
              {([['all', 'ALL'], ['buy', 'BUYS'], ['sell', 'SELLS'], ['inst', 'MF/INS']] as [Side, string][]).map(([k, l]) =>
                <Chip key={k} color={k === 'sell' ? T.red : k === 'inst' ? T.cyan : T.green} active={side === k} onClick={() => setSide(k)}>{l}</Chip>)}
              <Input value={q} onChange={setQ} placeholder="stock or client" width={180} />
              {q && <Chip color={T.muted} onClick={() => setQ('')}>✕</Chip>}
            </div>}>
            <DataTable columns={cols} rows={rows} rowKey={r => `${r.date}|${r.kind}|${r.symbol}|${r.client_name}`} dense maxHeight={700}
              initialSort={{ key: 'date', dir: 'desc' }} empty="No deals match" />
          </Panel>
          <div style={{ height: 12 }} />
          <ShortSelling />
        </>
      )}
    </div>
  )
}

/** Institutional short selling (NSE's daily disclosure, Bloomberg SI-style): who is being shorted, how persistently,
 *  and how big that is against all trading in the stock over the window. */
function ShortSelling() {
  const [days, setDays] = useState(20)
  const [d, setD] = useState<Awaited<ReturnType<typeof getShortSelling>>['data'] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    setD(null); setErr(null)
    getShortSelling(days).then(r => { if (live) setD(r.data) }).catch(e => { if (live) setErr(e?.message || 'short selling unavailable') })
    return () => { live = false }
  }, [days])
  const cols: Column<ShortRow>[] = [
    { key: 'sym', label: 'Stock', sort: r => r.symbol, render: r => <TickerLink symbol={r.symbol} /> },
    { key: 'pct', label: '% of volume', align: 'right', sort: r => r.short_pct_of_volume ?? -1, title: 'shares sold short ÷ all shares traded in the window',
      render: r => <span style={{ color: (r.short_pct_of_volume ?? 0) >= 2 ? T.red : (r.short_pct_of_volume ?? 0) >= 0.5 ? T.amber : T.muted, fontWeight: 600 }}>
        {r.short_pct_of_volume == null ? '—' : `${r.short_pct_of_volume.toFixed(2)}%`}</span> },
    { key: 'qty', label: 'Shares shorted', align: 'right', sort: r => r.short_qty, render: r => r.short_qty.toLocaleString('en-IN') },
    { key: 'days', label: 'Days', align: 'right', sort: r => r.days, title: 'sessions with a short-sale disclosure',
      render: r => <span style={{ color: r.days >= days / 2 ? T.amber : T.text }}>{r.days}</span> },
    { key: 'last', label: 'Last', align: 'right', sort: r => r.last, render: r => <span style={{ color: T.dim }}>{r.last}</span> },
    { key: 'move', label: 'Price over window', align: 'right', sort: r => r.move_pct ?? -999, title: 'adjusted close, from the first session of the window to the latest',
      render: r => <span style={{ color: (r.move_pct ?? 0) >= 0 ? T.green : T.red }}>{fmtPct(r.move_pct, 1)}</span> },
  ]
  return (
    <Panel source={sourceOf(d?.data_through ?? null, { source: 'NSE short sales' })} badge="context" title={`Institutional short selling${d ? ` · ${d.count} stocks` : ''}`} accent={T.red} pad={0}
      subtitle={d ? `NSE short-sale disclosures, ${d.from} → ${d.data_through ?? 'latest'} · ranked by shares shorted as a share of all trading · persistent shorting (many days) in a rising stock can fuel a squeeze` : 'NSE short-sale disclosures'}
      right={<div style={{ display: 'flex', gap: 4 }}>{[5, 20, 60].map(n => <Chip key={n} color={T.red} active={days === n} onClick={() => setDays(n)}>{n} SESSIONS</Chip>)}</div>}>
      {err ? <ErrorBox error={err} /> : !d ? <Loading label="short selling" /> :
        <DataTable columns={cols} rows={d.rows} rowKey={r => r.symbol} dense maxHeight={480} initialSort={{ key: 'pct', dir: 'desc' }}
          exportName={`short_selling_${days}d`} empty="No short-sale disclosures in this window" />}
      <div style={{ fontSize: 10, color: T.dim, padding: '6px 10px' }}>
        Context, not a signal: NSE publishes institutional short sales (no client names), not the outstanding short position.
      </div>
    </Panel>
  )
}

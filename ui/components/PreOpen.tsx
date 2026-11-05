'use client'

import { apiError } from '@/lib/errors'
/**
 * PRE — the NSE pre-open call auction (orders 09:00–09:08, price discovery, trading from 09:15). Per stock: the
 * indicative equilibrium price (IEP), the gap vs yesterday's close, and the buy and sell quantity left in the book.
 * A one-sided book (imbalance near ±1) is the earliest read on the open. Refreshes every 20 s during the auction;
 * outside it NSE keeps the last session's final book.
 */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { getPreOpen, type PreOpen as PreOpenData, type PreOpenRow } from '@/lib/api'
import { daysUntil, useCorpEvents } from '@/lib/useCorpEvents'
import { usePins } from '@/lib/pins'
import { useWatchlist } from '@/context/AppContext'
import { Chip, DataTable, ErrorBox, EventBadge, Input, Loading, PageHeader, Panel, Stat, T, TickerLink, type Column, fmtPct, fmtPx, fmtSigned, tone } from '@/components/terminal'

type Key = 'FO' | 'NIFTY' | 'BANKNIFTY' | 'ALL'
const KEYS: [Key, string][] = [['FO', 'F&O STOCKS'], ['NIFTY', 'NIFTY 50'], ['BANKNIFTY', 'BANK NIFTY'], ['ALL', 'ALL NSE']]
const BUCKETS: [number, number, string][] = [[-Infinity, -3, '< −3%'], [-3, -1, '−3…−1'], [-1, 0, '−1…0'], [0, 1, '0…+1'], [1, 3, '+1…+3'], [3, Infinity, '> +3%']]

const pct = fmtPct
const money = (v: number | null) => (v == null ? '—' : v >= 1e7 ? `₹${(v / 1e7).toFixed(1)} cr` : `₹${(v / 1e5).toFixed(1)} L`)
const qty = (v: number | null) => (v == null ? '—' : Math.round(v).toLocaleString('en-IN'))

function auctionPhase(now: Date): { live: boolean; label: string } {
  const m = now.getHours() * 60 + now.getMinutes()
  const wd = now.getDay() >= 1 && now.getDay() <= 5
  if (!wd) return { live: false, label: 'market closed today · showing the last session' }
  if (m < 9 * 60) return { live: false, label: 'auction opens 09:00 · showing the last session' }
  if (m < 9 * 60 + 8) return { live: true, label: 'ORDER ENTRY · 09:00–09:08' }
  if (m < 9 * 60 + 15) return { live: true, label: 'PRICE DISCOVERY DONE · trading at 09:15' }
  return { live: false, label: 'regular session · this is the morning auction' }
}

function Imbalance({ v }: { v: number | null }) {
  if (v == null) return <span style={{ color: T.dim }}>—</span>
  const w = Math.min(Math.abs(v), 1) * 30
  return (
    <span title={`${(v * 100).toFixed(0)}%: (buy − sell) ÷ (buy + sell) left in the book`}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span style={{ position: 'relative', width: 60, height: 6, background: T.border, display: 'inline-block' }}>
        <span style={{ position: 'absolute', top: 0, height: 6, width: w, background: v >= 0 ? T.green : T.red, left: v >= 0 ? 30 : 30 - w }} />
        <span style={{ position: 'absolute', left: 29.5, top: -2, width: 1, height: 10, background: T.muted }} />
      </span>
      <span style={{ color: tone(v), minWidth: 34, textAlign: 'right' }}>{fmtSigned(v * 100, 0)}</span>
    </span>
  )
}

export function PreOpen() {
  const [key, setKey] = useState<Key>('FO')
  const [data, setData] = useState<PreOpenData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const [now, setNow] = useState(() => new Date())
  const events = useCorpEvents()
  const { watchlist } = useWatchlist()
  const { pins } = usePins()
  const phase = auctionPhase(now)

  const load = useCallback(() => {
    getPreOpen(key).then(r => { setData(r.data); setError(null) }).catch(e => setError(apiError(e, 'unavailable')))
  }, [key])
  useEffect(() => { setData(null); load() }, [load])
  useEffect(() => {
    const iv = setInterval(() => { const n = new Date(); setNow(n); if (auctionPhase(n).live) load() }, 20_000)
    return () => clearInterval(iv)
  }, [load])

  const rows = useMemo(() => (data?.rows ?? []).filter(r => r.change_pct != null), [data])
  // liquid enough to matter: at least ₹10 L crossed in the auction (illiquid names gap on a handful of shares)
  const liquid = useMemo(() => rows.filter(r => (r.value ?? 0) >= 1e6), [rows])
  const mine = useMemo(() => {
    const s = new Set<string>(watchlist.map(w => w.toUpperCase().replace(/\.NS$/, '')))
    for (const p of Object.values(pins)) if (p.pick.symbol?.region === 'IN') s.add(p.pick.symbol.base.toUpperCase())
    return rows.filter(r => s.has(r.symbol))
  }, [rows, watchlist, pins])
  const filtered = useMemo(() => { const n = q.trim().toUpperCase(); return n ? rows.filter(r => r.symbol.includes(n)) : rows }, [rows, q])
  const hist = useMemo(() => BUCKETS.map(([lo, hi, label]) => ({ label, lo, n: rows.filter(r => r.change_pct! >= lo && r.change_pct! < hi).length })), [rows])
  const median = useMemo(() => { const v = rows.map(r => r.change_pct!).sort((a, b) => a - b); return v.length ? v[Math.floor(v.length / 2)] : null }, [rows])
  const top = (list: PreOpenRow[], f: (r: PreOpenRow) => number, n = 10) => [...list].sort((a, b) => f(b) - f(a)).slice(0, n)

  const sessionDay = data?.timestamp?.slice(0, 11)
  const cols: Column<PreOpenRow>[] = [
    { key: 'symbol', label: 'Stock', sort: r => r.symbol, render: r => <TickerLink symbol={r.symbol} /> },
    { key: 'iep', label: 'IEP ₹', align: 'right', sort: r => r.iep ?? 0, render: r => <span style={{ color: T.bright }}>{fmtPx(r.iep)}</span> },
    { key: 'gap', label: 'Gap', align: 'right', sort: r => r.change_pct ?? 0, render: r => <span style={{ color: tone(r.change_pct), fontWeight: 600 }}>{pct(r.change_pct)}</span> },
    { key: 'prev', label: 'Prev close', align: 'right', sort: r => r.prev_close ?? 0, render: r => <span style={{ color: T.muted }}>{fmtPx(r.prev_close)}</span> },
    { key: 'qty', label: 'Matched qty', align: 'right', sort: r => r.final_qty ?? 0, render: r => <span style={{ color: T.muted }}>{qty(r.final_qty)}</span> },
    { key: 'value', label: 'Value', align: 'right', sort: r => r.value ?? 0, render: r => <span style={{ color: T.text }}>{money(r.value)}</span> },
    { key: 'buy', label: 'Buy left', align: 'right', sort: r => r.buy_qty ?? 0, render: r => <span style={{ color: T.green }}>{qty(r.buy_qty)}</span> },
    { key: 'sell', label: 'Sell left', align: 'right', sort: r => r.sell_qty ?? 0, render: r => <span style={{ color: T.red }}>{qty(r.sell_qty)}</span> },
    { key: 'imb', label: 'Imbalance', sort: r => r.imbalance ?? 0, render: r => <Imbalance v={r.imbalance} /> },
    { key: 'yh', label: 'vs 52w high', align: 'right', sort: r => r.vs_year_high_pct ?? -999,
      render: r => <span style={{ color: r.vs_year_high_pct != null && r.vs_year_high_pct >= 0 ? T.amber : T.muted }}>{r.vs_year_high_pct != null && r.vs_year_high_pct >= 0 ? 'NEW HIGH' : pct(r.vs_year_high_pct, 1)}</span> },
    { key: 'event', label: 'Next event', render: r => { const e = events.get(r.symbol)?.[0]; return e ? <EventBadge kind={e.kind} date={e.event_date} days={daysUntil(e.event_date)} typical={e.typical_move_pct} detail={e.detail} /> : <span style={{ color: T.dim }}>—</span> } },
  ]
  const mini = (title: string, list: PreOpenRow[], accent: string, show: (r: PreOpenRow) => ReactNode) => (
    <Panel title={title} accent={accent} pad={0}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: T.mono, fontSize: 11.5 }}>
        <tbody>
          {list.map(r => (
            <tr key={r.symbol} style={{ borderBottom: `1px solid ${T.border}` }}>
              <td style={{ padding: '5px 10px' }}><TickerLink symbol={r.symbol} /></td>
              <td style={{ padding: '5px 6px', textAlign: 'right', color: T.muted }}>{money(r.value)}</td>
              <td style={{ padding: '5px 10px', textAlign: 'right' }}>{show(r)}</td>
            </tr>))}
          {!list.length && <tr><td style={{ padding: 10, color: T.dim }}>—</td></tr>}
        </tbody>
      </table>
    </Panel>
  )

  return (
    <div>
      <PageHeader code="PRE" title="Pre-Open Auction"
        subtitle={`NSE call auction: IEP, gap and the order book left after matching · ${data?.timestamp ? `book as of ${data.timestamp}` : 'loading'}`}
        right={<div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          <span style={{ fontSize: 10, color: phase.live ? T.green : T.dim, marginRight: 8, letterSpacing: 0.5 }}>{phase.live ? '● ' : ''}{phase.label}</span>
          {KEYS.map(([k, l]) => <Chip key={k} color={T.amber} active={key === k} onClick={() => setKey(k)}>{l}</Chip>)}
        </div>} />
      {error && <ErrorBox error={error} />}
      {!data && !error && <Loading label="Reading the NSE pre-open book" />}
      {data && !rows.length && (
        <Panel title="No pre-open book" accent={T.red}>
          <span style={{ fontSize: 12, color: T.muted }}>NSE has no {KEYS.find(k => k[0] === key)?.[1]} pre-open data right now (the index lists are cleared between
            sessions). Try <span role="button" style={{ color: T.cyan, cursor: 'pointer' }} onClick={() => setKey('FO')}>F&O STOCKS</span>.</span>
        </Panel>
      )}
      {data && rows.length > 0 && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 10, marginBottom: 12 }}>
            <Stat label="Advances / declines" value={<span><span style={{ color: T.green }}>{data.advances ?? '—'}</span> / <span style={{ color: T.red }}>{data.declines ?? '—'}</span></span>}
                  sub={`${data.unchanged ?? 0} unchanged · ${sessionDay ?? ''}`} />
            <Stat label="Median gap" value={pct(median)} color={tone(median)} sub={`${rows.length} stocks`} />
            <Stat label="Gaps > ±2%" value={<span><span style={{ color: T.green }}>{rows.filter(r => r.change_pct! > 2).length}</span> / <span style={{ color: T.red }}>{rows.filter(r => r.change_pct! < -2).length}</span></span>} sub="up / down" />
            <Stat label="Matched in auction" value={money(data.total_value)} sub="total value crossed" />
            <div style={{ border: `1px solid ${T.border}`, background: T.panel, padding: '10px 12px' }}>
              <div style={{ fontSize: 10, color: T.muted, letterSpacing: 1, marginBottom: 6 }}>GAP DISTRIBUTION</div>
              <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height: 44 }}>
                {hist.map(h => {
                  const max = Math.max(...hist.map(x => x.n), 1)
                  return (
                    <div key={h.label} title={`${h.label}: ${h.n}`} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
                      <span style={{ fontSize: 9, color: T.muted }}>{h.n}</span>
                      <span style={{ width: '100%', height: Math.max(2, (h.n / max) * 30), background: h.lo >= 0 ? T.green : T.red, opacity: 0.8 }} />
                    </div>)
                })}
              </div>
              <div style={{ display: 'flex', gap: 4, fontSize: 9, color: T.dim, marginTop: 2 }}>{hist.map(h => <span key={h.label} style={{ flex: 1, textAlign: 'center' }}>{h.label}</span>)}</div>
            </div>
          </div>
          {mine.length > 0 && (
            <Panel title="Your stocks" accent={T.cyan} subtitle="watchlist and pins in this list" style={{ marginBottom: 12 }}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 18px', fontSize: 12 }}>
                {mine.map(r => (
                  <span key={r.symbol} style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
                    <TickerLink symbol={r.symbol} /><span style={{ color: tone(r.change_pct) }}>{pct(r.change_pct)}</span><Imbalance v={r.imbalance} />
                  </span>))}
              </div>
            </Panel>
          )}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 12, marginBottom: 12 }}>
            {mini('Gap up', top(liquid, r => r.change_pct!).filter(r => r.change_pct! > 0), T.green, r => <span style={{ color: T.green, fontWeight: 600 }}>{pct(r.change_pct)}</span>)}
            {mini('Gap down', top(liquid, r => -r.change_pct!).filter(r => r.change_pct! < 0), T.red, r => <span style={{ color: T.red, fontWeight: 600 }}>{pct(r.change_pct)}</span>)}
            {mini('Buyers left over', top(liquid.filter(r => r.imbalance != null && (r.buy_qty ?? 0) + (r.sell_qty ?? 0) > 0), r => r.imbalance!).filter(r => r.imbalance! > 0), T.green, r => <Imbalance v={r.imbalance} />)}
            {mini('Sellers left over', top(liquid.filter(r => r.imbalance != null && (r.buy_qty ?? 0) + (r.sell_qty ?? 0) > 0), r => -r.imbalance!).filter(r => r.imbalance! < 0), T.red, r => <Imbalance v={r.imbalance} />)}
          </div>
          <Panel title={`Full book · ${filtered.length.toLocaleString('en-IN')} stocks`} pad={0} accent={T.amber}
            subtitle="imbalance = (buy − sell) ÷ (buy + sell) of the orders left unmatched at the IEP · leaders above need ≥ ₹10 L matched"
            right={<Input value={q} onChange={setQ} placeholder="find stock" width={160} />}>
            <DataTable columns={cols} rows={filtered} rowKey={r => r.symbol} dense maxHeight={700} initialSort={{ key: 'gap', dir: 'desc' }} empty="No stocks match" />
          </Panel>
          <div style={{ fontSize: 10, color: T.dim, marginTop: 8 }}>
            Source: NSE pre-open market (www.nseindia.com). Each session's final book is archived daily under data/nse_archive/preopen for research.
            The pre-open is not part of any research verdict yet: context, not a signal.
          </div>
        </>
      )}
    </div>
  )
}

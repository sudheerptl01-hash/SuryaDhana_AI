'use client'

import { apiError } from '@/lib/errors'
/**
 * CF — company filings: every NSE equity announcement of the day, newest first, sorted into categories (results,
 * orders, ratings, M&A, insider/SAST, capital actions, people, board, analyst meets, press). Routine compliance
 * filings (depository certificates, trading-window notices, newspaper copies…) are hidden by default. Your stocks
 * (ICICI holdings, Desk, watchlist, pins) are highlighted and can be filtered. Refreshes every 60 s in market hours.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { getAnnouncements, getOpenPositions, type Filing, heldSymbols } from '@/lib/api'
import { useWatchlist } from '@/context/AppContext'
import { usePins } from '@/lib/pins'
import { Chip, ErrorBox, Input, Loading, PageHeader, Panel, T, TickerLink, fiscalQuarter, fmtPct, sourceOf, undatedSource } from '@/components/terminal'
import { useFinancialsLatest } from '@/lib/useFinancials'
import { isoDayFromNse, newestStamp } from '@/lib/nseDate'


const CATS: [string, string, string][] = [
  ['results', 'RESULTS', T.amber], ['orders', 'ORDERS', T.green], ['rating', 'RATINGS', T.cyan], ['m&a', 'M&A', T.violet],
  ['insider', 'INSIDER/SAST', T.green], ['capital', 'CAPITAL', T.amber], ['people', 'PEOPLE', T.muted], ['board', 'BOARD', T.muted],
  ['analyst', 'ANALYST MEETS', T.muted], ['press', 'PRESS', T.muted], ['other', 'OTHER', T.dim], ['routine', 'ROUTINE', T.dim],
]
const COLOR: Record<string, string> = Object.fromEntries(CATS.map(c => [c[0], c[2]]))
const LABEL: Record<string, string> = Object.fromEntries(CATS.map(c => [c[0], c[1]]))

export function CompanyFilings() {
  const [data, setData] = useState<Awaited<ReturnType<typeof getAnnouncements>>['data'] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [cats, setCats] = useState<Set<string>>(new Set())          // empty = everything except routine
  const [mineOnly, setMineOnly] = useState(false)
  const [q, setQ] = useState('')
  const [held, setHeld] = useState<string[]>([])
  const { watchlist } = useWatchlist()
  const { pins } = usePins()

  const load = useCallback(() => {
    getAnnouncements().then(r => { setData(r.data); setError(null) }).catch(e => setError(apiError(e, 'unavailable')))
  }, [])
  useEffect(() => {
    load()
    getOpenPositions().then(r => setHeld(heldSymbols(r.data))).catch(() => {})
    const iv = setInterval(load, 60_000)
    return () => clearInterval(iv)
  }, [load])

  const mine = useMemo(() => {
    const s = new Set<string>(held)
    watchlist.forEach(w => s.add(w.toUpperCase().replace(/\.NS$/, '')))
    Object.values(pins).forEach(p => { if (p.pick.symbol?.region === 'IN') s.add(p.pick.symbol.base.toUpperCase()) })
    return s
  }, [held, watchlist, pins])

  const items = useMemo(() => {
    const n = q.trim().toUpperCase()
    return (data?.items ?? []).filter(f =>
      (cats.size ? cats.has(f.category) : f.category !== 'routine')
      && (!mineOnly || mine.has(f.symbol))
      && (!n || f.symbol.includes(n) || (f.company ?? '').toUpperCase().includes(n) || f.subject.toUpperCase().includes(n)))
  }, [data, cats, mineOnly, mine, q])
  // results filers' numbers from the FA cache (the filing watcher queues each new results filing for a read)
  const { fin: resFin } = useFinancialsLatest([...new Set((data?.items ?? []).filter(f => f.category === 'results').map(f => f.symbol))], { prefetch: false })
  const mineCount = useMemo(() => (data?.items ?? []).filter(f => mine.has(f.symbol) && f.category !== 'routine').length, [data, mine])

  const toggle = (c: string) => setCats(prev => { const s = new Set(prev); s.has(c) ? s.delete(c) : s.add(c); return s })

  return (
    <div>
      <PageHeader code="CF" title="Company Filings"
        subtitle={`every NSE equity announcement today, newest first · ${data ? `${data.items.length} filings` : 'loading'}${data?.market_open ? ' · every 60 s' : ''}`}
        right={<div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <Chip color={T.cyan} active={mineOnly} onClick={() => setMineOnly(m => !m)}>YOUR STOCKS {mineCount}</Chip>
          <Input value={q} onChange={setQ} placeholder="stock, company or subject" width={220} />
        </div>} />
      {error && <ErrorBox error={error} />}
      {!data && !error && <Loading label="Reading NSE announcements" />}
      {data && (
        <>
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 10 }}>
            <Chip color={T.text} active={cats.size === 0} onClick={() => setCats(new Set())}>ALL (NO ROUTINE)</Chip>
            {CATS.map(([k, l, c]) => (data.counts[k] ?? 0) > 0 && (
              <Chip key={k} color={c} active={cats.has(k)} onClick={() => toggle(k)}>{l} {data.counts[k]}</Chip>))}
          </div>
          <Panel source={data?.market_open
            ? undatedSource('NSE announcements', `NSE's announcements feed in session, refreshed every 60 s (not a tick feed)${newestStamp(data?.items) ? ` · newest filing ${newestStamp(data?.items)!.slice(11, 16)} IST` : ''}`)
            : sourceOf(isoDayFromNse(data?.date), { source: 'NSE announcements' })} badge="context" title={`${items.length} filings`} accent={T.amber} pad={0}
            subtitle="click a ticker for its profile · ↗ opens the filing on NSE · categories: NSE's own subject first, then keywords in the summary (an earnings-call notice is not results)">
            <div style={{ maxHeight: 760, overflowY: 'auto' }}>
              {items.map(f => (
                <div key={`${f.seq}-${f.symbol}`} style={{ display: 'grid', gridTemplateColumns: '58px 110px 110px minmax(0, 1fr) 30px', gap: 10,
                                                       padding: '7px 12px', borderBottom: `1px solid ${T.border}`, alignItems: 'baseline',
                                                       background: mine.has(f.symbol) ? '#0b1420' : 'transparent' }}>
                  <span style={{ fontFamily: T.mono, fontSize: 11, color: T.muted }}>{(f.time ?? '').slice(11, 16)}</span>
                  <span style={{ display: 'inline-flex', gap: 4, alignItems: 'baseline' }}>
                    {mine.has(f.symbol) && <span title="your stock" style={{ color: T.cyan }}>●</span>}<TickerLink symbol={f.symbol} />
                  </span>
                  <span style={{ fontSize: 9.5, letterSpacing: 0.6, color: COLOR[f.category] ?? T.dim, fontWeight: 600 }}>{LABEL[f.category] ?? f.category.toUpperCase()}</span>
                  <span style={{ minWidth: 0 }}>
                    <span style={{ fontSize: 11.5, color: T.text }}>{f.subject}</span>
                    {f.category === 'results' && (() => {   // what the numbers said, once the filing's XBRL has been read
                      const n = resFin[f.symbol]
                      if (!n || !(n.filed_at ?? '').startsWith((f.time ?? '').slice(0, 10)) || (n.revenue_yoy == null && n.pat_yoy == null && !n.pat_yoy_turn)) return null
                      const c = (v: number | null | undefined) => v == null ? T.dim : v >= 0 ? T.green : T.red
                      return <span style={{ fontSize: 10.5, fontFamily: T.mono, marginLeft: 8, color: T.muted }}>
                        {fiscalQuarter(n.period_end)} · rev <span style={{ color: c(n.revenue_yoy) }}>{fmtPct(n.revenue_yoy, 0)}</span> · profit{' '}
                        {n.pat_yoy_turn ? <span style={{ color: n.pat_yoy_turn === 'to profit' ? T.green : T.red }}>{n.pat_yoy_turn}</span>
                          : <span style={{ color: c(n.pat_yoy) }}>{fmtPct(n.pat_yoy, 0)}</span>} y/y
                        {n.pe != null && <span style={{ color: T.dim }}> · P/E {n.pe.toFixed(0)}×</span>}</span>
                    })()}
                    {f.text && <span title={f.text} style={{ display: 'block', fontSize: 10.5, color: T.dim, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.text}</span>}
                  </span>
                  {f.pdf ? <a href={f.pdf} target="_blank" rel="noreferrer" title="open the filing on NSE" style={{ color: T.cyan, textDecoration: 'none', fontSize: 12 }}>↗</a> : <span />}
                </div>
              ))}
              {!items.length && <div style={{ padding: 16, fontSize: 12, color: T.dim }}>No filings match.</div>}
            </div>
          </Panel>
        </>
      )}
    </div>
  )
}

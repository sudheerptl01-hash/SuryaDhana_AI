'use client'

import { apiError } from '@/lib/errors'
import { fmtSigned } from '@/lib/format'   // signed numbers with U+2212 (C1-trader-ux-18)
/**
 * Who moved the index today: each constituent's contribution in index points (rebuilt free-float weights: shares
 * from results filings × previous close × (1 − promoter holding)). The explained total is shown next to the
 * actual move so the approximation's error is visible.
 *
 * Live program (reports/live_nse): the weights come from /api/market/index-contribution every 2 min (they are built
 * on the previous close, so they do not move intraday); the index level and every member's move come from the live
 * NSE quote service every 3 s (the Breeze websocket carries NIFTY 50 + its 50 members on one connection; NSE's
 * website, ≈ 1 min, for a member that is not streaming) and the points are recomputed here (liveModel.ts). The
 * panel's chip (`onSource`) is the live rows' own: LIVE · BREEZE · 1s, or DELAYED · NSE · <age> for the 2-min payload.
 */
import { useEffect, useMemo, useState } from 'react'
import { getIndexContribution, type IndexContribution as Data } from '@/lib/api'
import { Chip, T, TickerLink, fmtPct, type SourceInfo } from '@/components/terminal'
import { goToPage } from '@/lib/navigate'
import { useLiveQuotes } from '@/lib/liveQuotes'
import { liveContribution, nseDelayedSource } from '@/components/liveModel'
import { useMarketOpen } from '@/components/shell/useFeed'

/**
 * NSE's own stamp on the payload ("05-Nov-2026 09:54", IST) → what the header prints: the time today, or the session date
 * when the numbers are a previous session's (after the close, weekends, holidays). The panel never shows moves without
 * saying when NSE published them (asked 5 Nov: "is this live or stale?").
 */
export function contributionStamp(time: string | null | undefined, now: Date = new Date()): string | null {
  const m = /^(\d{2})-([A-Za-z]{3})-(\d{4})\s+(\d{2}):(\d{2})/.exec(time ?? '')
  if (!m) return null
  const todayIst = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', year: 'numeric' }).format(now)
  const stampDay = `${m[1]} ${m[2]} ${m[3]}`
  const hm = `${m[4]}:${m[5]} IST`
  return stampDay.toLowerCase() === todayIst.replace(/,/g, '').toLowerCase() ? `NSE ${hm}` : `NSE · session ${m[1]} ${m[2]} ${hm}`
}

export function IndexContribution({ onSource }: { onSource?: (s: SourceInfo | null) => void } = {}) {
  const [index, setIndex] = useState('NIFTY 50')
  const [raw, setD] = useState<Data | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    const load = () => getIndexContribution(index).then(r => { if (live) { setD(r.data); setErr(null) } })
      .catch(e => { if (live) setErr(apiError(e, 'unavailable')) })
    setD(null); load()
    const iv = setInterval(load, 120_000)
    return () => { live = false; clearInterval(iv) }
  }, [index])
  // live overlay: the index + its members from the live quote service, points recomputed on the stored weights
  const liveSyms = useMemo(() => (raw ? [raw.index, ...raw.members.map(m => m.symbol)] : []), [raw])
  const live = useLiveQuotes(liveSyms, { intervalMs: 3_000 })
  const lc = useMemo(() => (raw ? liveContribution(raw, live.quotes) : null), [raw, live.quotes])
  const d = lc
  const marketOpen = useMarketOpen()
  const src: SourceInfo | null = raw
    ? (live.available && live.source && lc && (lc.liveMembers > 0 || lc.indexLive)) ? live.source
      : nseDelayedSource(raw.time, { marketOpen, now: Date.now(), hint: 'heatmap ≈ 60 s + allIndices ≈ 15 s caches, re-polled every 2 min' })
    : null
  const srcKey = src ? `${src.state}|${src.source}|${Math.round((src.ageS ?? 0) / 5)}|${src.mix?.live ?? ''}|${src.asOf}` : ''
  useEffect(() => { onSource?.(src) }, [srcKey])  // eslint-disable-line react-hooks/exhaustive-deps
  const ms = (d?.members ?? []).filter(m => m.points != null)
  const top = ms.slice(0, 8), bottom = [...ms].reverse().slice(0, 8)
  const max = Math.max(1, ...ms.map(m => Math.abs(m.points!)))
  const bar = (m: Data['members'][number]) => (
    <div key={m.symbol} style={{ display: 'grid', gridTemplateColumns: '96px 1fr 62px 52px', gap: 8, alignItems: 'center', fontSize: 11, fontFamily: T.mono, padding: '2px 0' }}>
      <TickerLink symbol={m.symbol} />
      <div style={{ height: 8, background: '#0f141d', position: 'relative' }}>
        <div style={{ position: 'absolute', top: 0, bottom: 0, left: 0, width: `${Math.abs(m.points!) / max * 100}%`, background: m.points! >= 0 ? T.green : T.red, opacity: 0.8 }} />
      </div>
      <span style={{ textAlign: 'right', color: m.points! >= 0 ? T.green : T.red }}>{fmtSigned(m.points!, 1)}</span>
      <span style={{ textAlign: 'right', color: T.dim, fontSize: 10 }}>{fmtPct(m.change_pct, 1)}</span>
    </div>)
  const gap = d && d.change != null ? d.explained_points - d.change : null
  return (
    <div>
      <div style={{ display: 'flex', gap: 4, marginBottom: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        {['NIFTY 50', 'NIFTY BANK', 'NIFTY IT', 'NIFTY NEXT 50'].map(ix => <Chip key={ix} color={T.cyan} active={index === ix} onClick={() => setIndex(ix)}>{ix.replace('NIFTY ', '')}</Chip>)}
        <span style={{ flex: 1 }} />
        {d && <span style={{ fontSize: 11, fontFamily: T.mono, color: T.muted }}>
          {lc && (lc.liveMembers > 0 || lc.indexLive)
            ? <span data-contrib-stamp="live" title={`index ${lc.indexLive ? 'and ' : 'from NSE; '}${lc.liveMembers} of ${lc.members.length} members from the live NSE quote service (Breeze websocket, NSE's website when a name is not streaming); weights from filings, every 2 min`}>
                index {live.lineFor(lc.index) ?? 'from NSE'} · {lc.liveMembers}/{lc.members.length} members on live quotes · </span>
            : contributionStamp(d.time) && <span data-contrib-stamp title="NSE's publish time for these moves (index ~15 s, members ~60 s server cache); this panel re-polls every 2 min">{contributionStamp(d.time)} · </span>}
          actual <span style={{ color: (d.change ?? 0) >= 0 ? T.green : T.red }}>{fmtSigned(d.change, 1)} pts</span>
          {' · '}explained {fmtSigned(d.explained_points, 1)}
          {gap != null && d.change ? <span style={{ color: Math.abs(gap / d.change) > 0.1 ? T.amber : T.dim }}> ({(Math.abs(gap / d.change) * 100).toFixed(0)}% off)</span> : null}
        </span>}
      </div>
      {!d ? <div style={{ fontSize: 11, color: T.dim }}>{err ? `unavailable: ${err}` : 'Loading…'}</div> :
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18 }}>
          <div><div style={{ fontSize: 9, color: T.green, letterSpacing: 1, marginBottom: 3 }}>ADDED THE MOST</div>{top.filter(m => m.points! > 0).map(bar)}</div>
          <div><div style={{ fontSize: 9, color: T.red, letterSpacing: 1, marginBottom: 3 }}>TOOK AWAY THE MOST</div>{bottom.filter(m => m.points! < 0).map(bar)}</div>
        </div>}
      <div style={{ fontSize: 10, color: T.dim, marginTop: 4 }}>
        points = previous index level × weight × % change · weights rebuilt from filings (shares × price × (1 − promoter %)); sector indices also cap single weights, so they explain less exactly
        {d?.missing.length ? ` · not weighted yet: ${d.missing.join(', ')}` : ''}
        {' · '}<span role="button" onClick={() => goToPage('memb')} style={{ color: T.cyan, cursor: 'pointer' }}>all members · MEMB ›</span>
      </div>
    </div>
  )
}

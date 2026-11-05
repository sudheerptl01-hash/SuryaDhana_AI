'use client'

/**
 * SYS › live feeds (live program, reports/live_nse; L-INVENTORY row "add a live-feeds row per source with last-tick
 * age"): the live NSE quote service's own status from `GET /api/live/status`, every 10 s while the page is open — the
 * Breeze websocket engine (OFF / CONNECTING / LIVE / DEGRADED / DISCONNECTED), how many instruments it carries against
 * its cap, ticks per minute, the age of the last tick, whether a Breeze session exists, and the NSE website fallback's
 * health. Read-only: nothing here starts, stops or logs in anything.
 */
import { useEffect, useState } from 'react'
import { Panel, T, sourceOf, type SourceInfo } from '@/components/terminal'
import { fetchLiveStatus, fmtAge, type LiveStatus } from '@/lib/liveQuotes'

const STATE_COLOR: Record<string, string> = { LIVE: T.green, CONNECTING: T.amber, DEGRADED: T.amber, DISCONNECTED: T.red, OFF: T.muted }

export function LiveFeedStatus() {
  const [st, setSt] = useState<{ code: number; data: LiveStatus | null; at: string } | null>(null)
  useEffect(() => {
    let alive = true
    const ctl = new AbortController()
    const get = () => fetchLiveStatus(ctl.signal).then(r => { if (alive) setSt({ code: r.status, data: r.data, at: new Date().toISOString() }) })
    void get()
    const iv = setInterval(() => { if (typeof document === 'undefined' || document.visibilityState !== 'hidden') void get() }, 10_000)
    return () => { alive = false; clearInterval(iv); ctl.abort() }
  }, [])
  const d = st?.data
  const source: SourceInfo | null = !st ? null
    : d ? { ...sourceOf(st.at, { source: 'live service', live: d.state === 'LIVE' }), hint: 'GET /api/live/status every 10 s' }
    : { state: 'offline', source: 'live service', asOf: null, ageDays: null, hint: st.code === 404 ? 'the live quote service is not deployed yet (404)' : 'the live quote service is not answering' }
  const cell = (k: string, v: string, c: string = T.text, title?: string) => (
    <div title={title} style={{ border: `1px solid ${T.border}`, padding: '6px 10px', minWidth: 0 }}>
      <div style={{ fontSize: 9, color: T.dim, letterSpacing: 1, textTransform: 'uppercase' }}>{k}</div>
      <div style={{ fontFamily: T.mono, fontSize: 14, color: c, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{v}</div>
    </div>)
  return (
    <Panel title="Live feeds" subtitle="NSE prices for every pane: Breeze websocket → NSE website (≈ 1 min) → the last close" accent={T.green} source={source}>
      {!st ? <div style={{ fontSize: 11, color: T.dim }}>Reading /api/live/status…</div>
        : !d ? <div style={{ fontSize: 11, color: T.amber }}>{st.code === 404 ? 'Live quote service not deployed yet: panes keep their previous sources and say so.' : 'Live quote service not answering: panes show their last values as STALE / OFFLINE.'}</div>
        : <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, minmax(0, 1fr))', gap: 8 }}>
            {cell('Breeze websocket', d.state, STATE_COLOR[d.state] ?? T.text, 'the tick engine (LIVE_TICKS); OFF means every price comes from NSE’s website or the last close')}
            {cell('Instruments', d.subscribed != null ? `${d.subscribed}${d.cap != null ? ` / ${d.cap}` : ''}` : '—', T.text, 'subscribed on the socket / the cap')}
            {cell('Ticks per minute', d.ticks_per_min != null ? Math.round(d.ticks_per_min).toLocaleString('en-IN') : '—')}
            {cell('Last tick', d.last_tick_age_s != null ? `${fmtAge(d.last_tick_age_s)} ago` : '—', d.last_tick_age_s != null && d.last_tick_age_s > 10 ? T.amber : T.text,
                  'NIFTY 50 ticks about 10 times a second while NSE trades: a silence over 10 s in session means the feed stalled')}
            {cell('Breeze session', d.breeze_session == null ? '—' : d.breeze_session ? 'yes' : 'no', d.breeze_session === false ? T.amber : T.text,
                  'the daily ICICI login; without it the socket cannot connect (log in on BRKR)')}
            {cell('NSE fallback', d.nse_fallback?.ok == null ? '—' : d.nse_fallback.ok ? 'ok' : 'failing', d.nse_fallback?.ok === false ? T.red : T.text,
                  d.nse_fallback?.last_ok_at ? `last good NSE read ${d.nse_fallback.last_ok_at}` : 'NSE website (heatmap / allIndices), about 1 min behind')}
          </div>}
    </Panel>
  )
}

'use client'

/**
 * OMON › LIVE (reports/terminal_v2/PLAN.md 1.1 panel 7; precedent Quantsapp IV live): today's 15-minute IV path from the
 * Breeze chain pilot — ATM IV (ours, from bid/ask mids) with NSE's own IV beside it, the ATM straddle and the PCR per
 * snapshot — with the SourceChip LIVE · BREEZE / LIVE · NSE / OFFLINE the route reports. `context`; nothing here feeds
 * a trade. Shown only while OMON is in LIVE mode and the pilot has stored a snapshot for the day.
 */
import { useEffect, useState } from 'react'
import { Panel, T, fmtNum, type SourceInfo } from '@/components/terminal'
import { LineChart } from './charts'
import { getIvIntraday, storeNote, volError, type IvIntraday } from './api'

export function liveSource(d: IvIntraday | null): SourceInfo {
  if (!d || !d.ok) return { state: 'offline', source: 'iv_intraday', asOf: d?.date ?? null, hint: storeNote(d) ?? 'pilot not deployed' }
  const src = String(d.source ?? 'OFFLINE').toUpperCase()
  if (src === 'OFFLINE' || !d.points.length) return { state: 'offline', source: 'Breeze chain pilot', asOf: d.date, hint: 'no snapshot stored for this session' }
  const lastTs = d.points[d.points.length - 1].ts
  // stored 15-minute snapshots (iv_intraday), not a stream: DELAYED with their age, never LIVE (check:LV-GATES major)
  const ageS = Number.isFinite(Date.parse(lastTs)) ? Math.max(0, (Date.now() - Date.parse(lastTs)) / 1000) : null
  return { state: 'delayed', source: src, asOf: lastTs, ageS, hint: 'stored 15-minute chain snapshot (iv_intraday pilot)' }
}

export function IvLivePath({ symbol, enabled }: { symbol: string; enabled: boolean }) {
  const [d, setD] = useState<IvIntraday | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    if (!enabled) return
    let alive = true
    const load = () => getIvIntraday(symbol).then(r => { if (alive) { setD(r.data); setErr(null) } }).catch((e: unknown) => { if (alive) setErr(volError(e, 'unavailable')) })
    setD(null); load()
    const iv = setInterval(() => { if (!document.hidden) load() }, 5 * 60_000)        // the pilot writes every 15 min; 5 min is plenty
    return () => { alive = false; clearInterval(iv) }
  }, [symbol, enabled])
  if (!enabled) return null
  const pts = d?.points ?? []
  const last = pts.length ? pts[pts.length - 1] : null
  const hm = (ts: string) => ts.slice(11, 16)
  return (
    <Panel title={`${symbol} · IV today (15-min pilot)`} accent={T.cyan} pad={8} style={{ marginBottom: 12 }}
      source={liveSource(d)} badge={d?.badge ?? 'context'}
      subtitle={last ? `${hm(pts[0].ts)} → ${hm(last.ts)} IST · ${d?.snapshots ?? pts.length} snapshots · near expiry ${last.expiry} · ATM ${fmtNum(last.atm_strike, 0)}` : d?.date ?? ''}>
      {err && <div style={{ fontSize: 11, color: T.amber }}>Unavailable: {err}</div>}
      {!err && !last && <div style={{ fontSize: 11, color: T.muted }}>No intraday IV snapshot stored for this session{d && !d.ok ? ` (${storeNote(d)})` : ''}: the pilot runs 09:20–15:30 on trading days when the Breeze session is live and the budget ledger allows it (O-T6).</div>}
      {last && (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 2fr) minmax(220px, 1fr)', gap: 12, alignItems: 'start' }}>
          <div>
            <div style={{ fontSize: 10, color: T.muted, marginBottom: 4 }}>cyan = ATM IV (ours, bid/ask mid) · dashed = NSE's IV · amber = ATM straddle ₹ (right)</div>
            <LineChart dates={pts.map(p => p.ts)} height={150} lUnit="%" ariaLabel="intraday IV path"
              series={[{ label: 'ATM IV', color: T.cyan, values: pts.map(p => p.atm_iv), w: 1.7 },
                       { label: 'NSE IV', color: T.cyan, values: pts.map(p => p.nse_atm_iv), w: 1, dash: '4 3' },
                       { label: 'straddle', color: T.amber, values: pts.map(p => p.straddle), axis: 'R', w: 1.1 }]} />
          </div>
          <div style={{ fontFamily: T.mono, fontSize: 11, display: 'grid', gap: 4 }}>
            <div>ATM IV <b style={{ color: T.text }}>{fmtNum(last.atm_iv, 2)}%</b> <span style={{ color: T.dim }}>· NSE {fmtNum(last.nse_atm_iv, 2)}%</span></div>
            <div>straddle <b style={{ color: T.text }}>₹{fmtNum(last.straddle, 2)}</b></div>
            <div>PCR <b style={{ color: T.text }}>{fmtNum(last.pcr, 2)}</b> <span style={{ color: T.dim }}>· {last.n_strikes} strikes</span></div>
            <div style={{ color: T.dim, fontSize: 10, lineHeight: 1.5, marginTop: 4 }}>{d?.note}</div>
          </div>
        </div>
      )}
    </Panel>
  )
}

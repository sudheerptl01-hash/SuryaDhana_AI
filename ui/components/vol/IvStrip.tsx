'use client'

/**
 * Stock window › Profile: the implied-volatility strip (reports/terminal_v2/PLAN.md 1.1 panel 6; precedent Bloomberg DES
 * implied-vol strip): iv30_cm, IV rank and IV percentile (each defined), 25Δ skew, IV − RV20 and the next results date,
 * for an F&O underlying. `context`; the numbers describe where the stock's options are priced today. Renders nothing
 * for a stock without a stored IV row (not in F&O, or the store not deployed) except a one-line reason.
 */
import { useEffect, useState } from 'react'
import { BadgeChip, SourceChip, T, fmtNum, sourceOf } from '@/components/terminal'
import { getIvHistory, storeNote, volError, type IvHistory } from './api'

const pct = (v: number | null | undefined, d = 1) => (v == null || !Number.isFinite(v) ? '—' : `${fmtNum(v, d)}%`)
const signed = (v: number | null | undefined, d = 2) => (v == null || !Number.isFinite(v) ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(d)}`)

export function IvStrip({ symbol, nextResults }: { symbol: string; nextResults?: string | null }) {
  const [d, setD] = useState<IvHistory | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    setD(null); setErr(null)
    getIvHistory(symbol, 20).then(r => { if (alive) setD(r.data) }).catch((e: unknown) => { if (alive) setErr(volError(e, 'unavailable')) })
    return () => { alive = false }
  }, [symbol])
  const last = d?.ok && d.rows.length ? d.rows[d.rows.length - 1] : null
  // the store answered and holds nothing for this symbol: not an F&O underlying (or nothing traded) — no strip at all
  if (d && d.ok && !d.rows.length) return null
  const cell = (label: string, value: React.ReactNode, title?: string) => (
    <div title={title} style={{ textAlign: 'center', border: `1px solid ${T.border}`, padding: '4px 6px', minWidth: 0 }}>
      <div style={{ fontSize: 9, color: T.dim, letterSpacing: 1, whiteSpace: 'nowrap' }}>{label}</div>
      <div style={{ fontFamily: T.mono, fontSize: 12, color: T.text, whiteSpace: 'nowrap' }}>{value}</div>
    </div>
  )
  return (
    <section data-iv-strip style={{ border: `1px solid ${T.border}`, background: T.panel, minWidth: 0 }}>
      <header style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '6px 10px', borderBottom: `1px solid ${T.border}`, background: '#080b10' }}>
        <span style={{ width: 3, height: 11, background: T.violet }} />
        <span style={{ fontFamily: T.display, fontSize: 11, fontWeight: 600, letterSpacing: 1.5, color: T.violet, textTransform: 'uppercase' }}>Implied volatility</span>
        <span style={{ fontSize: 10, color: T.muted }}>{last ? `${symbol} options · stored ${last.date}` : 'F&O options'}</span>
        <span style={{ flex: 1 }} />
        <BadgeChip badge="context" />
        <SourceChip info={sourceOf(last?.date ?? null, { source: 'iv_summary_daily', hint: last ? null : (err ?? storeNote(d) ?? 'no stored IV row') })} />
      </header>
      <div style={{ padding: 10 }}>
        {last ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, minmax(0, 1fr))', gap: 4 }}>
            {cell('IV30 (CM)', pct(last.iv30_cm, 2), d?.definitions?.iv30_cm)}
            {cell('IV RANK', fmtNum(last.iv_rank_252 ?? d?.rank.stored.iv_rank_252 ?? d?.rank.iv_rank_252, 0), `${d?.definitions?.iv_rank_252 ?? 'IV rank'} (252 sessions)`)}
            {cell('IV PCTILE', fmtNum(last.iv_pctile_252 ?? d?.rank.stored.iv_pctile_252 ?? d?.rank.iv_pctile_252, 0), `${d?.definitions?.iv_pctile_252 ?? 'IV percentile'} (252 sessions)`)}
            {cell('25Δ SKEW', last.skew_25d_30 == null ? '—' : `${signed(last.skew_25d_30)} pts`, d?.definitions?.skew_25d_30)}
            {cell('IV − RV20 (CC)', last.iv_minus_rv20 == null ? '—' : `${signed(last.iv_minus_rv20)} pts`, d?.definitions?.iv_minus_rv20 ?? 'IV30 minus the 20-session close-to-close realised vol')}
            {cell('NEXT RESULTS', nextResults ?? '—', 'from the NSE event calendar (board meeting for results)')}
          </div>
        ) : (
          <div style={{ fontSize: 11, color: T.muted, lineHeight: 1.5 }}>
            {err ? `IV strip unavailable: ${err}` : d && !d.ok ? `No stored IV row (${storeNote(d)}): iv_summary_daily is written nightly by iv_eod for every F&O underlying once the IV store is deployed.`
              : d ? `${symbol} has no stored IV row: not an F&O underlying, or no traded strikes on the last session.` : 'Loading…'}
          </div>
        )}
        {last && <div style={{ fontSize: 10, color: T.dim, marginTop: 6 }}>{d?.note}</div>}
      </div>
    </section>
  )
}

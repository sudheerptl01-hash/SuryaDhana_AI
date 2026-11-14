'use client'

/**
 * DESK › "Book vs NIFTY · who moved them" (reports/terminal_v2/PLAN.md 1.2): the paper book's real lots × stored closes in
 * percentage points of NAV over a horizon, beside NIFTY's top adds and drags over the same sessions (GET
 * /api/desk/attribution). Honest when the book is in cash: "book = liquid fund since <date>; nothing to attribute" — it
 * never invents a contribution for a book that holds nothing. Reads the paper ledger only; writes nothing; the Desk's
 * rules are frozen. Badges: book / NIFTY `arithmetic`.
 */
import { useEffect, useState } from 'react'
import { BadgeChip, Panel, T, TickerLink, fmtInr, sourceOf } from '@/components/terminal'
import { driversError, fmtPts, getDeskAttribution, type DeskAttribution as Payload, type Horizon } from './api'
import { HorizonPicker } from './DriversView'
import { dayMon } from './driversModel'

const pp = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(2)} pp`)

export function DeskAttribution() {
  const [horizon, setHorizon] = useState<Horizon>('1m')
  const [d, setD] = useState<Payload | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    setD(null); setErr(null)
    getDeskAttribution(horizon).then(r => { if (alive) setD(r.data) }).catch((e: unknown) => { if (alive) setErr(driversError(e)) })
    return () => { alive = false }
  }, [horizon])
  const win = d?.horizon?.from ? `${dayMon(d.horizon.from)} → ${dayMon(d.horizon.to)} · ${d.horizon.sessions} sessions` : null
  const nifty = d?.nifty ?? null
  return (
    <Panel title="Book vs NIFTY · who moved them" accent={T.amber} pad={10} badge={d?.badges?.book ?? 'arithmetic'}
      source={sourceOf(d?.as_of ?? null, { source: 'paper ledger + index_contribution_daily', hint: err ?? (d && d.ok === false ? Object.values(d.store_errors ?? {}).join(' · ') : null) })}
      subtitle={win ? `${win} · real lots × stored closes, pp of NAV · PAPER` : 'real lots × stored closes, pp of NAV · PAPER'}
      right={<HorizonPicker value={horizon} onChange={setHorizon} />}>
      {err && <div style={{ fontSize: 11, color: T.amber }} data-desk-attr-error>Unavailable: {err}</div>}
      {!d && !err && <div style={{ fontSize: 11, color: T.dim }}>Loading…</div>}
      {d && (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 12 }} data-desk-attr={d.risk_off ? 'cash' : 'book'}>
          <div>
            <div style={{ fontSize: 10, letterSpacing: 1.2, color: T.muted, fontFamily: T.mono, marginBottom: 4 }}>THE BOOK</div>
            {d.risk_off ? (
              <div style={{ fontSize: 12, color: T.text, lineHeight: 1.6 }}>
                Book = liquid fund since {d.since ? dayMon(d.since) : '—'}; nothing to attribute. The crash filter keeps the Desk in cash
                (the book value is in the Desk header); this panel lists names only when the paper book holds real lots.
              </div>
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: T.mono, fontSize: 11 }}>
                <thead><tr style={{ color: T.muted, fontSize: 10 }}>{['STOCK', 'QTY', 'CLOSE FROM → TO', 'P&L', 'PP OF NAV'].map((h, i) =>
                  <th key={h} style={{ textAlign: i < 1 ? 'left' : 'right', padding: '3px 6px', borderBottom: `1px solid ${T.border}` }}>{h}</th>)}</tr></thead>
                <tbody>{d.rows.map(r => (
                  <tr key={r.symbol} style={{ borderBottom: `1px solid ${T.border}` }}>
                    <td style={{ padding: '3px 6px' }}><TickerLink symbol={r.symbol} /></td>
                    <td style={{ padding: '3px 6px', textAlign: 'right', color: T.muted }}>{r.qty ?? '—'}</td>
                    <td style={{ padding: '3px 6px', textAlign: 'right', color: T.muted }}>{r.close_from?.toFixed(2) ?? '—'} → {r.close_to?.toFixed(2) ?? '—'}</td>
                    <td style={{ padding: '3px 6px', textAlign: 'right', color: (r.pnl_inr ?? 0) >= 0 ? T.green : T.red }}>{fmtInr(r.pnl_inr)}</td>
                    <td style={{ padding: '3px 6px', textAlign: 'right' }}>{pp(r.pp_of_nav)}</td>
                  </tr>))}
                  <tr><td colSpan={4} style={{ padding: '4px 6px', color: T.muted }}>book, sum of lots</td><td style={{ padding: '4px 6px', textAlign: 'right', fontWeight: 600 }}>{pp(d.book_pp)}</td></tr>
                </tbody>
              </table>
            )}
          </div>
          <div>
            <div style={{ fontSize: 10, letterSpacing: 1.2, color: T.muted, fontFamily: T.mono, marginBottom: 4, display: 'flex', gap: 6, alignItems: 'center' }}>
              NIFTY 50, SAME SESSIONS <BadgeChip badge={d.badges?.nifty ?? 'arithmetic'} /></div>
            {!nifty ? <div style={{ fontSize: 11, color: T.muted }}>No stored contribution rows for these sessions · backfill pending.</div> : (
              <div style={{ fontFamily: T.mono, fontSize: 11, display: 'grid', gap: 3 }}>
                {/* the percentage comes from the SAME window slice as the points (markets.py nifty_board),
                    because a points figure on a ~25,000 index says nothing on its own */}
                <div>index move <b style={{ color: T.text }}>{fmtPts(nifty.index_move_pts)}</b> pts
                  {nifty.index_move_pct == null ? '' : ` (${nifty.index_move_pct > 0 ? '+' : ''}${nifty.index_move_pct.toFixed(2)}%)`}
                  {' · members explain '}{fmtPts(nifty.explained_pts)}</div>
                <div style={{ color: T.muted }}>adds: {nifty.top5_add.filter(m => (m.points ?? 0) > 0).map(m => `${m.symbol} ${fmtPts(m.points, 0)}`).join(' · ') || '—'}</div>
                <div style={{ color: T.muted }}>drags: {nifty.top5_drag.filter(m => (m.points ?? 0) < 0).map(m => `${m.symbol} ${fmtPts(m.points, 0)}`).join(' · ') || '—'}</div>
              </div>
            )}
          </div>
        </div>
      )}
      {d && <div style={{ fontSize: 10, color: T.dim, marginTop: 6 }}>{d.note ?? ''}{d.note_rules ? ` · ${d.note_rules}` : ''} · describes, does not predict</div>}
    </Panel>
  )
}

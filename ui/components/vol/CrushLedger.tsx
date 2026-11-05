'use client'

/**
 * EVTS › results IV-crush ledger (reports/terminal_v2/PLAN.md 1.1 panel 5; precedent ORATS / Market Chameleon earnings):
 * per stock, the last 8 releases — IV 5 d and 1 d before, 1 d after, the crush %, the move the options implied against
 * the move that happened. The stock picker is the VOL screener's names with results inside 60 days, sorted by the next
 * results date, so the trader reads the names that report next. `context`: a measured ledger of the past, never a
 * forecast of the next crush. Describes, does not predict.
 */
import { useEffect, useMemo, useState } from 'react'
import { Chip, DataTable, Panel, T, TickerLink, fmtNum, sourceOf, type Column } from '@/components/terminal'
import { getIvEvents, getVolScreen, storeNote, type CrushRow, type IvEvents, type ScreenRow } from './api'

const pct = (v: number | null | undefined, d = 1) => (v == null || !Number.isFinite(v) ? '—' : `${fmtNum(v, d)}%`)
const signedPct = (v: number | null | undefined, d = 1) => (v == null || !Number.isFinite(v) ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(d)}%`)

export function CrushLedger({ initial }: { initial?: string | null }) {
  const [names, setNames] = useState<ScreenRow[] | null>(null)
  const [screenNote, setScreenNote] = useState<string | null>(null)
  const [symbol, setSymbol] = useState<string>(initial ?? '')
  const [d, setD] = useState<IvEvents | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    getVolScreen('iv_pctile', 60).then(r => {
      if (!alive) return
      const rows = [...r.data.rows].filter(x => x.next_results).sort((a, b) => String(a.next_results).localeCompare(String(b.next_results)))
      setNames(rows); setScreenNote(storeNote(r.data))
      setSymbol(s => s || rows[0]?.symbol || 'INFY')
    }).catch(() => { if (alive) { setNames([]); setSymbol(s => s || 'INFY') } })
    return () => { alive = false }
  }, [])
  useEffect(() => {
    if (!symbol) return
    let alive = true
    setD(null); setErr(null)
    getIvEvents(symbol, 8).then(r => { if (alive) setD(r.data) }).catch((e: unknown) => { if (alive) setErr(e instanceof Error ? e.message : 'unavailable') })
    return () => { alive = false }
  }, [symbol])
  const cols = useMemo<Column<CrushRow>[]>(() => [
    { key: 'released', label: 'Released', sort: r => r.released_at, render: r => <span style={{ fontFamily: T.mono }}>{r.released_at.slice(0, 16).replace('T', ' ')}</span> },
    { key: 'expiry', label: 'Expiry', render: r => <span style={{ color: T.muted }}>{r.expiry ?? '—'}</span> },
    { key: 'pre5', label: 'IV −5d', align: 'right', sort: r => r.iv_pre_5d ?? -1, render: r => pct(r.iv_pre_5d) },
    { key: 'pre1', label: 'IV −1d', align: 'right', sort: r => r.iv_pre_1d ?? -1, render: r => pct(r.iv_pre_1d) },
    { key: 'post1', label: 'IV +1d', align: 'right', sort: r => r.iv_post_1d ?? -1, render: r => pct(r.iv_post_1d) },
    { key: 'crush', label: 'Crush', align: 'right', sort: r => r.crush_pct ?? 0, title: '(IV +1d ÷ IV −1d − 1): how much of the IV came out after the release',
      render: r => <span style={{ fontWeight: 600 }}>{signedPct(r.crush_pct)}</span> },
    { key: 'implied', label: 'Implied move', align: 'right', sort: r => r.implied_move_pct ?? -1, title: 'what the ATM straddle priced for the release day', render: r => `±${pct(r.implied_move_pct)}` },
    { key: 'realised', label: 'Realised move', align: 'right', sort: r => Math.abs(r.realised_move_pct ?? 0), title: 'the close-to-close move on the release day (absolute)', render: r => pct(Math.abs(r.realised_move_pct ?? NaN)) },
    { key: 'ratio', label: 'Realised ÷ implied', align: 'right', sort: r => (r.implied_move_pct ? Math.abs(r.realised_move_pct ?? 0) / r.implied_move_pct : 0),
      render: r => (r.implied_move_pct ? `${fmtNum(Math.abs(r.realised_move_pct ?? 0) / r.implied_move_pct, 2)}×` : '—') },
  ], [])
  const picked = names?.find(n => n.symbol === symbol)
  const asOf = d?.rows?.[0]?.released_at?.slice(0, 10) ?? null
  return (
    <Panel title="Results IV crush · ledger" accent={T.violet} pad={0} badge={d?.badge ?? 'context'}
      source={sourceOf(asOf, { source: 'iv_event_log', maxAgeDays: 400, hint: d && !d.ok ? storeNote(d) : null })}
      subtitle={`last 8 releases per stock · IV before / after · priced vs realised move${picked?.next_results ? ` · ${symbol} reports next on ${picked.next_results}` : ''}`}
      right={<span style={{ display: 'inline-flex', gap: 4, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
        {(names ?? []).slice(0, 8).map(n => <Chip key={n.symbol} color={T.violet} active={symbol === n.symbol} onClick={() => setSymbol(n.symbol)} title={`results ${n.next_results ?? '—'}`}>{n.symbol}</Chip>)}
        <input value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase())} placeholder="F&O stock" aria-label="crush ledger symbol"
          style={{ background: T.panel, border: `1px solid ${T.border}`, color: T.text, fontFamily: T.mono, fontSize: 11, padding: '3px 6px', width: 96, outline: 'none', textTransform: 'uppercase' }} />
      </span>}>
      {screenNote && <div style={{ padding: '6px 12px', fontSize: 10.5, color: T.amber }}>VOL screener (the picker's names): {screenNote}</div>}
      {err && <div style={{ padding: '8px 12px', fontSize: 11, color: T.amber }}>Unavailable: {err}</div>}
      {d && !d.ok && <div style={{ padding: '8px 12px', fontSize: 11, color: T.muted }}>No crush ledger stored ({storeNote(d)}): <code>iv_event_log</code> is written by <code>iv_eod</code> from <code>nse_results</code> release times once the IV store is deployed.</div>}
      {d && d.ok && <DataTable columns={cols} rows={d.rows} rowKey={r => `${r.symbol}-${r.released_at}`} dense exportName={`EVTS_crush_${symbol}`}
        empty={<div style={{ padding: 12, fontSize: 11, color: T.muted }}>No measured releases for <TickerLink symbol={symbol} /> yet (the ledger starts with the first release after the store went live).</div>} />}
      {d && d.ok && d.rows.length > 0 && <div style={{ padding: '6px 12px', fontSize: 10, color: T.dim }}>{d.note}</div>}
    </Panel>
  )
}

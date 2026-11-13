'use client'

/**
 * The PAPER F&O book on OSTR (Terminal v2 PLAN 2.2, review M40, W2-BOOK): the structures booked with "Book paper",
 * each leg marked (NSE's live option chain in session — DELAYED, never LIVE — else the stored F&O bhavcopy close),
 * P&L gross / costs / net, net Δ Γ Θ ν per underlying and a ₹ total, and the close / roll helpers (preview first, an
 * in-page confirmation, then the paper write). PAPER ONLY: no order is sent anywhere; the routes write ui-api's SQLite.
 * Backend: GET /api/options/book, POST /api/options/book/close, POST /api/options/book/roll (routers/fo_book.py).
 */
import { useCallback, useEffect, useState } from 'react'
import { getOptionChain } from '@/lib/api'
import { apiError } from '@/lib/errors'
import { BadgeChip, Btn, Chip, ErrorBox, Input, Label, Loading, Notice, Panel, Select, T, fmtInr, type SourceInfo } from '@/components/terminal'
import { ScenarioStrip } from '@/components/risk/ScenarioStrip'
import { closeBook, confirmFills, confirmRoll, getBook, rollBook, type BookPayload, type BookPosition, type BookStructure, type ClosePreview, type RollPreview } from './api'

const n = (v: number | null | undefined, d = 2) => v == null || !Number.isFinite(v) ? '—' : v.toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d })
const pnlColor = (v: number | null | undefined) => v == null || v === 0 ? T.text : v > 0 ? T.green : T.red

/** the book's chip: DELAYED · NSE option chain in session (≈ 1 min behind), CLOSE · <bhavcopy date> after it */
export function bookSource(p: Pick<BookPayload, 'mark_source' | 'as_of' | 'open_positions'> | null): SourceInfo | null {
  if (!p) return null
  const m = p.mark_source
  if (m.state === 'delayed') return { state: 'delayed', source: 'NSE option chain', asOf: p.as_of, ageDays: 0, hint: 'in session, ≈ 1 min behind' }
  if (m.state === 'closed') return { state: 'closed', source: 'NSE F&O bhavcopy', asOf: m.as_of, ageDays: null, hint: 'end-of-day close (settlement price where untraded)' }
  return p.open_positions ? { state: 'offline', source: 'chain', asOf: null, ageDays: null, hint: 'no chain answered: stored marks only' }
    : { state: 'input', source: null, asOf: null, ageDays: null, hint: 'the book is empty' }
}

function GreeksTable({ g }: { g: BookPayload['greeks'] }) {
  const th = { color: T.dim, fontWeight: 400, textAlign: 'right' as const, padding: '3px 6px' }
  const td = { textAlign: 'right' as const, padding: '3px 6px', fontVariantNumeric: 'tabular-nums' as const }
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: T.mono, fontSize: 10.5 }} data-fobook-greeks>
      <thead><tr>
        <th style={{ ...th, textAlign: 'left' }}>Underlying</th><th style={th}>Δ units</th><th style={th}>Δ lots</th><th style={th}>₹ per 1 %</th>
        <th style={th} title="½·Γ·(1 % of the forward)²: the P&L a 1 % move adds through gamma">Γ P&L of 1 %</th><th style={th}>Θ ₹/day</th><th style={th}>ν ₹/vol pt</th>
      </tr></thead>
      <tbody>
        {g.by_underlying.map(u => (
          <tr key={u.symbol} style={{ borderTop: `1px solid ${T.border}` }}>
            <td style={{ ...td, textAlign: 'left', color: T.amber }}>{u.symbol} <span style={{ color: T.dim }}>({u.positions})</span></td>
            <td style={td}>{n(u.delta, 1)}</td><td style={td}>{n(u.delta_lots, 3)}</td><td style={td}>{fmtInr(u.delta_inr_per_1pct, 0)}</td>
            <td style={td}>{fmtInr(u.gamma_pnl_1pct_inr, 0)}</td><td style={td}>{fmtInr(u.theta_day, 0)}</td><td style={td}>{fmtInr(u.vega, 0)}</td>
          </tr>
        ))}
        <tr style={{ borderTop: `1px solid ${T.borderHi}` }} title={g.total_note}>
          <td style={{ ...td, textAlign: 'left', color: T.text }}>Total (₹ terms)</td><td style={td}>—</td><td style={td}>—</td>
          <td style={td}>{fmtInr(g.total.delta_inr_per_1pct, 0)}</td><td style={td}>{fmtInr(g.total.gamma_pnl_1pct_inr, 0)}</td>
          <td style={td}>{fmtInr(g.total.theta_day, 0)}</td><td style={td}>{fmtInr(g.total.vega, 0)}</td>
        </tr>
      </tbody>
    </table>
  )
}

function LegRow({ p, picked, onPick }: { p: BookPosition; picked: boolean; onPick: (id: number) => void }) {
  const mk = p.mark
  return (
    <tr style={{ borderTop: `1px solid ${T.border}`, opacity: p.status === 'open' ? 1 : 0.55 }}>
      <td style={{ padding: '3px 6px' }}>
        {p.status === 'open' ? <input type="checkbox" checked={picked} onChange={() => onPick(p.id)} aria-label={`pick position ${p.id}`} /> : <span style={{ color: T.dim }}>{p.status}</span>}
      </td>
      <td style={{ padding: '3px 6px', color: p.side === 'buy' ? T.green : T.red }}>{p.side.toUpperCase()}</td>
      <td style={{ padding: '3px 6px' }}>{p.kind} {p.strike ?? ''}</td>
      <td style={{ padding: '3px 6px', color: T.muted }}>{p.expiry}{p.days_to_expiry != null ? ` (${n(p.days_to_expiry, 1)}d)` : ''}</td>
      <td style={{ padding: '3px 6px', textAlign: 'right' }}>{p.lots}×{p.lot_size}</td>
      <td style={{ padding: '3px 6px', textAlign: 'right' }} title={p.entry_price_source}>{n(p.entry_price)}</td>
      <td style={{ padding: '3px 6px', textAlign: 'right' }} title={mk ? `${mk.price_source} · ${mk.mark_method}` : 'no mark'}>
        {p.status === 'open' ? (mk ? <>{n(mk.price)}{mk.mark_method === 'model' || mk.mark_method === 'expired-unsettled'
          ? <span style={{ color: T.violet }}> ᴴ</span> : mk.mark_method === 'settlement' ? <span style={{ color: T.cyan }}> ˢ</span> : null}</> : '—') : n(p.exit_price)}
      </td>
      <td style={{ padding: '3px 6px', textAlign: 'right', color: T.muted }}>{mk?.iv != null ? `${n(mk.iv, 2)}%` : '—'}</td>
      <td style={{ padding: '3px 6px', textAlign: 'right', color: pnlColor(p.status === 'open' ? p.pnl.unrealised : p.pnl.realised) }}>
        {fmtInr(p.status === 'open' ? p.pnl.unrealised : p.pnl.realised, 0)}</td>
      <td style={{ padding: '3px 6px', textAlign: 'right', color: T.muted }}>{p.status === 'open' ? n(p.greeks.delta, 1) : ''}</td>
      <td style={{ padding: '3px 6px', textAlign: 'right', color: T.muted }}>{p.status === 'open' ? fmtInr(p.greeks.theta_day, 0) : ''}</td>
    </tr>
  )
}

function StructureCard({ s, onChanged }: { s: BookStructure; onChanged: () => void }) {
  const [picked, setPicked] = useState<number[]>([])
  const [action, setAction] = useState<null | 'close' | 'roll'>(null)
  const [preview, setPreview] = useState<{ kind: 'close'; close: ClosePreview } | { kind: 'roll'; roll: RollPreview } | null>(null)
  const [expiries, setExpiries] = useState<string[]>([])
  const [toExp, setToExp] = useState('')
  const [shift, setShift] = useState('0')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const sm = s.summary
  const openIds = s.positions.filter(p => p.status === 'open').map(p => p.id)
  const expiredOnly = s.positions.filter(p => p.status === 'open')
    .every(p => p.mark?.mark_method === 'settlement' || p.mark?.mark_method === 'expired-unsettled')
  const ids = picked.length ? picked : openIds
  const toggle = (id: number) => setPicked(ps => ps.includes(id) ? ps.filter(x => x !== id) : [...ps, id])

  const askClose = async () => {
    setAction('close'); setErr(null); setBusy(true)
    try { const r = await closeBook({ position_ids: ids, preview: true }); setPreview({ kind: 'close', close: r.data }) }
    catch (e) { setErr(apiError(e)) } finally { setBusy(false) }
  }
  const openRoll = async () => {
    setAction('roll'); setErr(null); setPreview(null)
    try {
      const r = await getOptionChain(s.symbol)
      const later = r.data.expiries.filter(e => e > (sm.nearest_expiry ?? ''))
      setExpiries(later.slice(0, 6)); setToExp(later[0] ?? '')
    } catch (e) { setErr(apiError(e)) }
  }
  const askRoll = async () => {
    if (!toExp) return
    setErr(null); setBusy(true)
    try { const r = await rollBook({ position_ids: ids, to_expiry: toExp, strike_shift: Number(shift) || 0, preview: true }); setPreview({ kind: 'roll', roll: r.data }) }
    catch (e) { setErr(apiError(e)) } finally { setBusy(false) }
  }
  const confirm = async () => {
    if (!preview) return
    setBusy(true); setErr(null)
    try {
      // CONFIRM fills at the previewed prices, labelled with the preview's clock — never re-priced silently in session
      if (preview.kind === 'close') {
        await closeBook({ position_ids: preview.close.fills.map(f => f.position_id), confirm: confirmFills(preview.close.fills), previewed_at: preview.close.as_of })
      } else {
        await rollBook({ position_ids: preview.roll.legs.map(l => l.position_id), to_expiry: preview.roll.to_expiry, strike_shift: preview.roll.strike_shift,
                         confirm: confirmRoll(preview.roll.legs), previewed_at: preview.roll.as_of, preview: false })
      }
      setPreview(null); setAction(null); setPicked([]); onChanged()
    } catch (e) { setErr(apiError(e)) } finally { setBusy(false) }
  }

  return (
    <div style={{ border: `1px solid ${T.border}`, background: T.panel2, padding: 10, display: 'grid', gap: 8 }} data-fobook-structure={s.id}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <span style={{ color: T.amber, fontWeight: 600, fontFamily: T.mono, fontSize: 11 }}>#{s.id} {s.name}</span>
        <Chip color={T.violet}>PAPER</Chip>
        <span style={{ fontFamily: T.mono, fontSize: 10.5, color: T.muted }}>
          {sm.net_label} {fmtInr(Math.abs(sm.entry_cashflow), 0)} · P&L <span style={{ color: pnlColor(sm.pnl_gross) }}>{fmtInr(sm.pnl_gross, 0)}</span>
          {' '}− costs {fmtInr(sm.costs, 0)} = <span style={{ color: pnlColor(sm.pnl_net), fontWeight: 600 }}>{fmtInr(sm.pnl_net, 0)}</span>
          {sm.pct_of_max_profit != null && <> · {n(sm.pct_of_max_profit, 0)}% of max profit</>}
          {sm.loss_x_credit != null && <> · loss {n(sm.loss_x_credit, 2)}× the credit</>}
          {sm.nearest_expiry && <> · nearest expiry {sm.nearest_expiry}</>}
          {!sm.marks_complete && <span style={{ color: T.amber }}> · some legs unmarked</span>}
        </span>
        <BadgeChip badge="arithmetic" note="P&L = (mark − fill) × units, costs from the NSE F&O statutory schedule (estimate)" />
        <span style={{ flex: 1 }} />
        {s.status === 'open' && <>
          <Btn size="sm" onClick={askClose} disabled={busy}>CLOSE{picked.length ? ` ${picked.length}` : ''}</Btn>
          {/* an expired leg settles, it cannot be rolled (the route refuses it too) */}
          {!expiredOnly && <Btn size="sm" onClick={openRoll} disabled={busy}>ROLL{picked.length ? ` ${picked.length}` : ''}</Btn>}
        </>}
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: T.mono, fontSize: 10.5 }}>
          <thead><tr style={{ color: T.dim }}>
            <th /><th style={{ textAlign: 'left', fontWeight: 400 }}>Side</th><th style={{ textAlign: 'left', fontWeight: 400 }}>Contract</th>
            <th style={{ textAlign: 'left', fontWeight: 400 }}>Expiry</th><th style={{ fontWeight: 400, textAlign: 'right' }}>Lots</th>
            <th style={{ fontWeight: 400, textAlign: 'right' }}>Fill</th><th style={{ fontWeight: 400, textAlign: 'right' }} title="ᴴ = heuristic: a model mark (strike outside the chain's window) or an expired contract whose expiry-day close is not stored yet; ˢ = NSE's final settlement (intrinsic on the underlying's close on the expiry day)">Mark</th>
            <th style={{ fontWeight: 400, textAlign: 'right' }}>IV</th><th style={{ fontWeight: 400, textAlign: 'right' }}>P&L</th>
            <th style={{ fontWeight: 400, textAlign: 'right' }}>Δ</th><th style={{ fontWeight: 400, textAlign: 'right' }}>Θ/day</th>
          </tr></thead>
          <tbody>{s.positions.map(p => <LegRow key={p.id} p={p} picked={picked.includes(p.id)} onPick={toggle} />)}</tbody>
        </table>
      </div>
      {action === 'roll' && !preview && (
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }} data-fobook-roll>
          <Select label="Roll to" value={toExp} onChange={setToExp} options={expiries.map(e => ({ value: e, label: e }))} />
          <Input label="Strike shift (pts)" value={shift} width={90} onChange={setShift} aria-label="strike shift" />
          <Btn size="sm" onClick={askRoll} disabled={busy || !toExp}>PRICE THE ROLL</Btn>
          <Btn size="sm" onClick={() => setAction(null)}>CANCEL</Btn>
          <Label>{picked.length ? `${picked.length} picked leg(s)` : 'every open leg'} · same side, kind and lots on the new expiry, priced from its chain</Label>
        </div>
      )}
      {preview && (
        <Notice color={T.cyan}>
          <div style={{ display: 'grid', gap: 4 }} data-fobook-confirm={preview.kind}>
            {preview.kind === 'close'
              ? <>
                  <div>Close {preview.close.fills.length} leg(s) on PAPER: {preview.close.fills.map(f => `#${f.position_id} at ${n(f.exit_price)}`).join(' · ')}.</div>
                  <div style={{ color: T.muted, fontSize: 10 }}>{[...new Set(preview.close.fills.map(f => f.exit_price_source))].join(' · ')}</div>
                </>
              : <>
                  <div>Roll to {preview.roll.to_expiry}{preview.roll.strike_shift ? ` (strikes ${preview.roll.strike_shift > 0 ? '+' : ''}${preview.roll.strike_shift})` : ''}: net {preview.roll.net_label} {fmtInr(Math.abs(preview.roll.net_cash), 0)}, costs {fmtInr(preview.roll.costs, 0)}.</div>
                  <div style={{ color: T.muted, fontSize: 10 }}>{preview.roll.legs.map(l => `#${l.position_id}: close ${n(l.close_at)} → open ${l.new_strike ?? 'FUT'} at ${n(l.open_at)}`).join(' · ')}</div>
                </>}
            <div style={{ color: T.dim, fontSize: 10 }} data-fobook-preview-clock>
              CONFIRM fills at these previewed prices (as of {(preview.kind === 'close' ? preview.close.as_of : preview.roll.as_of)?.slice(11, 16) ?? '—'} IST), labelled so — not re-priced
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <Btn size="sm" variant="primary" onClick={confirm} disabled={busy}>CONFIRM (PAPER)</Btn>
              <Btn size="sm" onClick={() => { setPreview(null); setAction(null) }}>CANCEL</Btn>
            </div>
          </div>
        </Notice>
      )}
      {err && <ErrorBox error={err} />}
    </div>
  )
}

export function PaperBook({ refreshKey }: { refreshKey?: number }) {
  const [data, setData] = useState<BookPayload | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [showAll, setShowAll] = useState(false)
  const load = useCallback(() => {
    let alive = true
    setLoading(true)
    getBook(showAll ? 'all' : 'open').then(r => { if (alive) { setData(r.data); setErr(null) } })
      .catch(e => { if (alive) setErr(e?.response?.status === 404 ? 'the paper F&O book is not on this ui-api yet (deploy pending)' : apiError(e)) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [showAll])
  useEffect(() => load(), [load, refreshKey])

  return (
    <Panel title="Paper F&O book" accent={T.violet} badge="arithmetic" source={bookSource(data)}
      subtitle={data ? `${data.open_positions} open leg(s) · marks ${data.marks_meta.used === 'live' ? 'from NSE\'s option chain in session' : 'at the stored F&O bhavcopy close'} · PAPER ONLY` : 'PAPER ONLY'}
      right={<div style={{ display: 'flex', gap: 6 }}>
        <Chip color={T.muted} active={showAll} onClick={() => setShowAll(v => !v)}>{showAll ? 'OPEN + CLOSED' : 'OPEN'}</Chip>
        <Btn size="sm" onClick={load}>{loading ? '…' : '↻'}</Btn>
      </div>}>
      {err && <ErrorBox error={err} onRetry={load} />}
      {!data && !err && <Loading label="paper book" />}
      {data && (
        <div style={{ display: 'grid', gap: 10 }}>
          {data.structures.length === 0
            ? <Notice color={T.muted}>No paper structures yet. Build one above and press <b>BOOK PAPER</b>: the legs are written to this book (ui-api&apos;s SQLite) at the prices shown — no order is sent anywhere.</Notice>
            : <>
                {/* risk/SPEC.md §4: scenario strip over the open book (reads /api/risk/fo itself; hides when empty) */}
                {data.open_positions > 0 && <ScenarioStrip />}
                <GreeksTable g={data.greeks} />
                <div style={{ fontFamily: T.mono, fontSize: 10.5, color: T.muted }}>
                  Book P&L <span style={{ color: pnlColor(data.totals.pnl_gross) }}>{fmtInr(data.totals.pnl_gross, 0)}</span> − costs {fmtInr(data.totals.costs, 0)} =
                  {' '}<span style={{ color: pnlColor(data.totals.pnl_net), fontWeight: 600 }}>{fmtInr(data.totals.pnl_net, 0)}</span>
                  {' '}(realised {fmtInr(data.totals.pnl_realised, 0)}) · Greeks at {data.time_convention}
                </div>
                {data.structures.map(s => <StructureCard key={s.id} s={s} onChanged={load} />)}
              </>}
          {data.marks_meta.notes.map((t, i) => <div key={i} style={{ fontSize: 10, color: T.amber }}>⚠ {t}</div>)}
          <div style={{ fontSize: 10, color: T.dim, lineHeight: 1.5 }}>{data.note}. Risk of this book (delta-gamma VaR, IV shocks, gaps, SPAN margin): RSK › F&amp;O.</div>
        </div>
      )}
    </Panel>
  )
}

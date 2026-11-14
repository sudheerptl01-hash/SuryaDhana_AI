'use client'

/**
 * MCXG › paper futures book (FINAL ROUND R5-FUTBOOK): the explicit BOOK PAPER action behind the ticket.
 *
 * The ticket above PRICES the trade and records nothing — that contract is unchanged. This panel is the separate,
 * explicit action (like OSTR's "Book paper"): it writes the ticket's fill into ui-api's paper futures book
 * (SQLite, PAPER ONLY at the database level), marks it daily from the STORED settlement reads
 * (settlement_source labelled: Breeze last-30-min VWAP, MCX's DSP method, else the ICICI band midpoint), settles an
 * expired contract at the stored settlement of record on its expiry session, and records realised money net of the
 * recorded costs at the close. Arithmetic only — the book describes, does not predict. No order API exists here.
 *
 * Data: /api/mcx/book (services/ui-api/routers/fut_book.py + fut_book_store.py).
 */
import { useCallback, useEffect, useState } from 'react'
import { BadgeChip, Btn, Chip, DataTable, Notice, Panel, Select, Stat, T,
         fmtInr, type Column, inputSource } from '@/components/terminal'
import { fmtSignedInr } from '@/lib/format'

interface Mark { price: number; as_of: string; source: string; session: string | null; quality: string | null }
interface OpenRow {
  id: number; family: string; expiry: string; side: 'buy' | 'sell'; lots: number; multiplier: number
  unit: string | null; entry_price: number; entry_price_source: string; entry_costs: number; opened_at: string
  expired: boolean; state: string; mark: Mark | null
  unrealised_inr: number | null; day_mtm_inr: number | null; day_mtm_basis: string | null
}
interface ClosedRow {
  id: number; family: string; expiry: string; side: 'buy' | 'sell'; lots: number
  entry_price: number; exit_price: number | null; exit_price_source: string | null; exit_kind: string | null
  closed_at: string | null
  realised: { gross_inr: number; costs_inr: number; realised_inr: number; basis: string } | null
}
interface BookPayload {
  paper: boolean; badge: string; as_of: string
  open: OpenRow[]; closed: ClosedRow[]
  totals: { open_unrealised_inr: number; unmarked: number; realised_inr: number; realised_gross_inr: number; costs_inr: number }
  notes: string[]
}

async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init)
  const body = await r.json().catch(() => null)
  if (!r.ok) {
    const msg = body?.error?.message ?? (typeof body?.detail === 'string' ? body.detail : null)
    throw new Error(msg ?? `HTTP ${r.status}`)
  }
  return body as T
}
const post = (url: string, body?: unknown) =>
  api(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body ?? {}) })

export interface FutBookProps {
  /** the ticket as currently filled in (the booking uses exactly what the ticket shows) */
  contract: string
  expiry: string | null            // the RESOLVED expiry (the quote's), never '' = front
  lots: number
  price: number | null
  priceSource: string | null
  brokerage: number
}

export function FutBook({ contract, expiry, lots, price, priceSource, brokerage }: FutBookProps) {
  const [book, setBook] = useState<BookPayload | null>(null)
  const [side, setSide] = useState<'buy' | 'sell'>('buy')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)

  const load = useCallback(async () => {
    try { setBook(await api<BookPayload>('/api/mcx/book')) } catch (e: unknown) { setErr(e instanceof Error ? e.message : 'book unavailable') }
  }, [])
  const refreshMarks = useCallback(async () => {
    // marks only — a page view never closes a position (F5, 14 Nov 2026); SETTLE below is the explicit action
    try { await post('/api/mcx/book/mark') } catch { /* stored reads may be empty on a fresh install — the book still renders */ }
    await load()
  }, [load])
  useEffect(() => { refreshMarks() }, [refreshMarks])

  const act = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true); setErr(null); setNote(null)
    try { await fn(); setNote(done); await refreshMarks() } catch (e: unknown) { setErr(e instanceof Error ? e.message : 'refused') }
    setBusy(false)
  }
  const bookPaper = () => act(() => post('/api/mcx/book', {
    contract, expiry, side, lots, price, price_source: priceSource ?? 'desk price', brokerage_per_order: brokerage, mode: 'paper',
    context: { ticket: { contract, expiry, lots, price, price_source: priceSource, brokerage_per_order: brokerage } },
  }), 'booked into the paper futures book')
  const closeAt = (pid: number) => act(() => post('/api/mcx/book/close', { position_ids: [pid], mode: 'paper' }),
    'closed at the stored mark')

  const canBook = !!price && !!expiry && !busy
  const openCols: Column<OpenRow>[] = [
    { key: 'contract', label: 'Contract', render: r => <span style={{ color: T.text, fontWeight: 600 }}>{r.family} <span style={{ color: T.dim }}>{r.expiry}</span></span> },
    { key: 'side', label: 'Side', render: r => <span style={{ color: r.side === 'buy' ? T.green : T.red, fontWeight: 600 }}>{r.side.toUpperCase()}</span> },
    { key: 'lots', label: 'Lots', align: 'right', render: r => <span style={{ color: T.text }}>{r.lots}</span> },
    { key: 'entry', label: 'Entry', align: 'right', render: r => <span style={{ color: T.text }} title={`${r.entry_price_source} · entry-side costs ${fmtInr(r.entry_costs, 2)} (recorded)`}>{fmtInr(r.entry_price, 1)}</span> },
    { key: 'mark', label: 'Mark', align: 'right', render: r => r.mark
        ? <span style={{ color: T.text }} title={`${r.mark.source}${r.mark.quality ? ` (${r.mark.quality})` : ''} · session ${r.mark.session ?? r.mark.as_of}`}>{fmtInr(r.mark.price, 1)} <span style={{ color: T.dim }}>{r.mark.as_of.slice(5)}</span></span>
        : <span style={{ color: T.amber }} title={r.expired ? 'expired: its expiry session’s settlement of record is not stored yet' : 'no stored settlement read yet'}>{r.expired ? 'UNSETTLED' : 'unmarked'}</span> },
    { key: 'day', label: 'Day MTM', align: 'right', render: r => r.day_mtm_inr == null ? <span style={{ color: T.dim }}>—</span>
        : <span style={{ color: r.day_mtm_inr >= 0 ? T.green : T.red }} title={r.day_mtm_basis ?? undefined}>{fmtSignedInr(r.day_mtm_inr)}</span> },
    { key: 'unreal', label: 'Unrealised', align: 'right', render: r => r.unrealised_inr == null ? <span style={{ color: T.dim }}>—</span>
        : <span style={{ color: r.unrealised_inr >= 0 ? T.green : T.red, fontWeight: 600 }} title="gross of exit-side costs (arithmetic)">{fmtSignedInr(r.unrealised_inr)}</span> },
    { key: 'act', label: '', align: 'right', render: r => (
        <Btn size="sm" disabled={busy || !r.mark || r.expired} onClick={() => closeAt(r.id)}
          title={r.expired ? 'an expired contract settles at the stored settlement of record, not a close' : 'close at the latest stored mark (its source is recorded in the fill)'}>CLOSE @ MARK</Btn>) },
  ]
  const closedCols: Column<ClosedRow>[] = [
    { key: 'contract', label: 'Contract', render: r => <span style={{ color: T.text }}>{r.family} <span style={{ color: T.dim }}>{r.expiry}</span></span> },
    { key: 'side', label: 'Side', render: r => <span style={{ color: r.side === 'buy' ? T.green : T.red }}>{r.side.toUpperCase()}</span> },
    { key: 'lots', label: 'Lots', align: 'right', render: r => <span style={{ color: T.text }}>{r.lots}</span> },
    { key: 'fill', label: 'Entry → Exit', align: 'right', render: r => <span style={{ color: T.text }} title={r.exit_price_source ?? undefined}>{fmtInr(r.entry_price, 1)} → {fmtInr(r.exit_price, 1)}</span> },
    { key: 'kind', label: 'How', render: r => <Chip color={r.exit_kind === 'settle' ? T.violet : T.cyan}>{r.exit_kind === 'settle' ? 'SETTLED' : 'CLOSED'}</Chip> },
    { key: 'real', label: 'Realised (net)', align: 'right', render: r => r.realised == null ? <span style={{ color: T.dim }}>—</span>
        : <span style={{ color: r.realised.realised_inr >= 0 ? T.green : T.red, fontWeight: 700 }}
            title={`gross ${fmtSignedInr(r.realised.gross_inr)} − costs ${fmtInr(r.realised.costs_inr, 2)} · ${r.realised.basis} · recorded at the close, never recomputed`}>{fmtSignedInr(r.realised.realised_inr)}</span> },
    { key: 'when', label: 'Closed', align: 'right', render: r => <span style={{ color: T.dim }}>{(r.closed_at ?? '').slice(0, 16)}</span> },
  ]

  const t = book?.totals
  const hasExpired = (book?.open ?? []).some(r => r.expired)   // F5: drives the explicit SETTLE action
  return (
    <Panel source={inputSource('the paper futures book (ui-api SQLite, PAPER ONLY)')} title="Paper futures book" accent={T.violet}
      badge="arithmetic"
      subtitle="the explicit BOOK PAPER action — daily MTM from the stored settlement reads (source labelled) · the ticket above still records nothing"
      right={<Chip color={T.violet}>PAPER</Chip>}
      bodyStyle={{ display: 'grid', gap: 10 }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'end', flexWrap: 'wrap' }}>
        <Select label="Side" value={side} onChange={s => setSide(s)} options={[{ value: 'buy', label: 'BUY' }, { value: 'sell', label: 'SELL' }]} />
        <div style={{ fontFamily: T.mono, fontSize: 11, color: T.text }}>
          {contract} {expiry ?? '—'} · {lots} lot{lots === 1 ? '' : 's'} @ {price ? fmtInr(price, 1) : '—'}
          <span style={{ color: T.dim }}> · {priceSource ?? 'no price source yet'}</span>
        </div>
        <Btn variant="go" disabled={!canBook} onClick={bookPaper}
          title={canBook ? 'write this fill into the paper futures book (an explicit action; the ticket itself records nothing)' : 'needs a desk price and a resolved expiry'}>
          BOOK PAPER</Btn>
        <Btn size="sm" disabled={busy} onClick={() => act(async () => {}, 'marks refreshed from the stored settlement reads')}
          title="re-read the stored settlement reads and append today's marks (idempotent)">MARK</Btn>
        {/* F5 (14 Nov 2026): closing an expired contract is an EXPLICIT action — the mount only marks */}
        <Btn size="sm" disabled={busy || !hasExpired}
          onClick={() => act(() => post('/api/mcx/book/mark?settle=true'),
            'expired contracts settled at their stored settlement of record')}
          title={hasExpired
            ? 'close every expired contract at its stored MCX settlement of record (the exit price and its source are recorded in the fill)'
            : 'nothing in the book has expired'}>SETTLE EXPIRED</Btn>
      </div>
      {err && <Notice color={T.red}>{err}</Notice>}
      {note && !err && <div style={{ fontSize: 10, color: T.green }}>{note}</div>}
      {t && (
        <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))' }}>
          <Stat label="Open unrealised" value={fmtSignedInr(t.open_unrealised_inr)} big={false}
            color={t.open_unrealised_inr >= 0 ? T.green : T.red} accent={T.violet}
            sub={t.unmarked ? `${t.unmarked} position${t.unmarked === 1 ? '' : 's'} unmarked` : 'gross of exit-side costs'} />
          <Stat label="Realised (net of costs)" value={fmtSignedInr(t.realised_inr)} big={false}
            color={t.realised_inr >= 0 ? T.green : T.red} accent={T.cyan}
            sub={`gross ${fmtSignedInr(t.realised_gross_inr)} − costs ${fmtInr(t.costs_inr, 2)}`} />
        </div>
      )}
      <DataTable columns={openCols} rows={book?.open ?? []} rowKey={r => String(r.id)} dense
        empty="No open paper futures positions — BOOK PAPER writes the ticket's fill here." />
      {(book?.closed?.length ?? 0) > 0 && (
        <DataTable columns={closedCols} rows={book?.closed ?? []} rowKey={r => String(r.id)} dense empty="" />
      )}
      <div style={{ fontSize: 10, color: T.dim, lineHeight: 1.5, display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <BadgeChip badge="arithmetic" />
        <span>
          PAPER ONLY — no order API exists on this desk. Marks are the stored settlement reads (Breeze last-30-min VWAP,
          MCX&rsquo;s DSP method, else the ICICI band midpoint, each labelled with its real session); an expired contract
          settles at the stored settlement of record on its expiry session. The book describes, does not predict.
        </span>
      </div>
    </Panel>
  )
}

export default FutBook

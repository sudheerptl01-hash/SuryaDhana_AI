'use client'

/**
 * FOBK › JOURNAL (E-JRNL, F-12): the paper book's append-only action log with the point-in-time context captured
 * at each action (GET /api/options/book/journal, routers/fo_book.py). A booking / close journals the market snapshot
 * taken AT the action — spot, IV30 (constant maturity) with its percentile and rank, IV30 − RV20, DTE — and a booking
 * also carries the OSTR checklist payload as sent (ticks, max-loss typed, margin + its source). Everything shown here
 * is the recorded fact, never recomputed against moved marks. PAPER ONLY: this log names no order route.
 */
import { useCallback, useEffect, useState } from 'react'
import client from '@/lib/api'
import { apiError } from '@/lib/errors'
import { Btn, Chip, ErrorBox, Loading, Notice, Panel, T, fmtInr } from '@/components/terminal'
import { inputSource } from '@/components/terminal/source'

// the route's own definitions (routers/derivatives.py DEFINITIONS — G9.1: rank and percentile are different numbers,
// each defined on hover wherever one is printed; the journal snapshot stores the numbers, these name them)
const definitions = {
  iv_pctile_252: "IV percentile: the share of the past 252 sessions whose iv30_cm was below today's.",
  iv_rank_252: "IV rank: where today's iv30_cm sits between its 252-session minimum (0) and maximum (100).",
}

interface JournalFill {
  position_id: number; symbol?: string; exit_price?: number
  realised_inr?: number | null; gross_inr?: number | null; costs_inr?: number | null
}
interface MarketCtx {
  symbol?: string; captured_at?: string; dte_days?: number | null; nearest_expiry?: string | null; note?: string
  iv?: {
    date?: string | null; spot?: number | null; iv30_cm?: number | null; iv_pctile_252?: number | null
    iv_rank_252?: number | null; iv_minus_rv20?: number | null; source?: string
  } | null
}
interface ClientCtx {
  ticked?: number; total?: number; max_loss_inr?: number | null
  margin_total?: number | null; margin_source?: string | null; event_hint?: string | null; note?: string
}
interface JournalCtx { market?: MarketCtx; client?: ClientCtx }
export interface JournalRow {
  id: number; ts: string; action: string; structure_id: number | null
  payload: { name?: string; symbol?: string; fills?: JournalFill[]; context?: JournalCtx; [k: string]: unknown }
}

const ACTION_COLOR: Record<string, string> = { book: T.amber, close: T.cyan, settle: T.cyan, roll: T.violet }
const nf = (v: number | null | undefined, d = 1) =>
  v == null || !Number.isFinite(v) ? '—' : v.toLocaleString('en-IN', { maximumFractionDigits: d })
const pnlColor = (v: number | null | undefined) => v == null || v === 0 ? T.text : v > 0 ? T.green : T.red

/** the context chips of one journal row — recorded facts, every chip neutral (never a directional colour) */
function CtxChips({ ctx }: { ctx: JournalCtx | undefined }) {
  if (!ctx || (!ctx.market && !ctx.client)) {
    return <span style={{ color: T.dim, fontSize: 9.5 }}>no context recorded with this row (pre-journal-context, or a settlement — its context is the settlement itself)</span>
  }
  const m = ctx.market
  const c = ctx.client
  const iv = m?.iv
  const chips: { key: string; text: string; title?: string }[] = []
  if (iv?.spot != null) chips.push({ key: 'spot', text: `SPOT ${nf(iv.spot, 1)}`, title: `stored EOD summary ${iv.date ?? ''} · ${iv.source ?? ''}` })
  if (iv?.iv30_cm != null) {
    chips.push({
      key: 'iv', text: `IV30 ${nf(iv.iv30_cm, 2)}%${iv.iv_pctile_252 != null ? ` · pctile ${nf(iv.iv_pctile_252, 0)}` : ''}${iv.iv_rank_252 != null ? ` · rank ${nf(iv.iv_rank_252, 0)}` : ''}`,
      title: `IV30 constant maturity as stored (${iv.date ?? '—'}). ${definitions.iv_pctile_252} ${definitions.iv_rank_252}`,
    })
  }
  if (iv?.iv_minus_rv20 != null) chips.push({ key: 'ivrv', text: `IV−RV ${iv.iv_minus_rv20 > 0 ? '+' : ''}${nf(iv.iv_minus_rv20, 1)}`, title: 'IV30 − RV20 (close-to-close), as stored at capture' })
  if (m?.dte_days != null) chips.push({ key: 'dte', text: `DTE ${nf(m.dte_days, 1)}d`, title: `calendar days to the nearest expiry (${m.nearest_expiry ?? '—'}) at the action` })
  if (c?.ticked != null && c?.total != null) chips.push({ key: 'chk', text: `CHECKLIST ${c.ticked}/${c.total}`, title: 'the OSTR pre-trade checklist as sent with the booking (it never gates anything)' })
  if (c?.max_loss_inr != null) chips.push({ key: 'loss', text: `MAX LOSS ${fmtInr(c.max_loss_inr, 0)}`, title: 'the max loss the owner typed on the checklist at booking' })
  if (c?.margin_total != null) chips.push({ key: 'mgn', text: `MARGIN ${fmtInr(c.margin_total, 0)}${c.margin_source ? ` · ${c.margin_source}` : ''}`, title: 'the margin shown at booking, with its source' })
  if (c?.event_hint) chips.push({ key: 'evt', text: `EVENT ${c.event_hint}`.slice(0, 60), title: c.event_hint })
  if (m?.note) chips.push({ key: 'note', text: '◌ partial capture', title: m.note })
  if (!chips.length) return <span style={{ color: T.dim, fontSize: 9.5 }}>context captured, nothing stored for it{m?.note ? ` — ${m.note}` : ''}</span>
  return (
    <span style={{ display: 'inline-flex', gap: 4, flexWrap: 'wrap' }}>
      {chips.map(ch => <Chip key={ch.key} color={T.muted} title={ch.title} style={{ fontSize: 9, padding: '1px 5px' }}>{ch.text}</Chip>)}
    </span>
  )
}

function rowRealised(r: JournalRow): number | null {
  if (r.action !== 'close' && r.action !== 'settle') return null
  const fills = r.payload.fills ?? []
  if (!fills.length || fills.some(f => f.realised_inr == null)) return null
  return fills.reduce((a, f) => a + (f.realised_inr ?? 0), 0)
}

export function Journal({ refreshKey }: { refreshKey?: number }) {
  const [rows, setRows] = useState<JournalRow[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const load = useCallback(() => {
    let alive = true
    setLoading(true)
    client.get<{ rows: JournalRow[]; paper_only: true }>('/api/options/book/journal', { params: { limit: 200 }, timeout: 20_000 })
      .then(r => { if (alive) { setRows(r.data.rows); setErr(null) } })
      .catch(e => { if (alive) setErr(apiError(e)) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [])
  useEffect(() => load(), [load, refreshKey])

  return (
    <Panel title="Journal" accent={T.violet} badge="arithmetic"
      source={inputSource('your own paper actions, journalled append-only (ui-api SQLite) with the context recorded at each one')}
      subtitle="the paper book's action log with the context captured at each action — point-in-time, never recomputed · PAPER ONLY"
      right={<Btn size="sm" onClick={load}>{loading ? '…' : '↻'}</Btn>}>
      {err && <ErrorBox error={err} onRetry={load} />}
      {!rows && !err && <Loading label="journal" />}
      {rows && rows.length === 0 && <Notice color={T.muted}>No actions journalled yet. Booking, closing or rolling a paper structure writes a row here with its context.</Notice>}
      {rows && rows.length > 0 && (
        <div style={{ display: 'grid', gap: 6 }} data-fobook-journal>
          {rows.map(r => {
            const realised = rowRealised(r)
            return (
              <div key={r.id} style={{ display: 'grid', gap: 3, padding: '6px 8px', border: `1px solid ${T.border}`, background: T.panel2 }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', fontFamily: T.mono, fontSize: 10.5 }}>
                  <span style={{ color: T.dim }}>{String(r.ts).slice(0, 16).replace('T', ' ')}</span>
                  <Chip color={ACTION_COLOR[r.action] ?? T.muted} style={{ fontSize: 9, padding: '1px 6px' }}>{r.action.toUpperCase()}</Chip>
                  <span style={{ color: T.amber }}>
                    {r.payload.symbol ?? (r.payload.fills?.[0]?.symbol as string | undefined) ?? ''}
                    {r.payload.name ? <span style={{ color: T.muted }}> {r.payload.name}</span> : null}
                    {r.structure_id != null ? <span style={{ color: T.dim }}> #{r.structure_id}</span> : null}
                  </span>
                  {realised != null && (
                    <span style={{ color: pnlColor(realised) }} title="the realised ₹ recorded with this close, net of the recorded costs (never recomputed)">
                      realised {fmtInr(realised, 0)}
                    </span>
                  )}
                  {(r.action === 'close' || r.action === 'settle') && realised == null && (r.payload.fills?.length ?? 0) > 0 && (
                    <span style={{ color: T.dim }} title="this close predates the recorded-realised build; the day read derives it from the stored fills where it can">realised: recorded from later closes</span>
                  )}
                </div>
                {(r.action === 'book' || r.action === 'close' || r.action === 'settle' || r.action === 'roll') && <CtxChips ctx={r.payload.context} />}
              </div>
            )
          })}
          <div style={{ fontSize: 10, color: T.dim }}>
            Context is captured at the action (stored EOD IV summary + the checklist as sent) and stored with the row — it describes that moment, it does not predict.
          </div>
        </div>
      )}
    </Panel>
  )
}

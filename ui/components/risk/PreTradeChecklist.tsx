'use client'

/**
 * Pre-trade checklist card on OSTR (risk/SPEC.md §5) — four items beside "Book paper", each with its data read
 * and an honest auto-state where one exists; the ticks are the owner's own. B-OSTR mounts it as
 * `<PreTradeChecklist symbol={...} onPayload={...} />` and passes the payload into the booking call's journal
 * note. The card NEVER gates the Book button (O-F3: never blocks); an unticked checklist books with the journal
 * note `checklist: 2/4`.
 *
 * Items:
 *  1. Event risk known — upcoming entries from the IV event log (GET /api/derivatives/iv/{symbol}: `events`);
 *     facts only ("results 2026-11-15"), manual tick.
 *  2. IV level seen — IV30 + percentile/rank auto-filled from the same read; the tick confirms the owner looked.
 *  3. Max loss typed — a ₹ input, compared (arithmetic) to what is left under the daily cap today; stored into
 *     the booking's journal payload.
 *  4. Margin known — auto-filled when the mount passes the margin block's answer (`margin` prop); else the tick
 *     confirms the owner read the MARGIN block above.
 *
 * State lives in `suryadhana.risk.checklist.v1` (one key, rewritten per session; items per symbol).
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { BadgeChip, Chip, Label, T } from '@/components/terminal'
import { getIvHistory } from '@/components/vol/api'
import {
  EMPTY_ITEMS, checklistNote, inr, maxLossLine, parseChecklist, remainingCap, serializeChecklist, tickedCount,
  type ChecklistItems,
} from './disciplineModel'
import { saveChecklistRaw, useDiscipline } from './useDiscipline'

export interface ChecklistPayload {
  session: string
  symbol: string
  ticked: number
  total: 4
  items: { event: boolean; iv: boolean; max_loss: boolean; margin: boolean }
  max_loss_inr: number | null
  /** the journal note an unticked checklist books with, e.g. "checklist: 2/4" */
  note: string
  iv30_cm?: number | null
  iv_pctile_252?: number | null
  event_hint?: string | null
  margin_total?: number | null
  margin_source?: string | null
}

export interface MarginHint { total: number | null; source: string; asOf?: string | null }

interface IvHint {
  iv30: number | null; pctile: number | null; rank: number | null; asOf: string | null
  events: { date: string; kind: string }[]
  /** the route's own definitions (G9.1: rank and percentile are different numbers, each defined on hover) */
  defPct: string | null; defRank: string | null
}

function istToday(): string {
  return new Date(Date.now() + 330 * 60_000).toISOString().slice(0, 10)
}

export function PreTradeChecklist({ symbol, onPayload, margin }: {
  symbol: string
  onPayload: (p: ChecklistPayload) => void
  /** the margin block's last answer, when the mount has one (optional — item 4 stays a manual tick without it) */
  margin?: MarginHint | null
}) {
  const d = useDiscipline()
  const sym = symbol.trim().toUpperCase()
  const state = useMemo(() => parseChecklist(d.checklistRaw, d.session), [d.checklistRaw, d.session])
  const items: ChecklistItems = state.items[sym] ?? { ...EMPTY_ITEMS }
  const [lossText, setLossText] = useState(items.max_loss_inr != null ? String(items.max_loss_inr) : '')
  const [open, setOpen] = useState(true)
  const [doneAt, setDoneAt] = useState<string | null>(null)
  const [iv, setIv] = useState<IvHint | null>(null)
  const alive = useRef(true)
  const lossTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // one IV read powers items 1 + 2 (facts only; the ticks stay the owner's)
  useEffect(() => {
    alive.current = true
    setIv(null)
    getIvHistory(sym, 40).then(r => {
      if (!alive.current) return
      const rows = r.data?.rows ?? []
      const last = rows.length ? rows[rows.length - 1] : null
      const today = istToday()
      const events = (r.data?.events ?? []).filter(e => typeof e?.date === 'string' && e.date >= today).slice(0, 3)
      setIv({ iv30: last?.iv30_cm ?? null, pctile: r.data?.rank?.iv_pctile_252 ?? null, rank: r.data?.rank?.iv_rank_252 ?? null,
              asOf: r.data?.as_of ?? null, events,
              defPct: r.data?.definitions?.iv_pctile_252 ?? null, defRank: r.data?.definitions?.iv_rank_252 ?? null })
    }).catch(() => { if (alive.current) setIv(null) })
    return () => { alive.current = false }
  }, [sym])

  // the symbol's stored max loss follows a symbol switch
  useEffect(() => { setLossText(items.max_loss_inr != null ? String(items.max_loss_inr) : '') }, [sym, d.session])  // eslint-disable-line react-hooks/exhaustive-deps

  const write = (next: ChecklistItems) => {
    const nextState = { session: d.session, items: { ...state.items, [sym]: next } }
    saveChecklistRaw(serializeChecklist(nextState))
    if (tickedCount(next) === 4 && tickedCount(items) < 4) {
      setDoneAt(new Date(Date.now() + 330 * 60_000).toISOString().slice(11, 16))
      setOpen(false)
    }
  }
  const tick = (k: 'event' | 'iv' | 'max_loss' | 'margin') => write({ ...items, [k]: !items[k] })
  const onLoss = (v: string) => {
    setLossText(v)
    if (lossTimer.current) clearTimeout(lossTimer.current)
    lossTimer.current = setTimeout(() => {
      const n = v.trim() === '' ? null : Number(v.replace(/[,\s]/g, ''))
      const maxLoss = n != null && Number.isFinite(n) && n >= 0 ? n : null
      write({ ...items, max_loss_inr: maxLoss, max_loss: maxLoss != null })
    }, 600)
  }
  useEffect(() => () => { if (lossTimer.current) clearTimeout(lossTimer.current) }, [])

  // the payload for the booking's journal note — recomputed on every change, never gating anything
  const remaining = remainingCap(d.settings, d.ev)
  const payloadRef = useRef(onPayload)
  payloadRef.current = onPayload
  useEffect(() => {
    payloadRef.current({
      session: d.session, symbol: sym, ticked: tickedCount(items), total: 4,
      items: { event: items.event, iv: items.iv, max_loss: items.max_loss, margin: items.margin },
      max_loss_inr: items.max_loss_inr, note: checklistNote(items),
      iv30_cm: iv?.iv30 ?? null, iv_pctile_252: iv?.pctile ?? null,
      event_hint: iv?.events.length ? iv.events.map(e => `${e.kind} ${e.date}`).join(' · ') : null,
      margin_total: margin?.total ?? null, margin_source: margin?.source ?? null,
    })
  }, [d.session, sym, items.event, items.iv, items.max_loss, items.margin, items.max_loss_inr, iv, margin])  // eslint-disable-line react-hooks/exhaustive-deps

  const nTicked = tickedCount(items)
  const loss = maxLossLine(items.max_loss_inr, remaining)

  if (!open && nTicked === 4) {
    return (
      <button type="button" data-sd-checklist-collapsed onClick={() => setOpen(true)}
        style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: T.mono, fontSize: 10,
                 letterSpacing: 1, color: T.green, border: `1px solid ${T.green}66`, background: 'transparent',
                 padding: '3px 8px', cursor: 'pointer' }}>
        ✓ CHECKLIST 4/4{doneAt ? ` · ${doneAt}` : ''}
      </button>
    )
  }

  const row = (k: 'event' | 'iv' | 'max_loss' | 'margin', label: string, body: ReactNode) => (
    <div style={{ display: 'grid', gridTemplateColumns: '18px 1fr', gap: 8, alignItems: 'start', padding: '4px 0',
                  borderBottom: `1px dashed ${T.border}` }} data-sd-checklist-item={k}>
      <input type="checkbox" checked={items[k]} onChange={() => tick(k)} aria-label={label} style={{ marginTop: 2 }} />
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 11, color: T.text }}>{label}</div>
        <div style={{ fontSize: 10, color: T.muted, lineHeight: 1.5 }}>{body}</div>
      </div>
    </div>
  )

  return (
    <div data-sd-checklist style={{ border: `1px solid ${T.border}`, background: T.panel2, padding: '8px 10px',
                                    display: 'grid', gap: 4, maxWidth: 420 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <Label color={T.amber}>Pre-trade checklist · {nTicked}/4</Label>
        <BadgeChip badge="heuristic" note="your own routine; it never gates the Book button — an unticked list books with the note 'checklist: n/4'" />
        <span style={{ flex: 1 }} />
        {nTicked === 4 && <Chip color={T.muted} onClick={() => setOpen(false)}>COLLAPSE</Chip>}
      </div>
      {row('event', `Event risk known — any event today/tomorrow for ${sym}?`,
        iv == null ? 'reading the IV event log…'
          : iv.events.length ? iv.events.map(e => `${e.kind} ${e.date}`).join(' · ')
          : 'no upcoming entry in the IV event log — ECO/EVTS have the full calendars')}
      {row('iv', 'IV level seen — IV30 and its percentile read?',
        iv == null ? 'reading…'
          : iv.iv30 != null
            ? <>IV30 {iv.iv30.toFixed(2)}%
                {iv.pctile != null && <span title={iv.defPct ?? 'IV percentile: share of the last year’s days below today'}>{` · ${Math.round(iv.pctile)}th IV percentile (1y)`}</span>}
                {iv.rank != null && <span title={iv.defRank ?? 'IV rank: today’s position in the 1-y min–max range'}>{` · IV rank ${Math.round(iv.rank)}`}</span>}
                {iv.asOf ? ` · as of ${iv.asOf.slice(0, 10)}` : ''}</>
            : 'no stored IV row for this name')}
      {row('max_loss', 'Max loss typed',
        <span>
          <input value={lossText} onChange={e => onLoss(e.target.value)} placeholder="₹" inputMode="numeric" aria-label="max loss in rupees"
            style={{ width: 110, background: '#07090d', color: T.text, border: `1px solid ${T.border}`, fontFamily: T.mono,
                     fontSize: 11, padding: '3px 6px', marginRight: 8 }} />
          <span style={{ color: loss.warn ? T.amber : T.muted }} data-sd-checklist-fit={loss.warn ? 'exceeds' : 'fits'}>{loss.text}</span>
        </span>)}
      {row('margin', 'Margin known',
        margin && margin.total != null
          ? <>{margin.source} · {inr(margin.total)}{margin.asOf ? ` · as of ${margin.asOf.slice(11, 16) || margin.asOf}` : ''} — the tick confirms you read it</>
          : 'the MARGIN block answers BREEZE / NSE SPAN FILE / HEURISTIC — the tick confirms you read it')}
    </div>
  )
}

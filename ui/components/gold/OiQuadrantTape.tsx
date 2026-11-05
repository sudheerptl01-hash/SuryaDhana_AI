'use client'

/**
 * d.quadrant / p.daily.* — the daily OI × price read: a 20-day tape of quadrant labels (long build-up / short
 * build-up / short covering / long unwinding) plus the 4-cell matrix with today's cell marked. Roll/expiry days are
 * greyed (`mechanical`). Context metric, neutral tokens; the caption says "folklore until G-STUDY-2".
 *
 * Wording rules (wave 1c): a session whose ΔOI is not stored reads "no OI for this session" with the reason the caller
 * gives (never "flat" — C-BEGINNER-24, C-DATA-19); "flat" is reserved for two known deltas with a zero; a delta that
 * spans missing sessions is named "Δ over N sessions" (C-TRADER-18) — the server's one-row delta is still printed, but
 * never as one day's move.
 */
import { T } from '@/components/terminal'
import type { QuadrantTapeRow } from '@/lib/gold/types'
import { QUADRANT_READ, istLabel, signed, signedPct, tapeReadout } from './goldViewModel'

const CELL: Record<string, { col: number; row: number; glyph: string }> = {
  'long build-up': { col: 1, row: 0, glyph: '▲▲' },
  'short covering': { col: 0, row: 0, glyph: '▲▼' },
  'short build-up': { col: 1, row: 1, glyph: '▼▲' },
  'long unwinding': { col: 0, row: 1, glyph: '▼▼' },
}

export function OiQuadrantTape({ tape, days = 20, tips, missingOiNote }: {
  tape: QuadrantTapeRow[]; days?: number; tips: (k: string) => string | undefined
  /** why ΔOI can be missing on the newest session (COMEX: "CME file lands T+1 ≈ 15:30 IST"; MCX: the 07:35 master) */
  missingOiNote?: string
}) {
  const rows = tape.slice(-days)
  const all = tape
  const prevOf = (r: QuadrantTapeRow): string | null => { const i = all.indexOf(r); return i > 0 ? all[i - 1].trade_date : null }
  const last = rows[rows.length - 1]
  const lastRead = last ? tapeReadout(last, prevOf(last), missingOiNote) : null
  const lastLabel = lastRead?.label ?? null
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 190px', gap: 12, alignItems: 'start' }}>
      <div>
        <div style={{ fontSize: 10, color: T.muted, marginBottom: 4 }} title={tips('quadrant')}>last {rows.length} sessions · Δprice % over ΔOI · greyed = roll / expiry day (mechanical) · ·· = ΔOI not stored</div>
        <div style={{ display: 'flex', gap: 2, overflowX: 'auto' }} data-quadrant-tape>
          {rows.length === 0 && <span style={{ color: T.dim, fontSize: 11 }}>no history yet — the tape fills from the day the ingest started</span>}
          {rows.map(r => {
            const rd = tapeReadout(r, prevOf(r), missingOiNote)
            const c = rd.label ? CELL[rd.label] : null
            return (
              <div key={r.trade_date} data-tape-sessions={rd.sessions ?? ''}
                title={`${istLabel(r.trade_date)} · ${rd.word}${r.mechanical ? ' · mechanical (roll/expiry)' : ''}${rd.note ? `\n${rd.note}` : ''}\nΔprice ${signedPct(r.dprice_pct)} · ΔOI ${signed(r.doi)}`}
                style={{ minWidth: 30, border: `1px solid ${rd.sessions != null && rd.sessions > 1 ? T.amberDim : T.border}`, padding: '3px 2px', textAlign: 'center', opacity: r.mechanical ? 0.4 : 1,
                         background: c ? (c.row === 0 ? '#0e121a' : '#0a0d13') : 'transparent' }}>
                <div style={{ fontSize: 9, fontFamily: T.mono, color: T.muted }}>{c?.glyph ?? '··'}</div>
                <div style={{ fontSize: 8, color: T.dim }}>{istLabel(r.trade_date).slice(4, 6).trim()}</div>
              </div>
            )
          })}
        </div>
        {last && lastRead && (
          <div style={{ fontSize: 11, color: T.text, marginTop: 6 }} data-tape-last>
            {istLabel(last.trade_date)}: <b style={{ color: T.bright }}>{lastRead.word}</b>
            {lastLabel && <span style={{ color: T.muted }}> — {QUADRANT_READ[lastLabel]}</span>}
            <span style={{ color: T.dim }}> · Δprice {signedPct(last.dprice_pct)} · ΔOI {signed(last.doi)}{last.mechanical ? ' · roll/expiry day' : ''}</span>
            {lastRead.note && <div style={{ fontSize: 10, color: T.amber }}>{lastRead.note}</div>}
          </div>
        )}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '14px 1fr 1fr', gridTemplateRows: '14px 1fr 1fr', gap: 2, fontSize: 9, fontFamily: T.mono }} data-quadrant-matrix>
        <span />
        <span style={{ color: T.dim, textAlign: 'center' }}>OI ▼</span>
        <span style={{ color: T.dim, textAlign: 'center' }}>OI ▲</span>
        <span style={{ color: T.dim, writingMode: 'vertical-rl', transform: 'rotate(180deg)', textAlign: 'center' }}>px ▲</span>
        {(['short covering', 'long build-up'] as const).map(k => <Cell key={k} k={k} on={lastLabel === k} />)}
        <span style={{ color: T.dim, writingMode: 'vertical-rl', transform: 'rotate(180deg)', textAlign: 'center' }}>px ▼</span>
        {(['long unwinding', 'short build-up'] as const).map(k => <Cell key={k} k={k} on={lastLabel === k} />)}
      </div>
    </div>
  )
}

function Cell({ k, on }: { k: string; on: boolean }) {
  return (
    <div title={QUADRANT_READ[k]} style={{ border: `1px solid ${on ? T.muted : T.border}`, background: on ? '#131926' : 'transparent', padding: '6px 4px', textAlign: 'center', color: on ? T.bright : T.muted, lineHeight: 1.3 }}>
      {k}
    </div>
  )
}
